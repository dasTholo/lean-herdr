"""The one network call in this tree -- and not one test reaches it.

`request` is injected for the model call; the spy sees the header and the
body as ARGUMENTS. Its predecessor had to read a curl config file off the
disk while curl would have been running, which was the only moment that
file still existed.

`SpyRunner` below it stays, and it is not a leftover: `wt_diff()` still
runs a real subprocess, so it still needs a `subprocess.run` double. Two
seams, two doubles -- that is the shape of the module now.
"""

import json
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

from lean_herdr import llm, openrouter
from lean_herdr.settings import OVERLAY_PATH, SETTINGS_PATH, LlmSettings
from tests.doubles import Completed

#: Every generate() call in here passes `settings=` explicitly. Without
#: it generate() calls file_settings(), which runs `git rev-parse` and
#: reads THIS repository's own .lean-ctx/lean-herdr/config.toml -- a unit test
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
    """Replaces subprocess.run -- and after the urllib move, only for `wt`.

    The model call has its own seam now (`SpyRequest`). What is left for
    this one is `wt_diff()`, which still starts a real subprocess: the
    argv it was handed, and the timeout it was given.
    """

    def __init__(self, reply=None, returncode=0, raises=None):
        self.calls: list[list[str]] = []
        self.timeouts: list[float | None] = []
        self.reply = reply
        self.returncode = returncode
        self.raises = raises

    def __call__(self, cmd, **kwargs):
        self.calls.append(list(cmd))
        self.timeouts.append(kwargs.get("timeout"))
        if self.raises is not None:
            raise self.raises
        out = "" if self.reply is None else json.dumps(self.reply)
        return Completed(returncode=self.returncode, stdout=out)


class SpyRequest:
    """Replaces openrouter.request and records what it was handed.

    Everything the old SpyRunner could only learn from a temp file --
    that the key is in the header and not in argv, that the body is the
    payload we built -- is a plain argument here.
    """

    def __init__(self, reply=None, raises=None):
        self.urls: list[str] = []
        self.methods: list[str] = []
        self.headers: list[dict] = []
        self.bodies: list[str | None] = []
        self.timeouts: list[float] = []
        self.reply = reply
        self.raises = raises

    def __call__(self, url, *, method="GET", headers=None, body=None, timeout_s):
        self.urls.append(url)
        self.methods.append(method)
        self.headers.append(dict(headers or {}))
        self.bodies.append(body)
        self.timeouts.append(timeout_s)
        if self.raises is not None:
            raise self.raises
        return None if self.reply is None else json.dumps(self.reply)


#: What CPython raises when `text=True` meets a byte that is not UTF-8:
#: a ValueError, which is neither an OSError nor a SubprocessError. Built
#: by hand here so it can be injected; that a real subprocess raises
#: exactly this shape is measured in the test right below the class.
DECODE_ERROR = UnicodeDecodeError("utf-8", b"caf\xe9", 3, 4, "invalid continuation byte")


class DecodingRunner:
    """A `subprocess.run` double that decodes the way the real one does.

    `text=True` hands the child's bytes to a decoder, and the CALLER's
    `errors=` decides what a foreign byte costs: the default `strict`
    raises, `replace` yields `�`. Recording `errors` is the whole
    point of the double -- it is the keyword the production code has to
    send, and a `**kwargs`-swallowing double could not tell whether it did.
    """

    def __init__(self, raw: bytes, returncode: int = 0):
        self.raw = raw
        self.returncode = returncode
        self.errors: list[str | None] = []

    def __call__(self, cmd, **kwargs):
        self.errors.append(kwargs.get("errors"))
        return Completed(
            returncode=self.returncode,
            stdout=self.raw.decode("utf-8", kwargs.get("errors") or "strict"),
        )


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


def test_the_key_travels_in_a_header_and_never_in_a_file(no_store):
    """The promise the 0600 curl config used to make, kept without a file.

    The key goes into an Authorization header inside this process. It
    reaches neither argv nor the filesystem -- and the url, the one part
    of this call that a proxy or a log could see, does not carry it.
    """
    spy = SpyRequest(answer("feat(x): y"))
    llm.complete(
        "prompt",
        effort="minimal",
        request=spy,
        env={openrouter.KEY_ENV: "sk-secret-42"},
        auth_path=no_store,
    )
    assert spy.headers[0]["Authorization"] == "Bearer sk-secret-42"
    assert "sk-secret-42" not in spy.urls[0]
    assert spy.urls == [openrouter.ENDPOINT]
    assert spy.methods == ["POST"]


