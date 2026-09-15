"""What a plan run does next -- a pure function of the plan, its orders and the checks.

No file, no process, no clock: `plancmd` reads the log and runs the checks, this module
only decides (spec section 6.4). The orchestrator counts nothing itself.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from lean_herdr.dispatch import verdict
from lean_herdr.orders import PLAN_TASK_RE, Order, message_from
from lean_herdr.plan import Plan

#: `worktree.changes` flags that mean work was left uncommitted. `untracked` is not one:
#: files the builder did not name stay out of its commits; one git does not ignore is the
#: review's finding and stops the merge (builder.md, briefs/review.lmd.md).
TRACKED_CHANGES = ("staged", "modified", "deleted", "renamed", "conflicted")


def _ruling(order: Order) -> str:
    """`result` or `reject`. A missing or unreadable verdict counts as `reject`."""
    return "result" if verdict(message_from(order, order.to_agent)) == "result" else "reject"


def _dirty(order: Order) -> bool:
    return order.done_changes is not None and any(
        flag in TRACKED_CHANGES for flag in order.done_changes
    )


def _label(plan_task: str | None) -> int | str | None:
    return (
        int(plan_task) if plan_task is not None and PLAN_TASK_RE.fullmatch(plan_task) else plan_task
    )


def _stopped(order: Order) -> dict[str, Any] | None:
    if order.state == "failed":
        return {"escalate": True, "reason": "agent_error", "task_id": order.id}
    if order.state == "canceled":
        return {"escalate": True, "reason": "canceled", "task_id": order.id}
    return None


def _work(plan: Plan | None, order: Order) -> str:
    """The `--work` a dispatch for this order uses: a task's own work, else the step."""
    if (
        order.step == "implement"
        and plan is not None
        and order.plan_task
        and PLAN_TASK_RE.fullmatch(order.plan_task)
    ):
        task = next((t for t in plan.tasks if t.number == int(order.plan_task)), None)
        if task is not None:
            return task.work
    return order.step or ""


def _round(orders: Sequence[Order], order: Order) -> int:
    same = [o for o in orders if o.step == order.step and o.plan_task == order.plan_task]
    return same.index(order) + 1


def _planning(
    orders: Sequence[Order], checks: Mapping[str, Sequence[dict[str, Any]]]
) -> dict[str, Any] | None:
    """The plan and its review. None once the review said `result`.

    Every plan step after the first carries the last plan order's `spec`: `dispatch order
    --step plan` needs `--spec`.
    """
    plans = [o for o in orders if o.step == "plan"]
    if not plans:
        return {"step": "plan", "work": "plan", "round": 1}
    last = plans[-1]
    stopped = _stopped(last)
    if stopped is not None:
        return stopped
    errors = list(checks.get(last.id, ()))
    if errors:
        if len(plans) >= 2 and checks.get(plans[-2].id):
            return {"escalate": True, "reason": "check×2", "task_id": last.id}
        return {
            "step": "plan",
            "work": "plan",
            "reason": "check",
            "errors": errors,
            "round": len(plans) + 1,
            "after": last.id,
            "spec": last.spec,
        }
    after_last = orders[orders.index(last) + 1 :]
    reviews = [o for o in after_last if o.step == "plan-review"]
    if not reviews:
        return {"step": "plan-review", "work": "plan-review"}
    review = reviews[-1]
    stopped = _stopped(review)
    if stopped is not None:
        return stopped
    if _ruling(review) == "result":
        return None
    rejects = [
        o
        for o in orders
        if o.step == "plan-review" and o.state == "completed" and _ruling(o) == "reject"
    ]
    if len(rejects) >= 2:
        return {"escalate": True, "reason": "plan-review reject×2", "task_id": review.id}
    return {
        "step": "plan",
        "work": "plan",
        "round": len(plans) + 1,
        "after": review.id,
        "spec": last.spec,
    }


def _cycle(orders: Sequence[Order], task: str, work: str) -> dict[str, Any] | None:
    """One task's implement/review loop -- or the branch's. None once its review said `result`."""
    group = [o for o in orders if o.plan_task == task and o.step in ("implement", "review")]
    implements = [o for o in group if o.step == "implement"]
    label = _label(task)
    if not group:
        if task == "branch":
            return {"step": "review", "task": label, "work": "review"}
        return {"step": "implement", "task": label, "work": work, "round": 1}
    last = group[-1]
    stopped = _stopped(last)
    if stopped is not None:
        return {**stopped, "task": label}
    if last.step == "implement":
        if not _dirty(last):
            return {"step": "review", "task": label, "work": "review", "after": last.id}
        since_review: list[Order] = []
        for order in reversed(group):
            if order.step == "review":
                break
            since_review.append(order)
        if len(since_review) >= 2 and _dirty(since_review[1]):
            return {"escalate": True, "reason": "uncommitted×2", "task_id": last.id, "task": label}
        return {
            "step": "implement",
            "task": label,
            "work": work,
            "reason": "uncommitted",
            "round": len(implements) + 1,
            "after": last.id,
        }
    if _ruling(last) == "result":
        return None
    rejects = [
        o for o in group if o.step == "review" and o.state == "completed" and _ruling(o) == "reject"
    ]
    if len(rejects) >= 2:
        return {"escalate": True, "reason": "review reject×2", "task_id": last.id, "task": label}
    return {
        "step": "implement",
        "task": label,
        "work": work,
        "round": len(implements) + 1,
        "after": last.id,
    }


def next_step(
    plan: Plan | None,
    orders: Sequence[Order],
    *,
    checks: Mapping[str, Sequence[dict[str, Any]]],
    merged: bool,
) -> dict[str, Any]:
    """The next move of a plan run (spec section 6.4).

    `orders` are this plan's orders, oldest first. `checks` maps a completed plan order's
    id to the `plan check` errors at its `report done` head; an empty list is a clean plan.
    """
    if merged:
        return {"done": True}
    waiting = [o for o in orders if o.is_open]
    if waiting:
        order = waiting[-1]
        answer = {
            "step": "await",
            "work": _work(plan, order),
            "task_id": order.id,
            "task": _label(order.plan_task),
            "round": _round(orders, order),
            "of": order.step,
        }
        if order.step == "plan":
            answer["spec"] = order.spec
        return answer
    answer = _planning(orders, checks)
    if answer is not None:
        return answer
    if plan is None:
        return {"escalate": True, "reason": "no_plan"}
    for task in plan.tasks:
        answer = _cycle(orders, str(task.number), task.work)
        if answer is not None:
            return answer
    answer = _cycle(orders, "branch", "implement")
    return answer if answer is not None else {"step": "merge"}


def task_summary(plan: Plan, orders: Sequence[Order]) -> list[dict[str, Any]]:
    """One row per task for `plan show`: its route, rounds, orders and state."""
    rows: list[dict[str, Any]] = []
    for task in plan.tasks:
        key = str(task.number)
        group = [o for o in orders if o.plan_task == key and o.step in ("implement", "review")]
        if not group:
            state = "pending"
        elif any(o.is_open for o in group):
            state = "working"
        else:
            answer = _cycle(orders, key, task.work)
            state = (
                "done"
                if answer is None
                else "escalated"
                if answer.get("escalate")
                else str(answer["step"])
            )
        rows.append(
            {
                "task": task.number,
                "title": task.title,
                "work": task.work,
                "lane": task.lane,
                "files": list(task.files),
                "rounds": sum(1 for o in group if o.step == "implement"),
                "orders": [o.id for o in group],
                "state": state,
            }
        )
    return rows
