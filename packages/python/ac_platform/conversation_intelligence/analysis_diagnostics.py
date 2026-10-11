"""Content-free, read-only recovery inventory and observed pipeline timings."""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionSettlement,
    ConversationAcquisitionUsage,
    ConversationReportMinuteEvent,
)
from ac_platform.conversation_intelligence.guest_models import ConversationProcessingLease
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationCommand,
    ConversationInferenceTask,
    ConversationProcessingPlan,
    ConversationRun,
)
from ac_platform.outbox.models import Job

LIMIT = 5_000


async def analysis_inventory(
    database: AsyncSession, *, now: datetime, days: int = 14
) -> dict[str, Any]:
    """Select IDs, states and timestamps only; never fetch report/transcript blobs."""
    if type(days) is not int or not 1 <= days <= 30:
        raise ValueError("The observation window must be between one and 30 days.")
    plan = ConversationProcessingPlan
    lease = ConversationProcessingLease
    usage = ConversationAcquisitionUsage
    event = ConversationReportMinuteEvent
    latest_kind = (
        select(event.kind)
        .where(event.usage_id == usage.id)
        .order_by(event.revision.desc())
        .limit(1)
        .correlate(usage)
        .scalar_subquery()
    )
    held = (
        (
            await database.execute(
                select(
                    plan.id.label("plan_id"),
                    plan.recording_id,
                    plan.state,
                    plan.created_at,
                    plan.expires_at,
                    plan.progress["failure_code"].as_string().label("failure_code"),
                    usage.id.label("usage_id"),
                    usage.reserved_seconds,
                    latest_kind.label("minute_kind"),
                    ConversationAcquisitionSettlement.kind.label("legacy_settlement"),
                )
                .outerjoin(lease, lease.id == plan.processing_lease_id)
                .outerjoin(usage, usage.id == lease.usage_id)
                .outerjoin(
                    ConversationAcquisitionSettlement,
                    ConversationAcquisitionSettlement.usage_id == usage.id,
                )
                .where(plan.state.in_(("held", "cancelled")), plan.erased_at.is_(None))
                .order_by(plan.created_at, plan.id)
                .limit(LIMIT + 1)
            )
        )
        .mappings()
        .all()
    )
    run, task = ConversationRun, ConversationInferenceTask
    timings = (
        (
            await database.execute(
                select(
                    run.id.label("run_id"),
                    run.recording_id,
                    run.state,
                    run.created_at,
                    run.completed_at,
                    task.stage,
                    Job.kind.label("job_kind"),
                    Job.status.label("job_status"),
                    Job.available_at,
                    Job.dispatch_started_at,
                    Job.receipt_recorded_at,
                    Job.attempt_count,
                )
                .join(Job, Job.id == run.job_id)
                .outerjoin(task, task.run_id == run.id)
                .where(run.created_at >= now - timedelta(days=days), run.created_at <= now)
                .order_by(run.created_at, run.id)
                .limit(LIMIT + 1)
            )
        )
        .mappings()
        .all()
    )
    checkpoint = ConversationCheckpoint
    stages = (
        (
            await database.execute(
                select(checkpoint.recording_id, checkpoint.stage, checkpoint.created_at)
                .where(
                    checkpoint.created_at >= now - timedelta(days=days),
                    checkpoint.created_at <= now,
                    checkpoint.erased_at.is_(None),
                )
                .order_by(checkpoint.created_at, checkpoint.id)
                .limit(LIMIT + 1)
            )
        )
        .mappings()
        .all()
    )
    deliveries = (
        (
            await database.execute(
                select(
                    usage.submission_id,
                    event.plan_id,
                    usage.reserved_seconds.label("source_duration_seconds"),
                    usage.created_at.label("source_reserved_at"),
                    ConversationCommand.created_at.label("plan_accepted_at"),
                    event.created_at.label("report_delivered_at"),
                )
                .select_from(event)
                .join(usage, usage.id == event.usage_id)
                .outerjoin(plan, plan.id == event.plan_id)
                .outerjoin(
                    ConversationCommand,
                    ConversationCommand.id == plan.acceptance_command_id,
                )
                .where(
                    event.kind == "delivered",
                    event.created_at >= now - timedelta(days=days),
                    event.created_at <= now,
                )
                .order_by(event.created_at, event.usage_id)
                .limit(LIMIT + 1)
            )
        )
        .mappings()
        .all()
    )
    return {
        "checked_at": now,
        "window_days": days,
        "held_plans": [dict(row) for row in held[:LIMIT]],
        "runs": [dict(row) for row in timings[:LIMIT]],
        "checkpoints": [dict(row) for row in stages[:LIMIT]],
        "delivered_calls": [dict(row) for row in deliveries[:LIMIT]],
        "truncated": {
            "held_plans": len(held) > LIMIT,
            "runs": len(timings) > LIMIT,
            "checkpoints": len(stages) > LIMIT,
            "delivered_calls": len(deliveries) > LIMIT,
        },
    }


