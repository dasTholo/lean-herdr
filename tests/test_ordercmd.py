from pathlib import Path

import pytest

from lean_herdr.ordercmd import OrderRequest, create_order, plan_flag_problem
from lean_herdr.orderlog import read_events, task_ids
from lean_herdr.orders import fold

ROOT = Path("/repo")
WORKER = "builder-plan-shop"
SLUG = r"(?=.{1,12}\Z)[a-z][a-z0-9]*(?:-[a-z0-9]+)*"


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        ((None, None, None, None), None),
        (("shop", "plan", None, "docs/specs/shop-design.md"), None),
        (("shop", "plan-review", None, None), None),
        (("shop", "implement", "3", None), None),
        (("shop", "review", "branch", None), None),
        (("shop", None, None, None), "--plan and --step go together"),
        ((None, "implement", "3", None), "--plan and --step go together"),
        (("Shop", "plan", None, "s.md"), f"--plan 'Shop' is no plan slug ({SLUG})"),
        (
            ("a-slug-far-too-long", "plan", None, "s.md"),
            f"--plan 'a-slug-far-too-long' is no plan slug ({SLUG})",
        ),
        (("a--b", "plan", None, "s.md"), f"--plan 'a--b' is no plan slug ({SLUG})"),
        (("shop-", "plan", None, "s.md"), f"--plan 'shop-' is no plan slug ({SLUG})"),
        (("a-b", "plan", None, "s.md"), None),
        (("abcdefghijkl", "plan", None, "s.md"), None),
        (
            ("abcdefghijklm", "plan", None, "s.md"),
            f"--plan 'abcdefghijklm' is no plan slug ({SLUG})",
        ),
        (
            ("shop", "merge", None, None),
            "--step 'merge' is none of plan, plan-review, implement, review",
        ),
        (("shop", "implement", None, None), "--step implement needs --plan-task"),
        (("shop", "review", "0", None), "--plan-task '0' is neither a task number nor branch"),
        (("shop", "review", "x", None), "--plan-task 'x' is neither a task number nor branch"),
        (("shop", "review", "03", None), "--plan-task '03' is neither a task number nor branch"),
        (("shop", "implement", "²", None), "--plan-task '²' is neither a task number nor branch"),
        (("shop", "plan", "3", "s.md"), "--step plan does not take --plan-task"),
        (("shop", "plan", None, None), "--step plan needs --spec"),
        (("shop", "implement", "3", "s.md"), "--step implement does not take --spec"),
    ],
)
def test_plan_flag_problem(flags, expected):
    assert plan_flag_problem(*flags) == expected


def test_an_order_carries_its_plan_fields_into_the_log(tmp_path):
    result = create_order(
        OrderRequest(
            to_agent=WORKER,
            message="Task 3 of plan shop",
            plan="shop",
            step="implement",
            plan_task="3",
        ),
        root=ROOT,
        orders_dir=tmp_path,
    )
    order = fold(read_events(result["task_id"], orders=tmp_path))
    assert (order.plan, order.step, order.plan_task, order.spec) == ("shop", "implement", "3", None)


def test_bad_plan_flags_write_nothing(tmp_path):
    result = create_order(
        OrderRequest(to_agent=WORKER, message="x", plan="shop"), root=ROOT, orders_dir=tmp_path
    )
    assert result == {"ok": False, "error": "usage_error: --plan and --step go together"}
    assert task_ids(orders=tmp_path) == []
