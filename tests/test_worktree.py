import json
from pathlib import Path
from typing import Any

import pytest

from lean_herdr.herdr import Herdr
from lean_herdr.worktree import (
    WorktreeOpenFailed,
    WorktreeTarget,
    WorktrunkMissing,
    _open_workspace,
    anchor_pane,
    ensure_worktree,
    find_worktree,
    repo_root_from,
    wt_switch,
)
from tests.doubles import Completed, FakeProc, which_stub

EMPTY_LISTING = {
    "result": {
        "source": {"repo_root": "/repo", "source_workspace_id": "w1"},
        "worktrees": [],
    }
}
LISTING_WITH_WORKTREES = {
    "result": {
        "source": {"repo_root": "/repo", "source_workspace_id": "w1"},
        "worktrees": [
            {"branch": "feat/auth", "path": "/repo.feat-auth", "open_workspace_id": "w2"},
            {"branch": "feat/other", "path": "/repo.other", "open_workspace_id": "w3"},
        ],
    }
}

# Verbatim shape (fields the code never reads are elided with plausible
# values), measured live against real Herdr 0.8.2 / wt 0.76.0 on 2026-09-03
# via `herdr worktree open`. Neither `open_workspace_id` nor `workspace_id`
# exists at the top level of `result` — the shape every test below used to
# assume, and the real Herdr never produces.
MEASURED_WORKTREE_OPEN_REPLY: dict[str, Any] = {
    "id": "cli:worktree:open",
    "result": {
        "already_open": True,
        "type": "worktree_opened",
        "workspace": {
            "workspace_id": "w2",
            "label": "feat/probe",
            "active_tab_id": "w2:t1",
            "worktree": {"checkout_path": "/repo.feat-probe", "repo_root": "/repo"},
        },
        "worktree": {
            "branch": "feat/probe",
            "open_workspace_id": "w2",
            "path": "/repo.feat-probe",
        },
        "root_pane": {"pane_id": "w2:p1", "tab_id": "w2:t1", "workspace_id": "w2"},
        "tab": {"tab_id": "w2:t1", "workspace_id": "w2", "pane_count": 1},
    },
}


def real_worktree_open_reply(
    *, workspace_id: str, branch: str, path: str, already_open: bool = False
) -> dict[str, Any]:
    """A `worktree open` reply in the real (measured) shape, for any branch.

    `MEASURED_WORKTREE_OPEN_REPLY` fixes the fields to the live probe; this
    parametrises the same shape so the existing `feat/auth`-flavoured tests
    can carry the real reply too.
    """
    tab_id = f"{workspace_id}:t1"
    return {
        "id": "cli:worktree:open",
        "result": {
            "already_open": already_open,
            "type": "worktree_opened",
            "workspace": {
                "workspace_id": workspace_id,
                "label": branch,
                "active_tab_id": tab_id,
                "worktree": {"checkout_path": path, "repo_root": "/repo"},
            },
            "worktree": {
                "branch": branch,
                "open_workspace_id": workspace_id,
                "path": path,
            },
            "root_pane": {
                "pane_id": f"{workspace_id}:p1",
                "tab_id": tab_id,
                "workspace_id": workspace_id,
            },
            "tab": {"tab_id": tab_id, "workspace_id": workspace_id, "pane_count": 1},
        },
    }


@pytest.fixture
def h(monkeypatch) -> tuple[Herdr, FakeProc]:
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
    proc = FakeProc()
    return Herdr(runner=proc), proc


def test_repo_root_comes_from_the_reply_not_from_pwd():
    assert repo_root_from(LISTING_WITH_WORKTREES) == Path("/repo")
    assert repo_root_from({"result": {}}) is None


def test_find_worktree_matches_the_branch():
    found = find_worktree(LISTING_WITH_WORKTREES, "feat/auth")
    assert found is not None
    assert found["path"] == "/repo.feat-auth"
    assert find_worktree(LISTING_WITH_WORKTREES, "does-not-exist") is None


def test_existing_worktree_is_reused(h, monkeypatch):
    herdr, proc = h
    proc.replies = {("worktree", "list"): LISTING_WITH_WORKTREES}
    target = ensure_worktree("feat/auth", herdr=herdr, cwd="/repo")
    assert target == WorktreeTarget(path=Path("/repo.feat-auth"), workspace_id="w2")
    assert not proc.called_with("worktree", "open"), "must not create anything new"


def test_new_worktree_is_created_and_registered_at_repo_root(h, monkeypatch):
    herdr, proc = h
    proc.replies = {
        ("worktree", "list"): EMPTY_LISTING,
        ("worktree", "open"): real_worktree_open_reply(
            workspace_id="w2", branch="feat/auth", path="/repo.feat-auth"
        ),
    }
    monkeypatch.setattr("lean_herdr.worktree.shutil.which", lambda _b: "/usr/bin/wt")
    wt_calls: list[list[str]] = []

    def wt_runner(cmd, **kwargs):
        wt_calls.append(list(cmd))
        assert kwargs["cwd"] == "/repo", "wt switch runs at the repo root"
        return Completed(
            stdout=json.dumps(
                {"action": "created", "branch": "feat/auth", "path": "/repo.feat-auth"}
            )
        )

    target = ensure_worktree("feat/auth", herdr=herdr, cwd="/repo", runner=wt_runner)
    assert target.path == Path("/repo.feat-auth") and target.workspace_id == "w2"
    assert wt_calls[0][:5] == ["wt", "switch", "--create", "feat/auth", "--no-cd"]
    assert "--yes" in wt_calls[0] and "--format" in wt_calls[0]
    assert not any(c[1] == "list" and "--format=json" in c for c in wt_calls), (
        "wt list output is never parsed — two schemas (W2)"
    )
    assert proc.called_with("worktree", "open", "--cwd", "/repo"), (
        "--cwd is the repo root, never the worktree path (H8)"
    )