def test_the_body_carries_model_and_effort(no_store):
    """complete() resolves nothing -- it sends what it is handed."""
    spy = SpyRequest(answer("feat(x): y"))
    llm.complete(
        "prompt",
        effort="minimal",
        model="some/other-model",
        request=spy,
        env={openrouter.KEY_ENV: "k"},
        auth_path=no_store,
    )
    body = json.loads(spy.bodies[0])
    assert body["model"] == "some/other-model"
    assert body["reasoning"] == {"effort": "minimal"}
    assert body["messages"] == [{"role": "user", "content": "prompt"}]


def test_the_precedence_runs_flag_environment_file_constant(no_store):
    """One test for the whole chain, so a reordering cannot hide."""
    cfg = LlmSettings(model="file/model", effort="medium")
    env = {openrouter.KEY_ENV: "k", llm.MODEL_ENV: "env/model"}

    def sent(**kw):
        spy = SpyRequest(answer("feat(x): y"))
        llm.generate(
            "prompt",
            request=spy,
            env=env,
            auth_path=no_store,
            settings=cfg,
            **kw,
        )
        return json.loads(spy.bodies[0])

    assert sent(model="flag/model")["model"] == "flag/model"
    assert sent()["model"] == "env/model", "the environment beats the file"
    assert sent(effort="low")["reasoning"] == {"effort": "low"}
    assert sent()["reasoning"] == {"effort": "medium"}, "the file beats the constant"


def test_without_a_file_and_without_an_environment_the_constants_win(no_store):
    spy = SpyRequest(answer("feat(x): y"))
    llm.generate(
        "prompt",
        request=spy,
        env={openrouter.KEY_ENV: "k"},
        auth_path=no_store,
        settings=LlmSettings(),
    )
    body = json.loads(spy.bodies[0])
    assert body["model"] == llm.DEFAULT_MODEL
    assert body["reasoning"] == {"effort": llm.GENERATE_EFFORT}


def test_the_first_non_empty_candidate_wins():
    assert llm._first(None, "", "third", fallback="f") == "third"
    assert llm._first(None, "", fallback="f") == "f"


def _write_config(root: Path, text: str) -> Path:
    """Put the config where SETTINGS_PATH says it lives, never at a literal.

    Spelling the path out here once cost a red suite when it moved out of
    `.config/`: `file_settings()` resolves SETTINGS_PATH, so a fixture that
    writes anywhere else tests the missing-file path under a name that
    promises the opposite.
    """
    path = root / SETTINGS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_a_broken_settings_file_costs_the_defaults_not_the_commit(tmp_path, capsys):
    """The hard invariant, at the one place that could break it."""
    _write_config(tmp_path, "[llm]\nmodel = 5\n")
    assert llm.file_settings(tmp_path) == LlmSettings()
    assert "ignoring the settings file" in capsys.readouterr().err


def test_a_directory_that_is_no_repository_costs_the_defaults(tmp_path, capsys):
    assert llm.file_settings(cwd=tmp_path) == LlmSettings()
    assert "ignoring the settings file" in capsys.readouterr().err


def test_an_undecodable_repo_root_costs_the_defaults_not_the_run(monkeypatch, capsys):
    """The last stretch of the same path F1 closed one layer further in.

    `canonical_root()` runs `git rev-parse` with `text=True` and no
    `errors=`, so a non-UTF-8 byte in the repository PATH decodes strictly
    and raises UnicodeDecodeError -- a ValueError, which neither OSError
    nor SubprocessError names. Uncaught it leaves `bin/herdr-llm
    prereview` as a traceback and exit 1, and exit 1 is this CLI's word
    for "the model rejected".
    """

    def boom(*_a, **_kw):
        raise UnicodeDecodeError("utf-8", b"\xe9", 0, 1, "invalid start byte")

    monkeypatch.setattr(llm, "canonical_root", boom)
    assert llm.file_settings() == LlmSettings()
    assert "ignoring the settings file" in capsys.readouterr().err


def test_a_missing_file_is_the_normal_case_and_says_nothing(tmp_path, capsys):
    assert llm.file_settings(tmp_path) == LlmSettings()
    assert capsys.readouterr().err == "", "an absent file is not a complaint"


