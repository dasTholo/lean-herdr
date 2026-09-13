# lean-herdr: Review-Fixes des Katalog-Branches, SDK 1.1.0 neu bewertet — Design v1.0

**Stand:** 2026-09-13 · **Status:** Teil A entworfen, nicht implementiert · Teil B
abgeschlossen (Messung hier, Nachträge in den alten Specs mit `6dfb9a9`)
**Anlass:** Der Plan `2026-09-04-lean-herdr-rollenmodelle-und-katalog.lmd.md` ist mit
9/9 Tasks durch (`448b336..b25dd98`, 705 Tests grün). Das Final-Review über den
ganzen Branch endete mit offenen Punkten, und keiner davon ist behoben. Parallel
hat Thinkery AG die `leanctx-sdk` 1.1.0 veröffentlicht; der Betreiber will wissen,
ob das an früheren Entscheidungen etwas ändert.
**Bezug:** `2026-09-04-lean-herdr-rollenmodelle-und-katalog-design.md`,
`2026-09-02-leanctx-sdk-evaluation.md`, `2026-09-03-lean-herdr-auftragslog-design.md`
**Betrifft:** Teil A — `lean_herdr/initcmd.py`, `lean_herdr/catalog.py`,
`lean_herdr/settings.py`, `lean_herdr/llm.py` (nur Docstring), `README.md`,
`lean_herdr/templates/config.toml`, `.lean-ctx/lean-herdr/config.toml`,
`tests/fixtures/openrouter-models.sample.json`, Tests; vorab ein Format-Commit über
`lean_herdr/` und `tests/`. Teil B und die Nachträge — nur `docs/specs/`.

---

## 1. Zwei Teile, ein Dokument

Teil A behebt, was das Final-Review offen ließ. Teil B hält fest, was SDK 1.1.0 an
früheren Befunden ändert — gemessen, ohne Einbau. Die Teile teilen keinen Code; sie
stehen zusammen, weil der Betreiber sie zusammen entschieden hat. Teil B ändert
keine Zeile unter `lean_herdr/`.

Die Befundnummern folgen der Liste des Final-Reviews (Projekt-Erinnerung
`rollenmodelle-katalog-branch-final-review`). Die Nummern 7, 8 und 12 stehen dort
nicht unter „offen".

## 2. Ausgangslage, gemessen am 2026-09-13

| Befund | Beleg im Tree |
|---|---|
| 1 — ein `[models]`-Tippfehler nimmt den `init`-Report mit | `initcmd.py:223`: `_warnings()` ruft `models_settings(data)` selbst, und `_warnings()` läuft in `workspace_init` **hinter** dem `try` (`:369`), der `SettingsError` fängt (`:363`) |
| 2 — das Overlay wird nicht atomar geschrieben | `catalog.py:238`: `path.write_text(...)` direkt auf `models.auto.toml` |
| 3 — `fetch()` ohne Gürtel um den `request`-Seam | `catalog.py:88`: `request(...)` ohne `try`; `complete()` hat ihn (`llm.py:252-275`) |
| 4 — README zählt vier Abschnitte | `README.md:293` „Four sections", `[models]` fehlt |
| 5 — leeres Orchestrator-`model` falsch beschrieben | `README.md:312-314` und der Template-Kommentar `config.toml:20`; wahr nur für `workspace.py:272`. `dispatch` macht `""` zu `None` (`dispatch.py:814`), `missing_flags()` lehnt ab |
| 6 — `generate()`-Docstring ohne Overlay-Stufe | `llm.py:383-385` nennt vier Stufen; der Kettenblock `llm.py:50-67` nennt fünf (`generate()`-Modellkette `:58-59`) |
| 9 — Modell ohne `supported_efforts` ungetestet | der Code verwirft es (`catalog.py:160-162`), die Fixture hat keinen solchen Eintrag |
| 10 — „`openrouter.py` importiert nichts aus `lean_herdr`" hat keinen Test | das Gegenstück für `llm.py` existiert (`test_llm_does_not_import_the_catalogue`) |
| 11 — Zwei-Effort-Regel auf `workspace up` ungetestet | `workspace.py:381-384` reicht beide Stufen an `check()` |
| 13 — die Overlay-Grenze hält nur der Schreiber | `settings.py:381-385` übernimmt **jedes** `[llm]`-Feld aus dem Overlay; der Kettenblock `llm.py:50-67` kennt das Overlay nur als Stufe für `model`, drei Tests (`tests/test_settings.py:266`, `tests/test_llm.py:273`, `tests/test_dispatch.py:638`) verlangen das Gegenteil |
| 14 — `_TYPES` und `ALLOWED` können auseinanderlaufen | `settings.py:113` leitet `ALLOWED` aus den Feldern ab, `:160` indiziert `_TYPES[key]` |

