# lean-herdr: Planausführung mit konfigurierbaren Agents — Gesamtbild und Teilprojekt 1 „Rollen und Routing" — Design v1.0

**Stand:** 2026-09-14 · **Status:** Teil A beschlossen · Teil B entworfen, nicht implementiert
**Anlass:** Die nächste Ausbaustufe: Der lean-herdr-Orchestrator führt Pläne aus, die mit
lean-md geschrieben sind, und verteilt ihre Tasks an Agents, deren Rolle, Modell und
Rechte die Konfiguration bestimmt. Das Brainstorming hat oh-my-opencode-slim, den
lean-md-Skill `lmd-subagent-driven-development` und lean-herdr verglichen, gemessen und
die Arbeit in drei Teilprojekte zerlegt.
**Bezug:** `2026-09-01-lean-herdr-design.md` (Sterntopologie, B3),
`2026-09-01-lean-herdr-ctx-task-design.md` (PID-Join, B-2),
`2026-09-03-lean-herdr-auftragslog-design.md` (Auftragslog),
`2026-09-04-lean-herdr-rollenmodelle-und-katalog-design.md` (`[roles.*]`)
**Betrifft:** Teil A — nur `docs/specs/`. Teil B — `lean_herdr/settings.py`,
`lean_herdr/dispatch.py`, `lean_herdr/workspace.py`, `lean_herdr/checkcmd.py`,
`lean_herdr/templating.py` (`LAYOUT`), `lean_herdr/templates/` (`config.toml`,
`opencode.jsonc`, `roles/orchestrator.md`, neu `claude/*.json`), die eingecheckten Kopien
samt `.lean-ctx/lean-herdr/templates.lock.json`, `README.md`; Tests in
`test_settings.py`, `test_dispatch*.py`, `test_checkcmd.py`, `test_initcmd.py`,
`test_worker_permissions.py`, `test_role_prohibitions.py`, `test_templates.py`.

---

# Teil A — Gesamtbild

## A1. Ablauf

```
Betreiber + lmd-brainstorm (eigene Session) ─► Spec (docs/specs, main)
                        │ Anweisung: „Plan-Writer mit Spec Y, dann ausführen" oder „Plan X ausführen"
Orchestrator (Pane; liest keine Dateien, nur JSON von lean-herdr)
 1 dispatch --work plan ────────► Plan (.lmd.md, auf main committet)
 2 lean-herdr plan check ───────► Befunde → neuer Auftrag an den Plan-Writer
 3 dispatch --work plan-review ─► VERDIKT reject → neuer Auftrag an den Plan-Writer
                                  (höchstens N Runden, dann Eskalation)
 4 lean-herdr plan show ────────► Spuren und Tasks als JSON; Branch plan/<slug> von main
 5 je Spur, parallel bis zur Obergrenze: Worktree plan/<slug>--<spur>
      je Task: dispatch --work <Arbeitsart> → report → dispatch --work review → VERDIKT
 6 Spur fertig: dispatch --work integrate ─► wt merge plan/<slug> (seriell)
 7 alle Spuren gemergt: dispatch --work review (Branch)
      → dispatch --work integrate ─► wt merge main, push origin
```

| Beziehung | Kanal |
|---|---|
| Orchestrator ↔ jeder Agent | Auftragslog, adressiert über den Herdr-Namen |
| Befunde einem Agent zuordnen | Bus-Posts pro Pane-Agent, gelesen über `bus.parse_registry(from_agent=…)` |
| Pane-Agent ↔ eigener Subagent | Rückgabewert des Agent- bzw. `task`-Tools |
| Wissen über Tasks hinweg | `ctx_knowledge` |

## A2. Entscheidungen

