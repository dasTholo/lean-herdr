import json
from pathlib import Path

import pytest

from lean_herdr.dispatch import (
    AGENT_READY_TIMEOUT_S,
    DispatchRequest,
    agent_args,
    agent_name,
    dispatch,
    main,
    profile_for,
)
from lean_herdr.herdr import Herdr
from lean_herdr.settings import (
    SETTINGS_PATH,
    RoleSettings,
    read_settings,
    settings_for,
)
from tests.doubles import FakeProc, which_stub

ROOT = Path("/repo")
AGENT_ID = "mcp-2018183-70c877bf"


def req(**kwargs) -> DispatchRequest:
    base = {
        "role": "builder",
        "kind": "claude",
        "model": "sonnet",
        "role_file": Path("roles/builder.md"),
    }
    return DispatchRequest(**{**base, **kwargs})  # ty: ignore[invalid-argument-type]


def registry() -> dict:
    return {"agents": [{"agent_id": AGENT_ID, "pid": 42}]}


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
    h_proc = FakeProc()
    h_proc.replies = {("pane", "split"): {"result": {"pane": {"pane_id": "w1:p6"}}}}
    return h_proc, tmp_path / "registry.json"


def run_dispatch(
    world,
    *,
    reg: dict,
    request=None,
    agent_id: str | None = AGENT_ID,
    waiter=None,
    **kwargs,
):
    h_proc, path = world
    path.write_text(json.dumps(reg), encoding="utf-8")
    return dispatch(
        request or req(),
        herdr=Herdr(runner=h_proc),
        root=ROOT,
        registry_path=path,
        waiter=waiter or (lambda *a, **kw: agent_id),
        **kwargs,
    )


def test_the_ready_timeout_default_exists_only_once():
    """Production reads `cfg.ready_timeout_s`; the module constant is only the
    signature default of wait_for_agent_id(). Two literals would drift."""
    assert AGENT_READY_TIMEOUT_S == RoleSettings().ready_timeout_s


def test_the_cli_flag_beats_the_file():
    cfg = RoleSettings(profile="power")
    assert profile_for("builder", None, settings=cfg) == "power"
    assert profile_for("builder", "minimal", settings=cfg) == "minimal"


def test_profile_for_falls_back_to_the_role_default_without_settings():
    """No `settings` at all must still give each role its built-in default --
    the orchestrator's `minimal` was silently lost once `role` stopped being
    read (review finding)."""
    assert profile_for("orchestrator") == "minimal"
    assert profile_for("builder") == "standard"


def test_profile_for_override_beats_the_role_default_too():
    assert profile_for("orchestrator", "power") == "power"


def test_profile_for_explicit_settings_beats_the_role_default_too():
    cfg = RoleSettings(profile="power")
    assert profile_for("orchestrator", settings=cfg) == "power"


def test_agent_name_follows_the_template():
    cfg = RoleSettings(name_template="{branch}--{role}")
    assert agent_name("builder", "feat/auth", settings=cfg) == "feat-auth--builder"
    assert agent_name("builder", None, settings=cfg) == "builder"


def test_agent_name_is_branch_AND_role():
    """A reviewer dispatch must never hit the running builder of that branch."""
    assert agent_name("builder", "feat/auth") == "builder-feat-auth"
    assert agent_name("builder", "feat/auth") != agent_name("reviewer", "feat/auth")


def test_the_role_prompt_travels_as_a_file_never_as_text():
    args = agent_args("claude", "sonnet", Path("roles/builder.md"))
    assert args == ["--model", "sonnet", "--append-system-prompt-file", "roles/builder.md"]
    assert not any("\n" in a for a in args), "Herdr rejects multi-line arguments (H2)"


def test_build_mode_returns_pane_and_agent_id_and_creates_nothing(world):
    """The build mode is finished the moment the agent_id is resolved."""
    h_proc, _ = world
    result = run_dispatch(world, reg=registry())
    assert result == {
        "ok": True, "pane": "w1:p6", "agent_id": AGENT_ID, "agent": "builder"
    }
    assert h_proc.called_with("agent", "start"), "the worker is running"
    assert not h_proc.called_with("agent", "prompt", "--wait"), (
        "the build mode neither rings nor waits"
    )


def test_the_build_mode_hands_out_the_agent_name(world):
    """The orchestrator must not have to rebuild the name template by hand."""
    result = run_dispatch(world, reg=registry())
    assert result["agent"] == "builder"


