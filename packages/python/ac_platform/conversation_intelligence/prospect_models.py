"""Tenant-scoped, person-authored prospect identity and explicit call history."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base


def _member_fk(column: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["tenant_id", column],
        ["memberships.tenant_id", "memberships.person_id"],
        name=f"fk_prospect_{column}_member",
        ondelete="RESTRICT",
    )


class ConversationProspect(Base):
    __tablename__ = "conversation_prospects"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_prospect_tenant_id"),
        _member_fk("created_by_person_id"),
        _member_fk("owner_person_id"),
        CheckConstraint("revision >= 1", name="positive_revision"),
        CheckConstraint("length(trim(display_name)) BETWEEN 1 AND 160", name="name_bounds"),
        Index("ix_prospect_created", "tenant_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="RESTRICT"))
    display_name: Mapped[str] = mapped_column(String(160))
    created_by_person_id: Mapped[UUID] = mapped_column(Uuid)
    owner_person_id: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revision: Mapped[int] = mapped_column(Integer)


class ConversationProspectMembership(Base):
    __tablename__ = "conversation_prospect_memberships"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "prospect_id"],
            ["conversation_prospects.tenant_id", "conversation_prospects.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "submission_id"],
            [
                "conversation_guest_submissions.tenant_id",
                "conversation_guest_submissions.submission_id",
            ],
            ondelete="RESTRICT",
        ),
        _member_fk("linked_by_person_id"),
        _member_fk("ended_by_person_id"),
        CheckConstraint(
            "(ended_at IS NULL AND ended_reason IS NULL AND ended_by_person_id IS NULL) OR "
            "(ended_at IS NOT NULL AND ended_at >= created_at AND ended_reason IS NOT NULL AND "
            "ended_reason IN ('unlinked', 'superseded', 'source_erasure'))",
            name="end_shape",
        ),
        Index(
            "uq_prospect_active_call",
            "tenant_id",
            "submission_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
            sqlite_where=text("ended_at IS NULL"),
        ),
        Index(
            "ix_prospect_membership_read", "tenant_id", "prospect_id", "ended_at", "submission_id"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    prospect_id: Mapped[UUID] = mapped_column(Uuid)
    submission_id: Mapped[UUID] = mapped_column(Uuid)
    linked_by_person_id: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_reason: Mapped[str | None] = mapped_column(String(32))
    ended_by_person_id: Mapped[UUID | None] = mapped_column(Uuid)
