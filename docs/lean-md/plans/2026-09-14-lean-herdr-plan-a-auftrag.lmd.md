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

# lean-herdr TP2 — Plan A: Auftrag und Stempel

Spec: `docs/specs/2026-09-14-lean-herdr-plan-design.md` (§6.3, §5.2, §5.5, §11).
Teil 1 von 3; danach Plan B „Plan lesen und steuern" und Plan C „Ausliefern".
Render je Task: `lean-md render docs/lean-md/plans/2026-09-14-lean-herdr-plan-a-auftrag.lmd.md --phase task-N`.

## Goal

Die Aufträge und Berichte tragen, was ein Plan-Lauf später auswertet: Ein Auftrag gehört über
`--plan/--step/--plan-task/--spec` zu einem Plan, `report start` und `report done` stempeln
`head` und `changes` des Worktrees. `dispatch` lehnt zu lange Agent-Namen vor dem Pane ab und
stellt `.lean-ctx/lean-herdr/bin` vorn in den `PATH` eines Workers.

- **Task 1** — Messungen: `wt step diff <sha>`, `wt list --format=json`, `PATH` im Pane.
- **Task 2** — Plan-Felder im Auftrag: `orders.py`, `ordercmd.py`, `dispatch.py`.
- **Task 3** — Stempel: `report.worktree_stamp`, `Order.start_head/done_head/done_changes`.
- **Task 4** — `dispatch`: Längenprüfung des Agent-Namens, `PATH` für Worker.

## Architecture

```
lean_herdr/orders.py    + PLAN_STEPS, PLAN_SLUG_RE, _text; Order.plan/step/plan_task/spec  (Task 2)
                        + Order.start_head/done_head/done_changes; _apply liest die Stempel (Task 3)
lean_herdr/ordercmd.py  + OrderRequest.plan/step/plan_task/spec, plan_flag_problem;
                          create_order prüft und schreibt die Felder                      (Task 2)
lean_herdr/dispatch.py  + --plan/--step/--plan-task/--spec; missing_flags; main           (Task 2)
                        + import os, HERDR_NAME_MAX, WORKER_BIN; _build prüft die Länge;
                          dispatch() setzt PATH                                            (Task 4)
lean_herdr/report.py    + WT_TIMEOUT_S, CHANGE_FLAGS, STAMPED, worktree_stamp;
                          report(..., stamper=); main übergibt worktree_stamp               (Task 3)
tests/test_orders.py, tests/test_ordercmd.py (neu), tests/test_dispatch_await.py,
tests/test_report.py, tests/test_dispatch.py
```

Bestand, auf den die Tasks bauen: `orders._apply` (`lean_herdr/orders.py:96-118`),
`ordercmd.create_order` (`lean_herdr/ordercmd.py:60-96`), `dispatch.build_parser`
(`lean_herdr/dispatch.py:579-638`), `dispatch.missing_flags` (`:681-790`), `dispatch._build`
(`:793-839`), `dispatch.main` (`:842-964`), das Env des `pane split` in `dispatch()` (`:295-315`),
`report.report` (`lean_herdr/report.py:213-244`), `report.main` (`:292-330`).
Test-Muster: `tests/test_orders.py` (`event`, `created`), `tests/test_dispatch_await.py`
(`main_root`, `_one_json_line`), `tests/test_report.py` (`order`), `tests/test_dispatch.py`
(`world`, `req`, `registry`, `_line`, `_no_launch`, `_spy_dispatch`), `tests/doubles.py`
(`FakeProc`, `Completed`, `write_role_fixture`).

## Global Constraints

- Non-Goals: kein Verb `plan`, keine Plan-Lese- oder Zustandslogik (Plan B); keine Templates, kein
  eingebautes Routing für `plan`/`plan-review`, keine Änderung an Rollen-Prompts (Plan C).
- Ein Auftrag ohne Plan-Flags verhält sich unverändert; alle bestehenden Tests bleiben grün.
- CLI-Vertrag: eine JSON-Zeile, `ok`, Exit 0. Unzulässige Plan-Flags ergeben `usage_error`, bevor
  etwas ins Log geschrieben wird.
- `report` bleibt erfolgreich, wenn `wt` scheitert; der Stempel heißt dann `wt_error`.
- Task 1 misst, bevor Task 3 und Task 4 etwas festschreiben. Weicht eine Messung vom erwarteten
  Ergebnis ab, endet Task 1 mit BLOCKED.
- Reihenfolge 1 → 2 → 3 → 4.
- Keine Datei unter `lean_herdr/` über 800 Produktions-LOC; `dispatch.py` stand bei 581 (Task 4 misst).

@phase "task-1"
## Task 1: Messungen — `wt step diff <sha>`, `wt list --format=json`, `PATH` im Pane

**Files:** keine Änderung im Repo. Arbeitsverzeichnis der Messung: `/tmp/lh-measure`.

**Interfaces:** keine. **Produces:** drei gemessene Fakten, festgehalten über
`remember_decision`; Task 3 und Task 4 setzen sie voraus.

### Schritt 1 — Wegwerf-Repo

Jeden Befehl einzeln ausführen:

