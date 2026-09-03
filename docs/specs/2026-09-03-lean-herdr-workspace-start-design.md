# lean-herdr: Ein Binary, ein Workspace-Start — Design v1.0

**Stand:** 2026-09-03 · **Status:** entworfen, nicht implementiert
**Ersetzt:** den Abschnitt „Bootstrap" der `README.md` und die hartcodierte
Konstante `handlers.ORCHESTRATOR`
**Anlass:** Der Betreiber fragte nach dem Ablauf
*Terminal → `herdr` → „Workspace starten mit der Config"*. Die Klärung legte
eine zweite, größere Anforderung frei: lean-herdr soll auch in einem fremden,
notfalls leeren Projekt benutzbar sein.

## 1. Der Anlass, und was er freigelegt hat

Die Ausgangsfrage war klein: Wenn `.config/lean-herdr.toml` fertig
konfiguriert ist, wie startet man damit einen Workspace? Die Antwort war,
dass man es gar nicht kann.

**Heute gibt es zwei Startwege, und beide lesen die Config nicht.** Der
manuelle aus dem README (`herdr pane split --current …` gefolgt von
`herdr agent start orch …`) und die Plugin-Action `bootstrap`, ein
Tastendruck im laufenden Herdr. Letztere liest ihre Werte aus
`handlers.ORCHESTRATOR` — Name, Laufzeit und Umgebung als Literale im Code:

```python
ORCHESTRATOR = {
    "name": "orch",
    "kind": "opencode",
    "env": {"LEAN_CTX_TOOL_PROFILE": "minimal", "LEAN_CTX_ROLE": "orchestrator"},
}
```

`settings.py` wird dort nirgends aufgerufen. `.config/lean-herdr.toml` wirkt
ausschließlich in `dispatch.py`, also erst *nachdem* der Orchestrator steht.

**Die zweite Anforderung kam beim Nachfragen.** lean-herdr ist heute
vollständig selbstbezüglich: `bin/herdr-dispatch` und `bin/herdr-report` sind
relative Pfade, wörtlich so in `roles/*.md`, in `opencode.jsonc` und in
`.claude/settings.json`. Ein fremdes Projekt hat nichts davon. Wie teuer diese
Selbstbezüglichkeit ist, steht bereits im Code: `wt_switch` verzweigt seit
einem gemessenen Fehlschlag auf `base="@"` statt auf den Default-Branch —

> „a worker reports back by running `bin/herdr-report`, which is introduced by
> the orchestrator's own branch. A worktree branched off `main` structurally
> lacks that script" — `worktree.py:65-75`

Ein Workaround, der nur existiert, weil das Werkzeug im Repo liegt statt auf
dem PATH.

## 2. Entscheidung

Drei Entscheidungen, in dieser Reihenfolge getroffen:

1. **Ein Binary statt dreier.** `lean-herdr` als einziger Entry-Point mit den
   Verben `dispatch`, `report`, `workspace`. Global installiert, nicht im Repo.
2. **Eigene Dateien nach `.lean-ctx/lean-herdr/`.** Config und Rollentexte;
   die fremden Suchpfade bleiben, wo ihre Eigentümer suchen.
3. **`workspace init` und `workspace up` über einem Kern**, den die
   Plugin-Action `bootstrap` mitbenutzt.

Der Umfang von `up` ist bewusst klein: **nur der Orchestrator.** Worker
entstehen weiterhin ausschließlich über `dispatch`.

### 2.1 Warum nicht auch Worker-Panes

Die Annahme, Worker-Panes seien ohnehin immer dieselben, hält der Messung
nicht stand. Die Wiederverwendung hängt am Agent-Namen, und der hängt am
Branch:

- `dispatch.py:250-255` verwendet eine Pane wieder, wenn ein Agent **exakt
  dieses Namens** noch in `herdr agent list` steht — dann nur `/clear`.
- `agent_name()` (`dispatch.py:129-143`) liefert ohne `--worktree` schlicht
  `builder` bzw. `reviewer`, mit `--worktree` dagegen `{role}-{branch}`.
- `roles/orchestrator.md` schreibt `--worktree <branch>` vor, sobald Code
  entsteht. Der Normalfall ist also der Branch-Fall.
- Und mit `--worktree` landet die Pane über `anchor_pane()`
  (`worktree.py:159-170`) im **eigenen Workspace der Worktree** — genau den
  räumt das Teardown am Branch-Ende weg.