| # | Entscheidung |
|---|---|
| E1 | lean-herdr steuert die Ausführung; der Orchestrator bleibt der einzige, der `dispatch` aufruft (Sterntopologie). |
| E2 | Specs entstehen in einer eigenen Session mit `lmd-brainstorm`; ein Plan-Writer-Agent schreibt daraus den Plan; der Orchestrator führt nur fertige Pläne aus. |
| E3 | Der Plan nennt keine Agents. Jede Task trägt eine Arbeitsart; `[routing]` in der Config ordnet Arbeitsarten Rollen zu. |
| E4 | lean-md-Direktiven (`@phase`, `@call`, `@symbol` …) bleiben. Plan-Template und Rezepte werden vorerst lokal unter `.lean-ctx/lean-md` angepasst, ohne lean-md-Release. |
| E5 | Routing im Plan über Rezepte: `@call route(work, lane, files)` als erste Zeile jeder Task, Spuren in `@phase "lanes"` über `@call lane(name, deps)`. |
| E6 | Parallelität über Spuren (Ansatz 1): der Plan-Writer schneidet Spuren; ein wt-Worktree pro Spur, abgezweigt von `plan/<slug>`; Tasks innerhalb einer Spur nacheinander, Spuren parallel; Abhängigkeiten nur zwischen ganzen Spuren; der Integrator mergt Spuren seriell. |
| E7 | Prüfung vor der Ausführung zweistufig: `lean-herdr plan check` (deterministisch), dann ein Plan-Reviewer-Agent für das, was Urteil braucht (versteckte Abhängigkeiten, Dateilisten, Konflikt-Brennpunkte, Zuschnitt). |
| E8 | Jeder Review ist ein eigener Pane-Agent, gestartet vom Orchestrator. In-Session-Subagents gibt es nur innerhalb von Pane-Agents, für Arbeit ohne eigene Zuordnung. |
| E9 | `lmd-finishing-a-development-branch` wird aufgeteilt: Review durch einen Review-Agent, wt/git/Push durch einen Integrator-Agent, geführt vom Orchestrator. Der Integrator übernimmt die Teardown-Folge aus `orchestrator.md`; das bisherige Nicht-Ziel „kein Push" entfällt für ihn. |
| E10 | Keine doppelte Arbeit: vorhandene Module (`dispatch`, `worktree`, `ordercmd`, `report`, `llm`, `bus`, `join`, `leanctx`, `templating`) werden wiederverwendet oder erweitert, nicht nachgebaut. |

## A3. Messungen vom 2026-09-14

