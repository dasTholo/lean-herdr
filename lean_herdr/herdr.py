"""Herdr CLI → dict. All outbound traffic to Herdr lives here.

No call without a timeout: without one, Herdr waits indefinitely.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

DEFAULT_TIMEOUT_S = 10.0


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
        if not self.is_available():
            return {}
        cmd = [self.binary, *args]
        try:
            proc = self._runner(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout if timeout is not None else self.timeout,
            )
        except (OSError, subprocess.SubprocessError):
            return {}
        if proc.returncode != 0 and not proc.stdout.strip():
            return {}
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

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
        self, name: str, *, kind: str, pane: str, agent_args: Sequence[str] = ()
    ) -> dict[str, Any]:
        """Start an agent in the pane. Native arguments after `--`.

        Herdr rejects multi-line arguments (H2) — role texts come as a file,
        never as argument text.
        """
        args = ["agent", "start", name, "--kind", kind, "--pane", pane]
        if agent_args:
            args = [*args, "--", *agent_args]
        return self.run(*args)

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
