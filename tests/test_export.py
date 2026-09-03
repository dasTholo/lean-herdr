import json
import sqlite3

from lean_herdr.export import (
    claude_session_path,
    find_error,
    opencode_messages,
    read_jsonl,
    session_error,
    session_id_from_agent_list,
)

FAILED_EXPORT = {
    "messages": [
        {"role": "user", "content": "do something"},
        {
            "role": "assistant",
            "error": {
                "name": "APIError",
                "data": {
                    "message": "User not found.",
                    "statusCode": 401,
                    "url": "https://openrouter.ai/api/v1/chat",
                },
            },
        },
    ]
}


def test_find_error_reads_the_nested_apierror():
    assert find_error(FAILED_EXPORT) == "APIError: User not found. (401)"


def test_find_error_is_none_for_a_clean_export():
    assert find_error({"messages": [{"role": "assistant", "content": "done"}]}) is None


def test_find_error_ignores_empty_error_fields():
    assert find_error({"error": None, "messages": [{"error": {}}]}) is None


def test_find_error_also_accepts_a_string():
    assert find_error({"session": {"last_error": "rate limited"}}) == "rate limited"


def test_session_id_from_agent_list():
    agents = [
        {"name": "orch", "agent_session": {"value": "2cd57baf"}},
        {"name": "builder", "agent_session": {"value": "1b7c63c4"}},
    ]
    assert session_id_from_agent_list(agents, "builder") == "1b7c63c4"
    assert session_id_from_agent_list(agents, "gone") is None


def test_claude_path_is_the_slug_of_the_project_root_path(tmp_path):
    path = claude_session_path("abc123", tmp_path)
    expected = str(tmp_path.resolve()).replace("/", "-")
    assert path.parent.name == expected
    assert path.name == "abc123.jsonl"


def test_read_jsonl_skips_broken_lines(tmp_path):
    file = tmp_path / "s.jsonl"
    file.write_text('{"a": 1}\nnot json\n\n{"b": 2}\n', encoding="utf-8")
    assert read_jsonl(file) == [{"a": 1}, {"b": 2}]


def test_read_jsonl_is_empty_when_the_file_is_missing(tmp_path):
    assert read_jsonl(tmp_path / "does-not-exist.jsonl") == []


def _opencode_db(tmp_path, session_id, messages):
    """Minimal reconstruction of the real store: message(session_id, data, time_created)."""
    path = tmp_path / "opencode.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE message (session_id TEXT, data TEXT, time_created INTEGER)")
    for i, message in enumerate(messages):
        con.execute(
            "INSERT INTO message VALUES (?, ?, ?)",
            (session_id, json.dumps(message), i),
        )
    con.commit()
    con.close()
    return path


def test_opencode_messages_reads_only_its_own_session(tmp_path):
    path = _opencode_db(tmp_path, "s1", [{"role": "user"}, {"role": "assistant"}])
    con = sqlite3.connect(path)
    con.execute("INSERT INTO message VALUES ('s2', '{\"role\": \"foreign\"}', 9)")
    con.commit()
    con.close()
    assert opencode_messages("s1", path) == [{"role": "user"}, {"role": "assistant"}]


def test_opencode_messages_is_empty_without_a_database(tmp_path):
    assert opencode_messages("s1", tmp_path / "gone.db") == []


def test_session_error_finds_the_error_in_the_opencode_store(tmp_path):
    path = _opencode_db(tmp_path, "s1", [FAILED_EXPORT["messages"][1]])
    error = session_error("opencode", "s1", tmp_path, db_path=path)
    assert error == "APIError: User not found. (401)"


def test_session_error_is_none_without_a_session_id(tmp_path):
    assert session_error("opencode", None, tmp_path) is None
    assert session_error("claude", "", tmp_path) is None


def test_session_error_knows_only_the_two_stores(tmp_path):
    assert session_error("codex", "s1", tmp_path) is None
