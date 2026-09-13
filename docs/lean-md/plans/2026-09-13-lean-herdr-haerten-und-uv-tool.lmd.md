@lean-md
consumer: ai
crp: compact

@var test_cmd default="uv run pytest -q" desc="project test runner command"
@var lint_cmd default="uv run ruff check" desc="project lint gate"
@import .lean-ctx/lean-md/plan-recipes /

# lean-herdr — `workspace up` und Konfiguration härten, ein Install für alle Projekte

Quelle: `docs/specs/2026-09-13-lean-herdr-haerten-und-uv-tool-design.md` (v1.0).
Render je Task:
`lean-md render docs/lean-md/plans/2026-09-13-lean-herdr-haerten-und-uv-tool.lmd.md --phase task-N`.

## Goal

`lean-herdr` läuft in jedem Repository dieser Maschine aus **einem** nicht-editablen
Snapshot von `main`. `workspace up` und die Konfiguration verlieren die gemessenen
Fehlerpfade (Spec §2.2). Die Templates werden projektneutral, bekommen ein Lock und
einen Update-Weg, der keine Hand-Edits überschreibt; `workspace check` sagt ohne zu
starten, ob `up` und `dispatch` laufen und wo es still schlechter wird.

- **Task 0 — Messen:** Snapshot-Quelle, Manifest-Verhalten von Herdr, Ignore-Regeln,
  `plugin unlink`, zwei pre-merge-Befehle in wt.
- **Task 1–4 — Fehlerpfade:** `GitUnusable`, `OverlayError`, nur lesen was gebraucht
  wird, ein Temp-Name pro Overlay-Schreiber samt Ignore-Urteil je Pfad.
- **Task 5–7 — Templates und Prüfung:** `templating.py` mit Token, Lock und Zuständen,
  `init --test/--lint/--update`, `workspace check`.
- **Task 8–9 — Install-Oberfläche:** Verben `llm`/`plugin`, Manifest im Paket,
  `bin/herdr-llm` entfällt; README, `.gitignore`.
- **Task 10 — nach dem Merge:** Migration dieses Repos und Abnahme (Spec §1, §10).

## Architecture

```
lean_herdr/
  bus.py          +  GitUnusable(BusError) aus canonical_root                          (T1)
  settings.py     +  OverlayError(SettingsError) aus llm_settings_layered              (T2)
  llm.py          ~  file_settings: kaputtes Overlay -> config.toml allein             (T2)
                  ~  prog und stderr-Präfix `lean-herdr llm`, Docstrings              (T8)
  workspace.py    ~  up: llm_settings vor dem Start, liest kein Overlay               (T3)
                  ~  Wort `check`; --update/--test/--lint nur für init                 (T6, T7)
  catalog.py      ~  main: Efforts aus llm_settings, nur `check` liest das Overlay     (T3)
                  ~  write_overlay: mkstemp je Schreiber + os.replace                  (T4)
  dispatch.py     ~  main: Overlay nur bei --await                                    (T3)
  initcmd.py      ~  GitUnusable vor BusError                                         (T1)
                  +  _check_temp_ignored                                              (T4)
                  ~  rendert über templating, _place nimmt Bytes                       (T5)
                  ~  Lock, Zustände, --test/--lint/--update                            (T6)
                  -  _read, _check_*, _warnings -> checkcmd                            (T7)
  templating.py   +  TEMPLATES LAYOUT DEFAULT_VALUES VALUE_RE render                   (T5)
                  +  LOCK_PATH LockError read_lock write_lock file_state
                     resolve_values state_warnings                                    (T6)
  checkcmd.py     +  workspace_check, machine_report, install_report, Generator,
                     Plugin-Link, Temp-Reste                                          (T7)
  cli.py          ~  Verben llm und plugin, Import-Crash ohne stdout                   (T8)
  __main__.py     -  sys.path-Eingriff                                                (T8)
  plugin/herdr-plugin.toml  +  Befehle ["lean-herdr", "plugin", "<sub>"]              (T8)
  templates/{wt.toml,settings.json,opencode.jsonc}  ~  Token                          (T5)
  templates/config.toml  ~  Kommentar ohne bin/herdr-llm                              (T9)
bin/herdr-llm     -                                                                   (T8)
.lean-ctx/lean-herdr/templates.lock.json  +                                           (T6, T9)
opencode.jsonc, .claude/settings.json, .config/wt.toml  ~  gerendert                  (T5)
README.md, .gitignore  ~                                                              (T9)
herdr-plugin.toml (Root)  -  erst nach dem Merge                                      (T10)
```

Diese Repo-Kopien sind Kopien: `tests/test_templates.py` hält jede gegen das gerenderte
Template, ab Task 6 zusätzlich gegen das Lock dieses Repos.

## Global Constraints

- **Reihenfolge (Spec §9).** Task 0 zuerst. 3 nach 2. 4 nach 0c. 5 nach 0e. 6 nach 5.
  7 nach 1, 2, 4 und 6 — und nie parallel zu 4, weil 7 `_check_overlay_ignored` samt
  Tests umzieht. 8 nach 0b. 9 nach 0a, 3, 4, 6, 7 und 8. 10 erst nach dem Merge.
  Die Tasks teilen Dateien (`initcmd.py`: 1, 4, 5, 6, 7; `workspace.py`: 3, 6, 7) und
  laufen deshalb der Reihe nach.
- **Beide Gate-Befehle in jedem Task und im Final-Gate:** `uv run pytest -q` **und**
  `uv run ruff check`. Das pre-merge-Gate dieses Repos ist bis Task 10 nicht approved
  und würde beim Merge still übersprungen.
- **Leitregel §4.1:** jede Stelle liest nur die Datei, deren Inhalt sie verwendet.
  Kein toleranter Leser in `up`, `dispatch`, `models check`; `llm.file_settings` bleibt
  der einzige Pfad, der nie wirft.
- **Kein gemeinsamer Helfer** für atomares Schreiben: Overlay (`catalog.write_overlay`)
  und Lock (`templating.write_lock`) schreiben je inline. Kein Lock gegen S1.
- **`llm` und `openrouter` bleiben stdlib-only, `llm` importiert nie `catalog`;**
  `dependencies = []`, keine neue Abhängigkeit.
- **Das Root-`herdr-plugin.toml` bleibt bis Task 10 Schritt 2 liegen und unverändert** —
  der Plugin-Link zeigt bis dahin auf den Checkout.
- **Keine Datei unter `lean_herdr/` über 800 Produktions-LOC** (gemessen in Task 7).
- **Anker statt Zeilennummern.** Zeilenangaben der Spec stammen von `93ba6f1`;
  bestehender Code wird über `@symbol`, `@read … mode=signatures` und Testnamen gefunden.
- **Non-Goals (§12):** keine Veröffentlichung; keine Agents-Konfiguration und kein
  Dispatch-Umbau (`dispatch.py` ändert nur, *wann* es das Overlay liest); kein
  Lint-Pflichtschritt in `builder.md`, kein Format-Check im Gate; kein automatisches
  Reinstall oder Template-Update; keine Erkennung des Projekttyps für `--test`/`--lint`.

@phase "task-0"
## Task 0: Messen, kein Code

**Files:** keine. Jedes Teilergebnis geht sofort nach `ctx_session`
(`action=finding`, Wert beginnt mit `task0/0a:` … `task0/0e:`), am Ende eine
Zusammenfassung über `remember_decision`. Keine Datei im Repo, kein Scratch-Ledger.

**Wer die Ergebnisse braucht:** 0a → Task 9 (Installzeile im README) und Task 10;
0b → Task 8; 0c → Task 4; 0d → Task 10; 0e → Task 5.

Alle Proben laufen unter `/tmp/lean-herdr-task0` und räumen hinter sich auf. Kein
Schritt ändert `~/.local/share/uv/tools/lean-herdr`, `~/.config/worktrunk/` oder den
bestehenden Link von `lean.herdr`.

    T=/tmp/lean-herdr-task0
    rm -rf "$T" && mkdir -p "$T"

### 0a — nicht-editabler Snapshot aus `main`, isoliert

    UV_TOOL_DIR="$T/tools" UV_TOOL_BIN_DIR="$T/bin" \
      uv tool install "lean-herdr @ git+file:///home/tholo/Scripts/lean-herdr@main"

Expected: Exit 0, `Installed 1 executable: lean-herdr`.

    "$T/tools/lean-herdr/bin/python" - "$T/bin/lean-herdr" <<'EOF'
    import importlib.metadata
    import sys
    from pathlib import Path

    import lean_herdr

    prefix = Path(sys.prefix).resolve()
    print("receipt", (prefix / "uv-receipt.toml").is_file())
    print("package_under_prefix", Path(lean_herdr.__file__).resolve().is_relative_to(prefix))
    print("binary_under_prefix", Path(sys.argv[1]).resolve().is_relative_to(prefix))
    print("direct_url", importlib.metadata.distribution("lean-herdr").read_text("direct_url.json"))
    print("templates", (Path(lean_herdr.__file__).parent / "templates" / "wt.toml").is_file())
    EOF
    "$T/bin/lean-herdr" --help

Expected: `receipt True`, `package_under_prefix True`, `binary_under_prefix True`,
`direct_url` ohne `"editable": true`, `templates True`, dann `usage: lean-herdr …`.

**Fallback**, falls uv `git+file` ablehnt — ein Wheel aus einem main-Worktree:

    git -C /home/tholo/Scripts/lean-herdr worktree add --detach "$T/main" main
    uv build --wheel --out-dir "$T/dist" "$T/main"
    UV_TOOL_DIR="$T/tools" UV_TOOL_BIN_DIR="$T/bin" uv tool install "$T"/dist/lean_herdr-*.whl
    git -C /home/tholo/Scripts/lean-herdr worktree remove "$T/main"

Danach dieselbe Python-Probe, dieselben Erwartungen.

Finding `task0/0a:` die Quelle, mit der es klappte, **genau so**, wie Task 9 und 10 sie
hinter `uv tool install --reinstall` schreiben. Erwartet:
`"lean-herdr @ git+file:///home/tholo/Scripts/lean-herdr@main"`.

### 0b — liest Herdr das Manifest bei jedem Event, oder kopiert `link` es?

Braucht einen laufenden Herdr-Server (H7).

    mkdir -p "$T/probe"
    cat > "$T/probe/herdr-plugin.toml" <<EOF
    id = "lean.probe"
    name = "lean-herdr probe"
    version = "0.0.1"
    min_herdr_version = "0.8.0"
    description = "task 0b"
    platforms = ["linux", "macos"]

    [[events]]
    on = "workspace.focused"
    command = ["sh", "-c", "echo first \$PWD >> $T/fired"]
    EOF
    herdr plugin link "$T/probe"
    herdr plugin list --plugin lean.probe

Expected: eine Zeile `- lean.probe (lean-herdr probe) enabled [local:/tmp/lean-herdr-task0/probe]`.

Einen Workspace fokussieren (in Herdr wechseln; oder `herdr workspace --help` für den
Befehl). Dann `cat "$T/fired"` — Expected: `first <cwd>`.

Jetzt im Manifest `first` durch `second` ersetzen, **ohne** neu zu linken, und wieder
einen Workspace fokussieren. `cat "$T/fired"`:

- zweite Zeile `second …` → Herdr liest das Manifest **live**;
- zweite Zeile `first …` → `link` hat es **kopiert**.

Finding `task0/0b:` `live` oder `kopiert`, und das `<cwd>` aus der Zeile (Spec §2.1
leitet ab, dass Herdr im verlinkten Verzeichnis startet).

Beide Ausgänge lassen den Plan unverändert: das Root-Manifest bleibt bis Task 10.
`kopiert` heißt nur, dass Task 8 den laufenden Plugin-Pfad gar nicht berührt.

### 0d — Syntax von `herdr plugin unlink`

    herdr plugin --help
    herdr plugin unlink --help

Mit der gefundenen Syntax die Probe entfernen, dann:

    herdr plugin list

Expected: keine Zeile `lean.probe`; `lean.herdr` weiter mit `[local:/home/tholo/Scripts/lean-herdr]`.

Finding `task0/0d:` die exakte Unlink-Zeile für `lean.herdr` (per ID oder per Pfad).

### 0c — `git check-ignore` für beide Regeln und alle drei Namen

    git init -q "$T/ignore"
    printf '%s\n' '.lean-ctx/lean-herdr/models.auto.toml' '.lean-ctx/lean-herdr/.tmp-*' \
      > "$T/ignore/.gitignore"
    git -C "$T/ignore" check-ignore -v \
      .lean-ctx/lean-herdr/models.auto.toml \
      .lean-ctx/lean-herdr/.tmp-models.auto.toml.k3j9x_ab \
      .lean-ctx/lean-herdr/.tmp-models.auto.toml.probe \
      .lean-ctx/lean-herdr/.tmp-templates.lock.json.q1w2e3

Expected: vier Zeilen; die erste nennt `.gitignore:1:`, die drei anderen `.gitignore:2:`.

    git -C "$T/ignore" check-ignore -v .lean-ctx/lean-herdr/templates.lock.json

Expected: keine Ausgabe, Exit 1 — das Lock bleibt versioniert.

    printf '%s\n' '.lean-ctx/lean-herdr/models.auto.toml' > "$T/ignore/.gitignore"
    git -C "$T/ignore" check-ignore -v .lean-ctx/lean-herdr/.tmp-models.auto.toml.probe

Expected: keine Ausgabe, Exit 1 — nur die Overlay-Regel lässt jeden Temp-Namen durch
(der Stand dieses Repos).

Finding `task0/0c:` Ignore-Zeile `.lean-ctx/lean-herdr/.tmp-*` bestätigt, Probe-Name
`.lean-ctx/lean-herdr/.tmp-models.auto.toml.probe` wird von ihr erfasst, das Lock nicht.

### 0e — wt: zwei benannte pre-merge-Befehle, Abbruch an `lint`, Approval für den neuen

    git init -q -b main "$T/wt"
    git -C "$T/wt" config user.email t@example.invalid
    git -C "$T/wt" config user.name Test
    mkdir -p "$T/wt/.config"
    printf '[pre-merge]\ntest = "echo ran-test"\n' > "$T/wt/.config/wt.toml"
    git -C "$T/wt" add . && git -C "$T/wt" commit -qm seed
    cd "$T/wt" && wt config approvals add
    wt config approvals list --format json

Expected: `"state": "approved"`. Fragt `approvals add` interaktiv, die Bestätigung per
`wt config approvals --help` finden.

    cat > "$T/wt/.config/wt.toml" <<'EOF'
    [pre-merge]
    test = "echo ran-test"
    lint = "sh -c 'echo ran-lint; exit 3'"
    EOF
    git -C "$T/wt" commit -qam "add lint"
    wt config approvals list --format json

Expected: **nicht** `approved` — der neue Befehl verlangt ein neues Approval.

    wt config approvals add
    wt switch --create feat
    echo x > x.txt && git add x.txt && git commit -qm x
    wt merge

Expected: die Ausgabe zeigt `ran-test`, dann `ran-lint`; der Merge bricht ab, Exit ≠ 0;
`git -C "$T/wt" log --oneline main` zeigt weiter zwei Commits.

Finding `task0/0e:` beide Befehle laufen in Dateireihenfolge, `lint` bricht ab, ein
neuer Befehl braucht ein neues Approval.

**Weicht 0e ab** (wt führt nur einen Befehl je Hook aus, bricht an `lint` nicht ab, oder
ein neuer Befehl bleibt ohne Approval-Pflicht): **STOP**, Rückfrage beim Betreiber.
Spec §5.1 und §11 setzen alle drei voraus.

### Aufräumen

    herdr plugin list
    rm -rf /tmp/lean-herdr-task0
    git -C /home/tholo/Scripts/lean-herdr worktree prune

Expected: keine Zeile `lean.probe`. Die wt-Approvals für `/tmp/lean-herdr-task0/wt`
bleiben als Eintrag im Store; per `wt config approvals --help` entfernen, wenn es dafür
einen Befehl gibt.

### Close

@call remember_decision("Hardening plan task 0, measured: snapshot source = the 0a finding (expected lean-herdr @ git+file:///home/tholo/Scripts/lean-herdr@main); herdr reads the manifest live or copied it = 0b; unlink line = 0d; .lean-ctx/lean-herdr/.tmp-* ignores both temp names and not the lock = 0c; wt runs pre-merge test then lint, aborts at lint, a new command needs a new approval = 0e. Replace every expected value that measured differently.")
@phase-end

@phase "task-1"
## Task 1: `GitUnusable` — ein git, das nicht antworten kann, wird benannt

**Files:** `lean_herdr/bus.py`, `lean_herdr/initcmd.py`, `lean_herdr/handlers.py`
(nur Kommentar), `lean_herdr/llm.py` (nur Kommentar), `tests/test_bus_canonical_root.py`,
`tests/test_initcmd.py`, `tests/test_workspace.py`, `tests/test_catalog.py`,
`tests/test_handlers.py` (nur Docstring).

**Interfaces — Produces:**
`class GitUnusable(BusError)` in `lean_herdr/bus.py`.
`canonical_root(cwd=None) -> Path` wirft `GitUnusable("git_unusable: <Ursache>")`
(mit `__cause__`), wenn `subprocess.run` `OSError`, `subprocess.SubprocessError` oder
`UnicodeDecodeError` wirft. Kein Repository bleibt `BusError` (nicht `GitUnusable`).

**Ist-Zustand:** kein `try` um `subprocess.run`. `workspace.main` und `catalog.main`
haben schon eine `BusError`-Stufe, die `str(exc)` ausgibt — sie greift ohne
Codeänderung, sobald `canonical_root` benannt wirft. `initcmd.workspace_init` fängt
`BusError` als `not_a_git_repo` und `OSError` als `init_stopped`; ein hängendes git
fliegt dort ganz durch.

@read lean_herdr/bus.py mode=signatures
@symbol body name=workspace_init

@call tdd(tests/test_bus_canonical_root.py)

Rot heißt hier: `ImportError: cannot import name 'GitUnusable'`.

### Die Tests

In `tests/test_bus_canonical_root.py`, am Ende:

    @pytest.mark.parametrize(
        "cause",
        [
            pytest.param(FileNotFoundError(2, "No such file or directory", "git"), id="git missing"),
            pytest.param(subprocess.TimeoutExpired(cmd=["git"], timeout=5.0), id="git hung"),
            pytest.param(
                UnicodeDecodeError("utf-8", b"\xe9", 0, 1, "invalid start byte"), id="undecodable"
            ),
        ],
    )
    def test_a_git_that_cannot_answer_is_git_unusable(monkeypatch, tmp_path, cause):
        """Three ways git fails to answer at all, and each one used to leave raw.

        Raw, they walked past every `main()`'s BusError rung and came out as
        `workspace_crashed:` or `models_crashed:` -- or, in `init`, next to a
        `not_a_git_repo` that sends the operator to `git init` for a missing binary.
        """
        from lean_herdr.bus import BusError, GitUnusable

        def refuse(*_args, **_kwargs):
            raise cause

        monkeypatch.setattr(subprocess, "run", refuse)
        with pytest.raises(GitUnusable, match="^git_unusable: ") as caught:
            canonical_root(tmp_path)
        assert isinstance(caught.value, BusError)
        assert caught.value.__cause__ is cause


    def test_no_repository_stays_a_plain_bus_error(tmp_path: Path):
        """git answered, and its answer was "no". That is not git being unusable."""
        from lean_herdr.bus import BusError, GitUnusable

        with pytest.raises(BusError) as caught:
            canonical_root(tmp_path)
        assert not isinstance(caught.value, GitUnusable)

In `tests/test_initcmd.py`, direkt nach `test_without_a_git_repo_it_says_so`:

    @pytest.mark.parametrize(
        "cause",
        [
            pytest.param(FileNotFoundError(2, "No such file or directory", "git"), id="git missing"),
            pytest.param(subprocess.TimeoutExpired(cmd=["git"], timeout=5.0), id="git hung"),
        ],
    )
    def test_a_git_that_cannot_answer_stops_init_without_asking_for_git_init(
        monkeypatch, tmp_path, cause
    ):
        """`not_a_git_repo: run git init` is the wrong repair for a missing binary."""
        quiet(monkeypatch)
        monkeypatch.chdir(tmp_path)

        def refuse(*_args, **_kwargs):
            raise cause

        monkeypatch.setattr("lean_herdr.bus.subprocess.run", refuse)
        answer = workspace_init()
        assert answer["ok"] is False
        assert answer["error"].startswith("init_stopped: git_unusable: "), answer["error"]
        assert not (tmp_path / "opencode.jsonc").exists(), "it wrote before checking"

In `tests/test_workspace.py`: `import subprocess` zu den Imports; direkt nach
`test_main_gives_each_failure_its_own_rung`:

    def test_main_names_a_git_that_cannot_answer(monkeypatch, capsys):
        """Through the real `canonical_root`, not a raised stand-in.

        The rung above has always worked for a BusError. A hung git never was one,
        and it ended as `workspace_crashed:`.
        """

        def hang(*_args, **_kwargs):
            raise subprocess.TimeoutExpired(cmd=["git"], timeout=5.0)

        monkeypatch.setattr("lean_herdr.bus.subprocess.run", hang)
        assert workspace.main(["up"]) == 0
        answer = json.loads(capsys.readouterr().out)
        assert answer["ok"] is False
        assert answer["error"].startswith("git_unusable: "), answer["error"]

In `tests/test_catalog.py`, direkt nach
`test_a_root_that_is_no_repository_is_named_not_swallowed`:

    def test_a_git_that_cannot_answer_is_named_too(monkeypatch, capsys):
        """The same rung, reached by a git that is not on the PATH at all."""

        def missing(*_args, **_kwargs):
            raise FileNotFoundError(2, "No such file or directory", "git")

        monkeypatch.setattr("lean_herdr.bus.subprocess.run", missing)
        assert catalog.main(["check"]) == 0
        answer = one_line(capsys)
        assert answer["ok"] is False
        assert answer["error"].startswith("git_unusable: "), answer["error"]

### Der Fix

@call patch("lean_herdr/bus.py", "a new class after BusError, and the subprocess.run call plus docstring of canonical_root")

1. Direkt nach `class BusError`:

        class GitUnusable(BusError):
            """git itself could not answer -- missing, hung, or output that does not decode.

            Not "this is no repository": that stays a plain BusError carrying git's own
            words. The two need different repairs -- `git init` there, a PATH or a disk
            here -- and a caller that cannot tell them apart sends the operator to the
            wrong one. A BusError all the same, so every caller that already names a bus
            failure names this one too instead of crashing on it.
            """

2. Im Docstring von `canonical_root`, als letzter Absatz:

            Raises BusError when git answers that this is no repository, and
            GitUnusable when git could not be asked at all. Every `main()` with a
            BusError rung reports both by name.

