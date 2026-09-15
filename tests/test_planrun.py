import pytest

from lean_herdr.orders import Order
from lean_herdr.plan import Plan, Task
from lean_herdr.planrun import next_step, task_summary

WORKER = "worker"
SPEC = "docs/specs/shop-design.md"
PLAN = Plan(
    slug="shop",
    ref="plan/shop",
    tasks=(
        Task(1, "Task 1: models", 10, routed=True, work="implement", lane="core", files=("a.py",)),
        Task(
            2, "Task 2: api", 20, routed=True, work="implement-small", lane="core", files=("b.py",)
        ),
    ),
    lanes={"core": ()},
)
ERR = [
    {
        "kind": "no_route",
        "line": 10,
        "phase": "task-1",
        "message": "task-1 does not start with @call route(work, lane, files)",
    }
]


def o(order_id, step, *, task=None, state="completed", verdict=None, changes=()):
    return Order(
        id=order_id,
        from_agent="orch",
        to_agent=WORKER,
        state=state,
        plan="shop",
        step=step,
        plan_task=task,
        spec=SPEC if step == "plan" else None,
        messages=((WORKER, f"VERDIKT: {verdict}\nbecause"),) if verdict else (),
        done_changes=tuple(changes) if state == "completed" else None,
    )


PLANNED = [o("p1", "plan"), o("r1", "plan-review", verdict="result")]
TASKS_DONE = [
    *PLANNED,
    o("i1", "implement", task="1"),
    o("v1", "review", task="1", verdict="result"),
    o("i2", "implement", task="2"),
    o("v2", "review", task="2", verdict="result"),
]
UNKNOWN = Order(
    id="i1", to_agent=WORKER, state="completed", plan="shop", step="implement", plan_task="1"
)


@pytest.mark.parametrize(
    ("orders", "checks", "expected"),
    [
        ([], {}, {"step": "plan", "work": "plan", "round": 1}),
        (
            [o("p1", "plan", state="working")],
            {},
            {
                "step": "await",
                "work": "plan",
                "task_id": "p1",
                "task": None,
                "round": 1,
                "of": "plan",
                "spec": SPEC,
            },
        ),
        (
            [o("p1", "plan"), o("r1", "plan-review", state="working")],
            {},
            {
                "step": "await",
                "work": "plan-review",
                "task_id": "r1",
                "task": None,
                "round": 1,
                "of": "plan-review",
            },
        ),
        (
            [o("p1", "plan", state="failed")],
            {},
            {"escalate": True, "reason": "agent_error", "task_id": "p1"},
        ),
        (
            [o("p1", "plan", state="canceled")],
            {},
            {"escalate": True, "reason": "canceled", "task_id": "p1"},
        ),
        (
            [o("p1", "plan")],
            {"p1": ERR},
            {
                "step": "plan",
                "work": "plan",
                "reason": "check",
                "errors": ERR,
                "round": 2,
                "after": "p1",
                "spec": SPEC,
            },
        ),
        (
            [o("p1", "plan"), o("p2", "plan")],
            {"p1": ERR, "p2": ERR},
            {"escalate": True, "reason": "check×2", "task_id": "p2"},
        ),
        (
            [
                o("p1", "plan"),
                o("p2", "plan"),
                o("r1", "plan-review", verdict="reject"),
                o("p3", "plan"),
            ],
            {"p1": ERR, "p2": [], "p3": ERR},
            {
                "step": "plan",
                "work": "plan",
                "reason": "check",
                "errors": ERR,
                "round": 4,
                "after": "p3",
                "spec": SPEC,
            },
        ),
        ([o("p1", "plan")], {}, {"step": "plan-review", "work": "plan-review"}),
        (
            [o("p1", "plan"), o("r1", "plan-review", verdict="reject")],
            {},
            {"step": "plan", "work": "plan", "round": 2, "after": "r1", "spec": SPEC},
        ),
        (
            [
                o("p1", "plan"),
                o("r1", "plan-review", verdict="reject"),
                o("p2", "plan"),
                o("r2", "plan-review", verdict="reject"),
            ],
            {},
            {"escalate": True, "reason": "plan-review reject×2", "task_id": "r2"},
        ),
        (PLANNED, {}, {"step": "implement", "task": 1, "work": "implement", "round": 1}),
        (
            [*PLANNED, o("i1", "implement", task="1", changes=["modified"])],
            {},
            {
                "step": "implement",
                "task": 1,
                "work": "implement",
                "reason": "uncommitted",
                "round": 2,
                "after": "i1",
            },
        ),
        (
            [
                *PLANNED,
                o("i1", "implement", task="1", changes=["modified"]),
                o("i2", "implement", task="1", changes=["staged"]),
            ],
            {},
            {"escalate": True, "reason": "uncommitted×2", "task_id": "i2", "task": 1},
        ),
        (
            [
                *PLANNED,
                o("i1", "implement", task="1", changes=["modified"]),
                o("v1", "review", task="1", verdict="reject"),
                o("i2", "implement", task="1", changes=["staged"]),
            ],
            {},
            {
                "step": "implement",
                "task": 1,
                "work": "implement",
                "reason": "uncommitted",
                "round": 3,
                "after": "i2",
            },
        ),
        (
            [*PLANNED, o("i1", "implement", task="1", changes=["untracked"])],
            {},
            {"step": "review", "task": 1, "work": "review", "after": "i1"},
        ),
        ([*PLANNED, UNKNOWN], {}, {"step": "review", "task": 1, "work": "review", "after": "i1"}),
        (
            [
                *PLANNED,
                o("i1", "implement", task="1"),
                o("v1", "review", task="1", verdict="reject"),
            ],
            {},
            {"step": "implement", "task": 1, "work": "implement", "round": 2, "after": "v1"},
        ),
        (
            [*PLANNED, o("i1", "implement", task="1"), o("v1", "review", task="1")],
            {},
            {"step": "implement", "task": 1, "work": "implement", "round": 2, "after": "v1"},
        ),
        (
            [
                *PLANNED,
                o("i1", "implement", task="1"),
                o("v1", "review", task="1", verdict="reject"),
                o("i2", "implement", task="1"),
                o("v2", "review", task="1", verdict="reject"),
            ],
            {},
            {"escalate": True, "reason": "review reject×2", "task_id": "v2", "task": 1},
        ),
        (
            [
                *PLANNED,
                o("i1", "implement", task="1"),
                o("v1", "review", task="1", verdict="result"),
            ],
            {},
            {"step": "implement", "task": 2, "work": "implement-small", "round": 1},
        ),
        (
            [
                *PLANNED,
                o("i1", "implement", task="1"),
                o("v1", "review", task="1", verdict="result"),
                o("i2", "implement", task="2", state="created"),
            ],
            {},
            {
                "step": "await",
                "work": "implement-small",
                "task_id": "i2",
                "task": 2,
                "round": 1,
                "of": "implement",
            },
        ),
        (
            [*PLANNED, o("i1", "implement", task="1", state="failed")],
            {},
            {"escalate": True, "reason": "agent_error", "task_id": "i1", "task": 1},
        ),
        (TASKS_DONE, {}, {"step": "review", "task": "branch", "work": "review"}),
        (
            [*TASKS_DONE, o("b1", "review", task="branch", verdict="reject")],
            {},
            {"step": "implement", "task": "branch", "work": "implement", "round": 1, "after": "b1"},
        ),
        (
            [
                *TASKS_DONE,
                o("b1", "review", task="branch", verdict="reject"),
                o("b2", "implement", task="branch"),
            ],
            {},
            {"step": "review", "task": "branch", "work": "review", "after": "b2"},
        ),
        (
            [
                *TASKS_DONE,
                o("b1", "review", task="branch", verdict="reject"),
                o("b2", "implement", task="branch"),
                o("b3", "review", task="branch", verdict="reject"),
            ],
            {},
            {"escalate": True, "reason": "review reject×2", "task_id": "b3", "task": "branch"},
        ),
        (
            [
                *TASKS_DONE,
                o("b1", "review", task="branch", verdict="reject"),
                o("b2", "implement", task="branch", changes=["modified"]),
            ],
            {},
            {
                "step": "implement",
                "task": "branch",
                "work": "implement",
                "reason": "uncommitted",
                "round": 2,
                "after": "b2",
            },
        ),
        (
            [*PLANNED, o("i1", "implement", task="1", state="canceled")],
            {},
            {"escalate": True, "reason": "canceled", "task_id": "i1", "task": 1},
        ),
        ([*TASKS_DONE, o("b1", "review", task="branch", verdict="result")], {}, {"step": "merge"}),
    ],
    ids=[
        "fresh",
        "await-plan",
        "await-plan-review",
        "plan-failed",
        "plan-canceled",
        "check",
        "check-twice",
        "check-not-in-a-row",
        "plan-review",
        "plan-review-reject",
        "plan-review-reject-twice",
        "first-task",
        "uncommitted",
        "uncommitted-twice",
        "uncommitted-not-in-a-row",
        "untracked-only",
        "changes-unknown",
        "review-reject",
        "review-no-verdict",
        "review-reject-twice",
        "next-task",
        "await-task",
        "implement-failed",
        "branch-review",
        "branch-reject",
        "branch-fixed",
        "branch-reject-twice",
        "branch-uncommitted",
        "implement-canceled",
        "merge",
    ],
)
def test_next_step(orders, checks, expected):
    assert next_step(PLAN, orders, checks=checks, merged=False) == expected


