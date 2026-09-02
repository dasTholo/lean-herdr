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


def test_the_shipped_template_changes_nothing():
    """The file in the repo is fully commented out -- that is its purpose."""
    # Anchored on the repo root, not relative: SETTINGS_PATH is relative and
    # pytest may be started from any directory.
    data = read_settings(Path(__file__).resolve().parents[1] / SETTINGS_PATH)
    assert data == {}, f"{SETTINGS_PATH} carries active values: {sorted(data)}"
    assert settings_for("builder", data) == RoleSettings(profile="standard")
