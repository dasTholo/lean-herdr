# Installing lean-herdr

What a machine needs before `lean-herdr` does anything, how to keep the
installed snapshot current, and how to work on this repository. Using it --
setting up a project, the bootstrap, the work-order path -- is in
[README.md](README.md).

## Runtime dependencies

Herdr installs no toolchains — these things must be present:

| What | What for | Installation |
|---|---|---|
| `lean-herdr` (this project) | one binary, six verbs: dispatch, llm, models, plugin, report, workspace | `uv tool install --reinstall "lean-herdr @ git+file:///home/tholo/Scripts/lean-herdr@main"` — a snapshot of `main`, see [Updating](#updating) |
| `herdr` >= 0.8.0 (measured on 0.8.2 in this tree) | panes, agents, workspaces | see the Herdr project |
| `lean-ctx` >= 3.10.1 | agent bus, project memory, tool profiles | `cargo install lean-ctx` |
| `uv` | development: test runner and dev dependencies | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| `python3` | runs the Claude-Code hooks of the policy adapter | your distribution |
| `worktrunk` (`wt`) >= 0.75.0 | one worktree per branch, merge, cleanup | `cargo install worktrunk` |
| Herdr plugin `devashish2203/herdr-worktrunk` | binds worktrees to workspaces; needs `fzf` and `jq` | `herdr plugin install devashish2203/herdr-worktrunk` |
| `opencode` >= 1.18.25 | orchestrator and reviewer | see the opencode project |
| Claude Code >= 2.1.252 | builder | see the Claude Code project |

## Approvals

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

## The commit generator

The commit generator lives in worktrunk's **user** config. This one file is
not optional bookkeeping: without `[commit.generation]` worktrunk writes
`Changes to a.txt` from the file names, and that is the message the
orchestrator's `wt step squash` then carries into `main`.

    # ~/.config/worktrunk/config.toml
    [commit]
    stage = "none"          # shared by step commit, step squash AND merge

    [commit.generation]
    command = "lean-herdr llm generate"

`stage` sits under `[commit]`, not at the top level — a bare `stage = "none"`
is reported as *"User config has unknown field stage (will be ignored)"* and
does nothing (measured on worktrunk 0.76.0). Being user config, it is
machine-wide: `wt step commit`, `wt step squash` and `wt merge` stop staging
for you in **every** repository. The direction is the safe one — they commit
what you staged and never more — but it is a habit change everywhere, not
just here.

`lean-herdr` resolves on the PATH of every repository -- the installed
snapshot, never this checkout -- and a failing generation command is fatal,
not a silent fallback: it would break `wt step commit` and `wt merge` in all
your other projects. The generator is repo-agnostic: it only formats what
worktrunk hands it on stdin. `lean-herdr workspace check` says whether the
effective command is this one.

worktrunk also knows `[projects."<id>"]` blocks. Whether
`commit.generation.command` is allowed inside one is untested; if it were, the
generator could be scoped to this repository instead of the whole machine.
The machine-wide line works either way and stays the recommendation.

The key is read from `$OPENROUTER_API_KEY`, else from opencode's own store at
`~/.local/share/opencode/auth.json`. With neither, commits fall back to file
names and nothing breaks.

    export OPENROUTER_API_KEY=<your key>

**The new attack surface, named:** the builder may now run a command that
sends the contents of its worktree to a third-party service. That was already
true of every agent in this project, but here without a model in between that
could refuse. In a repository with secrets in it, do not configure the
generator.

## The Herdr plugins

The lean-herdr plugin ships inside the package. Link the installed copy --
`lean-herdr workspace check` prints the exact path:

    herdr plugin link <tool-venv>/lib/python3.14/site-packages/lean_herdr/plugin

Then check — Herdr does not reject unknown plugin events, it only warns:

    herdr plugin list        # expectation: no line with `warning:`

## Updating

`lean-herdr` on the PATH is a snapshot of `main`, not this checkout. After a
merge, take the new snapshot on purpose -- nothing reinstalls itself:

    uv tool install --reinstall "lean-herdr @ git+file:///home/tholo/Scripts/lean-herdr@main"
    lean-herdr workspace check

Then, in every project that uses it:

    lean-herdr workspace init --update

If that rewrote `.config/wt.toml`, the changed gate command needs a fresh
`wt config approvals add` -- until then worktrunk skips it silently.

`workspace check` also names what shadows the snapshot: an activated venv
whose `bin/` comes first on the PATH -- this repository's own `.venv`
included -- and a `PYTHONPATH` that puts another `lean_herdr` ahead of the
installed one. A reinstall on a new Python minor version moves the package
path; `check` then prints the new `herdr plugin link` line.

## Development

    uv sync --dev
    pre-commit install   # once per clone, after `uv tool install pre-commit`
    uv run pytest -q
    uv run ruff check
    uv run ty check

`pre-commit install` sets up both hook stages of `.pre-commit-config.yaml`:
ruff, ruff format and ty on every commit that touches Python or
`pyproject.toml`, pytest on every push, and a guard that keeps
`docs/specs/` and `docs/lean-md/` off `main`.

`uv run lean-herdr …` runs this checkout; the bare `lean-herdr` is the
installed snapshot. `uv run lean-herdr workspace check` therefore warns that
there is no tool venv and that the install is editable -- correctly.

Tests with `-m integration` need real binaries and do not run in CI.
