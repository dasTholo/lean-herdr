# lean-herdr — Design

**Status:** ⚠️ **teilweise überholt** (2026-09-01) · **Datum:** 2026-08-24 · **Version:** 0.1.0

> ## Überholt — bitte zuerst lesen
>
> Messungen gegen lean-ctx **3.10.1** haben zwei der fünf Anforderungen dieser
> Spec als **undurchführbar** erwiesen. Belege und Ersatz:
> [`2026-09-01-multi-agent-workspace-design.md`](2026-09-01-multi-agent-workspace-design.md).
>
> **Die Wurzel:** lean-ctx bindet Sitzungs- und Agentenzustand an eine
> **Prozess-Identität**, nicht an die cwd. Ein Plugin-Handler ist ein
> One-Shot-Prozess ohne Agent-Identität — er kann **weder in eine Session
> schreiben noch am Agentenbus teilnehmen**. Beides betrifft die Architektur
> dieser Spec im Kern, nicht ihre Details.
>
> | Anforderung | Status |
> |---|---|
> | 1 · Restore (Digest je Workspace) | ✅ trägt — Lesen über `lean-ctx call --project-root` ist verifiziert |
> | 2 · Sichtbarkeit (Task-Token in der Sidebar) | ⚠️ trägt, aber `$task` ist bereits von `herdr-plugin-renamer` belegt → eigenen Namen wählen (`$ctx`) |
> | 3 · Rückschreiben (`session finding`) | ❌ **unmöglich** — `call` meldet Erfolg und persistiert nichts (B1); die CLI trifft ohne Agent-Identität eine fremde Session (B2) |
> | 4 · Agent-Präsenz (`ctx_agent` je Pane) | ❌ **unmöglich** — `register` ignoriert übergebene IDs, die Registrierung endet mit dem Prozess (B3) |
> | 5 · Gateway (`lean-ctx call`) | ✅ trägt |
>
> **Weitere überholte Stellen in diesem Dokument:**
> - *„`ctx_session` antwortet über `call` mit `tool_calls not available`"* — in
>   3.10.1 behoben. Lesen funktioniert; nur Schreiben ist der No-Op.
> - *„cwd als Join-Key"* — die cwd ist kein Schlüssel. Der belastbare Join läuft
>   über die **PID**: `herdr pane process-info` → lean-ctx-Prozess-PID →
>   `ctx_agent list`-Eintrag mit derselben `pid`.
> - *„MCP `ctx_agent`: `post`, `read`, `claim`, `brief`, `lease`"* — `claim`,
>   `brief` und `lease` existieren nicht. Real: `register, list, post, read,
>   status, info, handoff, sync, poll_events, diary, recall_diary, diaries,
>   share_knowledge, receive_knowledge, lease_acquire, lease_release`.
> - Der Digest muss nicht von Hand gebaut werden — `ctx_session action=resume`
>   liefert ihn bereits fertig.
>
> **Was weiterhin gilt und nirgends sonst steht:** die verifizierten
> Herdr-Event-Namen, die Registrierungs-Asymmetrie von `plugin link`/`unlink`,
> die Latenzmessungen und die Manifest-Lint-Regel. Deshalb bleibt dieses
> Dokument erhalten, statt gelöscht zu werden.

Ein Herdr-Plugin, das lean-ctx-Kontext über Herdr-Serverneustarts hinweg trägt,
den aktiven Task in der Herdr-Sidebar sichtbar macht und Agenten-Ereignisse
zurück ins lean-ctx-Gedächtnis schreibt.

## Problem

Herdr stellt nach einem Serverneustart die Hülle wieder her — Workspaces, Tabs,
Panes, cwd, und bei unterstützten Agenten die Sitzung selbst über
`claude --resume <id>`. Der Agent kommt zurück, aber ohne Projektgedächtnis:
Task, Findings und Entscheidungen aus lean-ctx sind nicht Teil dessen, was Herdr
speichert.

Umgekehrt weiß lean-ctx nichts von Herdr. `ctx_agent` koordiniert Agenten über
einen Nachrichtenbus, hat aber kein `spawn` — es sieht nur, was sich registriert.
Agenten, die in Herdr-Panes laufen, sind für lean-ctx unsichtbar.

Die beiden Systeme persistieren verschiedene Ebenen und kennen einander nicht.
Dieses Plugin ist das Bindeglied.

