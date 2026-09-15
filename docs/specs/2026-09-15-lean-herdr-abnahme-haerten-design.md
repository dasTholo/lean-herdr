# lean-herdr: Befunde der TP2-Abnahme härten — Design v1.0

**Stand:** 2026-09-15 · **Status:** entworfen, nicht implementiert
**Anlass:** Die Abnahme von TP2 (Plan C, Task 9) lief in `~/Scripts/lh-plan-probe` bis `done` —
aber nur mit Eingriffen. Ein claude-Worker hing im frischen Worktree am Ordner-Vertrauensdialog,
und der Orchestrator bestätigte ihn selbst per Tastendruck. Der Merge scheiterte an ungetrackten
`__pycache__/`-Verzeichnissen, und die Eskalation fand ihren Workspace nicht mehr, weil er schon
geschlossen war. Rollen ohne `model` fielen erst beim ersten `dispatch` auf, und
`wt config approvals add` verweigerte ohne Terminal.
**Bezug:** `2026-09-14-lean-herdr-plan-design.md` (§5.3 Rechte, §6 Plan-Modus, §8 Check, §15 Abnahme);
Plan C `docs/lean-md/plans/2026-09-14-lean-herdr-plan-c-ausliefern.lmd.md` (Task 9);
`2026-09-13-lean-herdr-haerten-und-uv-tool-design.md` (`_check_temp_ignored`).
**Betrifft:** neu `lean_herdr/dialogs.py`; geändert `lean_herdr/herdr.py`, `dispatch.py`,
`checkcmd.py`; `lean_herdr/templates/` (`roles/orchestrator.md`, `roles/builder.md`,
`briefs/implement.lmd.md`, `briefs/review.lmd.md`, `opencode.jsonc`, `claude/orchestrator.json`)
samt eingecheckten Kopien und Lock; `README.md`, `INSTALL.md`; Tests.

---

## 1. Ziel und Abnahme

Nach `workspace up` braucht ein Plan-Lauf keinen Menschen mehr, solange nichts Inhaltliches
eskaliert. Worker starten ohne Dialog; ein Dialog wird gemeldet, nie beantwortet; der Merge
scheitert nicht an Artefakten; ein gescheiterter Merge lässt den Zustand für den Menschen offen.

**Abnahme** (letzte Task, gemessen):

1. `uv run pytest -q` grün; `lean-herdr workspace check` in diesem Repository ohne neue Fehler.
2. Ein Ein-Task-Plan läuft in einem frischen Wegwerf-Repository nach dem Rezept in §9 bis `done`,
   ohne jeden Eingriff außer der worktrunk-Freigabe, die das Rezept vorab erteilt. Kein Worker
   blockiert an einem Dialog, der Orchestrator sendet keine Taste und keinen Prompt in einen
   Worker-Pane, der Merge scheitert nicht an ungetrackten Dateien.
3. `workspace check` meldet im Wegwerf-Repository vor dem Lauf keine Zeile zu `__pycache__/` und
   keine Zeile `model unset`.

## 2. Ausgangslage, gemessen am 2026-09-15

