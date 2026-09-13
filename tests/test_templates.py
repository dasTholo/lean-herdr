"""The template in the wheel is the source; this repo's copy is a copy.

`lean-herdr workspace init` writes from lean_herdr/templates/. This repo
uses itself, so every file init would write also exists here as a
checked-in copy at the place init would put it. Two spellings of one text
is exactly the drift this test exists to prevent: without it,
test_role_prohibitions.py would guard the copy while `init` shipped the
other fassung into every new project -- and the test that watches the
prohibitions would watch the wrong file.
"""

from pathlib import Path

import pytest

from lean_herdr.initcmd import LAYOUT

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "lean_herdr" / "templates"

#: `init` writes these into a target project; this repo carries each of
#: them at exactly that path. One table, imported from the code that owns
#: it -- a second copy here would drift the moment a file is added.
PAIRS = LAYOUT


@pytest.mark.parametrize(("template", "copy"), sorted(PAIRS.items()))
def test_template_and_checked_in_copy_are_byte_identical(template, copy):
    assert (TEMPLATES / template).read_bytes() == (ROOT / copy).read_bytes(), (
        f"{template} and {copy} have drifted apart"
    )


def test_no_template_without_a_pair_and_no_pair_without_a_template():
    """Both directions: a stray file ships to strangers unannounced."""
    on_disk = {p.relative_to(TEMPLATES).as_posix() for p in TEMPLATES.rglob("*") if p.is_file()}
    assert on_disk == set(PAIRS), f"unpaired: {sorted(on_disk ^ set(PAIRS))}"
