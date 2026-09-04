@lean-md
consumer: ai
crp: compact

@var test_cmd default="uv run pytest -q" desc="project test runner command"
@var lint_cmd default="uv run ruff check ." desc="project lint gate"
@import .lean-ctx/lean-md/plan-recipes /

# lean-herdr — Der erste opencode-Start in einem Projekt

Quelle: `docs/specs/2026-09-04-lean-herdr-orchestrator-erststart-design.md` (v1.0).
Render je Task:
`lean-md render docs/lean-md/plans/2026-09-04-lean-herdr-orchestrator-erststart.lmd.md --phase task-N`.

## Goal

`lean-herdr workspace up` baut in etwa der Hälfte der Läufe keinen arbeitsfähigen
Orchestrator auf. Die Ursache liegt nicht bei uns: opencodes **erster Bootstrap in
einem Projekt, das ein Projekt-Plugin trägt, hängt** — und `workspace init` schreibt
genau so ein Plugin. Der Hänger hat zwei eigene Defekte freigelegt, und beide
kosten mehr als der Hänger selbst: `agent start` bekommt von uns 10 s Budget, wo
Herdr 30 s wartet, und der Kill danach wird als *Ablehnung* gemeldet, worauf seit
`51dac35` der Waiter übersprungen wird — ein funktionierender Orchestrator kommt
hoch, den niemand mehr beobachtet.

Vier Tasks, in dieser Reihenfolge zwingend:

1. `herdr.py` reicht Herdrs `--timeout` durch und leitet das eigene Subprozessbudget
   daraus ab. Damit killt lean-herdr nie mehr einen Start, den Herdr noch legitim
   abwartet. Dazu `pane_send_keys` und die Zeitschranke, die eine Ablehnung nach
   0,0 s von einem ausgesessenen Budget trennt.
2. `herdr.start_agent` — der gemeinsame Helfer: Versuch 1, `ctrl-c`, Versuch 2, und
   zwei getrennte Fehlerbilder statt einem.
3. `workspace.py` und `dispatch.py` rufen den Helfer statt `agent_start`. `up` und
   `dispatch` bekommen damit denselben zweiten Anlauf, über einen Mechanismus.
4. `initcmd.py` wärmt das Projekt einmal, kopflos — die Erstlast fällt dort an, wo
   sie sichtbar und harmlos ist, nicht im heißen Pfad.

## Architecture

```
lean_herdr/
  herdr.py     ~  HERDR_MAX_TIMEOUT_MS, AGENT_START_REFUSAL_S,
                  timeout_ms_for(), pane_send_keys(),
                  agent_start(..., timeout_ms=, now=)               (Task 1)
                  + FIRST_START_TIMEOUT_MS, PANE_FREE_TIMEOUT_S,
                    PANE_FREE_INTERVAL_S, _free_pane(), start_agent() (Task 2)
  workspace.py ~  start_orchestrator ruft start_agent(),
                  neu: retry_on_hang                                (Task 3)
  dispatch.py  ~  dispatch() ruft start_agent()                     (Task 3)
  handlers.py  ~  handle_bootstrap: retry_on_hang=False             (Task 3)
  initcmd.py   ~  WARM_TIMEOUT_S, _warm_opencode(), `warmed`        (Task 4)

tests/doubles.py       ~  Clock, ScriptedProc                       (Task 1)
tests/test_herdr.py    ~  Budget, Durchreichen, Schranke            (Task 1)
                          + der Helfer, beide Anläufe, beide Fehler (Task 2)
tests/test_workspace.py ~ opencode_stuck mit Pane und Workspace     (Task 3)
tests/test_dispatch.py  ~ derselbe Helfer, kein zweiter Mechanismus (Task 3)
tests/test_handlers.py  ~ der Tastendruck sitzt keinen Haenger aus  (Task 3)
tests/test_initcmd.py   ~ das Aufwärmen, und wann es ausbleibt      (Task 4)
README.md               ~ ein Absatz unter „Setting up a project"   (Task 4)
```

Der Startweg nach Task 3, beide Verbraucher auf einem Helfer:

```
start_agent(herdr, name, kind=, pane=, agent_args=,
            first_timeout_ms=12000, retry_timeout_ms=<ready_timeout_s in ms>)
  -> agent_start(..., timeout_ms=first_timeout_ms)     Herdr wartet selbst
       Antwort da              -> {"ok": True, "reply": ...}
       Antwort nach < 3,5 s    -> {"ok": False, "error": "agent_start_failed"}
       Antwort nach >= 3,5 s   -> der Hänger:
            pane send-keys <PANE> ctrl-c
            pollen bis kein agent_list()-Eintrag mehr diese pane_id trägt
            nach der halben Frist ein zweites ctrl-c
         -> agent_start(..., timeout_ms=retry_timeout_ms)   gewärmt: 3,4 s
              Antwort da  -> {"ok": True, "reply": ..., "retried": True}
              sonst       -> {"ok": False, "error": "opencode_stuck"}
```

Die gemessene Grundlage dieses Plans steht in der Spec (§1, §2, §5.4, alles am
2026-09-04 gegen opencode 1.18.25 und Herdr 0.8.2). Vier Zahlen trägt der Code als
Kommentar, und nur diese vier:

| Konstante | Wert | Messung |
|---|---|---|
| `FIRST_START_TIMEOUT_MS` | 12 000 | warmer Start 3,4–3,9 s |
| `PANE_FREE_TIMEOUT_S` | 6 | Frist für `ctrl-c` |
| `WARM_TIMEOUT_S` | 8 | 5 s wärmten 6/6, 8 s ist der Zuschlag |
| `HERDR_MAX_TIMEOUT_MS` | 300 000 | Herdrs eigene Obergrenze für `--timeout` |

## Global Constraints

- **Vier Abweichungen von der Spec, alle bewusst — ein Review meldet sie NICHT
  als Befund:**
  1. **`AGENT_START_REFUSAL_S` ist neu, und der Retry-Loop liest sie.** Spec §5.1
     sagt, der Loop gegen `agent_pane_busy` bleibe unverändert und dürfe mit dem
     Hänger „nicht vermischt werden". Genau das passiert aber, sobald `--timeout`
     durchgereicht wird: ein von Herdr ausgesessenes Budget endet mit *positivem*
     Exit-Code, also in derselben Form wie die Ablehnung — der Loop würde einen
     Hänger fünfmal wiederholen und aus 12 s würden 60. Die Schranke ist die
     Umsetzung des Spec-Satzes, nicht sein Bruch: sie trennt die beiden an dem
     Merkmal, das die Messung nennt — eine Ablehnung antwortet nach 0,0 s.
  2. **Eine schnelle Ablehnung bekommt keinen zweiten Anlauf.** Spec §5.1 lässt die
     Unterscheidung erst nach Versuch 2 fallen. Das Ergebnis ist dasselbe, dieser
     Weg aber billiger und ehrlicher: die Pane-Race ist innerhalb von `agent_start`
     schon fünfmal wiederholt, und ein `ctrl-c` in eine Pane, in der nichts läuft,
     ist eine Geste ins Leere.
  3. **Das Subprozessbudget ist `timeout_ms / 1000 + self.timeout`**, nicht
     `+ DEFAULT_TIMEOUT_S`. Dieselbe Form wie die Nachbarmethode `agent_prompt`
     (`herdr.py:agent_prompt`); `self.timeout` IST per Vorgabe `DEFAULT_TIMEOUT_S`,
     und ein Herdr mit eigenem Budget behält es so auch hier.
  4. **`start_agent` gibt `{"ok": bool, ...}` zurück, nicht die rohe Herdr-Antwort.**
     Die Aufrufer brauchen den Fehler*namen*; ein `{}` könnte ihn nicht tragen, und
     ein zweites Ausrechnen an zwei Stellen wäre genau der zweite Mechanismus, den
     dieser Plan abschafft.
- **Der Vertrag des Hauses gilt unverändert:** `Herdr`-Methoden werden zu `{}`, nie
  zu Ausnahmen. `start_agent` ist die eine Ausnahme von der *Form*, nicht von der
  Regel: es wirft ebenfalls nie, es antwortet nur reicher.
- **Drei Fehlerbilder, drei Bedeutungen, keine Überschneidung.**
  `agent_start_failed` = Herdr hat abgelehnt (falscher Name, unbekannte Art, Pane
  dauerhaft belegt) · `opencode_stuck` = auch der zweite Anlauf kam nicht bis zur
  Eingabebereitschaft, mit Pane- und Workspace-ID · `no_agent_id` = der Agent ist
  bereit, sein MCP-Server steht nicht in der Registry. Heute sind alle drei
  entweder `no_agent_id` oder `agent_start_failed`.
- **Die Pane bleibt bestehen.** Abgebrochen wird der Prozess, nicht die Kachel: kein
  Layout-Flackern, keine wechselnde Pane-ID im Ergebnis. Bleibt die Pane nach dem
  `ctrl-c` belegt, ist `opencode_stuck` der bewusst gewählte Ausgang — ehrlich, mit
  Pane-ID, statt sie zu schließen.