def test_a_broken_overlay_costs_the_defaults_not_the_commit(tmp_path, capsys):
    """The same hard invariant, now over TWO files.

    `models.auto.toml` is written by a machine, and a machine that writes
    nonsense must not be able to abort every commit in this repository.
    """
    path = tmp_path / OVERLAY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[llm]\nmodel = 5\n", encoding="utf-8")
    assert llm.file_settings(tmp_path) == LlmSettings()
    assert "ignoring the settings file" in capsys.readouterr().err


def test_the_overlay_is_read_under_config_toml(tmp_path):
    """Both files reach `generate()`: the overlay's `model`, under config.toml's lines.

    The proof is `model`, because `model` is the one key the overlay gives --
    config.toml here is silent on it and speaks on `prereview_model` instead.
    """
    _write_config(tmp_path, '[llm]\nprereview_model = "by/hand"\n')
    overlay = tmp_path / OVERLAY_PATH
    overlay.write_text('[llm]\nmodel = "auto/pick"\n', encoding="utf-8")
    got = llm.file_settings(tmp_path)
    assert got.model == "auto/pick"
    assert got.prereview_model == "by/hand"


def test_the_file_is_read_relative_to_the_repo_root(tmp_path):
    _write_config(tmp_path, '[llm]\nmodel = "from/file"\nprereview_effort = "medium"\n')
    got = llm.file_settings(tmp_path)
    assert got.model == "from/file"
    assert got.prereview_effort == "medium"
    assert got.effort == "", "an unset key stays the empty string"


def test_a_fenced_answer_loses_its_fence(no_store):
    spy = SpyRequest(answer("```\nfix(parser): add null check\n```"))
    got = llm.complete(
        "prompt",
        effort="minimal",
        request=spy,
        env={openrouter.KEY_ENV: "k"},
        auth_path=no_store,
    )
    assert got == "fix(parser): add null check"


def test_the_fallback_reads_the_files_out_of_the_diffstat():
    assert llm.fallback_message(DIFFSTAT_PROMPT) == (
        "Changes to lean_herdr/llm.py, tests/test_llm.py"
    )


def test_the_fallback_caps_the_file_list():
    stat = "\n".join(f" f{n}.py | 1 +" for n in range(6))
    prompt = f"<diffstat>\n{stat}\n</diffstat>"
    assert llm.fallback_message(prompt) == ("Changes to f0.py, f1.py, f2.py and 3 more")


def test_the_fallback_survives_a_prompt_with_no_diffstat():
    assert llm.fallback_message("nothing useful here") == ("Changes to the working tree")


@pytest.mark.parametrize(
    "spy",
    [
        SpyRequest(reply=None),
        SpyRequest(reply={"error": {"message": "rate limited"}}),
        SpyRequest(answer("   ")),
        SpyRequest(raises=urllib.error.URLError("no route")),
    ],
    ids=["transport-failed", "error-body", "empty-answer", "url-error"],
)
def test_generate_returns_the_fallback_for_every_failure(spy, no_store):
    got = llm.generate(
        DIFFSTAT_PROMPT,
        request=spy,
        settings=NO_FILE,
        env={openrouter.KEY_ENV: "k"},
        auth_path=no_store,
    )
    assert got == "Changes to lean_herdr/llm.py, tests/test_llm.py"


def test_generate_without_a_key_never_calls_the_endpoint(no_store):
    spy = SpyRequest(answer("feat(x): y"))
    got = llm.generate(DIFFSTAT_PROMPT, request=spy, env={}, auth_path=no_store, settings=NO_FILE)
    assert spy.urls == []
    assert got.startswith("Changes to ")


def test_a_prompt_over_the_cap_is_never_sent(no_store):
    spy = SpyRequest(answer("feat(x): y"))
    huge = "x" * (llm.MAX_PROMPT_BYTES + 1)
    assert (
        llm.complete(
            huge,
            effort="minimal",
            request=spy,
            env={openrouter.KEY_ENV: "k"},
            auth_path=no_store,
        )
        is None
    )
    assert spy.urls == [], "a runaway diff must not cost money"


def test_a_key_that_would_inject_a_header_is_refused(no_store):
    """A newline in a header value is an injection, not a formatting slip.

    `http.client` refuses such a value itself -- with a ValueError, out of
    a function whose whole contract is `never raises`. The check therefore
    stays explicit and stays in front of the call.
    """
    spy = SpyRequest(answer("feat(x): y"))
    assert (
        llm.complete(
            "prompt",
            effort="minimal",
            request=spy,
            env={openrouter.KEY_ENV: 'k"\nX-Evil: 1'},
            auth_path=no_store,
        )
        is None
    )
    assert spy.urls == []


