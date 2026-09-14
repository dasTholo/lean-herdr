# lean-herdr

A workspace in which a cheap orchestrator agent hands out work to stronger
worker agents: orders over an event log of our own, findings over the agent
bus, timing over Herdr, isolation over Git worktrees.

Installing it, keeping it current and working on this repository:
[INSTALL.md](INSTALL.md).

## How it works

Three roles, each an agent in a Herdr pane of its own:

| Role | Runtime as set up here | Job |
|---|---|---|
| orchestrator | opencode, a cheap model | takes the task from you, hands out orders, merges -- writes no code, reads no project files |
| builder | Claude Code | carries out one order in a worktree of its own |
| reviewer | opencode, another model than the builder's | rules on the builder's branch: `result` or `reject` |

One task, start to finish:

1. `lean-herdr workspace up` starts the orchestrator in this repository's
   Herdr workspace. You give it the task in its terminal.
2. It builds a worker with `lean-herdr dispatch --work implement --worktree <branch>`:
   `[routing]` in the config names the role for that work -- the builder,
   unless you route it elsewhere. worktrunk creates the worktree, Herdr opens
   a workspace on it, and the agent starts in a pane there.
3. It writes the order into the event log (`lean-herdr dispatch order`) and
   waits with `--await`. The wait runs inside the script, not inside the
   model, so a long run costs the orchestrator one step. The worker takes its
   order and reports back with `lean-herdr report`; a question comes back as
   `input_required` and gets a `dispatch answer`.
4. On request a small model pre-reviews the diff (`--prereview`). It can send
   the builder into a second round before any reviewer is built -- it can
   reject, never approve.
5. The reviewer runs on the same branch (`--work review`). On `result` the orchestrator
   squashes, closes the worktree's workspace and merges into `main` with
   `wt merge`, whose pre-merge gate runs the project's test and lint
   commands. The commit message comes from `lean-herdr llm generate`.
   Pushing stays with you.
6. Once the branch is done, one or two sentences about it go into lean-ctx's
   project memory (`lean-herdr dispatch remember`).

