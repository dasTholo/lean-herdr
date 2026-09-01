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
    parse_zeit,
    read_registry,
)

FIXTURE = Path(__file__).parent / "fixtures" / "registry.sample.json"
PROJEKT = "/home/tholo/Scripts/lean-herdr"
#: Fest, nicht `now()`: die Probe ist eingefroren, die Uhr darf nicht mitreden.
JETZT = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def sample() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_eingefrorene_probe_hat_die_erwartete_form(sample):
    """Bricht sichtbar, wenn lean-ctx sein internes Format aendert."""
    assert "scratchpad" in sample, sorted(sample)
    assert "agents" in sample
    first = sample["scratchpad"][0]
    for feld in (
        "id", "from_agent", "to_agent", "task_id", "category", "priority",
        "privacy", "message", "metadata", "project_root", "timestamp",
        "read_by", "expires_at",
    ):
        assert feld in first, f"Feld {feld} fehlt in der Probe"
    assert "pid" in sample["agents"][0], "PID-Join braucht das pid-Feld"


def test_parse_registry_nimmt_projektlose_nachrichten_mit(sample):
    msgs = parse_registry(sample, project_root=PROJEKT, now=JETZT)
    assert msgs, "projektlose Nachrichten (project_root=null) duerfen nicht wegfallen"
    assert all(m.project_root in (None, PROJEKT) for m in msgs)
    assert "m-fremdes-projekt" not in [m.id for m in msgs]


def test_neun_nachkommastellen_sind_lesbar():
    """fromisoformat vertraegt hoechstens sechs — lean-ctx schreibt neun."""
    wert = parse_zeit("2026-08-01T15:10:08.404790674Z")
    assert wert is not None and wert.tzinfo is not None
    assert wert.year == 2026 and wert.microsecond == 404790
    assert parse_zeit(None) is None and parse_zeit("morgen frueh") is None


def test_abgelaufene_nachrichten_fallen_weg(sample):
    """Eine tote Antwort von gestern darf nicht als Ergebnis durchgehen."""
    ids = [m.id for m in parse_registry(sample, project_root=PROJEKT, now=JETZT)]
    assert "m-abgelaufen" not in ids
    assert "m-mit-projekt" in ids, "expires_at in der Zukunft bleibt gueltig"
    assert "m-ohne-projekt" in ids, "ohne expires_at gilt unbegrenzt"


def test_vor_dem_ablauf_ist_die_nachricht_noch_da(sample):
    frueher = datetime(2026, 9, 1, 5, 0, tzinfo=UTC)
    ids = [m.id for m in parse_registry(sample, project_root=PROJEKT, now=frueher)]
    assert "m-abgelaufen" in ids


def test_parse_registry_verwirft_fremden_root():
    data = {
        "scratchpad": [
            {"id": "a", "from_agent": "x", "project_root": "/fremd", "message": "nein"},
            {"id": "b", "from_agent": "x", "project_root": None, "message": "ja"},
        ]
    }
    msgs = parse_registry(data, project_root="/home/tholo/Scripts/lean-herdr")
    assert [m.id for m in msgs] == ["b"]


def test_parse_registry_filtert_auf_task_id_und_absender():
    data = {
        "scratchpad": [
            {"id": "a", "from_agent": "w1", "task_id": "T1", "message": "treffer"},
            {"id": "b", "from_agent": "w2", "task_id": "T1", "message": "falscher absender"},
            {"id": "c", "from_agent": "w1", "task_id": "T2", "message": "falsche aufgabe"},
        ]
    }
    msgs = parse_registry(data, project_root="/p", task_id="T1", from_agent="w1")
    assert [m.id for m in msgs] == ["a"]


def test_parse_registry_bricht_bei_fehlendem_schluessel():
    with pytest.raises(BusError, match="scratchpad"):
        parse_registry({"messages": []}, project_root="/p")


def test_read_registry_meldet_fehlende_datei(tmp_path: Path):
    with pytest.raises(BusError, match="unreadable"):
        read_registry(tmp_path / "gibt-es-nicht.json")


def test_agents_in_registry_liefert_pid_traeger(sample):
    agents = agents_in_registry(sample)
    assert agents and all(isinstance(a.get("pid"), int) for a in agents)


def test_busmessage_ist_unveraenderlich():
    m = BusMessage.from_raw({"id": "a", "from_agent": "x"})
    with pytest.raises(FrozenInstanceError):
        m.id = "b"  # type: ignore[misc]
