"""`lean-herdr workspace check` -- will `up` and `dispatch` run here, and what gets worse?

One JSON line, and nothing else happens: no start, no write, no fetch, no
warm-up. `errors` are what makes `up` or `dispatch` fail right now; `warnings`
are what still runs, only worse -- a gate worktrunk skips, commit messages out
of file names, a snapshot shadowed by a venv. Every line names the next step.

Every foreign command here only READS, bounded by CHECK_TIMEOUT_S, and a binary
that is not on the PATH gives no verdict rather than a guessed one. `init`
reports the same machine through the same producer -- `machine_report` is
imported there, never rebuilt (one producer per rule, M3). Granting a
machine-wide permission stays a gesture of the human at the keyboard: nothing
here runs `lean-ctx allow`, `wt config approvals add` or `herdr plugin link`.
"""

from __future__ import annotations

import importlib.metadata
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import lean_herdr
from lean_herdr.bus import BusError, GitUnusable, canonical_root
from lean_herdr.settings import (
    OVERLAY_PATH,
    SETTINGS_PATH,
    OverlayError,
    SettingsError,
    llm_settings_layered,
    model_warnings,
    models_settings,
    read_settings,
    settings_for,
    workspace_settings,
)
from lean_herdr.templating import (
    LAYOUT,
    LOCK_PATH,
    LockError,
    blocked,
    file_state,
    read_lock,
    render,
    resolve_values,
    state_warnings,
)
from lean_herdr.workspace import INIT_HINT, missing_agent_config

#: The binaries a lean-herdr project leans on, and what each one is for.
BINARIES = (
    ("herdr", "panes, agents and workspaces"),
    ("wt", "one worktree per branch, merge and cleanup"),
    ("lean-ctx", "agent bus, project memory, tool profiles"),
)

#: The tables `up` and `dispatch` read roles out of.
ROLES = ("default", "orchestrator", "builder", "reviewer")

#: What worktrunk's `commit.generation.command` has to start with. Flags behind
#: it are the operator's.
GENERATOR = ("lean-herdr", "llm", "generate")

PLUGIN_ID = "lean.herdr"

#: `herdr plugin list` has no JSON; the plugin's line ends in `[local:<path>]`.
_LOCAL = re.compile(r"\[local:([^\]]+)\]")

#: `lean.herdr` as a whole name, never a piece of a longer plugin id.
_OWN = re.compile(rf"(?<![\w.-]){re.escape(PLUGIN_ID)}(?![\w.-])")

#: A read-only check must not hold up the whole call.
CHECK_TIMEOUT_S = 10.0


def _run(
    runner: Any, *cmd: str, cwd: Path | None = None
) -> subprocess.CompletedProcess[str] | None:
    """One read-only foreign command, run to its end. None when it cannot run at all.

    `errors="replace"`: a reply in bytes no codec takes still comes back, and
    the check reading it reports an unreadable answer -- a None here would be
    read as no verdict, i.e. green. ValueError is the belt for a runner that
    decodes strictly anyway.
    """
    if shutil.which(cmd[0]) is None:
        return None
    try:
        return runner(
            list(cmd),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=CHECK_TIMEOUT_S,
            cwd=None if cwd is None else str(cwd),
            check=False,
        )
    except OSError, subprocess.SubprocessError, ValueError:
        return None


