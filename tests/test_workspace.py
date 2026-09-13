"""`workspace up` and the core the keystroke shares with it."""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from lean_herdr import workspace
from lean_herdr.bus import BusError
from lean_herdr.herdr import FIRST_START_TIMEOUT_MS, Herdr
from lean_herdr.llm import GENERATE_EFFORT, PREREVIEW_EFFORT
from lean_herdr.settings import OVERLAY_PATH, SETTINGS_PATH, SettingsError, WorkspaceSettings
from tests.doubles import (
    FakeProc,
    agent_started,
    which_stub,
    write_opencode_config,
)

#: A REAL directory, not the `/repo` literal this used to be. The core now
#: stats `<root>/opencode.jsonc` before it does anything else, so a root
#: that cannot hold one would turn every test in this file into the guard's
#: message. Created at import because the herdr replies below quote it;
#: filled and removed again by `_project`.
ROOT = Path(tempfile.mkdtemp(prefix="lean-herdr-workspace-"))


@pytest.fixture(scope="module", autouse=True)
def _project():
    """Every core test runs in a project opencode could actually resolve."""
    write_opencode_config(ROOT)
    yield
    shutil.rmtree(ROOT, ignore_errors=True)


#: A workspace found by rule 1 -- worktree.checkout_path == root.
BY_WORKTREE = {
    "result": {
        "workspaces": [
            {
                "workspace_id": "w3",
                "worktree": {"checkout_path": str(ROOT)},
            }
        ]
    }
}

#: A workspace `workspace create --cwd` made itself: worktree is null, so
#: rule 1 cannot see it and only the pane fallback can.
WITHOUT_WORKTREE = {"result": {"workspaces": [{"workspace_id": "w3", "worktree": None}]}}

PANES = {"result": {"panes": [{"pane_id": "w3:p1", "cwd": str(ROOT), "workspace_id": "w3"}]}}
NO_AGENTS = {"result": {"agents": []}}
SPLIT = {"result": {"pane": {"pane_id": "w3:p9"}}}

#: A start that worked. Underneath every `replies`, never on top of it: an
#: unanswered ("agent", "start") falls back to FakeProc's empty default, which
#: is what a REFUSAL looks like here -- so without this every test in the file
#: would take the refusal path and none would reach the wait.
STARTED = {("agent", "start"): agent_started("orch", "w3:p9")}


def herdr_with(monkeypatch, replies, *, available=True):
    monkeypatch.setattr("shutil.which", which_stub(available))
    proc = FakeProc(replies={**STARTED, **replies})
    return Herdr(runner=proc), proc


def core(herdr, **rest):
    defaults = {
        "root": ROOT,
        "settings": WorkspaceSettings(),
        "profile": "minimal",
        "model": "",
        "kind": "opencode",
        "workspace_id": None,
        "ready_timeout_s": 1.0,
        "waiter": lambda *a, **k: "mcp-42",
    }
    return workspace.start_orchestrator(herdr=herdr, **{**defaults, **rest})


def test_without_the_binary_there_is_no_server(monkeypatch):
    herdr, _ = herdr_with(monkeypatch, {}, available=False)
    assert core(herdr)["error"] == "no_herdr_server"


def test_an_empty_workspace_list_reply_is_a_dead_socket(monkeypatch):
    """workspace_list() would flatten this onto []; the raw reply does not."""
    herdr, _ = herdr_with(monkeypatch, {("workspace", "list"): {}})
    assert core(herdr)["error"] == "no_herdr_server"


def test_a_running_orchestrator_starts_no_second_one(monkeypatch):
    replies = {
        ("workspace", "list"): BY_WORKTREE,
        ("agent", "list"): {"result": {"agents": [{"name": "orch", "pane_id": "w3:p2"}]}},
    }
    herdr, proc = herdr_with(monkeypatch, replies)
    answer = core(herdr)
    assert answer["ok"] is True and answer["already_running"] is True
    assert answer["pane"] == "w3:p2"
    assert not proc.called_with("pane", "split"), proc.flat()


