"""`lean-herdr workspace init` -- write the templates, report the rest.

Two rules run through everything here.

The first: an existing file is NEVER overwritten without --force. A
stranger's `opencode.jsonc` or `.claude/settings.json` flattened in
silence would be the most expensive mistake this tool could make. Skipped
files are named in the result, so nobody has to guess what happened.

The second: preconditions are REPORTED, never repaired. Every foreign
command here only READS -- `lean-ctx allow --list`, `wt config approvals
list --format json`, `herdr plugin list`. `init` runs no `lean-ctx allow`
and no `wt config approvals add`: granting a machine-wide permission is a
gesture that belongs to the human at the keyboard.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from lean_herdr.bus import BusError, canonical_root

TEMPLATES = Path(__file__).resolve().parent / "templates"

#: A read-only check must not hold up the whole call.
CHECK_TIMEOUT_S = 10.0

#: template inside the package -> where it goes in the target project.
#: THE one truth: tests/test_templates.py imports this table to hold each
#: template byte-identical against this repo's own copy.
#:
#: Only the first four are movable. `opencode.jsonc`,
#: `.claude/settings.json`, `.config/wt.toml` and the opencode plugin sit
#: where their owners look for them. `.config/wt.toml` could in theory move
#: via WORKTRUNK_PROJECT_CONFIG_PATH -- but that variable would have to be
#: set on EVERY `wt` call, hand-typed ones included, and a single miss makes
#: `wt` skip the project hooks silently and report success. The pre-merge
#: test gate would then not run at all.
LAYOUT = {
    "config.toml": ".lean-ctx/lean-herdr/config.toml",
    "roles/orchestrator.md": ".lean-ctx/lean-herdr/roles/orchestrator.md",
    "roles/builder.md": ".lean-ctx/lean-herdr/roles/builder.md",
    "roles/reviewer.md": ".lean-ctx/lean-herdr/roles/reviewer.md",
    "opencode.jsonc": "opencode.jsonc",
    "settings.json": ".claude/settings.json",
    "wt.toml": ".config/wt.toml",
    "lean-ctx-policy.js": ".opencode/plugins/lean-ctx-policy.js",
}


def _read(runner: Any, *cmd: str, cwd: Path | None = None) -> str | None:
    """One read-only foreign command. None when it cannot run at all.

    stdout AND stderr, because `wt` writes its warnings to stderr and a
    check that ignored them would report a green state over a complaint.
    """
    if shutil.which(cmd[0]) is None:
        return None
    try:
        proc = runner(
            list(cmd),
            capture_output=True,
            text=True,
            timeout=CHECK_TIMEOUT_S,
            cwd=None if cwd is None else str(cwd),
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return (proc.stdout or "") + (proc.stderr or "")


def _warnings(root: Path, *, runner: Any = subprocess.run) -> list[str]:
    """The README checklist as lines. Nothing here changes anything."""
    found: list[str] = []
    for binary, why in (
        ("herdr", "panes, agents and workspaces"),
        ("wt", "one worktree per branch, merge and cleanup"),
        ("lean-ctx", "agent bus, project memory, tool profiles"),
    ):
        if shutil.which(binary) is None:
            found.append(f"{binary} is not on PATH -- needed for {why}")

    allowlist = _read(runner, "lean-ctx", "allow", "--list")
    # Word boundaries, not a plain substring: the listing prints the config
    # path too, and a project directory called lean-herdr would otherwise
    # read as a granted permission.
    if allowlist is not None and not re.search(r"\blean-herdr\b", allowlist):
        found.append(
            "lean-ctx does not allow `lean-herdr` -- "
            "an agent under shell gating cannot run it: lean-ctx allow lean-herdr"
        )

    approvals = _read(runner, "wt", "config", "approvals", "list", "--format", "json", cwd=root)
    if approvals is not None:
        # The reply may carry a warning line ahead of the JSON, so parse
        # from the first brace rather than the first byte.
        start = approvals.find("{")
        try:
            state = json.loads(approvals[start:])["state"] if start >= 0 else None
        except (json.JSONDecodeError, KeyError, TypeError):
            state = None
        if state != "approved":
            found.append(
                f"worktrunk project hooks are not approved (state: {state!r}) -- "
                "wt skips them SILENTLY and reports success, so the pre-merge "
                "test gate would not run: wt config approvals add"
            )

    plugins = _read(runner, "herdr", "plugin", "list")
    if plugins is not None and "warning:" in plugins:
        found.append(
            "herdr plugin list carries a `warning:` line -- "
            "Herdr does not reject an unknown plugin event, it only warns"
        )
    return found


def _place(target: Path, source: Path, *, force: bool) -> bool:
    """Write one template. True when it landed, False when it was skipped.

    `exists()` FOLLOWS the link, so a dead symlink at a template's place
    reads as an absent file and the write lands wherever it points --
    outside the project this command was aimed at, past the only guard it
    has. `is_symlink()` is the half that sees it. And `--force` is
    permission to overwrite HERE, never to write somewhere else: the link
    goes, its target is not touched.
    """
    if (target.is_symlink() or target.exists()) and not force:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        target.unlink()
    target.write_bytes(source.read_bytes())
    return True


def workspace_init(
    *,
    root: Path | None = None,
    force: bool = False,
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    """Write the templates into this project. Never raises.

    No git repository: a hard stop with a named next step. `init` does not
    run `git init` itself -- that is a gesture belonging to the human.

    A tree that is hostile or half-built -- a dead symlink at a template's
    place, a regular file where a directory belongs, a directory nobody may
    write -- ends the run early with `init_stopped` and the report so far.
    Letting the exception through would take the written/skipped list with
    it, and nobody could then say which files already landed.
    """
    try:
        base = root if root is not None else canonical_root()
    except BusError:
        return {"ok": False, "error": "not_a_git_repo: run `git init` first"}
    except OSError as exc:
        # `canonical_root()` shells out to git; with no git on the PATH that
        # is a FileNotFoundError, which is not a BusError.
        return {"ok": False, "error": f"init_stopped: {exc}"}

    written: list[str] = []
    skipped: list[str] = []
    try:
        for name, relative in LAYOUT.items():
            landed = _place(base / relative, TEMPLATES / name, force=force)
            (written if landed else skipped).append(relative)
    except OSError as exc:
        return {
            "ok": False,
            "error": f"init_stopped: {exc}",
            "root": str(base),
            "written": sorted(written),
            "skipped": sorted(skipped),
        }
    return {
        "ok": True,
        "root": str(base),
        "written": sorted(written),
        "skipped": sorted(skipped),
        "warnings": _warnings(base, runner=runner),
    }
