"""`init` in a stranger's project: writes, skips, warns -- never repairs."""

import subprocess

import pytest

from lean_herdr.initcmd import (
    LAYOUT,
    WARM_TIMEOUT_S,
    _check_allowlist,
    _check_approvals,
    _check_plugins,
    workspace_init,
)
from lean_herdr.settings import SETTINGS_PATH
from lean_herdr.workspace import OPENCODE_ORCHESTRATOR
from tests.doubles import Completed, FakeProc, which_stub


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, timeout=30)
    return tmp_path


def quiet(monkeypatch):
    """No foreign binary in reach -- the warnings are tested separately."""
    monkeypatch.setattr("shutil.which", which_stub(False))


def test_a_fresh_project_gets_every_file(monkeypatch, repo):
    quiet(monkeypatch)
    answer = workspace_init(root=repo)
    assert answer["ok"] is True
    assert answer["written"] == sorted(LAYOUT.values())
    assert answer["skipped"] == []
    for relative in LAYOUT.values():
        assert (repo / relative).is_file(), relative


def test_a_second_run_writes_nothing(monkeypatch, repo):
    quiet(monkeypatch)
    workspace_init(root=repo)
    answer = workspace_init(root=repo)
    assert answer["written"] == []
    assert answer["skipped"] == sorted(LAYOUT.values())


def test_a_dangling_symlink_is_not_written_through(monkeypatch, repo, tmp_path):
    """`exists()` follows the link, so a dead one looks like an absent file.

    A stranger's tree that carries `opencode.jsonc -> ../outside.json` would
    otherwise have `init` write the template to a path OUTSIDE the project it
    was pointed at -- past the one guard this command has.
    """
    quiet(monkeypatch)
    outside = tmp_path.parent / "outside.json"
    assert not outside.exists()
    (repo / "opencode.jsonc").symlink_to(outside)
    answer = workspace_init(root=repo)
    assert not outside.exists(), "init wrote past the project root"
    assert "opencode.jsonc" in answer["skipped"]


def test_force_replaces_the_link_instead_of_following_it(monkeypatch, repo, tmp_path):
    """--force is permission to overwrite HERE, not to write elsewhere."""
    quiet(monkeypatch)
    outside = tmp_path.parent / "outside.json"
    outside.write_text("not mine", encoding="utf-8")
    link = repo / "opencode.jsonc"
    link.symlink_to(outside)
    answer = workspace_init(root=repo, force=True)
    assert outside.read_text(encoding="utf-8") == "not mine"
    assert not link.is_symlink() and link.is_file()
    assert "opencode.jsonc" in answer["written"]


def test_a_symlinked_parent_directory_is_not_written_through(monkeypatch, repo, tmp_path):
    """The leaf guard sees a link AT the template's place, never one above it.

    `.claude -> ~/dotfiles/claude` is an ordinary dotfiles setup. `exists()`
    on `.claude/settings.json` resolves straight through it, and the write
    lands outside the project -- the same escape one level up.
    """
    quiet(monkeypatch)
    outside = tmp_path.parent / "outside-claude"
    outside.mkdir(exist_ok=True)
    (repo / ".claude").symlink_to(outside, target_is_directory=True)
    answer = workspace_init(root=repo)
    assert list(outside.iterdir()) == [], "init wrote past the project root"
    assert ".claude/settings.json" in answer["skipped"]


def test_force_does_not_write_through_a_symlinked_parent_either(monkeypatch, repo, tmp_path):
    """Two levels up, and with --force: still not a way out of the project.

    --force is permission to overwrite a FILE that is already there. A
    linked directory carries everything else the operator keeps behind it,
    so it is neither followed nor removed -- it is reported as skipped and
    the choice stays theirs.
    """
    quiet(monkeypatch)
    outside = tmp_path.parent / "outside-opencode"
    outside.mkdir(exist_ok=True)
    link = repo / ".opencode"
    link.symlink_to(outside, target_is_directory=True)
    answer = workspace_init(root=repo, force=True)
    assert list(outside.iterdir()) == [], "init wrote past the project root"
    assert ".opencode/plugins/lean-ctx-policy.js" in answer["skipped"]
    assert link.is_symlink(), "the operator's link is not init's to remove"


def test_a_layout_parent_that_is_a_file_keeps_the_report(monkeypatch, repo):
    """The docstring promises no exception. A half-built tree tests it.

    Without the guard the FileExistsError escapes mid-loop and takes the
    written/skipped list with it -- leaving nobody able to say which files
    already landed.
    """
    quiet(monkeypatch)
    (repo / ".claude").write_text("a file where a directory belongs", encoding="utf-8")
    answer = workspace_init(root=repo)
    assert answer["ok"] is False
    assert answer["error"].startswith("init_stopped: ")
    assert (repo / ".claude").is_file(), "the stranger's file must survive"
    assert "written" in answer and "skipped" in answer, "the report must survive"