def test_rule_one_finds_the_workspace_by_checkout_path(monkeypatch):
    replies = {
        ("workspace", "list"): BY_WORKTREE,
        ("agent", "list"): NO_AGENTS,
        ("pane", "list"): PANES,
        ("pane", "split"): SPLIT,
    }
    herdr, proc = herdr_with(monkeypatch, replies)
    assert core(herdr)["workspace"] == "w3"
    assert not proc.called_with("workspace", "create"), proc.flat()


def test_rule_two_finds_it_by_pane_cwd_when_the_worktree_is_null(monkeypatch):
    """The case a `worktree: null` workspace would otherwise duplicate."""
    replies = {
        ("workspace", "list"): WITHOUT_WORKTREE,
        ("agent", "list"): NO_AGENTS,
        ("pane", "list"): PANES,
        ("pane", "split"): SPLIT,
    }
    herdr, proc = herdr_with(monkeypatch, replies)
    assert core(herdr)["workspace"] == "w3"
    assert not proc.called_with("workspace", "create"), proc.flat()


def test_neither_rule_hits_so_a_workspace_is_created(monkeypatch):
    replies = {
        ("workspace", "list"): {"result": {"workspaces": []}},
        ("workspace", "create"): {"result": {"workspace": {"workspace_id": "w9"}}},
        ("agent", "list"): NO_AGENTS,
        ("pane", "list"): {"result": {"panes": [{"pane_id": "w9:p1", "workspace_id": "w9"}]}},
        ("pane", "split"): SPLIT,
    }
    herdr, proc = herdr_with(monkeypatch, replies)
    assert core(herdr)["workspace"] == "w9"
    assert proc.called_with("workspace", "create", "--cwd", "--label", ROOT.name)
    assert proc.called_with("--env", "LEAN_CTX_TOOL_PROFILE=minimal")


def test_a_given_workspace_id_never_creates_one(monkeypatch):
    """The keystroke path: it must land where the key was pressed."""
    replies = {
        ("workspace", "list"): {"result": {"workspaces": []}},
        ("agent", "list"): NO_AGENTS,
        ("pane", "list"): {"result": {"panes": [{"pane_id": "w7:p1", "workspace_id": "w7"}]}},
        ("pane", "split"): SPLIT,
    }
    herdr, proc = herdr_with(monkeypatch, replies)
    assert core(herdr, workspace_id="w7")["workspace"] == "w7"
    assert not proc.called_with("workspace", "create"), proc.flat()


def test_a_workspace_without_a_pane_is_no_anchor_pane(monkeypatch):
    replies = {
        ("workspace", "list"): BY_WORKTREE,
        ("agent", "list"): NO_AGENTS,
        ("pane", "list"): {"result": {"panes": []}},
    }
    herdr, _ = herdr_with(monkeypatch, replies)
    assert core(herdr)["error"] == "no_anchor_pane"


def test_a_failed_split_says_so(monkeypatch):
    replies = {
        ("workspace", "list"): BY_WORKTREE,
        ("agent", "list"): NO_AGENTS,
        ("pane", "list"): PANES,
        ("pane", "split"): {},
    }
    herdr, _ = herdr_with(monkeypatch, replies)
    assert core(herdr)["error"] == "pane_split_failed"


def test_a_refused_agent_start_is_reported_instead_of_waited_out(monkeypatch):
    """A refused `agent start` is named at once -- and the waiter never runs.

    Herdr answers `agent_pane_busy` after 0.0 s when the freshly split pane
    has not reached its interactive shell prompt. The reply used to be
    discarded here, so the wait ran its full `ready_timeout_s` -- 45 s by
    default -- for an agent id that could never come, and then reported
    `no_agent_id`: neither the cause nor the moment.
    """
    replies = {
        ("workspace", "list"): BY_WORKTREE,
        ("agent", "list"): NO_AGENTS,
        ("pane", "list"): PANES,
        # What a refusal looks like by the time it reaches this caller: the
        # exit code and stderr are gone, an empty dict is all that is left.
        ("agent", "start"): {},
    }
    herdr, _ = herdr_with(monkeypatch, {**replies, ("pane", "split"): SPLIT})

    def waiter(*_a, **_kw):
        raise AssertionError("the waiter must not run after a refused agent start")

    assert core(herdr, waiter=waiter) == {
        "ok": False,
        "error": "agent_start_failed",
        "workspace": "w3",
        "pane": "w3:p9",
    }


