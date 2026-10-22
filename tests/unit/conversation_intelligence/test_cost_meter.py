"""The cost meter (owner, 22 Oct 2026): cost per audio minute now, full reports against short
calls, recorded-only calls apart, by pipeline version; and Usage's overview counting
analysed calls only (115 shown for 69 analysed before)."""

from __future__ import annotations

from typing import Any

from ac_platform.conversation_intelligence.cost_meter import TARGETS, meter_view
from ac_platform.conversation_intelligence.cost_metrics import Scope, build_metrics, parse_export
from tests.unit.conversation_intelligence.test_cost_metrics import (
    NOW,
    _at,
    _call,
    _document,
    _steps,
)


def _meter_document() -> dict[str, Any]:
    document = _document("production")
    document["calls"] = [
        _call("call-full"),
        _call("call-short", hours_ago=4, delivered_at=None),
        _call("call-recorded", hours_ago=3, delivered_at=None),
        _call("call-canary", kind="canary", hours_ago=2),
        _call("call-synthetic", kind="synthetic", hours_ago=2),
        _call("call-old", hours_ago=24 * 9),
    ]
    document["steps"] = (
        _steps("call-full")
        + _steps("call-short", hours_ago=4)[:1]  # transcribed, no report
        + _steps("call-canary", hours_ago=2)
        + _steps("call-synthetic", hours_ago=2)
        + _steps("call-old", hours_ago=24 * 9)
    )
    document["local_steps"] = [
        {
            "call": "call-recorded",
            "company": "co-1",
            "status": "succeeded",
            "attempts": 1,
            "run_ms": 900,
            "at": _at(3),
        }
    ]
    document["pointer_reviews"] = []
    return document


def _window(view: dict[str, Any], key: str) -> dict[str, Any]:
    return next(row for row in view["windows"] if row["key"] == key)


def test_the_meter_splits_full_reports_short_calls_and_recorded_only() -> None:
    export = parse_export("production", _meter_document())
    view = meter_view([export], environment="production", now=NOW)
    assert view["available"] is True and view["targets"] == list(TARGETS) == [0.40, 0.10]
    assert view["age_seconds"] == 360  # the export was made 0.1 hours before NOW
    week = _window(view, "7d")
    assert (week["all_in"]["calls"], week["full_reports"]["calls"], week["short"]["calls"]) == (
        2,
        1,
        1,
    )
    # Canary, synthetic and 9-day-old calls never count; a recorded-only call never has a rate.
    assert week["not_analysed"] == {"calls": 1, "audio_minutes": 10.0}
    assert week["all_in"]["audio_minutes"] == 20.0
    assert week["full_reports"]["per_minute"] > week["short"]["per_minute"] > 0
    total = week["full_reports"]["rupees"] + week["short"]["rupees"]
    assert abs(week["all_in"]["rupees"] - total) < 0.011
    # Today (India time) and the last 24 hours hold the same calls here.
    assert _window(view, "today")["all_in"] == _window(view, "24h")["all_in"] == week["all_in"]


def test_versions_show_apart_so_a_switch_is_visible() -> None:
    document = _meter_document()
    document["calls"][1] = _call("call-short", hours_ago=4, delivered_at=None, facts="one-pass-v1")
    view = meter_view([parse_export("production", document)], environment="production", now=NOW)
    labels = {row["label"]: row for row in view["by_version"]}
    assert len(labels) == 2
    one_pass = next(row for label, row in labels.items() if "one-pass-v1" in label)
    assert (one_pass["calls"], one_pass["full_reports"]) == (1, 0)
    assert view["by_version"][0]["last_at"] >= view["by_version"][1]["last_at"]


def test_an_environment_without_an_export_says_so() -> None:
    export = parse_export("staging", _document())
    view = meter_view([export], environment="production", now=NOW)
    assert view["available"] is False and view["age_seconds"] is None


def test_usage_overview_counts_analysed_calls_and_recorded_ones_apart() -> None:
    export = parse_export("production", _meter_document())
    overview = build_metrics([export], Scope(now=NOW, days=7, environment="all", tests=False))[
        "overview"
    ]
    assert overview["calls"] == 2 and overview["recorded_only"] == 1
    assert overview["environments"][0]["recorded_only"] == 1
    with_tests = build_metrics([export], Scope(now=NOW, days=7, environment="all", tests=True))[
        "overview"
    ]
    assert with_tests["calls"] == 4  # the canary and the synthetic call, when asked
