"""Course completion proof through real bytes, scanner invocation and durable queueing."""

from __future__ import annotations

import asyncio
import hashlib
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from ac_platform.audit.models import AuditEvent
from ac_platform.authorization.policy import CapabilityDenied
from ac_platform.media.errors import MediaConflict, MediaForbidden, MediaQuotaExceeded
from ac_platform.media.models import MediaAsset, MediaLifecycle, MediaUploadIntent, MediaVersion
from ac_platform.media.scanner import ScanResult, SignatureContentScanner
from ac_platform.media.studio_upload import StudioVideoUploadRequest, StudioVideoUploads
from ac_platform.media.studio_video_completion import (
    MEDIA_PROCESS_VERSION_JOB,
    StudioVideoCompletion,
)
from ac_platform.media.video_file_storage import VideoFileStorage
from ac_platform.outbox.models import Job, JobStatus
from ac_platform.worker import build_default_dispatcher
from tests.unit.authorization.test_capability_application import state as state  # noqa: F401
from tests.unit.catalog.test_studio_capabilities import CatalogSession
from tests.unit.media.test_studio_selection import selection as selection  # noqa: F401

DATA = b"\x00\x00\x00\x18ftypmp42" + b"course-video" * 200


class _Sessions:
    def __init__(self, database) -> None:
        self.database = database
        self.active_transactions = 0

    def __call__(self):
        owner = self

        class Scope(CatalogSession):
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            @asynccontextmanager
            async def begin(self):
                owner.active_transactions += 1
                try:
                    with self.database.begin_nested():
                        yield
                finally:
                    owner.active_transactions -= 1

            async def refresh(self, row) -> None:
                self.database.refresh(row)

        return Scope(self.database)


class _ObservedScanner:
    def __init__(self, sessions: _Sessions, *, clean: bool = True) -> None:
        self.sessions, self.clean = sessions, clean
        self.calls = 0

    def scan(self, **kwargs) -> ScanResult:
        self.calls += 1
        assert self.sessions.active_transactions == 0
        if not self.clean:
            return ScanResult(False, "MALWARE_DETECTED")
        return SignatureContentScanner().scan(**kwargs)


class _BlockingScanner(_ObservedScanner):
    def __init__(self, sessions: _Sessions) -> None:
        super().__init__(sessions)
        self.started, self.release = Event(), Event()

    def scan(self, **kwargs) -> ScanResult:
        self.started.set()
        assert self.release.wait(timeout=10)
        return super().scan(**kwargs)


async def _prepared(selection, tmp_path: Path, *, clean: bool = True):
    state = selection
    checksum = hashlib.sha256(DATA).hexdigest()
    storage = VideoFileStorage(
        root=(tmp_path / "video-objects").resolve(),
        max_object_bytes=1024 * 1024,
        max_store_bytes=4 * 1024 * 1024,
    )
    state.service.storage = storage
    upload = await StudioVideoUploads(state.database, state.service).create(
        state.editor,
        program_id=state.program,
        body=StudioVideoUploadRequest(
            filename="Lesson.mp4",
            content_type="video/mp4",
            content_length=len(DATA),
            checksum_sha256=checksum,
        ),
        idempotency_key=uuid4().hex,
    )
    storage.put_stream(
        object_key=state.db.get(MediaVersion, upload.media_version_id).object_key,
        chunks=(DATA,),
        content_type="video/mp4",
        content_length=len(DATA),
        checksum_sha256=checksum,
    )
    sessions = _Sessions(state.db)
    scanner = _ObservedScanner(sessions, clean=clean)
    state.service.scanner = scanner
    coordinator = StudioVideoCompletion(sessions, state.service, storage)
    return SimpleNamespace(
        state=state,
        upload=upload,
        storage=storage,
        sessions=sessions,
        scanner=scanner,
        coordinator=coordinator,
    )


async def test_real_scan_runs_without_transaction_then_atomically_queues_processing(
    selection, tmp_path
):
    prepared = await _prepared(selection, tmp_path)
    result = await prepared.coordinator.complete(
        prepared.state.editor,
        program_id=prepared.state.program,
        upload_id=prepared.upload.upload_id,
        idempotency_key="complete-lesson",
    )

    intent = prepared.state.db.get(MediaUploadIntent, prepared.upload.upload_id)
    version = prepared.state.db.get(MediaVersion, prepared.upload.media_version_id)
    asset = prepared.state.db.get(MediaAsset, prepared.upload.media_id)
    job = prepared.state.db.get(Job, result.processing_job_id)
    assert prepared.scanner.calls == 1
    assert prepared.sessions.active_transactions == 0
    assert intent.state == "processing" and result.state is MediaLifecycle.PROCESSING
    assert version.state == "processing" and asset.state == "processing"
    assert asset.current_version_id is None and version.duration_seconds is None
    assert job is not None and job.status == JobStatus.QUEUED.value
    assert job.kind == MEDIA_PROCESS_VERSION_JOB and job.external_side_effect is False
    assert job.payload["program_id"] == str(prepared.state.program)
    assert job.payload["version_id"] == str(version.id)
    assert MEDIA_PROCESS_VERSION_JOB not in build_default_dispatcher().allowed_kinds


