# lean-herdr: Befunde der TP2-Abnahme härten — Design v1.1

**Stand:** 2026-09-15 · **Status:** entworfen, nicht implementiert · **v1.1:** M1 und M2 gemessen
(§2). Ein Worktree erbt claudes Ordner-Vertrauen vom Repository-Root; das Vertrauen erteilt einmal
`workspace init --trust-claude`, `dispatch` schreibt nichts.
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
`checkcmd.py`, `initcmd.py`, `workspace.py`; `lean_herdr/templates/` (`roles/orchestrator.md`,
`roles/builder.md`, `briefs/implement.lmd.md`, `briefs/review.lmd.md`, `opencode.jsonc`,
`claude/orchestrator.json`) samt eingecheckten Kopien und Lock; `README.md`, `INSTALL.md`; Tests.

---

## 1. Ziel und Abnahme

Nach `workspace up` braucht ein Plan-Lauf keinen Menschen mehr, solange nichts Inhaltliches
eskaliert. Worker starten ohne Dialog; ein Dialog wird gemeldet, nie beantwortet; der Merge
scheitert nicht an Artefakten; ein gescheiterter Merge lässt den Zustand für den Menschen offen.

**Abnahme** (letzte Task, gemessen):

1. `uv run pytest -q` grün; `lean-herdr workspace check` in diesem Repository ohne neue Fehler.
2. Ein Ein-Task-Plan läuft in einem frischen Wegwerf-Repository nach dem Rezept in §9 bis `done`,
   ohne jeden Eingriff außer den beiden Freigaben, die das Rezept vorab erteilt (worktrunk,
   `workspace init --trust-claude`). Kein Worker blockiert an einem Dialog, der Orchestrator sendet
   keine Taste und keinen Prompt in einen Worker-Pane, der Merge scheitert nicht an ungetrackten
   Dateien.
3. `workspace check` meldet im Wegwerf-Repository vor dem Lauf keine Zeile zu `__pycache__/`, keine
   Zeile `model unset` und keine Zeile `claude does not trust`.

## 2. Ausgangslage, gemessen am 2026-09-15

| Befund | Beleg |
|---|---|
| Ein claude-Worker hängt im frischen Worktree am Ordner-Vertrauensdialog | Der Plan-Worktree `~/Scripts/lh-plan-probe.plan-probe` liegt neben dem Repository, nicht darin. Der erste Build scheiterte zweimal (`opencode_stuck`, `no_agent_id`) |
| Der Orchestrator hat den Dialog selbst bestätigt | Sein Bericht: „Down+Enter on ‚Yes, I trust this folder'“. opencode erlaubt ihm `herdr *` (`opencode.jsonc:42`); `orchestrator.md` verbietet es nirgends. Kein Code in lean-herdr sendete je Pfeil oder Enter (`git log --all -G "send.keys.*([Dd]own\|[Ee]nter)"` leer; `_free_pane` sendet nur `ctrl-c`) |
| **M1:** Ein Worktree erbt das Ordner-Vertrauen seines Repository-Roots | claude hält das Vertrauen in `~/.claude.json` unter `projects.<pfad>.hasTrustDialogAccepted`, nicht in Projekt-Settings. Nicht vertrauter Root `lh-trust-probe`: auch der Worktree `lh-trust-probe.w1` zeigt den Dialog (mit seinem eigenen Pfad). Nach „Yes" im Root schreibt claude genau `projects["/home/tholo/Scripts/lh-trust-probe"]` (aufgelöster Pfad); danach startet claude in `.w1` ohne Dialog und ohne eigenen Schlüssel. `~/.claude.json` trägt keinen einzigen `lean-herdr.<branch>`-Worktree trotz vieler Builder-Läufe. Claude Code 2.1.272, `CLAUDE_CONFIG_DIR` ungesetzt |
| Das TP2-Probe-Repository war nicht vertraut | Niemand hatte claude in seinem Root gestartet; der Dialog galt deshalb jedem Worktree |
| **M2:** Ein Startdialog lässt `herdr agent start` scheitern | Exit 1 nach 3,8 s, stdout leer, stderr `{"error":{"code":"agent_not_ready","message":"agent m1-root is blocked during startup and is not ready for prompts"}}`. `agent list`: `agent_status = "blocked"`, `launch_pending: true`. `agent read <pane> --source detection` gibt den Bildschirm als reinen Text aus, kein JSON. 3,8 s liegt knapp über `AGENT_START_REFUSAL_S` (3,5 s): `start_agent` hielte den Start für einen Hänger und schickte `ctrl-c` in den Dialog |
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
| E1 | `workspace init --trust-claude` trägt `projects.<root>.hasTrustDialogAccepted = true` in claudes Zustandsdatei ein — genau diesen Schlüssel, atomar, jeden anderen unverändert. Jeder Worktree erbt das Vertrauen (M1). Ohne den Schalter bleibt die Datei unberührt; `dispatch` schreibt nie hinein, und nichts erteilt Vertrauen per Tastendruck. |
| E2 | Jeder Dialog wird erkannt und als `agent_blocked` mit Dialogtext gemeldet, beim Start (auch von `workspace up`), vor dem Wiederverwenden eines Workers und in jeder Warterunde. Nichts in lean-herdr beantwortet ihn. |
| E3 | Der Orchestrator beantwortet nie einen Dialog. Seine herdr-Rechte schrumpfen auf `worktree list`, `workspace close` und `workspace report-metadata`. |
| E4 | Abschluss: Merge mit `--no-remove` bei offenem Workspace, danach den Workspace schließen, danach `wt remove`. |
| E5 | Ungetrackte, nicht ignorierte Dateien bleiben ein Merge-Stopp. `workspace check` warnt, wenn `__pycache__/` nicht ignoriert ist; `init` schreibt weiterhin keine Ignore-Regeln. |
| E6 | `workspace check` warnt bei einer Worker-Rolle ohne `model`. |
| E7 | Abnahme-Rezept: `uv init` vor `git init`, nach dem ersten Commit `git branch -M main`, `workspace init --trust-claude`, `wt config approvals add --yes`. |
| E8 | `workspace check` warnt, wenn eine Rolle `kind = "claude"` hat und claude dem Root nicht vertraut. |

