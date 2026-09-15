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
