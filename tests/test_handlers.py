import functools
import json
import subprocess
import sys
from pathlib import Path

import pytest

from lean_herdr import handlers, workspace
from lean_herdr.config import Config
from tests.doubles import FakeProc, which_stub

#: `lean-ctx call` prints plain text -- as a str it goes through FakeProc to
#: stdout verbatim.
RESUME = (
    "--- SESSION RESUME (post-compaction) ---\n"
    "Project: lean-herdr\n"
    "Task: build lean-herdr\n"
    "Key findings: scratchpad instead of messages\n"
    "---"
)
LEDGER = "Handoff Ledgers (1):\n  1. /handoffs/new.json"


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
    monkeypatch.setattr("lean_herdr.leanctx.shutil.which", which_stub(True))
    monkeypatch.setattr("lean_herdr.handlers.canonical_root", lambda cwd: Path("/repo"))
    h_proc, l_proc = FakeProc(), FakeProc()
    l_proc.replies = {
        ("call", "ctx_session"): RESUME,
        ("call", "ctx_handoff"): LEDGER,
    }
    monkeypatch.setattr("lean_herdr.handlers.Herdr", lambda *a, **kw: __import__(
        "lean_herdr.herdr", fromlist=["Herdr"]
    ).Herdr(runner=h_proc))
    monkeypatch.setattr("lean_herdr.handlers.LeanCtx", lambda root, **kw: __import__(
        "lean_herdr.leanctx", fromlist=["LeanCtx"]
    ).LeanCtx(root, runner=l_proc))
    return h_proc, l_proc, tmp_path


def cfg(tmp_path: Path, **rest) -> Config:
    env = {
        "HERDR_PLUGIN_STATE_DIR": str(tmp_path / "state"),
        "HERDR_PANE_ID": "w2:p2",
        "HERDR_WORKSPACE_ID": "w2",
        **rest,
    }
    return Config.from_env(env)


def test_pane_detected_writes_the_digest_and_sets_the_ctx_token(world):
    h_proc, _, tmp_path = world
    c = cfg(tmp_path, HERDR_PLUGIN_EVENT_JSON=json.dumps(
        {"pane_id": "w2:p2", "pane": {"cwd": "/repo.feat"}}
    ))
    handlers.handle_pane_detected(c)
    digest = tmp_path / "state" / "w2:p2.md"
    assert digest.is_file()
    assert "build lean-herdr" in digest.read_text(encoding="utf-8")
    # The id is POSITIONAL, not --pane: herdr.report_metadata() measured that
    # against 0.8.2 and the predecessor plan's assertion never caught up.
    assert h_proc.called_with(
        "pane", "report-metadata", "w2:p2", "--source", "lean.herdr",
        "--token", "ctx=build lean-herdr",
    )


def test_the_cwd_goes_through_canonical_root(world, monkeypatch):
    """B12: a raw worktree cwd opens a lean-ctx project of its own."""
    _, l_proc, tmp_path = world
    seen: list[Path] = []
    monkeypatch.setattr(
        "lean_herdr.handlers.canonical_root",
        lambda cwd: (seen.append(Path(cwd)), Path("/repo"))[1],
    )
    handlers.handle_pane_detected(cfg(tmp_path, HERDR_PLUGIN_EVENT_JSON=json.dumps(
        {"pane_id": "w2:p2", "pane": {"cwd": "/repo.feat-auth"}}
    )))
    assert seen == [Path("/repo.feat-auth")]
    # Three calls carry the flag -- resume, handoff list, handoff show. Every
    # one of them must carry the SAME canonical root; the predecessor plan
    # unpacked a single call and would have died on the other two.
    roots = [c[c.index("--project-root") + 1] for c in l_proc.calls if "--project-root" in c]
    assert len(roots) == 3, roots
    assert set(roots) == {"/repo"}


