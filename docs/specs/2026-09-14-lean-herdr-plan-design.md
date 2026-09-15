# lean-herdr: Planausführung — Teilprojekt 2 „Plan“ — Design v1.0

**Stand:** 2026-09-14, TP0-Nachtrag 2026-09-15 · **Status:** beschlossen, nicht implementiert
**Anlass:** Der Orchestrator soll einen Plan schreiben lassen, ihn prüfen und reviewen lassen
und ihn danach Task für Task von Agents ausführen lassen. TP1 („Rollen und Routing“) hat die
Grundlage gelegt; lauffähig ist heute nur die Kette `--work implement` → `--work review` →
Merge für eine einzelne Aufgabe.
**Bezug:** `2026-09-14-lean-herdr-rollen-und-routing-design.md` (Teil A Gesamtbild, TP1);
lean-md `docs/lean-md/specs/2026-09-14-lmd-outline-json-design.md` (TP0, abgeschlossen: Tag `v0.2.4` = `3d27803`);
lean-md `docs/lean-md/2026-08-31-distributionskanal-entfallen.md`
**Betrifft:** neu `lean_herdr/plan.py`, `lean_herdr/planrun.py`, `lean_herdr/plancmd.py`;
geändert `lean_herdr/cli.py`, `dispatch.py`, `llm.py`, `ordercmd.py`, `orders.py`, `report.py`,
`settings.py`, `initcmd.py`, `checkcmd.py`, `templating.py` (`LAYOUT`);
`lean_herdr/templates/` (Rollen-Prompts, Briefs, Plan-Template, Rezepte, `lang/python`,
`bin/pylsp`, `claude/*.json`, `opencode.jsonc`, `settings.json`, `config.toml`) samt
eingecheckten Kopien und Lock; `README.md`, `INSTALL.md`; Tests.

---

## 1. Einordnung

### 1.1 Reihenfolge

| # | Teilprojekt | Repo | Ergebnis |
|---|---|---|---|
| 0 | `lean-md outline --json` | lean-md | Phasen, `@call`s, Makro-Signaturen und Prüfbefunde als JSON; abgeschlossen, über Shim und Gateway installiert (2026-09-15, §2.1) |
| 1 | **TP2 Plan** (dieses Dokument) | lean-herdr | Plan schreiben, prüfen, reviewen, seriell ausführen |
| 2 | Anbieterwahl | lean-herdr | Endpoint-Rangliste (Preis nach Rabatt, Durchsatz, Latenz, Uptime) mit Fallback |
| – | FastAPI-Testlauf | neues Repo unter `~/Scripts` | Abnahme des Gesamtablaufs |

### 1.2 Änderungen am Gesamtbild (TP1-Spec, Teil A)

- TP2 enthält die **serielle Ausführung** eines reviewten Plans (A5 sah sie erst in TP3).
  Parallele Spuren, Integrator und Push bleiben TP3.
- Der Plan entsteht auf `plan/<slug>`, nicht auf `main` (A1 Schritt 1).
- Vor dem Merge läuft ein **Review über den ganzen Branch** (A1 Schritt 7, seriell).
- Die **Längenprüfung** für Agent-Namen wird vorgezogen; die automatische Kürzung bleibt TP3.
- Die Plan-Struktur liest lean-herdr über `lean-md outline` (TP0), nicht über einen eigenen
  Parser. E4 („ohne lean-md-Release“) gilt dafür nicht mehr; der lokale Release 0.2.4 ist
  installiert (§2.1).

### 1.3 Entscheidungen

| # | Entscheidung |
|---|---|
| D1 | TP2 endet mit serieller Ausführung: ganzer Plan = eine Spur, je Task `implement` → `review`, am Ende Branch-Review und Merge. |
| D2 | Der Plan entsteht auf `plan/<slug>`; Plan-Writer, Review-Runden und alle Tasks nutzen denselben Worktree; ein Merge bringt Plan und Code nach `main`. |
| D3 | Der Auftrag nennt nur die Task; der Worker holt seinen Brief mit `lean-herdr plan brief`. |
| D4 | Der Brief setzt zusammen: `@include hard-rules`, die angepasste Disziplin der SDD-Companions und die Regeln von lean-herdr; der Reviewer bekommt dazu Global Constraints und Commit-Bereich. |
| D5 | Die angepassten Companions liegen als eigene Brief-Templates in lean-herdr, nicht als lean-md-Overlay (das wirkt projektweit, auch auf SDD-Sessions des Betreibers). |
| D6 | lean-herdr liefert Plan-Template, Rezepte, `lang/python` und Briefs unter eigenen Namen; die lean-md-Seeds bleiben unberührt. |
| D7 | `workspace init` richtet lean-md im Projekt ein (`lean-md skill install`); `workspace check` meldet fehlende Voraussetzungen auf dem Rechner, repariert sie nicht. |
| D8 | Den Fortschritt liefert das Auftragslog; `plan next` sagt den nächsten Schritt. Der Orchestrator zählt nichts selbst. |
| D9 | Volles Plan-Format schon in TP2: `route(work, lane, files)`, `@phase "lanes"`, `@phase "constraints"`. |
| D10 | Prüfschleife wie bei Tasks: zwei fehlgeschlagene Checks in Folge oder zwei Ablehnungen → Eskalation. Nach `result` geht es direkt weiter; einen Halt drückt die Anweisung aus. |
| D11 | Task-Commits bleiben; im Plan-Modus kein `wt step squash`. |
| D12 | `report` stempelt `head` und `changes` über `wt list --format=json`; Reviewer-Diffs laufen über `wt step diff`. |
| D13 | `ty` erreicht die Panes über einen Wrapper `pylsp` in `.lean-ctx/lean-herdr/bin`, den `dispatch` vorn in den `PATH` stellt. |
| D14 | Das Pre-Review bleibt im Plan-Modus: bei `plan` prüft es den Plan gegen die Spec, bei `implement` die Änderung gegen die gerenderte Task ab der Task-Basis (§6.6). |

