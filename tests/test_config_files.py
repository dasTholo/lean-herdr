import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_jsonc(path: Path) -> dict:
    """Zeilenkommentare entfernen, ohne // in Zeichenketten anzufassen."""
    zeilen = []
    for zeile in path.read_text(encoding="utf-8").splitlines():
        ohne_strings = re.sub(r'"(?:[^"\\]|\\.)*"', '""', zeile)
        treffer = ohne_strings.find("//")
        zeilen.append(zeile[:treffer] if treffer != -1 else zeile)
    return json.loads("\n".join(zeilen))


def test_opencode_jsonc_ist_gueltig_und_liegt_im_repo():
    cfg = load_jsonc(ROOT / "opencode.jsonc")
    assert set(cfg) >= {"mcp", "agent"}


def test_lean_ctx_wird_als_stdio_server_registriert():
    server = load_jsonc(ROOT / "opencode.jsonc")["mcp"]["lean-ctx"]
    assert server["type"] == "local"
    assert server["command"] == ["lean-ctx"], "serve ist der HTTP-Server, nicht stdio"
    assert server["enabled"] is True


def test_beide_opencode_agenten_haben_rollentext_deckel_und_waechter():
    cfg = load_jsonc(ROOT / "opencode.jsonc")
    for name in ("orchestrator", "reviewer"):
        agent = cfg["agent"][name]
        assert agent["prompt"] == f"{{file:./roles/{name}.md}}"
        assert isinstance(agent["steps"], int) and agent["steps"] > 0
        perm = agent["permission"]
        assert perm["edit"] == "deny" and perm["write"] == "deny"
        assert perm["bash"]["*"] == "deny", "Waechter greift nur hier (B4)"


def test_orchestrator_darf_dispatch_wt_und_herdr():
    bash = load_jsonc(ROOT / "opencode.jsonc")["agent"]["orchestrator"]["permission"]["bash"]
    assert bash["bin/herdr-dispatch *"] == "allow"
    assert bash["wt *"] == "allow"
    assert bash["herdr *"] == "allow"


def test_reviewer_darf_nichts_schreiben_und_kein_wt():
    bash = load_jsonc(ROOT / "opencode.jsonc")["agent"]["reviewer"]["permission"]["bash"]
    assert "wt *" not in bash, "der Reviewer merged nicht"
    assert set(bash) >= {"*", "git diff*", "git log*"}


def test_wt_toml_hat_das_pre_merge_testtor_und_ein_festes_schema():
    cfg = tomllib.loads((ROOT / ".config" / "wt.toml").read_text(encoding="utf-8"))
    assert cfg["pre-merge"]["test"].startswith("uv run pytest")
    assert cfg["list"]["json-schema"] == 1


def test_readme_nennt_jede_laufzeit_abhaengigkeit():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for pflicht in (
        "uv", "worktrunk", "herdr-worktrunk", "fzf", "jq",
        "lean-ctx allow herdr", "lean-ctx allow wt", "wt config approvals",
        "warning:", "ctx_task", "<ORCHESTRATOR_AGENT_ID>",
    ):
        assert pflicht in text, f"README nennt {pflicht!r} nicht"