1. `git init -q -b main /tmp/lh-measure`
2. `git -C /tmp/lh-measure commit -q --allow-empty -m base`
3. `git -C /tmp/lh-measure rev-parse HEAD` — die Ausgabe ist `BASE`.
4. `uv run python -c 'from pathlib import Path; Path("/tmp/lh-measure/committed.txt").write_text("x\n")'`
5. `git -C /tmp/lh-measure add committed.txt`
6. `git -C /tmp/lh-measure commit -q -m committed`
7. `uv run python -c 'from pathlib import Path; Path("/tmp/lh-measure/untracked.txt").write_text("y\n")'`

### Schritt 2 — `wt step diff` mit einem Commit als Ziel

Run: `wt -C /tmp/lh-measure step diff <BASE> -- --name-only`

Expected: genau die zwei Zeilen `committed.txt` und `untracked.txt` (Reihenfolge egal).

### Schritt 3 — `wt list --format=json`

Run: `wt -C /tmp/lh-measure list --format=json`

Expected: JSON mit `items`; der Eintrag mit `"worktree": {"current": true, …}` trägt
`"head": {"sha": "<HEAD von Schritt 1.6>"}` und in `worktree.changes` den Schlüssel
`"untracked": true`; die Schlüssel `staged`, `modified`, `renamed`, `deleted`, `conflicted`
sind vorhanden.

### Schritt 4 — `PATH` im Pane (nur in einer laufenden Herdr-Sitzung, `HERDR_ENV=1`)

1. `uv run python -c 'from pathlib import Path; Path("/tmp/lh-measure/bin").mkdir(exist_ok=True)'`
2. `herdr pane split --direction down --cwd /tmp/lh-measure --env PATH=/tmp/lh-measure/bin:$PATH`
   — `$PATH` expandiert die aufrufende Shell. Aus der JSON-Antwort `result.pane.pane_id` als `PANE`.
3. `herdr pane run <PANE> 'echo LH_PATH=$PATH'` — einfache Quotes: die Shell im Pane expandiert.
4. `herdr pane read <PANE> --source recent --lines 20`
5. `herdr pane close <PANE>`

Expected in Schritt 4.4: eine Zeile, die mit `LH_PATH=/tmp/lh-measure/bin:` beginnt.

### Schritt 5 — Festhalten und Aufräumen

Weicht eine der Erwartungen aus Schritt 2, 3 oder 4 ab: die tatsächliche Ausgabe im Bericht nennen
und mit BLOCKED enden.

Den Aufruf aus Schritt 2 (`wt step diff <sha>`) legt Plan B, Task 6, in `tests/test_llm.py` als Test fest.

@call remember_decision("lean-herdr TP2 measurements: `wt -C <path> step diff <sha>` diffs committed and untracked changes since that commit; `wt list --format=json` marks the current worktree with worktree.current and carries head.sha plus worktree.changes flags; `herdr pane split --env PATH=<bin>:$PATH` keeps <bin> in the pane shell's PATH.")

Run: `uv run python -c 'import shutil; shutil.rmtree("/tmp/lh-measure")'`
@phase-end

@phase "task-2"
## Task 2: Plan-Felder im Auftrag

**Files:** Modify `lean_herdr/orders.py`, `lean_herdr/ordercmd.py`, `lean_herdr/dispatch.py`,
`tests/test_orders.py`, `tests/test_dispatch_await.py`, `tests/test_dispatch.py`.
Create `tests/test_ordercmd.py`.

**Interfaces — Produces:**

    # lean_herdr/orders.py
    PLAN_STEPS = ("plan", "plan-review", "implement", "review")
    PLAN_SLUG_RE = re.compile(r"[a-z][a-z0-9-]{0,11}")
    PLAN_TASK_RE = re.compile(r"[1-9][0-9]*")
    Order.plan: str | None; Order.step: str | None; Order.plan_task: str | None; Order.spec: str | None
    # lean_herdr/ordercmd.py
    OrderRequest.plan / .step / .plan_task / .spec: str | None = None
    def plan_flag_problem(plan: str | None, step: str | None, plan_task: str | None, spec: str | None) -> str | None
    # CLI
    lean-herdr dispatch order --to <agent> --message "…" [--after o-…]
        [--plan <slug> --step plan|plan-review|implement|review [--plan-task N|branch] [--spec <pfad>]]

Regeln von `plan_flag_problem` (Rückgabe wörtlich):

| Lage | Rückgabe |
|---|---|
| alle vier `None` | `None` |
| nur eins von `plan`/`step` | `--plan and --step go together` |
| Slug verfehlt das Muster | `--plan '<slug>' is no plan slug ([a-z][a-z0-9-]{0,11})` |
| unbekannter Schritt | `--step '<step>' is none of plan, plan-review, implement, review` |
| `implement`/`review` ohne `plan_task` | `--step <step> needs --plan-task` |
| `plan_task` weder `branch` noch eine Zahl ≥ 1 ohne führende Null (`PLAN_TASK_RE`) | `--plan-task '<wert>' is neither a task number nor branch` |
| `plan`/`plan-review` mit `plan_task` | `--step <step> does not take --plan-task` |
| `plan` ohne `spec` | `--step plan needs --spec` |
| anderer Schritt mit `spec` | `--step <step> does not take --spec` |

### Schritt 1 — Tests zuerst

`tests/test_orders.py`, nach `test_the_predecessor_is_kept_as_given`:

    def test_the_plan_fields_are_kept_as_given():
        order = fold([created(plan="shop", step="implement", plan_task="3")])
        assert (order.plan, order.step, order.plan_task, order.spec) == ("shop", "implement", "3", None)
        plain = fold([created()])
        assert (plain.plan, plain.step, plain.plan_task, plain.spec) == (None, None, None, None)

