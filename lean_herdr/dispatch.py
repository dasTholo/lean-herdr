"""One dispatch = one call.

Pure mechanics: the script asks no model and makes no assignment decision.
Who gets which task is decided by the orchestrator, before it comes in
here.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from lean_herdr.bus import (
    BusError,
    agents_in_registry,
    canonical_root,
    read_registry,
)
from lean_herdr.export import session_error, session_id_from_agent_list
from lean_herdr.herdr import Herdr
from lean_herdr.join import resolve_agent_id
from lean_herdr.tasks import (
    Task,
    TaskError,
    find_task,
    message_from,
    read_tasks,
)
from lean_herdr.worktree import (
    WorktreeOpenFailed,
    WorktrunkMissing,
    anchor_pane,
    ensure_worktree,
)

#: Default per role -- measured fixed cost per step:
#: minimal 2 711, standard 4 920, power 11 559 token.
PROFILE_BY_ROLE = {"orchestrator": "minimal"}
DEFAULT_PROFILE = "standard"

AGENT_READY_TIMEOUT_S = 45.0
AGENT_READY_INTERVAL_S = 0.5

#: The wait mode asks the file, not the CLI: no process start per round.
POLL_INTERVAL_S = 1.0

#: Exactly one ring per wait call. The payload lives in the task store.
#: Worded neutrally, because the same text also wakes a task resumed after a
#: question -- then it is not new. And it points at `get`, not `list`: only
#: `get` prints the history that carries the orchestrator's answer. The text
#: itself stays German, like the role prompt it is spoken into.
WAKE_PROMPT = "Aufgabe {task_id} wartet auf dich — ctx_task get zeigt Auftrag und Verlauf."

#: Machine-readable verdict on the FIRST line of the completion message.
#: Replaces the bus field `category` that fell away: without it the
#: orchestrator would have to read prose to tell 'can be merged' from 'must
#: go back' -- exactly what this design rules out. `failed` will not do: a
#: reasoned rejection is not a failure. The marker stays German because the
#: reviewer's role prompt is.
VERDICT_RE = re.compile(r"VERDIKT:\s*(result|reject)\s*$")


@dataclass(frozen=True)
class DispatchRequest:
    role: str
    kind: str
    model: str
    role_file: Path
    worktree: str | None = None
    profile: str | None = None


def profile_for(role: str, override: str | None = None) -> str:
    return override or PROFILE_BY_ROLE.get(role, DEFAULT_PROFILE)


def agent_name(role: str, worktree: str | None = None) -> str:
    """The reuse key is (branch, role), not the branch alone.

    A worktree carries several workers -- builder and reviewer -- and a
    reviewer dispatch onto the same branch must never hit the running
    builder.
    """
    if not worktree:
        return role
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", worktree).strip("-").lower()
    return f"{role}-{slug}"


def agent_args(kind: str, model: str, role_file: Path) -> list[str]:
    """Native arguments. Role prompts travel as a FILE, never as text (H2)."""
    if kind == "claude":
        return ["--model", model, "--append-system-prompt-file", str(role_file)]
    if kind == "opencode":
        # With opencode the role prompt hangs on agent.<name>.prompt in
        # opencode.jsonc; here only the agent is picked.
        return ["--model", model, "--agent", role_file.stem]
    raise ValueError(f"unknown kind: {kind}")


def wait_for_agent_id(
    herdr: Herdr,
    name: str,
    *,
    registry_path: str | Path | None = None,
    timeout_s: float = AGENT_READY_TIMEOUT_S,
    interval_s: float = AGENT_READY_INTERVAL_S,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> str | None:
    """Wait for the MCP server of the freshly started agent.

    Blocks in the shell call, not in the model -- that is the cheap part.
    """
    deadline = now() + timeout_s
    while True:
        agents = herdr.agent_list()
        pane = next((a.get("pane_id") for a in agents if a.get("name") == name), None)
        if pane:
            info = herdr.pane_process_info(str(pane))
            try:
                registry = read_registry(registry_path)
            except BusError:
                registry = {}
            agent_id = resolve_agent_id(
                agents, info, agents_in_registry(registry), name=name
            )
            if agent_id:
                return agent_id
        if now() >= deadline:
            return None
        sleep(interval_s)


def _result(
    ok: bool, pane: str | None, agent_id: str | None, **rest: Any
) -> dict[str, Any]:
    return {"ok": ok, "pane": pane, "agent_id": agent_id, **rest}


def dispatch(
    req: DispatchRequest,
    *,
    herdr: Herdr,
    root: Path,
    cwd: Path | None = None,
    registry_path: str | Path | None = None,
    waiter: Callable[..., str | None] = wait_for_agent_id,
) -> dict[str, Any]:
    """Build one worker. Never raises; the result carries `ok`.

    Creates NO task and does not wait. This process can do neither:
    `ctx_task create` requires a registered, long-lived MCP agent
    (tools/ctx_task.rs:12), and a `lean-ctx call` is exactly not that.
    """
    name = agent_name(req.role, req.worktree)
    target_cwd = cwd if cwd is not None else root
    # None means: split in our own workspace (--current). Only the worktree
    # case sets an anchor.
    target_pane: str | None = None
    if req.worktree:
        try:
            target = ensure_worktree(req.worktree, herdr=herdr, cwd=root)
        except WorktrunkMissing:
            return _result(False, None, None, error="worktrunk_missing")
        except WorktreeOpenFailed as exc:
            # Do not carry on: a pane in the right directory that teardown
            # does not know about is worse than a clean abort.
            return _result(False, None, None, error=f"worktree_open_failed: {exc}")
        target_cwd = target.path
        target_pane = anchor_pane(herdr, target.workspace_id)
        if target_pane is None:
            return _result(False, None, None, error="no_anchor_pane")

    existing = next((a for a in herdr.agent_list() if a.get("name") == name), None)
    if existing:
        pane = str(existing.get("pane_id") or "")
        # Reset between two tasks: /clear caps the context at the base load
        # and triggers NO lifecycle change (H4).
        herdr.agent_prompt(name, "/clear", wait=False)
    else:
        pane = herdr.pane_split(
            target_cwd,
            pane=target_pane,
            env={
                "LEAN_CTX_TOOL_PROFILE": profile_for(req.role, req.profile),
                "LEAN_CTX_ROLE": req.role,
            },
        ) or ""
        if not pane:
            return _result(False, None, None, error="pane_split_failed")
        herdr.agent_start(
            name,
            kind=req.kind,
            pane=pane,
            agent_args=agent_args(req.kind, req.model, req.role_file),
        )

    agent_id = waiter(herdr, name, registry_path=registry_path)
    if not agent_id:
        return _result(False, pane, None, error="no_agent_id")
    # This is the end. The orchestrator creates the task itself through
    # ctx_task, with exactly this agent_id as to_agent: tasks_for_agent()
    # compares exactly as a string (core/a2a/task.rs:236), a friendly name
    # would never find the task.
    return _result(True, pane, agent_id)


@dataclass(frozen=True)
class AwaitRequest:
    role: str
    kind: str
    task_id: str
    worktree: str | None = None
    timeout_ms: int = 300_000


def verdict(message: str | None) -> str | None:
    """`VERDIKT: result` or `VERDIKT: reject` on the FIRST line -- else None.

    First line only, so that quoting the same words further down in the
    reasoning cannot flip the verdict.
    """
    lines = (message or "").lstrip().splitlines()
    hit = VERDICT_RE.match(lines[0]) if lines else None
    return hit.group(1) if hit else None


def _await_result(ok: bool, task_id: str, **rest: Any) -> dict[str, Any]:
    return {"ok": ok, "task_id": task_id, **rest}


def _result_for_state(task: Task) -> dict[str, Any] | None:
    """The return for this state -- or None if we keep waiting.

    `input-required` returns even though is_terminal() does not call it
    terminal: only the orchestrator can answer, and it is asleep inside this
    very call. Without this return the script would wait for something that
    cannot happen without it.
    """
    message = message_from(task, task.to_agent)
    if task.state == "completed":
        result = _await_result(
            True, task.id, state=task.state, message=message or ""
        )
        ruling = verdict(message)
        if ruling:
            result["verdict"] = ruling
        return result
    if task.state == "failed":
        return _await_result(
            False,
            task.id,
            state=task.state,
            error=f"agent_failed: {message or 'no reason given'}",
        )
    if task.state == "canceled":
        return _await_result(False, task.id, state=task.state, error="task_canceled")
    if task.state == "input-required":
        return _await_result(
            False,
            task.id,
            state=task.state,
            error="input_required",
            message=message or "",
        )
    return None


def await_task(
    req: AwaitRequest,
    *,
    herdr: Herdr,
    root: Path,
    tasks_path: str | Path | None = None,
    interval_s: float = POLL_INTERVAL_S,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Wait for the state change the worker sets itself.

    The waiting stays in the script: no CLI, no registration, no model step
    per round. Never raises; the result carries `ok`.
    """
    name = agent_name(req.role, req.worktree)
    deadline = now() + req.timeout_ms / 1000.0
    has_rung = False
    state = ""
    while True:
        try:
            tasks = read_tasks(tasks_path)
        except TaskError as exc:
            return _await_result(
                False, req.task_id, error=f"tasks_unreadable: {exc}"
            )
        task = find_task(tasks, req.task_id)
        if task is None:
            # The orchestrator created the task BEFORE this call, and
            # ctx_task renames the finished file into place before it
            # answers (core/a2a/task.rs:213). Missing here means the id is
            # wrong -- waiting will not change that.
            return _await_result(False, req.task_id, error="task_not_found")
        state = task.state
        outcome = _result_for_state(task)
        if outcome is not None:
            return outcome
        if not has_rung:
            # Exactly once, and without --wait: whoever sleeps through the
            # first ring will not wake for the second. That is what the
            # timeout is for.
            herdr.agent_prompt(
                name, WAKE_PROMPT.format(task_id=req.task_id), wait=False
            )
            has_rung = True
        if now() >= deadline:
            break
        sleep(interval_s)

    # No state change before the deadline. The truth lives in the session
    # store, not in the lifecycle (H1): a crashed worker leaves the task
    # sitting on `created` or `working`.
    error = session_error(
        req.kind, session_id_from_agent_list(herdr.agent_list(), name), root
    )
    if error:
        return _await_result(
            False, req.task_id, state=state, error=f"agent_error: {error}"
        )
    return _await_result(False, req.task_id, state=state, error="no_reply")


