"""The catalogue, against a recorded answer. No test in here reaches the network."""

import json
from pathlib import Path

import pytest

from lean_herdr import catalog, llm
from lean_herdr.bus import BusError
from lean_herdr.settings import (
    OVERLAY_PATH,
    SETTINGS_PATH,
    ModelsSettings,
    llm_settings,
    read_settings,
)

FIXTURE = Path(__file__).parent / "fixtures" / "openrouter-models.sample.json"


def sample() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["data"]


class FakeRequest:
    def __init__(self, reply=None):
        self.urls: list[str] = []
        #: Recorded so the no-key guarantee has a test and not just a
        #: docstring: an Authorization header is the only way a key could
        #: leave `fetch()`, since it passes no body and no query credential.
        self.headers: list[dict | None] = []
        self.reply = reply

    def __call__(self, url, *, method="GET", headers=None, body=None, timeout_s):
        self.urls.append(url)
        self.headers.append(headers)
        return self.reply


def test_fetch_returns_the_recorded_page_as_five_dicts():
    fake = FakeRequest(FIXTURE.read_text(encoding="utf-8"))
    models = catalog.fetch(requires=("reasoning",), request=fake)
    assert models is not None
    assert [entry["id"] for entry in models] == [
        "cheap/no-benchmarks",
        "cheap/no-minimal-effort",
        "mid/no-effort-list",
        "mid/small-context",
        "good/all-clear",
    ]


def test_the_url_carries_what_works_and_neither_parameter_that_does_not():
    """Spec section 1.4, measured 2026-09-04.

    `search=` is accepted and then IGNORED -- two different queries came
    back byte-identical -- and `category=programming` answers HTTP 400. A
    url that grew either one would look like it filters and would not.
    """
    fake = FakeRequest(FIXTURE.read_text(encoding="utf-8"))
    catalog.fetch(requires=("reasoning",), limit=200, request=fake)
    url = fake.urls[0]
    assert url.startswith(f"{catalog.CATALOG_URL}?")
    assert "sort=pricing-low-to-high" in url
    assert "limit=200" in url
    assert "supported_parameters=reasoning" in url
    assert "search" not in url
    assert "category" not in url


def test_the_catalogue_is_asked_without_a_key(monkeypatch):
    """A deliberate deviation from the spec, and the one that needs a guard.

    Spec section 2 moved `api_key()` into `openrouter` because "both
    consumers need it"; section 1.4 then MEASURED that `/models` answers
    without one. Measured beats argued -- and a key requirement here would
    make a public catalogue lookup fail on a machine that has none, for a
    request the endpoint serves anyway.

    `api_key()` is made to explode rather than merely checked for absence:
    a future edit that reaches for it fails here instead of silently
    reintroducing the requirement.
    """

    def boom(*_args, **_kwargs):
        raise AssertionError("fetch() must not ask for an API key")

    monkeypatch.setattr(catalog.openrouter, "api_key", boom)
    fake = FakeRequest(FIXTURE.read_text(encoding="utf-8"))

    assert catalog.fetch(requires=("reasoning",), request=fake) is not None
    assert fake.headers == [None], fake.headers


@pytest.mark.parametrize(
    "reply",
    [
        None,
        "not json at all",
        '{"total_count": 261}',
        '{"data": "not a list"}',
    ],
    ids=["no answer", "not json", "no data key", "data is a string"],
)
def test_fetch_answers_every_unusable_reply_with_none(reply):
    """Never raises. None is every failure, the same profile as `request()`."""
    assert catalog.fetch(requires=("reasoning",), request=FakeRequest(reply)) is None