## 2. Ausgangslage, gemessen am 2026-09-14

| Messung | Ergebnis |
|---|---|
| `cli.py` `VERBS` | kein Verb `plan`; `plan`, `plan-review`, `integrate` sind reserviert (`settings.py:144-149`) |
| `lean-md render <plan> --phase task-N` | beginnt mit `## Task N`: kein Plan-Kopf, keine Global Constraints, keine Hard-Rules; Rezepte expandiert, `@read` ausgewertet (0,1–0,7 s je Phase) |
| `@include hard-rules` in eigener `.lmd.md` | rendert eigenständig (eingebaut + `hard-rules.ext.lmd.md`) |
| `@include dispatch-contract` | verlangt `ctx_agent register`, Handoff an `controller_id`, `git commit -m` — unvereinbar mit `lean-herdr report` und `wt step commit` |
| lean-md-Companion-Overlay `.lean-ctx/lean-md/skills/<skill>/companions/` | ersetzt den eingebauten Companion projektweit (`src/skills.rs:66-79`) |
| `@import` | übernimmt nur Makros, Prosa fällt weg (`src/macros.rs:457-470`) — `lang/*.lmd.md` erreicht keinen Render |
| Unbekanntes Makro in einer Phase | Fehler erst beim Rendern, `PHASE_ABORTED` (`src/phases.rs:436-473`) |
| `@call`-Argumente | Komma außerhalb Quotes trennt; fehlende Argumente werden still `""`, überzählige still verworfen (`src/macros.rs:131-185`) |
| lean-md im neuen Projekt | ohne `lean-md skill install` weder Skill-Stubs noch Seeds unter `.lean-ctx/lean-md/` |
| lean-ctx-Addon-Kanal | upstream entfernt; lean-md 0.2.3 von Hand installiert; Shim `~/.local/bin/lean-md` nimmt die höchste Version unter `addons/bin/lean-md/` |
| `wt step diff <sha>` | nimmt einen Commit als Ziel: Commits, gestaged, ungestaged und ungetrackt seit diesem Commit (17 ms) |
| `wt list --format=json` | liefert je Worktree `head.sha` und `worktree.changes` (29 ms) |
| `llm.prereview_result` | bewertet `wt step diff` seit dem Abzweigen gegen `order.description` (`llm.py:413-448`, `:518-572`, `dispatch.py:505-506`); Grenze `MAX_DIFF_BYTES` = 150 000 |
| `agent_name()` | ersetzt Nicht-Alphanumerisches durch `-`, prüft keine Länge (`dispatch.py:162`); Herdr erlaubt `[a-z][a-z0-9_-]{0,31}` |
| `ensure_worktree` | nutzt einen vorhandenen Worktree des Branches, legt sonst einen von `main` an (`worktree.py:206-239`) |
| `ctx_refactor` mit Python | Standard `pylsp` fehlt; `rename/move/inline/reformat/inspections` nur mit JetBrains-IDE; `replace_symbol_body` mit `path` funktioniert ohne LSP |
| `[lsp]` in projekt-lokaler `.lean-ctx.toml` | wird nicht übernommen (`merge.rs`) |
| Wrapper `pylsp` → `ty server` im `PATH` | `references` (11 Treffer für `role_for_work`, 0,22 s) und `definition` funktionieren; `symbols_overview` liefert keine Symbole |
| Produktions-LOC | `dispatch.py` 581, `checkcmd.py` 408, `llm.py` 352, `settings.py` 326, `report.py` 209, `initcmd.py` 169, `ordercmd.py` 100 |

### 2.1 Nachtrag TP0, gemessen am 2026-09-15

| Messung | Ergebnis |
|---|---|
| lean-md-Stand | Tag `v0.2.4` = `3d27803`, enthält alle `outline`-Fixes nach dem Prepare-Commit `07caf9f`; Shim und Gateway-`command` in `~/.config/lean-ctx/config.toml` zeigen auf `addons/bin/lean-md/0.2.4/` |
| `lean-md outline - --json` mit leerem stdin | `{"errors":[],"macros":{},"phases":[]}`, Exit 0 |
| Befundarten | `unknown_macro`, `arity`, `malformed_call`, `embedded_call`, `duplicate_phase`, `nested_phase`, `unterminated_phase`, `unterminated_define`, `import`, `missing_phase`; `arity` nennt lean-md einen Lint (ein Render füllt fehlende Argumente auf), er steht trotzdem in `errors` und ergibt Exit 1 |
| Schlüssel `phase` | fehlt bei einem Befund außerhalb jeder Phase; `import` trägt die Phase seines `@import`, `missing_phase` den geforderten Namen (`line` = 0) |
| `@call` in Liste oder Zitat | fehlt in `calls`; Befund `embedded_call` (Marker nach CommonMark) |
| eingerücktes `@call` | Text wie beim Rendern: fehlt in `calls`, kein Befund |
| `@import` im Header (ohne Leerzeile davor) | geprüft wird nur der Body nach dem Header: Makros nicht im Scope, jedes `@call` ergibt `unknown_macro` |
| alle 15 `.lmd.md`-Dateien unter `docs/lean-md/plans/` | Exit 0, keine Befunde; `2026-09-14-lean-herdr-rollen-und-routing.lmd.md` liefert `task-1` … `task-9` (Abnahme der TP0-Spec §12) |

