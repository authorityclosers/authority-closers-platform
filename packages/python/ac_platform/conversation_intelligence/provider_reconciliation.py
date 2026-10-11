"""Append-only operator evidence for one provider-confirmed unaccepted C2 send.

This module never calls a provider, clears a dispatch fence, settles money or
retries a call. Unknown/completed outcomes must use their own recovery path.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.application import ConversationConflict, utc
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.entitlements import Quote
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.inference import binding_for
from ac_platform.conversation_intelligence.models import (
    ConversationInferenceTask,
    ConversationProcessingPlan,
    ConversationQuote,
    ConversationRecording,
    ConversationRun,
)
from ac_platform.conversation_intelligence.report_minutes import ReportMinutes
from ac_platform.outbox.models import Job
from ac_platform.outbox.repository import RecoveryStateRepository
from ac_platform.tenancy.models import Membership

ACTION = "conversation.provider_outcome_reconciled"
_SHA256 = r"^[a-f0-9]{64}$"


class C2OutcomeEvidence(BaseModel):
    """Metadata-only attestation; retain the actual confirmation privately."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_id: Literal["ac.sales-xray.c2-outcome-evidence/1"] = Field(alias="schema")
    environment: Literal["development", "staging", "production"]
    issue: Literal["AUT-1801"]
    approval_reference: str = Field(
        pattern=r"^(AUT-[0-9]+|https://github.com/authorityclosers/authority-closers-platform/"
        r"issues/[0-9]+(?:#issuecomment-[0-9]+)?)$"
    )
    approver_person_id: UUID
    operator_person_id: UUID
    tenant_id: UUID
    submission_id: UUID
    recording_id: UUID
    run_id: UUID
    job_id: UUID
    generation: int = Field(strict=True, ge=1)
    recovery_generation: int = Field(strict=True, ge=1)
    attempt_count: int = Field(strict=True, ge=1, le=25)
    provider_attempt_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,254}$")
    dispatch_started_at: AwareDatetime
    source_sha256: str = Field(pattern=_SHA256)
    quote_fingerprint: str = Field(pattern=_SHA256)
    input_sha256: str = Field(pattern=_SHA256)
    provider: Literal["elevenlabs"]
    model: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.:/-]{0,127}$")
    verified_at: AwareDatetime
    verification_method: Literal["provider_request_history", "provider_support"]
    provider_request_id_sha256: str = Field(pattern=_SHA256)
    provider_confirmation_sha256: str = Field(pattern=_SHA256)
    outcome: Literal["not_accepted", "completed", "unknown"]


def _require_binding(
    proof: C2OutcomeEvidence,
    recording: ConversationRecording,
    task: ConversationInferenceTask,
    job: Job,
    quote: Quote,
    *,
    now: datetime,
) -> None:
    if (
        proof.outcome != "not_accepted"
        or proof.tenant_id != recording.tenant_id
        or proof.recording_id != recording.id
        or proof.source_sha256 != recording.source_sha256
        or proof.generation != recording.generation
        or task.tenant_id != recording.tenant_id
        or task.person_id != recording.person_id
        or task.recording_id != recording.id
        or task.generation != recording.generation
        or task.run_id != proof.run_id
        or task.job_id != proof.job_id
        or task.stage != "C2"
        or task.erased_at is not None
        or task.state not in {"failed", "uncertain"}
        or task.checkpoint_id is not None
        or task.intent is None
        or content_hash(task.intent) != task.intent_sha256
        or job.id != proof.job_id
        or job.tenant_id != recording.tenant_id
        or job.kind != "conversation.infer_provider.v1"
        or job.status != "dead_letter"
        or not job.external_side_effect
        or job.lease_token is not None
        or job.leased_until is not None
        or job.provider_receipt is not None
        or job.provider_receipt_digest is not None
        or job.payload.get("run_id") != str(task.run_id)
        or job.recovery_generation != proof.recovery_generation
        or job.attempt_count != proof.attempt_count
        or job.dispatch_started_at is None
        or utc(job.dispatch_started_at) != utc(proof.dispatch_started_at)
        or job.provider_idempotency_key != proof.provider_attempt_id
        or quote.fingerprint != proof.quote_fingerprint
        or quote.input_sha256 != proof.input_sha256
        or quote.provider_id != proof.provider
        or quote.provider_model != proof.model
        or quote.source != binding_for(recording)
        or not utc(proof.dispatch_started_at) <= utc(proof.verified_at) <= utc(now)
    ):
        raise ConversationConflict(
            "The provider confirmation does not match this terminal C2 attempt."
        )


