"""lean-ctx CLI -> CtxResponse, with an enforced canonical --project-root.

ctx_session write actions are deliberately absent: they report success and
persist nothing (B1). ctx_agent read is absent as well: it requires a
registration inside the same process (B9).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_TIMEOUT_S = 5.0

#: `lean-ctx call` reports an error on the first line, not via the exit code.
ERROR_PREFIXES = ("error:", "Error:")

#: Lines from `ctx_handoff list`: "  1. /path/to/file.json"
LEDGER_LINE = re.compile(r"^\s*\d+\.\s+(\S+)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class CtxResponse:
    """One answer from `lean-ctx call` -- text, not JSON.

    Three states that MUST be kept apart:
    ok=True  + text != ""  -> an answer with content
    ok=True  + text == ""  -> a valid but empty answer (fresh project)
    ok=False + error       -> unavailable | timeout | the error line of lean-ctx
    """

    ok: bool
    text: str = ""
    error: str | None = None

    def json(self) -> dict[str, Any]:
        """The embedded JSON body if there is one -- otherwise {}.

        `ctx_handoff show` writes two header lines and then JSON; other calls
        write none at all. So try from the first `{` on and stay silent when
        it does not work out.
        """
        start = self.text.find("{")
        if start < 0:
            return {}
        try:
            data = json.loads(self.text[start:])
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}


class LeanCtx:
    def __init__(
        self,
        project_root: str | Path,
        *,
        binary: str = "lean-ctx",
        timeout: float = DEFAULT_TIMEOUT_S,
        runner: Any = subprocess.run,
    ) -> None:
        #: Comes from bus.canonical_root() -- never from $PWD, never a worktree.
        self.project_root = str(project_root)
        self.binary = binary
        self.timeout = timeout
        self._runner = runner
        self._available: bool | None = None

    def is_available(self) -> bool:
        if self._available is None:
            self._available = shutil.which(self.binary) is not None
        return self._available

    def _run(self, args: list[str]) -> CtxResponse:
        """Never raise, but ALWAYS distinguish why nothing came back."""
        if not self.is_available():
            return CtxResponse(False, error="unavailable")
        try:
            proc = self._runner(
                [self.binary, *args],
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            return CtxResponse(False, error="timeout")
        except (OSError, subprocess.SubprocessError) as exc:
            return CtxResponse(False, error=f"spawn_failed: {exc}")
        text = (proc.stdout or "").strip()
        first = text.splitlines()[0] if text else ""
        if proc.returncode != 0 or first.startswith(ERROR_PREFIXES):
            return CtxResponse(False, text, error=first or f"exit {proc.returncode}")
        return CtxResponse(True, text)

    def call(self, tool: str, arguments: dict[str, Any]) -> CtxResponse:
        """`lean-ctx call <tool> --project-root <canonical> --json '<args>'`."""
        return self._run(
            [
                "call",
                tool,
                "--project-root",
                self.project_root,
                "--json",
                json.dumps(arguments, separators=(",", ":")),
            ]
        )

    # -- Bus (write only) ------------------------------------------------

    def post(
        self,
        *,
        message: str,
        to_agent: str | None = None,
        task_id: str | None = None,
        category: str = "task",
        metadata: dict[str, Any] | None = None,
    ) -> CtxResponse:
        """Put a message on the bus. NOT usable for work orders.

        From a CLI process this always posts as `anonymous`: registration is
        bound to the pid of a short-lived process (B-2), and the role prompts
        rightly refuse `anonymous` as a client. And `task_id` never arrives:
        every write path of `ctx_agent post` hard-sets it to `None`
        (core/agents/registry.rs:430, shared.rs:31). Work orders therefore run
        through our own log, see lean_herdr/orderlog.py -- which needs no
        identity at all.

        `to_agent` MUST be a lean-ctx agent_id. A friendly name is accepted
        silently and never delivered (B7).
        """
        args: dict[str, Any] = {"action": "post", "message": message, "category": category}
        if to_agent:
            args["to_agent"] = to_agent
        if task_id:
            args["task_id"] = task_id
        if metadata:
            args["metadata"] = metadata
        return self.call("ctx_agent", args)

    # -- Context (read only) ---------------------------------------------

    def session_resume(self) -> CtxResponse:
        """The finished resume report: project, findings, archives, stats.

        The text is the result, not raw material. It is neither taken apart
        nor rebuilt -- lean_herdr/digest.py only unframes it.
        """
        return self.call("ctx_session", {"action": "resume"})

    def handoff_list(self) -> CtxResponse:
        """All handoff ledgers, newest first."""
        return self.call("ctx_handoff", {"action": "list"})

    def handoff_show(self, path: str | Path) -> CtxResponse:
        """One ledger. `path` is MANDATORY -- without it: `error: -32602`."""
        return self.call("ctx_handoff", {"action": "show", "path": str(path)})

    # -- Knowledge (write only) -------------------------------------------

    def knowledge_remember(
        self, *, key: str, value: str, category: str = "decisions"
    ) -> CtxResponse:
        """One entry into the project memory. ONE PER BRANCH, never per order.

        The 800-entry cap is GLOBAL across every project on this machine
        (measured: 278 active / 21 archived). Three to five notes per order
        would be fifty per branch, and after fifteen branches lean-herdr
        would evict other projects' memories. Hence: key
        `lean-herdr/<branch>`, category `decisions`, and ONE TO TWO
        sentences -- what the branch achieved and which decision outlives it.
        The history lives in the order log, not here.

        The brevity is a rule, not a matter of taste: the injection quota is
        capped, so a long entry crowds out more useful ones.

        There is deliberately no `knowledge_recall()`. Knowledge is INJECTED,
        not fetched: a `ctx_read` brings the relevant entries along unasked,
        capped by `recall_facts_limit=10` and filtered by a relevance
        threshold (`ctx_read(handlers.py)` got nothing at all). A read step
        would cost a tool call for something already in the context.

        Nothing is tidied up afterwards either -- lean-ctx has the lifecycle
        already: decay 0.01/day, stale after 30 days, archiving instead of
        deletion at the cap, rehydration on a recall miss. Writing sparingly
        IS the precaution.
        """
        return self.call(
            "ctx_knowledge",
            {"action": "remember", "key": key, "value": value, "category": category},
        )


def newest_handoff(list_text: str) -> str | None:
    """First path from `ctx_handoff list` -- the list comes newest first."""
    match = LEDGER_LINE.search(list_text or "")
    return match.group(1) if match else None