class UsageError(Exception):
    """A parser complaint -- raised instead of ending the process."""


class _Parser(argparse.ArgumentParser):
    """argparse ends a usage error with exit 2 and one line on stderr.

    Same reason as missing_flags(): the orchestrator reads `ok` on stdout and
    would see no output at all. A missing `--kind`, a missing `role`, an
    invalid choice and an unknown flag all run through error(), so redirecting
    it alone gives every operator error one shape. `--help` goes through
    exit(), not error(), and stays untouched.
    """

    def error(self, message: str) -> NoReturn:
        raise UsageError(message)


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(
        prog="herdr-dispatch", description="Build or wait -- one call."
    )
    p.add_argument("role", help="builder | reviewer | orchestrator")
    p.add_argument("--kind", required=True, choices=("claude", "opencode"))
    # `--await` would yield the dest `await` -- a keyword, unreachable as
    # args.await. The dest MUST be set.
    p.add_argument(
        "--await",
        dest="waiting",
        action="store_true",
        help="wait for a task to finish instead of building a worker",
    )
    p.add_argument("--task-id", default=None, help="required with --await")
    p.add_argument("--model", default=None, help="required in build mode")
    p.add_argument(
        "--role-file", default=None, type=Path, help="required in build mode"
    )
    p.add_argument(
        "--worktree", default=None, help="branch; the pane runs in its worktree"
    )
    p.add_argument(
        "--profile", default=None, help="overrides the role's default profile"
    )
    p.add_argument("--timeout-ms", type=int, default=300_000, help="only with --await")
    return p


