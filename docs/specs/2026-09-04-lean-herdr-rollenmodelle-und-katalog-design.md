# lean-herdr: Modelle aus der Config, curl raus, Katalog rein — Design v1.0

**Stand:** 2026-09-04 · **Status:** entworfen, nicht implementiert
**Anlass:** Welches Modell eine Rolle bekommt, entscheidet heute der Orchestrator
im Lauf — aus einer Prosa-Tabelle in seinem eigenen Prompt, in der `sonnet` hart
steht. Es gibt keinen Ort, an dem `orchestrator = X`, `builder = Y`,
`reviewer = Z` steht und den man ändern kann, ohne einen Rollenprompt
umzuschreiben. Und die eine HTTP-Stelle des Projekts ist ein `curl`-Subprozess.
**Betrifft:** `lean_herdr/settings.py`, `lean_herdr/dispatch.py`,
`lean_herdr/workspace.py`, `lean_herdr/handlers.py`, `lean_herdr/llm.py`,
`lean_herdr/cli.py`, `lean_herdr/initcmd.py`,
`lean_herdr/templates/config.toml`, `.lean-ctx/lean-herdr/roles/orchestrator.md`,
`README.md`, `.gitignore` — neu: `lean_herdr/openrouter.py`,
`lean_herdr/catalog.py`

---

## 1. Ausgangslage, gemessen

### 1.1 Wo Modelle heute herkommen

| Rolle | Herkunft des Modells | Wo konfigurierbar |
|---|---|---|
| Orchestrator | `[workspace].model` → `--model` an opencode | ja |
| Builder | `dispatch --model`, Pflichtflag, vom Orchestrator gewählt | **nein** |
| Reviewer | dito | **nein** |

`dispatch --model` ist im Build-Modus Pflicht (`dispatch.py:586`,
`missing_flags()` mit cc=45). `agent_args(kind, model, role_file)`
(`dispatch.py:158-166`) setzt `--model` immer. Die Wahl trifft der Orchestrator
nach dieser Tabelle in seinem Prompt:

```
| Write, rebuild, test code      | builder  | claude   | sonnet                |
| Check what the builder built   | reviewer | opencode | a different one       |
```

**Die Rollen-Tabellen gibt es dabei längst.** `.lean-ctx/lean-herdr/config.toml`
ist byte-identisch mit dem Template und hat **null aktive Zeilen** — alles
auskommentiert, sodass das Projekt sich ohne die Datei genauso verhält. Was sie
zeigt, ist trotzdem die Struktur, die `settings.py` kennt:

| Block | zeigt heute | Modell? |
|---|---|---|
| `[roles.orchestrator]` | `profile` | **nein** |
| `[roles.builder]` | `direction` | **nein** |
| `[roles.reviewer]` | `ratio` | **nein** |
| `[llm]` | `model`, `prereview_model`, beide `effort` | ja — aber nur für `llm.py` |
| `[workspace]` | `label`, `kind`, `model` | ja — nur der Orchestrator-Pane |

Die drei Rollen-Blöcke tragen Pane-Geometrie und Kontext-Profil und **keinen
`model`-Schlüssel**, nicht einmal auskommentiert: `RoleSettings` hat das Feld
nicht. Und `[llm].model` ist der Verwechslungskandidat — sein eigener Kommentar
sagt „Read by `lean_herdr/llm.py` alone"; mit dem, womit Builder und Reviewer
arbeiten, hat es nichts zu tun.

Das ist der Grund, warum Abschnitt 3 die **kleinstmögliche** Änderung ist:
`[roles.builder]` und `[roles.reviewer]` sind vorhandene Tabellen, die zwei
Schlüssel dazubekommen. Es entsteht keine neue Struktur, und wer die Datei heute
liest, findet die neuen Zeilen dort, wo er sie erwartet.

### 1.2 Der Commit-Pfad läuft auf dem System-Interpreter

`bin/herdr-llm` beginnt mit `#!/usr/bin/env python3` und macht ein
`sys.path.insert` auf das Repo — kein venv, kein `uv run`. Gemessen auf dieser
Maschine:

```
/usr/bin/python3   3.14.7   venv: False
httpx     : ABSENT
tomli_w   : ABSENT
certifi   : present
```

worktrunk startet `bin/herdr-llm generate` als `commit.generation.command` bei
**jedem Commit in jedem Repository der Maschine**. Ein `import httpx` in
`lean_herdr/llm.py` bricht diesen Pfad, solange httpx nicht systemweit
installiert ist. `pyproject.toml` führt heute `dependencies = []`.

