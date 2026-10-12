"""Missing clocks, failed attempts and privacy cannot manufacture a speed pass."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from ac_platform.conversation_intelligence.pipeline_timings import distribution, summarize

NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)


def row(**changes: Any) -> dict[str, Any]:
    return {
        "stage": "C5",
        "state": "completed",
        "claims": 1,
        "enqueue": NOW,
        "dispatch": NOW + timedelta(seconds=2),
        "receipt": NOW + timedelta(seconds=30),
        "completed": NOW + timedelta(seconds=31),
        "published": NOW + timedelta(seconds=30.5),
        **changes,
    }


def delivery(**changes: Any) -> dict[str, Any]:
    return {
        "state": "completed",
        "uploaded": NOW - timedelta(seconds=10),
        "accepted": NOW,
        "report_saved": NOW + timedelta(seconds=48),
        "delivered": NOW + timedelta(seconds=49),
        "delivery_bound": True,
        **changes,
    }


def test_queue_receipt_and_publication_have_distinct_clocks() -> None:
    value = summarize([row()], [delivery()], limit=200)
    stage = value["stages"]["C5"]
    assert stage["enqueue_to_dispatch"]["p50_seconds"] == 2
    assert stage["dispatch_to_receipt"]["p50_seconds"] == 28
    assert stage["receipt_to_checkpoint"]["p50_seconds"] == 0.5
    assert stage["enqueue_to_completed"]["p50_seconds"] == 31
    assert value["plans"]["acceptance_to_delivery"]["p50_seconds"] == 49
    assert value["plans"]["acceptance_to_report_saved"]["p50_seconds"] == 48
    assert value["plans"]["source_stored_to_delivery"]["p50_seconds"] == 59
    assert value["plans"]["report_saved_to_delivery"]["p50_seconds"] == 1
    assert value["twenty_minute_under_60_seconds"] == "unverified"


def test_missing_and_reversed_clocks_stay_out_of_percentiles() -> None:
    result = distribution(
        [row(), row(receipt=None), row(receipt=NOW), row(receipt=NOW + timedelta(seconds=2))],
        "dispatch",
        "receipt",
    )
    assert result == {
        "n": 2,
        "missing": 1,
        "reversed": 1,
        "p50_seconds": 0,
        "p95_seconds": 28,
        "max_seconds": 28,
    }


def test_nearest_rank_tail_uses_the_observed_tail_not_interpolation() -> None:
    samples = [row(receipt=NOW + timedelta(seconds=2 + n)) for n in range(1, 21)]
    result = distribution(samples, "dispatch", "receipt")
    assert result["n"] == 20
    assert result["p50_seconds"] == 10
    assert result["p95_seconds"] == 19
    assert result["max_seconds"] == 20


def test_failed_and_uncertain_results_do_not_lower_completed_latency() -> None:
    value = summarize(
        [row(), row(state="failed", claims=3, completed=NOW + timedelta(seconds=3))],
        [delivery(state="held", report_saved=None, delivered=None)],
        limit=200,
    )
    stage = value["stages"]["C5"]
    assert stage["states"] == {"completed": 1, "failed": 1}
    assert stage["reclaimed_jobs"] == 1
    assert stage["enqueue_to_completed"]["n"] == 1
    assert stage["enqueue_to_completed"]["p50_seconds"] == 31
    assert stage["dispatch_to_receipt"]["n"] == 2
    assert value["plans"]["acceptance_to_delivery"]["n"] == 0


def test_empty_and_truncated_samples_are_honest() -> None:
    empty = summarize([], [], limit=1)
    assert empty["stages"]["C2"]["dispatch_to_receipt"]["p50_seconds"] is None
    truncated = summarize([row(), row()], [delivery(), delivery()], limit=1)
    assert truncated["run_sample"] == {"n": 1, "truncated": True}
    assert truncated["plan_sample"] == {"n": 1, "truncated": True}
    assert truncated["stages"]["C5"]["runs"] == 1


def test_content_and_identifiers_do_not_enter_summary() -> None:
    value = summarize(
        [row(payload="PRIVATE CALL WORDS", credential="PRIVATE TOKEN", id="PRIVATE IDENTIFIER")],
        [delivery(transcript="PRIVATE TRANSCRIPT")],
        limit=200,
    )
    serialized = json.dumps(value)
    assert "PRIVATE" not in serialized
    assert "provider_completed" not in serialized
    assert "retries" not in serialized


@pytest.mark.parametrize("value", [0, 501, True, "20"])
def test_limit_is_bounded(value: Any) -> None:
    with pytest.raises(ValueError, match="pipeline_timing_limit_invalid"):
        summarize([], [], limit=value)


@pytest.mark.parametrize("changes", [{"stage": "PRIVATE"}, {"state": "PRIVATE"}, {"claims": True}])
def test_unknown_labels_cannot_leak_content(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="pipeline_timing_(state|stage)_invalid"):
        summarize([row(**changes)], [], limit=200)


def test_timezone_offsets_use_elapsed_time() -> None:
    right = (NOW + timedelta(seconds=3)).astimezone(timezone(timedelta(hours=5, minutes=30)))
    assert distribution([{"a": NOW, "b": right}], "a", "b")["p50_seconds"] == 3
    with pytest.raises(ValueError, match="pipeline_timing_clock_invalid"):
        distribution([{"a": NOW.replace(tzinfo=None), "b": right}], "a", "b")


def test_an_unbound_report_is_never_counted_as_delivered() -> None:
    value = summarize([], [delivery(delivery_bound=False)], limit=200)
    assert value["plans"]["bound_saved_reports"] == 1
    assert value["plans"]["bound_delivery_reports"] == 0
    assert value["plans"]["acceptance_to_delivery"]["p95_seconds"] is None


def test_c1_publication_to_c2_is_distinct_from_provider_queueing() -> None:
    value = summarize(
        [row(stage="C2", c1_published=NOW - timedelta(seconds=40), c1_matches=1)],
        [],
        limit=200,
    )
    assert value["c1_c2_handoff"]["c1_publication_to_c2_enqueue"]["p50_seconds"] == 40
    assert value["c1_c2_handoff"]["c1_publication_to_c2_dispatch"]["p50_seconds"] == 42
    assert value["stages"]["C2"]["enqueue_to_dispatch"]["p50_seconds"] == 2


def test_ambiguous_c1_does_not_pick_a_favourable_clock() -> None:
    value = summarize([row(stage="C2", c1_matches=2, c1_published=None)], [], limit=200)
    assert value["c1_c2_handoff"]["ambiguous_c1_artifacts"] == 1
    assert value["c1_c2_handoff"]["c1_publication_to_c2_dispatch"]["n"] == 0
