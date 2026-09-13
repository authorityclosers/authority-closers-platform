"""PostgreSQL proof for source-bound read-only C1 measurement views."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ac_platform.conversation_intelligence.application import (
    AUDIOATLAS_HOSTED_RECIPE,
    ConversationApplication,
    ConversationConflict,
    ConversationDenied,
    ConversationNotFound,
)
from ac_platform.conversation_intelligence.checkpoints import build_checkpoint, content_hash
from ac_platform.conversation_intelligence.inference import binding_for
from ac_platform.conversation_intelligence.measurement_view import ConversationMeasurements
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationPermission,
    ConversationRecording,
)
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_worker_postgresql import _prepare


@pytest.fixture
def postgres_harness() -> Any:
    """Use only the disposable loopback PostgreSQL harness."""

    yield from _postgres_harness.__wrapped__()  # type: ignore[attr-defined]


def _canonical_c0(recording: ConversationRecording) -> Any:
    payload = {
        "source_sha256": recording.source_sha256,
        "source_bytes": recording.source_bytes,
        "content_type": recording.content_type,
        "permission_reference": str(recording.permission_id),
    }
    return build_checkpoint(
        binding_for(recording), "C0", "recording-v1", {}, (), content_hash(payload)
    )


def test_measurement_view_returns_saved_c1_and_enforces_current_source_authority(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        prepared = await _prepare(postgres_harness, tmp_path)
        assert await prepared.worker.run_once()
        engine = create_async_engine(postgres_harness.url)
        try:
            async with AsyncSession(engine) as database, database.begin():
                application = ConversationApplication(database, clock=lambda: prepared.state.now)
                view = cast(
                    dict[str, Any],
                    await ConversationMeasurements(application).get(
                        prepared.state.actor, prepared.recording_id
                    ),
                )
                row = await database.scalar(
                    select(ConversationCheckpoint).where(
                        ConversationCheckpoint.recording_id == prepared.recording_id,
                        ConversationCheckpoint.stage == "C1",
                    )
                )
                assert row is not None and row.payload is not None
                payload = row.payload
                display = payload["display"]
                assert view["schema"] == "ac.sales-xray.measurement-view/1"
                assert view["availability"] == "available"
                assert view["source"]["tenant_id"] == str(prepared.state.tenant_id)
                assert view["source"]["recording_id"] == str(prepared.recording_id)
                assert view["source"]["source_sha256"] == prepared.state.source_sha256
                assert view["source"]["source_rate"] == 48_000
                assert view["source"]["decoded_rate"] == 48_000
                assert view["source"]["clock"] == "decoded_audio_track"
                assert view["source"]["container_video_sync_certified"] is False
                assert view["audioatlas"]["profile"] == "audioatlas-native-0.1-40ms-10ms"
                assert view["audioatlas"]["window_ms"] == 40
                assert view["audioatlas"]["hop_ms"] == 10
                assert view["audioatlas"]["feature_sha256"] == payload["feature_sha256"]
                first_saved = display["channels"][0]
                first_view = view["audioatlas"]["channels"][0]
                assert first_view["label"] == "Channel 1"
                assert first_view["level"]["value"] == first_saved["median_dbfs"]
                assert first_view["pitch"]["value"] == first_saved["f0_median_hz"]
                assert (
                    first_view["pitch"]["available_fraction"]
                    == first_saved["pitch_available_fraction"]
                )
                assert first_view["series"][0]["unit"] == "dBFS"
                assert first_view["series"][1]["unit"] == "Hz"
                assert [point["start_ms"] for point in first_view["series"][0]["points"]] == [
                    time * 1000 for time in first_saved["time_s"]
                ]
                assert [
                    point["value"] for point in first_view["series"][0]["points"]
                ] == first_saved["dbfs"]
                assert view["signallab"] == {
                    "status": "unavailable",
                    "reason": "source_inspected_adapter_not_implemented",
                    "source_revision": "signallab-studio-0.2",
                    "runtime_output": False,
                }

            other = await seed(engine)
            async with AsyncSession(engine) as database, database.begin():
                with pytest.raises(ConversationNotFound):
                    await ConversationMeasurements(
                        ConversationApplication(database, clock=lambda: other.now)
                    ).get(other.actor, prepared.recording_id)

            async def add_c1_and_check(make_row: Any, check: Any) -> None:
                async with AsyncSession(engine) as database, database.begin():
                    row = await database.scalar(
                        select(ConversationCheckpoint).where(
                            ConversationCheckpoint.recording_id == prepared.recording_id,
                            ConversationCheckpoint.stage == "C1",
                            ConversationCheckpoint.erased_at.is_(None),
                        )
                    )
                    recording = await database.get(ConversationRecording, prepared.recording_id)
                    assert row is not None and row.payload is not None and row.manifest is not None
                    assert recording is not None
                    values = make_row(row, recording)
                    inserted = ConversationCheckpoint(
                        id=uuid4(),
                        recording_id=row.recording_id,
                        tenant_id=row.tenant_id,
                        person_id=row.person_id,
                        cache_key=values["cache_key"],
                        manifest_sha256=values["manifest_sha256"],
                        payload_sha256=values.get("payload_sha256", row.payload_sha256),
                        stage="C1",
                        feature_blob_id=row.feature_blob_id,
                        manifest=values["manifest"],
                        payload=values.get("payload", deepcopy(row.payload)),
                        created_at=datetime.now(UTC) + timedelta(days=1),
                    )
                    database.add(inserted)
                    await database.flush()
                    inserted_id = inserted.id
                try:
                    await check()
                finally:
                    async with AsyncSession(engine) as database, database.begin():
                        await database.execute(
                            update(ConversationCheckpoint)
                            .where(ConversationCheckpoint.id == inserted_id)
                            .values(erased_at=prepared.state.now, payload=None, manifest=None)
                        )

            def wrong_parent_row(row: Any, recording: Any) -> dict[str, Any]:
                assert row.manifest is not None
                wrong_c0 = build_checkpoint(
                    binding_for(recording), "C0", "recording-v1", {}, (), "f" * 64
                )
                wrong_c1 = build_checkpoint(
                    binding_for(recording),
                    "C1",
                    row.manifest["revision"],
                    json.loads(row.manifest["config_json"]),
                    (wrong_c0,),
                    row.payload_sha256,
                )
                return {
                    "cache_key": wrong_c1.cache_key,
                    "manifest_sha256": wrong_c1.manifest_sha256,
                    "manifest": wrong_c1.as_dict(),
                }

            async def expect_wrong_parent() -> None:
                async with AsyncSession(engine) as database, database.begin():
                    with pytest.raises(ConversationConflict):
                        await ConversationMeasurements(
                            ConversationApplication(database, clock=lambda: prepared.state.now)
                        ).get(prepared.state.actor, prepared.recording_id)

            await add_c1_and_check(wrong_parent_row, expect_wrong_parent)

            def tampered_payload_row(row: Any, recording: Any) -> dict[str, Any]:
                assert row.payload is not None
                payload = deepcopy(row.payload)
                payload["display"]["channels"][0]["dbfs"][0] = 1.0
                assert row.manifest is not None
                tampered = build_checkpoint(
                    binding_for(recording),
                    "C1",
                    row.manifest["revision"],
                    json.loads(row.manifest["config_json"]),
                    (_canonical_c0(recording),),
                    row.payload_sha256,
                    replicate="test-tampered-payload",
                )
                return {
                    "cache_key": tampered.cache_key,
                    "manifest_sha256": tampered.manifest_sha256,
                    "manifest": tampered.as_dict(),
                    "payload": payload,
                }

            async def expect_tampered_payload() -> None:
                async with AsyncSession(engine) as database, database.begin():
                    with pytest.raises(ConversationConflict):
                        await ConversationMeasurements(
                            ConversationApplication(database, clock=lambda: prepared.state.now)
                        ).get(prepared.state.actor, prepared.recording_id)

            await add_c1_and_check(tampered_payload_row, expect_tampered_payload)

            def hosted_update(row: Any, recording: Any) -> dict[str, Any]:
                assert row.payload is not None
                payload = deepcopy(row.payload)
                payload["acoustics"].update(
                    {
                        "rate": 16_000,
                        "sample_count": 16_000,
                        "window_samples": 640,
                        "hop_samples": 160,
                        "rows": 100,
                        "uncompressed_payload_bytes": 6_600,
                    }
                )
                payload["timebase"].update(
                    {"rate": 16_000, "nominal_source_samples_per_decoded_sample": 3}
                )
                for channel in payload["display"]["channels"]:
                    channel["frame_count"] = 100
                c0 = _canonical_c0(recording)
                checkpoint = build_checkpoint(
                    binding_for(recording),
                    "C1",
                    AUDIOATLAS_HOSTED_RECIPE,
                    {"decode_rate": 16_000, "window_profile": "audioatlas-40ms-10ms"},
                    (c0,),
                    content_hash(payload),
                )
                return {
                    "cache_key": checkpoint.cache_key,
                    "manifest_sha256": checkpoint.manifest_sha256,
                    "payload_sha256": checkpoint.payload_sha256,
                    "manifest": checkpoint.as_dict(),
                    "payload": payload,
                }

            async def expect_hosted_measurements() -> None:
                async with AsyncSession(engine) as database, database.begin():
                    result = cast(
                        dict[str, Any],
                        await ConversationMeasurements(
                            ConversationApplication(database, clock=lambda: prepared.state.now)
                        ).get(prepared.state.actor, prepared.recording_id),
                    )
                    assert result["source"]["decoded_rate"] == 16_000
                    assert result["audioatlas"]["decoded_rate"] == 16_000
                    assert result["audioatlas"]["window_ms"] == 40
                    assert result["audioatlas"]["hop_ms"] == 10

            await add_c1_and_check(hosted_update, expect_hosted_measurements)

            async with AsyncSession(engine) as database, database.begin():
                await database.execute(
                    update(ConversationPermission)
                    .where(ConversationPermission.id == prepared.state.permission_id)
                    .values(revoked_at=prepared.state.now)
                )
            async with AsyncSession(engine) as database, database.begin():
                with pytest.raises(ConversationDenied):
                    await ConversationMeasurements(
                        ConversationApplication(database, clock=lambda: prepared.state.now)
                    ).get(prepared.state.actor, prepared.recording_id)

            async with AsyncSession(engine) as database, database.begin():
                await database.execute(
                    update(ConversationRecording)
                    .where(ConversationRecording.id == prepared.recording_id)
                    .values(state="deleted", deleted_at=prepared.state.now)
                )
            async with AsyncSession(engine) as database, database.begin():
                with pytest.raises(ConversationNotFound):
                    await ConversationMeasurements(
                        ConversationApplication(database, clock=lambda: prepared.state.now)
                    ).get(prepared.state.actor, prepared.recording_id)
                with pytest.raises(ConversationNotFound):
                    await ConversationMeasurements(
                        ConversationApplication(database, clock=lambda: other.now)
                    ).get(other.actor, prepared.recording_id)
        finally:
            await engine.dispose()

    run(exercise())