### 1.3 Import-Kosten, gleicher Interpreter, 7 Läufe, Median

| Modul | Median | über Basis |
|---|---|---|
| `sys` (Basis) | 13,9 ms | — |
| `json` | 18,3 ms | +4 ms |
| **`urllib.request`** | **40,6 ms** | **+27 ms** |
| `httpx` | 79,5 ms | +66 ms |

Zur Fairness: **beide** Varianten sind schneller als heute, denn der jetzige Weg
importiert `subprocess` *und* forkt einen vollständigen `curl`-Prozess. Der
Import-Unterschied ist nicht das Hauptargument — das ist 1.2.

### 1.4 Was der OpenRouter-Katalog wirklich beantwortet

Abgefragt am 2026-09-04 gegen `https://openrouter.ai/api/v1/models`:

| Abruf | Ergebnis |
|---|---|
| `?sort=pricing-low-to-high&limit=4&supported_parameters=tools,reasoning` | **funktioniert** — genau 4 Einträge, dazu `total_count: 261` und `links.next` |
| `?search=glm` bzw. `?search=gemini 3` | **wird ignoriert** — beide liefern identische Antworten |
| `?category=programming` | **HTTP 400** |

Ohne Key beantwortet. Jeder Eintrag trägt
`pricing.{prompt,completion}`, `context_length`, `supported_parameters`,
`reasoning.{mandatory,supported_efforts,default_effort}` und — sofern vorhanden —
`benchmarks.artificial_analysis.{intelligence_index,coding_index,agentic_index}`.

**Folgerung:** „billigstes Modell, das Tools und Reasoning kann und einen
`coding_index` über N hat" ist ein **einziges deterministisches GET** plus ein
Zahlenvergleich. Ein Tool-Calling-Loop davor würde ein Modell dafür bezahlen,
Query-Parameter zu wählen, die ein Flag exakt ausdrückt. Tool-Calling ist
deshalb **nicht** Teil dieses Designs; es kommt zurück, wenn ein Verbraucher
auftaucht, der ohne Werkzeuge wirklich nicht auskommt — der Prereview-Judge mit
seinem `MAX_DIFF_BYTES`-Cap wäre ein Kandidat, ist aber ein eigener Spec.

### 1.5 Ein Nebenfund, der die Automatik bedingt

`EFFORTS = ("minimal", "low", "medium", "high")` in `settings.py` ist statisch.
Der Katalog meldet für `google/gemini-3.8-flash` aber
`supported_efforts: ["high","medium","low"]` und `mandatory: true` — **kein
`minimal`**, während `GENERATE_EFFORT = "minimal"` gesetzt ist. Ein automatisch
gewähltes Modell kann den konfigurierten Effort also schlicht nicht können.
Ohne Gegenprüfung schriebe der Tagescheck eine Kombination, die beim nächsten
Commit als HTTP-Fehler zurückkommt und in eine Fallback-Message verschwindet —
also aussieht wie ein fehlender Key.

### 1.6 Produktions-LOC, gemessen (nicht `wc -l`)

`llm.py`: **352 Prod-LOC** (751 physisch). `dispatch.py`: 529 (842).
`settings.py`: 191 (430). Kein Modul ist am 800er-Limit; `dispatch.py` ist dem
600er-Ziel am nächsten und wächst in diesem Design nur um wenige Zeilen.

---

## 2. Modulschnitt

| Modul | Aufgabe | Importiert von |
|---|---|---|
| **`openrouter.py`** *(neu)* | Alles, was OpenRouter kennt: Basis-URL, `api_key()`, die eine `request()`-Funktion über `urllib` | `llm.py`, `catalog.py` |
| **`catalog.py`** *(neu)* | Modellkatalog: GET `/models`, Filter, Schwellen, Empfehlung, Schreiben des Overlays | `cli.py`, `workspace.py` |
| `llm.py` | Unverändert in der Aufgabe: `complete()`, `generate()`, `prereview()` — ohne curl | `bin/herdr-llm`, `dispatch.py` |

