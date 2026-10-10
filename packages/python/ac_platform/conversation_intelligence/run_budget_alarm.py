"""Read-only overdue-work inventory for the watchdog; never repairs or sends."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.conversation_intelligence.models import ConversationProcessingPlan
from ac_platform.conversation_intelligence.released_run_recovery import released_run_candidates
from ac_platform.conversation_intelligence.source_run_budget import expired_source_reservations


async def overdue_processing_plans(
    database: AsyncSession, *, limit: int = 100, now: datetime | None = None
) -> dict[str, Any]:
    """Return identifiers and budget facts only, bounded to one watchdog page."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Alarm limit must be between one and 100.")
    now = now or await database.scalar(select(func.clock_timestamp()))
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
    sources = list(await database.scalars(expired_source_reservations(now).limit(limit + 1)))
    unfinished = list((await database.execute(released_run_candidates().limit(limit + 1))).all())
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
        "overdue_sources": [
            {
                "usage_id": str(row.id),
                "submission_id": str(row.submission_id),
                "tenant_id": str(row.tenant_id),
                "owner": "processing_plan_scheduler",
            }
            for row in sources[:limit]
        ],
        "sources_truncated": len(sources) > limit,
        "released_unfinished_runs": [
            {
                "run_id": str(run.id),
                "job_id": str(job.id),
                "recording_id": str(run.recording_id),
                "tenant_id": str(run.tenant_id),
                "state": run.state,
                "owner": "processing_plan_scheduler",
            }
            for job, run in unfinished[:limit]
        ],
        "runs_truncated": len(unfinished) > limit,
    }
