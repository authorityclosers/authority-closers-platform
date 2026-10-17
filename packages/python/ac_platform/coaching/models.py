"""Learner-owned Coaching state (owner decisions 10 Oct 2026: private by default).

Share revisions and feedback are append-only: a rep's share state is the
latest revision; nothing is updated or deleted (supersede, never overwrite).
Learner context is the one free-text record: never edited, and erased with the
account (identity/sales_xray_profile.erase_sales_xray_profile).
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
    Text,
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


class CoachingLearnerContext(Base):
    """What the learner adds about their focus ("Add context", spec 12.2/12.6).

    Free text, so it is erased with the account; otherwise never edited. The
    newest note for the current focus is shown back with the likely reason.
    """

    __tablename__ = "coaching_learner_context"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "person_id"], ["memberships.tenant_id", "memberships.person_id"]
        ),
        UniqueConstraint(
            "tenant_id", "person_id", "command_id", name="uq_coaching_learner_context_command"
        ),
        CheckConstraint("length(focus_skill_id) BETWEEN 1 AND 64", name="context_skill_bounds"),
        CheckConstraint("length(context) BETWEEN 1 AND 1000", name="context_bounds"),
        Index("ix_coaching_learner_context_latest", "tenant_id", "person_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    command_id: Mapped[UUID] = mapped_column(Uuid)
    focus_skill_id: Mapped[str] = mapped_column(String(64))
    mission_origin_submission_id: Mapped[UUID] = mapped_column(Uuid)
    context: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
