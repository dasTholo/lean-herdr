import json
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lean_herdr.bus import (
    BusError,
    BusMessage,
    agents_in_registry,
    parse_registry,
    parse_time,
    read_registry,
)

FIXTURE = Path(__file__).parent / "fixtures" / "registry.sample.json"
PROJECT = "/home/tholo/Scripts/lean-herdr"
#: Fixed, not `now()`: the sample is frozen, the clock must not have a say.
NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def sample() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_the_frozen_sample_has_the_expected_shape(sample):
    """Breaks visibly if lean-ctx changes its internal format."""
    assert "scratchpad" in sample, sorted(sample)
    assert "agents" in sample
    first = sample["scratchpad"][0]
    for field in (
        "id", "from_agent", "to_agent", "task_id", "category", "priority",
        "privacy", "message", "metadata", "project_root", "timestamp",
        "read_by", "expires_at",
    ):
        assert field in first, f"field {field} is missing from the sample"
    assert "pid" in sample["agents"][0], "PID join needs the pid field"


def test_parse_registry_keeps_messages_without_a_project(sample):
    msgs = parse_registry(sample, project_root=PROJECT, now=NOW)
    assert msgs, "messages without a project (project_root=null) must not be dropped"
    assert all(m.project_root in (None, PROJECT) for m in msgs)
    assert "m-fremdes-projekt" not in [m.id for m in msgs]


def test_nine_fractional_digits_are_readable():
    """fromisoformat tolerates at most six — lean-ctx writes nine."""
    value = parse_time("2026-08-01T15:10:08.404790674Z")
    assert value is not None and value.tzinfo is not None
    assert value.year == 2026 and value.microsecond == 404790
    assert parse_time(None) is None and parse_time("morgen frueh") is None


def test_expired_messages_are_dropped(sample):
    """A dead reply from yesterday must not pass as a result."""
    ids = [m.id for m in parse_registry(sample, project_root=PROJECT, now=NOW)]
    assert "m-abgelaufen" not in ids
    assert "m-mit-projekt" in ids, "expires_at in the future stays valid"
    assert "m-ohne-projekt" in ids, "without expires_at it stays valid indefinitely"


def test_before_expiry_the_message_is_still_there(sample):
    earlier = datetime(2026, 9, 1, 5, 0, tzinfo=UTC)
    ids = [m.id for m in parse_registry(sample, project_root=PROJECT, now=earlier)]
    assert "m-abgelaufen" in ids


def test_parse_registry_rejects_a_foreign_root():
    data = {
        "scratchpad": [
            {"id": "a", "from_agent": "x", "project_root": "/foreign", "message": "no"},
            {"id": "b", "from_agent": "x", "project_root": None, "message": "yes"},
        ]
    }
    msgs = parse_registry(data, project_root="/home/tholo/Scripts/lean-herdr")
    assert [m.id for m in msgs] == ["b"]


def test_parse_registry_filters_by_task_id_and_sender():
    data = {
        "scratchpad": [
            {"id": "a", "from_agent": "w1", "task_id": "T1", "message": "hit"},
            {"id": "b", "from_agent": "w2", "task_id": "T1", "message": "wrong sender"},
            {"id": "c", "from_agent": "w1", "task_id": "T2", "message": "wrong task"},
        ]
    }
    msgs = parse_registry(data, project_root="/p", task_id="T1", from_agent="w1")
    assert [m.id for m in msgs] == ["a"]


def test_parse_registry_raises_on_missing_key():
    with pytest.raises(BusError, match="scratchpad"):
        parse_registry({"messages": []}, project_root="/p")


def test_read_registry_reports_a_missing_file(tmp_path: Path):
    with pytest.raises(BusError, match="unreadable"):
        read_registry(tmp_path / "does-not-exist.json")


def test_agents_in_registry_returns_pid_carriers(sample):
    agents = agents_in_registry(sample)
    assert agents and all(isinstance(a.get("pid"), int) for a in agents)


def test_busmessage_is_immutable():
    m = BusMessage.from_raw({"id": "a", "from_agent": "x"})
    with pytest.raises(FrozenInstanceError):
        m.id = "b"  # type: ignore[misc]  # ty: ignore[invalid-assignment]
