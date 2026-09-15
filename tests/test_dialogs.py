"""claude's folder trust and a blocked pane: trust written only on request, a dialog named, never answered."""

import json
from pathlib import Path

import pytest

from lean_herdr import dialogs
from lean_herdr.dialogs import (
    CLAUDE_STATE_FILE,
    DIALOG_LINES,
    TRUST_KEY,
    blocked_dialog,
    claude_state_path,
    claude_trusts,
    trust_root,
)
from lean_herdr.herdr import Herdr
from tests.doubles import Completed, FakeProc, which_stub


def state_file(tmp_path: Path, projects: dict, **rest) -> Path:
    path = tmp_path / "config" / CLAUDE_STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"numStartups": 7, **rest, "projects": projects}), encoding="utf-8")
    return path


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def root(tmp_path) -> Path:
    path = tmp_path / "probe"
    path.mkdir()
    return path.resolve()


def test_the_state_file_follows_claude_config_dir(tmp_path):
    assert claude_state_path({"CLAUDE_CONFIG_DIR": str(tmp_path)}) == tmp_path / ".claude.json"
    assert claude_state_path({}) == Path.home() / ".claude.json"


def test_claude_trusts_the_root_its_state_accepts(root, tmp_path):
    path = state_file(tmp_path, {str(root): {TRUST_KEY: True}})
    assert claude_trusts(root, state=path) is True


@pytest.mark.parametrize(
    "projects",
    [{}, {"/elsewhere": {TRUST_KEY: True}}, {"ROOT": {TRUST_KEY: False}}, {"ROOT": {}}],
    ids=["no entry", "another path", "declined", "no key"],
)
def test_claude_does_not_trust_a_root_its_state_does_not_accept(root, tmp_path, projects):
    projects = {str(root) if key == "ROOT" else key: value for key, value in projects.items()}
    assert claude_trusts(root, state=state_file(tmp_path, projects)) is False


@pytest.mark.parametrize(
    "content", [None, "", "not json", "[]"], ids=["missing", "empty", "not json", "a list"]
)
def test_an_unreadable_state_is_no_verdict(root, tmp_path, content):
    path = tmp_path / CLAUDE_STATE_FILE
    if content is not None:
        path.write_text(content, encoding="utf-8")
    assert claude_trusts(root, state=path) is None


def test_trust_root_writes_one_key_and_nothing_else_moves(root, tmp_path):
    other = {"allowedTools": ["Bash(ls)"], TRUST_KEY: False}
    path = state_file(tmp_path, {"/elsewhere": other}, theme="dark")
    assert trust_root(root, state=path) == "written"
    data = read(path)
    assert data["projects"][str(root)] == {TRUST_KEY: True}
    assert data["projects"]["/elsewhere"] == other
    assert data["numStartups"] == 7 and data["theme"] == "dark"
    assert claude_trusts(root, state=path) is True


def test_trust_root_keeps_the_other_keys_of_the_roots_entry(root, tmp_path):
    path = state_file(tmp_path, {str(root): {"allowedTools": [], TRUST_KEY: False}})
    assert trust_root(root, state=path) == "written"
    assert read(path)["projects"][str(root)] == {"allowedTools": [], TRUST_KEY: True}


def test_a_state_without_a_projects_table_gets_one(root, tmp_path):
    path = tmp_path / CLAUDE_STATE_FILE
    path.write_text('{"numStartups": 1}', encoding="utf-8")
    assert trust_root(root, state=path) == "written"
    assert read(path) == {"numStartups": 1, "projects": {str(root): {TRUST_KEY: True}}}


def test_an_already_trusted_root_is_not_written_again(root, tmp_path):
    path = state_file(tmp_path, {str(root): {TRUST_KEY: True}})
    before = path.read_bytes()
    assert trust_root(root, state=path) == "already"
    assert path.read_bytes() == before


def test_a_missing_state_file_is_never_created(root, tmp_path):
    absent = tmp_path / CLAUDE_STATE_FILE
    assert trust_root(root, state=absent).startswith("failed: no claude state at ")
    assert not absent.exists()