def test_generate_passes_the_measured_effort_by_default(no_store):
    spy = SpyRequest(answer("feat(x): y"))
    llm.generate(
        "prompt",
        request=spy,
        env={openrouter.KEY_ENV: "k"},
        auth_path=no_store,
        settings=NO_FILE,
    )
    assert json.loads(spy.bodies[0])["reasoning"] == {"effort": "minimal"}


def test_generate_writes_the_message_and_exits_zero(monkeypatch, capsys, tmp_path):
    store = tmp_path / "auth.json"
    store.write_text(json.dumps({"openrouter": {"key": "k"}}))
    monkeypatch.setattr(openrouter, "AUTH_PATH", store)
    # Empty, so the store is what decides -- on a machine that exports
    # $OPENROUTER_API_KEY the file would otherwise never be consulted.
    monkeypatch.setattr(llm.os, "environ", {})
    monkeypatch.setattr(llm.sys, "stdin", _Stdin(DIFFSTAT_PROMPT))
    monkeypatch.setattr(llm, "generate", lambda *a, **kw: "feat(llm): add the generator")
    assert llm.main(["generate"]) == 0
    captured = capsys.readouterr()
    assert captured.out == "feat(llm): add the generator\n"
    assert captured.err == "", "a key in the store means no missing-key notice"


def test_the_flags_reach_generate(monkeypatch, tmp_path):
    """The whole job of this CLI: three flags onto three keyword arguments."""
    monkeypatch.setattr(openrouter, "AUTH_PATH", tmp_path / "absent.json")
    monkeypatch.setattr(llm.os, "environ", {openrouter.KEY_ENV: "k"})
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


def test_the_absent_flags_stay_none_so_generate_owns_the_precedence(monkeypatch, tmp_path):
    """A constant passed from here would put the CLI's silence above the file."""
    monkeypatch.setattr(openrouter, "AUTH_PATH", tmp_path / "absent.json")
    monkeypatch.setattr(llm.os, "environ", {openrouter.KEY_ENV: "k"})
    monkeypatch.setattr(llm.sys, "stdin", _Stdin(DIFFSTAT_PROMPT))
    seen: dict[str, object] = {}
    monkeypatch.setattr(llm, "generate", lambda prompt, **kw: (seen.update(kw), "feat(x): y")[1])
    assert llm.main(["generate"]) == 0
    assert seen["model"] is None
    assert seen["effort"] is None
    assert seen["timeout_s"] == llm.GENERATE_TIMEOUT_S


def test_a_sub_second_timeout_survives_into_the_request(no_store):
    """The float goes through as it stands -- an int() would round it to zero.

    Under curl that made `max-time = 0`, which is curl for NO limit at all;
    urllib takes the float directly. Either way a timeout that rounds away
    is the unbounded call the generator may never impose on a commit.
    """
    spy = SpyRequest(answer("fix(x): y"))
    llm.complete(
        "prompt",
        effort="minimal",
        model="vendor/m",
        timeout_s=0.5,
        request=spy,
        env={openrouter.KEY_ENV: "k"},
        auth_path=no_store,
    )
    assert spy.timeouts == [0.5]


def test_a_timeout_that_is_not_positive_is_a_usage_error(capsys):
    """Loud, like every other typo in the operator's worktrunk config."""
    with pytest.raises(SystemExit) as excinfo:
        llm.build_parser().parse_args(["generate", "--timeout", "0"])
    assert excinfo.value.code == 2
    assert "must be greater than 0" in capsys.readouterr().err


def test_generate_exits_zero_even_when_everything_breaks(monkeypatch, capsys, tmp_path):
    """The contract worktrunk forces on us: text out, exit 0, always."""
    monkeypatch.setattr(openrouter, "AUTH_PATH", tmp_path / "absent.json")
    monkeypatch.setattr(llm.sys, "stdin", _Stdin(DIFFSTAT_PROMPT))

    def boom(*_a, **_kw):
        raise RuntimeError("the network is on fire")

    monkeypatch.setattr(llm, "generate", boom)
    assert llm.main(["generate"]) == 0
    captured = capsys.readouterr()
    assert captured.out == "Changes to lean_herdr/llm.py, tests/test_llm.py\n"
    assert "the network is on fire" in captured.err