def test_without_lean_ctx_nothing_happens_and_nothing_breaks(monkeypatch, tmp_path):
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
    monkeypatch.setattr("lean_herdr.leanctx.shutil.which", which_stub(False))
    monkeypatch.setattr("lean_herdr.handlers.canonical_root", lambda cwd: Path("/repo"))
    h_proc, l_proc = FakeProc(), FakeProc()
    monkeypatch.setattr("lean_herdr.handlers.Herdr", lambda *a, **kw: __import__(
        "lean_herdr.herdr", fromlist=["Herdr"]
    ).Herdr(runner=h_proc))
    monkeypatch.setattr("lean_herdr.handlers.LeanCtx", lambda root, **kw: __import__(
        "lean_herdr.leanctx", fromlist=["LeanCtx"]
    ).LeanCtx(root, runner=l_proc))
    for handler in (
        handlers.handle_workspace_created,
        handlers.handle_pane_detected,
        handlers.handle_status_changed,
        handlers.handle_inject,
        handlers.handle_bootstrap,
    ):
        handler(cfg(tmp_path, HERDR_PLUGIN_EVENT_JSON=json.dumps({"pane": {"cwd": "/repo"}})))
    assert l_proc.calls == [], "without lean-ctx there must be no call"
    assert not any("--token" in c for c in h_proc.calls), "no token without context"


# -- The three nothing-cases, each with its own behaviour ----------------


def test_an_empty_session_state_stays_silent(world, capsys):
    """Fresh project: no token, no digest -- and NO note."""
    h_proc, l_proc, tmp_path = world
    l_proc.replies = {("call", "ctx_session"): ""}
    handlers.handle_pane_detected(cfg(tmp_path, HERDR_PLUGIN_EVENT_JSON=json.dumps(
        {"pane_id": "w2:p2", "pane": {"cwd": "/repo"}}
    )))
    assert not any("--token" in c for c in h_proc.calls)
    assert not (tmp_path / "state" / "w2:p2.md").exists()
    assert capsys.readouterr().err == "", "empty is not an error"


def test_an_error_from_lean_ctx_leaves_a_note(world, capsys):
    """Broken is not empty -- here a line MUST appear in the plugin log."""
    h_proc, l_proc, tmp_path = world
    l_proc.replies = {("call", "ctx_session"): "error: -32603: internal"}
    handlers.handle_pane_detected(cfg(tmp_path, HERDR_PLUGIN_EVENT_JSON=json.dumps(
        {"pane_id": "w2:p2", "pane": {"cwd": "/repo"}}
    )))
    assert not any("--token" in c for c in h_proc.calls)
    assert "ctx_session resume" in capsys.readouterr().err


def test_a_timeout_leaves_a_note(world, capsys):
    import subprocess

    _, l_proc, tmp_path = world
    l_proc.raises = subprocess.TimeoutExpired(cmd=["lean-ctx"], timeout=1)
    handlers.handle_pane_detected(cfg(tmp_path, HERDR_PLUGIN_EVENT_JSON=json.dumps(
        {"pane_id": "w2:p2", "pane": {"cwd": "/repo"}}
    )))
    assert "timeout" in capsys.readouterr().err


def test_no_handler_touches_the_esc_token(world):
    h_proc, _, tmp_path = world
    handlers.handle_pane_detected(cfg(tmp_path, HERDR_PLUGIN_EVENT_JSON=json.dumps(
        {"pane_id": "w2:p2", "pane": {"cwd": "/repo"}}
    )))
    assert not any("esc" in " ".join(c) for c in h_proc.calls), (
        "esc belongs to the orchestrator -- two writers on one token are a "
        "silent conflict"
    )


def test_workspace_created_sets_the_token_on_the_workspace(world):
    h_proc, _, tmp_path = world
    handlers.handle_workspace_created(cfg(tmp_path, HERDR_PLUGIN_EVENT_JSON=json.dumps(
        {"workspace_id": "w2", "workspace": {"cwd": "/repo"}}
    )))
    assert h_proc.called_with(
        "workspace", "report-metadata", "w2", "--source", "lean.herdr"
    )


