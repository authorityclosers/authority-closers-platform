"""One bounded local source per uploader, independent of provider/ledger outcomes."""

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import aliased

from ac_platform.conversation_intelligence.acquisition_models import ConversationAcquisitionUsage
from ac_platform.conversation_intelligence.application import LOCAL_JOB
from ac_platform.conversation_intelligence.bulk_import_models import (
    ConversationRecordingImport,
    ConversationRecordingImportItem,
)
from ac_platform.conversation_intelligence.guest_models import (
    ConversationGuestSubmission,
    ConversationProcessingContinuation,
    ConversationProcessingLease,
    ConversationProcessingPrincipal,
)
from ac_platform.conversation_intelligence.models import ConversationRecording, ConversationRun
from ac_platform.outbox.models import Job

LOCAL_IMPORT_BUDGET = timedelta(hours=1)


def active_local_item(
    *, tenant_id: UUID, uploader_id: UUID, submission_id: UUID, now: datetime
) -> Select[tuple[UUID]]:
    usage, item, batch = (
        ConversationAcquisitionUsage,
        ConversationRecordingImportItem,
        ConversationRecordingImport,
    )
    link, recording, lease = (
        ConversationGuestSubmission,
        ConversationRecording,
        ConversationProcessingLease,
    )
    principal, run = ConversationProcessingPrincipal, ConversationRun
    previous, previous_job = aliased(ConversationRun), aliased(Job)
    # Match the canonical progress ordering before filtering state. An old live
    # run cannot mask a newer terminal one, or a failure mask an active retry.
    current_run = (
        select(previous.id)
        .join(previous_job, previous_job.id == previous.job_id)
        .where(
            previous.recording_id == recording.id,
            previous.tenant_id == recording.tenant_id,
            previous.person_id == recording.person_id,
            previous.generation == recording.generation,
            previous_job.kind == LOCAL_JOB,
        )
        .order_by(previous.created_at.desc(), previous_job.created_at.desc(), previous.id.desc())
        .correlate(recording)
        .limit(1)
        .scalar_subquery()
    )
    continuation = ConversationProcessingContinuation
    valid_continuation = (
        select(continuation.id)
        .where(
            continuation.processing_lease_id == lease.id,
            continuation.tenant_id == tenant_id,
            continuation.person_id == recording.person_id,
            continuation.usage_id == usage.id,
            continuation.submission_id == usage.submission_id,
            continuation.recording_id == recording.id,
            continuation.source_sha256 == recording.source_sha256,
            continuation.source_revision == recording.source_revision,
            continuation.generation == recording.generation,
            continuation.owner_person_id == usage.person_id,
            continuation.owner_visitor_id.is_(None),
            continuation.created_at >= lease.expires_at,
            continuation.expires_at > now,
        )
        .correlate(lease, usage, recording)
        .exists()
    )
    return (
        select(usage.id)
        .join(item, item.usage_id == usage.id)
        .join(batch, batch.id == item.batch_id)
        .join(link, (link.usage_id == usage.id) & (link.tenant_id == tenant_id))
        .join(recording, recording.id == link.recording_id)
        .join(lease, lease.id == link.processing_lease_id)
        .join(principal, principal.id == lease.principal_id)
        .join(run, run.id == current_run)
        .join(Job, Job.id == run.job_id)
        .where(
            usage.tenant_id == tenant_id,
            item.tenant_id == tenant_id,
            batch.tenant_id == tenant_id,
            batch.uploader_person_id == uploader_id,
            item.reused.is_(False),
            usage.submission_id != submission_id,
            link.submission_id == usage.submission_id,
            link.source_sha256 == usage.source_sha256,
            recording.tenant_id == tenant_id,
            recording.person_id == link.person_id,
            recording.source_sha256 == usage.source_sha256,
            recording.state == "ready",
            lease.tenant_id == tenant_id,
            lease.person_id == recording.person_id,
            lease.usage_id == usage.id,
            lease.revoked_at.is_(None),
            (lease.expires_at > now) | valid_continuation,
            principal.revoked_at.is_(None),
            principal.tenant_id == tenant_id,
            principal.person_id == recording.person_id,
            run.state.in_(("queued", "running")),
            run.created_at > now - LOCAL_IMPORT_BUDGET,
            Job.tenant_id == tenant_id,
            Job.status.in_(("queued", "leased", "retry_wait")),
        )
        .limit(1)
    )
