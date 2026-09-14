"""`init` in a stranger's project: writes, skips, warns -- never repairs."""

import json
import subprocess
import tomllib
from typing import Any

import pytest

from lean_herdr.checkcmd import TEMP_IGNORE
from lean_herdr.initcmd import WARM_TIMEOUT_S, workspace_init
from lean_herdr.settings import OVERLAY_PATH, SETTINGS_PATH
from lean_herdr.templating import DEFAULT_VALUES, LAYOUT, LOCK_PATH, digest
from lean_herdr.workspace import OPENCODE_ORCHESTRATOR
from tests.doubles import Completed, FakeProc, undecodable, which_stub


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, timeout=30)
    return tmp_path


#: A snapshot install that shadows nothing. `init` reports the install through
#: `checkcmd.install_report`, and this suite runs from the repo venv -- which is,
#: correctly, no snapshot. tests/test_checkcmd.py tests the real thing.
HEALTHY_INSTALL = {
    "tool": True,
    "editable": False,
    "package": "/snap/lean_herdr",
    "binary": "/snap/bin/lean-herdr",
    "plugin": None,
}


@pytest.fixture(autouse=True)
def snapshot_install(monkeypatch):
    monkeypatch.setattr(
        "lean_herdr.checkcmd.install_report",
        lambda **_kwargs: (dict(HEALTHY_INSTALL), []),
    )


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


def test_init_writes_the_templates_rendered_and_no_token(monkeypatch, repo):
    """A stranger's project gets commands, never `{{lean-herdr:...}}` braces."""
    quiet(monkeypatch)
    workspace_init(root=repo)
    for relative in LAYOUT.values():
        assert b"{{lean-herdr:" not in (repo / relative).read_bytes(), relative
    gate = tomllib.loads((repo / ".config" / "wt.toml").read_text(encoding="utf-8"))
    assert gate["pre-merge"] == DEFAULT_VALUES


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
    assert answer["templates"][".claude/settings.json"] == "blocked"
    assert any(w.startswith(".claude/settings.json is blocked: ") for w in answer["warnings"])


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


def test_a_symlinked_lock_directory_is_neither_read_nor_written(
    monkeypatch, repo, tmp_path_factory
):
    """`.lean-ctx -> ~/dotfiles/lean-ctx` carries the lock's folder along.

    Written through the link, the lock lands outside the project; read through
    it, a file nobody here owns would decide every template's state.
    """
    quiet(monkeypatch)
    outside = tmp_path_factory.mktemp("outside-lean-ctx")
    (repo / ".lean-ctx").symlink_to(outside, target_is_directory=True)
    answer = workspace_init(root=repo)
    assert answer["ok"] is True
    assert list(outside.iterdir()) == [], "init wrote past the project root"
    assert any(w.startswith(f"{LOCK_PATH} is blocked: ") for w in answer["warnings"]), answer[
        "warnings"
    ]


def test_a_symlinked_lock_file_stays_a_link_and_its_target_untouched(
    monkeypatch, repo, tmp_path_factory
):
    """`os.replace` onto a link swaps the link for a file -- the operator's link, gone."""
    quiet(monkeypatch)
    target = tmp_path_factory.mktemp("outside-lock") / "templates.lock.json"
    target.write_text('{"files": {}, "values": {}}\n', encoding="utf-8")
    before = target.read_bytes()
    link = repo / LOCK_PATH
    link.parent.mkdir(parents=True)
    link.symlink_to(target)
    answer = workspace_init(root=repo)
    assert answer["ok"] is True
    assert link.is_symlink(), "the operator's link is not init's to replace"
    assert target.read_bytes() == before
    assert any(w.startswith(f"{LOCK_PATH} is blocked: ") for w in answer["warnings"])


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


@pytest.mark.parametrize(
    "cause",
    [
        pytest.param(FileNotFoundError(2, "No such file or directory", "git"), id="git missing"),
        pytest.param(subprocess.TimeoutExpired(cmd=["git"], timeout=5.0), id="git hung"),
    ],
)
def test_a_git_that_cannot_answer_stops_init_without_asking_for_git_init(
    monkeypatch, tmp_path, cause
):
    """`not_a_git_repo: run git init` is the wrong repair for a missing binary."""
    quiet(monkeypatch)
    monkeypatch.chdir(tmp_path)

    def refuse(*_args, **_kwargs):
        raise cause

    monkeypatch.setattr("lean_herdr.bus.subprocess.run", refuse)
    answer = workspace_init()
    assert answer["ok"] is False
    assert answer["error"].startswith("init_stopped: git_unusable: "), answer["error"]
    assert not (tmp_path / "opencode.jsonc").exists(), "it wrote before checking"


