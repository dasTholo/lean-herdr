@lean-md
consumer: ai
crp: compact

@var test_cmd default="uv run pytest -q" desc="project test runner command"
@var lint_cmd default="uv run ruff check ." desc="project lint gate"
@import .lean-ctx/lean-md/plan-recipes /

@define ids_before(label)
<!-- Freeze the collected test IDs before a pass -->
Run:
    S="${TMPDIR:-/tmp}/lean-herdr-ids"; mkdir -p "$S"   # Scratchpad, nie das Repo
    uv run pytest -q --collect-only 2>&1 | grep '::' | sort > "$S/ids-{{ label }}-before.txt"
    grep -c '' "$S/ids-{{ label }}-before.txt"
@define-end

@define ids_after(label)
<!-- Prove the pass lost no test: every removed ID has exactly one added counterpart -->
Run:
    S="${TMPDIR:-/tmp}/lean-herdr-ids"
    uv run pytest -q --collect-only 2>&1 | grep '::' | sort > "$S/ids-{{ label }}-after.txt"
    diff "$S/ids-{{ label }}-before.txt" "$S/ids-{{ label }}-after.txt"
— Expected: gleich viele `<`- wie `>`-Zeilen, jede `<`-Zeile hat genau ein `>`-Gegenstück
  in derselben Datei, keine `<`-Zeile steht allein. Eine alleinstehende `<`-Zeile ist ein
  verlorener Test, eine überzählige `>`-Zeile ein doppelt angelegter.
  **Die Integrationstests sieht dieser Vergleich nicht:** `--collect-only` folgt
  `addopts = "-m 'not integration'"`. Für sie bürgt die Zahl hinter `deselected` im
  Testlauf desselben Tasks — `7` bis Task 11, `10` ab Task 12.
@define-end

@define de_scan(paths)
<!-- German token scan over the touched paths -- the per-task language gate -->
Run:
    uv run python -c '
    import re, sys
    W = set("""aber alle allen als auch auf aus bei beim bereits damit dann das dass dem den
    denn der des deshalb diese diesem diesen dieser dieses doch dort durch ein eine einem
    einen einer eines etwas für fuer ganz gegen gibt haben hier ich ihm ihr ihre immer ist
    jede jeden jeder jedes kann kein keine keinen können koennen mehr mit muss müssen muessen
    nach nicht nichts nie noch nur oben oder ohne schon sehr sein seine sich sie sind soll
    sollen sondern sonst statt steht stehen über ueber und unser unten viel vom von wäre waere
    weil weiter welche wenn werden wie wieder wir wird wurde würde wuerde zum zur zwischen zwar
    absender anker antwort anzahl aufgabe ausführen ausfuehren bricht datei dateien eintrag
    einträge eintraege ergebnis fällt faellt fehler felder fertig frist gefunden gehört gehoert
    gekürzt gekuerzt gescheitert gesehen grün gruen grund hängt haengt jetzt jüngster juengster
    kandidaten kaputt kern kontext läuft laeuft liste löschen loeschen möglich moeglich nachricht
    nachrichten nächste naechste nanosekunden notiz öffnen oeffnen pfad pfade projekt prüfen
    pruefen quelle rahmen roh schlüssel schluessel schritte später spaeter treffer ungültig
    ungueltig vorfahren vorhanden während waehrend wert werte zeile zeilen zeit ziel zurück
    zurueck""".split())
    bad = 0
    for p in sys.argv[1:]:
        for i, line in enumerate(open(p, encoding="utf-8", errors="replace"), 1):
            hits = sorted({w for w in re.findall(r"[A-Za-zÄÖÜäöüß]+", line.lower()) if w in W})
            if hits:
                bad += 1
                print(f"{p}:{i}: {hits}")
    sys.exit(1 if bad else 0)
    ' {{ paths }}
— Expected: keine Ausgabe, exit 0. Jeder Treffer wird übersetzt — oder er ist ein
  geschützter String nach §4 der Spec und wandert mit einer Zeile Begründung in die
  Ausnahmeliste von `tests/test_language.py`.
@define-end

# lean-herdr — Englisch außerhalb `docs/` und Abschluss des Plugins

Quelle: `docs/specs/2026-09-02-lean-herdr-englisch-und-plugin-design.md`.
Render je Task:
`lean-md render docs/lean-md/plans/2026-09-02-lean-herdr-englisch-und-plugin.lmd.md --phase task-N`.

## Goal

Zwei Stränge, ein Plan, weil der eine den anderen sonst zurückdreht.

**Strang A (Task 1-8):** alles außerhalb `docs/` wird englisch — Bezeichner,
Kommentare, Docstrings, Testnamen, Assertion-Meldungen. Kein Verhalten ändert sich.
`tests/test_language.py` macht die Regel danach maschinell durchsetzbar.

**Strang B (Task 9-12):** die drei offenen Tasks des Vorgängerplans
`docs/lean-md/plans/2026-09-01-lean-herdr.lmd.md` — `digest.py`, `handlers.py`, der
opencode-Policy-Adapter — plus die Rückholung von `leanctx.py`, auf dem `handlers.py`
vollständig aufbaut. Ihr Plan-Code steht hier **bereits übersetzt** und gegen die
heutigen Module geprüft; niemand schreibt aus dem Vorgängerplan ab.

**Task 13:** Buchhaltung — `AGENTS.md`, Einfrier-Vermerk im Vorgängerplan,
Richtigstellung zweier überholter Spec-Absätze.

## Architecture

```
Strang A — je Task Produktionsdatei und ihr Test zusammen, ein Commit
  1  bus.py       + test_bus_parse_registry.py, test_bus_canonical_root.py
  2  export.py    + test_export.py
  3  join.py      + test_join.py
  4  herdr.py     + test_herdr.py
  5  worktree.py  + test_worktree.py
  6  config.py, __main__.py + test_config.py, test_config_files.py, test_manifest.py
  7  Restbestand: dispatch.py, __init__.py, doubles.py, test_tool_profile.py,
     herdr-plugin.toml, opencode.jsonc, pyproject.toml, .config/wt.toml, bin/herdr-dispatch
  8  tests/test_language.py                                          NEU

Strang B — die offenen Tasks des Vorgängerplans, übersetzt
  9  lean_herdr/digest.py   + tests/test_digest.py                   NEU
 10  lean_herdr/leanctx.py  + tests/test_leanctx.py    aus 72dee2f^ zurückgeholt
 11  lean_herdr/handlers.py + tests/test_handlers.py                 NEU
 12  .opencode/plugins/lean-ctx-policy.js + tests/test_policy_adapter.py  NEU

 13  AGENTS.md, 2026-09-01-lean-herdr.lmd.md, zwei Spec-Absätze
```

Gemessener Ausgangsstand (2026-09-02, Branch `feat/lean-herdr`):
`238 passed, 7 deselected`, `ruff check` sauber, 27 versionierte Dateien außerhalb
`docs/` tragen deutsche Prosa.

## Gemessene Abweichungen zur Spec

Fünf Befunde aus der Vermessung dieses Plans. Sie ändern den Umfang nicht, aber sie
korrigieren Annahmen, auf die ein Implementer sonst hereinfällt.

| Spec sagt | Gemessen |
|---|---|
| §2: `__main__.py:41` importiert `lean_herdr.handlers`, „jedes Subkommando endet im `ModuleNotFoundError`" | Der Import steht **innerhalb** des `try` mit `except Exception`. Jedes Subkommando endet mit **exit 0** und einer stderr-Zeile; `test_manifest.py::test_main_ueberlebt_ein_fehlendes_handlers_modul` (ab Task 6 `test_main_survives_a_missing_handlers_module`) nagelt genau das fest. Task 11 macht die Subkommandos wirksam, es repariert keinen Absturz. |
| §6: „Die Produktionsnamen sind dort bereits englisch" | Nur die **öffentlichen** Namen. `digest.py` trägt deutsche Modulkonstanten und Locals (`MAX_HANDOFF_ZEILEN`, `RAHMEN`, `COMPRESSION_ZEILE`, `TASK_ZEILE`, `FINDINGS_ZEILE`, `kern`, `zeilen`, `gekuerzt`, `treffer`, `roh`, `anzahl`), `leanctx.py` `CtxAntwort`/`FEHLER_PRAEFIXE`/`LEDGER_ZEILE`. Das Abschreiben ist eine **vollständige** Übersetzung, nicht nur eine der Testnamen. |
| §5/§10: „Anzahl unverändert" gilt für alle A-Tasks | Task 8 legt `tests/test_language.py` an und **muss** die Anzahl erhöhen (238 → 241). Die Regel gilt für Task 1-7; für Task 8 und ab Strang B gilt allein: kein Test verschwindet. |
| §2: „26 Dateien ausserhalb `docs/` tragen deutsche Prosa" | **27.** Der Token-Scan findet 25 Dateien plus die beiden eingefrorenen Fixtures. Ohne Folge für den Umfang — Task 1-7 nennen jede Datei beim Namen —, aber die Zahl in der Spec ist zu klein. |
| §5, A8: Scan „mit Wortgrenzen" | `\b` trennt `parse_zeit` **nicht** (`_` ist ein Wortzeichen). Der Scan tokenisiert deshalb auf `[A-Za-zÄÖÜäöüß]+` — also auch über `_` hinweg. Das fängt Bezeichnersegmente *und* löst das `die`-in-`diet`-Problem, gegen das die Wortgrenze gedacht war. |

## Vier Defekte im geerbten Plan-Code — gemessen und hier bereits behoben

Der Code der Vorgänger-Tasks 14/15/16 wurde nicht abgeschrieben, sondern extrahiert
und gegen den heutigen Baum **ausgeführt**. Dabei fielen vier Fehler an, die ein
wörtliches Abschreiben in einen roten Testlauf geführt hätten. Sie stehen in diesem
Plan bereits korrigiert; die inhaltlichen Korrekturen tragen je einen Kommentar an
Ort und Stelle.

| Defekt | Wirkung beim Abschreiben |
|---|---|
| `test_pane_detected_…` prüfte `called_with("--pane", "w2:p2", …)` | `herdr.report_metadata()` schreibt die ID **positional** (gemessen gegen Herdr 0.8.2, Docstring sagt es ausdrücklich). Die Assertion war nie erfüllbar → `AssertionError`. |
| `test_die_cwd_geht_durch_canonical_root` entpackte `(call,) = [c for c in l_proc.calls if "--project-root" in c]` | `_context()` setzt **drei** Aufrufe ab — `session_resume`, `handoff_list`, `handoff_show`. → `ValueError: too many values to unpack (expected 1, got 3)`. Die Ersatzform prüft, dass **alle drei** denselben kanonischen Root tragen, und ist damit strenger als das Original. |
| `digest.py` benutzte `re.M` | `ruff` meldet `FURB167` → das Qualitätstor `uv run ruff check .` wäre rot. Jetzt `re.MULTILINE`, wie es `leanctx.py` ohnehin schon tat. |
| `test_policy_adapter.py` rief `subprocess.run(...)` zweimal ohne `check=` | `ruff` meldet `PLW1510` → dasselbe Tor rot. Jetzt `check=False`, wie `tests/test_manifest.py` es bereits hält. |

Gemessen im Trockenlauf über einer Repo-Kopie: nach den Korrekturen laufen
`test_digest.py` (6), `test_leanctx.py` (13), `test_handlers.py` (13) und
`test_policy_adapter.py` (4 + 3 Integration) grün, und `ruff check` ist auf allen acht
Dateien sauber. Der JS-Adapter lädt unter `node` und meldet alle drei Hookpunkte.

## Global Constraints

- **Task 1-7 ändern kein Verhalten.** Umbenennungen, Kommentare, Docstrings,
  Testnamen, Assertion-Meldungen. Kein Refactoring darüber hinaus, keine Behebung
  der fünf Funktionen über Komplexitätsschwelle 15 (`export.find_error` 22,
  `dispatch.dispatch` 18, `bus.parse_registry` 17, `dispatch.wait_for_agent_id` 16,
  `export.opencode_messages` 16).
