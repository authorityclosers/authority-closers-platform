"""Capture deadlines and operational rates, independent of AI scoring."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from ac_platform.lead_desk.capture_guard import CaptureCall, daily_rates, state_for

NOW = datetime(2026, 10, 29, 13, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    ("age", "expected"), [(1799, "waiting"), (1800, "missing"), (1801, "missing")]
)
def test_missing_deadline(age, expected):
    assert state_for(at=NOW - timedelta(seconds=age), now=NOW, received=False) == expected


@pytest.mark.parametrize(
    ("run", "report", "expected"),
    [
        (None, False, "uploaded"),
        ("queued", False, "analysing"),
        ("running", False, "analysing"),
        ("completed", True, "report_ready"),
        ("completed", False, "uploaded"),
        ("failed", False, "uploaded"),
    ],
)
def test_receipt_and_report_are_required(run, report, expected):
    assert state_for(at=NOW, now=NOW, received=True, run_state=run, report=report) == expected
    assert state_for(at=NOW, now=NOW, received=False, run_state=run, report=report) == "waiting"


def test_short_call_hold_is_done_without_a_report():
    assert state_for(at=NOW, now=NOW, received=True, short=True) == "short_call"
    assert state_for(at=NOW, now=NOW, received=True, run_state="completed", short=True) == (
        "short_call"
    )
    assert state_for(at=NOW, now=NOW, received=True, run_state="queued", short=True) == (
        "analysing"
    )
    assert state_for(at=NOW, now=NOW, received=False, short=True) == "waiting"
    seller = UUID(int=1)
    call = CaptureCall(
        event_id=UUID(int=3), lead_id=UUID(int=2), person_id=seller, at=NOW, state="short_call"
    )
    row = daily_rates([call], {})[0]
    assert (row.received, row.analysed, row.needs_fix) == (1, 0, False)


def test_rates_count_calls_once_and_use_india_days_and_strict_90_percent():
    seller = UUID(int=1)
    calls = [
        CaptureCall(
            event_id=UUID(int=i + 10),
            lead_id=UUID(int=2),
            person_id=seller,
            at=NOW,
            state="report_ready" if i < 9 else "missing",
        )
        for i in range(10)
    ]
    row = daily_rates(calls, {seller: "Alex Example"})[0]
    assert (row.calls, row.received, row.analysed, row.rate, row.needs_fix) == (10, 9, 9, 90, False)
    calls.append(calls[-1].model_copy(update={"event_id": UUID(int=99)}))
    assert daily_rates(calls, {})[0].needs_fix
    calls.append(calls[-1].model_copy(update={"at": datetime(2026, 10, 29, 18, 30, tzinfo=UTC)}))
    assert str(daily_rates(calls, {})[0].day) == "2026-10-30"


def test_contract_rejects_unknown_state():
    with pytest.raises(ValidationError):
        CaptureCall(
            event_id=UUID(int=1), lead_id=UUID(int=2), person_id=None, at=NOW, state="guaranteed"
        )
