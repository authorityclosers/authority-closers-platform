from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.service import AuditRepository
from ac_platform.kernel.authz import ActorContext
from ac_platform.kernel.errors import AuthorizationDenied
from ac_platform.kernel.events import EventCategory, EventEnvelope
from ac_platform.outbox.models import (
    Job,
    JobStatus,
    OperationsRecoveryState,
    OutboxEvent,
    OutboxEventStatus,
    RecoveryStatus,
)
from ac_platform.outbox.policy import ReconciliationRequiredError
from ac_platform.outbox.repository import (
    EXPIRED_DISPATCH_AMBIGUITY_REASON,
    DuplicateIntentError,
    JobRepository,
    LeaseLostError,
    OutboxJobRoute,
    OutboxRepository,
    RecoveryStateRepository,
    RetryPolicy,
    build_job_acknowledge_statement,
    build_job_ambiguity_statement,
    build_job_claim_statement,
    build_job_dispatch_statement,
    build_job_expired_dispatch_quarantine_statement,
    build_job_failure_statement,
    build_job_receipt_statement,
    build_job_renew_statement,
    build_job_take_statement,
    canonical_receipt_digest,
    mark_database_restore,
)


class _Rows:
    def __init__(self, rows: list[Job] | list[OutboxEvent]) -> None:
        self._rows = rows

    def all(self) -> list[Job] | list[OutboxEvent]:
        return self._rows


class _Savepoint:
    async def __aenter__(self) -> _Savepoint:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


def _session() -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.add = Mock()
    session.begin_nested = Mock(return_value=_Savepoint())
    return session


def _state(
    status: str = RecoveryStatus.READY.value, generation: int = 3
) -> OperationsRecoveryState:
    now = datetime(2026, 8, 30, 12, tzinfo=UTC)
    return OperationsRecoveryState(
        id=1,
        generation=generation,
        status=status,
        marked_at=now,
        hold_reason="restore review",
        reconciled_at=now if status == RecoveryStatus.READY.value else None,
        reconciled_by=uuid4() if status == RecoveryStatus.READY.value else None,
        reconciliation_reason="approved" if status == RecoveryStatus.READY.value else None,
        updated_at=now,
    )


def _job(
    *,
    status: str = JobStatus.QUEUED.value,
    max_attempts: int = 3,
    generation: int = 3,
) -> Job:
    now = datetime(2026, 8, 30, 12, tzinfo=UTC)
    leased = status == JobStatus.LEASED.value
    held = status == JobStatus.HELD.value
    dead = status == JobStatus.DEAD_LETTER.value
    return Job(
        id=uuid4(),
        tenant_id=uuid4(),
        kind="email.enrollment_welcome.v1",
        dedupe_key=f"outbox:{uuid4()}",
        payload=_welcome_payload(),
        external_side_effect=True,
        recovery_generation=generation,
        status=status,
        attempt_count=1 if leased else 0,
        max_attempts=max_attempts,
        available_at=now,
        leased_until=now + timedelta(minutes=1) if leased else None,
        lease_token=uuid4() if leased else None,
        held_at=now if held else None,
        hold_reason="restore review" if held else None,
        dead_lettered_at=now if dead else None,
        created_at=now,
        updated_at=now,
    )


def _welcome_payload() -> dict[str, str]:
    return {
        "enrollment_id": str(uuid4()),
        "entitlement_id": str(uuid4()),
        "provenance_id": str(uuid4()),
        "person_id": str(uuid4()),
        "program_version_id": str(uuid4()),
        "source": "free_self",
    }


def _route() -> OutboxJobRoute:
    payload = _welcome_payload()
    return OutboxJobRoute(
        job_kind="email.enrollment_welcome.v1",
        required_payload_keys=frozenset(payload),
        uuid_payload_keys=frozenset(set(payload) - {"source"}),
        allowed_payload_values={"source": frozenset({"free_self", "manual_grant"})},
    )


