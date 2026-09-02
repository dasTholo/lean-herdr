from lean_herdr.digest import render_digest, strip_frame, summary_token

#: The shape of a real `lean-ctx call ctx_session {"action":"resume"}`. The
#: wording is synthetic; the LINES are what matters, because render_digest()
#: must carry every one of them through.
RESUME = (
    "--- SESSION RESUME (post-compaction) ---\n"
    "[COMPRESSION: standard] Dense output. Atomic fact lines.\n"
    "Project: lean-herdr\n"
    "Task: rework the plan\n"
    "Key findings: registry.json carries the messages under scratchpad; "
    "project_root is usually null\n"
    "Archives: d87f9bd455c4c365(ctx_read), c5f10c0559312d84(ctx_read)\n"
    "Stats: 104 calls, 1382898 tok saved\n"
    "---"
)
HANDOFF = " ctx_handoff show\n path: /x.json\n  - lean_herdr/digest.py\n  - tests/"


def test_the_finished_digest_is_adopted_not_rebuilt():
    """No field may get lost -- Project, Archives and Stats included."""
    text = render_digest(RESUME, HANDOFF)
    assert text is not None
    for line in (
        "Project: lean-herdr",
        "Task: rework the plan",
        "Archives: d87f9bd455c4c365(ctx_read)",
        "Stats: 104 calls, 1382898 tok saved",
    ):
        assert line in text, f"lost: {line}"
    assert "- lean_herdr/digest.py" in text


def test_only_frame_and_configuration_lines_are_dropped():
    core = strip_frame(RESUME)
    assert "SESSION RESUME" not in core
    assert "[COMPRESSION:" not in core
    assert not core.startswith("-") and not core.endswith("-")
    assert "Project: lean-herdr" in core


def test_without_content_there_is_no_digest():
    """Fresh project: no digest, no token -- the normal case, not a failure."""
    assert render_digest("", None) is None
    assert render_digest("--- SESSION RESUME ---\n---", None) is None
    assert summary_token("") is None


def test_the_token_is_single_line_and_capped():
    token = summary_token("Task: " + "x" * 200)
    assert token is not None and len(token) <= 60 and "\n" not in token
    assert token.endswith("…")


def test_the_token_falls_back_to_the_findings_count():
    assert summary_token("Key findings: a; b") == "2 findings"
    assert summary_token("Project: x") is None
    # A real resume is multi-line and neither line comes first: without
    # re.MULTILINE both patterns would miss and the token would be None.
    assert summary_token(RESUME) == "rework the plan"
    assert summary_token("Project: x\nKey findings: a; b") == "2 findings"


def test_the_handoff_is_capped():
    many = "\n".join(f"  - file{i}.py" for i in range(40))
    text = render_digest("Task: t", many)
    # `- file`, not `  - file`: render_digest() strips the joined handoff, so
    # the FIRST line loses its indentation. Counting without it stays exact.
    assert text is not None and text.count("- file") == 12
