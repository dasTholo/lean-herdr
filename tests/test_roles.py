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
    """Without the BOUNDARY section the defence against prompt injection is gone."""
    text = (ROLES / f"{name}.md").read_text(encoding="utf-8")
    assert "## BOUNDARY" in text
    assert "data, not authority" in text


@pytest.mark.parametrize("name", ALLE)
def test_jede_rolle_verbietet_polling(name):
    text = (ROLES / f"{name}.md").read_text(encoding="utf-8")
    assert "then stop" in text.lower() or "stop and report" in text.lower()
    assert "model step" in text


#: Either the unfilled placeholder or a real lean-ctx agent_id.
ORCHESTRATOR_ZEILE = re.compile(
    r"^\s*ORCHESTRATOR = (<ORCHESTRATOR_AGENT_ID>|mcp-\d+-[0-9a-f]+)\s*$", re.MULTILINE
)


@pytest.mark.parametrize("name", ARBEITER)
def test_arbeiter_kennen_die_orchestrator_id_stelle(name):
    """Trust is set at bootstrap, never claimed by the message.

    The test must bear both states: the file in the repo carries the
    placeholder, the same file after the bootstrap the inserted id. A test on
    the placeholder alone would turn red exactly when the role is set up
    correctly.
    """
    text = (ROLES / f"{name}.md").read_text(encoding="utf-8")
    assert ORCHESTRATOR_ZEILE.search(text), "ORCHESTRATOR line missing or empty"


@pytest.mark.parametrize("name", ARBEITER)
def test_workers_work_through_ctx_task(name):
    text = (ROLES / f"{name}.md").read_text(encoding="utf-8")
    assert "ctx_task" in text and "task_id" in text
    assert "to_agent" not in text, "the worker does not address, it answers in place"


def test_reviewer_antwortet_maschinenlesbar():
    text = (ROLES / "reviewer.md").read_text(encoding="utf-8")
    assert "VERDIKT: result" in text and "VERDIKT: reject" in text
    assert "not in your" in text and "prose" in text


def test_orchestrator_kennt_die_wt_merge_falle():
    text = (ROLES / "orchestrator.md").read_text(encoding="utf-8")
    assert "wt -C" in text
    assert "with the source branch as its argument" in text
    assert "esc=" in text, "escalation runs through the workspace token esc"
    assert "You never touch the `ctx` token" in text


def test_orchestrator_liest_ok_nicht_den_exitcode():
    text = (ROLES / "orchestrator.md").read_text(encoding="utf-8")
    assert "never the exit code" in text
