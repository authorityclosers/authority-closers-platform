"""AI on calls tables (migration 20261021_0119, owner 21 Oct 2026). Both append-only.

- ``call_ai_settings``: one organisation's levels, a new revision per save (newest
  wins); every save is also audited with old and new.
- ``call_ai_decisions``: what the level did to one call. 'skipped' names the plan and
  the first stage it left out (one row per plan) and why (``reason``: the seller's level,
  or the short-call rule; migration 20261021_0120); 'upgraded' is a person's "Get full
  report" for that call. Ids and levels only: no call content, so erasure has nothing
  to empty here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base


class CallAiSettings(Base):
    """One saved revision of an organisation's AI-on-calls levels (newest wins)."""

    __tablename__ = "call_ai_settings"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_call_ai_settings_tenant"),
        UniqueConstraint("tenant_id", "revision", name="uq_call_ai_settings_revision"),
        CheckConstraint("revision >= 1", name="call_ai_settings_revision"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    revision: Mapped[int] = mapped_column(Integer)
    config: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_by_person_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CallAiDecision(Base):
    """A call the level stopped before a paid stage, or a person's upgrade of one call."""

    __tablename__ = "call_ai_decisions"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_call_ai_decision_tenant"),
        ForeignKeyConstraint(
            ["recording_id"], ["conversation_recordings.id"], name="fk_call_ai_decision_recording"
        ),
        UniqueConstraint("plan_id", "decision", name="uq_call_ai_decision_plan"),
        CheckConstraint(
            "level IN ('off', 'data_only', 'auto', 'full')", name="call_ai_decision_level"
        ),
        CheckConstraint("decision IN ('skipped', 'upgraded')", name="call_ai_decision_kind"),
        CheckConstraint(
            "(decision = 'skipped') = (plan_id IS NOT NULL AND stage IN ('C2', 'C4'))",
            name="call_ai_decision_skip",
        ),
        CheckConstraint(
            "decision <> 'upgraded' OR actor_person_id IS NOT NULL",
            name="call_ai_decision_actor",
        ),
        CheckConstraint(
            "reason IS NULL OR reason IN ('level', 'short_call', 'no_conversation')",
            name="call_ai_decision_reason",
        ),
        Index("ix_call_ai_decision_call", "recording_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    recording_id: Mapped[UUID] = mapped_column(Uuid)
    plan_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    # The seller whose call it is (the upload's account), when known.
    person_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    level: Mapped[str] = mapped_column(String(16))
    decision: Mapped[str] = mapped_column(String(16))
    stage: Mapped[str | None] = mapped_column(String(8), nullable=True)
    settings_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor_person_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Why a call stopped (null on upgrades and on rows written before migration 0120).
    reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
