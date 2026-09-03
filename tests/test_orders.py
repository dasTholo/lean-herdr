from dataclasses import FrozenInstanceError

import pytest

from lean_herdr.orderlog import Event
from lean_herdr.orders import (
    EVENT_KINDS,
    Order,
    fold,
    is_terminal,
    message_from,
    newest_open,
)

TASK = "o-1a05e34cd15-1cf3b885"
ORCH = "orchestrator"
WORKER = "builder-feat-x"


def event(kind, actor=WORKER, seq=1, **payload):
    return Event(
        sequence=seq,
        kind=kind,
        task_id=TASK,
        actor=actor,
        at="2026-09-03T07:12:04Z",
        previous_digest=None if seq == 1 else "sha256:x",
        payload=payload,
        digest=f"d{seq}",
    )


def created(**payload):
    base = {"to_agent": WORKER, "description": "build the order log"}
    return event("created", ORCH, 1, **(base | payload))


def test_a_created_event_alone_is_an_open_order():
    order = fold([created()])
    assert order.id == TASK
    assert order.from_agent == ORCH
    assert order.to_agent == WORKER
    assert order.state == "created"
    assert order.description == "build the order log"
    assert order.is_open


def test_the_state_is_the_last_transition():
    order = fold([created(), event("working", seq=2), event("completed", seq=3)])
    assert order.state == "completed"
    assert not order.is_open


@pytest.mark.parametrize("kind", ("completed", "failed", "canceled"))
def test_the_three_terminal_kinds_close_the_order(kind):
    assert is_terminal(fold([created(), event(kind, seq=2)]).state)


def test_answered_is_the_only_kind_that_is_not_its_own_state():
    """The orchestrator answered, so the worker is working again."""
    order = fold(
        [
            created(),
            event("working", seq=2),
            event("input-required", seq=3, message="which branch strategy?"),
            event("answered", ORCH, 4, message="feat/x, off main"),
        ]
    )
    assert order.state == "working"
    assert order.is_open


def test_the_question_and_the_answer_are_two_separate_messages():
    order = fold(
        [
            created(),
            event("input-required", seq=2, message="which branch strategy?"),
            event("answered", ORCH, 3, message="feat/x, off main"),
        ]
    )
    assert message_from(order, WORKER) == "which branch strategy?"
    assert message_from(order, ORCH) == "feat/x, off main"


def test_the_order_text_is_never_returned_as_the_workers_answer():
    """The description rides on `created`, not in a message -- the trap is gone."""
    order = fold([created(), event("completed", seq=2)])
    assert message_from(order, WORKER) is None


def test_the_newest_message_of_an_actor_wins():
    order = fold(
        [
            created(),
            event("failed", seq=2, message="first attempt"),
            event("working", seq=3),
            event("completed", seq=4, message="second attempt, green"),
        ]
    )
    assert message_from(order, WORKER) == "second attempt, green"


def test_an_unknown_kind_survives_verbatim_and_is_never_terminal():
    """A format change must run into the timeout, not into a false success."""
    order = fold([created(), event("quantum-entangled", seq=2)])
    assert order.state == "quantum-entangled"
    assert not is_terminal(order.state)
    assert order.is_open


def test_the_predecessor_is_kept_as_given():
    assert fold([created(after="o-2")]).after == "o-2"
    assert fold([created()]).after is None


def test_folding_nothing_yields_an_order_with_no_state():
    """A task id that has no events must not look like a fresh order."""
    order = fold([])
    assert order.state == ""
    assert not order.is_open


def test_newest_open_takes_the_first_open_order_for_this_agent():
    mine_done = Order(id="o-1", to_agent=WORKER, state="completed")
    theirs = Order(id="o-2", to_agent="reviewer-feat-x", state="created")
    mine_open = Order(id="o-3", to_agent=WORKER, state="created")
    assert newest_open([mine_open, theirs, mine_done], WORKER).id == "o-3"
    assert newest_open([mine_done, theirs], WORKER) is None


def test_an_order_is_immutable():
    """`frozen=True` is load-bearing, and nothing pinned it.

    fold() REPLACES: `_apply()` builds a new Order per event and never
    writes a field. The moment one of them is assignable, a caller can edit
    a folded order in place -- and the state would stop being the fold of
    the log and become a field again, which is the one thing this design
    rules out. test_tasks.py::test_task_is_immutable guarded the store this
    replaced; it had no successor until here.
    """
    order = fold([created()])
    with pytest.raises(FrozenInstanceError):
        order.state = "completed"


def test_every_kind_of_the_design_is_known():
    assert set(EVENT_KINDS) == {
        "created", "working", "input-required", "answered",
        "completed", "failed", "canceled",
    }
