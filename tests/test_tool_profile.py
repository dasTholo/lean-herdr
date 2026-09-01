"""Profil-Test: `minimal` muss ctx_call enthalten."""

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


def tools_unter(profil: str, tmp_path) -> set[str]:
    """Echter stdio-Handshake gegen den installierten Server.

    HOME zeigt auf tmp_path, damit keine Nutzerkonfiguration mitspricht — aber
    PATH bleibt der echte. lean-ctx liegt typischerweise in `~/.cargo/bin` oder
    `~/.local/bin`; ein zusammengesetzter Minimal-PATH wuerde den Server nicht
    mehr finden, und der Test scheiterte an sich selbst statt am Profil.
    """
    binary = shutil.which("lean-ctx")
    if binary is None:
        pytest.skip("lean-ctx nicht installiert")
    eingabe = "".join(json.dumps(m) + "\n" for m in (INITIALIZE, INITIALIZED, LIST))
    proc = subprocess.run(
        [binary],
        input=eingabe,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        cwd=tmp_path,
        env={
            **os.environ,
            "HOME": str(tmp_path),
            "LEAN_CTX_TOOL_PROFILE": profil,
        },
    )
    namen: set[str] = set()
    for zeile in proc.stdout.splitlines():
        try:
            nachricht = json.loads(zeile)
        except json.JSONDecodeError:
            continue
        for tool in (nachricht.get("result") or {}).get("tools") or ():
            namen.add(tool["name"])
    return namen


def test_minimal_enthaelt_ctx_call(tmp_path):
    namen = tools_unter("minimal", tmp_path)
    assert namen, "tools/list lieferte nichts — Handshake gescheitert?"
    assert "ctx_call" in namen, (
        "Der Orchestrator erreicht ctx_agent ausschliesslich ueber ctx_call. "
        "Ohne ctx_call verstummt er, ohne einen Fehler zu melden."
    )
    assert len(namen) <= 12, f"minimal ist gewachsen: {sorted(namen)}"


def test_standard_bringt_ctx_session_mit(tmp_path):
    assert {"ctx_call", "ctx_session"} <= tools_unter("standard", tmp_path)