3. Der Aufruf `proc = subprocess.run(...)` wird:

            try:
                proc = subprocess.run(
                    ["git", "rev-parse", "--git-common-dir"],
                    cwd=str(cwd) if cwd is not None else None,
                    capture_output=True,
                    text=True,
                    timeout=GIT_TIMEOUT_S,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError, UnicodeDecodeError) as exc:
                # OSError: no git on the PATH. SubprocessError: TimeoutExpired, a git
                # that hung. UnicodeDecodeError: `text=True` decodes strictly, and a
                # non-UTF-8 byte in the path is a ValueError nobody else names.
                raise GitUnusable(f"git_unusable: {exc}") from exc

   Die Klammern bleiben: PEP 758 erlaubt das klammerlose `except A, B` nur ohne `as`.

@call patch("lean_herdr/initcmd.py", "the try/except around canonical_root at the top of workspace_init")

4. Import: `from lean_herdr.bus import BusError, GitUnusable, canonical_root`.
5. Der Block wird:

            try:
                base = root if root is not None else canonical_root()
            except GitUnusable as exc:
                # BEFORE BusError, whose subclass it is: a git that cannot answer read
                # as `not_a_git_repo: run git init` sends the operator to the wrong repair.
                return {"ok": False, "error": f"init_stopped: {exc}"}
            except BusError:
                return {"ok": False, "error": "not_a_git_repo: run `git init` first"}

   Das `except OSError` samt Kommentar entfällt.

@call patch("lean_herdr/handlers.py", "the comment above except (BusError, SettingsError, OSError) in handle_bootstrap")

6. Code bleibt. Der Kommentar wird:

            # `canonical_root()` answers a missing, hung or undecodable git with
            # `GitUnusable`, a BusError, so the first name covers every git failure.
            # `OSError` stays as the belt on this block's own promise: a failure here
            # shows a notification, never only a stderr line in the plugin log through
            # `__main__`'s catch-all.

@call patch("lean_herdr/llm.py", "the comment inside the except clause of file_settings")

7. Code bleibt. Die beiden Kommentarabsätze im `except` werden:

                # BusError covers every way `canonical_root()` fails: no repository,
                # and -- as GitUnusable -- a git that is missing, hung, or answers a
                # path that does not decode. OSError, SubprocessError and ValueError
                # stay as the belt on this function's own promise: it never raises,
                # because a raise here aborts the commit worktrunk is in the middle of,
                # and in `prereview` mode it would end as a traceback with exit 1 --
                # this CLI's word for "the model rejected".

@call patch("tests/test_handlers.py", "the docstring of test_bootstrap_without_git_on_the_path_notifies_like_every_other_failure")

8. Test bleibt. Der Docstring wird:

            """A raw OSError out of this block still ends in a notification.

            `canonical_root()` itself answers a missing git with GitUnusable, a BusError
            (tests/test_bus_canonical_root.py). The `OSError` beside it stays as the
            belt, and this test holds it: without it the failure escapes to
            `__main__`'s catch-all and reaches the operator as a stderr line in the
            plugin log where every other failure path here shows a notification.
            """

Sichtbar ändert sich die Ausgabe auch in `report.main` (`git_unusable: …` statt
`report_crashed:`) und in `handlers._context` — gewollt, kein Test hält das alte
Verhalten fest. `orderlog.state_dir` bleibt unberührt.

Ohne Änderung grün bleiben `test_without_a_git_repo_it_says_so`,
`test_canonical_root_without_a_repo_raises`,
`test_a_root_that_is_no_repository_is_named_not_swallowed` und
`test_an_undecodable_repo_root_costs_the_defaults_not_the_run`.

### Verify & Close

@call verify(lean_herdr/bus.py lean_herdr/initcmd.py lean_herdr/handlers.py lean_herdr/llm.py tests/)
@call review_change()
@call gate(lean_herdr/bus.py lean_herdr/initcmd.py lean_herdr/handlers.py lean_herdr/llm.py tests/test_bus_canonical_root.py tests/test_initcmd.py tests/test_workspace.py tests/test_catalog.py tests/test_handlers.py)
@call commit("lean_herdr/bus.py lean_herdr/initcmd.py lean_herdr/handlers.py lean_herdr/llm.py tests/test_bus_canonical_root.py tests/test_initcmd.py tests/test_workspace.py tests/test_catalog.py tests/test_handlers.py", "fix(bus): name a git that cannot answer, so init, up and models say so instead of crashing")
@phase-end

@phase "task-2"
## Task 2: `OverlayError` — ein kaputtes Overlay kostet nur das Overlay

**Files:** `lean_herdr/settings.py`, `lean_herdr/llm.py`, `tests/test_settings.py`,
`tests/test_llm.py`.

**Interfaces — Produces:**
`class OverlayError(SettingsError)` in `lean_herdr/settings.py`.
`llm_settings_layered(root, data=None) -> LlmSettings` liest **zuerst** `config.toml`
(bzw. `data`), dann das Overlay; ein `SettingsError` aus dem Overlay-Teil wird
`OverlayError("<OVERLAY_PATH>: <Ursache> -- `lean-herdr models apply` rewrites it")`.
`llm.file_settings(root=None, *, cwd=None) -> LlmSettings` wirft weiter nie: bei
`OverlayError` Meldung `…ignoring the overlay: …` auf stderr, dann `[llm]` aus
`config.toml` allein; scheitert auch das, die Defaults wie heute.

**Ist-Zustand:** `file_settings` fängt beide Dateien in einem `try` — ein kaputtes
Overlay kostet auch ein gültiges `[llm].model`/`effort` aus `config.toml`.

@read lean_herdr/settings.py mode=signatures
@read lean_herdr/llm.py mode=signatures

@call tdd(tests/test_settings.py::test_a_broken_overlay_is_an_overlay_error_and_still_a_settings_error)
@call tdd(tests/test_llm.py::test_a_broken_overlay_costs_the_overlay_and_not_config_toml)

Rot heißt hier: erst `ImportError: cannot import name 'OverlayError'`, dann
`LlmSettings() != LlmSettings(model='by/hand', effort='low')`.

### Die Tests

In `tests/test_settings.py`, direkt nach `test_a_broken_overlay_is_loud_here`:

    @pytest.mark.parametrize(
        "text",
        ["[llm]\nmodel = 5\n", '[llm]\nmodel = "unclosed\n'],
        ids=["wrong-type", "malformed-toml"],
    )
    def test_a_broken_overlay_is_an_overlay_error_and_still_a_settings_error(tmp_path, text):
        """Its own class for the one reader that must tell it apart, and a
        SettingsError for every loud path that already catches one."""
        from lean_herdr.settings import (
            OVERLAY_PATH,
            OverlayError,
            SettingsError,
            llm_settings_layered,
        )

        _write_llm_files(tmp_path, config='[llm]\nmodel = "by/hand"\n', overlay=text)
        with pytest.raises(OverlayError, match="lean-herdr models apply") as caught:
            llm_settings_layered(tmp_path)
        assert isinstance(caught.value, SettingsError)
        assert str(OVERLAY_PATH) in str(caught.value)


    def test_a_broken_config_toml_is_not_an_overlay_error(tmp_path):
        """config.toml is read first: a file broken in both places names the operator's."""
        from lean_herdr.settings import OverlayError, SettingsError, llm_settings_layered

        _write_llm_files(tmp_path, config="[llm]\nmodel = 5\n", overlay="[llm]\nmodel = 6\n")
        with pytest.raises(SettingsError) as caught:
            llm_settings_layered(tmp_path)
        assert not isinstance(caught.value, OverlayError)

In `tests/test_llm.py`, direkt nach `test_a_broken_overlay_costs_the_defaults_not_the_commit`:

    def test_a_broken_overlay_costs_the_overlay_and_not_config_toml(tmp_path, capsys):
        """The machine's file is broken, the operator's is not -- the operator's still counts.

        One `try` around both files used to hand back the defaults here, and the
        commit ran on the built-in model although config.toml named another.
        """
        _write_config(tmp_path, '[llm]\nmodel = "by/hand"\neffort = "low"\n')
        (tmp_path / OVERLAY_PATH).write_text("[llm]\nmodel = 5\n", encoding="utf-8")
        assert llm.file_settings(tmp_path) == LlmSettings(model="by/hand", effort="low")
        err = capsys.readouterr().err
        assert "ignoring the overlay" in err, err
        assert str(OVERLAY_PATH) in err, err

Und in `test_a_broken_overlay_costs_the_defaults_not_the_commit` wird die letzte Zeile:

        assert "ignoring the overlay" in capsys.readouterr().err

(ohne `config.toml` bleiben es die Defaults; die Meldung nennt jetzt das Overlay).

### Der Fix

@call patch("lean_herdr/settings.py", "a new class after SettingsError, and the body plus docstring of llm_settings_layered")

1. Direkt nach `class SettingsError`:

        class OverlayError(SettingsError):
            """`models.auto.toml` is unusable -- the file a machine wrote, not the operator.

            A SettingsError, so every loud path that catches one reports this one too.
            Its own class for the one reader that must tell the two apart:
            `llm.file_settings()` drops a broken overlay and keeps config.toml, instead
            of losing both.
            """

2. Im Docstring von `llm_settings_layered`, nach dem Absatz „The overlay gives
   `model` and NOTHING else. …", ein neuer Absatz:

            A broken OVERLAY raises OverlayError, a SettingsError: every loud caller
            reports it as before, and `llm.file_settings()` alone can tell it apart and
            keep config.toml. config.toml is read first, so a file that is broken in
            both places names the operator's own file.

3. Der Rumpf ab `base = Path(root)` bis vor den Kommentar „The overlay went through
   `llm_settings()` WHOLE above" wird:

            base = Path(root)
            above = llm_settings(read_settings(base / SETTINGS_PATH) if data is None else data)
            try:
                below = llm_settings(read_settings(base / OVERLAY_PATH))
            except SettingsError as exc:
                raise OverlayError(
                    f"{OVERLAY_PATH}: {exc} -- `lean-herdr models apply` rewrites it"
                ) from exc

   Kommentar und `return replace(above, model=above.model or below.model)` bleiben.

@call patch("lean_herdr/llm.py", "the settings import, the last docstring paragraph and the try block of file_settings")

4. Der Import aus `lean_herdr.settings` wird:

        from lean_herdr.settings import (
            EFFORTS,
            SETTINGS_PATH,
            LlmSettings,
            OverlayError,
            SettingsError,
            llm_settings,
            llm_settings_layered,
            read_settings,
        )

