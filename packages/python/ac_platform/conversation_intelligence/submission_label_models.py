"""Private, owner-authored labels for retained acquisition submissions.

The label history is separate from immutable upload and report provenance. Its
content is physically removed when the underlying source is erased.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
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


class ConversationSubmissionLabelRevision(Base):
    """One append-only custom label revision for a saved call."""

    __tablename__ = "conversation_submission_label_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "submission_id"],
            [
                "conversation_guest_submissions.tenant_id",
                "conversation_guest_submissions.submission_id",
            ],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "actor_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
        ),
        UniqueConstraint(
            "tenant_id", "submission_id", "revision", name="uq_submission_label_revision"
        ),
        CheckConstraint("revision >= 1", name="positive_revision"),
        CheckConstraint(
            "display_name IS NULL OR (length(trim(display_name)) > 0 "
            "AND length(display_name) <= 120)",
            name="display_name_bounds",
        ),
        Index("ix_submission_label_latest", "tenant_id", "submission_id", "revision"),
        Index("ix_submission_label_actor", "tenant_id", "actor_person_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    submission_id: Mapped[UUID] = mapped_column(Uuid)
    revision: Mapped[int] = mapped_column(Integer)
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    actor_person_id: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
