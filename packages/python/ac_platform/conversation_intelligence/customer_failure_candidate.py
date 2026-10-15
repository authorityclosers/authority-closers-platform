"""Locked canonical recovery facts for the future customer settlement adapter.

This internal context neither settles usage nor executes work. No HTTP route or
worker calls it yet. Its caller must eventually persist settlement, paired
snapshots and audit in this same transaction, after the reserved schema change.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import compute_audit_hash
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionSettlement,
    ConversationAcquisitionUsage,
)
from ac_platform.conversation_intelligence.acquisition_sessions import AcquisitionSessions
from ac_platform.conversation_intelligence.application import ConversationConflict, utc
from ac_platform.conversation_intelligence.checkpoints import SourceBinding
from ac_platform.conversation_intelligence.customer_terminal_receipt import (
    CustomerTerminalFailureReceipt,
)
from ac_platform.conversation_intelligence.guest_models import (
    ConversationGuestSubmission,
    ConversationProcessingLease,
    ConversationProcessingPrincipal,
)
from ac_platform.conversation_intelligence.inference import INFERENCE_JOB
from ac_platform.conversation_intelligence.models import (
    ConversationInferenceTask,
    ConversationRecording,
    ConversationReportDraft,
    ConversationRun,
)
from ac_platform.conversation_intelligence.processing_actor import ProcessingActor
from ac_platform.identity.models import Person
from ac_platform.outbox.models import Job, OperationsRecoveryState
from ac_platform.tenancy.models import Membership


def _unavailable() -> ConversationConflict:
    return ConversationConflict("Canonical customer failure evidence is unavailable.")


@asynccontextmanager
async def locked_recovered_customer_failure(
    database: AsyncSession,
    *,
    actor: ProcessingActor,
    run_id: UUID,
    event_id: UUID,
    allow_terminal_replay: bool = False,
) -> AsyncIterator[CustomerTerminalFailureReceipt]:
    """Recheck one exact recovery under locks in a fresh caller session.

    Expired browser/provider windows do not authorize new work and do not erase
    failed-work evidence. This context checks persisted processing/source
    identity; it is never a substitute for dispatch or customer read authority.
    Contended job/task/run locks fail closed instead of waiting behind a worker
    that already holds a job lock and needs the processing/source locks.
    """
    if (
        not isinstance(actor, ProcessingActor)
        or any(
            type(value) is not UUID
            for value in (actor.tenant_id, actor.person_id, actor.processing_lease_id)
        )
        or type(run_id) is not UUID
        or type(event_id) is not UUID
        or type(allow_terminal_replay) is not bool
        or database.in_transaction()
        or database.new
        or database.dirty
        or database.deleted
    ):
        raise _unavailable()
    async with database.begin():
        await AcquisitionSessions(
            database, tenant_id=actor.tenant_id, policy_revision="terminal-failure-v1"
        )._admit(mutation=True)
        recovery = await database.scalar(
            select(OperationsRecoveryState)
            .where(OperationsRecoveryState.id == 1)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if recovery is None or recovery.status != "ready":
            raise _unavailable()
        lock = int.from_bytes(
            hashlib.sha256(b"processing:" + actor.processing_lease_id.bytes).digest()[:8],
            "big",
            signed=True,
        )
        await database.execute(select(func.pg_advisory_xact_lock(lock)))
        admission = (
            await database.execute(
                select(ConversationGuestSubmission, ConversationProcessingLease)
                .join(
                    ConversationProcessingLease,
                    ConversationProcessingLease.id
                    == ConversationGuestSubmission.processing_lease_id,
                )
                .join(
                    ConversationProcessingPrincipal,
                    ConversationProcessingPrincipal.id == ConversationProcessingLease.principal_id,
                )
                .where(
                    ConversationGuestSubmission.tenant_id == actor.tenant_id,
                    ConversationGuestSubmission.person_id == actor.person_id,
                    ConversationGuestSubmission.processing_lease_id == actor.processing_lease_id,
                    ConversationProcessingLease.tenant_id == actor.tenant_id,
                    ConversationProcessingLease.person_id == actor.person_id,
                    ConversationProcessingLease.usage_id == ConversationGuestSubmission.usage_id,
                    ConversationProcessingLease.revoked_at.is_(None),
                    ConversationProcessingPrincipal.tenant_id == actor.tenant_id,
                    ConversationProcessingPrincipal.person_id == actor.person_id,
                    ConversationProcessingPrincipal.revoked_at.is_(None),
                )
                .with_for_update(read=True)
                .execution_options(populate_existing=True)
            )
        ).first()
        if admission is None:
            raise _unavailable()
        link, lease = admission
        person = await database.scalar(
            select(Person)
            .join(Membership, Membership.person_id == Person.id)
            .where(
                Person.id == actor.person_id,
                Person.status == "active",
                Person.email.is_(None),
                Person.email_verified_at.is_(None),
                Membership.tenant_id == actor.tenant_id,
                Membership.role == "processing",
                Membership.status == "active",
                Membership.ended_at.is_(None),
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if person is None:
            raise _unavailable()
        recording = await database.scalar(
            select(ConversationRecording)
            .where(
                ConversationRecording.id == link.recording_id,
                ConversationRecording.tenant_id == actor.tenant_id,
                ConversationRecording.person_id == actor.person_id,
                ConversationRecording.source_sha256 == link.source_sha256,
                ConversationRecording.state == "ready",
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if recording is None:
            raise _unavailable()
        candidate = (
            await database.execute(
                select(Job, ConversationInferenceTask, ConversationRun)
                .join(ConversationInferenceTask, ConversationInferenceTask.job_id == Job.id)
                .join(ConversationRun, ConversationRun.id == ConversationInferenceTask.run_id)
                .where(
                    ConversationRun.id == run_id,
                    ConversationRun.job_id == Job.id,
                    Job.tenant_id == actor.tenant_id,
                    Job.recovery_generation == recovery.generation,
                    ConversationInferenceTask.tenant_id == actor.tenant_id,
                    ConversationInferenceTask.person_id == actor.person_id,
                    ConversationInferenceTask.recording_id == recording.id,
                    ConversationInferenceTask.processing_lease_id == lease.id,
                    ConversationInferenceTask.session_id.is_(None),
                    ConversationInferenceTask.generation == recording.generation,
                    ConversationRun.tenant_id == actor.tenant_id,
                    ConversationRun.person_id == actor.person_id,
                    ConversationRun.recording_id == recording.id,
                    ConversationRun.generation == recording.generation,
                )
                .with_for_update(
                    of=(Job, ConversationInferenceTask, ConversationRun), skip_locked=True
                )
                .execution_options(populate_existing=True)
            )
        ).first()
        if candidate is None:
            raise _unavailable()
        job, task, run = candidate
        if (
            job.kind != INFERENCE_JOB
            or not job.external_side_effect
            or job.status != "dead_letter"
            or job.lease_token is not None
            or job.leased_until is not None
            or task.state not in {"failed", "uncertain"}
            or task.erased_at is not None
            or task.checkpoint_id is not None
            or run.state != "failed"
            or run.completed_at is None
        ):
            raise _unavailable()
        usage = await database.scalar(
            select(ConversationAcquisitionUsage)
            .where(
                ConversationAcquisitionUsage.id == link.usage_id,
                ConversationAcquisitionUsage.tenant_id == actor.tenant_id,
                ConversationAcquisitionUsage.submission_id == link.submission_id,
                ConversationAcquisitionUsage.source_sha256 == recording.source_sha256,
            )
            # Publication can hold usage while inserting a draft whose foreign
            # keys need the run/source locks held above. Refuse contention;
            # waiting here would invert those locks and deadlock publication.
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        if usage is None:
            raise _unavailable()
        settlement = await database.get(
            ConversationAcquisitionSettlement, usage.id, populate_existing=True
        )
        # A retained draft alone is not delivery proof. It needs reconciliation
        # and cannot qualify for this automatic failed-work candidate either.
        report = await database.scalar(
            select(ConversationReportDraft.id)
            .where(
                ConversationReportDraft.tenant_id == actor.tenant_id,
                ConversationReportDraft.person_id == actor.person_id,
                ConversationReportDraft.recording_id == recording.id,
            )
            .limit(1)
        )
        live = await database.scalar(
            select(ConversationRun.id)
            .where(
                ConversationRun.tenant_id == actor.tenant_id,
                ConversationRun.person_id == actor.person_id,
                ConversationRun.recording_id == recording.id,
                ConversationRun.state.in_(("queued", "running")),
            )
            .limit(1)
        )
        event = await database.scalar(
            select(AuditEvent).where(
                AuditEvent.id == event_id, AuditEvent.tenant_id == actor.tenant_id
            )
        )
        expected = {
            "schema": "ac.sales_xray.provider_job_recovery/1",
            "run_id": str(run.id),
            "stage": task.stage,
            "claim_count": job.attempt_count,
            "claim_limit": job.max_attempts,
            "recovery_generation": recovery.generation,
            "dispatch_started": job.dispatch_started_at is not None,
            "task_state": task.state,
            "run_state": run.state,
        }
        if (
            (settlement is not None and not allow_terminal_replay)
            or report is not None
            or live is not None
            or event is None
            or event.action != "conversation.provider_job_recovery_required"
            or event.actor_type != "system"
            or event.actor_person_id is not None
            or event.session_id is not None
            or event.resource_type != "job"
            or event.resource_id != str(job.id)
            or event.payload != expected
            or utc(event.occurred_at) != utc(run.completed_at)
        ):
            raise _unavailable()
        actual_hash = compute_audit_hash(
            event_id=event.id,
            tenant_id=event.tenant_id,
            sequence_no=event.sequence_no,
            actor_person_id=event.actor_person_id,
            actor_type=event.actor_type,
            session_id=event.session_id,
            action=event.action,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            payload=event.payload,
            reason=event.reason,
            request_id=event.request_id,
            occurred_at=event.occurred_at,
            previous_hash=event.previous_hash,
            recorded_at=event.recorded_at,
        )
        if actual_hash != event.event_hash:
            raise _unavailable()
        receipt = CustomerTerminalFailureReceipt(
            source=SourceBinding(
                str(actor.tenant_id),
                str(recording.id),
                recording.source_sha256,
                str(recording.source_revision),
            ),
            usage_id=str(usage.id),
            submission_id=str(usage.submission_id),
            duration_evidence_sha256=usage.duration_evidence_sha256,
            reserved_seconds=usage.reserved_seconds,
            run_id=str(run.id),
            recovery_generation=recovery.generation,
            failure_event_id=str(event.id),
            failure_event_sha256=event.event_hash,
            completed_at_epoch=int(utc(run.completed_at).timestamp()),
        )
        if settlement is not None and (
            settlement.kind != "terminal_failure"
            or settlement.charged_seconds != 0
            or settlement.receipt_sha256 != receipt.fingerprint
        ):
            raise _unavailable()
        yield receipt
