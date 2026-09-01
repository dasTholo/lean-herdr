import json
from pathlib import Path

import pytest

from lean_herdr.dispatch import (
    DispatchRequest,
    agent_args,
    agent_name,
    dispatch,
    find_reply,
    main,
    profile_for,
)
from lean_herdr.herdr import Herdr
from lean_herdr.leanctx import LeanCtx
from tests.doubles import FakeProc, which_stub

ROOT = Path("/repo")
AGENT_ID = "mcp-2018183-70c877bf"


def req(**kwargs) -> DispatchRequest:
    basis = {
        "role": "builder",
        "kind": "claude",
        "model": "sonnet",
        "role_file": Path("roles/builder.md"),
        "task_id": "T1",
        "task": "Bau die Funktion foo.",
    }
    return DispatchRequest(**{**basis, **kwargs})  # ty: ignore[invalid-argument-type]


def registry(*nachrichten: dict) -> dict:
    return {"agents": [{"agent_id": AGENT_ID, "pid": 42}], "scratchpad": list(nachrichten)}


def antwort(category: str = "result", task_id: str = "T1", **rest) -> dict:
    return {
        "id": "m1", "from_agent": AGENT_ID, "to_agent": "orch", "task_id": task_id,
        "category": category, "message": "fertig, drei Tests gruen",
        "project_root": str(ROOT), "timestamp": "2026-09-01T10:00:00Z", **rest,
    }


@pytest.fixture
def welt(monkeypatch, tmp_path):
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
    monkeypatch.setattr("lean_herdr.leanctx.shutil.which", which_stub(True))
    h_proc, l_proc = FakeProc(), FakeProc()
    h_proc.replies = {("pane", "split"): {"result": {"pane": {"pane_id": "w1:p6"}}}}
    return h_proc, l_proc, tmp_path / "registry.json"


def lauf(welt, *, reg: dict, request=None, agent_id: str | None = AGENT_ID, **kwargs):
    h_proc, l_proc, pfad = welt
    pfad.write_text(json.dumps(reg), encoding="utf-8")
    return dispatch(
        request or req(),
        herdr=Herdr(runner=h_proc),
        leanctx=LeanCtx(ROOT, runner=l_proc),
        root=ROOT,
        registry_path=pfad,
        waiter=lambda *a, **kw: agent_id,
        **kwargs,
    )


def test_profil_folgt_der_rolle_und_laesst_sich_ueberschreiben():
    assert profile_for("orchestrator") == "minimal"
    assert profile_for("builder") == "standard"
    assert profile_for("reviewer") == "standard"
    assert profile_for("builder", "minimal") == "minimal"


def test_agentenname_ist_branch_UND_rolle():
    """Ein Reviewer-Dispatch darf nie den laufenden Builder desselben Branches treffen."""
    assert agent_name("builder") == "builder"
    assert agent_name("builder", "feat/auth") == "builder-feat-auth"
    assert agent_name("reviewer", "feat/auth") == "reviewer-feat-auth"
    assert agent_name("builder", "feat/auth") != agent_name("reviewer", "feat/auth")


def test_rollentext_geht_als_datei_nie_als_text():
    args = agent_args("claude", "sonnet", Path("roles/builder.md"))
    assert args == ["--model", "sonnet", "--append-system-prompt-file", "roles/builder.md"]
    assert not any("\n" in a for a in args), "mehrzeilige Argumente lehnt Herdr ab (H2)"


def test_erfolgreicher_durchlauf_legt_die_aufgabe_auf_den_bus(welt):
    h_proc, l_proc, _ = welt
    ergebnis = lauf(welt, reg=registry(antwort()))
    assert ergebnis["ok"] is True
    assert ergebnis["result"] == "fertig, drei Tests gruen"
    assert ergebnis["agent_id"] == AGENT_ID
    gepostet = json.loads(l_proc.calls[0][l_proc.calls[0].index("--json") + 1])
    assert gepostet["to_agent"] == AGENT_ID and gepostet["task_id"] == "T1"
    assert gepostet["message"] == "Bau die Funktion foo."
    assert h_proc.called_with("prompt", "--wait"), "der Prompt ist nur die Klingel"


def test_das_profil_wird_am_pane_gesetzt_nicht_am_agenten(welt):
    h_proc, _, _ = welt
    lauf(welt, reg=registry(antwort()))
    assert h_proc.called_with("--env", "LEAN_CTX_TOOL_PROFILE=standard")
    assert h_proc.called_with("--env", "LEAN_CTX_ROLE=builder")
    start = next(c for c in h_proc.calls if c[1:3] == ["agent", "start"])
    assert "--env" not in start, "agent start kennt kein --env (H9)"