## Umfang

**Enthalten**

1. **Restore** — nach Serverneustart oder Handoff wird pro Workspace der
   lean-ctx-Kontext ermittelt und als Digest bereitgestellt.
2. **Sichtbarkeit** — der aktive Task erscheint als Token in der Herdr-Sidebar,
   pro Pane und pro Workspace.
3. **Rückschreiben** — abgeschlossene Agentenarbeit erzeugt ein
   `lean-ctx session finding`.
4. **Agent-Präsenz** — in Panes erkannte Agenten werden bei lean-ctx registriert
   und beim Beenden abgemeldet.
5. **Gateway** — ein Modul, das über `lean-ctx call` alle MCP-Tools erreicht,
   insbesondere `ctx_handoff` und `ctx_agent`.

**Nicht enthalten (bewusst)**

| Ausgeschlossen | Begründung |
|---|---|
| Automatisches Prompten des Agenten | Läuft in `agent_blocked` / `agent_prompt_stalled` und stört beim Tippen. Zustellung ist eine bewusste Geste. |
| `blocked` als Finding | Transienter UI-Zustand, kein Erkenntnisgewinn. Würde das Gedächtnis mit Rauschen füllen. |
| Erfassung von Pane-Output | Pane-Inhalt enthält Tokens, Secrets und Prompts. Ein Kontext-Plugin ist kein Datensammler. |
| Dispatch-Orchestrierung | Agenten aus lean-ctx heraus starten und einsammeln. Präsenz ist die Voraussetzung dafür, nicht die Sache selbst. |
| Remote-Bridging | Plugins laufen immer dort, wo der Herdr-Server läuft. lean-ctx gehört auf dieselbe Maschine (R1). Kein Tunnel, kein Cloud-Sync. |

## Verifizierte Grundlagen

Gegen Herdr 0.8.2 und lean-ctx 3.9.19 gemessen, nicht aus Dokumentation
übernommen.

### Event-Namen

Das Plugin-Manifest verwendet **Punkt-Notation**. Die Namen im Socket-Schema
(`pane_agent_detected`) sind interne Broadcast-Namen und werden im Manifest
als `unknown event` gewarnt.

Gültig, per `plugin link` ohne Warnung bestätigt:

```
pane.agent_detected          pane.created      workspace.created
pane.agent_status_changed    pane.closed       workspace.closed
tab.created                  pane.exited       workspace.focused
worktree.created
```

`layout.updated` **existiert nicht**, obwohl das Schema `layout_updated` kennt.

**Herdr lehnt unbekannte Events nicht ab, es warnt nur.** Ein Tippfehler bleibt
zur Laufzeit stumm. Nach jedem `plugin link` ist `plugin list` auf `warning:`
zu prüfen — das gehört in die CI.

### Asymmetrie bei der Registrierung

`plugin link` funktioniert ohne laufenden Server, `plugin unlink` erfordert
einen. Relevant für Setup- und Teardown-Reihenfolge in Tests.

### Latenz

| Aufruf | ms |
|---|---|
| `lean-ctx session status` | 58 |
| `lean-ctx call ctx_agent` | 57 |
| `lean-ctx sessions show` | 48 |
| `uv run` (PEP 723) | 25 |
| `python3` (System) | 18 |
| Rust-Binary | 1 |

Ein einzelner lean-ctx-Aufruf kostet mehr als der gesamte Python-Start. Die
Sprachwahl ist für die Laufzeit dieses Plugins irrelevant; die Subprozesse
dominieren. `lean-ctx call` verursacht gegenüber direkten CLI-Kommandos keinen
nennenswerten Aufschlag.

### Zwei Subsysteme namens „agent"

| | Kann | Zugang |
|---|---|---|
| CLI `lean-ctx agent` | Identität: `register --id --role --owner`, `heartbeat`, `list`, `gc` | direkt |
| MCP `ctx_agent` | Koordination: `post`, `read`, `claim`, `brief`, `diary`, `lease` | nur `lean-ctx call` |

Trotz gleichen Namens verschiedene Systeme. Präsenz nutzt das CLI, Koordination
das Gateway.

## Technische Entscheidungen

### Python mit uv

`command = ["uv", "run", "python", "-m", "lean_herdr", "<subcommand>"]`

