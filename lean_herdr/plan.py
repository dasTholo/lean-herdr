"""A plan as data: read it off its branch, outline it with lean-md, check lean-herdr's rules.

`lean-md outline` parses the document; nothing here reads `@call` syntax itself. What is
left for this module is what only lean-herdr knows: the branch a plan lives on, the works
`[routing]` routes, and the rules of the spec's section 3.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PLANS_DIR = "docs/lean-md/plans"

#: The phases every plan carries besides its tasks.
REQUIRED_PHASES = ("constraints", "lanes")

TASK_PHASE_RE = re.compile(r"task-([1-9][0-9]*)")

GIT_TIMEOUT_S = 10.0
OUTLINE_TIMEOUT_S = 30.0


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
