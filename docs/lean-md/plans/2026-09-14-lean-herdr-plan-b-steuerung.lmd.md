@lean-md
consumer: ai
crp: compact

@var test_cmd default="uv run pytest -q" desc="project test runner command"
@var lint_cmd default="uv run ruff check ." desc="project lint gate"
@import .lean-ctx/lean-md/plan-recipes /

@define py_gate(paths)
<!-- Python pre-commit bar: ruff format on the paths, ruff check, ty check, full test suite -->
1. Run: `uv run ruff check --select I --fix {{ paths }}` — sortiert die Importe (I001).
2. Run: `uv run ruff format {{ paths }}`
3. Run: `uv run ruff check .` — Expected: keine Befunde.
4. Run: `uv run ty check` — Expected: keine Befunde.
5. Run: `uv run pytest -q` — Expected: PASS.
@define-end

# lean-herdr TP2 — Plan B: Plan lesen und steuern

Spec: `docs/specs/2026-09-14-lean-herdr-plan-design.md` (§3, §6.1–§6.6).
Teil 2 von 3; setzt Plan A „Auftrag und Stempel" voraus, danach Plan C „Ausliefern".
Render je Task: `lean-md render docs/lean-md/plans/2026-09-14-lean-herdr-plan-b-steuerung.lmd.md --phase task-N`.

## Goal

lean-herdr liest einen Plan von seinem Branch, prüft ihn und sagt dem Orchestrator den nächsten
Schritt: `lean-herdr plan check | next | show | brief`. Das Pre-Review beurteilt im Plan-Modus
den Plan gegen die Spec und eine Task-Änderung gegen die gerenderte Task.

- **Task 1** — `plan.py`: Quelle lesen (`git show`), `lean-md outline`, Struktur.
- **Task 2** — `plan.py`: Regeln aus §3, Befunde am Branch, `load_plan`.
- **Task 3** — `planrun.py`: `next_step`, `task_summary` — rein, ohne I/O.
- **Task 4** — `plancmd.py`: `check`, `next`, `show`; Verb `plan` in `cli.py`.
- **Task 5** — `plancmd.py`: `brief`; `report.order_text` wird öffentlich.
- **Task 6** — Pre-Review im Plan-Modus: `llm`, `plancmd.prereview_input`, `dispatch.await_task`.

## Architecture

```
lean_herdr/plan.py      + PlanError, Finding, Task, Plan, plan_path, plan_branch, run_git, show,
                          read_source, outline, structure                                (Task 1)
                        + BRANCH_FILES, TOOLING_DIRS, rule_findings, branch_findings, load_plan (Task 2)
lean_herdr/planrun.py   + TRACKED_CHANGES, next_step, task_summary                        (Task 3)
lean_herdr/plancmd.py   + plan_orders, check_result, next_result, show_result, build_parser,
                          missing_flags, main                                             (Task 4)
                        + BRIEFS_DIR, BriefError, render, compose_brief, brief_main        (Task 5)
                        + PLAN_RULES_SUMMARY, PrereviewInput, prereview_input             (Task 6)
lean_herdr/cli.py       + VERBS["plan"], USAGE (Task 4); USAGE-Zeile für `plan brief`        (Task 5)
lean_herdr/report.py    ~ _brief → order_text                                             (Task 5)
lean_herdr/llm.py       + PLAN_PREREVIEW_PROMPT; wt_diff(base=), prereview(plan=),
                          prereview_result(base=, plan=); CLI --base, --plan               (Task 6)
lean_herdr/dispatch.py  ~ await_task holt Auftrag, Basis und Prompt für Plan-Aufträge     (Task 6)
tests/test_plan.py, tests/test_planrun.py, tests/test_plancmd.py (neu); tests/test_llm.py,
tests/test_dispatch_prereview.py
```

Wiederverwendet: `orders.fold`/`message_from`, `orderlog.read_events`/`task_ids`/`state_dir`,
`dispatch.verdict` (`lean_herdr/dispatch.py:360-368`), `dispatch.UsageError`/`_Parser`
(`:561-576`, wie in `catalog.py`), `settings.work_roles`/`role_for_work`/`settings_for`/`STAGES`,
`worktree.find_worktree`, `bus.canonical_root`. Subprozess-Muster: `checkcmd._run`
(`lean_herdr/checkcmd.py:99-122`). Pre-Review heute: `llm.wt_diff` (`lean_herdr/llm.py:413-448`),
`llm.prereview` (`:451-515`), `llm.prereview_result` (`:518-572`), Aufruf in
`dispatch.await_task` (`lean_herdr/dispatch.py:499-513`). Test-Muster: `tests/doubles.py`
(`FakeProc`, `Completed`), `tests/test_dispatch_prereview.py` (`wait`, `llm_doubles`,
`no_network`), `tests/test_llm.py` (`SpyRequest`, `answer`, `no_store`, `worktrees`, `NO_FILE`).

Aus Plan A (gemergt): `Order.plan/step/plan_task/spec`, `Order.start_head/done_head`,
`Order.done_changes` (`None` = unbekannt), `orders.PLAN_SLUG_RE`, `report.worktree_stamp`.

## Global Constraints

- Voraussetzung: Plan A ist auf `main`.
- Non-Goals: keine Brief-, Template- oder Rollen-Dateien, kein eingebautes Routing für
  `plan`/`plan-review`, keine Änderung an `orchestrator.md` (alles Plan C); kein Python-Parser für
  `@call`-Syntax — die Struktur kommt aus `lean-md outline`; keine Parallelität.
- Kein Test ruft `lean-md`, `git`, `wt` oder das Netz wirklich auf; jede Seam bekommt ein Double.
- CLI-Vertrag: `plan check | next | show` schreiben eine JSON-Zeile mit `ok`, Exit 0.
  `plan brief` schreibt Klartext; ein Fehler ist eine Zeile auf stderr und Exit 1.
- `planrun.py` macht kein I/O: kein Subprozess, kein Dateizugriff, keine Uhr.
- Das Pre-Review eines Auftrags ohne Plan bleibt, wie es ist, bis auf die Grenze: `MAX_DIFF_BYTES`
  gilt für Diff und Auftrag zusammen (Spec §6.6). Die bestehenden Tests in `tests/test_llm.py` und
  `tests/test_dispatch_prereview.py` bleiben grün; nur die zwei CLI-Tests, die alle Argumente an
  `wt_diff`/`prereview` festhalten, erwarten zusätzlich `base` und `plan` (Task 6).
- Jeder Brief endet mit dem Auftragstext (`report.order_text`), auch wo Spec §6.5 ihn nicht nennt:
  eine zweite Runde braucht die Befunde, auf die sie antwortet.
- Reihenfolge 1 → 2 → 3 → 4 → 5 → 6.
- Keine Datei unter `lean_herdr/` über 800 Produktions-LOC.

@phase "task-1"
## Task 1: `plan.py` — Quelle, Outline, Struktur

**Files:** Create `lean_herdr/plan.py`, `tests/test_plan.py`.

**Interfaces — Produces** (`lean_herdr/plan.py`):

    PLANS_DIR = "docs/lean-md/plans"
    REQUIRED_PHASES = ("constraints", "lanes")
    class PlanError(Exception)            # Nachricht beginnt mit dem Fehlercode
    @dataclass(frozen=True) class Finding(kind: str, message: str, line: int = 0, phase: str | None = None)
        def as_json(self) -> dict[str, Any]   # "phase" fehlt, wenn None
    @dataclass(frozen=True) class Task(number: int, title: str, line: int, routed: bool = False,
                                       work: str = "", lane: str = "", files: tuple[str, ...] = ())
    @dataclass(frozen=True) class Plan(slug: str, ref: str, tasks: tuple[Task, ...],
                                       lanes: dict[str, tuple[str, ...]] = {}, errors: tuple[Finding, ...] = (),
                                       warnings: tuple[Finding, ...] = ())
    def plan_path(slug: str) -> str       # "docs/lean-md/plans/<slug>.lmd.md"
    def plan_branch(slug: str) -> str     # "plan/<slug>"
    def run_git(root: Path, *args: str, runner=subprocess.run) -> subprocess.CompletedProcess[str] | None  # None: git not runnable
    def show(root: Path, ref: str, path: str, *, runner=subprocess.run) -> str | None
    def read_source(root: Path, slug: str, *, ref: str | None = None, runner=subprocess.run) -> tuple[str, str]
    def outline(root: Path, text: str, *, runner=subprocess.run) -> dict[str, Any]
    def structure(slug: str, ref: str, data: dict[str, Any]) -> Plan

`read_source` fragt `ref`, sonst `plan/<slug>`, dann `main`; keiner trägt die Datei →
`PlanError("no_plan: <refs mit ' and '> carry no <pfad>")`. `outline` hat keine JSON-Antwort
mit `phases` → `PlanError("config_error: lean-md outline unavailable (needs lean-md >= 0.2.4)")`.

### Schritt 1 — Tests zuerst

`tests/test_plan.py`:

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
                    {"macro": "route", "args": ["implement", "core", "app/models.py tests/test_models.py"], "line": 16}
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
        "errors": [{"kind": "unknown_macro", "line": 40, "phase": "task-2", "message": "macro not found: gate"}],
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
                ("show", f"plan/shop:{PLAN_FILE}"): Completed(returncode=128, stderr="invalid object name"),
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
        assert seen["cmd"] == ["lean-md", "outline", "-", "--json", "--require-phase", "constraints,lanes"]
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
            Task(1, "Task 1: models", 15, routed=True, work="implement", lane="core",
                 files=("app/models.py", "tests/test_models.py")),
            Task(2, "Task 2: api", 30, routed=True, work="implement", lane="api", files=("app/main.py",)),
        )
        assert plan.lanes == {"core": (), "api": ("core",)}
        assert plan.errors == (Finding("unknown_macro", "macro not found: gate", 40, "task-2"),)


    def test_a_task_whose_first_call_is_no_route_is_unrouted():
        data = {
            "phases": [
                {"name": "task-1", "title": "T", "line": 3, "calls": [{"macro": "commit", "args": ["a", "b"], "line": 4}]}
            ]
        }
        assert structure(SLUG, "plan/shop", data).tasks == (Task(1, "T", 3),)


    def test_a_finding_leaves_out_an_absent_phase():
        assert Finding("import", "x").as_json() == {"kind": "import", "line": 0, "message": "x"}

Run: `uv run pytest -q tests/test_plan.py`

Expected: FAIL — `ModuleNotFoundError: No module named 'lean_herdr.plan'`.

### Schritt 2 — Implementierung

