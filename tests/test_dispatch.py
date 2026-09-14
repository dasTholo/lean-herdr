import json
from itertools import pairwise
from pathlib import Path

import pytest

from lean_herdr import dispatch as dispatch_module
from lean_herdr.dispatch import (
    AGENT_ENV,
    AGENT_READY_TIMEOUT_S,
    DispatchRequest,
    agent_args,
    agent_name,
    dispatch,
    main,
    profile_for,
)
from lean_herdr.herdr import FIRST_START_TIMEOUT_MS, Herdr, timeout_ms_for
from lean_herdr.report import resolve_agent
from lean_herdr.settings import (
    OVERLAY_PATH,
    SETTINGS_PATH,
    RoleSettings,
    claude_settings_path,
    read_settings,
    role_prompt_path,
    settings_for,
)
from tests.doubles import FakeProc, agent_started, which_stub, write_role_fixture

ROOT = Path("/repo")
AGENT_ID = "mcp-2018183-70c877bf"

#: A start that WORKED. Every fixture reaching `agent start` owes one: an
#: unanswered ("agent", "start") falls back to FakeProc's empty default, and
#: that is exactly what a refusal leaves behind -- dispatch() would report
#: `agent_start_failed` and never reach the wait these tests are about. Only
#: its truthiness is read (the pane comes from the split, not from here), so
#: one canned reply serves every test in the file.
STARTED = {("agent", "start"): agent_started("builder", "w1:p6", kind="claude")}


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
    h_proc.replies = {
        **STARTED,
        ("pane", "split"): {"result": {"pane": {"pane_id": "w1:p6"}}},
    }
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
    prompt = ROOT / ".lean-ctx" / "lean-herdr" / "roles" / "builder.md"
    args = agent_args("claude", "sonnet", prompt, "builder", root=ROOT)
    assert args == [
        "--model",
        "sonnet",
        "--append-system-prompt-file",
        "/repo/.lean-ctx/lean-herdr/roles/builder.md",
        "--settings",
        "/repo/.lean-ctx/lean-herdr/claude/builder.json",
    ]
    assert not any("\n" in a for a in args), "Herdr rejects multi-line arguments (H2)"


def test_opencode_is_told_the_role_not_the_prompt_files_stem():
    """An `--role-file` override changes the prompt, never the agent opencode resolves."""
    args = agent_args("opencode", "m", Path("/elsewhere/strict.md"), "reviewer", root=ROOT)
    assert args == ["--model", "m", "--agent", "reviewer"]


def test_build_mode_returns_pane_and_agent_id_and_creates_nothing(world):
    """The build mode is finished the moment the agent_id is resolved."""
    h_proc, _ = world
    result = run_dispatch(world, reg=registry())
    assert result == {"ok": True, "pane": "w1:p6", "agent_id": AGENT_ID, "agent": "builder"}
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
        **STARTED,
        ("pane", "split"): {"result": {"pane": {"pane_id": "w2:p2"}}},
        ("pane", "list"): {"result": {"panes": [{"pane_id": "w2:p1"}]}},
        ("worktree", "list"): {
            "result": {
                "source": {"repo_root": "/repo"},
                "worktrees": [
                    {"branch": "feat/auth", "path": "/repo.feat-auth", "open_workspace_id": "w2"}
                ],
            }
        },
    }
    result = run_dispatch(world, reg=registry(), request=req(worktree="feat/auth"))
    assert result["agent"] == "builder-feat-auth"
    split = next(c for c in h_proc.calls if c[1:3] == ["pane", "split"])
    assert "LEAN_HERDR_AGENT=builder-feat-auth" in " ".join(split)