def test_a_hung_start_is_reported_as_opencode_stuck_with_pane_and_workspace(
    monkeypatch,
):
    """The new error, and the two ids the operator needs to find the tile.

    `agent_start_failed` stays reserved for a real refusal; a start that
    hung through both attempts gets its own name, because it is its own
    repair -- the tile is alive and holds a process that never painted.
    """
    replies = {
        ("workspace", "list"): BY_WORKTREE,
        ("agent", "list"): NO_AGENTS,
        ("pane", "list"): PANES,
        ("pane", "split"): SPLIT,
    }
    herdr, _ = herdr_with(monkeypatch, replies)
    monkeypatch.setattr(
        workspace,
        "start_agent",
        lambda *a, **kw: {"ok": False, "error": "opencode_stuck"},
    )

    def waiter(*_a, **_kw):
        raise AssertionError("the waiter must not run after a stuck start")

    assert core(herdr, waiter=waiter) == {
        "ok": False,
        "error": "opencode_stuck",
        "workspace": "w3",
        "pane": "w3:p9",
    }


def test_the_orchestrator_start_goes_through_the_shared_helper(monkeypatch):
    """One mechanism, not two -- and the retry gets the configured budget."""
    replies = {
        ("workspace", "list"): BY_WORKTREE,
        ("agent", "list"): NO_AGENTS,
        ("pane", "list"): PANES,
        ("pane", "split"): SPLIT,
    }
    herdr, _ = herdr_with(monkeypatch, replies)
    seen: dict[str, object] = {}
    real = workspace.start_agent

    def spy(*a, **kw):
        seen.update(kw)
        return real(*a, **kw)

    monkeypatch.setattr(workspace, "start_agent", spy)
    core(herdr, ready_timeout_s=45.0)
    assert seen["first_timeout_ms"] == FIRST_START_TIMEOUT_MS
    assert seen["retry_timeout_ms"] == 45_000


def test_a_small_budget_shrinks_the_first_attempt_with_it(monkeypatch):
    """The keystroke grants 6 s -- the first attempt must not take 12.

    `handle_bootstrap` runs inside Herdr's handler process and caps the
    budget at KEYSTROKE_READY_TIMEOUT_S for a measured reason. A flat
    FIRST_START_TIMEOUT_MS would have made the keystroke block for twice
    that cap before anything else even started.
    """
    replies = {
        ("workspace", "list"): BY_WORKTREE,
        ("agent", "list"): NO_AGENTS,
        ("pane", "list"): PANES,
        ("pane", "split"): SPLIT,
    }
    herdr, _ = herdr_with(monkeypatch, replies)
    seen: dict[str, object] = {}
    real = workspace.start_agent

    def spy(*a, **kw):
        seen.update(kw)
        return real(*a, **kw)

    monkeypatch.setattr(workspace, "start_agent", spy)
    core(herdr, ready_timeout_s=6.0, retry_on_hang=False)
    assert seen["first_timeout_ms"] == 6_000
    assert seen["retry_timeout_ms"] == 0, "no second attempt for the keystroke"


def test_a_timeout_without_an_agent_id_is_not_ok(monkeypatch):
    replies = {
        ("workspace", "list"): BY_WORKTREE,
        ("agent", "list"): NO_AGENTS,
        ("pane", "list"): PANES,
        ("pane", "split"): SPLIT,
    }
    herdr, _ = herdr_with(monkeypatch, replies)
    answer = core(herdr, waiter=lambda *a, **k: None)
    assert answer["ok"] is False and answer["error"] == "no_agent_id"
    assert answer["pane"] == "w3:p9", "the pane exists and the operator needs it"