5. Der letzte Docstring-Absatz von `file_settings` („Two files now, one rule: …") wird:

            Two files, one rule: `models.auto.toml` below, `config.toml` above. A
            broken overlay costs the overlay alone -- config.toml still counts, and
            the reason goes to stderr. A broken config.toml costs the defaults.
            Neither costs the commit.

6. Der `try`-Block (ohne das `except` darunter) wird:

            try:
                base = Path(root) if root is not None else canonical_root(cwd)
                try:
                    return llm_settings_layered(base)
                except OverlayError as exc:
                    # The machine's file is broken, the operator's may not be. Losing
                    # `[llm].model` and `effort` over a file the daily check wrote would
                    # punish the operator for the machine: drop the overlay, keep
                    # config.toml. A broken config.toml raises again below and costs the
                    # defaults, exactly as before.
                    print(f"herdr-llm: ignoring the overlay: {exc}", file=sys.stderr)
                    return llm_settings(read_settings(base / SETTINGS_PATH))

   Das äußere `except (SettingsError, BusError, OSError, subprocess.SubprocessError, ValueError)`
   samt Kommentar und `print(… ignoring the settings file …)` bleibt unverändert.
   Das Präfix `herdr-llm:` wird erst in Task 8 umbenannt.

Ohne Änderung grün bleiben `test_a_broken_overlay_is_loud_here`,
`test_a_broken_settings_file_costs_the_defaults_not_the_commit`,
`test_the_overlay_is_read_under_config_toml`,
`test_a_broken_overlay_is_a_config_error_too` (tests/test_dispatch.py) und
`test_main_reads_config_toml_exactly_once_per_call`.

### Verify & Close

@call verify(lean_herdr/settings.py lean_herdr/llm.py tests/test_settings.py tests/test_llm.py)
@call gate(lean_herdr/settings.py lean_herdr/llm.py tests/test_settings.py tests/test_llm.py)
@call commit("lean_herdr/settings.py lean_herdr/llm.py tests/test_settings.py tests/test_llm.py", "fix(settings): a broken overlay is an error of its own, and the commit path keeps config.toml when only the overlay is broken")
@call remember_decision("settings.OverlayError(SettingsError) exists since task 2 of the hardening plan: llm_settings_layered reads config.toml first and raises OverlayError for a broken models.auto.toml; llm.file_settings catches it and falls back to config.toml alone.")
@phase-end

@phase "task-3"
## Task 3: nur lesen, was gebraucht wird — `up`, `models`, `dispatch`

**Files:** `lean_herdr/workspace.py`, `lean_herdr/catalog.py`, `lean_herdr/dispatch.py`,
`tests/test_workspace.py`, `tests/test_catalog.py`, `tests/test_dispatch.py`.

**Interfaces:** keine neuen. Verhalten:

| Stelle | danach |
|---|---|
| `workspace_up` | `llm_settings(data)` **vor** `start_orchestrator`, immer; liest das Overlay nie |
| `catalog.main` | Efforts aus `llm_settings(data)`; nur `check` liest `llm_settings_layered(root, data)` für `current`, **vor** dem Fetch |
| `dispatch.main` | `llm_settings_layered(root, raw)` nur bei `args.waiting`, sonst `llm_settings(raw)` |

@call recall_context("OverlayError from task 2 of the hardening plan")

**Ist-Zustand:** `workspace_up` liest `llm_settings_layered` **nach** dem Start — ein
kaputtes Overlay verschluckt `pane`/`agent_id` eines laufenden Orchestrators.
`catalog.main` liest es vor jedem Unterbefehl, `apply` kann ein kaputtes Overlay also
nicht heilen. `dispatch.main` liest es für jedes Kommando.

@read lean_herdr/workspace.py mode=signatures
@read lean_herdr/catalog.py mode=signatures
@read lean_herdr/dispatch.py mode=signatures

Gesucht sind darin `catalog.main` und `dispatch.main` (je `def main`).

@call tdd(tests/test_workspace.py::test_a_broken_overlay_does_not_cost_the_started_orchestrator)
@call tdd(tests/test_catalog.py::test_apply_rewrites_a_broken_overlay_instead_of_refusing_it)
@call tdd(tests/test_dispatch.py::test_the_log_commands_do_not_read_the_overlay)

Rot heißt hier: `OverlayError` fliegt aus `workspace_up`; `apply` antwortet
`config_error:`; jedes Log-Kommando antwortet `config_error:` statt `{"ok": true}`.

### Die Tests

In `tests/test_workspace.py`: der Import wird
`from lean_herdr.settings import OVERLAY_PATH, SETTINGS_PATH, SettingsError, WorkspaceSettings`.
Direkt nach `test_a_broken_models_block_is_read_even_with_auto_off`:

    def test_a_broken_overlay_does_not_cost_the_started_orchestrator(monkeypatch, tmp_path):
        """Read after the start, the overlay threw away a running orchestrator's names.

        `up` reads no overlay at all now: it carries `model` alone, and `up` needs the
        two efforts, which live in config.toml.
        """
        _write_config(tmp_path, AUTO_ON)
        (tmp_path / OVERLAY_PATH).write_text("[llm]\nmodel = 5\n", encoding="utf-8")
        herdr, _ = herdr_with(monkeypatch, {})
        monkeypatch.setattr(
            workspace,
            "start_orchestrator",
            lambda **kw: {"ok": True, "pane": "w3:p9", "agent_id": "mcp-42"},
        )
        monkeypatch.setattr(
            "lean_herdr.catalog.check",
            lambda **kw: {"written": True, "model": "cheap/one", "reason": "written"},
        )
        answer = workspace.workspace_up(root=tmp_path, herdr=herdr)
        assert answer["ok"] is True
        assert answer["pane"] == "w3:p9"
        assert answer["agent_id"] == "mcp-42"
        assert answer["models"]["reason"] == "written"


    def test_a_typo_in_llm_stops_up_before_anything_starts(monkeypatch, tmp_path):
        """`[llm]` is validated like `[models]`: always, and ahead of the start."""
        _write_config(tmp_path, CONFIG + '\n[llm]\neffort = "enormous"\n')
        herdr, _ = herdr_with(monkeypatch, {})

        def boom(**kwargs):
            raise AssertionError("a broken [llm] must stop `up` before the start")

        monkeypatch.setattr(workspace, "start_orchestrator", boom)
        with pytest.raises(SettingsError, match="effort"):
            workspace.workspace_up(root=tmp_path, herdr=herdr)

In `tests/test_catalog.py`, direkt nach
`test_main_apply_writes_the_overlay_regardless_of_auto`:

    def _broken_overlay(root: Path) -> Path:
        path = root / OVERLAY_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("[llm]\nmodel = 5\n", encoding="utf-8")
        return path


    def test_apply_rewrites_a_broken_overlay_instead_of_refusing_it(monkeypatch, tmp_path, capsys):
        """`apply` exists to write this file. Refusing to run over it left no way back."""
        no_network(monkeypatch, tmp_path)
        overlay = _broken_overlay(tmp_path)
        assert catalog.main(["apply"]) == 0
        answer = one_line(capsys)
        assert answer["ok"] is True
        assert answer["reason"] == "written"
        assert llm_settings(read_settings(overlay)).model == answer["model"]


    def test_list_does_not_read_the_overlay(monkeypatch, tmp_path, capsys):
        no_network(monkeypatch, tmp_path)
        _broken_overlay(tmp_path)
        assert catalog.main(["list"]) == 0
        assert one_line(capsys)["ok"] is True


    def test_check_stays_loud_about_a_broken_overlay_and_fetches_nothing(
        monkeypatch, tmp_path, capsys
    ):
        """`current` is the one answer that needs the overlay -- and a broken one is named."""
        no_network(monkeypatch, tmp_path)
        _broken_overlay(tmp_path)

        def no_fetch(**_kwargs):
            raise AssertionError("a broken overlay must cost no request")

        monkeypatch.setattr("lean_herdr.catalog.fetch", no_fetch)
        assert catalog.main(["check"]) == 0
        answer = one_line(capsys)
        assert answer["ok"] is False
        assert answer["error"].startswith("config_error:"), answer["error"]
        assert "lean-herdr models apply" in answer["error"], answer["error"]

In `tests/test_dispatch.py`, direkt nach `test_the_overlay_reaches_dispatch_under_config_toml`:

    @pytest.mark.parametrize(
        ("argv", "seam"),
        [
            (["order", "--to", "builder-feat", "--message", "build it"], "create_order"),
            (["answer", "--task-id", "o-1", "--message", "yes"], "answer_order"),
            (["cancel", "--task-id", "o-1", "--message", "no longer"], "cancel_order"),
        ],
        ids=["order", "answer", "cancel"],
    )
    def test_the_log_commands_do_not_read_the_overlay(monkeypatch, tmp_path, capsys, argv, seam):
        """They write into the log and never ask a model, so the overlay has nothing to say.

        Reading it anyway turned a broken machine-written file into a refused order.
        """
        root = tmp_path / "repo"
        _write_config(root, "")
        (root / OVERLAY_PATH).write_text("[llm]\nmodel = 5\n", encoding="utf-8")
        monkeypatch.setattr(f"lean_herdr.dispatch.{seam}", lambda *a, **kw: {"ok": True})
        assert _line(argv, root, monkeypatch, capsys) == {"ok": True}

### Zwei bestehende Tests in `tests/test_dispatch.py` folgen

`test_main_reads_config_toml_exactly_once_per_call`:

- Der Absatz „The overlay is a SECOND file and is expected: …" im Docstring wird:

            The overlay is a SECOND file, and only the wait mode reads it -- the one
            mode whose judge uses the model it names. Both counts are held here.

- Ab `_line([*BUILD_ARGS, "--model", "opus"], root, monkeypatch, capsys)` bis zum
  Ende des Tests:

            _line([*BUILD_ARGS, "--model", "opus"], root, monkeypatch, capsys)

            assert reads.count("config.toml") == 1, reads
            assert reads.count("models.auto.toml") == 0, "the build mode has no use for it"

            reads.clear()
            _line(["builder", "--await", "--task-id", "T1"], root, monkeypatch, capsys)

            assert reads.count("config.toml") == 1, reads
            assert reads.count("models.auto.toml") == 1, "the wait mode reads it for the judge"

`test_a_broken_overlay_is_a_config_error_too`:

- Der erste Docstring-Satz wird: „`models.auto.toml` is read in the wait mode through
  the SAME function as in llm.file_settings() -- and here, unlike there, it has a
  reader."
- Der `main(...)`-Aufruf wird
  `code = main(["builder", "--kind", "claude", "--await", "--task-id", "T1"])`.
- Nach `assert "effort" in result["error"], result["error"]` kommt
  `assert "lean-herdr models apply" in result["error"], result["error"]`.

### Der Fix

@call patch("lean_herdr/workspace.py", "the settings import, the docstring and the body of workspace_up")

1. Im Import aus `lean_herdr.settings` wird `llm_settings_layered` zu `llm_settings`.
2. Der Docstring-Absatz „This one DOES raise, …" wird:

            This one DOES raise, and it is the one place in this module that
            does: an unreadable config leaves through `read_settings`,
            `settings_for`, `models_settings`, `llm_settings` or
            `workspace_settings`, and a root that is no repository through
            `canonical_root`. Every one of them runs BEFORE `start_orchestrator`;
            after the start nothing raises (`check()` never does), so a started
            orchestrator's pane and agent id always reach the caller. `main()`
            turns the raise into `config_error:` -- a config the operator cannot
            read must not be answered with defaults.

            The overlay is not read here at all. It carries `model` alone, and
            `up` needs only the two efforts out of `[llm]`.

3. Direkt nach `models = models_settings(data)`:

            # `[llm]` likewise, and for the same reason -- and BEFORE the start: read
            # after it, a raise would throw away the pane and agent id of an
            # orchestrator that is already running.
            llm_cfg = llm_settings(data)

4. Die Zeile `llm_cfg = llm_settings_layered(base, data)` hinter den beiden
   Funktions-Imports entfällt; `check(...)` bekommt `llm_cfg` von oben.

@call patch("lean_herdr/catalog.py", "the settings import and the reading block at the top of main plus the check branch")

5. Im Import aus `lean_herdr.settings` kommt `llm_settings` dazu.
6. `llm_cfg = llm_settings_layered(root, data)` und der `efforts`-Block samt Kommentar
   werden:

                # `[llm]` of config.toml alone: the efforts are all `list` and `apply`
                # need, and the overlay carries `model` and nothing else. `apply`
                # therefore overwrites a broken overlay -- and heals it -- instead of
                # refusing to run over the very file it exists to write.
                own = llm_settings(data)
                # BOTH resolved levels, because the one key the overlay writes
                # serves both jobs. The fallbacks are llm.py's constants, and they
                # are imported rather than respelled -- a second spelling would
                # drift the day one of them changes (M3).
                efforts = (
                    own.effort or llm.GENERATE_EFFORT,
                    own.prereview_effort or llm.PREREVIEW_EFFORT,
                )

7. Der Zweig `elif args.command == "check":` beginnt mit:

                # `current` is the one answer that needs the overlay, and the one
                # place it stays loud: an OverlayError is a SettingsError. Read
                # BEFORE the fetch, so a broken file costs no request.
                current = llm_settings_layered(root, data).model or llm.DEFAULT_MODEL

   und im Ergebnis-Dict wird `"current": llm_cfg.model or llm.DEFAULT_MODEL` zu
   `"current": current`.

@call patch("lean_herdr/dispatch.py", "the settings import, and the comment block plus llm_cfg line in main")

8. Im Import aus `lean_herdr.settings` kommt `llm_settings` dazu.
9. Der Kommentarblock ab „Validated HERE, in the one consumer …" bis einschließlich
   `llm_cfg = llm_settings_layered(root, raw)` wird:

            # `[llm]` is validated for EVERY command, in the one consumer that has a
            # reader for the complaint: a SettingsError here leaves main() as
            # `config_error: <reason>`. llm.file_settings() swallows the same error
            # -- there it would cost a commit -- so without this a typo in `[llm]`
            # would be silent everywhere.
            #
            # The overlay only where it is USED: the wait mode hands `llm_cfg` to the
            # pre-review judge, and there it takes the SAME layering
            # llm.file_settings() applies, out of the same function -- otherwise the
            # commit generator and the judge would run on different models. The build
            # mode and the log commands never read a model out of `[llm]`, so a broken
            # overlay must not cost them a dispatch. `raw` is handed in either way, so
            # config.toml is still read exactly once
            # (test_main_reads_config_toml_exactly_once_per_call counts both files).
            llm_cfg = llm_settings_layered(root, raw) if args.waiting else llm_settings(raw)

Ohne Änderung grün bleiben `test_up_hands_the_catalogue_both_effort_levels_in_order`,
`test_up_with_auto_off_never_asks_the_catalogue`,
`test_the_effort_fallbacks_come_from_llm_and_are_not_respelled`,
`test_main_check_names_the_winner_and_what_runs_today`,
`test_a_broken_llm_block_is_a_config_error_too` und
`test_the_overlay_reaches_dispatch_under_config_toml`.

### Verify & Close

@call verify(lean_herdr/workspace.py lean_herdr/catalog.py lean_herdr/dispatch.py tests/)
@call review_change()
@call gate(lean_herdr/workspace.py lean_herdr/catalog.py lean_herdr/dispatch.py tests/test_workspace.py tests/test_catalog.py tests/test_dispatch.py)
@call commit("lean_herdr/workspace.py lean_herdr/catalog.py lean_herdr/dispatch.py tests/test_workspace.py tests/test_catalog.py tests/test_dispatch.py", "fix(config): read the overlay only where its model is used, so up, apply and the log commands stop failing on it")
@phase-end

@phase "task-4"
## Task 4: ein Temp-Name pro Overlay-Schreiber, ein Ignore-Urteil je Pfad

**Files:** `lean_herdr/catalog.py`, `lean_herdr/initcmd.py`, `tests/test_catalog.py`,
`tests/test_initcmd.py`.

**Interfaces:**
`write_overlay(model: str, *, root: Path, stamp: str | None = None) -> Path` bleibt in der
Signatur. Neu, **wie** sie schreibt: `tempfile.mkstemp(dir=<Overlay-Verzeichnis>,
prefix=".tmp-models.auto.toml.")`, Schreiben über den Deskriptor, dann `os.replace`.
Bei `OSError` löscht sie nur **ihre** Temp-Datei und wirft weiter.

**Produces** in `lean_herdr/initcmd.py` (Task 7 zieht beides nach `checkcmd`):
`TEMP_IGNORE = ".lean-ctx/lean-herdr/.tmp-*"`,
`TEMP_PROBE = OVERLAY_PATH.parent / ".tmp-models.auto.toml.probe"`,
`_check_temp_ignored(root: Path, runner: Any) -> str | None` — eigener
`git check-ignore -v`-Aufruf, **immer**, nicht hinter `[models].auto`.

@call recall_context("hardening plan task 0c: which ignore line covers the temp names")

Weicht 0c ab (die Zeile `.lean-ctx/lean-herdr/.tmp-*` erfasst die Probe nicht, oder sie
erfasst das Lock), gilt die gemessene Zeile für `TEMP_IGNORE` — und die Abweichung geht
als Finding an den Controller.

**Ist-Zustand:** fester Name `.tmp-models.auto.toml` — zwei Schreiber teilen die Inode
(S2), ein offener Deskriptor schreibt nach dem fremden `replace` in die Live-Datei (S3),
ein scheiternder Schreiber löscht die fremde Temp-Datei (S4). `_check_overlay_ignored`
fragt nur nach dem Overlay; `.gitignore` dieses Repos nennt nur das Overlay.

@read lean_herdr/catalog.py mode=signatures
@read lean_herdr/initcmd.py mode=signatures

@call tdd(tests/test_catalog.py::test_every_writer_takes_a_temp_name_of_its_own)
@call tdd(tests/test_initcmd.py::test_an_ignored_overlay_alone_still_warns_about_the_temp_files)

Rot heißt hier: `AttributeError: <module 'lean_herdr.catalog'> has no attribute 'os'`,
dann `ImportError: cannot import name 'TEMP_IGNORE'`.

### Die Tests

In `tests/test_catalog.py`, direkt nach
`test_a_failed_replace_leaves_the_old_overlay_and_no_temp_file`:

    def test_every_writer_takes_a_temp_name_of_its_own(monkeypatch, tmp_path):
        """Two writers, two temp files -- no shared inode for their bytes to mix in.

        Deterministic, no timing: the swap is refused, so each call stops right where
        a second, concurrent writer would have met the first one's file.
        """
        seen: list[str] = []

        def refuse(src, dst):
            seen.append(Path(src).name)
            raise OSError("stop before the swap")

        monkeypatch.setattr("lean_herdr.catalog.os.replace", refuse)
        for model in ("good/all-clear", "mid/small-context"):
            with pytest.raises(OSError, match="stop before the swap"):
                catalog.write_overlay(model, root=tmp_path)
        assert len(seen) == 2 and seen[0] != seen[1], seen
        assert all(name.startswith(".tmp-models.auto.toml.") for name in seen), seen
        assert list((tmp_path / OVERLAY_PATH).parent.glob(".tmp-*")) == []


    def test_a_failing_writer_removes_its_own_temp_file_and_no_other(monkeypatch, tmp_path):
        """S4: a writer that fails used to delete the temp file a second writer had written."""
        folder = (tmp_path / OVERLAY_PATH).parent
        folder.mkdir(parents=True)
        foreign = folder / ".tmp-models.auto.toml.x"
        foreign.write_text("another writer's half", encoding="utf-8")

        def refuse(src, dst):
            raise OSError("the disk said no")

        monkeypatch.setattr("lean_herdr.catalog.os.replace", refuse)
        with pytest.raises(OSError, match="the disk said no"):
            catalog.write_overlay("good/all-clear", root=tmp_path)
        assert foreign.read_text(encoding="utf-8") == "another writer's half"
        assert sorted(p.name for p in folder.glob(".tmp-*")) == [foreign.name]

`test_a_failed_replace_leaves_the_old_overlay_and_no_temp_file` folgt: die Zeilen

        def refuse(self, target):
            raise OSError("the disk said no")

        monkeypatch.setattr(type(path), "replace", refuse)

werden

        def refuse(src, dst):
            raise OSError("the disk said no")

        monkeypatch.setattr("lean_herdr.catalog.os.replace", refuse)

und im Docstring desselben Tests wird der Absatz „`.gitignore` names `models.auto.toml`
exactly. …" bis „… where `orderlog.append` does not have to." zu:

        A `.tmp-` file left beside the overlay shows up in `git status` wherever
        `.lean-ctx/lean-herdr/.tmp-*` is not ignored -- which is why `write_overlay`
        removes its own, where `orderlog.append` does not have to.

In `tests/test_initcmd.py`: der Import aus `lean_herdr.initcmd` bekommt `TEMP_IGNORE`,
`TEMP_PROBE` und `_check_temp_ignored`. Direkt nach
`test_without_git_there_is_no_verdict_on_the_overlay`:

    def test_the_temp_check_asks_git_about_a_probe_name(monkeypatch, repo):
        """`check-ignore` matches patterns, so the probe needs no file on disk."""
        monkeypatch.setattr("shutil.which", which_stub(True))
        named = FakeProc(replies={("check-ignore",): f".gitignore:23:{TEMP_IGNORE}\t{TEMP_PROBE}"})
        assert _check_temp_ignored(repo, named) is None
        assert named.called_with("check-ignore", "-v", str(TEMP_PROBE))
        silent = FakeProc(replies={("check-ignore",): ""})
        line = _check_temp_ignored(repo, silent)
        assert line is not None and TEMP_IGNORE in line


    def test_an_ignored_overlay_alone_still_warns_about_the_temp_files(monkeypatch, repo):
        """One verdict per path, and the temp one even with `auto` off.

        A single `check-ignore` over both paths answers as soon as ONE is covered --
        and a rule for the overlay alone, this repository's state, would pass for both.
        """
        monkeypatch.setattr("shutil.which", which_stub(True))
        only_the_overlay = FakeProc(
            replies={
                ("check-ignore", "-v", str(OVERLAY_PATH)): (
                    f".gitignore:22:{OVERLAY_PATH}\t{OVERLAY_PATH}"
                )
            },
            default="",
        )
        warnings = workspace_init(root=repo, runner=only_the_overlay)["warnings"]
        assert any(TEMP_IGNORE in w for w in warnings), warnings

`test_the_gitignore_warning_only_appears_when_auto_is_on` folgt, weil die neue
Temp-Warnung auch „does not ignore" sagt: die Zeile
`assert not any("does not ignore" in w for w in off)` wird

        assert not any(str(OVERLAY_PATH) in w for w in off)

### Der Fix

@call patch("lean_herdr/catalog.py", "the imports, the WHOLE-also-means-never-HALF docstring paragraph and the body of write_overlay")

1. Zu den stdlib-Imports kommen `import os` und `import tempfile`.
2. Der Docstring-Absatz „WHOLE also means never HALF: …" wird:

            WHOLE also means never HALF, and never MIXED: the text goes to a temp
            file of this writer's own -- `tempfile.mkstemp` beside the overlay,
            prefix `.tmp-models.auto.toml.` -- and `os.replace` swaps it in. A fixed
            temp name was shared by concurrent writers: their bytes mixed in one
            inode, one writer's open descriptor wrote into the live overlay after
            the other's replace, and one writer's cleanup deleted the other's file
            (measured 2026-09-13: 4 of 400 synchronised pairs left a broken
            overlay). `write_failed` means again that the filesystem said no.

            What remains, and is accepted: two checks at once both fetch, and the
            last complete replace wins (S1). Both results are whole files. No lock,
            no shared helper. `mkstemp` creates the file 0600; the overlay is
            machine-local.

3. Der Rumpf ab `path = Path(root) / OVERLAY_PATH` bis vor `return path` wird:

            path = Path(root) / OVERLAY_PATH
            path.parent.mkdir(parents=True, exist_ok=True)
            # A temp name of this writer's OWN. `mkstemp` raises before anything
            # exists, so its OSError needs no cleanup and stays outside the `try`.
            fd, name = tempfile.mkstemp(dir=path.parent, prefix=f".tmp-{path.name}.")
            tmp = Path(name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(
                        f"# written by `lean-herdr models` on {when}. Do not edit --\n"
                        "# the next run overwrites this file. Your own choice belongs in\n"
                        f"# {SETTINGS_PATH}, which wins over this one.\n"
                        "[llm]\n"
                        f'model = "{model}"\n'
                    )
                os.replace(tmp, path)
            except OSError:
                # Only OUR temp file. Another writer's lives under another name, and
                # removing it would lose that writer's run.
                tmp.unlink(missing_ok=True)
                raise

   Der Text der Datei ist unverändert. `mkdir` bleibt vor allem anderen:
   `test_a_filesystem_that_refuses_is_a_reason_and_not_a_crash` legt eine Datei an die
   Stelle von `.lean-ctx`.

@call patch("lean_herdr/initcmd.py", "two constants and a new check after _check_overlay_ignored, and the checks tuple in _warnings")

4. Direkt nach `_check_overlay_ignored`:

        #: The ignore line the temp files of the whole-file writers under
        #: `.lean-ctx/lean-herdr/` need. Their names change on every run, so no
        #: line naming one of them could ever cover the next.
        TEMP_IGNORE = ".lean-ctx/lean-herdr/.tmp-*"

        #: One name such a writer could draw. `git check-ignore` matches patterns and
        #: needs no file on disk, so this probe stands for every name `mkstemp` picks.
        TEMP_PROBE = OVERLAY_PATH.parent / ".tmp-models.auto.toml.probe"


        def _check_temp_ignored(root: Path, runner: Any) -> str | None:
            """git does not ignore the writers' temp files. Asked always, never behind `auto`.

            Its own call, never one shared with `_check_overlay_ignored`: a single
            `check-ignore` over both paths answers non-empty as soon as ONE of them
            is covered -- and a rule for the overlay alone would then pass for both.
            """
            answer = _read(runner, "git", "check-ignore", "-v", str(TEMP_PROBE), cwd=root)
            if answer is None or answer.strip():
                return None
            return (
                f"git does not ignore {TEMP_IGNORE} -- a writer killed mid-run leaves a "
                "temp file there that would show up in git status. Add to .gitignore: "
                f"{TEMP_IGNORE}"
            )

5. Im Tupel `checks` von `_warnings`, direkt nach der Overlay-Zeile:

                # NOT guarded by `auto`: the template lock is written in every
                # project, and so is its temp file.
                _check_temp_ignored(root, runner),

Ohne Änderung grün bleiben `test_a_second_call_overwrites_the_file_whole`,
`test_the_overlay_is_valid_toml_although_we_have_no_writer`,
`test_a_filesystem_that_refuses_is_a_reason_and_not_a_crash`,
`test_a_healthy_machine_warns_about_nothing` (FakeProc antwortet dort `{}`, also nicht
leer) und `test_the_overlay_check_asks_git_rather_than_reading_gitignore`.

### Verify & Close

@call verify(lean_herdr/catalog.py lean_herdr/initcmd.py tests/test_catalog.py tests/test_initcmd.py)
@call gate(lean_herdr/catalog.py lean_herdr/initcmd.py tests/test_catalog.py tests/test_initcmd.py)
@call commit("lean_herdr/catalog.py lean_herdr/initcmd.py tests/test_catalog.py tests/test_initcmd.py", "fix(catalog): give every overlay writer a temp name of its own, and judge the temp files' ignore rule on its own")
@phase-end

@phase "task-5"
## Task 5: `templating.py` — zwei Token, gerenderte Templates, gerenderte Kopien

**Files:** Create `lean_herdr/templating.py`, `tests/test_templating.py`.
Modify `lean_herdr/initcmd.py`, `lean_herdr/templates/wt.toml`,
`lean_herdr/templates/settings.json`, `lean_herdr/templates/opencode.jsonc`,
`.config/wt.toml`, `.claude/settings.json`, `opencode.jsonc`, `tests/doubles.py`,
`tests/test_templates.py`, `tests/test_worker_permissions.py`,
`tests/test_config_files.py`, `tests/test_initcmd.py`, `tests/test_manifest.py`.

**Interfaces — Produces** (`lean_herdr/templating.py`):
`TEMPLATES: Path`, `LAYOUT: dict[str, str]` (zieht aus `initcmd` um, Inhalt gleich),
`DEFAULT_VALUES = {"lint": "uv run ruff check", "test": "uv run pytest"}`,
`VALUE_RE: re.Pattern[str]`,
`render(name: str, values: Mapping[str, str]) -> bytes` — ersetzt
`{{lean-herdr:test}}`/`{{lean-herdr:lint}}`; `ValueError` für einen Wert, den `VALUE_RE`
ablehnt, und für ein übrig gebliebenes `{{lean-herdr:`.
`initcmd._place(root: Path, relative: str, data: bytes, *, force: bool) -> bool` nimmt die
gerenderten Bytes statt eines Quellpfads; `workspace_init` rendert mit `DEFAULT_VALUES`
(Flags und Lock kommen in Task 6).

@call recall_context("hardening plan task 0e: wt runs two named pre-merge commands")

Weicht 0e ab: **STOP** vor diesem Task, Rückfrage beim Betreiber.

@read lean_herdr/initcmd.py mode=signatures

### Der Test zuerst

@call tdd(tests/test_templating.py)

Rot heißt hier: `ModuleNotFoundError: No module named 'lean_herdr.templating'`.

`tests/test_templating.py`:

    """`render` and the two tokens: what `workspace init` writes into a stranger's project."""

    import json
    import tomllib

    import pytest

    from lean_herdr import templating
    from lean_herdr.settings import load_jsonc
    from lean_herdr.templating import DEFAULT_VALUES, LAYOUT, VALUE_RE, render

    #: Another project's commands. Every assertion that holds for the defaults must
    #: hold for these too, or a render shifted a line.
    FOREIGN = {"test": "cargo test", "lint": "cargo clippy"}


    @pytest.mark.parametrize("values", [DEFAULT_VALUES, FOREIGN], ids=["default", "foreign"])
    @pytest.mark.parametrize("name", sorted(LAYOUT))
    def test_no_token_survives_rendering(name, values):
        assert b"{{lean-herdr:" not in render(name, values)


    def test_the_default_values_pass_their_own_pattern():
        assert all(VALUE_RE.match(value) for value in DEFAULT_VALUES.values())


    @pytest.mark.parametrize(
        "value",
        [
            'uv run "pytest"',
            "pytest*",
            "a:b",
            "$HOME/run",
            "make\ntest",
            "make test ",
            "a;b",
            "a && b",
            "a|b",
            "a\\b",
            "",
        ],
        ids=[
            "quote",
            "star",
            "colon",
            "dollar",
            "newline",
            "trailing-space",
            "semicolon",
            "ampersand",
            "pipe",
            "backslash",
            "empty",
        ],
    )
    def test_a_value_that_would_break_out_of_its_file_is_refused(value):
        """The value lands in TOML, JSON and JSONC nobody escapes -- and in a shell."""
        assert VALUE_RE.match(value) is None
        with pytest.raises(ValueError, match="not a command"):
            render("wt.toml", {**DEFAULT_VALUES, "test": value})


    def test_a_leftover_token_is_a_broken_package(monkeypatch, tmp_path):
        """A misspelt token must not ship into a project as literal braces."""
        (tmp_path / "wt.toml").write_text('test = "{{lean-herdr:tset}}"\n', encoding="utf-8")
        monkeypatch.setattr(templating, "TEMPLATES", tmp_path)
        with pytest.raises(ValueError, match="left after rendering"):
            render("wt.toml", DEFAULT_VALUES)


    def test_the_gate_and_the_permissions_carry_the_same_two_commands(tmp_path):
        """One string, three files: the gate runs it, both builders may run it first."""
        gate = tomllib.loads(render("wt.toml", FOREIGN).decode("utf-8"))["pre-merge"]
        assert gate == {"test": "cargo test", "lint": "cargo clippy"}
        allow = json.loads(render("settings.json", FOREIGN))["permissions"]["allow"]
        assert "Bash(cargo test:*)" in allow
        assert "Bash(cargo clippy:*)" in allow
        jsonc = tmp_path / "opencode.jsonc"
        jsonc.write_bytes(render("opencode.jsonc", FOREIGN))
        bash = load_jsonc(jsonc).data["agent"]["builder"]["permission"]["bash"]
        assert bash["cargo test*"] == "allow"
        assert bash["cargo clippy*"] == "allow"


    def test_the_list_schema_wt_ignores_is_gone():
        """wt 0.77 reports `list.json-schema` in a project config as ignored, everywhere."""
        assert "list" not in tomllib.loads(render("wt.toml", DEFAULT_VALUES).decode("utf-8"))

### Das Modul

`lean_herdr/templating.py`:

    """The templates `workspace init` writes, rendered with this project's two commands.

    Two tokens and nothing else: `{{lean-herdr:test}}` and `{{lean-herdr:lint}}`.
    Each value is a WHOLE command. The pre-merge gate in `.config/wt.toml` runs it,
    and the same string is the prefix of the builder's permission in
    `opencode.jsonc` and `.claude/settings.json` -- the builder may run exactly
    what the gate measures the merge against, with arguments behind it.

    No template engine and no escaping. The values land in JSON, JSONC and TOML
    that are filled by hand, so `VALUE_RE` keeps out every character that would
    need escaping there or mean something to a shell: a quote, a backslash, `*`,
    `:`, `$`, a newline, `;`, `&`, `|`. How far a prefix opens the gate is the
    operator's call.
    """

    from __future__ import annotations

    import re
    from collections.abc import Mapping
    from pathlib import Path

    TEMPLATES = Path(__file__).resolve().parent / "templates"

Danach `LAYOUT` **samt seinem ganzen `#:`-Kommentar** wörtlich aus `initcmd.py`, mit einer
Änderung im Kommentar: „to hold each template byte-identical against this repo's own
copy" wird „to hold each rendered template byte-identical against this repo's own
copy". Dann:

    #: What `init` renders when neither a flag nor the lock names a value. `ruff
    #: check` without a path checks `.`, and this repository is green under both.
    DEFAULT_VALUES = {"lint": "uv run ruff check", "test": "uv run pytest"}

    #: A value: a letter or digit, then letters, digits, space and `._/=+,@-`, and no
    #: space at the end. The pattern of `catalog.SLUG_RE`, for the same reason -- the
    #: string goes into files assembled by hand.
    VALUE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._/=+,@-]*(?<! )\Z")

    _TOKEN = re.compile(r"\{\{lean-herdr:(test|lint)\}\}")
    _LEFTOVER = "{{lean-herdr:"


    def render(name: str, values: Mapping[str, str]) -> bytes:
        """The template `name` with both tokens replaced -- the bytes `init` writes.

        Raises ValueError for a value `VALUE_RE` refuses, and for a token left over
        after rendering: a misspelt token in a shipped template is a broken package,
        and tests/test_templating.py holds every template to it. Bytes in, bytes out:
        no newline translation touches a template on the way.
        """
        for key in DEFAULT_VALUES:
            value = values.get(key, "")
            if not VALUE_RE.match(value):
                raise ValueError(f"{key}: {value!r} is not a command init writes into a config file")
        source = (TEMPLATES / name).read_bytes().decode("utf-8")
        text = _TOKEN.sub(lambda hit: values[hit.group(1)], source)
        if _LEFTOVER in text:
            raise ValueError(f"{name}: a `{_LEFTOVER}...}}}}` token is left after rendering")
        return text.encode("utf-8")

### Die Templates

@call patch("lean_herdr/templates/wt.toml", "the header comment, the [pre-merge] table and the [list] table with its W2 comment")

1. Alles vom Dateianfang bis vor den Kommentar „# Appended to worktrunk's own commit
   prompt" wird:

        # worktrunk project hooks. Project hooks need an approval on their first run:
        # `wt config approvals`.
        #
        # pre-merge is the gate: worktrunk runs it after the rebase and BEFORE the
        # merge, and a failure aborts the merge. That gives one check which does not
        # hang on a model's judgement. Both commands are rendered by `lean-herdr
        # workspace init --test/--lint`, and the builder's permissions carry the same
        # two strings -- a changed command needs `wt config approvals add` again.

        [pre-merge]
        test = "{{lean-herdr:test}}"
        lint = "{{lean-herdr:lint}}"

   Der `[commit.generation]`-Block bleibt unverändert.

@call patch("lean_herdr/templates/settings.json", "the Bash(uv run pytest:*) line")

2. `"Bash(uv run pytest:*)",` wird zu zwei Zeilen:

              "Bash({{lean-herdr:test}}:*)",
              "Bash({{lean-herdr:lint}}:*)",

@call patch("lean_herdr/templates/opencode.jsonc", "the uv run pytest* and uv run ruff* lines in the builder's bash block")

3. Die beiden Zeilen werden:

                  // The pre-merge gate's own two commands, rendered by `workspace init`:
                  // the builder may run exactly what the merge is measured against.
                  "{{lean-herdr:test}}*": "allow",
                  "{{lean-herdr:lint}}*": "allow",

   Mit dem Default wird `uv run ruff*` damit zu `uv run ruff check*` — `ruff format`
   fällt aus der Freigabe, das Gate prüft kein Format.

### `initcmd` rendert

@call patch("lean_herdr/initcmd.py", "TEMPLATES and LAYOUT with its comment, the import block, _place and the _place call in workspace_init")

4. `TEMPLATES = …` und `LAYOUT` samt Kommentar entfallen. Neuer Import:
   `from lean_herdr.templating import DEFAULT_VALUES, LAYOUT, render`.
5. `_place` wird `def _place(root: Path, relative: str, data: bytes, *, force: bool) -> bool:`;
   die erste Docstring-Zeile „Write one rendered template. True when it landed, False
   when it was skipped."; `target.write_bytes(source.read_bytes())` wird
   `target.write_bytes(data)`. Die Symlink-Regeln bleiben wörtlich.
6. In `workspace_init`:
   `landed = _place(base, relative, render(name, DEFAULT_VALUES), force=force)`.

### Die Kopien in diesem Repo

    uv run python - <<'EOF'
    from pathlib import Path

    from lean_herdr.templating import DEFAULT_VALUES, LAYOUT, render

    for name, relative in LAYOUT.items():
        Path(relative).write_bytes(render(name, DEFAULT_VALUES))
    EOF
    git status --short

Expected: unter den Kopien genau `.claude/settings.json`, `.config/wt.toml` und
`opencode.jsonc` geändert; die übrigen fünf unverändert. Dieses Repo verliert `-q` im
Gate und bekommt `lint` als zweiten Gate-Befehl.

### Die Tests, die folgen

`tests/doubles.py`: `from lean_herdr.initcmd import TEMPLATES` wird
`from lean_herdr.templating import DEFAULT_VALUES, render`; in `write_opencode_config`
wird `path.write_bytes((TEMPLATES / "opencode.jsonc").read_bytes())` zu
`path.write_bytes(render("opencode.jsonc", DEFAULT_VALUES))`, und im Docstring
„The TEMPLATE is copied rather than a minimal literal written on purpose" zu „The
TEMPLATE is rendered, as `init` renders it, rather than a minimal literal written on
purpose".

`tests/test_templates.py` wird ganz:

    """The template in the wheel is the source; this repo's copy is a rendering of it.

    `lean-herdr workspace init` renders lean_herdr/templates/ and writes the result.
    This repo uses itself, so every file init would write also exists here as a
    checked-in copy at the place init would put it. Two spellings of one text is
    exactly the drift this test exists to prevent: without it,
    test_role_prohibitions.py would guard the copy while `init` shipped the other
    version into every new project -- and the test that watches the prohibitions
    would watch the wrong file.
    """

    from pathlib import Path

    import pytest

    from lean_herdr.templating import DEFAULT_VALUES, LAYOUT, TEMPLATES, render

    ROOT = Path(__file__).resolve().parents[1]


    @pytest.mark.parametrize(("template", "copy"), sorted(LAYOUT.items()))
    def test_the_rendered_template_and_the_checked_in_copy_are_byte_identical(template, copy):
        assert render(template, DEFAULT_VALUES) == (ROOT / copy).read_bytes(), (
            f"{template} and {copy} have drifted apart"
        )


    def test_no_template_without_a_pair_and_no_pair_without_a_template():
        """Both directions: a stray file ships to strangers unannounced."""
        on_disk = {p.relative_to(TEMPLATES).as_posix() for p in TEMPLATES.rglob("*") if p.is_file()}
        assert on_disk == set(LAYOUT), f"unpaired: {sorted(on_disk ^ set(LAYOUT))}"

`tests/test_worker_permissions.py`:

- Import dazu: `from lean_herdr.templating import LAYOUT, render`.
- Nach `WORKERS = …`:

        #: Another project's gate. The permission files are rendered with these too, so
        #: a render that shifted a line fails here even where this repo's copy passes.
        FOREIGN = {"test": "cargo test", "lint": "cargo clippy"}

- In `BUILDER_TOOLING` wird `"uv run ruff*"` zu `"uv run ruff check*"`.
- `def opencode() -> dict:` wird `def opencode(root: Path = ROOT) -> dict:` und liest
  `root / "opencode.jsonc"` (auch in der `found`-Meldung `root`);
  `def claude_allow() -> list[str]:` wird `def claude_allow(root: Path = ROOT) -> list[str]:`
  und liest `root / ".claude" / "settings.json"`.
- Direkt vor `@pytest.mark.parametrize("role", WORKERS)` des ersten Tests:

        @pytest.fixture(scope="module")
        def foreign_root(tmp_path_factory) -> Path:
            """opencode.jsonc and .claude/settings.json, rendered with FOREIGN."""
            root = tmp_path_factory.mktemp("foreign")
            for name in ("opencode.jsonc", "settings.json"):
                target = root / LAYOUT[name]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(render(name, FOREIGN))
            return root


        @pytest.fixture(params=["repo", "foreign"])
        def gate_root(request, foreign_root) -> Path:
            return ROOT if request.param == "repo" else foreign_root

- Diese fünf Tests bekommen den Parameter `gate_root` und rufen `opencode(gate_root)`
  bzw. `claude_allow(gate_root)`: `test_the_permission_is_never_a_bare_wildcard`,
  `test_no_worker_gate_ever_names_the_dispatch_verb`,
  `test_the_builders_gate_is_not_a_blank_cheque`,
  `test_the_claude_builders_gate_is_not_a_blank_cheque`,
  `test_no_permission_file_hands_out_worktrunk_wholesale`.
- Der `#:`-Kommentar über `CLAUDE_BUILDER_TOOLING` und die Konstante werden:

        #: The Claude harness spells the same grant differently, so the two files
        #: cannot share one list. `git add` and `wt step commit` are the ones
        #: `.lean-ctx/lean-herdr/roles/builder.md` makes mandatory -- `wt step commit
        #: --stage none` commits the INDEX, so without `git add` the commit is empty.
        #: The test and the lint command are the pre-merge gate's own: the gate checks
        #: lint since the operator decision of 2026-09-13, so every builder must be
        #: able to run it first.
        #:
        #: The two harnesses are still NOT at parity: opencode also grants the builder
        #: `git commit*`, `git diff*` and `git status*`, which the Claude side does not
        #: (operator decision, 2026-09-03). Nothing in
        #: `.lean-ctx/lean-herdr/roles/builder.md` makes those mandatory -- `wt step
        #: commit` replaces `git commit`, and the rest are conveniences -- so the
        #: narrower gate stands.
        CLAUDE_BUILDER_TOOLING = (
            "Bash(git add:*)",
            "Bash(uv run pytest:*)",
            "Bash(uv run ruff check:*)",
            "Bash(wt step commit:*)",
        )

`tests/test_config_files.py`: `test_wt_toml_has_the_pre_merge_gate_and_a_fixed_schema`
wird ganz:

    def test_wt_toml_has_the_pre_merge_gate_with_test_and_lint():
        cfg = tomllib.loads((ROOT / ".config" / "wt.toml").read_text(encoding="utf-8"))
        assert cfg["pre-merge"]["test"].startswith("uv run pytest")
        assert cfg["pre-merge"]["lint"].startswith("uv run ruff check")
        assert "list" not in cfg, "wt ignores list.json-schema in a project config"

`tests/test_manifest.py`: `from lean_herdr.initcmd import LAYOUT` wird
`from lean_herdr.templating import LAYOUT`.

`tests/test_initcmd.py`: `LAYOUT` kommt aus `lean_herdr.templating` (zusammen mit
`DEFAULT_VALUES`), `import tomllib` dazu; direkt nach `test_a_second_run_writes_nothing`:

    def test_init_writes_the_templates_rendered_and_no_token(monkeypatch, repo):
        """A stranger's project gets commands, never `{{lean-herdr:...}}` braces."""
        quiet(monkeypatch)
        workspace_init(root=repo)
        for relative in LAYOUT.values():
            assert b"{{lean-herdr:" not in (repo / relative).read_bytes(), relative
        gate = tomllib.loads((repo / ".config" / "wt.toml").read_text(encoding="utf-8"))
        assert gate["pre-merge"] == DEFAULT_VALUES

Ohne Änderung grün bleiben `test_force_overwrites_it`,
`test_a_dangling_symlink_is_not_written_through`,
`test_force_does_not_write_through_a_symlinked_parent_either` und
`test_the_repo_ships_the_claude_permissions_too`.

### Verify & Close

@call verify(lean_herdr/ tests/ .config/wt.toml .claude/settings.json opencode.jsonc)
@call review_change()
@call gate(lean_herdr/templating.py lean_herdr/initcmd.py tests/)
@call commit("lean_herdr/templating.py lean_herdr/initcmd.py lean_herdr/templates/wt.toml lean_herdr/templates/settings.json lean_herdr/templates/opencode.jsonc .config/wt.toml .claude/settings.json opencode.jsonc tests/doubles.py tests/test_templating.py tests/test_templates.py tests/test_worker_permissions.py tests/test_config_files.py tests/test_initcmd.py tests/test_manifest.py", "feat(init): render the gate's test and lint commands into the templates, and drop the list schema wt ignores")
@call remember_decision("lean_herdr/templating.py exists since task 5 of the hardening plan: TEMPLATES, LAYOUT, DEFAULT_VALUES {test: uv run pytest, lint: uv run ruff check}, VALUE_RE, render(name, values) -> bytes. initcmd._place takes rendered bytes. This repo's opencode.jsonc, .claude/settings.json and .config/wt.toml are renderings with DEFAULT_VALUES.")
@phase-end

@phase "task-6"
## Task 6: Lock, Zustände, `init --test/--lint/--update`; das Lock dieses Repos

**Files:** `lean_herdr/templating.py`, `lean_herdr/initcmd.py`, `lean_herdr/workspace.py`,
`tests/test_templating.py`, `tests/test_initcmd.py`, `tests/test_templates.py`,
`tests/test_workspace.py`; neu und versioniert `.lean-ctx/lean-herdr/templates.lock.json`.

**Interfaces — Produces** (`lean_herdr/templating.py`):

- `LOCK_PATH = Path(".lean-ctx") / "lean-herdr" / "templates.lock.json"`
- `class LockError(ValueError)` — Meldung beginnt mit dem Pfad
- `digest(data: bytes) -> str` — sha256, hex
- `resolve_values(locked: Mapping[str, str], *, test: str | None = None, lint: str | None = None) -> dict[str, str]` — Flag > Lock > Default
- `read_lock(root: Path) -> dict[str, dict[str, str]]` — `{"values": {…}, "files": {…}}`; fehlt die Datei: beide leer; kaputt: `LockError`
- `write_lock(root: Path, *, values: Mapping[str, str], files: Mapping[str, str]) -> Path`
- `file_state(root: Path, relative: str, *, rendered: bytes, locked: str | None) -> str` — einer von `blocked missing current unknown outdated edited diverged`
- `state_warnings(templates: Mapping[str, str]) -> list[str]` — eine Zeile je Zustand außer `current`/`edited`

**Produces** (`lean_herdr/initcmd.py`):
`workspace_init(*, root=None, force=False, update=False, test=None, lint=None, runner=subprocess.run) -> dict[str, Any]`
— Ergebnis-Schlüssel `ok root written skipped values templates warmed warnings`;
Fehler `usage_error: --force and --update exclude each other`,
`usage_error: --test '<v>' …`, `lock_malformed: <LockError> -- fix or delete it`.

**Produces** (`lean_herdr/workspace.py`): `--update`, `--test`, `--lint` im Parser;
`up` lehnt jedes Init-Flag ab: `usage_error: up does not take <flags>`.

@call recall_context("templating.py from task 5 of the hardening plan")

@read lean_herdr/templating.py mode=full
@symbol body name=workspace_init
@read lean_herdr/workspace.py mode=signatures

### Zustände (Spec §5.3), in dieser Reihenfolge geprüft

D = sha256 der Datei, L = Lock-Eintrag, P = sha256 des gerenderten Templates.

| Zustand | Bedingung |
|---|---|
| `blocked` | ein Elternteil unter `root` oder das Ziel selbst ist ein Symlink |
| `missing` | Datei fehlt |
| `current` | D = P |
| `unknown` | kein L |
| `outdated` | D = L ≠ P |
| `edited` | D ≠ L = P |
| `diverged` | D ≠ L, L ≠ P |

| Modus | schreibt | Lock-Eintrag |
|---|---|---|
| ohne Flag | `missing` | geschriebene und `current` auf D — auch einen vorhandenen, veralteten |
| `--update` | `missing`, `outdated` | wie oben |
| `--force` | alles außer unter Symlink-Elternteil | alle geschriebenen |

Einträge für Dateien, die der Lauf nicht schreibt und nicht `current` findet, bleiben
**unverändert** — sonst würde `outdated` beim nächsten Lauf `unknown`.

@call tdd(tests/test_templating.py::test_every_state_from_prepared_files)
@call tdd(tests/test_initcmd.py::test_a_changed_value_leaves_an_untouched_file_outdated_until_update)

Rot heißt hier: `ImportError: cannot import name 'file_state'`, dann
`TypeError: workspace_init() got an unexpected keyword argument 'test'`.

### Die Tests in `tests/test_templating.py`

Imports werden:

    import json
    import re
    import tomllib

    import pytest

    from lean_herdr import templating
    from lean_herdr.settings import load_jsonc
    from lean_herdr.templating import (
        DEFAULT_VALUES,
        LAYOUT,
        LOCK_PATH,
        VALUE_RE,
        LockError,
        digest,
        file_state,
        read_lock,
        render,
        resolve_values,
        state_warnings,
        write_lock,
    )

Am Ende der Datei:

    TARGET = ".config/wt.toml"
    RENDERED = b"what init would write\n"
    WRITTEN_BEFORE = b"what init wrote last time\n"


    def _put(root, data: bytes) -> None:
        path = root / TARGET
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


    @pytest.mark.parametrize(
        ("on_disk", "locked", "expected"),
        [
            (None, None, "missing"),
            (RENDERED, None, "current"),
            (RENDERED, digest(WRITTEN_BEFORE), "current"),
            (b"a stranger's file\n", None, "unknown"),
            (WRITTEN_BEFORE, digest(WRITTEN_BEFORE), "outdated"),
            (b"a hand edit\n", digest(RENDERED), "edited"),
            (b"a hand edit\n", digest(WRITTEN_BEFORE), "diverged"),
        ],
        ids=["missing", "current", "current-over-a-stale-entry", "unknown", "outdated", "edited", "diverged"],
    )
    def test_every_state_from_prepared_files(tmp_path, on_disk, locked, expected):
        if on_disk is not None:
            _put(tmp_path, on_disk)
        assert file_state(tmp_path, TARGET, rendered=RENDERED, locked=locked) == expected


    def test_a_symlinked_parent_or_target_is_blocked(tmp_path):
        """The two rules of `_place`: never through a linked parent, never through a link."""
        outside = tmp_path / "outside"
        outside.mkdir()
        root = tmp_path / "repo"
        root.mkdir()
        (root / ".config").symlink_to(outside, target_is_directory=True)
        assert file_state(root, TARGET, rendered=RENDERED, locked=None) == "blocked"
        (root / ".config").unlink()
        (root / ".config").mkdir()
        (root / TARGET).symlink_to(outside / "wt.toml")
        assert file_state(root, TARGET, rendered=RENDERED, locked=None) == "blocked"


    def test_a_missing_lock_is_no_values_and_no_entries(tmp_path):
        assert read_lock(tmp_path) == {"values": {}, "files": {}}


    def test_the_lock_reads_back_what_was_written_and_diffs_line_by_line(tmp_path):
        files = {".config/wt.toml": digest(b"x"), "opencode.jsonc": digest(b"y")}
        path = write_lock(tmp_path, values=DEFAULT_VALUES, files=files)
        assert path == tmp_path / LOCK_PATH
        assert read_lock(tmp_path) == {"values": DEFAULT_VALUES, "files": files}
        expected = json.dumps({"files": files, "values": DEFAULT_VALUES}, indent=2, sort_keys=True)
        assert path.read_text(encoding="utf-8") == expected + "\n"
        assert list(path.parent.glob(".tmp-*")) == []


    @pytest.mark.parametrize(
        "text",
        [
            "not json",
            "[]",
            '{"values": {}}',
            '{"values": {"test": "rm \\"x\\""}, "files": {}}',
            '{"values": {"format": "ruff format"}, "files": {}}',
            '{"values": {}, "files": {"elsewhere.txt": "' + "0" * 64 + '"}}',
            '{"values": {}, "files": {"opencode.jsonc": "not-a-digest"}}',
        ],
        ids=[
            "no-json",
            "not-an-object",
            "no-files",
            "bad-value",
            "unknown-value-key",
            "key-outside-layout",
            "bad-digest",
        ],
    )
    def test_a_broken_lock_is_a_lock_error_naming_its_path(tmp_path, text):
        """No state is guessed from a record nobody can read."""
        path = tmp_path / LOCK_PATH
        path.parent.mkdir(parents=True)
        path.write_text(text, encoding="utf-8")
        with pytest.raises(LockError, match=re.escape(str(path))):
            read_lock(tmp_path)


    def test_a_flag_beats_the_lock_and_the_lock_beats_the_default():
        locked = {"test": "cargo test"}
        assert resolve_values(locked) == {"test": "cargo test", "lint": "uv run ruff check"}
        assert resolve_values(locked, test="make test", lint="make lint") == {
            "test": "make test",
            "lint": "make lint",
        }


    def test_every_state_but_current_and_edited_names_a_next_step():
        """A hand edit is intent, and `current` has nothing to do."""
        states = {
            f"file-{state}": state
            for state in ("missing", "current", "unknown", "outdated", "edited", "diverged", "blocked")
        }
        lines = state_warnings(states)
        assert [line.split(" is ")[0] for line in lines] == [
            "file-blocked",
            "file-diverged",
            "file-missing",
            "file-outdated",
            "file-unknown",
        ]
        assert all("init --update" in line for line in lines if " is outdated" in line)

### Die Tests in `tests/test_initcmd.py`

Imports dazu: `import json`; aus `lean_herdr.templating` zusätzlich `LOCK_PATH` und
`digest`. Am Ende der Datei:

    def _lock(repo) -> dict:
        return json.loads((repo / LOCK_PATH).read_text(encoding="utf-8"))


    def test_init_locks_every_file_it_wrote(monkeypatch, repo):
        quiet(monkeypatch)
        answer = workspace_init(root=repo)
        assert answer["values"] == DEFAULT_VALUES
        assert answer["templates"] == {relative: "current" for relative in LAYOUT.values()}
        lock = _lock(repo)
        assert lock["values"] == DEFAULT_VALUES
        assert lock["files"] == {
            relative: digest((repo / relative).read_bytes()) for relative in LAYOUT.values()
        }


    def test_a_value_given_once_is_kept_by_the_lock(monkeypatch, repo):
        quiet(monkeypatch)
        workspace_init(root=repo, test="cargo test", lint="cargo clippy")
        answer = workspace_init(root=repo)
        assert answer["values"] == {"test": "cargo test", "lint": "cargo clippy"}
        assert answer["written"] == []


    def test_init_without_a_flag_locks_a_current_file_it_did_not_write(monkeypatch, repo):
        """Older projects get their lock without a single file overwritten."""
        quiet(monkeypatch)
        workspace_init(root=repo)
        (repo / LOCK_PATH).unlink()
        answer = workspace_init(root=repo)
        assert answer["written"] == []
        assert set(_lock(repo)["files"]) == set(LAYOUT.values())


    def test_a_changed_value_leaves_an_untouched_file_outdated_until_update(monkeypatch, repo):
        """Without --update nothing is overwritten -- and the entry stays, or the next
        --update could no longer tell the untouched file from an edited one."""
        quiet(monkeypatch)
        workspace_init(root=repo)
        before = _lock(repo)["files"][".config/wt.toml"]
        answer = workspace_init(root=repo, test="cargo test")
        assert answer["templates"][".config/wt.toml"] == "outdated"
        assert ".config/wt.toml" in answer["skipped"]
        assert _lock(repo)["files"][".config/wt.toml"] == before
        assert any(w.startswith(".config/wt.toml is outdated") for w in answer["warnings"])

        updated = workspace_init(root=repo, update=True)
        assert ".config/wt.toml" in updated["written"]
        assert updated["templates"][".config/wt.toml"] == "current"
        gate = tomllib.loads((repo / ".config" / "wt.toml").read_text(encoding="utf-8"))
        assert gate["pre-merge"]["test"] == "cargo test"


    def test_update_leaves_a_hand_edit_and_says_why(monkeypatch, repo):
        quiet(monkeypatch)
        workspace_init(root=repo)
        settings = repo / ".claude" / "settings.json"
        settings.write_text(
            settings.read_text(encoding="utf-8").replace("git add", "git add -p"), encoding="utf-8"
        )
        entry = _lock(repo)["files"][".claude/settings.json"]
        answer = workspace_init(root=repo, update=True, test="cargo test")
        assert ".claude/settings.json" in answer["skipped"]
        assert answer["templates"][".claude/settings.json"] == "diverged"
        assert "git add -p" in settings.read_text(encoding="utf-8")
        assert _lock(repo)["files"][".claude/settings.json"] == entry
        assert any(w.startswith(".claude/settings.json is diverged") for w in answer["warnings"])


    def test_an_edit_on_its_own_is_intent_and_no_warning(monkeypatch, repo):
        quiet(monkeypatch)
        workspace_init(root=repo)
        (repo / "opencode.jsonc").write_text("{}", encoding="utf-8")
        answer = workspace_init(root=repo, update=True)
        assert answer["templates"]["opencode.jsonc"] == "edited"
        assert "opencode.jsonc" in answer["skipped"]
        assert not any(w.startswith("opencode.jsonc") for w in answer["warnings"])


    def test_force_writes_everything_and_locks_it(monkeypatch, repo):
        quiet(monkeypatch)
        workspace_init(root=repo)
        (repo / "opencode.jsonc").write_text("{}", encoding="utf-8")
        answer = workspace_init(root=repo, force=True, lint="cargo clippy")
        assert answer["written"] == sorted(LAYOUT.values())
        lock = _lock(repo)
        assert lock["values"]["lint"] == "cargo clippy"
        assert lock["files"]["opencode.jsonc"] == digest((repo / "opencode.jsonc").read_bytes())


    def test_force_and_update_together_is_a_usage_error(monkeypatch, repo):
        quiet(monkeypatch)
        answer = workspace_init(root=repo, force=True, update=True)
        assert answer == {"ok": False, "error": "usage_error: --force and --update exclude each other"}
        assert not (repo / "opencode.jsonc").exists()


    @pytest.mark.parametrize(
        "value",
        ['uv run "x"', "pytest*", "a:b", "$HOME/x", "a\nb"],
        ids=["quote", "star", "colon", "dollar", "newline"],
    )
    def test_a_flag_value_that_would_break_out_is_a_usage_error(monkeypatch, repo, value):
        quiet(monkeypatch)
        answer = workspace_init(root=repo, test=value)
        assert answer["ok"] is False
        assert answer["error"].startswith("usage_error: --test "), answer["error"]
        assert not (repo / "opencode.jsonc").exists()


    def test_a_broken_lock_is_lock_malformed_and_nothing_is_written(monkeypatch, repo):
        quiet(monkeypatch)
        (repo / LOCK_PATH).parent.mkdir(parents=True)
        (repo / LOCK_PATH).write_text("not json", encoding="utf-8")
        answer = workspace_init(root=repo)
        assert answer["ok"] is False
        assert answer["error"].startswith("lock_malformed: ")
        assert answer["error"].endswith("-- fix or delete it")
        assert not (repo / "opencode.jsonc").exists()
        assert (repo / LOCK_PATH).read_text(encoding="utf-8") == "not json"

### Die Tests in `tests/test_workspace.py`

`test_main_routes_init_and_hands_force_on` wird ganz ersetzt durch:

    def test_main_routes_init_and_hands_every_flag_on(monkeypatch, capsys):
        """`workspace_init` is imported ON THE CALL, so the seam is `initcmd`."""
        seen: list[dict[str, object]] = []
        monkeypatch.setattr(
            "lean_herdr.initcmd.workspace_init",
            lambda **kwargs: (seen.append(kwargs), {"ok": True, "written": []})[1],
        )
        assert workspace.main(["init"]) == 0
        assert workspace.main(["init", "--force"]) == 0
        assert (
            workspace.main(["init", "--update", "--test", "cargo test", "--lint", "cargo clippy"])
            == 0
        )
        assert seen == [
            {"force": False, "update": False, "test": None, "lint": None},
            {"force": True, "update": False, "test": None, "lint": None},
            {"force": False, "update": True, "test": "cargo test", "lint": "cargo clippy"},
        ]
        lines = capsys.readouterr().out.strip().splitlines()
        assert len(lines) == 3 and all(json.loads(line)["ok"] for line in lines)

Direkt nach `test_up_refuses_force_rather_than_ignoring_it`:

    @pytest.mark.parametrize(
        "flags",
        [["--update"], ["--test", "cargo test"], ["--lint", "cargo clippy"]],
        ids=["update", "test", "lint"],
    )
    def test_up_refuses_every_init_flag(capsys, flags):
        """Swallowed, an init flag on `up` would look like it did something."""
        assert workspace.main(["up", *flags]) == 0
        answer = json.loads(capsys.readouterr().out)
        assert answer["ok"] is False
        assert answer["error"] == f"usage_error: up does not take {flags[0]}"

### Der Fix

@call patch("lean_herdr/templating.py", "the module docstring, the imports, and new definitions after render")

1. Im Modul-Docstring, als letzter Absatz:

        The lock, `templates.lock.json`, records what `init` wrote: the resolved
        values and a sha256 per file. Against it and a fresh rendering every target
        has one of seven states (`file_state`), and `init --update` rewrites only the
        files nobody touched since.

2. Imports werden:

        from __future__ import annotations

        import hashlib
        import json
        import os
        import re
        import tempfile
        from collections.abc import Mapping
        from pathlib import Path

3. Nach `render`:

        #: Versioned, like the role prompts: it travels in the branch, and the next
        #: `init --update` -- anybody's -- needs the record of what init wrote.
        LOCK_PATH = Path(".lean-ctx") / "lean-herdr" / "templates.lock.json"

        _SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")

        #: state -> the next step `state_warnings` names. `current` and `edited` are
        #: absent on purpose: nothing to do, and a hand edit is intent.
        _NEXT_STEP = {
            "missing": "`lean-herdr workspace init --update` writes it",
            "outdated": "nobody edited it since init wrote it: `lean-herdr workspace init --update`",
            "unknown": "no lock entry and not what init would write -- compare it with the template by hand",
            "diverged": "edited here AND changed in the package -- compare it with the template by hand",
            "blocked": "it or one of its parent directories is a symlink, and init never writes through one",
        }


        class LockError(ValueError):
            """`templates.lock.json` is there and unusable. The message starts with the path."""


        def digest(data: bytes) -> str:
            """The sha256 the lock records, as hex."""
            return hashlib.sha256(data).hexdigest()


        def resolve_values(
            locked: Mapping[str, str], *, test: str | None = None, lint: str | None = None
        ) -> dict[str, str]:
            """Flag > lock > default, per key -- the one resolution `init` and `check` share."""
            given = {"test": test, "lint": lint}
            return {key: given[key] or locked.get(key) or default for key, default in DEFAULT_VALUES.items()}


        def read_lock(root: Path) -> dict[str, dict[str, str]]:
            """The lock as `{"values": {...}, "files": {...}}`. Missing: both empty.

            Broken is a LockError, never a guess: not JSON, not that shape, a value
            `VALUE_RE` refuses, or a file key outside LAYOUT. A state computed from a
            record nobody can read would be the silent wrong answer the lock exists
            to prevent.
            """
            path = Path(root) / LOCK_PATH
            try:
                raw = path.read_bytes()
            except FileNotFoundError:
                return {"values": {}, "files": {}}
            except OSError as exc:
                raise LockError(f"{path}: unreadable: {exc}") from exc
            try:
                data = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise LockError(f"{path}: not JSON: {exc}") from exc
            if not isinstance(data, dict) or set(data) != {"values", "files"}:
                raise LockError(f"{path}: expected exactly the keys `values` and `files`")
            values, files = data["values"], data["files"]
            if not isinstance(values, dict) or not isinstance(files, dict):
                raise LockError(f"{path}: `values` and `files` must be objects")
            for key, value in values.items():
                if key not in DEFAULT_VALUES or not isinstance(value, str) or not VALUE_RE.match(value):
                    raise LockError(f"{path}: values.{key} = {value!r} is not a usable command")
            targets = set(LAYOUT.values())
            for key, entry in files.items():
                if key not in targets or not isinstance(entry, str) or not _SHA256_RE.match(entry):
                    raise LockError(f"{path}: files.{key} is no template target with a sha256")
            return {"values": dict(values), "files": dict(files)}


        def write_lock(root: Path, *, values: Mapping[str, str], files: Mapping[str, str]) -> Path:
            """The whole lock, through a temp file of this writer's own, then `os.replace`.

            Inline, like `catalog.write_overlay` -- no shared helper. WHOLE is the
            file, not the content: the caller hands every entry it did not write back
            in unchanged. Keys sorted, indent 2, a trailing newline, so a diff in the
            branch shows one line per changed file. `mkstemp` creates 0600, and git
            records no mode but the executable bit.
            """
            path = Path(root) / LOCK_PATH
            path.parent.mkdir(parents=True, exist_ok=True)
            text = json.dumps({"files": dict(files), "values": dict(values)}, indent=2, sort_keys=True)
            fd, name = tempfile.mkstemp(dir=path.parent, prefix=f".tmp-{path.name}.")
            tmp = Path(name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(text + "\n")
                os.replace(tmp, path)
            except OSError:
                # Only OUR temp file, for the reason `write_overlay` gives.
                tmp.unlink(missing_ok=True)
                raise
            return path


        def file_state(root: Path, relative: str, *, rendered: bytes, locked: str | None) -> str:
            """One target's state, checked in this order.

            D is the file, L the lock entry, P the rendered template.
            `blocked` -- a symlink on the way or at the target (the rules of
            `initcmd._place`); `missing`; `current` D = P; `unknown` no L;
            `outdated` D = L != P; `edited` D != L = P; `diverged` D != L, L != P.

            Raises OSError for a target that is there and cannot be read -- a
            directory in its place, a regular file where a parent directory belongs.
            `init` stops on it with its report so far; `check` names it.
            """
            base = Path(root)
            parent = base
            for part in Path(relative).parts[:-1]:
                parent = parent / part
                if parent.is_symlink():
                    return "blocked"
            target = base / relative
            if target.is_symlink():
                return "blocked"
            try:
                on_disk = digest(target.read_bytes())
            except FileNotFoundError:
                return "missing"
            produced = digest(rendered)
            if on_disk == produced:
                return "current"
            if locked is None:
                return "unknown"
            if on_disk == locked:
                return "outdated"
            return "edited" if locked == produced else "diverged"


        def state_warnings(templates: Mapping[str, str]) -> list[str]:
            """One line per template that needs a gesture or a hand, sorted by path."""
            return [
                f"{relative} is {state}: {_NEXT_STEP[state]}"
                for relative, state in sorted(templates.items())
                if state in _NEXT_STEP
            ]

   Zeilen über 100 Zeichen bricht `ruff format` im Gate um; `ruff check` meldet E501
   in diesem Projekt nicht (kein `select`).

@call patch("lean_herdr/initcmd.py", "the module docstring's first rule, the templating import, and the signature, docstring and body of workspace_init from the root lookup to the return")

4. Im Modul-Docstring wird der Satz „The first: an existing file is NEVER overwritten
   without --force." zu:

        The first: an existing file is NEVER overwritten without --force -- or
        without --update, and then only when the lock proves nobody touched it
        since init wrote it.

5. Der Import aus `lean_herdr.templating` wird so — `DEFAULT_VALUES` braucht `initcmd`
   ab jetzt nicht mehr, `resolve_values` kennt es:

        from lean_herdr.templating import (
            LAYOUT,
            VALUE_RE,
            LockError,
            digest,
            file_state,
            read_lock,
            render,
            resolve_values,
            state_warnings,
            write_lock,
        )
6. Die Signatur wird:

        def workspace_init(
            *,
            root: Path | None = None,
            force: bool = False,
            update: bool = False,
            test: str | None = None,
            lint: str | None = None,
            runner: Any = subprocess.run,
        ) -> dict[str, Any]:

7. Die erste Docstring-Zeile wird „Write the templates into this project, and lock what
   landed. Never raises."; als letzter Docstring-Absatz:

            Three modes. Without a flag only `missing` files are written. `--update`
            also rewrites `outdated` ones -- untouched since init wrote them, so no
            hand edit is lost. `--force` writes everything but through a symlinked
            parent. The lock records the resolved values and, per file, the sha256 of
            what this run wrote or found `current`; every other entry stays as it
            was, or a later `--update` could no longer tell an untouched file from an
            edited one.

8. Vor dem `try` um `canonical_root`:

            if force and update:
                return {"ok": False, "error": "usage_error: --force and --update exclude each other"}
            for flag, value in (("--test", test), ("--lint", lint)):
                if value is not None and not VALUE_RE.match(value):
                    return {
                        "ok": False,
                        "error": (
                            f"usage_error: {flag} {value!r} -- letters, digits, spaces and "
                            "._/=+,@- only, starting with a letter or digit, no trailing space"
                        ),
                    }

9. Ab `written: list[str] = []` bis einschließlich des `except OSError`-Returns wird:

            try:
                lock = read_lock(base)
            except LockError as exc:
                return {
                    "ok": False,
                    "error": f"lock_malformed: {exc} -- fix or delete it",
                    "root": str(base),
                }
            values = resolve_values(lock["values"], test=test, lint=lint)
            files = dict(lock["files"])
            written: list[str] = []
            skipped: list[str] = []
            templates: dict[str, str] = {}
            try:
                for name, relative in LAYOUT.items():
                    data = render(name, values)
                    state = file_state(base, relative, rendered=data, locked=files.get(relative))
                    wanted = force or state == "missing" or (update and state == "outdated")
                    if wanted and _place(base, relative, data, force=force or update):
                        written.append(relative)
                        state = "current"
                    else:
                        skipped.append(relative)
                    if state == "current":
                        files[relative] = digest(data)
                    templates[relative] = state
                write_lock(base, values=values, files=files)
            except OSError as exc:
                return {
                    "ok": False,
                    "error": f"init_stopped: {exc}",
                    "root": str(base),
                    "written": sorted(written),
                    "skipped": sorted(skipped),
                }

10. Die Zeile `warnings = _warnings(base, …) + warnings` wird
    `warnings = _warnings(base, data=data, overlay_auto=overlay_auto, runner=runner) + state_warnings(templates) + warnings`
    (mehrzeilig nach `ruff format`), und das Ergebnis-Dict bekommt zwischen `skipped`
    und `warmed` die Schlüssel `"values": values,` und `"templates": templates,`.

@call patch("lean_herdr/workspace.py", "build_parser, and the up/init branch in main plus a helper above main")

11. In `build_parser`, nach `--force`:

            p.add_argument(
                "--update",
                action="store_true",
                help="init: also rewrite files nobody edited since init wrote them",
            )
            p.add_argument(
                "--test",
                default=None,
                help="init: the pre-merge test command, and the builder's permission for it",
            )
            p.add_argument(
                "--lint",
                default=None,
                help="init: the pre-merge lint command, and the builder's permission for it",
            )

12. Direkt vor `def main`:

        def _init_flags(args: argparse.Namespace) -> str:
            """The init-only flags that were given, as one phrase. Empty: none."""
            given = (
                ("--force", args.force),
                ("--update", args.update),
                ("--test", args.test),
                ("--lint", args.lint),
            )
            return " and ".join(flag for flag, value in given if value)

13. Im `try` von `main` wird der Block ab `if args.command == "up":` bis einschließlich
    `result = workspace_init(force=args.force)` zu:

                stray = _init_flags(args)
                if args.command != "init" and stray:
                    result = {
                        "ok": False,
                        "error": f"usage_error: {args.command} does not take {stray}",
                    }
                elif args.command == "up":
                    result = workspace_up()
                else:
                    # Imported on the call, not up top: `up` is what runs on every
                    # start, and it needs none of this.
                    from lean_herdr.initcmd import workspace_init

                    result = workspace_init(
                        force=args.force, update=args.update, test=args.test, lint=args.lint
                    )

### `tests/test_templates.py` hält ab jetzt das Lock

Die Datei wird ganz:

    """The template in the wheel is the source; this repo's copy is a rendering of it.

    `lean-herdr workspace init` renders lean_herdr/templates/ and writes the result.
    This repo uses itself, so every file init would write also exists here as a
    checked-in copy at the place init would put it. Two spellings of one text is
    exactly the drift this test exists to prevent: without it,
    test_role_prohibitions.py would guard the copy while `init` shipped the other
    version into every new project -- and the test that watches the prohibitions
    would watch the wrong file.

    The lock of this repository is held too. `file_state` checks D = P before it ever
    looks at the lock, so byte identity alone would pass over a missing or stale
    lock -- and a stale entry turns a later hand edit into `diverged` instead of
    `edited`. Every template change therefore pulls the lock along:
    `uv run lean-herdr workspace init`.
    """

    from pathlib import Path

    import pytest

    from lean_herdr.templating import (
        LAYOUT,
        LOCK_PATH,
        TEMPLATES,
        digest,
        file_state,
        read_lock,
        render,
        resolve_values,
    )

    ROOT = Path(__file__).resolve().parents[1]


    def test_this_repository_carries_its_lock():
        assert (ROOT / LOCK_PATH).is_file(), f"no {LOCK_PATH} -- run `uv run lean-herdr workspace init`"
        assert set(read_lock(ROOT)["files"]) == set(LAYOUT.values())


    @pytest.mark.parametrize(("template", "copy"), sorted(LAYOUT.items()))
    def test_the_rendered_template_and_the_checked_in_copy_are_byte_identical(template, copy):
        rendered = render(template, resolve_values(read_lock(ROOT)["values"]))
        assert rendered == (ROOT / copy).read_bytes(), f"{template} and {copy} have drifted apart"


    @pytest.mark.parametrize(("template", "copy"), sorted(LAYOUT.items()))
    def test_every_lock_entry_is_the_checked_in_copy(template, copy):
        lock = read_lock(ROOT)
        assert lock["files"].get(copy) == digest((ROOT / copy).read_bytes()), (
            f"{LOCK_PATH}: the entry for {copy} is stale -- run `uv run lean-herdr workspace init`"
        )
        rendered = render(template, resolve_values(lock["values"]))
        assert file_state(ROOT, copy, rendered=rendered, locked=lock["files"][copy]) == "current"


    def test_no_template_without_a_pair_and_no_pair_without_a_template():
        """Both directions: a stray file ships to strangers unannounced."""
        on_disk = {p.relative_to(TEMPLATES).as_posix() for p in TEMPLATES.rglob("*") if p.is_file()}
        assert on_disk == set(LAYOUT), f"unpaired: {sorted(on_disk ^ set(LAYOUT))}"

### Das Lock dieses Repos

Erst wenn alle anderen Tests grün sind:

    uv run lean-herdr workspace init

Expected: eine JSON-Zeile mit `"ok": true`, `"written": []`, jede Datei in `templates`
`"current"`, `"values"` gleich den Defaults. Der Warm-up kann bis 8 s dauern.

    git check-ignore -v .lean-ctx/lean-herdr/templates.lock.json

Expected: keine Ausgabe, Exit 1 — die Datei ist nicht ignoriert.

    uv run pytest -q tests/test_templates.py

Expected: PASS.

Ohne Änderung grün bleiben `test_a_fresh_project_gets_every_file`,
`test_a_second_run_writes_nothing`, `test_a_dangling_symlink_is_not_written_through`,
`test_force_replaces_the_link_instead_of_following_it`,
`test_a_layout_parent_that_is_a_file_keeps_the_report`,
`test_a_stranger_file_survives_without_force` und
`test_up_refuses_force_rather_than_ignoring_it`.

### Verify & Close

@call verify(lean_herdr/templating.py lean_herdr/initcmd.py lean_herdr/workspace.py tests/ .lean-ctx/lean-herdr/templates.lock.json)
@call review_change()
@call gate(lean_herdr/templating.py lean_herdr/initcmd.py lean_herdr/workspace.py tests/)
@call commit("lean_herdr/templating.py lean_herdr/initcmd.py lean_herdr/workspace.py tests/test_templating.py tests/test_initcmd.py tests/test_templates.py tests/test_workspace.py .lean-ctx/lean-herdr/templates.lock.json", "feat(init): lock what init writes, and let --update rewrite only the files nobody touched")
@call remember_decision("Since task 6 of the hardening plan: templating has LOCK_PATH, LockError, digest, resolve_values, read_lock, write_lock, file_state (blocked missing current unknown outdated edited diverged) and state_warnings; workspace_init takes force/update/test/lint and returns values and templates; this repo carries .lean-ctx/lean-herdr/templates.lock.json and tests/test_templates.py holds L = D for every copy.")
@phase-end

@phase "task-7"
## Task 7: `checkcmd.py` — `workspace check`, und `init` meldet über dieselben Produzenten

**Files:** Create `lean_herdr/checkcmd.py`, `tests/test_checkcmd.py`.
Modify `lean_herdr/initcmd.py`, `lean_herdr/workspace.py`, `tests/test_initcmd.py`,
`tests/test_workspace.py`.

**Interfaces — Produces** (`lean_herdr/checkcmd.py`):

- `workspace_check(*, root: Path | None = None, runner: Any = subprocess.run) -> dict[str, Any]`
  — `{"ok", "root", "errors", "warnings", "install", "templates"}`; ohne Repository fehlt
  `root`. Wirft nie, startet, schreibt und fetcht nichts.
- `machine_report(root: Path | None, *, data: dict[str, Any], overlay_auto: bool, runner: Any = subprocess.run) -> tuple[dict[str, Any], list[str]]`
  — Install-Fakten und jede Maschinen-Warnung; `init` und `check` teilen sie.
- `install_report(*, prefix=None, package=None, which=shutil.which, direct_url=_direct_url, environ=None) -> tuple[dict[str, Any], list[str]]`
  — `install` hat die Schlüssel `tool editable package binary plugin` (`plugin` füllt
  `machine_report`).
- `_check_generator(root: Path | None, runner: Any) -> str | None`
- `_linked_plugin(runner: Any, expected: Path) -> tuple[str | None, str | None]`
- `_check_temp_leftovers(root: Path) -> str | None`
- verschoben aus `initcmd`, unverändert: `CHECK_TIMEOUT_S`, `_read`, `_check_allowlist`,
  `_check_approvals`, `_check_plugins`, `_check_overlay_ignored`, `TEMP_IGNORE`,
  `TEMP_PROBE`, `_check_temp_ignored`.

**Consumes:** `bus.GitUnusable`/`BusError` (Task 1), `settings.OverlayError` (Task 2),
die Ignore-Prüfungen (Task 4), `templating.read_lock`/`file_state`/`resolve_values`/
`state_warnings`/`LockError` (Task 6), `workspace.INIT_HINT`/`missing_agent_config`.

**Entfällt** in `initcmd`: `_warnings`; `workspace_init` holt seine Warnungen aus
`machine_report` — meldet also künftig auch Generator, Install und Plugin-Link.

@call recall_context("hardening plan tasks 1, 2, 4 and 6: GitUnusable, OverlayError, the temp ignore check, the template lock")

@read lean_herdr/initcmd.py mode=signatures
@read lean_herdr/templating.py mode=signatures
@read tests/test_initcmd.py mode=signatures

Gemessen am 2026-09-13, damit die Parser auf echte Formen zielen:
`wt config show --format json` antwortet `{"project": {…}, "system": {"exists": false, "path": …}, "user": {"config": null, "exists": false, "path": …}}`
und schreibt danach auf stderr `▲ Project config has key list.json-schema …`;
`herdr plugin list --plugin lean.herdr` antwortet
`- lean.herdr (lean-herdr context) enabled [local:/home/tholo/Scripts/lean-herdr]`.

@call tdd(tests/test_checkcmd.py)

Rot heißt hier: `ModuleNotFoundError: No module named 'lean_herdr.checkcmd'`.

### `tests/test_checkcmd.py`

Die Datei beginnt so:

    """`workspace check`: every group of warnings, and the errors that stop `up` and `dispatch`."""

    import json
    import subprocess
    from pathlib import Path

    import pytest

    from lean_herdr import checkcmd
    from lean_herdr.bus import BusError
    from lean_herdr.checkcmd import (
        TEMP_IGNORE,
        TEMP_PROBE,
        _check_allowlist,
        _check_approvals,
        _check_generator,
        _check_overlay_ignored,
        _check_plugins,
        _check_temp_ignored,
        _check_temp_leftovers,
        _linked_plugin,
        install_report,
        workspace_check,
    )
    from lean_herdr.initcmd import workspace_init
    from lean_herdr.settings import OVERLAY_PATH, SETTINGS_PATH
    from lean_herdr.templating import LAYOUT, LOCK_PATH
    from tests.doubles import FakeProc, which_stub


    @pytest.fixture
    def repo(tmp_path):
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, timeout=30)
        return tmp_path

Danach, **unverändert aus `tests/test_initcmd.py` verschoben** (dort gelöscht):
`test_the_allowlist_check_answers_a_line_only_when_the_name_is_missing`,
`test_an_unreadable_approvals_reply_is_reported_as_an_unknown_state`,
`test_the_approvals_check_parses_from_the_first_brace`,
`test_the_plugin_check_only_fires_on_a_warning_line`,
`test_the_overlay_check_asks_git_rather_than_reading_gitignore`,
`test_without_git_there_is_no_verdict_on_the_overlay`,
`test_the_temp_check_asks_git_about_a_probe_name`.

Dann die neuen Tests:

    def wt_show(user=None, system=None) -> str:
        """wt's own shape (0.77.0), with the stderr line `_read` appends behind the JSON."""
        shown = {
            "user": {"config": user, "exists": user is not None, "path": "/home/x/.config/wt.toml"},
            "system": {"exists": system is not None, "path": "/etc/xdg/worktrunk/config.toml"},
        }
        if system is not None:
            shown["system"]["config"] = system
        return json.dumps(shown, indent=2) + "\n\n▲ Project config has key list.json-schema\n"


    def generation(command: str) -> dict:
        return {"commit": {"generation": {"command": command}}}


    @pytest.mark.parametrize(
        ("user", "system", "warned"),
        [
            pytest.param(generation("lean-herdr llm generate"), None, False, id="user config"),
            pytest.param(
                generation("lean-herdr llm generate --effort low"), None, False, id="flags behind it"
            ),
            pytest.param(None, generation("lean-herdr llm generate"), False, id="system config"),
            pytest.param(
                generation("/home/x/lean-herdr/bin/herdr-llm generate"),
                generation("lean-herdr llm generate"),
                True,
                id="user before system",
            ),
            pytest.param(None, None, True, id="none at all"),
        ],
    )
    def test_the_generator_is_read_user_before_system(monkeypatch, tmp_path, user, system, warned):
        monkeypatch.setattr("shutil.which", which_stub(True))
        proc = FakeProc(replies={("config", "show"): wt_show(user, system)})
        line = _check_generator(tmp_path, proc)
        assert (line is not None) is warned, line
        assert proc.called_with("wt", "config", "show", "--format", "json")


    def test_a_missing_generator_names_the_line_to_add(monkeypatch, tmp_path):
        monkeypatch.setattr("shutil.which", which_stub(True))
        line = _check_generator(tmp_path, FakeProc(replies={("config", "show"): wt_show()}))
        assert line is not None and 'command = "lean-herdr llm generate"' in line


    def test_an_unreadable_wt_answer_is_no_green_verdict(monkeypatch, tmp_path):
        monkeypatch.setattr("shutil.which", which_stub(True))
        line = _check_generator(tmp_path, FakeProc(replies={("config", "show"): "error: no"}))
        assert line is not None and "no readable answer" in line


    def prefix_with(tmp_path: Path, *, receipt: bool = True) -> tuple[Path, Path]:
        """A prepared tool venv: (prefix, the package's __init__.py inside it)."""
        prefix = tmp_path / "tools" / "lean-herdr"
        package = prefix / "lib" / "python3.14" / "site-packages" / "lean_herdr" / "__init__.py"
        package.parent.mkdir(parents=True)
        package.write_text("", encoding="utf-8")
        (prefix / "bin").mkdir()
        (prefix / "bin" / "lean-herdr").write_text("", encoding="utf-8")
        if receipt:
            (prefix / "uv-receipt.toml").write_text("", encoding="utf-8")
        return prefix, package


    def report(prefix, package, *, binary, direct_url=None, environ=None):
        return install_report(
            prefix=prefix,
            package=package,
            which=lambda _name: None if binary is None else str(binary),
            direct_url=lambda: direct_url,
            environ=environ or {},
        )


    def test_a_snapshot_reached_through_a_symlink_on_path_warns_about_nothing(tmp_path):
        """`~/.local/bin/lean-herdr` is a symlink into the tool venv -- the correct install."""
        prefix, package = prefix_with(tmp_path)
        link = tmp_path / "local-bin" / "lean-herdr"
        link.parent.mkdir()
        link.symlink_to(prefix / "bin" / "lean-herdr")
        install, lines = report(
            prefix, package, binary=link, direct_url='{"url": "file:///x", "dir_info": {}}'
        )
        assert lines == []
        assert install["tool"] is True
        assert install["editable"] is False
        assert install["package"] == str(package.parent.resolve())
        assert install["binary"] == str((prefix / "bin" / "lean-herdr").resolve())


    def test_no_receipt_is_no_tool_venv(tmp_path):
        prefix, package = prefix_with(tmp_path, receipt=False)
        install, lines = report(prefix, package, binary=prefix / "bin" / "lean-herdr")
        assert install["tool"] is False
        assert any("uv-receipt.toml" in line for line in lines), lines


    def test_an_editable_install_is_named(tmp_path):
        prefix, package = prefix_with(tmp_path)
        install, lines = report(
            prefix,
            package,
            binary=prefix / "bin" / "lean-herdr",
            direct_url='{"url": "file:///home/x/lean-herdr", "dir_info": {"editable": true}}',
        )
        assert install["editable"] is True
        assert any("editable" in line for line in lines), lines


    def test_a_package_outside_the_prefix_names_pythonpath_when_it_is_set(tmp_path):
        prefix, _ = prefix_with(tmp_path)
        fake = tmp_path / "elsewhere" / "lean_herdr" / "__init__.py"
        fake.parent.mkdir(parents=True)
        fake.write_text("", encoding="utf-8")
        _, lines = report(
            prefix,
            fake,
            binary=prefix / "bin" / "lean-herdr",
            environ={"PYTHONPATH": str(tmp_path / "elsewhere")},
        )
        assert any("PYTHONPATH=" in line for line in lines), lines


    def test_a_binary_outside_the_prefix_is_a_shadowing_venv(tmp_path):
        prefix, package = prefix_with(tmp_path)
        venv = tmp_path / "repo" / ".venv" / "bin" / "lean-herdr"
        venv.parent.mkdir(parents=True)
        venv.write_text("", encoding="utf-8")
        _, lines = report(prefix, package, binary=venv)
        assert any("outside" in line and ".venv" in line for line in lines), lines


    def test_no_binary_on_path_is_named(tmp_path):
        prefix, package = prefix_with(tmp_path)
        _, lines = report(prefix, package, binary=None)
        assert any("not on PATH" in line for line in lines), lines


    def test_the_plugin_link_is_read_from_the_local_marker(monkeypatch, tmp_path):
        monkeypatch.setattr("shutil.which", which_stub(True))
        expected = tmp_path / "lean_herdr" / "plugin"
        good = FakeProc(
            replies={
                ("plugin", "list"): (
                    f"1 plugin installed:\n- lean.herdr (lean-herdr context) enabled [local:{expected}]\n"
                )
            }
        )
        assert _linked_plugin(good, expected) == (str(expected), None)
        assert good.called_with("herdr", "plugin", "list", "--plugin", "lean.herdr")
        checkout = FakeProc(
            replies={("plugin", "list"): "- lean.herdr (context) enabled [local:/home/x/lean-herdr]\n"}
        )
        linked, line = _linked_plugin(checkout, expected)
        assert linked == "/home/x/lean-herdr"
        assert line is not None and f"herdr plugin link {expected}" in line


    def test_without_herdr_there_is_no_plugin_verdict(monkeypatch, tmp_path):
        monkeypatch.setattr("shutil.which", which_stub(False))
        assert _linked_plugin(FakeProc(), tmp_path) == (None, None)


    def test_temp_files_left_behind_are_named(tmp_path):
        assert _check_temp_leftovers(tmp_path) is None
        folder = tmp_path / OVERLAY_PATH.parent
        folder.mkdir(parents=True)
        (folder / ".tmp-models.auto.toml.k3j9x_ab").write_text("half", encoding="utf-8")
        line = _check_temp_leftovers(tmp_path)
        assert line is not None and ".tmp-models.auto.toml.k3j9x_ab" in line


    #: A snapshot install that shadows nothing -- this suite runs from the repo venv,
    #: which is, correctly, no snapshot.
    HEALTHY = {
        "tool": True,
        "editable": False,
        "package": "/snap/lean_herdr",
        "binary": "/snap/bin/lean-herdr",
        "plugin": None,
    }


    @pytest.fixture
    def snapshot(monkeypatch):
        monkeypatch.setattr(checkcmd, "install_report", lambda **_kwargs: (dict(HEALTHY), []))


    def healthy_machine() -> FakeProc:
        return FakeProc(
            replies={
                ("allow", "--list"): "Extra (additive, via `lean-ctx allow`): lean-herdr",
                ("config", "approvals"): '{"state": "approved"}',
                ("config", "show"): wt_show(generation("lean-herdr llm generate")),
                ("plugin", "list"): "- lean.herdr (context) enabled [local:/snap/lean_herdr/plugin]\n",
                ("check-ignore",): ".gitignore:1:rule\tpath",
            }
        )


    def initialised(monkeypatch, repo):
        """`init` on a machine without binaries, then every binary back on the PATH."""
        monkeypatch.setattr("shutil.which", which_stub(False))
        assert workspace_init(root=repo)["ok"] is True
        monkeypatch.setattr("shutil.which", which_stub(True))


    def test_an_initialised_project_on_a_healthy_machine_is_ok_and_all_current(
        monkeypatch, repo, snapshot
    ):
        initialised(monkeypatch, repo)
        answer = workspace_check(root=repo, runner=healthy_machine())
        assert answer["ok"] is True, answer
        assert answer["errors"] == []
        assert answer["warnings"] == []
        assert answer["root"] == str(repo)
        assert answer["templates"] == {relative: "current" for relative in LAYOUT.values()}
        assert answer["install"]["plugin"] == "/snap/lean_herdr/plugin"


    def test_check_changes_nothing_and_runs_nothing_that_writes(monkeypatch, repo, snapshot):
        """No start, no write, no fetch, no warm-up -- and no gesture that belongs to a human."""
        initialised(monkeypatch, repo)

        def files() -> dict:
            return {p: p.read_bytes() for p in repo.rglob("*") if p.is_file() and ".git" not in p.parts}

        before = files()
        proc = healthy_machine()
        workspace_check(root=repo, runner=proc)
        assert files() == before
        for forbidden in (("allow", "lean-herdr"), ("approvals", "add"), ("plugin", "link"), ("opencode",)):
            assert not proc.called_with(*forbidden), proc.flat()


    def test_outside_a_repository_there_is_no_root_and_an_error(monkeypatch, snapshot):
        def no_repo(*_args, **_kwargs):
            raise BusError("git rev-parse --git-common-dir failed: not a git repository")

        monkeypatch.setattr(checkcmd, "canonical_root", no_repo)
        monkeypatch.setattr("shutil.which", which_stub(False))
        answer = workspace_check()
        assert answer["ok"] is False
        assert "root" not in answer
        assert answer["errors"][0].startswith("git rev-parse --git-common-dir failed")
        assert answer["templates"] == {}


    def test_a_project_init_never_touched_is_not_initialised(monkeypatch, repo, snapshot):
        monkeypatch.setattr("shutil.which", which_stub(False))
        answer = workspace_check(root=repo)
        assert answer["ok"] is False
        assert any(e.startswith("not_initialised:") for e in answer["errors"]), answer["errors"]
        assert any(e.startswith("no_agent_config:") for e in answer["errors"]), answer["errors"]
        assert answer["templates"] == {relative: "missing" for relative in LAYOUT.values()}


    @pytest.mark.parametrize(
        ("config", "overlay", "names"),
        [
            pytest.param('[roles.builder]\ndirection = "links"\n', None, "direction", id="a role table"),
            pytest.param('[llm]\neffort = "enormous"\n', None, "effort", id="the llm table"),
            pytest.param(None, "[llm]\nmodel = 5\n", "lean-herdr models apply", id="the overlay"),
        ],
    )
    def test_what_stops_up_or_dispatch_is_an_error(
        monkeypatch, repo, snapshot, config, overlay, names
    ):
        initialised(monkeypatch, repo)
        monkeypatch.setattr("shutil.which", which_stub(False))
        if config is not None:
            (repo / SETTINGS_PATH).write_text(config, encoding="utf-8")
        if overlay is not None:
            (repo / OVERLAY_PATH).write_text(overlay, encoding="utf-8")
        answer = workspace_check(root=repo)
        assert answer["ok"] is False
        assert any(e.startswith("config_error:") and names in e for e in answer["errors"]), answer


    def test_a_broken_lock_guesses_no_state(monkeypatch, repo, snapshot):
        initialised(monkeypatch, repo)
        monkeypatch.setattr("shutil.which", which_stub(False))
        (repo / LOCK_PATH).write_text("not json", encoding="utf-8")
        answer = workspace_check(root=repo)
        assert answer["templates"] == {}
        assert any(w.startswith("lock_malformed:") for w in answer["warnings"]), answer["warnings"]


    def test_an_outdated_template_names_init_update(monkeypatch, repo, snapshot):
        initialised(monkeypatch, repo)
        monkeypatch.setattr("shutil.which", which_stub(False))
        lock = repo / LOCK_PATH
        lock.write_text(
            lock.read_text(encoding="utf-8").replace("uv run pytest", "cargo test"), encoding="utf-8"
        )
        answer = workspace_check(root=repo)
        assert answer["templates"][".config/wt.toml"] == "outdated"
        assert any(
            w.startswith(".config/wt.toml is outdated") and "init --update" in w
            for w in answer["warnings"]
        ), answer["warnings"]


    @pytest.mark.parametrize("auto", [False, True], ids=["auto-off", "auto-on"])
    def test_only_the_overlay_ignored_names_the_temp_line_whatever_auto_says(
        monkeypatch, repo, snapshot, auto
    ):
        """One verdict per path: the overlay's rule covers the overlay and nothing else.

        With `auto` on both checks run -- and a single `check-ignore` over both paths
        would answer as soon as the overlay is covered.
        """
        initialised(monkeypatch, repo)
        if auto:
            (repo / SETTINGS_PATH).write_text("[models]\nauto = true\n", encoding="utf-8")
        proc = FakeProc(
            replies={
                ("check-ignore", "-v", str(OVERLAY_PATH)): (
                    f".gitignore:22:{OVERLAY_PATH}\t{OVERLAY_PATH}"
                )
            },
            default="",
        )
        answer = workspace_check(root=repo, runner=proc)
        assert any(TEMP_IGNORE in w for w in answer["warnings"]), answer["warnings"]
        assert not any(f"does not ignore {OVERLAY_PATH}" in w for w in answer["warnings"])

### Das Modul

`lean_herdr/checkcmd.py` — Kopf:

    """`lean-herdr workspace check` -- will `up` and `dispatch` run here, and what gets worse?

    One JSON line, and nothing else happens: no start, no write, no fetch, no
    warm-up. `errors` are what makes `up` or `dispatch` fail right now; `warnings`
    are what still runs, only worse -- a gate worktrunk skips, commit messages out
    of file names, a snapshot shadowed by a venv. Every line names the next step.

    Every foreign command here only READS, bounded by CHECK_TIMEOUT_S, and a binary
    that is not on the PATH gives no verdict rather than a guessed one. `init`
    reports the same machine through the same producer -- `machine_report` is
    imported there, never rebuilt (one producer per rule, M3). Granting a
    machine-wide permission stays a gesture of the human at the keyboard: nothing
    here runs `lean-ctx allow`, `wt config approvals add` or `herdr plugin link`.
    """

    from __future__ import annotations

    import importlib.metadata
    import json
    import os
    import re
    import shlex
    import shutil
    import subprocess
    import sys
    from collections.abc import Callable, Mapping
    from pathlib import Path
    from typing import Any

    import lean_herdr
    from lean_herdr.bus import BusError, canonical_root
    from lean_herdr.settings import (
        OVERLAY_PATH,
        SETTINGS_PATH,
        OverlayError,
        SettingsError,
        llm_settings_layered,
        model_warnings,
        models_settings,
        read_settings,
        settings_for,
        workspace_settings,
    )
    from lean_herdr.templating import (
        LAYOUT,
        LockError,
        file_state,
        read_lock,
        render,
        resolve_values,
        state_warnings,
    )
    from lean_herdr.workspace import INIT_HINT, missing_agent_config

    #: The binaries a lean-herdr project leans on, and what each one is for.
    BINARIES = (
        ("herdr", "panes, agents and workspaces"),
        ("wt", "one worktree per branch, merge and cleanup"),
        ("lean-ctx", "agent bus, project memory, tool profiles"),
    )

    #: The tables `up` and `dispatch` read roles out of.
    ROLES = ("default", "orchestrator", "builder", "reviewer")

    #: What worktrunk's `commit.generation.command` has to start with. Flags behind
    #: it are the operator's.
    GENERATOR = ("lean-herdr", "llm", "generate")

    PLUGIN_ID = "lean.herdr"

    #: `herdr plugin list` has no JSON; the plugin's line ends in `[local:<path>]`.
    _LOCAL = re.compile(r"\[local:([^\]]+)\]")

Danach **wörtlich aus `initcmd.py` verschoben** (dort gelöscht), mit Kommentaren und
Docstrings: `CHECK_TIMEOUT_S` samt `#:`-Kommentar, `_read`, `_check_allowlist`,
`_check_approvals`, `_check_plugins`, `_check_overlay_ignored`, `TEMP_IGNORE`,
`TEMP_PROBE`, `_check_temp_ignored`. Im Docstring von `_check_overlay_ignored` wird
„`init` does NOT append the line itself." zu „Neither `init` nor `check` appends the
line itself.", und „and this module writes only its own files" zu „and lean-herdr
writes only its own files".

Dann die neuen Teile:

    def _dig(data: Any, *keys: str) -> Any:
        """`data[k1][k2]...`, or None as soon as a level is not a dict."""
        for key in keys:
            data = data.get(key) if isinstance(data, dict) else None
        return data


    def _check_generator(root: Path | None, runner: Any) -> str | None:
        """worktrunk's effective `commit.generation.command`, user config before system.

        `wt config show --format json` names both levels with `path`, `exists` and
        `config`. `_read` appends stderr, and wt writes its warnings there -- after
        the JSON -- so the object is decoded from the first brace and whatever
        follows it is ignored.
        """
        reply = _read(runner, "wt", "config", "show", "--format", "json", cwd=root)
        if reply is None:
            return None
        start = reply.find("{")
        try:
            shown = json.JSONDecoder().raw_decode(reply[start:])[0] if start >= 0 else None
        except json.JSONDecodeError:
            shown = None
        if not isinstance(shown, dict):
            return (
                "wt config show --format json gave no readable answer -- whether commits "
                "get their message from `lean-herdr llm generate` is unknown"
            )
        command = ""
        for level in ("user", "system"):
            found = _dig(shown, level, "config", "commit", "generation", "command")
            if isinstance(found, str) and found:
                command = found
                break
        if not command:
            return (
                "worktrunk has no commit.generation.command -- commits fall back to file "
                "names. Add to ~/.config/worktrunk/config.toml: [commit.generation] "
                'command = "lean-herdr llm generate"'
            )
        try:
            words = shlex.split(command)
        except ValueError:
            words = []
        if tuple(words[: len(GENERATOR)]) == GENERATOR:
            return None
        return (
            f"commit.generation.command is {command!r}, not `lean-herdr llm generate` -- "
            "the installed snapshot does not write the commit messages"
        )


    def _direct_url() -> str | None:
        """`direct_url.json` of the installed distribution, or None."""
        try:
            return importlib.metadata.distribution("lean-herdr").read_text("direct_url.json")
        except importlib.metadata.PackageNotFoundError:
            return None


    def install_report(
        *,
        prefix: Path | None = None,
        package: Path | None = None,
        which: Callable[[str], str | None] = shutil.which,
        direct_url: Callable[[], str | None] = _direct_url,
        environ: Mapping[str, str] | None = None,
    ) -> tuple[dict[str, Any], list[str]]:
        """Where this `lean-herdr` runs from, and what shadows it. Pure reads.

        Every seam defaults to the running process; the tests hand in a prepared
        prefix. `resolve()` on both sides is not optional: `~/.local/bin/lean-herdr`
        is a symlink into the tool venv (measured), and without it every correct
        install would warn. `uv-receipt.toml` is a uv detail -- should it change,
        this says "no tool venv" wrongly, and only ever as a warning.
        """
        base = Path(sys.prefix if prefix is None else prefix).resolve()
        here = Path(lean_herdr.__file__ if package is None else package).resolve().parent
        env = os.environ if environ is None else environ
        found = which("lean-herdr")
        binary = Path(found).resolve() if found else None
        try:
            record = json.loads(direct_url() or "{}")
        except json.JSONDecodeError:
            record = {}
        tool = (base / "uv-receipt.toml").is_file()
        editable = bool(_dig(record, "dir_info", "editable"))
        install: dict[str, Any] = {
            "tool": tool,
            "editable": editable,
            "package": str(here),
            "binary": None if binary is None else str(binary),
            "plugin": None,
        }
        lines: list[str] = []
        if not tool:
            lines.append(
                f"{base} is no uv tool venv (no uv-receipt.toml) -- this lean-herdr is not "
                "the installed snapshot; see README, Updating"
            )
        if editable:
            lines.append(
                "lean-herdr is installed editable -- every project runs whatever branch the "
                "checkout has; reinstall the snapshot from main, see README, Updating"
            )
        if not here.is_relative_to(base):
            shadow = env.get("PYTHONPATH")
            cause = (
                f"PYTHONPATH={shadow} shadows the snapshot"
                if shadow
                else "a checkout or a venv on sys.path shadows the snapshot"
            )
            lines.append(f"lean_herdr is imported from {here}, outside {base} -- {cause}")
        if binary is None:
            lines.append("lean-herdr is not on PATH -- agents, hooks and worktrunk cannot run it")
        elif not binary.is_relative_to(base):
            lines.append(
                f"`lean-herdr` on PATH resolves to {binary}, outside {base} -- an activated "
                "venv comes first on PATH and shadows the snapshot"
            )
        return install, lines


    def _linked_plugin(runner: Any, expected: Path) -> tuple[str | None, str | None]:
        """(the path Herdr links `lean.herdr` to, a warning). (None, None): no herdr."""
        listing = _read(runner, "herdr", "plugin", "list", "--plugin", PLUGIN_ID)
        if listing is None:
            return None, None
        hit = _LOCAL.search(listing)
        linked = hit.group(1) if hit else None
        if linked is not None and Path(linked) == expected:
            return linked, None
        return linked, (
            f"herdr links {PLUGIN_ID} to {linked or 'no local path'}, not to this "
            f"snapshot's manifest -- remove that link, then: herdr plugin link {expected}"
        )


    def _check_temp_leftovers(root: Path) -> str | None:
        """Temp files a killed `models` or `init` run left in `.lean-ctx/lean-herdr/`."""
        folder = root / OVERLAY_PATH.parent
        left = sorted(path.name for path in folder.glob(".tmp-*"))
        if not left:
            return None
        return (
            f"{folder} holds temp files a killed writer left behind: {', '.join(left)} -- "
            "delete them once no `models` or `init` run is active"
        )


    def machine_report(
        root: Path | None,
        *,
        data: dict[str, Any],
        overlay_auto: bool,
        runner: Any = subprocess.run,
    ) -> tuple[dict[str, Any], list[str]]:
        """The install facts and every machine warning -- the producer `init` and `check` share.

        `root=None` is a directory that is no repository: the checks that ask about
        a project -- approvals, ignore rules, leftovers -- have nothing to ask.
        `data` is config.toml already read and valid, `{}` otherwise.
        """
        found = [
            f"{binary} is not on PATH -- needed for {why}"
            for binary, why in BINARIES
            if shutil.which(binary) is None
        ]
        install, install_lines = install_report()
        found.extend(install_lines)
        install["plugin"], plugin_line = _linked_plugin(runner, Path(install["package"]) / "plugin")
        checks = [
            _check_allowlist(runner),
            _check_plugins(runner),
            plugin_line,
            _check_generator(root, runner),
        ]
        if root is not None:
            checks += [
                _check_approvals(root, runner),
                # Guarded by the config: without `[models].auto` no overlay is written.
                _check_overlay_ignored(root, runner) if overlay_auto else None,
                # NOT guarded: the template lock is written in every project.
                _check_temp_ignored(root, runner),
                _check_temp_leftovers(root),
            ]
        found.extend(line for line in checks if line is not None)
        found.extend(model_warnings(data))
        return install, found


    def _config_errors(root: Path) -> tuple[list[str], dict[str, Any], bool]:
        """What stops `up` or `dispatch` here right now, plus the config the warnings read."""
        errors: list[str] = []
        data: dict[str, Any] = {}
        auto = False
        path = root / SETTINGS_PATH
        if not path.is_file():
            errors.append(f"not_initialised: {SETTINGS_PATH} is missing -- {INIT_HINT}")
        else:
            try:
                data = read_settings(path)
                for role in ROLES:
                    settings_for(role, data)
                workspace_settings(data)
                auto = models_settings(data).auto
                llm_settings_layered(root, data)
            except OverlayError as exc:
                # config.toml itself is fine; `dispatch --await` refuses the overlay.
                errors.append(f"config_error: {exc}")
            except SettingsError as exc:
                errors.append(f"config_error: {exc}")
                data, auto = {}, False
        problem = missing_agent_config(root, settings_for("orchestrator", data).kind)
        if problem:
            errors.append(f"no_agent_config: {problem} -- {INIT_HINT}")
        return errors, data, auto


    def _template_report(root: Path) -> tuple[dict[str, str], list[str]]:
        """Every template's state, and the lines it earns. A broken lock guesses nothing."""
        try:
            lock = read_lock(root)
        except LockError as exc:
            return {}, [f"lock_malformed: {exc} -- fix or delete it; no template state is guessed"]
        values = resolve_values(lock["values"])
        templates: dict[str, str] = {}
        unreadable: list[str] = []
        for name, relative in LAYOUT.items():
            try:
                templates[relative] = file_state(
                    root, relative, rendered=render(name, values), locked=lock["files"].get(relative)
                )
            except OSError as exc:
                unreadable.append(f"{relative} cannot be read: {exc}")
        return templates, state_warnings(templates) + unreadable


    def workspace_check(*, root: Path | None = None, runner: Any = subprocess.run) -> dict[str, Any]:
        """Will `up` and `dispatch` run here, and where does it get quietly worse?

        Never raises; starts, writes and fetches nothing. `ok` is the absence of
        `errors`. Outside a repository the answer carries no `root`, and nothing
        that needs one is asked.
        """
        try:
            base = root if root is not None else canonical_root()
        except BusError as exc:
            install, warnings = machine_report(None, data={}, overlay_auto=False, runner=runner)
            return {
                "ok": False,
                "errors": [f"{exc} -- run this inside a git repository"],
                "warnings": warnings,
                "install": install,
                "templates": {},
            }
        errors, data, auto = _config_errors(base)
        install, warnings = machine_report(base, data=data, overlay_auto=auto, runner=runner)
        templates, template_lines = _template_report(base)
        return {
            "ok": not errors,
            "root": str(base),
            "errors": errors,
            "warnings": warnings + template_lines,
            "install": install,
            "templates": templates,
        }

### `initcmd` holt seine Warnungen dort

@call patch("lean_herdr/initcmd.py", "the module docstring's second rule, the imports, the moved checks and _warnings, and the warnings line in workspace_init")

1. Verschobene Teile löschen (siehe oben) und `_warnings` löschen.
2. Import dazu: `from lean_herdr.checkcmd import machine_report`. Danach unbenutzte
   Imports entfernen — `ruff check` meldet sie als F401 (erwartet: `json`, `re`,
   `OVERLAY_PATH`).
3. Im Modul-Docstring wird der Absatz „The second: preconditions are REPORTED, never
   repaired. …" bis „… and it is aborted on purpose." zu:

        The second: preconditions are REPORTED, never repaired. The warnings come
        out of `checkcmd.machine_report`, the producer `workspace check` uses too,
        and every foreign command it runs only READS. `init` runs no `lean-ctx
        allow`, no `wt config approvals add` and no `herdr plugin link`: granting a
        machine-wide permission is a gesture that belongs to the human at the
        keyboard. The ONE exception is the warm-up (`_warm_opencode`), and it stays
        inside the rule's intent: it changes nothing on the machine, only opencode's
        own cache for this project, and it is aborted on purpose.

4. In `workspace_init` wird die Zeile, die `_warnings(…)`, `state_warnings(templates)`
   und `warnings` zusammensetzt, zu:

            _install, found = machine_report(
                base, data=data, overlay_auto=overlay_auto, runner=runner
            )
            warnings = found + state_warnings(templates) + warnings

@call patch("lean_herdr/workspace.py", "the command choices and description in build_parser, and the up branch in main")

5. `p.add_argument("command", choices=("up", "init"))` wird
   `p.add_argument("command", choices=("up", "init", "check"))`; die `description` wird
   `"Set the project up, check it, or start the orchestrator from its config."`.
6. Direkt nach dem `elif args.command == "up":`-Zweig:

                elif args.command == "check":
                    # Imported on the call, like `initcmd`: `up` needs none of it.
                    from lean_herdr.checkcmd import workspace_check

                    result = workspace_check()

### Die Tests, die folgen

`tests/test_initcmd.py`:

- Der Import aus `lean_herdr.initcmd` behält nur `WARM_TIMEOUT_S` und `workspace_init`;
  neu `from lean_herdr.checkcmd import TEMP_IGNORE`. Die sieben verschobenen Tests
  sind hier gelöscht.
- Nach der `repo`-Fixture:

        #: A snapshot install that shadows nothing. `init` reports the install through
        #: `checkcmd.install_report`, and this suite runs from the repo venv -- which is,
        #: correctly, no snapshot. tests/test_checkcmd.py tests the real thing.
        HEALTHY_INSTALL = {
            "tool": True,
            "editable": False,
            "package": "/snap/lean_herdr",
            "binary": "/snap/bin/lean-herdr",
            "plugin": None,
        }


        @pytest.fixture(autouse=True)
        def snapshot_install(monkeypatch):
            monkeypatch.setattr(
                "lean_herdr.checkcmd.install_report",
                lambda **_kwargs: (dict(HEALTHY_INSTALL), []),
            )

- In `test_a_healthy_machine_warns_about_nothing` wird der vorhandene Eintrag
  `("plugin", "list")` durch die erste Zeile unten ersetzt (jetzt mit Link), und
  `("config", "show")` kommt neu dazu:

            ("plugin", "list"): "- lean.herdr (lean-herdr context) enabled [local:/snap/lean_herdr/plugin]\n",
            ("config", "show"): (
                '{"user": {"config": {"commit": {"generation": '
                '{"command": "lean-herdr llm generate"}}}}}'
            ),

- Am Ende der Datei:

        def test_init_names_the_generator_through_the_producer_check_uses(monkeypatch, repo):
            """`init` holds no warning list of its own: a machine without the generator is
            named here exactly as `workspace check` names it."""
            monkeypatch.setattr("shutil.which", which_stub(True))
            no_generator = FakeProc(replies={("config", "show"): '{"user": {"config": null}}'})
            warnings = workspace_init(root=repo, runner=no_generator)["warnings"]
            assert any("commit.generation.command" in w for w in warnings), warnings

`tests/test_workspace.py`, direkt nach `test_up_refuses_every_init_flag`:

    def test_main_routes_check_and_refuses_init_flags_there(monkeypatch, capsys):
        """`workspace_check` is imported ON THE CALL, so the seam is `checkcmd`."""
        monkeypatch.setattr(
            "lean_herdr.checkcmd.workspace_check", lambda: {"ok": True, "errors": []}
        )
        assert workspace.main(["check"]) == 0
        assert json.loads(capsys.readouterr().out) == {"ok": True, "errors": []}
        assert workspace.main(["check", "--force"]) == 0
        answer = json.loads(capsys.readouterr().out)
        assert answer["error"] == "usage_error: check does not take --force"

Ohne Änderung grün bleiben `test_every_missing_precondition_becomes_one_line`,
`test_a_machine_without_the_three_binaries_names_every_one_of_them`,
`test_a_check_that_cannot_run_at_all_invents_no_verdict`,
`test_init_never_runs_a_command_that_changes_anything`,
`test_the_gitignore_warning_only_appears_when_auto_is_on` und
`test_an_ignored_overlay_alone_still_warns_about_the_temp_files`.

### Produktions-LOC messen

    uv run python - <<'EOF'
    import ast
    import io
    import tokenize
    from pathlib import Path

    SKIP = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER}

    def production_loc(path: Path) -> int:
        source = path.read_text(encoding="utf-8")
        docs = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                first = node.body[0] if node.body else None
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                    docs.update(range(first.lineno, first.end_lineno + 1))
        lines = set()
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type not in SKIP:
                lines.update(range(token.start[0], token.end[0] + 1))
        return len(lines - docs)

    for path in sorted(Path("lean_herdr").glob("*.py")):
        count = production_loc(path)
        print(f"{count:5d} {path}" + ("  <-- over 800" if count > 800 else ""))
    EOF

