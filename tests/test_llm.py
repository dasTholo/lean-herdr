"""The one network call in this tree -- and not one test reaches it.

`runner` is injected everywhere; `SpyRunner` reads the curl config
while curl would be running, which is the only moment the file still
exists.
"""

import json
from pathlib import Path

import pytest

from lean_herdr import llm
from lean_herdr.settings import LlmSettings
from tests.doubles import Completed

#: Every generate() call in here passes `settings=` explicitly. Without
#: it generate() calls file_settings(), which runs `git rev-parse` and
#: reads THIS repository's own .config/lean-herdr.toml -- a unit test
#: that quietly depends on the checkout it runs in.
NO_FILE = LlmSettings()

DIFFSTAT_PROMPT = """<task>write a commit message</task>
<diffstat>
 lean_herdr/llm.py  | 42 ++++++++++
 tests/test_llm.py  | 18 +++++
 2 files changed, 60 insertions(+)
</diffstat>
<diff>...</diff>
"""


def answer(text: str) -> dict:
    return {"choices": [{"message": {"content": text}}]}


class SpyRunner:
    """Replaces subprocess.run and inspects the temp files in flight.

    The interesting facts about the call -- the key is not in argv,
    the config is 0600, both files are gone afterwards -- can only be
    checked from inside the call, because the `finally` removes them
    the moment it returns.
    """

    def __init__(self, reply=None, returncode=0, raises=None):
        self.calls: list[list[str]] = []
        self.config_texts: list[str] = []
        self.config_modes: list[int] = []
        self.bodies: list[str] = []
        self.paths: list[Path] = []
        self.timeouts: list[float | None] = []
        self.reply = reply
        self.returncode = returncode
        self.raises = raises

    def __call__(self, cmd, **kwargs):
        self.calls.append(list(cmd))
        self.timeouts.append(kwargs.get("timeout"))
        # Only a curl call carries these. The same double also stands in
        # for `wt step diff` in task 5, and reaching for --config there
        # would raise a ValueError the code under test does not catch.
        if "--config" in cmd:
            config = Path(cmd[cmd.index("--config") + 1])
            body = Path(cmd[cmd.index("--data-binary") + 1].removeprefix("@"))
            self.paths.extend((config, body))
            self.config_texts.append(config.read_text(encoding="utf-8"))
            self.config_modes.append(config.stat().st_mode & 0o777)
            self.bodies.append(body.read_text(encoding="utf-8"))
        if self.raises is not None:
            raise self.raises
        out = "" if self.reply is None else json.dumps(self.reply)
        return Completed(returncode=self.returncode, stdout=out)


class _Stdin:
    """A stdin double -- `monkeypatch.setattr(sys, "stdin", ...)`."""

    def __init__(self, text: str):
        self._text = text

    def read(self) -> str:
        return self._text


@pytest.fixture
def no_store(tmp_path):
    """An auth.json that does not exist -- the empty-machine case."""
    return tmp_path / "absent" / "auth.json"


def test_the_env_key_beats_the_opencode_store(tmp_path):
    store = tmp_path / "auth.json"
    store.write_text(json.dumps({"openrouter": {"key": "from-store"}}))
    assert llm.api_key({llm.KEY_ENV: "from-env"}, store) == "from-env"


def test_the_store_answers_when_the_env_is_empty(tmp_path):
    store = tmp_path / "auth.json"
    store.write_text(json.dumps({"openrouter": {"key": "from-store"}}))
    assert llm.api_key({}, store) == "from-store"
    assert llm.api_key({llm.KEY_ENV: "   "}, store) == "from-store"


def test_no_key_anywhere_is_none_not_a_crash(no_store):
    assert llm.api_key({}, no_store) is None


def test_a_malformed_store_is_none_not_a_crash(tmp_path):
    store = tmp_path / "auth.json"
    store.write_text("{ not json")
    assert llm.api_key({}, store) is None
    store.write_text(json.dumps({"openrouter": "a string"}))
    assert llm.api_key({}, store) is None


