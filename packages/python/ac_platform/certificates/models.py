"""SQLAlchemy models for immutable course-completion credentials.

Certificates are deliberately a narrow credential primitive. Every durable
certificate fact is bound to the learner's enrollment and to the complete
catalog owner identity, so a version UUID cannot be reused across catalog
scopes. Corrections and revocations are append-only, sequenced events.
"""

from __future__ import annotations

import re
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
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    event,
    func,
    select,
)
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.catalog.models import GLOBAL_CATALOG_OWNER_KEY
from ac_platform.certificates.digests import canonical_sha256
from ac_platform.db.base import Base

COURSE_COMPLETION_CERTIFICATE_TYPE = "course-completion"


def utc_now() -> datetime:
    """Return an aware UTC timestamp suitable for application defaults."""

    return datetime.now(UTC)


class CertificateEventType(StrEnum):
    """Append-only changes that can be made to a course-completion record."""

    ISSUED = "issued"
    CORRECTED = "corrected"
    REVOKED = "revoked"


class CertificateCommandStatus(StrEnum):
    """Durable state of a certificate idempotency claim."""

    PENDING = "pending"
    COMPLETED = "completed"


def _scope_checks(_table_name: str) -> tuple[CheckConstraint, ...]:
    return (
        CheckConstraint(
            "program_scope IN ('global', 'tenant')",
            name="scope_supported",
        ),
        CheckConstraint(
            "(program_scope = 'global' AND program_tenant_id IS NULL AND "
            f"program_owner_key = '{GLOBAL_CATALOG_OWNER_KEY.hex}') OR "
            "(program_scope = 'tenant' AND program_tenant_id IS NOT NULL AND "
            "program_owner_key = program_tenant_id)",
            name="scope_owner",
        ),
        CheckConstraint(
            "program_scope = 'global' OR program_tenant_id = tenant_id",
            name="tenant_owner",
        ),
    )


class CompletionSnapshot(Base):
    """An immutable, explainable evaluation of one enrolled course version."""

    __tablename__ = "completion_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_completion_snapshots_scoped_membership",
        ),
        ForeignKeyConstraint(
            [
                "enrollment_id",
                "tenant_id",
                "person_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
            ],
            [
                "enrollments.id",
                "enrollments.tenant_id",
                "enrollments.person_id",
                "enrollments.program_version_id",
                "enrollments.program_id",
                "enrollments.program_scope",
                "enrollments.program_owner_key",
            ],
            name="fk_completion_snapshots_enrollment_scope",
        ),
        ForeignKeyConstraint(
            ["program_version_id", "program_id", "program_scope", "program_owner_key"],
            [
                "program_versions.id",
                "program_versions.program_id",
                "program_versions.scope",
                "program_versions.owner_key",
            ],
            name="fk_completion_snapshots_program_version_scope",
        ),
        ForeignKeyConstraint(
            [
                "supersedes_snapshot_id",
                "tenant_id",
                "person_id",
                "enrollment_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
            ],
            [
                "completion_snapshots.id",
                "completion_snapshots.tenant_id",
                "completion_snapshots.person_id",
                "completion_snapshots.enrollment_id",
                "completion_snapshots.program_version_id",
                "completion_snapshots.program_id",
                "completion_snapshots.program_scope",
                "completion_snapshots.program_owner_key",
            ],
            name="fk_completion_snapshots_supersedes",
        ),
        UniqueConstraint(
            "id",
            "tenant_id",
            "person_id",
            "enrollment_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            name="uq_completion_snapshots_full_identity",
        ),
        CheckConstraint("required_activity_count >= 0", name="required_count_nonnegative"),
        CheckConstraint("completed_activity_count >= 0", name="completed_count_nonnegative"),
        CheckConstraint(
            "completed_activity_count <= required_activity_count",
            name="completed_count_within_denominator",
        ),
        CheckConstraint(
            "NOT is_complete OR completed_activity_count = required_activity_count",
            name="complete_count_matches",
        ),
        CheckConstraint(
            "NOT is_complete OR required_activity_count > 0",
            name="complete_requires_activity",
        ),
        CheckConstraint("length(snapshot_hash) = 64", name="snapshot_hash_sha256"),
        *_scope_checks("completion_snapshots"),
        Index(
            "ix_completion_snapshots_subject_version",
            "tenant_id",
            "person_id",
            "program_version_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    enrollment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_scope: Mapped[str] = mapped_column(String(16), nullable=False)
    program_tenant_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id"), nullable=True
    )
    program_owner_key: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    predicate_version: Mapped[str] = mapped_column(String(64), nullable=False)
    required_activity_count: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_activity_count: Mapped[int] = mapped_column(Integer, nullable=False)
    is_complete: Mapped[bool] = mapped_column(Boolean, nullable=False)
    required_activity_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    completed_activity_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    module_results: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    supersedes_snapshot_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)