def test_the_success_path_carries_all_four_names(monkeypatch):
    replies = {
        ("workspace", "list"): BY_WORKTREE,
        ("agent", "list"): NO_AGENTS,
        ("pane", "list"): PANES,
        ("pane", "split"): SPLIT,
    }
    herdr, proc = herdr_with(monkeypatch, replies)
    assert core(herdr) == {
        "ok": True,
        "workspace": "w3",
        "pane": "w3:p9",
        "agent": "orch",
        "agent_id": "mcp-42",
    }
    assert proc.called_with("agent", "start", "orch", "--kind", "opencode")
    assert proc.called_with("--", "--agent", "orchestrator")


def test_an_empty_model_means_no_model_flag_at_all(monkeypatch):
    replies = {
        ("workspace", "list"): BY_WORKTREE,
        ("agent", "list"): NO_AGENTS,
        ("pane", "list"): PANES,
        ("pane", "split"): SPLIT,
    }
    herdr, proc = herdr_with(monkeypatch, replies)
    core(herdr)
    assert not proc.called_with("agent", "start", "--model"), proc.flat()
    core(herdr, model="sonnet")
    assert proc.called_with("--", "--model", "sonnet", "--agent", "orchestrator")


# -- the agent name opencode has to be able to resolve ------------------

#: The one suffix all three guard messages carry.
INIT_HINT = "run `lean-herdr workspace init` first"

#: A COMPLETE set of replies -- every guard test below hands them over, so
#: a green answer would be available. What is asserted is that not one of
#: them is ever fetched: the whole point of the guard is that a doomed run
#: costs nothing, not that it fails a little later.
WOULD_WORK = {
    ("workspace", "list"): BY_WORKTREE,
    ("agent", "list"): NO_AGENTS,
    ("pane", "list"): PANES,
    ("pane", "split"): SPLIT,
}


def test_without_an_opencode_config_nothing_is_started_at_all(monkeypatch, tmp_path):
    """opencode cannot resolve `--agent orchestrator` here -- measured.

    It starts, prints "Agent not found: Orchestrator", never becomes an
    agent and never registers an MCP server. Before this guard the core
    then sat out the full `ready_timeout_s` -- 45 s measured -- for an
    agent id that could not arrive, and answered the misleading
    `no_agent_id`.
    """
    herdr, proc = herdr_with(monkeypatch, WOULD_WORK)
    answer = core(herdr, root=tmp_path)
    assert answer["ok"] is False
    assert answer["error"].startswith("no_agent_config: no opencode.jsonc in ")
    assert INIT_HINT in answer["error"]
    assert "not_initialised" not in answer["error"], (
        "that word belongs to the lean-herdr config, not to opencode's"
    )
    assert proc.calls == [], proc.flat()


def test_an_unparseable_opencode_config_gets_its_own_words(monkeypatch, tmp_path):
    """Broken is not absent, and an editor is not `init`."""
    (tmp_path / "opencode.jsonc").write_text('{"agent": {\n', encoding="utf-8")
    herdr, proc = herdr_with(monkeypatch, WOULD_WORK)
    error = core(herdr, root=tmp_path)["error"]
    assert error.startswith("no_agent_config: opencode.jsonc in ")
    assert "not valid JSONC" in error and INIT_HINT in error
    assert proc.calls == [], proc.flat()


def test_an_opencode_config_without_the_orchestrator_is_named_as_such(monkeypatch, tmp_path):
    """A file that parses is still no agent -- the third repair."""
    (tmp_path / "opencode.jsonc").write_text(
        '{"agent": {"builder": {"mode": "primary"}}}\n', encoding="utf-8"
    )
    herdr, proc = herdr_with(monkeypatch, WOULD_WORK)
    error = core(herdr, root=tmp_path)["error"]
    assert error.startswith("no_agent_config: ")
    assert "defines no agent.orchestrator" in error and INIT_HINT in error
    assert proc.calls == [], proc.flat()


