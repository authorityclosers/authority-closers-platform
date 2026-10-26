"""Lead OS reports (spec section 9): each lead counted once, conversions from history with
skipped stages passed, Junk out of every conversion, Lost reasons, overdue and no next step;
a Lost lead that was never a deal (junk, or merged into another lead) counts as Junk."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from ac_platform.lead_desk import reports
from ac_platform.lead_desk.journey.model import (
    Journey,
    default_journey,
    from_template,
    journey_of,
)
from ac_platform.lead_desk.journey.templates import LEGACY_NINE
from ac_platform.lead_desk.reports import LeadFact, Moved
from ac_platform.lead_desk.vocabulary import MERGED_DUPLICATE, NOT_A_LEAD

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
SELLER = uuid4()


def nine() -> Journey:
    return journey_of(LEGACY_NINE)


def eight() -> Journey:
    return Journey(
        1, "inside_sales_demos", from_template("inside_sales_demos", default_journey(), {})
    )


def fact(
    stage: str,
    step: str | None,
    *,
    days_ago: float = 2,
    next_in_hours: float | None = None,
    reason: str | None = None,
    source: str = "meta",
) -> LeadFact:
    return LeadFact(
        uuid4(),
        stage,
        step,
        SELLER,
        source,
        None,
        NOW - timedelta(days=days_ago),
        NOW + timedelta(hours=next_in_hours) if next_in_hours is not None else None,
        reason,
    )


def moved(lead: LeadFact, hours_after: float, journey: Journey, key: str, **extra: object) -> Moved:
    stage = journey.stage_for(key)
    assert stage is not None
    return Moved(
        lead.lead_id,
        lead.created_at + timedelta(hours=hours_after),
        stage.milestone,
        stage.kind,
        spoke=stage.milestone in reports.SPOKEN,
        **extra,  # type: ignore[arg-type]
    )


def world() -> tuple[Journey, dict[str, LeadFact], list[Moved]]:
    journey = nine()
    leads = {
        "new": fact("new", None),
        "nc": fact("not_connected", None),
        "interested": fact("interested", "interested", next_in_hours=4),
        "won": fact("won", "won"),
        "junk": fact("junk", "junk", reason="fake"),
        "old_lost": fact("lost", "lost", days_ago=100, reason="price"),
        "skipped": fact("won", "won", days_ago=3),
    }
    history = [
        moved(leads["nc"], 1, journey, "not_connected"),
        moved(leads["interested"], 1, journey, "not_connected"),
        moved(leads["interested"], 5, journey, "interested"),
        moved(leads["won"], 2, journey, "interested"),
        moved(leads["won"], 3, journey, "meeting_scheduled"),
        moved(leads["won"], 20, journey, "demo_completed"),
        moved(leads["won"], 30, journey, "won"),
        # Junk after interest: out of every conversion.
        moved(leads["junk"], 1, journey, "interested"),
        moved(leads["junk"], 2, journey, "junk"),
        moved(leads["old_lost"], 1, journey, "lost", reason="price"),
        # Straight to Won (an import): every step before counts as passed.
        moved(leads["skipped"], 1, journey, "won"),
    ]
    return journey, leads, history


def test_each_lead_is_counted_once_and_the_stages_add_up() -> None:
    journey, leads, history = world()
    report = reports.compute(journey, list(leads.values()), history, [], now=NOW, days=30)
    assert report.total == 7
    assert sum(count for _, count in report.by_stage) == 7
    counts = {stage.key: count for stage, count in report.by_stage}
    assert counts["won"] == 2 and counts["junk"] == 1 and counts["lost"] == 1
    assert report.groups == {"active": 3, "won": 2, "lost": 1, "junk": 1}


def test_conversions_come_from_history_and_leave_junk_out() -> None:
    journey, leads, history = world()
    report = reports.compute(journey, list(leads.values()), history, [], now=NOW, days=30)
    # New → first conversation: leads that came in this month, Junk left out.
    assert (report.first_connect.entered, report.first_connect.passed) == (5, 3)
    steps = {step.key: (step.entered, step.passed) for step in report.steps}
    # The skipped lead passed every step; the Junk lead is in none.
    assert steps["interested_to_meeting"] == (3, 2)
    assert steps["meeting_to_held"] == (2, 2)
    assert steps["held_to_won"] == (2, 2)


def test_lost_reasons_junk_overdue_and_no_next_step() -> None:
    journey, leads, history = world()
    report = reports.compute(
        journey,
        list(leads.values()),
        history,
        [],
        now=NOW,
        days=30,
        reasons=reports.reason_words(journey),
    )
    assert report.lost_now == [("Price or budget", 1)]
    assert report.lost_moves == []  # the Lost move was 100 days ago
    assert (report.junk_now, report.junk_moves) == (1, 1)
    # The new lead is late from its arrival; Not Connected has no next step.
    assert report.overdue == 1 and report.no_next == 1
    meta = report.sources["meta"]
    assert (meta.created, meta.junk, meta.won) == (6, 1, 2)


def test_a_reopened_lead_counts_each_step_once() -> None:
    journey = nine()
    lead = fact("interested", "interested", next_in_hours=2)
    history = [
        moved(lead, 1, journey, "interested"),
        moved(lead, 2, journey, "lost", reason="not_now"),
        moved(lead, 40, journey, "interested"),
    ]
    report = reports.compute(journey, [lead], history, [], now=NOW, days=30)
    steps = {step.key: (step.entered, step.passed) for step in report.steps}
    assert steps["interested_to_meeting"] == (1, 0)


def test_the_meeting_show_rate_counts_meetings_that_were_due() -> None:
    journey = nine()
    lead = fact("demo_completed", "demo_completed")
    meetings: list[tuple[UUID, str, datetime]] = [
        (lead.lead_id, "done", NOW - timedelta(days=1)),
        (lead.lead_id, "missed", NOW - timedelta(days=2)),
        (lead.lead_id, "scheduled", NOW + timedelta(days=1)),
    ]
    report = reports.compute(journey, [lead], [], meetings, now=NOW, days=30)
    assert report.show_rate == 0.5


def test_history_reads_v2_moves_and_legacy_results() -> None:
    journey = nine()
    lead_id = uuid4()
    at = NOW - timedelta(days=1)
    rows = [
        (
            lead_id,
            "result",
            {"connected": False, "stage": "not_connected", "from_stage": "new"},
            at,
        ),
        (
            lead_id,
            "stage",
            {"v": 2, "to_kind": "interested", "to_key": "meeting_scheduled", "stage": "interested"},
            at + timedelta(hours=1),
        ),
        (
            lead_id,
            "result",
            {"connected": True, "stage": "interested", "from_stage": "interested"},
            at + timedelta(hours=2),
        ),
        (lead_id, "note", {"note": "hello"}, at + timedelta(hours=3)),
        # The stage list changed under the lead (the template's map): not progress.
        (
            lead_id,
            "stage",
            {"v": 2, "source": "template", "to_kind": "won", "to_key": "won"},
            at + timedelta(hours=4),
        ),
    ]
    found = reports.history(journey, rows)
    assert [item.milestone for item in found] == ["unreachable", "appointment_booked", None]
    assert [item.spoke for item in found] == [False, True, True]


# Orchestrator, 25 Oct 2026: merges and junk never look like lost deals.
def test_lost_leads_that_were_never_deals_count_as_junk() -> None:
    journey = eight()
    leads = {
        "real": fact("lost", "lost", reason="price"),
        "junk": fact("lost", "lost", reason=NOT_A_LEAD),
        "merged": fact("lost", "lost", reason=MERGED_DUPLICATE),
        "won": fact("won", "won"),
    }
    history = [
        moved(leads["real"], 1, journey, "lost", reason="price"),
        moved(leads["junk"], 1, journey, "lost", reason=NOT_A_LEAD),
        moved(leads["merged"], 1, journey, "lost", reason=MERGED_DUPLICATE),
        moved(leads["won"], 1, journey, "won"),
    ]
    report = reports.compute(
        journey,
        list(leads.values()),
        history,
        [],
        now=NOW,
        days=30,
        reasons=reports.reason_words(journey),
    )
    # All three sit in the Lost column; only the real one is a lost deal.
    assert {stage.key: count for stage, count in report.by_stage}["lost"] == 3
    assert report.groups == {"active": 0, "won": 1, "lost": 1, "junk": 2}
    assert report.lost_now == [("Price or budget", 1)]
    assert report.lost_moves == [("Price or budget", 1)]
    assert (report.junk_now, report.junk_moves) == (2, 2)
    assert report.sources["meta"].junk == 2
