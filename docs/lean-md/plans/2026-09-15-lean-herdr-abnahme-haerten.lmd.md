@lean-md
consumer: ai
crp: compact

@var test_cmd default="uv run pytest -q" desc="project test runner command"
@var lint_cmd default="uv run ruff check ." desc="project lint gate"
@import .lean-ctx/lean-md/plan-recipes /

@define py_gate(paths)
<!-- Python pre-commit bar: ruff format on the paths, ruff check, ty check, full test suite -->
1. Run: `uv run ruff check --select I --fix {{ paths }}` — sortiert die Importe (I001).
2. Run: `uv run ruff format {{ paths }}`
3. Run: `uv run ruff check .` — Expected: keine Befunde.
4. Run: `uv run ty check` — Expected: keine Befunde.
5. Run: `uv run pytest -q` — Expected: PASS.
@define-end

@define copies()
<!-- Re-render this repo's checked-in copies and the template lock after a template change -->
1. Run: `uv run lean-herdr workspace init --update`
2. Expected: eine JSON-Zeile mit `"ok": true`; in `templates` steht kein Eintrag `edited`, `diverged`
   oder `unknown`. Sonst: den Eintrag im Bericht nennen und mit BLOCKED enden — eine Handänderung
   an einer Kopie wird nicht überschrieben.
3. Run: `uv run pytest -q tests/test_templates.py` — Expected: PASS.
@define-end

@define loc(names)
<!-- Measure production LOC (physical minus blank, comment and docstring lines) of lean_herdr modules -->
Run (der Block steht ohne Einrückung, so wie er in die Shell geht):

    uv run python - <<'EOF'
    import ast, io, tokenize
    from pathlib import Path
    def prod_loc(path):
        src = Path(path).read_text()
        doc = set()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
                first = node.body[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                    doc.update(range(first.lineno, first.end_lineno + 1))
        code = set()
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER):
                continue
            code.update(range(tok.start[0], tok.end[0] + 1))
        return len(code - doc)
    for name in "{{ names }}".split():
        print(name, prod_loc(f"lean_herdr/{name}.py"))
    EOF

Expected: jede Zahl ≤ 800; die Zahlen im Bericht nennen.
@define-end

# lean-herdr: Befunde der TP2-Abnahme härten

Spec: `docs/specs/2026-09-15-lean-herdr-abnahme-haerten-design.md` v1.1 (§1–§13).
Render je Task: `lean-md render docs/lean-md/plans/2026-09-15-lean-herdr-abnahme-haerten.lmd.md --phase task-N`.

**Hinweis an den Controller:** Task 9 braucht eine laufende Herdr-Sitzung und den Betreiber (Modelle je
Rolle). Sie führt der Controller selbst aus, nicht ein Implementer-Subagent.

## Goal

Nach `workspace up` braucht ein Plan-Lauf keinen Menschen mehr, solange nichts Inhaltliches
eskaliert: `workspace init --trust-claude` erteilt claudes Ordner-Vertrauen einmal für den Root, jeder
Dialog wird als `agent_blocked` gemeldet und nie beantwortet, der Orchestrator darf von `herdr` nur noch
drei Unterbefehle, der Abschluss mergt bei offenem Workspace (`--no-remove`), schließt ihn und entfernt
erst danach, und `workspace check` warnt vor einem nicht vertrauten Root, einem nicht ignorierten
`__pycache__/` und Worker-Rollen ohne `model`.

- **Task 1** — Messungen M3 und M4, vor jedem Code.
- **Task 2** — `lean_herdr/dialogs.py` (`claude_trusts`, `trust_root`, `blocked_dialog`), `Herdr.agent_read`, `start_agent(blocked=)`.
- **Task 3** — `dispatch`: `agent_blocked` beim Start und in jeder Warterunde.
- **Task 4** — `workspace init --trust-claude`; `workspace check` warnt vor einem nicht vertrauten Root.
- **Task 5** — Orchestrator: Dialog-Verbot, herdr-Rechte, Abschluss-Reihenfolge.
- **Task 6** — `workspace check`: `__pycache__/`-Warnung, `model unset`.
- **Task 7** — Briefs und Builder-Prompt: ungetrackte Dateien.
- **Task 8** — README und INSTALL.
- **Task 9** — Abnahme in einem Wegwerf-Repository.

## Architecture

```
lean_herdr/dialogs.py            neu: claude_state_path, claude_trusts, trust_root, blocked_dialog (Task 2)
lean_herdr/herdr.py              + Herdr.agent_read (stdout-Text); start_agent(blocked=) -> agent_blocked (Task 2)
lean_herdr/dispatch.py           ~ dispatch: blocked= an start_agent; await_task prüft je Runde         (Task 3)
lean_herdr/initcmd.py            + workspace_init(trust_claude=) -> claude_trust                       (Task 4)
lean_herdr/workspace.py          + --trust-claude                                                      (Task 4)
lean_herdr/checkcmd.py           + _claude_trust_warnings (Task 4); + PYCACHE_*, _check_pycache_ignored,
                                   _role_warnings: model (Task 6)
lean_herdr/templates/roles/orchestrator.md   ~ Teardown (beide), Escalation, Dialog-Satz               (Task 5)
lean_herdr/templates/opencode.jsonc          ~ orchestrator: drei herdr-Muster statt `herdr *`         (Task 5)
lean_herdr/templates/claude/orchestrator.json + deny herdr agent / herdr pane                          (Task 5)
lean_herdr/templates/briefs/implement.lmd.md, briefs/review.lmd.md, roles/builder.md                   (Task 7)
README.md, INSTALL.md                                                                                   (Task 8)
tests: neu test_dialogs; test_herdr, test_dispatch, test_dispatch_await, test_initcmd, test_workspace,
  test_checkcmd, test_role_prohibitions, test_worker_permissions, test_config_files, test_plan_templates
```

Wiederverwendet: `Herdr.run`/`_result`/`agent_list`, `ordercmd.order_result`, `dispatch._result`,
`checkcmd._run` und das Muster von `_check_temp_ignored`, `settings.settings_for`/`work_roles`,
`tests/doubles.py` (`FakeProc`, `ScriptedProc`, `Clock`, `Completed`, `which_stub`).
Kopien und Lock: `lean-herdr workspace init --update` (`@call copies()`).

## Global Constraints

- Task 1 läuft vor jedem Code. Weicht M3 oder M4 von seinem Expected ab, endet der Plan dort mit BLOCKED.
- Nichts in lean-herdr beantwortet einen Dialog: kein `send-keys`, `send-text`, `agent prompt` oder
  `pane run` in einen Pane, dessen Agent auf `blocked` steht. `start_agent` fragt `blocked` vor
  `_free_pane`; `await_task` fragt vor dem Wecken (E2, E3).
- claudes Zustandsdatei schreibt nur `workspace init --trust-claude`: genau
  `projects.<aufgelöster Root>.hasTrustDialogAccepted`, atomar, jeden anderen Schlüssel unverändert, nie
  eine neue Datei. `dispatch` und `check` lesen sie höchstens (E1, E8, Spec §12).
- Ungetrackte, nicht ignorierte Dateien bleiben ein Merge-Stopp; `init` schreibt keine Ignore-Regeln (E5).
- Der Abschluss entfernt nie mit `--force` und schließt nach einem gescheiterten Merge nichts (E4).
- Jede Template-Änderung zieht Kopien und Lock mit (`@call copies()`); Kopien bleiben byte-identisch.
- Tests rufen weder das echte `herdr`, `wt`, `claude` noch `lean-md` auf; echtes `git` in
  Wegwerf-Repositories ist erlaubt. Kein Test liest oder schreibt die echte Zustandsdatei: wo sie
  berührt wird, zeigt `CLAUDE_CONFIG_DIR` auf ein Temp-Verzeichnis oder `state=` auf eine Temp-Datei.
  Ausnahmen: Task 1 und Task 9.
- `orchestrator.md` nennt keinen Rollennamen
  (`tests/test_role_prohibitions.py::test_the_orchestrator_dispatches_by_work_and_names_no_role`).
- Reihenfolge: Task 2 vor Task 3 und Task 4; Tasks 3–7 vor Task 8; alles vor Task 9.
- Non-Goals (Spec §12): keine Ignore-Regeln aus `init`, kein automatisches Beantworten (auch nicht des
  Vertrauensdialogs), kein claude-Orchestrator mit eigenen Freigaben für `herdr`/`wt`, keine
  Anbieterwahl, keine Änderung an `wt`.
- Keine Datei unter `lean_herdr/` über 800 Produktions-LOC.

@phase "task-1"
## Task 1: Messungen M3 und M4

**Files:** keine im Repository. Wegwerf-Ort: `/tmp/lh-m3`.

**Consumes:** `wt` auf dem PATH. Existiert `/tmp/lh-m3` schon: mit BLOCKED enden — nichts löschen, was
diese Task nicht angelegt hat.

Umgebung für jeden `git`-Aufruf dieser Task: `GIT_CONFIG_GLOBAL=/dev/null`, `GIT_CONFIG_NOSYSTEM=1`
(eine globale Ignore-Datei des Rechners darf das Ergebnis nicht färben).

### Schritt 1 — M4: `check-ignore` ohne Verzeichnis

1. Run: `git init -q -b main /tmp/lh-m3/repo` und `git init -q -b main /tmp/lh-m3/norule`
2. `/tmp/lh-m3/repo/.gitignore` anlegen, Inhalt genau eine Zeile: `__pycache__/`
3. Run: `git -C /tmp/lh-m3/repo check-ignore -v __pycache__/lean-herdr.probe`
   Expected: Exit 0, Ausgabe `.gitignore:1:__pycache__/	__pycache__/lean-herdr.probe`.
4. Run: `git -C /tmp/lh-m3/norule check-ignore -v __pycache__/lean-herdr.probe`
   Expected: Exit 1, keine Ausgabe auf stdout.

### Schritt 2 — M3: Merge mit `--no-remove`, danach `wt remove`

1. Run: `git -C /tmp/lh-m3/repo add .gitignore` und
   `git -C /tmp/lh-m3/repo -c user.name=probe -c user.email=probe@example.invalid commit -q -m init`
2. Run: `git -C /tmp/lh-m3/repo worktree add -q -b m3 /tmp/lh-m3/repo.m3`
3. `/tmp/lh-m3/repo.m3/a.txt` anlegen (Inhalt `a`); Run: `git -C /tmp/lh-m3/repo.m3 add a.txt` und
   `git -C /tmp/lh-m3/repo.m3 -c user.name=probe -c user.email=probe@example.invalid commit -q -m "feat: a"`
4. `/tmp/lh-m3/repo.m3/__pycache__/x.pyc` anlegen (Inhalt beliebig).
5. Run: `wt -C /tmp/lh-m3/repo.m3 merge main --yes --no-commit --no-remove`
   Expected: Exit 0; `git -C /tmp/lh-m3/repo log --oneline main` zeigt `feat: a`;
   `/tmp/lh-m3/repo.m3` existiert noch.
6. Run: `wt -C /tmp/lh-m3/repo remove m3 --yes`
   Expected: Exit 0. Danach, höchstens 30 s lang je Sekunde geprüft (der Block geht ohne die sieben
   Leerzeichen Einrückung in die Shell):

       uv run python -c "import subprocess, time; ok = False
       for _ in range(30):
           wl = subprocess.run(['git', '-C', '/tmp/lh-m3/repo', 'worktree', 'list'], capture_output=True, text=True).stdout
           br = subprocess.run(['git', '-C', '/tmp/lh-m3/repo', 'branch', '--list', 'm3'], capture_output=True, text=True).stdout
           if 'repo.m3' not in wl and not br.strip():
               ok = True
               break
           time.sleep(1)
       print('removed', ok)"

   Expected: `removed True`.