def test_a_claude_orchestrator_needs_no_opencode_config(monkeypatch, tmp_path):
    """claude resolves no NAME: its role travels as a file (dispatch.agent_args)."""
    replies = {
        ("workspace", "list"): {"result": {"workspaces": []}},
        ("agent", "list"): NO_AGENTS,
        ("pane", "list"): {"result": {"panes": [{"pane_id": "w7:p1", "workspace_id": "w7"}]}},
        ("pane", "split"): SPLIT,
    }
    herdr, _ = herdr_with(monkeypatch, replies)
    answer = core(
        herdr,
        root=tmp_path,
        workspace_id="w7",
        kind="claude",
    )
    assert not (tmp_path / "opencode.jsonc").exists()
    assert answer["ok"] is True and answer["agent_id"] == "mcp-42"


def test_up_without_a_config_file_refuses(monkeypatch, tmp_path):
    """Not silently defaults: the config is the whole point of the call."""
    herdr, _ = herdr_with(monkeypatch, {})
    answer = workspace.workspace_up(root=tmp_path, herdr=herdr)
    assert answer["ok"] is False
    assert answer["error"].startswith("not_initialised:")


def _write_config(root: Path, text: str) -> None:
    (root / SETTINGS_PATH).parent.mkdir(parents=True, exist_ok=True)
    (root / SETTINGS_PATH).write_text(text, encoding="utf-8")


#: Every value deliberately different from the built-in default, so a
#: literal left anywhere on the path is a failure and not a coincidence.
CONFIG = """\
[workspace]
label = "orch-{repo}"

[roles.orchestrator]
profile = "power"
ready_timeout_s = 1.5
kind = "claude"
model = "opus"
"""


def test_up_takes_model_and_kind_from_the_orchestrator_role(monkeypatch, tmp_path):
    """Both arrive ONE BY ONE, out of the table the other two already come from.

    `settings` is down to the one thing that is about the WORKSPACE and
    not about the agent: its label. Splitting one pane's settings across
    two tables was the accident this holds shut.
    """
    _write_config(tmp_path, CONFIG)
    herdr, _ = herdr_with(monkeypatch, {})
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        workspace,
        "start_orchestrator",
        lambda **kwargs: (seen.update(kwargs), {"ok": True})[1],
    )
    assert workspace.workspace_up(root=tmp_path, herdr=herdr)["ok"] is True
    assert seen["model"] == "opus"
    assert seen["kind"] == "claude"
    assert seen["settings"] == WorkspaceSettings(label="orch-{repo}")


def test_up_carries_every_value_out_of_a_real_config_file(monkeypatch, tmp_path):
    """A file on disk -> `agent start`, with nothing hardcoded in between.

    `up` is the caller whose whole purpose is that file, and its two
    sections leave by different doors: `[workspace]` through the herdr
    calls, `[roles.orchestrator]` into the core's own arguments. Every
    other test in this file hands `start_orchestrator` its arguments
    directly and would stay green with the file never read at all.
    """
    _write_config(tmp_path, CONFIG)
    replies = {
        ("workspace", "list"): {"result": {"workspaces": []}},
        ("workspace", "create"): {"result": {"workspace": {"workspace_id": "w9"}}},
        ("agent", "list"): NO_AGENTS,
        ("pane", "list"): {"result": {"panes": [{"pane_id": "w9:p1", "workspace_id": "w9"}]}},
        ("pane", "split"): SPLIT,
    }
    herdr, proc = herdr_with(monkeypatch, replies)
    seen: dict[str, object] = {}
    core_fn = workspace.start_orchestrator

    def spy(**kwargs):
        seen.update(kwargs)
        # The real core, only with the waiter injected: `up` does not take
        # one, and the real one would sit out `ready_timeout_s`.
        return core_fn(**kwargs, waiter=lambda *a, **k: "mcp-42")

    monkeypatch.setattr(workspace, "start_orchestrator", spy)
    answer = workspace.workspace_up(root=tmp_path, herdr=herdr)

    assert answer["ok"] is True
    # [roles.orchestrator] -- read by the core, never by herdr.
    assert seen["profile"] == "power"
    assert seen["ready_timeout_s"] == 1.5
    # [workspace] -- one key left, and it is read on the way to herdr.
    assert proc.called_with("workspace", "create", "--label", f"orch-{tmp_path.name}")
    assert proc.called_with("--env", "LEAN_CTX_TOOL_PROFILE=power")
    assert proc.called_with("agent", "start", "orch", "--kind", "claude")
    assert proc.called_with("--", "--model", "opus", "--agent", "orchestrator")