`tests/test_ordercmd.py` (neu):

    from pathlib import Path

    import pytest

    from lean_herdr.ordercmd import OrderRequest, create_order, plan_flag_problem
    from lean_herdr.orderlog import read_events, task_ids
    from lean_herdr.orders import fold

    ROOT = Path("/repo")
    WORKER = "builder-plan-shop"
    SLUG = "[a-z][a-z0-9-]{0,11}"


    @pytest.mark.parametrize(
        ("flags", "expected"),
        [
            ((None, None, None, None), None),
            (("shop", "plan", None, "docs/specs/shop-design.md"), None),
            (("shop", "plan-review", None, None), None),
            (("shop", "implement", "3", None), None),
            (("shop", "review", "branch", None), None),
            (("shop", None, None, None), "--plan and --step go together"),
            ((None, "implement", "3", None), "--plan and --step go together"),
            (("Shop", "plan", None, "s.md"), f"--plan 'Shop' is no plan slug ({SLUG})"),
            (("a-slug-far-too-long", "plan", None, "s.md"), f"--plan 'a-slug-far-too-long' is no plan slug ({SLUG})"),
            (("shop", "merge", None, None), "--step 'merge' is none of plan, plan-review, implement, review"),
            (("shop", "implement", None, None), "--step implement needs --plan-task"),
            (("shop", "review", "0", None), "--plan-task '0' is neither a task number nor branch"),
            (("shop", "review", "x", None), "--plan-task 'x' is neither a task number nor branch"),
            (("shop", "review", "03", None), "--plan-task '03' is neither a task number nor branch"),
            (("shop", "implement", "²", None), "--plan-task '²' is neither a task number nor branch"),
            (("shop", "plan", "3", "s.md"), "--step plan does not take --plan-task"),
            (("shop", "plan", None, None), "--step plan needs --spec"),
            (("shop", "implement", "3", "s.md"), "--step implement does not take --spec"),
        ],
    )
    def test_plan_flag_problem(flags, expected):
        assert plan_flag_problem(*flags) == expected


    def test_an_order_carries_its_plan_fields_into_the_log(tmp_path):
        result = create_order(
            OrderRequest(
                to_agent=WORKER, message="Task 3 of plan shop", plan="shop", step="implement", plan_task="3"
            ),
            root=ROOT,
            orders_dir=tmp_path,
        )
        order = fold(read_events(result["task_id"], orders=tmp_path))
        assert (order.plan, order.step, order.plan_task, order.spec) == ("shop", "implement", "3", None)


    def test_bad_plan_flags_write_nothing(tmp_path):
        result = create_order(
            OrderRequest(to_agent=WORKER, message="x", plan="shop"), root=ROOT, orders_dir=tmp_path
        )
        assert result == {"ok": False, "error": "usage_error: --plan and --step go together"}
        assert task_ids(orders=tmp_path) == []

`tests/test_dispatch_await.py`: `task_ids` in den Import aus `lean_herdr.orderlog` aufnehmen; nach
`test_main_routes_from_and_after_through_to_the_event`:

    def test_main_routes_the_plan_fields_through_to_the_event(main_root, capsys):
        code = main(
            [
                "order", "--to", WORKER, "--message", "plan it",
                "--plan", "shop", "--step", "plan", "--spec", "docs/specs/shop-design.md",
            ]
        )
        assert code == 0
        result = _one_json_line(capsys)
        order = fold(read_events(result["task_id"], orders=state_dir(main_root)))
        assert (order.plan, order.step, order.plan_task, order.spec) == (
            "shop", "plan", None, "docs/specs/shop-design.md"
        )


    def test_main_refuses_bad_plan_flags_before_the_log(main_root, capsys):
        main(["order", "--to", WORKER, "--message", "x", "--plan", "shop", "--step", "implement"])
        assert _one_json_line(capsys) == {
            "ok": False,
            "error": "usage_error: --step implement needs --plan-task",
        }
        assert task_ids(orders=state_dir(main_root)) == []


    @pytest.mark.parametrize(
        "argv",
        [
            ["answer", "--task-id", TASK_ID, "--message", "m", "--plan", "shop"],
            ["cancel", "--task-id", TASK_ID, "--message", "m", "--step", "plan"],
            ["remember", "--key", "k", "--message", "m", "--plan-task", "3"],
        ],
    )
    def test_plan_flags_belong_to_order_alone(main_root, capsys, argv):
        main(argv)
        result = _one_json_line(capsys)
        assert result["ok"] is False
        assert "does not take" in result["error"]

`tests/test_dispatch.py`, am Dateiende:

    def test_plan_flags_belong_to_a_log_command(monkeypatch, tmp_path, capsys):
        root = tmp_path / "repo"
        _spy_dispatch(monkeypatch)
        result = _line(
            ["builder", "--kind", "claude", "--model", "sonnet", "--plan", "shop"], root, monkeypatch, capsys
        )
        assert result == {"ok": False, "error": "usage_error: --plan belongs to a log command"}

Run: `uv run pytest -q tests/test_orders.py tests/test_ordercmd.py tests/test_dispatch_await.py tests/test_dispatch.py -k plan`

Expected: FAIL — `ImportError: cannot import name 'plan_flag_problem'` beim Sammeln von
`tests/test_ordercmd.py`; pytest bricht den Lauf dort ab, bevor ein anderer Test läuft.