Expected: keine Zeile mit `over 800`.

### Verify & Close

@call verify(lean_herdr/checkcmd.py lean_herdr/initcmd.py lean_herdr/workspace.py tests/test_checkcmd.py tests/test_initcmd.py tests/test_workspace.py)
@call review_change()
@call gate(lean_herdr/checkcmd.py lean_herdr/initcmd.py lean_herdr/workspace.py tests/test_checkcmd.py tests/test_initcmd.py tests/test_workspace.py)
@call commit("lean_herdr/checkcmd.py lean_herdr/initcmd.py lean_herdr/workspace.py tests/test_checkcmd.py tests/test_initcmd.py tests/test_workspace.py", "feat(workspace): add check, and let init report the machine through the producer check uses")
@call remember_decision("Since task 7 of the hardening plan: lean_herdr/checkcmd.py owns every read-only machine check (_read, _check_*, TEMP_IGNORE, TEMP_PROBE, install_report, _check_generator, _linked_plugin, _check_temp_leftovers) and machine_report, shared by workspace_init and workspace_check; `lean-herdr workspace check` is the third word beside up and init.")
@phase-end

@phase "task-8"
## Task 8: Verben `llm` und `plugin`, Manifest ins Paket, `bin/herdr-llm` raus

**Files:** `lean_herdr/cli.py`, `lean_herdr/__main__.py`, `lean_herdr/llm.py`,
`lean_herdr/openrouter.py`, `lean_herdr/catalog.py`, `lean_herdr/settings.py`,
`tests/test_cli.py`, `tests/test_manifest.py`, `tests/test_catalog.py`,
`tests/test_openrouter.py`, `tests/test_llm.py`. Create
`lean_herdr/plugin/herdr-plugin.toml`. Delete `bin/herdr-llm`.
**Nicht:** das Root-`herdr-plugin.toml` — es bleibt bis Task 10 unverändert liegen.

