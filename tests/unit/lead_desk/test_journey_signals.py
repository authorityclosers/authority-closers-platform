"""Stage suggestions from what calls and notes say: offers only, never moves."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from ac_platform.lead_desk.journey import signals
from ac_platform.lead_desk.journey.model import Journey, Stage, default_journey, from_template


def test_each_fact_points_at_a_sales_moment() -> None:
    # The outcome as the call data engine stores it (call_data/values.py: {"enum": ...}).
    assert signals.milestone_of("outcome.call_outcome", {"enum": "meeting_scheduled"}, None) == (
        "appointment_booked"
    )
    assert signals.milestone_of("outcome.call_outcome", {"enum": "deal_closed"}, None) == "won"
    assert signals.milestone_of("outcome.call_outcome", {"enum": "no_sale"}, None) is None
    assert signals.milestone_of("outcome.call_outcome", {"value": "deal_closed"}, None) == "won"
    assert signals.milestone_of("commitment.next_step", None, "Site visit on Saturday 11am") == (
        "appointment_booked"
    )
    assert signals.milestone_of("note", None, "Sent the quotation by WhatsApp") == "proposal"
    assert signals.milestone_of("note", None, "") is None
    assert signals.milestone_of("note", None, "Not interested any more") is None


def test_names_come_from_the_words_heard() -> None:
    assert signals.term_of("Will do a site visit and a demo") == "site visit"
    assert signals.label_for("appointment_booked", "site visit") == "Site visit booked"
    assert signals.label_for("appointment_done", "test drive") == "Test drive done"
    assert signals.label_for("appointment_booked", None) == "Meeting booked"
    assert signals.label_for("proposal", None) == "Quote sent"


def test_moments_heard_often_and_not_covered_are_offered() -> None:
    simple = Journey(1, "simple", default_journey().stages)
    counts = Counter({"appointment_booked": 12, "proposal": 4, "application": 2, "won": 9})
    terms = {"appointment_booked": Counter({"demo": 8, "meeting": 4})}
    offered = signals.business_suggestions(counts, terms, simple)
    assert [(item["label"], item["kind"]) for item in offered] == [
        ("Demo booked", "interested"),
        ("Quote sent", "interested"),
    ]
    assert offered[0]["workflow"] == "heard in 12 calls and notes"
    assert offered[0]["ref"] == "calls:appointment_booked"


NINE = Journey(
    1,
    "inside_sales",
    (
        Stage("new", "Unworked", "new", "lead"),
        Stage("open_leads", "Open Leads", "follow_up", "contacted"),
        Stage("interested", "Interested", "interested", "qualified"),
        Stage("meeting_scheduled", "Meeting Scheduled", "interested", "appointment_booked"),
        Stage("won", "Won", "won", "won"),
        Stage("lost", "Closed / Lost", "lost", "lost"),
    ),
)
AT = datetime(2026, 10, 30, 8, 0, tzinfo=UTC)


def _offer(rows: list[tuple[str, object, str, datetime, object]]) -> str | None:
    found = signals.suggest_from(rows, NINE.resolve("new", "new"), NINE)
    return found["step"] if found else None


def test_the_calls_outcome_offers_the_stage_whatever_the_next_step_says() -> None:
    call = uuid4()
    closed = [  # a negotiation that closed (simulation lab S04)
        ("commitment.next_step", {"text": "Invoice today"}, "Send the invoice today", AT, call),
        ("outcome.call_outcome", {"enum": "deal_closed"}, "Deal closed", AT, call),
    ]
    assert _offer(closed) == "won"
    booked = [  # a proposal meeting booked (S09): no meeting word in the next step
        ("commitment.next_step", {}, "Proposal presentation at the Pune office", AT, call),
        ("outcome.call_outcome", {"enum": "meeting_scheduled"}, "Meeting scheduled", AT, call),
    ]
    assert _offer(booked) == "meeting_scheduled"


def test_a_call_that_ended_in_a_no_offers_nothing_that_reopens_the_lead() -> None:
    call = uuid4()
    lost = [  # signed with another firm, a check-in in March (S30)
        ("commitment.next_step", {}, "Call the prospect in March to check in", AT, call),
        ("outcome.call_outcome", {"enum": "no_sale"}, "No sale", AT, call),
    ]
    assert _offer(lost) is None
    # An older call's no does not hold back a newer call that went well.
    newer = uuid4()
    later = AT + timedelta(days=2)
    rows = [("outcome.call_outcome", {"enum": "meeting_scheduled"}, "Meeting", later, newer)]
    assert _offer(rows + lost) == "meeting_scheduled"


def test_a_moment_a_stage_already_covers_is_not_offered() -> None:
    real_estate = Journey(1, "real_estate", from_template("real_estate", default_journey(), {}))
    counts = Counter({"appointment_booked": 20, "negotiation": 5})
    assert signals.business_suggestions(counts, {}, real_estate) == []