Herdr setzt die cwd auf das Plugin-Verzeichnis, dort liegt `pyproject.toml`.
`uv run --script` mit PEP-723-Kopf scheidet aus: es isoliert jedes Skript, die
Handler könnten keine gemeinsame Bibliothek importieren.

Rust wurde erwogen und verworfen — die beiden Argumente dafür (Startlatenz,
Socket-Zugriff) halten der Messung nicht stand. Rust wird richtig, sobald ein
langlebiger `events.subscribe`-Abonnent dazukommt.

uv ist eine **Laufzeit**-Abhängigkeit (Rust hätte eine Build-Abhängigkeit).
Herdr installiert keine Toolchains; das gehört ins README.

### Null externe Dependencies

`json`, `subprocess`, `os`, `pathlib` decken alles ab. Das
`lean-ctx-sdk` wird **nicht** verwendet: sein CLI-Teil (`LeanCtxClient`) ist
selbst ein `subprocess`-Wrapper und deckt `read`/`search`/`shell`/`gain`/
`benchmark` ab — nicht `call`, also nicht die Tools, die wir brauchen. Sein
HTTP-Teil lohnt sich für langlebige Agentenloops mit Verbindungs- und
Health-Cache; unsere Handler leben ~50 ms und benötigte zusätzlich einen
laufenden `lean-ctx serve`.

### `lean-ctx call` als Gateway

```
lean-ctx call <tool> --project-root <path> --json '<json>'
```

Erreicht alle MCP-Tools. `ctx_handoff` ist darüber verifiziert erreichbar.
Keine HTTP-API, kein SDK, kein UDS-Protokoll.

Bekannte Grenze: `ctx_session` antwortet über `call` mit
`error: -32603: tool_calls not available`. Für Sessions wird deshalb das direkte
CLI verwendet.

### cwd als Join-Key

Herdr-Panes und -Workspaces haben eine cwd, lean-ctx-Sessions sind
projektgebunden. Kein Mapping, keine ID-Tabelle, nichts das veralten kann.

### Zustandslosigkeit

