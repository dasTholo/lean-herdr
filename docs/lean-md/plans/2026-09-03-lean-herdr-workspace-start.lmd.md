@lean-md
consumer: ai
crp: compact

@var test_cmd default="uv run pytest -q" desc="project test runner command"
@var lint_cmd default="uv run ruff check ." desc="project lint gate"
@import .lean-ctx/lean-md/plan-recipes /

# lean-herdr — Ein Binary, ein Workspace-Start

Quelle: `docs/specs/2026-09-03-lean-herdr-workspace-start-design.md` (v1.0).
Render je Task:
`lean-md render docs/lean-md/plans/2026-09-03-lean-herdr-workspace-start.lmd.md --phase task-N`.

## Goal

Aus drei Programmen wird eines. `lean-herdr` ist der einzige Entry-Point, global
installiert statt im Repo, mit den Verben `dispatch`, `report` und `workspace`.
Das neue Verb `workspace` bringt zwei Befehle mit: `up` startet den Orchestrator
aus `.lean-ctx/lean-herdr/config.toml`, `init` richtet ein fremdes Projekt ein.
Der Tastendruck `bootstrap` im laufenden Herdr läuft danach über denselben Kern
wie `up` — heute liest er die Config überhaupt nicht.

Die sechs Tasks bauen aufeinander auf und sind in dieser Reihenfolge zwingend.
Die Ordnung ist so gewählt, dass keine Datei zweimal umgeschrieben wird: der
Binary-Umzug (Task 2) läuft **vor** dem Anlegen der Vorlagen (Task 3), sonst
entstünden die Vorlagen in der alten Schreibweise und Task 2 müsste sie erneut
anfassen.

## Architecture

```
lean_herdr/
  cli.py         NEU  VERBS, main -- der Verb-Router                 (Task 1)
                      + "workspace" in VERBS                         (Task 4)
  workspace.py   NEU  start_orchestrator, find_workspace,
                      create_workspace, workspace_up, main           (Task 4)
                      + "init" im Parser                             (Task 5)
  initcmd.py     NEU  LAYOUT, workspace_init, die Vorbedingungsprüfung (Task 5)
  templates/     NEU  config.toml, roles/*.md, opencode.jsonc,
                      settings.json, wt.toml, lean-ctx-policy.js     (Task 3)
  settings.py    ~    SETTINGS_PATH auf .lean-ctx/lean-herdr/        (Task 3)
                      ROOT_KEYS + "workspace"; KINDS,
                      ORCHESTRATOR_AGENT, WorkspaceSettings,
                      WORKSPACE_ALLOWED, workspace_settings()        (Task 4)
  handlers.py    ~    ORCHESTRATOR faellt weg; handle_bootstrap
                      ruft workspace.start_orchestrator              (Task 4)
  ordercmd.py    ~    ORCHESTRATOR_AGENT kommt aus settings          (Task 4)
  dispatch.py    ~    nur Kommentare + choices=KINDS            (Task 2 / Task 4)
  report.py worktree.py bus.py orderlog.py orders.py join.py
  export.py digest.py config.py leanctx.py herdr.py    nur Kommentare (Task 2)
  llm.py         ~    nur Prosa: fuenf Erwaehnungen des Config-Pfads   (Task 3)
                      -- das Verhalten folgt SETTINGS_PATH von selbst

bin/herdr-dispatch  WEG                                              (Task 2)
bin/herdr-report    WEG                                              (Task 2)
bin/herdr-llm       BLEIBT  -- gehoert dem LLM-Plan, wird nicht angefasst

.config/lean-herdr.toml  ->  .lean-ctx/lean-herdr/config.toml        (Task 3)
roles/                   ->  .lean-ctx/lean-herdr/roles/             (Task 3)
opencode.jsonc           ~    lean-herdr-Muster (Task 2), prompt-Pfade (Task 3)
.claude/settings.json    ~    lean-herdr-Muster                      (Task 2)
.config/wt.toml          =    unveraendert, wird nur Vorlage         (Task 3)
.opencode/plugins/lean-ctx-policy.js  =  unveraendert, wird Vorlage  (Task 3)
pyproject.toml           ~    [project.scripts]                      (Task 1)
README.md                ~    Bootstrap, Freigaben, Konfiguration (Task 2 / 5 / 6)

tests/test_cli.py         NEU  (Task 1, waechst in Task 4)
tests/test_templates.py   NEU  (Task 3, Wahrheit wandert in Task 5)
tests/test_workspace.py   NEU  (Task 4)
tests/test_initcmd.py     NEU  (Task 5)
tests/test_worker_permissions.py  ~  der neue Fallstrick             (Task 2)
tests/test_manifest.py            ~  zwei der drei bin/-Eintraege     (Task 2)
tests/test_roles.py               ~  Muster (Task 2), Vorlage (Task 3)
tests/test_role_prohibitions.py   ~  Muster (Task 2), Vorlage (Task 3)
tests/test_config_files.py        ~  Muster (Task 2), Pfade (Task 3)
tests/test_settings.py            ~  Vorlage (Task 3), [workspace] (Task 4)
tests/test_worktree.py            ~  ein Kommentar                   (Task 2)
tests/test_handlers.py            ~  bootstrap laeuft ueber den Kern (Task 4)
```

Der Startweg nach Task 4, beide Verbraucher auf einem Kern:

```
lean-herdr workspace up
  -> canonical_root() -> .lean-ctx/lean-herdr/config.toml
       fehlt -> not_initialised
  -> start_orchestrator(workspace_id=None)
       -> Server? is_available() + rohes `workspace list`
       -> laeuft `orch` schon?  -> already_running
       -> Workspace: worktree.checkout_path == root
                     sonst erste Pane mit cwd == root
                     sonst `workspace create --cwd --label --env --focus`
       -> anchor_pane() -> pane split --env
       -> agent start orch --kind <kind> --pane <id> -- [--model <m>] --agent orchestrator
       -> wait_for_agent_id()

Tastendruck `bootstrap` im laufenden Herdr
  -> dieselbe Funktion, nur start_orchestrator(workspace_id=<aus dem Ereignis>)
       -> legt NIE einen Workspace an, sucht keinen
```

Gemessene Grundlagen dieses Plans (2026-09-03, gegen `herdr 0.8.2`,
`wt 0.76.0`, `lean-ctx 3.10.1`, im Workspace `w1` dieses Repos):

| Befund | Beleg |
|---|---|
| `workspace create` kennt genau `--cwd`, `--label`, `--env`, `--focus`/`--no-focus` | `herdr workspace create --help` |
| `workspace list` traegt `worktree.checkout_path` fuer einen Repo-Workspace | `w1` -> `/home/tholo/Scripts/lean-herdr` |
| `pane list` **ohne** `--workspace` traegt je Eintrag `cwd` **und** `workspace_id` | drei Eintraege, alle mit beiden Feldern |
| ein Workspace fuehrt Panes mit **fremdem** `cwd` mit | `w1:p11` sitzt in `/home/tholo/Scripts/zed-herdr`, gehoert aber zu `w1` |
| `pane process-info` liefert **kein** `env`, aber `shell_pid` | `{"process_info":{…,"shell_pid":15589}}` |
| `wt config approvals list --format json` liefert `{"state": …}` | `"state": "approval_required"` |
| `lean-ctx allow --list` nennt die Zusatzliste im Klartext | `Extra (additive, via 'lean-ctx allow'): cp, mkdir, …` |
| `.gitignore` enthaelt heute **keine** `.lean-ctx/`-Zeile | `git check-ignore .lean-ctx/lean-herdr/config.toml` -> rc=1 |
| `herdr agent start` nimmt native Argumente hinter `--` | `herdr agent start --help` |

Zwei Nebenbefunde derselben Messung, die **nicht** zu diesem Plan gehoeren und
kein Task ihn beheben darf — sie stehen hier, damit niemand sie fuer eine
Regression dieses Umbaus haelt:

- Das pre-merge-Test-Gate dieses Repos ist in worktrunk **nicht freigegeben**
  (`"state": "approval_required"`). Genau der Fehlermodus, vor dem die README
  warnt: `wt` ueberspringt den Hook still und meldet Erfolg.
- `wt` meldet zu `.config/wt.toml`: *„Project config has key list.json-schema
  which belongs in user config (will be ignored)"*. `test_config_files.py`
  prueft den Schluessel trotzdem; er wirkt nur nicht.

## Global Constraints

- **Der Vertrag des Hauses gilt fuer jedes neue CLI unveraendert:** eine
  JSON-Zeile auf stdout, `ok` als einzige Wahrheit, Exit **immer** 0, jeder
  Ausnahmetyp abgefangen. `cli.main`, `workspace.main` und `initcmd` folgen
  der `except`-Leiter von `report.main` (`report.py:294-329`), einschliesslich
  des abschliessenden `except Exception`. Ein `usage_error` ist eine JSON-Zeile,
  nie Exit 2.
- **`up` splittet IMMER von `anchor_pane()` aus — ein Zweig, nicht zwei.**
  Bewusste Abweichung von Spec §5 Schritt 5; ein Review meldet sie NICHT als
  Befund. Die Spec liess offen, ob die Wurzel-Pane eines frisch erzeugten
  Workspace das `--env` von `workspace create` traegt und damit schon die
  Orchestrator-Pane waere. Task 4 misst das (Schritt 0) und haelt das Ergebnis
  als Wissen fest, **verzweigt den Code aber nicht danach**: der Split-Pfad ist
  der, den `handle_bootstrap` heute geht, er ist gemessen, und beide Verbraucher
  teilen ihn. Ein zweiter Zweig spaerte eine leere Shell-Pane und kostete einen
  Pfad, den nur einer der beiden Aufrufer je nimmt.
- **Der geteilte Kern hat genau eine Stellschraube: `workspace_id`.**
  `None` = suchen oder anlegen (`up`). Ein Wert = genau diesen nehmen und
  **nie** einen anlegen (Tastendruck). Wanderte die Fund-oder-Anlege-Regel in
  den Kern, startete der Tastendruck den Orchestrator in einem anderen
  Workspace als dem, in dem er gedrueckt wurde — der Fehler, den
  `handlers.py:170-171` heute ausdruecklich vermeidet.
- **`up` ohne Config bricht ab, der Tastendruck nicht.** Die Asymmetrie ist
  gewollt: die Config ist der ganze Zweck von `up` (Spec §5.1), waehrend der
  Tastendruck eine Geste ist, die nicht ins Leere laufen darf. Fehlt die Datei,
  nimmt `handle_bootstrap` die eingebauten Vorgaben.
- **`init` ueberschreibt nie ohne `--force` und repariert nie.** Ein fremdes
  `opencode.jsonc` oder `.claude/settings.json` still zu ueberbuegeln waere der
  teuerste denkbare Fehlgriff dieses Werkzeugs. Fremde Befehle laufen
  ausschliesslich **lesend** (`lean-ctx allow --list`, `wt config approvals list
  --format json`, `herdr plugin list`); jeder fehlende Punkt wird eine Zeile in
  `warnings`, nie ein Abbruch und nie eine Reparatur.
- **Eine Wahrheit fuer jede Vorlage.** Alles, was `init` schreibt, liegt unter
  `lean_herdr/templates/`. Die eingecheckte Kopie dieses Repos ist eine Kopie,
  und `tests/test_templates.py` haelt beide byte-gleich. Ohne diesen Test
  bewachte `test_role_prohibitions.py` die Kopie, waehrend `init` die andere
  Fassung in jedes neue Projekt traegt.
- **Der neue Fallstrick des einen Binaries gehoert in einen Test.** Bisher
  trennte ein *anderes Programm* den Builder vom Dispatch-Weg; jetzt trennt nur
  noch das Gate. Kein Worker-Gate darf ein Wildcard direkt hinter `lean-herdr`
  fuehren (`lean-herdr *`, `lean-herdr*`, `lean-herdr report *`,
  `Bash(lean-herdr:*)`), und **kein Worker-Gate nennt je `lean-herdr dispatch`**.
- **Der Orchestrator-Name wird kein Konfigurationsschluessel.** Drei Stellen
  muessen uebereinstimmen — die Konstante, die Zeile `ORCHESTRATOR = orch` in
  beiden Rollentexten und
  `test_roles.py::test_the_role_prompts_trust_the_name_dispatch_actually_stamps`.
  Ein Schluessel braeche den Dreiklang auf, ohne dass jemand danach gefragt hat.
- **`SETTINGS_PATH` bleibt relativ.** Der Aufrufer verbindet ihn mit
  `canonical_root()`. Absolut oder auf `$PWD` verankert laedt die Config
  stillschweigend nicht mehr, sobald der Aufruf aus einem Unterverzeichnis oder
  einer Worktree kommt (`settings.py:18-22`).
- **Der Python-Syntax-Floor bleibt 3.11 fuer `lean_herdr/*.py`.** Die
  Plugin-Handler starten ein nacktes `python3`, den Interpreter des Hosts.
  `cli.py`, `workspace.py` und `initcmd.py` fallen unter denselben Glob in
  `test_manifest.py`; von den **drei** `bin/`-Eintraegen dort verlassen nur
  `herdr-dispatch` und `herdr-report` die Pruefliste, weil `lean-herdr` als
  Entry-Point unter dem installierten Interpreter laeuft. `bin/herdr-llm` bleibt
  stehen: es startet weiterhin ein nacktes `python3`.
- **Kein Import-Zyklus.** `ORCHESTRATOR_AGENT` zieht in Task 4 von `handlers`
  nach `settings`. Ohne diesen Umzug entstuende `handlers` -> `workspace` ->
  `dispatch` -> `ordercmd` -> `handlers`, und `ordercmd` greift zur **Importzeit**
  auf den Namen zu — der Zyklus kraechte beim ersten Import, nicht erst im Test.
