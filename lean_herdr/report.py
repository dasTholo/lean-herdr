"""The worker's side of the order log. One JSON line, exit ALWAYS 0.

Six subcommands: next, show, start, done, fail, ask. Deliberately no
`note` and no `recall`: knowledge is INJECTED, not fetched. A `ctx_read`
brings the relevant entries along unasked, capped by `recall_facts_limit`
and filtered by a relevance threshold, so a read step would cost a tool
call for something already in the context.

Thin on purpose, like lean-herdr dispatch: the mechanics live in
orderlog.py and orders.py, and this module only decides who is asking and
what to print.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, NoReturn

from lean_herdr.bus import BusError, canonical_root
from lean_herdr.dispatch import AGENT_ENV, ROLE_ENV, agent_name
from lean_herdr.orderlog import (
    OrderLogError,
    append,
    read_events,
    state_dir,
    task_ids,
)
from lean_herdr.orders import Order, fold, is_terminal, message_from, newest_open
from lean_herdr.settings import (
    SETTINGS_PATH,
    SettingsError,
    read_settings,
    settings_for,
)

GIT_TIMEOUT_S = 5.0


#: `wt list` is local and fast; it must not hold up a report.
WT_TIMEOUT_S = 5.0

#: The worktree flags a stamp keeps, in this order (`wt list --format=json`,
#: `worktree.changes`).
CHANGE_FLAGS = ("staged", "modified", "untracked", "renamed", "deleted", "conflicted")

#: The two subcommands whose event carries the stamp: `start` fixes the base a review
#: diffs from, `done` what the worker left behind.
STAMPED = ("start", "done")

# `AGENT_ENV` and `ROLE_ENV` are IMPORTED, never spelled here: dispatch.py
# writes exactly these two variables onto the pane it splits, and a second
# spelling on this side would leave the whole suite green while every order
# ran into the void -- the pane carrying one variable, the worker reading
# another. One truth, not two (M3).

#: subcommand -> the event kind it appends.
KIND_OF = {
    "start": "working",
    "done": "completed",
    "fail": "failed",
    "ask": "input-required",
}

#: The two subcommands that only read.
READING = ("next", "show")

#: Every subcommand this CLI accepts -- the parser's own `choices`, and the
#: list tests/test_worker_permissions.py holds BOTH permission files to.
#: The six words used to stand in four unbound copies (here, .claude/
#: settings.json, opencode.jsonc, the test), so a seventh subcommand
#: shipped green with no permission anywhere and failed at the worker in a
#: way that looks exactly like a crash.
SUBCOMMANDS = (*READING, *KIND_OF)


class ReportError(RuntimeError):
    """Something the worker must see as an error, not as an empty answer."""


def current_branch(cwd: str | Path | None = None, *, runner: Any = subprocess.run) -> str:
    """The branch of the checkout this process runs in -- "" when detached.

    Deliberately NOT in worktree.py: that module resolves and CREATES
    worktrees, and this design does not touch it.
    """
    proc = runner(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_S,
        check=False,
    )
    name = (proc.stdout or "").strip()
    return "" if proc.returncode != 0 or name == "HEAD" else name


def resolve_agent(
    override: str | None = None,
    *,
    root: Path,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    """Who this worker is. Three sources, in this order.

    1. `--agent` -- for tests and hand diagnosis. The role prompts do not
       name it, and the regular run never passes it.
    2. `$LEAN_HERDR_AGENT` -- set by dispatch.py on the pane it splits.
       This is the regular path, and it is exact by construction: the very
       same `agent_name()` call that addresses the order set this value.
    3. `$LEAN_CTX_ROLE` plus the current branch, through the SAME
       `agent_name()` / `settings_for()` the dispatch side uses, so the
       `name_template` from `.lean-ctx/lean-herdr/config.toml` governs both sides.
       This carries a pane started by hand. It is only the fallback because
       it silently disagrees whenever the dispatch carried no `--worktree`:
       there the agent is `builder`, here the derivation says
       `builder-feat-x`.

    Without either environment variable: `no_role`. Guessing a name would
    be worse than stopping -- an order under the wrong name reaches nobody,
    and the failure would look like a crash and run into `no_reply`.
    """
    if override:
        return override
    values = env if env is not None else os.environ
    name = (values.get(AGENT_ENV) or "").strip()
    if name:
        return name
    role = (values.get(ROLE_ENV) or "").strip()
    if not role:
        raise ReportError("no_role")
    settings = settings_for(role, read_settings(root / SETTINGS_PATH))
    return agent_name(role, current_branch(cwd) or None, settings=settings)


def _brief(order: Order, *, orders_dir: str | Path) -> str:
    """The order as the worker reads it, with its predecessor folded in.

    The run-up is a REFERENCE, not a retelling: `--after o-2` puts the
    predecessor's own closing words here, verbatim, and it costs no second
    tool call. Written into the description by hand they would arrive as
    the orchestrator's paraphrase.
    """
    lines = [
        f"{order.id}  [{order.state}]  <- {order.from_agent}",
        order.description,
    ]
    if order.after:
        previous = fold(read_events(order.after, orders=orders_dir))
        closing = message_from(previous, previous.to_agent) or ""
        lines.append(f"after: {order.after} ({previous.to_agent}, {previous.state})")
        if closing:
            lines.append(f'  "{closing}"')
    return "\n".join(lines)


def _folded(orders_dir: str | Path) -> list[Order]:
    return [fold(read_events(t, orders=orders_dir)) for t in task_ids(orders=orders_dir)]


def next_order(agent: str, *, orders_dir: str | Path) -> dict[str, Any]:
    """The open order for this agent, with its run-up -- or nothing to do."""
    order = newest_open(_folded(orders_dir), agent)
    if order is None:
        return {"ok": True, "agent": agent, "task_id": None, "text": "no open order"}
    return {
        "ok": True,
        "agent": agent,
        "task_id": order.id,
        "state": order.state,
        "from": order.from_agent,
        "text": _brief(order, orders_dir=orders_dir),
    }


def _mine(order: Order, agent: str, task_id: str) -> dict[str, Any] | None:
    """None when the order is this agent's -- otherwise the refusal."""
    if not order.state:
        return {"ok": False, "task_id": task_id, "error": "task_not_found"}
    if order.to_agent != agent:
        return {
            "ok": False,
            "task_id": task_id,
            "error": (
                f"usage_error: {task_id} is addressed to "
                f"{order.to_agent or '<nobody>'}, not to {agent}"
            ),
        }
    return None


