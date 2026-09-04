"""OpenRouter's model catalogue: fetch it, pick one, write the overlay.

One deterministic GET and a comparison of numbers, and deliberately not
more. The endpoint sorts by price server-side and filters by
`supported_parameters` server-side, so "the cheapest model that can
reason and clears these floors" is a url plus a loop. A tool-calling
model in front of that would be paying an LLM to choose query parameters
a flag expresses exactly (spec 1.4).

`llm.py` must NEVER import this module. The commit path runs on the
system interpreter at every commit in every repository on this machine;
catalogue code has no business there. The dependency goes the other way
round and only that way: catalog -> openrouter, catalog -> settings.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lean_herdr import openrouter
from lean_herdr.settings import OVERLAY_PATH, SETTINGS_PATH, ModelsSettings

CATALOG_URL = f"{openrouter.BASE_URL}/models"

#: One page is enough: the sort happens on the server, so the cheapest
#: candidates are at the front and paging would only fetch more expensive
#: ones we would never pick. `total_count` was 261 on 2026-09-04.
CATALOG_LIMIT = 200

#: `workspace up` opens the working day and does not wait longer than this
#: for a price comparison.
CATALOG_TIMEOUT_S = 10.0

#: What a model slug may contain. The catalogue is a third party and this
#: string goes into a TOML file we assemble by hand -- a quote or a newline
#: in it would not be an escaping bug, it would be a config file that means
#: something else. Every slug the endpoint served on 2026-09-04 matches.
SLUG_RE = re.compile(r"[A-Za-z0-9._:/-]+\Z")


def fetch(
    *,
    requires: Sequence[str],
    limit: int = CATALOG_LIMIT,
    timeout_s: float = CATALOG_TIMEOUT_S,
    request: Any = openrouter.request,
) -> list[dict[str, Any]] | None:
    """The catalogue page, cheapest first -- or None. Never raises.

    None means "no usable answer", from every cause there is: the
    transport, an HTTP error, a body that is not the shape we expect.
    Same profile as `llm.complete()`, and for the same reason -- the
    caller turns it into an untouched overlay, not into a failure.

    What is deliberately NOT sent, both measured 2026-09-04: `search=` is
    accepted and then IGNORED (two different queries came back
    byte-identical), so a name filter has to happen on this side; and
    `category=programming` answers HTTP 400.

    No API key. The endpoint answers this without one, and demanding a key
    would make a public catalogue lookup fail on a machine that has none.
    """
    query = {"sort": "pricing-low-to-high", "limit": str(limit)}
    if requires:
        query["supported_parameters"] = ",".join(requires)
    raw = request(
        f"{CATALOG_URL}?{urllib.parse.urlencode(query)}", timeout_s=timeout_s
    )
    if raw is None:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return None
    return [entry for entry in data if isinstance(entry, dict)]


def _number(value: Any) -> float | None:
    """A JSON number or a numeric string as a float. None: not a number.

    The string branch is not defensive programming: `pricing.prompt`
    arrives as `"0.0000001"`, a string, while `context_length` arrives as
    an int. Both are compared against a float threshold here.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _clears(
    entry: dict[str, Any],
    *,
    thresholds: ModelsSettings,
    efforts: Sequence[str],
) -> bool:
    """Every threshold, and the two rules that are easy to miss.

    MISSING EVIDENCE IS NOT A PASS. A model without
    `benchmarks.artificial_analysis` fails a set index threshold, and a
    model that does not list its supported efforts fails the effort check.
    The alternative -- treating "unknown" as "fine" -- would pick exactly
    the models nobody measured.

    `efforts` is a TUPLE, never one value. The overlay writes
    `[llm].model`, and that one key serves BOTH jobs: the commit generator
    on `effort`, and -- down the fallback chain -- the pre-review judge on
    `prereview_effort`. A candidate has to carry BOTH resolved levels, or
    the next commit comes back as an HTTP error that looks exactly like a
    missing key (spec 1.5).
    """
    slug = entry.get("id")
    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        return False
    reasoning = entry.get("reasoning")
    supported = (
        reasoning.get("supported_efforts") if isinstance(reasoning, dict) else None
    )
    if efforts:
        if not isinstance(supported, list):
            return False
        if any(level not in supported for level in efforts):
            return False
    if thresholds.min_context:
        context = _number(entry.get("context_length"))
        if context is None or context < thresholds.min_context:
            return False
    if thresholds.max_prompt_price:
        pricing = entry.get("pricing")
        price = (
            _number(pricing.get("prompt")) if isinstance(pricing, dict) else None
        )
        if price is None or price > thresholds.max_prompt_price:
            return False
    bench = entry.get("benchmarks")
    nested = bench.get("artificial_analysis") if isinstance(bench, dict) else None
    indices = nested if isinstance(nested, dict) else {}
    for key, floor in (
        ("coding_index", thresholds.min_coding_index),
        ("intelligence_index", thresholds.min_intelligence_index),
    ):
        if not floor:
            continue
        value = _number(indices.get(key))
        if value is None or value < floor:
            return False
    return True


def recommend(
    models: Sequence[dict[str, Any]],
    *,
    thresholds: ModelsSettings,
    efforts: Sequence[str],
) -> dict[str, Any] | None:
    """The FIRST entry that clears every threshold, or None.

    First, not best: `fetch()` asked for `pricing-low-to-high`, so the
    first survivor IS the cheapest one. Sorting again here would be a
    second ordering rule that can drift from the server's (M3).
    """
    return next(
        (
            entry
            for entry in models
            if _clears(entry, thresholds=thresholds, efforts=efforts)
        ),
        None,
    )


def write_overlay(model: str, *, root: Path, stamp: str | None = None) -> Path:
    """Write `models.auto.toml` WHOLE. Returns the path. Raises on a bad slug.

    Never edited in place, and that is not a shortcut: the stdlib has no
    TOML writer, and `tomli_w` is ABSENT on the system interpreter this
    project's commit path runs on. A file we generate completely, every
    time, needs neither -- and nothing here ever parses one back before
    overwriting it.

    Only `model` is written, NEVER `prereview_model`. The judge falls back
    to `model` anyway, and a second automatically set key would undo the
    very separation it exists for: raising `model` to make the judge
    smarter raises the generator's bill on every commit. Whoever wants a
    different judge sets `prereview_model` by hand, and no automatic run
    touches it.

    The ValueError is the one raise in this module, and it cannot reach
    the commit path: nothing on that path calls this. `check()` catches
    it, so the express commands do not crash either.
    """
    if not SLUG_RE.match(model):
        raise ValueError(f"not a usable model slug: {model!r}")
    when = stamp or datetime.now(UTC).isoformat(timespec="seconds")
    path = Path(root) / OVERLAY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# written by `lean-herdr models` on {when}. Do not edit --\n"
        "# the next run overwrites this file. Your own choice belongs in\n"
        f"# {SETTINGS_PATH}, which wins over this one.\n"
        "[llm]\n"
        f'model = "{model}"\n',
        encoding="utf-8",
    )
    return path