Randbedingungen, die die Fixes formen:

- `.gitignore:22` nennt genau `.lean-ctx/lean-herdr/models.auto.toml` — eine
  Temp-Datei daneben ist nicht ignoriert.
- `.lean-ctx/lean-herdr/config.toml` ist getrackt und muss byte-identisch mit dem
  Template bleiben (`test_template_and_checked_in_copy_are_byte_identical`).
- `orderlog.append` schreibt atomar über Temp-Datei und `Path.replace`
  (`orderlog.py:374-378`) und räumt die Temp-Datei bei einem Fehler nicht weg.

## 3. Teil A — Verhaltensfixes

Jeder Fix steht an seiner Quelle, inline, nach einem Rezept, das das Projekt schon
hat. Kein gemeinsamer Helfer: er würde `orderlog` (Hash-Kette) und den Commit-Pfad
in `llm.py` anfassen, und die beiden Schreibmuster sind verschieden — Bytes unter
Hash-Namen gegen Text an festem Pfad.

### 3.0 Vorab — ein Format-Commit ohne Verhaltensänderung

Das Gate der Plan-Rezepte formatiert seit `e775af7` wieder vor Lint und Tests
(`@reformat {{ paths }}`). Ohne Vorlauf mischte jede Task Fix und Formatierung:
`ruff format --check` meldet 48 von 94 Dateien, darunter alle zehn, die Teil A
anfasst.

- Der erste Commit formatiert `lean_herdr/` und `tests/` (45 Dateien) und sonst
  nichts. Nachweis: `ruff check` sauber, volle Testsuite grün, kein Test inhaltlich
  geändert.
- `docs/` bleibt ausgenommen: diese ruff-Version formatiert auch Python-Codeblöcke
  in Markdown und schriebe die Mess-Skripte um, die in drei Specs als Beleg stehen.
  `bin/herdr-llm` fasst ruff ohne Dateiendung nicht an.
- `except (A, B):` wird dabei zu `except A, B:` (PEP 758, erst ab Python 3.14
  gültig). Auf dem Commit-Pfad ist das sicher: `/usr/bin/python3` und das `python3`
  im PATH sind 3.14.7, und 3.14 ist der Syntax-Boden des Projekts.
- Erst danach folgen die Fixes. Das Gate ändert an den formatierten Dateien nichts
  mehr, und jeder Fix-Commit zeigt nur den Fix.

### 3.1 Befund 1 — der `init`-Report überlebt einen `[models]`-Fehler

- `workspace_init` validiert `models_settings(data)` im bestehenden `try`, neben
  `model_warnings(data)` und `workspace_settings(data)` (`initcmd.py:361-362`), und
  merkt sich `.auto`.
- `_warnings()` bekommt `overlay_auto: bool`, statt `models_settings(data)` selbst
  aufzurufen.
- Fehlerfall: der vorhandene Zweig (`:363-368`) — `no warm-up: <Grund>`,
  `data = {}`, `overlay_auto = False`. `written` und `skipped` bleiben im Report.
  Die Ignore-Prüfung fürs Overlay entfällt, weil ohne lesbare Config nicht
  feststeht, ob `auto` an ist.

### 3.2 Befund 2 — das Overlay wird atomar geschrieben