- **Kein neuer Konfigurationsschlüssel.** Weder für das Aufwärmen noch für die
  Fristen. `ready_timeout_s` bleibt bei 45 und wechselt nur die Rolle: es ist nicht
  mehr die tragende Frist, sondern das Netz unter dem Registry-Eintrag.
- **Herdrs Obergrenze wird gedeckelt, nicht angenommen.** `agent start --timeout`
  nimmt höchstens 300 000 ms; ein größer konfiguriertes `ready_timeout_s` wird beim
  Durchreichen darauf gedeckelt. Ohne den Deckel würde aus einem großzügigen Budget
  ein sofortiger Fehlschlag, weil Herdr den Aufruf ablehnt.
- **Kein Import-Zyklus.** `initcmd` importiert `OPENCODE_ORCHESTRATOR` aus
  `workspace` (Task 4). Das trägt, weil `workspace` seinerseits `initcmd` **nur
  innerhalb von `main()`** importiert. Wer diesen Import nach oben zieht, bricht den
  ersten Import des Pakets, nicht erst einen Test.
- **Testdauer.** Kein neuer Test schläft. `Clock` (Task 1) ist die Uhr, die der Test
  selbst stellt; jeder Pfad, der auf Dauer entscheidet, bekommt `now=` und `sleep=`
  gereicht.
- **Der schlechteste Fall von `up` wächst — gewollt, und kein Befund im Review.**
  `FIRST_START_TIMEOUT_MS` + `PANE_FREE_TIMEOUT_S` + `ready_timeout_s` für den
  zweiten Anlauf + `ready_timeout_s` für den Waiter, also rund 108 s bei den
  Vorgabewerten — vorausgesetzt, Herdr hält sein eigenes `--timeout` ein. Tut es
  das nicht, greift erst unser daraus abgeleitetes Budget, und die Decke liegt bei
  rund 128 s. Heute sind es 45 s, die nichts bewirken; im gewärmten Normalfall sind
  es danach unter 4 s.
- **Der Tastendruck sitzt den Hänger NICHT aus — und wird dadurch schneller, nicht
  langsamer.** `handlers.handle_bootstrap` ist der zweite Aufrufer von
  `start_orchestrator` und ruft ihn mit `min(role.ready_timeout_s,
  KEYSTROKE_READY_TIMEOUT_S)` = 6 s. Diese Deckelung hat einen eigenen, gemessenen
  Grund (`handlers.py:32-46`): Herdrs Handler-Prozess ist der falsche Ort, um 45 s
  auszusitzen, und der Kaltstart bleibt dort ein bewusst hingenommener Fehlalarm —
  „ihn abzudecken hieße, den Handler minutenlang zu blockieren". Ein pauschales
  `FIRST_START_TIMEOUT_MS` plus `PANE_FREE_TIMEOUT_S` plus zweiter Anlauf hätte dem
  Tastendruck ungefragt rund 30 s aufgezwungen. Zwei Regeln verhindern das:
  `start_orchestrator` leitet den ersten Versuch aus dem Budget ab, das der Aufrufer
  gewährt (`min(FIRST_START_TIMEOUT_MS, timeout_ms_for(ready_timeout_s))`), und
  `retry_on_hang=False` nimmt dem Tastendruck den zweiten Anlauf ganz. Sein
  schlechtester Fall wird damit 6 s + 6 s = 12 s gegen heute 16 s. Der abgebrochene
  erste Versuch wärmt trotzdem — gemessen wärmen schon 5 s —, der zweite
  Tastendruck trägt also, und genau so war der Fehlalarm dort immer gedacht.
- **Der geteilte Kern hat jetzt zwei Stellschrauben, und die zweite hat denselben
  Grund wie die erste.** `workspace_id` trennt „suchen oder anlegen" von „genau
  diesen nehmen", `retry_on_hang` trennt „darf minutenlang arbeiten" von „läuft in
  Herdrs Handler-Prozess". Beide Male ist der Unterschied nicht Geschmack, sondern
  der Ort, an dem der Aufrufer steht.
- **Non-Goals** (Ablehnungsgrund im Review, kein Versäumnis): kein Eingriff in das
  Zed-Plugin (`artisann.zed-herdr`) · `.opencode/plugins/lean-ctx-policy.js` bleibt
  unverändert · **kein `--pure` irgendwo** (es wärmt kopflos nicht, gemessen 6/6
  Hänger danach) · kein Schließen und Neuanlegen von Panes · keine
  Übersetzungsläufe, kein Refactoring nebenbei · keine Änderung an `settings.py`,
  `ordercmd.py`, `worktree.py` · an `handlers.py` **genau eine Zeile**:
  `retry_on_hang=False` im `start_orchestrator`-Aufruf, samt Begründung.
  `KEYSTROKE_READY_TIMEOUT_S` und alles andere dort bleibt, wie es ist.
- **Reihenfolge:** Task 2 setzt 1 voraus (der Helfer liest die Konstante und ruft die
  erweiterte Methode) · Task 3 setzt 2 voraus (er ruft den Helfer) · Task 4 ist von
  1–3 unabhängig, steht aber zuletzt, weil er das Netz erst spannt, nachdem `up`
  sich selbst helfen kann.

@phase "task-1"
## Task 1: `herdr.py` reicht Herdrs Budget durch

**Warum zuerst:** Defekt 3.1 der Spec verschwindet hier strukturell statt durch eine
größere Zahl. `Herdr.run` gibt jedem Aufruf `DEFAULT_TIMEOUT_S = 10.0`; Herdrs
`agent start` kehrt laut eigener Doku „erst zurück, wenn Herdr den erwarteten Agenten
erkannt hat und ihn für eingabebereit hält — Startvorgang standardmäßig 30 Sekunden".
Jeder Start über 10 s wird also von uns gekillt, mitten in Herdrs legitimer Wartezeit.

**Files:** Ändere `lean_herdr/herdr.py`, `tests/doubles.py`, `tests/test_herdr.py`.

**Interfaces — Produces:**

- `herdr.HERDR_MAX_TIMEOUT_MS: int`
- `herdr.AGENT_START_REFUSAL_S: float`
- `herdr.timeout_ms_for(seconds: float) -> int`
- `Herdr.pane_send_keys(self, pane: str, *keys: str) -> dict[str, Any]`
- `Herdr.agent_start(..., timeout_ms: int | None = None, now: Callable[[], float] = time.monotonic)`
- `tests.doubles.Clock`, `tests.doubles.ScriptedProc`

**Consumes:** die bestehenden Konstanten `AGENT_START_ATTEMPTS`,
`AGENT_START_INTERVAL_S`, `DEFAULT_TIMEOUT_S`, `NO_PROCESS_RC` und `Herdr._run`.

### Schritt 1 — den bestehenden Zustand ansehen, bevor etwas daran wächst

@read lean_herdr/herdr.py mode=signatures

@symbol body name=agent_start

Die drei Stellen, die dieser Task anfasst: der Konstantenblock am Dateikopf, die
Methode `agent_start` und der Platz für `pane_send_keys` neben `pane_split`.

### Schritt 2 — die Testdoubles, die Dauer und Reihenfolge ausdrücken können

`FakeProc` antwortet auf jeden passenden Aufruf gleich und sofort. Zwei Dinge, auf
die dieser Baum ab jetzt ankommt, lassen sich so nicht sagen: die **Reihenfolge**
(ein Start, der scheitert, und derselbe Aufruf, der danach durchgeht) und die
**Dauer** (eine Ablehnung nach 0,0 s gegen einen Start, den Herdr bis zu seinem
eigenen `--timeout` aussitzt).

Neuer Code in `tests/doubles.py`, unter `FakeProc`:

    @dataclass
    class Clock:
        """A monotonic clock the test moves itself.

        `agent_start` and `start_agent` tell a refusal from a hang by
        DURATION, and a test that really slept those seconds is a test
        nobody runs. Hand `now=clock.now` and `sleep=clock.sleep` in and the
        seconds pass without any passing.
        """

        t: float = 0.0

        def now(self) -> float:
            return self.t

        def sleep(self, seconds: float) -> None:
            self.t += seconds


    @dataclass
    class ScriptedProc(FakeProc):
        """FakeProc that also spends TIME and answers a SEQUENCE per prefix.

        Each `script` entry maps an argument prefix to `(cost_s, [reply, ...])`:
        the replies are handed out one per matching call, the last one
        repeating -- the same rule test_herdr.StartProc uses for its exit
        codes. A reply that is already a `Completed` is passed through
        untouched, so a script can express an EXIT CODE too; anything else
        goes through FakeProc's two stdout shapes. A prefix the script does
        not name falls through to FakeProc.
        """

        clock: Clock | None = None
        script: dict[tuple[str, ...], tuple[float, list[Any]]] = field(
            default_factory=dict
        )

        def __call__(self, cmd: list[str], **kwargs: Any) -> Completed:
            for prefix, (cost, replies) in self.script.items():
                if tuple(cmd[1 : 1 + len(prefix)]) != prefix:
                    continue
                seen = sum(
                    1 for c in self.calls if tuple(c[1 : 1 + len(prefix)]) == prefix
                )
                self.calls.append(list(cmd))
                if self.clock is not None:
                    self.clock.t += cost
                reply = replies[min(seen, len(replies) - 1)]
                if isinstance(reply, Completed):
                    return reply
                return Completed(stdout=self._stdout(reply))
            return super().__call__(cmd, **kwargs)

