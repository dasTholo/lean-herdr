"""A plan as data: read it off its branch, outline it with lean-md, check lean-herdr's rules.

`lean-md outline` parses the document; nothing here reads `@call` syntax itself. What is
left for this module is what only lean-herdr knows: the branch a plan lives on, the works
`[routing]` routes, and the rules of the spec's section 3.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from lean_herdr.settings import STAGES, SettingsError, role_for_work

PLANS_DIR = "docs/lean-md/plans"

#: The phases every plan carries besides its tasks.
REQUIRED_PHASES = ("constraints", "lanes")

TASK_PHASE_RE = re.compile(r"task-([1-9][0-9]*)")

GIT_TIMEOUT_S = 10.0
OUTLINE_TIMEOUT_S = 30.0

#: What a worker renders or reads inside the plan branch's worktree (spec section 4).
#: Role prompts and `bin/` are read from the repository root by `dispatch`, not from here.
BRANCH_FILES = (
    ".lean-ctx/lean-md.lock",
    ".lean-ctx/lean-md/plan-recipes.lmd.md",
    ".lean-ctx/lean-md/herdr-recipes.lmd.md",
    ".lean-ctx/lean-md/herdr-plan-template.lmd.md",
    ".lean-ctx/lean-md/lang/python.lmd.md",
    ".lean-ctx/lean-herdr/briefs/implement.lmd.md",
    ".lean-ctx/lean-herdr/briefs/review.lmd.md",
    ".lean-ctx/lean-herdr/briefs/plan.lmd.md",
    ".lean-ctx/lean-herdr/briefs/plan-review.lmd.md",
    ".claude/skills/lmd-writing-plans/SKILL.md",
    ".claude/skills/lmd-rendering-skills/SKILL.md",
)

#: A plan branch leaves these alone: `plan check` resolves them against the repository
#: root, a worker against the worktree, and both must read the same files.
TOOLING_DIRS = (".lean-ctx/lean-md/", ".lean-ctx/lean-herdr/briefs/")


class PlanError(Exception):
    """A plan that cannot be read at all. The message starts with its error code."""


@dataclass(frozen=True)
class Finding:
    kind: str
    message: str
    line: int = 0
    phase: str | None = None

    def as_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": self.kind, "line": self.line, "message": self.message}
        if self.phase is not None:
            out["phase"] = self.phase
        return out


@dataclass(frozen=True)
class Task:
    number: int
    title: str
    line: int
    #: The first `@call` of the phase is `route`; the three fields below come from it.
    routed: bool = False
    work: str = ""
    lane: str = ""
    files: tuple[str, ...] = ()


@dataclass(frozen=True)
class Plan:
    slug: str
    #: The ref the text was read from: `plan/<slug>`, `main`, or a commit.
    ref: str
    tasks: tuple[Task, ...]
    lanes: dict[str, tuple[str, ...]] = field(default_factory=dict)
    errors: tuple[Finding, ...] = ()
    warnings: tuple[Finding, ...] = ()


def plan_path(slug: str) -> str:
    return f"{PLANS_DIR}/{slug}.lmd.md"


def plan_branch(slug: str) -> str:
    return f"plan/{slug}"


def run_git(root: Path, *args: str, runner: Any) -> subprocess.CompletedProcess[str] | None:
    """One read-only git command in `root`. None when it cannot run at all."""
    try:
        return runner(
            ["git", *args],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=GIT_TIMEOUT_S,
            cwd=str(root),
            check=False,
        )
    except OSError, subprocess.SubprocessError, ValueError:
        return None


def show(root: Path, ref: str, path: str, *, runner: Any = subprocess.run) -> str | None:
    """`git show <ref>:<path>` -- None when the ref or the file is not there."""
    proc = run_git(root, "show", f"{ref}:{path}", runner=runner)
    return proc.stdout if proc is not None and proc.returncode == 0 else None


def read_source(
    root: Path, slug: str, *, ref: str | None = None, runner: Any = subprocess.run
) -> tuple[str, str]:
    """`(ref, text)` of the plan: `ref` when given, else `plan/<slug>`, else `main`.

    `main` carries the plan once the branch is merged and gone.
    """
    refs = (ref,) if ref else (plan_branch(slug), "main")
    for candidate in refs:
        text = show(root, candidate, plan_path(slug), runner=runner)
        if text is not None:
            return candidate, text
    raise PlanError(f"no_plan: {' and '.join(refs)} carry no {plan_path(slug)}")


def outline(root: Path, text: str, *, runner: Any = subprocess.run) -> dict[str, Any]:
    """`lean-md outline - --json --require-phase constraints,lanes`, run in `root`.

    The exit code is not read: 0 and 1 both carry the JSON. What proves the subcommand
    exists is the JSON itself -- lean-md 0.2.3 ends an unknown subcommand with exit 1 too.
    """
    unavailable = PlanError("config_error: lean-md outline unavailable (needs lean-md >= 0.2.4)")
    try:
        proc = runner(
            ["lean-md", "outline", "-", "--json", "--require-phase", ",".join(REQUIRED_PHASES)],
            input=text,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=OUTLINE_TIMEOUT_S,
            cwd=str(root),
            check=False,
        )
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise unavailable from exc
    try:
        data = json.loads(proc.stdout or "")
    except json.JSONDecodeError as exc:
        raise unavailable from exc
    if not isinstance(data, dict) or not isinstance(data.get("phases"), list):
        raise unavailable
    return data


def _args(call: dict[str, Any]) -> list[str]:
    return [str(arg) for arg in call.get("args") or []]


def structure(slug: str, ref: str, data: dict[str, Any]) -> Plan:
    """Tasks and lanes out of the outline, plus lean-md's own findings -- no rule of ours yet."""
    errors = tuple(
        Finding(
            kind=str(error.get("kind", "")),
            message=str(error.get("message", "")),
            line=int(error.get("line") or 0),
            phase=error.get("phase"),
        )
        for error in data.get("errors") or []
        if isinstance(error, dict)
    )
    tasks: list[Task] = []
    lanes: dict[str, tuple[str, ...]] = {}
    for phase in data.get("phases") or []:
        if not isinstance(phase, dict):
            continue
        name = str(phase.get("name", ""))
        calls = [call for call in phase.get("calls") or [] if isinstance(call, dict)]
        if name == "lanes":
            for call in calls:
                args = _args(call)
                if call.get("macro") == "lane" and args:
                    lanes[args[0]] = tuple(args[1].split()) if len(args) > 1 else ()
            continue
        hit = TASK_PHASE_RE.fullmatch(name)
        if hit is None:
            continue
        title, line = str(phase.get("title", "")), int(phase.get("line") or 0)
        if not calls or calls[0].get("macro") != "route":
            tasks.append(Task(int(hit.group(1)), title, line))
            continue
        args = _args(calls[0])
        tasks.append(
            Task(
                int(hit.group(1)),
                title,
                line,
                routed=True,
                work=args[0] if len(args) > 0 else "",
                lane=args[1] if len(args) > 1 else "",
                files=tuple(args[2].split()) if len(args) > 2 else (),
            )
        )
    return Plan(slug=slug, ref=ref, tasks=tuple(tasks), lanes=lanes, errors=errors)


