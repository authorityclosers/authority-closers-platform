"""Async repositories for transactional outbox and leased jobs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import Select, and_, exists, func, literal, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.service import AuditRepository
from ac_platform.kernel.authz import ActorContext
from ac_platform.kernel.events import EventCategory, EventEnvelope
from ac_platform.outbox.errors import (
    DuplicateIntentError,
    JobStateError,
    LeaseLostError,
    RetryNotAllowedError,
)
from ac_platform.outbox.models import (
    Job,
    JobStatus,
    OperationsRecoveryState,
    OutboxEvent,
    OutboxEventStatus,
    RecoveryStatus,
    utc_now,
)
from ac_platform.outbox.policy import (
    ReconciliationRequiredError,
    SideEffectHoldPolicy,
    recovery_actor_id,
    recovery_hold_timestamp,
)
from ac_platform.telemetry.redaction import sanitize_error

MAX_JOB_LEASE = timedelta(minutes=15)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _required_text(value: str, field_name: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    if len(normalized) > maximum:
        raise ValueError(f"{field_name} must be at most {maximum} characters")
    return normalized


def _bounded_error(error: str | BaseException, *, maximum: int = 2000) -> str:
    return sanitize_error(error, max_length=maximum)


def _require_same_transaction_audit(
    session: AsyncSession,
    audit: AuditRepository,
) -> None:
    if audit.session is not session:
        raise ValueError("audit evidence must use the same transaction as the operation")


def _dialect_name(session: AsyncSession) -> str | None:
    bind = session.get_bind()
    dialect = getattr(getattr(bind, "dialect", None), "name", None)
    return dialect if isinstance(dialect, str) else None


def _db_time_plus(*, seconds: float, dialect: str | None) -> Any:
    """Return a dialect-safe expression anchored to the database clock."""

    if dialect == "sqlite":
        return func.datetime(func.current_timestamp(), f"+{seconds:g} seconds")
    return func.now() + literal(seconds) * text("INTERVAL '1 second'")


def _lease_seconds(lease_for: timedelta) -> float:
    seconds = lease_for.total_seconds()
    if seconds <= 0 or lease_for > MAX_JOB_LEASE:
        raise ValueError("lease_for must be greater than zero and at most 15 minutes")
    return seconds


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Small deterministic exponential backoff policy with hard bounds."""

    max_attempts: int = 5
    base_delay: timedelta = timedelta(seconds=5)
    max_delay: timedelta = timedelta(minutes=5)

    def __post_init__(self) -> None:
        if not 1 <= self.max_attempts <= 25:
            raise ValueError("max_attempts must be between 1 and 25")
        if self.base_delay <= timedelta(0):
            raise ValueError("base_delay must be positive")
        if self.max_delay < self.base_delay:
            raise ValueError("max_delay must be at least base_delay")
        if self.max_delay > timedelta(hours=1):
            raise ValueError("max_delay must not exceed one hour")

    def delay_for_attempt(
        self,
        attempt_count: int,
        *,
        jitter_key: UUID | str | None = None,
    ) -> timedelta:
        """Return bounded exponential backoff with deterministic positive jitter."""

        if attempt_count < 1:
            raise ValueError("attempt_count must be at least one")
        multiplier: int = 2 ** min(attempt_count - 1, 20)
        delay: timedelta = self.base_delay * multiplier
        delay = min(delay, self.max_delay)
        if jitter_key is None or delay >= self.max_delay:
            return delay
        jitter_cap = min(delay * 0.25, self.max_delay - delay)
        sample = int.from_bytes(
            hashlib.sha256(f"{jitter_key}:{attempt_count}".encode()).digest()[:2],
            "big",
        )
        return delay + jitter_cap * (sample / 65_535)


