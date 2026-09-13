"""`render` and the two tokens: what `workspace init` writes into a stranger's project."""

import json
import re
import tomllib

import pytest

from lean_herdr import templating
from lean_herdr.settings import load_jsonc
from lean_herdr.templating import (
    DEFAULT_VALUES,
    LAYOUT,
    LOCK_PATH,
    VALUE_RE,
    LockError,
    digest,
    file_state,
    read_lock,
    render,
    resolve_values,
    state_warnings,
    write_lock,
)

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


TARGET = ".config/wt.toml"
RENDERED = b"what init would write\n"
WRITTEN_BEFORE = b"what init wrote last time\n"


def _put(root, data: bytes) -> None:
    path = root / TARGET
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


@pytest.mark.parametrize(
    ("on_disk", "locked", "expected"),
    [
        (None, None, "missing"),
        (RENDERED, None, "current"),
        (RENDERED, digest(WRITTEN_BEFORE), "current"),
        (b"a stranger's file\n", None, "unknown"),
        (WRITTEN_BEFORE, digest(WRITTEN_BEFORE), "outdated"),
        (b"a hand edit\n", digest(RENDERED), "edited"),
        (b"a hand edit\n", digest(WRITTEN_BEFORE), "diverged"),
    ],
    ids=[
        "missing",
        "current",
        "current-over-a-stale-entry",
        "unknown",
        "outdated",
        "edited",
        "diverged",
    ],
)
def test_every_state_from_prepared_files(tmp_path, on_disk, locked, expected):
    if on_disk is not None:
        _put(tmp_path, on_disk)
    assert file_state(tmp_path, TARGET, rendered=RENDERED, locked=locked) == expected


def test_a_symlinked_parent_or_target_is_blocked(tmp_path):
    """The two rules of `_place`: never through a linked parent, never through a link."""
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".config").symlink_to(outside, target_is_directory=True)
    assert file_state(root, TARGET, rendered=RENDERED, locked=None) == "blocked"
    (root / ".config").unlink()
    (root / ".config").mkdir()
    (root / TARGET).symlink_to(outside / "wt.toml")
    assert file_state(root, TARGET, rendered=RENDERED, locked=None) == "blocked"


def test_a_missing_lock_is_no_values_and_no_entries(tmp_path):
    assert read_lock(tmp_path) == {"values": {}, "files": {}}


def test_the_lock_reads_back_what_was_written_and_diffs_line_by_line(tmp_path):
    files = {".config/wt.toml": digest(b"x"), "opencode.jsonc": digest(b"y")}
    path = write_lock(tmp_path, values=DEFAULT_VALUES, files=files)
    assert path == tmp_path / LOCK_PATH
    assert read_lock(tmp_path) == {"values": DEFAULT_VALUES, "files": files}
    expected = json.dumps({"files": files, "values": DEFAULT_VALUES}, indent=2, sort_keys=True)
    assert path.read_text(encoding="utf-8") == expected + "\n"
    assert list(path.parent.glob(".tmp-*")) == []


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "[]",
        '{"values": {}}',
        '{"values": {"test": "rm \\"x\\""}, "files": {}}',
        '{"values": {"format": "ruff format"}, "files": {}}',
        '{"values": {}, "files": {"elsewhere.txt": "' + "0" * 64 + '"}}',
        '{"values": {}, "files": {"opencode.jsonc": "not-a-digest"}}',
        "[" * 200000,
    ],
    ids=[
        "no-json",
        "not-an-object",
        "no-files",
        "bad-value",
        "unknown-value-key",
        "key-outside-layout",
        "bad-digest",
        "nested-too-deep",
    ],
)
def test_a_broken_lock_is_a_lock_error_naming_its_path(tmp_path, text):
    """No state is guessed from a record nobody can read."""
    path = tmp_path / LOCK_PATH
    path.parent.mkdir(parents=True)
    path.write_text(text, encoding="utf-8")
    with pytest.raises(LockError, match=re.escape(str(path))):
        read_lock(tmp_path)


def test_a_flag_beats_the_lock_and_the_lock_beats_the_default():
    locked = {"test": "cargo test"}
    assert resolve_values(locked) == {"test": "cargo test", "lint": "uv run ruff check"}
    assert resolve_values(locked, test="make test", lint="make lint") == {
        "test": "make test",
        "lint": "make lint",
    }


def test_every_state_but_current_and_edited_names_a_next_step():
    """A hand edit is intent, and `current` has nothing to do."""
    states = {
        f"file-{state}": state
        for state in ("missing", "current", "unknown", "outdated", "edited", "diverged", "blocked")
    }
    lines = state_warnings(states)
    assert [line.split(" is ")[0] for line in lines] == [
        "file-blocked",
        "file-diverged",
        "file-missing",
        "file-outdated",
        "file-unknown",
    ]
    assert all("init --update" in line for line in lines if " is outdated" in line)
