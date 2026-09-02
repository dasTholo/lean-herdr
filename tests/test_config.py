from pathlib import Path

from lean_herdr.config import DEFAULT_HOOKS_DIR, Config


def test_from_env_reads_the_herdr_variables():
    cfg = Config.from_env(
        {
            "HERDR_PANE_ID": "w2:p2",
            "HERDR_WORKSPACE_ID": "w2",
            "HERDR_TAB_ID": "w2:t1",
            "HERDR_BIN_PATH": "/home/tholo/.local/bin/herdr",
            "HERDR_PLUGIN_STATE_DIR": "/var/state",
            "HERDR_PLUGIN_EVENT_JSON": '{"pane_id": "w2:p2", "kind": "claude"}',
        }
    )
    assert cfg.pane_id == "w2:p2" and cfg.workspace_id == "w2"
    assert cfg.herdr_bin == "/home/tholo/.local/bin/herdr"
    assert cfg.state_dir == Path("/var/state")
    assert cfg.event == {"pane_id": "w2:p2", "kind": "claude"}


def test_empty_environment_yields_usable_defaults():
    cfg = Config.from_env({})
    assert cfg.pane_id is None and cfg.state_dir is None and cfg.event is None
    assert cfg.herdr_bin == "herdr"
    assert cfg.hooks_dir == DEFAULT_HOOKS_DIR
    assert cfg.timeout == 5.0


def test_broken_event_json_does_not_break():
    assert Config.from_env({"HERDR_PLUGIN_EVENT_JSON": "{not json"}).event is None
    assert Config.from_env({"HERDR_PLUGIN_EVENT_JSON": "[1,2]"}).event is None


def test_hooks_dir_does_not_hardcode_to_claude():
    cfg = Config.from_env({"LEAN_HERDR_HOOKS_DIR": "/opt/hooks"})
    assert cfg.hooks_dir == Path("/opt/hooks")


def test_digest_path_only_with_state_dir():
    assert Config.from_env({}).digest_path("w2:p2") is None
    cfg = Config.from_env({"HERDR_PLUGIN_STATE_DIR": "/var/state"})
    assert cfg.digest_path("w2:p2") == Path("/var/state/w2:p2.md")