async def test_exact_retry_reuses_one_job_and_audit_without_rescanning(selection, tmp_path):
    prepared = await _prepared(selection, tmp_path)
    first = await prepared.coordinator.complete(
        prepared.state.editor,
        program_id=prepared.state.program,
        upload_id=prepared.upload.upload_id,
        idempotency_key="complete-once",
    )
    audit_count = prepared.state.db.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(AuditEvent.action == "media.upload_completed")
    )
    second = await prepared.coordinator.complete(
        prepared.state.editor,
        program_id=prepared.state.program,
        upload_id=prepared.upload.upload_id,
        idempotency_key="complete-once",
    )
    assert second.replayed and second.processing_job_id == first.processing_job_id
    assert prepared.scanner.calls == 1
    assert (
        prepared.state.db.scalar(select(func.count()).select_from(Job)) == 1
        and prepared.state.db.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action == "media.upload_completed")
        )
        == audit_count
    )
    with pytest.raises(MediaConflict):
        await prepared.coordinator.complete(
            prepared.state.editor,
            program_id=prepared.state.program,
            upload_id=prepared.upload.upload_id,
            idempotency_key="different-command",
        )


async def test_unclean_scan_fails_canonical_version_and_never_queues(selection, tmp_path):
    prepared = await _prepared(selection, tmp_path, clean=False)
    result = await prepared.coordinator.complete(
        prepared.state.editor,
        program_id=prepared.state.program,
        upload_id=prepared.upload.upload_id,
        idempotency_key="reject-lesson",
    )
    version = prepared.state.db.get(MediaVersion, prepared.upload.media_version_id)
    assert result.state.value == "failed" and result.processing_job_id is None
    assert version.state == "failed" and version.processing_error == "MALWARE_DETECTED"
    assert prepared.state.db.scalar(select(func.count()).select_from(Job)) == 0


async def test_revoked_course_authority_before_commit_preserves_uploading_state(
    selection, tmp_path, monkeypatch
):
    prepared = await _prepared(selection, tmp_path)
    original = prepared.coordinator._commit

    async def revoke_then_commit(*args, **kwargs):
        await prepared.state.app.revoke(
            prepared.state.actor,
            grant_id=prepared.state.write_grant.id,
            command_id=uuid4(),
            reason="Synthetic assignment ended during scan",
        )
        return await original(*args, **kwargs)

    monkeypatch.setattr(prepared.coordinator, "_commit", revoke_then_commit)
    with pytest.raises(CapabilityDenied):
        await prepared.coordinator.complete(
            prepared.state.editor,
            program_id=prepared.state.program,
            upload_id=prepared.upload.upload_id,
            idempotency_key="revoked-before-commit",
        )
    intent = prepared.state.db.get(MediaUploadIntent, prepared.upload.upload_id)
    assert intent.state == "uploading"
    assert intent.completion_fingerprint is None
    assert prepared.state.db.scalar(select(func.count()).select_from(Job)) == 0


async def test_asset_retired_during_scan_cannot_be_resurrected(selection, tmp_path, monkeypatch):
    prepared = await _prepared(selection, tmp_path)
    original = prepared.coordinator._commit

    async def retire_then_commit(*args, **kwargs):
        asset = prepared.state.db.get(MediaAsset, prepared.upload.media_id)
        asset.state = MediaLifecycle.RETIRED.value
        prepared.state.db.flush()
        return await original(*args, **kwargs)

    monkeypatch.setattr(prepared.coordinator, "_commit", retire_then_commit)
    with pytest.raises(MediaConflict, match="retired"):
        await prepared.coordinator.complete(
            prepared.state.editor,
            program_id=prepared.state.program,
            upload_id=prepared.upload.upload_id,
            idempotency_key="retired-before-commit",
        )
    intent = prepared.state.db.get(MediaUploadIntent, prepared.upload.upload_id)
    asset = prepared.state.db.get(MediaAsset, prepared.upload.media_id)
    assert intent.state == MediaLifecycle.UPLOADING.value
    assert asset.state == MediaLifecycle.RETIRED.value
    assert prepared.state.db.scalar(select(func.count()).select_from(Job)) == 0


async def test_plain_service_cannot_present_a_forged_completion_authorization(selection, tmp_path):
    prepared = await _prepared(selection, tmp_path)
    intent = prepared.state.db.get(MediaUploadIntent, prepared.upload.upload_id)
    with pytest.raises(MediaForbidden):
        prepared.state.service.complete_upload(
            prepared.state.db,
            prepared.state.editor,
            intent.id,
            request=SimpleNamespace(),
            idempotency_key="forged",
            studio_authorization=object(),
        )