def show_order(agent: str, task_id: str, *, orders_dir: str | Path) -> dict[str, Any]:
    """One order with its full event list.

    The only reason a worker reads this: after a question. The
    orchestrator's answer is the `answered` event, and it stands in this
    list under its own kind -- no history to hunt through, no message store
    that never gets printed.
    """
    order = fold(read_events(task_id, orders=orders_dir))
    refusal = _mine(order, agent, task_id)
    if refusal is not None:
        return refusal
    return {
        "ok": True,
        "agent": agent,
        "task_id": order.id,
        "state": order.state,
        "from": order.from_agent,
        "text": _brief(order, orders_dir=orders_dir),
        "events": [
            {"seq": e.sequence, "kind": e.kind, "actor": e.actor, "at": e.at, "message": e.message}
            for e in read_events(task_id, orders=orders_dir)
        ],
    }


def worktree_stamp(
    cwd: str | Path | None = None, *, runner: Any = subprocess.run
) -> dict[str, Any]:
    """`head` and set `changes` of the worktree this process runs in -- or `wt_error`.

    Read from the entry `wt list --format=json` marks `worktree.current`. Never raises:
    a stamp that cannot be taken is recorded as `wt_error`, and the report goes
    through anyway.
    """
    try:
        proc = runner(
            ["wt", "list", "--format=json"],
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            timeout=WT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"wt_error": f"wt list failed: {exc}"}
    if proc.returncode != 0:
        return {"wt_error": f"wt list exited {proc.returncode}: {(proc.stderr or '').strip()}"}
    try:
        data = json.loads(proc.stdout or "")
    except json.JSONDecodeError as exc:
        return {"wt_error": f"wt list printed no JSON: {exc}"}
    # Every level is checked for its shape: a report must not crash on output it did not expect.
    items = data.get("items") if isinstance(data, dict) else None
    current: dict[str, Any] = next(
        (
            item
            for item in (items if isinstance(items, list) else [])
            if isinstance(item, dict)
            and isinstance(item.get("worktree"), dict)
            and item["worktree"].get("current") is True
        ),
        {},
    )
    head = current.get("head")
    sha = head.get("sha") if isinstance(head, dict) else None
    if not isinstance(sha, str) or not sha:
        return {"wt_error": "wt list names no current worktree with a head"}
    changes = current["worktree"].get("changes")
    flags = changes if isinstance(changes, dict) else {}
    return {"head": sha, "changes": [flag for flag in CHANGE_FLAGS if flags.get(flag) is True]}


