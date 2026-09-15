import json
from pathlib import Path

import pytest

from lean_herdr import plancmd
from lean_herdr.orderlog import append
from lean_herdr.plancmd import check_result, main, next_result, plan_orders, show_result
from tests.doubles import Completed

ROOT = Path("/repo")
SLUG = "shop"
PLAN_FILE = "docs/lean-md/plans/shop.lmd.md"
WORKER = "builder-plan-shop"


def _phase(name, title, line, *calls):
    return {"name": name, "title": title, "line": line, "calls": list(calls)}


def _call(macro, line, *args):
    return {"macro": macro, "args": list(args), "line": line}


CLEAN = {
    "phases": [
        _phase("constraints", "Global Constraints", 5),
        _phase("lanes", "Lanes", 9, _call("lane", 11, "core", "")),
        _phase(
            "task-1", "Task 1: models", 15, _call("route", 16, "implement", "core", "app/models.py")
        ),
        _phase("task-2", "Task 2: api", 30, _call("route", 31, "implement", "core", "app/main.py")),
    ],
    "macros": {},
    "errors": [],
}
UNKNOWN_MACRO = {
    "kind": "unknown_macro",
    "line": 40,
    "phase": "task-2",
    "message": "macro not found: gate",
}
BROKEN = {**CLEAN, "errors": [UNKNOWN_MACRO]}
WARNED = {
    **CLEAN,
    "phases": [
        _phase("constraints", "Global Constraints", 5),
        _phase("lanes", "Lanes", 9, _call("lane", 11, "core", ""), _call("lane", 12, "api", "")),
        _phase("task-1", "Task 1: models", 15, _call("route", 16, "implement", "core", "app/x.py")),
        _phase("task-2", "Task 2: api", 30, _call("route", 31, "implement", "api", "app/x.py")),
    ],
}


class Repo:
    """`subprocess.run` for git and lean-md: answers from tables, records every call with its cwd.

    `files` maps `<ref>:<path>` to what `git show` prints; `outlines` maps a plan text to
    what `lean-md outline` prints for it -- a text without one gets lean-md 0.2.3's refusal.
    `lean-md render` echoes what it was asked for. Every other git call succeeds with nothing
    on stdout: `cat-file -e` finds the file, `diff --name-only` names no change.
    """

    def __init__(
        self, files=None, outlines=None, *, log="", status="", merge_base="", broken_render=None
    ):
        self.files = files or {}
        self.outlines = outlines or {}
        self.log = log
        self.status = status
        self.merge_base = merge_base
        self.broken_render = broken_render
        self.calls: list[tuple[list[str], str | None]] = []

    def __call__(self, cmd, **kwargs):
        self.calls.append((list(cmd), kwargs.get("cwd")))
        head = cmd[:2]
        if head == ["git", "show"]:
            text = self.files.get(cmd[2])
            return (
                Completed(stdout=text)
                if text is not None
                else Completed(returncode=128, stderr="fatal: bad object")
            )
        if head == ["git", "log"]:
            return Completed(stdout=self.log)
        if head == ["git", "status"]:
            return Completed(stdout=self.status)
        if head == ["git", "merge-base"]:
            return Completed(stdout=self.merge_base) if self.merge_base else Completed(returncode=1)
        if head == ["lean-md", "outline"]:
            data = self.outlines.get(kwargs["input"])
            if data is None:
                return Completed(returncode=1, stderr="lean-md: unknown subcommand")
            return Completed(stdout=json.dumps(data))
        if head == ["lean-md", "render"]:
            target = " ".join(cmd[2:-1])
            if target == self.broken_render:
                return Completed(returncode=1, stderr="PHASE_ABORTED: macro not found: gate\n")
            return Completed(stdout=f"<{target}>\n")
        return Completed()


