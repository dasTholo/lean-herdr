# lean-herdr: LLM-Commits und billige Vorprüfung — Design v1.0

**Stand:** 2026-09-03 · **Status:** entworfen, nicht implementiert
**Ergänzt:** den Auftragsweg aus `2026-09-03-lean-herdr-auftragslog-design.md`
um den Commit-Pfad des Builders und eine vorgeschaltete Diff-Prüfung
**Anlass:** worktrunk kann Commit-Messages von einem externen Kommando
erzeugen lassen (`wt step commit`, `wt step squash`, der Squash in
`wt merge`). Die Frage des Betreibers war, ob ein kleines, billiges Modell
das leisten kann — und ob dasselbe Modell den Agenten beim Review hilft.

## 1. Entscheidung

Ein Modul, zwei Verbraucher:

1. **Commit-Pfad.** `bin/herdr-llm generate` ist das
   `commit.generation.command` von worktrunk. Der Builder committet mit
   `wt step commit --stage none`, der Orchestrator squasht mit
   `wt step squash --stage none` und merged mit `--no-commit`.
2. **Vorprüfungs-Pfad.** `bin/herdr-dispatch builder --await --prereview`
   lässt dasselbe Modell über den Branch-Diff laufen, **bevor** der teure
   Reviewer gebaut wird. Es darf **ablehnen, aber nie freigeben.**

Beides trägt `lean_herdr/llm.py` — der einzige HTTP-Aufruf im Projekt.

**Reihenfolge der Umsetzung: erst der Commit-Pfad, dann die
Vorprüfung.** Der Commit-Pfad ist durchgemessen (Abschnitt 2), die
Vorprüfung ruht auf einer geschätzten Einstellung (10.2). Wer zuerst
den gemessenen Teil baut, kann den ungemessenen an einem laufenden
System prüfen, statt beide Unsicherheiten gleichzeitig zu tragen.

## 2. Gemessener Ausgangsbestand

Alles hier ist gemessen, nicht aus der Dokumentation übernommen.
Messumgebung: `wt v0.76.0`, `git 2.55.0`, `curl 8.22.0`,
`opencode` und Claude Code lokal vorhanden; `llm`, `aichat`, `codex`,
`gemini` **nicht**.

### 2.1 Der Ist-Zustand ohne Konfiguration

`~/.config/worktrunk/config.toml` existiert nicht. Ohne
`[commit.generation]` erzeugt worktrunk deterministische Messages aus
Dateinamen — gemessen: `Changes to a.txt`, mit dem Hinweis
`↳ Using fallback commit message`. `wt merge` squasht bereits heute; der
Squash-Commit, der in `main` landet, trägt also diese Message.

### 2.2 Vier Routen zum Modell, vier Preise

Aufgabe jeweils identisch (ein Conventional-Commit-Subject für eine
Ein-Zeilen-Änderung), Ausgabe jeweils korrekt:

| Route | Wanduhr | Kosten/Aufruf |
|---|---|---|
| `opencode run -m openrouter/google/gemini-3.8-flash` | 8,0 s | $0,0056 |
| `claude -p --model=haiku`, hermetisch (worktrunk-Doku) | 2,1 s | $0,0012 |
| `curl` → OpenRouter, gemini-3.8-flash, Reasoning-Default | 4,8 s | $0,00115 |
| **`curl` → OpenRouter, gemini-3.8-flash, `reasoning.effort=minimal`** | **1,7 s** | **$0,000045** |

Zwei Befunde erklären die Spanne, und beide widersprechen der Intuition,
ein kleines Modell sei automatisch billig:

- **Der Agenten-Harness kostet mehr als das Modell.** `opencode run`
  schickte für den Einzeiler 17 698 Token (4 729 Eingabe + 12 671 aus dem
  Cache) — System-Prompt, Werkzeugdefinitionen, MCP. Der hermetische
  `claude -p`-Aufruf brauchte 223 Eingabe-Token für dieselbe Frage.
- **Das Nachdenken kostet mehr als der Diff.** Der Default-Aufruf von
  gemini-3.8-flash verbrannte 294 Reasoning-Token; davon entfielen
  $0,00113 von $0,00115 auf die Ausgabe und $0,0000188 auf den Prompt.
  Mit `reasoning.effort=minimal` fallen die Reasoning-Token auf 0, die
  Antwort bleibt wörtlich dieselbe (`fix(parser): add null check`).
  `{"reasoning": {"enabled": false}}` geht **nicht**:
  *„Reasoning is mandatory for this endpoint and cannot be disabled."*

