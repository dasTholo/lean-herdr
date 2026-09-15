# Python language pack (lean-herdr)

- Tests: `uv run pytest -q <test files> -k <name>` — always name the files; a bare name is
  read as a path.
- Lint `uv run ruff check .`, format `uv run ruff format <paths>`, types `uv run ty check`.

## Plan-content rule: how a task edits code

- Find references and definitions with `ctx_refactor` (`references`, `definition`): lean-ctx
  starts `pylsp`, and `.lean-ctx/lean-herdr/bin/pylsp` hands that to `ty server`.
- Replace a function body with `ctx_refactor action=replace_symbol_body` and `path` set.
- Everything else: `ctx_read mode=anchored`, then `ctx_patch`.
- No `@refactor` for rename or move: for Python those need a JetBrains backend, and a worker
  has none.
