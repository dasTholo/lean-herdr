"""Subcommand-Dispatch der Plugin-Handler.

Ein Handler bricht nie etwas: jeder Pfad endet mit exit 0, jede Ausnahme
landet auf stderr — und damit in `herdr plugin log list --plugin lean.herdr`.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lean_herdr.config import Config

#: Subcommand → Funktionsname in lean_herdr.handlers. Bewusst NAMEN, nicht
#: Funktionsobjekte — siehe main().
HANDLERS = {
    "workspace-created": "handle_workspace_created",
    "pane-detected": "handle_pane_detected",
    "status-changed": "handle_status_changed",
    "inject": "handle_inject",
    "bootstrap": "handle_bootstrap",
}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] not in HANDLERS:
        sys.stderr.write(f"[lean.herdr] unbekannter Subcommand: {args[:1]}\n")
        return 0
    try:
        # Spaet und ueber den NAMEN aufloesen. Zwei Gruende, beide handfest:
        # 1. lean_herdr.handlers entsteht erst in Task 15. Ein Import am
        #    Modulkopf liesse schon diese Task an ihrem eigenen Testlauf
        #    scheitern; so meldet ein fehlender Handler nur eine stderr-Zeile.
        # 2. Ein zur Importzeit gebundenes Funktionsobjekt waere im Test nicht
        #    mehr zu ersetzen: ein monkeypatch auf handlers.handle_pane_detected
        #    ginge am gespeicherten Eintrag vorbei, und der Test pruefte nichts.
        handlers = importlib.import_module("lean_herdr.handlers")
        getattr(handlers, HANDLERS[args[0]])(Config.from_env())
    except Exception as exc:  # noqa: BLE001 — ein Handler bricht nie etwas
        sys.stderr.write(f"[lean.herdr] {args[0]} fehlgeschlagen: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
