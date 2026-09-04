import json
import subprocess
from typing import Any

import pytest

from lean_herdr.herdr import (
    AGENT_START_ATTEMPTS,
    AGENT_START_INTERVAL_S,
    AGENT_START_REFUSAL_S,
    DEFAULT_TIMEOUT_S,
    FIRST_START_TIMEOUT_MS,
    HERDR_MAX_TIMEOUT_MS,
    HERDR_MIN_TIMEOUT_MS,
    PANE_FREE_TIMEOUT_S,
    Herdr,
    _free_pane,
    start_agent,
    timeout_ms_for,
)
from tests.doubles import Clock, Completed, FakeProc, ScriptedProc, which_stub


@pytest.fixture
def fake(monkeypatch) -> FakeProc:
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
    return FakeProc()


def h(fake: FakeProc) -> Herdr:
    return Herdr(runner=fake)


#: What `agent start` really answers when the pane's shell has not reached its
#: interactive prompt yet: exit 1, nothing on stdout, the reason on stderr --
#: where `Herdr.run()` never looked. Measured 2026-09-04 against 0.8.2.
PANE_BUSY = (
    '{"error":{"code":"agent_pane_busy",'
    '"message":"agent target pane w8:p5 is not an available shell"}}'
)

#: And what it answers when it works.
STARTED = {
    "id": "cli:agent:start",
    "result": {
        "type": "agent_started",
        "agent": {
            "agent": "opencode",
            "name": "orch",
            "pane_id": "w8:p5",
            "agent_status": "idle",
            "interactive_ready": True,
        },
    },
}


class StartProc:
    """`herdr agent start` with a SEQUENCE of exit codes.

    FakeProc answers every call the same way and always with returncode 0, so
    it cannot express what this retry exists for: a refusal, then the very
    same call going through. `codes` is handed out one per call, the last one
    repeating. A non-zero code answers the way the real CLI does.
    """

    def __init__(self, *codes: int) -> None:
        self.codes: tuple[int, ...] = codes or (0,)
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str], **kwargs: Any) -> Completed:
        self.calls.append(list(cmd))
        code = self.codes[min(len(self.calls) - 1, len(self.codes) - 1)]
        if code:
            return Completed(returncode=code, stderr=PANE_BUSY)
        return Completed(stdout=json.dumps(STARTED))


def test_pane_split_sets_env_pairs(fake):
    # The real response from 0.8.2, verbatim in form: pane_id sits UNDER pane.
    fake.replies = {("pane", "split"): {"result": {"pane": {"pane_id": "w2:p2"}}}}
    pane = h(fake).pane_split(
        "/repo", env={"LEAN_CTX_TOOL_PROFILE": "standard", "LEAN_CTX_ROLE": "builder"}
    )
    assert pane == "w2:p2"
    assert fake.called_with("--env", "LEAN_CTX_TOOL_PROFILE=standard")
    assert fake.called_with("--env", "LEAN_CTX_ROLE=builder")
    assert "--no-focus" in fake.calls[0]
    assert "--current" in fake.calls[0], "without a target pane it stays the caller's own workspace"


def test_pane_split_with_target_pane_lands_in_foreign_workspace(fake):
    """The target pane determines the workspace of the new pane — not --current."""
    fake.replies = {("pane", "split"): {"result": {"pane": {"pane_id": "w2:p3"}}}}
    assert h(fake).pane_split("/repo.feat", pane="w2:p1") == "w2:p3"
    assert fake.called_with("--pane", "w2:p1")
    assert "--current" not in fake.calls[0]


def test_ratio_appears_only_when_set(monkeypatch):
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
    fake = FakeProc()
    h = Herdr(runner=fake)
    h.pane_split("/repo")
    assert "--ratio" not in fake.calls[0]
    h.pane_split("/repo", ratio=0.25)
    assert fake.calls[1][fake.calls[1].index("--ratio") + 1] == "0.25"