class CourseCompletionCertificate(Base):
    """The original immutable course-completion certificate record."""

    __tablename__ = "course_completion_certificates"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_course_completion_certificates_scoped_membership",
        ),
        ForeignKeyConstraint(
            [
                "enrollment_id",
                "tenant_id",
                "person_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
            ],
            [
                "enrollments.id",
                "enrollments.tenant_id",
                "enrollments.person_id",
                "enrollments.program_version_id",
                "enrollments.program_id",
                "enrollments.program_scope",
                "enrollments.program_owner_key",
            ],
            name="fk_course_completion_certificates_enrollment_scope",
        ),
        ForeignKeyConstraint(
            ["program_version_id", "program_id", "program_scope", "program_owner_key"],
            [
                "program_versions.id",
                "program_versions.program_id",
                "program_versions.scope",
                "program_versions.owner_key",
            ],
            name="fk_course_completion_certificates_program_version_scope",
        ),
        ForeignKeyConstraint(
            [
                "original_completion_snapshot_id",
                "tenant_id",
                "person_id",
                "enrollment_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
            ],
            [
                "completion_snapshots.id",
                "completion_snapshots.tenant_id",
                "completion_snapshots.person_id",
                "completion_snapshots.enrollment_id",
                "completion_snapshots.program_version_id",
                "completion_snapshots.program_id",
                "completion_snapshots.program_scope",
                "completion_snapshots.program_owner_key",
            ],
            name="fk_course_completion_certificates_original_snapshot",
        ),
        UniqueConstraint(
            "id",
            "tenant_id",
            "person_id",
            "enrollment_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            name="uq_course_completion_certificates_full_identity",
        ),
        UniqueConstraint(
            "tenant_id",
            "person_id",
            "enrollment_id",
            "program_id",
            "program_version_id",
            "program_scope",
            "program_owner_key",
            "certificate_type",
            name="uq_course_completion_certificates_subject_version_type",
        ),
        CheckConstraint("certificate_type = 'course-completion'", name="type"),
        CheckConstraint(
            "idempotency_key IS NULL OR length(trim(idempotency_key)) > 0",
            name="idempotency_nonblank",
        ),
        *_scope_checks("course_completion_certificates"),
        Index("ix_course_completion_certificates_subject", "tenant_id", "person_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    enrollment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_scope: Mapped[str] = mapped_column(String(16), nullable=False)
    program_tenant_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id"), nullable=True
    )
    program_owner_key: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    certificate_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=COURSE_COMPLETION_CERTIFICATE_TYPE,
        server_default=COURSE_COMPLETION_CERTIFICATE_TYPE,
    )
    original_completion_snapshot_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )


class CertificateEvent(Base):
    """An append-only, digest-bound event in a certificate chain."""

    __tablename__ = "certificate_events"
    __table_args__ = (
        ForeignKeyConstraint(
            [
                "certificate_id",
                "tenant_id",
                "person_id",
                "enrollment_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
            ],
            [
                "course_completion_certificates.id",
                "course_completion_certificates.tenant_id",
                "course_completion_certificates.person_id",
                "course_completion_certificates.enrollment_id",
                "course_completion_certificates.program_version_id",
                "course_completion_certificates.program_id",
                "course_completion_certificates.program_scope",
                "course_completion_certificates.program_owner_key",
            ],
            name="fk_certificate_events_certificate_scope",
        ),
        ForeignKeyConstraint(
            [
                "completion_snapshot_id",
                "tenant_id",
                "person_id",
                "enrollment_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
            ],
            [
                "completion_snapshots.id",
                "completion_snapshots.tenant_id",
                "completion_snapshots.person_id",
                "completion_snapshots.enrollment_id",
                "completion_snapshots.program_version_id",
                "completion_snapshots.program_id",
                "completion_snapshots.program_scope",
                "completion_snapshots.program_owner_key",
            ],
            name="fk_certificate_events_snapshot_scope",
        ),
        ForeignKeyConstraint(
            [
                "supersedes_event_id",
                "certificate_id",
                "tenant_id",
                "person_id",
                "enrollment_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
            ],
            [
                "certificate_events.id",
                "certificate_events.certificate_id",
                "certificate_events.tenant_id",
                "certificate_events.person_id",
                "certificate_events.enrollment_id",
                "certificate_events.program_version_id",
                "certificate_events.program_id",
                "certificate_events.program_scope",
                "certificate_events.program_owner_key",
            ],
            name="fk_certificate_events_supersedes",
        ),
        ForeignKeyConstraint(
            ["actor_person_id"],
            ["persons.id"],
            name="fk_certificate_events_actor_person",
        ),
        UniqueConstraint(
            "id",
            "certificate_id",
            "tenant_id",
            "person_id",
            "enrollment_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            name="uq_certificate_events_full_identity",
        ),
        UniqueConstraint(
            "certificate_id",
            "sequence_no",
            name="uq_certificate_events_certificate_sequence_no",
        ),
        UniqueConstraint(
            "certificate_id",
            "idempotency_key",
            name="uq_certificate_events_certificate_idempotency",
        ),
        CheckConstraint(
            "event_type IN ('issued', 'corrected', 'revoked')",
            name="type",
        ),
        CheckConstraint(
            "event_type <> 'issued' OR completion_snapshot_id IS NOT NULL",
            name="issue_has_snapshot",
        ),
        CheckConstraint(
            "event_type <> 'corrected' OR completion_snapshot_id IS NOT NULL",
            name="correction_has_snapshot",
        ),
        CheckConstraint(
            "event_type = 'issued' OR actor_person_id IS NOT NULL",
            name="change_has_actor",
        ),
        CheckConstraint(
            "event_type = 'issued' OR (reason IS NOT NULL AND length(trim(reason)) > 0)",
            name="change_has_reason",
        ),
        CheckConstraint(
            "idempotency_key IS NULL OR length(trim(idempotency_key)) > 0",
            name="idempotency_nonblank",
        ),
        CheckConstraint("sequence_no >= 1", name="sequence_positive"),
        CheckConstraint("length(request_digest) = 64", name="request_digest_sha256"),
        *_scope_checks("certificate_events"),
        Index("ix_certificate_events_certificate_sequence", "certificate_id", "sequence_no"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    certificate_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    enrollment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_scope: Mapped[str] = mapped_column(String(16), nullable=False)
    program_tenant_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id"), nullable=True
    )
    program_owner_key: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    completion_snapshot_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    supersedes_event_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    actor_person_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("persons.id"), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )


