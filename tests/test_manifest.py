import importlib
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

from lean_herdr.templating import LAYOUT

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "lean_herdr" / "plugin" / "herdr-plugin.toml"

#: The one line that turns this package into the `lean-herdr` an operator
#: and every role prompt actually type.
ENTRY_POINT = {"lean-herdr": "lean_herdr.cli:main"}

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


def test_every_manifest_command_runs_the_installed_plugin_verb():
    """The manifest starts no bare `python3` any more -- the snapshot's own binary.

    A host `python3` had to find the package through the linked checkout and
    parse it on whatever interpreter the host carried. `lean-herdr plugin <sub>`
    runs under the interpreter the package was installed with, so the syntax
    floor is `requires-python` alone. That `<sub>` has a handler is
    `test_no_handler_without_subcommand`'s job.
    """
    for entry in manifest()["events"] + manifest()["actions"]:
        assert entry["command"][:2] == ["lean-herdr", "plugin"], entry
        assert len(entry["command"]) == 3, entry


def test_python_m_from_the_checkout_still_reaches_the_handlers():
    """Without the `sys.path` insert, `python -m lean_herdr` works from the repo root."""
    proc = subprocess.run(
        [sys.executable, "-m", "lean_herdr", "does-not-exist"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "unknown subcommand" in proc.stderr


def test_the_entry_point_still_points_at_a_callable_main():
    """`lean-herdr <verb>` is the ONLY way in outside this checkout.

    The manifest spawns `lean-herdr plugin <sub>`, worktrunk spawns
    `lean-herdr llm generate`, and every role prompt and every operator types
    `lean-herdr`. That name exists solely because of this one pyproject line --
    rename the module or the function and nothing in the tree notices until an
    installed environment does.
    """
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["scripts"] == ENTRY_POINT
    for target in ENTRY_POINT.values():
        module, _, attribute = target.partition(":")
        assert callable(getattr(importlib.import_module(module), attribute)), target


@pytest.mark.integration
def test_the_wheel_ships_the_templates(tmp_path):
    """`init` writes files OUT of the package, and Herdr links the manifest inside it. A wheel without them is silent.

    `[tool.hatch.build.targets.wheel]` names the package, not its data, so
    nothing in this tree would notice `lean_herdr/templates/` dropping out
    of the build -- `init` reads them off the source checkout in every
    other test. It would break only in an installed environment, and only
    on the one call that is supposed to set a project up.

    Marked `integration` because a real build costs seconds; every other
    test in this suite runs in milliseconds.
    """
    if shutil.which("uv") is None:
        pytest.skip("uv not installed")
    build = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert build.returncode == 0, build.stderr
    wheel = next(iter(tmp_path.glob("*.whl")))
    with zipfile.ZipFile(wheel) as archive:
        shipped = set(archive.namelist())
    wanted = {f"lean_herdr/templates/{name}" for name in LAYOUT}
    wanted.add("lean_herdr/plugin/herdr-plugin.toml")
    assert wanted <= shipped, sorted(wanted - shipped)


@pytest.mark.integration
def test_plugin_link_produces_no_warning(tmp_path):
    """H6: Herdr only warns for unknown events — here the warning becomes fatal.

    It re-links the operator's real `lean.herdr` to this checkout's package
    directory. Run it on purpose, after the plugin was moved to the snapshot --
    never as part of a gate.
    """
    if shutil.which("herdr") is None:
        pytest.skip("herdr not installed")
    subprocess.run(
        ["herdr", "plugin", "link", str(MANIFEST.parent)],
        capture_output=True,
        text=True,
        check=False,
    )
    listing = subprocess.run(
        ["herdr", "plugin", "list"], capture_output=True, text=True, timeout=30, check=False
    )
    lines = [
        line for line in listing.stdout.splitlines() if "lean.herdr" in line or "warning:" in line
    ]
    assert not any("warning:" in line for line in lines), "\n".join(lines)
