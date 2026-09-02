"""Real lean-ctx calls against an isolated task store.

Runs only under `-m integration`. Every test sets LEAN_CTX_DATA_DIR to
tmp_path -- without it they would write into the operator's real store.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from lean_herdr.tasks import read_tasks, task_store_path

pytestmark = pytest.mark.integration


@pytest.fixture
def isolated_store(tmp_path, monkeypatch) -> Path:
    if shutil.which("lean-ctx") is None:
        pytest.skip("lean-ctx not installed")
    monkeypatch.setenv("LEAN_CTX_DATA_DIR", str(tmp_path))
    return tmp_path


def ctx_task(arguments: dict, *, cwd: Path) -> str:
    proc = subprocess.run(
        [
            "lean-ctx", "call", "ctx_task",
            "--project-root", str(cwd),
            "--json", json.dumps(arguments, separators=(",", ":")),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return (proc.stdout or "").strip()


def test_info_returns_the_expected_shape(isolated_store):
    """A fresh store is empty -- and says so in a fixed shape."""
    answer = ctx_task({"action": "info"}, cwd=isolated_store)
    assert answer.startswith("Task Store:"), answer
    assert "0 total" in answer


def test_create_without_registration_is_refused(isolated_store):
    """The load-bearing finding: writing needs identity, a CLI process has none.

    `lean-ctx call` builds its ToolContext with agent_id=None
    (cli/call_cmd.rs:160 plus ..Default::default()), and ctx_task refuses
    every writing action without identity (tools/ctx_task.rs:12).
    """
    answer = ctx_task(
        {"action": "create", "to_agent": "someone", "description": "x"},
        cwd=isolated_store,
    )
    assert "agent must be registered first" in answer, answer
    assert not (isolated_store / "agents" / "tasks.json").exists(), (
        "a refused creation must not leave a store behind"
    )


def test_list_runs_without_identity_and_finds_nothing(isolated_store):
    """Reading needs no identity -- the agent is then called 'unknown'."""
    answer = ctx_task({"action": "list"}, cwd=isolated_store)
    assert answer == "No tasks found for this agent.", answer


def test_task_store_path_points_at_the_isolated_store(isolated_store):
    """The path we rebuild and the one lean-ctx uses are the same one."""
    assert task_store_path() == isolated_store / "agents" / "tasks.json"
    assert read_tasks() == [], "before the first task the file does not exist"
