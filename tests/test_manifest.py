import ast
import importlib
import shutil
import subprocess
import tomllib
import zipfile
from pathlib import Path

import pytest

from lean_herdr.templating import LAYOUT

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "herdr-plugin.toml"

#: The one line that turns this package into the `lean-herdr` an operator
#: and every role prompt actually type.
ENTRY_POINT = {"lean-herdr": "lean_herdr.cli:main"}

#: The oldest interpreter a bare `python3` on an operator host may turn out to
#: be. Raised from 3.11 by operator decision on 2026-09-04: the hosts this
#: plugin runs on carry 3.14, and the workspace-start plan names that floor in
#: its Global Constraints. The number only ever loosens what `ast.parse`
#: accepts below -- lowering it again is the strict direction, not the lax one.
OLDEST_PYTHON = (3, 14)

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
    """Every command in the manifest spawns a bare `python3`.

    That interpreter is whatever the host provides, never the pinned one
    from `uv`. Syntax it cannot parse kills the handler at IMPORT time,
    before main() can keep its "exit always 0" promise. PEP 758's
    parenthesis-free `except A, B:` was such a case. ast.parse only
    parses, it runs nothing.

    `bin/herdr-dispatch` and `bin/herdr-report` used to stand in this list
    for the same reason and are gone: as the `lean-herdr` entry point the
    CLIs run under the INSTALLED interpreter. `bin/herdr-llm` stays --
    worktrunk starts it as a bare `python3` script, not through an entry
    point. The package glob stays too: `handlers.py` and everything it
    imports is still reached by a bare `python3`, and that now includes
    `workspace.py`.
    """
    assert all(e["command"][0] == "python3" for e in manifest()["events"]), (
        "the floor below only matters as long as the manifest spawns python3"
    )
    sources = [
        *sorted((ROOT / "lean_herdr").glob("*.py")),
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


def test_the_entry_point_still_points_at_a_callable_main():
    """`lean-herdr <verb>` is the ONLY way in outside this checkout.

    The manifest spawns `python3 -m lean_herdr` for the plugin events, but
    every role prompt, every worktrunk hook and every operator types
    `lean-herdr`. That name exists solely because of this one pyproject
    line -- rename the module or the function and nothing in the tree
    notices until an installed environment does.
    """
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["scripts"] == ENTRY_POINT
    for target in ENTRY_POINT.values():
        module, _, attribute = target.partition(":")
        assert callable(getattr(importlib.import_module(module), attribute)), target


@pytest.mark.integration
def test_the_wheel_ships_the_templates(tmp_path):
    """`init` writes files OUT of the package. A wheel without them is silent.

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
    assert wanted <= shipped, sorted(wanted - shipped)


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
    lines = [
        line for line in listing.stdout.splitlines() if "lean.herdr" in line or "warning:" in line
    ]
    assert not any("warning:" in line for line in lines), "\n".join(lines)