def test_the_worker_resolves_its_name_out_of_the_env_the_pane_was_given(world):
    """The two halves of the LEAN_HERDR_AGENT contract, tied together.

    `report.AGENT_ENV` used to be a second, independent spelling of the
    variable dispatch.py writes here. Renaming that copy left the whole
    suite green while every dispatched order ran into the void: the pane
    carried one variable, the worker read another, `next` answered "no open
    order" and the wait mode reported `no_reply` -- no error anywhere. The
    pane's OWN `--env` pairs go into the worker's resolver here, so a drift
    between the two sides cannot stay green.
    """
    h_proc, _ = world
    h_proc.replies = {
        **STARTED,
        ("pane", "split"): {"result": {"pane": {"pane_id": "w2:p2"}}},
        ("pane", "list"): {"result": {"panes": [{"pane_id": "w2:p1"}]}},
        ("worktree", "list"): {
            "result": {
                "source": {"repo_root": "/repo"},
                "worktrees": [
                    {"branch": "feat/auth", "path": "/repo.feat-auth", "open_workspace_id": "w2"}
                ],
            }
        },
    }
    result = run_dispatch(world, reg=registry(), request=req(worktree="feat/auth"))
    split = next(c for c in h_proc.calls if c[1:3] == ["pane", "split"])
    env = dict(pair.split("=", 1) for flag, pair in pairwise(split) if flag == "--env")
    assert env[AGENT_ENV] == "builder-feat-auth"
    assert resolve_agent(root=ROOT, env=env) == result["agent"] == "builder-feat-auth"


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
    run_dispatch(world, reg=registry(), settings=RoleSettings(direction="down", ratio=0.3))
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

    run_dispatch(world, reg=registry(), settings=RoleSettings(ready_timeout_s=7.5), waiter=spy)
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
    """Global constraint: no `.lean-ctx/lean-herdr/config.toml` -- byte-identical.

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
        "herdr",
        "pane",
        "split",
        "--current",
        "--direction",
        "right",
        "--cwd",
        "/repo",
        "--no-focus",
        "--env",
        "LEAN_CTX_TOOL_PROFILE=standard",
        "--env",
        "LEAN_CTX_ROLE=builder",
        "--env",
        "LEAN_HERDR_AGENT=builder",
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


def test_the_build_mode_reads_the_registry_the_data_dir_points_at(monkeypatch, tmp_path):
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
        ("agent", "list"): {"result": {"agents": [{"name": "builder", "pane_id": "w1:p6"}]}},
        ("pane", "process-info"): {"result": {"process_info": {"shell_pid": 4242}}},
    }

    result = dispatch(req(), herdr=Herdr(runner=h_proc), root=ROOT)

    assert result == {"ok": True, "pane": "w1:p6", "agent_id": AGENT_ID, "agent": "builder"}


def test_a_refused_agent_start_is_reported_instead_of_waited_out(world):
    """A refused `agent start` is named at once -- and the waiter never runs.

    Herdr answers `agent_pane_busy` after 0.0 s when the pane split a moment
    ago has not reached its interactive shell prompt. Discarding that reply
    cost the full `ready_timeout_s` and then reported `no_agent_id`, which
    names neither the cause nor the moment.
    """
    h_proc, _ = world
    h_proc.replies = {
        ("pane", "split"): {"result": {"pane": {"pane_id": "w1:p6"}}},
        # What is left of the refusal by the time it reaches dispatch().
        ("agent", "start"): {},
    }
    result = run_dispatch(
        world,
        reg=registry(),
        waiter=lambda *a, **kw: pytest.fail("the waiter must not run after a refused agent start"),
    )
    assert result == {
        "ok": False,
        "pane": "w1:p6",
        "agent_id": None,
        "error": "agent_start_failed",
    }


def test_a_worker_start_goes_through_the_same_helper(world, monkeypatch):
    """`dispatch` must not grow a second start path.

    A worktree is a NEW project to opencode, so a worker meets the very
    same first-bootstrap hang the orchestrator does. One helper, one
    retry, one pair of error names.
    """
    _h_proc, _ = world
    seen: dict[str, object] = {}
    real = dispatch_module.start_agent

    def spy(*a, **kw):
        seen.update(kw)
        return real(*a, **kw)

    monkeypatch.setattr(dispatch_module, "start_agent", spy)
    run_dispatch(world, reg=registry())
    assert seen["first_timeout_ms"] == FIRST_START_TIMEOUT_MS
    assert seen["retry_timeout_ms"] == timeout_ms_for(AGENT_READY_TIMEOUT_S)


def test_a_hung_worker_start_is_opencode_stuck(world, monkeypatch):
    _h_proc, _ = world
    monkeypatch.setattr(
        dispatch_module,
        "start_agent",
        lambda *a, **kw: {"ok": False, "error": "opencode_stuck"},
    )
    result = run_dispatch(
        world,
        reg=registry(),
        waiter=lambda *a, **kw: pytest.fail("no waiter after a stuck start"),
    )
    assert result == {
        "ok": False,
        "pane": "w1:p6",
        "agent_id": None,
        "error": "opencode_stuck",
    }


def test_without_an_agent_id_the_script_reports_an_error(world):
    assert run_dispatch(world, reg=registry(), agent_id=None)["error"] == "no_agent_id"


def test_main_writes_one_json_line_and_exits_0(capsys, monkeypatch):
    monkeypatch.setattr(
        "lean_herdr.dispatch.canonical_root",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("no repo")),
    )
    code = main(
        ["builder", "--kind", "claude", "--model", "sonnet", "--role-file", "roles/builder.md"]
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
    anchored on `$PWD` the file vanishes as soon as `lean-herdr dispatch` runs
    from a subdirectory or a worktree -- which is why this test runs from a
    foreign cwd. And a wait mode with different settings would ring an agent
    under a different name than the build mode started.
    """
    root = tmp_path / "repo"
    _write_config(root, '[default]\nname_template = "{branch}.{role}"\n')
    write_role_fixture(root, "builder")
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
    main([*base, "--model", "sonnet"])
    main([*base, "--await", "--task-id", "T1"])

    assert [s.name_template for s in seen] == ["{branch}.{role}"] * 2, (
        "the config lives in the repo root, not in $PWD"
    )
    assert seen[0] == seen[1], "both modes must name the same agent"
    assert agent_name("builder", "feat/auth", settings=seen[0]) == "feat-auth.builder"