### 2.3 Wie worktrunk das Kommando aufruft

worktrunk hat die Aufrufform selbst ausgegeben:

    wt step commit --show-prompt | sh -c '<commit.generation.command>'

stdin ist der gerenderte Prompt, stdout die Commit-Message. Der Prompt
enthält `<task>`, `<format>`, `<style>`, `<diffstat>`, `<diff>` und
`<context>` mit Branch und `recent_commits`. **Wir schreiben deshalb kein
eigenes Commit-Template** — Diff, Diffstat und Stilvorlage kommen von
worktrunk.

`--config-set 'commit.generation.command=…'` erreicht den Generator
(verifiziert). Das Projekt könnte den Generator also pro Aufruf
mitgeben — genutzt wird es trotzdem nicht, siehe 2.5.

**Ein fehlschlagendes Kommando ist fatal**, nicht stiller Rückfall:

    ✗ Commit generation command failed
    [exit:1]

Der Rückfall auf die Dateinamen-Message greift nur, wenn *gar kein*
Kommando konfiguriert ist. Daraus folgt die zentrale Regel für
`bin/herdr-llm generate`: immer exit 0, immer Text.

### 2.4 Das Staging-Verhalten, in einem Wegwerf-Repo gemessen

| # | Situation | Ergebnis |
|---|---|---|
| 1 | `wt step commit --stage none`, leerer Index | `✗ Nothing to commit`, exit 1, kein Commit, **kein Modellaufruf** |
| 2 | `--stage none` nach `git add a.txt`, daneben eine untracked Datei | committet nur `a.txt`, die untracked Datei bleibt untracked |
| 3 | `wt merge --yes --no-commit`, untracked Datei im Worktree | `✗ Cannot merge with --no-commit: probe has uncommitted changes / ?? untracked.md`, exit 1, **nichts passiert** |
| 4 | `wt merge --yes --stage none` ohne `--no-commit`, untracked Datei | merged, verweigert dann das Entfernen: `✗ Cannot remove worktree after merge`. **Nichts geht verloren** |
| 5 | `wt step squash --stage none` über zwei Commits | ein Commit, generierte Message, Subjects als „Combined commits" im Body |
| 6 | pre-merge-Hook bei `merge --no-commit` | **läuft** (`◎ Running pre-merge project:test @ <worktree>`); ein fehlschlagender Hook bricht **vor** dem Merge ab, `main` unberührt, Worktree bleibt, exit 7 durchgereicht |

Messung 6 ist die Voraussetzung des ganzen Entwurfs: das Testtor dieses
Projekts überlebt `--no-commit` unbeschädigt. Messung 4 korrigiert eine
Annahme, die in der Diskussion zunächst behauptet wurde — worktrunk
verliert unfertige Arbeit auch ohne `--no-commit` nicht.

`stage` ist laut `wt config create --help` ein Schlüssel der User-Config
und „Shared by `wt step commit`, `wt step squash`, and `wt merge`".

### 2.5 Warum die User-Config und nicht `--config-set`

Der Generator muss **drei** Aufrufstellen erreichen: den Commit des
Builders, den Squash des Orchestrators und den Squash *innerhalb* von
`wt merge`. Ein Wrapper mit `--config-set` erreicht nur die Stellen, die
ihn benutzen; wer von Hand `wt merge` tippt, bekommt still die
Dateinamen-Message ausgerechnet für den Commit, der in `main` landet.
Die User-Config gilt für alle drei plus die Branch-Summaries. Preis: ein
Operator-Schritt, dokumentiert neben den bestehenden
`lean-ctx allow`-Zeilen.

**Und daraus folgt: der Pfad im Kommando ist absolut.** Die User-Config
gilt für *jedes* Repository dieser Maschine. Ein relatives
`bin/herdr-llm generate` läuft überall sonst in `sh: not found` (exit
127) — und ein fehlschlagendes Kommando ist nach 2.3 fatal, nicht
stiller Rückfall. Der Betreiber bräche sich damit `wt step commit` und
`wt merge` in allen anderen Projekten.

