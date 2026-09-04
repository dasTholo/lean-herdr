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
from lean_herdr.settings import (
    SETTINGS_PATH,
    SettingsError,
    read_settings,
    settings_for,
    workspace_settings,
)

#: The token belongs to the plugin. `esc` belongs to the orchestrator and is
#: never touched here -- not even to clear it.
TOKEN = "ctx"

#: The keystroke is answered by the PANE, not by the agent id: a plugin
#: handler has nobody to show a result to, and Herdr's handler process is
#: the wrong place to sit out `[roles.orchestrator].ready_timeout_s` (45 s
#: by default). `lean-herdr workspace up` keeps the full wait -- its caller
#: reads the id off stdout and has a use for it.
#:
#: Measured 2026-09-04, an opencode orchestrator in a Herdr pane, from the
#: process appearing to its lean-ctx MCP server registering: **3.0 s warm**,
#: 363.6 s on the FIRST start in a project. The cap stood at 2.0 s and was
#: therefore below even the warm case -- the keystroke reported `no_agent_id`
#: on a run that had worked. Six is twice the measurement and still an order
#: of magnitude under the 45 s a handler must not sit out. The cold start
#: stays a false alarm; it happens once per project, and covering it would
#: mean blocking the handler for minutes.
KEYSTROKE_READY_TIMEOUT_S = 6.0


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

    Runs the SAME core as `lean-herdr workspace up`. Before this the
    keystroke read a literal in this module and never opened the config,
    so the two start paths could drift -- and did.

    The one difference stays in the argument: the workspace id comes from
    the event, so the core creates nothing and the pane lands here rather
    than in the caller's workspace.

    Unlike `up`, a missing config is NOT a stop here. `up` is a call whose
    whole purpose is the config; this is a keystroke that must not fail
    into nothing, so read_settings({}) and the built-in defaults carry it.
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
    cwd = cwd_from_event(event, herdr, cfg)
    if cwd is None:
        herdr.run(
            "notification", "show", "--message", "lean-herdr: workspace without a cwd"
        )
        return
    # Imported on the call, not up top. This module is imported by EVERY
    # plugin event, and `pane.agent_status_changed` fires constantly; the
    # `workspace -> dispatch -> ordercmd -> orderlog/llm` subtree measured
    # 10.7 ms of a 42 ms `import lean_herdr.handlers` on 2026-09-04. Only
    # this one handler needs it -- the same trade `workspace.main` makes
    # for `initcmd`, and the one cli.py's docstring argues for the router.
    from lean_herdr.workspace import start_orchestrator

    try:
        root = canonical_root(cwd)
        data = read_settings(root / SETTINGS_PATH)
        role = settings_for("orchestrator", data)
        result = start_orchestrator(
            herdr=herdr,
            root=root,
            settings=workspace_settings(data),
            profile=role.profile,
            model=role.model,
            kind=role.kind,
            workspace_id=workspace,
            ready_timeout_s=min(role.ready_timeout_s, KEYSTROKE_READY_TIMEOUT_S),
            # No second attempt here, for the same reason the timeout above is
            # capped: this process is Herdr's, and a hung first bootstrap
            # would hold it for another PANE_FREE_TIMEOUT_S plus a whole
            # retry. The cold start stays the accepted false alarm it already
            # is -- and it now cures itself, because the aborted attempt warms
            # the project and the next press comes up warm.
            retry_on_hang=False,
        )
    # `OSError` beside the two named ones, because `canonical_root()` shells
    # out to git: with no git on the PATH that is a bare FileNotFoundError
    # and NOT a BusError. `initcmd.workspace_init` reads the same call the
    # same way. Left out it escapes to `__main__`'s catch-all, and this one
    # failure reaches the operator as a stderr line in the plugin log while
    # every other one here shows a notification.
    except (BusError, SettingsError, OSError) as exc:
        herdr.run("notification", "show", "--message", f"lean-herdr: {exc}")
        return
    if result.get("already_running"):
        herdr.run(
            "notification",
            "show",
            "--message",
            "lean-herdr: the orchestrator is already running",
        )
    elif not result.get("ok"):
        herdr.run(
            "notification", "show", "--message", f"lean-herdr: {result.get('error')}"
        )