| Befund | Beleg |
|---|---|
| Ein claude-Worker hängt im frischen Worktree am Ordner-Vertrauensdialog | Der Plan-Worktree `~/Scripts/lh-plan-probe.plan-probe` liegt neben dem Repository, nicht darin. Der erste Build scheiterte zweimal (`opencode_stuck`, `no_agent_id`) |
| Der Orchestrator hat den Dialog selbst bestätigt | Sein Bericht: „Down+Enter on ‚Yes, I trust this folder'“. opencode erlaubt ihm `herdr *` (`opencode.jsonc:42`); `orchestrator.md` verbietet es nirgends |
| lean-herdr kennt den Grund eines gescheiterten Starts nicht | `Herdr.agent_start` gibt bei jedem Exit > 0 `{}` zurück und verwirft stderr (`herdr.py:272-287`); `start_agent` meldet dann `agent_start_failed` oder `opencode_stuck` (`herdr.py:476-493`) |
| Ein blockierter Worker wirkt beim Warten wie Stille | `await_task` fragt `agent list` erst nach der Deadline und antwortet `no_reply` (`dispatch.py:562-576`); `no_reply` wiederholt der Orchestrator, statt zu eskalieren |
| Der Abschluss schließt den Workspace vor dem Merge | `orchestrator.md:132-148` (Einzel-Task), `:218-222` (Plan). Der Merge scheiterte, `herdr workspace report-metadata` antwortete `workspace_not_found` / `pane_not_found` |
| `wt merge --no-commit` verlangt einen sauberen Worktree; ungetrackte Dateien zählen | `✗ Cannot merge with --no-commit: plan/probe has uncommitted changes` mit `?? src/probe/__pycache__/`, `?? tests/__pycache__/`; `wt merge --help`: „Requires a clean working tree“. `wt remove` scheitert ohne `--force` ebenso |
| Briefs nennen ungetrackte Dateien erwartet | `briefs/implement.lmd.md:40` „Files the task did not name stay untracked — that is expected.“; `briefs/review.lmd.md:30` „An untracked file is no defect by itself“ |
| `__pycache__/` ignoriert sich nicht selbst | `.pytest_cache/` und `.ruff_cache/` tragen eine eigene `.gitignore`, `__pycache__/` nicht. Das Probe-Repository hatte keine `.gitignore`, weil `git init` vor `uv init` lief. Dieses Repository ignoriert es (`.gitignore:2`) |
| Rollen ohne `model` fallen erst beim Build auf | `usage_error: build mode needs --model` (`dispatch.py:849`); `workspace check` meldete `ok: true`, `_role_warnings` warnt nur zu `kind` (`checkcmd.py:556-558`) |
| `wt config approvals add` braucht ohne Terminal `--yes` | `✗ Cannot prompt for approval in non-interactive environment` |
| `git init` legt `master` an | Probe-Repository auf `master`; der Orchestrator mergt nach `main` |

## 3. Entscheidungen

| # | Entscheidung |
|---|---|
| E1 | Vor dem Start eines claude-Workers in einem Worktree desselben Repositorys markiert `dispatch` den Worktree als vertraut — über den gemessenen Mechanismus (§8, M1), nie per Tastendruck. |
| E2 | Jeder andere Dialog wird erkannt und als `agent_blocked` mit Dialogtext gemeldet, beim Start und in jeder Warterunde. Nichts in lean-herdr beantwortet ihn. |
| E3 | Der Orchestrator beantwortet nie einen Dialog. Seine herdr-Rechte schrumpfen auf `worktree list`, `workspace close` und `workspace report-metadata`. |
| E4 | Abschluss: Merge mit `--no-remove` bei offenem Workspace, danach den Workspace schließen, danach `wt remove`. |
| E5 | Ungetrackte, nicht ignorierte Dateien bleiben ein Merge-Stopp. `workspace check` warnt, wenn `__pycache__/` nicht ignoriert ist; `init` schreibt weiterhin keine Ignore-Regeln. |
| E6 | `workspace check` warnt bei einer Worker-Rolle ohne `model`. |
| E7 | Abnahme-Rezept: `uv init` vor `git init`, nach dem ersten Commit `git branch -M main`, `wt config approvals add --yes`. |
| E8 | Findet M1 keinen stabilen Mechanismus für E1, hält der Plan an und legt das dem Betreiber vor. Die Abnahme (§1, Punkt 2) wird nicht aufgeweicht. |

## 4. Dialoge in Worker-Panes

### 4.1 `lean_herdr/dialogs.py`

Ein eigenes Modul: `dispatch.py` steht bei 650 Produktions-LOC.

**Vorab-Vertrauen** (`pretrust`):

- nur für `kind = "claude"` und nur für einen Worker mit `--worktree`;
- nur, wenn der Worktree zum Repository gehört: `git rev-parse --git-common-dir` ist für Worktree
  und `repo_root` dasselbe Verzeichnis;
- nur, wenn claude dem `repo_root` selbst vertraut — das Vertrauen des Menschen wird auf einen
  Checkout desselben Repositorys übertragen, nie neu erteilt;
- es trägt genau diesen einen Pfad ein. Liegt der Mechanismus in einer Datei außerhalb des
  Repositorys, schreibt es atomar (Temp-Datei, `os.replace`) und lässt jeden anderen Schlüssel
  unverändert;
