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


def test_pane_for_agent_matches_the_name():
    assert pane_for_agent(AGENT_LIST, "builder") == "w2:p1"
    assert pane_for_agent(AGENT_LIST, "does-not-exist") is None


def test_shell_pid_from_nested_response():
    assert shell_pid_from_process_info(PROCESS_INFO) == 2018183
    assert shell_pid_from_process_info({"result": {}}) is None
    assert shell_pid_from_process_info({}) is None


def test_agent_id_via_the_pid_field_not_via_the_string():
    assert agent_id_for_pid(REGISTRY_AGENTS, 2018183) == "mcp-2018183-70c877bf"
    assert agent_id_for_pid(REGISTRY_AGENTS, 999) is None


def test_resolve_agent_id_full_chain():
    got = resolve_agent_id(AGENT_LIST, PROCESS_INFO, REGISTRY_AGENTS, name="builder")
    assert got == "mcp-2018183-70c877bf"


def test_resolve_agent_id_without_pane_is_none():
    assert resolve_agent_id(AGENT_LIST, PROCESS_INFO, REGISTRY_AGENTS, name="gone") is None


def test_resolve_agent_id_falls_back_to_the_process_group(tmp_path: Path):
    """The lean-ctx process is a child of the pane shell, not the shell itself."""

    def stat(pid: int, pgrp: int) -> None:
        d = tmp_path / str(pid)
        d.mkdir(parents=True, exist_ok=True)
        (d / "stat").write_text(f"{pid} (lean-ctx) S 1 {pgrp} {pgrp} 0 -1 0\n")

    stat(500, 500)  # the pane shell
    stat(501, 500)  # its lean-ctx child
    agents = [{"agent_id": "mcp-501-abc", "pid": 501, "started_at": "2026-09-01T07:00:00Z"}]
    got = resolve_agent_id(
        [{"name": "builder", "pane_id": "w2:p1"}],
        {"result": {"process_info": {"shell_pid": 500}}},
        agents,
        name="builder",
        proc_root=tmp_path,
    )
    assert got == "mcp-501-abc"


def test_process_group_without_proc_is_none(tmp_path: Path):
    assert process_group(1, tmp_path) is None


def _write_stat(tmp_path: Path, pid: int, ppid: int, pgrp: int) -> None:
    """Test helper: minimal /proc/<pid>/stat line with the command name in parens."""
    d = tmp_path / str(pid)
    d.mkdir(parents=True, exist_ok=True)
    (d / "stat").write_text(f"{pid} (x) S {ppid} {pgrp} {pgrp} 0 -1 0\n")


def test_process_ancestors_without_proc_is_empty(tmp_path: Path):
    assert process_ancestors(1, tmp_path) == []


def test_process_ancestors_does_not_hang_on_a_cycle(tmp_path: Path):
    """Two processes that list each other as parent in /proc must not send
    process_ancestors() into an infinite loop."""
    _write_stat(tmp_path, 700, 701, 700)
    _write_stat(tmp_path, 701, 700, 701)
    assert process_ancestors(700, tmp_path) == [701]


def test_resolve_agent_id_via_the_ancestor_chain(tmp_path: Path):
    """The measured case: opencode/claude open their own process group,
    lean-ctx inherits it — neither the pid hit nor the process-group hit
    applies, only the ancestor walk finds the registry entry."""
    _write_stat(tmp_path, 185157, 12532, 185157)  # zsh, the pane shell
    _write_stat(tmp_path, 185502, 185157, 185502)  # opencode, own pgrp
    _write_stat(tmp_path, 185631, 185502, 185502)  # lean-ctx, inherits it

    agents = [{"agent_id": "mcp-185631-abc", "pid": 185631, "started_at": "2026-09-01T08:00:00Z"}]
    got = resolve_agent_id(
        [{"name": "builder", "pane_id": "w2:p1"}],
        {"result": {"process_info": {"shell_pid": 185157}}},
        agents,
        name="builder",
        proc_root=tmp_path,
    )
    assert got == "mcp-185631-abc"


def test_resolve_agent_id_direct_hit_takes_precedence_over_ancestors(tmp_path: Path):
    """When there is a direct pid hit, it still wins — even if another
    registry entry would only match via the ancestor chain."""
    _write_stat(tmp_path, 900, 1, 900)  # shell
    _write_stat(tmp_path, 901, 900, 901)  # agent, own pgrp
    _write_stat(tmp_path, 902, 901, 901)  # lean-ctx, inherits it

    agents = [
        {"agent_id": "mcp-900-exact", "pid": 900, "started_at": "2026-09-01T09:00:00Z"},
        {"agent_id": "mcp-902-ancestor", "pid": 902, "started_at": "2026-09-01T09:05:00Z"},
    ]
    got = resolve_agent_id(
        [{"name": "builder", "pane_id": "w2:p1"}],
        {"result": {"process_info": {"shell_pid": 900}}},
        agents,
        name="builder",
        proc_root=tmp_path,
    )
    assert got == "mcp-900-exact"


def test_resolve_agent_id_no_hit_stays_none(tmp_path: Path):
    _write_stat(tmp_path, 910, 1, 910)  # shell with no relation to the registry at all

    agents = [{"agent_id": "mcp-999-unrelated", "pid": 999, "started_at": "2026-09-01T09:10:00Z"}]
    got = resolve_agent_id(
        [{"name": "builder", "pane_id": "w2:p1"}],
        {"result": {"process_info": {"shell_pid": 910}}},
        agents,
        name="builder",
        proc_root=tmp_path,
    )
    assert got is None


def test_resolve_agent_id_vanished_process_does_not_raise(tmp_path: Path):
    """proc_root does not exist at all — resolve_agent_id() returns None
    instead of an exception, even across the new ancestor stage."""
    agents = [{"agent_id": "mcp-999-unrelated", "pid": 999, "started_at": "2026-09-01T09:10:00Z"}]
    got = resolve_agent_id(
        [{"name": "builder", "pane_id": "w2:p1"}],
        {"result": {"process_info": {"shell_pid": 12345}}},
        agents,
        name="builder",
        proc_root=tmp_path / "does-not-exist",
    )
    assert got is None
