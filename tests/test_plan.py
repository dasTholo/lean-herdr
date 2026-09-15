import json
from pathlib import Path

import pytest

from lean_herdr.plan import (
    BRANCH_FILES,
    Finding,
    Plan,
    PlanError,
    Task,
    branch_findings,
    load_plan,
    outline,
    plan_branch,
    plan_path,
    read_source,
    rule_findings,
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


def plan_of(*tasks, lanes=None, ref="plan/shop"):
    return Plan(
        slug=SLUG, ref=ref, tasks=tuple(tasks), lanes=lanes if lanes is not None else {"core": ()}
    )


def routed(number, work="implement", lane="core", files=("a.py",)):
    return Task(
        number, f"Task {number}", number * 10, routed=True, work=work, lane=lane, files=tuple(files)
    )


def test_a_clean_plan_has_no_findings():
    assert rule_findings(plan_of(routed(1), routed(2)), {}) == ([], [])


@pytest.mark.parametrize(
    ("plan", "expected"),
    [
        (plan_of(), [Finding("no_tasks", "the plan has no task-N phase")]),
        (
            plan_of(routed(2)),
            [Finding("task_order", "task-2 stands where task-1 belongs", 20, "task-2")],
        ),
        (
            plan_of(Task(1, "T", 10)),
            [
                Finding(
                    "no_route",
                    "task-1 does not start with @call route(work, lane, files)",
                    10,
                    "task-1",
                )
            ],
        ),
        (
            plan_of(routed(1, work="plan")),
            [
                Finding(
                    "stage_as_work",
                    "task-1: 'plan' is a stage of a plan run, not a work",
                    10,
                    "task-1",
                )
            ],
        ),
        (
            plan_of(routed(1, work="deploy")),
            [
                Finding(
                    "unknown_work", "task-1: no role for work 'deploy' in [routing]", 10, "task-1"
                )
            ],
        ),
        (
            plan_of(routed(1, lane="api")),
            [
                Finding(
                    "unknown_lane",
                    "task-1: lane 'api' is not declared in the lanes phase",
                    10,
                    "task-1",
                )
            ],
        ),
        (
            plan_of(routed(1, files=())),
            [Finding("no_files", "task-1: route names no files", 10, "task-1")],
        ),
        (
            plan_of(routed(1), lanes={"core": ("db",)}),
            [Finding("unknown_lane", "lane 'core' depends on undeclared lane 'db'", 0, "lanes")],
        ),
        (
            plan_of(routed(1), lanes={"core": ("api",), "api": ("core",)}),
            [
                Finding("lane_cycle", "lane 'api' depends on itself", 0, "lanes"),
                Finding("lane_cycle", "lane 'core' depends on itself", 0, "lanes"),
            ],
        ),
        (
            plan_of(
                routed(1, lane="api"), routed(2, lane="core"), lanes={"core": (), "api": ("core",)}
            ),
            [
                Finding(
                    "order_vs_deps",
                    "task-1 (lane 'api') comes before a task of lane 'core' it depends on",
                    10,
                    "task-1",
                )
            ],
        ),
    ],
    ids=["tasks", "order", "route", "stage", "work", "lane", "files", "dep", "cycle", "deps"],
)
def test_each_rule_names_its_finding(plan, expected):
    errors, warnings = rule_findings(plan, {})
    assert errors == expected
    assert warnings == []


def test_a_file_in_two_unrelated_lanes_is_a_warning_only():
    plan = plan_of(
        routed(1, lane="core", files=("app/x.py",)),
        routed(2, lane="api", files=("app/x.py",)),
        lanes={"core": (), "api": ()},
    )
    assert rule_findings(plan, {}) == (
        [],
        [
            Finding(
                "lane_overlap",
                "app/x.py is touched by lanes 'api' and 'core', and neither depends on the other",
            )
        ],
    )


def test_a_file_shared_along_a_dependency_is_no_overlap():
    plan = plan_of(
        routed(1, lane="core", files=("app/x.py",)),
        routed(2, lane="api", files=("app/x.py",)),
        lanes={"core": (), "api": ("core",)},
    )
    assert rule_findings(plan, {}) == ([], [])


def test_the_branch_must_carry_the_tooling():
    missing = BRANCH_FILES[1]
    proc = FakeProc(
        replies={
            ("cat-file", "-e", f"plan/shop:{missing}"): Completed(returncode=128),
            ("diff", "--name-only"): Completed(stdout=""),
        }
    )
    assert branch_findings(ROOT, plan_of(routed(1)), runner=proc) == [
        Finding(
            "missing_on_branch",
            f"plan/shop carries no {missing} -- commit the output of `lean-herdr workspace init` on main",
        )
    ]


def test_a_branch_that_changes_the_tooling_is_refused():
    proc = FakeProc(
        replies={
            ("diff", "--name-only"): Completed(stdout=".lean-ctx/lean-md/herdr-recipes.lmd.md\n")
        }
    )
    assert branch_findings(ROOT, plan_of(routed(1)), runner=proc) == [
        Finding(
            "branch_touches_tooling",
            "plan/shop changes .lean-ctx/lean-md/herdr-recipes.lmd.md; plan branches leave the tooling to main",
        )
    ]
    assert proc.called_with(
        "git",
        "diff",
        "--name-only",
        "main...plan/shop",
        "--",
        ".lean-ctx/lean-md/",
        ".lean-ctx/lean-herdr/briefs/",
    )


def test_a_plan_read_from_main_gets_no_branch_findings():
    proc = FakeProc()
    assert branch_findings(ROOT, plan_of(routed(1), ref="main"), runner=proc) == []
    assert proc.calls == []


def test_load_plan_joins_outline_rules_and_branch():
    proc = FakeProc(
        replies={
            ("show", f"plan/shop:{PLAN_FILE}"): Completed(stdout=TEXT),
            ("outline",): OUTLINE,
            ("diff", "--name-only"): Completed(stdout=""),
        }
    )
    plan = load_plan(ROOT, SLUG, {}, runner=proc)
    assert plan.ref == "plan/shop"
    assert [task.number for task in plan.tasks] == [1, 2]
    assert plan.errors == (Finding("unknown_macro", "macro not found: gate", 40, "task-2"),)
    assert plan.warnings == ()
