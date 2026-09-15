"""`lean-herdr plan check | next | show | brief` -- a plan run as the orchestrator and its workers see it.

One JSON line with `ok`, exit ALWAYS 0, like `dispatch` and `report`: the orchestrator reads
`ok`, not the exit code. What comes next is `planrun`'s decision; this module reads the log,
runs `plan check` where `planrun` needs its result, and prints.

`brief` is the one plain-text output (spec 6.2): the text a worker works from, or one line
on stderr with exit 1 -- a worker's shell reads the exit code, not JSON.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lean_herdr.bus import BusError, canonical_root
from lean_herdr.dispatch import UsageError, _Parser
from lean_herdr.orderlog import OrderLogError, read_events, state_dir, task_ids
from lean_herdr.orders import PLAN_SLUG_RE, Order, fold
from lean_herdr.plan import (
    Plan,
    PlanError,
    load_plan,
    outline,
    plan_branch,
    plan_path,
    read_source,
    run_git,
    show,
    structure,
)
from lean_herdr.planrun import next_step, task_summary
from lean_herdr.report import order_text
from lean_herdr.settings import (
    SETTINGS_PATH,
    STAGES,
    SettingsError,
    read_settings,
    settings_for,
    work_roles,
)
from lean_herdr.worktree import find_worktree

SUBCOMMANDS = ("check", "next", "show", "brief")

#: One brief per step, rendered whole in the worker's worktree (spec section 4).
BRIEFS_DIR = Path(".lean-ctx") / "lean-herdr" / "briefs"

RENDER_TIMEOUT_S = 60.0


class BriefError(Exception):
    """Why no brief could be put together -- the one line `plan brief` prints on stderr."""


def render(
    cwd: Path, path: str | Path, *, phase: str | None = None, runner: Any = subprocess.run
) -> str:
    """`lean-md render <path> [--phase <phase>] --consumer=ai` in `cwd`, stripped.

    `cwd` is the worker's worktree: imports and `@include` resolve against it, and a phase
    render writes to that worktree's lean-ctx session, which is wanted (spec section 6.5).
    """
    where = f"{path} --phase {phase}" if phase else str(path)
    cmd = ["lean-md", "render", str(path), *(["--phase", phase] if phase else []), "--consumer=ai"]
    try:
        proc = runner(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=RENDER_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise BriefError(f"render_failed: {where}: {exc}") from exc
    text = (proc.stdout or "").strip()
    if proc.returncode != 0 or not text:
        lines = (proc.stderr or "").strip().splitlines()
        raise BriefError(
            f"render_failed: {where}: {lines[0] if lines else f'exit {proc.returncode}'}"
        )
    return text


def _lines(cwd: Path, *args: str, runner: Any) -> list[str]:
    """The output lines of one git command in `cwd`; none when it fails."""
    proc = run_git(cwd, *args, runner=runner)
    return proc.stdout.splitlines() if proc is not None and proc.returncode == 0 else []


def _review_base(orders: list[Order], number: int, *, cwd: Path, runner: Any) -> tuple[str, str]:
    """`(sha, note)`: where task `number`'s changes start, and what stood in for a missing stamp.

    The `report start` head of the task's FIRST implement order; without it the `report done`
    head of the task before; without that the merge base with main (spec section 6.4).
    """
    implements = [o for o in orders if o.step == "implement" and o.plan_task == str(number)]
    first = implements[0].start_head if implements else None
    if first:
        return first, ""
    previous = [
        o.done_head or ""
        for o in orders
        if o.step == "implement" and o.plan_task == str(number - 1) and o.done_head
    ]
    if previous:
        return previous[
            -1
        ], f"(no start head on task {number}: the done head of task {number - 1} stands in)"
    base = _lines(cwd, "merge-base", "main", "HEAD", runner=runner)
    if not base:
        raise BriefError(f"no_base: task {number} has no start head, and no merge base with main")
    return base[0], f"(no start head on task {number}: the merge base with main stands in)"


def _diff_section(sha: str, note: str, *, cwd: Path, runner: Any) -> str:
    commits = _lines(cwd, "log", "--oneline", f"{sha}..HEAD", runner=runner)
    status = _lines(cwd, "status", "--porcelain", "--untracked-files=all", runner=runner)
    untracked = [line[3:] for line in status if line.startswith("?? ")]
    lines = ["## Diff", "", f"`wt step diff {sha}` {note}".rstrip(), "", "Commits:"]
    lines += [f"- {commit}" for commit in commits] or ["- none"]
    lines += ["", "Untracked files, in no commit:"]
    lines += [f"- {path}" for path in untracked] or ["- none"]
    return "\n".join(lines)


def _task_list(root: Path, slug: str, *, runner: Any) -> str:
    ref, text = read_source(root, slug, runner=runner)
    plan = structure(slug, ref, outline(root, text, runner=runner))
    return "\n".join(["## Tasks", "", *(f"- {task.title}" for task in plan.tasks)])


def _works(data: dict[str, Any]) -> str:
    """The works a plan may route to, with the role and model behind each -- no stages."""
    lines = ["## Works", ""]
    for work, role in sorted(work_roles(data).items()):
        if work not in STAGES:
            model = settings_for(role, data).model or "(runtime default)"
            lines.append(f"- `{work}` -> {role}, model {model}")
    return "\n".join(lines)


def _finding_line(finding: dict[str, Any]) -> str:
    where = f"line {finding['line']}" + (f" ({finding['phase']})" if "phase" in finding else "")
    return f"- [{finding['kind']}] {where}: {finding['message']}"


def compose_brief(
    order: Order,
    *,
    root: Path,
    cwd: Path,
    orders_dir: str | Path,
    data: dict[str, Any],
    runner: Any = subprocess.run,
) -> str:
    """The text a worker works from, for one plan order (spec section 6.5).

    `root` is the repository root (log, `git show`, `plan check`), `cwd` the worker's
    worktree (every render, the commit list, the untracked files).
    """
    if order.plan is None or order.step is None:
        raise BriefError(f"order {order.id} belongs to no plan")
    slug, step, task = order.plan, order.step, order.plan_task
    path = plan_path(slug)
    parts = [render(cwd, BRIEFS_DIR / f"{step}.lmd.md", runner=runner)]
    if step == "implement" and task != "branch":
        parts.append(render(cwd, path, phase=f"task-{task}", runner=runner))
    elif step == "implement":
        parts.append(render(cwd, path, phase="constraints", runner=runner))
    elif step == "review" and task != "branch":
        parts.append(render(cwd, path, phase="constraints", runner=runner))
        parts.append(render(cwd, path, phase=f"task-{task}", runner=runner))
        number = int(task or 0)
        sha, note = _review_base(
            plan_orders(slug, orders_dir=orders_dir), number, cwd=cwd, runner=runner
        )
        parts.append(_diff_section(sha, note, cwd=cwd, runner=runner))
    elif step == "review":
        parts.append(render(cwd, path, phase="constraints", runner=runner))
        parts.append(_task_list(root, slug, runner=runner))
        parts.append("## Diff\n\n`wt step diff` -- everything since the branch left main")
    elif step == "plan":
        parts.append(f"## Plan\n\n`{path}` on branch `{plan_branch(slug)}`\n\nSpec: `{order.spec}`")
        parts.append(_works(data))
    else:
        checked = check_result(root, slug, data, runner=runner)
        if "error" in checked:
            raise BriefError(str(checked["error"]))
        lines = ["## plan check", "", "Errors:"]
        lines += [_finding_line(finding) for finding in checked["errors"]] or ["- none"]
        lines += ["", "Warnings:"]
        lines += [_finding_line(finding) for finding in checked["warnings"]] or ["- none"]
        parts.append(f"## Plan\n\n`{path}` on branch `{plan_branch(slug)}`")
        parts.append("\n".join(lines))
    parts.append("## Order\n\n" + order_text(order, orders_dir=orders_dir))
    return "\n\n".join(parts)


def _brief_failed(message: str) -> int:
    sys.stderr.write(message + "\n")
    return 1


def brief_main(argv: list[str]) -> int:
    """`plan brief --task o-…`: the brief on stdout and exit 0, or one line on stderr and exit 1."""
    try:
        args = build_parser().parse_args(argv)
        complaint = missing_flags(args)
        if complaint:
            return _brief_failed(f"usage_error: {complaint}")
        cwd = Path.cwd()
        root = canonical_root(cwd)
        orders_dir = state_dir(root)
        order = fold(read_events(args.task, orders=orders_dir))
        if not order.state:
            return _brief_failed(f"task_not_found: {args.task}")
        data = _settings(root)
        text = compose_brief(order, root=root, cwd=cwd, orders_dir=orders_dir, data=data)
    except UsageError as exc:
        return _brief_failed(f"usage_error: {exc}")
    except SettingsError as exc:
        return _brief_failed(f"config_error: {exc}")
    except (BriefError, PlanError, OrderLogError, BusError) as exc:
        return _brief_failed(str(exc))
    except Exception as exc:  # noqa: BLE001 -- one line on stderr, never a traceback
        return _brief_failed(f"brief_crashed: {exc}")
    sys.stdout.write(text + "\n")
    return 0


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
    if args.command == "brief":
        if args.slug is not None:
            return "brief takes --task, not a slug"
        return None if args.task else "brief needs --task"
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
    """`check`, `next`, `show`: one JSON line on stdout, exit ALWAYS 0. `brief`: see brief_main."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["brief"]:
        return brief_main(arguments)
    result: dict[str, Any]
    try:
        args = build_parser().parse_args(arguments)
        if args.command == "brief":
            raise UsageError("brief comes first: lean-herdr plan brief --task o-…")
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


