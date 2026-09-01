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


def _stat_felder(pid: int, proc_root: str | Path) -> list[str] | None:
    """Die Felder ab `state` aus /proc/<pid>/stat, oder None bei jedem Fehler.

    Gemeinsame Grundlage fuer process_group() und process_ancestors() — beide
    lesen dieselbe Zeile, nur unterschiedliche Felder daraus.
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
    return raw[close + 2 :].split()


def process_group(pid: int, proc_root: str | Path = "/proc") -> int | None:
    """Prozessgruppe einer PID aus /proc/<pid>/stat (Feld 5).

    Gibt None zurueck, wenn /proc fehlt oder der Prozess weg ist — der
    Aufrufer behandelt das als 'kein Treffer', nie als Fehler.
    """
    fields = _stat_felder(pid, proc_root)
    if fields is None or len(fields) < 3:
        return None
    try:
        return int(fields[2])
    except ValueError:
        return None


def _parent_pid(pid: int, proc_root: str | Path) -> int | None:
    """PPID einer PID aus /proc/<pid>/stat (Feld 4).

    Dieselbe Robustheit wie process_group(): fehlendes /proc, ein
    verschwundener Prozess oder eine kaputte stat-Datei ergeben None statt
    einer Exception.
    """
    fields = _stat_felder(pid, proc_root)
    if fields is None or len(fields) < 2:
        return None
    try:
        return int(fields[1])
    except ValueError:
        return None


def process_ancestors(
    pid: int, proc_root: str | Path = "/proc", max_schritte: int = 32
) -> list[int]:
    """Vorfahrenkette von pid ueber PPID, naechster Vorfahre zuerst.

    Grund: Herdrs `agent start` legt den Agenten in eine bestehende
    interaktive Shell (siehe resolve_agent_id()), aber opencode und claude
    oeffnen dabei eine **eigene** Prozessgruppe, die der lean-ctx-MCP-Server
    erbt. Gemessen:

        zsh (shell_pid, pgrp=shell_pid) -> opencode/claude (eigene pgrp)
            -> lean-ctx (erbt die Agenten-pgrp)

    Weder der direkte pid-Treffer noch der Prozessgruppen-Fallback in
    resolve_agent_id() greifen dann, obwohl shell_pid ein Vorfahre des
    lean-ctx-Prozesses bleibt — deshalb dieser Walk als dritte Stufe.

    Wie process_group(): fehlendes /proc, ein verschwundener Prozess oder
    eine kaputte stat-Datei ergeben eine leere Liste, nie eine Exception.
    Begrenzt auf `max_schritte`, damit ein Zyklus in einem kaputten /proc
    nicht zur Endlosschleife wird; zusaetzlich stoppt die Kette bei PID <= 1
    und bei einer PID, die schon einmal aufgetaucht ist.
    """
    kette: list[int] = []
    gesehen = {pid}
    aktuell = pid
    for _ in range(max_schritte):
        ppid = _parent_pid(aktuell, proc_root)
        if ppid is None or ppid <= 1 or ppid in gesehen:
            break
        kette.append(ppid)
        gesehen.add(ppid)
        aktuell = ppid
    return kette


def _juengster_agent_id(kandidaten: list[dict[str, Any]]) -> str | None:
    """Von mehreren Kandidaten den mit dem juengsten started_at waehlen."""
    if not kandidaten:
        return None
    juengster = max(kandidaten, key=lambda a: str(a.get("started_at", "")))
    agent_id = juengster.get("agent_id")
    return str(agent_id) if agent_id else None


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
    if pgrp is not None:
        kandidaten = [
            a
            for a in agents
            if isinstance(a.get("pid"), int) and process_group(a["pid"], proc_root) == pgrp
        ]
        gefunden = _juengster_agent_id(kandidaten)
        if gefunden is not None:
            return gefunden

    # Stufe 3: Vorfahren-Walk. Im echten Betrieb gemessen (siehe
    # process_ancestors()): opencode/claude oeffnen eine eigene
    # Prozessgruppe, lean-ctx erbt sie — weder der direkte noch der
    # Prozessgruppen-Treffer greifen dann, obwohl shell_pid ein Vorfahre
    # des Registry-Prozesses bleibt.
    vorfahren_kandidaten = [
        a
        for a in agents
        if isinstance(a.get("pid"), int) and pid in process_ancestors(a["pid"], proc_root)
    ]
    return _juengster_agent_id(vorfahren_kandidaten)
