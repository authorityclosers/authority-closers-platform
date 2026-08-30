"""Fail-closed durable worker with exact routing and bounded provider dispatch."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager, suppress
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Any, Protocol
from uuid import UUID

import structlog
from sqlalchemy import and_, column, select, table
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.application.settings import get_settings
from ac_platform.identity.models import Person, PersonStatus
from ac_platform.outbox.models import Job, JobStatus, RecoveryStatus
from ac_platform.outbox.policy import ReconciliationRequiredError
from ac_platform.outbox.repository import (
    DuplicateIntentError,
    JobRepository,
    JobStateError,
    LeaseLostError,
    OutboxJobRoute,
    OutboxRepository,
    RecoveryStateRepository,
)
from ac_platform.providers import (
    DeliveryReceipt,
    EmailMessage,
    EmailProvider,
    PermanentProviderError,
    TransientProviderError,
    create_email_provider_from_settings,
)
from ac_platform.telemetry import InMemoryTelemetrySink, TelemetryCategory, TelemetryRecorder

ENROLLMENT_WELCOME_EVENT = "enrollment.welcome.requested.v1"
ENROLLMENT_WELCOME_JOB = "email.enrollment_welcome.v1"
ENROLLMENT_WELCOME_ROUTE = OutboxJobRoute(
    job_kind=ENROLLMENT_WELCOME_JOB,
    required_payload_keys=frozenset(
        {
            "enrollment_id",
            "entitlement_id",
            "provenance_id",
            "person_id",
            "program_version_id",
            "source",
        }
    ),
    uuid_payload_keys=frozenset(
        {
            "enrollment_id",
            "entitlement_id",
            "provenance_id",
            "person_id",
            "program_version_id",
        }
    ),
    allowed_payload_values={"source": frozenset({"free_self", "manual_grant"})},
)
OUTBOX_JOB_ROUTES: Mapping[str, OutboxJobRoute] = MappingProxyType(
    {ENROLLMENT_WELCOME_EVENT: ENROLLMENT_WELCOME_ROUTE}
)

# Explicit v1 read shape for the server-side recipient resolver. Lightweight
# SQL tables avoid importing enrollment command services into the worker while
# still binding every signed internal identifier to canonical database rows.
_ENROLLMENTS = table(
    "enrollments",
    column("id"),
    column("tenant_id"),
    column("person_id"),
    column("program_version_id"),
    column("source"),
    column("status"),
)
_ENTITLEMENTS = table(
    "entitlements",
    column("id"),
    column("tenant_id"),
    column("person_id"),
    column("enrollment_id"),
    column("provenance_id"),
    column("program_version_id"),
    column("status"),
)
_ENROLLMENT_PROVENANCE = table(
    "enrollment_provenance",
    column("id"),
    column("tenant_id"),
    column("person_id"),
    column("enrollment_id"),
    column("program_version_id"),
    column("source"),
)


class WorkerNotReadyError(ReconciliationRequiredError):
    """The durable recovery generation or local safety hold prevents work."""


class UnknownJobKindError(PermanentProviderError):
    """A durable job did not match the worker's explicit dispatcher allowlist."""


class AmbiguousProviderReceiptError(PermanentProviderError):
    """A provider responded with evidence that cannot be bound to this job."""


class SessionFactory(Protocol):
    def __call__(self) -> AbstractAsyncContextManager[AsyncSession]:
        """Create one session context for a short worker transaction."""


@dataclass(frozen=True, slots=True)
class PreparedDispatch:
    """In-memory provider command; recipient data is never persisted on the job."""

    job_id: UUID
    tenant_id: UUID | None
    kind: str
    attempt_count: int
    lease_token: UUID
    recovery_generation: int
    provider_idempotency_key: str
    message: EmailMessage


JobHandler = Callable[[PreparedDispatch], Awaitable[DeliveryReceipt]]