async def test_outbox_dedupe_returns_canonical_intent_and_rejects_conflict() -> None:
    session = _session()
    event = EventEnvelope(
        name="enrollment.created.v1",
        category=EventCategory.DOMAIN_FACT,
        aggregate_type="enrollment",
        aggregate_id=uuid4(),
        tenant_id=uuid4(),
        payload={"source": "free"},
    )
    session.scalar.side_effect = [None, None]
    repository = OutboxRepository(session)
    first = await repository.enqueue(event, dedupe_key="enrollment:1")

    session.scalar.side_effect = [first]
    assert await repository.enqueue(event, dedupe_key="enrollment:1") is first

    conflict = EventEnvelope(
        name=event.name,
        category=event.category,
        aggregate_type=event.aggregate_type,
        aggregate_id=event.aggregate_id,
        tenant_id=event.tenant_id,
        payload={"source": "different"},
    )
    session.scalar.side_effect = [first]
    with pytest.raises(DuplicateIntentError):
        await repository.enqueue(conflict, dedupe_key="enrollment:1")


async def test_savepoint_dedupe_reload_preserves_the_outer_outbox_transaction() -> None:
    session = _session()
    event = EventEnvelope(
        name="enrollment.created.v1",
        category=EventCategory.DOMAIN_FACT,
        aggregate_type="enrollment",
        aggregate_id=uuid4(),
        tenant_id=uuid4(),
        payload={"source": "free_self"},
    )
    canonical = OutboxEvent(
        id=event.event_id,
        tenant_id=event.tenant_id,
        event_type=event.name,
        aggregate_type=event.aggregate_type,
        aggregate_id=event.aggregate_id,
        dedupe_key="savepoint:event",
        payload=dict(event.payload),
        occurred_at=event.occurred_at,
    )
    session.scalar.side_effect = [None, canonical]
    session.flush.side_effect = IntegrityError("duplicate", {}, Exception("duplicate"))

    reloaded = await OutboxRepository(session).enqueue(event, dedupe_key="savepoint:event")

    assert reloaded is canonical
    session.begin_nested.assert_called_once()


async def test_savepoint_dedupe_reload_preserves_the_outer_job_transaction() -> None:
    session = _session()
    canonical = Job(
        id=uuid4(),
        kind="internal.test.v1",
        dedupe_key="savepoint:job",
        payload={"value": 1},
        external_side_effect=False,
        recovery_generation=0,
        status=JobStatus.QUEUED.value,
        max_attempts=5,
    )
    session.scalar.side_effect = [None, canonical]
    session.flush.side_effect = IntegrityError("duplicate", {}, Exception("duplicate"))

    reloaded = await JobRepository(session).enqueue(
        kind=canonical.kind,
        dedupe_key=canonical.dedupe_key,
        payload=canonical.payload,
    )

    assert reloaded is canonical
    session.begin_nested.assert_called_once()


async def test_audit_intent_cannot_cross_the_outbox_boundary() -> None:
    event = EventEnvelope(
        name="audit.job.retry.v1",
        category=EventCategory.AUDIT,
        aggregate_type="job",
        aggregate_id=uuid4(),
        tenant_id=uuid4(),
        payload={"reason": "operator"},
    )
    with pytest.raises(ValueError, match="audit store"):
        await OutboxRepository(_session()).enqueue(event)


async def test_allowlisted_welcome_materialization_contains_no_recipient() -> None:
    session = _session()
    state = _state()
    payload = _welcome_payload()
    event = OutboxEvent(
        id=uuid4(),
        tenant_id=uuid4(),
        event_type="enrollment.welcome.requested.v1",
        aggregate_type="enrollment",
        aggregate_id=uuid4(),
        dedupe_key="welcome:1",
        payload=payload,
        status=OutboxEventStatus.PENDING.value,
        occurred_at=datetime(2026, 8, 30, 12, tzinfo=UTC),
        created_at=datetime(2026, 8, 30, 12, tzinfo=UTC),
    )
    session.scalar.side_effect = [state, None, state]
    session.scalars.return_value = _Rows([event])

    jobs = await OutboxRepository(session).materialize_pending_jobs(
        routes={event.event_type: _route()}
    )

    assert len(jobs) == 1
    assert jobs[0].kind == "email.enrollment_welcome.v1"
    assert jobs[0].payload == payload
    assert "to" not in jobs[0].payload
    assert "email" not in jobs[0].payload
    assert event.status == OutboxEventStatus.PUBLISHED.value