## 3. Plan-Format

**Ort:** `docs/lean-md/plans/<slug>.lmd.md` auf `plan/<slug>`. Der Slug erfüllt
`[a-z][a-z0-9-]{0,11}`. Der Kopf nennt die zugrunde liegende Spec.

```
@lean-md
consumer: ai
crp: compact

@var test_cmd default="uv run pytest -q"
@var lint_cmd default="uv run ruff check ."
@var fmt_cmd  default="uv run ruff format"
@import .lean-ctx/lean-md/herdr-recipes /

# <Titel>
Spec: docs/specs/<…>-design.md
## Goal / ## Architecture (Prosa)

@phase "constraints"
## Global Constraints
- nur Invarianten aus der Spec
@phase-end

@phase "lanes"
## Lanes
@call lane(core, "")
@call lane(api, "core")
@phase-end

@phase "task-1"
@call route(implement, core, "app/models.py tests/test_models.py")
## Task 1: …
@phase-end
```

**Regeln von `plan check`** (zusätzlich zu den Befunden von `lean-md outline`):

| Regel | Befund |
|---|---|
| Phasen `task-1 … task-N` lückenlos, in Dokument-Reihenfolge | `task_order` |
| erstes `@call` jeder Task ist `route` | `no_route` |
| `work` wird über `[routing]` aufgelöst | `unknown_work` |
| `work` ist keine Stufe (`plan`, `plan-review`, `review`, `integrate`) | `stage_as_work` |
| `lane` ist in `lanes` deklariert | `unknown_lane` |
| `deps` (durch Leerzeichen getrennt, wie `files`) nennen nur deklarierte Spuren, ohne Zyklus | `unknown_lane` / `lane_cycle` |
| keine Task steht vor einer Task einer Spur, von der ihre Spur abhängt | `order_vs_deps` |
| `files` ist nicht leer | `no_files` |
| dieselbe Datei in zwei Spuren, die nicht voneinander abhängen | **Warnung** `lane_overlap` |
| eine Datei aus §4 fehlt am Plan-Commit | `missing_on_branch` |
| `plan/<slug>` ändert gegenüber `main` etwas unter `.lean-ctx/lean-md/` oder `.lean-ctx/lean-herdr/briefs/` | `branch_touches_tooling` |

Jeder Befund von `lean-md outline` (§2.1) ist ein Fehler, `arity` eingeschlossen. Ein `route` in
einer Liste, einem Zitat oder eingerückt zählt nicht als Aufruf: `no_route`, bei Liste oder Zitat
zusätzlich `embedded_call`.

## 4. Ausgelieferte Dateien und lean-md-Einrichtung

Alle Dateien schreibt `workspace init` mit dem Lock von lean-herdr.

| Datei | Inhalt |
|---|---|
| `.lean-ctx/lean-md/herdr-plan-template.lmd.md` | Gerüst aus §3; `test_cmd`/`lint_cmd`/`fmt_cmd` aus `--test`/`--lint`/`--lang` |
| `.lean-ctx/lean-md/herdr-recipes.lmd.md` | `@import .lean-ctx/lean-md/plan-recipes /`; `@define route(work, lane, files)` und `@define lane(name, deps)` (erste Zeile Beschreibungskommentar, danach eine sichtbare Zeile für den Worker); überschreibt `commit(paths, msg)` mit `git add {{ paths }}` + `wt step commit --stage none --yes` und `gate(paths)` mit `fmt_cmd`, `lint_cmd`, `test_cmd` |
| `.lean-ctx/lean-md/lang/python.lmd.md` | Leitfaden für den Plan-Writer: `uv run pytest -k`, `ruff check`, `ruff format`; Referenzen und Definitionen über `ctx_refactor`; Funktionskörper über `replace_symbol_body` mit `path`; sonst anchored `ctx_patch`; kein `@refactor` für Umbenennen oder Verschieben |
| `.lean-ctx/lean-herdr/briefs/implement.lmd.md` | `@include hard-rules`; Disziplin nach SDD-`implementer` (Unklarheit → `report ask`; zu groß oder Plan falsch → `report fail` mit Grund; TDD; Selbst-Review über `wt step diff`; `report done` mit `status`, `commits`, `tests`, `concerns`); Regeln von lean-herdr (Commit nur `wt step commit --stage none`, kein `git commit -m`, kein Push, kein Merge, im Worktree bleiben) |
| `.lean-ctx/lean-herdr/briefs/review.lmd.md` | `@include hard-rules`; Disziplin nach SDD-`task-reviewer`: Teil 1 Spec-Treue, Teil 2 Code-Qualität, Critical/Important/Minor, „plan-mandated“ ist kein Mangel; Critical oder Important → `VERDIKT: reject`; offene Punkte → `report ask`; Plan-Konflikt → `report fail`; schreibt nichts, auch nicht über `ctx_shell` |
| `.lean-ctx/lean-herdr/briefs/plan.lmd.md` | `@include hard-rules`; `lmd-writing-plans` mit `herdr-plan-template`; Pflicht-Phasen und `route` als erste Zeile; Python-Leitfaden; Plan committen, dann `lean-herdr plan check <slug>`, erst bei `ok` `report done`; nach `--after` die Befunde des Vorgängers abarbeiten |
| `.lean-ctx/lean-herdr/briefs/plan-review.lmd.md` | `@include hard-rules`; angepasster `plan-reviewer`-Companion aus `lmd-writing-plans`: versteckte Abhängigkeiten, Dateilisten, Konflikt-Brennpunkte, Zuschnitt der Tasks und Spuren; `VERDIKT: result\|reject` |
| `.lean-ctx/lean-herdr/roles/plan-writer.md`, `roles/plan-reviewer.md` | vollständige Rollen-Prompts wie `builder.md`/`reviewer.md` (Trust, `report`-Ablauf, BOUNDARY) |
| `.lean-ctx/lean-herdr/claude/plan-writer.json`, `claude/plan-reviewer.json` | `deny`-Listen nach §5.3 |
| `.lean-ctx/lean-herdr/bin/pylsp` | ausführbar, `exec ty server "$@"`; nur bei `--lang python` |