### Schritt 2 — `orders.py`

@call patch("lean_herdr/orders.py", "the import block, the line after _STATE_OF, the Order fields, and the created branch of _apply")

- Import-Block: `import re` vor `from collections.abc import Iterable` (ruff I001: `import`-Zeilen vor `from`-Zeilen).
- Nach `_STATE_OF` einfügen:

      #: The four steps of a plan run an order can belong to (`dispatch order --step`).
      PLAN_STEPS = ("plan", "plan-review", "implement", "review")

      #: A plan slug. `plan/<slug>` is the branch, and the longest agent name built on it,
      #: `plan-reviewer-plan-<slug>`, has to stay within herdr's 32 characters.
      PLAN_SLUG_RE = re.compile(r"[a-z][a-z0-9-]{0,11}")

      #: A task number on an order: decimal, no leading zero. `str.isdigit` lets "²" through,
      #: and `int("²")` raises.
      PLAN_TASK_RE = re.compile(r"[1-9][0-9]*")

- In `Order` nach `after: str | None = None`:

      #: The plan run this order belongs to; all four None for an order outside a plan.
      #: `plan_task` is a task number as text ("3") or "branch".
      plan: str | None = None
      step: str | None = None
      plan_task: str | None = None
      spec: str | None = None

- Vor `def _apply` einfügen:

      def _text(value: Any) -> str | None:
          """A payload value as text, or None for an absent or empty one."""
          return str(value) if value else None

- Im `created`-Zweig von `_apply`, in `replace(...)` nach `after=str(after) if after else None,`:

      plan=_text(event.payload.get("plan")),
      step=_text(event.payload.get("step")),
      plan_task=_text(event.payload.get("plan_task")),
      spec=_text(event.payload.get("spec")),

### Schritt 3 — `ordercmd.py`

@call patch("lean_herdr/ordercmd.py", "the orders import, the OrderRequest fields, the line before create_order, and the checks plus payload inside create_order")

- `from lean_herdr.orders import fold, is_terminal` → `from lean_herdr.orders import PLAN_SLUG_RE, PLAN_STEPS, PLAN_TASK_RE, fold, is_terminal`
- In `OrderRequest` nach `actor: str = ORCHESTRATOR_AGENT`:

      #: The plan run this order belongs to -- see `plan_flag_problem` for what goes together.
      plan: str | None = None
      step: str | None = None
      plan_task: str | None = None
      spec: str | None = None

- Vor `def create_order` einfügen:

      def plan_flag_problem(
          plan: str | None, step: str | None, plan_task: str | None, spec: str | None
      ) -> str | None:
          """Why these plan fields cannot go on an order -- None when they can.

          All four absent is an order outside a plan. Otherwise `plan` and `step` come
          together, `plan_task` belongs to `implement` and `review` and only to them, and
          `spec` belongs to `plan` and only to it. One producer for `dispatch.missing_flags`
          and `create_order` (M3).
          """
          if plan is None and step is None and plan_task is None and spec is None:
              return None
          if plan is None or step is None:
              return "--plan and --step go together"
          if not PLAN_SLUG_RE.fullmatch(plan):
              return f"--plan {plan!r} is no plan slug ({PLAN_SLUG_RE.pattern})"
          if step not in PLAN_STEPS:
              return f"--step {step!r} is none of {', '.join(PLAN_STEPS)}"
          if step in ("implement", "review"):
              if plan_task is None:
                  return f"--step {step} needs --plan-task"
              if plan_task != "branch" and not PLAN_TASK_RE.fullmatch(plan_task):
                  return f"--plan-task {plan_task!r} is neither a task number nor branch"
          elif plan_task is not None:
              return f"--step {step} does not take --plan-task"
          if step == "plan" and not spec:
              return "--step plan needs --spec"
          if step != "plan" and spec is not None:
              return f"--step {step} does not take --spec"
          return None

- In `create_order` nach der `--message`-Prüfung:

      problem = plan_flag_problem(req.plan, req.step, req.plan_task, req.spec)
      if problem:
          return {"ok": False, "error": f"usage_error: {problem}"}

- In `create_order` nach `payload["after"] = req.after`:

      for key, value in (
          ("plan", req.plan),
          ("step", req.step),
          ("plan_task", req.plan_task),
          ("spec", req.spec),
      ):
          if value is not None:
              payload[key] = value

### Schritt 4 — `dispatch.py`

@call patch("lean_herdr/dispatch.py", "the ordercmd import, the --key argument in build_parser, the order branch plus the line after it in missing_flags, the role-mode stray list in missing_flags, and the OrderRequest in main")

- Import aus `lean_herdr.ordercmd`: `plan_flag_problem` ergänzen.
- In `build_parser` nach `p.add_argument("--key", …)`:

      p.add_argument("--plan", default=None, help="only with `order`: the plan slug this order belongs to")
      p.add_argument(
          "--step", default=None, help="only with `order --plan`: plan | plan-review | implement | review"
      )
      p.add_argument("--plan-task", default=None, help="only with `order --plan`: the task number, or branch")
      p.add_argument("--spec", default=None, help="only with `order --step plan`: the spec to plan")

