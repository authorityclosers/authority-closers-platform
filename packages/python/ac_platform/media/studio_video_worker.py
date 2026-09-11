"""One-job local Studio video worker with recovery and lease fencing.

It is never registered with the generic dispatcher or started automatically.
An explicit local Studio runtime may expose this worker for a dedicated runner.
It claims only the exact Studio processing kind, performs blocking encoding
outside database transactions, and drains accepted work before propagating
native cancellation.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractAsyncContextManager, suppress
from dataclasses import dataclass
from datetime import timedelta
from functools import partial
from threading import Lock
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from ac_platform.media.studio_video_completion import MEDIA_PROCESS_VERSION_JOB
from ac_platform.media.studio_video_processing import (
    PreparedStudioVideo,
    VerifiedStudioVideo,
)
from ac_platform.outbox.errors import JobStateError, LeaseLostError
from ac_platform.outbox.models import Job, JobStatus
from ac_platform.outbox.policy import ReconciliationRequiredError
from ac_platform.outbox.repository import JobRepository, RecoveryStateRepository

_MAX_LEASE = timedelta(minutes=15)


class StudioVideoWorkerSessionFactory(Protocol):
    def __call__(self) -> AbstractAsyncContextManager[AsyncSession]:
        """Create one async session for a short worker transaction."""


class StudioVideoPipeline(Protocol):
    def prepare(self, database: Session, job: Job) -> PreparedStudioVideo: ...

    def process(
        self, prepared: PreparedStudioVideo, *, attempt_id: UUID
    ) -> VerifiedStudioVideo: ...

    async def finalize(
        self,
        database: AsyncSession,
        prepared: PreparedStudioVideo,
        verified: VerifiedStudioVideo,
    ) -> None: ...

    async def record_failure(
        self,
        database: AsyncSession,
        job: Job,
        *,
        terminal: bool,
    ) -> None: ...

    def release(self, verified: VerifiedStudioVideo) -> None: ...

    def discard(self, verified: VerifiedStudioVideo) -> None: ...


@dataclass(frozen=True, slots=True)
class StudioVideoJobLease:
    job_id: UUID
    lease_token: UUID
    recovery_generation: int


@dataclass(frozen=True, slots=True)
class StudioVideoWorkerResult:
    claimed: int = 0
    succeeded: int = 0
    retried: int = 0
    dead_lettered: int = 0
    fenced: int = 0
    recovery_held: int = 0
    release_failed: int = 0
    busy: int = 0


class _CommittedReleaseError(RuntimeError):
    """The canonical success committed, but releasing local guards failed."""

    def __init__(self, message: str, *, release_failed: bool) -> None:
        super().__init__(message)
        self.release_failed = release_failed


@dataclass(slots=True)
class _ProcessedStudioVideo:
    verified: VerifiedStudioVideo
    executor: ThreadPoolExecutor
    resolved: bool = False


class StudioVideoJobWorker:
    """Claim and fully resolve at most one Studio video processing job."""

    allowed_job_kinds = frozenset({MEDIA_PROCESS_VERSION_JOB})

    def __init__(
        self,
        session_factory: StudioVideoWorkerSessionFactory,
        pipeline: StudioVideoPipeline,
        *,
        lease_for: timedelta = timedelta(minutes=5),
        heartbeat_every: timedelta = timedelta(seconds=30),
    ) -> None:
        if not timedelta(seconds=1) <= lease_for <= _MAX_LEASE:
            raise ValueError("lease_for must be between one second and fifteen minutes")
        if heartbeat_every <= timedelta(0) or heartbeat_every * 2 >= lease_for:
            raise ValueError("heartbeat_every must be positive and less than half the lease")
        self._session_factory = session_factory
        self.pipeline = pipeline
        self.lease_for = lease_for
        self.heartbeat_every = heartbeat_every
        self.claim_lease_for = min(lease_for, timedelta(seconds=30))
        self._admission = Lock()

    async def run_once(self) -> StudioVideoWorkerResult:
        """Run no more than one exact-kind job; no polling or runtime activation."""

        if not self._admission.acquire(blocking=False):
            return StudioVideoWorkerResult(busy=1)
        try:
            try:
                lease = await self._claim_one()
            except ReconciliationRequiredError:
                return StudioVideoWorkerResult(recovery_held=1)
            if lease is None:
                return StudioVideoWorkerResult()

            owned = asyncio.create_task(
                self._execute(lease),
                name=f"studio-video-job-{lease.job_id}",
            )
            try:
                return await asyncio.shield(owned)
            except asyncio.CancelledError:
                # A native Task.cancel() cancels an ordinary executor await.
                # The strongly held child owns the accepted command; drain it
                # before returning this worker's single admission slot.
                while not owned.done():
                    try:
                        await asyncio.shield(owned)
                    except asyncio.CancelledError:
                        continue
                    except BaseException:
                        break
                if owned.done() and not owned.cancelled():
                    with suppress(BaseException):
                        owned.exception()
                raise
        finally:
            self._admission.release()

    async def _claim_one(self) -> StudioVideoJobLease | None:
        async with self._session_factory() as database, database.begin():
            jobs = await JobRepository(database).claim(
                lease_for=self.claim_lease_for,
                limit=1,
                kinds=self.allowed_job_kinds,
            )
            if not jobs:
                return None
            job = jobs[0]
            if type(job.lease_token) is not UUID:
                raise LeaseLostError("claimed Studio video job has no lease token")
            state = await RecoveryStateRepository(database).require_ready(
                lock=True,
                shared_lock=True,
            )
            return StudioVideoJobLease(job.id, job.lease_token, state.generation)

    async def _execute(self, lease: StudioVideoJobLease) -> StudioVideoWorkerResult:
        try:
            prepared = await self._prepare(lease)
        except (LeaseLostError, ReconciliationRequiredError):
            return StudioVideoWorkerResult(claimed=1, fenced=1)
        except Exception:
            return await self._fail(lease, "studio_video_prepare_failed")

        try:
            processed = await self._process_with_heartbeat(
                lease,
                prepared,
                attempt_id=uuid4(),
            )
        except (LeaseLostError, ReconciliationRequiredError):
            return StudioVideoWorkerResult(claimed=1, fenced=1)
        except Exception:
            return await self._fail(lease, "studio_video_process_failed")

        try:
            await self._finalize(lease, prepared, processed)
        except _CommittedReleaseError as error:
            return StudioVideoWorkerResult(
                claimed=1,
                succeeded=1,
                release_failed=int(error.release_failed),
            )
        except (LeaseLostError, ReconciliationRequiredError):
            return StudioVideoWorkerResult(claimed=1, fenced=1)
        except Exception:
            return await self._fail(lease, "studio_video_finalize_failed")
        return StudioVideoWorkerResult(claimed=1, succeeded=1)

    async def _prepare(self, lease: StudioVideoJobLease) -> PreparedStudioVideo:
        async with self._session_factory() as database, database.begin():
            repository = JobRepository(database)
            job = await repository.lock_internal_lease(
                lease.job_id,
                lease.lease_token,
                kind=MEDIA_PROCESS_VERSION_JOB,
                recovery_generation=lease.recovery_generation,
            )
            job = await repository.renew(
                job,
                lease.lease_token,
                lease_for=self.lease_for,
            )
            prepared = await database.run_sync(lambda sync: self.pipeline.prepare(sync, job))
            if (
                prepared.job_id != lease.job_id
                or prepared.lease_token != lease.lease_token
                or prepared.recovery_generation != lease.recovery_generation
                or prepared.tenant_id != job.tenant_id
            ):
                raise JobStateError("prepared Studio video does not match its fenced job")
            return prepared

    async def _renew(self, lease: StudioVideoJobLease) -> None:
        async with self._session_factory() as database, database.begin():
            repository = JobRepository(database)
            job = await repository.lock_internal_lease(
                lease.job_id,
                lease.lease_token,
                kind=MEDIA_PROCESS_VERSION_JOB,
                recovery_generation=lease.recovery_generation,
            )
            await repository.renew(job, lease.lease_token, lease_for=self.lease_for)

    async def _heartbeat(
        self,
        lease: StudioVideoJobLease,
        stop: asyncio.Event,
    ) -> BaseException | None:
        while True:
            try:
                await asyncio.wait_for(
                    stop.wait(),
                    timeout=self.heartbeat_every.total_seconds(),
                )
                return None
            except TimeoutError:
                pass
            try:
                await self._renew(lease)
            except BaseException as error:
                return error

    async def _process_with_heartbeat(
        self,
        lease: StudioVideoJobLease,
        prepared: PreparedStudioVideo,
        *,
        attempt_id: UUID,
    ) -> _ProcessedStudioVideo:
        stop = asyncio.Event()
        executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix=f"studio-video-{lease.job_id}",
        )
        processing = asyncio.get_running_loop().run_in_executor(
            executor,
            partial(self.pipeline.process, prepared, attempt_id=attempt_id),
        )
        heartbeat = asyncio.create_task(
            self._heartbeat(lease, stop),
            name=f"studio-video-heartbeat-{lease.job_id}",
        )
        done, _ = await asyncio.wait((processing, heartbeat), return_when=asyncio.FIRST_COMPLETED)
        if heartbeat in done:
            heartbeat_error = heartbeat.result()
            if heartbeat_error is not None:
                try:
                    completed = await processing
                except BaseException as blocked_process_error:
                    executor.shutdown(wait=True)
                    raise heartbeat_error from blocked_process_error
                processed = _ProcessedStudioVideo(completed, executor)
                await self._discard(processed)
                raise heartbeat_error
        verified: VerifiedStudioVideo | None = None
        process_failure: BaseException | None = None
        try:
            verified = await processing
        except BaseException as error:
            process_failure = error
        stop.set()
        heartbeat_error = await heartbeat
        if process_failure is not None:
            executor.shutdown(wait=True)
            raise process_failure
        if verified is None:
            executor.shutdown(wait=True)
            raise JobStateError("Studio video processing returned no verified result")
        if heartbeat_error is not None:
            processed = _ProcessedStudioVideo(verified, executor)
            await self._discard(processed)
            raise heartbeat_error
        return _ProcessedStudioVideo(verified, executor)

    async def _finalize(
        self,
        lease: StudioVideoJobLease,
        prepared: PreparedStudioVideo,
        processed: _ProcessedStudioVideo,
    ) -> None:
        committed = False
        cleanup = "discard"
        primary_error: BaseException | None = None
        try:
            async with self._session_factory() as database:
                transaction = await database.begin()
                try:
                    repository = JobRepository(database)
                    job = await repository.lock_internal_lease(
                        lease.job_id,
                        lease.lease_token,
                        kind=MEDIA_PROCESS_VERSION_JOB,
                        recovery_generation=lease.recovery_generation,
                    )
                    await self.pipeline.finalize(database, prepared, processed.verified)
                    await repository.complete(job, lease.lease_token)
                except BaseException as error:
                    try:
                        await transaction.rollback()
                    except BaseException as rollback_error:
                        error.add_note(
                            f"Studio video rollback was uncertain: {type(rollback_error).__name__}"
                        )
                        cleanup = "release"
                    raise
                # A commit attempt is uncertain until session exit finishes
                # and the pipeline's transaction lifecycle hook classifies it.
                cleanup = "release"
                await transaction.commit()
                committed = True
        except BaseException as error:
            primary_error = error

        cleanup_error: BaseException | None = None
        try:
            if cleanup == "release":
                await self._release(processed)
            else:
                # No commit was attempted: session acquisition/begin failed,
                # or the finalization body was confirmed rolled back.
                await self._discard(processed)
        except BaseException as error:
            cleanup_error = error

        if committed:
            if primary_error is not None or cleanup_error is not None:
                cause = primary_error or cleanup_error
                assert cause is not None
                raise _CommittedReleaseError(
                    "Committed Studio video finalization cleanup needs attention.",
                    release_failed=cleanup_error is not None,
                ) from cause
            return
        if primary_error is not None:
            if cleanup_error is not None:
                primary_error.add_note(
                    f"Studio video verification cleanup failed: {type(cleanup_error).__name__}"
                )
            raise primary_error
        if cleanup_error is not None:
            raise cleanup_error
        raise RuntimeError("Studio video finalization ended without a commit")

    async def _discard(self, processed: _ProcessedStudioVideo) -> None:
        await self._resolve(processed, discard=True)

    async def _release(self, processed: _ProcessedStudioVideo) -> None:
        await self._resolve(processed, discard=False)

    async def _resolve(self, processed: _ProcessedStudioVideo, *, discard: bool) -> None:
        if processed.resolved:
            raise RuntimeError("Studio video verification was already resolved")
        operation = self.pipeline.discard if discard else self.pipeline.release
        try:
            await asyncio.get_running_loop().run_in_executor(
                processed.executor,
                operation,
                processed.verified,
            )
        finally:
            # Both pipeline operations consume the proof even when their local
            # cleanup reports an error. Never follow a failed release by delete.
            processed.resolved = True
            processed.executor.shutdown(wait=True)

    async def _fail(
        self,
        lease: StudioVideoJobLease,
        error: str,
    ) -> StudioVideoWorkerResult:
        try:
            async with self._session_factory() as database, database.begin():
                repository = JobRepository(database)
                job = await repository.lock_internal_lease(
                    lease.job_id,
                    lease.lease_token,
                    kind=MEDIA_PROCESS_VERSION_JOB,
                    recovery_generation=lease.recovery_generation,
                )
                failed = await repository.fail(job, lease.lease_token, error)
                await self.pipeline.record_failure(
                    database,
                    failed,
                    terminal=failed.status == JobStatus.DEAD_LETTER.value,
                )
        except (LeaseLostError, ReconciliationRequiredError):
            return StudioVideoWorkerResult(claimed=1, fenced=1)
        return StudioVideoWorkerResult(
            claimed=1,
            retried=int(failed.status == JobStatus.RETRY_WAIT.value),
            dead_lettered=int(failed.status == JobStatus.DEAD_LETTER.value),
        )


__all__ = [
    "StudioVideoJobLease",
    "StudioVideoJobWorker",
    "StudioVideoPipeline",
    "StudioVideoWorkerResult",
    "StudioVideoWorkerSessionFactory",
]
