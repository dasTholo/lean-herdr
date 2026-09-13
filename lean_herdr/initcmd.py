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
gesture that belongs to the human at the keyboard. The ONE exception is
the warm-up (`_warm_opencode`), and it stays inside the rule's intent: it
changes nothing on the machine, only opencode's own cache for this
project, and it is aborted on purpose.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from lean_herdr.bus import BusError, GitUnusable, canonical_root
from lean_herdr.settings import (
    OVERLAY_PATH,
    SETTINGS_PATH,
    SettingsError,
    model_warnings,
    models_settings,
    read_settings,
    settings_for,
    workspace_settings,
)
from lean_herdr.workspace import OPENCODE_ORCHESTRATOR

TEMPLATES = Path(__file__).resolve().parent / "templates"

#: A read-only check must not hold up the whole call.
CHECK_TIMEOUT_S = 10.0

#: The warm-up, and the one number it turns on. opencode's FIRST bootstrap
#: in a project that carries a project plugin hangs -- and the plugin this
#: very command writes is such a plugin. A bootstrap that got far enough
#: and was then ABORTED warms the project; the next start measures 3.4 s.
#: 5 s warmed 6 of 6 runs on 2026-09-04, 8 s is the margin. The ABORT is
#: the point: the exit code and the output are worthless here.
#:
#: NOT `--pure`: that switch skips external plugins, i.e. exactly the step
#: that has to be warmed. Measured 3 of 3 still hanging afterwards.
WARM_TIMEOUT_S = 8.0

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
    except OSError, subprocess.SubprocessError:
        return None
    return (proc.stdout or "") + (proc.stderr or "")


def _check_allowlist(runner: Any) -> str | None:
    """`lean-ctx allow --list`. A line when it does not name `lean-herdr`.

    Word boundaries, not a plain substring: the listing prints the config
    path too, and a project directory called lean-herdr would otherwise
    read as a granted permission.

    This line can only ever be a hint. `lean-ctx allow --list` prints the
    additive `Extra` list in full but reduces the base `shell_allowlist`
    to a COUNT ("74 command(s) permitted"), so an operator who put
    `lean-herdr` in the base list is indistinguishable here from one who
    granted it nowhere. Measured 2026-09-04; there is no --format json.
    Claiming "does not allow" would therefore be a verdict the check
    cannot reach -- and a false alarm on every run, in every project.
    """
    allowlist = _read(runner, "lean-ctx", "allow", "--list")
    if allowlist is None or re.search(r"\blean-herdr\b", allowlist):
        return None
    return (
        "lean-ctx allow --list does not name `lean-herdr` -- it shows only the "
        "additive `Extra` list, never the base allowlist, so this is a hint and "
        "not a verdict. If the base list does not carry it either, an agent under "
        "shell gating cannot run it: lean-ctx allow lean-herdr"
    )


def _check_approvals(root: Path, runner: Any) -> str | None:
    """`wt config approvals list`. A line for anything but `approved`.

    An unreadable reply is reported as an unknown state, never as a green
    one: this check exists because `wt` skips unapproved hooks silently.
    """
    approvals = _read(runner, "wt", "config", "approvals", "list", "--format", "json", cwd=root)
    if approvals is None:
        return None
    # `_read` concatenates stdout AND stderr, so the reply may carry a
    # warning line ahead of the JSON -- parse from the first brace rather
    # than from the first byte.
    start = approvals.find("{")
    try:
        state = json.loads(approvals[start:])["state"] if start >= 0 else None
    except json.JSONDecodeError, KeyError, TypeError:
        state = None
    if state == "approved":
        return None
    return (
        f"worktrunk project hooks are not approved (state: {state!r}) -- "
        "wt skips them SILENTLY and reports success, so the pre-merge "
        "test gate would not run: wt config approvals add"
    )


