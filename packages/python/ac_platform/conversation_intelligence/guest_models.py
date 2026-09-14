"""Non-login processing identity, bounded leases and immutable source ownership."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base


class ConversationProcessingPrincipal(Base):
    __tablename__ = "conversation_processing_principals"
    __table_args__ = (
        UniqueConstraint("tenant_id"),
        UniqueConstraint("person_id"),
        UniqueConstraint("id", "tenant_id", "person_id"),
        ForeignKeyConstraint(
            ["tenant_id", "person_id"], ["memberships.tenant_id", "memberships.person_id"]
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    operator_reference: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConversationProcessingLease(Base):
    __tablename__ = "conversation_processing_leases"
    __table_args__ = (
        UniqueConstraint("usage_id"),
        UniqueConstraint("id", "tenant_id", "person_id"),
        ForeignKeyConstraint(
            ["principal_id", "tenant_id", "person_id"],
            [
                "conversation_processing_principals.id",
                "conversation_processing_principals.tenant_id",
                "conversation_processing_principals.person_id",
            ],
        ),
        CheckConstraint("expires_at > created_at", name="bounded_expiry"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    principal_id: Mapped[UUID] = mapped_column(Uuid)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    usage_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("conversation_acquisition_usage.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConversationProcessingContinuation(Base):
    """Owner-authorized, append-only recovery for an expired processing lease.

    This row extends authority for one exact saved source for a short window;
    it never changes the original lease, acquisition usage, quota, or request
    allowance.  The owner columns snapshot the owner that authenticated the
    request so a later visitor claim cannot transfer a visitor grant.
    """

    __tablename__ = "conversation_processing_continuations"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", "person_id"),
        ForeignKeyConstraint(
            ["processing_lease_id", "tenant_id", "person_id"],
            [
                "conversation_processing_leases.id",
                "conversation_processing_leases.tenant_id",
                "conversation_processing_leases.person_id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "submission_id"],
            [
                "conversation_guest_submissions.tenant_id",
                "conversation_guest_submissions.submission_id",
            ],
        ),
        ForeignKeyConstraint(
            ["owner_visitor_id", "tenant_id"],
            ["conversation_visitors.id", "conversation_visitors.tenant_id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "owner_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
        ),
        ForeignKeyConstraint(["usage_id"], ["conversation_acquisition_usage.id"]),
        ForeignKeyConstraint(["recording_id"], ["conversation_recordings.id"]),
        CheckConstraint(
            "(owner_person_id IS NULL) <> (owner_visitor_id IS NULL)", name="one_owner"
        ),
        CheckConstraint("source_revision >= 1 AND generation >= 1", name="positive_source"),
        CheckConstraint("length(source_sha256) = 64", name="source_hash"),
        CheckConstraint("expires_at > created_at", name="bounded_expiry"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    submission_id: Mapped[UUID] = mapped_column(Uuid)
    recording_id: Mapped[UUID] = mapped_column(Uuid)
    processing_lease_id: Mapped[UUID] = mapped_column(Uuid)
    usage_id: Mapped[UUID] = mapped_column(Uuid)
    owner_person_id: Mapped[UUID | None] = mapped_column(Uuid)
    owner_visitor_id: Mapped[UUID | None] = mapped_column(Uuid)
    source_sha256: Mapped[str] = mapped_column(String(64))
    source_revision: Mapped[int] = mapped_column(Integer)
    generation: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConversationGuestSubmission(Base):
    __tablename__ = "conversation_guest_submissions"
    __table_args__ = (
        UniqueConstraint("recording_id"),
        UniqueConstraint("processing_lease_id"),
        UniqueConstraint("usage_id"),
        ForeignKeyConstraint(
            ["recording_id", "tenant_id", "person_id"],
            [
                "conversation_recordings.id",
                "conversation_recordings.tenant_id",
                "conversation_recordings.person_id",
            ],
        ),
        ForeignKeyConstraint(
            ["processing_lease_id", "tenant_id", "person_id"],
            [
                "conversation_processing_leases.id",
                "conversation_processing_leases.tenant_id",
                "conversation_processing_leases.person_id",
            ],
        ),
        CheckConstraint("length(source_sha256) = 64", name="source_hash"),
    )
    tenant_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    submission_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    recording_id: Mapped[UUID] = mapped_column(Uuid)
    processing_lease_id: Mapped[UUID] = mapped_column(Uuid)
    usage_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("conversation_acquisition_usage.id"))
    source_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
