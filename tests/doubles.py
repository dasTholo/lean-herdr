"""Recording test doubles for subprocess-driven CLIs.

Shape taken from lean-ctx/integrations/hermes-lean-ctx (FakeGateway,
Apache-2.0): the double records what was called and answers from a table.
No network, no real binary.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Completed:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


@dataclass
class FakeProc:
    """Replaces subprocess.run. `replies` maps an argument prefix to a reply.

    Two reply shapes, because there are two CLIs: Herdr prints JSON, `lean-ctx
    call` plain text. A **str** therefore reaches stdout verbatim, anything
    else through json.dumps -- otherwise an error line such as
    `error: -32602: ...` could not be faked, because json.dumps would wrap it
    in quotes.
    """

    replies: dict[tuple[str, ...], Any] = field(default_factory=dict)
    calls: list[list[str]] = field(default_factory=list)
    raises: Exception | None = None
    default: Any = field(default_factory=dict)

    @staticmethod
    def _stdout(reply: Any) -> str:
        return reply if isinstance(reply, str) else json.dumps(reply)

    def __call__(self, cmd: list[str], **kwargs: Any) -> Completed:
        self.calls.append(list(cmd))
        if self.raises is not None:
            raise self.raises
        for prefix, reply in self.replies.items():
            if tuple(cmd[1 : 1 + len(prefix)]) == prefix:
                return Completed(stdout=self._stdout(reply))
        return Completed(stdout=self._stdout(self.default))

    def called_with(self, *tokens: str) -> bool:
        """Was there a call containing all tokens in this order?"""
        for call in self.calls:
            rest = list(call)
            for token in tokens:
                if token in rest:
                    rest = rest[rest.index(token) + 1 :]
                else:
                    break
            else:
                return True
        return False

    def flat(self) -> str:
        return " | ".join(" ".join(c) for c in self.calls)


def which_stub(available: bool) -> Callable[[str], str | None]:
    return lambda _binary: "/usr/bin/fake" if available else None
