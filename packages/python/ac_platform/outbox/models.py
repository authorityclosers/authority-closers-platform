"""SQLAlchemy 2 persistence shapes for durable external work."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Uuid,
    false,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ac_platform.db.base import Base
from ac_platform.identity.models import Person


def utc_now() -> datetime:
    """Return an aware UTC timestamp suitable for application-side defaults."""

    return datetime.now(UTC)


class OutboxEventStatus(StrEnum):
    """Lifecycle of an outbox intent, independent of the downstream job."""

    PENDING = "pending"
    HELD = "held"
    PUBLISHED = "published"
    DEAD_LETTER = "dead_letter"


class JobStatus(StrEnum):
    """Durable job states used by the worker and recovery policy."""

    QUEUED = "queued"
    # ``pending`` and ``processing`` are descriptive compatibility aliases for
    # callers that use queue terminology rather than the persisted state names.
    PENDING = "queued"
    LEASED = "leased"
    PROCESSING = "leased"
    RETRY_WAIT = "retry_wait"
    HELD = "held"
    SUCCEEDED = "succeeded"
    DEAD_LETTER = "dead_letter"
    FAILED = "dead_letter"


class RecoveryStatus(StrEnum):
    """Global durable recovery gate states."""

    HELD = "held"
    READY = "ready"


class OutboxEvent(Base):
    """A transactional intent that must survive a process crash."""

    __tablename__ = "outbox_events"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'held', 'published', 'dead_letter')",
            name="status",
        ),
        CheckConstraint(
            "length(trim(event_type)) > 0",
            name="event_type_nonblank",
        ),
        CheckConstraint(
            "length(trim(aggregate_type)) > 0",
            name="aggregate_type_nonblank",
        ),
        CheckConstraint(
            "length(trim(dedupe_key)) > 0",
            name="dedupe_key_nonblank",
        ),
        CheckConstraint(
            "publish_attempts >= 0",
            name="publish_attempts_nonnegative",
        ),
        CheckConstraint(
            "(status = 'held' AND held_at IS NOT NULL AND hold_reason IS NOT NULL "
            "AND length(trim(hold_reason)) > 0) OR "
            "(status <> 'held' AND held_at IS NULL AND hold_reason IS NULL)",
            name="held_state_consistent",
        ),
        CheckConstraint(
            "(status = 'published' AND published_at IS NOT NULL) OR "
            "(status <> 'published' AND published_at IS NULL)",
            name="published_state_consistent",
        ),
        CheckConstraint(
            "(status = 'dead_letter' AND dead_lettered_at IS NOT NULL "
            "AND last_error IS NOT NULL AND length(trim(last_error)) > 0) OR "
            "(status <> 'dead_letter' AND dead_lettered_at IS NULL)",
            name="dead_letter_state_consistent",
        ),
        CheckConstraint(
            "(reconciled_at IS NULL AND reconciled_by IS NULL "
            "AND reconciliation_reason IS NULL) OR "
            "(reconciled_at IS NOT NULL AND reconciled_by IS NOT NULL "
            "AND reconciliation_reason IS NOT NULL "
            "AND length(trim(reconciliation_reason)) > 0)",
            name="reconciliation_state_consistent",
        ),
        Index("ix_outbox_events_pending", "status", "created_at"),
        Index("ix_outbox_events_aggregate", "aggregate_type", "aggregate_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", name="fk_outbox_events_tenant_id_tenants"),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(200), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=OutboxEventStatus.PENDING.value,
        server_default=OutboxEventStatus.PENDING.value,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    publish_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    held_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hold_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    dead_lettered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reconciled_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("persons.id", name="fk_outbox_events_reconciled_by_persons"),
        nullable=True,
    )
    reconciliation_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    @property
    def event_name(self) -> str:
        """Descriptive alias matching the kernel envelope terminology."""

        return self.event_type


class Job(Base):
    """A durable, idempotent unit of work with a renewable lease."""

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'leased', 'retry_wait', 'held', 'succeeded', 'dead_letter')",
            name="status",
        ),
        CheckConstraint(
            "length(trim(kind)) > 0",
            name="kind_nonblank",
        ),
        CheckConstraint(
            "length(trim(dedupe_key)) > 0",
            name="dedupe_key_nonblank",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND max_attempts >= 1 AND attempt_count <= max_attempts",
            name="attempt_bounds",
        ),
        CheckConstraint(
            "(status = 'leased' AND lease_token IS NOT NULL AND leased_until IS NOT NULL) OR "
            "(status <> 'leased' AND lease_token IS NULL AND leased_until IS NULL)",
            name="lease_state_consistent",
        ),
        CheckConstraint(
            "(status = 'held' AND held_at IS NOT NULL AND hold_reason IS NOT NULL "
            "AND length(trim(hold_reason)) > 0) OR "
            "(status <> 'held' AND held_at IS NULL AND hold_reason IS NULL)",
            name="held_state_consistent",
        ),
        CheckConstraint(
            "(status = 'dead_letter' AND dead_lettered_at IS NOT NULL "
            "AND last_error IS NOT NULL AND length(trim(last_error)) > 0) OR "
            "(status <> 'dead_letter' AND dead_lettered_at IS NULL)",
            name="dead_letter_state_consistent",
        ),
        CheckConstraint(
            "(reconciled_at IS NULL AND reconciled_by IS NULL "
            "AND reconciliation_reason IS NULL) OR "
            "(reconciled_at IS NOT NULL AND reconciled_by IS NOT NULL "
            "AND reconciliation_reason IS NOT NULL "
            "AND length(trim(reconciliation_reason)) > 0)",
            name="reconciliation_state_consistent",
        ),
        CheckConstraint(
            "(provider_receipt IS NULL AND provider_receipt_digest IS NULL "
            "AND receipt_recorded_at IS NULL) OR "
            "(provider_receipt IS NOT NULL AND provider_receipt_digest IS NOT NULL "
            "AND receipt_recorded_at IS NOT NULL)",
            name="provider_receipt_state_consistent",
        ),
        CheckConstraint(
            "(dispatch_started_at IS NULL AND provider_idempotency_key IS NULL) OR "
            "(dispatch_started_at IS NOT NULL AND provider_idempotency_key IS NOT NULL)",
            name="dispatch_state_consistent",
        ),
        CheckConstraint(
            "delivery_ambiguous_at IS NULL OR dispatch_started_at IS NOT NULL",
            name="ambiguous_delivery_requires_dispatch",
        ),
        CheckConstraint(
            "(external_side_effect AND recovery_generation >= 1) OR "
            "(NOT external_side_effect AND recovery_generation = 0)",
            name="recovery_generation_consistent",
        ),
        CheckConstraint(
            "status <> 'succeeded' OR NOT external_side_effect OR provider_receipt IS NOT NULL",
            name="external_success_requires_receipt",
        ),
        Index("ix_jobs_claimable", "status", "available_at", "created_at"),
        Index("ix_jobs_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", name="fk_jobs_tenant_id_tenants"),
        nullable=True,
    )
    kind: Mapped[str] = mapped_column(String(128), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    external_side_effect: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    recovery_generation: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=JobStatus.QUEUED.value,
        server_default=JobStatus.QUEUED.value,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5, server_default="5"
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    leased_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_token: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    provider_idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dispatch_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    provider_receipt: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    provider_receipt_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    receipt_recorded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivery_ambiguous_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    held_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hold_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    dead_lettered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reconciled_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("persons.id", name="fk_jobs_reconciled_by_persons"),
        nullable=True,
    )
    reconciliation_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
    )

    @property
    def attempts(self) -> int:
        """Compatibility alias for the persisted attempt counter."""

        return self.attempt_count

    @property
    def run_at(self) -> datetime:
        """Compatibility alias for the next eligible execution time."""

        return self.available_at


class OperationsControlBase(DeclarativeBase):
    """Internal operations metadata kept outside the mapped domain registry."""

    metadata = MetaData(naming_convention=Base.metadata.naming_convention)


class OperationsRecoveryState(OperationsControlBase):
    """Singleton database authority fencing every external side effect generation."""

    __tablename__ = "operations_recovery_state"
    __table_args__ = (
        CheckConstraint("id = 1", name="singleton"),
        CheckConstraint("generation >= 1", name="generation_positive"),
        CheckConstraint("status IN ('held', 'ready')", name="status"),
        CheckConstraint(
            "status <> 'held' OR (marked_at IS NOT NULL AND hold_reason IS NOT NULL)",
            name="held_evidence_required",
        ),
        CheckConstraint(
            "(status = 'held' AND reconciled_at IS NULL AND reconciled_by IS NULL "
            "AND reconciliation_reason IS NULL) OR "
            "(status = 'ready' AND reconciled_at IS NOT NULL "
            "AND reconciled_by IS NOT NULL AND reconciliation_reason IS NOT NULL)",
            name="reconciliation_state_consistent",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=RecoveryStatus.HELD.value,
        server_default=RecoveryStatus.HELD.value,
    )
    marked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    hold_reason: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        default="initial_activation_requires_reconciliation",
        server_default="initial_activation_requires_reconciliation",
    )
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reconciled_by: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            Person.__table__.c.id,
            name="fk_operations_recovery_state_reconciled_by_persons",
        ),
        nullable=True,
    )
    reconciliation_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )


def operations_control_metadata() -> MetaData:
    """Return the internal durable control schema for migration parity checks."""

    return OperationsControlBase.metadata


__all__ = [
    "Job",
    "JobStatus",
    "OperationsControlBase",
    "OperationsRecoveryState",
    "OutboxEvent",
    "OutboxEventStatus",
    "RecoveryStatus",
    "operations_control_metadata",
    "utc_now",
]
