@lean-md
consumer: ai
crp: compact

@var test_cmd default="uv run pytest -q" desc="project test runner command"
@var lint_cmd default="uv run ruff check ." desc="project lint gate"
@import .lean-ctx/lean-md/plan-recipes /

# lean-herdr — die offenen Befunde des Katalog-Branches

Quelle: `docs/specs/2026-09-13-lean-herdr-katalog-review-und-sdk-1-1-design.md` (v1.0), Teil A.
Render je Task:
`lean-md render docs/lean-md/plans/2026-09-13-lean-herdr-katalog-review.lmd.md --phase task-N`.

## Goal

Das Final-Review des Katalog-Branches (`448b336..b25dd98`) endete mit offenen
Befunden; dieser Plan schließt sie. Die Nummern folgen der Liste des Reviews —
7, 8 und 12 stehen dort nicht unter „offen" und kommen hier nicht vor.

- **Task 1 — Format:** ein Commit über `lean_herdr/` und `tests/` ohne
  Verhaltensänderung. Danach ändert das Gate an keiner fremden Zeile mehr etwas,
  und jeder Fix-Commit zeigt nur den Fix (Spec 3.0).
- **Task 2–5 — Verhalten:** Befund 1 (der `init`-Report überlebt einen
  `[models]`-Fehler), 2 (das Overlay wird atomar geschrieben), 3 (`fetch()` hält
  „Never raises"), 13 (aus dem Overlay zählt nur `model`). Jeder neue Test
  scheitert vor seinem Fix.
- **Task 6 — Doku:** Befund 4, 5 und 6.
- **Task 7–8 — Wächter:** Befund 9, 10, 11 und 14. Diese Tests laufen sofort grün;
  widerlegt werden sie durch eine benannte Mutation, die vor dem Commit wieder
  verschwindet.

Teil B (SDK 1.1.0) und die Nachträge aus Spec §7 sind mit `6dfb9a9` und
`9fbb729` erledigt. Dafür gibt es keinen Task.

## Architecture

```
lean_herdr/ + tests/  ~  ruff format, sonst nichts                          (Task 1)
lean_herdr/
  initcmd.py     ~  workspace_init validiert [models] im try;
                    _warnings(..., overlay_auto=) statt eigenem Lesen       (Task 2)
  catalog.py     ~  write_overlay: .tmp-models.auto.toml + Path.replace     (Task 3)
                 ~  fetch: Guertel um den request-Seam                      (Task 4)
  settings.py    ~  llm_settings_layered: aus dem Overlay nur model         (Task 5)
  llm.py         ~  generate()-Docstring verweist auf THE TWO CHAINS        (Task 6)
  templates/config.toml ~ Kommentar zu [roles.orchestrator].model           (Task 6)
.lean-ctx/lean-herdr/config.toml ~ byte-gleich mit dem Template             (Task 6)
README.md        ~  fuenf Abschnitte; das leere Orchestrator-model          (Task 6)
tests/
  test_initcmd.py    +  Befund 1                                            (Task 2)
  test_catalog.py    +  Befund 2, 3, 9; ~ ..._as_five_dicts, eine Meldung   (Task 3, 4, 7)
  test_settings.py   +  Befund 13, 14; ~ ein Test umgeschrieben             (Task 5, 8)
  test_llm.py        ~  ein Test umgeschrieben                              (Task 5)
  test_dispatch.py   ~  ein Test umgeschrieben                              (Task 5)
  test_openrouter.py +  Befund 10                                           (Task 8)
  test_workspace.py  +  Befund 11                                           (Task 8)
  fixtures/openrouter-models.sample.json + mid/no-effort-list an Position 3 (Task 7)
```

## Global Constraints

- **Task 1 zuerst.** Jeder spätere Task setzt den formatierten Tree voraus: neuer
  Code in diesem Plan steht schon in der Form, die `ruff format` schreibt
  (Zeilenlänge 100, `except A, B:` nach PEP 758 auf dem Syntax-Boden 3.14). Die
  übrigen Tasks sind inhaltlich unabhängig, laufen aber der Reihe nach, weil sie
  Dateien teilen (`tests/test_catalog.py`: 3, 4, 7; `tests/test_settings.py`: 5, 8).
- **Anker statt Zeilennummern.** Task 1 verschiebt Zeilen in 45 Dateien; jede
  Zeilennummer der Spec stammt von davor. Bestehender Code wird über `@symbol`,
  `@read … mode=signatures` und `@call patch(…)` gefunden, bestehende Tests über
  ihren Namen.
- **Kein gemeinsamer Helfer** für atomares Schreiben oder den Seam-Gürtel. Jeder
  Fix steht an seiner Quelle (Spec §3, §8); `orderlog.py` und `llm.complete()`
  bleiben unberührt.
- **`dispatch.py` wird nicht angefasst**, auch nicht für Befund 5 — dort ändern
  sich nur README und Template.
- **Kein toleranter Leser für ein kaputtes Overlay.** Ein unbekannter Schlüssel,
  ein falscher Typ oder ein ungültiger Wert bleibt `SettingsError`;
  `test_a_broken_overlay_is_a_config_error_too` und
  `test_a_broken_overlay_costs_the_defaults_not_the_commit` bleiben unverändert
  grün. Ein **gültiges** fremdes Feld im Overlay wird ignoriert, nicht abgelehnt.
- **`write_overlay` schreibt weiter nur `model`.**
- **Wächter-Tasks (7, 8) ändern keine Produktionsdatei.** Vor ihrem Commit endet
  `git diff --quiet -- lean_herdr/` mit Exit 0.
- **Non-Goals:** kein Komplexitäts-Refactor (`_clears` bleibt bei cc=26), kein
  Formatieren von `docs/`, kein Einbau der `leanctx-sdk`, keine neue Abhängigkeit.

@phase "task-1"
## Task 1: Format-Commit über `lean_herdr/` und `tests/`

**Files:** jede Datei, die `ruff format` unter `lean_herdr/` und `tests/`
umschreibt — 45 am 2026-09-13 —, und keine andere. **Nicht:** `docs/` (ruff
formatiert Python-Codeblöcke in Markdown und schriebe die Mess-Skripte um, die in
drei Specs als Beleg stehen), `README.md`, `bin/herdr-llm`.

**Interfaces:** keine. Kein Verhalten und kein Test ändert sich.

Die Zahlen 45, 17 und 62 unten gelten für `9fbb729` und bleiben gültig, solange
kein Commit davor `lean_herdr/` oder `tests/` berührt. Weichen sie ab, tragen das
AST-Skript, `ruff check` und dieselbe Zahl `N passed` den Nachweis — nicht die Zahlen.

### Schritt 1 — die Ausgangslage messen

Run: `uv run pytest -q` — Expected: PASS. Die Zahl `N passed` notieren.

Run: `uv run ruff format --check lean_herdr tests`
— Expected: `45 files would be reformatted, 17 files already formatted`, Exit 1.

### Schritt 2 — formatieren

Run: `uv run ruff format lean_herdr tests`
— Expected: `45 files reformatted, 17 files left unchanged`.

Dabei wird `except (A, B):` zu `except A, B:`. Das ist PEP 758, gültig ab
Python 3.14, dem Syntax-Boden des Projekts; `/usr/bin/python3`, auf dem
`bin/herdr-llm` läuft, ist 3.14.7. **Nicht zurückdrehen.**

### Schritt 3 — nachweisen, dass sich nur die Form geändert hat

Das Prüfskript läuft über stdin und wird nicht eingecheckt. Es vergleicht den AST
jeder geänderten Datei mit `HEAD`. Strings werden vorher auf ihre Wörter
normalisiert, weil `ruff format` Docstrings neu einrückt; eine geänderte
Anweisung, ein anderer Name oder Wert fällt trotzdem auf.

    uv run python - <<'EOF'
    import ast
    import subprocess
    import sys


    def shape(source: str) -> str:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                node.value = " ".join(node.value.split())
        return ast.dump(tree)


    def git(*args: str) -> str:
        return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


    names = git("diff", "--name-only").split()
    stray = [n for n in names if not (n.startswith(("lean_herdr/", "tests/")) and n.endswith(".py"))]
    moved = [
        n
        for n in names
        if n not in stray and shape(git("show", f"HEAD:{n}")) != shape(open(n, encoding="utf-8").read())
    ]
    print(f"{len(names)} files | outside lean_herdr/+tests/ or not .py: {stray} | AST changed: {moved}")
    sys.exit(1 if stray or moved else 0)
    EOF

Expected: `45 files | outside lean_herdr/+tests/ or not .py: [] | AST changed: []`, Exit 0.

Run: `uv run ruff format --check lean_herdr tests` — Expected: `62 files already formatted`.

Run: {{ var lint_cmd }} — Expected: `All checks passed!`

Run: {{ var test_cmd }} — Expected: PASS, dieselbe Zahl `N passed` wie in Schritt 1.

### Verify & Close

@call commit("lean_herdr tests", "style: ruff format over lean_herdr/ and tests/, and nothing else")
@call remember_decision("lean_herdr/ and tests/ are ruff-formatted since task 1 of the catalogue-review plan: line-length 100, and except A, B: is PEP 758, correct on the 3.14 floor. Code shown in later tasks is already in that form.")
@phase-end

@phase "task-2"
## Task 2: Befund 1 — der `init`-Report überlebt einen `[models]`-Fehler

**Files:** `lean_herdr/initcmd.py`, `tests/test_initcmd.py`.

**Interfaces — Produces:**
`_warnings(root: Path, *, data: dict[str, Any], overlay_auto: bool, runner: Any = subprocess.run) -> list[str]`
— ruft `models_settings()` nicht mehr selbst. Einziger Aufrufer ist
`workspace_init`; kein Test ruft `_warnings` direkt.

**Ist-Zustand:** `_warnings()` liest `models_settings(data).auto` selbst und läuft
in `workspace_init` **hinter** dem `try`, der `SettingsError` fängt.
`[models] auto = 1` passiert `settings_for` und `model_warnings` und fliegt erst in
`_warnings` — nachdem die Dateien geschrieben sind.

@read lean_herdr/initcmd.py mode=signatures
@symbol body name=workspace_init

@call tdd(tests/test_initcmd.py::test_a_broken_models_block_costs_the_warm_up_and_not_the_report)

Rot heißt hier: `SettingsError: models.auto: 1 is int, not bool` fliegt aus
`workspace_init`.

### Der Test

In `tests/test_initcmd.py`, direkt nach
`test_a_broken_worker_block_costs_the_warm_up_and_not_the_report`:

    def test_a_broken_models_block_costs_the_warm_up_and_not_the_report(monkeypatch, repo):
        """`[models]` is the table `_warnings` acts on, and nobody validated it first.

        `auto = 1` passes `settings_for` and `model_warnings` untouched and used to
        raise out of `_warnings` -- after the files were written, so `main()` answered
        with a bare `config_error:` and the written/skipped report was gone.
        """
        quiet(monkeypatch)
        (repo / SETTINGS_PATH).parent.mkdir(parents=True, exist_ok=True)
        (repo / SETTINGS_PATH).write_text("[models]\nauto = 1\n", encoding="utf-8")
        answer = workspace_init(root=repo)
        assert answer["ok"] is True
        assert answer["written"], "the report must survive"
        assert answer["warmed"] is False
        assert any(w.startswith("no warm-up: ") and "models.auto" in w for w in answer["warnings"])

### Der Fix

@call patch("lean_herdr/initcmd.py", "the def line, docstring and overlay check of _warnings, and the try/except around read_settings in workspace_init")

1. Die Signatur von `_warnings` wird:

        def _warnings(
            root: Path, *, data: dict[str, Any], overlay_auto: bool, runner: Any = subprocess.run
        ) -> list[str]:

2. In ihrem Docstring, nach dem Absatz, der mit „`data` is the settings file,
   already read." beginnt, ein neuer Absatz:

            `overlay_auto` is `[models].auto`, validated by the caller inside the
            guard that keeps the written/skipped report. Read here instead, a typo
            in `[models]` raised past that guard and took the report with it.

3. Im Tupel `checks` wird die Bedingung `if models_settings(data).auto` zu
   `if overlay_auto`; der Kommentar darüber bleibt:

                _check_overlay_ignored(root, runner) if overlay_auto else None,

4. In `workspace_init`, im `try` direkt nach `workspace_settings(data)`:

                # `[models]` is read here too, because `_warnings` acts on it: `auto`
                # decides whether the overlay's ignore rule is checked at all. Read
                # inside the guard and handed on as a plain bool -- a typo in it
                # costs the warm-up and that one check, never the report.
                overlay_auto = models_settings(data).auto

5. Im `except SettingsError`-Zweig wird `data, kind = {}, ""` zu:

                # Without a readable config nobody can say whether `auto` is on,
                # so the overlay's ignore rule is not checked either.
                data, kind, overlay_auto = {}, "", False

6. Der Aufruf darunter wird:

            warnings = _warnings(base, data=data, overlay_auto=overlay_auto, runner=runner) + warnings

`models_settings` bleibt importiert — `workspace_init` braucht es jetzt.

Ohne Änderung grün bleiben `test_the_gitignore_warning_only_appears_when_auto_is_on`,
`test_a_malformed_config_skips_the_warm_up_and_says_why` und
`test_a_broken_worker_block_costs_the_warm_up_and_not_the_report`.

### Verify & Close

@call verify(lean_herdr/initcmd.py tests/test_initcmd.py)
@call gate(lean_herdr/initcmd.py tests/test_initcmd.py)
@call commit("lean_herdr/initcmd.py tests/test_initcmd.py", "fix(init): validate [models] inside the guard, so a typo there costs the warm-up and not the report")
@phase-end

@phase "task-3"
## Task 3: Befund 2 — das Overlay wird atomar geschrieben

**Files:** `lean_herdr/catalog.py`, `tests/test_catalog.py`.

**Interfaces:** `write_overlay(model: str, *, root: Path, stamp: str | None = None) -> Path`
bleibt, wie sie ist. Neu ist nur, **wie** sie schreibt: nach
`.tmp-models.auto.toml` im selben Verzeichnis, dann `Path.replace`. Wirft Schreiben
oder Ersetzen `OSError`, löscht sie die Temp-Datei (`missing_ok=True`) und wirft
weiter; `check()` meldet wie heute `write_failed`.

**Warum löschen, wo `orderlog.append` es nicht tut:** `.gitignore` nennt genau
`.lean-ctx/lean-herdr/models.auto.toml`. Eine liegen gebliebene Temp-Datei stünde
in `git status` des Betreibers. Ein harter Abbruch zwischen Schreiben und Ersetzen
hinterlässt sie trotzdem — akzeptiert, denn `models.auto.toml` selbst ist dann
unberührt, nie halb geschrieben.

@symbol body name=write_overlay

@call tdd(tests/test_catalog.py::test_a_failed_replace_leaves_the_old_overlay_and_no_temp_file)

Rot heißt hier: `Failed: DID NOT RAISE <class 'OSError'>` — `write_text` schreibt
direkt, `replace` wird nie gerufen, und das alte Overlay ist schon überschrieben.

### Der Test

In `tests/test_catalog.py`, direkt nach `test_a_second_call_overwrites_the_file_whole`:

    def test_a_failed_replace_leaves_the_old_overlay_and_no_temp_file(monkeypatch, tmp_path):
        """The overlay is never half-written, and a failed attempt leaves nothing behind.

        `.gitignore` names `models.auto.toml` exactly. A `.tmp-` file left beside it
        would show up in the operator's `git status` -- which is why `write_overlay`
        removes it, where `orderlog.append` does not have to.
        """
        path = catalog.write_overlay("good/all-clear", root=tmp_path)
        before = path.read_text(encoding="utf-8")

        def refuse(self, target):
            raise OSError("the disk said no")

        monkeypatch.setattr(type(path), "replace", refuse)
        with pytest.raises(OSError, match="the disk said no"):
            catalog.write_overlay("mid/small-context", root=tmp_path)
        assert path.read_text(encoding="utf-8") == before
        assert list(path.parent.glob(".tmp-*")) == []

### Der Fix

@call patch("lean_herdr/catalog.py", "the docstring and the body of write_overlay")

1. Im Docstring, nach dem Absatz „Never edited in place, and that is not a
   shortcut: …", ein neuer Absatz:

            WHOLE also means never HALF: the text goes to `.tmp-models.auto.toml`
            beside the overlay, and `Path.replace` swaps it in -- the recipe of
            `orderlog.append`, without `fsync` for the same reason. A hard kill
            between the two leaves the temp file behind and the overlay untouched.

2. Der Rumpf ab `path = Path(root) / OVERLAY_PATH` bis vor `return path` wird:

            path = Path(root) / OVERLAY_PATH
            tmp = path.with_name(f".tmp-{path.name}")
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                tmp.write_text(
                    f"# written by `lean-herdr models` on {when}. Do not edit --\n"
                    "# the next run overwrites this file. Your own choice belongs in\n"
                    f"# {SETTINGS_PATH}, which wins over this one.\n"
                    "[llm]\n"
                    f'model = "{model}"\n',
                    encoding="utf-8",
                )
                tmp.replace(path)
            except OSError:
                # `.gitignore` names the overlay EXACTLY, so a temp file left here
                # would sit in the operator's `git status`. `orderlog.append` may
                # leave its own behind; this one may not.
                tmp.unlink(missing_ok=True)
                raise

   Der Text der Datei ist unverändert. `mkdir` bleibt **vor** dem `try`:
   `test_a_filesystem_that_refuses_is_a_reason_and_not_a_crash` legt eine Datei an
   die Stelle von `.lean-ctx`, und dieses `OSError` hat keine Temp-Datei zum
   Löschen.

Ohne Änderung grün bleiben `test_a_second_call_overwrites_the_file_whole`,
`test_the_overlay_is_valid_toml_although_we_have_no_writer` und
`test_a_filesystem_that_refuses_is_a_reason_and_not_a_crash`.

### Verify & Close

@call verify(lean_herdr/catalog.py tests/test_catalog.py)
@call gate(lean_herdr/catalog.py tests/test_catalog.py)
@call commit("lean_herdr/catalog.py tests/test_catalog.py", "fix(catalog): write the overlay through a temp file, and take the temp file away when that fails")
@phase-end

@phase "task-4"
## Task 4: Befund 3 — `fetch()` hält „Never raises"

**Files:** `lean_herdr/catalog.py`, `tests/test_catalog.py`.

**Interfaces:** `fetch(*, requires, limit=CATALOG_LIMIT, timeout_s=CATALOG_TIMEOUT_S, request=openrouter.request) -> list[dict[str, Any]] | None`
bleibt. Wirft der injizierte `request` `OSError` oder `ValueError`, liefert
`fetch()` `None`; `check()` macht daraus wie heute `no_catalog`.

**Muster:** der `try/except` um `request(...)` in `llm.complete()` —
`openrouter.request` wirft nie, aber `request` ist injizierbar, und das Versprechen
gibt die Funktion selbst.

@read lean_herdr/catalog.py mode=signatures

@call tdd(tests/test_catalog.py::test_a_request_seam_that_raises_is_no_catalogue)

Rot heißt hier: beide Parameter scheitern mit der Exception selbst
(`OSError: refused`, `ValueError: bad url`).

### Der Test

In `tests/test_catalog.py`, direkt nach
`test_fetch_answers_every_unusable_reply_with_none`:

    @pytest.mark.parametrize(
        "error", [OSError("refused"), ValueError("bad url")], ids=["oserror", "valueerror"]
    )
    def test_a_request_seam_that_raises_is_no_catalogue(tmp_path, error):
        """`fetch()` promises "never raises" itself -- it does not borrow that from a default.

        `openrouter.request` answers every failure with None, but `request` is
        injectable, and `check()` stands between `workspace up` and a price comparison.
        Same belt, same reason as `llm.complete()`.
        """

        def boom(url, **kwargs):
            raise error

        assert catalog.fetch(requires=("reasoning",), request=boom) is None
        outcome = catalog.check(
            root=tmp_path, settings=ModelsSettings(auto=True), efforts=(), request=boom
        )
        assert outcome == {"written": False, "model": None, "reason": "no_catalog"}
        assert not (tmp_path / OVERLAY_PATH).exists()

### Der Fix

@call patch("lean_herdr/catalog.py", "the request(...) call in fetch")

Die eine Zeile `raw = request(f"{CATALOG_URL}?…", timeout_s=timeout_s)` in
`fetch()` wird:

        try:
            raw = request(f"{CATALOG_URL}?{urllib.parse.urlencode(query)}", timeout_s=timeout_s)
        except OSError, ValueError:
            # The belt on the SEAM, as in `llm.complete()`: `openrouter.request`
            # answers every failure with None already, but `request` is
            # injectable, and "never raises" is a promise this function makes
            # itself -- `check()` and `workspace up` stand behind it.
            return None

`except OSError, ValueError:` ist PEP 758 und genau die Form, die `ruff format`
seit Task 1 schreibt. **Keine Klammern ergänzen** — das Gate nähme sie wieder weg.

### Verify & Close

@call verify(lean_herdr/catalog.py tests/test_catalog.py)
@call gate(lean_herdr/catalog.py tests/test_catalog.py)
@call commit("lean_herdr/catalog.py tests/test_catalog.py", "fix(catalog): put the belt on the request seam in fetch(), as complete() has it")
@phase-end

@phase "task-5"
## Task 5: Befund 13 — aus dem Overlay zählt nur `model`

**Files:** `lean_herdr/settings.py`, `tests/test_settings.py`, `tests/test_llm.py`,
`tests/test_dispatch.py`.

**Interfaces:** `llm_settings_layered(root: str | Path, data: dict[str, Any] | None = None) -> LlmSettings`
bleibt. Neu ist die Regel: aus dem Overlay kommt **nur** `model`, und nur, wo
`config.toml` schweigt (`""` gilt als Schweigen). Jedes andere `[llm]`-Feld kommt
allein aus `config.toml` oder bleibt `""`.

**Die Grenze der Regel:** das Overlay läuft weiter **vollständig** durch
`llm_settings()`. Unbekannter Schlüssel, falscher Typ, ungültiger Wert (etwa
`effort = "enormous"`) bleiben `SettingsError` — erst danach wird `.model`
übernommen. Ein **gültiges** fremdes Feld wird ignoriert: abgelehnt ließe es
`dispatch` mit `config_error:` an einer Datei scheitern, die nichts Falsches sagt.

Damit stimmt der Leser mit dem Kettenblock THE TWO CHAINS in `llm.py`, dem
Schreiber `write_overlay`, dem README und dem Template überein; die alle kennen das
Overlay schon nur als Stufe für `model`.

@symbol body name=llm_settings_layered

@call tdd(tests/test_settings.py::test_the_overlay_gives_model_and_nothing_else)

Rot heißt hier: `effort="low"` und `prereview_model="auto/judge"` aus dem Overlay
kommen an.

### Die Tests — einer neu, drei umgeschrieben

**Neu**, in `tests/test_settings.py` direkt nach
`test_config_toml_alone_reaches_the_caller`:

    def test_the_overlay_gives_model_and_nothing_else(tmp_path):
        """The check writes one key, and the chain in llm.py knows the overlay for one key.

        A valid `effort` or `prereview_model` in the overlay is IGNORED, not refused:
        refusing it would fail `dispatch` over a file that says nothing wrong. An invalid
        one still raises -- `test_a_broken_overlay_is_a_config_error_too` holds that.
        """
        from lean_herdr.settings import LlmSettings, llm_settings_layered

        _write_llm_files(
            tmp_path,
            config='[llm]\nprereview_effort = "high"\n',
            overlay='[llm]\nmodel = "auto/pick"\neffort = "low"\nprereview_model = "auto/judge"\n',
        )
        got = llm_settings_layered(tmp_path)
        assert got == LlmSettings(model="auto/pick", prereview_effort="high")

**Umgeschrieben** — die drei bestehenden Tests verlangen heute das Gegenteil. Sie
werden ersetzt, nicht gelöscht; ihr Zweck bleibt.

1. `test_config_toml_beats_the_overlay_field_by_field` in `tests/test_settings.py`
   wird ganz ersetzt, **umbenannt**, weil „field by field" genau die Mischung
   benennt, die dieser Fix abschafft. Er ist vor dem Fix ebenfalls rot:

        def test_config_toml_beats_the_overlay_where_it_speaks(tmp_path):
            """The operator's hand survives every daily check.

            The overlay is what a machine wrote. Where config.toml names `model`, the
            overlay's `model` is gone -- and the three other keys it carries here never
            arrive at all, spoken over or not.
            """
            from lean_herdr.settings import LlmSettings, llm_settings_layered

            _write_llm_files(
                tmp_path,
                config='[llm]\nmodel = "by/hand"\nprereview_effort = "high"\n',
                overlay=(
                    '[llm]\nmodel = "auto/pick"\nprereview_model = "auto/judge"\n'
                    'effort = "low"\nprereview_effort = "minimal"\n'
                ),
            )
            got = llm_settings_layered(tmp_path)
            assert got == LlmSettings(model="by/hand", prereview_effort="high")

2. `test_the_overlay_is_read_under_config_toml` in `tests/test_llm.py` wird ganz
   ersetzt. Den Beweis führt jetzt `model` aus dem Overlay unter einem
   `config.toml` ohne `model`; grün vor und nach dem Fix:

        def test_the_overlay_is_read_under_config_toml(tmp_path):
            """Both files reach `generate()`: the overlay's `model`, under config.toml's lines.

            The proof is `model`, because `model` is the one key the overlay gives --
            config.toml here is silent on it and speaks on `prereview_model` instead.
            """
            _write_config(tmp_path, '[llm]\nprereview_model = "by/hand"\n')
            overlay = tmp_path / OVERLAY_PATH
            overlay.write_text('[llm]\nmodel = "auto/pick"\n', encoding="utf-8")
            got = llm.file_settings(tmp_path)
            assert got.model == "auto/pick"
            assert got.prereview_model == "by/hand"

3. `test_the_overlay_reaches_dispatch_under_config_toml` in `tests/test_dispatch.py`
   wird ganz ersetzt, nach demselben Muster; grün vor und nach dem Fix:

        def test_the_overlay_reaches_dispatch_under_config_toml(monkeypatch, tmp_path):
            """The layering llm.file_settings() applies, out of the same function.

            Read the overlay in only one of the two and the commit generator and
            the pre-review judge would run on different models the moment one
            exists. The proof is `model`, the one key the overlay gives, under a
            config.toml that is silent on it.
            """
            root = tmp_path / "repo"
            _write_config(root, '[llm]\nprereview_model = "by/hand"\n')
            (root / OVERLAY_PATH).write_text('[llm]\nmodel = "auto/pick"\n', encoding="utf-8")
            monkeypatch.setattr("lean_herdr.dispatch.canonical_root", lambda *a, **kw: root)
            seen = []

            def spy(_request, **kwargs):
                seen.append(kwargs["llm_cfg"])
                return {"ok": True}

            monkeypatch.setattr("lean_herdr.dispatch.dispatch", spy)
            monkeypatch.setattr("lean_herdr.dispatch.await_task", spy)

            main(["builder", "--kind", "claude", "--await", "--task-id", "T1"])

            assert seen[0].model == "auto/pick"
            assert seen[0].prereview_model == "by/hand"

### Der Fix

@call patch("lean_herdr/settings.py", "the docstring and the return statement of llm_settings_layered")

1. Im Docstring, nach dem ersten Absatz („The overlay is what the daily check
   wrote; …"), ein neuer Absatz:

            The overlay gives `model` and NOTHING else. The daily check writes that
            one key, and the THE TWO CHAINS block in llm.py knows the overlay as a
            level for `model` only. Any other `[llm]` field comes out of config.toml
            or stays "" -- whatever else a hand put into the overlay has no effect.

2. Die beiden Zeilen `below = …` und `above = …` bleiben. Das `return LlmSettings(**{…})`
   darunter wird, samt Kommentar davor:

            # The overlay went through `llm_settings()` WHOLE above: an unknown
            # key, a wrong type or an invalid value is already a SettingsError.
            # Only now is `model` lifted out of it. A valid foreign field is
            # ignored, not refused -- refusing it would fail `dispatch` over a
            # file that says nothing wrong, only nothing that counts.
            return replace(above, model=above.model or below.model)

   `replace` ist in `settings.py` schon aus `dataclasses` importiert; `fields`
   bleibt ebenfalls in Gebrauch.

Run: `uv run pytest -q tests/test_settings.py tests/test_llm.py tests/test_dispatch.py`
— Expected: PASS. Ohne Änderung grün darunter:
`test_a_broken_overlay_is_a_config_error_too`,
`test_a_broken_overlay_costs_the_defaults_not_the_commit`,
`test_an_empty_value_in_the_foreground_lets_the_overlay_through`,
`test_handed_in_data_beats_the_file_on_disk`.

### Verify & Close

@call verify(lean_herdr/settings.py tests/test_settings.py tests/test_llm.py tests/test_dispatch.py)
@call gate(lean_herdr/settings.py tests/test_settings.py tests/test_llm.py tests/test_dispatch.py)
@call commit("lean_herdr/settings.py tests/test_settings.py tests/test_llm.py tests/test_dispatch.py", "fix(settings): take model and nothing else from the overlay, as the chain and the writer already say")
@call remember_decision("llm_settings_layered takes only model from models.auto.toml, and only where config.toml is silent. The overlay still goes through llm_settings() whole first, so an invalid overlay stays a SettingsError; a valid foreign field is ignored.")
@phase-end

@phase "task-6"
## Task 6: Doku — Befund 4, 5 und 6

**Files:** `README.md`, `lean_herdr/templates/config.toml`,
`.lean-ctx/lean-herdr/config.toml`, `lean_herdr/llm.py` (nur Docstring).

**Interfaces:** keine. Kein Code ändert sein Verhalten; `dispatch.py` bleibt, wie
Task 4 des Katalog-Plans es gewollt hat — für `--model` gibt es keine
Rollentabelle, weil ein Modell, das niemand nennt, Geld kostet.

### Befund 4 — `README.md` zählt fünf Abschnitte

@call patch("README.md", "the paragraph that begins with Four sections in the Configuration section")

Der Absatz wird ganz ersetzt:

    Five sections: `[default]` and `[roles.<role>]` describe how a pane is
    split, `[llm]` the commit generator and the pre-review judge, and
    `[workspace]` the pane `lean-herdr workspace up` opens for the
    orchestrator — `label` alone, and that one optional. `[models]` decides
    whether `workspace up` may keep `[llm].model` current from OpenRouter's
    catalogue by itself; see [Keeping the model current](#keeping-the-model-current).

### Befund 5 — das leere Orchestrator-`model`, richtig beschrieben

@call patch("README.md", "the paragraph that begins with --kind and --model on a dispatch call beat the file")

Der Absatz wird ganz ersetzt:

    `--kind` and `--model` on a `dispatch` call beat the file; with neither,
    `dispatch` refuses to build. A worker quietly running on its runtime's
    default model costs real money and nobody sees it. The orchestrator is the
    one exception, and only where it is started: an empty `model` means no
    `--model` at all for `lean-herdr workspace up` and for the keystroke, which
    is what the keystroke has always done. `dispatch orchestrator` is not a
    start and has no such exception — it needs `--model` or a set `model`.

@call patch("lean_herdr/templates/config.toml", "the model line under # [roles.orchestrator]")

Die eine Zeile `# model = ""           # empty: no --model at all` wird zu zwei:

    # model = ""           # empty: no --model on `workspace up` or the keystroke;
    #                      # `dispatch orchestrator` still needs --model or this key

Dieselbe Änderung, byte-gleich, in `.lean-ctx/lean-herdr/config.toml`:

@call patch(".lean-ctx/lean-herdr/config.toml", "the model line under # [roles.orchestrator]")

Run: `uv run pytest -q tests/test_templates.py` — Expected: PASS
(`test_template_and_checked_in_copy_are_byte_identical` ist der Beweis).

### Befund 6 — der `generate()`-Docstring verweist auf die Kette

@call patch("lean_herdr/llm.py", "the paragraph that begins with Resolution, in this order in the generate() docstring")

Der Absatz „Resolution, in this order: … clutter." wird ganz ersetzt; die achte
Beschreibung der Kette entfällt, statt korrigiert zu werden:

        Which model and which effort win is the THE TWO CHAINS block at the
        top of this module -- the authority, and the only description of the
        order in here. A copy in this docstring had already lost the overlay
        level once (M3).

Die Begründungen, die der alte Absatz trug (Umgebung über der Datei, keine
Umgebungsstufe für den Effort), stehen schon im Kettenblock.

### Verify & Close

`README.md` und die beiden TOML-Dateien gehen **nicht** durch `@reformat`: ruff
formatiert Python-Codeblöcke in Markdown.

@call verify(README.md lean_herdr/templates/config.toml .lean-ctx/lean-herdr/config.toml lean_herdr/llm.py)
Run: `uv run pytest -q tests/test_templates.py tests/test_language.py` — Expected: PASS.
@call gate(lean_herdr/llm.py)
@call commit("README.md lean_herdr/templates/config.toml .lean-ctx/lean-herdr/config.toml lean_herdr/llm.py", "docs: five config sections, the empty orchestrator model told right, and generate() pointing at the chain")
@phase-end

@phase "task-7"
## Task 7: Befund 9 — ein Modell ohne `supported_efforts`

**Files:** `tests/fixtures/openrouter-models.sample.json`, `tests/test_catalog.py`.
**Keine** Produktionsdatei.

**Interfaces:** keine. Der Wächter sichert Verhalten, das heute schon stimmt:
`_clears` verwirft ein Modell ohne Effort-Liste, sobald Efforts verlangt sind.

### Schritt 1 — der fünfte Fixture-Eintrag

@call patch("tests/fixtures/openrouter-models.sample.json", "the gap between the cheap/no-minimal-effort entry and the mid/small-context entry")

An Position 3 der `data`-Liste, zwischen `cheap/no-minimal-effort` und
`mid/small-context` (Komma davor und danach nicht vergessen):

    {
      "id": "mid/no-effort-list",
      "context_length": 200000,
      "pricing": {"prompt": "0.00000008", "completion": "0.0000003"},
      "supported_parameters": ["reasoning"],
      "reasoning": {"mandatory": true, "default_effort": "low"},
      "benchmarks": {
        "artificial_analysis": {
          "intelligence_index": 58.0,
          "coding_index": 56.0,
          "agentic_index": 45.0
        }
      }
    }

Die Position ist so gewählt, dass kein bestehendes Ergebnis kippt: mit `efforts=()`
gewinnt immer ein Eintrag davor, mit gesetzten `efforts` fällt der neue heraus.

Run: `uv run pytest -q tests/test_catalog.py`
— Expected: genau **1 failed**, `test_fetch_returns_the_recorded_page_as_four_dicts`
(die Liste hat jetzt fünf ids). Kippt ein anderer Test, stimmt die Position nicht —
anhalten und melden.

### Schritt 2 — zwei bestehende Tests anpassen

@call patch("tests/test_catalog.py", "test_fetch_returns_the_recorded_page_as_four_dicts and the total assertion in test_main_list_shows_the_survivors_and_writes_nothing")

1. `test_fetch_returns_the_recorded_page_as_four_dicts` heißt
   `test_fetch_returns_the_recorded_page_as_five_dicts`; die erwartete Liste wird:

            assert [entry["id"] for entry in models] == [
                "cheap/no-benchmarks",
                "cheap/no-minimal-effort",
                "mid/no-effort-list",
                "mid/small-context",
                "good/all-clear",
            ]

2. In `test_main_list_shows_the_survivors_and_writes_nothing` bleibt `total == 3`;
   die Meldung nennt beide Aussortierten:

            assert answer["total"] == 3, (
                "cheap/no-minimal-effort cannot do `minimal`, mid/no-effort-list lists no efforts"
            )

### Schritt 3 — das widerlegbare Paar

In `tests/test_catalog.py`, direkt nach
`test_a_model_that_cannot_do_the_effort_is_dropped`:

    @pytest.mark.parametrize(
        ("efforts", "expected"),
        [(("minimal",), "mid/small-context"), ((), "mid/no-effort-list")],
        ids=["an effort is asked for", "no effort is asked for"],
    )
    def test_a_model_without_an_effort_list_fails_only_the_effort_check(efforts, expected):
        """Missing evidence is not a pass -- for efforts as for benchmarks.

        `mid/no-effort-list` clears `min_coding_index=50.0` and is cheaper than
        `mid/small-context`, but lists no `supported_efforts`. Asked for an effort it
        is dropped and `mid/small-context` wins; asked for none it wins itself -- so
        the missing list alone is what dropped it.

        Remove the list check from `_clears` and the first case does not pick a wrong
        model, it errors: `level not in None` is a TypeError. That error IS the
        refutation, not a broken test.
        """
        picked = catalog.recommend(
            sample(), thresholds=ModelsSettings(min_coding_index=50.0), efforts=efforts
        )
        assert picked is not None
        assert picked["id"] == expected

Run: `uv run pytest -q tests/test_catalog.py` — Expected: PASS.

### Schritt 4 — die Mutation

@call patch("lean_herdr/catalog.py", "the two lines if not isinstance(supported, list): return False inside the if efforts: block of _clears")

Die zwei Zeilen `if not isinstance(supported, list):` und `return False` löschen.

Run: `uv run pytest -q tests/test_catalog.py::test_a_model_without_an_effort_list_fails_only_the_effort_check`
— Expected: **1 failed, 1 passed**. `an effort is asked for` scheitert mit einem
`TypeError` über `NoneType`, nicht mit einer falschen Wahl — das ist die
Widerlegung, kein kaputter Test. `no effort is asked for` bleibt grün.

Run: `git checkout -- lean_herdr/catalog.py`

Run: `git diff --quiet -- lean_herdr/` — Expected: Exit 0.

### Verify & Close

@call verify(tests/fixtures/openrouter-models.sample.json tests/test_catalog.py)
@call gate(tests/test_catalog.py)
@call commit("tests/fixtures/openrouter-models.sample.json tests/test_catalog.py", "test(catalog): a fifth fixture model without an effort list, and the pair that proves the list is what drops it")
@phase-end

@phase "task-8"
## Task 8: Befund 10, 11 und 14 — drei Wächter

**Files:** `tests/test_openrouter.py`, `tests/test_workspace.py`,
`tests/test_settings.py`. **Keine** Produktionsdatei — die Mutationen werden vor dem
Commit zurückgenommen.

**Interfaces:** keine. Jeder Test sichert Verhalten, das heute stimmt, und läuft
sofort grün.

### Befund 10 — `openrouter.py` importiert nichts aus `lean_herdr`

Muster: `test_importing_handlers_does_not_drag_in_the_workspace_subtree` in
`tests/test_handlers.py` — ein Subprozess, weil `sys.modules` in diesem Prozess
längst den Rest des Pakets kennt. `lean_herdr/__init__.py` importiert nichts.

@call patch("tests/test_openrouter.py", "the import block at the top")

`import subprocess` und `import sys` kommen zu den stdlib-Importen
(`io`, `json`, `subprocess`, `sys`, `urllib.error`). Am Ende der Datei:

    def test_openrouter_imports_nothing_from_lean_herdr():
        """The root of its subtree: `llm.py` and `catalog.py` import it, it imports neither.

        `bin/herdr-llm` loads this on the system interpreter at every commit, so anything
        it pulled in from the package would ride along. A subprocess, because pytest has
        long since imported the rest of `lean_herdr` into this one -- the pattern of
        `test_importing_handlers_does_not_drag_in_the_workspace_subtree`.
        """
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import lean_herdr.openrouter, sys;"
                    "print(sorted(m for m in sys.modules if m.split('.')[0] == 'lean_herdr'))"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        assert proc.stdout.strip() == "['lean_herdr', 'lean_herdr.openrouter']", (
            proc.stdout + proc.stderr
        )

Run: `uv run pytest -q tests/test_openrouter.py::test_openrouter_imports_nothing_from_lean_herdr` — Expected: PASS.

**Mutation:** in `lean_herdr/openrouter.py` unter den Importen
`from lean_herdr.settings import SETTINGS_PATH` einfügen.

Run: `uv run pytest -q tests/test_openrouter.py::test_openrouter_imports_nothing_from_lean_herdr`
— Expected: FAIL, die Liste enthält `lean_herdr.settings`.

Run: `git checkout -- lean_herdr/openrouter.py`

### Befund 11 — `workspace up` reicht beide Effort-Stufen

Muster: `test_up_with_auto_on_carries_the_catalogue_answer` — `catalog.check` wird
durch `checked(**kwargs)` ersetzt, `start_orchestrator` durch ein Lambda.

@read lean_herdr/workspace.py mode=signatures

@call patch("tests/test_workspace.py", "the import block at the top")

Neuer Import: `from lean_herdr.llm import GENERATE_EFFORT, PREREVIEW_EFFORT`. Direkt
nach `test_up_with_auto_on_carries_the_catalogue_answer`:

    @pytest.mark.parametrize(
        ("llm_block", "expected"),
        [
            ('\n[llm]\neffort = "high"\nprereview_effort = "medium"\n', ("high", "medium")),
            ("", (GENERATE_EFFORT, PREREVIEW_EFFORT)),
        ],
        ids=["both levels from [llm]", "both levels from llm.py"],
    )
    def test_up_hands_the_catalogue_both_effort_levels_in_order(
        monkeypatch, tmp_path, llm_block, expected
    ):
        """One `[llm].model` serves two jobs, so the check has to know both efforts.

        The generator's first, the judge's second. The two values in `[llm]` differ on
        purpose: two equal ones would let a swap in `workspace_up` pass. The fallback
        row takes the constants from llm.py, the way `up` does.
        """
        _write_config(tmp_path, AUTO_ON + llm_block)
        herdr, _ = herdr_with(monkeypatch, {})
        seen: dict[str, object] = {}

        def checked(**kwargs):
            seen.update(kwargs)
            return {"written": False, "model": None, "reason": "fresh"}

        monkeypatch.setattr(workspace, "start_orchestrator", lambda **kw: {"ok": True})
        monkeypatch.setattr("lean_herdr.catalog.check", checked)
        workspace.workspace_up(root=tmp_path, herdr=herdr)
        assert seen["efforts"] == expected

Run: `uv run pytest -q tests/test_workspace.py::test_up_hands_the_catalogue_both_effort_levels_in_order` — Expected: 2 passed.

**Mutation a — vertauscht:** in `workspace_up` die beiden Zeilen im Tupel
`efforts=(…)` vertauschen (`llm_cfg.prereview_effort or PREREVIEW_EFFORT` zuerst).

Run: `uv run pytest -q tests/test_workspace.py::test_up_hands_the_catalogue_both_effort_levels_in_order` — Expected: 2 failed.

Run: `git checkout -- lean_herdr/workspace.py`

**Mutation b — gestrichen:** die Zeile `llm_cfg.prereview_effort or PREREVIEW_EFFORT,`
löschen.

Run: `uv run pytest -q tests/test_workspace.py::test_up_hands_the_catalogue_both_effort_levels_in_order` — Expected: 2 failed.

Run: `git checkout -- lean_herdr/workspace.py`

### Befund 14 — `_TYPES` und `ALLOWED` laufen nicht auseinander

In `tests/test_settings.py`, direkt nach `test_the_profile_follows_the_role`:

    def test_every_allowed_role_key_has_a_type():
        """`ALLOWED` comes from the RoleSettings fields, `_TYPES` is written by hand.

        `_check_types` lets a key through on `ALLOWED` and then indexes `_TYPES[key]`:
        a field added to the dataclass and forgotten in the table is not a SettingsError
        but a KeyError, where every caller expects a SettingsError.
        """
        from lean_herdr import settings

        assert set(settings._TYPES) == settings.ALLOWED

Run: `uv run pytest -q tests/test_settings.py::test_every_allowed_role_key_has_a_type` — Expected: PASS.

**Mutation:** in `lean_herdr/settings.py` den Eintrag `"shares_builder_model": bool,`
aus `_TYPES` löschen.

Run: `uv run pytest -q tests/test_settings.py::test_every_allowed_role_key_has_a_type` — Expected: FAIL.

Run: `git checkout -- lean_herdr/settings.py`

### Verify & Close

Run: `git diff --quiet -- lean_herdr/` — Expected: Exit 0.

@call verify(tests/test_openrouter.py tests/test_workspace.py tests/test_settings.py)
@call gate(tests/test_openrouter.py tests/test_workspace.py tests/test_settings.py)
@call commit("tests/test_openrouter.py tests/test_workspace.py tests/test_settings.py", "test: three guards that held by convention -- the import root of openrouter, both efforts on up, and _TYPES against ALLOWED")
@phase-end