def test_main_reads_config_toml_exactly_once_per_call(monkeypatch, tmp_path, capsys):
    """The read COUNT, which its neighbour above does not check.

    `test_main_loads_the_config_once_for_both_modes` compares the settings
    the two modes see; it would stay green against an implementation that
    read the file three times and agreed with itself every time. The
    constraint is about the count, and `dispatch.main()`'s own comment
    names a test as its guard -- so one has to actually count.

    The overlay is a SECOND file, and only the wait mode reads it -- the one
    mode whose judge uses the model it names. Both counts are held here.
    """
    root = tmp_path / "repo"
    _write_config(root, BUILDER_CONFIG)
    write_role_fixture(root, "builder")
    reads: list[str] = []
    real = dispatch_module.read_settings

    def counting(path, *args, **kwargs):
        reads.append(Path(path).name)
        return real(path, *args, **kwargs)

    monkeypatch.setattr("lean_herdr.dispatch.read_settings", counting)
    monkeypatch.setattr("lean_herdr.settings.read_settings", counting)
    _spy_dispatch(monkeypatch)

    _line([*BUILD_ARGS, "--model", "opus"], root, monkeypatch, capsys)

    assert reads.count("config.toml") == 1, reads
    assert reads.count("models.auto.toml") == 0, "the build mode has no use for it"

    reads.clear()
    _line(["builder", "--await", "--task-id", "T1"], root, monkeypatch, capsys)

    assert reads.count("config.toml") == 1, reads
    assert reads.count("models.auto.toml") == 1, "the wait mode reads it for the judge"


