"""HERDR_*/LEAN_HERDR_*-Umgebung → eine dataclass.

Herdr setzt HERDR_* in jedem Pane und in jedem Handler-Prozess; ein Skript
weiss damit ohne Zutun, wo es steht.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_HOOKS_DIR = Path.home() / ".claude" / "hooks"
DEFAULT_TIMEOUT_S = 5.0


def _float(raw: str | None, fallback: float) -> float:
    try:
        return float(raw) if raw else fallback
    except ValueError:
        return fallback


@dataclass(frozen=True)
class Config:
    pane_id: str | None = None
    workspace_id: str | None = None
    tab_id: str | None = None
    herdr_bin: str = "herdr"
    socket_path: str | None = None
    state_dir: Path | None = None
    event: dict[str, Any] | None = None
    hooks_dir: Path = DEFAULT_HOOKS_DIR
    timeout: float = DEFAULT_TIMEOUT_S

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Config:
        e = os.environ if env is None else env
        state = e.get("HERDR_PLUGIN_STATE_DIR")
        hooks = e.get("LEAN_HERDR_HOOKS_DIR")
        return cls(
            pane_id=e.get("HERDR_PANE_ID") or None,
            workspace_id=e.get("HERDR_WORKSPACE_ID") or None,
            tab_id=e.get("HERDR_TAB_ID") or None,
            herdr_bin=e.get("HERDR_BIN_PATH") or "herdr",
            socket_path=e.get("HERDR_SOCKET_PATH") or None,
            state_dir=Path(state) if state else None,
            event=cls._event(e.get("HERDR_PLUGIN_EVENT_JSON")),
            hooks_dir=Path(hooks) if hooks else DEFAULT_HOOKS_DIR,
            timeout=_float(e.get("LEAN_HERDR_TIMEOUT"), DEFAULT_TIMEOUT_S),
        )

    @staticmethod
    def _event(raw: str | None) -> dict[str, Any] | None:
        """Kaputtes Event-JSON ist kein Grund zu brechen — dann eben keins."""
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    def digest_path(self, key: str) -> Path | None:
        """Ablage des Digests je Pane. Ohne STATE_DIR gibt es keine Ablage."""
        return (self.state_dir / f"{key}.md") if self.state_dir else None