`lean_herdr/plan.py`:

    """A plan as data: read it off its branch, outline it with lean-md, check lean-herdr's rules.

    `lean-md outline` parses the document; nothing here reads `@call` syntax itself. What is
    left for this module is what only lean-herdr knows: the branch a plan lives on, the works
    `[routing]` routes, and the rules of the spec's section 3.
    """

    from __future__ import annotations

    import json
    import re
    import subprocess
    from dataclasses import dataclass, field
    from pathlib import Path
    from typing import Any

    PLANS_DIR = "docs/lean-md/plans"

    #: The phases every plan carries besides its tasks.
    REQUIRED_PHASES = ("constraints", "lanes")

    TASK_PHASE_RE = re.compile(r"task-([1-9][0-9]*)")

    GIT_TIMEOUT_S = 10.0
    OUTLINE_TIMEOUT_S = 30.0


    class PlanError(Exception):
        """A plan that cannot be read at all. The message starts with its error code."""


    @dataclass(frozen=True)
    class Finding:
        kind: str
        message: str
        line: int = 0
        phase: str | None = None

        def as_json(self) -> dict[str, Any]:
            out: dict[str, Any] = {"kind": self.kind, "line": self.line, "message": self.message}
            if self.phase is not None:
                out["phase"] = self.phase
            return out


    @dataclass(frozen=True)
    class Task:
        number: int
        title: str
        line: int
        #: The first `@call` of the phase is `route`; the three fields below come from it.
        routed: bool = False
        work: str = ""
        lane: str = ""
        files: tuple[str, ...] = ()


    @dataclass(frozen=True)
    class Plan:
        slug: str
        #: The ref the text was read from: `plan/<slug>`, `main`, or a commit.
        ref: str
        tasks: tuple[Task, ...]
        lanes: dict[str, tuple[str, ...]] = field(default_factory=dict)
        errors: tuple[Finding, ...] = ()
        warnings: tuple[Finding, ...] = ()


    def plan_path(slug: str) -> str:
        return f"{PLANS_DIR}/{slug}.lmd.md"


    def plan_branch(slug: str) -> str:
        return f"plan/{slug}"


    def run_git(root: Path, *args: str, runner: Any) -> subprocess.CompletedProcess[str] | None:
        """One read-only git command in `root`. None when it cannot run at all."""
        try:
            return runner(
                ["git", *args],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=GIT_TIMEOUT_S,
                cwd=str(root),
                check=False,
            )
        except (OSError, subprocess.SubprocessError, ValueError):
            return None


    def show(root: Path, ref: str, path: str, *, runner: Any = subprocess.run) -> str | None:
        """`git show <ref>:<path>` -- None when the ref or the file is not there."""
        proc = run_git(root, "show", f"{ref}:{path}", runner=runner)
        return proc.stdout if proc is not None and proc.returncode == 0 else None


    def read_source(
        root: Path, slug: str, *, ref: str | None = None, runner: Any = subprocess.run
    ) -> tuple[str, str]:
        """`(ref, text)` of the plan: `ref` when given, else `plan/<slug>`, else `main`.

        `main` carries the plan once the branch is merged and gone.
        """
        refs = (ref,) if ref else (plan_branch(slug), "main")
        for candidate in refs:
            text = show(root, candidate, plan_path(slug), runner=runner)
            if text is not None:
                return candidate, text
        raise PlanError(f"no_plan: {' and '.join(refs)} carry no {plan_path(slug)}")


    def outline(root: Path, text: str, *, runner: Any = subprocess.run) -> dict[str, Any]:
        """`lean-md outline - --json --require-phase constraints,lanes`, run in `root`.

        The exit code is not read: 0 and 1 both carry the JSON. What proves the subcommand
        exists is the JSON itself -- lean-md 0.2.3 ends an unknown subcommand with exit 1 too.
        """
        unavailable = PlanError("config_error: lean-md outline unavailable (needs lean-md >= 0.2.4)")
        try:
            proc = runner(
                ["lean-md", "outline", "-", "--json", "--require-phase", ",".join(REQUIRED_PHASES)],
                input=text,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=OUTLINE_TIMEOUT_S,
                cwd=str(root),
                check=False,
            )
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            raise unavailable from exc
        try:
            data = json.loads(proc.stdout or "")
        except json.JSONDecodeError as exc:
            raise unavailable from exc
        if not isinstance(data, dict) or not isinstance(data.get("phases"), list):
            raise unavailable
        return data


    def _args(call: dict[str, Any]) -> list[str]:
        return [str(arg) for arg in call.get("args") or []]


    def structure(slug: str, ref: str, data: dict[str, Any]) -> Plan:
        """Tasks and lanes out of the outline, plus lean-md's own findings -- no rule of ours yet."""
        errors = tuple(
            Finding(
                kind=str(error.get("kind", "")),
                message=str(error.get("message", "")),
                line=int(error.get("line") or 0),
                phase=error.get("phase"),
            )
            for error in data.get("errors") or []
            if isinstance(error, dict)
        )
        tasks: list[Task] = []
        lanes: dict[str, tuple[str, ...]] = {}
        for phase in data.get("phases") or []:
            if not isinstance(phase, dict):
                continue
            name = str(phase.get("name", ""))
            calls = [call for call in phase.get("calls") or [] if isinstance(call, dict)]
            if name == "lanes":
                for call in calls:
                    args = _args(call)
                    if call.get("macro") == "lane" and args:
                        lanes[args[0]] = tuple(args[1].split()) if len(args) > 1 else ()
                continue
            hit = TASK_PHASE_RE.fullmatch(name)
            if hit is None:
                continue
            title, line = str(phase.get("title", "")), int(phase.get("line") or 0)
            if not calls or calls[0].get("macro") != "route":
                tasks.append(Task(int(hit.group(1)), title, line))
                continue
            args = _args(calls[0])
            tasks.append(
                Task(
                    int(hit.group(1)),
                    title,
                    line,
                    routed=True,
                    work=args[0] if len(args) > 0 else "",
                    lane=args[1] if len(args) > 1 else "",
                    files=tuple(args[2].split()) if len(args) > 2 else (),
                )
            )
        return Plan(slug=slug, ref=ref, tasks=tuple(tasks), lanes=lanes, errors=errors)

Run: `uv run pytest -q tests/test_plan.py`

Expected: PASS — 14 Tests (die Parametrisierung zählt dreifach).

@call verify(lean_herdr/plan.py tests/test_plan.py)
@call py_gate(lean_herdr/plan.py tests/test_plan.py)
@call commit("lean_herdr/plan.py tests/test_plan.py", "feat(plan): read a plan off its branch and outline it with lean-md")
@phase-end

@phase "task-2"
## Task 2: `plan.py` — Regeln, Befunde am Branch, `load_plan`

**Files:** Modify `lean_herdr/plan.py`, `tests/test_plan.py`.

**Interfaces — Produces** (`lean_herdr/plan.py`):

    BRANCH_FILES: tuple[str, ...]   # was ein Worker im Worktree des Plan-Branches rendert
    TOOLING_DIRS = (".lean-ctx/lean-md/", ".lean-ctx/lean-herdr/briefs/")
    def rule_findings(plan: Plan, data: dict[str, Any]) -> tuple[list[Finding], list[Finding]]  # (errors, warnings)
    def branch_findings(root: Path, plan: Plan, *, runner=subprocess.run) -> list[Finding]
    def load_plan(root: Path, slug: str, data: dict[str, Any], *, ref: str | None = None, runner=subprocess.run) -> Plan

Befunde (Nachricht wörtlich; `line`/`phase` wie in der Spalte):

| `kind` | Nachricht | line, phase |
|---|---|---|
| `task_order` | `task-<n> stands where task-<i> belongs` | Task-Zeile, `task-<n>` |
| `no_route` | `task-<n> does not start with @call route(work, lane, files)` | Task-Zeile, `task-<n>` |
| `stage_as_work` | `task-<n>: '<work>' is a stage of a plan run, not a work` | Task-Zeile, `task-<n>` |
| `unknown_work` | `task-<n>: no role for work '<work>' in [routing]` | Task-Zeile, `task-<n>` |
| `unknown_lane` | `task-<n>: lane '<lane>' is not declared in the lanes phase` | Task-Zeile, `task-<n>` |
| `no_files` | `task-<n>: route names no files` | Task-Zeile, `task-<n>` |
| `unknown_lane` | `lane '<lane>' depends on undeclared lane '<dep>'` | 0, `lanes` |
| `lane_cycle` | `lane '<lane>' depends on itself` | 0, `lanes` |
| `order_vs_deps` | `task-<n> (lane '<lane>') comes before a task of lane '<dep>' it depends on` | Task-Zeile, `task-<n>` |
| Warnung `lane_overlap` | `<datei> is touched by lanes '<a>' and '<b>', and neither depends on the other` | 0, — |
| `missing_on_branch` | `<ref> carries no <datei> -- commit the output of `lean-herdr workspace init` on main` | 0, — |
| `branch_touches_tooling` | `<ref> changes <datei>; plan branches leave the tooling to main` | 0, — |

Ein Plan, der von `main` gelesen wurde, bekommt keine Befunde am Branch. `load_plan` sortiert die
Fehler nach `(line, kind)`. Befunde ohne Phase (`missing_on_branch`, `branch_touches_tooling`,
`lane_overlap`) tragen keinen Schlüssel `phase` — wie `lean-md outline` (TP0-Spec §4).

### Schritt 1 — Tests zuerst

In `tests/test_plan.py` den Import aus `lean_herdr.plan` ersetzen durch:

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