**lean-md-Einrichtung:** `init` ruft `lean-md skill install lmd-writing-plans` und
`lean-md skill install lmd-brainstorm` lokal auf (`lmd-rendering-skills` kommt mit). Das
schreibt `.claude/skills/<name>/`, die Seeds unter `.lean-ctx/lean-md/` und
`.lean-ctx/lean-md.lock`. Scheitert der Aufruf, schreibt `init` die eigenen Dateien trotzdem
und meldet `lean_md: {installed: […], error: …}`. `init --update` ruft die Installation
erneut auf; lean-md frischt dabei nur unveränderte Seeds auf.

**`--lang`:** in TP2 nur `python`, zugleich Standard.

**Committete Dateien sind Voraussetzung.** Worker rendern im Worktree von `plan/<slug>`, der
von `main` abzweigt; Imports und `@include` lösen gegen das Arbeitsverzeichnis auf, und
Claude findet Skills unter `.claude/skills/` des Worktrees. Deshalb müssen die Ausgaben von
`init` — Template, Rezepte, `lang/python`, Briefs, Rollen-Prompts, `bin/pylsp`, die lean-md-Seeds
samt `lean-md.lock` und `.claude/skills/lmd-writing-plans` mit `lmd-rendering-skills` — auf
`main` committet sein. `workspace check` warnt für jede dieser Dateien, die `git ls-files`
nicht kennt. `plan check` meldet `missing_on_branch`, wenn eine davon am Plan-Commit fehlt,
und `branch_touches_tooling`, wenn `plan/<slug>` gegenüber `main` etwas unter
`.lean-ctx/lean-md/` oder `.lean-ctx/lean-herdr/briefs/` ändert. So lösen `plan.py`
(Repo-Wurzel) und die Worker (Worktree) dieselben Dateien auf.

## 5. Rollen, Routing, Rechte

### 5.1 Routing

| Arbeitsart | eingebaute Rolle |
|---|---|
| `implement` | `builder` |
| `review` | `reviewer` (Task- und Branch-Review) |
| `plan` | `plan-writer` (neu) |
| `plan-review` | `plan-reviewer` (neu) |
| `integrate` | — (reserviert, TP3) |

- `model_warnings` vergleicht zusätzlich die Rolle hinter `plan-review` mit der Rolle hinter
  `plan`; Opt-out `shares_reviewed_model` beim Plan-Reviewer.
- Worker haben kein eingebautes `kind` und kein Modell. Das Config-Template zeigt
  auskommentiert `[roles.plan-writer]` und `[roles.plan-reviewer]`.
- Arbeitsarten eines Plans kommen aus `route`; eine kleine Task kann über eine eigene
  Arbeitsart auf eine Rolle mit kleinerem Modell gehen (`[routing] implement-small = …`).

### 5.2 Agent-Namen

`dispatch` weist im Build-Modus einen Namen über 32 Zeichen vor jedem Pane mit
`config_error` ab. Mit dem Standard-`name_template` passt die längste Rolle:
`plan-reviewer-plan-<slug≤12>` = 31 Zeichen. Eine Kürzung gibt es nicht (TP3).

### 5.3 Rechte

| Rolle | opencode (`opencode.jsonc`) | claude (`claude/<rolle>.json`, `deny`) |
|---|---|---|
| orchestrator | + `lean-herdr plan next *`, `plan show *`, `plan check *` | unverändert |
| builder | + `lean-herdr plan brief *` | + `Bash(git push:*)`, `Bash(wt merge:*)`, `Bash(wt step push:*)` |
| reviewer | + `lean-herdr plan brief *`, `wt step diff *` | bisher + push/merge |
| plan-writer | Schreiben erlaubt; `lean-herdr report …`, `plan brief *`, `plan check *`, `git add*`, `wt step commit *`, `git status*`, `git diff*`, `git log*` | push/merge |
| plan-reviewer | wie reviewer + `plan check *` | wie reviewer + push/merge |

- `.claude/settings.json` erlaubt zusätzlich `Bash(lean-herdr plan brief:*)`,
  `Bash(lean-herdr plan check:*)`, `Bash(lean-herdr plan next:*)`, `Bash(lean-herdr plan show:*)`
  und `Bash(wt step diff:*)` — damit läuft auch ein Orchestrator mit `kind = "claude"`; alle
  vier `plan`-Befehle lesen nur.