class AllowlistedDispatcher:
    """Dispatch only exact job kinds registered by the caller."""

    def __init__(self, handlers: Mapping[str, JobHandler]) -> None:
        if any(not kind.strip() for kind in handlers):
            raise ValueError("dispatcher job kinds must not be blank")
        self._handlers = dict(handlers)

    @property
    def allowed_kinds(self) -> frozenset[str]:
        return frozenset(self._handlers)

    async def dispatch(self, prepared: PreparedDispatch) -> DeliveryReceipt:
        handler = self._handlers.get(prepared.kind)
        if handler is None:
            raise UnknownJobKindError(f"job kind is not allowlisted: {prepared.kind}")
        return await handler(prepared)


@dataclass(frozen=True, slots=True)
class WorkerRunResult:
    """Counts from one bounded worker pass."""

    materialized: int = 0
    claimed: int = 0
    succeeded: int = 0
    retried: int = 0
    dead_lettered: int = 0

    def add_outcome(self, outcome: Mapping[str, int]) -> WorkerRunResult:
        return WorkerRunResult(
            materialized=self.materialized,
            claimed=self.claimed + outcome.get("claimed", 0),
            succeeded=self.succeeded + outcome.get("succeeded", 0),
            retried=self.retried + outcome.get("retried", 0),
            dead_lettered=self.dead_lettered + outcome.get("dead_lettered", 0),
        )


def _email_handler(provider: EmailProvider) -> JobHandler:
    async def send(prepared: PreparedDispatch) -> DeliveryReceipt:
        return await provider.send(prepared.message)

    return send


def build_default_dispatcher(
    settings: Any | None = None,
    *,
    provider: EmailProvider | None = None,
) -> AllowlistedDispatcher:
    """Build the one exact G1 email route with the fake/no-network default."""

    if settings is None:
        settings = get_settings()
    email_provider = provider or create_email_provider_from_settings(settings)
    return AllowlistedDispatcher({ENROLLMENT_WELCOME_JOB: _email_handler(email_provider)})


