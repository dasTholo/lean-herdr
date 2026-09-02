"""One dispatch = one call.

Pure mechanics: the script asks no model and makes no assignment decision.
Who gets which task is decided by the orchestrator, before it comes in
here.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from lean_herdr.bus import (
    BusError,
    agents_in_registry,
    canonical_root,
    read_registry,
)
from lean_herdr.export import session_error, session_id_from_agent_list
from lean_herdr.herdr import Herdr
from lean_herdr.join import resolve_agent_id
from lean_herdr.settings import (
    DEFAULT_PROFILE,
    PROFILE_BY_ROLE,
    SETTINGS_PATH,
    RoleSettings,
    SettingsError,
    read_settings,
    settings_for,
)
from lean_herdr.tasks import (
    Task,
    TaskError,
    find_task,
    message_from,
    read_tasks,
    task_store_path,
)
from lean_herdr.worktree import (
    WorktreeOpenFailed,
    WorktrunkMissing,
    anchor_pane,
    ensure_worktree,
    find_worktree,
)

#: Derived, not copied: production reads `cfg.ready_timeout_s`, so a second
#: literal here would drift away from the real default unnoticed.
AGENT_READY_TIMEOUT_S = RoleSettings.ready_timeout_s
AGENT_READY_INTERVAL_S = 0.5

#: The wait mode asks the file, not the CLI: no process start per round.
POLL_INTERVAL_S = 1.0

#: How long `--await` waits without the flag. One value for the parser AND
#: for AwaitRequest -- two copies would drift apart unnoticed.
DEFAULT_TIMEOUT_MS = 300_000

#: Exactly one ring per wait call. The payload lives in the task store.
#: Worded neutrally, because the same text also wakes a task resumed after a
#: question -- then it is not new. And it points at `get`, not `list`: only
#: `get` prints the history that carries the orchestrator's answer. English,
#: like the role prompt it is spoken into.
WAKE_PROMPT = "Task {task_id} is waiting for you -- ctx_task get shows order and history."

#: Machine-readable verdict on the FIRST line of the completion message.
#: Replaces the bus field `category` that fell away: without it the
#: orchestrator would have to read prose to tell 'can be merged' from 'must
#: go back' -- exactly what this design rules out. `failed` will not do: a
#: reasoned rejection is not a failure. `VERDIKT:` is a protocol token, not
#: prose: roles/reviewer.md writes exactly this literal, and every review
#: already written carries it -- so it stays as it is, English role prompts or
#: not. `VERDICT:` is deliberately NOT accepted.
VERDICT_RE = re.compile(r"VERDIKT:\s*(result|reject)\s*$")


@dataclass(frozen=True)
class DispatchRequest:
    role: str
    kind: str
    model: str
    role_file: Path
    worktree: str | None = None
    profile: str | None = None


def profile_for(
    role: str, override: str | None = None, *, settings: RoleSettings | None = None
) -> str:
    """CLI flag beats file beats built-in default."""
    return override or (
        settings or RoleSettings(profile=PROFILE_BY_ROLE.get(role, DEFAULT_PROFILE))
    ).profile


def agent_name(
    role: str, worktree: str | None = None, *, settings: RoleSettings | None = None
) -> str:
    """The reuse key is (branch, role), never the branch alone.

    One worktree carries several workers -- builder and reviewer -- and a
    reviewer dispatch onto the same branch must never hit the running
    builder. That the template carries both placeholders is checked by
    settings.py at load time; here they are only filled in.
    """
    if not worktree:
        return role
    template = (settings or RoleSettings()).name_template
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", worktree).strip("-").lower()
    return template.format(role=role, branch=slug)


def agent_args(kind: str, model: str, role_file: Path) -> list[str]:
    """Native arguments. Role prompts travel as a FILE, never as text (H2)."""
    if kind == "claude":
        return ["--model", model, "--append-system-prompt-file", str(role_file)]
    if kind == "opencode":
        # With opencode the role prompt hangs on agent.<name>.prompt in
        # opencode.jsonc; here only the agent is picked.
        return ["--model", model, "--agent", role_file.stem]
    raise ValueError(f"unknown kind: {kind}")


def default_registry_path() -> Path:
    """The registry NEXT TO the task store -- same install, same resolution.

    `bus.REGISTRY_PATH` is the hardcoded XDG default, while
    `tasks.task_store_path()` honours `LEAN_CTX_DATA_DIR`, a legacy
    `~/.lean-ctx` and `XDG_*`. Both name the SAME `agents/` directory, so
    without this the build mode read an absent registry -- a full
    `ready_timeout_s` stall ending in `no_agent_id` -- exactly where the wait
    mode read the right store.
    """
    return task_store_path().parent / "registry.json"


def wait_for_agent_id(
    herdr: Herdr,
    name: str,
    *,
    registry_path: str | Path | None = None,
    timeout_s: float = AGENT_READY_TIMEOUT_S,
    interval_s: float = AGENT_READY_INTERVAL_S,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> str | None:
    """Wait for the MCP server of the freshly started agent.

    Blocks in the shell call, not in the model -- that is the cheap part.
    """
    path = registry_path if registry_path is not None else default_registry_path()
    deadline = now() + timeout_s
    while True:
        agents = herdr.agent_list()
        pane = next((a.get("pane_id") for a in agents if a.get("name") == name), None)
        if pane:
            info = herdr.pane_process_info(str(pane))
            try:
                registry = read_registry(path)
            except BusError:
                registry = {}
            agent_id = resolve_agent_id(
                agents, info, agents_in_registry(registry), name=name
            )
            if agent_id:
                return agent_id
        if now() >= deadline:
            return None
        sleep(interval_s)


def _result(
    ok: bool, pane: str | None, agent_id: str | None, **rest: Any
) -> dict[str, Any]:
    return {"ok": ok, "pane": pane, "agent_id": agent_id, **rest}


def dispatch(
    req: DispatchRequest,
    *,
    herdr: Herdr,
    root: Path,
    cwd: Path | None = None,
    registry_path: str | Path | None = None,
    waiter: Callable[..., str | None] = wait_for_agent_id,
    settings: RoleSettings | None = None,
) -> dict[str, Any]:
    """Build one worker. Never raises; the result carries `ok`.

    Creates NO task and does not wait. This process can do neither:
    `ctx_task create` requires a registered, long-lived MCP agent
    (tools/ctx_task.rs:12), and a `lean-ctx call` is exactly not that.
    """
    cfg = settings or RoleSettings(profile=PROFILE_BY_ROLE.get(req.role, DEFAULT_PROFILE))
    name = agent_name(req.role, req.worktree, settings=cfg)
    target_cwd = cwd if cwd is not None else root
    # None means: split in our own workspace (--current). Only the worktree
    # case sets an anchor.
    target_pane: str | None = None
    if req.worktree:
        try:
            target = ensure_worktree(req.worktree, herdr=herdr, cwd=root)
        except WorktrunkMissing:
            return _result(False, None, None, error="worktrunk_missing")
        except WorktreeOpenFailed as exc:
            # Do not carry on: a pane in the right directory that teardown
            # does not know about is worse than a clean abort.
            return _result(False, None, None, error=f"worktree_open_failed: {exc}")
        target_cwd = target.path
        target_pane = anchor_pane(herdr, target.workspace_id)
        if target_pane is None:
            return _result(False, None, None, error="no_anchor_pane")

    existing = next((a for a in herdr.agent_list() if a.get("name") == name), None)
    if existing:
        pane = str(existing.get("pane_id") or "")
        # Reset between two tasks: /clear caps the context at the base load
        # and triggers NO lifecycle change (H4).
        herdr.agent_prompt(name, "/clear", wait=False)
    else:
        pane = herdr.pane_split(
            target_cwd,
            pane=target_pane,
            direction=cfg.direction,
            ratio=cfg.ratio,
            focus=cfg.focus,
            env={
                "LEAN_CTX_TOOL_PROFILE": profile_for(
                    req.role, req.profile, settings=cfg
                ),
                "LEAN_CTX_ROLE": req.role,
            },
        ) or ""
        if not pane:
            return _result(False, None, None, error="pane_split_failed")
        herdr.agent_start(
            name,
            kind=req.kind,
            pane=pane,
            agent_args=agent_args(req.kind, req.model, req.role_file),
        )

    agent_id = waiter(
        herdr, name, registry_path=registry_path, timeout_s=cfg.ready_timeout_s
    )
    if not agent_id:
        return _result(False, pane, None, error="no_agent_id")
    # This is the end. The orchestrator creates the task itself through
    # ctx_task, with exactly this agent_id as to_agent: tasks_for_agent()
    # compares exactly as a string (core/a2a/task.rs:236), a friendly name
    # would never find the task.
    return _result(True, pane, agent_id)


@dataclass(frozen=True)
class AwaitRequest:
    role: str
    kind: str
    task_id: str
    worktree: str | None = None
    timeout_ms: int = DEFAULT_TIMEOUT_MS


def verdict(message: str | None) -> str | None:
    """`VERDIKT: result` or `VERDIKT: reject` on the FIRST line -- else None.

    First line only, so that quoting the same words further down in the
    reasoning cannot flip the verdict.
    """
    lines = (message or "").lstrip().splitlines()
    hit = VERDICT_RE.match(lines[0]) if lines else None
    return hit.group(1) if hit else None


def _worker_root(worktree: str | None, *, herdr: Herdr, root: Path) -> Path:
    """The directory a worker of this dispatch runs in.

    The build mode splits its pane in `ensure_worktree(...).path` and
    `claude_session_path()` slugs exactly that cwd into
    `~/.claude/projects/<slug>`. Looking for a worktree worker's error under
    the repo-root slug would never find it, and every crash would come back
    as `no_reply` -- which the orchestrator retries instead of escalating.

    Falls back to the root when the worktree cannot be resolved: a missing
    reason is bad, an exception out of the wait mode would be worse.

    Read-only: this only runs on the timeout path, purely to locate a log --
    never to fix the situation. It looks the branch up via `worktree_list()`
    / `find_worktree()` instead of `ensure_worktree()`, which would CREATE a
    worktree that a failed build or a cleaned-up workspace left missing. A
    wait call must not create anything as a side effect of diagnosing one.
    """
    if not worktree:
        return root
    try:
        eintrag = find_worktree(herdr.worktree_list(root), worktree)
        pfad = eintrag.get("path") if isinstance(eintrag, dict) else None
    except (TypeError, AttributeError, KeyError):
        return root
    return Path(pfad) if pfad else root


def _await_result(ok: bool, task_id: str, **rest: Any) -> dict[str, Any]:
    return {"ok": ok, "task_id": task_id, **rest}


def _result_for_state(task: Task) -> dict[str, Any] | None:
    """The return for this state -- or None if we keep waiting.

    `input-required` returns even though is_terminal() does not call it
    terminal: only the orchestrator can answer, and it is asleep inside this
    very call. Without this return the script would wait for something that
    cannot happen without it.
    """
    message = message_from(task, task.to_agent)
    if task.state == "completed":
        result = _await_result(
            True, task.id, state=task.state, message=message or ""
        )
        ruling = verdict(message)
        if ruling:
            result["verdict"] = ruling
        return result
    if task.state == "failed":
        return _await_result(
            False,
            task.id,
            state=task.state,
            error=f"agent_failed: {message or 'no reason given'}",
        )
    if task.state == "canceled":
        return _await_result(False, task.id, state=task.state, error="task_canceled")
    if task.state == "input-required":
        return _await_result(
            False,
            task.id,
            state=task.state,
            error="input_required",
            message=message or "",
        )
    return None


def await_task(
    req: AwaitRequest,
    *,
    herdr: Herdr,
    root: Path,
    tasks_path: str | Path | None = None,
    interval_s: float = POLL_INTERVAL_S,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
    settings: RoleSettings | None = None,
) -> dict[str, Any]:
    """Wait for the state change the worker sets itself.

    The waiting stays in the script: no CLI, no registration, no model step
    per round. Never raises; the result carries `ok`.

    `settings` MUST be the same one the build mode got -- it decides the
    agent's name, and a ring under a different name reaches nobody.
    """
    name = agent_name(req.role, req.worktree, settings=settings)
    deadline = now() + req.timeout_ms / 1000.0
    has_rung = False
    state = ""
    while True:
        try:
            tasks = read_tasks(tasks_path)
        except TaskError as exc:
            return _await_result(
                False, req.task_id, error=f"tasks_unreadable: {exc}"
            )
        task = find_task(tasks, req.task_id)
        if task is None:
            # The orchestrator created the task BEFORE this call, and
            # ctx_task renames the finished file into place before it
            # answers (core/a2a/task.rs:213). Missing here means the id is
            # wrong -- waiting will not change that.
            return _await_result(False, req.task_id, error="task_not_found")
        state = task.state
        outcome = _result_for_state(task)
        if outcome is not None:
            return outcome
        if not has_rung:
            # Exactly once, and without --wait: whoever sleeps through the
            # first ring will not wake for the second. That is what the
            # timeout is for.
            herdr.agent_prompt(
                name, WAKE_PROMPT.format(task_id=req.task_id), wait=False
            )
            has_rung = True
        if now() >= deadline:
            break
        sleep(interval_s)

    # No state change before the deadline. The truth lives in the session
    # store, not in the lifecycle (H1): a crashed worker leaves the task
    # sitting on `created` or `working`.
    error = session_error(
        req.kind,
        session_id_from_agent_list(herdr.agent_list(), name),
        _worker_root(req.worktree, herdr=herdr, root=root),
    )
    if error:
        return _await_result(
            False, req.task_id, state=state, error=f"agent_error: {error}"
        )
    return _await_result(False, req.task_id, state=state, error="no_reply")


class UsageError(Exception):
    """A parser complaint -- raised instead of ending the process."""


class _Parser(argparse.ArgumentParser):
    """argparse ends a usage error with exit 2 and one line on stderr.

    Same reason as missing_flags(): the orchestrator reads `ok` on stdout and
    would see no output at all. A missing `--kind`, a missing `role`, an
    invalid choice and an unknown flag all run through error(), so redirecting
    it alone gives every operator error one shape. `--help` goes through
    exit(), not error(), and stays untouched.
    """

    def error(self, message: str) -> NoReturn:
        raise UsageError(message)


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(
        prog="herdr-dispatch", description="Build or wait -- one call."
    )
    p.add_argument("role", help="builder | reviewer | orchestrator")
    p.add_argument("--kind", required=True, choices=("claude", "opencode"))
    # `--await` would yield the dest `await` -- a keyword, unreachable as
    # args.await. The dest MUST be set.
    p.add_argument(
        "--await",
        dest="waiting",
        action="store_true",
        help="wait for a task to finish instead of building a worker",
    )
    p.add_argument("--task-id", default=None, help="required with --await")
    p.add_argument("--model", default=None, help="required in build mode")
    p.add_argument(
        "--role-file", default=None, type=Path, help="required in build mode"
    )
    p.add_argument(
        "--worktree", default=None, help="branch; the pane runs in its worktree"
    )
    p.add_argument(
        "--profile", default=None, help="overrides the role's default profile"
    )
    # `default=None`, not the number: only that tells a `--timeout-ms` given
    # in build mode from one left out. main() fills the value in.
    p.add_argument(
        "--timeout-ms",
        type=int,
        default=None,
        help=f"only with --await (default {DEFAULT_TIMEOUT_MS})",
    )
    return p


def _given(*pairs: tuple[str, Any]) -> str:
    """The flags of that list that were actually given, as one phrase."""
    return " and ".join(flag for flag, value in pairs if value is not None)


def missing_flags(args: argparse.Namespace) -> str | None:
    """Mode-dependent flag validation -- deliberately NOT via argparse.

    `required=True` ends the process with exit 2 and one line on stderr.
    The orchestrator reads `ok` on stdout; a typo would look to it like no
    output at all.

    The same holds for the flags of the OTHER mode: argparse accepts every
    one of them in both, and the mode that does not read them drops them
    without a word -- `--timeout-ms` in build mode, though its own help says
    "only with --await", and `--model`/`--role-file`/`--profile` under
    `--await`. A non-positive `--timeout-ms` bought exactly one ring and an
    immediate `no_reply`.
    """
    if args.waiting:
        if not args.task_id:
            return "--await needs --task-id"
        stray = _given(
            ("--model", args.model),
            ("--role-file", args.role_file),
            ("--profile", args.profile),
        )
        if stray:
            return f"--await does not take {stray}"
        if args.timeout_ms is not None and args.timeout_ms <= 0:
            return f"--timeout-ms must be positive, not {args.timeout_ms}"
        return None
    missing = [
        flag
        for flag, value in (("--model", args.model), ("--role-file", args.role_file))
        if not value
    ]
    if missing:
        return f"build mode needs {' and '.join(missing)}"
    stray = _given(("--timeout-ms", args.timeout_ms))
    return f"build mode does not take {stray}" if stray else None


def main(argv: list[str] | None = None) -> int:
    """Output: one JSON line on stdout. Exit ALWAYS 0.

    The orchestrator reads `ok`, not the exit code -- so a failure does not
    abort its shell call.
    """
    result: dict[str, Any]
    try:
        args = build_parser().parse_args(argv)
        missing = missing_flags(args)
        if missing:
            result = {"ok": False, "error": f"usage_error: {missing}"}
        else:
            # Read once, hand to both modes: the wait mode has to ring the
            # agent the build mode started, and the name comes from here.
            # SETTINGS_PATH is RELATIVE -- anchored on anything but the
            # canonical root the file would silently not be found as soon as
            # bin/herdr-dispatch runs from a subdirectory or a worktree.
            # A SettingsError is caught below and reaches the caller as
            # `config_error: <reason>` -- an operator's wrong config value is
            # not a crash.
            root = canonical_root()
            settings = settings_for(args.role, read_settings(root / SETTINGS_PATH))
            if args.waiting:
                result = await_task(
                    AwaitRequest(
                        role=args.role,
                        kind=args.kind,
                        task_id=args.task_id,
                        worktree=args.worktree,
                        timeout_ms=args.timeout_ms or DEFAULT_TIMEOUT_MS,
                    ),
                    herdr=Herdr(),
                    root=root,
                    settings=settings,
                )
            else:
                result = dispatch(
                    DispatchRequest(
                        role=args.role,
                        kind=args.kind,
                        model=args.model,
                        role_file=args.role_file,
                        worktree=args.worktree,
                        profile=args.profile,
                    ),
                    herdr=Herdr(),
                    root=root,
                    cwd=root,
                    settings=settings,
                )
    except UsageError as exc:
        result = {"ok": False, "error": f"usage_error: {exc}"}
    except SettingsError as exc:
        result = {"ok": False, "error": f"config_error: {exc}"}
    except Exception as exc:  # noqa: BLE001 -- never abort the caller
        result = {"ok": False, "error": f"dispatch_crashed: {exc}"}
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    return 0
