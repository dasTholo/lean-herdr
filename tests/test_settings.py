import re
import subprocess
from pathlib import Path

import pytest

from lean_herdr.settings import (
    RoleSettings,
    SettingsError,
    WorkspaceSettings,
    load_jsonc,
    read_settings,
    settings_for,
    workspace_settings,
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

    Read the TEMPLATE from git, not the working tree and not this repo's
    own copy: the template is what `lean-herdr workspace init` writes into
    a stranger's project, and the first operator who uncomments a line
    must not get a red suite plus a dirty tree. If git cannot answer,
    skip -- a skip is honest, a false pass is not.
    """
    root = Path(__file__).resolve().parents[1]
    template = Path("lean_herdr") / "templates" / "config.toml"
    try:
        shipped = subprocess.run(
            ["git", "show", f"HEAD:{template.as_posix()}"],
            cwd=root,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.skip(f"git is unavailable: {exc}")
    if shipped.returncode != 0:
        pytest.skip(f"{template} is not in HEAD yet")
    path = tmp_path / template.name
    path.write_bytes(shipped.stdout)
    data = read_settings(path)
    assert data == {}, f"{template} carries active values: {sorted(data)}"
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


def test_an_unknown_workspace_key_does_not_stay_silent():
    with pytest.raises(SettingsError, match="unknown keys"):
        workspace_settings({"workspace": {"labl": "x"}})


def test_a_workspace_key_under_roles_is_still_unknown():
    """[workspace] is its own dataclass, not a widened RoleSettings."""
    with pytest.raises(SettingsError, match="unknown keys"):
        settings_for("builder", {"roles": {"builder": {"label": "x"}}})


def test_a_kind_no_role_prompt_is_written_for_is_rejected():
    with pytest.raises(SettingsError, match="workspace.kind"):
        workspace_settings({"workspace": {"kind": "codex"}})


def test_a_literal_label_is_valid_but_an_unknown_placeholder_is_not():
    assert workspace_settings({"workspace": {"label": "work"}}).label == "work"
    with pytest.raises(SettingsError, match="not formattable"):
        workspace_settings({"workspace": {"label": "{branch}"}})


def test_no_workspace_section_means_every_default():
    assert workspace_settings({}) == WorkspaceSettings()


# -- load_jsonc: opencode's own configuration --------------------------


def test_a_missing_jsonc_file_is_absent_rather_than_broken(tmp_path):
    """Absent and present-but-unusable are two different repairs."""
    result = load_jsonc(tmp_path / "opencode.jsonc")
    assert result.found is False
    assert result.error == ""
    assert result.data == {}


def test_a_comment_inside_a_string_literal_survives_the_strip(tmp_path):
    """The whole reason this is not `json.loads` on a `//`-split line."""
    path = tmp_path / "opencode.jsonc"
    path.write_text(
        "{\n"
        "  // a real comment\n"
        '  "schema": "https://opencode.ai/config.json", // and a trailing one\n'
        '  "agent": {"orchestrator": {"mode": "primary"}}\n'
        "}\n",
        encoding="utf-8",
    )
    result = load_jsonc(path)
    assert result.found is True and result.error == ""
    assert result.data["schema"] == "https://opencode.ai/config.json"
    assert "orchestrator" in result.data["agent"]


def test_broken_json_is_present_and_named_never_raised(tmp_path):
    path = tmp_path / "opencode.jsonc"
    path.write_text('{"agent": {\n', encoding="utf-8")
    result = load_jsonc(path)
    assert result.found is True, "the file IS there -- that is not `absent`"
    assert "not valid JSONC" in result.error
    assert result.data == {}


def test_a_top_level_that_is_not_an_object_is_no_configuration(tmp_path):
    path = tmp_path / "opencode.jsonc"
    path.write_text("[1, 2]\n", encoding="utf-8")
    assert "list" in load_jsonc(path).error


def test_undecodable_bytes_do_not_escape_as_an_exception(tmp_path):
    path = tmp_path / "opencode.jsonc"
    path.write_bytes(b'{"agent": "\xff\xfe"}')
    result = load_jsonc(path)
    assert result.found is True and "unreadable" in result.error


def test_a_directory_where_the_file_belongs_is_not_an_exception_either(tmp_path):
    """The OSError that is not FileNotFoundError -- total means total."""
    (tmp_path / "opencode.jsonc").mkdir()
    assert "unreadable" in load_jsonc(tmp_path / "opencode.jsonc").error