## 4. Dialoge in Worker-Panes

### 4.1 claude-Vertrauen (`lean_herdr/dialogs.py`)

Ein eigenes Modul: `dispatch.py` steht bei 650 Produktions-LOC.

- **Zustandsdatei:** `$CLAUDE_CONFIG_DIR/.claude.json`, ohne die Variable `~/.claude.json` (M1).
  lean-herdr legt sie nie an.
- **`claude_trusts(root)`:** `True` oder `False` nach `projects.<aufgelöster Root>.hasTrustDialogAccepted`;
  `None` (kein Urteil), wenn die Datei fehlt oder nicht lesbar ist. Gefragt wird nur der
  Root-Schlüssel selbst. Ob ein vertrautes Elternverzeichnis zählt, ist nicht gemessen — eine Warnung
  wäre dann überflüssig, nie falsch-sicher.
- **`trust_root(root)`:** setzt den Schlüssel und antwortet `written`, `already` oder
  `failed: <Grund>`. Eine fehlende Datei ist `failed` (claude lief unter dieser Konfiguration nie).
  Schreibt atomar (Temp-Datei neben der Datei, `os.replace`, Dateimodus bleibt) und bricht nie ab.
  Ist die Datei ein Symlink, ersetzt es dessen Ziel (Temp-Datei neben dem Ziel); der Link bleibt ein
  Link.
  Eine laufende claude-Sitzung kann die Datei aus ihrem Speicherstand zurückschreiben; einen so
  verlorenen Eintrag nennt `workspace check`.
- **`workspace init --trust-claude`** ruft `trust_root` und meldet das Ergebnis als `claude_trust`;
  `failed` ist eine Warnung, kein Fehler von `init`. Mit `--update` und `--force` kombinierbar; `up`
  und `check` lehnen den Schalter ab wie jeden `init`-Schalter. Das ist die einzige rechnerweite
  Freigabe, die `init` erteilt, und nur auf den Schalter hin.

### 4.2 Erkennen (`blocked_dialog`)

Steht der Pane in `herdr agent list` auf `agent_status = "blocked"`, liefert es die letzten
Bildschirmzeilen (höchstens 20) über einen neuen Wrapper `Herdr.agent_read`
(`herdr agent read <pane> --source detection --lines 20`; stdout ist reiner Text, M2), sonst `None`.

### 4.3 `dispatch`

