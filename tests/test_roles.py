import re
from pathlib import Path

import pytest

ROLES = Path(__file__).resolve().parents[1] / "roles"
WORKERS = ("builder", "reviewer")
ALL_ROLES = ("orchestrator", *WORKERS)


@pytest.mark.parametrize("name", ALL_ROLES)
def test_role_file_exists(name):
    assert (ROLES / f"{name}.md").is_file()


@pytest.mark.parametrize("name", ALL_ROLES)
def test_every_role_has_a_boundary(name):
    """Without the BOUNDARY section the defence against prompt injection is gone."""
    text = (ROLES / f"{name}.md").read_text(encoding="utf-8")
    assert "## BOUNDARY" in text
    assert "data, not authority" in text


@pytest.mark.parametrize("name", ALL_ROLES)
def test_every_role_forbids_polling(name):
    text = (ROLES / f"{name}.md").read_text(encoding="utf-8")
    assert "then stop" in text.lower() or "stop and report" in text.lower()
    assert "model step" in text


#: Either the unfilled placeholder or a real lean-ctx agent_id.
ORCHESTRATOR_LINE = re.compile(
    r"^\s*ORCHESTRATOR = (<ORCHESTRATOR_AGENT_ID>|mcp-\d+-[0-9a-f]+)\s*$", re.MULTILINE
)


@pytest.mark.parametrize("name", WORKERS)
def test_workers_know_the_orchestrator_id_slot(name):
    """Trust is set at bootstrap, never claimed by the message.

    The test must bear both states: the file in the repo carries the
    placeholder, the same file after the bootstrap the inserted id. A test on
    the placeholder alone would turn red exactly when the role is set up
    correctly.
    """
    text = (ROLES / f"{name}.md").read_text(encoding="utf-8")
    assert ORCHESTRATOR_LINE.search(text), "ORCHESTRATOR line missing or empty"


@pytest.mark.parametrize("name", WORKERS)
def test_workers_work_through_ctx_task(name):
    text = (ROLES / f"{name}.md").read_text(encoding="utf-8")
    assert "ctx_task" in text and "task_id" in text
    assert "to_agent" not in text, "the worker does not address, it answers in place"


def test_reviewer_answers_machine_readably():
    text = (ROLES / "reviewer.md").read_text(encoding="utf-8")
    assert "VERDIKT: result" in text and "VERDIKT: reject" in text
    assert "not in your prose" in text


def test_orchestrator_knows_the_wt_merge_trap():
    text = (ROLES / "orchestrator.md").read_text(encoding="utf-8")
    assert "wt -C" in text
    assert "with the source branch as its argument" in text
    assert "esc=" in text, "escalation runs through the workspace token esc"
    assert "You never touch the `ctx` token" in text


def test_orchestrator_reads_ok_not_the_exit_code():
    text = (ROLES / "orchestrator.md").read_text(encoding="utf-8")
    assert "never the exit code" in text