@pytest.mark.parametrize(
    "error", [OSError("refused"), ValueError("bad url")], ids=["oserror", "valueerror"]
)
def test_a_request_seam_that_raises_is_no_catalogue(tmp_path, error):
    """`fetch()` promises "never raises" itself -- it does not borrow that from a default.

    `openrouter.request` answers every failure with None, but `request` is
    injectable, and `check()` stands between `workspace up` and a price comparison.
    Same belt, same reason as `llm.complete()`.
    """

    def boom(url, **kwargs):
        raise error

    assert catalog.fetch(requires=("reasoning",), request=boom) is None
    outcome = catalog.check(
        root=tmp_path, settings=ModelsSettings(auto=True), efforts=(), request=boom
    )
    assert outcome == {"written": False, "model": None, "reason": "no_catalog"}
    assert not (tmp_path / OVERLAY_PATH).exists()


# Every row names its thresholds IN FULL -- nothing carries over from the
# row above, and everything unnamed is the default, i.e. "no threshold".
# Two of these rows stand again as named tests below, where the reasoning
# behind the two rejection rules belongs.
@pytest.mark.parametrize(
    ("thresholds", "efforts", "expected"),
    [
        (ModelsSettings(), (), "cheap/no-benchmarks"),
        (ModelsSettings(), ("minimal", "low"), "cheap/no-benchmarks"),
        (ModelsSettings(min_coding_index=30.0), ("minimal",), "mid/small-context"),
        (ModelsSettings(min_coding_index=30.0), (), "cheap/no-minimal-effort"),
        (ModelsSettings(min_context=100000), ("minimal",), "cheap/no-benchmarks"),
        (
            ModelsSettings(min_context=100000, min_coding_index=30.0),
            ("minimal",),
            "good/all-clear",
        ),
        (ModelsSettings(max_prompt_price=0.00000001), (), None),
        (ModelsSettings(min_intelligence_index=99.0), (), None),
    ],
    ids=[
        "nothing filters, the first one wins",
        "both levels are listed",
        "no benchmarks block, and no minimal effort",
        "index 38.5 is enough without an effort claim",
        "a missing benchmarks block costs nothing without an index floor",
        "index, effort and context together",
        "nobody is that cheap",
        "nobody is that good",
    ],
)
def test_recommend_picks_the_first_survivor(thresholds, efforts, expected):
    picked = catalog.recommend(sample(), thresholds=thresholds, efforts=efforts)
    assert (None if picked is None else picked["id"]) == expected


def test_recommend_takes_the_given_order_and_does_not_re_sort():
    """The M3 rule, and the only test that can catch it breaking.

    `fetch()` asked the server for `pricing-low-to-high`, so the first
    survivor IS the cheapest one and `recommend()` must not order anything
    itself -- a second ordering rule is one that can drift from the
    server's. Every other test in this file is blind to that: the fixture
    is already in ascending price order, so an implementation that sorted
    by price would agree with all of them.

    So this one hands the list in REVERSED. The expected answer is the
    entry that comes first in the argument, which is now the most
    expensive one. A `recommend` that re-sorted would return
    `cheap/no-benchmarks` here and fail.
    """
    picked = catalog.recommend(list(reversed(sample())), thresholds=ModelsSettings(), efforts=())
    assert picked is not None
    assert picked["id"] == "good/all-clear", "the order given is the order used"


@pytest.mark.parametrize(
    "junk",
    [float("nan"), float("inf"), "NaN", "Infinity", "-inf"],
    ids=["nan", "inf", "nan-string", "infinity-string", "negative-inf"],
)
def test_a_non_finite_index_does_not_clear_a_floor(junk):
    """Junk evidence must not beat missing evidence.

    Every comparison against a NaN is False, so `nan < floor` is False and
    a NaN index would sail past a threshold that a model with NO index at
    all is rejected for. `json.loads` accepts a bare `NaN` or `Infinity`,
    so this comes off the wire, not just out of a hand-built dict. An
    infinity is refused with it: a catalogue claiming an unbounded score
    is not evidence either.
    """
    entry = {
        "id": "junk/evidence",
        "context_length": 128000,
        "pricing": {"prompt": "0.00000001"},
        "reasoning": {"supported_efforts": ["minimal", "low"]},
        "benchmarks": {"artificial_analysis": {"coding_index": junk}},
    }
    picked = catalog.recommend(
        [entry], thresholds=ModelsSettings(min_coding_index=30.0), efforts=()
    )
    assert picked is None