@dataclass(frozen=True, slots=True)
class OutboxJobRoute:
    """Exact versioned mapping from one outbox event to one durable job kind."""

    job_kind: str
    required_payload_keys: frozenset[str]
    uuid_payload_keys: frozenset[str] = frozenset()
    allowed_payload_values: Mapping[str, frozenset[str]] = field(default_factory=dict)
    max_attempts: int = 5

    def __post_init__(self) -> None:
        object.__setattr__(self, "job_kind", _required_text(self.job_kind, "job_kind", 128))
        if not self.required_payload_keys:
            raise ValueError("outbox route requires an explicit payload schema")
        if any(
            not isinstance(key, str) or not key.strip() or len(key) > 64
            for key in self.required_payload_keys
        ):
            raise ValueError("outbox route payload keys must be bounded non-blank strings")
        if not self.uuid_payload_keys.issubset(self.required_payload_keys):
            raise ValueError("UUID payload keys must be part of the required schema")
        normalized_allowlists = {
            key: frozenset(values) for key, values in self.allowed_payload_values.items()
        }
        if not set(normalized_allowlists).issubset(self.required_payload_keys):
            raise ValueError("allowlisted value keys must be part of the required schema")
        if any(not values for values in normalized_allowlists.values()):
            raise ValueError("allowlisted payload values must not be empty")
        if any(
            not isinstance(value, str) or not value.strip() or len(value) > 500
            for values in normalized_allowlists.values()
            for value in values
        ):
            raise ValueError("allowlisted payload values must be bounded non-blank strings")
        object.__setattr__(
            self,
            "allowed_payload_values",
            MappingProxyType(normalized_allowlists),
        )
        if not 1 <= self.max_attempts <= 25:
            raise ValueError("route max_attempts must be between 1 and 25")

    def normalize_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Reject schema drift and canonicalize UUID identifiers."""

        if not isinstance(payload, Mapping):
            raise ValueError("outbox payload must be an object")
        if set(payload) != set(self.required_payload_keys):
            raise ValueError("outbox payload does not match the allowlisted versioned schema")
        normalized: dict[str, Any] = {}
        for key in sorted(self.required_payload_keys):
            value = payload[key]
            if key in self.uuid_payload_keys:
                try:
                    normalized[key] = str(UUID(str(value)))
                except (TypeError, ValueError, AttributeError) as error:
                    raise ValueError(f"outbox payload field {key} must be a UUID") from error
            elif isinstance(value, str):
                normalized_value = _required_text(value, key, 500)
                allowed_values = self.allowed_payload_values.get(key)
                if allowed_values is not None and normalized_value not in allowed_values:
                    raise ValueError(f"outbox payload field {key} is not allowlisted")
                normalized[key] = normalized_value
            elif value is None or isinstance(value, bool | int | float):
                normalized[key] = value
            else:
                raise ValueError(f"outbox payload field {key} has an unsupported type")
        return normalized


def canonical_receipt_digest(receipt: Mapping[str, Any]) -> str:
    """Hash canonical provider evidence before storing it on a job."""

    canonical = json.dumps(
        dict(receipt),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def build_job_claim_statement(
    *,
    now: datetime,
    recovery_generation: int,
    limit: int = 1,
) -> Select[tuple[Job]]:
    """Build the row-locking claim query.

    PostgreSQL executes the ``FOR UPDATE SKIP LOCKED`` seam. Dialects without
    row-lock support simply ignore that clause, which keeps unit tests useful
    while leaving the production concurrency contract visible in one place.
    """

    if limit < 1 or limit > 500:
        raise ValueError("limit must be between 1 and 500")
    del now
    queued = Job.status.in_((JobStatus.QUEUED.value, JobStatus.RETRY_WAIT.value))
    eligible_queued = and_(queued, Job.available_at <= func.now())
    expired_lease = and_(
        Job.status == JobStatus.LEASED.value,
        Job.leased_until.is_not(None),
        Job.leased_until <= func.now(),
    )
    generation_is_current = or_(
        Job.external_side_effect.is_(False),
        Job.recovery_generation == recovery_generation,
    )
    recovery_is_ready = exists(
        select(OperationsRecoveryState.id).where(
            OperationsRecoveryState.id == 1,
            OperationsRecoveryState.status == RecoveryStatus.READY.value,
            OperationsRecoveryState.generation == recovery_generation,
        )
    )
    return (
        select(Job)
        .where(
            or_(eligible_queued, expired_lease),
            generation_is_current,
            recovery_is_ready,
            Job.attempt_count < Job.max_attempts,
        )
        .order_by(Job.available_at.asc(), Job.created_at.asc(), Job.id.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )


def build_job_take_statement(
    *,
    job_id: UUID,
    lease_token: UUID,
    lease_for: timedelta,
    recovery_generation: int,
    dialect: str = "postgresql",
) -> Any:
    """Build the database-clock transition that claims exactly one job."""

    seconds = _lease_seconds(lease_for)
    queued = and_(
        Job.status.in_((JobStatus.QUEUED.value, JobStatus.RETRY_WAIT.value)),
        Job.available_at <= func.now(),
    )
    expired = and_(
        Job.status == JobStatus.LEASED.value,
        Job.leased_until <= func.now(),
    )
    return (
        update(Job)
        .where(
            Job.id == job_id,
            or_(queued, expired),
            Job.attempt_count < Job.max_attempts,
            or_(
                Job.external_side_effect.is_(False),
                and_(
                    Job.recovery_generation == recovery_generation,
                    exists(
                        select(OperationsRecoveryState.id).where(
                            OperationsRecoveryState.id == 1,
                            OperationsRecoveryState.status == RecoveryStatus.READY.value,
                            OperationsRecoveryState.generation == recovery_generation,
                        )
                    ),
                ),
            ),
        )
        .values(
            status=JobStatus.LEASED.value,
            attempt_count=Job.attempt_count + 1,
            lease_token=lease_token,
            leased_until=_db_time_plus(seconds=seconds, dialect=dialect),
            held_at=None,
            hold_reason=None,
            dead_lettered_at=None,
            last_error=None,
            updated_at=func.now(),
        )
    )


def build_job_exhausted_statement(*, recovery_generation: int) -> Any:
    """Dead-letter available jobs whose bounded attempt budget is exhausted."""

    available = or_(
        and_(
            Job.status.in_((JobStatus.QUEUED.value, JobStatus.RETRY_WAIT.value)),
            Job.available_at <= func.now(),
        ),
        and_(Job.status == JobStatus.LEASED.value, Job.leased_until <= func.now()),
    )
    return (
        update(Job)
        .where(
            available,
            Job.attempt_count >= Job.max_attempts,
            or_(
                Job.external_side_effect.is_(False),
                Job.recovery_generation == recovery_generation,
            ),
        )
        .values(
            status=JobStatus.DEAD_LETTER.value,
            lease_token=None,
            leased_until=None,
            held_at=None,
            hold_reason=None,
            dead_lettered_at=func.now(),
            available_at=func.now(),
            last_error="job attempt budget exhausted",
            updated_at=func.now(),
        )
    )


def build_job_renew_statement(
    *,
    job_id: UUID,
    lease_token: UUID,
    lease_for: timedelta,
    recovery_generation: int,
    dialect: str = "postgresql",
) -> Any:
    """Build a database-clock, fenced lease renewal."""

    seconds = _lease_seconds(lease_for)
    return (
        update(Job)
        .where(
            Job.id == job_id,
            Job.status == JobStatus.LEASED.value,
            Job.lease_token == lease_token,
            Job.leased_until > func.now(),
            or_(
                Job.external_side_effect.is_(False),
                and_(
                    Job.recovery_generation == recovery_generation,
                    exists(
                        select(OperationsRecoveryState.id).where(
                            OperationsRecoveryState.id == 1,
                            OperationsRecoveryState.status == RecoveryStatus.READY.value,
                            OperationsRecoveryState.generation == recovery_generation,
                        )
                    ),
                ),
            ),
        )
        .values(
            leased_until=_db_time_plus(seconds=seconds, dialect=dialect),
            updated_at=func.now(),
        )
    )


def build_job_acknowledge_statement(*, job_id: UUID, lease_token: UUID) -> Any:
    """Build a fenced success acknowledgement using the database clock."""

    return (
        update(Job)
        .where(
            Job.id == job_id,
            Job.status == JobStatus.LEASED.value,
            Job.lease_token == lease_token,
            Job.leased_until > func.now(),
            or_(Job.external_side_effect.is_(False), Job.provider_receipt.is_not(None)),
        )
        .values(
            status=JobStatus.SUCCEEDED.value,
            leased_until=None,
            lease_token=None,
            last_error=None,
            updated_at=func.now(),
        )
    )


def build_job_dispatch_statement(
    *,
    job_id: UUID,
    lease_token: UUID,
    recovery_generation: int,
    provider_idempotency_key: str,
) -> Any:
    """Persist dispatch-start evidence only while the global generation is ready."""

    return (
        update(Job)
        .where(
            Job.id == job_id,
            Job.status == JobStatus.LEASED.value,
            Job.lease_token == lease_token,
            Job.leased_until > func.now(),
            Job.external_side_effect.is_(True),
            Job.recovery_generation == recovery_generation,
            exists(
                select(OperationsRecoveryState.id).where(
                    OperationsRecoveryState.id == 1,
                    OperationsRecoveryState.status == RecoveryStatus.READY.value,
                    OperationsRecoveryState.generation == recovery_generation,
                )
            ),
        )
        .values(
            provider_idempotency_key=provider_idempotency_key,
            dispatch_started_at=func.now(),
            updated_at=func.now(),
        )
    )


def build_job_receipt_statement(
    *,
    job_id: UUID,
    lease_token: UUID,
    receipt: Mapping[str, Any],
    receipt_digest: str,
) -> Any:
    """Persist canonical provider receipt evidence under the live job lease."""

    return (
        update(Job)
        .where(
            Job.id == job_id,
            Job.status == JobStatus.LEASED.value,
            Job.lease_token == lease_token,
            Job.leased_until > func.now(),
        )
        .values(
            provider_receipt=dict(receipt),
            provider_receipt_digest=receipt_digest,
            receipt_recorded_at=func.now(),
            updated_at=func.now(),
        )
    )


def build_job_ambiguity_statement(
    *,
    job_id: UUID,
    lease_token: UUID,
    recovery_generation: int,
    provider_idempotency_key: str,
    error: str,
) -> Any:
    """Record uncertainty only while the exact effect lease is still live."""

    return (
        update(Job)
        .where(
            Job.id == job_id,
            Job.status == JobStatus.LEASED.value,
            Job.lease_token == lease_token,
            Job.leased_until > func.now(),
            Job.external_side_effect.is_(True),
            Job.recovery_generation == recovery_generation,
            Job.provider_idempotency_key == provider_idempotency_key,
            Job.dispatch_started_at.is_not(None),
            Job.provider_receipt.is_(None),
            Job.provider_receipt_digest.is_(None),
            Job.receipt_recorded_at.is_(None),
            exists(
                select(OperationsRecoveryState.id).where(
                    OperationsRecoveryState.id == 1,
                    OperationsRecoveryState.status == RecoveryStatus.READY.value,
                    OperationsRecoveryState.generation == recovery_generation,
                )
            ),
        )
        .values(
            delivery_ambiguous_at=func.now(),
            last_error=error,
            updated_at=func.now(),
        )
    )


def build_job_failure_statement(
    *,
    job_id: UUID,
    lease_token: UUID,
    dead_letter: bool,
    retry_delay: timedelta = timedelta(0),
    last_error: str | None = None,
    ambiguous: bool = False,
    dialect: str = "postgresql",
) -> Any:
    """Build a fenced failure acknowledgement with bounded retry scheduling."""

    if retry_delay < timedelta(0) or retry_delay > timedelta(hours=1):
        raise ValueError("retry_delay must be between zero and one hour")
    values: dict[str, Any] = {
        "status": JobStatus.DEAD_LETTER.value if dead_letter else JobStatus.RETRY_WAIT.value,
        "leased_until": None,
        "lease_token": None,
        "updated_at": func.now(),
    }
    if last_error is not None:
        values["last_error"] = last_error
    if ambiguous:
        values["delivery_ambiguous_at"] = func.now()
    if dead_letter:
        values.update(
            dead_lettered_at=func.now(),
            available_at=func.now(),
        )
    else:
        values["available_at"] = _db_time_plus(seconds=retry_delay.total_seconds(), dialect=dialect)
    return (
        update(Job)
        .where(
            Job.id == job_id,
            Job.status == JobStatus.LEASED.value,
            Job.lease_token == lease_token,
            Job.leased_until > func.now(),
        )
        .values(**values)
    )


def _on_conflict_insert(
    *,
    table: Any,
    values: Mapping[str, Any],
    key_columns: list[Any],
    dialect: str,
) -> Any:
    if dialect == "postgresql":
        return (
            postgresql_insert(table)
            .values(**values)
            .on_conflict_do_nothing(index_elements=key_columns)
            .returning(table.id)
        )
    if dialect == "sqlite":
        return (
            sqlite_insert(table)
            .values(**values)
            .on_conflict_do_nothing(index_elements=key_columns)
            .returning(table.id)
        )
    raise ValueError(f"unsupported dedupe SQL dialect: {dialect}")


class RecoveryStateRepository:
    """Database-authoritative global fence for external side effects."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self,
        *,
        lock: bool = False,
        shared_lock: bool = False,
    ) -> OperationsRecoveryState | None:
        statement = select(OperationsRecoveryState).where(OperationsRecoveryState.id == 1)
        if shared_lock:
            lock = True
        if lock:
            statement = statement.with_for_update(read=shared_lock)
        return cast(OperationsRecoveryState | None, await self._session.scalar(statement))

    async def require_ready(
        self,
        *,
        expected_generation: int | None = None,
        lock: bool = False,
        shared_lock: bool = False,
    ) -> OperationsRecoveryState:
        state = await self.get(lock=lock, shared_lock=shared_lock)
        if state is None:
            raise ReconciliationRequiredError("durable recovery state is missing")
        if state.status != RecoveryStatus.READY.value:
            raise ReconciliationRequiredError(
                "database recovery generation is held pending audited reconciliation"
            )
        if expected_generation is not None and state.generation != expected_generation:
            raise ReconciliationRequiredError("job belongs to a stale database recovery generation")
        return state

    async def require_held(self, *, lock: bool = False) -> OperationsRecoveryState:
        state = await self.get(lock=lock)
        if state is None:
            raise ReconciliationRequiredError("durable recovery state is missing")
        if state.status != RecoveryStatus.HELD.value:
            raise ReconciliationRequiredError(
                "restore hold requires the durable recovery generation to be held first"
            )
        return state

    async def mark_restore(
        self,
        *,
        reason: str = "database_restore_requires_reconciliation",
        now: datetime | None = None,
    ) -> OperationsRecoveryState:
        state = await self.get(lock=True)
        if state is None:
            raise ReconciliationRequiredError("durable recovery state is missing")
        current_time = recovery_hold_timestamp(now)
        state.generation += 1
        state.status = RecoveryStatus.HELD.value
        state.marked_at = current_time
        state.hold_reason = _required_text(reason, "reason", 500)
        state.reconciled_at = None
        state.reconciled_by = None
        state.reconciliation_reason = None
        state.updated_at = current_time
        await self._session.flush()
        return state

    async def reconcile(
        self,
        *,
        actor: ActorContext,
        reason: str,
        audit: AuditRepository,
        now: datetime | None = None,
    ) -> OperationsRecoveryState:
        actor.require_permission("recovery_reconcile")
        _require_same_transaction_audit(self._session, audit)
        if actor.tenant_id is None:
            raise JobStateError("recovery reconciliation requires an attributable tenant")
        state = await self.get(lock=True)
        if state is None:
            raise ReconciliationRequiredError("durable recovery state is missing")
        if state.status == RecoveryStatus.READY.value:
            return state
        held_outbox = cast(
            int | None,
            await self._session.scalar(
                select(func.count(OutboxEvent.id)).where(
                    OutboxEvent.status == OutboxEventStatus.HELD.value
                )
            ),
        )
        held_jobs = cast(
            int | None,
            await self._session.scalar(
                select(func.count(Job.id)).where(
                    Job.status == JobStatus.HELD.value,
                    Job.external_side_effect.is_(True),
                )
            ),
        )
        if int(held_outbox or 0) or int(held_jobs or 0):
            raise ReconciliationRequiredError(
                "all held outbox events and external jobs must be explicitly reconciled"
            )
        normalized_reason = SideEffectHoldPolicy.normalize_reconciliation_reason(reason)
        current_time = recovery_hold_timestamp(now)
        await audit.append_for_actor(
            actor,
            action="operations.recovery_generation_reconciled",
            resource_type="operations_recovery_state",
            resource_id=str(state.generation),
            payload={"generation": state.generation, "previous_hold_reason": state.hold_reason},
            reason=normalized_reason,
            now=current_time,
        )
        state.status = RecoveryStatus.READY.value
        state.reconciled_at = current_time
        state.reconciled_by = actor.person_id
        state.reconciliation_reason = normalized_reason
        state.updated_at = current_time
        await self._session.flush()
        return state


