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

    def agent_start(
        self,
        name: str,
        *,
        kind: str,
        pane: str,
        agent_args: Sequence[str] = (),
        sleep: Callable[[float], None] = time.sleep,
    ) -> dict[str, Any]:
        """Start an agent in the pane. Native arguments after `--`.

        Herdr rejects multi-line arguments (H2) — role texts come as a file,
        never as argument text.

        Retries a non-zero exit code up to AGENT_START_ATTEMPTS times: the
        pane split a moment ago may not have reached its interactive prompt
        yet, and that refusal is transient — see the constants for the
        measurement. Returns the reply of the last attempt, `{}` when every
        one of them was refused; that empty dict is what the callers report
        `agent_start_failed` on.
        """
        args = ["agent", "start", name, "--kind", kind, "--pane", pane]
        if agent_args:
            args = [*args, "--", *agent_args]
        reply: dict[str, Any] = {}
        for attempt in range(AGENT_START_ATTEMPTS):
            reply, code = self._run(*args)
            if code <= 0:
                # 0 is the start that worked. A NEGATIVE code is
                # NO_PROCESS_RC: no binary, an OSError, a timeout. None of
                # those is the prompt race, and repeating a timeout five
                # times would cost five full timeouts.
                return reply
            if attempt + 1 < AGENT_START_ATTEMPTS:
                sleep(AGENT_START_INTERVAL_S)
        return reply

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
