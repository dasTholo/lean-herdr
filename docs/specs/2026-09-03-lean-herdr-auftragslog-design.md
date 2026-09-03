# lean-herdr: Auftragsweg auf ein eigenes Ereignis-Log — Design v1.0

**Stand:** 2026-09-03 · **Status:** entworfen, nicht implementiert
**Ersetzt:** den `ctx_task`-Auftragsweg aus
`2026-09-01-lean-herdr-ctx-task-design.md` (dessen Abschnitte 3 bis 6)
**Anlass:** Die `leanctx-sdk` hat mit PR #8 und PR #10 zwei Versionen
nachgelegt. Die Gegenprüfung gegen
`2026-09-02-leanctx-sdk-evaluation.md` hat dabei nicht die SDK als Lösung
gefunden, sondern die Annahme widerlegt, die den `ctx_task`-Weg überhaupt
erzwungen hat.

> **Zur Schreibweise:** Dieses Dokument benutzt korrekte deutsche Umlaute, wie
> `2026-09-02-leanctx-sdk-evaluation.md`. Die älteren Specs im selben
> Verzeichnis benutzen die Ersatzschreibung `ae/oe/ue`.

## 1. Der Anlass, und warum er nicht die SDK ist

Der Betreiber fragte, ob PR #8 der `leanctx-sdk` dem Auftragsweg hilft. Die
Messung sagt nein — aber sie hat unterwegs etwas anderes gefunden.

**PR #8 hilft nicht.** `AgentContext` erreicht nur eine geschlossene, beim
Handshake beidseitig geprüfte Menge von Werkzeugen. Gemessen gegen die lokale
`lean-ctx 3.10.1`:

```
read-only:  ctx_compose ctx_glob ctx_read ctx_search ctx_symbol ctx_tree
+ write:    ctx_edit ctx_fill ctx_patch
+ execute:  ctx_shell
ctx_task / ctx_agent / ctx_session / ctx_handoff / ctx_call
  → UnsupportedCapabilityError: Engine did not negotiate capability
```

Die Menge steht als `frozenset` in `agent.py:41-45`. Befund E-2 der Evaluation
bleibt damit vollständig: die SDK kann `leanctx.py` nicht ersetzen.

**PR #10 löst E-4, verschärft E-7.** Fork plus `attach_session` aus einem
Fremdprozess läuft jetzt durch (`workspace_completed seq=5`). Ändert der
Arbeiter dagegen die gebundene Quelldatei vor dem Anhängen, scheitert es mit
`WorkspaceConflictError` — der Fall, den die Evaluation offen ließ, ist
geschlossen und trifft genau einen Builder.

**Der eigentliche Fund liegt neben der SDK.** Zwei tragende Annahmen der
Evaluation hielten der Nachmessung nicht stand, und beide hingen nicht an der
SDK, sondern an der Art ihrer Benutzung:

- **E-5 („ein Workspace trägt genau einen Auftrag")** — die alte Messung rief
  `ws.complete()` je Auftrag und schloss aus dem terminalen Lebenszyklus auf
  die Grenze. `complete()` ist optional. Gemessen tragen sechs Aufträge und
  vier Sitzungen einen Workspace, der durchgehend `active` bleibt.
- **E-6 („kein `input-required`")** — der Rückfragezyklus läuft vollständig
  ohne `abort`: `unresolved_questions` → der Orchestrator liest → `decisions` →
  der Arbeiter macht weiter.

Daraus folgt nicht, dass die SDK die Antwort ist. Es folgt, dass **die
Architektur** die Antwort ist, die die Evaluation an der SDK gemessen hat: ein
dateibasiertes, append-only, hash-verkettetes Ereignis-Log. Das ist
`json` + `hashlib` + `pathlib` aus der Standardbibliothek.

## 2. Entscheidung

Der Auftragsweg wechselt von `ctx_task` auf ein **eigenes Ereignis-Log**.

**Die tragende Umkehrung:** Der `ctx_task`-Entwurf ruht auf dem Satz
*„Schreiben braucht Identität, Lesen nicht."* Daraus folgte alles Weitere —
der Orchestrator muss ein registrierter, langlebiger MCP-Agent sein, Python
darf **nie** schreiben, und der Schreibpfad ist nicht unit-testbar (Abschnitt 6
der Vorgängerspec, ausdrücklich eingeräumt).

Mit einem eigenen Log schreibt jeder Prozess. Der Auftrag wird zum
Skriptaufruf, und die eingeräumte Lücke schließt sich.

**Der Kontext bleibt bei lean-ctx.** `ctx_knowledge` ist Kernprodukt und
beworben; `ctx_task` steht in `LOCAL_COLLABORATION_COMPATIBILITY_TOOLS` mit dem
Kommentar *„LeanCTX is a Context SDK, not an agent coordination product."*
Thinkerys eigenes `docs/PREVIEW.md` zieht dieselbe Grenze: *„durable context
state, not an agent task queue … worker scheduling remain owned by the host
orchestration layer."* Drei unabhängige Quellen, eine Linie: **Kontext gehört
zu lean-ctx, Auftragskoordination gehört uns.**

**Die SDK bleibt draußen** — als gemessene Formatvorlage, nicht als
Abhängigkeit. `ContextWorkspace` ist weiterhin PREVIEW, und ein Workspace neben
`ctx_knowledge` und `ctx_handoff` wäre ein dritter Kontextspeicher für einen
Zweck, den der erste erfüllt.

## 3. Gemessener Ausgangsbestand

Alle Messungen am 2026-09-03 gegen `lean-ctx 3.10.1` und den SDK-Checkout
`277d0c7`; Reproduktion in Abschnitt 12.

| Befund | Beleg |
|---|---|
| `AgentContext` läuft, erreicht `ctx_task` aber nicht | `UnsupportedCapabilityError`, `agent.py:41-45`, `agent.py:483` |
| Agent Tools verlangen Engine **exakt** `3.10.1` | `agent.py:436`, `SUPPORTED_AGENT_TOOLS_ENGINE_VERSION`; anders als der Workspace-Kern, der nur die Major-Version prüft (E-1) |
| SDK 1.1.0 ist nicht veröffentlicht | PyPI führt `1.0.0`; `COMPATIBILITY.md`: Engine 3.10.1 *„not yet published"*; GitHub-Release der Engine ist `v3.10.0` |
| Fork + `attach_session` aus dem Fremdprozess trägt | `[worker] attach_session OK`, `workspace_completed seq=5` |
| Quelländerung nach dem Bind scheitert | `attach_session FAIL WorkspaceConflictError` |
| ein Workspace trägt beliebig viele Aufträge | `lifecycle=active events=12 sessions=4 entries=6` |
| Rückfragezyklus ohne `abort` läuft | `unresolved_questions` → `decisions` → weiterarbeiten |
| **ein CLI-Prozess schreibt in `ctx_knowledge`** | `Remembered [facts] probe-cli-write … (revision 1)` — ohne Registrierung, anders als `ctx_task` (B-2) |
| `ctx_task list` ist bereits agent-gefiltert | `No tasks found for this agent.` — der globale TaskStore landet nie im Arbeiterkontext |
| `ctx_knowledge recall` braucht die Kategorie | ohne `category`: `No facts matching …`, auch mit `mode=exact`; mit `category`: `showing 1/1` |
| `ctx_knowledge search` ist projektübergreifend | 12 Treffer aus mehreren Projekten, **3778 Tokens** |
| lean-ctx hat den Lebenszyklus bereits | `cap 800, decay 0.01/day, stale >30d`; `GC: eviction archives, never deletes`; Archive werden bei `recall`-Miss rehydriert |
| die Wissens-Kappe ist **global**, nicht projektweise | `278 active / 21 archived (cap 800)` über alle Projekte des Rechners |
| Wissen wird **injiziert**, nicht gelesen | `ctx_read(tasks.py)` → 1 Eintrag ~150 Tok, mitten im Wort gekürzt; `ctx_read(settings.py)` → 2 Einträge ~120 Tok, `phi=0.32`; `ctx_read(handlers.py)` → **nichts** |
| lean-ctx adressiert Projekte über Hashes | `projects/` führt 68 Ordner mit 16-stelligen Hex-Namen — ein eigener Namensraum ist nötig |

## 4. Architektur und Datenfluss

```
Orchestrator                herdr-dispatch                 Arbeiter
──────────────────────────────────────────────────────────────────────
1. herdr-dispatch builder   → Pane splitten, Agent starten
                              agent_id auflösen (Bereitschaftsbeleg)
                            ← {"ok":true,"agent_id":"mcp-…","pane":"w1:pX"}

2. herdr-dispatch order     → Ereignis `created` ins Log
     --to builder@feat-x      (KEIN MCP, kein ctx_call)
     --after o-2
     --message "…"          ← {"ok":true,"task_id":"o-3"}

3. herdr-dispatch --await   → klingeln            → herdr-report next
     --task-id o-3            Ereignisse lesen    ← herdr-report start
                              bis terminal        ← herdr-report done|fail|ask
                            ← {"ok":true,"state":"completed","message":"…"}
```

Schritt 3 bleibt unverändert der Kern: **das Warten bleibt im Skript.** Kein
CLI-Aufruf je Runde, keine Registrierung, keine Modellkosten. Das
Polling-Verbot des Rollentexts bleibt gewahrt.

Schritt 2 ist die Änderung: Er war ein MCP-Werkzeugaufruf, den nur ein
registrierter Agent machen konnte. Jetzt ist er ein Skriptaufruf.

**Der PID-Join bleibt tragend, wechselt aber die Rolle.** Die Adresse ist
künftig der Herdr-Agentenname `builder@feat-x`, den beide Seiten ohne
Auflösung kennen — `tasks_for_agent()` mit seinem exakten String-Vergleich
(`core/a2a/task.rs:236`) fällt weg. `wait_for_agent_id` wird damit vom
Adressauflöser zum **Bereitschaftsbeleg**: der Agent ist hochgekommen und bei
lean-ctx registriert. Task 3 und Fix `4d2a747` bleiben in Kraft.

**Der Ort des Logs:**

```
lean_ctx_data_dir() / "lean-herdr" / <repo-name> / orders/
```

Drei Gründe für das lean-ctx-Datenverzeichnis statt eines eigenen XDG-Pfads:
`tasks._data_dir()` steht bereits gemessen und getestet, mit der vollständigen
Präzedenz aus `core/data_dir.rs:12` und der Legacy-Erkennung `_has_data()`;
`LEAN_CTX_DATA_DIR` wird damit auch unser Testgriff, und zwar erstmals für
**beide** Pfade; und ein Zustandsort ist konsistenter als ein verwaistes Log
neben einem deinstallierten lean-ctx.

Der Zwischenordner heißt `lean-herdr`, nicht `herdr` — `herdr` ist der
Terminal-Multiplexer, den dieses Projekt steuert, und ein Ordner dieses Namens
in einem fremden Datenverzeichnis würde falsch gelesen. Er grenzt uns zugleich
gegen die 35 lean-ctx-eigenen Ordner ab.

**Eine Wahrheit, nicht zwei.** Das Abschluss-Review über `707ceb5..a631ab4`
führt als M3 auf, dass `bus.REGISTRY_PATH` und `dispatch.default_registry_path`
zwei abweichende Wahrheiten für denselben Pfad sind. Dieser Entwurf führt einen
neuen Pfad ein und darf das Muster nicht wiederholen: `orderlog.state_dir()`
ist die **einzige** Auflösung. Keine Modulkonstante daneben, kein zweiter
Aufbau in `dispatch.py`, keine Voreinstellung im CLI. Wer den Pfad braucht,
ruft die Funktion.

**Ein Randfall, bewusst festgelegt:** Zwei unabhängige Klone desselben Repos
träfen sich in demselben Ordner. Der Ordner trägt deshalb eine Datei `root` mit
dem kanonischen Pfad aus `bus.canonical_root()`. Weicht sie beim Öffnen ab, ist
das der Fehler `state_root_mismatch` — **kein** automatisches Ausweichen auf
einen Hash-Suffix. Der Randfall wird sichtbar, statt sich still zu vermischen.

**Ein Prüfpunkt für den Plan:** ob lean-ctx je einen Reaper über fremde
Unterordner seines Datenverzeichnisses laufen lässt. `ctx_task` räumt
nachweislich nur `agents/tasks.json` (`cleanup_old(72)`,
`core/a2a/task.rs:250`), und die Existenz von `addons/`, `context-os/` und
`packages/` spricht für geduldete Fremd-Namensräume — aber das ist ein Indiz,
keine Messung. Der Plan misst es, bevor er sich darauf verlässt.

## 5. Komponenten

`tasks.py` (201 LOC, nur lesend) wird abgelöst. Sein wertvollster Teil
überlebt: `_data_dir()` samt `_has_data()`. Was entfällt, ist die
Rust-Enum-Übersetzung `normalize_state` — unser Log schreibt unsere Namen.

An seine Stelle treten **zwei** Module statt eines. Die Grenze hält beide unter
200 LOC und macht sie getrennt testbar.

### Neu: `lean_herdr/orderlog.py` — die Ablage

Weiß nichts von Aufträgen, nur von Ereignissen.

```
state_dir() -> Path                                # + `root`-Wächter
append(task_id, kind, actor, payload) -> Event     # atomar, hash-verkettet
read_events(task_id) -> list[Event]
task_ids() -> list[str]
```

Anhängen ist `Path.write_text()` auf eine Temporärdatei, dann
`Path.replace()` — derselbe atomare Rename wie `os.replace`, in der API, die
der übrige Baum benutzt. **Kein `os.fsync`:** ein Auftragslog auf einem
Entwicklerrechner muss nicht gegen Stromausfall härten, und es wäre der einzige
`os`-Griff in einem sonst reinen `pathlib`-Modul.

Der Dateiname trägt die 16-stellige Sequenz und den Digest-Präfix, nach dem
Vorbild, das E-3 der Evaluation an der SDK gemessen hat:

```
orders/<task_id>/events/0000000000000003-a3f1c9e2.json
```

**Der Repo-Name** ist `bus.canonical_root().name` — der Verzeichnisname des
kanonischen Haupt-Checkouts, nicht der eines Worktrees und nicht `$PWD`. Alle
Arbeiter eines Branches treffen sich damit im selben Log, egal aus welchem
Worktree sie schreiben.

**Die `task_id`** erzeugt `herdr-dispatch order`, nach demselben Muster wie
lean-ctx: ein Präfix, ein Zeitstempel in Millisekunden als Basis-36, ein
Zufallssuffix — `o-1a05e34cd15-1cf3b885`. Sie ist projektweit eindeutig, ohne
Zähler und ohne eine Datei, die zwei gleichzeitige Aufrufe sperren müssten. Die
Kurzform `o-3` in den Beispielen dieses Dokuments steht für die Lesbarkeit.

### Neu: `lean_herdr/orders.py` — das Auftragsmodell

Weiß nichts von Dateien, nur von Ereignislisten.

```
Order (frozen)                    # id, to_agent, state, description,
                                  # after, messages
fold(events) -> Order             # Zustand = letzter Übergang
is_terminal(state) -> bool
message_from(order, actor) -> str | None
```

Das ist der Grund für den Schnitt: `fold()` ist eine reine Funktion über eine
Liste. Der Kern des Auftragswegs wird ohne Dateisystem, ohne `tmp_path`, ohne
Fixture testbar.

### Neu: `bin/herdr-report` — das Arbeiter-CLI

Dünn, nach dem Vorbild von `bin/herdr-dispatch`. Sechs Subkommandos:

| Kommando | Wirkung |
|---|---|
| `next` | der offene Auftrag für diesen Agenten, mit dem Vorlauf (§7) |
| `show --task o-…` | ein Auftrag mit seiner Ereignisliste |
| `start --task o-…` | Ereignis `working` |
| `done --task o-… --message "…"` | Ereignis `completed` |
| `fail --task o-… --message "…"` | Ereignis `failed` |
| `ask --task o-… --message "…"` | Ereignis `input-required` |

Kein `note`-Kommando, kein `recall` — Begründung in §7.

**Wie der Arbeiter weiß, wer er ist — ein Regress, der behoben werden muss.**
Bei `ctx_task` musste er das nie wissen: `list` filtert serverseitig nach der
registrierten `agent_id` des aufrufenden Prozesses („No tasks found for this
agent", gemessen). Mit einem eigenen Log fällt dieser Filter weg, und
`herdr-report` muss seinen Namen selbst bestimmen. Er tut das aus dem, was beim
Agentenstart bereits gesetzt wird:

```python
role   = os.environ["LEAN_CTX_ROLE"]        # dispatch.py setzt sie beim Start
branch = <aktueller Branch im cwd>          # worktree.py
name   = agent_name(role, branch, settings=settings_for(role))
```

`agent_name()` und `settings_for()` bestehen bereits und werden
wiederverwendet, nicht nachgebaut — damit trägt der Arbeiter garantiert
denselben Namen, unter dem `herdr-dispatch` ihn adressiert und anklingelt. Das
`name_template` aus `.config/lean-herdr.toml` gilt für beide Seiten.

Fehlt `LEAN_CTX_ROLE`, bricht `herdr-report` mit `no_role` ab, statt einen
Namen zu raten. Ein Flag `--agent` überschreibt die Auflösung; es dient Tests
und der Diagnose von Hand, nicht dem Regelbetrieb, und die Rollentexte nennen
es nicht.

### Geändert: `lean_herdr/dispatch.py`

- neues Subkommando `order` — der Schreibpfad, den heute nur ein MCP-Agent
  gehen kann; dazu `cancel` für hängengebliebene Aufträge
- `await_task` liest `orderlog` statt `tasks`
- `_result_for_state` behält seine **Form** und damit die fünf Rücklagen aus
  Abschnitt 5 der Vorgängerspec unverändert

### Geändert: `lean_herdr/leanctx.py`

Eine neue Methode neben `session_resume()` / `handoff_list()`:

```python
def knowledge_remember(self, *, key: str, value: str,
                       category: str = "decisions") -> CtxResponse
```

Kein `knowledge_recall()` — Begründung in §7. Das Modul kommt in B2a des
laufenden Plans ohnehin aus `72dee2f^` zurück.

### Entfällt ersatzlos

`lean_herdr/tasks.py`, `tests/test_tasks.py`,
`tests/test_tasks_integration.py`, `tests/fixtures/tasks.sample.json` — und
damit auch deren Ausnahme in `tests/test_language.py`, die als Buchhaltung
mitwandert.

## 6. Das Ereignisformat

```json
{ "schema_version": "lean-herdr.order-event/v1",
  "sequence": 3,
  "kind": "input-required",
  "task_id": "o-3",
  "actor": "builder@feat-x",
  "at": "2026-09-03T07:12:04Z",
  "previous_digest": "sha256:…",
  "payload": { "message": "Welche Branch-Strategie?" } }
```

Sieben Ereignisarten:

```
created · working · input-required · answered · completed · failed · canceled
```

`answered` ist neu gegenüber `ctx_task`. Dort versteckt sich die Antwort des
Orchestrators im `message` eines `update(state="working")`, was
`orchestrator.md` heute in sechs Zeilen erklären muss — samt der Warnung, dass
`action: "message"` in einen Speicher schreibt, den kein `ctx_task`-Aufruf je
ausgibt. Hier ist die Antwort ein eigenes Ereignis, und beide Erklärungen
fallen ersatzlos weg.

Das `created`-Ereignis trägt zusätzlich `to_agent`, `description` und optional
`after` — die `task_id` des Vorgängerauftrags (§7).

**Der Zustand ist die Faltung, nicht ein Feld.** Das Log ist append-only; ein
Zustand wird nie überschrieben, nur ein neues Ereignis angehängt. `fold()`
liest den letzten Zustandsübergang.

## 7. Kontext — fünf Quellen, eine davon passiv

| Was | Woher | Wie |
|---|---|---|
| die Anweisung | `created`-Ereignis | `herdr-report next` — aktiv |
| der Verlauf dieses Auftrags | dieselben Ereignisse | `herdr-report show` — aktiv, nur nach einer Rückfrage |
| der Vorlauf | Abschlussereignis des Vorgängers | in `next` eingefaltet |
| die Rolle | `roles/<rolle>.md` | Systemprompt, überlebt `/clear` |
| Langzeitgedächtnis | `ctx_knowledge` | **Injektion** — passiv |

### Der Vorlauf: verweisen statt nacherzählen

```
$ herdr-report next
o-3  [created]  ← orchestrator
Build the order log module per plan task 4.
after: o-2 (reviewer@feat-x, completed)
  "Reviewed the fold() unit; two findings, both fixed. VERDIKT: result"
```

Heute schreibt der Orchestrator den Vorlauf in die Beschreibung: er formuliert
ihn, der Arbeiter liest ihn, und der Wortlaut der Vorgängermeldung geht durch
die Nacherzählung verloren. Mit `--after o-2` steht dort das Original, und es
kostet **keinen** zweiten Werkzeugaufruf — `next` faltet es ein.

### Warum der Arbeiter `ctx_knowledge` nicht liest

Gemessen wird Wissen **injiziert**, nicht abgerufen: ein `ctx_read` bringt
relevante Einträge ungefragt mit, gedeckelt durch `recall_facts_limit=10`,
gefiltert über eine Relevanzschwelle (`ctx_read(handlers.py)` bekam nichts) und
hart gekürzt (der Eintrag bei `tasks.py` brach mitten im Wort ab).

Daraus folgt: **kein Leseschritt im Rollentext.** Kein Werkzeugaufruf, keine
erklärenden Zeilen, kein `knowledge_recall()` in `leanctx.py`. Was relevant
ist, steht schon im Kontext, wenn der Arbeiter seine erste Datei liest.

### Warum der Arbeiter `ctx_knowledge` nicht schreibt

Die Kappe von 800 Einträgen ist **global**. Schriebe jeder Arbeiter je Auftrag
drei bis fünf Notizen, wären das bei zehn Aufträgen fünfzig Einträge je Branch
— nach fünfzehn Branches verdrängt lean-herdr die Erinnerungen fremder
Projekte.

Deshalb: **ein Eintrag je Branch, nicht je Auftrag**, geschrieben vom
Orchestrator beim Abschluss über `knowledge_remember()`, Schlüssel
`lean-herdr/<branch>`, Kategorie `decisions`. Inhalt sind **ein bis zwei
Sätze** — was der Branch erreicht hat und welche Entscheidung ihn überlebt.
Nicht der Verlauf; der steht im Log.

Die Kürze ist eine Regel, keine Stilfrage: die Injektionsquote ist gedeckelt,
und ein langer Eintrag verdrängt nützlichere. Bestehende lean-herdr-Einträge
mit 400–500 Wörtern sind für den Menschen geschrieben, konkurrieren aber um
denselben Platz.

**Aufgeräumt wird nicht.** lean-ctx hat den Lebenszyklus bereits — Verfall
0,01/Tag, stale ab 30 Tagen, Archivierung statt Löschung bei Erreichen der
Kappe, Rehydrierung bei `recall`-Miss. Ein eigener Reaper wäre eine zweite
Politik neben einer funktionierenden. Die Sparsamkeit beim Schreiben ist die
Vorsorge, nicht das Aufräumen danach.

## 8. Fehlerbehandlung

Die fünf Rücklagen des Warte-Modus bleiben **wörtlich** wie in Abschnitt 5 der
Vorgängerspec. Das ist der Vertrag mit `orchestrator.md`, und er ändert sich
nicht:

| Zustand | Rückgabe |
|---|---|
| `completed` | `ok: true`, Abschlussnachricht |
| `failed` | `ok: false`, `error: agent_failed:<message>` |
| `canceled` | `ok: false`, `error: task_canceled` |
| `input-required` | `ok: false`, `error: input_required`, plus die Frage |
| Timeout | `ok: false`, `error: no_reply` |

**Neue Codes:** `state_root_mismatch` (der Kanonik-Wächter), `no_role`
(`LEAN_CTX_ROLE` fehlt, §5),
`log_unreadable:<pfad>` (Gegenstück zu `tasks_unreadable`),
`chain_broken:<seq>`. **Entfällt:** `tasks_unreadable`. **Bleibt:**
`task_not_found`, `pane_split_failed`, `no_agent_id`, `agent_error:<text>`,
`worktrunk_missing`, `worktree_open_failed:<msg>`, `no_anchor_pane`,
`dispatch_crashed`.

`chain_broken` ist der Zugewinn: `previous_digest` macht eine Lücke oder eine
nachträgliche Änderung sichtbar. Bei `tasks.json`, das bei jedem Schreibvorgang
komplett ersetzt wird, gibt es dafür kein Gegenstück. Eine gebrochene Kette ist
ein **Fehler**, nie ein „nichts zu tun" — dieselbe Regel, die `read_tasks()`
heute für den kaputten Store durchhält.

**Eine unbekannte Ereignisart wird nie terminal.** Wörtlich die Regel aus
`normalize_state`: ein fremdes `kind` bleibt verbatim, gilt nicht als terminal,
und der Warte-Modus läuft in den Timeout — sichtbar, statt einen falschen
Erfolg zu melden.

**H1 bleibt gewahrt.** Der Erfolgsbeweis ist das Ereignis, das der adressierte
Arbeiter selbst schreibt. `agent_status: idle` bedeutet weiterhin nichts.
Stürzt ein Arbeiter vor dem ersten Ereignis ab, verharrt der Auftrag auf
`created`, und `session_error()` aus `export.py` macht aus dem `no_reply` ein
`agent_error:<text>`. Dieser Pfad bleibt vollständig unangetastet.

**Aufräumen und Lebensdauer:** niemand räumt auf, und das ist gewollt. Anders
als bei `ctx_task` gibt es kein `cleanup_old(72)`, das terminale Aufträge nach
72 Stunden entfernt — das Log bleibt liegen, bis der Mensch es löscht. Ein
liegengebliebener nicht-terminaler Auftrag bleibt der Beleg, dass ein Durchlauf
abgebrochen ist; `herdr-dispatch cancel --task-id …` schließt ihn.

**Ehrlich zu benennen — ein Verlust:** `ctx_task cancel` erlaubt das Schließen
laut `handle_cancel` **nur dem Ersteller**. Diese Zusicherung des Werkzeugs
wird zu einer Regel im Rollentext. Wir tauschen eine erzwungene
Zugriffsregel gegen eine vereinbarte.

## 9. Erlaubnisse — die neue Angriffsfläche

Der Punkt, der beim Abschluss-Review als M5 aufkam und beim Nachmessen größer
wurde als der Befund selbst.

**Gemessen:** `roles/builder.md` und `roles/reviewer.md` enthalten heute
**keine einzige Shell-Zeile**. Ihr gesamter Auftragsweg läuft über
`ctx_call(name="ctx_task", …)` — ein MCP-Werkzeug, das keine
Kommandozeilen-Erlaubnis braucht. Nur `orchestrator.md` ruft überhaupt eine
Shell (`bin/herdr-dispatch`, `herdr`, `wt`), und `opencode.jsonc` erlaubt ihm
genau das:

```jsonc
"orchestrator": { "permission": { "edit": "deny", "write": "deny",
  "bash": { "*": "deny", "bin/herdr-dispatch *": "allow", "herdr *": "allow",
            "wt *": "allow", "git status*": "allow", "git log*": "allow" } } }
"reviewer":     { "permission": { "edit": "deny", "write": "deny",
  "bash": { "*": "deny", "git diff*": "allow", "git log*": "allow",
            "git show*": "allow", "git status*": "allow" } } }
```

**Dieser Entwurf verlagert den Auftragsweg der Arbeiter von MCP auf ein CLI.**
Damit brauchen zwei Rollen erstmals eine Shell-Erlaubnis, die sie bisher nicht
hatten — und für `reviewer` steht dort ausdrücklich `"*": "deny"`. Ohne
Nachtrag könnte er seinen Auftrag nicht abholen. Das ist kein Blocker, aber es
ist der Preis dieses Entwurfs, und er gehört benannt statt entdeckt.

**Die Erlaubnis wird je Subkommando erteilt, nicht als Wildcard.** Ein
`"bin/herdr-report *": "allow"` würde alles durchlassen, was hinter dem
Programmnamen steht. Stattdessen:

```jsonc
"bash": { "*": "deny",
  "bin/herdr-report next": "allow",
  "bin/herdr-report show *": "allow",
  "bin/herdr-report start *": "allow",
  "bin/herdr-report done *": "allow",
  "bin/herdr-report fail *": "allow",
  "bin/herdr-report ask *": "allow" }
```

`builder` bekommt denselben Block; er ist in `opencode.jsonc` bisher gar nicht
geführt und muss angelegt werden. Die BOUNDARY-Abschnitte der Rollentexte
bleiben unverändert: das CLI schreibt Ereignisse, es führt nichts aus, was in
einem Auftrag steht.

**Für Claude-Code-Arbeiter ist die Lage anders und schlechter.** Das Repo
liefert keine `.claude`-Konfiguration aus — `git ls-files '.claude*'` ist leer,
gemessen. Die Erlaubnis hängt dort an den globalen Einstellungen des
Betreibers, und ein frischer Checkout auf einer anderen Maschine hat sie nicht.
Der Entwurf verlangt deshalb, dass `.claude/settings.json` mit denselben sechs
Mustern **ins Repo kommt** — sonst ist der Auftragsweg auf einer zweiten
Maschine stumm, und zwar mit einem Fehlerbild (der Arbeiter meldet nie etwas),
das aussieht wie ein Absturz und über `no_reply` in den Timeout läuft.

**Zur Präzisierung von M5:** Der Befund sagt, `roles/orchestrator.md:100`
verlange `jq`, das in keinem Allow-Muster stehe. Nachgemessen kommt `jq` in
`roles/` **null mal** vor. Was dort steht (`:101-102`), ist jq-*Syntax* als
Lesenotation für die JSON-Antwort von `herdr worktree list` — kein Aufruf. Der
Kern des Befundes bleibt aber richtig: die Notation lädt dazu ein, `jq`
tatsächlich aufzurufen, und das wäre nicht erlaubt. Da dieser Entwurf die
Rollentexte ohnehin überarbeitet, wird die Notation dort durch eine Formulierung
ersetzt, die kein Werkzeug nahelegt.

## 10. Testbarkeit

Der eigentliche Gewinn, und der Grund für den Modulschnitt aus §5.

- **`fold()` ohne Dateisystem.** Ereignisliste rein, `Order` raus. Alle sieben
  Ereignisarten, der Rückfragezyklus, die unbekannte Art, die Reihenfolge, die
  `after`-Einfaltung — reine Funktionstests.
- **`orderlog` gegen `tmp_path`.** Anhängen, Kette, atomarer Rename,
  `root`-Wächter, gebrochene Kette.
- **Der Schreibpfad wird unit-testbar.** Das schließt die Lücke, die Abschnitt
  6 der Vorgängerspec einräumt: *„Der Schreibpfad ist nicht unit-testbar.
  `ctx_task create` verlangt einen registrierten, langlebigen MCP-Agenten —
  genau das, was ein Testprozess nicht sein kann."* `herdr-dispatch order` ist
  ein Skriptaufruf.
- **Integrationstests** über `LEAN_CTX_DATA_DIR` auf `tmp_path`, weiterhin
  unter `-m integration`.
- **Rollentexte** bleiben kritisches Material.
  `tests/test_role_prohibitions.py` bekommt die neuen Pflichtsätze: der
  Arbeiter ruft `herdr-report next`, beginnt mit `start`, endet mit
  `done`/`fail`.

**Die verbleibende Grenze, ausdrücklich:** dass der Arbeiter das CLI im Betrieb
tatsächlich aufruft, lässt sich nur im Durchlauf beweisen. Das war bei
`ctx_task` genauso.

## 11. Was dieser Entwurf NICHT tut

- **Kein Einsatz der `leanctx-sdk`.** Sie bleibt gemessene Formatvorlage. PR #8
  erreicht `ctx_task` nicht (E-2), `ContextWorkspace` ist weiterhin PREVIEW,
  SDK 1.1.0 und Engine 3.10.1 sind nicht veröffentlicht, und der Betrieb liefe
  auf einem Git-Commit. Die Lizenzfrage (E-9) entfällt bei privater Nutzung,
  trägt hier also nicht.
- **Kein Workspace als Kontextspeicher.** Er wäre der dritte neben
  `ctx_knowledge` und `ctx_handoff`, für einen Zweck, den der erste erfüllt.
- **Kein eigener Wissens-Reaper.** lean-ctx' Lebenszyklus genügt (§7).
- **Kein Fan-out.** Ein Arbeiter je (Branch, Rolle), wie bisher.
- **Kein Eingriff in lean-ctx.** `ctx_knowledge` wird über `lean-ctx call`
  benutzt, wie `bus.py` und `leanctx.py` es tun.
- **Keine Migration alter `ctx_task`-Aufträge.** Der Store ist leer, und
  `cleanup_old(72)` hat ihn ohnehin geräumt.
- **Keine Änderung an `session_error()`, `bus.py`, `worktree.py`, `join.py`,
  `export.py`.** Der Timeout-Pfad und der PID-Join bleiben, wie sie sind.
- **Keine Abarbeitung der übrigen offenen Review-Befunde.** Aus
  `lean-herdr-abschluss-review-befunde-a631ab4` übernimmt dieser Entwurf M3
  (§4), M5 (§9), M9 und I10 (§13). Draußen bleiben I2 (toter
  `permission.ask`-Hook), I3 (die Hook-Skripte lassen `patch` und `list`
  durch), I4 (das Repo liefert keine Hooks aus), I7 (fünf Ausnahmepfade in
  `handlers.py`), I8 (`handle_status_changed` ohne Entprellung), I11
  (serverweiter Bootstrap-Duplikatschutz) und M2 (toter Bus-Cluster um
  `parse_registry`, `herdr.workspace_close`). Sie liegen im Plugin-, Hook- und
  Bus-Bereich und haben keinen Bezug zum Auftragsweg. **Eine Ausnahme mit
  Bezug, als Prüfpunkt notiert:** I9 nennt `dispatch.py:167-168`
  (`read_registry`-`BusError`) als ungetestet — laut Docstring die Ursache
  eines realen `ready_timeout`-Stalls. Diese Zeilen liegen in
  `wait_for_agent_id`, das dieser Entwurf zum Bereitschaftsbeleg umwidmet (§4).
  Wer die Funktion anfasst, deckt den Pfad mit ab.

## 12. Reproduktion

SDK-Checkout und Testumgebung:

```bash
git clone --depth 1 https://github.com/Thinkery-AG/leanctx-sdk.git sdk   # 277d0c7
uv venv --python 3.12 probe
uv pip install --python probe/bin/python ./sdk
```

**Agent Tools gegen die echte Engine** (`probe_agent.py`): öffnet einen
`AgentContext` auf das Projekt, listet `capabilities`, ruft `ctx_task`,
`ctx_agent`, `ctx_session`, `ctx_handoff` und `ctx_call` — alle fünf enden in
`UnsupportedCapabilityError` — und wiederholt das mit
`AgentPermissions(write=True, execute=True)`.

**Fork und Inhalts-Pin** (`probe_fork_orch.py` / `probe_fork_worker.py`): der
Orchestrator legt Workspace, Anker und Checkpoint an und forkt; der Arbeiter
läuft als eigener Prozess, ruft `bind_source` und `attach_session`. Mit dem
Argument `mutate` ändert er die Quelldatei zwischen Bind und Anhängen.

**Mehrere Aufträge und Rückfragezyklus** (`probe_multi.py`): sechs Aufträge in
einem Workspace, ohne `ws.complete()`; danach `unresolved_questions`, Lesen
über `project_context()`, `decisions`, Weiterarbeit.

**`ctx_knowledge` aus einem CLI-Prozess:**

```bash
lean-ctx call ctx_knowledge --project-root <root> \
  --json '{"action":"remember","key":"probe","value":"…","category":"facts"}'
lean-ctx call ctx_knowledge --project-root <root> \
  --json '{"action":"recall","category":"facts","query":"…"}'
lean-ctx call ctx_knowledge --project-root <root> --json '{"action":"policy"}'
lean-ctx call ctx_knowledge --project-root <root> \
  --json '{"action":"lifecycle_report"}'
```

Die Arbeitskopien liegen im Scratchpad dieser Sitzung und sind nicht Teil des
Projekts. Der Probe-Eintrag `probe-cli-write` wurde nach der Messung mit
`{"action":"remove","key":"probe-cli-write","category":"facts"}` entfernt.

## 13. Buchhaltung

- **`docs/specs/2026-09-02-leanctx-sdk-evaluation.md`** bekommt einen Abschnitt
  „Gegenprüfung 2026-09-03": E-4 aufgelöst, E-7 geschlossen und gemessen, E-1
  für Agent Tools umgekehrt, E-2 durch Messung bestätigt, E-5 und E-6
  widerlegt. Die Entscheidung in Abschnitt 6 wird von „A gewählt" auf „durch
  diese Spec überholt" fortgeschrieben; die Befunde selbst bleiben stehen.
- **`docs/specs/2026-09-01-lean-herdr-ctx-task-design.md`** bekommt einen
  Kopfvermerk: Abschnitte 3 bis 6 sind durch diese Spec ersetzt; Abschnitt 1
  (die Befunde B-1 bis B-4) und Abschnitt 8 (Stand des Plans) bleiben gültig.
- **`README.md`** beschreibt den Auftragsweg und muss ohnehin mit. Im selben
  Zug fallen die Rückstände, die das Abschluss-Review als I10 führt: Plugin und
  Policy-Adapter kommen dort gar nicht vor; das README behauptet `uv` als
  Laufzeit, tatsächlich läuft nacktes `python3`; es fordert `herdr>=0.8.2`,
  während `herdr-plugin.toml` `0.8.0` bewirbt. Ebenso I11: `README:41` sagt
  „once per workspace", der Duplikatschutz in `handlers.py:174` ist aber
  serverweit.
- **Die `VERDIKT`-Ausnahme wird dort begründet, wo sie hingehört.** M9 stellt
  fest, dass `VERDIKT` deutsche Orthographie auf 11 Zeilen in 5 Dateien
  außerhalb `docs/` ist, begründet nur in einem Codekommentar
  (`dispatch.py:78-80`) — nicht in `AGENTS.md` und nicht in der
  Ausnahmeliste von `tests/test_language.py`. Da dieser Entwurf die
  Rollentexte und `dispatch.verdict()` anfasst, ist das der Moment: das Token
  **bleibt** (es ist ein Protokollwort, kein Prosa-Deutsch, und `VERDICT_RE`
  ist seine Autorität), aber die Ausnahme wird in `tests/test_language.py`
  namentlich eingetragen, mit einer Zeile Begründung. Sonst färbt ein `verdikt`
  in `GERMAN_WORDS` elf Zeilen rot.
