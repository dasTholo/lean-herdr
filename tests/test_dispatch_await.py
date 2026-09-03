import json
from pathlib import Path

import pytest

from lean_herdr.dispatch import (
    DEFAULT_TIMEOUT_MS,
    ORCHESTRATOR_AGENT,
    AwaitRequest,
    OrderRequest,
    answer_order,
    await_task,
    cancel_order,
    create_order,
    main,
    remember_branch,
    verdict,
)
from lean_herdr.herdr import Herdr
from lean_herdr.leanctx import CtxResponse
from lean_herdr.orderlog import append, read_events, state_dir
from lean_herdr.orders import fold, message_from
from tests.doubles import FakeProc, which_stub

ROOT = Path("/repo")
WORKER = "builder-feat-x"
TASK_ID = "o-1a05e34cd15-1cf3b885"


def log(tmp_path, *events, task=TASK_ID):
    """Build an order log from (kind, actor, payload) triples."""
    for kind, actor, payload in events:
        append(task, kind, actor, payload, orders=tmp_path)
    return tmp_path


def created(to_agent=WORKER, description="build foo", **rest):
    return ("created", "orchestrator", {"to_agent": to_agent, "description": description, **rest})


@pytest.fixture
def herdr(monkeypatch):
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
    proc = FakeProc()
    proc.replies = {("agent", "list"): {"result": {"agents": []}}}
    return Herdr(runner=proc), proc


def wait(herdr, tmp_path, *events, timeout_ms=300_000, role="builder", worktree=None, **rest):
    log(tmp_path, *events)
    h, _ = herdr
    return await_task(
        AwaitRequest(
            role=role, kind="claude", task_id=TASK_ID,
            worktree=worktree, timeout_ms=timeout_ms,
        ),
        herdr=h,
        root=ROOT,
        orders_dir=tmp_path,
        sleep=lambda _s: None,
        **rest,
    )


def test_completed_is_success_with_the_closing_message(herdr, tmp_path):
    result = wait(
        herdr, tmp_path,
        created(),
        ("working", WORKER, {}),
        ("completed", WORKER, {"message": "done, three tests green"}),
    )
    assert result["ok"] is True
    assert result["state"] == "completed"
    assert result["message"] == "done, three tests green"
    assert "verdict" not in result


def test_an_already_terminal_state_does_not_ring_at_all(herdr, tmp_path):
    """The orchestrator may repeat --await safely."""
    _, proc = herdr
    wait(herdr, tmp_path, created(), ("completed", WORKER, {"message": "done"}))
    assert not proc.called_with("agent", "prompt")


def test_failed_carries_the_workers_reason(herdr, tmp_path):
    result = wait(
        herdr, tmp_path, created(),
        ("failed", WORKER, {"message": "test 4 cannot be fixed"}),
    )
    assert result["ok"] is False
    assert result["error"] == "agent_failed: test 4 cannot be fixed"


def test_failed_without_a_reason_does_not_lie(herdr, tmp_path):
    """The order description is not a reason given by the worker."""
    result = wait(herdr, tmp_path, created(), ("failed", WORKER, {}))
    assert result["error"] == "agent_failed: no reason given"


def test_canceled_has_its_own_code(herdr, tmp_path):
    result = wait(herdr, tmp_path, created(), ("canceled", WORKER, {}))
    assert result["error"] == "task_canceled"


def test_input_required_returns_with_the_question(herdr, tmp_path):
    """Only the orchestrator can answer -- it has to be woken."""
    result = wait(
        herdr, tmp_path,
        created(),
        ("input-required", WORKER, {"message": "which branch strategy?"}),
    )
    assert result["ok"] is False
    assert result["error"] == "input_required"
    assert result["message"] == "which branch strategy?"


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
        created(),
        ("completed", WORKER, {"message": "VERDIKT: reject\ntests/test_foo.py is missing"}),
        role="reviewer",
    )
    assert result["ok"] is True, "the reviewer delivered -- reject is not a failure"
    assert result["verdict"] == "reject"


def test_an_open_state_rings_once_and_runs_into_the_timeout(herdr, tmp_path):
    _, proc = herdr
    clock = iter([0.0, 0.0, 5.0, 5.0, 20.0])
    result = wait(
        herdr, tmp_path, created(), ("working", WORKER, {}),
        timeout_ms=10_000, now=lambda: next(clock),
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
        (h, proc), tmp_path, created(), timeout_ms=1_000, now=lambda: next(clock)
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
        created(),
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
        created(),
        timeout_ms=1_000,
        worktree="feat/gone",
        now=lambda: next(clock),
    )
    assert result["error"] == "no_reply"
    assert switch_calls == [], "timeout diagnosis must not attempt `wt switch --create`"
    assert not proc.called_with("worktree", "open"), (
        "timeout diagnosis must not register a workspace with herdr either"
    )