def test_a_missing_key_says_so_on_stderr(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(openrouter, "AUTH_PATH", tmp_path / "absent.json")
    monkeypatch.setattr(llm.os, "environ", {})
    monkeypatch.setattr(llm.sys, "stdin", _Stdin(DIFFSTAT_PROMPT))
    monkeypatch.setattr(llm, "generate", lambda *a, **kw: "x")
    assert llm.main(["generate"]) == 0
    assert "falling back to the file names" in capsys.readouterr().err


def worktrees(*entries: dict) -> dict:
    return {"result": {"worktrees": list(entries)}}


def test_prereview_reads_only_the_first_line(no_store):
    """The reasoning may say `reject` as often as it likes."""
    spy = SpyRequest(
        answer(
            "PREREVIEW: pass\nI would reject this if the order had not asked "
            "for it. Nothing to reject."
        )
    )
    ruling, note = llm.prereview(
        "add a parser",
        "diff --git a/x b/x",
        request=spy,
        env={openrouter.KEY_ENV: "k"},
        auth_path=no_store,
        settings=NO_FILE,
    )
    assert ruling == "pass"
    assert note.startswith("I would reject this")


def test_a_verdict_further_down_does_not_count(no_store):
    spy = SpyRequest(answer("Looks fine to me.\nPREREVIEW: reject"))
    ruling, note = llm.prereview(
        "add a parser",
        "diff",
        request=spy,
        env={openrouter.KEY_ENV: "k"},
        auth_path=no_store,
        settings=NO_FILE,
    )
    assert ruling == "skipped"
    assert note == "unparsable_answer"


@pytest.mark.parametrize(
    ("diff", "spy", "reason"),
    [
        ("   ", SpyRequest(answer("PREREVIEW: reject")), "empty_diff"),
        (
            "x" * (llm.MAX_DIFF_BYTES + 1),
            SpyRequest(answer("PREREVIEW: reject")),
            "diff_too_large",
        ),
        ("diff", SpyRequest(reply=None), "no_answer"),
        ("diff", SpyRequest(answer("I have no opinion")), "unparsable_answer"),
        # Two raises on the injection seam, not inside the transport: whatever
        # a caller injects, this layer owes its callers `skipped` -- never a
        # rejection and never a traceback. The wait mode reported one as
        # `dispatch_crashed` on a task that had completed, and the manual CLI
        # as exit 1, the code that is supposed to mean the model rejected.
        # Both arms of `complete()`'s net are exercised here: URLError is an
        # OSError, and the decode error a ValueError that is NOT one.
        ("diff", SpyRequest(raises=urllib.error.URLError("no route")), "no_answer"),
        ("diff", SpyRequest(raises=DECODE_ERROR), "no_answer"),
    ],
    ids=[
        "empty",
        "too-large",
        "transport-failed",
        "unparsable",
        "url-error",
        "undecodable",
    ],
)
def test_prereview_never_rejects_when_its_own_machinery_fails(diff, spy, reason, no_store):
    ruling, note = llm.prereview(
        "an order",
        diff,
        request=spy,
        env={openrouter.KEY_ENV: "k"},
        auth_path=no_store,
        settings=NO_FILE,
    )
    assert ruling == "skipped", "the plumbing must never reject"
    assert note == reason


def test_a_missing_key_is_skipped_not_rejected(no_store):
    spy = SpyRequest(answer("PREREVIEW: reject"))
    ruling, note = llm.prereview(
        "an order",
        "diff",
        request=spy,
        env={},
        auth_path=no_store,
        settings=NO_FILE,
    )
    assert (ruling, note) == ("skipped", "no_answer")
    assert spy.urls == []


def judged(no_store, *, cfg=None, env=None, **kw):
    """One prereview call; returns the request body that was sent."""
    spy = SpyRequest(answer("PREREVIEW: pass"))
    llm.prereview(
        "an order",
        "diff",
        request=spy,
        auth_path=no_store,
        settings=cfg if cfg is not None else NO_FILE,
        env={openrouter.KEY_ENV: "k", **(env or {})},
        **kw,
    )
    return json.loads(spy.bodies[0])


def test_the_judges_precedence_runs_all_six_levels(no_store):
    """Raising the judge must not raise the commit generator's bill."""
    cfg = LlmSettings(
        model="file/shared",
        prereview_model="file/judge",
        effort="minimal",
        prereview_effort="medium",
    )
    both = {
        llm.MODEL_ENV: "env/shared",
        llm.PREREVIEW_MODEL_ENV: "env/judge",
    }
    assert judged(no_store, cfg=cfg, env=both, model="flag/m")["model"] == "flag/m"
    assert judged(no_store, cfg=cfg, env=both)["model"] == "env/judge"
    assert judged(no_store, cfg=cfg, env={llm.MODEL_ENV: "env/shared"})["model"] == "file/judge", (
        "its own file key beats the shared environment"
    )
    assert (
        judged(
            no_store,
            cfg=LlmSettings(model="file/shared"),
            env={llm.MODEL_ENV: "env/shared"},
        )["model"]
        == "env/shared"
    )
    assert judged(no_store, cfg=LlmSettings(model="file/shared"))["model"] == "file/shared", (
        "with nothing of its own the judge shares the model"
    )
    assert judged(no_store)["model"] == llm.DEFAULT_MODEL


def test_the_judge_does_not_inherit_the_commit_generators_effort(no_store):
    """`[llm].effort` is the formatter's `minimal`. Inheriting it would
    make the judge as thoughtless as the formatter, silently."""
    cfg = LlmSettings(effort="minimal")
    assert judged(no_store, cfg=cfg)["reasoning"] == {"effort": llm.PREREVIEW_EFFORT}
    assert judged(no_store, cfg=LlmSettings(effort="minimal", prereview_effort="high"))[
        "reasoning"
    ] == {"effort": "high"}
    assert judged(no_store, cfg=cfg, effort="low")["reasoning"] == {"effort": "low"}


def test_the_note_is_cut_at_the_cap(no_store):
    spy = SpyRequest(answer("PREREVIEW: reject\n" + "x" * 5000))
    _ruling, note = llm.prereview(
        "an order",
        "diff",
        request=spy,
        env={openrouter.KEY_ENV: "k"},
        auth_path=no_store,
        settings=NO_FILE,
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
        "an order",
        branch="feat/x",
        worktree_list=worktrees(),
        runner=runner,
    ) == {"prereview": "skipped", "prereview_note": "worktree_unresolved"}
    assert (
        llm.prereview_result(
            "an order",
            branch="feat/x",
            worktree_list=worktrees({"branch": "feat/x"}),
            runner=runner,
        )["prereview_note"]
        == "worktree_unresolved"
    )
    assert (
        llm.prereview_result(
            "an order",
            branch=None,
            worktree_list=worktrees(),
            runner=runner,
        )["prereview_note"]
        == "no_branch"
    )


def test_prereview_itself_refuses_to_judge_without_an_order(no_store):
    """`bin/herdr-llm prereview` without --order reaches prereview() direct.

    prereview_result() has its own no_order guard, but the manual entry
    point does not go through it -- and argparse defaults --order to "".
    The guard belongs to whoever builds the prompt.
    """
    spy = SpyRequest(answer("PREREVIEW: reject\nnothing matches the order"))
    assert llm.prereview(
        "",
        "diff --git a/x b/x\n+print('debug')",
        request=spy,
        env={openrouter.KEY_ENV: "k"},
        auth_path=no_store,
        settings=NO_FILE,
    ) == ("skipped", "no_order")
    assert spy.urls == [], "no model may be asked to judge against nothing"


def test_an_empty_order_is_skipped_not_rejected():
    """An order log whose first event is not `created` leaves description "".

    The prompt lists "changes the order does not cover" as a ground for
    rejection, so an empty <order> block invites exactly the false reject
    the whole module is built to avoid.
    """

    def runner(*_a, **_kw):
        raise AssertionError("nothing may run without an order to judge")

    assert llm.prereview_result(
        "",
        branch="feat/x",
        worktree_list=worktrees({"branch": "feat/x", "path": "/w"}),
        runner=runner,
    ) == {"prereview": "skipped", "prereview_note": "no_order"}


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
        "an order",
        branch="feat/x",
        worktree_list=worktrees({"branch": "feat/x", "path": "/w"}),
        runner=runner,
    ) == {"prereview": "skipped", "prereview_note": "diff_failed"}


