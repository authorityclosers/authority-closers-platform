"""AI budget settings owned in Admin (migration 20261019_0099, owner decision 19 Oct 2026).

Append-only: every change is a new revision for its budget scope. The owner sets the
ceiling and the period; any Admin moves the cap per period up to the ceiling.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base


class ConversationBudgetSetting(Base):
    __tablename__ = "conversation_budget_settings"
    __table_args__ = (
        UniqueConstraint("scope_id", "revision", name="uq_budget_setting_revision"),
        CheckConstraint("revision >= 1", name="revision"),
        CheckConstraint("ceiling_paise >= 0", name="ceiling"),
        CheckConstraint("period IN ('lifetime', 'monthly', 'daily')", name="period"),
        CheckConstraint(
            "(period = 'lifetime') = (period_cap_paise IS NULL)"
            " AND (period_cap_paise IS NULL OR period_cap_paise BETWEEN 0 AND ceiling_paise)",
            name="period_cap",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    scope_id: Mapped[UUID] = mapped_column(Uuid)
    revision: Mapped[int] = mapped_column(Integer)
    ceiling_paise: Mapped[int] = mapped_column(Integer)
    period: Mapped[str] = mapped_column(String(16))
    # The cap for each month or day; NULL for lifetime, whose cap is the ledger's own.
    period_cap_paise: Mapped[int | None] = mapped_column(Integer)
    set_by_person_id: Mapped[UUID | None] = mapped_column(Uuid)
    reason: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


__all__ = ["ConversationBudgetSetting"]
