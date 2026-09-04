import re
import subprocess
from pathlib import Path

import pytest

from lean_herdr.settings import (
    SETTINGS_PATH,
    RoleSettings,
    SettingsError,
    read_settings,
    settings_for,
)


def test_without_a_file_the_defaults_apply(tmp_path):
    """The config is an option, not an obligation."""
    assert read_settings(tmp_path / "does-not-exist.toml") == {}
    assert settings_for("builder") == RoleSettings(profile="standard")


def test_the_profile_follows_the_role():
    assert settings_for("orchestrator").profile == "minimal"
    assert settings_for("builder").profile == "standard"
    assert settings_for("reviewer").profile == "standard"


def test_default_overlays_the_builtin_and_roles_overlays_default():
    data = {
        "default": {"direction": "down", "ratio": 0.4},
        "roles": {"builder": {"ratio": 0.7}},
    }
    builder = settings_for("builder", data)
    assert builder.direction == "down", "[default] applies to every role"
    assert builder.ratio == 0.7, "[roles.builder] beats [default]"
    assert settings_for("reviewer", data).ratio == 0.4


def test_default_also_beats_the_builtin_role_default():
    data = {"default": {"profile": "power"}}
    assert settings_for("orchestrator", data).profile == "power"


def test_broken_toml_does_not_stay_silent(tmp_path):
    path = tmp_path / "lean-herdr.toml"
    path.write_text("[default\n", encoding="utf-8")
    with pytest.raises(SettingsError, match="malformed"):
        read_settings(path)


def test_unknown_keys_do_not_stay_silent():
    """A typo that quietly evaporates is worse than a crash."""
    with pytest.raises(SettingsError, match="direktion"):
        settings_for("builder", {"default": {"direktion": "down"}})


def test_a_wrong_direction_does_not_stay_silent():
    with pytest.raises(SettingsError, match="direction"):
        settings_for("builder", {"default": {"direction": "links"}})


def test_a_wrong_type_does_not_stay_silent():
    with pytest.raises(SettingsError, match="ratio"):
        settings_for("builder", {"default": {"ratio": "half"}})


@pytest.mark.parametrize("value", [0.0, 1.0, 1.5, -0.2])
def test_ratio_must_lie_between_zero_and_one(value):
    with pytest.raises(SettingsError, match="ratio"):
        settings_for("builder", {"default": {"ratio": value}})


@pytest.mark.parametrize("key", ["ratio", "ready_timeout_s"])
@pytest.mark.parametrize("value", [True, False])
def test_a_bool_is_not_a_number(key, value):
    """`isinstance(True, int)` is True -- so a bool slips through the type
    check unless it is rejected by name.

    `ready_timeout_s = true` would then pass `float(True) == 1.0 > 0` as well
    and become a live one-second agent-ready timeout: a wrong value silently
    turned into a working one, which is exactly what a present-but-wrong file
    must never do. `ratio = true` is caught by its 0..1 bounds anyway -- but
    then the message blames the range instead of the type, so both keys are
    rejected by name and the message says `is bool`.
    """
    with pytest.raises(SettingsError, match=rf"{key}: {value} is bool"):
        settings_for("builder", {"default": {key: value}})


def test_ready_timeout_must_be_positive():
    with pytest.raises(SettingsError, match="ready_timeout_s"):
        settings_for("builder", {"default": {"ready_timeout_s": 0}})


@pytest.mark.parametrize(
    "template", ["{branch}", "{role}", "worker", "{role}-{twig}"]
)
def test_a_name_template_missing_either_placeholder_is_rejected(template):
    """The reuse key is (branch, role) -- otherwise a reviewer dispatch hits
    the running builder of that branch."""
    with pytest.raises(SettingsError, match="name_template"):
        settings_for("builder", {"default": {"name_template": template}})


@pytest.mark.parametrize(
    "text, offender",
    [
        ('direction = "down"\n', "'direction'"),
        ('[defaults]\ndirection = "down"\n', "'defaults'"),
        ('[role.builder]\ndirection = "down"\n', "'role'"),
    ],
    ids=["no-section-header", "defaults-typo", "role-typo"],
)
def test_misplaced_top_level_content_does_not_stay_silent(tmp_path, text, offender):
    """A typo one level up evaporates just as quietly as one inside a section
    -- and hands the operator plain defaults instead of an error."""
    path = tmp_path / "lean-herdr.toml"
    path.write_text(text, encoding="utf-8")
    data = read_settings(path)
    with pytest.raises(SettingsError, match=re.escape(offender)):
        settings_for("builder", data)