### Schritt 3 — Festhalten und Aufräumen

Weicht eine Erwartung ab: die tatsächliche Ausgabe im Bericht nennen und mit BLOCKED enden.

@call remember_decision("lean-herdr hardening M3/M4: git check-ignore -v __pycache__/lean-herdr.probe matches the __pycache__/ rule with no such directory (exit 0 with the rule, 1 without); wt merge main --yes --no-commit --no-remove succeeds with an ignored __pycache__/ in the worktree and keeps the worktree, and wt remove <branch> --yes afterwards removes worktree and branch in the background.")

Run: `uv run python -c 'import shutil; shutil.rmtree("/tmp/lh-m3")'`
@phase-end

@phase "task-2"
## Task 2: `dialogs.py`, `Herdr.agent_read`, `start_agent(blocked=)`

**Files:** Create `lean_herdr/dialogs.py`, `tests/test_dialogs.py`. Modify `lean_herdr/herdr.py`, `tests/test_herdr.py`.

**Consumes:** Spec §2 (M1, M2): die Zustandsdatei ist `$CLAUDE_CONFIG_DIR/.claude.json` bzw.
`~/.claude.json`, der Schlüssel `projects.<aufgelöster Root>.hasTrustDialogAccepted`; ein Worktree erbt ihn.
`herdr agent read <pane> --source detection --lines N` gibt den Bildschirm als reinen Text auf stdout aus;
`herdr agent list` meldet `agent_status = "blocked"`.

**Interfaces — Produces:**
- `dialogs.claude_state_path(environ: Mapping[str, str] | None = None) -> Path`
- `dialogs.claude_trusts(root: Path, *, state: Path | None = None) -> bool | None`
- `dialogs.trust_root(root: Path, *, state: Path | None = None) -> str` — `"written"`, `"already"` oder `"failed: <why>"`
- `dialogs.blocked_dialog(herdr: Herdr, *, pane: str | None = None, name: str | None = None) -> str | None`
- `Herdr.agent_read(self, target: str, *, source: str = "detection", lines: int = 20) -> str`
- `start_agent(..., blocked: Callable[[str], str | None] | None = None)` → zusätzlich
  `{"ok": False, "error": "agent_blocked", "dialog": <str>}`

### Schritt 1 — Tests zuerst

`tests/test_dialogs.py` anlegen:

    """claude's folder trust and a blocked pane: trust written only on request, a dialog named, never answered."""

    import json
    from pathlib import Path

    import pytest

    from lean_herdr import dialogs
    from lean_herdr.dialogs import (
        CLAUDE_STATE_FILE,
        DIALOG_LINES,
        TRUST_KEY,
        blocked_dialog,
        claude_state_path,
        claude_trusts,
        trust_root,
    )
    from lean_herdr.herdr import Herdr
    from tests.doubles import Completed, FakeProc, which_stub


    def state_file(tmp_path: Path, projects: dict, **rest) -> Path:
        path = tmp_path / "config" / CLAUDE_STATE_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"numStartups": 7, **rest, "projects": projects}), encoding="utf-8")
        return path


    def read(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))


    @pytest.fixture
    def root(tmp_path) -> Path:
        path = tmp_path / "probe"
        path.mkdir()
        return path.resolve()


    def test_the_state_file_follows_claude_config_dir(tmp_path):
        assert claude_state_path({"CLAUDE_CONFIG_DIR": str(tmp_path)}) == tmp_path / ".claude.json"
        assert claude_state_path({}) == Path.home() / ".claude.json"


    def test_claude_trusts_the_root_its_state_accepts(root, tmp_path):
        path = state_file(tmp_path, {str(root): {TRUST_KEY: True}})
        assert claude_trusts(root, state=path) is True


    @pytest.mark.parametrize(
        "projects",
        [{}, {"/elsewhere": {TRUST_KEY: True}}, {"ROOT": {TRUST_KEY: False}}, {"ROOT": {}}],
        ids=["no entry", "another path", "declined", "no key"],
    )
    def test_claude_does_not_trust_a_root_its_state_does_not_accept(root, tmp_path, projects):
        projects = {str(root) if key == "ROOT" else key: value for key, value in projects.items()}
        assert claude_trusts(root, state=state_file(tmp_path, projects)) is False


    @pytest.mark.parametrize(
        "content", [None, "", "not json", "[]"], ids=["missing", "empty", "not json", "a list"]
    )
    def test_an_unreadable_state_is_no_verdict(root, tmp_path, content):
        path = tmp_path / CLAUDE_STATE_FILE
        if content is not None:
            path.write_text(content, encoding="utf-8")
        assert claude_trusts(root, state=path) is None


    def test_trust_root_writes_one_key_and_nothing_else_moves(root, tmp_path):
        other = {"allowedTools": ["Bash(ls)"], TRUST_KEY: False}
        path = state_file(tmp_path, {"/elsewhere": other}, theme="dark")
        assert trust_root(root, state=path) == "written"
        data = read(path)
        assert data["projects"][str(root)] == {TRUST_KEY: True}
        assert data["projects"]["/elsewhere"] == other
        assert data["numStartups"] == 7 and data["theme"] == "dark"
        assert claude_trusts(root, state=path) is True


    def test_trust_root_keeps_the_other_keys_of_the_roots_entry(root, tmp_path):
        path = state_file(tmp_path, {str(root): {"allowedTools": [], TRUST_KEY: False}})
        assert trust_root(root, state=path) == "written"
        assert read(path)["projects"][str(root)] == {"allowedTools": [], TRUST_KEY: True}


    def test_a_state_without_a_projects_table_gets_one(root, tmp_path):
        path = tmp_path / CLAUDE_STATE_FILE
        path.write_text('{"numStartups": 1}', encoding="utf-8")
        assert trust_root(root, state=path) == "written"
        assert read(path) == {"numStartups": 1, "projects": {str(root): {TRUST_KEY: True}}}


    def test_an_already_trusted_root_is_not_written_again(root, tmp_path):
        path = state_file(tmp_path, {str(root): {TRUST_KEY: True}})
        before = path.read_bytes()
        assert trust_root(root, state=path) == "already"
        assert path.read_bytes() == before


    def test_a_missing_state_file_is_never_created(root, tmp_path):
        absent = tmp_path / CLAUDE_STATE_FILE
        assert trust_root(root, state=absent).startswith("failed: no claude state at ")
        assert not absent.exists()


    @pytest.mark.parametrize("content", ["not json", "[]", '{"projects": []}'])
    def test_an_unreadable_state_is_left_as_it_is(root, tmp_path, content):
        path = tmp_path / CLAUDE_STATE_FILE
        path.write_text(content, encoding="utf-8")
        assert trust_root(root, state=path).startswith("failed: ")
        assert path.read_text(encoding="utf-8") == content


    def test_a_failed_write_leaves_the_file_and_no_temp_file_behind(root, tmp_path, monkeypatch):
        path = state_file(tmp_path, {})
        before = path.read_bytes()

        def refuse(*_args, **_kwargs):
            raise OSError("read-only file system")

        monkeypatch.setattr(dialogs.os, "replace", refuse)
        assert trust_root(root, state=path) == "failed: read-only file system"
        assert path.read_bytes() == before
        assert sorted(p.name for p in path.parent.iterdir()) == [CLAUDE_STATE_FILE]


    def test_the_written_file_keeps_its_mode(root, tmp_path):
        path = state_file(tmp_path, {})
        path.chmod(0o640)
        assert trust_root(root, state=path) == "written"
        assert path.stat().st_mode & 0o777 == 0o640


    @pytest.fixture
    def herdr(monkeypatch) -> tuple[Herdr, FakeProc]:
        monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
        proc = FakeProc()
        return Herdr(runner=proc), proc


    def agents(*entries: dict) -> dict:
        return {"result": {"type": "agent_list", "agents": list(entries)}}


    def test_a_blocked_pane_answers_with_its_last_screen_lines(herdr):
        h, proc = herdr
        proc.replies = {
            ("agent", "list"): agents(
                {"name": "builder-feat", "pane_id": "w2:p2", "agent_status": "blocked"}
            ),
            ("agent", "read"): "\n".join(f"line {n}" for n in range(30)) + "\n\n",
        }
        text = blocked_dialog(h, pane="w2:p2")
        assert text == "\n".join(f"line {n}" for n in range(30 - DIALOG_LINES, 30))
        assert proc.called_with("agent", "read", "w2:p2", "--source", "detection")


    def test_a_worker_is_found_by_name_while_waiting(herdr):
        h, proc = herdr
        proc.replies = {
            ("agent", "list"): agents(
                {"name": "reviewer-feat", "pane_id": "w2:p3", "agent_status": "idle"},
                {"name": "builder-feat", "pane_id": "w2:p2", "agent_status": "blocked"},
            ),
            ("agent", "read"): "Allow this command?\n",
        }
        assert blocked_dialog(h, name="builder-feat") == "Allow this command?"
        assert proc.called_with("agent", "read", "w2:p2")


    @pytest.mark.parametrize("status", ["idle", "working", "done", "unknown"])
    def test_any_other_state_is_no_dialog_and_reads_no_screen(herdr, status):
        h, proc = herdr
        proc.replies = {
            ("agent", "list"): agents({"name": "b", "pane_id": "w2:p2", "agent_status": status})
        }
        assert blocked_dialog(h, pane="w2:p2") is None
        assert not proc.called_with("agent", "read")


    def test_a_pane_herdr_does_not_list_is_no_dialog(herdr):
        h, proc = herdr
        proc.replies = {
            ("agent", "list"): agents({"name": "b", "pane_id": "w9:p9", "agent_status": "blocked"})
        }
        assert blocked_dialog(h, pane="w2:p2") is None


    def test_a_blocked_pane_without_screen_text_is_still_blocked(herdr):
        h, proc = herdr
        proc.replies = {
            ("agent", "list"): agents({"name": "b", "pane_id": "w2:p2", "agent_status": "blocked"}),
            ("agent", "read"): Completed(returncode=1),
        }
        assert blocked_dialog(h, pane="w2:p2") == "(herdr returned no screen text)"


    def test_nothing_in_here_sends_input_to_a_pane(herdr):
        h, proc = herdr
        proc.replies = {
            ("agent", "list"): agents({"name": "b", "pane_id": "w2:p2", "agent_status": "blocked"}),
            ("agent", "read"): "Do you trust the files in this folder?\n",
        }
        blocked_dialog(h, pane="w2:p2")
        for verb in (("send-keys",), ("send-text",), ("agent", "prompt"), ("pane", "run")):
            assert not proc.called_with(*verb), proc.flat()

