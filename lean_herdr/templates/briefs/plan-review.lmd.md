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