def test_inject_sends_the_digest_without_wait(world):
    h_proc, _, tmp_path = world
    path = tmp_path / "state" / "w2:p2.md"
    path.parent.mkdir(parents=True)
    path.write_text("# lean-ctx context\n\n**Task:** keep building\n", encoding="utf-8")
    h_proc.replies = {
        ("agent", "list"): {"result": {"agents": [{"name": "builder", "pane_id": "w2:p2"}]}}
    }
    handlers.handle_inject(cfg(tmp_path))
    prompt = next(c for c in h_proc.calls if c[1:3] == ["agent", "prompt"])
    assert "keep building" in " ".join(prompt)
    assert "--wait" not in prompt


def test_inject_without_a_digest_reports_visibly(world):
    h_proc, _, tmp_path = world
    handlers.handle_inject(cfg(tmp_path))
    assert h_proc.called_with("notification", "show"), (
        "automation fails silently, a deliberate gesture visibly"
    )


def test_bootstrap_starts_the_orchestrator_in_its_own_workspace(world, monkeypatch):
    h_proc, _, tmp_path = world
    h_proc.replies = {
        # The core reads the RAW `workspace list`. Without an answer the reply
        # is `{}`, which reads as a dead socket -- it would stop before the
        # split this test is about.
        ("workspace", "list"): {"result": {"workspaces": []}},
        ("pane", "list"): {"result": {"panes": [{"pane_id": "w2:p1"}]}},
        ("pane", "split"): {"result": {"pane": {"pane_id": "w2:p9"}}},
    }
    # The waiter is INJECTED, not patched at module level: `waiter` is a
    # default argument of start_orchestrator, bound when that function was
    # defined, so monkeypatching lean_herdr.workspace.wait_for_agent_id would
    # never reach it. Left alone the real waiter sleeps out the capped
    # KEYSTROKE_READY_TIMEOUT_S. An ("agent", "list") reply is no way out:
    # the same call carries the duplicate check and would skip the split.
    #
    # The target is `lean_herdr.workspace`, not `lean_herdr.handlers`:
    # handle_bootstrap imports the name ON THE CALL, so `handlers` never
    # holds one to patch. test_bootstrap_resolves_start_orchestrator_at_
    # call_time keeps that seam honest.
    monkeypatch.setattr(
        "lean_herdr.workspace.start_orchestrator",
        functools.partial(workspace.start_orchestrator, waiter=lambda *a, **k: "mcp-42"),
    )
    handlers.handle_bootstrap(cfg(tmp_path, HERDR_PLUGIN_EVENT_JSON=json.dumps(
        {"workspace_id": "w2", "workspace": {"cwd": "/repo"}}
    )))
    split = next(c for c in h_proc.calls if c[1:3] == ["pane", "split"])
    assert "--pane" in split and "w2:p1" in split, "the pane belongs in THIS workspace"
    assert "LEAN_CTX_TOOL_PROFILE=minimal" in split
    start = next(c for c in h_proc.calls if c[1:3] == ["agent", "start"])
    assert "orch" in start and "opencode" in start
    assert not h_proc.called_with("workspace", "create"), h_proc.flat()


def test_bootstrap_does_not_start_a_second_orchestrator(world):
    h_proc, _, tmp_path = world
    h_proc.replies = {
        ("workspace", "list"): {"result": {"workspaces": []}},
        ("agent", "list"): {"result": {"agents": [{"name": "orch", "pane_id": "w2:p9"}]}},
        # An anchor pane and a split reply are present on purpose: without them
        # the handler would skip the split for lack of an anchor, and the test
        # would stay green even with the duplicate guard removed.
        ("pane", "list"): {"result": {"panes": [{"pane_id": "w2:p1"}]}},
        ("pane", "split"): {"result": {"pane": {"pane_id": "w2:p9"}}},
    }
    handlers.handle_bootstrap(cfg(tmp_path, HERDR_PLUGIN_EVENT_JSON=json.dumps(
        {"workspace_id": "w2", "workspace": {"cwd": "/repo"}}
    )))
    assert not any(c[1:3] == ["pane", "split"] for c in h_proc.calls)
    note = next(c for c in h_proc.calls if c[1:3] == ["notification", "show"])
    assert "already running" in " ".join(note), note


