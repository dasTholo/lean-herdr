"""`lean_md_warnings`: what a plan run needs, named before `lean-herdr plan` ever runs."""

import json

import pytest

from lean_herdr.checkcmd import COMMITTED_FILES, lean_md_warnings
from tests.doubles import Completed, FakeProc

OUTLINE = {"phases": [], "macros": {}, "errors": []}
STUB = ".claude/skills/lmd-writing-plans/SKILL.md"
GATEWAY = '[[gateway.servers]]\nname = "lean-md"\n\n[gateway.servers.env]\nLEAN_MD_SKILLS_DIR = "{skills}"\n'


@pytest.fixture
def ready(monkeypatch, tmp_path_factory):
    """A repository and a machine on which every check passes; each test takes one thing away."""
    repo = tmp_path_factory.mktemp("repo")
    config = tmp_path_factory.mktemp("lean-ctx")
    skills = tmp_path_factory.mktemp("skills")
    (config / "config.toml").write_text(GATEWAY.format(skills=skills), encoding="utf-8")
    (repo / STUB).parent.mkdir(parents=True)
    (repo / STUB).write_text("stub\n", encoding="utf-8")
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    return {
        "repo": repo,
        "config": config / "config.toml",
        "environ": {"LEAN_CTX_CONFIG_DIR": str(config)},
    }


def warnings(ready, replies=None, environ=None):
    table = {
        ("outline",): OUTLINE,
        ("ls-files",): "\n".join(COMMITTED_FILES) + "\n",
        **(replies or {}),
    }
    return lean_md_warnings(
        ready["repo"], runner=FakeProc(replies=table), environ=environ or ready["environ"]
    )


def test_a_ready_machine_and_repository_warn_about_nothing(ready):
    assert warnings(ready) == []


def test_no_lean_md_on_path(ready, monkeypatch):
    monkeypatch.setattr(
        "shutil.which", lambda name: None if name == "lean-md" else f"/usr/bin/{name}"
    )
    assert warnings(ready) == [
        "lean-md is not on PATH -- plans need lean-md >= 0.2.4, see INSTALL.md"
    ]


def test_a_lean_md_without_outline(ready):
    old = Completed(
        returncode=1, stderr="Usage: lean-md <render|check|mcp|skill|source|ack> [args]"
    )
    assert warnings(ready, {("outline",): old}) == [
        "lean-md on PATH knows no outline --json (needs >= 0.2.4) -- lean-herdr plan cannot read a plan"
    ]


def test_the_probe_hands_lean_md_an_empty_document_on_stdin(ready):
    seen = []

    def runner(cmd, **kwargs):
        seen.append((list(cmd), kwargs.get("input")))
        if cmd[1] == "outline":
            return Completed(stdout=json.dumps(OUTLINE))
        return Completed(stdout="\n".join(COMMITTED_FILES))

    assert lean_md_warnings(ready["repo"], runner=runner, environ=ready["environ"]) == []
    assert (["lean-md", "outline", "-", "--json"], "") in seen


def test_no_gateway_entry_is_named_with_its_file(ready):
    ready["config"].write_text("[gateway]\n", encoding="utf-8")
    assert warnings(ready) == [
        f"{ready['config']} has no gateway entry lean-md -- agents cannot render a skill (ctx_md_render)"
    ]


def test_no_lean_ctx_config_at_all_is_no_gateway_entry_either(ready, tmp_path):
    assert warnings(ready, environ={"LEAN_CTX_CONFIG_DIR": str(tmp_path)}) == [
        f"{tmp_path / 'config.toml'} has no gateway entry lean-md -- agents cannot render a skill (ctx_md_render)"
    ]


def test_a_broken_lean_ctx_config_gives_no_verdict_and_says_so(ready):
    ready["config"].write_text("[gateway\n", encoding="utf-8")
    (line,) = warnings(ready)
    assert line.startswith(f"{ready['config']} cannot be read: ")
    assert line.endswith(" -- no verdict on the lean-md gateway entry")


def test_a_skills_dir_that_is_gone(ready, tmp_path):
    gone = tmp_path / "gone"
    ready["config"].write_text(GATEWAY.format(skills=gone), encoding="utf-8")
    assert warnings(ready) == [
        f"LEAN_MD_SKILLS_DIR of the lean-md gateway entry in {ready['config']} is no directory: {str(gone)!r}"
    ]


def test_no_plan_skill_stub(ready):
    (ready["repo"] / STUB).unlink()
    assert warnings(ready) == [
        ".claude/skills/lmd-writing-plans is missing -- lean-herdr workspace init --update installs it"
    ]


def test_no_ty(ready, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None if name == "ty" else f"/usr/bin/{name}")
    assert warnings(ready) == [
        "ty is not on PATH -- .lean-ctx/lean-herdr/bin/pylsp starts ty server for Python workers"
    ]


def test_files_nobody_committed_are_named(ready):
    config = ready["repo"] / ".lean-ctx" / "lean-herdr" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text("", encoding="utf-8")
    assert warnings(ready, {("ls-files",): STUB + "\n"}) == [
        (
            "not committed: .lean-ctx/lean-herdr/config.toml -- a worker's worktree of plan/<slug> "
            "branches off main and lacks them; commit them on main"
        )
    ]