def test_a_stranger_file_survives_without_force(monkeypatch, repo):
    """The most expensive mistake this tool could make."""
    quiet(monkeypatch)
    mine = repo / "opencode.jsonc"
    mine.write_text('{"agent": {"mine": {}}}', encoding="utf-8")
    answer = workspace_init(root=repo)
    assert "opencode.jsonc" in answer["skipped"]
    assert mine.read_text(encoding="utf-8") == '{"agent": {"mine": {}}}'


def test_force_overwrites_it(monkeypatch, repo):
    quiet(monkeypatch)
    mine = repo / "opencode.jsonc"
    mine.write_text("{}", encoding="utf-8")
    answer = workspace_init(root=repo, force=True)
    assert answer["skipped"] == []
    assert "lean-herdr report next" in mine.read_text(encoding="utf-8")


def test_without_a_git_repo_it_says_so(monkeypatch, tmp_path):
    quiet(monkeypatch)
    # canonical_root() is what fails, so drive it through the real path:
    # no `root=`, from a directory that is not a checkout.
    monkeypatch.chdir(tmp_path)
    answer = workspace_init()
    assert answer["ok"] is False
    assert answer["error"].startswith("not_a_git_repo:")
    assert not (tmp_path / "opencode.jsonc").exists(), "it wrote before checking"


def test_every_missing_precondition_becomes_one_line(monkeypatch, repo):
    monkeypatch.setattr("shutil.which", which_stub(True))
    replies = {
        ("allow", "--list"): "Mode: restricted -- 73 command(s) permitted",
        ("config", "approvals"): '{"state": "approval_required"}',
        ("plugin", "list"): "- lean.herdr enabled\n  warning: unknown event\n",
    }
    proc = FakeProc(replies=replies, default="")
    warnings = workspace_init(root=repo, runner=proc)["warnings"]
    assert any("lean-ctx allow lean-herdr" in w for w in warnings)
    assert any("not approved" in w for w in warnings)
    assert any("warning:" in w for w in warnings)


def test_a_healthy_machine_warns_about_nothing(monkeypatch, repo):
    monkeypatch.setattr("shutil.which", which_stub(True))
    replies = {
        ("allow", "--list"): "Extra (additive, via `lean-ctx allow`): lean-herdr",
        ("config", "approvals"): '{"state": "approved"}',
        ("plugin", "list"): "- lean.herdr (lean-herdr context) enabled\n",
    }
    assert workspace_init(root=repo, runner=FakeProc(replies=replies))["warnings"] == []


def test_the_allowlist_check_answers_a_line_only_when_the_name_is_missing(monkeypatch):
    monkeypatch.setattr("shutil.which", which_stub(True))
    granted = FakeProc(replies={("allow", "--list"): "Extra (additive): lean-herdr"})
    assert _check_allowlist(granted) is None
    silent = FakeProc(replies={("allow", "--list"): "Mode: restricted -- 73 command(s)"})
    line = _check_allowlist(silent)
    assert line is not None and "lean-ctx allow lean-herdr" in line


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param("not json at all", id="no brace at all"),
        pytest.param("warning: no hooks\n{oops", id="a brace, but no json"),
        pytest.param('{"other": 1}', id="json without the key"),
    ],
)
def test_an_unreadable_approvals_reply_is_reported_as_an_unknown_state(monkeypatch, tmp_path, reply):
    """Never a green verdict over a reply nobody could parse."""
    monkeypatch.setattr("shutil.which", which_stub(True))
    line = _check_approvals(tmp_path, FakeProc(replies={("config", "approvals"): reply}))
    assert line is not None and "state: None" in line


def test_the_approvals_check_parses_from_the_first_brace(monkeypatch, tmp_path):
    """`_read` concatenates stdout AND stderr, so `wt`'s warning comes first.

    Parsing from byte 0 would make an approved project read as unparseable
    the moment `wt` has anything to complain about.
    """
    monkeypatch.setattr("shutil.which", which_stub(True))
    noisy = FakeProc(
        replies={("config", "approvals"): 'warning: hooks changed\n{"state": "approved"}'}
    )
    assert _check_approvals(tmp_path, noisy) is None


