@lean-md
consumer: ai
crp: compact

@var test_cmd default="uv run pytest -q" desc="project test runner command"
@var lint_cmd default="uv run ruff check ." desc="project lint gate"
@import .lean-ctx/lean-md/plan-recipes /

# lean-herdr — Rollen und Routing (Teilprojekt 1)

Quelle: `docs/specs/2026-09-14-lean-herdr-rollen-und-routing-design.md` (v1.0), Teil B.
Render je Task:
`lean-md render docs/lean-md/plans/2026-09-14-lean-herdr-rollen-und-routing.lmd.md --phase task-N`.

## Goal

Der Orchestrator verteilt Arbeit nach **Arbeitsart**, nicht nach Rolle:
`lean-herdr dispatch --work <art>`, und `[routing]` in `config.toml` bestimmt die Rolle
dahinter. `dispatch` prüft vor jedem Pane, ob die Rolle laufen kann. Rechte gelten je
Rolle statt geteilt, die Modell-Warnung vergleicht die Rolle hinter `review` mit jeder
Rolle, die sie prüft, und `workspace check` meldet, was `dispatch --work` verweigern würde.

- **Task 1** — opencode: orchestrator und reviewer verlieren die lean-ctx-Schreibwerkzeuge;
  die Schreibweise wird zuerst gegen opencode 1.18.29 gemessen (B4).
- **Task 2** — `[routing]`, `work_roles`, `role_for_work` (B2).
- **Task 3** — `missing_agent_config` mit Agentnamen, Rollenpfade und `role_problem` in
  `settings.py` (B3, Grundlage für B7).
- **Task 4** — `.lean-ctx/lean-herdr/claude/<rolle>.json` als Templates mit Lock (B4).
- **Task 5** — `dispatch`: Prompt-Pfad gegen die Wurzel, Vorab-Prüfung, `agent_args` mit
  Rolle und `--settings`, `role` in der Antwort (B3, B4).
- **Task 6** — `dispatch --work` (B3).
- **Task 7** — Modell-Warnung verallgemeinert, `shares_builder_model` →
  `shares_reviewed_model` (B6).
- **Task 8** — `workspace check`: Befunde je Arbeitsart (B7).
- **Task 9** — `orchestrator.md` ohne Rollennamen, README, `[routing]` im Config-Template (B5).

## Architecture

```
lean_herdr/
  settings.py    + ROUTING_BUILTIN, STAGES, WORK_RE, ROLE_RE, _check_routing,
                   work_roles, role_for_work; ROOT_KEYS + "routing"              (Task 2)
                 + ROLE_PROMPTS, CLAUDE_SETTINGS, OPENCODE_CONFIG, role_prompt_path,
                   claude_settings_path, missing_agent_config(root, kind, agent),
                   role_problem                                                  (Task 3)
                 ~ RoleSettings.shares_reviewed_model; model_warnings            (Task 7)
  workspace.py   − OPENCODE_CONFIG, missing_agent_config (→ settings.py)         (Task 3)
                 ~ ein Kommentar zu agent_args                                   (Task 5)
  checkcmd.py    ~ Import aus settings.py                                        (Task 3)
                 + WORKER_SENTENCES, _role_warnings; Rollen aus [routing] prüfen (Task 8)
  templating.py  ~ LAYOUT + claude/builder.json, claude/reviewer.json            (Task 4)
  dispatch.py    ~ agent_args(kind, model, role_file, role, *, root); main():
                   Prompt-Pfad, Vorab-Prüfung, "role"; --role-file optional      (Task 5)
                 + --work, role_or_work; Positional optional                    (Task 6)
                 ~ Warnung an der Rolle hinter review                            (Task 7)
  templates/
    opencode.jsonc          ~ orchestrator, reviewer ohne lean-ctx-Schreibwerkzeuge (Task 1)
    claude/builder.json     +                                                    (Task 4)
    claude/reviewer.json    +                                                    (Task 4)
    config.toml             ~ shares_reviewed_model (Task 7); [routing]-Kommentar (Task 9)
    roles/orchestrator.md   ~ --work, keine Rollennamen                          (Task 9)
opencode.jsonc, .lean-ctx/lean-herdr/{config.toml, claude/*.json, roles/orchestrator.md,
  templates.lock.json}      ~ nur über `uv run lean-herdr workspace init [--update]`
README.md        ~ Task 4 (zehn Dateien), 5 (claude-Rechte), 7 (Schlüssel), 9 (--work, [routing])
tests/
  doubles.py                        + write_role_fixture                         (Task 5)
  test_worker_permissions.py        + opencode-Sperre (1); claude-Rollendateien (4)
  test_settings.py                  + routing (2); Rollen-Prüfung (3); ~ model_warnings (7)
  test_dispatch.py                  + routing (2); Vorab-Prüfung, agent_args, Fixtures (5);
                                      --work (6); Warnung (7)
  test_dispatch_uncovered_paths.py  ~ Fixture, "role" in der Antwort             (Task 5)
  test_initcmd.py                   ~ shares_reviewed_model                      (Task 7)
  test_checkcmd.py                  + Befunde je Arbeitsart; ~ gesunder Fall     (Task 8)
  test_role_prohibitions.py         ~ Sätze aus orchestrator.md; Ersatztest      (Task 9)
```

Drei Festlegungen, die die Spec offen lässt:

- **`missing_agent_config` zieht nach `settings.py`.** `workspace.py` importiert `dispatch`
  (`UsageError`, `wait_for_agent_id`). Importierte `dispatch` umgekehrt `workspace`, schlösse
  sich der Kreis beim ersten Import. `settings.py` ist das Blatt-Modul, das `load_jsonc` und
  `ORCHESTRATOR_AGENT` aus demselben Grund schon trägt. `workspace.py` und `checkcmd.py`
  rufen die Funktion von dort mit `OPENCODE_ORCHESTRATOR` auf.
- **Eine Prüfung, zwei Leser.** `settings.role_problem(root, role, kind, prompt)` liefert den
  Text der drei Vorab-Befunde (B3). `dispatch.main()` antwortet damit `config_error:`,
  `checkcmd` macht daraus Warnungen (B7).
- **Wo geprüft und aufgelöst wird.** `dispatch.main()` prüft im Build-Zweig nach
  `missing_flags()` und vor `dispatch()`, also vor `ensure_worktree` und `pane split`;
  `dispatch()` selbst ändert nur den Aufruf von `agent_args`. `--work` wird direkt nach dem
  Lesen der Config aufgelöst und als `args.command` gesetzt: `settings_for`, `missing_flags`,
  `AwaitRequest`, `DispatchRequest` und die Warnung lesen danach denselben Rollennamen.
  Die Wahl „Rolle oder `--work`" (`role_or_work`) hängt an keiner Config und läuft vor
  `canonical_root()`.

## Global Constraints

- **Reihenfolge 1 → 9, nichts parallel.** Geteilte Dateien: `settings.py` (2, 3, 7),
  `dispatch.py` (5, 6, 7), `tests/test_settings.py` (2, 3, 7), `tests/test_dispatch.py`
  (2, 5, 6, 7), `tests/test_worker_permissions.py` (1, 4), Templates samt Lock (1, 4, 7, 9),
  `README.md` (4, 5, 7, 9). Task 5 braucht 3 und 4, Task 6 braucht 2 und 5, Task 7 braucht 6,
  Task 8 braucht 2 und 3, Task 9 braucht 6 und 7.
- **Task 1 misst, bevor ein Test festschreibt.** Läuft `opencode run` nicht, oder zeigt schon
  der Ausgangszustand keine lean-ctx-Schreibwerkzeuge, endet Task 1 mit BLOCKED. Keine
  Schreibweise wird geraten.
- **CLI-Vertrag:** jede `dispatch`-Antwort bleibt eine JSON-Zeile mit `ok`, Exit 0. Kein
  Vorab-Befund öffnet einen Worktree, ein Pane oder einen Agent.
- **Ohne `[routing]` wie heute:** `dispatch builder|reviewer|orchestrator` bleibt. Neu sind
  nur das optionale `--role-file` und `config_error:` für einen fehlenden Prompt, opencode-Block
  oder eine fehlende claude-Datei.
- **Unberührt:** `.claude/settings.json`, `roles/builder.md`, `roles/reviewer.md` — Template
  und Kopie. Vor jedem Commit endet
  `git diff --quiet HEAD -- .claude/settings.json lean_herdr/templates/settings.json lean_herdr/templates/roles/builder.md lean_herdr/templates/roles/reviewer.md .lean-ctx/lean-herdr/roles/builder.md .lean-ctx/lean-herdr/roles/reviewer.md`
  mit Exit 0. Kein `--setting-sources`; keine `deny`-Liste sperrt `Skill` oder `Skill(…)`.
- **Templates:** jede eingecheckte Kopie byte-gleich, Lock aktuell (`tests/test_templates.py`).
  Eine neue Template-Datei zieht `uv run lean-herdr workspace init` nach, eine geänderte
  `uv run lean-herdr workspace init --update`. Kopien und Lock nie von Hand.
- **Dateigröße:** keine Datei unter `lean_herdr/` über 800 Produktions-LOC. Gemessen am
  2026-09-14: `dispatch.py` 531, `checkcmd.py` 355, `settings.py` 270, `workspace.py` 258.
- **Non-Goals (B10):** kein `LEAN_CTX_PROFILE` je Rolle; kein Skill-Feld in `[roles.*]`;
  keine Skill-Anbindung der Prompts; keine zusammengesetzten Prompts; keine neuen Rollen
  (plan-writer, plan-reviewer, integrator); keine Änderung an Teardown, Merge oder Push;
  keine Längenprüfung für Agent-Namen; die `ctx_shell`-Lücke bleibt offen.

@phase "task-1"
## Task 1: opencode — lean-ctx-Schreibwerkzeuge für orchestrator und reviewer sperren

**Files:** Modify `lean_herdr/templates/opencode.jsonc`, `tests/test_worker_permissions.py`.
Neu erzeugt: `opencode.jsonc`, `.lean-ctx/lean-herdr/templates.lock.json`.

**Interfaces:** keine Python-Schnittstelle. **Produces:** in `opencode.jsonc` erreichen
`agent.orchestrator` und `agent.reviewer` die drei lean-ctx-Schreibwerkzeuge nicht mehr;
`agent.builder` bleibt ohne Sperre.

### Schritt 1 — Ausgangslage messen

Run: `opencode --version` — Expected: `1.18.29`. Eine andere Version im Bericht nennen und
weiter messen.

Run, in der Repo-Wurzel:

    LEAN_CTX_TOOL_PROFILE=power opencode run --agent reviewer "List every tool you can call whose name contains ctx_patch, ctx_edit or ctx_refactor. Call none of them. Answer with the exact tool names, one per line, or with NONE."

Expected: drei Namen, erwartet `lean-ctx_ctx_patch`, `lean-ctx_ctx_edit`,
`lean-ctx_ctx_refactor`. **Es gelten die ausgegebenen Namen**, nicht die erwarteten. Weichen
sie ab, stehen ab hier überall — Messung, Test, Template — die gemessenen.

Endet der Befehl mit einem Fehler (kein Modell, keine Zugangsdaten) oder antwortet er
`NONE` → **BLOCKED** mit der Ausgabe. Nichts ändern, nichts committen.

### Schritt 2 — Variante A: Permission-Schlüssel

Nur zum Messen, in `opencode.jsonc` an der Repo-Wurzel: im Block `agent.reviewer.permission`
direkt nach der Zeile `"write": "deny",` in der Einrückung der Nachbarzeilen einfügen:

    "lean-ctx_ctx_patch": "deny",
    "lean-ctx_ctx_edit": "deny",
    "lean-ctx_ctx_refactor": "deny",

Run: `opencode debug agent reviewer` — Expected: keine Fehlermeldung; unter `permission` je
Werkzeug ein Eintrag der Form `{"permission": "lean-ctx_ctx_patch", "action": "deny", "pattern": "*"}`.

Run: der `opencode run`-Befehl aus Schritt 1 — Expected: `NONE`.

Beides erfüllt → **Variante A gilt**, weiter mit Schritt 4.

### Schritt 3 — Variante B: `tools`-Schalter (nur wenn Schritt 2 nicht `NONE` ergab)

Die drei Zeilen aus Schritt 2 wieder entfernen. Stattdessen im Block `agent.reviewer` direkt
nach der Zeile `"steps": 40,` einfügen:

    "tools": {
      "lean-ctx_ctx_patch": false,
      "lean-ctx_ctx_edit": false,
      "lean-ctx_ctx_refactor": false
    },

