"""Append-only proof and report versions for retained C5 recovery.

Recovery versions deliberately live beside the provider checkpoint graph.  A
retained response can become readable after source-owned validation, but that
does not turn an uncertain provider task into a canonical C5/C6 execution.
Content columns may be cleared by the existing recording erasure job; identity
hashes and the version lineage remain immutable.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.conversation_intelligence.models import member_fk, recording_fk
from ac_platform.db.base import Base


class ConversationRetainedC5Version(Base):
    """One source-bound revalidation or reviewed correction result.

    ``payload`` is a report draft only when ``validation_state`` is
    ``revalidated`` or ``corrected``.  A ``needs_correction`` row preserves the
    failed revalidation proof without exposing a report.  The row never claims
    a provider checkpoint, a C6 presentation, human approval, or an official
    score.
    """

    __tablename__ = "conversation_retained_c5_versions"
    __table_args__ = (
        recording_fk(),
        ForeignKeyConstraint(
            ["run_id", "tenant_id", "person_id"],
            ["conversation_runs.id", "conversation_runs.tenant_id", "conversation_runs.person_id"],
        ),
        member_fk(),
        UniqueConstraint("run_id", "version"),
        UniqueConstraint("run_id", "fingerprint"),
        CheckConstraint("version >= 1", name="positive_version"),
        CheckConstraint("generation >= 1", name="positive_generation"),
        CheckConstraint(
            "validation_state IN ('needs_correction','revalidated','corrected')",
            name="validation_state",
        ),
        CheckConstraint(
            "review_origin = 'Codex automated proposal'", name="review_origin"
        ),
        CheckConstraint("human_approved = false", name="never_human_approved"),
        CheckConstraint("dipak_adjudicated = false", name="never_dipak_adjudicated"),
        CheckConstraint("official_score = false", name="never_official_score"),
        CheckConstraint(
            "(erased_at IS NOT NULL) OR "
            "(validation_state = 'needs_correction' AND payload IS NULL) OR "
            "(validation_state IN ('revalidated','corrected') AND payload IS NOT NULL)",
            name="payload_matches_state",
        ),
        Index("ix_conversation_retained_c5_versions_recording", "recording_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    recording_id: Mapped[UUID] = mapped_column(Uuid)
    run_id: Mapped[UUID] = mapped_column(Uuid)
    task_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("conversation_inference_tasks.run_id"))
    job_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("jobs.id"))
    quote_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("conversation_quotes.id"))
    permission_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("conversation_permissions.id"))
    source_revision: Mapped[int] = mapped_column(Integer)
    source_sha256: Mapped[str] = mapped_column(String(64))
    generation: Mapped[int] = mapped_column(Integer)
    retention_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    c2_checkpoint_id: Mapped[UUID] = mapped_column(Uuid)
    c2_manifest_sha256: Mapped[str] = mapped_column(String(64))
    c3_checkpoint_id: Mapped[UUID] = mapped_column(Uuid)
    c3_manifest_sha256: Mapped[str] = mapped_column(String(64))
    c4_checkpoint_ids: Mapped[list[str]] = mapped_column(JSON)
    c4_manifest_sha256s: Mapped[list[str]] = mapped_column(JSON)
    c5_input_sha256: Mapped[str] = mapped_column(String(64))
    c5_input: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    original_quote: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    original_attempt: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    original_receipt: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    original_raw_sha256: Mapped[str] = mapped_column(String(64))
    raw_blob_id: Mapped[UUID] = mapped_column(Uuid)
    version: Mapped[int] = mapped_column(Integer)
    fingerprint: Mapped[str] = mapped_column(String(64))
    validation_state: Mapped[str] = mapped_column(String(32))
    failure_code: Mapped[str | None] = mapped_column(String(128))
    correction: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    correction_payload_sha256: Mapped[str | None] = mapped_column(String(64))
    review_origin: Mapped[str] = mapped_column(String(64), default="Codex automated proposal")
    human_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    dipak_adjudicated: Mapped[bool] = mapped_column(Boolean, default=False)
    official_score: Mapped[bool] = mapped_column(Boolean, default=False)
    proof: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    report_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# Short aliases keep the recovery boundary easy to discover for callers while
# leaving one canonical mapped class for Alembic and erasure wiring.
ConversationC5RecoveryVersion = ConversationRetainedC5Version


__all__ = ["ConversationC5RecoveryVersion", "ConversationRetainedC5Version"]