def test_pane_send_keys_puts_the_pane_id_first(fake):
    """The id is positional -- `--pane` here is exit 2."""
    h(fake).pane_send_keys("w8:p5", "ctrl-c")
    assert fake.calls == [["herdr", "pane", "send-keys", "w8:p5", "ctrl-c"]]


def test_pane_list_filters_by_workspace(fake):
    fake.replies = {("pane", "list"): {"result": {"panes": [{"pane_id": "w2:p1"}]}}}
    assert h(fake).pane_list("w2") == [{"pane_id": "w2:p1"}]
    assert fake.called_with("--workspace", "w2")


def test_no_call_appends_json(fake):
    """Regression: --json doesn't exist in herdr and aborts with exit 2."""
    herdr = h(fake)
    herdr.agent_list()
    herdr.pane_split("/repo")
    herdr.agent_prompt("builder", "go", wait=False)
    herdr.report_metadata("pane", "w1:p1", "ctx", "T1")
    assert all("--json" not in call for call in fake.calls)


def test_agent_start_passes_native_arguments_after_double_dash(fake):
    h(fake).agent_start(
        "builder",
        kind="claude",
        pane="w2:p2",
        agent_args=["--model", "sonnet", "--append-system-prompt-file", "roles/builder.md"],
    )
    call = fake.calls[0]
    native = call[call.index("--") + 1 :]
    assert native[:4] == ["--model", "sonnet", "--append-system-prompt-file", "roles/builder.md"]
    assert "--env" not in call, "agent start doesn't know --env (H9)"


def test_agent_prompt_without_wait_for_control_commands(fake):
    h(fake).agent_prompt("builder", "/clear", wait=False)
    assert "--wait" not in fake.calls[0], "/clear doesn't trigger a lifecycle change (H4)"


def test_agent_prompt_with_wait_and_timeout(fake):
    h(fake).agent_prompt("builder", "Task is on the bus.", timeout_ms=120000)
    assert fake.called_with("--wait")
    assert fake.called_with("--timeout", "120000")


def test_missing_binary_returns_empty_dict(monkeypatch):
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(False))
    fake = FakeProc()
    assert Herdr(runner=fake).agent_list() == []
    assert fake.calls == [], "without a binary, no call may happen"


def test_timeout_becomes_empty_dict(fake):
    fake.raises = subprocess.TimeoutExpired(cmd=["herdr"], timeout=1)
    assert h(fake).agent_list() == []


def test_broken_json_becomes_empty_dict(monkeypatch):
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))

    def runner(cmd, **kwargs):
        return Completed(stdout="<html>nope</html>")

    assert Herdr(runner=runner).agent_list() == []


def test_report_metadata_builds_the_token_pair(fake):
    fake.default = {"result": {"ok": True}}
    assert h(fake).report_metadata("workspace", "w2", "esc", "T1: reviewer rejects")
    # ID positional, --source mandatory — measured against 0.8.2.
    assert fake.called_with(
        "workspace", "report-metadata", "w2",
        "--source", "lean.herdr",
        "--token", "esc=T1: reviewer rejects",
    )
    assert "--workspace" not in fake.calls[0]


def test_worktree_open_takes_the_repo_root_as_cwd(fake):
    h(fake).worktree_open(cwd="/repo", path="/repo.feat", label="feat/auth")
    assert fake.called_with("--cwd", "/repo", "--path", "/repo.feat", "--label", "feat/auth")


def test_run_still_answers_every_failure_path_with_an_empty_dict(monkeypatch):
    """Guards the split into _run(): run()'s public behaviour is unchanged.

    Four ways out, one answer. The class contract is `errors become {}, never
    exceptions`, and the returncode the private half now hands back may not
    leak an exception or a non-dict through the public one.
    """
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(False))
    assert Herdr(runner=FakeProc()).run("agent", "list") == {}
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
    assert Herdr(runner=FakeProc(raises=OSError(2, "no herdr"))).run("agent") == {}
    timeout = subprocess.TimeoutExpired(cmd=["herdr"], timeout=1)
    assert Herdr(runner=FakeProc(raises=timeout)).run("agent") == {}
    refused = Herdr(runner=lambda cmd, **kw: Completed(returncode=1, stderr=PANE_BUSY))
    assert refused.run("agent", "start") == {}
    garbage = Herdr(runner=lambda cmd, **kw: Completed(stdout="<html>nope</html>"))
    assert garbage.run("agent", "list") == {}


