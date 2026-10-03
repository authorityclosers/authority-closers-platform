"""First-report measurements, retained only with their source recording."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base


class ConversationCallMetrics(Base):
    """One speaker-keyed numeric summary per completed acquisition usage."""

    __tablename__ = "conversation_call_metrics"
    __table_args__ = (
        Index("ix_conversation_call_metrics_tenant_created", "tenant_id", "created_at"),
    )

    usage_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("conversation_acquisition_settlements.usage_id"), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"))
    submission_id: Mapped[UUID] = mapped_column(Uuid)
    recording_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("conversation_recordings.id"))
    report_draft_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("conversation_report_drafts.id"))
    rules: Mapped[str] = mapped_column(Text)
    summary: Mapped[dict[str, Any] | None] = mapped_column(
        JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql"), nullable=True
    )
    summary_sha256: Mapped[str] = mapped_column(String(64))
    outcome_kind: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
