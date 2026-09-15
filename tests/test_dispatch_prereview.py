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
from lean_herdr.plancmd import PrereviewInput
from lean_herdr.settings import LlmSettings
from tests.doubles import Completed, FakeProc, which_stub

ROOT = Path("/repo")
WORKER = "builder-feat-x"
TASK_ID = "o-1a05e34cd15-1cf3b885"
BRANCH = "feat/x"
WORKTREES = {"result": {"worktrees": [{"branch": BRANCH, "path": "/worktrees/feat-x"}]}}


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
    append(
        TASK_ID,
        "created",
        "orchestrator",
        {"to_agent": WORKER, "description": "add a parser"},
        orders=tmp_path,
    )
    append(TASK_ID, "working", WORKER, {}, orders=tmp_path)
    append(TASK_ID, "completed", WORKER, {"message": message}, orders=tmp_path)
    return tmp_path


def no_network(*_a, **_kw):
    """The default `request` in here: reaching it is the bug, not the answer."""
    raise AssertionError("no test may reach the real endpoint")


def wait(
    herdr,
    tmp_path,
    *,
    prereview,
    runner,
    request=no_network,
    worktree=BRANCH,
    llm_cfg=None,
):
    return await_task(
        AwaitRequest(
            role="builder",
            kind="claude",
            task_id=TASK_ID,
            worktree=worktree,
            timeout_ms=300_000,
            prereview=prereview,
        ),
        herdr=herdr,
        root=ROOT,
        orders_dir=tmp_path,
        sleep=lambda _s: None,
        runner=runner,
        request=request,
        # NEVER None here: prereview() would then call file_settings(),
        # which runs a real `git rev-parse` and reads this checkout's own
        # .lean-ctx/lean-herdr/config.toml. In production main() hands the
        # validated block down; in a test we hand down an empty one.
        llm_cfg=llm_cfg if llm_cfg is not None else LlmSettings(),
    )


def llm_doubles(verdict_line: str, monkeypatch, tmp_path):
    """A `wt` double, an endpoint double and a key, so complete() runs.

    Two seams, because the wait mode has two: `runner` drives `wt step
    diff`, `request` is the model call. One double could stand in for both
    while the model call went through curl; it cannot now.
    """
    store = tmp_path / "auth.json"
    store.write_text(json.dumps({"openrouter": {"key": "k"}}))
    monkeypatch.setattr("lean_herdr.openrouter.AUTH_PATH", store)
    # Empty, so the store decides. Left alone, these tests read the real
    # $OPENROUTER_API_KEY of whatever machine runs them -- and one holding
    # a `"`, a backslash or a newline makes complete() refuse the key, which
    # would turn both rulings into `skipped` on that machine alone.
    monkeypatch.setattr("lean_herdr.llm.os.environ", {})

    def runner(_cmd, **_kw):
        return Completed(stdout="diff --git a/x b/x\n+print('debug')")

    def request(_url, **_kw):
        return openrouter(verdict_line)

    return runner, request


def test_without_the_flag_the_answer_is_the_one_from_before(herdr, tmp_path):
    def runner(*_a, **_kw):
        raise AssertionError("no pre-review may run without --prereview")

    result = wait(herdr, completed_log(tmp_path), prereview=False, runner=runner)
    assert result["ok"] is True
    assert result["state"] == "completed"
    assert "prereview" not in result
    assert "prereview_note" not in result


def test_a_rejection_stands_beside_the_verdict_never_instead(herdr, tmp_path, monkeypatch):
    runner, request = llm_doubles(
        "PREREVIEW: reject\ndebug leftover: print()", monkeypatch, tmp_path
    )
    result = wait(
        herdr,
        completed_log(tmp_path, "VERDIKT: result\nall green"),
        prereview=True,
        runner=runner,
        request=request,
    )
    assert result["verdict"] == "result", "the strong reviewer keeps its key"
    assert result["prereview"] == "reject"
    assert result["prereview_note"] == "debug leftover: print()"
    assert result["ok"] is True, "a pre-review is not a failure of the order"


def test_a_pass_changes_nothing_about_the_answer(herdr, tmp_path, monkeypatch):
    runner, request = llm_doubles("PREREVIEW: pass", monkeypatch, tmp_path)
    result = wait(
        herdr,
        completed_log(tmp_path),
        prereview=True,
        runner=runner,
        request=request,
    )
    assert result["prereview"] == "pass"
    assert result["ok"] is True
    assert result["state"] == "completed"


@pytest.mark.parametrize("state", ["failed", "canceled", "input-required"])
def test_the_pre_review_only_runs_on_completed(herdr, tmp_path, state):
    def runner(*_a, **_kw):
        raise AssertionError(f"nothing may run on {state}")

    append(
        TASK_ID,
        "created",
        "orchestrator",
        {"to_agent": WORKER, "description": "d"},
        orders=tmp_path,
    )
    append(TASK_ID, state, WORKER, {"message": "m"}, orders=tmp_path)
    result = wait(herdr, tmp_path, prereview=True, runner=runner)
    assert "prereview" not in result


