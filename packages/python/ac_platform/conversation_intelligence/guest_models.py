"""Non-login processing identity, bounded leases and immutable source ownership."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
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