Run: der `opencode run`-Befehl aus Schritt 1 — Expected: `NONE` → **Variante B gilt**.
Sonst **BLOCKED** mit den Ausgaben aus Schritt 2 und 3.

### Schritt 4 — Messdatei zurücksetzen, Ergebnis sichern

Run: `git checkout -- opencode.jsonc`

Run: `git status --short opencode.jsonc` — Expected: keine Ausgabe.

Variante A gemessen →
@call remember_decision("opencode 1.18.29 removes an MCP tool from an agent through a permission key named after the tool, e.g. lean-ctx_ctx_patch = deny under agent.<name>.permission -- measured by opencode run listing the callable tools (plan 2026-09-14 rollen-und-routing, task 1)")

Variante B gemessen →
@call remember_decision("opencode 1.18.29 ignores a permission key for an MCP tool; the agent-level tools map with lean-ctx_ctx_patch = false removes it -- measured by opencode run listing the callable tools (plan 2026-09-14 rollen-und-routing, task 1)")

### Schritt 5 — Test zuerst

`tests/test_worker_permissions.py`, direkt nach `WORKERS = ("builder", "reviewer")`:

    #: lean-ctx's own write tools, under the names opencode gives an MCP tool --
    #: measured against opencode 1.18.29 (plan 2026-09-14, task 1). `edit` and
    #: `write` deny opencode's built-in tools only; these three pass both.
    LEAN_CTX_WRITERS = ("lean-ctx_ctx_patch", "lean-ctx_ctx_edit", "lean-ctx_ctx_refactor")

    #: The opencode agents that change no file.
    NON_WRITING = ("orchestrator", "reviewer")

Am Dateiende. **Variante A:**

    @pytest.mark.parametrize("role", NON_WRITING)
    def test_a_role_that_writes_nothing_cannot_reach_lean_ctxs_write_tools(role, gate_root):
        """`edit: deny` stops opencode's own editor, not an MCP tool with a name of its own."""
        permission = opencode(gate_root)["agent"][role]["permission"]
        for tool in LEAN_CTX_WRITERS:
            assert permission.get(tool) == "deny", f"{role} may still call {tool}"

**Variante B** — derselbe Test, Rumpf ab der ersten Code-Zeile:

        tools = opencode(gate_root)["agent"][role].get("tools", {})
        for tool in LEAN_CTX_WRITERS:
            assert tools.get(tool) is False, f"{role} may still call {tool}"

Für beide Varianten:

    def test_the_builder_keeps_lean_ctxs_write_tools(gate_root):
        """The block is for the roles that write nothing -- the builder writes."""
        agent = opencode(gate_root)["agent"]["builder"]
        named = set(agent["permission"]) | set(agent.get("tools", {}))
        assert not named & set(LEAN_CTX_WRITERS), sorted(named & set(LEAN_CTX_WRITERS))

Run: `uv run pytest -q tests/test_worker_permissions.py -k lean_ctxs` — Expected: FAIL für
`orchestrator` und `reviewer`, je `repo` und `foreign`; PASS für den Builder.

### Schritt 6 — Template

@call patch("lean_herdr/templates/opencode.jsonc", "the permission blocks of agent.orchestrator and agent.reviewer")

**Variante A:** in `agent.orchestrator.permission` und in `agent.reviewer.permission` je
direkt nach `"write": "deny",`, in deren Einrückung:

    // lean-ctx writes through MCP tools of its own, and `edit`/`write` do
    // not reach them: opencode gates an MCP tool by its own name (measured
    // against opencode 1.18.29). `ctx_shell` stays open -- a reading role
    // needs it, and lean-ctx's shell allowlist is not per role.
    "lean-ctx_ctx_patch": "deny",
    "lean-ctx_ctx_edit": "deny",
    "lean-ctx_ctx_refactor": "deny",

**Variante B:** in `agent.orchestrator` direkt nach `"steps": 60,` und in `agent.reviewer`
direkt nach `"steps": 40,`, in deren Einrückung:

    // lean-ctx writes through MCP tools of its own, and `edit`/`write` do
    // not reach them; opencode 1.18.29 ignores a permission key for an MCP
    // tool, the tools map removes it (measured). `ctx_shell` stays open --
    // a reading role needs it, and lean-ctx's shell allowlist is not per role.
    "tools": {
      "lean-ctx_ctx_patch": false,
      "lean-ctx_ctx_edit": false,
      "lean-ctx_ctx_refactor": false
    },

Run: `uv run lean-herdr workspace init --update` — Expected: eine JSON-Zeile mit
`"ok": true` und `"written": ["opencode.jsonc"]`.

Run: `uv run pytest -q tests/test_worker_permissions.py tests/test_templates.py` — Expected: PASS.

### Verify & Close

@call verify(lean_herdr/templates/opencode.jsonc opencode.jsonc tests/test_worker_permissions.py)
@call gate(tests/test_worker_permissions.py)
@call commit("lean_herdr/templates/opencode.jsonc opencode.jsonc .lean-ctx/lean-herdr/templates.lock.json tests/test_worker_permissions.py", "feat(opencode): deny lean-ctx's write tools to the roles that write nothing")
@phase-end

@phase "task-2"
## Task 2: `[routing]` — Arbeitsarten auf Rollen

**Files:** Modify `lean_herdr/settings.py`, `tests/test_settings.py`, `tests/test_dispatch.py`.

**Interfaces — Produces** (`lean_herdr/settings.py`):

    ROOT_KEYS = ("default", "roles", "llm", "workspace", "models", "routing")
    ROUTING_BUILTIN = {"implement": "builder", "review": "reviewer"}
    STAGES = ("plan", "plan-review", "review", "integrate")
    WORK_RE = re.compile(r"[a-z][a-z0-9-]*")    # used with fullmatch
    ROLE_RE = re.compile(r"[a-z][a-z0-9_-]*")   # used with fullmatch
    def work_roles(data: dict[str, Any] | None = None) -> dict[str, str]
    def role_for_work(work: str, data: dict[str, Any] | None = None) -> str   # SettingsError

Fehlertexte, wörtlich: `no role for work 'plan'` · `routing: section is not a table, but str` ·
`routing: work 'Rename' does not match [a-z][a-z0-9-]*` ·
`routing.rename: 'Refactorer' is no role name ([a-z][a-z0-9_-]*)`.

Bestehend:
@read lean_herdr/settings.py mode=signatures

### Schritt 1 — Tests zuerst

`tests/test_settings.py`: `ROOT_KEYS`, `role_for_work` und `work_roles` in den bestehenden
Import `from lean_herdr.settings import (...)` aufnehmen. Am Dateiende:

    # -- routing: [routing] -------------------------------------------------


    def test_routing_is_a_known_root_key():
        assert "routing" in ROOT_KEYS
        assert settings_for("builder", {"routing": {"rename": "refactorer"}}).profile == "standard"


    def test_routing_without_a_table_keeps_the_built_in_works():
        """Without `[routing]` the project dispatches exactly as it did by role name."""
        assert role_for_work("implement", {}) == "builder"
        assert role_for_work("review", None) == "reviewer"


    def test_routing_overrides_a_built_in_work_and_adds_its_own():
        data = {"routing": {"implement": "coder", "rename": "refactorer"}}
        assert role_for_work("implement", data) == "coder"
        assert role_for_work("rename", data) == "refactorer"
        assert role_for_work("review", data) == "reviewer"


    def test_routing_lists_the_built_in_works_under_the_table():
        assert work_roles({"routing": {"rename": "refactorer"}}) == {
            "implement": "builder",
            "review": "reviewer",
            "rename": "refactorer",
        }


    @pytest.mark.parametrize("work", ["plan", "plan-review", "integrate", "deploy"])
    def test_routing_knows_no_role_for_a_work_nobody_named(work):
        """The stages get their built-in roles with TP2 and TP3 -- until then, no guess."""
        with pytest.raises(SettingsError) as caught:
            role_for_work(work, {})
        assert str(caught.value) == f"no role for work {work!r}"


    @pytest.mark.parametrize(
        "routing",
        [
            pytest.param({"Rename": "refactorer"}, id="work with a capital"),
            pytest.param({"re_name": "refactorer"}, id="work with an underscore"),
            pytest.param({"1st": "refactorer"}, id="work starting with a digit"),
            pytest.param({"rename": "Refactorer"}, id="role with a capital"),
            pytest.param({"rename": "re factorer"}, id="role with a space"),
            pytest.param({"rename": ""}, id="empty role"),
            pytest.param({"rename": 5}, id="role not a string"),
        ],
    )
    def test_routing_with_a_malformed_line_fails_every_reader(routing):
        """Checked in `_check_root`: a call by role name meets the broken line too."""
        with pytest.raises(SettingsError, match="routing"):
            settings_for("builder", {"routing": routing})


    def test_routing_that_is_no_table_is_a_settings_error():
        with pytest.raises(SettingsError, match="routing: section is not a table"):
            settings_for("builder", {"routing": "builder"})

`tests/test_dispatch.py`, direkt nach `test_a_broken_llm_block_is_a_config_error_too`:

    def test_a_broken_routing_line_fails_a_call_by_role_name_too(monkeypatch, tmp_path, capsys):
        """`[routing]` is checked on load, so the builder call meets the broken line."""
        root = tmp_path / "repo"
        _write_config(root, '[routing]\nrename = "Refactorer"\n')
        monkeypatch.setattr("lean_herdr.dispatch.canonical_root", lambda *a, **kw: root)
        _no_launch(monkeypatch)

        assert main(["builder", "--kind", "claude", "--model", "sonnet"]) == 0

        result = json.loads(capsys.readouterr().out.strip())
        assert result["ok"] is False
        assert result["error"].startswith("config_error: routing.rename: "), result["error"]

Run: `uv run pytest -q tests/test_settings.py tests/test_dispatch.py -k routing`
— Expected: der Lauf bricht beim Sammeln ab (`ImportError: cannot import name …` in `tests/test_settings.py`);
danach `uv run pytest -q tests/test_dispatch.py -k routing` einzeln — Expected: FAIL mit
`config_error: settings: unknown top-level keys ['routing']`.

### Schritt 2 — Implementierung

@call patch("lean_herdr/settings.py", "ROOT_KEYS, the line after KINDS, _check_root, the line after settings_for")