- `write_overlay` schreibt nach `.tmp-models.auto.toml` im selben Verzeichnis und
  ersetzt dann mit `Path.replace` — das Rezept aus `orderlog.append`, ohne `fsync`
  aus demselben Grund (`orderlog.py:13`).
- `mkdir` bleibt vor dem Schreiben. Wirft Schreiben oder Ersetzen `OSError`, löscht
  `write_overlay` die Temp-Datei (`missing_ok=True`) und wirft weiter; `check()`
  meldet wie heute `write_failed` (`catalog.py:313-314`).
- Das Löschen ist der Unterschied zu `orderlog`: die Ignore-Regel trifft nur den
  genauen Namen, eine liegen gebliebene Temp-Datei stünde in `git status` des
  Betreibers.
- Restrisiko, akzeptiert: ein harter Abbruch zwischen Schreiben und Ersetzen
  hinterlässt die Temp-Datei. `models.auto.toml` selbst ist dann unberührt — nie
  halb geschrieben.

### 3.3 Befund 3 — `fetch()` hält „Never raises"

`request(...)` in `fetch()` steht in `try/except (OSError, ValueError)` und liefert
`None` — Muster und Begründung aus `complete()` (`llm.py:269-275`):
`openrouter.request` wirft nie, aber `request` ist injizierbar, und das Versprechen
gibt `fetch()` selbst. `check()` macht aus `None` wie heute `no_catalog`.

### 3.4 Befund 13 — aus dem Overlay zählt nur `model`

- `llm_settings_layered` nimmt aus dem Overlay nur `model`; jedes andere
  `[llm]`-Feld kommt allein aus `config.toml` oder bleibt `""`.
- Das Overlay läuft weiter vollständig durch `llm_settings()`: ein unbekannter
  Schlüssel, ein falscher Typ **oder ein ungültiger Wert** in einem bekannten Feld
  (etwa `effort = "enormous"`) bleibt `SettingsError`. Erst danach wird `.model`
  übernommen.
- Ein **gültiges** fremdes Feld (`effort = "low"`, `prereview_model = …`) wird
  ignoriert, nicht abgelehnt. Abgelehnt würde `dispatch` mit `config_error:` an
  einer Datei scheitern, die nichts Falsches sagt, sondern nur nichts mehr bewirkt.
- Das bringt den Leser in Einklang mit dem Kettenblock `llm.py:50-67`, der das
  Overlay nur als Stufe für `model` kennt (`:59`, `:64`), mit dem Schreiber, dem
  README (`:89`, `:159`) und dem Template (`config.toml:43`, `:50`). Der Katalog-Spec
  sagte „Feld für Feld" (`:455`) und hat dazu einen Nachtrag (Abschnitt 7).
- Der Schreiber bleibt, wie er ist: er schreibt nur `model` (`catalog.py:222-227`).

## 4. Teil A — Doku

- **Befund 4:** `README.md:293` nennt fünf Abschnitte; `[models]` bekommt einen Satz
  mit Verweis auf „Keeping the model current".
- **Befund 5:** der Code bleibt, wie Task 4 ihn gewollt hat — `dispatch.py:803-804`:
  für `--model` gibt es keine Rollentabelle, weil ein Modell, das niemand nennt,
  Geld kostet. `README.md:312-314` und der Template-Kommentar zu
  `[roles.orchestrator].model` sagen künftig: ein leeres `model` heißt kein
  `--model` bei `workspace up` und beim Tastendruck; `dispatch orchestrator` braucht
  `--model` oder ein gesetztes `model`. Template und `.lean-ctx/lean-herdr/config.toml`
  ändern sich byte-gleich.
- **Befund 6:** der `generate()`-Docstring zählt die Stufen nicht mehr auf, er
  verweist auf den Kettenblock `llm.py:50-67` (M3). Die achte Beschreibung der Kette
  entfällt, statt korrigiert zu werden.

## 5. Teil A — Tests