`tests/test_herdr.py` — am Dateiende:

    def test_agent_read_returns_the_plain_text_herdr_prints(fake):
        """`agent read` prints the screen, not JSON (M2): stdout is the answer."""
        screen = " Accessing workspace:\n\n ❯ No, exit\n   Yes, I trust this folder\n"
        fake.replies = {("agent", "read"): screen}
        assert h(fake).agent_read("w2:p2", lines=20) == screen
        assert fake.calls == [
            ["herdr", "agent", "read", "w2:p2", "--source", "detection", "--lines", "20"]
        ]


    def test_agent_read_answers_empty_text_when_herdr_refuses(fake):
        fake.replies = {
            ("agent", "read"): Completed(returncode=1, stderr='{"error": {"code": "agent_not_found"}}')
        }
        assert h(fake).agent_read("w2:p2") == ""


    def test_a_blocked_first_attempt_is_named_before_any_key_goes_into_the_pane(monkeypatch):
        """`ctrl-c` into a dialog is an answer -- the question comes first, and nothing follows it."""
        monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
        clock = Clock()
        proc = ScriptedProc(clock=clock, script={("agent", "start"): (12.0, [{}, STARTED])})
        asked: list[str] = []

        def blocked(pane: str) -> str | None:
            asked.append(pane)
            return "Do you trust the files in this folder?"

        result = start_agent(
            Herdr(runner=proc),
            "orch",
            kind="claude",
            pane="w8:p5",
            retry_timeout_ms=45_000,
            sleep=clock.sleep,
            now=clock.now,
            blocked=blocked,
        )
        assert result == {
            "ok": False,
            "error": "agent_blocked",
            "dialog": "Do you trust the files in this folder?",
        }
        assert asked == ["w8:p5"]
        assert not proc.called_with("pane", "send-keys"), proc.flat()
        assert len([c for c in proc.calls if c[1:3] == ["agent", "start"]]) == 1


    def test_without_a_dialog_the_hung_start_keeps_its_second_attempt(monkeypatch):
        monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
        clock = Clock()
        proc = ScriptedProc(
            clock=clock,
            script={
                ("agent", "start"): (12.0, [{}, STARTED]),
                ("agent", "list"): (0.0, [{"result": {"agents": []}}]),
            },
        )
        result = start_agent(
            Herdr(runner=proc),
            "orch",
            kind="opencode",
            pane="w8:p5",
            retry_timeout_ms=45_000,
            sleep=clock.sleep,
            now=clock.now,
            blocked=lambda _pane: None,
        )
        assert result == {"ok": True, "reply": STARTED, "retried": True}

Run: `uv run pytest -q tests/test_dialogs.py tests/test_herdr.py` — Expected: FAIL (`ModuleNotFoundError:
lean_herdr.dialogs`, `AttributeError: agent_read`, `TypeError: … 'blocked'`).

### Schritt 2 — `Herdr.agent_read`

`lean_herdr/herdr.py`, in `class Herdr` direkt nach der Methode `agent_list` (`herdr.py:306-308`), vor
`pane_process_info`, einfügen:

        def agent_read(self, target: str, *, source: str = "detection", lines: int = 20) -> str:
            """`herdr agent read <TARGET> --source <source> --lines <N>`: the screen, "" on any failure.

            Unlike the commands `run()` serves, it prints the screen as plain text,
            not JSON (measured 2026-09-15) -- stdout is the answer. `detection` is
            the snapshot herdr judges an agent's state on, so a `blocked` agent's
            dialog is in it.
            """
            if not self.is_available():
                return ""
            cmd = [self.binary, "agent", "read", target, "--source", source, "--lines", str(lines)]
            try:
                proc = self._runner(cmd, capture_output=True, text=True, timeout=self.timeout)
            except (OSError, subprocess.SubprocessError, ValueError):
                return ""
            return proc.stdout if proc.returncode == 0 else ""

### Schritt 3 — `start_agent(blocked=)`

`lean_herdr/herdr.py`, `start_agent` (`herdr.py:401`):

1. In der Signatur nach `now: Callable[[], float] = time.monotonic,` einfügen:

           blocked: Callable[[str], str | None] | None = None,

2. Im Docstring die Zeile `    Three answers, because they are three different repairs:` ersetzen durch
   `    Four answers, because they are four different repairs:` und in der Tabelle nach der
   `opencode_stuck`-Zeile einfügen:

           {"ok": False, "error": "agent_blocked", "dialog": ...}  a dialog waits for a human

3. Im Docstring vor der Zeile ``Never raises; the caller reads `ok`.`` einfügen:

        `blocked` is asked once the first attempt ends without an agent, and
        BEFORE `_free_pane`: its `ctrl-c` would be a keystroke into a dialog. A
        text back means a dialog waits for a human -- no second attempt, and
        nothing here answers it. A claude start that meets its folder-trust
        dialog ends after 3.8 s (measured 2026-09-15), just past
        AGENT_START_REFUSAL_S, so without this question it would read as a
        hang. None, the default, skips the question, as the orchestrator's own
        start does.

4. Zwischen `        return {"ok": True, "reply": reply}` (`herdr.py:476`) und
   `    if now() - started_at < AGENT_START_REFUSAL_S:` (`herdr.py:477`) einfügen:

        dialog = blocked(pane) if blocked is not None else None
        if dialog is not None:
            return {"ok": False, "error": "agent_blocked", "dialog": dialog}

### Schritt 4 — `lean_herdr/dialogs.py`

    """Dialogs in worker panes: claude's folder trust, and a dialog named -- never answered.

    A claude worker stops at the folder-trust dialog in every worktree of a
    repository whose root claude does not trust, and a worktree inherits the
    root's trust (measured 2026-09-15). So trust is granted once, by the human,
    through `workspace init --trust-claude` (`trust_root`), and `workspace check`
    names a root without it (`claude_trusts`). Every dialog that still appears
    is reported with its text (`blocked_dialog`). Nothing here sends a key, a
    prompt or any other input into a pane.
    """

    from __future__ import annotations

    import contextlib
    import json
    import os
    import tempfile
    from collections.abc import Mapping
    from pathlib import Path
    from typing import Any

    from lean_herdr.herdr import Herdr

    #: Where claude keeps its global state, the folder trust per project path
    #: included; `$CLAUDE_CONFIG_DIR` moves the file as it moves claude.
    #: Measured 2026-09-15 against Claude Code 2.1.272.
    CLAUDE_CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"
    CLAUDE_STATE_FILE = ".claude.json"
    TRUST_KEY = "hasTrustDialogAccepted"

    #: At most this many screen lines travel in an `agent_blocked` answer.
    DIALOG_LINES = 20

    #: What `herdr agent list` says of an agent that waits for a human.
    BLOCKED = "blocked"


    def claude_state_path(environ: Mapping[str, str] | None = None) -> Path:
        """`$CLAUDE_CONFIG_DIR/.claude.json`, or `~/.claude.json` without the variable."""
        env = os.environ if environ is None else environ
        base = env.get(CLAUDE_CONFIG_DIR_ENV)
        return (Path(base) if base else Path.home()) / CLAUDE_STATE_FILE


    def _read_state(path: Path) -> dict[str, Any] | None:
        """The state file as a JSON object -- None when it is missing, unreadable or no object."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None


    def _key(root: Path) -> str | None:
        """The resolved root path, the key claude writes after the human's "Yes"."""
        try:
            return str(root.resolve())
        except (OSError, RuntimeError):
            return None


    def claude_trusts(root: Path, *, state: Path | None = None) -> bool | None:
        """Does claude trust `root`? None when its state cannot be read -- no verdict.

        Only the root's own key is asked. Whether claude counts a trusted parent
        directory is not measured, so a root below one gets a needless warning
        at worst, never a false all-clear.
        """
        data = _read_state(state if state is not None else claude_state_path())
        key = _key(root)
        if data is None or key is None:
            return None
        projects = data.get("projects")
        entry = projects.get(key) if isinstance(projects, dict) else None
        return isinstance(entry, dict) and entry.get(TRUST_KEY) is True


    def _replace(path: Path, text: str) -> str:
        """`text` into `path` atomically and with the file's own mode: `written` or `failed: <why>`."""
        try:
            mode = path.stat().st_mode & 0o7777
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.lean-herdr-")
        except OSError as exc:
            return f"failed: {exc}"
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
            os.chmod(tmp, mode)
            os.replace(tmp, path)
        except OSError as exc:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            return f"failed: {exc}"
        return "written"


    def trust_root(root: Path, *, state: Path | None = None) -> str:
        """Record the human's trust in `root`: `written`, `already` or `failed: <why>`.

        The gesture behind `workspace init --trust-claude`, and the same record
        claude writes when a human answers "Yes, I trust this folder" in the root.
        Exactly one key is set -- `projects.<root>.hasTrustDialogAccepted` -- and
        every other key stays as it was read. A missing file is not created: claude
        has not run under this config, and a file of lean-herdr's making would not
        be claude's. A claude session that is running may write its own copy back
        over this one; `workspace check` names the root again if it does. Never
        raises.
        """
        path = state if state is not None else claude_state_path()
        key = _key(root)
        if key is None:
            return f"failed: cannot resolve {root}"
        if not path.is_file():
            return f"failed: no claude state at {path} -- start claude once, then run this again"
        data = _read_state(path)
        if data is None:
            return f"failed: {path} holds no JSON object"
        projects = data.setdefault("projects", {})
        if not isinstance(projects, dict):
            return f"failed: {path} carries no projects table"
        entry = projects.get(key)
        if isinstance(entry, dict) and entry.get(TRUST_KEY) is True:
            return "already"
        projects[key] = {**(entry if isinstance(entry, dict) else {}), TRUST_KEY: True}
        return _replace(path, json.dumps(data, indent=2, ensure_ascii=False))


    def blocked_dialog(herdr: Herdr, *, pane: str | None = None, name: str | None = None) -> str | None:
        """The last screen lines of an agent that waits for a human -- None for every other state.

        Found by `pane` at the start, where the pane is all there is, and by `name`
        while waiting, where the order names the worker. `blocked` is herdr's own
        verdict (`agent list`); the text comes from `agent read --source detection`,
        the snapshot that verdict was made on. Reads only: the dialog is reported,
        never answered.
        """
        if pane is None and name is None:
            return None
        for agent in herdr.agent_list():
            hit = agent.get("pane_id") == pane if pane is not None else agent.get("name") == name
            if not hit:
                continue
            if agent.get("agent_status") != BLOCKED:
                return None
            target = str(agent.get("pane_id") or pane or "")
            text = herdr.agent_read(target, lines=DIALOG_LINES)
            lines = [line.rstrip() for line in text.splitlines() if line.strip()]
            return "\n".join(lines[-DIALOG_LINES:]) or "(herdr returned no screen text)"
        return None

Run: `uv run pytest -q tests/test_dialogs.py tests/test_herdr.py` — Expected: PASS.

### Schritt 5 — Messen, prüfen, committen

@call loc("dialogs herdr")
@call verify(lean_herdr/dialogs.py lean_herdr/herdr.py tests/test_dialogs.py tests/test_herdr.py)
@call py_gate(lean_herdr/dialogs.py lean_herdr/herdr.py tests/test_dialogs.py tests/test_herdr.py)
@call commit("lean_herdr/dialogs.py lean_herdr/herdr.py tests/test_dialogs.py tests/test_herdr.py", "feat(dialogs): read and record claude's folder trust, and name a blocked pane")
@phase-end

@phase "task-3"
## Task 3: `dispatch` — `agent_blocked` beim Start und beim Warten

**Files:** Modify `lean_herdr/dispatch.py`, `tests/test_dispatch.py`, `tests/test_dispatch_await.py`.

**Consumes:** Task 2 — `dialogs.blocked_dialog`, `start_agent(blocked=)`.