### Schritt 3 — die Konstanten

Neuer Code in `lean_herdr/herdr.py`, unter `AGENT_START_INTERVAL_S`:

    #: `agent start --timeout` takes at most this many milliseconds. A larger
    #: value is REFUSED, so a generously configured `ready_timeout_s` would turn
    #: into an instant failure instead of a long wait -- `timeout_ms_for()` caps
    #: it. Measured 2026-09-04 against 0.8.2.
    HERDR_MAX_TIMEOUT_MS = 300_000

    #: Above the whole cost of a run of pure refusals -- AGENT_START_ATTEMPTS
    #: answers after 0.0 s plus the sleeps between them -- and far below any
    #: `--timeout` a caller passes. An `agent start` slower than this did not
    #: lose the prompt race: Herdr sat it out to its own `--timeout`, which is
    #: opencode's first-bootstrap hang. Repeating THAT would cost five full
    #: budgets, so the loop below stops at it and `start_agent` reads it to tell
    #: the two failures apart.
    AGENT_START_REFUSAL_S = AGENT_START_ATTEMPTS * AGENT_START_INTERVAL_S + 1.0


    def timeout_ms_for(seconds: float) -> int:
        """A budget in seconds as Herdr's `--timeout`, capped at its maximum."""
        return min(int(seconds * 1000), HERDR_MAX_TIMEOUT_MS)

@call tdd(test_timeout_ms_for_caps_at_herdrs_own_maximum)

Der Testfall, verbatim, in `tests/test_herdr.py`:

    def test_timeout_ms_for_caps_at_herdrs_own_maximum():
        """A `ready_timeout_s` beyond Herdr's limit must not become a refusal."""
        assert timeout_ms_for(45) == 45_000
        assert timeout_ms_for(1.5) == 1_500
        assert timeout_ms_for(600) == HERDR_MAX_TIMEOUT_MS

### Schritt 4 — `pane_send_keys`

Neuer Code in `lean_herdr/herdr.py`, hinter `pane_split`:

    def pane_send_keys(self, pane: str, *keys: str) -> dict[str, Any]:
        """`herdr pane send-keys <PANE_ID> <KEY>...`.

        The pane id is POSITIONAL here, not `--pane` -- the same quirk
        `report_metadata` carries. Keys follow it positionally too.
        """
        return self.run("pane", "send-keys", pane, *keys)

@call tdd(test_pane_send_keys_puts_the_pane_id_first)

Der Testfall, verbatim:

    def test_pane_send_keys_puts_the_pane_id_first(fake):
        """The id is positional -- `--pane` here is exit 2."""
        h(fake).pane_send_keys("w8:p5", "ctrl-c")
        assert fake.calls == [["herdr", "pane", "send-keys", "w8:p5", "ctrl-c"]]

### Schritt 5 — `agent_start` reicht das Budget durch

Ändere die Methode. `--timeout` steht **vor** dem `--`, sonst reicht Herdr es an
opencode weiter statt es selbst zu lesen. Das Subprozessbudget wird aus demselben
Wert abgeleitet: `timeout_ms / 1000 + self.timeout` — dieselbe Form, die
`agent_prompt` schon benutzt.

@call patch("lean_herdr/herdr.py", "agent_start: timeout_ms + now in die Signatur, --timeout in die Argumente, budget an _run, die Refusal-Schranke in den Loop")

Die Methode danach, verbatim:

    def agent_start(
        self,
        name: str,
        *,
        kind: str,
        pane: str,
        agent_args: Sequence[str] = (),
        timeout_ms: int | None = None,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.monotonic,
    ) -> dict[str, Any]:
        """Start an agent in the pane. Native arguments after `--`.

        Herdr rejects multi-line arguments (H2) -- role texts come as a file,
        never as argument text.

        `timeout_ms` is Herdr's OWN `--timeout`: it returns only once it has
        recognised the expected agent and holds it ready for input, 30 s by
        default. Our subprocess budget is derived from it rather than set
        beside it -- without that, `DEFAULT_TIMEOUT_S` killed every start
        past 10 s in the middle of Herdr's legitimate wait, and the kill then
        read as a refusal. `--timeout` goes BEFORE the `--`: behind it, Herdr
        would hand the flag to the runtime instead of reading it.

        Retries a non-zero exit code up to AGENT_START_ATTEMPTS times: the
        pane split a moment ago may not have reached its interactive prompt
        yet, and that refusal is transient -- see the constants for the
        measurement. It stops early on an attempt that took longer than
        AGENT_START_REFUSAL_S: that one is not the race but a `--timeout`
        Herdr sat out, and repeating it would cost five full budgets.
        Returns the reply of the last attempt, `{}` when every one of them
        was refused; that empty dict is what the callers report on.
        """
        args = ["agent", "start", name, "--kind", kind, "--pane", pane]
        if timeout_ms is not None:
            args += ["--timeout", str(timeout_ms)]
        if agent_args:
            args = [*args, "--", *agent_args]
        budget = None if timeout_ms is None else timeout_ms / 1000.0 + self.timeout
        reply: dict[str, Any] = {}
        for attempt in range(AGENT_START_ATTEMPTS):
            started_at = now()
            reply, code = self._run(*args, timeout=budget)
            if code <= 0:
                # 0 is the start that worked. A NEGATIVE code is
                # NO_PROCESS_RC: no binary, an OSError, a timeout. None of
                # those is the prompt race, and repeating a timeout five
                # times would cost five full timeouts.
                return reply
            if now() - started_at >= AGENT_START_REFUSAL_S:
                return reply
            if attempt + 1 < AGENT_START_ATTEMPTS:
                sleep(AGENT_START_INTERVAL_S)
        return reply

### Schritt 6 — die drei Testfälle dazu

@call tdd(test_the_timeout_is_passed_through_and_becomes_the_subprocess_budget)

Verbatim, in `tests/test_herdr.py`:

    def test_the_timeout_is_passed_through_and_becomes_the_subprocess_budget(
        monkeypatch,
    ):
        """Herdr's own wait, and our budget derived from it -- not beside it."""
        monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
        seen: dict[str, Any] = {}

        def runner(cmd: list[str], **kwargs: Any) -> Completed:
            seen["cmd"], seen["budget"] = list(cmd), kwargs["timeout"]
            return Completed(stdout=json.dumps(STARTED))

        Herdr(runner=runner).agent_start(
            "orch",
            kind="opencode",
            pane="w8:p5",
            agent_args=["--agent", "orchestrator"],
            timeout_ms=12_000,
        )
        cmd = seen["cmd"]
        assert cmd[cmd.index("--timeout") + 1] == "12000"
        assert cmd.index("--timeout") < cmd.index("--"), (
            "behind the `--` Herdr hands the flag to opencode instead of reading it"
        )
        assert seen["budget"] == 12.0 + DEFAULT_TIMEOUT_S


    def test_without_a_timeout_nothing_changes_at_all(monkeypatch):
        """The callers that pass none keep today's behaviour, byte for byte."""
        monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
        seen: dict[str, Any] = {}

        def runner(cmd: list[str], **kwargs: Any) -> Completed:
            seen["cmd"], seen["budget"] = list(cmd), kwargs["timeout"]
            return Completed(stdout=json.dumps(STARTED))

        Herdr(runner=runner).agent_start("orch", kind="opencode", pane="w8:p5")
        assert "--timeout" not in seen["cmd"]
        assert seen["budget"] == DEFAULT_TIMEOUT_S


    def test_a_start_that_sat_out_its_budget_is_not_repeated(monkeypatch):
        """The hang is not the prompt race -- five repeats would cost five budgets.

        A refusal answers after 0.0 s (measured); a start Herdr sat out to its
        own `--timeout` answers after the whole budget, in exactly the same
        shape. Only the fast one is what AGENT_START_ATTEMPTS exists for.
        """
        monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
        clock = Clock()
        proc = ScriptedProc(
            clock=clock,
            script={("agent", "start"): (12.0, [Completed(returncode=1)])},
        )
        naps: list[float] = []
        assert (
            Herdr(runner=proc).agent_start(
                "orch",
                kind="opencode",
                pane="w8:p5",
                timeout_ms=12_000,
                sleep=naps.append,
                now=clock.now,
            )
            == {}
        )
        assert len(proc.calls) == 1, proc.flat()
        assert naps == []

Der Skript-Eintrag dieses Tests liefert eine `Completed`-Instanz statt eines
JSON-Werts — nur so läßt sich der positive Exit-Code ausdrücken, an dem der Loop
seine Entscheidung trifft. Das ist genau der Durchreichzweig, den `ScriptedProc` in
Schritt 2 dafür bekommen hat.

**Expected:** `uv run pytest -q tests/test_herdr.py` grün, und `uv run pytest -q`
ebenfalls — kein bestehender Aufrufer übergibt `timeout_ms`, das Verhalten ohne den
Parameter ist unverändert.

