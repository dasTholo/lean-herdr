import json
from pathlib import Path

import pytest

from lean_herdr.dispatch import (
    DispatchRequest,
    agent_args,
    agent_name,
    dispatch,
    main,
    profile_for,
)
from lean_herdr.herdr import Herdr
from tests.doubles import FakeProc, which_stub

ROOT = Path("/repo")
AGENT_ID = "mcp-2018183-70c877bf"


def req(**kwargs) -> DispatchRequest:
    base = {
        "role": "builder",
        "kind": "claude",
        "model": "sonnet",
        "role_file": Path("roles/builder.md"),
    }
    return DispatchRequest(**{**base, **kwargs})  # ty: ignore[invalid-argument-type]


def registry() -> dict:
    return {"agents": [{"agent_id": AGENT_ID, "pid": 42}]}


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
    monkeypatch.setattr("lean_herdr.leanctx.shutil.which", which_stub(True))
    h_proc, l_proc = FakeProc(), FakeProc()
    h_proc.replies = {("pane", "split"): {"result": {"pane": {"pane_id": "w1:p6"}}}}
    return h_proc, l_proc, tmp_path / "registry.json"


def run_dispatch(world, *, reg: dict, request=None, agent_id: str | None = AGENT_ID, **kwargs):
    h_proc, _, path = world
    path.write_text(json.dumps(reg), encoding="utf-8")
    return dispatch(
        request or req(),
        herdr=Herdr(runner=h_proc),
        root=ROOT,
        registry_path=path,
        waiter=lambda *a, **kw: agent_id,
        **kwargs,
    )


def test_profil_folgt_der_rolle_und_laesst_sich_ueberschreiben():
    assert profile_for("orchestrator") == "minimal"
    assert profile_for("builder") == "standard"
    assert profile_for("reviewer") == "standard"
    assert profile_for("builder", "minimal") == "minimal"


def test_agentenname_ist_branch_UND_rolle():
    """Ein Reviewer-Dispatch darf nie den laufenden Builder desselben Branches treffen."""
    assert agent_name("builder") == "builder"
    assert agent_name("builder", "feat/auth") == "builder-feat-auth"
    assert agent_name("reviewer", "feat/auth") == "reviewer-feat-auth"
    assert agent_name("builder", "feat/auth") != agent_name("reviewer", "feat/auth")


def test_the_role_prompt_travels_as_a_file_never_as_text():
    args = agent_args("claude", "sonnet", Path("roles/builder.md"))
    assert args == ["--model", "sonnet", "--append-system-prompt-file", "roles/builder.md"]
    assert not any("\n" in a for a in args), "Herdr rejects multi-line arguments (H2)"


def test_build_mode_returns_pane_and_agent_id_and_creates_nothing(world):
    """The build mode is finished the moment the agent_id is resolved."""
    h_proc, _, _ = world
    result = run_dispatch(world, reg=registry())
    assert result == {"ok": True, "pane": "w1:p6", "agent_id": AGENT_ID}
    assert h_proc.called_with("agent", "start"), "the worker is running"
    assert not h_proc.called_with("agent", "prompt", "--wait"), (
        "the build mode neither rings nor waits"
    )


def test_the_profile_is_set_on_the_pane_not_on_the_agent(world):
    h_proc, _, _ = world
    run_dispatch(world, reg=registry())
    assert h_proc.called_with("--env", "LEAN_CTX_TOOL_PROFILE=standard")
    assert h_proc.called_with("--env", "LEAN_CTX_ROLE=builder")
    start = next(c for c in h_proc.calls if c[1:3] == ["agent", "start"])
    assert "--env" not in start, "agent start knows no --env (H9)"


def test_an_existing_agent_is_reused_and_cleared(world):
    h_proc, _, _ = world
    h_proc.replies = {
        ("agent", "list"): {"result": {"agents": [{"name": "builder", "pane_id": "w1:p6"}]}},
    }
    result = run_dispatch(world, reg=registry())
    assert result["pane"] == "w1:p6"
    assert not any(c[1:3] == ["pane", "split"] for c in h_proc.calls)
    clear = next(c for c in h_proc.calls if "/clear" in c)
    assert "--wait" not in clear, "/clear without --wait (H4)"


