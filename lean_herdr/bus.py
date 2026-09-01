"""Bus-Zugriff: kanonischer Projekt-Root und Nachrichten aus registry.json.

Die zwei Wahrheiten, die sich `bin/herdr-dispatch` und die Plugin-Handler
teilen. Beide existieren genau einmal, weil beide Seiten sie sonst
unterschiedlich falsch machen wuerden.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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


REGISTRY_PATH = Path.home() / ".local" / "share" / "lean-ctx" / "agents" / "registry.json"

#: Top-Level-Schluessel, unter dem lean-ctx die Bus-Nachrichten ablegt.
#: An einer echten registry.json verifiziert (2026-09-01) — nicht "messages".
MESSAGES_KEY = "scratchpad"

#: lean-ctx schreibt NEUN Nachkommastellen; fromisoformat vertraegt hoechstens
#: sechs und wirft sonst ValueError. Gemessen: 2026-08-01T15:10:08.404790674Z.
_NANOSEKUNDEN = re.compile(r"(\.\d{6})\d+")


def parse_zeit(text: str | None) -> datetime | None:
    """RFC-3339-Zeitstempel → aware datetime. Unlesbares wird zu None.

    None heisst hier ausdruecklich 'unbekannt', nicht 'jetzt' und nicht
    'abgelaufen' — ein unlesbarer Zeitstempel darf keine Nachricht verwerfen.
    """
    if not text:
        return None
    normal = _NANOSEKUNDEN.sub(r"\1", str(text).replace("Z", "+00:00"))
    try:
        wert = datetime.fromisoformat(normal)
    except ValueError:
        return None
    return wert if wert.tzinfo else wert.replace(tzinfo=UTC)


@dataclass(frozen=True)
class BusMessage:
    """Eine Bus-Nachricht, so wie registry.json sie traegt."""

    id: str
    from_agent: str
    to_agent: str | None
    task_id: str | None
    category: str
    priority: str
    privacy: str
    message: str
    metadata: dict[str, Any]
    project_root: str | None
    timestamp: str
    read_by: tuple[str, ...]
    expires_at: str | None

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> BusMessage:
        return cls(
            id=str(raw.get("id", "")),
            from_agent=str(raw.get("from_agent", "")),
            to_agent=raw.get("to_agent"),
            task_id=raw.get("task_id"),
            category=str(raw.get("category", "")),
            priority=str(raw.get("priority", "")),
            privacy=str(raw.get("privacy", "")),
            message=str(raw.get("message", "")),
            metadata=raw.get("metadata") or {},
            project_root=raw.get("project_root"),
            timestamp=str(raw.get("timestamp", "")),
            read_by=tuple(raw.get("read_by") or ()),
            expires_at=raw.get("expires_at"),
        )

    def is_expired(self, now: datetime) -> bool:
        """Abgelaufen? Ohne oder mit unlesbarem expires_at: nein.

        Die 12-h-TTL steht nur in der Dokumentation; im Feld ist das Feld
        meistens null. Fehlt es, gilt die Nachricht unbegrenzt — steht dort
        aber eine vergangene Zeit, ist sie tot und darf nicht mehr als
        aktuelles Ergebnis durchgehen.
        """
        frist = parse_zeit(self.expires_at)
        return frist is not None and frist <= now


def read_registry(path: str | Path | None = None) -> dict[str, Any]:
    """registry.json laden. Fehlt sie oder ist sie kaputt: BusError.

    Nie Erfolg durch Schweigen — ein leeres Ergebnis und ein unlesbarer Bus
    sind zwei verschiedene Dinge.
    """
    p = Path(path) if path is not None else REGISTRY_PATH
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise BusError(f"registry unreadable at {p}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BusError(f"registry malformed at {p}: {exc}") from exc
    if not isinstance(data, dict):
        raise BusError(f"registry has unexpected shape at {p}: {type(data).__name__}")
    return data


def parse_registry(
    data: dict[str, Any],
    *,
    project_root: str | Path,
    task_id: str | None = None,
    from_agent: str | None = None,
    now: datetime | None = None,
) -> list[BusMessage]:
    """Bus-Nachrichten dieses Projekts, optional auf Aufgabe und Absender gefiltert.

    `project_root` ist ein Kanonisierungsergebnis (canonical_root()), kein $PWD.
    Nachrichten ohne `project_root` werden mitgenommen — lean-ctx setzt das Feld
    nicht immer —, Nachrichten eines fremden Roots nie. Abgelaufene fallen weg;
    `now` ist injizierbar, damit der Test keine Uhr braucht.
    """
    if MESSAGES_KEY not in data:
        raise BusError(
            f"registry hat keinen Schluessel {MESSAGES_KEY!r} — "
            f"Format geaendert? vorhanden: {sorted(data)}"
        )
    wanted = str(Path(project_root).resolve())
    jetzt = now if now is not None else datetime.now(UTC)
    out: list[BusMessage] = []
    for raw in data[MESSAGES_KEY] or ():
        if not isinstance(raw, dict):
            continue
        msg = BusMessage.from_raw(raw)
        if msg.project_root is not None and msg.project_root != wanted:
            continue
        if msg.is_expired(jetzt):
            continue
        if task_id is not None and msg.task_id != task_id:
            continue
        if from_agent is not None and msg.from_agent != from_agent:
            continue
        out.append(msg)
    return out


def agents_in_registry(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Die registrierten Agenten — Quelle fuer den PID-Join (Task 3)."""
    return [a for a in (data.get("agents") or ()) if isinstance(a, dict)]