def _read(runner: Any, *cmd: str, cwd: Path | None = None) -> str | None:
    """stdout AND stderr of `_run`. None when it cannot run at all.

    Both, because `wt` writes its warnings to stderr and a check that
    ignored them would report a green state over a complaint.
    """
    proc = _run(runner, *cmd, cwd=cwd)
    if proc is None:
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

    Neither `init` nor `check` appends the line itself. A `.gitignore` belongs
    to the project, and lean-herdr writes only its own files -- the operator
    gets the exact line and decides.
    """
    proc = _run(runner, "git", "check-ignore", "-v", str(OVERLAY_PATH), cwd=root)
    if proc is None or proc.returncode != 1:
        # None: no git at all. 0: git named the rule that covers it. 1 is the
        # one "not ignored" -- with a warning on stderr as well, at times, so
        # the output decides nothing. Anything else (128, `fatal:`) is no verdict.
        return None
    return (
        f"[models].auto is on and git does not ignore {OVERLAY_PATH} -- "
        "it is machine-local and must not be shared. Add to .gitignore: "
        f"{OVERLAY_PATH}"
    )


#: The ignore line the temp files of the whole-file writers under
#: `.lean-ctx/lean-herdr/` need. Their names change on every run, so no
#: line naming one of them could ever cover the next.
TEMP_IGNORE = ".lean-ctx/lean-herdr/.tmp-*"

#: One name each writer could draw -- the overlay's and the lock's. `git
#: check-ignore` matches patterns and needs no file on disk, so a probe stands
#: for every name `mkstemp` picks, and a rule narrower than TEMP_IGNORE that
#: covers one writer's names shows up on the other writer's probe.
TEMP_PROBE = OVERLAY_PATH.parent / ".tmp-models.auto.toml.probe"
LOCK_TEMP_PROBE = LOCK_PATH.parent / ".tmp-templates.lock.json.probe"


def _check_temp_ignored(root: Path, runner: Any) -> str | None:
    """git does not ignore the writers' temp files. Asked always, never behind `auto`.

    One call per probe, never one shared with `_check_overlay_ignored` or with
    each other: a single `check-ignore` over several paths succeeds as soon as
    ONE of them is covered -- and a rule for one path would then pass for all.
    """
    for probe in (TEMP_PROBE, LOCK_TEMP_PROBE):
        proc = _run(runner, "git", "check-ignore", "-v", str(probe), cwd=root)
        if proc is not None and proc.returncode == 1:
            return (
                f"git does not ignore {TEMP_IGNORE} (probed with {probe}) -- a writer killed "
                "mid-run leaves a temp file there that would show up in git status. Add to "
                f".gitignore: {TEMP_IGNORE}"
            )
    return None


def _dig(data: Any, *keys: str) -> Any:
    """`data[k1][k2]...`, or None as soon as a level is not a dict."""
    for key in keys:
        data = data.get(key) if isinstance(data, dict) else None
    return data


def _check_generator(root: Path | None, runner: Any) -> str | None:
    """worktrunk's effective `commit.generation.command`, user config before system.

    `wt config show --format json` names both levels with `path`, `exists` and
    `config`. `_read` appends stderr, and wt writes its warnings there -- after
    the JSON -- so the object is decoded from the first brace and whatever
    follows it is ignored.
    """
    reply = _read(runner, "wt", "config", "show", "--format", "json", cwd=root)
    if reply is None:
        return None
    start = reply.find("{")
    try:
        shown = json.JSONDecoder().raw_decode(reply[start:])[0] if start >= 0 else None
    except json.JSONDecodeError:
        shown = None
    if not isinstance(shown, dict):
        return (
            "wt config show --format json gave no readable answer -- whether commits "
            "get their message from `lean-herdr llm generate` is unknown"
        )
    command = ""
    for level in ("user", "system"):
        found = _dig(shown, level, "config", "commit", "generation", "command")
        if isinstance(found, str) and found:
            command = found
            break
    if not command:
        return (
            "worktrunk has no commit.generation.command -- commits fall back to file "
            "names. Add to ~/.config/worktrunk/config.toml: [commit.generation] "
            'command = "lean-herdr llm generate"'
        )
    try:
        words = shlex.split(command)
    except ValueError:
        words = []
    if tuple(words[: len(GENERATOR)]) == GENERATOR:
        return None
    return (
        f"commit.generation.command is {command!r}, not `lean-herdr llm generate` -- "
        "the installed snapshot does not write the commit messages"
    )


def _direct_url() -> str | None:
    """`direct_url.json` of the installed distribution, or None."""
    try:
        return importlib.metadata.distribution("lean-herdr").read_text("direct_url.json")
    except importlib.metadata.PackageNotFoundError:
        return None


def install_report(
    *,
    prefix: Path | None = None,
    package: Path | None = None,
    which: Callable[[str], str | None] = shutil.which,
    direct_url: Callable[[], str | None] = _direct_url,
    environ: Mapping[str, str] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Where this `lean-herdr` runs from, and what shadows it. Pure reads.

    Every seam defaults to the running process; the tests hand in a prepared
    prefix. `resolve()` on both sides is not optional: `~/.local/bin/lean-herdr`
    is a symlink into the tool venv (measured), and without it every correct
    install would warn. `uv-receipt.toml` is a uv detail -- should it change,
    this says "no tool venv" wrongly, and only ever as a warning.
    """
    base = Path(sys.prefix if prefix is None else prefix).resolve()
    here = Path(lean_herdr.__file__ if package is None else package).resolve().parent
    env = os.environ if environ is None else environ
    found = which("lean-herdr")
    binary = Path(found).resolve() if found else None
    try:
        record = json.loads(direct_url() or "{}")
    except json.JSONDecodeError:
        record = {}
    tool = (base / "uv-receipt.toml").is_file()
    editable = bool(_dig(record, "dir_info", "editable"))
    install: dict[str, Any] = {
        "tool": tool,
        "editable": editable,
        "package": str(here),
        "binary": None if binary is None else str(binary),
        "plugin": None,
    }
    lines: list[str] = []
    if not tool:
        lines.append(
            f"{base} is no uv tool venv (no uv-receipt.toml) -- this lean-herdr is not "
            "the installed snapshot; see README, Updating"
        )
    if editable:
        lines.append(
            "lean-herdr is installed editable -- every project runs whatever branch the "
            "checkout has; reinstall the snapshot from main, see README, Updating"
        )
    if not here.is_relative_to(base):
        shadow = env.get("PYTHONPATH")
        cause = (
            f"PYTHONPATH={shadow} shadows the snapshot"
            if shadow
            else "a checkout or a venv on sys.path shadows the snapshot"
        )
        lines.append(f"lean_herdr is imported from {here}, outside {base} -- {cause}")
    if binary is None:
        lines.append("lean-herdr is not on PATH -- agents, hooks and worktrunk cannot run it")
    elif not binary.is_relative_to(base):
        lines.append(
            f"`lean-herdr` on PATH resolves to {binary}, outside {base} -- an activated "
            "venv comes first on PATH and shadows the snapshot"
        )
    return install, lines