- In `missing_flags` den `order`-Zweig (`if args.command == "order": …` bis `return f"order needs …"`) ersetzen durch:

      if args.command == "order":
          stray = _given(("--task-id", args.task_id))
          if stray:
              return f"`{args.command}` does not take {stray}"
          missing = [
              flag
              for flag, value in (("--to", args.to), ("--message", args.message))
              if not value
          ]
          if missing:
              return f"order needs {' and '.join(missing)}"
          return plan_flag_problem(args.plan, args.step, args.plan_task, args.spec)
      plan_flags = _given(
          ("--plan", args.plan),
          ("--step", args.step),
          ("--plan-task", args.plan_task),
          ("--spec", args.spec),
      )
      if plan_flags:
          return f"`{args.command}` does not take {plan_flags}"

- In `missing_flags` die Liste der Rollen-Modi (`("--key", args.key),` vor `)` und
  `if stray: return f"{stray} belongs to a log command"`) um vier Zeilen ergänzen:

      ("--plan", args.plan),
      ("--step", args.step),
      ("--plan-task", args.plan_task),
      ("--spec", args.spec),

- In `main` das `OrderRequest(...)` um vier Argumente nach `actor=sender,` ergänzen:

      plan=args.plan,
      step=args.step,
      plan_task=args.plan_task,
      spec=args.spec,

Run: `uv run pytest -q tests/test_orders.py tests/test_ordercmd.py tests/test_dispatch_await.py tests/test_dispatch.py -k plan`

Expected: PASS — `test_the_plan_fields_are_kept_as_given`, `test_plan_flag_problem` (18 Fälle),
`test_an_order_carries_its_plan_fields_into_the_log`, `test_bad_plan_flags_write_nothing`,
`test_main_routes_the_plan_fields_through_to_the_event`,
`test_main_refuses_bad_plan_flags_before_the_log`, `test_plan_flags_belong_to_order_alone` (3),
`test_plan_flags_belong_to_a_log_command`.

@call verify(lean_herdr/orders.py lean_herdr/ordercmd.py lean_herdr/dispatch.py tests/test_orders.py tests/test_ordercmd.py tests/test_dispatch_await.py tests/test_dispatch.py)
@call review_change()
@call py_gate(lean_herdr/orders.py lean_herdr/ordercmd.py lean_herdr/dispatch.py tests/test_orders.py tests/test_ordercmd.py tests/test_dispatch_await.py tests/test_dispatch.py)
@call commit("lean_herdr/orders.py lean_herdr/ordercmd.py lean_herdr/dispatch.py tests/test_orders.py tests/test_ordercmd.py tests/test_dispatch_await.py tests/test_dispatch.py", "feat(order): let an order name the plan, step, task and spec it belongs to")
@phase-end

@phase "task-3"
## Task 3: Stempel in `report start` und `report done`

**Files:** Modify `lean_herdr/report.py`, `lean_herdr/orders.py`, `tests/test_report.py`,
`tests/test_orders.py`.

**Interfaces — Produces:**

    # lean_herdr/report.py
    WT_TIMEOUT_S = 5.0
    CHANGE_FLAGS = ("staged", "modified", "untracked", "renamed", "deleted", "conflicted")
    STAMPED = ("start", "done")
    def worktree_stamp(cwd: str | Path | None = None, *, runner: Any = subprocess.run) -> dict[str, Any]
        # {"head": "<sha>", "changes": ["modified", …]}  oder  {"wt_error": "<grund>"}
    def report(agent, command, task_id, message, *, orders_dir, stamper: Callable[[], Mapping[str, Any]] | None = None) -> dict[str, Any]
    # lean_herdr/orders.py
    Order.start_head: str | None      # head des ersten `working`-Events
    Order.done_head: str | None       # head des `completed`-Events
    Order.done_changes: tuple[str, ...] | None   # None = unbekannt (kein Stempel, wt_error)

**Consumes:** Messung aus Task 1 (Form von `wt list --format=json`).

### Schritt 1 — Tests zuerst

`tests/test_orders.py`, nach `test_the_plan_fields_are_kept_as_given`:

    def test_the_stamps_of_start_and_done_are_kept():
        order = fold(
            [
                created(),
                event("working", seq=2, head="aaa111", changes=[]),
                event("input-required", seq=3, message="which?"),
                event("answered", ORCH, 4, message="this"),
                event("working", seq=5, head="bbb222", changes=[]),
                event("completed", seq=6, message="done", head="ccc333", changes=["modified"]),
            ]
        )
        assert order.start_head == "aaa111", "the first start is the task's base"
        assert order.done_head == "ccc333"
        assert order.done_changes == ("modified",)


    def test_an_order_without_stamps_knows_nothing_about_its_worktree():
        order = fold(
            [created(), event("working", seq=2), event("completed", seq=3, wt_error="wt list exited 1")]
        )
        assert (order.start_head, order.done_head, order.done_changes) == (None, None, None)


    def test_a_head_that_is_no_commit_id_is_no_head():
        """A head reaches `git show <head>:…` and `wt step diff <head>`; `-` there reads as an option."""
        order = fold(
            [
                created(),
                event("working", seq=2, head="--output=/tmp/x", changes=[]),
                event("completed", seq=3, head="HEAD~1", changes=[]),
            ]
        )
        assert (order.start_head, order.done_head) == (None, None)

