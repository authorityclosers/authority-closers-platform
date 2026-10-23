"""Economics settings (migration 20261023_0126, owner 23 Oct 2026).

One append-only table, like ``ai_spend_settings``: each save in Admin is a new revision,
newest wins, and every save is audited with old and new. It holds fixed costs and fee rates
only; revenue and AI cost are read live from the plans table and the metrics store. The
schema gate allows no triggers, so the ORM refuses updates and deletes (as audit events do).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base


class EconomicsHistoryError(RuntimeError):
    """A saved revision was changed or deleted; save a new revision instead."""


class EconomicsSettings(Base):
    """One saved revision of the economics settings (newest wins)."""

    __tablename__ = "economics_settings"
    __table_args__ = (
        UniqueConstraint("revision", name="uq_economics_settings_revision"),
        CheckConstraint("revision >= 1", name="revision"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer)
    config: Mapped[dict[str, Any]] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_by_person_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


@event.listens_for(EconomicsSettings, "before_update")
def _refuse_update(_mapper: object, _connection: object, _target: object) -> None:
    raise EconomicsHistoryError("Economics settings are append-only: save a new revision.")


@event.listens_for(EconomicsSettings, "before_delete")
def _refuse_delete(_mapper: object, _connection: object, _target: object) -> None:
    raise EconomicsHistoryError("Economics settings are append-only: save a new revision.")