@pytest.mark.parametrize(
    "event_type,payload_mutation",
    [
        ("unknown.event.v1", {}),
        ("enrollment.welcome.requested.v1", {"to": "attacker@example.test"}),
        ("enrollment.welcome.requested.v1", {"source": "unapproved"}),
    ],
)
async def test_unknown_or_schema_drifted_outbox_events_dead_letter_without_job(
    event_type: str,
    payload_mutation: dict[str, str],
) -> None:
    session = _session()
    payload = _welcome_payload() | payload_mutation
    event = OutboxEvent(
        id=uuid4(),
        tenant_id=uuid4(),
        event_type=event_type,
        aggregate_type="enrollment",
        aggregate_id=uuid4(),
        dedupe_key=f"event:{uuid4()}",
        payload=payload,
        status=OutboxEventStatus.PENDING.value,
        occurred_at=datetime(2026, 8, 30, 12, tzinfo=UTC),
        created_at=datetime(2026, 8, 30, 12, tzinfo=UTC),
    )
    session.scalar.return_value = _state()
    session.scalars.return_value = _Rows([event])

    jobs = await OutboxRepository(session).materialize_pending_jobs(
        routes={"enrollment.welcome.requested.v1": _route()}
    )

    assert jobs == []
    assert event.status == OutboxEventStatus.DEAD_LETTER.value
    assert event.dead_lettered_at is not None
    assert event.published_at is None


async def test_non_object_outbox_payload_is_contained_without_aborting_materialization() -> None:
    session = _session()
    event = OutboxEvent(
        id=uuid4(),
        tenant_id=uuid4(),
        event_type="enrollment.welcome.requested.v1",
        aggregate_type="enrollment",
        aggregate_id=uuid4(),
        dedupe_key=f"event:{uuid4()}",
        payload=[],  # type: ignore[arg-type]
        status=OutboxEventStatus.PENDING.value,
        occurred_at=datetime(2026, 8, 30, 12, tzinfo=UTC),
        created_at=datetime(2026, 8, 30, 12, tzinfo=UTC),
    )
    session.scalar.return_value = _state()
    session.scalars.return_value = _Rows([event])

    jobs = await OutboxRepository(session).materialize_pending_jobs(
        routes={"enrollment.welcome.requested.v1": _route()}
    )

    assert jobs == []
    assert event.status == OutboxEventStatus.DEAD_LETTER.value


def test_job_claim_and_dispatch_fences_compile_for_postgresql() -> None:
    job_id = uuid4()
    token = uuid4()
    statements = (
        build_job_claim_statement(
            now=datetime(2026, 8, 30, 12, tzinfo=UTC),
            recovery_generation=3,
            limit=1,
        ),
        build_job_take_statement(
            job_id=job_id,
            lease_token=token,
            lease_for=timedelta(seconds=30),
            recovery_generation=3,
        ),
        build_job_renew_statement(
            job_id=job_id,
            lease_token=token,
            lease_for=timedelta(seconds=40),
            recovery_generation=3,
        ),
        build_job_dispatch_statement(
            job_id=job_id,
            lease_token=token,
            recovery_generation=3,
            provider_idempotency_key="outbox:1",
        ),
        build_job_acknowledge_statement(job_id=job_id, lease_token=token),
        build_job_ambiguity_statement(
            job_id=job_id,
            lease_token=token,
            recovery_generation=3,
            provider_idempotency_key="outbox:1",
            error="provider timeout",
        ),
        build_job_failure_statement(
            job_id=job_id,
            lease_token=token,
            dead_letter=False,
            retry_delay=timedelta(seconds=5),
            last_error="safe",
            ambiguous=True,
        ),
        build_job_receipt_statement(
            job_id=job_id,
            lease_token=token,
            receipt={"accepted": True},
            receipt_digest="a" * 64,
        ),
    )
    sql = [str(statement.compile(dialect=postgresql.dialect())) for statement in statements]
    assert "FOR UPDATE SKIP LOCKED" in sql[0]
    assert all("now()" in statement.lower() for statement in sql[1:])
    assert all("operations_recovery_state" in sql[index] for index in (0, 1, 2, 3, 5))
    assert "provider_receipt IS NULL" in sql[5]
    assert "lease_token" in sql[5]


