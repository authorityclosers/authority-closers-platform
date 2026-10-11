from datetime import UTC, datetime, timedelta

from ac_platform.conversation_intelligence.analysis_diagnostics import summarize_timings


def test_failed_and_missing_provider_timestamps_never_become_fast_samples():
    start = datetime(2026, 10, 11, tzinfo=UTC)
    row = {
        "stage": "C5",
        "job_kind": "conversation.infer_provider.v1",
        "state": "completed",
        "created_at": start,
        "completed_at": start + timedelta(seconds=110),
        "dispatch_started_at": start + timedelta(seconds=10),
        "receipt_recorded_at": start + timedelta(seconds=100),
        "attempt_count": 1,
    }
    summary = summarize_timings(
        {
            "runs": [
                row,
                {**row, "state": "failed", "attempt_count": 2},
                {**row, "dispatch_started_at": None, "receipt_recorded_at": None},
            ]
        }
    )
    c5 = summary["stages"]["C5"]
    assert c5["run"]["samples"] == 2
    assert c5["before_dispatch"] == {
        "samples": 1,
        "p50_seconds": 10.0,
        "p95_seconds": 10.0,
        "maximum_seconds": 10.0,
    }
    assert c5["dispatch_to_receipt"]["p95_seconds"] == 90
    assert summary["incomplete_runs"] == {"C5": 1}
    assert summary["retries_observed"] == 1


def test_no_runs_means_no_measured_latency():
    assert summarize_timings({"runs": []})["stages"] == {}
