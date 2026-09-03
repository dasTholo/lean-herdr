"""The three commands that WRITE into the order log.

Split out of dispatch.py the moment that file crossed the project's 800
production LOC limit -- the move section 3g of the order-log plan named in
advance for exactly this measurement. The signatures are unchanged; only
their home is new, and `dispatch.main()` still routes the positional slot
here.

`order_result` came along: it is the shape of an order result, and both
sides of the split need it. Leaving it in dispatch.py would have made the
import circular. It is public for exactly that reason -- it used to carry
a leading underscore while being imported across a module boundary, which
promised a privacy it never had.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lean_herdr.handlers import ORCHESTRATOR
from lean_herdr.orderlog import (
    OrderLogError,
    append,
    new_task_id,
    read_events,
    state_dir,
)
from lean_herdr.orders import fold, is_terminal

#: Who `order` stamps as the sender. The bootstrap starts the orchestrator
#: pane under exactly this herdr agent name, and the workers' role prompts
#: compare against exactly this string -- so it is imported, never spelled
#: a second time (M3). `--from` overrides it for a differently named pane.
ORCHESTRATOR_AGENT = ORCHESTRATOR["name"]


def order_result(ok: bool, task_id: str, **rest: Any) -> dict[str, Any]:
    """The shape every order answer takes -- the write side's and the wait
    mode's alike. Public: dispatch.py imports it."""
    return {"ok": ok, "task_id": task_id, **rest}


@dataclass(frozen=True)
class OrderRequest:
    to_agent: str
    message: str
    after: str | None = None
    #: The claimed sender. The workers compare it against the one name
    #: their role prompt trusts, so the default must be the name the
    #: bootstrap actually starts the orchestrator under.
    actor: str = ORCHESTRATOR_AGENT


def create_order(
    req: OrderRequest,
    *,
    root: Path,
    orders_dir: str | Path | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Write the `created` event. Never raises; the result carries `ok`.

    THIS is the step the ctx_task design could not take from a script:
    `ctx_task create` demanded a registered, long-lived MCP agent, which a
    `lean-ctx call` is exactly not. A log of our own has no such rule, so
    the write path is a script call -- and unit-testable at last.

    `--after` is checked, not merely stored: an id nobody wrote would make
    `herdr-report next` fold in nothing, silently, and the worker would
    lose the predecessor's wording without ever learning why.
    """
    if not req.to_agent:
        return {"ok": False, "error": "usage_error: order needs --to"}
    if not req.message:
        return {"ok": False, "error": "usage_error: order needs --message"}
    try:
        directory = orders_dir if orders_dir is not None else state_dir(root)
        if req.after and not read_events(req.after, orders=directory):
            return {"ok": False, "error": f"task_not_found: {req.after}"}
        new_id = task_id or new_task_id()
        payload: dict[str, Any] = {
            "to_agent": req.to_agent,
            "description": req.message,
        }
        if req.after:
            payload["after"] = req.after
        append(new_id, "created", req.actor, payload, orders=directory)
    except OrderLogError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "task_id": new_id, "to_agent": req.to_agent}


def answer_order(
    task_id: str,
    message: str,
    *,
    root: Path,
    orders_dir: str | Path | None = None,
    actor: str = ORCHESTRATOR_AGENT,
) -> dict[str, Any]:
    """Answer a question the worker asked. Never raises.

    `answered` is the event ctx_task did not have. There the reply hid
    inside the `message` of an update(state="working"), which
    orchestrator.md had to explain in six lines -- plus a warning that
    `action: "message"` writes into a store no ctx_task call ever prints.
    Here it is an event of its own, and both explanations fall away.

    The order goes back to `working` by itself: orders._STATE_OF maps
    `answered` to that state, so there is no second call and no transition
    the orchestrator could forget.
    """
    try:
        directory = orders_dir if orders_dir is not None else state_dir(root)
        events = read_events(task_id, orders=directory)
        if not events:
            return order_result(False, task_id, error="task_not_found")
        order = fold(events)
        if order.state != "input-required":
            return order_result(
                False,
                task_id,
                state=order.state,
                error=(
                    f"usage_error: {task_id} is {order.state or '<unknown>'}, "
                    "not input-required -- nobody asked anything"
                ),
            )
        append(task_id, "answered", actor, {"message": message}, orders=directory)
    except OrderLogError as exc:
        return order_result(False, task_id, error=str(exc))
    return order_result(True, task_id, state="working", message=message)


def cancel_order(
    task_id: str,
    message: str,
    *,
    root: Path,
    orders_dir: str | Path | None = None,
    actor: str = ORCHESTRATOR_AGENT,
) -> dict[str, Any]:
    """Close an order that got stuck. Never raises.

    An honest loss, named: `ctx_task cancel` let ONLY the creator close a
    task (handle_cancel). Our log enforces nothing of the kind -- the rule
    moved into the role prompt. We traded an enforced access rule for an
    agreed one.

    Nobody else cleans up, and that is intended. There is no
    `cleanup_old(72)` here: the log stays until a human deletes it, and an
    order left non-terminal is the evidence that a run broke off.
    """
    try:
        directory = orders_dir if orders_dir is not None else state_dir(root)
        events = read_events(task_id, orders=directory)
        if not events:
            return order_result(False, task_id, error="task_not_found")
        order = fold(events)
        if is_terminal(order.state):
            return order_result(
                False,
                task_id,
                state=order.state,
                error=f"usage_error: {task_id} is already {order.state}",
            )
        append(task_id, "canceled", actor, {"message": message}, orders=directory)
    except OrderLogError as exc:
        return order_result(False, task_id, error=str(exc))
    return order_result(True, task_id, state="canceled", message=message)