| Messung | Ergebnis |
|---|---|
| `ctx_agent register` aus der Claude-Hauptsession, dann aus einem ihrer Subagents | beide `mcp-19940-6a6bfe85…`; der Subagent überschreibt Typ und Rolle; `list` zeigt einen Agent |
| dasselbe in opencode 1.18.29 (Pane, Agent „Build") mit einem `task`-Subagent | beide `mcp-106120-95a1133f…`, gleiches Überschreiben; `list` zeigt je Pane einen Agent |
| Folgerung | Eine lean-ctx-Identität je MCP-Server-Prozess, praktisch je Pane. Subagents können nicht über `ctx_agent` adressiert werden; `dispatch()` liefert eine eigene `agent_id` nur für Pane-Agents. |
| `wt switch --create plan/x--l1 --base plan/x` | legt Branch und Worktree vom Plan-Branch an |
| zwei Worktrees mit getrennten Dateien, nacheinander `wt merge plan/x --no-commit --no-remove` | der zweite wird automatisch rebased und per Fast-Forward gemergt |
| zwei Worktrees ändern dieselbe Zeile | `wt merge` endet mit exit 1, der Rebase bleibt im Worktree offen (`UU`) |
| Plan-Branch selbst in einem Worktree geöffnet, dann Merge einer Spur | gelingt; der Worktree des Plan-Branches zieht mit |
| `lean-md render <plan> --list-phases` | liest den Rohtext, wertet nichts aus; der Titel ist die erste wörtliche Überschrift (`lean-md/src/phases.rs` `phase_title`) — eine Überschrift aus einem Makro sieht es nicht |
| `@call` innerhalb `@phase` | wird bei `--phase` aufgelöst; HTML-Kommentare aus dem Makro bleiben erhalten; der Beschreibungskommentar des Makros wird bei jedem Aufruf mitgerendert |
| Claude Code `--settings <datei>` | Rechte-Arrays werden über alle Quellen zusammengeführt; ein `deny` gewinnt über jedes `allow` (Doku `settings`, `permissions`); `--setting-sources` schaltet auch Projekt-`CLAUDE.md` und Skills ab |

## A4. Vergleich, Kurzfassung

| | oh-my-opencode-slim | lean-md SDD | lean-herdr |
|---|---|---|---|
| Steuerung | starkes Modell in der OpenCode-Session | Claude-Hauptsession | günstiges Modell im Pane, liest keine Dateien |
| Plan | Todo-Liste im Chat | `.lmd.md`, Task einzeln renderbar | keiner |
| Transport | OpenCode-Background-Tasks | Agent-Tool, `ctx_agent` | eigene Prozesse in Panes, Auftragslog |
| Isolation | Worktrees nur als Skill | ein Checkout | wt-Worktree je Branch |
| Review | optional | zwei Urteile je Task + Branch | Pflicht, anderes Modell |
| Rechte | meist nur im Prompt | Prompt | opencode je Rolle, claude geteilt |

Übernommen: Agent als Konfigurationseintrag, Zuordnung über die Config statt fester
Kette im Orchestrator-Prompt, Obergrenze für Parallelität. Nicht übernommen: Rechte nur
im Prompt, Zustand im Speicher, unbegrenzte Parallelität als Standard, stilles
Weiterlaufen bei ungültiger Config.

## A5. Teilprojekte

| TP | Inhalt | Spec |
|---|---|---|
| 1 | Rollen und Routing: `[routing]`, `dispatch --work`, Rechte je Rolle, verallgemeinerte Modell-Warnung, `orchestrator.md` ohne Rollennamen | Teil B dieses Dokuments |
| 2 | Plan: Template und Rezepte (`route`, `lane`) unter `.lean-ctx/lean-md`, `lean-herdr plan start\|show\|check`, Rollen plan-writer und plan-reviewer mit ihren Overlays | eigene Spec |
| 3 | Ausführung in Spuren und Abschluss: Basis für `ensure_worktree`, Kürzung der Agent-Namen, Warten auf mehrere Aufträge, Rolle integrator mit Merge nach `plan/<slug>` und `main` samt Push, Overlays für SDD und Finishing | eigene Spec |

Reihenfolge 1 → 2 → 3: `plan check` braucht `[routing]`, die Ausführung braucht das
Plan-Format.

Offen für die Specs von TP2 und TP3, hier bewusst nicht entschieden:

- Überschneidende Dateien paralleler Spuren: ablehnen oder nur melden.
- Squash je Spur oder Task-Commits behalten.
- Standard der Spuren-Obergrenze und der Plan-Review-Runden.
- Kürzungsregel für Agent-Namen: Herdr erlaubt `[a-z][a-z0-9_-]{0,31}`, `agent_name()`
  prüft keine Länge.
- Nachweis des Plan-Reviews über Bus-Posts (`LeanCtx.post` / `bus.parse_registry`).
- Umgang der Plan-Rezepte mit dem mitgerenderten Beschreibungskommentar.

---

# Teil B — Teilprojekt 1: Rollen und Routing

## B1. Ausgangslage

| Befund | Beleg |
|---|---|
| Die Kette builder → reviewer steht fest im Orchestrator-Prompt | `roles/orchestrator.md` „Sequence per task", „`[roles.builder]` and `[roles.reviewer]`" |
| Der Orchestrator tippt Rollenname und Prompt-Pfad | `orchestrator.md` Schritt 1 `--role-file .lean-ctx/lean-herdr/roles/<role>.md`; `dispatch.py:718-724` verlangt `--role-file` im Build-Modus; eigener Test `test_role_prohibitions.py:253` |
| Rollennamen sind frei, aber nicht als Ziel einer Arbeitsart | `settings.settings_for` (`settings.py:226`) nimmt jeden Namen; es gibt keinen Schlüssel für Arbeitsarten (`ROOT_KEYS`, `settings.py:126`) |
| Die Modell-Warnung kennt nur zwei Rollen | `model_warnings` vergleicht fest builder und reviewer (`settings.py:258-259`); `dispatch.main` hängt sie nur an `reviewer` (`dispatch.py:849`); Opt-out `shares_builder_model` (`settings.py:101`) |
| Die opencode-Prüfung kennt nur den Orchestrator | `workspace.missing_agent_config` sucht nur `agent.orchestrator` (`workspace.py:168`) |
| Alle claude-Worker teilen eine Allowlist | `.claude/settings.json` erlaubt u. a. `git add`, `wt step commit` — auch einem claude-Reviewer; `agent_args` gibt claude nur `--model` und `--append-system-prompt-file` (`dispatch.py:161-169`) |
| lean-ctx-Schreibwerkzeuge umgehen Bash-/Edit-Regeln | opencode-Reviewer: `edit`/`write` `deny`, Bash-Muster (`opencode.jsonc`), aber keine Regel für `lean-ctx_ctx_patch`, `_ctx_edit`, `_ctx_refactor` |
| Pflichtsätze sind je Datei gepinnt | `PROHIBITIONS` und `MANDATORY_SENTENCES` in `tests/test_role_prohibitions.py:31`, `:124` |

## B2. `[routing]`

Neuer Top-Level-Schlüssel in `ROOT_KEYS`. Er ordnet Arbeitsarten Rollen zu.

```toml
[routing]
implement = "builder"
review    = "reviewer"
rename    = "refactorer"   # eigene Arbeitsart

[roles.refactorer]
kind  = "opencode"
model = "…"
```

**Eingebaut in TP1:** `implement = "builder"`, `review = "reviewer"`. Ohne `[routing]`
verhält sich das Projekt wie heute.

**Reserviert** (Stufen): `plan`, `plan-review`, `review`, `integrate`. `plan`,
`plan-review` und `integrate` bekommen ihre eingebauten Ziele erst mit TP2 und TP3;
bis dahin ist ein Aufruf dieser Arbeitsarten ohne Eintrag in `[routing]` ein Fehler
(`config_error: no role for work 'plan'`). Eine Stufe kann nicht als Arbeitsart eines
Plans dienen — das prüft TP2.

**Namen:**
- Arbeitsart: `[a-z][a-z0-9-]*`.
- Zielrolle: `[a-z][a-z0-9_-]*` — sie wird Teil des Herdr-Agentnamens. Die Längengrenze
  gehört zu TP3.
- Ein Wert, der kein String ist oder das Muster verfehlt: `SettingsError`. Geprüft wird
  in `_check_root`, also von jedem Leser der Datei — auch ein Aufruf per Rollenname
  meldet einen kaputten `[routing]`-Eintrag.

**Auflösung:** eine Funktion `role_for_work(work, data) -> str` in `settings.py`:
`[routing]` > eingebauter Wert > `SettingsError`. Eine Stelle, von `dispatch` und
`workspace check` gleich benutzt.

## B3. `lean-herdr dispatch --work`

```
lean-herdr dispatch --work rename [--worktree <branch>] [--profile …] [--model …] [--kind …]
lean-herdr dispatch --work rename --await --task-id o-… [--worktree <branch>] [--prereview]
```

- `--work <art>` löst über B2 die Rolle auf und verhält sich dann genau wie der Aufruf
  mit diesem Rollennamen. Gilt für Bauen und Warten.
- Das Positional `command` wird optional. Genau eins von beiden: Rollenname /
  Log-Befehl **oder** `--work`. Beides oder keins: `usage_error`. `--work` zusammen mit
  einem Log-Befehl ist ein streunendes Flag nach der Doktrin von `missing_flags()`.
- `--role-file` wird optional. Standard: `.lean-ctx/lean-herdr/roles/<rolle>.md`. Ein
  angegebenes `--role-file` gewinnt, ändert aber nur die Prompt-Datei.
- **Bezugspfad:** Prompt-Datei und claude-Datei werden gegen `canonical_root()` zu
  absoluten Pfaden aufgelöst, bevor sie geprüft und an den Agent übergeben werden. Heute
  reicht `dispatch` ein relatives `--role-file` unverändert durch, und claude löst es im
  Pane-Verzeichnis auf — im Worktree, dem die Datei fehlen kann.
- **Rollenname, nicht Dateistamm:** `agent_args(kind, model, role_file, role)` bekommt
  die Rolle. opencode startet mit `--agent <rolle>` statt `--agent <role_file.stem>`
  (`dispatch.py:168`); claude bekommt
  `--settings <root>/.lean-ctx/lean-herdr/claude/<rolle>.json`. Die Prüfungen unten nutzen
  denselben Rollennamen.
- Die Antwort im Build-Modus trägt zusätzlich `role`. `agent`, `pane`, `agent_id`
  bleiben.
- Der Aufruf mit Rollennamen bleibt für Handarbeit erhalten.

**Prüfung vor dem Start** (Build-Modus, egal ob über `--work` oder Rollennamen), in
dieser Reihenfolge, jede mit eigenem Text:

1. Prompt-Datei fehlt → `config_error: no role prompt at <pfad>`.
2. `kind = "opencode"` und kein `agent.<rolle>` in `opencode.jsonc` →
   `config_error: <Text aus missing_agent_config>`. `missing_agent_config(root, kind)`
   bekommt den Agentnamen als Parameter; die beiden bisherigen Aufrufer
   (`workspace.py`, `checkcmd.py:467`) übergeben weiterhin `orchestrator`.
3. `kind = "claude"` und keine `.lean-ctx/lean-herdr/claude/<rolle>.json` →
   `config_error: no claude settings at <pfad>`.

Nichts davon startet ein Pane. Alles wird vor `pane_split` geprüft.

## B4. Rechte je Rolle

**opencode:** unverändert `agent.<rolle>.permission` in `opencode.jsonc`. Neu: jede
Rolle, die nicht schreiben darf (heute `orchestrator`, `reviewer`), sperrt zusätzlich die
lean-ctx-Schreibwerkzeuge `ctx_patch`, `ctx_edit`, `ctx_refactor` im Agent-Block. Die
genaue Schreibweise (Werkzeugschalter oder Permission-Schlüssel für MCP-Werkzeuge) misst
eine eigene, frühe Task des Plans gegen opencode 1.18.29, bevor ein Test sie festschreibt.

**claude:** jede claude-Rolle hat eine Datei `.lean-ctx/lean-herdr/claude/<rolle>.json`;
`agent_args("claude", …)` hängt `--settings <datei>` an.

```json
// .lean-ctx/lean-herdr/claude/reviewer.json
{ "permissions": { "deny": [
  "Edit", "Write", "NotebookEdit",
  "Bash(git add:*)", "Bash(git commit:*)", "Bash(wt step commit:*)",
  "mcp__lean-ctx__ctx_patch", "mcp__lean-ctx__ctx_edit", "mcp__lean-ctx__ctx_refactor"
] } }
```

```json
// .lean-ctx/lean-herdr/claude/builder.json
{}
```

- `.claude/settings.json` bleibt unverändert; die Sessions des Betreibers merken nichts.
- `deny` gewinnt über jedes `allow` aus jeder Quelle (A3), deshalb reicht die Datei zum
  Einschränken.
- `--setting-sources` wird nicht verwendet (A3: schaltet Projekt-`CLAUDE.md` und Skills ab).
- Beide Dateien sind Templates mit Lock wie die übrigen (`initcmd`, `templating`).

**Bekannte Lücke, nicht Teil von TP1:** `ctx_shell` bleibt für Prüfer offen, weil sie
lesen müssen, und kann trotzdem schreibende Befehle ausführen. Die Shell-Allowlist von
lean-ctx ist global, nicht je Rolle. Dieselbe Lücke besteht heute für opencode.

## B5. Rollen-Prompts

- Bleiben je Rolle eine vollständige Datei. Kein Zusammensetzen aus Bausteinen; die
  Wiederholung von Trust, `report`-Ablauf und BOUNDARY bleibt und wird abgesichert (B8).
- Kein Skill-Feld in der Config; ein Prompt nennt seinen lean-md-Skill selbst.
- `orchestrator.md`, nur der Tooling-Teil und die Stellen mit Rollennamen:
  - Schritt 1 wird `lean-herdr dispatch --work <art> [--worktree <branch>]`; kein
    `--role-file`, keine Rollennamen.
  - Schritt 3 wird `lean-herdr dispatch --work <art> --await --task-id o-… …`.
  - „Sequence per task" spricht von `--work implement` und `--work review` statt von
    builder und reviewer; die Reihenfolge selbst, Prereview, Teardown und Eskalation
    bleiben unverändert (Teardown wandert erst mit TP3).
  - „Model and runtime" verweist auf `[routing]` und `[roles.<rolle>]` allgemein.
- `builder.md` und `reviewer.md` bleiben unverändert.

## B6. Modell-Warnung, verallgemeinert

- `model_warnings(data)` vergleicht die Rolle hinter `review` mit jeder Rolle hinter
  einer Arbeitsart, die keine Stufe ist (`implement` und eigene). Gleiches, nicht leeres
  Modell → eine Warnung je Paar, außer die prüfende Rolle setzt
  `shares_reviewed_model = true`. Zeigen beide Arbeitsarten auf dieselbe Rolle, entsteht
  kein Paar.
- `shares_builder_model` wird ersatzlos zu `shares_reviewed_model`. Der alte Schlüssel
  ist danach unbekannt und damit ein `SettingsError` mit Hinweis im README.
- `dispatch.main` hängt die Warnungen an jede Build-Antwort, deren Rolle die Rolle hinter
  `review` ist — über `--work review` oder den Rollennamen.
- `plan-review` gegen `plan` kommt mit TP2 dazu, über dieselbe Funktion.

## B7. `workspace check`

Zusätzliche Befunde in `workspace check` (Warnungen, kein Abbruch), über
`role_for_work` und dieselben Prüfungen wie B3. Die feste Rollenliste `checkcmd.ROLES`
(`checkcmd.py:65`) wird um die Zielrollen aus `[routing]` ergänzt, damit auch eine eigene
Rolle wie `refactorer` geprüft wird.

- Jede Arbeitsart aus `[routing]` und jede eingebaute: die Zielrolle hat eine
  Prompt-Datei.
- Artefakt je `kind`: Ist `kind` der Rolle gesetzt (Config oder eingebauter Wert), wird
  genau das Artefakt dieser Art geprüft — opencode-Block oder claude-Datei. Ist `kind`
  leer — der Normalfall nach `init`, weil Worker keine eingebaute Art haben —, gibt es
  eine Warnung „`[roles.<rolle>].kind` unset: `dispatch --work <art>` needs --kind" und
  keine Artefakt-Prüfung.
- Jeder Rollen-Prompt hinter einer Arbeitsart außer dem Orchestrator enthält die
  Pflichtsätze `lean-herdr report start`, `ORCHESTRATOR = orch` und
  „Never pass `--agent`.".

## B8. Fehlerbild

| Lage | Antwort |
|---|---|
| Arbeitsart ohne Zielrolle | `config_error: no role for work '<art>'` |
| Arbeitsart oder Rolle verfehlt das Namensmuster | `config_error: …` beim Laden |
| Rollenname und `--work` zugleich, oder keins | `usage_error: …` |
| Prompt-Datei fehlt | `config_error: no role prompt at <pfad>` |
| opencode-Block fehlt | `config_error: <missing_agent_config>` |
| claude-Datei fehlt | `config_error: no claude settings at <pfad>` |
| `shares_builder_model` gesetzt | `config_error: unknown key …` |

Alle Antworten bleiben eine JSON-Zeile mit `ok`, Exit 0.

## B9. Tests

- `settings`: eingebaute Zuordnung; `[routing]` überschreibt; `plan` ohne Eintrag ergibt
  `config_error: no role for work 'plan'`; Namensmuster, schon beim Laden gemeldet — auch
  bei einem Aufruf per Rollenname; unbekannte Arbeitsart; `ROOT_KEYS` enthält `routing`.
- `dispatch`: `--work` löst Rolle, Prompt-Pfad, `kind`, `model` auf und liefert `role`;
  Rollenname allein funktioniert weiter; beides oder keins → `usage_error`; `--work` mit
  Log-Befehl → `usage_error`; die drei Vorab-Prüfungen aus B3 starten kein Pane (der
  Fake-Herdr sieht kein `pane split`); ein relatives `--role-file` wird gegen die Wurzel
  aufgelöst; opencode bekommt `--agent <rolle>`. Bestehende Dispatch-Tests, die heute
  nicht existierende Prompt-Pfade übergeben (u. a. `test_dispatch.py`,
  `test_dispatch_await.py`), bekommen Fixture-Dateien — Prompt und, bei `kind = claude`,
  `claude/builder.json`.
- `agent_args`: claude enthält `--settings <.lean-ctx/lean-herdr/claude/<rolle>.json>`.
- Rechte: die `deny`-Liste jeder nicht schreibenden claude-Rolle enthält `Edit`, `Write`,
  `NotebookEdit`, die drei lean-ctx-Schreibwerkzeuge und jede Regel aus
  `.claude/settings.json` außer den `lean-herdr report`-Befehlen und den beiden
  Gate-Befehlen (`{test}`/`{lint}` des Templates); der bestehende Test „kein Worker bekommt `dispatch`" läuft über
  alle Rollen-Dateien beider Arten; die opencode-Sperre der lean-ctx-Schreibwerkzeuge für
  `orchestrator` und `reviewer`.
- `model_warnings`: Paare `review` gegen `implement` und gegen eine eigene Arbeitsart;
  Opt-out `shares_reviewed_model`; leeres Modell warnt nicht; dieselbe Rolle auf beiden
  Seiten warnt nicht; bestehende Tests mit `shares_builder_model` (`test_settings.py`,
  `test_initcmd.py`) ziehen auf den neuen Namen um.
- `missing_agent_config` mit beliebigem Agentnamen.
- `workspace check`: fehlender Prompt, fehlender Block, fehlende claude-Datei, leeres
  `kind`, fehlender Pflichtsatz; eine eigene Rolle aus `[routing]` wird mitgeprüft.
- Rollen-Prompts: `PROHIBITIONS`/`MANDATORY_SENTENCES` für `orchestrator.md` an die neuen
  Befehle angepasst; `test_the_role_file_path_the_orchestrator_types_actually_resolves`
  wird ersetzt durch „`orchestrator.md` nennt `--work` und kein `--role-file`".
- Templates: Parität und Lock für `claude/builder.json`, `claude/reviewer.json`.

## B10. Nicht-Ziele

- Kein lean-ctx-Kontext-Profil (`LEAN_CTX_PROFILE`) je Rolle.
- Kein Skill-Feld in `[roles.*]`.
- Keine aus Bausteinen gerenderten Rollen-Prompts.
- Keine neuen Rollen (plan-writer, plan-reviewer, integrator — TP2/TP3).
- Keine Änderung an Teardown, Merge oder Push (TP3).
- Keine Längenprüfung für Agent-Namen (TP3).
- Keine Schließung der `ctx_shell`-Lücke (B4).

## B11. Randbedingungen

- Keine Datei unter `lean_herdr/` über 800 Produktions-LOC (Ziel 600). Gemessen am
  2026-09-14 ohne Leer-, Kommentar- und Docstring-Zeilen: `dispatch.py` 531,
  `checkcmd.py` 355, `settings.py` 270, `workspace.py` 258. Die Auflösungslogik gehört
  nach `settings.py`; `dispatch.py` bekommt nur das Flag und die Vorab-Prüfungen und wird
  vor dem Plan neu gemessen.
- Sprache: Code, Prompts, README, Commits Englisch; diese Spec Deutsch.
- Eingecheckte Kopien bleiben byte-identisch mit ihren Templates
  (`tests/test_templates.py`); neue Templates bekommen einen Lock-Eintrag.
- Vertrag der CLI: eine JSON-Zeile mit `ok`, Exit 0, nie eine Exception zum Aufrufer.
