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
from lean_herdr.settings import load_jsonc
from lean_herdr.templating import LAYOUT, read_lock, render, resolve_values

ROOT = Path(__file__).resolve().parents[1]
WORKERS = ("builder", "reviewer", "plan-writer", "plan-reviewer")

#: lean-ctx's own write tools, under the names opencode gives an MCP tool --
#: measured against opencode 1.18.29 (plan 2026-09-14, task 1). `edit` and
#: `write` deny opencode's built-in tools only; these three pass both.
LEAN_CTX_WRITERS = ("lean-ctx_ctx_patch", "lean-ctx_ctx_edit", "lean-ctx_ctx_refactor")

#: The opencode agents that change no file.
NON_WRITING = ("orchestrator", "reviewer", "plan-reviewer")

#: The claude roles that ship a settings file `dispatch` hands over as `--settings`.
CLAUDE_ROLES = ("builder", "reviewer", "orchestrator", "plan-writer", "plan-reviewer")

#: The claude roles that change no file. Their `deny` outranks every `allow` from
#: every source, the shared `.claude/settings.json` included.
CLAUDE_NON_WRITING = ("reviewer", "plan-reviewer")

#: What writes, whatever `.claude/settings.json` says: Claude Code's own editors
#: and lean-ctx's three write tools.
CLAUDE_WRITERS = (
    "Edit",
    "Write",
    "NotebookEdit",
    "mcp__lean-ctx__ctx_patch",
    "mcp__lean-ctx__ctx_edit",
    "mcp__lean-ctx__ctx_refactor",
)

#: What stays a human gesture, whatever a role may otherwise run (plan spec 5.3).
PUSH_AND_MERGE = ("Bash(git push:*)", "Bash(wt merge:*)", "Bash(wt step push:*)")

#: What the orchestrator may run of herdr: find the worktree, close its workspace, set `esc=`.
ORCHESTRATOR_HERDR = (
    "herdr worktree list *",
    "herdr workspace close *",
    "herdr workspace report-metadata *",
)


def claude_rules(role: str, key: str, root: Path = ROOT) -> list[str]:
    """`permissions.<key>` of `.lean-ctx/lean-herdr/claude/<role>.json`; absent is empty."""
    data = json.loads((root / LAYOUT[f"claude/{role}.json"]).read_text(encoding="utf-8"))
    return data.get("permissions", {}).get(key, [])


#: Another project's gate. The permission files are rendered with these too, so
#: a render that shifted a line fails here even where this repo's copy passes.
FOREIGN = {"test": "cargo test", "lint": "cargo clippy"}