Das ist kein Kompromiss, sondern der Normalfall: `bin/herdr-llm` setzt
seinen `sys.path` aus dem eigenen Dateipfad, genau wie
`bin/herdr-dispatch` es heute tut (`parents[1]`, verifiziert), und der
Generator ist **repo-agnostisch** — er formatiert nur, was worktrunk ihm
auf stdin reicht. Ein absoluter Pfad bedient deshalb alle Repositories
der Maschine sinnvoll, nicht nur dieses.

## 3. Architektur und Datenfluss

### 3.1 Commit-Pfad

```
Builder im Worktree:
  git add <die Dateien, die zum Auftrag gehören>
  wt step commit --stage none --yes
    → Prompt rendern (+ <project-guidance> aus .config/wt.toml)
    → sh -c 'bin/herdr-llm generate'
         stdin: Prompt → curl → OpenRouter → stdout: Message
    → git commit

Orchestrator im Haupt-Checkout, nach verdict=result:
  1. Pfad + workspace_id auflösen, solange der Worktree existiert
  2. wt -C <path> step squash --stage none --yes
  3. herdr workspace close <workspace_id>
  4. wt -C <path> merge main --yes --no-commit
```

Die Reihenfolge ist nicht verhandelbar und aus dem bestehenden
Orchestrator-Text übernommen: der Squash braucht den Worktree, das
Schließen des Workspace muss vor dem Merge liegen, weil `wt merge` den
Checkout entfernt.

`--no-commit` überspringt Commit **und** Squash — deshalb ist Schritt 2
kein Luxus, sondern die Stelle, an der der Squash überhaupt noch
stattfindet. Der Gewinn steht in Messung 3: liegt am Ende Unfertiges im
Worktree, verweigert der Merge, bevor `main` sich bewegt.

**Scheitert Schritt 2, endet der Abbau dort.** Der Orchestrator
schließt dann **keinen** Workspace und merged **nicht** — er
eskaliert mit dem Fehlertext von `wt`. Das ist keine Kleinigkeit: der
Abbau bekommt mit dem Squash erstmals einen Schritt, der scheitern
kann, *bevor* etwas Unumkehrbares passiert ist, und der bestehende
Teardown-Text in `roles/orchestrator.md` kennt dafür noch keinen Zweig.
Der offene Workspace ist dabei erwünscht — er ist genau der Zustand, in
dem ein Mensch nachsehen kann, was der Squash nicht wollte.

### 3.2 Vorprüfungs-Pfad

```
bin/herdr-dispatch builder --await --prereview --task-id o-… --worktree <branch>
  → wartet wie bisher
  → Auftrag steht auf `completed`?
      → Pfad über find_worktree(herdr.worktree_list(root), branch)
            kein Eintrag / kein `path` → skipped: worktree_unresolved
      → wt -C <path> step diff       (committed + staged + unstaged +
                                     untracked gegen die Merge-Base —
                                     genau das, was wt merge einschlösse)
      → llm.prereview(order.description, diff)
      → in DIESELBE JSON-Antwort:
          {"ok": true, …, "prereview": "reject", "prereview_note": "…"}
  → jeder andere Zustand: unverändert
```

Der Aufruf kostet **keinen zusätzlichen Modellschritt** des
Orchestrators: er liest diese JSON-Zeile ohnehin.

`dispatch.py` **importiert `llm.prereview()` im Prozess** und ruft nicht
`bin/herdr-llm` als Subprozess auf. Das CLI existiert für den Menschen,
nicht als Umweg für den eigenen Code — ein zweiter Prozess brächte nur
eine zweite Fehlerquelle und eine zweite Stelle, an der der Key gelesen
wird.

`prereview` steht **neben** `verdict`, nie an seiner Stelle. `verdict`
gehört dem starken Reviewer und dem `VERDIKT:`-Protokoll; ein zweiter
Schreiber auf demselben Schlüssel wäre genau die Verwechslung, die
`VERDICT_RE` verhindern soll.

Werte: `pass` | `reject` | `skipped`. **Nur `reject` ändert etwas.** Bei
`pass` und bei `skipped` verhält sich der Orchestrator exakt wie heute:
er baut den Reviewer und lässt ihn urteilen. Das ist die Umsetzung von
„nur ablehnen, nie freigeben" — ein `pass` ist keine Freigabe, sondern
die Abwesenheit eines Einwands.

