"""Read-only overdue-work inventory for the watchdog; never repairs or sends."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.conversation_intelligence.models import ConversationProcessingPlan


async def overdue_processing_plans(database: AsyncSession, *, limit: int = 100) -> dict[str, Any]:
    """Return identifiers and budget facts only, bounded to one watchdog page."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Alarm limit must be between one and 100.")
    now = await database.scalar(select(func.clock_timestamp()))
    assert now is not None
    plans = list(
        (
            await database.scalars(
                select(ConversationProcessingPlan)
                .where(
                    ConversationProcessingPlan.state.in_(("active", "quoted")),
                    ConversationProcessingPlan.expires_at <= now,
                    ConversationProcessingPlan.erased_at.is_(None),
                )
                .order_by(ConversationProcessingPlan.expires_at, ConversationProcessingPlan.id)
                .limit(limit + 1)
            )
        ).all()
    )
    return {
        "schema": "ac.sales_xray.run_budget_alarm/1",
        "checked_at": now.isoformat(),
        "overdue": [
            {
                "plan_id": str(row.id),
                "tenant_id": str(row.tenant_id),
                "recording_id": str(row.recording_id),
                "state": row.state,
                "budget_expires_at": row.expires_at.isoformat(),
                "owner": "processing_plan_scheduler",
            }
            for row in plans[:limit]
        ],
        "truncated": len(plans) > limit,
    }
