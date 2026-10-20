"""AI spend settings (migration 20261020_0112, owner 20 Oct 2026).

One append-only table: each save in Admin is a new revision, newest wins, and every
save is audited with old and new. Spend itself is never stored here: it is read from
each feature's own rows (see ``ledger``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, DateTime, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base


class AiSpendSettings(Base):
    """One saved revision of this environment's AI spend caps (newest wins)."""

    __tablename__ = "ai_spend_settings"
    __table_args__ = (
        UniqueConstraint("revision", name="uq_ai_spend_settings_revision"),
        CheckConstraint("revision >= 1", name="revision"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer)
    config: Mapped[dict[str, Any]] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_by_person_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
