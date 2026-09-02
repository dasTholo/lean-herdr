# CLAUDE.md

## Project Hard Rules

> lean-ctx tool-discipline (ctx_read/ctx_shell/ctx_search/ctx_tree mapping, read
> modes, CEP, dense output) is loaded globally via `~/.claude/CLAUDE.md`.


- **No Brief-/Report-Files**: ctx_session
- **File size — no `lean_herdr/` file above 800 *production* LOC** (600 is the target)

## Language

- Interaction, chat, plans, specs: **German** with proper umlauts (ä ö ü ß) — never ae / oe / ue / ss
- Code and code comments: **English**
- Shipped artefacts — `roles/*.md` (agent prompts), `README.md` (operator docs),
  commit messages: **English**
