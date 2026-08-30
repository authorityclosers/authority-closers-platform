"""SQLAlchemy models for explicit, audited course access.

Enrollment is deliberately a small capability boundary.  A row in
``entitlements`` is usable only when it points at an enrollment and an
immutable provenance record.  The source allow-list is intentionally narrow:
the public learner command and the separately named manual-grant seam.
"""

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
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    event,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.catalog.models import GLOBAL_CATALOG_OWNER_KEY
from ac_platform.db.base import Base


def utc_now() -> datetime:
    """Return an aware UTC timestamp suitable for application defaults."""

    return datetime.now(UTC)


class EnrollmentStatus(StrEnum):
    """Lifecycle state of the canonical enrollment record."""

    ACTIVE = "active"
    REVOKED = "revoked"


class EntitlementStatus(StrEnum):
    """Lifecycle state of the access capability derived from an enrollment."""

    ACTIVE = "active"
    REVOKED = "revoked"


class EnrollmentSource(StrEnum):
    """Only sources that may create access in the G1 slice."""

    FREE_SELF = "free_self"
    MANUAL_GRANT = "manual_grant"


class CommandStatus(StrEnum):
    """Durable idempotency state for a transaction-oriented command."""

    PENDING = "pending"
    COMPLETED = "completed"


class EnrollmentEligibilityFact(Base):
    """Canonical server-owned eligibility for one learner and catalog version."""

    __tablename__ = "enrollment_eligibility_facts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_enrollment_eligibility_facts_membership",
        ),
        ForeignKeyConstraint(
            ["program_version_id", "program_id", "program_scope", "program_owner_key"],
            [
                "program_versions.id",
                "program_versions.program_id",
                "program_versions.scope",
                "program_versions.owner_key",
            ],
            name="fk_enrollment_eligibility_facts_program_version",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_enrollment_eligibility_facts_tenant_id_id"),
        UniqueConstraint(
            "tenant_id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            name="uq_enrollment_eligibility_facts_subject_version",
        ),
        CheckConstraint(
            "program_scope IN ('global', 'tenant')",
            name="program_scope_supported",
        ),
        CheckConstraint(
            "(program_scope = 'global' AND program_tenant_id IS NULL AND "
            f"program_owner_key = '{GLOBAL_CATALOG_OWNER_KEY.hex}') OR "
            "(program_scope = 'tenant' AND program_tenant_id IS NOT NULL AND "
            "program_owner_key = program_tenant_id)",
            name="program_scope_owner_match",
        ),
        CheckConstraint(
            "program_scope = 'global' OR program_tenant_id = tenant_id",
            name="tenant_program_owner_match",
        ),
        CheckConstraint("length(trim(policy_version)) > 0", name="policy_version_nonblank"),
        CheckConstraint(
            "valid_until IS NULL OR valid_until > evaluated_at",
            name="valid_window",
        ),
        Index(
            "ix_enrollment_eligibility_facts_subject_version",
            "tenant_id",
            "person_id",
            "program_version_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_scope: Mapped[str] = mapped_column(String(16), nullable=False)
    program_tenant_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id"), nullable=True
    )
    program_owner_key: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    age_gate_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    eligibility_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    prerequisites_satisfied: Mapped[bool] = mapped_column(Boolean, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(128), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
    )
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Enrollment(Base):
    """A tenant-scoped learner enrollment pinned to one program version."""

    __tablename__ = "enrollments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_enrollments_tenant_person_membership",
        ),
        ForeignKeyConstraint(
            ["program_version_id", "program_id", "program_scope", "program_owner_key"],
            [
                "program_versions.id",
                "program_versions.program_id",
                "program_versions.scope",
                "program_versions.owner_key",
            ],
            name="fk_enrollments_program_version_scope",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_enrollments_tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "person_id",
            "program_version_id",
            name="uq_enrollments_subject_program_version",
        ),
        UniqueConstraint(
            "tenant_id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            name="uq_enrollments_tenant_person_program_version",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            name="uq_enrollments_scoped_full_identity",
        ),
        UniqueConstraint(
            "id",
            "tenant_id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            name="uq_enrollments_full_identity",
        ),
        CheckConstraint(
            "source IN ('free_self', 'manual_grant')",
            name="source_allowed",
        ),
        CheckConstraint(
            "status IN ('active', 'revoked')",
            name="status",
        ),
        CheckConstraint(
            "program_scope IN ('global', 'tenant')",
            name="program_scope_supported",
        ),
        CheckConstraint(
            "(program_scope = 'global' AND program_tenant_id IS NULL AND "
            f"program_owner_key = '{GLOBAL_CATALOG_OWNER_KEY.hex}') OR "
            "(program_scope = 'tenant' AND program_tenant_id IS NOT NULL AND "
            "program_owner_key = program_tenant_id)",
            name="program_scope_owner_match",
        ),
        CheckConstraint(
            "program_scope = 'global' OR program_tenant_id = tenant_id",
            name="tenant_program_owner_match",
        ),
        Index("ix_enrollments_person_tenant", "person_id", "tenant_id"),
        Index("ix_enrollments_program_version", "tenant_id", "program_version_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_scope: Mapped[str] = mapped_column(String(16), nullable=False)
    program_tenant_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id"), nullable=True
    )
    program_owner_key: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=EnrollmentStatus.ACTIVE.value,
        server_default=EnrollmentStatus.ACTIVE.value,
    )
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
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