Worker-Panes sind im Worktree-Fluss also absichtlich branch-gebunden und
sterben mit dem Branch. Sie beim Start vorzuerzeugen legte sie im falschen
Workspace unter dem falschen Namen an; `dispatch --worktree` ignorierte sie
und splittete trotzdem neue.

### 2.2 Warum ein Binary und nicht zwei

Der naheliegende Einwand lautet, zwei getrennte Programme trennten Builder
und Orchestrator sauberer. Das tun sie nicht — die Grenze verlief nie dort.

- Die **lean-ctx-Allowlist ist maschinenweit**
  (`~/.config/lean-ctx/config.toml`), eine Liste, kein Eintrag pro Rolle. Ein
  `lean-ctx allow herdr-dispatch` gälte für den Builder ebenso. Sie beantwortet
  nur, welches Programm überhaupt starten darf.
- Die **echte Trennung sitzt in den Agent-Gates**: `.claude/settings.json` und
  der `permission.bash`-Block je Agent in `opencode.jsonc`, beide mit
  `"*": "deny"` als Grundlage. Sie matchen die ganze Kommandozeile und
  unterscheiden `lean-herdr report next` von `lean-herdr dispatch order`
  genauso gut wie zwei Programme.

Ein Binary verliert damit keine Grenze, die je eine war, und ersetzt drei
Freigaben durch eine: `lean-ctx allow lean-herdr`.

**Der Preis ist ein neuer Fallstrick, und er gehört in einen Test.** Bisher
war die Trennung strukturell: die Builder-Allowlist erwähnte
`herdr-dispatch` nie, weil es ein anderes Programm war. Mit einem Binary
reicht ein schlampiges `Bash(lean-herdr:*)`, um dem Builder das Dispatch-Verb
zu geben. `test_worker_permissions.py:80-84` prüft heute nur
`bin/herdr-report *`; das muss wachsen (Abschnitt 9).

### 2.3 Warum `.lean-ctx/lean-herdr/`

`.lean-ctx/` ist bereits die Konvention „ein Unterordner pro lean-Werkzeug":
lean-md ist ein eigenes Projekt und wohnt dort schon als `.lean-ctx/lean-md/`.
lean-herdr zieht als Geschwister ein.

Der ursprüngliche Einwand — Squatting in einem fremden Namensraum, wie ihn
`orderlog.state_dir()` (`orderlog.py:125-128`) bewusst vermeidet — trägt
hier nicht: dort ging es um das Datenverzeichnis *eines anderen Programms*,
hier um das Projektverzeichnis derselben Werkzeugfamilie.

**Zur `.gitignore`:** Zum Zeitpunkt dieses Entwurfs ist die Zeile `.lean-ctx/`
aus der `.gitignore` entfernt (`git check-ignore` liefert rc=1). Es ist also
nichts umzuschreiben, und `init` fasst die Datei nicht an. Sollte die Zeile je
zurückkehren, ist die Falle dokumentiert und gemessen: `!.lean-ctx/lean-herdr/`
allein wirkt **nicht**, weil git eine Datei nicht wieder einschließen kann,
deren Elternverzeichnis ausgeschlossen ist. Nur die Form

```
.lean-ctx/*
!.lean-ctx/lean-herdr/
```

funktioniert. Mit der ersten Form bleiben die Rollentexte unversioniert, kein
Worktree trägt sie, und jeder Dispatch läuft ins Leere — still.

## 3. Architektur

### 3.1 Entry-Point

```toml
[project.scripts]
lean-herdr = "lean_herdr.cli:main"
```

Neu: **`lean_herdr/cli.py`**, ein reiner Verb-Router von etwa fünfzig Zeilen.
Er baut nichts nach, sondern ruft die vorhandenen `main(argv) -> int`:

| Verb | Ziel | Status |
|---|---|---|
| `lean-herdr dispatch …` | `dispatch.main` | existiert |
| `lean-herdr report …` | `report.main` | existiert |
| `lean-herdr workspace …` | `workspace.main` | neu |

Ein unbekanntes Verb liefert `{"ok": false, "error": "usage_error: …"}` bei
Exit 0 — derselbe Vertrag, den `_Parser.error` (`dispatch.py:495-506`) schon
durchsetzt: der Aufrufer liest `ok`, nie den Exit-Code.

