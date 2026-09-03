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


def test_the_adapter_is_syntactically_loadable():
    """Not marked `integration` on purpose -- this one has to run by default.

    The four tests above search the file for substrings. A file that node
    rejects outright can carry every one of them, so all four stay green on
    an adapter opencode cannot even import. The tests that really load it are
    deselected by `addopts` in pyproject.toml, which leaves `pytest -q` with
    no reader of this file at all. `node --check` parses, it runs nothing.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is missing -- the adapter's syntax stays UNCHECKED in this run")
    proc = subprocess.run(
        [node, "--check", str(ADAPTER)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, f"node --check rejects the adapter:\n{proc.stderr}"


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
    """tool.execute.after -> `lean-ctx hook observe`, or lean-ctx sees nothing.

    The payload is the one opencode really passes: the arguments ride on the
    FIRST parameter (input={tool,sessionID,callID,args}), the second one
    carries the result (output={title,metadata,output}). A driver that puts
    `args` on the second parameter would let an adapter reading `output.args`
    look healthy while every real observation arrives empty.
    """
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
          {{
            tool: "Read",
            sessionID: "ses_1",
            callID: "call_1",
            args: {{ filePath: "README.md" }},
          }},
          {{ title: "README.md", metadata: {{}}, output: "x" }},
        );
        console.log("observed");
        """,
    )
    assert "observed" in proc.stdout, proc.stderr
    seen = json.loads(transcript.read_text(encoding="utf-8"))
    assert seen["tool_name"] == "read", "the name is passed through lower-cased"
    assert seen["tool_input"] == {"filePath": "README.md"}, "args ride on `input`"
    assert seen["tool_response"] == "x"
    assert seen["session_id"] == "ses_1"


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


def _hooks_dir(tmp_path: Path, body: str) -> Path:
    """A hooks directory holding one bash script with `body`."""
    hooks = tmp_path / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    script = hooks / "bash-enforce-ctx-shell.py"
    script.write_text(body, encoding="utf-8")
    script.chmod(0o755)
    return hooks


@pytest.mark.integration
def test_a_crashing_script_passes_through_but_is_never_silent(tmp_path):
    """Fail-open is the design -- failing open WITHOUT a word is not.

    A hook that dies leaves the tool unguarded. If that happens silently,
    nobody learns the hardening stopped working.
    """
    hooks = _hooks_dir(tmp_path, "import sys\nsys.stderr.write('boom\\n')\nsys.exit(3)\n")
    proc = node_driver(
        tmp_path,
        f"""
        process.env.LEAN_HERDR_HOOKS_DIR = {json.dumps(str(hooks))};
        const {{ LeanCtxPolicy }} = await import({json.dumps(str(ADAPTER))});
        const hooks = await LeanCtxPolicy({{ directory: process.cwd() }});
        await hooks["tool.execute.before"](
          {{ tool: "bash" }}, {{ args: {{ command: "echo hi" }} }},
        );
        console.log("passed through");
        """,
    )
    assert "passed through" in proc.stdout, proc.stderr
    assert "exit 3" in proc.stderr, f"the crash must be noted: {proc.stderr}"
    assert "boom" in proc.stderr, "the script's own stderr must reach the operator"


@pytest.mark.integration
def test_a_script_that_ignores_stdin_does_not_kill_the_session(tmp_path):
    """An EPIPE on the hook's stdin must never take the whole process down.

    Without an `error` handler on `child.stdin`, node raises an unhandled
    'error' event and exits -- the one failure mode the adapter promises can
    never happen. A payload past the pipe buffer makes it reproducible.
    """
    hooks = _hooks_dir(tmp_path, "import sys\nsys.exit(0)\n")
    proc = node_driver(
        tmp_path,
        f"""
        process.env.LEAN_HERDR_HOOKS_DIR = {json.dumps(str(hooks))};
        const {{ LeanCtxPolicy }} = await import({json.dumps(str(ADAPTER))});
        const hooks = await LeanCtxPolicy({{ directory: process.cwd() }});
        await hooks["tool.execute.before"](
          {{ tool: "bash" }}, {{ args: {{ command: "x".repeat(4_000_000) }} }},
        );
        console.log("survived");
        """,
    )
    assert proc.returncode == 0, f"node died: {proc.stderr}"
    assert "survived" in proc.stdout, proc.stderr
    assert "Unhandled" not in proc.stderr, proc.stderr


@pytest.mark.integration
def test_hooks_may_live_inside_the_repository(tmp_path):
    """Not every checkout shares one home directory.

    Without LEAN_HERDR_HOOKS_DIR the adapter looks in the project's own
    `.claude/hooks` before falling back to the home directory, so a repo can
    carry its policy with it.
    """
    root = tmp_path / "repo"
    local = root / ".claude" / "hooks"
    local.mkdir(parents=True)
    (local / "bash-enforce-ctx-shell.py").write_text(
        "import json, sys\n"
        "print(json.dumps({'hookSpecificOutput': {'permissionDecision': 'deny',\n"
        "    'permissionDecisionReason': 'denied by the repository-local hook'}}))\n",
        encoding="utf-8",
    )
    proc = node_driver(
        tmp_path,
        f"""
        delete process.env.LEAN_HERDR_HOOKS_DIR;
        const {{ LeanCtxPolicy }} = await import({json.dumps(str(ADAPTER))});
        const hooks = await LeanCtxPolicy({{ project: {{ worktree: {json.dumps(str(root))} }} }});
        try {{
          await hooks["tool.execute.before"](
            {{ tool: "bash" }}, {{ args: {{ command: "echo hi" }} }},
          );
          console.log("ALLOWED");
        }} catch (err) {{
          console.log("DENIED: " + err.message);
        }}
        """,
    )
    assert "DENIED: denied by the repository-local hook" in proc.stdout, (
        f"stdout={proc.stdout} stderr={proc.stderr}"
    )