#: The builder's own gate. .lean-ctx/lean-herdr/roles/builder.md prescribes TDD and commits via
#: `wt step commit --stage none`, and `bash: {"*": "deny"}` plus the report
#: patterns let it do neither -- an opencode builder would fail on its first
#: `uv run pytest` and again on its first commit. Exactly this list, nothing
#: wider: `wt step commit *`, not `wt *`, and not `wt step *`.
BUILDER_TOOLING = (
    "uv run pytest*",
    "uv run ruff check*",
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
    return "lean-herdr report next" if command == "next" else f"lean-herdr report {command} *"


def claude_key(command: str) -> str:
    return (
        "Bash(lean-herdr report next)"
        if command == "next"
        else f"Bash(lean-herdr report {command}:*)"
    )


def opencode(root: Path = ROOT) -> dict:
    """opencode.jsonc, parsed by the stripper lean_herdr/settings.py owns.

    Not a second one: that stripper already handles `//` inside string
    literals, and two of them would drift. It is total, so the assertion
    is what turns a broken repo file into a sentence instead of a KeyError.
    """
    cfg = load_jsonc(root / "opencode.jsonc")
    assert cfg.found, f"no opencode.jsonc at {root}"
    assert not cfg.error, cfg.error
    return cfg.data


@pytest.fixture(scope="module")
def foreign_root(tmp_path_factory) -> Path:
    """opencode.jsonc and .claude/settings.json, rendered with FOREIGN."""
    root = tmp_path_factory.mktemp("foreign")
    for name in (
        "opencode.jsonc",
        "settings.json",
        "claude/builder.json",
        "claude/reviewer.json",
        "claude/orchestrator.json",
        "claude/plan-writer.json",
        "claude/plan-reviewer.json",
    ):
        target = root / LAYOUT[name]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(render(name, FOREIGN))
    return root


@pytest.fixture(params=["repo", "foreign"])
def gate_root(request, foreign_root) -> Path:
    return ROOT if request.param == "repo" else foreign_root


@pytest.mark.parametrize("role", WORKERS)
def test_every_worker_is_configured_at_all(role):
    assert role in opencode()["agent"], f"{role} has no opencode agent block"


@pytest.mark.parametrize("role", WORKERS)
def test_every_worker_may_run_every_report_subcommand(role):
    allowed = opencode()["agent"][role]["permission"]["bash"]
    assert allowed["*"] == "deny", "the default must stay deny"
    for command in SUBCOMMANDS:
        assert allowed.get(opencode_key(command)) == "allow", f"{role} cannot run `{command}`"


def test_the_permission_is_never_a_bare_wildcard(gate_root):
    """One binary means the gate is the ONLY separation left.

    Before this, `herdr-dispatch` and `herdr-report` were two programs,
    and the builder's allowlist separated them by simply never naming the
    first. Now a sloppy `lean-herdr *` hands the builder the orchestrator's
    own verb -- `order`, `answer`, `cancel` and `remember` included.
    """
    for role in WORKERS:
        allowed = opencode(gate_root)["agent"][role]["permission"]["bash"]
        for wildcard in ("lean-herdr *", "lean-herdr*", "lean-herdr report *"):
            assert wildcard not in allowed, f"{role}: {wildcard} is too wide"
    for entry in claude_allow(gate_root):
        assert entry not in ("Bash(lean-herdr:*)", "Bash(lean-herdr)"), entry


def test_no_worker_gate_ever_names_the_dispatch_verb(gate_root):
    """The verb that belongs to the orchestrator, and to nobody else.

    `dispatch order` writes work orders and `dispatch answer` closes an
    input-required round trip. A worker holding either could hand itself
    an order under the sender the other workers trust.
    """
    for role in WORKERS:
        allowed = opencode(gate_root)["agent"][role]["permission"]["bash"]
        offenders = [key for key in allowed if "dispatch" in key]
        assert not offenders, f"{role} may run the dispatch verb: {offenders}"
    offenders = [key for key in claude_allow(gate_root) if "dispatch" in key]
    assert not offenders, f".claude/settings.json: {offenders}"
    for role in CLAUDE_ROLES:
        offenders = [rule for rule in claude_rules(role, "allow", gate_root) if "dispatch" in rule]
        assert not offenders, f"claude/{role}.json: {offenders}"


def test_the_repo_ships_the_claude_permissions_too():
    """Without this file a fresh checkout on another machine is silent."""
    allow = claude_allow()
    for command in SUBCOMMANDS:
        assert claude_key(command) in allow, f"Claude Code cannot run `{command}`"


def claude_allow(root: Path = ROOT) -> list[str]:
    return json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8"))[
        "permissions"
    ]["allow"]


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


def test_the_builders_gate_is_not_a_blank_cheque(gate_root):
    """`nothing more` is half the operator's decision -- pin that half too."""
    allowed = opencode(gate_root)["agent"]["builder"]["permission"]["bash"]
    for forbidden in (
        "git push*",
        "git *",
        "uv *",
        "uv run *",
        "rm*",
        "curl*",
        "wt *",
        "wt step *",
    ):
        assert forbidden not in allowed, f"{forbidden} widens the builder's gate"


#: The gate's formatter and type check (plan C final review, F1): the builder
#: needs both to follow herdr-recipes' `gate()` and the Python pack's `ty check`.
GATE_FORMATTER_AND_TYPES = ("uv run ruff format*", "uv run ty check*")


def test_the_opencode_builder_may_run_the_formatter_and_ty_check():
    """The gate's first and third lines, both hard-coded by the Python pack.

    Without these the builder is stopped at `uv run ruff format` and
    `uv run ty check` exactly like it was at `uv run pytest` before F1.
    """
    allowed = opencode()["agent"]["builder"]["permission"]["bash"]
    for pattern in GATE_FORMATTER_AND_TYPES:
        assert allowed.get(pattern) == "allow", f"the builder cannot run `{pattern}`"


@pytest.mark.parametrize("role", ("reviewer", "plan-reviewer"))
def test_opencode_reviewer_roles_may_not_run_the_formatter_or_ty_check(role):
    """Neither judge writes, and `ruff format`/`ty check` are not theirs to run."""
    allowed = opencode()["agent"][role]["permission"]["bash"]
    for pattern in GATE_FORMATTER_AND_TYPES:
        assert pattern not in allowed, f"{role} may run `{pattern}`"


def test_the_claude_builder_may_commit_through_worktrunk():
    """The same gate as the opencode builder, on the other harness.

    Without this line a Claude Code builder is stopped at its first
    commit by a permission prompt no one is sitting at.
    """
    assert "Bash(wt step commit:*)" in claude_allow()


