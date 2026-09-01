import json
from pathlib import Path

import pytest

from lean_herdr.herdr import Herdr
from lean_herdr.worktree import (
    WorktreeOpenFailed,
    WorktreeTarget,
    WorktrunkMissing,
    anchor_pane,
    ensure_worktree,
    find_worktree,
    repo_root_from,
    wt_switch,
)
from tests.doubles import Completed, FakeProc, which_stub

LISTE_LEER = {
    "result": {
        "source": {"repo_root": "/repo", "source_workspace_id": "w1"},
        "worktrees": [],
    }
}
LISTE_MIT = {
    "result": {
        "source": {"repo_root": "/repo", "source_workspace_id": "w1"},
        "worktrees": [
            {"branch": "feat/auth", "path": "/repo.feat-auth", "open_workspace_id": "w2"},
            {"branch": "feat/andere", "path": "/repo.andere", "open_workspace_id": "w3"},
        ],
    }
}


@pytest.fixture
def h(monkeypatch) -> tuple[Herdr, FakeProc]:
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
    proc = FakeProc()
    return Herdr(runner=proc), proc


def test_repo_root_kommt_aus_der_antwort_nicht_aus_pwd():
    assert repo_root_from(LISTE_MIT) == Path("/repo")
    assert repo_root_from({"result": {}}) is None


def test_find_worktree_trifft_den_branch():
    gefunden = find_worktree(LISTE_MIT, "feat/auth")
    assert gefunden is not None
    assert gefunden["path"] == "/repo.feat-auth"
    assert find_worktree(LISTE_MIT, "gibt-es-nicht") is None


def test_vorhandener_worktree_wird_wiederverwendet(h, monkeypatch):
    herdr, proc = h
    proc.replies = {("worktree", "list"): LISTE_MIT}
    ziel = ensure_worktree("feat/auth", herdr=herdr, cwd="/repo")
    assert ziel == WorktreeTarget(path=Path("/repo.feat-auth"), workspace_id="w2")
    assert not proc.called_with("worktree", "open"), "nichts neu anlegen"


def test_neuer_worktree_wird_erzeugt_und_am_repo_root_registriert(h, monkeypatch):
    herdr, proc = h
    proc.replies = {
        ("worktree", "list"): LISTE_LEER,
        ("worktree", "open"): {"result": {"open_workspace_id": "w2"}},
    }
    monkeypatch.setattr("lean_herdr.worktree.shutil.which", lambda _b: "/usr/bin/wt")
    wt_calls: list[list[str]] = []

    def wt_runner(cmd, **kwargs):
        wt_calls.append(list(cmd))
        assert kwargs["cwd"] == "/repo", "wt switch laeuft im Repo-Root"
        return Completed(
            stdout=json.dumps(
                {"action": "created", "branch": "feat/auth", "path": "/repo.feat-auth"}
            )
        )

    ziel = ensure_worktree("feat/auth", herdr=herdr, cwd="/repo", runner=wt_runner)
    assert ziel.path == Path("/repo.feat-auth") and ziel.workspace_id == "w2"
    assert wt_calls[0][:5] == ["wt", "switch", "--create", "feat/auth", "--no-cd"]
    assert "--yes" in wt_calls[0] and "--format" in wt_calls[0]
    assert not any(c[1] == "list" and "--format=json" in c for c in wt_calls), (
        "wt list wird nie geparst — zwei Schemata (W2)"
    )
    assert proc.called_with("worktree", "open", "--cwd", "/repo"), (
        "--cwd ist der Repo-Root, nie der Worktree-Pfad (H8)"
    )


def test_ohne_wt_ist_es_ein_klarer_fehler(h, monkeypatch):
    herdr, proc = h
    proc.replies = {("worktree", "list"): LISTE_LEER}
    monkeypatch.setattr("lean_herdr.worktree.shutil.which", lambda _b: None)
    with pytest.raises(WorktrunkMissing):
        ensure_worktree("feat/auth", herdr=herdr, cwd="/repo")


def test_wt_switch_ohne_pfad_in_der_antwort_ist_none(monkeypatch):
    monkeypatch.setattr("lean_herdr.worktree.shutil.which", lambda _b: "/usr/bin/wt")
    assert wt_switch("f", cwd="/repo", runner=lambda *a, **k: Completed(stdout="{}")) is None


def test_vorhandener_worktree_ohne_workspace_wird_nachgeoeffnet(h):
    """Der Baum kann ohne offenen Workspace dastehen — dann wird er geoeffnet."""
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
        ("worktree", "open"): {"result": {"open_workspace_id": "w5"}},
    }
    ziel = ensure_worktree("feat/auth", herdr=herdr, cwd="/repo")
    assert ziel == WorktreeTarget(path=Path("/repo.feat-auth"), workspace_id="w5")
    assert proc.called_with("worktree", "open", "--cwd", "/repo")


def test_gescheitertes_worktree_open_ist_ein_fehler_kein_ziel(h, monkeypatch):
    """Ein Ziel ohne Workspace saehe aus wie Erfolg und braeche spaeter den Abbau."""
    herdr, proc = h
    proc.replies = {
        ("worktree", "list"): LISTE_LEER,
        ("worktree", "open"): {"error": {"code": "linked_worktree_source"}},
    }
    monkeypatch.setattr("lean_herdr.worktree.shutil.which", lambda _b: "/usr/bin/wt")
    runner = lambda *a, **k: Completed(
        stdout=json.dumps({"path": "/repo.feat-auth"})
    )
    with pytest.raises(WorktreeOpenFailed, match="linked_worktree_source"):
        ensure_worktree("feat/auth", herdr=herdr, cwd="/repo", runner=runner)


def test_anchor_pane_nimmt_einen_pane_des_ziel_workspaces(h):
    herdr, proc = h
    proc.replies = {
        ("pane", "list"): {"result": {"panes": [{"pane_id": "w2:p1", "workspace_id": "w2"}]}}
    }
    assert anchor_pane(herdr, "w2") == "w2:p1"
    assert proc.called_with("--workspace", "w2")


def test_anchor_pane_ist_none_wenn_der_workspace_leer_ist(h):
    herdr, proc = h
    proc.replies = {("pane", "list"): {"result": {"panes": []}}}
    assert anchor_pane(herdr, "w2") is None
