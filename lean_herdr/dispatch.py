"""Eine Zuteilung = ein Aufruf.

Reine Mechanik: das Skript fragt kein Modell und trifft keine
Zuordnungsentscheidung. Wer welche Aufgabe bekommt, entscheidet der
Orchestrator, bevor er hier hereinkommt.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lean_herdr.bus import (
    BusError,
    BusMessage,
    agents_in_registry,
    canonical_root,
    parse_registry,
    read_registry,
)
from lean_herdr.export import session_error, session_id_from_agent_list
from lean_herdr.herdr import Herdr
from lean_herdr.join import resolve_agent_id
from lean_herdr.leanctx import LeanCtx
from lean_herdr.worktree import (
    WorktreeOpenFailed,
    WorktrunkMissing,
    anchor_pane,
    ensure_worktree,
)

#: Voreinstellung je Rolle — gemessene Fixkosten je Schritt:
#: minimal 2 711, standard 4 920, power 11 559 Token.
PROFILE_BY_ROLE = {"orchestrator": "minimal"}
DEFAULT_PROFILE = "standard"

#: Antwortkategorien, die eine Aufgabe beenden.
ANTWORT_KATEGORIEN = ("result", "reject", "blocked")

AGENT_READY_TIMEOUT_S = 45.0
AGENT_READY_INTERVAL_S = 0.5


@dataclass(frozen=True)
class DispatchRequest:
    role: str
    kind: str
    model: str
    role_file: Path
    task_id: str
    task: str
    worktree: str | None = None
    profile: str | None = None
    timeout_ms: int = 300_000


def profile_for(role: str, override: str | None = None) -> str:
    return override or PROFILE_BY_ROLE.get(role, DEFAULT_PROFILE)


def agent_name(role: str, worktree: str | None = None) -> str:
    """Der Wiederverwendungsschluessel ist (branch, rolle), nicht der Branch allein.

    Ein Worktree traegt mehrere Arbeiter — Builder und Reviewer —, und ein
    Reviewer-Dispatch auf denselben Branch darf niemals den laufenden Builder
    treffen.
    """
    if not worktree:
        return role
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", worktree).strip("-").lower()
    return f"{role}-{slug}"


def agent_args(kind: str, model: str, role_file: Path) -> list[str]:
    """Native Argumente. Rollentexte gehen als DATEI, nie als Argumenttext (H2)."""
    if kind == "claude":
        return ["--model", model, "--append-system-prompt-file", str(role_file)]
    if kind == "opencode":
        # Der Rollentext haengt bei opencode an agent.<name>.prompt in
        # opencode.jsonc; hier wird nur der Agent gewaehlt.
        return ["--model", model, "--agent", role_file.stem]
    raise ValueError(f"unbekannter kind: {kind}")


def wait_for_agent_id(
    herdr: Herdr,
    name: str,
    *,
    registry_path: str | Path | None = None,
    timeout_s: float = AGENT_READY_TIMEOUT_S,
    interval_s: float = AGENT_READY_INTERVAL_S,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> str | None:
    """Auf den MCP-Server des frisch gestarteten Agenten warten.

    Blockiert im Shell-Aufruf, nicht im Modell — das ist der billige Teil.
    """
    frist = now() + timeout_s
    while True:
        agents = herdr.agent_list()
        pane = next((a.get("pane_id") for a in agents if a.get("name") == name), None)
        if pane:
            info = herdr.pane_process_info(str(pane))
            try:
                registry = read_registry(registry_path)
            except BusError:
                registry = {}
            agent_id = resolve_agent_id(
                agents, info, agents_in_registry(registry), name=name
            )
            if agent_id:
                return agent_id
        if now() >= frist:
            return None
        sleep(interval_s)


def find_reply(
    registry: dict[str, Any],
    *,
    project_root: str | Path,
    task_id: str,
    from_agent: str,
) -> BusMessage | None:
    """Juengste Antwort dieses Arbeiters zu dieser Aufgabe."""
    treffer = [
        m
        for m in parse_registry(
            registry, project_root=project_root, task_id=task_id, from_agent=from_agent
        )
        if m.category in ANTWORT_KATEGORIEN
    ]
    return max(treffer, key=lambda m: m.timestamp) if treffer else None


def _ergebnis(
    ok: bool, req: DispatchRequest, pane: str | None, agent_id: str | None, **rest: Any
) -> dict[str, Any]:
    return {"ok": ok, "task_id": req.task_id, "pane": pane, "agent_id": agent_id, **rest}


def dispatch(
    req: DispatchRequest,
    *,
    herdr: Herdr,
    leanctx: LeanCtx,
    root: Path,
    cwd: Path | None = None,
    registry_path: str | Path | None = None,
    waiter: Callable[..., str | None] = wait_for_agent_id,
) -> dict[str, Any]:
    """Eine ganze Zuteilung. Wirft nie; das Ergebnis traegt `ok`."""
    name = agent_name(req.role, req.worktree)
    ziel_cwd = cwd if cwd is not None else root
    # None heisst: im eigenen Workspace teilen (--current). Nur der
    # Worktree-Fall setzt einen Anker.
    ziel_pane: str | None = None
    if req.worktree:
        try:
            ziel = ensure_worktree(req.worktree, herdr=herdr, cwd=root)
        except WorktrunkMissing:
            return _ergebnis(False, req, None, None, error="worktrunk_missing")
        except WorktreeOpenFailed as exc:
            # Nicht weiterlaufen: ein Pane im richtigen Verzeichnis, den der
            # Abbau nicht kennt, ist schlimmer als ein sauberer Abbruch.
            return _ergebnis(False, req, None, None, error=f"worktree_open_failed: {exc}")
        ziel_cwd = ziel.path
        ziel_pane = anchor_pane(herdr, ziel.workspace_id)
        if ziel_pane is None:
            return _ergebnis(False, req, None, None, error="no_anchor_pane")

    vorhanden = next((a for a in herdr.agent_list() if a.get("name") == name), None)
    if vorhanden:
        pane = str(vorhanden.get("pane_id") or "")
        # Zwischen zwei Aufgaben zuruecksetzen: /clear deckelt den Kontext auf
        # die Grundlast und loest KEINEN Lifecycle-Wechsel aus (H4).
        herdr.agent_prompt(name, "/clear", wait=False)
    else:
        pane = herdr.pane_split(
            ziel_cwd,
            pane=ziel_pane,
            env={
                "LEAN_CTX_TOOL_PROFILE": profile_for(req.role, req.profile),
                "LEAN_CTX_ROLE": req.role,
            },
        ) or ""
        if not pane:
            return _ergebnis(False, req, None, None, error="pane_split_failed")
        herdr.agent_start(
            name,
            kind=req.kind,
            pane=pane,
            agent_args=agent_args(req.kind, req.model, req.role_file),
        )

    agent_id = waiter(herdr, name, registry_path=registry_path)
    if not agent_id:
        return _ergebnis(False, req, pane, None, error="no_agent_id")

    # Der Bus traegt den Inhalt, der Prompt nur die Klingel.
    gepostet = leanctx.post(
        message=req.task,
        to_agent=agent_id,
        task_id=req.task_id,
        category="task",
        metadata={"role": req.role, "branch": req.worktree or ""},
    )
    if not gepostet.ok:
        # Ohne Aufgabe auf dem Bus ist die Klingel sinnlos: der Arbeiter faende
        # nichts und wir haetten am Ende ein irrefuehrendes `no_reply`.
        return _ergebnis(
            False, req, pane, agent_id, error=f"post_failed: {gepostet.error}"
        )
    herdr.agent_prompt(
        name,
        f"Neue Aufgabe {req.task_id} liegt auf dem Bus.",
        wait=True,
        timeout_ms=req.timeout_ms,
    )

    try:
        registry = read_registry(registry_path)
    except BusError:
        return _ergebnis(False, req, pane, agent_id, error="bus_unreadable")

    antwort = find_reply(
        registry, project_root=root, task_id=req.task_id, from_agent=agent_id
    )
    if antwort is not None:
        return _ergebnis(
            antwort.category != "blocked",
            req,
            pane,
            agent_id,
            category=antwort.category,
            result=antwort.message,
        )

    # Keine Antwort: die Wahrheit steht in der Sitzungsablage, nicht im Zustand
    # (H1). Herdr liefert nur die ID; gelesen wird bei Claude die JSONL-Datei,
    # bei opencode die SQLite-Ablage — `herdr agent export` gibt es nicht.
    fehler = session_error(
        req.kind, session_id_from_agent_list(herdr.agent_list(), name), root
    )
    if fehler:
        return _ergebnis(False, req, pane, agent_id, error=f"agent_error: {fehler}")
    return _ergebnis(False, req, pane, agent_id, error="no_reply")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="herdr-dispatch", description="Eine Zuteilung, ein Aufruf.")
    p.add_argument("role", help="builder | reviewer | orchestrator")
    p.add_argument("--kind", required=True, choices=("claude", "opencode"))
    p.add_argument("--model", required=True)
    p.add_argument("--role-file", required=True, type=Path)
    p.add_argument("--task-id", required=True)
    p.add_argument("--task", required=True)
    p.add_argument("--worktree", default=None, help="Branch; der Pane laeuft in dessen Worktree")
    p.add_argument("--profile", default=None, help="ueberschreibt die Voreinstellung der Rolle")
    p.add_argument("--timeout-ms", type=int, default=300_000)
    return p


def main(argv: list[str] | None = None) -> int:
    """Ausgabe: eine JSON-Zeile auf stdout. Exit IMMER 0.

    Der Orchestrator liest `ok`, nicht den Exit-Code — damit ein Fehlschlag
    nicht seinen Shell-Aufruf abbricht.
    """
    args = build_parser().parse_args(argv)
    req = DispatchRequest(
        role=args.role,
        kind=args.kind,
        model=args.model,
        role_file=args.role_file,
        task_id=args.task_id,
        task=args.task,
        worktree=args.worktree,
        profile=args.profile,
        timeout_ms=args.timeout_ms,
    )
    try:
        root = canonical_root()
        herdr = Herdr()
        ergebnis = dispatch(
            req, herdr=herdr, leanctx=LeanCtx(root), root=root, cwd=root
        )
    except Exception as exc:  # noqa: BLE001 -- nie den Aufrufer abbrechen
        ergebnis = {
            "ok": False,
            "task_id": req.task_id,
            "pane": None,
            "agent_id": None,
            "error": f"dispatch_crashed: {exc}",
        }
    sys.stdout.write(json.dumps(ergebnis, ensure_ascii=False) + "\n")
    return 0