@pytest.mark.parametrize("roles", ["builder", [1, 2], 3])
def test_a_non_table_roles_does_not_raise_attribute_error(roles):
    """The caller catches SettingsError -- an AttributeError slips past it."""
    with pytest.raises(SettingsError, match="roles is not a table"):
        settings_for("builder", {"roles": roles})


@pytest.mark.parametrize("data", [["x"], "x", 3, ("default", {})])
def test_non_mapping_settings_data_does_not_raise_attribute_error(data):
    with pytest.raises(SettingsError, match="root is not a table"):
        settings_for("builder", data)


def test_a_valid_file_survives_the_top_level_check(tmp_path):
    """Guard against over-correcting: role names stay free-form, and a file
    that only uses [default] and [roles.*] behaves exactly as before."""
    path = tmp_path / "lean-herdr.toml"
    path.write_text(
        '[default]\ndirection = "down"\n\n[roles.whatever]\nratio = 0.3\n',
        encoding="utf-8",
    )
    data = read_settings(path)
    assert settings_for("whatever", data) == RoleSettings(
        direction="down", ratio=0.3, profile="standard"
    )
    assert settings_for("builder", data).direction == "down"
    assert settings_for("builder", data).ratio is None


def test_the_shipped_template_changes_nothing(tmp_path):
    """As SHIPPED the file is fully commented out -- that is its purpose.

    Read from git, not from the working tree: the file exists to invite the
    operator to uncomment lines, and the first one who does must not get a red
    suite plus a dirty tree. If git cannot answer, skip -- a skip is honest,
    a false pass is not.
    """
    # Anchored on the repo root, not relative: SETTINGS_PATH is relative and
    # pytest may be started from any directory.
    root = Path(__file__).resolve().parents[1]
    try:
        shipped = subprocess.run(
            ["git", "show", f"HEAD:{SETTINGS_PATH.as_posix()}"],
            cwd=root,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.skip(f"git is unavailable: {exc}")
    if shipped.returncode != 0:
        pytest.skip(f"{SETTINGS_PATH} is not in HEAD yet")
    path = tmp_path / SETTINGS_PATH.name
    path.write_bytes(shipped.stdout)
    data = read_settings(path)
    assert data == {}, f"{SETTINGS_PATH} carries active values: {sorted(data)}"
    assert settings_for("builder", data) == RoleSettings(profile="standard")
    assert settings_for("reviewer", data) == RoleSettings(profile="standard")
    assert settings_for("orchestrator", data) == RoleSettings(profile="minimal")


def test_the_llm_section_is_read_and_defaults_to_empty():
    from lean_herdr.settings import LlmSettings, llm_settings

    assert llm_settings({}) == LlmSettings()
    assert llm_settings({"llm": {"model": "a/b"}}).model == "a/b"
    assert llm_settings({"llm": {"prereview_effort": "medium"}}).effort == ""


def test_the_llm_section_no_longer_breaks_the_whole_file():
    """Before this task `[llm]` made EVERY lean-herdr dispatch call fail."""
    from lean_herdr.settings import settings_for

    assert settings_for("builder", {"llm": {"model": "a/b"}}).profile == "standard"


@pytest.mark.parametrize(
    "block",
    [
        {"modell": "a/b"},
        {"model": 5},
        {"effort": "mininal"},
        {"prereview_effort": "enormous"},
    ],
    ids=["unknown-key", "wrong-type", "typo-in-effort", "unknown-effort"],
)
def test_a_wrong_llm_value_is_loud(block):
    from lean_herdr.settings import SettingsError, llm_settings

    with pytest.raises(SettingsError):
        llm_settings({"llm": block})


def test_the_llm_section_must_be_a_table():
    from lean_herdr.settings import SettingsError, llm_settings

    with pytest.raises(SettingsError, match="not a table"):
        llm_settings({"llm": "a/b"})
