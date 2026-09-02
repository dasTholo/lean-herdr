"""Read-only access to the A2A task store of lean-ctx.

The counterpart to bus.py for the work-order path. This file NEVER WRITES.
Creating a task or changing its state is reserved for a registered,
long-lived MCP agent via `ctx_call(name="ctx_task", ...)`; a CLI process has
no identity (`cli/call_cmd.rs:160` leaves `agent_id` at `None`) and is
turned away with `agent must be registered first`. Reading is open to any
process -- which is why the wait mode reads the file directly instead of
going through `lean-ctx call` (same rule as B9 on the bus).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class TaskError(RuntimeError):
    """The task store is unreadable -- never let that pass as 'nothing to do'."""


#: States after which no further change arrives (core/a2a/task.rs:42).
TERMINAL_STATES = frozenset({"completed", "failed", "canceled"})

#: tasks.json carries the Rust enum VARIANTS, not the CLI names. Measured on
#: a real file: "state": "Created". `TaskState` has no serde(rename)
#: (core/a2a/task.rs:6); the lowercase names come solely from the Display
#: impl (:16) that the CLI and the tool description use.
_STATE_NAMES = {
    "Created": "created",
    "Working": "working",
    "InputRequired": "input-required",
    "Completed": "completed",
    "Failed": "failed",
    "Canceled": "canceled",
}

#: Markers of a legacy or mixed install whose data directory is not split
#: along XDG lines (core/data_dir.rs:10).
_DATA_MARKERS = ("stats.json", "sessions", "vectors", "graphs", "knowledge")


def normalize_state(raw: Any) -> str:
    """Enum variant -> CLI name. Anything unknown is kept verbatim.

    An unknown state must never become terminal: otherwise a format change
    in lean-ctx would turn the wait mode into a false success. This way it
    runs into the timeout -- visible, and without lying.
    """
    text = str(raw or "")
    return _STATE_NAMES.get(text, text)


def is_terminal(state: str) -> bool:
    return state in TERMINAL_STATES


@dataclass(frozen=True)
class Task:
    """One task, exactly as tasks.json carries it."""

    id: str
    from_agent: str
    to_agent: str
    state: str
    description: str
    messages: tuple[dict[str, Any], ...]
    created_at: str
    updated_at: str

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> Task:
        return cls(
            id=str(raw.get("id", "")),
            from_agent=str(raw.get("from_agent", "")),
            to_agent=str(raw.get("to_agent", "")),
            state=normalize_state(raw.get("state")),
            description=str(raw.get("description", "")),
            messages=tuple(
                m for m in (raw.get("messages") or ()) if isinstance(m, dict)
            ),
            created_at=str(raw.get("created_at", "")),
            updated_at=str(raw.get("updated_at", "")),
        )


def _has_data(directory: Path) -> bool:
    """A marker counts only when it carries data (core/data_dir.rs:104-114, GL #623/#625).

    An empty legacy directory does not count. Concretely: an empty marker
    FILE (size 0) does not count, and a marker DIRECTORY with no entries
    does not count either. Otherwise an empty ~/.lean-ctx created by setup
    would split the store: lean-ctx would write to XDG while we read next
    to it. A missing or unreadable marker does not count and does not stop
    the scan of the remaining markers.
    """
    for marker in _DATA_MARKERS:
        path = directory / marker
        try:
            if path.is_dir():
                if next(path.iterdir(), None) is not None:
                    return True
            elif path.stat().st_size > 0:
                return True
        except OSError:
            continue
    return False


def _data_dir() -> Path:
    """lean_ctx_data_dir() rebuilt, same precedence (core/data_dir.rs:12).

    Rebuilt rather than queried: `lean-ctx call` never prints the path, and
    a second process start per poll would eat exactly the saving for which
    the wait mode reads the file in the first place.
    """
    override = os.environ.get("LEAN_CTX_DATA_DIR", "").strip()
    if override:
        return Path(override)
    legacy = Path.home() / ".lean-ctx"
    if _has_data(legacy):
        return legacy
    cfg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    mixed = (Path(cfg) if cfg else Path.home() / ".config") / "lean-ctx"
    if _has_data(mixed):
        return mixed
    data = os.environ.get("XDG_DATA_HOME", "").strip()
    base = Path(data) if data else Path.home() / ".local" / "share"
    return base / "lean-ctx"


def task_store_path() -> Path:
    """`$LEAN_CTX_DATA_DIR` before XDG, then `agents/tasks.json`."""
    return _data_dir() / "agents" / "tasks.json"


def read_tasks(path: str | Path | None = None) -> list[Task]:
    """Every task in the store, unfiltered.

    Missing file: empty list -- before the first task it simply does not
    exist. Unreadable or broken file: TaskError. That difference is the
    point: a destroyed store must never look like 'nothing to do'.

    No filtering by project, because `Task` has no project_root field
    (core/a2a/task.rs:100) -- the mapping runs through the unique task_id.
    A half-written store is impossible: TaskStore::save() writes tasks.tmp
    and renames it into place (:213).
    """
    p = Path(path) if path is not None else task_store_path()
    try:
        raw = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise TaskError(f"task store unreadable at {p}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TaskError(f"task store malformed at {p}: {exc}") from exc
    if not isinstance(data, dict) or "tasks" not in data:
        seen = sorted(data) if isinstance(data, dict) else type(data).__name__
        raise TaskError(
            f"task store has no 'tasks' key at {p} -- "
            f"format changed? present: {seen}"
        )
    return [Task.from_raw(r) for r in (data["tasks"] or ()) if isinstance(r, dict)]


def find_task(tasks: list[Task], task_id: str) -> Task | None:
    """The one and only lookup path of the wait mode.

    There is deliberately no filter by agent_id: it would have no caller in
    this plan. Should the stage-5 plugin later need an agent's view, it gets
    one there.
    """
    return next((t for t in tasks if t.id == task_id), None)


def message_from(task: Task, agent: str) -> str | None:
    """Newest message from that sender, as text -- otherwise None.

    `ctx_task update` appends the given message with `role=<agent_id>`
    (tools/ctx_task.rs, handle_update). The FIRST message of a task carries
    the creator's role instead and is only the description: blindly taking
    the last one would hand our own order back as the worker's answer
    whenever the worker completes without words.
    """
    for message in reversed(task.messages):
        if str(message.get("role", "")) != agent:
            continue
        text = "\n".join(
            str(part.get("text", ""))
            for part in (message.get("parts") or ())
            if isinstance(part, dict) and part.get("type") == "text"
        ).strip()
        if text:
            return text
    return None