1. `ROOT_KEYS` und sein Kommentar („The only five keys …" → „The only six keys the top level
   of the file may carry."):

       ROOT_KEYS = ("default", "roles", "llm", "workspace", "models", "routing")

2. Neu, direkt nach `KINDS = ("claude", "opencode")` und dessen Leerzeile:

       #: The two works TP1 builds in. `[routing]` lays itself over them, so a project
       #: without the table dispatches exactly as it did by role name.
       ROUTING_BUILTIN = {"implement": "builder", "review": "reviewer"}

       #: Works that are stages of a run, not work a plan hands out. `plan`,
       #: `plan-review` and `integrate` get their built-in roles with TP2 and TP3;
       #: until then a call without a `[routing]` line for one is a SettingsError.
       #: `model_warnings` pairs the role behind `review` with the role behind every
       #: work that is NOT one of these.
       STAGES = ("plan", "plan-review", "review", "integrate")

       #: A work name, and a role name. The role becomes part of the herdr agent
       #: name, so it is held to what that name may carry; its length is TP3's.
       WORK_RE = re.compile(r"[a-z][a-z0-9-]*")
       ROLE_RE = re.compile(r"[a-z][a-z0-9_-]*")

3. Neu, direkt vor `def _check_root`:

       def _check_routing(routing: Any) -> None:
           """`[routing]`: work name -> role name, each spelled the way its pattern allows.

           Called from `_check_root`, so EVERY reader of the file meets a broken line --
           a call by role name as much as `--work`.
           """
           if not isinstance(routing, dict):
               raise SettingsError(f"routing: section is not a table, but {type(routing).__name__}")
           for work, role in routing.items():
               if not WORK_RE.fullmatch(work):
                   raise SettingsError(f"routing: work {work!r} does not match {WORK_RE.pattern}")
               if not isinstance(role, str) or not ROLE_RE.fullmatch(role):
                   raise SettingsError(f"routing.{work}: {role!r} is no role name ({ROLE_RE.pattern})")

4. In `_check_root`, nach der Prüfung von `roles` und vor `return table`:

           routing = table.get("routing")
           if routing is not None:
               _check_routing(routing)

   Im Docstring von `_check_root` die erste Zeile ersetzen durch:
   `"""Top level: everything in `ROOT_KEYS`, `roles` a table, `routing` checked line by line.`

5. Neu, direkt nach `settings_for`:

       def work_roles(data: dict[str, Any] | None = None) -> dict[str, str]:
           """Every work that has a role: the built-in ones, `[routing]` laid over them."""
           table = _check_root({} if data is None else data)
           return {**ROUTING_BUILTIN, **(table.get("routing") or {})}


       def role_for_work(work: str, data: dict[str, Any] | None = None) -> str:
           """`[routing]` > built-in > SettingsError -- one resolution for dispatch and check."""
           role = work_roles(data).get(work)
           if role is None:
               raise SettingsError(f"no role for work {work!r}")
           return role

Run: `uv run pytest -q tests/test_settings.py tests/test_dispatch.py -k routing` — Expected: PASS.

### Verify & Close

@call verify(lean_herdr/settings.py tests/test_settings.py tests/test_dispatch.py)
@call gate(lean_herdr/settings.py tests/test_settings.py tests/test_dispatch.py)
@call commit("lean_herdr/settings.py tests/test_settings.py tests/test_dispatch.py", "feat(settings): route kinds of work to roles through [routing]")
@call remember_decision("lean-herdr [routing]: settings.role_for_work(work, data) is the one resolution -- [routing] over ROUTING_BUILTIN (implement=builder, review=reviewer), else SettingsError no role for work; STAGES = plan, plan-review, review, integrate; _check_root validates every routing line for every reader")
@phase-end

@phase "task-3"
## Task 3: eine opencode-Prüfung und eine Rollen-Prüfung für jede Rolle

**Files:** Modify `lean_herdr/settings.py`, `lean_herdr/workspace.py`, `lean_herdr/checkcmd.py`,
`tests/test_settings.py`.

**Interfaces — Produces** (`lean_herdr/settings.py`):

    ROLE_PROMPTS = Path(".lean-ctx") / "lean-herdr" / "roles"
    CLAUDE_SETTINGS = Path(".lean-ctx") / "lean-herdr" / "claude"
    OPENCODE_CONFIG = "opencode.jsonc"
    def role_prompt_path(root: Path, role: str) -> Path
    def claude_settings_path(root: Path, role: str) -> Path
    def missing_agent_config(root: Path, kind: str, agent: str) -> str | None
    def role_problem(root: Path, role: str, kind: str, prompt: Path) -> str | None

`role_problem` prüft in dieser Reihenfolge, Texte wörtlich: `no role prompt at <prompt>` →
Text aus `missing_agent_config` (`no opencode.jsonc in <root>` ·
`opencode.jsonc in <root> is <error>` · `opencode.jsonc in <root> defines no agent.<agent>`)
→ `no claude settings at <root>/.lean-ctx/lean-herdr/claude/<role>.json`.

**Removes** aus `lean_herdr/workspace.py`: `OPENCODE_CONFIG`, `missing_agent_config`.
`OPENCODE_ORCHESTRATOR` und `INIT_HINT` bleiben dort.

Bestehend:
@symbol body name=missing_agent_config

### Schritt 1 — Tests zuerst

`tests/test_settings.py`: `KINDS`, `claude_settings_path`, `missing_agent_config`,
`role_problem` und `role_prompt_path` in den Import aus `lean_herdr.settings` aufnehmen.
Am Dateiende:

    # -- role files ----------------------------------------------------------


    def test_the_opencode_guard_asks_for_the_agent_it_is_given(tmp_path):
        """One guard for every role now, not only the orchestrator."""
        (tmp_path / "opencode.jsonc").write_text('{"agent": {"refactorer": {}}}\n', encoding="utf-8")
        assert missing_agent_config(tmp_path, "opencode", "refactorer") is None
        assert missing_agent_config(tmp_path, "opencode", "orchestrator") == (
            f"opencode.jsonc in {tmp_path} defines no agent.orchestrator"
        )
        assert missing_agent_config(tmp_path, "claude", "orchestrator") is None


    def test_a_role_problem_is_named_in_the_order_dispatch_checks(tmp_path):
        """Prompt first, then the artefact of the runtime -- each in its own words."""
        prompt = role_prompt_path(tmp_path, "refactorer")
        claude = claude_settings_path(tmp_path, "refactorer")
        assert prompt == tmp_path / ".lean-ctx" / "lean-herdr" / "roles" / "refactorer.md"
        assert claude == tmp_path / ".lean-ctx" / "lean-herdr" / "claude" / "refactorer.json"
        for kind in KINDS:
            assert role_problem(tmp_path, "refactorer", kind, prompt) == f"no role prompt at {prompt}"

        prompt.parent.mkdir(parents=True)
        prompt.write_text("# Role: refactorer\n", encoding="utf-8")
        assert role_problem(tmp_path, "refactorer", "claude", prompt) == (
            f"no claude settings at {claude}"
        )
        assert role_problem(tmp_path, "refactorer", "opencode", prompt) == (
            f"no opencode.jsonc in {tmp_path}"
        )

        claude.parent.mkdir(parents=True)
        claude.write_text("{}\n", encoding="utf-8")
        (tmp_path / "opencode.jsonc").write_text('{"agent": {"refactorer": {}}}\n', encoding="utf-8")
        for kind in KINDS:
            assert role_problem(tmp_path, "refactorer", kind, prompt) is None

Run: `uv run pytest -q tests/test_settings.py -k "opencode_guard or role_problem"`
— Expected: ERROR, `ImportError: cannot import name …` für eine der neuen Funktionen.

### Schritt 2 — `settings.py`

@call patch("lean_herdr/settings.py", "the line after the OVERLAY_PATH constant, and the end of the file")

1. Neu, direkt nach `OVERLAY_PATH = …` und dessen Leerzeile:

       #: RELATIVE to the repo root, like SETTINGS_PATH. `dispatch` joins them onto
       #: canonical_root() before it checks a file or hands one to a pane: a relative
       #: path would resolve in the pane's cwd -- the worktree, which need not carry it.
       ROLE_PROMPTS = Path(".lean-ctx") / "lean-herdr" / "roles"
       CLAUDE_SETTINGS = Path(".lean-ctx") / "lean-herdr" / "claude"

2. Neu, am Dateiende nach `load_jsonc`:

       # -- role files --------------------------------------------------------

       #: opencode reads its project configuration from this file, at the repo
       #: root. Not configurable: opencode looks for exactly this name.
       OPENCODE_CONFIG = "opencode.jsonc"


       def role_prompt_path(root: Path, role: str) -> Path:
           """The prompt a role brings along when `--role-file` names none."""
           return root / ROLE_PROMPTS / f"{role}.md"


       def claude_settings_path(root: Path, role: str) -> Path:
           """The file a claude worker of this role gets as `--settings`."""
           return root / CLAUDE_SETTINGS / f"{role}.json"


       def missing_agent_config(root: Path, kind: str, agent: str) -> str | None:
           """Why opencode could not resolve `--agent <agent>` here. None: it can.

           Measured 2026-09-04. The agent is a NAME, and opencode resolves it out of
           the project's own `opencode.jsonc`. Where that file or its block is missing,
           opencode starts, prints "Agent not found", never becomes an agent and never
           registers its MCP server -- and the caller sat out the full `ready_timeout_s`
           for an agent id that could not arrive, then answered the misleading
           `no_agent_id`. Look first instead.

           Only opencode resolves a project-level agent name, so only opencode is
           checked; a claude worker's role travels as files (dispatch.agent_args).

           Three answers, because they are three repairs: absent (init has not run),
           present but unparseable (an editor), parsed without this agent (a config
           written for other roles).

           It lives here and not in workspace.py, where it started: `workspace`
           imports `dispatch`, and `dispatch` needs this guard for every role.
           """
           if kind != "opencode":
               return None
           config = load_jsonc(root / OPENCODE_CONFIG)
           if not config.found:
               return f"no {OPENCODE_CONFIG} in {root}"
           if config.error:
               return f"{OPENCODE_CONFIG} in {root} is {config.error}"
           agents = config.data.get("agent")
           if not isinstance(agents, dict) or not isinstance(agents.get(agent), dict):
               return f"{OPENCODE_CONFIG} in {root} defines no agent.{agent}"
           return None


       def role_problem(root: Path, role: str, kind: str, prompt: Path) -> str | None:
           """Why a worker of this role could not run here. None: nothing found.

           The three checks `dispatch` makes before it splits a pane, in this order and
           each in its own words: the prompt, then the artefact of the runtime --
           opencode's agent block or claude's settings file. `workspace check` reads
           the same answer as a warning; one producer for both (M3).
           """
           if not prompt.is_file():
               return f"no role prompt at {prompt}"
           problem = missing_agent_config(root, kind, role)
           if problem:
               return problem
           claude = claude_settings_path(root, role)
           if kind == "claude" and not claude.is_file():
               return f"no claude settings at {claude}"
           return None

### Schritt 3 — `workspace.py` und `checkcmd.py`

@call patch("lean_herdr/workspace.py", "the settings import, OPENCODE_CONFIG, the comments naming it, missing_agent_config, its call in start_orchestrator")

- `OPENCODE_CONFIG = "opencode.jsonc"` samt seinem zweizeiligen Kommentar löschen, ebenso die
  ganze Funktion `missing_agent_config`.
- `missing_agent_config` in den Import `from lean_herdr.settings import (...)` aufnehmen und `load_jsonc` daraus streichen — sonst meldet ruff F401.
- Kommentar über `OPENCODE_ORCHESTRATOR`: „find under `agent` in OPENCODE_CONFIG" →
  „find under `agent` in `opencode.jsonc`". Kommentar über `INIT_HINT`: „`init` is what
  writes OPENCODE_CONFIG" → „`init` is what writes `opencode.jsonc`".
- In `start_orchestrator`: `problem = missing_agent_config(root, kind, OPENCODE_ORCHESTRATOR)`.

@call patch("lean_herdr/checkcmd.py", "the two imports and the missing_agent_config call in _config_errors")

- `from lean_herdr.workspace import INIT_HINT, missing_agent_config` →
  `from lean_herdr.workspace import INIT_HINT, OPENCODE_ORCHESTRATOR`;
  `missing_agent_config` in den Import aus `lean_herdr.settings` aufnehmen.
- In `_config_errors` die Zeile `problem = missing_agent_config(root, settings_for("orchestrator", data).kind)` ersetzen durch:

      orchestrator = settings_for("orchestrator", data).kind
      problem = missing_agent_config(root, orchestrator, OPENCODE_ORCHESTRATOR)

Run: `uv run pytest -q tests/test_settings.py tests/test_workspace.py tests/test_checkcmd.py tests/test_handlers.py tests/test_initcmd.py`
— Expected: PASS.

### Verify & Close

@call verify(lean_herdr/settings.py lean_herdr/workspace.py lean_herdr/checkcmd.py tests/test_settings.py)
@call review_change()
@call gate(lean_herdr/settings.py lean_herdr/workspace.py lean_herdr/checkcmd.py tests/test_settings.py)
@call commit("lean_herdr/settings.py lean_herdr/workspace.py lean_herdr/checkcmd.py tests/test_settings.py", "refactor(settings): one opencode guard and one role check for every role")
@call remember_decision("lean-herdr: missing_agent_config(root, kind, agent) lives in settings.py since plan 2026-09-14 task 3 -- workspace imports dispatch, so dispatch cannot import workspace; settings.role_problem(root, role, kind, prompt) is the one producer for the dispatch pre-check and workspace check")
@phase-end

@phase "task-4"
## Task 4: claude-Rechte je Rolle als Templates

**Files:** Create `lean_herdr/templates/claude/builder.json`,
`lean_herdr/templates/claude/reviewer.json`. Modify `lean_herdr/templating.py`,
`tests/test_worker_permissions.py`, `README.md`. Neu erzeugt:
`.lean-ctx/lean-herdr/claude/builder.json`, `.lean-ctx/lean-herdr/claude/reviewer.json`,
`.lean-ctx/lean-herdr/templates.lock.json`.

**Interfaces — Produces:**
`LAYOUT["claude/builder.json"] == ".lean-ctx/lean-herdr/claude/builder.json"`,
`LAYOUT["claude/reviewer.json"] == ".lean-ctx/lean-herdr/claude/reviewer.json"` — derselbe Pfad
wie `settings.claude_settings_path(root, role)` aus Task 3.

### Schritt 1 — Tests zuerst

@call patch("tests/test_worker_permissions.py", "the templating import, foreign_root, test_no_worker_gate_ever_names_the_dispatch_verb, the end of the file")

- Import: `from lean_herdr.templating import LAYOUT, read_lock, render, resolve_values`.
- In `foreign_root` die Schleife über
  `("opencode.jsonc", "settings.json", "claude/builder.json", "claude/reviewer.json")` laufen lassen.
- Ans Ende von `test_no_worker_gate_ever_names_the_dispatch_verb`:

      for role in CLAUDE_ROLES:
          offenders = [rule for rule in claude_rules(role, "allow", gate_root) if "dispatch" in rule]
          assert not offenders, f"claude/{role}.json: {offenders}"

- Direkt nach `NON_WRITING` (aus Task 1):

      #: The claude roles that ship a settings file `dispatch` hands over as `--settings`.
      CLAUDE_ROLES = ("builder", "reviewer")

      #: The claude roles that change no file. Their `deny` outranks every `allow` from
      #: every source, the shared `.claude/settings.json` included.
      CLAUDE_NON_WRITING = ("reviewer",)

      #: What writes, whatever `.claude/settings.json` says: Claude Code's own editors
      #: and lean-ctx's three write tools.
      CLAUDE_WRITERS = (
          "Edit",
          "Write",
          "NotebookEdit",
          "mcp__lean-ctx__ctx_patch",
          "mcp__lean-ctx__ctx_edit",
          "mcp__lean-ctx__ctx_refactor",
      )


      def claude_rules(role: str, key: str, root: Path = ROOT) -> list[str]:
          """`permissions.<key>` of `.lean-ctx/lean-herdr/claude/<role>.json`; absent is empty."""
          data = json.loads((root / LAYOUT[f"claude/{role}.json"]).read_text(encoding="utf-8"))
          return data.get("permissions", {}).get(key, [])

- Am Dateiende:

      def test_every_worker_ships_a_claude_role_file():
          for role in WORKERS:
              assert f"claude/{role}.json" in LAYOUT, f"{role} has no claude settings template"


      @pytest.mark.parametrize("role", CLAUDE_NON_WRITING)
      def test_a_claude_role_that_writes_nothing_is_denied_every_writing_grant(role):
          """The shared allowlist hands every claude worker `git add` and `wt step commit`.

          Everything in it but the report path, the gate's own two commands and skills
          has to be taken back here, together with the editors and lean-ctx's tools.
          """
          values = resolve_values(read_lock(ROOT)["values"])
          kept = {f"Bash({values['test']}:*)", f"Bash({values['lint']}:*)"}
          shared = [
              rule
              for rule in claude_allow()
              if not rule.startswith("Bash(lean-herdr report")
              and rule not in kept
              and not rule.startswith("Skill")
          ]
          deny = claude_rules(role, "deny")
          for rule in (*CLAUDE_WRITERS, *shared):
              assert rule in deny, f"claude/{role}.json does not deny {rule}"


      @pytest.mark.parametrize("role", CLAUDE_ROLES)
      def test_no_claude_role_takes_the_skill_tool_away(role):
          """Skills stay loadable for every claude role; which one a role loads is TP2's."""
          denied = claude_rules(role, "deny")
          offenders = [rule for rule in denied if rule == "Skill" or rule.startswith("Skill(")]
          assert not offenders, f"claude/{role}.json denies {offenders}"

Run: `uv run pytest -q tests/test_worker_permissions.py` — Expected: FAIL/ERROR mit
`KeyError: 'claude/builder.json'`.

### Schritt 2 — Templates und `LAYOUT`

Create `lean_herdr/templates/claude/builder.json` (eine Zeile, mit Zeilenende):

    {}

Create `lean_herdr/templates/claude/reviewer.json` (mit Zeilenende):

    {
      "permissions": {
        "deny": [
          "Edit",
          "Write",
          "NotebookEdit",
          "Bash(git add:*)",
          "Bash(git commit:*)",
          "Bash(wt step commit:*)",
          "mcp__lean-ctx__ctx_patch",
          "mcp__lean-ctx__ctx_edit",
          "mcp__lean-ctx__ctx_refactor"
        ]
      }
    }

@call patch("lean_herdr/templating.py", "LAYOUT and the comment above it")

- In `LAYOUT` direkt nach dem Eintrag `"roles/reviewer.md": …`:

      "claude/builder.json": ".lean-ctx/lean-herdr/claude/builder.json",
      "claude/reviewer.json": ".lean-ctx/lean-herdr/claude/reviewer.json",

- Kommentar: „Only the first four are movable." → „Only the first six are movable."

Run: `uv run lean-herdr workspace init` — Expected: eine JSON-Zeile mit `"ok": true` und
`"written": [".lean-ctx/lean-herdr/claude/builder.json", ".lean-ctx/lean-herdr/claude/reviewer.json"]`.

Run: `git check-ignore .lean-ctx/lean-herdr/claude/reviewer.json` — Expected: keine Ausgabe,
Exit 1 (die Datei wird versioniert).

Run: `uv run pytest -q tests/test_worker_permissions.py tests/test_templates.py tests/test_templating.py tests/test_initcmd.py tests/test_checkcmd.py tests/test_manifest.py`
— Expected: PASS.

### Schritt 3 — README

@call patch("README.md", "the section Setting up a project")

- „It writes eight files -- the config and the three role prompts under" →
  „It writes ten files -- the config, the three role prompts and two claude role settings under"
- „Three of the eight carry this project's own commands" → „Three of the ten carry this project's own commands"
- „and one of the eight files is such a plugin" → „and one of the ten files is such a plugin"

### Verify & Close

@call verify(lean_herdr/templating.py lean_herdr/templates/claude/builder.json lean_herdr/templates/claude/reviewer.json tests/test_worker_permissions.py README.md)
@call review_change()
@call gate(lean_herdr/templating.py tests/test_worker_permissions.py)
@call commit("lean_herdr/templating.py lean_herdr/templates/claude/builder.json lean_herdr/templates/claude/reviewer.json .lean-ctx/lean-herdr/claude/builder.json .lean-ctx/lean-herdr/claude/reviewer.json .lean-ctx/lean-herdr/templates.lock.json tests/test_worker_permissions.py README.md", "feat(templates): ship a claude settings file per worker role")
@phase-end

@phase "task-5"
## Task 5: `dispatch` prüft die Rolle vor dem Pane und benennt Agents nach der Rolle

**Files:** Modify `lean_herdr/dispatch.py`, `lean_herdr/workspace.py` (ein Kommentar),
`tests/doubles.py`, `tests/test_dispatch.py`, `tests/test_dispatch_uncovered_paths.py`, `README.md`.

**Interfaces — Consumes:** `role_prompt_path`, `claude_settings_path`, `role_problem` (Task 3);
`LAYOUT["claude/…"]` (Task 4). **Produces:**

    # lean_herdr/dispatch.py
    def agent_args(kind: str, model: str, role_file: Path, role: str, *, root: Path) -> list[str]
    #   claude:   ["--model", m, "--append-system-prompt-file", str(role_file),
    #              "--settings", str(root / ".lean-ctx/lean-herdr/claude/<role>.json")]
    #   opencode: ["--model", m, "--agent", role]
    # tests/doubles.py
    def write_role_fixture(root: Path, *roles: str) -> None

Build-Modus: `--role-file` optional, Standard `role_prompt_path(root, rolle)`; ein angegebener
Pfad wird gegen `canonical_root()` aufgelöst. Ein Vorab-Befund antwortet
`{"ok": false, "error": "config_error: <role_problem>"}` und ruft `dispatch()` nicht. Die
Antwort von `dispatch()` bekommt `"role": <rolle>`.

Bestehend:
@read lean_herdr/dispatch.py mode=signatures

### Schritt 1 — Test-Hilfe

@call patch("tests/doubles.py", "the imports and the line after write_opencode_config")

Import ergänzen: `from lean_herdr.settings import claude_settings_path, role_prompt_path`.
Neu, direkt nach `write_opencode_config`:

    def write_role_fixture(root: Path, *roles: str) -> None:
        """Everything `dispatch` checks before it splits a pane, for these roles and both kinds.

        The prompt under `.lean-ctx/lean-herdr/roles/`, an empty claude settings file, and
        `opencode.jsonc` from the shipped template -- which names the orchestrator, the
        builder and the reviewer, and no other role.
        """
        for role in roles:
            prompt = role_prompt_path(root, role)
            prompt.parent.mkdir(parents=True, exist_ok=True)
            prompt.write_text(f"# Role: {role}\n", encoding="utf-8")
            claude = claude_settings_path(root, role)
            claude.parent.mkdir(parents=True, exist_ok=True)
            claude.write_text("{}\n", encoding="utf-8")
        write_opencode_config(root)

### Schritt 2 — Tests zuerst

@call patch("tests/test_dispatch.py", "the imports, test_the_role_prompt_travels_as_a_file_never_as_text, the line after test_the_config_fills_a_missing_kind_flag")

Imports: `claude_settings_path` und `role_prompt_path` in den Import aus `lean_herdr.settings`,
`write_role_fixture` in den Import aus `tests.doubles`.

`test_the_role_prompt_travels_as_a_file_never_as_text` ganz ersetzen, und direkt danach neu:

    def test_the_role_prompt_travels_as_a_file_never_as_text():
        prompt = ROOT / ".lean-ctx" / "lean-herdr" / "roles" / "builder.md"
        args = agent_args("claude", "sonnet", prompt, "builder", root=ROOT)
        assert args == [
            "--model",
            "sonnet",
            "--append-system-prompt-file",
            "/repo/.lean-ctx/lean-herdr/roles/builder.md",
            "--settings",
            "/repo/.lean-ctx/lean-herdr/claude/builder.json",
        ]
        assert not any("\n" in a for a in args), "Herdr rejects multi-line arguments (H2)"


    def test_opencode_is_told_the_role_not_the_prompt_files_stem():
        """An `--role-file` override changes the prompt, never the agent opencode resolves."""
        args = agent_args("opencode", "m", Path("/elsewhere/strict.md"), "reviewer", root=ROOT)
        assert args == ["--model", "m", "--agent", "reviewer"]

Neu, direkt nach `test_the_config_fills_a_missing_kind_flag`:

    @pytest.mark.parametrize(
        ("kind", "drop", "expected"),
        [
            pytest.param("claude", "prompt", "config_error: no role prompt at ", id="prompt"),
            pytest.param("opencode", "block", "config_error: opencode.jsonc in ", id="block"),
            pytest.param("claude", "claude file", "config_error: no claude settings at ", id="claude"),
        ],
    )
    def test_a_role_that_cannot_run_is_refused_before_any_pane(
        monkeypatch, tmp_path, capsys, kind, drop, expected
    ):
        """All three are checked before `pane split`, and none of them starts anything.

        Herdr is a recording fake, not a stop sign: without the check dispatch() would
        run on, and its calls would show up in `proc.calls`.
        """
        root = tmp_path / "repo"
        _write_config(root, "")
        write_role_fixture(root, "builder")
        if drop == "prompt":
            role_prompt_path(root, "builder").unlink()
        elif drop == "claude file":
            claude_settings_path(root, "builder").unlink()
        else:
            (root / "opencode.jsonc").write_text('{"agent": {"reviewer": {}}}\n', encoding="utf-8")
        monkeypatch.setattr("lean_herdr.herdr.shutil.which", which_stub(True))
        proc = FakeProc()
        monkeypatch.setattr("lean_herdr.dispatch.Herdr", lambda *a, **kw: Herdr(runner=proc))

        got = _line(["builder", "--kind", kind, "--model", "sonnet"], root, monkeypatch, capsys)

        assert got["ok"] is False
        assert got["error"].startswith(expected), got
        assert proc.calls == [], proc.flat()


    def test_a_relative_role_file_is_resolved_against_the_repo_root(monkeypatch, tmp_path, capsys):
        """Handed on as typed, it would resolve in the pane's worktree, which may lack it."""
        root = tmp_path / "repo"
        _write_config(root, BUILDER_CONFIG)
        write_role_fixture(root, "builder")
        (root / "prompts").mkdir()
        (root / "prompts" / "strict.md").write_text("# Role: builder\n", encoding="utf-8")
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        seen = _spy_dispatch(monkeypatch)

        got = _line([*BUILD_ARGS, "--role-file", "prompts/strict.md"], root, monkeypatch, capsys)

        assert got["ok"] is True, got
        assert [r.role_file for r in seen] == [root / "prompts" / "strict.md"]


    def test_without_a_role_file_the_role_brings_its_own_prompt(monkeypatch, tmp_path, capsys):
        root = tmp_path / "repo"
        _write_config(root, BUILDER_CONFIG)
        write_role_fixture(root, "builder")
        seen = _spy_dispatch(monkeypatch)

        got = _line(BUILD_ARGS, root, monkeypatch, capsys)

        assert got["ok"] is True, got
        assert got["role"] == "builder", got
        assert [r.role_file for r in seen] == [role_prompt_path(root, "builder")]

`BUILD_ARGS` und sein Kommentar:

    #: Everything a builder build needs BESIDE the two flags under test -- the prompt
    #: now comes with the role.
    BUILD_ARGS = ["builder"]

Run: `uv run pytest -q tests/test_dispatch.py -k "role_prompt_travels or stem or cannot_run or role_file or own_prompt"`
— Expected: FAIL (`agent_args` kennt kein `role`; Build-Modus verlangt `--role-file`).

### Schritt 3 — Implementierung

@call patch("lean_herdr/dispatch.py", "the settings import, agent_args, the agent_args call in dispatch, --role-file in build_parser, the build branch of missing_flags, the build branch of main")

1. `claude_settings_path`, `role_problem` und `role_prompt_path` in den Import aus
   `lean_herdr.settings` aufnehmen.

2. `agent_args` ganz ersetzen:

       def agent_args(kind: str, model: str, role_file: Path, role: str, *, root: Path) -> list[str]:
           """Native arguments. Role prompts travel as a FILE, never as text (H2).

           Both runtimes are told the ROLE, never the prompt file's stem: an `--role-file`
           override changes the prompt and nothing else. A claude worker also gets its
           role's settings file -- `deny` beats every `allow` from every source, so that
           file can only narrow what `.claude/settings.json` grants.
           """
           if kind == "claude":
               return [
                   "--model",
                   model,
                   "--append-system-prompt-file",
                   str(role_file),
                   "--settings",
                   str(claude_settings_path(root, role)),
               ]
           if kind == "opencode":
               # With opencode the role prompt hangs on agent.<role>.prompt in
               # opencode.jsonc; here only the agent is picked.
               return ["--model", model, "--agent", role]
           raise ValueError(f"unknown kind: {kind}")

3. In `dispatch()`:
   `agent_args=agent_args(req.kind, req.model, req.role_file, req.role, root=root),`

4. In `build_parser()` das Argument `--role-file`:

       p.add_argument(
           "--role-file",
           default=None,
           type=Path,
           help="build mode: the prompt file; default .lean-ctx/lean-herdr/roles/<role>.md",
       )

5. In `missing_flags()` den Block `missing = [flag for flag, value in (("--model", …), ("--role-file", …)) if not value]`
   samt `if missing: return f"build mode needs …"` ersetzen durch:

       if not args.model:
           return "build mode needs --model"

6. In `main()` den letzten `else:`-Zweig (Build-Modus) ab `result = dispatch(` bis einschließlich
   `result = {**result, "warnings": notes}` ersetzen durch:

                   # Against the ROOT, not $PWD: claude resolves a relative prompt path in
                   # the pane's cwd, and that is the worktree, which need not carry the
                   # file. An absolute --role-file passes through `/` untouched.
                   prompt = (
                       root / args.role_file
                       if args.role_file
                       else role_prompt_path(root, args.command)
                   )
                   # Before dispatch(), so before ensure_worktree and `pane split`: a
                   # worker without its prompt or its runtime's file is a pane that
                   # starts, never reports, and costs the orchestrator a `no_reply`.
                   problem = role_problem(root, args.command, args.kind, prompt)
                   if problem:
                       result = {"ok": False, "error": f"config_error: {problem}"}
                   else:
                       result = dispatch(
                           DispatchRequest(
                               role=args.command,
                               kind=args.kind,
                               model=args.model,
                               role_file=prompt,
                               worktree=args.worktree,
                               profile=args.profile,
                           ),
                           herdr=Herdr(),
                           root=root,
                           cwd=root,
                           settings=settings,
                       )
                       result = {**result, "role": args.command}
                       # Additive, and only where a reader exists: the orchestrator
                       # reads the reviewer's dispatch line, so that is where a
                       # warning about the reviewer's model gets seen. `ok` is
                       # untouched -- a shared model is a warning, never a refusal.
                       notes = model_warnings(raw) if args.command == "reviewer" else []
                       if notes:
                           result = {**result, "warnings": notes}

@call patch("lean_herdr/workspace.py", "the comment above agent_args in start_orchestrator")

Kommentar „NOT agent_args(): that helper always sets --model and derives the agent name from
a role FILE stem." → „NOT agent_args(): that helper always sets --model and hands a claude
worker its role's settings file."

### Schritt 4 — bestehende Tests an die Vorab-Prüfung anpassen

In `tests/test_dispatch.py` jeweils direkt nach dem `_write_config(...)` des Tests:

| Test | Änderung |
|---|---|
| `test_main_loads_the_config_once_for_both_modes` | `write_role_fixture(root, "builder")`; der Build-Aufruf wird `main([*base, "--model", "sonnet"])` |
| `test_main_reads_config_toml_exactly_once_per_call` | `write_role_fixture(root, "builder")` |
| `test_only_the_orchestrator_has_a_kind_without_a_file` | `write_role_fixture(root, "orchestrator", "builder")`; der Orchestrator-Aufruf wird `["orchestrator", "--model", "x"]` |
| `test_the_orchestrators_built_in_kind_does_not_excuse_a_model` | Aufruf wird `["orchestrator"]` (keine Fixture: der Usage-Fehler kommt vorher) |
| `test_the_model_flag_beats_the_file` | `write_role_fixture(root, "builder")` |
| `test_the_config_fills_a_missing_model_flag` | `write_role_fixture(root, "builder")` |
| `test_the_kind_flag_beats_the_file` | `write_role_fixture(root, "builder")` |
| `test_the_config_fills_a_missing_kind_flag` | `write_role_fixture(root, "builder")` |
| `test_a_reviewer_build_carries_the_shared_model_warning` | `write_role_fixture(root, "reviewer")`; Aufruf wird `_line(["reviewer"], root, monkeypatch, capsys)` |
| `test_a_builder_build_of_the_same_config_carries_no_warning` | `write_role_fixture(root, "builder")` |

`tests/test_dispatch_uncovered_paths.py`, `test_main_success_path_never_touches_a_real_subprocess`:
Parameter `tmp_path` ergänzen; vor dem `canonical_root`-Patch `root = tmp_path / "repo"` und
`write_role_fixture(root, "builder")` (Import aus `tests.doubles`); der Patch liefert `root`
statt `ROOT`; der `main`-Aufruf wird `main(["builder", "--kind", "claude", "--model", "sonnet"])`;
das erwartete Ergebnis wird
`{"ok": True, "pane": "w1:p6", "agent_id": AGENT_ID, "agent": "builder", "role": "builder"}`.

Run: {{ var test_cmd }} — Expected: PASS. Scheitert ein weiterer Test mit
`config_error: no role prompt at` oder `config_error: no claude settings at`, bekommt er
`write_role_fixture(root, <rolle>)` wie oben und keine andere Änderung.

### Schritt 5 — README

@call patch("README.md", "the paragraph ending with how far it opens the builder's gate is your call.")

Neuer Absatz direkt danach:

    A claude worker also gets `--settings .lean-ctx/lean-herdr/claude/<role>.json`
    beside `.claude/settings.json`. Claude Code merges the permission lists of
    every source and a `deny` beats every `allow`, so a role file can only
    narrow: `builder.json` is empty, `reviewer.json` takes back the editors,
    `git add`, `git commit`, `wt step commit` and lean-ctx's three write tools.
    An opencode worker gets the same per role from its block in
    `opencode.jsonc`. `dispatch` refuses a role whose prompt, opencode block or
    claude file is missing, before it opens a worktree or a pane.

### Schritt 6 — Produktions-LOC messen

    uv run python - <<'EOF'
    import ast
    import io
    import tokenize
    from pathlib import Path

    SKIP = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER}

    def production_loc(path: Path) -> int:
        source = path.read_text(encoding="utf-8")
        docs = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                first = node.body[0] if node.body else None
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                    docs.update(range(first.lineno, first.end_lineno + 1))
        lines = set()
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type not in SKIP:
                lines.update(range(token.start[0], token.end[0] + 1))
        return len(lines - docs)

    for path in sorted(Path("lean_herdr").glob("*.py")):
        count = production_loc(path)
        print(f"{count:5d} {path}" + ("  <-- over 800" if count > 800 else ""))
    EOF