def test_without_wt_it_is_a_clear_error(h, monkeypatch):
    herdr, proc = h
    proc.replies = {("worktree", "list"): EMPTY_LISTING}
    monkeypatch.setattr("lean_herdr.worktree.shutil.which", lambda _b: None)
    with pytest.raises(WorktrunkMissing):
        ensure_worktree("feat/auth", herdr=herdr, cwd="/repo")


def test_wt_switch_without_a_path_in_the_reply_is_none(monkeypatch):
    monkeypatch.setattr("lean_herdr.worktree.shutil.which", lambda _b: "/usr/bin/wt")
    assert wt_switch("f", cwd="/repo", runner=lambda *a, **k: Completed(stdout="{}")) is None


def test_existing_worktree_without_workspace_is_reopened(h):
    """The tree can exist without an open workspace — it gets reopened then."""
    herdr, proc = h
    proc.replies = {
        ("worktree", "list"): {
            "result": {
                "source": {"repo_root": "/repo"},
                "worktrees": [
                    {"branch": "feat/auth", "path": "/repo.feat-auth",
                     "open_workspace_id": None}
                ],
            }
        },
        ("worktree", "open"): real_worktree_open_reply(
            workspace_id="w5", branch="feat/auth", path="/repo.feat-auth"
        ),
    }
    target = ensure_worktree("feat/auth", herdr=herdr, cwd="/repo")
    assert target == WorktreeTarget(path=Path("/repo.feat-auth"), workspace_id="w5")
    assert proc.called_with("worktree", "open", "--cwd", "/repo")


def test_failed_worktree_open_is_an_error_not_a_target(h, monkeypatch):
    """A target without a workspace would look like success and break teardown later."""
    herdr, proc = h
    proc.replies = {
        ("worktree", "list"): EMPTY_LISTING,
        ("worktree", "open"): {"error": {"code": "linked_worktree_source"}},
    }
    monkeypatch.setattr("lean_herdr.worktree.shutil.which", lambda _b: "/usr/bin/wt")
    runner = lambda *a, **k: Completed(
        stdout=json.dumps({"path": "/repo.feat-auth"})
    )
    with pytest.raises(WorktreeOpenFailed, match="linked_worktree_source"):
        ensure_worktree("feat/auth", herdr=herdr, cwd="/repo", runner=runner)


def test_anchor_pane_takes_a_pane_from_the_target_workspace(h):
    herdr, proc = h
    proc.replies = {
        ("pane", "list"): {"result": {"panes": [{"pane_id": "w2:p1", "workspace_id": "w2"}]}}
    }
    assert anchor_pane(herdr, "w2") == "w2:p1"
    assert proc.called_with("--workspace", "w2")


def test_anchor_pane_is_none_when_the_workspace_is_empty(h):
    herdr, proc = h
    proc.replies = {("pane", "list"): {"result": {"panes": []}}}
    assert anchor_pane(herdr, "w2") is None


def test_open_workspace_reads_the_measured_reply_shape(h):
    """`_open_workspace` against the verbatim reply real Herdr 0.8.2 sends.

    Every test above this one used to feed `{"result": {"open_workspace_id":
    "w2"}}` — a shape the real `worktree open` never produces. This is the
    shape it does; `_open_workspace` must find `w2` inside it.
    """
    herdr, proc = h
    proc.replies = {("worktree", "open"): MEASURED_WORKTREE_OPEN_REPLY}
    workspace_id = _open_workspace(
        herdr, repo_root=Path("/repo"), path=Path("/repo.feat-probe"), branch="feat/probe"
    )
    assert workspace_id == "w2"


def test_open_workspace_tab_only_response_names_what_it_got(h):
    """herdr-worktrunk may register a checkout as a tab, not a workspace.

    A reply carrying only a tab has no workspace of its own to report — the
    error must name that specifically, not the generic "no workspace_id",
    and must NOT treat the tab's `workspace_id` (the tab's *host* workspace)
    as if it were the worktree's own.
    """
    herdr, proc = h
    proc.replies = {
        ("worktree", "open"): {
            "result": {"tab": {"tab_id": "w9:t1", "workspace_id": "w9"}}
        }
    }
    with pytest.raises(WorktreeOpenFailed, match="tab 'w9:t1', no workspace"):
        _open_workspace(
            herdr, repo_root=Path("/repo"), path=Path("/repo.feat-x"), branch="feat/x"
        )

