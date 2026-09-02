# lean-herdr — Englisch ausserhalb `docs/` und Abschluss des Plugins

**Stand:** 2026-09-02 · **Status:** abgenommen, Plan ausstehend
**Ausgangspunkt:** Branch `feat/lean-herdr` nach dem `ctx_task`-Umbau
(`docs/lean-md/plans/2026-09-02-lean-herdr-ctx-task.lmd.md`, alle sieben Tasks
abgenommen). 238 Tests gruen, 7 Integrationstests gruen, `ruff check` sauber.

## 1. Zweck

Zwei Dinge, die zusammengehoeren, weil das eine das andere sonst zurueckdreht:

1. **Uebersetzung.** `AGENTS.md` verlangt seit Commit `36fc9f7` Englisch fuer
   alles ausserhalb `docs/`. 26 Dateien tragen noch Deutsch. Bisher galt „keine
   Uebersetzungs-Feldzuege" — der Betreiber hat am 2026-09-02 entschieden, den
   Durchgang jetzt bewusst zu fahren.
2. **Plugin-Abschluss.** Die Tasks 14 (`digest.py`), 15 (`handlers.py`) und 16
   (opencode-Policy-Adapter) des Vorgaengerplans `2026-09-01-lean-herdr.lmd.md`
   sind offen. Ihr Plan-Code traegt **deutsche Testnamen** — wer sie woertlich
   abschreibt, fuehrt genau das Deutsch wieder ein, das die Uebersetzung
   beseitigt. Deshalb eine Spec, nicht zwei.

## 2. Gemessener Ausgangsbestand

| Befund | Beleg |
|---|---|
| 26 Dateien ausserhalb `docs/` tragen deutsche Prosa | Wortlisten-Scan, Treffer je Datei: `join.py` 32, `worktree.py` 31, `bus.py` 29, `herdr.py` 27, `test_join.py` 18, `export.py` 17, … |
| **genau ein** deutscher oeffentlicher Name | `lean_herdr.bus.parse_zeit`, 5 Stellen (`bus.py:62`, `bus.py:122`, `test_bus_parse_registry.py:13,51,54`) |
| **80** deutsche Testnamen in 9 Testdateien | `test_export.py` 13, `test_join.py` 13, `test_herdr.py` 12, `test_bus_parse_registry.py` 11, `test_worktree.py` 8, `test_config_files.py` 6, `test_manifest.py` 4, `test_config.py` 3, `test_bus_canonical_root.py` 1 (im Spec-Review nachgemessen; eine fruehere Zaehlung von ~51 war zu niedrig) |
| deutsche **private** Namen und ein oeffentlicher Parameter | `bus._NANOSEKUNDEN`; `join._stat_felder`, `join._juengster_agent_id`, und `join.process_ancestors(..., max_schritte=32)` — letzterer steht in einer oeffentlichen Signatur, wird aber von keinem Aufrufer benannt uebergeben |
| `tests/fixtures/*.json` tragen deutsche Prosa | `registry.sample.json` 3 Stellen, `tasks.sample.json` 2 (z. B. `"Bau die Funktion foo."`) — eingefrorene echte Aufnahmen |
| `.pytest_cache/v/cache/nodeids` traegt 29 deutsche Test-IDs | wird bei **jedem** Lauf neu geschrieben — ein Scan ueber „alles ausserhalb `docs/`" waere nach dem ersten `pytest` rot |
| frische Regression aus dem `ctx_task`-Lauf | `dispatch.py:303-307` traegt `eintrag` und `pfad` in einer sonst vollstaendig englischen Datei |
| Uebersetzung hat **keine** dateiuebergreifende Wirkung | nur `parse_zeit` kreuzt Modulgrenzen; Kommentare und Locals sind lokal |
| das Loeschen von `leanctx.py` **bricht Task 15** | `from lean_herdr.leanctx import LeanCtx, newest_handoff` (Planzeile 4849); `_kontext()` ist ganz auf `session_resume()` / `handoff_list()` / `handoff_show()` gebaut (4896-4910); `CtxAntwort` unterscheidet dort die drei Faelle Fehler/leer/Inhalt (4885, 5279); die `welt`-Fixture monkeypatcht `lean_herdr.leanctx.*` (5061, 5071-5073, 5117, 5123-5125). Task 14 und 16 sind frei davon. |
| `__main__.py` ist heute unbenutzbar | `__main__.py:41` importiert `lean_herdr.handlers`, das es nicht gibt — jedes Subkommando endet im `ModuleNotFoundError`. Task 15 schliesst das. |
| Plan-Code von Task 14/15/16 ist halb deutsch | Produktionsnamen englisch (`strip_frame`, `render_digest`, `summary_token`), Testnamen deutsch (`test_der_fertige_digest_wird_uebernommen_nicht_nachgebaut`), Fixture `welt` |

