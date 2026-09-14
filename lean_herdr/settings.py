"""`.lean-ctx/lean-herdr/config.toml` -> RoleSettings. Precedence: CLI > file > default.

`tomllib` is stdlib since 3.11 -- no new runtime dependency.

Deliberately separate from config.py, which reads the HERDR_* environment
for the plugin handlers: different purpose, different lifetime. Without the
file the project behaves exactly as it does without this module; a file that
IS there but is wrong is an error and never stays silent.

`load_jsonc` at the bottom reads a SECOND configuration file in a second
format -- `opencode.jsonc`, which belongs to opencode and not to us. It sits
here because this is the module that owns reading configuration, and because
two copies of one comment stripper would drift (M3).
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any

#: RELATIVE to the repo root, not to $PWD. The caller joins it onto
#: canonical_root() -- otherwise the config silently fails to load as soon
#: as `lean-herdr dispatch` runs from a subdirectory, and the promise "a
#: wrong file never stays silent" would be broken.
#:
#: `.lean-ctx/<tool>/` is the convention of this tool family -- lean-md is
#: already there. Not `.config/`: that directory belongs to whoever else
#: writes into it, and `init` has to be able to write ours without
#: touching theirs.
SETTINGS_PATH = Path(".lean-ctx") / "lean-herdr" / "config.toml"

#: RELATIVE to the repo root, exactly like SETTINGS_PATH, and joined onto
#: canonical_root() by whoever reads it. Written by `lean-herdr models
#: apply` and by the daily check in `workspace up` -- never by hand.
#:
#: It sits BESIDE config.toml because that is where an operator looks for
#: configuration. That choice has a price the alternative would not have:
#: the file is machine-local and must never be shared, so a .gitignore
#: rule has to name it. A blanket `.lean-ctx/` would untrack the four
#: files in there that are tracked on purpose, so the rule has to hit this
#: one name (task 9).
OVERLAY_PATH = Path(".lean-ctx") / "lean-herdr" / "models.auto.toml"

#: RELATIVE to the repo root, like SETTINGS_PATH. `dispatch` joins them onto
#: canonical_root() before it checks a file or hands one to a pane: a relative
#: path would resolve in the pane's cwd -- the worktree, which need not carry it.
ROLE_PROMPTS = Path(".lean-ctx") / "lean-herdr" / "roles"
CLAUDE_SETTINGS = Path(".lean-ctx") / "lean-herdr" / "claude"

#: Per-role default -- measured fixed cost per step:
#: minimal 2,711 / standard 4,920 / power 11,559 tokens.
PROFILE_BY_ROLE = {"orchestrator": "minimal"}
DEFAULT_PROFILE = "standard"

#: The orchestrator's built-in runtime, so the keystroke route
#: (handlers.handle_bootstrap) keeps behaving exactly as it does today
#: without reading a thing. Workers have NO built-in kind: they say it,
#: by flag or by config, or `dispatch` refuses -- a worker started on the
#: wrong runtime resolves a role prompt that is not written for it.
KIND_BY_ROLE = {"orchestrator": "opencode"}

#: `herdr pane split --direction` knows exactly these two.
DIRECTIONS = ("right", "down")


class SettingsError(RuntimeError):
    """The config is present but unusable.

    Whoever writes `direction = "links"` and silently gets `right` will hunt
    the bug in the wrong place. A MISSING file is fine -- that is the normal
    case.
    """


class OverlayError(SettingsError):
    """`models.auto.toml` is unusable -- the file a machine wrote, not the operator.

    A SettingsError, so every loud path that catches one reports this one too.
    Its own class for the one reader that must tell the two apart:
    `llm.file_settings()` drops a broken overlay and keeps config.toml, instead
    of losing both.
    """


@dataclass(frozen=True)
class RoleSettings:
    direction: str = "right"
    ratio: float | None = None
    focus: bool = False
    name_template: str = "{role}-{branch}"
    profile: str = DEFAULT_PROFILE
    ready_timeout_s: float = 45.0
    #: "" is "not set", the same spelling LlmSettings uses, so a caller
    #: can fall through with a plain `or`. `None` would need a second
    #: spelling for one state and a second check at every level.
    model: str = ""
    kind: str = ""
    #: Only the role behind `review` has a reader for this one, and that is the
    #: same price `direction` already pays under [roles.orchestrator]: ALLOWED is
    #: built from these fields, so every key is legal under every role. Setting it
    #: elsewhere changes nothing -- it does not quietly change something else
    #: either. It was `shares_builder_model` and has no alias: the old name is an
    #: unknown key now, and says so.
    shares_reviewed_model: bool = False


_TYPES: dict[str, Any] = {
    "direction": str,
    "ratio": (float, int, type(None)),
    "focus": bool,
    "name_template": str,
    "profile": str,
    "ready_timeout_s": (float, int),
    "model": str,
    "kind": str,
    "shares_reviewed_model": bool,
}

#: Keys where a bool would slip through `_TYPES`: `isinstance(True, int)` is
#: True. `ready_timeout_s = true` would pass `float(True) == 1.0 > 0` too and
#: become a live one-second timeout -- a wrong value silently turned into a
#: working one. `ratio = true` its 0..1 bounds would catch, but the message
#: would blame the range instead of the type.
_NO_BOOL = ("ratio", "ready_timeout_s")

ALLOWED = frozenset(f.name for f in fields(RoleSettings))

#: The only six keys the top level of the file may carry.
ROOT_KEYS = ("default", "roles", "llm", "workspace", "models", "routing")

#: The two runtimes a role prompt is written for. `dispatch --kind` and
#: `[roles.<role>].kind` read the SAME tuple -- two lists would let a
#: value pass one gate and fail the other (M3).
KINDS = ("claude", "opencode")

#: The two works TP1 builds in. `[routing]` lays itself over them, so a project
#: without the table dispatches exactly as it did by role name.
ROUTING_BUILTIN = {"implement": "builder", "review": "reviewer"}

#: Works that are stages of a run, not work a plan hands out. `plan`,
#: `plan-review` and `integrate` get their built-in roles with TP2 and TP3;
#: until then a call without a `[routing]` line for one is a SettingsError.
#: `model_warnings` pairs the role behind `review` with the role behind every
#: work that is NOT one of these.
STAGES = ("plan", "plan-review", "review", "integrate")

#: A work name, and a role name. The role becomes part of the herdr agent
#: name, so it is held to what that name may carry; its length is TP3's.
WORK_RE = re.compile(r"[a-z][a-z0-9-]*")
ROLE_RE = re.compile(r"[a-z][a-z0-9_-]*")

#: The herdr agent name of the orchestrator, and the sender the workers
#: trust. Deliberately NOT a config key: three places must agree on it --
#: this constant, the line `ORCHESTRATOR = orch` in both role prompts, and
#: test_roles.py::test_the_role_prompts_trust_the_name_dispatch_actually_stamps.
#: A key would break that triad without anyone asking for it.
#:
#: It lives HERE, in the leaf module, and not in handlers.py where it
#: started: `handlers` now imports `workspace`, `workspace` imports
#: `dispatch`, and `dispatch` reaches `ordercmd` -- which read this name at
#: IMPORT time. Left in handlers.py that chain closes into a cycle that
#: crashes on the first import, not in a test.
ORCHESTRATOR_AGENT = "orch"


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
        raise SettingsError(f"{role}: unknown keys {unknown}; allowed: {sorted(ALLOWED)}")
    for key, value in block.items():
        sneaky_bool = key in _NO_BOOL and isinstance(value, bool)
        if sneaky_bool or not isinstance(value, _TYPES[key]):
            raise SettingsError(f"{role}.{key}: {value!r} is {type(value).__name__}")


def _validate(values: RoleSettings, role: str) -> None:
    if values.direction not in DIRECTIONS:
        raise SettingsError(f"{role}: direction={values.direction!r}, allowed: {list(DIRECTIONS)}")
    if values.kind and values.kind not in KINDS:
        raise SettingsError(f"{role}: kind={values.kind!r}, allowed: {list(KINDS)}")
    if values.ratio is not None and not 0.0 < float(values.ratio) < 1.0:
        raise SettingsError(f"{role}: ratio={values.ratio!r} is not between 0 and 1")
    if float(values.ready_timeout_s) <= 0:
        raise SettingsError(f"{role}: ready_timeout_s={values.ready_timeout_s!r} <= 0")
    # The reuse key is (branch, role). Drop either placeholder and a reviewer
    # dispatch hits the running builder of that branch -- or two branches
    # end up sharing one worker.
    if "{role}" not in values.name_template or "{branch}" not in values.name_template:
        raise SettingsError(
            f"{role}: name_template={values.name_template!r} must contain {{role}} AND {{branch}}"
        )
    try:
        values.name_template.format(role="r", branch="b")
    except (KeyError, IndexError, ValueError) as exc:
        raise SettingsError(
            f"{role}: name_template={values.name_template!r} is not formattable: {exc}"
        ) from exc


def _overlay(base: RoleSettings, block: Any, role: str) -> RoleSettings:
    if not isinstance(block, dict):
        raise SettingsError(f"{role}: section is not a table, but {type(block).__name__}")
    _check_types(block, role)
    merged = replace(base, **block)
    _validate(merged, role)
    return merged


def _check_routing(routing: Any) -> None:
    """`[routing]`: work name -> role name, each spelled the way its pattern allows.

    Called from `_check_root`, so EVERY reader of the file meets a broken line --
    a call by role name as much as `--work`.
    """
    if not isinstance(routing, dict):
        raise SettingsError(f"routing: section is not a table, but {type(routing).__name__}")
    for work, role in routing.items():
        if not WORK_RE.fullmatch(work):
            raise SettingsError(f"routing: work {work!r} does not match {WORK_RE.pattern}")
        if not isinstance(role, str) or not ROLE_RE.fullmatch(role):
            raise SettingsError(f"routing.{work}: {role!r} is no role name ({ROLE_RE.pattern})")


def _check_root(table: Any) -> dict[str, Any]:
    """Top level: everything in `ROOT_KEYS`, `roles` a table, `routing` checked line by line.

    Reading just the known sections would let `[defaults]`, `[role.x]` or
    a key without any section header evaporate in silence -- the operator gets
    plain defaults and never learns that the file did nothing. The type check
    keeps a wrong `roles` an error the caller can catch, not an AttributeError.
    """
    if not isinstance(table, dict):
        raise SettingsError(f"settings: root is not a table, but {type(table).__name__}")
    unknown = sorted(set(table) - set(ROOT_KEYS))
    if unknown:
        raise SettingsError(
            f"settings: unknown top-level keys {unknown}; allowed: {sorted(ROOT_KEYS)}"
        )
    roles = table.get("roles")
    if roles is not None and not isinstance(roles, dict):
        raise SettingsError(f"settings: roles is not a table, but {type(roles).__name__}")
    routing = table.get("routing")
    if routing is not None:
        _check_routing(routing)
    return table


def settings_for(role: str, data: dict[str, Any] | None = None) -> RoleSettings:
    """Default -> `[default]` -> `[roles.<role>]`. Each layer may override.

    `[default]` in the file beats the built-in per-role default too: to
    change only the builder, write it under `[roles.builder]`.
    """
    table = _check_root({} if data is None else data)
    values = RoleSettings(
        profile=PROFILE_BY_ROLE.get(role, DEFAULT_PROFILE),
        kind=KIND_BY_ROLE.get(role, ""),
    )
    for block in (table.get("default"), (table.get("roles") or {}).get(role)):
        if block is not None:
            values = _overlay(values, block, role)
    return values


def work_roles(data: dict[str, Any] | None = None) -> dict[str, str]:
    """Every work that has a role: the built-in ones, `[routing]` laid over them."""
    table = _check_root({} if data is None else data)
    return {**ROUTING_BUILTIN, **(table.get("routing") or {})}


def role_for_work(work: str, data: dict[str, Any] | None = None) -> str:
    """`[routing]` > built-in > SettingsError -- one resolution for dispatch and check."""
    role = work_roles(data).get(work)
    if role is None:
        raise SettingsError(f"no role for work {work!r}")
    return role


def model_warnings(data: dict[str, Any] | None = None) -> list[str]:
    """What a config earns without being wrong. A list, empty is normal.

    The review's value is that it runs on a DIFFERENT model -- different blind
    spots. So the role behind `review` is compared with the role behind every
    work that is not a stage: `implement` and every work of the project's own.
    One line per role on the same, non-empty model; none where both works name
    one role, none when the reviewing role sets `shares_reviewed_model`. A
    warning, never a refusal: two workers on one model is a legitimate thing to
    want, it just must not happen by accident.

    Raises whatever `settings_for()` raises. Both callers read the file once and
    validated already; a second, quieter error path here would be a second rule
    for one thing (M3).
    """
    routes = work_roles(data)
    checker = routes["review"]
    judge = settings_for(checker, data)
    if not judge.model or judge.shares_reviewed_model:
        return []
    reviewed = sorted({role for work, role in routes.items() if work not in STAGES})
    return [
        (
            f"{role} and {checker} both run on {judge.model!r} -- the {checker} "
            "earns its keep by having different blind spots. Set "
            f"[roles.{checker}].shares_reviewed_model = true if this is meant."
        )
        for role in reviewed
        if role != checker and settings_for(role, data).model == judge.model
    ]


#: OpenRouter's reasoning levels. A typo would otherwise reach the
#: endpoint verbatim, come back as an HTTP error, and be swallowed into
#: a fallback commit message -- a wrong value that looks exactly like a
#: missing key.
EFFORTS = ("minimal", "low", "medium", "high")


@dataclass(frozen=True)
class LlmSettings:
    """`[llm]` -- the commit generator and the pre-review judge.

    Deliberately NOT part of RoleSettings. Those describe how a pane is
    split and what a worker is called, and dispatch.py reads every one
    of them. These four are read by llm.py alone -- and by a process
    worktrunk starts in repositories this project does not own.

    The empty string means "not set", so the resolution chain in llm.py
    stays a plain first-non-empty. `None` would need a second spelling
    for the same state and a second check at every level.
    """

    model: str = ""
    prereview_model: str = ""
    effort: str = ""
    prereview_effort: str = ""


LLM_ALLOWED = frozenset(f.name for f in fields(LlmSettings))


def llm_settings(data: dict[str, Any] | None = None) -> LlmSettings:
    """`[llm]` out of the settings file. No section: every default.

    Same strictness as settings_for(): an unknown key, a wrong type or
    an effort level OpenRouter does not know is a SettingsError, never a
    silent fallback. Whoever writes `effort = "mininal"` must not go
    hunting for the bug in the model.

    Note who catches it, because the two consumers differ on purpose:
    `llm.file_settings()` swallows this and takes the defaults -- it
    serves `lean-herdr llm generate`, where a raise would abort the
    commit worktrunk is in the middle of. `dispatch.main()` calls this
    function directly and lets it through as `config_error:` -- there
    the orchestrator reads the complaint. Without that second call site
    a typo in `[llm]` would be silent everywhere.
    """
    table = _check_root({} if data is None else data)
    block = table.get("llm")
    if block is None:
        return LlmSettings()
    if not isinstance(block, dict):
        raise SettingsError(f"llm: section is not a table, but {type(block).__name__}")
    unknown = sorted(set(block) - LLM_ALLOWED)
    if unknown:
        raise SettingsError(f"llm: unknown keys {unknown}; allowed: {sorted(LLM_ALLOWED)}")
    for key, value in block.items():
        if not isinstance(value, str):
            raise SettingsError(f"llm.{key}: {value!r} is {type(value).__name__}, not str")
    values = LlmSettings(**block)
    for key in ("effort", "prereview_effort"):
        level = getattr(values, key)
        if level and level not in EFFORTS:
            raise SettingsError(f"llm.{key}={level!r}, allowed: {list(EFFORTS)}")
    return values


def llm_settings_layered(root: str | Path, data: dict[str, Any] | None = None) -> LlmSettings:
    """`models.auto.toml` UNDER `config.toml`. One function, both consumers.

    The overlay is what the daily check wrote; `[llm]` in config.toml is
    what the operator wrote, and the operator wins. That order is the
    whole reason the overlay is a second FILE and not surgery on the
    first: an explicit `model` in config.toml survives every check, and
    no automatic run has to parse and preserve a human's line.

    The overlay gives `model` and NOTHING else. The daily check writes that
    one key, and the THE TWO CHAINS block in llm.py knows the overlay as a
    level for `model` only. Any other `[llm]` field comes out of config.toml
    or stays "" -- whatever else a hand put into the overlay has no effect.

    A broken OVERLAY raises OverlayError, a SettingsError: every loud caller
    reports it as before, and `llm.file_settings()` alone can tell it apart and
    keep config.toml. config.toml is read first, so a file that is broken in
    both places names the operator's own file.

    An empty string in the foreground still means "not set" -- the same
    rule `llm._first()` follows -- so `model = ""` in config.toml lets the
    overlay through instead of blanking it.

    `data` is config.toml ALREADY READ. `dispatch.main()` hands it in
    because it read the file for its RoleSettings anyway, and
    `test_main_reads_config_toml_exactly_once_per_call` counts that read.

    BOTH consumers must call this -- `llm.file_settings()` and
    `dispatch.main()`. If only one read the overlay, the commit generator
    and the pre-review judge would run on different models the moment one
    exists: exactly the drift the THE TWO CHAINS block exists to prevent.
    """
    base = Path(root)
    above = llm_settings(read_settings(base / SETTINGS_PATH) if data is None else data)
    try:
        below = llm_settings(read_settings(base / OVERLAY_PATH))
    except SettingsError as exc:
        raise OverlayError(
            f"{OVERLAY_PATH}: {exc} -- `lean-herdr models apply` rewrites it"
        ) from exc
    # The overlay went through `llm_settings()` WHOLE above: an unknown
    # key, a wrong type or an invalid value is already a SettingsError.
    # Only now is `model` lifted out of it. A valid foreign field is
    # ignored, not refused -- refusing it would fail `dispatch` over a
    # file that says nothing wrong, only nothing that counts.
    return replace(above, model=above.model or below.model)


@dataclass(frozen=True)
class ModelsSettings:
    """`[models]` -- what the daily catalogue check is allowed to do.

    `auto = false` is the default and it is the whole safety: without
    that one box ticked, nothing is fetched and nothing is written, and
    `workspace up` does exactly what it does today. `models check` and
    `models apply` are express commands and run regardless.

    Every threshold defaults to "no threshold". `max_prompt_price = 0.0`
    therefore means NO LIMIT, not "free models only" -- the reading that
    would be a nasty surprise, and the one an operator has to be told
    about in the template comment.

    `requires` goes to the endpoint's `supported_parameters` filter and
    deliberately does NOT carry `tools`: `[llm].model` serves two pure
    completion jobs without a single tool, and demanding tool support
    would rule out cheap candidates for no gain. `reasoning` is in there
    because `complete()` always sends a reasoning block and the endpoint
    refuses to have it switched off.
    """

    auto: bool = False
    max_age_h: float = 24.0
    min_coding_index: float = 0.0
    min_intelligence_index: float = 0.0
    max_prompt_price: float = 0.0
    min_context: int = 0
    requires: tuple[str, ...] = ("reasoning",)


MODELS_ALLOWED = frozenset(f.name for f in fields(ModelsSettings))

#: `[models]` numbers where a bool must not slip through: `isinstance(True,
#: int)` is True, so `min_context = true` would become a live threshold of
#: 1. Same defect `_NO_BOOL` catches for the role table, same cure.
_MODELS_NUMBERS = (
    "max_age_h",
    "min_coding_index",
    "min_intelligence_index",
    "max_prompt_price",
    "min_context",
)


def models_settings(data: dict[str, Any] | None = None) -> ModelsSettings:
    """`[models]` out of the settings file. No section: every default.

    Same strictness as everywhere in this module: an unknown key, a wrong
    type or a negative threshold is a SettingsError, never a silent
    fallback. A threshold nobody meant is worse than no threshold -- it
    would quietly pick a different model and cost money for a reason
    nobody can find.
    """
    table = _check_root({} if data is None else data)
    block = table.get("models")
    if block is None:
        return ModelsSettings()
    if not isinstance(block, dict):
        raise SettingsError(f"models: section is not a table, but {type(block).__name__}")
    unknown = sorted(set(block) - MODELS_ALLOWED)
    if unknown:
        raise SettingsError(f"models: unknown keys {unknown}; allowed: {sorted(MODELS_ALLOWED)}")
    values = dict(block)
    if "auto" in values and not isinstance(values["auto"], bool):
        raise SettingsError(
            f"models.auto: {values['auto']!r} is {type(values['auto']).__name__}, not bool"
        )
    for key in _MODELS_NUMBERS:
        if key not in values:
            continue
        number = values[key]
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            raise SettingsError(
                f"models.{key}: {number!r} is {type(number).__name__}, not a number"
            )
        if number < 0:
            raise SettingsError(f"models.{key}={number!r} is negative")
    if "min_context" in values and not isinstance(values["min_context"], int):
        raise SettingsError(f"models.min_context={values['min_context']!r} is not a whole number")
    if "requires" in values:
        wanted = values["requires"]
        if not isinstance(wanted, list) or not all(isinstance(item, str) for item in wanted):
            raise SettingsError(f"models.requires={wanted!r} is not a list of strings")
        # A tuple, because the dataclass is frozen and a list in a frozen
        # dataclass is a mutable field on an immutable object -- the sort
        # of thing that works until somebody appends to it.
        values["requires"] = tuple(wanted)
    return ModelsSettings(**values)


@dataclass(frozen=True)
class WorkspaceSettings:
    """`[workspace]` -- what `lean-herdr workspace up` needs to start.

    One key, and that is the whole table now: `kind` and `model` moved to
    `[roles.orchestrator]`, where the other two things
    `start_orchestrator` reads already live (`profile`,
    `ready_timeout_s`). Splitting one pane's settings across two tables
    was the accident; the label is a caption for the workspace, not for
    the agent, and stays.

    What is NOT here: `direction`, `ratio` and `focus`. The orchestrator
    pane takes `pane_split`'s own defaults. That is what the keystroke
    does today and the one path both callers share; naming it here keeps
    it a decision rather than an oversight, in a module whose whole
    purpose is that a wrong file never stays silent.
    """

    label: str = "{repo}"


WORKSPACE_ALLOWED = frozenset(f.name for f in fields(WorkspaceSettings))

#: Keys that USED to live under `[workspace]`. The generic complaint --
#: "unknown keys ['model']; allowed: ['label']" -- is true and useless:
#: it sends the reader hunting for a typo instead of to the new home.
#: This is the sort of message this module writes anyway; whoever writes
#: `direction = "links"` and silently gets `right` will hunt the bug in
#: the wrong place.
MOVED_TO_ORCHESTRATOR = ("model", "kind")


def workspace_settings(data: dict[str, Any] | None = None) -> WorkspaceSettings:
    """`[workspace]` out of the settings file. No section: every default.

    Same strictness as settings_for(): an unknown key, a wrong type, or a
    label carrying a placeholder nothing fills is a SettingsError --
    never a silent fallback.
    """
    table = _check_root({} if data is None else data)
    block = table.get("workspace")
    if block is None:
        return WorkspaceSettings()
    if not isinstance(block, dict):
        raise SettingsError(f"workspace: section is not a table, but {type(block).__name__}")
    moved = [key for key in MOVED_TO_ORCHESTRATOR if key in block]
    if moved:
        raise SettingsError(
            "; ".join(f"workspace.{key} has moved to [roles.orchestrator].{key}" for key in moved)
        )
    unknown = sorted(set(block) - WORKSPACE_ALLOWED)
    if unknown:
        raise SettingsError(
            f"workspace: unknown keys {unknown}; allowed: {sorted(WORKSPACE_ALLOWED)}"
        )
    for key, value in block.items():
        if not isinstance(value, str):
            raise SettingsError(f"workspace.{key}: {value!r} is {type(value).__name__}, not str")
    values = WorkspaceSettings(**block)
    # `{repo}` is OPTIONAL here, unlike name_template's {role}/{branch}:
    # the label is a caption, not a reuse key, so a literal `label =
    # "work"` is valid. An UNKNOWN placeholder is not -- it would surface
    # as a KeyError deep inside `up`, far from the line that caused it.
    try:
        values.label.format(repo="r")
    except (KeyError, IndexError, ValueError) as exc:
        raise SettingsError(f"workspace.label={values.label!r} is not formattable: {exc}") from exc
    return values


# -- opencode.jsonc ----------------------------------------------------


@dataclass(frozen=True)
class JsoncFile:
    """One JSONC file, read TOTAL: `load_jsonc` never raises out of it.

    Three states, kept apart because each one is a different repair and
    the operator has to be told which:

    * `found=False`, `error=""` -- there is no file at that path. The
      answer is `workspace init`.
    * `found=True`, `error` non-empty -- the file is there and unusable:
      undecodable bytes, JSON the comment strip could not save, or a top
      level that is not an object. The answer is an editor, and `data`
      stays `{}` so a caller that ignores `error` reads nothing rather
      than something wrong. Every `error` is phrased to follow the word
      "is", so a caller can name the file and paste this behind it.
    * `found=True`, `error=""` -- `data` is what the file says.

    A bare `dict | None` would collapse the first two onto one answer, and
    a raise would hand every caller an except ladder for a file that is
    simply not there -- which is the normal case in a project `init` never
    touched.
    """

    data: dict[str, Any] = field(default_factory=dict)
    found: bool = False
    error: str = ""


#: A JSON string literal with its escapes. Blanked before the `//` search,
#: so a URL inside a value keeps everything behind its own `//`.
_JSON_STRING = re.compile(r'"(?:[^"\\]|\\.)*"')


def _blank_strings(line: str) -> str:
    """Every string literal on the line, hollowed out but the SAME length.

    The length is the point. The `//` is searched for in this line and the
    cut is made in the original one, so the two must share a coordinate
    system. The predecessor of this function replaced each literal with
    `""` and then sliced the original at an index taken from the shorter
    string -- on any line carrying a literal AND a trailing comment it cut
    into the value, and the file failed to parse. No file in this repo has
    such a line, which is why it stayed green until this function moved
    into production.
    """
    return _JSON_STRING.sub(lambda m: '"' + " " * (len(m.group()) - 2) + '"', line)


def load_jsonc(path: str | Path) -> JsoncFile:
    """JSON with `//` line comments -> JsoncFile. Never raises.

    Block comments are deliberately NOT handled: no file this project
    reads or writes carries one, and a `/* */` scanner that has to respect
    string literals is a parser rather than the six lines below.
    """
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return JsoncFile()
    except (OSError, UnicodeDecodeError) as exc:
        return JsoncFile(found=True, error=f"unreadable: {exc}")
    stripped: list[str] = []
    for line in text.splitlines():
        hit = _blank_strings(line).find("//")
        stripped.append(line[:hit] if hit != -1 else line)
    try:
        data: Any = json.loads("\n".join(stripped))
    except json.JSONDecodeError as exc:
        return JsoncFile(found=True, error=f"not valid JSONC: {exc}")
    if not isinstance(data, dict):
        return JsoncFile(
            found=True,
            error=f"not an object at the top level, but a {type(data).__name__}",
        )
    return JsoncFile(data=data, found=True)


# -- role files --------------------------------------------------------

#: opencode reads its project configuration from this file, at the repo
#: root. Not configurable: opencode looks for exactly this name.
OPENCODE_CONFIG = "opencode.jsonc"


def role_prompt_path(root: Path, role: str) -> Path:
    """The prompt a role brings along when `--role-file` names none."""
    return root / ROLE_PROMPTS / f"{role}.md"


def claude_settings_path(root: Path, role: str) -> Path:
    """The file a claude worker of this role gets as `--settings`."""
    return root / CLAUDE_SETTINGS / f"{role}.json"


def missing_agent_config(root: Path, kind: str, agent: str) -> str | None:
    """Why opencode could not resolve `--agent <agent>` here. None: it can.

    Measured 2026-09-04. The agent is a NAME, and opencode resolves it out of
    the project's own `opencode.jsonc`. Where that file or its block is missing,
    opencode starts, prints "Agent not found", never becomes an agent and never
    registers its MCP server -- and the caller sat out the full `ready_timeout_s`
    for an agent id that could not arrive, then answered the misleading
    `no_agent_id`. Look first instead.

    Only opencode resolves a project-level agent name, so only opencode is
    checked; a claude worker's role travels as files (dispatch.agent_args).

    Three answers, because they are three repairs: absent (init has not run),
    present but unparseable (an editor), parsed without this agent (a config
    written for other roles).

    It lives here and not in workspace.py, where it started: `workspace`
    imports `dispatch`, and `dispatch` needs this guard for every role.
    """
    if kind != "opencode":
        return None
    config = load_jsonc(root / OPENCODE_CONFIG)
    if not config.found:
        return f"no {OPENCODE_CONFIG} in {root}"
    if config.error:
        return f"{OPENCODE_CONFIG} in {root} is {config.error}"
    agents = config.data.get("agent")
    if not isinstance(agents, dict) or not isinstance(agents.get(agent), dict):
        return f"{OPENCODE_CONFIG} in {root} defines no agent.{agent}"
    return None


def role_problem(root: Path, role: str, kind: str, prompt: Path) -> str | None:
    """Why a worker of this role could not run here. None: nothing found.

    The three checks `dispatch` makes before it splits a pane, in this order and
    each in its own words: the prompt, then the artefact of the runtime --
    opencode's agent block or claude's settings file. `workspace check` reads
    the same answer as a warning; one producer for both (M3).
    """
    if not prompt.is_file():
        return f"no role prompt at {prompt}"
    problem = missing_agent_config(root, kind, role)
    if problem:
        return problem
    claude = claude_settings_path(root, role)
    if kind == "claude" and not claude.is_file():
        return f"no claude settings at {claude}"
    return None