Am Dateiende:

    def plan_of(*tasks, lanes=None, ref="plan/shop"):
        return Plan(slug=SLUG, ref=ref, tasks=tuple(tasks), lanes=lanes if lanes is not None else {"core": ()})


    def routed(number, work="implement", lane="core", files=("a.py",)):
        return Task(number, f"Task {number}", number * 10, routed=True, work=work, lane=lane, files=tuple(files))


    def test_a_clean_plan_has_no_findings():
        assert rule_findings(plan_of(routed(1), routed(2)), {}) == ([], [])


    @pytest.mark.parametrize(
        ("plan", "expected"),
        [
            (plan_of(routed(2)), [Finding("task_order", "task-2 stands where task-1 belongs", 20, "task-2")]),
            (
                plan_of(Task(1, "T", 10)),
                [Finding("no_route", "task-1 does not start with @call route(work, lane, files)", 10, "task-1")],
            ),
            (
                plan_of(routed(1, work="plan")),
                [Finding("stage_as_work", "task-1: 'plan' is a stage of a plan run, not a work", 10, "task-1")],
            ),
            (
                plan_of(routed(1, work="deploy")),
                [Finding("unknown_work", "task-1: no role for work 'deploy' in [routing]", 10, "task-1")],
            ),
            (
                plan_of(routed(1, lane="api")),
                [Finding("unknown_lane", "task-1: lane 'api' is not declared in the lanes phase", 10, "task-1")],
            ),
            (plan_of(routed(1, files=())), [Finding("no_files", "task-1: route names no files", 10, "task-1")]),
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
                plan_of(routed(1, lane="api"), routed(2, lane="core"), lanes={"core": (), "api": ("core",)}),
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
        ids=["order", "route", "stage", "work", "lane", "files", "dep", "cycle", "deps"],
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
            [Finding("lane_overlap", "app/x.py is touched by lanes 'api' and 'core', and neither depends on the other")],
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
        proc = FakeProc(replies={("diff", "--name-only"): Completed(stdout=".lean-ctx/lean-md/herdr-recipes.lmd.md\n")})
        assert branch_findings(ROOT, plan_of(routed(1)), runner=proc) == [
            Finding(
                "branch_touches_tooling",
                "plan/shop changes .lean-ctx/lean-md/herdr-recipes.lmd.md; plan branches leave the tooling to main",
            )
        ]
        assert proc.called_with(
            "git", "diff", "--name-only", "main...plan/shop", "--", ".lean-ctx/lean-md/", ".lean-ctx/lean-herdr/briefs/"
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

Run: `uv run pytest -q tests/test_plan.py`

Expected: FAIL — `ImportError: cannot import name 'BRANCH_FILES'`.

### Schritt 2 — Implementierung

@call patch("lean_herdr/plan.py", "the import block, the line after OUTLINE_TIMEOUT_S, and the end of the file")

- Import-Block: `from dataclasses import dataclass, field` → `from dataclasses import dataclass, field, replace`;
  nach `from typing import Any`:

      from lean_herdr.settings import STAGES, SettingsError, role_for_work

- Nach `OUTLINE_TIMEOUT_S = 30.0`:

      #: What a worker renders or reads inside the plan branch's worktree (spec section 4).
      #: Role prompts and `bin/` are read from the repository root by `dispatch`, not from here.
      BRANCH_FILES = (
          ".lean-ctx/lean-md.lock",
          ".lean-ctx/lean-md/plan-recipes.lmd.md",
          ".lean-ctx/lean-md/herdr-recipes.lmd.md",
          ".lean-ctx/lean-md/herdr-plan-template.lmd.md",
          ".lean-ctx/lean-md/lang/python.lmd.md",
          ".lean-ctx/lean-herdr/briefs/implement.lmd.md",
          ".lean-ctx/lean-herdr/briefs/review.lmd.md",
          ".lean-ctx/lean-herdr/briefs/plan.lmd.md",
          ".lean-ctx/lean-herdr/briefs/plan-review.lmd.md",
          ".claude/skills/lmd-writing-plans/SKILL.md",
          ".claude/skills/lmd-rendering-skills/SKILL.md",
      )

      #: A plan branch leaves these alone: `plan check` resolves them against the repository
      #: root, a worker against the worktree, and both must read the same files.
      TOOLING_DIRS = (".lean-ctx/lean-md/", ".lean-ctx/lean-herdr/briefs/")

- Am Dateiende:

      def _reach(lanes: dict[str, tuple[str, ...]]) -> dict[str, set[str]]:
          """Every declared lane each lane depends on, directly or through another one."""
          reach: dict[str, set[str]] = {}
          for lane, deps in lanes.items():
              seen: set[str] = set()
              stack = list(deps)
              while stack:
                  dep = stack.pop()
                  if dep in seen or dep not in lanes:
                      continue
                  seen.add(dep)
                  stack.extend(lanes[dep])
              reach[lane] = seen
          return reach


      def rule_findings(plan: Plan, data: dict[str, Any]) -> tuple[list[Finding], list[Finding]]:
          """The rules of spec section 3 that need no git: `(errors, warnings)`."""
          errors: list[Finding] = []
          warnings: list[Finding] = []
          for index, task in enumerate(plan.tasks, start=1):
              phase = f"task-{task.number}"
              if task.number != index:
                  errors.append(Finding("task_order", f"{phase} stands where task-{index} belongs", task.line, phase))
              if not task.routed:
                  errors.append(
                      Finding("no_route", f"{phase} does not start with @call route(work, lane, files)", task.line, phase)
                  )
                  continue
              if task.work in STAGES:
                  errors.append(
                      Finding("stage_as_work", f"{phase}: {task.work!r} is a stage of a plan run, not a work", task.line, phase)
                  )
              else:
                  try:
                      role_for_work(task.work, data)
                  except SettingsError:
                      errors.append(
                          Finding("unknown_work", f"{phase}: no role for work {task.work!r} in [routing]", task.line, phase)
                      )
              if task.lane not in plan.lanes:
                  errors.append(
                      Finding(
                          "unknown_lane", f"{phase}: lane {task.lane!r} is not declared in the lanes phase", task.line, phase
                      )
                  )
              if not task.files:
                  errors.append(Finding("no_files", f"{phase}: route names no files", task.line, phase))
          for lane, deps in sorted(plan.lanes.items()):
              for dep in deps:
                  if dep not in plan.lanes:
                      errors.append(Finding("unknown_lane", f"lane {lane!r} depends on undeclared lane {dep!r}", 0, "lanes"))
          reach = _reach(plan.lanes)
          for lane in sorted(plan.lanes):
              if lane in reach[lane]:
                  errors.append(Finding("lane_cycle", f"lane {lane!r} depends on itself", 0, "lanes"))
          for position, task in enumerate(plan.tasks):
              later = {other.lane for other in plan.tasks[position + 1 :]}
              blocking = sorted(later & reach.get(task.lane, set()))
              if task.routed and blocking:
                  errors.append(
                      Finding(
                          "order_vs_deps",
                          f"task-{task.number} (lane {task.lane!r}) comes before a task of lane {blocking[0]!r} it depends on",
                          task.line,
                          f"task-{task.number}",
                      )
                  )
          owners: dict[str, set[str]] = {}
          for task in plan.tasks:
              for path in task.files:
                  owners.setdefault(path, set()).add(task.lane)
          for path, lanes in sorted(owners.items()):
              ordered = sorted(lanes)
              unrelated = [
                  (a, b)
                  for i, a in enumerate(ordered)
                  for b in ordered[i + 1 :]
                  if b not in reach.get(a, set()) and a not in reach.get(b, set())
              ]
              if unrelated:
                  a, b = unrelated[0]
                  warnings.append(
                      Finding("lane_overlap", f"{path} is touched by lanes {a!r} and {b!r}, and neither depends on the other")
                  )
          return errors, warnings


      def branch_findings(root: Path, plan: Plan, *, runner: Any = subprocess.run) -> list[Finding]:
          """What the plan branch lacks or changes that its workers need unchanged from main."""
          if plan.ref == "main":
              return []
          errors: list[Finding] = []
          for path in BRANCH_FILES:
              proc = run_git(root, "cat-file", "-e", f"{plan.ref}:{path}", runner=runner)
              if proc is None or proc.returncode != 0:
                  errors.append(
                      Finding(
                          "missing_on_branch",
                          f"{plan.ref} carries no {path} -- commit the output of `lean-herdr workspace init` on main",
                      )
                  )
          proc = run_git(root, "diff", "--name-only", f"main...{plan.ref}", "--", *TOOLING_DIRS, runner=runner)
          changed = proc.stdout.split() if proc is not None and proc.returncode == 0 else []
          for path in changed:
              errors.append(
                  Finding("branch_touches_tooling", f"{plan.ref} changes {path}; plan branches leave the tooling to main")
              )
          return errors


      def load_plan(
          root: Path,
          slug: str,
          data: dict[str, Any],
          *,
          ref: str | None = None,
          runner: Any = subprocess.run,
      ) -> Plan:
          """Read, outline and check one plan. Raises PlanError when it cannot be read at all."""
          found, text = read_source(root, slug, ref=ref, runner=runner)
          plan = structure(slug, found, outline(root, text, runner=runner))
          errors, warnings = rule_findings(plan, data)
          errors += branch_findings(root, plan, runner=runner)
          ordered = sorted([*plan.errors, *errors], key=lambda finding: (finding.line, finding.kind))
          return replace(plan, errors=tuple(ordered), warnings=tuple(warnings))

Run: `uv run pytest -q tests/test_plan.py`

Expected: PASS — alle Tests in `tests/test_plan.py`.

@call verify(lean_herdr/plan.py tests/test_plan.py)
@call py_gate(lean_herdr/plan.py tests/test_plan.py)
@call commit("lean_herdr/plan.py tests/test_plan.py", "feat(plan): check a plan's tasks, lanes and branch against the rules")
@phase-end

@phase "task-3"
## Task 3: `planrun.py` — der nächste Schritt

**Files:** Create `lean_herdr/planrun.py`, `tests/test_planrun.py`.

**Interfaces — Produces** (`lean_herdr/planrun.py`):

    TRACKED_CHANGES = ("staged", "modified", "deleted", "renamed", "conflicted")
    def next_step(plan: Plan | None, orders: Sequence[Order], *,
                  checks: Mapping[str, Sequence[dict[str, Any]]], merged: bool) -> dict[str, Any]
    def task_summary(plan: Plan, orders: Sequence[Order]) -> list[dict[str, Any]]

`orders`: die Aufträge dieses Plans, älteste zuerst. `checks`: Auftrags-ID eines erledigten
Plan-Auftrags → Fehler von `plan check` am `head` seines `report done` (leer = sauber).

Reihenfolge der Entscheidung (Spec §6.4):

1. `merged` → `{"done": True}`
2. offener Auftrag (neuester) → `{"step": "await", "work", "task_id", "task", "round"}`
3. Planung: kein Plan-Auftrag → `plan` Runde 1; letzter Plan-Auftrag `failed`/`canceled` →
   `escalate`; Check-Fehler → `plan` mit `reason: check` bzw. zweimal in Folge
   `escalate check×2`; kein Plan-Review danach → `plan-review`; Plan-Review `reject` → `plan`
   bzw. zweimal `escalate plan-review reject×2`; `result` → weiter
4. kein `Plan` → `{"escalate": True, "reason": "no_plan"}`
5. je Task: Zyklus `implement` → `review` (siehe Tabelle unten)
6. Zyklus `branch`: beginnt mit `review`; `result` → `{"step": "merge"}`

Zyklus einer Task (`task` = Zahl, bzw. `"branch"`), letzter Auftrag der Gruppe:

| Lage | Antwort |
|---|---|
| keine Aufträge | Task: `implement` Runde 1 · Branch: `{"step": "review", "task": "branch", "work": "review"}` |
| `failed` / `canceled` | `escalate agent_error` / `canceled`, mit `task_id`, `task` |
| `implement` erledigt, getrackte Änderungen | `implement` mit `reason: uncommitted`, Runde n+1; zwei solche seit dem letzten Review → `escalate uncommitted×2` |
| `implement` erledigt, sauber oder unbekannt | `review` mit `after` |
| `review` `result` | Zyklus fertig |
| `review` `reject` oder ohne Urteil | `implement` Runde n+1 mit `after`; zwei Ablehnungen → `escalate review reject×2` |

### Schritt 1 — Tests zuerst

`tests/test_planrun.py`:

    import pytest

    from lean_herdr.orders import Order
    from lean_herdr.plan import Plan, Task
    from lean_herdr.planrun import next_step, task_summary

    WORKER = "worker"
    PLAN = Plan(
        slug="shop",
        ref="plan/shop",
        tasks=(
            Task(1, "Task 1: models", 10, routed=True, work="implement", lane="core", files=("a.py",)),
            Task(2, "Task 2: api", 20, routed=True, work="implement-small", lane="core", files=("b.py",)),
        ),
        lanes={"core": ()},
    )
    ERR = [{"kind": "no_route", "line": 10, "phase": "task-1", "message": "task-1 does not start with @call route(work, lane, files)"}]


    def o(order_id, step, *, task=None, state="completed", verdict=None, changes=()):
        return Order(
            id=order_id,
            from_agent="orch",
            to_agent=WORKER,
            state=state,
            plan="shop",
            step=step,
            plan_task=task,
            messages=((WORKER, f"VERDIKT: {verdict}\nbecause"),) if verdict else (),
            done_changes=tuple(changes) if state == "completed" else None,
        )


    PLANNED = [o("p1", "plan"), o("r1", "plan-review", verdict="result")]
    TASKS_DONE = [
        *PLANNED,
        o("i1", "implement", task="1"),
        o("v1", "review", task="1", verdict="result"),
        o("i2", "implement", task="2"),
        o("v2", "review", task="2", verdict="result"),
    ]
    UNKNOWN = Order(id="i1", to_agent=WORKER, state="completed", plan="shop", step="implement", plan_task="1")


    @pytest.mark.parametrize(
        ("orders", "checks", "expected"),
        [
            ([], {}, {"step": "plan", "work": "plan", "round": 1}),
            (
                [o("p1", "plan", state="working")],
                {},
                {"step": "await", "work": "plan", "task_id": "p1", "task": None, "round": 1},
            ),
            ([o("p1", "plan", state="failed")], {}, {"escalate": True, "reason": "agent_error", "task_id": "p1"}),
            ([o("p1", "plan", state="canceled")], {}, {"escalate": True, "reason": "canceled", "task_id": "p1"}),
            (
                [o("p1", "plan")],
                {"p1": ERR},
                {"step": "plan", "work": "plan", "reason": "check", "errors": ERR, "round": 2, "after": "p1"},
            ),
            (
                [o("p1", "plan"), o("p2", "plan")],
                {"p1": ERR, "p2": ERR},
                {"escalate": True, "reason": "check×2", "task_id": "p2"},
            ),
            ([o("p1", "plan")], {}, {"step": "plan-review", "work": "plan-review"}),
            (
                [o("p1", "plan"), o("r1", "plan-review", verdict="reject")],
                {},
                {"step": "plan", "work": "plan", "round": 2, "after": "r1"},
            ),
            (
                [
                    o("p1", "plan"),
                    o("r1", "plan-review", verdict="reject"),
                    o("p2", "plan"),
                    o("r2", "plan-review", verdict="reject"),
                ],
                {},
                {"escalate": True, "reason": "plan-review reject×2", "task_id": "r2"},
            ),
            (PLANNED, {}, {"step": "implement", "task": 1, "work": "implement", "round": 1}),
            (
                [*PLANNED, o("i1", "implement", task="1", changes=["modified"])],
                {},
                {"step": "implement", "task": 1, "work": "implement", "reason": "uncommitted", "round": 2, "after": "i1"},
            ),
            (
                [
                    *PLANNED,
                    o("i1", "implement", task="1", changes=["modified"]),
                    o("i2", "implement", task="1", changes=["staged"]),
                ],
                {},
                {"escalate": True, "reason": "uncommitted×2", "task_id": "i2", "task": 1},
            ),
            (
                [*PLANNED, o("i1", "implement", task="1", changes=["untracked"])],
                {},
                {"step": "review", "task": 1, "work": "review", "after": "i1"},
            ),
            ([*PLANNED, UNKNOWN], {}, {"step": "review", "task": 1, "work": "review", "after": "i1"}),
            (
                [*PLANNED, o("i1", "implement", task="1"), o("v1", "review", task="1", verdict="reject")],
                {},
                {"step": "implement", "task": 1, "work": "implement", "round": 2, "after": "v1"},
            ),
            (
                [*PLANNED, o("i1", "implement", task="1"), o("v1", "review", task="1")],
                {},
                {"step": "implement", "task": 1, "work": "implement", "round": 2, "after": "v1"},
            ),
            (
                [
                    *PLANNED,
                    o("i1", "implement", task="1"),
                    o("v1", "review", task="1", verdict="reject"),
                    o("i2", "implement", task="1"),
                    o("v2", "review", task="1", verdict="reject"),
                ],
                {},
                {"escalate": True, "reason": "review reject×2", "task_id": "v2", "task": 1},
            ),
            (
                [*PLANNED, o("i1", "implement", task="1"), o("v1", "review", task="1", verdict="result")],
                {},
                {"step": "implement", "task": 2, "work": "implement-small", "round": 1},
            ),
            (
                [
                    *PLANNED,
                    o("i1", "implement", task="1"),
                    o("v1", "review", task="1", verdict="result"),
                    o("i2", "implement", task="2", state="created"),
                ],
                {},
                {"step": "await", "work": "implement-small", "task_id": "i2", "task": 2, "round": 1},
            ),
            ([*PLANNED, o("i1", "implement", task="1", state="failed")], {}, {"escalate": True, "reason": "agent_error", "task_id": "i1", "task": 1}),
            (TASKS_DONE, {}, {"step": "review", "task": "branch", "work": "review"}),
            (
                [*TASKS_DONE, o("b1", "review", task="branch", verdict="reject")],
                {},
                {"step": "implement", "task": "branch", "work": "implement", "round": 1, "after": "b1"},
            ),
            (
                [*TASKS_DONE, o("b1", "review", task="branch", verdict="reject"), o("b2", "implement", task="branch")],
                {},
                {"step": "review", "task": "branch", "work": "review", "after": "b2"},
            ),
            (
                [
                    *TASKS_DONE,
                    o("b1", "review", task="branch", verdict="reject"),
                    o("b2", "implement", task="branch"),
                    o("b3", "review", task="branch", verdict="reject"),
                ],
                {},
                {"escalate": True, "reason": "review reject×2", "task_id": "b3", "task": "branch"},
            ),
            (
                [
                    *TASKS_DONE,
                    o("b1", "review", task="branch", verdict="reject"),
                    o("b2", "implement", task="branch", changes=["modified"]),
                ],
                {},
                {"step": "implement", "task": "branch", "work": "implement", "reason": "uncommitted", "round": 2, "after": "b2"},
            ),
            (
                [*PLANNED, o("i1", "implement", task="1", state="canceled")],
                {},
                {"escalate": True, "reason": "canceled", "task_id": "i1", "task": 1},
            ),
            ([*TASKS_DONE, o("b1", "review", task="branch", verdict="result")], {}, {"step": "merge"}),
        ],
        ids=[
            "fresh", "await-plan", "plan-failed", "plan-canceled", "check", "check-twice", "plan-review",
            "plan-review-reject", "plan-review-reject-twice", "first-task", "uncommitted", "uncommitted-twice",
            "untracked-only", "changes-unknown", "review-reject", "review-no-verdict", "review-reject-twice",
            "next-task", "await-task", "implement-failed", "branch-review", "branch-reject", "branch-fixed",
            "branch-reject-twice", "branch-uncommitted", "implement-canceled", "merge",
        ],
    )
    def test_next_step(orders, checks, expected):
        assert next_step(PLAN, orders, checks=checks, merged=False) == expected


    def test_a_merged_plan_is_done_whatever_the_log_says():
        assert next_step(PLAN, [o("p1", "plan", state="working")], checks={}, merged=True) == {"done": True}


    def test_without_a_plan_on_the_branch_the_run_cannot_go_on():
        assert next_step(None, PLANNED, checks={}, merged=False) == {"escalate": True, "reason": "no_plan"}


    def test_the_summary_names_each_tasks_state_rounds_and_orders():
        orders = [
            *PLANNED,
            o("i1", "implement", task="1"),
            o("v1", "review", task="1", verdict="result"),
            o("i2", "implement", task="2", state="working"),
        ]
        rows = task_summary(PLAN, orders)
        assert [(r["task"], r["state"], r["rounds"], r["orders"]) for r in rows] == [
            (1, "done", 1, ["i1", "v1"]),
            (2, "working", 1, ["i2"]),
        ]
        assert rows[1]["title"] == "Task 2: api"
        assert rows[1]["work"] == "implement-small"
        assert rows[1]["lane"] == "core"
        assert rows[1]["files"] == ["b.py"]
        assert task_summary(PLAN, PLANNED)[0]["state"] == "pending"

Run: `uv run pytest -q tests/test_planrun.py`

Expected: FAIL — `ModuleNotFoundError: No module named 'lean_herdr.planrun'`.

### Schritt 2 — Implementierung

`lean_herdr/planrun.py`:

    """What a plan run does next -- a pure function of the plan, its orders and the checks.

    No file, no process, no clock: `plancmd` reads the log and runs the checks, this module
    only decides (spec section 6.4). The orchestrator counts nothing itself.
    """

    from __future__ import annotations

    from collections.abc import Mapping, Sequence
    from typing import Any

    from lean_herdr.dispatch import verdict
    from lean_herdr.orders import PLAN_TASK_RE, Order, message_from
    from lean_herdr.plan import Plan

    #: `worktree.changes` flags that mean work was left uncommitted. `untracked` is not one:
    #: a builder leaves the files it did not name untracked on purpose (builder.md).
    TRACKED_CHANGES = ("staged", "modified", "deleted", "renamed", "conflicted")


    def _ruling(order: Order) -> str:
        """`result` or `reject`. A missing or unreadable verdict counts as `reject`."""
        return "result" if verdict(message_from(order, order.to_agent)) == "result" else "reject"


    def _dirty(order: Order) -> bool:
        return order.done_changes is not None and any(flag in TRACKED_CHANGES for flag in order.done_changes)


    def _label(plan_task: str | None) -> int | str | None:
        return int(plan_task) if plan_task is not None and PLAN_TASK_RE.fullmatch(plan_task) else plan_task


    def _stopped(order: Order) -> dict[str, Any] | None:
        if order.state == "failed":
            return {"escalate": True, "reason": "agent_error", "task_id": order.id}
        if order.state == "canceled":
            return {"escalate": True, "reason": "canceled", "task_id": order.id}
        return None


    def _work(plan: Plan | None, order: Order) -> str:
        """The `--work` a dispatch for this order uses: a task's own work, else the step."""
        if order.step == "implement" and plan is not None and order.plan_task and PLAN_TASK_RE.fullmatch(order.plan_task):
            task = next((t for t in plan.tasks if t.number == int(order.plan_task)), None)
            if task is not None:
                return task.work
        return order.step or ""


    def _round(orders: Sequence[Order], order: Order) -> int:
        same = [o for o in orders if o.step == order.step and o.plan_task == order.plan_task]
        return same.index(order) + 1


    def _planning(orders: Sequence[Order], checks: Mapping[str, Sequence[dict[str, Any]]]) -> dict[str, Any] | None:
        """The plan and its review. None once the review said `result`."""
        plans = [o for o in orders if o.step == "plan"]
        if not plans:
            return {"step": "plan", "work": "plan", "round": 1}
        last = plans[-1]
        stopped = _stopped(last)
        if stopped is not None:
            return stopped
        errors = list(checks.get(last.id, ()))
        if errors:
            if len(plans) >= 2 and checks.get(plans[-2].id):
                return {"escalate": True, "reason": "check×2", "task_id": last.id}
            return {
                "step": "plan",
                "work": "plan",
                "reason": "check",
                "errors": errors,
                "round": len(plans) + 1,
                "after": last.id,
            }
        after_last = orders[orders.index(last) + 1 :]
        reviews = [o for o in after_last if o.step == "plan-review"]
        if not reviews:
            return {"step": "plan-review", "work": "plan-review"}
        review = reviews[-1]
        stopped = _stopped(review)
        if stopped is not None:
            return stopped
        if _ruling(review) == "result":
            return None
        rejects = [o for o in orders if o.step == "plan-review" and o.state == "completed" and _ruling(o) == "reject"]
        if len(rejects) >= 2:
            return {"escalate": True, "reason": "plan-review reject×2", "task_id": review.id}
        return {"step": "plan", "work": "plan", "round": len(plans) + 1, "after": review.id}


    def _cycle(orders: Sequence[Order], task: str, work: str) -> dict[str, Any] | None:
        """One task's implement/review loop -- or the branch's. None once its review said `result`."""
        group = [o for o in orders if o.plan_task == task and o.step in ("implement", "review")]
        implements = [o for o in group if o.step == "implement"]
        label = _label(task)
        if not group:
            if task == "branch":
                return {"step": "review", "task": label, "work": "review"}
            return {"step": "implement", "task": label, "work": work, "round": 1}
        last = group[-1]
        stopped = _stopped(last)
        if stopped is not None:
            return {**stopped, "task": label}
        if last.step == "implement":
            if not _dirty(last):
                return {"step": "review", "task": label, "work": "review", "after": last.id}
            since_review: list[Order] = []
            for order in reversed(group):
                if order.step == "review":
                    break
                since_review.append(order)
            if len(since_review) >= 2 and _dirty(since_review[1]):
                return {"escalate": True, "reason": "uncommitted×2", "task_id": last.id, "task": label}
            return {
                "step": "implement",
                "task": label,
                "work": work,
                "reason": "uncommitted",
                "round": len(implements) + 1,
                "after": last.id,
            }
        if _ruling(last) == "result":
            return None
        rejects = [o for o in group if o.step == "review" and o.state == "completed" and _ruling(o) == "reject"]
        if len(rejects) >= 2:
            return {"escalate": True, "reason": "review reject×2", "task_id": last.id, "task": label}
        return {"step": "implement", "task": label, "work": work, "round": len(implements) + 1, "after": last.id}


    def next_step(
        plan: Plan | None,
        orders: Sequence[Order],
        *,
        checks: Mapping[str, Sequence[dict[str, Any]]],
        merged: bool,
    ) -> dict[str, Any]:
        """The next move of a plan run (spec section 6.4).

        `orders` are this plan's orders, oldest first. `checks` maps a completed plan order's
        id to the `plan check` errors at its `report done` head; an empty list is a clean plan.
        """
        if merged:
            return {"done": True}
        waiting = [o for o in orders if o.is_open]
        if waiting:
            order = waiting[-1]
            return {
                "step": "await",
                "work": _work(plan, order),
                "task_id": order.id,
                "task": _label(order.plan_task),
                "round": _round(orders, order),
            }
        answer = _planning(orders, checks)
        if answer is not None:
            return answer
        if plan is None:
            return {"escalate": True, "reason": "no_plan"}
        for task in plan.tasks:
            answer = _cycle(orders, str(task.number), task.work)
            if answer is not None:
                return answer
        answer = _cycle(orders, "branch", "implement")
        return answer if answer is not None else {"step": "merge"}


    def task_summary(plan: Plan, orders: Sequence[Order]) -> list[dict[str, Any]]:
        """One row per task for `plan show`: its route, rounds, orders and state."""
        rows: list[dict[str, Any]] = []
        for task in plan.tasks:
            key = str(task.number)
            group = [o for o in orders if o.plan_task == key and o.step in ("implement", "review")]
            if not group:
                state = "pending"
            elif any(o.is_open for o in group):
                state = "working"
            else:
                answer = _cycle(orders, key, task.work)
                state = "done" if answer is None else "escalated" if answer.get("escalate") else str(answer["step"])
            rows.append(
                {
                    "task": task.number,
                    "title": task.title,
                    "work": task.work,
                    "lane": task.lane,
                    "files": list(task.files),
                    "rounds": sum(1 for o in group if o.step == "implement"),
                    "orders": [o.id for o in group],
                    "state": state,
                }
            )
        return rows

Run: `uv run pytest -q tests/test_planrun.py`

Expected: PASS — `test_next_step` (27 Fälle) und die drei weiteren Tests.

@call verify(lean_herdr/planrun.py tests/test_planrun.py)
@call review_change()
@call py_gate(lean_herdr/planrun.py tests/test_planrun.py)
@call commit("lean_herdr/planrun.py tests/test_planrun.py", "feat(planrun): decide a plan run's next step from its plan, orders and checks")
@phase-end

@phase "task-4"
## Task 4: `plancmd.py` — `check`, `next`, `show`; Verb `plan`

**Files:** Create `lean_herdr/plancmd.py`, `tests/test_plancmd.py`. Modify `lean_herdr/cli.py`.

**Interfaces — Produces** (`lean_herdr/plancmd.py`):

    SUBCOMMANDS = ("check", "next", "show")
    def plan_orders(slug: str, *, orders_dir: str | Path) -> list[Order]        # älteste zuerst
    def check_result(root: Path, slug: str, data: dict, *, runner=subprocess.run) -> dict
    def next_result(root: Path, slug: str, data: dict, *, orders_dir, runner=subprocess.run) -> dict
    def show_result(root: Path, slug: str, data: dict, *, orders_dir, runner=subprocess.run) -> dict
    def build_parser() -> argparse.ArgumentParser
    def missing_flags(args: argparse.Namespace) -> str | None
    def main(argv: list[str] | None = None) -> int                              # eine JSON-Zeile, Exit 0

Ausgaben (Spec §6.2, §9):

| Befehl | `ok` | Inhalt |
|---|---|---|
| `check <slug>` | keine `errors` | `slug`, `ref`, `errors[]`, `warnings[]`; ohne Plan `{ok: false, error: "no_plan: …"}` |
| `next <slug>` | immer, außer `config_error` | Antwort von `planrun.next_step`; `merged` = `main` trägt die Plan-Datei |
| `show <slug>` | Plan lesbar | `slug`, `ref`, `planning[]` (`task_id`, `step`, `state`), `tasks[]` aus `task_summary`, `errors[]`, `warnings[]` |

`next` prüft jeden erledigten `plan`-Auftrag am `head` seines `report done` (ohne Stempel: am
Branch-Kopf); trägt dieser Stand keinen Plan, ist das der Befund `no_plan`. `config_error` beendet
`next` mit `ok: false`. Fehler von `main`: `usage_error: …`, `config_error: …` (Settings),
`plan_crashed: …`.

### Schritt 1 — Tests zuerst

`tests/test_plancmd.py`:

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
            _phase("task-1", "Task 1: models", 15, _call("route", 16, "implement", "core", "app/models.py")),
            _phase("task-2", "Task 2: api", 30, _call("route", 31, "implement", "core", "app/main.py")),
        ],
        "macros": {},
        "errors": [],
    }
    UNKNOWN_MACRO = {"kind": "unknown_macro", "line": 40, "phase": "task-2", "message": "macro not found: gate"}
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

        def __init__(self, files=None, outlines=None, *, log="", status="", merge_base="", broken_render=None):
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
                return Completed(stdout=text) if text is not None else Completed(returncode=128, stderr="fatal: bad object")
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


    def order(orders, task_id, step, *, task=None, spec=None, after=None, start=None, done=None, message="", plan=SLUG):
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
            append(task_id, "completed", WORKER, {"message": message, "head": done, "changes": []}, orders=orders)


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
        order(tmp_path, "o-1", "plan", spec="docs/specs/shop-design.md", done="h1")
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
        order(tmp_path, "o-1", "plan", spec="docs/specs/shop-design.md", done="h1")
        repo = Repo({f"main:{PLAN_FILE}": "clean"}, {"clean": CLEAN})
        assert next_result(ROOT, SLUG, {}, orders_dir=tmp_path, runner=repo) == {"ok": True, "done": True}


    def test_next_checks_a_plan_order_at_the_head_it_reported_done_on(tmp_path):
        order(tmp_path, "o-1", "plan", spec="docs/specs/shop-design.md", done="h1")
        repo = Repo(
            {f"h1:{PLAN_FILE}": "broken", f"plan/shop:{PLAN_FILE}": "clean"},
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
        assert (["git", "show", f"h1:{PLAN_FILE}"], "/repo") in repo.calls


    def test_next_hands_a_clean_plan_to_the_plan_review(tmp_path):
        order(tmp_path, "o-1", "plan", spec="docs/specs/shop-design.md", done="h1")
        repo = Repo({f"h1:{PLAN_FILE}": "clean", f"plan/shop:{PLAN_FILE}": "clean"}, {"clean": CLEAN})
        assert next_result(ROOT, SLUG, {}, orders_dir=tmp_path, runner=repo) == {
            "ok": True,
            "step": "plan-review",
            "work": "plan-review",
        }


    def test_next_without_lean_md_outline_is_a_config_error(tmp_path):
        order(tmp_path, "o-1", "plan", spec="docs/specs/shop-design.md", done="h1")
        repo = Repo({f"h1:{PLAN_FILE}": "clean"})
        assert next_result(ROOT, SLUG, {}, orders_dir=tmp_path, runner=repo) == {
            "ok": False,
            "error": "config_error: lean-md outline unavailable (needs lean-md >= 0.2.4)",
        }


    def test_show_lists_the_planning_orders_and_every_task(tmp_path):
        order(tmp_path, "o-1", "plan", spec="docs/specs/shop-design.md", done="h1")
        order(tmp_path, "o-2", "plan-review", done="h1", message="VERDIKT: result\nfine")
        order(tmp_path, "o-3", "implement", task="1", start="h1")
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
            (["check", "Shop"], "usage_error: 'Shop' is no plan slug ([a-z][a-z0-9-]{0,11})"),
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

Run: `uv run pytest -q tests/test_plancmd.py`

Expected: FAIL — `ImportError: cannot import name 'plancmd' from 'lean_herdr'` beim Sammeln.

### Schritt 2 — `plancmd.py`

`lean_herdr/plancmd.py`:

    """`lean-herdr plan check | next | show` -- a plan run as the orchestrator sees it.

    One JSON line with `ok`, exit ALWAYS 0, like `dispatch` and `report`: the orchestrator reads
    `ok`, not the exit code. What comes next is `planrun`'s decision; this module reads the log,
    runs `plan check` where `planrun` needs its result, and prints.
    """

    from __future__ import annotations

    import argparse
    import json
    import subprocess
    import sys
    from pathlib import Path
    from typing import Any

    from lean_herdr.bus import BusError, canonical_root
    from lean_herdr.dispatch import UsageError, _Parser
    from lean_herdr.orderlog import OrderLogError, read_events, state_dir, task_ids
    from lean_herdr.orders import PLAN_SLUG_RE, Order, fold
    from lean_herdr.plan import Plan, PlanError, load_plan, plan_path, show
    from lean_herdr.planrun import next_step, task_summary
    from lean_herdr.settings import SETTINGS_PATH, SettingsError, read_settings, work_roles

    SUBCOMMANDS = ("check", "next", "show")


    def plan_orders(slug: str, *, orders_dir: str | Path) -> list[Order]:
        """This plan's orders, oldest first -- `task_ids` lists the log newest first."""
        folded = (fold(read_events(task_id, orders=orders_dir)) for task_id in reversed(task_ids(orders=orders_dir)))
        return [order for order in folded if order.plan == slug]


    def _findings(plan: Plan) -> dict[str, Any]:
        return {
            "errors": [finding.as_json() for finding in plan.errors],
            "warnings": [finding.as_json() for finding in plan.warnings],
        }


    def check_result(root: Path, slug: str, data: dict[str, Any], *, runner: Any = subprocess.run) -> dict[str, Any]:
        """`plan check`: the committed plan against lean-md and spec section 3. Warnings never cost `ok`."""
        try:
            plan = load_plan(root, slug, data, runner=runner)
        except PlanError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": not plan.errors, "slug": slug, "ref": plan.ref, **_findings(plan)}


    def _checks(
        root: Path, slug: str, data: dict[str, Any], orders: list[Order], *, runner: Any
    ) -> dict[str, list[dict[str, Any]]]:
        """The errors of `plan check` at the head each completed plan order reported done on.

        Without a stamped head the branch tip stands in. A head that carries no plan is a
        finding of its own; any other PlanError -- lean-md without `outline` -- propagates.
        """
        checks: dict[str, list[dict[str, Any]]] = {}
        for order in orders:
            if order.step != "plan" or order.state != "completed":
                continue
            try:
                plan = load_plan(root, slug, data, ref=order.done_head, runner=runner)
            except PlanError as exc:
                if not str(exc).startswith("no_plan:"):
                    raise
                checks[order.id] = [{"kind": "no_plan", "line": 0, "message": str(exc)}]
                continue
            checks[order.id] = [finding.as_json() for finding in plan.errors]
        return checks


    def next_result(
        root: Path,
        slug: str,
        data: dict[str, Any],
        *,
        orders_dir: str | Path,
        runner: Any = subprocess.run,
    ) -> dict[str, Any]:
        """`plan next`: one step for the orchestrator (spec section 6.4)."""
        orders = plan_orders(slug, orders_dir=orders_dir)
        if show(root, "main", plan_path(slug), runner=runner) is not None:
            return {"ok": True, **next_step(None, orders, checks={}, merged=True)}
        try:
            checks = _checks(root, slug, data, orders, runner=runner)
        except PlanError as exc:
            return {"ok": False, "error": str(exc)}
        plan: Plan | None
        try:
            plan = load_plan(root, slug, data, runner=runner)
        except PlanError as exc:
            if not str(exc).startswith("no_plan:"):
                return {"ok": False, "error": str(exc)}
            plan = None
        return {"ok": True, **next_step(plan, orders, checks=checks, merged=False)}


    def show_result(
        root: Path,
        slug: str,
        data: dict[str, Any],
        *,
        orders_dir: str | Path,
        runner: Any = subprocess.run,
    ) -> dict[str, Any]:
        """`plan show`: the plan's tasks with state, rounds and orders -- for the orchestrator and a human."""
        try:
            plan = load_plan(root, slug, data, runner=runner)
        except PlanError as exc:
            return {"ok": False, "error": str(exc)}
        orders = plan_orders(slug, orders_dir=orders_dir)
        return {
            "ok": True,
            "slug": slug,
            "ref": plan.ref,
            "planning": [
                {"task_id": order.id, "step": order.step, "state": order.state}
                for order in orders
                if order.step in ("plan", "plan-review")
            ],
            "tasks": task_summary(plan, orders),
            **_findings(plan),
        }


    def build_parser() -> argparse.ArgumentParser:
        p = _Parser(prog="lean-herdr plan", description="Check a plan and steer its run.")
        p.add_argument("command", choices=SUBCOMMANDS)
        p.add_argument("slug", nargs="?", default=None, help="the plan: docs/lean-md/plans/<slug>.lmd.md on plan/<slug>")
        p.add_argument("--task", default=None, help="brief: the order id")
        return p


    def missing_flags(args: argparse.Namespace) -> str | None:
        if args.task is not None:
            return f"{args.command} does not take --task"
        if args.slug is None:
            return f"{args.command} needs a slug"
        if not PLAN_SLUG_RE.fullmatch(args.slug):
            return f"{args.slug!r} is no plan slug ({PLAN_SLUG_RE.pattern})"
        return None


    def _settings(root: Path) -> dict[str, Any]:
        """config.toml with `[routing]` validated: a broken table is `config_error`, not `unknown_work`."""
        data = read_settings(root / SETTINGS_PATH)
        work_roles(data)
        return data


    def _run(args: argparse.Namespace) -> dict[str, Any]:
        root = canonical_root()
        data = _settings(root)
        if args.command == "check":
            return check_result(root, args.slug, data)
        if args.command == "next":
            return next_result(root, args.slug, data, orders_dir=state_dir(root))
        return show_result(root, args.slug, data, orders_dir=state_dir(root))


    def main(argv: list[str] | None = None) -> int:
        """`check`, `next`, `show`: one JSON line on stdout, exit ALWAYS 0."""
        result: dict[str, Any]
        try:
            args = build_parser().parse_args(argv)
            complaint = missing_flags(args)
            result = {"ok": False, "error": f"usage_error: {complaint}"} if complaint else _run(args)
        except UsageError as exc:
            result = {"ok": False, "error": f"usage_error: {exc}"}
        except SettingsError as exc:
            result = {"ok": False, "error": f"config_error: {exc}"}
        except (OrderLogError, BusError) as exc:
            result = {"ok": False, "error": str(exc)}
        except Exception as exc:  # noqa: BLE001 -- never abort the caller
            result = {"ok": False, "error": f"plan_crashed: {exc}"}
        sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
        return 0

Run: `uv run pytest -q tests/test_plancmd.py`

Expected: PASS — alle Tests in `tests/test_plancmd.py`.

### Schritt 3 — Verb `plan` in `cli.py`

@call patch("lean_herdr/cli.py", "the first docstring line, the house-contract sentence, VERBS and USAGE")

- Erste Docstring-Zeile → `One binary, seven verbs: `lean-herdr dispatch | llm | models | plan | plugin | report | workspace`.`
- `Four keep the house\ncontract: one JSON line on stdout, `ok` as the only truth, exit ALWAYS 0. Two` →
  `Five keep the house\ncontract: one JSON line on stdout, `ok` as the only truth, exit ALWAYS 0. Two`
- In `VERBS` nach `"models": "lean_herdr.catalog",`: `"plan": "lean_herdr.plancmd",`
- `USAGE`: `{dispatch|llm|models|plugin|report|workspace}` → `{dispatch|llm|models|plan|plugin|report|workspace}`;
  `  dispatch, models, report, workspace: one JSON line on stdout, exit 0\n` →
  `  dispatch, models, plan, report, workspace: one JSON line on stdout, exit 0\n`

`PLAIN_VERBS` bleibt unverändert (Spec §6.2).

Run: `uv run pytest -q tests/test_cli.py`

Expected: PASS — `test_each_verb_reaches_its_own_main_with_the_rest[plan-lean_herdr.plancmd]` und
`test_every_verb_names_a_module_that_actually_imports` decken das neue Verb ab.

@call verify(lean_herdr/plancmd.py lean_herdr/cli.py tests/test_plancmd.py)
@call py_gate(lean_herdr/plancmd.py lean_herdr/cli.py tests/test_plancmd.py)
@call commit("lean_herdr/plancmd.py lean_herdr/cli.py tests/test_plancmd.py", "feat(plan): add lean-herdr plan check, next and show")
@phase-end

@phase "task-5"
## Task 5: `plancmd.py` — `plan brief`

**Files:** Modify `lean_herdr/plancmd.py`, `lean_herdr/report.py`, `lean_herdr/cli.py`, `tests/test_plancmd.py`.

**Interfaces — Produces:**

    # lean_herdr/report.py
    def order_text(order: Order, *, orders_dir: str | Path) -> str   # bisher _brief, unverändert
    # lean_herdr/plancmd.py
    SUBCOMMANDS = ("check", "next", "show", "brief")
    BRIEFS_DIR = Path(".lean-ctx") / "lean-herdr" / "briefs"
    class BriefError(Exception)
    def render(cwd: Path, path: str | Path, *, phase: str | None = None, runner=subprocess.run) -> str
    def compose_brief(order: Order, *, root: Path, cwd: Path, orders_dir, data: dict, runner=subprocess.run) -> str
    def brief_main(argv: list[str]) -> int     # Klartext + Exit 0, sonst eine stderr-Zeile + Exit 1

Inhalt je Schritt (Spec §6.5); Teile getrennt durch eine Leerzeile, jeder Brief endet mit
`## Order` und `report.order_text` — so trägt eine zweite Runde die Befunde, auf die sie antwortet:

| `step` | Teile vor `## Order` |
|---|---|
| implement, Task N | `briefs/implement` · `task-N` |
| implement, branch | `briefs/implement` · `constraints` |
| review, Task N | `briefs/review` · `constraints` · `task-N` · `## Diff` |
| review, branch | `briefs/review` · `constraints` · `## Tasks` · `## Diff` ohne Basis |
| plan | `briefs/plan` · `## Plan` (Pfad, Branch, Spec) · `## Works` |
| plan-review | `briefs/plan-review` · `## Plan` · `## plan check` |

`## Diff` einer Task: `wt step diff <sha>` mit dem `start_head` des **ersten** `implement`-Auftrags
der Task; fehlt er, der letzte `done_head` eines `implement` der Task davor, sonst
`git merge-base main HEAD` — der Ersatz steht in Klammern dahinter. Danach die Commits
(`git log --oneline <sha>..HEAD`) und die ungetrackten Dateien (`git status --porcelain
--untracked-files=all`, nur `??`). Ohne jede Basis: `no_base: task N has no start head, and no
merge base with main`. Gerendert wird im Arbeitsverzeichnis des Workers (`cwd`), `git show` und
`plan check` laufen in der Repo-Wurzel.

Fehlerzeilen auf stderr: `usage_error: …`, `task_not_found: o-…`, `order o-… belongs to no plan`,
`render_failed: <datei>[ --phase <p>]: <erste stderr-Zeile>`, `no_base: …`, `no_plan: …`,
`config_error: …`, `brief_crashed: …`.

### Schritt 1 — Tests zuerst

In `tests/test_plancmd.py` die Importe ersetzen:

- `from lean_herdr.orderlog import append` → `from lean_herdr.orderlog import append, read_events`
- nach dieser Zeile: `from lean_herdr.orders import fold`
- `from lean_herdr.plancmd import check_result, main, next_result, plan_orders, show_result` →
  `from lean_herdr.plancmd import BriefError, check_result, compose_brief, main, next_result, plan_orders, show_result`

Am Dateiende:

    WT = Path("/wt/shop")


    def brief(orders, task_id, repo, *, data=None):
        order_ = fold(read_events(task_id, orders=orders))
        return compose_brief(order_, root=ROOT, cwd=WT, orders_dir=orders, data=data or {}, runner=repo)


    def test_an_implement_brief_is_the_brief_the_task_and_the_order(tmp_path):
        order(tmp_path, "o-1", "implement", task="2")
        repo = Repo()
        assert brief(tmp_path, "o-1", repo) == (
            "<.lean-ctx/lean-herdr/briefs/implement.lmd.md>\n\n"
            f"<{PLAN_FILE} --phase task-2>\n\n"
            "## Order\n\n"
            "o-1  [created]  <- orch\n"
            "implement of plan shop"
        )
        assert {cwd for _cmd, cwd in repo.calls} == {"/wt/shop"}


    def test_a_branch_implement_brief_carries_the_constraints_and_the_findings_it_answers(tmp_path):
        order(tmp_path, "o-1", "review", task="branch", done="h9", message="VERDIKT: reject\napp/main.py leaks a debug print")
        order(tmp_path, "o-2", "implement", task="branch", after="o-1")
        text = brief(tmp_path, "o-2", Repo())
        assert f"<{PLAN_FILE} --phase constraints>" in text
        assert "--phase task-" not in text
        assert "after: o-1 (builder-plan-shop, completed)" in text
        assert "app/main.py leaks a debug print" in text


    def test_a_task_review_diffs_from_the_start_head_of_the_first_implement_round(tmp_path):
        order(tmp_path, "o-1", "implement", task="2", start="s1", done="d1")
        order(tmp_path, "o-2", "review", task="2", done="d1", message="VERDIKT: reject\nno test")
        order(tmp_path, "o-3", "implement", task="2", start="s2", done="d2")
        order(tmp_path, "o-4", "review", task="2")
        repo = Repo(log="c2 test(api): cover the route\nc1 feat(api): add the route\n", status=" M app/main.py\n?? notes.txt\n")
        text = brief(tmp_path, "o-4", repo)
        assert text.index("--phase constraints>") < text.index("--phase task-2>") < text.index("## Diff")
        assert "`wt step diff s1`\n" in text
        assert "- c1 feat(api): add the route" in text
        assert "- notes.txt" in text
        assert "- app/main.py" not in text
        assert (["git", "log", "--oneline", "s1..HEAD"], "/wt/shop") in repo.calls


    def test_without_a_start_head_the_previous_tasks_done_head_stands_in_and_says_so(tmp_path):
        order(tmp_path, "o-1", "implement", task="1", start="s1", done="d1")
        order(tmp_path, "o-2", "implement", task="2", done="d2")
        order(tmp_path, "o-3", "review", task="2")
        text = brief(tmp_path, "o-3", Repo())
        assert "`wt step diff d1` (no start head on task 2: the done head of task 1 stands in)" in text


    def test_task_one_without_a_start_head_diffs_from_the_merge_base(tmp_path):
        order(tmp_path, "o-1", "implement", task="1", done="d1")
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


    def test_a_failing_render_names_the_file_and_the_phase(tmp_path):
        order(tmp_path, "o-1", "implement", task="1")
        with pytest.raises(BriefError) as caught:
            brief(tmp_path, "o-1", Repo(broken_render=f"{PLAN_FILE} --phase task-1"))
        assert str(caught.value) == f"render_failed: {PLAN_FILE} --phase task-1: PHASE_ABORTED: macro not found: gate"


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


    def test_brief_behind_a_flag_is_a_usage_error_and_no_show(cwd_repo, capsys):
        assert main(["--task", "o-1", "brief"]) == 0
        assert _line(capsys) == {
            "ok": False,
            "error": "usage_error: brief comes first: lean-herdr plan brief --task o-…",
        }

Run: `uv run pytest -q tests/test_plancmd.py`

Expected: FAIL — `ImportError: cannot import name 'BriefError' from 'lean_herdr.plancmd'` beim Sammeln.

### Schritt 2 — `report.order_text`

@call patch("lean_herdr/report.py", "def _brief and its two callers in next_order and show_order")

`_brief` heißt `order_text`, Rumpf und Docstring bleiben; beide Aufrufer
(`"text": _brief(order, orders_dir=orders_dir)`) rufen `order_text`.

Run: `uv run pytest -q tests/test_report.py`

Expected: PASS — unverändert.

### Schritt 3 — `plancmd.py`

@call patch("lean_herdr/plancmd.py", "the module docstring, the imports, SUBCOMMANDS and the line after it, missing_flags and the start of main")

- Modul-Docstring, erste Zeile → `"""`lean-herdr plan check | next | show | brief` -- a plan run as the orchestrator and its workers see it.`;
  am Docstring-Ende vor `"""` einfügen:

      `brief` is the one plain-text output (spec 6.2): the text a worker works from, or one line
      on stderr with exit 1 -- a worker's shell reads the exit code, not JSON.

- Importe: `from lean_herdr.plan import Plan, PlanError, load_plan, plan_path, show` →
  `from lean_herdr.plan import Plan, PlanError, load_plan, outline, plan_branch, plan_path, read_source, run_git, show, structure`;
  nach dem `planrun`-Import `from lean_herdr.report import order_text`;
  `from lean_herdr.settings import SETTINGS_PATH, SettingsError, read_settings, work_roles` →
  `from lean_herdr.settings import SETTINGS_PATH, STAGES, SettingsError, read_settings, settings_for, work_roles`
- `SUBCOMMANDS = ("check", "next", "show")` → `SUBCOMMANDS = ("check", "next", "show", "brief")`
- Nach `SUBCOMMANDS = ("check", "next", "show", "brief")`:

      #: One brief per step, rendered whole in the worker's worktree (spec section 4).
      BRIEFS_DIR = Path(".lean-ctx") / "lean-herdr" / "briefs"

      RENDER_TIMEOUT_S = 60.0


      class BriefError(Exception):
          """Why no brief could be put together -- the one line `plan brief` prints on stderr."""


      def render(cwd: Path, path: str | Path, *, phase: str | None = None, runner: Any = subprocess.run) -> str:
          """`lean-md render <path> [--phase <phase>] --consumer=ai` in `cwd`, stripped.

          `cwd` is the worker's worktree: imports and `@include` resolve against it, and a phase
          render writes to that worktree's lean-ctx session, which is wanted (spec section 6.5).
          """
          where = f"{path} --phase {phase}" if phase else str(path)
          cmd = ["lean-md", "render", str(path), *(["--phase", phase] if phase else []), "--consumer=ai"]
          try:
              proc = runner(
                  cmd,
                  cwd=str(cwd),
                  capture_output=True,
                  text=True,
                  errors="replace",
                  timeout=RENDER_TIMEOUT_S,
                  check=False,
              )
          except (OSError, subprocess.SubprocessError, ValueError) as exc:
              raise BriefError(f"render_failed: {where}: {exc}") from exc
          text = (proc.stdout or "").strip()
          if proc.returncode != 0 or not text:
              lines = (proc.stderr or "").strip().splitlines()
              raise BriefError(f"render_failed: {where}: {lines[0] if lines else f'exit {proc.returncode}'}")
          return text


      def _lines(cwd: Path, *args: str, runner: Any) -> list[str]:
          """The output lines of one git command in `cwd`; none when it fails."""
          proc = run_git(cwd, *args, runner=runner)
          return proc.stdout.splitlines() if proc is not None and proc.returncode == 0 else []


      def _review_base(orders: list[Order], number: int, *, cwd: Path, runner: Any) -> tuple[str, str]:
          """`(sha, note)`: where task `number`'s changes start, and what stood in for a missing stamp.

          The `report start` head of the task's FIRST implement order; without it the `report done`
          head of the task before; without that the merge base with main (spec section 6.4).
          """
          implements = [o for o in orders if o.step == "implement" and o.plan_task == str(number)]
          first = implements[0].start_head if implements else None
          if first:
              return first, ""
          previous = [
              o.done_head or ""
              for o in orders
              if o.step == "implement" and o.plan_task == str(number - 1) and o.done_head
          ]
          if previous:
              return previous[-1], f"(no start head on task {number}: the done head of task {number - 1} stands in)"
          base = _lines(cwd, "merge-base", "main", "HEAD", runner=runner)
          if not base:
              raise BriefError(f"no_base: task {number} has no start head, and no merge base with main")
          return base[0], f"(no start head on task {number}: the merge base with main stands in)"


      def _diff_section(sha: str, note: str, *, cwd: Path, runner: Any) -> str:
          commits = _lines(cwd, "log", "--oneline", f"{sha}..HEAD", runner=runner)
          status = _lines(cwd, "status", "--porcelain", "--untracked-files=all", runner=runner)
          untracked = [line[3:] for line in status if line.startswith("?? ")]
          lines = ["## Diff", "", f"`wt step diff {sha}` {note}".rstrip(), "", "Commits:"]
          lines += [f"- {commit}" for commit in commits] or ["- none"]
          lines += ["", "Untracked files, in no commit:"]
          lines += [f"- {path}" for path in untracked] or ["- none"]
          return "\n".join(lines)


      def _task_list(root: Path, slug: str, *, runner: Any) -> str:
          ref, text = read_source(root, slug, runner=runner)
          plan = structure(slug, ref, outline(root, text, runner=runner))
          return "\n".join(["## Tasks", "", *(f"- {task.title}" for task in plan.tasks)])


      def _works(data: dict[str, Any]) -> str:
          """The works a plan may route to, with the role and model behind each -- no stages."""
          lines = ["## Works", ""]
          for work, role in sorted(work_roles(data).items()):
              if work not in STAGES:
                  model = settings_for(role, data).model or "(runtime default)"
                  lines.append(f"- `{work}` -> {role}, model {model}")
          return "\n".join(lines)


      def _finding_line(finding: dict[str, Any]) -> str:
          where = f"line {finding['line']}" + (f" ({finding['phase']})" if "phase" in finding else "")
          return f"- [{finding['kind']}] {where}: {finding['message']}"


      def compose_brief(
          order: Order,
          *,
          root: Path,
          cwd: Path,
          orders_dir: str | Path,
          data: dict[str, Any],
          runner: Any = subprocess.run,
      ) -> str:
          """The text a worker works from, for one plan order (spec section 6.5).

          `root` is the repository root (log, `git show`, `plan check`), `cwd` the worker's
          worktree (every render, the commit list, the untracked files).
          """
          if order.plan is None or order.step is None:
              raise BriefError(f"order {order.id} belongs to no plan")
          slug, step, task = order.plan, order.step, order.plan_task
          path = plan_path(slug)
          parts = [render(cwd, BRIEFS_DIR / f"{step}.lmd.md", runner=runner)]
          if step == "implement" and task != "branch":
              parts.append(render(cwd, path, phase=f"task-{task}", runner=runner))
          elif step == "implement":
              parts.append(render(cwd, path, phase="constraints", runner=runner))
          elif step == "review" and task != "branch":
              parts.append(render(cwd, path, phase="constraints", runner=runner))
              parts.append(render(cwd, path, phase=f"task-{task}", runner=runner))
              number = int(task or 0)
              sha, note = _review_base(plan_orders(slug, orders_dir=orders_dir), number, cwd=cwd, runner=runner)
              parts.append(_diff_section(sha, note, cwd=cwd, runner=runner))
          elif step == "review":
              parts.append(render(cwd, path, phase="constraints", runner=runner))
              parts.append(_task_list(root, slug, runner=runner))
              parts.append("## Diff\n\n`wt step diff` -- everything since the branch left main")
          elif step == "plan":
              parts.append(f"## Plan\n\n`{path}` on branch `{plan_branch(slug)}`\n\nSpec: `{order.spec}`")
              parts.append(_works(data))
          else:
              checked = check_result(root, slug, data, runner=runner)
              if "error" in checked:
                  raise BriefError(str(checked["error"]))
              lines = ["## plan check", "", "Errors:"]
              lines += [_finding_line(finding) for finding in checked["errors"]] or ["- none"]
              lines += ["", "Warnings:"]
              lines += [_finding_line(finding) for finding in checked["warnings"]] or ["- none"]
              parts.append(f"## Plan\n\n`{path}` on branch `{plan_branch(slug)}`")
              parts.append("\n".join(lines))
          parts.append("## Order\n\n" + order_text(order, orders_dir=orders_dir))
          return "\n\n".join(parts)


      def _brief_failed(message: str) -> int:
          sys.stderr.write(message + "\n")
          return 1


      def brief_main(argv: list[str]) -> int:
          """`plan brief --task o-…`: the brief on stdout and exit 0, or one line on stderr and exit 1."""
          try:
              args = build_parser().parse_args(argv)
              complaint = missing_flags(args)
              if complaint:
                  return _brief_failed(f"usage_error: {complaint}")
              cwd = Path.cwd()
              root = canonical_root(cwd)
              orders_dir = state_dir(root)
              order = fold(read_events(args.task, orders=orders_dir))
              if not order.state:
                  return _brief_failed(f"task_not_found: {args.task}")
              data = _settings(root)
              text = compose_brief(order, root=root, cwd=cwd, orders_dir=orders_dir, data=data)
          except UsageError as exc:
              return _brief_failed(f"usage_error: {exc}")
          except SettingsError as exc:
              return _brief_failed(f"config_error: {exc}")
          except (BriefError, PlanError, OrderLogError, BusError) as exc:
              return _brief_failed(str(exc))
          except Exception as exc:  # noqa: BLE001 -- one line on stderr, never a traceback
              return _brief_failed(f"brief_crashed: {exc}")
          sys.stdout.write(text + "\n")
          return 0

- `missing_flags`: als erste Anweisung einfügen:

      if args.command == "brief":
          if args.slug is not None:
              return "brief takes --task, not a slug"
          return None if args.task else "brief needs --task"

- `main`: Docstring → `"""`check`, `next`, `show`: one JSON line on stdout, exit ALWAYS 0. `brief`: see brief_main."""`;
  als erste Anweisungen nach dem Docstring:

      arguments = list(sys.argv[1:] if argv is None else argv)
      if arguments[:1] == ["brief"]:
          return brief_main(arguments)

  und in `main` — nicht in `brief_main` — `args = build_parser().parse_args(argv)` →
  `args = build_parser().parse_args(arguments)`; direkt danach:

      if args.command == "brief":
          raise UsageError("brief comes first: lean-herdr plan brief --task o-…")

@call patch("lean_herdr/cli.py", "the house-contract sentence of the docstring, and the llm prereview line of USAGE")

- Im Docstring `exit ALWAYS 0. Two` → `exit ALWAYS 0 --` + Zeilenumbruch +
  `` `plan brief` aside, the one plain-text answer a worker reads. Two ``

- In `USAGE` nach `"  llm prereview: the ruling on stdout, exit 1 on reject\n"`:
  `"  plan brief: the brief on stdout, exit 1 with one line on stderr on failure\n"`

Run: `uv run pytest -q tests/test_plancmd.py tests/test_report.py tests/test_cli.py`

Expected: PASS — alle Tests der drei Dateien.

@call verify(lean_herdr/plancmd.py lean_herdr/report.py lean_herdr/cli.py tests/test_plancmd.py)
@call review_change()
@call py_gate(lean_herdr/plancmd.py lean_herdr/report.py lean_herdr/cli.py tests/test_plancmd.py)
@call commit("lean_herdr/plancmd.py lean_herdr/report.py lean_herdr/cli.py tests/test_plancmd.py", "feat(plan): compose a worker's brief with lean-herdr plan brief")
@phase-end

@phase "task-6"
## Task 6: Pre-Review im Plan-Modus

**Files:** Modify `lean_herdr/llm.py`, `lean_herdr/plancmd.py`, `lean_herdr/dispatch.py`,
`tests/test_llm.py`, `tests/test_plancmd.py`, `tests/test_dispatch_prereview.py`.

**Interfaces — Produces:**

    # lean_herdr/llm.py
    PLAN_PREREVIEW_PROMPT: str                                       # Platzhalter {order}, {diff}
    def wt_diff(path, *, base: str | None = None, runner=…, timeout_s=…) -> str | None
    def prereview(order, diff, *, plan: bool = False, …) -> tuple[str, str]
    def prereview_result(order, *, branch, worktree_list, base: str | None = None, plan: bool = False, …) -> dict
    # CLI: lean-herdr llm prereview [--base <sha>] [--plan] …
    # lean_herdr/plancmd.py
    PLAN_RULES_SUMMARY: str
    @dataclass(frozen=True) class PrereviewInput(order: str = "", base: str | None = None, plan: bool = False, skip: str | None = None)
    def prereview_input(order: Order, *, root: Path, branch: str | None, worktree_list: Any, runner=subprocess.run) -> PrereviewInput

| Auftrag | `PrereviewInput` |
|---|---|
| ohne `plan` | `skip="no_plan_order"` |
| `plan` | `order` = Spec von `main` + `PLAN_RULES_SUMMARY`, `plan=True`; Spec nicht lesbar → `skip="spec_unreadable"` |
| `implement`, Task N | `order` = Render `constraints` + `task-N` im Worktree, `base=start_head`; ohne `start_head` → `no_start_head`, Worktree nicht auflösbar → `worktree_unresolved`, Render scheitert → `render_failed` |
| `implement` branch, `review`, `plan-review` | `skip="no_prereview_for_step"` |

`dispatch.await_task` fragt `plancmd.prereview_input` nur bei einem Auftrag mit `plan`. Ein `skip`
wird zu `prereview: skipped` mit dem Grund als `prereview_note`; sonst gehen `order`, `base` und
`plan` an `llm.prereview_result`. `MAX_DIFF_BYTES` gilt für Diff und Auftrag zusammen.
Aufruf-Test für `wt step diff <sha>` (Plan A, Task 1): `test_a_base_diffs_since_that_commit`.

### Schritt 1 — Tests zuerst

`tests/test_llm.py`, zwei bestehende Tests anpassen:

- In `test_the_flags_reach_prereview`:
  `assert fetched == {"path": "/worktrees/feat-x", "timeout_s": 5.0}` →
  `assert fetched == {"path": "/worktrees/feat-x", "base": None, "timeout_s": 5.0}`;
  im `judged_with`-Vergleich nach `"diff": "diff --git a/x b/x",` die Zeile `"plan": False,`.
- In `test_the_absent_prereview_flags_stay_none_and_the_defaults_differ`:
  `assert fetched == {"path": ".", "timeout_s": llm.DIFF_TIMEOUT_S}` →
  `assert fetched == {"path": ".", "base": None, "timeout_s": llm.DIFF_TIMEOUT_S}`;
  am Ende `assert judged_with["plan"] is False`.

`tests/test_llm.py`, am Dateiende:

    def test_a_base_diffs_since_that_commit():
        calls = []

        def runner(cmd, **_kw):
            calls.append(list(cmd))
            return Completed(stdout="diff --git a/x b/x")

        assert llm.wt_diff("/worktrees/plan-shop", base="abc123", runner=runner) == "diff --git a/x b/x"
        assert calls == [["wt", "-C", "/worktrees/plan-shop", "step", "diff", "abc123"]]


    @pytest.mark.parametrize(
        ("plan", "present", "absent"),
        [
            (True, "expensive plan reviewer", "Judge ONLY the diff below"),
            (False, "Judge ONLY the diff below", "expensive plan reviewer"),
        ],
    )
    def test_plan_mode_picks_the_plan_prompt(no_store, plan, present, absent):
        spy = SpyRequest(answer("PREREVIEW: pass"))
        llm.prereview(
            "the spec",
            "diff --git a/p b/p",
            plan=plan,
            request=spy,
            env={openrouter.KEY_ENV: "k"},
            auth_path=no_store,
            settings=NO_FILE,
        )
        sent = json.dumps(spy.json_body())
        assert present in sent
        assert absent not in sent
        assert "the spec" in sent


    def test_order_and_diff_count_together_against_the_cap(no_store):
        half = llm.MAX_DIFF_BYTES // 2 + 1
        spy = SpyRequest(answer("PREREVIEW: reject"))
        ruling, note = llm.prereview(
            "o" * half,
            "d" * half,
            request=spy,
            env={openrouter.KEY_ENV: "k"},
            auth_path=no_store,
            settings=NO_FILE,
        )
        assert (ruling, note) == ("skipped", "diff_too_large")
        assert spy.urls == []


    def test_prereview_result_hands_base_and_prompt_on(no_store):
        seen = []

        def runner(cmd, **_kw):
            seen.append(list(cmd))
            return Completed(stdout="diff --git a/p b/p")

        spy = SpyRequest(answer("PREREVIEW: pass"))
        got = llm.prereview_result(
            "the spec",
            branch="plan/shop",
            worktree_list=worktrees({"branch": "plan/shop", "path": "/worktrees/plan-shop"}),
            base="abc123",
            plan=True,
            runner=runner,
            request=spy,
            settings=NO_FILE,
            env={openrouter.KEY_ENV: "k"},
            auth_path=no_store,
        )
        assert got == {"prereview": "pass", "prereview_note": ""}
        assert seen == [["wt", "-C", "/worktrees/plan-shop", "step", "diff", "abc123"]]
        assert "expensive plan reviewer" in json.dumps(spy.json_body())


    def test_the_cli_takes_base_and_plan(monkeypatch):
        fetched: dict[str, object] = {}
        judged_with: dict[str, object] = {}

        def fake_wt_diff(_path, **kwargs):
            fetched.update(kwargs)
            return "diff"

        def fake_prereview(_order, _diff, **kwargs):
            judged_with.update(kwargs)
            return "pass", ""

        monkeypatch.setattr(llm, "wt_diff", fake_wt_diff)
        monkeypatch.setattr(llm, "prereview", fake_prereview)
        assert llm.main(["prereview", "--base", "abc123", "--plan", "--order", "the spec"]) == 0
        assert fetched["base"] == "abc123"
        assert judged_with["plan"] is True

`tests/test_plancmd.py`: `from lean_herdr.orders import fold` → `from lean_herdr.orders import Order, fold`;
den `plancmd`-Import um `PLAN_RULES_SUMMARY, PrereviewInput` und `prereview_input` ergänzen. Am Dateiende:

    WORKTREES = {"result": {"worktrees": [{"branch": "plan/shop", "path": "/wt/shop"}]}}
    SPEC_FILE = "docs/specs/shop-design.md"


    def plan_order(**fields):
        return Order(id="o-1", to_agent=WORKER, state="completed", plan=SLUG, **fields)


    def picked(order_, repo, worktree_list=WORKTREES):
        return prereview_input(order_, root=ROOT, branch="plan/shop", worktree_list=worktree_list, runner=repo)


    def test_a_plan_is_judged_against_its_spec_from_main_and_the_rules():
        repo = Repo({f"main:{SPEC_FILE}": "# Shop\n\nThe API lists products.\n"})
        assert picked(plan_order(step="plan", spec=SPEC_FILE), repo) == PrereviewInput(
            order=f"# Shop\n\nThe API lists products.\n\n{PLAN_RULES_SUMMARY}", plan=True
        )


    def test_a_task_is_judged_against_its_rendered_task_since_its_start_head():
        repo = Repo()
        got = picked(plan_order(step="implement", plan_task="2", start_head="s1"), repo)
        assert got == PrereviewInput(
            order=f"<{PLAN_FILE} --phase constraints>\n\n<{PLAN_FILE} --phase task-2>", base="s1"
        )
        assert {cwd for _cmd, cwd in repo.calls} == {"/wt/shop"}


    @pytest.mark.parametrize(
        ("order_", "worktree_list", "repo", "skip"),
        [
            (Order(id="o-1", state="completed"), WORKTREES, Repo(), "no_plan_order"),
            (plan_order(step="plan", spec=SPEC_FILE), WORKTREES, Repo(), "spec_unreadable"),
            (plan_order(step="implement", plan_task="branch", start_head="s1"), WORKTREES, Repo(), "no_prereview_for_step"),
            (plan_order(step="review", plan_task="1"), WORKTREES, Repo(), "no_prereview_for_step"),
            (plan_order(step="implement", plan_task="1"), WORKTREES, Repo(), "no_start_head"),
            (plan_order(step="implement", plan_task="1", start_head="s1"), {"result": "garbage"}, Repo(), "worktree_unresolved"),
            (
                plan_order(step="implement", plan_task="1", start_head="s1"),
                WORKTREES,
                Repo(broken_render=f"{PLAN_FILE} --phase task-1"),
                "render_failed",
            ),
        ],
        ids=["no-plan", "no-spec", "branch", "review", "no-start-head", "no-worktree", "render"],
    )
    def test_what_gets_no_pre_review_says_why(order_, worktree_list, repo, skip):
        assert picked(order_, repo, worktree_list) == PrereviewInput(skip=skip)

`tests/test_dispatch_prereview.py`: nach `from lean_herdr.orderlog import append` die Zeile
`from lean_herdr.plancmd import PrereviewInput`. Am Dateiende:

    def plan_log(tmp_path):
        append(
            TASK_ID,
            "created",
            "orchestrator",
            {"to_agent": WORKER, "description": "Task 1 of plan shop", "plan": "shop", "step": "implement", "plan_task": "1"},
            orders=tmp_path,
        )
        append(TASK_ID, "working", WORKER, {"head": "s1", "changes": []}, orders=tmp_path)
        append(TASK_ID, "completed", WORKER, {"message": "done", "head": "d1", "changes": []}, orders=tmp_path)
        return tmp_path


    def test_a_plan_order_is_judged_with_what_plancmd_picks(herdr, tmp_path, monkeypatch):
        asked = {}

        def fake_input(order, **kwargs):
            asked.update(order_id=order.id, **kwargs)
            return PrereviewInput(order="the rendered task 1", base="s1")

        monkeypatch.setattr("lean_herdr.plancmd.prereview_input", fake_input)
        runner, request = llm_doubles("PREREVIEW: pass", monkeypatch, tmp_path)
        seen, bodies = [], []

        def recording_runner(cmd, **kw):
            seen.append(list(cmd))
            return runner(cmd, **kw)

        def recording_request(url, **kw):
            bodies.append(kw.get("body") or "")
            return request(url, **kw)

        result = wait(herdr, plan_log(tmp_path), prereview=True, runner=recording_runner, request=recording_request)
        assert result["prereview"] == "pass"
        assert seen == [["wt", "-C", "/worktrees/feat-x", "step", "diff", "s1"]]
        assert "the rendered task 1" in bodies[0]
        assert "Task 1 of plan shop" not in bodies[0]
        assert (asked["order_id"], asked["branch"], asked["root"]) == (TASK_ID, BRANCH, ROOT)


    def test_a_skip_from_plancmd_is_the_answer_and_nothing_runs(herdr, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "lean_herdr.plancmd.prereview_input", lambda order, **_kw: PrereviewInput(skip="no_start_head")
        )

        def runner(*_a, **_kw):
            raise AssertionError("a skipped pre-review runs no wt")

        result = wait(herdr, plan_log(tmp_path), prereview=True, runner=runner)
        assert result["ok"] is True
        assert result["prereview"] == "skipped"
        assert result["prereview_note"] == "no_start_head"


    def test_an_order_outside_a_plan_never_asks_plancmd(herdr, tmp_path, monkeypatch):
        def refuse(*_a, **_kw):
            raise AssertionError("an order without a plan must not reach plancmd")

        monkeypatch.setattr("lean_herdr.plancmd.prereview_input", refuse)
        runner, request = llm_doubles("PREREVIEW: pass", monkeypatch, tmp_path)
        result = wait(herdr, completed_log(tmp_path), prereview=True, runner=runner, request=request)
        assert result["prereview"] == "pass"

Run: `uv run pytest -q tests/test_llm.py tests/test_plancmd.py tests/test_dispatch_prereview.py`

Expected: FAIL — `ImportError` beim Sammeln (`PLAN_RULES_SUMMARY` und `PrereviewInput` fehlen in `lean_herdr.plancmd`); pytest
bricht den Lauf dort ab, bevor ein anderer Test läuft.

### Schritt 2 — `llm.py`

@call patch("lean_herdr/llm.py", "the line after PREREVIEW_PROMPT, wt_diff, the signature, cap and prompt of prereview, prereview_result, build_parser after --order, and the wt_diff and prereview calls in main")

- Nach `PREREVIEW_PROMPT = """…"""`:

      #: The plan-mode judge (plan spec 6.6): the diff is a plan, the order its spec plus the
      #: plan rules. It rejects only what shows without taste.
      PLAN_PREREVIEW_PROMPT = """You are a cheap pre-check that runs before an expensive plan reviewer.
      The diff below adds an implementation plan. Judge it ONLY against the spec and the plan
      rules given as the order.

      Answer with `PREREVIEW: pass` or `PREREVIEW: reject` on the FIRST line, then
      at most three sentences of reason.

      Reject ONLY for one of these, and name which one:
      - a requirement of the spec that no task of the plan covers
      - a plan rule from the order that the plan visibly breaks

      Never reject for wording, task size or style. When in doubt, pass: a strong
      plan reviewer runs after you either way, and a wrong rejection costs a whole
      planning round.

      <order>
      {order}
      </order>

      <diff>
      {diff}
      </diff>
      """

- `wt_diff`: in der Signatur vor `runner: Any = subprocess.run,` die Zeile `base: str | None = None,`;
  im Docstring vor dem Absatz „Untracked is also why …":

      `base` diffs since that commit instead of since branching: in plan mode one task's
      changes, without the plan commit and the tasks before it.

  und `["wt", "-C", str(path), "step", "diff"],` → `["wt", "-C", str(path), "step", "diff", *([base] if base else [])],`
- `prereview`: in der Signatur nach `*,` die Zeile `plan: bool = False,`; im Docstring vor dem Absatz
  „The judge resolves …":

      `plan` judges a plan against its spec with PLAN_PREREVIEW_PROMPT. The cap counts order and
      diff together: in plan mode the order is a whole spec.

  `if len(diff.encode("utf-8")) > MAX_DIFF_BYTES:` →
  `if len(diff.encode("utf-8")) + len(order.encode("utf-8")) > MAX_DIFF_BYTES:`;
  `PREREVIEW_PROMPT.format(order=order, diff=diff),` →
  `(PLAN_PREREVIEW_PROMPT if plan else PREREVIEW_PROMPT).format(order=order, diff=diff),`
- `prereview_result`: in der Signatur nach `worktree_list: Any,` die Zeilen `base: str | None = None,`
  und `plan: bool = False,`; `diff = wt_diff(path, runner=runner)` → `diff = wt_diff(path, base=base, runner=runner)`;
  `ruling, note = prereview(order, diff, settings=settings, **kwargs)` →
  `ruling, note = prereview(order, diff, plan=plan, settings=settings, **kwargs)`
- `build_parser`, nach dem `--order`-Argument:

      p.add_argument(
          "--base",
          default=None,
          help="prereview: diff since this commit instead of since branching",
      )
      p.add_argument(
          "--plan",
          action="store_true",
          help="prereview: judge a plan against the spec given as --order",
      )

- `main`: `diff = wt_diff(args.path, timeout_s=args.timeout or DIFF_TIMEOUT_S)` →
  `diff = wt_diff(args.path, base=args.base, timeout_s=args.timeout or DIFF_TIMEOUT_S)`;
  im `prereview(`-Aufruf nach `diff,` die Zeile `plan=args.plan,`.

Run: `uv run pytest -q tests/test_llm.py`

Expected: PASS — alle Tests in `tests/test_llm.py`.

### Schritt 3 — `plancmd.prereview_input`

@call patch("lean_herdr/plancmd.py", "the stdlib imports, the lean_herdr imports, and the end of the file")

- Import-Block: nach `import sys` die Zeile `from dataclasses import dataclass`;
  nach `from lean_herdr.settings import …` die Zeile `from lean_herdr.worktree import find_worktree`
- Am Dateiende:

      #: Spec section 3 in a few lines, for the plan-mode judge.
      PLAN_RULES_SUMMARY = """Plan rules:
      - phases `constraints` and `lanes` exist; tasks are `task-1` ... `task-N`, gapless, in document order
      - the first `@call` of every task is `route(work, lane, files)`, and `files` is not empty
      - `work` is routed in [routing] and is none of the stages plan, plan-review, review, integrate
      - every lane is declared with `@call lane(name, deps)`; deps name declared lanes and form no cycle
      - no task comes before a task of a lane its own lane depends on"""


      @dataclass(frozen=True)
      class PrereviewInput:
          """What the judge gets for one plan order (spec section 6.6) -- or why it gets nothing."""

          #: The text the judge reads as the order.
          order: str = ""
          #: The commit the diff starts at; None diffs since branching.
          base: str | None = None
          #: PLAN_PREREVIEW_PROMPT instead of PREREVIEW_PROMPT.
          plan: bool = False
          #: Set when this order gets no pre-review: the note beside `prereview: skipped`.
          skip: str | None = None


      def _worktree_path(worktree_list: Any, branch: str | None) -> Path | None:
          try:
              entry = find_worktree(worktree_list or {}, branch or "")
          except (AttributeError, TypeError):
              return None
          path = entry.get("path") if isinstance(entry, dict) else None
          return Path(path) if path else None


      def prereview_input(
          order: Order,
          *,
          root: Path,
          branch: str | None,
          worktree_list: Any,
          runner: Any = subprocess.run,
      ) -> PrereviewInput:
          """The judge's order, diff base and prompt for a plan order. Never raises.

          `plan`: the spec read from main, plus the plan rules; the diff since branching is the
          plan. `implement` on a task: the rendered constraints and task, diffed from the order's
          own `report start` head. Every other step gets no pre-review.
          """
          if order.plan is None:
              return PrereviewInput(skip="no_plan_order")
          if order.step == "plan":
              spec = show(root, "main", order.spec, runner=runner) if order.spec else None
              if not spec:
                  return PrereviewInput(skip="spec_unreadable")
              return PrereviewInput(order=f"{spec.strip()}\n\n{PLAN_RULES_SUMMARY}", plan=True)
          if order.step != "implement" or order.plan_task == "branch":
              return PrereviewInput(skip="no_prereview_for_step")
          if not order.start_head:
              return PrereviewInput(skip="no_start_head")
          path = _worktree_path(worktree_list, branch)
          if path is None:
              return PrereviewInput(skip="worktree_unresolved")
          try:
              text = "\n\n".join(
                  render(path, plan_path(order.plan), phase=phase, runner=runner)
                  for phase in ("constraints", f"task-{order.plan_task}")
              )
          except BriefError:
              return PrereviewInput(skip="render_failed")
          return PrereviewInput(order=text, base=order.start_head)

Run: `uv run pytest -q tests/test_plancmd.py`

Expected: PASS — alle Tests in `tests/test_plancmd.py`.

### Schritt 4 — `dispatch.await_task`

@call patch("lean_herdr/dispatch.py", "the pre-review block inside await_task")

Den Block von `if req.prereview and order.state == "completed":` bis vor `return outcome` ersetzen durch
(Kommentar über `verdict` bleibt):

      if req.prereview and order.state == "completed":
          # Beside `verdict`, never instead of it: that key belongs
          # to the strong reviewer and its VERDIKT: protocol, and a
          # second writer on it would be exactly the confusion
          # VERDICT_RE exists to prevent.
          worktrees = herdr.worktree_list(root)
          description = order.description
          judged: dict[str, Any] = {}
          if order.plan is not None:
              # Imported on the call: plancmd reaches planrun, and planrun imports this module.
              from lean_herdr.plancmd import prereview_input

              chosen = prereview_input(
                  order, root=root, branch=req.worktree, worktree_list=worktrees, runner=runner
              )
              if chosen.skip is not None:
                  outcome.update({"prereview": "skipped", "prereview_note": chosen.skip})
                  return outcome
              description = chosen.order
              judged = {"base": chosen.base, "plan": chosen.plan}
          outcome.update(
              llm.prereview_result(
                  description,
                  branch=req.worktree,
                  worktree_list=worktrees,
                  settings=llm_cfg,
                  runner=runner,
                  request=request,
                  **judged,
              )
          )

Run: `uv run pytest -q tests/test_llm.py tests/test_plancmd.py tests/test_dispatch_prereview.py tests/test_dispatch_await.py`

Expected: PASS — alle Tests der vier Dateien.

### Schritt 5 — Produktions-LOC messen

Run (der Block steht ohne Einrückung, so wie er in die Shell geht):

```bash
uv run python - <<'EOF'
import ast, io, tokenize
from pathlib import Path
def prod_loc(path):
    src = Path(path).read_text()
    doc = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                doc.update(range(first.lineno, first.end_lineno + 1))
    code = set()
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER):
            continue
        code.update(range(tok.start[0], tok.end[0] + 1))
    return len(code - doc)
for name in ("dispatch", "llm", "plan", "planrun", "plancmd", "report"):
    print(name, prod_loc(f"lean_herdr/{name}.py"))
EOF
```

Expected: jede Zahl ≤ 800; die Zahlen im Bericht nennen.

@call verify(lean_herdr/llm.py lean_herdr/plancmd.py lean_herdr/dispatch.py tests/test_llm.py tests/test_plancmd.py tests/test_dispatch_prereview.py)
@call review_change()
@call py_gate(lean_herdr/llm.py lean_herdr/plancmd.py lean_herdr/dispatch.py tests/test_llm.py tests/test_plancmd.py tests/test_dispatch_prereview.py)
@call commit("lean_herdr/llm.py lean_herdr/plancmd.py lean_herdr/dispatch.py tests/test_llm.py tests/test_plancmd.py tests/test_dispatch_prereview.py", "feat(prereview): judge a plan against its spec and a task since its start head")
@call remember_decision("lean-herdr TP2 plan B done: plan.py reads a plan off plan/<slug> (fallback main) and checks it via lean-md outline plus the spec's section 3 rules; planrun.next_step is the pure decision for plan next; plancmd adds plan check/next/show (JSON) and plan brief (plain text, exit 1 on failure); llm.prereview_result takes base and plan, and dispatch.await_task asks plancmd.prereview_input only for orders that carry a plan.")
@phase-end
