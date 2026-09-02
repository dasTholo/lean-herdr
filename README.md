# lean-herdr

A workspace in which a cheap orchestrator agent hands out tasks to stronger
worker agents: orders over the lean-ctx task store (`ctx_task`), findings over
the agent bus, timing over Herdr, isolation over Git worktrees.

Design and measurements: `docs/specs/2026-09-01-lean-herdr-design.md`,
`docs/specs/2026-09-01-lean-herdr-ctx-task-design.md`.

## Runtime dependencies

Herdr installs no toolchains — these things must be present:

| What | What for | Installation |
|---|---|---|
| `herdr` >= 0.8.2 | panes, agents, workspaces | see the Herdr project |
| `lean-ctx` >= 3.10.1 | task store, agent bus, project memory | `cargo install lean-ctx` |
| `uv` | runtime of the Python scripts and handlers | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| `worktrunk` (`wt`) >= 0.75.0 | one worktree per branch, merge, cleanup | `cargo install worktrunk` |
| Herdr plugin `devashish2203/herdr-worktrunk` | binds worktrees to workspaces; needs `fzf` and `jq` | `herdr plugin install devashish2203/herdr-worktrunk` |
| `opencode` >= 1.18.25 | orchestrator and reviewer | see the opencode project |
| Claude Code >= 2.1.252 | builder | see the Claude Code project |

Two approvals in lean-ctx, without which an agent under shell gating can steer
neither Herdr nor worktrunk:

    lean-ctx allow herdr
    lean-ctx allow wt

Plus one approval in worktrunk. Without it `wt` skips the project hooks from
`.config/wt.toml` **silently** and reports success — the pre-merge test gate
would then not run at all:

    wt config approvals list   # expectation: "state": "approved"
    wt config approvals add    # if "approval_required"

Then check — Herdr does not reject unknown plugin events, it only warns:

    herdr plugin list        # expectation: no line with `warning:`

## Bootstrap

The orchestrator does not start itself. Once per workspace:

    herdr pane split --current --direction right --cwd "$PWD" --no-focus \
      --env LEAN_CTX_TOOL_PROFILE=minimal --env LEAN_CTX_ROLE=orchestrator
    herdr agent start orch --kind opencode --pane <id> -- --agent orchestrator

Then resolve the orchestrator's lean-ctx agent_id and enter it in
`roles/builder.md` and `roles/reviewer.md` at the place
`<ORCHESTRATOR_AGENT_ID>` — that is the trust model: a task cannot claim to
come from the orchestrator.

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
