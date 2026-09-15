import json
from pathlib import Path

import pytest

from lean_herdr.orderlog import append, read_events, state_dir
from lean_herdr.orders import fold
from lean_herdr.report import (
    AGENT_ENV,
    ROLE_ENV,
    ReportError,
    current_branch,
    main,
    next_order,
    report,
    resolve_agent,
    show_order,
    worktree_stamp,
)
from tests.doubles import Completed, FakeProc

ROOT = Path("/repo")
ME = "builder-feat-x"
OTHER = "reviewer-feat-x"
ORCH = "orchestrator"


def order(tmp_path, task, *, to_agent=ME, description="build it", **payload):
    append(
        task,
        "created",
        ORCH,
        {"to_agent": to_agent, "description": description, **payload},
        orders=tmp_path,
    )
    return task


def _break_chain(orders_dir, task_id):
    """Tamper the sole committed event so the chain no longer verifies --
    the same trick test_orderlog.py's test_a_changed_body_breaks_the_chain
    uses, one level up.
    """
    (path,) = sorted((Path(orders_dir) / task_id / "events").glob("*.json"))
    body = json.loads(path.read_text(encoding="utf-8"))
    body["payload"]["description"] = "tampered"
    path.write_bytes(json.dumps(body, sort_keys=True, separators=(",", ":")).encode())


# -- identity ---------------------------------------------------------


def test_the_environment_name_wins_over_every_derivation():
    assert resolve_agent(root=ROOT, env={AGENT_ENV: ME, ROLE_ENV: "builder"}) == ME


def test_the_flag_beats_the_environment():
    assert resolve_agent("hand", root=ROOT, env={AGENT_ENV: ME}) == "hand"


def test_without_a_role_the_worker_stops_instead_of_guessing():
    """A guessed name reaches nobody, and the failure looks like a crash."""
    with pytest.raises(ReportError, match="no_role"):
        resolve_agent(root=ROOT, env={})


def test_the_fallback_derives_role_plus_branch(tmp_path, monkeypatch):
    monkeypatch.setattr("lean_herdr.report.current_branch", lambda *_a, **_k: "feat/lean-herdr")
    assert resolve_agent(root=tmp_path, env={ROLE_ENV: "builder"}) == "builder-feat-lean-herdr"


def test_a_detached_head_has_no_branch():
    assert current_branch(runner=lambda *_a, **_k: Completed(0, "HEAD\n", "")) == ""
    assert current_branch(runner=lambda *_a, **_k: Completed(1, "", "fatal")) == ""


# -- next -------------------------------------------------------------


def test_next_finds_the_open_order_for_this_agent(tmp_path):
    order(tmp_path, "o-a-1", to_agent=OTHER)
    order(tmp_path, "o-b-2", description="build the order log")
    result = next_order(ME, orders_dir=tmp_path)
    assert result["task_id"] == "o-b-2"
    assert "build the order log" in result["text"]
    assert f"<- {ORCH}" in result["text"], "the sender must be readable"


def test_next_skips_a_finished_order(tmp_path):
    order(tmp_path, "o-a-1")
    append("o-a-1", "completed", ME, {"message": "done"}, orders=tmp_path)
    assert next_order(ME, orders_dir=tmp_path)["task_id"] is None


def test_next_folds_in_the_predecessors_own_words(tmp_path):
    """The run-up is a reference, not a retelling."""
    order(tmp_path, "o-a-1", to_agent=OTHER)
    append(
        "o-a-1",
        "completed",
        OTHER,
        {"message": "VERDIKT: result\ntwo findings, both fixed"},
        orders=tmp_path,
    )
    order(tmp_path, "o-b-2", after="o-a-1")
    text = next_order(ME, orders_dir=tmp_path)["text"]
    assert "after: o-a-1 (reviewer-feat-x, completed)" in text
    assert "VERDIKT: result" in text


# -- the four writing commands ----------------------------------------


@pytest.mark.parametrize(
    ("command", "kind"),
    [("start", "working"), ("done", "completed"), ("fail", "failed"), ("ask", "input-required")],
)
def test_each_command_appends_its_own_kind(tmp_path, command, kind):
    order(tmp_path, "o-a-1")
    result = report(ME, command, "o-a-1", "a word", orders_dir=tmp_path)
    assert result["ok"] is True
    assert fold(read_events("o-a-1", orders=tmp_path)).state == kind


def test_a_worker_never_writes_on_a_foreign_order(tmp_path):
    order(tmp_path, "o-a-1", to_agent=OTHER)
    result = report(ME, "done", "o-a-1", "not mine", orders_dir=tmp_path)
    assert result["ok"] is False
    assert "addressed to reviewer-feat-x" in result["error"]
    assert len(read_events("o-a-1", orders=tmp_path)) == 1, "nothing was appended"


