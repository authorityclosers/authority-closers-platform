"""PostgreSQL proof for source-bound read-only C1 measurement views."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationDenied,
    ConversationNotFound,
)
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
                other = await seed(engine)
                with pytest.raises(ConversationNotFound):
                    await ConversationMeasurements(
                        ConversationApplication(database, clock=lambda: other.now)
                    ).get(other.actor, prepared.recording_id)
        finally:
            await engine.dispose()

    run(exercise())
