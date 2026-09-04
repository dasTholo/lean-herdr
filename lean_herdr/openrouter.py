"""Everything this project knows about OpenRouter: the key, and the one request.

Two consumers, and the split is the point. `llm.py` runs on the SYSTEM
interpreter -- worktrunk starts `bin/herdr-llm generate` as
`commit.generation.command` in every repository on this machine, and
that interpreter has no httpx and no tomli_w. `catalog.py` asks the same
host for its model list. Both need the base url and the same never-raising
error profile; only one of them needs a key.

`api_key()` moved here out of llm.py, where it was Completion knowledge
by accident. A module is named after what it speaks to.

Nothing here raises. `None` is every failure there is, and each caller
turns it into its own safe behaviour -- a fallback commit message, an
untouched overlay. A raise would reach worktrunk as a failed generation
command, and a failed command is fatal.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

BASE_URL = "https://openrouter.ai/api/v1"
ENDPOINT = f"{BASE_URL}/chat/completions"

KEY_ENV = "OPENROUTER_API_KEY"

#: opencode's credential store, read only when $OPENROUTER_API_KEY is
#: absent. Shape verified: {"openrouter": {"key": ..., "type": ...}}.
AUTH_PATH = Path.home() / ".local/share/opencode/auth.json"


def api_key(env: Any = None, auth_path: Any = None) -> str | None:
    """`$OPENROUTER_API_KEY`, else opencode's store, else None.

    None is not an error here. Every caller answers it with a safe
    behaviour of its own -- a fallback message, a skipped pre-review --
    never with an exception. A missing key must not break a commit.
    """
    environ = os.environ if env is None else env
    key = (environ.get(KEY_ENV) or "").strip()
    if key:
        return key
    path = AUTH_PATH if auth_path is None else Path(auth_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    entry = data.get("openrouter") if isinstance(data, dict) else None
    stored = entry.get("key") if isinstance(entry, dict) else None
    if not isinstance(stored, str) or not stored.strip():
        return None
    return stored.strip()


def request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: str | None = None,
    timeout_s: float,
) -> str | None:
    """One HTTP round trip as text, or None. Never raises.

    None means "no usable answer" for every reason there is: DNS, a
    refused connection, a socket timeout, a non-2xx status, bytes we
    cannot decode. The caller cannot tell those apart and does not need
    to -- it needs to not crash.

    The key never touches the filesystem and never touches argv: it
    arrives inside `headers` and stays in this process's memory. Its
    predecessor wrote it into a 0600 curl config file -- `ps` never saw
    it there either, but the filesystem did.

    The one behaviour that is NOT a port of curl: `max-time` was a TOTAL
    deadline, `timeout=` here is a SOCKET timeout, i.e. a deadline per
    blocking operation. A server dribbling one byte every 19 s keeps a
    20 s call alive forever. For a single non-streaming request against
    OpenRouter that is theoretical; a hard total deadline needs a
    watchdog, and no caller in this tree asks for one.
    """
    payload = None if body is None else body.encode("utf-8")
    req = urllib.request.Request(url, data=payload, method=method)
    for name, value in (headers or {}).items():
        req.add_header(name, value)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as response:
            raw = response.read()
    except (OSError, ValueError) as exc:
        # OSError is the wide net on purpose: urllib.error.URLError
        # descends from it, HTTPError (a non-2xx status) descends from
        # URLError, and a socket timeout IS an OSError. ValueError is the
        # belt -- a malformed url, or a header value http.client refuses,
        # neither of which may leave a function whose whole contract is
        # "never raises".
        #
        # The line on stderr is the cheap cure for the failure mode the
        # spec names: a network error that vanishes into a fallback
        # message looks exactly like a missing key.
        print(f"lean-herdr: {url} did not answer: {exc}", file=sys.stderr)
        return None
    # `replace`, never strict: one byte that is not UTF-8 in an error page
    # would otherwise raise out of here as a UnicodeDecodeError -- which is
    # a ValueError, and would arrive too late to be caught above.
    return raw.decode("utf-8", errors="replace")
