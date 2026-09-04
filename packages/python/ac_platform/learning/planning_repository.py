"""SQLAlchemy repository for proposal-level planning and analytics records."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ac_platform.learning.planning import PlanPeriod
from ac_platform.learning.planning_models import (
    AnalyticsEvent,
    LearningNextActionProjection,
    LearningPlanItem,
)


class AnalyticsEventReplayConflict(ValueError):
    """An event id was replayed with a different immutable observation."""


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

    def purge_expired_analytics_batch(
        self,
        database: Session,
        *,
        retention_policy_id: str,
        now: datetime,
        batch_size: int = 1_000,
        tenant_id: UUID | None = None,
    ) -> int:
        """Delete one bounded, explicitly policy-scoped expiry batch.

        Retention is a maintenance concern owned by a durable scheduler, not
        a consequence of serving a learner read.  The policy id is required
        so a caller cannot accidentally apply a disposable analytics rule to
        another retention class (for example, legal or audit records).
        """

        if not retention_policy_id or not retention_policy_id.strip():
            raise ValueError("retention_policy_id is required")
        if batch_size < 1 or batch_size > 10_000:
            raise ValueError("batch_size must be between 1 and 10000")
        cutoff = ensure_utc(now)
        statement = (
            select(AnalyticsEvent)
            .where(
                AnalyticsEvent.retention_policy_id == retention_policy_id,
                AnalyticsEvent.retention_expires_at <= cutoff,
            )
            .order_by(
                AnalyticsEvent.retention_expires_at,
                AnalyticsEvent.tenant_id,
                AnalyticsEvent.event_id,
            )
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        if tenant_id is not None:
            statement = statement.where(AnalyticsEvent.tenant_id == tenant_id)
        rows = tuple(database.scalars(statement))
        for row in rows:
            database.delete(row)
        if rows:
            database.flush()
        return len(rows)

    def purge_expired_analytics(
        self,
        database: Session,
        *,
        tenant_id: UUID,
        now: datetime,
        retention_policy_id: str | None = None,
        batch_size: int = 1_000,
    ) -> int:
        """Compatibility wrapper requiring an explicit policy.

        Older callers may still reach this name, but an omitted policy is a
        fail-closed no-op.  Learner reads never use this wrapper; the durable
        retention job supplies the approved policy id explicitly.
        """

        if retention_policy_id is None:
            return 0
        return self.purge_expired_analytics_batch(
            database,
            retention_policy_id=retention_policy_id,
            now=now,
            batch_size=batch_size,
            tenant_id=tenant_id,
        )

    def list_analytics_events(
        self,
        database: Session,
        *,
        tenant_id: UUID,
        person_id: UUID,
        period: PlanPeriod | None,
        now: datetime,
    ) -> Sequence[AnalyticsEvent]:
        statement = select(AnalyticsEvent).where(
            AnalyticsEvent.tenant_id == tenant_id,
            AnalyticsEvent.subject_person_id == person_id,
            AnalyticsEvent.retention_expires_at > ensure_utc(now),
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

    def add_analytics_events(
        self, database: Session, events: Sequence[AnalyticsEvent]
    ) -> tuple[int, int, tuple[str, ...]]:
        """Append a batch and classify exact replays without overwriting history.

        Event ids are tenant-scoped idempotency keys.  An exact replay is a
        harmless duplicate; reusing an id for a different observation is a
        conflict and never silently replaces the original row.
        """

        pending: list[AnalyticsEvent] = []
        duplicates = 0
        for event in events:
            existing = database.scalar(
                select(AnalyticsEvent).where(
                    AnalyticsEvent.tenant_id == event.tenant_id,
                    AnalyticsEvent.event_id == event.event_id,
                )
            )
            if existing is None:
                pending.append(event)
                continue
            if not _same_analytics_observation(existing, event):
                raise AnalyticsEventReplayConflict(
                    f"analytics event id {event.event_id!r} was replayed with different data"
                )
            duplicates += 1

        stored = 0
        stored_ids: list[str] = []
        for event in pending:
            try:
                with database.begin_nested():
                    database.add(event)
                    database.flush()
            except IntegrityError as exc:
                # A concurrent writer may have won after the preflight read.
                # Do not convert an unknown integrity failure into a duplicate.
                existing = database.scalar(
                    select(AnalyticsEvent).where(
                        AnalyticsEvent.tenant_id == event.tenant_id,
                        AnalyticsEvent.event_id == event.event_id,
                    )
                )
                if existing is None:
                    raise exc
                if not _same_analytics_observation(existing, event):
                    raise AnalyticsEventReplayConflict(
                        f"analytics event id {event.event_id!r} was replayed with different data"
                    ) from exc
                duplicates += 1
                continue
            stored += 1
            stored_ids.append(event.event_id)
        return stored, duplicates, tuple(stored_ids)


def _same_analytics_observation(existing: AnalyticsEvent, candidate: AnalyticsEvent) -> bool:
    """Compare immutable observation fields while ignoring server metadata.

    ``trace_id``, release, consent, retention, and ``created_at`` are
    request/storage metadata and therefore legitimately differ on a replay.
    The original row's metadata and retention deadline are preserved rather
    than extended by a retry.
    """

    fields = (
        "tenant_id",
        "actor_person_id",
        "subject_person_id",
        "event_id",
        "event_name",
        "event_version",
        "event_class",
        "session_id",
        "route",
        "period",
        "payload",
    )
    if any(
        _analytics_field(existing, field) != _analytics_field(candidate, field) for field in fields
    ):
        return False
    return ensure_utc(existing.occurred_at) == ensure_utc(candidate.occurred_at)


def _analytics_field(event: AnalyticsEvent, field: str) -> object:
    value = getattr(event, field)
    if field == "event_class" and value is None:
        return "product_analytics"
    return value


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def explicit_date(value: date | None) -> date | None:
    """Keep a plan's authored date date-only; never calculate a boundary."""

    return value


__all__ = [
    "AnalyticsEventReplayConflict",
    "PlanningRepository",
    "ensure_utc",
    "explicit_date",
]
