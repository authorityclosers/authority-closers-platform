"""Company insight from the analysis: wordings by calls, skill scores weakest first."""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from ac_platform.conversation_intelligence.analysis_insights import (
    _top,
    call_average,
    funnel_conversion,
    people,
    skill_scores,
    skill_weeks,
    week_of,
    weekly,
    weeks_between,
)
from ac_platform.lead_desk.journey.model import default_journey


def test_wordings_rank_by_how_many_calls_said_them() -> None:
    one, two, three = uuid4(), uuid4(), uuid4()
    rows = [
        (one, "Price is too high."),
        (one, "price is too  high"),  # same call, same wording: counted once
        (two, "Price is too high"),
        (three, "Need to ask my partner"),
        (three, "  "),  # empty wordings are skipped
    ]
    assert _top(rows) == [
        {"text": "Price is too high.", "calls": 2},
        {"text": "Need to ask my partner", "calls": 1},
    ]


def test_skill_scores_average_each_skill_and_count_needs_work() -> None:
    payloads = [
        {
            "pointers": [
                {"label": "Agenda", "status": "needs_improvement", "score": 40},
                {"label": "Listening", "status": "good", "score": 80},
            ]
        },
        {
            "pointers": [
                {"label": "Agenda", "status": "good", "score": 70},
                {"label": "Listening", "status": "good", "score": 90},
                {"label": "Broken", "status": "good", "score": True},
                "not a pointer",
            ]
        },
        None,
    ]
    assert skill_scores(payloads) == [
        {"label": "Agenda", "calls": 2, "average": 55, "needs_work_share": 0.5},
        {"label": "Listening", "calls": 2, "average": 85, "needs_work_share": 0.0},
    ]


# Monday 12 Oct 2026, 10:00 India time.
MONDAY = datetime(2026, 10, 12, 4, 30, tzinfo=UTC)


def review(*pointers: tuple[str, int, str]) -> dict[str, object]:
    return {
        "pointers": [
            {"label": label, "score": score, "status": status} for label, score, status in pointers
        ]
    }


def test_weeks_start_on_monday_in_india_time() -> None:
    # Sunday 23:00 UTC is already Monday in India.
    assert week_of(datetime(2026, 10, 18, 23, 0, tzinfo=UTC)) == date(2026, 10, 19)
    assert week_of(MONDAY + timedelta(days=6)) == date(2026, 10, 12)
    assert weeks_between(MONDAY, MONDAY + timedelta(days=15)) == [
        date(2026, 10, 12),
        date(2026, 10, 19),
        date(2026, 10, 26),
    ]
    assert call_average(review(("A", 40, "needs_improvement"), ("B", 80, "good"))) == 60
    assert call_average(None) is None


def test_weekly_counts_calls_read_and_scored_with_the_mean_score() -> None:
    one, two, three = uuid4(), uuid4(), uuid4()
    weeks = weeks_between(MONDAY, MONDAY + timedelta(days=7))
    calls = [(one, MONDAY), (two, MONDAY + timedelta(days=1)), (three, MONDAY + timedelta(days=7))]
    reviews = {one: review(("A", 40, "x")), two: review(("A", 60, "good"), ("B", 100, "good"))}
    assert weekly(weeks, calls, {one, three}, reviews) == [
        {"week": "2026-10-12", "calls": 2, "analysed": 1, "scored": 2, "average": 60},
        {"week": "2026-10-19", "calls": 1, "analysed": 1, "scored": 0, "average": None},
    ]
    by_skill = skill_weeks(weeks, calls, reviews, ["A", "B", "Unseen"])
    assert [item["label"] for item in by_skill] == ["A", "B"]
    assert by_skill[0]["weeks"] == [
        {"week": "2026-10-12", "average": 50, "calls": 2},
        {"week": "2026-10-19", "average": None, "calls": 0},
    ]


def test_people_show_each_sellers_calls_scores_and_weakest_skill() -> None:
    asha, ravi = uuid4(), uuid4()
    one, two, three = uuid4(), uuid4(), uuid4()
    weeks = weeks_between(MONDAY, MONDAY + timedelta(days=7))
    calls = [
        (one, MONDAY, asha),
        (two, MONDAY + timedelta(days=8), asha),
        (three, MONDAY, ravi),
    ]
    reviews = {
        one: review(("Agenda", 30, "needs_improvement"), ("Listening", 90, "good")),
        two: review(("Agenda", 50, "needs_improvement"), ("Listening", 70, "good")),
    }
    found = people(weeks, calls, {asha: "Asha (fictional)"}, {one, two, three}, reviews)
    assert [row["name"] for row in found] == ["Asha (fictional)", "Unknown"]
    asha_row = found[0]
    assert asha_row["calls"] == 2 and asha_row["scored"] == 2 and asha_row["average"] == 60
    assert asha_row["needs_work_share"] == 0.5
    assert asha_row["weakest"] == {"label": "Agenda", "average": 40, "calls": 2}
    assert asha_row["weeks"] == [1, 1]
    assert found[1]["average"] is None and found[1]["needs_work_share"] is None
    assert found[1]["weakest"] is None


def test_the_funnel_counts_the_furthest_stage_each_lead_reached() -> None:
    journey = default_journey()
    keys = [stage.key for stage in journey.funnel()]
    first, second, third = uuid4(), uuid4(), uuid4()
    leads = [
        (first, "won", None),  # won now
        (second, "lost", None),  # lost now, but was interested before
        (third, "new", None),
    ]
    events = [
        (second, "result", {"stage": "interested", "from_stage": "follow_up"}),
        (uuid4(), "result", {"stage": "won", "from_stage": "new"}),  # not in the window
    ]
    found = funnel_conversion(journey, leads, events)
    assert found["leads"] == 3 and found["lost"] == 1 and found["unreachable"] == 0
    reached = {row["key"]: row["reached"] for row in found["funnel"]}
    assert reached[keys[0]] == 3  # every lead is a lead
    interested = journey.resolve("interested", None)
    won = journey.resolve("won", None)
    assert interested is not None and won is not None
    assert reached[interested.key] == 2 and reached[won.key] == 1
    assert found["funnel"][0]["from_previous"] is None
    assert found["funnel"][0]["share"] == 1.0
    empty = funnel_conversion(journey, [], [])
    assert empty["leads"] == 0 and all(row["share"] is None for row in empty["funnel"])