#: The same config with the daily check switched on. `[models]` is the
#: fifth top-level table and the only one `up` reads for anything but the
#: pane it opens.
AUTO_ON = CONFIG + "\n[models]\nauto = true\n"


def test_up_with_auto_off_never_asks_the_catalogue(monkeypatch, tmp_path):
    """`auto = false` is the default, and then `up` fetches nothing at all.

    The import in `workspace_up` sits in the function body for exactly
    this reason: the common path returns before `catalog` -- and urllib,
    llm and dispatch behind it -- is ever loaded.
    """
    _write_config(tmp_path, CONFIG)
    herdr, _ = herdr_with(monkeypatch, {})
    monkeypatch.setattr(workspace, "start_orchestrator", lambda **kw: {"ok": True})

    def boom(**kwargs):
        raise AssertionError("auto is off; the catalogue must not be asked")

    monkeypatch.setattr("lean_herdr.catalog.check", boom)
    assert workspace.workspace_up(root=tmp_path, herdr=herdr) == {"ok": True}


def test_up_with_auto_on_carries_the_catalogue_answer(monkeypatch, tmp_path):
    """AFTER the start, never before, and merged in additively.

    `up` opens the working day: a price comparison must not stand between
    the operator and a running orchestrator.
    """
    _write_config(tmp_path, AUTO_ON)
    herdr, _ = herdr_with(monkeypatch, {})
    order: list[str] = []

    def started(**kwargs):
        order.append("start")
        return {"ok": True, "agent": "orch"}

    def checked(**kwargs):
        order.append("catalogue")
        return {"written": True, "model": "cheap/one", "reason": "written"}

    monkeypatch.setattr(workspace, "start_orchestrator", started)
    monkeypatch.setattr("lean_herdr.catalog.check", checked)
    answer = workspace.workspace_up(root=tmp_path, herdr=herdr)
    assert order == ["start", "catalogue"], "the start never waits on a price"
    assert answer["agent"] == "orch", "the start's own answer survives whole"
    assert answer["models"] == {
        "written": True,
        "model": "cheap/one",
        "reason": "written",
    }


@pytest.mark.parametrize(
    ("llm_block", "expected"),
    [
        ('\n[llm]\neffort = "high"\nprereview_effort = "medium"\n', ("high", "medium")),
        ("", (GENERATE_EFFORT, PREREVIEW_EFFORT)),
    ],
    ids=["both levels from [llm]", "both levels from llm.py"],
)
def test_up_hands_the_catalogue_both_effort_levels_in_order(
    monkeypatch, tmp_path, llm_block, expected
):
    """One `[llm].model` serves two jobs, so the check has to know both efforts.

    The generator's first, the judge's second. The two values in `[llm]` differ on
    purpose: two equal ones would let a swap in `workspace_up` pass. The fallback
    row takes the constants from llm.py, the way `up` does.
    """
    _write_config(tmp_path, AUTO_ON + llm_block)
    herdr, _ = herdr_with(monkeypatch, {})
    seen: dict[str, object] = {}

    def checked(**kwargs):
        seen.update(kwargs)
        return {"written": False, "model": None, "reason": "fresh"}

    monkeypatch.setattr(workspace, "start_orchestrator", lambda **kw: {"ok": True})
    monkeypatch.setattr("lean_herdr.catalog.check", checked)
    workspace.workspace_up(root=tmp_path, herdr=herdr)
    assert seen["efforts"] == expected