def _linked_plugin(runner: Any, expected: Path) -> tuple[str | None, str | None]:
    """(the path Herdr links `lean.herdr` to, a warning). (None, None): no herdr.

    Only a `[local:...]` behind `lean.herdr` on the same line counts -- another
    plugin's path is not this one's -- and both sides are compared resolved:
    the same folder reached through a symlink is the same manifest.
    """
    listing = _read(runner, "herdr", "plugin", "list", "--plugin", PLUGIN_ID)
    if listing is None:
        return None, None
    linked = None
    for line in listing.splitlines():
        hit = _LOCAL.search(line)
        if hit and _OWN.search(line, 0, hit.start()):
            linked = hit.group(1)
            break
    if linked is not None and Path(linked).resolve() == expected.resolve():
        return linked, None
    return linked, (
        f"herdr links {PLUGIN_ID} to {linked or 'no local path'}, not to this snapshot's "
        f"manifest -- herdr plugin unlink {PLUGIN_ID}, then: herdr plugin link {expected}"
    )


def _check_temp_leftovers(root: Path) -> str | None:
    """Temp files a killed `models` or `init` run left in `.lean-ctx/lean-herdr/`.

    Not behind a symlink: no writer here ever leaves a file in a linked folder.
    """
    if blocked(root, OVERLAY_PATH.parent):
        return None
    folder = root / OVERLAY_PATH.parent
    left = sorted(path.name for path in folder.glob(".tmp-*"))
    if not left:
        return None
    return (
        f"{folder} holds temp files a killed writer left behind: {', '.join(left)} -- "
        "delete them once no `models` or `init` run is active"
    )


def machine_report(
    root: Path | None,
    *,
    data: dict[str, Any],
    overlay_auto: bool,
    runner: Any = subprocess.run,
) -> tuple[dict[str, Any], list[str]]:
    """The install facts and every machine warning -- the producer `init` and `check` share.

    `root=None` is a directory that is no repository: the checks that ask about
    a project -- approvals, ignore rules, leftovers -- have nothing to ask.
    `data` is config.toml already read and valid, `{}` otherwise.
    """
    found = [
        f"{binary} is not on PATH -- needed for {why}"
        for binary, why in BINARIES
        if shutil.which(binary) is None
    ]
    install, install_lines = install_report()
    found.extend(install_lines)
    install["plugin"], plugin_line = _linked_plugin(runner, Path(install["package"]) / "plugin")
    checks = [
        _check_allowlist(runner),
        _check_plugins(runner),
        plugin_line,
        _check_generator(root, runner),
    ]
    if root is not None:
        checks += [
            _check_approvals(root, runner),
            # Guarded by the config: without `[models].auto` no overlay is written.
            _check_overlay_ignored(root, runner) if overlay_auto else None,
            # NOT guarded: the template lock is written in every project.
            _check_temp_ignored(root, runner),
            _check_temp_leftovers(root),
        ]
    found.extend(line for line in checks if line is not None)
    found.extend(model_warnings(data))
    return install, found