- **Dateigroesse:** kein `lean_herdr/`-Modul ueber 800 **produktive** LOC (Ziel
  600). Produktive LOC = physische Zeilen minus Leer-, Kommentar- und
  Docstring-Zeilen; `wc -l` ist ausdruecklich **nicht** das Mass, und die beiden
  Zahlen liegen in diesem Baum weit auseinander — `dispatch.py` steht am
  2026-09-03 bei 817 physischen gegen 519 produktive Zeilen. Ein Gate, das die
  physische Zahl gegen 800 haelt, ist deshalb schon heute rot, ohne dass eine
  Regel verletzt waere (`AGENTS.md`, „Project Hard Rules").
  `init` kommt deshalb von vornherein nach `lean_herdr/initcmd.py` statt spaeter
  aus `workspace.py` herausgeschnitten zu werden — `up` und `init` teilen nichts
  ausser dem Verb, und `ordercmd.py` ist der Praezedenzfall.
- **Sprachtor:** `tests/test_language.py` greift fuer alle neuen Dateien
  automatisch. Alles ausserhalb `docs/` ist Englisch — `lean_herdr/templates/`
  und die Rollentexte eingeschlossen.
- **Non-Goals** (Ablehnungsgrund im Review, kein Versaeumnis): keine
  Worker-Panes vorab anlegen; kein konfigurierbarer Orchestrator-Name; kein
  `kind`/`model` als Default fuer `dispatch`; kein `git init` durch `init`;
  **kein Rueckbau von `base="@"` in `wt_switch`** (die Rollentexte reisen
  weiterhin im Branch, der Workaround verliert nur einen seiner Gruende); keine
  Shims fuer `bin/herdr-dispatch` und `bin/herdr-report`; **keine Aenderung an**
  `orderlog.py`, `orders.py`, `join.py`, `export.py`, `digest.py`, `leanctx.py`,
  `bus.py`, `worktree.py` ausser Kommentaren.
- **Reihenfolge:** Task 2 setzt 1 voraus (die Allowlists nennen ein Programm,
  das laufen muss) · Task 3 setzt 2 voraus (die Vorlagen entstehen in der neuen
  Schreibweise) · Task 4 setzt 3 voraus (`up` liest die Config am neuen Ort) ·
  Task 5 setzt 4 voraus (`init` haengt am Parser aus Task 4) · Task 6 setzt alle
  voraus.
- **Der LLM-Plan ist weiter gelandet, als dieser Plan bei seiner Niederschrift
  annahm — am 2026-09-03 nachgemessen, nicht vermutet.**
  `docs/lean-md/plans/2026-09-03-lean-herdr-llm-commits.lmd.md` laeuft parallel, und
  im Baum stehen inzwischen nicht nur seine Tasks 1 und 2 (`8e2272e`, `26a25d5`,
  `0a32bab`), sondern auch der Pre-Review-Richter (`9449ec1`, `9677639`, `14bf07c`)
  und alles, was danach an ihm korrigiert wurde (bis `02c7e79`). **Vier** Folgen,
  die dieser Plan traegt:
  1. **`ROOT_KEYS` ist heute `("default", "roles", "llm")`.** Task 4 macht daraus
     ein **Vier**-Tupel. Wer die Zeile stattdessen abschreibt, wie sie in der
     Spec steht, loescht `"llm"` — dann wird jeder `[llm]`-Block ein
     `config_error`, und `tests/test_settings.py` wird an zwei Stellen rot.
  2. **`lean_herdr/llm.py` hat inzwischen ein eigenes CLI** — `main()` bei
     `llm.py:685`, `build_parser()` mit `prog="herdr-llm"` bei `:635`, und die
     beiden Modi `generate` und `prereview`. Fuer diesen Plan bleibt das folgenlos:
     `llm.py` liest `SETTINGS_PATH` aus `settings` und folgt dem Umzug in Task 3
     von selbst. Nur seine Prosa nennt den alten Pfad — an **fuenf** Stellen statt
     an den drei, die in der ersten Fassung dieses Plans standen, und eine davon
     ist ein argparse-Hilfetext, den ein Benutzer zu sehen bekommt.
  3. **`bin/herdr-llm` EXISTIERT** — versioniert seit `14bf07c` — **und bleibt.**
     Das Verb `lean-herdr llm` ist Sache des anderen Plans; hier wird die Datei
     weder angelegt noch entfernt noch umgeschrieben. Deshalb nennt das
     Aufraeum-Gate in Task 2 `bin/herdr-dispatch` und `bin/herdr-report`
     ausdruecklich statt `bin/herdr-` als Praefix — und deshalb ueberlebt das
     Verzeichnis `bin/` diesen Plan. Jede Formulierung, die hinterher „`bin/` ist
     weg" behauptet, ist falsch.
  4. **`bin/herdr-llm` bleibt darum auch in `tests/test_manifest.py`.** Es startet
     ein nacktes `python3` und faellt unter denselben Syntax-Floor wie die
     Plugin-Handler. Aus der dortigen `sources`-Liste verlassen **zwei von drei**
     `bin/`-Eintraegen die Pruefliste, nicht alle drei. Wer sie durch den blossen
     Paket-Glob ersetzt, loescht eine Pruefung, die noch etwas bewacht — und zwar
     lautlos, weil kein Test das Fehlen eines Tests meldet.
  Wer beide Plaene ausfuehrt, fuehrt sie **nacheinander** aus, nie nebeneinander:
  beide fassen `opencode.jsonc`, `.claude/settings.json`, `settings.py` und
  `.config/lean-herdr.toml` an — und diesen letzten Pfad gibt es nach Task 3
  nicht mehr.

@phase "task-1"
## Task 1: `lean_herdr/cli.py` — der Verb-Router und der Entry-Point

**Files:** Create `lean_herdr/cli.py`, `tests/test_cli.py`. Modify
`pyproject.toml`.
**Interfaces:** Produces `lean_herdr.cli.VERBS: dict[str, str]` und
`lean_herdr.cli.main(argv: list[str] | None = None) -> int`; ausserdem den
Konsolen-Entry-Point `lean-herdr = "lean_herdr.cli:main"`.
**Consumes:** `lean_herdr.dispatch.main`, `lean_herdr.report.main` — beide
**lazy**, nicht auf Modulebene.

Dieser Task ist rein additiv. `bin/herdr-dispatch` und `bin/herdr-report`
bleiben bestehen und funktionieren weiter; Task 2 raeumt sie ab.

### Der Router

Der Vertrag steht schon zweimal im Baum — `dispatch.main` (`dispatch.py:727-817`)
und `report.main` (`report.py:294-329`) schreiben beide eine JSON-Zeile und geben
immer 0 zurueck. Der Router baut nichts davon nach, er reicht durch.

@read lean_herdr/report.py mode=lines:294-329

Neue Datei `lean_herdr/cli.py` (verbatim, sie existiert noch nicht):

    """One binary, three verbs: `lean-herdr dispatch | report | workspace`.

    A router, nothing more. Every verb hands off to a `main(argv) -> int`
    that already exists and already keeps the house contract: one JSON line
    on stdout, `ok` as the only truth, exit ALWAYS 0. Rebuilding any of that
    here would be a second place for a rule that has one.

    The verb modules are imported ON THE CALL, not up here. `lean_herdr.
    workspace` reaches `lean_herdr.dispatch` and from there `ordercmd`; a
    top-level import of all three would make this router the place where
    that whole chain resolves, and a bare `lean-herdr report next` -- the
    call a worker makes on every single step -- would pay for it.
    """

    from __future__ import annotations

    import importlib
    import json
    import sys

    #: verb -> the module that owns it. The values are import PATHS, not
    #: modules: see the docstring on why nothing is imported up here.
    #: `workspace` joins in its own task; a verb without a module would be a
    #: crash disguised as a usage error.
    VERBS = {
        "dispatch": "lean_herdr.dispatch",
        "report": "lean_herdr.report",
    }

    USAGE = "usage: lean-herdr {dispatch|report} ...\n"


    def _usage(message: str) -> int:
        """A usage error is a JSON line and exit 0, never argparse's exit 2.

        Same reason as dispatch._Parser.error: the caller reads `ok` on
        stdout. An unknown verb that ended the process with exit 2 and one
        line on stderr would reach an orchestrator as no output at all --
        indistinguishable from a crash.
        """
        line = {"ok": False, "error": f"usage_error: {message}"}
        sys.stdout.write(json.dumps(line, ensure_ascii=False) + "\n")
        return 0


    def main(argv: list[str] | None = None) -> int:
        """Route `lean-herdr <verb> ...` to the verb's own main. Exit ALWAYS 0."""
        args = list(sys.argv[1:] if argv is None else argv)
        if not args:
            return _usage(f"no verb; expected one of {sorted(VERBS)}")
        verb, rest = args[0], args[1:]
        if verb in ("-h", "--help"):
            # --help goes to stdout as plain text, not as JSON: it is the one
            # output a human asked for directly. Same split argparse makes
            # between exit() and error().
            sys.stdout.write(USAGE)
            return 0
        module = VERBS.get(verb)
        if module is None:
            return _usage(f"unknown verb {verb!r}; expected one of {sorted(VERBS)}")
        return importlib.import_module(module).main(rest)


    if __name__ == "__main__":
        raise SystemExit(main())

### Der Entry-Point

@call patch("pyproject.toml", "ein [project.scripts]-Block hinter [project]")

Hinter dem `[project]`-Block, vor `[dependency-groups]`:

    [project.scripts]
    lean-herdr = "lean_herdr.cli:main"

### Die Tests

Neue Datei `tests/test_cli.py` (verbatim):

    """The verb router: routing, and the two ways of getting it wrong.

    Every verb's own main is tested by its own file. What is tested here is
    that the router reaches it with the REST of the arguments, and that a
    bad verb keeps the house contract instead of argparse's exit 2.
    """

    import json

    import pytest

    from lean_herdr import cli


    @pytest.mark.parametrize(("verb", "module"), sorted(cli.VERBS.items()))
    def test_each_verb_reaches_its_own_main_with_the_rest(monkeypatch, verb, module):
        seen = {}

        def fake_main(argv):
            seen["argv"] = argv
            return 0

        monkeypatch.setattr(f"{module}.main", fake_main)
        assert cli.main([verb, "--kind", "opencode"]) == 0
        assert seen["argv"] == ["--kind", "opencode"], "the verb must not travel on"


    def test_an_unknown_verb_is_a_json_line_and_exit_zero(capsys):
        """Exit 2 plus a line on stderr would reach the caller as no output."""
        assert cli.main(["does-not-exist"]) == 0
        answer = json.loads(capsys.readouterr().out)
        assert answer["ok"] is False
        assert answer["error"].startswith("usage_error: unknown verb")


    def test_no_verb_at_all_is_the_same_shape(capsys):
        assert cli.main([]) == 0
        answer = json.loads(capsys.readouterr().out)
        assert answer["ok"] is False
        assert "no verb" in answer["error"]


    def test_help_is_plain_text_for_a_human(capsys):
        assert cli.main(["--help"]) == 0
        assert capsys.readouterr().out.startswith("usage: lean-herdr")


    def test_every_verb_names_a_module_that_actually_imports():
        """A typo in VERBS would only surface on the call that needs it."""
        import importlib

        for verb, module in cli.VERBS.items():
            assert callable(importlib.import_module(module).main), verb

@call tdd(test_an_unknown_verb_is_a_json_line_and_exit_zero)

### Installieren und pruefen

Der Entry-Point muss auf dem PATH stehen, bevor Task 2 die Allowlists darauf
umstellt. Editierbar, sonst kostet jede Codeaenderung eine Neuinstallation:

    uv tool install --editable /home/tholo/Scripts/lean-herdr --force

    lean-herdr report next
    lean-herdr does-not-exist
    lean-herdr --help

**Expected:** Zeile 1 und 2 sind je eine JSON-Zeile mit `"ok"`; Zeile 2 traegt
`"usage_error: unknown verb 'does-not-exist'"`. Zeile 3 ist Klartext. Alle drei
enden mit Exit 0 — `echo $?` liefert `0`.

### Verify & Close

@call verify(lean_herdr/cli.py pyproject.toml tests/test_cli.py)
@call gate(lean_herdr/cli.py pyproject.toml tests/test_cli.py)
@call commit("lean_herdr/cli.py pyproject.toml tests/test_cli.py", "feat(cli): route lean-herdr dispatch and report through one entry point")
@call remember_decision("lean-herdr: `lean-herdr` is the console entry point (lean_herdr.cli:main); the verb modules are imported lazily on the call, because lean_herdr.workspace pulls dispatch -> ordercmd behind it and `lean-herdr report next` runs on every worker step")
@phase-end

@phase "task-2"
## Task 2: Ein Binary — `bin/` entfaellt, alle Aufrufstellen wandern

**Files:** Delete `bin/herdr-dispatch`, `bin/herdr-report`. Modify
`opencode.jsonc`, `.claude/settings.json`, `roles/orchestrator.md`,
`roles/builder.md`, `roles/reviewer.md`, `README.md`,
`tests/test_worker_permissions.py`, `tests/test_manifest.py`,
`tests/test_role_prohibitions.py`, `tests/test_roles.py`,
`tests/test_config_files.py`, `tests/test_worktree.py`,
`tests/test_dispatch.py`, `tests/test_dispatch_await.py`,
`tests/test_dispatch_uncovered_paths.py`, `tests/test_settings.py`,
`lean_herdr/dispatch.py`, `lean_herdr/report.py`, `lean_herdr/settings.py`,
`lean_herdr/worktree.py`, `lean_herdr/bus.py`, `lean_herdr/ordercmd.py`,
`lean_herdr/orderlog.py`.
**Interfaces:** Ein neuer Test in `tests/test_role_prohibitions.py` (unten);
sonst kein neuer Code. Die Ersetzung ist mechanisch und vollstaendig:
`bin/herdr-dispatch` -> `lean-herdr dispatch`, `bin/herdr-report` ->
`lean-herdr report`. Nach diesem Task nennt **keine** versionierte Datei
ausserhalb `docs/` mehr einen dieser beiden Pfade. `bin/herdr-llm` bleibt
unberuehrt — die Datei **existiert** (versioniert seit `14bf07c`), gehoert dem
LLM-Plan, und wird hier weder geloescht noch umgeschrieben.
**Consumes:** den Entry-Point aus Task 1.

@call recall_context("lean-herdr console entry point lean-herdr cli verbs")

Dieser Task ist ein einziger, atomarer Bruch. Jede Teil-Ersetzung allein
laesst die Suite rot: die Rollentexte nennen Kommandos, die Allowlists
freigeben, und beide Seiten haengen an denselben Tests.

### Der Ausgangsbestand

    grep -rn 'bin/herdr-dispatch\|bin/herdr-report' \
      --exclude-dir=docs --exclude-dir=.git --exclude-dir=.pytest_cache \
      --exclude-dir=__pycache__ .

**Expected:** 82 Treffer in 18 Dateien (gemessen 2026-09-03; die erste Fassung
dieses Plans zaehlte 87 in 21, bevor der LLM-Plan Zeilen umschrieb — eine
Abweichung nach unten ist kein Alarm, eine Datei mehr als hier gelistet schon).
Am Ende dieses Tasks liefert derselbe Aufruf **null** Treffer.

Das Muster nennt die beiden Programme ausdruecklich statt `bin/herdr-` als
Praefix: `lean_herdr/llm.py`, `lean_herdr/settings.py`, `README.md`,
`tests/test_llm.py` und `.config/lean-herdr.toml` erwaehnen `bin/herdr-llm`, das
dem LLM-Plan gehoert und hier nicht angefasst wird. Ein
Praefix-Gate waere darum nie gruen zu bekommen, ohne fremde Arbeit
mitzuschleifen. `.pytest_cache` faellt heraus, weil dort die Test-IDs des
letzten Laufs liegen — dieselbe Falle, die `test_language.py` mit `git ls-files`
umgeht.

### Die Allowlists

@call patch("opencode.jsonc", "die bash-Bloecke aller drei Agenten")

Im Block `agent.orchestrator.permission.bash` wird aus
`"bin/herdr-dispatch *": "allow"`:

    "lean-herdr dispatch *": "allow",

In `agent.builder.permission.bash` und `agent.reviewer.permission.bash` werden
aus den sechs `bin/herdr-report`-Zeilen:

    "lean-herdr report next": "allow",
    "lean-herdr report show *": "allow",
    "lean-herdr report start *": "allow",
    "lean-herdr report done *": "allow",
    "lean-herdr report fail *": "allow",
    "lean-herdr report ask *": "allow",

Der Kommentar ueber dem Builder-Block wird um den neuen Grund ergaenzt — er ist
der Kern dieses Tasks und nicht laenger nur eine Vorsichtsmassnahme:

    // The worker's order path is a CLI now, so both workers need a shell
    // permission they never had -- granted per subcommand. Two reasons, and
    // the second one is new: `lean-herdr report *` would let through anything
    // behind the program name, AND `lean-herdr *` would hand the worker the
    // dispatch verb. Until this commit the separation was structural -- the
    // builder's allowlist simply never named the other program, because there
    // was one. Now the gate is the only separation left.

@call patch(".claude/settings.json", "die sechs report-Eintraege in `permissions.allow`")

**Nur diese sechs Zeilen, kein Ersatz der Datei.** `permissions.allow` traegt
**neun** Eintraege: hinter den sechs stehen `Bash(git add:*)`,
`Bash(uv run pytest:*)` und `Bash(wt step commit:*)`
(`.claude/settings.json:10-12`), und alle drei sind festgenagelt —
`tests/test_worker_permissions.py::CLAUDE_BUILDER_TOOLING` (`:167-171`) und
`::test_the_claude_builder_may_commit_through_worktrunk` (`:147-153`). Wer den
Block unten als ganze Datei schreibt, macht drei Tests rot und nimmt dem
Claude-Builder gleichzeitig das Recht zu committen und zu testen.

          "Bash(lean-herdr report next)",
          "Bash(lean-herdr report show:*)",
          "Bash(lean-herdr report start:*)",
          "Bash(lean-herdr report done:*)",
          "Bash(lean-herdr report fail:*)",
          "Bash(lean-herdr report ask:*)",

### Die Rollentexte

@read roles/orchestrator.md mode=anchored
@read roles/builder.md mode=anchored
@read roles/reviewer.md mode=anchored

@call patch("roles/orchestrator.md", "jedes `bin/herdr-dispatch` und `bin/herdr-report`")
@call patch("roles/builder.md", "jedes `bin/herdr-report`")
@call patch("roles/reviewer.md", "jedes `bin/herdr-report`")

Rein mechanisch, ohne jede Umformulierung: `bin/herdr-dispatch` ->
`lean-herdr dispatch`, `bin/herdr-report` -> `lean-herdr report`. Der Satz in
`roles/orchestrator.md:129` nennt die erlaubten Programme und wird dabei
praeziser, nicht laenger:

    Nothing but `herdr`, `wt`, `git` and `lean-herdr dispatch` is allowed

### Die Tests, die daran haengen

@call patch("tests/test_worker_permissions.py", "opencode_key, claude_key, die Wildcard-Tests und der Praefix-Abgleich")

`opencode_key()` und `claude_key()` bekommen das neue Programm:

    def opencode_key(command: str) -> str:
        """One pattern per subcommand -- a wildcard behind the program name
        would let through anything at all. `next` is the only one that takes no
        flags, so it is the only one without a trailing ` *`.
        """
        return (
            "lean-herdr report next"
            if command == "next"
            else f"lean-herdr report {command} *"
        )


    def claude_key(command: str) -> str:
        return (
            "Bash(lean-herdr report next)"
            if command == "next"
            else f"Bash(lean-herdr report {command}:*)"
        )

`test_the_permission_is_never_a_bare_wildcard` wird ersetzt — es prueft jetzt
den Fallstrick, der mit dem einen Binary entsteht:

    def test_the_permission_is_never_a_bare_wildcard():
        """One binary means the gate is the ONLY separation left.

        Before this, `herdr-dispatch` and `herdr-report` were two programs,
        and the builder's allowlist separated them by simply never naming the
        first. Now a sloppy `lean-herdr *` hands the builder the orchestrator's
        own verb -- `order`, `answer`, `cancel` and `remember` included.
        """
        for role in WORKERS:
            allowed = opencode()["agent"][role]["permission"]["bash"]
            for wildcard in ("lean-herdr *", "lean-herdr*", "lean-herdr report *"):
                assert wildcard not in allowed, f"{role}: {wildcard} is too wide"
        for entry in claude_allow():
            assert entry not in ("Bash(lean-herdr:*)", "Bash(lean-herdr)"), entry


    def test_no_worker_gate_ever_names_the_dispatch_verb():
        """The verb that belongs to the orchestrator, and to nobody else.

        `dispatch order` writes work orders and `dispatch answer` closes an
        input-required round trip. A worker holding either could hand itself
        an order under the sender the other workers trust.
        """
        for role in WORKERS:
            allowed = opencode()["agent"][role]["permission"]["bash"]
            offenders = [key for key in allowed if "dispatch" in key]
            assert not offenders, f"{role} may run the dispatch verb: {offenders}"
        offenders = [key for key in claude_allow() if "dispatch" in key]
        assert not offenders, f".claude/settings.json: {offenders}"

Und der Praefix-Abgleich in
`test_no_permission_file_names_a_subcommand_the_cli_does_not_have` folgt den
neuen Praefixen. **Vier** Stellen, nicht zwei: `removeprefix` und `startswith`
tragen unterschiedliche Formen, und wer nur die `removeprefix`-Zeilen anfasst,
laesst den Filter auf einem Praefix stehen, den keine Regel mehr erfuellt — die
Menge waere leer und der Test gruen aus dem falschen Grund.

    named = {
        key.removeprefix("lean-herdr report ").removesuffix(" *")
        for key in opencode()["agent"][role]["permission"]["bash"]
        if key.startswith("lean-herdr report")
    }
    ...
    named = {
        key.removeprefix("Bash(lean-herdr report ").removesuffix(":*)").removesuffix(")")
        for key in claude_allow()
        if key.startswith("Bash(lean-herdr report")
    }

@call patch("tests/test_manifest.py", "die sources-Liste und ihren Docstring")

**Zwei** der **drei** `bin/`-Eintraege verlassen die Pruefliste. `bin/herdr-llm`
bleibt darin — es startet weiterhin ein nacktes `python3` und ist genau das, wofuer
dieser Test da ist. Wer die Liste durch den blossen Paket-Glob ersetzt, loescht
lautlos eine Pruefung, die noch etwas bewacht. Der Docstring sagt beides:

    def test_the_package_parses_on_the_python3_the_manifest_may_meet():
        """Every command in the manifest spawns a bare `python3`.

        That interpreter is whatever the host provides, never the pinned one
        from `uv`. Syntax it cannot parse kills the handler at IMPORT time,
        before main() can keep its "exit always 0" promise. PEP 758's
        parenthesis-free `except A, B:` was such a case. ast.parse only
        parses, it runs nothing.

        `bin/herdr-dispatch` and `bin/herdr-report` used to stand in this list
        for the same reason and are gone: as the `lean-herdr` entry point the
        CLIs run under the INSTALLED interpreter. `bin/herdr-llm` stays --
        worktrunk starts it as a bare `python3` script, not through an entry
        point. The package glob stays too: `handlers.py` and everything it
        imports is still reached by a bare `python3`, and that now includes
        `workspace.py`.
        """
        assert all(e["command"][0] == "python3" for e in manifest()["events"]), (
            "the floor below only matters as long as the manifest spawns python3"
        )
        sources = [
            *sorted((ROOT / "lean_herdr").glob("*.py")),
            ROOT / "bin" / "herdr-llm",
        ]

@call patch("tests/test_role_prohibitions.py", "die MANDATORY_SENTENCES mit bin/-Pfaden")
@call patch("tests/test_roles.py", "test_workers_work_through_herdr_report")
@call patch("tests/test_config_files.py", "test_orchestrator_may_dispatch_wt_and_herdr und die README-Liste")

In `test_config_files.py`:

    def test_orchestrator_may_dispatch_wt_and_herdr():
        bash = load_jsonc(ROOT / "opencode.jsonc")["agent"]["orchestrator"]["permission"]["bash"]
        assert bash["lean-herdr dispatch *"] == "allow"
        assert bash["wt *"] == "allow"
        assert bash["herdr *"] == "allow"

Und in `test_readme_names_every_runtime_dependency` wird
`"lean-ctx allow herdr-report"` zu `"lean-ctx allow lean-herdr"`, sowie
`"bin/herdr-dispatch order", "bin/herdr-report"` zu
`"lean-herdr dispatch order", "lean-herdr report"`.

### Der Test, den es noch nicht gibt: `--role-file`

`roles/orchestrator.md:14` schreibt dem Orchestrator die Zeile

    lean-herdr dispatch <role> --kind <claude|opencode> --model <model> \
      --role-file roles/<role>.md [--worktree <branch>] [--profile <p>]

vor, und **kein einziger Test beruehrt diesen Pfad**. `dispatch` reicht ihn
unveraendert an `--append-system-prompt-file` bzw. an den opencode-Agentennamen
weiter. Zeigt er ins Leere, startet der Worker ohne Prompt, meldet nie, und der
Orchestrator laeuft in den Warte-Timeout mit `no_reply` — bei **gruener Suite**.

Task 3 verschiebt die Rollentexte genau dorthin. Der Test kommt deshalb hier,
eine Task zu frueh: mit dem heutigen Pfad ist er sofort gruen, und er wird rot
in dem Moment, in dem Task 3 die Dateien bewegt, ohne die Zeile nachzuziehen.
Das ist der einzige Zeitpunkt, an dem er etwas beweist.

@call patch("tests/test_role_prohibitions.py", "ROOT und der neue --role-file-Test")

Neben `ROLES` kommt eine Wurzel dazu — der Pfad in der Zeile ist relativ zum
Repo, nicht zum Rollenverzeichnis:

    ROOT = Path(__file__).resolve().parent.parent

Und ans Ende der Datei:

    def test_the_role_file_path_the_orchestrator_types_actually_resolves():
        """A stale --role-file is a GREEN suite and a dead run.

        dispatch hands this path straight to `--append-system-prompt-file`
        (claude) or reads its stem as the agent name (opencode). Pointing
        nowhere, the worker starts without a prompt, never reports, and the
        orchestrator hits the wait-mode timeout with `no_reply`. Every other
        test in this file pins a COMMAND; this one pins a path, and nothing
        else did.
        """
        text = (ROLES / "orchestrator.md").read_text(encoding="utf-8")
        hit = re.search(r"--role-file (\S+)", text)
        assert hit, "the orchestrator prompt no longer names a --role-file path"
        template = hit.group(1)
        assert "<role>" in template, f"{template!r} names no role placeholder"
        for role in ("orchestrator", "builder", "reviewer"):
            path = ROOT / template.replace("<role>", role)
            assert path.is_file(), f"{template} does not resolve for {role}: {path}"

@call tdd(test_the_role_file_path_the_orchestrator_types_actually_resolves)

### Die Kommentare in der Produktion

Sieben Module nennen die alten Pfade in Docstrings und Kommentaren. Sie werden
falsch, sobald das Programm global ist — und `worktree.wt_switch` traegt die
teuerste dieser Aussagen, weil sie eine Verhaltensentscheidung begruendet.

@call patch("lean_herdr/worktree.py", "der --base-Absatz im wt_switch-Docstring")

Der Absatz nennt heute `bin/herdr-report` als Grund fuer `base="@"`. Dieser Grund
faellt weg; der andere bleibt und traegt allein:

    `--no-cd` because the script doesn't change directory; `--yes` because no
    human is sitting at the approval prompt. `base` defaults to `@` (the
    currently checked-out branch) rather than `wt`'s own default (the repo's
    default branch): the order-log path is self-referential -- a worker reads
    its role prompt from `.lean-ctx/lean-herdr/roles/`, which is introduced by
    the orchestrator's own branch. A worktree branched off `main` structurally
    lacks those files, so the worker starts without a prompt, never reports,
    and the orchestrator runs into the wait-mode timeout with `no_reply`.

    The report CLI itself is no longer part of this argument: `lean-herdr`
    lives on the PATH, not in the tree. Measured before that move: `wt switch
    --create feat/probe` with no `--base` produced a worktree at `main`'s HEAD,
    missing `bin/herdr-report`, `.claude/settings.json` and
    `lean_herdr/orderlog.py` alike -- the second and third of those still
    travel in the branch today.