def test_a_broken_pre_review_is_skipped_never_a_rejection(herdr, tmp_path, monkeypatch):
    # os.environ has to be patched process-wide, not handed in as
    # `env={}`: dispatch passes only `runner` and `request` down, so this
    # is the one grip on the key resolution from out here. Do not
    # "simplify" it.
    monkeypatch.setattr("lean_herdr.openrouter.AUTH_PATH", tmp_path / "absent.json")
    monkeypatch.setattr("lean_herdr.llm.os.environ", {})
    result = wait(
        herdr,
        completed_log(tmp_path),
        prereview=True,
        runner=lambda *a, **k: Completed(stdout="diff --git a/x b/x"),
    )
    assert result["prereview"] == "skipped"
    assert result["prereview_note"] == "no_answer"


def test_the_flag_needs_await_and_a_worktree():
    parse = build_parser().parse_args
    assert (
        missing_flags(
            parse(
                [
                    "builder",
                    "--kind",
                    "claude",
                    "--model",
                    "sonnet",
                    "--role-file",
                    "roles/builder.md",
                    "--prereview",
                ]
            )
        )
        == "build mode does not take --prereview"
    )
    assert (
        missing_flags(
            parse(["builder", "--kind", "claude", "--await", "--task-id", TASK_ID, "--prereview"])
        )
        == "--prereview needs --worktree"
    )
    assert (
        missing_flags(parse(["order", "--to", WORKER, "--message", "m", "--prereview"]))
        == "`order` does not take --prereview"
    )


def test_a_stray_flag_is_a_json_line_not_an_exit_code(capsys):
    assert main(["order", "--to", WORKER, "--message", "m", "--prereview"]) == 0
    answer = json.loads(capsys.readouterr().out)
    assert answer["ok"] is False
    assert "--prereview" in answer["error"]


def plan_log(tmp_path):
    append(
        TASK_ID,
        "created",
        "orchestrator",
        {
            "to_agent": WORKER,
            "description": "Task 1 of plan shop",
            "plan": "shop",
            "step": "implement",
            "plan_task": "1",
        },
        orders=tmp_path,
    )
    append(TASK_ID, "working", WORKER, {"head": "aaa1111", "changes": []}, orders=tmp_path)
    append(
        TASK_ID,
        "completed",
        WORKER,
        {"message": "done", "head": "ddd1111", "changes": []},
        orders=tmp_path,
    )
    return tmp_path


def test_a_plan_order_is_judged_with_what_plancmd_picks(herdr, tmp_path, monkeypatch):
    asked = {}

    def fake_input(order, **kwargs):
        asked.update(order_id=order.id, **kwargs)
        return PrereviewInput(order="the rendered task 1", base="aaa1111")

    monkeypatch.setattr("lean_herdr.plancmd.prereview_input", fake_input)
    runner, request = llm_doubles("PREREVIEW: pass", monkeypatch, tmp_path)
    seen, bodies = [], []

    def recording_runner(cmd, **kw):
        seen.append(list(cmd))
        return runner(cmd, **kw)

    def recording_request(url, **kw):
        bodies.append(kw.get("body") or "")
        return request(url, **kw)

    result = wait(
        herdr,
        plan_log(tmp_path),
        prereview=True,
        runner=recording_runner,
        request=recording_request,
    )
    assert result["prereview"] == "pass"
    assert seen == [["wt", "-C", "/worktrees/feat-x", "step", "diff", "aaa1111"]]
    assert "the rendered task 1" in bodies[0]
    assert "Task 1 of plan shop" not in bodies[0]
    assert (asked["order_id"], asked["branch"], asked["root"]) == (TASK_ID, BRANCH, ROOT)


def test_a_skip_from_plancmd_is_the_answer_and_nothing_runs(herdr, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "lean_herdr.plancmd.prereview_input",
        lambda order, **_kw: PrereviewInput(skip="no_start_head"),
    )

    def runner(*_a, **_kw):
        raise AssertionError("a skipped pre-review runs no wt")

    result = wait(herdr, plan_log(tmp_path), prereview=True, runner=runner)
    assert result["ok"] is True
    assert result["prereview"] == "skipped"
    assert result["prereview_note"] == "no_start_head"


def test_an_order_outside_a_plan_never_asks_plancmd(herdr, tmp_path, monkeypatch):
    def refuse(*_a, **_kw):
        raise AssertionError("an order without a plan must not reach plancmd")

    monkeypatch.setattr("lean_herdr.plancmd.prereview_input", refuse)
    runner, request = llm_doubles("PREREVIEW: pass", monkeypatch, tmp_path)
    result = wait(herdr, completed_log(tmp_path), prereview=True, runner=runner, request=request)
    assert result["prereview"] == "pass"
