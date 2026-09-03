"""The order log: append-only, hash-chained, one JSON file per event.

The counterpart to bus.py for the work-order path -- but this one WRITES.
That is the whole point. `ctx_task` reserved every write for a registered,
long-lived MCP agent (`tools/ctx_task.rs:12`), so the orchestrator had to
be one and the write path could not be unit-tested. A file of our own has
no such rule: every process writes, and creating an order is a script call.

This module knows nothing about ORDERS, only about EVENTS. What a sequence
of events means lives in lean_herdr/orders.py, and that module never
touches a file. The cut is what makes fold() a pure function.

`os.fsync` is deliberately absent: a work-order log on a developer's
machine does not have to harden against power loss. The atomic rename is
`Path.replace()`, the same call as `os.replace` in the API the rest of the
tree uses; the only `os` grip left here is `os.environ`, inherited with the
data-directory precedence from the tasks.py this module replaces.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lean_herdr.bus import canonical_root


class OrderLogError(RuntimeError):
    """The log is unreadable or broken -- never let that pass as 'nothing to do'.

    The same rule read_tasks() held for the task store: a destroyed log
    must not look like an empty one.
    """


#: Written into every event and checked on every read. A different value is
#: a format this reader does not understand -- an error, not a shrug.
SCHEMA_VERSION = "lean-herdr.order-event/v1"

#: `orders/<task_id>/events/0000000000000003-a3f1c9e2.json`
#: 16 digits, so a lexical sort IS sequence order. The digest prefix makes a
#: renamed, swapped or hand-edited file visible instead of silent; the shape
#: is the one E-3 of the SDK evaluation measured on ContextWorkspace.
SEQUENCE_DIGITS = 16
DIGEST_PREFIX_LEN = 8

#: A task id is our own product (new_task_id), but it arrives through a CLI
#: flag and then becomes a path segment. `../` in a `--task-id` must never
#: reach the file system. No dot is allowed at all -- our ids never carry
#: one, and allowing it would let `..` through the pattern intact.
_TASK_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}\Z")

#: Markers of a legacy or mixed install whose data directory is not split
#: along XDG lines (core/data_dir.rs:10). Carried over verbatim from
#: lean_herdr/tasks.py: the precedence is measured and tested, and rebuilding
#: it from scratch would drift.
_DATA_MARKERS = ("stats.json", "sessions", "vectors", "graphs", "knowledge")


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


def lean_ctx_data_dir() -> Path:
    """lean_ctx_data_dir() rebuilt, same precedence (core/data_dir.rs:12).

    Rebuilt rather than queried: `lean-ctx call` never prints the path, and
    a second process start per poll would eat exactly the saving for which
    the wait mode reads files in the first place.

    Public, unlike the `_data_dir()` it replaces:
    `dispatch.default_registry_path()` needs the SAME resolution for
    `agents/registry.json`. A second construction beside this one is M3 of
    the closing review repeated. Whoever needs the path calls the function.
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


def state_dir(root: str | Path | None = None) -> Path:
    """`<data>/lean-herdr/<repo>/orders`, with the canonicity guard beside it.

    THE single resolution of this path. No module constant next to it, no
    second build-up in dispatch.py, no default in a CLI.

    `lean-herdr`, not `herdr`: `herdr` is the terminal multiplexer this
    project drives, and a directory of that name inside a foreign data
    directory would be read as its own. The name also keeps us apart from
    the 35 directories lean-ctx owns there.

    The repo name is `canonical_root().name` -- the main checkout's
    directory name, never a worktree's and never `$PWD`. All workers of a
    branch meet in the same log no matter which worktree they write from.

    `root` is passed in wherever the caller already resolved it:
    `canonical_root()` starts git. The wait mode resolves once, BEFORE its
    loop -- one git call per dispatch instead of one per second.

    The guard: the repo directory carries a file `root` with the canonical
    path. Two independent clones of the same repository would otherwise
    meet in one directory under the same basename. A deviation is
    `state_root_mismatch` -- deliberately NOT an automatic dodge onto a
    hash suffix. The edge case becomes visible instead of silently mixing.
    """
    base = Path(root) if root is not None else canonical_root()
    home = lean_ctx_data_dir() / "lean-herdr" / base.name
    marker = home / "root"
    try:
        home.mkdir(parents=True, exist_ok=True)
        recorded = marker.read_text(encoding="utf-8").strip() if marker.exists() else ""
        if not recorded:
            marker.write_text(f"{base}\n", encoding="utf-8")
            recorded = str(base)
    except OSError as exc:
        raise OrderLogError(f"log_unreadable: {marker}: {exc}") from exc
    if recorded != str(base):
        raise OrderLogError(f"state_root_mismatch: {home} belongs to {recorded}, not to {base}")
    return home / "orders"


