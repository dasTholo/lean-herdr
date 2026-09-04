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


def test_help_is_plain_text_for_a_human(capsys):
    assert cli.main(["--help"]) == 0
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

    module.main = explode
    monkeypatch.setitem(sys.modules, "lean_herdr.exploding_verb", module)
    monkeypatch.setitem(cli.VERBS, "boom", "lean_herdr.exploding_verb")
    assert cli.main(["boom"]) == 0
    answer = json.loads(capsys.readouterr().out)
    assert answer["ok"] is False
    assert "the delegate let one through" in answer["error"]