def test_a_catalogue_that_did_not_answer_is_not_a_failed_up(monkeypatch, tmp_path):
    """`ok` belongs to the start alone."""
    _write_config(tmp_path, AUTO_ON)
    herdr, _ = herdr_with(monkeypatch, {})
    monkeypatch.setattr(workspace, "start_orchestrator", lambda **kw: {"ok": True})
    monkeypatch.setattr(
        "lean_herdr.catalog.check",
        lambda **kw: {"written": False, "model": None, "reason": "no_catalog"},
    )
    answer = workspace.workspace_up(root=tmp_path, herdr=herdr)
    assert answer["ok"] is True
    assert answer["models"]["reason"] == "no_catalog"


def test_a_broken_models_block_is_read_even_with_auto_off(monkeypatch, tmp_path):
    """A typo in `[models]` must not stay silent -- that is the promise.

    `main()` turns this into `config_error:`; validating it only behind
    `auto` would leave the operator's typo undiscovered until the day
    they switch the feature on.
    """
    _write_config(tmp_path, CONFIG + '\n[models]\nmax_age_h = "soon"\n')
    herdr, _ = herdr_with(monkeypatch, {})
    monkeypatch.setattr(workspace, "start_orchestrator", lambda **kw: {"ok": True})
    with pytest.raises(SettingsError, match="max_age_h"):
        workspace.workspace_up(root=tmp_path, herdr=herdr)


def test_a_broken_overlay_does_not_cost_the_started_orchestrator(monkeypatch, tmp_path):
    """Read after the start, the overlay threw away a running orchestrator's names.

    `up` reads no overlay at all now: it carries `model` alone, and `up` needs the
    two efforts, which live in config.toml.
    """
    _write_config(tmp_path, AUTO_ON)
    (tmp_path / OVERLAY_PATH).write_text("[llm]\nmodel = 5\n", encoding="utf-8")
    herdr, _ = herdr_with(monkeypatch, {})
    monkeypatch.setattr(
        workspace,
        "start_orchestrator",
        lambda **kw: {"ok": True, "pane": "w3:p9", "agent_id": "mcp-42"},
    )
    monkeypatch.setattr(
        "lean_herdr.catalog.check",
        lambda **kw: {"written": True, "model": "cheap/one", "reason": "written"},
    )
    answer = workspace.workspace_up(root=tmp_path, herdr=herdr)
    assert answer["ok"] is True
    assert answer["pane"] == "w3:p9"
    assert answer["agent_id"] == "mcp-42"
    assert answer["models"]["reason"] == "written"


def test_a_typo_in_llm_stops_up_before_anything_starts(monkeypatch, tmp_path):
    """`[llm]` is validated like `[models]`: always, and ahead of the start."""
    _write_config(tmp_path, CONFIG + '\n[llm]\neffort = "enormous"\n')
    herdr, _ = herdr_with(monkeypatch, {})

    def boom(**kwargs):
        raise AssertionError("a broken [llm] must stop `up` before the start")

    monkeypatch.setattr(workspace, "start_orchestrator", boom)
    with pytest.raises(SettingsError, match="effort"):
        workspace.workspace_up(root=tmp_path, herdr=herdr)


def test_main_answers_a_bad_command_with_one_json_line(capsys):
    assert workspace.main(["nope"]) == 0
    answer = json.loads(capsys.readouterr().out)
    assert answer["ok"] is False and answer["error"].startswith("usage_error:")


def test_main_routes_init_and_hands_every_flag_on(monkeypatch, capsys):
    """`workspace_init` is imported ON THE CALL, so the seam is `initcmd`."""
    seen: list[dict[str, object]] = []
    monkeypatch.setattr(
        "lean_herdr.initcmd.workspace_init",
        lambda **kwargs: (seen.append(kwargs), {"ok": True, "written": []})[1],
    )
    assert workspace.main(["init"]) == 0
    assert workspace.main(["init", "--force"]) == 0
    assert (
        workspace.main(["init", "--update", "--test", "cargo test", "--lint", "cargo clippy"]) == 0
    )
    assert seen == [
        {"force": False, "update": False, "test": None, "lint": None},
        {"force": True, "update": False, "test": None, "lint": None},
        {"force": False, "update": True, "test": "cargo test", "lint": "cargo clippy"},
    ]
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 3 and all(json.loads(line)["ok"] for line in lines)