- Nicht schreibende Rollen (orchestrator, reviewer, plan-reviewer) sperren in opencode
  weiterhin `edit`, `write` und die lean-ctx-Schreibwerkzeuge.
- **Bekannte Lücke:** `ctx_shell` bleibt offen (global `mcp__lean-ctx__*`); ein Push über
  `ctx_shell` ist nur per Brief verboten.

### 5.4 Rollen-Prompts

- `plan-writer.md`, `plan-reviewer.md` enthalten die Pflichtsätze `lean-herdr report start`,
  `ORCHESTRATOR = orch` und „Never pass `--agent`.“.
- Alle vier Worker-Prompts bekommen nach `report start` den Schritt
  `lean-herdr plan brief --task o-…`, sobald der Auftrag einen Plan trägt.
- `orchestrator.md` bekommt den Abschnitt „Plan mode“ (§7).

### 5.5 `PATH` für Worker

Existiert `<root>/.lean-ctx/lean-herdr/bin`, hängt `dispatch` beim `pane split` zusätzlich
`--env PATH=<root>/.lean-ctx/lean-herdr/bin:<PATH des aufrufenden Prozesses>` an
(ausgeschrieben, `root` aus `canonical_root()`). Der lean-ctx-Server im Pane erbt ihn.

## 6. CLI und Datenfluss

### 6.1 Module

| Modul | Aufgabe |
|---|---|
| `plan.py` | liest den Plan (`git show plan/<slug>:docs/lean-md/plans/<slug>.lmd.md`; fehlt der Branch nach dem Merge, von `main`), ruft `lean-md outline - --json --require-phase constraints,lanes` mit der Repo-Wurzel als Arbeitsverzeichnis, baut `Plan` (Tasks mit `work`, `lane`, `files`, Titel) und prüft §3 |
| `planrun.py` | reine Zustandsmaschine ohne I/O: `Plan` + gefaltete Aufträge mit `plan = <slug>` → nächster Schritt (§6.4) |
| `plancmd.py` | Verb `plan`: Argumente, JSON-Ausgabe, Zusammenbau der Briefs |

Wiederverwendet werden `orders.fold`, `dispatch.verdict`, `settings.role_for_work`,
`settings.work_roles`.

### 6.2 Befehle

| Befehl | Nutzer | Ausgabe |
|---|---|---|
| `lean-herdr plan check <slug>` | Orchestrator, Plan-Writer, Plan-Reviewer | JSON `{ok, errors[], warnings[]}`; geprüft wird der committete Stand |
| `lean-herdr plan next <slug>` | Orchestrator | JSON, eine Zeile (§6.4) |
| `lean-herdr plan show <slug>` | Orchestrator, Mensch | JSON: Tasks mit Titel, `work`, `lane`, `files`, Zustand, Runden, Auftrags-IDs |
| `lean-herdr plan brief --task o-…` | alle Worker | Klartext; Fehler als eine Zeile auf stderr, Exit 1 |

`plan brief` ist die einzige Ausgabe außerhalb des JSON-Vertrags. `cli.PLAIN_VERBS` bleibt
unverändert; `plancmd` wählt die Ausgabeart je Unterbefehl.

### 6.3 Auftrag und Stempel

- `dispatch order` bekommt `--plan <slug> --step plan|plan-review|implement|review
  [--plan-task N|branch] [--spec <pfad>]`. Die Felder landen im Payload und in `Order`.
  `--spec` ist bei `--step plan` Pflicht und sonst unzulässig. `--plan-task` fehlt bei
  `plan` und `plan-review`; bei `implement` und `review` ist es eine Tasknummer oder
  `branch`. Jede andere Kombination ist ein `usage_error`, bevor etwas ins Log geschrieben
  wird.
- `report start` und `report done` schreiben `head` (SHA) und `changes` (Flags) aus dem
  Eintrag mit `worktree.current: true` von `wt list --format=json` ins Event. Scheitert
  `wt`, trägt das Event `wt_error`; `report` bleibt erfolgreich.

### 6.4 `plan next`

