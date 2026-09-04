# lean-herdr: Der erste opencode-Start in einem Projekt — Design v1.0

**Stand:** 2026-09-04 · **Status:** entworfen, nicht implementiert
**Anlass:** `lean-herdr workspace up` baut in etwa der Hälfte der Läufe keinen
arbeitsfähigen Orchestrator auf. Nach `ready_timeout_s` (45 s) antwortet es
`{"ok": false, "error": "no_agent_id"}`; in der Pane steht ein laufender
opencode-Prozess, der nichts malt.
**Betrifft:** `lean_herdr/herdr.py`, `lean_herdr/workspace.py`,
`lean_herdr/dispatch.py`, `lean_herdr/initcmd.py`

## 1. Die Ursache

opencodes **erster Bootstrap in einem Projekt, das ein Projekt-Plugin trägt,
hängt.** Der Prozess bleibt unmittelbar nach dem Laden der Projekt-Config
stehen: alle Bun-Threads in `futex_do_wait`, der Hauptthread in `epoll_wait`,
ein einziger offener Socket — eine leerlaufende Keep-Alive-Verbindung zur
npm-Registry — und keine Kindprozesse. Er malt den Alt-Screen (7581 Bytes) und
danach nichts mehr, auch nach 300 s nicht.

`lean-herdr workspace init` schreibt genau so ein Plugin:
`.opencode/plugins/lean-ctx-policy.js`.

Die Schritte, die im gesunden Fall 0,5 s später folgen, kommen im Hängerfall
nie — der opencode-Log endet mitten in der Bootstrap-Sequenz:

```
10:25:07.534  loading path=<root>/.opencode/opencode.jsonc     <- letzte Zeile
              (gesund folgt hier: "all LSPs are disabled" -> init
               -> "watcher backend" -> "project copy refresh")
```

### 1.1 Ablation, je drei Läufe in frischen git-Repos

| Variante | Hänger | Zeit bis Oberfläche |
|---|---|---|
| `workspace init` vollständig | 3/3 | — |
| **ohne `.opencode/`** | **0/3** | **3,4 s** |
| ohne `mcp`-Block in `opencode.jsonc` | 3/3 | — |
| nur `$schema` in `opencode.jsonc` | 3/3 | — |
| ganz ohne `opencode.jsonc` (Plugin bleibt) | 2/3 | — |
| Plugin nach `.opencode/plugin/` (Singular) | 3/3 | — |
| Plugin + eigenes `package.json` | 3/3 | — |
| leeres Plugin ohne jeden Import | 2/3 | — |

Verschränktes A/B gegen die Kontrolle: **mit `init` 2/3 Hänger** (der dritte
11,8 s), **ohne `init` 0/3 und konstant 3,4 s.**

Es ist also weder der Inhalt des Plugins noch sein Ort noch die
`opencode.jsonc` — es ist die **bloße Existenz eines Projekt-Plugins** beim
allerersten Bootstrap eines Projekts.

### 1.2 Der Ausweg

Ein Bootstrap, der weit genug kommt und dann **abgebrochen** wird, wärmt das
Projekt. Der nächste Start läuft dann in 3,4 s.

| Aufwärmschritt | dauert | wärmt? |
|---|---|---|
| `opencode debug startup` | 0,5 s | nein |
| `opencode debug scrap` | 0,5 s | nein |
| `opencode debug agent <name> --pure` | 1,4 s | **nein** (3/3) |
| `opencode debug config --pure` | 1,0 s | **nein** (3/3) |
| `opencode --pure` interaktiv in einer PTY | 3,4 s | ja (2/2) |
| **`opencode debug agent <name>`, nach 5 s abgebrochen** | 5 s | **ja (3/3)** |
| **dieselbe, nach 8 s abgebrochen** | 8 s | **ja (3/3)** |
| interaktiver Start mit Plugin, nach 5–20 s abgebrochen | 5–20 s | **ja (6/6)** |

Zwei Folgerungen, beide gegen die Intuition:

1. **`--pure` wärmt kopflos nicht.** Der Schalter überspringt externe Plugins —
   also genau den Schritt, der gewärmt werden muss.
