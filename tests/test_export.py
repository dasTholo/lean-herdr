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

GESCHEITERT = {
    "messages": [
        {"role": "user", "content": "tu was"},
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


def test_find_error_liest_die_verschachtelte_apierror():
    assert find_error(GESCHEITERT) == "APIError: User not found. (401)"


def test_find_error_ist_none_bei_sauberem_export():
    assert find_error({"messages": [{"role": "assistant", "content": "fertig"}]}) is None


def test_find_error_ignoriert_leere_fehlerfelder():
    assert find_error({"error": None, "messages": [{"error": {}}]}) is None


def test_find_error_nimmt_auch_eine_zeichenkette():
    assert find_error({"session": {"last_error": "rate limited"}}) == "rate limited"


def test_session_id_aus_agent_list():
    agents = [
        {"name": "orch", "agent_session": {"value": "2cd57baf"}},
        {"name": "builder", "agent_session": {"value": "1b7c63c4"}},
    ]
    assert session_id_from_agent_list(agents, "builder") == "1b7c63c4"
    assert session_id_from_agent_list(agents, "weg") is None


def test_claude_pfad_ist_der_slug_des_projektwurzelpfads(tmp_path):
    pfad = claude_session_path("abc123", tmp_path)
    erwartet = str(tmp_path.resolve()).replace("/", "-")
    assert pfad.parent.name == erwartet
    assert pfad.name == "abc123.jsonl"


def test_read_jsonl_ueberspringt_kaputte_zeilen(tmp_path):
    datei = tmp_path / "s.jsonl"
    datei.write_text('{"a": 1}\nkein json\n\n{"b": 2}\n', encoding="utf-8")
    assert read_jsonl(datei) == [{"a": 1}, {"b": 2}]


def test_read_jsonl_ist_leer_wenn_die_datei_fehlt(tmp_path):
    assert read_jsonl(tmp_path / "gibt-es-nicht.jsonl") == []


def _opencode_db(tmp_path, session_id, nachrichten):
    """Minimale Nachbildung der echten Ablage: message(session_id, data, time_created)."""
    pfad = tmp_path / "opencode.db"
    con = sqlite3.connect(pfad)
    con.execute("CREATE TABLE message (session_id TEXT, data TEXT, time_created INTEGER)")
    for i, nachricht in enumerate(nachrichten):
        con.execute(
            "INSERT INTO message VALUES (?, ?, ?)",
            (session_id, json.dumps(nachricht), i),
        )
    con.commit()
    con.close()
    return pfad


def test_opencode_messages_liest_nur_die_eigene_sitzung(tmp_path):
    pfad = _opencode_db(tmp_path, "s1", [{"role": "user"}, {"role": "assistant"}])
    con = sqlite3.connect(pfad)
    con.execute("INSERT INTO message VALUES ('s2', '{\"role\": \"fremd\"}', 9)")
    con.commit()
    con.close()
    assert opencode_messages("s1", pfad) == [{"role": "user"}, {"role": "assistant"}]


def test_opencode_messages_ist_leer_ohne_datenbank(tmp_path):
    assert opencode_messages("s1", tmp_path / "weg.db") == []


def test_session_error_findet_den_fehler_in_der_opencode_ablage(tmp_path):
    pfad = _opencode_db(tmp_path, "s1", [GESCHEITERT["messages"][1]])
    fehler = session_error("opencode", "s1", tmp_path, db_path=pfad)
    assert fehler == "APIError: User not found. (401)"


def test_session_error_ist_none_ohne_session_id(tmp_path):
    assert session_error("opencode", None, tmp_path) is None
    assert session_error("claude", "", tmp_path) is None


def test_session_error_kennt_nur_die_zwei_ablagen(tmp_path):
    assert session_error("codex", "s1", tmp_path) is None