- es bricht nie ab. Scheitert es, startet `dispatch` trotzdem; ein dann erscheinender Dialog läuft
  über `agent_blocked`.

**Erkennen** (`blocked_dialog`): Steht der Pane in `herdr agent list` auf
`agent_status = "blocked"`, liefert es die letzten Bildschirmzeilen (höchstens 20) über einen
neuen Wrapper `Herdr.agent_read` (`herdr agent read <pane> --source detection`), sonst `None`.

### 4.2 `dispatch`

- **Start:** `pretrust` läuft vor `start_agent`. `start_agent` prüft `blocked_dialog`, sobald der
  erste Versuch ohne Agent endet — **vor** `_free_pane`, denn dessen `ctrl-c` wäre ein Tastendruck
  in den Dialog. Liefert `blocked_dialog` einen Text, gibt es keinen zweiten Versuch, und `dispatch`
  antwortet `{"ok": false, "error": "agent_blocked", "pane": "<pane>", "dialog": "<Text>"}`.
  Sonst bleiben die bisherigen Fehler und der zweite Versuch. Nennt Herdr beim Startdialog einen
  eigenen Grund (M2), darf `Herdr.agent_start` ihn durchreichen; entschieden wird über `agent list`.
- **Warten:** Jede Runde von `await_task` sucht den Worker über seinen Namen in `herdr agent list`
  und prüft dessen Pane mit `blocked_dialog`. Bei `blocked` antwortet es sofort
  `error: "agent_blocked"` mit `dialog`, statt nach der Deadline `no_reply`. Die Prüfung kostet
  einen `agent list`-Aufruf je Runde.

### 4.3 Orchestrator

- `orchestrator.md`, Abschnitt Escalation: `agent_blocked` ist eine Eskalation mit dem Dialogtext.
  Dazu der Satz (wortgetreu getestet): *You never answer a dialog in a worker's pane: no
  `herdr agent send-keys`, no `herdr agent prompt`, no keystroke of any kind.*
- `opencode.jsonc`, Orchestrator: `"herdr *": "allow"` wird zu `"herdr worktree list *"`,
  `"herdr workspace close *"`, `"herdr workspace report-metadata *"`.
- `claude/orchestrator.json`: `deny` erhält `Bash(herdr agent:*)` und `Bash(herdr pane:*)`.
- Kopien und Lock ziehen mit.

## 5. Abschluss-Reihenfolge

Beide Abschnitte in `orchestrator.md` stellen um. Ein Pane verliert nie sein cwd, weil der
Worktree erst verschwindet, wenn sein Workspace geschlossen ist.

Einzel-Task („Teardown and merge“):

    1. Check: verdict=result, not reject
    2. herdr worktree list --cwd <repo_root>  -> `path` and `open_workspace_id` of the branch
    3. wt -C <path> step squash --stage none --yes
    4. wt -C <path> merge main --yes --no-commit --no-remove
    5. herdr workspace close <workspace_id>
    6. wt -C <repo_root> remove <branch> --yes

Plan („Teardown for a plan -- no squash“): Schritte 2, 4, 5, 6.

- **Schritt 3 oder 4 scheitert:** nichts schließen, nichts entfernen. `esc=` per
  `herdr workspace report-metadata` am noch offenen Worker-Workspace, Eskalation mit `wt`s
  Fehlertext.
- **Schritt 6 scheitert:** `main` ist gemergt. Der Orchestrator meldet den Fehler und entfernt
  nie mit `--force`. Die Entfernung läuft im Hintergrund; nicht darauf prüfen.
- Der Begründungstext („The reverse is a mistake …“) sagt künftig: Mergen bei offenem Workspace
  ist sicher, weil `--no-remove` den Checkout stehen lässt; entfernt wird erst nach dem Schließen.
- README, Ablauf der Einzel-Task (Schritt 5 dort), zieht mit.

## 6. Ungetrackte Dateien und Check

### 6.1 `__pycache__/`

Neue Prüfung in `checkcmd.py` nach dem Muster von `_check_temp_ignored`, als Warnung in
`workspace_check`:

