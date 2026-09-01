"""Bus-Zugriff: kanonischer Projekt-Root und Nachrichten aus registry.json.

Die zwei Wahrheiten, die sich `bin/herdr-dispatch` und die Plugin-Handler
teilen. Beide existieren genau einmal, weil beide Seiten sie sonst
unterschiedlich falsch machen wuerden.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

GIT_TIMEOUT_S = 5.0


class BusError(RuntimeError):
    """Der Bus ist nicht lesbar — nie stillschweigend als Erfolg werten."""


def canonical_root(cwd: str | Path | None = None) -> Path:
    """Repo-Root eines Checkouts, auch aus einem Linked Worktree heraus.

    `git rev-parse --git-common-dir` zeigt aus jedem Worktree auf das `.git`
    des Haupt-Checkouts; dessen Elternverzeichnis ist der Root, auf den
    lean-ctx einen stdio-Server ohnehin kanonisiert. Jeder
    `--project-root`-Wert im Projekt kommt aus dieser Funktion — nie aus
    $PWD, nie aus einem Worktree-Pfad (B12).
    """
    proc = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_S,
        check=False,
    )
    if proc.returncode != 0:
        raise BusError(f"git rev-parse --git-common-dir failed: {proc.stderr.strip()}")
    common = Path(proc.stdout.strip())
    if not common.is_absolute():
        base = Path(cwd) if cwd is not None else Path.cwd()
        common = base / common
    return common.resolve().parent
