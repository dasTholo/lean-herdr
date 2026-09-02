"""One handler per subcommand. Reads and shows -- never writes to lean-ctx.

A plugin handler is a one-shot process without an agent identity and CANNOT
write (B1-B3). Persistent state lives only in the digest under
HERDR_PLUGIN_STATE_DIR and in lean-ctx itself; the plugin keeps no register
of its own.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from lean_herdr.bus import BusError, canonical_root
from lean_herdr.config import Config
from lean_herdr.digest import render_digest, summary_token
from lean_herdr.herdr import Herdr
from lean_herdr.leanctx import LeanCtx, newest_handoff

#: The token belongs to the plugin. `esc` belongs to the orchestrator and is
#: never touched here -- not even to clear it.
TOKEN = "ctx"

#: The orchestrator pane of the bootstrap. minimal, because it only needs ctx_call.
ORCHESTRATOR = {
    "name": "orch",
    "kind": "opencode",
    "env": {"LEAN_CTX_TOOL_PROFILE": "minimal", "LEAN_CTX_ROLE": "orchestrator"},
}


def _note(text: str) -> None:
    """stderr ends up in `herdr plugin log list --plugin lean.herdr`."""
    sys.stderr.write(f"[lean.herdr] {text}\n")


def cwd_from_event(event: dict[str, Any] | None, herdr: Herdr, cfg: Config) -> Path | None:
    """cwd of the pane or workspace from the event -- else asked of Herdr."""
    for source in (event or {}, (event or {}).get("pane") or {}, (event or {}).get("workspace") or {}):
        if isinstance(source, dict) and source.get("cwd"):
            return Path(str(source["cwd"]))
    if cfg.pane_id:
        info = herdr.pane_process_info(cfg.pane_id)
        cwd = ((info.get("result") or {}).get("process_info") or {}).get("cwd")
        if cwd:
            return Path(str(cwd))
    return None


def _context(cwd: Path, cfg: Config) -> tuple[str | None, str | None]:
    """(digest, token text) for this cwd. (None, None) when there is nothing.

    The three nothing-cases are KEPT APART, because they must be handled
    differently -- that is what CtxResponse is for:
    * error or timeout -> a note on stderr, so `herdr plugin log list` has
      something to show. Something is broken.
    * valid, but empty -> silence. A fresh project is the normal case.
    Without that distinction every note would be either noise or missing.
    """
    try:
        root = canonical_root(cwd)
    except BusError as exc:
        _note(f"no repo at {cwd}: {exc}")
        return None, None
    leanctx = LeanCtx(root, timeout=cfg.timeout)
    resume = leanctx.session_resume()
    if not resume.ok:
        _note(f"ctx_session resume: {resume.error}")
        return None, None
    if not resume.text:
        return None, None  # fresh project -- not an error, no note

    # The handoff is a bonus: if it fails, the digest stays valid.
    handoff_text: str | None = None
    listing = leanctx.handoff_list()
    if listing.ok:
        path = newest_handoff(listing.text)
        if path:
            shown = leanctx.handoff_show(path)
            handoff_text = shown.text if shown.ok else None
    elif listing.error not in ("unavailable",):
        _note(f"ctx_handoff list: {listing.error}")

    return render_digest(resume.text, handoff_text), summary_token(resume.text)


def _show(cfg: Config, herdr: Herdr, scope: str, target: str, cwd: Path) -> None:
    digest, token = _context(cwd, cfg)
    if digest and scope == "pane":
        path = cfg.digest_path(target)
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(digest, encoding="utf-8")
    if token:
        herdr.report_metadata(scope, target, TOKEN, token)


# -- Handlers ----------------------------------------------------------


def handle_workspace_created(cfg: Config) -> None:
    """Resumption: after a server restart Herdr recreates the workspaces."""
    herdr = Herdr(cfg.herdr_bin, timeout=cfg.timeout)
    event = cfg.event or {}
    workspace = str(
        event.get("workspace_id")
        or (event.get("workspace") or {}).get("id")
        or cfg.workspace_id
        or ""
    )
    if not workspace:
        return
    cwd = cwd_from_event(event, herdr, cfg)
    if cwd is None:
        for entry in herdr.workspace_list():
            if str(entry.get("id")) == workspace and entry.get("cwd"):
                cwd = Path(str(entry["cwd"]))
                break
    if cwd is None:
        return
    _show(cfg, herdr, "workspace", workspace, cwd)


def handle_pane_detected(cfg: Config) -> None:
    """An agent was detected -- after `claude --resume` as well."""
    herdr = Herdr(cfg.herdr_bin, timeout=cfg.timeout)
    event = cfg.event or {}
    pane = str(event.get("pane_id") or (event.get("pane") or {}).get("id") or cfg.pane_id or "")
    if not pane:
        return
    cwd = cwd_from_event(event, herdr, cfg)
    if cwd is None:
        return
    _show(cfg, herdr, "pane", pane, cwd)


def handle_status_changed(cfg: Config) -> None:
    """Only refresh the token -- same path, same source."""
    handle_pane_detected(cfg)


def handle_inject(cfg: Config) -> None:
    """A deliberate gesture: send the stored digest to the pane's agent.

    Prompting automatically from a handler is out of the question -- it would
    run into agent_blocked and disturb someone who is typing.
    """
    herdr = Herdr(cfg.herdr_bin, timeout=cfg.timeout)
    event = cfg.event or {}
    pane = str(event.get("pane_id") or cfg.pane_id or "")
    path = cfg.digest_path(pane) if pane else None
    if path is None or not path.is_file():
        # Automation fails silently, a deliberate gesture fails visibly.
        herdr.run("notification", "show", "--message", "lean-herdr: no digest for this pane")
        return
    name = next(
        (str(a.get("name")) for a in herdr.agent_list() if str(a.get("pane_id")) == pane), ""
    )
    if not name:
        herdr.run("notification", "show", "--message", "lean-herdr: no agent in this pane")
        return
    herdr.agent_prompt(name, path.read_text(encoding="utf-8"), wait=False)


def handle_bootstrap(cfg: Config) -> None:
    """A deliberate gesture: open an orchestrator pane in THIS workspace.

    The handler does not act as an agent -- it only types what stage 3 step 1
    types by hand. An anchor pane from this workspace makes sure the new pane
    lands here and not in the caller's workspace.
    """
    herdr = Herdr(cfg.herdr_bin, timeout=cfg.timeout)
    event = cfg.event or {}
    workspace = str(
        event.get("workspace_id")
        or (event.get("workspace") or {}).get("id")
        or cfg.workspace_id
        or ""
    )
    if not workspace:
        herdr.run("notification", "show", "--message", "lean-herdr: no workspace")
        return
    if any(a.get("name") == ORCHESTRATOR["name"] for a in herdr.agent_list()):
        herdr.run(
            "notification", "show", "--message", "lean-herdr: the orchestrator is already running"
        )
        return
    cwd = cwd_from_event(event, herdr, cfg)
    anchor = next(
        (str(p["pane_id"]) for p in herdr.pane_list(workspace) if p.get("pane_id")), None
    )
    if cwd is None or anchor is None:
        herdr.run(
            "notification", "show", "--message", "lean-herdr: workspace without a pane or cwd"
        )
        return
    pane = herdr.pane_split(cwd, pane=anchor, env=ORCHESTRATOR["env"])
    if not pane:
        herdr.run("notification", "show", "--message", "lean-herdr: pane split failed")
        return
    herdr.agent_start(
        ORCHESTRATOR["name"],
        kind=ORCHESTRATOR["kind"],
        pane=pane,
        agent_args=["--agent", "orchestrator"],
    )
