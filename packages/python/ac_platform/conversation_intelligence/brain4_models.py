"""Brain 4.0 shadow reads of saved reports (brain4_shadow.py), beta only.

One row per attempt: 'running' committed before the provider call, then 'saved' with
the checked answer or 'failed' with a stable code. Erasing the call empties the answer
and stamps erased_at, with the call's pointer reviews (AUT-2010).
"""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base


class ConversationBrain4Review(Base):
    __tablename__ = "conversation_brain4_reviews"
    __table_args__ = (
        CheckConstraint("version = 'brain4-review/1'", name="brain4_review_version"),
        CheckConstraint("state IN ('running', 'saved', 'failed')", name="brain4_review_state"),
        CheckConstraint("trigger IN ('auto', 'operator')", name="brain4_review_trigger"),
        CheckConstraint(
            "(state = 'saved' AND erased_at IS NULL) = (payload IS NOT NULL)",
            name="brain4_review_payload",
        ),
        CheckConstraint(
            "(payload IS NULL OR length(payload_sha256) = 64) AND length(source_sha256) = 64"
            " AND length(rubric_sha256) = 64 AND length(prompt_sha256) = 64",
            name="brain4_review_digests",
        ),
        CheckConstraint(
            "(state = 'running') = (finished_at IS NULL)", name="brain4_review_finished"
        ),
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_brain4_review_tenant"),
        ForeignKeyConstraint(
            ["recording_id"], ["conversation_recordings.id"], name="fk_brain4_review_recording"
        ),
        ForeignKeyConstraint(["run_id"], ["conversation_runs.id"], name="fk_brain4_review_run"),
        ForeignKeyConstraint(
            ["report_draft_id"],
            ["conversation_report_drafts.id"],
            name="fk_brain4_review_report_draft",
        ),
        Index("ix_brain4_review_read", "recording_id", "run_id", "created_at"),
        Index("ix_brain4_review_recent", "state", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    recording_id: Mapped[UUID] = mapped_column(Uuid)
    run_id: Mapped[UUID] = mapped_column(Uuid)
    report_draft_id: Mapped[UUID] = mapped_column(Uuid)
    source_sha256: Mapped[str] = mapped_column(String(64))
    transcript_revision: Mapped[str] = mapped_column(String(128))
    version: Mapped[str] = mapped_column(String(32))
    rubric_sha256: Mapped[str] = mapped_column(String(64))
    model_id: Mapped[str] = mapped_column(String(64))
    prompt_sha256: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16))
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    payload_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_inr: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    trigger: Mapped[str] = mapped_column(String(16))
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
