"""OpenRouter's model catalogue: fetch it, pick one, write the overlay.

One deterministic GET and a comparison of numbers, and deliberately not
more. The endpoint sorts by price server-side and filters by
`supported_parameters` server-side, so "the cheapest model that can
reason and clears these floors" is a url plus a loop. A tool-calling
model in front of that would be paying an LLM to choose query parameters
a flag expresses exactly (spec 1.4).

`llm.py` must NEVER import this module. The commit path runs on the
system interpreter at every commit in every repository on this machine;
catalogue code has no business there. The dependency runs the other way
and only that way: catalog -> openrouter, settings, llm and dispatch --
the last two for the CLI at the bottom, which reuses their constants and
their parser rather than growing a third copy.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
import urllib.parse
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lean_herdr import llm, openrouter
from lean_herdr.bus import BusError, canonical_root
from lean_herdr.dispatch import UsageError, _Parser
from lean_herdr.settings import (
    OVERLAY_PATH,
    SETTINGS_PATH,
    ModelsSettings,
    SettingsError,
    llm_settings_layered,
    models_settings,
    read_settings,
)

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
    raw = request(f"{CATALOG_URL}?{urllib.parse.urlencode(query)}", timeout_s=timeout_s)
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

    NaN and the infinities are NOT numbers for this purpose, and that is
    the same rule as MISSING EVIDENCE IS NOT A PASS one level up. Every
    comparison against a NaN is False, so a NaN index would CLEAR a floor
    and a NaN price would CLEAR a cap -- junk evidence doing exactly what
    absent evidence is forbidden to do. `json.loads` accepts a bare `NaN`
    or `Infinity` by default, so this arrives from a third party, not only
    from a hand-built dict.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
    else:
        return None
    return number if math.isfinite(number) else None


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
    supported = reasoning.get("supported_efforts") if isinstance(reasoning, dict) else None
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
        price = _number(pricing.get("prompt")) if isinstance(pricing, dict) else None
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
        (entry for entry in models if _clears(entry, thresholds=thresholds, efforts=efforts)),
        None,
    )


def write_overlay(model: str, *, root: Path, stamp: str | None = None) -> Path:
    """Write `models.auto.toml` WHOLE. Returns the path. Raises on a bad slug.

    Never edited in place, and that is not a shortcut: the stdlib has no
    TOML writer, and `tomli_w` is ABSENT on the system interpreter this
    project's commit path runs on. A file we generate completely, every
    time, needs neither -- and nothing here ever parses one back before
    overwriting it.

    WHOLE also means never HALF: the text goes to `.tmp-models.auto.toml`
    beside the overlay, and `Path.replace` swaps it in -- the recipe of
    `orderlog.append`, without `fsync` for the same reason. A hard kill
    between the two leaves the temp file behind and the overlay untouched.

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
    tmp = path.with_name(f".tmp-{path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        tmp.write_text(
            f"# written by `lean-herdr models` on {when}. Do not edit --\n"
            "# the next run overwrites this file. Your own choice belongs in\n"
            f"# {SETTINGS_PATH}, which wins over this one.\n"
            "[llm]\n"
            f'model = "{model}"\n',
            encoding="utf-8",
        )
        tmp.replace(path)
    except OSError:
        # `.gitignore` names the overlay EXACTLY, so a temp file left here
        # would sit in the operator's `git status`. `orderlog.append` may
        # leave its own behind; this one may not.
        tmp.unlink(missing_ok=True)
        raise
    return path


#: The reasons `check()` can give. Every one of them leaves the overlay
#: exactly as it was; only `written` changes a file.
#:   auto_off      -- [models].auto is false and this was not `apply`
#:   fresh         -- the overlay is younger than max_age_h
#:   no_catalog    -- the endpoint gave nothing usable
#:   no_candidate  -- nobody cleared the thresholds
#:   bad_slug      -- the winner's id is not one we will write
#:   write_failed  -- the filesystem said no
#:   written       -- a new overlay is on disk


def _outcome(reason: str, *, model: str | None = None, written: bool = False) -> dict[str, Any]:
    return {"written": written, "model": model, "reason": reason}