def _no_launch(monkeypatch):
    """Make the real launch path unreachable, loudly.

    A config-error test proves that main() STOPS before doing anything.
    Proving it by letting the launch path stand and trusting the guard is
    a trap: on 2026-09-03 a guard was momentarily removed to check that a
    test bites, main() ran on, and `dispatch()` split a real pane in the
    operator's live Herdr workspace and started a real `claude` there.
    A test may never be one edit away from that.
    """

    def stop(*_a, **_kw):
        raise AssertionError("main() reached the launch path past a config error")

    monkeypatch.setattr("lean_herdr.dispatch.dispatch", stop)
    monkeypatch.setattr("lean_herdr.dispatch.await_task", stop)


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
    _no_launch(monkeypatch)

    code = main(
        ["builder", "--kind", "claude", "--model", "sonnet", "--role-file", "roles/builder.md"]
    )

    assert code == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1
    result = json.loads(lines[0])
    assert result["ok"] is False
    assert result["error"].startswith("config_error:"), result["error"]
    assert "direction" in result["error"], result["error"]


def test_a_broken_config_is_a_config_error_in_await_mode_too(monkeypatch, tmp_path, capsys):
    """`--await` reads the same config through the same code path -- a wrong
    file must not wear the `dispatch_crashed:` label there either."""
    root = tmp_path / "repo"
    _write_config(root, '[default]\ndirection = "links"\n')
    monkeypatch.setattr("lean_herdr.dispatch.canonical_root", lambda *a, **kw: root)
    _no_launch(monkeypatch)

    code = main(["builder", "--kind", "claude", "--await", "--task-id", "T1"])

    assert code == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1
    result = json.loads(lines[0])
    assert result["ok"] is False
    assert result["error"].startswith("config_error:"), result["error"]
    assert "direction" in result["error"], result["error"]


def test_a_broken_llm_block_is_a_config_error_too(monkeypatch, tmp_path, capsys):
    """`[llm]` is validated in main() beside `[default]`, for EVERY command.

    The commit generator swallows a broken file -- there a wrong value must
    not cost a commit. Here it has a reader, so it stays loud, and the
    operator learns of the typo on the next dispatch rather than through a
    pre-review that is silently `skipped` forever.
    """
    root = tmp_path / "repo"
    _write_config(root, '[llm]\neffort = "enormous"\n')
    monkeypatch.setattr("lean_herdr.dispatch.canonical_root", lambda *a, **kw: root)
    _no_launch(monkeypatch)

    code = main(
        ["builder", "--kind", "claude", "--model", "sonnet", "--role-file", "roles/builder.md"]
    )

    assert code == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1
    result = json.loads(lines[0])
    assert result["ok"] is False
    assert result["error"].startswith("config_error:"), result["error"]
    assert "effort" in result["error"], result["error"]


def test_a_broken_routing_line_fails_a_call_by_role_name_too(monkeypatch, tmp_path, capsys):
    """`[routing]` is checked on load, so the builder call meets the broken line."""
    root = tmp_path / "repo"
    _write_config(root, '[routing]\nrename = "Refactorer"\n')
    monkeypatch.setattr("lean_herdr.dispatch.canonical_root", lambda *a, **kw: root)
    _no_launch(monkeypatch)

    assert main(["builder", "--kind", "claude", "--model", "sonnet"]) == 0

    result = json.loads(capsys.readouterr().out.strip())
    assert result["ok"] is False
    assert result["error"].startswith("config_error: routing.rename: "), result["error"]


def test_a_broken_overlay_is_a_config_error_too(monkeypatch, tmp_path, capsys):
    """`models.auto.toml` is read in the wait mode through the SAME function as in
    llm.file_settings() -- and here, unlike there, it has a reader.

    The generator swallows a broken overlay, because a machine-written file
    must not cost a commit. The orchestrator gets told instead, so the
    operator learns the daily check wrote nonsense on the next dispatch.
    """
    root = tmp_path / "repo"
    _write_config(root, "")
    (root / OVERLAY_PATH).write_text('[llm]\neffort = "enormous"\n', encoding="utf-8")
    monkeypatch.setattr("lean_herdr.dispatch.canonical_root", lambda *a, **kw: root)
    _no_launch(monkeypatch)

    code = main(["builder", "--kind", "claude", "--await", "--task-id", "T1"])

    assert code == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1
    result = json.loads(lines[0])
    assert result["ok"] is False
    assert result["error"].startswith("config_error:"), result["error"]
    assert "effort" in result["error"], result["error"]
    assert "lean-herdr models apply" in result["error"], result["error"]