Neu: **`lean_herdr/workspace.py`**, etwa zweihundert Zeilen, mit `up`, `init`
und deren Parser. Wächst es Richtung vierhundert, wird `init` nach
`initcmd.py` abgespalten — so wie `ordercmd.py` schon einmal von
`dispatch.py` abgespalten wurde.

`bin/herdr-dispatch` und `bin/herdr-report` entfallen. Als Shims behalten
hieße, zwei Schreibweisen in vier Allowlists zu pflegen — genau die
Doppelung, gegen die `test_worker_permissions.py` überhaupt existiert.

### 3.2 Ablage im Zielprojekt

```
.lean-ctx/lean-herdr/
    config.toml                                 ← heute .config/lean-herdr.toml
    roles/{orchestrator,builder,reviewer}.md    ← heute roles/
```

Unverschiebbar, weil fremde Suchpfade, aber von `init` ebenfalls geschrieben:
`opencode.jsonc`, `.opencode/plugins/lean-ctx-policy.js`,
`.claude/settings.json`, `.config/wt.toml`.

`.config/wt.toml` bliebe theoretisch über `WORKTRUNK_PROJECT_CONFIG_PATH`
verschiebbar, praktisch nicht: die Variable müsste bei *jedem* `wt`-Aufruf
gesetzt sein, auch bei den handgetippten. Fehlt sie einmal, überspringt `wt`
die Projekt-Hooks still und meldet Erfolg — das pre-merge-Test-Gate liefe
nicht. Das README warnt bereits vor genau diesem Fehlermodus.

### 3.3 Eine Wahrheit für die Vorlagen

**Alle** Dateien, die `init` schreibt, liegen als Vorlage im Wheel unter
`lean_herdr/templates/` — `config.toml`, die drei Rollentexte,
`opencode.jsonc`, `settings.json`, `wt.toml`, `lean-ctx-policy.js`. `init`
kopiert von dort und erzeugt nichts programmatisch.

Für die Rollentexte hat das eine Folge, die ein Test tragen muss: Das
`.lean-ctx/lean-herdr/roles/` **dieses** Repos ist selbst eine solche Kopie.
`test_roles.py` und `test_role_prohibitions.py` prüfen künftig die Vorlage —
die Quelle —, und ein zusätzlicher Test hält Vorlage und eingecheckte Kopie
byte-gleich. Ohne ihn driften zwei Fassungen desselben Textes auseinander,
und der Test, der die Verbote bewacht, bewacht die falsche.

## 4. Konfiguration

`RoleSettings` bleibt, was es ist: Pane-Geometrie plus Profil, pro Rolle. Was
`up` braucht, ist etwas anderes und bekommt einen eigenen Abschnitt.

```toml
[workspace]
label = "{repo}"        # Herdr-Workspace-Label; {repo} = Verzeichnisname
kind  = "opencode"      # Laufzeit des Orchestrators
model = ""              # leer = kein --model, wie der heutige Bootstrap

[roles.orchestrator]
profile = "minimal"     # unverändert
```

`ROOT_KEYS` wächst von `("default", "roles")` auf
`("default", "roles", "workspace")`, mit unveränderter Strenge: ein unbekannter
Schlüssel bleibt ein `SettingsError`, kein stiller Default.

Zwei Festlegungen, damit keine zweite Lesart offenbleibt:

- **`{repo}` in `label` ist optional.** Anders als bei `name_template`, wo
  `{role}` und `{branch}` erzwungen sind, weil der Wiederverwendungsschlüssel
  an ihnen hängt (`settings.py:113-126`), ist `label` reine Beschriftung. Ein
  wörtliches `label = "arbeit"` ist gültig; ein unbekannter Platzhalter bleibt
  ein `SettingsError`.
- **`up` baut die Agent-Argumente selbst, nicht über `agent_args()`.** Die
  Funktion (`dispatch.py:146-154`) setzt für `opencode` immer `--model` und
  leitet den Agentennamen aus dem Dateinamen der Rolle ab — beides passt hier
  nicht. `up` übergibt `--agent orchestrator` und hängt `--model <m>` nur an,
  wenn `model` nicht leer ist. Das ist genau, was `handle_bootstrap` heute
  tut.

