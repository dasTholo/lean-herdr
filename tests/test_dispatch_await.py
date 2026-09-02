import json
from pathlib import Path

import pytest

from lean_herdr.dispatch import (
    DEFAULT_TIMEOUT_MS,
    AwaitRequest,
    await_task,
    main,
    verdict,
)
from lean_herdr.herdr import Herdr
from tests.doubles import FakeProc, which_stub

ROOT = Path("/repo")
WORKER = "mcp-2018183-70c877bf"
TASK_ID = "task-1a05e34cd15-1cf3b885"


def message(role: str, text: str) -> dict:
    return {"role": role, "parts": [{"type": "text", "text": text}]}


def raw_task(state: str = "Working", *, reply: str | None = None) -> dict:
    messages = [message("orch", "build foo")]
    if reply is not None:
        messages.append(message(WORKER, reply))
    return {
        "id": TASK_ID, "from_agent": "orch", "to_agent": WORKER,
        "state": state, "description": "build foo", "messages": messages,
        "artifacts": [], "history": [], "metadata": {},
        "created_at": "2026-09-02T10:00:00Z", "updated_at": "2026-09-02T10:05:00Z",
    }


@pytest.fixture
def herdr(monkeypatch):
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
    proc = FakeProc()
    proc.replies = {("agent", "list"): {"result": {"agents": []}}}
    return Herdr(runner=proc), proc


def wait(
    herdr, tmp_path, *tasks, timeout_ms=300_000, role="builder", worktree=None, **rest
):
    path = tmp_path / "tasks.json"
    path.write_text(
        json.dumps({"tasks": list(tasks), "updated_at": ""}), encoding="utf-8"
    )
    h, _ = herdr
    return await_task(
        AwaitRequest(
            role=role,
            kind="claude",
            task_id=TASK_ID,
            worktree=worktree,
            timeout_ms=timeout_ms,
        ),
        herdr=h,
        root=ROOT,
        tasks_path=path,
        sleep=lambda _s: None,
        **rest,
    )


def test_completed_is_success_with_the_closing_message(herdr, tmp_path):
    result = wait(herdr, tmp_path, raw_task("Completed", reply="done, three tests green"))
    assert result["ok"] is True
    assert result["state"] == "completed"
    assert result["message"] == "done, three tests green"
    assert "verdict" not in result


def test_an_already_terminal_state_does_not_ring_at_all(herdr, tmp_path):
    """The orchestrator may repeat --await safely."""
    _, proc = herdr
    wait(herdr, tmp_path, raw_task("Completed", reply="done"))
    assert not proc.called_with("agent", "prompt")


def test_failed_carries_the_workers_reason(herdr, tmp_path):
    result = wait(herdr, tmp_path, raw_task("Failed", reply="test 4 cannot be fixed"))
    assert result["ok"] is False
    assert result["error"] == "agent_failed: test 4 cannot be fixed"


def test_failed_without_a_reason_does_not_lie(herdr, tmp_path):
    """The task description is not a reason given by the worker."""
    result = wait(herdr, tmp_path, raw_task("Failed"))
    assert result["error"] == "agent_failed: no reason given"


def test_canceled_has_its_own_code(herdr, tmp_path):
    assert wait(herdr, tmp_path, raw_task("Canceled"))["error"] == "task_canceled"


def test_input_required_returns_with_the_question(herdr, tmp_path):
    """Only the orchestrator can answer -- it has to be woken."""
    result = wait(
        herdr, tmp_path, raw_task("InputRequired", reply="main or develop?")
    )
    assert result["ok"] is False
    assert result["error"] == "input_required"
    assert result["message"] == "main or develop?"


def test_the_verdict_is_read_from_the_first_line_only():
    assert verdict("VERDIKT: result\nall green") == "result"
    assert verdict("VERDIKT: reject\nbus.py:14 lacks a test") == "reject"
    assert verdict("all green\nVERDIKT: result") is None, "first line only"
    assert verdict("I write VERDIKT: result somewhere") is None
    assert verdict(None) is None and verdict("") is None
    assert verdict("VERDICT: result") is None, (
        "VERDIKT: is a protocol token shared with roles/reviewer.md -- "
        "translating it would silently invalidate every review already written"
    )


