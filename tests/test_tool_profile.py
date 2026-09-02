"""Profile test: `minimal` must carry ctx_call."""

import json
import os
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.integration

INITIALIZE = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "lean-herdr-tests", "version": "0"},
    },
}
INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized"}
LIST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}


def tools_under(profile: str, tmp_path) -> set[str]:
    """Real stdio handshake against the installed server.

    HOME points at tmp_path so that no user configuration has a say -- but
    PATH stays the real one. lean-ctx typically lives in `~/.cargo/bin` or
    `~/.local/bin`; a hand-assembled minimal PATH would no longer find the
    server, and the test would fail on itself instead of on the profile.
    """
    binary = shutil.which("lean-ctx")
    if binary is None:
        pytest.skip("lean-ctx not installed")
    stdin_text = "".join(json.dumps(m) + "\n" for m in (INITIALIZE, INITIALIZED, LIST))
    proc = subprocess.run(
        [binary],
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        cwd=tmp_path,
        env={
            **os.environ,
            "HOME": str(tmp_path),
            "LEAN_CTX_TOOL_PROFILE": profile,
        },
    )
    names: set[str] = set()
    for line in proc.stdout.splitlines():
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        for tool in (message.get("result") or {}).get("tools") or ():
            names.add(tool["name"])
    return names


def test_minimal_carries_ctx_call(tmp_path):
    names = tools_under("minimal", tmp_path)
    assert names, "tools/list returned nothing -- handshake failed?"
    assert "ctx_call" in names, (
        "The orchestrator reaches ctx_agent exclusively through ctx_call. "
        "Without ctx_call it goes silent without reporting an error."
    )
    assert len(names) <= 12, f"minimal has grown: {sorted(names)}"


def test_standard_brings_ctx_session_along(tmp_path):
    assert {"ctx_call", "ctx_session"} <= tools_under("standard", tmp_path)