- **Start:** `start_agent` prüft `blocked_dialog`, sobald der erste Versuch ohne Agent endet —
  **vor** `_free_pane`, denn dessen `ctrl-c` wäre ein Tastendruck in den Dialog. Liefert
  `blocked_dialog` einen Text, gibt es keinen zweiten Versuch, und `dispatch` antwortet
  `{"ok": false, "error": "agent_blocked", "pane": "<pane>", "dialog": "<Text>"}`. Sonst bleiben die
  bisherigen Fehler und der zweite Versuch. Herdr nennt `agent_not_ready` auf stderr (M2); entschieden
  wird über `agent list`. Endet ein Dialog-Start schneller als `AGENT_START_REFUSAL_S`, wiederholt
  `agent_start` den Start; `agent start` verlangt einen Pane an der Shell-Eingabe und schreibt in einen
  belegten Pane nichts. Danach gilt dieselbe Prüfung. Endet auch der zweite Versuch ohne Agent, fragt
  `start_agent` `blocked_dialog` noch einmal, bevor es `opencode_stuck` meldet: Ein Hänger im ersten
  Versuch und ein Dialog im zweiten ergeben `agent_blocked`.
- **Wiederverwenden:** Steht der Worker schon in `herdr agent list`, liest `dispatch` dessen
  `agent_status` aus demselben Eintrag — vor dem `/clear`, denn `agent prompt` tippt in den Pane. Bei
  `blocked` antwortet es `{"ok": false, "error": "agent_blocked", "pane": "<pane>", "dialog": "<Text>"}`
  (Text über `agent read`, wie bei `blocked_dialog`), ohne `/clear` und ohne Start. Damit fragen alle
  drei Eingabewege vorher: Start, Wiederverwenden, Wecken.
- **Warten:** Jede Runde von `await_task` sucht den Worker über seinen Namen in `herdr agent list`
  und prüft dessen Pane mit `blocked_dialog` — vor dem Wecken, denn `agent prompt` tippt in den Pane.
  Bei `blocked` antwortet es sofort `error: "agent_blocked"` mit `dialog`, statt nach der Deadline
  `no_reply`. Die Prüfung kostet einen `agent list`-Aufruf je Runde.

### 4.4 Orchestrator

- `orchestrator.md`, Abschnitt Escalation: `agent_blocked` ist eine Eskalation mit dem Dialogtext.
  Dazu der Satz (wortgetreu getestet): *You never answer a dialog in a worker's pane: no
  `herdr agent send-keys`, no `herdr agent prompt`, no keystroke of any kind.*
- `opencode.jsonc`, Orchestrator: `"herdr *": "allow"` wird zu `"herdr worktree list *"`,
  `"herdr workspace close *"`, `"herdr workspace report-metadata *"`.
- `claude/orchestrator.json`: `deny` erhält `Bash(herdr agent:*)` und `Bash(herdr pane:*)`.
- Kopien und Lock ziehen mit.
- **`workspace up`:** `start_orchestrator` reicht `blocked` an `start_agent` durch wie `dispatch`.
  Trifft der Orchestrator-Start auf einen Dialog (ein claude-Orchestrator im nicht vertrauten Root),
  antwortet `up` `{"ok": false, "error": "agent_blocked", "dialog": "<Text>", "workspace": …, "pane": …}`
  statt eines `ctrl-c` in den Dialog; der Tastendruck (`handle_bootstrap`) meldet denselben Fehler.

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
- **Schritt 5 scheitert:** `main` ist gemergt, der Workspace noch offen. Kein `wt remove` — der
  Pane hätte kein cwd mehr. `esc=` am offenen Workspace, Eskalation mit herdrs Fehlertext.
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

### 6.4 claude-Vertrauen

`workspace check` sammelt die Rollen, deren `kind` `claude` ist — den Orchestrator und jede Rolle
hinter einer Work, `[default]` eingeschlossen — und fragt `claude_trusts(root)`. `False` ergibt:
*claude does not trust <root> -- a claude worker stops at the folder-trust dialog in every worktree
of this repository, and dispatch answers agent_blocked. Run: lean-herdr workspace init --trust-claude*
Läuft keine Worker-Rolle auf claude, nur der Orchestrator, nennt die Zeile nach demselben Präfix die
Folge für `up`: *claude does not trust <root> -- the claude orchestrator stops at the folder-trust
dialog when workspace up starts it, and up answers agent_blocked. Run: lean-herdr workspace init
--trust-claude* Keine claude-Rolle oder `None`: keine Zeile.

## 7. Doku

- `INSTALL.md`, Approvals: Ohne Terminal (Agent, CI) braucht es `wt config approvals add --yes`;
  die Freigabe gilt den Hooks des Projekts.
