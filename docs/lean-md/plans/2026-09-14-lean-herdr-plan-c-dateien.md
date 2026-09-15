# lean-herdr TP2 — Plan C: Dateien

Anhang zu `docs/lean-md/plans/2026-09-14-lean-herdr-plan-c-ausliefern.lmd.md`. Diese Dateien
tragen lean-md-Direktiven (`@define`, `@call`, `@phase`, `@include`). In einer `.lmd.md`-Datei
würde lean-md sie auswerten, auch in Fences; deshalb stehen sie hier, in gewöhnlichem Markdown.
Jede Datei ist der Text zwischen den Fence-Zeilen ihres Abschnitts, byte-genau, mit einem
Zeilenumbruch am Ende.

## `.lean-ctx/lean-md/probe-recipes.lmd.md`

````text
@import .lean-ctx/lean-md/plan-recipes /

@define commit(paths, msg)
<!-- probe override -->
PROBE-COMMIT {{ paths }}
@define-end

@define gate(paths)
<!-- probe override -->
PROBE-GATE {{ paths }}
@define-end
````

## `probe.lmd.md`

````text
@lean-md
consumer: ai

@import .lean-ctx/lean-md/probe-recipes /

@phase "task-1"
## Task 1: probe
@call commit("a.py", "feat: a")
@call gate(a.py)
@call verify(a.py)
@phase-end
````

## `brief.lmd.md`

````text
@lean-md
consumer: ai

@include hard-rules

# Brief: probe

PROBE-BRIEF
````

## `lean_herdr/templates/lean-md/herdr-plan-template.lmd.md`

````text
@lean-md
consumer: ai
crp: compact

@var test_cmd default="{{lean-herdr:test}}" desc="project test runner command"
@var lint_cmd default="{{lean-herdr:lint}}" desc="project lint gate"
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

Run: `{{lean-herdr:test}} tests/test_module.py -k name_adds_one` — Expected: FAIL (`ImportError`).

### Step 2 — implementation

`src/pkg/module.py`:

    def name(arg: int) -> int:
        return arg + 1

Run: `{{lean-herdr:test}} tests/test_module.py -k name_adds_one` — Expected: PASS.

@call verify(src/pkg/module.py tests/test_module.py)
@call gate(src/pkg/module.py tests/test_module.py)
@call commit("src/pkg/module.py tests/test_module.py", "feat: add name")
@phase-end
````

## `lean_herdr/templates/lean-md/herdr-recipes.lmd.md`

````text
# herdr-recipes — lean-herdr's macros for a plan that a lean-herdr run executes
#
# Imported by a plan via:  @import .lean-ctx/lean-md/herdr-recipes /
# It imports plan-recipes and overrides `commit` and `gate`: a worker commits through
# worktrunk with the generator's message, and its gate runs this project's own commands.
# `lean-herdr workspace init` writes this file. Each @define's FIRST body line is its
# description (`lean-md render … --signatures`).

@import .lean-ctx/lean-md/plan-recipes /

@define route(work, lane, files)
<!-- First line of every task: the work that dispatches it, its lane, and every file it touches -->
Route: work `{{ work }}` · lane `{{ lane }}` · files `{{ files }}`
@define-end

@define lane(name, deps)
<!-- One lane of the plan and the lanes it waits for (space-separated; "" for none) -->
- Lane `{{ name }}` — after: `{{ deps }}`
@define-end

@define commit(paths, msg)
<!-- Stage exactly these paths and commit through worktrunk; the generator writes the message -->
Run:
    git add {{ paths }}
    wt step commit --stage none --yes
The commit is about: {{ msg }}
@define-end

@define gate(paths)
<!-- Pre-commit bar: format the paths, lint, the full test suite -->
1. Run: `uv run ruff format {{ paths }}`
2. Run: `{{lean-herdr:lint}}` — Expected: clean.
3. Run: `{{lean-herdr:test}}` — Expected: PASS.
@define-end
````

## `lean_herdr/templates/briefs/implement.lmd.md`

````text
@lean-md
consumer: ai

@include hard-rules

# Brief: implement one task of a lean-herdr plan

You implement exactly ONE task. The task below this brief is the authoritative source — build
precisely what it specifies, nothing more (YAGNI). `## Order` at the end says which round this
is, and carries the findings a later round answers.

## Before you start

- Something is ambiguous, or the task leaves an interface undefined: do not guess. Ask with
  `lean-herdr report ask --task o-… --message "<the specific question>"`.
- The task is too large for one clean TDD cycle, or the plan is wrong: stop with
  `lean-herdr report fail --task o-… --message "<too-large | plan-wrong>: <why>"`.

## How you work

- TDD: the failing test first, run it red, the minimal code, run it green. No production code
  without a failing test first.
- Stay in this worktree. Commit in small steps, through worktrunk only:
  `git add <the paths the task names>`, then `wt step commit --stage none --yes`.
  Never `git commit -m`, never `git add -A`, never push, never merge.
- Before you finish: run the full test suite, then review your own change with `wt step diff`
  — dead code, leftover TODOs, scope creep, missing error handling.
