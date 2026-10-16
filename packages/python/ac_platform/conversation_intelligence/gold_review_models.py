"""Standing reviewer authority and erasable, version-bound gold judgements."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base


class GoldReviewer(Base):
    __tablename__ = "conversation_gold_reviewers"

    person_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("persons.id"), primary_key=True)
    designated_by: Mapped[UUID] = mapped_column(Uuid, ForeignKey("persons.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GoldAssignment(Base):
    __tablename__ = "conversation_gold_assignments"
    __table_args__ = (
        UniqueConstraint("recording_id", "reviewer_id", name="uq_gold_assignment_call_reviewer"),
    )

    assignment_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("conversation_review_assignments.id"), primary_key=True
    )
    recording_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("conversation_recordings.id"))
    reviewer_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("persons.id"))
    review_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("conversation_pointer_reviews.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GoldRow(Base):
    __tablename__ = "conversation_gold_rows"
    __table_args__ = (
        UniqueConstraint("assignment_id", "request_key", name="uq_gold_row_request"),
        UniqueConstraint("supersedes_id", name="uq_gold_row_supersedes"),
        CheckConstraint("length(target) BETWEEN 1 AND 96", name="gold_target"),
        CheckConstraint(
            "length(ai_sha256) = 64 AND length(request_sha256) = 64", name="gold_digests"
        ),
        CheckConstraint("(erased_at IS NULL) = (payload IS NOT NULL)", name="gold_erasure"),
        Index("ix_gold_row_call", "recording_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    assignment_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("conversation_gold_assignments.assignment_id")
    )
    recording_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("conversation_recordings.id"))
    review_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("conversation_pointer_reviews.id"))
    reviewer_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("persons.id"))
    target: Mapped[str] = mapped_column(String(96))
    ai_sha256: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    supersedes_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("conversation_gold_rows.id")
    )
    request_key: Mapped[str] = mapped_column(String(128))
    request_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
