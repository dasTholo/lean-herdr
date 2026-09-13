"""`openrouter.request` never reaches the network in here, and never raises."""

import io
import json
import subprocess
import sys
import urllib.error

import pytest

from lean_herdr import openrouter


class FakeResponse(io.BytesIO):
    """What urlopen's context manager yields: a readable with a close."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def urlopen_returning(raw: bytes, recorder: dict):
    def fake(req, timeout=None):
        recorder["url"] = req.full_url
        recorder["method"] = req.get_method()
        recorder["headers"] = dict(req.header_items())
        recorder["body"] = req.data
        recorder["timeout"] = timeout
        return FakeResponse(raw)

    return fake


def test_a_get_carries_url_method_and_timeout(monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(openrouter.urllib.request, "urlopen", urlopen_returning(b"{}", seen))
    assert openrouter.request("https://x/y", timeout_s=3.5) == "{}"
    assert seen["url"] == "https://x/y"
    assert seen["method"] == "GET"
    assert seen["body"] is None
    assert seen["timeout"] == 3.5


def test_a_post_carries_headers_and_an_encoded_body(monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(
        openrouter.urllib.request,
        "urlopen",
        urlopen_returning(json.dumps({"ok": True}).encode(), seen),
    )
    got = openrouter.request(
        openrouter.ENDPOINT,
        method="POST",
        headers={"Authorization": "Bearer k", "Content-Type": "application/json"},
        body='{"model": "m"}',
        timeout_s=20.0,
    )
    assert json.loads(got) == {"ok": True}
    assert seen["method"] == "POST"
    assert seen["body"] == b'{"model": "m"}'
    # add_header title-cases the name; the value must survive verbatim.
    assert seen["headers"]["Authorization"] == "Bearer k"


@pytest.mark.parametrize(
    "boom",
    [
        urllib.error.URLError("no route"),
        urllib.error.HTTPError("https://x", 400, "Bad Request", {}, None),
        TimeoutError("timed out"),
        ValueError("unknown url type"),
    ],
    ids=["transport", "http-error", "timeout", "bad-url"],
)
def test_every_failure_is_none_and_none_of_them_raise(monkeypatch, boom):
    def fake(req, timeout=None):
        raise boom

    monkeypatch.setattr(openrouter.urllib.request, "urlopen", fake)
    assert openrouter.request("https://x", timeout_s=1.0) is None


def test_a_body_that_is_not_utf8_is_replaced_not_raised(monkeypatch):
    monkeypatch.setattr(openrouter.urllib.request, "urlopen", urlopen_returning(b"caf\xe9", {}))
    assert openrouter.request("https://x", timeout_s=1.0) == "caf�"


@pytest.fixture
def no_store(tmp_path):
    """An auth.json that does not exist -- the empty-machine case."""
    return tmp_path / "absent" / "auth.json"


def test_the_env_key_beats_the_opencode_store(tmp_path):
    store = tmp_path / "auth.json"
    store.write_text(json.dumps({"openrouter": {"key": "from-store"}}))
    assert openrouter.api_key({openrouter.KEY_ENV: "from-env"}, store) == "from-env"


def test_the_store_answers_when_the_env_is_empty(tmp_path):
    store = tmp_path / "auth.json"
    store.write_text(json.dumps({"openrouter": {"key": "from-store"}}))
    assert openrouter.api_key({}, store) == "from-store"
    assert openrouter.api_key({openrouter.KEY_ENV: "   "}, store) == "from-store"


def test_no_key_anywhere_is_none_not_a_crash(no_store):
    assert openrouter.api_key({}, no_store) is None


def test_a_malformed_store_is_none_not_a_crash(tmp_path):
    store = tmp_path / "auth.json"
    store.write_text("{ not json")
    assert openrouter.api_key({}, store) is None
    store.write_text(json.dumps({"openrouter": "a string"}))
    assert openrouter.api_key({}, store) is None


def test_openrouter_imports_nothing_from_lean_herdr():
    """The root of its subtree: `llm.py` and `catalog.py` import it, it imports neither.

    `bin/herdr-llm` loads this on the system interpreter at every commit, so anything
    it pulled in from the package would ride along. A subprocess, because pytest has
    long since imported the rest of `lean_herdr` into this one -- the pattern of
    `test_importing_handlers_does_not_drag_in_the_workspace_subtree`.
    """
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import lean_herdr.openrouter, sys;"
                "print(sorted(m for m in sys.modules if m.split('.')[0] == 'lean_herdr'))"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    assert proc.stdout.strip() == "['lean_herdr', 'lean_herdr.openrouter']", (
        proc.stdout + proc.stderr
    )