#: Spec section 3 in a few lines, for the plan-mode judge.
PLAN_RULES_SUMMARY = """Plan rules:
- phases `constraints` and `lanes` exist; tasks are `task-1` ... `task-N`, gapless, in document order
- the first `@call` of every task is `route(work, lane, files)`, and `files` is not empty
- `work` is routed in [routing] and is none of the stages plan, plan-review, review, integrate
- every lane is declared with `@call lane(name, deps)`; deps name declared lanes and form no cycle
- no task comes before a task of a lane its own lane depends on"""


@dataclass(frozen=True)
class PrereviewInput:
    """What the judge gets for one plan order (spec section 6.6) -- or why it gets nothing."""

    #: The text the judge reads as the order.
    order: str = ""
    #: The commit the diff starts at; None diffs since branching.
    base: str | None = None
    #: PLAN_PREREVIEW_PROMPT instead of PREREVIEW_PROMPT.
    plan: bool = False
    #: Set when this order gets no pre-review: the note beside `prereview: skipped`.
    skip: str | None = None


def _worktree_path(worktree_list: Any, branch: str | None) -> Path | None:
    try:
        entry = find_worktree(worktree_list or {}, branch or "")
    except AttributeError, TypeError:
        return None
    path = entry.get("path") if isinstance(entry, dict) else None
    return Path(path) if path else None


