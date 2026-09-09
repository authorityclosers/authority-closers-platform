"""Separate Focus commitment history: never an earned credit or XP account."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    event,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base
from ac_platform.practice.models import attempt_fk, member_fk


class PracticeFocusRun(Base):
    __tablename__ = "practice_focus_runs"
    __table_args__ = (
        attempt_fk(),
        UniqueConstraint("attempt_id"),
        UniqueConstraint("id", "tenant_id", "person_id"),
        Index(
            "uq_practice_focus_runs_active",
            "tenant_id",
            "person_id",
            unique=True,
            postgresql_where=text("state = 'active'"),
            sqlite_where=text("state = 'active'"),
        ),
        CheckConstraint(
            "(state = 'active' AND finished_at IS NULL AND exit_cost = 0 "
            "AND completion_restore = 0) OR "
            "(state = 'ended' AND finished_at IS NOT NULL AND exit_cost IN (0,1) "
            "AND completion_restore = 0) OR "
            "(state = 'completed' AND finished_at IS NOT NULL AND exit_cost = 0 "
            "AND completion_restore IN (0,1))",
            name="state_shape",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    attempt_id: Mapped[UUID] = mapped_column(Uuid)
    state: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exit_cost: Mapped[int] = mapped_column(Integer)
    completion_restore: Mapped[int] = mapped_column(Integer)


class PracticeFocusEvent(Base):
    __tablename__ = "practice_focus_events"
    __table_args__ = (
        member_fk(),
        ForeignKeyConstraint(
            ["run_id", "tenant_id", "person_id"],
            [
                "practice_focus_runs.id",
                "practice_focus_runs.tenant_id",
                "practice_focus_runs.person_id",
            ],
        ),
        UniqueConstraint("tenant_id", "person_id", "revision"),
        UniqueConstraint("run_id", "kind", name="uq_practice_focus_events_run_kind"),
        CheckConstraint("revision >= 1", name="positive_revision"),
        CheckConstraint(
            "charges_before BETWEEN 0 AND 3 AND charges_after BETWEEN 0 AND 3",
            name="charge_bounds",
        ),
        CheckConstraint(
            "(kind = 'day_reset' AND run_id IS NULL AND charges_after = 3) OR "
            "(kind = 'started' AND run_id IS NOT NULL AND charges_before > 0 "
            "AND charges_after = charges_before) OR "
            "(kind = 'ended' AND run_id IS NOT NULL "
            "AND charges_before - charges_after IN (0,1)) OR "
            "(kind = 'completed' AND run_id IS NOT NULL "
            "AND charges_after = CASE WHEN charges_before < 3 THEN charges_before + 1 ELSE 3 END)",
            name="event_shape",
        ),
        CheckConstraint("reset_day >= local_day", name="day_high_water"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    run_id: Mapped[UUID | None] = mapped_column(Uuid)
    revision: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))
    charges_before: Mapped[int] = mapped_column(Integer)
    charges_after: Mapped[int] = mapped_column(Integer)
    local_day: Mapped[date] = mapped_column(Date)
    reset_day: Mapped[date] = mapped_column(Date)
    timezone: Mapped[str] = mapped_column(String(64))
    policy_version: Mapped[str] = mapped_column(String(64))
    audit_event_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("audit_events.id"), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def _immutable(*args: Any) -> None:
    raise RuntimeError("Focus history is immutable; append a new event.")


event.listen(PracticeFocusEvent, "before_update", _immutable)
event.listen(PracticeFocusEvent, "before_delete", _immutable)