def test_every_missing_precondition_becomes_one_line(monkeypatch, repo):
    monkeypatch.setattr("shutil.which", which_stub(True))
    replies: dict[tuple[str, ...], Any] = {
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
    replies: dict[tuple[str, ...], Any] = {
        ("allow", "--list"): "Extra (additive, via `lean-ctx allow`): lean-herdr",
        ("config", "approvals"): '{"state": "approved"}',
        ("plugin", "list"): (
            "- lean.herdr (lean-herdr context) enabled [local:/snap/lean_herdr/plugin]\n"
        ),
        ("config", "show"): (
            '{"user": {"config": {"commit": {"generation": '
            '{"command": "lean-herdr llm generate"}}}}}'
        ),
    }
    assert workspace_init(root=repo, runner=FakeProc(replies=replies))["warnings"] == []


def test_an_ignored_overlay_alone_still_warns_about_the_temp_files(monkeypatch, repo):
    """One verdict per path, and the temp one even with `auto` off.

    A single `check-ignore` over both paths answers as soon as ONE is covered --
    and a rule for the overlay alone, this repository's state, would pass for both.
    """
    monkeypatch.setattr("shutil.which", which_stub(True))
    only_the_overlay = FakeProc(
        replies={
            ("check-ignore", "-v", str(OVERLAY_PATH)): (
                f".gitignore:22:{OVERLAY_PATH}\t{OVERLAY_PATH}"
            )
        },
        default=Completed(returncode=1),
    )
    warnings = workspace_init(root=repo, runner=only_the_overlay)["warnings"]
    assert any(TEMP_IGNORE in w for w in warnings), warnings


def test_the_gitignore_warning_only_appears_when_auto_is_on(monkeypatch, repo):
    """Guarded by the config, unlike its three neighbours.

    Without `[models].auto` no overlay is ever written, and a rule for a
    file that cannot exist would be noise in every project that never
    switched the feature on.

    The config is written BEFORE the run and the run gets no `--force`,
    so `_place` skips it and the config `machine_report` is handed is this one.
    """
    monkeypatch.setattr("shutil.which", which_stub(True))
    (repo / SETTINGS_PATH).parent.mkdir(parents=True, exist_ok=True)
    proc = FakeProc(default=Completed(returncode=1))

    (repo / SETTINGS_PATH).write_text("[models]\nauto = false\n", encoding="utf-8")
    off = workspace_init(root=repo, runner=proc)["warnings"]
    assert not any(str(OVERLAY_PATH) in w for w in off)

    (repo / SETTINGS_PATH).write_text("[models]\nauto = true\n", encoding="utf-8")
    on = workspace_init(root=repo, runner=proc)["warnings"]
    assert any("does not ignore" in w and str(OVERLAY_PATH) in w for w in on)
    assert not (repo / ".gitignore").exists(), "init reports, it never repairs"


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


def test_a_runner_that_decodes_strictly_keeps_the_report(monkeypatch, repo):
    """An answer no codec takes arrives AFTER every file landed -- and took the report along.

    opencode stays off the PATH: the warm-up is not what this test is about.
    """
    monkeypatch.setattr("shutil.which", lambda binary: None if binary == "opencode" else "/x")
    answer = workspace_init(root=repo, runner=undecodable)
    assert answer["ok"] is True
    assert answer["written"] == sorted(LAYOUT.values())
    assert answer["skipped"] == []
    assert answer["templates"] == {relative: "current" for relative in LAYOUT.values()}


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


def test_without_opencode_on_path_nothing_is_warmed_and_nothing_is_said(monkeypatch, repo):
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
    (repo / SETTINGS_PATH).write_text('[roles.orchestrator]\nkind = "claude"\n', encoding="utf-8")
    proc = FakeProc(default="")
    answer = workspace_init(root=repo, runner=proc)
    assert answer["warmed"] is False
    assert not any(c[0] == "opencode" for c in proc.calls), proc.flat()


def test_a_leftover_workspace_kind_is_named_here_not_left_for_up(monkeypatch, repo):
    """`kind` moved, and `init` is the run that says so.

    `init` steers its warm-up off `[roles.orchestrator]` alone, so a line
    left behind under `[workspace]` decides nothing here. But staying
    quiet about it would leave the operator to discover the dead key on
    the next `workspace up`, as a `config_error:` -- from the one command
    whose job is to report what is wrong with the project. So the moved
    key is read here too, and it lands in `warnings` with its new home in
    the text.
    """
    monkeypatch.setattr("shutil.which", which_stub(True))
    (repo / SETTINGS_PATH).parent.mkdir(parents=True, exist_ok=True)
    (repo / SETTINGS_PATH).write_text('[workspace]\nkind = "claude"\n', encoding="utf-8")
    answer = workspace_init(root=repo, runner=FakeProc(default=""))
    assert answer["ok"] is True, "the written/skipped report must survive"
    assert answer["warmed"] is False
    assert any(
        "workspace.kind has moved to [roles.orchestrator].kind" in w for w in answer["warnings"]
    )


@pytest.mark.parametrize(
    ("extra", "warned"),
    [
        pytest.param("", True, id="one model, and nobody said so"),
        pytest.param("shares_reviewed_model = true\n", False, id="one model, and it is meant"),
    ],
)
def test_init_warns_when_builder_and_reviewer_share_a_model(monkeypatch, repo, extra, warned):
    """The reviewer earns its keep by having DIFFERENT blind spots.

    `settings.model_warnings` is the one producer of this line; `init`
    reads the config once and hands it to the checklist.
    """
    quiet(monkeypatch)
    (repo / SETTINGS_PATH).parent.mkdir(parents=True, exist_ok=True)
    (repo / SETTINGS_PATH).write_text(
        '[roles.builder]\nmodel = "sonnet"\n\n[roles.reviewer]\nmodel = "sonnet"\n' + extra,
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


@pytest.mark.parametrize(
    "toml,expected",
    [
        pytest.param('[roles.builder]\ndirection = "links"\n', "direction='links'", id="builder"),
        pytest.param('[roles.reviewer]\ndirection = "links"\n', "direction='links'", id="reviewer"),
        pytest.param(
            '[routing]\nrefactor = "refactorer"\n\n[roles.refactorer]\ndirection = "links"\n',
            "direction='links'",
            id="a routed role",
        ),
        pytest.param(
            '[routing]\nimplement = "coder"\nreview = "judge"\n\n[roles.builder]\nbogus = 1\n',
            "builder: unknown keys ['bogus']",
            id="builder routed elsewhere",
        ),
    ],
)
def test_a_broken_worker_block_costs_the_warm_up_and_not_the_report(
    monkeypatch, repo, toml, expected
):
    """`[roles.orchestrator]` alone is not the whole config `init` reads.

    `workspace_init` validates every worker role's table -- `[roles.builder]`,
    `[roles.reviewer]`, and every role `[routing]` points at -- ALWAYS, even when
    `[routing]` sends `implement` or `review` to another role entirely -- tables
    `settings_for("orchestrator", ...)` never touches and `model_warnings` can
    return before it ever reaches. Before the guard, a broken worker block
    raised out of `workspace_init` AFTER the files were written, and `main()`
    turned that into a bare `config_error:`: the written/skipped report was
    lost for a fault in a table `init` does not even act on.
    """
    quiet(monkeypatch)
    (repo / SETTINGS_PATH).parent.mkdir(parents=True, exist_ok=True)
    (repo / SETTINGS_PATH).write_text(toml, encoding="utf-8")
    answer = workspace_init(root=repo)
    assert answer["ok"] is True
    assert answer["written"] or answer["skipped"], "the report must survive"
    assert answer["warmed"] is False
    assert any(expected in w for w in answer["warnings"])


def test_a_broken_models_block_costs_the_warm_up_and_not_the_report(monkeypatch, repo):
    """`[models]` is the table `machine_report` acts on, and nobody validated it first.

    `auto = 1` passes `settings_for` and `model_warnings` untouched and used to
    raise out of `machine_report` -- after the files were written, so `main()` answered
    with a bare `config_error:` and the written/skipped report was gone.
    """
    quiet(monkeypatch)
    (repo / SETTINGS_PATH).parent.mkdir(parents=True, exist_ok=True)
    (repo / SETTINGS_PATH).write_text("[models]\nauto = 1\n", encoding="utf-8")
    answer = workspace_init(root=repo)
    assert answer["ok"] is True
    assert answer["written"], "the report must survive"
    assert answer["warmed"] is False
    assert any(w.startswith("no warm-up: ") and "models.auto" in w for w in answer["warnings"])


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


def _lock(repo) -> dict:
    return json.loads((repo / LOCK_PATH).read_text(encoding="utf-8"))


def test_init_locks_every_file_it_wrote(monkeypatch, repo):
    quiet(monkeypatch)
    answer = workspace_init(root=repo)
    assert answer["values"] == DEFAULT_VALUES
    assert answer["templates"] == {relative: "current" for relative in LAYOUT.values()}
    lock = _lock(repo)
    assert lock["values"] == DEFAULT_VALUES
    assert lock["files"] == {
        relative: digest((repo / relative).read_bytes()) for relative in LAYOUT.values()
    }


def test_a_value_given_once_is_kept_by_the_lock(monkeypatch, repo):
    quiet(monkeypatch)
    workspace_init(root=repo, test="cargo test", lint="cargo clippy")
    answer = workspace_init(root=repo)
    assert answer["values"] == {"test": "cargo test", "lint": "cargo clippy"}
    assert answer["written"] == []


def test_init_without_a_flag_locks_a_current_file_it_did_not_write(monkeypatch, repo):
    """Older projects get their lock without a single file overwritten."""
    quiet(monkeypatch)
    workspace_init(root=repo)
    (repo / LOCK_PATH).unlink()
    answer = workspace_init(root=repo)
    assert answer["written"] == []
    assert set(_lock(repo)["files"]) == set(LAYOUT.values())


def test_a_changed_value_leaves_an_untouched_file_outdated_until_update(monkeypatch, repo):
    """Without --update nothing is overwritten -- and the entry stays, or the next
    --update could no longer tell the untouched file from an edited one."""
    quiet(monkeypatch)
    workspace_init(root=repo)
    before = _lock(repo)["files"][".config/wt.toml"]
    answer = workspace_init(root=repo, test="cargo test")
    assert answer["templates"][".config/wt.toml"] == "outdated"
    assert ".config/wt.toml" in answer["skipped"]
    assert _lock(repo)["files"][".config/wt.toml"] == before
    assert any(w.startswith(".config/wt.toml is outdated") for w in answer["warnings"])

    updated = workspace_init(root=repo, update=True)
    assert ".config/wt.toml" in updated["written"]
    assert updated["templates"][".config/wt.toml"] == "current"
    gate = tomllib.loads((repo / ".config" / "wt.toml").read_text(encoding="utf-8"))
    assert gate["pre-merge"]["test"] == "cargo test"


def test_update_leaves_a_hand_edit_and_says_why(monkeypatch, repo):
    quiet(monkeypatch)
    workspace_init(root=repo)
    settings = repo / ".claude" / "settings.json"
    settings.write_text(
        settings.read_text(encoding="utf-8").replace("git add", "git add -p"), encoding="utf-8"
    )
    entry = _lock(repo)["files"][".claude/settings.json"]
    answer = workspace_init(root=repo, update=True, test="cargo test")
    assert ".claude/settings.json" in answer["skipped"]
    assert answer["templates"][".claude/settings.json"] == "diverged"
    assert "git add -p" in settings.read_text(encoding="utf-8")
    assert _lock(repo)["files"][".claude/settings.json"] == entry
    assert any(w.startswith(".claude/settings.json is diverged") for w in answer["warnings"])


def test_an_edit_on_its_own_is_intent_and_no_warning(monkeypatch, repo):
    quiet(monkeypatch)
    workspace_init(root=repo)
    entry = _lock(repo)["files"]["opencode.jsonc"]
    (repo / "opencode.jsonc").write_text("{}", encoding="utf-8")
    answer = workspace_init(root=repo, update=True)
    assert answer["templates"]["opencode.jsonc"] == "edited"
    assert "opencode.jsonc" in answer["skipped"]
    assert not any(w.startswith("opencode.jsonc") for w in answer["warnings"])
    assert (repo / "opencode.jsonc").read_text(encoding="utf-8") == "{}"
    assert _lock(repo)["files"]["opencode.jsonc"] == entry


def test_update_leaves_an_unknown_file_alone_and_says_so(monkeypatch, repo):
    """No lock entry and not what init would write: nobody can tell whose edit it is."""
    quiet(monkeypatch)
    workspace_init(root=repo)
    (repo / LOCK_PATH).unlink()
    (repo / "opencode.jsonc").write_text("{}", encoding="utf-8")
    answer = workspace_init(root=repo, update=True)
    assert "opencode.jsonc" in answer["skipped"]
    assert answer["templates"]["opencode.jsonc"] == "unknown"
    assert (repo / "opencode.jsonc").read_text(encoding="utf-8") == "{}"
    assert any(w.startswith("opencode.jsonc is unknown: ") for w in answer["warnings"])


def test_the_install_lines_reach_the_warnings(monkeypatch, repo):
    """`init` hands the install report on through `machine_report`, not a list of its own."""
    quiet(monkeypatch)
    monkeypatch.setattr(
        "lean_herdr.checkcmd.install_report",
        lambda **_kwargs: (dict(HEALTHY_INSTALL), ["SENTINEL"]),
    )
    assert "SENTINEL" in workspace_init(root=repo)["warnings"]


def test_force_writes_everything_and_locks_it(monkeypatch, repo):
    quiet(monkeypatch)
    workspace_init(root=repo)
    (repo / "opencode.jsonc").write_text("{}", encoding="utf-8")
    answer = workspace_init(root=repo, force=True, lint="cargo clippy")
    assert answer["written"] == sorted(LAYOUT.values())
    lock = _lock(repo)
    assert lock["values"]["lint"] == "cargo clippy"
    assert lock["files"]["opencode.jsonc"] == digest((repo / "opencode.jsonc").read_bytes())


def test_a_run_stopped_mid_loop_still_locks_what_landed(monkeypatch, repo):
    """Without the lock, the rerun forgets the value it was given and calls its own file unknown."""
    quiet(monkeypatch)
    blocker = repo / ".opencode" / "plugins" / "lean-ctx-policy.js"
    blocker.mkdir(parents=True)
    answer = workspace_init(root=repo, test="cargo test")
    assert answer["error"].startswith("init_stopped: "), answer
    assert _lock(repo)["values"]["test"] == "cargo test"
    assert answer["values"]["test"] == "cargo test"
    assert answer["templates"][".config/wt.toml"] == "current"
    blocker.rmdir()
    again = workspace_init(root=repo)
    assert again["templates"][".config/wt.toml"] == "current", again


def test_force_and_update_together_is_a_usage_error(monkeypatch, repo):
    quiet(monkeypatch)
    answer = workspace_init(root=repo, force=True, update=True)
    assert answer == {"ok": False, "error": "usage_error: --force and --update exclude each other"}
    assert not (repo / "opencode.jsonc").exists()


@pytest.mark.parametrize(
    "value",
    ['uv run "x"', "pytest*", "a:b", "$HOME/x", "a\nb"],
    ids=["quote", "star", "colon", "dollar", "newline"],
)
def test_a_flag_value_that_would_break_out_is_a_usage_error(monkeypatch, repo, value):
    quiet(monkeypatch)
    answer = workspace_init(root=repo, test=value)
    assert answer["ok"] is False
    assert answer["error"].startswith("usage_error: --test "), answer["error"]
    assert not (repo / "opencode.jsonc").exists()


def test_a_broken_lock_is_lock_malformed_and_nothing_is_written(monkeypatch, repo):
    quiet(monkeypatch)
    (repo / LOCK_PATH).parent.mkdir(parents=True)
    (repo / LOCK_PATH).write_text("not json", encoding="utf-8")
    answer = workspace_init(root=repo)
    assert answer["ok"] is False
    assert answer["error"].startswith("lock_malformed: ")
    assert answer["error"].endswith("-- fix or delete it")
    assert not (repo / "opencode.jsonc").exists()
    assert (repo / LOCK_PATH).read_text(encoding="utf-8") == "not json"


def test_init_names_the_generator_through_the_producer_check_uses(monkeypatch, repo):
    """`init` holds no warning list of its own: a machine without the generator is
    named here exactly as `workspace check` names it."""
    monkeypatch.setattr("shutil.which", which_stub(True))
    no_generator = FakeProc(replies={("config", "show"): '{"user": {"config": null}}'})
    warnings = workspace_init(root=repo, runner=no_generator)["warnings"]
    assert any("commit.generation.command" in w for w in warnings), warnings
