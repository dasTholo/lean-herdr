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