| Lage | Antwort |
|---|---|
| Plan-Datei liegt auf `main` | `{done: true}` |
| kein Plan-Auftrag | `{step: plan, work: plan, round: 1}` |
| offener Auftrag (nicht terminal) | `{step: await, work, task_id, task, round}` |
| Plan-Auftrag `failed` oder `canceled` | `{escalate: true, reason, task_id}` |
| Plan-Auftrag `done`, `plan check` fehlerhaft | `{step: plan, reason: check, errors, round, after}`. Geprüft wird der Stand am `head` aus dem `report done` dieses Auftrags (`git show <head>:<pfad>`); `plancmd` prüft jeden erledigten Plan-Auftrag so und übergibt die Ergebnisse an `planrun`. Sind die letzten zwei Plan-Aufträge beide fehlerhaft → `{escalate: true, reason: check×2}` |
| Check ok, kein Plan-Review | `{step: plan-review, work: plan-review}` |
| Plan-Review `reject` | `{step: plan, round, after}`; zweimal → `escalate` |
| Plan-Review `result` | erste offene Task: |
| — kein `implement`-Auftrag | `{step: implement, task, work, round: 1}` |
| — `implement` `done`, getrackte Änderungen offen (`staged`, `modified`, `deleted`, `renamed` oder `conflicted`) | `{step: implement, task, work, reason: uncommitted, round, after}`; zweimal in Folge → `escalate`. Ungetrackte Dateien lösen keine Runde aus (`builder.md`: „Untracked files stay untracked“); der Review-Brief nennt sie |
| — `implement` `done`, sauber | `{step: review, task, work: review, after}` |
| — `review` `reject` | `{step: implement, task, work, round: n+1, after}`; zweite Ablehnung → `escalate` |
| — `review` `result` | nächste Task |
| alle Tasks `result`, kein Branch-Review | `{step: review, task: branch, work: review}` |
| Branch-Review `reject` | `{step: implement, task: branch, work: implement, after}`; zweimal → `escalate` |
| Branch-Review `result` | `{step: merge}` |
| Worker-Auftrag `failed` | `{escalate: true, reason: agent_error, task_id}` |
| Auftrag (jeder `step`) `canceled` | `{escalate: true, reason: canceled, task_id}` |
| `implement` mit `task: branch` `done` | dieselbe Prüfung auf getrackte Änderungen wie bei Tasks, danach `{step: review, task: branch, work: review, after}` |
| `report`-Event mit `wt_error` statt `head`/`changes` | `changes` gilt als unbekannt, nicht als offen (die Ablehnung durch `wt merge --no-commit` bleibt letzte Sperre). Fehlt der `head` aus `report start`, nimmt der Review-Brief den `head` aus dem letzten `report done` der vorigen Task, bei Task 1 die Merge-Basis mit `main`, und nennt den Ersatz |

- `round` zählt die Aufträge desselben Schritts: die `implement`-Aufträge einer Task bzw. die
  Plan-Aufträge. `--prereview` gibt der Orchestrator in Runde 1 von `implement` (Task) und
  von `plan` mit (§6.6).
- Ein fehlendes oder unlesbares Urteil gilt wie bisher als `reject`.

### 6.5 Briefs

| `step` | Inhalt von `plan brief` |
|---|---|
| implement (Task) | Render von `briefs/implement` + Render von `task-N` |
| implement (branch) | `briefs/implement` + `constraints` + Auftragstext mit den Befunden des Branch-Reviews |
| review (Task) | `briefs/review` + `constraints` + `task-N` + „Diff: `wt step diff <head>`“ mit `head` aus dem `report start` des **ersten** `implement`-Auftrags der Task + Commit-Liste + ungetrackte Dateien aus `git status --porcelain --untracked-files=all` im Worktree |
| review (branch) | `briefs/review` + `constraints` + Tasks mit Titeln + „Diff: `wt step diff`“ |
| plan | `briefs/plan` + Slug, Pfad des Plans + Arbeitsarten aus `[routing]` ohne Stufen, mit Rolle und Modell + Spec-Pfad aus dem Payload (`--spec`) + Auftragstext |
| plan-review | `briefs/plan-review` + Pfad des Plans + Befunde von `plan check` |

Gerendert wird mit `lean-md render` im Worktree des Workers. Ein CLI-Render einer Phase
schreibt in dessen lean-ctx-Session (`src/phases.rs:392`); das ist gewollt.

### 6.6 Pre-Review im Plan-Modus

Heute bewertet `llm.prereview_result` das ganze Diff seit dem Abzweigen (`wt step diff`,
`llm.py:413-448`) gegen `order.description` (`dispatch.py:505-506`). Im Plan-Modus wäre das
falsch: Das Diff enthält Plan-Commit und frühere Tasks, der Auftragstext ist knapp. Deshalb
bekommt der Judge im Plan-Modus einen eigenen Auftrag und eine eigene Diff-Basis:

| Schritt | Auftrag an den Judge | Diff | Prompt |
|---|---|---|---|
| `implement`, Task, Runde 1 | Render von `constraints` + `task-N` | `wt step diff <head aus report start des Auftrags>` | `PREREVIEW_PROMPT` wie heute |
| `plan`, Runde 1 | Inhalt der Spec (Pfad aus `--spec`, gelesen von `main`) + Kurzfassung der Regeln aus §3 | `wt step diff` (seit dem Abzweigen, also nur der Plan) | neu `PLAN_PREREVIEW_PROMPT`: lehnt nur ab, wenn eine Anforderung der Spec in keiner Task vorkommt oder der Plan §3 sichtbar verletzt |
| `implement` über den Branch, `review`, `plan-review` | kein Pre-Review | – | – |

- `llm.prereview_result` bekommt `base: str | None` (→ `wt -C <path> step diff <base>`) und
  die Wahl des Prompts; `llm prereview` (CLI) bekommt `--base <sha>` und `--plan`.
- `dispatch.await_task` holt Auftragsbild, Basis und Prompt über
  `plancmd.prereview_input(order)`, sobald der Auftrag `plan` im Payload trägt; sonst bleibt
  alles wie heute. In `dispatch.py` kommen nur wenige Zeilen hinzu.
- Grenzen wie heute: Über `MAX_DIFF_BYTES` (150 000) für Diff und Auftragsbild zusammen
  lautet das Ergebnis `skipped`, nie `reject`.
- Ein `prereview: reject` führt wie heute zu genau einem Folgeauftrag desselben Schritts mit
  `--after` und `prereview_note`; der wird ohne `--prereview` abgewartet und zählt als Runde 2.

## 7. Ablauf des Orchestrators („Plan mode“)

**Anweisungen des Betreibers**