def test_a_finished_order_takes_no_further_event(tmp_path):
    order(tmp_path, "o-a-1")
    append("o-a-1", "completed", ME, {"message": "done"}, orders=tmp_path)
    assert "already completed" in report(ME, "done", "o-a-1", "again", orders_dir=tmp_path)["error"]


def test_an_unknown_event_kind_never_counts_as_terminal(tmp_path):
    """`is_terminal()` only names completed/failed/canceled -- an unknown
    kind must fold into a state of its own and still take a write. Same
    rule fold()'s own docstring holds for a format change: it must land on
    a visible state, never on a silent block.
    """
    order(tmp_path, "o-a-1")
    append("o-a-1", "vanished", ME, {}, orders=tmp_path)
    result = report(ME, "done", "o-a-1", "closing anyway", orders_dir=tmp_path)
    assert result["ok"] is True
    assert fold(read_events("o-a-1", orders=tmp_path)).state == "completed"


def test_an_unknown_order_is_not_found(tmp_path):
    assert report(ME, "start", "o-nope", "", orders_dir=tmp_path)["error"] == "task_not_found"


WT_LIST = {
    "items": [
        {"branch": "main", "head": {"sha": "0000"}, "worktree": {"current": False, "changes": {}}},
        {
            "branch": "plan/shop",
            "head": {"sha": "abc123"},
            "worktree": {
                "current": True,
                "changes": {"staged": False, "modified": True, "untracked": True},
            },
        },
    ]
}


def test_the_stamp_reads_head_and_set_flags_of_the_current_worktree():
    runner = FakeProc(replies={("list", "--format=json"): WT_LIST})
    assert worktree_stamp(runner=runner) == {"head": "abc123", "changes": ["modified", "untracked"]}
    assert runner.called_with("wt", "list", "--format=json")


@pytest.mark.parametrize(
    ("reply", "error"),
    [
        (Completed(returncode=1, stderr="not a repo"), "wt list exited 1: not a repo"),
        (Completed(stdout="no json"), "wt list printed no JSON"),
        ({"items": []}, "wt list names no current worktree with a head"),
        ({"items": "none"}, "wt list names no current worktree with a head"),
        (
            {"items": [{"worktree": "current", "head": {"sha": "abc"}}]},
            "wt list names no current worktree with a head",
        ),
        (
            {"items": [{"worktree": {"current": True}, "head": "abc"}]},
            "wt list names no current worktree with a head",
        ),
    ],
)
def test_a_stamp_that_cannot_be_taken_is_a_wt_error(reply, error):
    stamp = worktree_stamp(runner=FakeProc(replies={("list", "--format=json"): reply}))
    assert set(stamp) == {"wt_error"}
    assert stamp["wt_error"].startswith(error)


def test_a_missing_wt_is_a_wt_error_too():
    assert set(worktree_stamp(runner=FakeProc(raises=FileNotFoundError("wt")))) == {"wt_error"}