- nur, wenn `pyproject.toml` im Repository-Root liegt;
- `git check-ignore -v __pycache__/lean-herdr.probe` im Root; Exit 1 ergibt:
  *git does not ignore `__pycache__/` (probed with `__pycache__/lean-herdr.probe`) -- every test run
  leaves bytecode there, and untracked files stop `wt merge --no-commit` and `wt remove`. Add to
  .gitignore: `__pycache__/`*
- kein `git` oder ein anderer Exit: kein Urteil.

### 6.2 Rolle ohne `model`

`_role_warnings` meldet nach dem Orchestrator-`continue` (`checkcmd.py:563` — `workspace up`
startet den Orchestrator ohne Modell) für jede Rolle hinter einer gerouteten Work, deren
`settings_for(role, data).model` leer ist, auch über `[default]`:
*`[roles.<role>].model unset: dispatch --work <work> needs --model`*.
Die erwarteten Warnungen im Healthy-Test ändern sich mit.

### 6.3 Briefs und Rollen-Prompts

- `briefs/implement.lmd.md`: der Satz „Files the task did not name stay untracked — that is
  expected." wird zu: *Files the task did not name stay out of your commits. Leave no untracked file
  that git does not ignore: it stops the merge. Delete scratch files you created; if a tool
  generates such files, name them under `concerns:` — the project's ignore rules are not yours to
  change.*
- `roles/builder.md`, nach „nothing you did not name reaches the commit.": *An untracked file that
  git does not ignore stops the merge — delete what you created, name what a tool generated.*
- `briefs/review.lmd.md`: „An untracked file is no defect by itself; name one that belongs in a
  commit." wird zu: *An ignored file is no defect. An untracked file that git does not ignore stops
  the merge: name it — Important if it belongs in a commit, Minor if only the project's ignore rules
  miss it.*

Die neuen Sätze werden wortgetreu getestet. Der Orchestrator ändert nichts; scheitert der Merge
daran, gilt §5.

## 7. Doku

- `INSTALL.md`, Approvals: Ohne Terminal (Agent, CI) braucht es `wt config approvals add --yes`;
  die Freigabe gilt den Hooks des Projekts.
- `README.md`: Abschluss-Reihenfolge (§5), Dialoge (Vorab-Vertrauen, `agent_blocked`, der
  Orchestrator beantwortet keinen Dialog), die zwei neuen Warnungen von `workspace check`.

## 8. Messungen (erste Task, vor jedem Code)

| # | Frage | Entscheidet |
|---|---|---|
| M1 | Wo legt claude das Ordner-Vertrauen ab, und verhindert ein Eintrag für einen neuen Worktree-Pfad den Dialog beim nächsten Start? Gilt das Vertrauen eines Elternverzeichnisses? | E1 oder E8 |
| M2 | Was antwortet `herdr agent start` bei einem claude-Startdialog (Exit, stderr, Dauer), und steht der Pane danach in `herdr agent list` auf `blocked`? Was liefert `herdr agent read --source detection`? | §4.1, §4.2 |
| M3 | `wt -C <path> merge main --yes --no-commit --no-remove` mit ignoriertem `__pycache__/` im Worktree; danach, bei geschlossenem Workspace, `wt -C <root> remove <branch> --yes`: Ist gemergt, sind Worktree und Branch weg? | §5 |
| M4 | Trifft `git check-ignore -v __pycache__/lean-herdr.probe` die Regel `__pycache__/`, auch wenn kein solches Verzeichnis existiert? | §6.1 |

Jede Messung landet als Fakt im Wissen. Weicht ein Ergebnis von diesem Spec ab, hält der Plan an.

## 9. Abnahme-Rezept

In `~/Scripts/<probe>` (Wegwerf-Repository; das Elternverzeichnis ist kein Git-Repository):

1. `mkdir -p ~/Scripts/<probe>`; darin **zuerst** `uv init --package --name probe`, danach
   `git init -q` — nur `uv init` außerhalb eines Git-Repositorys legt das Repository samt
   `.gitignore` (mit `__pycache__/`) an.
2. `uv add --dev pytest ruff ty`; `git add -A`; `git commit -m "chore: empty probe project"`;
   `git branch -M main`.
3. `lean-herdr workspace init`; in `.lean-ctx/lean-herdr/config.toml` für jede Rolle `kind` **und**
   `model`.
