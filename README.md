# lean-herdr

A workspace in which a cheap orchestrator agent hands out work to stronger
worker agents: orders over an event log of our own, findings over the agent
bus, timing over Herdr, isolation over Git worktrees.

Design and measurements: `docs/specs/2026-09-01-lean-herdr-design.md`,
`docs/specs/2026-09-03-lean-herdr-auftragslog-design.md`.

## Runtime dependencies

Herdr installs no toolchains — these things must be present:

| What | What for | Installation |
|---|---|---|
| `herdr` >= 0.8.0 (measured on 0.8.2 in this tree) | panes, agents, workspaces | see the Herdr project |
| `lean-ctx` >= 3.10.1 | agent bus, project memory, tool profiles | `cargo install lean-ctx` |
| `uv` | development: test runner and dev dependencies | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| `python3` | runtime of the plugin handlers | your distribution |
| `worktrunk` (`wt`) >= 0.75.0 | one worktree per branch, merge, cleanup | `cargo install worktrunk` |
| Herdr plugin `devashish2203/herdr-worktrunk` | binds worktrees to workspaces; needs `fzf` and `jq` | `herdr plugin install devashish2203/herdr-worktrunk` |
| `opencode` >= 1.18.25 | orchestrator and reviewer | see the opencode project |
| Claude Code >= 2.1.252 | builder | see the Claude Code project |

Three approvals in lean-ctx, without which an agent under shell gating can
steer neither Herdr nor worktrunk nor its own order path:

    lean-ctx allow herdr
    lean-ctx allow wt
    lean-ctx allow lean-herdr

`lean-herdr` needs its own line now. The gate normalises a command to its
basename before comparing, and until this change the CLIs lived inside the
project root, where a script is carried by its path rather than by the
allowlist. On the PATH that exemption is gone -- and it was never a
property worth relying on.

Plus one approval in worktrunk. Without it `wt` skips the project hooks from
`.config/wt.toml` **silently** and reports success — the pre-merge test gate
would then not run at all:

    wt config approvals list   # expectation: "state": "approved"
    wt config approvals add    # if "approval_required"

Plus the commit generator, in worktrunk's **user** config. This one file is
not optional bookkeeping: without `[commit.generation]` worktrunk writes
`Changes to a.txt` from the file names, and that is the message the
orchestrator's `wt step squash` then carries into `main`.

    # ~/.config/worktrunk/config.toml
    [commit]
    stage = "none"          # shared by step commit, step squash AND merge

    [commit.generation]
    command = "/home/you/Scripts/lean-herdr/bin/herdr-llm generate"

`stage` sits under `[commit]`, not at the top level — a bare `stage = "none"`
is reported as *"User config has unknown field stage (will be ignored)"* and
does nothing (measured on worktrunk 0.76.0). Being user config, it is
machine-wide: `wt step commit`, `wt step squash` and `wt merge` stop staging
for you in **every** repository. The direction is the safe one — they commit
what you staged and never more — but it is a habit change everywhere, not
just here.

**The path is absolute, never `bin/herdr-llm`.** That file governs every
repository on the machine; a relative path would run into `sh: not found`
(exit 127) everywhere else, and a failing generation command is fatal, not a
silent fallback — it would break `wt step commit` and `wt merge` in all your
other projects. The generator is repo-agnostic: it only formats what
worktrunk hands it on stdin, so one absolute path serves every repository
sensibly.

worktrunk also knows `[projects."<id>"]` blocks. Whether
`commit.generation.command` is allowed inside one is untested; if it were, the
generator could be scoped to this repository instead of the whole machine.
The absolute path works either way and stays the recommendation.

The key is read from `$OPENROUTER_API_KEY`, else from opencode's own store at
`~/.local/share/opencode/auth.json`. With neither, commits fall back to file
names and nothing breaks.

    export OPENROUTER_API_KEY=<your key>

Which model, and how hard it thinks, is configured per project in
`.config/lean-herdr.toml` under `[llm]` — the same file the role settings
live in. For the commit generator: `--model` beats `$LEAN_HERDR_LLM_MODEL`,
which beats `[llm].model`, which beats the built-in; `--effort` beats
`[llm].effort`, which beats the built-in `minimal`. The pre-review judge has
keys of its own — see the work-order section. A broken or absent file costs
the defaults, never the commit.

**The new attack surface, named:** the builder may now run a command that
sends the contents of its worktree to a third-party service. That was already
true of every agent in this project, but here without a model in between that
could refuse. In a repository with secrets in it, do not configure the
generator.