def _config_errors(root: Path) -> tuple[list[str], dict[str, Any], bool]:
    """What stops `up` or `dispatch` here right now, plus the config the warnings read."""
    errors: list[str] = []
    data: dict[str, Any] = {}
    auto = False
    path = root / SETTINGS_PATH
    if not path.is_file():
        errors.append(f"not_initialised: {SETTINGS_PATH} is missing -- {INIT_HINT}")
    else:
        try:
            data = read_settings(path)
            for role in ROLES:
                settings_for(role, data)
            workspace_settings(data)
            auto = models_settings(data).auto
            llm_settings_layered(root, data)
        except OverlayError as exc:
            # config.toml itself is fine; `dispatch --await` refuses the overlay.
            errors.append(f"config_error: {exc}")
        except SettingsError as exc:
            errors.append(f"config_error: {exc}")
            data, auto = {}, False
    problem = missing_agent_config(root, settings_for("orchestrator", data).kind)
    if problem:
        errors.append(f"no_agent_config: {problem} -- {INIT_HINT}")
    return errors, data, auto


def _template_report(root: Path) -> tuple[dict[str, str], list[str]]:
    """Every template's state, and the lines it earns. A broken lock guesses nothing.

    Nor is a lock behind a symlink read -- `init` never writes it there -- and
    every state is then judged as if there were no lock.
    """
    lock: dict[str, dict[str, str]] = {"values": {}, "files": {}}
    lock_state: dict[str, str] = {}
    if blocked(root, LOCK_PATH):
        lock_state = {str(LOCK_PATH): "blocked"}
    else:
        try:
            lock = read_lock(root)
        except LockError as exc:
            return {}, [f"lock_malformed: {exc} -- fix or delete it; no template state is guessed"]
    values = resolve_values(lock["values"])
    templates: dict[str, str] = {}
    unreadable: list[str] = []
    for name, relative in LAYOUT.items():
        try:
            templates[relative] = file_state(
                root, relative, rendered=render(name, values), locked=lock["files"].get(relative)
            )
        except OSError as exc:
            unreadable.append(f"{relative} cannot be read: {exc}")
    return templates, state_warnings({**templates, **lock_state}) + unreadable


def _unrooted(error: str, runner: Any) -> dict[str, Any]:
    """The answer without a root: one error, and only what needs no project is asked."""
    install, warnings = machine_report(None, data={}, overlay_auto=False, runner=runner)
    return {
        "ok": False,
        "errors": [error],
        "warnings": warnings,
        "install": install,
        "templates": {},
    }


def workspace_check(*, root: Path | None = None, runner: Any = subprocess.run) -> dict[str, Any]:
    """Will `up` and `dispatch` run here, and where does it get quietly worse?

    Never raises; starts, writes and fetches nothing. `ok` is the absence of
    `errors`. Outside a repository the answer carries no `root`, and nothing
    that needs one is asked.
    """
    try:
        base = root if root is not None else canonical_root()
    except GitUnusable as exc:
        # BEFORE BusError, whose subclass it is: a git that is missing or hung
        # is not a directory outside a repository, and needs another repair.
        return _unrooted(f"{exc} -- check that git is installed and on PATH", runner)
    except BusError as exc:
        return _unrooted(f"{exc} -- run this inside a git repository", runner)
    errors, data, auto = _config_errors(base)
    install, warnings = machine_report(base, data=data, overlay_auto=auto, runner=runner)
    templates, template_lines = _template_report(base)
    return {
        "ok": not errors,
        "root": str(base),
        "errors": errors,
        "warnings": warnings + template_lines,
        "install": install,
        "templates": templates,
    }
