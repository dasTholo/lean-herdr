"""PID join: Herdr name → pane → shell_pid → lean-ctx agent_id.

Pure functions over responses that were already fetched. All outside traffic
lives in herdr.py and bus.py — this module holds only the mapping, so it
stays testable without duplication.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any


def pane_for_agent(agent_list: Iterable[dict[str, Any]], name: str) -> str | None:
    """pane_id of the agent with this Herdr name."""
    for entry in agent_list:
        if entry.get("name") == name:
            pane = entry.get("pane_id") or entry.get("pane")
            return str(pane) if pane else None
    return None


def shell_pid_from_process_info(info: dict[str, Any]) -> int | None:
    """`herdr pane process-info --pane <id>` → .result.process_info.shell_pid."""
    node: Any = info
    for key in ("result", "process_info", "shell_pid"):
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return int(node) if isinstance(node, int) else None


def agent_id_for_pid(agents: Iterable[dict[str, Any]], pid: int) -> str | None:
    """Registry entry with exactly this pid — via the field, never via the ID string."""
    for agent in agents:
        if agent.get("pid") == pid:
            agent_id = agent.get("agent_id")
            return str(agent_id) if agent_id else None
    return None


def _stat_fields(pid: int, proc_root: str | Path) -> list[str] | None:
    """The fields from `state` onward in /proc/<pid>/stat, or None on any error.

    Shared basis for process_group() and process_ancestors() — both
    read the same line, just different fields from it.
    """
    stat_path = Path(proc_root) / str(pid) / "stat"
    try:
        raw = stat_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    # The command name is in parentheses and may contain spaces.
    close = raw.rfind(")")
    if close == -1:
        return None
    return raw[close + 2 :].split()


def process_group(pid: int, proc_root: str | Path = "/proc") -> int | None:
    """Process group of a PID from /proc/<pid>/stat (field 5).

    Returns None when /proc is missing or the process is gone — the
    caller treats that as 'no hit', never as an error.
    """
    fields = _stat_fields(pid, proc_root)
    if fields is None or len(fields) < 3:
        return None
    try:
        return int(fields[2])
    except ValueError:
        return None


def _parent_pid(pid: int, proc_root: str | Path) -> int | None:
    """PPID of a PID from /proc/<pid>/stat (field 4).

    Same robustness as process_group(): missing /proc, a
    vanished process, or a broken stat file all produce None instead of
    an exception.
    """
    fields = _stat_fields(pid, proc_root)
    if fields is None or len(fields) < 2:
        return None
    try:
        return int(fields[1])
    except ValueError:
        return None


def process_ancestors(
    pid: int, proc_root: str | Path = "/proc", max_steps: int = 32
) -> list[int]:
    """Ancestor chain of pid via PPID, nearest ancestor first.

    Reason: Herdr's `agent start` places the agent into an existing
    interactive shell (see resolve_agent_id()), but opencode and claude
    open their **own** process group when they do, which the lean-ctx MCP
    server inherits. Measured:

        zsh (shell_pid, pgrp=shell_pid) -> opencode/claude (own pgrp)
            -> lean-ctx (inherits the agent's pgrp)

    Neither the direct pid hit nor the process-group fallback in
    resolve_agent_id() then applies, even though shell_pid remains an
    ancestor of the lean-ctx process — hence this walk as a third stage.

    Like process_group(): missing /proc, a vanished process, or a
    broken stat file all produce an empty list, never an exception.
    Bounded by `max_steps`, so that a cycle in a broken /proc
    does not become an infinite loop; the chain also stops at PID <= 1
    and at a PID that has already shown up once.
    """
    chain: list[int] = []
    seen = {pid}
    current = pid
    for _ in range(max_steps):
        ppid = _parent_pid(current, proc_root)
        if ppid is None or ppid <= 1 or ppid in seen:
            break
        chain.append(ppid)
        seen.add(ppid)
        current = ppid
    return chain


def _newest_agent_id(candidates: list[dict[str, Any]]) -> str | None:
    """From several candidates, pick the one with the newest started_at."""
    if not candidates:
        return None
    newest = max(candidates, key=lambda a: str(a.get("started_at", "")))
    agent_id = newest.get("agent_id")
    return str(agent_id) if agent_id else None


def resolve_agent_id(
    agent_list: Iterable[dict[str, Any]],
    process_info: dict[str, Any],
    registry_agents: Iterable[dict[str, Any]],
    *,
    name: str,
    proc_root: str | Path = "/proc",
) -> str | None:
    """The whole chain. None if any link is missing."""
    if pane_for_agent(agent_list, name) is None:
        return None
    pid = shell_pid_from_process_info(process_info)
    if pid is None:
        return None
    agents = list(registry_agents)
    exact = agent_id_for_pid(agents, pid)
    if exact is not None:
        return exact

    pgrp = process_group(pid, proc_root)
    if pgrp is not None:
        candidates = [
            a
            for a in agents
            if isinstance(a.get("pid"), int) and process_group(a["pid"], proc_root) == pgrp
        ]
        found = _newest_agent_id(candidates)
        if found is not None:
            return found

    # Stage 3: ancestor walk. Measured in real operation (see
    # process_ancestors()): opencode/claude open their own
    # process group, lean-ctx inherits it — neither the direct nor the
    # process-group hit then applies, even though shell_pid remains an
    # ancestor of the registry process.
    ancestor_candidates = [
        a
        for a in agents
        if isinstance(a.get("pid"), int) and pid in process_ancestors(a["pid"], proc_root)
    ]
    return _newest_agent_id(ancestor_candidates)