def test_job_claim_kind_filter_applies_to_select_and_take() -> None:
    job_id = uuid4()
    allowed = ("email.enrollment_welcome.v1", "email.password_reset.v1")
    claim_sql = str(
        build_job_claim_statement(
            now=datetime(2026, 8, 30, 12, tzinfo=UTC),
            recovery_generation=3,
            kinds=allowed,
        ).compile(dialect=postgresql.dialect())
    )
    take_sql = str(
        build_job_take_statement(
            job_id=job_id,
            lease_token=uuid4(),
            lease_for=timedelta(seconds=30),
            recovery_generation=3,
            kinds=allowed,
        ).compile(dialect=postgresql.dialect())
    )

    assert "jobs.kind IN" in claim_sql
    assert "jobs.kind IN" in take_sql


@pytest.mark.parametrize(
    "kinds",
    [(), ("",), ("   ",), ("x" * 129,)],
)
def test_job_claim_kind_filter_rejects_empty_or_invalid_allowlists(
    kinds: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError):
        build_job_claim_statement(
            now=datetime(2026, 8, 30, 12, tzinfo=UTC),
            recovery_generation=3,
            kinds=kinds,
        )


def test_job_claim_kind_filter_rejects_oversized_allowlists() -> None:
    with pytest.raises(ValueError, match="at most"):
        build_job_take_statement(
            job_id=uuid4(),
            lease_token=uuid4(),
            lease_for=timedelta(seconds=30),
            recovery_generation=3,
            kinds=tuple(f"internal.test.{index}" for index in range(65)),
        )


@pytest.mark.parametrize("kinds", ["email.example.v1", (1,)])
def test_job_claim_kind_filter_rejects_bare_strings_and_non_strings(kinds: object) -> None:
    with pytest.raises(ValueError):
        build_job_claim_statement(
            now=datetime(2026, 8, 30, 12, tzinfo=UTC),
            recovery_generation=3,
            kinds=kinds,  # type: ignore[arg-type]
        )