_BASE36 = "0123456789abcdefghijklmnopqrstuvwxyz"


def _base36(number: int) -> str:
    if number <= 0:
        return "0"
    out: list[str] = []
    while number:
        number, rest = divmod(number, 36)
        out.append(_BASE36[rest])
    return "".join(reversed(out))


def new_task_id(*, now: Callable[[], float] = time.time) -> str:
    """`o-<millis base 36>-<random hex>` -- lean-ctx's own id shape.

    Project-wide unique without a counter and without a file two concurrent
    calls would have to lock. The short form `o-3` in the design document
    stands for readability, not for the real shape.
    """
    return f"o-{_base36(int(now() * 1000))}-{secrets.token_hex(4)}"


@dataclass(frozen=True)
class Event:
    """One event, exactly as its file carries it -- plus its own digest.

    `digest` is NOT part of the body: it is the sha256 OF the file bytes,
    and it shows up in exactly two places -- the file name, and the
    `previous_digest` of the next event. Keeping it out of the body is what
    makes the chain checkable at all; a body carrying its own digest could
    never hash to it.
    """

    sequence: int
    kind: str
    task_id: str
    actor: str
    at: str
    previous_digest: str | None
    payload: dict[str, Any]
    digest: str

    @property
    def message(self) -> str:
        return str(self.payload.get("message", ""))


def _safe(task_id: str) -> str:
    if not _TASK_ID.match(task_id or ""):
        raise OrderLogError(f"bad_task_id: {task_id!r}")
    return task_id


def _events_dir(task_id: str, orders: str | Path | None) -> Path:
    base = Path(orders) if orders is not None else state_dir()
    return base / _safe(task_id) / "events"


def _body(
    *,
    sequence: int,
    kind: str,
    task_id: str,
    actor: str,
    at: str,
    previous_digest: str | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "sequence": sequence,
        "kind": kind,
        "task_id": task_id,
        "actor": actor,
        "at": at,
        "previous_digest": previous_digest,
        "payload": payload,
    }


def _canonical(body: dict[str, Any]) -> bytes:
    """The exact bytes that go onto disk AND get hashed.

    `sort_keys` and the tight separators are load-bearing, not style: the
    file is written as these bytes, so `sha256sum` on the file reproduces
    the digest in its name. Nothing re-serialises on read -- the reader
    hashes the raw bytes.
    """
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _event_from(body: dict[str, Any], digest: str) -> Event:
    payload = body.get("payload")
    return Event(
        sequence=int(body["sequence"]),
        kind=str(body.get("kind", "")),
        task_id=str(body.get("task_id", "")),
        actor=str(body.get("actor", "")),
        at=str(body.get("at", "")),
        previous_digest=body.get("previous_digest"),
        payload=payload if isinstance(payload, dict) else {},
        digest=digest,
    )


