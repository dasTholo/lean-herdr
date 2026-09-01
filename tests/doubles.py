"""Aufzeichnende Testdoppel fuer subprocess-getriebene CLIs.

Form uebernommen aus lean-ctx/integrations/hermes-lean-ctx (FakeGateway,
Apache-2.0): das Doppel zeichnet auf, was gerufen wurde, und antwortet aus
einer Tabelle. Kein Netz, kein echtes Binary.
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
    """Ersetzt subprocess.run. `replies` bildet ein Argument-Praefix auf eine
    Antwort ab.

    Zwei Antwortformen, weil es zwei CLIs gibt: Herdr gibt JSON aus, `lean-ctx
    call` Klartext. Ein **str** wird deshalb wortwoertlich zu stdout, alles
    andere per json.dumps — sonst liesse sich eine Fehlerzeile wie
    `error: -32602: …` nicht faelschen, weil json.dumps sie in
    Anfuehrungszeichen setzte.
    """

    replies: dict[tuple[str, ...], Any] = field(default_factory=dict)
    calls: list[list[str]] = field(default_factory=list)
    raises: Exception | None = None
    default: Any = field(default_factory=dict)

    @staticmethod
    def _stdout(antwort: Any) -> str:
        return antwort if isinstance(antwort, str) else json.dumps(antwort)

    def __call__(self, cmd: list[str], **kwargs: Any) -> Completed:
        self.calls.append(list(cmd))
        if self.raises is not None:
            raise self.raises
        for praefix, antwort in self.replies.items():
            if tuple(cmd[1 : 1 + len(praefix)]) == praefix:
                return Completed(stdout=self._stdout(antwort))
        return Completed(stdout=self._stdout(self.default))

    def called_with(self, *tokens: str) -> bool:
        """Kam ein Aufruf vor, der alle Tokens in dieser Reihenfolge enthaelt?"""
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