`prereview_note` wird auf 2 000 Zeichen gekürzt. Die Notiz reist in den
Folgeauftrag und damit in das Auftrags-Log; eine ausufernde
Modellbegründung gehört dort nicht hinein.

**`_worker_root()` wird hier ausdrücklich NICHT benutzt.** Die Funktion
fällt auf den Repo-Root zurück, wenn der Branch sich nicht auflösen lässt
(`dispatch.py:338-345`), und ihr Docstring sagt auch, warum das dort
richtig ist: sie sucht auf dem Timeout-Pfad ein Absturzprotokoll, und der
Root ist die vernünftige zweite Adresse. Für die Vorprüfung wäre genau
dieser Rückfall ein Fehler mit Folgen — `wt step diff` liefe dann im
Haupt-Checkout des Orchestrators, und ein dortiger schmutziger Baum
könnte ein `reject` auf einen **fremden** Diff auslösen. Das bräche die
Invariante aus Abschnitt 5. Die Vorprüfung löst den Pfad deshalb selbst
auf, über `find_worktree()`, und behandelt „nicht gefunden" als
`skipped` — ein sichtbar unterlassenes Urteil statt eines falschen.

## 4. Komponenten

### Neu: `lean_herdr/llm.py`

Stdlib-only, kein Manifest-Eintrag. Der `runner` ist injizierbar — exakt
das Muster aus `worktree.wt_switch()`, damit kein Test ins Netz läuft.

```python
DEFAULT_MODEL = "google/gemini-3.8-flash"   # $LEAN_HERDR_LLM_MODEL schlägt ihn
ENDPOINT      = "https://openrouter.ai/api/v1/chat/completions"
MAX_PROMPT_BYTES = 200_000
GENERATE_TIMEOUT_S, PREREVIEW_TIMEOUT_S = 20.0, 60.0

def api_key(env=os.environ, auth_path=None) -> str | None
def complete(prompt, *, effort, model=…, timeout_s=…, runner=subprocess.run) -> str | None
def fallback_message(prompt: str) -> str
def generate(prompt: str, *, runner=…) -> str
def prereview(order: str, diff: str, *, runner=…) -> tuple[str, str]
```

**Key-Auflösung:** `$OPENROUTER_API_KEY`, sonst `openrouter.key` aus
`~/.local/share/opencode/auth.json` (Struktur verifiziert:
`{"openrouter": {"key": …, "type": …}}`), sonst `None`.

**Der Key steht nicht in `argv`.** `curl --config <tempfile>` (Modus
0600, im `finally` entfernt) trägt `url` und den
`Authorization`-Header, der Body geht über `--data-binary @<file>`. Ein
`-H "Bearer …"` auf der Kommandozeile wäre über `ps` für jeden Prozess
auf der Maschine lesbar — in einem Multiplexer voller Agenten kein
theoretisches Problem.

**Effort:** `generate` → `minimal` (Messung 2.2: 26× billiger, gleiche
Antwort). `prereview` → `low`; dort ist Nachdenken den Cent wert, und die
Vorprüfung ersetzt im Erfolgsfall einen kompletten Reviewer-Dispatch.

### Neu: `bin/herdr-llm`

Zwei Modi, nicht drei — worktrunk kennt nur **ein**
`commit.generation.command` für Commit *und* Squash:

    bin/herdr-llm generate  [--model M] [--effort E] [--timeout S]
    bin/herdr-llm prereview [-C <path>] [--order <text>] [--model M] …

`generate` liest stdin, schreibt stdout, endet **immer** mit 0.
`prereview` ist der manuelle Einstiegspunkt: ein Branch hinein, das
Urteil heraus, ohne dass ein Auftrag angelegt wird. Für ein Feature,
dessen Qualität sich erst im Betrieb zeigt, ist das der wichtigere der
beiden Modi.

### Geändert: `lean_herdr/dispatch.py`

- `AwaitRequest` bekommt `prereview: bool = False`.
- `_result_for_state()` bleibt unangetastet; die Vorprüfung hängt in
  `await_task()` hinter dem `completed`-Ergebnis, mit demselben
  injizierbaren `runner`.