def test_the_overlay_reaches_dispatch_under_config_toml(monkeypatch, tmp_path):
    """The layering llm.file_settings() applies, out of the same function.

    Read the overlay in only one of the two and the commit generator and
    the pre-review judge would run on different models the moment one
    exists. The proof is `model`, the one key the overlay gives, under a
    config.toml that is silent on it.
    """
    root = tmp_path / "repo"
    _write_config(root, '[llm]\nprereview_model = "by/hand"\n')
    (root / OVERLAY_PATH).write_text('[llm]\nmodel = "auto/pick"\n', encoding="utf-8")
    monkeypatch.setattr("lean_herdr.dispatch.canonical_root", lambda *a, **kw: root)
    seen = []

    def spy(_request, **kwargs):
        seen.append(kwargs["llm_cfg"])
        return {"ok": True}

    monkeypatch.setattr("lean_herdr.dispatch.dispatch", spy)
    monkeypatch.setattr("lean_herdr.dispatch.await_task", spy)

    main(["builder", "--kind", "claude", "--await", "--task-id", "T1"])

    assert seen[0].model == "auto/pick"
    assert seen[0].prereview_model == "by/hand"


@pytest.mark.parametrize(
    ("argv", "seam"),
    [
        (["order", "--to", "builder-feat", "--message", "build it"], "create_order"),
        (["answer", "--task-id", "o-1", "--message", "yes"], "answer_order"),
        (["cancel", "--task-id", "o-1", "--message", "no longer"], "cancel_order"),
    ],
    ids=["order", "answer", "cancel"],
)
def test_the_log_commands_do_not_read_the_overlay(monkeypatch, tmp_path, capsys, argv, seam):
    """They write into the log and never ask a model, so the overlay has nothing to say.

    Reading it anyway turned a broken machine-written file into a refused order.
    """
    root = tmp_path / "repo"
    _write_config(root, "")
    (root / OVERLAY_PATH).write_text("[llm]\nmodel = 5\n", encoding="utf-8")
    monkeypatch.setattr(f"lean_herdr.dispatch.{seam}", lambda *a, **kw: {"ok": True})
    assert _line(argv, root, monkeypatch, capsys) == {"ok": True}


def test_a_broken_config_wins_over_a_usage_error(monkeypatch, tmp_path, capsys):
    """Ordering DID shift, and this test is where that is written down.

    The config is read before missing_flags() now, because it can satisfy
    --model and --kind; reading it later would reject a call the file
    answers. So a config this process cannot read reaches the caller even
    when the command line is also wrong. That is the bigger of the two
    complaints, and the only one that would otherwise be silent -- the
    usage error is still there the next time the operator types it.
    """
    root = tmp_path / "repo"
    _write_config(root, '[default]\ndirection = "links"\n')
    monkeypatch.setattr("lean_herdr.dispatch.canonical_root", lambda *a, **kw: root)

    code = main(["builder", "--kind", "claude"])  # also missing --model

    assert code == 0
    result = json.loads(capsys.readouterr().out.strip())
    assert result["ok"] is False
    assert result["error"].startswith("config_error:"), result["error"]


#: A file that answers both duty flags on its own -- no --kind, no --model
#: on the command line, and the build still runs.
BUILDER_CONFIG = '[roles.builder]\nkind = "claude"\nmodel = "sonnet"\n'

#: Everything a builder build needs BESIDE the two flags under test -- the prompt
#: now comes with the role.
BUILD_ARGS = ["builder"]

