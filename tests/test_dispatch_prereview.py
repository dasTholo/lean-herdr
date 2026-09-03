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
    # Empty, so the store decides. Left alone, these tests read the real
    # $OPENROUTER_API_KEY of whatever machine runs them -- and one holding
    # a `"`, a backslash or a newline makes complete() refuse the key, which
    # would turn both rulings into `skipped` on that machine alone.
    monkeypatch.setattr("lean_herdr.llm.os.environ", {})

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
