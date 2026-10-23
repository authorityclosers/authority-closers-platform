"""The gold checkpoint's sampling rule (orchestrator, 21 Oct 2026). Fictional calls only."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from ac_platform.conversation_intelligence import gold_checkpoint
from ac_platform.conversation_intelligence.gold_checkpoint import (
    EVERY_CALL,
    Candidate,
    Checkpoint,
    choose,
    features,
    progress,
)

START = datetime(2026, 10, 21, 10, tzinfo=UTC)
# The first checkpoint's sample (fresh-1, 21 Oct): the sampling rule's tests use it.
BASE: dict[str, object] = {
    "name": "fresh-1",
    "since": "2026-10-21T09:51:31Z",
    "mode": "brain4_blind",
    "daily": 5,
    "total": 25,
    "assign_from_hour": 8,
    "minutes": (10, 30),
    "workspaces": "company",
    "at_least": {"price": 15, "objection": 12, "decision": 12},
    "mix": {"first_call": 15, "follow_up": 10, "won": 5, "lost": 5, "pending": 5},
    "salespeople": {"at_least": 3, "at_most_each": 10},
}


def plan(**changes: object) -> Checkpoint:
    data = dict(BASE)
    data.update(changes)
    if "daily" not in changes:
        data["daily"] = min(data["daily"], data["total"])
    return Checkpoint.model_validate(data)


def call(n: int, person: str, *found: str) -> Candidate:
    return Candidate(f"call-{n:03d}", person, START + timedelta(minutes=n), frozenset(found))


def test_the_checkpoint_in_force_is_the_report_review() -> None:
    current = gold_checkpoint.current()
    assert (current.name, current.mode, current.daily) == ("review-1", "report", 5)
    assert current.minutes == (10, 30)
    # Our own workspaces until the owner approves customer calls.
    assert current.workspaces == "company"
    assert current.at_least == {} and current.mix == {}
    # The first sample stays valid, and Gate 3 is one number away.
    assert plan().mode == "brain4_blind" and plan(total=50).total == 50


@pytest.mark.parametrize(
    "change",
    [
        {"minutes": (30, 10)},
        {"at_least": {"invented": 1}},
        {"at_least": {"price": 99}},
        {"daily": 30},
        {"since": "2026-10-21T09:51:31"},
        {"mode": "graded"},
    ],
)
def test_a_wrong_checkpoint_is_refused(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        plan(**change)


def test_features_come_from_saved_facts_only() -> None:
    outcome = {
        "stages": ["Discovery", "Negotiation"],
        "objections": [{"text": "Too costly", "handled": False}],
        "next_steps": [],
    }
    found = features(
        outcome,
        {"authority": {"state": "concern"}},
        sequence="follow_up",
        recorded_outcome="no_decision",
    )
    assert found == {"price", "objection", "decision", "follow_up", "pending"}
    assert features({"stages": ["Initial Contact"]}, None) == frozenset()
    assert (
        features(None, "not a block", sequence="unknown", recorded_outcome="maybe") == frozenset()
    )
    assert features({"next_steps": [{"text": "Send the plan"}]}, {}) == {"decision"}


def test_choose_respects_daily_room_total_and_salesperson_cap() -> None:
    one = {"at_least": 1, "at_most_each": 10}
    small = plan(total=4, at_least={}, mix={}, salespeople=one)
    pool = [call(n, "rep-a") for n in range(10)]
    assert [c.recording_id for c in choose(small, [], pool, 3)] == [
        "call-000",
        "call-001",
        "call-002",
    ]
    capped = plan(total=20, at_least={}, mix={}, salespeople={"at_least": 1, "at_most_each": 2})
    assert len(choose(capped, [], pool, 5)) == 2
    # With three salespeople wanted, the last places wait for new ones.
    assert len(choose(plan(total=4, at_least={}, mix={}), [], pool, 4)) == 2
    already = [call(100 + n, "rep-b") for n in range(4)]
    assert choose(small, already, pool, 5) == []


def test_choose_prefers_needed_counts_and_keeps_room_for_them() -> None:
    tight = plan(total=3, at_least={"price": 3}, mix={})
    pool = [call(1, "rep-a"), call(2, "rep-b", "price"), call(3, "rep-c", "price")]
    chosen = choose(tight, [], pool, 3)
    # Every remaining place is needed for price, so the call without it waits.
    assert [c.recording_id for c in chosen] == ["call-002", "call-003"]
    soft = plan(total=10, at_least={"objection": 2}, mix={"won": 1})
    pool = [call(1, "rep-a"), call(2, "rep-a", "won"), call(3, "rep-a", "objection")]
    assert [c.recording_id for c in choose(soft, [], pool, 1)] == ["call-003"]


def test_choose_brings_in_new_salespeople_when_places_run_out() -> None:
    few = plan(total=3, at_least={}, mix={})
    pool = [call(1, "rep-a"), call(2, "rep-a"), call(3, "rep-a"), call(4, "rep-b")]
    chosen = choose(few, [], pool, 3)
    assert {c.salesperson for c in chosen} == {"rep-a", "rep-b"}
    assert len(chosen) == 2  # the third place is kept for a third salesperson


def test_every_call_is_the_reader_before_checkpoints() -> None:
    assert (EVERY_CALL.mode, EVERY_CALL.workspaces, EVERY_CALL.minutes) == ("lines", "any", None)
    pool = [call(n, f"rep-{n}") for n in range(5)]
    assert len(choose(EVERY_CALL, [], pool, 50)) == 5


def test_progress_is_counts_only() -> None:
    picked = [call(1, "rep-a", "price"), call(2, "rep-b", "price", "won")]
    report = progress(plan(), picked)
    assert report["chosen"] == 2 and report["salespeople"] == 2
    assert report["at_least"]["price"] == {"want": 15, "have": 2}
    assert report["mix"]["won"] == {"want": 5, "have": 1}
    assert "call-001" not in str(report)
