import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / ".opencode" / "plugins" / "lean-ctx-policy.js"
HOOKS = Path.home() / ".claude" / "hooks"


def test_the_adapter_is_project_local_and_does_not_hardwire_claude():
    text = ADAPTER.read_text(encoding="utf-8")
    assert "LEAN_HERDR_HOOKS_DIR" in text
    assert '".claude", "hooks"' in text, "only as a default, not hardwired"


def test_every_mapped_hook_exists():
    text = ADAPTER.read_text(encoding="utf-8")
    for script in (
        "read-search-discipline.py",
        "bash-enforce-ctx-shell.py",
        "edit-tool-discipline.py",
        "lean-ctx-policy-guard.py",
    ):
        assert script in text, f"{script} is not mapped in the adapter"


def test_the_adapter_throws_only_on_deny():
    text = ADAPTER.read_text(encoding="utf-8")
    assert 'permissionDecision === "deny"' in text
    assert "throw new Error" in text
    assert 'output.status = "deny"' in text, "permission.ask does not ask"


def test_all_three_hook_points_are_wired():
    text = ADAPTER.read_text(encoding="utf-8")
    for point in ("tool.execute.before", "tool.execute.after", "permission.ask"):
        assert f'"{point}"' in text, f"{point} is missing from the adapter"
    assert '"hook", "observe"' in text, "tool.execute.after must feed lean-ctx"


def node_driver(tmp_path: Path, body: str) -> subprocess.CompletedProcess:
    """Really load and call the adapter -- not just read its text."""
    if shutil.which("node") is None:
        pytest.skip("node not installed")
    driver = tmp_path / "driver.mjs"
    driver.write_text(body, encoding="utf-8")
    return subprocess.run(
        ["node", str(driver)], capture_output=True, text=True, timeout=30, check=False
    )


@pytest.mark.integration
def test_a_real_hook_denies_native_grep_through_the_adapter(tmp_path):
    """The same decision as on Claude -- and through the JS adapter.

    Calling the Python script directly only checks the script. Mis-mapped
    tool names, a badly translated payload or a swallowed `deny` would stay
    undetected -- exactly the failures that can ONLY live in the adapter.
    """
    if not (HOOKS / "bash-enforce-ctx-shell.py").is_file():
        pytest.skip("policy hooks not installed")
    proc = node_driver(
        tmp_path,
        f"""
        const {{ LeanCtxPolicy }} = await import({json.dumps(str(ADAPTER))});
        const hooks = await LeanCtxPolicy({{ directory: process.cwd() }});
        const output = {{ args: {{ command: "grep -r foo ." }} }};
        try {{
          await hooks["tool.execute.before"]({{ tool: "bash" }}, output);
          console.log("PASSED");
        }} catch (err) {{
          console.log("DENIED: " + err.message);
        }}
        """,
    )
    assert "DENIED:" in proc.stdout, f"stdout={proc.stdout} stderr={proc.stderr}"
    assert "ctx_" in proc.stdout, "the reason comes from the script, not the adapter"


@pytest.mark.integration
def test_the_adapter_reports_every_tool_call_to_lean_ctx(tmp_path):
    """tool.execute.after -> `lean-ctx hook observe`, or lean-ctx sees nothing."""
    if shutil.which("lean-ctx") is None:
        pytest.skip("lean-ctx not installed")
    # A stub instead of the real binary: the test measures the HANDOVER, it
    # must not change the state of lean-ctx.
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    transcript = tmp_path / "seen.json"
    (stub_dir / "lean-ctx").write_text(
        "#!/bin/sh\ncat > " + json.dumps(str(transcript))[1:-1] + "\n",
        encoding="utf-8",
    )
    (stub_dir / "lean-ctx").chmod(0o755)
    proc = node_driver(
        tmp_path,
        f"""
        process.env.PATH = {json.dumps(str(stub_dir))} + ":" + process.env.PATH;
        const {{ LeanCtxPolicy }} = await import({json.dumps(str(ADAPTER))});
        const hooks = await LeanCtxPolicy({{ directory: process.cwd() }});
        await hooks["tool.execute.after"](
          {{ tool: "Read" }},
          {{ args: {{ filePath: "README.md" }}, output: {{ content: "x" }} }},
        );
        console.log("observed");
        """,
    )
    assert "observed" in proc.stdout, proc.stderr
    seen = json.loads(transcript.read_text(encoding="utf-8"))
    assert seen["tool_name"] == "read", "the name is passed through lower-cased"
    assert seen["tool_input"] == {"filePath": "README.md"}
    assert seen["tool_response"] == {"content": "x"}


@pytest.mark.integration
def test_a_missing_script_lets_the_tool_through(tmp_path):
    """A broken hardening must not be worse than none."""
    if shutil.which("node") is None:
        pytest.skip("node not installed")
    driver = tmp_path / "driver.mjs"
    driver.write_text(
        f"""
        process.env.LEAN_HERDR_HOOKS_DIR = {json.dumps(str(tmp_path / "empty"))};
        const {{ LeanCtxPolicy }} = await import({json.dumps(str(ADAPTER))});
        const hooks = await LeanCtxPolicy({{ directory: process.cwd() }});
        const output = {{ args: {{ command: "grep -r foo ." }} }};
        await hooks["tool.execute.before"]({{ tool: "bash" }}, output);
        console.log("passed through");
        """,
        encoding="utf-8",
    )
    proc = subprocess.run(
        ["node", str(driver)], capture_output=True, text=True, timeout=30, check=False
    )
    assert "passed through" in proc.stdout, proc.stderr
    assert "is missing" in proc.stderr, "the outage is noted on stderr"