- Follow the patterns of the surrounding code; keep files focused.

## Finish

`lean-herdr report done --task o-… --message "<status block>"`, the message exactly these lines:

    status: DONE | DONE_WITH_CONCERNS
    commits: <sha, sha, …>
    tests: <one line: what ran and passed>
    concerns: <only with DONE_WITH_CONCERNS>

Tracked changes left uncommitted at `done` send you into another round. Files the task did not
name stay untracked — that is expected.
````

## `lean_herdr/templates/briefs/review.lmd.md`

````text
@lean-md
consumer: ai

@include hard-rules

# Brief: review one task of a lean-herdr plan

You review ONE task's change — or, for `task: branch`, the whole branch. Below this brief stand
the plan's Global Constraints, the task and `## Diff`: the command that shows the change, the
commits it holds and the untracked files. Run that command yourself and do not trust any report
— verify every claim against the diff. You write nothing: no file, no commit, not through
`ctx_shell` either.

Produce TWO verdicts from this one diff read.

## Part 1 — Spec compliance

- Missing: what the task requires and the diff does not implement.
- Extra: code beyond the task (scope creep).
- Misunderstood: implemented, but not what the task meant.

## Part 2 — Code quality

- Correctness, error handling, test quality (does the test exercise the behaviour?), naming,
  dead code, and the Global Constraints.

## Calibration

Rate every finding Critical, Important or Minor. What the plan explicitly required
(`plan-mandated`) is no defect. An untracked file is no defect by itself; name one that belongs
in a commit.

## Finish

- Any Critical or Important finding: `VERDIKT: reject`. Otherwise `VERDIKT: result`.
- The verdict is the FIRST line of the message:

      lean-herdr report done --task o-… --message "VERDIKT: result
      <Part 1 and Part 2, every finding with file and line>"

- An open point you cannot settle from the diff: `lean-herdr report ask --task o-… --message "…"`.
- The task contradicts the plan or its Global Constraints:
  `lean-herdr report fail --task o-… --message "plan-conflict: <what>"`.
````

## `lean_herdr/templates/briefs/plan.lmd.md`

````text
@lean-md
consumer: ai

@include hard-rules

# Brief: write a lean-herdr plan

You write ONE implementation plan for the spec named below, on the branch this worktree holds.
Below this brief: the plan's path and branch, the spec, the works a task may route to, and
`## Order` — after a round before, it carries that round's findings; work through every one.

## How you write it

- Use the skill `lmd-writing-plans`, with `.lean-ctx/lean-md/herdr-plan-template.lmd.md` as the
  template instead of the skill's own: copy it to the plan's path and fill it in.
- Required phases: `constraints` (only invariants from the spec) and `lanes` (one
  `@call lane(name, "deps")` per lane), then `task-1` … `task-N` without gaps.
- The FIRST line of every task phase is `@call route(work, lane, "files")`: a work from the list
  below — never a stage (plan, plan-review, review, integrate) —, a declared lane, and every
  file the task touches.
- Python: read `.lean-ctx/lean-md/lang/python.lmd.md` first and follow it.

## Check, commit, finish

1. Commit the plan: `git add <the plan's path>`, then `wt step commit --stage none --yes`.
2. `lean-herdr plan check <slug>` checks the committed state. Fix every entry in `errors`,
   commit again, check again. Warnings are yours to judge.
3. Only once `ok` is true: `lean-herdr report done --task o-… --message "<plan path, task count, open questions>"`.

- The spec is unclear: `lean-herdr report ask`. The spec cannot be planned as written:
  `lean-herdr report fail` with the reason.
- Never push, never merge, never `git commit -m`.
````

## `lean_herdr/templates/briefs/plan-review.lmd.md`

````text
@lean-md
consumer: ai

@include hard-rules

# Brief: review a lean-herdr plan

You review ONE plan before any task of it runs. Below this brief: the plan's path and the
findings of `lean-herdr plan check` on its committed state. Read the plan and the spec it names.
You write nothing: no file, no commit, not through `ctx_shell` either.

## What to check

| Category | What to look for |
|---|---|
| Completeness | TODOs, placeholders, missing steps, a spec requirement no task covers |
| Hidden dependencies | a task that needs what only a later task builds |
| File lists | a route that misses a file its task touches, or names one it does not |
| Conflict hotspots | the same file in several tasks without a reason in the plan |
| Task and lane cut | a task too big for one TDD cycle; lanes that do not match the dependencies |
| Buildability | could an implementer follow each task without getting stuck? |

An anchor to existing code (`@read …`, `@symbol …`, `path:line`) is no placeholder. Every
`errors` entry of `plan check` is a reason to reject.

## Calibration

Only flag what would make an implementer build the wrong thing or get stuck. Wording and style
are not findings.

## Finish

The verdict is the FIRST line of the message:

    lean-herdr report done --task o-… --message "VERDIKT: result
    <findings, each with task and step>"

`VERDIKT: reject` when a finding would make an implementer build the wrong thing or get stuck.
````
