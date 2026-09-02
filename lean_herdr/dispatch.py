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
from typing import Any

from lean_herdr.bus import (
    BusError,
    agents_in_registry,
    canonical_root,
    read_registry,
)
from lean_herdr.herdr import Herdr
from lean_herdr.join import resolve_agent_id
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="herdr-dispatch", description="One dispatch, one call.")
    p.add_argument("role", help="builder | reviewer | orchestrator")
    p.add_argument("--kind", required=True, choices=("claude", "opencode"))
    p.add_argument("--model", required=True)
    p.add_argument("--role-file", required=True, type=Path)
    p.add_argument("--worktree", default=None, help="branch; the pane runs in its worktree")
    p.add_argument("--profile", default=None, help="overrides the default of the role")
    return p


def main(argv: list[str] | None = None) -> int:
    """Output: one JSON line on stdout. Exit ALWAYS 0.

    The orchestrator reads `ok`, not the exit code -- so that a failure does
    not abort its shell call.
    """
    args = build_parser().parse_args(argv)
    req = DispatchRequest(
        role=args.role,
        kind=args.kind,
        model=args.model,
        role_file=args.role_file,
        worktree=args.worktree,
        profile=args.profile,
    )
    try:
        root = canonical_root()
        herdr = Herdr()
        result = dispatch(req, herdr=herdr, root=root, cwd=root)
    except Exception as exc:  # noqa: BLE001 -- never abort the caller
        result = {"ok": False, "error": f"dispatch_crashed: {exc}"}
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    return 0