- `README.md`: Abschluss-Reihenfolge (§5); Einrichten mit `workspace init --trust-claude` (§4.1);
  Dialoge (`agent_blocked`, der Orchestrator beantwortet keinen Dialog); die Rechte von
  `orchestrator.json` ohne `herdr agent`/`herdr pane`; die drei neuen Warnungen von `workspace check`.

## 8. Messungen

| # | Frage | Stand | Entscheidet |
|---|---|---|---|
| M1 | Wo legt claude das Ordner-Vertrauen ab, und gilt es für einen Worktree? | gemessen (§2): `~/.claude.json`, der Worktree erbt vom Root | E1 |
| M2 | Was antwortet `herdr agent start` bei einem claude-Startdialog, steht der Pane auf `blocked`, was liefert `agent read --source detection`? | gemessen (§2) | §4.2, §4.3 |
| M3 | `wt -C <path> merge main --yes --no-commit --no-remove` mit ignoriertem `__pycache__/` im Worktree; danach, bei geschlossenem Workspace, `wt -C <root> remove <branch> --yes`: Ist gemergt, sind Worktree und Branch weg? | offen | §5 |
| M4 | Trifft `git check-ignore -v __pycache__/lean-herdr.probe` die Regel `__pycache__/`, auch wenn kein solches Verzeichnis existiert? | offen | §6.1 |

M3 und M4 laufen als erste Task, vor jedem Code. Jede Messung landet als Fakt im Wissen. Weicht ein
Ergebnis von diesem Spec ab, hält der Plan an.

## 9. Abnahme-Rezept

In `~/Scripts/<probe>` (Wegwerf-Repository; das Elternverzeichnis ist kein Git-Repository):

1. `mkdir -p ~/Scripts/<probe>`; darin **zuerst** `uv init --package --name probe`, danach
   `git init -q` — nur `uv init` außerhalb eines Git-Repositorys legt das Repository samt
   `.gitignore` (mit `__pycache__/`) an.
2. `uv add --dev pytest ruff ty`; `git add -A`; `git commit -m "chore: empty probe project"`;
   `git branch -M main`.
3. `lean-herdr workspace init --trust-claude` — `claude_trust` ist `written`; in
   `.lean-ctx/lean-herdr/config.toml` für jede Rolle `kind` **und** `model`.
4. `wt config approvals add --yes`; `git add -A`; `git commit -m "chore: lean-herdr workspace"`.
5. `lean-herdr workspace check` — `"ok": true`, keine Zeile zu `__pycache__/`, `model`,
   `claude does not trust`, `not committed`, lean-md, Gateway, Skill oder `ty`.
6. Spec anlegen und committen (wie Plan C, Task 9).
7. `lean-herdr workspace up`; im Orchestrator: `Plan spec <spec> as probe and run it`.

Erwartet bei `done`, ohne Eingriff: `plan next probe` → `{"ok": true, "done": true}`; `main` trägt
Plan- und Task-Commit ohne Squash; `uv run pytest -q` grün; jede Task `done`; kein Worker-Pane stand
je auf `blocked`; der Orchestrator hat keinen `herdr agent`-Befehl ausgeführt.

## 10. Fehlerbild

| Lage | Antwort |
|---|---|
| claude-Rolle, dem Root nicht vertraut (kein `--trust-claude`, Eintrag verloren) | `workspace check` warnt vorher; beim Start `agent_blocked` |
| `--trust-claude`, Zustandsdatei fehlt oder ist unlesbar | `claude_trust: "failed: …"` und eine Warnung; `init` bleibt `ok`; die Datei bleibt, wie sie war |
| `workspace check`, Zustandsdatei fehlt oder ist unlesbar | kein Urteil |
| `--trust-claude`, Zustandsdatei ist ein Symlink | das Ziel wird ersetzt; der Link bleibt ein Link |
| Dialog beim Start | `{"ok": false, "error": "agent_blocked", "pane": …, "dialog": …}` |
| Dialog während der Arbeit | `--await` antwortet `agent_blocked` mit `dialog`, sofort |
| Hänger im ersten Startversuch, Dialog im zweiten | `agent_blocked` mit `dialog` |
| Worker zum Wiederverwenden wartet in einem Dialog | `agent_blocked` mit `dialog`; kein `/clear` |
| Dialog beim Start des Orchestrators (`workspace up`) | `agent_blocked` mit `dialog`, `workspace` und `pane` |
| Start hängt ohne Dialog | `opencode_stuck` wie bisher |
| Merge scheitert (unsauberer Worktree, Gate rot, Rebase-Konflikt) | nichts geschlossen, nichts entfernt; `esc=` am offenen Workspace; Eskalation |
| `herdr workspace close` scheitert | `main` gemergt; kein `wt remove`; `esc=` am offenen Workspace; Eskalation |
| `wt remove` scheitert | gemeldet; nie `--force` |
| kein `pyproject.toml` | keine `__pycache__/`-Prüfung |
| `git check-ignore` läuft nicht | kein Urteil |

