"""SQLAlchemy 2 model for append-only audit evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    UniqueConstraint,
    Uuid,
    event,
    func,
)
from sqlalchemy.engine import Connection
from sqlalchemy.orm import DeclarativeBase, Mapped, Mapper, mapped_column

from ac_platform.db.base import Base
from ac_platform.tenancy.models import Tenant

GENESIS_HASH = "0" * 64


def utc_now() -> datetime:
    """Return an aware UTC timestamp suitable for application-side defaults."""

    return datetime.now(UTC)


class AuditMutationError(RuntimeError):
    """An audit row was changed or deleted instead of being superseded."""


class AuditEvent(Base):
    """One attributable privileged action in a per-tenant hash chain.

    The model has no update/delete service. Mapper guards catch ordinary ORM
    mutations; :func:`verify_audit_chain` additionally detects direct SQL
    tampering by reconstructing every hash from the stored facts.
    """

    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(
            "length(trim(action)) > 0",
            name="action_nonblank",
        ),
        CheckConstraint(
            "length(trim(actor_type)) > 0",
            name="actor_type_nonblank",
        ),
        CheckConstraint(
            "length(trim(resource_type)) > 0",
            name="resource_type_nonblank",
        ),
        CheckConstraint(
            "sequence_no >= 1",
            name="sequence_positive",
        ),
        CheckConstraint(
            "length(previous_hash) = 64 AND length(event_hash) = 64",
            name="hash_lengths",
        ),
        CheckConstraint(
            "reason IS NULL OR length(trim(reason)) > 0",
            name="reason_nonblank",
        ),
        CheckConstraint(
            "request_id IS NULL OR length(trim(request_id)) > 0",
            name="request_id_nonblank",
        ),
        UniqueConstraint(
            "tenant_id",
            "sequence_no",
            name="uq_audit_events_tenant_sequence",
        ),
        Index("ix_audit_events_resource", "tenant_id", "resource_type", "resource_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", name="fk_audit_events_tenant_id_tenants"),
        nullable=False,
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_person_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("persons.id", name="fk_audit_events_actor_person_id_persons"),
        nullable=True,
    )
    actor_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="person", server_default="person"
    )
    session_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("sessions.id", name="fk_audit_events_session_id_sessions"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(160), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    previous_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    @property
    def prev_hash(self) -> str:
        """Short alias used by some chain-verification callers."""

        return self.previous_hash

    @property
    def integrity_hash(self) -> str:
        """Descriptive alias for the current chain hash."""

        return self.event_hash

    @property
    def actor_id(self) -> UUID | None:
        """Generic actor alias while preserving the person-specific column."""

        return self.actor_person_id


@event.listens_for(AuditEvent, "before_update")
def _reject_audit_update(
    mapper: Mapper[Any],
    connection: Connection,
    target: AuditEvent,
) -> None:
    del mapper, connection, target
    raise AuditMutationError("audit events are append-only; write a superseding event")


@event.listens_for(AuditEvent, "before_delete")
def _reject_audit_delete(
    mapper: Mapper[Any],
    connection: Connection,
    target: AuditEvent,
) -> None:
    del mapper, connection, target
    raise AuditMutationError("audit events are append-only and cannot be deleted")


class AuditControlBase(DeclarativeBase):
    """Internal checkpoint metadata kept outside the mapped domain registry."""

    metadata = MetaData(naming_convention=Base.metadata.naming_convention)


class AuditChainHead(AuditControlBase):
    """Durable expected tail used to detect truncation and missing prefixes."""

    __tablename__ = "audit_chain_heads"
    __table_args__ = (
        CheckConstraint("sequence_no >= 1", name="sequence_positive"),
        CheckConstraint("length(event_hash) = 64", name="event_hash_length"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(Tenant.__table__.c.id, name="fk_audit_chain_heads_tenant_id_tenants"),
        primary_key=True,
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    event_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            AuditEvent.__table__.c.id,
            name="fk_audit_chain_heads_event_id_audit_events",
        ),
        nullable=False,
    )
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )


@event.listens_for(AuditChainHead, "before_delete")
def _reject_audit_checkpoint_delete(
    mapper: Mapper[Any],
    connection: Connection,
    target: AuditChainHead,
) -> None:
    del mapper, connection, target
    raise AuditMutationError("audit chain checkpoints cannot be deleted")


def audit_control_metadata() -> MetaData:
    """Return checkpoint metadata for migration and database parity tests."""

    return AuditControlBase.metadata


__all__ = [
    "AuditChainHead",
    "AuditControlBase",
    "AuditEvent",
    "AuditMutationError",
    "GENESIS_HASH",
    "audit_control_metadata",
    "utc_now",
]
