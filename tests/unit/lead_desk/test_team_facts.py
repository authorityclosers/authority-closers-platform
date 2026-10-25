"""A seller's activity as target facts (team engine, docs/product/lead-desk/team-engine.md,
section 2): a call and its outcome are one call, a talked call without an outcome is still
a connect, and follow-ups and meetings come from the right events."""

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
        # Three hours later on the same lead: a new call.
        (lead, "result", {"connected": False}, T0 + timedelta(hours=3)),
        (other, "call", {"via": "phone", "connected": False}, T0),
    ]
    facts = facts_from(events)
    assert count(facts, "calls") == 3
    assert count(facts, "connects") == 1
    assert count(facts, "follow_ups") == 1


def test_a_talked_call_without_an_outcome_is_still_a_connect() -> None:
    facts = facts_from([(uuid4(), "call", {"via": "phone", "connected": True}, T0)])
    assert (count(facts, "calls"), count(facts, "connects")) == (1, 1)


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
    assert count(facts, "calls") == 1


def test_nudges_are_off_unless_the_workspace_turns_them_on() -> None:
    seller = uuid4()
    assert not nudges_on(None, seller)
    assert nudges_on({"team": {"nudges": True}}, seller)
    assert not nudges_on({"team": {"nudges": True, "nudges_off_for": [str(seller)]}}, seller)
