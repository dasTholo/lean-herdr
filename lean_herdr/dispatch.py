"""One dispatch = one call.

Pure mechanics: the script asks no model and makes no assignment decision.
Who gets which task is decided by the orchestrator, before it comes in
here.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from lean_herdr import llm, openrouter
from lean_herdr.bus import (
    BusError,
    agents_in_registry,
    canonical_root,
    read_registry,
)
from lean_herdr.export import session_error, session_id_from_agent_list
from lean_herdr.herdr import (
    FIRST_START_TIMEOUT_MS,
    Herdr,
    start_agent,
    timeout_ms_for,
)
from lean_herdr.join import resolve_agent_id
from lean_herdr.leanctx import LeanCtx

# The write path lives next door since this file grew past comfort (plan 3g).
# Not because it crossed the 800-production-LOC ceiling -- it never has; the
# split happened at 371 production LOC and the file has been readable since.
# `order_result` went with it -- both sides need that result shape, and
# keeping it here would have made the import circular. Public, not
# `_await_result`: a name imported across a module boundary must not claim
# to be private, and the shape serves the write path as much as the wait.
from lean_herdr.ordercmd import (
    ORCHESTRATOR_AGENT,
    OrderRequest,
    answer_order,
    cancel_order,
    create_order,
    order_result,
)
from lean_herdr.orderlog import OrderLogError, lean_ctx_data_dir, read_events, state_dir
from lean_herdr.orders import Order, fold, message_from
from lean_herdr.settings import (
    DEFAULT_PROFILE,
    KINDS,
    PROFILE_BY_ROLE,
    SETTINGS_PATH,
    LlmSettings,
    RoleSettings,
    SettingsError,
    llm_settings,
    model_warnings,
    read_settings,
    settings_for,
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

#: The two variables the build mode stamps on the pane it splits and
#: `lean-herdr report` reads back out of its environment. ONE definition each
#: (M3): report.py IMPORTS these names rather than spelling the strings a
#: second time, and the `env=` dict of the pane split below is built from
#: them. A second spelling on either side is silent in the worst way --
#: the pane carries one variable, the worker reads another, every order
#: runs into the void and the wait mode reports `no_reply`.
AGENT_ENV = "LEAN_HERDR_AGENT"
ROLE_ENV = "LEAN_CTX_ROLE"

#: How long `--await` waits without the flag. One value for the parser AND
#: for AwaitRequest -- two copies would drift apart unnoticed.
DEFAULT_TIMEOUT_MS = 300_000

#: Exactly one ring per wait call. The payload lives in the order log.
#: Worded neutrally, because the same text also wakes a worker whose order
#: continues after a question -- then it is not new. English, like the role
#: prompt it is spoken into.
WAKE_PROMPT = (
    "Order {task_id} is waiting for you -- lean-herdr report next shows it, "
    "lean-herdr report show --task {task_id} its history."
)

#: Words the positional slot takes INSTEAD of a role. They write into the
#: log: no worker, no kind, no model, no worktree. Every other value is a
#: role and builds one or waits for one. (`remember` joins them in task 5.)
LOG_COMMANDS = ("order", "answer", "cancel", "remember")

#: Machine-readable verdict on the FIRST line of the completion message.
#: Replaces the bus field `category` that fell away: without it the
#: orchestrator would have to read prose to tell 'can be merged' from 'must
#: go back' -- exactly what this design rules out. `failed` will not do: a
#: reasoned rejection is not a failure. `VERDIKT:` is a protocol token, not
#: prose: .lean-ctx/lean-herdr/roles/reviewer.md writes exactly this literal, and every review
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
    """The registry inside the SAME lean-ctx install the rest of us read.

    `bus.REGISTRY_PATH` is the hardcoded XDG default, while
    `orderlog.lean_ctx_data_dir()` honours `LEAN_CTX_DATA_DIR`, a legacy
    `~/.lean-ctx` and `XDG_*`. Both name the same `agents/` directory, so
    without this the build mode read an absent registry -- a full
    `ready_timeout_s` stall ending in `no_agent_id`.

    One resolution, not two (M3): this builds on the same function
    `orderlog.state_dir()` builds on, never on a second copy of the
    precedence.
    """
    return lean_ctx_data_dir() / "agents" / "registry.json"


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

    Per worker, the worst case now costs FIRST_START_TIMEOUT_MS (12 s) plus
    the `ctrl-c` deadline (PANE_FREE_TIMEOUT_S, 6 s) plus `ready_timeout_s`
    for the second attempt plus `ready_timeout_s` again for the waiter --
    about 108 s at the 45 s default -- and the orchestrator builds its
    workers serially, one `dispatch()` call after another. That is
    deliberate, the same trade `start_orchestrator` makes for the same
    reason: a warm project pays none of it, because the first attempt
    carries and the rest of the chain never runs.
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
                ROLE_ENV: req.role,
                # The worker's own name, so `lean-herdr report` does not have to
                # derive it. Derivation from role plus branch disagrees with
                # this side whenever the dispatch carried no `--worktree`:
                # here the agent is `builder`, there it would be
                # `builder-feat-x`, and an order under the wrong name
                # reaches nobody.
                AGENT_ENV: name,
            },
        ) or ""
        if not pane:
            return _result(False, None, None, error="pane_split_failed")
        started = start_agent(
            herdr,
            name,
            kind=req.kind,
            pane=pane,
            agent_args=agent_args(req.kind, req.model, req.role_file),
            first_timeout_ms=FIRST_START_TIMEOUT_MS,
            retry_timeout_ms=timeout_ms_for(cfg.ready_timeout_s),
        )
        if not started["ok"]:
            # `agent_start_failed` is Herdr refusing after 0.0 s;
            # `opencode_stuck` is opencode's first bootstrap in this project
            # hanging, twice. ONE mechanism with `workspace up` -- a worktree
            # is a new project to opencode, so a worker meets the very same
            # hang the orchestrator does.
            return _result(False, pane, None, error=started["error"])

    agent_id = waiter(
        herdr, name, registry_path=registry_path, timeout_s=cfg.ready_timeout_s
    )
    if not agent_id:
        return _result(False, pane, None, error="no_agent_id")
    # This is the end. The orchestrator creates the order itself, with
    # exactly this `agent` as `--to`: the worker resolves the very same name
    # out of its environment, so the two sides cannot drift. `agent_id`
    # stays in the answer as the readiness receipt -- the agent came up and
    # registered with lean-ctx -- and for the escalation line of the role
    # prompt.
    return _result(True, pane, agent_id, agent=name)


@dataclass(frozen=True)
class AwaitRequest:
    role: str
    kind: str
    task_id: str
    worktree: str | None = None
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    #: Run the cheap pre-review over the branch diff once the order is
    #: `completed`. Never a gate: only `reject` changes anything, and
    #: every failure of the pre-review's own machinery is `skipped`.
    prereview: bool = False


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
        entry = find_worktree(herdr.worktree_list(root), worktree)
        path = entry.get("path") if isinstance(entry, dict) else None
    except (TypeError, AttributeError, KeyError):
        return root
    return Path(path) if path else root


def _result_for_state(order: Order) -> dict[str, Any] | None:
    """The return for this state -- or None if we keep waiting.

    `input-required` returns even though is_terminal() does not call it
    terminal: only the orchestrator can answer, and it is asleep inside
    this very call. Without this return the script would wait for
    something that cannot happen without it.
    """
    message = message_from(order, order.to_agent)
    if order.state == "completed":
        result = order_result(
            True, order.id, state=order.state, message=message or ""
        )
        ruling = verdict(message)
        if ruling:
            result["verdict"] = ruling
        return result
    if order.state == "failed":
        return order_result(
            False,
            order.id,
            state=order.state,
            error=f"agent_failed: {message or 'no reason given'}",
        )
    if order.state == "canceled":
        return order_result(False, order.id, state=order.state, error="task_canceled")
    if order.state == "input-required":
        return order_result(
            False,
            order.id,
            state=order.state,
            error="input_required",
            message=message or "",
        )
    return None


def await_task(
    req: AwaitRequest,
    *,
    herdr: Herdr,
    root: Path,
    orders_dir: str | Path | None = None,
    interval_s: float = POLL_INTERVAL_S,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
    settings: RoleSettings | None = None,
    runner: Any = subprocess.run,
    #: The HTTP injection for the pre-review's model call. `runner` above
    #: still drives `wt step diff`; without this second seam a
    #: `--prereview` test would reach the real network.
    request: Any = openrouter.request,
    #: `[llm]` out of the SAME file main() read for `settings`, and
    #: validated there -- so a wrong value is `config_error:` on stdout
    #: instead of a stderr line nobody reads. None means: no file was
    #: read, take the built-in constants.
    llm_cfg: LlmSettings | None = None,
) -> dict[str, Any]:
    """Wait for the event the worker writes itself.

    The waiting stays in the script: no CLI, no registration, no model step
    per round. Never raises; the result carries `ok`.

    The bell rings `order.to_agent` -- the name the order is actually
    addressed to, never one derived a second time here. `settings` and
    `--worktree` decide what `agent_name()` produces, and a `--await` call
    that spells either differently than the build call did would ring
    `builder` while the worker is `builder-feat-x`. `Herdr.run()` swallows
    every error and returns {} (herdr.py:52-70), so that miss is SILENT:
    the full timeout, then `no_reply`. One truth, not two (M3).

    The derivation stays as the fallback for the one moment no order names
    a worker yet -- a log whose first event is not `created`.
    """
    derived = agent_name(req.role, req.worktree, settings=settings)
    name = derived
    try:
        # ONCE, before the loop. state_dir() resolves canonical_root()
        # through git; inside the loop that would be a subprocess per poll
        # round -- exactly the cost the wait mode exists to avoid.
        directory = orders_dir if orders_dir is not None else state_dir(root)
    except OrderLogError as exc:
        return order_result(False, req.task_id, error=str(exc))
    deadline = now() + req.timeout_ms / 1000.0
    has_rung = False
    state = ""
    while True:
        try:
            events = read_events(req.task_id, orders=directory)
        except OrderLogError as exc:
            return order_result(False, req.task_id, error=str(exc))
        if not events:
            # The orchestrator wrote the `created` event BEFORE this call,
            # and append() renames the finished file into place before it
            # returns. Nothing here means the id is wrong -- waiting will
            # not change that.
            return order_result(False, req.task_id, error="task_not_found")
        order = fold(events)
        state = order.state
        name = order.to_agent or derived
        outcome = _result_for_state(order)
        if outcome is not None:
            if req.prereview and order.state == "completed":
                # Beside `verdict`, never instead of it: that key belongs
                # to the strong reviewer and its VERDIKT: protocol, and a
                # second writer on it would be exactly the confusion
                # VERDICT_RE exists to prevent.
                outcome.update(
                    llm.prereview_result(
                        order.description,
                        branch=req.worktree,
                        worktree_list=herdr.worktree_list(root),
                        settings=llm_cfg,
                        runner=runner,
                        request=request,
                    )
                )
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
        return order_result(
            False, req.task_id, state=state, error=f"agent_error: {error}"
        )
    return order_result(False, req.task_id, state=state, error="no_reply")


def remember_branch(
    key: str,
    value: str,
    *,
    root: Path,
    client: LeanCtx | None = None,
) -> dict[str, Any]:
    """The orchestrator's ONE entry for a finished branch. Never raises.

    Not `ok: false` when lean-ctx is missing: a memory entry is not the
    deliverable, and a failed dispatch at the very end of a green branch
    would read like a failed branch. The reason travels in `remembered`.
    """
    ctx = client or LeanCtx(root)
    answer = ctx.knowledge_remember(key=key, value=value)
    return {
        "ok": True,
        "key": key,
        "remembered": answer.ok,
        **({} if answer.ok else {"reason": answer.error or "unknown"}),
    }


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
        prog="lean-herdr dispatch", description="Build or wait -- one call."
    )
    p.add_argument(
        "command",
        help="builder | reviewer | orchestrator | order | answer | cancel | remember",
    )
    # No longer `required=True`: `order` and `cancel` take no kind, and
    # argparse would refuse a perfectly valid call. missing_flags() enforces it
    # for the two modes that DO need it -- there it answers with a JSON line
    # instead of exit 2.
    p.add_argument("--kind", default=None, choices=KINDS)
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
        "--prereview",
        action="store_true",
        help="only with --await and --worktree: judge the branch diff first",
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
    p.add_argument(
        "--to", default=None, help="required with `order`: the worker's agent name"
    )
    p.add_argument(
        "--after", default=None, help="only with `order`: the predecessor's task id"
    )
    p.add_argument(
        "--message", default=None, help="required with `order` and `cancel`"
    )
    # `--from` needs `dest=` for the same reason as `--await`: `from` is a
    # keyword and would be unreachable as args.from.
    p.add_argument(
        "--from",
        dest="from_agent",
        default=None,
        help=f"the sender stamped into the event (default {ORCHESTRATOR_AGENT})",
    )
    p.add_argument("--key", default=None, help="required with `remember`")
    return p


def _given(*pairs: tuple[str, Any]) -> str:
    """The flags of that list that were actually given, as one phrase."""
    return " and ".join(flag for flag, value in pairs if value is not None)


def missing_flags(args: argparse.Namespace) -> str | None:
    """Mode-dependent flag validation -- deliberately NOT via argparse.

    `required=True` ends the process with exit 2 and one line on stderr.
    The orchestrator reads `ok` on stdout; a typo would look to it like no
    output at all. The same holds for the flags of the OTHER modes:
    argparse accepts every one of them everywhere, and the mode that does
    not read them drops them without a word -- `--timeout-ms` in build
    mode, though its own help says "only with --await", and
    `--model`/`--role-file`/`--profile` under `--await`. A non-positive
    `--timeout-ms` bought exactly one ring and an immediate `no_reply`.
    """
    if args.command in LOG_COMMANDS:
        if args.waiting:
            return f"`{args.command}` does not take --await"
        stray = _given(
            ("--kind", args.kind),
            ("--model", args.model),
            ("--role-file", args.role_file),
            ("--profile", args.profile),
            ("--worktree", args.worktree),
            ("--timeout-ms", args.timeout_ms),
            # `store_true` hands out False, not None -- `or None` is what
            # makes _given() see it at all.
            ("--prereview", args.prereview or None),
        )
        if stray:
            return f"`{args.command}` does not take {stray}"
        if args.key and args.command != "remember":
            return "--key belongs to `remember`"
        if args.command == "order":
            stray = _given(("--task-id", args.task_id))
            if stray:
                return f"`{args.command}` does not take {stray}"
            missing = [
                flag
                for flag, value in (("--to", args.to), ("--message", args.message))
                if not value
            ]
            return f"order needs {' and '.join(missing)}" if missing else None
        if args.command == "remember":
            stray = _given(
                ("--task-id", args.task_id),
                ("--to", args.to),
                ("--after", args.after),
                ("--from", args.from_agent),
            )
            if stray:
                return f"`{args.command}` does not take {stray}"
            missing = [
                flag
                for flag, value in (
                    ("--key", args.key),
                    ("--message", args.message),
                )
                if not value
            ]
            return f"remember needs {' and '.join(missing)}" if missing else None
        # answer and cancel: same two flags, and neither takes --to/--after.
        stray = _given(("--to", args.to), ("--after", args.after))
        if stray:
            return f"`{args.command}` does not take {stray}"
        missing = [
            flag
            for flag, value in (
                ("--task-id", args.task_id),
                ("--message", args.message),
            )
            if not value
        ]
        return f"{args.command} needs {' and '.join(missing)}" if missing else None
    # The role modes take none of the log commands' flags. Worded
    # generically, not as a list: the list grows (task 5 adds --key) and an
    # enumeration would be wrong the next time.
    stray = _given(
        ("--to", args.to),
        ("--after", args.after),
        ("--message", args.message),
        ("--from", args.from_agent),
        ("--key", args.key),
    )
    if stray:
        return f"{stray} belongs to a log command"
    if not args.kind:
        return "--kind is required"
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
        if args.prereview and not args.worktree:
            return "--prereview needs --worktree"
        return None
    missing = [
        flag
        for flag, value in (("--model", args.model), ("--role-file", args.role_file))
        if not value
    ]
    if missing:
        return f"build mode needs {' and '.join(missing)}"
    # `--task-id` belongs to `--await`; in build mode argparse takes it and
    # the mode drops it without a word. Last gap of the stray-flag doctrine.
    stray = _given(
        ("--task-id", args.task_id),
        ("--timeout-ms", args.timeout_ms),
        ("--prereview", args.prereview or None),
    )
    return f"build mode does not take {stray}" if stray else None


def main(argv: list[str] | None = None) -> int:
    """Output: one JSON line on stdout. Exit ALWAYS 0.

    The orchestrator reads `ok`, not the exit code -- so a failure does not
    abort its shell call.
    """
    result: dict[str, Any]
    try:
        args = build_parser().parse_args(argv)
        # Read once, hand to both modes: the wait mode has to ring the agent
        # the build mode started, and the name comes from here. SETTINGS_PATH
        # is RELATIVE -- anchored on anything but the canonical root the file
        # would silently not be found as soon as `lean-herdr dispatch` runs
        # from a subdirectory or a worktree.
        #
        # BEFORE missing_flags(), and that is new: the file can now SATISFY
        # --model and --kind, so reading it afterwards would reject a call the
        # config answers. The price is real and accepted: a broken config value
        # now reaches the caller as `config_error:` even when the command line
        # ALSO has a usage error. Of the two that is the bigger one, and the
        # one that would otherwise stay silent.
        root = canonical_root()
        raw = read_settings(root / SETTINGS_PATH)
        settings = settings_for(args.command, raw)
        # Validated HERE, in the one consumer that has a reader for the
        # complaint: a SettingsError from this line leaves main() as
        # `config_error: <reason>` on stdout. llm.file_settings() deliberately
        # swallows the same error -- there it would cost a commit -- so without
        # this call a typo in `[llm]` would be silent everywhere.
        llm_cfg = llm_settings(raw)
        if args.command not in LOG_COMMANDS:
            # Precedence, at ONE place, and only for the role modes:
            #   kind:  --kind  > [roles.<role>].kind  -> else missing_flags()
            #   model: --model > [roles.<role>].model -> else missing_flags()
            # `order`/`answer`/`cancel`/`remember` are left out on purpose:
            # they REFUSE --kind and --model as stray flags, and a
            # `[default].kind` would otherwise turn every one of them into a
            # usage error nobody typed.
            args.kind = args.kind or settings.kind or None
            if not args.waiting:
                # Build mode only. Under --await a --model is itself a stray
                # flag, so filling it from the file would break a valid wait
                # call -- with a value the wait mode never even reads.
                args.model = args.model or settings.model or None
        missing = missing_flags(args)
        if missing:
            result = {"ok": False, "error": f"usage_error: {missing}"}
        else:
            sender = args.from_agent or ORCHESTRATOR_AGENT
            if args.command == "order":
                result = create_order(
                    OrderRequest(
                        to_agent=args.to,
                        message=args.message,
                        after=args.after,
                        actor=sender,
                    ),
                    root=root,
                )
            elif args.command == "answer":
                result = answer_order(
                    args.task_id, args.message, root=root, actor=sender
                )
            elif args.command == "cancel":
                result = cancel_order(
                    args.task_id, args.message, root=root, actor=sender
                )
            elif args.command == "remember":
                result = remember_branch(args.key, args.message, root=root)
            elif args.waiting:
                result = await_task(
                    AwaitRequest(
                        role=args.command,
                        kind=args.kind,
                        task_id=args.task_id,
                        worktree=args.worktree,
                        timeout_ms=args.timeout_ms or DEFAULT_TIMEOUT_MS,
                        prereview=args.prereview,
                    ),
                    herdr=Herdr(),
                    root=root,
                    settings=settings,
                    llm_cfg=llm_cfg,
                )
            else:
                result = dispatch(
                    DispatchRequest(
                        role=args.command,
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
                # Additive, and only where a reader exists: the orchestrator
                # reads the reviewer's dispatch line, so that is where a
                # warning about the reviewer's model gets seen. `ok` is
                # untouched -- a shared model is a warning, never a refusal.
                notes = model_warnings(raw) if args.command == "reviewer" else []
                if notes:
                    result = {**result, "warnings": notes}
    except UsageError as exc:
        result = {"ok": False, "error": f"usage_error: {exc}"}
    except SettingsError as exc:
        result = {"ok": False, "error": f"config_error: {exc}"}
    except Exception as exc:  # noqa: BLE001 -- never abort the caller
        result = {"ok": False, "error": f"dispatch_crashed: {exc}"}
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    return 0
