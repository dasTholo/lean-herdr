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
| `herdr` >= 0.8.0 | panes, agents, workspaces | see the Herdr project |
| `lean-ctx` >= 3.10.1 | agent bus, project memory, tool profiles | `cargo install lean-ctx` |
| `uv` | development: test runner and dev dependencies | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| `python3` | runtime of the plugin handlers and both CLIs | your distribution |
| `worktrunk` (`wt`) >= 0.75.0 | one worktree per branch, merge, cleanup | `cargo install worktrunk` |
| Herdr plugin `devashish2203/herdr-worktrunk` | binds worktrees to workspaces; needs `fzf` and `jq` | `herdr plugin install devashish2203/herdr-worktrunk` |
| `opencode` >= 1.18.25 | orchestrator and reviewer | see the opencode project |
| Claude Code >= 2.1.252 | builder | see the Claude Code project |

Three approvals in lean-ctx, without which an agent under shell gating can
steer neither Herdr nor worktrunk, and cannot fetch its own orders:

    lean-ctx allow herdr
    lean-ctx allow wt
    lean-ctx allow bin/herdr-report

Without the third one a lean-ctx-bound worker cannot fetch its order, and
the failure is silent: the orchestrator sees nothing and runs into
`no_reply`.

Plus one approval in worktrunk. Without it `wt` skips the project hooks from
`.config/wt.toml` **silently** and reports success — the pre-merge test gate
would then not run at all:

    wt config approvals list   # expectation: "state": "approved"
    wt config approvals add    # if "approval_required"

Then check — Herdr does not reject unknown plugin events, it only warns:

    herdr plugin list        # expectation: no line with `warning:`

## The work-order path

Orders live in an append-only, hash-chained event log under
`<lean-ctx data dir>/lean-herdr/<repo>/orders/`. Every process writes; no
registration, no MCP identity, no cleanup. The orchestrator drives it with

    bin/herdr-dispatch order   --to <agent> [--after o-…] --message "…"
    bin/herdr-dispatch answer  --task-id o-… --message "…"
    bin/herdr-dispatch cancel  --task-id o-… --message "…"
    bin/herdr-dispatch remember --key lean-herdr/<branch> --message "…"

and the worker answers with

    bin/herdr-report next | show | start | done | fail | ask

Nothing removes an order. A non-terminal one left lying is the evidence
that a run broke off; `cancel` closes it.

## What else ships here

- `herdr-plugin.toml` — the Herdr plugin: it shows the lean-ctx context per
  pane and workspace, carries it across server restarts, and offers the
  one-keystroke orchestrator bootstrap. Register it with `herdr plugin link`.
- `.opencode/plugins/lean-ctx-policy.js` — the policy adapter that runs the
  Claude-Code hooks from `$LEAN_HERDR_HOOKS_DIR` (default `~/.claude/hooks`)
  inside opencode, so both agent runtimes obey the same tool discipline.

## Bootstrap

The orchestrator does not start itself. Once per Herdr server — the
duplicate check in `handlers.py` reads `herdr agent list`, which is
server-wide, not per workspace:

    herdr pane split --current --direction right --cwd "$PWD" --no-focus \
      --env LEAN_CTX_TOOL_PROFILE=minimal --env LEAN_CTX_ROLE=orchestrator
    herdr agent start orch --kind opencode --pane <id> -- --agent orchestrator

`orch` is the trust anchor: `bin/herdr-dispatch order` stamps that name as
the sender, and `roles/builder.md` and `roles/reviewer.md` carry the line
`ORCHESTRATOR = orch`. Start the pane under another name and both role files
have to name it too — nothing resolves it for you.

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
