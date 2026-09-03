import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_jsonc(path: Path) -> dict:
    """Strip line comments without touching // inside string literals."""
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        without_strings = re.sub(r'"(?:[^"\\]|\\.)*"', '""', line)
        hit = without_strings.find("//")
        lines.append(line[:hit] if hit != -1 else line)
    return json.loads("\n".join(lines))


def test_opencode_jsonc_is_valid_and_lives_in_the_repo():
    cfg = load_jsonc(ROOT / "opencode.jsonc")
    assert set(cfg) >= {"mcp", "agent"}


def test_lean_ctx_is_registered_as_a_stdio_server():
    server = load_jsonc(ROOT / "opencode.jsonc")["mcp"]["lean-ctx"]
    assert server["type"] == "local"
    assert server["command"] == ["lean-ctx"], "serve is the HTTP server, not stdio"
    assert server["enabled"] is True


def test_both_opencode_agents_have_role_text_a_cap_and_a_guard():
    cfg = load_jsonc(ROOT / "opencode.jsonc")
    for name in ("orchestrator", "reviewer"):
        agent = cfg["agent"][name]
        assert agent["prompt"] == f"{{file:./roles/{name}.md}}"
        assert isinstance(agent["steps"], int) and agent["steps"] > 0
        perm = agent["permission"]
        assert perm["edit"] == "deny" and perm["write"] == "deny"
        assert perm["bash"]["*"] == "deny", "Guard applies only here (B4)"


def test_orchestrator_may_dispatch_wt_and_herdr():
    bash = load_jsonc(ROOT / "opencode.jsonc")["agent"]["orchestrator"]["permission"]["bash"]
    assert bash["bin/herdr-dispatch *"] == "allow"
    assert bash["wt *"] == "allow"
    assert bash["herdr *"] == "allow"


def test_reviewer_may_write_nothing_and_no_wt():
    bash = load_jsonc(ROOT / "opencode.jsonc")["agent"]["reviewer"]["permission"]["bash"]
    assert "wt *" not in bash, "the reviewer does not merge"
    assert set(bash) >= {"*", "git diff*", "git log*"}


def test_wt_toml_has_the_pre_merge_gate_and_a_fixed_schema():
    cfg = tomllib.loads((ROOT / ".config" / "wt.toml").read_text(encoding="utf-8"))
    assert cfg["pre-merge"]["test"].startswith("uv run pytest")
    assert cfg["list"]["json-schema"] == 1


def test_readme_names_every_runtime_dependency():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for requirement in (
        "uv", "python3", "worktrunk", "herdr-worktrunk", "fzf", "jq",
        "lean-ctx allow herdr", "lean-ctx allow wt",
        "lean-ctx allow bin/herdr-report",
        "wt config approvals", "warning:",
        # The work-order path, both halves of it. `ctx_task` used to stand
        # here; it is gone from the project, so requiring it would pin the
        # README to a tool that no longer exists.
        "bin/herdr-dispatch order", "bin/herdr-report",
        "ORCHESTRATOR = orch",
    ):
        assert requirement in text, f"README does not name {requirement!r}"