Then check — Herdr does not reject unknown plugin events, it only warns:

    herdr plugin list        # expectation: no line with `warning:`

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

    # .config/lean-herdr.toml -- the durable place
    [llm]
    model = "google/gemini-3.8-flash"   # both
    prereview_model = ""                # the judge only; empty: share `model`
    prereview_effort = "low"            # the judge thinks harder than the formatter

    # or ad hoc, for one pane, without touching a file every repo reads
    export LEAN_HERDR_PREREVIEW_MODEL=<something stronger>

Precedence for the judge's model: `--model` on the CLI, then
`$LEAN_HERDR_PREREVIEW_MODEL`, then `[llm].prereview_model`, then
`$LEAN_HERDR_LLM_MODEL`, then `[llm].model`, then the built-in default.
For its effort: `--effort`, then `[llm].prereview_effort`, then the built-in
`low` — three levels, and no environment one for either mode's effort. It
deliberately does NOT fall back to `[llm].effort`: that one is the commit
generator's `minimal`, and inheriting it would make the judge as thoughtless
as the formatter. Raising only the shared `model` to raise the judge would
raise the commit generator's bill on every single commit.

The same judgement by hand, without creating an order:

    bin/herdr-llm prereview -C <worktree> --order "<what it was supposed to do>"

Exit 1 on a rejection, and on nothing else -- 0 on `pass` and on `skipped`,
including the `skipped` a failure of its own machinery produces. Leave
`--order` out and it declines to judge at all: an empty order would invite a
rejection on a branch nobody described.

## What else ships here

- `herdr-plugin.toml` — the Herdr plugin: it shows the lean-ctx context per
  pane and workspace, carries it across server restarts, and offers the
  one-keystroke orchestrator bootstrap. Register it with `herdr plugin link`.
- `.opencode/plugins/lean-ctx-policy.js` — the policy adapter that runs the
  Claude-Code hooks inside opencode, so both agent runtimes obey the same
  tool discipline. It searches the project's own `.claude/hooks` first,
  then `~/.claude/hooks`; `$LEAN_HERDR_HOOKS_DIR`, when set, overrides
  both and searches only that one directory.

## Bootstrap

The orchestrator does not start itself. Once per Herdr server — the
duplicate check in `handlers.py` reads `herdr agent list`, which is
server-wide, not per workspace:

    herdr pane split --current --direction right --cwd "$PWD" --no-focus \
      --env LEAN_CTX_TOOL_PROFILE=minimal --env LEAN_CTX_ROLE=orchestrator
    herdr agent start orch --kind opencode --pane <id> -- --agent orchestrator

`orch` is the trust anchor: `lean-herdr dispatch order`, `answer` and
`cancel` stamp that name as the sender from the constant
`ORCHESTRATOR_AGENT` — never from the pane name — and `roles/builder.md`
and `roles/reviewer.md` carry the line `ORCHESTRATOR = orch`. Start the
pane under another name and the constant still stamps `orch`: pass
`--from <name>` on every `order`, `answer` and `cancel` call, and set
`ORCHESTRATOR = <name>` in both role files. The two must agree, or every
order is refused.

That rename turns one test red:
`tests/test_roles.py::test_the_role_prompts_trust_the_name_dispatch_actually_stamps`
holds the `ORCHESTRATOR = …` line of both role files against the constant
`dispatch.ORCHESTRATOR_AGENT`, and the rename moves only the role files.
Either rename the anchor itself — `ORCHESTRATOR["name"]` in
`lean_herdr/handlers.py`, which the constant is imported from — and then
the test is green again and no `--from` is needed at all; or keep
`--from` and accept that one red test for as long as the rename lasts. Do
not "fix" it by loosening the test: it is the only guard that the sender
the workers trust and the sender dispatch stamps are the same string.

Unlike the `ctx_task` path this replaced, the name is a claim, not a proof:
the log stamps what the writer passes. The rule catches a stray order, not a
determined one.

## Configuration

`.config/lean-herdr.toml` ships fully commented out: without an edit the
project behaves exactly as it does without the file. Precedence is
**CLI flag > file > built-in default**; `[default]` applies to every role,
`[roles.<role>]` beats `[default]`.

An unknown key, a wrong direction or a `name_template` without `{role}` and
`{branch}` are errors and are reported — never silently reset to the default.

## Development

    uv sync --dev
    uv run pytest -q

Tests with `-m integration` need real binaries and do not run in CI.
