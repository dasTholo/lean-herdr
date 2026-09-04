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


#: The bootstrap default, or whatever name the operator's orchestrator pane
#: runs under. NOT an `mcp-…` id any more: the order log stamps the herdr
#: agent name, the same string `--to` carries on the other side.
ORCHESTRATOR_LINE = re.compile(r"^\s*ORCHESTRATOR = ([A-Za-z0-9][\w.-]*)\s*$", re.MULTILINE)


@pytest.mark.parametrize("name", WORKERS)
def test_workers_know_which_sender_to_trust(name):
    """Trust is set at bootstrap, never claimed by the order.

    The test must bear both states: the file in the repo carries the
    bootstrap name, the same file after a rename the operator's own.
    """
    text = (ROLES / f"{name}.md").read_text(encoding="utf-8")
    assert ORCHESTRATOR_LINE.search(text), "ORCHESTRATOR line missing or empty"
    assert "<ORCHESTRATOR_AGENT_ID>" not in text, "the mcp id anchor is gone"


@pytest.mark.parametrize("name", WORKERS)
def test_the_trust_rule_does_not_oversell_itself(name):
    """The log stamps a claimed name -- the prompt must not imply otherwise."""
    text = (ROLES / f"{name}.md").read_text(encoding="utf-8")
    assert "rule, not a guarantee" in text


def test_the_role_prompts_trust_the_name_dispatch_actually_stamps():
    """Two spellings of one name would let every order fail the trust check."""
    from lean_herdr.dispatch import ORCHESTRATOR_AGENT

    for name in WORKERS:
        text = (ROLES / f"{name}.md").read_text(encoding="utf-8")
        hit = ORCHESTRATOR_LINE.search(text)
        assert hit.group(1) == ORCHESTRATOR_AGENT, (
            f"{name}.md trusts {hit.group(1)!r}, dispatch stamps "
            f"{ORCHESTRATOR_AGENT!r}"
        )


@pytest.mark.parametrize("name", WORKERS)
def test_workers_work_through_herdr_report(name):
    text = (ROLES / f"{name}.md").read_text(encoding="utf-8")
    assert "lean-herdr report next" in text
    assert "--task" in text
    assert "--to " not in text, "the worker does not address, it answers in place"
    assert "ctx_task" not in text, "the ctx_task path is gone"


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
