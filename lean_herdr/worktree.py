"""Worktree resolution: worktrunk creates, Herdr maps.

No registry of its own — Herdr owns the Worktree → Workspace mapping
itself, and `wt switch --format json` returns the path directly.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lean_herdr.herdr import Herdr

WT_TIMEOUT_S = 120.0


class WorktrunkMissing(RuntimeError):
    """`wt` is not installed — everything still works without --worktree."""


class WorktreeOpenFailed(RuntimeError):
    """The tree exists, but Herdr has not opened a workspace on it.

    This is a hard stop, not a cosmetic issue: without a workspace the pane
    still runs in the right directory, but teardown can no longer find it
    and a `linked_worktree_source` (H8) would go unnoticed.
    """


@dataclass(frozen=True)
class WorktreeTarget:
    """A worktree the way dispatch needs it: path AND workspace.

    `workspace_id` is not optional. A target without a workspace would only
    be half there — the pane would land in the wrong workspace and teardown
    would fail.
    """

    path: Path
    workspace_id: str


def repo_root_from(worktree_list: dict[str, Any]) -> Path | None:
    """`.result.source.repo_root` — never assume $PWD (H8)."""
    root = ((worktree_list.get("result") or {}).get("source") or {}).get("repo_root")
    return Path(root) if root else None


def find_worktree(worktree_list: dict[str, Any], branch: str) -> dict[str, Any] | None:
    for entry in (worktree_list.get("result") or {}).get("worktrees") or ():
        if isinstance(entry, dict) and entry.get("branch") == branch:
            return entry
    return None


def wt_switch(
    branch: str, *, cwd: str | Path, runner: Any = subprocess.run, base: str = "@"
) -> Path | None:
    """`wt switch --create <branch> --base <base> --no-cd --format json --yes` → .path.

    `--no-cd` because the script doesn't change directory; `--yes` because no
    human is sitting at the approval prompt. `base` defaults to `@` (the
    currently checked-out branch) rather than `wt`'s own default (the repo's
    default branch): the order-log path is self-referential -- a worker reads
    its role prompt from `.lean-ctx/lean-herdr/roles/`, which is introduced by
    the orchestrator's own branch. A worktree branched off `main` structurally
    lacks those files, so the worker starts without a prompt, never reports,
    and the orchestrator runs into the wait-mode timeout with `no_reply`.

    The report CLI itself is no longer part of this argument: `lean-herdr`
    lives on the PATH, not in the tree. Measured before that move: `wt switch
    --create feat/probe` with no `--base` produced a worktree at `main`'s HEAD,
    missing `bin/herdr-report`, `.claude/settings.json` and
    `lean_herdr/orderlog.py` alike -- the second and third of those still
    travel in the branch today.

    Honest subtlety: this runs with `cwd=repo_root` (H8 — `--cwd`/`cwd` MUST
    be the repo root, or the later `worktree open` is rejected with
    `linked_worktree_source`). So `@` resolves to whatever is checked out at
    the MAIN checkout — not necessarily the orchestrator's own branch, if the
    orchestrator itself is running inside a linked worktree.

    Also unchanged by this fix, and worth writing down so nobody "fixes" it
    back by accident: per `wt switch --help`, a branch created with an
    explicit `--base` gets no upstream unless its name matches an existing
    remote branch. That was already true of the old, defaulted `--base` — not
    a regression.
    """
    if shutil.which("wt") is None:
        raise WorktrunkMissing("wt is not installed")
    try:
        proc = runner(
            [
                "wt",
                "switch",
                "--create",
                branch,
                "--base",
                base,
                "--no-cd",
                "--format",
                "json",
                "--yes",
            ],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=WT_TIMEOUT_S,
        )
    except OSError, subprocess.SubprocessError:
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    path = data.get("path") if isinstance(data, dict) else None
    return Path(path) if path else None


def _open_workspace(herdr: Herdr, *, repo_root: Path, path: Path, branch: str) -> str:
    """Open the worktree with Herdr and return the workspace ID — or fail.

    --cwd MUST be the repo root; called from a linked-worktree workspace,
    Herdr rejects with `linked_worktree_source` (H8). Otherwise that exact
    case would come back as an empty dict and look like success.

    The id is not a top-level field. Measured against Herdr 0.8.2, a
    `worktree open` reply nests it as `result.workspace.workspace_id`, with
    `result.worktree.open_workspace_id` and `result.root_pane.workspace_id`
    carrying the same id as corroboration (`result.tab` is present too, but
    its `workspace_id` is NOT used as a hit — see below):

        {"result": {"workspace": {"workspace_id": "w2", ...},
                     "worktree": {"open_workspace_id": "w2", ...},
                     "root_pane": {"workspace_id": "w2", ...},
                     "tab": {"workspace_id": "w2", ...}}}

    `result.open_workspace_id` / `result.workspace_id` — the keys this used
    to read — exist only on `worktree_list` entries, never on an `open`
    reply; they stay below as a last-resort fallback so nothing that
    happened to rely on them breaks. The bug they caused was self-disguising:
    `ensure_worktree` consults `worktree_list` first, and THAT listing's
    entries genuinely do carry `open_workspace_id` — so a second call for the
    same branch quietly took the listing path and succeeded, while the
    first, workspace-opening call failed every time.
    """
    opened = herdr.worktree_open(cwd=repo_root, path=path, label=branch)
    result = opened.get("result") or {}
    workspace_obj = result.get("workspace") if isinstance(result.get("workspace"), dict) else {}
    worktree_obj = result.get("worktree") if isinstance(result.get("worktree"), dict) else {}
    root_pane = result.get("root_pane") if isinstance(result.get("root_pane"), dict) else {}
    tab = result.get("tab") if isinstance(result.get("tab"), dict) else {}
    # `tab.workspace_id` is deliberately NOT in this ladder. In tab mode that
    # id names whatever workspace already hosts the tab (e.g. the caller's
    # own) — not a new workspace for this worktree. Treating it as a hit
    # would silently hand back the wrong workspace instead of failing loud.
    workspace = (
        workspace_obj.get("workspace_id")
        or worktree_obj.get("open_workspace_id")
        or root_pane.get("workspace_id")
        or result.get("open_workspace_id")
        or result.get("workspace_id")
    )
    if not workspace:
        error_code = (opened.get("error") or {}).get("code")
        if error_code:
            reason = error_code
        elif tab:
            # herdr-worktrunk: Herdr registers a checkout either as a nested
            # worktree workspace or opens it as a plain tab, depending on
            # configuration. A tab-only reply has no workspace of its own to
            # report — say so specifically, not the generic "no workspace_id".
            reason = f"opened as tab {tab.get('tab_id')!r}, no workspace"
        else:
            reason = "no workspace_id"
        raise WorktreeOpenFailed(f"worktree open for {branch}: {reason}")
    return str(workspace)


def anchor_pane(herdr: Herdr, workspace_id: str) -> str | None:
    """Any pane in this workspace — the anchor point for splitting.

    `pane split --current` splits the caller's workspace, i.e. the
    orchestrator's. A worker created that way would sit in the wrong
    workspace: `workspace close <worktree_workspace>` wouldn't close it, and
    teardown would leave an orphan behind. So a pane of the worktree's own
    workspace is split deliberately instead.
    """
    for pane in herdr.pane_list(workspace_id):
        pane_id = pane.get("pane_id")
        if pane_id:
            return str(pane_id)
    return None


def ensure_worktree(
    branch: str, *, herdr: Herdr, cwd: str | Path, runner: Any = subprocess.run
) -> WorktreeTarget:
    """The branch's worktree — reuse an existing one, otherwise create it.

    Order: ask Herdr first (the worktree might already be open), then let
    worktrunk create one, then register it with Herdr. In EVERY case the
    end result is a workspace ID; a target without one would only be half
    there.
    """
    listing = herdr.worktree_list(cwd)
    repo_root = repo_root_from(listing) or Path(cwd)

    existing = find_worktree(listing, branch)
    if existing and existing.get("path"):
        path = Path(existing["path"])
        # The tree can exist without a workspace pointing at it — e.g. after
        # a Herdr restart. In that case it gets reopened here.
        workspace = existing.get("open_workspace_id")
        return WorktreeTarget(
            path=path,
            workspace_id=str(workspace)
            if workspace
            else _open_workspace(herdr, repo_root=repo_root, path=path, branch=branch),
        )

    path = wt_switch(branch, cwd=repo_root, runner=runner)
    if path is None:
        raise WorktrunkMissing(f"wt switch returned no path for {branch}")

    return WorktreeTarget(
        path=path,
        workspace_id=_open_workspace(herdr, repo_root=repo_root, path=path, branch=branch),
    )
