# lean-herdr: `workspace up` und Konfiguration härten, ein Install für alle Projekte — Design v1.0

**Stand:** 2026-09-13 · **Status:** entworfen, nicht implementiert
**Anlass:** Die Race-Untersuchung zu zwei gleichzeitigen `workspace up` (Final-Review des
Katalog-Branches, Befund „fester Temp-Name") hat drei weitere Defekte freigelegt, alle
gemessen. Parallel soll lean-herdr in anderen Projekten dieser Maschine nutzbar werden,
bevor die nächste Spec Agents-Konfiguration und Dispatch vertieft. Beides braucht
dasselbe Fundament: ein Install, eine geprüfte Konfiguration, Templates mit Update-Weg.
**Bezug:** `2026-09-13-lean-herdr-katalog-review-und-sdk-1-1-design.md` (§3.2, §8),
`2026-09-03-lean-herdr-workspace-start-design.md` (§3.1, §9),
`2026-09-04-lean-herdr-rollenmodelle-und-katalog-design.md`,
`2026-09-01-lean-herdr-design.md` (Herdr: `plugin link`/`unlink`, H6/H7)
**Betrifft:** `lean_herdr/{bus,settings,llm,catalog,workspace,dispatch,initcmd,cli,__main__}.py`,
neu `lean_herdr/templating.py`, `lean_herdr/checkcmd.py`,
`lean_herdr/plugin/herdr-plugin.toml`; die Templates `wt.toml`, `settings.json`,
`opencode.jsonc`, `config.toml` und ihre Kopien in diesem Repo; neu
`.lean-ctx/lean-herdr/templates.lock.json`; entfällt `bin/herdr-llm`, später
`herdr-plugin.toml` im Root; `README.md`, `.gitignore`, Tests.

---

## 1. Ziel und Abnahme

`lean-herdr` läuft in jedem Repository dieser Maschine aus **einem** installierten
Snapshot — unabhängig davon, welcher Branch in `~/Scripts/lean-herdr` gerade
ausgecheckt ist. `workspace up` und die Konfiguration verlieren die gemessenen
Fehlerpfade. Projektkopien der Templates werden projektneutral und haben einen
Update-Weg, der keine Hand-Edits überschreibt.

**Abnahme** (Task 10, nach dem Merge, gemessen):

1. In einem frischen Repository unter `/tmp` laufen `lean-herdr workspace init`,
   `workspace check`, `workspace up` und ein `wt step commit` — während
   `~/Scripts/lean-herdr` auf einem Feature-Branch steht. `wt config show --full`
   meldet die Commit-Generierung über `lean-herdr llm generate` als funktionsfähig.
2. `workspace check` meldet dort `install.tool: true`, `install.editable: false` und
   einen Paketpfad im Tool-venv.
3. `herdr plugin list --plugin lean.herdr` zeigt `[local:<tool-venv>/…/lean_herdr/plugin]`,
   `herdr plugin list` keine Zeile mit `warning:`.

Nicht Ziel: Veröffentlichung, andere Maschinen (§12).

## 2. Ausgangslage, gemessen am 2026-09-13

### 2.1 Install und Einstiege

| Befund | Beleg |
|---|---|
| Der uv-tool-Install ist editable | `direct_url.json`: `{"url": "file:///home/tholo/Scripts/lean-herdr", "dir_info": {"editable": true}}`, `_editable_impl_lean_herdr.pth` → Checkout. Jedes Projekt läuft auf dem ausgecheckten Branch |
| Drei Einstiege, drei mögliche Codestände | `lean-herdr` (uv tool); Plugin `python3 -m lean_herdr` mit `plugin link` auf den Checkout (`herdr plugin list`: `[local:/home/tholo/Scripts/lean-herdr]`); Generator laut README `…/bin/herdr-llm generate` |
| Plugin-Handler finden `lean_herdr` nur über den Checkout | System-`python3` sieht die `.pth` des Tool-venv nicht; `python3 -m` findet das Paket also nur, weil Herdr im verlinkten Checkout startet (abgeleitet, Task 0b misst). `bin/herdr-llm` schiebt den Checkout selbst in `sys.path`; der Eingriff in `__main__.py:13` wirkt erst nach dem Import, also nur beim Start als Skriptpfad |
| Der Herdr-Server hat `~/.local/bin` auf dem PATH | `/proc/<pid>/environ` von `herdr` und `herdr server` |
| Der Generator ist nicht eingerichtet | `wt config show --format json`: `"user": {"config": null, "exists": false}` |
| `list.json-schema` im Template wird ignoriert | wt 0.77.0: „Key list.json-schema belongs in user config (will be ignored)" — in jedem Projekt, das `init` schreibt |
| 2 Projekt-Befehle ohne Approval | `wt config show`: „2 project commands awaiting approval" |
| Projektspezifische Befehle in Templates | `wt.toml` `test = "uv run pytest -q"`, `settings.json` `Bash(uv run pytest:*)`, `opencode.jsonc` Builder `uv run pytest*`, `uv run ruff*`; die Rollen-Prompts nennen keinen Befehl |
| Kein Update-Weg für Projektkopien | `init` überspringt Vorhandenes, `--force` überschreibt alles, auch Hand-Edits |

### 2.2 Overlay und Fehlerpfade

Proben im Scratchpad gegen `93ba6f1`, Netz gesperrt, danach gelöscht.

| Befund | Beleg |
|---|---|
| S2: fester Temp-Name mischt Inhalte ungleicher Länge | 600 Zufallspaare: ab Längendifferenz 2 immer Mix, `tomllib` lehnt ab; zwei synchronisierte Prozesse mit je einem Write: 4/400 dauerhaft kaputtes Overlay |
| S3: offener Deskriptor schreibt in die Live-Datei | B hält die Temp-Inode, A ersetzt → Bs Bytes landen im Overlay, Bs `replace` wirft `FileNotFoundError` → `write_failed`; im verschränkten Fall Mix |
| S4: fremdes `unlink` | A scheitert und löscht die Temp-Datei, die B geschrieben hat → Bs Write verloren |
| `write_failed` ist Rauschen | synchronisiert: 169/400 (ungleich), 207/400 (gleich lang) |
| Gleiche Länge mischt nie | 0/600, 0/20 Reihenfolgen, 0/400 — aber kurz leeres Target und verlorene Writes |
| Keine Selbstheilung | kaputtes Overlay → `models apply`/`check`/`list`: `config_error`, kein Fetch, Hash vorher = nachher. Ursache `catalog.py:356`: `llm_settings_layered` vor jedem Unterbefehl |
| Verlorenes Start-Ergebnis | `workspace.main(["up"])` mit `auto = true` und kaputtem Overlay: `start_orchestrator` lief, Ausgabe `{"ok": false, "error": "config_error: …"}` ohne `pane`/`agent_id`. Ursache `workspace.py:369`, nach dem Start (`:345`) |
| `dispatch` blockiert Log-Kommandos | `dispatch.py:770` liest das Overlay für alle Kommandos; verbraucht wird `llm_cfg` nur im `--await`-Zweig (`:825`) |
| Commit-Pfad verliert `config.toml` | `llm.py:342-345`: ein `try` um beide Dateien → kaputtes Overlay kostet auch gültiges `[llm].model`/`effort` |
| Das Overlay trägt nur `model` | `settings.py:362`: `replace(above, model=above.model or below.model)` — Efforts kommen allein aus `config.toml`; `up` und `models apply` lesen das Overlay also für nichts |
| git-Fehler ungefangen | `bus.py:34-43`: kein `try` um `subprocess.run` — fehlendes git (`FileNotFoundError`), hängendes (`TimeoutExpired`), undekodierbarer Pfad (`UnicodeDecodeError`) → `workspace_crashed`/`models_crashed`; `handlers`, `initcmd`, `llm` fangen je eigen |
| Temp-Rest nicht ignoriert | `.gitignore:22` nennt nur `models.auto.toml` |

### 2.3 venv und Install-Erkennung

| Befund | Beleg |
|---|---|
| Aktives Fremd-venv ändert den Tool-Interpreter nicht | Shebang `#!/home/tholo/.local/share/uv/tools/lean-herdr/bin/python3`; `VIRTUAL_ENV` wirkungslos |
| Fremd-venv kann `lean_herdr` nicht importieren | `ModuleNotFoundError` — das Tool ist nur als CLI teilbar |
| Aktiviertes Repo-venv überdeckt den Snapshot | `which lean-herdr` mit `.venv/bin` vorn → `…/lean-herdr/.venv/bin/lean-herdr` |
| `PYTHONPATH` überdeckt das Paket sogar im Tool | Tool-Python mit `PYTHONPATH=<Fake-Paket>` importiert das Fake-Paket |
| Tool-venv erkennbar | `uv-receipt.toml` liegt in `sys.prefix` des Tool-venv, fehlt im Repo-venv |
| Editable erkennbar | `importlib.metadata.distribution("lean-herdr").read_text("direct_url.json")` |
| worktrunk-Config maschinenlesbar | `wt config show --format json`: `user`/`system` mit `path`, `exists`, `config`; Warnungen auf stderr |
| `herdr plugin list` hat kein JSON | Text `- lean.herdr (…) enabled [local:<pfad>]` |

## 3. Install-Oberfläche

### 3.1 Snapshot

`lean-herdr` wird nicht-editable aus `main` installiert und nach einem Merge bewusst
neu installiert: `uv tool install --reinstall <quelle>`. Die Quelle — `git+file://…@main`
oder ein Wheel aus einem main-Worktree — misst Task 0. Kein automatisches Reinstall.

In diesem Repo gibt es damit zwei Wege, gewollt: `uv run lean-herdr …` prüft den
Entwicklungsstand, das nackte `lean-herdr` ist der Snapshot. Worker rufen
`lean-herdr report …` auf dem stabilen Stand, `uv run pytest` testet den Branch.

### 3.2 Zwei neue Verben

`cli.VERBS` bekommt:

| Verb | Modul | Vertrag |
|---|---|---|
| `plugin <sub>` | `lean_herdr.__main__` | wie heute: stdout leer, Fehler auf stderr, exit 0 |
| `llm generate\|prereview …` | `lean_herdr.llm` | wie heute: `generate` exit 0 und Text auf stdout; `prereview` exit 1 nur bei `reject` |

Beide weichen vom JSON-Vertrag der übrigen Verben ab; der `cli.py`-Docstring und
`USAGE` nennen das. Der Import-Crash-Pfad (`_crashed`) schreibt für diese beiden
**keine** JSON-Zeile auf stdout — bei `llm generate` würde sie zur Commit-Message:

- `plugin`: Meldung auf stderr, exit 0 (ein Handler bricht nie etwas).
- `llm`: Meldung auf stderr, exit 1 — ein kaputter Install ist laut, am ersten Commit,
  wie der argparse-Usage-Fehler, den `llm.main` schon so behandelt.

`llm.build_parser` heißt `prog="lean-herdr llm"`; die stderr-Präfixe `herdr-llm:`
werden `lean-herdr llm:`.

### 3.3 Manifest im Paket

`herdr-plugin.toml` zieht nach `lean_herdr/plugin/herdr-plugin.toml`. Plugin-ID,
Events und Actions bleiben; jeder Befehl wird `["lean-herdr", "plugin", "<sub>"]`.
Verlinkt wird `Path(lean_herdr.__file__).parent / "plugin"` im Tool-venv — Code und
Manifest stammen damit aus demselben Snapshot. Das Root-Manifest bleibt bis Task 10
liegen (§11).

### 3.4 Folgen im Baum

- `bin/herdr-llm` entfällt, ebenso der `sys.path`-Eingriff in `__main__.py:13`.
  `python -m lean_herdr` aus dem Repo-Root funktioniert weiter.
- Die Regel „`llm`/`openrouter` nur stdlib, `llm` importiert nie `catalog`" bleibt.
  Ihre Begründung wechselt von „der System-Interpreter hat keine Pakete" zu „startet
  bei jedem Commit; `dependencies = []`". Betroffen: Docstrings in `llm.py`
  (Modul, `file_settings`), `openrouter.py`, `catalog.py` (Modul, `write_overlay`),
  `settings.py` (`llm_settings`), und die Guard-Tests `test_catalog.py`,
  `test_openrouter.py`, `test_llm.py`.
- `test_manifest.py::test_the_package_parses_on_the_python3_the_manifest_may_meet`
  verliert seinen Grund: das Manifest startet kein `python3` mehr. Er wird zu „jeder
  Manifest-Befehl beginnt mit `["lean-herdr", "plugin"]`" — dass `<sub>` in `HANDLERS`
  steht, prüft `test_no_handler_without_subcommand` schon. Der Syntax-Floor gilt nur
  noch über `requires-python`. Der Docstring von
  `test_the_entry_point_still_points_at_a_callable_main` nennt `python3 -m lean_herdr`
  und wird mitkorrigiert.
- `python3` bleibt Laufzeitabhängigkeit: `lean-ctx-policy.js:67` startet die
  Claude-Code-Hooks damit.

## 4. Overlay und Fehlerpfade

Leitregel: **jede Stelle liest nur die Datei, deren Inhalt sie verwendet.** Kein
toleranter Leser kommt dazu.

### 4.1 Lesen

| Stelle | danach |
|---|---|
| `workspace_up` | `llm_settings(data)` **vor** `start_orchestrator`, neben `models_settings` — immer, nicht nur bei `auto` (ein `[llm]`-Tippfehler bleibt nicht still, wie `[models]` heute). Nach dem Start wirft nichts mehr; `check()` wirft nie. Das Overlay liest `up` nicht |
| `catalog.main` | Efforts aus `llm_settings(data)`. `list` und `apply` lesen das Overlay nicht; `apply` überschreibt ein kaputtes Overlay und heilt es damit. Nur `check` liest `llm_settings_layered(root, data)` für `current` und bleibt laut |
| `dispatch.main` | `llm_settings(raw)` validiert immer; `llm_settings_layered(root, raw)` nur, wenn `args.waiting`. `config.toml` wird weiter genau einmal gelesen |
| `settings.llm_settings_layered` | ein Fehler im Overlay-Teil wird `OverlayError(SettingsError)`; die Meldung nennt `lean-herdr models apply` |
| `llm.file_settings` | fängt `OverlayError` zuerst: Meldung auf stderr, dann `config.toml` allein (eigener Fehler dort → Defaults wie heute). Wirft weiter nie |

Die letzte Zeile verengt eine bestehende Toleranz, statt eine neue zu schaffen:
`file_settings` ist schon heute der Pfad, der nie wirft. Alle lauten Pfade fangen
weiter `SettingsError` und sehen `OverlayError` als solchen.

### 4.2 Schreiben

`write_overlay` bekommt einen Temp-Namen pro Schreiber:

- `tempfile.mkstemp(dir=path.parent, prefix=".tmp-models.auto.toml.")`, schreiben über
  den Deskriptor, dann `os.replace`.
- Bei `OSError` löscht er nur **seine** Temp-Datei und wirft weiter; `check()` meldet
  `write_failed` wie heute.
- Behebt S2 (keine geteilte Inode), S3 (kein fremder Deskriptor auf der Live-Datei),
  S4 (kein fremdes `unlink`). `write_failed` heißt wieder: das Dateisystem sagte nein.
- `mkstemp` legt Modus 0600 an; das Overlay ist maschinenlokal, hingenommen.
- Bleibt, im Docstring benannt: S1 — zwei gleichzeitige Checks holen zweimal, das
  letzte vollständige `replace` gewinnt. Kein Lock, kein gemeinsamer Helfer.

Ein Rest nach hartem Abbruch hat wechselnde Namen. Empfohlen werden zwei Ignore-Zeilen:
`.lean-ctx/lean-herdr/models.auto.toml` (wie heute) und `.lean-ctx/lean-herdr/.tmp-*` —
die zweite deckt auch Reste des Lock-Schreibers (§5.2). Task 0c misst beide per
`git check-ignore`.

`_check_overlay_ignored` fällt **ein Urteil je Pfad**: ein `git check-ignore -v`-Aufruf
für `OVERLAY_PATH` — nur bei `auto`, wie heute —, ein zweiter für
`.lean-ctx/lean-herdr/.tmp-models.auto.toml.probe` — **immer**, weil der Lock-Schreiber in
jedem Projekt läuft. Leere Ausgabe heißt nicht ignoriert; die Warnung nennt genau die
fehlende Zeile. Ein
gemeinsamer Aufruf bestünde still, sobald nur das Overlay ignoriert ist — der Stand
dieses Repos (`.gitignore:22`). `check` meldet liegen gebliebene `.tmp-*` in
`.lean-ctx/lean-herdr/`, ebenfalls unabhängig von `auto` (§6).

### 4.3 git

- `bus.canonical_root` fängt `OSError`, `subprocess.SubprocessError` und
  `UnicodeDecodeError` und wirft `GitUnusable(BusError)` mit der Ursache.
- `workspace.main` und `catalog.main` geben ihn über ihre vorhandene
  `BusError`-Stufe benannt aus statt `*_crashed`.
- `initcmd.workspace_init` fängt `GitUnusable` **vor** `BusError` → `init_stopped: …`;
  sonst hieße „git fehlt" `not_a_git_repo: run git init`. Sein `except OSError` um
  `canonical_root` entfällt.
- `handlers.handle_bootstrap` und `llm.file_settings` fangen `BusError` schon; ihr Code
  bleibt, ihre Kommentare, die die rohen Ausnahmen von `canonical_root` beschreiben,
  werden richtiggestellt. `dispatch.main` bleibt unberührt (`dispatch_crashed`).
- Sichtbar ändert sich die Ausgabe auch, wo `BusError` schon gefangen wird:
  `report.main` (`report.py:325`) meldet fehlendes git benannt statt `report_crashed`,
  `handlers._context` (`handlers.py:82-83`) entsprechend. Gewollt; Tests, die das alte
  Verhalten festhalten, folgen. `orderlog.state_dir` umschließt `canonical_root` nicht.

## 5. Templates: rendern und festhalten

### 5.1 Rendern

Zwei Token, heute in keinem Template (gemessen: kein `{{`/`}}`):
`{{lean-herdr:test}}` und `{{lean-herdr:lint}}`. Die Werte sind **Befehls-Präfixe**.

| Template | Stelle |
|---|---|
| `wt.toml` | `[pre-merge] test = "{{lean-herdr:test}}"`; `[list] json-schema = 1` samt Kommentar entfällt |
| `settings.json` | `"Bash({{lean-herdr:test}}:*)"` — **kein** Lint-Token: die Claude-Seite bleibt bewusst enger als opencode (Betreiberentscheidung 2026-09-03, `test_worker_permissions.py:196-200`) |
| `opencode.jsonc` | Builder `"{{lean-herdr:test}}*"`, `"{{lean-herdr:lint}}*"` |

- Defaults: `test = "uv run pytest"`, `lint = "uv run ruff"`. Dieses Repo verliert
  damit `-q` im Gate — nur Ausgabe.
- Setzen: `init --test "…" --lint "…"`. Auflösung: Flag > Lock-Werte > Default.
- Werte passen auf `[A-Za-z0-9][A-Za-z0-9 ._/=+,@-]*` ohne Leerzeichen am Ende — kein
  Anführungszeichen, Backslash, `*`, `:`, `$`, Zeilenumbruch, Shell-Operator. Sie
  landen in JSON, JSONC und TOML, die von Hand gefüllt werden (Muster `SLUG_RE`).
  Sonst `usage_error`. Wie weit ein Präfix das Gate öffnet, entscheidet der Betreiber.
- Nach dem Rendern bleibt kein `{{lean-herdr:` übrig; sonst ist das Paket defekt
  (`ValueError`, von Tests bewacht).
- Die übrigen fünf Templates (Rollen, `config.toml`, Policy-Adapter) haben keine Token
  und werden wörtlich geschrieben.

### 5.2 Lock

`.lean-ctx/lean-herdr/templates.lock.json`, versioniert — es reist im Branch wie die
Rollen. `init` schreibt es ganz (Temp-Datei pro Schreiber mit Präfix
`.tmp-templates.lock.json.`, `os.replace`, inline wie §4.2). „Ganz“ betrifft die Datei,
nicht den Inhalt: Einträge für Dateien, die der Lauf nicht schreibt (`outdated`,
`edited`, `diverged`), bleiben unverändert — sonst würde `outdated` beim nächsten Lauf
`unknown`, und `--update` griffe nicht mehr:

```json
{
  "values": {"lint": "uv run ruff", "test": "uv run pytest"},
  "files": {".claude/settings.json": "<sha256 der geschriebenen Bytes>", "…": "…"}
}
```

Schlüssel sind die Zielpfade aus `LAYOUT`, sortiert, Einrückung 2. JSON, weil die
stdlib es liest und schreibt. Fehlt die Datei: keine Werte, keine Einträge. Ist sie
kaputt — kein JSON, falsche Form, ein Wert, der `VALUE_RE` verletzt, ein Schlüssel
außerhalb `LAYOUT` —: `LockError(ValueError)` mit Pfad; `init` antwortet
`lock_malformed: <pfad>: … -- fix or delete it`, `check` warnt (§6). Ein ungültiger
**Flag**-Wert bleibt `usage_error`.

### 5.3 Zustände je Datei

D = sha256 der Datei, L = Lock-Eintrag, P = sha256 des Paket-Templates, gerendert mit
den aufgelösten Werten. Geprüft in dieser Reihenfolge:

| Zustand | Bedingung | Bedeutung |
|---|---|---|
| `blocked` | ein Elternteil unter `root` ist ein Symlink, oder das Ziel selbst ist einer | Elternteil: `init` schreibt dort nie, auch nicht mit `--force`. Ziel: nur `--force` ersetzt den Link (beides Regeln aus `_place`) |
| `missing` | Datei fehlt | |
| `current` | D = P | nichts zu tun |
| `unknown` | kein L | Projekt aus der Zeit vor dieser Spec |
| `outdated` | D = L ≠ P | unberührt, Paket oder Werte sind weiter |
| `edited` | D ≠ L = P | Hand-Edit, Absicht |
| `diverged` | D ≠ L, L ≠ P | beides |

Ändert ein Flag die Werte, werden unberührte Dateien `outdated` und bearbeitete
`diverged` — derselbe Mechanismus, kein Sonderfall.

### 5.4 `init`

| Modus | schreibt | Lock |
|---|---|---|
| ohne Flag | `missing` | setzt den Eintrag für `missing` (geschrieben) und `current` auf D — auch einen vorhandenen, veralteten; so bekommen ältere Projekte ihr Lock ohne Überschreiben |
| `--update` | `missing`, `outdated` | wie oben plus die neu geschriebenen |
| `--force` | alles außer Dateien unter einem Symlink-Elternteil | alle geschriebenen |

- `--force` und `--update` zusammen: `usage_error`.
- Die Ergebnis-Schlüssel `written`/`skipped` bleiben; neu `values` und `templates`
  (Zustand je Datei **nach** dem Lauf). `--update` nennt, was es warum stehen ließ.
- Symlink-Regeln von `_place` bleiben unverändert; `_place` bekommt die gerenderten
  Bytes statt eines Quellpfads.

### 5.5 Code-Ort

Neu `lean_herdr/templating.py`: `TEMPLATES`, `LAYOUT` (zieht aus `initcmd` um),
`LOCK_PATH`, `DEFAULT_VALUES`, `VALUE_RE`, `render()`, `read_lock()`, `write_lock()`,
`file_state()`. `initcmd` und `checkcmd` importieren es; die Tests importieren
`LAYOUT` von dort.

## 6. `lean-herdr workspace check`

Eine Antwort auf „laufen `up` und `dispatch` hier, und wo wird es still schlechter?" —
ohne zu starten, zu schreiben, zu fetchen oder vorzuwärmen.

- Drittes Wort neben `up` und `init`. `--force`, `--update`, `--test`, `--lint` sind
  dort `usage_error`, ebenso bei `up`.
- Eine JSON-Zeile, exit 0, wirft nie. `ok` = keine `errors`. Jede Zeile nennt den
  nächsten Schritt (Muster `INIT_HINT`).

```json
{"ok": true, "root": "…", "errors": [], "warnings": ["…"],
 "install": {"tool": true, "editable": false, "package": "…", "binary": "…", "plugin": "…"},
 "templates": {"opencode.jsonc": "current", ".config/wt.toml": "outdated"}}
```

**errors** — `up` oder `dispatch` scheitert jetzt:

- `GitUnusable` oder kein Repository (`BusError`); dann fehlt `root`.
- `config.toml` fehlt (`not_initialised`) oder ist ungültig: `settings_for` für
  `default`, `orchestrator`, `builder`, `reviewer`, dazu `workspace_settings`,
  `models_settings`, `llm_settings`.
- `OverlayError`.
- `missing_agent_config` für die `kind` des Orchestrators.

**warnings** — wird still schlechter:

| Gruppe | Prüfung | Grundlage |
|---|---|---|
| Maschine | `herdr`/`wt`/`lean-ctx` auf PATH, lean-ctx-Allowlist, wt-Approvals, `warning:` in `herdr plugin list` | heutige `_check_*` |
| Generator | wirksamer `commit.generation.command` fehlt, oder `shlex.split` davon beginnt nicht mit `lean-herdr llm generate` (Flags dahinter sind erlaubt) | `wt config show --format json`, `user.config` vor `system.config`; geparst mit `json.JSONDecoder().raw_decode` ab der ersten Klammer, weil `_read` stderr anhängt |
| Install | `uv-receipt.toml` fehlt in `sys.prefix`; editable; `lean_herdr.__file__` liegt aufgelöst nicht unter dem aufgelösten `sys.prefix` (nennt `PYTHONPATH`, wenn gesetzt); `Path(shutil.which("lean-herdr")).resolve()` liegt nicht darunter — ohne `resolve()` wäre jeder korrekte Install eine Warnung, denn `~/.local/bin/lean-herdr` ist ein Symlink ins Tool-venv (gemessen) | §2.3 |
| Plugin | kein `[local:…]` für `lean.herdr` oder ungleich `<paket>/plugin` → fertige `herdr plugin link …`-Zeile | `herdr plugin list --plugin lean.herdr`, Pfad per Regex |
| Templates | `outdated`/`missing` → `init --update`; `diverged`/`unknown` → von Hand abgleichen; `blocked` → Symlink nennen; `edited` ist keine Warnung. Lock kaputt: `templates` ist `{}`, eine Warnung nennt `lock_malformed` — kein Zustand wird geraten, auch nicht `unknown` | `templating.file_state` |
| Overlay und Lock | Ignore-Regel je Pfad: Overlay bei `auto`, `.tmp-*` immer; liegen gebliebene `.tmp-*` in `.lean-ctx/lean-herdr/` immer | §4.2, §5.2 |
| Modelle | `model_warnings` | vorhanden |

**Code:** neu `lean_herdr/checkcmd.py` mit
`workspace_check(*, root=None, runner=subprocess.run)`. `_read` und die `_check_*`
ziehen aus `initcmd` dorthin, ihre Tests nach `tests/test_checkcmd.py`. `init` behält
`warnings` und holt sie aus denselben Produzenten (eine Quelle je Regel, M3) — meldet
also künftig auch Generator, Install und Plugin. `workspace.main` importiert
`checkcmd` beim Aufruf, wie `initcmd`. Fremde Befehle bleiben reine Leser mit
`CHECK_TIMEOUT_S`; fehlt ein Binary, gibt es kein Urteil.

Hingenommen: `uv run lean-herdr workspace check` in diesem Repo warnt „kein Tool-venv,
editable" — korrekt. `uv-receipt.toml` ist ein uv-Detail; ändert es sich, meldet
`check` fälschlich „kein Tool-venv" — nur als Warnung.

## 7. README

Operator-Doku, Englisch. Anzupassen:

- **Runtime dependencies:** `lean-herdr`-Zeile — Snapshot-Befehl aus Task 0 statt
  `uv tool install --editable .`, die Zeile nennt die sechs Verben `dispatch`, `llm`,
  `models`, `plugin`, `report`, `workspace`; `python3`-Zeile — Zweck „runs the
  Claude-Code hooks of the policy adapter" statt „runtime of the plugin handlers".
- **Commit generator:** `command = "lean-herdr llm generate"`; der Absatz „The path is
  absolute, never `bin/herdr-llm`" entfällt; `stage = "none"` bleibt als dokumentierte
  Option mit seinem maschinenweiten Hinweis.
- **Work-order path:** `bin/herdr-llm prereview …` → `lean-herdr llm prereview …`.
- **Keeping the model current:** Ignore-Zeilen `.lean-ctx/lean-herdr/models.auto.toml`
  und `.lean-ctx/lean-herdr/.tmp-*`;
  `apply` rewrites a broken overlay.
- **What else ships here:** Manifest-Ort, `herdr plugin link <tool-venv>/…/lean_herdr/plugin`,
  den Pfad nennt `workspace check`.
- **Setting up a project:** `--test`/`--lint`, `templates.lock.json`, `--update`,
  `workspace check`, die Ignore-Zeile `.lean-ctx/lean-herdr/.tmp-*`; der Absatz über `uv run pytest` in Nicht-Python-Projekten wird zu
  `--test`/`--lint`.
- **Neu „Updating":** nach einem Merge `uv tool install --reinstall …`, dann
  `lean-herdr workspace check` und je Projekt `workspace init --update`; Hinweis auf
  venv-/`PYTHONPATH`-Überdeckung (§2.3).
- **Development:** `uv run lean-herdr …` ist der Entwicklungsstand; `check` warnt dort
  zu Recht.

`tests/test_config_files.py::test_readme_names_every_runtime_dependency` verlangt
zusätzlich `lean-herdr llm generate`, `lean-herdr workspace check` und `--reinstall`;
ein neuer Test daneben verlangt, dass `bin/herdr-llm` im README nicht mehr vorkommt.
`test_wt_toml_has_the_pre_merge_gate_and_a_fixed_schema` verliert die
`json-schema`-Assertion (`test_config_files.py:61`).
Außerdem: der Kommentar `templates/config.toml:37` (`through bin/herdr-llm`) und seine
Kopie in `.lean-ctx/lean-herdr/config.toml`; die zweite `.gitignore`-Zeile dieses Repos.

## 8. Tests

**Neu**

- `bus`: fehlendes, hängendes git und undekodierbarer Pfad → `GitUnusable`; `init`
  meldet fehlendes git als `init_stopped`, nicht `not_a_git_repo`.
- `settings`: kaputtes Overlay → `OverlayError`, `isinstance(…, SettingsError)`.
- `llm.file_settings`: kaputtes Overlay + gültiges `[llm].model`/`effort` → Werte aus
  `config.toml`, Meldung auf stderr.
- `workspace_up` mit `auto = true` und kaputtem Overlay → `ok`, `pane`, `agent_id`
  bleiben; `[llm]`-Tippfehler → `config_error`, `start_orchestrator` nicht aufgerufen.
- `models apply` über kaputtem Overlay → `written`, danach lesbar.
- `dispatch order|answer|cancel` mit kaputtem Overlay → `ok`; `--await` → `config_error`.
- `write_overlay`: zwei Aufrufe mit abgefangenem `os.replace` erzeugen verschiedene
  Temp-Namen; ein scheiternder Schreiber lässt eine fremde `.tmp-models.auto.toml.x`
  stehen. Deterministisch, ohne Timing.
- `templating`: kein Token nach `render`; jeder Zustand aus §5.3 aus präparierten
  Dateien; `init`/`--update`/`--force` schreiben und locken nach §5.4; Werte mit `"`,
  `*`, `:`, `$`, Zeilenumbruch → `usage_error`; kaputtes Lock → `lock_malformed`.
- Gates mit Fremdwert `--test "cargo test" --lint "cargo clippy"`: die Assertions aus
  `test_worker_permissions.py` (kein Blankoscheck, kein `lean-herdr dispatch` in
  Worker-Gates, kein Wildcard direkt hinter `lean-herdr`) laufen auch gegen die so
  gerenderten Templates.
- `checkcmd`: jede Gruppe über `FakeProc`; Install-Erkennung gegen ein präpariertes
  Prefix (Receipt ja/nein, `editable`, Paket außerhalb, `PYTHONPATH`); Plugin-Pfad aus
  `[local:…]`; Generator aus wt-JSON mit angehängter stderr-Zeile, `user` vor `system`;
  Generator mit Flags hinter `lean-herdr llm generate` → keine Warnung; Temp-Reste;
  Lock kaputt → `templates == {}`; nur das Overlay ignoriert → Warnung nennt
  `.lean-ctx/lean-herdr/.tmp-*`, auch bei `auto = false`; `which` über einen Symlink ins Prefix → keine Warnung.
- `cli`: `plugin` und `llm` routen; `llm prereview` gibt exit 1 durch; Import-Crash
  von `llm` → stderr + exit 1, von `plugin` → stderr + exit 0, beide ohne stdout.

**Geändert**

- `test_manifest.py`: `MANIFEST` → `lean_herdr/plugin/herdr-plugin.toml`; Floor-Test
  nach §3.4; `bin/herdr-llm` aus der Prüfliste; der Wheel-Test verlangt auch das
  Manifest; `test_plugin_link_produces_no_warning` linkt das Paket-Verzeichnis.
- `test_templates.py`: `render(template, Werte aus dem Lock dieses Repos)` == Kopie im
  Repo; das Lock dieses Repos **existiert** und meldet für jede Datei `current`. Es
  entsteht und wird committet in Task 6 (`uv run lean-herdr workspace init` im Repo).
  Außerdem ist jeder Lock-Eintrag gleich dem sha256 der Kopie im Repo (L = D). Ohne
  diese beiden Bedingungen bestünde der Test auch mit fehlendem oder veraltetem Lock,
  weil D = P vor dem Lock-Eintrag geprüft wird; ein veralteter Eintrag machte einen
  späteren Hand-Edit zu `diverged` statt `edited`. Jede Template-Änderung zieht damit
  das Lock nach (`uv run lean-herdr workspace init`).
- `test_worker_permissions.py`: `CLAUDE_BUILDER_TOOLING` bleibt; die Assertions laufen
  zusätzlich gegen die mit Fremdwert gerenderten Templates (oben).
- `test_config_files.py`: `list.json-schema`-Assertion entfällt; README-Guard nach §7.
- `test_initcmd.py`: `_check_*`-Tests ziehen nach `test_checkcmd.py`; `LAYOUT` aus
  `templating`.
- Guard-Docstrings nach §3.4.

`-m integration`: Wheel enthält Templates und Manifest; `herdr plugin link` auf das
Paket-Verzeichnis ohne `warning:`.

## 9. Reihenfolge

| # | Inhalt | hängt an |
|---|---|---|
| 0 | **Messen, kein Code.** (a) `uv tool install` nicht-editable aus `git+file://…@main` in ein isoliertes `UV_TOOL_DIR`, Fallback Wheel aus main-Worktree; (b) liest Herdr das Manifest bei jedem Event oder kopiert `link` es; (c) `git check-ignore` für die Zeilen `models.auto.toml` und `.tmp-*` auf Overlay, Overlay-Temp- und Lock-Temp-Namen; (d) Syntax von `herdr plugin unlink`. Ergebnisse in `ctx_session` | — |
| 1 | `GitUnusable` (§4.3) | — |
| 2 | `OverlayError`, `llm.file_settings` (§4.1) | — |
| 3 | nur lesen, was gebraucht wird: `up`, `models`, `dispatch` (§4.1) | 2 |
| 4 | `write_overlay`, Ignore-Check für beide Namen (§4.2) | 0c |
| 5 | `templating.py`: `LAYOUT`, Token, `render`, Template-Änderungen, Kopien im Repo (§5.1, §5.5) | — |
| 6 | Lock, Zustände, `init --test/--lint/--update` (§5.2–5.4); Lock dieses Repos committen | 5 |
| 7 | `checkcmd.py`, `workspace check`, `init` über dieselben Produzenten (§6) | 1, 2, 4, 6 |
| 8 | Verben `plugin`/`llm`, Manifest ins Paket, `bin/herdr-llm` und `sys.path`-Eingriff raus, Docstrings (§3) | 0b |
| 9 | README, Template-Kommentar samt Lock dieses Repos, `.gitignore` (§7) | 0a, 3, 4, 6, 7, 8 |
| 10 | Migration und Abnahme, **nach dem Merge** (§10, §1) | alle |

1–4 sind klein und berühren den Install nicht. 5–7 bauen aufeinander auf; 7 zieht
außerdem das in 4 geänderte `_check_overlay_ignored` samt Tests um und läuft deshalb
nie parallel zu 4. 8 kommt spät,
weil es den Plugin-Weg ändert; das Root-Manifest bleibt bis 10, damit das verlinkte
Plugin auf dem Branch weiterläuft.

## 10. Migration dieses Repos (Task 10)

1. `uv tool install --reinstall <quelle aus Task 0>` → `workspace check`:
   `editable: false`.
2. `herdr plugin unlink …` (braucht laufenden Server, H7), dann
   `herdr plugin link <tool-venv>/…/lean_herdr/plugin`; Root-`herdr-plugin.toml`
   löschen und committen.
3. `~/.config/worktrunk/config.toml` anlegen: `[commit.generation] command =
   "lean-herdr llm generate"`. Ob `[commit] stage = "none"` dazukommt, entscheidet der
   Betreiber dabei — maschinenweit.
4. `lean-herdr workspace check` meldet jede Template-Datei dieses Repos `current` — das
   Lock kam mit Task 6.
5. `wt config approvals add` für die offenen Projekt-Befehle.
6. Abnahme aus §1; `workspace check` hier und im `/tmp`-Repo ohne `errors`.

Übergang: Bis Schritt 2 zeigt der Plugin-Link auf den Checkout. Dort liegt bis dahin
unverändert das Root-Manifest mit `python3 -m lean_herdr`, und das Paket liegt
daneben — die Handler laufen weiter, auf Checkout-Code. Erst Schritt 2 legt sie auf
den Snapshot. Das Root-Manifest ist ab Task 8 ungetestet (`test_manifest.py` prüft
das Paket-Manifest) und lebt nur bis Schritt 2.

## 11. Risiken

| Risiko | Gegenmittel |
|---|---|
| uv nimmt `git+file` nicht | Task 0a; Fallback Wheel aus main-Worktree |
| Herdr liest das Manifest live, der Link auf den Checkout bricht auf dem Branch | Root-Manifest bleibt bis Task 10; Task 0b misst |
| Rendern verschiebt eine Gate-Zeile | Permission-Tests gegen Default **und** Fremdwert (§8) |
| Python-Minor-Wechsel beim Reinstall → Link ins Leere | `check` meldet mit fertiger Link-Zeile |
| Aktiviertes Repo-venv oder `PYTHONPATH` überdeckt den Snapshot | Install-Gruppe in `check` |
| Zwei Branches fahren `--update`, das Lock kollidiert | Konflikt sichtbar in git, selten; kein Mechanismus |
| `uv-receipt.toml` ändert sich | nur Warnung |
| Produktions-LOC | gemessen: `catalog` 240, `workspace` 229, `initcmd` 187, `llm` 344, `dispatch` 530; neue Module klein; Grenze 800 |

## 12. Was dieser Entwurf NICHT tut

- **Keine Veröffentlichung**, kein `herdr plugin install` aus GitHub, keine anderen
  Maschinen.
- **Keine Agents-Konfiguration, kein Dispatch-Umbau** — nächste Spec. `dispatch.py`
  ändert nur, wann es das Overlay liest.
- **Kein automatisches Reinstall, kein automatisches Template-Update** — `--update` ist
  eine Geste.
- **Kein toleranter Leser** in `up`, `dispatch`, `models check` (Katalog-Spec §8).
- **Kein gemeinsamer Helfer** für atomares Schreiben; Overlay und Lock schreiben inline.
- **Kein Lock gegen S1**, keine Erkennung laufender Checks.
- **Keine Erkennung des Projekttyps** für `--test`/`--lint`; Defaults oder Flags.
- **Keine neue Abhängigkeit**; `dependencies = []`.
