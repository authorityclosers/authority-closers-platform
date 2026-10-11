"""Append-only call review labels (AUT-1798): verdicts, notes, gold labels.

One row is one reviewer statement about one call: a verdict on a section of
a run's report, a note, Dipak's gold label, a training/test data mark, or a
review state. A later statement of the same kind by the same reviewer
supersedes the earlier one as a new row; nothing is edited or deleted. The ORM
hooks below and the PostgreSQL trigger refuse UPDATE and DELETE. Labels are an
internal reviewer record, never an official score (AC-SVAL) and never shown to
reps.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    event,
    func,
)
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapped, Mapper, mapped_column

from ac_platform.db.base import Base

LABEL_KINDS = frozenset({"verdict", "note", "gold", "data_use", "status"})


def utc_now() -> datetime:
    return datetime.now(UTC)


class ReviewLabelHistoryMutationError(RuntimeError):
    """Review history is superseded by a new row, never rewritten."""


class ConversationReviewLabel(Base):
    __tablename__ = "conversation_review_labels"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('verdict', 'note', 'gold', 'data_use', 'status')", name="kind_supported"
        ),
        CheckConstraint(
            "kind <> 'verdict' OR (section IS NOT NULL AND run_id IS NOT NULL)",
            name="verdict_has_section_and_run",
        ),
        CheckConstraint("section IS NULL OR length(trim(section)) > 0", name="section_nonblank"),
        UniqueConstraint("supersedes_id", name="uq_conversation_review_labels_supersedes"),
        UniqueConstraint("audit_event_id", name="uq_conversation_review_labels_audit_event"),
        Index("ix_conversation_review_labels_recording", "tenant_id", "recording_id"),
        Index("ix_conversation_review_labels_kind_created", "kind", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    recording_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("conversation_recordings.id"), nullable=False
    )
    run_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("conversation_runs.id"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    section: Mapped[str | None] = mapped_column(String(96), nullable=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    supersedes_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("conversation_review_labels.id"), nullable=True
    )
    actor_person_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("persons.id"), nullable=False
    )
    audit_event_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("audit_events.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )


@event.listens_for(ConversationReviewLabel, "before_update")
@event.listens_for(ConversationReviewLabel, "before_delete")
def _reject_label_mutation(
    mapper: Mapper[Any], connection: Connection, target: ConversationReviewLabel
) -> None:
    del mapper, connection, target
    raise ReviewLabelHistoryMutationError("review labels are append-only; add a new label instead")


__all__ = ["LABEL_KINDS", "ConversationReviewLabel", "ReviewLabelHistoryMutationError"]
