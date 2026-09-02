import subprocess

import pytest

from lean_herdr.herdr import Herdr
from tests.doubles import Completed, FakeProc, which_stub


@pytest.fixture
def fake(monkeypatch) -> FakeProc:
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
    return FakeProc()


def h(fake: FakeProc) -> Herdr:
    return Herdr(runner=fake)


def test_pane_split_sets_env_pairs(fake):
    # The real response from 0.8.2, verbatim in form: pane_id sits UNDER pane.
    fake.replies = {("pane", "split"): {"result": {"pane": {"pane_id": "w2:p2"}}}}
    pane = h(fake).pane_split(
        "/repo", env={"LEAN_CTX_TOOL_PROFILE": "standard", "LEAN_CTX_ROLE": "builder"}
    )
    assert pane == "w2:p2"
    assert fake.called_with("--env", "LEAN_CTX_TOOL_PROFILE=standard")
    assert fake.called_with("--env", "LEAN_CTX_ROLE=builder")
    assert "--no-focus" in fake.calls[0]
    assert "--current" in fake.calls[0], "without a target pane it stays the caller's own workspace"


def test_pane_split_with_target_pane_lands_in_foreign_workspace(fake):
    """The target pane determines the workspace of the new pane — not --current."""
    fake.replies = {("pane", "split"): {"result": {"pane": {"pane_id": "w2:p3"}}}}
    assert h(fake).pane_split("/repo.feat", pane="w2:p1") == "w2:p3"
    assert fake.called_with("--pane", "w2:p1")
    assert "--current" not in fake.calls[0]


def test_ratio_appears_only_when_set(monkeypatch):
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
    fake = FakeProc()
    h = Herdr(runner=fake)
    h.pane_split("/repo")
    assert "--ratio" not in fake.calls[0]
    h.pane_split("/repo", ratio=0.25)
    assert fake.calls[1][fake.calls[1].index("--ratio") + 1] == "0.25"


def test_pane_list_filters_by_workspace(fake):
    fake.replies = {("pane", "list"): {"result": {"panes": [{"pane_id": "w2:p1"}]}}}
    assert h(fake).pane_list("w2") == [{"pane_id": "w2:p1"}]
    assert fake.called_with("--workspace", "w2")


def test_no_call_appends_json(fake):
    """Regression: --json doesn't exist in herdr and aborts with exit 2."""
    herdr = h(fake)
    herdr.agent_list()
    herdr.pane_split("/repo")
    herdr.agent_prompt("builder", "go", wait=False)
    herdr.report_metadata("pane", "w1:p1", "ctx", "T1")
    assert all("--json" not in call for call in fake.calls)


def test_agent_start_passes_native_arguments_after_double_dash(fake):
    h(fake).agent_start(
        "builder",
        kind="claude",
        pane="w2:p2",
        agent_args=["--model", "sonnet", "--append-system-prompt-file", "roles/builder.md"],
    )
    call = fake.calls[0]
    native = call[call.index("--") + 1 :]
    assert native[:4] == ["--model", "sonnet", "--append-system-prompt-file", "roles/builder.md"]
    assert "--env" not in call, "agent start doesn't know --env (H9)"


def test_agent_prompt_without_wait_for_control_commands(fake):
    h(fake).agent_prompt("builder", "/clear", wait=False)
    assert "--wait" not in fake.calls[0], "/clear doesn't trigger a lifecycle change (H4)"


def test_agent_prompt_with_wait_and_timeout(fake):
    h(fake).agent_prompt("builder", "Task is on the bus.", timeout_ms=120000)
    assert fake.called_with("--wait")
    assert fake.called_with("--timeout", "120000")


def test_missing_binary_returns_empty_dict(monkeypatch):
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(False))
    fake = FakeProc()
    assert Herdr(runner=fake).agent_list() == []
    assert fake.calls == [], "without a binary, no call may happen"


def test_timeout_becomes_empty_dict(fake):
    fake.raises = subprocess.TimeoutExpired(cmd=["herdr"], timeout=1)
    assert h(fake).agent_list() == []


def test_broken_json_becomes_empty_dict(monkeypatch):
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))

    def runner(cmd, **kwargs):
        return Completed(stdout="<html>nope</html>")

    assert Herdr(runner=runner).agent_list() == []


def test_report_metadata_builds_the_token_pair(fake):
    fake.default = {"result": {"ok": True}}
    assert h(fake).report_metadata("workspace", "w2", "esc", "T1: reviewer rejects")
    # ID positional, --source mandatory — measured against 0.8.2.
    assert fake.called_with(
        "workspace", "report-metadata", "w2",
        "--source", "lean.herdr",
        "--token", "esc=T1: reviewer rejects",
    )
    assert "--workspace" not in fake.calls[0]


def test_worktree_open_takes_the_repo_root_as_cwd(fake):
    h(fake).worktree_open(cwd="/repo", path="/repo.feat", label="feat/auth")
    assert fake.called_with("--cwd", "/repo", "--path", "/repo.feat", "--label", "feat/auth")
