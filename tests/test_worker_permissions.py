"""The worker's order path is a CLI now, so it needs a shell permission.

Before this design the role prompts under .lean-ctx/lean-herdr/roles/ carried no shell
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

#: The builder's own gate. .lean-ctx/lean-herdr/roles/builder.md prescribes TDD and commits via
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
    return (
        "lean-herdr report next"
        if command == "next"
        else f"lean-herdr report {command} *"
    )


def claude_key(command: str) -> str:
    return (
        "Bash(lean-herdr report next)"
        if command == "next"
        else f"Bash(lean-herdr report {command}:*)"
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
    """One binary means the gate is the ONLY separation left.

    Before this, `herdr-dispatch` and `herdr-report` were two programs,
    and the builder's allowlist separated them by simply never naming the
    first. Now a sloppy `lean-herdr *` hands the builder the orchestrator's
    own verb -- `order`, `answer`, `cancel` and `remember` included.
    """
    for role in WORKERS:
        allowed = opencode()["agent"][role]["permission"]["bash"]
        for wildcard in ("lean-herdr *", "lean-herdr*", "lean-herdr report *"):
            assert wildcard not in allowed, f"{role}: {wildcard} is too wide"
    for entry in claude_allow():
        assert entry not in ("Bash(lean-herdr:*)", "Bash(lean-herdr)"), entry


def test_no_worker_gate_ever_names_the_dispatch_verb():
    """The verb that belongs to the orchestrator, and to nobody else.

    `dispatch order` writes work orders and `dispatch answer` closes an
    input-required round trip. A worker holding either could hand itself
    an order under the sender the other workers trust.
    """
    for role in WORKERS:
        allowed = opencode()["agent"][role]["permission"]["bash"]
        offenders = [key for key in allowed if "dispatch" in key]
        assert not offenders, f"{role} may run the dispatch verb: {offenders}"
    offenders = [key for key in claude_allow() if "dispatch" in key]
    assert not offenders, f".claude/settings.json: {offenders}"


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
            key.removeprefix("lean-herdr report ").removesuffix(" *")
            for key in opencode()["agent"][role]["permission"]["bash"]
            if key.startswith("lean-herdr report")
        }
        assert named == expected, f"{role}: {sorted(named ^ expected)}"
    named = {
        key.removeprefix("Bash(lean-herdr report ").removesuffix(":*)").removesuffix(")")
        for key in claude_allow()
        if key.startswith("Bash(lean-herdr report")
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


#: The Claude harness spells the same grant differently, so the two files
#: cannot share one list. These three are the ones `.lean-ctx/lean-herdr/roles/builder.md` makes
#: mandatory: stage, test, commit. `wt step commit --stage none` commits the
#: INDEX, so without `git add` the commit is empty and the role text cannot
#: be followed at all -- and an agent told to do TDD has to run a test.
#:
#: The two harnesses are deliberately NOT at parity: opencode also grants the
#: builder `uv run ruff*`, `git commit*`, `git diff*` and `git status*`, which
#: the Claude side does not (operator decision, 2026-09-03). Nothing in
#: `.lean-ctx/lean-herdr/roles/builder.md` makes those mandatory -- `wt step commit` replaces
#: `git commit`, and the rest are conveniences -- so the narrower gate stands.
CLAUDE_BUILDER_TOOLING = (
    "Bash(git add:*)",
    "Bash(uv run pytest:*)",
    "Bash(wt step commit:*)",
)


def test_the_claude_builder_may_do_what_its_role_text_prescribes():
    """Half a pair is worse than none: it fails one step later, silently.

    The branch that made `git add` load-bearing granted only the commit
    itself here, so a Claude builder reached its first `git add` and
    stopped at a permission prompt no one is sitting at -- which the
    orchestrator sees as `no_reply`, with nothing naming the cause.
    """
    allow = claude_allow()
    for pattern in CLAUDE_BUILDER_TOOLING:
        assert pattern in allow, f"the Claude builder cannot run `{pattern}`"


def test_the_claude_builders_gate_is_not_a_blank_cheque():
    """The other half of the operator's decision, pinned on this side too."""
    allow = claude_allow()
    for forbidden in ("Bash(git:*)", "Bash(git push:*)", "Bash(uv:*)",
                      "Bash(uv run:*)", "Bash(rm:*)", "Bash(curl:*)"):
        assert forbidden not in allow, f"{forbidden} widens the builder's gate"


def test_no_permission_file_hands_out_worktrunk_wholesale():
    """`wt *` on a worker is the whole tool, merge and push included."""
    for entry in claude_allow():
        assert entry not in ("Bash(wt:*)", "Bash(wt step:*)"), entry


def test_the_reviewer_still_may_not_write():
    permission = opencode()["agent"]["reviewer"]["permission"]
    assert permission["edit"] == "deny"
    assert permission["write"] == "deny"
