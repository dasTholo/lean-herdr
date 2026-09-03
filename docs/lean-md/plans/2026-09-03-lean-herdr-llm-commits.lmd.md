@lean-md
consumer: ai
crp: compact

@var test_cmd default="uv run pytest -q" desc="project test runner command"
@var lint_cmd default="uv run ruff check ." desc="project lint gate"
@import .lean-ctx/lean-md/plan-recipes /

# lean-herdr — LLM-Commits und billige Vorprüfung

Quelle: `docs/specs/2026-09-03-lean-herdr-llm-commits-design.md` (v1.0). Dieser
Plan ergänzt den Auftragsweg aus
`docs/lean-md/plans/2026-09-03-lean-herdr-auftragslog.lmd.md` und ersetzt nichts
daraus. Render je Task:
`lean-md render docs/lean-md/plans/2026-09-03-lean-herdr-llm-commits.lmd.md --phase task-N`.

## Goal

Ein Modul, zwei Verbraucher. `lean_herdr/llm.py` wird der einzige HTTP-Aufruf des
Projekts: ein kleines Modell über `curl` an OpenRouter. Der erste Verbraucher ist
worktrunk — `bin/herdr-llm generate` wird das `commit.generation.command`, damit
der Builder mit `wt step commit --stage none` echte Conventional-Commit-Messages
schreibt statt `Changes to a.txt`. Der zweite Verbraucher ist der Warte-Modus:
`bin/herdr-dispatch builder --await --prereview` lässt dasselbe Modell über den
Branch-Diff laufen, **bevor** der teure Reviewer gebaut wird, und darf dabei
**ablehnen, aber nie freigeben**.

Beide Teile stehen für sich. Tasks 1–4 liefern den vollständigen Commit-Pfad und
sind ohne die Vorprüfung lauffähig; Tasks 5–7 setzen darauf auf. Die Reihenfolge
ist die der Spec (§1): der Commit-Pfad ist durchgemessen, die Vorprüfung ruht auf
einer geschätzten Effort-Einstellung, die Task 5 zuerst misst.

## Architecture

```
lean_herdr/
  llm.py        NEU  api_key, complete, fallback_message, _first,
                     file_settings, generate                        (Task 1)
                     + wt_diff, prereview, prereview_result         (Task 5)
                     + build_parser, main  (das CLI dahinter)       (Task 2/7)
  settings.py   ~    ROOT_KEYS + "llm"; EFFORTS, LlmSettings,
                     LLM_ALLOWED, llm_settings()                    (Task 1)
  dispatch.py   ~    AwaitRequest.prereview; await_task ruft
                     llm.prereview_result(); Parser + missing_flags  (Task 6)
  worktree.py   ~    unverändert — llm.py importiert nur find_worktree()
  bus.py        ~    unverändert — llm.py importiert canonical_root()
  orderlog.py orders.py ordercmd.py report.py join.py export.py
  handlers.py herdr.py digest.py config.py                unberührt
.config/lean-herdr.toml   ~    ein auskommentierter [llm]-Block
bin/herdr-llm             NEU  dünner Aufruf von lean_herdr.llm.main
bin/herdr-dispatch        unverändert — die Flags leben in dispatch.build_parser()
roles/builder.md          ~    Schritt 3 wird konkret: `wt step commit --stage none`
roles/orchestrator.md     ~    Abbau mit Squash + `--no-commit`; Vorprüfung
.config/wt.toml           ~    [commit.generation] template-append
opencode.jsonc            ~    builder: "wt step commit *": "allow"
.claude/settings.json     ~    "Bash(wt step commit:*)"
README.md                 ~    Operator-Schritte: User-Config, Key, Freigabe
tests/test_llm.py                    NEU  (Task 1, wächst in Task 5)
tests/test_dispatch_prereview.py     NEU  (Task 6)
tests/test_manifest.py               ~    bin/herdr-llm ins Python-Floor-Raster
tests/test_worker_permissions.py     ~    BUILDER_TOOLING + Verbotsliste
```

Der Commit-Pfad:

```
Builder im Worktree:
  git add <die Dateien, die zum Auftrag gehören>
  wt step commit --stage none --yes
    → Prompt rendern (+ <project-guidance> aus .config/wt.toml)
    → sh -c '/abs/pfad/bin/herdr-llm generate'
         stdin: Prompt → curl → OpenRouter → stdout: Message
    → git commit

Orchestrator im Haupt-Checkout, nach verdict=result:
  1. Pfad + workspace_id auflösen, solange der Worktree existiert
  2. wt -C <path> step squash --stage none --yes
  3. herdr workspace close <workspace_id>
  4. wt -C <path> merge main --yes --no-commit
```

Der Vorprüfungs-Pfad:

```
bin/herdr-dispatch builder --await --prereview --task-id o-… --worktree <branch>
  → wartet wie bisher
  → Auftrag steht auf `completed`?
      → find_worktree(herdr.worktree_list(root), branch)
            kein Eintrag / kein `path` → skipped: worktree_unresolved
      → wt -C <path> step diff
      → llm.prereview(order.description, diff)
      → in DIESELBE JSON-Antwort:
          {"ok": true, …, "prereview": "reject", "prereview_note": "…"}
  → jeder andere Zustand: unverändert
```

Gemessene Grundlagen dieses Plans (Spec §2, alle am 2026-09-03 gegen
`wt 0.76.0`, `git 2.55.0`, `curl 8.22.0`):

| Befund | Beleg |
|---|---|
| ohne `[commit.generation]` schreibt worktrunk `Changes to a.txt` | `↳ Using fallback commit message` |
| `reasoning.effort=minimal` kostet $0,000045 statt $0,00115 — gleiche Antwort | 0 Reasoning-Token, wörtlich `fix(parser): add null check` |
| `{"reasoning": {"enabled": false}}` geht **nicht** | *„Reasoning is mandatory for this endpoint and cannot be disabled."* |
| der Agenten-Harness kostet mehr als das Modell | `opencode run`: 17 698 Token; hermetisch `claude -p`: 223 |
| die Aufrufform ist `wt step commit --show-prompt \| sh -c '<command>'` | worktrunk hat sie selbst ausgegeben |
| ein fehlschlagendes Kommando ist **fatal**, kein stiller Rückfall | `✗ Commit generation command failed` `[exit:1]` |
| `--stage none` bei leerem Index: exit 1, **kein Modellaufruf** | `✗ Nothing to commit` |
| `--stage none` committet nur Gestagetes; Untracked bleibt untracked | Messung 2.4 #2 |
| `merge --no-commit` verweigert bei Unfertigem im Worktree | `✗ Cannot merge with --no-commit: probe has uncommitted changes` |
| der pre-merge-Hook läuft auch bei `--no-commit` | `◎ Running pre-merge project:test @ <worktree>`, exit 7 durchgereicht |
| `wt step diff` zeigt committed + staged + unstaged + untracked seit dem Abzweig | `wt step --help` (0.76.0) |
| opencodes Key liegt als `{"openrouter": {"key": …}}` | `~/.local/share/opencode/auth.json` |

## Global Constraints

- **Der Generator blockiert den Builder nie.** `bin/herdr-llm generate` endet
  **immer** mit 0 und schreibt **immer** Text. Kein Key, curl-Fehler, Timeout,
  HTTP ≠ 200, Prompt über der Obergrenze, leere Antwort — jeder Fall ergibt die
  Fallback-Message. Das ist keine Höflichkeit: nach Messung 2.3 bricht ein
  fehlschlagendes Kommando den Commit ab, und der Rückfall auf Dateinamen greift
  nur, wenn **gar kein** Kommando konfiguriert ist.
- **Die Vorprüfung lehnt nie fälschlich ab.** Kein Key, Timeout, unparsbare
  Antwort, leerer Diff, nicht auflösbarer Worktree, Diff über der Obergrenze —
  jeder dieser Fälle ist `skipped` mit Grund, **nie** `reject`. Das Modell darf
  blockieren, seine Infrastruktur nicht.
- **`prereview` steht neben `verdict`, nie an seiner Stelle.** `verdict` gehört
  dem starken Reviewer und dem `VERDIKT:`-Protokoll; ein zweiter Schreiber auf
  demselben Schlüssel wäre genau die Verwechslung, die `VERDICT_RE` verhindert.
  Werte: `pass` | `reject` | `skipped`. **Nur `reject` ändert etwas** — bei `pass`
  und `skipped` verhält sich der Orchestrator exakt wie heute.
- **`_worker_root()` wird für die Vorprüfung ausdrücklich NICHT benutzt.** Die
  Funktion fällt auf den Repo-Root zurück, wenn der Branch sich nicht auflösen
  lässt (`dispatch.py:338-345`) — richtig für ihren Zweck (ein Absturzprotokoll
  auf dem Timeout-Pfad), fatal für diesen: `wt step diff` liefe im Haupt-Checkout
  des Orchestrators, und ein dortiger schmutziger Baum löste ein `reject` auf
  einen **fremden** Diff aus. Die Vorprüfung löst den Pfad selbst über
  `find_worktree()` auf und behandelt „nicht gefunden" als `skipped`.
- **Der Key steht nie in `argv`.** `curl --config <tempfile>` (Modus 0600, im
  `finally` entfernt) trägt `url` und den `Authorization`-Header, der Body geht
  über `--data-binary @<file>`. Ein `-H "Bearer …"` wäre über `ps` für jeden
  Prozess der Maschine lesbar.
- **Kein Test geht ins Netz.** `runner` ist überall injizierbar — exakt das
  Muster aus `worktree.wt_switch()`.
- **Verdikt-Parsing wie beim Reviewer:** erste Zeile, `PREREVIEW: pass|reject`,
  alles andere → `skipped`. Erste Zeile allein, damit dieselben Worte in der
  Begründung das Urteil nicht kippen können — wörtlich die Begründung, die
  `dispatch.verdict()` schon trägt.
- **Der Pfad in der worktrunk-User-Config ist absolut.** Die Datei gilt
  maschinenweit; ein relatives `bin/herdr-llm generate` liefe in jedem anderen
  Repository in `sh: not found` (exit 127) — und das ist nach 2.3 fatal. Der
  Generator ist repo-agnostisch, er formatiert nur, was auf stdin ankommt.
- **Dateigröße:** kein `lean_herdr/`-Modul über 800 produktive LOC (Ziel 600).
  `dispatch.py` steht bei **762 physischen** Zeilen — das ist NICHT das Maß der
  Regel. Task 6 misst nach und meldet das Ergebnis, statt es zu schätzen.
  Reißt die Grenze, wandert **nicht** die Grenze, sondern `build_parser()` /
  `missing_flags()` / `main()` nach `lean_herdr/dispatchcli.py` — derselbe
  Schnitt, den `ordercmd.py` schon einmal bekommen hat.

  **Betreiber-Entscheidung vom 2026-09-03, nachdem Task 6 gemessen hat:**
  produktive LOC sind das Maß (physische Zeilen minus Leerzeilen, Kommentare,
  Docstrings) — so, wie AGENTS.md es immer gemeint hat. Gemessen: `dispatch.py`
  815 physisch / **537 produktiv**, `llm.py` 648 / **334**. Beide liegen unter
  dem Ziel von 600; **der Schnitt nach `dispatchcli.py` entfällt.** Zur
  Einordnung: der historische `ordercmd.py`-Schnitt geschah bei 574 physisch /
  371 produktiv — `dispatch.py` hat 800 nach keinem der beiden Maße je
  überschritten, anders als sein eigener Kommentar behauptete.
- **Non-Goals** (Ablehnungsgrund im Review, kein Versäumnis): kein eigenes
  Commit-Template (worktrunk rendert, wir hängen nur `template-append` an); kein
  blockierendes Modell-Urteil vor dem Merge (der pre-merge-Hook bleibt das Tor);
  keine Freigabe durch das kleine Modell (`pass` ist kein `result`, der starke
  Reviewer läuft immer); kein Wrapper-Skript um `wt`; keine Korrektur von
  `list.json-schema`; **keine Änderung an** `_result_for_state()`,
  `session_error()`, `bus.py`, `worktree.py`, `join.py`, `export.py`,
  `handlers.py`, `herdr.py`, `orderlog.py`, `orders.py`.
- **Aufgehobenes Non-Goal, auf Betreiberanordnung vom 2026-09-03** — ein Review
  meldet das NICHT als Abweichung: Spec §9 verbot Konfiguration in
  `.config/lean-herdr.toml` und wollte `settings.py` unberührt lassen. Der
  Betreiber hat entschieden, dass Modell und Effort dort konfigurierbar sein
  sollen — über `settings.SETTINGS_PATH`, das die Datei bereits kennt. Task 1
  setzt das um. Zwei Folgen, die niemand übersehen darf:
  (a) `_check_root()` lässt am Top-Level heute nur `default` und `roles` zu; ein
  `[llm]`-Block bräche ohne die `ROOT_KEYS`-Erweiterung **jeden**
  `bin/herdr-dispatch`-Aufruf mit `config_error:`. Die Erweiterung geht dem
  Rest voraus.
  (b) `bin/herdr-llm generate` läuft in **jedem** Repository der Maschine. Eine
  kaputte oder fehlende Konfigurationsdatei darf dort nichts kosten außer den
  Vorgabewerten — `llm.file_settings()` fängt `SettingsError`, `BusError` und
  `OSError` und meldet den Grund auf stderr. `bin/herdr-dispatch` lässt denselben
  Fehler dagegen als `config_error:` durch: dort hat er einen Leser.
  Was **bleibt**: `RoleSettings` wird nicht angefasst, und `[llm]` ist ein Block
  für sich, den nur `llm.py` liest.
- **Zweite bewusste Abweichung von der Spec** — ein Review meldet sie NICHT als
  Befund: Spec §9 nennt nur `$LEAN_HERDR_LLM_MODEL`. Der Plan gibt der Vorprüfung
  mit `$LEAN_HERDR_PREREVIEW_MODEL` und `[llm].prereview_model` **eigene** Ebenen.
  Grund: eine gemeinsame Einstellung bedient beide Verbraucher, und wer den
  Richter auf ein stärkeres Modell heben wollte, hätte damit auch den
  Commit-Generator gehoben — für jeden einzelnen Commit.
