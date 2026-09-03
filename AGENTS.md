# CLAUDE.md

## Project Hard Rules

> lean-ctx tool-discipline (ctx_read/ctx_shell/ctx_search/ctx_tree mapping, read
> modes, CEP, dense output) is loaded globally via `~/.claude/CLAUDE.md`.


- **No Brief-/Report-Files**: ctx_session
- **File size — no `lean_herdr/` file above 800 *production* LOC** (600 is the target)

## Language

- Interaction and chat, and everything under `docs/` (plans, specs, their prose):
  **German** with proper umlauts (ä ö ü ß) — never ae / oe / ue / ss
- Everything outside `docs/`: **English**. Code, comments, docstrings, test names,
  `roles/*.md` (agent prompts), `README.md` (operator docs), commit messages.
- **No translation sweeps.** German that already exists outside `docs/` stays put.
  It becomes English when something rewrites that file or section anyway — and
  then in full, never half.
  The one deliberate sweep ran on 2026-09-02 and left the tree English outside
  `docs/`; its plan is the 2026-09-02 language plan under `docs/lean-md/plans/`.
  Two files stay German on purpose — `tests/fixtures/registry.sample.json` and
  `tests/fixtures/tasks.sample.json` are frozen recordings, and both sit in
  `EXCEPTIONS` of `tests/test_language.py`. This rule governs what comes after
  that sweep, and `tests/test_language.py` now enforces the result.
