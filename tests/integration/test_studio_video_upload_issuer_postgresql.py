"""PostgreSQL proof for the deterministic same-host Studio video issuer."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.media.errors import MediaConflict
from ac_platform.media.models import MediaUploadIntent, StudioVideoUpload
from ac_platform.media.service import MediaService
from ac_platform.media.signing import MediaSigner
from ac_platform.media.studio_upload import StudioVideoUploadRequest, StudioVideoUploads
from ac_platform.media.video_file_storage import VideoFileStorage
from tests.integration.test_media_delivery_renewal_postgresql import (
    _run_async,
    postgres_harness,  # noqa: F401 - shared disposable migrated schema
)
from tests.integration.test_studio_draft_authoring_postgresql import seed


def test_postgresql_replay_reissues_exact_stored_admission_route(
    postgres_harness,  # noqa: F811
    tmp_path,
    monkeypatch,
):
    async def run() -> None:
        engine = create_async_engine(postgres_harness.schema_url, pool_size=2, max_overflow=0)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        signer = MediaSigner("studio-video-issuer-postgres-key-32bytes")
        storage = VideoFileStorage(
            root=(tmp_path / "video-objects").resolve(),
            max_object_bytes=1024 * 1024,
            max_store_bytes=4 * 1024 * 1024,
        )
        service = MediaService(
            storage=storage,
            signer=signer,
            webhook_secret="studio-video-issuer-postgres-webhook-32bytes",  # noqa: S106
        )
        body = StudioVideoUploadRequest(
            filename="PostgreSQL lesson.mp4",
            content_type="video/mp4",
            content_length=8192,
            checksum_sha256="A" * 64,
        )
        try:
            state = await seed(sessions)
            async with sessions() as database, database.begin():
                first = await StudioVideoUploads(database, service).create(
                    state.actors[0],
                    program_id=state.program_id,
                    body=body,
                    idempotency_key="postgres-same-host-video",
                )
            async with sessions() as database, database.begin():
                replay = await StudioVideoUploads(database, service).create(
                    state.actors[0],
                    program_id=state.program_id,
                    body=body,
                    idempotency_key="postgres-same-host-video",
                )
                assert replay == first
                assert replay.upload_url == (
                    f"/v1/admin/studio/programs/{state.program_id}"
                    f"/video-uploads/{first.upload_id}/bytes"
                )
                assert replay.upload_headers["x-content-sha256"] == "a" * 64
                assert (
                    await database.scalar(select(func.count()).select_from(MediaUploadIntent)) == 1
                )
                assert (
                    await database.scalar(select(func.count()).select_from(StudioVideoUpload)) == 1
                )
                intent = await database.get(MediaUploadIntent, first.upload_id)
                assert intent is not None
                intent.expires_at = datetime.now(UTC) - timedelta(seconds=1)

            def forbidden(**_kwargs):
                pytest.fail("expired persisted admission reached the issuer")

            monkeypatch.setattr(storage, "create_studio_video_upload_intent", forbidden)
            with pytest.raises(MediaConflict):
                async with sessions() as database, database.begin():
                    await StudioVideoUploads(database, service).create(
                        state.actors[0],
                        program_id=state.program_id,
                        body=body,
                        idempotency_key="postgres-same-host-video",
                    )
        finally:
            await engine.dispose()

    _run_async(run())