- `build_parser()` / `missing_flags()`: `--prereview` ohne `--await`
  ist ein Fehler, `--prereview` ohne `--worktree` ebenfalls — dem
  bestehenden Muster folgend, das Streuflags meldet statt sie zu
  ignorieren. Lässt sich der Pfad zur Laufzeit nicht auflösen, ist das
  kein Fehler, sondern `skipped`.
- **Der Streuflag-Zweig für `LOG_COMMANDS`** (`dispatch.py:587-620`)
  zählt seine Flags einzeln auf. `--prereview` muss dort mitgenannt
  werden, sonst schluckt `order --prereview` das Flag stillschweigend —
  genau das Verhalten, das dieser Zweig verhindern soll.

Die Datei liegt bei 762 Zeilen; die 800-Zeilen-Grenze aus `AGENTS.md`
gilt. Wenn der Zuwachs sie reißt, wandert der Vorprüfungs-Block als
eigene kleine Funktion nach `llm.py` — nicht die Grenze wird gelockert.

### Geändert: `roles/builder.md`

Schritt 3 wird konkret statt „small commits":

> Stage explicitly what the order asked for — `git add <paths>`, never
> `git add -A`, never `git add .`. Then `wt step commit --stage none --yes`.
> Untracked files stay untracked: nothing you did not name reaches the
> commit. An empty index fails loudly (`✗ Nothing to commit`) — that is
> the reminder to stage, not an error to work around.

### Geändert: `roles/orchestrator.md`

- Teardown: der Squash-Schritt und `--no-commit` (3.1).
- Neue Eskalationsursache: `Cannot merge with --no-commit` heißt, im
  Worktree liegt Unfertiges. Das ist ein Befund für den Menschen, keine
  Panne zum Wegräumen — der Orchestrator entfernt nichts.
- Vorprüfung: `--prereview` am Builder-`--await`; bei
  `prereview: reject` ein Folgeauftrag mit `--after o-…`, der
  `prereview_note` trägt — und auf **dieser** Runde **kein**
  `--prereview`. Das begrenzt ein hartnäckiges kleines Modell auf genau
  eine Ablehnung, ohne dass irgendwo ein Zähler steht.

### Geändert: `.config/wt.toml`

`[commit.generation] template-append` mit der Projektstimme: Conventional
Commits mit Scope, englisch, beschreibt **was sich ändert**, Body nur bei
materiellen Änderungen, gemessene Fakten statt Absichten. Der Fragment
braucht einmalig `wt config approvals add` — derselbe Gate, den die
README für die Hooks beschreibt.

### Geändert: `.claude/settings.json`, `opencode.jsonc`, `README.md`

Siehe Abschnitt 6.

## 5. Fehlerbehandlung

**Der Generator blockiert den Builder nie.** `bin/herdr-llm generate`
endet immer mit 0 und gibt immer Text aus:

| Fall | Ausgabe |
|---|---|
| Kein Key | `Changes to <Dateien aus dem <diffstat>>` + Notiz auf stderr |
| curl-Fehler, Timeout, HTTP ≠ 200 | dasselbe |
| Prompt > `MAX_PROMPT_BYTES` | dasselbe, **ohne** Aufruf — kein Kostenunfall bei einem Riesen-Diff |
| Antwort leer oder nur Whitespace | dasselbe |

Die Fallback-Message entsteht aus dem `<diffstat>`-Block, den worktrunk
ohnehin mitschickt — **kein `git`-Subprozess im Fehlerpfad**.

**Die Vorprüfung lehnt nie fälschlich ab.** Kein Key, Timeout,
unparsbare Antwort, leerer Diff, nicht auflösbarer Worktree, Diff über
der Obergrenze — jeder dieser Fälle ergibt `skipped` mit Grund, nie
`reject`. Das ist die technische Fassung der Entwurfsentscheidung: das
Modell darf blockieren, seine Infrastruktur nicht.

**Verdikt-Parsing wie beim Reviewer:** erste Zeile,
`PREREVIEW: pass|reject`, alles andere → `skipped`. Erste Zeile allein,
damit dieselben Worte in der Begründung das Urteil nicht kippen können —
wörtlich die Begründung, die `dispatch.verdict()` schon trägt.