def report(
    agent: str,
    command: str,
    task_id: str,
    message: str,
    *,
    orders_dir: str | Path,
    stamper: Callable[[], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Append the event this subcommand stands for.

    Refuses an order addressed to somebody else and one that is already
    terminal. Neither gets a code of its own: they are operator errors, and
    `usage_error:` already carries those.
    """
    order = fold(read_events(task_id, orders=orders_dir))
    refusal = _mine(order, agent, task_id)
    if refusal is not None:
        return refusal
    if is_terminal(order.state):
        return {
            "ok": False,
            "task_id": task_id,
            "error": f"usage_error: {task_id} is already {order.state}",
        }
    payload: dict[str, Any] = {"message": message} if message else {}
    if stamper is not None and command in STAMPED:
        payload.update(stamper())
    event = append(task_id, KIND_OF[command], agent, payload, orders=orders_dir)
    return {"ok": True, "agent": agent, "task_id": task_id, "state": event.kind}


class UsageError(Exception):
    """A parser complaint -- raised instead of ending the process."""


class _Parser(argparse.ArgumentParser):
    """Same reason as in dispatch.py: the worker reads `ok` on stdout.

    argparse ends a usage error with exit 2 and one line on stderr, which
    would reach the worker as no output at all.
    """

    def error(self, message: str) -> NoReturn:
        raise UsageError(message)


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(prog="lean-herdr report", description="Report on a work order.")
    p.add_argument("command", choices=SUBCOMMANDS)
    p.add_argument("--task", default=None, help="the order id; not used by `next`")
    p.add_argument("--message", default=None, help="required for done, fail and ask")
    p.add_argument(
        "--agent",
        default=None,
        help="override the resolved agent name; for tests and hand diagnosis",
    )
    return p


def missing_flags(args: argparse.Namespace) -> str | None:
    if args.command == "next":
        stray = " and ".join(
            flag
            for flag, value in (("--task", args.task), ("--message", args.message))
            if value is not None
        )
        return f"next does not take {stray}" if stray else None
    if not args.task:
        return f"{args.command} needs --task"
    if args.command in ("done", "fail", "ask") and not args.message:
        return f"{args.command} needs --message"
    if args.command in ("show", "start") and args.message is not None:
        return f"{args.command} does not take --message"
    return None


def main(argv: list[str] | None = None) -> int:
    """Output: one JSON line on stdout. Exit ALWAYS 0.

    Same contract as lean-herdr dispatch, for the same reason: the worker
    reads `ok`, not the exit code, and a usage error must not abort its
    shell call.
    """
    result: dict[str, Any]
    try:
        args = build_parser().parse_args(argv)
        complaint = missing_flags(args)
        if complaint:
            result = {"ok": False, "error": f"usage_error: {complaint}"}
        else:
            root = canonical_root()
            agent = resolve_agent(args.agent, root=root)
            orders_dir = state_dir(root)
            if args.command == "next":
                result = next_order(agent, orders_dir=orders_dir)
            elif args.command == "show":
                result = show_order(agent, args.task, orders_dir=orders_dir)
            else:
                result = report(
                    agent,
                    args.command,
                    args.task,
                    args.message or "",
                    orders_dir=orders_dir,
                    stamper=worktree_stamp,
                )
    except UsageError as exc:
        result = {"ok": False, "error": f"usage_error: {exc}"}
    except ReportError as exc:
        result = {"ok": False, "error": str(exc)}
    except (OrderLogError, BusError, SettingsError) as exc:
        result = {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 -- never abort the caller
        result = {"ok": False, "error": f"report_crashed: {exc}"}
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    return 0