**Der Agent-Name des Orchestrators wird bewusst kein Konfigurationsschlüssel.**
Das README beschreibt den Umbenennungspfad und was er kostet:
`dispatch.ORCHESTRATOR_AGENT`, die Zeile `ORCHESTRATOR = orch` in beiden
Rollentexten und
`test_roles.py::test_the_role_prompts_trust_the_name_dispatch_actually_stamps`
müssen übereinstimmen. Ein Config-Schlüssel bräche diesen Dreiklang auf, ohne
dass jemand danach gefragt hat. `handlers.ORCHESTRATOR` gibt `kind` und `env`
an `[workspace]` und `[roles.orchestrator]` ab und behält nur den Namen.

`SETTINGS_PATH` wird zu `.lean-ctx/lean-herdr/config.toml` — weiterhin
**relativ**, aus dem Grund, der schon in `settings.py:18-22` steht: der
Aufrufer verbindet ihn mit `canonical_root()`, sonst lädt die Config
stillschweigend nicht mehr, sobald der Aufruf aus einem Unterverzeichnis oder
einem Worktree kommt.

## 5. Ablauf `lean-herdr workspace up`

1. **Wurzel und Config.** `canonical_root()`, dann
   `read_settings(root / SETTINGS_PATH)`. Fehlt die Datei:
   `{"ok": false, "error": "not_initialised: run `lean-herdr workspace init`"}`.
   Nicht stillschweigend mit Defaults starten — die Config ist der ganze Zweck
   des Aufrufs.
2. **Server erreichbar?** `herdr.is_available()` plus ein `workspace list`.
   Kein Server: `{"ok": false, "error": "no_herdr_server"}`, statt am toten
   Socket zu hängen. Jedes `herdr <sub>` läuft über den Socket; der Server ist
   eine echte Vorbedingung, keine Annahme.
3. **Läuft der Orchestrator schon?** `agent list` nach `ORCHESTRATOR_AGENT`
   absuchen → `{"ok": true, "already_running": true, …}`. Derselbe
   Duplikat-Check, den `handle_bootstrap` heute macht; `up` ist idempotent.
4. **Workspace finden oder anlegen.** Existiert einer mit
   `worktree.checkout_path == root`, wird der genommen. Sonst
   `herdr workspace create --cwd <root> --label <label>
   --env LEAN_CTX_TOOL_PROFILE=<profil> --env LEAN_CTX_ROLE=orchestrator
   --focus`.
5. **Pane.** *Die eine Stelle, die der Plan zuerst messen muss:* Landet das
   `--env` von `workspace create` auf der Wurzel-Pane, ist diese Pane bereits
   die Orchestrator-Pane und der Schritt entfällt. Wenn nicht, wird von
   `anchor_pane()` aus gesplittet — der Pfad, den `handle_bootstrap` schon
   geht. Beide Zweige sind klein, der Fallback existiert. Liefert
   `anchor_pane()` nichts — ein Workspace ohne Pane, nach einem
   Server-Neustart möglich —, endet der Aufruf mit
   `{"ok": false, "error": "no_anchor_pane"}`; derselbe Fehlername, den
   `dispatch()` (`dispatch.py:246-248`) für dieselbe Lage benutzt.
6. **Agent starten.**
   `herdr agent start orch --kind <kind> --pane <id> -- [--model <m>]
   --agent orchestrator`.
7. **Auf Bereitschaft warten.**
   `wait_for_agent_id(…, timeout_s=ready_timeout_s)` — die Funktion aus
   `dispatch.py:173-205`, wiederverwendet, nicht nachgebaut. Ohne `agent_id`:
   `{"ok": false, "error": "no_agent_id"}`.
8. **Ausgabe.**
   `{"ok": true, "workspace": "w3", "pane": "w3:p1", "agent": "orch",
   "agent_id": "…"}`.

## 6. Ablauf `lean-herdr workspace init [--force]`

1. **Wurzel bestimmen.** `canonical_root()` startet git; ohne Repo:
   `{"ok": false, "error": "not_a_git_repo: run `git init` first"}`. `init`
   legt selbst kein Repo an — das ist eine Geste, die dem Menschen gehört.
2. **Dateien schreiben, nur wenn sie fehlen.** Vorhandene werden übersprungen
   und im Ergebnis genannt; `--force` überschreibt. Ein fremdes
   `opencode.jsonc` oder `.claude/settings.json` still zu überbügeln wäre der
   teuerste denkbare Fehlgriff dieses Werkzeugs.