def read_events(task_id: str, *, orders: str | Path | None = None) -> list[Event]:
    """Every event of one order, in sequence -- or an empty list.

    Missing directory: empty list; before the first event it simply does
    not exist. Unreadable, malformed, out of sequence or off the chain:
    OrderLogError. That difference is the point.

    What the chain catches: a changed body (the file no longer hashes to
    the digest in its name), a renamed or swapped file (same check), a gap
    or a duplicate sequence (the running count), a re-linked event (the
    `previous_digest` comparison). What it cannot catch is a truncation at
    the END -- an append-only log that lost its last file is still
    internally consistent. That is honest, and the wait mode runs into its
    timeout there rather than reporting a wrong state.

    Every `chain_broken` names the ORDER and the event that broke it --
    `chain_broken: o-1a05e34cd15-1cf3b885 @ 3: not linked to its
    predecessor`. It has to: nothing ever deletes an order and
    `report._folded()` folds every one of them, so a single corrupted log
    blocks `herdr-report next` for every worker until a human clears it.
    The failure stays hard on purpose -- a broken log is an error, never a
    'nothing to do' -- and naming the order is what makes it fixable.
    """
    directory = _events_dir(task_id, orders)
    try:
        files = sorted(p for p in directory.iterdir() if p.suffix == ".json")
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise OrderLogError(f"log_unreadable: {directory}: {exc}") from exc

    events: list[Event] = []
    for path in files:
        try:
            blob = path.read_bytes()
        except OSError as exc:
            raise OrderLogError(f"log_unreadable: {path}: {exc}") from exc
        digest = hashlib.sha256(blob).hexdigest()
        seq_text, _, prefix = path.stem.partition("-")
        if prefix != digest[:DIGEST_PREFIX_LEN]:
            raise OrderLogError(
                f"chain_broken: {task_id} @ {path.name}: "
                "does not hash to the digest in its name"
            )
        try:
            body = json.loads(blob.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OrderLogError(f"log_unreadable: {path}: {exc}") from exc
        if not isinstance(body, dict):
            raise OrderLogError(
                f"log_unreadable: {path}: body is {type(body).__name__}, not an object"
            )
        if body.get("schema_version") != SCHEMA_VERSION:
            raise OrderLogError(
                f"log_unreadable: {path}: schema is "
                f"{body.get('schema_version')!r}, not {SCHEMA_VERSION!r}"
            )
        expected_seq = len(events) + 1
        if body.get("sequence") != expected_seq or seq_text != (
            f"{expected_seq:0{SEQUENCE_DIGITS}d}"
        ):
            raise OrderLogError(f"chain_broken: {task_id} @ {expected_seq}: out of sequence")
        if body.get("previous_digest") != (f"sha256:{events[-1].digest}" if events else None):
            raise OrderLogError(
                f"chain_broken: {task_id} @ {expected_seq}: not linked to its predecessor"
            )
        events.append(_event_from(body, digest))
    return events


def append(
    task_id: str,
    kind: str,
    actor: str,
    payload: dict[str, Any] | None = None,
    *,
    orders: str | Path | None = None,
    at: str | None = None,
) -> Event:
    """Append one event. Atomic: write a temp file, then `Path.replace()`.

    Reads before it writes: sequence and `previous_digest` come from the
    events already there. A broken chain therefore refuses the append
    instead of compounding the damage.

    Two writers racing for the same sequence do NOT overwrite each other --
    their file names differ in the digest -- and read_events() then reports
    the duplicate as `chain_broken`. That is the honest outcome: the
    protocol serialises the two sides (one always waits for the other), so
    a collision means something else already went wrong.
    """
    directory = _events_dir(task_id, orders)
    previous = read_events(task_id, orders=orders)
    body = _body(
        sequence=len(previous) + 1,
        kind=kind,
        task_id=task_id,
        actor=actor,
        at=at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        previous_digest=f"sha256:{previous[-1].digest}" if previous else None,
        payload=dict(payload or {}),
    )
    blob = _canonical(body)
    digest = hashlib.sha256(blob).hexdigest()
    short = digest[:DIGEST_PREFIX_LEN]
    target = directory / f"{body['sequence']:0{SEQUENCE_DIGITS}d}-{short}.json"
    tmp = directory / f".tmp-{short}"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(blob)
        tmp.replace(target)
    except OSError as exc:
        raise OrderLogError(f"log_unreadable: {directory}: {exc}") from exc
    return _event_from(body, digest)


def task_ids(*, orders: str | Path | None = None) -> list[str]:
    """Every order in the log, newest first.

    The id carries a millisecond timestamp in base 36, so a reverse sort by
    name is newest-first for as long as that number keeps its digit count
    -- which it does until 2059. The sort is a convenience: correctness
    comes from the caller filtering by addressee and open state.
    """
    base = Path(orders) if orders is not None else state_dir()
    try:
        return sorted((p.name for p in base.iterdir() if p.is_dir()), reverse=True)
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise OrderLogError(f"log_unreadable: {base}: {exc}") from exc