#: Same model under both roles -- legal, and exactly what earns the warning.
SHARED_MODEL_CONFIG = (
    '[roles.builder]\nkind = "claude"\nmodel = "sonnet"\n'
    '[roles.reviewer]\nkind = "claude"\nmodel = "sonnet"\n'
)


def _line(argv, root, monkeypatch, capsys):
    """main(argv) against a config at `root` -- the one JSON line, parsed."""
    # The modes reached from here that are NOT spied write a real order log.
    # Kept inside tmp_path the way every other test in this project that
    # touches the store does -- otherwise it lands in the operator's own
    # lean-ctx data directory and the next run inherits it.
    monkeypatch.setenv("LEAN_CTX_DATA_DIR", str(root.parent / "data"))
    monkeypatch.setattr("lean_herdr.dispatch.canonical_root", lambda *a, **kw: root)
    assert main(argv) == 0
    return json.loads(capsys.readouterr().out.strip())


def _spy_dispatch(monkeypatch) -> list[DispatchRequest]:
    """Catch the request main() builds, and launch nothing while doing it."""
    seen: list[DispatchRequest] = []

    def spy(request, **_kwargs):
        seen.append(request)
        return {"ok": True, "pane": "w1:p6", "agent_id": AGENT_ID}

    monkeypatch.setattr("lean_herdr.dispatch.dispatch", spy)
    monkeypatch.setattr("lean_herdr.dispatch.await_task", spy)
    return seen


def test_only_the_orchestrator_has_a_kind_without_a_file(monkeypatch, tmp_path, capsys):
    """`settings.KIND_BY_ROLE` reaches `--kind` too, and only for one role.

    `settings_for()` seeds `kind` from that table, so `settings.kind` is
    already `"opencode"` for the orchestrator with NO config file at all
    -- and the fill in `main()` therefore satisfies `--kind` for it. The
    builder gets `""` from the same call and is still refused. That is the
    asymmetry the table exists for, spelled out here so nobody later reads
    it as a leak: workers say their runtime or `dispatch` refuses, and the
    flag that costs money when nobody names it -- `--model` -- has no such
    table and is refused for BOTH.
    """
    root = tmp_path / "repo"
    _write_config(root, "")
    write_role_fixture(root, "orchestrator", "builder")
    _spy_dispatch(monkeypatch)

    orch = _line(["orchestrator", "--model", "x"], root, monkeypatch, capsys)
    work = _line([*BUILD_ARGS, "--model", "x"], root, monkeypatch, capsys)

    assert orch["ok"] is True, orch
    assert work["ok"] is False
    assert "--kind is required" in work["error"], work


def test_the_orchestrators_built_in_kind_does_not_excuse_a_model(monkeypatch, tmp_path, capsys):
    """The one built-in stops at `kind`. `--model` is still a duty flag."""
    root = tmp_path / "repo"
    _write_config(root, "")
    _spy_dispatch(monkeypatch)

    got = _line(["orchestrator"], root, monkeypatch, capsys)

    assert got["ok"] is False
    assert got["error"].startswith("usage_error: build mode needs --model"), got


def test_the_model_flag_beats_the_file(monkeypatch, tmp_path, capsys):
    """CLI > file, the precedence settings.py already promises."""
    root = tmp_path / "repo"
    _write_config(root, BUILDER_CONFIG)
    write_role_fixture(root, "builder")
    seen = _spy_dispatch(monkeypatch)

    _line([*BUILD_ARGS, "--model", "opus"], root, monkeypatch, capsys)

    assert [r.model for r in seen] == ["opus"]


def test_the_config_fills_a_missing_model_flag(monkeypatch, tmp_path, capsys):
    """No --model typed, `[roles.builder].model` set: the value reaches
    dispatch() in the request, and the call is not a usage error."""
    root = tmp_path / "repo"
    _write_config(root, BUILDER_CONFIG)
    write_role_fixture(root, "builder")
    seen = _spy_dispatch(monkeypatch)

    got = _line(BUILD_ARGS, root, monkeypatch, capsys)

    assert got["ok"] is True, got
    assert [r.model for r in seen] == ["sonnet"]


