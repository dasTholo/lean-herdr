import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "herdr-plugin.toml"

#: Per `plugin link` ohne Warnung bestaetigt. `layout.updated` existiert NICHT.
GUELTIGE_EVENTS = {
    "pane.agent_detected",
    "pane.agent_status_changed",
    "pane.created",
    "pane.closed",
    "pane.exited",
    "tab.created",
    "workspace.created",
    "workspace.closed",
    "workspace.focused",
    "worktree.created",
}


def manifest() -> dict:
    return tomllib.loads(MANIFEST.read_text(encoding="utf-8"))


def test_jedes_event_ist_bekannt_und_in_punkt_notation():
    for eintrag in manifest()["events"]:
        on = eintrag["on"]
        assert "_" not in on.split(".")[0], f"{on}: Socket-Schema statt Punkt-Notation"
        assert on in GUELTIGE_EVENTS, f"{on} ist kein gueltiges Herdr-Event"


def test_kein_handler_ohne_subcommand():
    from lean_herdr.__main__ import HANDLERS

    for eintrag in manifest()["events"] + manifest()["actions"]:
        sub = eintrag["command"][-1]
        assert sub in HANDLERS, f"{sub} hat keinen Handler"


def test_die_beiden_aktionen_haengen_am_richtigen_kontext():
    nach_id = {a["id"]: a for a in manifest()["actions"]}
    assert nach_id["inject"]["contexts"] == ["pane"]
    assert nach_id["bootstrap"]["contexts"] == ["workspace"], (
        "Der Bootstrap legt einen Pane IN diesem Workspace an — Pane-Kontext "
        "waere der falsche Bezug."
    )


def test_main_ueberlebt_ein_fehlendes_handlers_modul(monkeypatch, capsys):
    """Task 13 muss ohne Task 15 durchlaufen: der Import passiert erst im Aufruf."""
    import importlib

    from lean_herdr.__main__ import main

    def kein_modul(name):
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(importlib, "import_module", kein_modul)
    assert main(["inject"]) == 0
    assert "[lean.herdr] inject fehlgeschlagen" in capsys.readouterr().err


def test_unbekannter_subcommand_ist_kein_absturz(capsys):
    from lean_herdr.__main__ import main

    assert main(["gibt-es-nicht"]) == 0
    assert "unbekannter Subcommand" in capsys.readouterr().err


@pytest.mark.integration
def test_plugin_link_erzeugt_keine_warnung(tmp_path):
    """H6: Herdr warnt bei unbekannten Events nur — hier wird die Warnung fatal."""
    if shutil.which("herdr") is None:
        pytest.skip("herdr nicht installiert")
    subprocess.run(
        ["herdr", "plugin", "link", str(ROOT)], capture_output=True, text=True, check=False
    )
    liste = subprocess.run(
        ["herdr", "plugin", "list"], capture_output=True, text=True, timeout=30, check=False
    )
    zeilen = [z for z in liste.stdout.splitlines() if "lean.herdr" in z or "warning:" in z]
    assert not any("warning:" in z for z in zeilen), "\n".join(zeilen)