`tests/doubles.agent_started` bleibt, wie es ist. Beim letzten Eingriff dieser Art
brachen zehn Tests, weil sie auf der leeren Standardantwort des Doubles liefen —
diesmal vorher angesehen: `FakeProc` wählt seine Antwort über das **Präfix**
`("agent", "start")`, und `called_with(...)` prüft Token in Reihenfolge, nicht an
Position. Ein zusätzliches `--timeout` in den Argumenten ändert an beidem nichts.

### Verify & Close

@call verify(lean_herdr/herdr.py tests/doubles.py tests/test_herdr.py)
@call gate(lean_herdr/herdr.py tests/doubles.py tests/test_herdr.py)
@call commit("lean_herdr/herdr.py tests/doubles.py tests/test_herdr.py", "fix(herdr): pass Herdr's own start budget through instead of killing it")
@call remember_decision("herdr.AGENT_START_REFUSAL_S trennt eine Ablehnung nach 0,0 s von einem `--timeout`, das Herdr ausgesessen hat; der Retry-Loop und start_agent lesen dieselbe Konstante. tests/doubles.Clock + ScriptedProc drücken Dauer und Reihenfolge aus, ohne zu schlafen.")
@phase-end

@phase "task-2"
## Task 2: `herdr.start_agent` — der gemeinsame Helfer

@call recall_context("herdr.AGENT_START_REFUSAL_S, tests/doubles.Clock und ScriptedProc aus Task 1")

**Warum hier:** opencodes erster Bootstrap in einem Projekt mit Plugin hängt, und ein
Bootstrap, der weit genug kam und dann **abgebrochen** wurde, wärmt das Projekt — der
nächste Start läuft in 3,4 s. Der abgebrochene erste Start ist selbst das Aufwärmen;
ein zweiter Anlauf braucht deshalb keinen Sonderweg. Der Helfer lebt in `herdr.py`,
weil er ausschließlich aus Herdr-Verkehr besteht.

**Files:** Ändere `lean_herdr/herdr.py`, `tests/test_herdr.py`.

**Interfaces — Produces:**

- `herdr.FIRST_START_TIMEOUT_MS: int`, `herdr.PANE_FREE_TIMEOUT_S: float`,
  `herdr.PANE_FREE_INTERVAL_S: float`
- `herdr.start_agent(herdr, name, *, kind, pane, agent_args=(), first_timeout_ms=FIRST_START_TIMEOUT_MS, retry_timeout_ms, sleep=time.sleep, now=time.monotonic) -> dict[str, Any]`
  — antwortet `{"ok": True, "reply": <Herdr-Antwort>}`, im zweiten Anlauf zusätzlich
  `"retried": True`, sonst `{"ok": False, "error": "agent_start_failed"}` oder
  `{"ok": False, "error": "opencode_stuck"}`. `retry_timeout_ms <= 0` schaltet den
  zweiten Anlauf ab; der Hänger wird dann sofort `opencode_stuck`.

**Consumes:** `Herdr.agent_start` (Task 1), `Herdr.pane_send_keys` (Task 1),
`Herdr.agent_list`, `AGENT_START_REFUSAL_S` (Task 1).

### Schritt 1 — die Fristen

Neuer Code in `lean_herdr/herdr.py`, hinter `AGENT_START_REFUSAL_S`:

    #: The FIRST attempt's budget. A warm start measures 3.4-3.9 s (2026-09-04),
    #: so this is room to spare -- and short enough not to sit out a hang for
    #: the full `ready_timeout_s` before doing anything about it.
    FIRST_START_TIMEOUT_MS = 12_000

    #: How long `ctrl-c` gets to clear the pane before the second attempt.
    PANE_FREE_TIMEOUT_S = 6.0
    PANE_FREE_INTERVAL_S = 0.5

### Schritt 2 — die Pane räumen

Neuer Code in `lean_herdr/herdr.py`, hinter der Klasse `Herdr`:

    def _free_pane(
        herdr: Herdr,
        pane: str,
        *,
        sleep: Callable[[float], None],
        now: Callable[[], float],
    ) -> None:
        """`ctrl-c` the pane, then wait until no agent claims it any more.

        The pane STAYS. Aborting the process rather than closing the tile is
        what keeps the layout still and the pane id in the result stable --
        closing and re-splitting would change both.

        A second `ctrl-c` follows after half the deadline: a hung opencode
        never drew its surface and therefore never grabbed the key, while one
        that did draw it did.

        The wait STARTS with a sleep, and that order is the whole point. A
        hung start never got as far as being an agent, so `agent_list()`
        carries no entry for this pane to begin with -- polling first would
        return on the spot, give `ctrl-c` no time to land at all and make
        both PANE_FREE_TIMEOUT_S and the second key dead code. The deadline
        is a ceiling, not a promise: when it passes with the pane still
        taken, this returns anyway and lets the second attempt say so.
        """
        herdr.pane_send_keys(pane, "ctrl-c")
        deadline = now() + PANE_FREE_TIMEOUT_S
        again_at = now() + PANE_FREE_TIMEOUT_S / 2
        again = False
        while True:
            sleep(PANE_FREE_INTERVAL_S)
            if not any(a.get("pane_id") == pane for a in herdr.agent_list()):
                return
            if now() >= deadline:
                return
            if not again and now() >= again_at:
                herdr.pane_send_keys(pane, "ctrl-c")
                again = True

### Schritt 3 — der Helfer

Neuer Code in `lean_herdr/herdr.py`, hinter `_free_pane`:

    def start_agent(
        herdr: Herdr,
        name: str,
        *,
        kind: str,
        pane: str,
        agent_args: Sequence[str] = (),
        first_timeout_ms: int = FIRST_START_TIMEOUT_MS,
        retry_timeout_ms: int,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.monotonic,
    ) -> dict[str, Any]:
        """Start an agent, with a second attempt for opencode's first bootstrap.

        opencode's FIRST bootstrap in a project that carries a project plugin
        hangs -- and `workspace init` writes exactly such a plugin. Measured
        2026-09-04: the process stops right after loading the project config
        and never paints anything, not even after 300 s. A bootstrap that got
        far enough and was then ABORTED warms the project; the next start
        measures 3.4 s. So the aborted first attempt IS the warm-up, and the
        second one needs no special path at all.

        The detector is Herdr's own `--timeout`, never a poll of ours: it is
        documented, and Herdr knows before we do whether the agent is ready
        for input.

        Three answers, because they are three different repairs:

            {"ok": True, "reply": ...}            it is running
            {"ok": False, "error": "agent_start_failed"}   Herdr refused
            {"ok": False, "error": "opencode_stuck"}       the start hangs

        A refusal is answered at once and gets NO second attempt: it arrives
        after 0.0 s, the transient half of it was already repeated
        AGENT_START_ATTEMPTS times inside `agent_start`, and a `ctrl-c` into a
        pane where nothing runs is a gesture into the void.

        `retry_timeout_ms <= 0` switches the second attempt off entirely and
        turns the hang straight into `opencode_stuck`. That is for a caller
        that must not block: the keystroke runs inside Herdr's handler
        process (handlers.KEYSTROKE_READY_TIMEOUT_S), and there a hang is a
        deliberately accepted false alarm. It still pays nothing for the
        choice -- the aborted first attempt warms the project either way, so
        the next press is the one that carries.

        Never raises; the caller reads `ok`.
        """
        started_at = now()
        reply = herdr.agent_start(
            name,
            kind=kind,
            pane=pane,
            agent_args=agent_args,
            timeout_ms=first_timeout_ms,
            sleep=sleep,
            now=now,
        )
        if reply:
            return {"ok": True, "reply": reply}
        if now() - started_at < AGENT_START_REFUSAL_S:
            return {"ok": False, "error": "agent_start_failed"}
        if retry_timeout_ms <= 0:
            return {"ok": False, "error": "opencode_stuck"}
        _free_pane(herdr, pane, sleep=sleep, now=now)
        reply = herdr.agent_start(
            name,
            kind=kind,
            pane=pane,
            agent_args=agent_args,
            timeout_ms=retry_timeout_ms,
            sleep=sleep,
            now=now,
        )
        if reply:
            return {"ok": True, "reply": reply, "retried": True}
        return {"ok": False, "error": "opencode_stuck"}

### Schritt 4 — die vier Testfälle

@call tdd(test_a_start_that_works_costs_neither_a_key_nor_a_second_attempt)