def missing_flags(args: argparse.Namespace) -> str | None:
    """Mode-dependent required flags -- deliberately NOT via argparse.

    `required=True` ends the process with exit 2 and one line on stderr.
    The orchestrator reads `ok` on stdout; a typo would look to it like no
    output at all.
    """
    if args.waiting:
        return None if args.task_id else "--await needs --task-id"
    missing = [
        flag
        for flag, value in (("--model", args.model), ("--role-file", args.role_file))
        if not value
    ]
    return f"build mode needs {' and '.join(missing)}" if missing else None


def main(argv: list[str] | None = None) -> int:
    """Output: one JSON line on stdout. Exit ALWAYS 0.

    The orchestrator reads `ok`, not the exit code -- so a failure does not
    abort its shell call.
    """
    result: dict[str, Any]
    try:
        args = build_parser().parse_args(argv)
        missing = missing_flags(args)
        if missing:
            result = {"ok": False, "error": f"usage_error: {missing}"}
        elif args.waiting:
            result = await_task(
                AwaitRequest(
                    role=args.role,
                    kind=args.kind,
                    task_id=args.task_id,
                    worktree=args.worktree,
                    timeout_ms=args.timeout_ms,
                ),
                herdr=Herdr(),
                root=canonical_root(),
            )
        else:
            root = canonical_root()
            result = dispatch(
                DispatchRequest(
                    role=args.role,
                    kind=args.kind,
                    model=args.model,
                    role_file=args.role_file,
                    worktree=args.worktree,
                    profile=args.profile,
                ),
                herdr=Herdr(),
                root=root,
                cwd=root,
            )
    except UsageError as exc:
        result = {"ok": False, "error": f"usage_error: {exc}"}
    except Exception as exc:  # noqa: BLE001 -- never abort the caller
        result = {"ok": False, "error": f"dispatch_crashed: {exc}"}
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    return 0