class DurableWorker:
    """Claim, resolve, dispatch, evidence, and acknowledge one job at a time."""

    def __init__(
        self,
        session_factory: SessionFactory | None = None,
        *,
        dispatcher: AllowlistedDispatcher | None = None,
        settings: Any | None = None,
        batch_size: int = 50,
        lease_for: timedelta = timedelta(minutes=2),
        provider_timeout: timedelta = timedelta(seconds=30),
        poll_interval: float = 1.0,
        telemetry: TelemetryRecorder | None = None,
    ) -> None:
        if not 1 <= batch_size <= 500:
            raise ValueError("batch_size must be between 1 and 500")
        if not timedelta(seconds=1) <= provider_timeout <= timedelta(minutes=2):
            raise ValueError("provider_timeout must be between one second and two minutes")
        if lease_for < provider_timeout + timedelta(seconds=10):
            raise ValueError("lease_for must cover provider_timeout plus a safety margin")
        if lease_for > timedelta(minutes=15):
            raise ValueError("lease_for must not exceed 15 minutes")
        if poll_interval < 0:
            raise ValueError("poll_interval must not be negative")
        if session_factory is None:
            from ac_platform.db.session import session_factory as configured_session_factory

            session_factory = configured_session_factory
        self._session_factory = session_factory
        self._settings = settings or get_settings()
        self._dispatcher = dispatcher or build_default_dispatcher(self._settings)
        self._batch_size = batch_size
        self._lease_for = lease_for
        self._claim_lease_for = min(lease_for, timedelta(seconds=30))
        self._provider_timeout = provider_timeout
        self._poll_interval = poll_interval
        self._logger = structlog.get_logger().bind(component="durable_worker")
        self._telemetry = telemetry or TelemetryRecorder(InMemoryTelemetrySink())
        self._ready = False
        self._started = False

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def allowed_job_kinds(self) -> frozenset[str]:
        return self._dispatcher.allowed_kinds

    async def prepare(self) -> bool:
        """Require both the local hold and durable database gate to be released."""

        if self._started and self._ready:
            return True
        local_hold = bool(getattr(self._settings, "external_side_effects_hold", True))
        async with self._session_factory() as session, session.begin():
            state = await RecoveryStateRepository(session).get()
        self._started = True
        if local_hold:
            self._logger.warning("worker_local_side_effect_hold_active")
            return False
        if state is None or state.status != RecoveryStatus.READY.value:
            self._logger.warning(
                "worker_recovery_reconciliation_required",
                recovery_generation=(state.generation if state is not None else 0),
            )
            return False
        self._ready = True
        self._logger.info(
            "worker_ready",
            allowed_job_kinds=sorted(self.allowed_job_kinds),
            recovery_generation=state.generation,
        )
        return True

    async def start(self) -> bool:
        return await self.prepare()

    async def run_once(self) -> WorkerRunResult:
        """Materialize safely, then claim/commit/dispatch one job at a time."""

        if not self._ready:
            raise WorkerNotReadyError("worker is not ready for external side effects")
        try:
            materialized = await self._materialize()
        except ReconciliationRequiredError as error:
            self._ready = False
            raise WorkerNotReadyError(str(error)) from error
        result = WorkerRunResult(materialized=len(materialized))
        for _ in range(self._batch_size):
            try:
                job = await self._claim_one()
            except ReconciliationRequiredError:
                self._ready = False
                break
            if job is None:
                break
            result = result.add_outcome(await self._execute_one(job))
        return result

    async def run(
        self,
        *,
        stop_event: asyncio.Event | None = None,
        max_iterations: int | None = None,
    ) -> None:
        if max_iterations is not None and max_iterations < 1:
            raise ValueError("max_iterations must be positive")
        stop = stop_event or asyncio.Event()
        iterations = 0
        while not stop.is_set():
            if await self.prepare():
                await self.run_once()
            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                return
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self._poll_interval)

    async def _materialize(self) -> list[Job]:
        async with self._session_factory() as session, session.begin():
            return await OutboxRepository(session).materialize_pending_jobs(
                routes=OUTBOX_JOB_ROUTES,
                limit=self._batch_size,
            )

    async def _claim_one(self) -> Job | None:
        async with self._session_factory() as session, session.begin():
            jobs = await JobRepository(session).claim(
                lease_for=self._claim_lease_for,
                limit=1,
            )
            return jobs[0] if jobs else None

    async def _prepare_dispatch(self, job_id: UUID, lease_token: UUID) -> PreparedDispatch:
        async with self._session_factory() as session, session.begin():
            job = await session.get(Job, job_id)
            if job is None:
                raise LeaseLostError("job no longer exists")
            if job.kind != ENROLLMENT_WELCOME_JOB:
                raise UnknownJobKindError(f"job kind is not allowlisted: {job.kind}")
            state = await RecoveryStateRepository(session).require_ready(
                expected_generation=job.recovery_generation,
                lock=True,
                shared_lock=True,
            )
            repository = JobRepository(session)
            await repository.renew(
                job,
                lease_token,
                lease_for=self._lease_for,
            )
            provider_key = job.dedupe_key
            message = await self._resolve_message(session, job, provider_key=provider_key)
            await repository.record_dispatch_started(
                job,
                lease_token,
                provider_idempotency_key=provider_key,
                recovery_generation=state.generation,
            )
            return PreparedDispatch(
                job_id=job.id,
                tenant_id=job.tenant_id,
                kind=job.kind,
                attempt_count=job.attempt_count,
                lease_token=lease_token,
                recovery_generation=state.generation,
                provider_idempotency_key=provider_key,
                message=message,
            )

    async def _dispatch_under_recovery_fence(
        self,
        prepared: PreparedDispatch,
    ) -> DeliveryReceipt:
        """Keep restore's exclusive generation lock behind an in-flight effect."""

        async with self._session_factory() as session, session.begin():
            job = await JobRepository(session).lock_for_dispatch(
                prepared.job_id,
                prepared.lease_token,
                recovery_generation=prepared.recovery_generation,
                provider_idempotency_key=prepared.provider_idempotency_key,
            )
            message = await self._resolve_message(
                session,
                job,
                provider_key=prepared.provider_idempotency_key,
            )
            current = replace(prepared, attempt_count=job.attempt_count, message=message)
            async with asyncio.timeout(self._provider_timeout.total_seconds()):
                receipt = await self._dispatcher.dispatch(current)
            if not isinstance(receipt, DeliveryReceipt):
                raise AmbiguousProviderReceiptError(
                    "provider returned an unsupported receipt shape"
                )
            if receipt.idempotency_key != prepared.provider_idempotency_key:
                raise AmbiguousProviderReceiptError(
                    "provider receipt idempotency key did not match the durable dispatch"
                )
            if (
                not receipt.provider_message_id.strip()
                or len(receipt.provider_message_id) > 255
                or not isinstance(receipt.deduplicated, bool)
                or not isinstance(receipt.accepted_at, datetime)
                or receipt.accepted_at.tzinfo is None
            ):
                raise AmbiguousProviderReceiptError("provider returned invalid receipt evidence")
            if receipt.accepted is not True:
                raise PermanentProviderError("provider did not accept the durable dispatch")
            return receipt

    @staticmethod
    async def _resolve_message(
        session: AsyncSession,
        job: Job,
        *,
        provider_key: str,
    ) -> EmailMessage:
        payload = ENROLLMENT_WELCOME_ROUTE.normalize_payload(job.payload)
        if job.tenant_id is None:
            raise PermanentProviderError("enrollment welcome job requires a canonical tenant")
        enrollment_id = UUID(payload["enrollment_id"])
        entitlement_id = UUID(payload["entitlement_id"])
        provenance_id = UUID(payload["provenance_id"])
        person_id = UUID(payload["person_id"])
        program_version_id = UUID(payload["program_version_id"])
        person = await session.scalar(
            select(Person)
            .join(_ENROLLMENTS, _ENROLLMENTS.c.person_id == Person.id)
            .join(
                _ENTITLEMENTS,
                and_(
                    _ENTITLEMENTS.c.enrollment_id == _ENROLLMENTS.c.id,
                    _ENTITLEMENTS.c.person_id == _ENROLLMENTS.c.person_id,
                    _ENTITLEMENTS.c.tenant_id == _ENROLLMENTS.c.tenant_id,
                ),
            )
            .join(
                _ENROLLMENT_PROVENANCE,
                and_(
                    _ENROLLMENT_PROVENANCE.c.id == _ENTITLEMENTS.c.provenance_id,
                    _ENROLLMENT_PROVENANCE.c.enrollment_id == _ENROLLMENTS.c.id,
                    _ENROLLMENT_PROVENANCE.c.person_id == _ENROLLMENTS.c.person_id,
                    _ENROLLMENT_PROVENANCE.c.tenant_id == _ENROLLMENTS.c.tenant_id,
                ),
            )
            .where(
                Person.id == person_id,
                Person.status == PersonStatus.ACTIVE.value,
                Person.email_verified_at.is_not(None),
                _ENROLLMENTS.c.id == enrollment_id,
                _ENROLLMENTS.c.tenant_id == job.tenant_id,
                _ENROLLMENTS.c.person_id == person_id,
                _ENROLLMENTS.c.program_version_id == program_version_id,
                _ENROLLMENTS.c.source == payload["source"],
                _ENROLLMENTS.c.status == "active",
                _ENTITLEMENTS.c.id == entitlement_id,
                _ENTITLEMENTS.c.tenant_id == job.tenant_id,
                _ENTITLEMENTS.c.person_id == person_id,
                _ENTITLEMENTS.c.program_version_id == program_version_id,
                _ENTITLEMENTS.c.status == "active",
                _ENROLLMENT_PROVENANCE.c.id == provenance_id,
                _ENROLLMENT_PROVENANCE.c.tenant_id == job.tenant_id,
                _ENROLLMENT_PROVENANCE.c.person_id == person_id,
                _ENROLLMENT_PROVENANCE.c.program_version_id == program_version_id,
                _ENROLLMENT_PROVENANCE.c.source == payload["source"],
            )
            .with_for_update(read=True)
        )
        if (
            person is None
            or person.status != PersonStatus.ACTIVE.value
            or person.email is None
            or person.email_verified_at is None
        ):
            raise PermanentProviderError(
                "enrollment welcome recipient is not an active verified canonical identity"
            )
        return EmailMessage(
            to=person.email,
            template="enrollment-welcome",
            template_version=1,
            idempotency_key=provider_key,
            variables={
                "enrollment_id": payload["enrollment_id"],
                "program_version_id": payload["program_version_id"],
                "source": payload["source"],
            },
            communication_class="enrollment_welcome_next_action",
        )

    async def _execute_one(self, job: Job) -> dict[str, int]:
        lease_token = job.lease_token
        if lease_token is None:
            return {"claimed": 1}
        if job.provider_receipt is not None:
            try:
                await self._complete(job.id, lease_token)
            except LeaseLostError as error:
                self._logger.warning("worker_job_ack_fenced", error_code=type(error).__name__)
                return {"claimed": 1}
            self._emit("worker.job.succeeded", job, outcome="succeeded")
            return {"claimed": 1, "succeeded": 1}
        try:
            prepared = await self._prepare_dispatch(job.id, lease_token)
        except (LeaseLostError, ReconciliationRequiredError) as error:
            self._logger.warning("worker_dispatch_fenced", error_code=type(error).__name__)
            return {"claimed": 1}
        except (PermanentProviderError, ValueError) as error:
            return await self._safe_fail(job, lease_token, error, permanent=True)
        except Exception as error:
            return await self._safe_fail(job, lease_token, error, permanent=False)

        try:
            receipt = await self._dispatch_under_recovery_fence(prepared)
        except (LeaseLostError, ReconciliationRequiredError) as error:
            if isinstance(error, ReconciliationRequiredError):
                self._ready = False
            self._logger.warning("worker_dispatch_fenced", error_code=type(error).__name__)
            return {"claimed": 1}
        except TimeoutError as error:
            return await self._safe_fail(
                job,
                lease_token,
                error,
                permanent=False,
                ambiguous=True,
                provider_idempotency_key=prepared.provider_idempotency_key,
            )
        except AmbiguousProviderReceiptError as error:
            return await self._safe_fail(
                job,
                lease_token,
                error,
                permanent=True,
                ambiguous=True,
                provider_idempotency_key=prepared.provider_idempotency_key,
            )
        except PermanentProviderError as error:
            return await self._safe_fail(job, lease_token, error, permanent=True)
        except TransientProviderError as error:
            return await self._safe_fail(job, lease_token, error, permanent=False)
        except Exception as error:  # adapter bugs/network uncertainty must not stop the batch
            return await self._safe_fail(
                job,
                lease_token,
                error,
                permanent=False,
                ambiguous=True,
                provider_idempotency_key=prepared.provider_idempotency_key,
            )

        receipt_payload = _receipt_payload(receipt)
        try:
            await self._record_receipt(job.id, lease_token, receipt_payload)
        except LeaseLostError as error:
            with suppress(LeaseLostError, JobStateError):
                await self._record_ambiguous(
                    job.id,
                    lease_token=lease_token,
                    recovery_generation=job.recovery_generation,
                    provider_idempotency_key=prepared.provider_idempotency_key,
                    error=error,
                )
            self._logger.warning("worker_job_ack_fenced", error_code=type(error).__name__)
            return {"claimed": 1}
        except Exception as error:
            return await self._safe_fail(
                job,
                lease_token,
                error,
                permanent=isinstance(error, DuplicateIntentError),
                ambiguous=True,
                provider_idempotency_key=prepared.provider_idempotency_key,
            )
        try:
            await self._complete(job.id, lease_token)
        except LeaseLostError as error:
            self._logger.warning("worker_job_ack_fenced", error_code=type(error).__name__)
            return {"claimed": 1}
        except Exception as error:
            self._logger.warning("worker_job_ack_failed", error_code=type(error).__name__)
            return {"claimed": 1}
        self._emit("worker.job.succeeded", job, outcome="succeeded")
        return {"claimed": 1, "succeeded": 1}

    async def _safe_fail(
        self,
        job: Job,
        lease_token: UUID,
        error: BaseException,
        *,
        permanent: bool,
        ambiguous: bool = False,
        provider_idempotency_key: str | None = None,
    ) -> dict[str, int]:
        try:
            failed = await self._fail(
                job.id,
                lease_token,
                error,
                permanent=permanent,
                ambiguous=ambiguous,
            )
        except LeaseLostError:
            if ambiguous and provider_idempotency_key is not None:
                with suppress(LeaseLostError, JobStateError):
                    await self._record_ambiguous(
                        job.id,
                        lease_token=lease_token,
                        recovery_generation=job.recovery_generation,
                        provider_idempotency_key=provider_idempotency_key,
                        error=error,
                    )
            self._logger.warning("worker_job_failure_fenced", error_code=type(error).__name__)
            return {"claimed": 1}
        dead_lettered = failed.status == JobStatus.DEAD_LETTER.value
        outcome = "dead_lettered" if dead_lettered else "retry_wait"
        self._emit(f"worker.job.{outcome}", job, outcome=outcome, error=error)
        return {
            "claimed": 1,
            "dead_lettered": int(dead_lettered),
            "retried": int(not dead_lettered),
        }

    async def _record_receipt(
        self,
        job_id: UUID,
        lease_token: UUID,
        receipt: Mapping[str, Any],
    ) -> None:
        async with self._session_factory() as session, session.begin():
            await JobRepository(session).record_receipt(job_id, lease_token, receipt)

    async def _complete(self, job_id: UUID, lease_token: UUID) -> None:
        async with self._session_factory() as session, session.begin():
            await JobRepository(session).complete(job_id, lease_token)

    async def _fail(
        self,
        job_id: UUID,
        lease_token: UUID,
        error: BaseException,
        *,
        permanent: bool,
        ambiguous: bool,
    ) -> Job:
        async with self._session_factory() as session, session.begin():
            return await JobRepository(session).fail(
                job_id,
                lease_token,
                error,
                permanent=permanent,
                ambiguous=ambiguous,
            )

    async def _record_ambiguous(
        self,
        job_id: UUID,
        *,
        lease_token: UUID,
        recovery_generation: int,
        provider_idempotency_key: str,
        error: BaseException,
    ) -> None:
        async with self._session_factory() as session, session.begin():
            await JobRepository(session).record_delivery_ambiguity(
                job_id,
                lease_token=lease_token,
                recovery_generation=recovery_generation,
                provider_idempotency_key=provider_idempotency_key,
                error=error,
            )

    def _emit(
        self,
        name: str,
        job: Job,
        *,
        outcome: str,
        error: BaseException | None = None,
    ) -> None:
        attributes: dict[str, Any] = {
            "job_kind": job.kind,
            "attempt": job.attempt_count,
            "outcome": outcome,
        }
        if error is not None:
            attributes["error_code"] = _error_code(error)
        self._telemetry.emit(
            name,
            attributes,
            category=TelemetryCategory.OPERATIONAL,
        )


def _receipt_payload(receipt: DeliveryReceipt) -> dict[str, Any]:
    return {
        "idempotency_key": receipt.idempotency_key,
        "provider_message_id": receipt.provider_message_id,
        "accepted": receipt.accepted,
        "deduplicated": receipt.deduplicated,
        "accepted_at": receipt.accepted_at.isoformat(),
    }


def _error_code(error: BaseException) -> str:
    value = re.sub(r"(?<!^)(?=[A-Z])", "_", type(error).__name__).lower()
    return value[:64] or "provider_error"


async def run() -> None:
    await DurableWorker().run()


def main() -> None:
    asyncio.run(run())


__all__ = [
    "AmbiguousProviderReceiptError",
    "AllowlistedDispatcher",
    "DurableWorker",
    "ENROLLMENT_WELCOME_EVENT",
    "ENROLLMENT_WELCOME_JOB",
    "ENROLLMENT_WELCOME_ROUTE",
    "OUTBOX_JOB_ROUTES",
    "PreparedDispatch",
    "SessionFactory",
    "UnknownJobKindError",
    "WorkerNotReadyError",
    "WorkerRunResult",
    "build_default_dispatcher",
    "main",
    "run",
]
