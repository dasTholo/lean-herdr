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
