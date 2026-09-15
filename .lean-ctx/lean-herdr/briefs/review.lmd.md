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
