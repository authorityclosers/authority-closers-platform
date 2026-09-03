from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine, create_engine, delete, event, inspect, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from ac_platform.audit.models import (
    GENESIS_HASH,
    AuditChainHead,
    AuditEvent,
    AuditMutationError,
    audit_control_metadata,
)
from ac_platform.audit.service import compute_audit_hash, verify_audit_chain_sync
from ac_platform.db.models import model_metadata
from ac_platform.identity.models import Person
from ac_platform.outbox.models import (
    Job,
    JobStatus,
    OperationsRecoveryState,
    OutboxEvent,
    OutboxEventStatus,
    RecoveryStatus,
    operations_control_metadata,
)
from ac_platform.outbox.repository import (
    EXPIRED_DISPATCH_AMBIGUITY_REASON,
    build_job_acknowledge_statement,
    build_job_ambiguity_statement,
    build_job_claim_statement,
    build_job_dispatch_statement,
    build_job_expired_dispatch_quarantine_statement,
    build_job_receipt_statement,
    build_job_renew_statement,
    build_job_take_statement,
    canonical_receipt_digest,
)
from ac_platform.providers.models import ProviderInbox, ProviderInboxStatus
from ac_platform.tenancy.models import Tenant


def _migration_path() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "db"
        / "migrations"
        / "versions"
        / "20260830_0006_operations.py"
    )


