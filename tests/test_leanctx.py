import json
import subprocess

import pytest

from lean_herdr.leanctx import CtxResponse, LeanCtx, newest_handoff
from tests.doubles import Completed, FakeProc, which_stub

ROOT = "/home/tholo/Scripts/lean-herdr"

#: Measured verbatim against lean-ctx 3.10.1 (wording anglicised, shape kept).
RESUME_TEXT = (
    "--- SESSION RESUME (post-compaction) ---\n"
    "Project: lean-herdr\n"
    "Task: rework the plan\n"
    "Key findings: registry.json carries the messages under scratchpad\n"
    "Stats: 104 calls, 1382898 tok saved\n"
    "---"
)
LEDGER_TEXT = (
    "Handoff Ledgers (9):\n"
    "  1. /home/tholo/.local/share/lean-ctx/handoffs/20260901-new.json\n"
    "  2. /home/tholo/.local/share/lean-ctx/handoffs/20260621-old.json"
)


@pytest.fixture
def fake(monkeypatch) -> FakeProc:
    monkeypatch.setattr("lean_herdr.leanctx.shutil.which", which_stub(True))
    return FakeProc()


def args_of(call: list[str]) -> dict:
    return json.loads(call[call.index("--json") + 1])


def test_every_call_carries_the_canonical_root(fake):
    LeanCtx(ROOT, runner=fake).call("ctx_agent", {"action": "post"})
    assert fake.called_with("--project-root", ROOT)


def test_a_worktree_path_never_reaches_the_flag(fake):
    """B12: --project-root on a linked worktree opens a second bus."""
    LeanCtx(ROOT, runner=fake).post(message="x")
    (call,) = fake.calls
    root = call[call.index("--project-root") + 1]
    assert root == ROOT
    assert ".feat" not in root and "/tmp/" not in root


def test_post_builds_the_directed_message(fake):
    LeanCtx(ROOT, runner=fake).post(
        message="Please work on task T1.",
        to_agent="mcp-2018183-70c877bf",
        task_id="T1",
        category="task",
        metadata={"branch": "feat/auth"},
    )
    assert args_of(fake.calls[0]) == {
        "action": "post",
        "message": "Please work on task T1.",
        "category": "task",
        "to_agent": "mcp-2018183-70c877bf",
        "task_id": "T1",
        "metadata": {"branch": "feat/auth"},
    }


def test_session_resume_is_a_read_action(fake):
    LeanCtx(ROOT, runner=fake).session_resume()
    assert args_of(fake.calls[0]) == {"action": "resume"}


def test_no_write_action_and_no_bus_read():
    """B1: ctx_session writes persist nothing. B9: read needs the same process."""
    forbidden = {"task", "finding", "decision", "status", "read"}
    assert not forbidden & {n for n in dir(LeanCtx) if not n.startswith("_")}


def test_handoff_show_without_a_path_does_not_exist(fake):
    """Measured: `show` without path answers `error: -32602`."""
    LeanCtx(ROOT, runner=fake).handoff_show("/path/l.json")
    assert args_of(fake.calls[0]) == {"action": "show", "path": "/path/l.json"}


# -- The three states that must be kept apart ---------------------------

def test_plain_text_is_not_read_as_json(monkeypatch):
    """The core finding: `lean-ctx call` prints text, never JSON."""
    monkeypatch.setattr("lean_herdr.leanctx.shutil.which", which_stub(True))
    answer = LeanCtx(
        ROOT, runner=lambda *a, **k: Completed(stdout=RESUME_TEXT)
    ).session_resume()
    assert answer.ok and "Project: lean-herdr" in answer.text


def test_empty_output_is_valid_and_not_an_error(monkeypatch):
    """Fresh project: ok, but without content -- not the same as an error."""
    monkeypatch.setattr("lean_herdr.leanctx.shutil.which", which_stub(True))
    answer = LeanCtx(ROOT, runner=lambda *a, **k: Completed(stdout="")).session_resume()
    assert answer.ok is True and answer.text == "" and answer.error is None


def test_an_error_line_is_recognised_as_an_error(monkeypatch):
    """lean-ctx reports errors on the first line, not via the exit code."""
    monkeypatch.setattr("lean_herdr.leanctx.shutil.which", which_stub(True))
    answer = LeanCtx(
        ROOT,
        runner=lambda *a, **k: Completed(
            stdout="error: -32602: path is required for action=show"
        ),
    ).handoff_show("")
    assert answer.ok is False and "path is required" in (answer.error or "")


def test_a_timeout_is_distinguishable_from_empty(monkeypatch):
    monkeypatch.setattr("lean_herdr.leanctx.shutil.which", which_stub(True))
    fake = FakeProc(raises=subprocess.TimeoutExpired(cmd=["lean-ctx"], timeout=1))
    answer = LeanCtx(ROOT, runner=fake).session_resume()
    assert answer.ok is False and answer.error == "timeout"


def test_no_call_without_the_binary(monkeypatch):
    monkeypatch.setattr("lean_herdr.leanctx.shutil.which", which_stub(False))
    fake = FakeProc()
    answer = LeanCtx(ROOT, runner=fake).session_resume()
    assert answer == CtxResponse(False, error="unavailable")
    assert fake.calls == []


def test_embedded_json_is_found_when_it_is_there():
    """`ctx_handoff show`: two header lines, then JSON."""
    answer = CtxResponse(True, ' ctx_handoff show\n path: /x.json\n{"schema_version": 1}')
    assert answer.json() == {"schema_version": 1}
    assert CtxResponse(True, RESUME_TEXT).json() == {}


def test_newest_handoff_takes_the_first_entry():
    newest = newest_handoff(LEDGER_TEXT)
    assert newest is not None and newest.endswith("20260901-new.json")
    assert newest_handoff("Handoff Ledgers (0):") is None
    assert newest_handoff("") is None
