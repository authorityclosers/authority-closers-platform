"""Single-job offline worker on AC's durable queue; no inference/provider credentials.

This local process adapter is deliberately limited to local/test. The container
sandbox candidate must earn its own runtime receipt before hosted media activation.
"""

from __future__ import annotations

import asyncio
import os
import stat
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal, TypeVar, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ac_platform.conversation_intelligence.application import (
    AUDIOATLAS_RECIPE,
    DELETE_JOB,
    LOCAL_JOB,
    ConversationApplication,
    ConversationConflict,
    ConversationDenied,
    utc,
)
from ac_platform.conversation_intelligence.checkpoints import (
    SourceBinding,
    build_checkpoint,
    content_hash,
)
from ac_platform.conversation_intelligence.entitlements import (
    BudgetAccount,
    ExecutionPermission,
    MinuteAccount,
    Quote,
    SettlementReceipt,
    mark_dispatched,
    metered_seconds,
    settle,
)
from ac_platform.conversation_intelligence.models import (
    ConversationBudgetAccount,
    ConversationCheckpoint,
    ConversationMinuteAccount,
    ConversationPermission,
    ConversationQuote,
    ConversationRecording,
    ConversationRun,
)
from ac_platform.conversation_intelligence.signals import inspect_media
from ac_platform.conversation_intelligence.storage import (
    CHUNK_BYTES,
    MAX_OBJECT_BYTES,
    ObjectKey,
    ObjectKind,
    PrivateLocalRecordingStorage,
    StorageError,
)
from ac_platform.identity.models import Person
from ac_platform.outbox.models import Job
from ac_platform.outbox.repository import JobRepository, RecoveryStateRepository
from ac_platform.tenancy.models import Membership, Tenant

_T = TypeVar("_T")
_WORK_LEASE = timedelta(minutes=15)
_WORK_HEARTBEAT = timedelta(seconds=30)
_WORKER_LOCK_NAME = ".ac-conversation-worker.lock"


async def _drain(awaitable: asyncio.Future[Any]) -> None:
    """Join a cancelled executor await before releasing its owned resources."""

    while not awaitable.done():
        try:
            await asyncio.shield(awaitable)
        except asyncio.CancelledError:
            continue
        except BaseException:
            break
    if awaitable.done() and not awaitable.cancelled():
        with suppress(BaseException):
            awaitable.exception()


async def _await_joined(awaitable: asyncio.Future[Any]) -> Any:
    """Await an executor operation without abandoning its native thread."""

    try:
        return await asyncio.shield(awaitable)
    except asyncio.CancelledError:
        await _drain(awaitable)
        raise


class _RecordingStorageFence:
    """Cross-process fence for all local conversation storage effects.

    The domain deletion worker and the local inspection worker use the same
    private-root lock. A single global lock is intentional: the database row
    lock is acquired only after this fence, so deletion cannot deadlock behind
    an inspection phase that is waiting for its final database transaction.
    """

    def __init__(self, root: Path) -> None:
        self.path = root / _WORKER_LOCK_NAME
        self._handle: Any | None = None
        self._locked = False

    def __enter__(self) -> None:
        try:
            if self.path.exists() or self.path.is_symlink():
                info = self.path.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise StorageError("storage_worker_fence_invalid")
            flags = os.O_CREAT | os.O_RDWR | int(getattr(os, "O_NOFOLLOW", 0))
            flags |= int(getattr(os, "O_BINARY", 0))
            descriptor = os.open(self.path, flags, 0o600)
            try:
                self._handle = os.fdopen(descriptor, "r+b", buffering=0)
            except BaseException:
                os.close(descriptor)
                raise
            info = os.fstat(self._handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise StorageError("storage_worker_fence_invalid")
            if os.name == "nt":
                import msvcrt

                # msvcrt.locking requires a byte-sized region at the current offset.
                self._handle.seek(0)
                if info.st_size == 0:
                    self._handle.write(b"\0")
                    self._handle.flush()
                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX)  # type: ignore[attr-defined]
            self._locked = True
        except StorageError:
            self._close()
            raise
        except OSError:
            self._close()
            raise StorageError("storage_worker_fence_unavailable") from None
        return None

    def __exit__(self, *_: object) -> Literal[False]:
        try:
            if self._handle is not None and self._locked:
                if os.name == "nt":
                    import msvcrt

                    self._handle.seek(0)
                    msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]
        except OSError:
            raise StorageError("storage_worker_fence_release_failed") from None
        finally:
            self._locked = False
            self._close()
        return False

    def _close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None