- **DIE ZWEI KETTEN, einmal und maßgeblich.** Fünf Stellen beschreiben sie (der
  Konstanten-Kommentar in `llm.py`, `.config/lean-herdr.toml`, die
  `argparse`-Hilfetexte, und die README an zwei Stellen). Alle fünf geben
  **das** hier wieder:

      generate()  model:   --model  >  $LEAN_HERDR_LLM_MODEL  >  [llm].model
                           >  DEFAULT_MODEL
      generate()  effort:  --effort  >  [llm].effort  >  GENERATE_EFFORT

      prereview() model:   --model  >  $LEAN_HERDR_PREREVIEW_MODEL
                           >  [llm].prereview_model  >  $LEAN_HERDR_LLM_MODEL
                           >  [llm].model  >  DEFAULT_MODEL
      prereview() effort:  --effort  >  [llm].prereview_effort
                           >  PREREVIEW_EFFORT

  Drei Dinge daran sind Absicht und keine Lücke: **der Effort hat keine
  Umgebungsebene** (Flag und Datei genügen für vier Werte); **`prereview_effort`
  fällt NICHT auf `[llm].effort` zurück** (das ist das `minimal` des
  Commit-Generators, und es zu erben machte den Richter still ebenso
  gedankenlos wie den Formatierer); und **die Umgebung steht über der Datei**
  (sie ist der Griff in einer laufenden Pane, ohne eine Datei anzufassen, die
  jedes Repository dieser Maschine liest).

  **Was „wiedergeben" heißt — Betreiber-Entscheidung vom 2026-09-03**, sie
  ersetzt die frühere Forderung nach wörtlichem Abschreiben: **Ebenen und
  Reihenfolge sind überall exakt dieselben, die Benennung folgt der jeweiligen
  Umgebung.** Innerhalb der `[llm]`-Tabelle heißt der Schlüssel `model`, nicht
  `[llm].model`; für den Operator heißt der Boden `built-in`, nicht
  `DEFAULT_MODEL`; in den `argparse`-Hilfetexten stehen die Flagnamen, wie
  `argparse` sie schreibt. Ein Review-Befund ist deshalb **nur**, wenn eine
  Ebene fehlt, eine dazukommt oder die Reihenfolge abweicht — nicht, wenn ein
  Name der Umgebung angepasst ist. Der `[llm]`-Block, den Task 1 geliefert hat,
  ist die Vorlage für diese Anpassung und bleibt, wie er ist.
- **Sprachtor:** `tests/test_language.py` greift für die neuen Dateien
  automatisch — alles außerhalb `docs/` ist Englisch, `roles/*.md` und
  `README.md` eingeschlossen.
- **Reihenfolge:** Task 2 setzt 1 voraus · Task 3 setzt 2 voraus (der Rollentext
  beschreibt ein Kommando, das laufen muss) · Task 4 ist von 1–3 unabhängig, aber
  gehört zum Commit-Pfad · Task 5 setzt 1 voraus · Task 6 setzt 5 voraus · Task 7
  setzt 5+6 voraus.

@phase "task-1"
## Task 1: `lean_herdr/llm.py` — der HTTP-Aufruf, die Konfiguration, der Generator

**Files:** Create `lean_herdr/llm.py`, `tests/test_llm.py`. Modify
`lean_herdr/settings.py`, `.config/lean-herdr.toml`, `tests/test_settings.py`.
**Interfaces:** Produces `lean_herdr.settings.EFFORTS`, `LlmSettings`
(`model`/`prereview_model`/`effort`/`prereview_effort`, alle `str = ""`),
`LLM_ALLOWED`, `llm_settings(data=None) -> LlmSettings`; und
`lean_herdr.llm.DEFAULT_MODEL`, `MODEL_ENV`, `KEY_ENV`, `ENDPOINT`, `AUTH_PATH`,
`MAX_PROMPT_BYTES`, `GENERATE_TIMEOUT_S`, `GENERATE_EFFORT`,
`api_key(env=None, auth_path=None) -> str | None`,
`complete(prompt, *, effort, model=DEFAULT_MODEL, timeout_s=…, runner=…,
env=None, auth_path=None) -> str | None`, `fallback_message(prompt) -> str`,
`_first(*candidates, fallback) -> str`,
`file_settings(root=None, *, cwd=None) -> LlmSettings`,
`generate(prompt, *, model=None, effort=None, timeout_s=…, runner=…, env=None,
auth_path=None, settings=None) -> str`.
**Consumes:** `lean_herdr.settings.{SETTINGS_PATH, read_settings, SettingsError}`,
`lean_herdr.bus.{canonical_root, BusError}`, sonst die Standardbibliothek. Kein
Eintrag in `herdr-plugin.toml` — das Modul ist eine Bibliothek, kein
Plugin-Handler.

### Zuerst: `[llm]` in `lean_herdr/settings.py`

`_check_root()` (`settings.py:139-161`) lässt am Top-Level **nur** `default` und
`roles` zu und wirft für alles andere `SettingsError`. Ein `[llm]`-Block in
`.config/lean-herdr.toml` würde deshalb heute **jeden** `bin/herdr-dispatch`-Aufruf
mit `config_error:` scheitern lassen — nicht nur die neuen. Der Schlüssel muss
also zuerst erlaubt werden, sonst bricht dieser Task den bestehenden Auftragsweg.

@call patch("lean_herdr/settings.py", "ROOT_KEYS und das Ende der Datei")

`ROOT_KEYS` bekommt einen dritten Eintrag:

    #: The only three keys the top level of the file may carry.
    ROOT_KEYS = ("default", "roles", "llm")

Und ans Ende der Datei, hinter `settings_for()`:

    #: OpenRouter's reasoning levels. A typo would otherwise reach the
    #: endpoint verbatim, come back as an HTTP error, and be swallowed into
    #: a fallback commit message -- a wrong value that looks exactly like a
    #: missing key.
    EFFORTS = ("minimal", "low", "medium", "high")


    @dataclass(frozen=True)
    class LlmSettings:
        """`[llm]` -- the commit generator and the pre-review judge.

        Deliberately NOT part of RoleSettings. Those describe how a pane is
        split and what a worker is called, and dispatch.py reads every one
        of them. These four are read by llm.py alone -- and by a process
        worktrunk starts in repositories this project does not own.

        The empty string means "not set", so the resolution chain in llm.py
        stays a plain first-non-empty. `None` would need a second spelling
        for the same state and a second check at every level.
        """

        model: str = ""
        prereview_model: str = ""
        effort: str = ""
        prereview_effort: str = ""


    LLM_ALLOWED = frozenset(f.name for f in fields(LlmSettings))


    def llm_settings(data: dict[str, Any] | None = None) -> LlmSettings:
        """`[llm]` out of the settings file. No section: every default.

        Same strictness as settings_for(): an unknown key, a wrong type or
        an effort level OpenRouter does not know is a SettingsError, never a
        silent fallback. Whoever writes `effort = "mininal"` must not go
        hunting for the bug in the model.

        Note who catches it, because the two consumers differ on purpose:
        `llm.file_settings()` swallows this and takes the defaults -- it
        serves `bin/herdr-llm generate`, where a raise would abort the
        commit worktrunk is in the middle of. `dispatch.main()` calls this
        function directly and lets it through as `config_error:` -- there
        the orchestrator reads the complaint. Without that second call site
        a typo in `[llm]` would be silent everywhere.
        """
        table = _check_root({} if data is None else data)
        block = table.get("llm")
        if block is None:
            return LlmSettings()
        if not isinstance(block, dict):
            raise SettingsError(
                f"llm: section is not a table, but {type(block).__name__}"
            )
        unknown = sorted(set(block) - LLM_ALLOWED)
        if unknown:
            raise SettingsError(
                f"llm: unknown keys {unknown}; allowed: {sorted(LLM_ALLOWED)}"
            )
        for key, value in block.items():
            if not isinstance(value, str):
                raise SettingsError(
                    f"llm.{key}: {value!r} is {type(value).__name__}, not str"
                )
        values = LlmSettings(**block)
        for key in ("effort", "prereview_effort"):
            level = getattr(values, key)
            if level and level not in EFFORTS:
                raise SettingsError(f"llm.{key}={level!r}, allowed: {list(EFFORTS)}")
        return values

### Dann: der Code

`lean_herdr/llm.py` (neu):

    """The one HTTP call in this project: a small model, over curl.

    Two consumers, one module. `generate()` turns worktrunk's rendered
    commit prompt into a commit message -- it IS the
    `commit.generation.command`. `prereview()` runs the same model over a
    branch diff before the expensive reviewer is built. Both go through
    `complete()`, and `complete()` is the only place that talks to the
    network.

    `runner` is injectable throughout -- the pattern from
    `worktree.wt_switch()`. No test in this repository reaches the
    network.

    Stdlib plus `worktree.find_worktree()` from task 5 on, and no entry in
    herdr-plugin.toml: this is a library and
    a CLI, not a plugin handler.
    """

    from __future__ import annotations

    import json
    import os
    import re
    import subprocess
    import sys
    import tempfile
    from pathlib import Path
    from typing import Any

    from lean_herdr.bus import BusError, canonical_root
    from lean_herdr.settings import (
        SETTINGS_PATH,
        LlmSettings,
        SettingsError,
        llm_settings,
        read_settings,
    )

`argparse` is deliberately NOT imported here — task 2 adds it together with the
CLI that uses it. Importing it one task early is an F401 under this project's
ruff defaults, and this task's own gate would fail on it. `sys` IS used here:
`file_settings()` writes its reason to stderr.

