"""The files a plan run renders: the plan template, the recipes, the Python pack, the briefs, pylsp.

`tests/test_templates.py` keeps the checked-in copies byte-identical; this file pins what
each one has to say for a plan run to work at all.
"""

import os
import re
from pathlib import Path

import pytest

from lean_herdr.templating import DEFAULT_VALUES, EXECUTABLE, render

ROOT = Path(__file__).resolve().parents[1]
BRIEFS = ("implement", "review", "plan", "plan-review")

#: An `@define` line and the first line of its body.
DEFINE_RE = re.compile(r"^@define (\w+)\((.*)\)$\n(.*)$", re.MULTILINE)


def rendered(name: str) -> str:
    return render(name, DEFAULT_VALUES).decode("utf-8")


@pytest.mark.parametrize("step", BRIEFS)
def test_every_brief_is_a_lean_md_document_with_the_hard_rules(step):
    text = rendered(f"briefs/{step}.lmd.md")
    assert text.startswith("@lean-md\n")
    assert "\n@include hard-rules\n" in text


@pytest.mark.parametrize(
    ("step", "sentence"),
    [
        ("implement", "wt step commit --stage none --yes"),
        ("implement", "Never `git commit -m`, never `git add -A`, never push, never merge."),
        ("implement", "status: DONE | DONE_WITH_CONCERNS"),
        ("review", "Produce TWO verdicts from this one diff read."),
        ("review", "Any Critical or Important finding: `VERDIKT: reject`."),
        ("review", "You write nothing: no file, no commit, not through `ctx_shell` either."),
        ("plan", ".lean-ctx/lean-md/herdr-plan-template.lmd.md"),
        ("plan", "lean-herdr plan check <slug>"),
        ("plan", "Only once `ok` is true:"),
        ("plan-review", "Every `errors` entry of `plan check` is a reason to reject."),
        ("plan-review", "You write nothing: no file, no commit, not through `ctx_shell` either."),
    ],
)
def test_each_brief_carries_its_rules(step, sentence):
    text = " ".join(rendered(f"briefs/{step}.lmd.md").split())
    assert sentence in text


def test_the_recipes_define_route_lane_commit_and_gate_each_with_a_description():
    text = rendered("lean-md/herdr-recipes.lmd.md")
    assert text.count("\n@import .lean-ctx/lean-md/plan-recipes /\n") == 1
    defines = {name: (params, first) for name, params, first in DEFINE_RE.findall(text)}
    assert set(defines) == {"route", "lane", "commit", "gate"}
    assert defines["route"][0] == "work, lane, files"
    assert defines["lane"][0] == "name, deps"
    assert all(first.startswith("<!--") for _params, first in defines.values())


def test_the_recipes_commit_through_worktrunk_and_gate_with_this_projects_commands():
    text = rendered("lean-md/herdr-recipes.lmd.md")
    assert "wt step commit --stage none --yes" in text
    assert "git commit" not in text
    assert f"`{DEFAULT_VALUES['test']}`" in text
    assert f"`{DEFAULT_VALUES['lint']}`" in text


def test_the_plan_template_carries_the_required_phases_and_routes_its_task():
    text = rendered("lean-md/herdr-plan-template.lmd.md")
    assert "\n@import .lean-ctx/lean-md/herdr-recipes /\n" in text
    for phase in ("constraints", "lanes", "task-1"):
        assert f'\n@phase "{phase}"\n' in text, phase
    assert text.split('\n@phase "task-1"\n', 1)[1].startswith("@call route(")


def test_the_python_pack_names_the_test_files_and_no_rename_refactor():
    text = " ".join(rendered("lean-md/lang/python.lmd.md").split())
    assert "always name the files" in text
    assert "No `@refactor` for rename or move" in text


def test_pylsp_hands_the_language_server_to_ty():
    text = rendered("bin/pylsp")
    assert text.startswith("#!/bin/sh\n")
    assert 'exec ty server "$@"' in text


def test_the_checked_in_pylsp_is_executable():
    assert EXECUTABLE == {".lean-ctx/lean-herdr/bin/pylsp"}
    for relative in EXECUTABLE:
        assert os.access(ROOT / relative, os.X_OK), relative
