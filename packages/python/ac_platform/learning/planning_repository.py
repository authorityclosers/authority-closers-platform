"""SQLAlchemy repository for proposal-level planning and analytics records."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ac_platform.learning.planning import PlanPeriod
from ac_platform.learning.planning_models import (
    AnalyticsEvent,
    LearningNextActionProjection,
    LearningPlanItem,
)


class PlanningRepository:
    """Read/write adapter used inside the authenticated transaction."""

    def list_plan_items(
        self, database: Session, *, tenant_id: UUID, person_id: UUID, period: PlanPeriod
    ) -> Sequence[LearningPlanItem]:
        return tuple(
            database.scalars(
                select(LearningPlanItem)
                .where(
                    LearningPlanItem.tenant_id == tenant_id,
                    LearningPlanItem.person_id == person_id,
                    LearningPlanItem.period == period.value,
                    LearningPlanItem.superseded_at.is_(None),
                )
                .order_by(
                    LearningPlanItem.position,
                    LearningPlanItem.planned_for,
                    LearningPlanItem.id,
                )
            )
        )

    def get_plan_item(
        self, database: Session, *, tenant_id: UUID, person_id: UUID, plan_item_id: UUID
    ) -> LearningPlanItem | None:
        return database.scalar(
            select(LearningPlanItem).where(
                LearningPlanItem.id == plan_item_id,
                LearningPlanItem.tenant_id == tenant_id,
                LearningPlanItem.person_id == person_id,
                LearningPlanItem.superseded_at.is_(None),
            )
        )

    def get_next_action(
        self, database: Session, *, tenant_id: UUID, person_id: UUID
    ) -> LearningNextActionProjection | None:
        return database.scalar(
            select(LearningNextActionProjection).where(
                LearningNextActionProjection.tenant_id == tenant_id,
                LearningNextActionProjection.person_id == person_id,
            )
        )

    def purge_expired_analytics(self, database: Session, *, tenant_id: UUID, now: datetime) -> int:
        result = cast(
            CursorResult[Any],
            database.execute(
                delete(AnalyticsEvent).where(
                    AnalyticsEvent.tenant_id == tenant_id,
                    AnalyticsEvent.retention_expires_at <= now,
                )
            ),
        )
        return int(result.rowcount or 0)

    def list_analytics_events(
        self,
        database: Session,
        *,
        tenant_id: UUID,
        person_id: UUID,
        period: PlanPeriod | None,
        now: datetime,
    ) -> Sequence[AnalyticsEvent]:
        self.purge_expired_analytics(database, tenant_id=tenant_id, now=now)
        statement = select(AnalyticsEvent).where(
            AnalyticsEvent.tenant_id == tenant_id,
            AnalyticsEvent.subject_person_id == person_id,
        )
        if period is not None:
            statement = statement.where(AnalyticsEvent.period == period.value)
        return tuple(
            database.scalars(
                statement.order_by(AnalyticsEvent.occurred_at, AnalyticsEvent.event_id)
            )
        )

    def add_analytics_event(self, database: Session, event: AnalyticsEvent) -> bool:
        """Insert once and preserve the outer authenticated transaction on replay."""

        existing = database.scalar(
            select(AnalyticsEvent.event_id).where(
                AnalyticsEvent.tenant_id == event.tenant_id,
                AnalyticsEvent.event_id == event.event_id,
            )
        )
        if existing is not None:
            return False
        try:
            with database.begin_nested():
                database.add(event)
                database.flush()
        except IntegrityError:
            return False
        return True


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def explicit_date(value: date | None) -> date | None:
    """Keep a plan's authored date date-only; never calculate a boundary."""

    return value


__all__ = ["PlanningRepository", "ensure_utc", "explicit_date"]