## 3. Umfang

**Drin**

- Strang A: vollstaendiges Englisch ausserhalb `docs/` — Bezeichner, Kommentare,
  Docstrings, Testnamen, `parse_zeit` → `parse_time`, plus die
  `dispatch.py`-Regression.
- Strang A Abschluss: `tests/test_language.py` macht die Regel durchsetzbar.
- Strang B: Vorgaenger-Tasks 14, 15, 16.
- Buchhaltung: `AGENTS.md`, Einfrier-Vermerk im Vorgaengerplan, Richtigstellung
  eines ueberholten Spec-Absatzes.

**Draussen** (Ablehnungsgrund im Review, kein Versaeumnis)

- **Strang C vollstaendig** — Task 12 (Stufe-4-Durchlauf mit Merge), die
  Kostenmessung `minimal` vs. `standard` und der Beweis des
  `kind="claude"`-Pfades von `session_error()`. Das sind Betriebsdurchlaeufe mit
  echten Agenten und echten Kosten, die ein Implementer-Subagent nicht ausfuehren
  kann. Eigene Spec, wenn der Betreiber den Durchlauf fahren will.
- Die Prosa unter `docs/` bleibt deutsch.
- Keine Verhaltensaenderung. Kein Refactoring ueber Umbenennungen hinaus. Keine
  Behebung der fuenf Funktionen ueber der Komplexitaetsschwelle 15
  (`export.find_error` 22, `dispatch.dispatch` 18, `bus.parse_registry` 17,
  `dispatch.wait_for_agent_id` 16, `export.opencode_messages` 16).

## 4. Die tragende Regel der Uebersetzung

**Uebersetzt werden:** Bezeichner (Locals, Parameter, Funktionen, Klassen,
Konstanten), Kommentare, Docstrings, Testnamen.

**Nie uebersetzt werden String-Literale** — ausser sie sind unverkennbar Prosa
fuer Menschen. Unantastbar bleiben:

- Protokoll-Token: `VERDIKT:` (`dispatch.VERDICT_RE` ist die Autoritaet)
- Registry- und JSON-Schluessel: `scratchpad`, `pid`, `expires_at`, `repo_root`, …
- CLI-Flags und Unterkommandos: `--no-focus`, `pane split`, `worktree open`, …
- Umgebungsvariablen: `LEAN_CTX_TOOL_PROFILE`, `LEAN_CTX_ROLE`, `LEAN_CTX_DATA_DIR`
- **Testdaten**: `parse_zeit("morgen frueh")` in `test_bus_parse_registry.py:54`
  ist die Probe „etwas, das `fromisoformat` nicht parsen kann". Ein
  wohlmeinendes `"2026-01-01"` dreht den Test still um.
- **`tests/fixtures/registry.sample.json` und `tests/fixtures/tasks.sample.json`
  bleiben unangetastet.** Es sind eingefrorene Aufnahmen echter lean-ctx-Daten
  (`"Bau die Funktion foo."`, `"brauche eine Entscheidung zum Datenmodell"`),
  festgenagelt von `test_the_frozen_sample_has_the_expected_shape`. Wer sie
  uebersetzt, faelscht die Messung, auf der `parse_registry()` und
  `lean_herdr.tasks` beruhen.

**Der Test fuer „ist das Prosa?"** lautet nicht „klingt es deutsch?", sondern:
*bekommt ein Mensch diesen String je zu Gesicht?* Eine Fehlermeldung auf stdout
ja — ein Wert, den Code vergleicht, parst oder als Schluessel benutzt, nein, auch
wenn er wie ein Satz aussieht. Im Zweifel bleibt der String stehen: ein
unuebersetzter Satz ist ein Schoenheitsfehler, ein uebersetzter Schluessel ist
ein Defekt.

Ist ein String doch Prosa fuer den Betreiber und ein Test nagelt ihn fest,
wandert die Erwartung **im selben Commit** mit.

## 5. Zuschnitt Strang A

Ein Task je Modul, Produktionsdatei und ihr Test zusammen — so liegt jede
Umbenennung mit ihren Aufrufstellen in einem Commit und ein Review sieht eine
ueberschaubare Flaeche.