def order(
    orders,
    task_id,
    step,
    *,
    task=None,
    spec=None,
    after=None,
    start=None,
    done=None,
    message="",
    plan=SLUG,
):
    """One order in the log, as `dispatch order` and `report` write it.

    `start` and `done` are the heads `report start` and `report done` stamped; `done` None
    leaves the order open. `plan=None` writes an order outside any plan.
    """
    created = {"to_agent": WORKER, "description": f"{step} of plan {plan}"}
    if plan is not None:
        created.update(plan=plan, step=step)
    for key, value in (("plan_task", task), ("spec", spec), ("after", after)):
        if value is not None:
            created[key] = value
    append(task_id, "created", "orch", created, orders=orders)
    if start is not None:
        append(task_id, "working", WORKER, {"head": start, "changes": []}, orders=orders)
    if done is not None:
        append(
            task_id,
            "completed",
            WORKER,
            {"message": message, "head": done, "changes": []},
            orders=orders,
        )


@pytest.fixture
def cwd_repo(monkeypatch, tmp_path):
    """`main` resolves the root and the log itself; both point at tmp_path here."""
    monkeypatch.setattr(plancmd, "canonical_root", lambda cwd=None: tmp_path)
    monkeypatch.setattr(plancmd, "state_dir", lambda root=None: tmp_path)
    return tmp_path


def _line(capsys):
    out = capsys.readouterr().out
    assert out.count("\n") == 1, out
    return json.loads(out)


def test_plan_orders_are_this_plans_alone_oldest_first(tmp_path):
    order(tmp_path, "o-1", "plan", spec="docs/specs/shop-design.md", done="eee1111")
    order(tmp_path, "o-2", "plan", plan="other", spec="docs/specs/other-design.md")
    order(tmp_path, "o-3", "implement", plan=None)
    order(tmp_path, "o-4", "plan-review")
    assert [o.id for o in plan_orders(SLUG, orders_dir=tmp_path)] == ["o-1", "o-4"]


def test_check_is_ok_with_warnings_alone():
    repo = Repo({f"plan/shop:{PLAN_FILE}": "warned"}, {"warned": WARNED})
    result = check_result(ROOT, SLUG, {}, runner=repo)
    assert result["ok"] is True
    assert result["ref"] == "plan/shop"
    assert result["errors"] == []
    assert [w["kind"] for w in result["warnings"]] == ["lane_overlap"]


def test_check_with_errors_is_not_ok():
    repo = Repo({f"plan/shop:{PLAN_FILE}": "broken"}, {"broken": BROKEN})
    assert check_result(ROOT, SLUG, {}, runner=repo) == {
        "ok": False,
        "slug": SLUG,
        "ref": "plan/shop",
        "errors": [UNKNOWN_MACRO],
        "warnings": [],
    }


def test_check_without_a_plan_names_both_refs():
    assert check_result(ROOT, SLUG, {}, runner=Repo()) == {
        "ok": False,
        "error": f"no_plan: plan/shop and main carry no {PLAN_FILE}",
    }


def test_next_starts_with_the_plan(tmp_path):
    assert next_result(ROOT, SLUG, {}, orders_dir=tmp_path, runner=Repo()) == {
        "ok": True,
        "step": "plan",
        "work": "plan",
        "round": 1,
    }


def test_next_is_done_once_main_carries_the_plan(tmp_path):
    order(tmp_path, "o-1", "plan", spec="docs/specs/shop-design.md", done="eee1111")
    repo = Repo({f"main:{PLAN_FILE}": "clean"}, {"clean": CLEAN})
    assert next_result(ROOT, SLUG, {}, orders_dir=tmp_path, runner=repo) == {
        "ok": True,
        "done": True,
    }


def test_next_checks_a_plan_order_at_the_head_it_reported_done_on(tmp_path):
    order(tmp_path, "o-1", "plan", spec="docs/specs/shop-design.md", done="eee1111")
    repo = Repo(
        {f"eee1111:{PLAN_FILE}": "broken", f"plan/shop:{PLAN_FILE}": "clean"},
        {"broken": BROKEN, "clean": CLEAN},
    )
    assert next_result(ROOT, SLUG, {}, orders_dir=tmp_path, runner=repo) == {
        "ok": True,
        "step": "plan",
        "work": "plan",
        "reason": "check",
        "errors": [UNKNOWN_MACRO],
        "round": 2,
        "after": "o-1",
    }
    assert (["git", "show", f"eee1111:{PLAN_FILE}"], "/repo") in repo.calls


