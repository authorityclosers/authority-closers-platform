"""A seller's activity as target facts (team engine, docs/product/lead-desk/team-engine.md,
section 2): a call and its outcome are one call, calls and connects count as Home counts
them (Dipak's honest numbers: an answer with no call is no call, and only the phone's own
evidence connects), and follow-ups and meetings come from the right events."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from ac_platform.lead_desk.targets import count
from ac_platform.lead_desk.team import facts_from, nudges_on

T0 = datetime(2026, 10, 28, 6, 0, tzinfo=UTC)


def test_a_call_and_its_outcome_are_one_call() -> None:
    lead, other = uuid4(), uuid4()
    events = [
        (lead, "call", {"via": "phone", "connected": True}, T0),
        (
            lead,
            "result",
            {"connected": True, "was_due": True},
            T0 + timedelta(minutes=8),
        ),
        # Three hours later on the same lead, an answer with no call of its own: no call.
        (lead, "result", {"connected": False}, T0 + timedelta(hours=3)),
        (other, "call", {"via": "phone", "connected": False}, T0),
    ]
    facts = facts_from(events)
    assert count(facts, "calls") == 2
    assert count(facts, "connects") == 1
    assert count(facts, "follow_ups") == 1


def test_a_talked_call_without_an_outcome_is_still_a_connect() -> None:
    facts = facts_from([(uuid4(), "call", {"via": "phone", "connected": True}, T0)])
    assert (count(facts, "calls"), count(facts, "connects")) == (1, 1)


def test_calls_and_connects_count_as_home_counts_them() -> None:
    """Bug report #170, 4 Nov 2026: the seller's targets read 29 calls and 11 connects beside
    Home's 15 and 12. A call in or a missed call is no call out; a Call-button dial connects
    only on the seconds its phone's call log matched (phone_seconds, read beside it), never
    on its time away or the seller's "We talked"."""
    lead = uuid4()
    away = {"estimated": True, "duration_seconds": 40}
    facts = facts_from(
        [
            (lead, "call", away, T0),
            (lead, "result", {"connected": True}, T0 + timedelta(minutes=1)),
            (lead, "call", {**away, "phone_seconds": 35}, T0 + timedelta(minutes=10)),
            (lead, "call", {"via": "phone", "direction": "incoming", "duration_seconds": 60}, T0),
            (lead, "call", {"via": "phone", "direction": "missed"}, T0),
        ]
    )
    assert (count(facts, "calls"), count(facts, "connects")) == (2, 1)


def test_follow_ups_and_meetings_come_from_their_events() -> None:
    lead = uuid4()
    facts = facts_from(
        [
            # Booking a follow-up is not doing one.
            (lead, "scheduled", {"follow_up_at": "2026-10-29T05:00:00+00:00"}, T0),
            (lead, "result", {"connected": True, "was_due": False}, T0),
            (lead, "task", {"action": "done"}, T0),
            (lead, "task", {"action": "snoozed"}, T0),
            (lead, "meeting", {"action": "scheduled"}, T0),
            (lead, "meeting", {"action": "rescheduled"}, T0),
        ]
    )
    assert count(facts, "follow_ups") == 1
    assert count(facts, "meetings") == 1
    # The saved answer had no call of its own.
    assert count(facts, "calls") == 0


def test_nudges_are_on_unless_someone_turned_them_off() -> None:
    # Owner, 26 Oct 2026 (report #23): "of course nudge should be already on".
    seller = uuid4()
    assert nudges_on(None, seller)
    assert nudges_on({"team": {}}, seller)
    assert nudges_on({"team": {"nudges": True}}, seller)
    assert not nudges_on({"team": {"nudges": False}}, seller)
    assert not nudges_on({"team": {"nudges_off_for": [str(seller)]}}, seller)
