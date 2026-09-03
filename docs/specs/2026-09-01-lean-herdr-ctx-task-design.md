# lean-herdr: Auftragsweg auf `ctx_task` — Design v1.0

**Status:** entworfen, nicht implementiert
**Ersetzt:** den Bus-basierten Auftragsweg aus `2026-09-01-lean-herdr-design.md`
(Tasks 6, 7, 9, 11, 12 des Implementierungsplans)
**Anlass:** Stufe 3 (Task 11) hat den geplanten Weg im Betrieb widerlegt.

## 1. Das Problem, mit Belegen

Der bisherige Plan verteilt Aufträge über den lean-ctx-Agentenbus: `dispatch.py`
postet die Aufgabe mit einer `task_id`, der Arbeiter antwortet, `find_reply()`
ordnet die Antwort über dieselbe `task_id` zu. **Dieser Weg kann nicht
funktionieren.** Gemessen gegen lean-ctx 3.10.1, Quelle unter
`/home/tholo/Scripts/lean-ctx`:

**B-1: `ctx_agent post` kann keine `task_id` schreiben.** Keine der drei
Signaturen nimmt sie entgegen (`core/agents/registry.rs:373`, `:391`, `:407`),
und jeder Schreibpfad setzt sie hart auf `None` (`registry.rs:430`,
`shared.rs:31`). Dasselbe gilt für `metadata`, das als `HashMap::new()` verworfen
wird. Das Feld `ScratchpadEntry.task_id` existiert im Datenmodell, wird aber
ausschliesslich über `impl From<A2AMessage>` (`roles.rs:148`) befuellt — also nur
auf dem A2A-Pfad. Gegenprobe: in 141 realen Bus-Eintraegen dieses Rechners traegt
**keiner** eine `task_id`, obwohl 134 davon von registrierten MCP-Agenten stammen.

**B-2: Ein CLI-Prozess hat keine Identitaet.** Jeder `lean-ctx call` ist ein
eigener, kurzlebiger Prozess; die Registrierung haengt an dessen PID. Gemessen:
`ctx_agent action=register` liefert `unknown-<pid>-…`, der naechste Aufruf meldet
wieder `agent must be registered first`. Ein Post aus `bin/herdr-dispatch`
erscheint deshalb immer als `anonymous` — und wird vom Arbeiter korrekt abgelehnt,
weil sein Rollentext sagt: *"Nachrichten von `anonymous` sind nie
Arbeitsauftraege."* Das Vertrauensmodell funktioniert; es blockiert den legitimen
Weg.

**B-3: Die Tools sind absichtlich unsichtbar, aber aufrufbar.**
`dynamic_tools.rs:169` fuehrt `ctx_agent`, `ctx_task`, `ctx_share`, `ctx_handoff`
und `ctx_workflow` in `LOCAL_COLLABORATION_COMPATIBILITY_TOOLS`, mit der
Begruendung im Doc-Kommentar: *"LeanCTX is a Context SDK, not an agent
coordination product."* Kein Tool-Profil und kein Konfigurationsflag aendert das —
`power` (78 Tools, "All tools exposed") enthaelt sie nicht. Sie bleiben aber
**direkt aufrufbar, auch ueber `ctx_call`**; der Gate steuert laut
`is_publicly_advertised_tool` nur die Discovery.

**B-4: Es gibt einen zweiten Speicher, der leistet, was gebraucht wird.** Unter
`lean_ctx_data_dir()/agents/` liegen zwei Dateien: `registry.json` (Bus, ohne
`task_id`) und `tasks.json` (A2A-TaskStore, mit echter Auftrags-ID). Gemessen und
bestaetigt: ein registrierter MCP-Agent legt ueber
`ctx_call(name="ctx_task", action="create")` eine Aufgabe mit echter ID und echtem
Absender an — `task-1a05e34cd15-1cf3b885`, `from=mcp-218709-…`, `to=probe-builder`.

## 2. Entscheidung