def test_a_broken_chain_is_never_success_by_silence(herdr, tmp_path):
    """A destroyed log must not look like 'nothing to do'."""
    log(tmp_path, created(), ("working", WORKER, {}))
    first, _second = sorted(
        p for p in (tmp_path / TASK_ID / "events").iterdir() if p.suffix == ".json"
    )
    first.unlink()
    h, _ = herdr
    result = await_task(
        AwaitRequest(role="builder", kind="claude", task_id=TASK_ID, timeout_ms=1000),
        herdr=h, root=ROOT, orders_dir=tmp_path, sleep=lambda _s: None,
    )
    assert result["ok"] is False
    assert result["error"].startswith("chain_broken")


def test_an_unknown_task_id_neither_waits_nor_rings(herdr, tmp_path):
    """append() renamed the finished file into place before it returned."""
    _, proc = herdr
    result = wait(herdr, tmp_path)
    assert result["error"] == "task_not_found"
    assert not proc.called_with("agent", "prompt")


def test_await_surfaces_a_broken_state_dir_before_the_loop(monkeypatch, tmp_path, herdr):
    """`state_dir(root)` is resolved ONCE, before the loop (dispatch.py:396) --
    its own OrderLogError (a second clone under the same basename, the way
    test_orderlog.py's test_a_second_clone_under_the_same_name_is_an_error_
    not_a_dodge triggers it) must surface as the await result, never as a
    crash and never as a silent no_reply."""
    monkeypatch.setenv("LEAN_CTX_DATA_DIR", str(tmp_path / "data"))
    state_dir(tmp_path / "one" / "repo")
    h, _ = herdr
    result = await_task(
        AwaitRequest(role="builder", kind="claude", task_id=TASK_ID, timeout_ms=1000),
        herdr=h, root=tmp_path / "two" / "repo", sleep=lambda _s: None,
    )
    assert result["ok"] is False
    assert result["error"].startswith("state_root_mismatch")