**Interfaces — Produces:**
- bei einem Dialog beim Start: `{"ok": False, "pane": <pane>, "agent_id": None, "error": "agent_blocked", "dialog": <str>}`
- `await_task` antwortet in der Runde, in der der Worker auf `blocked` steht,
  `{"ok": False, "task_id": …, "state": …, "error": "agent_blocked", "dialog": <str>}` — vor dem Wecken.

### Schritt 1 — Tests zuerst

`tests/test_dispatch.py` — nach `test_a_hung_worker_start_is_opencode_stuck` (`test_dispatch.py:413-430`):

    def test_a_dialog_at_the_start_is_agent_blocked_with_its_text(world):
        """`herdr agent list` says `blocked`: no second attempt, no key, and the dialog travels."""
        h_proc, _ = world
        h_proc.replies = {
            ("pane", "split"): {"result": {"pane": {"pane_id": "w1:p6"}}},
            ("agent", "start"): {},
            ("agent", "list"): {
                "result": {"agents": [{"pane_id": "w1:p6", "agent_status": "blocked"}]}
            },
            ("agent", "read"): "Do you trust the files in this folder?\n",
        }
        result = run_dispatch(
            world,
            reg=registry(),
            waiter=lambda *a, **kw: pytest.fail("no waiter after a dialog"),
        )
        assert result == {
            "ok": False,
            "pane": "w1:p6",
            "agent_id": None,
            "error": "agent_blocked",
            "dialog": "Do you trust the files in this folder?",
        }
        assert not h_proc.called_with("send-keys"), h_proc.flat()
        assert len([c for c in h_proc.calls if c[1:3] == ["agent", "start"]]) == 1

`tests/test_dispatch_await.py`:

- Import: `from tests.doubles import FakeProc, which_stub` → `from tests.doubles import FakeProc, ScriptedProc, which_stub`
- nach `test_a_crashed_worktree_worker_becomes_agent_error_too` einfügen:

      def test_a_blocked_worker_is_named_at_once_and_never_rung(herdr, tmp_path):
          """A dialog is not silence: `agent_blocked` with its text, before the bell, not after the deadline."""
          h, proc = herdr
          proc.replies = {
              ("agent", "list"): {
                  "result": {
                      "agents": [{"name": WORKER, "pane_id": "w1:p6", "agent_status": "blocked"}]
                  }
              },
              ("agent", "read"): "Allow this command?\n",
          }
          clock = iter([0.0, 0.0, 99.0])
          result = wait(
              (h, proc),
              tmp_path,
              created(),
              ("working", WORKER, {}),
              timeout_ms=1_000,
              now=lambda: next(clock),
          )
          assert result["ok"] is False
          assert result["error"] == "agent_blocked"
          assert result["dialog"] == "Allow this command?"
          assert result["state"] == "working"
          assert not proc.called_with("agent", "prompt"), proc.flat()


      def test_a_dialog_that_appears_while_working_ends_the_wait_in_that_round(monkeypatch, tmp_path):
          monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
          working = {
              "result": {"agents": [{"name": WORKER, "pane_id": "w1:p6", "agent_status": "working"}]}
          }
          blocked = {
              "result": {"agents": [{"name": WORKER, "pane_id": "w1:p6", "agent_status": "blocked"}]}
          }
          proc = ScriptedProc(
              script={("agent", "list"): (0.0, [working, blocked])},
              replies={("agent", "read"): "Allow this command?\n"},
          )
          clock = iter([0.0, 0.0, 99.0])
          result = wait(
              (Herdr(runner=proc), proc),
              tmp_path,
              created(),
              ("working", WORKER, {}),
              timeout_ms=1_000,
              now=lambda: next(clock),
          )
          assert result["error"] == "agent_blocked"
          assert result["dialog"] == "Allow this command?"
          assert len([c for c in proc.calls if c[1:3] == ["agent", "prompt"]]) == 1

Run: `uv run pytest -q tests/test_dispatch.py tests/test_dispatch_await.py` — Expected: FAIL
(`error` ist `agent_start_failed` bzw. `no_reply` statt `agent_blocked`).

### Schritt 2 — Import

`lean_herdr/dispatch.py`, bei den `lean_herdr`-Importen:

    from lean_herdr.dialogs import blocked_dialog

### Schritt 3 — Start

1. Im Aufruf `start_agent(` (`dispatch.py:338-346`) nach `retry_timeout_ms=timeout_ms_for(cfg.ready_timeout_s),` einfügen:

                blocked=lambda started_pane: blocked_dialog(herdr, pane=started_pane),

2. Den Block `if not started["ok"]:` (`dispatch.py:347-353`) ersetzen durch:

            if not started["ok"]:
                # `agent_start_failed` is Herdr refusing after 0.0 s;
                # `opencode_stuck` is opencode's first bootstrap in this project
                # hanging, twice. ONE mechanism with `workspace up` -- a worktree
                # is a new project to opencode, so a worker meets the very same
                # hang the orchestrator does. `agent_blocked` carries the `dialog`
                # a human has to answer; nothing here answers it.
                rest = {key: value for key, value in started.items() if key != "ok"}
                return _result(False, pane, None, **rest)

### Schritt 4 — Warten

In der Schleife von `await_task` zwischen dem Block `if outcome is not None:` (endet mit
`            return outcome`, `dispatch.py:555`) und `        if not has_rung:` (`dispatch.py:556`) einfügen:

            dialog = blocked_dialog(herdr, name=name)
            if dialog is not None:
                # Every round, and BEFORE the bell: `agent prompt` types into the pane,
                # and typed into a dialog it would answer it. The worker waits for a
                # human -- one `agent list` per round is the price of saying so now
                # instead of `no_reply` after the deadline.
                return order_result(
                    False, req.task_id, state=state, error="agent_blocked", dialog=dialog
                )

Run: `uv run pytest -q tests/test_dispatch.py tests/test_dispatch_await.py tests/test_dispatch_prereview.py tests/test_dispatch_uncovered_paths.py`
— Expected: PASS.

### Schritt 5 — Messen, prüfen, committen

@call loc("dispatch")
@call verify(lean_herdr/dispatch.py tests/test_dispatch.py tests/test_dispatch_await.py)
@call py_gate(lean_herdr/dispatch.py tests/test_dispatch.py tests/test_dispatch_await.py)
@call commit("lean_herdr/dispatch.py tests/test_dispatch.py tests/test_dispatch_await.py", "feat(dispatch): report agent_blocked with the dialog at the start and while waiting")
@phase-end

@phase "task-4"
## Task 4: `workspace init --trust-claude` und die Vertrauens-Warnung

**Files:** Modify `lean_herdr/initcmd.py`, `lean_herdr/workspace.py`, `lean_herdr/checkcmd.py`,
`tests/test_initcmd.py`, `tests/test_workspace.py`, `tests/test_checkcmd.py`.

**Consumes:** Task 2 — `dialogs.trust_root`, `dialogs.claude_trusts`; Task 3 (`checkcmd` importiert
`dispatch`, das `dialogs` importiert — kein Zyklus).

**Interfaces — Produces:**
- `workspace_init(..., trust_claude: bool = False)`; mit dem Schalter trägt die Antwort `claude_trust`
  (`"written"`, `"already"` oder `"failed: …"`), ein `failed` zusätzlich die Warnung
  `--trust-claude failed: …`; `ok` bleibt `true`. Ohne den Schalter fehlt der Schlüssel `claude_trust`.
- `lean-herdr workspace init --trust-claude`; `up` und `check` lehnen den Schalter ab.
- `workspace check`: bei mindestens einer Rolle mit `kind = "claude"` und `claude_trusts(root) is False` die Zeile
  `claude does not trust <root> -- a claude worker stops at the folder-trust dialog in every worktree of this repository, and dispatch answers agent_blocked. Run: lean-herdr workspace init --trust-claude`

### Schritt 1 — Tests zuerst

`tests/test_initcmd.py` — am Dateiende:

    def test_init_leaves_claudes_state_alone_without_the_flag(monkeypatch, repo, tmp_path_factory):
        quiet(monkeypatch)
        config = tmp_path_factory.mktemp("claude")
        state = config / ".claude.json"
        state.write_text('{"projects": {}}', encoding="utf-8")
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
        answer = workspace_init(root=repo)
        assert "claude_trust" not in answer
        assert state.read_text(encoding="utf-8") == '{"projects": {}}'


    def test_trust_claude_records_the_root_in_claudes_state(monkeypatch, repo, tmp_path_factory):
        """The human's "Yes" for the root, given up front -- every worktree inherits it."""
        quiet(monkeypatch)
        config = tmp_path_factory.mktemp("claude")
        (config / ".claude.json").write_text('{"projects": {}}', encoding="utf-8")
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
        answer = workspace_init(root=repo, trust_claude=True)
        assert answer["ok"] is True
        assert answer["claude_trust"] == "written"
        projects = json.loads((config / ".claude.json").read_text(encoding="utf-8"))["projects"]
        assert projects == {str(repo.resolve()): {"hasTrustDialogAccepted": True}}
        assert workspace_init(root=repo, trust_claude=True)["claude_trust"] == "already"


    def test_a_trust_that_fails_is_a_warning_not_a_failed_init(monkeypatch, repo, tmp_path_factory):
        quiet(monkeypatch)
        config = tmp_path_factory.mktemp("claude")
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
        answer = workspace_init(root=repo, trust_claude=True)
        assert answer["ok"] is True
        assert answer["claude_trust"].startswith("failed: no claude state at ")
        assert any(w.startswith("--trust-claude failed: ") for w in answer["warnings"]), answer[
            "warnings"
        ]
        assert not (config / ".claude.json").exists()

`tests/test_workspace.py`:

- `test_main_routes_init_and_hands_every_flag_on` (`test_workspace.py:666-692`) ganz ersetzen durch:

      def test_main_routes_init_and_hands_every_flag_on(monkeypatch, capsys):
          """`workspace_init` is imported ON THE CALL, so the seam is `initcmd`."""
          seen: list[dict[str, object]] = []
          monkeypatch.setattr(
              "lean_herdr.initcmd.workspace_init",
              lambda **kwargs: (seen.append(kwargs), {"ok": True, "written": []})[1],
          )
          base = {
              "force": False,
              "update": False,
              "test": None,
              "lint": None,
              "lang": None,
              "trust_claude": False,
          }
          assert workspace.main(["init"]) == 0
          assert workspace.main(["init", "--force"]) == 0
          assert (
              workspace.main(["init", "--update", "--test", "cargo test", "--lint", "cargo clippy"]) == 0
          )
          assert workspace.main(["init", "--lang", "python"]) == 0
          assert workspace.main(["init", "--trust-claude"]) == 0
          assert seen == [
              base,
              {**base, "force": True},
              {**base, "update": True, "test": "cargo test", "lint": "cargo clippy"},
              {**base, "lang": "python"},
              {**base, "trust_claude": True},
          ]
          lines = capsys.readouterr().out.strip().splitlines()
          assert len(lines) == 5 and all(json.loads(line)["ok"] for line in lines)

- in der Parametrisierung von `test_up_refuses_every_init_flag` (`test_workspace.py:703-707`):

      [["--update"], ["--test", "cargo test"], ["--lint", "cargo clippy"], ["--lang", "python"]],
      ids=["update", "test", "lint", "lang"],

  ersetzen durch:

      [
          ["--update"],
          ["--test", "cargo test"],
          ["--lint", "cargo clippy"],
          ["--lang", "python"],
          ["--trust-claude"],
      ],
      ids=["update", "test", "lint", "lang", "trust-claude"],

