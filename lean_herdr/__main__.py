"""Subcommand dispatch for the plugin handlers: `lean-herdr plugin <sub>`.

A handler never breaks anything: every path ends with exit 0, every exception
lands on stderr — and thus in `herdr plugin log list --plugin lean.herdr`.
`python -m lean_herdr <sub>` from a checkout reaches the same `main`.
"""

from __future__ import annotations

import importlib
import sys

from lean_herdr.config import Config

#: Subcommand → function name in lean_herdr.handlers. Deliberately NAMES, not
#: function objects — see main().
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
        sys.stderr.write(f"[lean.herdr] unknown subcommand: {args[:1]}\n")
        return 0
    try:
        # Resolved late, by NAME. Two reasons, both concrete:
        # 1. lean_herdr.handlers may be missing -- a partial install, a broken
        #    module. An import at the module's top would take every subcommand
        #    down with it; this way, a missing handler costs one stderr line.
        # 2. A function object bound at import time could no longer be swapped
        #    in the test: a monkeypatch on handlers.handle_pane_detected would
        #    miss the stored entry, and the test would check nothing.
        handlers = importlib.import_module("lean_herdr.handlers")
        getattr(handlers, HANDLERS[args[0]])(Config.from_env())
    except Exception as exc:  # noqa: BLE001 — a handler never breaks anything
        sys.stderr.write(f"[lean.herdr] {args[0]} failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
