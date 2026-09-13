"""Native session export → error object.

The only reliable place for 'did the turn fail?'. Herdr's
agent_status doesn't encode failure (H1).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

#: Keys under which the agents store their error object.
ERROR_KEYS = ("error", "lastError", "last_error")

#: opencode stores its sessions in exactly one SQLite file.
OPENCODE_DB = Path.home() / ".local" / "share" / "opencode" / "opencode.db"


def _format(err: dict[str, Any]) -> str:
    name = err.get("name") or err.get("type") or "error"
    raw = err.get("data")
    data: dict[str, Any] = raw if isinstance(raw, dict) else {}
    message = data.get("message") or err.get("message") or ""
    status = data.get("statusCode") or data.get("status_code") or err.get("statusCode")
    parts = [str(name)]
    if message:
        parts.append(str(message))
    text = ": ".join(parts)
    return f"{text} ({status})" if status else text


def find_error(export: Any) -> str | None:
    """First error object anywhere in the export, as plain text.

    Recursive, because the nesting differs by agent and version.
    An empty or null-valued error field counts as 'no error'.
    """
    if isinstance(export, dict):
        for key in ERROR_KEYS:
            err = export.get(key)
            if isinstance(err, dict) and err:
                return _format(err)
            if isinstance(err, str) and err.strip():
                return err.strip()
        for value in export.values():
            found = find_error(value)
            if found is not None:
                return found
        return None
    if isinstance(export, list):
        for item in export:
            found = find_error(item)
            if found is not None:
                return found
    return None


def session_id_from_agent_list(agent_list: Iterable[dict[str, Any]], name: str) -> str | None:
    """agent_session.value from `herdr agent list`.

    Never cache: the session ID changes on every /clear.
    """
    for entry in agent_list:
        if entry.get("name") != name:
            continue
        session = entry.get("agent_session")
        if isinstance(session, dict):
            value = session.get("value")
            return str(value) if value else None
        if isinstance(session, str) and session:
            return session
    return None


# -- The two stores --------------------------------------------------


def claude_session_path(session_id: str, project_root: str | Path) -> Path:
    """~/.claude/projects/<slug>/<session_id>.jsonl — slug = path with / → -."""
    slug = str(Path(project_root).resolve()).replace("/", "-")
    return Path.home() / ".claude" / "projects" / slug / f"{session_id}.jsonl"


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Read JSONL lines. If the file is missing or a line is broken: skip it."""
    try:
        raw = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines: list[dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            lines.append(data)
    return lines


def opencode_messages(session_id: str, db_path: str | Path | None = None) -> list[dict[str, Any]]:
    """message.data of this session from opencode's SQLite store.

    Read-only and `immutable=1`: opencode writes to the same file while
    we read — without these flags you'd risk `database is locked`.
    """
    path = Path(db_path) if db_path is not None else OPENCODE_DB
    if not path.is_file():
        return []
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True, timeout=2.0)
    except sqlite3.Error:
        return []
    try:
        rows = con.execute(
            "SELECT data FROM message WHERE session_id = ? ORDER BY time_created",
            (session_id,),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()
    messages: list[dict[str, Any]] = []
    for (raw,) in rows:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError, TypeError:
            continue
        if isinstance(data, dict):
            messages.append(data)
    return messages


def session_error(
    kind: str,
    session_id: str | None,
    project_root: str | Path,
    *,
    db_path: str | Path | None = None,
) -> str | None:
    """The error of this session, no matter which agent ran it.

    None means: no error found — even when the store is missing.
    The caller doesn't distinguish between the two, because both have the
    same consequence: there's no evidence of failure, so it stays `no_reply`.
    """
    if not session_id:
        return None
    if kind == "claude":
        return find_error(read_jsonl(claude_session_path(session_id, project_root)))
    if kind == "opencode":
        return find_error(opencode_messages(session_id, db_path))
    return None