def test_undecodable_wt_output_is_a_wt_error_too():
    """`subprocess.run(..., text=True)` raises UnicodeDecodeError on non-UTF-8 output;
    `report` must stay successful even when `wt` fails this way too."""
    runner = FakeProc(raises=UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"))
    assert set(worktree_stamp(runner=runner)) == {"wt_error"}


@pytest.mark.parametrize(
    ("command", "stamped"), [("start", True), ("done", True), ("fail", False), ("ask", False)]
)
def test_start_and_done_carry_the_stamp(tmp_path, command, stamped):
    order(tmp_path, "o-a-1")
    report(
        ME,
        command,
        "o-a-1",
        "a word",
        orders_dir=tmp_path,
        stamper=lambda: {"head": "abc123", "changes": []},
    )
    payload = read_events("o-a-1", orders=tmp_path)[-1].payload
    assert ("head" in payload) is stamped


def test_a_refused_report_takes_no_stamp(tmp_path):
    order(tmp_path, "o-a-1", to_agent=OTHER)
    calls = []
    report(ME, "done", "o-a-1", "x", orders_dir=tmp_path, stamper=lambda: calls.append(1) or {})
    assert calls == []


# -- show -------------------------------------------------------------


def test_show_lists_the_answer_as_its_own_event(tmp_path):
    """The reason `show` exists: after a question, the answer stands here."""
    order(tmp_path, "o-a-1")
    append("o-a-1", "input-required", ME, {"message": "which branch strategy?"}, orders=tmp_path)
    append("o-a-1", "answered", ORCH, {"message": "feat/x, off main"}, orders=tmp_path)
    result = show_order(ME, "o-a-1", orders_dir=tmp_path)
    assert result["state"] == "working"
    assert [e["kind"] for e in result["events"]] == ["created", "input-required", "answered"]
    assert result["events"][-1]["message"] == "feat/x, off main"


# -- the CLI shell ----------------------------------------------------


def _one_json_line(capsys) -> dict:
    """Exactly one JSON line on stdout -- main()'s own contract, spelled
    out here so the broken-log guard tests below can lean on it instead
    of re-deriving it.
    """
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1
    return json.loads(lines[0])


@pytest.fixture
def main_root(tmp_path, monkeypatch):
    """Isolate main()'s own canonical_root()/state_dir() resolution under
    tmp_path -- report.py's twin of test_dispatch_await.py's own
    main_root fixture. Needed only by the broken-log guard tests below:
    those must prove the guard survives all the way through main(), not
    just through next_order()/report() called directly.
    """
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setenv("LEAN_CTX_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr("lean_herdr.report.canonical_root", lambda *a, **kw: root)
    monkeypatch.setenv(AGENT_ENV, ME)
    return root


def test_a_usage_error_is_a_json_line_and_exit_zero(capsys):
    assert main(["done", "--task", "o-a-1"]) == 0
    answer = json.loads(capsys.readouterr().out)
    assert answer["ok"] is False
    assert "done needs --message" in answer["error"]


def test_an_unknown_subcommand_lands_on_stdout_too(capsys):
    assert main(["note", "--task", "o-a-1"]) == 0
    answer = json.loads(capsys.readouterr().out)
    assert answer["ok"] is False
    assert answer["error"].startswith("usage_error")


def test_next_takes_no_flags(capsys):
    assert main(["next", "--task", "o-a-1"]) == 0
    assert "next does not take --task" in json.loads(capsys.readouterr().out)["error"]


def test_next_never_reads_a_broken_log_as_no_open_order(main_root, capsys):
    """The Global Constraint made concrete: a broken log is an error,
    never a 'nothing to do'. `next_order()` legitimately answers the
    {"ok": True, "task_id": None, "text": "no open order"} shape on an
    EMPTY log (test_next_skips_a_finished_order's sibling case) -- a
    destroyed one must come back looking nothing like it, the read path's
    own twin of test_dispatch_await.py's
    test_a_broken_chain_is_never_success_by_silence.
    """
    orders_dir = state_dir(main_root)
    order(orders_dir, "o-a-1")
    _break_chain(orders_dir, "o-a-1")
    assert main(["next"]) == 0
    result = _one_json_line(capsys)
    assert result["ok"] is False
    assert result["error"].startswith("chain_broken")
    assert result != {"ok": True, "agent": ME, "task_id": None, "text": "no open order"}
    # `next` folds EVERY order in the log, so the one that broke has to be
    # named -- nothing ever deletes an order, and without the id the
    # operator cannot tell which of them is blocking every worker.
    assert "o-a-1" in result["error"], result["error"]


def test_done_never_reads_a_broken_log_as_task_not_found(main_root, capsys):
    """report()'s own twin: a destroyed log must not fold into an empty
    Order and answer `task_not_found` -- that is `_mine()`'s \"nothing to
    act on\" shape (test_an_unknown_order_is_not_found), and a chain break
    is not the same thing as an order that never existed.
    """
    orders_dir = state_dir(main_root)
    order(orders_dir, "o-a-1")
    _break_chain(orders_dir, "o-a-1")
    assert main(["done", "--task", "o-a-1", "--message", "x"]) == 0
    result = _one_json_line(capsys)
    assert result["ok"] is False
    assert result["error"].startswith("chain_broken")
    assert result != {"ok": False, "task_id": "o-a-1", "error": "task_not_found"}
    assert "o-a-1" in result["error"], result["error"]


def test_main_stamps_start_and_done_with_the_real_worktree(main_root, monkeypatch, capsys):
    """`main` must pass `stamper=worktree_stamp` to `report()` -- removing that keyword
    leaves every other test in this file green, so it needs a test of its own.
    """
    orders_dir = state_dir(main_root)
    order(orders_dir, "o-a-1")
    monkeypatch.setattr(
        "lean_herdr.report.worktree_stamp",
        lambda *a, **kw: {"head": "abc1234", "changes": ["modified"]},
    )
    assert main(["start", "--task", "o-a-1"]) == 0
    assert _one_json_line(capsys)["ok"] is True
    assert main(["done", "--task", "o-a-1", "--message", "shipped"]) == 0
    assert _one_json_line(capsys)["ok"] is True
    payload = read_events("o-a-1", orders=orders_dir)[-1].payload
    assert payload["head"] == "abc1234"


def test_main_stamps_start_and_done_even_on_a_wt_error(main_root, monkeypatch, capsys):
    orders_dir = state_dir(main_root)
    order(orders_dir, "o-a-1")
    monkeypatch.setattr(
        "lean_herdr.report.worktree_stamp",
        lambda *a, **kw: {"wt_error": "wt list exited 1: boom"},
    )
    assert main(["start", "--task", "o-a-1"]) == 0
    assert _one_json_line(capsys)["ok"] is True
    assert main(["done", "--task", "o-a-1", "--message", "shipped"]) == 0
    assert _one_json_line(capsys)["ok"] is True
    payload = read_events("o-a-1", orders=orders_dir)[-1].payload
    assert "wt_error" in payload