Expected: keine Zeile mit `over 800`; `dispatch.py` um 550.

### Verify & Close

@call verify(lean_herdr/dispatch.py lean_herdr/workspace.py tests/doubles.py tests/test_dispatch.py tests/test_dispatch_uncovered_paths.py README.md)
@call review_change()
@call gate(lean_herdr/dispatch.py lean_herdr/workspace.py tests/doubles.py tests/test_dispatch.py tests/test_dispatch_uncovered_paths.py)
@call commit("lean_herdr/dispatch.py lean_herdr/workspace.py tests/doubles.py tests/test_dispatch.py tests/test_dispatch_uncovered_paths.py README.md", "feat(dispatch): check a role's prompt and runtime file before any pane, and name agents by role")
@call remember_decision("lean-herdr dispatch since plan 2026-09-14 task 5: the prompt is root-resolved (default .lean-ctx/lean-herdr/roles/<role>.md), role_problem runs in main() before dispatch(), opencode gets --agent <role>, claude gets --settings .lean-ctx/lean-herdr/claude/<role>.json; tests build role files with tests.doubles.write_role_fixture")
@phase-end

@phase "task-6"
## Task 6: `dispatch --work`

**Files:** Modify `lean_herdr/dispatch.py`, `tests/test_dispatch.py`.

