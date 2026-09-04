"""`workspace up` and the core the keystroke shares with it."""

import json
from pathlib import Path

from lean_herdr import workspace
from lean_herdr.herdr import Herdr
from lean_herdr.settings import WorkspaceSettings
from tests.doubles import FakeProc, which_stub

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


def herdr_with(monkeypatch, replies, *, available=True):
    monkeypatch.setattr("shutil.which", which_stub(available))
    proc = FakeProc(replies=replies)
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


def test_main_answers_a_bad_command_with_one_json_line(capsys):
    assert workspace.main(["nope"]) == 0
    answer = json.loads(capsys.readouterr().out)
    assert answer["ok"] is False and answer["error"].startswith("usage_error:")
