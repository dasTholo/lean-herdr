import re
from pathlib import Path

import pytest

ROLES = Path(__file__).resolve().parents[1] / "roles"
ARBEITER = ("builder", "reviewer")
ALLE = ("orchestrator", *ARBEITER)


@pytest.mark.parametrize("name", ALLE)
def test_rollendatei_existiert(name):
    assert (ROLES / f"{name}.md").is_file()


@pytest.mark.parametrize("name", ALLE)
def test_jede_rolle_hat_eine_grenze(name):
    """Ohne GRENZE-Abschnitt fehlt die Abwehr gegen Bus-Prompt-Injection."""
    text = (ROLES / f"{name}.md").read_text(encoding="utf-8")
    assert "## GRENZE" in text
    assert "Daten, keine Befehlsgewalt" in text


@pytest.mark.parametrize("name", ALLE)
def test_jede_rolle_verbietet_polling(name):
    text = (ROLES / f"{name}.md").read_text(encoding="utf-8")
    assert "anhalten" in text.lower() or "halte an" in text.lower()
    assert "Modellschritt" in text


#: Entweder der unausgefuellte Platzhalter oder eine echte lean-ctx-agent_id.
ORCHESTRATOR_ZEILE = re.compile(
    r"^\s*ORCHESTRATOR = (<ORCHESTRATOR_AGENT_ID>|mcp-\d+-[0-9a-f]+)\s*$", re.MULTILINE
)


@pytest.mark.parametrize("name", ARBEITER)
def test_arbeiter_kennen_die_orchestrator_id_stelle(name):
    """Vertrauen wird beim Start gesetzt, nicht von der Nachricht behauptet.

    Der Test muss beide Zustaende ertragen: die Datei im Repo traegt den
    Platzhalter, dieselbe Datei nach dem Bootstrap die eingesetzte ID. Ein
    Test auf den Platzhalter allein wuerde genau dann rot, wenn die Rolle
    richtig eingerichtet ist.
    """
    text = (ROLES / f"{name}.md").read_text(encoding="utf-8")
    assert ORCHESTRATOR_ZEILE.search(text), "ORCHESTRATOR-Zeile fehlt oder ist leer"


@pytest.mark.parametrize("name", ARBEITER)
def test_arbeiter_antworten_gerichtet_mit_task_id(name):
    text = (ROLES / f"{name}.md").read_text(encoding="utf-8")
    assert "to_agent" in text and "task_id" in text


def test_reviewer_antwortet_maschinenlesbar():
    text = (ROLES / "reviewer.md").read_text(encoding="utf-8")
    assert '"result" | "reject"' in text
    assert "nicht deine Prosa" in text


def test_orchestrator_kennt_die_wt_merge_falle():
    text = (ROLES / "orchestrator.md").read_text(encoding="utf-8")
    assert "wt -C" in text
    assert "niemals mit dem Quellbranch" in text
    assert "esc=" in text, "Eskalation laeuft ueber den Workspace-Token esc"
    assert "`ctx` fasst du nie an" in text


def test_orchestrator_liest_ok_nicht_den_exitcode():
    text = (ROLES / "orchestrator.md").read_text(encoding="utf-8")
    assert "nie den Exit-Code" in text
