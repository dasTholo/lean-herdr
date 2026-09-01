"""Nativer Session-Export → Fehlerobjekt.

Der einzige verlaessliche Ort fuer 'ist der Turn gescheitert?'. Herdrs
agent_status kodiert kein Scheitern (H1).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

#: Schluessel, unter denen die Agenten ihr Fehlerobjekt ablegen.
ERROR_KEYS = ("error", "lastError", "last_error")

#: opencode legt seine Sitzungen in genau einer SQLite-Datei ab.
OPENCODE_DB = Path.home() / ".local" / "share" / "opencode" / "opencode.db"


def _format(err: dict[str, Any]) -> str:
    name = err.get("name") or err.get("type") or "error"
    roh = err.get("data")
    data: dict[str, Any] = roh if isinstance(roh, dict) else {}
    message = data.get("message") or err.get("message") or ""
    status = data.get("statusCode") or data.get("status_code") or err.get("statusCode")
    teile = [str(name)]
    if message:
        teile.append(str(message))
    text = ": ".join(teile)
    return f"{text} ({status})" if status else text


def find_error(export: Any) -> str | None:
    """Erstes Fehlerobjekt irgendwo im Export, als Klartext.

    Rekursiv, weil die Verschachtelung je Agent und Version verschieden ist.
    Ein leeres oder null-wertiges error-Feld gilt als 'kein Fehler'.
    """
    if isinstance(export, dict):
        for key in ERROR_KEYS:
            err = export.get(key)
            if isinstance(err, dict) and err:
                return _format(err)
            if isinstance(err, str) and err.strip():
                return err.strip()
        for value in export.values():
            found = find_error(value)
            if found is not None:
                return found
        return None
    if isinstance(export, list):
        for item in export:
            found = find_error(item)
            if found is not None:
                return found
    return None


def session_id_from_agent_list(agent_list: Iterable[dict[str, Any]], name: str) -> str | None:
    """agent_session.value aus `herdr agent list`.

    Nie cachen: die Session-ID wechselt bei jedem /clear.
    """
    for entry in agent_list:
        if entry.get("name") != name:
            continue
        session = entry.get("agent_session")
        if isinstance(session, dict):
            value = session.get("value")
            return str(value) if value else None
        if isinstance(session, str) and session:
            return session
    return None


# -- Die zwei Ablagen --------------------------------------------------


def claude_session_path(session_id: str, project_root: str | Path) -> Path:
    """~/.claude/projects/<slug>/<session_id>.jsonl — slug = Pfad mit / → -."""
    slug = str(Path(project_root).resolve()).replace("/", "-")
    return Path.home() / ".claude" / "projects" / slug / f"{session_id}.jsonl"


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """JSONL-Zeilen lesen. Fehlt die Datei oder ist eine Zeile kaputt: ueberspringen."""
    try:
        roh = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    zeilen: list[dict[str, Any]] = []
    for zeile in roh.splitlines():
        zeile = zeile.strip()
        if not zeile:
            continue
        try:
            daten = json.loads(zeile)
        except json.JSONDecodeError:
            continue
        if isinstance(daten, dict):
            zeilen.append(daten)
    return zeilen


def opencode_messages(session_id: str, db_path: str | Path | None = None) -> list[dict[str, Any]]:
    """message.data dieser Sitzung aus opencodes SQLite-Ablage.

    Nur lesend und `immutable=1`: opencode schreibt in dieselbe Datei, waehrend
    wir lesen — ohne diese Flags riskiert man `database is locked`.
    """
    pfad = Path(db_path) if db_path is not None else OPENCODE_DB
    if not pfad.is_file():
        return []
    try:
        con = sqlite3.connect(f"file:{pfad}?mode=ro&immutable=1", uri=True, timeout=2.0)
    except sqlite3.Error:
        return []
    try:
        zeilen = con.execute(
            "SELECT data FROM message WHERE session_id = ? ORDER BY time_created",
            (session_id,),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()
    nachrichten: list[dict[str, Any]] = []
    for (roh,) in zeilen:
        try:
            daten = json.loads(roh)
        except json.JSONDecodeError, TypeError:
            continue
        if isinstance(daten, dict):
            nachrichten.append(daten)
    return nachrichten


def session_error(
    kind: str,
    session_id: str | None,
    project_root: str | Path,
    *,
    db_path: str | Path | None = None,
) -> str | None:
    """Der Fehler dieser Sitzung, egal welcher Agent sie gefuehrt hat.

    None heisst: kein Fehler gefunden — auch dann, wenn die Ablage fehlt.
    Der Aufrufer unterscheidet das nicht, weil beides dieselbe Folge hat:
    es gibt keinen Beleg fuer ein Scheitern, also bleibt es bei `no_reply`.
    """
    if not session_id:
        return None
    if kind == "claude":
        return find_error(read_jsonl(claude_session_path(session_id, project_root)))
    if kind == "opencode":
        return find_error(opencode_messages(session_id, db_path))
    return None