def test_a_garbage_worktree_list_is_skipped_not_a_crash():
    assert (
        llm.prereview_result(
            "an order",
            branch="feat/x",
            worktree_list="not a dict",
            runner=lambda *a, **k: Completed(),
        )["prereview"]
        == "skipped"
    )


def test_the_resolved_path_is_the_one_the_diff_runs_in(no_store):
    """Two seams in one call: `runner` fetches the diff, `request` judges it."""
    seen = []

    def runner(cmd, **_kw):
        seen.append(list(cmd))
        return Completed(stdout="diff --git a/x b/x")

    got = llm.prereview_result(
        "an order",
        branch="feat/x",
        worktree_list=worktrees(
            {"branch": "other", "path": "/wrong"},
            {"branch": "feat/x", "path": "/right"},
        ),
        runner=runner,
        request=SpyRequest(answer("PREREVIEW: reject\nno test")),
        settings=NO_FILE,
        env={openrouter.KEY_ENV: "k"},
        auth_path=no_store,
    )
    assert got == {"prereview": "reject", "prereview_note": "no test"}
    assert seen[0] == ["wt", "-C", "/right", "step", "diff"]


def test_the_cli_rejects_with_exit_one(monkeypatch, capsys):
    monkeypatch.setattr(llm, "wt_diff", lambda *a, **kw: "diff --git a/x b/x")
    monkeypatch.setattr(llm, "prereview", lambda *a, **kw: ("reject", "no test beside new logic"))
    assert llm.main(["prereview", "-C", "/worktrees/feat-x"]) == 1
    out = capsys.readouterr().out
    assert out == "reject\nno test beside new logic\n"