def test_without_an_agent_id_the_script_reports_an_error(world):
    assert run_dispatch(world, reg=registry(), agent_id=None)["error"] == "no_agent_id"


def test_main_writes_one_json_line_and_exits_0(capsys, monkeypatch):
    monkeypatch.setattr(
        "lean_herdr.dispatch.canonical_root",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("no repo")),
    )
    code = main(
        ["builder", "--kind", "claude", "--model", "sonnet",
         "--role-file", "roles/builder.md"]
    )
    assert code == 0, "the orchestrator reads ok, not the exit code"
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1
    result = json.loads(lines[0])
    assert result["ok"] is False and result["error"].startswith("dispatch_crashed")


def test_a_worktree_dispatch_starts_the_pane_in_the_worktree(world, monkeypatch):
    h_proc, _, _ = world
    h_proc.replies = {
        ("pane", "split"): {"result": {"pane": {"pane_id": "w2:p2"}}},
        ("pane", "list"): {"result": {"panes": [{"pane_id": "w2:p1"}]}},
        ("worktree", "list"): {
            "result": {
                "source": {"repo_root": "/repo"},
                "worktrees": [
                    {"branch": "feat/auth", "path": "/repo.feat-auth",
                     "open_workspace_id": "w2"}
                ],
            }
        },
    }
    result = run_dispatch(world, reg=registry(), request=req(worktree="feat/auth"))
    assert result["ok"] is True
    assert h_proc.called_with("--cwd", "/repo.feat-auth"), "the worker lives in the worktree"
    start = next(c for c in h_proc.calls if c[1:3] == ["agent", "start"])
    assert "builder-feat-auth" in start


def test_a_worktree_dispatch_splits_a_pane_of_that_workspace(world):
    """Otherwise the worker would sit in the orchestrator workspace and survive teardown."""
    h_proc, _, _ = world
    h_proc.replies = {
        ("pane", "split"): {"result": {"pane": {"pane_id": "w2:p2"}}},
        ("pane", "list"): {"result": {"panes": [{"pane_id": "w2:p1"}]}},
        ("worktree", "list"): {
            "result": {
                "source": {"repo_root": "/repo"},
                "worktrees": [
                    {"branch": "feat/auth", "path": "/repo.feat-auth",
                     "open_workspace_id": "w2"}
                ],
            }
        },
    }
    run_dispatch(world, reg=registry(), request=req(worktree="feat/auth"))
    split = next(c for c in h_proc.calls if c[1:3] == ["pane", "split"])
    assert "--pane" in split and "w2:p1" in split
    assert "--current" not in split


def test_a_worktree_without_an_anchor_pane_aborts(world):
    h_proc, _, _ = world
    h_proc.replies = {
        ("pane", "list"): {"result": {"panes": []}},
        ("worktree", "list"): {
            "result": {
                "source": {"repo_root": "/repo"},
                "worktrees": [
                    {"branch": "feat/auth", "path": "/repo.feat-auth",
                     "open_workspace_id": "w2"}
                ],
            }
        },
    }
    result = run_dispatch(world, reg=registry(), request=req(worktree="feat/auth"))
    assert result["ok"] is False and result["error"] == "no_anchor_pane"


def test_a_missing_worktrunk_reports_worktrunk_missing(world, monkeypatch):
    monkeypatch.setattr("lean_herdr.worktree.shutil.which", lambda _b: None)
    h_proc, _, _ = world
    h_proc.replies = {
        ("worktree", "list"): {"result": {"source": {"repo_root": "/repo"}, "worktrees": []}},
    }
    result = run_dispatch(world, reg=registry(), request=req(worktree="feat/neu"))
    assert result["error"] == "worktrunk_missing"