2. **Der abgebrochene erste Start ist selbst das Aufwärmen.** Nicht ein
   sauberes Beenden wärmt, sondern dass der Bootstrap mit Plugin weit genug
   gekommen ist. Ein zweiter Anlauf braucht deshalb keinen Sonderweg.

## 2. Was ausgeschlossen ist

Jeweils gemessen, nicht vermutet:

- **Nicht die Terminal-Fähigkeitsabfragen.** In einer nackten PTY, die
  *keine* Abfrage beantwortet, malt opencode die volle Oberfläche und meldet
  „1 MCP". Der Alt-Screen steht nach 0,7 s, der lean-ctx-Kindprozess nach
  3,1 s, der Registry-Eintrag nach 4,1 s.
- **Nicht `interactive_ready`.** Das Feld steht auch bei einem erfolgreich
  gestarteten, `idle` gemeldeten Agenten auf `None`. Es ist keine Fehlermarke.
- **Nicht „kein lean-ctx-Kindprozess".** Bun hängt Kindprozesse unter
  `/proc/<pid>/task/<tid>/children`; wer nur `task/<pid>/children` liest, sieht
  keine.
- **Nicht das Zed-Plugin, nicht `--focus`, nicht `--env`, nicht die
  Rollenauflösung.** Bereits vom Betreiber gemessen, hier nicht widerlegt.
- **Nicht das Netz.** Zur npm-Registry: Verbindung, TLS und erstes Byte in
  50 ms, über IPv4 wie über IPv6, 5/5.
- **Nicht der Abbruch des `agent start`-Clients.** Wird der Client mitten im
  Start hart gekillt, kommt der Agent trotzdem hoch, wird benannt, erreicht
  `idle` und registriert seinen MCP-Server. Gemessen.

## 3. Zwei Defekte in lean-herdr, die der Hänger freigelegt hat

**3.1 Das Budget von `agent start` ist zu klein.** `Herdr.run` gibt jedem
Aufruf `DEFAULT_TIMEOUT_S = 10.0`. Herdrs `agent start` kehrt aber laut eigener
Doku „erst zurück, wenn Herdr den erwarteten Agenten erkannt hat und ihn für
eingabebereit hält — Startvorgang standardmäßig 30 Sekunden". Jeder Start über
10 s wird also von uns gekillt, mitten in Herdrs legitimer Wartezeit.

**3.2 Der Kill wird als Ablehnung gemeldet.** `_run` liefert für den Timeout
`NO_PROCESS_RC = -999`; `agent_start` kehrt bei `code <= 0` sofort mit `{}`
zurück, und seit `51dac35` melden `start_orchestrator` und `dispatch` darauf
`agent_start_failed` und **überspringen den Waiter** — während in der Pane ein
funktionierender Agent hochkommt, den niemand mehr beobachtet. Ein langsamer,
aber erfolgreicher Start wird so zu einer gemeldeten Störung plus einem
verwaisten Orchestrator.

## 4. Entscheidung

1. **`init` wärmt das Projekt einmal, kopflos.** Die Erstlast fällt dort an, wo
   sie sichtbar und harmlos ist, nicht im heißen Pfad.
2. **`up` und `dispatch` bekommen einen zweiten Anlauf** über einen
   *gemeinsamen* Helfer. Er ist das Netz für Projekte, die vor diesem Fix
   eingerichtet wurden, und für Worktrees, die für opencode neue Projekte sind.
3. **Die Pane bleibt bestehen.** Abgebrochen wird der Prozess, nicht die
   Kachel — kein Layout-Flackern, keine wechselnde Pane-ID im Ergebnis.
4. **Das Policy-Plugin bleibt.** Es ist gewollt; mit dem Aufwärmen kostet es
   nichts mehr.

## 5. Der Entwurf

### 5.1 `herdr.py` — Budget durchreichen, Tasten senden, Wiederanlauf

**`agent_start(..., timeout_ms: int | None = None)`** reicht `--timeout` an
Herdr durch *und* setzt das eigene Subprozessbudget auf
`timeout_ms / 1000 + DEFAULT_TIMEOUT_S`. Damit killt lean-herdr nie mehr einen
Start, den Herdr noch legitim abwartet — Defekt 3.1 verschwindet strukturell,
nicht durch eine größere Zahl. Ohne `timeout_ms` bleibt das heutige Verhalten.

