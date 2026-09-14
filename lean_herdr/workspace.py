"""`lean-herdr workspace up` -- the orchestrator pane, from the config.

Two callers, one core. `up` is the command line; `handlers.handle_bootstrap`
is the keystroke inside a running Herdr. Before this module the two could
drift, and did: the keystroke read its name, runtime and environment from
a literal in handlers.py and never opened the config at all.

They differ in exactly ONE thing, and it sits in the signature rather than
in the core: `up` may look for a workspace and create one, the keystroke
may NOT. It has to land in the workspace the key was pressed in -- put the
find-or-create rule inside the core and the keystroke starts the
orchestrator somewhere the operator is not looking.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn

from lean_herdr.bus import BusError, canonical_root
from lean_herdr.dispatch import UsageError, wait_for_agent_id
from lean_herdr.herdr import (
    FIRST_START_TIMEOUT_MS,
    Herdr,
    start_agent,
    timeout_ms_for,
)
from lean_herdr.settings import (
    ORCHESTRATOR_AGENT,
    SETTINGS_PATH,
    SettingsError,
    WorkspaceSettings,
    llm_settings,
    load_jsonc,
    models_settings,
    read_settings,
    settings_for,
    workspace_settings,
)
from lean_herdr.worktree import anchor_pane

#: opencode reads its project configuration from this file, at the repo
#: root. Not configurable: opencode looks for exactly this name.
OPENCODE_CONFIG = "opencode.jsonc"

#: The agent NAME `start_orchestrator` hands opencode, and the key it has to
#: find under `agent` in OPENCODE_CONFIG. One truth for both: the guard and
#: the `--agent` argument must ask for the same word, or the guard passes a
#: run that opencode then refuses.
#:
#: Deliberately not ORCHESTRATOR_AGENT: that one is `orch`, the name Herdr
#: registers the agent under. These are two different namespaces that happen
#: to describe the same pane.
OPENCODE_ORCHESTRATOR = "orchestrator"

#: Every guard message ends here. `init` is what writes OPENCODE_CONFIG, and
#: it is the same next step for a file that is absent, broken, or short of
#: this one agent -- with --force for the latter two, which will not
#: overwrite silently.
INIT_HINT = "run `lean-herdr workspace init` first"


class _Parser(argparse.ArgumentParser):
    """argparse ends a usage error with exit 2 and one line on stderr.

    Same reason as dispatch._Parser: the caller reads `ok` on stdout and
    would see no output at all. Not imported from there -- that name is
    private to its module, and four lines are cheaper than making it
    public for one reuse.
    """

    def error(self, message: str) -> NoReturn:
        raise UsageError(message)


def find_workspace(herdr: Herdr, root: Path, listing: dict[str, Any]) -> str | None:
    """The workspace for `root` -- by worktree first, by pane cwd second.

    `worktree` is optional AND nullable in WorkspaceInfo
    (herdr-api.schema.json:1113-1133): a workspace that `workspace create
    --cwd` made itself can carry `worktree: null`. Searching
    `checkout_path` alone would never find that one again and would create
    a second workspace on the next call -- as soon as the orchestrator
    pane is closed and the duplicate check no longer bites.

    The pane fallback is deliberately SECOND, not equal. Measured against
    0.8.2, a workspace carries panes with foreign `cwd` too: `w1` of this
    repo held a pane sitting in another repository entirely. The mapping
    is fuzzy, so it only runs when the exact rule found nothing.
    """
    for entry in (listing.get("result") or {}).get("workspaces") or ():
        if not isinstance(entry, dict):
            continue
        worktree = entry.get("worktree")
        if isinstance(worktree, dict) and worktree.get("checkout_path") == str(root):
            return str(entry.get("workspace_id") or "") or None
    for pane in herdr.pane_list():
        if pane.get("cwd") == str(root) and pane.get("workspace_id"):
            return str(pane["workspace_id"])
    return None


def create_workspace(
    herdr: Herdr, root: Path, *, settings: WorkspaceSettings, env: dict[str, str]
) -> str | None:
    """`herdr workspace create` for this root. Returns the id, or None.

    Measured against 0.8.2, `workspace create` takes --cwd, --label, --env
    and --focus/--no-focus, and nothing else. The id ladder mirrors
    worktree._open_workspace(): a nested `result.workspace.workspace_id`
    first, the flat key as a fallback, so a shape shift does not read as
    success.
    """
    args = [
        "workspace",
        "create",
        "--cwd",
        str(root),
        "--label",
        settings.label.format(repo=root.name),
        "--focus",
    ]
    for key, value in env.items():
        args += ["--env", f"{key}={value}"]
    result = herdr.run(*args).get("result") or {}
    nested = result.get("workspace")
    nested = nested if isinstance(nested, dict) else {}
    workspace = nested.get("workspace_id") or result.get("workspace_id")
    return str(workspace) if workspace else None


def missing_agent_config(root: Path, kind: str) -> str | None:
    """Why opencode could not resolve the orchestrator here. None: it can.

    Measured 2026-09-04. `--agent orchestrator` is a NAME, and opencode
    resolves it out of the project's own `opencode.jsonc`. In a project
    where `workspace init` never ran that file does not exist: opencode
    starts, prints "Agent not found: Orchestrator", never becomes an agent
    and never registers its MCP server. Without this check the caller then
    sat out the full `ready_timeout_s` -- 45 s -- waiting for an agent id
    that could not arrive, and answered the misleading `no_agent_id`. The
    same class of defect as the discarded `agent_start` reply: launch
    something doomed and wait it out instead of looking first.

    Only opencode has this failure mode, so only opencode is checked. A
    claude worker never resolves a project-level agent NAME at all -- its
    role travels as a FILE on `--append-system-prompt-file`
    (dispatch.agent_args), so there is nothing here that could fail to
    resolve and nothing to check.

    Three answers, not one, because they are three different repairs:
    absent (init has not run), present but unparseable (an editor), and
    parsed without this agent (a config for another project's roles). One
    word for all three would send the operator to the wrong one.
    """
    if kind != "opencode":
        return None
    config = load_jsonc(root / OPENCODE_CONFIG)
    if not config.found:
        return f"no {OPENCODE_CONFIG} in {root}"
    if config.error:
        return f"{OPENCODE_CONFIG} in {root} is {config.error}"
    agents = config.data.get("agent")
    if not isinstance(agents, dict) or not isinstance(agents.get(OPENCODE_ORCHESTRATOR), dict):
        return f"{OPENCODE_CONFIG} in {root} defines no agent.{OPENCODE_ORCHESTRATOR}"
    return None


def start_orchestrator(
    *,
    herdr: Herdr,
    root: Path,
    settings: WorkspaceSettings,
    profile: str,
    model: str,
    kind: str,
    workspace_id: str | None,
    ready_timeout_s: float,
    retry_on_hang: bool = True,
    waiter: Callable[..., str | None] = wait_for_agent_id,
) -> dict[str, Any]:
    """Start the orchestrator. Never raises; the result carries `ok`.

    `model` and `kind` arrive one by one, like `profile` and
    `ready_timeout_s` before them and out of the same table --
    `[roles.orchestrator]`. `settings` is down to the one thing that is
    about the WORKSPACE and not about the agent: its label.

    `workspace_id=None` means "find the workspace for `root`, or create
    one" -- the `up` path. A given id means "use exactly this one and
    create nothing" -- the keystroke path.

    `retry_on_hang=False` takes the second attempt away: a hang is then
    reported at once instead of being sat out. That is the keystroke's path
    -- `handle_bootstrap` runs inside Herdr's handler process, which is the
    wrong place to block (handlers.KEYSTROKE_READY_TIMEOUT_S), and the cold
    start is a deliberately accepted false alarm there. It costs that path
    nothing: the aborted first attempt warms the project anyway, so the next
    press is the one that carries.
    """
    # FIRST, ahead of every other precondition: this is one stat and no
    # subprocess at all, and a run that cannot possibly work must cost
    # nothing rather than a workspace, a pane and 45 s of waiting. It is a
    # precondition, not a knob -- the core still has exactly one, and that
    # one is `workspace_id`.
    #
    # `workspace_up` refuses a missing lean-herdr config with
    # `not_initialised` before it ever gets here, so on THAT path this only
    # bites a half-initialised project. The keystroke has no such check --
    # it takes the built-in defaults on purpose -- so for `handle_bootstrap`
    # this is the only thing standing between a keystroke and a wait for an
    # agent opencode could not name.
    problem = missing_agent_config(root, kind)
    if problem:
        return {"ok": False, "error": f"no_agent_config: {problem} -- {INIT_HINT}"}
    if not herdr.is_available():
        return {"ok": False, "error": "no_herdr_server"}
    # A RAW `workspace list`, not workspace_list(): that method
    # (herdr.py:189-191) flattens "server dead" and "zero workspaces" onto
    # the same `[]`, and only the raw reply tells them apart -- `{}` when
    # nothing answered. Every `herdr <sub>` goes through that socket, so
    # this is a real precondition, not an assumption; without it the call
    # would hang on a dead socket instead of saying so.
    listing = herdr.run("workspace", "list")
    if not listing:
        return {"ok": False, "error": "no_herdr_server"}

    # `agent list` is server-wide, not per workspace -- the same duplicate
    # check the keystroke makes today. This is what makes `up` idempotent.
    running = next(
        (a for a in herdr.agent_list() if a.get("name") == ORCHESTRATOR_AGENT),
        None,
    )
    if running:
        return {
            "ok": True,
            "already_running": True,
            "agent": ORCHESTRATOR_AGENT,
            "pane": str(running.get("pane_id") or "") or None,
        }

    env = {"LEAN_CTX_TOOL_PROFILE": profile, "LEAN_CTX_ROLE": "orchestrator"}
    target = (
        workspace_id
        or find_workspace(herdr, root, listing)
        or create_workspace(herdr, root, settings=settings, env=env)
    )
    if not target:
        return {"ok": False, "error": "no_workspace"}

    # Always split, never take the workspace's root pane. One path, shared
    # with the keystroke, and it is the one that is measured.
    anchor = anchor_pane(herdr, target)
    if anchor is None:
        # A workspace without a pane -- possible after a server restart.
        # Same error name dispatch() uses for the same situation.
        return {"ok": False, "error": "no_anchor_pane", "workspace": target}
    pane = herdr.pane_split(root, pane=anchor, env=env)
    if not pane:
        return {"ok": False, "error": "pane_split_failed", "workspace": target}

    # NOT agent_args(): that helper always sets --model and derives the
    # agent name from a role FILE stem. Here the agent is named directly
    # and --model is omitted entirely when the config leaves it empty --
    # exactly what handle_bootstrap does today.
    agent_args = ["--agent", OPENCODE_ORCHESTRATOR]
    if model:
        agent_args = ["--model", model, *agent_args]
    # Both budgets come out of the ONE the caller granted. `up` grants 45 s
    # and gets the full FIRST_START_TIMEOUT_MS; the keystroke grants 6
    # (handlers.KEYSTROKE_READY_TIMEOUT_S) and its first attempt shrinks with
    # it -- a flat 12 s would have made a keystroke sit in Herdr's handler
    # process for twice what that cap allows.
    started = start_agent(
        herdr,
        ORCHESTRATOR_AGENT,
        kind=kind,
        pane=pane,
        agent_args=agent_args,
        first_timeout_ms=min(FIRST_START_TIMEOUT_MS, timeout_ms_for(ready_timeout_s)),
        retry_timeout_ms=timeout_ms_for(ready_timeout_s) if retry_on_hang else 0,
    )
    if not started["ok"]:
        # Two failures, two names, and the helper is the one that can tell
        # them apart: `agent_start_failed` is Herdr saying no after 0.0 s,
        # `opencode_stuck` is a start that did not reach readiness even on
        # the second attempt. Both carry the pane, because the tile is still
        # there and the operator needs to find it -- the helper aborts the
        # PROCESS, never the pane.
        return {
            "ok": False,
            "error": started["error"],
            "workspace": target,
            "pane": pane,
        }
    agent_id = waiter(herdr, ORCHESTRATOR_AGENT, timeout_s=ready_timeout_s)
    if not agent_id:
        return {
            "ok": False,
            "error": "no_agent_id",
            "workspace": target,
            "pane": pane,
        }
    return {
        "ok": True,
        "workspace": target,
        "pane": pane,
        "agent": ORCHESTRATOR_AGENT,
        "agent_id": agent_id,
    }


def workspace_up(*, root: Path | None = None, herdr: Herdr | None = None) -> dict[str, Any]:
    """Root, config, then the shared core.

    A missing config is a hard stop, not a fallback to defaults: the
    config is the whole point of this call. The keystroke, which is a
    gesture rather than a call, takes the defaults instead.

    This one DOES raise, and it is the one place in this module that
    does: an unreadable config leaves through `read_settings`,
    `settings_for`, `models_settings`, `llm_settings` or
    `workspace_settings`, and a root that is no repository through
    `canonical_root`. Every one of them runs BEFORE `start_orchestrator`;
    after the start nothing raises (`check()` never does), so a started
    orchestrator's pane and agent id always reach the caller. `main()`
    turns the raise into `config_error:` -- a config the operator cannot
    read must not be answered with defaults.

    The overlay is not read here at all. It carries `model` alone, and
    `up` needs only the two efforts out of `[llm]`.
    """
    base = root if root is not None else canonical_root()
    path = base / SETTINGS_PATH
    if not path.is_file():
        return {
            "ok": False,
            "error": "not_initialised: run `lean-herdr workspace init`",
        }
    data = read_settings(path)
    role = settings_for("orchestrator", data)
    # Validated even when `auto` is off: a typo in [models] must not stay
    # silent, which is this module's whole promise. workspace.main() turns
    # a SettingsError from here into `config_error:`.
    models = models_settings(data)
    # `[llm]` likewise, and for the same reason -- and BEFORE the start: read
    # after it, a raise would throw away the pane and agent id of an
    # orchestrator that is already running.
    llm_cfg = llm_settings(data)
    result = start_orchestrator(
        herdr=herdr if herdr is not None else Herdr(),
        root=base,
        settings=workspace_settings(data),
        profile=role.profile,
        model=role.model,
        kind=role.kind,
        workspace_id=None,
        ready_timeout_s=role.ready_timeout_s,
    )
    if not models.auto:
        return result
    # AFTER the start, never before: `up` opens the working day, and a
    # price comparison must not stand between the operator and a running
    # orchestrator. Merged in additively -- `ok` belongs to the start
    # alone, and a catalogue that did not answer is not a failed `up`.
    #
    # Imported on the call, like `initcmd` above it and for the same
    # reason: `catalog` reaches urllib, llm AND dispatch, and the common
    # path -- `auto` off, the default -- returns above without paying for
    # any of it.
    from lean_herdr.catalog import check
    from lean_herdr.llm import GENERATE_EFFORT, PREREVIEW_EFFORT

    return {
        **result,
        "models": check(
            root=base,
            settings=models,
            efforts=(
                llm_cfg.effort or GENERATE_EFFORT,
                llm_cfg.prereview_effort or PREREVIEW_EFFORT,
            ),
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(
        prog="lean-herdr workspace",
        description="Set the project up, check it, or start the orchestrator from its config.",
    )
    p.add_argument("command", choices=("up", "init", "check"))
    p.add_argument(
        "--force",
        action="store_true",
        help="init: overwrite files that are already there",
    )
    p.add_argument(
        "--update",
        action="store_true",
        help="init: also rewrite files nobody edited since init wrote them",
    )
    p.add_argument(
        "--test",
        default=None,
        help="init: the pre-merge test command, and the builder's permission for it",
    )
    p.add_argument(
        "--lint",
        default=None,
        help="init: the pre-merge lint command, and the builder's permission for it",
    )
    return p


def _init_flags(args: argparse.Namespace) -> str:
    """The init-only flags that were given, as one phrase. Empty: none."""
    given = (
        ("--force", args.force),
        ("--update", args.update),
        ("--test", args.test),
        ("--lint", args.lint),
    )
    # Given is not truthy: `--test ""` is a flag on the command line all the same.
    return " and ".join(flag for flag, value in given if value not in (None, False))


def main(argv: list[str] | None = None) -> int:
    """Output: one JSON line on stdout. Exit ALWAYS 0.

    Same contract and the same except ladder as report.main, for the same
    reason: the caller reads `ok`, and a usage error must not abort its
    shell call.
    """
    result: dict[str, Any]
    try:
        args = build_parser().parse_args(argv)
        stray = _init_flags(args)
        if args.command != "init" and stray:
            result = {
                "ok": False,
                "error": f"usage_error: {args.command} does not take {stray}",
            }
        elif args.command == "up":
            result = workspace_up()
        elif args.command == "check":
            # Imported on the call, like `initcmd`: `up` needs none of it.
            from lean_herdr.checkcmd import workspace_check

            result = workspace_check()
        else:
            # Imported on the call, not up top: `up` is what runs on every
            # start, and it needs none of this.
            from lean_herdr.initcmd import workspace_init

            result = workspace_init(
                force=args.force, update=args.update, test=args.test, lint=args.lint
            )
    except UsageError as exc:
        result = {"ok": False, "error": f"usage_error: {exc}"}
    except SettingsError as exc:
        result = {"ok": False, "error": f"config_error: {exc}"}
    except BusError as exc:
        result = {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 -- never abort the caller
        result = {"ok": False, "error": f"workspace_crashed: {exc}"}
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    return 0
