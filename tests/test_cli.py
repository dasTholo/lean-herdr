"""The verb router: routing, and the three ways of getting it wrong.

Every verb's own main is tested by its own file. What is tested here is
that the router reaches it with the REST of the arguments, that a bad
verb keeps the house contract instead of argparse's exit 2, and that a
verb whose module dies on the way in keeps it too.
"""

import json
import sys
import types

import pytest

from lean_herdr import cli


@pytest.mark.parametrize(("verb", "module"), sorted(cli.VERBS.items()))
def test_each_verb_reaches_its_own_main_with_the_rest(monkeypatch, verb, module):
    seen = {}

    def fake_main(argv):
        seen["argv"] = argv
        return 0

    monkeypatch.setattr(f"{module}.main", fake_main)
    assert cli.main([verb, "--kind", "opencode"]) == 0
    assert seen["argv"] == ["--kind", "opencode"], "the verb must not travel on"


def test_the_models_verb_reaches_the_catalogue(monkeypatch):
    """The fourth verb, and the one that must never reach the network here.

    `catalog.main` has no `request` seam on purpose, so the seam is the
    function itself -- exactly what the router hands the rest of the
    arguments to.
    """
    seen: dict[str, list[str]] = {}

    def fake_main(argv: list[str]) -> int:
        seen["argv"] = argv
        return 0

    monkeypatch.setattr("lean_herdr.catalog.main", fake_main)
    assert cli.main(["models", "check"]) == 0
    assert seen["argv"] == ["check"]


def test_an_unknown_verb_is_a_json_line_and_exit_zero(capsys):
    """Exit 2 plus a line on stderr would reach the caller as no output."""
    assert cli.main(["does-not-exist"]) == 0
    answer = json.loads(capsys.readouterr().out)
    assert answer["ok"] is False
    assert answer["error"].startswith("usage_error: unknown verb")


def test_no_verb_at_all_is_the_same_shape(capsys):
    assert cli.main([]) == 0
    answer = json.loads(capsys.readouterr().out)
    assert answer["ok"] is False
    assert "no verb" in answer["error"]


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_help_is_plain_text_for_a_human(capsys, flag):
    """Both spellings, because `-h` would otherwise route as an unknown verb."""
    assert cli.main([flag]) == 0
    assert capsys.readouterr().out.startswith("usage: lean-herdr")


def test_every_verb_names_a_module_that_actually_imports():
    """A typo in VERBS would only surface on the call that needs it."""
    import importlib

    for verb, module in cli.VERBS.items():
        assert callable(importlib.import_module(module).main), verb


def test_a_verb_whose_module_dies_on_import_is_still_one_json_line(monkeypatch, capsys):
    """A delegate's `except` ladder does not exist until it is imported.

    `lean_herdr.workspace` reaches dispatch and from there ordercmd,
    which binds `ORCHESTRATOR_AGENT` while the module body runs. A
    failure that deep happens before any of those clauses are in scope,
    and the router would hand the caller a traceback and a non-zero
    exit -- the one shape an orchestrator cannot tell apart from no
    output at all.
    """
    monkeypatch.setitem(cli.VERBS, "boom", "lean_herdr.no_such_module")
    assert cli.main(["boom"]) == 0
    answer = json.loads(capsys.readouterr().out)
    assert answer["ok"] is False
    assert answer["error"].startswith("cli_crashed: boom:")


def test_a_verb_whose_main_raises_is_caught_too(monkeypatch, capsys):
    """Every delegate catches its own. The router does not bet on it."""
    module = types.ModuleType("lean_herdr.exploding_verb")

    def explode(argv: list[str]) -> int:
        raise RuntimeError("the delegate let one through")

    module.__dict__["main"] = explode
    monkeypatch.setitem(sys.modules, "lean_herdr.exploding_verb", module)
    monkeypatch.setitem(cli.VERBS, "boom", "lean_herdr.exploding_verb")
    assert cli.main(["boom"]) == 0
    answer = json.loads(capsys.readouterr().out)
    assert answer["ok"] is False
    assert "the delegate let one through" in answer["error"]


def test_llm_prereview_hands_its_exit_code_through(monkeypatch):
    """Exit 1 is the ruling `reject` -- the one verb whose exit code carries a result."""
    monkeypatch.setattr("lean_herdr.llm.main", lambda argv: 1 if argv[:1] == ["prereview"] else 0)
    assert cli.main(["llm", "prereview", "--order", "x"]) == 1
    assert cli.main(["llm", "generate"]) == 0


@pytest.mark.parametrize(("verb", "code"), [("llm", 1), ("plugin", 0)])
def test_a_plain_verb_that_dies_on_import_writes_nothing_on_stdout(monkeypatch, capsys, verb, code):
    """On `llm generate` a JSON line on stdout would become the commit message.

    `llm` ends loud, with 1, at the first commit -- like the argparse usage error
    `llm.main` already lets through. `plugin` ends with 0: a handler never breaks
    anything, and stderr is the plugin log.
    """
    monkeypatch.setitem(cli.VERBS, verb, "lean_herdr.no_such_module")
    assert cli.main([verb, "generate"]) == code
    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith(f"lean-herdr {verb}: "), err