def test_agent_start_returns_at_once_when_herdr_says_yes(monkeypatch):
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
    proc = StartProc(0)
    naps: list[float] = []
    reply = Herdr(runner=proc).agent_start(
        "orch", kind="opencode", pane="w8:p5", sleep=naps.append
    )
    assert reply == STARTED
    assert len(proc.calls) == 1
    assert naps == [], "a start that works may not cost a single sleep"


def test_agent_start_retries_the_pane_that_is_not_a_shell_yet(monkeypatch):
    """Measured 2026-09-04: the refusal lands at 0.0 s and one repeat clears it."""
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
    proc = StartProc(1, 0)
    naps: list[float] = []
    reply = Herdr(runner=proc).agent_start(
        "orch", kind="opencode", pane="w8:p5", sleep=naps.append
    )
    assert reply == STARTED, "the reply of the attempt that worked, not the refusal"
    assert len(proc.calls) == 2
    assert naps == [AGENT_START_INTERVAL_S]


def test_agent_start_gives_up_after_the_bound(monkeypatch):
    """A PERMANENT refusal -- an invalid name, an unknown kind -- answers
    exactly like the transient one: exit 1, nothing on stdout. Without the
    bound the wrapper would repeat it forever."""
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
    proc = StartProc(1)
    naps: list[float] = []
    assert Herdr(runner=proc).agent_start(
        "nope", kind="claude", pane="w8:p5", sleep=naps.append
    ) == {}
    assert len(proc.calls) == AGENT_START_ATTEMPTS
    assert naps == [AGENT_START_INTERVAL_S] * (AGENT_START_ATTEMPTS - 1)


def test_agent_start_does_not_retry_when_no_process_ran_at_all(monkeypatch):
    """A timeout is not the race, and five repeats would cost five timeouts.

    Same for a missing binary. Those paths carry the sentinel returncode, not
    a refusal, and the loop tells them apart by its sign.
    """
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
    proc = FakeProc(raises=subprocess.TimeoutExpired(cmd=["herdr"], timeout=1))
    naps: list[float] = []
    assert Herdr(runner=proc).agent_start(
        "orch", kind="opencode", pane="w8:p5", sleep=naps.append
    ) == {}
    assert len(proc.calls) == 1 and naps == []


def test_timeout_ms_for_caps_at_herdrs_own_maximum():
    """A `ready_timeout_s` beyond Herdr's limit must not become a refusal."""
    assert timeout_ms_for(45) == 45_000
    assert timeout_ms_for(4) == 4_000
    assert timeout_ms_for(600) == HERDR_MAX_TIMEOUT_MS


def test_timeout_ms_for_holds_herdrs_own_minimum():
    """Herdr refuses a `--timeout` of 3000 or less, so we never send one.

    `AgentStartParams.timeout_ms` in `herdr-api.schema.json`: "Values must
    be greater than 3000 and at most 300000." A `ready_timeout_s` of 2 or 3
    is a legal setting -- `settings.py` validates it as `> 0` only -- and
    without the floor it would turn a short budget into an INSTANT refusal.
    That is the same failure the cap above prevents, approached from the
    other end, so the same rule answers it: Herdr's bound is honoured, not
    assumed away.
    """
    assert HERDR_MIN_TIMEOUT_MS > 3_000
    assert timeout_ms_for(2) == HERDR_MIN_TIMEOUT_MS
    assert timeout_ms_for(3) == HERDR_MIN_TIMEOUT_MS
    assert timeout_ms_for(4) == 4_000


