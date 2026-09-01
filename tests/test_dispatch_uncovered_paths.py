"""Closes four proven test gaps in lean_herdr/dispatch.py (review findings).

1. dispatch()'s `cwd` parameter was never checked against what actually
   reaches Herdr.pane_split() -- every existing test leaves it at its
   default, so a silently ignored `cwd` would go unnoticed.
2. main()'s success path (canonical_root() does NOT raise) was never
   exercised; the only main() test in test_dispatch.py covers exclusively
   the crash-before-construction path.
3. wait_for_agent_id() -- and with it Herdr.pane_process_info() and the PID
   join in lean_herdr.join -- was never run for real; all 17 tests in
   test_dispatch.py inject `waiter=lambda *a, **kw: agent_id`.
4. The `pane_split_failed` branch is reachable but had no dedicated unit
   test.

Production code (lean_herdr/*.py, bin/herdr-dispatch) and the existing
tests/test_dispatch.py are untouched -- this file only adds new tests.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lean_herdr.dispatch import (
    DispatchRequest,
    dispatch,
    main,
    wait_for_agent_id,
)
from lean_herdr.herdr import Herdr
from lean_herdr.leanctx import LeanCtx
from tests.doubles import FakeProc, which_stub

ROOT = Path("/repo")
AGENT_ID = "mcp-2018183-70c877bf"


def make_request(**kwargs) -> DispatchRequest:
    base = {
        "role": "builder",
        "kind": "claude",
        "model": "sonnet",
        "role_file": Path("roles/builder.md"),
        "task_id": "T1",
        "task": "Build the foo function.",
    }
    return DispatchRequest(**{**base, **kwargs})  # ty: ignore[invalid-argument-type]


def make_registry(*messages: dict) -> dict:
    return {"agents": [{"agent_id": AGENT_ID, "pid": 42}], "scratchpad": list(messages)}


def make_reply(category: str = "result", task_id: str = "T1", **rest) -> dict:
    return {
        "id": "m1", "from_agent": AGENT_ID, "to_agent": "orch", "task_id": task_id,
        "category": category, "message": "done, three tests green",
        "project_root": str(ROOT), "timestamp": "2026-09-01T10:00:00Z", **rest,
    }


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
    monkeypatch.setattr("lean_herdr.leanctx.shutil.which", which_stub(True))
    h_proc, l_proc = FakeProc(), FakeProc()
    h_proc.replies = {("pane", "split"): {"result": {"pane": {"pane_id": "w1:p6"}}}}
    return h_proc, l_proc, tmp_path / "registry.json"


# -- Gap 1: dispatch()'s cwd parameter -------------------------------------


def test_dispatch_forwards_explicit_cwd_to_pane_split_not_root(world):
    """dispatch(cwd=...) must reach Herdr.pane_split() verbatim, not `root`.

    Mutation check (done outside the repo, see task report): setting
    `ziel_cwd = root` inside dispatch() turns this test red. Every one of
    the 17 tests in test_dispatch.py stays green under that mutation
    because none of them ever pass a `cwd` that differs from `root`.
    """
    h_proc, l_proc, registry_path = world
    other_cwd = Path("/worktrees/feat-auth")
    registry_path.write_text(json.dumps(make_registry(make_reply())), encoding="utf-8")

    dispatch(
        make_request(),
        herdr=Herdr(runner=h_proc),
        leanctx=LeanCtx(ROOT, runner=l_proc),
        root=ROOT,
        cwd=other_cwd,
        registry_path=registry_path,
        waiter=lambda *a, **kw: AGENT_ID,
    )

    split_call = next(c for c in h_proc.calls if c[1:3] == ["pane", "split"])
    assert split_call[split_call.index("--cwd") + 1] == str(other_cwd)
    assert str(ROOT) not in split_call


# -- Gap 2: main()'s success path stays hermetic ---------------------------


def test_main_success_path_never_touches_a_real_subprocess(monkeypatch, capsys):
    """main()'s normal path (canonical_root() does NOT raise) was only ever
    covered via the crash branch. This test proves the success path both
    produces a correct result and stays hermetic even if a future change
    drops the canonical_root() patch: subprocess.run/Popen are guarded
    globally, so any accidental real process attempt fails the test
    instead of starting real panes and agents, as happened once in review.
    """

    def _forbidden(*args, **kwargs):
        pytest.fail(f"main() attempted a real subprocess call: {args!r}")

    monkeypatch.setattr("subprocess.run", _forbidden)
    monkeypatch.setattr("subprocess.Popen", _forbidden)

    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
    monkeypatch.setattr("lean_herdr.leanctx.shutil.which", which_stub(True))
    monkeypatch.setattr("lean_herdr.dispatch.canonical_root", lambda *a, **kw: ROOT)

    h_proc, l_proc = FakeProc(), FakeProc()
    h_proc.replies = {
        ("agent", "list"): {
            "result": {"agents": [{"name": "builder", "pane_id": "w1:p6"}]}
        },
        ("pane", "process-info"): {"result": {"process_info": {"shell_pid": 4242}}},
    }
    registry = {
        "agents": [{"agent_id": AGENT_ID, "pid": 4242}],
        "scratchpad": [make_reply()],
    }
    monkeypatch.setattr("lean_herdr.dispatch.Herdr", lambda *a, **kw: Herdr(runner=h_proc))
    monkeypatch.setattr(
        "lean_herdr.dispatch.LeanCtx", lambda root: LeanCtx(root, runner=l_proc)
    )
    monkeypatch.setattr("lean_herdr.dispatch.read_registry", lambda *a, **kw: registry)

    code = main(
        [
            "builder", "--kind", "claude", "--model", "sonnet",
            "--role-file", "roles/builder.md", "--task-id", "T1", "--task", "x",
        ]
    )

    assert code == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1
    result = json.loads(lines[0])
    assert result == {
        "ok": True,
        "task_id": "T1",
        "pane": "w1:p6",
        "agent_id": AGENT_ID,
        "category": "result",
        "result": "done, three tests green",
    }


# -- Gap 3: wait_for_agent_id() run for real -------------------------------


def test_wait_for_agent_id_runs_the_real_pid_join(monkeypatch, tmp_path):
    """Runs wait_for_agent_id() for real: Herdr.pane_process_info() and the
    PID join in lean_herdr.join.resolve_agent_id() actually execute here,
    unlike in test_dispatch.py where `waiter=lambda *a, **kw: agent_id`
    bypasses all of it.
    """
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
    h_proc = FakeProc()
    h_proc.replies = {
        ("agent", "list"): {
            "result": {"agents": [{"name": "builder", "pane_id": "w1:p6"}]}
        },
        ("pane", "process-info"): {"result": {"process_info": {"shell_pid": 4242}}},
    }
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps({"agents": [{"agent_id": AGENT_ID, "pid": 4242}], "scratchpad": []}),
        encoding="utf-8",
    )

    agent_id = wait_for_agent_id(
        Herdr(runner=h_proc),
        "builder",
        registry_path=registry_path,
        sleep=lambda _s: pytest.fail("the pane is found on the very first check"),
    )

    assert agent_id == AGENT_ID
    assert h_proc.called_with("pane", "process-info", "--pane", "w1:p6")


def test_wait_for_agent_id_returns_none_when_no_pane_ever_appears(monkeypatch):
    """The 'not found' branch: no existing test drives this to completion."""
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
    h_proc = FakeProc()
    h_proc.replies = {("agent", "list"): {"result": {"agents": []}}}

    clock = iter([0.0, 10.0])  # first call sets the deadline, second is past it
    sleeps: list[float] = []

    agent_id = wait_for_agent_id(
        Herdr(runner=h_proc),
        "builder",
        timeout_s=1.0,
        interval_s=0.1,
        now=lambda: next(clock),
        sleep=sleeps.append,
    )

    assert agent_id is None
    assert sleeps == [], "the deadline was already past on the first check"


# -- Gap 4: pane_split_failed -----------------------------------------------


def test_dispatch_reports_pane_split_failed_when_herdr_gives_no_pane(
    monkeypatch, tmp_path
):
    """Herdr.pane_split() returning no pane_id must surface as
    pane_split_failed in the result -- and thus in the JSON line main()
    writes -- not silently continue or crash.
    """
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
    monkeypatch.setattr("lean_herdr.leanctx.shutil.which", which_stub(True))
    h_proc, l_proc = FakeProc(), FakeProc()
    h_proc.replies = {
        ("agent", "list"): {"result": {"agents": []}},
        ("pane", "split"): {"result": {}},  # no pane_id -> pane_split() returns None
    }
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(make_registry()), encoding="utf-8")

    result = dispatch(
        make_request(),
        herdr=Herdr(runner=h_proc),
        leanctx=LeanCtx(ROOT, runner=l_proc),
        root=ROOT,
        registry_path=registry_path,
        waiter=lambda *a, **kw: pytest.fail(
            "waiter must not run after a pane_split failure"
        ),
    )

    assert result == {
        "ok": False,
        "task_id": "T1",
        "pane": None,
        "agent_id": None,
        "error": "pane_split_failed",
    }
    json_line = json.dumps(result, ensure_ascii=False)
    assert '"error": "pane_split_failed"' in json_line
    assert '"ok": false' in json_line
    assert not any(c[1:3] == ["agent", "start"] for c in h_proc.calls)