async def test_cancellation_releases_storage_guard_and_completion_capacity(selection, tmp_path):
    prepared = await _prepared(selection, tmp_path)
    blocking = _BlockingScanner(prepared.sessions)
    prepared.state.service.scanner = blocking
    task = asyncio.create_task(
        prepared.coordinator.complete(
            prepared.state.editor,
            program_id=prepared.state.program,
            upload_id=prepared.upload.upload_id,
            idempotency_key="cancelled-completion",
        )
    )
    assert await asyncio.to_thread(blocking.started.wait, 5)
    task.cancel()
    await asyncio.sleep(0.05)
    assert not task.done()
    assert prepared.coordinator.limiter.borrowed_tokens == 1
    blocking.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    prepared.state.service.scanner = _ObservedScanner(prepared.sessions)
    retry = await prepared.coordinator.complete(
        prepared.state.editor,
        program_id=prepared.state.program,
        upload_id=prepared.upload.upload_id,
        idempotency_key="cancelled-completion",
    )
    assert retry.state is MediaLifecycle.PROCESSING
    assert prepared.coordinator.limiter.borrowed_tokens == 0


async def test_cancellation_during_hash_releases_acquired_guard_and_capacity(
    selection, tmp_path, monkeypatch
):
    prepared = await _prepared(selection, tmp_path)
    coordinator = StudioVideoCompletion(
        prepared.sessions, prepared.state.service, prepared.storage, max_active=1
    )
    started, release = Event(), Event()
    original_inspect = prepared.storage._inspect

    def paused_inspect(object_key):
        started.set()
        assert release.wait(timeout=10)
        return original_inspect(object_key)

    monkeypatch.setattr(prepared.storage, "_inspect", paused_inspect)
    task = asyncio.create_task(
        coordinator.complete(
            prepared.state.editor,
            program_id=prepared.state.program,
            upload_id=prepared.upload.upload_id,
            idempotency_key="cancelled-hash",
        )
    )
    assert await asyncio.to_thread(started.wait, 5)
    task.cancel()
    await asyncio.sleep(0.05)
    assert not task.done()
    assert coordinator.limiter.borrowed_tokens == 1
    with pytest.raises(MediaQuotaExceeded):
        await coordinator.complete(
            prepared.state.editor,
            program_id=prepared.state.program,
            upload_id=prepared.upload.upload_id,
            idempotency_key="capacity-still-owned",
        )
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    monkeypatch.setattr(prepared.storage, "_inspect", original_inspect)
    retry = await coordinator.complete(
        prepared.state.editor,
        program_id=prepared.state.program,
        upload_id=prepared.upload.upload_id,
        idempotency_key="cancelled-hash",
    )
    assert retry.state is MediaLifecycle.PROCESSING
    assert coordinator.limiter.borrowed_tokens == 0


async def test_third_active_completion_is_rejected_and_failure_releases_slot(
    selection, tmp_path, monkeypatch
):
    prepared = await _prepared(selection, tmp_path)
    coordinator = StudioVideoCompletion(
        prepared.sessions, prepared.state.service, prepared.storage, max_active=2
    )
    entered, release = 0, asyncio.Event()
    two_entered = asyncio.Event()

    async def held(*_args, idempotency_key, **_kwargs):
        nonlocal entered
        entered += 1
        if entered == 2:
            two_entered.set()
        await release.wait()
        if idempotency_key == "first":
            raise RuntimeError("synthetic bounded failure")
        return object()

    monkeypatch.setattr(coordinator, "_complete_admitted", held)
    first = asyncio.create_task(
        coordinator.complete(
            prepared.state.editor,
            program_id=prepared.state.program,
            upload_id=prepared.upload.upload_id,
            idempotency_key="first",
        )
    )
    second = asyncio.create_task(
        coordinator.complete(
            prepared.state.editor,
            program_id=prepared.state.program,
            upload_id=prepared.upload.upload_id,
            idempotency_key="second",
        )
    )
    await asyncio.wait_for(two_entered.wait(), 2)
    with pytest.raises(MediaQuotaExceeded):
        await coordinator.complete(
            prepared.state.editor,
            program_id=prepared.state.program,
            upload_id=prepared.upload.upload_id,
            idempotency_key="third",
        )
    release.set()
    outcomes = await asyncio.gather(first, second, return_exceptions=True)
    assert any(isinstance(item, RuntimeError) for item in outcomes)
    assert coordinator.limiter.borrowed_tokens == 0


async def test_completion_concurrency_cannot_be_configured_above_two(selection, tmp_path):
    prepared = await _prepared(selection, tmp_path)
    with pytest.raises(ValueError, match="one or two"):
        StudioVideoCompletion(
            prepared.sessions,
            prepared.state.service,
            prepared.storage,
            max_active=3,
        )