| Anweisung | Verhalten |
|---|---|
| „Plane Spec `<pfad>` als `<slug>`“ | Schleife bis Plan-Review `result`, dann Stopp und Bericht |
| „Plane Spec `<pfad>` als `<slug>` und führe ihn aus“ | Schleife bis `done` |
| „Führe Plan `<slug>` aus“ | Einstieg beim ersten offenen Schritt |

Einzelaufgaben ohne Plan laufen unverändert. Pro Session ein Plan.

**Schleife**

```
1  lean-herdr plan next <slug>
2  done        → dispatch remember --key lean-herdr/plan/<slug>, Stopp, Bericht
   escalate    → Eskalation
   merge       → Aufräumen (unten)
   await       → nur Schritt c mit der gelieferten task_id
   sonst:
   a  lean-herdr dispatch --work <work> --worktree plan/<slug>
   b  lean-herdr dispatch order --to <agent> --plan <slug> --step <step> [--plan-task N|branch] [--spec <pfad>]
        [--after o-…] --message "<Task N von Plan <slug> | Spec <pfad> | Befunde>"
   c  lean-herdr dispatch --work <work> --await --task-id o-… --worktree plan/<slug>
        [--prereview, wenn step = implement (Task) oder plan und round = 1]
3  zurück zu 1
```

- Selbst auswerten muss der Orchestrator zwei Dinge: `error: input_required`
  (`dispatch answer`, dann erneut warten) und `prereview: reject` (ein Folgeauftrag desselben
  Schritts mit `--after o-…` und `prereview_note`, abgewartet ohne `--prereview`; `plan next`
  zählt ihn als Runde 2).
- **Aufräumen bei `merge`**, ohne Squash:
  1. `herdr worktree list --cwd <repo_root>` → `path`, `open_workspace_id` von `plan/<slug>`
  2. `herdr workspace close <workspace_id>`
  3. `wt -C <path> merge main --yes --no-commit`

  Plan- und Task-Commits landen rebased auf `main`, das Gate läuft, `--no-commit` lehnt bei
  unfertiger Arbeit ab. Kein Push.
- **Eskalation** wie bisher (Token `esc`, Meldung im Terminal) mit dem Grund aus
  `plan next`, außerdem bei fehlgeschlagenem Gate und `Cannot merge with --no-commit`.

## 8. `workspace init` und `workspace check`

- `init`: `--lang python` (Standard); lean-md-Einrichtung (§4); neue und geänderte Templates
  mit Lock; `bin/pylsp` mit Ausführungsrecht.
- `check`, nur Warnungen:
  - `lean-md` fehlt auf `PATH` oder kennt `outline` nicht (braucht 0.2.4); Probe: `lean-md outline - --json` mit leerem Dokument auf stdin; vorhanden nur, wenn stdout ein JSON-Objekt mit `phases` ist (0.2.3 endet bei einem unbekannten Unterbefehl ebenfalls mit Exit 1)
  - kein Gateway-Eintrag `lean-md` in `~/.config/lean-ctx/config.toml`, oder
    `LEAN_MD_SKILLS_DIR` zeigt auf kein Verzeichnis
  - `.claude/skills/lmd-writing-plans` fehlt
  - `ty` fehlt bei `--lang python`
  - eine Datei aus §4, die `git ls-files` nicht kennt
- Prompt, Artefakt und Pflichtsätze von `plan-writer` und `plan-reviewer` prüft der
  bestehende Mechanismus aus TP1 (B7) mit, weil beide jetzt hinter eingebauten
  Arbeitsarten stehen.

## 9. Fehlerbild

| Lage | Antwort |
|---|---|
| `plan/<slug>` und `main` ohne Plan-Datei | `plan check/show`: `{ok: false, error: "no_plan: …"}`; `plan next` ohne Plan-Auftrag: `{step: plan}` |
| `lean-md` fehlt oder kennt `outline` nicht (stdout ist kein JSON-Objekt mit `phases`) | `config_error: lean-md outline unavailable (needs lean-md >= 0.2.4)` |
| Befunde aus `outline` oder §3 | `plan check`: `ok: false`, `errors[]` mit `kind`, `line`, `phase`, `message` |
| Slug verfehlt `[a-z][a-z0-9-]{0,11}` | `usage_error` |
| unzulässige Kombination `--plan/--step/--plan-task/--spec` | `usage_error`, nichts im Log |
| `plan brief` für einen Auftrag ohne Plan | stderr `order o-… belongs to no plan`, Exit 1 |
| `wt list` scheitert bei `report` | `ok: true`, Event mit `wt_error` |
| Agent-Name über 32 Zeichen | `config_error` vor dem Pane |
| `.lean-ctx/lean-herdr/bin` fehlt | kein `PATH`-Zusatz, kein Fehler |

Alle JSON-Befehle: eine Zeile mit `ok`, Exit 0, nie eine Exception zum Aufrufer.

## 10. Tests

