# lean-herdr — Design

**Status:** Design vollständig · **Datum:** 2026-09-01 · **Version:** 0.3.0

Das Bindeglied zwischen Herdr und lean-ctx: ein Workspace, in dem ein
Orchestrator-Agent Aufgaben an Arbeiter-Agenten verschiedener Anbieter verteilt
— Koordination über den lean-ctx-Agentenbus, Takt über Herdr — und ein
Herdr-Plugin, das den Zustand dieses Workspace sichtbar macht und über
Serverneustarts trägt.

> **Vorgänger:** `2026-08-24-lean-herdr-design.md` (v0.1.0) entwarf lean-herdr
> als reines Plugin. Messungen gegen lean-ctx 3.10.1 haben zwei seiner fünf
> Anforderungen als undurchführbar erwiesen — ein Plugin-Handler ist ein
> One-Shot-Prozess ohne Agent-Identität und kann weder in eine Session schreiben
> noch am Agentenbus teilnehmen (B1–B3). Diese Spec ersetzt ihn vollständig:
> was trug, ist hier aufgegangen; was nicht trug, ist ersetzt. Die alte Datei
> ist entfernt, ihre Fassung steht in der Git-Historie.

## Problem

Wer heute mit mehreren Agenten arbeitet, ist selbst der Orchestrator: Terminal
wechseln, Aufgabe eintippen, warten, Ergebnis kopieren, nächsten Agenten
anstoßen. Das skaliert nicht und bindet den Menschen an die Mechanik.

Die Bausteine für Automatisierung liegen bereit, kennen einander aber nicht:
Herdr verwaltet Panes und erkennt Agentenzustände, lean-ctx hält ein
projektgebundenes Gedächtnis und einen Agentenbus. Was fehlt, ist der Zuschnitt —
wer welche Aufgabe hat und über welchen Kanal.

Und was Herdr nach einem Serverneustart wiederherstellt, ist die Hülle:
Workspaces, Tabs, Panes, cwd, bei unterstützten Agenten die Sitzung selbst. Der
Agent kommt zurück, aber ohne Projektgedächtnis — Task, Findings und
Entscheidungen aus lean-ctx sind nicht Teil dessen, was Herdr speichert.

## Ziel

Ein Workspace, in dem verschiedene Modelle das tun, wofür sie taugen: ein
billiges Modell koordiniert, ein starkes schreibt Code, ein drittes reviewt —
und weil es ein anderes Modell ist, hat es andere Blindstellen. Was dort
passiert, ist in der Sidebar ablesbar und überlebt einen Serverneustart.

## Umfang

**Enthalten**

1. **Rollenschnitt** — Orchestrator, Builder, Reviewer als eigenständige
   Pane-Agenten mit je eigenem Modell.
2. **Zuteilung** — der Orchestrator startet Arbeiter, verteilt Aufgaben,
   sammelt Ergebnisse ein.
3. **Kanaltrennung** — der Bus trägt den Inhalt, Herdr den Takt.
4. **Verifikation** — Erfolg wird am Inhalt geprüft, nie am Agentenzustand.
5. **Wissensträger** — Skripte, Skills, Rollen, Profile mit klarer Zuständigkeit.
6. **Sichtbarkeit** — ein Herdr-Plugin zeigt Task und Zustand je Pane und
   Workspace in der Sidebar.
7. **Wiederaufnahme** — nach einem Serverneustart ermittelt dasselbe Plugin je
   Workspace den lean-ctx-Kontext und stellt ihn als Digest bereit.