def _migration_module() -> ModuleType:
    specification = importlib.util.spec_from_file_location(
        "operations_migration",
        _migration_path(),
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _operations_metadata() -> dict[str, sa.Table]:
    tables: dict[str, sa.Table] = {}
    for metadata in (
        model_metadata(),
        operations_control_metadata(),
        audit_control_metadata(),
    ):
        tables.update(metadata.tables)
    return tables


@pytest.fixture()
def database() -> tuple[Engine, DbSession]:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    # The operations fixture only needs its own persistence graph.  Keep the
    # unrelated certificate tables out of this SQLite-only fixture because
    # their PostgreSQL-specific digest constraint is exercised by their own
    # PostgreSQL suite.
    excluded_tables = {
        "completion_snapshots",
        "course_completion_certificates",
        "certificate_events",
    }
    model_metadata().create_all(
        engine,
        tables=[
            table for table in model_metadata().sorted_tables if table.name not in excluded_tables
        ],
    )
    operations_control_metadata().create_all(engine)
    audit_control_metadata().create_all(engine)
    session = DbSession(engine)
    session.add(OperationsRecoveryState())
    session.commit()
    try:
        yield engine, session
    finally:
        session.close()
        engine.dispose()


def test_operations_migration_is_forward_only_and_pinned_to_0005() -> None:
    migration = _migration_module()

    assert migration.revision == "20260830_0006"
    assert migration.down_revision == "20260830_0005"
    with pytest.raises(RuntimeError, match="forward-only"):
        migration.downgrade()


def test_operations_migration_builds_every_durable_table_with_model_parity() -> None:
    engine = create_engine("sqlite:///:memory:")
    migration = _migration_module()
    expected_tables = {
        "outbox_events",
        "jobs",
        "operations_recovery_state",
        "provider_inbox",
        "audit_events",
        "audit_chain_heads",
    }
    try:
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        with engine.begin() as connection:
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
        inspector = inspect(engine)
        assert expected_tables.issubset(inspector.get_table_names())
        models = _operations_metadata()
        for table_name in expected_tables:
            assert {column["name"] for column in inspector.get_columns(table_name)} == set(
                models[table_name].columns.keys()
            )
            migrated_checks = {
                constraint["name"] for constraint in inspector.get_check_constraints(table_name)
            }
            model_checks = {
                constraint.name
                for constraint in models[table_name].constraints
                if isinstance(constraint, sa.CheckConstraint)
            }
            assert migrated_checks == model_checks
            assert {index["name"] for index in inspector.get_indexes(table_name)} == {
                index.name for index in models[table_name].indexes
            }

        with engine.connect() as connection:
            initial = (
                connection.execute(sa.text("SELECT * FROM operations_recovery_state"))
                .mappings()
                .one()
            )
        assert initial["id"] == 1
        assert initial["generation"] == 1
        assert initial["status"] == RecoveryStatus.HELD.value
        assert initial["hold_reason"] == "initial_activation_requires_reconciliation"
    finally:
        engine.dispose()


def test_postgresql_migration_reinforces_append_only_audit_evidence() -> None:
    source = _migration_path().read_text(encoding="utf-8")

    assert "BEFORE UPDATE OR DELETE ON {quoted_schema}.audit_events" in source
    assert "BEFORE DELETE ON {quoted_schema}.audit_chain_heads" in source
    assert source.count("BEFORE TRUNCATE") == 2
    assert "reject_audit_evidence_mutation" in source
    assert "SECURITY DEFINER" in source
    assert "SET search_path = pg_catalog, {quoted_schema}, pg_temp" in source
    assert "append_audit_chain_head" in source
    assert "REVOKE ALL ON TABLE {quoted_schema}.audit_chain_heads FROM PUBLIC" in source
    assert "_active_postgresql_schema" in source
    assert "current_setting('ac.audit_append', true)" not in source


def test_dedupe_keys_and_provider_inbox_scope_are_database_unique(
    database: tuple[Engine, DbSession],
) -> None:
    _, session = database
    outbox = OutboxEvent(
        id=uuid4(),
        event_type="enrollment.created.v1",
        aggregate_type="enrollment",
        aggregate_id=uuid4(),
        dedupe_key="enrollment:1",
        payload={"source": "free_self"},
    )
    session.add(outbox)
    session.commit()

    session.add(
        OutboxEvent(
            id=uuid4(),
            event_type=outbox.event_type,
            aggregate_type=outbox.aggregate_type,
            aggregate_id=outbox.aggregate_id,
            dedupe_key=outbox.dedupe_key,
            payload=outbox.payload,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    inbox = ProviderInbox(
        id=uuid4(),
        provider="fake-email",
        external_event_id="evt-1",
        event_type="delivery.accepted",
        payload={"ok": True},
    )
    session.add(inbox)
    session.commit()
    assert len(inbox.payload_digest) == 64
    session.add(
        ProviderInbox(
            id=uuid4(),
            provider=inbox.provider,
            external_event_id=inbox.external_event_id,
            event_type=inbox.event_type,
            payload={"ok": False},
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_audit_event_is_append_only_and_raw_tamper_is_detectable(
    database: tuple[Engine, DbSession],
) -> None:
    engine, session = database
    tenant_id = uuid4()
    actor_id = uuid4()
    event_id = uuid4()
    occurred_at = datetime(2026, 8, 30, 12, tzinfo=UTC)
    session.add_all(
        [
            Tenant(id=tenant_id, slug="audit-test", name="Audit test"),
            Person(id=actor_id, email="operator@example.test"),
        ]
    )
    session.commit()
    event_hash = compute_audit_hash(
        event_id=event_id,
        tenant_id=tenant_id,
        sequence_no=1,
        actor_person_id=actor_id,
        actor_type="person",
        session_id=None,
        action="job.retry",
        resource_type="job",
        resource_id="job-1",
        payload={"approved": True},
        reason="operator review",
        request_id=None,
        occurred_at=occurred_at,
        recorded_at=occurred_at,
        previous_hash=GENESIS_HASH,
    )
    audit_event = AuditEvent(
        id=event_id,
        tenant_id=tenant_id,
        sequence_no=1,
        actor_person_id=actor_id,
        actor_type="person",
        action="job.retry",
        resource_type="job",
        resource_id="job-1",
        payload={"approved": True},
        reason="operator review",
        occurred_at=occurred_at,
        recorded_at=occurred_at,
        previous_hash=GENESIS_HASH,
        event_hash=event_hash,
    )
    checkpoint = AuditChainHead(
        tenant_id=tenant_id,
        sequence_no=1,
        event_id=event_id,
        event_hash=event_hash,
        updated_at=occurred_at,
    )
    session.add(audit_event)
    session.flush()
    session.add(checkpoint)
    session.commit()
    assert verify_audit_chain_sync(session, tenant_id).valid

    session.add(
        AuditEvent(
            id=uuid4(),
            tenant_id=tenant_id,
            sequence_no=1,
            actor_person_id=actor_id,
            actor_type="person",
            action="job.retry",
            resource_type="job",
            resource_id="job-2",
            payload={"approved": True},
            reason="duplicate sequence test",
            occurred_at=occurred_at,
            recorded_at=occurred_at,
            previous_hash=GENESIS_HASH,
            event_hash="b" * 64,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    audit_event.action = "job.delete"
    with pytest.raises(AuditMutationError, match="append-only"):
        session.flush()
    session.rollback()

    with engine.begin() as connection:
        connection.execute(
            update(AuditEvent.__table__)
            .where(AuditEvent.id == event_id)
            .values(payload={"approved": False})
        )
    session.expire_all()
    assert not verify_audit_chain_sync(session, tenant_id).valid


def test_audit_checkpoint_detects_raw_tail_truncation(
    database: tuple[Engine, DbSession],
) -> None:
    engine, session = database
    tenant_id = uuid4()
    actor_id = uuid4()
    event_id = uuid4()
    occurred_at = datetime(2026, 8, 30, 12, tzinfo=UTC)
    session.add_all(
        [
            Tenant(id=tenant_id, slug="truncate-test", name="Truncate test"),
            Person(id=actor_id, email="truncate@example.test"),
        ]
    )
    session.commit()
    event_hash = compute_audit_hash(
        event_id=event_id,
        tenant_id=tenant_id,
        sequence_no=1,
        actor_person_id=actor_id,
        actor_type="person",
        session_id=None,
        action="job.retry",
        resource_type="job",
        resource_id="job-1",
        payload={},
        reason=None,
        request_id=None,
        occurred_at=occurred_at,
        recorded_at=occurred_at,
        previous_hash=GENESIS_HASH,
    )
    audit_event = AuditEvent(
        id=event_id,
        tenant_id=tenant_id,
        sequence_no=1,
        actor_person_id=actor_id,
        actor_type="person",
        action="job.retry",
        resource_type="job",
        resource_id="job-1",
        payload={},
        occurred_at=occurred_at,
        recorded_at=occurred_at,
        previous_hash=GENESIS_HASH,
        event_hash=event_hash,
    )
    session.add(audit_event)
    session.flush()
    session.add(
        AuditChainHead(
            tenant_id=tenant_id,
            sequence_no=1,
            event_id=event_id,
            event_hash=event_hash,
            updated_at=occurred_at,
        )
    )
    session.commit()

    with engine.begin() as connection:
        # SQLite enforces the newly canonical event-id foreign key, while this
        # test intentionally simulates storage-level tail truncation.
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.execute(delete(AuditEvent.__table__).where(AuditEvent.id == event_id))
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    session.expire_all()
    report = verify_audit_chain_sync(session, tenant_id)

    assert not report.valid
    assert report.failure_reason == "audit checkpoint references a missing event tail"


@pytest.mark.parametrize(
    "invalid",
    [
        "job_leased_without_token",
        "job_queued_with_token",
        "job_held_without_evidence",
        "job_dead_letter_without_error",
        "outbox_published_without_timestamp",
        "outbox_pending_with_published_timestamp",
        "outbox_held_without_evidence",
        "provider_processing_without_lease",
        "provider_received_with_lease",
        "provider_processed_without_timestamp",
        "provider_retry_without_error",
    ],
)
def test_state_constraints_fail_closed(
    database: tuple[Engine, DbSession],
    invalid: str,
) -> None:
    _, session = database
    now = datetime(2026, 8, 30, 12, tzinfo=UTC)
    token = uuid4()
    if invalid.startswith("job_"):
        row: object = Job(
            id=uuid4(),
            kind="internal.test.v1",
            dedupe_key=f"job:{uuid4()}",
            payload={},
            external_side_effect=False,
            recovery_generation=0,
            status=JobStatus.QUEUED.value,
            available_at=now,
        )
        assert isinstance(row, Job)
        if invalid == "job_leased_without_token":
            row.status = JobStatus.LEASED.value
        elif invalid == "job_queued_with_token":
            row.lease_token = token
            row.leased_until = now + timedelta(minutes=1)
        elif invalid == "job_held_without_evidence":
            row.status = JobStatus.HELD.value
        else:
            row.status = JobStatus.DEAD_LETTER.value
            row.dead_lettered_at = now
    elif invalid.startswith("outbox_"):
        row = OutboxEvent(
            id=uuid4(),
            event_type="test.event.v1",
            aggregate_type="test",
            aggregate_id=uuid4(),
            dedupe_key=f"event:{uuid4()}",
            payload={},
            status=OutboxEventStatus.PENDING.value,
        )
        assert isinstance(row, OutboxEvent)
        if invalid == "outbox_published_without_timestamp":
            row.status = OutboxEventStatus.PUBLISHED.value
        elif invalid == "outbox_pending_with_published_timestamp":
            row.published_at = now
        else:
            row.status = OutboxEventStatus.HELD.value
    else:
        row = ProviderInbox(
            id=uuid4(),
            provider="fake-email",
            external_event_id=f"evt-{uuid4()}",
            event_type="delivery.accepted",
            payload={},
            status=ProviderInboxStatus.RECEIVED.value,
        )
        assert isinstance(row, ProviderInbox)
        if invalid == "provider_processing_without_lease":
            row.status = ProviderInboxStatus.PROCESSING.value
        elif invalid == "provider_received_with_lease":
            row.processing_lease_token = token
            row.processing_lease_until = now + timedelta(minutes=1)
        elif invalid == "provider_processed_without_timestamp":
            row.status = ProviderInboxStatus.PROCESSED.value
        else:
            row.status = ProviderInboxStatus.RETRY_WAIT.value

    session.add(row)
    with pytest.raises(IntegrityError):
        session.flush()


def test_required_evidence_fields_reject_blank_strings(
    database: tuple[Engine, DbSession],
) -> None:
    _, session = database
    now = datetime(2026, 8, 30, 12, tzinfo=UTC)

    session.add(
        Job(
            id=uuid4(),
            kind="internal.test.v1",
            dedupe_key=f"blank-job:{uuid4()}",
            payload={},
            status=JobStatus.HELD.value,
            held_at=now,
            hold_reason="   ",
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    session.add(
        OutboxEvent(
            id=uuid4(),
            event_type="test.event.v1",
            aggregate_type="test",
            aggregate_id=uuid4(),
            dedupe_key=f"blank-outbox:{uuid4()}",
            payload={},
            status=OutboxEventStatus.HELD.value,
            held_at=now,
            hold_reason="",
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    session.add(
        ProviderInbox(
            id=uuid4(),
            provider="fake-email",
            external_event_id=f"blank-provider:{uuid4()}",
            event_type="delivery.failed",
            payload={},
            status=ProviderInboxStatus.RETRY_WAIT.value,
            last_error=" ",
            available_at=now,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    tenant_id = uuid4()
    actor_id = uuid4()
    session.add_all(
        [
            Tenant(id=tenant_id, slug=f"blank-audit-{uuid4()}", name="Blank audit"),
            Person(id=actor_id, email=f"blank-audit-{uuid4()}@example.test"),
        ]
    )
    session.commit()
    session.add(
        AuditEvent(
            id=uuid4(),
            tenant_id=tenant_id,
            sequence_no=1,
            actor_person_id=actor_id,
            action="job.retry",
            resource_type="job",
            payload={},
            reason="",
            previous_hash=GENESIS_HASH,
            event_hash="a" * 64,
            occurred_at=now,
            recorded_at=now,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_recovery_state_reverse_constraint_rejects_inconsistent_evidence(
    database: tuple[Engine, DbSession],
) -> None:
    _, session = database
    state = session.get(OperationsRecoveryState, 1)
    assert state is not None
    state.status = RecoveryStatus.READY.value

    with pytest.raises(IntegrityError):
        session.flush()


def test_sqlite_executes_db_timed_job_fences_and_global_generation_guard(
    database: tuple[Engine, DbSession],
) -> None:
    _, session = database
    actor_id = uuid4()
    session.add(Person(id=actor_id, email="worker-operator@example.test"))
    state = session.get(OperationsRecoveryState, 1)
    assert state is not None
    state.status = RecoveryStatus.READY.value
    state.reconciled_at = datetime.now(UTC)
    state.reconciled_by = actor_id
    state.reconciliation_reason = "initial operations review"
    token = uuid4()
    job = Job(
        id=uuid4(),
        kind="email.enrollment_welcome.v1",
        dedupe_key=f"outbox:{uuid4()}",
        payload={},
        external_side_effect=True,
        recovery_generation=state.generation,
        status=JobStatus.LEASED.value,
        attempt_count=1,
        lease_token=token,
        leased_until=datetime.now(UTC) + timedelta(minutes=5),
    )
    session.add(job)
    session.commit()

    renewed = session.execute(
        build_job_renew_statement(
            job_id=job.id,
            lease_token=token,
            lease_for=timedelta(seconds=60),
            recovery_generation=state.generation,
            dialect="sqlite",
        ).execution_options(synchronize_session=False)
    )
    assert renewed.rowcount == 1
    session.commit()

    state.status = RecoveryStatus.HELD.value
    state.reconciled_at = None
    state.reconciled_by = None
    state.reconciliation_reason = None
    session.commit()
    fenced = session.execute(
        build_job_renew_statement(
            job_id=job.id,
            lease_token=token,
            lease_for=timedelta(seconds=60),
            recovery_generation=state.generation,
            dialect="sqlite",
        ).execution_options(synchronize_session=False)
    )
    assert fenced.rowcount == 0

    state.status = RecoveryStatus.READY.value
    state.reconciled_at = datetime.now(UTC)
    state.reconciled_by = actor_id
    state.reconciliation_reason = "restore reviewed"
    session.commit()
    provider_key = job.dedupe_key
    dispatched = session.execute(
        build_job_dispatch_statement(
            job_id=job.id,
            lease_token=token,
            recovery_generation=state.generation,
            provider_idempotency_key=provider_key,
        ).execution_options(synchronize_session=False)
    )
    assert dispatched.rowcount == 1
    ambiguous = session.execute(
        build_job_ambiguity_statement(
            job_id=job.id,
            lease_token=token,
            recovery_generation=state.generation,
            provider_idempotency_key=provider_key,
            error="provider timeout",
        ).execution_options(synchronize_session=False)
    )
    assert ambiguous.rowcount == 1
    session.commit()
    session.refresh(job)
    assert job.delivery_ambiguous_at is not None
    assert job.last_error == "provider timeout"
    receipt = {"idempotency_key": provider_key, "accepted": True}
    recorded = session.execute(
        build_job_receipt_statement(
            job_id=job.id,
            lease_token=token,
            receipt=receipt,
            receipt_digest=canonical_receipt_digest(receipt),
        ).execution_options(synchronize_session=False)
    )
    assert recorded.rowcount == 1
    acknowledged = session.execute(
        build_job_acknowledge_statement(job_id=job.id, lease_token=token).execution_options(
            synchronize_session=False
        )
    )
    assert acknowledged.rowcount == 1
    session.commit()
    session.refresh(job)
    assert job.status == JobStatus.SUCCEEDED.value
    assert job.lease_token is None
    assert job.provider_receipt == receipt
    stale_ambiguity = session.execute(
        build_job_ambiguity_statement(
            job_id=job.id,
            lease_token=token,
            recovery_generation=state.generation,
            provider_idempotency_key=provider_key,
            error="stale worker must not overwrite success",
        ).execution_options(synchronize_session=False)
    )
    assert stale_ambiguity.rowcount == 0


def test_expired_effect_claim_quarantines_unknown_delivery_and_reclaims_only_safe_jobs(
    database: tuple[Engine, DbSession],
) -> None:
    _, session = database
    now = datetime.now(UTC)
    operator_id = uuid4()
    session.add(Person(id=operator_id, email=f"claim-operator-{uuid4()}@example.test"))
    state = session.get(OperationsRecoveryState, 1)
    assert state is not None
    state.status = RecoveryStatus.READY.value
    state.reconciled_at = now
    state.reconciled_by = operator_id
    state.reconciliation_reason = "claim recovery reviewed"

    def expired_job(
        *,
        external: bool,
        dispatch_started: bool,
        receipt_present: bool = False,
    ) -> Job:
        job_id = uuid4()
        provider_key = f"claim:{job_id}" if dispatch_started else None
        receipt = {"idempotency_key": provider_key, "accepted": True} if receipt_present else None
        job = Job(
            id=job_id,
            kind="email.enrollment_welcome.v1" if external else "internal.test.v1",
            dedupe_key=f"job:{job_id}",
            payload={},
            external_side_effect=external,
            recovery_generation=state.generation if external else 0,
            status=JobStatus.LEASED.value,
            attempt_count=1,
            max_attempts=5,
            available_at=now - timedelta(minutes=10),
            lease_token=uuid4(),
            leased_until=now - timedelta(minutes=1),
            provider_idempotency_key=provider_key,
            dispatch_started_at=now - timedelta(minutes=2) if dispatch_started else None,
            created_at=now - timedelta(minutes=10),
            updated_at=now - timedelta(minutes=1),
        )
        if receipt is not None:
            job.provider_receipt = receipt
            job.provider_receipt_digest = canonical_receipt_digest(receipt)
            job.receipt_recorded_at = now - timedelta(minutes=2)
        return job

    unresolved = expired_job(external=True, dispatch_started=True)
    before_dispatch = expired_job(external=True, dispatch_started=False)
    internal = expired_job(external=False, dispatch_started=True)
    with_receipt = expired_job(
        external=True,
        dispatch_started=True,
        receipt_present=True,
    )
    classified_retry_id = uuid4()
    classified_retry = Job(
        id=classified_retry_id,
        kind="email.enrollment_welcome.v1",
        dedupe_key=f"job:{classified_retry_id}",
        payload={},
        external_side_effect=True,
        recovery_generation=state.generation,
        status=JobStatus.RETRY_WAIT.value,
        attempt_count=1,
        max_attempts=5,
        available_at=now - timedelta(minutes=1),
        provider_idempotency_key=f"claim:{classified_retry_id}",
        dispatch_started_at=now - timedelta(minutes=2),
        created_at=now - timedelta(minutes=5),
        updated_at=now - timedelta(minutes=1),
    )
    session.add_all([unresolved, before_dispatch, internal, with_receipt, classified_retry])
    session.commit()

    quarantined = session.execute(
        build_job_expired_dispatch_quarantine_statement().execution_options(
            synchronize_session=False
        )
    )
    assert quarantined.rowcount == 1
    session.commit()
    session.refresh(unresolved)
    assert unresolved.status == JobStatus.DEAD_LETTER.value
    assert unresolved.delivery_ambiguous_at is not None
    assert unresolved.dead_lettered_at is not None
    assert unresolved.last_error == EXPIRED_DISPATCH_AMBIGUITY_REASON
    assert unresolved.lease_token is None
    assert unresolved.leased_until is None

    claimable = list(
        session.scalars(
            build_job_claim_statement(
                now=now,
                recovery_generation=state.generation,
                limit=10,
            )
        ).all()
    )
    assert {row.id for row in claimable} == {
        before_dispatch.id,
        internal.id,
        with_receipt.id,
        classified_retry.id,
    }
    fenced_take = session.execute(
        build_job_take_statement(
            job_id=unresolved.id,
            lease_token=uuid4(),
            lease_for=timedelta(seconds=30),
            recovery_generation=state.generation,
            dialect="sqlite",
        ).execution_options(synchronize_session=False)
    )
    assert fenced_take.rowcount == 0
    for row in claimable:
        taken = session.execute(
            build_job_take_statement(
                job_id=row.id,
                lease_token=uuid4(),
                lease_for=timedelta(seconds=30),
                recovery_generation=state.generation,
                dialect="sqlite",
            ).execution_options(synchronize_session=False)
        )
        assert taken.rowcount == 1