def test_the_key_never_reaches_argv(no_store):
    spy = SpyRunner(answer("feat(x): y"))
    llm.complete(
        "prompt", effort="minimal", runner=spy,
        env={llm.KEY_ENV: "sk-secret-42"}, auth_path=no_store,
    )
    flat = " ".join(spy.calls[0])
    assert "sk-secret-42" not in flat, flat
    assert "Bearer" not in flat, flat
    assert "sk-secret-42" in spy.config_texts[0]


def test_the_config_file_is_0600_and_gone_afterwards(no_store):
    spy = SpyRunner(answer("feat(x): y"))
    llm.complete(
        "prompt", effort="minimal", runner=spy,
        env={llm.KEY_ENV: "sk-secret-42"}, auth_path=no_store,
    )
    assert spy.config_modes == [0o600]
    for path in spy.paths:
        assert not path.exists(), f"{path} was left behind"


def test_the_body_carries_model_and_effort(no_store):
    """complete() resolves nothing -- it sends what it is handed."""
    spy = SpyRunner(answer("feat(x): y"))
    llm.complete(
        "prompt", effort="minimal", model="some/other-model", runner=spy,
        env={llm.KEY_ENV: "k"}, auth_path=no_store,
    )
    body = json.loads(spy.bodies[0])
    assert body["model"] == "some/other-model"
    assert body["reasoning"] == {"effort": "minimal"}
    assert body["messages"] == [{"role": "user", "content": "prompt"}]


def test_the_precedence_runs_flag_environment_file_constant(no_store):
    """One test for the whole chain, so a reordering cannot hide."""
    cfg = LlmSettings(model="file/model", effort="medium")
    env = {llm.KEY_ENV: "k", llm.MODEL_ENV: "env/model"}

    def sent(**kw):
        spy = SpyRunner(answer("feat(x): y"))
        llm.generate(
            "prompt", runner=spy, env=env, auth_path=no_store,
            settings=cfg, **kw,
        )
        return json.loads(spy.bodies[0])

    assert sent(model="flag/model")["model"] == "flag/model"
    assert sent()["model"] == "env/model", "the environment beats the file"
    assert sent(effort="low")["reasoning"] == {"effort": "low"}
    assert sent()["reasoning"] == {"effort": "medium"}, "the file beats the constant"


def test_without_a_file_and_without_an_environment_the_constants_win(no_store):
    spy = SpyRunner(answer("feat(x): y"))
    llm.generate(
        "prompt", runner=spy, env={llm.KEY_ENV: "k"}, auth_path=no_store,
        settings=LlmSettings(),
    )
    body = json.loads(spy.bodies[0])
    assert body["model"] == llm.DEFAULT_MODEL
    assert body["reasoning"] == {"effort": llm.GENERATE_EFFORT}


def test_the_first_non_empty_candidate_wins():
    assert llm._first(None, "", "third", fallback="f") == "third"
    assert llm._first(None, "", fallback="f") == "f"


def test_a_broken_settings_file_costs_the_defaults_not_the_commit(tmp_path, capsys):
    """The hard invariant, at the one place that could break it."""
    (tmp_path / ".config").mkdir()
    (tmp_path / ".config" / "lean-herdr.toml").write_text(
        "[llm]\nmodel = 5\n", encoding="utf-8"
    )
    assert llm.file_settings(tmp_path) == LlmSettings()
    assert "ignoring the settings file" in capsys.readouterr().err


def test_a_directory_that_is_no_repository_costs_the_defaults(tmp_path, capsys):
    assert llm.file_settings(cwd=tmp_path) == LlmSettings()
    assert "ignoring the settings file" in capsys.readouterr().err


def test_a_missing_file_is_the_normal_case_and_says_nothing(tmp_path, capsys):
    assert llm.file_settings(tmp_path) == LlmSettings()
    assert capsys.readouterr().err == "", "an absent file is not a complaint"


def test_the_file_is_read_relative_to_the_repo_root(tmp_path):
    (tmp_path / ".config").mkdir()
    (tmp_path / ".config" / "lean-herdr.toml").write_text(
        '[llm]\nmodel = "from/file"\nprereview_effort = "medium"\n',
        encoding="utf-8",
    )
    got = llm.file_settings(tmp_path)
    assert got.model == "from/file"
    assert got.prereview_effort == "medium"
    assert got.effort == "", "an unset key stays the empty string"


