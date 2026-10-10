"""Owner-requested bounded local successors, using the retained upload consent."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import func, select

from ac_platform.conversation_intelligence.application import (
    LOCAL_JOB,
    ConversationApplication,
    ConversationConflict,
)
from ac_platform.conversation_intelligence.contracts import QuoteAcceptance, RunIntent
from ac_platform.conversation_intelligence.entitlements import ExecutionPermission, Quote
from ac_platform.conversation_intelligence.models import (
    ConversationPermission,
    ConversationQuote,
    ConversationRecording,
    ConversationRun,
)
from ac_platform.conversation_intelligence.processing_actor import ProcessingActor
from ac_platform.outbox.models import Job

if TYPE_CHECKING:
    from ac_platform.http.conversation_intake import ConversationIntakeRuntime


async def retry_local_analysis(
    app: ConversationApplication,
    runtime: ConversationIntakeRuntime,
    actor: ProcessingActor,
    recording: ConversationRecording,
    *,
    key: str,
) -> dict[str, Any]:
    now = await app.admit(actor)
    live = await app.database.scalar(
        select(ConversationRun.id)
        .join(Job, Job.id == ConversationRun.job_id)
        .where(
            ConversationRun.recording_id == recording.id,
            ConversationRun.generation == recording.generation,
            ConversationRun.state.in_(("queued", "running")),
            Job.kind == LOCAL_JOB,
            Job.status != "dead_letter",
        )
        .limit(1)
    )
    if live is not None:
        raise ConversationConflict("Another local retry is already waiting or working.")
    previous = (
        await app.database.execute(
            select(ConversationRun, Job)
            .join(Job, Job.id == ConversationRun.job_id)
            .where(
                ConversationRun.recording_id == recording.id,
                ConversationRun.tenant_id == actor.tenant_id,
                ConversationRun.person_id == actor.person_id,
                ConversationRun.generation == recording.generation,
                Job.kind == LOCAL_JOB,
            )
            .order_by(
                ConversationRun.created_at.desc(), Job.created_at.desc(), ConversationRun.id.desc()
            )
            .limit(1)
            .with_for_update(of=(ConversationRun, Job), skip_locked=True)
        )
    ).first()
    if previous is None:
        raise ConversationConflict(
            "The local analysis is still being recovered. Try again shortly."
        )
    run, job = previous
    if (
        job.status != "dead_letter"
        or job.lease_token is not None
        or job.external_side_effect
        or job.provider_receipt is not None
    ):
        raise ConversationConflict(
            "The local analysis is still being recovered. Try again shortly."
        )
    count = await app.database.scalar(
        select(func.count())
        .select_from(ConversationRun)
        .join(Job, Job.id == ConversationRun.job_id)
        .where(
            ConversationRun.recording_id == recording.id,
            ConversationRun.generation == recording.generation,
            Job.kind == LOCAL_JOB,
        )
    )
    if count is None or count >= 3:
        raise ConversationConflict("This call has reached its local analysis retry limit.")
    try:
        original = await app.database.get(ConversationQuote, UUID(job.payload["quote_id"]))
    except (KeyError, ValueError, TypeError):
        original = None
    if original is None or original.recording_id != recording.id or original.revoked_at is not None:
        raise ConversationConflict("The saved upload approval is unavailable.")
    quote = Quote.from_dict(original.quote)
    permission = await app.database.get(ConversationPermission, recording.permission_id)
    if (
        permission is None
        or quote.privacy_revision != runtime.policy.privacy_revision
        or quote.retention_ref != runtime.policy.retention_ref
        or quote.professional_gate_ref != runtime.policy.authorization_ref
        or quote.recipe_revision != runtime.policy.acoustic_recipe
        or quote.provider_id != "local"
        or quote.operation != "inspect_audioatlas"
        or quote.max_cost_paise != 0
        or quote.entitlement_seconds != 0
        or quote.account_id != str(actor.person_id)
        or original.budget_scope_id != runtime.policy.budget_scope_id
    ):
        raise ConversationConflict(
            "The saved local approval changed. The AC team needs to check it."
        )
    # The explicit retry action carries the identical, current private upload
    # terms into a fresh local quote. No external-provider consent is implied.
    identifier = uuid4()
    fresh = replace(
        quote,
        quote_id=str(identifier),
        created_at_epoch=int(now.timestamp()),
        expires_at_epoch=min(
            int((now + timedelta(minutes=15)).timestamp()), int(permission.expires_at.timestamp())
        ),
    )
    execution = replace(
        ExecutionPermission.from_dict(original.execution_permission),
        quote_fingerprint=fresh.fingerprint,
        expires_at_epoch=fresh.expires_at_epoch,
    )
    row = ConversationQuote(
        id=identifier,
        tenant_id=actor.tenant_id,
        person_id=actor.person_id,
        recording_id=recording.id,
        budget_scope_id=original.budget_scope_id,
        quote=fresh.as_dict(),
        execution_permission=execution.as_dict(),
    )
    app.database.add(row)
    await app.database.flush()
    await runtime.intake(app).accept(
        actor,
        identifier,
        QuoteAcceptance(
            quote_fingerprint=fresh.fingerprint,
            privacy_revision=fresh.privacy_revision,
            accepted=True,
        ),
    )
    successor = await app.request_run(
        actor,
        RunIntent(
            recording_id=recording.id,
            source_revision=str(recording.source_revision),
            quote_id=identifier,
            recipe_revision=fresh.recipe_revision,
        ),
        key="local-retry:" + hashlib.sha256(key.encode()).hexdigest(),
    )
    return {
        "retry_kind": "local",
        "recording_id": str(recording.id),
        "run_id": successor["id"],
        "state": successor["state"],
    }
