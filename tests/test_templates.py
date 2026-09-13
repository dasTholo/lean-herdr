"""The template in the wheel is the source; this repo's copy is a rendering of it.

`lean-herdr workspace init` renders lean_herdr/templates/ and writes the result.
This repo uses itself, so every file init would write also exists here as a
checked-in copy at the place init would put it. Two spellings of one text is
exactly the drift this test exists to prevent: without it,
test_role_prohibitions.py would guard the copy while `init` shipped the other
version into every new project -- and the test that watches the prohibitions
would watch the wrong file.
"""

from pathlib import Path

import pytest

from lean_herdr.templating import DEFAULT_VALUES, LAYOUT, TEMPLATES, render

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(("template", "copy"), sorted(LAYOUT.items()))
def test_the_rendered_template_and_the_checked_in_copy_are_byte_identical(template, copy):
    assert render(template, DEFAULT_VALUES) == (ROOT / copy).read_bytes(), (
        f"{template} and {copy} have drifted apart"
    )


def test_no_template_without_a_pair_and_no_pair_without_a_template():
    """Both directions: a stray file ships to strangers unannounced."""
    on_disk = {p.relative_to(TEMPLATES).as_posix() for p in TEMPLATES.rglob("*") if p.is_file()}
    assert on_disk == set(LAYOUT), f"unpaired: {sorted(on_disk ^ set(LAYOUT))}"