def test_a_fenced_answer_loses_its_fence(no_store):
    spy = SpyRunner(answer("```\nfix(parser): add null check\n```"))
    got = llm.complete(
        "prompt", effort="minimal", runner=spy,
        env={llm.KEY_ENV: "k"}, auth_path=no_store,
    )
    assert got == "fix(parser): add null check"


def test_the_fallback_reads_the_files_out_of_the_diffstat():
    assert llm.fallback_message(DIFFSTAT_PROMPT) == (
        "Changes to lean_herdr/llm.py, tests/test_llm.py"
    )


def test_the_fallback_caps_the_file_list():
    stat = "\n".join(f" f{n}.py | 1 +" for n in range(6))
    prompt = f"<diffstat>\n{stat}\n</diffstat>"
    assert llm.fallback_message(prompt) == (
        "Changes to f0.py, f1.py, f2.py and 3 more"
    )


def test_the_fallback_survives_a_prompt_with_no_diffstat():
    assert llm.fallback_message("nothing useful here") == (
        "Changes to the working tree"
    )


@pytest.mark.parametrize(
    "spy",
    [
        SpyRunner(answer("x"), returncode=7),
        SpyRunner(reply={"error": {"message": "rate limited"}}),
        SpyRunner(answer("   ")),
        SpyRunner(raises=OSError("curl is not installed")),
    ],
    ids=["curl-failed", "error-body", "empty-answer", "no-curl"],
)
def test_generate_returns_the_fallback_for_every_failure(spy, no_store):
    got = llm.generate(
        DIFFSTAT_PROMPT, runner=spy, settings=NO_FILE,
        env={llm.KEY_ENV: "k"}, auth_path=no_store,
    )
    assert got == "Changes to lean_herdr/llm.py, tests/test_llm.py"


def test_generate_without_a_key_never_calls_curl(no_store):
    spy = SpyRunner(answer("feat(x): y"))
    got = llm.generate(
        DIFFSTAT_PROMPT, runner=spy, env={}, auth_path=no_store, settings=NO_FILE
    )
    assert spy.calls == []
    assert got.startswith("Changes to ")


def test_a_prompt_over_the_cap_is_never_sent(no_store):
    spy = SpyRunner(answer("feat(x): y"))
    huge = "x" * (llm.MAX_PROMPT_BYTES + 1)
    assert llm.complete(
        huge, effort="minimal", runner=spy,
        env={llm.KEY_ENV: "k"}, auth_path=no_store,
    ) is None
    assert spy.calls == [], "a runaway diff must not cost money"


def test_a_key_that_would_break_the_config_line_is_refused(no_store):
    spy = SpyRunner(answer("feat(x): y"))
    assert llm.complete(
        "prompt", effort="minimal", runner=spy,
        env={llm.KEY_ENV: 'k"\nheader = "X-Evil: 1'}, auth_path=no_store,
    ) is None
    assert spy.calls == []


def test_generate_passes_the_measured_effort_by_default(no_store):
    spy = SpyRunner(answer("feat(x): y"))
    llm.generate(
        "prompt", runner=spy, env={llm.KEY_ENV: "k"}, auth_path=no_store,
        settings=NO_FILE,
    )
    assert json.loads(spy.bodies[0])["reasoning"] == {"effort": "minimal"}


def test_generate_writes_the_message_and_exits_zero(monkeypatch, capsys, tmp_path):
    store = tmp_path / "auth.json"
    store.write_text(json.dumps({"openrouter": {"key": "k"}}))
    monkeypatch.setattr(llm, "AUTH_PATH", store)
    # Empty, so the store is what decides -- on a machine that exports
    # $OPENROUTER_API_KEY the file would otherwise never be consulted.
    monkeypatch.setattr(llm.os, "environ", {})
    monkeypatch.setattr(llm.sys, "stdin", _Stdin(DIFFSTAT_PROMPT))
    monkeypatch.setattr(
        llm, "generate", lambda *a, **kw: "feat(llm): add the generator"
    )
    assert llm.main(["generate"]) == 0
    captured = capsys.readouterr()
    assert captured.out == "feat(llm): add the generator\n"
    assert captured.err == "", "a key in the store means no missing-key notice"