Verbatim, in `tests/test_herdr.py`, hinter den `agent_start`-Tests:

    #: The helper's happy path and its two failures, all against a Clock: the
    #: distinction it makes is DURATION, and a test that slept those seconds
    #: would take a minute to say what these say in none.
    def _helper(proc: Any, clock: Clock) -> dict[str, Any]:
        return start_agent(
            Herdr(runner=proc),
            "orch",
            kind="opencode",
            pane="w8:p5",
            agent_args=["--agent", "orchestrator"],
            retry_timeout_ms=45_000,
            sleep=clock.sleep,
            now=clock.now,
        )


    def test_a_start_that_works_costs_neither_a_key_nor_a_second_attempt(monkeypatch):
        monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
        clock = Clock()
        proc = ScriptedProc(clock=clock, script={("agent", "start"): (3.4, [STARTED])})
        assert _helper(proc, clock) == {"ok": True, "reply": STARTED}
        assert not proc.called_with("pane", "send-keys"), proc.flat()
        assert len(proc.calls) == 1


    def test_a_hung_start_is_aborted_and_the_second_attempt_carries_it(monkeypatch):
        """The measured cure: `ctrl-c`, then the very same start in 3.4 s."""
        monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
        clock = Clock()
        proc = ScriptedProc(
            clock=clock,
            script={
                # First call sits out the whole `--timeout` and answers
                # nothing; the second one -- the project is warm now -- works.
                ("agent", "start"): (12.0, [{}, STARTED]),
                ("agent", "list"): (0.0, [{"result": {"agents": []}}]),
            },
        )
        assert _helper(proc, clock) == {
            "ok": True,
            "reply": STARTED,
            "retried": True,
        }
        assert proc.called_with("pane", "send-keys", "w8:p5", "ctrl-c")
        starts = [c for c in proc.calls if c[1:3] == ["agent", "start"]]
        assert len(starts) == 2
        assert starts[0][starts[0].index("--timeout") + 1] == str(
            FIRST_START_TIMEOUT_MS
        )
        assert starts[1][starts[1].index("--timeout") + 1] == "45000"


    def test_a_refusal_is_named_at_once_and_costs_no_second_attempt(monkeypatch):
        """0.0 s is Herdr saying no -- a name it does not know, a kind it has not."""
        monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
        clock = Clock()
        proc = ScriptedProc(clock=clock, script={("agent", "start"): (0.0, [{}])})
        assert _helper(proc, clock) == {"ok": False, "error": "agent_start_failed"}
        assert not proc.called_with("pane", "send-keys"), proc.flat()


    def test_a_second_attempt_that_fails_too_is_opencode_stuck(monkeypatch):
        """The honest exit of the residual risk: `ctrl-c` may not reach it."""
        monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
        clock = Clock()
        proc = ScriptedProc(
            clock=clock,
            script={
                ("agent", "start"): (12.0, [{}]),
                # The pane stays taken: the hung process never let go.
                ("agent", "list"): (
                    0.0,
                    [{"result": {"agents": [{"name": "orch", "pane_id": "w8:p5"}]}}],
                ),
            },
        )
        assert _helper(proc, clock) == {"ok": False, "error": "opencode_stuck"}
        keys = [c for c in proc.calls if c[1:3] == ["pane", "send-keys"]]
        assert len(keys) == 2, "a second ctrl-c after half the deadline"


    def test_without_a_retry_budget_the_hang_is_reported_at_once(monkeypatch):
        """The keystroke's path: it runs in Herdr's handler process.

        There a hang is a deliberately accepted false alarm
        (handlers.KEYSTROKE_READY_TIMEOUT_S) -- blocking that process for a
        second attempt would be the very thing the cap exists to prevent.
        Nothing is lost: the aborted first attempt warms the project anyway,
        so the next press carries.
        """
        monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
        clock = Clock()
        proc = ScriptedProc(clock=clock, script={("agent", "start"): (6.0, [{}])})
        assert start_agent(
            Herdr(runner=proc),
            "orch",
            kind="opencode",
            pane="w8:p5",
            first_timeout_ms=6_000,
            retry_timeout_ms=0,
            sleep=clock.sleep,
            now=clock.now,
        ) == {"ok": False, "error": "opencode_stuck"}
        assert len(proc.calls) == 1, proc.flat()
        assert not proc.called_with("pane", "send-keys"), (
            "no key, no poll, no second attempt -- the handler must come back"
        )

Der Import in `tests/test_herdr.py` wächst um `FIRST_START_TIMEOUT_MS`,
`HERDR_MAX_TIMEOUT_MS`, `DEFAULT_TIMEOUT_S`, `start_agent`, `timeout_ms_for` und um
`Clock`, `ScriptedProc` aus `tests.doubles`.

**Expected:** `uv run pytest -q tests/test_herdr.py` grün. Kein Produktionsaufrufer
benutzt `start_agent` bisher — die volle Suite bleibt unverändert grün.

### Verify & Close

@call verify(lean_herdr/herdr.py tests/test_herdr.py)
@call gate(lean_herdr/herdr.py tests/test_herdr.py)
@call review_change()
@call commit("lean_herdr/herdr.py tests/test_herdr.py", "feat(herdr): a second attempt for the first opencode bootstrap")
@call remember_decision("herdr.start_agent ist der EINE Startweg fuer up und dispatch: Versuch 1 mit FIRST_START_TIMEOUT_MS, bei einem Haenger ctrl-c und Versuch 2 mit dem vollen ready_timeout_s. Es antwortet {ok, reply|error} -- agent_start_failed fuer eine Ablehnung, opencode_stuck fuer den Haenger.")
@phase-end

@phase "task-3"
## Task 3: `workspace.py` und `dispatch.py` — ein Aufruf statt zweier Pfade

@call recall_context("herdr.start_agent, seine drei Antworten und die Konstanten aus Task 2")

**Warum:** Defekt 3.2 der Spec. `agent_start` liefert für unseren eigenen Timeout
`NO_PROCESS_RC`, `agent_start` kehrt bei `code <= 0` mit `{}` zurück, und seit
`51dac35` melden beide Aufrufer darauf `agent_start_failed` und **überspringen den
Waiter** — während in der Pane ein funktionierender Agent hochkommt, den niemand mehr
beobachtet. Ein langsamer, aber erfolgreicher Start wird so zu einer gemeldeten
Störung plus einem verwaisten Orchestrator.

**Files:** Ändere `lean_herdr/workspace.py`, `lean_herdr/dispatch.py`,
`tests/test_workspace.py`, `tests/test_dispatch.py`.

**Interfaces — Consumes:** `herdr.start_agent`, `herdr.FIRST_START_TIMEOUT_MS`,
`herdr.timeout_ms_for`. **Produces:** das neue Fehlerbild `opencode_stuck` in beiden
Ergebnisformen — in `workspace` mit `workspace` und `pane`, in `dispatch` mit `pane`.

### Schritt 1 — die beiden Stellen ansehen

@symbol body name=start_orchestrator

@symbol body name=dispatch

Beide tragen heute denselben `herdr.agent_start(...)`-Aufruf mit derselben
`if not started:`-Prüfung und demselben Kommentarblock darüber. Beide werden ersetzt.

### Schritt 2 — `workspace.py`

Der Import wächst:

    from lean_herdr.herdr import (
        FIRST_START_TIMEOUT_MS,
        Herdr,
        start_agent,
        timeout_ms_for,
    )

@call patch("lean_herdr/workspace.py", "start_orchestrator: der agent_start-Aufruf samt if-not-started-Block wird der start_agent-Aufruf")

Der Block danach, verbatim — er ersetzt alles von `started = herdr.agent_start(`
bis zum Ende des `if not started:`-Zweigs:

    # Both budgets come out of the ONE the caller granted. `up` grants 45 s
    # and gets the full FIRST_START_TIMEOUT_MS; the keystroke grants 6
    # (handlers.KEYSTROKE_READY_TIMEOUT_S) and its first attempt shrinks with
    # it -- a flat 12 s would have made a keystroke sit in Herdr's handler
    # process for twice what that cap allows.
    started = start_agent(
        herdr,
        ORCHESTRATOR_AGENT,
        kind=settings.kind,
        pane=pane,
        agent_args=agent_args,
        first_timeout_ms=min(
            FIRST_START_TIMEOUT_MS, timeout_ms_for(ready_timeout_s)
        ),
        retry_timeout_ms=timeout_ms_for(ready_timeout_s) if retry_on_hang else 0,
    )
    if not started["ok"]:
        # Two failures, two names, and the helper is the one that can tell
        # them apart: `agent_start_failed` is Herdr saying no after 0.0 s,
        # `opencode_stuck` is a start that did not reach readiness even on
        # the second attempt. Both carry the pane, because the tile is still
        # there and the operator needs to find it -- the helper aborts the
        # PROCESS, never the pane.
        return {
            "ok": False,
            "error": started["error"],
            "workspace": target,
            "pane": pane,
        }

`ready_timeout_s` ist bereits ein Parameter von `start_orchestrator` — der zweite
Anlauf bekommt damit das volle konfigurierte Budget, und der Waiter danach seines.

Die Signatur wächst um **einen** Parameter, direkt hinter `ready_timeout_s`:

    retry_on_hang: bool = True,

und der Docstring von `start_orchestrator` um den Absatz, der ihn erklärt:

    `retry_on_hang=False` takes the second attempt away: a hang is then
    reported at once instead of being sat out. That is the keystroke's path
    -- `handle_bootstrap` runs inside Herdr's handler process, which is the
    wrong place to block (handlers.KEYSTROKE_READY_TIMEOUT_S), and the cold
    start is a deliberately accepted false alarm there. It costs that path
    nothing: the aborted first attempt warms the project anyway, so the next
    press is the one that carries.

