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
  `roles/*.md` (agent prompts), `README.md` (operator docs), commit messages.
- **No translation sweeps.** German that already exists outside `docs/` stays put.
  It becomes English when something rewrites that file or section anyway — and
  then in full, never half.
  The one deliberate sweep ran on 2026-09-02 and left the tree English outside
  `docs/`; its plan is the 2026-09-02 language plan under `docs/lean-md/plans/`.
  One file stays German on purpose — `tests/fixtures/registry.sample.json` is
  a frozen recording, and it sits in `EXCEPTIONS` of `tests/test_language.py`.
  This rule governs what comes after that sweep, and `tests/test_language.py`
  now enforces the result.
