import hashlib
import json
from dataclasses import FrozenInstanceError

import pytest

from lean_herdr.orderlog import (
    DIGEST_PREFIX_LEN,
    SCHEMA_VERSION,
    SEQUENCE_DIGITS,
    OrderLogError,
    append,
    lean_ctx_data_dir,
    new_task_id,
    read_events,
    state_dir,
    task_ids,
)

TASK = "o-1a05e34cd15-1cf3b885"


def files(orders, task=TASK):
    return sorted(p for p in (orders / task / "events").iterdir() if p.suffix == ".json")


def test_the_first_event_opens_the_chain(tmp_path):
    event = append(TASK, "created", "orchestrator", {"description": "x"}, orders=tmp_path)
    assert event.sequence == 1
    assert event.previous_digest is None
    assert event.kind == "created"


def test_the_file_name_carries_sequence_and_digest_prefix(tmp_path):
    """A renamed or swapped file must be visible, not silent."""
    event = append(TASK, "created", "orchestrator", orders=tmp_path)
    (path,) = files(tmp_path)
    assert path.name == f"{'0' * 15}1-{event.digest[:DIGEST_PREFIX_LEN]}.json"


def test_the_file_bytes_are_what_was_hashed(tmp_path):
    """sha256sum on the file reproduces the digest in its name."""
    event = append(TASK, "created", "orchestrator", {"description": "x"}, orders=tmp_path)
    (path,) = files(tmp_path)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == event.digest


def test_every_further_event_links_to_its_predecessor(tmp_path):
    first = append(TASK, "created", "orchestrator", orders=tmp_path)
    second = append(TASK, "working", "builder-feat-x", orders=tmp_path)
    assert second.sequence == 2
    assert second.previous_digest == f"sha256:{first.digest}"
    assert [e.kind for e in read_events(TASK, orders=tmp_path)] == ["created", "working"]


def test_the_body_carries_the_schema_version(tmp_path):
    append(TASK, "created", "orchestrator", orders=tmp_path)
    (path,) = files(tmp_path)
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == SCHEMA_VERSION


def test_an_event_is_immutable(tmp_path):
    """`frozen=True` on Event is load-bearing, and nothing pinned it.

    An Event's `digest` is the sha256 of the file it was read from, and the
    next event's `previous_digest` is compared against it. An assignable
    field would let a caller re-point the chain in memory -- the very
    forgery read_events() exists to catch, done after the read.
    """
    event = append(TASK, "created", "orchestrator", orders=tmp_path)
    with pytest.raises(FrozenInstanceError):
        event.digest = "0" * 64


def test_a_missing_log_is_empty_and_not_an_error(tmp_path):
    """Before the first event the directory simply does not exist."""
    assert read_events(TASK, orders=tmp_path) == []
    assert task_ids(orders=tmp_path / "nowhere") == []


def test_a_changed_body_breaks_the_chain(tmp_path):
    append(TASK, "created", "orchestrator", {"description": "x"}, orders=tmp_path)
    (path,) = files(tmp_path)
    body = json.loads(path.read_text(encoding="utf-8"))
    body["payload"]["description"] = "something else"
    path.write_bytes(json.dumps(body, sort_keys=True, separators=(",", ":")).encode())
    with pytest.raises(OrderLogError, match="chain_broken"):
        read_events(TASK, orders=tmp_path)


def test_a_gap_in_the_sequence_breaks_the_chain(tmp_path):
    append(TASK, "created", "orchestrator", orders=tmp_path)
    append(TASK, "working", "builder-feat-x", orders=tmp_path)
    append(TASK, "completed", "builder-feat-x", orders=tmp_path)
    first, second, _third = files(tmp_path)
    second.unlink()
    with pytest.raises(OrderLogError, match=rf"chain_broken: {TASK} @ 2: out of sequence"):
        read_events(TASK, orders=tmp_path)
    assert first.exists()