@call patch("tests/test_worktree.py", "der Kommentar in test_wt_switch_passes_base_at_by_default")

Die restlichen sind Wortersetzungen im Kommentar, ohne Verhaltensbezug — bis auf
die beiden `prog=`-Werte und den einen Test, der auf einem von ihnen steht. Die
Zeilennummern sind am 2026-09-03 nachgemessen; `dispatch.py` ist seit der ersten
Fassung dieses Plans um rund 45 Zeilen gewachsen, die uebrigen Dateien stehen
unveraendert:

| Datei | Stelle |
|---|---|
| `lean_herdr/dispatch.py` | `:78`, `:96-97`, `:274`, `:541` (`prog=`), `:744` |
| `lean_herdr/report.py` | `:9`, `:265` (`prog=`), `:297` |
| `lean_herdr/settings.py` | `:20` |
| `lean_herdr/bus.py` | `:3` |
| `lean_herdr/ordercmd.py` | `:71` |
| `lean_herdr/orderlog.py` | `:287` |
| `tests/test_dispatch.py` | `:370` |
| `tests/test_dispatch_uncovered_paths.py` | `:15` (Modul-Docstring) |
| `tests/test_settings.py` | `:194` — kam mit dem LLM-Plan dazu |
| `opencode.jsonc` | `:41` und `:53` — **zwei** Kommentarzeilen, nicht eine |

Die beiden `prog=`-Werte werden `"lean-herdr dispatch"` und
`"lean-herdr report"` — sie stehen in jeder `--help`-Ausgabe, und ein Programm,
das sich anders nennt als es aufgerufen wird, schickt jeden Leser in die Irre.

**Und genau daran haengt ein Test, der sonst still rot wird.**
`tests/test_dispatch_await.py:492` prueft `assert "herdr-dispatch" in
capsys.readouterr().out`. Der neue Wert `lean-herdr dispatch` enthaelt diese
Zeichenkette **nicht** — dazwischen steht ein Leerzeichen, kein Bindestrich. Die
Zeile wandert mit:

    assert "lean-herdr dispatch" in capsys.readouterr().out

### Die README

@call patch("README.md", "der Freigabe-Absatz und der Arbeitsauftrags-Abschnitt")

Der lange Absatz ueber die Pfad-Ausnahme des Shell-Gates verliert seine
Grundlage — die Ausnahme galt, **weil** das Skript im Projektwurzelverzeichnis
lag. Er schrumpft auf drei Zeilen und eine dritte Freigabe:

    Three approvals in lean-ctx, without which an agent under shell gating can
    steer neither Herdr nor worktrunk nor its own order path:

        lean-ctx allow herdr
        lean-ctx allow wt
        lean-ctx allow lean-herdr

    `lean-herdr` needs its own line now. The gate normalises a command to its
    basename before comparing, and until this change the CLIs lived inside the
    project root, where a script is carried by its path rather than by the
    allowlist. On the PATH that exemption is gone -- and it was never a
    property worth relying on.

Der Abschnitt „The work-order path" bekommt die neuen Kommandozeilen:

        lean-herdr dispatch order    --to <agent> [--after o-…] --message "…"
        lean-herdr dispatch answer   --task-id o-… --message "…"
        lean-herdr dispatch cancel   --task-id o-… --message "…"
        lean-herdr dispatch remember --key lean-herdr/<branch> --message "…"

    and the worker answers with

        lean-herdr report next | show | start | done | fail | ask

Die Zeile in der Abhaengigkeitstabelle wird ebenfalls praezise: `python3` ist
jetzt „runtime of the plugin handlers"; die CLIs laufen unter dem
Interpreter, den `uv tool install` mitbringt.

### Die Skripte loeschen

    git rm bin/herdr-dispatch bin/herdr-report

Keine Shims. Zwei Schreibweisen in vier Allowlists zu pflegen waere genau die
Doppelung, gegen die `test_worker_permissions.py` ueberhaupt existiert.

### Verify & Close

    grep -rn 'bin/herdr-dispatch\|bin/herdr-report' \
      --exclude-dir=docs --exclude-dir=.git --exclude-dir=.pytest_cache \
      --exclude-dir=__pycache__ . ; echo rc=$?

**Expected:** keine Ausgabe, `rc=1`. `docs/` ist ausgenommen — die Planungs- und
Spec-Dokumente sind Aufzeichnungen ihrer Zeit und werden nicht nachgezogen.

@call verify(opencode.jsonc .claude/settings.json roles README.md tests lean_herdr)
@call review_change()
@call gate(.)
@call commit(".", "refactor: replace bin/herdr-dispatch and bin/herdr-report with the lean-herdr verbs")
@call remember_decision("lean-herdr: with one binary the ONLY separation between builder and dispatch is the agent gate -- test_worker_permissions.py forbids `lean-herdr *`, `lean-herdr*`, `lean-herdr report *`, `Bash(lean-herdr:*)` and any worker key containing `dispatch`")
@phase-end

