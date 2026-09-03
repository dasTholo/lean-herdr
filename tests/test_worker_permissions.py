"""The worker's order path is a CLI now, so it needs a shell permission.

Before this design roles/builder.md and roles/reviewer.md carried no shell
line at all: everything ran through ctx_task, an MCP tool. reviewer even
carries `"*": "deny"`. Without the six patterns below the worker cannot
fetch its order, and the failure looks exactly like a crash -- the
orchestrator sees nothing and runs into `no_reply`.
"""

import json
from pathlib import Path

import pytest

from tests.test_config_files import load_jsonc

ROOT = Path(__file__).resolve().parents[1]
WORKERS = ("builder", "reviewer")

#: One pattern per subcommand. A wildcard behind the program name would let
#: through anything at all.
SUBCOMMANDS = ("next", "show", "start", "done", "fail", "ask")


def opencode() -> dict:
    """opencode.jsonc, parsed by the stripper tests/test_config_files.py owns.

    Not a second one: that stripper already handles `//` inside string
    literals, and two of them would drift.
    """
    return load_jsonc(ROOT / "opencode.jsonc")


@pytest.mark.parametrize("role", WORKERS)
def test_every_worker_is_configured_at_all(role):
    assert role in opencode()["agent"], f"{role} has no opencode agent block"


@pytest.mark.parametrize("role", WORKERS)
def test_every_worker_may_run_every_report_subcommand(role):
    allowed = opencode()["agent"][role]["permission"]["bash"]
    assert allowed["*"] == "deny", "the default must stay deny"
    for command in SUBCOMMANDS:
        key = "bin/herdr-report next" if command == "next" else f"bin/herdr-report {command} *"
        assert allowed.get(key) == "allow", f"{role} cannot run `{command}`"


def test_the_permission_is_never_a_bare_wildcard():
    for role in WORKERS:
        assert "bin/herdr-report *" not in opencode()["agent"][role]["permission"]["bash"]


def test_the_repo_ships_the_claude_permissions_too():
    """Without this file a fresh checkout on another machine is silent."""
    allow = json.loads(
        (ROOT / ".claude" / "settings.json").read_text(encoding="utf-8")
    )["permissions"]["allow"]
    assert "Bash(bin/herdr-report next)" in allow
    for command in SUBCOMMANDS[1:]:
        assert f"Bash(bin/herdr-report {command}:*)" in allow


def test_the_reviewer_still_may_not_write():
    permission = opencode()["agent"]["reviewer"]["permission"]
    assert permission["edit"] == "deny"
    assert permission["write"] == "deny"