def test_the_cli_passes_and_skips_with_exit_zero(monkeypatch, capsys):
    monkeypatch.setattr(llm, "wt_diff", lambda *a, **kw: "diff")
    for ruling in ("pass", "skipped"):
        # `fixed=ruling` binds now, not at call time -- ruff B023.
        monkeypatch.setattr(llm, "prereview", lambda *a, fixed=ruling, **kw: (fixed, ""))
        assert llm.main(["prereview"]) == 0
        assert capsys.readouterr().out == f"{ruling}\n"


def test_a_failing_wt_diff_says_so_and_judges_nothing(monkeypatch, capsys):
    """One cause, one answer: the same `skipped` the --await path gives.

    Exit 1 then means exactly one thing -- the model rejected. A machine
    that could not fetch the diff has found nothing, and a withheld ruling
    is not a finding. The stderr line stays, for the human who typed the
    wrong `-C`.
    """
    monkeypatch.setattr(llm, "wt_diff", lambda *a, **kw: None)
    monkeypatch.setattr(
        llm,
        "prereview",
        lambda *a, **kw: pytest.fail("nothing may be judged without a diff"),
    )
    assert llm.main(["prereview", "-C", "/gone"]) == 0
    captured = capsys.readouterr()
    assert captured.out == "skipped\ndiff_failed\n"
    assert "step diff` failed" in captured.err


def test_a_strict_decode_raises_a_value_error_no_handler_here_names():
    """Not a double -- the premise, measured on a real subprocess.

    `wt step diff` carries untracked files, so one latin-1 file lying in
    the tree puts a foreign byte on that stdout. Under `text=True` alone
    CPython raises UnicodeDecodeError, and that is a ValueError: it walks
    straight through `except (OSError, subprocess.SubprocessError)`.
    """
    cmd = [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'a\\xe9b')"]
    with pytest.raises(ValueError) as excinfo:
        subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    raised = excinfo.value
    assert not isinstance(raised, OSError)
    assert not isinstance(raised, subprocess.SubprocessError)
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=30,
        check=False,
    )
    assert proc.stdout == "a�b", "errors=replace is what keeps the bytes coming"


def test_the_diff_is_fetched_with_a_lenient_decode():
    """A foreign byte in the branch may not cost the branch its ruling."""
    spy = DecodingRunner(b"diff --git a/x b/x\n+caf\xe9\n")
    assert llm.wt_diff("/w", runner=spy) == "diff --git a/x b/x\n+caf�\n"
    assert spy.errors == ["replace"]


def test_a_foreign_byte_in_the_diff_is_judged_and_not_crashed_on(no_store):
    """The finding end to end: a `�` in the prompt, and a real ruling out.

    Before this, the UnicodeDecodeError left `wt_diff()`, ran through
    `prereview_result()` into the wait mode's collecting `except`, and
    turned a task that had actually completed into `dispatch_crashed`.
    """
    spy = SpyRequest(answer("PREREVIEW: reject\nno test"))
    got = llm.prereview_result(
        "an order",
        branch="feat/x",
        worktree_list=worktrees({"branch": "feat/x", "path": "/w"}),
        runner=DecodingRunner(b"diff --git a/x b/x\n+caf\xe9\n"),
        request=spy,
        settings=NO_FILE,
        env={openrouter.KEY_ENV: "k"},
        auth_path=no_store,
    )
    assert got == {"prereview": "reject", "prereview_note": "no test"}
    assert "caf�" in json.loads(spy.bodies[0])["messages"][0]["content"]