def test_the_pane_carries_the_agent_name_in_its_environment(world):
    """The worker resolves its own name from here -- no derivation, no drift.

    Built like the existing worktree tests: `world` is (FakeProc, path), the
    branch rides on `request=req(worktree=...)` -- `dispatch()` has no
    `worktree` parameter -- and the worktree replies must be in place or
    ensure_worktree() falls through to the real `wt` binary.
    """
    h_proc, _ = world
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
    result = run_dispatch(world, reg=registry(), request=req(worktree="feat/auth"))
    assert result["agent"] == "builder-feat-auth"
    split = next(c for c in h_proc.calls if c[1:3] == ["pane", "split"])
    assert "LEAN_HERDR_AGENT=builder-feat-auth" in " ".join(split)


def test_the_profile_is_set_on_the_pane_not_on_the_agent(world):
    h_proc, _ = world
    run_dispatch(world, reg=registry())
    assert h_proc.called_with("--env", "LEAN_CTX_TOOL_PROFILE=standard")
    assert h_proc.called_with("--env", "LEAN_CTX_ROLE=builder")
    start = next(c for c in h_proc.calls if c[1:3] == ["agent", "start"])
    assert "--env" not in start, "agent start knows no --env (H9)"


def test_dispatch_with_no_settings_still_gives_the_orchestrator_its_minimal_profile(
    world,
):
    """Same argv as before Task 7: `settings=None` must not fall back to
    `standard` for a role that has its own built-in default."""
    h_proc, _ = world
    run_dispatch(world, reg=registry(), request=req(role="orchestrator"))
    assert h_proc.called_with("--env", "LEAN_CTX_TOOL_PROFILE=minimal")


def test_layout_from_the_config_reaches_herdr(world):
    h_proc, _ = world
    run_dispatch(
        world, reg=registry(), settings=RoleSettings(direction="down", ratio=0.3)
    )
    split = next(c for c in h_proc.calls if c[1:3] == ["pane", "split"])
    assert "--direction" in split and split[split.index("--direction") + 1] == "down"
    assert "--ratio" in split and split[split.index("--ratio") + 1] == "0.3"


def test_the_configured_ready_timeout_reaches_the_waiter(world):
    """`ready_timeout_s` is the one knob no argv can show.

    Every other test stubs the waiter with `lambda *a, **kw: agent_id` and
    never looks at what it was handed -- so dropping `timeout_s=cfg.
    ready_timeout_s` would leave the whole suite green while the config knob
    quietly did nothing.
    """
    seen: list[dict] = []

    def spy(_herdr, _name, **kwargs):
        seen.append(kwargs)
        return AGENT_ID

    run_dispatch(
        world, reg=registry(), settings=RoleSettings(ready_timeout_s=7.5), waiter=spy
    )
    assert seen and seen[0].get("timeout_s") == 7.5


def test_focus_true_drops_the_no_focus_flag(world):
    """The second knob no test drove: `focus` only shows in the argv.

    `--no-focus` is added by Herdr.pane_split() when `focus` is false, so
    re-hardcoding it -- or dropping `focus=cfg.focus` -- would be invisible
    without both halves of this test.
    """
    h_proc, _ = world
    run_dispatch(world, reg=registry(), settings=RoleSettings(focus=True))
    focused = next(c for c in h_proc.calls if c[1:3] == ["pane", "split"])
    h_proc.calls.clear()
    run_dispatch(world, reg=registry(), settings=RoleSettings())
    unfocused = next(c for c in h_proc.calls if c[1:3] == ["pane", "split"])

    assert "--no-focus" not in focused, "focus = true must hand the pane the focus"
    assert "--no-focus" in unfocused, "the default must not steal the focus"


def test_without_a_config_file_the_split_is_the_one_from_before(world, tmp_path):
    """Global constraint: no `.config/lean-herdr.toml` -- byte-identical.

    The expected argv is the one this project sent before the config existed;
    a `--ratio` or a `--focus` sneaking in would show up here.
    """
    h_proc, _ = world
    missing = tmp_path / SETTINGS_PATH
    assert not missing.exists()
    cfg = settings_for("builder", read_settings(missing))
    run_dispatch(world, reg=registry(), settings=cfg)
    split = next(c for c in h_proc.calls if c[1:3] == ["pane", "split"])
    assert split == [
        "herdr", "pane", "split", "--current", "--direction", "right",
        "--cwd", "/repo", "--no-focus",
        "--env", "LEAN_CTX_TOOL_PROFILE=standard",
        "--env", "LEAN_CTX_ROLE=builder",
        "--env", "LEAN_HERDR_AGENT=builder",
    ]


