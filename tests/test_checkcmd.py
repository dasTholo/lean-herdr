"""`workspace check`: every group of warnings, and the errors that stop `up` and `dispatch`."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from lean_herdr import checkcmd
from lean_herdr.bus import BusError, GitUnusable
from lean_herdr.checkcmd import (
    PYCACHE_IGNORE,
    PYCACHE_PROBE,
    TEMP_IGNORE,
    TEMP_PROBE,
    _check_allowlist,
    _check_approvals,
    _check_generator,
    _check_overlay_ignored,
    _check_plugins,
    _check_pycache_ignored,
    _check_temp_ignored,
    _check_temp_leftovers,
    _linked_plugin,
    _read,
    install_report,
    workspace_check,
)
from lean_herdr.initcmd import workspace_init
from lean_herdr.settings import OVERLAY_PATH, SETTINGS_PATH, claude_settings_path, role_prompt_path
from lean_herdr.templating import LAYOUT, LOCK_PATH
from tests.doubles import Completed, FakeProc, undecodable, which_stub


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, timeout=30)
    return tmp_path


@pytest.fixture(autouse=True)
def no_user_lean_ctx_config(monkeypatch, tmp_path_factory):
    """`lean_md_warnings` reads lean-ctx's config -- never this machine's own in here."""
    monkeypatch.setenv("LEAN_CTX_CONFIG_DIR", str(tmp_path_factory.mktemp("no-lean-ctx")))


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
def test_an_unreadable_approvals_reply_is_reported_as_an_unknown_state(
    monkeypatch, tmp_path, reply
):
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


def test_the_overlay_check_asks_git_rather_than_reading_gitignore(monkeypatch, repo):
    """The verdict is git's, not ours.

    A rule can sit in a parent directory, in `.git/info/exclude` or in a
    global excludes file, and a text search over `.gitignore` would raise
    a false alarm on every one of them.
    """
    monkeypatch.setattr("shutil.which", which_stub(True))
    named = FakeProc(replies={("check-ignore",): f".gitignore:20:{OVERLAY_PATH}\t{OVERLAY_PATH}"})
    assert _check_overlay_ignored(repo, named) is None
    silent = FakeProc(replies={("check-ignore",): Completed(returncode=1)})
    line = _check_overlay_ignored(repo, silent)
    assert line is not None and str(OVERLAY_PATH) in line


def test_without_git_there_is_no_verdict_on_the_overlay(monkeypatch, repo):
    """No git at all: no answer, and an unasked question invents none."""
    monkeypatch.setattr("shutil.which", lambda binary: None if binary == "git" else "/usr/bin/fake")
    assert _check_overlay_ignored(repo, FakeProc(default="")) is None


def test_the_temp_check_asks_git_about_a_probe_name(monkeypatch, repo):
    """`check-ignore` matches patterns, so the probe needs no file on disk."""
    monkeypatch.setattr("shutil.which", which_stub(True))
    named = FakeProc(replies={("check-ignore",): f".gitignore:23:{TEMP_IGNORE}\t{TEMP_PROBE}"})
    assert _check_temp_ignored(repo, named) is None
    assert named.called_with("check-ignore", "-v", str(TEMP_PROBE))
    silent = FakeProc(replies={("check-ignore",): Completed(returncode=1)})
    line = _check_temp_ignored(repo, silent)
    assert line is not None and TEMP_IGNORE in line


@pytest.mark.parametrize(
    ("check", "names"),
    [
        pytest.param(_check_overlay_ignored, str(OVERLAY_PATH), id="overlay"),
        pytest.param(_check_temp_ignored, TEMP_IGNORE, id="temp files"),
    ],
)
def test_an_ignore_check_judges_by_the_exit_code_not_the_output(monkeypatch, repo, check, names):
    """git answers 1 for a path it does not ignore -- and may still print a warning.

    Read as output, that warning passed for a named rule: a green verdict over a
    path nobody ignores. Anything but 0 and 1 -- 128 and a `fatal:` -- is no
    verdict either way.
    """
    monkeypatch.setattr("shutil.which", which_stub(True))
    warned = Completed(
        returncode=1,
        stderr="warning: unable to access '/home/x/.config/git/ignore': Permission denied\n",
    )
    line = check(repo, FakeProc(replies={("check-ignore",): warned}))
    assert line is not None and names in line
    fatal = Completed(returncode=128, stderr="fatal: not a git repository\n")
    assert check(repo, FakeProc(replies={("check-ignore",): fatal})) is None


@pytest.mark.parametrize(
    ("rule", "warned"),
    [
        pytest.param(
            ".lean-ctx/lean-herdr/.tmp-models.auto.toml.*", True, id="the overlay writer's only"
        ),
        pytest.param(TEMP_IGNORE, False, id="every writer's"),
    ],
)
def test_the_temp_check_probes_the_lock_writer_as_well(monkeypatch, repo, rule, warned):
    """A rule for the overlay's temp names passes that probe and misses the lock's.

    Real git, with the operator's own excludes kept out: the verdict is git's match.
    """
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(repo / "no-config"))
    (repo / ".gitignore").write_text(f"{OVERLAY_PATH}\n{rule}\n", encoding="utf-8")
    line = _check_temp_ignored(repo, subprocess.run)
    assert (line is not None) is warned, line
    if warned:
        assert line is not None and ".tmp-templates.lock.json" in line


def _python_project(repo: Path) -> None:
    (repo / "pyproject.toml").write_text('[project]\nname = "probe"\n', encoding="utf-8")


def test_the_pycache_check_asks_git_about_a_probe_name(monkeypatch, repo):
    monkeypatch.setattr("shutil.which", which_stub(True))
    _python_project(repo)
    named = FakeProc(replies={("check-ignore",): f".gitignore:2:{PYCACHE_IGNORE}\t{PYCACHE_PROBE}"})
    assert _check_pycache_ignored(repo, named) is None
    assert named.called_with("check-ignore", "-v", PYCACHE_PROBE)
    silent = FakeProc(replies={("check-ignore",): Completed(returncode=1)})
    assert _check_pycache_ignored(repo, silent) == (
        "git does not ignore __pycache__/ (probed with __pycache__/lean-herdr.probe) -- every test "
        "run leaves bytecode there, and untracked files stop `wt merge --no-commit` and "
        "`wt remove`. Add to .gitignore: __pycache__/"
    )


def test_without_pyproject_there_is_no_pycache_question(monkeypatch, repo):
    monkeypatch.setattr("shutil.which", which_stub(True))
    proc = FakeProc(replies={("check-ignore",): Completed(returncode=1)})
    assert _check_pycache_ignored(repo, proc) is None
    assert not proc.called_with("check-ignore"), proc.flat()


def test_a_pycache_check_git_cannot_answer_gives_no_verdict(monkeypatch, repo):
    monkeypatch.setattr("shutil.which", which_stub(True))
    _python_project(repo)
    fatal = Completed(returncode=128, stderr="fatal: not a git repository\n")
    assert _check_pycache_ignored(repo, FakeProc(replies={("check-ignore",): fatal})) is None
    monkeypatch.setattr("shutil.which", lambda binary: None if binary == "git" else "/usr/bin/fake")
    assert _check_pycache_ignored(repo, FakeProc(default="")) is None


@pytest.mark.parametrize(
    ("gitignore", "warned"),
    [pytest.param("", True, id="no rule"), pytest.param("__pycache__/\n", False, id="rule")],
)
def test_the_pycache_rule_covers_the_probe_with_no_directory_on_disk(
    monkeypatch, repo, gitignore, warned
):
    """Real git, with the operator's own excludes kept out (M4)."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(repo / "no-config"))
    _python_project(repo)
    (repo / ".gitignore").write_text(gitignore, encoding="utf-8")
    line = _check_pycache_ignored(repo, subprocess.run)
    assert (line is not None) is warned, line