**Interfaces — Consumes:** `settings.role_for_work` (Task 2), `tests.doubles.write_role_fixture`
(Task 5). **Produces:**

    lean-herdr dispatch --work <work> [--worktree <branch>] [--profile …] [--model …] [--kind …] [--role-file …]
    lean-herdr dispatch --work <work> --await --task-id o-… [--worktree <branch>] [--prereview] [--timeout-ms …]

    # lean_herdr/dispatch.py
    def role_or_work(args: argparse.Namespace) -> str | None

Fehlertexte, wörtlich: `usage_error: name a role or --work` ·
`usage_error: name a role or --work, not both: <rolle> and --work <art>` ·
`usage_error: `<log-befehl>` does not take --work` · `config_error: no role for work '<art>'`.

Bestehend:
@read lean_herdr/dispatch.py mode=signatures

### Schritt 1 — Tests zuerst

`tests/test_dispatch.py`, direkt nach `test_without_a_role_file_the_role_brings_its_own_prompt`:

    #: A work of the project's own, and the role [routing] names for it.
    RENAME_CONFIG = (
        '[routing]\nrename = "refactorer"\n\n[roles.refactorer]\nkind = "claude"\nmodel = "haiku"\n'
    )


    def test_work_resolves_the_role_with_its_prompt_kind_and_model(monkeypatch, tmp_path, capsys):
        """`--work` behaves exactly like the call by the role it resolves to."""
        root = tmp_path / "repo"
        _write_config(root, RENAME_CONFIG)
        write_role_fixture(root, "refactorer")
        seen = _spy_dispatch(monkeypatch)

        got = _line(["--work", "rename"], root, monkeypatch, capsys)

        assert got["ok"] is True, got
        assert got["role"] == "refactorer", got
        assert [(r.role, r.kind, r.model, r.role_file) for r in seen] == [
            ("refactorer", "claude", "haiku", role_prompt_path(root, "refactorer"))
        ]


    def test_work_implement_needs_no_routing_table(monkeypatch, tmp_path, capsys):
        root = tmp_path / "repo"
        _write_config(root, BUILDER_CONFIG)
        write_role_fixture(root, "builder")
        seen = _spy_dispatch(monkeypatch)

        got = _line(["--work", "implement"], root, monkeypatch, capsys)

        assert got["ok"] is True, got
        assert [r.role for r in seen] == ["builder"]


    def test_work_under_await_rings_the_role_it_resolves_to(monkeypatch, tmp_path, capsys):
        """The wait mode must name the agent the build mode started -- same role, same name."""
        root = tmp_path / "repo"
        _write_config(root, RENAME_CONFIG)
        seen = _spy_dispatch(monkeypatch)

        _line(["--work", "rename", "--await", "--task-id", "o-1"], root, monkeypatch, capsys)

        assert [(r.role, r.kind) for r in seen] == [("refactorer", "claude")]


    def test_a_work_nobody_routed_is_a_config_error(monkeypatch, tmp_path, capsys):
        root = tmp_path / "repo"
        _write_config(root, "")
        _no_launch(monkeypatch)

        got = _line(["--work", "plan", "--kind", "claude", "--model", "m"], root, monkeypatch, capsys)

        assert got == {"ok": False, "error": "config_error: no role for work 'plan'"}


    @pytest.mark.parametrize(
        ("argv", "expected"),
        [
            pytest.param(
                ["builder", "--work", "implement"],
                "usage_error: name a role or --work, not both",
                id="both",
            ),
            pytest.param(["--kind", "claude"], "usage_error: name a role or --work", id="neither"),
            pytest.param(
                ["order", "--to", "b", "--message", "x", "--work", "implement"],
                "usage_error: `order` does not take --work",
                id="with a log command",
            ),
        ],
    )
    def test_a_role_and_work_exclude_each_other(monkeypatch, tmp_path, capsys, argv, expected):
        root = tmp_path / "repo"
        _write_config(root, "")
        _no_launch(monkeypatch)
        monkeypatch.setattr(
            "lean_herdr.dispatch.create_order", lambda *a, **kw: pytest.fail("an order was written")
        )

        got = _line(argv, root, monkeypatch, capsys)

        assert got["ok"] is False
        assert got["error"].startswith(expected), got


    def test_a_work_routed_to_a_log_command_is_a_config_error(monkeypatch, tmp_path, capsys):
        """`order` takes the positional slot instead of a role, so it can never be one."""
        root = tmp_path / "repo"
        _write_config(root, '[routing]\nsend = "order"\n')
        _no_launch(monkeypatch)
        monkeypatch.setattr(
            "lean_herdr.dispatch.create_order", lambda *a, **kw: pytest.fail("an order was written")
        )

        got = _line(["--work", "send", "--to", "b", "--message", "x"], root, monkeypatch, capsys)

        assert got == {
            "ok": False,
            "error": "config_error: routing.send: 'order' is a log command, not a role",
        }