Der bestehende Wiederholungsversuch gegen `agent_pane_busy`
(`AGENT_START_ATTEMPTS = 5`, positiver Exit-Code, Antwort nach 0,0 s) bleibt
unverändert. Er behandelt eine andere Störung als der Hänger und darf mit ihr
nicht vermischt werden.

**`pane_send_keys(pane, *keys)`** → `herdr pane send-keys`. Neue Methode,
gleiche Form wie die übrigen: Fehler werden `{}`, nie Ausnahmen.

**`start_agent(...)` — der gemeinsame Helfer.** Er lebt hier, weil er
ausschließlich aus Herdr-Verkehr besteht:

```
start_agent(herdr, name, *, kind, pane, agent_args,
            first_timeout_ms, retry_timeout_ms) -> dict
```

1. Versuch 1: `agent_start(..., timeout_ms=first_timeout_ms)`.
   Antwortet Herdr, ist der Agent bereit — fertig.
2. Sonst: `pane_send_keys(pane, "ctrl-c")` — die CLI-Form ist positional,
   `herdr pane send-keys <PANE_ID> <KEY>...`. Danach pollen, bis kein Eintrag
   aus `agent_list()` mehr diese `pane_id` trägt, höchstens
   `PANE_FREE_TIMEOUT_S`. Ist die Pane nach der Hälfte der Frist noch belegt,
   ein zweites `ctrl-c`: ein hängender opencode hat seine Oberfläche nie
   aufgebaut und fängt die Taste deshalb nicht ab, ein gezeichneter schon.
3. Versuch 2: `agent_start(..., timeout_ms=retry_timeout_ms)`. Das Projekt ist
   jetzt gewärmt; gemessen 3,4 s.
4. Bleibt auch der erfolglos, meldet der Helfer, **welche** der beiden
   Störungen vorlag: Ablehnung durch Herdr oder Hänger.

Der Detektor ist Herdrs eigenes `--timeout`, kein eigenes Pollen. Es ist
dokumentiert, und Herdr weiß früher als wir, ob der Agent eingabebereit ist.

### 5.2 `workspace.py` und `dispatch.py` — ein Aufruf statt zweier Pfade

Beide ersetzen ihren `herdr.agent_start(...)`-Aufruf samt
`agent_start_failed`-Prüfung durch `start_agent(...)`. Die Fehlerbilder
trennen sich:

| Fehler | bedeutet |
|---|---|
| `agent_start_failed` | Herdr hat abgelehnt — falscher Name, unbekannte Art, Pane dauerhaft belegt |
| `opencode_stuck` | Der Start hängt; auch der zweite Anlauf kam nicht bis zur Eingabebereitschaft |
| `no_agent_id` | Der Agent ist bereit, aber sein MCP-Server steht nicht in der Registry |

`opencode_stuck` trägt Pane- und Workspace-ID, damit der Betreiber die Kachel
findet. Die drei sind heute alle `no_agent_id` oder `agent_start_failed`.

### 5.3 `initcmd.py` — das Aufwärmen

Nach dem Schreiben der Dateien, nur wenn das Binary im PATH liegt und
`workspace_settings()` über der eben geschriebenen Config `kind == "opencode"`
ergibt: `opencode debug agent <OPENCODE_ORCHESTRATOR>` im Projekt, kopflos,
hartes Budget `WARM_TIMEOUT_S`, Ausgabe verworfen, Rückgabewert egal — der
Abbruch *ist* der Zweck. Der Agentname wird aus `workspace.py` importiert, nie
ein zweites Mal buchstabiert; er muß derselbe sein, den `up` später übergibt.

Jeder Fehler bleibt stumm und landet höchstens im `warnings`-Feld, das `init`
schon führt. Das Ergebnis meldet `warmed`.

Kein neuer Konfigurationsschlüssel. Wer das Aufwärmen nicht will, hat mit
`up` weiterhin einen Weg, der sich selbst hilft.

### 5.4 Fristen