class OutboxRepository:
    """Persist and advance outbox intents without committing the caller's UoW."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue(
        self,
        event: EventEnvelope,
        *,
        dedupe_key: str | None = None,
    ) -> OutboxEvent:
        """Insert one event, returning the existing equivalent intent on replay."""

        if event.category is EventCategory.AUDIT or event.name.startswith("audit."):
            raise ValueError("audit events use the append-only audit store, not the outbox")
        key = _required_text(dedupe_key or str(event.event_id), "dedupe_key", 255)
        existing = await self._session.scalar(
            select(OutboxEvent).where(OutboxEvent.dedupe_key == key)
        )
        if existing is not None:
            if self._same_intent(existing, event):
                return existing
            raise DuplicateIntentError("dedupe key was reused for a different outbox intent")

        values = {
            "id": event.event_id,
            "tenant_id": event.tenant_id,
            "event_type": event.name,
            "aggregate_type": event.aggregate_type,
            "aggregate_id": event.aggregate_id,
            "dedupe_key": key,
            "payload": dict(event.payload),
            "occurred_at": _as_utc(event.occurred_at),
        }
        dialect = _dialect_name(self._session)
        if dialect in {"postgresql", "sqlite"}:
            result = cast(
                Any,
                await self._session.execute(
                    _on_conflict_insert(
                        table=OutboxEvent,
                        values=values,
                        key_columns=[OutboxEvent.dedupe_key],
                        dialect=dialect,
                    )
                ),
            )
            inserted_id = result.scalar_one_or_none()
            if inserted_id is None:
                existing = cast(
                    OutboxEvent | None,
                    await self._session.scalar(
                        select(OutboxEvent).where(OutboxEvent.dedupe_key == key)
                    ),
                )
                if existing is None:
                    raise RuntimeError("outbox conflict did not reload a canonical row")
                if not self._same_intent(existing, event):
                    raise DuplicateIntentError(
                        "dedupe key was reused for a different outbox intent"
                    )
                return existing
            canonical = cast(OutboxEvent | None, await self._session.get(OutboxEvent, inserted_id))
            if canonical is None:
                raise RuntimeError("outbox insert did not reload its canonical row")
            return canonical

        row = OutboxEvent(**values)
        try:
            async with self._session.begin_nested():
                self._session.add(row)
                await self._session.flush()
        except IntegrityError as error:
            existing = cast(
                OutboxEvent | None,
                await self._session.scalar(
                    select(OutboxEvent).where(OutboxEvent.dedupe_key == key)
                ),
            )
            if existing is None:
                raise
            if not self._same_intent(existing, event):
                raise DuplicateIntentError(
                    "dedupe key was reused for a different outbox intent"
                ) from error
            return existing
        return row

    async def enqueue_event(
        self,
        event: EventEnvelope,
        *,
        dedupe_key: str | None = None,
    ) -> OutboxEvent:
        """Explicitly named alias for callers composing a transactional command."""

        return await self.enqueue(event, dedupe_key=dedupe_key)

    async def claim_pending(
        self,
        *,
        now: datetime | None = None,
        limit: int = 50,
    ) -> list[OutboxEvent]:
        """Claim pending intents under a row lock for downstream job creation."""

        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        del now
        statement = (
            select(OutboxEvent)
            .where(OutboxEvent.status == OutboxEventStatus.PENDING.value)
            .order_by(OutboxEvent.created_at.asc(), OutboxEvent.id.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        rows = list((await self._session.scalars(statement)).all())
        for row in rows:
            row.publish_attempts = (row.publish_attempts or 0) + 1
            row.last_error = None
        await self._session.flush()
        return rows

    async def claim(self, *, now: datetime | None = None, limit: int = 50) -> list[OutboxEvent]:
        """Alias for :meth:`claim_pending`."""

        return await self.claim_pending(now=now, limit=limit)

    async def mark_published(
        self,
        event: OutboxEvent | UUID,
        *,
        published_at: datetime | None = None,
    ) -> OutboxEvent:
        row = await self._get_outbox(event)
        if row.status == OutboxEventStatus.PUBLISHED.value:
            return row
        if row.status != OutboxEventStatus.PENDING.value:
            raise JobStateError("outbox event is not publishable")
        row.status = OutboxEventStatus.PUBLISHED.value
        row.published_at = _as_utc(published_at or utc_now())
        row.dead_lettered_at = None
        row.last_error = None
        row.held_at = None
        row.hold_reason = None
        await self._session.flush()
        return row

    async def mark_failed(
        self,
        event: OutboxEvent | UUID,
        error: str | BaseException,
    ) -> OutboxEvent:
        row = await self._get_outbox(event)
        if row.status != OutboxEventStatus.PENDING.value:
            raise JobStateError("published outbox event cannot be failed")
        row.last_error = _bounded_error(error)
        await self._session.flush()
        return row

    async def materialize_pending_jobs(
        self,
        *,
        routes: Mapping[str, OutboxJobRoute],
        limit: int = 50,
        now: datetime | None = None,
    ) -> list[Job]:
        """Atomically turn pending intents into jobs and publish the intents.

        The caller owns the surrounding transaction. A crash before commit
        rolls back both the job insert and the outbox acknowledgement, so a
        pending intent can never disappear between those two durable facts.
        """

        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        if not routes:
            raise ValueError("outbox materialization requires an explicit route allowlist")
        await RecoveryStateRepository(self._session).require_ready(lock=True, shared_lock=True)
        jobs = JobRepository(self._session)
        rows = await self.claim_pending(limit=limit, now=now)
        materialized: list[Job] = []
        for row in rows:
            route = routes.get(row.event_type)
            if route is None:
                await self.mark_dead_letter(
                    row,
                    f"outbox event type is not allowlisted: {row.event_type}",
                    now=now,
                )
                continue
            try:
                payload = route.normalize_payload(row.payload)
            except ValueError as error:
                await self.mark_dead_letter(row, error, now=now)
                continue
            job = await jobs.enqueue(
                kind=route.job_kind,
                dedupe_key=f"outbox:{row.id}",
                payload=payload,
                tenant_id=row.tenant_id,
                max_attempts=route.max_attempts,
                external_side_effect=True,
            )
            await self.mark_published(row)
            materialized.append(job)
        return materialized

    async def mark_dead_letter(
        self,
        event: OutboxEvent | UUID,
        error: str | BaseException,
        *,
        now: datetime | None = None,
    ) -> OutboxEvent:
        """Terminally contain an unroutable intent without an external effect."""

        row = await self._get_outbox(event)
        if row.status == OutboxEventStatus.DEAD_LETTER.value:
            return row
        if row.status != OutboxEventStatus.PENDING.value:
            raise JobStateError("only pending outbox events may be dead-lettered")
        current_time = recovery_hold_timestamp(now)
        row.status = OutboxEventStatus.DEAD_LETTER.value
        row.dead_lettered_at = current_time
        row.last_error = _bounded_error(error)
        row.published_at = None
        row.held_at = None
        row.hold_reason = None
        await self._session.flush()
        return row

    async def materialize(self, **kwargs: Any) -> list[Job]:
        """Short alias for the atomic outbox-to-job materialization command."""

        return await self.materialize_pending_jobs(**kwargs)

    async def hold_for_restore(
        self,
        *,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> int:
        """Fence every not-yet-published outbox intent after a restore."""

        await RecoveryStateRepository(self._session).require_held(lock=True)
        normalized_reason = _required_text(
            reason or "database_restore_requires_reconciliation", "reason", 500
        )
        current_time = recovery_hold_timestamp(now)
        rows = list(
            (
                await self._session.scalars(
                    select(OutboxEvent).where(OutboxEvent.status == OutboxEventStatus.PENDING.value)
                )
            ).all()
        )
        for row in rows:
            row.status = OutboxEventStatus.HELD.value
            row.held_at = current_time
            row.hold_reason = normalized_reason
            row.published_at = None
            row.dead_lettered_at = None
            row.reconciled_at = None
            row.reconciled_by = None
            row.reconciliation_reason = None
            row.last_error = None
        await self._session.flush()
        return len(rows)

    async def reconcile_held(
        self,
        event_ids: Iterable[UUID],
        *,
        actor: ActorContext,
        reason: str,
        audit: AuditRepository | None = None,
        now: datetime | None = None,
    ) -> list[OutboxEvent]:
        """Release an explicit held set with mandatory same-UoW audit evidence."""

        if audit is None:
            raise ValueError("outbox reconciliation requires an audit repository")
        _require_same_transaction_audit(self._session, audit)
        self._require_recovery_permission(actor)
        requested_ids = tuple(dict.fromkeys(event_ids))
        if not requested_ids:
            raise ValueError("reconciliation requires an explicit non-empty outbox set")
        current_time = recovery_hold_timestamp(now)
        rows = list(
            (
                await self._session.scalars(
                    select(OutboxEvent).where(OutboxEvent.id.in_(requested_ids)).with_for_update()
                )
            ).all()
        )
        by_id = {row.id: row for row in rows}
        if any(event_id not in by_id for event_id in requested_ids):
            raise JobStateError("reconciliation named an outbox event that does not exist")
        ordered = [by_id[event_id] for event_id in requested_ids]
        for row in ordered:
            if row.status != OutboxEventStatus.HELD.value:
                raise JobStateError("only held outbox events may be reconciled")
            self._require_tenant_scope(row.tenant_id, actor)
        normalized_reason = SideEffectHoldPolicy.normalize_reconciliation_reason(reason)
        for row in ordered:
            self._audit_tenant(row.tenant_id)
            await audit.append_for_actor(
                actor,
                action="outbox.recovery_reconciled",
                resource_type="outbox_event",
                resource_id=row.id,
                payload={"hold_reason": row.hold_reason, "released_status": "pending"},
                reason=normalized_reason,
                now=current_time,
            )
            row.status = OutboxEventStatus.PENDING.value
            row.held_at = None
            row.hold_reason = None
            row.reconciled_at = current_time
            row.reconciled_by = actor.person_id
            row.reconciliation_reason = normalized_reason
        await self._session.flush()
        return ordered

    @staticmethod
    def _require_tenant_scope(tenant_id: UUID | None, actor: ActorContext) -> None:
        if tenant_id is None:
            if actor.tenant_id is not None:
                raise JobStateError("a tenant-scoped actor cannot reconcile a global operation")
            return
        actor.require_tenant(tenant_id)

    @staticmethod
    def _audit_tenant(tenant_id: UUID | None) -> UUID:
        if tenant_id is None:
            raise JobStateError("an attributable tenant is required for an operations audit event")
        return tenant_id

    @staticmethod
    def _require_recovery_permission(actor: ActorContext) -> None:
        actor.require_permission("recovery_reconcile")

    async def _get_outbox(self, event: OutboxEvent | UUID) -> OutboxEvent:
        row = (
            event if isinstance(event, OutboxEvent) else await self._session.get(OutboxEvent, event)
        )
        if row is None:
            raise JobStateError("outbox event does not exist")
        return row

    @staticmethod
    def _same_intent(existing: OutboxEvent, event: EventEnvelope) -> bool:
        return (
            existing.id == event.event_id
            and existing.tenant_id == event.tenant_id
            and existing.event_type == event.name
            and existing.aggregate_type == event.aggregate_type
            and existing.aggregate_id == event.aggregate_id
            and existing.payload == dict(event.payload)
            and _as_utc(existing.occurred_at) == _as_utc(event.occurred_at)
        )


class JobRepository:
    """Durable job state machine with lease ownership and bounded retries."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        retry_policy: RetryPolicy | None = None,
        hold_policy: SideEffectHoldPolicy | None = None,
    ) -> None:
        self._session = session
        self.retry_policy = retry_policy or RetryPolicy()
        self.hold_policy = hold_policy or SideEffectHoldPolicy()

    async def enqueue(
        self,
        *,
        kind: str,
        dedupe_key: str,
        payload: Mapping[str, Any],
        tenant_id: UUID | None = None,
        max_attempts: int | None = None,
        available_at: datetime | None = None,
        external_side_effect: bool = False,
        hold: bool | None = None,
        job_id: UUID | None = None,
    ) -> Job:
        """Insert one job, returning an equivalent existing job on replay."""

        normalized_kind = _required_text(kind, "kind", 128)
        normalized_key = _required_text(dedupe_key, "dedupe_key", 255)
        attempts = max_attempts if max_attempts is not None else self.retry_policy.max_attempts
        if not 1 <= attempts <= 25:
            raise ValueError("max_attempts must be between 1 and 25")
        if external_side_effect and hold is False:
            raise ValueError("external side-effect hold cannot be bypassed by a caller")
        existing = await self._session.scalar(select(Job).where(Job.dedupe_key == normalized_key))
        if existing is not None:
            if self._same_job(
                existing,
                normalized_kind,
                tenant_id,
                payload,
                attempts,
                external_side_effect,
            ):
                return existing
            raise DuplicateIntentError("dedupe key was reused for a different job intent")

        recovery_generation = 0
        if external_side_effect:
            recovery_state = await RecoveryStateRepository(self._session).get(
                lock=True,
                shared_lock=True,
            )
            if recovery_state is None:
                recovery_generation = 1
                should_hold = True
            else:
                recovery_generation = recovery_state.generation
                should_hold = hold is True or recovery_state.status != RecoveryStatus.READY.value
        else:
            should_hold = bool(hold) if hold is not None else False
        now = _as_utc(available_at or utc_now())
        values = {
            "id": job_id or uuid4(),
            "tenant_id": tenant_id,
            "kind": normalized_kind,
            "dedupe_key": normalized_key,
            "payload": dict(payload),
            "external_side_effect": external_side_effect,
            "recovery_generation": recovery_generation,
            "status": JobStatus.HELD.value if should_hold else JobStatus.QUEUED.value,
            "max_attempts": attempts,
            "available_at": now,
            "held_at": now if should_hold else None,
            "hold_reason": (
                f"recovery_generation_{recovery_generation}_held"
                if should_hold and external_side_effect
                else ("caller_requested_hold" if should_hold else None)
            ),
        }
        dialect = _dialect_name(self._session)
        if dialect in {"postgresql", "sqlite"}:
            result = cast(
                Any,
                await self._session.execute(
                    _on_conflict_insert(
                        table=Job,
                        values=values,
                        key_columns=[Job.dedupe_key],
                        dialect=dialect,
                    )
                ),
            )
            inserted_id = result.scalar_one_or_none()
            if inserted_id is None:
                existing = cast(
                    Job | None,
                    await self._session.scalar(select(Job).where(Job.dedupe_key == normalized_key)),
                )
                if existing is None:
                    raise RuntimeError("job conflict did not reload a canonical row")
                if not self._same_job(
                    existing,
                    normalized_kind,
                    tenant_id,
                    payload,
                    attempts,
                    external_side_effect,
                ):
                    raise DuplicateIntentError("dedupe key was reused for a different job intent")
                return existing
            canonical = cast(Job | None, await self._session.get(Job, inserted_id))
            if canonical is None:
                raise RuntimeError("job insert did not reload its canonical row")
            return canonical

        row = Job(**values)
        try:
            async with self._session.begin_nested():
                self._session.add(row)
                await self._session.flush()
        except IntegrityError as error:
            existing = cast(
                Job | None,
                await self._session.scalar(select(Job).where(Job.dedupe_key == normalized_key)),
            )
            if existing is None:
                raise
            if not self._same_job(
                existing,
                normalized_kind,
                tenant_id,
                payload,
                attempts,
                external_side_effect,
            ):
                raise DuplicateIntentError(
                    "dedupe key was reused for a different job intent"
                ) from error
            return existing
        return row

    async def enqueue_job(self, **kwargs: Any) -> Job:
        """Keyword-preserving alias for integrations that call this a command."""

        return await self.enqueue(**kwargs)

    async def claim(
        self,
        *,
        now: datetime | None = None,
        lease_for: timedelta = timedelta(minutes=5),
        limit: int = 1,
    ) -> list[Job]:
        """Claim eligible jobs and increment their durable attempt counters."""

        _lease_seconds(lease_for)
        if limit != 1:
            raise ValueError("durable workers must claim exactly one job per transaction")
        current_time = _as_utc(now or utc_now())
        recovery_state = await RecoveryStateRepository(self._session).require_ready(
            lock=True,
            shared_lock=True,
        )
        await self._session.execute(
            build_job_exhausted_statement(recovery_generation=recovery_state.generation)
        )
        rows = list(
            (
                await self._session.scalars(
                    build_job_claim_statement(
                        now=current_time,
                        recovery_generation=recovery_state.generation,
                        limit=limit,
                    )
                )
            ).all()
        )
        claimed: list[Job] = []
        dialect = _dialect_name(self._session) or "postgresql"
        for row in rows:
            token = uuid4()
            result = await self._session.execute(
                build_job_take_statement(
                    job_id=row.id,
                    lease_token=token,
                    lease_for=lease_for,
                    recovery_generation=recovery_state.generation,
                    dialect=dialect,
                )
            )
            rowcount = getattr(result, "rowcount", None)
            if isinstance(rowcount, int):
                if rowcount != 1:
                    continue
                await self._session.refresh(row)
            else:
                row.status = JobStatus.LEASED.value
                row.attempt_count += 1
                row.lease_token = token
                row.leased_until = current_time + lease_for
                row.held_at = None
                row.hold_reason = None
                row.dead_lettered_at = None
                row.last_error = None
                row.updated_at = current_time
                await self._session.flush()
            claimed.append(row)
        return claimed

    async def renew(
        self,
        job: Job | UUID,
        lease_token: UUID,
        *,
        lease_for: timedelta = timedelta(minutes=5),
        now: datetime | None = None,
    ) -> Job:
        _lease_seconds(lease_for)
        row = await self._get_job(job)
        recovery_state = await RecoveryStateRepository(self._session).require_ready(
            expected_generation=(row.recovery_generation if row.external_side_effect else None),
            lock=True,
            shared_lock=True,
        )
        result = await self._session.execute(
            build_job_renew_statement(
                job_id=row.id,
                lease_token=lease_token,
                lease_for=lease_for,
                recovery_generation=recovery_state.generation,
                dialect=_dialect_name(self._session) or "postgresql",
            )
        )
        rowcount = getattr(result, "rowcount", None)
        current_time = _as_utc(now or utc_now())
        if isinstance(rowcount, int):
            if rowcount != 1:
                await self._raise_fenced_lease_error(row, lease_token, now=current_time)
            await self._session.refresh(row)
            return row
        await self._require_lease(row, lease_token, now=current_time)
        row.leased_until = current_time + lease_for
        row.updated_at = current_time
        await self._session.flush()
        return row

    async def lock_for_dispatch(
        self,
        job: Job | UUID,
        lease_token: UUID,
        *,
        recovery_generation: int,
        provider_idempotency_key: str,
    ) -> Job:
        """Hold shared recovery and exclusive job locks across a bounded effect."""

        normalized_key = _required_text(
            provider_idempotency_key,
            "provider_idempotency_key",
            255,
        )
        await RecoveryStateRepository(self._session).require_ready(
            expected_generation=recovery_generation,
            lock=True,
            shared_lock=True,
        )
        job_id = job.id if isinstance(job, Job) else job
        row = cast(
            Job | None,
            await self._session.scalar(
                select(Job)
                .where(
                    Job.id == job_id,
                    Job.status == JobStatus.LEASED.value,
                    Job.lease_token == lease_token,
                    Job.leased_until > func.now(),
                    Job.external_side_effect.is_(True),
                    Job.recovery_generation == recovery_generation,
                    Job.provider_idempotency_key == normalized_key,
                    Job.dispatch_started_at.is_not(None),
                )
                .with_for_update()
            ),
        )
        if row is None:
            raise LeaseLostError("job dispatch was fenced by lease or recovery state")
        return row

    async def record_dispatch_started(
        self,
        job: Job | UUID,
        lease_token: UUID,
        *,
        provider_idempotency_key: str,
        recovery_generation: int,
        now: datetime | None = None,
    ) -> Job:
        """Persist pre-effect evidence under both lease and recovery fences."""

        row = await self._get_job(job)
        normalized_key = _required_text(
            provider_idempotency_key,
            "provider_idempotency_key",
            255,
        )
        result = await self._session.execute(
            build_job_dispatch_statement(
                job_id=row.id,
                lease_token=lease_token,
                recovery_generation=recovery_generation,
                provider_idempotency_key=normalized_key,
            )
        )
        rowcount = getattr(result, "rowcount", None)
        current_time = _as_utc(now or utc_now())
        if isinstance(rowcount, int):
            if rowcount != 1:
                await self._raise_fenced_lease_error(row, lease_token, now=current_time)
            await self._session.refresh(row)
        else:
            await RecoveryStateRepository(self._session).require_ready(
                expected_generation=recovery_generation,
                lock=True,
                shared_lock=True,
            )
            await self._require_lease(row, lease_token, now=current_time)
            row.provider_idempotency_key = normalized_key
            row.dispatch_started_at = current_time
            row.updated_at = current_time
            await self._session.flush()
        return row

    async def record_receipt(
        self,
        job: Job | UUID,
        lease_token: UUID,
        receipt: Mapping[str, Any],
        *,
        now: datetime | None = None,
    ) -> Job:
        """Persist canonical provider evidence even if acknowledgement later loses its lease."""

        row = await self._get_job(job)
        normalized_receipt = dict(receipt)
        receipt_key = normalized_receipt.get("idempotency_key")
        if not isinstance(receipt_key, str) or receipt_key != row.provider_idempotency_key:
            raise DuplicateIntentError(
                "provider receipt does not match the durable idempotency key"
            )
        receipt_digest = canonical_receipt_digest(normalized_receipt)
        if row.provider_receipt_digest is not None:
            if row.provider_receipt_digest != receipt_digest:
                raise DuplicateIntentError("provider returned conflicting receipt evidence")
            return row
        result = await self._session.execute(
            build_job_receipt_statement(
                job_id=row.id,
                lease_token=lease_token,
                receipt=normalized_receipt,
                receipt_digest=receipt_digest,
            )
        )
        rowcount = getattr(result, "rowcount", None)
        current_time = _as_utc(now or utc_now())
        if isinstance(rowcount, int) and rowcount == 1:
            await self._session.refresh(row)
            return row
        if not isinstance(rowcount, int):
            await self._require_lease(row, lease_token, now=current_time)
        locked = await self._get_job_for_update(row.id)
        if locked.provider_receipt_digest not in {None, receipt_digest}:
            raise DuplicateIntentError("provider returned conflicting receipt evidence")
        if locked.provider_idempotency_key != receipt_key:
            raise LeaseLostError("provider receipt does not match the durable dispatch intent")
        locked.provider_receipt = normalized_receipt
        locked.provider_receipt_digest = receipt_digest
        locked.receipt_recorded_at = current_time
        locked.updated_at = current_time
        await self._session.flush()
        return locked

    async def record_delivery_ambiguity(
        self,
        job: Job | UUID,
        *,
        lease_token: UUID,
        recovery_generation: int,
        provider_idempotency_key: str,
        error: str | BaseException,
        now: datetime | None = None,
    ) -> Job:
        """Record uncertainty only under the exact active effect lease."""

        row = await self._get_job(job)
        normalized_key = _required_text(
            provider_idempotency_key,
            "provider_idempotency_key",
            255,
        )
        normalized_error = _bounded_error(error)
        current_time = _as_utc(now or utc_now())
        result = await self._session.execute(
            build_job_ambiguity_statement(
                job_id=row.id,
                lease_token=lease_token,
                recovery_generation=recovery_generation,
                provider_idempotency_key=normalized_key,
                error=normalized_error,
            )
        )
        rowcount = getattr(result, "rowcount", None)
        if isinstance(rowcount, int):
            if rowcount != 1:
                await self._session.refresh(row)
                raise LeaseLostError(
                    "delivery ambiguity was fenced by lease, recovery, job state, or receipt"
                )
            await self._session.refresh(row)
            return row

        await self._require_lease(row, lease_token, now=current_time)
        if (
            not row.external_side_effect
            or row.recovery_generation != recovery_generation
            or row.provider_idempotency_key != normalized_key
            or row.dispatch_started_at is None
            or row.provider_receipt is not None
            or row.provider_receipt_digest is not None
            or row.receipt_recorded_at is not None
        ):
            raise LeaseLostError("delivery ambiguity does not match the current effect fence")
        await RecoveryStateRepository(self._session).require_ready(
            expected_generation=recovery_generation,
            lock=True,
            shared_lock=True,
        )
        row.delivery_ambiguous_at = current_time
        row.last_error = normalized_error
        row.updated_at = current_time
        await self._session.flush()
        return row

    async def record_ambiguous_evidence(
        self,
        job: Job | UUID,
        *,
        lease_token: UUID,
        recovery_generation: int,
        provider_idempotency_key: str,
        error: str | BaseException,
        now: datetime | None = None,
    ) -> Job:
        """Compatibility alias for the strictly fenced ambiguity operation."""

        return await self.record_delivery_ambiguity(
            job,
            lease_token=lease_token,
            recovery_generation=recovery_generation,
            provider_idempotency_key=provider_idempotency_key,
            error=error,
            now=now,
        )

    async def complete(
        self,
        job: Job | UUID,
        lease_token: UUID,
        *,
        now: datetime | None = None,
    ) -> Job:
        row = await self._get_job(job)
        if row.external_side_effect and row.provider_receipt is None:
            raise JobStateError("external job cannot succeed without durable provider receipt")
        result = await self._session.execute(
            build_job_acknowledge_statement(job_id=row.id, lease_token=lease_token)
        )
        rowcount = getattr(result, "rowcount", None)
        current_time = _as_utc(now or utc_now())
        if isinstance(rowcount, int):
            if rowcount != 1:
                await self._raise_fenced_lease_error(row, lease_token, now=current_time)
            await self._session.refresh(row)
            return row
        else:
            await self._require_lease(row, lease_token, now=current_time)
        row.status = JobStatus.SUCCEEDED.value
        row.leased_until = None
        row.lease_token = None
        row.last_error = None
        row.updated_at = current_time
        await self._session.flush()
        return row

    async def succeed(
        self,
        job: Job | UUID,
        lease_token: UUID,
        *,
        now: datetime | None = None,
    ) -> Job:
        """Alias for :meth:`complete`."""

        return await self.complete(job, lease_token, now=now)

    async def fail(
        self,
        job: Job | UUID,
        lease_token: UUID,
        error: str | BaseException,
        *,
        now: datetime | None = None,
        permanent: bool = False,
        ambiguous: bool = False,
    ) -> Job:
        row = await self._get_job(job)
        current_time = _as_utc(now or utc_now())
        dead_letter = permanent or row.attempt_count >= row.max_attempts
        retry_delay = (
            timedelta(0)
            if dead_letter
            else self.retry_policy.delay_for_attempt(
                row.attempt_count,
                jitter_key=row.id,
            )
        )
        sanitized_error = _bounded_error(error)
        result = await self._session.execute(
            build_job_failure_statement(
                job_id=row.id,
                lease_token=lease_token,
                dead_letter=dead_letter,
                retry_delay=retry_delay,
                last_error=sanitized_error,
                ambiguous=ambiguous,
                dialect=_dialect_name(self._session) or "postgresql",
            )
        )
        rowcount = getattr(result, "rowcount", None)
        if isinstance(rowcount, int):
            if rowcount != 1:
                await self._raise_fenced_lease_error(row, lease_token, now=current_time)
            await self._session.refresh(row)
            return row
        else:
            await self._require_lease(row, lease_token, now=current_time)
        row.last_error = sanitized_error
        row.leased_until = None
        row.lease_token = None
        if dead_letter:
            row.status = JobStatus.DEAD_LETTER.value
            row.dead_lettered_at = current_time
            row.available_at = current_time
        else:
            row.status = JobStatus.RETRY_WAIT.value
            row.dead_lettered_at = None
            row.available_at = current_time + retry_delay
        if ambiguous:
            row.delivery_ambiguous_at = current_time
        row.updated_at = current_time
        await self._session.flush()
        return row

    async def retry(
        self,
        job: Job | UUID,
        *,
        actor: ActorContext,
        reason: str,
        now: datetime | None = None,
        audit: AuditRepository | None = None,
    ) -> Job:
        """Authorize and requeue one dead-letter job for a fresh bounded run."""

        if audit is None:
            raise ValueError("job retry requires an audit repository")
        _require_same_transaction_audit(self._session, audit)
        actor.require_permission("job_retry")
        normalized_reason = self.hold_policy.normalize_reconciliation_reason(reason)
        row = await self._get_job_for_update(job)
        self._require_tenant_scope(row, actor)
        if row.status != JobStatus.DEAD_LETTER.value:
            raise RetryNotAllowedError("only dead-letter jobs may be manually retried")
        previous_status = row.status
        current_time = _as_utc(now or utc_now())
        recovery_state = await RecoveryStateRepository(self._session).get(
            lock=True,
            shared_lock=True,
        )
        should_hold = row.external_side_effect and (
            recovery_state is None or recovery_state.status != RecoveryStatus.READY.value
        )
        row.status = JobStatus.HELD.value if should_hold else JobStatus.QUEUED.value
        row.attempt_count = 0
        row.available_at = current_time
        row.leased_until = None
        row.lease_token = None
        row.dead_lettered_at = None
        row.last_error = None
        row.held_at = current_time if should_hold else None
        row.hold_reason = "recovery_generation_held" if should_hold else None
        if row.external_side_effect:
            row.recovery_generation = recovery_state.generation if recovery_state is not None else 1
        row.updated_at = current_time
        self._audit_tenant(row)
        await audit.append_for_actor(
            actor,
            action="job.retry",
            resource_type="job",
            resource_id=row.id,
            payload={"previous_status": previous_status, "dedupe_key": row.dedupe_key},
            reason=normalized_reason,
            now=current_time,
        )
        await self._session.flush()
        return row

    async def hold_for_restore(
        self,
        *,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> int:
        """Move every non-terminal job to held and clear stale leases."""

        await RecoveryStateRepository(self._session).require_held(lock=True)
        normalized_reason = _required_text(reason or self.hold_policy.restore_reason, "reason", 500)
        current_time = recovery_hold_timestamp(now)
        rows = list(
            (
                await self._session.scalars(
                    select(Job).where(
                        Job.external_side_effect.is_(True),
                        Job.status.not_in((JobStatus.SUCCEEDED.value, JobStatus.DEAD_LETTER.value)),
                    )
                )
            ).all()
        )
        for row in rows:
            row.status = JobStatus.HELD.value
            row.held_at = current_time
            row.hold_reason = normalized_reason
            row.leased_until = None
            row.lease_token = None
            row.dead_lettered_at = None
            row.reconciled_at = None
            row.reconciled_by = None
            row.reconciliation_reason = None
            row.updated_at = current_time
        await self._session.flush()
        return len(rows)

    async def mark_restored(
        self,
        *,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> int:
        """Alias emphasizing that restore handling is a durable state change."""

        return await self.hold_for_restore(reason=reason, now=now)

    async def reconcile_held(
        self,
        job_ids: Iterable[UUID],
        *,
        actor: ActorContext,
        reason: str,
        now: datetime | None = None,
        audit: AuditRepository | None = None,
    ) -> list[Job]:
        """Release exactly the explicit held set after named-operations review."""

        if audit is None:
            raise ValueError("job reconciliation requires an audit repository")
        _require_same_transaction_audit(self._session, audit)
        self.hold_policy.require_reconciliation(actor)
        normalized_reason = self.hold_policy.normalize_reconciliation_reason(reason)
        requested_ids = tuple(dict.fromkeys(job_ids))
        if not requested_ids:
            raise ValueError("reconciliation requires an explicit non-empty job set")
        current_time = recovery_hold_timestamp(now)
        recovery_state = await RecoveryStateRepository(self._session).get(lock=True)
        if recovery_state is None:
            raise ReconciliationRequiredError("durable recovery state is missing")
        rows = list(
            (
                await self._session.scalars(
                    select(Job).where(Job.id.in_(requested_ids)).with_for_update()
                )
            ).all()
        )
        by_id = {row.id: row for row in rows}
        missing = [job_id for job_id in requested_ids if job_id not in by_id]
        if missing:
            raise JobStateError("reconciliation named a job that does not exist")
        ordered = [by_id[job_id] for job_id in requested_ids]
        for row in ordered:
            if row.status != JobStatus.HELD.value:
                raise JobStateError("only held jobs may be reconciled")
            self._require_tenant_scope(row, actor)
        for row in ordered:
            hold_reason = row.hold_reason
            row.status = JobStatus.QUEUED.value
            row.held_at = None
            row.hold_reason = None
            row.leased_until = None
            row.lease_token = None
            row.reconciled_at = current_time
            row.reconciled_by = recovery_actor_id(actor)
            row.reconciliation_reason = normalized_reason
            if row.external_side_effect:
                row.recovery_generation = recovery_state.generation
            row.available_at = current_time
            row.updated_at = current_time
            self._audit_tenant(row)
            await audit.append_for_actor(
                actor,
                action="job.recovery_reconciled",
                resource_type="job",
                resource_id=row.id,
                payload={"hold_reason": hold_reason, "released_status": "queued"},
                reason=normalized_reason,
                now=current_time,
            )
        await self._session.flush()
        return ordered

    async def restore_and_hold_external_side_effects(
        self,
        *,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> int:
        """Long-form alias used by recovery runbooks."""

        return await self.hold_for_restore(reason=reason, now=now)

    async def _require_lease(
        self,
        job: Job | UUID,
        lease_token: UUID,
        *,
        now: datetime | None,
    ) -> Job:
        row = await self._get_job(job)
        current_time = _as_utc(now or utc_now())
        if row.status != JobStatus.LEASED.value:
            if row.status == JobStatus.HELD.value:
                raise ReconciliationRequiredError("held job cannot be acknowledged by a worker")
            raise LeaseLostError("job is not currently leased")
        if row.lease_token != lease_token or row.leased_until is None:
            raise LeaseLostError("worker lease token is not current")
        if _as_utc(row.leased_until) <= current_time:
            raise LeaseLostError("worker lease has expired")
        return row

    async def _raise_fenced_lease_error(
        self,
        row: Job,
        lease_token: UUID,
        *,
        now: datetime,
    ) -> None:
        """Preserve the held-vs-lost distinction after a zero-row UPDATE."""

        await self._session.refresh(row)
        await self._require_lease(row, lease_token, now=now)
        raise LeaseLostError("job lease acknowledgement was fenced by a concurrent update")

    async def _get_job(self, job: Job | UUID) -> Job:
        row = job if isinstance(job, Job) else await self._session.get(Job, job)
        if row is None:
            raise JobStateError("job does not exist")
        return row

    async def _get_job_for_update(self, job: Job | UUID) -> Job:
        job_id = job.id if isinstance(job, Job) else job
        row = await self._session.scalar(
            select(Job)
            .where(Job.id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise JobStateError("job does not exist")
        return row

    @staticmethod
    def _same_job(
        existing: Job,
        kind: str,
        tenant_id: UUID | None,
        payload: Mapping[str, Any],
        max_attempts: int,
        external_side_effect: bool,
    ) -> bool:
        return (
            existing.kind == kind
            and existing.tenant_id == tenant_id
            and existing.payload == dict(payload)
            and existing.max_attempts == max_attempts
            and existing.external_side_effect is external_side_effect
        )

    @staticmethod
    def _normalize_reason(reason: str) -> str:
        return SideEffectHoldPolicy.normalize_reconciliation_reason(reason)

    @staticmethod
    def _require_tenant_scope(row: Job, actor: ActorContext) -> None:
        if row.tenant_id is None:
            if actor.tenant_id is not None:
                raise JobStateError("a tenant-scoped actor cannot reconcile a global job")
            return
        actor.require_tenant(row.tenant_id)

    @staticmethod
    def _require_tenant_scope_value(tenant_id: UUID | None, actor: ActorContext) -> None:
        if tenant_id is None:
            if actor.tenant_id is not None:
                raise JobStateError("a tenant-scoped actor cannot reconcile a global operation")
            return
        actor.require_tenant(tenant_id)

    @staticmethod
    def _audit_tenant(row: Job) -> UUID:
        if row.tenant_id is None:
            raise JobStateError("an attributable tenant is required for a job audit event")
        return row.tenant_id

    @staticmethod
    def _audit_tenant_value(tenant_id: UUID | None) -> UUID:
        if tenant_id is None:
            raise JobStateError("an attributable tenant is required for an operations audit event")
        return tenant_id

    @staticmethod
    def _require_recovery_permission(actor: ActorContext) -> None:
        actor.require_permission("recovery_reconcile")


async def reconcile_operations(
    session: AsyncSession,
    *,
    outbox_event_ids: Iterable[UUID] = (),
    job_ids: Iterable[UUID] = (),
    actor: ActorContext,
    reason: str,
    now: datetime | None = None,
) -> tuple[list[OutboxEvent], list[Job]]:
    """Reconcile explicit outbox and job holds in one caller-owned transaction."""

    event_ids = tuple(dict.fromkeys(outbox_event_ids))
    requested_job_ids = tuple(dict.fromkeys(job_ids))
    if not event_ids and not requested_job_ids:
        raise ValueError("reconciliation requires an explicit non-empty operations set")
    audit = AuditRepository(session)
    events: list[OutboxEvent] = []
    jobs: list[Job] = []
    if event_ids:
        events = await OutboxRepository(session).reconcile_held(
            event_ids,
            actor=actor,
            reason=reason,
            audit=audit,
            now=now,
        )
    if requested_job_ids:
        jobs = await JobRepository(session).reconcile_held(
            requested_job_ids,
            actor=actor,
            reason=reason,
            audit=audit,
            now=now,
        )
    held_outbox = cast(
        int | None,
        await session.scalar(
            select(func.count(OutboxEvent.id)).where(
                OutboxEvent.status == OutboxEventStatus.HELD.value
            )
        ),
    )
    held_jobs = cast(
        int | None,
        await session.scalar(
            select(func.count(Job.id)).where(
                Job.status == JobStatus.HELD.value,
                Job.external_side_effect.is_(True),
            )
        ),
    )
    if not int(held_outbox or 0) and not int(held_jobs or 0):
        await RecoveryStateRepository(session).reconcile(
            actor=actor,
            reason=reason,
            audit=audit,
            now=now,
        )
    return events, jobs


async def mark_database_restore(
    session: AsyncSession,
    *,
    reason: str = "database_restore_requires_reconciliation",
    now: datetime | None = None,
) -> tuple[OperationsRecoveryState, int, int]:
    """Advance the global generation and hold all uncertain work atomically."""

    state = await RecoveryStateRepository(session).mark_restore(reason=reason, now=now)
    held_outbox = await OutboxRepository(session).hold_for_restore(reason=reason, now=now)
    held_jobs = await JobRepository(session).hold_for_restore(reason=reason, now=now)
    return state, held_outbox, held_jobs


async def reconcile_recovery_state(
    session: AsyncSession,
    *,
    actor: ActorContext,
    reason: str,
    now: datetime | None = None,
) -> OperationsRecoveryState:
    """Audit and release a generation only after no held external work remains."""

    return await RecoveryStateRepository(session).reconcile(
        actor=actor,
        reason=reason,
        audit=AuditRepository(session),
        now=now,
    )


__all__ = [
    "DuplicateIntentError",
    "JobRepository",
    "JobStateError",
    "LeaseLostError",
    "MAX_JOB_LEASE",
    "OutboxJobRoute",
    "OutboxRepository",
    "RecoveryStateRepository",
    "build_job_acknowledge_statement",
    "build_job_dispatch_statement",
    "build_job_exhausted_statement",
    "build_job_failure_statement",
    "build_job_receipt_statement",
    "build_job_renew_statement",
    "build_job_take_statement",
    "canonical_receipt_digest",
    "mark_database_restore",
    "reconcile_operations",
    "reconcile_recovery_state",
    "RetryNotAllowedError",
    "RetryPolicy",
    "build_job_claim_statement",
]