def test_the_plugin_check_only_fires_on_a_warning_line(monkeypatch):
    monkeypatch.setattr("shutil.which", which_stub(True))
    clean = FakeProc(replies={("plugin", "list"): "- lean.herdr (context) enabled\n"})
    assert _check_plugins(clean) is None
    noisy = FakeProc(replies={("plugin", "list"): "- lean.herdr\n  warning: unknown event\n"})
    line = _check_plugins(noisy)
    assert line is not None and "warning:" in line


def test_a_machine_without_the_three_binaries_names_every_one_of_them(monkeypatch, repo):
    quiet(monkeypatch)
    proc = FakeProc(default="")
    warnings = workspace_init(root=repo, runner=proc)["warnings"]
    assert [w.split(" is not on PATH")[0] for w in warnings] == ["herdr", "wt", "lean-ctx"]
    assert proc.calls == [], "a binary that is not on PATH is never run"


@pytest.mark.parametrize(
    "boom",
    [
        pytest.param(OSError("cannot execute"), id="OSError"),
        pytest.param(subprocess.SubprocessError("gave up"), id="SubprocessError"),
    ],
)
def test_a_check_that_cannot_run_at_all_invents_no_verdict(monkeypatch, repo, boom):
    """A read-only check must not hold up the call -- nor guess an answer."""
    monkeypatch.setattr("shutil.which", which_stub(True))
    proc = FakeProc(raises=boom, default="")
    assert workspace_init(root=repo, runner=proc)["warnings"] == []


def test_init_never_runs_a_command_that_changes_anything(monkeypatch, repo):
    """Reported, not repaired -- the whole point of the checklist."""
    monkeypatch.setattr("shutil.which", which_stub(True))
    proc = FakeProc(replies={}, default="")
    workspace_init(root=repo, runner=proc)
    for forbidden in (("allow", "lean-herdr"), ("approvals", "add"), ("plugin", "link")):
        assert not proc.called_with(*forbidden), proc.flat()


def test_init_warms_the_project_once_and_says_so(monkeypatch, repo):
    """The first opencode bootstrap here would hang -- so `init` spends it.

    Measured 2026-09-04: a bootstrap that got far enough and was then
    aborted warms the project, and the next start takes 3.4 s instead of
    hanging. `init` is where that cost is visible and harmless.
    """
    monkeypatch.setattr("shutil.which", which_stub(True))
    proc = FakeProc(default="")
    answer = workspace_init(root=repo, runner=proc)
    assert answer["warmed"] is True
    warm = [c for c in proc.calls if c[0] == "opencode"]
    assert warm == [["opencode", "debug", "agent", OPENCODE_ORCHESTRATOR]]
    assert "--pure" not in warm[0], (
        "--pure skips external plugins -- exactly the step to be warmed "
        "(measured 3 of 3 still hanging afterwards)"
    )


def test_the_warm_up_budget_is_hard_and_the_abort_is_the_point(monkeypatch, repo):
    """It is aborted, and the abort counts as warmed -- not as a failure."""
    monkeypatch.setattr("shutil.which", which_stub(True))
    seen: dict[str, object] = {}

    def runner(cmd, **kwargs):
        if cmd[0] == "opencode":
            seen["timeout"] = kwargs["timeout"]
            seen["cwd"] = kwargs["cwd"]
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=WARM_TIMEOUT_S)
        return Completed(stdout="")

    assert workspace_init(root=repo, runner=runner)["warmed"] is True
    assert seen["timeout"] == WARM_TIMEOUT_S
    assert seen["cwd"] == str(repo), "the project is what gets warmed"


def test_without_opencode_on_path_nothing_is_warmed_and_nothing_is_said(
    monkeypatch, repo
):
    """Silent, like every other check that cannot run."""
    quiet(monkeypatch)
    proc = FakeProc(default="")
    answer = workspace_init(root=repo, runner=proc)
    assert answer["warmed"] is False
    assert not any(c[0] == "opencode" for c in proc.calls), proc.flat()


def test_a_claude_project_is_not_warmed(monkeypatch, repo):
    """The hang is opencode's; a claude workspace pays nothing for it.

    The config is placed BEFORE the run, and the run gets no `--force`:
    `_place` skips a file that is already there, so the `kind` written
    here is the one the warm-up decision reads. With `--force` the
    template would land on top of it and the test would measure the
    default instead of what it set.
    """
    monkeypatch.setattr("shutil.which", which_stub(True))
    (repo / SETTINGS_PATH).parent.mkdir(parents=True, exist_ok=True)
    (repo / SETTINGS_PATH).write_text(
        '[roles.orchestrator]\nkind = "claude"\n', encoding="utf-8"
    )
    proc = FakeProc(default="")
    answer = workspace_init(root=repo, runner=proc)
    assert answer["warmed"] is False
    assert not any(c[0] == "opencode" for c in proc.calls), proc.flat()