def test_a_decode_error_the_replacement_missed_is_skipped_not_a_crash(no_store):
    """The belt beside the braces of `errors="replace"`.

    Whatever else this layer can raise, it owes its callers `skipped` --
    never a rejection and never a traceback. The wait mode would report
    the traceback as a crashed dispatch, the CLI as exit 1, and exit 1
    means one thing only: the model rejected the branch.
    """
    assert llm.wt_diff("/x", runner=SpyRunner(raises=DECODE_ERROR)) is None
    assert (
        llm.complete(
            "prompt",
            effort="minimal",
            request=SpyRequest(raises=DECODE_ERROR),
            env={openrouter.KEY_ENV: "k"},
            auth_path=no_store,
        )
        is None
    )


def test_the_flags_reach_prereview(monkeypatch):
    """The twin of `test_the_flags_reach_generate`, for the other mode.

    `--order` is the one whose loss is silent: prereview() answers an
    empty order with `skipped` / `no_order`, so every manual run would
    keep exiting 0 with a plausible word on stdout and judge nothing.
    """
    fetched: dict[str, object] = {}
    judged_with: dict[str, object] = {}

    def fake_wt_diff(path, **kwargs):
        fetched["path"] = path
        fetched.update(kwargs)
        return "diff --git a/x b/x"

    def fake_prereview(order, diff, **kwargs):
        judged_with["order"] = order
        judged_with["diff"] = diff
        judged_with.update(kwargs)
        return "pass", ""

    monkeypatch.setattr(llm, "wt_diff", fake_wt_diff)
    monkeypatch.setattr(llm, "prereview", fake_prereview)
    argv = [
        "prereview",
        "-C",
        "/worktrees/feat-x",
        "--order",
        "add a row parser",
        "--model",
        "vendor/m",
        "--effort",
        "high",
        "--timeout",
        "5",
    ]
    assert llm.main(argv) == 0
    assert fetched == {"path": "/worktrees/feat-x", "timeout_s": 5.0}
    assert judged_with == {
        "order": "add a row parser",
        "diff": "diff --git a/x b/x",
        "model": "vendor/m",
        "effort": "high",
        "timeout_s": 5.0,
    }


def test_the_absent_prereview_flags_stay_none_and_the_defaults_differ(monkeypatch):
    """A constant passed from here would put the CLI's silence above the file.

    And the two defaults this mode falls back to are NOT one number:
    `wt step diff` gets 30 seconds, the model call 60.
    """
    fetched: dict[str, object] = {}
    judged_with: dict[str, object] = {}

    def fake_wt_diff(path, **kwargs):
        fetched["path"] = path
        fetched.update(kwargs)
        return "diff"

    def fake_prereview(order, _diff, **kwargs):
        judged_with["order"] = order
        judged_with.update(kwargs)
        return "pass", ""

    monkeypatch.setattr(llm, "wt_diff", fake_wt_diff)
    monkeypatch.setattr(llm, "prereview", fake_prereview)
    assert llm.main(["prereview"]) == 0
    assert fetched == {"path": ".", "timeout_s": llm.DIFF_TIMEOUT_S}
    assert judged_with["order"] == ""
    assert judged_with["model"] is None
    assert judged_with["effort"] is None
    assert judged_with["timeout_s"] == llm.PREREVIEW_TIMEOUT_S


@pytest.mark.integration
def test_the_real_chain_answers_at_all(tmp_path):
    """The one test that reaches the network -- never in CI.

    Everything else in this file injects `request`. This one injects
    nothing and takes the real default, to prove the pieces fit together
    in the real world: a real key, a real socket, a real OpenRouter
    answer. It costs a fraction of a cent.
    """
    if openrouter.api_key() is None:
        pytest.skip("no OpenRouter key on this machine")
    got = llm.complete(
        "Answer with exactly the word: pong",
        effort=llm.GENERATE_EFFORT,
    )
    assert got is not None and "pong" in got.lower()