TDD in zwei Formen. Die vier Fixes aus Abschnitt 3 bekommen je einen Test, der vor
dem Fix scheitert. Die Wächter zu 9, 10, 11 und 14 sichern Verhalten, das heute
schon stimmt: sie laufen sofort grün und werden stattdessen durch eine Mutation
widerlegt, wie im Final-Review.

| Befund | Test | rot vor dem Fix / unter der Mutation |
|---|---|---|
| 1 | `workspace_init` mit `[models]` `auto = 1` liefert `ok`, `written` und die `no warm-up:`-Warnung | heute `SettingsError` |
| 2 | `Path.replace` wirft `OSError`: das alte Overlay ist unverändert, keine `.tmp-*`-Datei liegt daneben | heute ist die Datei schon überschrieben |
| 3 | `request` wirft `OSError` bzw. `ValueError`: `fetch()` → `None`, `check()` → `no_catalog` | heute fliegt die Exception |
| 13 | Overlay mit `model`, `effort` und `prereview_model`, `config.toml` ohne sie: nur `model` kommt an; dazu drei bestehende Tests umschreiben (siehe unten) | heute kommen alle drei an |
| 9 | siehe unten | Listen-Prüfung `catalog.py:161-162` entfernt |
| 10 | ein Subprozess importiert `lean_herdr.openrouter`; aus `lean_herdr` stehen nur `lean_herdr` und `lean_herdr.openrouter` in `sys.modules` — Muster aus `test_importing_handlers_does_not_drag_in_the_workspace_subtree` | ein `from lean_herdr.settings import …` in `openrouter.py` |
| 11 | `workspace up` mit `auto = true`, `catalog.check` ersetzt nach dem Muster `checked(**kwargs)` aus `test_up_with_auto_on_carries_the_catalogue_answer` (`tests/test_workspace.py:535`): `efforts` trägt beide aufgelösten Stufen — einmal aus `[llm]` mit zwei verschiedenen Werten (`effort = "high"`, `prereview_effort = "medium"`, damit auch eine Vertauschung auffällt), einmal aus `GENERATE_EFFORT`/`PREREVIEW_EFFORT` | eine der beiden Stufen in `workspace.py:381-384` gestrichen oder vertauscht |
| 14 | `set(settings._TYPES) == settings.ALLOWED` | ein `_TYPES`-Eintrag entfernt |

**Befund 13 — drei bestehende Tests verlangen heute das Gegenteil.** Sie werden mit
dem Fix umgeschrieben, nicht gelöscht; ihr eigentlicher Zweck bleibt:

- `test_config_toml_beats_the_overlay_field_by_field` (`tests/test_settings.py:266`):
  das Overlay trägt `model`, `prereview_model`, `effort` und `prereview_effort`.
  Künftig kommt davon nur `model` an, und nur, wo `config.toml` schweigt. Sein
  Docstring spricht von „the three the check filled in"; der gebaute Check füllt
  einen Schlüssel.
- `test_the_overlay_is_read_under_config_toml` (`tests/test_llm.py:273`) und
  `test_the_overlay_reaches_dispatch_under_config_toml` (`tests/test_dispatch.py:638`):
  beide beweisen, dass ihr Verbraucher das Overlay liest. Den Beweis führt künftig
  `model` aus dem Overlay unter einem `config.toml` ohne `model`, statt
  `prereview_model`.

Ohne Änderung grün bleiben `test_a_broken_overlay_is_a_config_error_too`
(`tests/test_dispatch.py:610`: ein ungültiges `effort` im Overlay bleibt
`config_error:`, siehe 3.4), `test_a_broken_overlay_costs_the_defaults_not_the_commit`
(`tests/test_llm.py:260`) und die übrigen Overlay-Tests in `tests/test_settings.py`,
die nur `model` oder kaputtes TOML schreiben.

**Befund 9 — ein fünfter Fixture-Eintrag.** `mid/no-effort-list` kommt an Position 3
der Fixture, zwischen `cheap/no-minimal-effort` und `mid/small-context`:

