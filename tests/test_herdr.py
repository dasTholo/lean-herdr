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


def test_pane_split_setzt_env_paare(fake):
    # Die echte Antwort von 0.8.2, verbatim in der Form: pane_id liegt UNTER pane.
    fake.replies = {("pane", "split"): {"result": {"pane": {"pane_id": "w2:p2"}}}}
    pane = h(fake).pane_split(
        "/repo", env={"LEAN_CTX_TOOL_PROFILE": "standard", "LEAN_CTX_ROLE": "builder"}
    )
    assert pane == "w2:p2"
    assert fake.called_with("--env", "LEAN_CTX_TOOL_PROFILE=standard")
    assert fake.called_with("--env", "LEAN_CTX_ROLE=builder")
    assert "--no-focus" in fake.calls[0]
    assert "--current" in fake.calls[0], "ohne Ziel-Pane bleibt es der eigene Workspace"


def test_pane_split_mit_ziel_pane_landet_im_fremden_workspace(fake):
    """Der Ziel-Pane bestimmt den Workspace des neuen Panes — nicht --current."""
    fake.replies = {("pane", "split"): {"result": {"pane": {"pane_id": "w2:p3"}}}}
    assert h(fake).pane_split("/repo.feat", pane="w2:p1") == "w2:p3"
    assert fake.called_with("--pane", "w2:p1")
    assert "--current" not in fake.calls[0]


def test_pane_list_filtert_auf_den_workspace(fake):
    fake.replies = {("pane", "list"): {"result": {"panes": [{"pane_id": "w2:p1"}]}}}
    assert h(fake).pane_list("w2") == [{"pane_id": "w2:p1"}]
    assert fake.called_with("--workspace", "w2")


def test_kein_aufruf_haengt_json_an(fake):
    """Regression: --json existiert in herdr nicht und bricht mit exit 2 ab."""
    herdr = h(fake)
    herdr.agent_list()
    herdr.pane_split("/repo")
    herdr.agent_prompt("builder", "los", wait=False)
    herdr.report_metadata("pane", "w1:p1", "ctx", "T1")
    assert all("--json" not in call for call in fake.calls)


def test_agent_start_reicht_native_argumente_nach_doppelstrich(fake):
    h(fake).agent_start(
        "builder",
        kind="claude",
        pane="w2:p2",
        agent_args=["--model", "sonnet", "--append-system-prompt-file", "roles/builder.md"],
    )
    call = fake.calls[0]
    nativ = call[call.index("--") + 1 :]
    assert nativ[:4] == ["--model", "sonnet", "--append-system-prompt-file", "roles/builder.md"]
    assert "--env" not in call, "agent start kennt kein --env (H9)"


def test_agent_prompt_ohne_wait_fuer_steuerbefehle(fake):
    h(fake).agent_prompt("builder", "/clear", wait=False)
    assert "--wait" not in fake.calls[0], "/clear loest keinen Lifecycle-Wechsel aus (H4)"


def test_agent_prompt_mit_wait_und_timeout(fake):
    h(fake).agent_prompt("builder", "Aufgabe liegt auf dem Bus.", timeout_ms=120000)
    assert fake.called_with("--wait")
    assert fake.called_with("--timeout", "120000")


def test_fehlendes_binary_liefert_leeres_dict(monkeypatch):
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(False))
    fake = FakeProc()
    assert Herdr(runner=fake).agent_list() == []
    assert fake.calls == [], "ohne Binary darf kein Aufruf passieren"


def test_timeout_wird_zu_leerem_dict(fake):
    fake.raises = subprocess.TimeoutExpired(cmd=["herdr"], timeout=1)
    assert h(fake).agent_list() == []


def test_kaputtes_json_wird_zu_leerem_dict(monkeypatch):
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))

    def runner(cmd, **kwargs):
        return Completed(stdout="<html>nope</html>")

    assert Herdr(runner=runner).agent_list() == []


def test_report_metadata_baut_das_token_paar(fake):
    fake.default = {"result": {"ok": True}}
    assert h(fake).report_metadata("workspace", "w2", "esc", "T1: reviewer lehnt ab")
    # ID positional, --source Pflicht — gemessen gegen 0.8.2.
    assert fake.called_with(
        "workspace", "report-metadata", "w2",
        "--source", "lean.herdr",
        "--token", "esc=T1: reviewer lehnt ab",
    )
    assert "--workspace" not in fake.calls[0]


def test_worktree_open_nimmt_den_repo_root_als_cwd(fake):
    h(fake).worktree_open(cwd="/repo", path="/repo.feat", label="feat/auth")
    assert fake.called_with("--cwd", "/repo", "--path", "/repo.feat", "--label", "feat/auth")