def test_an_existing_agent_is_reused_and_cleared(world):
    h_proc, _ = world
    h_proc.replies = {
        ("agent", "list"): {"result": {"agents": [{"name": "builder", "pane_id": "w1:p6"}]}},
    }
    result = run_dispatch(world, reg=registry())
    assert result["pane"] == "w1:p6"
    assert not any(c[1:3] == ["pane", "split"] for c in h_proc.calls)
    clear = next(c for c in h_proc.calls if "/clear" in c)
    assert "--wait" not in clear, "/clear without --wait (H4)"


def test_the_build_mode_reads_the_registry_the_data_dir_points_at(
    monkeypatch, tmp_path
):
    """Both halves of one dispatch must read the SAME lean-ctx install.

    `bus.REGISTRY_PATH` is the hardcoded XDG default, while
    `orderlog.lean_ctx_data_dir()` honours `LEAN_CTX_DATA_DIR`, a legacy
    `~/.lean-ctx` and `XDG_*` -- for the same `agents/` directory. Reading
    the hardcoded one let the build mode stall into `no_agent_id` on every
    non-default install, while the wait mode read the right log.
    """
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
    # The hardcoded default is deliberately absent here: only the resolution
    # via the lean-ctx data dir can still find the agent.
    monkeypatch.setattr("lean_herdr.bus.REGISTRY_PATH", tmp_path / "nowhere.json")
    data = tmp_path / "data"
    (data / "agents").mkdir(parents=True)
    (data / "agents" / "registry.json").write_text(
        json.dumps({"agents": [{"agent_id": AGENT_ID, "pid": 4242}]}), encoding="utf-8"
    )
    monkeypatch.setenv("LEAN_CTX_DATA_DIR", str(data))

    h_proc = FakeProc()
    h_proc.replies = {
        ("agent", "list"): {
            "result": {"agents": [{"name": "builder", "pane_id": "w1:p6"}]}
        },
        ("pane", "process-info"): {"result": {"process_info": {"shell_pid": 4242}}},
    }

    result = dispatch(req(), herdr=Herdr(runner=h_proc), root=ROOT)

    assert result == {
        "ok": True, "pane": "w1:p6", "agent_id": AGENT_ID, "agent": "builder"
    }


def test_without_an_agent_id_the_script_reports_an_error(world):
    assert run_dispatch(world, reg=registry(), agent_id=None)["error"] == "no_agent_id"


def test_main_writes_one_json_line_and_exits_0(capsys, monkeypatch):
    monkeypatch.setattr(
        "lean_herdr.dispatch.canonical_root",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("no repo")),
    )
    code = main(
        ["builder", "--kind", "claude", "--model", "sonnet",
         "--role-file", "roles/builder.md"]
    )
    assert code == 0, "the orchestrator reads ok, not the exit code"
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1
    result = json.loads(lines[0])
    assert result["ok"] is False and result["error"].startswith("dispatch_crashed")


def _write_config(root: Path, text: str) -> None:
    (root / SETTINGS_PATH).parent.mkdir(parents=True, exist_ok=True)
    (root / SETTINGS_PATH).write_text(text, encoding="utf-8")


def test_main_loads_the_config_once_for_both_modes(monkeypatch, tmp_path):
    """One read, one RoleSettings, both modes -- and read from the repo root.

    Two things would break in silence otherwise. `SETTINGS_PATH` is relative:
    anchored on `$PWD` the file vanishes as soon as `bin/herdr-dispatch` runs
    from a subdirectory or a worktree -- which is why this test runs from a
    foreign cwd. And a wait mode with different settings would ring an agent
    under a different name than the build mode started.
    """
    root = tmp_path / "repo"
    _write_config(root, '[default]\nname_template = "{branch}.{role}"\n')
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setattr("lean_herdr.dispatch.canonical_root", lambda *a, **kw: root)
    seen: list[RoleSettings] = []

    def spy(_request, **kwargs):
        seen.append(kwargs["settings"])
        return {"ok": True}

    monkeypatch.setattr("lean_herdr.dispatch.dispatch", spy)
    monkeypatch.setattr("lean_herdr.dispatch.await_task", spy)

    base = ["builder", "--kind", "claude", "--worktree", "feat/auth"]
    main([*base, "--model", "sonnet", "--role-file", "roles/builder.md"])
    main([*base, "--await", "--task-id", "T1"])

    assert [s.name_template for s in seen] == ["{branch}.{role}"] * 2, (
        "the config lives in the repo root, not in $PWD"
    )
    assert seen[0] == seen[1], "both modes must name the same agent"
    assert agent_name("builder", "feat/auth", settings=seen[0]) == "feat-auth.builder"


