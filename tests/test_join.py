from pathlib import Path

from lean_herdr.join import (
    agent_id_for_pid,
    pane_for_agent,
    process_group,
    resolve_agent_id,
    shell_pid_from_process_info,
)

AGENT_LIST = [
    {"name": "orch", "pane_id": "w1:p1", "kind": "opencode"},
    {"name": "builder", "pane_id": "w2:p1", "kind": "claude"},
]

PROCESS_INFO = {"result": {"process_info": {"shell_pid": 2018183, "cwd": "/x"}}}

REGISTRY_AGENTS = [
    {"agent_id": "mcp-3540259-4ac80990", "pid": 3540259, "started_at": "2026-09-01T05:59:27Z"},
    {"agent_id": "mcp-2018183-70c877bf", "pid": 2018183, "started_at": "2026-09-01T06:10:00Z"},
]


def test_pane_for_agent_trifft_den_namen():
    assert pane_for_agent(AGENT_LIST, "builder") == "w2:p1"
    assert pane_for_agent(AGENT_LIST, "gibt-es-nicht") is None


def test_shell_pid_aus_verschachtelter_antwort():
    assert shell_pid_from_process_info(PROCESS_INFO) == 2018183
    assert shell_pid_from_process_info({"result": {}}) is None
    assert shell_pid_from_process_info({}) is None


def test_agent_id_ueber_das_pid_feld_nicht_ueber_den_string():
    assert agent_id_for_pid(REGISTRY_AGENTS, 2018183) == "mcp-2018183-70c877bf"
    assert agent_id_for_pid(REGISTRY_AGENTS, 999) is None


def test_resolve_agent_id_ganze_kette():
    got = resolve_agent_id(AGENT_LIST, PROCESS_INFO, REGISTRY_AGENTS, name="builder")
    assert got == "mcp-2018183-70c877bf"


def test_resolve_agent_id_ohne_pane_ist_none():
    assert resolve_agent_id(AGENT_LIST, PROCESS_INFO, REGISTRY_AGENTS, name="weg") is None


def test_resolve_agent_id_faellt_auf_die_prozessgruppe_zurueck(tmp_path: Path):
    """Der lean-ctx-Prozess ist ein Kind der Pane-Shell, nicht die Shell selbst."""

    def stat(pid: int, pgrp: int) -> None:
        d = tmp_path / str(pid)
        d.mkdir(parents=True, exist_ok=True)
        (d / "stat").write_text(f"{pid} (lean-ctx) S 1 {pgrp} {pgrp} 0 -1 0\n")

    stat(500, 500)  # die Pane-Shell
    stat(501, 500)  # ihr lean-ctx-Kind
    agents = [{"agent_id": "mcp-501-abc", "pid": 501, "started_at": "2026-09-01T07:00:00Z"}]
    got = resolve_agent_id(
        [{"name": "builder", "pane_id": "w2:p1"}],
        {"result": {"process_info": {"shell_pid": 500}}},
        agents,
        name="builder",
        proc_root=tmp_path,
    )
    assert got == "mcp-501-abc"


def test_process_group_ohne_proc_ist_none(tmp_path: Path):
    assert process_group(1, tmp_path) is None