`tests/test_checkcmd.py`:

- nach der Fixture `no_user_lean_ctx_config` einfügen:

      @pytest.fixture(autouse=True)
      def no_user_claude_state(monkeypatch, tmp_path_factory):
          """`workspace check` reads claude's state file -- never this machine's own in here."""
          monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path_factory.mktemp("no-claude")))

- am Dateiende:

      def _claude_state(monkeypatch, tmp_path_factory, projects: dict) -> None:
          config = tmp_path_factory.mktemp("claude")
          (config / ".claude.json").write_text(json.dumps({"projects": projects}), encoding="utf-8")
          monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))


      def _untrusted(root: Path) -> str:
          return (
              f"claude does not trust {root} -- a claude worker stops at the folder-trust dialog in "
              "every worktree of this repository, and dispatch answers agent_blocked. "
              "Run: lean-herdr workspace init --trust-claude"
          )


      CLAUDE_BUILDER = '[roles.builder]\nkind = "claude"\n'


      def test_a_claude_role_in_an_untrusted_root_is_named(
          monkeypatch, repo, snapshot, tmp_path_factory
      ):
          initialised(monkeypatch, repo)
          monkeypatch.setattr("shutil.which", which_stub(False))
          (repo / SETTINGS_PATH).write_text(CLAUDE_BUILDER, encoding="utf-8")
          _claude_state(monkeypatch, tmp_path_factory, {})
          warnings = workspace_check(root=repo)["warnings"]
          assert _untrusted(repo) in warnings, warnings


      def test_a_trusted_root_is_not_named(monkeypatch, repo, snapshot, tmp_path_factory):
          initialised(monkeypatch, repo)
          monkeypatch.setattr("shutil.which", which_stub(False))
          (repo / SETTINGS_PATH).write_text(CLAUDE_BUILDER, encoding="utf-8")
          _claude_state(
              monkeypatch, tmp_path_factory, {str(repo.resolve()): {"hasTrustDialogAccepted": True}}
          )
          warnings = workspace_check(root=repo)["warnings"]
          assert not any(w.startswith("claude does not trust") for w in warnings), warnings


      def test_without_a_claude_role_trust_is_not_asked(monkeypatch, repo, snapshot, tmp_path_factory):
          initialised(monkeypatch, repo)
          monkeypatch.setattr("shutil.which", which_stub(False))
          (repo / SETTINGS_PATH).write_text('[roles.builder]\nkind = "opencode"\n', encoding="utf-8")
          _claude_state(monkeypatch, tmp_path_factory, {})
          warnings = workspace_check(root=repo)["warnings"]
          assert not any(w.startswith("claude does not trust") for w in warnings), warnings


      def test_a_claude_state_nobody_can_read_gives_no_verdict(monkeypatch, repo, snapshot):
          """The autouse CLAUDE_CONFIG_DIR holds no state file at all."""
          initialised(monkeypatch, repo)
          monkeypatch.setattr("shutil.which", which_stub(False))
          (repo / SETTINGS_PATH).write_text(CLAUDE_BUILDER, encoding="utf-8")
          warnings = workspace_check(root=repo)["warnings"]
          assert not any(w.startswith("claude does not trust") for w in warnings), warnings

Run: `uv run pytest -q tests/test_initcmd.py tests/test_workspace.py tests/test_checkcmd.py` — Expected: FAIL
(`TypeError: … 'trust_claude'`, die Vertrauens-Zeile fehlt).

### Schritt 2 — `initcmd.py`

1. Import bei den `lean_herdr`-Importen:

       from lean_herdr.dialogs import trust_root