def test_keine_antwort_ohne_fehler_ist_no_reply(welt):
    ergebnis = lauf(welt, reg=registry())
    assert ergebnis == {
        "ok": False, "task_id": "T1", "pane": "w1:p6",
        "agent_id": AGENT_ID, "error": "no_reply",
    }


def test_keine_antwort_mit_fehler_in_der_ablage_ist_agent_error(
    welt, tmp_path, monkeypatch
):
    """Der ganze Weg echt: agent list → session_id → JSONL-Datei → error.

    `herdr agent export` gibt es nicht; die Wahrheit liegt in der Ablage des
    Agenten. Deshalb faelscht der Test kein Exportkommando, sondern legt die
    Datei an, die Claude Code wirklich schreibt.
    """
    h_proc, _, _ = welt
    h_proc.replies = {
        ("pane", "split"): {"result": {"pane": {"pane_id": "w1:p6"}}},
        ("agent", "list"): {
            "result": {
                "agents": [
                    {
                        "name": "builder",
                        "pane_id": "w1:p6",
                        "agent_session": {"value": "sid1"},
                    }
                ]
            }
        },
    }
    monkeypatch.setenv("HOME", str(tmp_path))
    ablage = tmp_path / ".claude" / "projects" / str(ROOT.resolve()).replace("/", "-")
    ablage.mkdir(parents=True)
    (ablage / "sid1.jsonl").write_text(
        json.dumps({"role": "user", "content": "los"}) + "\n"
        + json.dumps(
            {
                "role": "assistant",
                "error": {
                    "name": "APIError",
                    "data": {"message": "User not found.", "statusCode": 401},
                },
            }
        ) + "\n",
        encoding="utf-8",
    )
    ergebnis = lauf(welt, reg=registry())
    assert ergebnis["ok"] is False
    assert ergebnis["error"] == "agent_error: APIError: User not found. (401)"


def test_gescheiterter_bus_post_ist_nicht_no_reply(welt):
    """Ohne Aufgabe auf dem Bus waere `no_reply` eine Luege ueber die Ursache."""
    _, l_proc, _ = welt
    # str → wortwoertlich auf stdout: genau die Fehlerform von lean-ctx.
    l_proc.replies = {("call", "ctx_agent"): "error: -32603: bus unavailable"}
    ergebnis = lauf(welt, reg=registry(antwort()))
    assert ergebnis["ok"] is False
    assert ergebnis["error"].startswith("post_failed:")


def test_fremde_antwort_zaehlt_nicht(welt):
    """Antwort mit falscher task_id oder falschem Absender ist keine Antwort."""
    fremd = registry(antwort(task_id="T2"), antwort(from_agent="mcp-999-aaa"))
    assert lauf(welt, reg=fremd)["error"] == "no_reply"


def test_reject_ist_eine_antwort_aber_kein_erfolgssignal(welt):
    ergebnis = lauf(welt, reg=registry(antwort("reject")))
    assert ergebnis["ok"] is True and ergebnis["category"] == "reject"


def test_blocked_ist_kein_erfolg(welt):
    assert lauf(welt, reg=registry(antwort("blocked")))["ok"] is False


def test_unlesbarer_bus_ist_nie_erfolg_durch_schweigen(welt, monkeypatch):
    h_proc, l_proc, pfad = welt
    ergebnis = dispatch(
        req(),
        herdr=Herdr(runner=h_proc),
        leanctx=LeanCtx(ROOT, runner=l_proc),
        root=ROOT,
        registry_path=pfad / "gibt-es-nicht",
        waiter=lambda *a, **kw: AGENT_ID,
    )
    assert ergebnis["error"] == "bus_unreadable"


def test_vorhandener_agent_wird_wiederverwendet_und_geleert(welt):
    h_proc, _, _ = welt
    h_proc.replies = {
        ("agent", "list"): {"result": {"agents": [{"name": "builder", "pane_id": "w1:p6"}]}},
    }
    ergebnis = lauf(welt, reg=registry(antwort()))
    assert ergebnis["pane"] == "w1:p6"
    assert not any(c[1:3] == ["pane", "split"] for c in h_proc.calls)
    clear = next(c for c in h_proc.calls if "/clear" in c)
    assert "--wait" not in clear, "/clear ohne --wait (H4)"