Das ist die **zweite** Stellschraube dieses Kerns, und sie trennt dieselbe Sache wie
die erste: nicht Geschmack, sondern den Ort, an dem der Aufrufer steht.

### Schritt 3 — `dispatch.py`

Der Import wächst um dieselben drei Namen:

    from lean_herdr.herdr import (
        FIRST_START_TIMEOUT_MS,
        Herdr,
        start_agent,
        timeout_ms_for,
    )

@call patch("lean_herdr/dispatch.py", "dispatch: der agent_start-Aufruf samt if-not-started-Block wird der start_agent-Aufruf")

Der Block danach, verbatim:

        started = start_agent(
            herdr,
            name,
            kind=req.kind,
            pane=pane,
            agent_args=agent_args(req.kind, req.model, req.role_file),
            first_timeout_ms=FIRST_START_TIMEOUT_MS,
            retry_timeout_ms=timeout_ms_for(cfg.ready_timeout_s),
        )
        if not started["ok"]:
            # `agent_start_failed` is Herdr refusing after 0.0 s;
            # `opencode_stuck` is opencode's first bootstrap in this project
            # hanging, twice. ONE mechanism with `workspace up` -- a worktree
            # is a new project to opencode, so a worker meets the very same
            # hang the orchestrator does.
            return _result(False, pane, None, error=started["error"])

### Schritt 4 — `handlers.py`, genau eine Zeile

`handle_bootstrap` ist der zweite Aufrufer von `start_orchestrator`, und der einzige,
der in Herdrs Handler-Prozess läuft. Er bekommt eine Zeile mehr im bestehenden
Aufruf (`handlers.py:226-233`), unmittelbar hinter `ready_timeout_s=`:

    retry_on_hang=False,

und darüber die Begründung, die an `KEYSTROKE_READY_TIMEOUT_S` anschließt:

            # No second attempt here, for the same reason the timeout above is
            # capped: this process is Herdr's, and a hung first bootstrap
            # would hold it for another PANE_FREE_TIMEOUT_S plus a whole
            # retry. The cold start stays the accepted false alarm it already
            # is -- and it now cures itself, because the aborted attempt warms
            # the project and the next press comes up warm.

@call patch("lean_herdr/handlers.py", "handle_bootstrap: retry_on_hang=False in den start_orchestrator-Aufruf, mit der Begruendung darueber")

Sonst wird an `handlers.py` nichts angefasst — `KEYSTROKE_READY_TIMEOUT_S` behält
Wert und Kommentar.

### Schritt 5 — die Tests

Die bestehenden `test_a_refused_agent_start_is_reported_instead_of_waited_out` in
**beiden** Dateien bleiben unverändert grün: `FakeProc` antwortet sofort, der Helfer
nimmt den Ablehnungszweig, kein zweiter Anlauf, kein `ctrl-c`. Das ist der Beleg,
dass `agent_start_failed` weiterhin der echten Ablehnung gehört — prüfe es, bevor du
etwas an ihnen änderst.

@call tdd(test_a_hung_start_is_reported_as_opencode_stuck_with_pane_and_workspace)

Verbatim, in `tests/test_workspace.py`:

    def test_a_hung_start_is_reported_as_opencode_stuck_with_pane_and_workspace(
        monkeypatch,
    ):
        """The new error, and the two ids the operator needs to find the tile.

        `agent_start_failed` stays reserved for a real refusal; a start that
        hung through both attempts gets its own name, because it is its own
        repair -- the tile is alive and holds a process that never painted.
        """
        replies = {
            ("workspace", "list"): BY_WORKTREE,
            ("agent", "list"): NO_AGENTS,
            ("pane", "list"): PANES,
            ("pane", "split"): SPLIT,
        }
        herdr, _ = herdr_with(monkeypatch, replies)
        monkeypatch.setattr(
            workspace,
            "start_agent",
            lambda *a, **kw: {"ok": False, "error": "opencode_stuck"},
        )

        def waiter(*_a, **_kw):
            raise AssertionError("the waiter must not run after a stuck start")

        assert core(herdr, waiter=waiter) == {
            "ok": False,
            "error": "opencode_stuck",
            "workspace": "w3",
            "pane": "w3:p9",
        }


    def test_the_orchestrator_start_goes_through_the_shared_helper(monkeypatch):
        """One mechanism, not two -- and the retry gets the configured budget."""
        replies = {
            ("workspace", "list"): BY_WORKTREE,
            ("agent", "list"): NO_AGENTS,
            ("pane", "list"): PANES,
            ("pane", "split"): SPLIT,
        }
        herdr, _ = herdr_with(monkeypatch, replies)
        seen: dict[str, object] = {}
        real = workspace.start_agent

        def spy(*a, **kw):
            seen.update(kw)
            return real(*a, **kw)

        monkeypatch.setattr(workspace, "start_agent", spy)
        core(herdr, ready_timeout_s=45.0)
        assert seen["first_timeout_ms"] == FIRST_START_TIMEOUT_MS
        assert seen["retry_timeout_ms"] == 45_000


    def test_a_small_budget_shrinks_the_first_attempt_with_it(monkeypatch):
        """The keystroke grants 6 s -- the first attempt must not take 12.

        `handle_bootstrap` runs inside Herdr's handler process and caps the
        budget at KEYSTROKE_READY_TIMEOUT_S for a measured reason. A flat
        FIRST_START_TIMEOUT_MS would have made the keystroke block for twice
        that cap before anything else even started.
        """
        replies = {
            ("workspace", "list"): BY_WORKTREE,
            ("agent", "list"): NO_AGENTS,
            ("pane", "list"): PANES,
            ("pane", "split"): SPLIT,
        }
        herdr, _ = herdr_with(monkeypatch, replies)
        seen: dict[str, object] = {}
        real = workspace.start_agent

        def spy(*a, **kw):
            seen.update(kw)
            return real(*a, **kw)

        monkeypatch.setattr(workspace, "start_agent", spy)
        core(herdr, ready_timeout_s=6.0, retry_on_hang=False)
        assert seen["first_timeout_ms"] == 6_000
        assert seen["retry_timeout_ms"] == 0, "no second attempt for the keystroke"

Und verbatim in `tests/test_dispatch.py`:

    def test_a_worker_start_goes_through_the_same_helper(world, monkeypatch):
        """`dispatch` must not grow a second start path.

        A worktree is a NEW project to opencode, so a worker meets the very
        same first-bootstrap hang the orchestrator does. One helper, one
        retry, one pair of error names.
        """
        h_proc, _ = world
        seen: dict[str, object] = {}
        real = dispatch_module.start_agent

        def spy(*a, **kw):
            seen.update(kw)
            return real(*a, **kw)

        monkeypatch.setattr(dispatch_module, "start_agent", spy)
        run_dispatch(world, reg=registry())
        assert seen["first_timeout_ms"] == FIRST_START_TIMEOUT_MS
        assert seen["retry_timeout_ms"] == timeout_ms_for(AGENT_READY_TIMEOUT_S)


    def test_a_hung_worker_start_is_opencode_stuck(world, monkeypatch):
        h_proc, _ = world
        monkeypatch.setattr(
            dispatch_module,
            "start_agent",
            lambda *a, **kw: {"ok": False, "error": "opencode_stuck"},
        )
        result = run_dispatch(
            world,
            reg=registry(),
            waiter=lambda *a, **kw: pytest.fail("no waiter after a stuck start"),
        )
        assert result == {
            "ok": False,
            "pane": "w1:p6",
            "agent_id": None,
            "error": "opencode_stuck",
        }

`tests/test_dispatch.py` importiert heute nur **Namen** aus `lean_herdr.dispatch`
(`AGENT_ENV`, `AGENT_READY_TIMEOUT_S`, `dispatch`, `main`, …), nicht das Modul —
`monkeypatch.setattr` braucht aber das Modulobjekt. Der Importblock bekommt deshalb
eine neue Zeile und eine erweiterte:

    from lean_herdr import dispatch as dispatch_module
    from lean_herdr.herdr import FIRST_START_TIMEOUT_MS, Herdr, timeout_ms_for

`Herdr` steht dort schon in einer eigenen `from lean_herdr.herdr import`-Zeile —
erweitere die, statt eine zweite danebenzusetzen. `AGENT_READY_TIMEOUT_S` ist
bereits importiert; `test_the_ready_timeout_default_exists_only_once` hält es an
`RoleSettings.ready_timeout_s` gebunden, also ist es hier der richtige Name.