class _FencedExecutor:
    """Own a storage fence and all synchronous work until its thread is joined."""

    def __init__(self, root: Path) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="conversation-worker"
        )
        self._fence = _RecordingStorageFence(root)
        self._entered = False

    async def __aenter__(self) -> _FencedExecutor:
        acquire = self._submit(self._fence.__enter__)
        try:
            await _await_joined(acquire)
        except asyncio.CancelledError:
            acquired = acquire.done() and not acquire.cancelled() and acquire.exception() is None
            if acquired:
                release = self._submit(self._fence.__exit__, None, None, None)
                with suppress(BaseException):
                    await _await_joined(release)
            self._executor.shutdown(wait=True)
            raise
        except BaseException:
            self._executor.shutdown(wait=True)
            raise
        self._entered = True
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        release_error: BaseException | None = None
        try:
            release = self._submit(self._fence.__exit__, exc_type, exc, traceback)
            try:
                await _await_joined(release)
            except BaseException as error:
                release_error = error
        finally:
            self._entered = False
            self._executor.shutdown(wait=True)
        if release_error is not None:
            raise release_error
        return False

    async def run(
        self, operation: Callable[..., _T], *args: Any, **kwargs: Any
    ) -> _T:
        if not self._entered:
            raise RuntimeError("storage fence is not active")
        return cast(_T, await _await_joined(self._submit(operation, *args, **kwargs)))

    def _submit(
        self, operation: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> asyncio.Future[Any]:
        return asyncio.get_running_loop().run_in_executor(
            self._executor, partial(operation, *args, **kwargs)
        )


@dataclass(frozen=True)
class Work:
    job_id: UUID
    lease_token: UUID
    recovery_generation: int
    kind: str


class OfflineConversationWorker:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        storage: PrivateLocalRecordingStorage,
        scratch: PrivateLocalRecordingStorage,
        environment: Literal["local", "test"],
        lease_for: timedelta = _WORK_LEASE,
        heartbeat_every: timedelta = _WORK_HEARTBEAT,
    ) -> None:
        if environment not in {"local", "test"} or storage.root == scratch.root:
            raise ValueError("Local worker requires separate private storage and scratch roots.")
        if not timedelta(seconds=1) <= lease_for <= timedelta(minutes=15):
            raise ValueError("lease_for must be between one second and fifteen minutes")
        if heartbeat_every <= timedelta(0) or heartbeat_every * 2 >= lease_for:
            raise ValueError("heartbeat_every must be positive and less than half the lease")
        self.sessions, self.storage, self.scratch = sessions, storage, scratch
        self.lease_for, self.heartbeat_every = lease_for, heartbeat_every

    async def claim(self) -> Work | None:
        async with self.sessions() as db, db.begin():
            recovery = await RecoveryStateRepository(db).require_ready(lock=True, shared_lock=True)
            repository = JobRepository(db)
            jobs = await repository.claim(
                kinds=(LOCAL_JOB, DELETE_JOB),
                limit=1,
                lease_for=min(self.lease_for, timedelta(seconds=30)),
            )
            if not jobs:
                return None
            job = jobs[0]
            if job.lease_token is None:
                raise RuntimeError("Claimed work has no lease.")
            # The short claim lease only protects the claim transaction. Extend it
            # before starting a native phase so the first heartbeat has headroom.
            await repository.renew(job, job.lease_token, lease_for=self.lease_for)
            return Work(job.id, job.lease_token, recovery.generation, job.kind)

    async def _renew(self, work: Work) -> None:
        async with self.sessions() as db, db.begin():
            repository = JobRepository(db)
            job = await self._job(db, work)
            await repository.renew(job, work.lease_token, lease_for=self.lease_for)

    async def _heartbeat(
        self, work: Work, stop: asyncio.Event
    ) -> BaseException | None:
        while True:
            try:
                await asyncio.wait_for(
                    stop.wait(), timeout=self.heartbeat_every.total_seconds()
                )
                return None
            except TimeoutError:
                pass
            try:
                await self._renew(work)
            except BaseException as error:
                return error

    async def _run_claimed(self, work: Work) -> None:
        stop = asyncio.Event()
        heartbeat = asyncio.create_task(
            self._heartbeat(work, stop),
            name=f"conversation-heartbeat-{work.job_id}",
        )
        if work.kind == LOCAL_JOB:
            operation_coro = self._inspect_job(work)
        elif work.kind == DELETE_JOB:
            operation_coro = self._erase_job(work)
        else:
            operation_coro = self._unsupported_job(work)
        operation = asyncio.create_task(operation_coro, name=f"conversation-job-{work.job_id}")
        try:
            done, _ = await asyncio.wait(
                (operation, heartbeat), return_when=asyncio.FIRST_COMPLETED
            )
            if heartbeat in done and operation not in done:
                heartbeat_error = heartbeat.result()
                if heartbeat_error is not None:
                    await _drain(operation)
                    raise heartbeat_error
            await asyncio.shield(operation)
            stop.set()
            # A renewal can already be inside its DB transaction when the
            # operation completes and acknowledges the job. Drain that renewal;
            # its post-success lease loss cannot invalidate the committed result.
            await _drain(heartbeat)
        except asyncio.CancelledError:
            stop.set()
            await _drain(operation)
            await _drain(heartbeat)
            raise
        except BaseException:
            stop.set()
            await _drain(heartbeat)
            raise

    async def _unsupported_job(self, work: Work) -> None:
        raise RuntimeError(f"Worker received unsupported job kind {work.kind!r}.")

    async def _job(self, db: AsyncSession, work: Work) -> Job:
        return await JobRepository(db).lock_internal_lease(
            work.job_id,
            work.lease_token,
            kind=work.kind,
            recovery_generation=work.recovery_generation,
        )

    async def _scope(
        self,
        db: AsyncSession,
        job: Job,
    ) -> tuple[ConversationRecording, ConversationRun, ConversationQuote, Quote]:
        recording_id = UUID(job.payload["recording_id"])
        owner = await db.scalar(
            select(ConversationRecording.person_id).where(
                ConversationRecording.id == recording_id,
                ConversationRecording.tenant_id == job.tenant_id,
            )
        )
        if owner is None:
            raise ConversationDenied("Recording unavailable.")
        person = await db.scalar(
            select(Person)
            .where(Person.id == owner)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        tenant = await db.scalar(
            select(Tenant)
            .where(Tenant.id == job.tenant_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        member = await db.scalar(
            select(Membership)
            .where(
                Membership.tenant_id == job.tenant_id,
                Membership.person_id == owner,
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        recording = await db.scalar(
            select(ConversationRecording)
            .where(
                ConversationRecording.id == recording_id,
                ConversationRecording.tenant_id == job.tenant_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            person is None
            or person.status != "active"
            or person.email_verified_at is None
            or tenant is None
            or tenant.status != "active"
            or member is None
            or member.status != "active"
            or member.ended_at is not None
            or recording is None
            or recording.state != "ready"
            or recording.generation != job.payload.get("generation")
        ):
            raise ConversationDenied("Recording authority is no longer active.")
        permission = await db.scalar(
            select(ConversationPermission)
            .where(
                ConversationPermission.id == recording.permission_id,
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        now = datetime.now(UTC)
        if (
            permission is None
            or permission.revoked_at is not None
            or permission.provider != "local"
            or permission.source_sha256 != recording.source_sha256
            or utc(permission.expires_at) <= now
            or utc(permission.retention_until) <= now
        ):
            raise ConversationDenied("The exact recording permission has expired or been revoked.")
        run = await db.scalar(
            select(ConversationRun)
            .where(
                ConversationRun.id == UUID(job.payload["run_id"]),
                ConversationRun.job_id == job.id,
                ConversationRun.recording_id == recording.id,
                ConversationRun.generation == recording.generation,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        quoted = await db.scalar(
            select(ConversationQuote)
            .where(
                ConversationQuote.id == UUID(job.payload["quote_id"]),
                ConversationQuote.recording_id == recording.id,
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if (
            run is None
            or run.state not in {"queued", "running"}
            or quoted is None
            or quoted.revoked_at is not None
            or run.recipe_revision != AUDIOATLAS_RECIPE
        ):
            raise ConversationConflict("The run or quote no longer authorizes processing.")
        quote = Quote.from_dict(quoted.quote)
        execution = ExecutionPermission.from_dict(quoted.execution_permission)
        if (
            quote.provider_id != "local"
            or quote.provider_model != "audioatlas"
            or quote.operation != "inspect_audioatlas"
            or quote.max_cost_paise != 0
            or quote.source
            != SourceBinding(
                str(recording.tenant_id),
                str(recording.id),
                recording.source_sha256,
                str(recording.source_revision),
            )
            or execution.quote_fingerprint != quote.fingerprint
            or int(now.timestamp()) >= min(quote.expires_at_epoch, execution.expires_at_epoch)
        ):
            raise ConversationDenied("The local execution permission is unavailable.")
        return recording, run, quoted, quote

    async def _accounts(
        self,
        db: AsyncSession,
        recording: ConversationRecording,
        quoted: ConversationQuote,
    ) -> tuple[ConversationMinuteAccount, ConversationBudgetAccount]:
        budget = await db.scalar(
            select(ConversationBudgetAccount)
            .where(
                ConversationBudgetAccount.scope_id == quoted.budget_scope_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        minutes = await db.scalar(
            select(ConversationMinuteAccount)
            .where(
                ConversationMinuteAccount.tenant_id == recording.tenant_id,
                ConversationMinuteAccount.person_id == recording.person_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if minutes is None or budget is None:
            raise ConversationDenied("Reserved processing entitlement unavailable.")
        return minutes, budget

    @staticmethod
    def _save_accounts(
        minutes: ConversationMinuteAccount, budget: ConversationBudgetAccount, transition: Any
    ) -> None:
        if transition.changed:
            minutes.snapshot, budget.snapshot = (
                transition.minutes.as_dict(),
                transition.budget.as_dict(),
            )
            minutes.revision += 1
            budget.revision += 1

    @staticmethod
    def _feature_bytes(payload: dict[str, Any]) -> int:
        acoustics = payload.get("acoustics")
        if not isinstance(acoustics, dict):
            raise StorageError("conversation_c1_cache_metadata_invalid")
        header_bytes = acoustics.get("header_bytes")
        payload_bytes = acoustics.get("uncompressed_payload_bytes")
        if (
            type(header_bytes) is not int
            or type(payload_bytes) is not int
            or header_bytes <= 0
            or payload_bytes <= 0
        ):
            raise StorageError("conversation_c1_cache_metadata_invalid")
        size = header_bytes + payload_bytes
        if size <= 0 or size > MAX_OBJECT_BYTES:
            raise StorageError("conversation_c1_cache_metadata_invalid")
        return size

    def _verify_object(self, key: ObjectKey, sha: str, expected_bytes: int) -> None:
        if type(expected_bytes) is not int or expected_bytes <= 0:
            raise StorageError("storage_invalid_expected_size")
        size = sum(len(block) for block in self.storage.iter_bytes(key, expected_sha256=sha))
        if size != expected_bytes:
            raise StorageError("storage_size_mismatch")

    def _verify_cached_c1(
        self,
        source: ObjectKey,
        source_sha: str,
        source_bytes: int,
        feature_blob_id: UUID | None,
        payload: dict[str, Any] | None,
        payload_sha: str,
    ) -> dict[str, Any]:
        if type(feature_blob_id) is not UUID or not isinstance(payload, dict):
            raise StorageError("conversation_c1_cache_missing_feature_blob")
        if content_hash(payload) != payload_sha:
            raise StorageError("conversation_c1_cache_payload_mismatch")
        feature_sha = payload.get("feature_sha256")
        acoustics = payload.get("acoustics")
        if (
            payload.get("schema") != "ac.sales-xray.signal-checkpoint/1"
            or payload.get("stage") != "C1"
            or payload.get("source_sha256") != source_sha
            or payload.get("source_bytes") != source_bytes
            or not isinstance(feature_sha, str)
            or not isinstance(acoustics, dict)
            or acoustics.get("source_sha256") != source_sha
            or acoustics.get("feature_sha256") != feature_sha
        ):
            raise StorageError("conversation_c1_cache_identity_mismatch")
        self._verify_object(source, source_sha, source_bytes)
        self._verify_object(
            ObjectKey(
                source.tenant_id,
                source.recording_id,
                feature_blob_id,
                ObjectKind.SIGNAL_FEATURES,
            ),
            feature_sha,
            self._feature_bytes(payload),
        )
        return payload

    def _inspect(
        self,
        source: ObjectKey,
        sha: str,
        expected_bytes: int,
        root: Path,
    ) -> dict[str, Any]:
        media = root / "source.media"
        with media.open("xb") as stream:
            for block in self.storage.iter_bytes(source, expected_sha256=sha):
                stream.write(block)
        if media.stat().st_size != expected_bytes:
            raise StorageError("storage_size_mismatch")
        result = inspect_media(media, root / "result", rate=48000)
        if (
            result.get("source_sha256") != sha
            or result.get("source_bytes") != expected_bytes
            or not isinstance(result.get("feature_sha256"), str)
        ):
            raise StorageError("conversation_c1_result_identity_mismatch")
        return result

    def _persist_features(self, key: ObjectKey, path: Path, sha: str) -> None:
        def chunks() -> Iterator[bytes]:
            with path.open("rb") as source:
                while block := source.read(CHUNK_BYTES):
                    yield block

        expected_bytes = path.stat().st_size
        try:
            self.storage.put(key, chunks(), expected_sha256=sha, expected_bytes=expected_bytes)
        except StorageError as error:
            if str(error) != "storage_object_exists":
                raise
            self._verify_object(key, sha, expected_bytes)

    async def _inspect_job(self, work: Work) -> None:
        async with _FencedExecutor(self.storage.root) as fenced:
            async with self.sessions() as db, db.begin():
                job = await self._job(db, work)
                recording, _, quoted, _ = await self._scope(db, job)
                source = ObjectKey(
                    recording.tenant_id, recording.id, recording.id, ObjectKind.SOURCE_AUDIO
                )
                source_sha = recording.source_sha256
                source_bytes = recording.source_bytes
                binding = SourceBinding(
                    str(recording.tenant_id),
                    str(recording.id),
                    source_sha,
                    str(recording.source_revision),
                )
                c0_payload = {
                    "source_sha256": source_sha,
                    "source_bytes": source_bytes,
                    "content_type": recording.content_type,
                    "permission_reference": str(recording.permission_id),
                }
                c0 = build_checkpoint(
                    binding, "C0", "recording-v1", {}, (), content_hash(c0_payload)
                )
                await ConversationApplication(db).publish_checkpoint(
                    job_id=work.job_id,
                    lease_token=work.lease_token,
                    recovery_generation=work.recovery_generation,
                    checkpoint=c0,
                    payload=c0_payload,
                )
                c1_config = {"decode_rate": 48000, "window_profile": "audioatlas-40ms-10ms"}
                c1_key = build_checkpoint(
                    binding,
                    "C1",
                    AUDIOATLAS_RECIPE,
                    c1_config,
                    (c0,),
                    "0" * 64,
                ).cache_key
                existing = await db.scalar(
                    select(ConversationCheckpoint).where(
                        ConversationCheckpoint.recording_id == recording.id,
                        ConversationCheckpoint.cache_key == c1_key,
                        ConversationCheckpoint.erased_at.is_(None),
                    )
                )
                cached_row = (
                    None
                    if existing is None
                    else (existing.payload, existing.feature_blob_id, existing.payload_sha256)
                )

            cached: dict[str, Any] | None = None
            if cached_row is not None:
                cached = await fenced.run(
                    self._verify_cached_c1,
                    source,
                    source_sha,
                    source_bytes,
                    cached_row[1],
                    cached_row[0],
                    cached_row[2],
                )

            # Dispatch is committed only after a cache hit has proved its source and
            # feature artifact, so a failed cache lookup has a known no-execution path.
            async with self.sessions() as db, db.begin():
                job = await self._job(db, work)
                recording, run, quoted, _ = await self._scope(db, job)
                minutes, budget = await self._accounts(db, recording, quoted)
                transition = mark_dispatched(
                    MinuteAccount.from_dict(minutes.snapshot),
                    BudgetAccount.from_dict(budget.snapshot),
                    str(run.id),
                    str(job.id),
                    int(datetime.now(UTC).timestamp()),
                )
                self._save_accounts(minutes, budget, transition)
                run.state = "running"

            # Local computation has no external side effect. A retry reuses C0/C1
            # and its original reservation/attempt; a new profile cannot trigger ASR.
            # The storage fence remains held until native work, DB finalization and
            # the executor thread have all drained. TemporaryDirectory then erases
            # source/PCM scratch only after the native call has actually returned.
            with TemporaryDirectory(prefix="work-", dir=self.scratch.root) as directory:
                root = Path(directory)
                result = (
                    cached
                    if cached is not None
                    else await fenced.run(self._inspect, source, source_sha, source_bytes, root)
                )
                feature_path = root / "result" / "features.aaf"
                if cached is None and feature_path.stat().st_size != self._feature_bytes(result):
                    raise StorageError("conversation_c1_result_size_mismatch")
                c1 = build_checkpoint(
                    binding,
                    "C1",
                    AUDIOATLAS_RECIPE,
                    c1_config,
                    (c0,),
                    content_hash(result),
                )
                async with self.sessions() as db, db.begin():
                    job = await self._job(db, work)
                    recording, run, quoted, quote = await self._scope(db, job)
                    blob_id = cached_row[1] if cached_row is not None else None
                    if cached is None:
                        await fenced.run(
                            self._persist_features,
                            ObjectKey(
                                recording.tenant_id,
                                recording.id,
                                run.id,
                                ObjectKind.SIGNAL_FEATURES,
                            ),
                            feature_path,
                            result["feature_sha256"],
                        )
                        blob_id = run.id
                    await ConversationApplication(db).publish_checkpoint(
                        job_id=work.job_id,
                        lease_token=work.lease_token,
                        recovery_generation=work.recovery_generation,
                        checkpoint=c1,
                        payload=result,
                        feature_blob_id=blob_id,
                        storage=self.storage,
                    )
                    minutes, budget = await self._accounts(db, recording, quoted)
                    transition = settle(
                        MinuteAccount.from_dict(minutes.snapshot),
                        BudgetAccount.from_dict(budget.snapshot),
                        str(run.id),
                        SettlementReceipt(
                            str(run.id),
                            quote.fingerprint,
                            "local",
                            str(job.id),
                            metered_seconds(result["media_duration_ms"]),
                            0,
                            f"checkpoint:{c1.manifest_sha256}",
                        ),
                    )
                    self._save_accounts(minutes, budget, transition)
                    run.state = (
                        "failed"
                        if transition.reservation.state == "reconciliation_required"
                        else "completed"
                    )
                    run.completed_at = datetime.now(UTC)
                    await JobRepository(db).complete(work.job_id, work.lease_token)

    async def _erase_job(self, work: Work) -> None:
        async with _FencedExecutor(self.storage.root) as fenced:  # noqa: SIM117
            async with self.sessions() as db, db.begin():
                job = await self._job(db, work)
                recording = await db.scalar(
                    select(ConversationRecording)
                    .where(
                        ConversationRecording.id == UUID(job.payload["recording_id"]),
                        ConversationRecording.tenant_id == job.tenant_id,
                    )
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if (
                    recording is None
                    or recording.state not in {"deleting", "deleted"}
                    or recording.generation != job.payload["generation"]
                ):
                    raise ConversationConflict("Erasure no longer matches its generation.")
                runs = (
                    await db.scalars(
                        select(ConversationRun).where(
                            ConversationRun.recording_id == recording.id,
                        )
                    )
                ).all()
                expected = (
                    ObjectKey(
                        recording.tenant_id,
                        recording.id,
                        recording.id,
                        ObjectKind.SOURCE_AUDIO,
                    ),
                    *(
                        ObjectKey(
                            recording.tenant_id,
                            recording.id,
                            run.id,
                            ObjectKind.SIGNAL_FEATURES,
                        )
                        for run in runs
                    ),
                )
                receipt = await fenced.run(
                    self.storage.delete_recording,
                    recording.tenant_id,
                    recording.id,
                    expected_keys=expected,
                )
                if not receipt.local_inventory_empty:
                    raise StorageError("storage_erasure_incomplete")
                await ConversationApplication(db).finish_erasure(
                    job_id=work.job_id,
                    lease_token=work.lease_token,
                    recovery_generation=work.recovery_generation,
                )

    async def run_once(self) -> bool:
        work = await self.claim()
        if work is None:
            return False
        owned = asyncio.create_task(
            self._run_claimed(work),
            name=f"conversation-owned-job-{work.job_id}",
        )
        try:
            await asyncio.shield(owned)
        except asyncio.CancelledError:
            # Cancellation of a native await does not cancel its executor thread.
            # Keep the owned job alive and join it before returning the lease/fence
            # to the process, then propagate cancellation to the caller.
            await _drain(owned)
            if owned.done() and not owned.cancelled():
                with suppress(BaseException):
                    owned.exception()
            raise
        except Exception:
            # No provider/media exception text enters shared operational logs.
            # A failed local attempt is not a no-charge receipt: leave any
            # dispatched reservation held for explicit reconciliation.
            async with self.sessions() as db, db.begin():
                await self._job(db, work)
                await JobRepository(db).fail(
                    work.job_id, work.lease_token, "conversation_local_phase_failed"
                )
            raise RuntimeError(
                "The local conversation job failed; see its durable state."
            ) from None
        return True
