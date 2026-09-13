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


def test_orchestrator_may_dispatch_wt_and_herdr():
    bash = opencode()["agent"]["orchestrator"]["permission"]["bash"]
    assert bash["lean-herdr dispatch *"] == "allow"
    assert bash["wt *"] == "allow"
    assert bash["herdr *"] == "allow"


def test_reviewer_may_write_nothing_and_no_wt():
    bash = opencode()["agent"]["reviewer"]["permission"]["bash"]
    assert "wt *" not in bash, "the reviewer does not merge"
    assert set(bash) >= {"*", "git diff*", "git log*"}


def test_wt_toml_has_the_pre_merge_gate_with_test_and_lint():
    cfg = tomllib.loads((ROOT / ".config" / "wt.toml").read_text(encoding="utf-8"))
    assert cfg["pre-merge"]["test"].startswith("uv run pytest")
    assert cfg["pre-merge"]["lint"].startswith("uv run ruff check")
    assert "list" not in cfg, "wt ignores list.json-schema in a project config"


def test_readme_names_every_runtime_dependency():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
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
        # lean-ctx 3.10.1). The README names the spelling that CAN match.
        "lean-ctx allow lean-herdr",
        "wt config approvals",
        "warning:",
        # The work-order path, both halves of it. `ctx_task` used to stand
        # here; it is gone from the project, so requiring it would pin the
        # README to a tool that no longer exists.
        "lean-herdr dispatch order",
        "lean-herdr report",
        "ORCHESTRATOR = orch",
    ):
        assert requirement in text, f"README does not name {requirement!r}"