def prereview_input(
    order: Order,
    *,
    root: Path,
    branch: str | None,
    worktree_list: Any,
    runner: Any = subprocess.run,
) -> PrereviewInput:
    """The judge's order, diff base and prompt for a plan order. Never raises.

    `plan`: the spec read from main, plus the plan rules; the diff since branching is the
    plan. `implement` on a task: the rendered constraints and task, diffed from the order's
    own `report start` head. Every other step gets no pre-review.
    """
    if order.plan is None:
        return PrereviewInput(skip="no_plan_order")
    if order.step == "plan":
        spec = show(root, "main", order.spec, runner=runner) if order.spec else None
        if not spec:
            return PrereviewInput(skip="spec_unreadable")
        return PrereviewInput(order=f"{spec.strip()}\n\n{PLAN_RULES_SUMMARY}", plan=True)
    if order.step != "implement" or order.plan_task == "branch":
        return PrereviewInput(skip="no_prereview_for_step")
    if not order.start_head:
        return PrereviewInput(skip="no_start_head")
    path = _worktree_path(worktree_list, branch)
    if path is None:
        return PrereviewInput(skip="worktree_unresolved")
    try:
        text = "\n\n".join(
            render(path, plan_path(order.plan), phase=phase, runner=runner)
            for phase in ("constraints", f"task-{order.plan_task}")
        )
    except BriefError:
        return PrereviewInput(skip="render_failed")
    return PrereviewInput(order=text, base=order.start_head)