class CommandIdempotency(Base):
    """The request claim and result for one actor/tenant command key."""

    __tablename__ = "command_idempotency"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "actor_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_command_idempotency_actor_membership",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "subject_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_command_idempotency_subject_membership",
        ),
        ForeignKeyConstraint(
            ["program_version_id", "program_id", "program_scope", "program_owner_key"],
            [
                "program_versions.id",
                "program_versions.program_id",
                "program_versions.scope",
                "program_versions.owner_key",
            ],
            name="fk_command_idempotency_program_version",
        ),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "result_enrollment_id",
                "subject_person_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
            ],
            [
                "enrollments.tenant_id",
                "enrollments.id",
                "enrollments.person_id",
                "enrollments.program_version_id",
                "enrollments.program_id",
                "enrollments.program_scope",
                "enrollments.program_owner_key",
            ],
            name="fk_command_idempotency_result_enrollment",
        ),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "result_entitlement_id",
                "subject_person_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
            ],
            [
                "entitlements.tenant_id",
                "entitlements.id",
                "entitlements.person_id",
                "entitlements.program_version_id",
                "entitlements.program_id",
                "entitlements.program_scope",
                "entitlements.program_owner_key",
            ],
            name="fk_command_idempotency_result_entitlement",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "result_provenance_id",
                "subject_person_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
            ],
            [
                "enrollment_provenance.tenant_id",
                "enrollment_provenance.id",
                "enrollment_provenance.person_id",
                "enrollment_provenance.program_version_id",
                "enrollment_provenance.program_id",
                "enrollment_provenance.program_scope",
                "enrollment_provenance.program_owner_key",
            ],
            name="fk_command_idempotency_result_provenance",
            use_alter=True,
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_command_idempotency_tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "actor_person_id",
            "operation",
            "idempotency_key",
            name="uq_command_idempotency_scope_key",
        ),
        CheckConstraint(
            "operation IN ('enroll_free', 'grant_manual')",
            name="operation_allowed",
        ),
        CheckConstraint(
            "status IN ('pending', 'completed')",
            name="status",
        ),
        CheckConstraint(
            "length(trim(idempotency_key)) > 0",
            name="idempotency_key_nonblank",
        ),
        CheckConstraint(
            "length(request_digest) = 64",
            name="request_digest_sha256",
        ),
        CheckConstraint(
            "(status = 'pending' AND result_enrollment_id IS NULL "
            "AND result_entitlement_id IS NULL AND result_provenance_id IS NULL "
            "AND completed_at IS NULL) OR "
            "(status = 'completed' AND result_enrollment_id IS NOT NULL "
            "AND result_entitlement_id IS NOT NULL AND result_provenance_id IS NOT NULL "
            "AND completed_at IS NOT NULL)",
            name="result_state_complete",
        ),
        CheckConstraint(
            "program_scope IN ('global', 'tenant')",
            name="program_scope_supported",
        ),
        CheckConstraint(
            "(program_scope = 'global' AND program_tenant_id IS NULL AND "
            f"program_owner_key = '{GLOBAL_CATALOG_OWNER_KEY.hex}') OR "
            "(program_scope = 'tenant' AND program_tenant_id IS NOT NULL AND "
            "program_owner_key = program_tenant_id)",
            name="program_scope_owner_match",
        ),
        CheckConstraint(
            "program_scope = 'global' OR program_tenant_id = tenant_id",
            name="tenant_program_owner_match",
        ),
        Index("ix_command_idempotency_result_enrollment", "tenant_id", "result_enrollment_id"),
        Index("ix_command_idempotency_result_entitlement", "tenant_id", "result_entitlement_id"),
        Index("ix_command_idempotency_result_provenance", "tenant_id", "result_provenance_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    actor_person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    subject_person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_scope: Mapped[str] = mapped_column(String(16), nullable=False)
    program_tenant_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id"), nullable=True
    )
    program_owner_key: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=CommandStatus.PENDING.value,
        server_default=CommandStatus.PENDING.value,
    )
    result_enrollment_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    result_entitlement_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    result_provenance_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EnrollmentProvenance(Base):
    """Immutable audit evidence explaining why access was created."""

    __tablename__ = "enrollment_provenance"
    __table_args__ = (
        ForeignKeyConstraint(
            [
                "tenant_id",
                "enrollment_id",
                "person_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
            ],
            [
                "enrollments.tenant_id",
                "enrollments.id",
                "enrollments.person_id",
                "enrollments.program_version_id",
                "enrollments.program_id",
                "enrollments.program_scope",
                "enrollments.program_owner_key",
            ],
            name="fk_enrollment_provenance_enrollment",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_enrollment_provenance_subject_membership",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "command_idempotency_id"],
            ["command_idempotency.tenant_id", "command_idempotency.id"],
            name="fk_enrollment_provenance_command",
        ),
        ForeignKeyConstraint(
            ["actor_person_id"],
            ["persons.id"],
            name="fk_enrollment_provenance_actor_person",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_enrollment_provenance_tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            name="uq_enrollment_provenance_full_identity",
        ),
        CheckConstraint(
            "source IN ('free_self', 'manual_grant')",
            name="source_allowed",
        ),
        CheckConstraint(
            "source <> 'free_self' OR actor_person_id = person_id",
            name="free_source_requires_self",
        ),
        CheckConstraint(
            "source <> 'manual_grant' OR (reason IS NOT NULL AND length(trim(reason)) > 0)",
            name="manual_source_requires_reason",
        ),
        CheckConstraint(
            "program_scope IN ('global', 'tenant')",
            name="program_scope_supported",
        ),
        CheckConstraint(
            "(program_scope = 'global' AND program_tenant_id IS NULL AND "
            f"program_owner_key = '{GLOBAL_CATALOG_OWNER_KEY.hex}') OR "
            "(program_scope = 'tenant' AND program_tenant_id IS NOT NULL AND "
            "program_owner_key = program_tenant_id)",
            name="program_scope_owner_match",
        ),
        CheckConstraint(
            "program_scope = 'global' OR program_tenant_id = tenant_id",
            name="tenant_program_owner_match",
        ),
        Index("ix_enrollment_provenance_enrollment", "tenant_id", "enrollment_id"),
        Index("ix_enrollment_provenance_subject", "tenant_id", "person_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    enrollment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    actor_person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_scope: Mapped[str] = mapped_column(String(16), nullable=False)
    program_tenant_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id"), nullable=True
    )
    program_owner_key: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    command_idempotency_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    audit_event_name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default="audit.enrollment.created.v1",
        server_default="audit.enrollment.created.v1",
    )
    policy_inputs: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
    )
    controlled_gaps: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )


class Entitlement(Base):
    """The explicit access capability used by protected learning operations."""

    __tablename__ = "entitlements"
    __table_args__ = (
        ForeignKeyConstraint(
            [
                "tenant_id",
                "enrollment_id",
                "person_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
            ],
            [
                "enrollments.tenant_id",
                "enrollments.id",
                "enrollments.person_id",
                "enrollments.program_version_id",
                "enrollments.program_id",
                "enrollments.program_scope",
                "enrollments.program_owner_key",
            ],
            name="fk_entitlements_enrollment",
        ),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "person_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
            ],
            [
                "enrollments.tenant_id",
                "enrollments.person_id",
                "enrollments.program_version_id",
                "enrollments.program_id",
                "enrollments.program_scope",
                "enrollments.program_owner_key",
            ],
            name="fk_entitlements_subject_program_enrollment",
        ),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "provenance_id",
                "person_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
            ],
            [
                "enrollment_provenance.tenant_id",
                "enrollment_provenance.id",
                "enrollment_provenance.person_id",
                "enrollment_provenance.program_version_id",
                "enrollment_provenance.program_id",
                "enrollment_provenance.program_scope",
                "enrollment_provenance.program_owner_key",
            ],
            name="fk_entitlements_provenance",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_entitlements_tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            name="uq_entitlements_full_identity",
        ),
        UniqueConstraint(
            "tenant_id",
            "enrollment_id",
            name="uq_entitlements_enrollment",
        ),
        UniqueConstraint(
            "tenant_id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            name="uq_entitlements_subject_program_version",
        ),
        CheckConstraint(
            "status IN ('active', 'revoked')",
            name="status",
        ),
        CheckConstraint(
            "program_scope IN ('global', 'tenant')",
            name="program_scope_supported",
        ),
        CheckConstraint(
            "(program_scope = 'global' AND program_tenant_id IS NULL AND "
            f"program_owner_key = '{GLOBAL_CATALOG_OWNER_KEY.hex}') OR "
            "(program_scope = 'tenant' AND program_tenant_id IS NOT NULL AND "
            "program_owner_key = program_tenant_id)",
            name="program_scope_owner_match",
        ),
        CheckConstraint(
            "program_scope = 'global' OR program_tenant_id = tenant_id",
            name="tenant_program_owner_match",
        ),
        Index("ix_entitlements_subject", "tenant_id", "person_id"),
        Index("ix_entitlements_program_version", "tenant_id", "program_version_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    enrollment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    provenance_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_scope: Mapped[str] = mapped_column(String(16), nullable=False)
    program_tenant_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id"), nullable=True
    )
    program_owner_key: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=EntitlementStatus.ACTIVE.value,
        server_default=EntitlementStatus.ACTIVE.value,
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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


class EnrollmentProvenanceMutationError(RuntimeError):
    """Provenance is evidence and may only be appended, never rewritten."""


@event.listens_for(EnrollmentProvenance, "before_update")
def _reject_provenance_update(*_: Any) -> None:
    raise EnrollmentProvenanceMutationError(
        "enrollment provenance is append-only; write a new enrollment instead"
    )


@event.listens_for(EnrollmentProvenance, "before_delete")
def _reject_provenance_delete(*_: Any) -> None:
    raise EnrollmentProvenanceMutationError(
        "enrollment provenance is append-only and cannot be deleted"
    )


__all__ = [
    "CommandIdempotency",
    "CommandStatus",
    "Enrollment",
    "EnrollmentEligibilityFact",
    "EnrollmentProvenance",
    "EnrollmentProvenanceMutationError",
    "EnrollmentSource",
    "EnrollmentStatus",
    "Entitlement",
    "EntitlementStatus",
    "utc_now",
]