def test_the_reviewers_verdict_comes_back_machine_readable(herdr, tmp_path):
    result = wait(
        herdr, tmp_path,
        raw_task("Completed", reply="VERDIKT: reject\ntests/test_foo.py is missing"),
        role="reviewer",
    )
    assert result["ok"] is True, "the reviewer delivered -- reject is not a failure"
    assert result["verdict"] == "reject"


def test_an_open_state_rings_once_and_runs_into_the_timeout(herdr, tmp_path):
    _, proc = herdr
    clock = iter([0.0, 0.0, 5.0, 5.0, 20.0])
    result = wait(
        herdr, tmp_path, raw_task("Working"), timeout_ms=10_000, now=lambda: next(clock)
    )
    assert result["error"] == "no_reply"
    assert result["state"] == "working"
    rings = [c for c in proc.calls if c[1:3] == ["agent", "prompt"]]
    assert len(rings) == 1, "exactly one ring per wait call"
    assert "--wait" not in rings[0], "the ring does not wait -- the script does"
    assert TASK_ID in " ".join(rings[0])


def test_a_crashed_worker_becomes_agent_error(herdr, tmp_path, monkeypatch):
    """The cause from the session store instead of a meaningless no_reply (H1)."""
    h, proc = herdr
    proc.replies = {
        ("agent", "list"): {
            "result": {
                "agents": [
                    {"name": "builder", "pane_id": "w1:p6",
                     "agent_session": {"value": "sid1"}}
                ]
            }
        }
    }
    monkeypatch.setenv("HOME", str(tmp_path))
    store = tmp_path / ".claude" / "projects" / str(ROOT.resolve()).replace("/", "-")
    store.mkdir(parents=True)
    (store / "sid1.jsonl").write_text(
        json.dumps({"role": "user", "content": "go"}) + "\n"
        + json.dumps(
            {
                "role": "assistant",
                "error": {
                    "name": "APIError",
                    "data": {"message": "User not found.", "statusCode": 401},
                },
            }
        ) + "\n",
        encoding="utf-8",
    )
    clock = iter([0.0, 0.0, 99.0])
    result = wait(
        (h, proc), tmp_path, raw_task("Created"), timeout_ms=1_000, now=lambda: next(clock)
    )
    assert result["error"] == "agent_error: APIError: User not found. (401)"


def test_a_crashed_worktree_worker_becomes_agent_error_too(
    herdr, tmp_path, monkeypatch
):
    """The session store is slugged from the WORKER's cwd, not from the repo root.

    A `--worktree` worker runs in the worktree -- the build mode hands
    `ensure_worktree(...).path` to `pane split` -- so `~/.claude/projects`
    carries the worktree slug. Searching under the repo-root slug finds
    nothing and reports `no_reply`, and the orchestrator then retries a crash
    it is supposed to escalate without a retry.
    """
    h, proc = herdr
    worktree = tmp_path / "repo.feat-auth"
    worktree.mkdir()
    proc.replies = {
        ("agent", "list"): {
            "result": {
                "agents": [
                    {"name": "builder-feat-auth", "pane_id": "w2:p2",
                     "agent_session": {"value": "sid2"}}
                ]
            }
        },
        ("worktree", "list"): {
            "result": {
                "source": {"repo_root": str(ROOT)},
                "worktrees": [
                    {"branch": "feat/auth", "path": str(worktree),
                     "open_workspace_id": "w2"}
                ],
            }
        },
    }
    monkeypatch.setenv("HOME", str(tmp_path))
    store = tmp_path / ".claude" / "projects" / str(worktree).replace("/", "-")
    store.mkdir(parents=True)
    (store / "sid2.jsonl").write_text(
        json.dumps(
            {
                "role": "assistant",
                "error": {
                    "name": "APIError",
                    "data": {"message": "User not found.", "statusCode": 401},
                },
            }
        ) + "\n",
        encoding="utf-8",
    )
    clock = iter([0.0, 0.0, 99.0])
    result = wait(
        (h, proc),
        tmp_path,
        raw_task("Created"),
        timeout_ms=1_000,
        worktree="feat/auth",
        now=lambda: next(clock),
    )
    assert result["error"] == "agent_error: APIError: User not found. (401)"


