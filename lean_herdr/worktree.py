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
    branch: str, *, cwd: str | Path, runner: Any = subprocess.run
) -> Path | None:
    """`wt switch --create <branch> --no-cd --format json --yes` → .path.

    `--no-cd` because the script doesn't change directory; `--yes` because
    no human is sitting at the approval prompt.
    """
    if shutil.which("wt") is None:
        raise WorktrunkMissing("wt is not installed")
    try:
        proc = runner(
            ["wt", "switch", "--create", branch, "--no-cd", "--format", "json", "--yes"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=WT_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    path = data.get("path") if isinstance(data, dict) else None
    return Path(path) if path else None


def _open_workspace(
    herdr: Herdr, *, repo_root: Path, path: Path, branch: str
) -> str:
    """Open the worktree with Herdr and return the workspace ID — or fail.

    --cwd MUST be the repo root; called from a linked-worktree workspace,
    Herdr rejects with `linked_worktree_source` (H8). Otherwise that exact
    case would come back as an empty dict and look like success.
    """
    opened = herdr.worktree_open(cwd=repo_root, path=path, label=branch)
    result = opened.get("result") or {}
    workspace = result.get("open_workspace_id") or result.get("workspace_id")
    if not workspace:
        reason = (opened.get("error") or {}).get("code") or "no workspace_id"
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
        workspace_id=_open_workspace(
            herdr, repo_root=repo_root, path=path, branch=branch
        ),
    )
