"""`lean-herdr plan check | next | show` -- a plan run as the orchestrator sees it.

One JSON line with `ok`, exit ALWAYS 0, like `dispatch` and `report`: the orchestrator reads
`ok`, not the exit code. What comes next is `planrun`'s decision; this module reads the log,
runs `plan check` where `planrun` needs its result, and prints.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from lean_herdr.bus import BusError, canonical_root
from lean_herdr.dispatch import UsageError, _Parser
from lean_herdr.orderlog import OrderLogError, read_events, state_dir, task_ids
from lean_herdr.orders import PLAN_SLUG_RE, Order, fold
from lean_herdr.plan import Plan, PlanError, load_plan, plan_path, show
from lean_herdr.planrun import next_step, task_summary
from lean_herdr.settings import SETTINGS_PATH, SettingsError, read_settings, work_roles

SUBCOMMANDS = ("check", "next", "show")


def plan_orders(slug: str, *, orders_dir: str | Path) -> list[Order]:
    """This plan's orders, oldest first -- `task_ids` lists the log newest first."""
    folded = (
        fold(read_events(task_id, orders=orders_dir))
        for task_id in reversed(task_ids(orders=orders_dir))
    )
    return [order for order in folded if order.plan == slug]


def _findings(plan: Plan) -> dict[str, Any]:
    return {
        "errors": [finding.as_json() for finding in plan.errors],
        "warnings": [finding.as_json() for finding in plan.warnings],
    }


def check_result(
    root: Path, slug: str, data: dict[str, Any], *, runner: Any = subprocess.run
) -> dict[str, Any]:
    """`plan check`: the committed plan against lean-md and spec section 3. Warnings never cost `ok`."""
    try:
        plan = load_plan(root, slug, data, runner=runner)
    except PlanError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": not plan.errors, "slug": slug, "ref": plan.ref, **_findings(plan)}


def _checks(
    root: Path, slug: str, data: dict[str, Any], orders: list[Order], *, runner: Any
) -> dict[str, list[dict[str, Any]]]:
    """The errors of `plan check` at the head each completed plan order reported done on.

    Without a stamped head the branch tip stands in. A head that carries no plan is a
    finding of its own; any other PlanError -- lean-md without `outline` -- propagates.
    """
    checks: dict[str, list[dict[str, Any]]] = {}
    for order in orders:
        if order.step != "plan" or order.state != "completed":
            continue
        try:
            plan = load_plan(root, slug, data, ref=order.done_head, runner=runner)
        except PlanError as exc:
            if not str(exc).startswith("no_plan:"):
                raise
            checks[order.id] = [{"kind": "no_plan", "line": 0, "message": str(exc)}]
            continue
        checks[order.id] = [finding.as_json() for finding in plan.errors]
    return checks


def next_result(
    root: Path,
    slug: str,
    data: dict[str, Any],
    *,
    orders_dir: str | Path,
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    """`plan next`: one step for the orchestrator (spec section 6.4)."""
    orders = plan_orders(slug, orders_dir=orders_dir)
    if show(root, "main", plan_path(slug), runner=runner) is not None:
        return {"ok": True, **next_step(None, orders, checks={}, merged=True)}
    try:
        checks = _checks(root, slug, data, orders, runner=runner)
    except PlanError as exc:
        return {"ok": False, "error": str(exc)}
    plan: Plan | None
    try:
        plan = load_plan(root, slug, data, runner=runner)
    except PlanError as exc:
        if not str(exc).startswith("no_plan:"):
            return {"ok": False, "error": str(exc)}
        plan = None
    return {"ok": True, **next_step(plan, orders, checks=checks, merged=False)}


def show_result(
    root: Path,
    slug: str,
    data: dict[str, Any],
    *,
    orders_dir: str | Path,
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    """`plan show`: the plan's tasks with state, rounds and orders -- for the orchestrator and a human."""
    try:
        plan = load_plan(root, slug, data, runner=runner)
    except PlanError as exc:
        return {"ok": False, "error": str(exc)}
    orders = plan_orders(slug, orders_dir=orders_dir)
    return {
        "ok": True,
        "slug": slug,
        "ref": plan.ref,
        "planning": [
            {"task_id": order.id, "step": order.step, "state": order.state}
            for order in orders
            if order.step in ("plan", "plan-review")
        ],
        "tasks": task_summary(plan, orders),
        **_findings(plan),
    }


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(prog="lean-herdr plan", description="Check a plan and steer its run.")
    p.add_argument("command", choices=SUBCOMMANDS)
    p.add_argument(
        "slug",
        nargs="?",
        default=None,
        help="the plan: docs/lean-md/plans/<slug>.lmd.md on plan/<slug>",
    )
    p.add_argument("--task", default=None, help="brief: the order id")
    return p


def missing_flags(args: argparse.Namespace) -> str | None:
    if args.task is not None:
        return f"{args.command} does not take --task"
    if args.slug is None:
        return f"{args.command} needs a slug"
    if not PLAN_SLUG_RE.fullmatch(args.slug):
        return f"{args.slug!r} is no plan slug ({PLAN_SLUG_RE.pattern})"
    return None


def _settings(root: Path) -> dict[str, Any]:
    """config.toml with `[routing]` validated: a broken table is `config_error`, not `unknown_work`."""
    data = read_settings(root / SETTINGS_PATH)
    work_roles(data)
    return data


def _run(args: argparse.Namespace) -> dict[str, Any]:
    root = canonical_root()
    data = _settings(root)
    if args.command == "check":
        return check_result(root, args.slug, data)
    if args.command == "next":
        return next_result(root, args.slug, data, orders_dir=state_dir(root))
    return show_result(root, args.slug, data, orders_dir=state_dir(root))


def main(argv: list[str] | None = None) -> int:
    """`check`, `next`, `show`: one JSON line on stdout, exit ALWAYS 0."""
    result: dict[str, Any]
    try:
        args = build_parser().parse_args(argv)
        complaint = missing_flags(args)
        result = {"ok": False, "error": f"usage_error: {complaint}"} if complaint else _run(args)
    except UsageError as exc:
        result = {"ok": False, "error": f"usage_error: {exc}"}
    except SettingsError as exc:
        result = {"ok": False, "error": f"config_error: {exc}"}
    except (OrderLogError, BusError) as exc:
        result = {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 -- never abort the caller
        result = {"ok": False, "error": f"plan_crashed: {exc}"}
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    return 0