@pytest.mark.parametrize("content", ["not json", "[]", '{"projects": []}'])
def test_an_unreadable_state_is_left_as_it_is(root, tmp_path, content):
    path = tmp_path / CLAUDE_STATE_FILE
    path.write_text(content, encoding="utf-8")
    assert trust_root(root, state=path).startswith("failed: ")
    assert path.read_text(encoding="utf-8") == content


def test_a_failed_write_leaves_the_file_and_no_temp_file_behind(root, tmp_path, monkeypatch):
    path = state_file(tmp_path, {})
    before = path.read_bytes()

    def refuse(*_args, **_kwargs):
        raise OSError("read-only file system")

    monkeypatch.setattr(dialogs.os, "replace", refuse)
    assert trust_root(root, state=path) == "failed: read-only file system"
    assert path.read_bytes() == before
    assert sorted(p.name for p in path.parent.iterdir()) == [CLAUDE_STATE_FILE]


def test_the_written_file_keeps_its_mode(root, tmp_path):
    path = state_file(tmp_path, {})
    path.chmod(0o640)
    assert trust_root(root, state=path) == "written"
    assert path.stat().st_mode & 0o777 == 0o640


@pytest.fixture
def herdr(monkeypatch) -> tuple[Herdr, FakeProc]:
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
    proc = FakeProc()
    return Herdr(runner=proc), proc


def agents(*entries: dict) -> dict:
    return {"result": {"type": "agent_list", "agents": list(entries)}}


def test_a_blocked_pane_answers_with_its_last_screen_lines(herdr):
    h, proc = herdr
    proc.replies = {
        ("agent", "list"): agents(
            {"name": "builder-feat", "pane_id": "w2:p2", "agent_status": "blocked"}
        ),
        ("agent", "read"): "\n".join(f"line {n}" for n in range(30)) + "\n\n",
    }
    text = blocked_dialog(h, pane="w2:p2")
    assert text == "\n".join(f"line {n}" for n in range(30 - DIALOG_LINES, 30))
    assert proc.called_with("agent", "read", "w2:p2", "--source", "detection")


def test_a_worker_is_found_by_name_while_waiting(herdr):
    h, proc = herdr
    proc.replies = {
        ("agent", "list"): agents(
            {"name": "reviewer-feat", "pane_id": "w2:p3", "agent_status": "idle"},
            {"name": "builder-feat", "pane_id": "w2:p2", "agent_status": "blocked"},
        ),
        ("agent", "read"): "Allow this command?\n",
    }
    assert blocked_dialog(h, name="builder-feat") == "Allow this command?"
    assert proc.called_with("agent", "read", "w2:p2")


@pytest.mark.parametrize("status", ["idle", "working", "done", "unknown"])
def test_any_other_state_is_no_dialog_and_reads_no_screen(herdr, status):
    h, proc = herdr
    proc.replies = {
        ("agent", "list"): agents({"name": "b", "pane_id": "w2:p2", "agent_status": status})
    }
    assert blocked_dialog(h, pane="w2:p2") is None
    assert not proc.called_with("agent", "read")


def test_a_pane_herdr_does_not_list_is_no_dialog(herdr):
    h, proc = herdr
    proc.replies = {
        ("agent", "list"): agents({"name": "b", "pane_id": "w9:p9", "agent_status": "blocked"})
    }
    assert blocked_dialog(h, pane="w2:p2") is None


def test_a_blocked_pane_without_screen_text_is_still_blocked(herdr):
    h, proc = herdr
    proc.replies = {
        ("agent", "list"): agents({"name": "b", "pane_id": "w2:p2", "agent_status": "blocked"}),
        ("agent", "read"): Completed(returncode=1),
    }
    assert blocked_dialog(h, pane="w2:p2") == "(herdr returned no screen text)"


def test_nothing_in_here_sends_input_to_a_pane(herdr):
    h, proc = herdr
    proc.replies = {
        ("agent", "list"): agents({"name": "b", "pane_id": "w2:p2", "agent_status": "blocked"}),
        ("agent", "read"): "Do you trust the files in this folder?\n",
    }
    blocked_dialog(h, pane="w2:p2")
    for verb in (("send-keys",), ("send-text",), ("agent", "prompt"), ("pane", "run")):
        assert not proc.called_with(*verb), proc.flat()