`tests/test_report.py`: Import-Zeile `from tests.doubles import Completed` →
`from tests.doubles import Completed, FakeProc`; `worktree_stamp` in den Import aus
`lean_herdr.report` aufnehmen; nach `test_an_unknown_order_is_not_found`:

    WT_LIST = {
        "items": [
            {"branch": "main", "head": {"sha": "0000"}, "worktree": {"current": False, "changes": {}}},
            {
                "branch": "plan/shop",
                "head": {"sha": "abc123"},
                "worktree": {
                    "current": True,
                    "changes": {"staged": False, "modified": True, "untracked": True},
                },
            },
        ]
    }


    def test_the_stamp_reads_head_and_set_flags_of_the_current_worktree():
        runner = FakeProc(replies={("list", "--format=json"): WT_LIST})
        assert worktree_stamp(runner=runner) == {"head": "abc123", "changes": ["modified", "untracked"]}
        assert runner.called_with("wt", "list", "--format=json")


    @pytest.mark.parametrize(
        ("reply", "error"),
        [
            (Completed(returncode=1, stderr="not a repo"), "wt list exited 1: not a repo"),
            (Completed(stdout="no json"), "wt list printed no JSON"),
            ({"items": []}, "wt list names no current worktree with a head"),
            ({"items": "none"}, "wt list names no current worktree with a head"),
            ({"items": [{"worktree": "current", "head": {"sha": "abc"}}]}, "wt list names no current worktree with a head"),
            ({"items": [{"worktree": {"current": True}, "head": "abc"}]}, "wt list names no current worktree with a head"),
        ],
    )
    def test_a_stamp_that_cannot_be_taken_is_a_wt_error(reply, error):
        stamp = worktree_stamp(runner=FakeProc(replies={("list", "--format=json"): reply}))
        assert set(stamp) == {"wt_error"}
        assert stamp["wt_error"].startswith(error)


    def test_a_missing_wt_is_a_wt_error_too():
        assert set(worktree_stamp(runner=FakeProc(raises=FileNotFoundError("wt")))) == {"wt_error"}


    @pytest.mark.parametrize(
        ("command", "stamped"), [("start", True), ("done", True), ("fail", False), ("ask", False)]
    )
    def test_start_and_done_carry_the_stamp(tmp_path, command, stamped):
        order(tmp_path, "o-a-1")
        report(
            ME, command, "o-a-1", "a word", orders_dir=tmp_path,
            stamper=lambda: {"head": "abc123", "changes": []},
        )
        payload = read_events("o-a-1", orders=tmp_path)[-1].payload
        assert ("head" in payload) is stamped


    def test_a_refused_report_takes_no_stamp(tmp_path):
        order(tmp_path, "o-a-1", to_agent=OTHER)
        calls = []
        report(ME, "done", "o-a-1", "x", orders_dir=tmp_path, stamper=lambda: calls.append(1) or {})
        assert calls == []

Run: `uv run pytest -q tests/test_orders.py tests/test_report.py`

Expected: FAIL — `ImportError: cannot import name 'worktree_stamp'` beim Sammeln von
`tests/test_report.py`; pytest bricht den Lauf dort ab, bevor ein anderer Test läuft.

### Schritt 2 — `orders.py`

@call patch("lean_herdr/orders.py", "the Order fields after spec, and the non-created return of _apply")

- In `Order` nach `spec: str | None = None`:

      #: `head` of the first `working` event (`report start`), and `head` and `changes` of
      #: the `completed` event (`report done`). `done_changes` None: nothing is known --
      #: no stamp, or a `wt_error` instead of one.
      start_head: str | None = None
      done_head: str | None = None
      done_changes: tuple[str, ...] | None = None

- Nach `_text` einfügen:

      #: A head as `wt list` stamps it. Letters and digits only: the value reaches
      #: `git show <head>:…`, `git log <head>..HEAD` and `wt step diff <head>`, where a
      #: leading `-` would read as an option.
      _COMMIT_RE = re.compile(r"[0-9A-Za-z]{1,64}")


      def _commit(value: Any) -> str | None:
          """A payload head, or None for an absent one and for one no commit id looks like."""
          return value if isinstance(value, str) and _COMMIT_RE.fullmatch(value) else None

- Das abschließende `return replace(order, id=order.id or event.task_id, state=…, messages=messages)`
  von `_apply` ersetzen durch:

      start_head = order.start_head
      if event.kind == "working" and start_head is None:
          start_head = _commit(event.payload.get("head"))
      done_head, done_changes = order.done_head, order.done_changes
      if event.kind == "completed":
          done_head = _commit(event.payload.get("head"))
          changes = event.payload.get("changes")
          done_changes = tuple(str(flag) for flag in changes) if isinstance(changes, list) else None
      return replace(
          order,
          id=order.id or event.task_id,
          state=_STATE_OF.get(event.kind, event.kind),
          messages=messages,
          start_head=start_head,
          done_head=done_head,
          done_changes=done_changes,
      )

### Schritt 3 — `report.py`

@call patch("lean_herdr/report.py", "the collections.abc import, the line after GIT_TIMEOUT_S, the line before def report, the report function, and the report call in main")

- `from collections.abc import Mapping` → `from collections.abc import Callable, Mapping`
- Nach `GIT_TIMEOUT_S = 5.0`:

      #: `wt list` is local and fast; it must not hold up a report.
      WT_TIMEOUT_S = 5.0

      #: The worktree flags a stamp keeps, in this order (`wt list --format=json`,
      #: `worktree.changes`).
      CHANGE_FLAGS = ("staged", "modified", "untracked", "renamed", "deleted", "conflicted")

      #: The two subcommands whose event carries the stamp: `start` fixes the base a review
      #: diffs from, `done` what the worker left behind.
      STAMPED = ("start", "done")

