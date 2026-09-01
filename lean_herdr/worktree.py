"""Worktree-Aufloesung: worktrunk erzeugt, Herdr bildet ab.

Kein eigenes Register — Herdr fuehrt die Zuordnung Worktree → Workspace
selbst, und `wt switch --format json` liefert den Pfad direkt.
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
    """`wt` ist nicht installiert — ohne --worktree laeuft trotzdem alles."""


class WorktreeOpenFailed(RuntimeError):
    """Der Baum steht, aber Herdr hat keinen Workspace darauf geoeffnet.

    Das ist ein Abbruchgrund, kein Schoenheitsfehler: ohne Workspace laeuft
    der Pane zwar im richtigen Verzeichnis, aber der Abbau findet ihn nicht
    mehr und ein `linked_worktree_source` (H8) bliebe unbemerkt.
    """


@dataclass(frozen=True)
class WorktreeTarget:
    """Ein Worktree, wie der Dispatch ihn braucht: Pfad UND Workspace.

    `workspace_id` ist nicht optional. Ein Ziel ohne Workspace waere nur halb
    da — der Pane kaeme in den falschen Workspace und der Abbau fiele aus.
    """

    path: Path
    workspace_id: str


def repo_root_from(worktree_list: dict[str, Any]) -> Path | None:
    """`.result.source.repo_root` — nie $PWD annehmen (H8)."""
    root = ((worktree_list.get("result") or {}).get("source") or {}).get("repo_root")
    return Path(root) if root else None


def find_worktree(worktree_list: dict[str, Any], branch: str) -> dict[str, Any] | None:
    for eintrag in (worktree_list.get("result") or {}).get("worktrees") or ():
        if isinstance(eintrag, dict) and eintrag.get("branch") == branch:
            return eintrag
    return None


def wt_switch(
    branch: str, *, cwd: str | Path, runner: Any = subprocess.run
) -> Path | None:
    """`wt switch --create <branch> --no-cd --format json --yes` → .path.

    `--no-cd`, weil das Skript nicht umzieht; `--yes`, weil kein Mensch am
    Approval-Prompt sitzt.
    """
    if shutil.which("wt") is None:
        raise WorktrunkMissing("wt ist nicht installiert")
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
    pfad = data.get("path") if isinstance(data, dict) else None
    return Path(pfad) if pfad else None


def _open_workspace(
    herdr: Herdr, *, repo_root: Path, path: Path, branch: str
) -> str:
    """Worktree bei Herdr oeffnen und die Workspace-ID liefern — oder scheitern.

    --cwd MUSS der Repo-Root sein; aus einem Linked-Worktree-Workspace heraus
    lehnt Herdr mit `linked_worktree_source` ab (H8). Genau dieser Fall kaeme
    sonst als leeres dict zurueck und saehe aus wie Erfolg.
    """
    geoeffnet = herdr.worktree_open(cwd=repo_root, path=path, label=branch)
    ergebnis = geoeffnet.get("result") or {}
    workspace = ergebnis.get("open_workspace_id") or ergebnis.get("workspace_id")
    if not workspace:
        grund = (geoeffnet.get("error") or {}).get("code") or "keine workspace_id"
        raise WorktreeOpenFailed(f"worktree open fuer {branch}: {grund}")
    return str(workspace)


def anchor_pane(herdr: Herdr, workspace_id: str) -> str | None:
    """Irgendein Pane dieses Workspaces — der Ankerpunkt fuers Teilen.

    `pane split --current` teilt den Workspace des Aufrufers, also den des
    Orchestrators. Ein so entstandener Arbeiter liegt im falschen Workspace:
    `workspace close <worktree_workspace>` beendet ihn nicht, und der Abbau
    laesst eine Leiche stehen. Deshalb wird gezielt ein Pane des
    Worktree-Workspaces geteilt.
    """
    for pane in herdr.pane_list(workspace_id):
        pane_id = pane.get("pane_id")
        if pane_id:
            return str(pane_id)
    return None


def ensure_worktree(
    branch: str, *, herdr: Herdr, cwd: str | Path, runner: Any = subprocess.run
) -> WorktreeTarget:
    """Worktree des Branches — vorhandenen wiederverwenden, sonst anlegen.

    Reihenfolge: erst Herdr fragen (der Worktree kann schon offen sein), dann
    worktrunk erzeugen lassen, dann bei Herdr registrieren. Am Ende steht in
    JEDEM Fall eine Workspace-ID; ein Ziel ohne sie waere nur halb da.
    """
    liste = herdr.worktree_list(cwd)
    repo_root = repo_root_from(liste) or Path(cwd)

    vorhanden = find_worktree(liste, branch)
    if vorhanden and vorhanden.get("path"):
        pfad = Path(vorhanden["path"])
        # Der Baum kann stehen, ohne dass ein Workspace darauf zeigt — z. B.
        # nach einem Herdr-Neustart. Dann wird er hier nachgeoeffnet.
        workspace = vorhanden.get("open_workspace_id")
        return WorktreeTarget(
            path=pfad,
            workspace_id=str(workspace)
            if workspace
            else _open_workspace(herdr, repo_root=repo_root, path=pfad, branch=branch),
        )

    pfad = wt_switch(branch, cwd=repo_root, runner=runner)
    if pfad is None:
        raise WorktrunkMissing(f"wt switch lieferte keinen Pfad fuer {branch}")

    return WorktreeTarget(
        path=pfad,
        workspace_id=_open_workspace(
            herdr, repo_root=repo_root, path=pfad, branch=branch
        ),
    )