| Task | Dateien | Besonderheit |
|---|---|---|
| A1 | `lean_herdr/bus.py`, `tests/test_bus_parse_registry.py`, `tests/test_bus_canonical_root.py` | `parse_zeit` → `parse_time` (5 Stellen) und `_NANOSEKUNDEN`; der **Wert** von `MESSAGES_KEY` bleibt `"scratchpad"`, die Fixture `registry.sample.json` bleibt unberuehrt |
| A2 | `lean_herdr/export.py`, `tests/test_export.py` | groesste Local-Flaeche (18 Treffer, 10 deutsche Testnamen) |
| A3 | `lean_herdr/join.py`, `tests/test_join.py` | 32 + 18 Treffer; `_stat_felder`, `_juengster_agent_id` und der oeffentliche Parameter `process_ancestors(..., max_schritte=)` |
| A4 | `lean_herdr/herdr.py`, `tests/test_herdr.py` | |
| A5 | `lean_herdr/worktree.py`, `tests/test_worktree.py` | `find_worktree`s `eintrag` |
| A6 | `lean_herdr/config.py`, `lean_herdr/__main__.py`, `tests/test_config.py`, `tests/test_config_files.py`, `tests/test_manifest.py` | **muss vor Strang B liegen** — B baut darauf auf. Konkreter Fall der Prosa-Regel aus §4: die stderr-Texte von `__main__.py` („unbekannter Subcommand", „fehlgeschlagen") sind Prosa fuer den Betreiber und von `test_manifest.py:68` festgenagelt — Text und Erwartung wandern im selben Commit |
| A7 | `dispatch._worker_root` (die `eintrag`/`pfad`-Regression), `tests/doubles.py`, `tests/test_tool_profile.py`, Reste in `tests/test_dispatch*.py`, `bin/herdr-dispatch`, `pyproject.toml`, `opencode.jsonc`, `herdr-plugin.toml`, `.config/wt.toml`, `lean_herdr/__init__.py` | Abschluss-Scan ueber den ganzen Baum |
| A8 | `tests/test_language.py` (neu) | landet zuletzt, damit er beim Landen gruen ist und danach Strang B bewacht |

**Tor je Task:** `uv run pytest -q` mit unveraenderter Anzahl, `uv run ruff check .`
sauber, Deutsch-Scan ueber die beruehrten Dateien = 0 Treffer.

### A8 — `tests/test_language.py`

Das Projekt schuetzt die Rollentexte bereits durch gezielte Tests statt durch
Disziplin (`tests/test_role_prohibitions.py`, 13 Verbotssaetze). Der Sprach-Test
ist dessen Nachfolger fuer den Code.

- **Der Umfang ist `git ls-files`, nicht das Dateisystem.** Das ist die tragende
  Festlegung: ausserhalb `docs/` liegen auch `.pytest_cache/v/cache/nodeids` (29
  deutsche Test-IDs, bei **jedem** Lauf neu geschrieben), `__pycache__/*.pyc`,
  `scratch.md`, `.lean-ctx/`, `.claude/skills/` und `uv.lock`. Ein Scan ueber das
  Dateisystem waere nach dem ersten `pytest` rot. Der Test nimmt die versionierten
  Dateien, zieht `docs/` ab und ueberspringt Binaerdateien.
- Scannt gegen eine **kuratierte** Liste deutscher Funktionswoerter, mit
  Wortgrenzen — sonst schlaegt `die` in `diet` an.
- Traegt eine **explizite Ausnahmeliste** fuer die unantastbaren Token aus §4,
  namentlich `tests/fixtures/*.json`; jede Ausnahme mit einer Zeile Begruendung
  im Code.
- Prueft ausdruecklich auch `ae`/`oe`/`ue`/`ss`-Transliterationen, weil die dem
  Wortlisten-Scan sonst entgehen.

## 6. Zuschnitt Strang B

| Task | Inhalt | Haengt an |
|---|---|---|
| B1 | Vorgaenger-Task 14 — `lean_herdr/digest.py` | — |
| B2a | `lean_herdr/leanctx.py` + `tests/test_leanctx.py` aus `72dee2f^` zurueckholen, im selben Zug englisch | A6 |
| B2b | Vorgaenger-Task 15 — `lean_herdr/handlers.py` | B1, B2a |
| B3 | Vorgaenger-Task 16 — `.opencode/plugins/lean-ctx-policy.js`, `tests/test_policy_adapter.py` | — (geprueft: keine `lean_herdr`-Importe in seinem Planbereich) |

Abgeschrieben aus `docs/lean-md/plans/2026-09-01-lean-herdr.lmd.md` (Bereiche
4595-4775, 4775-5280, 5282-5631), mit zwei Auflagen:

1. **Testnamen und Fixtures werden beim Abschreiben englisch gesetzt** (`welt` →
   `world`). Die Produktionsnamen sind dort bereits englisch.
2. **Der Plan-Code ist aelter als der Umbau.** Er entstand, als es `leanctx.py`
   noch gab und `settings.py` noch nicht. Ein Widerspruch ist bereits gefunden
   und in B2a aufgeloest (siehe unten); jeder B-Task prueft seine uebrigen
   Importe und Annahmen gegen die **heutigen** Module und **meldet** einen
   weiteren Widerspruch als Befund, statt still anzupassen.

### B2a — warum `leanctx.py` zurueckkommt