def test_bootstrap_without_git_on_the_path_notifies_like_every_other_failure(
    world, monkeypatch
):
    """`canonical_root()` shells out to git -- no git is a bare OSError.

    initcmd.py reads that same call the same way and answers it with
    `init_stopped`. Caught here only as `(BusError, SettingsError)` it
    escapes to `__main__`'s catch-all instead, and the operator gets a
    stderr line in the plugin log where every other failure path in this
    handler shows a notification.
    """
    h_proc, _, tmp_path = world
    monkeypatch.setattr(
        "lean_herdr.handlers.canonical_root",
        lambda cwd: (_ for _ in ()).throw(
            FileNotFoundError(2, "No such file or directory", "git")
        ),
    )
    handlers.handle_bootstrap(cfg(tmp_path, HERDR_PLUGIN_EVENT_JSON=json.dumps(
        {"workspace_id": "w2", "workspace": {"cwd": "/repo"}}
    )))
    note = next(c for c in h_proc.calls if c[1:3] == ["notification", "show"])
    assert "git" in " ".join(note), note


def test_importing_handlers_does_not_drag_in_the_workspace_subtree():
    """Every plugin event pays for this import -- and one of them fires constantly.

    `pane.agent_status_changed` runs `python3 -m lean_herdr <sub>` again and
    again, and each run imports this module. Measured 2026-09-04:
    `import lean_herdr.handlers` cost 42.2 ms, of which the
    workspace -> dispatch -> ordercmd -> orderlog/llm subtree was 10.7 ms --
    paid on every event for a name only `handle_bootstrap` ever uses.

    A subprocess, because `sys.modules` in this process is long past the
    question: pytest has imported `lean_herdr.workspace` for other tests.
    """
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import lean_herdr.handlers, sys;"
                "print('lean_herdr.workspace' in sys.modules)"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    assert proc.stdout.strip() == "False", proc.stdout + proc.stderr


def test_bootstrap_resolves_start_orchestrator_at_call_time(world, monkeypatch):
    """The seam is the DEFINING module, because the import sits on the call.

    With a function-local import the name never lands in `handlers`, so a
    patch aimed there would quietly stop biting: every bootstrap test would
    keep passing while running the real waiter. This test fails the moment
    that happens -- on the patch below AND on the assertion under it.
    """
    _, _, tmp_path = world
    seen: list[dict] = []
    monkeypatch.setattr(
        "lean_herdr.workspace.start_orchestrator",
        lambda **kwargs: (seen.append(kwargs), {"ok": True})[1],
    )
    handlers.handle_bootstrap(cfg(tmp_path, HERDR_PLUGIN_EVENT_JSON=json.dumps(
        {"workspace_id": "w2", "workspace": {"cwd": "/repo"}}
    )))
    assert [k["workspace_id"] for k in seen] == ["w2"]
    assert not hasattr(handlers, "start_orchestrator"), (
        "a module-level name would make the patch above a no-op"
    )


def test_main_catches_every_exception_and_ends_with_0(monkeypatch, capsys):
    """The monkeypatch bites ONLY because __main__ resolves the handler by NAME.

    Were HANDLERS to hold the function object, main() would still pull the old
    function -- the test would run green without checking anything.
    """
    from lean_herdr.__main__ import main

    monkeypatch.setattr(
        handlers, "handle_pane_detected",
        lambda cfg: (_ for _ in ()).throw(RuntimeError("broken")),
    )
    assert main(["pane-detected"]) == 0
    assert "broken" in capsys.readouterr().err
