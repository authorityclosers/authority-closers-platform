"""Append-only sensitive-segment marks (ADR 0051, ETH-03 containment).

A mark names a transcript segment by ID only. It never carries segment text, so
recording erasure keeps it. A release is a new row that supersedes the mark; a
mark is effective while no release supersedes it. Update and delete are refused
by the ORM hooks below and by the PostgreSQL trigger installed in migration 0065.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
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
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Mapped, Mapper, mapped_column
from sqlalchemy.sql.elements import ColumnElement

from ac_platform.db.base import Base

SENSITIVE_CATEGORIES = frozenset({"SENSITIVE_FINANCIAL", "SENSITIVE_LEGAL"})
MARK_ACTIONS = frozenset({"mark", "release"})
MARK_SOURCES = frozenset({"operator", "generation"})
REASON_REF_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._:#/-]{2,79}$")
REASON_REF_SQL_PATTERN = "^[A-Za-z0-9][A-Za-z0-9 ._:#/-]{2,79}$"


class _ReasonRefPatternExpression(ColumnElement[bool]):
    """PostgreSQL enforces the ``reason_ref`` pattern; SQLite keeps the length bound."""

    inherit_cache = True


@compiles(_ReasonRefPatternExpression, "postgresql")
def _compile_postgresql_reason_ref_pattern(
    _element: _ReasonRefPatternExpression, _compiler: object, **_kw: object
) -> str:
    return f"reason_ref ~ '{REASON_REF_SQL_PATTERN}'"


@compiles(_ReasonRefPatternExpression)
def _compile_default_reason_ref_pattern(
    _element: _ReasonRefPatternExpression, _compiler: object, **_kw: object
) -> str:
    return "length(trim(reason_ref)) >= 3 AND length(reason_ref) <= 80"


def utc_now() -> datetime:
    return datetime.now(UTC)


class SensitiveSegmentHistoryMutationError(RuntimeError):
    """Mark history is superseded by a release row, never rewritten."""


class ConversationSensitiveSegmentMark(Base):
    """One mark or release action; ``id`` is its command intent ID."""

    __tablename__ = "conversation_sensitive_segment_marks"
    __table_args__ = (
        CheckConstraint(
            "category IN ('SENSITIVE_FINANCIAL', 'SENSITIVE_LEGAL')", name="category_supported"
        ),
        CheckConstraint("action IN ('mark', 'release')", name="action_supported"),
        CheckConstraint("source IN ('operator', 'generation')", name="source_supported"),
        CheckConstraint(
            "(action = 'mark' AND supersedes_mark_id IS NULL) OR "
            "(action = 'release' AND supersedes_mark_id IS NOT NULL)",
            name="release_supersedes",
        ),
        CheckConstraint(
            "length(trim(reason_ref)) >= 3 AND length(reason_ref) <= 80", name="reason_ref_bound"
        ),
        CheckConstraint(_ReasonRefPatternExpression(), name="reason_ref_pattern"),
        CheckConstraint("length(trim(segment_id)) > 0", name="segment_id_bound"),
        CheckConstraint("length(trim(transcript_revision)) > 0", name="revision_bound"),
        UniqueConstraint(
            "supersedes_mark_id", name="uq_conversation_sensitive_segment_marks_supersedes"
        ),
        UniqueConstraint(
            "audit_event_id", name="uq_conversation_sensitive_segment_marks_audit_event"
        ),
        Index("ix_conversation_sensitive_segment_marks_recording", "tenant_id", "recording_id"),
        Index("ix_conversation_sensitive_segment_marks_revision", "transcript_revision"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    recording_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("conversation_recordings.id"), nullable=False
    )
    transcript_revision: Mapped[str] = mapped_column(String(256), nullable=False)
    segment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    supersedes_mark_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("conversation_sensitive_segment_marks.id"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_person_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("persons.id"), nullable=False
    )
    reason_ref: Mapped[str] = mapped_column(String(80), nullable=False)
    audit_event_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("audit_events.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )


@event.listens_for(ConversationSensitiveSegmentMark, "before_update")
@event.listens_for(ConversationSensitiveSegmentMark, "before_delete")
def _reject_mark_mutation(
    mapper: Mapper[Any], connection: Connection, target: ConversationSensitiveSegmentMark
) -> None:
    del mapper, connection, target
    raise SensitiveSegmentHistoryMutationError(
        "sensitive-segment marks are append-only; release the mark instead"
    )


__all__ = [
    "MARK_ACTIONS",
    "MARK_SOURCES",
    "REASON_REF_PATTERN",
    "SENSITIVE_CATEGORIES",
    "ConversationSensitiveSegmentMark",
    "SensitiveSegmentHistoryMutationError",
]
