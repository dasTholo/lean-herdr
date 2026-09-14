# CLAUDE.md

## Project Hard Rules

> lean-ctx tool-discipline (ctx_read/ctx_shell/ctx_search/ctx_tree mapping, read
> modes, CEP, dense output) is loaded globally via `~/.claude/CLAUDE.md`.


- **No Brief-/Report-Files**: ctx_session
- **File size — no `lean_herdr/` file above 800 *production* LOC** (600 is the target).
  Production LOC = physical lines minus blank, comment and docstring lines. Measure it,
  never `wc -l`: the two diverge widely in this tree, far enough that the largest file's
  physical count is already over 800 with the rule intact. No figure is quoted here on
  purpose — one ages with the next commit, and this file has carried two stale readings
  already. Measure before you decide anything on a number.

## Language

- Interaction and chat, and everything under `docs/` (plans, specs, their prose):
  **German**. The spelling is free: the existing files carry both the ä ö ü ß
  characters and their ae / oe / ue / ss transcriptions, nothing enforces
  either form, and no file gets rewritten for the sake of one.
- Everything outside `docs/`: **English**. Code, comments, docstrings, test names,
  `.lean-ctx/lean-herdr/roles/*.md` (agent prompts), `README.md` and `INSTALL.md`
  (operator docs), commit messages.
