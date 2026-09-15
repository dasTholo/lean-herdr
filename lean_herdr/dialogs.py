"""Dialogs in worker panes: claude's folder trust, and a dialog named -- never answered.

A claude worker stops at the folder-trust dialog in every worktree of a
repository whose root claude does not trust, and a worktree inherits the
root's trust (measured 2026-09-15). So trust is granted once, by the human,
through `workspace init --trust-claude` (`trust_root`), and `workspace check`
names a root without it (`claude_trusts`). Every dialog that still appears
is reported with its text (`blocked_dialog`). Nothing here sends a key, a
prompt or any other input into a pane.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from lean_herdr.herdr import Herdr

#: Where claude keeps its global state, the folder trust per project path
#: included; `$CLAUDE_CONFIG_DIR` moves the file as it moves claude.
#: Measured 2026-09-15 against Claude Code 2.1.272.
CLAUDE_CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"
CLAUDE_STATE_FILE = ".claude.json"
TRUST_KEY = "hasTrustDialogAccepted"

#: At most this many screen lines travel in an `agent_blocked` answer.
DIALOG_LINES = 20

#: What `herdr agent list` says of an agent that waits for a human.
BLOCKED = "blocked"


def claude_state_path(environ: Mapping[str, str] | None = None) -> Path:
    """`$CLAUDE_CONFIG_DIR/.claude.json`, or `~/.claude.json` without the variable."""
    env = os.environ if environ is None else environ
    base = env.get(CLAUDE_CONFIG_DIR_ENV)
    return (Path(base) if base else Path.home()) / CLAUDE_STATE_FILE


def _read_state(path: Path) -> dict[str, Any] | None:
    """The state file as a JSON object -- None when it is missing, unreadable or no object."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return None
    return data if isinstance(data, dict) else None


def _key(root: Path) -> str | None:
    """The resolved root path, the key claude writes after the human's "Yes"."""
    try:
        return str(root.resolve())
    except OSError, RuntimeError:
        return None


def claude_trusts(root: Path, *, state: Path | None = None) -> bool | None:
    """Does claude trust `root`? None when its state cannot be read -- no verdict.

    Only the root's own key is asked. Whether claude counts a trusted parent
    directory is not measured, so a root below one gets a needless warning
    at worst, never a false all-clear.
    """
    data = _read_state(state if state is not None else claude_state_path())
    key = _key(root)
    if data is None or key is None:
        return None
    projects = data.get("projects")
    entry = projects.get(key) if isinstance(projects, dict) else None
    return isinstance(entry, dict) and entry.get(TRUST_KEY) is True


def _replace(path: Path, text: str) -> str:
    """`text` into `path` atomically and with the file's own mode: `written` or `failed: <why>`.

    A symlinked `path` is written through: the temp file lands beside the link's
    target and replaces the target, so the link stays a link.
    """
    try:
        path = path.resolve()
        mode = path.stat().st_mode & 0o7777
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.lean-herdr-")
    except (OSError, RuntimeError) as exc:
        return f"failed: {exc}"
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except OSError as exc:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        return f"failed: {exc}"
    return "written"


def trust_root(root: Path, *, state: Path | None = None) -> str:
    """Record the human's trust in `root`: `written`, `already` or `failed: <why>`.

    The gesture behind `workspace init --trust-claude`, and the same record
    claude writes when a human answers "Yes, I trust this folder" in the root.
    Exactly one key is set -- `projects.<root>.hasTrustDialogAccepted` -- and
    every other key stays as it was read. A missing file is not created: claude
    has not run under this config, and a file of lean-herdr's making would not
    be claude's. A claude session that is running may write its own copy back
    over this one; `workspace check` names the root again if it does. Never
    raises.
    """
    path = state if state is not None else claude_state_path()
    key = _key(root)
    if key is None:
        return f"failed: cannot resolve {root}"
    if not path.is_file():
        return f"failed: no claude state at {path} -- start claude once, then run this again"
    data = _read_state(path)
    if data is None:
        return f"failed: {path} holds no JSON object"
    projects = data.setdefault("projects", {})
    if not isinstance(projects, dict):
        return f"failed: {path} carries no projects table"
    entry = projects.get(key)
    if isinstance(entry, dict) and entry.get(TRUST_KEY) is True:
        return "already"
    projects[key] = {**(entry if isinstance(entry, dict) else {}), TRUST_KEY: True}
    return _replace(path, json.dumps(data, indent=2, ensure_ascii=False))


def dialog_text(herdr: Herdr, pane: str) -> str:
    """The last screen lines of a `blocked` pane, as an `agent_blocked` answer carries them.

    For a caller that already holds herdr's `blocked` verdict out of `agent list`;
    `blocked_dialog` asks for that verdict first. Reads only.
    """
    text = herdr.agent_read(pane, lines=DIALOG_LINES)
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines[-DIALOG_LINES:]) or "(herdr returned no screen text)"


def blocked_dialog(herdr: Herdr, *, pane: str | None = None, name: str | None = None) -> str | None:
    """The last screen lines of an agent that waits for a human -- None for every other state.

    Found by `pane` at the start, where the pane is all there is, and by `name`
    while waiting, where the order names the worker. `blocked` is herdr's own
    verdict (`agent list`); the text comes from `agent read --source detection`,
    the snapshot that verdict was made on. Reads only: the dialog is reported,
    never answered.
    """
    if pane is None and name is None:
        return None
    for agent in herdr.agent_list():
        hit = agent.get("pane_id") == pane if pane is not None else agent.get("name") == name
        if not hit:
            continue
        if agent.get("agent_status") != BLOCKED:
            return None
        return dialog_text(herdr, str(agent.get("pane_id") or pane or ""))
    return None