def test_expired_external_dispatch_is_excluded_and_quarantined_by_sql_contract() -> None:
    job_id = uuid4()
    claim_sql = str(
        build_job_claim_statement(
            now=datetime(2026, 8, 30, 12, tzinfo=UTC),
            recovery_generation=3,
            limit=1,
        ).compile(dialect=postgresql.dialect())
    )
    take_sql = str(
        build_job_take_statement(
            job_id=job_id,
            lease_token=uuid4(),
            lease_for=timedelta(seconds=30),
            recovery_generation=3,
        ).compile(dialect=postgresql.dialect())
    )
    quarantine_sql = str(
        build_job_expired_dispatch_quarantine_statement().compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    safe_reclaim_predicate = (
        "jobs.external_side_effect IS false OR jobs.dispatch_started_at IS NULL "
        "OR jobs.provider_receipt IS NOT NULL"
    )
    assert safe_reclaim_predicate in claim_sql
    assert safe_reclaim_predicate in take_sql
    assert "jobs.external_side_effect IS true" in quarantine_sql
    assert "jobs.dispatch_started_at IS NOT NULL" in quarantine_sql
    assert "jobs.provider_receipt IS NULL" in quarantine_sql
    assert "jobs.leased_until <= now()" in quarantine_sql
    assert "delivery_ambiguous_at=coalesce(jobs.delivery_ambiguous_at, now())" in quarantine_sql
    assert EXPIRED_DISPATCH_AMBIGUITY_REASON in quarantine_sql
    assert len(EXPIRED_DISPATCH_AMBIGUITY_REASON) <= 500

    safe_retry_sql = str(
        build_job_failure_statement(
            job_id=job_id,
            lease_token=uuid4(),
            dead_letter=False,
            retry_delay=timedelta(seconds=5),
            last_error="explicit retryable response",
            ambiguous=False,
        ).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "provider_idempotency_key=NULL" in safe_retry_sql
    assert "dispatch_started_at=NULL" in safe_retry_sql


async def test_external_job_enqueue_cannot_bypass_durable_hold() -> None:
    session = _session()
    session.scalar.side_effect = [None]
    with pytest.raises(ValueError, match="cannot be bypassed"):
        await JobRepository(session).enqueue(
            kind="email.enrollment_welcome.v1",
            dedupe_key="job:1",
            payload=_welcome_payload(),
            external_side_effect=True,
            hold=False,
        )

    session.scalar.side_effect = [None, _state(RecoveryStatus.HELD.value)]
    held = await JobRepository(session).enqueue(
        kind="email.enrollment_welcome.v1",
        dedupe_key="job:2",
        payload=_welcome_payload(),
        external_side_effect=True,
    )
    assert held.status == JobStatus.HELD.value
    assert held.recovery_generation == 3


async def test_claim_is_one_at_a_time_and_requires_ready_generation() -> None:
    session = _session()
    repository = JobRepository(session)
    with pytest.raises(ValueError, match="exactly one"):
        await repository.claim(limit=2)

    session.scalar.return_value = _state(RecoveryStatus.HELD.value)
    with pytest.raises(ReconciliationRequiredError):
        await repository.claim(limit=1)


async def test_restore_row_holds_cannot_run_before_the_global_marker_is_held() -> None:
    session = _session()
    session.scalar.return_value = _state(RecoveryStatus.READY.value)

    with pytest.raises(ReconciliationRequiredError, match="held first"):
        await OutboxRepository(session).hold_for_restore()
    with pytest.raises(ReconciliationRequiredError, match="held first"):
        await JobRepository(session).hold_for_restore()


async def test_fenced_acknowledgement_rejects_zero_row_update() -> None:
    session = _session()
    job = _job(status=JobStatus.LEASED.value)
    job.external_side_effect = False
    job.recovery_generation = 0
    session.execute.return_value = Mock(rowcount=0)

    with pytest.raises(LeaseLostError):
        await JobRepository(session).complete(
            job,
            job.lease_token or uuid4(),
            now=datetime(2026, 8, 30, 12, tzinfo=UTC),
        )


def test_retry_jitter_and_receipt_digest_are_deterministic_and_bounded() -> None:
    policy = RetryPolicy(base_delay=timedelta(seconds=10), max_delay=timedelta(minutes=1))
    key = uuid4()
    first = policy.delay_for_attempt(2, jitter_key=key)
    second = policy.delay_for_attempt(2, jitter_key=key)
    assert first == second
    assert timedelta(seconds=20) <= first <= timedelta(seconds=25)
    assert canonical_receipt_digest({"accepted": True, "id": "one"}) == canonical_receipt_digest(
        {"id": "one", "accepted": True}
    )


async def test_restore_generation_holds_pending_outbox_and_external_jobs_atomically() -> None:
    session = _session()
    state = _state()
    event = OutboxEvent(
        id=uuid4(),
        tenant_id=uuid4(),
        event_type="enrollment.welcome.requested.v1",
        aggregate_type="enrollment",
        aggregate_id=uuid4(),
        dedupe_key="restore:event",
        payload=_welcome_payload(),
        status=OutboxEventStatus.PENDING.value,
        occurred_at=datetime(2026, 8, 30, 12, tzinfo=UTC),
        created_at=datetime(2026, 8, 30, 12, tzinfo=UTC),
    )
    job = _job()
    session.scalar.return_value = state
    session.scalars.side_effect = [_Rows([event]), _Rows([job])]

    updated, held_outbox, held_jobs = await mark_database_restore(session)

    assert updated.generation == 4
    assert updated.status == RecoveryStatus.HELD.value
    assert held_outbox == held_jobs == 1
    assert event.status == OutboxEventStatus.HELD.value
    assert job.status == JobStatus.HELD.value
    assert job.lease_token is None


async def test_recovery_generation_release_requires_empty_holds_and_same_uow_audit() -> None:
    session = _session()
    state = _state(RecoveryStatus.HELD.value)
    session.scalar.side_effect = [state, 0, 0]
    audit = AuditRepository(session)
    audit.append_for_actor = AsyncMock()  # type: ignore[method-assign]
    operations_tenant_id = uuid4()
    actor = ActorContext(
        person_id=uuid4(),
        session_id=uuid4(),
        tenant_id=operations_tenant_id,
        permissions=frozenset({"recovery_reconcile", "global_recovery_reconcile"}),
    )

    released = await RecoveryStateRepository(session).reconcile(
        actor=actor,
        reason="all provider state verified",
        audit=audit,
        now=datetime(2026, 8, 30, 12, 1, tzinfo=UTC),
        operations_tenant_id=operations_tenant_id,
    )

    assert released.status == RecoveryStatus.READY.value
    assert released.reconciled_by == actor.person_id
    audit.append_for_actor.assert_awaited_once()  # type: ignore[attr-defined]


async def test_recovery_reconciliation_rejects_audit_from_another_transaction() -> None:
    session = _session()
    other_session = _session()
    operations_tenant_id = uuid4()
    actor = ActorContext(
        person_id=uuid4(),
        session_id=uuid4(),
        tenant_id=operations_tenant_id,
        permissions=frozenset({"recovery_reconcile", "global_recovery_reconcile"}),
    )

    with pytest.raises(ValueError, match="same transaction"):
        await RecoveryStateRepository(session).reconcile(
            actor=actor,
            reason="reviewed",
            audit=AuditRepository(other_session),
            operations_tenant_id=operations_tenant_id,
        )


async def test_job_retry_and_outbox_reconcile_reject_cross_transaction_audit() -> None:
    session = _session()
    other_audit = AuditRepository(_session())
    tenant_id = uuid4()
    actor = ActorContext(
        person_id=uuid4(),
        session_id=uuid4(),
        tenant_id=tenant_id,
        permissions=frozenset({"job_retry", "recovery_reconcile"}),
    )
    dead_job = _job(status=JobStatus.DEAD_LETTER.value)
    dead_job.tenant_id = tenant_id

    with pytest.raises(ValueError, match="same transaction"):
        await JobRepository(session).retry(
            dead_job,
            actor=actor,
            reason="reviewed",
            audit=other_audit,
        )
    with pytest.raises(ValueError, match="same transaction"):
        await OutboxRepository(session).reconcile_held(
            [uuid4()],
            actor=actor,
            reason="reviewed",
            audit=other_audit,
        )


async def test_manual_job_retry_writes_actor_audit_in_the_same_uow() -> None:
    session = _session()
    tenant_id = uuid4()
    row = _job(status=JobStatus.DEAD_LETTER.value)
    row.tenant_id = tenant_id
    row.provider_idempotency_key = row.dedupe_key
    row.dispatch_started_at = datetime(2026, 8, 30, 11, 58, tzinfo=UTC)
    row.delivery_ambiguous_at = datetime(2026, 8, 30, 12, tzinfo=UTC)
    row.last_error = EXPIRED_DISPATCH_AMBIGUITY_REASON
    session.scalar.side_effect = [row, _state()]
    audit = AuditRepository(session)
    audit.append_for_actor = AsyncMock()  # type: ignore[method-assign]
    actor = ActorContext(
        person_id=uuid4(),
        session_id=uuid4(),
        tenant_id=tenant_id,
        permissions=frozenset({"job_retry"}),
    )

    retried = await JobRepository(session).retry(
        row,
        actor=actor,
        reason="provider state reviewed",
        audit=audit,
    )

    assert retried.status == JobStatus.QUEUED.value
    assert retried.attempt_count == 0
    assert retried.reconciled_by == actor.person_id
    assert retried.reconciliation_reason == "provider state reviewed"
    assert retried.provider_idempotency_key is None
    assert retried.dispatch_started_at is None
    assert retried.delivery_ambiguous_at is None
    audit.append_for_actor.assert_awaited_once()  # type: ignore[attr-defined]
    prior_evidence = audit.append_for_actor.await_args.kwargs["payload"]["prior_effect_evidence"]
    assert prior_evidence == {
        "dispatch_started_at": "2026-08-30T11:58:00+00:00",
        "delivery_ambiguous_at": "2026-08-30T12:00:00+00:00",
        "provider_idempotency_key": row.dedupe_key,
    }


async def test_global_job_retry_requires_configured_control_tenant_and_global_permission() -> None:
    control_tenant_id = uuid4()
    row = _job(status=JobStatus.DEAD_LETTER.value)
    row.tenant_id = None
    session = _session()
    session.scalar.side_effect = [row, _state()]
    audit = AuditRepository(session)
    audit.append_for_actor = AsyncMock()  # type: ignore[method-assign]
    actor = ActorContext(
        person_id=uuid4(),
        session_id=uuid4(),
        tenant_id=control_tenant_id,
        permissions=frozenset({"job_retry", "global_job_retry"}),
    )

    retried = await JobRepository(session).retry(
        row,
        actor=actor,
        reason="provider delivery reviewed",
        audit=audit,
        operations_tenant_id=control_tenant_id,
    )

    assert retried.status == JobStatus.QUEUED.value
    audit.append_for_actor.assert_awaited_once()  # type: ignore[attr-defined]

    row.status = JobStatus.DEAD_LETTER.value
    actor_without_global_permission = ActorContext(
        person_id=actor.person_id,
        session_id=actor.session_id,
        tenant_id=control_tenant_id,
        permissions=frozenset({"job_retry"}),
    )
    session.scalar.side_effect = [row]
    with pytest.raises(AuthorizationDenied):
        await JobRepository(session).retry(
            row,
            actor=actor_without_global_permission,
            reason="provider delivery reviewed",
            audit=audit,
            operations_tenant_id=control_tenant_id,
        )


async def test_global_job_retry_rejects_an_ordinary_tenant_even_with_global_permission() -> None:
    row = _job(status=JobStatus.DEAD_LETTER.value)
    row.tenant_id = None
    session = _session()
    session.scalar.return_value = row
    audit = AuditRepository(session)
    actor = ActorContext(
        person_id=uuid4(),
        session_id=uuid4(),
        tenant_id=uuid4(),
        permissions=frozenset({"job_retry", "global_job_retry"}),
    )

    with pytest.raises(AuthorizationDenied):
        await JobRepository(session).retry(
            row,
            actor=actor,
            reason="provider delivery reviewed",
            audit=audit,
            operations_tenant_id=uuid4(),
        )


async def test_job_reconciliation_clears_hold_metadata_before_queueing() -> None:
    session = _session()
    tenant_id = uuid4()
    row = _job(status=JobStatus.HELD.value)
    row.tenant_id = tenant_id
    session.scalar.return_value = _state(RecoveryStatus.HELD.value)
    session.scalars.return_value = _Rows([row])
    audit = AuditRepository(session)
    audit.append_for_actor = AsyncMock()  # type: ignore[method-assign]
    actor = ActorContext(
        person_id=uuid4(),
        session_id=uuid4(),
        tenant_id=tenant_id,
        permissions=frozenset({"recovery_reconcile"}),
    )

    reconciled = await JobRepository(session).reconcile_held(
        [row.id],
        actor=actor,
        reason="provider state verified",
        audit=audit,
        now=datetime(2026, 8, 30, 12, 1, tzinfo=UTC),
    )

    assert reconciled == [row]
    assert row.status == JobStatus.QUEUED.value
    assert row.held_at is None
    assert row.hold_reason is None
    audit.append_for_actor.assert_awaited_once()  # type: ignore[attr-defined]


async def test_shared_recovery_lock_compiles_to_postgresql_for_share() -> None:
    session = _session()
    session.scalar.return_value = _state()

    await RecoveryStateRepository(session).get(lock=True, shared_lock=True)

    statement = session.scalar.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "FOR SHARE" in sql