- **String-Literale werden nie übersetzt** — außer sie sind unverkennbar Prosa, die
  ein Mensch zu Gesicht bekommt (stderr-Meldung, Assertion-Text, Plugin-Titel).
  Unantastbar: Protokoll-Token (`VERDIKT:`, `RESULT:`, `REJECT:` — `dispatch.VERDICT_RE`
  ist die Autorität), Registry- und JSON-Schlüssel (`scratchpad`, `pid`, `expires_at`,
  `repo_root`), CLI-Flags und Unterkommandos, Umgebungsvariablennamen und **Testdaten**
  (`parse_time("morgen frueh")` ist die Probe „etwas, das `fromisoformat` nicht parst").
  Im Zweifel bleibt der String stehen.
- **`tests/fixtures/registry.sample.json` und `tests/fixtures/tasks.sample.json`
  bleiben byteidentisch.** Prüfbar: `git diff --stat` nennt sie in keinem Task.
- **Nachweispflicht Task 1-7:** `238 passed, 7 deselected` unverändert, **und** der
  Vergleich der gesammelten Test-IDs zeigt eine reine 1:1-Umbenennung (siehe
  `ids_before`/`ids_after`). Ab Task 8 wächst die Zahl; es verschwindet nie ein Test.
- **Reihenfolge:** Task 6 vor jedem B-Task · Task 9 und 10 vor Task 11 · Task 8 nach
  Task 7, damit er beim Landen grün ist und danach Strang B bewacht. Task 1-5 sind
  untereinander unabhängig.
- **`@reformat` wird nicht ausgeführt** (übernommene Abweichung beider Vorgängerpläne):
  das Qualitätstor ist `ruff check`, **nicht** `ruff format --check`. Die `gate`-Rezeptur
  gibt den Schritt aus; er wird übersprungen. In Strang A würde der Formatter den Diff
  aufblähen und die Übersetzung unlesbar machen.
- **Strang B schreibt nicht still um.** Der Plan-Code ist älter als der `ctx_task`-Umbau.
  Ein Widerspruch zu den heutigen Modulen wird **gemeldet**, nicht behoben. Zwei sind
  bereits aufgelöst und stehen in den Tasks; ein dritter ist als Befund vermerkt.
- **Non-Goals** (Ablehnungsgrund im Review, kein Versäumnis): Strang C der Spec
  (Stufe-4-Durchlauf mit Merge, Kostenmessung `minimal` vs. `standard`, Beweis des
  `kind="claude"`-Pfades von `session_error()`) — Betriebsdurchläufe mit echten Agenten
  und echten Kosten, eigene Spec. Die Prosa unter `docs/` bleibt deutsch.

@phase "task-1"
## Task 1 (A1): `bus.py` — der einzige deutsche öffentliche Name

**Files:** Modify `lean_herdr/bus.py`, `tests/test_bus_parse_registry.py`,
`tests/test_bus_canonical_root.py`.
**Interfaces:** Renames `lean_herdr.bus.parse_zeit` → `parse_time`. Sonst keine
Signaturänderung.

`parse_zeit` ist der **einzige** deutsche öffentliche Name im Projekt und der einzige,
der eine Modulgrenze kreuzt: fünf Stellen, `bus.py:62`, `bus.py:122`,
`tests/test_bus_parse_registry.py:13,51,54`. Alles andere in diesem Task ist lokal.

@call callers("parse_zeit")

Run: `@refactor` (ctx_refactor) — Symbol `parse_zeit` projektweit zu `parse_time`
umbenennen. Nicht von Hand über fünf Dateien; ein übersehener Aufrufer bricht erst
zur Laufzeit.

Bestehender Code — anchoren, nicht abschreiben:

@read lean_herdr/bus.py mode=anchored
@read tests/test_bus_parse_registry.py mode=anchored
@read tests/test_bus_canonical_root.py mode=anchored

Danach der Rest, per `ctx_patch` über die Anker:

- `_NANOSEKUNDEN` → `_NANOSECONDS`; die Locals `wert` (`bus.py:72`) und `frist`
  (`bus.py:122`) → `value` / `deadline`.
- Alle deutschen Kommentare und Docstrings in `bus.py`.
- Testkonstanten `PROJEKT` → `PROJECT`, `JETZT` → `NOW` in
  `tests/test_bus_parse_registry.py`.
- Alle deutschen Testnamen beider Testdateien. `test_eingefrorene_probe_hat_die_erwartete_form`
  wird `test_the_frozen_sample_has_the_expected_shape` — die Spec nennt ihn bereits so.
- **Assertion-Meldungen werden übersetzt.** `"projektlose Nachrichten (project_root=null)
  duerfen nicht wegfallen"` sieht ein Mensch beim Fehlschlag; das ist Prosa.

**Was stehen bleibt** — jeder Verstoß hier ist ein stiller Testschaden:

- `parse_time("morgen frueh")` in `test_bus_parse_registry.py`. Das ist die Probe
  „etwas, das `fromisoformat` nicht parsen kann". Ein wohlmeinendes `"2026-01-01"`
  dreht den Test lautlos um.
- Der **Wert** `"scratchpad"` von `MESSAGES_KEY` und jeder andere Registry-Schlüssel
  (`pid`, `expires_at`, `project_root`, `from_agent`, `task_id`).
- Die synthetischen Nachrichtentexte `"nein"`, `"ja"`, `"treffer"`,
  `"falscher absender"`, `"falsche aufgabe"` in den Inline-Dicts. Das ist Nutzlast,
  die der Code vergleicht — keine Prosa.
- `tests/fixtures/registry.sample.json` wird **nicht angefasst**.

### Verify & Close (feste Reihenfolge in jedem A-Task)

@call ids_before(a1)

… Übersetzung anwenden …

@call verify("lean_herdr/bus.py tests/test_bus_parse_registry.py tests/test_bus_canonical_root.py")
@call de_scan(lean_herdr/bus.py tests/test_bus_parse_registry.py tests/test_bus_canonical_root.py)
@call ids_after(a1)

Run: git diff --stat — Expected: `tests/fixtures/registry.sample.json` steht **nicht** in der Liste.

@call gate("lean_herdr/bus.py tests/test_bus_parse_registry.py tests/test_bus_canonical_root.py")

Run: {{ var test_cmd }} — Expected: `238 passed, 7 deselected`.

@call commit("lean_herdr/bus.py tests/test_bus_parse_registry.py tests/test_bus_canonical_root.py", "refactor(bus): English identifiers, comments and test names")
@call remember_decision("lean-herdr: bus.parse_zeit heisst jetzt parse_time -- der einzige deutsche oeffentliche Name des Projekts, fuenf Stellen. Der WERT von MESSAGES_KEY bleibt 'scratchpad'; parse_time('morgen frueh') bleibt als unparsbare Probe stehen; tests/fixtures/registry.sample.json ist eine eingefrorene Aufnahme und wird nie uebersetzt")
@phase-end

@phase "task-2"
## Task 2 (A2): `export.py`

**Files:** Modify `lean_herdr/export.py`, `tests/test_export.py`.
**Interfaces:** Keine. Nur Locals, Kommentare, Docstrings, Testnamen.

Reine Lokalarbeit — `export.py` hat keinen deutschen öffentlichen Namen. Die deutschen
Locals sitzen dicht: `roh` (`:24`, `:90`, `:130`), `zeile` (`:94-95`), `daten`
(`:99`, `:132`), `pfad` (`:113`, `:117`), `zeilen` (`:121`).

@read lean_herdr/export.py mode=anchored
@read tests/test_export.py mode=anchored

@call patch("lean_herdr/export.py", "deutsche Locals, Kommentare und Docstrings")
@call patch("tests/test_export.py", "deutsche Testnamen, Docstrings und Assertion-Meldungen")

**Was stehen bleibt:** die Schlüsselnamen der opencode-SQLite-Ablage
(`message`, `session_id`, `data`, `time_created`) und jeder JSONL-Feldname —
`export.py` vergleicht sie, ein Mensch sieht sie nie.
`find_error` behält seine kognitive Komplexität 22; sie zu senken ist Non-Goal.

### Verify & Close

@call ids_before(a2)
@call verify("lean_herdr/export.py tests/test_export.py")
@call de_scan(lean_herdr/export.py tests/test_export.py)
@call ids_after(a2)
@call gate("lean_herdr/export.py tests/test_export.py")

Run: {{ var test_cmd }} — Expected: `238 passed, 7 deselected`.

@call commit("lean_herdr/export.py tests/test_export.py", "refactor(export): English identifiers, comments and test names")
@phase-end

@phase "task-3"
## Task 3 (A3): `join.py` — zwei private Namen und ein öffentlicher Parameter

**Files:** Modify `lean_herdr/join.py`, `tests/test_join.py`.
**Interfaces:** Renames `join._stat_felder` → `_stat_fields`,
`join._juengster_agent_id` → `_newest_agent_id`, und den **öffentlichen** Parameter
`process_ancestors(pid, proc_root="/proc", max_schritte=32)` → `max_steps=32`.

Die größte deutsche Fläche des Projekts (35 + 17 Treffer). Der Parameter
`max_schritte` steht in einer öffentlichen Signatur, wird aber von keinem Aufrufer
benannt übergeben — die Umbenennung bricht deshalb nichts.

@call callers("process_ancestors")

@read lean_herdr/join.py mode=anchored
@read tests/test_join.py mode=anchored

Zu übersetzen, mit den gemessenen Stellen:

- `_stat_felder` (`:43`, `:67`, `:83`) → `_stat_fields`
- `_juengster_agent_id` (`:128`, `:163`, `:177`) → `_newest_agent_id`
- `max_schritte` (`:93`, `:111` im Docstring, `:118`) → `max_steps`
- Locals: `gesehen` (`:116`) → `seen`, `juengster` (`:132`) → `newest`,
  `kandidaten` (`:128`, `:158`) → `candidates`, `gefunden` (`:163`) → `found`,
  `vorfahren_kandidaten` (`:177`) → `ancestor_candidates`
- alle Kommentare, Docstrings, Testnamen und Assertion-Meldungen

### Verify & Close

@call ids_before(a3)
@call verify("lean_herdr/join.py tests/test_join.py")
@call de_scan(lean_herdr/join.py tests/test_join.py)
@call ids_after(a3)
@call review_change()
@call gate("lean_herdr/join.py tests/test_join.py")

Run: {{ var test_cmd }} — Expected: `238 passed, 7 deselected`.

@call commit("lean_herdr/join.py tests/test_join.py", "refactor(join): English identifiers, comments and test names")
@phase-end

@phase "task-4"
## Task 4 (A4): `herdr.py`

**Files:** Modify `lean_herdr/herdr.py`, `tests/test_herdr.py`.
**Interfaces:** Keine. Das Local `ziel` in `pane_split` (`:110`) → `target`.

`herdr.py` trägt die dichteste Kommentarschicht des Projekts (27 Treffer): jede
gemessene Eigenheit von Herdr 0.8.2 steht dort als Begründung. **Die Begründungen
wandern mit, sie werden nicht gekürzt.** Wer „KEIN --json anhaengen: Herdr 0.8.2
kennt den Schalter nicht" zu „no --json" eindampft, wirft den Grund weg, und der
nächste Leser fügt das Flag wieder ein.

@read lean_herdr/herdr.py mode=anchored
@read tests/test_herdr.py mode=anchored

@call patch("lean_herdr/herdr.py", "deutsche Kommentare, Docstrings und das Local ziel")
@call patch("tests/test_herdr.py", "deutsche Testnamen, Docstrings und Assertion-Meldungen")

**Was stehen bleibt:** `SOURCE = "lean.herdr"`, jedes CLI-Argument (`pane`, `split`,
`--no-focus`, `--direction`, `report-metadata`, `--source`, `--token`) und die
Hinweiskürzel `H2`, `H4`, `H8`, `H9`, `B12` — sie zeigen auf Befunde der Spec.

### Verify & Close

@call ids_before(a4)
@call verify("lean_herdr/herdr.py tests/test_herdr.py")
@call de_scan(lean_herdr/herdr.py tests/test_herdr.py)
@call ids_after(a4)
@call gate("lean_herdr/herdr.py tests/test_herdr.py")

Run: {{ var test_cmd }} — Expected: `238 passed, 7 deselected`.

@call commit("lean_herdr/herdr.py tests/test_herdr.py", "refactor(herdr): English comments, docstrings and test names")
@phase-end

@phase "task-5"
## Task 5 (A5): `worktree.py`

**Files:** Modify `lean_herdr/worktree.py`, `tests/test_worktree.py`.
**Interfaces:** Keine.

@read lean_herdr/worktree.py mode=anchored
@read tests/test_worktree.py mode=anchored

Gemessene Locals: `eintrag` (`:53`) → `entry`, `pfad` (`:83`, `:135`, `:146`, `:151`)
→ `path`, `ergebnis` (`:97`) → `result`, `liste` (`:130`) → `listing`,
`vorhanden` (`:133`) → `existing`, `geoeffnet` (`:97`) → `opened`. Dazu alle
Kommentare, Docstrings, Testnamen und Assertion-Meldungen.

**Achtung, gleichnamiger Schlüssel:** `ergebnis.get("open_workspace_id")` und
`data.get("path")` lesen Herdr-JSON. Der Local heißt danach `result`, der
**Schlüssel** `"path"` bleibt `"path"`.

### Verify & Close

@call ids_before(a5)
@call verify("lean_herdr/worktree.py tests/test_worktree.py")
@call de_scan(lean_herdr/worktree.py tests/test_worktree.py)
@call ids_after(a5)
@call gate("lean_herdr/worktree.py tests/test_worktree.py")

Run: {{ var test_cmd }} — Expected: `238 passed, 7 deselected`.

@call commit("lean_herdr/worktree.py tests/test_worktree.py", "refactor(worktree): English identifiers, comments and test names")
@phase-end

@phase "task-6"
## Task 6 (A6): `config.py` und `__main__.py` — Prosa, die ein Test festnagelt

**Files:** Modify `lean_herdr/config.py`, `lean_herdr/__main__.py`,
`tests/test_config.py`, `tests/test_config_files.py`, `tests/test_manifest.py`.
**Interfaces:** Keine. `Config`, `HANDLERS` und `main()` behalten Namen und Form.

**Dieser Task muss vor jedem B-Task liegen** — Task 9, 11 und 12 bauen auf `Config`
und `HANDLERS` auf.

Der konkrete Fall der Prosa-Regel: die stderr-Texte von `__main__.py` sind Prosa für
den Betreiber (sie landen in `herdr plugin log list --plugin lean.herdr`) **und** ein
Test nagelt sie fest. Text und Erwartung wandern im **selben** Commit:

| `__main__.py` | Erwartung |
|---|---|
| `f"[lean.herdr] unbekannter Subcommand: {args[:1]}\n"` → `f"[lean.herdr] unknown subcommand: {args[:1]}\n"` | `test_manifest.py`: `"unbekannter Subcommand"` → `"unknown subcommand"` |
| `f"[lean.herdr] {args[0]} fehlgeschlagen: {exc}\n"` → `f"[lean.herdr] {args[0]} failed: {exc}\n"` | `test_manifest.py`: `"[lean.herdr] inject fehlgeschlagen"` → `"[lean.herdr] inject failed"` |

@read lean_herdr/__main__.py mode=anchored
@read tests/test_manifest.py mode=anchored
@read lean_herdr/config.py mode=anchored
@read tests/test_config.py mode=anchored
@read tests/test_config_files.py mode=anchored

Weiter zu übersetzen: der ausführliche Kommentar in `main()` über die späte Auflösung
**über den Namen** — er ist der Grund, warum `test_main_catches_every_exception_and_ends_with_0`
aus Task 11 überhaupt etwas prüft. Er wandert vollständig mit. In `test_manifest.py`
außerdem `GUELTIGE_EVENTS` → `VALID_EVENTS` und das Local `eintrag`/`zeilen`/`liste`.

**Zwei Testnamen werden hier festgelegt, weil spätere Tasks sie zitieren** — die
übrigen wählt der Implementer frei:

| heute | danach |
|---|---|
| `test_main_ueberlebt_ein_fehlendes_handlers_modul` | `test_main_survives_a_missing_handlers_module` |
| `test_unbekannter_subcommand_ist_kein_absturz` | `test_an_unknown_subcommand_is_not_a_crash` |

Der erste wird in Task 13 in eine Spec geschrieben, der zweite ist der Grund, warum
Task 11 seinen eigenen `test_unbekannter_subcommand_bricht_nicht` streicht.

**Was stehen bleibt:** jeder Subcommand-Schlüssel von `HANDLERS`
(`workspace-created`, `pane-detected`, `status-changed`, `inject`, `bootstrap`) und
jeder Eventname in `VALID_EVENTS` (`pane.agent_detected`, …). Sie stehen wörtlich so
in `herdr-plugin.toml`; eine Übersetzung entkoppelt Manifest und Dispatch lautlos.
Ebenso jeder `HERDR_*`- und `LEAN_HERDR_*`-Umgebungsvariablenname.

### Verify & Close

@call ids_before(a6)
@call verify("lean_herdr/config.py lean_herdr/__main__.py tests/test_config.py tests/test_config_files.py tests/test_manifest.py")
@call de_scan(lean_herdr/config.py lean_herdr/__main__.py tests/test_config.py tests/test_config_files.py tests/test_manifest.py)
@call ids_after(a6)
@call gate("lean_herdr/config.py lean_herdr/__main__.py tests/test_config.py tests/test_config_files.py tests/test_manifest.py")

Run: {{ var test_cmd }} — Expected: `238 passed, 7 deselected`.

@call commit("lean_herdr/config.py lean_herdr/__main__.py tests/test_config.py tests/test_config_files.py tests/test_manifest.py", "refactor(plugin): English identifiers, stderr texts and test names")
@call remember_decision("lean-herdr: die stderr-Texte von __main__.py heissen jetzt 'unknown subcommand' und '<sub> failed'; tests/test_manifest.py prueft genau diese Zeichenketten. Die HANDLERS-Schluessel und die Eventnamen sind KEINE Prosa -- sie stehen woertlich in herdr-plugin.toml")
@phase-end

@phase "task-7"
## Task 7 (A7): der Restbestand — Abschluss-Scan über den ganzen Baum

**Files:** Modify `lean_herdr/dispatch.py`, `lean_herdr/__init__.py`,
`tests/doubles.py`, `tests/test_tool_profile.py`, `herdr-plugin.toml`,
`opencode.jsonc`, `pyproject.toml`, `.config/wt.toml`, `bin/herdr-dispatch`.
Prüfen (voraussichtlich schon sauber): `tests/test_dispatch*.py`, `README.md`,
`roles/*.md`, `AGENTS.md`, `CLAUDE.md`, `herdr-api.schema.json`,
`.config/lean-herdr.toml`, `.zed/settings.json`, `tests/test_settings.py`,
`tests/test_tasks*.py`, `tests/test_roles.py`, `tests/test_role_prohibitions.py`.
**Interfaces:** Keine.

Nach diesem Task ist der Baum außerhalb `docs/` deutschfrei — außer den zwei
eingefrorenen Fixtures.

**1. Die frische Regression aus dem `ctx_task`-Lauf.** `dispatch.py:303-307` trägt
`eintrag` und `pfad` in einer sonst vollständig englischen Datei:

@read lean_herdr/dispatch.py mode=lines:300-307

`eintrag` → `entry`, `pfad` → `path`. Der Docstring darüber ist bereits englisch.

**2. Der Rest, mit den gemessenen Stellen:**

| Datei | Was |
|---|---|
| `lean_herdr/__init__.py` | der Modul-Docstring `"""lean-herdr — Orchestrator-Workspace zwischen Herdr und lean-ctx."""` |
| `tests/doubles.py` | Docstrings von `FakeProc`, `called_with`, das Local `antwort`/`praefix` in `_stdout` und `__call__` |
| `tests/test_tool_profile.py` | Modul-Docstring, Docstrings, `namen` → `names`, die Assertion-Meldungen und der `pytest.skip`-Text |
| `herdr-plugin.toml` | `description`, beide `title`, die `description` der Aktion `bootstrap` und alle Kommentare. **Prosa für den Betreiber — Herdr zeigt sie in der Oberfläche.** Kein Test nagelt sie fest. |
| `opencode.jsonc` | alle Kommentare und die `description` des Reviewer-Agenten |
| `pyproject.toml` | `[project].description`, die `per-file-ignores`-Begründung, die `addopts`-Begründung und der Markertext `"integration: braucht echte …"` — den zeigt `pytest --markers` |
| `.config/wt.toml` | alle Kommentare (W2-Begründung, pre-merge-Testtor) |
| `bin/herdr-dispatch` | der Modul-Docstring `"""Zuteilung an einen Arbeiter-Agenten. …"""` |

@read tests/doubles.py mode=anchored
@read tests/test_tool_profile.py mode=anchored
@read herdr-plugin.toml mode=anchored
@read opencode.jsonc mode=anchored
@read pyproject.toml mode=anchored
@read .config/wt.toml mode=anchored
@read bin/herdr-dispatch mode=anchored

**Was stehen bleibt:** jeder `id`, jedes `on`, jedes `command`-Element und jede
`contexts`-Liste in `herdr-plugin.toml`; jeder Konfigurationsschlüssel in
`opencode.jsonc` und `pyproject.toml`; der Markername `integration` selbst.

**3. Der Abschluss-Scan über alles.** Er ist das eigentliche Tor dieses Tasks:

@call de_scan($(git ls-files | grep -v '^docs/' | grep -v '^tests/fixtures/'))

— Expected: keine Ausgabe. Bleibt ein Treffer übrig, gehört er entweder übersetzt oder
in die Ausnahmeliste von Task 8, mit einer Zeile Begründung.

### Verify & Close

@call ids_before(a7)
@call verify("lean_herdr tests bin herdr-plugin.toml opencode.jsonc pyproject.toml .config")
@call ids_after(a7)

Run: git diff --stat — Expected: keine der beiden Dateien unter `tests/fixtures/`.

@call gate("lean_herdr/dispatch.py lean_herdr/__init__.py tests/doubles.py tests/test_tool_profile.py herdr-plugin.toml opencode.jsonc pyproject.toml .config/wt.toml bin/herdr-dispatch")

Run: {{ var test_cmd }} — Expected: `238 passed, 7 deselected`.

**Niemals `git add .` in diesem Task.** Der Arbeitsbaum trägt zwei unversionierte
Dateien: `scratch.md` (nicht in `.gitignore`, 17 deutsche Zeilen) und dieses
Plandokument. `git add .` zöge `scratch.md` in `git ls-files` — und damit in den
Umfang von `tests/test_language.py`, das im nächsten Task angelegt wird und dann beim
Landen rot wäre. Genau die Datei, die Task 8 als Begründung für den `git ls-files`-Umfang
nennt. Deshalb die Pfadliste, nicht der Punkt:

@call commit("lean_herdr/dispatch.py lean_herdr/__init__.py tests/doubles.py tests/test_tool_profile.py herdr-plugin.toml opencode.jsonc pyproject.toml .config/wt.toml bin/herdr-dispatch", "refactor: English everywhere outside docs/")

Run: git status --short — Expected: `scratch.md` steht weiterhin als `??` da,
unversioniert. Steht es als `A`, ist der Commit zurückzunehmen.

@call remember_decision("lean-herdr: der Baum ausserhalb docs/ ist seit 2026-09-02 vollstaendig englisch. Zwei Ausnahmen und nur zwei: tests/fixtures/registry.sample.json und tests/fixtures/tasks.sample.json sind eingefrorene Aufnahmen echter lean-ctx-Daten und bleiben deutsch")
@phase-end

@phase "task-8"
## Task 8 (A8): `tests/test_language.py` — die Regel wird durchsetzbar

**Files:** Create `tests/test_language.py`.
**Interfaces:** Produces `GERMAN_WORDS`, `EXCEPTIONS`,
`german_hits(text) -> set[str]`, `tracked_text_files() -> list[Path]`.

Das Projekt schützt die Rollentexte bereits durch gezielte Tests statt durch Disziplin
(`tests/test_role_prohibitions.py`, 13 Verbotssätze). Dieser Test ist dessen Nachfolger
für den Code. Er landet **zuletzt in Strang A**, damit er beim Landen grün ist und
danach Strang B bewacht.

Drei Festlegungen tragen ihn:

1. **Der Umfang ist `git ls-files`, nicht das Dateisystem.** Außerhalb `docs/` liegen
   auch `.pytest_cache/v/cache/nodeids` (29 deutsche Test-IDs, bei **jedem** Lauf neu
   geschrieben), `__pycache__/*.pyc`, `scratch.md`, `.lean-ctx/`, `.claude/skills/` und
   `uv.lock`. Ein Scan über das Dateisystem wäre nach dem ersten `pytest` rot.
2. **Tokenisiert wird auf `[A-Za-zÄÖÜäöüß]+`, also auch über `_` hinweg.** `\b` trennt
   `parse_zeit` nicht — `_` ist ein Wortzeichen. Die Tokenisierung fängt
   Bezeichnersegmente *und* löst das Problem, gegen das die Wortgrenze gedacht war
   (`die` schlägt in `diet` nicht mehr an, weil `diet` ein eigenes Token ist).
3. **Die Wortliste ist kuratiert, nicht vollständig.** Englische Homographen fehlen
   bewusst: `die`, `man`, `hat`, `war`, `also`, `still`, `leer`, `probe`, `kind`, `hand`,
   `list`, `mode`, `rest`, `start`. Ein deutsches Wort, das durchrutscht, wird
   nachgetragen — die Liste wächst, sie ist kein Beweis.

`tests/test_language.py` (neu):

    """Everything outside docs/ is English -- enforced, not merely agreed.

    AGENTS.md has demanded it since commit 36fc9f7; the sweep of 2026-09-02 made
    the tree comply. This test keeps it that way.
    """

    import re
    import shutil
    import subprocess
    from pathlib import Path

    import pytest

    ROOT = Path(__file__).resolve().parents[1]

    #: A CURATED list of unambiguous German words -- function words plus the stems
    #: this repository actually produced. English homographs are deliberately
    #: absent: die, man, hat, war, also, still, leer, probe, kind, hand, list,
    #: mode, rest, start. The list grows when a German word slips through; it is
    #: a net, not a proof.
    GERMAN_WORDS = frozenset(
        """
        aber alle allen als auch auf aus bei beim bereits damit dann das dass dem den
        denn der des deshalb diese diesem diesen dieser dieses doch dort durch ein eine
        einem einen einer eines etwas für fuer ganz gegen gibt haben hier ich ihm ihr
        ihre immer ist jede jeden jeder jedes kann kein keine keinen können koennen mehr
        mit muss müssen muessen nach nicht nichts nie noch nur oben oder ohne schon sehr
        sein seine sich sie sind soll sollen sondern sonst statt steht stehen über ueber
        und unser unten viel vom von wäre waere weil weiter welche wenn werden wie wieder
        wir wird wurde würde wuerde zum zur zwischen zwar
        absender anker antwort anzahl aufgabe ausführen ausfuehren bricht datei dateien
        eintrag einträge eintraege ergebnis fällt faellt fehler felder fertig frist
        gefunden gehört gehoert gekürzt gekuerzt gescheitert gesehen grün gruen grund
        hängt haengt jetzt jüngster juengster kandidaten kaputt kern kontext läuft laeuft
        liste löschen loeschen möglich moeglich nachricht nachrichten nächste naechste
        nanosekunden notiz öffnen oeffnen pfad pfade projekt prüfen pruefen quelle rahmen
        roh schlüssel schluessel schritte später spaeter treffer ungültig ungueltig
        vorfahren vorhanden während waehrend wert werte zeile zeilen zeit ziel zurück
        zurueck
        """.split()
    )

    #: Every exception carries its reason. Nothing joins this list silently.
    EXCEPTIONS = {
        # Frozen recordings of real lean-ctx data. Translating them would falsify
        # the measurement that parse_registry() and lean_herdr.tasks rest on --
        # test_the_frozen_sample_has_the_expected_shape pins their shape.
        "tests/fixtures/registry.sample.json": "frozen recording of a real registry",
        "tests/fixtures/tasks.sample.json": "frozen recording of a real task store",
        # This file carries the word list itself.
        "tests/test_language.py": "carries GERMAN_WORDS",
    }

    _TOKEN = re.compile(r"[A-Za-zÄÖÜäöüß]+")


    def german_hits(text: str) -> set[str]:
        """The German words in `text`, tokenised across `_` as well.

        `\\b` would not split `parse_zeit`: `_` is a word character. Splitting on
        letter runs catches identifier segments and keeps `diet` from matching
        `die` at the same time.
        """
        return {w for w in _TOKEN.findall(text.lower()) if w in GERMAN_WORDS}


    def tracked_text_files() -> list[Path]:
        """Versioned files outside docs/, minus the exceptions and binaries.

        git ls-files, never the file system: .pytest_cache/v/cache/nodeids is
        rewritten on EVERY run and carries the German test IDs of whatever ran
        last. A file-system scan would be red right after the first pytest.
        """
        out = subprocess.run(
            ["git", "ls-files"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        ).stdout
        files = []
        for rel in out.splitlines():
            if not rel or rel.startswith("docs/") or rel in EXCEPTIONS:
                continue
            path = ROOT / rel
            try:
                path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue  # binary or unreadable -- nothing to read language from
            files.append(path)
        return files


    @pytest.fixture(scope="module")
    def tracked() -> list[Path]:
        if shutil.which("git") is None:
            pytest.skip("git not installed")
        return tracked_text_files()


    def test_no_german_outside_docs(tracked):
        """AGENTS.md: everything outside docs/ is English."""
        offenders = []
        for path in tracked:
            rel = path.relative_to(ROOT)
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                hits = german_hits(line)
                if hits:
                    offenders.append(f"{rel}:{number}: {sorted(hits)}")
        assert not offenders, "German outside docs/:\n" + "\n".join(offenders)


    def test_the_scan_catches_transliterations():
        """ae/oe/ue/ss forms evade a naive umlaut scan -- they must not evade this one."""
        assert german_hits("Der Pfad wird fuer jeden Eintrag geprueft") >= {
            "der", "pfad", "wird", "fuer", "eintrag",
        }
        assert german_hits("Die Zeilen muessen zurueck") >= {"zeilen", "muessen", "zurueck"}
        assert german_hits("this diet is a die-hard list") == set(), "no English homographs"


    def test_the_scan_reads_tracked_files_only(tracked):
        """A file-system walk would be red after the first pytest run."""
        rels = {str(p.relative_to(ROOT)) for p in tracked}
        assert rels, "git ls-files returned nothing"
        assert not any(r.startswith("docs/") for r in rels)
        assert not any(r.startswith((".pytest_cache/", "__pycache__/")) for r in rels)
        assert not (rels & EXCEPTIONS.keys())
        assert "lean_herdr/bus.py" in rels, "the scan must actually reach the code"

@call tdd(-k the_scan_catches_transliterations)

### Verify & Close

@call ids_before(a8)
@call verify("tests/test_language.py")
@call ids_after(a8)

— Expected: **keine** `<`-Zeile, genau drei `>`-Zeilen. In diesem einen A-Task wächst
die Anzahl; verschwinden darf trotzdem nichts.

@call gate("tests/test_language.py")

Run: {{ var test_cmd }} — Expected: `241 passed, 7 deselected`.

@call commit("tests/test_language.py", "test(language): enforce English outside docs/")
@call remember_decision("lean-herdr: tests/test_language.py setzt die Sprachregel durch. Umfang ist `git ls-files` minus docs/ minus EXCEPTIONS -- nie das Dateisystem, weil .pytest_cache/v/cache/nodeids bei jedem Lauf deutsche Test-IDs neu schreibt. Tokenisiert wird auf [A-Za-zAeOeUeaeoeuess]+, also auch ueber _ hinweg, weil \\b parse_zeit nicht trennt. GERMAN_WORDS ist kuratiert und enthaelt bewusst keine englischen Homographen (die, man, hat, war, also, still, leer, probe)")
@phase-end

@phase "task-9"
## Task 9 (B1): `digest.py` — der Digest wird nicht von Hand gebaut

@call recall_context("lean-herdr Plugin Config state_dir ctx-Token")

**Files:** Create `lean_herdr/digest.py`, `tests/test_digest.py`.
**Interfaces:** Produces
`strip_frame(resume_text) -> str`,
`render_digest(resume_text, handoff_text=None) -> str | None`,
`summary_token(resume_text, max_len=60) -> str | None`.

**`ctx_session action=resume` liefert den Digest fertig** — und zwar als **Klartext**,
nicht als Feldersammlung. Gemessen gegen lean-ctx 3.10.1:

    --- SESSION RESUME (post-compaction) ---
    [COMPRESSION: standard] Dense output. Atomic fact lines, abbreviations, diff-only code.
    Project: lean-herdr
    Task: Modified: 1 file changed, 211 insertions(+), 20 deletions(-) in docs/lean-md/plans
    Key findings: Read 2026-09-01-lean-herdr.lmd.md (4781L); …
    Archives: d87f9bd455c4c365(ctx_read), c5f10c0559312d84(ctx_read), …
    Stats: 104 calls, 1382898 tok saved
    ---

Das ist der Digest. **Er wird übernommen, nicht zerlegt.** Ein Nachbau aus ausgewählten
Feldern — Task, Findings, Decisions — würde Projekt, Archive, Statistik und Ledger
stillschweigend wegwerfen; was der Agent dann sähe, wäre ärmer als das, was lean-ctx
ohnehin schon fertig hingelegt hat. Dieser Task rahmt nur: Rahmenzeilen weg,
Handoff-Referenzen dran.

`ctx_handoff` ergänzt die kuratierten Datei-Referenzen — über `action=list` (der
neueste Ledger steht oben) und dann `action=show` mit dessen `path`. Beides holt der
Aufrufer; hier stehen nur reine Funktionen über Texten, kein I/O.

**Ist der Resume-Text nach dem Entrahmen leer und gibt es keinen Handoff, wird kein
Digest geschrieben und kein Token gesetzt.** Ein frisches Projekt ist der Normalfall,
kein Fehler.

Der Token heißt **`ctx`**, nicht `task`: `herdr-plugin-renamer` belegt `$task` bereits
mit seinem generierten Pane-Namen, und zwei Plugins um denselben Token wären ein
stiller Konflikt.

**Übersetzt gegenüber dem Vorgängerplan** (Bereich 4595-4773): die Modulkonstanten
`MAX_HANDOFF_ZEILEN`/`RAHMEN`/`COMPRESSION_ZEILE`/`TASK_ZEILE`/`FINDINGS_ZEILE`, alle
Locals, alle Docstrings, alle Testnamen, die Digest-Überschrift `# lean-ctx-Kontext`
und der Fallback-Token `"2 Findings"` → `"2 findings"`. Auch die eingefrorene
Resume-Probe im Test ist englisch — sie ist synthetisch, kein festgenagelter Mitschnitt.

`lean_herdr/digest.py` (neu):

    """Context -> digest. Pure functions over text, no I/O.

    The digest arrives FINISHED from `ctx_session resume`. Here it is only
    unframed and extended by the handoff references -- it is never rebuilt from
    fields.
    """

    from __future__ import annotations

    import re

    MAX_HANDOFF_LINES = 12
    TOKEN_MAX = 60

    #: The frame lines of ctx_session resume: `--- SESSION RESUME ... ---` and `---`.
    FRAME = re.compile(r"^-{3,}.*$", re.MULTILINE)

    #: The configuration line is an instruction to the server, not context.
    COMPRESSION_LINE = re.compile(r"^\[COMPRESSION:.*$", re.MULTILINE)

    #: `Task: ...` in the resume text -- the only line that feeds the token.
    TASK_LINE = re.compile(r"^Task:\s*(.+)$", re.MULTILINE)
    FINDINGS_LINE = re.compile(r"^Key findings:\s*(.+)$", re.MULTILINE)


    def strip_frame(resume_text: str) -> str:
        """Drop frame and configuration lines, keep the content.

        Everything else stays VERBATIM -- Project, Archives, Stats and ledger
        lines included, all of which a rebuild would lose.
        """
        without = COMPRESSION_LINE.sub("", FRAME.sub("", resume_text or ""))
        return "\n".join(line for line in without.splitlines() if line.strip()).strip()


    def render_digest(resume_text: str, handoff_text: str | None = None) -> str | None:
        """Markdown digest -- or None when there is nothing to show."""
        core = strip_frame(resume_text)
        handoff = "\n".join(
            line for line in (handoff_text or "").splitlines() if line.strip()
        ).strip()
        if not (core or handoff):
            return None

        lines = ["# lean-ctx context", ""]
        if core:
            lines += [core, ""]
        if handoff:
            capped = handoff.splitlines()[:MAX_HANDOFF_LINES]
            lines += ["## Handoff", *capped, ""]
        return "\n".join(lines).rstrip() + "\n"


    def summary_token(resume_text: str, max_len: int = TOKEN_MAX) -> str | None:
        """One-liner for the `ctx` metadata token of the sidebar."""
        text = resume_text or ""
        match = TASK_LINE.search(text)
        raw = match.group(1) if match else ""
        if not raw.strip():
            findings = FINDINGS_LINE.search(text)
            if not findings:
                return None
            count = len([t for t in findings.group(1).split(";") if t.strip()])
            return f"{count} findings" if count else None
        single = " ".join(raw.split())
        return single if len(single) <= max_len else single[: max_len - 1] + "…"

`tests/test_digest.py` (neu):

    from lean_herdr.digest import render_digest, strip_frame, summary_token

    #: The shape of a real `lean-ctx call ctx_session {"action":"resume"}`. The
    #: wording is synthetic; the LINES are what matters, because render_digest()
    #: must carry every one of them through.
    RESUME = (
        "--- SESSION RESUME (post-compaction) ---\n"
        "[COMPRESSION: standard] Dense output. Atomic fact lines.\n"
        "Project: lean-herdr\n"
        "Task: rework the plan\n"
        "Key findings: registry.json carries the messages under scratchpad; "
        "project_root is usually null\n"
        "Archives: d87f9bd455c4c365(ctx_read), c5f10c0559312d84(ctx_read)\n"
        "Stats: 104 calls, 1382898 tok saved\n"
        "---"
    )
    HANDOFF = " ctx_handoff show\n path: /x.json\n  - lean_herdr/digest.py\n  - tests/"


    def test_the_finished_digest_is_adopted_not_rebuilt():
        """No field may get lost -- Project, Archives and Stats included."""
        text = render_digest(RESUME, HANDOFF)
        assert text is not None
        for line in (
            "Project: lean-herdr",
            "Task: rework the plan",
            "Archives: d87f9bd455c4c365(ctx_read)",
            "Stats: 104 calls, 1382898 tok saved",
        ):
            assert line in text, f"lost: {line}"
        assert "- lean_herdr/digest.py" in text


    def test_only_frame_and_configuration_lines_are_dropped():
        core = strip_frame(RESUME)
        assert "SESSION RESUME" not in core
        assert "[COMPRESSION:" not in core
        assert not core.startswith("-") and not core.endswith("-")
        assert "Project: lean-herdr" in core


    def test_without_content_there_is_no_digest():
        """Fresh project: no digest, no token -- the normal case, not a failure."""
        assert render_digest("", None) is None
        assert render_digest("--- SESSION RESUME ---\n---", None) is None
        assert summary_token("") is None


    def test_the_token_is_single_line_and_capped():
        token = summary_token("Task: " + "x" * 200)
        assert token is not None and len(token) <= 60 and "\n" not in token
        assert token.endswith("…")


    def test_the_token_falls_back_to_the_findings_count():
        assert summary_token("Key findings: a; b") == "2 findings"
        assert summary_token("Project: x") is None


    def test_the_handoff_is_capped():
        many = "\n".join(f"  - file{i}.py" for i in range(40))
        text = render_digest("Task: t", many)
        assert text is not None and text.count("  - file") <= 12

@call tdd(-k the_finished_digest_is_adopted_not_rebuilt)

### Verify & Close

@call verify("lean_herdr/digest.py tests/test_digest.py")
@call de_scan(lean_herdr/digest.py tests/test_digest.py)
@call gate("lean_herdr/digest.py tests/test_digest.py")

Run: {{ var test_cmd }} — Expected: `247 passed, 7 deselected`.
Run: {{ var test_cmd }} tests/test_language.py — Expected: PASS (der Sprach-Test aus
Task 8 bewacht ab hier jeden B-Task).

@call commit("lean_herdr/digest.py tests/test_digest.py", "feat(digest): build the digest from ctx_session resume and ctx_handoff show")
@call remember_decision("lean-herdr: ctx_session resume liefert einen FERTIGEN Klartext-Digest; render_digest() entrahmt ihn nur (--- Zeilen und [COMPRESSION:]) und haengt die Handoff-Referenzen an -- es baut ihn NICHT aus Feldern nach, sonst gingen Project, Archives, Stats und Ledger verloren. Kein Inhalt -> None: kein Digest, kein Token. Der Token heisst ctx, weil herdr-plugin-renamer $task belegt")
@phase-end

@phase "task-10"
## Task 10 (B2a): `leanctx.py` aus `72dee2f^` zurückholen — englisch

**Files:** Create `lean_herdr/leanctx.py`, `tests/test_leanctx.py` (Wiederherstellung
aus `72dee2f^`).
**Interfaces:** Produces `CtxResponse` (frozen dataclass: `ok`, `text`, `error`,
`json()`), `LeanCtx(project_root, *, binary="lean-ctx", timeout=5.0, runner=subprocess.run)`
mit `is_available()`, `call()`, `post()`, `session_resume()`, `handoff_list()`,
`handoff_show(path)`, und `newest_handoff(list_text) -> str | None`.

Das Modul wurde im `ctx_task`-Lauf als tot gelöscht (`72dee2f`). Das war auf dem
damaligen Stand richtig — kein Produktionscode importierte es —, aber das Wissen war
unvollständig: Task 11 baut `_context()` **vollständig** darauf auf. Der Betreiber hat
am 2026-09-02 entschieden, es aus der Historie zurückzuholen statt es nachzubauen.
Gründe: es war gemessen und getestet, es kapselt eine abgenommene Invariante
(`--project-root` bei **jedem** Aufruf), und `CtxResponse` unterscheidet Fehler,
gültig-leer und Inhalt — drei Fälle, die `_context()` auseinanderhalten muss und die
ein `dict` nicht hergibt.

**Die Wiederherstellung ist wörtlich; die Übersetzung ist die einzige beabsichtigte
Abweichung.** Alles andere gegenüber dem gelöschten Stand ist ein Befund, keine
Verbesserung. Der Ausgangstext:

Run:
    git show 72dee2f^:lean_herdr/leanctx.py
    git show 72dee2f^:tests/test_leanctx.py
— Expected: 167 bzw. 142 Zeilen.

**Umbenannt beim Übersetzen** (die einzigen öffentlichen Änderungen):
`CtxAntwort` → `CtxResponse`, `FEHLER_PRAEFIXE` → `ERROR_PREFIXES`,
`LEDGER_ZEILE` → `LEDGER_LINE`. Task 11 spricht bereits von `CtxResponse`.

`lean_herdr/leanctx.py` (wiederhergestellt und übersetzt):

    """lean-ctx CLI -> CtxResponse, with an enforced canonical --project-root.

    ctx_session write actions are deliberately absent: they report success and
    persist nothing (B1). ctx_agent read is absent as well: it requires a
    registration inside the same process (B9).
    """

    from __future__ import annotations

    import json
    import re
    import shutil
    import subprocess
    from dataclasses import dataclass
    from pathlib import Path
    from typing import Any

    DEFAULT_TIMEOUT_S = 5.0

    #: `lean-ctx call` reports an error on the first line, not via the exit code.
    ERROR_PREFIXES = ("error:", "Error:")

    #: Lines from `ctx_handoff list`: "  1. /path/to/file.json"
    LEDGER_LINE = re.compile(r"^\s*\d+\.\s+(\S+)\s*$", re.MULTILINE)


    @dataclass(frozen=True)
    class CtxResponse:
        """One answer from `lean-ctx call` -- text, not JSON.

        Three states that MUST be kept apart:
        ok=True  + text != ""  -> an answer with content
        ok=True  + text == ""  -> a valid but empty answer (fresh project)
        ok=False + error       -> unavailable | timeout | the error line of lean-ctx
        """

        ok: bool
        text: str = ""
        error: str | None = None

        def json(self) -> dict[str, Any]:
            """The embedded JSON body if there is one -- otherwise {}.

            `ctx_handoff show` writes two header lines and then JSON; other calls
            write none at all. So try from the first `{` on and stay silent when
            it does not work out.
            """
            start = self.text.find("{")
            if start < 0:
                return {}
            try:
                data = json.loads(self.text[start:])
            except json.JSONDecodeError:
                return {}
            return data if isinstance(data, dict) else {}


    class LeanCtx:
        def __init__(
            self,
            project_root: str | Path,
            *,
            binary: str = "lean-ctx",
            timeout: float = DEFAULT_TIMEOUT_S,
            runner: Any = subprocess.run,
        ) -> None:
            #: Comes from bus.canonical_root() -- never from $PWD, never a worktree.
            self.project_root = str(project_root)
            self.binary = binary
            self.timeout = timeout
            self._runner = runner
            self._available: bool | None = None

        def is_available(self) -> bool:
            if self._available is None:
                self._available = shutil.which(self.binary) is not None
            return self._available

        def _run(self, args: list[str]) -> CtxResponse:
            """Never raise, but ALWAYS distinguish why nothing came back."""
            if not self.is_available():
                return CtxResponse(False, error="unavailable")
            try:
                proc = self._runner(
                    [self.binary, *args],
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                )
            except subprocess.TimeoutExpired:
                return CtxResponse(False, error="timeout")
            except (OSError, subprocess.SubprocessError) as exc:
                return CtxResponse(False, error=f"spawn_failed: {exc}")
            text = (proc.stdout or "").strip()
            first = text.splitlines()[0] if text else ""
            if proc.returncode != 0 or first.startswith(ERROR_PREFIXES):
                return CtxResponse(False, text, error=first or f"exit {proc.returncode}")
            return CtxResponse(True, text)

        def call(self, tool: str, arguments: dict[str, Any]) -> CtxResponse:
            """`lean-ctx call <tool> --project-root <canonical> --json '<args>'`."""
            return self._run(
                [
                    "call",
                    tool,
                    "--project-root",
                    self.project_root,
                    "--json",
                    json.dumps(arguments, separators=(",", ":")),
                ]
            )

        # -- Bus (write only) ------------------------------------------------

        def post(
            self,
            *,
            message: str,
            to_agent: str | None = None,
            task_id: str | None = None,
            category: str = "task",
            metadata: dict[str, Any] | None = None,
        ) -> CtxResponse:
            """Put a message on the bus. NOT usable for work orders.

            From a CLI process this always posts as `anonymous`: registration is
            bound to the pid of a short-lived process (B-2), and the role prompts
            rightly refuse `anonymous` as a client. And `task_id` never arrives:
            every write path of `ctx_agent post` hard-sets it to `None`
            (core/agents/registry.rs:430, shared.rs:31). Work orders therefore run
            through `ctx_task`, see lean_herdr/tasks.py.

            `to_agent` MUST be a lean-ctx agent_id. A friendly name is accepted
            silently and never delivered (B7).
            """
            args: dict[str, Any] = {"action": "post", "message": message, "category": category}
            if to_agent:
                args["to_agent"] = to_agent
            if task_id:
                args["task_id"] = task_id
            if metadata:
                args["metadata"] = metadata
            return self.call("ctx_agent", args)

        # -- Context (read only) ---------------------------------------------

        def session_resume(self) -> CtxResponse:
            """The finished resume report: project, findings, archives, stats.

            The text is the result, not raw material. It is neither taken apart
            nor rebuilt -- lean_herdr/digest.py only unframes it.
            """
            return self.call("ctx_session", {"action": "resume"})

        def handoff_list(self) -> CtxResponse:
            """All handoff ledgers, newest first."""
            return self.call("ctx_handoff", {"action": "list"})

        def handoff_show(self, path: str | Path) -> CtxResponse:
            """One ledger. `path` is MANDATORY -- without it: `error: -32602`."""
            return self.call("ctx_handoff", {"action": "show", "path": str(path)})


    def newest_handoff(list_text: str) -> str | None:
        """First path from `ctx_handoff list` -- the list comes newest first."""
        match = LEDGER_LINE.search(list_text or "")
        return match.group(1) if match else None

`tests/test_leanctx.py` (wiederhergestellt und übersetzt):

    import json
    import subprocess

    import pytest

    from lean_herdr.leanctx import CtxResponse, LeanCtx, newest_handoff
    from tests.doubles import Completed, FakeProc, which_stub

    ROOT = "/home/tholo/Scripts/lean-herdr"

    #: Measured verbatim against lean-ctx 3.10.1 (wording anglicised, shape kept).
    RESUME_TEXT = (
        "--- SESSION RESUME (post-compaction) ---\n"
        "Project: lean-herdr\n"
        "Task: rework the plan\n"
        "Key findings: registry.json carries the messages under scratchpad\n"
        "Stats: 104 calls, 1382898 tok saved\n"
        "---"
    )
    LEDGER_TEXT = (
        "Handoff Ledgers (9):\n"
        "  1. /home/tholo/.local/share/lean-ctx/handoffs/20260901-new.json\n"
        "  2. /home/tholo/.local/share/lean-ctx/handoffs/20260621-old.json"
    )


    @pytest.fixture
    def fake(monkeypatch) -> FakeProc:
        monkeypatch.setattr("lean_herdr.leanctx.shutil.which", which_stub(True))
        return FakeProc()


    def args_of(call: list[str]) -> dict:
        return json.loads(call[call.index("--json") + 1])


    def test_every_call_carries_the_canonical_root(fake):
        LeanCtx(ROOT, runner=fake).call("ctx_agent", {"action": "post"})
        assert fake.called_with("--project-root", ROOT)


    def test_a_worktree_path_never_reaches_the_flag(fake):
        """B12: --project-root on a linked worktree opens a second bus."""
        LeanCtx(ROOT, runner=fake).post(message="x")
        (call,) = fake.calls
        root = call[call.index("--project-root") + 1]
        assert root == ROOT
        assert ".feat" not in root and "/tmp/" not in root


    def test_post_builds_the_directed_message(fake):
        LeanCtx(ROOT, runner=fake).post(
            message="Please work on task T1.",
            to_agent="mcp-2018183-70c877bf",
            task_id="T1",
            category="task",
            metadata={"branch": "feat/auth"},
        )
        assert args_of(fake.calls[0]) == {
            "action": "post",
            "message": "Please work on task T1.",
            "category": "task",
            "to_agent": "mcp-2018183-70c877bf",
            "task_id": "T1",
            "metadata": {"branch": "feat/auth"},
        }


    def test_session_resume_is_a_read_action(fake):
        LeanCtx(ROOT, runner=fake).session_resume()
        assert args_of(fake.calls[0]) == {"action": "resume"}


    def test_no_write_action_and_no_bus_read():
        """B1: ctx_session writes persist nothing. B9: read needs the same process."""
        forbidden = {"task", "finding", "decision", "status", "read"}
        assert not forbidden & {n for n in dir(LeanCtx) if not n.startswith("_")}


    def test_handoff_show_without_a_path_does_not_exist(fake):
        """Measured: `show` without path answers `error: -32602`."""
        LeanCtx(ROOT, runner=fake).handoff_show("/path/l.json")
        assert args_of(fake.calls[0]) == {"action": "show", "path": "/path/l.json"}


    # -- The three states that must be kept apart ---------------------------

    def test_plain_text_is_not_read_as_json(monkeypatch):
        """The core finding: `lean-ctx call` prints text, never JSON."""
        monkeypatch.setattr("lean_herdr.leanctx.shutil.which", which_stub(True))
        answer = LeanCtx(
            ROOT, runner=lambda *a, **k: Completed(stdout=RESUME_TEXT)
        ).session_resume()
        assert answer.ok and "Project: lean-herdr" in answer.text


    def test_empty_output_is_valid_and_not_an_error(monkeypatch):
        """Fresh project: ok, but without content -- not the same as an error."""
        monkeypatch.setattr("lean_herdr.leanctx.shutil.which", which_stub(True))
        answer = LeanCtx(ROOT, runner=lambda *a, **k: Completed(stdout="")).session_resume()
        assert answer.ok is True and answer.text == "" and answer.error is None


    def test_an_error_line_is_recognised_as_an_error(monkeypatch):
        """lean-ctx reports errors on the first line, not via the exit code."""
        monkeypatch.setattr("lean_herdr.leanctx.shutil.which", which_stub(True))
        answer = LeanCtx(
            ROOT,
            runner=lambda *a, **k: Completed(
                stdout="error: -32602: path is required for action=show"
            ),
        ).handoff_show("")
        assert answer.ok is False and "path is required" in (answer.error or "")


    def test_a_timeout_is_distinguishable_from_empty(monkeypatch):
        monkeypatch.setattr("lean_herdr.leanctx.shutil.which", which_stub(True))
        fake = FakeProc(raises=subprocess.TimeoutExpired(cmd=["lean-ctx"], timeout=1))
        answer = LeanCtx(ROOT, runner=fake).session_resume()
        assert answer.ok is False and answer.error == "timeout"


    def test_no_call_without_the_binary(monkeypatch):
        monkeypatch.setattr("lean_herdr.leanctx.shutil.which", which_stub(False))
        fake = FakeProc()
        answer = LeanCtx(ROOT, runner=fake).session_resume()
        assert answer == CtxResponse(False, error="unavailable")
        assert fake.calls == []


    def test_embedded_json_is_found_when_it_is_there():
        """`ctx_handoff show`: two header lines, then JSON."""
        answer = CtxResponse(True, ' ctx_handoff show\n path: /x.json\n{"schema_version": 1}')
        assert answer.json() == {"schema_version": 1}
        assert CtxResponse(True, RESUME_TEXT).json() == {}


    def test_newest_handoff_takes_the_first_entry():
        newest = newest_handoff(LEDGER_TEXT)
        assert newest is not None and newest.endswith("20260901-new.json")
        assert newest_handoff("Handoff Ledgers (0):") is None
        assert newest_handoff("") is None

**Befund-Pflicht:** Weicht der wiederhergestellte Text über die Übersetzung hinaus vom
Stand `72dee2f^` ab, wird die Abweichung **gemeldet**, nicht stillschweigend behalten.
Prüfbar:

Run: git show 72dee2f^:lean_herdr/leanctx.py > /dev/null && `@read lean_herdr/leanctx.py mode=full`
— Expected: Struktur, Reihenfolge und Logik deckungsgleich; nur Bezeichner, Kommentare
und Docstrings sind englisch.

@call tdd(-k every_call_carries_the_canonical_root)

### Verify & Close

@call verify("lean_herdr/leanctx.py tests/test_leanctx.py")
@call de_scan(lean_herdr/leanctx.py tests/test_leanctx.py)
@call gate("lean_herdr/leanctx.py tests/test_leanctx.py")

Run: {{ var test_cmd }} — Expected: `260 passed, 7 deselected`.

@call commit("lean_herdr/leanctx.py tests/test_leanctx.py", "feat(leanctx): restore the CLI gateway from 72dee2f^, in English")
@call remember_decision("lean-herdr: lean_herdr/leanctx.py ist aus 72dee2f^ zurueckgeholt, weil handlers._context() vollstaendig darauf aufbaut. CtxAntwort heisst jetzt CtxResponse, FEHLER_PRAEFIXE ERROR_PREFIXES, LEDGER_ZEILE LEDGER_LINE. Die drei Zustaende ok+text / ok+leer / fehler sind der Grund fuer die dataclass -- ein dict gibt sie nicht her. Jeder call() traegt --project-root aus bus.canonical_root(), nie $PWD und nie einen Worktree (B12)")
@phase-end

@phase "task-11"
## Task 11 (B2b): `handlers.py` — fünf Handler, die nie etwas brechen

@call recall_context("lean-herdr Config digest_path render_digest summary_token CtxResponse")

**Files:** Create `lean_herdr/handlers.py`, `tests/test_handlers.py`.
**Interfaces:** Produces
`handle_workspace_created(cfg) -> None`, `handle_pane_detected(cfg) -> None`,
`handle_status_changed(cfg) -> None`, `handle_inject(cfg) -> None`,
`handle_bootstrap(cfg) -> None`,
`cwd_from_event(event, herdr, cfg) -> Path | None`.

Erst dieser Task macht die Subkommandos von `__main__.py` wirksam. Ohne ihn läuft jedes
mit exit 0 und einer stderr-Zeile ins Leere — kein Absturz (siehe „Gemessene
Abweichungen zur Spec"), aber auch keine Wirkung.

Der Datenfluss, den diese Handler bilden:

    workspace.created / focused ─► workspace list → canonical_root(cwd)
                                   → ctx_session resume + ctx_handoff show
                                   → workspace report-metadata <id> --source lean.herdr --token ctx="<task>"

    pane.agent_detected ─────────► pane get → canonical_root(cwd) → Digest
       (auch nach --resume)        → STATE_DIR/<pane_id>.md
                                   → pane report-metadata <id> --source lean.herdr --token ctx="<task>"

    pane.agent_status_changed ───► Token auffrischen

    Action inject ───────────────► STATE_DIR/<pane_id>.md → herdr agent prompt

    Action bootstrap ────────────► pane list --workspace <id> → Ankerpane
       (Workspace-Kontext)         → pane split --pane <anker> --env minimal
                                   → agent start orch --kind opencode

**Die Kanonisierung gilt auch hier — gerade hier.** Die Handler gehen über
`leanctx.py`, also über dieselbe CLI mit demselben Pflichtflag, nicht über einen
MCP-Server. Die Kanonisierung, die lean-ctx einem stdio-Server schenkt, gibt es für sie
nicht. Jede `cwd`, die ein Handler aus einem Herdr-Event zieht, läuft zuerst durch
`canonical_root()`. Ein Handler, der die rohe Workspace-cwd durchreicht, legt für jeden
Worktree ein eigenes lean-ctx-Projekt an (B12) — und zeigt dann einen **leeren Digest**
an, statt zu brechen. Der stillste denkbare Fehler.

**Worktree-Workspaces bekommen denselben Digest wie der Haupt-Workspace**, weil
`canonical_root()` sie auf den Repo-Root führt. Das ist richtig — es ist dasselbe
Projektgedächtnis — und spart einen eigenen `worktree.created`-Handler.

Der Unterschied in der letzten Zeile der Fehlertabelle ist Absicht: **Automatik
scheitert still, eine bewusste Geste scheitert sichtbar.**

| Fall | Verhalten |
|---|---|
| lean-ctx fehlt oder antwortet nicht | exit 0, kein Token, Notiz auf stderr |
| kein Session-State für die cwd | still, kein Token — Normalfall bei frischen Projekten |
| lean-ctx hängt | `subprocess` mit 5 s Timeout (aus `Config.timeout`) |
| unerwartete Exception | oberster `try/except` in `__main__` → stderr, exit 0 |
| kein Digest bei `inject` | `herdr notification show` |

**Befund, der gemeldet und NICHT behoben wird.** `ORCHESTRATOR` schreibt
`LEAN_CTX_TOOL_PROFILE: "minimal"` fest. Seit dem `ctx_task`-Umbau gibt es dafür
`lean_herdr.settings`: `PROFILE_BY_ROLE = {"orchestrator": "minimal"}`, überschreibbar
über `.config/lean-herdr.toml`. Die Werte stimmen heute **überein**, das Verhalten ist
also unverändert — aber `handle_bootstrap` ignoriert die Konfigurationsdatei, die
`dispatch.py` respektiert. Das gehört in eine eigene Spec, nicht in diesen Task.

**Übersetzt gegenüber dem Vorgängerplan** (Bereich 4775-5280): `_notiz` → `_note`,
`_kontext` → `_context`, `_zeigen` → `_show`, alle Locals, alle Docstrings und
Kommentare, alle Testnamen, die Fixture `welt` → `world` und die
`notification show`-Texte (die sieht der Betreiber in der Herdr-Oberfläche).
**Gestrichen:** `test_unbekannter_subcommand_bricht_nicht` — `test_manifest.py`
prüft dasselbe seit Task 13 des Vorgängerplans (dort seit Task 6
`test_an_unknown_subcommand_is_not_a_crash`); ein zweiter Test derselben Sache
bindet nur Wartung.

`lean_herdr/handlers.py` (neu):

    """One handler per subcommand. Reads and shows -- never writes to lean-ctx.

    A plugin handler is a one-shot process without an agent identity and CANNOT
    write (B1-B3). Persistent state lives only in the digest under
    HERDR_PLUGIN_STATE_DIR and in lean-ctx itself; the plugin keeps no register
    of its own.
    """

    from __future__ import annotations

    import sys
    from pathlib import Path
    from typing import Any

    from lean_herdr.bus import BusError, canonical_root
    from lean_herdr.config import Config
    from lean_herdr.digest import render_digest, summary_token
    from lean_herdr.herdr import Herdr
    from lean_herdr.leanctx import LeanCtx, newest_handoff

    #: The token belongs to the plugin. `esc` belongs to the orchestrator and is
    #: never touched here -- not even to clear it.
    TOKEN = "ctx"

    #: The orchestrator pane of the bootstrap. minimal, because it only needs ctx_call.
    ORCHESTRATOR = {
        "name": "orch",
        "kind": "opencode",
        "env": {"LEAN_CTX_TOOL_PROFILE": "minimal", "LEAN_CTX_ROLE": "orchestrator"},
    }


    def _note(text: str) -> None:
        """stderr ends up in `herdr plugin log list --plugin lean.herdr`."""
        sys.stderr.write(f"[lean.herdr] {text}\n")


    def cwd_from_event(event: dict[str, Any] | None, herdr: Herdr, cfg: Config) -> Path | None:
        """cwd of the pane or workspace from the event -- else asked of Herdr."""
        for source in (event or {}, (event or {}).get("pane") or {}, (event or {}).get("workspace") or {}):
            if isinstance(source, dict) and source.get("cwd"):
                return Path(str(source["cwd"]))
        if cfg.pane_id:
            info = herdr.pane_process_info(cfg.pane_id)
            cwd = ((info.get("result") or {}).get("process_info") or {}).get("cwd")
            if cwd:
                return Path(str(cwd))
        return None


    def _context(cwd: Path, cfg: Config) -> tuple[str | None, str | None]:
        """(digest, token text) for this cwd. (None, None) when there is nothing.

        The three nothing-cases are KEPT APART, because they must be handled
        differently -- that is what CtxResponse is for:
        * error or timeout -> a note on stderr, so `herdr plugin log list` has
          something to show. Something is broken.
        * valid, but empty -> silence. A fresh project is the normal case.
        Without that distinction every note would be either noise or missing.
        """
        try:
            root = canonical_root(cwd)
        except BusError as exc:
            _note(f"no repo at {cwd}: {exc}")
            return None, None
        leanctx = LeanCtx(root, timeout=cfg.timeout)
        resume = leanctx.session_resume()
        if not resume.ok:
            _note(f"ctx_session resume: {resume.error}")
            return None, None
        if not resume.text:
            return None, None  # fresh project -- not an error, no note

        # The handoff is a bonus: if it fails, the digest stays valid.
        handoff_text: str | None = None
        listing = leanctx.handoff_list()
        if listing.ok:
            path = newest_handoff(listing.text)
            if path:
                shown = leanctx.handoff_show(path)
                handoff_text = shown.text if shown.ok else None
        elif listing.error not in ("unavailable",):
            _note(f"ctx_handoff list: {listing.error}")

        return render_digest(resume.text, handoff_text), summary_token(resume.text)


    def _show(cfg: Config, herdr: Herdr, scope: str, target: str, cwd: Path) -> None:
        digest, token = _context(cwd, cfg)
        if digest and scope == "pane":
            path = cfg.digest_path(target)
            if path is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(digest, encoding="utf-8")
        if token:
            herdr.report_metadata(scope, target, TOKEN, token)


    # -- Handlers ----------------------------------------------------------

    def handle_workspace_created(cfg: Config) -> None:
        """Resumption: after a server restart Herdr recreates the workspaces."""
        herdr = Herdr(cfg.herdr_bin, timeout=cfg.timeout)
        event = cfg.event or {}
        workspace = str(
            event.get("workspace_id") or (event.get("workspace") or {}).get("id") or cfg.workspace_id or ""
        )
        if not workspace:
            return
        cwd = cwd_from_event(event, herdr, cfg)
        if cwd is None:
            for entry in herdr.workspace_list():
                if str(entry.get("id")) == workspace and entry.get("cwd"):
                    cwd = Path(str(entry["cwd"]))
                    break
        if cwd is None:
            return
        _show(cfg, herdr, "workspace", workspace, cwd)


    def handle_pane_detected(cfg: Config) -> None:
        """An agent was detected -- after `claude --resume` as well."""
        herdr = Herdr(cfg.herdr_bin, timeout=cfg.timeout)
        event = cfg.event or {}
        pane = str(event.get("pane_id") or (event.get("pane") or {}).get("id") or cfg.pane_id or "")
        if not pane:
            return
        cwd = cwd_from_event(event, herdr, cfg)
        if cwd is None:
            return
        _show(cfg, herdr, "pane", pane, cwd)


    def handle_status_changed(cfg: Config) -> None:
        """Only refresh the token -- same path, same source."""
        handle_pane_detected(cfg)


    def handle_inject(cfg: Config) -> None:
        """A deliberate gesture: send the stored digest to the pane's agent.

        Prompting automatically from a handler is out of the question -- it would
        run into agent_blocked and disturb someone who is typing.
        """
        herdr = Herdr(cfg.herdr_bin, timeout=cfg.timeout)
        event = cfg.event or {}
        pane = str(event.get("pane_id") or cfg.pane_id or "")
        path = cfg.digest_path(pane) if pane else None
        if path is None or not path.is_file():
            # Automation fails silently, a deliberate gesture fails visibly.
            herdr.run("notification", "show", "--message", "lean-herdr: no digest for this pane")
            return
        name = next(
            (str(a.get("name")) for a in herdr.agent_list() if str(a.get("pane_id")) == pane), ""
        )
        if not name:
            herdr.run("notification", "show", "--message", "lean-herdr: no agent in this pane")
            return
        herdr.agent_prompt(name, path.read_text(encoding="utf-8"), wait=False)


    def handle_bootstrap(cfg: Config) -> None:
        """A deliberate gesture: open an orchestrator pane in THIS workspace.

        The handler does not act as an agent -- it only types what stage 3 step 1
        types by hand. An anchor pane from this workspace makes sure the new pane
        lands here and not in the caller's workspace.
        """
        herdr = Herdr(cfg.herdr_bin, timeout=cfg.timeout)
        event = cfg.event or {}
        workspace = str(
            event.get("workspace_id")
            or (event.get("workspace") or {}).get("id")
            or cfg.workspace_id
            or ""
        )
        if not workspace:
            herdr.run("notification", "show", "--message", "lean-herdr: no workspace")
            return
        if any(a.get("name") == ORCHESTRATOR["name"] for a in herdr.agent_list()):
            herdr.run(
                "notification", "show", "--message", "lean-herdr: the orchestrator is already running"
            )
            return
        cwd = cwd_from_event(event, herdr, cfg)
        anchor = next(
            (str(p["pane_id"]) for p in herdr.pane_list(workspace) if p.get("pane_id")), None
        )
        if cwd is None or anchor is None:
            herdr.run(
                "notification", "show", "--message", "lean-herdr: workspace without a pane or cwd"
            )
            return
        pane = herdr.pane_split(cwd, pane=anchor, env=ORCHESTRATOR["env"])
        if not pane:
            herdr.run("notification", "show", "--message", "lean-herdr: pane split failed")
            return
        herdr.agent_start(
            ORCHESTRATOR["name"],
            kind=ORCHESTRATOR["kind"],
            pane=pane,
            agent_args=["--agent", "orchestrator"],
        )

`tests/test_handlers.py` (neu):

    import json
    from pathlib import Path

    import pytest

    from lean_herdr import handlers
    from lean_herdr.config import Config
    from tests.doubles import FakeProc, which_stub

    #: `lean-ctx call` prints plain text -- as a str it goes through FakeProc to
    #: stdout verbatim.
    RESUME = (
        "--- SESSION RESUME (post-compaction) ---\n"
        "Project: lean-herdr\n"
        "Task: build lean-herdr\n"
        "Key findings: scratchpad instead of messages\n"
        "---"
    )
    LEDGER = "Handoff Ledgers (1):\n  1. /handoffs/new.json"


    @pytest.fixture
    def world(monkeypatch, tmp_path):
        monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
        monkeypatch.setattr("lean_herdr.leanctx.shutil.which", which_stub(True))
        monkeypatch.setattr("lean_herdr.handlers.canonical_root", lambda cwd: Path("/repo"))
        h_proc, l_proc = FakeProc(), FakeProc()
        l_proc.replies = {
            ("call", "ctx_session"): RESUME,
            ("call", "ctx_handoff"): LEDGER,
        }
        monkeypatch.setattr("lean_herdr.handlers.Herdr", lambda *a, **kw: __import__(
            "lean_herdr.herdr", fromlist=["Herdr"]
        ).Herdr(runner=h_proc))
        monkeypatch.setattr("lean_herdr.handlers.LeanCtx", lambda root, **kw: __import__(
            "lean_herdr.leanctx", fromlist=["LeanCtx"]
        ).LeanCtx(root, runner=l_proc))
        return h_proc, l_proc, tmp_path


    def cfg(tmp_path: Path, **rest) -> Config:
        env = {
            "HERDR_PLUGIN_STATE_DIR": str(tmp_path / "state"),
            "HERDR_PANE_ID": "w2:p2",
            "HERDR_WORKSPACE_ID": "w2",
            **rest,
        }
        return Config.from_env(env)


    def test_pane_detected_writes_the_digest_and_sets_the_ctx_token(world):
        h_proc, _, tmp_path = world
        c = cfg(tmp_path, HERDR_PLUGIN_EVENT_JSON=json.dumps(
            {"pane_id": "w2:p2", "pane": {"cwd": "/repo.feat"}}
        ))
        handlers.handle_pane_detected(c)
        digest = tmp_path / "state" / "w2:p2.md"
        assert digest.is_file()
        assert "build lean-herdr" in digest.read_text(encoding="utf-8")
        # The id is POSITIONAL, not --pane: herdr.report_metadata() measured that
        # against 0.8.2 and the predecessor plan's assertion never caught up.
        assert h_proc.called_with(
            "pane", "report-metadata", "w2:p2", "--source", "lean.herdr",
            "--token", "ctx=build lean-herdr",
        )


    def test_the_cwd_goes_through_canonical_root(world, monkeypatch):
        """B12: a raw worktree cwd opens a lean-ctx project of its own."""
        _, l_proc, tmp_path = world
        seen: list[Path] = []
        monkeypatch.setattr(
            "lean_herdr.handlers.canonical_root",
            lambda cwd: (seen.append(Path(cwd)), Path("/repo"))[1],
        )
        handlers.handle_pane_detected(cfg(tmp_path, HERDR_PLUGIN_EVENT_JSON=json.dumps(
            {"pane_id": "w2:p2", "pane": {"cwd": "/repo.feat-auth"}}
        )))
        assert seen == [Path("/repo.feat-auth")]
        # Three calls carry the flag -- resume, handoff list, handoff show. Every
        # one of them must carry the SAME canonical root; the predecessor plan
        # unpacked a single call and would have died on the other two.
        roots = {c[c.index("--project-root") + 1] for c in l_proc.calls if "--project-root" in c}
        assert roots == {"/repo"}


    def test_without_lean_ctx_nothing_happens_and_nothing_breaks(monkeypatch, tmp_path):
        monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
        monkeypatch.setattr("lean_herdr.leanctx.shutil.which", which_stub(False))
        monkeypatch.setattr("lean_herdr.handlers.canonical_root", lambda cwd: Path("/repo"))
        h_proc, l_proc = FakeProc(), FakeProc()
        monkeypatch.setattr("lean_herdr.handlers.Herdr", lambda *a, **kw: __import__(
            "lean_herdr.herdr", fromlist=["Herdr"]
        ).Herdr(runner=h_proc))
        monkeypatch.setattr("lean_herdr.handlers.LeanCtx", lambda root, **kw: __import__(
            "lean_herdr.leanctx", fromlist=["LeanCtx"]
        ).LeanCtx(root, runner=l_proc))
        for handler in (
            handlers.handle_workspace_created,
            handlers.handle_pane_detected,
            handlers.handle_status_changed,
            handlers.handle_inject,
            handlers.handle_bootstrap,
        ):
            handler(cfg(tmp_path, HERDR_PLUGIN_EVENT_JSON=json.dumps({"pane": {"cwd": "/repo"}})))
        assert l_proc.calls == [], "without lean-ctx there must be no call"
        assert not any("--token" in c for c in h_proc.calls), "no token without context"


    # -- The three nothing-cases, each with its own behaviour ----------------

    def test_an_empty_session_state_stays_silent(world, capsys):
        """Fresh project: no token, no digest -- and NO note."""
        h_proc, l_proc, tmp_path = world
        l_proc.replies = {("call", "ctx_session"): ""}
        handlers.handle_pane_detected(cfg(tmp_path, HERDR_PLUGIN_EVENT_JSON=json.dumps(
            {"pane_id": "w2:p2", "pane": {"cwd": "/repo"}}
        )))
        assert not any("--token" in c for c in h_proc.calls)
        assert not (tmp_path / "state" / "w2:p2.md").exists()
        assert capsys.readouterr().err == "", "empty is not an error"


    def test_an_error_from_lean_ctx_leaves_a_note(world, capsys):
        """Broken is not empty -- here a line MUST appear in the plugin log."""
        h_proc, l_proc, tmp_path = world
        l_proc.replies = {("call", "ctx_session"): "error: -32603: internal"}
        handlers.handle_pane_detected(cfg(tmp_path, HERDR_PLUGIN_EVENT_JSON=json.dumps(
            {"pane_id": "w2:p2", "pane": {"cwd": "/repo"}}
        )))
        assert not any("--token" in c for c in h_proc.calls)
        assert "ctx_session resume" in capsys.readouterr().err


    def test_a_timeout_leaves_a_note(world, capsys):
        import subprocess

        _, l_proc, tmp_path = world
        l_proc.raises = subprocess.TimeoutExpired(cmd=["lean-ctx"], timeout=1)
        handlers.handle_pane_detected(cfg(tmp_path, HERDR_PLUGIN_EVENT_JSON=json.dumps(
            {"pane_id": "w2:p2", "pane": {"cwd": "/repo"}}
        )))
        assert "timeout" in capsys.readouterr().err


    def test_no_handler_touches_the_esc_token(world):
        h_proc, _, tmp_path = world
        handlers.handle_pane_detected(cfg(tmp_path, HERDR_PLUGIN_EVENT_JSON=json.dumps(
            {"pane_id": "w2:p2", "pane": {"cwd": "/repo"}}
        )))
        assert not any("esc" in " ".join(c) for c in h_proc.calls), (
            "esc belongs to the orchestrator -- two writers on one token are a "
            "silent conflict"
        )


    def test_workspace_created_sets_the_token_on_the_workspace(world):
        h_proc, _, tmp_path = world
        handlers.handle_workspace_created(cfg(tmp_path, HERDR_PLUGIN_EVENT_JSON=json.dumps(
            {"workspace_id": "w2", "workspace": {"cwd": "/repo"}}
        )))
        assert h_proc.called_with(
            "workspace", "report-metadata", "w2", "--source", "lean.herdr"
        )


    def test_inject_sends_the_digest_without_wait(world):
        h_proc, _, tmp_path = world
        path = tmp_path / "state" / "w2:p2.md"
        path.parent.mkdir(parents=True)
        path.write_text("# lean-ctx context\n\n**Task:** keep building\n", encoding="utf-8")
        h_proc.replies = {
            ("agent", "list"): {"result": {"agents": [{"name": "builder", "pane_id": "w2:p2"}]}}
        }
        handlers.handle_inject(cfg(tmp_path))
        prompt = next(c for c in h_proc.calls if c[1:3] == ["agent", "prompt"])
        assert "keep building" in " ".join(prompt)
        assert "--wait" not in prompt


    def test_inject_without_a_digest_reports_visibly(world):
        h_proc, _, tmp_path = world
        handlers.handle_inject(cfg(tmp_path))
        assert h_proc.called_with("notification", "show"), (
            "automation fails silently, a deliberate gesture visibly"
        )


    def test_bootstrap_starts_the_orchestrator_in_its_own_workspace(world):
        h_proc, _, tmp_path = world
        h_proc.replies = {
            ("pane", "list"): {"result": {"panes": [{"pane_id": "w2:p1"}]}},
            ("pane", "split"): {"result": {"pane": {"pane_id": "w2:p9"}}},
        }
        handlers.handle_bootstrap(cfg(tmp_path, HERDR_PLUGIN_EVENT_JSON=json.dumps(
            {"workspace_id": "w2", "workspace": {"cwd": "/repo"}}
        )))
        split = next(c for c in h_proc.calls if c[1:3] == ["pane", "split"])
        assert "--pane" in split and "w2:p1" in split, "the pane belongs in THIS workspace"
        assert "LEAN_CTX_TOOL_PROFILE=minimal" in split
        start = next(c for c in h_proc.calls if c[1:3] == ["agent", "start"])
        assert "orch" in start and "opencode" in start


    def test_bootstrap_does_not_start_a_second_orchestrator(world):
        h_proc, _, tmp_path = world
        h_proc.replies = {
            ("agent", "list"): {"result": {"agents": [{"name": "orch", "pane_id": "w2:p9"}]}}
        }
        handlers.handle_bootstrap(cfg(tmp_path, HERDR_PLUGIN_EVENT_JSON=json.dumps(
            {"workspace_id": "w2", "workspace": {"cwd": "/repo"}}
        )))
        assert not any(c[1:3] == ["pane", "split"] for c in h_proc.calls)
        assert h_proc.called_with("notification", "show")


    def test_main_catches_every_exception_and_ends_with_0(monkeypatch, capsys):
        """The monkeypatch bites ONLY because __main__ resolves the handler by NAME.

        Were HANDLERS to hold the function object, main() would still pull the old
        function -- the test would run green without checking anything.
        """
        from lean_herdr.__main__ import main

        monkeypatch.setattr(
            handlers, "handle_pane_detected",
            lambda cfg: (_ for _ in ()).throw(RuntimeError("broken")),
        )
        assert main(["pane-detected"]) == 0
        assert "broken" in capsys.readouterr().err

@call tdd(-k the_cwd_goes_through_canonical_root)

@call tdd(-k an_error_from_lean_ctx_leaves_a_note)

@call tdd(-k bootstrap_starts_the_orchestrator_in_its_own_workspace)

### Verify & Close

@call verify("lean_herdr/handlers.py tests/test_handlers.py")
@call de_scan(lean_herdr/handlers.py tests/test_handlers.py)
@call review_change()
@call gate("lean_herdr/handlers.py tests/test_handlers.py")

Run: {{ var test_cmd }} — Expected: `273 passed, 7 deselected`.

Run: HERDR_PANE_ID=w1:p1 python3 -m lean_herdr pane-detected — Expected: exit 0, keine
Ausnahme auf stderr. Das Subkommando ist ab jetzt wirksam.

@call commit("lean_herdr/handlers.py tests/test_handlers.py", "feat(plugin): five handlers that read and show instead of acting")
@call remember_decision("lean-herdr Handler: jede cwd aus einem Herdr-Event laeuft durch canonical_root(), bevor sie --project-root wird (B12); kein Handler fasst den esc-Token an; inject und bootstrap melden sich sichtbar, die Automatik scheitert still. _context() unterscheidet ueber CtxResponse drei Faelle: Fehler/Timeout -> Notiz auf stderr, gueltig-leer -> schweigen, Inhalt -> Digest. bootstrap teilt einen Ankerpane aus `pane list --workspace <id>`. OFFENER BEFUND: ORCHESTRATOR schreibt LEAN_CTX_TOOL_PROFILE=minimal fest und ignoriert lean_herdr.settings/.config/lean-herdr.toml -- Werte stimmen heute ueberein, eigene Spec")
@phase-end

@phase "task-12"
## Task 12 (B3): der opencode-Policy-Adapter — übersetzt, entscheidet nichts

**Files:** Create `.opencode/plugins/lean-ctx-policy.js`,
`tests/test_policy_adapter.py`.

Claude Code führt die lean-ctx-Disziplin über Hooks durch; opencode-Arbeiter laufen
heute ohne. Der Adapter schließt die Lücke, **ohne die Regeln zu verdoppeln** — ein
zweites Regelwerk driftet.

**Die Regeln passen bereits.** `bash-enforce-ctx-shell.py` prüft
`BASH_TOOL_NAMES = {"bash"}` — kleingeschrieben, exakt opencodes Tool-Name.
`read-search-discipline.py` normalisiert mit `tool_name.lower()` und kennt `read`,
`grep`, `glob`, `ls`. Es fehlt allein die Protokollübersetzung; keine Regel wird
angefasst.

Das Protokoll der vorhandenen Hooks, an `bash-enforce-ctx-shell.py` verifiziert:
stdin `{tool_name, tool_input, …}`, stdout
`{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
"permissionDecisionReason": "…"}}`, exit 0.

| opencode-Hook | Skript |
|---|---|
| `tool.execute.before` (`read`/`grep`/`glob`/`ls`) | `read-search-discipline.py` |
| `tool.execute.before` (`bash`) | `bash-enforce-ctx-shell.py` |
| `tool.execute.before` (`edit`/`write`) | `edit-tool-discipline.py` |
| `tool.execute.before` (alle befehls- und editiertragenden Tools) | `lean-ctx-policy-guard.py` |
| `permission.ask` | setzt `status = "deny"` statt nachzufragen |
| `tool.execute.after` | `lean-ctx hook observe` |

**Der Adapter bricht nie eine Sitzung.** Fehlt ein Skript, ist `python3` nicht da oder
antwortet der Hook nicht in 5 s, läuft der Tool-Aufruf durch und der Adapter schreibt
eine Notiz nach stderr. **Eine kaputte Härtung darf nicht schlimmer sein als keine.**

**Ablage:** `.opencode/plugins/` im Repo — opencode lädt Projekt-Plugins selbst, kein
Installationsschritt, keine Kopie nach `~/.config`. `.opencode/` ist nicht in
`.gitignore`; die Datei wird versioniert und damit ab Task 8 vom Sprach-Test bewacht.
Der Pfad zu den Hooks kommt aus `LEAN_HERDR_HOOKS_DIR` mit Voreinstellung
`~/.claude/hooks`; das Plugin zeigt nicht hart auf ein Claude-Verzeichnis.

**Übersetzt gegenüber dem Vorgängerplan** (Bereich 5282-5631): `SKRIPTE` → `SCRIPTS`,
`notiz` → `note`, `hookLaufen` → `runHook`, `beobachten` → `observe`, alle Locals
(`nutzlast`/`pfad`/`kind`/`aus`/`frist`/`entscheidung`/`skript`), alle Kommentare,
alle Testnamen und die Marker-Ausgaben des Node-Treibers
(`DURCHGELASSEN`/`ABGELEHNT`/`beobachtet`/`durchgelaufen`). Der stderr-Text bei
fehlendem Skript heißt `is missing` — `test_a_missing_script_lets_the_tool_through`
prüft genau dieses Wort.

`.opencode/plugins/lean-ctx-policy.js` (neu):

    /**
     * Runs the existing lean-ctx policy hooks under opencode.
     *
     * The adapter only translates the protocol -- it decides nothing. A rule
     * exists exactly once, in the Python scripts Claude Code already runs.
     */
    import { spawn } from "node:child_process";
    import { existsSync } from "node:fs";
    import { homedir } from "node:os";
    import { join } from "node:path";

    const HOOKS_DIR =
      process.env.LEAN_HERDR_HOOKS_DIR || join(homedir(), ".claude", "hooks");
    const TIMEOUT_MS = 5000;

    /** Tool name (lower-cased) -> the scripts in charge, in this order. */
    const SCRIPTS = {
      read: ["read-search-discipline.py"],
      grep: ["read-search-discipline.py"],
      glob: ["read-search-discipline.py"],
      list: ["read-search-discipline.py"],
      ls: ["read-search-discipline.py"],
      bash: ["bash-enforce-ctx-shell.py", "lean-ctx-policy-guard.py"],
      edit: ["edit-tool-discipline.py", "lean-ctx-policy-guard.py"],
      write: ["edit-tool-discipline.py", "lean-ctx-policy-guard.py"],
      patch: ["edit-tool-discipline.py", "lean-ctx-policy-guard.py"],
    };

    function note(text) {
      process.stderr.write(`[lean-ctx-policy] ${text}\n`);
    }

    /** Run one hook. Returns its decision or null. */
    function runHook(script, payload) {
      return new Promise((resolve) => {
        const path = join(HOOKS_DIR, script);
        if (!existsSync(path)) {
          note(`${script} is missing -- the tool runs through`);
          return resolve(null);
        }
        let child;
        try {
          child = spawn("python3", [path], { stdio: ["pipe", "pipe", "pipe"] });
        } catch (err) {
          note(`python3 not startable (${err.message}) -- the tool runs through`);
          return resolve(null);
        }
        let out = "";
        const timer = setTimeout(() => {
          child.kill("SIGKILL");
          note(`${script} did not answer within ${TIMEOUT_MS} ms -- the tool runs through`);
          resolve(null);
        }, TIMEOUT_MS);

        child.stdout.on("data", (b) => (out += b));
        child.on("error", (err) => {
          clearTimeout(timer);
          note(`${script}: ${err.message} -- the tool runs through`);
          resolve(null);
        });
        child.on("close", () => {
          clearTimeout(timer);
          try {
            resolve(JSON.parse(out)?.hookSpecificOutput ?? null);
          } catch {
            resolve(null);
          }
        });
        child.stdin.write(JSON.stringify(payload));
        child.stdin.end();
      });
    }

    /** Feed `lean-ctx hook observe`. Result-free and always without consequence. */
    function observe(payload) {
      return new Promise((resolve) => {
        let child;
        try {
          child = spawn("lean-ctx", ["hook", "observe"], {
            stdio: ["pipe", "ignore", "ignore"],
          });
        } catch (err) {
          note(`lean-ctx not startable (${err.message}) -- not observed`);
          return resolve();
        }
        const timer = setTimeout(() => {
          child.kill("SIGKILL");
          resolve();
        }, TIMEOUT_MS);
        child.on("error", () => {
          clearTimeout(timer);
          resolve();
        });
        child.on("close", () => {
          clearTimeout(timer);
          resolve();
        });
        child.stdin.write(JSON.stringify(payload));
        child.stdin.end();
      });
    }

    export const LeanCtxPolicy = async ({ project, directory }) => ({
      "tool.execute.before": async (input, output) => {
        const name = String(input.tool || "").toLowerCase();
        for (const script of SCRIPTS[name] ?? []) {
          const decision = await runHook(script, {
            tool_name: name,
            tool_input: output.args ?? {},
            cwd: directory ?? project?.worktree ?? process.cwd(),
            session_id: input.sessionID ?? null,
          });
          if (decision?.permissionDecision === "deny") {
            // Throwing blocks the tool call; opencode shows the reason as a tool
            // error. The turn continues -- never a session abort.
            throw new Error(
              decision.permissionDecisionReason || `[lean-ctx-policy] ${name} is blocked`,
            );
          }
          if (decision?.updatedInput) {
            Object.assign(output.args, decision.updatedInput);
          }
        }
      },

      "tool.execute.after": async (input, output) => {
        // `lean-ctx hook observe` feeds cache and ledger with what the tool
        // actually did -- the same payload shape as PostToolUse on Claude. It
        // decides nothing, prints nothing and exits 0; measured against
        // lean-ctx 3.10.1.
        await observe({
          tool_name: String(input.tool || "").toLowerCase(),
          tool_input: output.args ?? {},
          tool_response: output.output ?? output.result ?? {},
          cwd: directory ?? project?.worktree ?? process.cwd(),
          session_id: input.sessionID ?? null,
        });
      },

      "permission.ask": async (_permission, output) => {
        // No human sits at a worker pane. Asking means hanging.
        output.status = "deny";
      },
    });

`tests/test_policy_adapter.py` (neu) — dieselbe Entscheidung wie bei Claude, plus der
Ausfallpfad:

    import json
    import shutil
    import subprocess
    from pathlib import Path

    import pytest

    ROOT = Path(__file__).resolve().parents[1]
    ADAPTER = ROOT / ".opencode" / "plugins" / "lean-ctx-policy.js"
    HOOKS = Path.home() / ".claude" / "hooks"


    def test_the_adapter_is_project_local_and_does_not_hardwire_claude():
        text = ADAPTER.read_text(encoding="utf-8")
        assert "LEAN_HERDR_HOOKS_DIR" in text
        assert '".claude", "hooks"' in text, "only as a default, not hardwired"


    def test_every_mapped_hook_exists():
        text = ADAPTER.read_text(encoding="utf-8")
        for script in (
            "read-search-discipline.py",
            "bash-enforce-ctx-shell.py",
            "edit-tool-discipline.py",
            "lean-ctx-policy-guard.py",
        ):
            assert script in text, f"{script} is not mapped in the adapter"


    def test_the_adapter_throws_only_on_deny():
        text = ADAPTER.read_text(encoding="utf-8")
        assert 'permissionDecision === "deny"' in text
        assert "throw new Error" in text
        assert 'output.status = "deny"' in text, "permission.ask does not ask"


    def test_all_three_hook_points_are_wired():
        text = ADAPTER.read_text(encoding="utf-8")
        for point in ("tool.execute.before", "tool.execute.after", "permission.ask"):
            assert f'"{point}"' in text, f"{point} is missing from the adapter"
        assert '"hook", "observe"' in text, "tool.execute.after must feed lean-ctx"


    def node_driver(tmp_path: Path, body: str) -> subprocess.CompletedProcess:
        """Really load and call the adapter -- not just read its text."""
        if shutil.which("node") is None:
            pytest.skip("node not installed")
        driver = tmp_path / "driver.mjs"
        driver.write_text(body, encoding="utf-8")
        return subprocess.run(
            ["node", str(driver)], capture_output=True, text=True, timeout=30, check=False
        )


    @pytest.mark.integration
    def test_a_real_hook_denies_native_grep_through_the_adapter(tmp_path):
        """The same decision as on Claude -- and through the JS adapter.

        Calling the Python script directly only checks the script. Mis-mapped
        tool names, a badly translated payload or a swallowed `deny` would stay
        undetected -- exactly the failures that can ONLY live in the adapter.
        """
        if not (HOOKS / "bash-enforce-ctx-shell.py").is_file():
            pytest.skip("policy hooks not installed")
        proc = node_driver(
            tmp_path,
            f"""
            const {{ LeanCtxPolicy }} = await import({json.dumps(str(ADAPTER))});
            const hooks = await LeanCtxPolicy({{ directory: process.cwd() }});
            const output = {{ args: {{ command: "grep -r foo ." }} }};
            try {{
              await hooks["tool.execute.before"]({{ tool: "bash" }}, output);
              console.log("PASSED");
            }} catch (err) {{
              console.log("DENIED: " + err.message);
            }}
            """,
        )
        assert "DENIED:" in proc.stdout, f"stdout={proc.stdout} stderr={proc.stderr}"
        assert "ctx_" in proc.stdout, "the reason comes from the script, not the adapter"


    @pytest.mark.integration
    def test_the_adapter_reports_every_tool_call_to_lean_ctx(tmp_path):
        """tool.execute.after -> `lean-ctx hook observe`, or lean-ctx sees nothing."""
        if shutil.which("lean-ctx") is None:
            pytest.skip("lean-ctx not installed")
        # A stub instead of the real binary: the test measures the HANDOVER, it
        # must not change the state of lean-ctx.
        stub_dir = tmp_path / "bin"
        stub_dir.mkdir()
        transcript = tmp_path / "seen.json"
        (stub_dir / "lean-ctx").write_text(
            "#!/bin/sh\ncat > " + json.dumps(str(transcript))[1:-1] + "\n",
            encoding="utf-8",
        )
        (stub_dir / "lean-ctx").chmod(0o755)
        proc = node_driver(
            tmp_path,
            f"""
            process.env.PATH = {json.dumps(str(stub_dir))} + ":" + process.env.PATH;
            const {{ LeanCtxPolicy }} = await import({json.dumps(str(ADAPTER))});
            const hooks = await LeanCtxPolicy({{ directory: process.cwd() }});
            await hooks["tool.execute.after"](
              {{ tool: "Read" }},
              {{ args: {{ filePath: "README.md" }}, output: {{ content: "x" }} }},
            );
            console.log("observed");
            """,
        )
        assert "observed" in proc.stdout, proc.stderr
        seen = json.loads(transcript.read_text(encoding="utf-8"))
        assert seen["tool_name"] == "read", "the name is passed through lower-cased"
        assert seen["tool_input"] == {"filePath": "README.md"}
        assert seen["tool_response"] == {"content": "x"}


    @pytest.mark.integration
    def test_a_missing_script_lets_the_tool_through(tmp_path):
        """A broken hardening must not be worse than none."""
        if shutil.which("node") is None:
            pytest.skip("node not installed")
        driver = tmp_path / "driver.mjs"
        driver.write_text(
            f"""
            process.env.LEAN_HERDR_HOOKS_DIR = {json.dumps(str(tmp_path / "empty"))};
            const {{ LeanCtxPolicy }} = await import({json.dumps(str(ADAPTER))});
            const hooks = await LeanCtxPolicy({{ directory: process.cwd() }});
            const output = {{ args: {{ command: "grep -r foo ." }} }};
            await hooks["tool.execute.before"]({{ tool: "bash" }}, output);
            console.log("passed through");
            """,
            encoding="utf-8",
        )
        proc = subprocess.run(
            ["node", str(driver)], capture_output=True, text=True, timeout=30, check=False
        )
        assert "passed through" in proc.stdout, proc.stderr
        assert "is missing" in proc.stderr, "the outage is noted on stderr"

@call tdd(-k the_adapter_throws_only_on_deny)

@call tdd(-k all_three_hook_points_are_wired)

Run: `uv run pytest -q -m integration tests/test_policy_adapter.py` — Expected:
`3 passed` (oder skipped ohne `node`/Hooks/lean-ctx).

Run: `opencode run --agent reviewer "Read README.md with the read tool."` — Expected:
der Tool-Aufruf wird mit der Begründung aus `read-search-discipline.py` abgelehnt, und
die Sitzung läuft weiter.

### Verify & Close

@call verify(".opencode/plugins/lean-ctx-policy.js tests/test_policy_adapter.py")
@call de_scan(.opencode/plugins/lean-ctx-policy.js tests/test_policy_adapter.py)
@call gate(".opencode tests/test_policy_adapter.py")

Run: {{ var test_cmd }} — Expected: `277 passed, 10 deselected`.

@call commit(".opencode tests/test_policy_adapter.py", "feat(policy): opencode adapter on the existing lean-ctx hooks")
@call remember_decision("lean-herdr: der opencode-Policy-Adapter uebersetzt nur das Protokoll (stdin tool_name/tool_input -> stdout hookSpecificOutput.permissionDecision); fehlendes Skript, fehlendes python3 oder 5-s-Timeout lassen den Tool-Aufruf DURCH und schreiben nur nach stderr. Drei Hookpunkte: tool.execute.before (Policy), tool.execute.after (`lean-ctx hook observe`, folgenlos), permission.ask (deny statt haengen). Der Adaptertest faehrt durch den JS-Adapter, nicht am Python-Skript vorbei")
@phase-end

@phase "task-13"
## Task 13: Buchhaltung — die Regeln mit dem Durchgang versöhnen

**Files:** Modify `AGENTS.md`, `docs/lean-md/plans/2026-09-01-lean-herdr.lmd.md`,
`docs/specs/2026-09-01-lean-herdr-ctx-task-design.md`,
`docs/specs/2026-09-02-lean-herdr-englisch-und-plugin-design.md`.
**Interfaces:** Keine. Kein Code, kein Test ändert sich.

Vier Stellen behaupten nach diesem Plan etwas, das nicht mehr stimmt.

**1. `AGENTS.md` — „No translation sweeps" mit dem Durchgang versöhnen.**
Die Regel richtete sich gegen *beiläufiges* Halb-Übersetzen, nicht gegen einen
bewussten Durchgang. Sie bleibt stehen und bekommt zwei Sätze:

@call patch("AGENTS.md", "der Absatz 'No translation sweeps' unter ## Language")

Der Absatz lautet danach (englisch — `AGENTS.md` liegt außerhalb `docs/`):

    - **No translation sweeps.** German that already exists outside `docs/` stays put.
      It becomes English when something rewrites that file or section anyway — and
      then in full, never half.
      The one deliberate sweep ran on 2026-09-02 and left the tree English outside
      `docs/`; its plan is the one dated 2026-09-02 under `docs/lean-md/plans/`. This
      rule governs what comes after that sweep, and `tests/test_language.py` now
      enforces the result.

**Der Plan wird hier bewusst NICHT beim Namen genannt.** Sein Dateiname trägt das
Segment `-und-`, und `tests/test_language.py` tokenisiert über `-` und `.` hinweg:
`und` steht in `GERMAN_WORDS`, `AGENTS.md` ist versioniert und liegt außerhalb `docs/`
— der Pfad im Fließtext machte den Sprach-Test rot. Das Datum genügt, es gibt nur
einen Plan mit diesem Datum. **`AGENTS.md` gehört nicht in `EXCEPTIONS`**: das würde
ausgerechnet die Datei blenden, die die Regel aufstellt.

**2. `docs/lean-md/plans/2026-09-01-lean-herdr.lmd.md` — als historisch einfrieren.**
Ein Kopfvermerk direkt unter dem Titel:

@call patch("docs/lean-md/plans/2026-09-01-lean-herdr.lmd.md", "Kopfvermerk unter dem Titel")

    > **Eingefroren am 2026-09-02.** Die Code-Blöcke zeigen den Stand bei Abnahme.
    > Seit dem Sprach-Durchgang ist der Baum die Wahrheit, nicht mehr dieser Plan —
    > als Vergleichsgrundlage taugt er nicht. Seine drei offenen Tasks 14, 15 und 16
    > wurden **nicht** von hier ausgeführt, sondern aus
    > `docs/lean-md/plans/2026-09-02-lean-herdr-englisch-und-plugin.lmd.md`
    > (dort Task 9, 11 und 12), wo ihr Code übersetzt und gegen die heutigen Module
    > geprüft steht. Task 12 (Stufe-4-Durchlauf) bleibt offen.

**Abweichung von Spec §7, mit Grund.** Die Spec verlangt, die Blöcke von Task 14/15/16
„nachzuziehen". Der ausgeführte Code steht bereits übersetzt in diesem Plan; ihn ein
zweites Mal in ein ausdrücklich eingefrorenes Dokument zu kopieren, hielte zwei Kopien
derselben Sache in Deckung — genau das, wogegen der Einfrier-Vermerk gedacht ist. Der
Verweis erfüllt den Zweck (kein Leser schreibt mehr aus halb-deutschen Blöcken ab),
ohne die Duplikation. Wenn der Betreiber die wörtliche Fassung will, ist es ein
Ein-Zeilen-Nachtrag.

**3. `docs/specs/2026-09-01-lean-herdr-ctx-task-design.md:341-343` — überholt.**

@call patch("docs/specs/2026-09-01-lean-herdr-ctx-task-design.md", "der Absatz 'Der Plan-Code ist durchgehend deutsch benannt' unter '### Bewusst akzeptierte Abweichungen'")

    - Der Plan-Code war durchgehend **deutsch benannt**. Der Durchgang fand am
      2026-09-02 statt (`docs/lean-md/plans/2026-09-02-lean-herdr-englisch-und-plugin.lmd.md`);
      seither ist alles außerhalb `docs/` englisch und `tests/test_language.py` hält
      es so.

**4. `docs/specs/2026-09-02-lean-herdr-englisch-und-plugin-design.md` §2 — eine Zeile
der Bestandstabelle ist falsch gemessen.** Das ist eine Ergänzung über Spec §7 hinaus;
sie steht hier, weil die Spec sonst eine widerlegte Messung behält.

@call patch("docs/specs/2026-09-02-lean-herdr-englisch-und-plugin-design.md", "die Tabellenzeile '__main__.py ist heute unbenutzbar'")

    | `__main__.py` bleibt ohne `handlers.py` wirkungslos | `__main__.py:41` importiert
    `lean_herdr.handlers` **innerhalb** des `try` mit `except Exception`; jedes
    Subkommando endet mit exit 0 und einer stderr-Zeile — kein `ModuleNotFoundError`
    nach außen. `test_manifest.py::test_main_survives_a_missing_handlers_module`
    nagelt genau das fest. Task 15 macht die Subkommandos wirksam, es repariert
    keinen Absturz. |

### Verify & Close

@call verify("AGENTS.md docs/")

Run: {{ var test_cmd }} — Expected: `277 passed, 10 deselected` (unverändert; dieser
Task fasst keinen Code an).
Run: {{ var test_cmd }} tests/test_language.py — Expected: PASS. `AGENTS.md` liegt
außerhalb `docs/` und muss englisch bleiben.

@call commit("AGENTS.md docs/", "docs: reconcile the language rule and freeze the predecessor plan")
@call remember_decision("lean-herdr: der bewusste Sprach-Durchgang fand am 2026-09-02 statt. AGENTS.md haelt 'No translation sweeps' aufrecht und nennt den Durchgang als einmalige Ausnahme; 2026-09-01-lean-herdr.lmd.md ist eingefroren und verweist fuer seine Tasks 14/15/16 auf 2026-09-02-lean-herdr-englisch-und-plugin.lmd.md; sein Task 12 (Stufe-4-Durchlauf) bleibt offen und braucht eine eigene Spec")
@phase-end