def _reach(lanes: dict[str, tuple[str, ...]]) -> dict[str, set[str]]:
    """Every declared lane each lane depends on, directly or through another one."""
    reach: dict[str, set[str]] = {}
    for lane, deps in lanes.items():
        seen: set[str] = set()
        stack = list(deps)
        while stack:
            dep = stack.pop()
            if dep in seen or dep not in lanes:
                continue
            seen.add(dep)
            stack.extend(lanes[dep])
        reach[lane] = seen
    return reach


def rule_findings(plan: Plan, data: dict[str, Any]) -> tuple[list[Finding], list[Finding]]:
    """The rules of spec section 3 that need no git: `(errors, warnings)`."""
    errors: list[Finding] = []
    warnings: list[Finding] = []
    if not plan.tasks:
        errors.append(Finding("no_tasks", "the plan has no task-N phase"))
    for index, task in enumerate(plan.tasks, start=1):
        phase = f"task-{task.number}"
        if task.number != index:
            errors.append(
                Finding(
                    "task_order", f"{phase} stands where task-{index} belongs", task.line, phase
                )
            )
        if not task.routed:
            errors.append(
                Finding(
                    "no_route",
                    f"{phase} does not start with @call route(work, lane, files)",
                    task.line,
                    phase,
                )
            )
            continue
        if task.work in STAGES:
            errors.append(
                Finding(
                    "stage_as_work",
                    f"{phase}: {task.work!r} is a stage of a plan run, not a work",
                    task.line,
                    phase,
                )
            )
        else:
            try:
                role_for_work(task.work, data)
            except SettingsError:
                errors.append(
                    Finding(
                        "unknown_work",
                        f"{phase}: no role for work {task.work!r} in [routing]",
                        task.line,
                        phase,
                    )
                )
        if task.lane not in plan.lanes:
            errors.append(
                Finding(
                    "unknown_lane",
                    f"{phase}: lane {task.lane!r} is not declared in the lanes phase",
                    task.line,
                    phase,
                )
            )
        if not task.files:
            errors.append(Finding("no_files", f"{phase}: route names no files", task.line, phase))
    for lane, deps in sorted(plan.lanes.items()):
        for dep in deps:
            if dep not in plan.lanes:
                errors.append(
                    Finding(
                        "unknown_lane",
                        f"lane {lane!r} depends on undeclared lane {dep!r}",
                        0,
                        "lanes",
                    )
                )
    reach = _reach(plan.lanes)
    for lane in sorted(plan.lanes):
        if lane in reach[lane]:
            errors.append(Finding("lane_cycle", f"lane {lane!r} depends on itself", 0, "lanes"))
    for position, task in enumerate(plan.tasks):
        later = {other.lane for other in plan.tasks[position + 1 :]}
        blocking = sorted(later & reach.get(task.lane, set()))
        if task.routed and blocking:
            errors.append(
                Finding(
                    "order_vs_deps",
                    f"task-{task.number} (lane {task.lane!r}) comes before a task of lane {blocking[0]!r} it depends on",
                    task.line,
                    f"task-{task.number}",
                )
            )
    owners: dict[str, set[str]] = {}
    for task in plan.tasks:
        for path in task.files:
            owners.setdefault(path, set()).add(task.lane)
    for path, lanes in sorted(owners.items()):
        ordered = sorted(lanes)
        unrelated = [
            (a, b)
            for i, a in enumerate(ordered)
            for b in ordered[i + 1 :]
            if b not in reach.get(a, set()) and a not in reach.get(b, set())
        ]
        if unrelated:
            a, b = unrelated[0]
            warnings.append(
                Finding(
                    "lane_overlap",
                    f"{path} is touched by lanes {a!r} and {b!r}, and neither depends on the other",
                )
            )
    return errors, warnings


