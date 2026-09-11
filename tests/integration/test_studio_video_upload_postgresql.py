"""Course upload admission on real locks in a fresh migrated disposable schema."""

import asyncio

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.audit.models import AuditEvent
from ac_platform.media.errors import MediaConflict
from ac_platform.media.models import MediaQuotaUsage, MediaUploadIntent, StudioVideoUpload
from ac_platform.media.service import MediaService
from ac_platform.media.signing import MediaSigner
from ac_platform.media.studio_upload import StudioVideoUploadRequest, StudioVideoUploads
from ac_platform.media.video_file_storage import VideoFileStorage
from tests.integration.test_media_delivery_renewal_postgresql import (
    _run_async,
    _transaction_timeouts,
    postgres_harness,  # noqa: F401 - isolated migrated schema
)
from tests.integration.test_studio_draft_authoring_postgresql import seed


@pytest.mark.parametrize("scenario", ["same_key", "different_actor", "different_file"])
def test_upload_creation_serializes_and_preserves_immutable_scope(
    postgres_harness,  # noqa: F811
    scenario,
    tmp_path,
):
    async def run():
        engine = create_async_engine(
            postgres_harness.schema_url, pool_size=4, max_overflow=0, hide_parameters=True
        )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        signer = MediaSigner("studio-upload-synthetic-test-key-32bytes")
        storage = VideoFileStorage(
            root=(tmp_path / "video-objects").resolve(),
            max_object_bytes=1024 * 1024,
            max_store_bytes=4 * 1024 * 1024,
        )
        service = MediaService(
            storage=storage,
            signer=signer,
            webhook_secret="studio-upload-synthetic-webhook-32bytes",  # noqa: S106
        )
        try:
            state = await seed(sessions)
            written, started, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
            pids = {}

            async def create(database, *, second=False):
                return await StudioVideoUploads(database, service).create(
                    state.actors[1 if second and scenario == "different_actor" else 0],
                    program_id=state.program_id,
                    idempotency_key="same-key",
                    body=StudioVideoUploadRequest(
                        filename="Changed.mp4"
                        if second and scenario == "different_file"
                        else "Lecture.mp4",
                        content_type="video/mp4",
                        content_length=2000,
                        checksum_sha256="a" * 64,
                    ),
                )

            async def first():
                async with sessions() as database, database.begin():
                    pids["first"] = await _transaction_timeouts(database)
                    result = await create(database)
                    written.set()
                    await asyncio.wait_for(release.wait(), 10)
                    return result

            async def second():
                await asyncio.wait_for(written.wait(), 10)
                async with sessions() as database, database.begin():
                    pids["second"] = await _transaction_timeouts(database)
                    started.set()
                    return await create(database, second=True)

            tasks = [asyncio.create_task(first()), asyncio.create_task(second())]
            try:
                await asyncio.wait_for(started.wait(), 10)
                async with sessions() as observer, asyncio.timeout(7):
                    while pids["first"] not in await observer.scalar(
                        select(func.pg_blocking_pids(pids["second"]))
                    ):
                        if tasks[1].done():
                            pytest.fail(
                                "second upload never waited for the original actor/course lock"
                            )
                        await asyncio.sleep(0.01)
                    assert (
                        await observer.scalar(
                            select(func.count())
                            .select_from(StudioVideoUpload)
                            .where(StudioVideoUpload.tenant_id == state.tenant_id)
                        )
                        == 0
                    )
                release.set()
                first_result, second_result = await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True), 10
                )
            finally:
                release.set()
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
            assert not isinstance(first_result, BaseException)
            if scenario == "different_file":
                assert isinstance(second_result, MediaConflict)
            else:
                assert not isinstance(second_result, BaseException)
                assert (first_result.upload_id == second_result.upload_id) == (
                    scenario == "same_key"
                )
            expected = 2 if scenario == "different_actor" else 1
            async with sessions() as database, database.begin():
                for model in (StudioVideoUpload, MediaUploadIntent, MediaQuotaUsage):
                    assert (
                        await database.scalar(
                            select(func.count())
                            .select_from(model)
                            .where(model.tenant_id == state.tenant_id)
                        )
                        == expected
                    )
                assert (
                    await database.scalar(
                        select(func.sum(MediaQuotaUsage.upload_count)).where(
                            MediaQuotaUsage.tenant_id == state.tenant_id
                        )
                    )
                    == expected
                )
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(AuditEvent)
                        .where(
                            AuditEvent.tenant_id == state.tenant_id,
                            AuditEvent.action == "media.studio_upload_created",
                        )
                    )
                    == expected
                )
                # Exercise migration-level protection, not just the ORM guard.
                for statement in (
                    update(StudioVideoUpload)
                    .where(StudioVideoUpload.upload_id == first_result.upload_id)
                    .values(program_id=state.program_id),
                    delete(StudioVideoUpload).where(
                        StudioVideoUpload.upload_id == first_result.upload_id
                    ),
                ):
                    with pytest.raises(DBAPIError):
                        async with database.begin_nested():
                            await database.execute(statement)
        finally:
            await engine.dispose()

    _run_async(run())
