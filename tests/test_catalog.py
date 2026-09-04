"""The catalogue, against a recorded answer. No test in here reaches the network."""

import json
from pathlib import Path

import pytest

from lean_herdr import catalog
from lean_herdr.settings import (
    OVERLAY_PATH,
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


def test_fetch_returns_the_recorded_page_as_four_dicts():
    fake = FakeRequest(FIXTURE.read_text(encoding="utf-8"))
    models = catalog.fetch(requires=("reasoning",), request=fake)
    assert models is not None
    assert [entry["id"] for entry in models] == [
        "cheap/no-benchmarks",
        "cheap/no-minimal-effort",
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


def test_write_overlay_writes_the_model_and_never_the_judge(tmp_path):
    """`prereview_model` stays a human's key.

    The judge falls back to `model` anyway, and a second automatically set
    key would undo the separation it exists for.
    """
    path = catalog.write_overlay(
        "good/all-clear", root=tmp_path, stamp="2026-09-04T07:00:00+00:00"
    )
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