Die Schnittlinie hat einen harten Grund: `api_key()` liegt heute in `llm.py`, ist
aber OpenRouter-Wissen und nicht Completion-Wissen — beide Verbraucher brauchen
es. Und **`llm.py` darf `catalog.py` niemals importieren**: der Commit-Pfad läuft
unter `/usr/bin/python3` bei jedem Commit; Katalog-Code hat dort nichts zu
suchen. Die Namen folgen `herdr.py` / `leanctx.py` — ein Modul heißt nach dem,
mit dem es spricht.

---

## 3. Teil A — Rollen bekommen Modell und `kind`

### 3.1 `settings.py`

`RoleSettings` bekommt zwei Felder:

```python
model: str = ""     # "" = nicht gesetzt, wie in LlmSettings
kind: str = ""      # "" = nicht gesetzt; validiert gegen KINDS
```

`ALLOWED` und `_TYPES` wachsen entsprechend mit. `_validate()` prüft: `kind` ist
leer oder in `KINDS`.

Neben dem bestehenden `PROFILE_BY_ROLE = {"orchestrator": "minimal"}` tritt

```python
KIND_BY_ROLE = {"orchestrator": "opencode"}
```

Damit behält der Orchestrator sein heutiges Verhalten — auch auf der
Keystroke-Route (`handlers.handle_bootstrap`), die bewusst mit eingebauten
Defaults arbeitet und keine Config liest. Worker haben keinen eingebauten `kind`:
sie müssen ihn sagen, per Flag oder per Config.

