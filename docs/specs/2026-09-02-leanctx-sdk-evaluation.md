# leanctx-sdk 1.0.0 — Bewertung für den Auftragsweg von lean-herdr

**Status:** gemessen; Entscheidung vom 2026-09-02 (**Option A**, bei `ctx_task`
bleiben) — **überholt durch die Gegenprüfung vom 2026-09-03**, siehe
`2026-09-03-lean-herdr-auftragslog-design.md`. Dort ist gemessen: E-4 ist durch
PR #10 aufgelöst, E-7 geschlossen und nachgewiesen, E-1 für die neuen Agent
Tools umgekehrt (exakter Laufzeit-Pin auf 3.10.1), E-2 bestätigt — und **E-5
und E-6 sind widerlegt**: beide hingen an der Art der Benutzung, nicht an der
SDK. Die Befunde unten bleiben als Messung des Standes vom 2026-09-02 gültig;
die Optionen in Abschnitt 6 sind es nicht mehr.
**Nachtrag 2026-09-13:** SDK 1.1.0 ist veröffentlicht, ihr Python-Code aber
identisch mit dem Stand `277d0c7` der Gegenprüfung. E-2 ist am PyPI-Paket
bestätigt, E-1 präzisiert — der Pin vergleicht nur die Versionszeichenkette —,
siehe `2026-09-13-lean-herdr-katalog-review-und-sdk-1-1-design.md`, Abschnitt 6.
**Bezug:** `2026-09-01-lean-herdr-ctx-task-design.md` (Auftragsweg auf `ctx_task`)
**Anlass:** Thinkery AG hat die `leanctx-sdk` in Version 1.0.0 veröffentlicht
(<https://github.com/Thinkery-AG/leanctx-sdk>). Frage des Betreibers: hilft sie
uns beim Auftragsweg?

Dieses Dokument hält fest, **was gemessen wurde**. Abschnitt 6 nennt die Optionen,
die aus den Befunden folgen; der Betreiber hat sich für **A** entschieden. Die
Befunde selbst bleiben unverändert stehen — sie sind der Grund, aus dem B und C
später wieder aufgerufen werden könnten, ohne noch einmal gemessen werden zu
müssen.

> **Zur Schreibweise:** Dieses Dokument benutzt korrekte deutsche Umlaute. Die
> älteren Specs im selben Verzeichnis benutzen die Ersatzschreibung `ae/oe/ue`.
> Die Abweichung ist beabsichtigt und folgt einer ausdrücklichen Vorgabe.

## 1. Aufbau der Messung

| | |
|---|---|
| SDK | `thinkery-leanctx-sdk==1.0.0`, installiert mit `uv venv --python 3.12` + `uv pip install` |
| Engine | die real installierte `lean-ctx 3.10.1` unter `/home/tholo/.cargo/bin/lean-ctx` |
| Python | CPython 3.12.14 |
| Datum | 2026-09-02 |

Der „Arbeiter" lief in allen Durchläufen als **eigener Prozess** (`subprocess.run`),
nie als Funktionsaufruf im selben Interpreter — sonst wäre die entscheidende Frage
(sieht der Orchestrator den Endzustand?) nicht beantwortet.

Die Reproduktionsskripte stehen in Abschnitt 7.

## 2. Was die SDK ist

`PUBLIC-SURFACE-MANIFEST.md` ist eine Allowlist: *„Anything not listed is Internal."*

- **Stable v1** — fünf Primitive: `ContextSession`, `ContextSource`, `ContextView`,
  `ContextPlan`, `ContextReceipt`. Lebenszyklus *Select → Shape → Reuse → Recover*.
- **Preview** (`leanctx_sdk.preview`) — `ContextWorkspace`, `ContextCheckpoint`,
  `ContextDelta`, `ContextHandoff` samt Fork-Linie, Konfliktbericht und
  Handoff-Zulassung. *„May change in minor releases"*, nicht von der v1-Zusage
  gedeckt.

Kein `agent`, kein `task`, kein Bus, kein Zugriff auf `tasks.json`. Die neun Module
unter `src/leanctx_sdk/` — plus die Unterpakete `integrations/` und `preview/` —
bestätigen das. Der `POST-V1-RESEARCH-FREEZE` schließt
Nachschub aus: *„SDK v1 closes exploratory roadmap expansion."*

Die SDK bekräftigt damit dieselbe Position, die den Befund B-3 der `ctx_task`-Spec
erzeugt hat: *„LeanCTX is a Context SDK, not an agent coordination product."*

## 3. Befunde

### E-1 — Der Versions-Pin greift zur Laufzeit nicht (Korrektur)

`COMPATIBILITY.md` nennt Engine `v3.10.0`, Commit `5b69202…`, mit Binary-SHA-256,
und schreibt: *„Compatibility is never inferred from a version string, shared
checkout, or newer commit."* Daraus lässt sich **nicht** auf einen Laufzeit-Gate
schließen. Gemessen mit unserer 3.10.1:

```
engine:            {'engine_id': 'lean-ctx-local', 'engine_version': '3.10.1'}
policy_admission:  {'policy_ref': 'policy:engine-transport-v1:admitted',
                    'decision': 'admitted'}
status:            'succeeded'
```

Geprüft werden Protokoll (`interface 1.0.0`, `schema 1`, `transport 1`) und die
Major-Version (`engine.py`: `if int(engine_version.split(".", 1)[0]) != 3`). Die
Angaben in `COMPATIBILITY.md` sind eine Release-CI-Aussage, kein Laufzeitzwang.

**Der Versions-Pin ist kein Hinderungsgrund.**

### E-2 — `SubprocessEngineClient` ersetzt `leanctx.py` nicht

Docstring in `engine.py`: *„Strict subprocess client for the two public Engine
Interface v1 operations."* Gebunden an
`capability://leanctx/context-optimization`, Version `1.0.0`. Es gibt keinen
generischen `lean-ctx call <tool>`-Weg.

`LeanCtx.call(tool, arguments)` aus `lean_herdr/leanctx.py:100` braucht genau das —
der Auftragsweg der Spec läuft über `ctx_call(name="ctx_task", …)`. Die SDK kann
diesen Aufruf nicht tragen. `leanctx.py` bleibt erforderlich.

### E-3 — Der Workspace trägt einen Auftragskanal, und er funktioniert

Das ist der substanzielle Fund. Ein `ContextWorkspace` ist ein dauerhafter,
dateibasierter Zustandsspeicher, den ein zweiter Prozess öffnen kann.

Gemessen, Erfolgsfall — Arbeiter als eigener Prozess, Orchestrator liest mit:

```
[worker] geoeffnet, lifecycle=active            ← ContextWorkspace.open()
[worker] attach_session ok | session_id=herdr-sess-0001
[worker] session.complete -> state=completed outcome=completed
[worker] commit_context mit Sitzungs-Provenienz ok
[worker] workspace-receipt event_kind=workspace_completed seq=6

Orchestrator pollt die Ereignisdateien (ohne SDK, nur Dateisystem):
  seq=4 kind=session_attached
  seq=5 kind=context_committed
  seq=6 kind=workspace_completed
Status (frischer Handle): lifecycle=completed | events=6 | sessions=1 | entries=1
project_context: [('facts', 'Arbeiter: Feature X gebaut, 3 Dateien geaendert')]
```

Fehlerfall, gleicher Aufbau:

```
[worker] session.abort -> state=aborted
[worker] workspace-receipt event_kind=workspace_aborted seq=6
Terminal-Ereignis: {"kind": "workspace_aborted",
                    "payload": {"reason_code": "internal"}, "sequence": 6}
Status: lifecycle=aborted
project_context: [('unresolved_questions', 'Welche Branch-Strategie …?')]
```

**Ablage:**

```
<state_root>/workspaces/<uuid>/events/<16-stellige Sequenz>-<sha256>.json
```

Jede Datei ein Ereignis, `schema_version: "leanctx.workspace-event/v1"`,
hash-verkettet über `previous_digest`. Reines JSON — **pollbar ohne die SDK**, was
`dispatch.py --await` genau bräuchte, und strukturell sauberer als `tasks.json`
(geordnet, append-only, manipulationssicher verkettet).

Die Ereignisarten (`_EVENT_KINDS`):

```
checkpoint_created · context_committed · handoff_applied · package_pinned ·
policy_tightened · session_attached · source_attached · source_updated ·
workspace_aborted · workspace_completed · workspace_created · workspace_forked ·
workspace_restored · workspace_sealed · workspace_seeded
```

### E-4 — Fork plus `attach_session` scheitert

Das trifft genau die Form, wegen der der Workspace interessant wäre: ein Fork je
Arbeiter.

`bind_source` legt die Prozessbindung nur im Arbeitsspeicher ab:

```python
# workspace.py:3863
def bind_source(self, source_id: str, source: ContextSource) -> SourceAnchor:
    """Bind a portable inherited anchor to this process after exact recheck."""
    anchor = self._require_source(source_id)
    bound = _bind_portable_anchor(anchor, source)
    self._runtime_source_bindings[source_id] = bound   # :3867 — nur im Prozess
    return bound
```

`attach_session` liest aber die **dauerhafte** Projektion und verlangt eine
Übereinstimmung, die dort nie steht:

```python
# workspace.py:4029
for source_id in source_ids:
    anchors.append(state.sources[source_id])           # :4031 — von Platte
…
matching_anchors = [a for a in anchors
                    if a.engine_binding is not None
                    and _plain(a.engine_binding) == _plain(plan.source.to_dict())]
if len(matching_anchors) != 1:
    raise WorkspaceConflictError()                     # :4045
```

Ein geforkter Workspace erbt den Anker **ohne** `engine_binding` (bewusst — der
Pfad ist prozesslokal, `_bind_portable_anchor` heißt wörtlich *„without adding its
path to portable durable state"*). `bind_source` stellt die Bindung wieder her,
aber an einer Stelle, die `attach_session` nicht liest.

**Gemessen:**

| Ziel | Ergebnis |
|---|---|
| Eltern-Workspace (Anker im selben Prozess mit `attach_source` gesetzt) | `attach_session ok` |
| Fork (`ws.fork("builder", from_checkpoint=…)`) | `WorkspaceConflictError: workspace_conflict` |

Der andere Zugang ist ebenso versperrt: ruft der Arbeiter im Fork `start_session`
auf, ohne vorher `bind_source` aufzurufen, meldet die SDK
`WorkspaceValidationError: portable source must be explicitly rebound in this
process` (`workspace.py:3960`). Beide Wege in den Fork sind damit zu.

Ob Fehler oder undokumentierte Grenze ist von außen nicht zu entscheiden. Für uns
ist die Folge dieselbe: der Fan-out-Weg steht nicht zur Verfügung.

### E-5 — Ein Workspace trägt genau einen Auftrag

`_LIFECYCLES` kennt drei Werte: `active`, `completed`, `aborted`. Nach `complete()`
oder `abort()` ist der Workspace terminal. Gemessen:

```
Auftrag 1 abgeschlossen, lifecycle: completed
Auftrag 2 abgelehnt: WorkspaceLifecycleError: workspace_lifecycle
```

Je Auftrag also ein neuer Workspace. Bei einem Arbeiter je (Branch, Rolle), der
mehrere Aufträge nacheinander bekommt, heißt das: Workspace-Verwaltung wird zur
eigenen Aufgabe.

### E-6 — Kein `input-required`

Gemessene Zustandsräume:

```
SessionState:  created · planned · executing · completed · aborted · closed
HostOutcome:   unknown · accepted · rejected · completed · failed · aborted
_LIFECYCLES:   active · completed · aborted
```

Der Rückfragekanal aus Abschnitt 5 der `ctx_task`-Spec hat kein Gegenstück.

**Aber:** die Kategorien für Kontexteinträge (`_CATEGORIES`) lauten

```
constraints · decisions · facts · source_refs · unresolved_questions
```

Gemessen legt der Arbeiter seine Rückfrage als `unresolved_questions` ab, und der
Orchestrator liest sie aus `project_context()`. Ein Rückfragekanal ist damit
**baubar** — als Inhalt neben dem Zustand `aborted`, nicht als eigener Zustand.

### E-7 — Anmeldezeremonie und feste Reihenfolge

Bis eine Sitzung angeheftet war, waren sechs Validierungsfehler zu überwinden. Ein
zulässiger `SourceAnchor` verlangt:

- `kind ∈ {api, archive, custom, filesystem, git}` (`_KINDS`)
- `revision.kind == scope.kind == recovery.kind == kind` (`workspace.py:520`)
- `canonical_id == "file://" + source.relative_path` (`workspace.py:1822`)
- `revision.value == "sha256:" + <SHA-256 des Dateiinhalts>` (`workspace.py:1835`)
- `engine_binding == source.to_dict()`, sonst `attach_session` scheitert
- `trust.evidence_refs` als Liste, nicht als Zeichenkette

Die Aufrufreihenfolge liegt fest:

```
prepare  →  attach_session  →  session.complete  →  commit_context(session=…)  →  ws.complete()
```

`commit_context(session=…)` verlangt `session.state == "completed"`
(`workspace.py:4126`) — die Sitzungsprovenienz lässt sich also erst *nach* dem
Abschluss anhängen, nicht währenddessen.

Die Quelle ist **inhaltsgepinnt**: `_bind_portable_anchor` liest die Datei und
vergleicht ihren SHA-256 mit `anchor.revision.value`; bei Abweichung
`WorkspaceConflictError` (`workspace.py:1828–1836`).

Gemessen wurde davon nur der harmlose Fall: **im selben Prozess** stört eine
Änderung der Datei nicht, weil die Bindung schon steht — `attach_session` lief nach
dem Überschreiben der Datei durch. Der Fall, der wehtäte — Neubindung aus einem
anderen Prozess **nach** einer Änderung — ist **nicht nachgemessen**; er folgt aus
dem zitierten Code, nicht aus einem Durchlauf. Für einen Builder-Agenten, dessen
Auftrag das Ändern von Dateien ist, bleibt das eine strukturelle Reibung, deren
genaue Schwelle offen ist.

### E-8 — Kein Adapter für unsere Arbeiter

Der einzige mitgelieferte Framework-Adapter ist
`leanctx_sdk.integrations.openai_agents`, gepinnt auf `openai-agents==0.8.4`,
CPython 3.11, macOS arm64. `INTEGRATION-MODES.md`: *„No other framework or Agents
version is claimed."*

Unsere Arbeiter sind Claude-Code-Agenten mit MCP-Werkzeugen. Die SDK ist kein
MCP-Server. Ein Arbeiter kann ein Workspace-Ereignis also nur schreiben, wenn wir
ihm ein **eigenes CLI** geben (`bin/herdr-report …`), das er per Bash aufruft.

Das ist der Grund, aus dem die `ctx_task`-Spec ihren Weg gewählt hat: `ctx_call`
hat der Arbeiter bereits.

### E-9 — Lizenz

`LICENSING.md`: Die SDK ist **source-available** unter der *LeanCTX SDK Source
License 1.0*, ohne Change Date und ohne automatische Umwandlung. Erlaubt sind
Entwicklung, CI, Test, Staging, Evaluation, Proofs of Concept, Benchmarking und
begrenzte Sicherheitsforschung. **Commercial Production Use** verlangt einen
schriftlichen Vertrag mit Thinkery AG; dasselbe gilt für OEM-Einbettung und
kommerzielle Weiterverbreitung.

Die Engine bleibt Apache-2.0. Der Weg der bestehenden Spec — `ctx_call` gegen die
Engine — ist damit lizenzrechtlich der unbelastete.

Die hier dokumentierte Messung fällt unter „Evaluation" und ist gedeckt.

## 4. Bewertung gegen die fünf Rücklagen der `ctx_task`-Spec

| Rücklage (Spec Abschnitt 5) | Workspace-Entsprechung | Bewertung |
|---|---|---|
| `completed` | `workspace_completed`, `lifecycle=completed` | gemessen, trägt |
| `failed` | `workspace_aborted` + `reason_code` | gemessen, trägt |
| `canceled` | dasselbe `workspace_aborted` | nicht unterscheidbar |
| `input-required` | kein Zustand; `unresolved_questions` als Inhalt | nur nachbaubar |
| Timeout | skriptseitig, unverändert | unberührt |

## 5. Was diese Bewertung nicht geprüft hat

- **`ContextHandoff` / `ContextDelta` im Betrieb.** Der Fan-out über `fork` ist an
  E-4 gescheitert, bevor ein Handoff sinnvoll messbar war. Das Beispiel
  `examples/preview_workspace.py` läuft (`admission.decision == "admitted"`), aber
  im Einzelprozess und ohne angeheftete Sitzung.
- **Nebenläufigkeit.** `WorkspaceLockError` existiert und die SDK-eigene Testreihe
  enthält einen Wettlauf über zwei Prozesse; nachgemessen wurde das nicht.
- **`.ctxpkg`-Pfad** (`seal_checkpoint_package`, `seed_workspace_from_package`,
  `migrate_snapshot_v1`). Laut `COMPATIBILITY.md` verlangt **dieser** Pfad die
  exakte Engine-Freigabe — anders als der Workspace-Kern, siehe E-1.
- **Der Inhalts-Pin unter Änderung.** Neubindung aus einem Fremdprozess, nachdem
  der Arbeiter die Quelldatei geändert hat — siehe E-7. Aus dem Code abgeleitet,
  nicht durchlaufen.
- **Ob E-4 ein Fehler ist.** Kein Issue eröffnet, keine Rückfrage an Thinkery AG.

## 6. Optionen

> **Überholt am 2026-09-03.** Gewählt ist seither **C**; die Gegenprüfung
> in Abschnitt 8 hat zwei der Gründe für A (E-5, E-6) widerlegt und einen
> (E-4) aufgelöst. Die drei Optionen bleiben als Dokumentation des Standes
> vom 2026-09-02 stehen.

**A — Bei `ctx_task` bleiben. ‹gewählt am 2026-09-02, überholt am 2026-09-03›** Die bestehende Spec führt
in Abschnitt 7 nun „Kein Einsatz der `leanctx-sdk`" mit Verweis auf dieses
Dokument. Tragende Gründe: E-2, E-4, E-5, E-6, E-8, E-9. Ausdrücklich **nicht**
tragend: E-1 — der Versions-Pin war ein Fehlschluss, kein Hindernis. Der
Implementierungsplan läuft ab Task 8 unverändert weiter.

**B — Workspace als Auftragsweg.** Setzt voraus, dass E-4 sich auflösen lässt
(Fehlerbericht an Thinkery AG oder Verzicht auf `fork` zugunsten eines eigenen
Workspace je Arbeiter). Bringt ein dokumentiertes, verkettetes Ereignisformat mit,
kostet die Preview-Instabilität, die Lizenzfrage für den Betrieb, ein neues
Arbeiter-CLI und den nachgebauten Rückfragekanal.

**C — Eigenes Ereignis-Log, ohne SDK. ‹gewählt am 2026-09-03›** Sobald ein Arbeiter-CLI ohnehin nötig ist
(E-8), kann es genauso gut ein eigenes Format schreiben — mit unseren sechs
Zuständen inklusive `input-required`. Die in E-3 gemessene Ablage ist dafür die
Vorlage: 16-stellige Sequenz im Dateinamen, `previous_digest`-Kette, ein JSON je
Ereignis, append-only. Das ist `json` plus `os.replace` aus der Standardbibliothek.
Der Gewinn wäre, dass der Schreibpfad **unit-testbar** wird — die Lücke, die
Abschnitt 6 der `ctx_task`-Spec ausdrücklich einräumt. Der Preis ist ein Umbau des
Umbaus mitten im Lauf.

## 7. Reproduktion

Umgebung:

```bash
uv venv --python 3.12 sdkprobe
uv pip install --python sdkprobe/bin/python thinkery-leanctx-sdk==1.0.0
```

**Orchestrator** (`probe_orchestrator.py`) — legt den Workspace an, startet den
Arbeiter als eigenen Prozess, pollt danach die Ereignisdateien ohne die SDK:

```python
import hashlib, json, pathlib, subprocess, sys, time
from leanctx_sdk import ContextSource
from leanctx_sdk.preview import (ContextWorkspace, SourceAnchor, SourceFreshness,
                                 SourceRecovery, SourceRevision, SourceScope,
                                 SourceTrust)

ROOT, PROJ = pathlib.Path("state"), pathlib.Path("proj")
PROJ.mkdir(parents=True, exist_ok=True); ROOT.mkdir(parents=True, exist_ok=True)
(PROJ / "README.md").write_text("# Probe\n\nZeile zwei.\n", encoding="utf-8")

src = ContextSource("README.md", project_root=str(PROJ))
digest = "sha256:" + hashlib.sha256((PROJ / "README.md").read_bytes()).hexdigest()

ws = ContextWorkspace.create(str(ROOT), "orchestrator")
ws.attach_source(SourceAnchor(
    source_id="src-1", kind="filesystem", canonical_id="file://README.md",
    scope=SourceScope("filesystem", "file://README.md"),
    revision=SourceRevision("filesystem", digest),
    freshness=SourceFreshness("2026-09-02T00:00:00Z", "current"),
    trust=SourceTrust("local", ()),
    recovery=SourceRecovery("filesystem", "file://README.md", digest),
    engine_binding=src.to_dict(),          # ohne dies scheitert attach_session
))

# E-4: mit ws.fork(...) statt ws scheitert der Arbeiter an WorkspaceConflictError
target = ws
events = ROOT / "workspaces" / target.workspace_id / "events"
seen = {p.name for p in events.glob("*.json")}

proc = subprocess.run([sys.executable, "probe_worker.py", str(ROOT),
                       target.workspace_id, str(PROJ), "t-1",
                       sys.argv[1] if len(sys.argv) > 1 else "ok"],
                      capture_output=True, text=True, timeout=120)
print(proc.stdout.strip() or proc.stderr.strip()[-2000:])

deadline = time.time() + 5
while time.time() < deadline:
    for f in sorted(events.glob("*.json")):
        if f.name in seen:
            continue
        seen.add(f.name)
        rec = json.loads(f.read_text())
        print(f"  seq={rec['sequence']} kind={rec['kind']} payload={rec['payload']}")
    time.sleep(0.2)

st = ContextWorkspace.open(str(ROOT), target.workspace_id).status()
print("lifecycle:", st.lifecycle, "| events:", st.event_count)
```

**Arbeiter** (`probe_worker.py`) — eigener Prozess:

```python
import shutil as sh, sys
from leanctx_sdk import ContextSession, ContextSource, SubprocessEngineClient
from leanctx_sdk.preview import ContextWorkspace, ProjectContextEntry

state_root, ws_id, proj, task_id, outcome = sys.argv[1:6]
ws = ContextWorkspace.open(state_root, ws_id)
src = ContextSource("README.md", project_root=proj)

sess = ContextSession("baue Feature X", project_root=proj, task_id=task_id,
                      session_id="s-1",
                      engine=SubprocessEngineClient(sh.which("lean-ctx")))
sess.prepare(src)                                   # E-1: 3.10.1 wird angenommen
ws.attach_session(sess, source_ids=["src-1"])

if outcome == "ok":
    sess.complete({"dateien": 3}, outcome="completed")
    ws.commit_context([ProjectContextEntry(
        "11111111-1111-4111-8111-111111111111", "facts",
        "Arbeiter: Feature X gebaut")], session=sess)   # verlangt state==completed
    wrec = ws.complete()
else:
    ws.commit_context([ProjectContextEntry(
        "22222222-2222-4222-8222-222222222222", "unresolved_questions",
        "Welche Branch-Strategie?")])                   # E-6: Rueckfrage als Inhalt
    sess.abort(RuntimeError("Testfehler"))
    wrec = ws.abort("internal")

print(f"[worker] {wrec.event_kind} seq={wrec.sequence} "
      f"lifecycle={ws.status().lifecycle}")
```

Die Arbeitskopien der Messung liegen im Scratchpad dieser Sitzung
(`probe1_surface.py` … `probe5_mutation.py`) und sind nicht Teil des Projekts.

## 8. Gegenprüfung 2026-09-03

Gemessen gegen `lean-ctx 3.10.1` und den SDK-Checkout `277d0c7`, nach PR #8
und PR #10. Die Befunde aus Abschnitt 3 bleiben als Messung des Standes vom
2026-09-02 stehen; hier steht, was die Nachmessung an ihnen geändert hat.

| Befund | Stand 2026-09-03 |
|---|---|
| **E-1** (Versions-Pin) | für die neuen Agent Tools **umgekehrt**: `agent.py:436` verlangt die Engine **exakt** `3.10.1`, während der Workspace-Kern nur die Major-Version prüft |
| **E-2** (SDK ersetzt `leanctx.py` nicht) | **bestätigt**: `AgentContext` erreicht nur ein `frozenset` aus zehn Werkzeugen (`agent.py:41-45`); `ctx_task`, `ctx_agent`, `ctx_session`, `ctx_handoff` und `ctx_call` enden in `UnsupportedCapabilityError` |
| **E-4** (Fork + `attach_session`) | **aufgelöst** durch PR #10: `[worker] attach_session OK`, `workspace_completed seq=5` |
| **E-5** („ein Workspace trägt einen Auftrag") | **widerlegt**: `complete()` ist optional; gemessen tragen sechs Aufträge und vier Sitzungen einen durchgehend `active` Workspace |
| **E-6** („kein `input-required`") | **widerlegt**: der Rückfragezyklus läuft ohne `abort` — `unresolved_questions` → Lesen → `decisions` → weiterarbeiten |
| **E-7** (Inhalts-Pin) | **geschlossen und gemessen**: ändert der Arbeiter die gebundene Quelldatei vor dem Anhängen, scheitert es mit `WorkspaceConflictError` |

E-5 und E-6 hingen nicht an der SDK, sondern an der Art ihrer Benutzung.
Daraus folgt nicht, dass die SDK die Antwort ist, sondern dass die
**Architektur** die Antwort ist, die diese Bewertung an der SDK gemessen
hat: ein dateibasiertes, append-only, hash-verkettetes Ereignis-Log — also
Option C. Die Reproduktion steht in Abschnitt 12 der Nachfolgespec.