def test_the_flags_reach_generate(monkeypatch, tmp_path):
    """The whole job of this CLI: three flags onto three keyword arguments."""
    monkeypatch.setattr(llm, "AUTH_PATH", tmp_path / "absent.json")
    monkeypatch.setattr(llm.os, "environ", {llm.KEY_ENV: "k"})
    monkeypatch.setattr(llm.sys, "stdin", _Stdin(DIFFSTAT_PROMPT))
    seen: dict[str, object] = {}

    def spy(prompt, **kwargs):
        seen["prompt"] = prompt
        seen.update(kwargs)
        return "feat(x): y"

    monkeypatch.setattr(llm, "generate", spy)
    argv = ["generate", "--model", "vendor/m", "--effort", "high", "--timeout", "5"]
    assert llm.main(argv) == 0
    assert seen == {
        "prompt": DIFFSTAT_PROMPT,
        "model": "vendor/m",
        "effort": "high",
        "timeout_s": 5.0,
    }


def test_the_absent_flags_stay_none_so_generate_owns_the_precedence(
    monkeypatch, tmp_path
):
    """A constant passed from here would put the CLI's silence above the file."""
    monkeypatch.setattr(llm, "AUTH_PATH", tmp_path / "absent.json")
    monkeypatch.setattr(llm.os, "environ", {llm.KEY_ENV: "k"})
    monkeypatch.setattr(llm.sys, "stdin", _Stdin(DIFFSTAT_PROMPT))
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        llm, "generate", lambda prompt, **kw: (seen.update(kw), "feat(x): y")[1]
    )
    assert llm.main(["generate"]) == 0
    assert seen["model"] is None
    assert seen["effort"] is None
    assert seen["timeout_s"] == llm.GENERATE_TIMEOUT_S


def test_a_sub_second_timeout_survives_into_curls_config(no_store):
    """`max-time = 0` is curl for NO limit -- the one value this must never write.

    curl takes fractional seconds, so the float goes in as it stands. An
    int() here turned every timeout under a second into an unbounded call,
    which is exactly the hang the generator may never impose on a commit.
    """
    spy = SpyRunner(answer("fix(x): y"))
    llm.complete(
        "prompt", effort="minimal", model="vendor/m", timeout_s=0.5,
        runner=spy, env={llm.KEY_ENV: "k"}, auth_path=no_store,
    )
    assert "max-time = 0.5\n" in spy.config_texts[0]


def test_a_timeout_that_is_not_positive_is_a_usage_error(capsys):
    """Loud, like every other typo in the operator's worktrunk config."""
    with pytest.raises(SystemExit) as excinfo:
        llm.build_parser().parse_args(["generate", "--timeout", "0"])
    assert excinfo.value.code == 2
    assert "must be greater than 0" in capsys.readouterr().err


def test_generate_exits_zero_even_when_everything_breaks(monkeypatch, capsys, tmp_path):
    """The contract worktrunk forces on us: text out, exit 0, always."""
    monkeypatch.setattr(llm, "AUTH_PATH", tmp_path / "absent.json")
    monkeypatch.setattr(llm.sys, "stdin", _Stdin(DIFFSTAT_PROMPT))

    def boom(*_a, **_kw):
        raise RuntimeError("the network is on fire")

    monkeypatch.setattr(llm, "generate", boom)
    assert llm.main(["generate"]) == 0
    captured = capsys.readouterr()
    assert captured.out == "Changes to lean_herdr/llm.py, tests/test_llm.py\n"
    assert "the network is on fire" in captured.err


