"""Append-only capability grants, independent of learner membership roles.

A grant is effective only while no revocation references it. There is deliberately
no mutable status column or role expansion here: transaction-scoped policy must
also validate the person, session, tenant and exact requested resource.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    event,
    func,
)
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapped, Mapper, mapped_column

from ac_platform.db.base import Base

PLATFORM_CAPABILITIES = frozenset(
    {
        "platform_access_manage",
        "platform_tenants_read",
        "platform_catalog_read",
        "platform_catalog_write",
        "platform_catalog_publish",
    }
)
STUDIO_CAPABILITIES = frozenset(
    {"catalog_read", "catalog_write", "catalog_publish", "learner_diagnose", "learning_review"}
)
SUPPORTED_CAPABILITIES = PLATFORM_CAPABILITIES | STUDIO_CAPABILITIES


def utc_now() -> datetime:
    return datetime.now(UTC)


class CapabilityHistoryMutationError(RuntimeError):
    """Capability history must be superseded with a new grant or revocation."""


class CapabilityGrant(Base):
    """One attributable, exact-scope capability; ``id`` is its command intent ID."""

    __tablename__ = "capability_grants"
    __table_args__ = (
        CheckConstraint(
            "permission IN ('platform_access_manage', 'platform_tenants_read', "
            "'platform_catalog_read', 'platform_catalog_write', 'platform_catalog_publish', "
            "'catalog_read', 'catalog_write', 'catalog_publish', 'learner_diagnose', "
            "'learning_review')",
            name="permission_supported",
        ),
        CheckConstraint("scope_kind IN ('platform', 'tenant', 'program')", name="scope_supported"),
        CheckConstraint(
            "(scope_kind = 'platform' AND tenant_id IS NULL AND program_id IS NULL) OR "
            "(scope_kind = 'tenant' AND tenant_id IS NOT NULL AND program_id IS NULL) OR "
            "(scope_kind = 'program' AND tenant_id IS NOT NULL AND program_id IS NOT NULL)",
            name="scope_shape",
        ),
        CheckConstraint(
            "(scope_kind = 'platform' AND permission IN ('platform_access_manage', "
            "'platform_tenants_read', 'platform_catalog_read', 'platform_catalog_write', "
            "'platform_catalog_publish')) OR "
            "(scope_kind IN ('tenant', 'program') AND permission IN ('catalog_read', "
            "'catalog_write', 'catalog_publish', 'learner_diagnose', 'learning_review'))",
            name="permission_scope",
        ),
        CheckConstraint("length(trim(reason)) > 0 AND length(reason) <= 500", name="reason_bound"),
        ForeignKeyConstraint(
            ["program_id", "tenant_id"],
            ["programs.id", "programs.tenant_id"],
            name="fk_capability_grants_program_tenant",
        ),
        UniqueConstraint("audit_event_id", name="uq_capability_grants_audit_event"),
        Index("ix_capability_grants_subject_scope", "subject_person_id", "scope_kind", "tenant_id"),
        Index("ix_capability_grants_program", "tenant_id", "program_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    subject_person_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("persons.id"), nullable=False
    )
    permission: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    tenant_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id"), nullable=True
    )
    program_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    granted_by_person_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("persons.id"), nullable=False
    )
    audit_event_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("audit_events.id"), nullable=False
    )
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )


class CapabilityRevocation(Base):
    """An immutable revocation; a later regrant is a new CapabilityGrant row."""

    __tablename__ = "capability_revocations"
    __table_args__ = (
        UniqueConstraint("grant_id", name="uq_capability_revocations_grant"),
        UniqueConstraint("audit_event_id", name="uq_capability_revocations_audit_event"),
        CheckConstraint("length(trim(reason)) > 0 AND length(reason) <= 500", name="reason_bound"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    grant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("capability_grants.id"), nullable=False
    )
    revoked_by_person_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("persons.id"), nullable=False
    )
    audit_event_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("audit_events.id"), nullable=False
    )
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )


@event.listens_for(CapabilityGrant, "before_update")
@event.listens_for(CapabilityGrant, "before_delete")
@event.listens_for(CapabilityRevocation, "before_update")
@event.listens_for(CapabilityRevocation, "before_delete")
def _reject_capability_history_mutation(
    mapper: Mapper[Any],
    connection: Connection,
    target: CapabilityGrant | CapabilityRevocation,
) -> None:
    del mapper, connection, target
    raise CapabilityHistoryMutationError("capability history is immutable; append a new command")


__all__ = [
    "PLATFORM_CAPABILITIES",
    "STUDIO_CAPABILITIES",
    "SUPPORTED_CAPABILITIES",
    "CapabilityGrant",
    "CapabilityHistoryMutationError",
    "CapabilityRevocation",
]