def branch_findings(root: Path, plan: Plan, *, runner: Any = subprocess.run) -> list[Finding]:
    """What the plan branch lacks or changes that its workers need unchanged from main."""
    if plan.ref == "main":
        return []
    errors: list[Finding] = []
    for path in BRANCH_FILES:
        proc = run_git(root, "cat-file", "-e", f"{plan.ref}:{path}", runner=runner)
        if proc is None or proc.returncode != 0:
            errors.append(
                Finding(
                    "missing_on_branch",
                    f"{plan.ref} carries no {path} -- commit the output of `lean-herdr workspace init` on main",
                )
            )
    proc = run_git(
        root, "diff", "--name-only", f"main...{plan.ref}", "--", *TOOLING_DIRS, runner=runner
    )
    changed = proc.stdout.split() if proc is not None and proc.returncode == 0 else []
    for path in changed:
        errors.append(
            Finding(
                "branch_touches_tooling",
                f"{plan.ref} changes {path}; plan branches leave the tooling to main",
            )
        )
    return errors


def load_plan(
    root: Path,
    slug: str,
    data: dict[str, Any],
    *,
    ref: str | None = None,
    runner: Any = subprocess.run,
) -> Plan:
    """Read, outline and check one plan. Raises PlanError when it cannot be read at all."""
    found, text = read_source(root, slug, ref=ref, runner=runner)
    plan = structure(slug, found, outline(root, text, runner=runner))
    errors, warnings = rule_findings(plan, data)
    errors += branch_findings(root, plan, runner=runner)
    ordered = sorted([*plan.errors, *errors], key=lambda finding: (finding.line, finding.kind))
    return replace(plan, errors=tuple(ordered), warnings=tuple(warnings))
