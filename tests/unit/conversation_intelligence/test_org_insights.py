"""The company view (AUT-1798): extraction from one report, windows and filters.

The projection and aggregates are proved on PostgreSQL in
tests/database/test_org_insights_postgresql.py.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from ac_platform.conversation_intelligence.insight_models import SKILL_ORDER
from ac_platform.conversation_intelligence.org_insights import (
    InsightFilters,
    objection_kinds,
    report_language,
    report_outcome,
    seller_talk_share,
    skill_states,
)
from ac_platform.http.conversation_insights import insight_filters

NOW = datetime(2026, 10, 11, 9, 0, tzinfo=UTC)


def dimensions(states: dict[str, str], *, field: str = "call_state") -> list[dict[str, Any]]:
    return [{"dimension_id": skill, field: states.get(skill, "observed")} for skill in SKILL_ORDER]


def report(outcome: str, states: dict[str, str], objections: list[str]) -> dict[str, Any]:
    return {
        "dimensions": dimensions(states),
        "overview": {"outcome": {"kind": outcome}},
        "call_map": {"objections": [{"kind": kind} for kind in objections]},
    }


def test_skill_states_read_call_state_then_status_and_need_all_eight() -> None:
    states = dimensions(
        {"qualification": "needs_attention", "human_connection_trust": "strongly_demonstrated"}
    )
    assert skill_states(states) == "SONOOOOO"
    legacy = dimensions({"discovery_deep_understanding": "partial"}, field="status")
    assert skill_states(legacy) == "ONOOOOOO"
    assert skill_states(states[:7]) is None
    assert skill_states("not a list") is None
    unknown = dimensions({"communication_tonality": "insufficient_evidence"})
    unknown[0] = {"dimension_id": "human_connection_trust", "call_state": "not_applicable"}
    assert skill_states(unknown) == "-OOOOOOU"


def test_outcomes_prefer_the_overview_then_the_call_map() -> None:
    assert report_outcome({"overview": {"outcome": {"kind": "closed"}}}) == "won"
    assert report_outcome({"overview": {"outcome": {"kind": "future_date"}}}) == "booked"
    assert report_outcome({"overview": {"outcome": {"kind": "no_sale"}}}) == "lost"
    assert report_outcome({"call_map": {"outcome": {"kind": "follow_up"}}}) == "follow_up"
    assert report_outcome({"call_map": {"outcome": {"kind": "none"}}}) == "unclear"
    assert report_outcome({}) == "unclear"


def test_objections_are_distinct_normalised_and_at_most_three() -> None:
    found = {
        "call_map": {
            "objections": [
                {"kind": k} for k in ("Price", "price", "Too_busy", "a|b", "timing", "trust")
            ]
        }
    }
    assert objection_kinds(found) == "price|too busy|timing"
    assert objection_kinds({"call_map": {"objections": []}}) is None
    assert objection_kinds({}) is None


def test_talk_share_counts_only_confirmed_sellers() -> None:
    summary = {"speakers": {"s1": {"talk_share": 0.62}, "s2": {"talk_share": 0.38}}}
    assert seller_talk_share(summary, [{"speaker_id": "s1", "role": "you"}]) == 62
    assert seller_talk_share(summary, [{"speaker_id": "s2", "role": "salesperson"}]) == 38
    assert seller_talk_share(summary, [{"speaker_id": "s1", "role": "prospect"}]) is None
    assert seller_talk_share(summary, None) is None
    assert seller_talk_share(None, [{"speaker_id": "s1", "role": "you"}]) is None


def test_report_language_maps_scripts_to_language_mixes() -> None:
    assert report_language({"report_language": "hi-Deva+en"}) == "hi-en"
    assert report_language({"report_language": "mr-Deva+en"}) == "mr-en"
    assert report_language({}) == "en"
    assert report_language(None) is None


def test_window_and_previous_period() -> None:
    window = InsightFilters.window(NOW, span="30d", person="p")
    assert window.since == NOW - timedelta(days=30) and window.until == NOW
    previous = window.previous()
    assert previous is not None
    assert previous.until == window.since and previous.since == NOW - timedelta(days=60)
    assert previous.person == "p"
    assert InsightFilters.window(NOW, span="all").previous() is None
    assert InsightFilters.window(NOW).since == NOW - timedelta(days=90)


def _request(query: str) -> Request:
    return Request({"type": "http", "query_string": query.encode(), "headers": []})


def test_route_filters_validate_and_use_whole_india_days() -> None:
    filters = insight_filters(
        _request("from=2026-10-01&to=2026-10-02"),
        now=NOW,
        span=None,
        start=date(2026, 10, 1),
        end=date(2026, 10, 2),
        person=None,
        team=None,
        outcome="won",
        language=None,
    )
    # 1 Oct 00:00 IST is 30 Sep 18:30 UTC; the end day is inclusive.
    assert filters.since == datetime(2026, 9, 30, 18, 30, tzinfo=UTC)
    assert filters.until == datetime(2026, 10, 2, 18, 30, tzinfo=UTC)
    kwargs: dict[str, Any] = dict(
        now=NOW, start=None, end=None, person=None, team=None, language=None
    )
    with pytest.raises(HTTPException) as unknown:
        insight_filters(_request("secret=1"), span=None, outcome=None, **kwargs)
    assert unknown.value.status_code == 422
    with pytest.raises(HTTPException):
        insight_filters(_request("range=7y"), span="7y", outcome=None, **kwargs)
    with pytest.raises(HTTPException):
        insight_filters(_request("outcome=maybe"), span=None, outcome="maybe", **kwargs)
    with pytest.raises(HTTPException):
        insight_filters(_request("range=30d&range=90d"), span="30d", outcome=None, **kwargs)
    with pytest.raises(HTTPException):
        insight_filters(
            _request("from=2026-10-03&to=2026-10-01"),
            span=None,
            outcome=None,
            **{**kwargs, "start": date(2026, 10, 3), "end": date(2026, 10, 1)},
        )


def test_authored_history_windows_end_on_the_hour_for_one_cache_entry() -> None:
    a = InsightFilters.window(NOW.replace(minute=7), span="30d").to_the_hour()
    b = InsightFilters.window(NOW.replace(minute=52, second=9), span="30d").to_the_hour()
    assert a == b
    assert a.until == NOW.replace(hour=NOW.hour + 1, minute=0)
    assert a.since is not None and a.until - a.since == timedelta(days=30)
    exact = InsightFilters.window(NOW, span="all").to_the_hour()
    assert exact.until == NOW and exact.since is None


def test_explicit_windows_are_never_moved_and_dates_stay_in_range() -> None:
    start = datetime(2026, 9, 30, 18, 30, tzinfo=UTC)
    end = datetime(2026, 10, 2, 18, 30, tzinfo=UTC)
    fixed = InsightFilters.window(NOW, start=start, end=end)
    assert fixed.fixed and fixed.to_the_hour() == fixed
    kwargs: dict[str, Any] = dict(
        now=NOW, span=None, person=None, team=None, outcome=None, language=None
    )
    for early, late in ((date(1999, 12, 31), None), (None, date(9999, 12, 31))):
        query = "&".join(
            name + "=" + str(value)
            for name, value in (("from", early), ("to", late))
            if value is not None
        )
        with pytest.raises(HTTPException) as refused:
            insight_filters(_request(query), start=early, end=late, **kwargs)
        assert refused.value.status_code == 422
