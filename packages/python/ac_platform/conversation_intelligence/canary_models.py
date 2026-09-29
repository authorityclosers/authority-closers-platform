"""Append-only provenance for fictional pipeline canary submissions."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base


class ConversationCanarySubmission(Base):
    __tablename__ = "conversation_canary_submissions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "submission_id"],
            [
                "conversation_acquisition_usage.tenant_id",
                "conversation_acquisition_usage.submission_id",
            ],
        ),
        CheckConstraint(
            "environment IN ('local', 'test', 'development', 'staging', 'production')",
            name="environment",
        ),
        CheckConstraint("length(fixture_sha256) = 64", name="fixture_sha256"),
    )
    tenant_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    submission_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    environment: Mapped[str] = mapped_column(String(16))
    fixture_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
