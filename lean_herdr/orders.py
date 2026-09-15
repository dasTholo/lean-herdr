"""What a sequence of events MEANS. Knows nothing about files.

lean_herdr/orderlog.py stores events; this module reads them as an order.
The cut buys the design its testability: fold() is a pure function over a
list, so the whole order path is testable without a file system.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Any

from lean_herdr.orderlog import Event

#: The seven kinds an event may carry. `answered` is the one ctx_task did
#: not have: there the orchestrator's reply hid inside the `message` of an
#: update(state="working"), which orchestrator.md had to explain in six
#: lines -- plus a warning that `action: "message"` writes into a store no
#: ctx_task call ever prints. Here the answer is an event of its own, and
#: both explanations fall away.
EVENT_KINDS = (
    "created",
    "working",
    "input-required",
    "answered",
    "completed",
    "failed",
    "canceled",
)

#: States after which no further event arrives.
TERMINAL_STATES = frozenset({"completed", "failed", "canceled"})

#: kind -> the state it puts the order in. `answered` is the only kind whose
#: name is not its state: the orchestrator answered, so the worker is
#: working again. Every other kind names its own state.
_STATE_OF: dict[str, str] = {kind: kind for kind in EVENT_KINDS} | {"answered": "working"}


#: The four steps of a plan run an order can belong to (`dispatch order --step`).
PLAN_STEPS = ("plan", "plan-review", "implement", "review")

#: A plan slug. `plan/<slug>` is the branch, and the longest agent name built on it,
#: `plan-reviewer-plan-<slug>`, has to stay within herdr's 32 characters.
PLAN_SLUG_RE = re.compile(r"[a-z][a-z0-9-]{0,11}")

#: A task number on an order: decimal, no leading zero. `str.isdigit` lets "²" through,
#: and `int("²")` raises.
PLAN_TASK_RE = re.compile(r"[1-9][0-9]*")


def is_terminal(state: str) -> bool:
    return state in TERMINAL_STATES


@dataclass(frozen=True)
class Order:
    """One order, folded out of its events.

    `from_agent` is the actor of the `created` event. The role prompts rest
    on it: "exactly one sender may give you work" cannot be checked without
    naming the sender.

    `messages` keeps (actor, text) for every event that carried one. The
    order TEXT is not in there -- it rides in `description`, off the
    `created` event. That is the quiet win over the task store, where the
    first message carried the creator's role and blindly taking the last
    one handed our own order back as the worker's answer.

    The event KIND is deliberately not kept beside them. It had no reader:
    `message_from()` is the only consumer and asks by actor, and the one
    place that could have used it -- `dispatch._result_for_state()` -- is
    frozen verbatim by the design's five reserves. A third slot nobody
    reads only invites the misreading that the closing message is filtered
    by kind. `show_order()` prints every event with its kind straight off
    `read_events()`, so nothing is lost.
    """

    id: str
    from_agent: str = ""
    to_agent: str = ""
    state: str = ""
    description: str = ""
    after: str | None = None
    #: The plan run this order belongs to; all four None for an order outside a plan.
    #: `plan_task` is a task number as text ("3") or "branch".
    plan: str | None = None
    step: str | None = None
    plan_task: str | None = None
    spec: str | None = None
    messages: tuple[tuple[str, str], ...] = ()

    @property
    def is_open(self) -> bool:
        return bool(self.state) and not is_terminal(self.state)


def fold(events: Iterable[Event]) -> Order:
    """Events -> Order. The state is the LAST transition, never a field.

    The log is append-only: a state is never overwritten, only a new event
    appended. An unknown kind is kept verbatim as the state and is never
    terminal -- word for word the rule normalize_state() held for the task
    store. A format change must run into the timeout, visibly, instead of
    into a false success.
    """
    order = Order(id="")
    for event in events:
        order = _apply(order, event)
    return order


def _text(value: Any) -> str | None:
    """A payload value as text, or None for an absent or empty one."""
    return str(value) if value else None


def _apply(order: Order, event: Event) -> Order:
    messages = order.messages
    text = event.message.strip()
    if text:
        messages = (*messages, (event.actor, text))
    if event.kind == "created":
        after: Any = event.payload.get("after")
        return replace(
            order,
            id=event.task_id or order.id,
            from_agent=event.actor,
            to_agent=str(event.payload.get("to_agent", "")),
            description=str(event.payload.get("description", "")),
            after=str(after) if after else None,
            plan=_text(event.payload.get("plan")),
            step=_text(event.payload.get("step")),
            plan_task=_text(event.payload.get("plan_task")),
            spec=_text(event.payload.get("spec")),
            state=_STATE_OF["created"],
            messages=messages,
        )
    return replace(
        order,
        id=order.id or event.task_id,
        state=_STATE_OF.get(event.kind, event.kind),
        messages=messages,
    )


def message_from(order: Order, actor: str) -> str | None:
    """Newest message from that actor -- otherwise None."""
    for who, text in reversed(order.messages):
        if who == actor:
            return text
    return None


def newest_open(orders: Iterable[Order], agent: str) -> Order | None:
    """The one order this agent should look at -- or None.

    `ctx_task list` filtered server-side by the calling process's registered
    agent_id ("No tasks found for this agent", measured). A log of our own
    has no such filter, so it is spelled out here -- and stays a pure
    function over already-folded orders. The caller hands them in
    newest-first.
    """
    return next((o for o in orders if o.to_agent == agent and o.is_open), None)