def test_timeout_for_a_gone_worktree_creates_nothing(herdr, tmp_path, monkeypatch):
    """A wait call must not create a worktree merely to diagnose a timeout.

    `--worktree feat/gone` names a branch with no entry in `worktree list`
    (build mode failed earlier, or the operator cleaned it up). The timeout
    path only wants to know where the worker's session log might live; it
    must fall back to `root` and report `no_reply` without ever running
    `wt switch --create` -- that would leave a stray worktree and workspace
    as a side effect of merely diagnosing a timeout.
    """
    h, proc = herdr
    proc.replies = {
        ("agent", "list"): {"result": {"agents": []}},
        ("worktree", "list"): {
            "result": {"source": {"repo_root": str(ROOT)}, "worktrees": []}
        },
    }
    # `wt_switch`'s `runner` parameter defaults to the real `subprocess.run`,
    # bound once at import time -- monkeypatching the `subprocess` module
    # afterwards cannot intercept it. Spying on `wt_switch` itself is the
    # reliable way to prove `ensure_worktree`'s create step was never
    # reached, without risking a real `wt switch --create` subprocess.
    switch_calls: list[str] = []

    def spy_wt_switch(branch: str, *, cwd: object, runner: object = None) -> None:
        switch_calls.append(branch)

    monkeypatch.setattr("lean_herdr.worktree.wt_switch", spy_wt_switch)
    clock = iter([0.0, 0.0, 99.0])
    result = wait(
        (h, proc),
        tmp_path,
        raw_task("Created"),
        timeout_ms=1_000,
        worktree="feat/gone",
        now=lambda: next(clock),
    )
    assert result["error"] == "no_reply"
    assert switch_calls == [], "timeout diagnosis must not attempt `wt switch --create`"
    assert not proc.called_with("worktree", "open"), (
        "timeout diagnosis must not register a workspace with herdr either"
    )


def test_an_unreadable_store_is_never_success_by_silence(herdr, tmp_path):
    path = tmp_path / "tasks.json"
    path.write_text("{broken", encoding="utf-8")
    h, _ = herdr
    result = await_task(
        AwaitRequest(role="builder", kind="claude", task_id=TASK_ID),
        herdr=h, root=ROOT, tasks_path=path, sleep=lambda _s: None,
    )
    assert result["ok"] is False
    assert result["error"].startswith("tasks_unreadable:")


def test_an_unknown_task_id_neither_waits_nor_rings(herdr, tmp_path):
    """ctx_task finished writing the file before it answered."""
    _, proc = herdr
    result = wait(herdr, tmp_path)
    assert result["error"] == "task_not_found"
    assert not proc.called_with("agent", "prompt")


def test_an_unknown_state_never_counts_as_success(herdr, tmp_path):
    """A format change in lean-ctx runs into the timeout, not into an ok."""
    clock = iter([0.0, 0.0, 99.0])
    result = wait(
        herdr, tmp_path, raw_task("Vanished"), timeout_ms=1_000, now=lambda: next(clock)
    )
    assert result["ok"] is False and result["error"] == "no_reply"


def test_await_without_task_id_is_a_usage_error(capsys):
    """Exit 0 and one JSON line, even on a typo -- otherwise the
    orchestrator sees nothing at all."""
    code = main(["builder", "--kind", "claude", "--await"])
    assert code == 0
    result = json.loads(capsys.readouterr().out.strip())
    assert result["ok"] is False
    assert result["error"] == "usage_error: --await needs --task-id"


def test_build_mode_without_model_is_a_usage_error(capsys):
    code = main(["builder", "--kind", "claude"])
    assert code == 0
    result = json.loads(capsys.readouterr().out.strip())
    assert result["error"].startswith("usage_error: build mode needs --model")