async def record_c2_outcome(
    database: AsyncSession,
    proof: C2OutcomeEvidence,
    *,
    environment: str,
    now: datetime,
    apply: bool = False,
) -> dict[str, Any]:
    """Caller owns one transaction; default dry-run appends nothing."""
    try:
        proof = C2OutcomeEvidence.model_validate(proof.model_dump(mode="json", by_alias=True))
    except ValueError:
        raise ConversationConflict("The provider confirmation metadata is invalid.") from None
    if proof.environment != environment or proof.outcome != "not_accepted":
        raise ConversationConflict("A confirmed unaccepted provider request is required.")
    recovery = await RecoveryStateRepository(database).require_ready(lock=True, shared_lock=True)
    # Match owner-command lock order. Recording custody serializes owner retry.
    member = await database.get(
        Membership, (proof.tenant_id, proof.approver_person_id), with_for_update=True
    )
    operator = await database.get(
        Membership, (proof.tenant_id, proof.operator_person_id), with_for_update=True
    )
    if (
        member is None
        or member.role != "owner"
        or member.status != "active"
        or member.ended_at is not None
        or operator is None
        or operator.role not in {"owner", "admin"}
        or operator.status != "active"
        or operator.ended_at is not None
    ):
        raise ConversationConflict("A current owner approval and named operator are required.")
    recording = await database.get(ConversationRecording, proof.recording_id, with_for_update=True)
    link = await database.get(ConversationGuestSubmission, (proof.tenant_id, proof.submission_id))
    if (
        recording is None
        or recording.state != "ready"
        or link is None
        or link.recording_id != recording.id
        or link.person_id != recording.person_id
        or link.source_sha256 != proof.source_sha256
        or recovery.generation != proof.recovery_generation
    ):
        raise ConversationConflict(
            "The exact retained submission and recovery generation are required."
        )
    await ReportMinutes(database)._lock(link.usage_id, proof.tenant_id)
    task = await database.get(ConversationInferenceTask, proof.run_id, with_for_update=True)
    job = await database.get(Job, proof.job_id, with_for_update=True)
    run = await database.get(ConversationRun, proof.run_id, with_for_update=True)
    quoted = None if task is None else await database.get(ConversationQuote, task.quote_id)
    if (
        task is None
        or job is None
        or run is None
        or quoted is None
        or run.state != "failed"
        or (run.tenant_id, run.person_id, run.recording_id, run.generation, run.job_id)
        != (recording.tenant_id, recording.person_id, recording.id, recording.generation, job.id)
    ):
        raise ConversationConflict("The terminal provider task and run are required.")
    _require_binding(proof, recording, task, job, Quote.from_dict(quoted.quote), now=now)
    active = await database.scalar(
        select(ConversationProcessingPlan.id).where(
            ConversationProcessingPlan.recording_id == recording.id,
            ConversationProcessingPlan.state == "active",
            ConversationProcessingPlan.erased_at.is_(None),
        )
    )
    minute = await ReportMinutes(database).latest(link.usage_id)
    if active is not None or minute is None or minute.kind != "released":
        raise ConversationConflict(
            "Stop active processing and verify released customer minutes first."
        )
    payload = {
        "schema": "ac.sales-xray.provider-outcome-reconciliation/1",
        "evidence": proof.model_dump(mode="json", by_alias=True),
        "evidence_sha256": content_hash(proof.model_dump(mode="json", by_alias=True)),
        "dispatch_authorized": False,
        "provider_charge_state": "unresolved",
    }
    prior = await database.scalar(
        select(AuditEvent).where(
            AuditEvent.tenant_id == proof.tenant_id,
            AuditEvent.action == ACTION,
            AuditEvent.resource_type == "job",
            AuditEvent.resource_id == str(job.id),
        )
    )
    if prior is not None and prior.payload != payload:
        raise ConversationConflict("The provider confirmation conflicts with retained history.")
    run_id = uuid4()
    event = prior
    if apply and event is None:
        event = await AuditRepository(database).append(
            tenant_id=proof.tenant_id,
            actor_person_id=proof.operator_person_id,
            actor_type="operator",
            action=ACTION,
            resource_type="job",
            resource_id=job.id,
            payload=payload,
            request_id=str(run_id),
            reason="AUT-1801 approved C2 outcome; no dispatch or settlement.",
            now=now,
        )
    before = {"task_state": task.state, "job_state": job.status, "minute_state": minute.kind}
    return {
        "run_id": str(run_id),
        "issue": proof.issue,
        "environment": environment,
        "submission_id": str(proof.submission_id),
        "job_id": str(job.id),
        "approver_person_id": str(proof.approver_person_id),
        "operator_person_id": str(proof.operator_person_id),
        "before": {**before, "reconciliation_recorded": prior is not None},
        "after": {**before, "reconciliation_recorded": apply or prior is not None},
        "applied": apply,
        "event_id": None if event is None else str(event.id),
        "evidence_sha256": payload["evidence_sha256"],
        "dispatch_authorized": False,
        "provider_charge_state": "unresolved",
    }


async def has_reconciled_c2_outcome(
    database: AsyncSession,
    recording: ConversationRecording,
    task: ConversationInferenceTask,
    job: Job,
    *,
    now: datetime,
) -> bool:
    """Existing retry admission remains responsible for all successor authority."""
    if task.stage != "C2":
        return False
    event = await database.scalar(
        select(AuditEvent).where(
            AuditEvent.tenant_id == recording.tenant_id,
            AuditEvent.action == ACTION,
            AuditEvent.resource_type == "job",
            AuditEvent.resource_id == str(job.id),
        )
    )
    if event is None:
        return False
    try:
        payload = event.payload
        proof = C2OutcomeEvidence.model_validate(payload["evidence"])
        quoted = await database.get(ConversationQuote, task.quote_id)
        if (
            quoted is None
            or payload.get("schema") != "ac.sales-xray.provider-outcome-reconciliation/1"
            or payload.get("evidence_sha256") != content_hash(payload["evidence"])
            or payload.get("dispatch_authorized") is not False
            or payload.get("provider_charge_state") != "unresolved"
            or event.actor_type != "operator"
            or event.actor_person_id != proof.operator_person_id
        ):
            raise ValueError
        _require_binding(proof, recording, task, job, Quote.from_dict(quoted.quote), now=now)
    except (KeyError, TypeError, ValueError, ConversationConflict):
        raise ConversationConflict("The provider outcome reconciliation was fenced.") from None
    return True