`WorkspaceSettings` verliert `model` und `kind` und behält `label`.
`WORKSPACE_ALLOWED` schrumpft dadurch automatisch, sodass `[workspace].model`
zu einem `SettingsError` wird — aber die generische Meldung („unknown keys
`['model']`; allowed: `['label']`") schickt den Leser in die Irre. Es braucht
**eine gezielte Zeile pro umgezogenem Schlüssel**:

```
workspace.model has moved to [roles.orchestrator].model
workspace.kind has moved to [roles.orchestrator].kind
```

Das ist die Sorte Meldung, die dieses Modul ohnehin schreibt: „whoever writes
`direction = "links"` and silently gets `right` will hunt the bug in the wrong
place".

### 3.2 Reviewer und Builder auf demselben Modell — erlaubt, aber sichtbar

`roles/orchestrator.md` sagt heute: *„The reviewer's value is that it is a
different model — never take the same model as for the builder."* Sobald der
Orchestrator nicht mehr wählt, ist diese Prosa wirkungslos. Sie wandert in die
Config — **als Warnung, nicht als Verbot**:

| `builder.model` vs. `reviewer.model` | `[roles.reviewer].shares_builder_model` | Verhalten |
|---|---|---|
| verschieden | egal | still |
| gleich | nicht gesetzt (Default `false`) | **Warnung**, nichts bricht |
| gleich | `true` | still — bewusst so gemeint |

Die Warnung reist in einem additiven `warnings: [...]`-Schlüssel der JSON-Zeile
von `dispatch` (Build-Modus, Rolle `reviewer`) — dort liest der Orchestrator sie
tatsächlich — und in der bereits bestehenden Warnungsliste von
`initcmd._warnings()`.

`shares_builder_model` ist ein `bool` und gehört zu `_NO_BOOL` **nicht** dazu:
hier ist ein `bool` der richtige Typ, kein durchgerutschter.

### 3.3 `dispatch.py`

`--model` und `--kind` bleiben **Pflicht**, aber erfüllbar aus der Config.
`main()` liest die Settings ohnehin genau einmal für beide Modi
(`test_main_loads_the_config_once_for_both_modes`); dort werden `args.model` und
`args.kind` aus `settings_for(role)` aufgefüllt, **bevor** `missing_flags()`
läuft. Damit bleibt die Funktion mit cc=45 unangetastet und die Präzedenz steht
an einer Stelle:

```
dispatch model:  --model  >  [roles.<role>].model     -> sonst missing_flags
dispatch kind:   --kind   >  [roles.<role>].kind      -> sonst missing_flags
```

`dispatch()` selbst bekommt weiterhin einen `DispatchRequest` mit fertig
entschiedenen Werten und löst nichts auf — dasselbe Prinzip, das `complete()` in
`llm.py` trägt („this function resolves NOTHING but the key").

**Warum die Pflicht bleibt**, statt „leer = kein `--model`" zuzulassen: ein
Worker, der stillschweigend auf dem Default-Modell seiner Runtime baut, kostet
echtes Geld, und niemand sieht es. Der Orchestrator behält seine Ausnahme, weil
sie dort seit jeher gilt (`[workspace].model = ""` heißt „kein `--model` an
opencode") und die Keystroke-Route sie braucht.

### 3.4 `workspace.py` und `handlers.py`

`start_orchestrator()` bekommt `model` und `kind` **einzeln** durchgereicht, so
wie heute schon `profile` und `ready_timeout_s` aus `[roles.orchestrator]`
kommen. Die Signatur zeigt dann, was die Funktion wirklich braucht; `settings:
WorkspaceSettings` bleibt für `label`. `missing_agent_config(root, kind)`
bekommt den `kind` aus derselben Quelle.

`handle_bootstrap` nimmt weiter die eingebauten Defaults — durch `KIND_BY_ROLE`
ist das unverändert `opencode`, und `model` bleibt leer.

### 3.5 Rollenprompt und Template

`roles/orchestrator.md`: Die Tabelle „Task | Worker | kind | Model" mit dem
hartkodierten `sonnet` entfällt. An ihre Stelle tritt: Modell und `kind` stehen
in der Config, lass die Flags weg. Der Satz über die verschiedenen blinden
Flecken des Reviewers bleibt — er begründet jetzt einen Config-Schlüssel statt
eine Wahl im Lauf.

`templates/config.toml` bekommt die neuen Schlüssel als kommentierte Blöcke,
in der Form, die die Datei schon hat.

`templates/opencode.jsonc` wird **nicht** angefasst: opencode nimmt das Modell
vom CLI, nicht aus `agent.<name>`.

---

## 4. Teil B — curl raus, `urllib` rein

### 4.1 Die eine HTTP-Funktion

In `openrouter.py`:

```python
def request(url, *, method="GET", headers=None, body=None, timeout_s) -> str | None
```

Nie werfend, Body als `str` oder `None`. Das ist exakt das Fehlerprofil, das
`complete()` heute nach außen hat: kein Key, Prompt über dem Cap, Transport
gescheitert, Exit ≠ 0, unparsbarer Body, leerer String — alles `None`, und jeder
Aufrufer macht daraus sein eigenes sicheres Verhalten. Ein `raise` erreichte
worktrunk als gescheitertes `commit.generation.command`, und das ist fatal.

### 4.2 Was in `llm.py` wegfällt

- `_tempfile()` samt beider Aufrufe (curl-Config **und** Payload)
- der `try/finally` mit den zwei `unlink(missing_ok=True)`
- `errors="replace"` und der Kommentar über strikte Dekodierung beider Pipes
- der Kommentar über curls `max-time = 0`
- `subprocess` im HTTP-Pfad (bleibt für `wt_diff()`, dort ist es richtig)

Netto ein Abbau. `MAX_PROMPT_BYTES`, `_content()`, `_unfence()`,
`fallback_message()`, alle Timeout-Konstanten und beide Präzedenzketten bleiben
unberührt.

### 4.3 Was bleibt und sich nur neu begründet

Der Zeichenfilter auf dem Key (`'"\\\n\r'`) bleibt. Seine Begründung dreht sich:
aus „darf nicht in eine curl-Config-Zeile" wird „ein `\n` in einem Header-Wert
ist eine Header-Injection". `http.client` weist solche Werte selbst zurück — aber
mit einem `ValueError` aus einer Funktion, deren ganzer Vertrag „never raises"
lautet. Die Prüfung bleibt deshalb explizit und vorgelagert.

Das Sicherheitsargument aus dem Modul-Docstring wird dabei **stärker**, nicht
schwächer: der Key steht nicht mehr in einer temporären Datei mit Modus 0600,
sondern nur noch in einem Header-Objekt im Prozessspeicher. `ps` sah ihn schon
vorher nicht; jetzt sieht ihn auch das Dateisystem nie.

### 4.4 Eine ehrliche Abweichung

curls `max-time` ist eine **Gesamtfrist**. `urlopen(timeout=)` ist ein
**Socket-Timeout pro Blockier-Operation**. Ein Server, der alle 19 Sekunden ein
Byte schickt, läuft bei `GENERATE_TIMEOUT_S = 20.0` unbegrenzt weiter. Für einen
nicht-streamenden Einzelrequest gegen OpenRouter ist das praktisch irrelevant;
wer eine harte Gesamtfrist braucht, braucht einen Watchdog. Diese Abweichung
wird nicht verschwiegen, sondern steht als Kommentar an der Konstante.

### 4.5 Tests

Die `runner`-Injektion (`runner: Any = subprocess.run`) wird zur
`request`-Injektion. Der heutige `SpyRunner` liest die curl-Config-Datei aus dem
Dateisystem — „while curl would be running, which is the only moment the file
still exists". Dieser Kunstgriff entfällt vollständig: der Spy sieht Header und
Body direkt als Argumente. `test_llm.py` (917 Zeilen) wird dadurch **kleiner**.

Zwei Testfälle mit `id="curl-failed"` und `id="no-curl"` behalten ihre Absicht
und wechseln nur den Namen: Transport gescheitert, Client nicht vorhanden gibt es
nicht mehr — an seine Stelle tritt `URLError`.

`test_the_real_chain_answers_at_all` bleibt der einzige Test, der das Netz
berührt, und bleibt aus CI ausgeschlossen.

---

## 5. Teil C — Katalog und Tagescheck

### 5.1 `catalog.py`

```python
CATALOG_URL   = "https://openrouter.ai/api/v1/models"
CATALOG_LIMIT = 200          # eine Seite reicht: sortiert wird serverseitig
CATALOG_TIMEOUT_S = 10.0     # `up` wartet nicht länger auf einen Preisvergleich

def fetch(*, requires, limit=CATALOG_LIMIT, timeout_s=CATALOG_TIMEOUT_S,
          request=openrouter.request) -> list[dict] | None
def recommend(models, *, thresholds, efforts) -> dict | None
def write_overlay(model, *, root) -> Path
def check(*, root, now, request=openrouter.request) -> dict
```

`fetch()` benutzt `sort=pricing-low-to-high`, `supported_parameters`, `limit` und
`offset` — und **nicht** `search` (wird ignoriert) und **nicht** `category`
(HTTP 400). Ein Namensfilter passiert clientseitig. `None` heißt „keine
brauchbare Antwort", aus jedem Grund — dasselbe Profil wie `complete()`.

`recommend()` nimmt das **billigste** Modell, das jede Schwelle erfüllt.
Zwei Regeln, die leicht übersehen werden und beide bewusst so sind:

- **`efforts` ist ein Tupel, kein einzelner Wert.** Das Overlay setzt
  `[llm].model`, und dieser eine Wert bedient **beide** Jobs: den
  Commit-Generator mit `effort` und — über die Rückfallkette — den
  Prereview-Judge mit `prereview_effort`. Ein Kandidat muss deshalb **beide**
  aufgelösten Effort-Stufen in `reasoning.supported_efforts` führen, sonst ist
  er verworfen (siehe 1.5).
- **Ein Modell ohne `benchmarks.artificial_analysis` erfüllt eine gesetzte
  Index-Schwelle nicht.** Fehlende Evidenz ist kein Bestehen. Ist keine
  Index-Schwelle gesetzt, spielt der fehlende Block keine Rolle.

### 5.2 `[models]` — der neue Config-Block

| Schlüssel | Typ | Default | Bedeutung |
|---|---|---|---|
| `auto` | bool | **`false`** | Ohne dieses Kästchen schreibt nichts |
| `max_age_h` | float | `24.0` | Älter → neu holen |
| `min_coding_index` | float | `0.0` | aus `benchmarks.artificial_analysis` |
| `min_intelligence_index` | float | `0.0` | dito |
| `max_prompt_price` | float | `0.0` | USD pro Token, wie der Katalog es liefert. **`0.0` heißt „kein Limit"**, nicht „nur Gratis-Modelle" |
| `min_context` | int | `0` | `context_length` |
| `requires` | list[str] | `["reasoning"]` | an `supported_parameters` |

`requires` führt **`tools` bewusst nicht** im Default: `[llm].model` bedient zwei
reine Completion-Jobs ohne ein einziges Werkzeug (Abschnitt 1.4). `tools` zu
verlangen schlösse billige Kandidaten aus, ohne dass irgendetwas davon
profitiert. `reasoning` steht dagegen drin, weil `complete()` immer einen
`reasoning`-Block sendet und der Endpunkt ihn nicht abschalten lässt.

`[models]` muss in `settings.ROOT_KEYS` aufgenommen werden — `_check_root()`
weist heute jeden unbekannten Schlüssel der obersten Ebene ab, und ohne diesen
einen Eintrag scheitert **jede** Config, die den neuen Block trägt.

Gleiche Strenge wie überall in `settings.py`: unbekannter Schlüssel, falscher
Typ, negative Schwelle → `SettingsError`, nie ein stiller Rückfall.

### 5.3 Das Overlay

Geschrieben wird `.lean-ctx/lean-herdr/models.auto.toml`, vollständig neu, nie
in-place bearbeitet. Der Grund ist hart: **die stdlib hat keinen TOML-Writer**,
und `tomli_w` ist auf `/usr/bin/python3` ebenfalls ABSENT (1.2). Eine Datei, die
wir vollständig selbst erzeugen, braucht keinen. Ihr vollständiger Inhalt:

```toml
# written by `lean-herdr models` on <ISO-Zeitstempel>. Do not edit --
# the next run overwrites this file. Your own choice belongs in
# .lean-ctx/lean-herdr/config.toml, which wins over this one.
[llm]
model = "<slug>"
```

Geschrieben wird **nur `model`**, nie `prereview_model`: der Judge fällt ohnehin
auf `model` zurück, und ein zweiter automatisch gesetzter Schlüssel würde genau
die Trennung aufheben, für die es ihn gibt — „raising `model` to make the judge
smarter raises the generator's bill". Wer den Judge anders will, setzt
`prereview_model` von Hand, und die Automatik rührt ihn nicht an.

**Der Ablageort muss ignoriert werden — und das ist heute keine Tatsache,
sondern eine Aufgabe.** Geprüft am 2026-09-04:

```
git ls-files .lean-ctx/lean-herdr/
  .lean-ctx/lean-herdr/config.toml
  .lean-ctx/lean-herdr/roles/{builder,orchestrator,reviewer}.md

git check-ignore -v .lean-ctx/lean-herdr/models.auto.toml
  (keine Regel)
```

Ein `.gitignore` existiert, deckt aber `.lean-ctx/` nirgends ab, und die vier
Dateien dort sind **absichtlich** getrackt. Ein pauschales `.lean-ctx/` würde sie
mit untracken — die Regel muss also den einen Namen treffen:

```gitignore
# machine-local, written by `lean-herdr models` -- never shared
.lean-ctx/lean-herdr/models.auto.toml
```

Für **dieses** Repository ist das eine Zeile im Plan. Für **fremde** Projekte,
in denen `workspace init` läuft, ist es eine Entscheidung: `initcmd` schreibt
heute nur eigene Dateien und fasst fremde nicht an — der Modulkommentar begründet
das ausdrücklich („that directory belongs to whoever else writes into it"). Ein
`.gitignore` gehört dem Projekt, nicht uns. Deshalb: `workspace init` **hängt
nichts an**, sondern meldet über die bestehende `_warnings()`-Liste, dass die
Zeile fehlt, sobald `[models].auto` gesetzt ist. Der Operator entscheidet.

**Offene Alternative, die dieser Fund aufwirft:** Das Overlay könnte statt im
Repo im lean-ctx-Statusverzeichnis liegen (`orderlog.lean_ctx_data_dir()`, nach
Repo-Wurzel geschlüsselt) — dann bräuchte es nie ein `.gitignore`, in keinem
Projekt, und wäre auch der Sache nach maschinenlokal. Der Preis: es steht nicht
mehr neben `config.toml`, wo man Konfiguration sucht. Der Ablageort im Repo ist
die getroffene Wahl; diese Alternative ist notiert, weil erst die Prüfung oben
ihren Preis sichtbar gemacht hat.

**Wer die beiden Dateien zusammenführt:** eine neue Funktion in `settings.py`,
und zwar genau **eine** für beide Verbraucher:

```python
def llm_settings_layered(root) -> LlmSettings   # Overlay unten, config.toml darüber
```

Sie liest erst `models.auto.toml`, dann `config.toml` darüber, Feld für Feld, und
ein leerer String im Vordergrund gilt weiter als „nicht gesetzt".

Beide Aufrufer müssen sie nehmen — `llm.file_settings()` **und**
`dispatch.main()`. Läse nur einer das Overlay, benutzten Commit-Generator und
Prereview-Judge verschiedene Modelle, sobald ein Overlay existiert; das ist genau
der Drift, den der `THE TWO CHAINS`-Block ausschließen soll.

Was die beiden **nicht** teilen, bleibt wie heute und ist Absicht: `file_settings()`
schluckt jeden Fehler, weil ein Fehler dort den laufenden Commit abbräche;
`dispatch.main()` lässt ihn als `config_error:` durch, weil dort der
Orchestrator die Klage liest. Die Fehlertoleranz von `file_settings()` erstreckt
sich dabei unverändert auf beide Dateien: ein kaputtes Overlay ist kein kaputter
Commit, sondern ein ignoriertes Overlay.

**Präzedenz — die Kette wächst um eine Ebene:**

```
[llm].model:  --model  >  $LEAN_HERDR_LLM_MODEL  >  config.toml [llm].model
              >  models.auto.toml [llm].model  >  DEFAULT_MODEL
```

Das Overlay liegt **unter** der Hand des Operators: ein explizites
`[llm].model` in `config.toml` überlebt jeden Tagescheck. Genau das kann A2
(in-place-Chirurgie) nicht, und genau darum wurde es verworfen.

Diese Kette ist heute an fünf Stellen beschrieben; der `THE TWO CHAINS`-Block in
`llm.py` nennt sich selbst die Autorität und erklärt eine fehlende Ebene zum
Defekt. Alle fünf werden mitgeführt:

1. `llm.py`, `THE TWO CHAINS`-Block
2. `templates/config.toml`, `[llm]`-Kommentar
3. `llm.py`, argparse-Hilfetext `generate --model`
4. `llm.py`, argparse-Hilfetext `prereview --model`
5. `README.md`, beide Stellen

### 5.4 Der Tagescheck

- **Auslöser:** `lean-herdr workspace up`. **Niemals** `bin/herdr-llm generate` —
  der Commit-Pfad geht nicht ins Netz.
- **Stempel:** die `mtime` von `models.auto.toml` selbst. Keine zweite Datei,
  kein zweiter Zustand, der veralten kann.
- **Nie blockierend.** Kurzer Timeout; Netzfehler, HTTP-Fehler, unparsbare
  Antwort → die Datei bleibt wie sie ist, `up` läuft weiter und meldet den Grund
  in seiner JSON-Zeile. `up` startet den Arbeitstag und darf nicht an OpenRouter
  scheitern.
- **Opt-in.** `[models].auto = false` ist der Default. Ohne diesen Schlüssel holt
  `up` nichts und schreibt nichts — es tut dann exakt, was es heute tut. Das gilt
  **nur für den Automatismus**: `models check` und `models apply` sind
  ausdrückliche Befehle und laufen unabhängig davon (5.5).

### 5.5 CLI

`lean-herdr models list | check | apply`

| Verb | Netz | schreibt | Zweck |
|---|---|---|---|
| `list` | ja | nein | sortiert und gefiltert anzeigen |
| `check` | ja | nein | prüfen, Vorschlag zeigen |
| `apply` | ja | **ja** | Overlay schreiben, unabhängig von `[models].auto` |

Eine JSON-Zeile auf stdout, Exit immer 0 — wie `report` und `workspace`.
`apply` ist der ausdrückliche Befehl; `auto` ist die Erlaubnis, dass `up`
dasselbe von sich aus tut.

### 5.6 `DEFAULT_MODEL` bleibt

`google/gemini-3.8-flash` bleibt die eingebaute Konstante. Der Wert ist mit einer
Messreihe belegt (2026-09-03, 3 Läufe pro Zelle, Kosten pro Call, Fehlerfunde auf
einem präparierten Diff gegen eine saubere Kontrolle). Ihn ohne neue Messung zu
ersetzen, würde diese Belege wegwerfen. Der Tagescheck darf ihn überstimmen — die
Konstante zu ändern ist eine eigene Entscheidung mit eigener Messung.

---

## 6. Fehlerverhalten — die Zusammenfassung

| Lage | Antwort |
|---|---|
| `[workspace].model` steht noch in einer Config | `SettingsError` mit dem Ziel im Text |
| `--model` fehlt und `[roles.<role>].model` ist leer | `missing_flags()` wie heute |
| `builder.model == reviewer.model`, nicht bestätigt | Warnung in `warnings`, `ok` bleibt `true` |
| `[models]` hat einen unbekannten Schlüssel | `SettingsError` |
| Netz weg beim Tagescheck | Overlay unverändert, `up` läuft, Grund in der JSON-Zeile |
| Kein Kandidat erfüllt die Schwellen | Overlay unverändert, Grund in der JSON-Zeile |
| Kandidat kann den Effort nicht | verworfen, nächster Kandidat |
| Kein `$OPENROUTER_API_KEY` und keine `auth.json` | wie heute: Fallback-Message, kein Bruch |
| HTTP scheitert in `complete()` | `None` → Fallback-Message, Commit läuft |

## 7. Test-Strategie

- **`settings.py`**: neue Felder, `KIND_BY_ROLE`, die zwei Umzugsmeldungen, der
  `[models]`-Block mit je einem Fehlerfall pro Schlüssel, die drei Zeilen der
  `shares_builder_model`-Tabelle aus 3.2, `[models]` in `ROOT_KEYS`.
- **`llm_settings_layered()`**: Overlay allein; `config.toml` allein; beide, wobei
  `config.toml` gewinnt; ein leerer Wert im Vordergrund lässt das Overlay durch;
  ein kaputtes Overlay wird von `file_settings()` ignoriert, von
  `dispatch.main()` aber als `config_error:` gemeldet, wenn es in `config.toml`
  steckt.
- **`dispatch.py`**: Flag schlägt Datei; Datei füllt fehlendes Flag; beides leer
  bleibt `missing_flags()`; die Warnung erscheint im `warnings`-Schlüssel.
- **`llm.py`**: bestehende Testabsichten bleiben, `runner` wird `request`. Der
  Spy prüft Header und Body direkt. Kein Test erreicht das Netz außer dem einen,
  der es schon heute als einziger tut.
- **`catalog.py`**: `fetch` gegen eine injizierte `request`-Funktion mit einer
  Katalog-Antwort aus einer Fixture; `recommend` als Tabelle über Schwellen,
  einschließlich „Modell ohne `benchmarks` besteht eine Index-Schwelle nicht" und
  „Modell ohne den nötigen Effort wird verworfen"; `write_overlay` gegen
  `tmp_path`; `check` mit gestellter `mtime` für frisch / abgelaufen / `auto`
  aus.
- **`initcmd._warnings()`**: die neue Meldung erscheint, wenn `[models].auto`
  gesetzt ist und `.gitignore` die Overlay-Zeile nicht führt — und **nicht**,
  wenn `auto` aus ist oder die Zeile schon dasteht.
- **`test_language.py`** gilt unverändert: alles außerhalb `docs/` ist Englisch.
- **Ein Test, der die Schnittlinie hält:** `llm.py` importiert `catalog` nicht.
  Das ist die Regel aus Abschnitt 2, und sie ist die einzige, die ein Mensch beim
  Lesen übersieht.

## 8. Reihenfolge

1. **Teil B** — curl → `urllib`, `openrouter.py` entsteht. In sich abgeschlossen,
   berührt keine Config, und schafft die `request()`-Funktion, auf der Teil C
   steht.
2. **Teil A** — Rollen bekommen `model` und `kind`. Berührt die meisten Tests,
   aber keinen neuen Code.
3. **Teil C** — `catalog.py`, `[models]`, das Overlay, die CLI, der Haken in
   `workspace up`. Dazu, im selben Schritt und nicht später:
   - die eine Zeile in `.gitignore` dieses Repositories (5.3),
   - die `_warnings()`-Meldung in `initcmd`, wenn `[models].auto` gesetzt ist
     und die Zeile im `.gitignore` des Zielprojekts fehlt.

   Beides gehört an das Ende von Teil C, weil erst dort eine Datei entsteht, die
   ignoriert werden müsste. Vorgezogen wäre es eine Regel ohne Gegenstand.

Jeder Teil ist für sich lauffähig und abbrechbar. Bricht Teil C ab, steht das
Projekt trotzdem besser da als heute: curl ist weg und die Modelle stehen in der
Config — und es liegt keine ungetrackte Datei herum, die niemand ignoriert hat.

## 9. Bewusst nicht in diesem Design

- **Tool-Calling** in `llm.py` — verworfen mit der Messung aus 1.4. Kandidat für
  einen eigenen Spec ist der Prereview-Judge und sein `MAX_DIFF_BYTES`-Cap.
- **OpenRouters server-seitige Subagents** — überlappen mit dem, was
  `lean-herdr dispatch` selbst tut. Zwei Delegationsmechanismen nebeneinander
  wären eine eigene Entscheidung, keine Nebenwirkung dieser.
- **`httpx`** — verworfen mit 1.2. Kommt in Frage, wenn `bin/herdr-llm` eines
  Tages nicht mehr auf dem System-Interpreter laufen muss.
- **Ein Wechsel von `DEFAULT_MODEL`** — siehe 5.6.