4. `wt config approvals add --yes`; `git add -A`; `git commit -m "chore: lean-herdr workspace"`.
5. `lean-herdr workspace check` — `"ok": true`, keine Zeile zu `__pycache__/`, `model`,
   `not committed`, lean-md, Gateway, Skill oder `ty`.
6. Spec anlegen und committen (wie Plan C, Task 9).
7. `lean-herdr workspace up`; im Orchestrator: `Plan spec <spec> as probe and run it`.

Erwartet bei `done`, ohne Eingriff: `plan next probe` → `{"ok": true, "done": true}`; `main` trägt
Plan- und Task-Commit ohne Squash; `uv run pytest -q` grün; jede Task `done`; kein Worker-Pane stand
je auf `blocked`; der Orchestrator hat keinen `herdr agent`-Befehl ausgeführt.

## 10. Fehlerbild

| Lage | Antwort |
|---|---|
| claude-Worker, Vorab-Vertrauen nicht möglich (fremdes Repository, M1-Mechanismus scheitert) | Start läuft; erscheint der Dialog: `agent_blocked` |
| Dialog beim Start | `{"ok": false, "error": "agent_blocked", "pane": …, "dialog": …}` |
| Dialog während der Arbeit | `--await` antwortet `agent_blocked` mit `dialog`, sofort |
| Start hängt ohne Dialog | `opencode_stuck` wie bisher |
| Merge scheitert (unsauberer Worktree, Gate rot, Rebase-Konflikt) | nichts geschlossen, nichts entfernt; `esc=` am offenen Workspace; Eskalation |
| `wt remove` scheitert | gemeldet; nie `--force` |
| kein `pyproject.toml` | keine `__pycache__/`-Prüfung |
| `git check-ignore` läuft nicht | kein Urteil |

## 11. Tests

- `tests/test_dialogs.py`: `pretrust` mit Wegwerf-Repositories und einem Double für den
  M1-Mechanismus (fremdes Repository, nicht vertrauter Root, fremder Schlüssel bleibt,
  Schreibfehler bricht nicht ab); `blocked_dialog` mit Doubles für `agent list`/`agent read`.
- `dispatch`: `agent_blocked` beim Start und in einer Warterunde; `opencode_stuck` ohne Dialog.
- `test_worker_permissions.py`: Orchestrator ohne `herdr *`, genau die drei Unterbefehle; claude
  `orchestrator.json` verweigert `herdr agent`/`herdr pane`.
- `test_role_prohibitions.py`: Dialog-Satz; Merge mit `--no-remove` vor `workspace close`,
  `wt remove` nach `workspace close`, für beide Abschlüsse.
- `test_checkcmd.py`: `__pycache__/`-Warnung (nicht ignoriert, ignoriert, ohne `pyproject.toml`,
  ohne Urteil); `model unset` je Worker-Rolle, nicht für den Orchestrator.
- `test_plan_templates.py`: die neuen Brief-Sätze.
- Kein Test ruft echtes `herdr`, `wt`, `claude` oder `lean-md`; Ausnahmen sind nur M1–M4 und die
  Abnahme.

## 12. Nicht-Ziele

- `init` schreibt keine Ignore-Regeln.
- Kein automatisches Beantworten eines Dialogs; das Vorab-Vertrauen ist ein Eintrag, kein
  Tastendruck.
- Kein claude-Orchestrator mit eigenen Freigaben für `herdr`/`wt`.
- Anbieterwahl (eigener Spec auf `docs/anbieterwahl-spec`); Änderungen an `wt` selbst.

## 13. Grenzen und Zuschnitt

- Keine Datei unter `lean_herdr/` über 800 Produktions-LOC (heute: `dispatch.py` 650,
  `checkcmd.py` 500, `herdr.py` 230).
- Code, Templates, Prompts, Briefs, README und INSTALL: Englisch.
- Vorgeschlagener Plan: 1 Messungen · 2 `dialogs.py` und Herdr-Wrapper · 3 `dispatch` (Start,
  Warten) · 4 Orchestrator-Prompt und Rechte (Dialog, Abschluss) · 5 Check-Warnungen, Briefs,
  Builder-Prompt · 6 README/INSTALL · 7 Abnahme.
