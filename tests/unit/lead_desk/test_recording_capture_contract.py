"""The no-call-log command never accepts invented direction or arbitrary workspace selectors."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from ac_platform.lead_desk.contracts import CallOutcomes, RecordingCall


def test_recording_call_requires_number_clock_and_positive_duration():
    values = dict(
        command_id=UUID(int=1),
        number="+12025550123",
        started_at=datetime(2026, 10, 29, tzinfo=UTC),
        duration_seconds=20,
    )
    assert RecordingCall(**values).duration_seconds == 20
    for extra in (
        {"direction": "incoming"},
        {"tenant_id": str(UUID(int=2))},
        {"duration_seconds": 0},
    ):
        with pytest.raises(ValidationError):
            RecordingCall(**(values | extra))


def test_call_outcomes_take_recordings_only_never_audio_or_a_direction():
    call = dict(
        key="rec-1",
        number="+12025550123",
        started_at=datetime(2026, 10, 29, tzinfo=UTC),
        duration_seconds=45,
    )
    values = dict(device_id=UUID(int=1), source="recording", calls=[call])
    assert CallOutcomes(**values).calls[0].duration_seconds == 45
    for extra in (
        {"source": "call_log"},
        {"tenant_id": str(UUID(int=2))},
        {"calls": [call | {"direction": "outgoing"}]},
        {"calls": [call | {"audio": "..."}]},
        {"calls": [call | {"duration_seconds": 0}]},
        {"calls": [call | {"key": "../x"}]},
        {"calls": [call] * 201},
    ):
        with pytest.raises(ValidationError):
            CallOutcomes(**(values | extra))