2. Im Modul-Docstring die Zeile `keyboard. Two exceptions, both inside the rule's intent. The warm-up`
   ersetzen durch:

       keyboard -- and `--trust-claude` is that gesture, spelled out: the one
       machine-wide grant `init` makes, and only on the flag (`dialogs.trust_root`,
       one key in claude's own state file). Two more exceptions, both inside the
       rule's intent. The warm-up

3. In der Signatur von `workspace_init` nach `lang: str | None = None,` einfügen:

           trust_claude: bool = False,

4. Den abschließenden Block ab `    warmed = _warm_opencode(base, runner=runner) if kind == "opencode" else False`
   bis zum Ende der Funktion ersetzen durch:

        warmed = _warm_opencode(base, runner=runner) if kind == "opencode" else False
        # The human's "Yes" to claude's folder-trust dialog, given for the root up
        # front -- every worktree of it inherits it. Only on the flag, and a failure
        # costs the warning, never the report of the files that already landed.
        claude_trust = trust_root(base) if trust_claude else None
        if claude_trust is not None and claude_trust.startswith("failed"):
            warnings.append(f"--trust-claude {claude_trust}")
        answer: dict[str, Any] = {
            "ok": True,
            "root": str(base),
            "written": sorted(written),
            "skipped": sorted(skipped),
            "values": values,
            "templates": templates,
            "warmed": warmed,
            "lean_md": lean_md,
            "warnings": warnings,
        }
        if claude_trust is not None:
            answer["claude_trust"] = claude_trust
        return answer

### Schritt 3 — `workspace.py`

1. In `build_parser` nach dem `--lang`-Argument einfügen:

        p.add_argument(
            "--trust-claude",
            action="store_true",
            help="init: record claude's folder trust for this repository root, which every worktree "
            "of it inherits (one key in ~/.claude.json)",
        )

2. In `_init_flags` nach `("--lang", args.lang),` einfügen:

            ("--trust-claude", args.trust_claude),

3. In `main` den Aufruf

                result = workspace_init(
                    force=args.force, update=args.update, test=args.test, lint=args.lint, lang=args.lang
                )

   ersetzen durch:

                result = workspace_init(
                    force=args.force,
                    update=args.update,
                    test=args.test,
                    lint=args.lint,
                    lang=args.lang,
                    trust_claude=args.trust_claude,
                )

### Schritt 4 — `checkcmd.py`

1. Import bei den `lean_herdr`-Importen:

       from lean_herdr.dialogs import claude_trusts

2. Nach `_role_warnings` einfügen:

       def _claude_trust_warnings(root: Path, data: dict[str, Any]) -> list[str]:
           """A role on claude in a repository whose root claude does not trust.

           A worktree inherits the root's trust (measured 2026-09-15), so without it
           every claude worker stops at the folder-trust dialog and `dispatch` answers
           `agent_blocked`. Reads only; granting it is `init --trust-claude`. No state
           file, or one nobody can read: no verdict.
           """
           roles = {"orchestrator", *work_roles(data).values()}
           if not any(settings_for(role, data).kind == "claude" for role in roles):
               return []
           if claude_trusts(root) is not False:
               return []
           return [
               f"claude does not trust {root} -- a claude worker stops at the folder-trust dialog in "
               "every worktree of this repository, and dispatch answers agent_blocked. "
               "Run: lean-herdr workspace init --trust-claude"
           ]

3. In `workspace_check` die Zeile `        + _role_warnings(base, data)` ersetzen durch:

            + _role_warnings(base, data)
            + _claude_trust_warnings(base, data)

Run: `uv run pytest -q tests/test_initcmd.py tests/test_workspace.py tests/test_checkcmd.py tests/test_checkcmd_lean_md.py` — Expected: PASS.

### Schritt 5 — Messen, prüfen, committen

@call loc("initcmd workspace checkcmd")
@call verify(lean_herdr/initcmd.py lean_herdr/workspace.py lean_herdr/checkcmd.py)
@call py_gate(lean_herdr/initcmd.py lean_herdr/workspace.py lean_herdr/checkcmd.py tests/test_initcmd.py tests/test_workspace.py tests/test_checkcmd.py)
@call commit("lean_herdr/initcmd.py lean_herdr/workspace.py lean_herdr/checkcmd.py tests/test_initcmd.py tests/test_workspace.py tests/test_checkcmd.py", "feat(init): grant claude's folder trust for the root on --trust-claude, and check names a root without it")
@phase-end

@phase "task-5"
## Task 5: Orchestrator — Dialog-Verbot, herdr-Rechte, Abschluss-Reihenfolge

**Files:** Modify `lean_herdr/templates/roles/orchestrator.md`, `lean_herdr/templates/opencode.jsonc`,
`lean_herdr/templates/claude/orchestrator.json`, `tests/test_role_prohibitions.py`,
`tests/test_worker_permissions.py`, `tests/test_config_files.py`; die eingecheckten Kopien und den Lock.

**Consumes:** Task 3 — `dispatch` und `dispatch --await` antworten `agent_blocked` mit `dialog`.

**Interfaces — Produces:** Einzel-Task-Abschluss in sechs Schritten (squash, merge `--no-remove`,
`workspace close`, `wt remove`), Plan-Abschluss in vier; opencode-Orchestrator mit genau
`herdr worktree list *`, `herdr workspace close *`, `herdr workspace report-metadata *`;
claude-Orchestrator mit `deny` für `Bash(herdr agent:*)` und `Bash(herdr pane:*)`.

### Schritt 1 — Tests zuerst

`tests/test_role_prohibitions.py`:

- in `PROHIBITIONS` nach dem Eintrag `"Teardown for a plan -- no squash."`:

          (
              "orchestrator.md",
              "You never answer a dialog in a worker's pane: no `herdr agent send-keys`, "
              "no `herdr agent prompt`, no keystroke of any kind.",
              "E3: a dialog is reported, never answered -- by nobody in lean-herdr",
          ),
          (
              "orchestrator.md",
              "never remove with `--force`",
              "E4: a worktree that will not go is a finding, not an obstacle",
          ),

- in `MANDATORY_SENTENCES` nach dem Eintrag `"wt -C <path> merge main --yes --no-commit"`:

          (
              "orchestrator.md",
              "wt -C <path> merge main --yes --no-commit --no-remove",
              "E4: the checkout stays through the merge -- no pane loses its cwd",
          ),
          (
              "orchestrator.md",
              "wt -C <repo_root> remove <branch> --yes",
              "E4: the worktree goes only once its workspace is closed",
          ),
          (
              "orchestrator.md",
              "`agent_blocked` means a dialog waits in a worker's pane",
              "E2: a dialog in a worker's pane is an escalation, with its text",
          ),

- am Dateiende:

      @pytest.mark.parametrize(
          ("start", "end", "remove"),
          [
              pytest.param(
                  "## Teardown and merge",
                  "## Plan mode",
                  "wt -C <repo_root> remove <branch> --yes",
                  id="single task",
              ),
              pytest.param(
                  "**Teardown for a plan -- no squash.**",
                  "## Termination",
                  "wt -C <repo_root> remove plan/<slug> --yes",
                  id="plan",
              ),
          ],
      )
      def test_the_teardown_merges_with_the_workspace_open_and_removes_after_closing_it(
          start, end, remove
      ):
          """E4: merge with `--no-remove`, close the workspace, only then `wt remove` -- in both."""
          section = _normalized("orchestrator.md").split(start, 1)[1].split(end, 1)[0]
          merge = section.index("wt -C <path> merge main --yes --no-commit --no-remove")
          close = section.index("herdr workspace close <workspace_id>")
          assert merge < close < section.index(remove), section

`tests/test_worker_permissions.py`:

- nach `PUSH_AND_MERGE` einfügen:

      #: What the orchestrator may run of herdr: find the worktree, close its workspace, set `esc=`.
      ORCHESTRATOR_HERDR = (
          "herdr worktree list *",
          "herdr workspace close *",
          "herdr workspace report-metadata *",
      )

- im Docstring von `test_the_claude_orchestrator_writes_nothing` den Satzteil
  `unlike reviewer.json, nothing here narrows Bash: the orchestrator's` ersetzen durch
  ``unlike reviewer.json, Bash stays open but for `herdr agent` and `herdr pane`: the orchestrator's``
- am Dateiende:

      def test_the_opencode_orchestrator_runs_exactly_three_herdr_subcommands(gate_root):
          """E3: no `herdr agent`, no `herdr pane` -- a keystroke into a worker's pane is not its to send."""
          bash = opencode(gate_root)["agent"]["orchestrator"]["permission"]["bash"]
          assert sorted(key for key in bash if key.startswith("herdr")) == sorted(ORCHESTRATOR_HERDR)
          for pattern in ORCHESTRATOR_HERDR:
              assert bash[pattern] == "allow", pattern


      def test_the_claude_orchestrator_is_denied_herdr_agent_and_pane(gate_root):
          denied = claude_rules("orchestrator", "deny", gate_root)
          for rule in ("Bash(herdr agent:*)", "Bash(herdr pane:*)"):
              assert rule in denied, f"claude/orchestrator.json does not deny {rule}"

`tests/test_config_files.py`: `test_orchestrator_may_dispatch_wt_and_herdr` (`test_config_files.py:45-49`) ganz ersetzen durch:

    def test_orchestrator_may_dispatch_wt_and_three_herdr_subcommands():
        bash = opencode()["agent"]["orchestrator"]["permission"]["bash"]
        assert bash["lean-herdr dispatch *"] == "allow"
        assert bash["wt *"] == "allow"
        assert "herdr *" not in bash, "E3: no herdr agent, no herdr pane"
        for pattern in (
            "herdr worktree list *",
            "herdr workspace close *",
            "herdr workspace report-metadata *",
        ):
            assert bash[pattern] == "allow", pattern

Run: `uv run pytest -q tests/test_role_prohibitions.py tests/test_worker_permissions.py tests/test_config_files.py` — Expected: FAIL.

### Schritt 2 — `orchestrator.md`: Einzel-Task-Abschluss

In `lean_herdr/templates/roles/orchestrator.md` den Abschnitt ab der Zeile
`## Teardown and merge — this order, not another` bis ausschließlich `## Plan mode` ersetzen. Der neue
Text steht hier um vier Leerzeichen eingerückt; ohne diese vier Leerzeichen einsetzen, eine Leerzeile vor
`## Plan mode` lassen:

    ## Teardown and merge — this order, not another

    Merge while the worker's workspace is still open, close the workspace, and
    only then remove the worktree. `--no-remove` keeps the checkout standing
    through the merge, so no pane loses its cwd: the worktree goes only once no
    pane runs in it any more. An agent whose cwd disappears leaves a pane in an
    undefined state -- a mistake you only notice in operation.

        1. Check: verdict=result, not reject
        2. Resolve path and workspace WHILE the worktree still exists:
             herdr worktree list --cwd <repo_root>
           Read the JSON answer yourself: under `result.worktrees`, find the
           entry whose `branch` is your branch and take its `path` and its
           `open_workspace_id`. Do not pipe the answer through another program.
           Of `herdr` you run `worktree list`, `workspace close` and
           `workspace report-metadata`, nothing else; beyond that only `wt`,
           `git`, `lean-herdr dispatch` and `lean-herdr plan next | show`.
        3. wt -C <path> step squash --stage none --yes
        4. wt -C <path> merge main --yes --no-commit --no-remove
        5. herdr workspace close <workspace_id>
        6. wt -C <repo_root> remove <branch> --yes

    **`--no-commit` skips the commit AND the squash.** That is why step 3 is not
    a luxury: it is the only place the squash still happens, and from two commits
    on the squashed message is the one that lands in `main` (with exactly one,
    `wt` leaves the worker's message alone and says so). What `--no-commit` buys
    is step 4's refusal: if anything unfinished is left in the worktree -- an
    untracked file git does not ignore included -- the merge stops before `main`
    moves at all. It skips the commit, not the gates — the `pre-merge` hook still
    runs and its exit code still reaches you.

    **If step 3 or step 4 fails, the teardown ends there.** You close NO
    workspace and you remove NOTHING: set `esc=` on the worker's workspace, which
    is still open, and escalate with `wt`'s own error text. The open workspace is
    wanted: it is exactly the state in which a human can look at what the squash
    or the merge would not take.

    **If step 5 fails, `main` is merged and the workspace is still open.** Do not
    run step 6 -- the panes in it would lose their cwd. Set `esc=` on that open
    workspace and escalate with herdr's own error text.

    **If step 6 fails, `main` is merged.** Report `wt`'s own error text; never
    remove with `--force`. The removal runs in the background -- do not check for
    it.

    **`-C <path>` is not optional, it is the safeguard.** `wt merge <X>` merges
    the CURRENT worktree INTO X. You stand in the main checkout: without `-C` you
    drive `main` onto the feature branch — with exit 0 and without a warning.
    Never call `wt merge` with the source branch as its argument.

    You do not push. That stays a human gesture.

### Schritt 3 — `orchestrator.md`: Plan-Abschluss

Den Block ab der Zeile `**Teardown for a plan -- no squash.** Every task commit passed its own review and stays:`
bis ausschließlich `## Termination — no polling` ersetzen (Einrückung wie in Schritt 2 entfernen):

    **Teardown for a plan -- no squash.** Every task commit passed its own review and stays:

        1. herdr worktree list --cwd <repo_root> -> `path` and `open_workspace_id` of plan/<slug>
        2. wt -C <path> merge main --yes --no-commit --no-remove
        3. herdr workspace close <workspace_id>
        4. wt -C <repo_root> remove plan/<slug> --yes

    Escalate as for a single task — with the `reason` from `plan next`, on a failed gate, and on
    `Cannot merge with --no-commit`. A failed step 2, 3 or 4 is handled like a failed step 4, 5 or
    6 of a single task: nothing closed and nothing removed after a failed merge, no `wt remove`
    after a failed close, never `--force`.

### Schritt 4 — `orchestrator.md`: Escalation

1. Den Absatz ab ``Escalate on: twice `reject` `` bis ``and `✗ Cannot merge with --no-commit`.`` ersetzen durch
   (Einrückung entfernen):

       Escalate on: twice `reject`, `agent_error` (no retry — a 401 is a 401 the
       second time too), `agent_blocked`, a second `no_reply`, a failed `pre-merge`
       hook, a failed `wt step squash`, `✗ Cannot merge with --no-commit`, and a
       failed `herdr workspace close`.

       `agent_blocked` means a dialog waits in a worker's pane -- a permission, a
       trust question, a login. `dialog` carries its screen text: put it into the
       escalation verbatim. You never answer a dialog in a worker's pane: no
       `herdr agent send-keys`, no `herdr agent prompt`, no keystroke of any kind.
       Do not wait again and do not build another worker for that order -- the
       dialog is the human's to answer.

2. Die Zeile `      Last state: <no_reply | agent_error | reject×2>` ersetzen durch
   `      Last state: <no_reply | agent_error | agent_blocked | reject×2>`

### Schritt 5 — Rechte

`lean_herdr/templates/opencode.jsonc`, im Block `agent.orchestrator.permission.bash` die Zeile
`          "herdr *": "allow",` ersetzen durch (Einrückung wie die Nachbarzeilen: zehn Leerzeichen):

              // Of herdr only what the teardown and the escalation need: no `herdr agent`,
              // no `herdr pane` -- a keystroke into a worker's pane would answer its dialog.
              "herdr worktree list *": "allow",
              "herdr workspace close *": "allow",
              "herdr workspace report-metadata *": "allow",

`lean_herdr/templates/claude/orchestrator.json` — ganzer Inhalt:

    {
      "permissions": {
        "deny": [
          "Edit",
          "Write",
          "NotebookEdit",
          "mcp__lean-ctx__ctx_patch",
          "mcp__lean-ctx__ctx_edit",
          "mcp__lean-ctx__ctx_refactor",
          "Bash(herdr agent:*)",
          "Bash(herdr pane:*)"
        ]
      }
    }

### Schritt 6 — Kopien, prüfen, committen

@call copies()

Run: `uv run pytest -q tests/test_role_prohibitions.py tests/test_worker_permissions.py tests/test_roles.py tests/test_config_files.py` — Expected: PASS.

@call verify(lean_herdr/templates/roles/orchestrator.md lean_herdr/templates/opencode.jsonc lean_herdr/templates/claude/orchestrator.json)
@call py_gate(tests/test_role_prohibitions.py tests/test_worker_permissions.py tests/test_config_files.py)
@call commit("lean_herdr/templates/roles/orchestrator.md lean_herdr/templates/opencode.jsonc lean_herdr/templates/claude/orchestrator.json .lean-ctx/lean-herdr/roles/orchestrator.md opencode.jsonc .lean-ctx/lean-herdr/claude/orchestrator.json .lean-ctx/lean-herdr/templates.lock.json tests/test_role_prohibitions.py tests/test_worker_permissions.py tests/test_config_files.py", "feat(orchestrator): merge before closing, remove after, and never answer a dialog")

`init --update` kann auch Skill-Stubs auffrischen: nur die genannten Pfade committen, jede weitere Zeile
aus `git status --porcelain` im Bericht nennen.
@phase-end

@phase "task-6"
## Task 6: `workspace check` — `__pycache__/` und `model unset`

**Files:** Modify `lean_herdr/checkcmd.py`, `tests/test_checkcmd.py`.

**Consumes:** Task 4 hat `checkcmd.py` und `tests/test_checkcmd.py` schon geändert; Zeilenangaben unten
sind Stand vor Task 4 — maßgeblich ist der zitierte Text.

**Interfaces — Produces:**
- `checkcmd.PYCACHE_IGNORE = "__pycache__/"`, `checkcmd.PYCACHE_PROBE = "__pycache__/lean-herdr.probe"`
- `checkcmd._check_pycache_ignored(root: Path, runner: Any) -> str | None`, eingehängt in `machine_report`
- `_role_warnings`: je Worker-Rolle ohne `model` die Zeile
  `` [roles.<role>].model unset: `dispatch --work <work>` needs --model ``

### Schritt 1 — Tests zuerst

`tests/test_checkcmd.py`:

- im Import-Block `from lean_herdr.checkcmd import (` ergänzen: `PYCACHE_IGNORE`, `PYCACHE_PROBE`, `_check_pycache_ignored`
- nach `test_the_temp_check_probes_the_lock_writer_as_well` einfügen:

      def _python_project(repo: Path) -> None:
          (repo / "pyproject.toml").write_text('[project]\nname = "probe"\n', encoding="utf-8")


      def test_the_pycache_check_asks_git_about_a_probe_name(monkeypatch, repo):
          monkeypatch.setattr("shutil.which", which_stub(True))
          _python_project(repo)
          named = FakeProc(
              replies={("check-ignore",): f".gitignore:2:{PYCACHE_IGNORE}\t{PYCACHE_PROBE}"}
          )
          assert _check_pycache_ignored(repo, named) is None
          assert named.called_with("check-ignore", "-v", PYCACHE_PROBE)
          silent = FakeProc(replies={("check-ignore",): Completed(returncode=1)})
          assert _check_pycache_ignored(repo, silent) == (
              "git does not ignore __pycache__/ (probed with __pycache__/lean-herdr.probe) -- every test "
              "run leaves bytecode there, and untracked files stop `wt merge --no-commit` and "
              "`wt remove`. Add to .gitignore: __pycache__/"
          )


      def test_without_pyproject_there_is_no_pycache_question(monkeypatch, repo):
          monkeypatch.setattr("shutil.which", which_stub(True))
          proc = FakeProc(replies={("check-ignore",): Completed(returncode=1)})
          assert _check_pycache_ignored(repo, proc) is None
          assert not proc.called_with("check-ignore"), proc.flat()


      def test_a_pycache_check_git_cannot_answer_gives_no_verdict(monkeypatch, repo):
          monkeypatch.setattr("shutil.which", which_stub(True))
          _python_project(repo)
          fatal = Completed(returncode=128, stderr="fatal: not a git repository\n")
          assert _check_pycache_ignored(repo, FakeProc(replies={("check-ignore",): fatal})) is None
          monkeypatch.setattr(
              "shutil.which", lambda binary: None if binary == "git" else "/usr/bin/fake"
          )
          assert _check_pycache_ignored(repo, FakeProc(default="")) is None


      @pytest.mark.parametrize(
          ("gitignore", "warned"),
          [pytest.param("", True, id="no rule"), pytest.param("__pycache__/\n", False, id="rule")],
      )
      def test_the_pycache_rule_covers_the_probe_with_no_directory_on_disk(
          monkeypatch, repo, gitignore, warned
      ):
          """Real git, with the operator's own excludes kept out (M4)."""
          monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
          monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
          monkeypatch.setenv("XDG_CONFIG_HOME", str(repo / "no-config"))
          _python_project(repo)
          (repo / ".gitignore").write_text(gitignore, encoding="utf-8")
          line = _check_pycache_ignored(repo, subprocess.run)
          assert (line is not None) is warned, line


      def test_workspace_check_names_an_unignored_pycache_in_a_python_project(
          monkeypatch, repo, snapshot
      ):
          initialised(monkeypatch, repo)
          _python_project(repo)
          proc = FakeProc(
              replies={("check-ignore", "-v", PYCACHE_PROBE): Completed(returncode=1)},
              default=Completed(),
          )
          warnings = workspace_check(root=repo, runner=proc)["warnings"]
          assert any(w.startswith(f"git does not ignore {PYCACHE_IGNORE}") for w in warnings), warnings

- im Test `test_an_initialised_project_on_a_healthy_machine_is_ok_and_all_current` den Kommentar
  ``# After `init` no worker has a kind -- the normal case, and check names it.`` und die Liste ersetzen durch:

          # After `init` no worker has a kind or a model -- the normal case, and check names both.
          assert answer["warnings"] == [
              _kind_unset("builder", "implement"),
              _model_unset("builder", "implement"),
              _kind_unset("plan-writer", "plan"),
              _model_unset("plan-writer", "plan"),
              _kind_unset("plan-reviewer", "plan-review"),
              _model_unset("plan-reviewer", "plan-review"),
              _kind_unset("reviewer", "review"),
              _model_unset("reviewer", "review"),
          ]

- nach `_kind_unset` einfügen:

      def _model_unset(role: str, work: str) -> str:
          return f"[roles.{role}].model unset: `dispatch --work {work}` needs --model"


      def test_a_worker_with_a_model_is_not_named_and_default_counts(monkeypatch, repo, snapshot):
          """`[default].model` reaches every role through settings_for -- no line for any of them."""
          initialised(monkeypatch, repo)
          monkeypatch.setattr("shutil.which", which_stub(False))
          (repo / SETTINGS_PATH).write_text(
              '[default]\nmodel = "cheap"\n\n[roles.builder]\nmodel = "strong"\n', encoding="utf-8"
          )
          warnings = workspace_check(root=repo)["warnings"]
          assert not any(".model unset" in w for w in warnings), warnings


      def test_the_orchestrator_is_never_named_for_a_missing_model(monkeypatch, repo, snapshot):
          """`workspace up` starts the orchestrator without a model -- a work routed to it gets no line."""
          initialised(monkeypatch, repo)
          monkeypatch.setattr("shutil.which", which_stub(False))
          (repo / SETTINGS_PATH).write_text('[routing]\nsteer = "orchestrator"\n', encoding="utf-8")
          warnings = workspace_check(root=repo)["warnings"]
          assert _model_unset("orchestrator", "steer") not in warnings, warnings
          assert _model_unset("builder", "implement") in warnings, warnings

Run: `uv run pytest -q tests/test_checkcmd.py` — Expected: FAIL (`ImportError: PYCACHE_IGNORE`).

### Schritt 2 — `_check_pycache_ignored`

`lean_herdr/checkcmd.py`, nach `_check_temp_ignored` einfügen:

    #: The ignore rule a Python project needs before a worker's test run leaves bytecode in its
    #: worktree. `git check-ignore` matches patterns, so the probe needs no directory on disk (M4).
    PYCACHE_IGNORE = "__pycache__/"
    PYCACHE_PROBE = "__pycache__/lean-herdr.probe"


    def _check_pycache_ignored(root: Path, runner: Any) -> str | None:
        """A Python project whose git does not ignore `__pycache__/`.

        Every test run in a worker's worktree leaves bytecode behind, and both
        `wt merge --no-commit` and `wt remove` stop at an untracked file. Asked
        only where `pyproject.toml` marks the root as a Python project, and judged
        by the exit code like `_check_temp_ignored`. The rule stays the operator's
        to add: `init` writes none.
        """
        if not (root / "pyproject.toml").is_file():
            return None
        proc = _run(runner, "git", "check-ignore", "-v", PYCACHE_PROBE, cwd=root)
        if proc is None or proc.returncode != 1:
            return None
        return (
            f"git does not ignore {PYCACHE_IGNORE} (probed with {PYCACHE_PROBE}) -- every test run "
            "leaves bytecode there, and untracked files stop `wt merge --no-commit` and `wt remove`. "
            f"Add to .gitignore: {PYCACHE_IGNORE}"
        )

In `machine_report` in der Liste unter `if root is not None:` nach `            _check_temp_ignored(root, runner),` einfügen:

                # Only a Python project asks, and `init` still writes no rule (E5).
                _check_pycache_ignored(root, runner),

### Schritt 3 — `model unset`

In `_role_warnings`:

1. Die Zeile `        kind = settings_for(role, data).kind` ersetzen durch:

            role_settings = settings_for(role, data)
            kind = role_settings.kind

2. Unmittelbar nach

            if role == "orchestrator":
                continue

   einfügen:

            if not role_settings.model:
                # `dispatch` builds no worker without one (`usage_error: build mode needs
                # --model`); `[default].model` counts, settings_for lays it under the role.
                lines.append(f"[roles.{role}].model unset: `dispatch --work {work}` needs --model")

Run: `uv run pytest -q tests/test_checkcmd.py tests/test_checkcmd_lean_md.py tests/test_initcmd.py` — Expected: PASS.

### Schritt 4 — Messen, prüfen, committen

@call loc("checkcmd")
@call verify(lean_herdr/checkcmd.py tests/test_checkcmd.py)
@call py_gate(lean_herdr/checkcmd.py tests/test_checkcmd.py)
@call commit("lean_herdr/checkcmd.py tests/test_checkcmd.py", "feat(check): warn about an unignored __pycache__/ and a worker role without a model")
@phase-end

@phase "task-7"
## Task 7: Briefs und Builder-Prompt — ungetrackte Dateien

**Files:** Modify `lean_herdr/templates/briefs/implement.lmd.md`, `lean_herdr/templates/briefs/review.lmd.md`,
`lean_herdr/templates/roles/builder.md`, `tests/test_plan_templates.py`, `tests/test_role_prohibitions.py`;
die eingecheckten Kopien und den Lock.

### Schritt 1 — Tests zuerst

`tests/test_plan_templates.py`, in der Parameterliste von `test_each_brief_carries_its_rules` nach
`("implement", "status: DONE | DONE_WITH_CONCERNS"),`:

            ("implement", "Leave no untracked file that git does not ignore: it stops the merge."),
            ("implement", "the project's ignore rules are not yours to change."),
            ("review", "An ignored file is no defect."),
            (
                "review",
                "Important if it belongs in a commit, Minor if only the project's ignore rules miss it.",
            ),

und nach `test_each_brief_carries_its_rules`:

    @pytest.mark.parametrize(
        ("step", "sentence"),
        [
            ("implement", "that is expected."),
            ("review", "An untracked file is no defect by itself"),
        ],
    )
    def test_no_brief_calls_an_untracked_file_harmless(step, sentence):
        """E5: an untracked file git does not ignore stops the merge -- no brief may wave it through."""
        text = " ".join(rendered(f"briefs/{step}.lmd.md").split())
        assert sentence not in text

`tests/test_role_prohibitions.py`, in `MANDATORY_SENTENCES` nach dem Eintrag `"lean-herdr plan brief --task o-…"` des Builders:

        (
            "builder.md",
            "An untracked file that git does not ignore stops the merge — delete what you created, "
            "name what a tool generated.",
            "E5: untracked files stay a merge stop; the builder leaves none behind",
        ),

Run: `uv run pytest -q tests/test_plan_templates.py tests/test_role_prohibitions.py` — Expected: FAIL.

### Schritt 2 — Texte

`lean_herdr/templates/briefs/implement.lmd.md`: den Satz

    Files the task did not
    name stay untracked — that is expected.

ersetzen durch (davor steht im selben Absatz weiter ``Tracked changes left uncommitted at `done` send you into another round.``):

    Files the task did not
    name stay out of your commits. Leave no untracked file that git does not ignore: it stops the
    merge. Delete scratch files you created; if a tool generates such files, name them under
    `concerns:` — the project's ignore rules are not yours to change.

`lean_herdr/templates/briefs/review.lmd.md`: den Satz

    An untracked file is no defect by itself; name one that belongs
    in a commit.

ersetzen durch:

    An ignored file is no defect. An untracked file that git does not ignore stops
    the merge: name it — Important if it belongs in a commit, Minor if only the project's ignore rules
    miss it.

`lean_herdr/templates/roles/builder.md`, Schritt 4 der Sequenz: nach `reaches the commit.` (vor
`An empty index fails loudly`) einfügen und den Absatz neu umbrechen — drei Leerzeichen Einrückung,
Zeilenlänge wie die Nachbarzeilen:

    An untracked file that git does not ignore stops the merge — delete what you created,
    name what a tool generated.

### Schritt 3 — Kopien, prüfen, committen

@call copies()

Run: `uv run pytest -q tests/test_plan_templates.py tests/test_role_prohibitions.py tests/test_roles.py` — Expected: PASS.

@call verify(lean_herdr/templates/briefs/implement.lmd.md lean_herdr/templates/briefs/review.lmd.md lean_herdr/templates/roles/builder.md)
@call py_gate(tests/test_plan_templates.py tests/test_role_prohibitions.py)
@call commit("lean_herdr/templates/briefs/implement.lmd.md lean_herdr/templates/briefs/review.lmd.md lean_herdr/templates/roles/builder.md .lean-ctx/lean-herdr/briefs/implement.lmd.md .lean-ctx/lean-herdr/briefs/review.lmd.md .lean-ctx/lean-herdr/roles/builder.md .lean-ctx/lean-herdr/templates.lock.json tests/test_plan_templates.py tests/test_role_prohibitions.py", "docs(briefs): an untracked file git does not ignore stops the merge")

`init --update` kann auch Skill-Stubs auffrischen: nur die genannten Pfade committen, jede weitere Zeile
aus `git status --porcelain` im Bericht nennen.
@phase-end

@phase "task-8"
## Task 8: README und INSTALL

**Files:** Modify `README.md`, `INSTALL.md`.

**Consumes:** Tasks 3–7.

### Schritt 1 — README: Ablauf

In `README.md`, Abschnitt `## How it works`, den Listenpunkt 5 (`5. The reviewer runs on the same branch …`
bis `   Pushing stays with you.`) ersetzen durch:

    5. The reviewer runs on the same branch (`--work review`). On `result` the orchestrator
       squashes and merges into `main` with `wt merge --no-remove`, whose pre-merge gate runs
       the project's test and lint commands. Only then does it close the worktree's workspace,
       and only after that does `wt remove` take the worktree -- no pane ever loses its
       directory, and a merge that fails leaves the workspace open for you to look at. The
       commit message comes from `lean-herdr llm generate`. Pushing stays with you.

Abschnitt `### Plan mode`, Listenpunkt 5 ersetzen durch:

    5. A review of the whole branch, then the merge into `main`, without a squash: every task
       commit passed its own review. The teardown keeps the same order: merge, close the
       workspace, remove the worktree.

### Schritt 2 — README: Dialoge

Unmittelbar vor `## The work-order path` einfügen:

    ### Dialogs in worker panes

    A worker waits for nobody at the keyboard. Claude Code asks whether to trust a folder the
    first time it starts in a repository, and every worktree inherits the answer given for the
    repository root -- so `lean-herdr workspace init --trust-claude` gives that answer once, up
    front (see [Setting up a project](#setting-up-a-project)).

    Any other dialog -- a permission, a login -- is reported, never answered. At the start
    `dispatch` answers `{"ok": false, "error": "agent_blocked", "pane": …, "dialog": "<screen text>"}`;
    while it waits, `dispatch --await` answers `agent_blocked` in the round the dialog appears in,
    instead of `no_reply` after the timeout. The orchestrator escalates it with the dialog's text
    and sends no key into a worker's pane: of `herdr` it may run `worktree list`,
    `workspace close` and `workspace report-metadata`, and nothing else.

### Schritt 3 — README: Einrichten und Rechte

Abschnitt `## Setting up a project`, nach dem Absatz, der mit `Without the flags the gate is` beginnt
und mit `the builder's gate is your call.` endet, einfügen:

    A claude worker stops at Claude Code's folder-trust dialog unless Claude Code trusts the
    repository root, and every worktree of the repository inherits that trust. Grant it once, as
    you would by answering "Yes, I trust this folder" in the root:

        lean-herdr workspace init --trust-claude

    It sets exactly one key, `projects.<root>.hasTrustDialogAccepted`, in `~/.claude.json`
    (`$CLAUDE_CONFIG_DIR/.claude.json` when the variable is set), and reports `claude_trust`:
    `written`, `already`, or `failed: …` as a warning. It never creates that file, and nothing
    else in lean-herdr writes to it.

Im selben Abschnitt die Zeilen

    the same three; `orchestrator.json` takes back the editors and lean-ctx's three
    write tools too, leaving Bash open for `lean-herdr dispatch`, `lean-herdr plan`,
    `herdr` and `wt`.

ersetzen durch (ohne die vier Leerzeichen):

    the same three; `orchestrator.json` takes back the editors and lean-ctx's three
    write tools too and denies `herdr agent` and `herdr pane` -- the orchestrator sends no
    key into a worker's pane -- leaving Bash open for `lean-herdr dispatch`,
    `lean-herdr plan`, the rest of `herdr` and `wt`.

### Schritt 4 — README: `workspace check`

Nach dem Absatz, der mit ``For plan runs it also names a lean-md without `outline --json` `` beginnt, einfügen:

    In a Python project -- one with `pyproject.toml` -- it names a `__pycache__/` git does not
    ignore: every test run leaves bytecode in the worktree, and an untracked file stops
    `wt merge --no-commit` and `wt remove`. `init` writes no ignore rule; the warning carries the
    line to add. It also names every worker role without a `model`, for which `dispatch` builds
    nothing, and -- as soon as a role runs on claude -- a root Claude Code does not trust
    (`claude does not trust <root>`), with the `--trust-claude` line that grants it.

### Schritt 5 — INSTALL: Approvals

In `INSTALL.md`, Abschnitt `## Approvals`, die beiden Zeilen

        wt config approvals list   # expectation: "state": "approved"
        wt config approvals add    # if "approval_required"

ersetzen durch (die Codezeilen mit vier Leerzeichen Einrückung, der Absatz ohne):

        wt config approvals list         # expectation: "state": "approved"
        wt config approvals add          # if "approval_required"
        wt config approvals add --yes    # the same without a terminal: an agent, CI

    Without a terminal `wt config approvals add` refuses with `Cannot prompt for approval in
    non-interactive environment`; `--yes` grants it there. Either way the approval covers the hooks
    of this project's `.config/wt.toml` -- read them before you grant it.

Im Abschnitt `## Updating` die Zeilen

    If that rewrote `.config/wt.toml`, the changed gate command needs a fresh
    `wt config approvals add` -- until then worktrunk skips it silently.

ersetzen durch (ohne die vier Leerzeichen):

    If that rewrote `.config/wt.toml`, the changed gate command needs a fresh
    `wt config approvals add` (`--yes` without a terminal) -- until then worktrunk
    skips it silently.

### Schritt 6 — prüfen, committen

Run:

    uv run python -c 'import pathlib; r = pathlib.Path("README.md").read_text(); i = pathlib.Path("INSTALL.md").read_text(); need = [(r, "wt merge --no-remove"), (r, "### Dialogs in worker panes"), (r, "agent_blocked"), (r, "lean-herdr workspace init --trust-claude"), (r, "claude does not trust"), (r, "denies `herdr agent` and `herdr pane`"), (r, "__pycache__/"), (i, "wt config approvals add --yes")]; missing = [s for t, s in need if s not in t]; print(missing or "ok")'

Expected: `ok`.

Run: `uv run pytest -q tests/test_config_files.py` — Expected: PASS.

@call verify(README.md INSTALL.md)
@call commit("README.md INSTALL.md", "docs: teardown order, claude trust and dialogs, the new check warnings, approvals without a terminal")
@phase-end

@phase "task-9"
## Task 9: Abnahme

**Files:** keine in diesem Repository. Wegwerf-Repository `~/Scripts/lh-harden-probe`.

**Consumes:** Tasks 1–8 auf `main`; eine laufende Herdr-Sitzung; für jede Rolle `kind` und `model` nach
Vorgabe des Betreibers; claude unter `~/.claude.json` schon einmal gestartet.

Fehlt eine Voraussetzung: mit BLOCKED enden und sie nennen. Die Abnahme wird nicht simuliert.
Existiert `~/Scripts/lh-harden-probe` schon: BLOCKED — nichts löschen.

### Schritt 1 — dieses Repository

1. Run: `uv run pytest -q` — Expected: PASS.
2. Run: `uv run lean-herdr workspace check` — Expected: `"ok": true`; keine Warnung, die vor Task 2 nicht da
   war, außer einer Zeile `model unset` für eine Rolle, die hier wirklich kein `model` hat. Jede Warnung
   im Bericht nennen.

### Schritt 2 — den Snapshot installieren

Run: `uv tool install --reinstall "lean-herdr @ git+file:///home/tholo/Scripts/lean-herdr@main"`

Run: `lean-herdr workspace check` (außerhalb eines Repositorys) — Expected: `install.tool` ist `true`,
kein Eintrag `editable`.

### Schritt 3 — Wegwerf-Repository

1. `mkdir -p ~/Scripts/lh-harden-probe`; darin **zuerst** `uv init --package --name probe`, danach
   `git init -q`. Run: `grep -x '__pycache__/' ~/Scripts/lh-harden-probe/.gitignore` — Expected: Treffer.
2. Darin: `uv add --dev pytest ruff ty`; `git add -A`; `git commit -m "chore: empty probe project"`;
   `git branch -M main`.
3. Darin: `lean-herdr workspace init --trust-claude` — Expected: `"ok": true`, `claude_trust` ist `written`.
   In `.lean-ctx/lean-herdr/config.toml` für `orchestrator`, `builder`, `reviewer`, `plan-writer` und
   `plan-reviewer` `kind` **und** `model` nach Vorgabe des Betreibers eintragen.
4. Darin: `wt config approvals add --yes`; `git add -A`; `git commit -m "chore: lean-herdr workspace"`.
5. Darin: `lean-herdr workspace check` — Expected: `"ok": true`; keine Zeile zu `__pycache__/`, keine Zeile
   mit `model unset`, keine Zeile `claude does not trust`, keine Zeile `not committed:`, keine Zeile zu
   lean-md, Gateway, Skill oder `ty`.
6. `docs/specs/2026-09-15-probe-design.md` anlegen und committen:

       # probe: add

       `probe.add(a: int, b: int) -> int` returns the sum. A test in `tests/test_add.py` covers
       `add(2, 3) == 5` and `add(-1, 1) == 0`. Nothing else.

### Schritt 4 — der Lauf

1. Darin: `lean-herdr workspace up`.
2. Im Terminal des Orchestrators: `Plan spec docs/specs/2026-09-15-probe-design.md as probe and run it`.
3. Den Lauf beobachten, ohne einzugreifen: keine Taste, kein Prompt in irgendeinen Pane. Eskaliert der
   Orchestrator, die Eskalation mit Grund (bei `agent_blocked` mit `dialog`) und dem Stand von
   `lean-herdr plan show probe` im Bericht nennen und mit BLOCKED enden.

Expected, sobald der Orchestrator `done` meldet:

- `lean-herdr plan next probe` → `{"ok": true, "done": true}`
- `git -C ~/Scripts/lh-harden-probe log --oneline main` zeigt den Plan-Commit und mindestens einen
  Task-Commit, keinen Squash-Commit.
- `uv run pytest -q` in `~/Scripts/lh-harden-probe` → PASS.
- `lean-herdr plan show probe` → jede Task `done`.
- Keine Eskalation `agent_blocked`; kein Start eines Workers endete mit `agent_blocked`.
- Run: `herdr agent read <pane des Orchestrators> --source recent --lines 2000` — der Text enthält keinen
  ausgeführten Befehl `herdr agent` und keinen `herdr pane`.
- Nach höchstens 30 s: `git -C ~/Scripts/lh-harden-probe worktree list` nennt `plan/probe` nicht mehr, und
  `git -C ~/Scripts/lh-harden-probe branch --list plan/probe` ist leer.

Im Bericht: Anzahl der Aufträge je Schritt, Runden je Task, die `prereview`-Ergebnisse, jede Eskalation
und die Warnungen aus Schritt 3.5.

@call remember_decision("lean-herdr acceptance hardening: a one-task plan ran from spec to merge in ~/Scripts/lh-harden-probe without intervention; workspace init --trust-claude grants claude's folder trust for the root once and every worktree inherits it, dialogs come back as agent_blocked and are never answered, the teardown is merge --no-remove, workspace close, wt remove.")
@phase-end
