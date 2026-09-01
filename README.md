# lean-herdr

Ein Workspace, in dem ein billiger Orchestrator-Agent Aufgaben an staerkere
Arbeiter-Agenten verteilt: Inhalt ueber den lean-ctx-Agentenbus, Takt ueber
Herdr, Isolation ueber Git-Worktrees.

Entwurf und Messungen: `docs/specs/2026-09-01-lean-herdr-design.md`.

## Laufzeit-Abhaengigkeiten

Herdr installiert keine Toolchains — diese Dinge muessen vorhanden sein:

| Was | Wofuer | Installation |
|---|---|---|
| `herdr` >= 0.8.2 | Panes, Agenten, Workspaces | siehe Herdr-Projekt |
| `lean-ctx` >= 3.10.1 | Agentenbus, Projektgedaechtnis | `cargo install lean-ctx` |
| `uv` | Laufzeit der Python-Skripte und -Handler | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| `worktrunk` (`wt`) >= 0.75.0 | Worktree je Branch, Merge, Cleanup | `cargo install worktrunk` |
| Herdr-Plugin `devashish2203/herdr-worktrunk` | bindet Worktrees an Workspaces; braucht `fzf` und `jq` | `herdr plugin install devashish2203/herdr-worktrunk` |
| `opencode` >= 1.18.25 | Orchestrator und Reviewer | siehe opencode-Projekt |
| Claude Code >= 2.1.252 | Builder | siehe Claude-Code-Projekt |

Zwei Freigaben in lean-ctx, ohne die ein Agent unter Shell-Gating weder Herdr
noch worktrunk steuern kann:

    lean-ctx allow herdr
    lean-ctx allow wt

Danach pruefen — Herdr lehnt unbekannte Plugin-Events nicht ab, es warnt nur:

    herdr plugin list        # Erwartung: keine Zeile mit `warning:`

## Bootstrap

Der Orchestrator startet sich nicht selbst. Einmal je Workspace:

    herdr pane split --current --direction right --cwd "$PWD" --no-focus \
      --env LEAN_CTX_TOOL_PROFILE=minimal --env LEAN_CTX_ROLE=orchestrator
    herdr agent start orch --kind opencode --pane <id> -- --agent orchestrator

Danach die lean-ctx-agent_id des Orchestrators aufloesen und in
`roles/builder.md` und `roles/reviewer.md` an der Stelle
`<ORCHESTRATOR_AGENT_ID>` eintragen — das ist das Vertrauensmodell: eine
Bus-Nachricht kann nicht behaupten, der Orchestrator zu sein.

## Entwicklung

    uv sync --dev
    uv run pytest -q

Tests mit `-m integration` brauchen echte Binaries und laufen nicht in CI.