def test_a_broken_config_is_one_json_line_with_ok_false(monkeypatch, tmp_path, capsys):
    """A present-but-wrong config is an error -- never a silent fallback.

    And it reaches the orchestrator the way every other failure does: exit 0,
    one JSON line, `ok: false`, `error` starting with `config_error:` and
    carrying the underlying reason. Not `dispatch_crashed:` -- nothing
    crashed, an operator wrote a wrong value -- and never a traceback or
    exit 1.
    """
    root = tmp_path / "repo"
    _write_config(root, '[default]\ndirection = "links"\n')
    monkeypatch.setattr("lean_herdr.dispatch.canonical_root", lambda *a, **kw: root)

    code = main(
        ["builder", "--kind", "claude", "--model", "sonnet",
         "--role-file", "roles/builder.md"]
    )

    assert code == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1
    result = json.loads(lines[0])
    assert result["ok"] is False
    assert result["error"].startswith("config_error:"), result["error"]
    assert "direction" in result["error"], result["error"]


def test_a_broken_config_is_a_config_error_in_await_mode_too(
    monkeypatch, tmp_path, capsys
):
    """`--await` reads the same config through the same code path -- a wrong
    file must not wear the `dispatch_crashed:` label there either."""
    root = tmp_path / "repo"
    _write_config(root, '[default]\ndirection = "links"\n')
    monkeypatch.setattr("lean_herdr.dispatch.canonical_root", lambda *a, **kw: root)

    code = main(["builder", "--kind", "claude", "--await", "--task-id", "T1"])

    assert code == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1
    result = json.loads(lines[0])
    assert result["ok"] is False
    assert result["error"].startswith("config_error:"), result["error"]
    assert "direction" in result["error"], result["error"]


def test_a_usage_error_still_wins_over_a_broken_config(monkeypatch, tmp_path, capsys):
    """Ordering must not shift: missing flags are validated BEFORE the config
    is even loaded, so a broken config never masks a usage error."""
    root = tmp_path / "repo"
    _write_config(root, '[default]\ndirection = "links"\n')
    monkeypatch.setattr("lean_herdr.dispatch.canonical_root", lambda *a, **kw: root)

    code = main(["builder", "--kind", "claude"])  # missing --model / --role-file

    assert code == 0
    result = json.loads(capsys.readouterr().out.strip())
    assert result["ok"] is False
    assert result["error"].startswith("usage_error:"), result["error"]


def test_a_worktree_dispatch_starts_the_pane_in_the_worktree(world, monkeypatch):
    h_proc, _ = world
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
    result = run_dispatch(world, reg=registry(), request=req(worktree="feat/auth"))
    assert result["ok"] is True
    assert h_proc.called_with("--cwd", "/repo.feat-auth"), "the worker lives in the worktree"
    start = next(c for c in h_proc.calls if c[1:3] == ["agent", "start"])
    assert "builder-feat-auth" in start


def test_a_worktree_dispatch_splits_a_pane_of_that_workspace(world):
    """Otherwise the worker would sit in the orchestrator workspace and survive teardown."""
    h_proc, _ = world
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
    run_dispatch(world, reg=registry(), request=req(worktree="feat/auth"))
    split = next(c for c in h_proc.calls if c[1:3] == ["pane", "split"])
    assert "--pane" in split and "w2:p1" in split
    assert "--current" not in split


def test_a_worktree_without_an_anchor_pane_aborts(world):
    h_proc, _ = world
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
    result = run_dispatch(world, reg=registry(), request=req(worktree="feat/auth"))
    assert result["ok"] is False and result["error"] == "no_anchor_pane"


def test_a_missing_worktrunk_reports_worktrunk_missing(world, monkeypatch):
    monkeypatch.setattr("lean_herdr.worktree.shutil.which", lambda _b: None)
    h_proc, _ = world
    h_proc.replies = {
        ("worktree", "list"): {"result": {"source": {"repo_root": "/repo"}, "worktrees": []}},
    }
    result = run_dispatch(world, reg=registry(), request=req(worktree="feat/new"))
    assert result["error"] == "worktrunk_missing"