def _check_plugins(runner: Any) -> str | None:
    """`herdr plugin list`. A line when the listing carries a warning."""
    plugins = _read(runner, "herdr", "plugin", "list")
    if plugins is None or "warning:" not in plugins:
        return None
    return (
        "herdr plugin list carries a `warning:` line -- "
        "Herdr does not reject an unknown plugin event, it only warns"
    )


def _check_overlay_ignored(root: Path, runner: Any) -> str | None:
    """`[models].auto` is on and git does not ignore the overlay.

    `git check-ignore` is asked rather than `.gitignore` read, because the
    answer is git's and not ours: a rule can sit in a parent directory, in
    `.git/info/exclude` or in a global excludes file, and a text search
    would raise a false alarm on every one of them.

    `init` does NOT append the line itself. A `.gitignore` belongs to the
    project, and this module writes only its own files -- the operator
    gets the exact line and decides.
    """
    answer = _read(runner, "git", "check-ignore", "-v", str(OVERLAY_PATH), cwd=root)
    if answer is None or answer.strip():
        # None: no git at all, so no verdict. Non-empty: git named the
        # rule that covers it, which is exactly what we wanted.
        return None
    return (
        f"[models].auto is on and git does not ignore {OVERLAY_PATH} -- "
        "it is machine-local and must not be shared. Add to .gitignore: "
        f"{OVERLAY_PATH}"
    )


def _warnings(
    root: Path, *, data: dict[str, Any], overlay_auto: bool, runner: Any = subprocess.run
) -> list[str]:
    """The README checklist as lines. Nothing here changes anything.

    The three foreign checks each live in their own function: they share
    nothing but the `runner`, and four independent checks in one body sat
    over the complexity threshold and could only be tested through `init`.

    `data` is the settings file, already read. The config-derived warnings
    come out of `settings`, never out of a second reading here -- one
    producer per rule (M3), and `dispatch` reads the very same one for the
    reviewer's build line.

    `overlay_auto` is `[models].auto`, validated by the caller inside the
    guard that keeps the written/skipped report. Read here instead, a typo
    in `[models]` raised past that guard and took the report with it.
    """
    found: list[str] = []
    for binary, why in (
        ("herdr", "panes, agents and workspaces"),
        ("wt", "one worktree per branch, merge and cleanup"),
        ("lean-ctx", "agent bus, project memory, tool profiles"),
    ):
        if shutil.which(binary) is None:
            found.append(f"{binary} is not on PATH -- needed for {why}")
    checks = (
        _check_allowlist(runner),
        _check_approvals(root, runner),
        _check_plugins(runner),
        # Guarded by the config, unlike its three neighbours: without
        # `[models].auto` no overlay is ever written, and a rule for a file
        # that cannot exist would be noise in every project that never
        # switched the feature on.
        _check_overlay_ignored(root, runner) if overlay_auto else None,
    )
    found.extend(line for line in checks if line is not None)
    found.extend(model_warnings(data))
    return found


def _warm_opencode(root: Path, *, runner: Any) -> bool:
    """One aborted `opencode debug agent` in `root`. True when it ran.

    The only foreign command in this module that is not a pure read --
    and it still changes nothing on the operator's machine, only inside
    opencode's own cache for this project.

    Silent on every failure: a warm-up that did not happen costs the next
    `workspace up` its second attempt and nothing else, while an
    exception here would take the written/skipped report with it.
    """
    if shutil.which("opencode") is None:
        return False
    try:
        runner(
            ["opencode", "debug", "agent", OPENCODE_ORCHESTRATOR],
            capture_output=True,
            text=True,
            timeout=WARM_TIMEOUT_S,
            cwd=str(root),
            check=False,
        )
    except subprocess.TimeoutExpired:
        # The expected end, not an error: the abort IS the warm-up.
        return True
    except OSError, subprocess.SubprocessError:
        return False
    return True


