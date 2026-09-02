import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from lean_herdr.tasks import (
    TERMINAL_STATES,
    Task,
    TaskError,
    find_task,
    is_terminal,
    message_from,
    normalize_state,
    read_tasks,
    task_store_path,
)

FIXTURE = Path(__file__).parent / "fixtures" / "tasks.sample.json"
MEASURED_ID = "task-1a05e34cd15-1cf3b885"
CREATOR = "mcp-218709-e52c50725afd452fb2ea4bba4cf93730"


@pytest.fixture
def sample() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_the_frozen_sample_has_the_expected_shape(sample):
    """Breaks visibly when lean-ctx changes its task format."""
    assert "tasks" in sample, sorted(sample)
    first = sample["tasks"][0]
    for field in (
        "id", "from_agent", "to_agent", "state", "description",
        "messages", "artifacts", "history", "metadata",
        "created_at", "updated_at",
    ):
        assert field in first, f"field {field} missing from the sample"


def test_the_sample_carries_the_enum_variant_not_the_cli_name(sample):
    """The finding normalize_state() rests on."""
    assert sample["tasks"][0]["state"] == "Created", (
        "tasks.json writes the Rust enum variant. If something lowercase "
        "shows up here, lean-ctx has gained serde(rename) and _STATE_NAMES "
        "must follow."
    )


def test_the_sample_carries_real_measured_values(sample):
    """Lesson from task 2 of the predecessor plan: invented values prove nothing."""
    task = sample["tasks"][0]
    assert task["id"] == MEASURED_ID
    assert task["from_agent"] == CREATOR, "the sender is a real MCP agent_id"
    assert task["messages"][0]["role"] == task["from_agent"]


def test_state_names_are_translated():
    assert normalize_state("Created") == "created"
    assert normalize_state("Working") == "working"
    assert normalize_state("InputRequired") == "input-required"
    assert normalize_state("Completed") == "completed"
    assert normalize_state("Failed") == "failed"
    assert normalize_state("Canceled") == "canceled"


def test_an_unknown_state_survives_and_is_never_terminal():
    """A format change must never turn into a false success."""
    assert normalize_state("Vanished") == "Vanished"
    assert is_terminal("Vanished") is False
    assert normalize_state(None) == ""
    assert is_terminal("") is False


def test_terminal_is_exactly_completed_failed_canceled():
    assert set(TERMINAL_STATES) == {"completed", "failed", "canceled"}
    assert all(is_terminal(s) for s in TERMINAL_STATES)
    assert not any(is_terminal(s) for s in ("created", "working", "input-required"))


def _write(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_read_tasks_reads_the_sample(sample, tmp_path):
    tasks = read_tasks(_write(tmp_path, sample))
    assert [t.id for t in tasks] == [MEASURED_ID]
    assert tasks[0].state == "created", "the variant is translated on read"
    assert tasks[0].to_agent == "probe-builder"
    assert tasks[0].from_agent == CREATOR


def test_a_missing_file_is_not_an_error(tmp_path):
    """Before the first task the store simply does not exist."""
    assert read_tasks(tmp_path / "does-not-exist.json") == []


def test_a_broken_file_is_an_error(tmp_path):
    """A destroyed store must never look like 'nothing to do'."""
    path = tmp_path / "tasks.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(TaskError, match="malformed"):
        read_tasks(path)


def test_a_missing_tasks_key_is_an_error(tmp_path):
    with pytest.raises(TaskError, match="tasks"):
        read_tasks(_write(tmp_path, {"aufgaben": []}))


def test_find_task_looks_up_by_id(sample, tmp_path):
    tasks = read_tasks(_write(tmp_path, sample))
    assert find_task(tasks, MEASURED_ID) is not None
    assert find_task(tasks, "task-does-not-exist") is None


def _task(**rest) -> Task:
    base = {
        "id": "task-1", "from_agent": "orch", "to_agent": "w1",
        "state": "Working", "description": "build foo", "messages": [],
        "created_at": "", "updated_at": "",
    }
    return Task.from_raw({**base, **rest})


def _message(role: str, text: str) -> dict:
    return {"role": role, "parts": [{"type": "text", "text": text}]}


def test_message_from_takes_the_newest_of_that_sender():
    task = _task(messages=[
        _message("orch", "build foo"),
        _message("w1", "started"),
        _message("w1", "done, three tests green"),
    ])
    assert message_from(task, "w1") == "done, three tests green"


def test_message_from_never_returns_our_own_order():
    """A wordless completion is None, not the description."""
    task = _task(messages=[_message("orch", "build foo")])
    assert message_from(task, "w1") is None


def test_message_from_reads_only_text_parts():
    task = _task(messages=[
        {"role": "w1", "parts": [{"type": "data", "mime_type": "x", "data": "y"}]},
        _message("w1", "the text is what counts"),
    ])
    assert message_from(task, "w1") == "the text is what counts"


def test_task_is_immutable():
    task = _task()
    with pytest.raises(FrozenInstanceError):
        task.id = "other"  # type: ignore[misc]  # ty: ignore[invalid-assignment]


def test_store_path_follows_LEAN_CTX_DATA_DIR(tmp_path, monkeypatch):
    """This is what gives the integration tests a fully isolated store."""
    monkeypatch.setenv("LEAN_CTX_DATA_DIR", str(tmp_path))
    assert task_store_path() == tmp_path / "agents" / "tasks.json"


def test_store_path_falls_back_to_xdg(tmp_path, monkeypatch):
    monkeypatch.delenv("LEAN_CTX_DATA_DIR", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    assert task_store_path() == (
        tmp_path / "data" / "lean-ctx" / "agents" / "tasks.json"
    )


def test_a_legacy_install_with_data_wins_over_xdg(tmp_path, monkeypatch):
    """core/data_dir.rs:14 -- a legacy install is never silently relocated."""
    monkeypatch.delenv("LEAN_CTX_DATA_DIR", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    (tmp_path / ".lean-ctx").mkdir()
    (tmp_path / ".lean-ctx" / "stats.json").write_text("{}", encoding="utf-8")
    assert task_store_path() == tmp_path / ".lean-ctx" / "agents" / "tasks.json"


def test_an_empty_legacy_directory_does_not_count(tmp_path, monkeypatch):
    """Otherwise an empty ~/.lean-ctx left by setup would split the store."""
    monkeypatch.delenv("LEAN_CTX_DATA_DIR", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    (tmp_path / ".lean-ctx").mkdir()
    assert task_store_path() == (
        tmp_path / "data" / "lean-ctx" / "agents" / "tasks.json"
    )