3. **Voraussetzungen prüfen und melden, nicht reparieren.** Die Checkliste,
   die heute im README steht: `herdr`, `wt` und `lean-ctx` auf dem PATH,
   `lean-ctx allow lean-herdr` gesetzt, `wt config approvals list` mit
   `"state": "approved"`, `herdr plugin list` ohne `warning:`-Zeile. Jeder
   fehlende Punkt wird eine Zeile in `warnings`; `init` führt keine fremden
   Befehle aus.
4. **Ausgabe.**
   `{"ok": true, "written": [...], "skipped": [...], "warnings": [...]}`.

## 7. Plugin-Action auf denselben Kern

`handle_bootstrap` ruft künftig dieselbe Funktion wie `up`. Damit können die
beiden Startwege nicht mehr auseinanderdriften — heute können sie es, und der
Tastendruck ignoriert die Config vollständig.

## 8. Fehlerbehandlung

Unverändert das Hausmuster: eine JSON-Zeile auf stdout, `ok` als einzige
Wahrheit, Exit **immer** 0, jeder Ausnahmetyp abgefangen. `workspace.main`
bekommt dieselbe `except`-Leiter wie `report.main` (`report.py:294-329`),
einschließlich des abschließenden `except Exception`.

## 9. Tests

- **`cli.py`** — Verb-Routing; unbekanntes Verb liefert `usage_error` statt
  Exit 2.
- **`up`** gegen `FakeHerdr` aus `tests/doubles.py`: kein Server, Workspace
  existiert bereits, Orchestrator läuft bereits, Timeout ohne `agent_id`,
  Erfolgsweg.
- **`init`** in `tmp_path`: schreibt, überspringt, `--force`, kein Git-Repo,
  Warnungsliste.
- **`test_worker_permissions.py` — der neue Fallstrick.** Bisher trennte ein
  anderes Programm den Builder vom Dispatch, jetzt trennt nur noch das Gate.
  Zusätzlich also: kein Wildcard direkt hinter `lean-herdr`
  (`lean-herdr *`, `lean-herdr*`), und **kein Worker-Gate nennt je
  `lean-herdr dispatch`**.
- **Vorlagengleichheit** — `.lean-ctx/lean-herdr/roles/*.md` ist byte-gleich
  mit `lean_herdr/templates/roles/`.
- **`test_language.py`** — die neuen Dateien sind Englisch; nur `docs/` ist
  Deutsch.
- **`test_manifest.py`** — der Syntax-Floor gilt weiterhin für die Module, die
  die Plugin-Handler importieren: die Handler starten ein nacktes `python3`,
  den Interpreter des Hosts. Als `uv tool`-Entry-Point läuft `lean-herdr`
  dagegen unter dem installierten Interpreter; die beiden Einträge
  `bin/herdr-dispatch` und `bin/herdr-report` fallen aus der Prüfliste.

## 10. Migration dieses Repos

Das Repo benutzt sich selbst, also zählt die Reihenfolge:

1. `init` einmal hier laufen lassen; Ergebnis committen.
2. Alte Pfade entfernen: `.config/lean-herdr.toml`, `roles/`, `bin/`.
3. `lean-ctx allow lean-herdr`.
4. README neu: Der Bootstrap-Abschnitt wird `lean-herdr workspace up`. Der
   lange Absatz über die Pfad-Ausnahme im Shell-Gate wird ein Einzeiler — die
   Ausnahme galt, weil das Skript im Projektwurzelverzeichnis lag; global auf
   dem PATH ist die Freigabe Pflicht.

**Einmaliger Bruch:** Laufende Worker in bestehenden Worktrees verlieren
`bin/herdr-report`. Vor dem Merge alle offenen Aufträge schließen
(`lean-herdr dispatch cancel --task-id o-… --message "…"`).

## 11. Bewusst nicht enthalten

- **Worker-Panes vorab anlegen** — Abschnitt 2.1.
- **Orchestrator-Name konfigurierbar** — Abschnitt 4.
- **`kind`/`model` als Default für `dispatch`** — `RoleSettings` könnte sie
  tragen und `missing_flags` entsprechend lockern. Das ist eine eigene
  Verbesserung mit eigenem Testbedarf und gehört nicht in diesen Schnitt.
- **`git init` durch `init`** — eine Geste des Menschen, kein Werkzeugschritt.
- **`base="@"` in `wt_switch` zurückbauen** — der Workaround verliert mit den
  globalen Skripten seinen Hauptgrund, aber die Rollentexte reisen weiterhin
  im Branch. Ein eigener, messbarer Schnitt für später.
