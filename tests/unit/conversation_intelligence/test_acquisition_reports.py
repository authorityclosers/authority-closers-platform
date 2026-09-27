from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence.acquisition_reports import (
    AcquisitionReports,
    _progress_failure_code,
    _safe_progress_failure_code,
)
from ac_platform.conversation_intelligence.checkpoints import build_checkpoint, content_hash
from ac_platform.conversation_intelligence.inference import ConversationInference, binding_for
from ac_platform.conversation_intelligence.retained_c5_recovery import RetainedC5RecoveryService


def _recording() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        person_id=uuid4(),
        source_sha256="a" * 64,
        source_revision=1,
        source_bytes=128,
        content_type="audio/wav",
        permission_id=uuid4(),
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("conversation_provider_execution_timeout", "conversation_provider_execution_timeout"),
        ("conversation_report_payload_missing_field", "conversation_report_payload_missing_field"),
        ("conversation_provider_http_503", "conversation_provider_http_503"),
        ("stage_uncertain", "stage_uncertain"),
        ("provider response contained a secret", None),
        ("conversation_secret_value", None),
        (None, None),
    ],
)
def test_progress_failure_code_exposes_only_stable_allowlisted_values(
    value: object, expected: str | None
) -> None:
    assert _safe_progress_failure_code(value) == expected


def test_progress_failure_code_does_not_replay_a_superseded_generation() -> None:
    old_failed = SimpleNamespace(generation=1, state="failed")
    current_completed = SimpleNamespace(generation=2, state="completed")
    current_plan = SimpleNamespace(generation=2, state="completed", progress={})

    assert (
        _progress_failure_code(
            current_plan,
            [
                (old_failed, "conversation_provider_execution_timeout"),
                (current_completed, None),
            ],
            generation=2,
            has_report=False,
        )
        is None
    )


def test_progress_failure_code_clears_while_current_plan_is_active() -> None:
    current_plan = SimpleNamespace(
        generation=2,
        state="active",
        progress={"failure_code": "stage_uncertain"},
    )

    assert _progress_failure_code(current_plan, [], generation=2, has_report=False) is None


@pytest.mark.asyncio
async def test_recovered_guest_transcript_projects_native_tail_for_playback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recording = _recording()
    binding = binding_for(recording)
    c0 = build_checkpoint(
        binding,
        "C0",
        "recording-v1",
        {},
        (),
        content_hash({"source_sha256": recording.source_sha256}),
    )
    transcript = {
        "source_sha256": recording.source_sha256,
        "revision": "deepgram-response-sha",
        "timebase_id": "deepgram-native-seconds",
        "duration_ms": 1_000,
        "segments": [
            {"id": "s1", "start_ms": 0, "end_ms": 800, "text": "Hello"},
            {"id": "s2", "start_ms": 800, "end_ms": 1_135, "text": "Goodbye"},
        ],
    }
    c2 = build_checkpoint(
        binding,
        "C2",
        "deepgram-transcript-v1",
        {},
        (c0,),
        content_hash(transcript),
    )
    checkpoint = SimpleNamespace(
        stage="C2",
        cache_key=c2.cache_key,
        manifest_sha256=c2.manifest_sha256,
        payload_sha256=c2.payload_sha256,
        manifest=c2.as_dict(),
        payload=transcript,
        erased_at=None,
    )

    class Database:
        async def scalar(self, _query: object) -> SimpleNamespace:
            return checkpoint

    ownership = SimpleNamespace(database=Database(), clock=lambda: datetime.now(UTC))
    reports = AcquisitionReports(ownership)
    recovered = SimpleNamespace(
        c2_checkpoint_id=uuid4(),
        c2_manifest_sha256=c2.manifest_sha256,
    )

    async def recording_read(*args: object, **kwargs: object) -> tuple[None, SimpleNamespace]:
        return None, recording

    async def recovery_read(self: RetainedC5RecoveryService, value: object) -> SimpleNamespace:
        return recovered

    async def source_plan(self: ConversationInference, value: SimpleNamespace) -> SimpleNamespace:
        assert value is recording
        return SimpleNamespace(duration_ms=1_000)

    monkeypatch.setattr(reports, "recording", recording_read)
    monkeypatch.setattr(RetainedC5RecoveryService, "latest_for_recording", recovery_read)
    monkeypatch.setattr(ConversationInference, "plan_transcription", source_plan)

    payload = await reports.transcript(uuid4())

    assert payload["duration_ms"] == 1_000
    assert payload["segments"][-1]["end_ms"] == 1_000
    assert "playback_projection" not in payload
    assert checkpoint.payload["segments"][-1]["end_ms"] == 1_135