Run: `uv run pytest -q tests/test_dispatch.py -k "work"` — Expected: FAIL für die neuen
Fälle (`unrecognized arguments: --work` bzw. fehlendes Positional); die übrigen PASS.

### Schritt 2 — Implementierung

@call patch("lean_herdr/dispatch.py", "the settings import, the command argument in build_parser, the line before missing_flags, the start of main")

1. `role_for_work` in den Import aus `lean_herdr.settings` aufnehmen.

2. In `build_parser()` das Positional ersetzen und `--work` direkt danach:

       p.add_argument(
           "command",
           nargs="?",
           default=None,
           help="a role -- builder | reviewer | orchestrator | … -- or order | answer | cancel | remember",
       )
       # A role or --work, exactly one; role_or_work() says which is wrong. Not
       # argparse: a JSON line, not exit 2.
       p.add_argument("--work", default=None, help="a kind of work; [routing] names its role")

3. Neu, direkt vor `def missing_flags`:

       def role_or_work(args: argparse.Namespace) -> str | None:
           """A role name or `--work`, exactly one. The complaint, or None.

           Checked before the config is read, unlike missing_flags(): no file can
           answer it, and `--work` has to become a role before settings_for() can read
           that role's table. With a log command `--work` is a stray flag like any other.
           """
           if args.command in LOG_COMMANDS:
               return f"`{args.command}` does not take --work" if args.work is not None else None
           if args.command is None and args.work is None:
               return "name a role or --work"
           if args.command is not None and args.work is not None:
               return f"name a role or --work, not both: {args.command} and --work {args.work}"
           return None

4. In `main()` direkt nach `args = build_parser().parse_args(argv)`:

           clash = role_or_work(args)
           if clash:
               raise UsageError(clash)

   und zwischen `raw = read_settings(root / SETTINGS_PATH)` und
   `settings = settings_for(args.command, raw)`:

           if args.work is not None:
               # From here on the resolved role IS the command: settings_for,
               # missing_flags(), both modes and the warning read one name.
               args.command = role_for_work(args.work, raw)
               # `order`, `answer`, `cancel` and `remember` take the positional slot
               # INSTEAD of a role -- a routed one would turn --work into a log write.
               if args.command in LOG_COMMANDS:
                   raise SettingsError(
                       f"routing.{args.work}: {args.command!r} is a log command, not a role"
                   )

Run: `uv run pytest -q tests/test_dispatch.py tests/test_dispatch_await.py tests/test_dispatch_prereview.py tests/test_dispatch_uncovered_paths.py tests/test_cli.py`
— Expected: PASS.

### Verify & Close

@call verify(lean_herdr/dispatch.py tests/test_dispatch.py)
@call review_change()
@call gate(lean_herdr/dispatch.py tests/test_dispatch.py)
@call commit("lean_herdr/dispatch.py tests/test_dispatch.py", "feat(dispatch): build and wait by kind of work with --work")
@phase-end

@phase "task-7"
## Task 7: die Modell-Warnung folgt der Rolle hinter `review`

**Files:** Modify `lean_herdr/settings.py`, `lean_herdr/dispatch.py`,
`lean_herdr/templates/config.toml`, `README.md`, `tests/test_settings.py`,
`tests/test_initcmd.py`, `tests/test_dispatch.py`. Neu erzeugt:
`.lean-ctx/lean-herdr/config.toml`, `.lean-ctx/lean-herdr/templates.lock.json`.

**Interfaces — Consumes:** `work_roles`, `role_for_work`, `STAGES` (Task 2); `--work` (Task 6).
**Produces:** `RoleSettings.shares_reviewed_model: bool = False` ersetzt
`shares_builder_model` ohne Alias; `model_warnings(data) -> list[str]` bleibt in der
Signatur, jede Zeile beginnt mit `<rolle> and <prüfende rolle> both run on '<modell>'` und
enthält `different blind spots`. `dispatch` hängt `warnings` an die Build-Antwort der Rolle
hinter `review`.

Bestehend:
@symbol body name=model_warnings

### Schritt 1 — Tests zuerst

@call patch("tests/test_settings.py", "test_two_roles_on_one_model_warn_unless_confirmed and its parametrize block")

`test_two_roles_on_one_model_warn_unless_confirmed` samt `@pytest.mark.parametrize` ersetzen durch:

    @pytest.mark.parametrize(
        ("data", "pairs"),
        [
            pytest.param(
                {"roles": {"builder": {"model": "sonnet"}, "reviewer": {"model": "opus"}}},
                [],
                id="two models, nothing to say",
            ),
            pytest.param(
                {"roles": {"builder": {"model": "sonnet"}, "reviewer": {"model": "sonnet"}}},
                ["builder"],
                id="one model, and nobody said so",
            ),
            pytest.param(
                {
                    "roles": {
                        "builder": {"model": "sonnet"},
                        "reviewer": {"model": "sonnet", "shares_reviewed_model": True},
                    }
                },
                [],
                id="one model, and it is meant",
            ),
            pytest.param({}, [], id="no model at all is not a shared model"),
            pytest.param(
                {
                    "routing": {"rename": "refactorer"},
                    "roles": {"refactorer": {"model": "sonnet"}, "reviewer": {"model": "sonnet"}},
                },
                ["refactorer"],
                id="a work of the project's own is paired too",
            ),
            pytest.param(
                {"routing": {"implement": "reviewer"}, "roles": {"reviewer": {"model": "sonnet"}}},
                [],
                id="one role behind both works is no pair",
            ),
            pytest.param(
                {
                    "routing": {"review": "auditor"},
                    "roles": {"builder": {"model": "sonnet"}, "auditor": {"model": "sonnet"}},
                },
                ["builder"],
                id="the checker is whoever stands behind review",
            ),
        ],
    )
    def test_the_role_behind_review_warns_about_each_role_on_its_model(data, pairs):
        """A warning, never a refusal: two workers on one model is legitimate."""
        lines = model_warnings(data)
        assert [line.split(" and ", 1)[0] for line in lines] == pairs
        assert all("'sonnet'" in line and "different blind spots" in line for line in lines)


    def test_the_old_opt_out_key_is_unknown_now():
        """Renamed without an alias -- a file carrying it says so instead of going quiet."""
        with pytest.raises(SettingsError, match=r"unknown keys \['shares_builder_model'\]"):
            settings_for("reviewer", {"roles": {"reviewer": {"shares_builder_model": True}}})

`tests/test_initcmd.py`, in der Parametrisierung von
`test_init_warns_when_builder_and_reviewer_share_a_model`:
`pytest.param("shares_builder_model = true\n", False, …)` →
`pytest.param("shares_reviewed_model = true\n", False, id="one model, and it is meant")`.

`tests/test_dispatch.py`, direkt nach `test_a_builder_build_of_the_same_config_carries_no_warning`:

    def test_the_warning_follows_the_role_behind_review(monkeypatch, tmp_path, capsys):
        """Whoever `[routing]` puts behind `review` carries it -- by work or by name."""
        root = tmp_path / "repo"
        _write_config(
            root,
            '[routing]\nreview = "auditor"\n\n'
            '[roles.builder]\nkind = "claude"\nmodel = "sonnet"\n\n'
            '[roles.auditor]\nkind = "claude"\nmodel = "sonnet"\n\n'
            '[roles.reviewer]\nkind = "claude"\nmodel = "sonnet"\n',
        )
        write_role_fixture(root, "auditor", "reviewer")
        _spy_dispatch(monkeypatch)

        by_work = _line(["--work", "review"], root, monkeypatch, capsys)
        by_name = _line(["auditor"], root, monkeypatch, capsys)
        off_duty = _line(["reviewer"], root, monkeypatch, capsys)

        assert len(by_work.get("warnings", [])) == 1, by_work
        assert "blind spots" in by_work["warnings"][0], by_work
        assert by_name.get("warnings") == by_work["warnings"], by_name
        assert "warnings" not in off_duty, off_duty


    def test_a_broken_table_the_warning_reads_stops_the_call_before_any_pane(
        monkeypatch, tmp_path, capsys
    ):
        """`model_warnings` reads every routed role's table -- before dispatch(), not after."""
        root = tmp_path / "repo"
        _write_config(
            root,
            '[routing]\nrename = "refactorer"\n\n'
            '[roles.refactorer]\ndirection = "links"\n\n'
            '[roles.reviewer]\nkind = "claude"\nmodel = "sonnet"\n',
        )
        write_role_fixture(root, "reviewer")
        _no_launch(monkeypatch)

        got = _line(["--work", "review"], root, monkeypatch, capsys)

        assert got["ok"] is False
        assert got["error"].startswith("config_error: refactorer: direction"), got

Run: `uv run pytest -q tests/test_settings.py tests/test_initcmd.py tests/test_dispatch.py -k "review or opt_out or share or broken_table"`
— Expected: FAIL (neue Parametrisierung, unbekannter neuer Schlüssel, Warnung am falschen Aufruf,
kaputte Tabelle erst nach dem Start bemerkt).

### Schritt 2 — Implementierung

@call patch("lean_herdr/settings.py", "the shares_builder_model field with its comment, its _TYPES entry, model_warnings")

1. In `RoleSettings` das Feld samt Kommentar ersetzen:

       #: Only the role behind `review` has a reader for this one, and that is the
       #: same price `direction` already pays under [roles.orchestrator]: ALLOWED is
       #: built from these fields, so every key is legal under every role. Setting it
       #: elsewhere changes nothing -- it does not quietly change something else
       #: either. It was `shares_builder_model` and has no alias: the old name is an
       #: unknown key now, and says so.
       shares_reviewed_model: bool = False

2. In `_TYPES`: `"shares_builder_model": bool,` → `"shares_reviewed_model": bool,`.

