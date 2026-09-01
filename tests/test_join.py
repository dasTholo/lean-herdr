from pathlib import Path

from lean_herdr.join import (
    agent_id_for_pid,
    pane_for_agent,
    process_ancestors,
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


def _schreibe_stat(tmp_path: Path, pid: int, ppid: int, pgrp: int) -> None:
    """Testhilfe: minimale /proc/<pid>/stat-Zeile mit Kommandoname in Klammern."""
    d = tmp_path / str(pid)
    d.mkdir(parents=True, exist_ok=True)
    (d / "stat").write_text(f"{pid} (x) S {ppid} {pgrp} {pgrp} 0 -1 0\n")


def test_process_ancestors_ohne_proc_ist_leer(tmp_path: Path):
    assert process_ancestors(1, tmp_path) == []


def test_process_ancestors_bei_zyklus_haengt_nicht(tmp_path: Path):
    """Zwei Prozesse, die sich in /proc gegenseitig als Elternteil fuehren,
    duerfen process_ancestors() nicht in eine Endlosschleife schicken."""
    _schreibe_stat(tmp_path, 700, 701, 700)
    _schreibe_stat(tmp_path, 701, 700, 701)
    assert process_ancestors(700, tmp_path) == [701]


def test_resolve_agent_id_ueber_die_vorfahrenkette(tmp_path: Path):
    """Der gemessene Fall: opencode/claude oeffnen eine eigene Prozessgruppe,
    lean-ctx erbt sie — weder der pid- noch der Prozessgruppen-Treffer
    greifen, nur der Vorfahren-Walk findet den Registereintrag."""
    _schreibe_stat(tmp_path, 185157, 12532, 185157)  # zsh, die Pane-Shell
    _schreibe_stat(tmp_path, 185502, 185157, 185502)  # opencode, eigene pgrp
    _schreibe_stat(tmp_path, 185631, 185502, 185502)  # lean-ctx, erbt sie

    agents = [
        {"agent_id": "mcp-185631-abc", "pid": 185631, "started_at": "2026-09-01T08:00:00Z"}
    ]
    got = resolve_agent_id(
        [{"name": "builder", "pane_id": "w2:p1"}],
        {"result": {"process_info": {"shell_pid": 185157}}},
        agents,
        name="builder",
        proc_root=tmp_path,
    )
    assert got == "mcp-185631-abc"


def test_resolve_agent_id_direkter_treffer_hat_vorrang_vor_vorfahren(tmp_path: Path):
    """Gibt es einen direkten pid-Treffer, gewinnt der weiterhin — auch wenn
    ein anderer Registereintrag nur ueber die Vorfahrenkette passen wuerde."""
    _schreibe_stat(tmp_path, 900, 1, 900)  # shell
    _schreibe_stat(tmp_path, 901, 900, 901)  # agent, eigene pgrp
    _schreibe_stat(tmp_path, 902, 901, 901)  # lean-ctx, erbt sie

    agents = [
        {"agent_id": "mcp-900-exakt", "pid": 900, "started_at": "2026-09-01T09:00:00Z"},
        {"agent_id": "mcp-902-vorfahre", "pid": 902, "started_at": "2026-09-01T09:05:00Z"},
    ]
    got = resolve_agent_id(
        [{"name": "builder", "pane_id": "w2:p1"}],
        {"result": {"process_info": {"shell_pid": 900}}},
        agents,
        name="builder",
        proc_root=tmp_path,
    )
    assert got == "mcp-900-exakt"


def test_resolve_agent_id_kein_treffer_bleibt_none(tmp_path: Path):
    _schreibe_stat(tmp_path, 910, 1, 910)  # shell ohne jeden Bezug zur Registry

    agents = [{"agent_id": "mcp-999-fremd", "pid": 999, "started_at": "2026-09-01T09:10:00Z"}]
    got = resolve_agent_id(
        [{"name": "builder", "pane_id": "w2:p1"}],
        {"result": {"process_info": {"shell_pid": 910}}},
        agents,
        name="builder",
        proc_root=tmp_path,
    )
    assert got is None


def test_resolve_agent_id_verschwundener_prozess_wirft_nicht(tmp_path: Path):
    """proc_root existiert gar nicht — resolve_agent_id() liefert None statt
    einer Exception, auch ueber die neue Vorfahren-Stufe hinweg."""
    agents = [{"agent_id": "mcp-999-fremd", "pid": 999, "started_at": "2026-09-01T09:10:00Z"}]
    got = resolve_agent_id(
        [{"name": "builder", "pane_id": "w2:p1"}],
        {"result": {"process_info": {"shell_pid": 12345}}},
        agents,
        name="builder",
        proc_root=tmp_path / "nicht-vorhanden",
    )
    assert got is None