def test_a_leftover_workspace_kind_decides_nothing_here(monkeypatch, repo):
    """`kind` moved, and `init` asks the new home ALONE.

    The old spelling is refused where it is read -- by `workspace up`,
    through `workspace_settings`. `init` reads `[roles.orchestrator]`, so
    a line left behind under `[workspace]` does not quietly go on
    steering the warm-up: the role's built-in `opencode` does.
    """
    monkeypatch.setattr("shutil.which", which_stub(True))
    (repo / SETTINGS_PATH).parent.mkdir(parents=True, exist_ok=True)
    (repo / SETTINGS_PATH).write_text(
        '[workspace]\nkind = "claude"\n', encoding="utf-8"
    )
    proc = FakeProc(default="")
    assert workspace_init(root=repo, runner=proc)["warmed"] is True


@pytest.mark.parametrize(
    ("extra", "warned"),
    [
        pytest.param("", True, id="one model, and nobody said so"),
        pytest.param(
            "shares_builder_model = true\n", False, id="one model, and it is meant"
        ),
    ],
)
def test_init_warns_when_builder_and_reviewer_share_a_model(
    monkeypatch, repo, extra, warned
):
    """The reviewer earns its keep by having DIFFERENT blind spots.

    `settings.model_warnings` is the one producer of this line; `init`
    reads the config once and hands it to the checklist.
    """
    quiet(monkeypatch)
    (repo / SETTINGS_PATH).parent.mkdir(parents=True, exist_ok=True)
    (repo / SETTINGS_PATH).write_text(
        '[roles.builder]\nmodel = "sonnet"\n\n'
        '[roles.reviewer]\nmodel = "sonnet"\n' + extra,
        encoding="utf-8",
    )
    warnings = workspace_init(root=repo)["warnings"]
    assert any("different blind spots" in w for w in warnings) is warned


def test_a_malformed_config_skips_the_warm_up_and_says_why(monkeypatch, repo):
    """`read_settings` raising SettingsError must not fail `init` -- the
    files are already written, only the runtime is unknown, so the warm-up
    is skipped and the reason lands in `warnings`.

    The config is placed BEFORE the run, and the run gets no `--force`:
    `_place` skips it, so the broken file the warm-up decision reads is
    the stranger's, not the template's.
    """
    quiet(monkeypatch)
    (repo / SETTINGS_PATH).parent.mkdir(parents=True, exist_ok=True)
    (repo / SETTINGS_PATH).write_text("[workspace\nkind = opencode\n", encoding="utf-8")
    answer = workspace_init(root=repo)
    assert answer["ok"] is True
    assert answer["warmed"] is False
    assert any(w.startswith("no warm-up: ") for w in answer["warnings"])


def test_a_broken_worker_block_costs_the_warm_up_and_not_the_report(monkeypatch, repo):
    """`[roles.orchestrator]` alone is not the whole config `init` reads.

    `_warnings` hands `data` on to `settings.model_warnings`, which reads
    `[roles.builder]` and `[roles.reviewer]` -- tables
    `settings_for("orchestrator", ...)` never validates. Before the guard,
    a broken worker block raised out of `workspace_init` AFTER the files
    were written, and `main()` turned that into a bare `config_error:`:
    the written/skipped report was lost for a fault in a table `init`
    does not even act on.
    """
    quiet(monkeypatch)
    (repo / SETTINGS_PATH).parent.mkdir(parents=True, exist_ok=True)
    (repo / SETTINGS_PATH).write_text(
        '[roles.builder]\ndirection = "links"\n', encoding="utf-8"
    )
    answer = workspace_init(root=repo)
    assert answer["ok"] is True
    assert answer["written"] or answer["skipped"], "the report must survive"
    assert answer["warmed"] is False
    assert any("direction='links'" in w for w in answer["warnings"])


def test_a_warm_up_that_cannot_run_at_all_is_not_reported_as_success(monkeypatch, repo):
    """`_warm_opencode`'s own except branch: a spawn failure is not warmed,
    but `init` still finishes and reports it rather than crashing with it.
    """
    monkeypatch.setattr("shutil.which", which_stub(True))

    def runner(cmd, **kwargs):
        if cmd[0] == "opencode":
            raise OSError("cannot execute")
        return Completed(stdout="")

    answer = workspace_init(root=repo, runner=runner)
    assert answer["ok"] is True
    assert answer["warmed"] is False