def test_ohne_agent_id_meldet_das_skript_fehler(welt):
    assert lauf(welt, reg=registry(), agent_id=None)["error"] == "no_agent_id"


def test_find_reply_nimmt_die_juengste(tmp_path):
    alt = antwort(); alt["timestamp"] = "2026-09-01T09:00:00Z"; alt["message"] = "alt"
    neu = antwort(); neu["timestamp"] = "2026-09-01T11:00:00Z"; neu["message"] = "neu"
    gefunden = find_reply(
        registry(alt, neu), project_root=ROOT, task_id="T1", from_agent=AGENT_ID
    )
    assert gefunden is not None and gefunden.message == "neu"


def test_main_schreibt_eine_json_zeile_und_endet_mit_0(capsys, monkeypatch):
    monkeypatch.setattr(
        "lean_herdr.dispatch.canonical_root",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("kein repo")),
    )
    code = main(
        ["builder", "--kind", "claude", "--model", "sonnet",
         "--role-file", "roles/builder.md", "--task-id", "T1", "--task", "x"]
    )
    assert code == 0, "der Orchestrator liest ok, nicht den Exit-Code"
    zeilen = capsys.readouterr().out.strip().splitlines()
    assert len(zeilen) == 1
    ergebnis = json.loads(zeilen[0])
    assert ergebnis["ok"] is False and ergebnis["error"].startswith("dispatch_crashed")


def test_worktree_dispatch_startet_den_pane_im_worktree(welt, monkeypatch):
    h_proc, _, _ = welt
    h_proc.replies = {
        ("pane", "split"): {"result": {"pane": {"pane_id": "w2:p2"}}},
        ("pane", "list"): {"result": {"panes": [{"pane_id": "w2:p1"}]}},
        ("worktree", "list"): {
            "result": {
                "source": {"repo_root": "/repo"},
                "worktrees": [
                    {"branch": "feat/auth", "path": "/repo.feat-auth",
                     "open_workspace_id": "w2"}
                ],
            }
        },
    }
    ergebnis = lauf(welt, reg=registry(antwort()), request=req(worktree="feat/auth"))
    assert ergebnis["ok"] is True
    assert h_proc.called_with("--cwd", "/repo.feat-auth"), "der Arbeiter lebt im Worktree"
    start = next(c for c in h_proc.calls if c[1:3] == ["agent", "start"])
    assert "builder-feat-auth" in start


def test_worktree_dispatch_teilt_einen_pane_des_worktree_workspaces(welt):
    """Sonst laege der Arbeiter im Orchestrator-Workspace und ueberlebte den Abbau."""
    h_proc, _, _ = welt
    h_proc.replies = {
        ("pane", "split"): {"result": {"pane": {"pane_id": "w2:p2"}}},
        ("pane", "list"): {"result": {"panes": [{"pane_id": "w2:p1"}]}},
        ("worktree", "list"): {
            "result": {
                "source": {"repo_root": "/repo"},
                "worktrees": [
                    {"branch": "feat/auth", "path": "/repo.feat-auth",
                     "open_workspace_id": "w2"}
                ],
            }
        },
    }
    lauf(welt, reg=registry(antwort()), request=req(worktree="feat/auth"))
    split = next(c for c in h_proc.calls if c[1:3] == ["pane", "split"])
    assert "--pane" in split and "w2:p1" in split
    assert "--current" not in split


def test_worktree_ohne_ankerpane_bricht_ab(welt):
    h_proc, _, _ = welt
    h_proc.replies = {
        ("pane", "list"): {"result": {"panes": []}},
        ("worktree", "list"): {
            "result": {
                "source": {"repo_root": "/repo"},
                "worktrees": [
                    {"branch": "feat/auth", "path": "/repo.feat-auth",
                     "open_workspace_id": "w2"}
                ],
            }
        },
    }
    ergebnis = lauf(welt, reg=registry(antwort()), request=req(worktree="feat/auth"))
    assert ergebnis["ok"] is False and ergebnis["error"] == "no_anchor_pane"


def test_fehlendes_worktrunk_meldet_worktrunk_missing(welt, monkeypatch):
    monkeypatch.setattr("lean_herdr.worktree.shutil.which", lambda _b: None)
    h_proc, _, _ = welt
    h_proc.replies = {
        ("worktree", "list"): {"result": {"source": {"repo_root": "/repo"}, "worktrees": []}},
    }
    ergebnis = lauf(welt, reg=registry(), request=req(worktree="feat/neu"))
    assert ergebnis["error"] == "worktrunk_missing"
