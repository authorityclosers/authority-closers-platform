"""Dormant, bounded internal minute-expiry worker; no enqueue or provider route."""

from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.billing.expiry import ExpiryConflict, ExpiryScopeRefused, MinuteExpiryService
from ac_platform.billing.trial import TrialPolicy
from ac_platform.outbox.models import Job, JobStatus
from ac_platform.outbox.policy import ReconciliationRequiredError
from ac_platform.outbox.repository import JobRepository, LeaseLostError, RecoveryStateRepository

EXPIRY_JOB_KIND = "billing.capacity_expiry.v1"
ExpirySignal = Callable[[str, Mapping[str, str | bool]], None]
ExpirySessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class ExpiryIntentRefused(ValueError):
    """The stored intent does not have the exact trusted internal schema."""


@dataclass(frozen=True, slots=True)
class ExpiryWorkerResult:
    """Content-free pass receipt; only committed writes contribute counters."""

    outcome: Literal["idle", "succeeded", "dead_lettered", "retry_wait", "fenced", "unavailable"]
    claimed: int = 0
    closings: int = 0
    expired_seconds: int = 0
    deferred_lots: int = 0


@dataclass(frozen=True, slots=True)
class _Claim:
    job_id: UUID
    lease_token: UUID
    generation: int


def validate_expiry_intent(job: Job, *, operations_tenant_id: UUID) -> tuple[UUID, UUID]:
    """Payload supplies an account reference only; the service resolves authority."""
    if (
        job.kind != EXPIRY_JOB_KIND
        or job.external_side_effect is not False
        or type(job.tenant_id) is not UUID
        or job.tenant_id == operations_tenant_id
        or type(job.payload) is not dict
        or set(job.payload) != {"account_id"}
        or type(job.payload["account_id"]) is not str
    ):
        raise ExpiryIntentRefused("expiry_intent_refused")
    try:
        account_id = UUID(job.payload["account_id"])
    except ValueError:
        raise ExpiryIntentRefused("expiry_intent_refused") from None
    return job.tenant_id, account_id


class MinuteExpiryWorker:
    def __init__(
        self,
        *,
        session_factory: ExpirySessionFactory,
        public_learner_tenant_id: UUID,
        operations_tenant_id: UUID,
        trial_policy: TrialPolicy,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        signal: ExpirySignal | None = None,
    ) -> None:
        if (
            type(public_learner_tenant_id) is not UUID
            or type(operations_tenant_id) is not UUID
            or public_learner_tenant_id == operations_tenant_id
            or not isinstance(trial_policy, TrialPolicy)
            or not callable(session_factory)
            or not callable(clock)
            or (signal is not None and not callable(signal))
        ):
            raise ValueError("expiry_composition_refused")
        self._sessions = session_factory
        self._public = public_learner_tenant_id
        self._operations = operations_tenant_id
        self._trial = trial_policy
        self._clock = clock
        self._signal = signal
        self._logger = structlog.get_logger(__name__)

    def _now(self) -> datetime:
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("expiry_clock_refused")
        return now.astimezone(UTC)

    async def run_once(self) -> ExpiryWorkerResult:
        """Claim at most one job; commit its expiry, audit and success together.

        Lock order is recovery, job, tenant admission. Internal jobs store
        generation zero: carry the global generation observed at claim instead
        of replacing it with a generation observed after rollback or restore.
        """
        try:
            async with self._sessions() as db, db.begin():
                recovery = await RecoveryStateRepository(db).require_ready(
                    lock=True, shared_lock=True
                )
                jobs = await JobRepository(db).claim(now=self._now(), kinds=(EXPIRY_JOB_KIND,))
                if not jobs:
                    return ExpiryWorkerResult("idle")
                job = jobs[0]
                if job.lease_token is None:
                    raise LeaseLostError("expiry_claim_fenced")
                claim = _Claim(job.id, job.lease_token, recovery.generation)
        except (LeaseLostError, ReconciliationRequiredError):
            return ExpiryWorkerResult("fenced")
        except Exception:
            return ExpiryWorkerResult("unavailable")

        try:
            async with self._sessions() as db, db.begin():
                repository = JobRepository(db)
                job = await repository.lock_internal_lease(
                    claim.job_id,
                    claim.lease_token,
                    kind=EXPIRY_JOB_KIND,
                    recovery_generation=claim.generation,
                )
                tenant_id, account_id = validate_expiry_intent(
                    job, operations_tenant_id=self._operations
                )
                result = await MinuteExpiryService(
                    db,
                    public_learner_tenant_id=self._public,
                    operations_tenant_id=self._operations,
                    trial_policy=self._trial,
                    clock=self._now,
                ).expire_due(tenant_id=tenant_id, account_id=account_id)
                await repository.complete(job, claim.lease_token)
                receipt = ExpiryWorkerResult(
                    "succeeded",
                    claimed=1,
                    closings=len(result.closings),
                    expired_seconds=sum(closing.seconds for closing in result.closings),
                    deferred_lots=len(result.deferred_pending_lot_ids),
                )
            return receipt
        except (LeaseLostError, ReconciliationRequiredError):
            return ExpiryWorkerResult("fenced", claimed=1)
        except ExpiryConflict:
            return await self._fail(claim, code="expiry_conflict", permanent=True, conflict=True)
        except (ExpiryIntentRefused, ExpiryScopeRefused, ValueError, TypeError):
            return await self._fail(claim, code="expiry_refused", permanent=True)
        except Exception:
            # Never persist or log raw exception text, driver parameters or IDs.
            return await self._fail(claim, code="expiry_transient_failure", permanent=False)

    async def _fail(
        self, claim: _Claim, *, code: str, permanent: bool, conflict: bool = False
    ) -> ExpiryWorkerResult:
        try:
            async with self._sessions() as db, db.begin():
                repository = JobRepository(db)
                job = await repository.lock_internal_lease(
                    claim.job_id,
                    claim.lease_token,
                    kind=EXPIRY_JOB_KIND,
                    recovery_generation=claim.generation,
                )
                failed = await repository.fail(job, claim.lease_token, code, permanent=permanent)
                dead_lettered = failed.status == JobStatus.DEAD_LETTER.value
        except (LeaseLostError, ReconciliationRequiredError):
            return ExpiryWorkerResult("fenced", claimed=1)
        except Exception:
            # Leave the lease for existing bounded crash/reclaim handling.
            return ExpiryWorkerResult("unavailable", claimed=1)
        if conflict:
            attributes: dict[str, str | bool] = {"outcome": "dead_lettered", "retryable": False}
            self._logger.warning("billing.expiry_conflict", **attributes)
            if self._signal is not None:
                # An operational hook cannot change a committed canonical outcome.
                with suppress(Exception):
                    self._signal("billing.expiry_conflict", attributes)
        return ExpiryWorkerResult("dead_lettered" if dead_lettered else "retry_wait", claimed=1)
