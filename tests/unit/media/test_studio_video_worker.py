from __future__ import annotations

import asyncio
from datetime import timedelta
from threading import Event, get_ident
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from ac_platform.media.studio_video_completion import MEDIA_PROCESS_VERSION_JOB
from ac_platform.media.studio_video_processing import PreparedStudioVideo, VerifiedStudioVideo
from ac_platform.media.studio_video_worker import (
    StudioVideoJobLease,
    StudioVideoJobWorker,
    StudioVideoPipeline,
    StudioVideoWorkerResult,
)
from ac_platform.outbox.errors import LeaseLostError


class _ThreadPipeline:
    def __init__(self, *, blocked: bool = False) -> None:
        self.started = Event()
        self.finish = Event()
        self.blocked = blocked
        self.process_thread: int | None = None
        self.release_thread: int | None = None
        self.discard_thread: int | None = None

    def process(self, _prepared: PreparedStudioVideo, *, attempt_id: UUID) -> VerifiedStudioVideo:
        assert attempt_id.int
        self.process_thread = get_ident()
        self.started.set()
        if self.blocked:
            assert self.finish.wait(5)
        return cast(VerifiedStudioVideo, object())

    def release(self, _verified: VerifiedStudioVideo) -> None:
        self.release_thread = get_ident()

    def discard(self, _verified: VerifiedStudioVideo) -> None:
        self.discard_thread = get_ident()

    def prepare(
        self, _database: Any, _job: Any
    ) -> PreparedStudioVideo:  # pragma: no cover - overridden by harness
        raise AssertionError

    async def finalize(
        self, _database: Any, _prepared: Any, _verified: Any
    ) -> None:  # pragma: no cover
        raise AssertionError

    async def record_failure(
        self, _database: Any, _job: Any, *, terminal: bool
    ) -> None:  # pragma: no cover
        raise AssertionError(terminal)


class _HarnessWorker(StudioVideoJobWorker):
    def __init__(self, pipeline: _ThreadPipeline, *, lose_heartbeat: bool = False) -> None:
        super().__init__(
            cast(Any, lambda: None),
            cast(StudioVideoPipeline, pipeline),
            lease_for=timedelta(seconds=1),
            heartbeat_every=timedelta(milliseconds=10),
        )
        self.lease = StudioVideoJobLease(uuid4(), uuid4(), 7)
        self.prepared = cast(
            PreparedStudioVideo,
            SimpleNamespace(
                job_id=self.lease.job_id,
                lease_token=self.lease.lease_token,
                recovery_generation=self.lease.recovery_generation,
                tenant_id=None,
            ),
        )
        self.lose_heartbeat = lose_heartbeat

    async def _claim_one(self) -> StudioVideoJobLease | None:
        return self.lease

    async def _prepare(self, _lease: StudioVideoJobLease) -> PreparedStudioVideo:
        return self.prepared

    async def _renew(self, _lease: StudioVideoJobLease) -> None:
        if self.lose_heartbeat:
            raise LeaseLostError("synthetic reclaimed lease")

    async def _finalize(self, _lease: Any, _prepared: Any, processed: Any) -> None:
        await self._release(processed)

    async def _fail(self, _lease: Any, _error: Any) -> StudioVideoWorkerResult:  # pragma: no cover
        raise AssertionError("thread harness failures must be fenced before job mutation")


class _AcquireFails:
    async def __aenter__(self) -> Any:
        raise RuntimeError("synthetic session acquisition failure")

    async def __aexit__(self, *_args: Any) -> None:
        return None


class _BeginFails:
    async def __aenter__(self) -> _BeginFails:
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None

    async def begin(self) -> Any:
        raise RuntimeError("synthetic transaction begin failure")


def test_worker_has_only_the_studio_processing_kind_and_no_default_dispatcher() -> None:
    pipeline = _ThreadPipeline()
    worker = _HarnessWorker(pipeline)
    assert worker.allowed_job_kinds == frozenset({MEDIA_PROCESS_VERSION_JOB})
    assert not hasattr(worker, "_dispatcher")


@pytest.mark.asyncio
async def test_processing_and_guard_release_share_a_private_worker_thread() -> None:
    pipeline = _ThreadPipeline()
    worker = _HarnessWorker(pipeline)
    event_loop_thread = get_ident()

    result = await worker.run_once()

    assert result == StudioVideoWorkerResult(claimed=1, succeeded=1)
    assert pipeline.process_thread is not None
    assert pipeline.process_thread != event_loop_thread
    assert pipeline.release_thread == pipeline.process_thread
    assert pipeline.discard_thread is None


@pytest.mark.asyncio
async def test_native_cancellation_drains_encoding_before_releasing_guard() -> None:
    pipeline = _ThreadPipeline(blocked=True)
    worker = _HarnessWorker(pipeline)
    task = asyncio.create_task(worker.run_once())
    try:
        assert await asyncio.to_thread(pipeline.started.wait, 5)
        task.cancel()
        await asyncio.sleep(0.05)
        assert not task.done()
        assert pipeline.release_thread is None
        assert await worker.run_once() == StudioVideoWorkerResult(busy=1)
    finally:
        pipeline.finish.set()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert pipeline.release_thread == pipeline.process_thread
    assert pipeline.discard_thread is None
    assert await worker.run_once() == StudioVideoWorkerResult(claimed=1, succeeded=1)


@pytest.mark.asyncio
async def test_lost_heartbeat_waits_for_encoding_then_discards_on_its_thread() -> None:
    pipeline = _ThreadPipeline(blocked=True)
    worker = _HarnessWorker(pipeline, lose_heartbeat=True)
    task = asyncio.create_task(worker.run_once())
    try:
        assert await asyncio.to_thread(pipeline.started.wait, 5)
        await asyncio.sleep(0.05)
        assert not task.done()
        assert pipeline.discard_thread is None
    finally:
        pipeline.finish.set()

    result = await task
    assert result == StudioVideoWorkerResult(claimed=1, fenced=1)
    assert pipeline.discard_thread == pipeline.process_thread
    assert pipeline.release_thread is None


@pytest.mark.asyncio
@pytest.mark.parametrize("context", [_AcquireFails(), _BeginFails()])
async def test_finalize_setup_failure_discards_and_closes_its_private_executor(
    context: Any,
) -> None:
    pipeline = _ThreadPipeline()
    worker = _HarnessWorker(pipeline)
    processed = await worker._process_with_heartbeat(
        worker.lease,
        worker.prepared,
        attempt_id=uuid4(),
    )
    worker._session_factory = cast(Any, lambda: context)

    with pytest.raises(RuntimeError, match="synthetic"):
        await StudioVideoJobWorker._finalize(
            worker,
            worker.lease,
            worker.prepared,
            processed,
        )

    assert pipeline.discard_thread == pipeline.process_thread
    assert pipeline.release_thread is None
    assert processed.resolved is True
