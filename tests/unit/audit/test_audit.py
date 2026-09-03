from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit import (
    GENESIS_HASH,
    AuditChainHead,
    AuditRepository,
    build_audit_tenant_lock_statement,
    canonical_audit_bytes,
    compute_audit_hash,
    verify_audit_chain,
)
from ac_platform.audit.models import AuditEvent
from ac_platform.kernel.authz import ActorContext


class _Rows:
    def __init__(self, rows: list[AuditEvent]) -> None:
        self._rows = rows

    def all(self) -> list[AuditEvent]:
        return self._rows


def _session() -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.add = Mock()
    return session


def _event(
    *,
    tenant_id: UUID,
    actor_id: UUID,
    sequence: int,
    previous_hash: str,
    occurred_at: datetime,
) -> AuditEvent:
    event_id = uuid4()
    event_hash = compute_audit_hash(
        event_id=event_id,
        tenant_id=tenant_id,
        sequence_no=sequence,
        actor_person_id=actor_id,
        actor_type="person",
        session_id=None,
        action="job.retry",
        resource_type="job",
        resource_id=f"job-{sequence}",
        payload={"attempt": sequence},
        reason="operator review",
        request_id=f"request-{sequence}",
        occurred_at=occurred_at,
        recorded_at=occurred_at,
        previous_hash=previous_hash,
    )
    return AuditEvent(
        id=event_id,
        tenant_id=tenant_id,
        sequence_no=sequence,
        actor_person_id=actor_id,
        actor_type="person",
        action="job.retry",
        resource_type="job",
        resource_id=f"job-{sequence}",
        payload={"attempt": sequence},
        reason="operator review",
        request_id=f"request-{sequence}",
        occurred_at=occurred_at,
        recorded_at=occurred_at,
        previous_hash=previous_hash,
        event_hash=event_hash,
    )


def _head(row: AuditEvent) -> AuditChainHead:
    return AuditChainHead(
        tenant_id=row.tenant_id,
        sequence_no=row.sequence_no,
        event_id=row.id,
        event_hash=row.event_hash,
        updated_at=row.recorded_at,
    )


async def test_audit_append_updates_the_per_tenant_checkpoint_in_the_same_uow() -> None:
    session = _session()
    session.scalar.side_effect = [None, None]
    repository = AuditRepository(session)
    tenant_id = uuid4()
    actor_id = uuid4()
    first = await repository.append(
        tenant_id=tenant_id,
        actor_person_id=actor_id,
        action="job.retry",
        resource_type="job",
        resource_id=uuid4(),
        payload={"attempt": 1},
        reason="operator-approved",
        now=datetime(2026, 8, 30, 12, tzinfo=UTC),
    )

    checkpoint = session.add.call_args_list[1].args[0]
    assert isinstance(checkpoint, AuditChainHead)
    assert checkpoint.sequence_no == 1
    assert checkpoint.event_id == first.id
    assert checkpoint.event_hash == first.event_hash
    assert first.previous_hash == GENESIS_HASH

    session.scalar.side_effect = [checkpoint, first]
    second = await repository.append(
        tenant_id=tenant_id,
        actor_person_id=actor_id,
        action="job.reconciled",
        resource_type="job",
        resource_id=first.resource_id,
        payload={"released": True},
        reason="provider state checked",
        now=datetime(2026, 8, 30, 12, 1, tzinfo=UTC),
    )

    assert second.sequence_no == 2
    assert second.previous_hash == first.event_hash
    assert checkpoint.sequence_no == 2
    assert checkpoint.event_id == second.id
    assert checkpoint.event_hash == second.event_hash
    assert session.flush.await_count == 4


async def test_audit_append_rejects_checkpoint_tail_disagreement() -> None:
    session = _session()
    tenant_id = uuid4()
    actor_id = uuid4()
    row = _event(
        tenant_id=tenant_id,
        actor_id=actor_id,
        sequence=1,
        previous_hash=GENESIS_HASH,
        occurred_at=datetime(2026, 8, 30, 12, tzinfo=UTC),
    )
    checkpoint = _head(row)
    checkpoint.event_hash = "f" * 64
    session.scalar.side_effect = [checkpoint, row]

    with pytest.raises(RuntimeError, match="checkpoint does not match"):
        await AuditRepository(session).append(
            tenant_id=tenant_id,
            actor_person_id=actor_id,
            action="job.retry",
            resource_type="job",
        )
    session.add.assert_not_called()


