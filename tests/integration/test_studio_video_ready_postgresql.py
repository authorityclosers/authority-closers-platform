"""Real admitted/scanned upload -> FFmpeg -> fenced READY in a disposable DB.

The source is a generated 1.25-second 320x180 test clip, NOT 4K or a lecture.
Signature scanning is explicit test composition, not production antivirus.
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import subprocess
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from threading import get_ident
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository, verify_audit_chain_sync
from ac_platform.media.errors import MediaConflict, MediaForbidden, MediaProcessingError
from ac_platform.media.models import (
    ActivityMediaBinding,
    MediaAsset,
    MediaRendition,
    MediaUploadIntent,
    MediaVersion,
)
from ac_platform.media.processing import FFmpegMediaProcessor, ProcessingQuota, TranscodeProfile
from ac_platform.media.scanner import SignatureContentScanner
from ac_platform.media.service import MediaService
from ac_platform.media.signing import MediaSigner
from ac_platform.media.studio_upload import StudioVideoUploadRequest, StudioVideoUploads
from ac_platform.media.studio_video_completion import (
    MEDIA_PROCESS_VERSION_JOB,
    StudioVideoCompletion,
)
from ac_platform.media.studio_video_processing import StudioVideoProcessing
from ac_platform.media.studio_video_worker import StudioVideoJobWorker
from ac_platform.media.video_file_storage import VideoFileStorage
from ac_platform.outbox.models import Job
from ac_platform.outbox.policy import ReconciliationRequiredError
from ac_platform.outbox.repository import JobRepository, LeaseLostError, RecoveryStateRepository
from tests.integration.test_ffmpeg_video_attempts import _decode, _materialize_attempt
from tests.integration.test_media_delivery_renewal_postgresql import (
    _run_async,
)
from tests.integration.test_media_delivery_renewal_postgresql import (
    postgres_harness as _postgres_harness,
)
from tests.integration.test_studio_draft_authoring_postgresql import seed

pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="requires FFmpeg + ffprobe"
)


@pytest.fixture
def postgres_harness():
    # Per test: stale queued jobs and restore-generation changes stay isolated.
    yield from _postgres_harness.__wrapped__()


def _clip(tmp_path: Path) -> bytes:
    path = tmp_path / "synthetic.mp4"
    subprocess.run(  # noqa: S603 - fixed executable and generated test path
        [  # noqa: S607 - controlled local executable on the test host PATH
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x180:r=24:d=1.25",
            "-c:v",
            "libx264",
            "-threads",
            "1",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=30,
    )
    return path.read_bytes()


async def admitted(sessions, tmp_path: Path, data: bytes):
    state = await seed(sessions)
    actor = replace(
        state.actors[0], permissions=frozenset({"recovery_reconcile", "global_recovery_reconcile"})
    )
    async with sessions() as database, database.begin():
        await RecoveryStateRepository(database).reconcile(
            actor=actor,
            reason="Isolated worker test fixture reconciliation",
            audit=AuditRepository(database),
            operations_tenant_id=state.tenant_id,
        )
    storage = VideoFileStorage(
        root=tmp_path / "video-objects", max_object_bytes=8 * 1024**2, max_store_bytes=32 * 1024**2
    )
    quota = ProcessingQuota(
        max_source_bytes=1024**2,
        max_output_bytes=8 * 1024**2,
        max_renditions=2,
        max_duration_seconds=5,
        max_output_files=16,
        max_temp_bytes=16 * 1024**2,
    )
    processor = FFmpegMediaProcessor(
        profiles=(TranscodeProfile("180p", 160, 90, 200),), quota=quota
    )
    service = MediaService(
        storage=storage,
        processor=processor,
        processing_quota=quota,
        signer=MediaSigner("worker-fixture-synthetic-signing-key-long-enough"),
        scanner=SignatureContentScanner(),
        webhook_secret="worker-fixture-synthetic-webhook-key-long-enough",  # noqa: S106
    )
    checksum = hashlib.sha256(data).hexdigest()
    async with sessions() as database, database.begin():
        upload = await StudioVideoUploads(database, service).create(
            state.actors[0],
            program_id=state.program_id,
            body=StudioVideoUploadRequest(
                filename="Synthetic test clip.mp4",
                content_type="video/mp4",
                content_length=len(data),
                checksum_sha256=checksum,
            ),
            idempotency_key=uuid4().hex,
        )
        version = await database.get(MediaVersion, upload.media_version_id)
        assert version is not None
        key = version.object_key
    storage.put_stream(
        object_key=key,
        chunks=(data,),
        content_type="video/mp4",
        content_length=len(data),
        checksum_sha256=checksum,
    )
    receipt = await StudioVideoCompletion(sessions, service, storage).complete(
        state.actors[0],
        program_id=state.program_id,
        upload_id=upload.upload_id,
        idempotency_key="complete-generated-clip",
    )
    return state, service, upload, receipt


@pytest.mark.parametrize(
    "outcome", ["ready", "retired", "changed_payload", "lease_expired", "restore_hold"]
)
def test_real_encoded_result_commits_only_for_current_admission_and_live_lease(
    postgres_harness: Any,
    tmp_path: Path,
    outcome: str,
) -> None:
    data = _clip(tmp_path)

    async def run():
        engine = create_async_engine(postgres_harness.schema_url, pool_size=3, max_overflow=0)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        verified = None
        try:
            state, service, upload, receipt = await admitted(sessions, tmp_path, data)
            pipeline = StudioVideoProcessing(service)
            async with sessions() as database, database.begin():
                jobs = await JobRepository(database).claim(
                    kinds=frozenset({MEDIA_PROCESS_VERSION_JOB}), limit=1
                )
                assert len(jobs) == 1 and jobs[0].id == receipt.processing_job_id
                prepared = await database.run_sync(lambda sync: pipeline.prepare(sync, jobs[0]))
            assert engine.pool.checkedout() == 0
            # This synchronous call and its guards stay on this one test thread.
            # Production worker must bridge a dedicated thread without open DB tx.
            verified = pipeline.process(prepared, attempt_id=uuid4())
            assert engine.pool.checkedout() == 0
            inventory = verified.result.object_keys
            prefix = f"{prepared.object_key}/attempts/{verified.attempt_id}"
            if outcome == "retired":
                async with sessions() as database, database.begin():
                    asset = await database.get(MediaAsset, upload.media_id)
                    asset.state = "retired"  # isolated fixture revocation during work
            elif outcome == "changed_payload":
                async with sessions() as database, database.begin():
                    job = await database.get(Job, prepared.job_id)
                    job.payload = {**job.payload, "source_checksum_sha256": "a" * 64}
            elif outcome == "lease_expired":
                async with sessions() as database, database.begin():
                    job = await database.get(Job, prepared.job_id)
                    job.leased_until = func.clock_timestamp() - timedelta(seconds=1)
            elif outcome == "restore_hold":
                async with sessions() as database, database.begin():
                    await RecoveryStateRepository(database).mark_restore(
                        reason="isolated test hold"
                    )

            pending_commit, allow_commit = asyncio.Event(), asyncio.Event()

            async def finalize():
                async with sessions() as database, database.begin():
                    await pipeline.finalize(database, prepared, verified)
                    if outcome == "ready":
                        pending_commit.set()
                        await asyncio.wait_for(allow_commit.wait(), 5)
                    await JobRepository(database).complete(prepared.job_id, prepared.lease_token)

            if outcome == "ready":
                task = asyncio.create_task(finalize())
                try:
                    await asyncio.wait_for(pending_commit.wait(), 5)
                    with pytest.raises(MediaForbidden):
                        pipeline.discard(verified)
                    with pytest.raises(MediaForbidden):
                        pipeline.release(verified)
                finally:
                    allow_commit.set()
                    await task
                with pytest.raises(MediaForbidden):
                    pipeline.discard(verified)  # commit is known, even before release
                pipeline.release(verified)
                with pytest.raises(MediaForbidden):
                    pipeline.discard(verified)  # released proof cannot delete committed video
                verified = None
                keys, folder = _materialize_attempt(
                    service.storage, prefix=prefix, destination=tmp_path / "encoded"
                )
                assert keys == set(inventory)
                _decode(folder / "renditions" / "master.m3u8")
                _decode(folder / "renditions" / "progressive.mp4")
            else:
                with pytest.raises(
                    (MediaConflict, MediaForbidden, LeaseLostError, ReconciliationRequiredError)
                ):
                    await finalize()
                pipeline.discard(verified)
                verified = None
                assert service.storage.list_prefix(prefix) == ()
            assert service.storage.read(prepared.object_key) == data
            async with sessions() as database:
                version = await database.get(MediaVersion, upload.media_version_id)
                intent = await database.get(MediaUploadIntent, upload.upload_id)
                asset = await database.get(MediaAsset, upload.media_id)
                job = await database.get(Job, receipt.processing_job_id)
                assert (
                    version.state
                    == intent.state
                    == ("ready" if outcome == "ready" else "processing")
                )
                assert (asset.current_version_id == version.id) is (outcome == "ready")
                assert (job.status == "succeeded") is (outcome == "ready")
                count = await database.scalar(
                    select(func.count())
                    .select_from(MediaRendition)
                    .where(MediaRendition.version_id == version.id)
                )
                assert count == (2 if outcome == "ready" else 0)
                audits = await database.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.action == "media.studio_video_processed")
                )
                assert audits == (1 if outcome == "ready" else 0)
                assert (
                    await database.scalar(select(func.count()).select_from(ActivityMediaBinding))
                    == 0
                )
                if outcome == "ready":
                    assert 1.0 < version.duration_seconds < 2.0
                    assert (version.width, version.height) == (320, 180)
                chain = await database.run_sync(
                    lambda sync: verify_audit_chain_sync(sync, tenant_id=state.tenant_id)
                )
                assert chain.valid
        finally:
            if verified is not None:
                pipeline.discard(verified)
            await engine.dispose()

    _run_async(run())


@pytest.mark.parametrize("failure_event", ["before_commit", "after_commit"])
def test_concrete_worker_commit_uncertainty_closes_transaction_before_guard_release(
    postgres_harness: Any,
    tmp_path: Path,
    monkeypatch,
    failure_event: str,
) -> None:
    data = _clip(tmp_path)

    async def run():
        engine = create_async_engine(postgres_harness.schema_url, pool_size=3, max_overflow=0)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            _, service, upload, receipt = await admitted(sessions, tmp_path, data)
            pipeline = StudioVideoProcessing(service)
            finalize = pipeline.finalize

            async def uncertain(database, prepared, verified):
                await finalize(database, prepared, verified)

                def interrupt_commit(current):
                    raise RuntimeError("synthetic transaction outcome uncertainty")

                event.listen(database.sync_session, failure_event, interrupt_commit)

            monkeypatch.setattr(pipeline, "finalize", uncertain)
            result = await StudioVideoJobWorker(sessions, pipeline).run_once()
            assert result.claimed == 1
            assert not pipeline._verified  # no leaked guards/executor after either outcome
            async with sessions() as database:
                job = await database.get(Job, receipt.processing_job_id)
                version = await database.get(MediaVersion, upload.media_version_id)
                renditions = (
                    await database.scalars(
                        select(MediaRendition).where(MediaRendition.version_id == version.id)
                    )
                ).all()
                if failure_event == "after_commit":
                    assert job.status == "succeeded" and version.state == "ready"
                    assert len(renditions) == 2
                    assert all(
                        service.storage.head(item.object_key) is not None for item in renditions
                    )
                else:
                    assert job.status == "retry_wait" and version.state == "processing"
                    assert not renditions
                # Unknown commit retains attempt files but every stripe is released.
                keys = service.storage.list_prefix(version.object_key)
                with service.storage.hold_verifications(keys):
                    pass
        finally:
            await engine.dispose()

    _run_async(run())


@pytest.mark.parametrize("maximum_attempts", [1, 2])
def test_worker_failed_encode_projects_terminal_failure_without_publishing_or_exposing_error(
    postgres_harness: Any,
    tmp_path: Path,
    monkeypatch,
    maximum_attempts: int,
) -> None:
    data = _clip(tmp_path)

    async def run():
        engine = create_async_engine(postgres_harness.schema_url, pool_size=3, max_overflow=0)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            _, service, upload, receipt = await admitted(sessions, tmp_path, data)
            async with sessions() as database, database.begin():
                job = await database.get(Job, receipt.processing_job_id)
                job.max_attempts = maximum_attempts  # explicit fixture bound, not operational edits

            def failed(command, cwd):
                raise MediaProcessingError(
                    "synthetic private filesystem detail not for queue storage"
                )

            monkeypatch.setattr(service.processor, "command_runner", failed)
            pipeline = StudioVideoProcessing(service)
            result = await StudioVideoJobWorker(sessions, pipeline).run_once()
            assert result.claimed == 1 and result.succeeded == 0
            assert result.dead_lettered == int(maximum_attempts == 1)
            assert result.retried == int(maximum_attempts == 2)
            async with sessions() as database:
                version = await database.get(MediaVersion, upload.media_version_id)
                intent = await database.get(MediaUploadIntent, upload.upload_id)
                asset = await database.get(MediaAsset, upload.media_id)
                job = await database.get(Job, receipt.processing_job_id)
                terminal = maximum_attempts == 1
                assert (
                    version.state
                    == intent.state
                    == asset.state
                    == ("failed" if terminal else "processing")
                )
                assert version.processing_error == (
                    "STUDIO_VIDEO_PROCESSING_FAILED" if terminal else None
                )
                assert asset.current_version_id is None
                assert "synthetic private filesystem" not in str(job.last_error)
                assert await database.scalar(select(func.count()).select_from(MediaRendition)) == 0
                assert await database.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.action == "media.studio_video_processing_failed")
                ) == int(terminal)
                assert (
                    await database.scalar(select(func.count()).select_from(ActivityMediaBinding))
                    == 0
                )
                assert service.storage.list_prefix(version.object_key) == (version.object_key,)
            assert not pipeline._verified
        finally:
            await engine.dispose()

    _run_async(run())


def test_concrete_job_worker_encodes_without_open_db_and_releases_on_own_thread(
    postgres_harness: Any,
    tmp_path: Path,
    monkeypatch,
) -> None:
    data = _clip(tmp_path)

    async def run():
        engine = create_async_engine(postgres_harness.schema_url, pool_size=3, max_overflow=0)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            state, service, upload, receipt = await admitted(sessions, tmp_path, data)
            pipeline = StudioVideoProcessing(service)
            process, release = pipeline.process, pipeline.release
            threads, outputs = {}, {}
            main_thread = get_ident()

            def observed_process(prepared, *, attempt_id):
                threads["process"] = get_ident()
                assert threads["process"] != main_thread
                assert engine.pool.checkedout() == 0
                result = process(prepared, attempt_id=attempt_id)
                outputs["prefix"] = f"{prepared.object_key}/attempts/{attempt_id}"
                outputs["keys"] = result.result.object_keys
                return result

            def observed_release(verified):
                threads["release"] = get_ident()
                assert threads["release"] == threads["process"]
                assert engine.pool.checkedout() == 0
                release(verified)

            monkeypatch.setattr(pipeline, "process", observed_process)
            monkeypatch.setattr(pipeline, "release", observed_release)
            worker = StudioVideoJobWorker(sessions, pipeline)
            first = await worker.run_once()
            assert first.claimed == first.succeeded == 1
            assert first.retried == first.dead_lettered == first.fenced == first.release_failed == 0
            second = await worker.run_once()
            assert second.claimed == 0 and not pipeline._verified
            assert threads["process"] == threads["release"]
            keys, folder = _materialize_attempt(
                service.storage, prefix=outputs["prefix"], destination=tmp_path / "worker-encoded"
            )
            assert keys == set(outputs["keys"])
            _decode(folder / "renditions" / "master.m3u8")
            _decode(folder / "renditions" / "progressive.mp4")
            async with sessions() as database:
                job = await database.get(Job, receipt.processing_job_id)
                version = await database.get(MediaVersion, upload.media_version_id)
                assert job.status == "succeeded" and version.state == "ready"
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(AuditEvent)
                        .where(
                            AuditEvent.tenant_id == state.tenant_id,
                            AuditEvent.action == "media.studio_video_processed",
                        )
                    )
                    == 1
                )
                assert (
                    await database.scalar(select(func.count()).select_from(ActivityMediaBinding))
                    == 0
                )
        finally:
            await engine.dispose()

    _run_async(run())
