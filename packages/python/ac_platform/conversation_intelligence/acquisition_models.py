"""Private guest admission and append-only acquisition usage, independent of identity.

A visitor is not a verified Person or a tenant membership. Claiming a visitor
adds a link to an existing canonical person; it never rewrites the original
usage owner, creates a second identity, or clears previously incurred usage.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base


class ConversationVisitor(Base):
    __tablename__ = "conversation_visitors"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id"),
        UniqueConstraint("token_hash"),
        CheckConstraint("length(token_hash) = 32", name="token_length"),
        CheckConstraint("expires_at > created_at", name="bounded_expiry"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"))
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConversationVisitorClaim(Base):
    __tablename__ = "conversation_visitor_claims"
    __table_args__ = (
        Index("ix_conversation_visitor_claims_person", "tenant_id", "person_id"),
        ForeignKeyConstraint(
            ["visitor_id", "tenant_id"],
            ["conversation_visitors.id", "conversation_visitors.tenant_id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
        ),
    )
    visitor_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    session_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("sessions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConversationAcquisitionUsage(Base):
    """One admitted source; uncertain provider outcomes remain charged/reserved.

    A settlement is a separate row. A new login, browser or policy revision
    cannot mutate this row or reopen its source reservation.
    """

    __tablename__ = "conversation_acquisition_usage"
    __table_args__ = (
        Index("ix_conversation_acquisition_usage_person", "tenant_id", "person_id"),
        Index("ix_conversation_acquisition_usage_visitor", "tenant_id", "visitor_id"),
        UniqueConstraint("tenant_id", "submission_id"),
        ForeignKeyConstraint(
            ["visitor_id", "tenant_id"],
            ["conversation_visitors.id", "conversation_visitors.tenant_id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
        ),
        CheckConstraint("(visitor_id IS NULL) <> (person_id IS NULL)", name="one_owner"),
        CheckConstraint("reserved_seconds BETWEEN 1 AND 6000", name="duration_bound"),
        CheckConstraint("length(source_sha256) = 64", name="source_hash"),
        CheckConstraint("length(duration_evidence_sha256) = 64", name="duration_evidence"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"))
    visitor_id: Mapped[UUID | None] = mapped_column(Uuid)
    person_id: Mapped[UUID | None] = mapped_column(Uuid)
    submission_id: Mapped[UUID] = mapped_column(Uuid)
    source_sha256: Mapped[str] = mapped_column(String(64))
    duration_evidence_sha256: Mapped[str] = mapped_column(String(64))
    reserved_seconds: Mapped[int] = mapped_column(Integer)
    policy_revision: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConversationAcquisitionSettlement(Base):
    __tablename__ = "conversation_acquisition_settlements"
    __table_args__ = (
        CheckConstraint("charged_seconds BETWEEN 0 AND 6000", name="duration_bound"),
        CheckConstraint("length(receipt_sha256) = 64", name="receipt_hash"),
        CheckConstraint("kind IN ('completed', 'no_work_performed')", name="kind"),
        CheckConstraint(
            "kind <> 'no_work_performed' OR charged_seconds = 0", name="no_work_charge"
        ),
    )
    usage_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("conversation_acquisition_usage.id"), primary_key=True
    )
    charged_seconds: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32))
    receipt_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