Das Modul wurde im `ctx_task`-Lauf als tot geloescht (`72dee2f`). Das war auf dem
damaligen Stand richtig — kein Produktionscode importierte es —, aber das Wissen
war unvollstaendig: Task 15 baut `_kontext()` vollstaendig darauf auf. Der
Betreiber hat am 2026-09-02 entschieden, es aus der Historie zurueckzuholen statt
es nachzubauen. Gruende: es war gemessen und getestet, es kapselt eine
abgenommene Invariante (`--project-root` bei **jedem** Aufruf) und `CtxAntwort`
unterscheidet Fehler, gueltig-leer und Inhalt — drei Faelle, die `_kontext()`
auseinanderhalten muss und die ein `dict` nicht hergibt.

B2a stellt `lean_herdr/leanctx.py` und `tests/test_leanctx.py` aus `72dee2f^`
wieder her und uebersetzt sie im selben Zug ins Englische. Die Wiederherstellung
ist woertlich; Abweichungen vom geloeschten Stand sind Befunde, keine
Verbesserungen.

## 7. Buchhaltung (ein Task, zuletzt)

- **`AGENTS.md`** — die Zeile „No translation sweeps" mit diesem Vorhaben
  versoehnen. Sie richtete sich gegen *beilaeufiges* Halb-Uebersetzen, nicht
  gegen einen bewussten Durchgang. Festhalten, dass der Durchgang am 2026-09-02
  stattgefunden hat und die Regel ab da regelt, was danach kommt.
- **`docs/lean-md/plans/2026-09-01-lean-herdr.lmd.md`** — Kopfvermerk, der ihn
  als historisch einfriert: die Code-Bloecke zeigen den Stand bei Abnahme, seit
  der Uebersetzung ist der Baum die Wahrheit, nicht mehr als
  Vergleichsgrundlage verwenden. Nachgezogen werden **nur** die Bloecke der noch
  offenen Tasks 14/15/16.
- **`docs/specs/2026-09-01-lean-herdr-ctx-task-design.md:341-343`** — der Absatz
  „Der Plan-Code ist durchgehend deutsch benannt; der Betreiber uebersetzt am
  Stueck nach dem Lauf" ist ueberholt und wird richtiggestellt.

## 8. Testen

Strang A fuehrt **kein neues Verhalten** ein, also keine neuen Verhaltenstests.
Die vorhandenen 238 sind das Netz. Zwei Zusaetze:

- `tests/test_language.py` (A8) macht die Sprachregel durchsetzbar.
- Strang B bringt seine Tests aus dem Vorgaengerplan mit.

**Nachweispflicht je A-Task:** nicht nur die *Anzahl* der Tests bleibt gleich,
sondern die **Liste der gesammelten Test-IDs** wird vorher/nachher verglichen.
Eine Umbenennung, die versehentlich zwei Tests zu einem verschmilzt, haelt die
Anzahl nicht — aber eine, die einen Test loescht und einen anderen doppelt
anlegt, koennte es. Der ID-Vergleich faengt beides.

## 9. Risiken

| Risiko | Gegenmittel |
|---|---|
| Ein mituebersetzter **Datenstring** dreht einen Test still um | §4 verbietet String-Literale; kleine Diffs je Task machen es sichtbar |
| Ein Test geht beim Umbenennen verloren | Vergleich der gesammelten Test-IDs, nicht nur der Anzahl (§8) |
| B's Plan-Code passt nicht mehr zum Baum | B-Tasks pruefen Importe gegen die heutigen Module und melden Widersprueche (§6) |
| Der Sprach-Test schlaegt falsch an | Wortgrenzen, kuratierte Liste, explizite Ausnahmeliste mit Begruendung (§5, A8) |
| `parse_time` bricht einen Aufrufer | 5 bekannte Stellen, `ctx_refactor` fuer die Umbenennung, gruene Suite als Tor |

## 10. Reihenfolge

```
A1 → A2 → A3 → A4 → A5 → A6 → A7 → A8 → B1 → B2a → B2b → B3 → Buchhaltung
```

Zwoelf Tasks. Echte Abhaengigkeiten: A6 vor B · B1 und B2a vor B2b · A8 landet
nach A7, damit er beim Landen gruen ist und danach Strang B bewacht. A1-A5 sind
untereinander unabhaengig und koennten parallel laufen; die Reihenfolge steht
nur, damit Reviews eine ruhige Flaeche sehen.

B2a bringt die Tests von `test_leanctx.py` zurueck, B1/B2b/B3 bringen eigene mit —
die Testanzahl waechst also ab B1. Die Regel „Anzahl unveraendert" aus §5 gilt nur
fuer die A-Tasks; ab B gilt: **kein Test verschwindet**, gemessen am Vergleich der
gesammelten Test-IDs.
