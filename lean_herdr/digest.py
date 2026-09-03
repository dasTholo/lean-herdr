"""Context -> digest. Pure functions over text, no I/O.

The digest arrives FINISHED from `ctx_session resume`. Here it is only
unframed and extended by the handoff references -- it is never rebuilt from
fields.
"""

from __future__ import annotations

import re

MAX_HANDOFF_LINES = 12
TOKEN_MAX = 60

#: The frame lines of ctx_session resume: `--- SESSION RESUME ... ---` and `---`.
FRAME = re.compile(r"^-{3,}.*$", re.MULTILINE)

#: The configuration line is an instruction to the server, not context.
COMPRESSION_LINE = re.compile(r"^\[COMPRESSION:.*$", re.MULTILINE)

#: `Task: ...` in the resume text -- the only line that feeds the token.
#: `[ \t]`, not `\s`: `\s` crosses the line break, so an empty `Task:` line
#: would swallow the FOLLOWING line instead of leaving the fallback its turn.
TASK_LINE = re.compile(r"^Task:[ \t]*(.+)$", re.MULTILINE)
FINDINGS_LINE = re.compile(r"^Key findings:\s*(.+)$", re.MULTILINE)


def strip_frame(resume_text: str) -> str:
    """Drop frame and configuration lines, keep the content.

    Everything else stays VERBATIM -- Project, Archives, Stats and ledger
    lines included, all of which a rebuild would lose.
    """
    without = COMPRESSION_LINE.sub("", FRAME.sub("", resume_text or ""))
    return "\n".join(line for line in without.splitlines() if line.strip()).strip()


def render_digest(resume_text: str, handoff_text: str | None = None) -> str | None:
    """Markdown digest -- or None when there is nothing to show."""
    core = strip_frame(resume_text)
    # No .strip() on the joined block: blank lines are already gone, so there
    # is nothing left around it -- but stripping would eat the indentation of
    # the first and last line, and `ctx_handoff show` delivers JSON whose
    # indentation carries meaning.
    handoff = "\n".join(
        line for line in (handoff_text or "").splitlines() if line.strip()
    )
    if not (core or handoff):
        return None

    lines = ["# lean-ctx context", ""]
    if core:
        lines += [core, ""]
    if handoff:
        capped = handoff.splitlines()[:MAX_HANDOFF_LINES]
        lines += ["## Handoff", *capped, ""]
    return "\n".join(lines).rstrip() + "\n"


def summary_token(resume_text: str, max_len: int = TOKEN_MAX) -> str | None:
    """One-liner for the `ctx` metadata token of the sidebar."""
    text = resume_text or ""
    match = TASK_LINE.search(text)
    raw = match.group(1) if match else ""
    if not raw.strip():
        findings = FINDINGS_LINE.search(text)
        if not findings:
            return None
        count = len([t for t in findings.group(1).split(";") if t.strip()])
        return f"{count} findings" if count else None
    single = " ".join(raw.split())
    return single if len(single) <= max_len else single[: max_len - 1] + "…"
