import re
import subprocess
from pathlib import Path

import pytest

from lean_herdr.settings import (
    KINDS,
    ROOT_KEYS,
    RoleSettings,
    SettingsError,
    WorkspaceSettings,
    claude_settings_path,
    load_jsonc,
    missing_agent_config,
    model_warnings,
    read_settings,
    role_for_work,
    role_problem,
    role_prompt_path,
    settings_for,
    work_roles,
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


def test_every_allowed_role_key_has_a_type():
    """`ALLOWED` comes from the RoleSettings fields, `_TYPES` is written by hand.

    `_check_types` lets a key through on `ALLOWED` and then indexes `_TYPES[key]`:
    a field added to the dataclass and forgotten in the table is not a SettingsError
    but a KeyError, where every caller expects a SettingsError.
    """
    from lean_herdr import settings

    assert set(settings._TYPES) == settings.ALLOWED


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


@pytest.mark.parametrize("template", ["{branch}", "{role}", "worker", "{role}-{twig}"])
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
    assert settings_for("orchestrator", data) == RoleSettings(profile="minimal", kind="opencode")


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


def _write_llm_files(root, *, config=None, overlay=None):
    """Both files where settings.py says they live, never at a literal.

    A fixture that spells the path out itself tests the missing-file path
    under a name that promises the opposite the day one of them moves.
    """
    from lean_herdr.settings import OVERLAY_PATH, SETTINGS_PATH

    for relative, text in ((SETTINGS_PATH, config), (OVERLAY_PATH, overlay)):
        if text is None:
            continue
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def test_neither_file_is_every_default(tmp_path):
    """Both files are optional, exactly like the single one was."""
    from lean_herdr.settings import LlmSettings, llm_settings_layered

    assert llm_settings_layered(tmp_path) == LlmSettings()


def test_the_overlay_alone_reaches_the_caller(tmp_path):
    from lean_herdr.settings import llm_settings_layered

    _write_llm_files(tmp_path, overlay='[llm]\nmodel = "auto/pick"\n')
    assert llm_settings_layered(tmp_path).model == "auto/pick"


def test_config_toml_alone_reaches_the_caller(tmp_path):
    from lean_herdr.settings import llm_settings_layered

    _write_llm_files(tmp_path, config='[llm]\nmodel = "by/hand"\n')
    assert llm_settings_layered(tmp_path).model == "by/hand"


def test_the_overlay_gives_model_and_nothing_else(tmp_path):
    """The check writes one key, and the chain in llm.py knows the overlay for one key.

    A valid `effort` or `prereview_model` in the overlay is IGNORED, not refused:
    refusing it would fail `dispatch` over a file that says nothing wrong. An invalid
    one still raises -- `test_a_broken_overlay_is_a_config_error_too` holds that.
    """
    from lean_herdr.settings import LlmSettings, llm_settings_layered

    _write_llm_files(
        tmp_path,
        config='[llm]\nprereview_effort = "high"\n',
        overlay='[llm]\nmodel = "auto/pick"\neffort = "low"\nprereview_model = "auto/judge"\n',
    )
    got = llm_settings_layered(tmp_path)
    assert got == LlmSettings(model="auto/pick", prereview_effort="high")


def test_config_toml_beats_the_overlay_where_it_speaks(tmp_path):
    """The operator's hand survives every daily check.

    The overlay is what a machine wrote. Where config.toml names `model`, the
    overlay's `model` is gone -- and the three other keys it carries here never
    arrive at all, spoken over or not.
    """
    from lean_herdr.settings import LlmSettings, llm_settings_layered

    _write_llm_files(
        tmp_path,
        config='[llm]\nmodel = "by/hand"\nprereview_effort = "high"\n',
        overlay=(
            '[llm]\nmodel = "auto/pick"\nprereview_model = "auto/judge"\n'
            'effort = "low"\nprereview_effort = "minimal"\n'
        ),
    )
    got = llm_settings_layered(tmp_path)
    assert got == LlmSettings(model="by/hand", prereview_effort="high")


def test_an_empty_value_in_the_foreground_lets_the_overlay_through(tmp_path):
    """`model = ""` is "not set" here too -- the rule `llm._first()` follows.

    Blanking the key instead would leave the operator no way back to the
    overlay short of deleting the line.
    """
    from lean_herdr.settings import llm_settings_layered

    _write_llm_files(
        tmp_path,
        config='[llm]\nmodel = ""\n',
        overlay='[llm]\nmodel = "auto/pick"\n',
    )
    assert llm_settings_layered(tmp_path).model == "auto/pick"


def test_handed_in_data_beats_the_file_on_disk(tmp_path):
    """`data` is config.toml ALREADY READ -- dispatch.main() hands it in.

    Precedence only, and the name says so now: the file says one thing,
    `data` says another, and `data` wins. This would stay green against an
    implementation that read the file anyway and then discarded it, so it
    is NOT the proof that the read is spared --
    `test_main_reads_config_toml_exactly_once_per_call` in
    tests/test_dispatch.py counts the reads and is.
    """
    from lean_herdr.settings import llm_settings_layered

    _write_llm_files(
        tmp_path,
        config='[llm]\nmodel = "from/disk"\n',
        overlay='[llm]\nmodel = "auto/pick"\n',
    )
    got = llm_settings_layered(tmp_path, {"llm": {"model": "from/data"}})
    assert got.model == "from/data"


@pytest.mark.parametrize(
    "text",
    ["[llm]\nmodel = 5\n", '[llm]\nmodel = "unclosed\n'],
    ids=["wrong-type", "malformed-toml"],
)
def test_a_broken_overlay_is_loud_here(tmp_path, text):
    """Loud in settings.py. `llm.file_settings()` is the one place that
    swallows it, and it does so for both files at once."""
    from lean_herdr.settings import SettingsError, llm_settings_layered

    _write_llm_files(tmp_path, overlay=text)
    with pytest.raises(SettingsError):
        llm_settings_layered(tmp_path)


@pytest.mark.parametrize(
    "text",
    ["[llm]\nmodel = 5\n", '[llm]\nmodel = "unclosed\n'],
    ids=["wrong-type", "malformed-toml"],
)
def test_a_broken_overlay_is_an_overlay_error_and_still_a_settings_error(tmp_path, text):
    """Its own class for the one reader that must tell it apart, and a
    SettingsError for every loud path that already catches one."""
    from lean_herdr.settings import (
        OVERLAY_PATH,
        OverlayError,
        SettingsError,
        llm_settings_layered,
    )

    _write_llm_files(tmp_path, config='[llm]\nmodel = "by/hand"\n', overlay=text)
    with pytest.raises(OverlayError, match="lean-herdr models apply") as caught:
        llm_settings_layered(tmp_path)
    assert isinstance(caught.value, SettingsError)
    assert str(OVERLAY_PATH) in str(caught.value)


def test_a_broken_config_toml_is_not_an_overlay_error(tmp_path):
    """config.toml is read first: a file broken in both places names the operator's."""
    from lean_herdr.settings import OverlayError, SettingsError, llm_settings_layered

    _write_llm_files(tmp_path, config="[llm]\nmodel = 5\n", overlay="[llm]\nmodel = 6\n")
    with pytest.raises(SettingsError) as caught:
        llm_settings_layered(tmp_path)
    assert not isinstance(caught.value, OverlayError)


def test_an_unknown_workspace_key_does_not_stay_silent():
    with pytest.raises(SettingsError, match="unknown keys"):
        workspace_settings({"workspace": {"labl": "x"}})


def test_a_workspace_key_under_roles_is_still_unknown():
    """[workspace] is its own dataclass, not a widened RoleSettings."""
    with pytest.raises(SettingsError, match="unknown keys"):
        settings_for("builder", {"roles": {"builder": {"label": "x"}}})


def test_a_kind_no_role_prompt_is_written_for_is_rejected():
    """The check moved with the key: `kind` is a role setting now."""
    with pytest.raises(SettingsError, match="builder: kind="):
        settings_for("builder", {"roles": {"builder": {"kind": "codex"}}})


def test_a_role_carries_its_own_model_and_kind():
    values = settings_for("builder", {"roles": {"builder": {"kind": "claude", "model": "sonnet"}}})
    assert values.kind == "claude"
    assert values.model == "sonnet"


def test_only_the_orchestrator_has_a_built_in_kind():
    """A worker says it -- by flag or by config -- or `dispatch` refuses.

    Started on the wrong runtime it resolves a role prompt that is not
    written for it, so there is nothing sensible to fall back to.
    """
    assert settings_for("orchestrator").kind == "opencode"
    assert settings_for("builder").kind == ""
    assert settings_for("reviewer").kind == ""


def test_workspace_model_names_its_new_home():
    """ "unknown keys ['model']" is true and useless -- it sends the reader
    hunting for a typo instead of to the new home.
    """
    with pytest.raises(SettingsError, match=r"\[roles.orchestrator\].model"):
        workspace_settings({"workspace": {"model": "x"}})
    with pytest.raises(SettingsError, match=r"\[roles.orchestrator\].kind"):
        workspace_settings({"workspace": {"kind": "claude"}})
    with pytest.raises(SettingsError) as both:
        workspace_settings({"workspace": {"model": "x", "kind": "claude"}})
    assert "workspace.model has moved" in str(both.value)
    assert "workspace.kind has moved" in str(both.value)


def test_a_literal_label_is_valid_but_an_unknown_placeholder_is_not():
    assert workspace_settings({"workspace": {"label": "work"}}).label == "work"
    with pytest.raises(SettingsError, match="not formattable"):
        workspace_settings({"workspace": {"label": "{branch}"}})


def test_no_workspace_section_means_every_default():
    assert workspace_settings({}) == WorkspaceSettings()


def test_a_default_model_reaches_every_role():
    """The mechanics of `ALLOWED`, held down so nobody reads it as an accident.

    `[default]` is overlaid onto every role, the orchestrator included --
    one line sets the model for the whole project.
    """
    data = {"default": {"model": "sonnet"}}
    assert [settings_for(role, data).model for role in ("builder", "reviewer", "orchestrator")] == [
        "sonnet",
        "sonnet",
        "sonnet",
    ]


@pytest.mark.parametrize(
    ("roles", "warned"),
    [
        pytest.param(
            {"builder": {"model": "sonnet"}, "reviewer": {"model": "opus"}},
            False,
            id="two models, nothing to say",
        ),
        pytest.param(
            {"builder": {"model": "sonnet"}, "reviewer": {"model": "sonnet"}},
            True,
            id="one model, and nobody said so",
        ),
        pytest.param(
            {
                "builder": {"model": "sonnet"},
                "reviewer": {"model": "sonnet", "shares_builder_model": True},
            },
            False,
            id="one model, and it is meant",
        ),
        pytest.param({}, False, id="no model at all is not a shared model"),
    ],
)
def test_two_roles_on_one_model_warn_unless_confirmed(roles, warned):
    """A warning, never a refusal: two workers on one model is legitimate."""
    lines = model_warnings({"roles": roles})
    assert bool(lines) is warned
    assert not warned or "'sonnet'" in lines[0]


# -- models: [models] ---------------------------------------------------


def test_models_block_is_a_known_root_key():
    """Without "models" in ROOT_KEYS every config carrying the block fails."""
    assert settings_for("builder", {"models": {"auto": True}}).profile == "standard"


def test_no_models_section_means_every_default():
    from lean_herdr.settings import ModelsSettings, models_settings

    assert models_settings({}) == ModelsSettings()
    assert models_settings({}).auto is False


def test_a_negative_threshold_is_a_settings_error():
    from lean_herdr.settings import models_settings

    with pytest.raises(SettingsError, match="max_prompt_price"):
        models_settings({"models": {"max_prompt_price": -1.0}})


@pytest.mark.parametrize(
    "block",
    [
        {"auto": "yes"},
        {"max_age_h": "24"},
        {"min_coding_index": -1},
        {"min_context": True},
        {"min_context": 1.5},
        {"requires": "reasoning"},
        {"requires": [1]},
        {"strict": True},
    ],
    ids=[
        "auto-not-bool",
        "max_age_h-not-number",
        "min_coding_index-negative",
        "min_context-bool",
        "min_context-not-whole",
        "requires-not-a-list",
        "requires-not-strings",
        "unknown-key",
    ],
)
def test_a_wrong_models_value_is_loud(block):
    from lean_herdr.settings import models_settings

    with pytest.raises(SettingsError):
        models_settings({"models": block})


def test_the_models_section_must_be_a_table():
    from lean_herdr.settings import models_settings

    with pytest.raises(SettingsError, match="not a table"):
        models_settings({"models": "a/b"})


def test_requires_arrives_as_a_tuple():
    from lean_herdr.settings import models_settings

    values = models_settings({"models": {"requires": ["reasoning", "tools"]}})
    assert values.requires == ("reasoning", "tools")
    assert isinstance(values.requires, tuple)


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


# -- routing: [routing] -------------------------------------------------


def test_routing_is_a_known_root_key():
    assert "routing" in ROOT_KEYS
    assert settings_for("builder", {"routing": {"rename": "refactorer"}}).profile == "standard"


def test_routing_without_a_table_keeps_the_built_in_works():
    """Without `[routing]` the project dispatches exactly as it did by role name."""
    assert role_for_work("implement", {}) == "builder"
    assert role_for_work("review", None) == "reviewer"


def test_routing_overrides_a_built_in_work_and_adds_its_own():
    data = {"routing": {"implement": "coder", "rename": "refactorer"}}
    assert role_for_work("implement", data) == "coder"
    assert role_for_work("rename", data) == "refactorer"
    assert role_for_work("review", data) == "reviewer"


def test_routing_lists_the_built_in_works_under_the_table():
    assert work_roles({"routing": {"rename": "refactorer"}}) == {
        "implement": "builder",
        "review": "reviewer",
        "rename": "refactorer",
    }


@pytest.mark.parametrize("work", ["plan", "plan-review", "integrate", "deploy"])
def test_routing_knows_no_role_for_a_work_nobody_named(work):
    """The stages get their built-in roles with TP2 and TP3 -- until then, no guess."""
    with pytest.raises(SettingsError) as caught:
        role_for_work(work, {})
    assert str(caught.value) == f"no role for work {work!r}"


@pytest.mark.parametrize(
    "routing",
    [
        pytest.param({"Rename": "refactorer"}, id="work with a capital"),
        pytest.param({"re_name": "refactorer"}, id="work with an underscore"),
        pytest.param({"1st": "refactorer"}, id="work starting with a digit"),
        pytest.param({"rename": "Refactorer"}, id="role with a capital"),
        pytest.param({"rename": "re factorer"}, id="role with a space"),
        pytest.param({"rename": ""}, id="empty role"),
        pytest.param({"rename": 5}, id="role not a string"),
    ],
)
def test_routing_with_a_malformed_line_fails_every_reader(routing):
    """Checked in `_check_root`: a call by role name meets the broken line too."""
    with pytest.raises(SettingsError, match="routing"):
        settings_for("builder", {"routing": routing})


def test_routing_that_is_no_table_is_a_settings_error():
    with pytest.raises(SettingsError, match="routing: section is not a table"):
        settings_for("builder", {"routing": "builder"})


# -- role files ----------------------------------------------------------


def test_the_opencode_guard_asks_for_the_agent_it_is_given(tmp_path):
    """One guard for every role now, not only the orchestrator."""
    (tmp_path / "opencode.jsonc").write_text('{"agent": {"refactorer": {}}}\n', encoding="utf-8")
    assert missing_agent_config(tmp_path, "opencode", "refactorer") is None
    assert missing_agent_config(tmp_path, "opencode", "orchestrator") == (
        f"opencode.jsonc in {tmp_path} defines no agent.orchestrator"
    )
    assert missing_agent_config(tmp_path, "claude", "orchestrator") is None


def test_a_role_problem_is_named_in_the_order_dispatch_checks(tmp_path):
    """Prompt first, then the artefact of the runtime -- each in its own words."""
    prompt = role_prompt_path(tmp_path, "refactorer")
    claude = claude_settings_path(tmp_path, "refactorer")
    assert prompt == tmp_path / ".lean-ctx" / "lean-herdr" / "roles" / "refactorer.md"
    assert claude == tmp_path / ".lean-ctx" / "lean-herdr" / "claude" / "refactorer.json"
    for kind in KINDS:
        assert role_problem(tmp_path, "refactorer", kind, prompt) == f"no role prompt at {prompt}"

    prompt.parent.mkdir(parents=True)
    prompt.write_text("# Role: refactorer\n", encoding="utf-8")
    assert role_problem(tmp_path, "refactorer", "claude", prompt) == (
        f"no claude settings at {claude}"
    )
    assert role_problem(tmp_path, "refactorer", "opencode", prompt) == (
        f"no opencode.jsonc in {tmp_path}"
    )

    claude.parent.mkdir(parents=True)
    claude.write_text("{}\n", encoding="utf-8")
    (tmp_path / "opencode.jsonc").write_text('{"agent": {"refactorer": {}}}\n', encoding="utf-8")
    for kind in KINDS:
        assert role_problem(tmp_path, "refactorer", kind, prompt) is None