```json
{
  "id": "mid/no-effort-list",
  "context_length": 200000,
  "pricing": {"prompt": "0.00000008", "completion": "0.0000003"},
  "supported_parameters": ["reasoning"],
  "reasoning": {"mandatory": true, "default_effort": "low"},
  "benchmarks": {
    "artificial_analysis": {
      "intelligence_index": 58.0,
      "coding_index": 56.0,
      "agentic_index": 45.0
    }
  }
}
```

Die Position ist so gewählt, dass kein bestehendes Ergebnis kippt. Geprüft gegen
jeden Test, der die Fixture liest:

- Mit `efforts=()` gewinnt in jedem Fall ein Eintrag davor (`cheap/no-benchmarks`
  oder `cheap/no-minimal-effort`). Einen Test mit leerem `efforts` und einer
  Index-Untergrenze, unter der der neue Eintrag gewänne — `coding_index` in
  (38.5, 56] oder `intelligence_index` in (41, 58] —, gibt es nicht.
- Mit gesetzten `efforts` fällt der neue Eintrag ohne Liste heraus. Die Fälle
  „no benchmarks block, and no minimal effort" und „index, effort and context
  together" der Parametrisierung sowie
  `test_a_model_that_cannot_do_the_effort_is_dropped` prüfen die Regel damit
  nebenbei mit.
- `test_recommend_takes_the_given_order_and_does_not_re_sort` behält
  `good/all-clear` vorn.
- `test_main_list_shows_the_survivors_and_writes_nothing` behält `total == 3`; seine
  Meldung nennt künftig beide Aussortierten.
- Einzige Anpassung: `test_fetch_returns_the_recorded_page_as_four_dicts` wird zu
  `…_as_five_dicts`, mit der fünften id.

Dazu ein benannter Test als widerlegbares Paar: mit `min_coding_index=50.0` gewinnt
bei `efforts=("minimal",)` `mid/small-context`, bei `efforts=()` `mid/no-effort-list`.
Der zweite Fall beweist, dass allein die fehlende Liste den Eintrag aussortiert.

Unter der Mutation aus der Tabelle (Listen-Prüfung `catalog.py:161-162` entfernt)
wirft `level not in None` einen `TypeError`: der Paar-Test scheitert mit einem
Fehler, nicht mit einer falschen Wahl. Das zählt als widerlegt; der Plan nennt
diese Fehlerform, damit niemand sie für einen kaputten Test hält.

## 6. Teil B — SDK 1.1.0, neu bewertet

### 6.1 Messung

Gemessen am 2026-09-13 gegen `thinkery-leanctx-sdk==1.1.0` von PyPI unter CPython
3.14.7, mit zwei Engines: dem Wheel `thinkery-leanctx-engine==3.10.1` und der
lokalen `lean-ctx 3.10.1` unter `~/.cargo/bin`. Reproduktion in 6.4.

| Frage | Ergebnis |
|---|---|
| Veröffentlicht? | SDK 1.1.0 auf PyPI (2026-09-06T15:29Z) und als GitHub-Release `v1.1.0`; Engine 3.10.1 auf PyPI (`thinkery-leanctx-engine`, 2026-09-06) und als lean-ctx-Release `v3.10.1` — laut `gh release list` das neueste |
| Python-Code seit der Gegenprüfung geändert? | **nein.** `git diff --stat 277d0c7 main`: 24 Dateien, keine unter `src/`. Geändert sind Release-CI, `COMPATIBILITY.md`, `README.md`, `CHANGELOG.md` und die Pakete für TypeScript, Go, Rust, JVM und .NET. `LICENSING.md` und `docs/PREVIEW.md` sind unverändert |
| Welche Werkzeuge erreicht `AgentContext`? | mit beiden Engines `ctx_compose ctx_glob ctx_read ctx_search ctx_symbol ctx_tree` (Standardrechte, nur lesend) |
| Die vier, die `leanctx.py` ruft? | `ctx_agent`, `ctx_session`, `ctx_handoff`, `ctx_knowledge` → `UnsupportedCapabilityError: Engine did not negotiate capability` |
| Wie streng ist der Engine-Pin? | `agent.py:38` `SUPPORTED_AGENT_TOOLS_ENGINE_VERSION = "3.10.1"`, verglichen wird die Versionszeichenkette (`agent.py:436`). Die cargo-gebaute `lean-ctx` hat **nicht** den SHA-256 der zertifizierten Linux-Binary (`0385c816…`) und wird trotzdem angenommen |
| Python-Bereich | `requires_python <3.15,>=3.9`; der Boden des Projekts, 3.14, liegt darin |