def test_a_non_finite_price_does_not_clear_a_cap():
    """The same hole on the other threshold: `nan > cap` is False too."""
    entry = {
        "id": "junk/price",
        "context_length": 128000,
        "pricing": {"prompt": "NaN"},
        "reasoning": {"supported_efforts": ["minimal"]},
    }
    picked = catalog.recommend(
        [entry], thresholds=ModelsSettings(max_prompt_price=1e-8), efforts=()
    )
    assert picked is None


def test_a_model_without_benchmarks_fails_a_set_index_threshold():
    """Missing evidence is not a pass.

    `cheap/no-benchmarks` is the first and cheapest entry and carries no
    `benchmarks` block at all. Treating "unknown" as "fine" would pick
    exactly the models nobody measured.
    """
    picked = catalog.recommend(
        sample(),
        thresholds=ModelsSettings(min_coding_index=30.0),
        efforts=(),
    )
    assert picked is not None
    assert picked["id"] == "cheap/no-minimal-effort"


def test_a_model_that_cannot_do_the_effort_is_dropped():
    """Both resolved effort levels, or the candidate is gone.

    One `[llm].model` serves the commit generator on `effort` and the
    pre-review judge on `prereview_effort`. `cheap/no-minimal-effort`
    lists high/medium/low and would answer the second job and fail the
    first with an HTTP error that looks like a missing key.
    """
    picked = catalog.recommend(
        sample(),
        thresholds=ModelsSettings(min_coding_index=30.0),
        efforts=("minimal",),
    )
    assert picked is not None
    assert picked["id"] == "mid/small-context"


@pytest.mark.parametrize(
    ("efforts", "expected"),
    [(("minimal",), "mid/small-context"), ((), "mid/no-effort-list")],
    ids=["an effort is asked for", "no effort is asked for"],
)
def test_a_model_without_an_effort_list_fails_only_the_effort_check(efforts, expected):
    """Missing evidence is not a pass -- for efforts as for benchmarks.

    `mid/no-effort-list` clears `min_coding_index=50.0` and is cheaper than
    `mid/small-context`, but lists no `supported_efforts`. Asked for an effort it
    is dropped and `mid/small-context` wins; asked for none it wins itself -- so
    the missing list alone is what dropped it.

    Remove the list check from `_clears` and the first case does not pick a wrong
    model, it errors: `level not in None` is a TypeError. That error IS the
    refutation, not a broken test.
    """
    picked = catalog.recommend(
        sample(), thresholds=ModelsSettings(min_coding_index=50.0), efforts=efforts
    )
    assert picked is not None
    assert picked["id"] == expected


def test_write_overlay_writes_the_model_and_never_the_judge(tmp_path):
    """`prereview_model` stays a human's key.

    The judge falls back to `model` anyway, and a second automatically set
    key would undo the separation it exists for.
    """
    path = catalog.write_overlay("good/all-clear", root=tmp_path, stamp="2026-09-04T07:00:00+00:00")
    assert path == tmp_path / OVERLAY_PATH
    text = path.read_text(encoding="utf-8")
    assert "2026-09-04T07:00:00+00:00" in text
    assert "[llm]" in text
    assert 'model = "good/all-clear"' in text
    assert "prereview_model" not in text


def test_the_overlay_is_valid_toml_although_we_have_no_writer(tmp_path):
    """Hand-assembled TOML parses back to exactly the slug we put in."""
    path = catalog.write_overlay("good/all-clear", root=tmp_path)
    assert llm_settings(read_settings(path)).model == "good/all-clear"


