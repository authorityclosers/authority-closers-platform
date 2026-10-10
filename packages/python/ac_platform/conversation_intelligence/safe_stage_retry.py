"""Bounded successor checkpoints; never clear or replay an old provider send."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.models import AuditEvent
from ac_platform.conversation_intelligence.application import ConversationConflict, utc
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.models import (
    ConversationInferenceTask,
    ConversationRecording,
)
from ac_platform.conversation_intelligence.provider_failure_observation import (
    ProviderFailureObservation,
)
from ac_platform.outbox.models import Job

if TYPE_CHECKING:
    from ac_platform.conversation_intelligence.inference import ServicePlan

MAX_SOURCE_STAGE_ATTEMPTS = 3


def predecessor_id(checkpoint: dict[str, Any]) -> UUID | None:
    replicate = checkpoint.get("replicate", "")
    if not replicate:
        return None
    if not isinstance(replicate, str) or not replicate.startswith("retry:"):
        raise ConversationConflict("This checkpoint is not an authorized analysis retry.")
    try:
        return UUID(replicate.removeprefix("retry:"))
    except ValueError:
        raise ConversationConflict("The retry predecessor is invalid.") from None


def base_cache_key(checkpoint: dict[str, Any]) -> str:
    """Select the matching failed chunk without its old attempt replicate."""
    try:
        return content_hash(
            {
                "schema": "ac.sales_xray.checkpoint/1",
                "binding": checkpoint["binding"],
                "stage": checkpoint["stage"],
                "revision": checkpoint["revision"],
                "config": checkpoint["config"],
                "parents": checkpoint["parents"],
                "replicate": "",
            }
        )
    except KeyError:
        raise ConversationConflict("The immutable stage input is unavailable.") from None


async def require_retry_predecessor(
    database: AsyncSession,
    recording: ConversationRecording,
    run_id: UUID,
    *,
    now: datetime,
) -> ConversationInferenceTask:
    """Prove terminal ownership, transport evidence and a finite source lineage."""
    first: ConversationInferenceTask | None = None
    seen: set[UUID] = set()
    current: UUID | None = run_id
    while current is not None:
        if current in seen or len(seen) >= MAX_SOURCE_STAGE_ATTEMPTS - 1:
            raise ConversationConflict("This call has reached its analysis retry limit.")
        seen.add(current)
        task = await database.get(ConversationInferenceTask, current)
        if (
            task is None
            or task.erased_at is not None
            or task.intent is None
            or content_hash(task.intent) != task.intent_sha256
            or (task.tenant_id, task.person_id, task.recording_id, task.generation)
            != (recording.tenant_id, recording.person_id, recording.id, recording.generation)
            or task.state not in {"failed", "uncertain"}
            or task.checkpoint_id is not None
        ):
            raise ConversationConflict("The previous stage is not safely retryable.")
        job = await database.get(Job, task.job_id)
        if (
            job is None
            or job.tenant_id != recording.tenant_id
            or job.status != "dead_letter"
            or job.lease_token is not None
            or job.leased_until is not None
            or not job.external_side_effect
            or job.kind != "conversation.infer_provider.v1"
            or job.payload.get("run_id") != str(task.run_id)
            or job.provider_receipt is not None
        ):
            raise ConversationConflict("The previous analysis still needs reconciliation.")
        if job.dispatch_started_at is not None:
            observed = await database.scalar(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == recording.tenant_id,
                    AuditEvent.action == "conversation.provider_failure_observed",
                    AuditEvent.resource_type == "job",
                    AuditEvent.resource_id == str(job.id),
                )
            )
            assessed = await database.scalar(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == recording.tenant_id,
                    AuditEvent.action == "conversation.provider_retry_assessed",
                    AuditEvent.resource_type == "job",
                    AuditEvent.resource_id == str(job.id),
                )
            )
            if observed is None or assessed is None:
                raise ConversationConflict("The provider outcome needs checking before retry.")
            evidence = observed.payload
            if (
                evidence.get("schema") != "ac.sales_xray.provider_failure_evidence/1"
                or evidence.get("job_id") != str(job.id)
                or evidence.get("attempt_count") != job.attempt_count
                or evidence.get("recovery_generation") != job.recovery_generation
                or evidence.get("dispatch_started_at") != job.dispatch_started_at.isoformat()
            ):
                raise ConversationConflict("The original provider failure evidence was fenced.")
            try:
                observation = ProviderFailureObservation.from_dict(
                    evidence.get("failure_observation")
                )
            except ValueError:
                raise ConversationConflict(
                    "The original provider failure evidence is invalid."
                ) from None
            if (
                observation.reservation_id != str(task.run_id)
                or observation.attempt_id != job.provider_idempotency_key
            ):
                raise ConversationConflict("The original provider dispatch binding changed.")
            payload = assessed.payload
            assessment = payload.get("assessment")
            if (
                payload.get("schema") != "ac.sales_xray.provider_retry_assessment/1"
                or payload.get("job_id") != str(job.id)
                or payload.get("failure_event_id") != str(observed.id)
                or payload.get("failure_event_hash") != observed.event_hash
                or payload.get("claim_count") != job.attempt_count
                or payload.get("claim_limit") != job.max_attempts
                or payload.get("recovery_generation") != job.recovery_generation
                or not isinstance(assessment, dict)
                or assessment.get("state") != "transport_retry_eligible"
                or assessment.get("dispatch_authorized") is not False
                or not isinstance(assessment.get("not_before"), str)
            ):
                raise ConversationConflict("The provider outcome needs checking before retry.")
            try:
                not_before = datetime.fromisoformat(assessment["not_before"])
                if not_before.tzinfo is None or utc(now) < utc(not_before):
                    raise ValueError
            except ValueError:
                raise ConversationConflict(
                    "This analysis is waiting before it can retry."
                ) from None
        checkpoint = task.intent.get("checkpoint")
        if not isinstance(checkpoint, dict):
            raise ConversationConflict("The immutable stage input is unavailable.")
        if first is not None and (
            task.stage != first.stage
            or first.intent is None
            or base_cache_key(checkpoint) != base_cache_key(first.intent["checkpoint"])
        ):
            raise ConversationConflict("The retry lineage changed its original stage input.")
        first = task if first is None else first
        current = predecessor_id(checkpoint)
    assert first is not None
    return first


async def successor_plan[ServicePlanT: ServicePlan](
    database: AsyncSession,
    recording: ConversationRecording,
    plan: ServicePlanT,
    run_id: UUID,
    *,
    now: datetime,
) -> ServicePlanT:
    """Reuse exact source/input/route, with a distinct immutable checkpoint key."""
    task = await require_retry_predecessor(database, recording, run_id, now=now)
    assert task.intent is not None
    checkpoint = task.intent["checkpoint"]
    expected = replace(plan.checkpoint, replicate=checkpoint.get("replicate", "")).as_dict()
    # Input identity excludes the future provider output; all other checkpoint
    # metadata must match. No new route, prompt, source or profile is inferred.
    if task.stage != plan.checkpoint.stage or content_hash(checkpoint) != content_hash(expected):
        raise ConversationConflict("The retry input differs from its original stage.")
    result = replace(plan, checkpoint=replace(plan.checkpoint, replicate=f"retry:{run_id}"))
    return result