**Interfaces — Produces:**
`cli.VERBS` bekommt `"llm": "lean_herdr.llm"` und `"plugin": "lean_herdr.__main__"`.
`cli.PLAIN_VERBS = {"llm": 1, "plugin": 0}` — scheitert der Import eines dieser
Verben, schreibt `_crashed` **nichts** auf stdout, sondern
`lean-herdr <verb>: cannot run <module>: <exc>` auf stderr, und endet mit diesem
Exit-Code. `llm.build_parser` hat `prog="lean-herdr llm"`, jedes stderr-Präfix
`herdr-llm:` wird `lean-herdr llm:`. Jeder Manifest-Befehl ist
`["lean-herdr", "plugin", "<sub>"]`.

@call recall_context("hardening plan task 0b: does Herdr read the manifest live, and in which cwd")

Beide Ausgänge von 0b lassen diesen Task unverändert: das Root-Manifest bleibt, der
Plugin-Link zeigt bis Task 10 auf den Checkout.

@read lean_herdr/cli.py mode=full
@read lean_herdr/__main__.py mode=full
@read tests/test_manifest.py mode=full

@call tdd(tests/test_cli.py::test_a_plain_verb_that_dies_on_import_writes_nothing_on_stdout)
@call tdd(tests/test_manifest.py::test_every_manifest_command_runs_the_installed_plugin_verb)