def test_a_second_call_overwrites_the_file_whole(tmp_path):
    """Never edited in place -- the old slug must be gone, not shadowed."""
    catalog.write_overlay("good/all-clear", root=tmp_path)
    path = catalog.write_overlay("mid/small-context", root=tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "good/all-clear" not in text
    assert llm_settings(read_settings(path)).model == "mid/small-context"


def test_a_failed_replace_leaves_the_old_overlay_and_no_temp_file(monkeypatch, tmp_path):
    """The overlay is never half-written, and a failed attempt leaves nothing behind.

    `.gitignore` names `models.auto.toml` exactly. A `.tmp-` file left beside it
    would show up in the operator's `git status` -- which is why `write_overlay`
    removes it, where `orderlog.append` does not have to.
    """
    path = catalog.write_overlay("good/all-clear", root=tmp_path)
    before = path.read_text(encoding="utf-8")

    def refuse(self, target):
        raise OSError("the disk said no")

    monkeypatch.setattr(type(path), "replace", refuse)
    with pytest.raises(OSError, match="the disk said no"):
        catalog.write_overlay("mid/small-context", root=tmp_path)
    assert path.read_text(encoding="utf-8") == before
    assert list(path.parent.glob(".tmp-*")) == []


def test_a_slug_that_would_break_out_of_the_toml_string_raises(tmp_path):
    """A quote in a third party's slug is not an escaping bug.

    It would be a config file that means something else. This is the one
    raise in the module, and it cannot reach the commit path -- nothing
    there calls it.
    """
    with pytest.raises(ValueError, match="not a usable model slug"):
        catalog.write_overlay('a"b', root=tmp_path)
    assert not (tmp_path / OVERLAY_PATH).exists()


def test_llm_does_not_import_the_catalogue():
    """Spec section 2, and the one rule a human misses while reading.

    `bin/herdr-llm` runs on the system interpreter at every commit in
    every repository on this machine. Catalogue code there would be an
    import cost on a path that has no use for it -- and the module reaches
    urllib.parse and datetime that llm.py deliberately does not.
    """
    source = Path(catalog.__file__).with_name("llm.py").read_text(encoding="utf-8")
    assert "catalog" not in source


def test_auto_off_touches_neither_the_network_nor_the_file(tmp_path):
    """`[models].auto = false` is the default, and it is the whole safety.

    Not one byte on the wire and not one on the disk. The daily check
    `workspace up` makes has to cost exactly nothing until somebody ticks
    that box.
    """
    fake = FakeRequest(FIXTURE.read_text(encoding="utf-8"))
    outcome = catalog.check(root=tmp_path, settings=ModelsSettings(), efforts=(), request=fake)
    assert outcome == {"written": False, "model": None, "reason": "auto_off"}
    assert fake.urls == [], "auto is off; nothing may be fetched"
    assert not (tmp_path / OVERLAY_PATH).exists()


def test_apply_fetches_although_auto_is_off(tmp_path):
    """`force=True` is `models apply`, and `auto` is not its gate.

    `auto` is the permission for `up` to run this by itself, never a
    switch on an express command somebody typed.
    """
    fake = FakeRequest(FIXTURE.read_text(encoding="utf-8"))
    outcome = catalog.check(
        root=tmp_path,
        settings=ModelsSettings(),
        efforts=(),
        force=True,
        request=fake,
    )
    assert outcome["written"] is True
    assert outcome["model"] == "cheap/no-benchmarks"
    assert fake.urls, "an express command asks regardless of the config"


def test_a_fresh_overlay_is_not_refetched(tmp_path):
    """The overlay's own mtime IS the stamp.

    No second file and no second piece of state that could go stale on
    its own -- the thing whose age matters is the thing that is asked.
    """
    catalog.write_overlay("good/all-clear", root=tmp_path)
    fake = FakeRequest(FIXTURE.read_text(encoding="utf-8"))
    outcome = catalog.check(
        root=tmp_path,
        settings=ModelsSettings(auto=True),
        efforts=(),
        request=fake,
    )
    assert outcome == {"written": False, "model": None, "reason": "fresh"}
    assert fake.urls == []


def test_an_overlay_past_max_age_h_is_fetched_again(tmp_path):
    path = catalog.write_overlay("good/all-clear", root=tmp_path)
    fake = FakeRequest(FIXTURE.read_text(encoding="utf-8"))
    outcome = catalog.check(
        root=tmp_path,
        settings=ModelsSettings(auto=True, max_age_h=1.0),
        efforts=(),
        now=path.stat().st_mtime + 3601.0,
        request=fake,
    )
    assert outcome["written"] is True
    assert fake.urls


def test_max_age_zero_fetches_every_single_time(tmp_path):
    """`0` means NO threshold here, the reading every `[models]` number has."""
    catalog.write_overlay("good/all-clear", root=tmp_path)
    fake = FakeRequest(FIXTURE.read_text(encoding="utf-8"))
    outcome = catalog.check(
        root=tmp_path,
        settings=ModelsSettings(auto=True, max_age_h=0.0),
        efforts=(),
        request=fake,
    )
    assert outcome["written"] is True
    assert fake.urls


def test_without_an_overlay_there_is_nothing_to_be_fresh(tmp_path):
    fake = FakeRequest(FIXTURE.read_text(encoding="utf-8"))
    outcome = catalog.check(
        root=tmp_path,
        settings=ModelsSettings(auto=True),
        efforts=(),
        request=fake,
    )
    assert outcome["written"] is True
    assert llm_settings(read_settings(tmp_path / OVERLAY_PATH)).model == ("cheap/no-benchmarks")


def test_a_catalogue_that_did_not_answer_leaves_the_file_alone(tmp_path):
    """Never fatal. `up` opens the working day, and a catalogue that did
    not answer is not a failed `up`: the file stays as it is and the
    reason travels in the answer.
    """
    path = catalog.write_overlay("good/all-clear", root=tmp_path)
    before = path.read_text(encoding="utf-8")
    outcome = catalog.check(
        root=tmp_path,
        settings=ModelsSettings(auto=True),
        efforts=(),
        force=True,
        request=FakeRequest(None),
    )
    assert outcome == {"written": False, "model": None, "reason": "no_catalog"}
    assert path.read_text(encoding="utf-8") == before


def test_thresholds_nobody_clears_leave_the_file_alone(tmp_path):
    """`no_candidate` is not `no_catalog`: the endpoint answered fine."""
    path = catalog.write_overlay("good/all-clear", root=tmp_path)
    before = path.read_text(encoding="utf-8")
    outcome = catalog.check(
        root=tmp_path,
        settings=ModelsSettings(auto=True, min_intelligence_index=99.0),
        efforts=(),
        force=True,
        request=FakeRequest(FIXTURE.read_text(encoding="utf-8")),
    )
    assert outcome == {"written": False, "model": None, "reason": "no_candidate"}
    assert path.read_text(encoding="utf-8") == before


def test_a_filesystem_that_refuses_is_a_reason_and_not_a_crash(tmp_path):
    """The one real guard behind "check() never raises", and its only test.

    `workspace up` calls this on a machine we do not control: a read-only
    checkout, a directory owned by someone else, a full disk. Every one of
    those is an OSError out of `write_overlay`, and letting it through
    would turn a price comparison into a failed `up` -- the exact thing
    the never-blocking rule forbids. Dropping the `except OSError` from
    `check()` passes every other test in this file.
    """
    blocked = tmp_path / ".lean-ctx"
    blocked.write_text("not a directory", encoding="utf-8")

    outcome = catalog.check(
        root=tmp_path,
        settings=ModelsSettings(auto=True),
        efforts=(),
        request=FakeRequest(FIXTURE.read_text(encoding="utf-8")),
    )

    assert outcome["written"] is False
    assert outcome["reason"] == "write_failed"
    assert outcome["model"] == "cheap/no-benchmarks", "it says WHICH one it lost"


def test_apply_reports_the_failure_it_had(monkeypatch, tmp_path, capsys):
    """`ok` is the WRITE, not the run. The failure side had no test.

    An `apply` that always reported `ok: true` would tell the operator the
    overlay is current while the file on disk is whatever it was.
    """
    monkeypatch.setattr("lean_herdr.catalog.canonical_root", lambda *a, **kw: tmp_path)
    monkeypatch.setattr("lean_herdr.catalog.fetch", lambda **kw: [])

    assert catalog.main(["apply"]) == 0

    answer = one_line(capsys)
    assert answer["ok"] is False, "no candidate is not a successful apply"
    assert answer["reason"] == "no_candidate"
    assert answer["written"] is False


def test_a_root_that_is_no_repository_is_named_not_swallowed(monkeypatch, capsys):
    """The `BusError` rung. Without it this falls through to `models_crashed:`.

    `canonical_root()` shells out to git; run outside a repository it says
    so, and that sentence is more use to the operator than a crash label
    wrapped around the same words.
    """

    def no_repo(*_args, **_kwargs):
        raise BusError("not a git repository")

    monkeypatch.setattr("lean_herdr.catalog.canonical_root", no_repo)

    assert catalog.main(["check"]) == 0

    answer = one_line(capsys)
    assert answer["ok"] is False
    assert answer["error"] == "not a git repository", "bare, with no prefix"


def test_a_git_that_cannot_answer_is_named_too(monkeypatch, capsys):
    """The same rung, reached by a git that is not on the PATH at all."""

    def missing(*_args, **_kwargs):
        raise FileNotFoundError(2, "No such file or directory", "git")

    monkeypatch.setattr("lean_herdr.bus.subprocess.run", missing)
    assert catalog.main(["check"]) == 0
    answer = one_line(capsys)
    assert answer["ok"] is False
    assert answer["error"].startswith("git_unusable: "), answer["error"]


def test_the_effort_fallbacks_come_from_llm_and_are_not_respelled(monkeypatch, tmp_path, capsys):
    """M3: one definition per rule. Two literals here would drift silently.

    `llm.GENERATE_EFFORT` and `llm.PREREVIEW_EFFORT` are imported, never
    copied -- so moving them has to move what `models` reports. Spelling
    them out as `"minimal"`/`"low"` passes every other test in this file.
    """
    no_network(monkeypatch, tmp_path)
    monkeypatch.setattr(llm, "GENERATE_EFFORT", "high")
    monkeypatch.setattr(llm, "PREREVIEW_EFFORT", "medium")

    assert catalog.main(["check"]) == 0

    assert one_line(capsys)["efforts"] == ["high", "medium"]


def no_network(monkeypatch, root):
    """`main()` has no `request` seam on purpose -- patch the MODULE.

    An unpatched `main(["check"])` would go to the real endpoint and an
    unpatched `main(["apply"])` would write into this very repository.
    """
    monkeypatch.setattr("lean_herdr.catalog.canonical_root", lambda *a, **kw: root)
    monkeypatch.setattr("lean_herdr.catalog.fetch", lambda **kw: sample())


def one_line(capsys) -> dict:
    out = capsys.readouterr().out
    assert out.count("\n") == 1, out
    return json.loads(out)


def test_main_list_shows_the_survivors_and_writes_nothing(monkeypatch, tmp_path, capsys):
    """Both resolved effort levels, because one `[llm].model` serves both jobs."""
    no_network(monkeypatch, tmp_path)
    assert catalog.main(["list", "--limit", "2"]) == 0
    answer = one_line(capsys)
    assert answer["ok"] is True
    assert answer["efforts"] == [llm.GENERATE_EFFORT, llm.PREREVIEW_EFFORT]
    assert answer["total"] == 3, (
        "cheap/no-minimal-effort cannot do `minimal`, mid/no-effort-list lists no efforts"
    )
    assert [entry["id"] for entry in answer["models"]] == [
        "cheap/no-benchmarks",
        "mid/small-context",
    ]
    assert not (tmp_path / OVERLAY_PATH).exists(), "list writes nothing"


def test_main_check_names_the_winner_and_what_runs_today(monkeypatch, tmp_path, capsys):
    no_network(monkeypatch, tmp_path)
    assert catalog.main(["check"]) == 0
    answer = one_line(capsys)
    assert answer["ok"] is True
    assert answer["model"] == "cheap/no-benchmarks"
    assert answer["current"] == llm.DEFAULT_MODEL
    assert not (tmp_path / OVERLAY_PATH).exists(), "check writes nothing"


def test_main_apply_writes_the_overlay_regardless_of_auto(monkeypatch, tmp_path, capsys):
    """No `[models]` section at all here, so `auto` is at its `false` default."""
    no_network(monkeypatch, tmp_path)
    assert catalog.main(["apply"]) == 0
    answer = one_line(capsys)
    assert answer["ok"] is True
    assert answer["reason"] == "written"
    assert llm_settings(read_settings(tmp_path / OVERLAY_PATH)).model == (answer["model"])


def _broken_overlay(root: Path) -> Path:
    path = root / OVERLAY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[llm]\nmodel = 5\n", encoding="utf-8")
    return path


def test_apply_rewrites_a_broken_overlay_instead_of_refusing_it(monkeypatch, tmp_path, capsys):
    """`apply` exists to write this file. Refusing to run over it left no way back."""
    no_network(monkeypatch, tmp_path)
    overlay = _broken_overlay(tmp_path)
    assert catalog.main(["apply"]) == 0
    answer = one_line(capsys)
    assert answer["ok"] is True
    assert answer["reason"] == "written"
    assert llm_settings(read_settings(overlay)).model == answer["model"]


def test_list_does_not_read_the_overlay(monkeypatch, tmp_path, capsys):
    no_network(monkeypatch, tmp_path)
    _broken_overlay(tmp_path)
    assert catalog.main(["list"]) == 0
    assert one_line(capsys)["ok"] is True


def test_check_stays_loud_about_a_broken_overlay_and_fetches_nothing(monkeypatch, tmp_path, capsys):
    """`current` is the one answer that needs the overlay -- and a broken one is named."""
    no_network(monkeypatch, tmp_path)
    _broken_overlay(tmp_path)

    def no_fetch(**_kwargs):
        raise AssertionError("a broken overlay must cost no request")

    monkeypatch.setattr("lean_herdr.catalog.fetch", no_fetch)
    assert catalog.main(["check"]) == 0
    answer = one_line(capsys)
    assert answer["ok"] is False
    assert answer["error"].startswith("config_error:"), answer["error"]
    assert "lean-herdr models apply" in answer["error"], answer["error"]


def test_main_answers_a_bad_command_with_one_json_line(capsys):
    """Exit 2 plus a line on stderr would reach the caller as no output.

    No patching needed and none wanted: the parser raises before
    `canonical_root()`, so this never touches a root or a socket.
    """
    assert catalog.main(["nope"]) == 0
    answer = one_line(capsys)
    assert answer["ok"] is False
    assert answer["error"].startswith("usage_error:")


def test_main_turns_a_broken_config_into_one_json_line(monkeypatch, tmp_path, capsys):
    """A `[models]` typo is reported, never swallowed into a default."""
    no_network(monkeypatch, tmp_path)
    (tmp_path / SETTINGS_PATH).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / SETTINGS_PATH).write_text("[models]\nauto = 1\n", encoding="utf-8")
    assert catalog.main(["check"]) == 0
    answer = one_line(capsys)
    assert answer["ok"] is False
    assert answer["error"].startswith("config_error:")
