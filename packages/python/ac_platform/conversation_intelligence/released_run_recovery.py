"""Stop orphaned work after customer failure without replaying a provider send."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionUsage,
    ConversationReportMinuteEvent,
)
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.models import (
    ConversationInferenceTask,
    ConversationRecording,
    ConversationRun,
)
from ac_platform.outbox.models import Job


def released_run_candidates() -> Select[tuple[Job, ConversationRun]]:
    """Read-only inventory of nonterminal source work after minute release."""
    usage = ConversationAcquisitionUsage
    latest_kind = (
        select(ConversationReportMinuteEvent.kind)
        .where(ConversationReportMinuteEvent.usage_id == usage.id)
        .order_by(ConversationReportMinuteEvent.revision.desc())
        .limit(1)
        .correlate(usage)
        .scalar_subquery()
    )
    return (
        select(Job, ConversationRun)
        .join(ConversationRun, ConversationRun.job_id == Job.id)
        .join(
            ConversationGuestSubmission,
            (ConversationGuestSubmission.recording_id == ConversationRun.recording_id)
            & (ConversationGuestSubmission.tenant_id == ConversationRun.tenant_id)
            & (ConversationGuestSubmission.person_id == ConversationRun.person_id),
        )
        .join(usage, usage.id == ConversationGuestSubmission.usage_id)
        .join(ConversationRecording, ConversationRecording.id == ConversationRun.recording_id)
        .where(
            latest_kind == "released",
            ConversationRun.state.in_(("queued", "running")),
            ConversationRecording.state == "ready",
            ConversationRun.generation == ConversationRecording.generation,
            Job.tenant_id == ConversationRun.tenant_id,
            Job.kind.in_(("conversation.inspect_local.v1", "conversation.infer_provider.v1")),
        )
        .order_by(ConversationRun.created_at, ConversationRun.id)
    )


async def stop_released_run(database: AsyncSession, *, generation: int) -> bool:
    now: datetime | None = await database.scalar(select(func.clock_timestamp()))
    assert now is not None
    candidate = (
        await database.execute(
            released_run_candidates()
            .where(
                or_(Job.recovery_generation == 0, Job.recovery_generation == generation),
                or_(
                    Job.status.in_(("queued", "retry_wait", "held", "dead_letter")),
                    (Job.status == "leased") & (Job.leased_until <= now),
                ),
                or_(
                    Job.provider_receipt.is_(None),
                    Job.provider_receipt["validation_state"].as_string() == "provider_returned",
                ),
            )
            .limit(1)
            .with_for_update(
                of=(ConversationAcquisitionUsage, Job, ConversationRun), skip_locked=True
            )
            .execution_options(populate_existing=True)
        )
    ).first()
    if candidate is None:
        return False
    job, run = candidate
    task = await database.scalar(
        select(ConversationInferenceTask)
        .where(ConversationInferenceTask.run_id == run.id)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    if task is None and await database.get(ConversationInferenceTask, run.id) is not None:
        return False  # Another recovery owner holds the task row.
    # A live worker holds the job row and is skipped. Dispatch and response
    # evidence, claim counts and provider-cost reservations remain immutable.
    job.status = "dead_letter"
    job.lease_token = job.leased_until = None
    job.held_at = job.hold_reason = None
    job.dead_lettered_at = job.dead_lettered_at or now
    job.last_error = job.last_error or "conversation_run_budget_expired"
    job.updated_at = now
    run.state, run.completed_at = "failed", now
    if task is not None and task.state in {"queued", "running"}:
        task.state = "uncertain" if job.dispatch_started_at is not None else "failed"
    await AuditRepository(database).append(
        tenant_id=run.tenant_id,
        actor_person_id=None,
        actor_type="system",
        action="conversation.released_run_stopped",
        resource_type="conversation_run",
        resource_id=run.id,
        payload={
            "job_id": str(job.id),
            "dispatch_started": job.dispatch_started_at is not None,
            "claim_count": job.attempt_count,
        },
        now=now,
    )
    return True