Jeder Handler ist ein One-Shot-Prozess — Herdrs eigenes Modell für Hooks
(„one-shot initialization commands rather than supervised daemons"). Persistenter
Zustand existiert nur im Digest unter `HERDR_PLUGIN_STATE_DIR` und in lean-ctx
selbst. Das Plugin führt kein eigenes Register.

## Architektur

```
lean-herdr/
  herdr-plugin.toml
  pyproject.toml
  lean_herdr/
    __main__.py      Subcommand-Dispatch
    config.py        HERDR_*/LEAN_HERDR_*-Env → dataclass (from_env)
    herdr.py         Herdr-CLI → dict
    leanctx.py       lean-ctx-CLI + `call`-Gateway
    digest.py        Kontext → Digest (reine Funktionen)
    handlers.py      ein Handler je Subcommand
  tests/
  docs/specs/
```

`config.py` und `tests/_helpers.py` werden aus
`lean-ctx/integrations/hermes-lean-ctx/` adaptiert (Apache-2.0, gleiches Repo):
die Env-Parsing-Helfer und `from_env()`, sowie `FakeGateway` als aufzeichnendes
Testdoppel. Aus `transport.py` wird die *Form* übernommen — eine Klasse kapselt
allen Außenverkehr, `is_available()` cacht — nicht der Inhalt.

## Datenfluss

```
Herdr-Neustart / Handoff
  └─ [[startup]] ──────────► workspace list --json
                             je Workspace: cwd → ctx_handoff show + sessions show
                             → workspace report-metadata --token ctx="<task>"

pane.agent_detected ────────► pane get → cwd → Digest → STATE_DIR/<pane_id>.md
   (auch nach --resume)       → pane report-metadata --token ctx="<task>"
                              → lean-ctx agent register --id <pane_id> --role dev

pane.agent_status_changed ──► nur bei done: lean-ctx session finding
                              Token auffrischen

pane.exited ────────────────► lean-ctx agent decommission <pane_id>
workspace.closed ───────────► lean-ctx call ctx_handoff {"action":"create"}

prefix+l → action inject ───► STATE_DIR/<pane_id>.md → herdr agent prompt
prefix+s → action save ─────► lean-ctx session save + snapshot create
```

### Digest-Format

Plain Markdown, deterministisch, gekappt auf 2000 Zeichen:

```markdown
# lean-ctx — <workspace label>
**Task:** <session task, sonst "—">

## Findings (max. 5, neueste zuerst)
- <finding>

## Decisions (max. 3)
- <decision>

## Handoff
<n> kuratierte Datei-Referenzen · Ledger <id>
```

Leere Abschnitte entfallen ganz. Gibt es weder Task noch Findings noch Ledger,
wird **kein** Digest geschrieben und kein Token gesetzt.

Der Digest speist sich aus Handoff-Ledger **und** Session-State. Das
Handoff-Ledger enthält kuratierte Datei-Referenzen mit Hashes und ist genau für
Agentenübergaben gebaut; das Muster stammt aus `hermes-lean-ctx`
(`on_session_end` → `ctx_handoff`, `on_session_start` → `resume`).

## Fehlerbehandlung

**Regel: ein Handler bricht nie etwas.** Übernommen aus `hermes-lean-ctx`:
*„falls der Daemon nicht erreichbar ist … damit der Agentenloop nie bricht."*

| Fall | Verhalten |
|---|---|
| lean-ctx fehlt oder antwortet nicht | exit 0, kein Token, Notiz auf stderr |
| Kein Session-State für die cwd | still, kein Token — Normalfall bei frischen Projekten |
| lean-ctx hängt | `subprocess` mit 5 s Timeout |
| Unerwartete Exception | oberster `try/except` → stderr, exit 0 |
| Kein Digest bei `inject` | `herdr notification show` |

Der Unterschied in der letzten Zeile ist Absicht: **Automatik scheitert still,
eine bewusste Geste scheitert sichtbar.** stderr landet in
`herdr plugin log list --plugin lean.herdr`.

## Tests

**1. Logik ohne I/O** — Digest-Rendering, Event-JSON-Parsing, cwd-Auflösung.
Reine Funktionen, keine Doppel. Der Großteil.

**2. Handler gegen Doppel** — `FakeLeanCtx` / `FakeHerdr` (adaptiert aus
`tests/_helpers.py`) zeichnen auf, welche Aufrufe ergingen. Jeder Handler wird
mit gefälschten `HERDR_*`-Variablen und `HERDR_PLUGIN_EVENT_JSON` aufgerufen.
Pflichtfall: `FakeLeanCtx(available=False)` führt in **jedem** Handler zu exit 0
ohne Aufruf.

**3. Manifest-Lint** — `plugin link` gefolgt von `plugin list`, Abbruch bei
`warning:`. Fängt Event-Tippfehler, die Herdr sonst verschweigt.

**4. Smoke-Test gegen echtes Herdr** — manuell, nicht in CI. Server starten,
Plugin linken, Agent starten, `plugin log list` prüfen.

Nicht getestet: Herdr selbst, lean-ctx selbst, `claude --resume`.

## Offene Punkte

1. ~~**lean-ctx Projekt-Root**~~ — erledigt 2026-08-24: `lean-herdr` ist in
   `allow_paths` eingetragen, die ctx_*-Tools erreichen das Projekt.
2. **`lean-ctx allow herdr`** — ohne diesen Eintrag kann ein Agent unter
   lean-ctx-Gating Herdr nicht steuern. Gehört ins README. Ebenso `uv`.
3. ~~**Probe-Plugins**~~ — erledigt 2026-09-01: `probe.dot`, `probe.underscore`
   und `probe.all` sind per `plugin unlink` entfernt, `plugin list` ist
   warnungsfrei.
4. ~~**`--owner` für `lean-ctx agent register`**~~ — hinfällig: Anforderung 4
   (Agent-Präsenz je Pane) ist nicht durchführbar, siehe Kopf des Dokuments.

## Anhang: Befund für lean-ctx

Nicht Teil dieses Projekts. Die beiden READMEs nennen unterschiedliche Pakete
für gleichnamige Klassen mit verschiedenen Signaturen:

| Quelle | Installation | Import | Signatur |
|---|---|---|---|
| `packages/python-lean-ctx/README.md` | `lean-ctx-sdk` | `lean_ctx` | `LeanCtxClient(binary, project_root)` |
| `integrations/hermes-lean-ctx/README.md` | `lean-ctx-client` | `leanctx` | `LeanCtxClient(base_url, bearer_token, …)` |

Wer der hermes-README folgt, installiert womöglich das falsche Paket.
