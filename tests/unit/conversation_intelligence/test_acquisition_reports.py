from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence.acquisition_reports import AcquisitionReports
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
        generation=1,
        state="ready",
    )


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


@pytest.mark.asyncio
async def test_progress_uses_newest_bounded_task_window_in_chronological_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recording = _recording()
    scope = SimpleNamespace(
        tenant_id=recording.tenant_id,
        processing_person_id=recording.person_id,
        processing_lease_id=uuid4(),
        claimed_account=False,
    )
    captured: list[str] = []
    newest = SimpleNamespace(stage="C5", state="running")
    older = SimpleNamespace(stage="C4", state="completed")

    class ScalarRows:
        def all(self) -> list[SimpleNamespace]:
            return [newest, older]

    class Database:
        async def scalar(self, query: object) -> None:
            return None

        async def scalars(self, query: object) -> ScalarRows:
            captured.append(str(query))
            return ScalarRows()

    ownership = SimpleNamespace(database=Database(), clock=lambda: datetime.now(UTC))
    reports = AcquisitionReports(ownership)

    async def recording_read(*args: object, **kwargs: object) -> tuple[object, object]:
        return scope, recording

    async def recovery_read(self: RetainedC5RecoveryService, value: object) -> None:
        return None

    async def draft_read(value: object) -> None:
        return None

    monkeypatch.setattr(reports, "recording", recording_read)
    monkeypatch.setattr(RetainedC5RecoveryService, "latest_for_recording", recovery_read)
    monkeypatch.setattr(reports, "_draft", draft_read)

    payload = await reports.progress(uuid4())

    assert captured and "conversation_inference_tasks.created_at DESC" in captured[0]
    assert "conversation_inference_tasks.run_id DESC" in captured[0]
    assert payload["stages"] == [
        {"stage": "C4", "state": "completed"},
        {"stage": "C5", "state": "running"},
    ]