Rot heißt hier: stdout trägt eine `cli_crashed`-JSON-Zeile; dann
`FileNotFoundError` für `lean_herdr/plugin/herdr-plugin.toml`.

### Die Tests

In `tests/test_cli.py`, am Ende:

    def test_llm_prereview_hands_its_exit_code_through(monkeypatch):
        """Exit 1 is the ruling `reject` -- the one verb whose exit code carries a result."""
        monkeypatch.setattr("lean_herdr.llm.main", lambda argv: 1 if argv[:1] == ["prereview"] else 0)
        assert cli.main(["llm", "prereview", "--order", "x"]) == 1
        assert cli.main(["llm", "generate"]) == 0


    @pytest.mark.parametrize(("verb", "code"), [("llm", 1), ("plugin", 0)])
    def test_a_plain_verb_that_dies_on_import_writes_nothing_on_stdout(
        monkeypatch, capsys, verb, code
    ):
        """On `llm generate` a JSON line on stdout would become the commit message.

        `llm` ends loud, with 1, at the first commit -- like the argparse usage error
        `llm.main` already lets through. `plugin` ends with 0: a handler never breaks
        anything, and stderr is the plugin log.
        """
        monkeypatch.setitem(cli.VERBS, verb, "lean_herdr.no_such_module")
        assert cli.main([verb, "generate"]) == code
        out, err = capsys.readouterr()
        assert out == ""
        assert err.startswith(f"lean-herdr {verb}: "), err