AWAIT = ["builder", "--kind", "claude", "--await", "--task-id", TASK_ID]
BUILD = ["builder", "--kind", "claude", "--model", "sonnet",
         "--role-file", "roles/builder.md"]


@pytest.mark.parametrize(
    "argv, offender",
    [
        pytest.param([*AWAIT, "--model", "sonnet"], "--model", id="model in await"),
        pytest.param(
            [*AWAIT, "--role-file", "roles/builder.md"], "--role-file",
            id="role-file in await",
        ),
        pytest.param([*AWAIT, "--profile", "minimal"], "--profile", id="profile in await"),
        pytest.param(
            [*BUILD, "--timeout-ms", "1000"], "--timeout-ms", id="timeout-ms in build"
        ),
        pytest.param([*AWAIT, "--timeout-ms", "0"], "--timeout-ms", id="timeout-ms zero"),
        pytest.param(
            [*AWAIT, "--timeout-ms", "-5"], "--timeout-ms", id="timeout-ms negative"
        ),
    ],
)
def test_a_flag_of_the_other_mode_is_a_usage_error(argv, offender, capsys, monkeypatch):
    """argparse takes every flag in every mode -- and the wrong-mode ones then
    vanish without a word.

    `--timeout-ms` says "only with --await" in its own help and was accepted
    in build mode; `--model`, `--role-file` and `--profile` were accepted
    under `--await`. `--timeout-ms 0` bought exactly one ring and an immediate
    `no_reply`. The subprocess guard is part of the contract: a usage error is
    decided before anything reaches git, Herdr or a pane.
    """

    def _forbidden(*args, **kwargs):
        pytest.fail(f"a usage error must never reach a real subprocess: {args!r}")

    monkeypatch.setattr("subprocess.run", _forbidden)
    monkeypatch.setattr("subprocess.Popen", _forbidden)

    code = main(argv)

    assert code == 0
    result = json.loads(capsys.readouterr().out.strip())
    assert result["ok"] is False
    assert result["error"].startswith("usage_error: "), result["error"]
    assert offender in result["error"], result["error"]


def test_await_without_timeout_ms_still_gets_the_default(monkeypatch, capsys):
    """`--timeout-ms` defaults to None in the parser so that a build-mode use
    can be told from an omission -- main() must fill the real value back in,
    or every wait would run with `timeout_ms=None`.
    """
    seen: list[AwaitRequest] = []

    def spy(request, **_kwargs):
        seen.append(request)
        return {"ok": True}

    monkeypatch.setattr("lean_herdr.dispatch.canonical_root", lambda *a, **kw: ROOT)
    monkeypatch.setattr("lean_herdr.dispatch.await_task", spy)

    main(["builder", "--kind", "claude", "--await", "--task-id", TASK_ID])
    capsys.readouterr()

    assert seen[0].timeout_ms == DEFAULT_TIMEOUT_MS


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["builder"], id="kind missing"),
        pytest.param(["--kind", "claude", "--await", "--task-id", TASK_ID], id="role missing"),
        pytest.param(["builder", "--kind", "cursor"], id="kind unknown"),
        pytest.param(["builder", "--kind", "claude", "--nope"], id="flag unknown"),
    ],
)
def test_argparse_failures_land_on_stdout_like_every_other_error(argv, capsys):
    """argparse would end the process with exit 2 and one line on STDERR.

    The orchestrator reads `ok` on stdout and would see no output at all --
    so the parser error takes the same shape as missing_flags().
    """
    code = main(argv)
    assert code == 0
    captured = capsys.readouterr()
    assert captured.err == "", "argparse must not write the usage line to stderr"
    result = json.loads(captured.out.strip())
    assert result["ok"] is False
    assert result["error"].startswith("usage_error: ")


def test_help_keeps_working(capsys):
    """Only the error path is redirected -- --help still prints and exits 0."""
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])
    assert exit_info.value.code == 0
    assert "herdr-dispatch" in capsys.readouterr().out