@phase "task-3"
## Task 3: `lean_herdr/templates/` — eine Wahrheit, und der Umzug der Ablage

**Files:** Create `lean_herdr/templates/config.toml`,
`lean_herdr/templates/roles/orchestrator.md`,
`lean_herdr/templates/roles/builder.md`,
`lean_herdr/templates/roles/reviewer.md`,
`lean_herdr/templates/opencode.jsonc`, `lean_herdr/templates/settings.json`,
`lean_herdr/templates/wt.toml`, `lean_herdr/templates/lean-ctx-policy.js`,
`tests/test_templates.py`. Move `.config/lean-herdr.toml` ->
`.lean-ctx/lean-herdr/config.toml`, `roles/` -> `.lean-ctx/lean-herdr/roles/`.
Modify `lean_herdr/settings.py`, `lean_herdr/llm.py`, `opencode.jsonc`,
`.lean-ctx/lean-herdr/roles/orchestrator.md`, `README.md`,
`tests/test_roles.py`, `tests/test_role_prohibitions.py`,
`tests/test_config_files.py`, `tests/test_settings.py`, gegebenenfalls
`pyproject.toml`.
**Interfaces:** Produces `lean_herdr.settings.SETTINGS_PATH ==
Path(".lean-ctx") / "lean-herdr" / "config.toml"` und das Vorlagenverzeichnis
`lean_herdr/templates/` mit genau acht Dateien.
**Consumes:** nichts Neues.

### Die Ablage

`.lean-ctx/` ist bereits die Konvention „ein Unterordner pro lean-Werkzeug" —
`lean-md` wohnt dort schon als `.lean-ctx/lean-md/`. lean-herdr zieht als
Geschwister ein. Die fremden Suchpfade bleiben, wo ihre Eigentuemer suchen:
`opencode.jsonc`, `.claude/settings.json`, `.config/wt.toml` und
`.opencode/plugins/lean-ctx-policy.js` sind unverschiebbar.

    mkdir -p .lean-ctx/lean-herdr && git mv .config/lean-herdr.toml .lean-ctx/lean-herdr/config.toml && git mv roles .lean-ctx/lean-herdr/roles

    git check-ignore -v .lean-ctx/lean-herdr/roles/builder.md ; echo rc=$?

**Expected:** keine Ausgabe, `rc=1`. Waere die Datei ignoriert, traege kein
Worktree die Rollentexte, und jeder Dispatch liefe still ins Leere. Die Falle ist
gemessen und dokumentiert: eine Zeile `.lean-ctx/` in der `.gitignore` liesse
sich **nicht** mit `!.lean-ctx/lean-herdr/` allein zuruecknehmen — git kann eine
Datei nicht wieder einschliessen, deren Elternverzeichnis ausgeschlossen ist.
Nur `.lean-ctx/*` plus die Negation wirkt. Dieser Task fasst die `.gitignore`
nicht an; sie traegt die Zeile heute nicht.

### Der neue Config-Pfad

@call patch("lean_herdr/settings.py", "SETTINGS_PATH und sein Kommentar")

    #: RELATIVE to the repo root, not to $PWD. The caller joins it onto
    #: canonical_root() -- otherwise the config silently fails to load as soon
    #: as `lean-herdr dispatch` runs from a subdirectory, and the promise "a
    #: wrong file never stays silent" would be broken.
    #:
    #: `.lean-ctx/<tool>/` is the convention of this tool family -- lean-md is
    #: already there. Not `.config/`: that directory belongs to whoever else
    #: writes into it, and `init` has to be able to write ours without
    #: touching theirs.
    SETTINGS_PATH = Path(".lean-ctx") / "lean-herdr" / "config.toml"

### Die Rollentexte in `opencode.jsonc`

@call patch("opencode.jsonc", "die drei prompt-Pfade")

    "prompt": "{file:./.lean-ctx/lean-herdr/roles/orchestrator.md}",
    "prompt": "{file:./.lean-ctx/lean-herdr/roles/builder.md}",
    "prompt": "{file:./.lean-ctx/lean-herdr/roles/reviewer.md}",

@call patch("tests/test_config_files.py", "test_both_opencode_agents_have_role_text_a_cap_and_a_guard")

        assert agent["prompt"] == f"{{file:./.lean-ctx/lean-herdr/roles/{name}.md}}"

### Die drei anderen Stellen, die auf `roles/` zeigen

Der `{file:...}`-Pfad ist nicht der einzige. Drei weitere nennen das alte
Verzeichnis, und die erste davon ist die gefaehrlichste, weil sie eine
Kommandozeile ist, die ein Agent wirklich tippt.

@call patch(".lean-ctx/lean-herdr/roles/orchestrator.md", "die --role-file-Zeile in Schritt 1")

    lean-herdr dispatch <role> --kind <claude|opencode> --model <model> \
      --role-file .lean-ctx/lean-herdr/roles/<role>.md \
      [--worktree <branch>] [--profile <p>]

Der Test aus Task 2,
`test_the_role_file_path_the_orchestrator_types_actually_resolves`, ist bis zu
dieser Aenderung **rot** — er ist der Grund, warum er eine Task frueher entstand.
Weil `test_role_prohibitions.py` seit Task 3 die Vorlage liest, wandert die
Zeile in **beide** Fassungen; der Gleichheitstest haelt das fest.

@call patch("README.md", "die vier Erwaehnungen der Rollentexte und des Config-Pfads")

Vier Stellen, am 2026-09-03 nachgemessen — die erste Fassung dieses Plans kannte
nur zwei, weil der LLM-Plan den `[llm]`-Abschnitt seither dazwischengeschoben hat:
`README.md:201-202` nennt `roles/builder.md` und `roles/reviewer.md` als Traeger
der Zeile `ORCHESTRATOR = orch`; `:91` nennt `.config/lean-herdr.toml` als den Ort
des `[llm]`-Blocks; `:150` nennt ihn in einem Kommentarbeispiel als „die dauerhafte
Stelle"; `:225` nennt ihn als die ausgelieferte, vollstaendig auskommentierte
Konfigurationsdatei. Alle vier wandern hier mit — nicht erst in Task 4, wo der
Bootstrap-Abschnitt ohnehin umgeschrieben wird: eine README, die einen Pfad nennt,
den es seit dem letzten Commit nicht mehr gibt, ist genau die Art Bruch, die dieser
Task zumacht.

@call patch("lean_herdr/llm.py", "die fuenf Erwaehnungen von .config/lean-herdr.toml")

`llm.py:46`, `:54`, `:375`, `:387` und `:657` nennen den alten Pfad im Text —
**fuenf** Stellen, nicht die drei der ersten Planfassung, und `:657` ist kein
Docstring, sondern der argparse-Hilfetext von `--model`: ihn stehenzulassen hiesse,
einem Benutzer in `--help` einen Pfad zu nennen, den es nicht mehr gibt. Das
**Verhalten** folgt dem Umzug von selbst — `file_settings()` liest `SETTINGS_PATH`
aus `settings` und weiss nichts von einem Literal.

`:387` traegt zusaetzlich einen Zeilenanker auf die Nachbardatei: „`.config/`
lookup from there would miss (settings.py:20-24)". Der Kommentar, den er meint,
steht heute bei `settings.py:18-22` und waechst durch den Patch oben auf `:18-27`;
der Anker wandert entsprechend mit, sonst zeigt er nach diesem Task auf
`PROFILE_BY_ROLE`.

`llm.py:378` nennt `bin/herdr-llm` und bleibt unberuehrt: dieser Pfad gehoert dem
LLM-Plan, und die Datei existiert.

### Die Vorlagen

Alle acht Dateien sind **byte-genaue Kopien** der eingecheckten Fassungen. Nichts
wird beim Kopieren umgeschrieben; die Vorlage ist die Quelle, und dieses Repo
haelt eine Kopie davon.

    mkdir -p lean_herdr/templates/roles && cp .lean-ctx/lean-herdr/config.toml lean_herdr/templates/config.toml && cp .lean-ctx/lean-herdr/roles/orchestrator.md .lean-ctx/lean-herdr/roles/builder.md .lean-ctx/lean-herdr/roles/reviewer.md lean_herdr/templates/roles/ && cp opencode.jsonc lean_herdr/templates/opencode.jsonc && cp .claude/settings.json lean_herdr/templates/settings.json && cp .config/wt.toml lean_herdr/templates/wt.toml && cp .opencode/plugins/lean-ctx-policy.js lean_herdr/templates/lean-ctx-policy.js

### Der Test, der die beiden Fassungen zusammenhaelt

Neue Datei `tests/test_templates.py` (verbatim):

    """The template in the wheel is the source; this repo's copy is a copy.

    `lean-herdr workspace init` writes from lean_herdr/templates/. This repo
    uses itself, so every file init would write also exists here as a
    checked-in copy at the place init would put it. Two spellings of one text
    is exactly the drift this test exists to prevent: without it,
    test_role_prohibitions.py would guard the copy while `init` shipped the
    other fassung into every new project -- and the test that watches the
    prohibitions would watch the wrong file.
    """

    from pathlib import Path

    import pytest

    ROOT = Path(__file__).resolve().parents[1]
    TEMPLATES = ROOT / "lean_herdr" / "templates"

    #: template (inside the package) -> the copy this repo checks in.
    #: This table moves into lean_herdr/initcmd.py as LAYOUT once `init`
    #: exists; then it is imported from there and lives exactly once.
    PAIRS = {
        "config.toml": ".lean-ctx/lean-herdr/config.toml",
        "roles/orchestrator.md": ".lean-ctx/lean-herdr/roles/orchestrator.md",
        "roles/builder.md": ".lean-ctx/lean-herdr/roles/builder.md",
        "roles/reviewer.md": ".lean-ctx/lean-herdr/roles/reviewer.md",
        "opencode.jsonc": "opencode.jsonc",
        "settings.json": ".claude/settings.json",
        "wt.toml": ".config/wt.toml",
        "lean-ctx-policy.js": ".opencode/plugins/lean-ctx-policy.js",
    }


    @pytest.mark.parametrize(("template", "copy"), sorted(PAIRS.items()))
    def test_template_and_checked_in_copy_are_byte_identical(template, copy):
        assert (TEMPLATES / template).read_bytes() == (ROOT / copy).read_bytes(), (
            f"{template} and {copy} have drifted apart"
        )


    def test_no_template_without_a_pair_and_no_pair_without_a_template():
        """Both directions: a stray file ships to strangers unannounced."""
        on_disk = {
            p.relative_to(TEMPLATES).as_posix()
            for p in TEMPLATES.rglob("*")
            if p.is_file()
        }
        assert on_disk == set(PAIRS), f"unpaired: {sorted(on_disk ^ set(PAIRS))}"

@call tdd(test_template_and_checked_in_copy_are_byte_identical)

### Die Tests, die jetzt die Vorlage pruefen

`test_roles.py` und `test_role_prohibitions.py` bewachen ab hier die **Quelle**,
nicht die Kopie — die Kopie haelt der Test oben byte-gleich.

@call patch("tests/test_roles.py", "die ROLES-Konstante")
@call patch("tests/test_role_prohibitions.py", "die ROLES-Konstante")

    ROLES = Path(__file__).resolve().parents[1] / "lean_herdr" / "templates" / "roles"

@call patch("tests/test_settings.py", "test_the_shipped_template_changes_nothing")

