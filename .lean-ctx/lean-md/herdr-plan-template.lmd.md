@lean-md
consumer: ai
crp: compact

@var test_cmd default="uv run pytest" desc="project test runner command"
@var lint_cmd default="uv run ruff check" desc="project lint gate"
@import .lean-ctx/lean-md/herdr-recipes /

# <Feature> — lean-herdr plan

Spec: `docs/specs/<date>-<topic>-design.md`

Copy this file to `docs/lean-md/plans/<slug>.lmd.md` on `plan/<slug>` and replace every `<…>`.
A worker renders ONE phase at a time (`lean-md render <plan> --phase task-N`), so everything a
task needs sits inside its phase. `lean-herdr plan check <slug>` holds the committed plan to
the rules: the phases `constraints` and `lanes`, then `task-1` … `task-N` without gaps, and a
route as the first line of every task.

## Goal

<one paragraph: what exists once the last task is merged>

## Architecture

<the files each task creates or changes, and the existing code it builds on>

@phase "constraints"
## Global Constraints

- <only invariants from the spec: non-goals, limits, an order the spec demands>
@phase-end

@phase "lanes"
## Lanes

@call lane(core, "")
@phase-end

@phase "task-1"
@call route(implement, core, "src/pkg/module.py tests/test_module.py")
## Task 1: <name>

**Files:** Create `src/pkg/module.py`, `tests/test_module.py`.

**Interfaces — Produces:** `def name(arg: int) -> int`

### Step 1 — failing test

`tests/test_module.py`:

    from pkg.module import name


    def test_name_adds_one():
        assert name(1) == 2

Run: `uv run pytest tests/test_module.py -k name_adds_one` — Expected: FAIL (`ImportError`).

### Step 2 — implementation

`src/pkg/module.py`:

    def name(arg: int) -> int:
        return arg + 1

Run: `uv run pytest tests/test_module.py -k name_adds_one` — Expected: PASS.

@call verify(src/pkg/module.py tests/test_module.py)
@call gate(src/pkg/module.py tests/test_module.py)
@call commit("src/pkg/module.py tests/test_module.py", "feat: add name")
@phase-end