def test_an_unknown_state_never_counts_as_success(herdr, tmp_path):
    """A format change in the log runs into the timeout, not into an ok."""
    clock = iter([0.0, 0.0, 99.0])
    result = wait(
        herdr, tmp_path, created(), ("vanished", WORKER, {}),
        timeout_ms=1_000, now=lambda: next(clock),
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


def test_an_order_can_be_created_from_a_plain_process(tmp_path):
    """The gap section 6 of the ctx_task spec conceded: closed."""
    result = create_order(
        OrderRequest(to_agent=WORKER, message="build the order log"),
        root=ROOT, orders_dir=tmp_path,
    )
    assert result["ok"] is True
    assert result["task_id"].startswith("o-")
    order = fold(read_events(result["task_id"], orders=tmp_path))
    assert order.to_agent == WORKER
    assert order.from_agent == ORCHESTRATOR_AGENT
    assert order.description == "build the order log"
    assert order.state == "created"


def test_an_order_can_name_its_predecessor(tmp_path):
    first = create_order(
        OrderRequest(to_agent=WORKER, message="a"), root=ROOT, orders_dir=tmp_path
    )["task_id"]
    second = create_order(
        OrderRequest(to_agent=WORKER, message="b", after=first),
        root=ROOT, orders_dir=tmp_path,
    )
    assert fold(read_events(second["task_id"], orders=tmp_path)).after == first


def test_a_predecessor_nobody_wrote_is_refused(tmp_path):
    """Silently folding in nothing would lose the wording without a word."""
    result = create_order(
        OrderRequest(to_agent=WORKER, message="b", after="o-nope"),
        root=ROOT, orders_dir=tmp_path,
    )
    assert result == {"ok": False, "error": "task_not_found: o-nope"}


def test_the_answer_is_an_event_of_its_own(tmp_path):
    """ctx_task hid it in an update message; here it stands under its kind."""
    task = create_order(
        OrderRequest(to_agent=WORKER, message="a"), root=ROOT, orders_dir=tmp_path
    )["task_id"]
    append(task, "input-required", WORKER, {"message": "which branch?"}, orders=tmp_path)
    result = answer_order(task, "feat/x, off main", root=ROOT, orders_dir=tmp_path)
    assert result["ok"] is True
    order = fold(read_events(task, orders=tmp_path))
    assert order.state == "working", "the order returns to working on its own"
    assert message_from(order, ORCHESTRATOR_AGENT) == "feat/x, off main"


def test_an_answer_to_a_question_nobody_asked_is_refused(tmp_path):
    task = create_order(
        OrderRequest(to_agent=WORKER, message="a"), root=ROOT, orders_dir=tmp_path
    )["task_id"]
    result = answer_order(task, "unasked", root=ROOT, orders_dir=tmp_path)
    assert result["ok"] is False
    assert "not input-required" in result["error"]
    assert len(read_events(task, orders=tmp_path)) == 1, "nothing was appended"


def test_the_full_question_cycle_ends_in_a_completion(herdr, tmp_path):
    """The wait mode returns on the question, and again on the answer's outcome."""
    task = create_order(
        OrderRequest(to_agent=WORKER, message="a"), root=ROOT, orders_dir=tmp_path
    )["task_id"]
    append(task, "working", WORKER, {}, orders=tmp_path)
    append(task, "input-required", WORKER, {"message": "which branch?"}, orders=tmp_path)
    h, _ = herdr
    asked = await_task(
        AwaitRequest(role="builder", kind="claude", task_id=task, timeout_ms=1000),
        herdr=h, root=ROOT, orders_dir=tmp_path, sleep=lambda _s: None,
    )
    assert asked["error"] == "input_required"
    assert asked["message"] == "which branch?"
    answer_order(task, "feat/x", root=ROOT, orders_dir=tmp_path)
    append(task, "completed", WORKER, {"message": "done"}, orders=tmp_path)
    done = await_task(
        AwaitRequest(role="builder", kind="claude", task_id=task, timeout_ms=1000),
        herdr=h, root=ROOT, orders_dir=tmp_path, sleep=lambda _s: None,
    )
    assert done["ok"] is True
    assert done["message"] == "done"


def test_cancel_closes_a_stuck_order(tmp_path):
    task = create_order(
        OrderRequest(to_agent=WORKER, message="a"), root=ROOT, orders_dir=tmp_path
    )["task_id"]
    result = cancel_order(task, "run broke off", root=ROOT, orders_dir=tmp_path)
    assert result["ok"] is True
    assert fold(read_events(task, orders=tmp_path)).state == "canceled"


def test_cancel_refuses_an_order_that_is_already_terminal(tmp_path):
    task = create_order(
        OrderRequest(to_agent=WORKER, message="a"), root=ROOT, orders_dir=tmp_path
    )["task_id"]
    append(task, "completed", WORKER, {"message": "done"}, orders=tmp_path)
    result = cancel_order(task, "too late", root=ROOT, orders_dir=tmp_path)
    assert result["ok"] is False
    assert "already completed" in result["error"]


def test_cancel_of_an_unknown_order_is_not_found(tmp_path):
    assert cancel_order("o-nope", "x", root=ROOT, orders_dir=tmp_path)["error"] == (
        "task_not_found"
    )


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["order", "--message", "x"], "order needs --to"),
        (["order", "--to", "builder-feat-x"], "order needs --message"),
        (["order", "--to", "b", "--message", "x", "--kind", "claude"],
         "`order` does not take --kind"),
        (["order", "--to", "b", "--message", "x", "--task-id", "o-1"],
         "`order` does not take --task-id"),
        (["cancel", "--message", "x"], "cancel needs --task-id"),
        (["answer", "--task-id", "o-1"], "answer needs --message"),
        (["answer", "--task-id", "o-1", "--message", "x", "--to", "b"],
         "`answer` does not take --to"),
        (["builder", "--to", "b"], "--to belongs to a log command"),
        (["builder", "--model", "m", "--role-file", "r"], "--kind is required"),
    ],
)
def test_the_modes_do_not_take_each_others_flags(argv, expected, capsys):
    assert main(argv) == 0
    answer = json.loads(capsys.readouterr().out)
    assert answer["ok"] is False
    assert expected in answer["error"]


def test_answer_of_an_unknown_order_is_not_found(tmp_path):
    """cancel_order's twin (test_cancel_of_an_unknown_order_is_not_found)
    was already covered; answer_order's own task_not_found branch
    (ordercmd.py:115) was not."""
    result = answer_order("o-nope", "x", root=ROOT, orders_dir=tmp_path)
    assert result["ok"] is False
    assert result["error"] == "task_not_found"


def test_create_order_refuses_a_predecessor_with_a_broken_chain(tmp_path):
    """A tampered `--after` log must come back as the documented error line
    -- never as task_not_found and never as a crash. `read_events(req.after,
    ...)` raises before create_order() ever reaches its own append()."""
    log(tmp_path, created(), ("working", WORKER, {}))
    first, _second = sorted(
        p for p in (tmp_path / TASK_ID / "events").iterdir() if p.suffix == ".json"
    )
    first.unlink()
    result = create_order(
        OrderRequest(to_agent=WORKER, message="b", after=TASK_ID),
        root=ROOT, orders_dir=tmp_path,
    )
    assert result["ok"] is False
    assert result["error"].startswith("chain_broken")