| Bereich | Inhalt |
|---|---|
| `plan.py` | jede Regel aus §3 mit Outline-JSON als Fixture; Durchreichen der `outline`-Fehler; Fallback auf `main`; `config_error` ohne `outline` |
| `planrun.py` | jede Zeile aus §6.4, rein, ohne I/O |
| `plancmd.py` | JSON-Vertrag; Klartext und Exit 1 bei `brief`; Briefs je `step` mit Doubles für `git show`, `lean-md` und `wt` |
| `dispatch` / `ordercmd` / `orders` | `--plan/--step/--plan-task/--spec`-Prüfung, Payload, `Order`-Felder; Namenslänge; `PATH` im `--env` nur bei vorhandenem `bin` |
| `report` | `head`/`changes` über ein `wt`-Double; `wt_error` |
| `llm` | `prereview_result` mit `base` (Diff ab SHA) und Prompt-Wahl; `PLAN_PREREVIEW_PROMPT`; `llm prereview --base --plan`; `await_task` nutzt `plancmd.prereview_input` nur bei Plan-Aufträgen; Grenze für Diff und Auftragsbild |
| `settings` | eingebaute Zuordnung `plan`/`plan-review`; Modell-Warnung `plan-review` gegen `plan` |
| Rechte | kein Worker bekommt `dispatch`; kein Worker darf pushen oder mergen; neue Allowlist-Einträge |
| Rollen-Prompts | Pflichtsätze der neuen Rollen; Schritt `plan brief` in allen Worker-Prompts; `orchestrator.md` nennt `plan next` |
| Templates | Parität und Lock für alle neuen Dateien, Ausführungsrecht von `bin/pylsp` |
| `init` / `check` | Aufruf von `lean-md skill install` über ein Double, `--lang`, neue Warnungen |

## 11. Mess-Tasks am Anfang des Plans

1. `wt step diff <sha>` mit einem Commit als Ziel liefert Commits und ungetrackte Dateien
   seit dem Commit — danach als Test festgeschrieben.
2. Ein lokales `@define commit` in `herdr-recipes` gewinnt gegen das `@define` aus dem
   `@import` von `plan-recipes`.
3. `herdr pane split --env PATH=…`: Das Verzeichnis steht nach dem Start von zsh im Pane
   noch vorn im `PATH`.
4. `lean-md outline --json` 0.2.4 ist über den Shim erreichbar (Voraussetzung TP0).

Scheitert eine Messung, endet die Task mit BLOCKED; nichts wird geraten.

## 12. Doku

| Datei | Abschnitt | Änderung |
|---|---|---|
| `README.md` | How it works | Plan-Modus, fünf Rollen, Ablauf Plan → Check → Review → Tasks → Branch-Review → Merge |
| | The work-order path | `order --plan/--step/--plan-task/--spec`; Pre-Review im Plan-Modus; `plan next\|show\|check\|brief`; `head`/`changes` |
| | What else ships here | Plan-Template, Rezepte, Briefs, `lang/python`, `bin/pylsp` |
| | Setting up a project | `--lang`, lean-md-Einrichtung, neue Dateizahl, `ty` |
| | Configuration | `[routing]` mit `plan`/`plan-review`; Beispiel `[roles.plan-writer]` |
| `INSTALL.md` | Runtime dependencies | lean-md ≥ 0.2.4 (von Hand installiert), `ty` |
| | Approvals / Updating | neue Allowlist-Einträge; `init --update` richtet lean-md erneut ein |

## 13. Nicht-Ziele

- parallele Spuren, Rolle integrator, Push (TP3)
- automatische Kürzung von Agent-Namen (TP3)
- Anbieterwahl und Provider-Pinning (eigenes Teilprojekt)
- Skill-Feld in `[roles.*]`; Python-Paket als lean-md-Seed; weitere Sprachen für `--lang`
- lean-md-Companion-Overlays
- Schließen der `ctx_shell`-Lücke
- Pre-Review für `review`, `plan-review` und `implement` über den ganzen Branch
- `[lsp]` in projekt-lokaler `.lean-ctx.toml` (lean-ctx-Änderung)

## 14. Randbedingungen

- Keine Datei unter `lean_herdr/` über 800 Produktions-LOC, Ziel 600. `dispatch.py` (581)
  bekommt nur die Order-Flags, den `PATH`-Zusatz und die Längenprüfung; die Plan-Logik
  liegt in den neuen Modulen. Vor dem Plan neu messen.
- Code, Prompts, Briefs, README, INSTALL und Commits Englisch; diese Spec Deutsch.
- Eingecheckte Kopien bleiben byte-identisch mit ihren Templates; jede neue Datei bekommt
  einen Lock-Eintrag.
- Tests rufen weder das echte `lean-md` noch `wt` oder `herdr` auf; sie nutzen Doubles.

## 15. Abnahme

- Alle Tests grün, `workspace check` in diesem Repo ohne neue Fehler.
- Ein Plan mit einer Task läuft in einem Wegwerf-Repo unter `~/Scripts` nach `init` und
  Commit von „Plane Spec … und führe ihn aus“ bis `done` durch.
- Der FastAPI-Testlauf folgt nach dem Teilprojekt Anbieterwahl.

## 16. Offen für spätere Teilprojekte

- Anbieterwahl: Rangliste aus `/models/<id>/endpoints` (Preis nach Rabatt, Durchsatz- und
  Latenz-Perzentile, Uptime), Pinning über `provider.order` in `opencode.jsonc` und ein
  `provider`-Feld in `llm.py`, Fallback über `allow_fallbacks` und
  `preferred_min_throughput`/`preferred_max_latency`.
- TP3: Spuren parallel, Integrator, Merge nach `plan/<slug>`, Push, Kürzung der Namen.
- lean-ctx: `[lsp]` aus vertrauter lokaler Config übernehmen oder `ty server` als
  Python-Standard; `symbols_overview` mit `ty`.