def test_the_kind_flag_beats_the_file(monkeypatch, tmp_path, capsys):
    root = tmp_path / "repo"
    _write_config(root, BUILDER_CONFIG)
    write_role_fixture(root, "builder")
    seen = _spy_dispatch(monkeypatch)

    _line([*BUILD_ARGS, "--kind", "opencode"], root, monkeypatch, capsys)

    assert [r.kind for r in seen] == ["opencode"]


def test_the_config_fills_a_missing_kind_flag(monkeypatch, tmp_path, capsys):
    """Workers have no built-in kind, so the file is the only other source."""
    root = tmp_path / "repo"
    _write_config(root, BUILDER_CONFIG)
    write_role_fixture(root, "builder")
    seen = _spy_dispatch(monkeypatch)

    got = _line(BUILD_ARGS, root, monkeypatch, capsys)

    assert got["ok"] is True, got
    assert [r.kind for r in seen] == ["claude"]


@pytest.mark.parametrize(
    ("kind", "drop", "expected"),
    [
        pytest.param("claude", "prompt", "config_error: no role prompt at ", id="prompt"),
        pytest.param("opencode", "block", "config_error: opencode.jsonc in ", id="block"),
        pytest.param("claude", "claude file", "config_error: no claude settings at ", id="claude"),
    ],
)
def test_a_role_that_cannot_run_is_refused_before_any_pane(
    monkeypatch, tmp_path, capsys, kind, drop, expected
):
    """All three are checked before `pane split`, and none of them starts anything.

    Herdr is a recording fake, not a stop sign: without the check dispatch() would
    run on, and its calls would show up in `proc.calls`.
    """
    root = tmp_path / "repo"
    _write_config(root, "")
    write_role_fixture(root, "builder")
    if drop == "prompt":
        role_prompt_path(root, "builder").unlink()
    elif drop == "claude file":
        claude_settings_path(root, "builder").unlink()
    else:
        (root / "opencode.jsonc").write_text('{"agent": {"reviewer": {}}}\n', encoding="utf-8")
    monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
    proc = FakeProc()
    monkeypatch.setattr("lean_herdr.dispatch.Herdr", lambda *a, **kw: Herdr(runner=proc))

    got = _line(["builder", "--kind", kind, "--model", "sonnet"], root, monkeypatch, capsys)

    assert got["ok"] is False
    assert got["error"].startswith(expected), got
    assert proc.calls == [], proc.flat()


