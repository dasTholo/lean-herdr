"""One binary, seven verbs: `lean-herdr dispatch | llm | models | plan | plugin | report | workspace`.

A router, nothing more. Every verb hands off to a `main(argv) -> int` that
already exists and already keeps its own contract. Five keep the house
contract: one JSON line on stdout, `ok` as the only truth, exit ALWAYS 0. Two
do not, on purpose, because nobody reading JSON calls them:

* `llm` is worktrunk's commit generator and the manual pre-review. `generate`
  writes the message on stdout and exits 0; `prereview` exits 1 on `reject`.
* `plugin` is Herdr's event and action handler: nothing on stdout, failures
  on stderr -- the plugin log -- and exit 0.

The one rung this file keeps is the one no delegate can reach: the import
itself, which runs before that delegate's own `except` clauses exist. For the
two plain verbs that rung writes NO JSON line -- on `llm generate` it would
become the commit message.

The verb modules are imported ON THE CALL, not up here. `lean_herdr.
workspace` reaches `lean_herdr.dispatch` and from there `ordercmd`; a
top-level import of all three would make this router the place where
that whole chain resolves, and a bare `lean-herdr report next` -- the
call a worker makes on every single step -- would pay for it.
"""

from __future__ import annotations

import importlib
import json
import sys

#: verb -> the module that owns it. The values are import PATHS, not
#: modules: see the docstring on why nothing is imported up here.
#: A verb without a module would be a crash disguised as a usage error --
#: test_cli.py imports every value to keep that impossible.
VERBS = {
    "dispatch": "lean_herdr.dispatch",
    "llm": "lean_herdr.llm",
    "models": "lean_herdr.catalog",
    "plan": "lean_herdr.plancmd",
    "plugin": "lean_herdr.__main__",
    "report": "lean_herdr.report",
    "workspace": "lean_herdr.workspace",
}

#: The two verbs outside the JSON contract, and the exit code an import crash
#: ends them with. `llm` 1: a broken install is loud at the first commit.
#: `plugin` 0: a handler never breaks anything.
PLAIN_VERBS = {"llm": 1, "plugin": 0}

USAGE = (
    "usage: lean-herdr {dispatch|llm|models|plan|plugin|report|workspace} ...\n"
    "  dispatch, models, plan, report, workspace: one JSON line on stdout, exit 0\n"
    "  llm generate: the commit message on stdout, exit 0\n"
    "  llm prereview: the ruling on stdout, exit 1 on reject\n"
    "  plugin <sub>: Herdr's handlers -- nothing on stdout, errors on stderr, exit 0\n"
)


def _usage(message: str) -> int:
    """A usage error is a JSON line and exit 0, never argparse's exit 2.

    Same reason as dispatch._Parser.error: the caller reads `ok` on
    stdout. An unknown verb that ended the process with exit 2 and one
    line on stderr would reach an orchestrator as no output at all --
    indistinguishable from a crash.
    """
    line = {"ok": False, "error": f"usage_error: {message}"}
    sys.stdout.write(json.dumps(line, ensure_ascii=False) + "\n")
    return 0


def _crashed(verb: str, exc: BaseException) -> int:
    """The last rung of report.main's ladder, one level up.

    A verb's own main catches everything it can raise -- but only once
    it is imported. `lean_herdr.workspace` reaches dispatch and from
    there ordercmd, which binds `ORCHESTRATOR_AGENT` while the module
    body runs; a failure there happens before a single one of those
    `except` clauses is in scope. The verb is named in the message
    because the traceback it replaces is the only other thing that
    would have said which import died.

    The two plain verbs get a stderr line instead, and their own exit
    code (PLAIN_VERBS).
    """
    if verb in PLAIN_VERBS:
        sys.stderr.write(f"lean-herdr {verb}: cannot run {VERBS[verb]}: {exc}\n")
        return PLAIN_VERBS[verb]
    line = {"ok": False, "error": f"cli_crashed: {verb}: {exc}"}
    sys.stdout.write(json.dumps(line, ensure_ascii=False) + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Route `lean-herdr <verb> ...` to the verb's own main. Exit ALWAYS 0."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        return _usage(f"no verb; expected one of {sorted(VERBS)}")
    verb, rest = args[0], args[1:]
    if verb in ("-h", "--help"):
        # --help goes to stdout as plain text, not as JSON: it is the one
        # output a human asked for directly. Same split argparse makes
        # between exit() and error().
        sys.stdout.write(USAGE)
        return 0
    module = VERBS.get(verb)
    if module is None:
        return _usage(f"unknown verb {verb!r}; expected one of {sorted(VERBS)}")
    try:
        return importlib.import_module(module).main(rest)
    except Exception as exc:  # noqa: BLE001 -- never abort the caller
        return _crashed(verb, exc)


if __name__ == "__main__":
    raise SystemExit(main())
