"""The one-pass request's call date: when the call was made, not when it was uploaded.

In production phones often upload late (a battery-restricted app uploads when it is next
opened), so "call me tomorrow at six" said on Friday must still mean Saturday when the call
arrives on Sunday (simulation lab, 1 Nov 2026; the fast call data engine's twin, deb67f5f).
Pure unit tests: no database, no provider.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from ac_platform.conversation_intelligence.reporting_pipeline import call_date_for
from ac_platform.one_pass.markers import call_moment

FRIDAY_CALL = datetime(2026, 10, 30, 7, 50, 54, tzinfo=UTC)  # Friday 13:20 in India
SUNDAY_UPLOAD = datetime(2026, 11, 1, 7, 35, tzinfo=UTC)  # Sunday 13:05 in India


class FakeDatabase:
    def __init__(self, started: datetime | None) -> None:
        self.started = started
        self.asked: list[tuple[str, dict[str, Any]]] = []

    async def scalar(self, statement: Any, params: dict[str, Any]) -> datetime | None:
        self.asked.append((" ".join(str(statement).split()), params))
        return self.started


def _recording() -> Any:
    return SimpleNamespace(id=uuid4(), tenant_id=uuid4(), created_at=SUNDAY_UPLOAD)


def test_a_late_upload_is_dated_by_its_call() -> None:
    recording = _recording()
    database = FakeDatabase(FRIDAY_CALL)
    date = asyncio.run(call_date_for(database, recording))
    assert date == "Friday 30 October 2026, 13:20 India time"
    sql, params = database.asked[0]
    # The recording's submission, its Lead Desk attach event, and the call it points at.
    assert "conversation_guest_submissions" in sql and "e.data ->> 'for_call'" in sql
    assert params == {"recording": recording.id, "tenant": recording.tenant_id}


def test_a_recording_on_no_call_says_its_date_is_the_upload() -> None:
    date = asyncio.run(call_date_for(FakeDatabase(None), _recording()))
    assert date == "Sunday 01 November 2026 (uploaded then; call time unknown)"


def test_the_date_fits_the_one_pass_request() -> None:
    # one_pass.stage refuses a date over 64 characters; the longest day and month fit.
    longest = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)  # a Wednesday in September
    assert len(call_moment(None, longest)) <= 64
    assert len(call_moment(longest, longest)) <= 64
