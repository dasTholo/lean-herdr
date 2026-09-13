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
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent / "templates"

#: template inside the package -> where it goes in the target project.
#: THE one truth: tests/test_templates.py imports this table to hold each
#: rendered template byte-identical against this repo's own copy.
#:
#: Only the first four are movable. `opencode.jsonc`,
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