def test_the_timeout_is_passed_through_and_becomes_the_subprocess_budget(
    monkeypatch,
):
    """Herdr's own wait, and our budget derived from it -- not beside it."""
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
    seen: dict[str, Any] = {}

    def runner(cmd: list[str], **kwargs: Any) -> Completed:
        seen["cmd"], seen["budget"] = list(cmd), kwargs["timeout"]
        return Completed(stdout=json.dumps(STARTED))

    Herdr(runner=runner).agent_start(
        "orch",
        kind="opencode",
        pane="w8:p5",
        agent_args=["--agent", "orchestrator"],
        timeout_ms=12_000,
    )
    cmd = seen["cmd"]
    assert cmd[cmd.index("--timeout") + 1] == "12000"
    assert cmd.index("--timeout") < cmd.index("--"), (
        "behind the `--` Herdr hands the flag to opencode instead of reading it"
    )
    assert seen["budget"] == 12.0 + DEFAULT_TIMEOUT_S


def test_without_a_timeout_nothing_changes_at_all(monkeypatch):
    """The callers that pass none keep today's behaviour, byte for byte."""
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
    seen: dict[str, Any] = {}

    def runner(cmd: list[str], **kwargs: Any) -> Completed:
        seen["cmd"], seen["budget"] = list(cmd), kwargs["timeout"]
        return Completed(stdout=json.dumps(STARTED))

    Herdr(runner=runner).agent_start("orch", kind="opencode", pane="w8:p5")
    assert "--timeout" not in seen["cmd"]
    assert seen["budget"] == DEFAULT_TIMEOUT_S


def test_a_start_that_sat_out_its_budget_is_not_repeated(monkeypatch):
    """The hang is not the prompt race -- five repeats would cost five budgets.

    A refusal answers after 0.0 s (measured); a start Herdr sat out to its
    own `--timeout` answers after the whole budget, in exactly the same
    shape. Only the fast one is what AGENT_START_ATTEMPTS exists for.
    """
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
    clock = Clock()
    proc = ScriptedProc(
        clock=clock,
        script={("agent", "start"): (12.0, [Completed(returncode=1)])},
    )
    naps: list[float] = []
    assert (
        Herdr(runner=proc).agent_start(
            "orch",
            kind="opencode",
            pane="w8:p5",
            timeout_ms=12_000,
            sleep=naps.append,
            now=clock.now,
        )
        == {}
    )
    assert len(proc.calls) == 1, proc.flat()
    assert naps == []


#: The helper's happy path and its two failures, all against a Clock: the
#: distinction it makes is DURATION, and a test that slept those seconds
#: would take a minute to say what these say in none.
def _helper(proc: Any, clock: Clock) -> dict[str, Any]:
    return start_agent(
        Herdr(runner=proc),
        "orch",
        kind="opencode",
        pane="w8:p5",
        agent_args=["--agent", "orchestrator"],
        retry_timeout_ms=45_000,
        sleep=clock.sleep,
        now=clock.now,
    )


def test_a_start_that_works_costs_neither_a_key_nor_a_second_attempt(monkeypatch):
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
    clock = Clock()
    proc = ScriptedProc(clock=clock, script={("agent", "start"): (3.4, [STARTED])})
    assert _helper(proc, clock) == {"ok": True, "reply": STARTED}
    assert not proc.called_with("pane", "send-keys"), proc.flat()
    assert len(proc.calls) == 1


def test_a_hung_start_is_aborted_and_the_second_attempt_carries_it(monkeypatch):
    """The measured cure: `ctrl-c`, then the very same start in 3.4 s."""
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
    clock = Clock()
    proc = ScriptedProc(
        clock=clock,
        script={
            # First call sits out the whole `--timeout` and answers
            # nothing; the second one -- the project is warm now -- works.
            ("agent", "start"): (12.0, [{}, STARTED]),
            ("agent", "list"): (0.0, [{"result": {"agents": []}}]),
        },
    )
    assert _helper(proc, clock) == {
        "ok": True,
        "reply": STARTED,
        "retried": True,
    }
    assert proc.called_with("pane", "send-keys", "w8:p5", "ctrl-c")
    starts = [c for c in proc.calls if c[1:3] == ["agent", "start"]]
    assert len(starts) == 2
    assert starts[0][starts[0].index("--timeout") + 1] == str(
        FIRST_START_TIMEOUT_MS
    )
    assert starts[1][starts[1].index("--timeout") + 1] == "45000"