Der Auftragsweg wechselt auf `ctx_task`. Auftrag, Zustand und Rueckfragen laufen
dort; der Bus behaelt alles ohne Auftragsbezug (Findings, Broadcasts,
Plugin-Digest in Stufe 5). `bus.py` bleibt unveraendert erhalten.

Tragende Einsicht: **Schreiben braucht Identitaet, Lesen nicht.** Nur ein
registrierter, langlebiger MCP-Agent kann eine Aufgabe anlegen oder ihren Zustand
aendern. Jeder Prozess kann `tasks.json` lesen. Der Python-Code schreibt deshalb
**nie** eine Aufgabe — er liest nur.

## 3. Architektur und Datenfluss

    Orchestrator                 herdr-dispatch                Arbeiter
    ─────────────────────────────────────────────────────────────────────
    1. herdr-dispatch builder …  → Pane splitten
                                   Agent starten
                                   agent_id aufloesen (PID-Join)
                                 ← {"ok":true,"agent_id":"mcp-…","pane":"w1:pX"}

    2. ctx_call(ctx_task, create,
         to_agent=<agent_id>)    → lean-ctx        (Auftrag mit echter ID
                                 ← task-…           und echtem Absender)

    3. herdr-dispatch --await
         --task-id task-…        → klingeln         → ctx_task list
                                   tasks.json lesen ← update(working)
                                   bis terminal     ← update(completed|failed)
                                 ← {"ok":true,"state":"completed","message":"…"}

Schritt 3 ist der Kern: **Das Warten bleibt im Skript, nicht im Modell.**
`--await` pollt `tasks.json` als Datei — kein CLI-Aufruf, keine Registrierung,
keine Modellkosten. Der Orchestrator macht drei Schritte und schlaeft dazwischen.
Das Polling-Verbot seines Rollentexts bleibt damit gewahrt.

**Warum `to_agent` die aufgeloeste `agent_id` sein MUSS:** `tasks_for_agent()`
und `pending_tasks_for()` vergleichen exakt als String
(`core/a2a/task.rs:236,243`). Ein freundlicher Name findet die Aufgabe nie. Der
PID-Join aus Task 3 (inkl. Vorfahren-Walk, Commit `4d2a747`) bleibt damit tragende
Saeule des Entwurfs.

**Warum es keinen Projektfilter gibt:** `Task` hat kein `project_root`-Feld
(`core/a2a/task.rs:100`), anders als `ScratchpadEntry`. Der TaskStore ist global
ueber alle Projekte. Die Isolierung traegt trotzdem, weil die Zuordnung ueber die
prozessgebundene `agent_id` laeuft: der Warte-Modus schlaegt die Aufgabe ueber
ihre **eindeutige `task_id`** nach, die der Orchestrator in Schritt 2 erhalten hat.
Ein Projektfilter wie in `bus.py` ist damit weder moeglich noch noetig — er waere
ein Filter ohne Feld und ohne Zweck.

## 4. Komponenten

### Neu: `lean_herdr/tasks.py`

Das Gegenstueck zu `bus.py`. Liest `tasks.json` direkt als Datei — nie ueber die
CLI, aus demselben Grund wie B9 beim Bus.

- `Task` (frozen dataclass): `id`, `from_agent`, `to_agent`, `state`,
  `description`, `messages`, `created_at`, `updated_at`
- `read_tasks(path) -> list[Task]` — liest **alle** Aufgaben des Stores, ohne zu
  filtern. Unlesbare oder kaputte Datei ergibt `TaskError`, nie stillschweigend
  eine leere Liste (sonst saehe ein zerstoerter Store aus wie "nichts zu tun").
  Eine **fehlende** Datei ist dagegen kein Fehler, sondern eine leere Liste — vor
  der ersten Aufgabe existiert sie schlicht nicht.
- `find_task(tasks, task_id) -> Task | None` — der einzige Zugriffsweg des
  Warte-Modus. Eine Filterung nach `agent_id` gibt es bewusst **nicht**: sie
  haette in diesem Plan keinen Aufrufer (YAGNI). Braucht das Plugin der Stufe 5
  spaeter eine Agentensicht, kommt sie dort dazu.