def test_up_refuses_force_rather_than_ignoring_it(capsys):
    """--force belongs to `init`. Swallowed, it would look like it did something."""
    assert workspace.main(["up", "--force"]) == 0
    answer = json.loads(capsys.readouterr().out)
    assert answer["ok"] is False
    assert answer["error"] == "usage_error: up does not take --force"


@pytest.mark.parametrize(
    "flags",
    [["--update"], ["--test", "cargo test"], ["--lint", "cargo clippy"]],
    ids=["update", "test", "lint"],
)
def test_up_refuses_every_init_flag(capsys, flags):
    """Swallowed, an init flag on `up` would look like it did something."""
    assert workspace.main(["up", *flags]) == 0
    answer = json.loads(capsys.readouterr().out)
    assert answer["ok"] is False
    assert answer["error"] == f"usage_error: up does not take {flags[0]}"


@pytest.mark.parametrize("command", ["check", "up"])
def test_an_empty_init_flag_is_still_a_given_one(monkeypatch, capsys, command):
    """`--test ""` was given. Read as falsy, it slipped past the refusal and ran the command."""

    def refuse(*_args, **_kwargs):
        raise AssertionError(f"{command} ran with an init flag")

    monkeypatch.setattr("lean_herdr.checkcmd.workspace_check", refuse)
    monkeypatch.setattr("lean_herdr.workspace.workspace_up", refuse)
    assert workspace.main([command, "--test", ""]) == 0
    answer = json.loads(capsys.readouterr().out)
    assert answer["error"] == f"usage_error: {command} does not take --test", answer


def test_main_routes_check_and_refuses_init_flags_there(monkeypatch, capsys):
    """`workspace_check` is imported ON THE CALL, so the seam is `checkcmd`."""
    monkeypatch.setattr("lean_herdr.checkcmd.workspace_check", lambda: {"ok": True, "errors": []})
    assert workspace.main(["check"]) == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True, "errors": []}
    assert workspace.main(["check", "--force"]) == 0
    answer = json.loads(capsys.readouterr().out)
    assert answer["error"] == "usage_error: check does not take --force"


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        pytest.param(
            SettingsError('orchestrator: direction="links"'),
            'config_error: orchestrator: direction="links"',
            id="a wrong config is named as one",
        ),
        pytest.param(
            BusError("not_a_git_repo: run `git init` first"),
            "not_a_git_repo: run `git init` first",
            id="a bus error travels verbatim",
        ),
        pytest.param(
            RuntimeError("something nobody foresaw"),
            "workspace_crashed: something nobody foresaw",
            id="and everything else still ends in one json line",
        ),
    ],
)
def test_main_gives_each_failure_its_own_rung(monkeypatch, capsys, raised, expected):
    """One JSON line, exit 0, and a prefix the orchestrator can tell apart."""
    monkeypatch.setattr(
        "lean_herdr.workspace.workspace_up",
        lambda: (_ for _ in ()).throw(raised),
    )
    assert workspace.main(["up"]) == 0
    answer = json.loads(capsys.readouterr().out)
    assert answer["ok"] is False and answer["error"] == expected


def test_main_names_a_git_that_cannot_answer(monkeypatch, capsys):
    """Through the real `canonical_root`, not a raised stand-in.

    The rung above has always worked for a BusError. A hung git never was one,
    and it ended as `workspace_crashed:`.
    """

    def hang(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=["git"], timeout=5.0)

    monkeypatch.setattr("lean_herdr.bus.subprocess.run", hang)
    assert workspace.main(["up"]) == 0
    answer = json.loads(capsys.readouterr().out)
    assert answer["ok"] is False
    assert answer["error"].startswith("git_unusable: "), answer["error"]
