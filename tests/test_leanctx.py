import json
import subprocess

import pytest

from lean_herdr.leanctx import CtxAntwort, LeanCtx, newest_handoff
from tests.doubles import Completed, FakeProc, which_stub

ROOT = "/home/tholo/Scripts/lean-herdr"

#: Verbatim gemessen gegen lean-ctx 3.10.1.
RESUME_TEXT = (
    "--- SESSION RESUME (post-compaction) ---\n"
    "Project: lean-herdr\n"
    "Task: Plan ueberarbeiten\n"
    "Key findings: registry.json traegt die Nachrichten unter scratchpad\n"
    "Stats: 104 calls, 1382898 tok saved\n"
    "---"
)
LEDGER_TEXT = (
    "Handoff Ledgers (9):\n"
    "  1. /home/tholo/.local/share/lean-ctx/handoffs/20260901-neu.json\n"
    "  2. /home/tholo/.local/share/lean-ctx/handoffs/20260621-alt.json"
)


@pytest.fixture
def fake(monkeypatch) -> FakeProc:
    monkeypatch.setattr("lean_herdr.leanctx.shutil.which", which_stub(True))
    return FakeProc()


def args_of(call: list[str]) -> dict:
    return json.loads(call[call.index("--json") + 1])


def test_jeder_call_traegt_den_kanonischen_root(fake):
    LeanCtx(ROOT, runner=fake).call("ctx_agent", {"action": "post"})
    assert fake.called_with("--project-root", ROOT)


def test_ein_worktree_pfad_kommt_nie_ins_flag(fake):
    """B12: --project-root auf einem Linked Worktree legt einen zweiten Bus an."""
    LeanCtx(ROOT, runner=fake).post(message="x")
    (call,) = fake.calls
    root = call[call.index("--project-root") + 1]
    assert root == ROOT
    assert ".feat" not in root and "/tmp/" not in root


def test_post_baut_die_gerichtete_nachricht(fake):
    LeanCtx(ROOT, runner=fake).post(
        message="Bitte Task T1 bearbeiten.",
        to_agent="mcp-2018183-70c877bf",
        task_id="T1",
        category="task",
        metadata={"branch": "feat/auth"},
    )
    assert args_of(fake.calls[0]) == {
        "action": "post",
        "message": "Bitte Task T1 bearbeiten.",
        "category": "task",
        "to_agent": "mcp-2018183-70c877bf",
        "task_id": "T1",
        "metadata": {"branch": "feat/auth"},
    }


def test_session_resume_ist_eine_leseaktion(fake):
    LeanCtx(ROOT, runner=fake).session_resume()
    assert args_of(fake.calls[0]) == {"action": "resume"}


def test_keine_schreibaktion_und_kein_bus_lesen():
    """B1: ctx_session-Schreiben persistiert nichts. B9: read braucht denselben Prozess."""
    verboten = {"task", "finding", "decision", "status", "read"}
    assert not verboten & {n for n in dir(LeanCtx) if not n.startswith("_")}


def test_handoff_show_ohne_pfad_gibt_es_nicht(fake):
    """Gemessen: `show` ohne path antwortet `error: -32602`."""
    LeanCtx(ROOT, runner=fake).handoff_show("/pfad/l.json")
    assert args_of(fake.calls[0]) == {"action": "show", "path": "/pfad/l.json"}


# -- Die drei Zustaende, die auseinandergehalten werden muessen ----------

def test_klartext_wird_nicht_als_json_gelesen(monkeypatch):
    """Der Kernbefund: `lean-ctx call` gibt Text aus, nie JSON."""
    monkeypatch.setattr("lean_herdr.leanctx.shutil.which", which_stub(True))
    antwort = LeanCtx(
        ROOT, runner=lambda *a, **k: Completed(stdout=RESUME_TEXT)
    ).session_resume()
    assert antwort.ok and "Project: lean-herdr" in antwort.text


def test_leere_ausgabe_ist_gueltig_und_kein_fehler(monkeypatch):
    """Frisches Projekt: ok, aber ohne Inhalt — nicht dasselbe wie ein Fehler."""
    monkeypatch.setattr("lean_herdr.leanctx.shutil.which", which_stub(True))
    antwort = LeanCtx(ROOT, runner=lambda *a, **k: Completed(stdout="")).session_resume()
    assert antwort.ok is True and antwort.text == "" and antwort.error is None


def test_fehlerzeile_wird_als_fehler_erkannt(monkeypatch):
    """lean-ctx meldet Fehler in der ersten Zeile, nicht ueber den Exit-Code."""
    monkeypatch.setattr("lean_herdr.leanctx.shutil.which", which_stub(True))
    antwort = LeanCtx(
        ROOT,
        runner=lambda *a, **k: Completed(
            stdout="error: -32602: path is required for action=show"
        ),
    ).handoff_show("")
    assert antwort.ok is False and "path is required" in (antwort.error or "")


def test_timeout_ist_von_leer_unterscheidbar(monkeypatch):
    monkeypatch.setattr("lean_herdr.leanctx.shutil.which", which_stub(True))
    fake = FakeProc(raises=subprocess.TimeoutExpired(cmd=["lean-ctx"], timeout=1))
    antwort = LeanCtx(ROOT, runner=fake).session_resume()
    assert antwort.ok is False and antwort.error == "timeout"


def test_ohne_binary_kein_aufruf(monkeypatch):
    monkeypatch.setattr("lean_herdr.leanctx.shutil.which", which_stub(False))
    fake = FakeProc()
    antwort = LeanCtx(ROOT, runner=fake).session_resume()
    assert antwort == CtxAntwort(False, error="unavailable")
    assert fake.calls == []


def test_eingebettetes_json_wird_gefunden_wenn_es_da_ist():
    """`ctx_handoff show`: zwei Kopfzeilen, dann JSON."""
    antwort = CtxAntwort(True, ' ctx_handoff show\n path: /x.json\n{"schema_version": 1}')
    assert antwort.json() == {"schema_version": 1}
    assert CtxAntwort(True, RESUME_TEXT).json() == {}


def test_newest_handoff_nimmt_den_ersten_eintrag():
    neuester = newest_handoff(LEDGER_TEXT)
    assert neuester is not None and neuester.endswith("20260901-neu.json")
    assert newest_handoff("Handoff Ledgers (0):") is None
    assert newest_handoff("") is None
