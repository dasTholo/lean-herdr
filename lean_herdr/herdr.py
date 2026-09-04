"""Herdr CLI → dict. All outbound traffic to Herdr lives here.

No call without a timeout: without one, Herdr waits indefinitely.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

DEFAULT_TIMEOUT_S = 10.0

#: The exit code `_run` reports when NO process ran at all -- a missing
#: binary, an OSError, a timeout. Negative and far outside the range a real
#: one can take (0-255, or the negated signal number of a kill), so a caller
#: can tell "Herdr said no" from "Herdr never spoke".
NO_PROCESS_RC = -999

#: `agent start` refuses a pane whose shell has not reached its interactive
#: prompt yet -- `agent_pane_busy`, exit 1, nothing on stdout, after 0.0 s.
#: Measured 2026-09-04 against the live 0.8.2 server, walking the sequence
#: both callers walk (`workspace create` -> `pane split` -> `agent start`):
#:
#:   immediately, as the callers did before   3 of 5 -- 2 refused at 0.0 s
#:   with a 2 s settle after the create       4 of 5 -- a sleep does not cure it
#:   retry up to 5x, 0.5 s apart              6 of 6, never more than 2 tries
#:
#: So it is a transient race that fails fast and loudly, and one repeat
#: clears it. The bound exists because a PERMANENT refusal -- an invalid
#: agent name, an unknown kind -- answers in exactly the same shape and must
#: not be repeated forever.
AGENT_START_ATTEMPTS = 5
AGENT_START_INTERVAL_S = 0.5

#: `agent start --timeout` takes at most this many milliseconds. A larger
#: value is REFUSED, so a generously configured `ready_timeout_s` would turn
#: into an instant failure instead of a long wait -- `timeout_ms_for()` caps
#: it. Measured 2026-09-04 against 0.8.2.
HERDR_MAX_TIMEOUT_MS = 300_000

#: And the same bound from below. `AgentStartParams.timeout_ms` in the shipped
#: `herdr-api.schema.json`: "Values must be greater than 3000 and at most
#: 300000." A `ready_timeout_s` of 2 or 3 is a legal setting -- `settings.py`
#: validates it as `> 0` only -- and passing it straight through would turn a
#: short budget into an INSTANT refusal, which is the failure the cap above
#: exists to prevent, only approached from the other end. Greater than 3000,
#: so the smallest value we may send is 3001.
HERDR_MIN_TIMEOUT_MS = 3_001

#: Above the whole cost of a run of pure refusals -- AGENT_START_ATTEMPTS
#: answers after 0.0 s plus the sleeps between them -- and far below any
#: `--timeout` a caller passes. An `agent start` slower than this did not
#: lose the prompt race: Herdr sat it out to its own `--timeout`, which is
#: opencode's first-bootstrap hang. Repeating THAT would cost five full
#: budgets, so the loop below stops at it and `start_agent` reads it to tell
#: the two failures apart.
AGENT_START_REFUSAL_S = AGENT_START_ATTEMPTS * AGENT_START_INTERVAL_S + 1.0

#: The FIRST attempt's budget. A warm start measures 3.4-3.9 s (2026-09-04),
#: so this is room to spare -- and short enough not to sit out a hang for
#: the full `ready_timeout_s` before doing anything about it.
FIRST_START_TIMEOUT_MS = 12_000

#: How long `ctrl-c` gets to clear the pane before the second attempt.
PANE_FREE_TIMEOUT_S = 6.0
PANE_FREE_INTERVAL_S = 0.5


def timeout_ms_for(seconds: float) -> int:
    """A budget in seconds as Herdr's `--timeout`, held inside its bounds.

    Both ends, and for the same reason: a value outside them is not a long
    or a short wait, it is an immediate refusal.
    """
    return max(HERDR_MIN_TIMEOUT_MS, min(int(seconds * 1000), HERDR_MAX_TIMEOUT_MS))


class Herdr:
    """Thin wrapper around the Herdr CLI. Errors become {}, never exceptions.

    The plugin handlers must never break anything, and the scripts check the
    content. Whoever needs to distinguish 'empty' from 'broken' asks
    is_available().
    """

    def __init__(
        self,
        binary: str = "herdr",
        *,
        timeout: float = DEFAULT_TIMEOUT_S,
        runner: Any = subprocess.run,
    ) -> None:
        self.binary = binary
        self.timeout = timeout
        self._runner = runner
        self._available: bool | None = None

    # -- Foundation ----------------------------------------------------

    def is_available(self) -> bool:
        if self._available is None:
            self._available = shutil.which(self.binary) is not None
        return self._available

    def run(self, *args: str, timeout: float | None = None) -> dict[str, Any]:
        """Run `herdr <args>` and return the response as a dict.

        NEVER append --json: Herdr 0.8.2 doesn't know the flag (neither global
        nor per subcommand) and aborts with exit 2. It doesn't exist because
        Herdr always writes JSON to stdout anyway.
        """
        return self._run(*args, timeout=timeout)[0]

    def _run(
        self, *args: str, timeout: float | None = None
    ) -> tuple[dict[str, Any], int]:
        """`run()`, plus the exit code it throws away.

        `run()` flattens "Herdr refused" and "Herdr answered nothing" onto the
        same `{}` -- and the reason (`agent_pane_busy`, say) went to stderr,
        which nobody kept. That is indistinguishable at the call site, and it
        cost `agent start` its whole diagnosis. The class contract stays as it
        is -- errors become {}, never exceptions -- and this is the private
        seam beneath it, for the one caller that has to tell the two apart.

        The code is NO_PROCESS_RC wherever no process ran, so a caller reading
        it cannot mistake that for a refusal.
        """
        if not self.is_available():
            return {}, NO_PROCESS_RC
        cmd = [self.binary, *args]
        try:
            proc = self._runner(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout if timeout is not None else self.timeout,
            )
        except (OSError, subprocess.SubprocessError):
            return {}, NO_PROCESS_RC
        if proc.returncode != 0 and not proc.stdout.strip():
            return {}, proc.returncode
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return {}, proc.returncode
        return (data if isinstance(data, dict) else {}), proc.returncode

    @staticmethod
    def _result(data: dict[str, Any], *keys: str) -> Any:
        node: Any = data
        for key in ("result", *keys):
            if not isinstance(node, dict):
                return None
            node = node.get(key)
        return node

    # -- Panes and agents --------------------------------------------

    def pane_list(self, workspace: str | None = None) -> list[dict[str, Any]]:
        """Panes, optionally restricted to a workspace."""
        args = ["pane", "list"]
        if workspace:
            args += ["--workspace", workspace]
        panes = self._result(self.run(*args), "panes")
        return [p for p in (panes or ()) if isinstance(p, dict)]

    def pane_split(
        self,
        cwd: str | Path,
        *,
        pane: str | None = None,
        direction: str = "right",
        ratio: float | None = None,
        env: dict[str, str] | None = None,
        focus: bool = False,
    ) -> str | None:
        """Create a new pane and return its pane_id.

        The only place for --env: `agent start` doesn't know --env (H9).

        `pane` selects the pane being split — and thus the workspace the new
        one lands in. Without it, Herdr splits `--current`, i.e. ALWAYS the
        caller's workspace. For a worker in a worktree that's wrong:
        `workspace close <worktree_workspace>` would not terminate it.
        """
        target = ["--pane", pane] if pane else ["--current"]
        args = ["pane", "split", *target, "--direction", direction, "--cwd", str(cwd)]
        if ratio is not None:
            args += ["--ratio", str(ratio)]
        if not focus:
            args.append("--no-focus")
        for key, value in (env or {}).items():
            args += ["--env", f"{key}={value}"]
        data = self.run(*args)
        # Measured against 0.8.2: {"result": {"pane": {"pane_id": "w1:p7", ...}}}.
        pane = self._result(data, "pane", "pane_id") or self._result(data, "pane_id")
        return str(pane) if pane else None

    def pane_send_keys(self, pane: str, *keys: str) -> dict[str, Any]:
        """`herdr pane send-keys <PANE_ID> <KEY>...`.

        The pane id is POSITIONAL here, not `--pane` -- the same quirk
        `report_metadata` carries. Keys follow it positionally too.
        """
        return self.run("pane", "send-keys", pane, *keys)

    def agent_start(
        self,
        name: str,
        *,
        kind: str,
        pane: str,
        agent_args: Sequence[str] = (),
        timeout_ms: int | None = None,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.monotonic,
    ) -> dict[str, Any]:
        """Start an agent in the pane. Native arguments after `--`.

        Herdr rejects multi-line arguments (H2) — role texts come as a file,
        never as argument text.

        `timeout_ms` is Herdr's OWN `--timeout`: it returns only once it has
        recognised the expected agent and holds it ready for input, 30 s by
        default. Our subprocess budget is derived from it rather than set
        beside it — without that, `DEFAULT_TIMEOUT_S` killed every start
        past 10 s in the middle of Herdr's legitimate wait, and the kill then
        read as a refusal. `--timeout` goes BEFORE the `--`: behind it, Herdr
        would hand the flag to the runtime instead of reading it.

        Retries a non-zero exit code up to AGENT_START_ATTEMPTS times: the
        pane split a moment ago may not have reached its interactive prompt
        yet, and that refusal is transient — see the constants for the
        measurement. It stops early on an attempt that took longer than
        AGENT_START_REFUSAL_S: that one is not the race but a `--timeout`
        Herdr sat out, and repeating it would cost five full budgets.

        A reply comes back ONLY for a zero exit code; every positive one
        answers `{}`, and that empty dict is what the callers report on.
        The line has to be drawn here rather than left to `_run`, which
        collapses a failure to `{}` only while stdout stays EMPTY. That
        holds for every refusal measured so far (2026-09-04:
        `agent_pane_not_found` came back exit 1, stdout empty, the reason
        on stderr) -- but what Herdr prints when its OWN `--timeout`
        expires is not measured, because before this method passed
        `--timeout` through, our subprocess budget always fired first and
        Herdr never got to report that timeout at all. A body on stdout
        behind a failed start would otherwise read as a start that worked,
        and `start_agent` would answer `ok` for an agent that never came up.
        """
        args = ["agent", "start", name, "--kind", kind, "--pane", pane]
        if timeout_ms is not None:
            args += ["--timeout", str(timeout_ms)]
        if agent_args:
            args = [*args, "--", *agent_args]
        budget = None if timeout_ms is None else timeout_ms / 1000.0 + self.timeout
        for attempt in range(AGENT_START_ATTEMPTS):
            started_at = now()
            reply, code = self._run(*args, timeout=budget)
            if code <= 0:
                # 0 is the start that worked. A NEGATIVE code is
                # NO_PROCESS_RC: no binary, an OSError, a timeout. None of
                # those is the prompt race, and repeating a timeout five
                # times would cost five full timeouts.
                return reply
            # Past here the code is POSITIVE: nothing came up, whatever the
            # process may have written. Both exits below answer `{}`.
            if now() - started_at >= AGENT_START_REFUSAL_S:
                return {}
            if attempt + 1 < AGENT_START_ATTEMPTS:
                sleep(AGENT_START_INTERVAL_S)
        return {}

    def agent_prompt(
        self,
        name: str,
        text: str,
        *,
        wait: bool = True,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        """Ring the bell. ALWAYS send control commands (/clear) with wait=False (H4)."""
        args = ["agent", "prompt", name, text]
        if wait:
            args.append("--wait")
        if timeout_ms is not None:
            args += ["--timeout", str(timeout_ms)]
        budget = None if timeout_ms is None else timeout_ms / 1000.0 + self.timeout
        return self.run(*args, timeout=budget)

    def agent_list(self) -> list[dict[str, Any]]:
        agents = self._result(self.run("agent", "list"), "agents")
        return [a for a in (agents or ()) if isinstance(a, dict)]

    def pane_process_info(self, pane: str) -> dict[str, Any]:
        return self.run("pane", "process-info", "--pane", pane)

    # -- Visibility --------------------------------------------------

    SOURCE = "lean.herdr"

    def report_metadata(
        self, scope: str, target: str, token: str, value: str
    ) -> bool:
        """`herdr <scope> report-metadata <id> --source lean.herdr --token k=v`.

        Two measured quirks (0.8.2): the ID is POSITIONAL, not
        `--pane`/`--workspace`; and `--source` is mandatory — without it, exit 2.
        The source is the namespace our tokens live under, so another plugin
        can't overwrite them.

        scope is "pane" or "workspace". True if the call went through.
        """
        data = self.run(
            scope,
            "report-metadata",
            target,
            "--source",
            self.SOURCE,
            "--token",
            f"{token}={value}",
        )
        return bool(data)

    # -- Workspaces and worktrees --------------------------------------

    def workspace_list(self) -> list[dict[str, Any]]:
        spaces = self._result(self.run("workspace", "list"), "workspaces")
        return [w for w in (spaces or ()) if isinstance(w, dict)]

    def workspace_close(self, workspace: str) -> dict[str, Any]:
        return self.run("workspace", "close", workspace)

    def worktree_list(self, cwd: str | Path) -> dict[str, Any]:
        return self.run("worktree", "list", "--cwd", str(cwd))

    def worktree_open(self, *, cwd: str | Path, path: str | Path, label: str) -> dict[str, Any]:
        """`--cwd` MUST be the repo root, never a linked-worktree path (H8)."""
        return self.run(
            "worktree", "open", "--cwd", str(cwd), "--path", str(path), "--label", label
        )


def _free_pane(
    herdr: Herdr,
    pane: str,
    *,
    sleep: Callable[[float], None],
    now: Callable[[], float],
) -> None:
    """`ctrl-c` the pane, then wait until no agent claims it any more.

    The pane STAYS. Aborting the process rather than closing the tile is
    what keeps the layout still and the pane id in the result stable --
    closing and re-splitting would change both.

    A second `ctrl-c` follows after half the deadline: a hung opencode
    never drew its surface and therefore never grabbed the key, while one
    that did draw it did.

    The wait is not cut short by an empty `agent_list()`, and that is the
    whole point. A hung start never got as far as being an agent, so no
    entry carries this pane to begin with -- ending on that would give
    `ctrl-c` a single poll interval to land and make both
    PANE_FREE_TIMEOUT_S and the second key dead code. So the pane is only
    read as free once the second key has gone out; before that the
    deadline is what governs.

    The deadline is a ceiling, not a promise: when it passes with the pane
    still taken, this returns anyway and lets the second attempt say so.
    """
    herdr.pane_send_keys(pane, "ctrl-c")
    started_at = now()
    deadline = started_at + PANE_FREE_TIMEOUT_S
    again_at = started_at + PANE_FREE_TIMEOUT_S / 2
    again = False
    while True:
        sleep(PANE_FREE_INTERVAL_S)
        if not again and now() >= again_at:
            herdr.pane_send_keys(pane, "ctrl-c")
            again = True
        if now() >= deadline:
            return
        if again and not any(a.get("pane_id") == pane for a in herdr.agent_list()):
            return


def start_agent(
    herdr: Herdr,
    name: str,
    *,
    kind: str,
    pane: str,
    agent_args: Sequence[str] = (),
    first_timeout_ms: int = FIRST_START_TIMEOUT_MS,
    retry_timeout_ms: int,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Start an agent, with a second attempt for opencode's first bootstrap.

    opencode's FIRST bootstrap in a project that carries a project plugin
    hangs -- and `workspace init` writes exactly such a plugin. Measured
    2026-09-04: the process stops right after loading the project config
    and never paints anything, not even after 300 s. A bootstrap that got
    far enough and was then ABORTED warms the project; the next start
    measures 3.4 s. So the aborted first attempt IS the warm-up, and the
    second one needs no special path at all.

    The detector is Herdr's own `--timeout`, never a poll of ours: it is
    documented, and Herdr knows before we do whether the agent is ready
    for input.

    Three answers, because they are three different repairs:

        {"ok": True, "reply": ...}            it is running
        {"ok": False, "error": "agent_start_failed"}   Herdr refused
        {"ok": False, "error": "opencode_stuck"}       the start hangs

    `opencode_stuck` is named after the measured cause, not after the
    runtime: a start of any kind that never reached input-readiness gets
    it. A `claude` worker on a loaded machine can end here too, and the
    repair is the same one -- look at the pane.

    The first attempt is never let run under AGENT_START_REFUSAL_S: a
    smaller `first_timeout_ms` is raised to it, because the refusal/hang
    split above depends on outlasting that threshold.

    A refusal is answered at once and gets NO second attempt: it arrives
    after 0.0 s, the transient half of it was already repeated
    AGENT_START_ATTEMPTS times inside `agent_start`, and a `ctrl-c` into a
    pane where nothing runs is a gesture into the void.

    `retry_timeout_ms <= 0` switches the second attempt off entirely and
    turns the hang straight into `opencode_stuck`. That is for a caller
    that must not block: the keystroke runs inside Herdr's handler
    process (handlers.KEYSTROKE_READY_TIMEOUT_S), and there a hang is a
    deliberately accepted false alarm. It still pays nothing for the
    choice -- the aborted first attempt warms the project either way, so
    the next press is the one that carries.

    Never raises; the caller reads `ok`.
    """
    # The refusal/hang split below is a DURATION test, so the first attempt
    # must outlast the threshold or the split cannot work: a budget under
    # AGENT_START_REFUSAL_S makes every hang look like a refusal, and
    # `agent_start`'s own early stop never fires -- the loop would then repeat
    # the hang AGENT_START_ATTEMPTS times, which is the very cost the
    # threshold exists to prevent. `ready_timeout_s` is validated as `> 0`
    # only, so a caller may legitimately grant less than that.
    first_timeout_ms = max(first_timeout_ms, timeout_ms_for(AGENT_START_REFUSAL_S))
    started_at = now()
    reply = herdr.agent_start(
        name,
        kind=kind,
        pane=pane,
        agent_args=agent_args,
        timeout_ms=first_timeout_ms,
        sleep=sleep,
        now=now,
    )
    if reply:
        return {"ok": True, "reply": reply}
    if now() - started_at < AGENT_START_REFUSAL_S:
        return {"ok": False, "error": "agent_start_failed"}
    if retry_timeout_ms <= 0:
        return {"ok": False, "error": "opencode_stuck"}
    _free_pane(herdr, pane, sleep=sleep, now=now)
    reply = herdr.agent_start(
        name,
        kind=kind,
        pane=pane,
        agent_args=agent_args,
        timeout_ms=retry_timeout_ms,
        sleep=sleep,
        now=now,
    )
    if reply:
        return {"ok": True, "reply": reply, "retried": True}
    return {"ok": False, "error": "opencode_stuck"}