## 11. Tests

- `tests/test_dialogs.py`: `claude_trusts` (vertraut, nicht vertraut, fehlende und unlesbare Datei);
  `trust_root` (schreibt genau den Schlüssel, `already`, fremde Schlüssel bleiben, Dateimodus bleibt,
  Schreibfehler hinterlässt nichts, fehlende Datei wird nicht angelegt, ein Symlink bleibt ein Link);
  `blocked_dialog` mit Doubles für `agent list`/`agent read`.
- `test_herdr.py`: `agent_read` liest stdout als Text; `start_agent` fragt `blocked` vor `_free_pane`
  und nach dem zweiten Versuch.
- `dispatch`: `agent_blocked` beim Start, vor dem Wiederverwenden (kein `/clear`) und in einer
  Warterunde, vor dem Wecken; `opencode_stuck` ohne Dialog.
- `test_initcmd.py`: `--trust-claude` schreibt, meldet `already`, meldet `failed` als Warnung; ohne
  Schalter bleibt die Datei unberührt. `test_workspace.py`: der Schalter wird durchgereicht, `up` und
  `check` lehnen ihn ab; `up` meldet einen Dialog beim Orchestrator-Start als `agent_blocked` mit
  `dialog`.
- `test_worker_permissions.py`: Orchestrator ohne `herdr *`, genau die drei Unterbefehle; claude
  `orchestrator.json` verweigert `herdr agent`/`herdr pane`. `test_config_files.py` zieht mit.
- `test_role_prohibitions.py`: Dialog-Satz; Merge mit `--no-remove` vor `workspace close`,
  `wt remove` nach `workspace close`, für beide Abschlüsse.
- `test_checkcmd.py`: `__pycache__/`-Warnung (nicht ignoriert, ignoriert, ohne `pyproject.toml`,
  ohne Urteil); `model unset` je Worker-Rolle, nicht für den Orchestrator; claude-Vertrauen
  (claude-Rolle und nicht vertraut, vertraut, keine claude-Rolle, nur der Orchestrator auf claude,
  kein Urteil).
- `test_plan_templates.py`: die neuen Brief-Sätze.
- Kein Test ruft echtes `herdr`, `wt`, `claude` oder `lean-md`; Ausnahmen sind nur M3, M4 und die
  Abnahme. Kein Test liest oder schreibt die echte Zustandsdatei: `CLAUDE_CONFIG_DIR` zeigt dort auf
  ein Temp-Verzeichnis.

## 12. Nicht-Ziele

- `init` schreibt keine Ignore-Regeln.
- Kein automatisches Beantworten eines Dialogs, auch nicht des Vertrauensdialogs: Vertrauen erteilt
  nur `workspace init --trust-claude`, als Eintrag, nie als Tastendruck.
- `dispatch` schreibt nie in claudes Zustandsdatei; lean-herdr legt sie nie an.
- Kein claude-Orchestrator mit eigenen Freigaben für `herdr`/`wt`.
- Anbieterwahl (eigener Spec auf `docs/anbieterwahl-spec`); Änderungen an `wt` selbst.

## 13. Grenzen und Zuschnitt

- Keine Datei unter `lean_herdr/` über 800 Produktions-LOC (heute: `dispatch.py` 650,
  `checkcmd.py` 500, `herdr.py` 230).
- Code, Templates, Prompts, Briefs, README und INSTALL: Englisch.
- Vorgeschlagener Plan: 1 Messungen M3/M4 · 2 `dialogs.py` und Herdr-Wrapper · 3 `dispatch` (Start,
  Warten) · 4 `init --trust-claude` und Check-Vertrauen · 5 Orchestrator-Prompt und Rechte (Dialog,
  Abschluss) · 6 Check `__pycache__/` und `model` · 7 Briefs und Builder-Prompt · 8 README/INSTALL ·
  9 Abnahme.