async def test_audit_chain_reconstruction_detects_tamper() -> None:
    tenant_id = uuid4()
    actor_id = uuid4()
    row = _event(
        tenant_id=tenant_id,
        actor_id=actor_id,
        sequence=1,
        previous_hash=GENESIS_HASH,
        occurred_at=datetime(2026, 8, 30, 12, tzinfo=UTC),
    )
    checkpoint = _head(row)
    row.payload = {"attempt": 999}
    session = _session()
    session.scalars.return_value = _Rows([row])
    session.scalar.return_value = checkpoint

    report = await verify_audit_chain(session, tenant_id)

    assert not report.valid
    assert report.failure_sequence == 1
    assert report.failure_reason == "audit event hash does not match stored facts"


async def test_audit_checkpoint_detects_tail_truncation_and_empty_prefix() -> None:
    tenant_id = uuid4()
    actor_id = uuid4()
    first = _event(
        tenant_id=tenant_id,
        actor_id=actor_id,
        sequence=1,
        previous_hash=GENESIS_HASH,
        occurred_at=datetime(2026, 8, 30, 12, tzinfo=UTC),
    )
    second = _event(
        tenant_id=tenant_id,
        actor_id=actor_id,
        sequence=2,
        previous_hash=first.event_hash,
        occurred_at=datetime(2026, 8, 30, 12, 1, tzinfo=UTC),
    )
    checkpoint = _head(second)
    session = _session()
    session.scalars.return_value = _Rows([first])
    session.scalar.return_value = checkpoint

    truncated = await verify_audit_chain(session, tenant_id)
    assert not truncated.valid
    assert truncated.failure_reason == "audit checkpoint does not match the reconstructed tail"

    session.scalars.return_value = _Rows([])
    empty = await verify_audit_chain(session, tenant_id)
    assert not empty.valid
    assert empty.failure_reason == "audit checkpoint references a missing event tail"


async def test_audit_rows_without_a_checkpoint_fail_closed() -> None:
    tenant_id = uuid4()
    row = _event(
        tenant_id=tenant_id,
        actor_id=uuid4(),
        sequence=1,
        previous_hash=GENESIS_HASH,
        occurred_at=datetime(2026, 8, 30, 12, tzinfo=UTC),
    )
    session = _session()
    session.scalars.return_value = _Rows([row])
    session.scalar.return_value = None

    report = await verify_audit_chain(session, tenant_id)

    assert not report.valid
    assert report.failure_reason == "audit chain checkpoint is missing"


async def test_audit_requires_attributable_person_for_person_events() -> None:
    with pytest.raises(ValueError, match="attributable actor"):
        await AuditRepository(_session()).append(
            tenant_id=uuid4(),
            actor_person_id=None,
            action="admin.change",
            resource_type="job",
        )


def test_audit_hash_serializes_every_immutable_model_field() -> None:
    facts = {
        "event_id": uuid4(),
        "tenant_id": uuid4(),
        "sequence_no": 1,
        "actor_person_id": uuid4(),
        "actor_type": "person",
        "session_id": uuid4(),
        "action": "job.retry",
        "resource_type": "job",
        "resource_id": "job-1",
        "payload": {"attempt": 1},
        "reason": "approved",
        "request_id": "request-1",
        "occurred_at": datetime(2026, 8, 30, 12, tzinfo=UTC),
        "recorded_at": datetime(2026, 8, 30, 12, 0, 1, tzinfo=UTC),
        "previous_hash": GENESIS_HASH,
    }
    canonical = json.loads(canonical_audit_bytes(**facts))
    model_fields = set(AuditEvent.__table__.columns.keys())
    canonical_fields = set(canonical)

    assert canonical_fields == (model_fields - {"id", "event_hash"}) | {"event_id"}
    changed = compute_audit_hash(
        **facts | {"recorded_at": datetime(2026, 8, 30, 12, 0, 2, tzinfo=UTC)}
    )
    assert changed != compute_audit_hash(**facts)


def test_audit_append_uses_a_postgresql_tenant_transaction_lock() -> None:
    sql = str(build_audit_tenant_lock_statement(uuid4()).compile(dialect=postgresql.dialect()))

    assert "pg_advisory_xact_lock" in sql


def test_redundant_audit_sequence_index_is_absent() -> None:
    assert {index.name for index in AuditEvent.__table__.indexes} == {"ix_audit_events_resource"}
    assert any(
        constraint.name == "uq_audit_events_tenant_sequence"
        for constraint in AuditEvent.__table__.constraints
    )


async def test_audit_actor_facade_requires_tenant_context() -> None:
    actor = ActorContext(
        person_id=uuid4(),
        session_id=uuid4(),
        tenant_id=None,
    )

    with pytest.raises(ValueError, match="actor tenant"):
        await AuditRepository(_session()).append_for_actor(
            actor,
            action="job.retry",
            resource_type="job",
        )