Two rejections, an agent error or a failed gate end in an escalation to you,
not in a retry. lean-ctx gives both agent runtimes the same tool discipline;
the Herdr plugin shows each pane's context and starts the orchestrator with
one keystroke. Which runtime and model each role gets is set in
`.lean-ctx/lean-herdr/config.toml`, see [Configuration](#configuration).

## The work-order path

Orders live in an append-only, hash-chained event log under
`<lean-ctx data dir>/lean-herdr/<repo>/orders/`. Every process writes; no
registration, no MCP identity, no cleanup. The orchestrator drives it with

    lean-herdr dispatch order    --to <agent> [--after o-…] --message "…"
    lean-herdr dispatch answer   --task-id o-… --message "…"
    lean-herdr dispatch cancel   --task-id o-… --message "…"
    lean-herdr dispatch remember --key lean-herdr/<branch> --message "…"

and the worker answers with

    lean-herdr report next | show | start | done | fail | ask

Nothing removes an order. A non-terminal one left lying is the evidence
that a run broke off; `cancel` closes it.

The wait call for a builder takes `--prereview`. A small model then reads the
branch diff -- `wt step diff`: committed, staged, unstaged and untracked
against the merge base, exactly what `wt merge` would take -- and answers in
the same JSON line, beside `verdict`:

    {"ok": true, "state": "completed", "prereview": "reject",
     "prereview_note": "new logic in parse_row() with no test beside it"}

Only `reject` changes anything. `pass` and `skipped` are the same to the
orchestrator: the strong reviewer runs either way. Every failure of the
pre-review itself -- no key, timeout, an unresolvable worktree -- is
`skipped` with a reason, never a rejection.

`--timeout-ms` does not cover the pre-review. The judgement runs only where
the wait ended in `completed` -- a run that hits the timeout never reaches it
-- and it then carries timeouts of its own: 30 seconds for `wt step diff`, 60
for the judgement. So a `completed` answer can take up to 90 seconds longer
than `--timeout-ms` alone suggests, and a timed-out one exactly as long as
before.

The judge may run on a model of its own. The two jobs are not the same one:
the commit generator formats a diffstat and is happy with the smallest model
there is, the judge reads code.

    # .lean-ctx/lean-herdr/config.toml -- the durable place
    [llm]
    model = "google/gemini-3.8-flash"   # both
    prereview_model = ""                # the judge only; empty: share `model`
    prereview_effort = "low"            # the judge thinks harder than the formatter

    # or ad hoc, for one pane, without touching a file every repo reads
    export LEAN_HERDR_PREREVIEW_MODEL=<something stronger>

Precedence for the judge's model: `--model` on the CLI, then
`$LEAN_HERDR_PREREVIEW_MODEL`, then `[llm].prereview_model`, then
`$LEAN_HERDR_LLM_MODEL`, then `[llm].model`, then the same key in
`models.auto.toml` beside the config, then the built-in default.
For its effort: `--effort`, then `[llm].prereview_effort`, then the built-in
`low` — three levels, and no environment one for either mode's effort. It
deliberately does NOT fall back to `[llm].effort`: that one is the commit
generator's `minimal`, and inheriting it would make the judge as thoughtless
as the formatter. Raising only the shared `model` to raise the judge would
raise the commit generator's bill on every single commit.

The same judgement by hand, without creating an order:

    lean-herdr llm prereview -C <worktree> --order "<what it was supposed to do>"

Exit 1 on a rejection, and on nothing else -- 0 on `pass` and on `skipped`,
including the `skipped` a failure of its own machinery produces. Leave
`--order` out and it declines to judge at all: an empty order would invite a
rejection on a branch nobody described.

## Keeping the model current

`[llm].model` can be kept current from OpenRouter's catalogue: the cheapest
model that can reason and clears the floors you set.

    lean-herdr models list     # what would qualify, cheapest first
    lean-herdr models check    # the winner, and what runs today
    lean-herdr models apply    # write it

`apply` writes `.lean-ctx/lean-herdr/models.auto.toml`, which loses to
`[llm]` in `config.toml`: an explicit `model` there survives every check,
and `apply` rewrites a broken overlay. The file is machine-local, and so are
the temp files its writer and the template lock's writer leave after a hard
kill -- add both lines to `.gitignore`:

    .lean-ctx/lean-herdr/models.auto.toml
    .lean-ctx/lean-herdr/.tmp-*

With `[models].auto = true`, `lean-herdr workspace up` does the same by
itself, at most once every `max_age_h`, after the orchestrator is already
running and never blocking it. Without that key -- the default -- `up`
fetches nothing and writes nothing. A candidate must support both efforts
the two jobs resolve to, and a model with no
`benchmarks.artificial_analysis` block does not clear an index floor:
missing evidence is not a pass.

## What else ships here

- `lean_herdr/plugin/herdr-plugin.toml` — the Herdr plugin: it shows the
  lean-ctx context per pane and workspace, carries it across server restarts,
  and offers the one-keystroke orchestrator bootstrap. It ships inside the
  package, so code and manifest come out of one snapshot. Linking it is an
  install step: [INSTALL.md](INSTALL.md#the-herdr-plugins).
- `.opencode/plugins/lean-ctx-policy.js` — the policy adapter that runs the
  Claude-Code hooks inside opencode, so both agent runtimes obey the same
  tool discipline. It searches the project's own `.claude/hooks` first,
  then `~/.claude/hooks`; `$LEAN_HERDR_HOOKS_DIR`, when set, overrides
  both and searches only that one directory.
- `lean_herdr/templates/` -- everything `lean-herdr workspace init` writes
  into a project. The copies in this repository are copies of exactly
  these files, and `tests/test_templates.py` keeps them byte-identical.

## Setting up a project

In a repository that has never seen lean-herdr:

    lean-herdr workspace init

It writes ten files -- the config, the three role prompts and two claude role settings under
`.lean-ctx/lean-herdr/`, and `opencode.jsonc`, `.claude/settings.json`,
`.config/wt.toml` and `.opencode/plugins/lean-ctx-policy.js` where their
owners look for them. An existing file is skipped and named in the result;
`--force` overwrites. It needs a git repository and does not create one.

Three of the ten carry this project's own commands: `.config/wt.toml` runs
them as the pre-merge gate, and `.claude/settings.json` and `opencode.jsonc`
let the builder run the same two first. Name them on the first run:

    lean-herdr workspace init --test "cargo test" --lint "cargo clippy"

Without the flags the gate is `uv run pytest` and `uv run ruff check`. A value
is a whole command of letters, digits, spaces and `._/=+,@-`; how far it opens
the builder's gate is your call.

A claude worker also gets `--settings .lean-ctx/lean-herdr/claude/<role>.json`
beside `.claude/settings.json`. Claude Code merges the permission lists of
every source and a `deny` beats every `allow`, so a role file can only
narrow: `builder.json` is empty, `reviewer.json` takes back the editors,
`git add`, `git commit`, `wt step commit` and lean-ctx's three write tools.
An opencode worker gets the same per role from its block in
`opencode.jsonc`. `dispatch` refuses a role whose prompt, opencode block or
claude file is missing, before it opens a worktree or a pane.

`init` records what it wrote in `.lean-ctx/lean-herdr/templates.lock.json` --
commit it, like the role prompts. With it, `lean-herdr workspace init --update`
rewrites only the files nobody edited since, and leaves a hand edit where it
is, naming it. `--force` and `--update` exclude each other. The lock's writer
needs the ignore line for its temp file:

    .lean-ctx/lean-herdr/.tmp-*

`lean-herdr workspace check` answers, without starting or writing anything,
whether `up` and `dispatch` will run here and what gets quietly worse: the
config, each template's state, the install, the plugin link, the commit
generator and the ignore rules.

It also spends one aborted opencode bootstrap in the project, up to eight
seconds. opencode's first bootstrap in a project that carries a project
plugin hangs -- and one of the ten files is such a plugin. The aborted
run is the cure: every start after it takes about three seconds. The
result reports it as `warmed` once the warm-up RAN -- not that it
succeeded: a project whose `opencode.jsonc` never named the orchestrator
agent exits at once and still reports `true`. It is `false` when there is
no `opencode` on PATH, when `[roles.orchestrator].kind` is not `opencode`,
or when the run itself could not start.

What it does NOT do is repair your machine. The three lean-ctx approvals,
the worktrunk hook approval and the Herdr plugin registration are reported
as `warnings` and stay yours to grant; [INSTALL.md](INSTALL.md) names each one.

## Bootstrap

The orchestrator does not start itself. Once per Herdr server — the
duplicate check reads `herdr agent list`, which is server-wide, not per
workspace:

    lean-herdr workspace up

It reads `[workspace]` and `[roles.orchestrator]` from
`.lean-ctx/lean-herdr/config.toml`, finds or creates the workspace for
this repository, splits a pane and starts the agent in it. Called twice it
answers `already_running` and changes nothing. The keystroke
"Start the orchestrator in this workspace" in a running Herdr runs the
same code — it only skips the find-or-create step, so the pane lands in
the workspace the key was pressed in.

`orch` is the trust anchor: `lean-herdr dispatch order`, `answer` and
`cancel` stamp that name as the sender from the constant
`ORCHESTRATOR_AGENT` — never from the pane name — and
`.lean-ctx/lean-herdr/roles/builder.md` and
`.lean-ctx/lean-herdr/roles/reviewer.md` carry the line
`ORCHESTRATOR = orch`. Start the pane under another name and the constant
still stamps `orch`: pass `--from <name>` on every `order`, `answer` and
`cancel` call, and set `ORCHESTRATOR = <name>` in both role files. The two
must agree, or every order is refused.

That rename turns one test red:
`tests/test_roles.py::test_the_role_prompts_trust_the_name_dispatch_actually_stamps`
holds the `ORCHESTRATOR = …` line of both role files against the constant
`dispatch.ORCHESTRATOR_AGENT`, and the rename moves only the role files.
Either rename the anchor itself — `ORCHESTRATOR_AGENT` in
`lean_herdr/settings.py`, which the constant is imported from — and then
the test is green again and no `--from` is needed at all; or keep
`--from` and accept that one red test for as long as the rename lasts. Do
not "fix" it by loosening the test: it is the only guard that the sender
the workers trust and the sender dispatch stamps are the same string.

Unlike the `ctx_task` path this replaced, the name is a claim, not a proof:
the log stamps what the writer passes. The rule catches a stray order, not a
determined one.

## Configuration

`.lean-ctx/lean-herdr/config.toml` ships fully commented out: without an
edit the project behaves exactly as it does without the file. Precedence is
**CLI flag > file > built-in default**; `[default]` applies to every role,
`[roles.<role>]` beats `[default]`.

Six sections: `[routing]` names the role behind each kind of work, `[default]` and
`[roles.<role>]` describe how a pane is
split, `[llm]` the commit generator and the pre-review judge, and
`[workspace]` the pane `lean-herdr workspace up` opens for the
orchestrator — `label` alone, and that one optional. `[models]` decides
whether `workspace up` may keep `[llm].model` current from OpenRouter's
catalogue by itself; see [Keeping the model current](#keeping-the-model-current).

Which model, and how hard it thinks, is configured per project in
`.lean-ctx/lean-herdr/config.toml` under `[llm]` — the same file the role
settings live in. For the commit generator: `--model` beats
`$LEAN_HERDR_LLM_MODEL`, which beats `[llm].model`, which beats the same key
in `models.auto.toml` beside it, which beats the built-in; `--effort` beats
`[llm].effort`, which beats the built-in `minimal`. The pre-review judge has
keys of its own — see the work-order section. `models.auto.toml` is what
`lean-herdr models` writes, and it loses to every line an operator wrote by
hand. A broken `models.auto.toml` costs the overlay alone, a broken `config.toml` the defaults -- neither costs the commit.

Which model and which runtime each role gets is configured per role, in
`[roles.orchestrator]`, `[roles.builder]` and `[roles.reviewer]`:

    [roles.builder]
    kind  = "claude"
    model = "sonnet"

    [roles.reviewer]
    kind  = "opencode"
    model = "<a different one>"   # different blind spots is the point
    # shares_reviewed_model = true # confirm the same model on purpose

`shares_reviewed_model` belongs to the role behind `review` and silences the
warning for every role it reviews. It used to be called
`shares_builder_model`; that name is an unknown key now, and a config
carrying it fails with `config_error:` until the line is renamed.

`--kind` and `--model` on a `dispatch` call beat the file; with neither,
`dispatch` refuses to build. A worker quietly running on its runtime's
default model costs real money and nobody sees it. The orchestrator is the
one exception, and only where it is started: an empty `model` means no
`--model` at all for `lean-herdr workspace up` and for the keystroke, which
is what the keystroke has always done. `dispatch orchestrator` is not a
start and has no such exception — it needs `--model` or a set `model`.

Which role does which kind of work is set in `[routing]`. Without the table
the two built-in works apply -- `implement` goes to `builder`, `review` to
`reviewer` -- and a work of your own needs a line and a role:

    [routing]
    rename = "refactorer"

    [roles.refactorer]
    kind  = "opencode"
    model = "<a model>"

`lean-herdr dispatch --work rename` then builds the `refactorer` with
`.lean-ctx/lean-herdr/roles/refactorer.md`; an opencode role also needs its
block under `agent` in `opencode.jsonc`, a claude role its
`.lean-ctx/lean-herdr/claude/refactorer.json`. `plan`, `plan-review` and
`integrate` are reserved and have no built-in role yet: a call without a
`[routing]` line for one is `config_error: no role for work 'plan'`. A work
is spelled `[a-z][a-z0-9-]*`, a role `[a-z][a-z0-9_-]*`.
`lean-herdr workspace check` names every work whose role lacks its prompt,
its runtime, its file or a sentence the worker cannot run without.

An unknown key, a wrong direction or a `name_template` without `{role}` and
`{branch}` are errors and are reported — never silently reset to the default.