- Vor `def report` einfügen:

      def worktree_stamp(cwd: str | Path | None = None, *, runner: Any = subprocess.run) -> dict[str, Any]:
          """`head` and set `changes` of the worktree this process runs in -- or `wt_error`.

          Read from the entry `wt list --format=json` marks `worktree.current`. Never raises:
          a stamp that cannot be taken is recorded as `wt_error`, and the report goes
          through anyway.
          """
          try:
              proc = runner(
                  ["wt", "list", "--format=json"],
                  cwd=str(cwd) if cwd is not None else None,
                  capture_output=True,
                  text=True,
                  timeout=WT_TIMEOUT_S,
                  check=False,
              )
          except (OSError, subprocess.SubprocessError) as exc:
              return {"wt_error": f"wt list failed: {exc}"}
          if proc.returncode != 0:
              return {"wt_error": f"wt list exited {proc.returncode}: {(proc.stderr or '').strip()}"}
          try:
              data = json.loads(proc.stdout or "")
          except json.JSONDecodeError as exc:
              return {"wt_error": f"wt list printed no JSON: {exc}"}
          # Every level is checked for its shape: a report must not crash on output it did not expect.
          items = data.get("items") if isinstance(data, dict) else None
          current: dict[str, Any] = next(
              (
                  item
                  for item in (items if isinstance(items, list) else [])
                  if isinstance(item, dict)
                  and isinstance(item.get("worktree"), dict)
                  and item["worktree"].get("current") is True
              ),
              {},
          )
          head = current.get("head")
          sha = head.get("sha") if isinstance(head, dict) else None
          if not isinstance(sha, str) or not sha:
              return {"wt_error": "wt list names no current worktree with a head"}
          changes = current["worktree"].get("changes")
          flags = changes if isinstance(changes, dict) else {}
          return {"head": sha, "changes": [flag for flag in CHANGE_FLAGS if flags.get(flag) is True]}

- `report`: Signatur um `stamper: Callable[[], Mapping[str, Any]] | None = None` nach
  `orders_dir: str | Path,` ergänzen und den `append(...)`-Aufruf ersetzen durch:

      payload: dict[str, Any] = {"message": message} if message else {}
      if stamper is not None and command in STAMPED:
          payload.update(stamper())
      event = append(task_id, KIND_OF[command], agent, payload, orders=orders_dir)

- In `main` den `report(...)`-Aufruf um `stamper=worktree_stamp,` nach `orders_dir=orders_dir,` ergänzen.

Run: `uv run pytest -q tests/test_orders.py tests/test_report.py`

Expected: PASS — die neuen Tests und alle bestehenden in beiden Dateien.

@call verify(lean_herdr/report.py lean_herdr/orders.py tests/test_report.py tests/test_orders.py)
@call py_gate(lean_herdr/report.py lean_herdr/orders.py tests/test_report.py tests/test_orders.py)
@call commit("lean_herdr/report.py lean_herdr/orders.py tests/test_report.py tests/test_orders.py", "feat(report): stamp head and worktree changes on start and done")
@phase-end

@phase "task-4"
## Task 4: `dispatch` — Länge des Agent-Namens, `PATH` für Worker

**Files:** Modify `lean_herdr/dispatch.py`, `tests/test_dispatch.py`.

**Interfaces — Produces** (`lean_herdr/dispatch.py`):

    HERDR_NAME_MAX = 32
    WORKER_BIN = Path(".lean-ctx") / "lean-herdr" / "bin"
    # _build: Name länger als HERDR_NAME_MAX →
    #   {"ok": False, "error": "config_error: agent name '<name>' has <n> characters, herdr allows 32"}
    # dispatch(): existiert root / WORKER_BIN, bekommt `pane split` zusätzlich
    #   --env PATH=<root>/.lean-ctx/lean-herdr/bin:<PATH dieses Prozesses>

**Consumes:** Messung aus Task 1 (`PATH` im Pane).

### Schritt 1 — Tests zuerst

`tests/test_dispatch.py`, am Dateiende:

    def test_an_agent_name_over_32_characters_is_refused_before_any_pane(monkeypatch, tmp_path, capsys):
        root = tmp_path / "repo"
        write_role_fixture(root, "builder")
        _no_launch(monkeypatch)
        result = _line(
            ["builder", "--kind", "claude", "--model", "sonnet", "--worktree", "plan/a-slug-far-too-long-x"],
            root,
            monkeypatch,
            capsys,
        )
        assert result == {
            "ok": False,
            "error": "config_error: agent name 'builder-plan-a-slug-far-too-long-x' has 34 characters, herdr allows 32",
        }


    def test_an_agent_name_of_exactly_32_characters_still_dispatches(monkeypatch, tmp_path, capsys):
        root = tmp_path / "repo"
        write_role_fixture(root, "builder")
        seen = _spy_dispatch(monkeypatch)
        result = _line(
            ["builder", "--kind", "claude", "--model", "sonnet", "--worktree", "plan/a-slug-far-too-long"],
            root,
            monkeypatch,
            capsys,
        )
        assert result["ok"] is True
        assert len(seen) == 1


    def test_the_worker_bin_goes_in_front_of_the_panes_path(world, tmp_path, monkeypatch):
        h_proc, path = world
        (tmp_path / ".lean-ctx" / "lean-herdr" / "bin").mkdir(parents=True)
        monkeypatch.setenv("PATH", "/usr/bin")
        path.write_text(json.dumps(registry()), encoding="utf-8")
        dispatch(
            req(), herdr=Herdr(runner=h_proc), root=tmp_path, registry_path=path,
            waiter=lambda *a, **kw: AGENT_ID,
        )
        split = next(c for c in h_proc.calls if c[1:3] == ["pane", "split"])
        assert f"PATH={tmp_path / '.lean-ctx' / 'lean-herdr' / 'bin'}:/usr/bin" in split


    def test_without_a_worker_bin_the_pane_path_is_left_alone(world, tmp_path):
        h_proc, path = world
        path.write_text(json.dumps(registry()), encoding="utf-8")
        dispatch(
            req(), herdr=Herdr(runner=h_proc), root=tmp_path, registry_path=path,
            waiter=lambda *a, **kw: AGENT_ID,
        )
        split = next(c for c in h_proc.calls if c[1:3] == ["pane", "split"])
        assert not any(arg.startswith("PATH=") for arg in split)

