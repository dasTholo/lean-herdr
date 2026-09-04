"""`workspace up` and the core the keystroke shares with it."""

import json
from pathlib import Path

import pytest

from lean_herdr import workspace
from lean_herdr.bus import BusError
from lean_herdr.herdr import Herdr
from lean_herdr.settings import SETTINGS_PATH, SettingsError, WorkspaceSettings
from tests.doubles import FakeProc, agent_started, which_stub

ROOT = Path("/repo")

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
WITHOUT_WORKTREE = {
    "result": {"workspaces": [{"workspace_id": "w3", "worktree": None}]}
}

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
    assert proc.called_with("workspace", "create", "--cwd", "--label", "repo")
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
    core(herdr, settings=WorkspaceSettings(model="sonnet"))
    assert proc.called_with("--", "--model", "sonnet", "--agent", "orchestrator")


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
kind = "claude"
model = "opus"
label = "orch-{repo}"

[roles.orchestrator]
profile = "power"
ready_timeout_s = 1.5
"""


def test_up_carries_every_value_out_of_a_real_config_file(monkeypatch, tmp_path):
    """A file on disk -> `agent start`, with nothing hardcoded in between.

    `up` is the caller whose whole purpose is that file, and its two
    sections leave by different doors: `[workspace]` through the herdr
    calls, `[roles.orchestrator]` into the core's own arguments. Every
    other test in this file hands `start_orchestrator` its settings
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
    # [workspace] -- read on the way to herdr.
    assert proc.called_with("workspace", "create", "--label", f"orch-{tmp_path.name}")
    assert proc.called_with("--env", "LEAN_CTX_TOOL_PROFILE=power")
    assert proc.called_with("agent", "start", "orch", "--kind", "claude")
    assert proc.called_with("--", "--model", "opus", "--agent", "orchestrator")


def test_main_answers_a_bad_command_with_one_json_line(capsys):
    assert workspace.main(["nope"]) == 0
    answer = json.loads(capsys.readouterr().out)
    assert answer["ok"] is False and answer["error"].startswith("usage_error:")


def test_main_routes_init_and_hands_force_on(monkeypatch, capsys):
    """`workspace_init` is imported ON THE CALL, so the seam is `initcmd`."""
    seen: list[bool] = []
    monkeypatch.setattr(
        "lean_herdr.initcmd.workspace_init",
        lambda *, force: (seen.append(force), {"ok": True, "written": []})[1],
    )
    assert workspace.main(["init"]) == 0
    assert workspace.main(["init", "--force"]) == 0
    assert seen == [False, True]
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 2 and all(json.loads(line)["ok"] for line in lines)


def test_up_refuses_force_rather_than_ignoring_it(capsys):
    """--force belongs to `init`. Swallowed, it would look like it did something."""
    assert workspace.main(["up", "--force"]) == 0
    answer = json.loads(capsys.readouterr().out)
    assert answer["ok"] is False
    assert answer["error"] == "usage_error: up does not take --force"


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
