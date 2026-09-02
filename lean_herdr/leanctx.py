"""lean-ctx-CLI → CtxAntwort, mit erzwungenem kanonischem --project-root.

ctx_session-Schreibaktionen fehlen hier absichtlich: sie melden Erfolg und
persistieren nichts (B1). ctx_agent read fehlt ebenfalls: es verlangt eine
Registrierung im selben Prozess (B9).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_TIMEOUT_S = 5.0

#: `lean-ctx call` meldet Fehler als erste Zeile, nicht ueber den Exit-Code.
FEHLER_PRAEFIXE = ("error:", "Error:")

#: Zeilen aus `ctx_handoff list`: "  1. /pfad/zur/datei.json"
LEDGER_ZEILE = re.compile(r"^\s*\d+\.\s+(\S+)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class CtxAntwort:
    """Eine Antwort von `lean-ctx call` — Text, nicht JSON.

    Drei Zustaende, die auseinandergehalten werden MUESSEN:
    ok=True  + text≠""  → Antwort mit Inhalt
    ok=True  + text=""  → gueltige, aber leere Antwort (frisches Projekt)
    ok=False + error    → unavailable | timeout | die Fehlerzeile von lean-ctx
    """

    ok: bool
    text: str = ""
    error: str | None = None

    def json(self) -> dict[str, Any]:
        """Eingebetteter JSON-Rumpf, falls einer da ist — sonst {}.

        `ctx_handoff show` schreibt zwei Kopfzeilen und danach JSON; andere
        Aufrufe gar keins. Deshalb ab der ersten `{` versuchen und schweigen,
        wenn es nicht aufgeht.
        """
        start = self.text.find("{")
        if start < 0:
            return {}
        try:
            daten = json.loads(self.text[start:])
        except json.JSONDecodeError:
            return {}
        return daten if isinstance(daten, dict) else {}


class LeanCtx:
    def __init__(
        self,
        project_root: str | Path,
        *,
        binary: str = "lean-ctx",
        timeout: float = DEFAULT_TIMEOUT_S,
        runner: Any = subprocess.run,
    ) -> None:
        #: Kommt aus bus.canonical_root() — nie aus $PWD, nie aus einem Worktree.
        self.project_root = str(project_root)
        self.binary = binary
        self.timeout = timeout
        self._runner = runner
        self._available: bool | None = None

    def is_available(self) -> bool:
        if self._available is None:
            self._available = shutil.which(self.binary) is not None
        return self._available

    def _run(self, args: list[str]) -> CtxAntwort:
        """Nie werfen, aber IMMER unterscheiden, warum nichts kam."""
        if not self.is_available():
            return CtxAntwort(False, error="unavailable")
        try:
            proc = self._runner(
                [self.binary, *args],
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            return CtxAntwort(False, error="timeout")
        except (OSError, subprocess.SubprocessError) as exc:
            return CtxAntwort(False, error=f"spawn_failed: {exc}")
        text = (proc.stdout or "").strip()
        erste = text.splitlines()[0] if text else ""
        if proc.returncode != 0 or erste.startswith(FEHLER_PRAEFIXE):
            return CtxAntwort(False, text, error=erste or f"exit {proc.returncode}")
        return CtxAntwort(True, text)

    def call(self, tool: str, arguments: dict[str, Any]) -> CtxAntwort:
        """`lean-ctx call <tool> --project-root <kanonisch> --json '<args>'`."""
        return self._run(
            [
                "call",
                tool,
                "--project-root",
                self.project_root,
                "--json",
                json.dumps(arguments, separators=(",", ":")),
            ]
        )

    # -- Bus (nur schreibend) -------------------------------------------

    def post(
        self,
        *,
        message: str,
        to_agent: str | None = None,
        task_id: str | None = None,
        category: str = "task",
        metadata: dict[str, Any] | None = None,
    ) -> CtxAntwort:
        """Put a message on the bus. NOT usable for work orders.

        From a CLI process this always posts as `anonymous`: registration is
        bound to the pid of a short-lived process (B-2), and the role prompts
        rightly refuse `anonymous` as a client. And `task_id` never arrives:
        every write path of `ctx_agent post` hard-sets it to `None`
        (core/agents/registry.rs:430, shared.rs:31). Work orders therefore run
        through `ctx_task`, see lean_herdr/tasks.py.

        `to_agent` MUST be a lean-ctx agent_id. A friendly name is accepted
        silently and never delivered (B7).
        """
        args: dict[str, Any] = {"action": "post", "message": message, "category": category}
        if to_agent:
            args["to_agent"] = to_agent
        if task_id:
            args["task_id"] = task_id
        if metadata:
            args["metadata"] = metadata
        return self.call("ctx_agent", args)

    # -- Kontext (nur lesend) -------------------------------------------

    def session_resume(self) -> CtxAntwort:
        """Fertiger Wiederaufnahme-Bericht: Projekt, Findings, Archive, Statistik.

        Der Text ist das Ergebnis, nicht ein Rohstoff. Er wird nicht zerlegt
        und nicht nachgebaut — Task 14 rahmt ihn nur.
        """
        return self.call("ctx_session", {"action": "resume"})

    def handoff_list(self) -> CtxAntwort:
        """Alle Handoff-Ledger, neueste zuerst."""
        return self.call("ctx_handoff", {"action": "list"})

    def handoff_show(self, path: str | Path) -> CtxAntwort:
        """Ein Ledger. `path` ist PFLICHT — ohne ihn: `error: -32602`."""
        return self.call("ctx_handoff", {"action": "show", "path": str(path)})


def newest_handoff(list_text: str) -> str | None:
    """Erster Pfad aus `ctx_handoff list` — die Liste kommt neueste zuerst."""
    treffer = LEDGER_ZEILE.search(list_text or "")
    return treffer.group(1) if treffer else None