#: The Claude harness spells the same grant differently, so the two files
#: cannot share one list. `git add` and `wt step commit` are the ones
#: `.lean-ctx/lean-herdr/roles/builder.md` makes mandatory -- `wt step commit
#: --stage none` commits the INDEX, so without `git add` the commit is empty.
#: The test and the lint command are the pre-merge gate's own: the gate checks
#: lint since the operator decision of 2026-09-13, so every builder must be
#: able to run it first.
#:
#: The two harnesses are still NOT at parity: opencode also grants the builder
#: `git commit*`, `git diff*` and `git status*`, which the Claude side does not
#: (operator decision, 2026-09-03). Nothing in
#: `.lean-ctx/lean-herdr/roles/builder.md` makes those mandatory -- `wt step
#: commit` replaces `git commit`, and the rest are conveniences -- so the
#: narrower gate stands.
CLAUDE_BUILDER_TOOLING = (
    "Bash(git add:*)",
    "Bash(uv run pytest:*)",
    "Bash(uv run ruff check:*)",
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


def test_the_claude_builders_gate_is_not_a_blank_cheque(gate_root):
    """The other half of the operator's decision, pinned on this side too."""
    allow = claude_allow(gate_root)
    for forbidden in (
        "Bash(git:*)",
        "Bash(git push:*)",
        "Bash(uv:*)",
        "Bash(uv run:*)",
        "Bash(rm:*)",
        "Bash(curl:*)",
    ):
        assert forbidden not in allow, f"{forbidden} widens the builder's gate"


def test_claude_settings_allow_the_formatter_and_ty_check(gate_root):
    """`.claude/settings.json` grants every claude worker both, same as the builder's
    opencode block -- fixed literal commands, not the `{{lean-herdr:...}}` tokens,
    since `--lang python` pins the formatter and `ty check` reads only (F1)."""
    allow = claude_allow(gate_root)
    assert "Bash(uv run ruff format:*)" in allow
    assert "Bash(uv run ty check:*)" in allow


def test_no_permission_file_hands_out_worktrunk_wholesale(gate_root):
    """`wt *` on a worker is the whole tool, merge and push included."""
    for entry in claude_allow(gate_root):
        assert entry not in ("Bash(wt:*)", "Bash(wt step:*)"), entry


def test_the_reviewer_still_may_not_write():
    permission = opencode()["agent"]["reviewer"]["permission"]
    assert permission["edit"] == "deny"
    assert permission["write"] == "deny"


@pytest.mark.parametrize("role", NON_WRITING)
def test_a_role_that_writes_nothing_cannot_reach_lean_ctxs_write_tools(role, gate_root):
    """`edit: deny` stops opencode's own editor, not an MCP tool with a name of its own."""
    permission = opencode(gate_root)["agent"][role]["permission"]
    for tool in LEAN_CTX_WRITERS:
        assert permission.get(tool) == "deny", f"{role} may still call {tool}"


def test_the_builder_keeps_lean_ctxs_write_tools(gate_root):
    """The block is for the roles that write nothing -- the builder writes."""
    agent = opencode(gate_root)["agent"]["builder"]
    named = set(agent["permission"]) | set(agent.get("tools", {}))
    assert not named & set(LEAN_CTX_WRITERS), sorted(named & set(LEAN_CTX_WRITERS))


def test_every_worker_ships_a_claude_role_file():
    for role in WORKERS:
        assert f"claude/{role}.json" in LAYOUT, f"{role} has no claude settings template"


@pytest.mark.parametrize("role", CLAUDE_NON_WRITING)
def test_a_claude_role_that_writes_nothing_is_denied_every_writing_grant(role):
    """The shared allowlist hands every claude worker `git add` and `wt step commit`.

    The four `plan` commands and `wt step diff` only read, and stay as well.

    Everything in it but the report path, the test command, `ty check` and skills
    has to be taken back here, together with the editors and lean-ctx's tools. The
    lint command and the formatter write too now (`ruff check --fix`, `ruff format`),
    so they join the writing grants this role denies.
    """
    values = resolve_values(read_lock(ROOT)["values"])
    kept = {f"Bash({values['test']}:*)", "Bash(uv run ty check:*)"}
    shared = [
        rule
        for rule in claude_allow()
        if not rule.startswith("Bash(lean-herdr report")
        and rule not in kept
        and not rule.startswith("Skill")
        and not rule.startswith("Bash(lean-herdr plan ")
        and rule != "Bash(wt step diff:*)"
    ]
    deny = claude_rules(role, "deny")
    for rule in (*CLAUDE_WRITERS, *shared):
        assert rule in deny, f"claude/{role}.json does not deny {rule}"


@pytest.mark.parametrize("role", CLAUDE_ROLES)
def test_no_claude_role_takes_the_skill_tool_away(role):
    """Skills stay loadable for every claude role; which one a role loads is TP2's."""
    denied = claude_rules(role, "deny")
    offenders = [rule for rule in denied if rule == "Skill" or rule.startswith("Skill(")]
    assert not offenders, f"claude/{role}.json denies {offenders}"


def test_the_claude_orchestrator_writes_nothing(gate_root):
    """`claude/orchestrator.json`: the editors and lean-ctx's three write tools,
    denied -- unlike reviewer.json, Bash stays open but for `herdr agent` and `herdr pane`: the orchestrator's
    whole job is running `lean-herdr dispatch`/`report` through it.
    """
    denied = claude_rules("orchestrator", "deny", gate_root)
    for rule in CLAUDE_WRITERS:
        assert rule in denied, f"claude/orchestrator.json does not deny {rule}"


def test_the_claude_builder_blocks_push_and_merge_and_nothing_else(gate_root):
    assert claude_rules("builder", "deny", gate_root) == list(PUSH_AND_MERGE)


@pytest.mark.parametrize("role", WORKERS)
def test_no_claude_worker_may_push_or_merge(role):
    denied = claude_rules(role, "deny")
    for rule in PUSH_AND_MERGE:
        assert rule in denied, f"claude/{role}.json does not deny {rule}"


def test_the_plan_writer_may_write_commit_and_check_its_plan(gate_root):
    agent = opencode(gate_root)["agent"]["plan-writer"]
    assert "edit" not in agent["permission"] and "write" not in agent["permission"]
    bash = agent["permission"]["bash"]
    for pattern in (
        "lean-herdr plan brief *",
        "lean-herdr plan check *",
        "git add*",
        "wt step commit *",
    ):
        assert bash.get(pattern) == "allow", f"the plan writer cannot run `{pattern}`"
    assert "wt *" not in bash and "git push*" not in bash


def test_the_plan_reviewer_may_check_and_diff_but_not_commit(gate_root):
    bash = opencode(gate_root)["agent"]["plan-reviewer"]["permission"]["bash"]
    for pattern in ("lean-herdr plan brief *", "lean-herdr plan check *", "wt step diff *"):
        assert bash.get(pattern) == "allow", f"the plan reviewer cannot run `{pattern}`"
    for forbidden in ("git add*", "git commit*", "wt step commit *"):
        assert forbidden not in bash, forbidden


@pytest.mark.parametrize("role", WORKERS)
def test_every_worker_may_fetch_its_brief(role, gate_root):
    bash = opencode(gate_root)["agent"][role]["permission"]["bash"]
    assert bash.get("lean-herdr plan brief *") == "allow", f"{role} cannot run `plan brief`"


@pytest.mark.parametrize("role", ("builder", "reviewer", "plan-reviewer"))
def test_the_diff_is_open_to_whoever_writes_or_judges_a_task(role, gate_root):
    bash = opencode(gate_root)["agent"][role]["permission"]["bash"]
    assert bash.get("wt step diff") == "allow", f"{role} cannot run a bare `wt step diff`"
    assert bash.get("wt step diff *") == "allow", f"{role} cannot run `wt step diff <sha>`"


def test_the_orchestrator_steers_a_plan_and_fetches_no_brief(gate_root):
    bash = opencode(gate_root)["agent"]["orchestrator"]["permission"]["bash"]
    for pattern in ("lean-herdr plan next *", "lean-herdr plan show *", "lean-herdr plan check *"):
        assert bash.get(pattern) == "allow", f"the orchestrator cannot run `{pattern}`"
    assert "lean-herdr plan brief *" not in bash


def test_claude_may_run_the_four_plan_commands_and_the_diff(gate_root):
    allow = claude_allow(gate_root)
    for rule in (
        "Bash(wt step diff:*)",
        "Bash(lean-herdr plan brief:*)",
        "Bash(lean-herdr plan check:*)",
        "Bash(lean-herdr plan next:*)",
        "Bash(lean-herdr plan show:*)",
    ):
        assert rule in allow, f".claude/settings.json does not allow {rule}"


def test_the_opencode_orchestrator_runs_exactly_three_herdr_subcommands(gate_root):
    """E3: no `herdr agent`, no `herdr pane` -- a keystroke into a worker's pane is not its to send."""
    bash = opencode(gate_root)["agent"]["orchestrator"]["permission"]["bash"]
    assert sorted(key for key in bash if key.startswith("herdr")) == sorted(ORCHESTRATOR_HERDR)
    for pattern in ORCHESTRATOR_HERDR:
        assert bash[pattern] == "allow", pattern


def test_the_claude_orchestrator_is_denied_herdr_agent_and_pane(gate_root):
    denied = claude_rules("orchestrator", "deny", gate_root)
    for rule in ("Bash(herdr agent:*)", "Bash(herdr pane:*)"):
        assert rule in denied, f"claude/orchestrator.json does not deny {rule}"
