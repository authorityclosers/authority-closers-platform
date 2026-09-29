"""Completed analyses per Asia/Kolkata day, read from durable settlement receipts."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Date, String, and_, cast, func, literal_column, select

from ac_platform.conversation_intelligence.acquisition_library import _submission_owner_filter
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionSettlement,
    ConversationAcquisitionUsage,
    ConversationVisitorClaim,
)
from ac_platform.conversation_intelligence.canary_models import ConversationCanarySubmission
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.kernel.authz import ActorContext

TIMEZONE = "Asia/Kolkata"
WINDOW_DAYS = 30


async def account_activity(
    ownership: GuestOwnership, actor: ActorContext, *, shared_identity_locks: bool = False
) -> dict[str, Any]:
    """Count this account's completed analyses per day in one grouped statement.

    An analysis counts once, on the Asia/Kolkata date its ``completed``
    settlement receipt was written (when the first report was persisted).
    Receipts outlive the 7-day recording retention, so calls whose recording has
    since expired or been deleted still count; that is intended. Unsettled usage,
    ``no_work_performed`` settlements and fictional canary calls never count.
    """
    now = await ownership.sessions._admit()
    await ownership.sessions._owner(None, actor, now, shared_identity_locks=shared_identity_locks)
    zone = ZoneInfo(TIMEZONE)
    today = now.astimezone(zone).date()
    first = today - timedelta(days=WINDOW_DAYS - 1)
    previous = first - timedelta(days=WINDOW_DAYS)
    usage, claim = ConversationAcquisitionUsage, ConversationVisitorClaim
    settlement, canary = ConversationAcquisitionSettlement, ConversationCanarySubmission
    # A constant zone keeps the SELECT and GROUP BY expressions identical for PostgreSQL.
    zone_name = literal_column(f"'{TIMEZONE}'", String)
    day = cast(func.timezone(zone_name, settlement.created_at), Date).label("day")
    rows = await ownership.database.execute(
        select(day, func.count(), func.coalesce(func.sum(settlement.charged_seconds), 0))
        .select_from(settlement)
        .join(usage, usage.id == settlement.usage_id)
        .outerjoin(
            claim, and_(claim.visitor_id == usage.visitor_id, claim.tenant_id == usage.tenant_id)
        )
        .where(
            usage.tenant_id == actor.tenant_id,
            _submission_owner_filter(usage, claim, person_id=actor.person_id, visitor_id=None),
            settlement.kind == "completed",
            settlement.created_at >= datetime.combine(previous, time(), zone),
            settlement.created_at < datetime.combine(today + timedelta(days=1), time(), zone),
            ~select(canary.submission_id)
            .where(
                canary.tenant_id == usage.tenant_id,
                canary.submission_id == usage.submission_id,
            )
            .exists(),
        )
        .group_by(day)
    )
    by_day = {row[0]: (int(row[1]), int(row[2])) for row in rows}
    days = []
    for offset in range(WINDOW_DAYS):
        date = first + timedelta(days=offset)
        count, seconds = by_day.get(date, (0, 0))
        days.append({"date": date.isoformat(), "analysed": count, "analysed_seconds": seconds})
    return {
        "timezone": TIMEZONE,
        "days": days,
        "analysed_last_30_days": sum(entry["analysed"] for entry in days),
        "analysed_previous_30_days": sum(
            count for date, (count, _) in by_day.items() if date < first
        ),
    }