def test_an_await_answer_names_the_spec_only_for_a_plan_order():
    """F7: a restarted orchestrator resends `--step plan` with `--spec` from this
    field (ordercmd requires it for that step); an `implement` order carries no
    spec at all, so its await answer must not gain one.
    """
    plan_await = next_step(PLAN, [o("p1", "plan", state="working")], checks={}, merged=False)
    assert plan_await["spec"] == SPEC

    implement_await = next_step(
        PLAN,
        [
            *PLANNED,
            o("i1", "implement", task="1"),
            o("v1", "review", task="1", verdict="result"),
            o("i2", "implement", task="2", state="created"),
        ],
        checks={},
        merged=False,
    )
    assert "spec" not in implement_await


def test_a_merged_plan_is_done_whatever_the_log_says():
    assert next_step(PLAN, [o("p1", "plan", state="working")], checks={}, merged=True) == {
        "done": True
    }


def test_without_a_plan_on_the_branch_the_run_cannot_go_on():
    assert next_step(None, PLANNED, checks={}, merged=False) == {
        "escalate": True,
        "reason": "no_plan",
    }


def test_the_summary_names_each_tasks_state_rounds_and_orders():
    orders = [
        *PLANNED,
        o("i1", "implement", task="1"),
        o("v1", "review", task="1", verdict="result"),
        o("i2", "implement", task="2", state="working"),
    ]
    rows = task_summary(PLAN, orders)
    assert [(r["task"], r["state"], r["rounds"], r["orders"]) for r in rows] == [
        (1, "done", 1, ["i1", "v1"]),
        (2, "working", 1, ["i2"]),
    ]
    assert rows[1]["title"] == "Task 2: api"
    assert rows[1]["work"] == "implement-small"
    assert rows[1]["lane"] == "core"
    assert rows[1]["files"] == ["b.py"]
    assert task_summary(PLAN, PLANNED)[0]["state"] == "pending"