def test_next_hands_a_clean_plan_to_the_plan_review(tmp_path):
    order(tmp_path, "o-1", "plan", spec="docs/specs/shop-design.md", done="eee1111")
    repo = Repo(
        {f"eee1111:{PLAN_FILE}": "clean", f"plan/shop:{PLAN_FILE}": "clean"}, {"clean": CLEAN}
    )
    assert next_result(ROOT, SLUG, {}, orders_dir=tmp_path, runner=repo) == {
        "ok": True,
        "step": "plan-review",
        "work": "plan-review",
    }


def test_next_without_lean_md_outline_is_a_config_error(tmp_path):
    order(tmp_path, "o-1", "plan", spec="docs/specs/shop-design.md", done="eee1111")
    repo = Repo({f"eee1111:{PLAN_FILE}": "clean"})
    assert next_result(ROOT, SLUG, {}, orders_dir=tmp_path, runner=repo) == {
        "ok": False,
        "error": "config_error: lean-md outline unavailable (needs lean-md >= 0.2.4)",
    }


def test_show_lists_the_planning_orders_and_every_task(tmp_path):
    order(tmp_path, "o-1", "plan", spec="docs/specs/shop-design.md", done="eee1111")
    order(tmp_path, "o-2", "plan-review", done="eee1111", message="VERDIKT: result\nfine")
    order(tmp_path, "o-3", "implement", task="1", start="eee1111")
    repo = Repo({f"plan/shop:{PLAN_FILE}": "clean"}, {"clean": CLEAN})
    result = show_result(ROOT, SLUG, {}, orders_dir=tmp_path, runner=repo)
    assert result["ok"] is True
    assert result["planning"] == [
        {"task_id": "o-1", "step": "plan", "state": "completed"},
        {"task_id": "o-2", "step": "plan-review", "state": "completed"},
    ]
    assert [(t["task"], t["state"], t["orders"]) for t in result["tasks"]] == [
        (1, "working", ["o-3"]),
        (2, "pending", []),
    ]


def test_main_hands_the_slug_and_the_config_to_check(cwd_repo, monkeypatch, capsys):
    seen = {}

    def fake(root, slug, data, **_kw):
        seen.update(root=root, slug=slug, data=data)
        return {"ok": True, "errors": [], "warnings": []}

    monkeypatch.setattr(plancmd, "check_result", fake)
    assert main(["check", "shop"]) == 0
    assert _line(capsys) == {"ok": True, "errors": [], "warnings": []}
    assert seen == {"root": cwd_repo, "slug": "shop", "data": {}}


@pytest.mark.parametrize(
    ("argv", "error"),
    [
        (["next"], "usage_error: next needs a slug"),
        (
            ["check", "Shop"],
            r"usage_error: 'Shop' is no plan slug ((?=.{1,12}\Z)[a-z][a-z0-9]*(?:-[a-z0-9]+)*)",
        ),
        (["show", "shop", "--task", "o-1"], "usage_error: show does not take --task"),
    ],
)
def test_main_refuses_bad_arguments_as_one_json_line(cwd_repo, capsys, argv, error):
    assert main(argv) == 0
    assert _line(capsys) == {"ok": False, "error": error}


def test_an_unknown_subcommand_is_a_usage_error_too(cwd_repo, capsys):
    assert main(["merge", "shop"]) == 0
    assert _line(capsys)["error"].startswith("usage_error: argument command")


def test_a_crash_is_still_one_json_line(cwd_repo, monkeypatch, capsys):
    def boom(*_a, **_kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(plancmd, "next_result", boom)
    assert main(["next", "shop"]) == 0
    assert _line(capsys) == {"ok": False, "error": "plan_crashed: boom"}


def test_a_broken_routing_table_is_a_config_error(cwd_repo, capsys):
    config = cwd_repo / ".lean-ctx" / "lean-herdr" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text('[routing]\nimplement = "Bad Role"\n', encoding="utf-8")
    assert main(["check", "shop"]) == 0
    assert _line(capsys)["error"].startswith("config_error: routing.implement:")