def test_a_duplicate_sequence_breaks_the_chain(tmp_path):
    """Two writers at the same sequence keep BOTH files -- and that is an error."""
    append(TASK, "created", "orchestrator", orders=tmp_path)
    (path,) = files(tmp_path)
    # a genuine second event at sequence 1 -- own bytes, own valid digest,
    # so it is the SEQUENCE check that has to catch it, not the file name.
    body = json.loads(path.read_text(encoding="utf-8"))
    body["actor"] = "someone-else"
    blob = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    digest = hashlib.sha256(blob).hexdigest()
    path.with_name(f"{'0' * 15}1-{digest[:DIGEST_PREFIX_LEN]}.json").write_bytes(blob)
    with pytest.raises(OrderLogError, match="chain_broken"):
        read_events(TASK, orders=tmp_path)


def test_a_relinked_event_breaks_the_chain(tmp_path):
    """The `previous_digest` comparison -- the check nothing else reaches.

    This forgery is the one neither of the other two checks can see: event 3
    keeps its own sequence AND hashes to the digest in its own file name, so
    the name check and the running count both wave it through. Only its
    `previous_digest` lies -- it points back at event 1, cutting event 2 out
    of the chain. Disable the comparison in read_events() and every other
    test in this file stays green.
    """
    first = append(TASK, "created", "orchestrator", orders=tmp_path)
    append(TASK, "working", "builder-feat-x", orders=tmp_path)
    append(TASK, "input-required", "builder-feat-x", {"message": "?"}, orders=tmp_path)
    *_earlier, third = files(tmp_path)
    body = json.loads(third.read_text(encoding="utf-8"))
    body["previous_digest"] = f"sha256:{first.digest}"
    blob = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    digest = hashlib.sha256(blob).hexdigest()
    third.unlink()
    third.with_name(f"{3:0{SEQUENCE_DIGITS}d}-{digest[:DIGEST_PREFIX_LEN]}.json").write_bytes(blob)
    with pytest.raises(OrderLogError, match=rf"chain_broken: {TASK} @ 3: not linked"):
        read_events(TASK, orders=tmp_path)


def test_an_unknown_schema_version_is_unreadable_not_empty(tmp_path):
    append(TASK, "created", "orchestrator", orders=tmp_path)
    (path,) = files(tmp_path)
    body = json.loads(path.read_text(encoding="utf-8"))
    body["schema_version"] = "lean-herdr.order-event/v2"
    blob = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    path.with_name(
        f"{'0' * 15}1-{hashlib.sha256(blob).hexdigest()[:DIGEST_PREFIX_LEN]}.json"
    ).write_bytes(blob)
    path.unlink()
    with pytest.raises(OrderLogError, match="log_unreadable"):
        read_events(TASK, orders=tmp_path)


def test_append_refuses_to_extend_a_broken_chain(tmp_path):
    append(TASK, "created", "orchestrator", orders=tmp_path)
    (path,) = files(tmp_path)
    path.write_bytes(b'{"schema_version": "lean-herdr.order-event/v1"}')
    with pytest.raises(OrderLogError):
        append(TASK, "working", "builder-feat-x", orders=tmp_path)


def test_a_task_id_never_becomes_a_path_escape(tmp_path):
    """`--task-id` comes off a command line. `../` must not reach the disk."""
    for evil in ("../escape", "..", ".", "a/b", "", "o" * 65, "o-\x00", "o-bad\n"):
        with pytest.raises(OrderLogError, match="bad_task_id"):
            read_events(evil, orders=tmp_path)
    # And the write path guards the same way -- it is the one that creates.
    with pytest.raises(OrderLogError, match="bad_task_id"):
        append("..", "created", "orchestrator", orders=tmp_path)


def test_task_ids_lists_the_orders_newest_first(tmp_path):
    for task in ("o-a-1", "o-c-3", "o-b-2"):
        append(task, "created", "orchestrator", orders=tmp_path)
    assert task_ids(orders=tmp_path) == ["o-c-3", "o-b-2", "o-a-1"]