`test_each_verb_reaches_its_own_main_with_the_rest` läuft ohne Änderung über die
beiden neuen Verben mit.

`tests/test_manifest.py`:

- `import ast` entfällt, `import sys` kommt dazu.
- `MANIFEST = ROOT / "lean_herdr" / "plugin" / "herdr-plugin.toml"`.
- Die Konstante `OLDEST_PYTHON` samt `#:`-Kommentar entfällt.
- `test_the_package_parses_on_the_python3_the_manifest_may_meet` wird ganz ersetzt durch:

        def test_every_manifest_command_runs_the_installed_plugin_verb():
            """The manifest starts no bare `python3` any more -- the snapshot's own binary.

            A host `python3` had to find the package through the linked checkout and
            parse it on whatever interpreter the host carried. `lean-herdr plugin <sub>`
            runs under the interpreter the package was installed with, so the syntax
            floor is `requires-python` alone. That `<sub>` has a handler is
            `test_no_handler_without_subcommand`'s job.
            """
            for entry in manifest()["events"] + manifest()["actions"]:
                assert entry["command"][:2] == ["lean-herdr", "plugin"], entry
                assert len(entry["command"]) == 3, entry


        def test_python_m_from_the_checkout_still_reaches_the_handlers():
            """Without the `sys.path` insert, `python -m lean_herdr` works from the repo root."""
            proc = subprocess.run(
                [sys.executable, "-m", "lean_herdr", "does-not-exist"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            assert proc.returncode == 0, proc.stderr
            assert "unknown subcommand" in proc.stderr

- Der Docstring von `test_the_entry_point_still_points_at_a_callable_main` wird:

            """`lean-herdr <verb>` is the ONLY way in outside this checkout.

            The manifest spawns `lean-herdr plugin <sub>`, worktrunk spawns
            `lean-herdr llm generate`, and every role prompt and every operator types
            `lean-herdr`. That name exists solely because of this one pyproject line --
            rename the module or the function and nothing in the tree notices until an
            installed environment does.
            """

- In `test_the_wheel_ships_the_templates` wird
  `wanted = {f"lean_herdr/templates/{name}" for name in LAYOUT}` zu

            wanted = {f"lean_herdr/templates/{name}" for name in LAYOUT}
            wanted.add("lean_herdr/plugin/herdr-plugin.toml")

  und der erste Docstring-Satz zu „`init` writes files OUT of the package, and Herdr
  links the manifest inside it. A wheel without them is silent."
- In `test_plugin_link_produces_no_warning` wird `str(ROOT)` im `link`-Aufruf zu
  `str(MANIFEST.parent)`, und der Docstring bekommt einen zweiten Absatz:

            It re-links the operator's real `lean.herdr` to this checkout's package
            directory. Run it on purpose, after the plugin was moved to the snapshot --
            never as part of a gate.

  **Integrationstests laufen in diesem Task nicht** (`-m integration` bleibt aus).

Guard-Docstrings, nur Text:

- `tests/test_catalog.py`, `test_llm_does_not_import_the_catalogue`: „`bin/herdr-llm`
  runs on the system interpreter at every commit in" wird „`lean-herdr llm generate`
  starts at every commit in".
- `tests/test_openrouter.py`, `test_openrouter_imports_nothing_from_lean_herdr`:
  „`bin/herdr-llm` loads this on the system interpreter at every commit, so anything" wird
  „`lean-herdr llm generate` loads this at every commit, so anything".
- `tests/test_llm.py`: in `test_an_undecodable_repo_root_costs_the_defaults_not_the_run`
  wird „`bin/herdr-llm` / `prereview`" (über den Zeilenumbruch) zu
  „`lean-herdr llm prereview`"; in `test_prereview_itself_refuses_to_judge_without_an_order`
  wird „`bin/herdr-llm prereview`" zu „`lean-herdr llm prereview`".

### Der Fix

@call patch("lean_herdr/cli.py", "the module docstring, VERBS, USAGE and _crashed")

1. Der Modul-Docstring wird:

        """One binary, six verbs: `lean-herdr dispatch | llm | models | plugin | report | workspace`.

        A router, nothing more. Every verb hands off to a `main(argv) -> int` that
        already exists and already keeps its own contract. Four keep the house
        contract: one JSON line on stdout, `ok` as the only truth, exit ALWAYS 0. Two
        do not, on purpose, because nobody reading JSON calls them:

        * `llm` is worktrunk's commit generator and the manual pre-review. `generate`
          writes the message on stdout and exits 0; `prereview` exits 1 on `reject`.
        * `plugin` is Herdr's event and action handler: nothing on stdout, failures
          on stderr -- the plugin log -- and exit 0.

        The one rung this file keeps is the one no delegate can reach: the import
        itself, which runs before that delegate's own `except` clauses exist. For the
        two plain verbs that rung writes NO JSON line -- on `llm generate` it would
        become the commit message.

        The verb modules are imported ON THE CALL, not up here. `lean_herdr.
        workspace` reaches `lean_herdr.dispatch` and from there `ordercmd`; a
        top-level import of all three would make this router the place where
        that whole chain resolves, and a bare `lean-herdr report next` -- the
        call a worker makes on every single step -- would pay for it.
        """

2. `VERBS` und `USAGE` werden:

        VERBS = {
            "dispatch": "lean_herdr.dispatch",
            "llm": "lean_herdr.llm",
            "models": "lean_herdr.catalog",
            "plugin": "lean_herdr.__main__",
            "report": "lean_herdr.report",
            "workspace": "lean_herdr.workspace",
        }

        #: The two verbs outside the JSON contract, and the exit code an import crash
        #: ends them with. `llm` 1: a broken install is loud at the first commit.
        #: `plugin` 0: a handler never breaks anything.
        PLAIN_VERBS = {"llm": 1, "plugin": 0}

        USAGE = (
            "usage: lean-herdr {dispatch|llm|models|plugin|report|workspace} ...\n"
            "  dispatch, models, report, workspace: one JSON line on stdout, exit 0\n"
            "  llm generate: the commit message on stdout, exit 0\n"
            "  llm prereview: the ruling on stdout, exit 1 on reject\n"
            "  plugin <sub>: Herdr's handlers -- nothing on stdout, errors on stderr, exit 0\n"
        )

   Der `#:`-Kommentar über `VERBS` bleibt.

3. In `_crashed`, als erste Anweisung nach dem Docstring:

            if verb in PLAIN_VERBS:
                sys.stderr.write(f"lean-herdr {verb}: cannot run {VERBS[verb]}: {exc}\n")
                return PLAIN_VERBS[verb]

   und als letzter Docstring-Absatz: „The two plain verbs get a stderr line instead,
   and their own exit code (PLAIN_VERBS)."

@call patch("lean_herdr/__main__.py", "the module docstring, the pathlib import and the sys.path insert")

4. Docstring:

        """Subcommand dispatch for the plugin handlers: `lean-herdr plugin <sub>`.

        A handler never breaks anything: every path ends with exit 0, every exception
        lands on stderr — and thus in `herdr plugin log list --plugin lean.herdr`.
        `python -m lean_herdr <sub>` from a checkout reaches the same `main`.
        """

5. `from pathlib import Path` und `sys.path.insert(0, str(Path(__file__).resolve().parents[1]))`
   samt Leerzeile entfallen. `import sys` bleibt.

@call patch("lean_herdr/llm.py", "the module docstring's stdlib paragraph, the file_settings docstring, build_parser's prog")

6. Modul-Docstring: „Stdlib plus `worktree.find_worktree()`, and no entry in
   herdr-plugin.toml: this is a library and a CLI, not a plugin handler. No third-party
   dependency -- the module starts on every commit" wird „Stdlib plus
   `worktree.find_worktree()`, reached as `lean-herdr llm` and never as a plugin handler.
   No third-party dependency -- the project declares `dependencies = []`, and the module
   starts on every commit".
7. `file_settings`-Docstring: „worktrunk starts `bin/herdr-llm generate` in EVERY
   repository" wird „worktrunk starts `lean-herdr llm generate` in EVERY repository".
8. `prog="herdr-llm"` wird `prog="lean-herdr llm"`.
9. Jedes `herdr-llm:` in einem stderr-Text wird `lean-herdr llm:` —
   `@edit lean_herdr/llm.py "herdr-llm:" "lean-herdr llm:" replace_all`.

@call patch("lean_herdr/openrouter.py", "the first paragraph after the summary line of the module docstring")

10. Der Absatz „Two consumers, and the split is the point. …" bis „… only one of them
    needs a key." wird:

        Two consumers, and the split is the point. `llm.py` starts on every commit:
        worktrunk runs `lean-herdr llm generate` as `commit.generation.command` in
        every repository on this machine, and the project declares
        `dependencies = []` -- so no httpx and no tomli_w, and an import that stays
        small. `catalog.py` asks the same host for its model list. Both need the
        base url and the same never-raising error profile; only one of them needs a
        key.

@call patch("lean_herdr/catalog.py", "one sentence in the module docstring and one in the write_overlay docstring")

11. Modul-Docstring: „The commit path runs on the system interpreter at every commit in
    every repository on this machine; catalogue code has no business there." wird „The
    commit path starts at every commit in every repository on this machine; catalogue
    code has no business on it."
12. `write_overlay`-Docstring: „and `tomli_w` is ABSENT on the system interpreter this
    project's commit path runs on." wird „and the project declares
    `dependencies = []`, so there is no `tomli_w` to reach for."

@call patch("lean_herdr/settings.py", "the llm_settings docstring")

13. „it serves `bin/herdr-llm generate`, where" wird „it serves
    `lean-herdr llm generate`, where".

Erst nach den Schritten 1–13:

    git grep -n "herdr-llm" -- lean_herdr tests ':!lean_herdr/templates/config.toml'

Expected: keine Treffer. Der Kommentar in `lean_herdr/templates/config.toml` bleibt bis
Task 9 stehen: hier geändert, würde `tests/test_templates.py` rot, weil erst Task 9 die
Kopie und ihren Lock-Eintrag nachzieht.

### Das Manifest im Paket

`lean_herdr/plugin/herdr-plugin.toml`:

    id = "lean.herdr"
    name = "lean-herdr context"
    version = "0.1.0"
    min_herdr_version = "0.8.0"
    description = "Shows the lean-ctx context per pane and workspace and carries it across server restarts."
    platforms = ["linux", "macos"]

    # Every command is the installed snapshot's `lean-herdr plugin <sub>`: code and
    # manifest come out of one package, and no bare `python3` has to find it.
    #
    # There is no startup event: after a server restart Herdr recreates the
    # workspaces, and that is exactly the moment to resume.
    [[events]]
    on = "workspace.created"
    command = ["lean-herdr", "plugin", "workspace-created"]

    [[events]]
    on = "workspace.focused"
    command = ["lean-herdr", "plugin", "workspace-created"]

    # Fires after `claude --resume` as well.
    [[events]]
    on = "pane.agent_detected"
    command = ["lean-herdr", "plugin", "pane-detected"]

    [[events]]
    on = "pane.agent_status_changed"
    command = ["lean-herdr", "plugin", "status-changed"]

    # Delivery is a deliberate gesture, never automatic: prompting from a handler
    # would fire during agent_blocked and interrupt typing.
    [[actions]]
    id = "inject"
    title = "Send the lean-ctx digest to this pane's agent"
    contexts = ["pane"]
    command = ["lean-herdr", "plugin", "inject"]

    # The one-keystroke bootstrap: open a pane with the minimal profile and start
    # the opencode orchestrator in it. Workspace context, because the new pane
    # belongs in THIS workspace.
    [[actions]]
    id = "bootstrap"
    title = "Start the orchestrator in this workspace"
    description = "Creates a pane with LEAN_CTX_TOOL_PROFILE=minimal and starts the opencode orchestrator in it."
    contexts = ["workspace"]
    command = ["lean-herdr", "plugin", "bootstrap"]

### `bin/herdr-llm` entfernen

    git rm bin/herdr-llm
    git grep -n "bin/herdr-llm" -- lean_herdr tests pyproject.toml ':!lean_herdr/templates/config.toml'

Expected: keine Treffer. README und `lean_herdr/templates/config.toml` folgen in Task 9.

Ohne Änderung grün bleiben `test_every_event_is_known_and_in_dot_notation`,
`test_no_handler_without_subcommand`, `test_main_survives_a_missing_handlers_module`,
`test_a_verb_whose_module_dies_on_import_is_still_one_json_line`,
`test_help_is_plain_text_for_a_human` und `test_llm_does_not_import_the_catalogue`.

### Verify & Close

@call verify(lean_herdr/ tests/ bin/)
@call review_change()
@call gate(lean_herdr/cli.py lean_herdr/__main__.py lean_herdr/llm.py lean_herdr/openrouter.py lean_herdr/catalog.py lean_herdr/settings.py tests/)
@call commit("lean_herdr/cli.py lean_herdr/__main__.py lean_herdr/llm.py lean_herdr/openrouter.py lean_herdr/catalog.py lean_herdr/settings.py lean_herdr/plugin/herdr-plugin.toml bin/herdr-llm tests/test_cli.py tests/test_manifest.py tests/test_catalog.py tests/test_openrouter.py tests/test_llm.py", "feat(cli): route llm and plugin through lean-herdr, ship the plugin manifest in the package, and drop bin/herdr-llm")
@phase-end

@phase "task-9"
## Task 9: README, Template-Kommentar samt Lock, `.gitignore`

**Files:** `README.md`, `lean_herdr/templates/config.toml`,
`.lean-ctx/lean-herdr/config.toml`, `.lean-ctx/lean-herdr/templates.lock.json`,
`.gitignore`, `tests/test_config_files.py`.

**Interfaces:** keine. Operator-Doku auf Englisch.

@call recall_context("hardening plan task 0a: the snapshot source for uv tool install --reinstall")

**SOURCE** unten ist die Quelle aus 0a, mit `/home/you/` statt des echten Home-Pfads —
die Schreibweise, die das README schon benutzt. Erwartet:
`"lean-herdr @ git+file:///home/you/Scripts/lean-herdr@main"`. Ergab 0a den
Wheel-Fallback, steht an beiden Stellen stattdessen der Dreizeiler aus 0a (Worktree,
`uv build --wheel`, `uv tool install --reinstall dist/lean_herdr-*.whl`).

@read README.md mode=full

### Der Test zuerst

@call tdd(tests/test_config_files.py::test_readme_no_longer_names_the_old_generator_script)

Rot heißt hier: `AssertionError` — das README nennt `bin/herdr-llm` noch dreimal.

In `tests/test_config_files.py`: im Tupel von `test_readme_names_every_runtime_dependency`,
direkt nach `"ORCHESTRATOR = orch",`:

            # One snapshot for every project: the generator worktrunk runs, the one
            # command that says whether it all fits, and the gesture that updates it.
            "lean-herdr llm generate",
            "lean-herdr workspace check",
            "--reinstall",

Am Ende der Datei:

    def test_readme_no_longer_names_the_old_generator_script():
        """`bin/herdr-llm` is gone; a README line naming it sends the operator nowhere."""
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        assert "bin/herdr-llm" not in text

### Das README

@call patch("README.md", "the runtime-dependency table, the commit generator block, the prereview line, the models ignore lines, the plugin bullet, the setting-up section, a new Updating section and Development")

1. Tabellenzeile `lean-herdr` wird:

        | `lean-herdr` (this project) | one binary, six verbs: dispatch, llm, models, plugin, report, workspace | `uv tool install --reinstall SOURCE` — a snapshot of `main`, see [Updating](#updating) |

2. Tabellenzeile `python3` wird:

        | `python3` | runs the Claude-Code hooks of the policy adapter | your distribution |

3. Im Generator-Block wird
   `command = "/home/you/Scripts/lean-herdr/bin/herdr-llm generate"` zu
   `command = "lean-herdr llm generate"`. `stage = "none"` und sein maschinenweiter
   Hinweis bleiben. Im `[llm]`-Absatz weiter unten wird der Satz „Either file broken or
   absent costs the defaults, never the commit." zu „A broken `models.auto.toml` costs
   the overlay alone, a broken `config.toml` the defaults -- neither costs the commit."

4. Der Absatz „**The path is absolute, never `bin/herdr-llm`.** …" bis „… so one
   absolute path serves every repository sensibly." wird:

        `lean-herdr` resolves on the PATH of every repository -- the installed
        snapshot, never this checkout -- and a failing generation command is fatal,
        not a silent fallback: it would break `wt step commit` and `wt merge` in all
        your other projects. The generator is repo-agnostic: it only formats what
        worktrunk hands it on stdin. `lean-herdr workspace check` says whether the
        effective command is this one.

   Im Absatz darauf wird „The absolute path works either way and stays the
   recommendation." zu „The machine-wide line works either way and stays the
   recommendation."

5. `bin/herdr-llm prereview -C <worktree> --order "<what it was supposed to do>"` wird
   `lean-herdr llm prereview -C <worktree> --order "<what it was supposed to do>"`.

6. In „Keeping the model current" wird der Block von „`apply` writes
   `.lean-ctx/lean-herdr/models.auto.toml`, which loses to" bis zur eingerückten
   Ignore-Zeile zu:

        `apply` writes `.lean-ctx/lean-herdr/models.auto.toml`, which loses to
        `[llm]` in `config.toml`: an explicit `model` there survives every check,
        and `apply` rewrites a broken overlay. The file is machine-local, and so are
        the temp files its writer and the template lock's writer leave after a hard
        kill -- add both lines to `.gitignore`:

            .lean-ctx/lean-herdr/models.auto.toml
            .lean-ctx/lean-herdr/.tmp-*

7. In „What else ships here" wird der Punkt `herdr-plugin.toml` zu:

        - `lean_herdr/plugin/herdr-plugin.toml` — the Herdr plugin: it shows the
          lean-ctx context per pane and workspace, carries it across server restarts,
          and offers the one-keystroke orchestrator bootstrap. It ships inside the
          package, so code and manifest come out of one snapshot. Link the installed
          copy, `herdr plugin link <tool-venv>/lib/python3.14/site-packages/lean_herdr/plugin`
          -- `lean-herdr workspace check` prints the exact path.

8. In „Setting up a project", direkt nach „… It needs a git repository and does not
   create one.":

        Three of the eight carry this project's own commands: `.config/wt.toml` runs
        them as the pre-merge gate, and `.claude/settings.json` and `opencode.jsonc`
        let the builder run the same two first. Name them on the first run:

            lean-herdr workspace init --test "cargo test" --lint "cargo clippy"

        Without the flags the gate is `uv run pytest` and `uv run ruff check`. A value
        is a whole command of letters, digits, spaces and `._/=+,@-`; how far it opens
        the builder's gate is your call.

        `init` records what it wrote in `.lean-ctx/lean-herdr/templates.lock.json` --
        commit it, like the role prompts. With it, `lean-herdr workspace init --update`
        rewrites only the files nobody edited since, and leaves a hand edit where it
        is, naming it. `--force` and `--update` exclude each other. The lock's writer
        needs the ignore line for its temp file:

            .lean-ctx/lean-herdr/.tmp-*

        `lean-herdr workspace check` answers, without starting or writing anything,
        whether `up` and `dispatch` will run here and what gets quietly worse: the
        config, each template's state, the install, the plugin link, the commit
        generator and the ignore rules.

   Der Absatz „Two of the eight carry this project's own answers and are meant to be
   edited: …" bis „… so you find out early." entfällt.

9. Neuer Abschnitt direkt vor `## Bootstrap`:

        ## Updating

        `lean-herdr` on the PATH is a snapshot of `main`, not this checkout. After a
        merge, take the new snapshot on purpose -- nothing reinstalls itself:

            uv tool install --reinstall SOURCE
            lean-herdr workspace check

        Then, in every project that uses it:

            lean-herdr workspace init --update

        If that rewrote `.config/wt.toml`, the changed gate command needs a fresh
        `wt config approvals add` -- until then worktrunk skips it silently.

        `workspace check` also names what shadows the snapshot: an activated venv
        whose `bin/` comes first on the PATH -- this repository's own `.venv`
        included -- and a `PYTHONPATH` that puts another `lean_herdr` ahead of the
        installed one. A reinstall on a new Python minor version moves the package
        path; `check` then prints the new `herdr plugin link` line.

10. „## Development" wird:

        ## Development

            uv sync --dev
            uv run pytest -q
            uv run ruff check

        `uv run lean-herdr …` runs this checkout; the bare `lean-herdr` is the
        installed snapshot. `uv run lean-herdr workspace check` therefore warns that
        there is no tool venv and that the install is editable -- correctly.

        Tests with `-m integration` need real binaries and do not run in CI.

`SOURCE` an beiden Stellen durch die Quelle aus 0a ersetzen (mit Anführungszeichen, wie
dort gemessen). Danach:

    git grep -n "bin/herdr-llm\|SOURCE" -- README.md

Expected: keine Treffer.

### Template-Kommentar und Lock

@call patch("lean_herdr/templates/config.toml", "the comment line naming bin/herdr-llm under [llm]")

11. `# through bin/herdr-llm, and the pre-review judge behind --prereview.` wird
    `# through lean-herdr llm generate, and the pre-review judge behind --prereview.`

Die Kopie und ihr Lock-Eintrag ziehen nach — genau die Geste, für die `--update` da ist:

    uv run lean-herdr workspace init --update

Expected: `"written": [".lean-ctx/lean-herdr/config.toml"]`, jede Datei in `templates`
`"current"`.

### `.gitignore`

@call patch(".gitignore", "the models.auto.toml block at the end")

12. Nach `.lean-ctx/lean-herdr/models.auto.toml`:

        # temp files of the overlay and template-lock writers, left only by a hard kill
        .lean-ctx/lean-herdr/.tmp-*

    git check-ignore -v .lean-ctx/lean-herdr/.tmp-models.auto.toml.probe
    git check-ignore -v .lean-ctx/lean-herdr/templates.lock.json

Expected: die erste nennt die neue `.gitignore`-Zeile; die zweite gibt nichts aus, Exit 1.

    uv run lean-herdr workspace check

Expected: `"errors": []`. Unter `warnings` erwartet und hingenommen: kein Tool-venv,
editable, `lean_herdr is imported from …/lean_herdr, outside …/.venv`, der Plugin-Link
auf den Checkout, der fehlende Generator, das offene Approval — Task 10 räumt sie weg. **Keine** Warnung zu `.lean-ctx/lean-herdr/.tmp-*`, keine zu
einem Template.

### Verify & Close

@call verify(README.md lean_herdr/templates/config.toml .lean-ctx/lean-herdr/ .gitignore tests/test_config_files.py)
@call gate(tests/test_config_files.py)
@call commit("README.md lean_herdr/templates/config.toml .lean-ctx/lean-herdr/config.toml .lean-ctx/lean-herdr/templates.lock.json .gitignore tests/test_config_files.py", "docs(readme): one snapshot for every project -- install, generator, plugin link, check and updating")
@phase-end

@phase "task-10"
## Task 10: Migration dieses Repos und Abnahme — **nach dem Merge**

**Files:** `herdr-plugin.toml` (Root, gelöscht). Sonst nur Maschinen-Zustand:
Tool-venv, Plugin-Link, `~/.config/worktrunk/config.toml`, wt-Approvals.

**Voraussetzung:** der Branch ist nach `main` gemergt; dieser Task läuft im
`main`-Checkout `/home/tholo/Scripts/lean-herdr`. Braucht einen laufenden Herdr-Server
(H7). Schritte 3 und 5 sind Gesten des Betreibers — der Controller fragt, bevor er sie
ausführt.

@call recall_context("hardening plan task 0: snapshot source (0a) and the herdr plugin unlink line (0d)")

### 1. Snapshot

    uv tool install --reinstall SOURCE
    lean-herdr workspace check

`SOURCE` ist die Quelle aus 0a mit dem echten Pfad (`/home/tholo/…`).
Expected: `"install"` mit `"tool": true`, `"editable": false`, `"package"` unter
`/home/tholo/.local/share/uv/tools/lean-herdr/`.

### 2. Plugin auf den Snapshot umlinken, Root-Manifest löschen

    lean-herdr workspace check | python3 -c 'import json, sys; print(json.load(sys.stdin)["install"]["package"] + "/plugin")'

Den ausgegebenen Pfad als `PLUGIN` merken. Dann, mit der Unlink-Zeile aus 0d:

    herdr plugin unlink …
    herdr plugin link "$PLUGIN"
    herdr plugin list --plugin lean.herdr
    herdr plugin list

Expected: `- lean.herdr (lean-herdr context) enabled [local:<PLUGIN>]`; keine Zeile mit
`warning:`.

    git rm herdr-plugin.toml
    uv run pytest -q
    uv run ruff check
    uv run pytest -q -m integration tests/test_manifest.py::test_the_wheel_ships_the_templates

Expected: PASS, `All checks passed!`, PASS. **Nicht**
`test_plugin_link_produces_no_warning` — er linkt `lean.herdr` zurück auf das
Paket-Verzeichnis des Checkouts.

@call commit("herdr-plugin.toml", "chore(plugin): drop the root manifest now that Herdr links the installed package")

### 3. Commit-Generator (Geste des Betreibers)

Der Betreiber entscheidet, ob `[commit] stage = "none"` dazukommt — maschinenweit.
`~/.config/worktrunk/config.toml` bekommt (neu anlegen oder von Hand ergänzen):

    [commit.generation]
    command = "lean-herdr llm generate"

    lean-herdr workspace check

Expected: keine Warnung mit `commit.generation.command`.

### 4. Templates dieses Repos

Expected in derselben Ausgabe: jede Datei unter `"templates"` ist `"current"`.

### 5. Approvals (Geste des Betreibers)

    wt config approvals add
    wt config approvals list --format json
    lean-herdr workspace check

Expected: `"state": "approved"` — das schließt den neuen `lint`-Befehl ein; in `check`
keine Approval-Warnung, `"errors": []`.

### 6. Abnahme (Spec §1)

    git -C /home/tholo/Scripts/lean-herdr switch -c probe/acceptance
    A=/tmp/lean-herdr-acceptance
    rm -rf "$A" && git init -q "$A"
    cd "$A" && git commit --allow-empty -qm seed
    lean-herdr workspace init
    lean-herdr workspace check

Expected: `init` mit `"ok": true` und acht Dateien unter `written`; `check` mit
`"errors": []`, `"install": {"tool": true, "editable": false, …}` und `"package"` im
Tool-venv — obwohl der Checkout auf `probe/acceptance` steht.

    wt config approvals add
    lean-herdr workspace up

Expected: `"ok": true` mit `pane` und `agent_id` — oder `"already_running": true`, weil
der Duplikat-Check serverweit ist.

    echo hello > hello.txt
    git add hello.txt
    wt step commit
    git log -1 --format=%s
    wt config show --full

Expected: `wt step commit` endet mit Exit 0; `wt config show --full` meldet die
Commit-Generierung über `lean-herdr llm generate` als funktionsfähig. Die Subject-Zeile
ist eine Conventional-Commit-Zeile — oder, ohne OpenRouter-Key, `Changes to hello.txt`
aus dem Fallback des Generators (dann lief der Generator, nur ohne Modell).

    herdr plugin list --plugin lean.herdr
    herdr plugin list

Expected: `[local:<PLUGIN>]` wie in Schritt 2; keine Zeile mit `warning:`.

Aufräumen: den Orchestrator-Pane des Abnahme-Workspace in Herdr schließen, dann

    git -C /home/tholo/Scripts/lean-herdr switch main
    git -C /home/tholo/Scripts/lean-herdr branch -D probe/acceptance
    rm -rf /tmp/lean-herdr-acceptance

### Close

Jede Abweichung von einem Expected geht als `ctx_session`-Finding an den Betreiber,
bevor aufgeräumt wird.

@call remember_decision("Hardening plan migrated on main: lean-herdr is a non-editable uv tool snapshot of main, lean.herdr links <tool-venv>/lean_herdr/plugin, the root herdr-plugin.toml is gone, worktrunk's user config runs lean-herdr llm generate, and a /tmp repository passed init, check, up and wt step commit while the checkout stood on another branch.")
@phase-end