| Konstante | Wert | Begründung |
|---|---|---|
| `FIRST_START_TIMEOUT_MS` | 12 000 | Warmer Start misst 3,4–3,9 s; reichlich Luft, ohne einen Hänger lange auszusitzen |
| `RETRY_START_TIMEOUT_MS` | aus `ready_timeout_s` | Der zweite Anlauf bekommt das volle konfigurierte Budget |
| `PANE_FREE_TIMEOUT_S` | 6 | Warten, bis `ctrl-c` die Pane geräumt hat |
| `WARM_TIMEOUT_S` | 8 | 5 s reichen gemessen 6/6; 8 s ist der Sicherheitszuschlag |
| `ready_timeout_s` | bleibt 45 | Nicht mehr die tragende Frist, sondern nur noch das Netz unter dem Registry-Eintrag — der steht ≤ 1 s nach der Bereitschaft |

Jede Konstante trägt ihre Messung im Kommentar, wie die bestehenden in
`herdr.py`.

**Zwei Randbedingungen, die der Code einhalten muß:**

- Herdrs `agent start --timeout` nimmt höchstens 300 000 ms. Ein größer
  konfiguriertes `ready_timeout_s` wird beim Durchreichen darauf gedeckelt —
  sonst lehnt Herdr den Aufruf ab, und aus einem großzügigen Budget würde ein
  sofortiger Fehlschlag.
- Der schlechteste Fall von `up` ist damit `FIRST_START_TIMEOUT_MS` +
  `PANE_FREE_TIMEOUT_S` + `ready_timeout_s` für den zweiten Anlauf +
  `ready_timeout_s` für den Waiter, also rund 108 s bei den Vorgabewerten.
  Heute sind es 45 s, die nichts bewirken; danach sind es im gewärmten
  Normalfall unter 4 s.

## 6. Tests

- `tests/doubles.py::agent_started` sieht ab 5.1 ein zusätzliches `--timeout`
  in den Argumenten. Beim letzten Eingriff dieser Art brachen zehn Tests, weil
  sie auf der leeren Standardantwort des Doubles liefen — diesmal vorher
  angesehen.
- Neu abzudecken:
  - Versuch 2 nach einem Hänger, mit `ctrl-c` dazwischen.
  - `opencode_stuck` als eigener Fehler mit Pane- und Workspace-ID.
  - `agent_start_failed` bleibt für die echte Ablehnung reserviert.
  - Das durchgereichte `--timeout` und das daraus abgeleitete
    Subprozessbudget.
  - `init` bleibt stumm, wenn `opencode` nicht im PATH ist, und meldet
    `warmed: false`.
  - `dispatch` nutzt denselben Helfer — eine Prüfung, dass es nicht zwei
    Mechanismen gibt.

## 7. Was nicht passiert

- Kein Eingriff in das Zed-Plugin (`artisann.zed-herdr`).
- `.opencode/plugins/lean-ctx-policy.js` bleibt, unverändert.
- Kein `--pure` irgendwo: es wärmt kopflos nicht (gemessen 6/6 Hänger danach).
- Kein Schließen und Neuanlegen von Panes.
- Keine Übersetzungsläufe, kein Refactoring nebenbei.

## 8. Restrisiko

**`ctrl-c` erreicht einen festgefahrenen Prozess möglicherweise nicht.** Der
hängende opencode steht in `epoll_wait`; ob seine Ereignisschleife den Handler
noch abarbeitet, ist nicht gemessen. Bleibt die Pane danach belegt, lehnt
`agent start` ab, und der Helfer meldet `opencode_stuck` — ehrlich, mit
Pane-ID, statt still zu scheitern. Das ist der bewusst gewählte Ausgang; die
Alternative wäre gewesen, die Pane zu schließen, was das Layout ändert.

**Das Aufwärmen ist an opencodes heutiges Verhalten gebunden.** Behebt opencode
den Hänger, wird `init` 8 s ärmer und sonst nichts; der Wiederanlauf in `up`
kostet dann nie etwas, weil Versuch 1 immer trägt.

## 9. Grundlage

Alle Zahlen dieses Dokuments sind am 2026-09-04 auf dem Rechner des Betreibers
gemessen worden, gegen opencode 1.18.25 und Herdr 0.8.2, jeweils in frisch
angelegten git-Repos, die nach der Messung wieder entfernt wurden.
