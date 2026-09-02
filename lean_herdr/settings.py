"""`.config/lean-herdr.toml` -> RoleSettings. Precedence: CLI > file > default.

`tomllib` is stdlib since 3.11 -- no new runtime dependency.

Deliberately separate from config.py, which reads the HERDR_* environment
for the plugin handlers: different purpose, different lifetime. Without the
file the project behaves exactly as it does without this module; a file that
IS there but is wrong is an error and never stays silent.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any

#: RELATIVE to the repo root, not to $PWD. The caller joins it onto
#: canonical_root() -- otherwise the config silently fails to load as soon as
#: bin/herdr-dispatch runs from a subdirectory, and the promise "a wrong file
#: never stays silent" would be broken.
SETTINGS_PATH = Path(".config") / "lean-herdr.toml"

#: Per-role default -- measured fixed cost per step:
#: minimal 2,711 / standard 4,920 / power 11,559 tokens.
PROFILE_BY_ROLE = {"orchestrator": "minimal"}
DEFAULT_PROFILE = "standard"

#: `herdr pane split --direction` knows exactly these two.
DIRECTIONS = ("right", "down")


class SettingsError(RuntimeError):
    """The config is present but unusable.

    Whoever writes `direction = "links"` and silently gets `right` will hunt
    the bug in the wrong place. A MISSING file is fine -- that is the normal
    case.
    """


@dataclass(frozen=True)
class RoleSettings:
    direction: str = "right"
    ratio: float | None = None
    focus: bool = False
    name_template: str = "{role}-{branch}"
    profile: str = DEFAULT_PROFILE
    ready_timeout_s: float = 45.0


_TYPES: dict[str, Any] = {
    "direction": str,
    "ratio": (float, int, type(None)),
    "focus": bool,
    "name_template": str,
    "profile": str,
    "ready_timeout_s": (float, int),
}

ALLOWED = frozenset(f.name for f in fields(RoleSettings))


def read_settings(path: str | Path | None = None) -> dict[str, Any]:
    """The file as a raw dict. Missing: {}. Broken: SettingsError."""
    p = Path(path) if path is not None else SETTINGS_PATH
    try:
        raw = p.read_bytes()
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise SettingsError(f"settings unreadable at {p}: {exc}") from exc
    try:
        return tomllib.loads(raw.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise SettingsError(f"settings malformed at {p}: {exc}") from exc


def _check_types(block: dict[str, Any], role: str) -> None:
    unknown = sorted(set(block) - ALLOWED)
    if unknown:
        raise SettingsError(
            f"{role}: unknown keys {unknown}; allowed: {sorted(ALLOWED)}"
        )
    for key, value in block.items():
        if not isinstance(value, _TYPES[key]):
            raise SettingsError(
                f"{role}.{key}: {value!r} is {type(value).__name__}"
            )


def _validate(values: RoleSettings, role: str) -> None:
    if values.direction not in DIRECTIONS:
        raise SettingsError(
            f"{role}: direction={values.direction!r}, allowed: {list(DIRECTIONS)}"
        )
    if values.ratio is not None and not 0.0 < float(values.ratio) < 1.0:
        raise SettingsError(f"{role}: ratio={values.ratio!r} is not between 0 and 1")
    if float(values.ready_timeout_s) <= 0:
        raise SettingsError(f"{role}: ready_timeout_s={values.ready_timeout_s!r} <= 0")
    # The reuse key is (branch, role). Drop either placeholder and a reviewer
    # dispatch hits the running builder of that branch -- or two branches
    # end up sharing one worker.
    if "{role}" not in values.name_template or "{branch}" not in values.name_template:
        raise SettingsError(
            f"{role}: name_template={values.name_template!r} "
            "must contain {role} AND {branch}"
        )
    try:
        values.name_template.format(role="r", branch="b")
    except (KeyError, IndexError, ValueError) as exc:
        raise SettingsError(
            f"{role}: name_template={values.name_template!r} is not formattable: {exc}"
        ) from exc


def _overlay(base: RoleSettings, block: Any, role: str) -> RoleSettings:
    if not isinstance(block, dict):
        raise SettingsError(
            f"{role}: section is not a table, but {type(block).__name__}"
        )
    _check_types(block, role)
    merged = replace(base, **block)
    _validate(merged, role)
    return merged


def settings_for(role: str, data: dict[str, Any] | None = None) -> RoleSettings:
    """Default -> `[default]` -> `[roles.<role>]`. Each layer may override.

    `[default]` in the file beats the built-in per-role default too: to
    change only the builder, write it under `[roles.builder]`.
    """
    table = data or {}
    values = RoleSettings(profile=PROFILE_BY_ROLE.get(role, DEFAULT_PROFILE))
    for block in (table.get("default"), (table.get("roles") or {}).get(role)):
        if block is not None:
            values = _overlay(values, block, role)
    return values
