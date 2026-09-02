"""Bus access: canonical project root and messages from registry.json.

The two truths shared by `bin/herdr-dispatch` and the plugin handlers.
Both exist exactly once, because otherwise both sides would get them
wrong in different ways.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

GIT_TIMEOUT_S = 5.0


class BusError(RuntimeError):
    """The bus is unreadable — never silently treat this as success."""


def canonical_root(cwd: str | Path | None = None) -> Path:
    """Repo root of a checkout, even from inside a linked worktree.

    `git rev-parse --git-common-dir` points from any worktree at the `.git`
    of the main checkout; its parent directory is the root that
    lean-ctx canonicalizes a stdio server to anyway. Every
    `--project-root` value in the project comes from this function — never from
    $PWD, never from a worktree path (B12).
    """
    proc = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_S,
        check=False,
    )
    if proc.returncode != 0:
        raise BusError(f"git rev-parse --git-common-dir failed: {proc.stderr.strip()}")
    common = Path(proc.stdout.strip())
    if not common.is_absolute():
        base = Path(cwd) if cwd is not None else Path.cwd()
        common = base / common
    return common.resolve().parent


REGISTRY_PATH = Path.home() / ".local" / "share" / "lean-ctx" / "agents" / "registry.json"

#: Top-level key under which lean-ctx stores the bus messages.
#: Verified against a real registry.json (2026-09-01) — not "messages".
MESSAGES_KEY = "scratchpad"

#: lean-ctx writes NINE fractional digits; fromisoformat tolerates at most
#: six and otherwise raises ValueError. Measured: 2026-08-01T15:10:08.404790674Z.
_NANOSECONDS = re.compile(r"(\.\d{6})\d+")


def parse_time(text: str | None) -> datetime | None:
    """RFC-3339 timestamp → aware datetime. Unreadable input becomes None.

    Here, None explicitly means 'unknown' — not 'now' and not
    'expired' — an unreadable timestamp must never drop a message.
    """
    if not text:
        return None
    normal = _NANOSECONDS.sub(r"\1", str(text).replace("Z", "+00:00"))
    try:
        value = datetime.fromisoformat(normal)
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


@dataclass(frozen=True)
class BusMessage:
    """A bus message, as registry.json carries it."""

    id: str
    from_agent: str
    to_agent: str | None
    task_id: str | None
    category: str
    priority: str
    privacy: str
    message: str
    metadata: dict[str, Any]
    project_root: str | None
    timestamp: str
    read_by: tuple[str, ...]
    expires_at: str | None

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> BusMessage:
        return cls(
            id=str(raw.get("id", "")),
            from_agent=str(raw.get("from_agent", "")),
            to_agent=raw.get("to_agent"),
            task_id=raw.get("task_id"),
            category=str(raw.get("category", "")),
            priority=str(raw.get("priority", "")),
            privacy=str(raw.get("privacy", "")),
            message=str(raw.get("message", "")),
            metadata=raw.get("metadata") or {},
            project_root=raw.get("project_root"),
            timestamp=str(raw.get("timestamp", "")),
            read_by=tuple(raw.get("read_by") or ()),
            expires_at=raw.get("expires_at"),
        )

    def is_expired(self, now: datetime) -> bool:
        """Expired? Missing or unreadable expires_at: no.

        The 12-hour TTL exists only in the documentation; in practice the field
        is usually null. If it's missing, the message is valid indefinitely — but if
        it holds a past time, the message is dead and must not pass as a
        current result.
        """
        deadline = parse_time(self.expires_at)
        return deadline is not None and deadline <= now


def read_registry(path: str | Path | None = None) -> dict[str, Any]:
    """Load registry.json. If it's missing or broken: BusError.

    Never success through silence — an empty result and an unreadable bus
    are two different things.
    """
    p = Path(path) if path is not None else REGISTRY_PATH
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise BusError(f"registry unreadable at {p}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BusError(f"registry malformed at {p}: {exc}") from exc
    if not isinstance(data, dict):
        raise BusError(f"registry has unexpected shape at {p}: {type(data).__name__}")
    return data


def parse_registry(
    data: dict[str, Any],
    *,
    project_root: str | Path,
    task_id: str | None = None,
    from_agent: str | None = None,
    now: datetime | None = None,
) -> list[BusMessage]:
    """Bus messages for this project, optionally filtered by task and sender.

    `project_root` is a canonicalization result (canonical_root()), not $PWD.
    Messages without `project_root` are kept (lean-ctx doesn't always set the
    field); messages from a foreign root never are. Expired ones are dropped;
    `now` is injectable so the test doesn't need a clock.
    """
    if MESSAGES_KEY not in data:
        raise BusError(
            f"registry has no key {MESSAGES_KEY!r} — "
            f"format changed? present: {sorted(data)}"
        )
    wanted = str(Path(project_root).resolve())
    effective_now = now if now is not None else datetime.now(UTC)
    out: list[BusMessage] = []
    for raw in data[MESSAGES_KEY] or ():
        if not isinstance(raw, dict):
            continue
        msg = BusMessage.from_raw(raw)
        if msg.project_root is not None and msg.project_root != wanted:
            continue
        if msg.is_expired(effective_now):
            continue
        if task_id is not None and msg.task_id != task_id:
            continue
        if from_agent is not None and msg.from_agent != from_agent:
            continue
        out.append(msg)
    return out


def agents_in_registry(data: dict[str, Any]) -> list[dict[str, Any]]:
    """The registered agents — source for the PID join (Task 3)."""
    return [a for a in (data.get("agents") or ()) if isinstance(a, dict)]
