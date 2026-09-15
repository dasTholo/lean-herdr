import json
from pathlib import Path

import pytest

from lean_herdr.plan import (
    Finding,
    PlanError,
    Task,
    outline,
    plan_branch,
    plan_path,
    read_source,
    structure,
)
from tests.doubles import Completed, FakeProc

ROOT = Path("/repo")
SLUG = "shop"
PLAN_FILE = "docs/lean-md/plans/shop.lmd.md"
TEXT = "@lean-md\n# shop\n"

OUTLINE = {
    "phases": [
        {"name": "constraints", "title": "Global Constraints", "line": 5, "calls": []},
        {
            "name": "lanes",
            "title": "Lanes",
            "line": 9,
            "calls": [
                {"macro": "lane", "args": ["core", ""], "line": 11},
                {"macro": "lane", "args": ["api", "core"], "line": 12},
            ],
        },
        {
            "name": "task-1",
            "title": "Task 1: models",
            "line": 15,
            "calls": [
                {
                    "macro": "route",
                    "args": ["implement", "core", "app/models.py tests/test_models.py"],
                    "line": 16,
                }
            ],
        },
        {
            "name": "task-2",
            "title": "Task 2: api",
            "line": 30,
            "calls": [
                {"macro": "route", "args": ["implement", "api", "app/main.py"], "line": 31},
                {"macro": "commit", "args": ["app/main.py", "feat: api"], "line": 50},
            ],
        },
    ],
    "macros": {"lane": ["name", "deps"], "route": ["work", "lane", "files"]},
    "errors": [
        {"kind": "unknown_macro", "line": 40, "phase": "task-2", "message": "macro not found: gate"}
    ],
}


def test_paths_follow_the_slug():
    assert plan_path(SLUG) == PLAN_FILE
    assert plan_branch(SLUG) == "plan/shop"


def test_the_plan_branch_is_read_first():
    proc = FakeProc(replies={("show", f"plan/shop:{PLAN_FILE}"): Completed(stdout=TEXT)})
    assert read_source(ROOT, SLUG, runner=proc) == ("plan/shop", TEXT)
    assert proc.calls[0] == ["git", "show", f"plan/shop:{PLAN_FILE}"]


def test_main_carries_the_plan_after_the_merge():
    proc = FakeProc(
        replies={
            ("show", f"plan/shop:{PLAN_FILE}"): Completed(
                returncode=128, stderr="invalid object name"
            ),
            ("show", f"main:{PLAN_FILE}"): Completed(stdout=TEXT),
        }
    )
    assert read_source(ROOT, SLUG, runner=proc) == ("main", TEXT)


def test_an_explicit_ref_is_the_only_one_asked():
    proc = FakeProc(replies={("show", f"abc123:{PLAN_FILE}"): Completed(stdout=TEXT)})
    assert read_source(ROOT, SLUG, ref="abc123", runner=proc) == ("abc123", TEXT)
    assert len(proc.calls) == 1


def test_no_ref_carrying_the_plan_is_no_plan():
    with pytest.raises(PlanError) as caught:
        read_source(ROOT, SLUG, runner=FakeProc(default=Completed(returncode=128)))
    assert str(caught.value) == f"no_plan: plan/shop and main carry no {PLAN_FILE}"


def test_outline_hands_the_plan_on_stdin_and_runs_in_the_root():
    seen = {}

    def runner(cmd, **kwargs):
        seen["cmd"], seen["kwargs"] = cmd, kwargs
        return Completed(stdout=json.dumps(OUTLINE))

    assert outline(ROOT, TEXT, runner=runner) == OUTLINE
    assert seen["cmd"] == [
        "lean-md",
        "outline",
        "-",
        "--json",
        "--require-phase",
        "constraints,lanes",
    ]
    assert seen["kwargs"]["input"] == TEXT
    assert seen["kwargs"]["cwd"] == "/repo"


@pytest.mark.parametrize(
    "reply",
    [
        Completed(returncode=1, stderr="Usage: lean-md <render|check|mcp|skill|source|ack> [args]"),
        Completed(stdout="[]"),
        Completed(stdout=json.dumps({"errors": []})),
    ],
)
def test_without_an_outline_json_lean_md_is_too_old(reply):
    with pytest.raises(PlanError) as caught:
        outline(ROOT, TEXT, runner=FakeProc(default=reply))
    assert str(caught.value) == "config_error: lean-md outline unavailable (needs lean-md >= 0.2.4)"


def test_findings_exit_one_and_still_carry_the_outline():
    reply = Completed(returncode=1, stdout=json.dumps(OUTLINE))
    assert outline(ROOT, TEXT, runner=FakeProc(default=reply)) == OUTLINE


def test_a_missing_lean_md_is_unavailable_too():
    with pytest.raises(PlanError):
        outline(ROOT, TEXT, runner=FakeProc(raises=FileNotFoundError("lean-md")))


def test_structure_reads_tasks_lanes_and_lean_md_findings():
    plan = structure(SLUG, "plan/shop", OUTLINE)
    assert plan.tasks == (
        Task(
            1,
            "Task 1: models",
            15,
            routed=True,
            work="implement",
            lane="core",
            files=("app/models.py", "tests/test_models.py"),
        ),
        Task(
            2, "Task 2: api", 30, routed=True, work="implement", lane="api", files=("app/main.py",)
        ),
    )
    assert plan.lanes == {"core": (), "api": ("core",)}
    assert plan.errors == (Finding("unknown_macro", "macro not found: gate", 40, "task-2"),)


def test_a_task_whose_first_call_is_no_route_is_unrouted():
    data = {
        "phases": [
            {
                "name": "task-1",
                "title": "T",
                "line": 3,
                "calls": [{"macro": "commit", "args": ["a", "b"], "line": 4}],
            }
        ]
    }
    assert structure(SLUG, "plan/shop", data).tasks == (Task(1, "T", 3),)


def test_a_finding_leaves_out_an_absent_phase():
    assert Finding("import", "x").as_json() == {"kind": "import", "line": 0, "message": "x"}