def test_answer_order_surfaces_a_broken_chain(tmp_path):
    """A destroyed log must not look like 'nothing to do' -- the write
    path's own twin of test_a_broken_chain_is_never_success_by_silence."""
    log(
        tmp_path, created(), ("working", WORKER, {}),
        ("input-required", WORKER, {"message": "which branch?"}),
    )
    first, *_rest = sorted(
        p for p in (tmp_path / TASK_ID / "events").iterdir() if p.suffix == ".json"
    )
    first.unlink()
    result = answer_order(TASK_ID, "reply", root=ROOT, orders_dir=tmp_path)
    assert result["ok"] is False
    assert result["error"].startswith("chain_broken")


def test_cancel_order_surfaces_a_broken_chain(tmp_path):
    log(tmp_path, created(), ("working", WORKER, {}))
    first, _second = sorted(
        p for p in (tmp_path / TASK_ID / "events").iterdir() if p.suffix == ".json"
    )
    first.unlink()
    result = cancel_order(TASK_ID, "abort", root=ROOT, orders_dir=tmp_path)
    assert result["ok"] is False
    assert result["error"].startswith("chain_broken")


@pytest.fixture
def main_root(tmp_path, monkeypatch):
    """Isolate main()'s own state_dir() resolution under tmp_path.

    main() never takes an `orders_dir` -- create_order/answer_order/
    cancel_order fall back to `state_dir(root)`, which layers
    `lean_ctx_data_dir()` under `canonical_root()`. Pinning both, the same
    way test_the_build_mode_reads_the_registry_the_data_dir_points_at pins
    the data dir, is the only way to drive main() end to end without ever
    touching the real lean-ctx install.
    """
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setenv("LEAN_CTX_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr("lean_herdr.dispatch.canonical_root", lambda *a, **kw: root)
    return root


def _one_json_line(capsys) -> dict:
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1
    return json.loads(lines[0])


def test_main_routes_order_into_create_order(main_root, capsys):
    """The headline capability, driven through main() end to end: no test
    exercised dispatch.py's routing into create_order()/answer_order()/
    cancel_order() before (dispatch.py:635/645/649) -- every prior main()
    test stopped inside missing_flags(). This one writes a real event and
    reads it back the way the orchestrator would."""
    code = main(["order", "--to", WORKER, "--message", "build the thing"])
    assert code == 0
    result = _one_json_line(capsys)
    assert result["ok"] is True
    order = fold(read_events(result["task_id"], orders=state_dir(main_root)))
    assert order.to_agent == WORKER
    assert order.from_agent == ORCHESTRATOR_AGENT
    assert order.description == "build the thing"


def test_main_routes_from_and_after_through_to_the_event(main_root, capsys):
    """`--from` and `--after` are the two order-only flags the headline
    test above does not touch -- both must reach the written event."""
    main(["order", "--to", WORKER, "--message", "a"])
    first = _one_json_line(capsys)["task_id"]

    code = main([
        "order", "--to", WORKER, "--message", "b",
        "--after", first, "--from", "reviewer-feat-x",
    ])
    assert code == 0
    result = _one_json_line(capsys)
    order = fold(read_events(result["task_id"], orders=state_dir(main_root)))
    assert order.from_agent == "reviewer-feat-x"
    assert order.after == first


def test_main_routes_answer_into_answer_order(main_root, capsys):
    main(["order", "--to", WORKER, "--message", "a"])
    task = _one_json_line(capsys)["task_id"]
    append(
        task, "input-required", WORKER, {"message": "which branch?"},
        orders=state_dir(main_root),
    )

    code = main(["answer", "--task-id", task, "--message", "feat/x, off main"])
    assert code == 0
    result = _one_json_line(capsys)
    assert result["ok"] is True
    order = fold(read_events(task, orders=state_dir(main_root)))
    assert order.state == "working"
    assert message_from(order, ORCHESTRATOR_AGENT) == "feat/x, off main"


def test_main_routes_cancel_into_cancel_order(main_root, capsys):
    main(["order", "--to", WORKER, "--message", "a"])
    task = _one_json_line(capsys)["task_id"]

    code = main(["cancel", "--task-id", task, "--message", "run broke off"])
    assert code == 0
    result = _one_json_line(capsys)
    assert result["ok"] is True
    order = fold(read_events(task, orders=state_dir(main_root)))
    assert order.state == "canceled"
    assert message_from(order, ORCHESTRATOR_AGENT) == "run broke off"


def test_remember_reports_success_even_when_lean_ctx_is_missing():
    """A memory entry is not the deliverable -- a green branch stays green."""
    class Absent:
        def knowledge_remember(self, **_kwargs):
            return CtxResponse(False, error="unavailable")

    result = remember_branch(
        "lean-herdr/feat-x", "one sentence", root=ROOT, client=Absent()
    )
    assert result["ok"] is True
    assert result["remembered"] is False
    assert result["reason"] == "unavailable"


def test_remember_needs_a_key_and_a_message(capsys):
    assert main(["remember", "--message", "x"]) == 0
    assert "remember needs --key" in json.loads(capsys.readouterr().out)["error"]
