@lean-md
consumer: ai
crp: compact

# lean-herdr TP2 — Index der Pläne

Spec: `docs/specs/2026-09-14-lean-herdr-plan-design.md`

TP2 ist in drei Pläne geteilt, die nacheinander laufen. Jeder rendert eine Task je Aufruf:
`lean-md render <plan> --phase task-N`.

| # | Plan | Tasks | Ergebnis |
|---|---|---|---|
| A | `docs/lean-md/plans/2026-09-14-lean-herdr-plan-a-auftrag.lmd.md` | 4 | Plan-Felder im Auftrag, Stempel `head`/`changes` über `wt list`, Längenprüfung der Agent-Namen, `PATH` für Worker |
| B | `docs/lean-md/plans/2026-09-14-lean-herdr-plan-b-steuerung.lmd.md` | 6 | `plan.py`, `planrun.py`, `lean-herdr plan check, next, show, brief`, Pre-Review im Plan-Modus |
| C | `docs/lean-md/plans/2026-09-14-lean-herdr-plan-c-ausliefern.lmd.md` | 9 | Rollen, Routing, Rechte, Vorlagen, Briefs, `init`, `check`, README/INSTALL, Abnahme |

Plan C hat einen Anhang, `docs/lean-md/plans/2026-09-14-lean-herdr-plan-c-dateien.md`: Dateien mit
lean-md-Direktiven, die in einer `.lmd.md`-Datei ausgewertet würden.

## Voraussetzungen

- TP0 (erfüllt 2026-09-15): lean-md 0.2.4 mit `outline --json` ist über Shim und Gateway installiert
  (Tag `v0.2.4` = `3d27803`; Plan im lean-md-Repository `docs/lean-md/plans/2026-09-14-lmd-outline-json.lmd.md`).
  Plan A braucht es nicht, Plan B nur über Doubles, Plan C misst es in Task 1.
- Jeder Plan beginnt auf einem `main`, auf dem sein Vorgänger gemergt ist.

## Übergaben

- A → B: `Order.plan`, `step`, `plan_task`, `spec`, `start_head`, `done_head`, `done_changes`;
  `orders.PLAN_SLUG_RE`, `orders.PLAN_TASK_RE`; `report.worktree_stamp`.
- B → C: `lean-herdr plan brief | check | next | show`; `plan.BRANCH_FILES`; `plancmd.BRIEFS_DIR`.
- Nach C: das Teilprojekt Anbieterwahl, danach der FastAPI-Testlauf (Spec §1.1).

## Abnahme (Spec §15)

- `uv run pytest -q` grün; `lean-herdr workspace check` in diesem Repository ohne neue Fehler.
- Ein Plan mit einer Task läuft in einem Wegwerf-Repository bis `done` (Plan C, Task 9).