def _place(root: Path, relative: str, source: Path, *, force: bool) -> bool:
    """Write one template. True when it landed, False when it was skipped.

    NO component below `root` may be a symlink -- neither the file at the
    end of `relative` nor a directory on the way to it.

    `exists()` FOLLOWS the link, so a dead symlink at a template's place
    reads as an absent file and the write lands wherever it points --
    outside the project this command was aimed at, past the only guard it
    has. `is_symlink()` is the half that sees it. And `--force` is
    permission to overwrite HERE, never to write somewhere else: the link
    goes, its target is not touched.

    A symlinked PARENT is the same escape one directory up, and `.claude`,
    `.config`, `.lean-ctx` or `.opencode` pointing into a dotfiles checkout
    is an ordinary setup, not a hostile tree. It is answered more narrowly
    on purpose: skipped WITH --force as well. Following it is the escape
    itself, and removing it would detach everything else the operator keeps
    behind that link -- more than `--force` asks for, which is to overwrite
    files that are already there. A skip is named in the report, so the
    gesture stays the operator's.

    Only the components below `root` are looked at. The root itself may
    legitimately sit under a symlinked path -- a linked home, a linked
    volume -- and walking past it would make `init` refuse to write
    anything at all in such a checkout.
    """
    parent = root
    for part in Path(relative).parts[:-1]:
        parent = parent / part
        if parent.is_symlink():
            return False
    target = root / relative
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
    except GitUnusable as exc:
        # BEFORE BusError, whose subclass it is: a git that cannot answer read
        # as `not_a_git_repo: run git init` sends the operator to the wrong repair.
        return {"ok": False, "error": f"init_stopped: {exc}"}
    except BusError:
        return {"ok": False, "error": "not_a_git_repo: run `git init` first"}

    written: list[str] = []
    skipped: list[str] = []
    try:
        for name, relative in LAYOUT.items():
            landed = _place(base, relative, TEMPLATES / name, force=force)
            (written if landed else skipped).append(relative)
    except OSError as exc:
        return {
            "ok": False,
            "error": f"init_stopped: {exc}",
            "root": str(base),
            "written": sorted(written),
            "skipped": sorted(skipped),
        }
    # ONE read, two readers below: the warning list and the warm-up
    # decision. `data` stays `{}` when the file is unreadable -- init has
    # already written its files at this point, and a config we cannot
    # parse is not a reason to lose that report.
    warnings: list[str] = []
    try:
        data = read_settings(base / SETTINGS_PATH)
        kind = settings_for("orchestrator", data).kind
        # `settings_for("orchestrator", ...)` reads two tables of four. The
        # other two are read anyway -- `[roles.builder]`/`[roles.reviewer]`
        # by `model_warnings` inside `_warnings` below, `[workspace]` by the
        # `up` and keystroke routes that run against this same file next.
        # Validating them HERE is what keeps the promise the except branch
        # makes: a config we cannot read costs the warm-up, not the
        # written/skipped report -- and `init` is the run that is supposed to
        # tell the operator the file is wrong, not the one that stays quiet
        # and lets `up` refuse it later. Both calls are free: they read
        # already-parsed tables and touch nothing.
        model_warnings(data)
        workspace_settings(data)
        # `[models]` is read here too, because `_warnings` acts on it: `auto`
        # decides whether the overlay's ignore rule is checked at all. Read
        # inside the guard and handed on as a plain bool -- a typo in it
        # costs the warm-up and that one check, never the report.
        overlay_auto = models_settings(data).auto
    except SettingsError as exc:
        # A config we cannot read is not a reason to fail `init` -- the files
        # are already written. It only means we cannot tell whether opencode
        # is the runtime here, so the warm-up is skipped and said so.
        warnings.append(f"no warm-up: {exc}")
        # Without a readable config nobody can say whether `auto` is on,
        # so the overlay's ignore rule is not checked either.
        data, kind, overlay_auto = {}, "", False
    warnings = _warnings(base, data=data, overlay_auto=overlay_auto, runner=runner) + warnings
    warmed = _warm_opencode(base, runner=runner) if kind == "opencode" else False
    return {
        "ok": True,
        "root": str(base),
        "written": sorted(written),
        "skipped": sorted(skipped),
        "warmed": warmed,
        "warnings": warnings,
    }