3. `model_warnings` ganz ersetzen:

       def model_warnings(data: dict[str, Any] | None = None) -> list[str]:
           """What a config earns without being wrong. A list, empty is normal.

           The review's value is that it runs on a DIFFERENT model -- different blind
           spots. So the role behind `review` is compared with the role behind every
           work that is not a stage: `implement` and every work of the project's own.
           One line per role on the same, non-empty model; none where both works name
           one role, none when the reviewing role sets `shares_reviewed_model`. A
           warning, never a refusal: two workers on one model is a legitimate thing to
           want, it just must not happen by accident.

           Raises whatever `settings_for()` raises. Both callers read the file once and
           validated already; a second, quieter error path here would be a second rule
           for one thing (M3).
           """
           routes = work_roles(data)
           checker = routes["review"]
           judge = settings_for(checker, data)
           if not judge.model or judge.shares_reviewed_model:
               return []
           reviewed = sorted({role for work, role in routes.items() if work not in STAGES})
           return [
               (
                   f"{role} and {checker} both run on {judge.model!r} -- the {checker} "
                   "earns its keep by having different blind spots. Set "
                   f"[roles.{checker}].shares_reviewed_model = true if this is meant."
               )
               for role in reviewed
               if role != checker and settings_for(role, data).model == judge.model
           ]

@call patch("lean_herdr/dispatch.py", "the else branch after if problem: in the build branch of main")

Im Build-Zweig von `main()` den `else:`-Zweig nach `if problem:` ganz ersetzen. Die Warnung wird
jetzt VOR `dispatch()` berechnet: `model_warnings` liest die Tabelle jeder gerouteten Rolle, und
eine kaputte muss den Aufruf stoppen, solange noch kein Pane steht.

                   else:
                       # Additive, and only where a reader exists: the orchestrator reads
                       # the dispatch line of the role behind `review` -- by `--work review`
                       # or by that role's name. `ok` is untouched: a warning, never a
                       # refusal. Computed BEFORE dispatch(): it reads the table of every
                       # routed role, and a broken one must stop the call while no pane
                       # exists yet, not cost the answer of a worker already started.
                       reviewing = args.command == role_for_work("review", raw)
                       notes = model_warnings(raw) if reviewing else []
                       result = dispatch(
                           DispatchRequest(
                               role=args.command,
                               kind=args.kind,
                               model=args.model,
                               role_file=prompt,
                               worktree=args.worktree,
                               profile=args.profile,
                           ),
                           herdr=Herdr(),
                           root=root,
                           cwd=root,
                           settings=settings,
                       )
                       result = {**result, "role": args.command}
                       if notes:
                           result = {**result, "warnings": notes}

@call patch("lean_herdr/templates/config.toml", "the shares_builder_model line under [roles.reviewer]")

    # shares_reviewed_model = false  # true: a role it reviews shares its model, meant

Run: `uv run lean-herdr workspace init --update` — Expected: eine JSON-Zeile mit `"ok": true`
und `"written": [".lean-ctx/lean-herdr/config.toml"]`.

@call patch("README.md", "the [roles.reviewer] example in Configuration and the paragraph after it")

- `    # shares_builder_model = true # confirm the same model on purpose` →
  `    # shares_reviewed_model = true # confirm the same model on purpose`
- Neuer Absatz direkt nach dem Beispielblock, vor „`--kind` and `--model` on a `dispatch` call beat the file":

      `shares_reviewed_model` belongs to the role behind `review` and silences the
      warning for every role it reviews. It used to be called
      `shares_builder_model`; that name is an unknown key now, and a config
      carrying it fails with `config_error:` until the line is renamed.

Run: `uv run pytest -q tests/test_settings.py tests/test_initcmd.py tests/test_dispatch.py tests/test_templates.py tests/test_checkcmd.py`
— Expected: PASS.

### Verify & Close

@call verify(lean_herdr/settings.py lean_herdr/dispatch.py lean_herdr/templates/config.toml README.md tests/test_settings.py tests/test_initcmd.py tests/test_dispatch.py)
@call review_change()
@call gate(lean_herdr/settings.py lean_herdr/dispatch.py tests/test_settings.py tests/test_initcmd.py tests/test_dispatch.py)
@call commit("lean_herdr/settings.py lean_herdr/dispatch.py lean_herdr/templates/config.toml .lean-ctx/lean-herdr/config.toml .lean-ctx/lean-herdr/templates.lock.json README.md tests/test_settings.py tests/test_initcmd.py tests/test_dispatch.py", "feat(settings): warn when the role behind review shares a model with a role it reviews")
@phase-end

@phase "task-8"
## Task 8: `workspace check` meldet, was `dispatch --work` verweigern würde

**Files:** Modify `lean_herdr/checkcmd.py`, `tests/test_checkcmd.py`.

**Interfaces — Consumes:** `work_roles` (Task 2); `role_prompt_path`, `claude_settings_path`,
`role_problem` (Task 3). **Produces** (`lean_herdr/checkcmd.py`):

    WORKER_SENTENCES = ("lean-herdr report start", "ORCHESTRATOR = orch", "Never pass `--agent`.")
    def _role_warnings(root: Path, data: dict[str, Any]) -> list[str]

`workspace_check()` → `warnings` = Maschine, dann `_role_warnings`, dann Templates. Zeilen,
wörtlich (je Arbeitsart, nach Arbeitsart sortiert):
`no role prompt at <prompt> -- `dispatch --work <art>` fails` ·
`[roles.<rolle>].kind unset: `dispatch --work <art>` needs --kind` ·
`<role_problem> -- `dispatch --work <art>` fails` ·
`<prompt> lacks [<sätze>] -- a worker without them cannot take or answer an order` ·
`<prompt> cannot be read: <fehler>`. `_config_errors` validiert zusätzlich jede Rolle aus
`[routing]`.

Bestehend:
@symbol body name=_config_errors
@symbol body name=workspace_check

### Schritt 1 — Tests zuerst

@call patch("tests/test_checkcmd.py", "the imports, test_an_initialised_project_on_a_healthy_machine_is_ok_and_all_current, the end of the file")

- Imports: `import re`; `claude_settings_path` und `role_prompt_path` in
  `from lean_herdr.settings import …`.
- In `test_an_initialised_project_on_a_healthy_machine_is_ok_and_all_current` die Zeile
  `assert answer["warnings"] == []` ersetzen durch:

      # After `init` no worker has a kind -- the normal case, and check names it.
      assert answer["warnings"] == [
          _kind_unset("builder", "implement"),
          _kind_unset("reviewer", "review"),
      ]

- Am Dateiende:

      def _kind_unset(role: str, work: str) -> str:
          return f"[roles.{role}].kind unset: `dispatch --work {work}` needs --kind"


      #: A work of the project's own, routed to a role `init` never wrote.
      REFACTORER = '[routing]\nrename = "refactorer"\n\n[roles.refactorer]\nkind = "{kind}"\n'


      def _refactorer(repo: Path, kind: str, *, prompt: bool = True) -> Path:
          """The config for `rename`, and -- unless told not to -- the builder's prompt as its own."""
          (repo / SETTINGS_PATH).write_text(REFACTORER.format(kind=kind), encoding="utf-8")
          path = role_prompt_path(repo, "refactorer")
          if prompt:
              path.write_bytes(role_prompt_path(repo, "builder").read_bytes())
          return path


      @pytest.mark.parametrize(
          ("kind", "prompt", "expected"),
          [
              pytest.param("claude", False, "no role prompt at {path}", id="no prompt"),
              pytest.param(
                  "opencode",
                  True,
                  "opencode.jsonc in {repo} defines no agent.refactorer",
                  id="no opencode block",
              ),
              pytest.param("claude", True, "no claude settings at {claude}", id="no claude file"),
          ],
      )
      def test_a_routed_role_dispatch_would_refuse_is_named(
          monkeypatch, repo, snapshot, kind, prompt, expected
      ):
          """A warning, not an error: `up` runs without it, and an unused work costs nothing."""
          initialised(monkeypatch, repo)
          monkeypatch.setattr("shutil.which", which_stub(False))
          path = _refactorer(repo, kind, prompt=prompt)
          line = expected.format(path=path, repo=repo, claude=claude_settings_path(repo, "refactorer"))

          answer = workspace_check(root=repo)

          assert answer["errors"] == [], answer["errors"]
          assert f"{line} -- `dispatch --work rename` fails" in answer["warnings"], answer["warnings"]


      def test_a_worker_prompt_without_its_mandatory_sentences_is_named(monkeypatch, repo, snapshot):
          initialised(monkeypatch, repo)
          monkeypatch.setattr("shutil.which", which_stub(False))
          prompt = role_prompt_path(repo, "reviewer")
          text = re.sub(r"Never pass\s+`--agent`\.", "", prompt.read_text(encoding="utf-8"))
          prompt.write_text(text, encoding="utf-8")

          warnings = workspace_check(root=repo)["warnings"]

          expected = (
              f"{prompt} lacks ['Never pass `--agent`.'] -- "
              "a worker without them cannot take or answer an order"
          )
          assert expected in warnings, warnings


      def test_a_role_only_routing_names_is_validated_too(monkeypatch, repo, snapshot):
          """`checkcmd.ROLES` knows four tables; a role behind `[routing]` is one more."""
          initialised(monkeypatch, repo)
          monkeypatch.setattr("shutil.which", which_stub(False))
          (repo / SETTINGS_PATH).write_text(
              '[routing]\nrename = "refactorer"\n\n[roles.refactorer]\ndirection = "links"\n',
              encoding="utf-8",
          )

          answer = workspace_check(root=repo)

          assert answer["ok"] is False
          assert any(e.startswith("config_error: refactorer: direction") for e in answer["errors"]), (
              answer["errors"]
          )

Run: `uv run pytest -q tests/test_checkcmd.py` — Expected: FAIL für den gesunden Fall und die
fünf neuen Fälle.

### Schritt 2 — Implementierung

@call patch("lean_herdr/checkcmd.py", "the settings import, ROLES, the line after ROLES, _config_errors, the warnings line of workspace_check")

1. In den Import aus `lean_herdr.settings`: `ORCHESTRATOR_AGENT`, `role_problem`,
   `role_prompt_path`, `work_roles`.

2. Kommentar über `ROLES`:
   `#: The tables `up` and `dispatch` read roles out of -- _config_errors adds every role [routing] names.`

3. Neu, direkt nach `ROLES`:

       #: What every worker prompt has to say, or its run breaks without a word: the
       #: order is never accepted, the sender never trusted, or an event is written
       #: under another name. tests/test_role_prohibitions.py and tests/test_roles.py pin
       #: them for the shipped prompts; this reaches a prompt of the project's own.
       WORKER_SENTENCES = (
           "lean-herdr report start",
           f"ORCHESTRATOR = {ORCHESTRATOR_AGENT}",
           "Never pass `--agent`.",
       )

4. In `_config_errors` die Zeile `for role in ROLES:` ersetzen durch:

               for role in (*ROLES, *work_roles(data).values()):

5. Neu, direkt vor `def _template_report`:

       def _role_warnings(root: Path, data: dict[str, Any]) -> list[str]:
           """What `dispatch --work <work>` would refuse, or run blind, for every work with a role.

           Warnings, never errors: `up` runs without any of it, and a work nobody
           dispatches costs nothing. `data` is config.toml already read and valid, `{}`
           otherwise -- the built-in works are checked either way. The artefact check is
           `role_problem`, the one `dispatch` refuses with (one producer per rule, M3).
           """
           lines: list[str] = []
           for work, role in sorted(work_roles(data).items()):
               prompt = role_prompt_path(root, role)
               if not prompt.is_file():
                   lines.append(f"no role prompt at {prompt} -- `dispatch --work {work}` fails")
                   continue
               kind = settings_for(role, data).kind
               if not kind:
                   # The normal case after `init`: workers have no built-in kind.
                   lines.append(f"[roles.{role}].kind unset: `dispatch --work {work}` needs --kind")
               else:
                   problem = role_problem(root, role, kind, prompt)
                   if problem:
                       lines.append(f"{problem} -- `dispatch --work {work}` fails")
               if role == "orchestrator":
                   continue
               try:
                   text = " ".join(prompt.read_text(encoding="utf-8").split())
               except (OSError, UnicodeDecodeError) as exc:
                   lines.append(f"{prompt} cannot be read: {exc}")
                   continue
               missing = [sentence for sentence in WORKER_SENTENCES if sentence not in text]
               if missing:
                   lines.append(
                       f"{prompt} lacks {missing} -- a worker without them cannot take or answer an order"
                   )
           return lines

6. In `workspace_check()`:
   `"warnings": warnings + template_lines,` → `"warnings": warnings + _role_warnings(base, data) + template_lines,`

Run: `uv run pytest -q tests/test_checkcmd.py tests/test_initcmd.py` — Expected: PASS.

