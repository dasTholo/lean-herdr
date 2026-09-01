"""PID-Join: Herdr-Name → Pane → shell_pid → lean-ctx-agent_id.

Reine Funktionen ueber bereits geholte Antworten. Aller Aussenverkehr liegt
in herdr.py und bus.py — hier steht nur die Zuordnung, damit sie ohne Doppel
testbar bleibt.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any


def pane_for_agent(agent_list: Iterable[dict[str, Any]], name: str) -> str | None:
    """pane_id des Agenten mit diesem Herdr-Namen."""
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
    """Registereintrag mit genau dieser pid — ueber das Feld, nie ueber den ID-String."""
    for agent in agents:
        if agent.get("pid") == pid:
            agent_id = agent.get("agent_id")
            return str(agent_id) if agent_id else None
    return None


def process_group(pid: int, proc_root: str | Path = "/proc") -> int | None:
    """Prozessgruppe einer PID aus /proc/<pid>/stat (Feld 5).

    Gibt None zurueck, wenn /proc fehlt oder der Prozess weg ist — der
    Aufrufer behandelt das als 'kein Treffer', nie als Fehler.
    """
    stat_path = Path(proc_root) / str(pid) / "stat"
    try:
        raw = stat_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    # Der Kommandoname steht in Klammern und darf Leerzeichen enthalten.
    close = raw.rfind(")")
    if close == -1:
        return None
    fields = raw[close + 2 :].split()
    if len(fields) < 3:
        return None
    try:
        return int(fields[2])
    except ValueError:
        return None


def resolve_agent_id(
    agent_list: Iterable[dict[str, Any]],
    process_info: dict[str, Any],
    registry_agents: Iterable[dict[str, Any]],
    *,
    name: str,
    proc_root: str | Path = "/proc",
) -> str | None:
    """Die ganze Kette. None, wenn irgendein Glied fehlt."""
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
    if pgrp is None:
        return None
    kandidaten = [
        a
        for a in agents
        if isinstance(a.get("pid"), int) and process_group(a["pid"], proc_root) == pgrp
    ]
    if not kandidaten:
        return None
    juengster = max(kandidaten, key=lambda a: str(a.get("started_at", "")))
    agent_id = juengster.get("agent_id")
    return str(agent_id) if agent_id else None
