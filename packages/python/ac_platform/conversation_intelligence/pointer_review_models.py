"""Saved AI pointer reviews for the 15 Oct Report (owner decision, 16 Oct 2026).

Append-only: a new review for the same report is a new row; the Report reads
the newest one for its exact run, source and transcript revision.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base


class ConversationPointerReview(Base):
    __tablename__ = "conversation_pointer_reviews"
    __table_args__ = (
        CheckConstraint("version = 'pointer-review/1'", name="pointer_review_version"),
        CheckConstraint(
            "length(source_sha256) = 64 AND length(payload_sha256) = 64"
            " AND length(prompt_sha256) = 64",
            name="pointer_review_digests",
        ),
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_pointer_review_tenant"),
        ForeignKeyConstraint(
            ["recording_id"], ["conversation_recordings.id"], name="fk_pointer_review_recording"
        ),
        ForeignKeyConstraint(["run_id"], ["conversation_runs.id"], name="fk_pointer_review_run"),
        ForeignKeyConstraint(
            ["report_draft_id"],
            ["conversation_report_drafts.id"],
            name="fk_pointer_review_report_draft",
        ),
        Index("ix_pointer_review_read", "recording_id", "run_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    recording_id: Mapped[UUID] = mapped_column(Uuid)
    run_id: Mapped[UUID] = mapped_column(Uuid)
    report_draft_id: Mapped[UUID] = mapped_column(Uuid)
    source_sha256: Mapped[str] = mapped_column(String(64))
    transcript_revision: Mapped[str] = mapped_column(String(128))
    version: Mapped[str] = mapped_column(String(32))
    model_id: Mapped[str] = mapped_column(String(64))
    prompt_sha256: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    payload_sha256: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
