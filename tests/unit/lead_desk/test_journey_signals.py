"""Stage suggestions from what calls and notes say: offers only, never moves."""

from __future__ import annotations

from collections import Counter

from ac_platform.lead_desk.journey import signals
from ac_platform.lead_desk.journey.model import Journey, default_journey, from_template


def test_each_fact_points_at_a_sales_moment() -> None:
    assert signals.milestone_of("outcome.call_outcome", {"value": "meeting_scheduled"}, None) == (
        "appointment_booked"
    )
    assert signals.milestone_of("outcome.call_outcome", {"value": "no_sale"}, None) is None
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


def test_a_moment_a_stage_already_covers_is_not_offered() -> None:
    real_estate = Journey(1, "real_estate", from_template("real_estate", default_journey(), {}))
    counts = Counter({"appointment_booked": 20, "negotiation": 5})
    assert signals.business_suggestions(counts, {}, real_estate) == []
