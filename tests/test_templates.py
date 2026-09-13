"""The template in the wheel is the source; this repo's copy is a rendering of it.

`lean-herdr workspace init` renders lean_herdr/templates/ and writes the result.
This repo uses itself, so every file init would write also exists here as a
checked-in copy at the place init would put it. Two spellings of one text is
exactly the drift this test exists to prevent: without it,
test_role_prohibitions.py would guard the copy while `init` shipped the other
version into every new project -- and the test that watches the prohibitions
would watch the wrong file.

The lock of this repository is held too. `file_state` checks D = P before it ever
looks at the lock, so byte identity alone would pass over a missing or stale
lock -- and a stale entry turns a later hand edit into `diverged` instead of
`edited`. Every template change therefore pulls the lock along:
`uv run lean-herdr workspace init`.
"""

from pathlib import Path

import pytest

from lean_herdr.templating import (
    LAYOUT,
    LOCK_PATH,
    TEMPLATES,
    digest,
    file_state,
    read_lock,
    render,
    resolve_values,
)

ROOT = Path(__file__).resolve().parents[1]


def test_this_repository_carries_its_lock():
    assert (ROOT / LOCK_PATH).is_file(), f"no {LOCK_PATH} -- run `uv run lean-herdr workspace init`"
    assert set(read_lock(ROOT)["files"]) == set(LAYOUT.values())


@pytest.mark.parametrize(("template", "copy"), sorted(LAYOUT.items()))
def test_the_rendered_template_and_the_checked_in_copy_are_byte_identical(template, copy):
    rendered = render(template, resolve_values(read_lock(ROOT)["values"]))
    assert rendered == (ROOT / copy).read_bytes(), f"{template} and {copy} have drifted apart"


@pytest.mark.parametrize(("template", "copy"), sorted(LAYOUT.items()))
def test_every_lock_entry_is_the_checked_in_copy(template, copy):
    lock = read_lock(ROOT)
    assert lock["files"].get(copy) == digest((ROOT / copy).read_bytes()), (
        f"{LOCK_PATH}: the entry for {copy} is stale -- run `uv run lean-herdr workspace init`"
    )
    rendered = render(template, resolve_values(lock["values"]))
    assert file_state(ROOT, copy, rendered=rendered, locked=lock["files"][copy]) == "current"


def test_no_template_without_a_pair_and_no_pair_without_a_template():
    """Both directions: a stray file ships to strangers unannounced."""
    on_disk = {p.relative_to(TEMPLATES).as_posix() for p in TEMPLATES.rglob("*") if p.is_file()}
    assert on_disk == set(LAYOUT), f"unpaired: {sorted(on_disk ^ set(LAYOUT))}"