def _seconds(start: Any, end: Any) -> float | None:
    if not isinstance(start, datetime) or not isinstance(end, datetime) or end < start:
        return None
    return (end - start).total_seconds()


def _distribution(values: list[float]) -> dict[str, Any]:
    ordered = sorted(values)
    return {
        "samples": len(ordered),
        "p50_seconds": ordered[math.ceil(len(ordered) * 0.5) - 1] if ordered else None,
        "p95_seconds": ordered[math.ceil(len(ordered) * 0.95) - 1] if ordered else None,
        "maximum_seconds": ordered[-1] if ordered else None,
    }


def summarize_timings(inventory: dict[str, Any]) -> dict[str, Any]:
    """Do not assign missing timestamps zero latency or mix failures with completions."""
    grouped: dict[str, dict[str, list[float]]] = {}
    incomplete: dict[str, int] = {}
    for row in inventory["runs"]:
        stage = row["stage"] or (
            "C0-C1" if row["job_kind"] == "conversation.inspect_local.v1" else "other"
        )
        group = grouped.setdefault(
            stage, {"run": [], "before_dispatch": [], "dispatch_to_receipt": []}
        )
        if row["state"] != "completed":
            incomplete[stage] = incomplete.get(stage, 0) + 1
            continue
        for label, start, end in (
            ("run", row["created_at"], row["completed_at"]),
            ("before_dispatch", row["created_at"], row["dispatch_started_at"]),
            ("dispatch_to_receipt", row["dispatch_started_at"], row["receipt_recorded_at"]),
        ):
            seconds = _seconds(start, end)
            if seconds is not None:
                group[label].append(seconds)

    def delivery_times(rows: list[dict[str, Any]], field: str) -> list[float]:
        values = [_seconds(row[field], row["report_delivered_at"]) for row in rows]
        return [value for value in values if value is not None]

    deliveries = inventory.get("delivered_calls", [])
    near_ten_minutes = [row for row in deliveries if 540 <= row["source_duration_seconds"] <= 660]
    band_times = delivery_times(near_ten_minutes, "plan_accepted_at")
    return {
        "stages": {
            stage: {name: _distribution(values) for name, values in group.items()}
            for stage, group in sorted(grouped.items())
        },
        "incomplete_runs": incomplete,
        "retries_observed": sum(max(0, row["attempt_count"] - 1) for row in inventory["runs"]),
        "delivery": {
            "calls": len(deliveries),
            "source_reserved_to_delivery": _distribution(
                delivery_times(deliveries, "source_reserved_at")
            ),
            "accepted_plan_to_delivery": _distribution(
                delivery_times(deliveries, "plan_accepted_at")
            ),
            "near_ten_minute_sources": {
                "duration_range_seconds": [540, 660],
                "calls": len(near_ten_minutes),
                "accepted_plan_to_delivery": _distribution(band_times),
                "measured_under_120_seconds": sum(value < 120 for value in band_times),
            },
        },
        "limits": [
            "Before dispatch includes queue, scheduling and admission; it is not pure queue wait.",
            "Dispatch to receipt includes provider work and receipt persistence; "
            "it is not pure provider latency.",
            "C0/C1 share a local run. C3/C6 have checkpoint timestamps, "
            "not independent run durations.",
            "No 10-minute-call speed claim is made without duration-bound end-to-end evidence.",
            "Delivery uses the app minute journal; earlier reports are absent from this measure.",
            "Reservation excludes upload preflight; acceptance excludes earlier stages.",
            "The 9-to-11-minute duration band is explicit, not an exact 10-minute source claim.",
        ],
    }
