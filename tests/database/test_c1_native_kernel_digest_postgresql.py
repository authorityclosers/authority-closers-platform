"""C1 publication accepts exactly the reviewed AudioAtlas kernels, through the real worker.

The FFT swap changed the compiled kernel's source digest. C1 checkpoints recorded by the
original kernel (and C1 produced by a native image that still runs it) must keep
publishing: a retry, lease recovery or re-analysis republishes the cached payload through
``ConversationApplication.publish_checkpoint``. An unreviewed kernel digest must not.
Narrowing or dropping ``ACCEPTED_NATIVE_SOURCE_SHA256`` in that check fails these tests.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.conversation_intelligence import worker as worker_module
from ac_platform.conversation_intelligence.application import AUDIOATLAS_RECIPE
from ac_platform.conversation_intelligence.checkpoints import (
    SourceBinding,
    build_checkpoint,
    content_hash,
)
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationRecording,
)
from ac_platform.conversation_intelligence.signals import (
    LEGACY_NATIVE_SOURCE_SHA256,
    NATIVE_SOURCE_SHA256,
    inspect_media,
)
from ac_platform.conversation_intelligence.storage import ObjectKey, ObjectKind
from ac_platform.outbox.models import Job
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_worker_postgresql import (
    Prepared,
    _assert_scratch_empty,
    _db_run,
    _postgres_harness,
    _prepare,
)

UNREVIEWED_KERNEL_SHA256 = "e" * 64


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


def _receipt_from(kernel_sha256: str) -> Any:
    """Real extraction whose receipt names another kernel build, as an older image would."""

    def inspect(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = inspect_media(*args, **kwargs)
        result["native_receipt"]["source_sha256"] = kernel_sha256
        return result

    return inspect


async def _c1(sessions: async_sessionmaker[AsyncSession], recording_id: UUID) -> Any:
    async with sessions() as database:
        return (
            await database.scalars(
                select(ConversationCheckpoint).where(
                    ConversationCheckpoint.recording_id == recording_id,
                    ConversationCheckpoint.stage == "C1",
                )
            )
        ).all()


async def _seed_cached_c1(
    sessions: async_sessionmaker[AsyncSession],
    prepared: Prepared,
    work: Path,
    kernel_sha256: str,
) -> UUID:
    """Store a self-consistent C1 checkpoint and feature blob recorded by another kernel.

    Checkpoint rows are immutable, so this inserts what an earlier run with that kernel
    would have left: the same C0/C1 identities the worker derives, a matching payload
    hash and manifest, and the verified feature object. The worker then finds it by
    cache key and republishes it, so only publication's kernel-digest rule decides.
    """
    async with sessions() as database:
        recording = await database.get(ConversationRecording, prepared.recording_id)
        assert recording is not None
    binding = SourceBinding(
        str(recording.tenant_id),
        str(recording.id),
        recording.source_sha256,
        str(recording.source_revision),
    )
    c0_payload = {
        "source_sha256": recording.source_sha256,
        "source_bytes": recording.source_bytes,
        "content_type": recording.content_type,
        "permission_reference": str(recording.permission_id),
    }
    c0 = build_checkpoint(binding, "C0", "recording-v1", {}, (), content_hash(c0_payload))
    source = work / "source.wav"
    source.write_bytes(prepared.data)
    payload = inspect_media(source, work / "c1", rate=48000)
    payload["native_receipt"]["source_sha256"] = kernel_sha256
    c1 = build_checkpoint(
        binding,
        "C1",
        AUDIOATLAS_RECIPE,
        {"decode_rate": 48000, "window_profile": "audioatlas-40ms-10ms"},
        (c0,),
        content_hash(payload),
    )
    blob_id = uuid4()
    features = (work / "c1" / "features.aaf").read_bytes()
    prepared.storage.put(
        ObjectKey(recording.tenant_id, recording.id, blob_id, ObjectKind.SIGNAL_FEATURES),
        iter((features,)),
        expected_sha256=payload["feature_sha256"],
        expected_bytes=len(features),
    )
    async with sessions() as database, database.begin():
        database.add(
            ConversationCheckpoint(
                id=uuid4(),
                recording_id=recording.id,
                tenant_id=recording.tenant_id,
                person_id=recording.person_id,
                cache_key=c1.cache_key,
                manifest_sha256=c1.manifest_sha256,
                payload_sha256=c1.payload_sha256,
                stage="C1",
                feature_blob_id=blob_id,
                manifest=c1.as_dict(),
                payload=payload,
                created_at=datetime.now(UTC),
            )
        )
    return blob_id


class ExtractorMustNotRun:
    """A cache miss would re-extract; record it so it cannot pass as a refusal."""

    called = False

    def __call__(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.called = True
        raise AssertionError("a cached C1 reuse unexpectedly re-extracted the media")


@pytest.mark.parametrize(
    "kernel_sha256",
    [LEGACY_NATIVE_SOURCE_SHA256, NATIVE_SOURCE_SHA256],
    ids=["original-kernel", "pocketfft-kernel"],
)
def test_fresh_c1_from_each_reviewed_kernel_publishes(
    postgres_harness: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kernel_sha256: str,
) -> None:
    async def exercise() -> None:
        prepared = await _prepare(postgres_harness, tmp_path)
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            monkeypatch.setattr(worker_module, "inspect_media", _receipt_from(kernel_sha256))
            assert await prepared.worker.run_once()
            assert (await _db_run(sessions, prepared.run_id)).state == "completed"
            (c1,) = await _c1(sessions, prepared.recording_id)
            assert c1.payload["native_receipt"]["source_sha256"] == kernel_sha256
            _assert_scratch_empty(prepared.scratch)
        finally:
            await engine.dispose()
            await prepared.worker.sessions.kw["bind"].dispose()

    run(exercise())


def test_fresh_c1_from_an_unreviewed_kernel_is_refused(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        prepared = await _prepare(postgres_harness, tmp_path)
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            monkeypatch.setattr(
                worker_module, "inspect_media", _receipt_from(UNREVIEWED_KERNEL_SHA256)
            )
            with pytest.raises(RuntimeError, match="local conversation job failed"):
                await prepared.worker.run_once()
            execution = await _db_run(sessions, prepared.run_id)
            assert execution.state != "completed"
            assert await _c1(sessions, prepared.recording_id) == []
            async with sessions() as database:
                assert (
                    await database.scalar(select(Job.status).where(Job.id == execution.job_id))
                    != "succeeded"
                )
            _assert_scratch_empty(prepared.scratch)
        finally:
            await engine.dispose()
            await prepared.worker.sessions.kw["bind"].dispose()

    run(exercise())


def test_cached_c1_recorded_by_the_original_kernel_is_reused(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        prepared = await _prepare(postgres_harness, tmp_path)
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            seed = tmp_path / "seed"
            seed.mkdir()
            blob_id = await _seed_cached_c1(sessions, prepared, seed, LEGACY_NATIVE_SOURCE_SHA256)
            extractor = ExtractorMustNotRun()
            monkeypatch.setattr(worker_module, "inspect_media", extractor)
            assert await prepared.worker.run_once()
            assert not extractor.called
            assert (await _db_run(sessions, prepared.run_id)).state == "completed"
            (c1,) = await _c1(sessions, prepared.recording_id)
            assert c1.feature_blob_id == blob_id
            assert c1.payload["native_receipt"]["source_sha256"] == LEGACY_NATIVE_SOURCE_SHA256
            _assert_scratch_empty(prepared.scratch)
        finally:
            await engine.dispose()
            await prepared.worker.sessions.kw["bind"].dispose()

    run(exercise())


def test_cached_c1_recorded_by_an_unreviewed_kernel_is_refused(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        prepared = await _prepare(postgres_harness, tmp_path)
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            seed = tmp_path / "seed"
            seed.mkdir()
            await _seed_cached_c1(sessions, prepared, seed, UNREVIEWED_KERNEL_SHA256)
            extractor = ExtractorMustNotRun()
            monkeypatch.setattr(worker_module, "inspect_media", extractor)
            with pytest.raises(RuntimeError, match="local conversation job failed"):
                await prepared.worker.run_once()
            # Refused at publication of the cached payload, not by a cache miss.
            assert not extractor.called
            execution = await _db_run(sessions, prepared.run_id)
            assert execution.state != "completed"
            async with sessions() as database:
                assert (
                    await database.scalar(select(Job.status).where(Job.id == execution.job_id))
                    != "succeeded"
                )
            _assert_scratch_empty(prepared.scratch)
        finally:
            await engine.dispose()
            await prepared.worker.sessions.kw["bind"].dispose()

    run(exercise())