Und verbatim in `tests/test_handlers.py`, zum Aufruf aus `handle_bootstrap`:

    def test_the_keystroke_asks_for_no_second_attempt(world, monkeypatch):
        """It runs in Herdr's handler process -- it must come back quickly.

        `KEYSTROKE_READY_TIMEOUT_S` caps the wait for a measured reason; a
        retry behind it would add PANE_FREE_TIMEOUT_S plus a whole second
        start to a process that is not ours to block. The cold start stays
        the accepted false alarm it already is -- and it now cures itself,
        because the aborted attempt warms the project.
        """
        _, _, tmp_path = world
        seen: list[dict] = []
        monkeypatch.setattr(
            "lean_herdr.workspace.start_orchestrator",
            lambda **kwargs: (seen.append(kwargs), {"ok": True})[1],
        )
        handlers.handle_bootstrap(cfg(tmp_path, HERDR_PLUGIN_EVENT_JSON=json.dumps(
            {"workspace_id": "w2", "workspace": {"cwd": "/repo"}}
        )))
        assert seen[0]["retry_on_hang"] is False
        assert seen[0]["ready_timeout_s"] == handlers.KEYSTROKE_READY_TIMEOUT_S

Das ist Zeile für Zeile der Weg, den `test_bootstrap_resolves_start_orchestrator_at_
call_time` (`tests/test_handlers.py:377-397`) schon geht — inklusive des Grundes,
warum der Patch auf `lean_herdr.workspace` zielt und nicht auf `handlers`:
`handle_bootstrap` importiert den Namen **auf dem Aufruf** (`handlers.py:220`), also
hält `handlers` nie einen, den man patchen könnte.

**Expected:** `uv run pytest -q` vollständig grün. Besonders zu prüfen, weil hier
schon einmal zehn Tests brachen: kein Test in `tests/test_workspace.py`,
`tests/test_dispatch.py`, `tests/test_dispatch_uncovered_paths.py` oder
`tests/test_handlers.py` läuft auf der leeren Standardantwort des Doubles statt auf
`agent_started(...)`.

### Verify & Close

@call verify(lean_herdr/workspace.py lean_herdr/dispatch.py lean_herdr/handlers.py tests/test_workspace.py tests/test_dispatch.py tests/test_handlers.py)
@call gate(lean_herdr/workspace.py lean_herdr/dispatch.py lean_herdr/handlers.py tests/test_workspace.py tests/test_dispatch.py tests/test_handlers.py)
@call review_change()
@call commit("lean_herdr/workspace.py lean_herdr/dispatch.py lean_herdr/handlers.py tests/test_workspace.py tests/test_dispatch.py tests/test_handlers.py", "fix(workspace,dispatch): one start path with a second attempt, and a name for the hang")
@call remember_decision("up und dispatch starten Agenten ausschliesslich ueber herdr.start_agent. opencode_stuck traegt in workspace Pane und Workspace, in dispatch die Pane; agent_start_failed bleibt der echten Ablehnung durch Herdr vorbehalten. start_orchestrator leitet first_timeout_ms aus ready_timeout_s ab und nimmt retry_on_hang: der Tastendruck (handlers.KEYSTROKE_READY_TIMEOUT_S = 6 s) bekommt keinen zweiten Anlauf, weil er in Herdrs Handler-Prozess laeuft.")
@phase-end

@phase "task-4"
## Task 4: `initcmd.py` wärmt das Projekt einmal, kopflos

@call recall_context("herdr.start_agent und der zweite Anlauf aus Task 2 und 3")

**Warum zuletzt:** Der Wiederanlauf aus Task 2/3 ist das Netz — er trägt Projekte, die
vor diesem Fix eingerichtet wurden, und Worktrees, die für opencode neue Projekte
sind. Das Aufwärmen ist der Normalweg: die Erstlast fällt dort an, wo sie sichtbar und
harmlos ist, nicht im heißen Pfad. Danach kostet der Wiederanlauf im Normalfall nie
etwas, weil Versuch 1 trägt.

Gemessen (2026-09-04, je drei Läufe in frischen git-Repos): `opencode debug agent
<name>` **mit** `--pure` wärmt in 3 von 3 Fällen **nicht** — der Schalter überspringt
externe Plugins, also genau den Schritt, der gewärmt werden muss. Ohne `--pure`, nach
5 s abgebrochen: 3 von 3 gewärmt, danach 3,4 s bis zur Oberfläche.

**Files:** Ändere `lean_herdr/initcmd.py`, `tests/test_initcmd.py`, `README.md`.

**Interfaces — Produces:** `initcmd.WARM_TIMEOUT_S: float`,
`initcmd._warm_opencode(root: Path, *, runner: Any) -> bool`, und das neue Feld
`warmed: bool` im Ergebnis von `workspace_init`.

**Consumes:** `workspace.OPENCODE_ORCHESTRATOR` — der Agentname wird importiert, nie
ein zweites Mal buchstabiert; er muß derselbe sein, den `up` später übergibt.
Weiter `settings.SETTINGS_PATH`, `settings.SettingsError`, `settings.read_settings`,
`settings.workspace_settings`.

### Schritt 1 — den Kopf von `initcmd.py` ansehen

@read lean_herdr/initcmd.py mode=signatures

Der Modul-Docstring nennt heute als zweite Regel: „preconditions are REPORTED, never
repaired. Every foreign command here only READS". Das Aufwärmen ist die eine Ausnahme
und muß dort auch so stehen — es ändert nichts an der Maschine des Betreibers,
sondern nur in opencodes eigenem Projekt-Cache.

### Schritt 2 — die Importe und die Frist

Neuer Code am Kopf von `lean_herdr/initcmd.py`, bei den bestehenden Importen:

    from lean_herdr.settings import (
        SETTINGS_PATH,
        SettingsError,
        read_settings,
        workspace_settings,
    )
    from lean_herdr.workspace import OPENCODE_ORCHESTRATOR

Dieser Import trägt, weil `workspace` seinerseits `initcmd` **nur innerhalb von
`main()`** importiert. Wer den dortigen Import nach oben zöge, bräche den ersten
Import des Pakets.

Neuer Code unter `CHECK_TIMEOUT_S`:

    #: The warm-up, and the one number it turns on. opencode's FIRST bootstrap
    #: in a project that carries a project plugin hangs -- and the plugin this
    #: very command writes is such a plugin. A bootstrap that got far enough
    #: and was then ABORTED warms the project; the next start measures 3.4 s.
    #: 5 s warmed 6 of 6 runs on 2026-09-04, 8 s is the margin. The ABORT is
    #: the point: the exit code and the output are worthless here.
    #:
    #: NOT `--pure`: that switch skips external plugins, i.e. exactly the step
    #: that has to be warmed. Measured 3 of 3 still hanging afterwards.
    WARM_TIMEOUT_S = 8.0

### Schritt 3 — das Aufwärmen selbst

Neuer Code in `lean_herdr/initcmd.py`, hinter `_warnings`:

    def _warm_opencode(root: Path, *, runner: Any) -> bool:
        """One aborted `opencode debug agent` in `root`. True when it ran.

        The only foreign command in this module that is not a pure read --
        and it still changes nothing on the operator's machine, only inside
        opencode's own cache for this project.

        Silent on every failure: a warm-up that did not happen costs the next
        `workspace up` its second attempt and nothing else, while an
        exception here would take the written/skipped report with it.
        """
        if shutil.which("opencode") is None:
            return False
        try:
            runner(
                ["opencode", "debug", "agent", OPENCODE_ORCHESTRATOR],
                capture_output=True,
                text=True,
                timeout=WARM_TIMEOUT_S,
                cwd=str(root),
                check=False,
            )
        except subprocess.TimeoutExpired:
            # The expected end, not an error: the abort IS the warm-up.
            return True
        except (OSError, subprocess.SubprocessError):
            return False
        return True

### Schritt 4 — `workspace_init` ruft es und meldet `warmed`

@call patch("lean_herdr/initcmd.py", "workspace_init: der Rueckgabeblock bekommt das Aufwaermen und das Feld warmed")

Der Block danach, verbatim — er ersetzt das abschließende `return {...}`:

    warnings = _warnings(base, runner=runner)
    warmed = False
    try:
        kind = workspace_settings(read_settings(base / SETTINGS_PATH)).kind
    except SettingsError as exc:
        # A config we cannot read is not a reason to fail `init` -- the files
        # are already written. It only means we cannot tell whether opencode
        # is the runtime here, so the warm-up is skipped and said so.
        warnings.append(f"no warm-up: {exc}")
        kind = ""
    if kind == "opencode":
        warmed = _warm_opencode(base, runner=runner)
    return {
        "ok": True,
        "root": str(base),
        "written": sorted(written),
        "skipped": sorted(skipped),
        "warmed": warmed,
        "warnings": warnings,
    }

Und im Modul-Docstring die zweite Regel um ihre eine Ausnahme ergänzen:

    The second: preconditions are REPORTED, never repaired. Every foreign
    command here only READS -- `lean-ctx allow --list`, `wt config approvals
    list --format json`, `herdr plugin list`. `init` runs no `lean-ctx allow`
    and no `wt config approvals add`: granting a machine-wide permission is a
    gesture that belongs to the human at the keyboard. The ONE exception is
    the warm-up (`_warm_opencode`), and it stays inside the rule's intent: it
    changes nothing on the machine, only opencode's own cache for this
    project, and it is aborted on purpose.

### Schritt 5 — die Tests

@call tdd(test_init_warms_the_project_once_and_says_so)

