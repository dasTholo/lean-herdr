import tomllib
from pathlib import Path

from lean_herdr.settings import load_jsonc

ROOT = Path(__file__).resolve().parents[1]


def opencode() -> dict:
    """This repo's own opencode.jsonc, or a named failure.

    `load_jsonc` is total on purpose -- production must not raise over a
    file a project never got. A test wants the opposite: this file IS
    there, and a broken one has to say so here rather than surface three
    lines down as a KeyError on `{}`.
    """
    cfg = load_jsonc(ROOT / "opencode.jsonc")
    assert cfg.found, f"no opencode.jsonc at {ROOT}"
    assert not cfg.error, cfg.error
    return cfg.data


def test_opencode_jsonc_is_valid_and_lives_in_the_repo():
    assert set(opencode()) >= {"mcp", "agent"}


def test_lean_ctx_is_registered_as_a_stdio_server():
    server = opencode()["mcp"]["lean-ctx"]
    assert server["type"] == "local"
    assert server["command"] == ["lean-ctx"], "serve is the HTTP server, not stdio"
    assert server["enabled"] is True


def test_both_opencode_agents_have_role_text_a_cap_and_a_guard():
    cfg = opencode()
    for name in ("orchestrator", "reviewer"):
        agent = cfg["agent"][name]
        assert agent["prompt"] == f"{{file:./.lean-ctx/lean-herdr/roles/{name}.md}}"
        assert isinstance(agent["steps"], int) and agent["steps"] > 0
        perm = agent["permission"]
        assert perm["edit"] == "deny" and perm["write"] == "deny"
        assert perm["bash"]["*"] == "deny", "Guard applies only here (B4)"


def test_orchestrator_may_dispatch_wt_and_three_herdr_subcommands():
    bash = opencode()["agent"]["orchestrator"]["permission"]["bash"]
    assert bash["lean-herdr dispatch *"] == "allow"
    assert bash["wt *"] == "allow"
    assert "herdr *" not in bash, "E3: no herdr agent, no herdr pane"
    for pattern in (
        "herdr worktree list *",
        "herdr workspace close *",
        "herdr workspace report-metadata *",
    ):
        assert bash[pattern] == "allow", pattern


def test_reviewer_may_write_nothing_and_no_wt():
    bash = opencode()["agent"]["reviewer"]["permission"]["bash"]
    assert "wt *" not in bash, "the reviewer does not merge"
    assert set(bash) >= {"*", "git diff*", "git log*"}


def test_wt_toml_has_the_pre_merge_gate_with_test_and_lint():
    cfg = tomllib.loads((ROOT / ".config" / "wt.toml").read_text(encoding="utf-8"))
    assert cfg["pre-merge"]["test"].startswith("uv run pytest")
    assert cfg["pre-merge"]["lint"].startswith("uv run ruff check")
    assert "list" not in cfg, "wt ignores list.json-schema in a project config"


def test_install_names_every_runtime_dependency():
    text = (ROOT / "INSTALL.md").read_text(encoding="utf-8")
    for requirement in (
        "uv",
        "python3",
        "worktrunk",
        "herdr-worktrunk",
        "fzf",
        "jq",
        "lean-ctx allow herdr",
        "lean-ctx allow wt",
        # The path form was never able to match: the gate normalises to the
        # basename and every allowlist entry is a bare name (measured on
        # lean-ctx 3.10.1). INSTALL.md names the spelling that CAN match.
        "lean-ctx allow lean-herdr",
        "wt config approvals",
        "warning:",
        # One snapshot for every project: the generator worktrunk runs, the one
        # command that says whether it all fits, and the gesture that updates it.
        "lean-herdr llm generate",
        "lean-herdr workspace check",
        "--reinstall",
        # The hooks this repository gates its own commits and pushes with.
        "pre-commit install",
        # Plan runs: lean-md reads the plan's structure, ty serves Python workers.
        "`lean-md` >= 0.2.4",
        "uv tool install ty",
        "seven verbs",
    ):
        assert requirement in text, f"INSTALL.md does not name {requirement!r}"


def test_readme_names_the_work_order_path():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for requirement in (
        # Both halves of it. `ctx_task` used to stand here; it is gone from the
        # project, so requiring it would pin the README to a tool that no
        # longer exists.
        "lean-herdr dispatch order",
        "lean-herdr report",
        "ORCHESTRATOR = orch",
        "lean-herdr plan next <slug>",
        "lean-herdr plan brief --task o-…",
        "--plan <slug> --step",
    ):
        assert requirement in text, f"README does not name {requirement!r}"


def test_readme_leaves_the_installation_to_install_md():
    """README.md is for using lean-herdr; what a machine needs lives in INSTALL.md."""
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "INSTALL.md" in text
    for install_only in ("## Runtime dependencies", "uv tool install", "lean-ctx allow"):
        assert install_only not in text, f"README still carries {install_only!r}"


def test_no_operator_doc_names_the_old_generator_script():
    """`bin/herdr-llm` is gone; a line naming it sends the operator nowhere."""
    for doc in ("README.md", "INSTALL.md"):
        assert "bin/herdr-llm" not in (ROOT / doc).read_text(encoding="utf-8"), doc
