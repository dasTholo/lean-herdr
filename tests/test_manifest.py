import ast
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "herdr-plugin.toml"

#: The oldest interpreter a bare `python3` on an operator host may turn out to
#: be. Nothing this package imports needs grammar newer than that.
OLDEST_PYTHON = (3, 11)

#: Confirmed via `plugin link` without warning. `layout.updated` does NOT exist.
VALID_EVENTS = {
    "pane.agent_detected",
    "pane.agent_status_changed",
    "pane.created",
    "pane.closed",
    "pane.exited",
    "tab.created",
    "workspace.created",
    "workspace.closed",
    "workspace.focused",
    "worktree.created",
}


def manifest() -> dict:
    return tomllib.loads(MANIFEST.read_text(encoding="utf-8"))


def test_every_event_is_known_and_in_dot_notation():
    for entry in manifest()["events"]:
        on = entry["on"]
        assert "_" not in on.split(".")[0], f"{on}: socket schema instead of dot notation"
        assert on in VALID_EVENTS, f"{on} is not a valid Herdr event"


def test_no_handler_without_subcommand():
    from lean_herdr.__main__ import HANDLERS

    for entry in manifest()["events"] + manifest()["actions"]:
        sub = entry["command"][-1]
        assert sub in HANDLERS, f"{sub} has no handler"


def test_both_actions_attach_to_the_right_context():
    by_id = {a["id"]: a for a in manifest()["actions"]}
    assert by_id["inject"]["contexts"] == ["pane"]
    assert by_id["bootstrap"]["contexts"] == ["workspace"], (
        "The bootstrap creates a pane IN this workspace — a pane context "
        "would be the wrong reference."
    )


def test_main_survives_a_missing_handlers_module(monkeypatch, capsys):
    """Task 13 must pass without Task 15: the import only happens on the call."""
    import importlib

    from lean_herdr.__main__ import main

    def no_module(name):
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(importlib, "import_module", no_module)
    assert main(["inject"]) == 0
    assert "[lean.herdr] inject failed" in capsys.readouterr().err


def test_an_unknown_subcommand_is_not_a_crash(capsys):
    from lean_herdr.__main__ import main

    assert main(["does-not-exist"]) == 0
    assert "unknown subcommand" in capsys.readouterr().err


def test_the_package_parses_on_the_python3_the_manifest_may_meet():
    """Every command here spawns a bare `python3` -- so does every bin/ script.

    That interpreter is whatever the host provides, never the pinned one from
    `uv`. Syntax it cannot parse kills the handler at IMPORT time, before
    main() can keep its "exit always 0" promise. PEP 758's parenthesis-free
    `except A, B:` was such a case. ast.parse only parses, it runs nothing.
    """
    assert all(e["command"][0] == "python3" for e in manifest()["events"]), (
        "the floor below only matters as long as the manifest spawns python3"
    )
    sources = [
        *sorted((ROOT / "lean_herdr").glob("*.py")),
        ROOT / "bin" / "herdr-dispatch",
        ROOT / "bin" / "herdr-report",
        ROOT / "bin" / "herdr-llm",
    ]
    offenders = []
    for path in sources:
        try:
            ast.parse(path.read_text(encoding="utf-8"), feature_version=OLDEST_PYTHON)
        except SyntaxError as err:
            offenders.append(f"{path.relative_to(ROOT)}:{err.lineno}: {err.msg}")
    floor = ".".join(str(part) for part in OLDEST_PYTHON)
    assert not offenders, f"needs syntax newer than {floor}:\n" + "\n".join(offenders)


@pytest.mark.integration
def test_plugin_link_produces_no_warning(tmp_path):
    """H6: Herdr only warns for unknown events — here the warning becomes fatal."""
    if shutil.which("herdr") is None:
        pytest.skip("herdr not installed")
    subprocess.run(
        ["herdr", "plugin", "link", str(ROOT)], capture_output=True, text=True, check=False
    )
    listing = subprocess.run(
        ["herdr", "plugin", "list"], capture_output=True, text=True, timeout=30, check=False
    )
    lines = [line for line in listing.stdout.splitlines() if "lean.herdr" in line or "warning:" in line]
    assert not any("warning:" in line for line in lines), "\n".join(lines)
