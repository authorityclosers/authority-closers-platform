"""Review 2.0 storage (migration 20261019_0101): pipelines and verdicts, append-only.

Reviewers judge the analysis (objects, facts, segments, voice, coaching points),
never report lines. A verdict holds the digest of the AI value it judged; a changed
answer supersedes the old row; call erasure empties the answer and keeps the shape.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base


class ReviewPipeline(Base):
    __tablename__ = "review_pipelines"
    __table_args__ = (
        UniqueConstraint("key", "version", name="uq_review_pipeline_version"),
        CheckConstraint("version >= 1", name="version"),
        CheckConstraint("kind IN ('analysis', 'coaching')", name="kind"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    key: Mapped[str] = mapped_column(String(48))
    version: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(120))
    definition: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_by: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("persons.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReviewVerdict(Base):
    __tablename__ = "review_verdicts"
    __table_args__ = (
        UniqueConstraint("reviewer_id", "request_key", name="uq_review_verdict_request"),
        UniqueConstraint("supersedes_id", name="uq_review_verdict_supersedes"),
        CheckConstraint(
            "target_kind IN ('object', 'fact', 'segment', 'voice', 'coaching')", name="target"
        ),
        CheckConstraint("length(ai_sha256) = 64", name="digest"),
        CheckConstraint("(erased_at IS NULL) = (answer IS NOT NULL)", name="erasure"),
        Index("ix_review_verdict_call", "recording_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    pipeline_key: Mapped[str] = mapped_column(String(48))
    pipeline_version: Mapped[int] = mapped_column(Integer)
    recording_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("conversation_recordings.id"))
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"))
    reviewer_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("persons.id"))
    target_kind: Mapped[str] = mapped_column(String(16))
    target_ref: Mapped[str] = mapped_column(String(96))
    question_key: Mapped[str] = mapped_column(String(48))
    ai_sha256: Mapped[str] = mapped_column(String(64))
    # SQL NULL once erased (not JSON null), as the erasure CHECK requires.
    answer: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True))
    supersedes_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("review_verdicts.id"))
    request_key: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


__all__ = ["ReviewPipeline", "ReviewVerdict"]