**Ablehnungsgründe der Vorprüfung** sind absichtlich eng und
auftragsunabhängig prüfbar: fehlende Tests zu neuer oder geänderter
Logik, Debug-Reste (`print`, `pdb`, auskommentierter Code), unaufgelöste
Merge-Marker, hartkodierte Pfade oder Geheimnisse, Werkzeug-Abfall im
Diff (`.orig`, `.rej`, Scratch-Dateien) und Änderungen, die der
Auftragstext nicht deckt. Nicht: Geschmack, Formatierung, Architektur.

## 6. Erlaubnisse und Operator-Schritte

Drei Permission-Stellen, alle vorhanden, nur erweitert:

- `opencode.jsonc`, builder: `"wt step commit *": "allow"`
- `.claude/settings.json`: `"Bash(wt step commit:*)"`
- `lean-ctx allow wt` — steht bereits in der README

Neuer README-Abschnitt neben den `lean-ctx allow`-Zeilen:

```toml
# ~/.config/worktrunk/config.toml
stage = "none"                    # gilt für step commit, step squash UND merge

[commit.generation]
command = "/pfad/zu/lean-herdr/bin/herdr-llm generate"   # absolut, siehe 2.5
```

Der Pfad ist **absolut**, nie `bin/herdr-llm`. Die README nennt ihn mit
dem echten Pfad des Checkouts und begründet in einem Satz, warum: die
Datei gilt maschinenweit.

Dazu `export OPENROUTER_API_KEY=…` — oder nichts tun, dann greift der
opencode-Store. Und einmalig `wt config approvals add` für das
`template-append`-Fragment.

**Die neue Angriffsfläche, benannt:** der Builder darf ein Kommando
aufrufen, das den Inhalt seines Worktrees an einen fremden Dienst
schickt. Das galt vorher schon für jeden Agenten dieses Projekts, hier
aber ohne Modell dazwischen, das ablehnen könnte. Wer in einem Repo mit
Geheimnissen arbeitet, konfiguriert den Generator nicht.

## 7. Testbarkeit

Kein Test geht ins Netz; `runner` wird injiziert.