def test_free_pane_sends_both_keys_before_it_may_end_on_an_empty_agent_list(monkeypatch):
    """A hung start never became an agent, so `agent_list()` is empty from
    the very first poll -- and that must not let the wait end after a single
    `ctrl-c`. Regression for the bug where PANE_FREE_TIMEOUT_S and the
    second key were dead code on exactly this path.
    """
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
    clock = Clock()
    proc = ScriptedProc(
        clock=clock,
        script={("agent", "list"): (0.0, [{"result": {"agents": []}}])},
    )
    _free_pane(Herdr(runner=proc), "w8:p5", sleep=clock.sleep, now=clock.now)
    keys = [c for c in proc.calls if c[1:3] == ["pane", "send-keys"]]
    assert len(keys) == 2, "the second ctrl-c must still go out on an empty agent_list()"
    assert clock.t >= PANE_FREE_TIMEOUT_S / 2, "must not return before the second key's deadline"


def test_a_refusal_is_named_at_once_and_costs_no_second_attempt(monkeypatch):
    """0.0 s is Herdr saying no -- a name it does not know, a kind it has not."""
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
    clock = Clock()
    proc = ScriptedProc(clock=clock, script={("agent", "start"): (0.0, [{}])})
    assert _helper(proc, clock) == {"ok": False, "error": "agent_start_failed"}
    assert not proc.called_with("pane", "send-keys"), proc.flat()


def test_a_second_attempt_that_fails_too_is_opencode_stuck(monkeypatch):
    """The honest exit of the residual risk: `ctrl-c` may not reach it."""
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
    clock = Clock()
    proc = ScriptedProc(
        clock=clock,
        script={
            ("agent", "start"): (12.0, [{}]),
            # The pane stays taken: the hung process never let go.
            ("agent", "list"): (
                0.0,
                [{"result": {"agents": [{"name": "orch", "pane_id": "w8:p5"}]}}],
            ),
        },
    )
    assert _helper(proc, clock) == {"ok": False, "error": "opencode_stuck"}
    keys = [c for c in proc.calls if c[1:3] == ["pane", "send-keys"]]
    assert len(keys) == 2, "a second ctrl-c after half the deadline"


def test_without_a_retry_budget_the_hang_is_reported_at_once(monkeypatch):
    """The keystroke's path: it runs in Herdr's handler process.

    There a hang is a deliberately accepted false alarm
    (handlers.KEYSTROKE_READY_TIMEOUT_S) -- blocking that process for a
    second attempt would be the very thing the cap exists to prevent.
    Nothing is lost: the aborted first attempt warms the project anyway,
    so the next press carries.
    """
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
    clock = Clock()
    proc = ScriptedProc(clock=clock, script={("agent", "start"): (6.0, [{}])})
    assert start_agent(
        Herdr(runner=proc),
        "orch",
        kind="opencode",
        pane="w8:p5",
        first_timeout_ms=6_000,
        retry_timeout_ms=0,
        sleep=clock.sleep,
        now=clock.now,
    ) == {"ok": False, "error": "opencode_stuck"}
    assert len(proc.calls) == 1, proc.flat()
    assert not proc.called_with("pane", "send-keys"), (
        "no key, no poll, no second attempt -- the handler must come back"
    )


