"""Suite-wide fixtures."""

import pytest


@pytest.fixture(autouse=True)
def no_user_claude_state(monkeypatch, tmp_path_factory):
    """claude's state file is read by `workspace check` and written by `init --trust-claude`.

    Never this machine's own in here: every test, in every module, starts with an
    empty CLAUDE_CONFIG_DIR. A test that sets the variable itself overrides this one.
    """
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path_factory.mktemp("no-claude")))