def test_workspace_check_names_an_unignored_pycache_in_a_python_project(
    monkeypatch, repo, snapshot
):
    initialised(monkeypatch, repo)
    _python_project(repo)
    proc = FakeProc(
        replies={("check-ignore", "-v", PYCACHE_PROBE): Completed(returncode=1)},
        default=Completed(),
    )
    warnings = workspace_check(root=repo, runner=proc)["warnings"]
    assert any(w.startswith(f"git does not ignore {PYCACHE_IGNORE}") for w in warnings), warnings


#: A child that answers with a byte no codec takes.
UNDECODABLE_CHILD = [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'\\xff')"]


def test_a_real_child_with_an_undecodable_answer_does_not_raise():
    assert _read(subprocess.run, *UNDECODABLE_CHILD) == "\N{REPLACEMENT CHARACTER}"


@pytest.mark.parametrize("judge", [_check_approvals, _check_generator])
def test_an_undecodable_answer_is_no_green_verdict(monkeypatch, tmp_path, judge):
    """Replaced, the bytes stay an unreadable reply -- never a silent None."""
    monkeypatch.setattr("shutil.which", which_stub(True))

    def child(_cmd, *, check, **kwargs):
        return subprocess.run(UNDECODABLE_CHILD, check=check, **kwargs)

    assert judge(tmp_path, child) is not None


def wt_show(user=None, system=None) -> str:
    """wt's own shape (0.77.0), with the stderr line `_read` appends behind the JSON."""
    shown = {
        "user": {"config": user, "exists": user is not None, "path": "/home/x/.config/wt.toml"},
        "system": {"exists": system is not None, "path": "/etc/xdg/worktrunk/config.toml"},
    }
    if system is not None:
        shown["system"]["config"] = system
    return json.dumps(shown, indent=2) + "\n\n▲ Project config has key list.json-schema\n"