def test_a_small_first_budget_is_floored_to_the_refusal_threshold(monkeypatch):
    """`ready_timeout_s` is validated as `> 0` only, so a caller may
    legitimately grant a first attempt below AGENT_START_REFUSAL_S. Without
    the floor, a hang that sits out exactly that small budget looks like a
    refusal and gets repeated AGENT_START_ATTEMPTS times inside
    `agent_start` -- the very cost the threshold exists to prevent.
    """
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
    clock = Clock()
    calls: list[list[str]] = []

    def runner(cmd: list[str], **kwargs: Any) -> Completed:
        calls.append(list(cmd))
        # A real hang sits out exactly the --timeout it was given.
        timeout_ms = int(cmd[cmd.index("--timeout") + 1])
        clock.t += timeout_ms / 1000.0
        return Completed(returncode=1)

    result = start_agent(
        Herdr(runner=runner),
        "orch",
        kind="opencode",
        pane="w8:p5",
        first_timeout_ms=3_000,
        retry_timeout_ms=0,
        sleep=clock.sleep,
        now=clock.now,
    )
    floor_ms = timeout_ms_for(AGENT_START_REFUSAL_S)
    assert result == {"ok": False, "error": "opencode_stuck"}
    assert all(int(c[c.index("--timeout") + 1]) >= floor_ms for c in calls)
    assert len(calls) == 1, "the floored budget must trigger the early stop after one attempt"


#: A non-zero exit that ALSO carries a body on stdout. `Herdr._run` collapses a
#: failure to `{}` only while stdout stays empty -- which is how every refusal
#: measured so far behaves (2026-09-04: `agent_pane_not_found` came back exit 1,
#: stdout empty, the reason on stderr). What Herdr prints when its own
#: `--timeout` expires is NOT measured: before this branch our 10 s subprocess
#: budget always fired first, so Herdr never got to report that timeout at all.
#: These three tests make the answer not depend on it.
REFUSED_WITH_BODY = Completed(returncode=1, stdout=PANE_BUSY)


def test_a_failure_that_wrote_to_stdout_is_still_no_reply(monkeypatch):
    """The exit code decides what a start answered, never the body."""
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
    clock = Clock()
    proc = ScriptedProc(
        clock=clock,
        script={("agent", "start"): (12.0, [REFUSED_WITH_BODY])},
    )
    assert (
        Herdr(runner=proc).agent_start(
            "orch",
            kind="opencode",
            pane="w8:p5",
            timeout_ms=12_000,
            sleep=clock.sleep,
            now=clock.now,
        )
        == {}
    )
    assert len(proc.calls) == 1, proc.flat()


def test_the_loop_falls_through_to_nothing_too(monkeypatch):
    """The other exit from the retry loop must answer `{}` just the same."""
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
    clock = Clock()
    proc = ScriptedProc(
        clock=clock,
        script={("agent", "start"): (0.0, [REFUSED_WITH_BODY])},
    )
    assert (
        Herdr(runner=proc).agent_start(
            "orch",
            kind="opencode",
            pane="w8:p5",
            timeout_ms=12_000,
            sleep=clock.sleep,
            now=clock.now,
        )
        == {}
    )
    assert len(proc.calls) == AGENT_START_ATTEMPTS, proc.flat()


def test_a_hang_that_answered_with_a_body_is_still_opencode_stuck(monkeypatch):
    """Read as a reply, this inverts the whole detector.

    `start_agent` asks `if reply:`. A hang whose answer carried a body
    would come back `{"ok": True}` for a start that never came up: no
    `ctrl-c`, no second attempt, no warm-up -- and `up` would then sit out
    the waiter's full `ready_timeout_s` and report `no_agent_id`. That is
    the very bug this branch set out to remove, under the wrong one of the
    three names.
    """
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
    clock = Clock()
    proc = ScriptedProc(
        clock=clock,
        script={
            ("agent", "start"): (12.0, [REFUSED_WITH_BODY]),
            ("agent", "list"): (0.0, [{"result": {"agents": []}}]),
        },
    )
    assert _helper(proc, clock) == {"ok": False, "error": "opencode_stuck"}
    assert proc.called_with("pane", "send-keys", "w8:p5", "ctrl-c")
