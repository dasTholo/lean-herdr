"""Herdr-CLI → dict. Aller Aussenverkehr zu Herdr liegt hier.

Kein Aufruf ohne Timeout: ohne ihn wartet Herdr unbegrenzt.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

DEFAULT_TIMEOUT_S = 10.0


class Herdr:
    """Duenner Wrapper um die Herdr-CLI. Fehler werden zu {}, nie zu Ausnahmen.

    Die Plugin-Handler duerfen nie etwas brechen, und die Skripte pruefen den
    Inhalt. Wer zwischen 'leer' und 'kaputt' unterscheiden muss, fragt
    is_available().
    """

    def __init__(
        self,
        binary: str = "herdr",
        *,
        timeout: float = DEFAULT_TIMEOUT_S,
        runner: Any = subprocess.run,
    ) -> None:
        self.binary = binary
        self.timeout = timeout
        self._runner = runner
        self._available: bool | None = None

    # -- Grundlage ----------------------------------------------------

    def is_available(self) -> bool:
        if self._available is None:
            self._available = shutil.which(self.binary) is not None
        return self._available

    def run(self, *args: str, timeout: float | None = None) -> dict[str, Any]:
        """`herdr <args>` ausfuehren und die Antwort als dict liefern.

        KEIN --json anhaengen: Herdr 0.8.2 kennt den Schalter nicht (weder global
        noch je Unterbefehl) und bricht mit exit 2 ab. Es gibt ihn nicht, weil
        Herdr ohnehin immer JSON auf stdout schreibt.
        """
        if not self.is_available():
            return {}
        cmd = [self.binary, *args]
        try:
            proc = self._runner(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout if timeout is not None else self.timeout,
            )
        except (OSError, subprocess.SubprocessError):
            return {}
        if proc.returncode != 0 and not proc.stdout.strip():
            return {}
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _result(data: dict[str, Any], *keys: str) -> Any:
        node: Any = data
        for key in ("result", *keys):
            if not isinstance(node, dict):
                return None
            node = node.get(key)
        return node

    # -- Panes und Agenten --------------------------------------------

    def pane_list(self, workspace: str | None = None) -> list[dict[str, Any]]:
        """Panes, optional auf einen Workspace eingeschraenkt."""
        args = ["pane", "list"]
        if workspace:
            args += ["--workspace", workspace]
        panes = self._result(self.run(*args), "panes")
        return [p for p in (panes or ()) if isinstance(p, dict)]

    def pane_split(
        self,
        cwd: str | Path,
        *,
        pane: str | None = None,
        direction: str = "right",
        env: dict[str, str] | None = None,
        focus: bool = False,
    ) -> str | None:
        """Neuen Pane anlegen und seine pane_id liefern.

        Der einzige Ort fuer --env: `agent start` kennt kein --env (H9).

        `pane` waehlt den Pane, der geteilt wird — und damit den Workspace, in
        dem der neue landet. Ohne ihn teilt Herdr `--current`, also IMMER den
        Workspace des Aufrufers. Fuer einen Arbeiter im Worktree ist das
        falsch: `workspace close <worktree_workspace>` wuerde ihn nicht
        beenden.
        """
        ziel = ["--pane", pane] if pane else ["--current"]
        args = ["pane", "split", *ziel, "--direction", direction, "--cwd", str(cwd)]
        if not focus:
            args.append("--no-focus")
        for key, value in (env or {}).items():
            args += ["--env", f"{key}={value}"]
        data = self.run(*args)
        # Gemessen gegen 0.8.2: {"result": {"pane": {"pane_id": "w1:p7", ...}}}.
        pane = self._result(data, "pane", "pane_id") or self._result(data, "pane_id")
        return str(pane) if pane else None

    def agent_start(
        self, name: str, *, kind: str, pane: str, agent_args: Sequence[str] = ()
    ) -> dict[str, Any]:
        """Agent im Pane starten. Native Argumente nach `--`.

        Mehrzeilige Argumente lehnt Herdr ab (H2) — Rollentexte kommen als
        Datei, nie als Argumenttext.
        """
        args = ["agent", "start", name, "--kind", kind, "--pane", pane]
        if agent_args:
            args = [*args, "--", *agent_args]
        return self.run(*args)

    def agent_prompt(
        self,
        name: str,
        text: str,
        *,
        wait: bool = True,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        """Klingeln. Steuerbefehle (/clear) IMMER mit wait=False senden (H4)."""
        args = ["agent", "prompt", name, text]
        if wait:
            args.append("--wait")
        if timeout_ms is not None:
            args += ["--timeout", str(timeout_ms)]
        budget = None if timeout_ms is None else timeout_ms / 1000.0 + self.timeout
        return self.run(*args, timeout=budget)

    def agent_list(self) -> list[dict[str, Any]]:
        agents = self._result(self.run("agent", "list"), "agents")
        return [a for a in (agents or ()) if isinstance(a, dict)]

    def pane_process_info(self, pane: str) -> dict[str, Any]:
        return self.run("pane", "process-info", "--pane", pane)

    # -- Sichtbarkeit --------------------------------------------------

    SOURCE = "lean.herdr"

    def report_metadata(
        self, scope: str, target: str, token: str, value: str
    ) -> bool:
        """`herdr <scope> report-metadata <id> --source lean.herdr --token k=v`.

        Zwei gemessene Eigenheiten (0.8.2): die ID ist POSITIONAL, nicht
        `--pane`/`--workspace`; und `--source` ist Pflicht — ohne sie exit 2.
        Die Source ist der Namensraum, unter dem unsere Tokens stehen; ein
        fremdes Plugin ueberschreibt sie damit nicht.

        scope ist "pane" oder "workspace". True, wenn der Aufruf durchging.
        """
        data = self.run(
            scope,
            "report-metadata",
            target,
            "--source",
            self.SOURCE,
            "--token",
            f"{token}={value}",
        )
        return bool(data)

    # -- Workspaces und Worktrees --------------------------------------

    def workspace_list(self) -> list[dict[str, Any]]:
        spaces = self._result(self.run("workspace", "list"), "workspaces")
        return [w for w in (spaces or ()) if isinstance(w, dict)]

    def workspace_close(self, workspace: str) -> dict[str, Any]:
        return self.run("workspace", "close", workspace)

    def worktree_list(self, cwd: str | Path) -> dict[str, Any]:
        return self.run("worktree", "list", "--cwd", str(cwd))

    def worktree_open(self, *, cwd: str | Path, path: str | Path, label: str) -> dict[str, Any]:
        """`--cwd` MUSS der Repo-Root sein, nie ein Linked-Worktree-Pfad (H8)."""
        return self.run(
            "worktree", "open", "--cwd", str(cwd), "--path", str(path), "--label", label
        )