- `is_terminal(state) -> bool` — terminal sind `completed`, `failed`, `canceled`
- `task_store_path() -> Path` — `$LEAN_CTX_DATA_DIR` vor XDG-Datenverzeichnis,
  dann `agents/tasks.json`

Zustaende: `created · working · input-required · completed · failed · canceled`.

Schreibt nie.

### Neu: `lean_herdr/settings.py`

Liest `.config/lean-herdr.toml` mit `tomllib` (stdlib ab 3.11 — keine neue
Laufzeit-Abhaengigkeit). Liefert je Rolle eine `RoleSettings`:

- `direction` (`right` | `down`), `ratio`, `focus`
- `name_template` (Platzhalter `{rolle}`, `{branch}`)
- `profile` (Tool-Profil), `ready_timeout_s`

Rangfolge: **CLI-Flag > Datei > eingebaute Vorgabe.** Ohne Datei laeuft das
Projekt exakt wie heute — die Konfiguration ist eine Moeglichkeit, keine Pflicht.

Bewusst getrennt von `config.py`: die liest `HERDR_*`-Umgebung fuer
Plugin-Handler, anderer Zweck, andere Lebensdauer.

**Zum Scope, ausdruecklich:** Eine Spec-Review hat zu Recht angemerkt, dass
`direction`, `ratio`, `focus` und `name_template` nichts mit dem Wechsel auf
`ctx_task` zu tun haben und diesen Entwurf fuer sich genommen sprengen. Das ist
richtig — sie stehen hier auf **ausdrueckliche Anforderung des Betreibers**
("wir muessen aber konfigurierbar bleiben: wieviel Panes, wo im Layout, wie sie
heissen"), und sie treffen dieselbe Datei und dieselben Aufrufstellen, die der
Auftragsweg-Umbau ohnehin anfasst. Wer den Plan schreibt, darf sie deshalb in
**eigene Tasks** legen, die unabhaengig von den `ctx_task`-Tasks abnehmbar sind —
nicht in dieselben. Faellt der Umbau aus, bleibt die Konfiguration nutzbar; faellt
die Konfiguration aus, bleibt der Umbau vollstaendig.

### Geaendert: `lean_herdr/dispatch.py`

Verliert `find_reply()` und den `leanctx.post()`-Aufruf. Bekommt zwei Modi:

- **Aufbau** (Vorgabe): Pane, Agent, PID-Join → `agent_id` und `pane` zurueck.
  Legt keine Aufgabe an, wartet nicht.
- **Warten** (`--await --task-id`): klingelt **genau einmal** beim Arbeiter
  (`herdr agent prompt <name> "…"`, ohne `--wait`), pollt danach `tasks.json` bis
  zu einer der fuenf Ruecklagen (Abschnitt 5). Poll-Intervall 1 s, Obergrenze
  `--timeout-ms` (Vorgabe 300 000). Keine zweite Klingel: ein Arbeiter, der die
  erste verschlafen hat, wird auch von der zweiten nicht geweckt — dafuer gibt es
  den Timeout und `session_error()`.

`agent_name()` und `profile_for()` fragen kuenftig die Settings statt der
Konstanten `PROFILE_BY_ROLE`/`DEFAULT_PROFILE`.

### Geaendert: `bin/herdr-dispatch`, `roles/*.md`, `.config/lean-herdr.toml` (neu)

Das Skript bekommt die neuen Flags. Die Rollentexte bekommen die
Dreischritt-Sequenz mit `ctx_call(name="ctx_task", …)` statt `ctx_agent post`,
und `input-required` als Rueckfragekanal.

### Unberuehrt

`bus.py`, `join.py`, `export.py`, `herdr.py`, `worktree.py`, `leanctx.py`.

`leanctx.post()` behaelt seine Signatur, verliert aber den einzigen Aufrufer. Der
Docstring haelt fest, dass es als `anonymous` postet und **nicht fuer Auftraege
taugt** — sonst greift jemand spaeter danach.

## 5. Fehlerbehandlung

Der Warte-Modus kehrt bei fuenf Lagen zurueck:

| Zustand | Rueckgabe |
|---|---|
| `completed` | `ok: true`, Abschlussnachricht |
| `failed` | `ok: false`, `error: agent_failed:<message>` |
| `canceled` | `ok: false`, `error: task_canceled` |
| `input-required` | `ok: false`, `error: input_required`, **plus die Frage** |
| Timeout | `ok: false`, `error: no_reply` |

Weitere Codes: `pane_split_failed`, `no_agent_id`, `tasks_unreadable`,
`task_not_found`, `agent_error:<text>`, `worktrunk_missing`,
`worktree_open_failed:<msg>`, `no_anchor_pane`, `dispatch_crashed`. Entfallen:
`post_failed:<text>`, `bus_unreadable`.

`input-required` kehrt bewusst zurueck, obwohl `is_terminal()` es nicht als
terminal fuehrt: der Orchestrator muss geweckt werden, sonst wartet das Skript auf
eine Antwort, die ohne ihn nie kommt. Er beantwortet per `ctx_task message` +
`update(state="working")` und ruft `--await` erneut. Das ist die einzige Stelle,
an der die Schleife zum Modell zurueckkehrt — mit konkretem Anlass, also kein
Polling.

**H1 bleibt gewahrt, strenger als bisher.** Der Erfolgsbeweis ist der
Zustandsuebergang, den der adressierte Arbeiter selbst setzt, nicht ein
Lebenszyklusfeld. `agent_status: idle` bedeutet weiterhin nichts.

Stuerzt ein Arbeiter ab, bevor er etwas setzt, verharrt die Aufgabe auf `created`
oder `working` bis zum Timeout. Dann greift `session_error()` aus `export.py`
unveraendert und macht aus dem nichtssagenden `no_reply` ein `agent_error:<text>`
mit der Ursache aus dem nativen Session-Export.

**Lebensdauer und Aufraeumen:** Niemand im Projekt raeumt Aufgaben auf.
`ctx_task` ruft bei **jedem** Aufruf `cleanup_old(72)` und entfernt terminale
Aufgaben, die aelter als 72 Stunden sind (`core/a2a/task.rs:250`). Eine
haengengebliebene, nicht-terminale Aufgabe bleibt dagegen liegen — das ist
gewollt: sie ist der Beleg, dass ein Durchlauf abgebrochen ist. Der Mensch kann
sie mit `ctx_task cancel` schliessen, was laut `handle_cancel` **nur dem
Ersteller** erlaubt ist, also dem Orchestrator.

## 6. Testbarkeit

**Unit-Tests** gegen Doppel: `FakeProc` fuer Herdr-Aufrufe, gefaelschte
`tasks.json` unter `tmp_path`. Deckt `tasks.py` vollstaendig ab und alle fuenf
Ruecklagen des Warte-Modus.

**Eingefrorene Probe** analog `registry.sample.json`, aber mit einer Lektion aus
Task 2: die dortige Probe enthielt *konstruierte* Werte, deren Absender-IDs nicht
mit echten uebereinstimmten, und belegte deshalb nichts. Fuer `tasks.json` wird
der **real gemessene** Eintrag `task-1a05e34cd15-1cf3b885` eingefroren. Ein
Formatwechsel bei lean-ctx faellt dann sofort auf.

**Integrationstests** werden durch `LEAN_CTX_DATA_DIR` erstmals sauber moeglich:
Der Test setzt die Variable auf `tmp_path` und bekommt einen vollstaendig
isolierten Store. Damit laesst sich echt gegen `ctx_task` pruefen — dass `info`
die erwartete Form liefert, dass `create` ohne Registrierung scheitert, dass die
Zustandsnamen stimmen. Weiterhin unter `-m integration`, nie im normalen Lauf.

**Die Grenze, ausdruecklich:** Der Schreibpfad ist nicht unit-testbar.
`ctx_task create` verlangt einen registrierten, langlebigen MCP-Agenten — genau
das, was ein Testprozess nicht sein kann. Dass der Orchestrator die Aufgabe
korrekt anlegt und der Arbeiter sie ueber `list` findet, laesst sich **nur im
Durchlauf** beweisen. Die Rollentexte sind damit kritisches Material;
`tests/test_role_prohibitions.py` wird um die neuen Pflichtsaetze erweitert (der
Arbeiter prueft `ctx_task list`, beginnt mit `update(state="working")`, endet mit
`completed`/`failed`). Das faengt wenigstens die Textdrift.

## 7. Was dieser Entwurf NICHT tut

- **Kein Eingriff in lean-ctx.** Die Tools bleiben unsichtbar; `ctx_call` genuegt.
- **Kein Fan-out.** Ein Arbeiter je (Branch, Rolle), wie bisher.
- **Kein Schreiben in `tasks.json` durch Python.** Nur registrierte MCP-Agenten
  schreiben, ueber `ctx_call`.
- **Keine Migration alter Bus-Auftraege.** Es gibt keine — der Weg hat nie
  funktioniert.
- **Kein Einsatz der `leanctx-sdk`.** Version 1.0.0 wurde am 2026-09-02 gegen die
  echte `lean-ctx 3.10.1` gemessen und verworfen. Sechs Gründe, jeder allein
  ausreichend: `SubprocessEngineClient` kennt nur zwei Engine-Operationen und kann
  `ctx_call` nicht ersetzen; `fork` plus `attach_session` scheitert, womit der
  Fan-out-Weg entfällt; ein `ContextWorkspace` trägt genau einen Auftrag; ein
  `input-required`-Zustand fehlt; unsere Arbeiter sind MCP-Agenten, für die es
  keinen Adapter gibt; und die SDK ist source-available, der Betrieb bräuchte
  einen Vertrag mit Thinkery AG. Der oft vermutete siebte Grund — der
  Engine-Versions-Pin — trägt **nicht**: 3.10.1 wird angenommen. Belege,
  Gegenprobe und Reproduktion in
  `docs/specs/2026-09-02-leanctx-sdk-evaluation.md`.

## 8. Stand des Implementierungsplans

Diese Spec entstand **mitten im Lauf** des Plans
`docs/lean-md/plans/2026-09-01-lean-herdr.lmd.md`. Wer den neuen Plan schreibt,
muss wissen, was schon steht und was nicht.

### Abgenommen (jeweils zwei Verdikte, Mutationsproben, `ruff` + `pytest` + `ty` gruen)

| Task | Ergebnis | Commit |
|---|---|---|
| 1 | `canonical_root()`, Testtor gegen echtes `git worktree add` | `5844c76` |
| 2 | `parse_registry()`, eingefrorene Registry-Probe | `2df0582` |
| 3 | PID-Join ueber das `pid`-Feld | `3dcc8fc`, **Fix** `4d2a747` |
| 4 | `find_error()`/`session_error()` — Erfolg am Inhalt (H1) | `6c23f3b`, `381d8fc` |
| 5 | `class Herdr` — aller Herdr-Verkehr | `5e345ca` |
| 6 | `leanctx.py` — CLI-Gateway mit erzwungenem `--project-root` | `398d920` |
| 7 | die drei Rollentexte | `62013c5`, `42756f2`, `8106d60` |
| 8 | `opencode.jsonc`, `.config/wt.toml`, README | `043c2ca` |
| 9 | `dispatch.py`, `bin/herdr-dispatch` | `7bb6583`, `a53d7c2` |
| 10 | `worktree.py`, `--worktree` | `daf56d9`, `afe1d4f` |
| 13 | Plugin-Geruest: Manifest, `config.py`, `__main__.py` | `4e33316`, `ea04deb` |

Querschnitt ausserhalb der Tasks: Python 3.14 (`50d68d0`), ty/ruff als
Language-Server (`0361547`), `PGH005` per-file (`e2add54`).

### Widerlegt

**Task 11 (Stufe 3, Ein-Aufgaben-Durchlauf)** — der Anlass dieser Spec. Der
Durchlauf lief bis zur Zuteilung und scheiterte dort an B-1 und B-2. Er hat
dabei drei Dinge geleistet, die kein Test geleistet haette: den PID-Join-Fehler
gefunden (Fix `4d2a747`, im echten Dispatch verifiziert), die
Prompt-Injection-Abwehr im Feld bestaetigt (der Builder lehnte den anonymen
Auftrag ab und begruendete es), und den Konstruktionsfehler des Auftragswegs
offengelegt.

### Blockiert oder offen

- **Task 12 (Stufe 4, Worktree-Durchlauf mit Merge)** — setzt 10 und 11 voraus,
  also blockiert, bis dieser Umbau steht. Enthaelt einen **ausstehenden
  README-Patch**: der Hinweis auf `wt config approvals`. Ohne diese Freigabe
  ueberspringt worktrunk Projekt-Hooks **stillschweigend** (`wt hook --help`:
  *"Declining skips every project command for that operation … and continues
  without them"*), das pre-merge-Testtor aus `.config/wt.toml` laeuft dann gar
  nicht. Der Plan sieht den Patch in Task 12 vor (Plan-Quelle Zeilen 4035-4058).
  **Bei der Abnahme von Task 12 pruefen, dass er tatsaechlich passiert ist** — ein
  Tor, auf das man sich verlaesst und das lautlos uebersprungen wird, ist
  gefaehrlicher als keines.
- **Task 14 (`digest.py`)** — offen, haengt an nichts, kann jederzeit laufen.
- **Task 15 (`handlers.py`)** — offen, setzt 13 und 14 voraus.
- **Task 16 (opencode-Policy-Adapter)** — offen, haengt an keiner anderen Task.

### Unbewiesene Annahmen der Ursprungsspec

- **Endebedingung (offener Punkt 4).** Im Durchlauf erschien im Builder-Pane nach
  getaner Arbeit der Vorschlag `❯ Bus nochmal pruefen, ob T1 inzwischen vom
  Orchestrator gekommen ist` — als Vorschlag im Eingabefeld, Status blieb `done`,
  keine laufende Schleife. Das Polling-Verbot in `roles/builder.md` hat den
  Gedanken nicht verhindert. Mit `ctx_task` verschiebt sich die Lage (der Arbeiter
  hat einen definierten Abschluss statt eines offenen Busses), aber der Beweis
  steht aus.
- **Kostenmessung (offener Punkt 13)** — was `minimal` gegenueber `standard`
  wirklich spart, ist weiterhin hochgerechnet, nicht gemessen.
- **`kind="claude"`-Pfad von `session_error()`** — nur der opencode-Pfad hat einen
  positiven Integrationstest. Ob `ERROR_KEYS` zum realen Claude-Code-jsonl-Schema
  passt, ist unbelegt. Folgenlos fuer H1 (ein falsch-negatives `find_error()`
  verschlechtert die Fehlermeldung, verwandelt aber kein Scheitern in Erfolg),
  aber offen.

### Bewusst akzeptierte Abweichungen

- `parse_registry()` hat kognitive Komplexitaet 17 ueber der Projektschwelle 15 —
  vom Betreiber abgenommen, der Brief-Code bleibt Vergleichsgrundlage.
- Der Plan-Code war durchgehend **deutsch benannt**. Der Durchgang fand am
  2026-09-02 statt (`docs/lean-md/plans/2026-09-02-lean-herdr-englisch-und-plugin.lmd.md`);
  seither ist alles außerhalb `docs/` englisch und `tests/test_language.py` hält
  es so.
- `@reformat` wird nicht ausgefuehrt: das Qualitaetstor ist `ruff check`, **nicht**
  `ruff format --check` — sonst schriebe der Formatter den woertlichen Plan-Code um.