- **`tests/test_llm.py`** — Key-Präzedenz (env schlägt auth.json; keins
  von beidem → `None`); Aufrufform (Key **nicht** in `argv`,
  Config-Datei 0600, wieder entfernt); Antwort-Parsing inklusive
  abgestreifter ```-Zäune; Fallback-Message aus einem echten
  `<diffstat>`-Block; jeder Fehlerfall → exit 0 mit Fallback;
  Prompt-Obergrenze ohne Aufruf; `PREREVIEW:`-Parsing nur auf der ersten
  Zeile.
- **`tests/test_dispatch_prereview.py`** — `--prereview` wirkt nur bei
  `completed`; `prereview` steht neben `verdict`, nie statt; Fehler →
  `skipped`, nie `reject`; ohne das Flag ist `await_task()` byte-gleich
  zu heute; `--prereview` ohne `--await` und ohne `--worktree` sind
  Nutzungsfehler.
- **`tests/test_worker_permissions.py`** — nicht `test_roles.py`, das
  nur den `ORCHESTRATOR`-Namen bewacht. Hier steht das Tupel
  `BUILDER_TOOLING`, gegen das
  `test_the_builder_may_run_the_gate_its_role_text_demands` prüft: es
  bekommt `"wt step commit *"`. Und `test_the_builders_gate_is_not_a_
  blank_cheque` bekommt `"wt *"` sowie `"wt step *"` in seine
  Verbotsliste — der Orchestrator darf `wt *`, der Builder genau einen
  Unterbefehl. (`"curl*"` steht dort bereits und bleibt: der Builder
  ruft nie selbst ins Netz.)
- **`tests/test_manifest.py`** — die Liste der geprüften
  Einstiegspunkte ist hart verdrahtet (`lean_herdr/*.py` plus
  `bin/herdr-dispatch` und `bin/herdr-report`). `bin/herdr-llm` fällt
  ohne einen Eintrag durch das Python-Floor-Raster;
  `lean_herdr/llm.py` ist automatisch abgedeckt.
- **`tests/test_language.py`** greift für die neuen Dateien automatisch.
- Ein `-m integration`-Test über die echte Kette, der in CI nicht läuft.

## 8. Kostenrechnung

Fünf Commits pro Auftrag zu $0,000045 sind **$0,0002**. Eine Vorprüfung
mit `effort=low` liegt je nach Diff-Größe im niedrigen Zehntelcent und
spart im Ablehnungsfall einen vollständigen Reviewer-Dispatch: eine
Pane, einen Agentenstart, einen Auftrag und einen Lauf des starken
Modells. Sie kostet nichts, wenn sie nichts findet, außer der Wartezeit
des `--await`-Aufrufs.

## 9. Was dieser Entwurf NICHT tut

- **Kein eigenes Commit-Template.** worktrunk rendert; wir ergänzen nur
  `template-append`.
- **Keine Konfiguration in `.config/lean-herdr.toml`.** Modell und
  Effort stehen als Konstanten in `llm.py`, überschreibbar per CLI-Flag
  und `$LEAN_HERDR_LLM_MODEL`. `settings.py` bleibt unberührt.
- **Kein blockierendes Modell-Urteil vor dem Merge.** Der pre-merge-Hook
  bleibt der Test, nicht das Modell.
- **Keine Freigabe durch das kleine Modell.** `pass` ist kein `result`;
  der starke Reviewer läuft in jedem Fall.
- **Kein Wrapper-Skript um `wt`.** Siehe 2.5.
- **Keine Korrektur von `list.json-schema`.** `wt config show` meldet
  bei jedem Aufruf, dass der Pin in `.config/wt.toml` ignoriert wird,
  weil der Schlüssel in die User-Config gehört. Ein echter Befund, aber
  ein anderer — er gehört in eine eigene Korrektur.

## 10. Offene Annahmen, in der Umsetzung zu messen

1. **Fehlende `template-append`-Freigabe im Agenten-Pane.** Ob eine
   nicht erteilte Freigabe still übergangen wird (die Doku sagt
   „Declining is non-fatal") oder auf eine Eingabe wartet, die im Pane
   niemand gibt, ist ungeprüft. `--yes` steht deshalb im Rollenbefehl,
   die Freigabe als Operator-Schritt in der README. Zu messen mit
   `wt step commit --dry-run` ohne tty und ohne Freigabe.
2. **`effort=low` für die Vorprüfung.** Der Wert ist geschätzt, nicht
   gemessen. Erste Umsetzungs-Task: dieselbe Vorprüfung mit `minimal`,
   `low` und `medium` über einen echten, absichtlich fehlerhaften Diff
   fahren und Trefferquote gegen Kosten stellen.
3. **Verhalten von `wt step squash --stage none` bei genau einem und bei
   null Commits.** Messung 5 lief über zwei. Beide Randfälle entscheiden,
   ob der Abbau-Zweig aus 3.1 im Normalbetrieb greift oder nur im
   Ausnahmefall.
4. **Projektbezogene Einträge in der User-Config.** worktrunk kennt
   `[projects."<id>"]`; ob `commit.generation.command` dort erlaubt ist,
   ist ungeprüft. Wäre es das, könnte der Generator auf dieses Repo
   beschränkt werden, statt maschinenweit zu gelten. Der absolute Pfad
   aus 2.5 funktioniert unabhängig davon und bleibt der Vorschlag.

## 11. Reproduktion

```bash
# 2.2 — die vier Routen
opencode run --dir /tmp --format json -m openrouter/google/gemini-3.8-flash "<frage>"
MAX_THINKING_TOKENS=0 claude -p --output-format json --no-session-persistence \
  --model=haiku --tools='' --safe-mode --setting-sources='user' --system-prompt='' < prompt.txt
curl -sS --config <cfg> -H "Content-Type: application/json" --data-binary @payload.json
#   payload mit und ohne  "reasoning": {"effort": "minimal"}

# 2.3 — Aufrufform und --config-set
wt step commit --dry-run --config-set 'commit.generation.command="cat >/dev/null; echo chore: probe"'

# 2.4 — Staging und Hooks, in einem Wegwerf-Repo
git init -q -b main && … && wt switch --create probe --base @ --no-cd --yes
wt step commit --stage none --yes            # leerer Index → exit 1
wt -C <worktree> merge main --yes --no-commit # untracked → exit 1, nichts passiert
wt -C <worktree> --config-set 'pre-merge.gate="exit 7"' merge main --yes --no-commit
```
