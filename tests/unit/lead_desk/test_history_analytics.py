"""Owner Analytics over old leads kept as history (owner, 2 Nov 2026): a typed city reads as
one place or is counted as not placed, never guessed; a campaign's key ignores spaces and
case, and a campaign of old leads only reads Ended until the owner says otherwise; in All
time the report counts old leads by campaign without making up a first-call time, an
overdue or a missing next step for them."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from ac_platform.lead_desk import reports
from ac_platform.lead_desk.campaigns import campaign_key, status_of, statuses
from ac_platform.lead_desk.journey.model import journey_of
from ac_platform.lead_desk.journey.templates import LEGACY_NINE
from ac_platform.lead_desk.places import place, top_cities
from ac_platform.lead_desk.reports import LeadFact, Moved

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
SELLER = uuid4()


def test_a_typed_city_reads_as_one_place_or_none() -> None:
    assert place("Poona") == "Pune"
    assert place("  PUNE city, Maharashtra ") == "Pune"
    assert place("पुणे") == "Pune"
    assert place("Hadapsar") == "Pune"
    assert place("Baramati, Pune") == "Baramati"
    assert place("Navi Mumbai") == "Navi Mumbai"
    assert place("Bombay") == "Mumbai"
    # Two metros, two towns, or no known place: not placed.
    assert place("Pune Mumbai") is None
    assert place("Baramati Karad") is None
    assert place("9876543210") is None
    assert place("") is None


def test_top_cities_count_placed_and_unplaced_apart() -> None:
    found, unplaced = top_cities(
        ["Pune", "poona", "Mumbai", "Somewhere Unknown", "", None, "Nashik", "nasik"], limit=2
    )
    assert found == [("Nashik", 2), ("Pune", 2)]
    assert unplaced == 1


def test_campaign_keys_and_statuses() -> None:
    assert campaign_key("meta", "  Rooftop   Offer ") == "meta:rooftop offer"
    assert campaign_key("csv", None) == "csv"
    said = statuses(
        {"campaigns": {"meta:a": {"status": "paused"}, "meta:b": {"status": "gone"}, "x": 3}}
    )
    assert said == {"meta:a": "paused"}
    assert status_of(said, "meta:a", history_only=True) == "paused"
    assert status_of(said, "csv:old", history_only=True) == "ended"
    assert status_of(said, "meta:new", history_only=False) == "live"
    assert statuses({}) == {}


def test_all_time_counts_old_leads_by_campaign_without_made_up_times() -> None:
    journey = journey_of(LEGACY_NINE)

    def lead(stage: str, *, history: bool, campaign: str, city: str | None) -> LeadFact:
        return LeadFact(
            uuid4(),
            stage,
            stage,
            SELLER,
            "csv" if history else "meta",
            "Fictional Old CRM" if history else None,
            NOW - timedelta(days=1 if history else 2),
            None,
            None,
            NOW - timedelta(days=150) if history else None,
            False,
            history,
            campaign,
            city,
        )

    won = lead("won", history=True, campaign="Fictional Old CRM", city="Poona")
    keen = lead("interested", history=True, campaign="Fictional Old CRM", city="Kolhapur")
    live = lead("new", history=False, campaign="Fictional Rooftop", city=None)

    def move(fact: LeadFact, key: str) -> Moved:
        stage = journey.stage_for(key)
        assert stage is not None
        # Brought in yesterday: the move is dated the day it was brought in.
        return Moved(fact.lead_id, NOW - timedelta(days=1), stage.milestone, stage.kind, spoke=True)

    report = reports.compute(
        journey,
        [won, keen, live],
        [move(won, "won"), move(keen, "interested")],
        [],
        now=NOW,
        days=reports.ALL_TIME,
    )
    old = report.campaigns[campaign_key("csv", "Fictional Old CRM")]
    assert (old.numbers.leads, old.numbers.history, old.numbers.won, old.numbers.interested) == (
        2,
        2,
        1,
        2,
    )
    assert old.numbers.first_minutes == []
    assert old.numbers.last_at == NOW - timedelta(days=150)
    assert report.campaigns[campaign_key("meta", "Fictional Rooftop")].numbers.leads == 1
    assert report.history_leads == 2
    # An interested old lead with no next step is history, not a lapse.
    assert report.no_next == 0
    assert report.first_connect_minutes is None
    assert report.cities == [("Kolhapur", 1), ("Pune", 1)]
    assert report.cities_unplaced == 0
