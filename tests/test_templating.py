"""`render` and the two tokens: what `workspace init` writes into a stranger's project."""

import json
import tomllib

import pytest

from lean_herdr import templating
from lean_herdr.settings import load_jsonc
from lean_herdr.templating import DEFAULT_VALUES, LAYOUT, VALUE_RE, render

#: Another project's commands. Every assertion that holds for the defaults must
#: hold for these too, or a render shifted a line.
FOREIGN = {"test": "cargo test", "lint": "cargo clippy"}


@pytest.mark.parametrize("values", [DEFAULT_VALUES, FOREIGN], ids=["default", "foreign"])
@pytest.mark.parametrize("name", sorted(LAYOUT))
def test_no_token_survives_rendering(name, values):
    assert b"{{lean-herdr:" not in render(name, values)


def test_the_default_values_pass_their_own_pattern():
    assert all(VALUE_RE.match(value) for value in DEFAULT_VALUES.values())


@pytest.mark.parametrize(
    "value",
    [
        'uv run "pytest"',
        "pytest*",
        "a:b",
        "$HOME/run",
        "make\ntest",
        "make test ",
        "a;b",
        "a && b",
        "a|b",
        "a\\b",
        "",
    ],
    ids=[
        "quote",
        "star",
        "colon",
        "dollar",
        "newline",
        "trailing-space",
        "semicolon",
        "ampersand",
        "pipe",
        "backslash",
        "empty",
    ],
)
def test_a_value_that_would_break_out_of_its_file_is_refused(value):
    """The value lands in TOML, JSON and JSONC nobody escapes -- and in a shell."""
    assert VALUE_RE.match(value) is None
    with pytest.raises(ValueError, match="not a command"):
        render("wt.toml", {**DEFAULT_VALUES, "test": value})


def test_a_leftover_token_is_a_broken_package(monkeypatch, tmp_path):
    """A misspelt token must not ship into a project as literal braces."""
    (tmp_path / "wt.toml").write_text('test = "{{lean-herdr:tset}}"\n', encoding="utf-8")
    monkeypatch.setattr(templating, "TEMPLATES", tmp_path)
    with pytest.raises(ValueError, match="left after rendering"):
        render("wt.toml", DEFAULT_VALUES)


def test_the_gate_and_the_permissions_carry_the_same_two_commands(tmp_path):
    """One string, three files: the gate runs it, both builders may run it first."""
    gate = tomllib.loads(render("wt.toml", FOREIGN).decode("utf-8"))["pre-merge"]
    assert gate == {"test": "cargo test", "lint": "cargo clippy"}
    allow = json.loads(render("settings.json", FOREIGN))["permissions"]["allow"]
    assert "Bash(cargo test:*)" in allow
    assert "Bash(cargo clippy:*)" in allow
    jsonc = tmp_path / "opencode.jsonc"
    jsonc.write_bytes(render("opencode.jsonc", FOREIGN))
    bash = load_jsonc(jsonc).data["agent"]["builder"]["permission"]["bash"]
    assert bash["cargo test*"] == "allow"
    assert bash["cargo clippy*"] == "allow"


def test_the_list_schema_wt_ignores_is_gone():
    """wt 0.77 reports `list.json-schema` in a project config as ignored, everywhere."""
    assert "list" not in tomllib.loads(render("wt.toml", DEFAULT_VALUES).decode("utf-8"))
