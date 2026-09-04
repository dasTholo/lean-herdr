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
from lean_herdr.herdr import Herdr
from lean_herdr.settings import (
    ORCHESTRATOR_AGENT,
    SETTINGS_PATH,
    SettingsError,
    WorkspaceSettings,
    read_settings,
    settings_for,
    workspace_settings,
)
from lean_herdr.worktree import anchor_pane


class _Parser(argparse.ArgumentParser):
    """argparse ends a usage error with exit 2 and one line on stderr.

    Same reason as dispatch._Parser: the caller reads `ok` on stdout and
    would see no output at all. Not imported from there -- that name is
    private to its module, and four lines are cheaper than making it
    public for one reuse.
    """

    def error(self, message: str) -> NoReturn:
        raise UsageError(message)


def find_workspace(
    herdr: Herdr, root: Path, listing: dict[str, Any]
) -> str | None:
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
        "workspace", "create",
        "--cwd", str(root),
        "--label", settings.label.format(repo=root.name),
        "--focus",
    ]
    for key, value in env.items():
        args += ["--env", f"{key}={value}"]
    result = herdr.run(*args).get("result") or {}
    nested = result.get("workspace") if isinstance(result.get("workspace"), dict) else {}
    workspace = nested.get("workspace_id") or result.get("workspace_id")
    return str(workspace) if workspace else None


def start_orchestrator(
    *,
    herdr: Herdr,
    root: Path,
    settings: WorkspaceSettings,
    profile: str,
    workspace_id: str | None,
    ready_timeout_s: float,
    waiter: Callable[..., str | None] = wait_for_agent_id,
) -> dict[str, Any]:
    """Start the orchestrator. Never raises; the result carries `ok`.

    `workspace_id=None` means "find the workspace for `root`, or create
    one" -- the `up` path. A given id means "use exactly this one and
    create nothing" -- the keystroke path.
    """
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
    target = workspace_id or find_workspace(herdr, root, listing) or create_workspace(
        herdr, root, settings=settings, env=env
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
    agent_args = ["--agent", "orchestrator"]
    if settings.model:
        agent_args = ["--model", settings.model, *agent_args]
    herdr.agent_start(
        ORCHESTRATOR_AGENT,
        kind=settings.kind,
        pane=pane,
        agent_args=agent_args,
    )
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


def workspace_up(
    *, root: Path | None = None, herdr: Herdr | None = None
) -> dict[str, Any]:
    """Root, config, then the shared core. Never raises.

    A missing config is a hard stop, not a fallback to defaults: the
    config is the whole point of this call. The keystroke, which is a
    gesture rather than a call, takes the defaults instead.
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
    return start_orchestrator(
        herdr=herdr if herdr is not None else Herdr(),
        root=base,
        settings=workspace_settings(data),
        profile=role.profile,
        workspace_id=None,
        ready_timeout_s=role.ready_timeout_s,
    )


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(
        prog="lean-herdr workspace",
        description="Set the project up, or start the orchestrator from its config.",
    )
    p.add_argument("command", choices=("up", "init"))
    p.add_argument(
        "--force",
        action="store_true",
        help="init: overwrite files that are already there",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    """Output: one JSON line on stdout. Exit ALWAYS 0.

    Same contract and the same except ladder as report.main, for the same
    reason: the caller reads `ok`, and a usage error must not abort its
    shell call.
    """
    result: dict[str, Any]
    try:
        args = build_parser().parse_args(argv)
        if args.command == "up":
            if args.force:
                result = {
                    "ok": False,
                    "error": "usage_error: up does not take --force",
                }
            else:
                result = workspace_up()
        else:
            # Imported on the call, not up top: `up` is what runs on every
            # start, and it needs none of this.
            from lean_herdr.initcmd import workspace_init

            result = workspace_init(force=args.force)
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
