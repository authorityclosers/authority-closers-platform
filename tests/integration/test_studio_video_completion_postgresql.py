"""PostgreSQL proof for scan/transaction separation and completion races."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from typing import Any
from uuid import uuid4

import anyio
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.media.errors import MediaConflict, MediaForbidden
from ac_platform.media.models import MediaLifecycle, MediaUploadIntent, MediaVersion
from ac_platform.media.scanner import ScanResult
from ac_platform.media.service import MediaService
from ac_platform.media.signing import MediaSigner
from ac_platform.media.studio_upload import StudioVideoUploadRequest, StudioVideoUploads
from ac_platform.media.studio_video_completion import StudioVideoCompletion
from ac_platform.media.video_file_storage import VideoFileStorage
from ac_platform.outbox.models import Job
from tests.integration.test_media_delivery_renewal_postgresql import (
    _run_async,
    postgres_harness,  # noqa: F401 - shared disposable migrated schema
)
from tests.integration.test_studio_draft_authoring_postgresql import seed

DATA = b"\x00\x00\x00\x18ftypmp42" + b"postgres-course-video" * 200


class _PausedScanner:
    def __init__(self, started: Event, release: Event) -> None:
        self.started, self.release = started, release
        self.calls = 0

    def scan(self, **kwargs: object) -> ScanResult:
        self.calls += 1
        self.started.set()
        assert self.release.wait(timeout=10)
        return ScanResult(True, verified_checksum_sha256=hashlib.sha256(DATA).hexdigest())


async def _prepare(
    sessions: async_sessionmaker[AsyncSession], state: Any, tmp_path: Path
) -> tuple[StudioVideoCompletion, Any, _PausedScanner, Event]:
    signer = MediaSigner("studio-completion-postgres-signing-key-32bytes")
    await anyio.Path(tmp_path).mkdir(parents=True, exist_ok=True)
    storage = VideoFileStorage(
        root=tmp_path / "video-objects",
        max_object_bytes=1024 * 1024,
        max_store_bytes=8 * 1024 * 1024,
    )
    started, release = Event(), Event()
    scanner = _PausedScanner(started, release)
    service = MediaService(
        storage=storage,
        signer=signer,
        scanner=scanner,
        webhook_secret="studio-completion-postgres-webhook-key-32bytes",  # noqa: S106
    )
    checksum = hashlib.sha256(DATA).hexdigest()
    async with sessions() as database, database.begin():
        upload = await StudioVideoUploads(database, service).create(
            state.actors[0],
            program_id=state.program_id,
            body=StudioVideoUploadRequest(
                filename="postgres-lecture.mp4",
                content_type="video/mp4",
                content_length=len(DATA),
                checksum_sha256=checksum,
            ),
            idempotency_key=uuid4().hex,
        )
        version = await database.get(MediaVersion, upload.media_version_id)
        assert version is not None
        object_key = version.object_key
    storage.put_stream(
        object_key=object_key,
        chunks=(DATA,),
        content_type="video/mp4",
        content_length=len(DATA),
        checksum_sha256=checksum,
    )
    return StudioVideoCompletion(sessions, service, storage), upload, scanner, release


@pytest.mark.parametrize("session_change", ["revoked", "expired", "tenant_cleared"])
def test_postgresql_session_change_while_scan_paused_cannot_commit(
    postgres_harness: Any,  # noqa: F811
    tmp_path: Path,
    session_change: str,
) -> None:
    async def run() -> None:
        engine = create_async_engine(postgres_harness.schema_url, pool_size=3, max_overflow=0)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            state = await seed(sessions)
            coordinator, upload, scanner, release = await _prepare(
                sessions, state, tmp_path / session_change
            )
            task = asyncio.create_task(
                coordinator.complete(
                    state.actors[0],
                    program_id=state.program_id,
                    upload_id=upload.upload_id,
                    idempotency_key=f"complete-{session_change}",
                )
            )
            try:
                assert await anyio.to_thread.run_sync(scanner.started.wait, 5)
                async with sessions() as database, database.begin():
                    # A paused full-file scan owns no database lock/transaction.
                    person = await database.scalar(
                        select(Person)
                        .where(Person.id == state.actors[0].person_id)
                        .with_for_update(nowait=True)
                    )
                    assert person is not None
                    identity = await database.get(
                        IdentitySession, state.actors[0].session_id, with_for_update=True
                    )
                    assert identity is not None
                    if session_change == "revoked":
                        identity.revoked_at = datetime.now(UTC)
                    elif session_change == "expired":
                        identity.created_at = datetime.now(UTC) - timedelta(hours=2)
                        identity.expires_at = datetime.now(UTC) - timedelta(seconds=1)
                    else:
                        identity.selected_tenant_id = None
                release.set()
                with pytest.raises(MediaForbidden):
                    await asyncio.wait_for(task, 10)
            finally:
                release.set()
                await asyncio.gather(task, return_exceptions=True)
            async with sessions() as database:
                intent = await database.get(MediaUploadIntent, upload.upload_id)
                assert intent is not None
                assert intent.state == MediaLifecycle.UPLOADING.value
                assert intent.completion_fingerprint is None
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(Job)
                        .where(Job.dedupe_key.endswith(str(upload.media_version_id)))
                    )
                    == 0
                )
        finally:
            await engine.dispose()

    _run_async(run())


def test_postgresql_concurrent_completion_creates_one_idempotent_job(
    postgres_harness: Any,  # noqa: F811
    tmp_path: Path,
) -> None:
    async def run() -> None:
        engine = create_async_engine(postgres_harness.schema_url, pool_size=3, max_overflow=0)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            state = await seed(sessions)
            coordinator, upload, scanner, release = await _prepare(sessions, state, tmp_path)
            first = asyncio.create_task(
                coordinator.complete(
                    state.actors[0],
                    program_id=state.program_id,
                    upload_id=upload.upload_id,
                    idempotency_key="concurrent-completion",
                )
            )
            assert await anyio.to_thread.run_sync(scanner.started.wait, 5)
            # The storage writer lease fences a second contender before DB state
            # or job identity can diverge; an exact retry succeeds after release.
            with pytest.raises(MediaConflict):
                await coordinator.complete(
                    state.actors[0],
                    program_id=state.program_id,
                    upload_id=upload.upload_id,
                    idempotency_key="concurrent-completion",
                )
            release.set()
            accepted = await asyncio.wait_for(first, 10)
            replay = await coordinator.complete(
                state.actors[0],
                program_id=state.program_id,
                upload_id=upload.upload_id,
                idempotency_key="concurrent-completion",
            )
            assert replay.replayed and replay.processing_job_id == accepted.processing_job_id
            assert scanner.calls == 1
            async with sessions() as database:
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(Job)
                        .where(Job.dedupe_key.endswith(str(upload.media_version_id)))
                    )
                    == 1
                )
        finally:
            await engine.dispose()

    _run_async(run())
