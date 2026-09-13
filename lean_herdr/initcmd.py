"""`lean-herdr workspace init` -- write the templates, report the rest.

Two rules run through everything here.

The first: an existing file is NEVER overwritten without --force -- or
without --update, and then only when the lock proves nobody touched it
since init wrote it. A
stranger's `opencode.jsonc` or `.claude/settings.json` flattened in
silence would be the most expensive mistake this tool could make. Skipped
files are named in the result, so nobody has to guess what happened.

The second: preconditions are REPORTED, never repaired. The warnings come
out of `checkcmd.machine_report`, the producer `workspace check` uses too,
and every foreign command it runs only READS. `init` runs no `lean-ctx
allow`, no `wt config approvals add` and no `herdr plugin link`: granting a
machine-wide permission is a gesture that belongs to the human at the
keyboard. The ONE exception is the warm-up (`_warm_opencode`), and it stays
inside the rule's intent: it changes nothing on the machine, only opencode's
own cache for this project, and it is aborted on purpose.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from lean_herdr.bus import BusError, GitUnusable, canonical_root
from lean_herdr.checkcmd import machine_report
from lean_herdr.settings import (
    SETTINGS_PATH,
    SettingsError,
    model_warnings,
    models_settings,
    read_settings,
    settings_for,
    workspace_settings,
)
from lean_herdr.templating import (
    LAYOUT,
    LOCK_PATH,
    VALUE_RE,
    LockError,
    blocked,
    digest,
    file_state,
    read_lock,
    render,
    resolve_values,
    state_warnings,
    write_lock,
)
from lean_herdr.workspace import OPENCODE_ORCHESTRATOR

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


def _place(root: Path, relative: str, data: bytes, *, force: bool) -> bool:
    """Write one rendered template. True when it landed, False when it was skipped.

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
    target.write_bytes(data)
    return True


def _lay_templates(
    base: Path, values: dict[str, str], files: dict[str, str], *, force: bool, update: bool
) -> tuple[list[str], list[str], dict[str, str], dict[str, str], OSError | None]:
    """Render, judge and place every template: (written, skipped, templates, files, stopped).

    `files` comes back as a new dict -- a fresh digest for every file that
    ended `current`, every other entry as it was. `stopped` is the OSError a
    hostile or half-built tree raised mid-loop, None otherwise; the lists
    then hold what happened up to that file, so the caller keeps its report.
    """
    written: list[str] = []
    skipped: list[str] = []
    templates: dict[str, str] = {}
    entries = dict(files)
    try:
        for name, relative in LAYOUT.items():
            data = render(name, values)
            state = file_state(base, relative, rendered=data, locked=entries.get(relative))
            wanted = force or state == "missing" or (update and state == "outdated")
            if wanted and _place(base, relative, data, force=force or update):
                written.append(relative)
                state = "current"
            else:
                skipped.append(relative)
            if state == "current":
                entries[relative] = digest(data)
            templates[relative] = state
    except OSError as exc:
        return written, skipped, templates, entries, exc
    return written, skipped, templates, entries, None


def workspace_init(
    *,
    root: Path | None = None,
    force: bool = False,
    update: bool = False,
    test: str | None = None,
    lint: str | None = None,
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    """Write the templates into this project, and lock what landed. Never raises.

    No git repository: a hard stop with a named next step. `init` does not
    run `git init` itself -- that is a gesture belonging to the human.

    A tree that is hostile or half-built -- a dead symlink at a template's
    place, a regular file where a directory belongs, a directory nobody may
    write -- ends the run early with `init_stopped` and the report so far.
    Letting the exception through would take the written/skipped list with
    it, and nobody could then say which files already landed.

    Three modes. Without a flag only `missing` files are written. `--update`
    also rewrites `outdated` ones -- untouched since init wrote them, so no
    hand edit is lost. `--force` writes everything but through a symlinked
    parent. The lock records the resolved values and, per file, the sha256 of
    what this run wrote or found `current`; every other entry stays as it
    was, or a later `--update` could no longer tell an untouched file from an
    edited one.
    """
    if force and update:
        return {"ok": False, "error": "usage_error: --force and --update exclude each other"}
    for flag, value in (("--test", test), ("--lint", lint)):
        if value is not None and not VALUE_RE.match(value):
            return {
                "ok": False,
                "error": (
                    f"usage_error: {flag} {value!r} -- letters, digits, spaces and "
                    "._/=+,@- only, starting with a letter or digit, no trailing space"
                ),
            }
    try:
        base = root if root is not None else canonical_root()
    except GitUnusable as exc:
        # BEFORE BusError, whose subclass it is: a git that cannot answer read
        # as `not_a_git_repo: run git init` sends the operator to the wrong repair.
        return {"ok": False, "error": f"init_stopped: {exc}"}
    except BusError:
        return {"ok": False, "error": "not_a_git_repo: run `git init` first"}

    # A symlink on the lock's way is the escape `_place` refuses for a template:
    # the lock is then neither read nor written, the values come from the flags
    # and the defaults, and the warnings name it.
    lock_blocked = blocked(base, LOCK_PATH)
    lock: dict[str, dict[str, str]] = {"values": {}, "files": {}}
    if not lock_blocked:
        try:
            lock = read_lock(base)
        except LockError as exc:
            return {
                "ok": False,
                "error": f"lock_malformed: {exc} -- fix or delete it",
                "root": str(base),
            }
    values = resolve_values(lock["values"], test=test, lint=lint)
    written, skipped, templates, files, stopped = _lay_templates(
        base, values, lock["files"], force=force, update=update
    )
    if stopped is None and not lock_blocked:
        try:
            write_lock(base, values=values, files=files)
        except OSError as exc:
            stopped = exc
    if stopped is not None:
        return {
            "ok": False,
            "error": f"init_stopped: {stopped}",
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
    _install, found = machine_report(base, data=data, overlay_auto=overlay_auto, runner=runner)
    lock_state = {str(LOCK_PATH): "blocked"} if lock_blocked else {}
    warnings = found + state_warnings({**templates, **lock_state}) + warnings
    warmed = _warm_opencode(base, runner=runner) if kind == "opencode" else False
    return {
        "ok": True,
        "root": str(base),
        "written": sorted(written),
        "skipped": sorted(skipped),
        "values": values,
        "templates": templates,
        "warmed": warmed,
        "warnings": warnings,
    }