Verbatim, in `tests/test_initcmd.py`:

    def test_init_warms_the_project_once_and_says_so(monkeypatch, repo):
        """The first opencode bootstrap here would hang -- so `init` spends it.

        Measured 2026-09-04: a bootstrap that got far enough and was then
        aborted warms the project, and the next start takes 3.4 s instead of
        hanging. `init` is where that cost is visible and harmless.
        """
        monkeypatch.setattr("shutil.which", which_stub(True))
        proc = FakeProc(default="")
        answer = workspace_init(root=repo, runner=proc)
        assert answer["warmed"] is True
        warm = [c for c in proc.calls if c[0] == "opencode"]
        assert warm == [["opencode", "debug", "agent", OPENCODE_ORCHESTRATOR]]
        assert "--pure" not in warm[0], (
            "--pure skips external plugins -- exactly the step to be warmed "
            "(measured 3 of 3 still hanging afterwards)"
        )


    def test_the_warm_up_budget_is_hard_and_the_abort_is_the_point(monkeypatch, repo):
        """It is aborted, and the abort counts as warmed -- not as a failure."""
        monkeypatch.setattr("shutil.which", which_stub(True))
        seen: dict[str, object] = {}

        def runner(cmd, **kwargs):
            if cmd[0] == "opencode":
                seen["timeout"] = kwargs["timeout"]
                seen["cwd"] = kwargs["cwd"]
                raise subprocess.TimeoutExpired(cmd=cmd, timeout=WARM_TIMEOUT_S)
            return Completed(stdout="")

        assert workspace_init(root=repo, runner=runner)["warmed"] is True
        assert seen["timeout"] == WARM_TIMEOUT_S
        assert seen["cwd"] == str(repo), "the project is what gets warmed"


    def test_without_opencode_on_path_nothing_is_warmed_and_nothing_is_said(
        monkeypatch, repo
    ):
        """Silent, like every other check that cannot run."""
        quiet(monkeypatch)
        proc = FakeProc(default="")
        answer = workspace_init(root=repo, runner=proc)
        assert answer["warmed"] is False
        assert not any(c[0] == "opencode" for c in proc.calls), proc.flat()


    def test_a_claude_project_is_not_warmed(monkeypatch, repo):
        """The hang is opencode's; a claude workspace pays nothing for it.

        The config is placed BEFORE the run, and the run gets no `--force`:
        `_place` skips a file that is already there, so the `kind` written
        here is the one the warm-up decision reads. With `--force` the
        template would land on top of it and the test would measure the
        default instead of what it set.
        """
        monkeypatch.setattr("shutil.which", which_stub(True))
        (repo / SETTINGS_PATH).parent.mkdir(parents=True, exist_ok=True)
        (repo / SETTINGS_PATH).write_text(
            '[workspace]\nkind = "claude"\n', encoding="utf-8"
        )
        proc = FakeProc(default="")
        answer = workspace_init(root=repo, runner=proc)
        assert answer["warmed"] is False
        assert not any(c[0] == "opencode" for c in proc.calls), proc.flat()

Die mitgelieferte Vorlage `lean_herdr/templates/config.toml` hat **jede** Zeile
auskommentiert — `workspace_settings({})` liefert also `kind == "opencode"`, und ein
frisches Projekt wird gewärmt. Genau deshalb muß der claude-Test seine Config selbst
setzen, bevor `init` läuft.

Die Importe in `tests/test_initcmd.py` wachsen um `WARM_TIMEOUT_S`,
`SETTINGS_PATH` (aus `lean_herdr.settings`), `OPENCODE_ORCHESTRATOR` (aus
`lean_herdr.workspace`) und `Completed` (aus `tests.doubles`).

**Bestehende Tests, vorher ansehen statt hinterher reparieren:**
`test_a_healthy_machine_warns_about_nothing` und
`test_every_missing_precondition_becomes_one_line` laufen mit `which_stub(True)` —
dort läuft das Aufwärmen jetzt mit und legt einen Aufruf mehr in `FakeProc.calls`.
Beide prüfen nur `warnings`, bleiben also grün.
`test_a_machine_without_the_three_binaries_names_every_one_of_them` prüft
`proc.calls == []` und läuft mit `which_stub(False)` — kein `opencode` auf PATH, kein
Aufruf. `test_init_never_runs_a_command_that_changes_anything` prüft drei verbotene
Muster; `opencode debug agent` ist keins davon und ändert nichts an der Maschine.

### Schritt 6 — README

@call patch("README.md", "unter `## Setting up a project`, hinter dem Absatz ueber die acht Dateien: ein Absatz ueber das Aufwaermen")

Neuer Text, verbatim, als eigener Absatz:

    It also spends one aborted opencode bootstrap in the project, up to eight
    seconds. opencode's first bootstrap in a project that carries a project
    plugin hangs -- and one of the eight files is such a plugin. The aborted
    run is the cure: every start after it takes about three seconds. The
    result reports it as `warmed`; without `opencode` on PATH, or in a
    workspace whose `kind` is not `opencode`, it is `false` and nothing runs.

**Expected:** `uv run pytest -q` vollständig grün, und in einem frischen Repo:

    lean-herdr workspace init
    # -> {"ok": true, ..., "warmed": true, "warnings": [...]}
    lean-herdr workspace up
    # -> {"ok": true, ...} in unter 5 s, ohne zweiten Anlauf

### Verify & Close

@call verify(lean_herdr/initcmd.py tests/test_initcmd.py README.md)
@call gate(lean_herdr/initcmd.py tests/test_initcmd.py README.md)
@call review_change()
@call commit("lean_herdr/initcmd.py tests/test_initcmd.py README.md", "feat(init): warm the project once, where the first bootstrap is harmless")
@call remember_decision("workspace init waermt das Projekt mit einem abgebrochenen `opencode debug agent <OPENCODE_ORCHESTRATOR>` (WARM_TIMEOUT_S=8, kein --pure, cwd=root) und meldet `warmed`. Der Agentname kommt per Import aus workspace.py -- er muss derselbe sein, den up spaeter uebergibt.")
@phase-end

## Nachtrag — was der Review danach noch geaendert hat

Der Plan wurde am 2026-09-04 vollstaendig umgesetzt (`fc607cd`, `b5b1e8a`,
`ef70bba`, `3e7c83d`). Der Branch-Review danach fand sechs Stellen, an denen der
oben abgedruckte Code **nicht** stehengeblieben ist. Wer diesen Plan spaeter
liest, findet im Baum also bewusst etwas anderes; die Gruende stehen als
Kommentar an Ort und Stelle.

In `2bb924f`:

1. **`_free_pane` gab `ctrl-c` real 0,5 s statt 6.** Ein Haenger wird nie Agent,
   also trug `agent_list()` keinen Eintrag fuer die Pane, und `not any(...)` war
   schon im ersten Durchlauf wahr — `PANE_FREE_TIMEOUT_S` und das zweite
   `ctrl-c` waren im *gewollten* Fall toter Code, und der Docstring behauptete
   das Gegenteil. Die Pane gilt jetzt erst als frei, nachdem das zweite
   `ctrl-c` raus ist.
2. **`start_agent` hebt `first_timeout_ms` auf `timeout_ms_for(AGENT_START_REFUSAL_S)`
   an.** Der Ablehnungs/Haenger-Test ist ein *Dauer*-Test; ein Budget unter 3,5 s
   liess jeden Haenger wie eine Ablehnung aussehen, worauf der Loop ihn fuenfmal
   wiederholte. Der Boden sitzt im Helfer, nicht an den Aufrufstellen.
3. `opencode_stuck` trifft auch `--kind claude`. Der Name bleibt (er ist Vertrag),
   die Grenze steht jetzt im Docstring.
4. `dispatch()` dokumentiert seinen gewachsenen Worst Case, wie `start_orchestrator`
   es schon tat.
5. Tests fuer die beiden ungetesteten `initcmd`-Zweige; im README heisst
   `warmed: true` jetzt nur noch, dass der Lauf *stattfand*.

In `e2cdc86`, aus derselben Runde, nach einer Betreiber-Entscheidung:

6. **`agent_start` antwortet nur bei Exit-Code 0 mit einer Antwort, sonst `{}`,
   und `timeout_ms_for` haelt auch Herdrs *Untergrenze* ein.** `_run` faellt nur
   dann auf `{}` zurueck, solange stdout leer bleibt; was Herdr bei abgelaufenem
   eigenem `--timeout` schreibt, war nie gemessen, weil vor diesem Branch immer
   unser Subprozessbudget zuerst zuschlug. Ein Rumpf auf stdout hinter einem
   gescheiterten Start las sich als Erfolg — genau der Fehler, den der Plan
   beseitigen sollte, unter dem falschen der drei Namen. Und
   `AgentStartParams.timeout_ms` im mitgelieferten `herdr-api.schema.json` sagt
   „Values must be greater than 3000 and at most 300000": der Plan deckelte nur
   oben, ein `ready_timeout_s` von 2 oder 3 wurde damit zur sofortigen
   Ablehnung. Damit traegt der Code eine **fuenfte** Zahl mit Herkunftskommentar
   (`HERDR_MIN_TIMEOUT_MS = 3001`) — die Global Constraint oben nennt vier.
