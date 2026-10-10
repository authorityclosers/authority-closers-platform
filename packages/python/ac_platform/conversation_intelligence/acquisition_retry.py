"""Owner retry prepares fresh bounded consent and preserves the failed attempt."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import select

from ac_platform.conversation_intelligence.application import (
    LOCAL_JOB,
    ConversationApplication,
    ConversationConflict,
    ConversationDenied,
)
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.inference import ConversationInference
from ac_platform.conversation_intelligence.models import (
    ConversationInferenceTask,
    ConversationProcessingPlan,
    ConversationRecording,
    ConversationRun,
)
from ac_platform.conversation_intelligence.processing_actor import ProcessingActor
from ac_platform.conversation_intelligence.processing_plan import (
    ConversationProcessingPlans,
    manifest_for,
)
from ac_platform.conversation_intelligence.report_minutes import ReportMinutes
from ac_platform.conversation_intelligence.reporting_pipeline import ReportingPipeline, StageRequest
from ac_platform.conversation_intelligence.safe_stage_retry import require_retry_predecessor
from ac_platform.kernel.authz import ActorContext
from ac_platform.outbox.models import Job

if TYPE_CHECKING:
    from ac_platform.http.conversation_intake import ConversationIntakeRuntime


async def prepare_analysis_retry(
    ownership: GuestOwnership,
    runtime: ConversationIntakeRuntime,
    submission_id: UUID,
    *,
    key: str,
    token: str | None = None,
    actor: ActorContext | None = None,
) -> dict[str, Any]:
    scope = await ownership.require_submission_owner(submission_id, token=token, actor=actor)
    if not scope.claimed_account:
        raise ConversationDenied(
            "Claim this saved call with the same AC account before processing it."
        )
    app = ConversationApplication(ownership.database, clock=ownership.clock)
    processing = ProcessingActor(
        scope.processing_person_id, scope.tenant_id, scope.processing_lease_id
    )
    intent = {"submission_id": str(submission_id)}

    async def saved_retry(identifier: UUID) -> dict[str, Any]:
        row = await ownership.database.get(ConversationProcessingPlan, identifier)
        if row is not None and row.erased_at is None and row.recording_id == scope.recording_id:
            return ConversationProcessingPlans.view(row, include_report_options=True)
        local = await ownership.database.get(ConversationRun, identifier)
        job = None if local is None else await ownership.database.get(Job, local.job_id)
        if (
            local is None
            or local.recording_id != scope.recording_id
            or job is None
            or job.kind != LOCAL_JOB
        ):
            raise ConversationConflict("The saved retry is unavailable.")
        view = await app._run_view(processing, local.id)
        return {
            "retry_kind": "local",
            "recording_id": str(local.recording_id),
            "run_id": str(local.id),
            "state": view["state"],
        }

    replay = await app._replay(processing, key, "processing_retry_prepared", intent)
    if replay is not None and replay.result_id is not None:
        return await saved_retry(replay.result_id)
    plan = await ownership.database.scalar(
        select(ConversationProcessingPlan)
        .where(
            ConversationProcessingPlan.recording_id == scope.recording_id,
            ConversationProcessingPlan.tenant_id == scope.tenant_id,
            ConversationProcessingPlan.person_id == scope.processing_person_id,
            ConversationProcessingPlan.erased_at.is_(None),
        )
        .order_by(
            ConversationProcessingPlan.created_at.desc(), ConversationProcessingPlan.id.desc()
        )
        .limit(1)
    )
    if plan is not None and plan.state not in {"held", "cancelled"}:
        # Another tab can commit this exact command between the first replay
        # read and the latest-plan read. Recover that receipt before refusing.
        replay = await app._replay(processing, key, "processing_retry_prepared", intent)
        if replay is not None and replay.result_id is not None:
            return await saved_retry(replay.result_id)
        raise ConversationConflict("This call does not have a failed analysis to retry.")
    recording = await ownership.database.get(ConversationRecording, scope.recording_id)
    if recording is None or recording.state != "ready":
        raise ConversationConflict("The saved recording is unavailable for retry.")
    local_run = await ownership.database.scalar(
        select(ConversationRun)
        .join(Job, Job.id == ConversationRun.job_id)
        .where(
            ConversationRun.recording_id == recording.id,
            ConversationRun.generation == recording.generation,
            Job.kind == LOCAL_JOB,
        )
        .order_by(
            ConversationRun.created_at.desc(), Job.created_at.desc(), ConversationRun.id.desc()
        )
        .limit(1)
    )
    local_retry = local_run is not None and local_run.state != "completed"
    if not local_retry and runtime.authority is None:
        raise ConversationConflict("Provider analysis is not enabled for this upload yet.")
    tasks = list(
        await ownership.database.scalars(
            select(ConversationInferenceTask)
            .where(
                ConversationInferenceTask.recording_id == recording.id,
                ConversationInferenceTask.generation == recording.generation,
                ConversationInferenceTask.erased_at.is_(None),
                ConversationInferenceTask.state.in_(("failed", "uncertain")),
            )
            .order_by(ConversationInferenceTask.created_at.desc())
        )
    )
    predecessor = (
        None
        if local_retry or not tasks
        else await require_retry_predecessor(
            ownership.database, recording, tasks[0].run_id, now=ownership.clock()
        )
    )
    if (
        not local_retry
        and not tasks
        and await ownership.database.scalar(
            select(ConversationInferenceTask.run_id)
            .where(
                ConversationInferenceTask.recording_id == recording.id,
                ConversationInferenceTask.state.in_(("queued", "running")),
                ConversationInferenceTask.erased_at.is_(None),
            )
            .limit(1)
        )
    ):
        raise ConversationConflict(
            "The failed analysis is still being recovered. Try again shortly."
        )
    usage_id = await ownership.sessions.reserve_report_retry(
        submission_id, key=key, token=token, actor=actor
    )
    grant = await ownership.ensure_processing_continuation(
        submission_id, key=key, token=token, actor=actor
    )
    processing = await ownership.resolve_processing_actor(submission_id, token=token, actor=actor)
    replay = await app._replay(processing, key, "processing_retry_prepared", intent)
    if replay is not None and replay.result_id is not None:
        return await saved_retry(replay.result_id)
    latest_plan_id = await ownership.database.scalar(
        select(ConversationProcessingPlan.id)
        .where(
            ConversationProcessingPlan.recording_id == recording.id,
            ConversationProcessingPlan.erased_at.is_(None),
        )
        .order_by(
            ConversationProcessingPlan.created_at.desc(), ConversationProcessingPlan.id.desc()
        )
        .limit(1)
    )
    if latest_plan_id != (None if plan is None else plan.id):
        raise ConversationConflict("Another retry was prepared. Refresh this call to review it.")
    if local_retry:
        from ac_platform.conversation_intelligence.local_analysis_retry import retry_local_analysis

        local_view = await retry_local_analysis(app, runtime, processing, recording, key=key)
        await app._receipt(
            processing,
            key,
            "processing_retry_prepared",
            intent,
            UUID(local_view["run_id"]),
            ownership.clock(),
        )
        return local_view
    assert runtime.authority is not None
    view = await ConversationProcessingPlans(app, runtime.authority, runtime.storage).quote(
        processing,
        recording.id,
        key="retry-plan:" + hashlib.sha256(key.encode()).hexdigest(),
        continuation_grant_id=grant,
        retry_of=None if predecessor is None else predecessor.run_id,
        report_language=None if plan is None else manifest_for(plan).report_language,
    )
    # Validate the existing source/provider cap before committing a renewed
    # customer reservation. This prepares a quote, never a provider dispatch;
    # the coordinator reuses it after the owner accepts the new bounded plan.
    service = ConversationInference(app, authority=runtime.authority)
    if predecessor is None:
        retry_plan = await ownership.database.get(ConversationProcessingPlan, UUID(view["id"]))
        assert retry_plan is not None
        await ReportMinutes(ownership.database).bind_retry_plan(usage_id, retry_plan)
        await app._receipt(
            processing, key, "processing_retry_prepared", intent, retry_plan.id, ownership.clock()
        )
        return view
    assert predecessor.intent is not None
    request = (
        None
        if predecessor.stage == "C2"
        else StageRequest.model_validate(predecessor.intent["request"]).model_copy(
            update={"retry_of": predecessor.run_id}
        )
    )
    stage = (
        await service.plan_transcription(recording, retry_of=predecessor.run_id)
        if request is None
        else await ReportingPipeline(service).plan(recording, request)
    )
    await runtime.authority.issue(
        app,
        processing,
        recording.id,
        key=f"plan:{view['id']}:{stage.checkpoint.cache_key}",
        request=request,
        retry_of=predecessor.run_id if request is None else None,
    )
    retry_plan = await ownership.database.get(ConversationProcessingPlan, UUID(view["id"]))
    assert retry_plan is not None
    await ReportMinutes(ownership.database).bind_retry_plan(usage_id, retry_plan)
    await app._receipt(
        processing, key, "processing_retry_prepared", intent, UUID(view["id"]), ownership.clock()
    )
    return view