Produktions-LOC messen — dasselbe Skript wie in Task 5, Schritt 6:

    uv run python - <<'EOF'
    import ast
    import io
    import tokenize
    from pathlib import Path

    SKIP = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER}

    def production_loc(path: Path) -> int:
        source = path.read_text(encoding="utf-8")
        docs = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                first = node.body[0] if node.body else None
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                    docs.update(range(first.lineno, first.end_lineno + 1))
        lines = set()
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type not in SKIP:
                lines.update(range(token.start[0], token.end[0] + 1))
        return len(lines - docs)

    for path in sorted(Path("lean_herdr").glob("*.py")):
        count = production_loc(path)
        print(f"{count:5d} {path}" + ("  <-- over 800" if count > 800 else ""))
    EOF

Expected: keine Zeile mit `over 800`.

### Verify & Close

@call verify(lean_herdr/checkcmd.py tests/test_checkcmd.py)
@call review_change()
@call gate(lean_herdr/checkcmd.py tests/test_checkcmd.py)
@call commit("lean_herdr/checkcmd.py tests/test_checkcmd.py", "feat(workspace): name in check every work whose role dispatch would refuse")
@phase-end

@phase "task-9"
## Task 9: `orchestrator.md` ohne Rollennamen, README und `[routing]` im Config-Template

**Files:** Modify `lean_herdr/templates/roles/orchestrator.md`,
`lean_herdr/templates/config.toml`, `tests/test_role_prohibitions.py`, `README.md`. Neu erzeugt:
`.lean-ctx/lean-herdr/roles/orchestrator.md`, `.lean-ctx/lean-herdr/config.toml`,
`.lean-ctx/lean-herdr/templates.lock.json`.

**Interfaces — Consumes:** `dispatch --work` (Task 6), die Warnung an `--work review` (Task 7),
die Zeile `shares_reviewed_model` im Config-Template (Task 7). Keine neue Code-Schnittstelle.
Reihenfolge, Prereview, Teardown und Eskalation in `orchestrator.md` bleiben inhaltlich gleich.

### Schritt 1 — Tests zuerst

@call patch("tests/test_role_prohibitions.py", "the Orchestrator block of PROHIBITIONS, the Orchestrator block of MANDATORY_SENTENCES, test_the_role_file_path_the_orchestrator_types_actually_resolves")

- In `PROHIBITIONS`, Block `# --- Orchestrator`, als letzter Eintrag:

      (
          "orchestrator.md",
          "You pass no role name and no prompt file.",
          "the config picks the role behind a work, not the orchestrator",
      ),

- In `MANDATORY_SENTENCES`, Block `# --- Orchestrator`, als erste Einträge:

      (
          "orchestrator.md",
          "lean-herdr dispatch --work <work> [--worktree <branch>]",
          "the build names the kind of work; [routing] names the role behind it",
      ),
      (
          "orchestrator.md",
          "lean-herdr dispatch --work <work> --await",
          "the wait call names the same work as the build, or it rings nobody",
      ),
      (
          "orchestrator.md",
          "Then the same three steps with `--work review` on the same branch.",
          "the review stays mandatory -- only the role behind it moved into the config",
      ),

- `test_the_role_file_path_the_orchestrator_types_actually_resolves` ganz ersetzen durch:

      def test_the_orchestrator_dispatches_by_work_and_names_no_role():
          """Since `[routing]` the config picks the role behind a work.

          A role name or a `--role-file` left in this prompt would be a second place
          that decides it -- one no config line can overrule, and one a renamed role
          turns into a dead run.
          """
          text = _normalized("orchestrator.md")
          assert "--work" in text
          assert "--role-file" not in text
          named = re.findall(r"\b(?:builder|reviewer)\b", text)
          assert not named, f"orchestrator.md still names roles: {named}"

Run: `uv run pytest -q tests/test_role_prohibitions.py` — Expected: FAIL für die vier neuen
Sätze und den Ersatztest.

### Schritt 2 — `orchestrator.md`

@call patch("lean_herdr/templates/roles/orchestrator.md", "sections 1. Build the worker, 3. Let it wait, Model and runtime, Sequence per task, the builder's message in the teardown")

1. Abschnitt `### 1. Build the worker` — alles zwischen dieser Überschrift und
   `### 2. Create the order` ersetzen durch:

       ### 1. Build the worker

           lean-herdr dispatch --work <work> [--worktree <branch>] [--profile <p>]

       `<work>` names the kind of work, not who does it: `implement` for the code,
       `review` for the ruling on it. The config decides which role does a work,
       and with which prompt. You pass no role name and no prompt file.

       The output is one JSON line. Read `ok`, never the exit code. On success it
       carries `pane`, `agent_id`, `agent` and `role`.

2. Abschnitt `### 3. Let it wait` — alles zwischen dieser Überschrift und
   `## Model and runtime — not your choice` ersetzen durch:

       ### 3. Let it wait

           lean-herdr dispatch --work <work> --await \
             --task-id o-… [--worktree <branch>] [--timeout-ms 300000]

       The same `--work` as in step 1: that is how this call finds the worker it
       rings. It rings the worker and then waits inside the script, not inside you.
       It costs you one model step, however long the work takes.

3. Abschnitt `## Model and runtime — not your choice` — alles bis `## Sequence per task`
   ersetzen durch:

       ## Model and runtime — not your choice

       `.lean-ctx/lean-herdr/config.toml` decides who does a work: `[routing]`
       names the role behind it, `[roles.<role>]` that role's model and runtime.
       **Leave `--kind` and `--model` off your dispatch calls**
       -- the file fills them in. Pass one only to override the file for a single
       call, and say why when you do.

       If the file names no model for a role, `dispatch` answers
       `usage_error: build mode needs --model` and builds nothing. That is
       deliberate: a worker quietly running on its runtime's default model costs
       real money and nobody sees it.

       The review earns its keep by having **different blind spots** than the work
       it checks -- a different model, not a second opinion from the same one. If
       the config gives both the same model, your `--work review` dispatch line
       carries a `warnings` entry saying so. It is a warning, not a refusal: report
       it and carry on.

       The pre-review is not a third worker: it is a flag on the wait call of
       `--work implement`, and the model behind it is small and cheap. It may
       block, it may never approve -- the strong review runs in every case, `pass`
       or not.

4. Abschnitt `## Sequence per task` — die nummerierte Liste bis vor
   `### When the worker asks back` ersetzen durch:

       1. Settle the branch name.
       2. Build the worker for `--work implement` (step 1) — with
          `--worktree <branch>` if code is produced. Create the order (step 2), let
          it wait (step 3).
       3. `ok: true`? Read `prereview` first, if you asked for it.

          The wait call of `--work implement` may carry `--prereview`:

              lean-herdr dispatch --work implement --await --task-id o-… \
                --worktree <branch> --prereview

          It costs you nothing extra -- you read that JSON line anyway. The key
          stands beside `verdict`, never instead of it, and takes one of three
          values:

          | `prereview` | What you do |
          |---|---|
          | `reject` | round 2 of `--work implement`, BEFORE any review worker is built |
          | `pass` | build the review worker -- `pass` is not an approval |
          | `skipped` | build the review worker -- the pre-review withheld its ruling |

          A `reject` is one follow-up order to the same worker, with `--after o-…`,
          carrying `prereview_note` verbatim. On THAT round you do **not** pass
          `--prereview` again: that limits a stubborn small model to exactly one
          rejection, without a counter anywhere.

          Then the same three steps with `--work review` on the same branch.
       4. The review's ruling is in `verdict`: `result` or `reject`. No prose
          parsing — if nothing is there, the review worker broke its format; treat
          that like `reject` and tell it so.
       5. On `result`: tear down and merge (below). On `reject`: round 2 of
          `--work implement`, then escalate.

5. Im Abschnitt `## Teardown and merge — this order, not another`:
   „`wt` leaves the builder's message alone" → „`wt` leaves the worker's message alone".

### Schritt 3 — `[routing]` im Config-Template

@call patch("lean_herdr/templates/config.toml", "the blank line after the shares_reviewed_model line, before # [llm]")

Neu, zwischen der Zeile `# shares_reviewed_model = false  # …` samt Leerzeile und `# [llm]`:

    # [routing] names the role behind each kind of work: `lean-herdr dispatch
    # --work <work>` builds that role, with its prompt under roles/ and its
    # [roles.<role>] table. Built in: implement = builder, review = reviewer.
    # Reserved, with no built-in role yet: plan, plan-review, integrate.
    # A work is [a-z][a-z0-9-]*, a role [a-z][a-z0-9_-]*.

    # [routing]
    # implement = "builder"
    # review    = "reviewer"
    # rename    = "refactorer"   # a work of your own: needs [roles.refactorer],
    #                            # roles/refactorer.md, and its opencode agent
    #                            # block or claude/refactorer.json

Eine Leerzeile trennt den Block von `# [llm]`.

Run: `uv run lean-herdr workspace init --update` — Expected: eine JSON-Zeile mit `"ok": true`
und `"written": [".lean-ctx/lean-herdr/config.toml", ".lean-ctx/lean-herdr/roles/orchestrator.md"]`.

### Schritt 4 — README

@call patch("README.md", "step 2 and step 5 of One task, start to finish; the first paragraph of Configuration; the paragraph ending it needs --model or a set model")

- Schritt 2 der Liste „One task, start to finish" ersetzen durch:

      2. It builds a worker with `lean-herdr dispatch --work implement --worktree <branch>`:
         `[routing]` in the config names the role for that work -- the builder,
         unless you route it elsewhere. worktrunk creates the worktree, Herdr opens
         a workspace on it, and the agent starts in a pane there.

- Schritt 5: „5. The reviewer runs on the same branch." →
  „5. The reviewer runs on the same branch (`--work review`)."
- „Five sections: `[default]` and `[roles.<role>]` describe how a pane is split," →
  „Six sections: `[routing]` names the role behind each kind of work, `[default]` and
  `[roles.<role>]` describe how a pane is split,"
- Neuer Absatz direkt nach dem Absatz, der mit „it needs `--model` or a set `model`." endet:

      Which role does which kind of work is set in `[routing]`. Without the table
      the two built-in works apply -- `implement` goes to `builder`, `review` to
      `reviewer` -- and a work of your own needs a line and a role:

          [routing]
          rename = "refactorer"

          [roles.refactorer]
          kind  = "opencode"
          model = "<a model>"

      `lean-herdr dispatch --work rename` then builds the `refactorer` with
      `.lean-ctx/lean-herdr/roles/refactorer.md`; an opencode role also needs its
      block under `agent` in `opencode.jsonc`, a claude role its
      `.lean-ctx/lean-herdr/claude/refactorer.json`. `plan`, `plan-review` and
      `integrate` are reserved and have no built-in role yet: a call without a
      `[routing]` line for one is `config_error: no role for work 'plan'`. A work
      is spelled `[a-z][a-z0-9-]*`, a role `[a-z][a-z0-9_-]*`.
      `lean-herdr workspace check` names every work whose role lacks its prompt,
      its runtime, its file or a sentence the worker cannot run without.

### Schritt 5 — ganze Suite

Run: {{ var test_cmd }} — Expected: PASS.

Run: `git diff --quiet HEAD -- .claude/settings.json lean_herdr/templates/settings.json lean_herdr/templates/roles/builder.md lean_herdr/templates/roles/reviewer.md .lean-ctx/lean-herdr/roles/builder.md .lean-ctx/lean-herdr/roles/reviewer.md`
— Expected: Exit 0.

### Verify & Close

@call verify(lean_herdr/templates/roles/orchestrator.md lean_herdr/templates/config.toml tests/test_role_prohibitions.py README.md)
@call review_change()
@call gate(tests/test_role_prohibitions.py)
@call commit("lean_herdr/templates/roles/orchestrator.md lean_herdr/templates/config.toml .lean-ctx/lean-herdr/roles/orchestrator.md .lean-ctx/lean-herdr/config.toml .lean-ctx/lean-herdr/templates.lock.json tests/test_role_prohibitions.py README.md", "feat(orchestrator): hand out work by kind through --work and name no role")
@call remember_decision("lean-herdr TP1 done (plan 2026-09-14 rollen-und-routing): orchestrator.md dispatches only by --work implement and --work review and names no role; [routing] in config.toml picks the role; TP2 adds plan, plan-review and the plan-writer/plan-reviewer roles through the same role_for_work")
@phase-end