def test_a_missing_key_says_so_on_stderr(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(llm, "AUTH_PATH", tmp_path / "absent.json")
    monkeypatch.setattr(llm.os, "environ", {})
    monkeypatch.setattr(llm.sys, "stdin", _Stdin(DIFFSTAT_PROMPT))
    monkeypatch.setattr(llm, "generate", lambda *a, **kw: "x")
    assert llm.main(["generate"]) == 0
    assert "falling back to the file names" in capsys.readouterr().err


def worktrees(*entries: dict) -> dict:
    return {"result": {"worktrees": list(entries)}}


def test_prereview_reads_only_the_first_line(no_store):
    """The reasoning may say `reject` as often as it likes."""
    spy = SpyRunner(answer(
        "PREREVIEW: pass\nI would reject this if the order had not asked "
        "for it. Nothing to reject."
    ))
    ruling, note = llm.prereview(
        "add a parser", "diff --git a/x b/x", runner=spy,
        env={llm.KEY_ENV: "k"}, auth_path=no_store, settings=NO_FILE,
    )
    assert ruling == "pass"
    assert note.startswith("I would reject this")


def test_a_verdict_further_down_does_not_count(no_store):
    spy = SpyRunner(answer("Looks fine to me.\nPREREVIEW: reject"))
    ruling, note = llm.prereview(
        "add a parser", "diff", runner=spy,
        env={llm.KEY_ENV: "k"}, auth_path=no_store, settings=NO_FILE,
    )
    assert ruling == "skipped"
    assert note == "unparsable_answer"


@pytest.mark.parametrize(
    ("diff", "spy", "reason"),
    [
        ("   ", SpyRunner(answer("PREREVIEW: reject")), "empty_diff"),
        (
            "x" * (llm.MAX_DIFF_BYTES + 1),
            SpyRunner(answer("PREREVIEW: reject")),
            "diff_too_large",
        ),
        ("diff", SpyRunner(raises=OSError("no curl")), "no_answer"),
        ("diff", SpyRunner(answer("I have no opinion")), "unparsable_answer"),
    ],
    ids=["empty", "too-large", "no-curl", "unparsable"],
)
def test_prereview_never_rejects_when_its_own_machinery_fails(diff, spy, reason, no_store):
    ruling, note = llm.prereview(
        "an order", diff, runner=spy,
        env={llm.KEY_ENV: "k"}, auth_path=no_store, settings=NO_FILE,
    )
    assert ruling == "skipped", "the plumbing must never reject"
    assert note == reason


def test_a_missing_key_is_skipped_not_rejected(no_store):
    spy = SpyRunner(answer("PREREVIEW: reject"))
    ruling, note = llm.prereview(
        "an order", "diff", runner=spy, env={}, auth_path=no_store,
        settings=NO_FILE,
    )
    assert (ruling, note) == ("skipped", "no_answer")
    assert spy.calls == []


def judged(no_store, *, cfg=None, env=None, **kw):
    """One prereview call; returns the request body that was sent."""
    spy = SpyRunner(answer("PREREVIEW: pass"))
    llm.prereview(
        "an order", "diff", runner=spy, auth_path=no_store,
        settings=cfg if cfg is not None else NO_FILE,
        env={llm.KEY_ENV: "k", **(env or {})},
        **kw,
    )
    return json.loads(spy.bodies[0])


def test_the_judges_precedence_runs_all_six_levels(no_store):
    """Raising the judge must not raise the commit generator's bill."""
    cfg = LlmSettings(
        model="file/shared", prereview_model="file/judge",
        effort="minimal", prereview_effort="medium",
    )
    both = {
        llm.MODEL_ENV: "env/shared",
        llm.PREREVIEW_MODEL_ENV: "env/judge",
    }
    assert judged(no_store, cfg=cfg, env=both, model="flag/m")["model"] == "flag/m"
    assert judged(no_store, cfg=cfg, env=both)["model"] == "env/judge"
    assert judged(no_store, cfg=cfg, env={llm.MODEL_ENV: "env/shared"})[
        "model"
    ] == "file/judge", "its own file key beats the shared environment"
    assert judged(
        no_store, cfg=LlmSettings(model="file/shared"),
        env={llm.MODEL_ENV: "env/shared"},
    )["model"] == "env/shared"
    assert judged(no_store, cfg=LlmSettings(model="file/shared"))[
        "model"
    ] == "file/shared", "with nothing of its own the judge shares the model"
    assert judged(no_store)["model"] == llm.DEFAULT_MODEL


def test_the_judge_does_not_inherit_the_commit_generators_effort(no_store):
    """`[llm].effort` is the formatter's `minimal`. Inheriting it would
    make the judge as thoughtless as the formatter, silently."""
    cfg = LlmSettings(effort="minimal")
    assert judged(no_store, cfg=cfg)["reasoning"] == {
        "effort": llm.PREREVIEW_EFFORT
    }
    assert judged(
        no_store, cfg=LlmSettings(effort="minimal", prereview_effort="high")
    )["reasoning"] == {"effort": "high"}
    assert judged(no_store, cfg=cfg, effort="low")["reasoning"] == {"effort": "low"}


def test_the_note_is_cut_at_the_cap(no_store):
    spy = SpyRunner(answer("PREREVIEW: reject\n" + "x" * 5000))
    _ruling, note = llm.prereview(
        "an order", "diff", runner=spy,
        env={llm.KEY_ENV: "k"}, auth_path=no_store, settings=NO_FILE,
    )
    assert len(note) == llm.NOTE_MAX_CHARS


def test_the_diff_comes_from_the_worktree_not_the_checkout():
    calls = []

    def runner(cmd, **_kw):
        calls.append(list(cmd))
        return Completed(stdout="diff --git a/x b/x")

    assert llm.wt_diff("/worktrees/feat-x", runner=runner) == "diff --git a/x b/x"
    assert calls == [["wt", "-C", "/worktrees/feat-x", "step", "diff"]]


def test_a_failing_wt_diff_is_none():
    assert llm.wt_diff("/x", runner=lambda *a, **k: Completed(returncode=1)) is None
    assert llm.wt_diff("/x", runner=SpyRunner(raises=OSError("no wt"))) is None


def test_an_unresolvable_worktree_is_skipped_not_rejected():
    """The invariant `_worker_root()` would have broken."""
    def runner(*_a, **_kw):
        raise AssertionError("nothing may run without a resolved path")

    assert llm.prereview_result(
        "an order", branch="feat/x", worktree_list=worktrees(), runner=runner,
    ) == {"prereview": "skipped", "prereview_note": "worktree_unresolved"}
    assert llm.prereview_result(
        "an order", branch="feat/x",
        worktree_list=worktrees({"branch": "feat/x"}), runner=runner,
    )["prereview_note"] == "worktree_unresolved"
    assert llm.prereview_result(
        "an order", branch=None, worktree_list=worktrees(), runner=runner,
    )["prereview_note"] == "no_branch"


def test_wt_diff_carries_its_own_timeout():
    """A lost timeout here hangs the wait mode on a wedged `wt`."""
    spy = SpyRunner()
    llm.wt_diff("/x", runner=spy)
    assert spy.timeouts == [llm.DIFF_TIMEOUT_S]


def test_a_diff_that_never_arrives_is_skipped_not_rejected():
    """`wt step diff` failing is the machine's fault, never the branch's."""
    def runner(*_a, **_kw):
        return Completed(returncode=1)

    assert llm.prereview_result(
        "an order", branch="feat/x",
        worktree_list=worktrees({"branch": "feat/x", "path": "/w"}),
        runner=runner,
    ) == {"prereview": "skipped", "prereview_note": "diff_failed"}


def test_a_garbage_worktree_list_is_skipped_not_a_crash():
    assert llm.prereview_result(
        "an order", branch="feat/x", worktree_list="not a dict",
        runner=lambda *a, **k: Completed(),
    )["prereview"] == "skipped"


def test_the_resolved_path_is_the_one_the_diff_runs_in(no_store):
    seen = []

    def runner(cmd, **_kw):
        seen.append(list(cmd))
        if cmd[:1] == ["wt"]:
            return Completed(stdout="diff --git a/x b/x")
        return Completed(stdout=json.dumps(answer("PREREVIEW: reject\nno test")))

    got = llm.prereview_result(
        "an order",
        branch="feat/x",
        worktree_list=worktrees(
            {"branch": "other", "path": "/wrong"},
            {"branch": "feat/x", "path": "/right"},
        ),
        runner=runner,
        settings=NO_FILE,
        env={llm.KEY_ENV: "k"},
        auth_path=no_store,
    )
    assert got == {"prereview": "reject", "prereview_note": "no test"}
    assert seen[0] == ["wt", "-C", "/right", "step", "diff"]
