"""The worker's order path is a CLI now, so it needs a shell permission.

Before this design roles/builder.md and roles/reviewer.md carried no shell
line at all: everything ran through ctx_task, an MCP tool. reviewer even
carries `"*": "deny"`. Without one pattern per subcommand the worker
cannot fetch its order, and the failure looks exactly like a crash -- the
orchestrator sees nothing and runs into `no_reply`.

The subcommand list is not repeated here: it is imported from the CLI that
owns it, so a seventh subcommand cannot ship without a permission beside
it. The builder's own gate -- the tests it is told to write and the commits
it is told to make -- is pinned right below it.
"""

import json
from pathlib import Path

import pytest

from lean_herdr.report import SUBCOMMANDS
from tests.test_config_files import load_jsonc

ROOT = Path(__file__).resolve().parents[1]
WORKERS = ("builder", "reviewer")

#: The builder's own gate. roles/builder.md prescribes TDD and commits via
#: `wt step commit --stage none`, and `bash: {"*": "deny"}` plus the report
#: patterns let it do neither -- an opencode builder would fail on its first
#: `uv run pytest` and again on its first commit. Exactly this list, nothing
#: wider: `wt step commit *`, not `wt *`, and not `wt step *`.
BUILDER_TOOLING = (
    "uv run pytest*",
    "uv run ruff*",
    "git add*",
    "git commit*",
    "git diff*",
    "git status*",
    "wt step commit *",
)


def opencode_key(command: str) -> str:
    """One pattern per subcommand -- a wildcard behind the program name
    would let through anything at all. `next` is the only one that takes no
    flags, so it is the only one without a trailing ` *`.
    """
    return "bin/herdr-report next" if command == "next" else f"bin/herdr-report {command} *"


def claude_key(command: str) -> str:
    return (
        "Bash(bin/herdr-report next)"
        if command == "next"
        else f"Bash(bin/herdr-report {command}:*)"
    )


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
        assert allowed.get(opencode_key(command)) == "allow", (
            f"{role} cannot run `{command}`"
        )


def test_the_permission_is_never_a_bare_wildcard():
    for role in WORKERS:
        allowed = opencode()["agent"][role]["permission"]["bash"]
        assert "bin/herdr-report *" not in allowed
        assert "bin/herdr-report*" not in allowed


def test_the_repo_ships_the_claude_permissions_too():
    """Without this file a fresh checkout on another machine is silent."""
    allow = claude_allow()
    for command in SUBCOMMANDS:
        assert claude_key(command) in allow, f"Claude Code cannot run `{command}`"


def claude_allow() -> list[str]:
    return json.loads(
        (ROOT / ".claude" / "settings.json").read_text(encoding="utf-8")
    )["permissions"]["allow"]


def test_no_permission_file_names_a_subcommand_the_cli_does_not_have():
    """The other direction, so the two lists cannot drift APART either.

    `report.SUBCOMMANDS` is the one truth now; before it the six words stood
    in four unbound copies and a seventh subcommand shipped green with no
    permission anywhere. This catches the reverse: an allow left standing
    for a subcommand that was renamed or removed.
    """
    expected = set(SUBCOMMANDS)
    for role in WORKERS:
        named = {
            key.removeprefix("bin/herdr-report ").removesuffix(" *")
            for key in opencode()["agent"][role]["permission"]["bash"]
            if key.startswith("bin/herdr-report")
        }
        assert named == expected, f"{role}: {sorted(named ^ expected)}"
    named = {
        key.removeprefix("Bash(bin/herdr-report ").removesuffix(":*)").removesuffix(")")
        for key in claude_allow()
        if key.startswith("Bash(bin/herdr-report")
    }
    assert named == expected, f".claude/settings.json: {sorted(named ^ expected)}"


def test_the_builder_may_run_the_gate_its_role_text_demands():
    """An agent told to do TDD has to be able to run a test.

    The opencode `builder` block shipped as `bash: {"*": "deny"}` plus the
    six report patterns -- so `uv run pytest` and `git commit` were both
    denied, and the role text prescribing them could not be followed at all.
    """
    allowed = opencode()["agent"]["builder"]["permission"]["bash"]
    assert allowed["*"] == "deny", "the fallback must stay deny"
    for pattern in BUILDER_TOOLING:
        assert allowed.get(pattern) == "allow", f"the builder cannot run `{pattern}`"


def test_the_builders_gate_is_not_a_blank_cheque():
    """`nothing more` is half the operator's decision -- pin that half too."""
    allowed = opencode()["agent"]["builder"]["permission"]["bash"]
    for forbidden in ("git push*", "git *", "uv *", "uv run *", "rm*", "curl*",
                      "wt *", "wt step *"):
        assert forbidden not in allowed, f"{forbidden} widens the builder's gate"


def test_the_claude_builder_may_commit_through_worktrunk():
    """The same gate as the opencode builder, on the other harness.

    Without this line a Claude Code builder is stopped at its first
    commit by a permission prompt no one is sitting at.
    """
    assert "Bash(wt step commit:*)" in claude_allow()


def test_no_permission_file_hands_out_worktrunk_wholesale():
    """`wt *` on a worker is the whole tool, merge and push included."""
    for entry in claude_allow():
        assert entry not in ("Bash(wt:*)", "Bash(wt step:*)"), entry


def test_the_reviewer_still_may_not_write():
    permission = opencode()["agent"]["reviewer"]["permission"]
    assert permission["edit"] == "deny"
    assert permission["write"] == "deny"