Die Punkte 6 und 7 sind das, was von der Plugin-Spec v0.1.0 trägt. Das Plugin
**liest und zeigt**; es schreibt nichts (siehe „Prozessgebundener Zustand").

**Nicht enthalten (bewusst)**

| Ausgeschlossen | Begründung |
|---|---|
| Arbeiter reden miteinander | Jede gelesene Nachricht kostet einen Modellschritt (~20 K Kontext). N Arbeiter über Kreuz wären N² Schritte. Stern, kein Netz. |
| Zweiter Builder im ersten Wurf | YAGNI. Die Topologie erlaubt ihn, der erste Wurf braucht ihn nicht. |
| Orchestrator liest Projektdateien | Das ist die Arbeit des Arbeiters. Ein Orchestrator, der Code liest, zahlt dessen Kontext in jedem seiner Schritte. |
| Plugin schreibt nach lean-ctx | Nachweislich unmöglich (B1–B3). Geschrieben wird von Pane-Agenten. |
| Automatisches Prompten aus Plugin-Handlern | Läuft in `agent_blocked` / `agent_prompt_stalled` und stört beim Tippen. Zustellung ist eine bewusste Geste des Orchestrators. |
| Erfassung von Pane-Output | Pane-Inhalt enthält Tokens, Secrets und Prompts. Ein Kontext-Plugin ist kein Datensammler. |
| Remote-Agenten | Der Bus liegt auf der Platte, Herdr-Panes laufen lokal. Kein Tunnel. |

## Verifizierte Grundlagen

Gegen herdr 0.8.2, lean-ctx 3.10.1, opencode 1.18.25 und Claude Code 2.1.252
gemessen, nicht aus Dokumentation übernommen. Ein vollständiger Durchlauf
(Orchestrator startet Arbeiter, verteilt, sammelt ein, gibt zurück) ist gelaufen.

### Herdr: Event-Namen im Plugin-Manifest

Das Manifest verwendet **Punkt-Notation**. Die Namen aus dem Socket-Schema
(`pane_agent_detected`) sind interne Broadcast-Namen und werden als
`unknown event` verworfen.

Gültig, per `plugin link` ohne Warnung bestätigt:

```
pane.agent_detected          pane.created      workspace.created
pane.agent_status_changed    pane.closed       workspace.closed
tab.created                  pane.exited       workspace.focused
worktree.created
```

`layout.updated` **existiert nicht**, obwohl das Schema `layout_updated` kennt.

**Herdr lehnt unbekannte Events nicht ab, es warnt nur.** Ein Tippfehler bleibt
zur Laufzeit stumm. Nach jedem `plugin link` ist `plugin list` auf `warning:` zu
prüfen — das gehört in die CI.

### Herdr: Asymmetrie bei der Registrierung

`plugin link` funktioniert ohne laufenden Server, `plugin unlink` erfordert
einen. Relevant für die Reihenfolge in Setup und Teardown von Tests.

### Latenz

| Aufruf | ms |
|---|---:|
| `lean-ctx session status` | 58 |
| `lean-ctx call ctx_agent` | 57 |
| `lean-ctx sessions show` | 48 |
| `uv run` (PEP 723) | 25 |
| `python3` (System) | 18 |
| Rust-Binary | 1 |

Ein einzelner lean-ctx-Aufruf kostet mehr als der gesamte Python-Start. **Die
Sprachwahl ist für die Laufzeit der Skripte irrelevant**; die Subprozesse
dominieren. `lean-ctx call` verursacht gegenüber direkten CLI-Kommandos keinen
nennenswerten Aufschlag.

Rust wird erst richtig, sobald ein langlebiger `events.subscribe`-Abonnent
dazukommt.

### Zwei Subsysteme namens „agent"

| | Kann | Zugang |
|---|---|---|
| CLI `lean-ctx agent` | Identität: `register --id --role --owner`, `heartbeat`, `presence`, `list`, `gc` | direkt |
| MCP `ctx_agent` | Koordination: `register`, `post`, `read`, `sync`, `poll_events`, `handoff`, `diary`, `share_knowledge`, `lease_acquire`/`lease_release` | über `ctx_call` |

Trotz gleichen Namens verschiedene Systeme mit getrennten Registern. Der
Agentenbus dieser Spec ist ausschließlich das **MCP**-Subsystem; das
CLI-Identitätssystem wird nicht verwendet.

### Der Agentenbus trägt Aufgaben

`ctx_agent` ist ein vollwertiger Aufgabenbus. Satzform je Nachricht:

```
id · from_agent · to_agent · task_id · category · priority · privacy
message · metadata · project_root · timestamp · read_by[] · expires_at
```

| Feld | Bedeutung |
|---|---|
| `project_root` | pro Nachricht — projekt-scoped, kein Übersprechen zwischen Repos |
| `to_agent` | gerichtete Zustellung; leer = Broadcast |
| `task_id` | Aufgabenkorrelation, eingebaut |
| `read_by[]` | Lesebestätigung |
| `expires_at` | 12 h TTL, räumt sich selbst auf |

Gerichtete Zustellung **filtert nach Agent-ID**. Ein freundlicher Name
(`to_agent: "reviewer"`) wird stumm angenommen und nie zugestellt — eine Falle,
die erst nach Stunden auffällt.

### Prozessgebundener Zustand — die Wurzel von vier Befunden

lean-ctx bindet Sitzungszustand an eine **Prozess-Identität**, nicht an die
Shell-cwd. Was ein langlebiger MCP-Client beim Start mitbekommt, gilt; was ein
One-Shot-Prozess setzt, stirbt mit ihm.

| Betroffen | Verhalten |
|---|---|
| `lean-ctx call ctx_session {task,finding,decision}` | meldet Erfolg, persistiert nichts (`task: null` im Export) |
| `lean-ctx session <write>` aus fremder cwd | trifft die global zuletzt aktive Session — nachweislich ein fremdes Projekt |
| `lean-ctx call ctx_agent register` | ignoriert `agent_id`/`id`/`name`, leitet aus der PID ab; Registrierung endet mit dem Prozess |
| `ctx_session action=role` über `call` | schaltet nur im eigenen Prozess um |

**Folge:** ein Herdr-Plugin-Handler hat keine Agent-Identität und kann weder
schreiben noch am Bus teilnehmen. Nur Pane-Agenten können das. Der Orchestrator
gehört deshalb in einen Pane, nicht in ein Plugin.

Posts über One-Shots landen als `from_agent: "anonymous"` und markieren sich
selbst als gelesen.

### Der PID-Join löst die Adressierung

Herdr-Name und lean-ctx-Agent-ID finden über die Prozess-ID zusammen:

```
herdr agent list       → pane_id
herdr pane process-info --pane <id>  → lean-ctx-Prozess, pid=N
ctx_agent list / presence            → Eintrag mit pid=N  →  to_agent
```

Viermal bestätigt, über zwei Agentenarten:

| Pane | Agent | lean-ctx-PID | Agent-ID |
|---|---|---:|---|
| `w1:p1` | claude | 3540259 | `mcp-3540259-4ac80990…` |
| `w1:p2` | opencode | 1214891 | `mcp-1214891-efb2b993…` |
| `w1:p3` | claude | 2012982 | `mcp-2012982-09db0559…` |
| `w1:p4` | claude | 2018183 | `mcp-2018183-70c877bf…` |

Null Modellschritte, kein Wettlauf, kein Register das veralten kann — bei jedem
Aufruf frisch ableitbar.

**Regel:** über das **`pid`-Feld** verbinden, das `ctx_agent list` ausgibt und
das in `registry.json` steht — **nicht** durch Zerlegen des ID-Strings. Sonst
bricht es, sobald lean-ctx sein ID-Format ändert.

### Kosten

Die Kosteneinheit ist der **Schritt** — ein einzelner LLM-Aufruf innerhalb eines
Turns. Jeder Tool-Aufruf beendet einen Schritt; das Ergebnis wird angehängt und
das Modell erneut vollständig aufgerufen.

Gemessen an einem Turn mit drei Tool-Aufrufen (opencode, Gemini 3.7 Flash):

| Schritt | total tok | cache read | cost |
|---|---:|---:|---:|
| 1 register | 20 119 | 0 | $0.0192 |
| 2 post | 20 285 | 0 | $0.0155 |
| 3 read | 20 385 | 16 259 | $0.0045 |
| 4 Antwort | 20 576 | 16 258 | $0.0049 |
| **Σ** | **81.4 K** | 32.5 K | **$0.0440** |

Gesamtausgabe des Modells: **177 Token.** Der Rest ist Systemprompt und
Tool-Schemas.

- **Jeder Schritt kostet ~20 K Kontext**, unabhängig von der Aufgabengröße. Der
  Hebel ist die Anzahl der Schritte, nicht deren Inhalt.
- **Warm ist ein Schritt $0.0047, kalt $0.017.** Der Cache greift ab Schritt 3
  (warum, ist nicht gemessen; `cache.write` ist durchgehend 0, was zu Geminis
  implizitem Caching passt).
- **`lean-ctx tools` steht auf `power` → 78 Tools** im Kontext jedes Schritts.
  `tools health` beziffert 42 wenig genutzte Tools mit ~6 553 Token je Sitzung.

Vollständiger Durchlauf im Spike: Orchestrator (Flash) **$0.07** / 3 min 3 s /
18.6 K Kontext, Arbeiter (Sonnet 5) 74.4 K Token.

**Polling ist der Kostenkiller, nicht das LLM.** `herdr agent prompt --wait` und
`agent wait --until` blockieren im Shell-Aufruf, ohne einen Modellaufruf. Eine
Schleife über `agent list` zahlt jeden Blick mit ~20 K.

### Rollen und Profile — was wirkt, was nicht

Rollendateien liegen unter `~/.local/share/lean-ctx/roles/` oder
`<projekt>/.lean-ctx/roles/`:

```toml
[role]   name, description, shell_policy
[tools]  allowed, denied
[io]     boundary_mode, allow_secret_paths, redact_outputs, allow_cross_project_search
[limits] max_context_tokens, max_shell_invocations, max_cost_usd
```

| Bestandteil | Ergebnis |
|---|---|
| Projekt-lokale Rollendatei | ✅ wird als `(project)` erkannt |
| Rolle **pro Agent** setzbar | ✅ **`LEAN_CTX_ROLE`** |
| `[limits]`-Werte werden geladen | ✅ angezeigt |
| Zähler laufen mit | ❌ 121 Aufrufe, Anzeige `shell 0/100` |
| `max_cost_usd` zählt Geld | ❌ Tool-I/O-Schätzung, `[fallback-blended]` |
| `[tools] allowed/denied` durchgesetzt | ❌ verbotenes Tool lief durch |
| Kontext-Presets (`preferred_mode`, `max_full`, `max_sig`) | ✅ wirksam |

**Eine Rolle ist ein Kontextformer, kein Wächter.**

Tool-Profile sind ein zweiter, unabhängiger Hebel — sie ändern, was im Kontext
*beworben* wird, nicht was erlaubt ist. Eine Rolle ändert die advertised-Zahl
nicht (63 bei `coder` wie bei `reviewer`).

| Profil | Tools | Inhalt |
|---|---:|---|
| `minimal` | 5 | `ctx_read`, `ctx_shell`, `ctx_search`, `ctx_glob`, `ctx_tree` |
| `lean` | 12 | „lazy core" |
| `power` | 78 | alles |

**Es fehlt ein passendes Profil.** `minimal` enthält kein einziges
Koordinationswerkzeug — kein `ctx_agent`, `ctx_session`, `ctx_handoff`,
`ctx_call`. Ein Orchestrator damit kann nichts orchestrieren; mit `power`
schleppt er 78 Schemas durch jeden Schritt. **Für den Orchestrator muss ein
eigenes Profil in lean-ctx geschrieben werden.**

`LEAN_CTX_TOOL_PROFILE` wird als Env-Var respektiert (`=minimal` → 5 Tools).
`=lean` wird ignoriert — ein Profilname, den die CLI kennt und die Env-Var nicht.

### `ctx_agent` ist nicht direkt exponiert

Weder Claude noch opencode finden `ctx_agent` im Standardprofil. Beide müssen
über `ctx_call` gehen:

```
ctx_call(name="ctx_agent", arguments={"action":"read"})
```

opencode präfixt MCP-Tools mit dem Servernamen (`lean-ctx_ctx_call`). **Ein
Prompt darf Tool-Namen nicht hart annehmen** — sie unterscheiden sich je Agent.

### Argumentübergabe beim Start

`herdr agent start <name> --kind <kind> --pane <id> -- <agent-args…>` reicht
native Argumente durch. Bestätigt: `["claude","--model","sonnet"]`,
`["opencode","--agent","orchestrator"]`.

**Mehrzeilige Argumente werden abgelehnt** —
`agent arguments cannot be encoded safely for the target shell`. Rollen- und
Plantexte müssen als **Datei** übergeben werden:

- Claude: `--append-system-prompt-file <pfad>` (auch `--agents`, `--plugin-dir`,
  `--mcp-config`, `--settings`, `--add-dir`)
- opencode: `agent.<name>.prompt = "{file:<pfad>}"` in `opencode.jsonc`, dann
  `--agent <name>`

Das ist die bessere Form ohnehin: versionierbar und überprüfbar.

### Herdrs Zustand kodiert kein Scheitern

`herdr agent prompt --wait` meldete Erfolg (`agent_status: idle`,
`interactive_ready: true`) für einen Turn, der mit HTTP 401 gescheitert war. Ein
gescheiterter Agent ist genauso `idle` wie ein erfolgreicher.

Die Wahrheit steht im nativen Session-Export:

```json
"error": { "name": "APIError", "data": { "message": "User not found.",
           "statusCode": 401, "url": "https://openrouter.ai/api/v1/..." }}
```

Die Session-ID dafür liefert **Herdr selbst** (`agent_session.value`), über die
per Agent installierte Integration.

### Lesbarkeit von Panes

`herdr agent read` liefert den Dialog, wenn der Pane Inhalt gerendert hat — bei
Claude wie bei opencode bestätigt. Ein Pane ohne gerenderten Inhalt gibt nur die
Statuszeile her. Der Export bleibt trotzdem der verlässliche Weg, weil **nur er
das `error`-Objekt trägt**.

### Herdr-Integrationen

`herdr integration install opencode` installiert **zwei** Plugins:
`plugins/herdr-agent-state.js` (Lifecycle) und `herdr-tui-session.js`
(Session-Restore). opencode bekommt damit dieselbe Behandlung wie Claude.

`herdr agent list` liefert für Claude-Agenten Token-Telemetrie
(`context`, `limit`, `usage`) — das Messinstrument für Schrittkosten ist
eingebaut. Für opencode-Agenten fehlt sie.

`lean-ctx wrap` kennt opencode nicht (`claude|codex|cursor|windsurf|cline|grok|aider|copilot`).
Die MCP-Registrierung für opencode ist Handarbeit in `opencode.jsonc`.

## Architektur

### Drei Rollen

| Rolle | Agent | Modell | Warum |
|---|---|---|---|
| `orchestrator` | opencode | schnell/billig (Flash-Klasse) | viele kleine Entscheidungen, ~$0.005/warmer Schritt |
| `builder` | claude | stark (Sonnet-Klasse) | die eigentliche Arbeit |
| `reviewer` | opencode | OpenAI-Klasse | **anderes Modell = andere Blindstellen** — das ist der Wert, nicht die Ersparnis |

### Stern, kein Netz

Nur der Orchestrator spricht mit allen. Arbeiter reden nie miteinander.

### Kanaltrennung

**Die Aufgabe liegt auf dem Bus, der Prompt ist nur die Klingel.**

```
Orchestrator ──[1] ctx_agent post  to_agent=<id> task_id=<id>──►  Bus
             ──[2] herdr agent prompt <name> --wait ───────────►  Arbeiter
                                                                    │
                   [3] ctx_agent read  ◄─────────────────────────────┘
Arbeiter     ──[4] ctx_agent post  to_agent=<orch-id> task_id=<id>─►  Bus
Orchestrator ──[5] ctx_agent read ──► Antwort mit task_id da?
                   nein → nativer Export auf `error` prüfen
```

Der Prompt trägt einen Satz, nicht die Aufgabe: er geht durch das Terminal, ist
unstrukturiert und bläht jeden Schritt auf. Der Bus trägt den Inhalt —
strukturiert, persistent, mit `task_id`, `read_by` und TTL.

Gemessen: ein Prompt von acht Wörtern genügte, der Arbeiter holte die Aufgabe
vom Bus und lieferte ein inhaltlich korrektes Ergebnis zurück.

### Wissensträger

Die Trennlinie ist nicht Geschmack, sie folgt aus der Kostenmessung.

| Träger | Ort | Inhalt | Warum dort |
|---|---|---|---|
| **Skript** | `bin/herdr-dispatch`, `bin/herdr-collect` | deterministische Mehrschritt-Sequenzen | kollabiert N Schritte auf 1 — der Haupthebel |
| **Skill** | `orchestrating-agents` | Urteil: welcher Arbeiter, welches Modell, Eskalation. Plus die harten Regeln | muss im Kontext stehen, damit das Modell folgt |
| **Rollendatei** | `<projekt>/.lean-ctx/roles/orchestrator.toml` | Kontextform und Budgetanzeige | keine Durchsetzung, siehe oben |
| **Profil** | `LEAN_CTX_TOOL_PROFILE` in `mcp.*.environment` | Schema-Last je Schritt | senkt die 20 K |
| **Wächter** | opencode `agent.<name>.permission` | „orchestriert, codet nicht" | **hier** greift Durchsetzung, nicht in der lean-ctx-Rolle |
| **Kostendeckel** | opencode `agent.<name>.steps` | begrenzt die gemessene Kosteneinheit | `max_cost_usd` zählt kein Geld |
| **Spec** | dieses Dokument | die Befunde, aus denen die Regeln folgen | damit niemand die Regeln später „vereinfacht" |

Ein Skill, der dem Modell die Mechanik erklärt („splitte, starte, poste, warte,
prüfe"), erzeugt fünf Schritte ≈ $0.10 je Aufgabe. Dasselbe als ein Skriptaufruf
ist ein Schritt ≈ $0.005.

### Ablage

Rollentexte sind versionierte Projektdateien, kein flüchtiger Zustand. Sie
gehören ins Repo, weil sie das Verhalten der Agenten festlegen und
nachvollziehbar bleiben müssen:

```
roles/
  orchestrator.md     → opencode  agent.orchestrator.prompt = "{file:…}"
  builder.md          → claude    --append-system-prompt-file
  reviewer.md         → opencode  agent.reviewer.prompt = "{file:…}"
.lean-ctx/roles/
  orchestrator.toml   → lean-ctx-Rolle (Kontextform, via LEAN_CTX_ROLE)
bin/
  herdr-dispatch      → eine Zuteilung, ein Aufruf
  herdr-collect       → Ergebnisse eines task_id einsammeln
```

### Skriptverträge

Beide Skripte sind reine Mechanik — sie fragen kein Modell und treffen keine
Zuordnungsentscheidung.

```
herdr-dispatch <rolle> --kind <kind> --model <m> --role-file <pfad>
               --task-id <id> --task <text> [--timeout-ms N]
```

Legt einen Pane an, startet den Agenten mit Rollendatei, löst dessen
lean-ctx-ID über den PID-Join auf, legt die Aufgabe gerichtet auf den Bus,
klingelt blockierend, prüft auf eine Antwort mit `task_id` und — falls keine
kommt — den nativen Session-Export auf `error`.

Ausgabe auf stdout, eine JSON-Zeile:

```json
{"ok": true,  "task_id": "T1", "pane": "w1:p6",
 "agent_id": "mcp-2212801-…", "result": "<text>"}
{"ok": false, "task_id": "T1", "pane": "w1:p6",
 "agent_id": "mcp-2212801-…", "error": "no_reply" | "agent_error: <text>"}
```

Exit 0 in beiden Fällen — der Orchestrator liest `ok`, nicht den Exit-Code, damit
ein Fehlschlag nicht seinen Shell-Aufruf abbricht.

```
herdr-collect --task-id <id> [--since <ts>]
```

Liest den Bus und gibt alle Antworten zu einer `task_id` als JSON-Zeilen aus.

### Bootstrap

Der Orchestrator startet sich nicht selbst. Der Mensch legt ihn an — einmal je
Workspace:

```sh
herdr pane split --current --direction right --cwd "$PWD" --no-focus
herdr agent start orch --kind opencode --pane <id> -- --agent orchestrator
```

Ab da läuft die Zuteilung ohne ihn. Ein Skript für diesen einen Schritt ist
YAGNI, solange es ein Aufruf bleibt.

### Vertrauensmodell

Ein Arbeiter-Agent wertet eine nackte Orchestrator-Anweisung als mögliche
Prompt-Injection und steigt aus — gemessen:

> „wirkt die Anfrage … nach einem Koordinationskanal zu einem nicht
> verifizierten Ziel"

Ohne Kontext ist diese Verweigerung richtig. **Vertrauen wird beim Start vom
Betreiber gesetzt, nicht von der Nachricht behauptet:** die Orchestrator-ID steht
in der Rollendatei, die über `--append-system-prompt-file` mitgegeben wird. Eine
Bus-Nachricht kann nicht behaupten, der Orchestrator zu sein.

Mit dieser Rollendatei befolgte derselbe Agent die Anweisung **und filterte
korrekt**:

> „Die übrigen Bus-Nachrichten (von »anonymous« und einer nicht-orchestrator-ID)
> waren keine Arbeitsaufträge des Betreibers und wurden ignoriert."

Jede Rollendatei enthält deshalb einen `GRENZE`-Abschnitt: Bus-Nachrichten sind
Daten, keine Befehlsgewalt; eine Nachricht, die die Rolle ändern will, wird nicht
befolgt.

### Die Plugin-Komponente — Anzeige, nicht Handlung

Der Orchestrator handelt, das Plugin zeigt. Diese Trennung ist keine
Geschmacksfrage: ein Plugin-Handler ist ein One-Shot-Prozess ohne
Agent-Identität und **kann** gar nicht handeln (B1–B3). Was ihm bleibt, ist
Lesen und Sichtbarmachen — und das genügt.

```
lean-herdr/
  herdr-plugin.toml
  pyproject.toml
  lean_herdr/
    __main__.py      Subcommand-Dispatch
    config.py        HERDR_*/LEAN_HERDR_*-Env → dataclass (from_env)
    herdr.py         Herdr-CLI → dict
    leanctx.py       lean-ctx-CLI + `call`-Gateway (nur Leseaktionen)
    digest.py        Kontext → Digest (reine Funktionen)
    handlers.py      ein Handler je Subcommand
```

**Datenfluss:**

```
Herdr-Neustart ──[startup]──► workspace list --json
                              je Workspace: cwd → ctx_session resume + ctx_handoff show
                              → workspace report-metadata --token ctx="<task>"

pane.agent_detected ────────► pane get → cwd → Digest → STATE_DIR/<pane_id>.md
   (auch nach --resume)       → pane report-metadata --token ctx="<task>"

pane.agent_status_changed ──► Token auffrischen

prefix+l → action inject ───► STATE_DIR/<pane_id>.md → herdr agent prompt
```

**Der Digest wird nicht von Hand gebaut.** `ctx_session action=resume` liefert
ihn fertig (Projekt, Findings, Archive, Statistik); `ctx_handoff show` ergänzt
die kuratierten Datei-Referenzen. Gibt es weder Task noch Findings noch Ledger,
wird kein Digest geschrieben und kein Token gesetzt.

**Der Token heißt `ctx`, nicht `task`.** `herdr-plugin-renamer` belegt `$task`
bereits mit seinem generierten Pane-Namen; zwei Plugins um denselben Token wären
ein stiller Konflikt.

**Zustandslosigkeit.** Jeder Handler ist ein One-Shot-Prozess — Herdrs eigenes
Modell für Hooks. Persistenter Zustand existiert nur im Digest unter
`HERDR_PLUGIN_STATE_DIR` und in lean-ctx selbst. Das Plugin führt kein eigenes
Register; die Zuordnung Pane → Agent läuft über den PID-Join.

**Sprachwahl:** Python mit `uv`, weil die Latenzmessung sagt, dass sie
irrelevant ist — ein einzelner lean-ctx-Aufruf kostet mehr als der gesamte
Python-Start. `uv run --script` mit PEP-723-Kopf scheidet aus: es isoliert jedes
Skript, die Handler könnten keine gemeinsame Bibliothek importieren. `uv` ist
damit eine **Laufzeit**-Abhängigkeit und gehört ins README, denn Herdr
installiert keine Toolchains.

**Null externe Dependencies.** `json`, `subprocess`, `os`, `pathlib` decken
alles ab. Das `lean-ctx-sdk` wird nicht verwendet: sein CLI-Teil ist selbst ein
`subprocess`-Wrapper ohne `call`, und sein HTTP-Teil bräuchte einen laufenden
`lean-ctx serve`.

## Lebensdauer eines Arbeiters

**Arbeiter bleiben am Leben. `/clear` zwischen Phasen, `/compact` zwischen Tasks
innerhalb einer Phase.**

Der Reflex wäre, je Aufgabe einen frischen Pane-Arbeiter zu starten, weil der
Kontext sonst wächst. Gemessen ist das der schlechteste der vier Wege:

| | Kontextwachstum | Anlauf je Aufgabe | Identität | in der Sidebar |
|---|---|---|---|---|
| dauerhaft, ohne Reset | **ja** | keiner | stabil | ✅ |
| flüchtiger Pane je Aufgabe | nein | ~30 s + kalter Cache | **wechselt** | ✅ |
| native Subagenten | nein | keiner | — | ❌ |
| **`/clear` zwischen Aufgaben** | **nein** | **keiner** | **stabil** | ✅ |

`/clear` gewinnt auf allen vier Achsen. Der Vorteil bei der Identität ist der
unterschätzte: die Adressierung muss **einmal** aufgelöst werden statt je
Aufgabe, weil PID und lean-ctx-ID den Clear überleben.

Belegt in einem Durchlauf mit `--model sonnet`:

| | Kontext |
|---|---:|
| nach Aufgabe 1 | 55.2 K |
| `/clear` | (Übergang) |
| nach Aufgabe 2 | **51.8 K** |

Die Rollendatei bleibt nach dem Clear wirksam: derselbe Arbeiter las
eigenständig den Bus, filterte fremde Nachrichten und meldete mit `task_id`
zurück. `--append-system-prompt-file` überlebt `/clear`.

**`/clear` macht einen Arbeiter nicht billig, es deckelt ihn.** Der Reset führt
auf die **Grundlast** zurück, nicht auf null — bei Claude in diesem Projekt
~44 K (`CLAUDE.md`, Skills, MCP-Tool-Schemas), beim opencode-Orchestrator ~20 K.
Erspart werden die ~30 K angesammelter Aufgabenkontext. Das Wachstum ist damit
begrenzt statt unbegrenzt; die Grundlast zahlt jede Aufgabe.

Die halbe Grundlast ist ein zweiter Grund, den Orchestrator in opencode laufen
zu lassen — nicht nur das billigere Modell.

Beide Agenten kennen den Befehl:

| | Reset | Zwischenstufe |
|---|---|---|
| Claude Code | `/clear` | Auto-Kompaktierung |
| opencode | `/new` (**Alias `/clear`**, `ctrl+x n`) | `/compact` (Alias `/summarize`) |

opencode kann denselben Effekt auch je Befehl erzielen: `subtask: true` an einem
Command erzwingt eine Subagenten-Ausführung, *„so it does not pollute your
primary context"* — ein Konfigurationseintrag statt eines Umbaus.

### Drei Fallstricke beim Reset

1. **Die Session-ID wechselt** (`2cd57baf…` → `1b7c63c4…`). Der Export-Pfad ist
   die einzige Quelle für `error` — er muss die ID nach jedem Clear **neu holen,
   nie cachen**.
2. **Steuerbefehle ohne `--wait` senden.** `/clear` löst keinen
   Lifecycle-Wechsel aus; `agent prompt --wait` scheitert mit exit 1.
3. **Die Token-Anzeige ist eine Drittanbieter-Quelle.** Sie stammt vom Plugin
   `herdr-agent-metrics`, nicht von Herdr, und aktualisiert auf Herdr-Events —
   die ein `/clear` nicht auslöst. Erzwingbar mit
   `herdr plugin action invoke herdr-agent-metrics.refresh`. Wer „ist dieser
   Arbeiter noch leichtgewichtig?" prüft, vergleicht gegen die **Grundlast**,
   nicht gegen 0.

Das Polling-Verbot bleibt trotzdem in **jeder** Rollendatei: zwischen dem Posten
des Ergebnisses und dem `/clear` liegt ein Turn, in dem Claudes Auto-Modus sich
eine Folgeaufgabe schreiben kann (beobachtet: `❯ Bus erneut prüfen, ob neue
Aufgaben eingegangen sind`). Der Clear beendet die Schleife, aber nicht
rückwirkend.

## Fehlerbehandlung

**Regel: Erfolg wird am Inhalt geprüft, nie am Zustand.**

| Fall | Verhalten |
|---|---|
| Arbeiter meldet nichts zurück | Keine Antwort mit `task_id` auf dem Bus → nativer Export lesen, auf `error` prüfen |
| Arbeiter scheitert am Provider | Export trägt das `error`-Objekt; `agent_status` bleibt `idle` |
| Orchestrator hängt | `--timeout` an jedem `prompt`/`wait`; ohne Timeout wartet Herdr unbegrenzt |
| Pane ohne gerenderten Inhalt | `agent read` liefert nur die Statuszeile → Export nutzen |

### Plugin-Handler: brechen nie etwas

Für die Anzeige-Komponente gilt eine eigene, strengere Regel: **ein Handler
bricht nie etwas.**

| Fall | Verhalten |
|---|---|
| lean-ctx fehlt oder antwortet nicht | exit 0, kein Token, Notiz auf stderr |
| Kein Session-State für die cwd | still, kein Token — Normalfall bei frischen Projekten |
| lean-ctx hängt | `subprocess` mit 5 s Timeout |
| Unerwartete Exception | oberster `try/except` → stderr, exit 0 |
| Kein Digest bei `inject` | `herdr notification show` |

Der Unterschied in der letzten Zeile ist Absicht: **Automatik scheitert still,
eine bewusste Geste scheitert sichtbar.** stderr landet in
`herdr plugin log list --plugin lean.herdr`. Dass `notification show` still sein
kann (H5), ist hier vertretbar — es ist eine Bequemlichkeit, kein
Eskalationskanal.

### Fehlschlag einer Zuteilung

`herdr-dispatch` unterscheidet zwei Fälle:

| `error` | Bedeutung | Reaktion |
|---|---|---|
| `agent_error: <text>` | Export trägt ein `error`-Objekt — Provider, Auth, Limit | **kein** Retry. Ein 401 wird beim zweiten Mal auch ein 401. |
| `no_reply` | kein `error`, aber keine Antwort mit `task_id` | **ein** Retry, nach vorherigem `/clear` |

Genau ein Wiederholungsversuch. Ein zweiter Fehlschlag ist ein Signal, kein
Rauschen — dann eskaliert der Orchestrator.

### Review-Ablehnung

Der Reviewer antwortet maschinenlesbar über `category` auf dem Bus: `result`
oder `reject`. Kein Prosa-Parsing.

```
builder → reviewer → reject → builder (Runde 2) → reviewer → reject → ESKALATION
```

**Zwei Runden, dann Mensch.** Ein Reviewer, der zweimal dasselbe ablehnt, hat
entweder recht (und der Builder kommt nicht weiter) oder unrecht (und niemand
merkt es). Beides braucht ein Urteil, das der Orchestrator nicht hat.

### Eskalation — drei Kanäle, weil einer nachweislich still ist

Gemessen: `herdr notification show` liefert `{"reason":"disabled","shown":false}`.
Der naheliegendste Kanal erreicht den Menschen nicht — immerhin sagt die CLI es
ehrlich, statt still zu schlucken.

| Kanal | Zuverlässigkeit | Rolle |
|---|---|---|
| **Orchestrator hält an** | immer | **primär** — nichts geht weiter, das ist unübersehbar |
| `pane report-metadata --token` | immer (lautlos bestätigt) | Sidebar zeigt, *welcher* Workspace jemanden braucht |
| `notification show` | **nur wenn aktiviert** | Extra; `shown` prüfen, nie darauf verlassen |

Der Orchestrator schreibt bei Eskalation in sein Terminal und macht dann nichts
mehr:

```
ESKALATION <task_id>: <grund>
  Arbeiter: <name> (<pane>, <agent_id>)
  Letzter Zustand: <no_reply | agent_error | reject×2>
  Ich warte auf eine Entscheidung.
```

Ein angehaltener Orchestrator ist das stärkste Signal, das dieser Aufbau kennt:
es kann nicht übersehen werden, weil nichts mehr passiert.

### Gesamtabbruch

| Grenze | Mechanismus |
|---|---|
| Schritte des Orchestrators | opencode `agent.orchestrator.steps` — deckelt die gemessene Kosteneinheit |
| Wanduhr je Zuteilung | `--timeout-ms` an jedem `dispatch` |
| Notbremse | Pane schließen — Arbeiter sterben mit ihren Panes |

Was es **nicht** gibt: einen Geldbetrag als Grenze. `max_cost_usd` zählt eine
Tool-I/O-Schätzung (B5), und die Token-Telemetrie kommt von einem
Drittanbieter-Plugin und nur für Claude-Agenten (H3). **Ein echter Kostendeckel
existiert in diesem Aufbau nicht** — das gehört ehrlich in die Spec, statt als
gelöst dargestellt zu werden.

## Tests

1. **Logik ohne I/O** — PID-Join-Auflösung, Bus-Nachrichten-Parsing,
   Export-Fehlererkennung, Digest-Rendering, Event-JSON-Parsing. Reine
   Funktionen, keine Doppel. Der Großteil.
2. **Skripte und Handler gegen Doppel** — `herdr-dispatch` und jeder
   Plugin-Handler gegen aufzeichnende Fakes für `herdr` und `lean-ctx`, mit
   gefälschten `HERDR_*`-Variablen und `HERDR_PLUGIN_EVENT_JSON`.
   Pflichtfälle: Arbeiter antwortet nicht → Skript meldet Fehler statt Erfolg;
   `FakeLeanCtx(available=False)` → **jeder** Handler exit 0 ohne Aufruf.
3. **Manifest-Lint** — `plugin link` gefolgt von `plugin list`, Abbruch bei
   `warning:`. Fängt Event-Tippfehler, die Herdr sonst verschweigt. Gehört in
   die CI, weil kein anderer Mechanismus sie sichtbar macht.
4. **Ein-Aufgaben-Durchlauf** — manuell, wie im Spike: Orchestrator startet
   Arbeiter, verteilt, sammelt ein. Nicht in CI, weil er Modellkosten
   verursacht.

`config.py` und die Testdoppel werden aus
`lean-ctx/integrations/hermes-lean-ctx/` adaptiert (Apache-2.0, gleiches Repo):
die Env-Parsing-Helfer und `from_env()`, sowie `FakeGateway` als aufzeichnendes
Testdoppel. Aus `transport.py` wird die *Form* übernommen — eine Klasse kapselt
allen Außenverkehr, `is_available()` cacht — nicht der Inhalt.

Nicht getestet: Herdr selbst, lean-ctx selbst, die Modelle, `claude --resume`.

## Offene Punkte

1. **Orchestrator-Profil** — muss in lean-ctx geschrieben werden; heute gibt es
   keins mit Koordinationswerkzeugen (B8).
2. **Parallele Arbeiter** — der PID-Join ist nur seriell erprobt. Zwei
   gleichzeitig gestartete Arbeiter sind ungetestet, ebenso `/clear` an einem
   Arbeiter, während ein anderer arbeitet.
3. **Kostendeckel** — `agent.<name>.steps` in opencode ist der einzige
   Kandidat, aber nicht gemessen. Bis dahin gibt es keine Geldgrenze.
4. **Greift die Endebedingung?** Das Polling-Verbot in der Rollendatei ist
   formuliert, aber nicht dagegen gemessen — der beobachtete Fall trat vor
   ihrer Einführung auf.
5. **`/compact` zwischen Tasks** — als Zwischenstufe vorgesehen, nur `/clear`
   ist gemessen.
6. **Laufzeit-Abhängigkeiten im README** — `uv` und `lean-ctx allow herdr`.
   Ohne den `allow`-Eintrag kann ein Agent unter lean-ctx-Gating Herdr nicht
   steuern; Herdr wiederum installiert keine Toolchains.
7. ~~**`$task`-Token-Kollision**~~ — entschieden: lean-herdr nimmt `$ctx`,
   `herdr-plugin-renamer` behält `$task`.
8. ~~**lean-ctx Projekt-Root**~~ — erledigt: `lean-herdr` steht in
   `allow_paths`, die `ctx_*`-Tools erreichen das Projekt.
9. ~~**Probe-Plugins**~~ — erledigt 2026-09-01: `probe.dot`, `probe.underscore`
   und `probe.all` per `plugin unlink` entfernt, `plugin list` warnungsfrei.

## Befund für lean-ctx

Nicht Teil dieses Projekts, aber blockierend oder irreführend:

| # | Befund |
|---|---|
| B1 | `lean-ctx call ctx_session {task,finding,decision}` meldet Erfolg und persistiert nichts |
| B2 | `lean-ctx session <write>` ohne Agent-Identität trifft die global zuletzt aktive Session — fremdes Projekt |
| B3 | `ctx_agent register` ignoriert `agent_id`/`id`/`name` |
| B4 | `[tools] allowed/denied` in Rollen wird nicht durchgesetzt |
| B5 | `max_cost_usd` deckelt eine Tool-I/O-Schätzung, keine Modellkosten; Zähler laufen nicht mit |
| B6 | `LEAN_CTX_TOOL_PROFILE=lean` wird ignoriert, `=minimal` greift |
| B7 | `to_agent` mit unbekanntem Namen wird stumm angenommen und nie zugestellt |
| B8 | Kein Profil mit Koordinationswerkzeugen (`ctx_agent`, `ctx_session`, `ctx_handoff`, `ctx_call`) |

## Befund für Herdr

| # | Befund |
|---|---|
| H1 | `agent_status` kodiert kein Scheitern — ein Agent mit HTTP 401 ist `idle` wie ein erfolgreicher |
| H2 | `agent start -- <args>` lehnt mehrzeilige Argumente ab (`cannot be encoded safely`) |
| H3 | Herdr selbst liefert **keine** Token-Telemetrie. Die Werte `context`/`limit`/`usage` in `agent list` sind gewöhnliche Metadaten-Tokens, gesetzt vom Drittanbieter-Plugin `herdr-agent-metrics` — nur für Claude, nicht für opencode, und aktualisiert auf Herdr-Events (die ein `/clear` nicht auslöst) |
| H4 | `herdr agent prompt --wait` scheitert mit exit 1 bei Befehlen, die keinen Lifecycle-Wechsel auslösen (`/clear`). Ohne `--wait` senden |
| H5 | `notification show` liefert `{"reason":"disabled","shown":false}`, wenn Benachrichtigungen aus sind — ehrlich, aber als alleiniger Eskalationskanal untauglich |
| H6 | Unbekannte Manifest-Events werden nur **gewarnt**, nicht abgelehnt — ein Tippfehler bleibt zur Laufzeit stumm (daher der Manifest-Lint in der CI) |
| H7 | `plugin link` funktioniert ohne laufenden Server, `plugin unlink` nicht |

## Anhang: Befund zu den lean-ctx-READMEs

Nicht Teil dieses Projekts. Die beiden READMEs nennen unterschiedliche Pakete
für gleichnamige Klassen mit verschiedenen Signaturen:

| Quelle | Installation | Import | Signatur |
|---|---|---|---|
| `packages/python-lean-ctx/README.md` | `lean-ctx-sdk` | `lean_ctx` | `LeanCtxClient(binary, project_root)` |
| `integrations/hermes-lean-ctx/README.md` | `lean-ctx-client` | `leanctx` | `LeanCtxClient(base_url, bearer_token, …)` |

Wer der hermes-README folgt, installiert womöglich das falsche Paket.