def check(
    *,
    root: Path,
    settings: ModelsSettings,
    efforts: Sequence[str],
    force: bool = False,
    now: float | None = None,
    request: Any = openrouter.request,
) -> dict[str, Any]:
    """Fetch, recommend, write -- or say why it did none of it. Never raises.

    The STAMP is the overlay's own mtime. No second file and no second
    piece of state that can go stale on its own.

    `force=True` is `models apply`: an express command, which runs
    regardless of `[models].auto` and regardless of the age. Without it
    this is the daily check `workspace up` makes, and `auto = false` --
    the default -- means it does nothing at all and costs nothing.

    Nothing here is allowed to be fatal. `up` opens the working day, and
    a catalogue that did not answer is not a failed `up`: the file stays
    as it is, the reason travels in the answer, and the built-in default
    carries the day as it did before.
    """
    if not (settings.auto or force):
        return _outcome("auto_off")
    path = Path(root) / OVERLAY_PATH
    if not force and settings.max_age_h:
        try:
            age_h = ((now or time.time()) - path.stat().st_mtime) / 3600.0
        except OSError:
            # No file yet -- or one we cannot stat. Either way there is
            # nothing to be fresh, so fetch.
            age_h = None
        if age_h is not None and age_h < settings.max_age_h:
            return _outcome("fresh")
    models = fetch(requires=settings.requires, request=request)
    if models is None:
        return _outcome("no_catalog")
    winner = recommend(models, thresholds=settings, efforts=efforts)
    if winner is None:
        return _outcome("no_candidate")
    slug = str(winner.get("id") or "")
    try:
        write_overlay(slug, root=Path(root))
    except ValueError:
        return _outcome("bad_slug", model=slug)
    except OSError:
        return _outcome("write_failed", model=slug)
    return _outcome("written", model=slug, written=True)


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(
        prog="lean-herdr models",
        description="Show, check or apply OpenRouter's cheapest fitting model.",
    )
    p.add_argument("command", choices=("list", "check", "apply"))
    p.add_argument(
        "--limit",
        type=int,
        default=10,
        help="list: how many survivors to show (default 10)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    """Output: one JSON line on stdout. Exit ALWAYS 0.

    `list` and `check` touch the network and write nothing. `apply`
    writes, and it writes regardless of `[models].auto`: `auto` is the
    permission for `up` to do this by itself, never a gate on an express
    command somebody typed.
    """
    result: dict[str, Any]
    try:
        args = build_parser().parse_args(argv)
        root = canonical_root()
        data = read_settings(root / SETTINGS_PATH)
        cfg = models_settings(data)
        llm_cfg = llm_settings_layered(root, data)
        # BOTH resolved levels, because the one key the overlay writes
        # serves both jobs. The fallbacks are llm.py's constants, and they
        # are imported rather than respelled -- a second spelling would
        # drift the day one of them changes (M3).
        efforts = (
            llm_cfg.effort or llm.GENERATE_EFFORT,
            llm_cfg.prereview_effort or llm.PREREVIEW_EFFORT,
        )
        if args.command == "list":
            models = fetch(requires=cfg.requires)
            if models is None:
                result = {"ok": False, "error": "no_catalog"}
            else:
                survivors = [
                    entry for entry in models if _clears(entry, thresholds=cfg, efforts=efforts)
                ]
                result = {
                    "ok": True,
                    "efforts": list(efforts),
                    "total": len(survivors),
                    "models": [
                        {
                            "id": entry.get("id"),
                            "prompt_price": (entry.get("pricing") or {}).get("prompt"),
                            "context_length": entry.get("context_length"),
                        }
                        for entry in survivors[: args.limit]
                    ],
                }
        elif args.command == "check":
            models = fetch(requires=cfg.requires)
            if models is None:
                result = {"ok": False, "error": "no_catalog"}
            else:
                winner = recommend(models, thresholds=cfg, efforts=efforts)
                result = {
                    "ok": winner is not None,
                    "model": None if winner is None else winner.get("id"),
                    "efforts": list(efforts),
                    "current": llm_cfg.model or llm.DEFAULT_MODEL,
                }
        else:
            outcome = check(root=root, settings=cfg, efforts=efforts, force=True)
            result = {"ok": outcome["written"], **outcome}
    except UsageError as exc:
        result = {"ok": False, "error": f"usage_error: {exc}"}
    except SettingsError as exc:
        result = {"ok": False, "error": f"config_error: {exc}"}
    except BusError as exc:
        result = {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 -- never abort the caller
        result = {"ok": False, "error": f"models_crashed: {exc}"}
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    return 0
