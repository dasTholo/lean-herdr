"""The log next to a real lean-ctx install, in an isolated data directory.

Runs only under `-m integration`. Every test sets LEAN_CTX_DATA_DIR to
tmp_path -- without it they would write into the operator's real store.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from lean_herdr.orderlog import append, read_events, state_dir

pytestmark = pytest.mark.integration


@pytest.fixture
def isolated(tmp_path, monkeypatch) -> Path:
    if shutil.which("lean-ctx") is None:
        pytest.skip("lean-ctx not installed")
    monkeypatch.setenv("LEAN_CTX_DATA_DIR", str(tmp_path))
    return tmp_path


def test_the_log_lands_beside_the_lean_ctx_data_and_survives_it(isolated, tmp_path):
    """Spec section 4: lean-ctx tolerates a foreign namespace in its data dir."""
    root = tmp_path / "repo"
    orders = state_dir(root)
    append("o-probe-1", "created", "orchestrator", {"description": "x"}, orders=orders)
    subprocess.run(
        [
            "lean-ctx",
            "call",
            "ctx_task",
            "--project-root",
            str(root),
            "--json",
            json.dumps({"action": "info"}),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert read_events("o-probe-1", orders=orders)[0].kind == "created"
    assert (orders.parent / "root").exists()
