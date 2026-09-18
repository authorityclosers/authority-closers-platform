"""Append-only, environment-scoped Sales Xray execution decisions."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.conversation_intelligence.models import member_fk
from ac_platform.db.base import Base


class ConversationExecutionControl(Base):
    __tablename__ = "conversation_execution_controls"
    __table_args__ = (
        member_fk(),
        UniqueConstraint("tenant_id", "environment", "revision"),
        CheckConstraint("revision >= 1", name="positive_revision"),
        CheckConstraint(
            "environment IN ('local','test','staging','production')", name="environment"
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    session_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("sessions.id"))
    environment: Mapped[str] = mapped_column(String(16))
    revision: Mapped[int] = mapped_column(Integer)
    paused: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
