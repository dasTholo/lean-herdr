"""The templates `workspace init` writes, rendered with this project's two commands.

Two tokens and nothing else: `{{lean-herdr:test}}` and `{{lean-herdr:lint}}`.
Each value is a WHOLE command. The pre-merge gate in `.config/wt.toml` runs it,
and the same string is the prefix of the builder's permission in
`opencode.jsonc` and `.claude/settings.json` -- the builder may run exactly
what the gate measures the merge against, with arguments behind it.

No template engine and no escaping. The values land in JSON, JSONC and TOML
that are filled by hand, so `VALUE_RE` keeps out every character that would
need escaping there or mean something to a shell: a quote, a backslash, `*`,
`:`, `$`, a newline, `;`, `&`, `|`. How far a prefix opens the gate is the
operator's call.

The lock, `templates.lock.json`, records what `init` wrote: the resolved
values and a sha256 per file. Against it and a fresh rendering every target
has one of seven states (`file_state`), and `init --update` rewrites only the
files nobody touched since.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent / "templates"

#: template inside the package -> where it goes in the target project.
#: THE one truth: tests/test_templates.py imports this table to hold each
#: rendered template byte-identical against this repo's own copy.
#:
#: Only the first seven are movable. `opencode.jsonc`,
#: `.claude/settings.json`, `.config/wt.toml` and the opencode plugin sit
#: where their owners look for them. `.config/wt.toml` could in theory move
#: via WORKTRUNK_PROJECT_CONFIG_PATH -- but that variable would have to be
#: set on EVERY `wt` call, hand-typed ones included, and a single miss makes
#: `wt` skip the project hooks silently and report success. The pre-merge
#: test gate would then not run at all.
LAYOUT = {
    "config.toml": ".lean-ctx/lean-herdr/config.toml",
    "roles/orchestrator.md": ".lean-ctx/lean-herdr/roles/orchestrator.md",
    "roles/builder.md": ".lean-ctx/lean-herdr/roles/builder.md",
    "roles/reviewer.md": ".lean-ctx/lean-herdr/roles/reviewer.md",
    "claude/orchestrator.json": ".lean-ctx/lean-herdr/claude/orchestrator.json",
    "claude/builder.json": ".lean-ctx/lean-herdr/claude/builder.json",
    "claude/reviewer.json": ".lean-ctx/lean-herdr/claude/reviewer.json",
    "opencode.jsonc": "opencode.jsonc",
    "settings.json": ".claude/settings.json",
    "wt.toml": ".config/wt.toml",
    "lean-ctx-policy.js": ".opencode/plugins/lean-ctx-policy.js",
}

#: What `init` renders when neither a flag nor the lock names a value. `ruff
#: check` without a path checks `.`, and this repository is green under both.
DEFAULT_VALUES = {"lint": "uv run ruff check", "test": "uv run pytest"}

#: A value: a letter or digit, then letters, digits, space and `._/=+,@-`, and no
#: space at the end. The pattern of `catalog.SLUG_RE`, for the same reason -- the
#: string goes into files assembled by hand.
VALUE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._/=+,@-]*(?<! )\Z")

_TOKEN = re.compile(r"\{\{lean-herdr:(test|lint)\}\}")
_LEFTOVER = "{{lean-herdr:"


def render(name: str, values: Mapping[str, str]) -> bytes:
    """The template `name` with both tokens replaced -- the bytes `init` writes.

    Raises ValueError for a value `VALUE_RE` refuses, and for a token left over
    after rendering: a misspelt token in a shipped template is a broken package,
    and tests/test_templating.py holds every template to it. Bytes in, bytes out:
    no newline translation touches a template on the way.
    """
    for key in DEFAULT_VALUES:
        value = values.get(key, "")
        if not VALUE_RE.match(value):
            raise ValueError(f"{key}: {value!r} is not a command init writes into a config file")
    source = (TEMPLATES / name).read_bytes().decode("utf-8")
    text = _TOKEN.sub(lambda hit: values[hit.group(1)], source)
    if _LEFTOVER in text:
        raise ValueError(f"{name}: a `{_LEFTOVER}...}}}}` token is left after rendering")
    return text.encode("utf-8")


#: Versioned, like the role prompts: it travels in the branch, and the next
#: `init --update` -- anybody's -- needs the record of what init wrote.
LOCK_PATH = Path(".lean-ctx") / "lean-herdr" / "templates.lock.json"

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")

#: state -> the next step `state_warnings` names. `current` and `edited` are
#: absent on purpose: nothing to do, and a hand edit is intent.
_NEXT_STEP = {
    "missing": "`lean-herdr workspace init --update` writes it",
    "outdated": "nobody edited it since init wrote it: `lean-herdr workspace init --update`",
    "unknown": "no lock entry and not what init would write -- compare it with the template by hand",
    "diverged": "edited here AND changed in the package -- compare it with the template by hand",
    "blocked": "it or one of its parent directories is a symlink, and init never writes through one",
}


class LockError(ValueError):
    """`templates.lock.json` is there and unusable. The message starts with the path."""


def digest(data: bytes) -> str:
    """The sha256 the lock records, as hex."""
    return hashlib.sha256(data).hexdigest()


def resolve_values(
    locked: Mapping[str, str], *, test: str | None = None, lint: str | None = None
) -> dict[str, str]:
    """Flag > lock > default, per key -- the one resolution `init` and `check` share."""
    given = {"test": test, "lint": lint}
    return {
        key: given[key] or locked.get(key) or default for key, default in DEFAULT_VALUES.items()
    }


def read_lock(root: Path) -> dict[str, dict[str, str]]:
    """The lock as `{"values": {...}, "files": {...}}`. Missing: both empty.

    Broken is a LockError, never a guess: not JSON, not that shape, a value
    `VALUE_RE` refuses, or a file key outside LAYOUT. A state computed from a
    record nobody can read would be the silent wrong answer the lock exists
    to prevent.
    """
    path = Path(root) / LOCK_PATH
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {"values": {}, "files": {}}
    except OSError as exc:
        raise LockError(f"{path}: unreadable: {exc}") from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        # RecursionError: arrays nested past the decoder's stack -- as unusable
        # as any other file that is not JSON, and never a crash of `check` or `init`.
        raise LockError(f"{path}: not JSON: {exc}") from exc
    if not isinstance(data, dict) or set(data) != {"values", "files"}:
        raise LockError(f"{path}: expected exactly the keys `values` and `files`")
    values, files = data["values"], data["files"]
    if not isinstance(values, dict) or not isinstance(files, dict):
        raise LockError(f"{path}: `values` and `files` must be objects")
    for key, value in values.items():
        if key not in DEFAULT_VALUES or not isinstance(value, str) or not VALUE_RE.match(value):
            raise LockError(f"{path}: values.{key} = {value!r} is not a usable command")
    targets = set(LAYOUT.values())
    for key, entry in files.items():
        if key not in targets or not isinstance(entry, str) or not _SHA256_RE.match(entry):
            raise LockError(f"{path}: files.{key} is no template target with a sha256")
    return {"values": dict(values), "files": dict(files)}


def write_lock(root: Path, *, values: Mapping[str, str], files: Mapping[str, str]) -> Path:
    """The whole lock, through a temp file of this writer's own, then `os.replace`.

    Inline, like `catalog.write_overlay` -- no shared helper. WHOLE is the
    file, not the content: the caller hands every entry it did not write back
    in unchanged. Keys sorted, indent 2, a trailing newline, so a diff in the
    branch shows one line per changed file. `mkstemp` creates 0600, and git
    records no mode but the executable bit.
    """
    path = Path(root) / LOCK_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps({"files": dict(files), "values": dict(values)}, indent=2, sort_keys=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=f".tmp-{path.name}.")
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
        os.replace(tmp, path)
    except OSError:
        # Only OUR temp file, for the reason `write_overlay` gives.
        tmp.unlink(missing_ok=True)
        raise
    return path


def blocked(root: Path, relative: str | Path) -> bool:
    """A symlink below `root` on the way to `relative`, or at it -- never gone through.

    The rules of `initcmd._place`, for the templates and for the lock alike.
    The root itself is not looked at: it may sit under a linked home or volume.
    """
    parent = Path(root)
    for part in Path(relative).parts[:-1]:
        parent = parent / part
        if parent.is_symlink():
            return True
    return (Path(root) / relative).is_symlink()


def file_state(root: Path, relative: str, *, rendered: bytes, locked: str | None) -> str:
    """One target's state, checked in this order.

    D is the file, L the lock entry, P the rendered template.
    `blocked` -- a symlink on the way or at the target (the rules of
    `initcmd._place`); `missing`; `current` D = P; `unknown` no L;
    `outdated` D = L != P; `edited` D != L = P; `diverged` D != L, L != P.

    Raises OSError for a target that is there and cannot be read -- a
    directory in its place, a regular file where a parent directory belongs.
    `init` stops on it with its report so far; `check` names it.
    """
    if blocked(root, relative):
        return "blocked"
    target = Path(root) / relative
    try:
        on_disk = digest(target.read_bytes())
    except FileNotFoundError:
        return "missing"
    produced = digest(rendered)
    if on_disk == produced:
        return "current"
    if locked is None:
        return "unknown"
    if on_disk == locked:
        return "outdated"
    return "edited" if locked == produced else "diverged"


def state_warnings(templates: Mapping[str, str]) -> list[str]:
    """One line per template that needs a gesture or a hand, sorted by path."""
    return [
        f"{relative} is {state}: {_NEXT_STEP[state]}"
        for relative, state in sorted(templates.items())
        if state in _NEXT_STEP
    ]
