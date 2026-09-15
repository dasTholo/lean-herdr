import json
from pathlib import Path

import pytest

from lean_herdr import plancmd
from lean_herdr.bus import BusError
from lean_herdr.orderlog import append, read_events
from lean_herdr.orders import Order, fold
from lean_herdr.plancmd import (
    PLAN_RULES_SUMMARY,
    BriefError,
    PrereviewInput,
    check_result,
    compose_brief,
    main,
    next_result,
    plan_orders,
    prereview_input,
    show_result,
)
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
    `lean-md render` echoes what it was asked for. `toplevel` is what `git rev-parse
    --show-toplevel` prints; None makes it fail. Every other git call succeeds with nothing
    on stdout: `cat-file -e` finds the file, `diff --name-only` names no change.
    """

    def __init__(
        self,
        files=None,
        outlines=None,
        *,
        log="",
        status="",
        merge_base="",
        broken_render=None,
        toplevel=None,
    ):
        self.files = files or {}
        self.toplevel = toplevel
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
        if cmd[:3] == ["git", "rev-parse", "--show-toplevel"]:
            if self.toplevel is None:
                return Completed(returncode=128, stderr="fatal: not a git repository")
            return Completed(stdout=self.toplevel)
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
    """`main` resolves the root and the log itself; both point at tmp_path here.

    No git runs either: `git rev-parse --show-toplevel` cannot, so the cwd stands in.
    """
    monkeypatch.setattr(plancmd, "canonical_root", lambda cwd=None: tmp_path)
    monkeypatch.setattr(plancmd, "state_dir", lambda root=None: tmp_path)
    monkeypatch.setattr(plancmd, "run_git", lambda *_a, **_kw: None)
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
        "spec": "docs/specs/shop-design.md",
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


def _load_plan_refs(monkeypatch):
    """Every `ref` plancmd hands `load_plan`, in call order; the real function still answers."""
    refs = []
    real = plancmd.load_plan

    def spy(*args, ref=None, **kwargs):
        refs.append(ref)
        return real(*args, ref=ref, **kwargs)

    monkeypatch.setattr(plancmd, "load_plan", spy)
    return refs


def test_next_does_not_recheck_a_plan_its_plan_review_passed(tmp_path, monkeypatch):
    order(tmp_path, "o-1", "plan", spec="docs/specs/shop-design.md", done="eee1111")
    order(tmp_path, "o-2", "plan-review", done="eee1111", message="VERDIKT: result\nfine")
    order(tmp_path, "o-3", "implement", task="1", start="eee1111", done="fff1111")
    repo = Repo(
        {f"eee1111:{PLAN_FILE}": "broken", f"plan/shop:{PLAN_FILE}": "clean"},
        {"broken": BROKEN, "clean": CLEAN},
    )
    refs = _load_plan_refs(monkeypatch)
    assert next_result(ROOT, SLUG, {}, orders_dir=tmp_path, runner=repo) == {
        "ok": True,
        "step": "review",
        "task": 1,
        "work": "review",
        "after": "o-3",
    }
    assert refs == [None]
    assert (["git", "show", f"eee1111:{PLAN_FILE}"], "/repo") not in repo.calls


def test_a_plan_round_after_a_rejected_review_is_still_checked(tmp_path, monkeypatch):
    order(tmp_path, "o-1", "plan", spec="docs/specs/shop-design.md", done="eee1111")
    order(tmp_path, "o-2", "plan-review", done="eee1111", message="VERDIKT: reject\nno lanes")
    order(tmp_path, "o-3", "plan", spec="docs/specs/shop-design.md", done="eee2222")
    repo = Repo(
        {f"eee2222:{PLAN_FILE}": "broken", f"plan/shop:{PLAN_FILE}": "broken"}, {"broken": BROKEN}
    )
    refs = _load_plan_refs(monkeypatch)
    assert next_result(ROOT, SLUG, {}, orders_dir=tmp_path, runner=repo) == {
        "ok": True,
        "step": "plan",
        "work": "plan",
        "reason": "check",
        "errors": [UNKNOWN_MACRO],
        "round": 3,
        "after": "o-3",
        "spec": "docs/specs/shop-design.md",
    }
    assert refs == ["eee2222", None]


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


WT = Path("/wt/shop")


def brief(orders, task_id, repo, *, data=None):
    order_ = fold(read_events(task_id, orders=orders))
    return compose_brief(order_, root=ROOT, cwd=WT, orders_dir=orders, data=data or {}, runner=repo)


def test_an_implement_brief_is_the_brief_the_task_and_the_order(tmp_path):
    order(tmp_path, "o-1", "implement", task="2")
    repo = Repo()
    assert brief(tmp_path, "o-1", repo) == (
        "<.lean-ctx/lean-herdr/briefs/implement.lmd.md>\n\n"
        f"<{PLAN_FILE} --phase constraints>\n\n"
        f"<{PLAN_FILE} --phase task-2>\n\n"
        "## Order\n\n"
        "o-1  [created]  <- orch\n"
        "implement of plan shop"
    )
    assert {cwd for _cmd, cwd in repo.calls} == {"/wt/shop"}


def test_a_branch_implement_brief_carries_the_constraints_and_the_findings_it_answers(tmp_path):
    order(
        tmp_path,
        "o-1",
        "review",
        task="branch",
        done="eee9999",
        message="VERDIKT: reject\napp/main.py leaks a debug print",
    )
    order(tmp_path, "o-2", "implement", task="branch", after="o-1")
    text = brief(tmp_path, "o-2", Repo())
    assert f"<{PLAN_FILE} --phase constraints>" in text
    assert "--phase task-" not in text
    assert "after: o-1 (builder-plan-shop, completed)" in text
    assert "app/main.py leaks a debug print" in text


def test_a_task_review_diffs_from_the_start_head_of_the_first_implement_round(tmp_path):
    order(tmp_path, "o-1", "implement", task="2", start="aaa1111", done="ddd1111")
    order(tmp_path, "o-2", "review", task="2", done="ddd1111", message="VERDIKT: reject\nno test")
    order(tmp_path, "o-3", "implement", task="2", start="aaa2222", done="ddd2222")
    order(tmp_path, "o-4", "review", task="2")
    repo = Repo(
        log="c2 test(api): cover the route\nc1 feat(api): add the route\n",
        status=" M app/main.py\n?? notes.txt\n",
    )
    text = brief(tmp_path, "o-4", repo)
    assert (
        text.index("--phase constraints>") < text.index("--phase task-2>") < text.index("## Diff")
    )
    assert "`wt step diff aaa1111`\n" in text
    assert "- c1 feat(api): add the route" in text
    assert "- notes.txt" in text
    assert "- app/main.py" not in text
    assert (["git", "log", "--oneline", "aaa1111..HEAD"], "/wt/shop") in repo.calls


def test_without_a_start_head_the_previous_tasks_done_head_stands_in_and_says_so(tmp_path):
    order(tmp_path, "o-1", "implement", task="1", start="aaa1111", done="ddd1111")
    order(tmp_path, "o-2", "implement", task="2", done="ddd2222")
    order(tmp_path, "o-3", "review", task="2")
    text = brief(tmp_path, "o-3", Repo())
    assert (
        "`wt step diff ddd1111` (no start head on task 2: the done head of task 1 stands in)"
        in text
    )


def test_task_one_without_a_start_head_diffs_from_the_merge_base(tmp_path):
    order(tmp_path, "o-1", "implement", task="1", done="ddd1111")
    order(tmp_path, "o-2", "review", task="1")
    text = brief(tmp_path, "o-2", Repo(merge_base="m0\n"))
    assert "`wt step diff m0` (no start head on task 1: the merge base with main stands in)" in text


def test_no_base_at_all_is_a_brief_error(tmp_path):
    order(tmp_path, "o-1", "review", task="1")
    with pytest.raises(BriefError, match="^no_base: task 1 "):
        brief(tmp_path, "o-1", Repo())


def test_a_branch_review_lists_the_tasks_and_diffs_the_whole_branch(tmp_path):
    order(tmp_path, "o-1", "review", task="branch")
    repo = Repo({f"plan/shop:{PLAN_FILE}": "clean"}, {"clean": CLEAN})
    text = brief(tmp_path, "o-1", repo)
    assert "## Tasks\n\n- Task 1: models\n- Task 2: api" in text
    assert "`wt step diff` -- everything since the branch left main" in text


def test_a_plan_brief_names_the_plan_the_spec_and_the_works_with_their_models(tmp_path):
    order(tmp_path, "o-1", "plan", spec="docs/specs/shop-design.md")
    data = {
        "routing": {"implement-small": "builder-small"},
        "roles": {"builder": {"model": "opus"}, "builder-small": {"model": "sonnet"}},
    }
    text = brief(tmp_path, "o-1", Repo(), data=data)
    assert f"`{PLAN_FILE}` on branch `plan/shop`" in text
    assert "Spec: `docs/specs/shop-design.md`" in text
    assert "- `implement` -> builder, model opus" in text
    assert "- `implement-small` -> builder-small, model sonnet" in text
    assert "`review`" not in text


def test_a_plan_review_brief_carries_the_findings_of_plan_check(tmp_path):
    order(tmp_path, "o-1", "plan-review")
    repo = Repo({f"plan/shop:{PLAN_FILE}": "broken"}, {"broken": BROKEN})
    text = brief(tmp_path, "o-1", repo)
    assert "Errors:\n- [unknown_macro] line 40 (task-2): macro not found: gate" in text
    assert "Warnings:\n- none" in text


def test_an_order_outside_a_plan_gets_no_brief(tmp_path):
    order(tmp_path, "o-1", "implement", plan=None)
    with pytest.raises(BriefError, match=r"^order o-1 belongs to no plan$"):
        brief(tmp_path, "o-1", Repo())


def test_renders_run_in_the_worktree_and_the_plan_is_read_in_the_root(tmp_path):
    order(tmp_path, "o-1", "review", task="branch")
    order(tmp_path, "o-2", "plan-review")
    repo = Repo({f"plan/shop:{PLAN_FILE}": "clean"}, {"clean": CLEAN})
    brief(tmp_path, "o-1", repo)
    brief(tmp_path, "o-2", repo)
    renders = {cwd for cmd, cwd in repo.calls if cmd[:2] == ["lean-md", "render"]}
    others = {cwd for cmd, cwd in repo.calls if cmd[:2] != ["lean-md", "render"]}
    assert renders == {"/wt/shop"}
    assert others == {"/repo"}
    kinds = {tuple(cmd[:2]) for cmd, _cwd in repo.calls}
    assert {("git", "show"), ("lean-md", "outline"), ("git", "cat-file"), ("git", "diff")} <= kinds


def test_a_failing_render_names_the_file_and_the_phase(tmp_path):
    order(tmp_path, "o-1", "implement", task="1")
    with pytest.raises(BriefError) as caught:
        brief(tmp_path, "o-1", Repo(broken_render=f"{PLAN_FILE} --phase task-1"))
    assert (
        str(caught.value)
        == f"render_failed: {PLAN_FILE} --phase task-1: PHASE_ABORTED: macro not found: gate"
    )


def test_brief_prints_plain_text_and_exits_zero(cwd_repo, monkeypatch, capsys):
    order(cwd_repo, "o-1", "implement", task="1")
    monkeypatch.setattr(plancmd, "compose_brief", lambda order_, **_kw: f"brief for {order_.id}")
    assert main(["brief", "--task", "o-1"]) == 0
    assert capsys.readouterr() == ("brief for o-1\n", "")


@pytest.mark.parametrize(
    ("argv", "line"),
    [
        (["brief"], "usage_error: brief needs --task"),
        (["brief", "shop", "--task", "o-1"], "usage_error: brief takes --task, not a slug"),
        (["brief", "--task", "o-9"], "task_not_found: o-9"),
    ],
)
def test_a_failed_brief_is_one_stderr_line_and_exit_one(cwd_repo, capsys, argv, line):
    assert main(argv) == 1
    assert capsys.readouterr() == ("", line + "\n")


@pytest.mark.parametrize(
    ("error", "line"),
    [
        (
            BusError("git rev-parse --git-common-dir failed: fatal: not a git repository\nhint: x"),
            "git rev-parse --git-common-dir failed: fatal: not a git repository hint: x",
        ),
        (RuntimeError("boom\n  in line two"), "brief_crashed: boom in line two"),
    ],
    ids=["bus", "crash"],
)
def test_a_multi_line_error_is_still_one_stderr_line(cwd_repo, monkeypatch, capsys, error, line):
    order(cwd_repo, "o-1", "implement", task="1")

    def broken(*_a, **_kw):
        raise error

    monkeypatch.setattr(plancmd, "compose_brief", broken)
    assert main(["brief", "--task", "o-1"]) == 1
    assert capsys.readouterr() == ("", line + "\n")


@pytest.mark.parametrize(
    ("toplevel", "top"),
    [("/wt/shop\n", "/wt/shop"), ("", None), (None, None)],
    ids=["toplevel", "no-answer", "git-fails"],
)
def test_brief_renders_in_the_worktree_top_from_a_subdirectory(
    monkeypatch, tmp_path, capsys, toplevel, top
):
    monkeypatch.setattr(plancmd, "canonical_root", lambda cwd=None: tmp_path)
    monkeypatch.setattr(plancmd, "state_dir", lambda root=None: tmp_path)
    order(tmp_path, "o-1", "implement", task="1")
    (tmp_path / "app").mkdir()
    monkeypatch.chdir(tmp_path / "app")
    here = str(Path.cwd())
    repo = Repo(toplevel=toplevel)
    assert plancmd.brief_main(["brief", "--task", "o-1"], runner=repo) == 0
    assert capsys.readouterr().err == ""
    assert (["git", "rev-parse", "--show-toplevel"], here) in repo.calls
    renders = {cwd for cmd, cwd in repo.calls if cmd[:2] == ["lean-md", "render"]}
    assert renders == {top or here}


def test_brief_behind_a_flag_is_a_usage_error_and_no_show(cwd_repo, capsys):
    assert main(["--task", "o-1", "brief"]) == 0
    assert _line(capsys) == {
        "ok": False,
        "error": "usage_error: brief comes first: lean-herdr plan brief --task o-…",
    }


WORKTREES = {"result": {"worktrees": [{"branch": "plan/shop", "path": "/wt/shop"}]}}
SPEC_FILE = "docs/specs/shop-design.md"


def plan_order(**fields):
    return Order(id="o-1", to_agent=WORKER, state="completed", plan=SLUG, **fields)


def picked(order_, repo, worktree_list=WORKTREES):
    return prereview_input(
        order_, root=ROOT, branch="plan/shop", worktree_list=worktree_list, runner=repo
    )


def test_a_plan_is_judged_against_its_spec_from_main_and_the_rules():
    repo = Repo({f"main:{SPEC_FILE}": "# Shop\n\nThe API lists products.\n"})
    assert picked(plan_order(step="plan", spec=SPEC_FILE), repo) == PrereviewInput(
        order=f"# Shop\n\nThe API lists products.\n\n{PLAN_RULES_SUMMARY}", plan=True
    )


def test_a_task_is_judged_against_its_rendered_task_since_its_start_head():
    repo = Repo()
    got = picked(plan_order(step="implement", plan_task="2", start_head="aaa1111"), repo)
    assert got == PrereviewInput(
        order=f"<{PLAN_FILE} --phase constraints>\n\n<{PLAN_FILE} --phase task-2>", base="aaa1111"
    )
    assert {cwd for _cmd, cwd in repo.calls} == {"/wt/shop"}


@pytest.mark.parametrize(
    ("order_", "worktree_list", "repo", "skip"),
    [
        (Order(id="o-1", state="completed"), WORKTREES, Repo(), "no_plan_order"),
        (plan_order(step="plan", spec=SPEC_FILE), WORKTREES, Repo(), "spec_unreadable"),
        (
            plan_order(step="implement", plan_task="branch", start_head="aaa1111"),
            WORKTREES,
            Repo(),
            "no_prereview_for_step",
        ),
        (plan_order(step="review", plan_task="1"), WORKTREES, Repo(), "no_prereview_for_step"),
        (plan_order(step="implement", plan_task="1"), WORKTREES, Repo(), "no_start_head"),
        (
            plan_order(step="implement", plan_task="1", start_head="aaa1111"),
            {"result": "garbage"},
            Repo(),
            "worktree_unresolved",
        ),
        (
            plan_order(step="implement", plan_task="1", start_head="aaa1111"),
            WORKTREES,
            Repo(broken_render=f"{PLAN_FILE} --phase task-1"),
            "render_failed",
        ),
        (
            plan_order(step="implement", plan_task="1", start_head="aaa1111"),
            {"result": {"worktrees": [{"branch": "plan/shop", "path": 5}]}},
            Repo(),
            "worktree_unresolved",
        ),
        (
            plan_order(step="implement", plan_task="1", start_head="aaa1111"),
            {"result": {"worktrees": [{"branch": "plan/shop", "path": ""}]}},
            Repo(),
            "worktree_unresolved",
        ),
    ],
    ids=[
        "no-plan",
        "no-spec",
        "branch",
        "review",
        "no-start-head",
        "no-worktree",
        "render",
        "path-not-str",
        "path-empty",
    ],
)
def test_what_gets_no_pre_review_says_why(order_, worktree_list, repo, skip):
    assert picked(order_, repo, worktree_list) == PrereviewInput(skip=skip)