The module is therefore not stdlib-only: it reads the project's settings file
through the module that owns that file, and resolves the repo root through the
one function the whole project resolves it with (`canonical_root()`, B12). A
second reader or a second `git rev-parse` would be exactly the two-truths bug
this codebase keeps catching.

    #: OpenRouter's slug for the model measured in the design (spec 2.2).
    #: The floor of the chain, never the decision: `[llm]` in
    #: .config/lean-herdr.toml, `$LEAN_HERDR_LLM_MODEL` and the CLI flag all
    #: beat it, in that rising order. See the precedence block below.
    DEFAULT_MODEL = "google/gemini-3.8-flash"
    MODEL_ENV = "LEAN_HERDR_LLM_MODEL"
    KEY_ENV = "OPENROUTER_API_KEY"
    ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

    #: opencode's credential store, read only when $OPENROUTER_API_KEY is
    #: absent. Shape verified: {"openrouter": {"key": ..., "type": ...}}.
    AUTH_PATH = Path.home() / ".local/share/opencode/auth.json"

    #: Above this the call is not made at all. A runaway diff would cost
    #: real money for an answer nobody can use, and the fallback is free.
    MAX_PROMPT_BYTES = 200_000

    GENERATE_TIMEOUT_S = 20.0

    #: `{"reasoning": {"enabled": false}}` is REFUSED by this endpoint
    #: ("Reasoning is mandatory for this endpoint and cannot be
    #: disabled."); `effort` is not. `minimal` measured at 0 reasoning
    #: tokens, 26x cheaper, and a byte-identical answer (spec 2.2).
    GENERATE_EFFORT = "minimal"

    #: worktrunk's prompt carries the diffstat in this block. The fallback
    #: reads the file names out of it instead of starting a `git`
    #: subprocess on the error path -- the error path is the one place
    #: that must not have a second way to fail.
    DIFFSTAT_RE = re.compile(r"<diffstat>(.*?)</diffstat>", re.DOTALL)
    FALLBACK_FILES = 3


    def api_key(env: Any = None, auth_path: Any = None) -> str | None:
        """`$OPENROUTER_API_KEY`, else opencode's store, else None.

        None is not an error here. Every caller answers it with a safe
        behaviour of its own -- a fallback message, a skipped pre-review --
        never with an exception. A missing key must not break a commit.
        """
        environ = os.environ if env is None else env
        key = (environ.get(KEY_ENV) or "").strip()
        if key:
            return key
        path = AUTH_PATH if auth_path is None else Path(auth_path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        entry = data.get("openrouter") if isinstance(data, dict) else None
        stored = entry.get("key") if isinstance(entry, dict) else None
        if not isinstance(stored, str) or not stored.strip():
            return None
        return stored.strip()


    def _tempfile(text: str) -> Path:
        """A 0600 file with `text` in it. The caller removes it."""
        handle, name = tempfile.mkstemp(prefix="herdr-llm-")
        path = Path(name)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(text)
        except OSError:
            path.unlink(missing_ok=True)
            raise
        # mkstemp already creates 0600; set it anyway, so the guarantee
        # this function makes does not depend on a platform default.
        path.chmod(0o600)
        return path


    def _unfence(text: str) -> str:
        """Strip a markdown fence the model wrapped its answer in.

        Asked for one line it still sometimes answers ```\nfix(x): y\n```.
        Stripping it here keeps both callers from doing it twice.
        """
        lines = text.strip().splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
        return "\n".join(lines).strip()


    def _content(stdout: str) -> str | None:
        """`.choices[0].message.content`, unfenced -- or None.

        Every shape that is not exactly that is None, not an exception:
        an error body, a rate-limit page, an empty string. The caller
        cannot tell those apart and does not need to.
        """
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return None
        choices = data.get("choices") if isinstance(data, dict) else None
        first = choices[0] if isinstance(choices, list) and choices else None
        message = first.get("message") if isinstance(first, dict) else None
        text = message.get("content") if isinstance(message, dict) else None
        if not isinstance(text, str):
            return None
        return _unfence(text) or None


    def complete(
        prompt: str,
        *,
        effort: str,
        model: str = DEFAULT_MODEL,
        timeout_s: float = GENERATE_TIMEOUT_S,
        runner: Any = subprocess.run,
        env: Any = None,
        auth_path: Any = None,
    ) -> str | None:
        """One completion, or None. Never raises, never blocks forever.

        None means "no usable answer" for every reason there is: no key, a
        prompt over the cap, curl failing, a non-zero exit, a body we
        cannot parse, an empty string. The callers turn that into their
        own safe behaviour. A raise here would reach worktrunk as a failed
        generation command, and a failed command is fatal (spec 2.3).

        The key never reaches `argv`. `curl --config <file>` carries the
        url and the Authorization header, mode 0600, removed in the
        `finally`. `-H "Bearer ..."` on the command line is readable via
        `ps` for every process on the machine -- in a multiplexer full of
        agents that is not a theoretical concern.
        """
        environ = os.environ if env is None else env
        if len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
            return None
        key = api_key(environ, auth_path)
        # NOTE: this function resolves NOTHING but the key. Model and effort
        # arrive decided -- `_first()` at the call site is the one precedence
        # rule, and a second chain here would drift from it (M3).
        # A key with a quote, a backslash or a newline in it cannot go
        # into a curl config line without changing what that line means.
        # Refusing is right: no real OpenRouter key looks like this, and a
        # header we assembled wrong is worse than no call at all.
        if not key or any(char in key for char in '"\\\n\r'):
            return None
        body = json.dumps(
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "reasoning": {"effort": effort},
            }
        )
        config: Path | None = None
        payload: Path | None = None
        try:
            config = _tempfile(
                f'url = "{ENDPOINT}"\n'
                f'header = "Authorization: Bearer {key}"\n'
                'header = "Content-Type: application/json"\n'
                # Der float, wie er ist: curl nimmt Bruchteile von Sekunden,
                # und `max-time = 0` -- was int() aus allem unter einer
                # Sekunde macht -- heisst bei curl GAR KEIN Limit.
                f"max-time = {timeout_s}\n"
            )
            payload = _tempfile(body)
            proc = runner(
                ["curl", "-sS", "--config", str(config), "--data-binary", f"@{payload}"],
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        finally:
            for path in (config, payload):
                if path is not None:
                    path.unlink(missing_ok=True)
        if proc.returncode != 0:
            return None
        return _content(proc.stdout)


    def _files_from_diffstat(block: str) -> list[str]:
        """The names out of a `git diff --stat` block: ` a.txt | 1 +`."""
        names = []
        for line in block.splitlines():
            head, sep, _rest = line.partition("|")
            name = head.strip()
            if sep and name:
                names.append(name)
        return names


    def fallback_message(prompt: str) -> str:
        """worktrunk's own wording, rebuilt from the prompt it just sent.

        With no command configured worktrunk writes `Changes to a.txt`
        (measured, spec 2.1). Saying the same thing means an operator
        reading `git log` cannot tell a missing key from a missing
        configuration -- and neither state is a lie about the commit.
        """
        hit = DIFFSTAT_RE.search(prompt)
        names = _files_from_diffstat(hit.group(1) if hit else "")
        if not names:
            return "Changes to the working tree"
        shown = ", ".join(names[:FALLBACK_FILES])
        rest = len(names) - FALLBACK_FILES
        return f"Changes to {shown}" + (f" and {rest} more" if rest > 0 else "")


    def _first(*candidates: str | None, fallback: str) -> str:
        """The first non-empty candidate -- the ONE precedence rule.

        One function instead of an `or`-chain per caller: two spellings of
        the same precedence drift apart the day somebody inserts a level.
        The ORDER stays visible at each call site, because that is the part
        that actually differs between the generator and the judge.
        """
        return next((c for c in candidates if c), fallback)


    def file_settings(root: Any = None, *, cwd: Any = None) -> LlmSettings:
        """`[llm]` from `<repo root>/.config/lean-herdr.toml` -- NEVER raises.

        Never, and that is the whole reason this wrapper exists next to
        `settings.llm_settings()`. worktrunk starts `bin/herdr-llm generate`
        in EVERY repository on the machine, and a failing generation command
        aborts the commit (spec 2.3). A missing file, a directory that is
        not a repository, a broken TOML and a bad value therefore all cost
        the built-in defaults -- never the commit. The reason goes to
        stderr, where an operator sees it without the commit paying for it.

        `SETTINGS_PATH` is relative and gets joined onto the repo root, not
        onto $PWD: the generator runs in the builder's worktree, and a
        `.config/` lookup from there would miss (settings.py:20-24).

        `root` is handed in by callers that resolved it already -- the wait
        mode has it. Without it this asks git once, per process.
        """
        try:
            base = Path(root) if root is not None else canonical_root(cwd)
            return llm_settings(read_settings(base / SETTINGS_PATH))
        except (SettingsError, BusError, OSError, subprocess.SubprocessError) as exc:
            # SubprocessError is NOT redundant beside OSError: canonical_root()
            # runs git with a timeout, and subprocess.TimeoutExpired descends
            # from SubprocessError, not from OSError. A hung git would
            # otherwise walk straight out of the manual `prereview` mode,
            # which has no blanket except around it.
            print(f"herdr-llm: ignoring the settings file: {exc}", file=sys.stderr)
            return LlmSettings()


    def generate(
        prompt: str,
        *,
        model: str | None = None,
        effort: str | None = None,
        timeout_s: float = GENERATE_TIMEOUT_S,
        runner: Any = subprocess.run,
        env: Any = None,
        auth_path: Any = None,
        settings: LlmSettings | None = None,
    ) -> str:
        """A commit message, always. Never empty, never an exception.

        worktrunk treats a failing generation command as fatal -- `✗ Commit
        generation command failed`, and the commit does not happen (spec
        2.3). Its own fallback to file names applies only when NO command
        is configured. So this function has exactly one contract: text
        out, whatever went wrong.

        Resolution, in this order: the explicit argument (the CLI flag),
        then the environment, then `[llm]` in the settings file, then the
        built-in constant. The environment sits ABOVE the file on purpose:
        it is the grip an operator has inside a running pane, without
        editing a file that every repository on this machine reads. The
        effort has no environment level -- a CLI flag and the file are
        enough, and a third spelling for a four-value enum is clutter.
        """
        environ = os.environ if env is None else env
        cfg = file_settings() if settings is None else settings
        answer = complete(
            prompt,
            effort=_first(effort, cfg.effort, fallback=GENERATE_EFFORT),
            model=_first(
                model, environ.get(MODEL_ENV), cfg.model, fallback=DEFAULT_MODEL
            ),
            timeout_s=timeout_s,
            runner=runner,
            env=env,
            auth_path=auth_path,
        )
        return answer or fallback_message(prompt)

### Die Tests

`tests/test_llm.py` (neu):

    """The one network call in this tree -- and not one test reaches it.

    `runner` is injected everywhere; `SpyRunner` reads the curl config
    while curl would be running, which is the only moment the file still
    exists.
    """

    import json
    import os
    from pathlib import Path

    import pytest

    from lean_herdr import llm
    from lean_herdr.settings import LlmSettings
    from tests.doubles import Completed

    #: Every generate() call in here passes `settings=` explicitly. Without
    #: it generate() calls file_settings(), which runs `git rev-parse` and
    #: reads THIS repository's own .config/lean-herdr.toml -- a unit test
    #: that quietly depends on the checkout it runs in.
    NO_FILE = LlmSettings()

    DIFFSTAT_PROMPT = """<task>write a commit message</task>
    <diffstat>
     lean_herdr/llm.py  | 42 ++++++++++
     tests/test_llm.py  | 18 +++++
     2 files changed, 60 insertions(+)
    </diffstat>
    <diff>...</diff>
    """


    def answer(text: str) -> dict:
        return {"choices": [{"message": {"content": text}}]}


    class SpyRunner:
        """Replaces subprocess.run and inspects the temp files in flight.

        The interesting facts about the call -- the key is not in argv,
        the config is 0600, both files are gone afterwards -- can only be
        checked from inside the call, because the `finally` removes them
        the moment it returns.
        """

        def __init__(self, reply=None, returncode=0, raises=None):
            self.calls: list[list[str]] = []
            self.config_texts: list[str] = []
            self.config_modes: list[int] = []
            self.bodies: list[str] = []
            self.paths: list[Path] = []
            self.reply = reply
            self.returncode = returncode
            self.raises = raises

        def __call__(self, cmd, **kwargs):
            self.calls.append(list(cmd))
            # Only a curl call carries these. The same double also stands in
            # for `wt step diff` in task 5, and reaching for --config there
            # would raise a ValueError the code under test does not catch.
            if "--config" in cmd:
                config = Path(cmd[cmd.index("--config") + 1])
                body = Path(cmd[cmd.index("--data-binary") + 1].removeprefix("@"))
                self.paths.extend((config, body))
                self.config_texts.append(config.read_text(encoding="utf-8"))
                self.config_modes.append(config.stat().st_mode & 0o777)
                self.bodies.append(body.read_text(encoding="utf-8"))
            if self.raises is not None:
                raise self.raises
            out = "" if self.reply is None else json.dumps(self.reply)
            return Completed(returncode=self.returncode, stdout=out)


    @pytest.fixture
    def no_store(tmp_path):
        """An auth.json that does not exist -- the empty-machine case."""
        return tmp_path / "absent" / "auth.json"


    def test_the_env_key_beats_the_opencode_store(tmp_path):
        store = tmp_path / "auth.json"
        store.write_text(json.dumps({"openrouter": {"key": "from-store"}}))
        assert llm.api_key({llm.KEY_ENV: "from-env"}, store) == "from-env"


    def test_the_store_answers_when_the_env_is_empty(tmp_path):
        store = tmp_path / "auth.json"
        store.write_text(json.dumps({"openrouter": {"key": "from-store"}}))
        assert llm.api_key({}, store) == "from-store"
        assert llm.api_key({llm.KEY_ENV: "   "}, store) == "from-store"


    def test_no_key_anywhere_is_none_not_a_crash(no_store):
        assert llm.api_key({}, no_store) is None


    def test_a_malformed_store_is_none_not_a_crash(tmp_path):
        store = tmp_path / "auth.json"
        store.write_text("{ not json")
        assert llm.api_key({}, store) is None
        store.write_text(json.dumps({"openrouter": "a string"}))
        assert llm.api_key({}, store) is None


    def test_the_key_never_reaches_argv(no_store):
        spy = SpyRunner(answer("feat(x): y"))
        llm.complete(
            "prompt", effort="minimal", runner=spy,
            env={llm.KEY_ENV: "sk-secret-42"}, auth_path=no_store,
        )
        flat = " ".join(spy.calls[0])
        assert "sk-secret-42" not in flat, flat
        assert "Bearer" not in flat, flat
        assert "sk-secret-42" in spy.config_texts[0]


    def test_the_config_file_is_0600_and_gone_afterwards(no_store):
        spy = SpyRunner(answer("feat(x): y"))
        llm.complete(
            "prompt", effort="minimal", runner=spy,
            env={llm.KEY_ENV: "sk-secret-42"}, auth_path=no_store,
        )
        assert spy.config_modes == [0o600]
        for path in spy.paths:
            assert not path.exists(), f"{path} was left behind"


    def test_the_body_carries_model_and_effort(no_store):
        """complete() resolves nothing -- it sends what it is handed."""
        spy = SpyRunner(answer("feat(x): y"))
        llm.complete(
            "prompt", effort="minimal", model="some/other-model", runner=spy,
            env={llm.KEY_ENV: "k"}, auth_path=no_store,
        )
        body = json.loads(spy.bodies[0])
        assert body["model"] == "some/other-model"
        assert body["reasoning"] == {"effort": "minimal"}
        assert body["messages"] == [{"role": "user", "content": "prompt"}]


    def test_the_precedence_runs_flag_environment_file_constant(no_store):
        """One test for the whole chain, so a reordering cannot hide."""
        cfg = LlmSettings(model="file/model", effort="medium")
        env = {llm.KEY_ENV: "k", llm.MODEL_ENV: "env/model"}

        def sent(**kw):
            spy = SpyRunner(answer("feat(x): y"))
            llm.generate(
                "prompt", runner=spy, env=env, auth_path=no_store,
                settings=cfg, **kw,
            )
            return json.loads(spy.bodies[0])

        assert sent(model="flag/model")["model"] == "flag/model"
        assert sent()["model"] == "env/model", "the environment beats the file"
        assert sent(effort="low")["reasoning"] == {"effort": "low"}
        assert sent()["reasoning"] == {"effort": "medium"}, "the file beats the constant"


    def test_without_a_file_and_without_an_environment_the_constants_win(no_store):
        spy = SpyRunner(answer("feat(x): y"))
        llm.generate(
            "prompt", runner=spy, env={llm.KEY_ENV: "k"}, auth_path=no_store,
            settings=LlmSettings(),
        )
        body = json.loads(spy.bodies[0])
        assert body["model"] == llm.DEFAULT_MODEL
        assert body["reasoning"] == {"effort": llm.GENERATE_EFFORT}


    def test_the_first_non_empty_candidate_wins():
        assert llm._first(None, "", "third", fallback="f") == "third"
        assert llm._first(None, "", fallback="f") == "f"


    def test_a_broken_settings_file_costs_the_defaults_not_the_commit(tmp_path, capsys):
        """The hard invariant, at the one place that could break it."""
        (tmp_path / ".config").mkdir()
        (tmp_path / ".config" / "lean-herdr.toml").write_text(
            "[llm]\nmodel = 5\n", encoding="utf-8"
        )
        assert llm.file_settings(tmp_path) == LlmSettings()
        assert "ignoring the settings file" in capsys.readouterr().err


    def test_a_directory_that_is_no_repository_costs_the_defaults(tmp_path, capsys):
        assert llm.file_settings(cwd=tmp_path) == LlmSettings()
        assert "ignoring the settings file" in capsys.readouterr().err


    def test_a_missing_file_is_the_normal_case_and_says_nothing(tmp_path, capsys):
        assert llm.file_settings(tmp_path) == LlmSettings()
        assert capsys.readouterr().err == "", "an absent file is not a complaint"


    def test_the_file_is_read_relative_to_the_repo_root(tmp_path):
        (tmp_path / ".config").mkdir()
        (tmp_path / ".config" / "lean-herdr.toml").write_text(
            '[llm]\nmodel = "from/file"\nprereview_effort = "medium"\n',
            encoding="utf-8",
        )
        got = llm.file_settings(tmp_path)
        assert got.model == "from/file"
        assert got.prereview_effort == "medium"
        assert got.effort == "", "an unset key stays the empty string"


    def test_a_fenced_answer_loses_its_fence(no_store):
        spy = SpyRunner(answer("```\nfix(parser): add null check\n```"))
        got = llm.complete(
            "prompt", effort="minimal", runner=spy,
            env={llm.KEY_ENV: "k"}, auth_path=no_store,
        )
        assert got == "fix(parser): add null check"


    def test_the_fallback_reads_the_files_out_of_the_diffstat():
        assert llm.fallback_message(DIFFSTAT_PROMPT) == (
            "Changes to lean_herdr/llm.py, tests/test_llm.py"
        )


    def test_the_fallback_caps_the_file_list():
        stat = "\n".join(f" f{n}.py | 1 +" for n in range(6))
        prompt = f"<diffstat>\n{stat}\n</diffstat>"
        assert llm.fallback_message(prompt) == (
            "Changes to f0.py, f1.py, f2.py and 3 more"
        )


    def test_the_fallback_survives_a_prompt_with_no_diffstat():
        assert llm.fallback_message("nothing useful here") == (
            "Changes to the working tree"
        )


    @pytest.mark.parametrize(
        "spy",
        [
            SpyRunner(answer("x"), returncode=7),
            SpyRunner(reply={"error": {"message": "rate limited"}}),
            SpyRunner(answer("   ")),
            SpyRunner(raises=OSError("curl is not installed")),
        ],
        ids=["curl-failed", "error-body", "empty-answer", "no-curl"],
    )
    def test_generate_returns_the_fallback_for_every_failure(spy, no_store):
        got = llm.generate(
            DIFFSTAT_PROMPT, runner=spy, settings=NO_FILE,
            env={llm.KEY_ENV: "k"}, auth_path=no_store,
        )
        assert got == "Changes to lean_herdr/llm.py, tests/test_llm.py"


    def test_generate_without_a_key_never_calls_curl(no_store):
        spy = SpyRunner(answer("feat(x): y"))
        got = llm.generate(
            DIFFSTAT_PROMPT, runner=spy, env={}, auth_path=no_store, settings=NO_FILE
        )
        assert spy.calls == []
        assert got.startswith("Changes to ")


    def test_a_prompt_over_the_cap_is_never_sent(no_store):
        spy = SpyRunner(answer("feat(x): y"))
        huge = "x" * (llm.MAX_PROMPT_BYTES + 1)
        assert llm.complete(
            huge, effort="minimal", runner=spy,
            env={llm.KEY_ENV: "k"}, auth_path=no_store,
        ) is None
        assert spy.calls == [], "a runaway diff must not cost money"


    def test_a_key_that_would_break_the_config_line_is_refused(no_store):
        spy = SpyRunner(answer("feat(x): y"))
        assert llm.complete(
            "prompt", effort="minimal", runner=spy,
            env={llm.KEY_ENV: 'k"\nheader = "X-Evil: 1'}, auth_path=no_store,
        ) is None
        assert spy.calls == []


    def test_generate_passes_the_measured_effort_by_default(no_store):
        spy = SpyRunner(answer("feat(x): y"))
        llm.generate(
            "prompt", runner=spy, env={llm.KEY_ENV: "k"}, auth_path=no_store,
            settings=NO_FILE,
        )
        assert json.loads(spy.bodies[0])["reasoning"] == {"effort": "minimal"}

### Die Tests für `[llm]`

An `tests/test_settings.py` anhängen — dort, wo die Strenge dieses Moduls schon
bewacht wird:

    def test_the_llm_section_is_read_and_defaults_to_empty():
        from lean_herdr.settings import LlmSettings, llm_settings

        assert llm_settings({}) == LlmSettings()
        assert llm_settings({"llm": {"model": "a/b"}}).model == "a/b"
        assert llm_settings({"llm": {"prereview_effort": "medium"}}).effort == ""


    def test_the_llm_section_no_longer_breaks_the_whole_file():
        """Before this task `[llm]` made EVERY herdr-dispatch call fail."""
        from lean_herdr.settings import settings_for

        assert settings_for("builder", {"llm": {"model": "a/b"}}).profile == "standard"


    @pytest.mark.parametrize(
        "block",
        [
            {"modell": "a/b"},
            {"model": 5},
            {"effort": "mininal"},
            {"prereview_effort": "enormous"},
        ],
        ids=["unknown-key", "wrong-type", "typo-in-effort", "unknown-effort"],
    )
    def test_a_wrong_llm_value_is_loud(block):
        from lean_herdr.settings import SettingsError, llm_settings

        with pytest.raises(SettingsError):
            llm_settings({"llm": block})


    def test_the_llm_section_must_be_a_table():
        from lean_herdr.settings import SettingsError, llm_settings

        with pytest.raises(SettingsError, match="not a table"):
            llm_settings({"llm": "a/b"})

### Die Konfigurationsdatei

`.config/lean-herdr.toml` ist im Repo und trägt heute nur auskommentierte
Beispiele — genau die Form, die der Kopf der Datei verspricht („Everything here
is commented out, so the project behaves exactly as it does without this file").
Der neue Block folgt ihr:

@call patch(".config/lean-herdr.toml", "das Ende der Datei, hinter [roles.reviewer]")

    # [llm]
    # Read by lean_herdr/llm.py alone: the commit generator worktrunk calls
    # through bin/herdr-llm, and the pre-review judge behind --prereview.
    # They are two different jobs -- the generator formats a diffstat, the
    # judge reads code -- so they get separate keys, and the judge inherits
    # only where a line below says so.
    #
    # The commit generator:
    #   model:  --model > $LEAN_HERDR_LLM_MODEL > model > built-in
    #   effort: --effort > effort > built-in "minimal"
    # model = "google/gemini-3.8-flash"   # the judge falls back to this
    # effort = "minimal"                  # THE GENERATOR ONLY -- not the judge
    #
    # The pre-review judge:
    #   model:  --model > $LEAN_HERDR_PREREVIEW_MODEL > prereview_model
    #           > $LEAN_HERDR_LLM_MODEL > model > built-in
    #   effort: --effort > prereview_effort > built-in
    # prereview_model = ""                # empty: share `model` above
    # prereview_effort = "low"            # `effort` above is NOT inherited
    #
    # Raising `model` to make the judge smarter raises the generator's bill
    # on every commit; give the judge `prereview_model` instead.
    # `effort` and `prereview_effort`: minimal | low | medium | high.

### Verify & Close

@call verify(lean_herdr/llm.py lean_herdr/settings.py .config/lean-herdr.toml tests/test_llm.py tests/test_settings.py)
@call review_change()
@call gate(lean_herdr/llm.py lean_herdr/settings.py tests/test_llm.py tests/test_settings.py)
@call commit("lean_herdr/llm.py lean_herdr/settings.py .config/lean-herdr.toml tests/test_llm.py tests/test_settings.py", "feat(llm): call a small model over curl, configured from .config/lean-herdr.toml")
@call remember_decision("lean_herdr/llm.py: the only HTTP call in lean-herdr. complete() returns None for EVERY failure and resolves NOTHING but the key; generate() always returns text because a failing commit.generation.command aborts the commit. Key goes through a 0600 curl --config file, never argv. Model and effort resolve flag > environment > [llm] in .config/lean-herdr.toml > built-in constant, via _first() at the call site. file_settings() never raises -- a broken config costs the defaults, not the commit. settings.ROOT_KEYS had to gain 'llm' first, or every herdr-dispatch call would fail with config_error.")
@phase-end

@phase "task-2"
## Task 2: `bin/herdr-llm` — das CLI und sein Syntax-Raster

**Files:** Create `bin/herdr-llm`. Modify `lean_herdr/llm.py`,
`tests/test_manifest.py`, `tests/test_llm.py`.
**Interfaces:** Produces `lean_herdr.llm.build_parser() ->
argparse.ArgumentParser`, `lean_herdr.llm.main(argv=None) -> int`, und das
ausführbare `bin/herdr-llm generate [--model M] [--effort E] [--timeout S]`.
**Consumes:** `lean_herdr.llm.generate`, `api_key`, `fallback_message` aus Task 1.

@call recall_context("lean_herdr/llm.py contract")

### Der Modus, den worktrunk aufruft

Nur `generate` in diesem Task — `prereview` kommt in Task 7 dazu, weil sein
Modell-Aufruf erst in Task 5 entsteht. Zwei Modi, nicht drei: worktrunk kennt
genau **ein** `commit.generation.command`, und dasselbe Kommando bedient den
Commit des Builders, den Squash des Orchestrators und den Squash innerhalb von
`wt merge`.

Der Import, den Task 1 bewusst ausgelassen hat, kommt jetzt oben dazu —
`import argparse`, alphabetisch vor `import json`. Dazu `EFFORTS` in den
bestehenden `from lean_herdr.settings import (...)`-Block: der Parser nimmt seine
`choices` von dort, statt die vier Wörter ein zweites Mal zu schreiben.

Ans Ende von `lean_herdr/llm.py` anhängen:

    def build_parser() -> argparse.ArgumentParser:
        p = argparse.ArgumentParser(
            prog="herdr-llm",
            description="Commit messages from a small model -- worktrunk's generator.",
        )
        p.add_argument("mode", choices=("generate",))
        p.add_argument(
            "--model", default=None,
            help="beats $LEAN_HERDR_LLM_MODEL, then [llm].model in "
                 ".config/lean-herdr.toml, then the built-in default",
        )
        p.add_argument(
            # EFFORTS, not a second spelling of the same four words: the
            # settings validator rejects anything outside it, and two lists
            # would disagree the day a fifth level shows up.
            "--effort", default=None, choices=EFFORTS,
            help="beats [llm].effort, then the built-in default; "
                 "no environment level exists",
        )
        p.add_argument(
            "--timeout", type=_positive_seconds, default=None, help="seconds"
        )
        return p


    def main(argv: list[str] | None = None) -> int:
        """`generate` reads stdin, writes stdout and ALWAYS exits 0.

        Always, including on an unexpected exception: worktrunk treats a
        failing `commit.generation.command` as fatal and does not commit
        (spec 2.3). The one thing that may still end this process with a
        non-zero code is argparse's own usage error -- a typo in the
        operator's user config, which is a state that SHOULD be loud, and
        which shows up on the very first commit.
        """
        args = build_parser().parse_args(argv)
        if args.mode == "generate":
            prompt = ""
            try:
                if not api_key():
                    print(
                        f"herdr-llm: no ${KEY_ENV} and no opencode key store -- "
                        "falling back to the file names",
                        file=sys.stderr,
                    )
                prompt = sys.stdin.read()
                # `None` for model and effort, not the constants: generate()
                # owns the precedence, and passing a constant here would put
                # the CLI's silence ABOVE the settings file.
                message = generate(
                    prompt,
                    model=args.model,
                    effort=args.effort,
                    timeout_s=args.timeout or GENERATE_TIMEOUT_S,
                )
            except Exception as exc:  # noqa: BLE001 -- a failure would abort the commit
                print(f"herdr-llm: {exc}", file=sys.stderr)
                message = fallback_message(prompt)
            sys.stdout.write(message.rstrip("\n") + "\n")
            return 0
        # Unreachable while `choices` names one mode -- and a placeholder:
        # task 7 replaces exactly this line with the prereview branch. Until
        # then it is a raise rather than a fall-through, so a second mode
        # added without a branch cannot exit 0 with an empty stdout.
        raise AssertionError(f"unhandled mode: {args.mode}")

`bin/herdr-llm` (neu, ausführbar — `chmod +x`). Die `sys.path`-Zeile ist dieselbe
wie in `bin/herdr-dispatch:7` und trägt den absoluten Pfad aus der
worktrunk-User-Config: das Skript findet sein Paket über den eigenen Dateipfad,
nicht über `$PWD`.

    #!/usr/bin/env python3
    """Commit messages for worktrunk. Output: text on stdout, exit 0."""

    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from lean_herdr.llm import main  # noqa: E402

    if __name__ == "__main__":
        raise SystemExit(main())

### Das Syntax-Raster

`tests/test_manifest.py` verdrahtet seine Einstiegspunkte hart
(`test_the_package_parses_on_the_python3_the_manifest_may_meet`,
`tests/test_manifest.py:92-96`): `lean_herdr/*.py` plus `bin/herdr-dispatch` und
`bin/herdr-report`. `lean_herdr/llm.py` ist über den Glob automatisch abgedeckt,
`bin/herdr-llm` fällt ohne einen Eintrag durch.

@call patch("tests/test_manifest.py", "die `sources`-Liste in test_the_package_parses_on_the_python3_the_manifest_may_meet")

Die Liste bekommt eine dritte Zeile:

        ROOT / "bin" / "herdr-llm",

### Die Tests

An `tests/test_llm.py` anhängen:

    def test_generate_writes_the_message_and_exits_zero(monkeypatch, capsys, tmp_path):
        store = tmp_path / "auth.json"
        store.write_text(json.dumps({"openrouter": {"key": "k"}}))
        monkeypatch.setattr(llm, "AUTH_PATH", store)
        monkeypatch.setattr(llm.sys, "stdin", _Stdin(DIFFSTAT_PROMPT))
        monkeypatch.setattr(
            llm, "generate", lambda *a, **kw: "feat(llm): add the generator"
        )
        assert llm.main(["generate"]) == 0
        assert capsys.readouterr().out == "feat(llm): add the generator\n"


    def test_generate_exits_zero_even_when_everything_breaks(monkeypatch, capsys, tmp_path):
        """The contract worktrunk forces on us: text out, exit 0, always."""
        monkeypatch.setattr(llm, "AUTH_PATH", tmp_path / "absent.json")
        monkeypatch.setattr(llm.sys, "stdin", _Stdin(DIFFSTAT_PROMPT))

        def boom(*_a, **_kw):
            raise RuntimeError("the network is on fire")

        monkeypatch.setattr(llm, "generate", boom)
        assert llm.main(["generate"]) == 0
        captured = capsys.readouterr()
        assert captured.out == "Changes to lean_herdr/llm.py, tests/test_llm.py\n"
        assert "the network is on fire" in captured.err


    def test_a_missing_key_says_so_on_stderr(monkeypatch, capsys, tmp_path):
        monkeypatch.setattr(llm, "AUTH_PATH", tmp_path / "absent.json")
        monkeypatch.setattr(llm.os, "environ", {})
        monkeypatch.setattr(llm.sys, "stdin", _Stdin(DIFFSTAT_PROMPT))
        monkeypatch.setattr(llm, "generate", lambda *a, **kw: "x")
        assert llm.main(["generate"]) == 0
        assert "falling back to the file names" in capsys.readouterr().err

Dazu, oben in `tests/test_llm.py` neben `SpyRunner`:

    class _Stdin:
        """A stdin double -- `monkeypatch.setattr(sys, "stdin", ...)`."""

        def __init__(self, text: str):
            self._text = text

        def read(self) -> str:
            return self._text

### Die Hand-Probe

    chmod +x bin/herdr-llm
    printf '<diffstat>\n a.txt | 1 +\n</diffstat>' | ./bin/herdr-llm generate; echo "exit:$?"

Expected: eine Zeile auf stdout, `exit:0`. Mit gesetztem Key eine
Conventional-Commit-Zeile, ohne Key `Changes to a.txt` plus die stderr-Notiz.

### Verify & Close

@call verify(bin/herdr-llm lean_herdr/llm.py tests/test_llm.py tests/test_manifest.py)
@call gate(bin/herdr-llm lean_herdr/llm.py tests/test_llm.py tests/test_manifest.py)
@call commit("bin/herdr-llm lean_herdr/llm.py tests/test_llm.py tests/test_manifest.py", "feat(llm): add bin/herdr-llm generate as worktrunk's commit generator")
@call remember_decision("bin/herdr-llm generate is worktrunk's commit.generation.command. It exits 0 on every runtime failure; only an argparse usage error is loud, because that is an operator typo in the machine-wide user config.")
@phase-end

@phase "task-3"
## Task 3: Der Commit-Pfad des Builders — Konfiguration, Rechte, Rollentext

**Files:** Modify `.config/wt.toml`, `roles/builder.md`, `opencode.jsonc`,
`.claude/settings.json`, `tests/test_worker_permissions.py`, `README.md`.
**Interfaces:** Produces das `[commit.generation] template-append`-Fragment, die
Berechtigung `wt step commit *` (opencode) / `Bash(wt step commit:*)` (Claude),
und den Operator-Abschnitt der README.
**Consumes:** `bin/herdr-llm generate` aus Task 2.

### Schritt 0 — die Messung aus Spec §10.1, VOR dem Rollentext

Offen ist, was ein **nicht freigegebenes** `template-append`-Fragment im
Agenten-Pane tut: still übergangen (die Doku sagt „Declining is non-fatal") oder
wartend auf eine Eingabe, die im Pane niemand gibt. Der zweite Fall hinge einen
Builder auf, und zwar unsichtbar — der Orchestrator liefe in `no_reply`.

    cd "$(mktemp -d)" && git init -q -b main && echo a > a.txt && git add a.txt \
      && git -c user.email=t@e -c user.name=t commit -qm init
    mkdir -p .config && printf '[commit.generation]\ntemplate-append = "probe"\n' > .config/wt.toml
    echo b >> a.txt && git add a.txt
    wt config approvals list          # Erwartung: nicht "approved"
    wt step commit --dry-run --stage none < /dev/null; echo "exit:$?"

Expected: eine Ausgabe und ein Exit-Code — **kein** Hängen. Notiere beides.

**Wenn der Aufruf hängt:** das `template-append`-Fragment kommt trotzdem in
`.config/wt.toml`, aber die README-Zeile `wt config approvals add` wird vom
empfohlenen zum **verpflichtenden** Operator-Schritt, und der Rollentext des
Builders bekommt einen Satz dazu, dass ein hängender `wt step commit` genau
diesen fehlenden Schritt bedeutet. Halte das Ergebnis in
`@call remember_decision(...)` am Ende dieses Tasks fest.

### `.config/wt.toml`

@call patch(".config/wt.toml", "das Ende der Datei -- ein neuer [commit.generation]-Block hinter [list]")

Neuer Block, wörtlich (die Projektstimme; worktrunk rendert Aufgabe, Format,
Diffstat und Diff selbst — wir hängen nur an, wir ersetzen nichts):

    # Appended to worktrunk's own commit prompt -- we write no template of our
    # own (spec 9). Needs `wt config approvals add` once, through the same
    # approval store as the pre-merge hook above -- but a stricter gate:
    # an unapproved hook is skipped silently, an unapproved fragment fails the
    # whole command (`Cannot prompt for approval in non-interactive
    # environment`, exit 1). Both agent paths pass `--yes`, which consents for
    # that one run without recording anything.
    [commit.generation]
    template-append = """
    Project voice:
    - Conventional Commits with a scope: `type(scope): subject`.
    - English, imperative, no trailing period, subject under 72 characters.
    - Describe WHAT changes, not what it is good for.
    - A body only for a material change, and then measured facts, not intentions.
    - Never mention the tool, the model or the agent that wrote this.
    """

### `roles/builder.md`

Schritt 3 lautet heute `3. Work: TDD, small commits, no refactoring outside the
order.` — eine Absicht ohne Kommando.

@call patch("roles/builder.md", "Schritt 3 der ## Sequence")

Ersetzen durch:

    3. Work: TDD, no refactoring outside the order. Commit in small steps:

           git add <the paths this order asked for>
           wt step commit --stage none --yes

       Stage explicitly what the order asked for -- never `git add -A`, never
       `git add .`. Untracked files stay untracked: nothing you did not name
       reaches the commit. An empty index fails loudly (`✗ Nothing to commit`) --
       that is the reminder to stage, not an error to work around.

       The commit message is written for you by the operator's configured
       generator. You do not pass `-m`, and you do not second-guess it.

### Die Rechte

`opencode.jsonc`, im `builder`-Block hinter `"git status*": "allow"`:

    "wt step commit *": "allow"

Der Orchestrator hat `"wt *"` und braucht nichts Neues. Der Reviewer bekommt
nichts — er schreibt nicht.

`.claude/settings.json`, in `permissions.allow`:

    "Bash(wt step commit:*)"

### Die Tests

`tests/test_worker_permissions.py` bewacht genau dieses Paar. `BUILDER_TOOLING`
(`tests/test_worker_permissions.py:30-37`) bekommt einen siebten Eintrag:

    "wt step commit *",

Und `test_the_builders_gate_is_not_a_blank_cheque`
(`tests/test_worker_permissions.py:137-141`) bekommt zwei weitere Muster in seine
Verbotsliste — der Orchestrator darf `wt *`, der Builder genau einen
Unterbefehl:

    for forbidden in ("git push*", "git *", "uv *", "uv run *", "rm*", "curl*",
                      "wt *", "wt step *"):

Dazu ein neuer Test, der die Claude-Seite bindet — die bestehenden
Report-Tests filtern auf das Präfix `bin/herdr-report` und sehen `wt` nicht:

    def test_the_claude_builder_may_commit_through_worktrunk():
        """The same gate as the opencode builder, on the other harness.

        Without this line a Claude Code builder is stopped at its first
        commit by a permission prompt no one is sitting at.
        """
        assert "Bash(wt step commit:*)" in claude_allow()


    def test_no_permission_file_hands_out_worktrunk_wholesale():
        """`wt *` on a worker is the whole tool, merge and push included."""
        for entry in claude_allow():
            assert entry not in ("Bash(wt:*)", "Bash(wt step:*)"), entry

Der Docstring von `BUILDER_TOOLING` nennt heute „TDD, small commits" — er bekommt
den neuen Grund dazu:

    #: The builder's own gate. roles/builder.md prescribes TDD and commits via
    #: `wt step commit --stage none`, and `bash: {"*": "deny"}` plus the report
    #: patterns let it do neither -- an opencode builder would fail on its first
    #: `uv run pytest` and again on its first commit. Exactly this list, nothing
    #: wider: `wt step commit *`, not `wt *`, and not `wt step *`.

### Die README

Neuer Abschnitt direkt hinter der `wt config approvals`-Passage
(`README.md:44-49`), vor der `herdr plugin list`-Zeile:

@call patch("README.md", "hinter dem `wt config approvals`-Absatz, vor `herdr plugin list`")

    Plus the commit generator, in worktrunk's **user** config. This one file is
    not optional bookkeeping: without `[commit.generation]` worktrunk writes
    `Changes to a.txt` from the file names, and `wt merge` squashes with exactly
    that message into `main`.

        # ~/.config/worktrunk/config.toml
        [commit]
        stage = "none"          # shared by step commit, step squash AND merge

        [commit.generation]
        command = "/home/you/Scripts/lean-herdr/bin/herdr-llm generate"

    `stage` sits under `[commit]`, not at the top level -- a bare `stage = "none"`
    is reported as *"User config has unknown field stage (will be ignored)"* and
    does nothing (measured on worktrunk 0.76.0). Being user config, it is
    machine-wide: `wt step commit`, `wt step squash` and `wt merge` stop staging
    for you in **every** repository. The direction is the safe one -- they commit
    what you staged and never more -- but it is a habit change everywhere, not
    just here.

    **The path is absolute, never `bin/herdr-llm`.** That file governs every
    repository on the machine; a relative path would run into `sh: not found`
    (exit 127) everywhere else, and a failing generation command is fatal, not a
    silent fallback -- it would break `wt step commit` and `wt merge` in all your
    other projects. The generator is repo-agnostic: it only formats what
    worktrunk hands it on stdin, so one absolute path serves every repository
    sensibly.

    worktrunk also knows `[projects."<id>"]` blocks. Whether
    `commit.generation.command` is allowed inside one is untested; if it were, the
    generator could be scoped to this repository instead of the whole machine.
    The absolute path works either way and stays the recommendation.

    The key is read from `$OPENROUTER_API_KEY`, else from opencode's own store at
    `~/.local/share/opencode/auth.json`. With neither, commits fall back to file
    names and nothing breaks.

        export OPENROUTER_API_KEY=sk-or-...

    Which model, and how hard it thinks, is configured per project in
    `.config/lean-herdr.toml` under `[llm]` -- the same file the role settings
    live in. For the commit generator: `--model` beats `$LEAN_HERDR_LLM_MODEL`,
    which beats `[llm].model`, which beats the built-in; `--effort` beats
    `[llm].effort`, which beats the built-in `minimal`. The pre-review judge has
    keys of its own -- see the work-order section. A broken or absent file costs
    the defaults, never the commit.

    **The new attack surface, named:** the builder may now run a command that
    sends the contents of its worktree to a third-party service. That was already
    true of every agent in this project, but here without a model in between that
    could refuse. In a repository with secrets in it, do not configure the
    generator.

### Verify & Close

@call verify(.config/wt.toml roles/builder.md opencode.jsonc .claude/settings.json tests/test_worker_permissions.py README.md)
@call gate(.config/wt.toml roles/builder.md opencode.jsonc .claude/settings.json tests/test_worker_permissions.py README.md)
@call commit(".config/wt.toml roles/builder.md opencode.jsonc .claude/settings.json tests/test_worker_permissions.py README.md", "feat(builder): commit through `wt step commit --stage none`")
@call remember_decision("The builder commits with `wt step commit --stage none --yes` and stages explicitly. Permission is `wt step commit *` only -- never `wt *`. The generator lives in worktrunk's MACHINE-WIDE user config with an ABSOLUTE path, because a failing generation command is fatal in every other repo too.")
@phase-end

@phase "task-4"
## Task 4: Der Abbau des Orchestrators — Squash, `--no-commit`, ein neuer Zweig

**Files:** Modify `roles/orchestrator.md`.
**Interfaces:** Produces den geänderten Teardown-Ablauf und eine neue
Eskalationsursache.
**Consumes:** die `stage = "none"`-Zeile der User-Config aus Task 3.

### Schritt 0 — die Messung aus Spec §10.3, VOR dem Rollentext

Messung 2.4 #5 lief über **zwei** Commits. Ob `wt step squash --stage none` bei
genau einem und bei null Commits durchgeht oder scheitert, entscheidet, ob der
neue Abbau-Zweig im Normalbetrieb greift oder nur im Ausnahmefall.

    D=$(mktemp -d) && cd "$D" && git init -q -b main && echo a > a.txt \
      && git add a.txt && git -c user.email=t@e -c user.name=t commit -qm init
    wt switch --create probe --base @ --no-cd --yes
    P=$(wt list --format json)      # den Pfad von `probe` ablesen
    # Fall A: null Commits auf der Branch
    wt -C <path> step squash --stage none --yes; echo "exit:$?"
    # Fall B: genau ein Commit
    cd <path> && echo b >> a.txt && git add a.txt \
      && git -c user.email=t@e -c user.name=t commit -qm "one"
    wt -C <path> step squash --stage none --yes; echo "exit:$?"

Expected: zwei Ausgaben und zwei Exit-Codes. Notiere beide wörtlich.

**Wenn Fall B scheitert** (ein Commit ist kein Squash-Fall), bekommt der
Rollentext einen Satz: „ein `✗`, das nur sagt, es gebe nichts zu squashen, ist
kein Abbruchgrund — weiter mit Schritt 3." Die Unterscheidung muss im Text
stehen, nicht im Kopf des Modells. Halte das Ergebnis in
`@call remember_decision(...)` fest.

### Der Teardown

Der Abschnitt `## Teardown and merge — this order, not another` in
`roles/orchestrator.md` trägt heute vier Schritte und endet mit
`wt -C <path> merge main --yes`.

@call patch("roles/orchestrator.md", "die vier nummerierten Schritte im Abschnitt Teardown and merge")

Ersetzen durch fünf:

        1. Check: verdict=result, not reject
        2. Resolve path and workspace WHILE the worktree still exists:
             herdr worktree list --cwd <repo_root>
           Read the JSON answer yourself: under `result.worktrees`, find the
           entry whose `branch` is your branch and take its `path` and its
           `open_workspace_id`. Do not pipe the answer through another program.
           Nothing but `herdr`, `wt`, `git` and `bin/herdr-dispatch` is allowed
           to you.
        3. wt -C <path> step squash --stage none --yes
        4. herdr workspace close <workspace_id>
        5. wt -C <path> merge main --yes --no-commit

Und der begründende Absatz darunter, neu:

    **`--no-commit` skips the commit AND the squash.** That is why step 3 is not
    a luxury: it is the only place the squash still happens, and the squashed
    message is the one that lands in `main`. What `--no-commit` buys is step 5's
    refusal: if anything unfinished is left in the worktree, the merge stops
    before `main` moves at all.

    **If step 3 fails, the teardown ends there.** You close NO workspace and you
    merge NOT AT ALL -- you escalate with `wt`'s own error text. This is the
    first step of the teardown that can fail before anything irreversible has
    happened, and the open workspace is wanted: it is exactly the state in which
    a human can look at what the squash would not take.

### Die neue Eskalationsursache

Der Abschnitt `## Escalation` listet heute vier Ursachen.

@call patch("roles/orchestrator.md", "die Zeile `Escalate on: twice reject, ...` im Abschnitt Escalation")

Ergänzen um zwei:

    Escalate on: twice `reject`, `agent_error` (no retry -- a 401 is a 401 the
    second time too), a second `no_reply`, a failed `pre-merge` hook, a failed
    `wt step squash`, and `✗ Cannot merge with --no-commit`.

    `Cannot merge with --no-commit` means unfinished work is lying in the
    worktree. That is a finding for the human, not a mess to tidy away: you
    remove nothing, you commit nothing on the worker's behalf, and you name the
    file the message points at.

### Die Probe

Der Ablauf ist Text für ein Modell — die Prüfung ist ein Durchlauf mit einem
Wegwerf-Repo, nicht ein Unittest. `tests/test_roles.py` bewacht nur den
`ORCHESTRATOR`-Namen und bleibt unberührt; `tests/test_role_prohibitions.py` und
`tests/test_language.py` laufen über den geänderten Text automatisch mit.

    uv run pytest -q tests/test_roles.py tests/test_role_prohibitions.py tests/test_language.py

Expected: PASS.

### Verify & Close

@call verify(roles/orchestrator.md)
@call gate(roles/orchestrator.md)
@call commit("roles/orchestrator.md", "docs(orchestrator): squash before the merge and stop the teardown when it fails")
@call remember_decision("Teardown is five steps now: check, resolve, `wt step squash --stage none`, close workspace, `wt merge --no-commit`. A failing squash ends the teardown BEFORE anything irreversible -- no workspace close, no merge, escalate instead.")
@phase-end

@phase "task-5"
## Task 5: `llm.prereview()` — das Urteil, und die Effort-Messung dahinter

**Files:** Modify `lean_herdr/llm.py`, `tests/test_llm.py`.
**Interfaces:** Produces `lean_herdr.llm.PREREVIEW_TIMEOUT_S`,
`PREREVIEW_EFFORT`, `PREREVIEW_MODEL_ENV`, `DIFF_TIMEOUT_S`, `NOTE_MAX_CHARS`,
`MAX_DIFF_BYTES`,
`PREREVIEW_RE`, `PREREVIEW_PROMPT`, `wt_diff(path, *, runner=…, timeout_s=…) ->
str | None`, `prereview(order, diff, *, model=None, effort=None, timeout_s=…,
runner=…, env=None, auth_path=None, settings=None) -> tuple[str, str]`,
`prereview_result(order, *, branch, worktree_list, settings=None, runner=…, …) ->
dict[str, str]`.
**Consumes:** `complete()`, `_first()`, `file_settings()` und
`settings.LlmSettings` aus Task 1; `lean_herdr.worktree.find_worktree`.

@call recall_context("lean_herdr/llm.py contract")

### Schritt 0 — die Messung aus Spec §10.2, VOR dem Code

`effort=low` ist **geschätzt, nicht gemessen** — die einzige ungemessene
Einstellung des ganzen Entwurfs. Miss sie, bevor sie als Konstante festfriert.

Bau einen absichtlich fehlerhaften Diff mit genau drei Fehlern aus der
Ablehnungsliste (ein `print()`-Rest, eine neue Funktion ohne Test, eine
hartkodierte absolute Pfadangabe) und einen sauberen Kontroll-Diff. Fahre beide
dreimal:

    for E in minimal low medium; do
      for D in bad.diff clean.diff; do
        printf 'effort=%s file=%s\n' "$E" "$D"
        # denselben Aufruf wie complete(), mit --config-Datei und dem Prompt aus
        # PREREVIEW_PROMPT unten; die Antwort-Header von OpenRouter tragen die
        # Kosten, `usage` im Body die Token
      done
    done

Expected, in einer Tabelle festgehalten: je Effort die Trefferquote auf
`bad.diff` (wie viele der drei Fehler benannt), die Fehlalarmquote auf
`clean.diff` (jedes `reject` dort ist einer) und die Kosten je Aufruf.

**Entscheidungsregel, vorab und nicht nachträglich:** die billigste Stufe ohne
Fehlalarm auf `clean.diff` gewinnt. Ein Fehlalarm kostet einen ganzen
Builder-Durchlauf; ein übersehener Fehler kostet nichts, weil der starke
Reviewer danach ohnehin läuft. Setze `PREREVIEW_EFFORT` auf das Ergebnis und
schreibe die gemessene Zahl in den Kommentar daneben — nicht „low, geschätzt",
sondern die Tabelle in zwei Zeilen.

### Der Code

An `lean_herdr/llm.py` anhängen (die neuen Konstanten oben zu den anderen):

    PREREVIEW_TIMEOUT_S = 60.0
    DIFF_TIMEOUT_S = 30.0

    #: A model of its own for the judge. Precedence: an explicit `model=`
    #: It is the second of six levels -- `model=` (the CLI's --model), this,
    #: `[llm].prereview_model`, $LEAN_HERDR_LLM_MODEL, `[llm].model`, then
    #: DEFAULT_MODEL. Without it the two jobs would be stuck on one
    #: variable, and they are not the same job: the commit path formats a
    #: diffstat and is happy with the smallest model there is, the judge
    #: reads code. The builder inherits the pane's environment, so moving
    #: $LEAN_HERDR_LLM_MODEL to raise the judge would raise the commit
    #: generator's bill on every commit as a side effect.
    PREREVIEW_MODEL_ENV = "LEAN_HERDR_PREREVIEW_MODEL"

    #: MEASURED in task 5, step 0 -- replace this comment with the table.
    #: The rule the measurement settled: the cheapest level with no false
    #: alarm on a clean diff wins. A false alarm costs a whole builder
    #: round; a missed finding costs nothing, because the strong reviewer
    #: runs afterwards either way.
    PREREVIEW_EFFORT = "low"

    #: The note travels into the follow-up order and from there into the
    #: order log. A rambling model justification does not belong there.
    NOTE_MAX_CHARS = 2_000

    #: Bigger than this and there is no judging left to do -- `skipped`,
    #: with a reason, and no call. Well under MAX_PROMPT_BYTES, because the
    #: prompt around the diff has to fit too.
    MAX_DIFF_BYTES = 150_000

    #: The FIRST line, exactly as `dispatch.verdict()` reads its own token:
    #: so that quoting the same words further down in the reasoning cannot
    #: flip the ruling. `PREREVIEW:` is a protocol token, not prose.
    PREREVIEW_RE = re.compile(r"PREREVIEW:\s*(pass|reject)\s*$")

    #: Deliberately narrow, and every ground checkable without knowing the
    #: project: no taste, no formatting, no architecture. Those belong to
    #: the strong reviewer, and a cheap model arguing about them would cost
    #: a builder round for nothing.
    PREREVIEW_PROMPT = """You are a cheap pre-check that runs before an expensive reviewer.
    Judge ONLY the diff below, and only against the order it was written for.

    Answer with `PREREVIEW: pass` or `PREREVIEW: reject` on the FIRST line, then
    at most three sentences of reason.

    Reject ONLY for one of these, and name which one:
    - new or changed logic with no test beside it
    - debug leftovers: print/pdb calls, commented-out code
    - unresolved merge markers
    - hard-coded absolute paths or secrets
    - tool droppings in the diff: .orig, .rej, scratch files
    - changes the order does not cover

    Never reject for taste, formatting or architecture. When in doubt, pass: a
    strong reviewer runs after you either way, and a wrong rejection costs a
    whole build round.

    <order>
    {order}
    </order>

    <diff>
    {diff}
    </diff>
    """


    def _skip(reason: str) -> dict[str, str]:
        return {"prereview": "skipped", "prereview_note": reason}


    def wt_diff(
        path: Any,
        *,
        runner: Any = subprocess.run,
        timeout_s: float = DIFF_TIMEOUT_S,
    ) -> str | None:
        """`wt -C <path> step diff` -- or None when the call fails at all.

        Verified against `wt step --help` (0.76.0): diff shows "all changes
        since branching (committed, staged, unstaged, untracked)" -- exactly
        the set `wt merge` would take. `git diff` alone would miss the
        committed part, `git diff main...` the untracked one.
        """
        try:
            proc = runner(
                ["wt", "-C", str(path), "step", "diff"],
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return proc.stdout if proc.returncode == 0 else None


    def prereview(
        order: str,
        diff: str,
        *,
        model: str | None = None,
        effort: str | None = None,
        timeout_s: float = PREREVIEW_TIMEOUT_S,
        runner: Any = subprocess.run,
        env: Any = None,
        auth_path: Any = None,
        settings: LlmSettings | None = None,
    ) -> tuple[str, str]:
        """(`pass` | `reject` | `skipped`, note). Never raises.

        `skipped` for every failure of the machinery itself -- no key,
        timeout, unparsable answer, empty diff, a diff over the cap. NEVER
        `reject`. That is the technical form of the design decision: the
        model may block, its plumbing may not.

        The judge resolves its own two levels FIRST and falls back to the
        shared ones: flag, `$LEAN_HERDR_PREREVIEW_MODEL`,
        `[llm].prereview_model`, `$LEAN_HERDR_LLM_MODEL`, `[llm].model`,
        constant. The effort does NOT fall back to `[llm].effort` -- that
        one is the commit generator's `minimal`, and inheriting it would
        quietly make the judge as thoughtless as the formatter.
        """
        if not diff.strip():
            return "skipped", "empty_diff"
        if len(diff.encode("utf-8")) > MAX_DIFF_BYTES:
            return "skipped", "diff_too_large"
        environ = os.environ if env is None else env
        cfg = file_settings() if settings is None else settings
        answer = complete(
            PREREVIEW_PROMPT.format(order=order, diff=diff),
            effort=_first(effort, cfg.prereview_effort, fallback=PREREVIEW_EFFORT),
            model=_first(
                model,
                environ.get(PREREVIEW_MODEL_ENV),
                cfg.prereview_model,
                environ.get(MODEL_ENV),
                cfg.model,
                fallback=DEFAULT_MODEL,
            ),
            timeout_s=timeout_s,
            runner=runner,
            env=env,
            auth_path=auth_path,
        )
        if answer is None:
            return "skipped", "no_answer"
        lines = answer.lstrip().splitlines()
        hit = PREREVIEW_RE.match(lines[0]) if lines else None
        if hit is None:
            return "skipped", "unparsable_answer"
        return hit.group(1), "\n".join(lines[1:]).strip()[:NOTE_MAX_CHARS]


    def prereview_result(
        order: str,
        *,
        branch: str | None,
        worktree_list: Any,
        settings: LlmSettings | None = None,
        runner: Any = subprocess.run,
        **kwargs: Any,
    ) -> dict[str, str]:
        """The two keys the wait mode merges into its `completed` answer.

        Resolves the path ITSELF via find_worktree(), and deliberately NOT
        via `dispatch._worker_root()`: that one falls back to the repo root
        when the branch does not resolve (dispatch.py:338-345), which is
        right for its own purpose -- finding a crash log on the timeout
        path -- and wrong here. `wt step diff` would then run in the
        orchestrator's own checkout, and a dirty tree there could reject a
        STRANGER's diff. "Not found" is `skipped`: a visibly withheld
        ruling instead of a false one.

        This function lives here and not in dispatch.py for a second
        reason: dispatch.py stands at 762 lines against an 800-line
        ceiling.
        """
        if not branch:
            return _skip("no_branch")
        try:
            entry = find_worktree(worktree_list or {}, branch)
        except (AttributeError, TypeError):
            return _skip("worktree_unresolved")
        path = entry.get("path") if isinstance(entry, dict) else None
        if not path:
            return _skip("worktree_unresolved")
        diff = wt_diff(path, runner=runner)
        if diff is None:
            return _skip("diff_failed")
        # `settings` comes in ALREADY VALIDATED from dispatch.main(), which
        # read the file once for its own RoleSettings anyway. Two gains: no
        # second `git rev-parse`, and a wrong `[llm]` value reaches the
        # orchestrator as `config_error:` instead of dying quietly in
        # file_settings(). Only the commit path may swallow it -- there a
        # broken config must not cost a commit; here it has a reader.
        ruling, note = prereview(
            order, diff, runner=runner, settings=settings, **kwargs
        )
        return {"prereview": ruling, "prereview_note": note}

Der Import oben in `lean_herdr/llm.py` wächst um eine Zeile — die einzige
Projektabhängigkeit dieses Moduls:

    from lean_herdr.worktree import find_worktree

### Die Tests

An `tests/test_llm.py` anhängen:

    def worktrees(*entries: dict) -> dict:
        return {"result": {"worktrees": list(entries)}}


    def test_prereview_reads_only_the_first_line(no_store):
        """The reasoning may say `reject` as often as it likes."""
        spy = SpyRunner(answer(
            "PREREVIEW: pass\nI would reject this if the order had not asked "
            "for it. Nothing to reject."
        ))
        ruling, note = llm.prereview(
            "add a parser", "diff --git a/x b/x", runner=spy,
            env={llm.KEY_ENV: "k"}, auth_path=no_store, settings=NO_FILE,
        )
        assert ruling == "pass"
        assert note.startswith("I would reject this")


    def test_a_verdict_further_down_does_not_count(no_store):
        spy = SpyRunner(answer("Looks fine to me.\nPREREVIEW: reject"))
        ruling, note = llm.prereview(
            "add a parser", "diff", runner=spy,
            env={llm.KEY_ENV: "k"}, auth_path=no_store, settings=NO_FILE,
        )
        assert ruling == "skipped"
        assert note == "unparsable_answer"


    @pytest.mark.parametrize(
        ("diff", "spy", "reason"),
        [
            ("   ", SpyRunner(answer("PREREVIEW: reject")), "empty_diff"),
            ("x" * (llm.MAX_DIFF_BYTES + 1), SpyRunner(answer("PREREVIEW: reject")), "diff_too_large"),
            ("diff", SpyRunner(raises=OSError("no curl")), "no_answer"),
            ("diff", SpyRunner(answer("I have no opinion")), "unparsable_answer"),
        ],
        ids=["empty", "too-large", "no-curl", "unparsable"],
    )
    def test_prereview_never_rejects_when_its_own_machinery_fails(diff, spy, reason, no_store):
        ruling, note = llm.prereview(
            "an order", diff, runner=spy,
            env={llm.KEY_ENV: "k"}, auth_path=no_store, settings=NO_FILE,
        )
        assert ruling == "skipped", "the plumbing must never reject"
        assert note == reason


    def test_a_missing_key_is_skipped_not_rejected(no_store):
        spy = SpyRunner(answer("PREREVIEW: reject"))
        ruling, note = llm.prereview(
            "an order", "diff", runner=spy, env={}, auth_path=no_store,
            settings=NO_FILE,
        )
        assert (ruling, note) == ("skipped", "no_answer")
        assert spy.calls == []


    def judged(no_store, *, cfg=None, env=None, **kw):
        """One prereview call; returns the request body that was sent."""
        spy = SpyRunner(answer("PREREVIEW: pass"))
        llm.prereview(
            "an order", "diff", runner=spy, auth_path=no_store,
            settings=cfg if cfg is not None else NO_FILE,
            env={llm.KEY_ENV: "k", **(env or {})},
            **kw,
        )
        return json.loads(spy.bodies[0])


    def test_the_judges_precedence_runs_all_six_levels(no_store):
        """Raising the judge must not raise the commit generator's bill."""
        cfg = LlmSettings(
            model="file/shared", prereview_model="file/judge",
            effort="minimal", prereview_effort="medium",
        )
        both = {
            llm.MODEL_ENV: "env/shared",
            llm.PREREVIEW_MODEL_ENV: "env/judge",
        }
        assert judged(no_store, cfg=cfg, env=both, model="flag/m")["model"] == "flag/m"
        assert judged(no_store, cfg=cfg, env=both)["model"] == "env/judge"
        assert judged(no_store, cfg=cfg, env={llm.MODEL_ENV: "env/shared"})[
            "model"
        ] == "file/judge", "its own file key beats the shared environment"
        assert judged(
            no_store, cfg=LlmSettings(model="file/shared"),
            env={llm.MODEL_ENV: "env/shared"},
        )["model"] == "env/shared"
        assert judged(no_store, cfg=LlmSettings(model="file/shared"))[
            "model"
        ] == "file/shared", "with nothing of its own the judge shares the model"
        assert judged(no_store)["model"] == llm.DEFAULT_MODEL


    def test_the_judge_does_not_inherit_the_commit_generators_effort(no_store):
        """`[llm].effort` is the formatter's `minimal`. Inheriting it would
        make the judge as thoughtless as the formatter, silently."""
        cfg = LlmSettings(effort="minimal")
        assert judged(no_store, cfg=cfg)["reasoning"] == {
            "effort": llm.PREREVIEW_EFFORT
        }
        assert judged(
            no_store, cfg=LlmSettings(effort="minimal", prereview_effort="high")
        )["reasoning"] == {"effort": "high"}
        assert judged(no_store, cfg=cfg, effort="low")["reasoning"] == {"effort": "low"}


    def test_the_note_is_cut_at_the_cap(no_store):
        spy = SpyRunner(answer("PREREVIEW: reject\n" + "x" * 5000))
        _ruling, note = llm.prereview(
            "an order", "diff", runner=spy,
            env={llm.KEY_ENV: "k"}, auth_path=no_store, settings=NO_FILE,
        )
        assert len(note) == llm.NOTE_MAX_CHARS


    def test_the_diff_comes_from_the_worktree_not_the_checkout():
        calls = []

        def runner(cmd, **_kw):
            calls.append(list(cmd))
            return Completed(stdout="diff --git a/x b/x")

        assert llm.wt_diff("/worktrees/feat-x", runner=runner) == "diff --git a/x b/x"
        assert calls == [["wt", "-C", "/worktrees/feat-x", "step", "diff"]]


    def test_a_failing_wt_diff_is_none():
        assert llm.wt_diff("/x", runner=lambda *a, **k: Completed(returncode=1)) is None
        assert llm.wt_diff("/x", runner=SpyRunner(raises=OSError("no wt"))) is None


    def test_an_unresolvable_worktree_is_skipped_not_rejected():
        """The invariant `_worker_root()` would have broken."""
        def runner(*_a, **_kw):
            raise AssertionError("nothing may run without a resolved path")

        assert llm.prereview_result(
            "an order", branch="feat/x", worktree_list=worktrees(), runner=runner,
        ) == {"prereview": "skipped", "prereview_note": "worktree_unresolved"}
        assert llm.prereview_result(
            "an order", branch="feat/x",
            worktree_list=worktrees({"branch": "feat/x"}), runner=runner,
        )["prereview_note"] == "worktree_unresolved"
        assert llm.prereview_result(
            "an order", branch=None, worktree_list=worktrees(), runner=runner,
        )["prereview_note"] == "no_branch"


    def test_a_garbage_worktree_list_is_skipped_not_a_crash():
        assert llm.prereview_result(
            "an order", branch="feat/x", worktree_list="not a dict",
            runner=lambda *a, **k: Completed(),
        )["prereview"] == "skipped"


    def test_the_resolved_path_is_the_one_the_diff_runs_in(no_store):
        seen = []

        def runner(cmd, **_kw):
            seen.append(list(cmd))
            if cmd[:1] == ["wt"]:
                return Completed(stdout="diff --git a/x b/x")
            return Completed(stdout=json.dumps(answer("PREREVIEW: reject\nno test")))

        got = llm.prereview_result(
            "an order",
            branch="feat/x",
            worktree_list=worktrees(
                {"branch": "other", "path": "/wrong"},
                {"branch": "feat/x", "path": "/right"},
            ),
            runner=runner,
            settings=NO_FILE,
            env={llm.KEY_ENV: "k"},
            auth_path=no_store,
        )
        assert got == {"prereview": "reject", "prereview_note": "no test"}
        assert seen[0] == ["wt", "-C", "/right", "step", "diff"]

### Verify & Close

@call verify(lean_herdr/llm.py tests/test_llm.py)
@call review_change()
@call gate(lean_herdr/llm.py tests/test_llm.py)
@call commit("lean_herdr/llm.py tests/test_llm.py", "feat(llm): judge a branch diff before the expensive reviewer runs")
@call remember_decision("llm.prereview() returns pass|reject|skipped; EVERY failure of its own machinery is skipped, never reject. prereview_result() resolves the worktree itself via find_worktree -- never dispatch._worker_root(), whose repo-root fallback would judge a stranger's diff -- and takes `settings` so [llm] is read once by dispatch.main() against the MAIN checkout, without a second git call. The judge's model chain: flag, $LEAN_HERDR_PREREVIEW_MODEL, [llm].prereview_model, $LEAN_HERDR_LLM_MODEL, [llm].model, constant; its effort does NOT inherit [llm].effort. Measured PREREVIEW_EFFORT: <the value from step 0>.")
@phase-end

@phase "task-6"
## Task 6: `--prereview` im Warte-Modus

**Files:** Modify `lean_herdr/dispatch.py`. Create
`tests/test_dispatch_prereview.py`.
**Interfaces:** Produces `AwaitRequest.prereview: bool = False`,
`await_task(..., runner=…, llm_cfg: LlmSettings | None = None)`, das Flag
`--prereview` an `bin/herdr-dispatch`, und die zwei Schlüssel `prereview` /
`prereview_note` **neben** `verdict` in der `completed`-Antwort.
**Consumes:** `lean_herdr.llm.prereview_result` aus Task 5;
`lean_herdr.settings.{LlmSettings, llm_settings}` aus Task 1.

@call recall_context("llm.prereview_result contract")

### Die fünf Stellen in `dispatch.py`

Anker: `@symbol AwaitRequest`, `@symbol await_task`, `@symbol build_parser`,
`@symbol missing_flags`, `@symbol main`. Der Import oben wächst um drei Zeilen:
`import subprocess` bei den Stdlib-Importen, `from lean_herdr import llm` bei den
Projektimporten, und `LlmSettings` sowie `llm_settings` in den bestehenden
`from lean_herdr.settings import (...)`-Block.

**1. `AwaitRequest`** bekommt ein sechstes Feld:

        #: Run the cheap pre-review over the branch diff once the order is
        #: `completed`. Never a gate: only `reject` changes anything, and
        #: every failure of the pre-review's own machinery is `skipped`.
        prereview: bool = False

**2. `await_task()`** bekommt zwei neue Schlüsselwort-Parameter hinter `now`
— alle Parameter dort sind bereits keyword-only, also bricht kein Aufrufer:

        runner: Any = subprocess.run,
        #: `[llm]` out of the SAME file main() read for `settings`, and
        #: validated there -- so a wrong value is `config_error:` on stdout
        #: instead of a stderr line nobody reads. None means: no file was
        #: read, take the built-in constants.
        llm_cfg: LlmSettings | None = None,

und der Rückgabe-Zweig in der Schleife (`dispatch.py:438-440`) wird zu:

        outcome = _result_for_state(order)
        if outcome is not None:
            if req.prereview and order.state == "completed":
                # Beside `verdict`, never instead of it: that key belongs
                # to the strong reviewer and its VERDIKT: protocol, and a
                # second writer on it would be exactly the confusion
                # VERDICT_RE exists to prevent.
                outcome.update(
                    llm.prereview_result(
                        order.description,
                        branch=req.worktree,
                        worktree_list=herdr.worktree_list(root),
                        settings=llm_cfg,
                        runner=runner,
                    )
                )
            return outcome

`_result_for_state()` bleibt unangetastet — die fünf Rücklagen des Warte-Modus
behalten ihre Form, und die Vorprüfung hängt hinter dem Ergebnis, nicht in ihm.

**3. `build_parser()`** bekommt ein Flag hinter `--worktree`:

        p.add_argument(
            "--prereview",
            action="store_true",
            help="only with --await and --worktree: judge the branch diff first",
        )

**4. `missing_flags()`**, drei Ergänzungen. Der `LOG_COMMANDS`-Zweig zählt seine
Streuflags einzeln auf (`dispatch.py:590-597`) — ohne einen Eintrag dort
schluckte `order --prereview` das Flag stillschweigend, genau das Verhalten, das
dieser Zweig verhindern soll. `store_true` liefert `False`, nicht `None`, also
`or None`, damit `_given()` es sieht:

        stray = _given(
            ("--kind", args.kind),
            ("--model", args.model),
            ("--role-file", args.role_file),
            ("--profile", args.profile),
            ("--worktree", args.worktree),
            ("--timeout-ms", args.timeout_ms),
            ("--prereview", args.prereview or None),
        )

Im `--await`-Zweig (`dispatch.py:657-669`), hinter der `--timeout-ms`-Prüfung:

        if args.prereview and not args.worktree:
            return "--prereview needs --worktree"

Und im Bau-Zweig (`dispatch.py:679`), damit `--prereview` ohne `--await` ein
Fehler ist statt eines verschluckten Flags:

        stray = _given(
            ("--task-id", args.task_id),
            ("--timeout-ms", args.timeout_ms),
            ("--prereview", args.prereview or None),
        )

**5. `main()`**, an zwei Stellen. Der Dateiinhalt wird heute nur an
`settings_for()` weitergereicht (`dispatch.py:704-705`); er bekommt einen Namen,
damit `[llm]` aus **derselben** Lesung validiert wird:

            root = canonical_root()
            raw = read_settings(root / SETTINGS_PATH)
            settings = settings_for(args.command, raw)
            # Validated HERE, in the one consumer that has a reader for the
            # complaint: a SettingsError from this line leaves main() as
            # `config_error: <reason>` on stdout. llm.file_settings()
            # deliberately swallows the same error -- there it would cost a
            # commit -- so without this call a typo in `[llm]` would be
            # silent everywhere, against settings.py's own promise that a
            # file which IS there but is wrong never stays silent.
            llm_cfg = llm_settings(raw)

`read_settings` und `SETTINGS_PATH` stehen bereits im Import-Block, `raw` ist
neu. Und im `AwaitRequest(...)`-Zweig:

        prereview=args.prereview,

dazu, als Argument von `await_task()` selbst neben `settings=settings`:

        llm_cfg=llm_cfg,

### Die Messung der Dateigröße

`dispatch.py` steht bei 762 Zeilen, die Grenze aus `AGENTS.md` bei 800.

    uv run python -c "print(sum(1 for _ in open('lean_herdr/dispatch.py')))"

Expected: eine Zahl unter 800. **Melde sie**, schätze sie nicht.

**Reißt sie die Grenze:** nicht die Grenze lockern. Der Schnitt, den dieses
Modul schon einmal bekommen hat, wiederholt sich — `build_parser()`,
`_given()`, `missing_flags()`, `UsageError`, `_Parser` und `main()` wandern nach
`lean_herdr/dispatchcli.py`, `bin/herdr-dispatch` importiert von dort, und
`tests/test_dispatch.py` folgt dem Import. Das ist dann ein eigener Commit vor
diesem.

### Die Tests

`tests/test_dispatch_prereview.py` (neu):

    """`--prereview` may block, but it may never wave anything through.

    The neighbouring file tests/test_dispatch_await.py owns the wait mode
    itself; this one owns exactly the new key beside its answer.
    """

    import json
    from pathlib import Path

    import pytest

    from lean_herdr.dispatch import AwaitRequest, await_task, build_parser, main, missing_flags
    from lean_herdr.herdr import Herdr
    from lean_herdr.orderlog import append
    from lean_herdr.settings import LlmSettings
    from tests.doubles import Completed, FakeProc, which_stub

    ROOT = Path("/repo")
    WORKER = "builder-feat-x"
    TASK_ID = "o-1a05e34cd15-1cf3b885"
    BRANCH = "feat/x"
    WORKTREES = {
        "result": {"worktrees": [{"branch": BRANCH, "path": "/worktrees/feat-x"}]}
    }


    def openrouter(text: str) -> str:
        return json.dumps({"choices": [{"message": {"content": text}}]})


    @pytest.fixture
    def herdr(monkeypatch):
        monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
        proc = FakeProc()
        proc.replies = {
            ("agent", "list"): {"result": {"agents": []}},
            ("worktree", "list"): WORKTREES,
        }
        return Herdr(runner=proc)


    def completed_log(tmp_path, message="done"):
        append(TASK_ID, "created", "orchestrator", {"to_agent": WORKER, "description": "add a parser"}, orders=tmp_path)
        append(TASK_ID, "working", WORKER, {}, orders=tmp_path)
        append(TASK_ID, "completed", WORKER, {"message": message}, orders=tmp_path)
        return tmp_path


    def wait(herdr, tmp_path, *, prereview, runner, worktree=BRANCH, llm_cfg=None):
        return await_task(
            AwaitRequest(
                role="builder", kind="claude", task_id=TASK_ID,
                worktree=worktree, timeout_ms=300_000, prereview=prereview,
            ),
            herdr=herdr,
            root=ROOT,
            orders_dir=tmp_path,
            sleep=lambda _s: None,
            runner=runner,
            # NEVER None here: prereview() would then call file_settings(),
            # which runs a real `git rev-parse` and reads this checkout's own
            # .config/lean-herdr.toml. In production main() hands the
            # validated block down; in a test we hand down an empty one.
            llm_cfg=llm_cfg if llm_cfg is not None else LlmSettings(),
        )


    def llm_runner(verdict_line: str, monkeypatch, tmp_path):
        """A curl/wt double plus a key, so complete() actually runs."""
        store = tmp_path / "auth.json"
        store.write_text(json.dumps({"openrouter": {"key": "k"}}))
        monkeypatch.setattr("lean_herdr.llm.AUTH_PATH", store)

        def runner(cmd, **_kw):
            if cmd[:1] == ["wt"]:
                return Completed(stdout="diff --git a/x b/x\n+print('debug')")
            return Completed(stdout=openrouter(verdict_line))

        return runner


    def test_without_the_flag_the_answer_is_the_one_from_before(herdr, tmp_path):
        def runner(*_a, **_kw):
            raise AssertionError("no pre-review may run without --prereview")

        result = wait(herdr, completed_log(tmp_path), prereview=False, runner=runner)
        assert result["ok"] is True
        assert result["state"] == "completed"
        assert "prereview" not in result
        assert "prereview_note" not in result


    def test_a_rejection_stands_beside_the_verdict_never_instead(herdr, tmp_path, monkeypatch):
        runner = llm_runner("PREREVIEW: reject\ndebug leftover: print()", monkeypatch, tmp_path)
        result = wait(
            herdr, completed_log(tmp_path, "VERDIKT: result\nall green"),
            prereview=True, runner=runner,
        )
        assert result["verdict"] == "result", "the strong reviewer keeps its key"
        assert result["prereview"] == "reject"
        assert result["prereview_note"] == "debug leftover: print()"
        assert result["ok"] is True, "a pre-review is not a failure of the order"


    def test_a_pass_changes_nothing_about_the_answer(herdr, tmp_path, monkeypatch):
        runner = llm_runner("PREREVIEW: pass", monkeypatch, tmp_path)
        result = wait(herdr, completed_log(tmp_path), prereview=True, runner=runner)
        assert result["prereview"] == "pass"
        assert result["ok"] is True
        assert result["state"] == "completed"


    @pytest.mark.parametrize("state", ["failed", "canceled", "input-required"])
    def test_the_pre_review_only_runs_on_completed(herdr, tmp_path, state):
        def runner(*_a, **_kw):
            raise AssertionError(f"nothing may run on {state}")

        append(TASK_ID, "created", "orchestrator", {"to_agent": WORKER, "description": "d"}, orders=tmp_path)
        append(TASK_ID, state, WORKER, {"message": "m"}, orders=tmp_path)
        result = wait(herdr, tmp_path, prereview=True, runner=runner)
        assert "prereview" not in result


    def test_a_broken_pre_review_is_skipped_never_a_rejection(herdr, tmp_path, monkeypatch):
        # os.environ has to be patched process-wide, not handed in as
        # `env={}`: dispatch passes only `runner` down, so this is the one
        # grip on the key resolution from out here. Do not "simplify" it.
        monkeypatch.setattr("lean_herdr.llm.AUTH_PATH", tmp_path / "absent.json")
        monkeypatch.setattr("lean_herdr.llm.os.environ", {})
        result = wait(
            herdr, completed_log(tmp_path), prereview=True,
            runner=lambda *a, **k: Completed(stdout="diff --git a/x b/x"),
        )
        assert result["prereview"] == "skipped"
        assert result["prereview_note"] == "no_answer"


    def test_the_flag_needs_await_and_a_worktree():
        parse = build_parser().parse_args
        assert missing_flags(parse(
            ["builder", "--kind", "claude", "--model", "sonnet",
             "--role-file", "roles/builder.md", "--prereview"]
        )) == "build mode does not take --prereview"
        assert missing_flags(parse(
            ["builder", "--kind", "claude", "--await", "--task-id", TASK_ID, "--prereview"]
        )) == "--prereview needs --worktree"
        assert missing_flags(parse(
            ["order", "--to", WORKER, "--message", "m", "--prereview"]
        )) == "`order` does not take --prereview"


    def test_a_stray_flag_is_a_json_line_not_an_exit_code(capsys):
        assert main(["order", "--to", WORKER, "--message", "m", "--prereview"]) == 0
        answer = json.loads(capsys.readouterr().out)
        assert answer["ok"] is False
        assert "--prereview" in answer["error"]

### Verify & Close

@call verify(lean_herdr/dispatch.py tests/test_dispatch_prereview.py)
@call review_change()
@call gate(lean_herdr/dispatch.py tests/test_dispatch_prereview.py)
@call commit("lean_herdr/dispatch.py tests/test_dispatch_prereview.py", "feat(dispatch): add --prereview to the wait mode, beside the verdict")
@call remember_decision("await_task() takes `runner` and merges llm.prereview_result() into the completed answer when --prereview is given. `prereview` never replaces `verdict`. --prereview without --await or without --worktree is a usage error; a failure at runtime is `skipped`. dispatch.py line count after this task: <the measured number>.")
@phase-end

@phase "task-7"
## Task 7: Der manuelle Einstieg und der Rollentext dazu

**Files:** Modify `lean_herdr/llm.py`, `roles/orchestrator.md`, `README.md`,
`tests/test_llm.py`.
**Interfaces:** Produces
`bin/herdr-llm prereview [-C <path>] [--order <text>] [--model M] [--effort E]
[--timeout S]`, den Vorprüfungs-Abschnitt im Orchestrator-Text und einen
`-m integration`-Test über die echte Kette.
**Consumes:** `llm.prereview`, `llm.wt_diff` aus Task 5; `--prereview` aus Task 6.

### Der zweite Modus

Für ein Feature, dessen Qualität sich erst im Betrieb zeigt, ist der manuelle
Einstieg der wichtigere der beiden Modi: ein Branch hinein, das Urteil heraus,
ohne dass ein Auftrag angelegt wird.

`build_parser()` aus Task 2 wächst um die zweite Wahl und zwei Flags;
`--model`, `--effort` und `--timeout` stehen schon dort und bedienen beide Modi:

        p.add_argument("mode", choices=("generate", "prereview"))
        p.add_argument(
            "-C", dest="path", default=".",
            help="prereview: the worktree to judge (default: the current one)",
        )
        p.add_argument(
            "--order", default="",
            help="prereview: the order text the diff is supposed to answer",
        )

In `main()` **ersetzt** der zweite Zweig genau die eine Zeile, die Task 2 als
Platzhalter stehen ließ — `raise AssertionError(f"unhandled mode: {args.mode}")`
samt ihrem Kommentar. Der `generate`-Zweig darüber bleibt unangetastet:

        diff = wt_diff(args.path, timeout_s=args.timeout or DIFF_TIMEOUT_S)
        if diff is None:
            print(f"herdr-llm: `wt -C {args.path} step diff` failed", file=sys.stderr)
            return 1
        # No `settings=`: prereview() resolves the file itself, from the
        # repository the operator is standing in. `--model`/`--effort` stay
        # None when unset, so the file keeps its place in the chain.
        ruling, note = prereview(
            args.order,
            diff,
            model=args.model,
            effort=args.effort,
            timeout_s=args.timeout or PREREVIEW_TIMEOUT_S,
        )
        sys.stdout.write(ruling + "\n")
        if note:
            sys.stdout.write(note + "\n")
        # Exit 1 on a rejection, so the mode is usable in a shell chain.
        # `skipped` is 0: a withheld ruling is not a finding.
        return 1 if ruling == "reject" else 0

Die Docstring-Zeile von `main()` bekommt den Zusatz, den Task 2 schon
vorwegnimmt: `prereview` ist der manuelle Einstiegspunkt und darf mit 1 enden.

### Die Tests

An `tests/test_llm.py` anhängen:

    def test_the_cli_rejects_with_exit_one(monkeypatch, capsys):
        monkeypatch.setattr(llm, "wt_diff", lambda *a, **kw: "diff --git a/x b/x")
        monkeypatch.setattr(
            llm, "prereview", lambda *a, **kw: ("reject", "no test beside new logic")
        )
        assert llm.main(["prereview", "-C", "/worktrees/feat-x"]) == 1
        out = capsys.readouterr().out
        assert out == "reject\nno test beside new logic\n"


    def test_the_cli_passes_and_skips_with_exit_zero(monkeypatch, capsys):
        monkeypatch.setattr(llm, "wt_diff", lambda *a, **kw: "diff")
        for ruling in ("pass", "skipped"):
            # `answer=ruling` binds now, not at call time -- ruff B023.
            monkeypatch.setattr(
                llm, "prereview", lambda *a, fixed=ruling, **kw: (fixed, "")
            )
            assert llm.main(["prereview"]) == 0
            assert capsys.readouterr().out == f"{ruling}\n"


    def test_a_failing_wt_diff_says_so_and_judges_nothing(monkeypatch, capsys):
        monkeypatch.setattr(llm, "wt_diff", lambda *a, **kw: None)
        monkeypatch.setattr(
            llm, "prereview",
            lambda *a, **kw: pytest.fail("nothing may be judged without a diff"),
        )
        assert llm.main(["prereview", "-C", "/gone"]) == 1
        assert "step diff` failed" in capsys.readouterr().err


    @pytest.mark.integration
    def test_the_real_chain_answers_at_all(tmp_path):
        """The one test that reaches the network -- never in CI.

        Everything else in this file injects `runner`. This one proves the
        pieces fit together in the real world: a real key, a real curl, a
        real OpenRouter answer. It costs a fraction of a cent.
        """
        import shutil

        if shutil.which("curl") is None:
            pytest.skip("curl not installed")
        if llm.api_key() is None:
            pytest.skip("no OpenRouter key on this machine")
        got = llm.complete(
            "Answer with exactly the word: pong", effort=llm.GENERATE_EFFORT,
        )
        assert got is not None and "pong" in got.lower()

### Der Rollentext des Orchestrators

@call patch("roles/orchestrator.md", "der Abschnitt ## Sequence per task, Punkt 3")

Punkt 3 lautet heute `ok: true? Then the same three steps for the reviewer on the
same branch.` Ersetzen durch:

    3. `ok: true`? Read `prereview` first, if you asked for it.

       The builder's wait call may carry `--prereview`:

           bin/herdr-dispatch builder --await --kind claude --task-id o-… \
             --worktree <branch> --prereview

       It costs you nothing extra -- you read that JSON line anyway. The key
       stands beside `verdict`, never instead of it, and takes one of three
       values:

       | `prereview` | What you do |
       |---|---|
       | `reject` | round 2 with the builder, BEFORE any reviewer is built |
       | `pass` | build the reviewer -- `pass` is not an approval |
       | `skipped` | build the reviewer -- the pre-review withheld its ruling |

       A `reject` is one follow-up order to the same builder, with `--after o-…`,
       carrying `prereview_note` verbatim. On THAT round you do **not** pass
       `--prereview` again: that limits a stubborn small model to exactly one
       rejection, without a counter anywhere.

       Then the same three steps for the reviewer on the same branch.

Und in `## Model choice — your judgement`, unter der Tabelle, ein Absatz:

    The pre-review is not a third worker: it is a flag on the builder's wait
    call, and the model behind it is small and cheap. It may block, it may never
    approve -- the strong reviewer runs in every case, `pass` or not.

### Die README

Im Abschnitt `The work-order path`, hinter der Aufzählung der Kommandos:

    The wait call for a builder takes `--prereview`. A small model then reads the
    branch diff -- `wt step diff`: committed, staged, unstaged and untracked
    against the merge base, exactly what `wt merge` would take -- and answers in
    the same JSON line, beside `verdict`:

        {"ok": true, "state": "completed", "prereview": "reject",
         "prereview_note": "new logic in parse_row() with no test beside it"}

    Only `reject` changes anything. `pass` and `skipped` are the same to the
    orchestrator: the strong reviewer runs either way. Every failure of the
    pre-review itself -- no key, timeout, an unresolvable worktree -- is
    `skipped` with a reason, never a rejection.

    The judge may run on a model of its own. The two jobs are not the same one:
    the commit generator formats a diffstat and is happy with the smallest model
    there is, the judge reads code.

        # .config/lean-herdr.toml -- the durable place
        [llm]
        model = "google/gemini-3.8-flash"   # both
        prereview_model = ""                # the judge only; empty: share `model`
        prereview_effort = "low"            # the judge thinks harder than the formatter

        # or ad hoc, for one pane, without touching a file every repo reads
        export LEAN_HERDR_PREREVIEW_MODEL=<something stronger>

    Precedence for the judge's model: `--model` on the CLI, then
    `$LEAN_HERDR_PREREVIEW_MODEL`, then `[llm].prereview_model`, then
    `$LEAN_HERDR_LLM_MODEL`, then `[llm].model`, then the built-in default. Its
    effort deliberately does NOT fall back to `[llm].effort`: that one is the
    commit generator's `minimal`, and inheriting it would make the judge as
    thoughtless as the formatter. Raising only the shared `model` to raise the
    judge would raise the commit generator's bill on every single commit.

    The same judgement by hand, without creating an order:

        bin/herdr-llm prereview -C <worktree> --order "<what it was supposed to do>"

    Exit 1 on a rejection, 0 on `pass` and on `skipped`.

### Verify & Close

@call verify(lean_herdr/llm.py roles/orchestrator.md README.md tests/test_llm.py)
@call review_change()
@call gate(lean_herdr/llm.py roles/orchestrator.md README.md tests/test_llm.py)

Dazu einmal die ganze Kette von Hand, in einem Wegwerf-Worktree mit einem
absichtlich fehlerhaften Diff:

    ./bin/herdr-llm prereview -C <worktree> --order "add a row parser"; echo "exit:$?"

Expected: `reject` plus eine Begründung, die einen der sechs Gründe benennt, und
`exit:1`. Auf einem sauberen Diff: `pass`, `exit:0`.

@call commit("lean_herdr/llm.py roles/orchestrator.md README.md tests/test_llm.py", "feat(llm): add the manual prereview entry point and wire it into the orchestrator")
@call remember_decision("bin/herdr-llm prereview -C <path> --order <text> is the manual entry point; exit 1 only on reject. The orchestrator passes --prereview on the FIRST builder round only -- that caps a stubborn small model at one rejection without a counter.")
@phase-end
