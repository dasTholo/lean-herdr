"""Everything outside docs/ is English -- enforced, not merely agreed.

AGENTS.md has demanded it since commit 36fc9f7; the sweep of 2026-09-02 made
the tree comply. This test keeps it that way.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: A CURATED list of unambiguous German words -- function words plus the stems
#: this repository actually produced. English homographs are deliberately
#: absent: die, man, hat, war, also, still, leer, probe, kind, hand, list,
#: mode, rest, start, weg. The list grows when a German word slips through; it
#: is a net, not a proof.
GERMAN_WORDS = frozenset(
    """
    aber alle allen als auch auf aus bei beim bereits damit dann das dass dem den
    denn der des deshalb diese diesem diesen dieser dieses doch dort durch ein eine
    einem einen einer eines etwas für fuer ganz gegen gibt haben hier ich ihm ihr
    ihre immer ist jede jeden jeder jedes kann kein keine keinen können koennen mehr
    mit muss müssen muessen nach nicht nichts nie noch nur oben oder ohne schon sehr
    sein seine sich sie sind soll sollen sondern sonst statt steht stehen über ueber
    und unser unten viel vom von wäre waere weil weiter welche wenn werden wie wieder
    wir wird wurde würde wuerde zum zur zwischen zwar
    absender aktuell anker antwort anzahl aufgabe ausführen ausfuehren bricht datei
    dateien eintrag einträge eintraege ergebnis exakt fällt faellt fehler felder
    fertig fremd fremden fremdes frist gefunden gehört gehoert gekürzt gekuerzt
    gescheitert gesehen grün gruen grund hängt haengt jetzt jüngster juengster
    kandidaten kaputt kern kette kontext läuft laeuft liste löschen loeschen möglich
    moeglich nachricht nachrichten nächste naechste nanosekunden notiz öffnen oeffnen
    pfad pfade projekt prüfen pruefen quelle rahmen roh schlüssel schluessel schritte
    später spaeter treffer ungültig ungueltig vorfahr vorfahre vorfahren vorhanden
    während waehrend wert werte zeile zeilen zeit ziel zurück zurueck
    """.split()  # noqa: SIM905 -- one prose block, so the list stays editable
)

#: Every exception carries its reason. Nothing joins this list silently.
EXCEPTIONS = {
    # A frozen recording of real lean-ctx data. Translating it would
    # falsify the measurement parse_registry() rests on --
    # test_the_frozen_sample_has_the_expected_shape pins its shape.
    "tests/fixtures/registry.sample.json": "frozen recording of a real registry",
    # This file carries the word list itself.
    "tests/test_language.py": "carries GERMAN_WORDS",
}

#: Strings that come verbatim from a frozen fixture. The recording cannot
#: change, so the test that reads it has to spell these in German. Removed
#: from the line before tokenising -- the rest of the line stays guarded.
FROZEN_IDS = {
    "tests/test_bus_parse_registry.py": (
        "m-fremdes-projekt",
        "m-mit-projekt",
        "m-ohne-projekt",
        "m-abgelaufen",
    ),
}

#: Protocol tokens that LOOK like German prose but are literals the code
#: owns. Removed from a line before tokenising, exactly like FROZEN_IDS.
#: `VERDIKT` is the literal of dispatch.VERDICT_RE: .lean-ctx/lean-herdr/roles/reviewer.md writes
#: it, every review ever written carries it, and the orchestrator reads it
#: as a machine value. It is a protocol word, not prose -- and without this
#: entry, the day somebody adds `verdikt` to GERMAN_WORDS every line in the
#: tree that carries the literal turns red for a token that is deliberately
#: spelled this way. No count here on purpose: the previous wording named
#: one ("eleven lines in five files") and was wrong by the time it was
#: read.
PROTOCOL_TOKENS = ("VERDIKT",)

_TOKEN = re.compile(r"[A-Za-zÄÖÜäöüß]+")


def german_hits(text: str, frozen: tuple[str, ...] = ()) -> set[str]:
    """The German words in `text`, tokenised across `_` as well.

    `\\b` would not split `parse_zeit`: `_` is a word character. Splitting
    on letter runs catches identifier segments and keeps `diet` from
    matching `die` at the same time. `frozen` lists strings the line quotes
    verbatim from a frozen fixture, and PROTOCOL_TOKENS the literals the
    code owns; both drop out first, the rest of the line stays guarded.
    """
    for token in (*PROTOCOL_TOKENS, *frozen):
        text = text.replace(token, " ")
    return {w for w in _TOKEN.findall(text.lower()) if w in GERMAN_WORDS}


def tracked_text_files() -> list[Path]:
    """Versioned files outside docs/, minus the exceptions and binaries.

    git ls-files, never the file system: .pytest_cache/v/cache/nodeids is
    rewritten on EVERY run and carries the German test IDs of whatever ran
    last. A file-system scan would be red right after the first pytest.
    """
    out = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    ).stdout
    files = []
    for rel in out.splitlines():
        if not rel or rel.startswith("docs/") or rel in EXCEPTIONS:
            continue
        path = ROOT / rel
        try:
            path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable -- nothing to read language from
        files.append(path)
    return files


@pytest.fixture(scope="module")
def tracked() -> list[Path]:
    if shutil.which("git") is None:
        pytest.skip("git not installed")
    return tracked_text_files()


def test_no_german_outside_docs(tracked):
    """AGENTS.md: everything outside docs/ is English."""
    offenders = []
    for path in tracked:
        rel = path.relative_to(ROOT)
        frozen = FROZEN_IDS.get(str(rel), ())
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            hits = german_hits(line, frozen)
            if hits:
                offenders.append(f"{rel}:{number}: {sorted(hits)}")
    assert not offenders, "German outside docs/:\n" + "\n".join(offenders)


def test_the_scan_catches_transliterations():
    """ae/oe/ue/ss forms evade a naive umlaut scan -- they must not evade this one."""
    assert german_hits("Der Pfad wird fuer jeden Eintrag geprueft") >= {
        "der",
        "pfad",
        "wird",
        "fuer",
        "eintrag",
    }
    assert german_hits("Die Zeilen muessen zurueck") >= {"zeilen", "muessen", "zurueck"}
    assert german_hits("this diet is a die-hard list") == set(), "no English homographs"
    frozen = FROZEN_IDS["tests/test_bus_parse_registry.py"]
    line = 'assert "m-mit-projekt" in ids'
    assert german_hits(line, frozen) == set(), "frozen ids drop out before tokenising"
    assert german_hits(line) == {"mit", "projekt"}, "the rest of the line stays guarded"


def test_the_scan_reads_tracked_files_only(tracked):
    """A file-system walk would be red after the first pytest run."""
    rels = {str(p.relative_to(ROOT)) for p in tracked}
    assert rels, "git ls-files returned nothing"
    assert not any(r.startswith("docs/") for r in rels)
    assert not any(r.startswith((".pytest_cache/", "__pycache__/")) for r in rels)
    assert not (rels & EXCEPTIONS.keys())
    assert "lean_herdr/bus.py" in rels, "the scan must actually reach the code"


def test_a_protocol_token_is_not_prose():
    """VERDIKT stays as it is -- and the scan must not turn red over it."""
    line = 'assert "VERDIKT: result" in message'
    assert german_hits(line) == set()
    # The guard is real only if the word list would otherwise fire.
    assert "verdikt" in {w.lower() for w in PROTOCOL_TOKENS}
    assert german_hits("VERDIKT: reject VERDIKT: result") == set()


def test_the_scan_still_catches_german_on_the_same_line():
    """Removing the token must not blank out the rest of the line."""
    assert german_hits('# VERDIKT ist der Schluessel') >= {"ist", "der", "schluessel"}