def generation(command: str) -> dict:
    return {"commit": {"generation": {"command": command}}}


@pytest.mark.parametrize(
    ("user", "system", "warned"),
    [
        pytest.param(generation("lean-herdr llm generate"), None, False, id="user config"),
        pytest.param(
            generation("lean-herdr llm generate --effort low"), None, False, id="flags behind it"
        ),
        pytest.param(None, generation("lean-herdr llm generate"), False, id="system config"),
        pytest.param(
            generation("/home/x/lean-herdr/bin/herdr-llm generate"),
            generation("lean-herdr llm generate"),
            True,
            id="user before system",
        ),
        pytest.param(None, None, True, id="none at all"),
    ],
)
def test_the_generator_is_read_user_before_system(monkeypatch, tmp_path, user, system, warned):
    monkeypatch.setattr("shutil.which", which_stub(True))
    proc = FakeProc(replies={("config", "show"): wt_show(user, system)})
    line = _check_generator(tmp_path, proc)
    assert (line is not None) is warned, line
    assert proc.called_with("wt", "config", "show", "--format", "json")


def test_a_missing_generator_names_the_line_to_add(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", which_stub(True))
    line = _check_generator(tmp_path, FakeProc(replies={("config", "show"): wt_show()}))
    assert line is not None and 'command = "lean-herdr llm generate"' in line


def test_an_unreadable_wt_answer_is_no_green_verdict(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", which_stub(True))
    line = _check_generator(tmp_path, FakeProc(replies={("config", "show"): "error: no"}))
    assert line is not None and "no readable answer" in line


def prefix_with(tmp_path: Path, *, receipt: bool = True) -> tuple[Path, Path]:
    """A prepared tool venv: (prefix, the package's __init__.py inside it)."""
    prefix = tmp_path / "tools" / "lean-herdr"
    package = prefix / "lib" / "python3.14" / "site-packages" / "lean_herdr" / "__init__.py"
    package.parent.mkdir(parents=True)
    package.write_text("", encoding="utf-8")
    (prefix / "bin").mkdir()
    (prefix / "bin" / "lean-herdr").write_text("", encoding="utf-8")
    if receipt:
        (prefix / "uv-receipt.toml").write_text("", encoding="utf-8")
    return prefix, package


def report(prefix, package, *, binary, direct_url=None, environ=None):
    return install_report(
        prefix=prefix,
        package=package,
        which=lambda _name: None if binary is None else str(binary),
        direct_url=lambda: direct_url,
        environ=environ or {},
    )


def test_a_snapshot_reached_through_a_symlink_on_path_warns_about_nothing(tmp_path):
    """`~/.local/bin/lean-herdr` is a symlink into the tool venv -- the correct install."""
    prefix, package = prefix_with(tmp_path)
    link = tmp_path / "local-bin" / "lean-herdr"
    link.parent.mkdir()
    link.symlink_to(prefix / "bin" / "lean-herdr")
    install, lines = report(
        prefix, package, binary=link, direct_url='{"url": "file:///x", "dir_info": {}}'
    )
    assert lines == []
    assert install["tool"] is True
    assert install["editable"] is False
    assert install["package"] == str(package.parent.resolve())
    assert install["binary"] == str((prefix / "bin" / "lean-herdr").resolve())


def test_no_receipt_is_no_tool_venv(tmp_path):
    prefix, package = prefix_with(tmp_path, receipt=False)
    install, lines = report(prefix, package, binary=prefix / "bin" / "lean-herdr")
    assert install["tool"] is False
    assert any("uv-receipt.toml" in line for line in lines), lines


def test_an_editable_install_is_named(tmp_path):
    prefix, package = prefix_with(tmp_path)
    install, lines = report(
        prefix,
        package,
        binary=prefix / "bin" / "lean-herdr",
        direct_url='{"url": "file:///home/x/lean-herdr", "dir_info": {"editable": true}}',
    )
    assert install["editable"] is True
    assert any("editable" in line for line in lines), lines


def test_a_package_outside_the_prefix_names_pythonpath_when_it_is_set(tmp_path):
    prefix, _ = prefix_with(tmp_path)
    fake = tmp_path / "elsewhere" / "lean_herdr" / "__init__.py"
    fake.parent.mkdir(parents=True)
    fake.write_text("", encoding="utf-8")
    _, lines = report(
        prefix,
        fake,
        binary=prefix / "bin" / "lean-herdr",
        environ={"PYTHONPATH": str(tmp_path / "elsewhere")},
    )
    assert any("PYTHONPATH=" in line for line in lines), lines


def test_a_binary_outside_the_prefix_is_a_shadowing_venv(tmp_path):
    prefix, package = prefix_with(tmp_path)
    venv = tmp_path / "repo" / ".venv" / "bin" / "lean-herdr"
    venv.parent.mkdir(parents=True)
    venv.write_text("", encoding="utf-8")
    _, lines = report(prefix, package, binary=venv)
    assert any("outside" in line and ".venv" in line for line in lines), lines


def test_no_binary_on_path_is_named(tmp_path):
    prefix, package = prefix_with(tmp_path)
    _, lines = report(prefix, package, binary=None)
    assert any("not on PATH" in line for line in lines), lines


def test_the_plugin_link_is_read_from_the_local_marker(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", which_stub(True))
    expected = tmp_path / "lean_herdr" / "plugin"
    good = FakeProc(
        replies={
            ("plugin", "list"): (
                f"1 plugin installed:\n- lean.herdr (lean-herdr context) enabled [local:{expected}]\n"
            )
        }
    )
    assert _linked_plugin(good, expected) == (str(expected), None)
    assert good.called_with("herdr", "plugin", "list", "--plugin", "lean.herdr")
    checkout = FakeProc(
        replies={("plugin", "list"): "- lean.herdr (context) enabled [local:/home/x/lean-herdr]\n"}
    )
    linked, line = _linked_plugin(checkout, expected)
    assert linked == "/home/x/lean-herdr"
    assert line is not None and f"herdr plugin link {expected}" in line


@pytest.mark.parametrize(
    ("through_link", "foreign_first"),
    [
        pytest.param(True, False, id="the same folder through a symlink"),
        pytest.param(False, True, id="another plugin's local path first"),
    ],
)
def test_the_plugin_link_is_judged_on_its_own_line_by_its_resolved_path(
    monkeypatch, tmp_path, through_link, foreign_first
):
    monkeypatch.setattr("shutil.which", which_stub(True))
    expected = tmp_path / "lean_herdr" / "plugin"
    expected.mkdir(parents=True)
    listed = expected
    if through_link:
        listed = tmp_path / "linked-plugin"
        listed.symlink_to(expected, target_is_directory=True)
    foreign = "- other.plugin (other) enabled [local:/x]\n" if foreign_first else ""
    proc = FakeProc(
        replies={("plugin", "list"): f"{foreign}- lean.herdr (context) enabled [local:{listed}]\n"}
    )
    assert _linked_plugin(proc, expected) == (str(listed), None)


def test_a_link_elsewhere_names_the_unlink_by_id(monkeypatch, tmp_path):
    """`herdr plugin unlink` takes the plugin id, not a path (Task 0d)."""
    monkeypatch.setattr("shutil.which", which_stub(True))
    expected = tmp_path / "lean_herdr" / "plugin"
    checkout = FakeProc(
        replies={("plugin", "list"): "- lean.herdr (context) enabled [local:/home/x/lean-herdr]\n"}
    )
    _linked, line = _linked_plugin(checkout, expected)
    assert line is not None and "herdr plugin unlink lean.herdr" in line, line
    assert f"herdr plugin link {expected}" in line


def test_without_herdr_there_is_no_plugin_verdict(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", which_stub(False))
    assert _linked_plugin(FakeProc(), tmp_path) == (None, None)


def test_temp_files_left_behind_are_named(tmp_path):
    assert _check_temp_leftovers(tmp_path) is None
    folder = tmp_path / OVERLAY_PATH.parent
    folder.mkdir(parents=True)
    (folder / ".tmp-models.auto.toml.k3j9x_ab").write_text("half", encoding="utf-8")
    line = _check_temp_leftovers(tmp_path)
    assert line is not None and ".tmp-models.auto.toml.k3j9x_ab" in line


#: A snapshot install that shadows nothing -- this suite runs from the repo venv,
#: which is, correctly, no snapshot.
HEALTHY = {
    "tool": True,
    "editable": False,
    "package": "/snap/lean_herdr",
    "binary": "/snap/bin/lean-herdr",
    "plugin": None,
}


@pytest.fixture
def snapshot(monkeypatch):
    monkeypatch.setattr(checkcmd, "install_report", lambda **_kwargs: (dict(HEALTHY), []))


def healthy_machine() -> FakeProc:
    return FakeProc(
        replies={
            ("allow", "--list"): "Extra (additive, via `lean-ctx allow`): lean-herdr",
            ("config", "approvals"): '{"state": "approved"}',
            ("config", "show"): wt_show(generation("lean-herdr llm generate")),
            ("plugin", "list"): "- lean.herdr (context) enabled [local:/snap/lean_herdr/plugin]\n",
            ("check-ignore",): ".gitignore:1:rule\tpath",
            ("outline",): {"phases": [], "macros": {}, "errors": []},
            ("ls-files",): "\n".join(checkcmd.COMMITTED_FILES) + "\n",
        }
    )


def initialised(monkeypatch, repo):
    """`init` on a machine without binaries, then every binary back on the PATH."""
    monkeypatch.setattr("shutil.which", which_stub(False))
    assert workspace_init(root=repo)["ok"] is True
    monkeypatch.setattr("shutil.which", which_stub(True))


@pytest.fixture
def lean_md_ready(monkeypatch, repo, tmp_path_factory):
    """What `lean_md_warnings` asks for: the gateway entry, its skills dir, the skill stub."""
    config = tmp_path_factory.mktemp("lean-ctx")
    skills = tmp_path_factory.mktemp("skills")
    (config / "config.toml").write_text(
        f'[[gateway.servers]]\nname = "lean-md"\n\n[gateway.servers.env]\nLEAN_MD_SKILLS_DIR = "{skills}"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("LEAN_CTX_CONFIG_DIR", str(config))
    stub = repo / ".claude" / "skills" / "lmd-writing-plans" / "SKILL.md"
    stub.parent.mkdir(parents=True)
    stub.write_text("stub\n", encoding="utf-8")


def test_an_initialised_project_on_a_healthy_machine_is_ok_and_all_current(
    monkeypatch, repo, snapshot, lean_md_ready
):
    initialised(monkeypatch, repo)
    answer = workspace_check(root=repo, runner=healthy_machine())
    assert answer["ok"] is True, answer
    assert answer["errors"] == []
    # After `init` no worker has a kind or a model -- the normal case, and check names both.
    assert answer["warnings"] == [
        _kind_unset("builder", "implement"),
        _model_unset("builder", "implement"),
        _kind_unset("plan-writer", "plan"),
        _model_unset("plan-writer", "plan"),
        _kind_unset("plan-reviewer", "plan-review"),
        _model_unset("plan-reviewer", "plan-review"),
        _kind_unset("reviewer", "review"),
        _model_unset("reviewer", "review"),
    ]
    assert answer["root"] == str(repo)
    assert answer["templates"] == {relative: "current" for relative in LAYOUT.values()}
    assert answer["install"]["plugin"] == "/snap/lean_herdr/plugin"


def test_check_changes_nothing_and_runs_nothing_that_writes(monkeypatch, repo, snapshot):
    """No start, no write, no fetch, no warm-up -- and no gesture that belongs to a human."""
    initialised(monkeypatch, repo)

    def files() -> dict:
        return {p: p.read_bytes() for p in repo.rglob("*") if p.is_file() and ".git" not in p.parts}

    before = files()
    proc = healthy_machine()
    workspace_check(root=repo, runner=proc)
    assert files() == before
    for forbidden in (
        ("allow", "lean-herdr"),
        ("approvals", "add"),
        ("plugin", "link"),
        ("opencode",),
    ):
        assert not proc.called_with(*forbidden), proc.flat()


def test_outside_a_repository_there_is_no_root_and_an_error(monkeypatch, snapshot):
    def no_repo(*_args, **_kwargs):
        raise BusError("git rev-parse --git-common-dir failed: not a git repository")

    monkeypatch.setattr(checkcmd, "canonical_root", no_repo)
    monkeypatch.setattr("shutil.which", which_stub(False))
    answer = workspace_check()
    assert answer["ok"] is False
    assert "root" not in answer
    assert answer["errors"][0].startswith("git rev-parse --git-common-dir failed")
    assert answer["templates"] == {}


def test_the_install_lines_reach_the_warnings(monkeypatch, repo):
    """`check` hands the install report on through `machine_report`."""
    monkeypatch.setattr(checkcmd, "install_report", lambda **_kwargs: (dict(HEALTHY), ["SENTINEL"]))
    monkeypatch.setattr("shutil.which", which_stub(False))
    assert "SENTINEL" in workspace_check(root=repo)["warnings"]


def test_a_git_that_cannot_answer_is_not_sent_into_a_repository(monkeypatch, snapshot):
    """`run this inside a git repository` is the wrong repair for a missing or hung git."""

    def unusable(*_args, **_kwargs):
        raise GitUnusable("git_unusable: [Errno 2] No such file or directory: 'git'")

    monkeypatch.setattr(checkcmd, "canonical_root", unusable)
    monkeypatch.setattr("shutil.which", which_stub(False))
    answer = workspace_check()
    assert answer["ok"] is False
    assert answer["errors"][0].startswith("git_unusable"), answer["errors"]
    assert "inside a git repository" not in answer["errors"][0], answer["errors"]


def test_a_runner_that_decodes_strictly_does_not_crash_check(monkeypatch, repo, snapshot):
    initialised(monkeypatch, repo)
    answer = workspace_check(root=repo, runner=undecodable)
    assert answer["root"] == str(repo)
    assert answer["templates"] == {relative: "current" for relative in LAYOUT.values()}


def test_a_project_init_never_touched_is_not_initialised(monkeypatch, repo, snapshot):
    monkeypatch.setattr("shutil.which", which_stub(False))
    answer = workspace_check(root=repo)
    assert answer["ok"] is False
    assert any(e.startswith("not_initialised:") for e in answer["errors"]), answer["errors"]
    assert any(e.startswith("no_agent_config:") for e in answer["errors"]), answer["errors"]
    assert answer["templates"] == {relative: "missing" for relative in LAYOUT.values()}


@pytest.mark.parametrize(
    ("config", "overlay", "names"),
    [
        pytest.param(
            '[roles.builder]\ndirection = "links"\n', None, "direction", id="a role table"
        ),
        pytest.param('[llm]\neffort = "enormous"\n', None, "effort", id="the llm table"),
        pytest.param(None, "[llm]\nmodel = 5\n", "lean-herdr models apply", id="the overlay"),
    ],
)
def test_what_stops_up_or_dispatch_is_an_error(monkeypatch, repo, snapshot, config, overlay, names):
    initialised(monkeypatch, repo)
    monkeypatch.setattr("shutil.which", which_stub(False))
    if config is not None:
        (repo / SETTINGS_PATH).write_text(config, encoding="utf-8")
    if overlay is not None:
        (repo / OVERLAY_PATH).write_text(overlay, encoding="utf-8")
    answer = workspace_check(root=repo)
    assert answer["ok"] is False
    assert any(e.startswith("config_error:") and names in e for e in answer["errors"]), answer


@pytest.mark.parametrize("text", ["not json", "[" * 200000], ids=["no-json", "nested-too-deep"])
def test_a_broken_lock_guesses_no_state(monkeypatch, repo, snapshot, text):
    initialised(monkeypatch, repo)
    monkeypatch.setattr("shutil.which", which_stub(False))
    (repo / LOCK_PATH).write_text(text, encoding="utf-8")
    answer = workspace_check(root=repo)
    assert answer["templates"] == {}
    assert any(w.startswith("lock_malformed:") for w in answer["warnings"]), answer["warnings"]


def test_a_symlinked_lock_directory_is_blocked_and_not_read_through(
    monkeypatch, repo, snapshot, tmp_path_factory
):
    """Read through the link, a stranger's file would be named this project's broken lock.

    The leftover scan stays out of the linked folder as well: its temp files are not ours.
    """
    monkeypatch.setattr("shutil.which", which_stub(False))
    outside = tmp_path_factory.mktemp("outside-lean-ctx")
    (outside / "lean-herdr").mkdir()
    (outside / "lean-herdr" / "templates.lock.json").write_text("not json", encoding="utf-8")
    (outside / "lean-herdr" / ".tmp-templates.lock.json.q1w2e3").write_text("x", encoding="utf-8")
    (repo / ".lean-ctx").symlink_to(outside, target_is_directory=True)
    warnings = workspace_check(root=repo)["warnings"]
    assert not any(w.startswith("lock_malformed:") for w in warnings), warnings
    assert any(w.startswith(f"{LOCK_PATH} is blocked: ") for w in warnings), warnings
    assert not any("left behind" in w for w in warnings), warnings


def test_an_outdated_template_names_init_update(monkeypatch, repo, snapshot):
    initialised(monkeypatch, repo)
    monkeypatch.setattr("shutil.which", which_stub(False))
    lock = repo / LOCK_PATH
    lock.write_text(
        lock.read_text(encoding="utf-8").replace("uv run pytest", "cargo test"), encoding="utf-8"
    )
    answer = workspace_check(root=repo)
    assert answer["templates"][".config/wt.toml"] == "outdated"
    assert any(
        w.startswith(".config/wt.toml is outdated") and "init --update" in w
        for w in answer["warnings"]
    ), answer["warnings"]


@pytest.mark.parametrize("auto", [False, True], ids=["auto-off", "auto-on"])
def test_only_the_overlay_ignored_names_the_temp_line_whatever_auto_says(
    monkeypatch, repo, snapshot, auto
):
    """One verdict per path: the overlay's rule covers the overlay and nothing else.

    With `auto` on both checks run -- and a single `check-ignore` over both paths
    would answer as soon as the overlay is covered.
    """
    initialised(monkeypatch, repo)
    if auto:
        (repo / SETTINGS_PATH).write_text("[models]\nauto = true\n", encoding="utf-8")
    proc = FakeProc(
        replies={
            ("check-ignore", "-v", str(OVERLAY_PATH)): (
                f".gitignore:22:{OVERLAY_PATH}\t{OVERLAY_PATH}"
            )
        },
        default=Completed(returncode=1),
    )
    answer = workspace_check(root=repo, runner=proc)
    assert any(TEMP_IGNORE in w for w in answer["warnings"]), answer["warnings"]
    assert not any(f"does not ignore {OVERLAY_PATH}" in w for w in answer["warnings"])


def _kind_unset(role: str, work: str) -> str:
    return f"[roles.{role}].kind unset: `dispatch --work {work}` needs --kind"


def _model_unset(role: str, work: str) -> str:
    return f"[roles.{role}].model unset: `dispatch --work {work}` needs --model"


def test_a_worker_with_a_model_is_not_named_and_default_counts(monkeypatch, repo, snapshot):
    """`[default].model` reaches every role through settings_for -- no line for any of them."""
    initialised(monkeypatch, repo)
    monkeypatch.setattr("shutil.which", which_stub(False))
    (repo / SETTINGS_PATH).write_text(
        '[default]\nmodel = "cheap"\n\n[roles.builder]\nmodel = "strong"\n', encoding="utf-8"
    )
    warnings = workspace_check(root=repo)["warnings"]
    assert not any(".model unset" in w for w in warnings), warnings


def test_the_orchestrator_is_never_named_for_a_missing_model(monkeypatch, repo, snapshot):
    """`workspace up` starts the orchestrator without a model -- a work routed to it gets no line."""
    initialised(monkeypatch, repo)
    monkeypatch.setattr("shutil.which", which_stub(False))
    (repo / SETTINGS_PATH).write_text('[routing]\nsteer = "orchestrator"\n', encoding="utf-8")
    warnings = workspace_check(root=repo)["warnings"]
    assert _model_unset("orchestrator", "steer") not in warnings, warnings
    assert _model_unset("builder", "implement") in warnings, warnings


#: A work of the project's own, routed to a role `init` never wrote.
REFACTORER = '[routing]\nrename = "refactorer"\n\n[roles.refactorer]\nkind = "{kind}"\n'


def _refactorer(repo: Path, kind: str, *, prompt: bool = True) -> Path:
    """The config for `rename`, and -- unless told not to -- the builder's prompt as its own."""
    (repo / SETTINGS_PATH).write_text(REFACTORER.format(kind=kind), encoding="utf-8")
    path = role_prompt_path(repo, "refactorer")
    if prompt:
        path.write_bytes(role_prompt_path(repo, "builder").read_bytes())
    return path


@pytest.mark.parametrize(
    ("kind", "prompt", "expected"),
    [
        pytest.param("claude", False, "no role prompt at {path}", id="no prompt"),
        pytest.param(
            "opencode",
            True,
            "opencode.jsonc in {repo} defines no agent.refactorer",
            id="no opencode block",
        ),
        pytest.param("claude", True, "no claude settings at {claude}", id="no claude file"),
    ],
)
def test_a_routed_role_dispatch_would_refuse_is_named(
    monkeypatch, repo, snapshot, kind, prompt, expected
):
    """A warning, not an error: `up` runs without it, and an unused work costs nothing."""
    initialised(monkeypatch, repo)
    monkeypatch.setattr("shutil.which", which_stub(False))
    path = _refactorer(repo, kind, prompt=prompt)
    line = expected.format(path=path, repo=repo, claude=claude_settings_path(repo, "refactorer"))

    answer = workspace_check(root=repo)

    assert answer["errors"] == [], answer["errors"]
    assert f"{line} -- `dispatch --work rename` fails" in answer["warnings"], answer["warnings"]


def test_a_worker_prompt_without_its_mandatory_sentences_is_named(monkeypatch, repo, snapshot):
    initialised(monkeypatch, repo)
    monkeypatch.setattr("shutil.which", which_stub(False))
    prompt = role_prompt_path(repo, "reviewer")
    text = re.sub(r"Never pass\s+`--agent`\.", "", prompt.read_text(encoding="utf-8"))
    prompt.write_text(text, encoding="utf-8")

    warnings = workspace_check(root=repo)["warnings"]

    expected = (
        f"{prompt} lacks ['Never pass `--agent`.'] -- "
        "a worker without them cannot take or answer an order"
    )
    assert expected in warnings, warnings


def test_a_role_only_routing_names_is_validated_too(monkeypatch, repo, snapshot):
    """`checkcmd.ROLES` knows four tables; a role behind `[routing]` is one more."""
    initialised(monkeypatch, repo)
    monkeypatch.setattr("shutil.which", which_stub(False))
    (repo / SETTINGS_PATH).write_text(
        '[routing]\nrename = "refactorer"\n\n[roles.refactorer]\ndirection = "links"\n',
        encoding="utf-8",
    )

    answer = workspace_check(root=repo)

    assert answer["ok"] is False
    assert any(e.startswith("config_error: refactorer: direction") for e in answer["errors"]), (
        answer["errors"]
    )


def test_a_work_routed_to_a_log_command_is_named(monkeypatch, repo, snapshot):
    """`dispatch --work` refuses a work routed to a log command; `check` says so first."""
    initialised(monkeypatch, repo)
    monkeypatch.setattr("shutil.which", which_stub(False))
    (repo / SETTINGS_PATH).write_text('[routing]\ncleanup = "order"\n', encoding="utf-8")

    answer = workspace_check(root=repo)

    assert answer["errors"] == [], answer["errors"]
    assert (
        "routing.cleanup: 'order' is a log command, not a role -- "
        "`dispatch --work cleanup` fails" in answer["warnings"]
    ), answer["warnings"]


def test_a_work_routed_to_the_orchestrators_agent_name_is_named(monkeypatch, repo, snapshot):
    """A real `dispatch --work` here would find the running orchestrator and `/clear` it."""
    initialised(monkeypatch, repo)
    monkeypatch.setattr("shutil.which", which_stub(False))
    (repo / SETTINGS_PATH).write_text('[routing]\ncleanup = "orch"\n', encoding="utf-8")

    answer = workspace_check(root=repo)

    assert answer["errors"] == [], answer["errors"]
    assert (
        "routing.cleanup: role 'orch' is the orchestrator's own agent name -- "
        "`dispatch --work cleanup` would /clear the running orchestrator, not build a worker"
        in answer["warnings"]
    ), answer["warnings"]


def _claude_state(monkeypatch, tmp_path_factory, projects: dict) -> None:
    config = tmp_path_factory.mktemp("claude")
    (config / ".claude.json").write_text(json.dumps({"projects": projects}), encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))


WORKER_UNTRUSTED = (
    "a claude worker stops at the folder-trust dialog in every worktree of this repository, "
    "and dispatch answers agent_blocked"
)
ORCHESTRATOR_UNTRUSTED = (
    "the claude orchestrator stops at the folder-trust dialog when workspace up starts it, "
    "and up answers agent_blocked"
)


def _untrusted(root: Path, consequence: str = WORKER_UNTRUSTED) -> str:
    return (
        f"claude does not trust {root} -- {consequence}. "
        "Run: lean-herdr workspace init --trust-claude"
    )


CLAUDE_BUILDER = '[roles.builder]\nkind = "claude"\n'


def test_a_claude_orchestrator_alone_is_named_for_up_not_for_worktrees(
    monkeypatch, repo, snapshot, tmp_path_factory
):
    initialised(monkeypatch, repo)
    monkeypatch.setattr("shutil.which", which_stub(False))
    (repo / SETTINGS_PATH).write_text('[roles.orchestrator]\nkind = "claude"\n', encoding="utf-8")
    _claude_state(monkeypatch, tmp_path_factory, {})
    warnings = workspace_check(root=repo)["warnings"]
    assert _untrusted(repo, ORCHESTRATOR_UNTRUSTED) in warnings, warnings
    assert _untrusted(repo) not in warnings, warnings


def test_a_claude_role_in_an_untrusted_root_is_named(monkeypatch, repo, snapshot, tmp_path_factory):
    initialised(monkeypatch, repo)
    monkeypatch.setattr("shutil.which", which_stub(False))
    (repo / SETTINGS_PATH).write_text(CLAUDE_BUILDER, encoding="utf-8")
    _claude_state(monkeypatch, tmp_path_factory, {})
    warnings = workspace_check(root=repo)["warnings"]
    assert _untrusted(repo) in warnings, warnings


def test_a_trusted_root_is_not_named(monkeypatch, repo, snapshot, tmp_path_factory):
    initialised(monkeypatch, repo)
    monkeypatch.setattr("shutil.which", which_stub(False))
    (repo / SETTINGS_PATH).write_text(CLAUDE_BUILDER, encoding="utf-8")
    _claude_state(
        monkeypatch, tmp_path_factory, {str(repo.resolve()): {"hasTrustDialogAccepted": True}}
    )
    warnings = workspace_check(root=repo)["warnings"]
    assert not any(w.startswith("claude does not trust") for w in warnings), warnings


def test_without_a_claude_role_trust_is_not_asked(monkeypatch, repo, snapshot, tmp_path_factory):
    initialised(monkeypatch, repo)
    monkeypatch.setattr("shutil.which", which_stub(False))
    (repo / SETTINGS_PATH).write_text('[roles.builder]\nkind = "opencode"\n', encoding="utf-8")
    _claude_state(monkeypatch, tmp_path_factory, {})
    warnings = workspace_check(root=repo)["warnings"]
    assert not any(w.startswith("claude does not trust") for w in warnings), warnings


def test_a_claude_state_nobody_can_read_gives_no_verdict(monkeypatch, repo, snapshot):
    """The suite-wide CLAUDE_CONFIG_DIR (tests/conftest.py) holds no state file at all."""
    initialised(monkeypatch, repo)
    monkeypatch.setattr("shutil.which", which_stub(False))
    (repo / SETTINGS_PATH).write_text(CLAUDE_BUILDER, encoding="utf-8")
    warnings = workspace_check(root=repo)["warnings"]
    assert not any(w.startswith("claude does not trust") for w in warnings), warnings