Run: `uv run pytest -q tests/test_dispatch.py -k "agent_name_over_32 or agent_name_of_exactly_32 or worker_bin"`

Expected: FAIL — `test_an_agent_name_over_32_characters_is_refused_before_any_pane`: `main` fängt den
`AssertionError` aus `_no_launch`, das Ergebnis trägt `dispatch_crashed: main() reached the launch path
past a config error` statt des `config_error`; `test_the_worker_bin_goes_in_front_of_the_panes_path`:
im `pane split` fehlt `PATH=`. Die Tests für genau 32 Zeichen und ohne bin-Verzeichnis sind schon
vorher grün.

### Schritt 2 — Implementierung

@call patch("lean_herdr/dispatch.py", "the stdlib imports, the line after VERDICT_RE, the env dict of pane_split in dispatch(), and the start of _build after the role_problem check")

- Import-Block: `import os` nach `import json`.
- Nach `VERDICT_RE = …`:

      #: herdr's agent names are `[a-z][a-z0-9_-]{0,31}`: 32 characters at most. A longer
      #: name is refused by herdr after the pane already exists, so `_build` checks first.
      HERDR_NAME_MAX = 32

      #: A project's own binaries for its workers -- `bin/pylsp` for Python. Present, the
      #: directory goes in front of the worker pane's PATH; absent, the PATH stays as it is.
      WORKER_BIN = Path(".lean-ctx") / "lean-herdr" / "bin"

- In `dispatch()` den Block `pane = (herdr.pane_split(…, env={…},) or "")` ersetzen durch:

      env = {
          "LEAN_CTX_TOOL_PROFILE": profile_for(req.role, req.profile, settings=cfg),
          ROLE_ENV: req.role,
          # The worker's own name, so `lean-herdr report` does not have to
          # derive it. Derivation from role plus branch disagrees with
          # this side whenever the dispatch carried no `--worktree`:
          # here the agent is `builder`, there it would be
          # `builder-feat-x`, and an order under the wrong name
          # reaches nobody.
          AGENT_ENV: name,
      }
      bin_dir = root / WORKER_BIN
      if bin_dir.is_dir():
          # Spelled out, not `$PATH`: herdr sets the value as given.
          env["PATH"] = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"
      pane = (
          herdr.pane_split(
              target_cwd,
              pane=target_pane,
              direction=cfg.direction,
              ratio=cfg.ratio,
              focus=cfg.focus,
              env=env,
          )
          or ""
      )

- In `_build` direkt nach `if problem: return {"ok": False, "error": f"config_error: {problem}"}`:

      name = agent_name(args.command, args.worktree, settings=settings)
      if len(name) > HERDR_NAME_MAX:
          return {
              "ok": False,
              "error": (
                  f"config_error: agent name {name!r} has {len(name)} characters, "
                  f"herdr allows {HERDR_NAME_MAX}"
              ),
          }

Run: `uv run pytest -q tests/test_dispatch.py -k "agent_name_over_32 or agent_name_of_exactly_32 or worker_bin"`

Expected: PASS — die vier neuen Tests.

Run: `uv run pytest -q tests/test_dispatch.py`
Expected: PASS — alle bestehenden Tests, u. a. `test_the_pane_carries_the_agent_name_in_its_environment`.

### Schritt 3 — Produktions-LOC messen

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
for name in ("dispatch", "ordercmd", "orders", "report"):
    print(name, prod_loc(f"lean_herdr/{name}.py"))
EOF
```

Expected: jede Zahl ≤ 800; die Zahlen im Bericht nennen.

@call verify(lean_herdr/dispatch.py tests/test_dispatch.py)
@call py_gate(lean_herdr/dispatch.py tests/test_dispatch.py)
@call commit("lean_herdr/dispatch.py tests/test_dispatch.py", "feat(dispatch): refuse agent names over 32 characters and put the worker bin on PATH")
@call remember_decision("lean-herdr TP2 plan A done: dispatch order takes --plan/--step/--plan-task/--spec (ordercmd.plan_flag_problem, Order.plan/step/plan_task/spec); report start/done stamp head and changes via wt list --format=json (report.worktree_stamp, Order.start_head/done_head/done_changes, None = unknown); dispatch refuses agent names over 32 characters and prepends .lean-ctx/lean-herdr/bin to a worker pane's PATH when it exists.")
@phase-end
