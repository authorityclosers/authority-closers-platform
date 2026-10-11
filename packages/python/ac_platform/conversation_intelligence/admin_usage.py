"""Operations-admin usage view (AUT-1798): counts of product events, nothing more.

Reads the product-analytics events recorded for the served Sales Xray
organisations (Strike A's telemetry/1 events once they ship): how many of
each event, by day, and how many distinct people and organisations sent them.
Payloads are never read or returned, and analytics never become progress or
payment state (AGENTS.md); this is a read-only count.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationDenied,
    ConversationError,
    utc,
)
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.kernel.authz import ActorContext
from ac_platform.learning.planning_models import AnalyticsEvent

MAX_DAYS = 90


class AdminUsage:
    def __init__(
        self,
        application: ConversationApplication,
        operations_tenant_id: UUID,
        *,
        recording_tenant_ids: tuple[UUID, ...],
    ) -> None:
        self.application = application
        self.database: AsyncSession = application.database
        self.operations_tenant_id = operations_tenant_id
        self.tenant_ids = tuple(
            item for item in dict.fromkeys(recording_tenant_ids) if item != operations_tenant_id
        )

    async def summary(self, actor: ActorContext, *, days: int = 7) -> dict[str, Any]:
        if actor.tenant_id != self.operations_tenant_id:
            raise ConversationDenied("Usage requires the AC operations workspace.")
        await ConversationProviderAdmin(self.application).admit(actor)
        if type(days) is not int or not 1 <= days <= MAX_DAYS:
            raise ConversationError("Choose a window between 1 and 90 days.")
        now: datetime = utc(self.application.clock())
        since = now - timedelta(days=days)
        scoped = (
            AnalyticsEvent.tenant_id.in_(self.tenant_ids),
            AnalyticsEvent.occurred_at >= since,
        )
        totals = (
            await self.database.execute(
                select(
                    func.count(),
                    func.count(distinct(AnalyticsEvent.actor_person_id)),
                    func.count(distinct(AnalyticsEvent.tenant_id)),
                ).where(*scoped)
            )
        ).one()
        names = (
            await self.database.execute(
                select(
                    AnalyticsEvent.event_name,
                    AnalyticsEvent.event_version,
                    func.count(),
                    func.count(distinct(AnalyticsEvent.actor_person_id)),
                )
                .where(*scoped)
                .group_by(AnalyticsEvent.event_name, AnalyticsEvent.event_version)
                .order_by(func.count().desc())
                .limit(200)
            )
        ).all()
        # Days are UTC dates, like the window itself, whatever the session's zone.
        day = func.date(func.timezone("UTC", AnalyticsEvent.occurred_at))
        daily_rows = {
            str(value): (count, people)
            for value, count, people in (
                await self.database.execute(
                    select(day, func.count(), func.count(distinct(AnalyticsEvent.actor_person_id)))
                    .where(*scoped)
                    .group_by(day)
                )
            ).all()
        }
        # Every date the rolling window touches, so the chart adds up to the totals.
        daily = []
        for offset in range((now.date() - since.date()).days, -1, -1):
            key = (now - timedelta(days=offset)).date().isoformat()
            count, people = daily_rows.get(key, (0, 0))
            daily.append({"day": key, "events": count, "people": people})
        return {
            "window": {"days": days, "since": since.isoformat()},
            "events": totals[0],
            "people": totals[1],
            "organisations": totals[2],
            "by_event": [
                {"name": name, "version": version, "count": count, "people": people}
                for name, version, count, people in names
            ],
            "daily": daily,
        }