def test_a_relative_role_file_is_resolved_against_the_repo_root(monkeypatch, tmp_path, capsys):
    """Handed on as typed, it would resolve in the pane's worktree, which may lack it."""
    root = tmp_path / "repo"
    _write_config(root, BUILDER_CONFIG)
    write_role_fixture(root, "builder")
    (root / "prompts").mkdir()
    (root / "prompts" / "strict.md").write_text("# Role: builder\n", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    seen = _spy_dispatch(monkeypatch)

    got = _line([*BUILD_ARGS, "--role-file", "prompts/strict.md"], root, monkeypatch, capsys)

    assert got["ok"] is True, got
    assert [r.role_file for r in seen] == [root / "prompts" / "strict.md"]


def test_without_a_role_file_the_role_brings_its_own_prompt(monkeypatch, tmp_path, capsys):
    root = tmp_path / "repo"
    _write_config(root, BUILDER_CONFIG)
    write_role_fixture(root, "builder")
    seen = _spy_dispatch(monkeypatch)

    got = _line(BUILD_ARGS, root, monkeypatch, capsys)

    assert got["ok"] is True, got
    assert got["role"] == "builder", got
    assert [r.role_file for r in seen] == [role_prompt_path(root, "builder")]


def test_neither_flag_nor_file_is_still_a_usage_error(monkeypatch, tmp_path, capsys):
    """The duty stays a duty.

    A worker that quietly builds on its runtime's default model costs real
    money and nobody sees it -- so an unanswered --model is refused, not
    defaulted.
    """
    root = tmp_path / "repo"
    _write_config(root, '[roles.builder]\nkind = "claude"\n')
    _no_launch(monkeypatch)

    got = _line(BUILD_ARGS, root, monkeypatch, capsys)

    assert got["ok"] is False
    assert got["error"] == "usage_error: build mode needs --model", got


def test_await_does_not_take_a_model_from_the_file(monkeypatch, tmp_path, capsys):
    """`--model` is a STRAY flag under --await, so the file must not set it.

    Filling it would turn a valid wait call into
    `usage_error: --await does not take --model` -- with a value the wait
    mode never reads in the first place.
    """
    root = tmp_path / "repo"
    _write_config(root, BUILDER_CONFIG)

    got = _line(["builder", "--await", "--task-id", "o-1"], root, monkeypatch, capsys)

    assert "usage_error" not in str(got.get("error", "")), got


def test_a_log_command_takes_no_kind_from_the_file(monkeypatch, tmp_path, capsys):
    """`order` refuses --kind as stray, so [default].kind must not reach it.

    Without the LOG_COMMANDS guard a single `[default] kind = "claude"`
    would break every `order`, `answer`, `cancel` and `remember` call in
    the project -- with a flag nobody typed.
    """
    root = tmp_path / "repo"
    _write_config(root, '[default]\nkind = "claude"\n')

    got = _line(
        ["order", "--to", "builder", "--message", "do it"],
        root,
        monkeypatch,
        capsys,
    )

    assert "does not take --kind" not in str(got.get("error", "")), got


def test_a_reviewer_build_carries_the_shared_model_warning(monkeypatch, tmp_path, capsys):
    """One model for two roles is allowed, but never silent.

    The orchestrator reads the REVIEWER's dispatch line, so that is the one
    line where the warning has a reader. `ok` is untouched.
    """
    root = tmp_path / "repo"
    _write_config(root, SHARED_MODEL_CONFIG)
    write_role_fixture(root, "reviewer")
    _spy_dispatch(monkeypatch)

    got = _line(["reviewer"], root, monkeypatch, capsys)

    assert got["ok"] is True, got
    assert len(got["warnings"]) == 1, got
    assert "blind spots" in got["warnings"][0], got


def test_a_builder_build_of_the_same_config_carries_no_warning(monkeypatch, tmp_path, capsys):
    """Same file, no reader: nothing reads the builder's line for this."""
    root = tmp_path / "repo"
    _write_config(root, SHARED_MODEL_CONFIG)
    write_role_fixture(root, "builder")
    _spy_dispatch(monkeypatch)

    got = _line(BUILD_ARGS, root, monkeypatch, capsys)

    assert got["ok"] is True, got
    assert "warnings" not in got, got


def test_a_worktree_dispatch_starts_the_pane_in_the_worktree(world, monkeypatch):
    h_proc, _ = world
    h_proc.replies = {
        **STARTED,
        ("pane", "split"): {"result": {"pane": {"pane_id": "w2:p2"}}},
        ("pane", "list"): {"result": {"panes": [{"pane_id": "w2:p1"}]}},
        ("worktree", "list"): {
            "result": {
                "source": {"repo_root": "/repo"},
                "worktrees": [
                    {"branch": "feat/auth", "path": "/repo.feat-auth", "open_workspace_id": "w2"}
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
        **STARTED,
        ("pane", "split"): {"result": {"pane": {"pane_id": "w2:p2"}}},
        ("pane", "list"): {"result": {"panes": [{"pane_id": "w2:p1"}]}},
        ("worktree", "list"): {
            "result": {
                "source": {"repo_root": "/repo"},
                "worktrees": [
                    {"branch": "feat/auth", "path": "/repo.feat-auth", "open_workspace_id": "w2"}
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
                    {"branch": "feat/auth", "path": "/repo.feat-auth", "open_workspace_id": "w2"}
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