### 6.2 Was sich an früheren Befunden ändert

- **Auftragslog §3 (Zeile „SDK 1.1.0 ist nicht veröffentlicht") und §11:** überholt.
  Der Grund „1.1.0 und Engine 3.10.1 nicht veröffentlicht, der Betrieb liefe auf
  einem Git-Commit" entfällt. Die Entscheidung — eigenes Ereignis-Log, keine SDK —
  trägt auf den übrigen Gründen: E-2, `ContextWorkspace` weiter PREVIEW, und ein
  Workspace wäre der dritte Kontextspeicher.
- **E-2:** bestätigt, jetzt am veröffentlichten Paket. `leanctx.py` bleibt.
- **E-1:** präzisiert. Der Pin ist exakt, aber nur auf die Versionszeichenkette.
  Folge für jeden späteren Einsatz: das nächste lean-ctx-Release macht
  `AgentContext` unbenutzbar, bis die SDK nachzieht — gleich, woher die Binary
  stammt.
- **E-9:** unverändert.

### 6.3 Ein Kandidat, mit Bedingung

Der Prereview-Judge sieht heute höchstens `MAX_DIFF_BYTES = 150_000` (`llm.py:138`),
darüber endet er in `skipped`/`diff_too_large` (`llm.py:487-488`). `AgentContext`
liefert genau die lesenden Werkzeuge, mit denen ein Judge den Branch selbst lesen
könnte; die Modellschleife bliebe beim Host (`docs/CUSTOM-AGENTS.md` der SDK:
*„LeanCTX never selects the model, retries the model, or decides when the task is
complete."*).

Kein Einbau jetzt. Ein eigener Spec erst, wenn `diff_too_large` im Betrieb auftritt.
Sein Preis steht schon fest:

- SDK und Engine-Wheel als Abhängigkeit im uv-tool-venv von `lean-herdr` — nie im
  Commit-Pfad, `bin/herdr-llm` läuft auf dem System-Interpreter;
- das Wheel legt ein eigenes `lean-ctx` in das `bin/` des venv;
- Tool-Calling über OpenRouter — `tools` käme in `[models].requires`, das heute
  bewusst ohne es auskommt;
- die Pflege des exakten Engine-Pins (6.2, E-1).

### 6.4 Reproduktion

```bash
git clone https://github.com/Thinkery-AG/leanctx-sdk.git sdk
git -C sdk diff --stat 277d0c7 main
gh release list -R yvgude/lean-ctx -L 4
gh release list -R Thinkery-AG/leanctx-sdk -L 4
uv venv --python 3.14 sdk114
uv pip install --python sdk114/bin/python 'thinkery-leanctx-sdk[agent]==1.1.0'
sdk114/bin/python probe_sdk114.py   # venv NICHT aktivieren: sonst findet which() das lean-ctx des Wheels
```

`probe_sdk114.py`:

```python
import hashlib, importlib.metadata as md, pathlib, shutil, sys
from leanctx_sdk import AgentContext
from leanctx_sdk.agent import SUPPORTED_AGENT_TOOLS_ENGINE_VERSION

CERTIFIED_LINUX_X86_64 = "0385c8169a4b20df84dc0f1e8b32788c3b7a402cb0b5ff484d391f8cd67a5bbc"
HERDR_TOOLS = ("ctx_agent", "ctx_session", "ctx_handoff", "ctx_knowledge")

print("python", sys.version.split()[0])
print("sdk", md.version("thinkery-leanctx-sdk"), "| engine wheel", md.version("thinkery-leanctx-engine"))
print("pinned engine", SUPPORTED_AGENT_TOOLS_ENGINE_VERSION)

path_bin = shutil.which("lean-ctx")
digest = hashlib.sha256(pathlib.Path(path_bin).read_bytes()).hexdigest()
print("PATH lean-ctx", path_bin, "sha256 certified:", digest == CERTIFIED_LINUX_X86_64)

proj = pathlib.Path(__file__).with_name("probe-proj")
proj.mkdir(exist_ok=True)
(proj / "README.md").write_text("# probe\n", encoding="utf-8")

for label, kwargs in (("wheel-engine", {}), ("path-engine", {"engine_binary": path_bin})):
    print(f"--- {label}")
    with AgentContext(str(proj), task="probe", **kwargs) as ctx:
        print("capabilities", sorted(ctx.capabilities))
        for tool in HERDR_TOOLS:
            try:
                ctx.call(tool, {"action": "status"})
                print(tool, "OK")
            except Exception as exc:
                print(tool, type(exc).__name__, str(exc)[:120])
```

Ausgabe:

```
python 3.14.7
sdk 1.1.0 | engine wheel 3.10.1
pinned engine 3.10.1
PATH lean-ctx /home/tholo/.cargo/bin/lean-ctx sha256 certified: False
--- wheel-engine
capabilities ['ctx_compose', 'ctx_glob', 'ctx_read', 'ctx_search', 'ctx_symbol', 'ctx_tree']
ctx_agent UnsupportedCapabilityError Engine did not negotiate capability: ctx_agent
ctx_session UnsupportedCapabilityError Engine did not negotiate capability: ctx_session
ctx_handoff UnsupportedCapabilityError Engine did not negotiate capability: ctx_handoff
ctx_knowledge UnsupportedCapabilityError Engine did not negotiate capability: ctx_knowledge
--- path-engine
(dieselben sechs Werkzeuge, dieselben vier Ablehnungen)
```

## 7. Nachträge in den alten Specs

Alle drei sind eingetragen, die ersten beiden mit dem Commit dieses Specs
(`6dfb9a9`), der dritte mit seiner Überarbeitung — ein Plan hat hier nichts mehr zu
tun. Die Befunde dort bleiben stehen, wie beim Nachtrag vom 2026-09-03:

- `2026-09-02-leanctx-sdk-evaluation.md`: eine Statuszeile unter dem Kopf, mit
  Verweis auf Abschnitt 6.
- `2026-09-03-lean-herdr-auftragslog-design.md`: ein Hinweis an der §3-Zeile „SDK
  1.1.0 ist nicht veröffentlicht" und am §11-Punkt „Kein Einsatz der
  `leanctx-sdk`", jeweils mit Verweis auf 6.2.
- `2026-09-04-lean-herdr-rollenmodelle-und-katalog-design.md`: ein Nachtrag an
  „Feld für Feld" (`:455`), mit Verweis auf 3.4 — eingetragen mit der
  Überarbeitung dieses Specs nach dem Spec-Review.

## 8. Was dieser Entwurf NICHT tut

- **Kein gemeinsamer Helfer** für atomares Schreiben oder den Seam-Gürtel
  (Abschnitt 3).
- **Keine Verhaltensänderung an `dispatch orchestrator`** (Befund 5).
- **Kein toleranter Leser** für ein kaputtes Overlay: ein Tippfehler darin bleibt
  ein Fehler, wie das README verspricht — *„reported — never silently reset"*.
- **Kein Einbau der `leanctx-sdk`**, keine neue Abhängigkeit (6.3).
- **Kein Komplexitäts-Refactor.** `_clears` liegt mit cc=26 über der Schwelle; keiner
  der Fixes berührt es, also bleibt es. `dispatch.py`, das größte Modul, wird nicht
  angefasst.
- **Kein Formatieren von `docs/`** (3.0): die Mess-Skripte in den Specs sind Belege.