class CertificateCommandIdempotency(Base):
    """Digest-bound command result whose IDs are relationally revalidated."""

    __tablename__ = "certificate_command_idempotency"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "actor_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_certificate_command_idempotency_actor_membership",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_certificate_command_idempotency_subject_membership",
        ),
        ForeignKeyConstraint(
            ["program_version_id", "program_id", "program_scope", "program_owner_key"],
            [
                "program_versions.id",
                "program_versions.program_id",
                "program_versions.scope",
                "program_versions.owner_key",
            ],
            name="fk_certificate_command_idempotency_program_version",
        ),
        ForeignKeyConstraint(
            [
                "result_certificate_id",
                "tenant_id",
                "person_id",
                "enrollment_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
            ],
            [
                "course_completion_certificates.id",
                "course_completion_certificates.tenant_id",
                "course_completion_certificates.person_id",
                "course_completion_certificates.enrollment_id",
                "course_completion_certificates.program_version_id",
                "course_completion_certificates.program_id",
                "course_completion_certificates.program_scope",
                "course_completion_certificates.program_owner_key",
            ],
            name="fk_certificate_command_idempotency_result_certificate",
        ),
        ForeignKeyConstraint(
            [
                "result_snapshot_id",
                "tenant_id",
                "person_id",
                "enrollment_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
            ],
            [
                "completion_snapshots.id",
                "completion_snapshots.tenant_id",
                "completion_snapshots.person_id",
                "completion_snapshots.enrollment_id",
                "completion_snapshots.program_version_id",
                "completion_snapshots.program_id",
                "completion_snapshots.program_scope",
                "completion_snapshots.program_owner_key",
            ],
            name="fk_certificate_command_idempotency_result_snapshot",
        ),
        ForeignKeyConstraint(
            [
                "result_event_id",
                "result_certificate_id",
                "tenant_id",
                "person_id",
                "enrollment_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
            ],
            [
                "certificate_events.id",
                "certificate_events.certificate_id",
                "certificate_events.tenant_id",
                "certificate_events.person_id",
                "certificate_events.enrollment_id",
                "certificate_events.program_version_id",
                "certificate_events.program_id",
                "certificate_events.program_scope",
                "certificate_events.program_owner_key",
            ],
            name="fk_certificate_command_idempotency_result_event",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_certificate_command_idempotency_tenant_id_id"),
        UniqueConstraint(
            "tenant_id",
            "actor_person_id",
            "operation",
            "idempotency_key",
            name="uq_certificate_command_idempotency_scope_key",
        ),
        CheckConstraint(
            "operation IN ('certificate_issue', 'certificate_correct', 'certificate_revoke')",
            name="operation_allowed",
        ),
        CheckConstraint("status IN ('pending', 'completed')", name="status"),
        CheckConstraint("length(trim(idempotency_key)) > 0", name="idempotency_key_nonblank"),
        CheckConstraint("length(request_digest) = 64", name="request_digest_sha256"),
        CheckConstraint(
            "(status = 'pending' AND result_certificate_id IS NULL "
            "AND result_snapshot_id IS NULL AND result_event_id IS NULL "
            "AND completed_at IS NULL) OR "
            "(status = 'completed' AND result_certificate_id IS NOT NULL "
            "AND result_event_id IS NOT NULL AND completed_at IS NOT NULL "
            "AND ((operation = 'certificate_revoke' AND result_snapshot_id IS NULL) "
            "OR (operation IN ('certificate_issue', 'certificate_correct') "
            "AND result_snapshot_id IS NOT NULL)))",
            name="result_state_complete",
        ),
        *_scope_checks("certificate_command_idempotency"),
        Index(
            "ix_certificate_command_idempotency_result",
            "tenant_id",
            "result_certificate_id",
            "result_event_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    actor_person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    enrollment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
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
        default=CertificateCommandStatus.PENDING.value,
        server_default=CertificateCommandStatus.PENDING.value,
    )
    result_certificate_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    result_snapshot_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    result_event_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def _event_digest(target: CertificateEvent) -> str:
    payload = {
        "certificate_id": str(target.certificate_id),
        "tenant_id": str(target.tenant_id),
        "person_id": str(target.person_id),
        "enrollment_id": str(target.enrollment_id),
        "program_id": str(target.program_id),
        "program_version_id": str(target.program_version_id),
        "program_scope": target.program_scope,
        "program_tenant_id": (
            str(target.program_tenant_id) if target.program_tenant_id is not None else None
        ),
        "program_owner_key": str(target.program_owner_key),
        "event_type": target.event_type,
        "completion_snapshot_id": (
            str(target.completion_snapshot_id)
            if target.completion_snapshot_id is not None
            else None
        ),
        "supersedes_event_id": (
            str(target.supersedes_event_id) if target.supersedes_event_id is not None else None
        ),
        "actor_person_id": (
            str(target.actor_person_id) if target.actor_person_id is not None else None
        ),
        "reason": target.reason,
        "provenance": target.provenance,
        "idempotency_key": target.idempotency_key,
    }
    return canonical_sha256(payload)


def _validate_event_digest(target: CertificateEvent) -> None:
    digest = target.request_digest
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError("certificate event request_digest must be lowercase SHA-256 hex")
    if digest != _event_digest(target):
        raise ValueError("certificate event request_digest does not match canonical event contents")


@event.listens_for(CertificateEvent, "before_insert")
def _assign_event_sequence_and_digest(
    _mapper: Any,
    connection: Connection,
    target: CertificateEvent,
) -> None:
    if target.sequence_no is None:
        maximum = connection.execute(
            select(func.max(CertificateEvent.sequence_no)).where(
                CertificateEvent.certificate_id == target.certificate_id
            )
        ).scalar_one()
        target.sequence_no = int(maximum or 0) + 1
    if not target.request_digest:
        target.request_digest = _event_digest(target)
    _validate_event_digest(target)


def _reject_immutable_change(*_: Any) -> None:
    raise ValueError("certificate records are immutable; append a certificate event instead")


for _immutable_model in (CompletionSnapshot, CourseCompletionCertificate, CertificateEvent):
    event.listen(_immutable_model, "before_update", _reject_immutable_change)
    event.listen(_immutable_model, "before_delete", _reject_immutable_change)


__all__ = [
    "COURSE_COMPLETION_CERTIFICATE_TYPE",
    "CertificateCommandIdempotency",
    "CertificateCommandStatus",
    "CertificateEvent",
    "CertificateEventType",
    "CompletionSnapshot",
    "CourseCompletionCertificate",
    "utc_now",
]