def test_a_new_task_id_is_unique_and_prefixed(tmp_path):
    ids = {new_task_id() for _ in range(50)}
    assert len(ids) == 50
    assert all(i.startswith("o-") for i in ids)


def test_no_temp_file_survives_an_append(tmp_path):
    """The atomic rename must leave nothing behind."""
    append(TASK, "created", "orchestrator", orders=tmp_path)
    assert not [p for p in (tmp_path / TASK / "events").iterdir() if p.name.startswith(".tmp")]


def guard(tmp_path, monkeypatch, *, data=None):
    monkeypatch.setenv("LEAN_CTX_DATA_DIR", str(data or tmp_path / "data"))
    return tmp_path / "repo"


def test_state_dir_follows_LEAN_CTX_DATA_DIR(tmp_path, monkeypatch):
    root = guard(tmp_path, monkeypatch)
    assert state_dir(root) == tmp_path / "data" / "lean-herdr" / "repo" / "orders"


def test_state_dir_writes_the_canonical_root_beside_the_orders(tmp_path, monkeypatch):
    root = guard(tmp_path, monkeypatch)
    orders = state_dir(root)
    assert (orders.parent / "root").read_text(encoding="utf-8").strip() == str(root)


def test_a_second_clone_under_the_same_name_is_an_error_not_a_dodge(tmp_path, monkeypatch):
    """Two checkouts named `repo` must not silently mix their orders."""
    monkeypatch.setenv("LEAN_CTX_DATA_DIR", str(tmp_path / "data"))
    state_dir(tmp_path / "one" / "repo")
    with pytest.raises(OrderLogError, match="state_root_mismatch"):
        state_dir(tmp_path / "two" / "repo")


def test_a_second_call_from_the_same_root_is_fine(tmp_path, monkeypatch):
    root = guard(tmp_path, monkeypatch)
    assert state_dir(root) == state_dir(root)


def test_the_data_dir_falls_back_to_xdg(tmp_path, monkeypatch):
    monkeypatch.delenv("LEAN_CTX_DATA_DIR", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    assert lean_ctx_data_dir() == tmp_path / "data" / "lean-ctx"


def test_a_legacy_install_with_data_wins_over_xdg(tmp_path, monkeypatch):
    monkeypatch.delenv("LEAN_CTX_DATA_DIR", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    (tmp_path / ".lean-ctx").mkdir()
    (tmp_path / ".lean-ctx" / "stats.json").write_text("{}", encoding="utf-8")
    assert lean_ctx_data_dir() == tmp_path / ".lean-ctx"


def test_an_empty_legacy_directory_does_not_count(tmp_path, monkeypatch):
    """An empty ~/.lean-ctx from a setup run must not split the store."""
    monkeypatch.delenv("LEAN_CTX_DATA_DIR", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    (tmp_path / ".lean-ctx").mkdir()
    assert lean_ctx_data_dir() == tmp_path / "data" / "lean-ctx"


def test_an_empty_marker_file_does_not_count(tmp_path, monkeypatch):
    monkeypatch.delenv("LEAN_CTX_DATA_DIR", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    (tmp_path / ".lean-ctx").mkdir()
    (tmp_path / ".lean-ctx" / "stats.json").write_text("", encoding="utf-8")
    assert lean_ctx_data_dir() == tmp_path / "data" / "lean-ctx"


def test_an_empty_marker_directory_does_not_count(tmp_path, monkeypatch):
    monkeypatch.delenv("LEAN_CTX_DATA_DIR", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    (tmp_path / ".lean-ctx" / "sessions").mkdir(parents=True)
    assert lean_ctx_data_dir() == tmp_path / "data" / "lean-ctx"


def test_a_non_empty_marker_directory_still_selects_legacy(tmp_path, monkeypatch):
    """Guards against over-correcting _has_data() into 'never legacy'."""
    monkeypatch.delenv("LEAN_CTX_DATA_DIR", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    sessions = tmp_path / ".lean-ctx" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "s1.json").write_text("{}", encoding="utf-8")
    assert lean_ctx_data_dir() == tmp_path / ".lean-ctx"
