"""Learner-owned Coaching state (owner decisions 10 Oct 2026: private by default).

Append-only. A rep's share state is the latest revision; nothing is updated or
deleted (supersede, never overwrite). Feedback carries no free text in phase 1
so account erasure needs no new purge path; "Add context" stays disabled.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base


class CoachingShareRevision(Base):
    """One tap: share (or stop sharing) my Coaching with my coaches and admins."""

    __tablename__ = "coaching_share_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "rep_person_id"], ["memberships.tenant_id", "memberships.person_id"]
        ),
        UniqueConstraint(
            "tenant_id", "rep_person_id", "revision", name="uq_coaching_share_revision"
        ),
        CheckConstraint("revision >= 1", name="positive_revision"),
        Index("ix_coaching_share_latest", "tenant_id", "rep_person_id", "revision"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    rep_person_id: Mapped[UUID] = mapped_column(Uuid)
    revision: Mapped[int] = mapped_column(Integer)
    shared: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CoachingFeedback(Base):
    """The learner's agreement with their current focus (never changes a score)."""

    __tablename__ = "coaching_feedback"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "person_id"], ["memberships.tenant_id", "memberships.person_id"]
        ),
        UniqueConstraint(
            "tenant_id", "person_id", "command_id", name="uq_coaching_feedback_command"
        ),
        CheckConstraint("agreement IN ('agree', 'not_completely')", name="agreement_supported"),
        CheckConstraint("length(focus_skill_id) BETWEEN 1 AND 64", name="focus_skill_bounds"),
        Index("ix_coaching_feedback_latest", "tenant_id", "person_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    command_id: Mapped[UUID] = mapped_column(Uuid)
    focus_skill_id: Mapped[str] = mapped_column(String(64))
    mission_origin_submission_id: Mapped[UUID] = mapped_column(Uuid)
    agreement: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
