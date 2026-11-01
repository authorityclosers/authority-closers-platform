"""The day a call's "tomorrow" counts from: when the call was made, not when it was uploaded.

A phone that was offline uploads Friday's call on Sunday; "call me tomorrow at six" must still
mean Saturday (simulation lab, 1 Nov 2026: S05 became Monday, S17's "Saturday" a week late).
Pure unit tests: no database, no provider. Lines are fictional.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from ac_platform.call_data import engine, taxonomy
from ac_platform.call_data.extraction import Segment, build_prompt

FRIDAY_CALL = datetime(2026, 10, 30, 7, 50, 54, tzinfo=UTC)  # Friday 13:20 in India
SUNDAY_UPLOAD = datetime(2026, 11, 1, 7, 35, tzinfo=UTC)  # Sunday 13:05 in India
LEAD = uuid4()
SUBMISSION = uuid4()


def _call(**extra: Any) -> engine.Call:
    return engine.Call(
        tenant_id=uuid4(),
        recording_id=uuid4(),
        principal_id=uuid4(),
        checkpoint_id=uuid4(),
        transcript_revision="r1",
        source_sha256=None,
        duration_ms=53000,
        created_at=SUNDAY_UPLOAD,
        **extra,
    )


class FakeConnection:
    """Answers load()'s reads: the transcript, no withheld marks, the owner, the lead and
    the lead's call event."""

    def __init__(self, started: datetime | None) -> None:
        self.started = started
        self.reads: list[str] = []

    def scalar(self, statement: Any, params: Any = None) -> Any:
        sql = " ".join(str(statement).split())
        self.reads.append(sql)
        if "SELECT coalesce(c.created_at, e.created_at)" in sql:
            # The attach event is written at upload; the call it points at (for_call) is when
            # the call was made.
            assert "e.data ->> 'for_call'" in sql and params["submission"] == str(SUBMISSION)
            return self.started
        if "FROM lead_desk_leads" in sql:
            return LEAD
        return {"segments": []}

    def execute(self, statement: Any, params: Any = None) -> Any:
        return SimpleNamespace(
            mappings=lambda: [],
            first=lambda: SimpleNamespace(submission_id=SUBMISSION, person_id=uuid4()),
        )


def test_a_late_upload_is_dated_by_the_call_not_the_upload() -> None:
    late = _call(started_at=FRIDAY_CALL)
    assert late.call_date() == "Friday 30 October 2026, 13:20 India time"
    system, _ = build_prompt(
        [Segment("s1", "Call me tomorrow at six.", 0, 2000, "speaker_1")],
        types=taxonomy.FAST_TYPES,
        call_date=late.call_date(),
    )
    assert "Call date: Friday 30 October 2026, 13:20 India time." in system


def test_a_call_on_no_lead_keeps_its_upload_time() -> None:
    assert _call().call_date() == "Sunday 01 November 2026, 13:05 India time"


def test_loading_a_call_reads_when_its_lead_call_was_made() -> None:
    connection = FakeConnection(FRIDAY_CALL)
    call = engine.load(connection, _call())
    assert (call.lead_id, call.started_at) == (LEAD, FRIDAY_CALL)
    assert call.call_date().startswith("Friday 30 October 2026")
    nowhere = engine.load(FakeConnection(None), _call())
    assert nowhere.started_at is None and nowhere.call_date().startswith("Sunday 01 November")