Der Test liest ab hier die Vorlage — sie ist, was ausgeliefert wird:

    def test_the_shipped_template_changes_nothing(tmp_path):
        """As SHIPPED the file is fully commented out -- that is its purpose.

        Read the TEMPLATE from git, not the working tree and not this repo's
        own copy: the template is what `lean-herdr workspace init` writes into
        a stranger's project, and the first operator who uncomments a line
        must not get a red suite plus a dirty tree. If git cannot answer,
        skip -- a skip is honest, a false pass is not.
        """
        root = Path(__file__).resolve().parents[1]
        template = Path("lean_herdr") / "templates" / "config.toml"
        try:
            shipped = subprocess.run(
                ["git", "show", f"HEAD:{template.as_posix()}"],
                cwd=root,
                capture_output=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            pytest.skip(f"git is unavailable: {exc}")
        if shipped.returncode != 0:
            pytest.skip(f"{template} is not in HEAD yet")
        path = tmp_path / template.name
        path.write_bytes(shipped.stdout)
        data = read_settings(path)
        assert data == {}, f"{template} carries active values: {sorted(data)}"
        assert settings_for("builder", data) == RoleSettings(profile="standard")
        assert settings_for("reviewer", data) == RoleSettings(profile="standard")
        assert settings_for("orchestrator", data) == RoleSettings(profile="minimal")

Beim ersten Lauf skippt dieser Test genau einmal — die Vorlage ist noch nicht in
`HEAD`. Nach dem Commit dieses Tasks ist er gruen.

### Liegen die Vorlagen wirklich im Wheel?

Eine Annahme, die geprueft und nicht geglaubt wird: hatchling nimmt
Nicht-Python-Dateien unterhalb des Paketverzeichnisses ueblicherweise mit. Ein
`init`, dem im fremden Projekt die Vorlagen fehlen, waere der erste Fehler, den
ein neuer Benutzer saehe.

    uv build --wheel && python3 -c "import glob,zipfile;w=sorted(glob.glob('dist/*.whl'))[-1];print(w);print('\n'.join(sorted(n for n in zipfile.ZipFile(w).namelist() if '/templates/' in n)))"

**Expected:** acht Zeilen unter `lean_herdr/templates/` — `config.toml`,
`lean-ctx-policy.js`, `opencode.jsonc`, `roles/builder.md`,
`roles/orchestrator.md`, `roles/reviewer.md`, `settings.json`, `wt.toml`.

Fehlen sie, bekommt `pyproject.toml` unter `[tool.hatch.build.targets.wheel]`:

    # Measured, not assumed: without this line the wheel carried no
    # templates/, and `lean-herdr workspace init` failed in a stranger's
    # project on its very first file.
    force-include = { "lean_herdr/templates" = "lean_herdr/templates" }

    rm -rf dist

### Verify & Close

@call verify(lean_herdr/settings.py opencode.jsonc tests)
@call gate(.)
@call commit(".", "refactor: move config and role prompts to .lean-ctx/lean-herdr and ship them as templates")
@call remember_decision("lean-herdr: SETTINGS_PATH is .lean-ctx/lean-herdr/config.toml, role prompts live in .lean-ctx/lean-herdr/roles/, and every file `init` writes exists as a byte-identical template under lean_herdr/templates/ -- tests/test_templates.py holds the two together")
@phase-end

@phase "task-4"
## Task 4: `[workspace]`, der geteilte Kern, `workspace up` und der Tastendruck

**Files:** Create `lean_herdr/workspace.py`, `tests/test_workspace.py`. Modify
`lean_herdr/settings.py`, `lean_herdr/handlers.py`, `lean_herdr/ordercmd.py`,
`lean_herdr/dispatch.py`, `lean_herdr/cli.py`,
`lean_herdr/templates/config.toml`, `.lean-ctx/lean-herdr/config.toml`,
`tests/test_settings.py`, `tests/test_handlers.py`, `tests/test_cli.py`,
`README.md`.
**Interfaces:** Produces in `lean_herdr.settings`: `KINDS`,
`ORCHESTRATOR_AGENT`, `WorkspaceSettings` (`label`/`kind`/`model`, alle `str`),
`WORKSPACE_ALLOWED`, `workspace_settings(data=None) -> WorkspaceSettings`; und
in `lean_herdr.workspace`: `UsageError`-basiertes `_Parser`,
`find_workspace(herdr, root, listing) -> str | None`,
`create_workspace(herdr, root, *, settings, env) -> str | None`,
`start_orchestrator(*, herdr, root, settings, profile, workspace_id,
ready_timeout_s, waiter=wait_for_agent_id) -> dict[str, Any]`,
`workspace_up(*, root=None, herdr=None) -> dict[str, Any]`, `build_parser()`,
`main(argv=None) -> int`.
**Consumes:** `lean_herdr.bus.{BusError, canonical_root}`,
`lean_herdr.dispatch.{UsageError, wait_for_agent_id}`,
`lean_herdr.herdr.Herdr`, `lean_herdr.settings.*`,
`lean_herdr.worktree.anchor_pane`.

@call recall_context("lean-herdr SETTINGS_PATH .lean-ctx/lean-herdr templates")

### Schritt 0: die eine Messung, die die Spec verlangt

Traegt die Wurzel-Pane eines frisch erzeugten Workspace das `--env` von
`workspace create`? Das Ergebnis **verzweigt den Code nicht** (siehe Global
Constraints), aber es beantwortet, ob der Split eine ueberfluessige Pane
erzeugt — und das ist ein Befund, den ein spaeterer Schnitt braucht.

`herdr pane process-info` liefert kein `env`, aber ein `shell_pid`; unter Linux
ist `/proc/<pid>/environ` die exakte Antwort. Das Skript unten laeuft ueber
`ctx_execute(language="python")`, **nicht** als `python3 - <<'PY'`: unter
`shell_strict_mode = true` lehnt das Shell-Gate jede Pipe in einen nackten
Interpreter permanent ab. Es durchlaeuft die Kette ohne Abschreiben und raeumt
hinter sich auf:

    mkdir -p /tmp/lh-env-probe && git -C /tmp/lh-env-probe init -q

Dann, als Python:

    import json, subprocess

    def herdr(*args):
        out = subprocess.run(["herdr", *args], capture_output=True, text=True,
                             timeout=30, check=False).stdout
        return json.loads(out)

    created = herdr("workspace", "create", "--cwd", "/tmp/lh-env-probe",
                    "--label", "lh-env-probe",
                    "--env", "LEAN_HERDR_PROBE=1", "--no-focus")
    print("CREATE REPLY:", json.dumps(created, indent=2))
    result = created.get("result") or {}
    nested = result.get("workspace") if isinstance(result.get("workspace"), dict) else {}
    ws = nested.get("workspace_id") or result.get("workspace_id")
    print("WORKSPACE ID:", ws)

    panes = (herdr("pane", "list", "--workspace", ws).get("result") or {}).get("panes") or []
    print("PANES:", [p.get("pane_id") for p in panes])
    for pane in panes:
        info = herdr("pane", "process-info", "--pane", pane["pane_id"])
        pid = ((info.get("result") or {}).get("process_info") or {}).get("shell_pid")
        if not pid:
            continue
        env = open(f"/proc/{pid}/environ", "rb").read().decode(errors="replace").split(chr(0))
        print(pane["pane_id"], "->",
              [e for e in env if e.startswith(("LEAN_HERDR_PROBE", "LEAN_CTX_"))])

    print(herdr("workspace", "close", ws))

Und wieder als Shell:

    rm -rf /tmp/lh-env-probe

**Expected:** drei Angaben, alle drei werden festgehalten.
(a) `CREATE REPLY` zeigt, **an welchem Schluessel die `workspace_id` steht** —
`create_workspace()` unten baut genau diese Leiter, und der Plan raet sie nicht.
(b) `WORKSPACE ID` ist nicht `None`; waere sie es, traegt die Antwort eine dritte
Form und die Leiter braucht einen dritten Zweig.
(c) Die letzte Zeile je Pane ist entweder `['LEAN_HERDR_PROBE=1', …]` — dann
traegt die Wurzel-Pane die Umgebung — oder `[]`. Beides ist ein gueltiges
Ergebnis; **keins aendert den Code**, weil `up` in jedem Fall splittet.

@call remember_decision("lean-herdr measurement 2026-09-03: `herdr workspace create` puts the id at <Schluessel>; its `--env` on the root pane -> <Ergebnis>. `up` splits from anchor_pane() regardless -- one path, shared with handle_bootstrap.")

### `[workspace]` in `lean_herdr/settings.py`

`_check_root()` laesst am Top-Level nur die Schluessel aus `ROOT_KEYS` zu. Ein
`[workspace]`-Block braechte ohne die Erweiterung **jeden**
`lean-herdr dispatch`-Aufruf mit `config_error:`. Die Erweiterung geht dem Rest
voraus.

@read lean_herdr/settings.py mode=anchored

**Lies die Zeile, bevor du sie ersetzt.** `ROOT_KEYS` traegt seit `8e2272e`
bereits `"llm"`; die Spec kennt diesen dritten Eintrag nicht, weil er nach ihr
entstand. Ein abgeschriebenes Drei-Tupel loescht ihn und macht
`tests/test_settings.py::test_the_llm_section_is_read_and_defaults_to_empty`
sowie `::test_the_llm_section_no_longer_breaks_the_whole_file` rot — und jeden
`[llm]`-Block zu einem `config_error`.

@call patch("lean_herdr/settings.py", "ROOT_KEYS, zwei neue Konstanten und das Ende der Datei")

`ROOT_KEYS` bekommt einen **vierten** Eintrag, und zwei Konstanten kommen dazu:

    #: The only four keys the top level of the file may carry.
    ROOT_KEYS = ("default", "roles", "llm", "workspace")

Der Docstring von `_check_root()` zaehlt die erlaubten Abschnitte auf und wandert
mit — `0a32bab` hat ihn zuletzt fuer `[llm]` nachgezogen, `[workspace]` gehoert
in denselben Satz.

    #: The two runtimes a role prompt is written for. `dispatch --kind` and
    #: `[workspace].kind` read the SAME tuple -- two lists would let a value
    #: pass one gate and fail the other (M3).
    KINDS = ("claude", "opencode")

    #: The herdr agent name of the orchestrator, and the sender the workers
    #: trust. Deliberately NOT a config key: three places must agree on it --
    #: this constant, the line `ORCHESTRATOR = orch` in both role prompts, and
    #: test_roles.py::test_the_role_prompts_trust_the_name_dispatch_actually_stamps.
    #: A key would break that triad without anyone asking for it.
    #:
    #: It lives HERE, in the leaf module, and not in handlers.py where it
    #: started: `handlers` now imports `workspace`, `workspace` imports
    #: `dispatch`, and `dispatch` reaches `ordercmd` -- which read this name at
    #: IMPORT time. Left in handlers.py that chain closes into a cycle that
    #: crashes on the first import, not in a test.
    ORCHESTRATOR_AGENT = "orch"

Ans **Ende der Datei**, hinter `llm_settings()` — nicht hinter `settings_for()`:
das ist seit dem LLM-Plan nicht mehr dieselbe Stelle (`settings_for()` endet bei
`settings.py:183`, danach laufen `LlmSettings` und `llm_settings()` bis `:247`).
Der neue Block spiegelt `llm_settings` und gehoert neben es, nicht davor:

    @dataclass(frozen=True)
    class WorkspaceSettings:
        """`[workspace]` -- what `lean-herdr workspace up` needs to start.

        Deliberately NOT part of RoleSettings. Those describe how a pane is
        split, per role, and `ALLOWED` is built from their fields -- widening
        that dataclass would make `label` and `kind` legal under `[roles.*]`
        as well, where nothing reads them and a typo would stay silent.

        `model = ""` means "no --model at all", exactly what the bootstrap
        does today. `None` would need a second spelling for the same state.

        What is NOT here: `direction`, `ratio` and `focus`. The orchestrator
        pane takes `pane_split`'s own defaults -- `start_orchestrator` reads
        only `profile` and `ready_timeout_s` off `[roles.orchestrator]`. That
        is what the keystroke does today and the one path both callers share;
        naming it here keeps it a decision rather than an oversight, in a
        module whose whole purpose is that a wrong file never stays silent.
        """

        label: str = "{repo}"
        kind: str = "opencode"
        model: str = ""


    WORKSPACE_ALLOWED = frozenset(f.name for f in fields(WorkspaceSettings))


    def workspace_settings(data: dict[str, Any] | None = None) -> WorkspaceSettings:
        """`[workspace]` out of the settings file. No section: every default.

        Same strictness as settings_for(): an unknown key, a wrong type, a
        kind no role prompt is written for, or a label carrying a placeholder
        nothing fills is a SettingsError -- never a silent fallback.
        """
        table = _check_root({} if data is None else data)
        block = table.get("workspace")
        if block is None:
            return WorkspaceSettings()
        if not isinstance(block, dict):
            raise SettingsError(
                f"workspace: section is not a table, but {type(block).__name__}"
            )
        unknown = sorted(set(block) - WORKSPACE_ALLOWED)
        if unknown:
            raise SettingsError(
                f"workspace: unknown keys {unknown}; "
                f"allowed: {sorted(WORKSPACE_ALLOWED)}"
            )
        for key, value in block.items():
            if not isinstance(value, str):
                raise SettingsError(
                    f"workspace.{key}: {value!r} is {type(value).__name__}, not str"
                )
        values = WorkspaceSettings(**block)
        if values.kind not in KINDS:
            raise SettingsError(
                f"workspace.kind={values.kind!r}, allowed: {list(KINDS)}"
            )
        # `{repo}` is OPTIONAL here, unlike name_template's {role}/{branch}:
        # the label is a caption, not a reuse key, so a literal `label =
        # "work"` is valid. An UNKNOWN placeholder is not -- it would surface
        # as a KeyError deep inside `up`, far from the line that caused it.
        try:
            values.label.format(repo="r")
        except (KeyError, IndexError, ValueError) as exc:
            raise SettingsError(
                f"workspace.label={values.label!r} is not formattable: {exc}"
            ) from exc
        return values

@call patch("lean_herdr/dispatch.py", "choices in build_parser")

    p.add_argument("--kind", default=None, choices=KINDS)

mit `KINDS` in der bestehenden `from lean_herdr.settings import (...)`-Liste.

@call patch("lean_herdr/ordercmd.py", "die ORCHESTRATOR_AGENT-Definition")

`ordercmd.py:36` liest den Namen nicht mehr aus `handlers`, sondern aus
`settings` — der Import von `handlers` (`ordercmd.py:22`) faellt dort ganz weg:

    from lean_herdr.settings import ORCHESTRATOR_AGENT

Und der Modul-Docstring bei `ordercmd.py:11` wandert mit: er erklaert heute, dass
`ORCHESTRATOR_AGENT` hier oeffentlich ist, um einen Import-Zyklus zu umgehen. Den
Zyklus gibt es nach diesem Task nicht mehr — der Name kommt aus dem Blattmodul.
Der Absatz nennt stattdessen den verbliebenen Grund: `dispatch.py` importiert ihn
weiterhin von hier.

`dispatch.py:41` bleibt **unveraendert**: es importiert den Namen weiterhin aus
`ordercmd`, das ihn re-exportiert. Damit bleiben auch
`test_roles.py::test_the_role_prompts_trust_the_name_dispatch_actually_stamps`
(`from lean_herdr.dispatch import ORCHESTRATOR_AGENT`) und der `--from`-Hilfetext
in `build_parser()` unberuehrt. Wer hier zusaetzlich aufraeumt, aendert eine
Zeile, die kein Test verlangt.

### Die Konfigurationsvorlage

@call patch("lean_herdr/templates/config.toml", "ein auskommentierter [workspace]-Block")

Ans Ende der Datei, im Stil der uebrigen Zeilen — auskommentiert, damit die
Vorlage weiter nichts aendert:

    # [workspace] describes the pane `lean-herdr workspace up` opens for the
    # orchestrator. Everything here has a built-in default too.

    # [workspace]
    # label = "{repo}"     # herdr workspace label; {repo} = directory name, optional
    # kind  = "opencode"   # claude | opencode -- the orchestrator's runtime
    # model = ""           # empty: no --model at all

    cp lean_herdr/templates/config.toml .lean-ctx/lean-herdr/config.toml

### `lean_herdr/workspace.py`

Neue Datei (verbatim):

    """`lean-herdr workspace up` -- the orchestrator pane, from the config.

    Two callers, one core. `up` is the command line; `handlers.handle_bootstrap`
    is the keystroke inside a running Herdr. Before this module the two could
    drift, and did: the keystroke read its name, runtime and environment from
    a literal in handlers.py and never opened the config at all.

    They differ in exactly ONE thing, and it sits in the signature rather than
    in the core: `up` may look for a workspace and create one, the keystroke
    may NOT. It has to land in the workspace the key was pressed in -- put the
    find-or-create rule inside the core and the keystroke starts the
    orchestrator somewhere the operator is not looking.
    """

    from __future__ import annotations

    import argparse
    import json
    import sys
    from collections.abc import Callable
    from pathlib import Path
    from typing import Any, NoReturn

    from lean_herdr.bus import BusError, canonical_root
    from lean_herdr.dispatch import UsageError, wait_for_agent_id
    from lean_herdr.herdr import Herdr
    from lean_herdr.settings import (
        ORCHESTRATOR_AGENT,
        SETTINGS_PATH,
        SettingsError,
        WorkspaceSettings,
        read_settings,
        settings_for,
        workspace_settings,
    )
    from lean_herdr.worktree import anchor_pane


    class _Parser(argparse.ArgumentParser):
        """argparse ends a usage error with exit 2 and one line on stderr.

        Same reason as dispatch._Parser: the caller reads `ok` on stdout and
        would see no output at all. Not imported from there -- that name is
        private to its module, and four lines are cheaper than making it
        public for one reuse.
        """

        def error(self, message: str) -> NoReturn:
            raise UsageError(message)


    def find_workspace(
        herdr: Herdr, root: Path, listing: dict[str, Any]
    ) -> str | None:
        """The workspace for `root` -- by worktree first, by pane cwd second.

        `worktree` is optional AND nullable in WorkspaceInfo
        (herdr-api.schema.json:1113-1133): a workspace that `workspace create
        --cwd` made itself can carry `worktree: null`. Searching
        `checkout_path` alone would never find that one again and would create
        a second workspace on the next call -- as soon as the orchestrator
        pane is closed and the duplicate check no longer bites.

        The pane fallback is deliberately SECOND, not equal. Measured against
        0.8.2, a workspace carries panes with foreign `cwd` too: `w1` of this
        repo held a pane sitting in another repository entirely. The mapping
        is fuzzy, so it only runs when the exact rule found nothing.
        """
        for entry in (listing.get("result") or {}).get("workspaces") or ():
            if not isinstance(entry, dict):
                continue
            worktree = entry.get("worktree")
            if isinstance(worktree, dict) and worktree.get("checkout_path") == str(root):
                return str(entry.get("workspace_id") or "") or None
        for pane in herdr.pane_list():
            if pane.get("cwd") == str(root) and pane.get("workspace_id"):
                return str(pane["workspace_id"])
        return None


    def create_workspace(
        herdr: Herdr, root: Path, *, settings: WorkspaceSettings, env: dict[str, str]
    ) -> str | None:
        """`herdr workspace create` for this root. Returns the id, or None.

        Measured against 0.8.2, `workspace create` takes --cwd, --label, --env
        and --focus/--no-focus, and nothing else. The id ladder mirrors
        worktree._open_workspace(): a nested `result.workspace.workspace_id`
        first, the flat key as a fallback, so a shape shift does not read as
        success.
        """
        args = [
            "workspace", "create",
            "--cwd", str(root),
            "--label", settings.label.format(repo=root.name),
            "--focus",
        ]
        for key, value in env.items():
            args += ["--env", f"{key}={value}"]
        result = herdr.run(*args).get("result") or {}
        nested = result.get("workspace") if isinstance(result.get("workspace"), dict) else {}
        workspace = nested.get("workspace_id") or result.get("workspace_id")
        return str(workspace) if workspace else None


    def start_orchestrator(
        *,
        herdr: Herdr,
        root: Path,
        settings: WorkspaceSettings,
        profile: str,
        workspace_id: str | None,
        ready_timeout_s: float,
        waiter: Callable[..., str | None] = wait_for_agent_id,
    ) -> dict[str, Any]:
        """Start the orchestrator. Never raises; the result carries `ok`.

        `workspace_id=None` means "find the workspace for `root`, or create
        one" -- the `up` path. A given id means "use exactly this one and
        create nothing" -- the keystroke path.
        """
        if not herdr.is_available():
            return {"ok": False, "error": "no_herdr_server"}
        # A RAW `workspace list`, not workspace_list(): that method
        # (herdr.py:189-191) flattens "server dead" and "zero workspaces" onto
        # the same `[]`, and only the raw reply tells them apart -- `{}` when
        # nothing answered. Every `herdr <sub>` goes through that socket, so
        # this is a real precondition, not an assumption; without it the call
        # would hang on a dead socket instead of saying so.
        listing = herdr.run("workspace", "list")
        if not listing:
            return {"ok": False, "error": "no_herdr_server"}

        # `agent list` is server-wide, not per workspace -- the same duplicate
        # check the keystroke makes today. This is what makes `up` idempotent.
        running = next(
            (a for a in herdr.agent_list() if a.get("name") == ORCHESTRATOR_AGENT),
            None,
        )
        if running:
            return {
                "ok": True,
                "already_running": True,
                "agent": ORCHESTRATOR_AGENT,
                "pane": str(running.get("pane_id") or "") or None,
            }

        env = {"LEAN_CTX_TOOL_PROFILE": profile, "LEAN_CTX_ROLE": "orchestrator"}
        target = workspace_id or find_workspace(herdr, root, listing) or create_workspace(
            herdr, root, settings=settings, env=env
        )
        if not target:
            return {"ok": False, "error": "no_workspace"}

        # Always split, never take the workspace's root pane. One path, shared
        # with the keystroke, and it is the one that is measured.
        anchor = anchor_pane(herdr, target)
        if anchor is None:
            # A workspace without a pane -- possible after a server restart.
            # Same error name dispatch() uses for the same situation.
            return {"ok": False, "error": "no_anchor_pane", "workspace": target}
        pane = herdr.pane_split(root, pane=anchor, env=env)
        if not pane:
            return {"ok": False, "error": "pane_split_failed", "workspace": target}

        # NOT agent_args(): that helper always sets --model and derives the
        # agent name from a role FILE stem. Here the agent is named directly
        # and --model is omitted entirely when the config leaves it empty --
        # exactly what handle_bootstrap does today.
        agent_args = ["--agent", "orchestrator"]
        if settings.model:
            agent_args = ["--model", settings.model, *agent_args]
        herdr.agent_start(
            ORCHESTRATOR_AGENT,
            kind=settings.kind,
            pane=pane,
            agent_args=agent_args,
        )
        agent_id = waiter(herdr, ORCHESTRATOR_AGENT, timeout_s=ready_timeout_s)
        if not agent_id:
            return {
                "ok": False,
                "error": "no_agent_id",
                "workspace": target,
                "pane": pane,
            }
        return {
            "ok": True,
            "workspace": target,
            "pane": pane,
            "agent": ORCHESTRATOR_AGENT,
            "agent_id": agent_id,
        }


    def workspace_up(
        *, root: Path | None = None, herdr: Herdr | None = None
    ) -> dict[str, Any]:
        """Root, config, then the shared core. Never raises.

        A missing config is a hard stop, not a fallback to defaults: the
        config is the whole point of this call. The keystroke, which is a
        gesture rather than a call, takes the defaults instead.
        """
        base = root if root is not None else canonical_root()
        path = base / SETTINGS_PATH
        if not path.is_file():
            return {
                "ok": False,
                "error": "not_initialised: run `lean-herdr workspace init`",
            }
        data = read_settings(path)
        role = settings_for("orchestrator", data)
        return start_orchestrator(
            herdr=herdr if herdr is not None else Herdr(),
            root=base,
            settings=workspace_settings(data),
            profile=role.profile,
            workspace_id=None,
            ready_timeout_s=role.ready_timeout_s,
        )


    def build_parser() -> argparse.ArgumentParser:
        p = _Parser(
            prog="lean-herdr workspace",
            description="Start the orchestrator from the project config.",
        )
        p.add_argument("command", choices=("up",))
        return p


    def main(argv: list[str] | None = None) -> int:
        """Output: one JSON line on stdout. Exit ALWAYS 0.

        Same contract and the same except ladder as report.main, for the same
        reason: the caller reads `ok`, and a usage error must not abort its
        shell call.
        """
        result: dict[str, Any]
        try:
            args = build_parser().parse_args(argv)
            if args.command == "up":
                result = workspace_up()
        except UsageError as exc:
            result = {"ok": False, "error": f"usage_error: {exc}"}
        except SettingsError as exc:
            result = {"ok": False, "error": f"config_error: {exc}"}
        except BusError as exc:
            result = {"ok": False, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001 -- never abort the caller
            result = {"ok": False, "error": f"workspace_crashed: {exc}"}
        sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
        return 0

@call patch("lean_herdr/cli.py", "VERBS und USAGE")

    VERBS = {
        "dispatch": "lean_herdr.dispatch",
        "report": "lean_herdr.report",
        "workspace": "lean_herdr.workspace",
    }

    USAGE = "usage: lean-herdr {dispatch|report|workspace} ...\n"

### Der Tastendruck auf denselben Kern

@read lean_herdr/handlers.py mode=anchored

@call patch("lean_herdr/handlers.py", "die ORCHESTRATOR-Konstante und handle_bootstrap")

Die Konstante `ORCHESTRATOR` faellt **ganz** weg: `kind` und `env` gehoeren jetzt
`[workspace]` und `[roles.orchestrator]`, der Name wohnt in `settings`. An ihre
Stelle tritt eine Frist, die nur dem Tastendruck gehoert:

    #: The keystroke is answered by the PANE, not by the agent id: a plugin
    #: handler has nobody to show a result to, and Herdr's handler process is
    #: the wrong place to sit out `[roles.orchestrator].ready_timeout_s` (45 s
    #: by default). `lean-herdr workspace up` keeps the full wait -- its caller
    #: reads the id off stdout and has a use for it.
    KEYSTROKE_READY_TIMEOUT_S = 2.0

Und `handle_bootstrap` wird zu:

    def handle_bootstrap(cfg: Config) -> None:
        """A deliberate gesture: open an orchestrator pane in THIS workspace.

        Runs the SAME core as `lean-herdr workspace up`. Before this the
        keystroke read a literal in this module and never opened the config,
        so the two start paths could drift -- and did.

        The one difference stays in the argument: the workspace id comes from
        the event, so the core creates nothing and the pane lands here rather
        than in the caller's workspace.

        Unlike `up`, a missing config is NOT a stop here. `up` is a call whose
        whole purpose is the config; this is a keystroke that must not fail
        into nothing, so read_settings({}) and the built-in defaults carry it.
        """
        herdr = Herdr(cfg.herdr_bin, timeout=cfg.timeout)
        event = cfg.event or {}
        workspace = str(
            event.get("workspace_id")
            or (event.get("workspace") or {}).get("id")
            or cfg.workspace_id
            or ""
        )
        if not workspace:
            herdr.run("notification", "show", "--message", "lean-herdr: no workspace")
            return
        cwd = cwd_from_event(event, herdr, cfg)
        if cwd is None:
            herdr.run(
                "notification", "show", "--message", "lean-herdr: workspace without a cwd"
            )
            return
        try:
            root = canonical_root(cwd)
            data = read_settings(root / SETTINGS_PATH)
            role = settings_for("orchestrator", data)
            result = start_orchestrator(
                herdr=herdr,
                root=root,
                settings=workspace_settings(data),
                profile=role.profile,
                workspace_id=workspace,
                ready_timeout_s=min(role.ready_timeout_s, KEYSTROKE_READY_TIMEOUT_S),
            )
        except (BusError, SettingsError) as exc:
            herdr.run("notification", "show", "--message", f"lean-herdr: {exc}")
            return
        if result.get("already_running"):
            herdr.run(
                "notification",
                "show",
                "--message",
                "lean-herdr: the orchestrator is already running",
            )
        elif not result.get("ok"):
            herdr.run(
                "notification", "show", "--message", f"lean-herdr: {result.get('error')}"
            )

Die Import-Zeilen von `handlers.py` wachsen entsprechend:

    from lean_herdr.settings import (
        SETTINGS_PATH,
        SettingsError,
        read_settings,
        settings_for,
        workspace_settings,
    )
    from lean_herdr.workspace import start_orchestrator

### Die Tests

Neue Datei `tests/test_workspace.py`. Das Hausmuster ist
`Herdr(runner=FakeProc(...))` plus `which_stub` — es gibt **kein** `FakeHerdr`
(`tests/doubles.py` traegt `Completed`, `FakeProc`, `which_stub`; siehe
`tests/test_dispatch.py:48` und `:66`).

@read tests/doubles.py mode=signatures
@read tests/test_dispatch.py mode=lines:40-80

Die Antworttabelle, die alle Faelle tragen (verbatim):

    """`workspace up` and the core the keystroke shares with it."""

    import json
    from pathlib import Path

    import pytest

    from lean_herdr import workspace
    from lean_herdr.herdr import Herdr
    from lean_herdr.settings import WorkspaceSettings
    from tests.doubles import FakeProc, which_stub

    ROOT = Path("/repo")

    #: A workspace found by rule 1 -- worktree.checkout_path == root.
    BY_WORKTREE = {
        "result": {
            "workspaces": [
                {
                    "workspace_id": "w3",
                    "worktree": {"checkout_path": str(ROOT)},
                }
            ]
        }
    }

    #: A workspace `workspace create --cwd` made itself: worktree is null, so
    #: rule 1 cannot see it and only the pane fallback can.
    WITHOUT_WORKTREE = {
        "result": {"workspaces": [{"workspace_id": "w3", "worktree": None}]}
    }

    PANES = {"result": {"panes": [{"pane_id": "w3:p1", "cwd": str(ROOT), "workspace_id": "w3"}]}}
    NO_AGENTS = {"result": {"agents": []}}
    SPLIT = {"result": {"pane": {"pane_id": "w3:p9"}}}


    def herdr_with(monkeypatch, replies, *, available=True):
        monkeypatch.setattr("shutil.which", which_stub(available))
        proc = FakeProc(replies=replies)
        return Herdr(runner=proc), proc


    def core(herdr, **rest):
        defaults = {
            "root": ROOT,
            "settings": WorkspaceSettings(),
            "profile": "minimal",
            "workspace_id": None,
            "ready_timeout_s": 1.0,
            "waiter": lambda *a, **k: "mcp-42",
        }
        return workspace.start_orchestrator(herdr=herdr, **{**defaults, **rest})

Die Faelle, einer je Test:

    def test_without_the_binary_there_is_no_server(monkeypatch):
        herdr, _ = herdr_with(monkeypatch, {}, available=False)
        assert core(herdr)["error"] == "no_herdr_server"


    def test_an_empty_workspace_list_reply_is_a_dead_socket(monkeypatch):
        """workspace_list() would flatten this onto []; the raw reply does not."""
        herdr, _ = herdr_with(monkeypatch, {("workspace", "list"): {}})
        assert core(herdr)["error"] == "no_herdr_server"


    def test_a_running_orchestrator_starts_no_second_one(monkeypatch):
        replies = {
            ("workspace", "list"): BY_WORKTREE,
            ("agent", "list"): {"result": {"agents": [{"name": "orch", "pane_id": "w3:p2"}]}},
        }
        herdr, proc = herdr_with(monkeypatch, replies)
        answer = core(herdr)
        assert answer["ok"] is True and answer["already_running"] is True
        assert answer["pane"] == "w3:p2"
        assert not proc.called_with("pane", "split"), proc.flat()


    def test_rule_one_finds_the_workspace_by_checkout_path(monkeypatch):
        replies = {
            ("workspace", "list"): BY_WORKTREE,
            ("agent", "list"): NO_AGENTS,
            ("pane", "list"): PANES,
            ("pane", "split"): SPLIT,
        }
        herdr, proc = herdr_with(monkeypatch, replies)
        assert core(herdr)["workspace"] == "w3"
        assert not proc.called_with("workspace", "create"), proc.flat()


    def test_rule_two_finds_it_by_pane_cwd_when_the_worktree_is_null(monkeypatch):
        """The case a `worktree: null` workspace would otherwise duplicate."""
        replies = {
            ("workspace", "list"): WITHOUT_WORKTREE,
            ("agent", "list"): NO_AGENTS,
            ("pane", "list"): PANES,
            ("pane", "split"): SPLIT,
        }
        herdr, proc = herdr_with(monkeypatch, replies)
        assert core(herdr)["workspace"] == "w3"
        assert not proc.called_with("workspace", "create"), proc.flat()


    def test_neither_rule_hits_so_a_workspace_is_created(monkeypatch):
        replies = {
            ("workspace", "list"): {"result": {"workspaces": []}},
            ("workspace", "create"): {"result": {"workspace": {"workspace_id": "w9"}}},
            ("agent", "list"): NO_AGENTS,
            ("pane", "list"): {"result": {"panes": [{"pane_id": "w9:p1", "workspace_id": "w9"}]}},
            ("pane", "split"): SPLIT,
        }
        herdr, proc = herdr_with(monkeypatch, replies)
        assert core(herdr)["workspace"] == "w9"
        assert proc.called_with("workspace", "create", "--cwd", "--label", "repo")
        assert proc.called_with("--env", "LEAN_CTX_TOOL_PROFILE=minimal")


    def test_a_given_workspace_id_never_creates_one(monkeypatch):
        """The keystroke path: it must land where the key was pressed."""
        replies = {
            ("workspace", "list"): {"result": {"workspaces": []}},
            ("agent", "list"): NO_AGENTS,
            ("pane", "list"): {"result": {"panes": [{"pane_id": "w7:p1", "workspace_id": "w7"}]}},
            ("pane", "split"): SPLIT,
        }
        herdr, proc = herdr_with(monkeypatch, replies)
        assert core(herdr, workspace_id="w7")["workspace"] == "w7"
        assert not proc.called_with("workspace", "create"), proc.flat()


    def test_a_workspace_without_a_pane_is_no_anchor_pane(monkeypatch):
        replies = {
            ("workspace", "list"): BY_WORKTREE,
            ("agent", "list"): NO_AGENTS,
            ("pane", "list"): {"result": {"panes": []}},
        }
        herdr, _ = herdr_with(monkeypatch, replies)
        assert core(herdr)["error"] == "no_anchor_pane"


    def test_a_failed_split_says_so(monkeypatch):
        replies = {
            ("workspace", "list"): BY_WORKTREE,
            ("agent", "list"): NO_AGENTS,
            ("pane", "list"): PANES,
            ("pane", "split"): {},
        }
        herdr, _ = herdr_with(monkeypatch, replies)
        assert core(herdr)["error"] == "pane_split_failed"


    def test_a_timeout_without_an_agent_id_is_not_ok(monkeypatch):
        replies = {
            ("workspace", "list"): BY_WORKTREE,
            ("agent", "list"): NO_AGENTS,
            ("pane", "list"): PANES,
            ("pane", "split"): SPLIT,
        }
        herdr, _ = herdr_with(monkeypatch, replies)
        answer = core(herdr, waiter=lambda *a, **k: None)
        assert answer["ok"] is False and answer["error"] == "no_agent_id"
        assert answer["pane"] == "w3:p9", "the pane exists and the operator needs it"


    def test_the_success_path_carries_all_four_names(monkeypatch):
        replies = {
            ("workspace", "list"): BY_WORKTREE,
            ("agent", "list"): NO_AGENTS,
            ("pane", "list"): PANES,
            ("pane", "split"): SPLIT,
        }
        herdr, proc = herdr_with(monkeypatch, replies)
        assert core(herdr) == {
            "ok": True,
            "workspace": "w3",
            "pane": "w3:p9",
            "agent": "orch",
            "agent_id": "mcp-42",
        }
        assert proc.called_with("agent", "start", "orch", "--kind", "opencode")
        assert proc.called_with("--", "--agent", "orchestrator")


    def test_an_empty_model_means_no_model_flag_at_all(monkeypatch):
        replies = {
            ("workspace", "list"): BY_WORKTREE,
            ("agent", "list"): NO_AGENTS,
            ("pane", "list"): PANES,
            ("pane", "split"): SPLIT,
        }
        herdr, proc = herdr_with(monkeypatch, replies)
        core(herdr)
        assert not proc.called_with("agent", "start", "--model"), proc.flat()
        core(herdr, settings=WorkspaceSettings(model="sonnet"))
        assert proc.called_with("--", "--model", "sonnet", "--agent", "orchestrator")


    def test_up_without_a_config_file_refuses(monkeypatch, tmp_path):
        """Not silently defaults: the config is the whole point of the call."""
        herdr, _ = herdr_with(monkeypatch, {})
        answer = workspace.workspace_up(root=tmp_path, herdr=herdr)
        assert answer["ok"] is False
        assert answer["error"].startswith("not_initialised:")


    def test_main_answers_a_bad_command_with_one_json_line(capsys):
        assert workspace.main(["nope"]) == 0
        answer = json.loads(capsys.readouterr().out)
        assert answer["ok"] is False and answer["error"].startswith("usage_error:")

@call tdd(test_a_given_workspace_id_never_creates_one)

Und die drei Nachbardateien:

@call patch("tests/test_settings.py", "die [workspace]-Faelle")

    def test_an_unknown_workspace_key_does_not_stay_silent():
        with pytest.raises(SettingsError, match="unknown keys"):
            workspace_settings({"workspace": {"labl": "x"}})


    def test_a_workspace_key_under_roles_is_still_unknown():
        """[workspace] is its own dataclass, not a widened RoleSettings."""
        with pytest.raises(SettingsError, match="unknown keys"):
            settings_for("builder", {"roles": {"builder": {"label": "x"}}})


    def test_a_kind_no_role_prompt_is_written_for_is_rejected():
        with pytest.raises(SettingsError, match="workspace.kind"):
            workspace_settings({"workspace": {"kind": "codex"}})


    def test_a_literal_label_is_valid_but_an_unknown_placeholder_is_not():
        assert workspace_settings({"workspace": {"label": "work"}}).label == "work"
        with pytest.raises(SettingsError, match="not formattable"):
            workspace_settings({"workspace": {"label": "{branch}"}})


    def test_no_workspace_section_means_every_default():
        assert workspace_settings({}) == WorkspaceSettings()

@call patch("tests/test_handlers.py", "die beiden bootstrap-Tests")

Beide Tests behalten ihre Aussage, aber **nicht** ihren Aufbau: der Weg laeuft
jetzt durch `start_orchestrator`, und der stellt zwei Bedingungen, die die
heutigen Tests nicht erfuellen.

`test_bootstrap_starts_the_orchestrator_in_its_own_workspace` (`:191`) und
`test_bootstrap_does_not_start_a_second_orchestrator` (`:207`) uebergeben heute
`{"workspace": {"cwd": "/repo"}}` und stellen **keine** Antwort auf
`("workspace", "list")` bereit. Nach der Aenderung:

1. Das rohe `workspace list` liefert `{}` → der Kern antwortet
   `no_herdr_server`, bevor er irgendetwas tut. Beide Tests brauchen deshalb
   einen `("workspace", "list")`-Eintrag in der Antworttabelle.
2. **Der Waiter ist die eigentliche Falle, und sie kostet Wartezeit statt einer
   Fehlermeldung.** `start_orchestrator` nimmt `waiter=wait_for_agent_id` als
   Vorgabe, und `handle_bootstrap` reicht keinen eigenen herein. In
   `test_bootstrap_starts_the_orchestrator_in_its_own_workspace` gibt es keine
   `("agent", "list")`-Antwort, `agent_list()` ist also `[]` — der echte Waiter
   pollt daraufhin mit `time.sleep` bis `ready_timeout_s` und liest dabei die
   **echte** Registry des Operators (`dispatch.py:71-72`:
   `AGENT_READY_TIMEOUT_S = RoleSettings.ready_timeout_s` = 45.0,
   `AGENT_READY_INTERVAL_S = 0.5`; `default_registry_path()` zeigt nach
   `~/.local/share/lean-ctx/agents/`). Das sind **45 Sekunden echter Schlaf in
   einem Unit-Test**, kein Fehlschlag — die Suite wird nicht rot, nur unbrauchbar
   langsam.

   Eine `("agent", "list")`-Antwort ist **kein** Ausweg: derselbe Aufruf traegt
   die Duplikatspruefung, der Kern antwortete `already_running` und spraenge den
   Split — der Test prueft dann nichts mehr. Der Ausweg ist eine Naht fuer den
   Waiter, und `handle_bootstrap` braucht sie ohnehin (siehe den Absatz unten):
   der Test setzt `monkeypatch.setattr("lean_herdr.workspace.wait_for_agent_id",
   lambda *a, **k: "mcp-42")`.

**Achtung, die Vorgabe der ersten Planfassung war hier falsch und ist gestrichen:**
`canonical_root` wirft in diesen Tests **nichts**. Die `world`-Fixture ersetzt sie
(`tests/test_handlers.py:26`:
`monkeypatch.setattr("lean_herdr.handlers.canonical_root", lambda cwd: Path("/repo"))`),
und der Stub liefert `/repo` fuer jedes `cwd`. Ein `git init -q` in `tmp_path`
aenderte daran nichts und gehoert nicht in diese Tests.

Zusaetzlich prueft der erste, dass **kein** `workspace create` abgesetzt wurde —
genau die Eigenschaft, die den Tastendruck vom `up` unterscheidet:

    assert not proc.called_with("workspace", "create"), proc.flat()

**Zwei Verhaltensaenderungen, die die Spec nicht erwaehnt und die hier
dokumentiert werden, damit sie niemand fuer einen Fehler haelt.**

Die erste: die neue Pane laeuft unter `canonical_root(cwd)` statt unter dem `cwd`
aus dem Ereignis. Das ist richtig — `SETTINGS_PATH` ist relativ zur Wurzel, und
eine Pane in einem Unterverzeichnis laese die Config nicht. Die Folge ist, dass
ein Tastendruck **ausserhalb** eines Git-Checkouts jetzt mit einer Notification
endet statt eine Pane zu oeffnen. Das ist kein Verlust: ohne Repo gibt es weder
Config noch Auftragslog, und der Orchestrator haette nichts zu tun.

Die zweite: **der Tastendruck wartet jetzt.** `handle_bootstrap` kehrt heute
unmittelbar nach `agent_start` zurueck (`handlers.py:202-207`); ueber den
geteilten Kern blockiert er, bis der Waiter eine `agent_id` sieht — im Prozess
eines Herdr-Plugin-Handlers, wo niemand eine Ausgabe erwartet. Die Antwort darauf
ist **nicht**, dem Kern das Warten abzugewoehnen (`up` braucht die `agent_id`,
und zwei Zweige waeren genau die Doppelung, gegen die dieser Task existiert),
sondern dem Tastendruck eine kurze eigene Frist zu geben. Das erledigt
`KEYSTROKE_READY_TIMEOUT_S` im Aufruf oben; ohne den Deckel saesse ein
Plugin-Handler die vollen 45 Sekunden aus `[roles.orchestrator].ready_timeout_s`
ab.

@call patch("tests/test_cli.py", "nichts weiter -- der parametrisierte Test nimmt das dritte Verb automatisch mit")

### README

@call patch("README.md", "der Bootstrap-Abschnitt")

    ## Bootstrap

    The orchestrator does not start itself. Once per Herdr server -- the
    duplicate check reads `herdr agent list`, which is server-wide, not per
    workspace:

        lean-herdr workspace up

    It reads `[workspace]` and `[roles.orchestrator]` from
    `.lean-ctx/lean-herdr/config.toml`, finds or creates the workspace for
    this repository, splits a pane and starts the agent in it. Called twice it
    answers `already_running` and changes nothing. The keystroke
    "Start the orchestrator in this workspace" in a running Herdr runs the
    same code -- it only skips the find-or-create step, so the pane lands in
    the workspace the key was pressed in.

Der Abschnitt „Configuration" nennt den neuen Pfad und den neuen Block. Der
Absatz ueber den Umbenennungspfad des Namens `orch` nennt statt
`ORCHESTRATOR["name"] in lean_herdr/handlers.py` jetzt
`ORCHESTRATOR_AGENT in lean_herdr/settings.py`.

### Verify & Close

@call verify(lean_herdr/workspace.py lean_herdr/settings.py lean_herdr/handlers.py)
@call review_change()
@call gate(.)
@call commit(".", "feat(workspace): start the orchestrator from the config, on one core with the keystroke")
@call remember_decision("lean-herdr: start_orchestrator(workspace_id=None) finds-or-creates (the `up` path), a given id uses exactly that one and creates nothing (the keystroke path). ORCHESTRATOR_AGENT moved from handlers.py to settings.py to break the handlers -> workspace -> dispatch -> ordercmd -> handlers import cycle.")
@phase-end

@phase "task-5"
## Task 5: `lean-herdr workspace init`

**Files:** Create `lean_herdr/initcmd.py`, `tests/test_initcmd.py`. Modify
`lean_herdr/workspace.py`, `tests/test_templates.py`, `README.md`.
**Interfaces:** Produces `lean_herdr.initcmd.LAYOUT: dict[str, str]`,
`lean_herdr.initcmd.TEMPLATES: Path`, `CHECK_TIMEOUT_S`,
`workspace_init(*, root=None, force=False, runner=subprocess.run) ->
dict[str, Any]`; und `workspace.build_parser()` kennt `init` und `--force`.
**Consumes:** `lean_herdr.bus.canonical_root`, sonst die Standardbibliothek.

@call recall_context("lean-herdr templates byte-identical copy init")

### Warum eine eigene Datei

`up` und `init` teilen nichts ausser dem Verb. Derselbe Schnitt, den
`ordercmd.py` schon einmal aus `dispatch.py` bekommen hat — und er kommt hier
sofort statt spaeter, weil `workspace.py` mit `init` darin ueber die
400-Zeilen-Marke liefe, ab der die Spec ihn ohnehin vorsieht.

### `lean_herdr/initcmd.py`

Neue Datei (verbatim):

    """`lean-herdr workspace init` -- write the templates, report the rest.

    Two rules run through everything here.

    The first: an existing file is NEVER overwritten without --force. A
    stranger's `opencode.jsonc` or `.claude/settings.json` flattened in
    silence would be the most expensive mistake this tool could make. Skipped
    files are named in the result, so nobody has to guess what happened.

    The second: preconditions are REPORTED, never repaired. Every foreign
    command here only READS -- `lean-ctx allow --list`, `wt config approvals
    list --format json`, `herdr plugin list`. `init` runs no `lean-ctx allow`
    and no `wt config approvals add`: granting a machine-wide permission is a
    gesture that belongs to the human at the keyboard.
    """

    from __future__ import annotations

    import json
    import re
    import shutil
    import subprocess
    from pathlib import Path
    from typing import Any

    from lean_herdr.bus import BusError, canonical_root

    TEMPLATES = Path(__file__).resolve().parent / "templates"

    #: A read-only check must not hold up the whole call.
    CHECK_TIMEOUT_S = 10.0

    #: template inside the package -> where it goes in the target project.
    #: THE one truth: tests/test_templates.py imports this table to hold each
    #: template byte-identical against this repo's own copy.
    #:
    #: Only the first four are movable. `opencode.jsonc`,
    #: `.claude/settings.json`, `.config/wt.toml` and the opencode plugin sit
    #: where their owners look for them. `.config/wt.toml` could in theory move
    #: via WORKTRUNK_PROJECT_CONFIG_PATH -- but that variable would have to be
    #: set on EVERY `wt` call, hand-typed ones included, and a single miss makes
    #: `wt` skip the project hooks silently and report success. The pre-merge
    #: test gate would then not run at all.
    LAYOUT = {
        "config.toml": ".lean-ctx/lean-herdr/config.toml",
        "roles/orchestrator.md": ".lean-ctx/lean-herdr/roles/orchestrator.md",
        "roles/builder.md": ".lean-ctx/lean-herdr/roles/builder.md",
        "roles/reviewer.md": ".lean-ctx/lean-herdr/roles/reviewer.md",
        "opencode.jsonc": "opencode.jsonc",
        "settings.json": ".claude/settings.json",
        "wt.toml": ".config/wt.toml",
        "lean-ctx-policy.js": ".opencode/plugins/lean-ctx-policy.js",
    }


    def _read(runner: Any, *cmd: str, cwd: Path | None = None) -> str | None:
        """One read-only foreign command. None when it cannot run at all.

        stdout AND stderr, because `wt` writes its warnings to stderr and a
        check that ignored them would report a green state over a complaint.
        """
        if shutil.which(cmd[0]) is None:
            return None
        try:
            proc = runner(
                list(cmd),
                capture_output=True,
                text=True,
                timeout=CHECK_TIMEOUT_S,
                cwd=None if cwd is None else str(cwd),
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return (proc.stdout or "") + (proc.stderr or "")


    def _warnings(root: Path, *, runner: Any = subprocess.run) -> list[str]:
        """The README checklist as lines. Nothing here changes anything."""
        found: list[str] = []
        for binary, why in (
            ("herdr", "panes, agents and workspaces"),
            ("wt", "one worktree per branch, merge and cleanup"),
            ("lean-ctx", "agent bus, project memory, tool profiles"),
        ):
            if shutil.which(binary) is None:
                found.append(f"{binary} is not on PATH -- needed for {why}")

        allowlist = _read(runner, "lean-ctx", "allow", "--list")
        # Word boundaries, not a plain substring: the listing prints the config
        # path too, and a project directory called lean-herdr would otherwise
        # read as a granted permission.
        if allowlist is not None and not re.search(r"\blean-herdr\b", allowlist):
            found.append(
                "lean-ctx does not allow `lean-herdr` -- "
                "an agent under shell gating cannot run it: lean-ctx allow lean-herdr"
            )

        approvals = _read(runner, "wt", "config", "approvals", "list", "--format", "json", cwd=root)
        if approvals is not None:
            # The reply may carry a warning line ahead of the JSON, so parse
            # from the first brace rather than the first byte.
            start = approvals.find("{")
            try:
                state = json.loads(approvals[start:])["state"] if start >= 0 else None
            except (json.JSONDecodeError, KeyError, TypeError):
                state = None
            if state != "approved":
                found.append(
                    f"worktrunk project hooks are not approved (state: {state!r}) -- "
                    "wt skips them SILENTLY and reports success, so the pre-merge "
                    "test gate would not run: wt config approvals add"
                )

        plugins = _read(runner, "herdr", "plugin", "list")
        if plugins is not None and "warning:" in plugins:
            found.append(
                "herdr plugin list carries a `warning:` line -- "
                "Herdr does not reject an unknown plugin event, it only warns"
            )
        return found


    def workspace_init(
        *,
        root: Path | None = None,
        force: bool = False,
        runner: Any = subprocess.run,
    ) -> dict[str, Any]:
        """Write the templates into this project. Never raises.

        No git repository: a hard stop with a named next step. `init` does not
        run `git init` itself -- that is a gesture belonging to the human.
        """
        try:
            base = root if root is not None else canonical_root()
        except BusError:
            return {"ok": False, "error": "not_a_git_repo: run `git init` first"}

        written: list[str] = []
        skipped: list[str] = []
        for name, relative in LAYOUT.items():
            target = base / relative
            if target.exists() and not force:
                skipped.append(relative)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((TEMPLATES / name).read_bytes())
            written.append(relative)
        return {
            "ok": True,
            "root": str(base),
            "written": sorted(written),
            "skipped": sorted(skipped),
            "warnings": _warnings(base, runner=runner),
        }

### Der Parser lernt das zweite Kommando

@call patch("lean_herdr/workspace.py", "build_parser und main")

    def build_parser() -> argparse.ArgumentParser:
        p = _Parser(
            prog="lean-herdr workspace",
            description="Set the project up, or start the orchestrator from its config.",
        )
        p.add_argument("command", choices=("up", "init"))
        p.add_argument(
            "--force",
            action="store_true",
            help="init: overwrite files that are already there",
        )
        return p

Und in `main()`, an der Stelle von `if args.command == "up":`:

            if args.command == "up":
                if args.force:
                    result = {
                        "ok": False,
                        "error": "usage_error: up does not take --force",
                    }
                else:
                    result = workspace_up()
            else:
                # Imported on the call, not up top: `up` is what runs on every
                # start, and it needs none of this.
                from lean_herdr.initcmd import workspace_init

                result = workspace_init(force=args.force)

### Die Tabelle wandert an ihren Platz

@call patch("tests/test_templates.py", "PAIRS durch den Import von LAYOUT ersetzen")

    from lean_herdr.initcmd import LAYOUT

    #: `init` writes these into a target project; this repo carries each of
    #: them at exactly that path. One table, imported from the code that owns
    #: it -- a second copy here would drift the moment a file is added.
    PAIRS = LAYOUT

### Die Tests

Neue Datei `tests/test_initcmd.py` (verbatim):

    """`init` in a stranger's project: writes, skips, warns -- never repairs."""

    import json
    import subprocess

    import pytest

    from lean_herdr.initcmd import LAYOUT, workspace_init
    from tests.doubles import Completed, FakeProc, which_stub


    @pytest.fixture
    def repo(tmp_path):
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, timeout=30)
        return tmp_path


    def quiet(monkeypatch):
        """No foreign binary in reach -- the warnings are tested separately."""
        monkeypatch.setattr("shutil.which", which_stub(False))


    def test_a_fresh_project_gets_every_file(monkeypatch, repo):
        quiet(monkeypatch)
        answer = workspace_init(root=repo)
        assert answer["ok"] is True
        assert answer["written"] == sorted(LAYOUT.values())
        assert answer["skipped"] == []
        for relative in LAYOUT.values():
            assert (repo / relative).is_file(), relative


    def test_a_second_run_writes_nothing(monkeypatch, repo):
        quiet(monkeypatch)
        workspace_init(root=repo)
        answer = workspace_init(root=repo)
        assert answer["written"] == []
        assert answer["skipped"] == sorted(LAYOUT.values())


    def test_a_stranger_file_survives_without_force(monkeypatch, repo):
        """The most expensive mistake this tool could make."""
        quiet(monkeypatch)
        mine = repo / "opencode.jsonc"
        mine.write_text('{"agent": {"mine": {}}}', encoding="utf-8")
        answer = workspace_init(root=repo)
        assert "opencode.jsonc" in answer["skipped"]
        assert mine.read_text(encoding="utf-8") == '{"agent": {"mine": {}}}'


    def test_force_overwrites_it(monkeypatch, repo):
        quiet(monkeypatch)
        mine = repo / "opencode.jsonc"
        mine.write_text("{}", encoding="utf-8")
        answer = workspace_init(root=repo, force=True)
        assert answer["skipped"] == []
        assert "lean-herdr report next" in mine.read_text(encoding="utf-8")


    def test_without_a_git_repo_it_says_so(monkeypatch, tmp_path):
        quiet(monkeypatch)
        # canonical_root() is what fails, so drive it through the real path:
        # no `root=`, from a directory that is not a checkout.
        monkeypatch.chdir(tmp_path)
        answer = workspace_init()
        assert answer["ok"] is False
        assert answer["error"].startswith("not_a_git_repo:")
        assert not (tmp_path / "opencode.jsonc").exists(), "it wrote before checking"


    def test_every_missing_precondition_becomes_one_line(monkeypatch, repo):
        monkeypatch.setattr("shutil.which", which_stub(True))
        replies = {
            ("allow", "--list"): "Mode: restricted -- 73 command(s) permitted",
            ("config", "approvals"): '{"state": "approval_required"}',
            ("plugin", "list"): "- lean.herdr enabled\n  warning: unknown event\n",
        }
        proc = FakeProc(replies=replies, default="")
        warnings = workspace_init(root=repo, runner=proc)["warnings"]
        assert any("lean-ctx allow lean-herdr" in w for w in warnings)
        assert any("not approved" in w for w in warnings)
        assert any("warning:" in w for w in warnings)


    def test_a_healthy_machine_warns_about_nothing(monkeypatch, repo):
        monkeypatch.setattr("shutil.which", which_stub(True))
        replies = {
            ("allow", "--list"): "Extra (additive, via `lean-ctx allow`): lean-herdr",
            ("config", "approvals"): '{"state": "approved"}',
            ("plugin", "list"): "- lean.herdr (lean-herdr context) enabled\n",
        }
        assert workspace_init(root=repo, runner=FakeProc(replies=replies))["warnings"] == []


    def test_init_never_runs_a_command_that_changes_anything(monkeypatch, repo):
        """Reported, not repaired -- the whole point of the checklist."""
        monkeypatch.setattr("shutil.which", which_stub(True))
        proc = FakeProc(replies={}, default="")
        workspace_init(root=repo, runner=proc)
        for forbidden in (("allow", "lean-herdr"), ("approvals", "add"), ("plugin", "link")):
            assert not proc.called_with(*forbidden), proc.flat()

`FakeProc` matcht auf dem Argument-Praefix ab Position 1 (`cmd[1:1+len(prefix)]`),
deshalb sind die Schluessel oben `("allow", "--list")` und nicht
`("lean-ctx", "allow", "--list")` — genau das Muster aus `tests/test_dispatch.py`.
`FakeProc` liefert `Completed(stdout=...)` ohne `stderr`; `_read()` verkraftet
das, weil es beide Felder mit `or ""` liest.

@call tdd(test_a_stranger_file_survives_without_force)

### README

@call patch("README.md", "ein Abschnitt `## Setting up a project` vor dem Bootstrap")

    ## Setting up a project

    In a repository that has never seen lean-herdr:

        lean-herdr workspace init

    It writes eight files -- the config and the three role prompts under
    `.lean-ctx/lean-herdr/`, and `opencode.jsonc`, `.claude/settings.json`,
    `.config/wt.toml` and `.opencode/plugins/lean-ctx-policy.js` where their
    owners look for them. An existing file is skipped and named in the result;
    `--force` overwrites. It needs a git repository and does not create one.

    What it does NOT do is repair your machine. The three lean-ctx approvals,
    the worktrunk hook approval and the Herdr plugin registration are reported
    as `warnings` and stay yours to grant.

    Two of the eight carry this project's own answers and are meant to be
    edited: `.config/wt.toml` pins the pre-merge gate to `uv run pytest -q`,
    and `.claude/settings.json` allows `Bash(uv run pytest:*)`. In a project
    that is not Python, both are wrong on the first merge -- and a pre-merge
    gate that fails is the one that aborts the merge, so you find out early.

### Verify & Close

@call verify(lean_herdr/initcmd.py lean_herdr/workspace.py tests/test_initcmd.py)
@call gate(.)
@call commit(".", "feat(workspace): add `init`, which writes the templates and reports the preconditions")
@call remember_decision("lean-herdr: initcmd.LAYOUT is the one truth for what `init` writes and where; tests/test_templates.py imports it. `init` never overwrites without --force and never repairs -- foreign commands run read-only only.")
@phase-end

@phase "task-6"
## Task 6: Selbstanwendung und Abnahme

**Files:** Modify `README.md`. Kein Produktionscode.
**Interfaces:** keine neuen.
**Consumes:** alles aus Tasks 1-5.

@call recall_context("lean-herdr workspace init up templates entry point")

Dieses Repo benutzt sich selbst. Der letzte Task beweist beide Richtungen: dass
`init` in einem **fremden** Projekt taugt, und dass dieses Projekt in seiner
neuen Form laeuft.

### Richtung 1: ein fremdes, leeres Projekt

    rm -rf /tmp/lh-stranger && mkdir -p /tmp/lh-stranger && git -C /tmp/lh-stranger init -q && cd /tmp/lh-stranger && lean-herdr workspace init

**Expected:** eine JSON-Zeile mit `"ok": true`, acht Eintraege in `written`,
`skipped` leer, `root` gleich `/tmp/lh-stranger`. In `warnings` steht mindestens
die worktrunk-Zeile, weil das frische Projekt keine Hook-Freigabe hat.

    cd /tmp/lh-stranger && find . -path ./.git -prune -o -type f -print | sort

**Expected:** genau die acht Pfade aus `initcmd.LAYOUT`.

    cd /tmp/lh-stranger && lean-herdr workspace init

**Expected:** `written` leer, `skipped` mit allen acht — der zweite Lauf fasst
nichts an.

    cd /tmp/lh-stranger && lean-herdr workspace up ; rm -rf /tmp/lh-stranger

**Expected:** eine JSON-Zeile. Laeuft in dieser Sitzung bereits ein `orch`,
lautet die Antwort `already_running` — der serverweite Duplikat-Check greift,
und das ist das richtige Verhalten, kein Fehlschlag.

### Richtung 2: dieses Repo

    lean-herdr workspace init

**Expected:** `written` **leer**, `skipped` mit allen acht. Das ist der Beweis
im echten Lauf, dass die Vorlagen und die eingecheckten Kopien an denselben
Stellen liegen — `tests/test_templates.py` prueft die Bytes, dieser Aufruf die
Pfade.

    lean-ctx allow lean-herdr && lean-ctx allow --list

**Expected:** `lean-herdr` steht in der `Extra`-Zeile. Ohne diese Freigabe
scheitert jeder Worker unter Shell-Gating am ersten `lean-herdr report next` —
und die Ausnahme, die das frueher trug, ist mit dem Umzug auf den PATH weg.

    lean-herdr workspace init && lean-herdr workspace up

**Expected:** `warnings` nennt `lean-ctx allow` jetzt nicht mehr.

### Die opencode-Rollentexte am neuen Ort

Der `{file:...}`-Pfad in `opencode.jsonc` zeigt seit Task 3 in ein
Punkt-Verzeichnis. Das wird hier einmal am echten Programm geprueft, nicht
angenommen:

    opencode run --agent reviewer 'Answer with exactly the word READY and nothing else.'

**Expected:** `READY`. Kommt stattdessen eine Beschwerde ueber eine fehlende
Prompt-Datei, ist der Pfad in `opencode.jsonc` falsch und nicht der Rollentext.

### Die volle Abnahme

    grep -rn 'bin/herdr-dispatch\|bin/herdr-report' \
      --exclude-dir=docs --exclude-dir=.git --exclude-dir=.pytest_cache \
      --exclude-dir=__pycache__ . ; echo rc=$?

**Expected:** keine Ausgabe, `rc=1`.

    git check-ignore .lean-ctx/lean-herdr/roles/builder.md ; echo rc=$?

**Expected:** `rc=1` — die Rollentexte sind versioniert und reisen im Branch.

Dieses Skript laeuft ueber `ctx_execute(language="python")`, **nicht** als
`python3 - <<'PY'` und nicht als `python3 -c`: unter `shell_strict_mode = true`
lehnt das Shell-Gate jede Pipe in einen nackten Interpreter ab, und zwar
permanent, nicht als voruebergehenden Fehler.

    import ast
    import pathlib

    for path in sorted(pathlib.Path("lean_herdr").glob("*.py")):
        src = path.read_text(encoding="utf-8")
        lines = src.splitlines()
        blank = sum(1 for line in lines if not line.strip())
        comment = sum(1 for line in lines if line.strip().startswith("#"))
        docstring = 0
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                if ast.get_docstring(node, clean=False) is not None:
                    first = node.body[0]
                    docstring += first.end_lineno - first.lineno + 1
        production = len(lines) - blank - comment - docstring
        over = "  <-- OVER" if production > 800 else ""
        print(f"{path.name}: {len(lines)} physical, {production} production{over}")

**Expected:** keine `OVER`-Zeile. Gemessen werden **produktive** Zeilen, nicht
`wc -l` — die Regel in `AGENTS.md` hat immer die erste Zahl gemeint, und in
diesem Baum liegen die beiden weit auseinander. Der Stand vor diesem Plan
(2026-09-03): `dispatch.py` **817 physisch gegen 519 produktiv**, `llm.py` 751
gegen 352. Ein Gate auf der physischen Zahl waere hier schon rot, bevor dieser
Plan eine Zeile angefasst hat. `dispatch.py` waechst hier nur um eine
`choices`-Zeile; `workspace.py` und `initcmd.py` liegen deutlich darunter.

@call gate(.)

### Der einmalige Bruch, vor dem Merge

Laufende Worker in bestehenden Worktrees verlieren `bin/herdr-report`. Vor dem
Merge muessen alle offenen Auftraege geschlossen sein — ein nicht-terminaler
Auftrag ist der Beleg, dass ein Lauf abgebrochen ist, und er blockiert
`report next` fuer jeden Worker:

    lean-herdr report next

**Expected:** kein offener Auftrag. Steht doch einer da, wird er geschlossen:
`lean-herdr dispatch cancel --task-id o-… --message "closed for the one-binary migration"`.

### README, letzter Durchgang

@call patch("README.md", "die Abhaengigkeitstabelle und der Abschnitt `What else ships here`")

Zwei Stellen sind nach fuenf Tasks noch nicht nachgezogen: die Tabelle nennt
`lean-herdr` selbst noch nicht als installiertes Werkzeug, und `What else ships
here` erwaehnt die Vorlagen nicht.

    | `lean-herdr` (this project) | one binary, three verbs: dispatch, report, workspace | `uv tool install --editable .` |

    - `lean_herdr/templates/` -- everything `lean-herdr workspace init` writes
      into a project. The copies in this repository are copies of exactly
      these files, and `tests/test_templates.py` keeps them byte-identical.

@call verify(README.md)
@call gate(.)
@call commit(".", "docs: describe the one-binary setup and the workspace verbs")
@call remember_decision("lean-herdr: the project is installed as `uv tool install --editable .` and needs `lean-ctx allow lean-herdr`; bin/herdr-dispatch and bin/herdr-report are gone (bin/herdr-llm STAYS -- it belongs to the LLM plan and is still a bare-python3 script in tests/test_manifest.py), and the role prompts live in .lean-ctx/lean-herdr/roles/. Migrating an existing checkout means closing every open order first -- running workers lose bin/herdr-report.")
@phase-end
