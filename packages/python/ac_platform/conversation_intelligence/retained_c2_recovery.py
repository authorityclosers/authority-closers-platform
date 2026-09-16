"""No-provider-call recovery for a retained, provider-returned C2 response.

This boundary is intentionally narrower than a retry.  It can bind one
already-retained C2 response to a later exact duplicate upload only when the
source, owner, route, input, provider receipt and private response blob all
verify.  It never changes the original task, job or ledger reservation and it
does not dispatch a provider.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import select

from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionUsage,
    ConversationVisitorClaim,
)
from ac_platform.conversation_intelligence.activation_contract import StageApproval
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationConflict,
    utc,
)
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.entitlements import ExecutionPermission, Quote
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.inference import (
    INFERENCE_JOB,
    ConversationInference,
    TranscriptionPlan,
    binding_for,
    verified_checkpoint,
)
from ac_platform.conversation_intelligence.inference_tasks import (
    InferenceTaskError,
    validate_scribe_result,
)
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationInferenceTask,
    ConversationPermission,
    ConversationPlanStageAuthorization,
    ConversationProcessingPlan,
    ConversationQuote,
    ConversationRecording,
    ConversationRun,
)
from ac_platform.conversation_intelligence.processing_actor import (
    ConversationActor,
    ProcessingActor,
    actor_columns,
)
from ac_platform.conversation_intelligence.providers import MAX_JSON_BYTES, ProviderResult
from ac_platform.conversation_intelligence.reporting_pipeline import ReportingPipeline
from ac_platform.conversation_intelligence.storage import (
    ObjectKey,
    ObjectKind,
    PrivateLocalRecordingStorage,
    StorageError,
)
from ac_platform.outbox.models import Job, JobStatus
from ac_platform.outbox.repository import (
    JobRepository,
    RecoveryStateRepository,
    canonical_receipt_digest,
)

if TYPE_CHECKING:
    from ac_platform.conversation_intelligence.authority import ConversationAuthority
    from ac_platform.conversation_intelligence.processing_plan import PlanManifest


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_REQUEST_ID = re.compile(r"[A-Za-z0-9_:-]{1,128}\Z")
_C2_VALIDATION = "transcript_schema_and_source_binding"
_RETAINED_REUSE_SCHEMA = "ac.sales-xray.retained-c2-reuse/1"
_RECEIPT_USAGE_KEYS = frozenset(
    {
        "promptTokenCount",
        "candidatesTokenCount",
        "thoughtsTokenCount",
        "cachedContentTokenCount",
        "totalTokenCount",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "input_tokens",
        "output_tokens",
    }
)


@dataclass(frozen=True, slots=True)
class _VerifiedSource:
    recording: ConversationRecording
    permission: ConversationPermission
    task: ConversationInferenceTask
    run: ConversationRun
    job: Job
    quote_row: ConversationQuote
    quote: Quote
    receipt: dict[str, Any]
    normalized: dict[str, Any]


def _conflict() -> ConversationConflict:
    return ConversationConflict("A retained transcription cannot be safely reused.")


def _safe_usage(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        raise _conflict()
    result: dict[str, int] = {}
    for key, amount in value.items():
        if (
            not isinstance(key, str)
            or key not in _RECEIPT_USAGE_KEYS
            or type(amount) is not int
            or amount < 0
            or amount > 1_000_000_000
        ):
            raise _conflict()
        result[key] = amount
    return result


def retained_c2_receipt(
    *,
    job: Job,
    source: _VerifiedSource,
    checkpoint: ConversationCheckpoint,
    input_sha256: str,
) -> dict[str, Any]:
    """Build a canonical target receipt without copying the provider blob."""

    receipt = source.receipt
    result = {
        "schema": "ac.sales-xray.provider-receipt/1",
        "idempotency_key": job.dedupe_key,
        "provider": receipt["provider"],
        "model": receipt["model"],
        "input_sha256": input_sha256,
        "response_sha256": receipt["response_sha256"],
        "provider_request_id": receipt.get("provider_request_id"),
        "checkpoint_id": str(checkpoint.id),
        "checkpoint_manifest_sha256": checkpoint.manifest_sha256,
        # The response remains in the source recording's private object
        # namespace.  The marker below proves that this is intentional.
        "raw_blob_id": str(source.task.run_id),
        "usage": dict(receipt.get("usage", {})),
        "cost_state": "reconciliation_required",
        "actual_cost_paise": None,
        "validation": _C2_VALIDATION,
        "validation_state": "validated",
        "human_approved": False,
        "retained_reuse": {
            "schema": _RETAINED_REUSE_SCHEMA,
            "provider_calls": 0,
            "source_recording_id": str(source.recording.id),
            "source_run_id": str(source.task.run_id),
            "source_response_sha256": receipt["response_sha256"],
        },
    }
    return result


class RetainedC2ReuseService:
    """Find and materialize one exact retained C2 result for a duplicate source."""

    def __init__(
        self,
        application: ConversationApplication,
        authority: ConversationAuthority,
        storage: PrivateLocalRecordingStorage,
    ) -> None:
        self.application = application
        self.database = application.database
        self.authority = authority
        self.storage = storage
        self.inference = ConversationInference(application, authority=authority)

    async def reuse(
        self,
        actor: ConversationActor,
        plan_row: ConversationProcessingPlan,
        plan_value: PlanManifest,
        recording: ConversationRecording,
        stage: TranscriptionPlan,
        approval: StageApproval,
        *,
        budget_scope_id: UUID,
        authorization_ref: str,
        key: str,
        now: datetime,
    ) -> ConversationInferenceTask | None:
        """Return a completed target task, or ``None`` when no source exists."""

        if (
            stage.checkpoint.stage != "C2"
            or approval.stage != "C2"
            or approval.source_sha256 != recording.source_sha256
            or approval.provider_id != stage.prepared.provider
            or approval.model_id != stage.prepared.model
            or approval.recipe_revision != stage.recipe_revision
            or approval.configuration_sha256
            != next(item.configuration_sha256 for item in plan_value.stages if item.stage == "C2")
        ):
            raise _conflict()
        source = await self._find_source(actor, recording, stage, approval, authorization_ref, now)
        if source is None:
            return None
        await RecoveryStateRepository(self.database).require_ready(lock=True, shared_lock=True)
        return await self._materialize(
            actor,
            plan_row,
            plan_value,
            recording,
            stage,
            approval,
            source,
            budget_scope_id=budget_scope_id,
            key=key,
            now=utc(now),
        )

    async def _find_source(
        self,
        actor: ConversationActor,
        target: ConversationRecording,
        target_stage: TranscriptionPlan,
        approval: StageApproval,
        authorization_ref: str,
        now: datetime,
    ) -> _VerifiedSource | None:
        rows = (
            await self.database.scalars(
                select(ConversationRecording)
                .where(
                    ConversationRecording.tenant_id == target.tenant_id,
                    ConversationRecording.person_id == target.person_id,
                    ConversationRecording.id != target.id,
                    ConversationRecording.source_sha256 == target.source_sha256,
                    ConversationRecording.source_bytes == target.source_bytes,
                    ConversationRecording.content_type == target.content_type,
                    ConversationRecording.source_revision == target.source_revision,
                    ConversationRecording.generation == target.generation,
                    ConversationRecording.state == "ready",
                    ConversationRecording.deleted_at.is_(None),
                )
                .order_by(ConversationRecording.created_at)
                .limit(32)
                .with_for_update(read=True)
            )
        ).all()
        for source in rows:
            source_processing_lease_id = None
            if isinstance(actor, ProcessingActor):
                source_processing_lease_id = await self._require_same_guest_owner(
                    actor, target, source
                )
            source_tasks = (
                await self.database.scalars(
                    select(ConversationInferenceTask)
                    .where(
                        ConversationInferenceTask.recording_id == source.id,
                        ConversationInferenceTask.tenant_id == target.tenant_id,
                        ConversationInferenceTask.person_id == target.person_id,
                        ConversationInferenceTask.generation == target.generation,
                        ConversationInferenceTask.stage == "C2",
                        ConversationInferenceTask.erased_at.is_(None),
                    )
                    .with_for_update()
                )
            ).all()
            if not source_tasks:
                continue
            source_plan = await self.inference.plan_transcription(source)
            matching = tuple(
                task for task in source_tasks if task.cache_key == source_plan.checkpoint.cache_key
            )
            if len(matching) != 1:
                raise _conflict()
            return await self._verify_source(
                source,
                matching[0],
                source_plan,
                target_stage,
                approval,
                now,
                authorization_ref=authorization_ref,
                source_processing_lease_id=source_processing_lease_id,
            )
        return None

    async def _require_same_guest_owner(
        self,
        actor: ProcessingActor,
        target: ConversationRecording,
        source: ConversationRecording,
    ) -> UUID:
        """Do not share an exact audio response across unrelated guest owners."""

        async def owner(recording: ConversationRecording) -> tuple[str, UUID]:
            link = await self.database.scalar(
                select(ConversationGuestSubmission).where(
                    ConversationGuestSubmission.recording_id == recording.id,
                    ConversationGuestSubmission.tenant_id == actor.tenant_id,
                    ConversationGuestSubmission.person_id == actor.person_id,
                )
            )
            if (
                link is None
                or link.tenant_id != actor.tenant_id
                or link.person_id != actor.person_id
                or link.recording_id != recording.id
                or link.source_sha256 != recording.source_sha256
                or (
                    recording.id == target.id
                    and link.processing_lease_id != actor.processing_lease_id
                )
            ):
                raise _conflict()
            usage = await self.database.get(ConversationAcquisitionUsage, link.usage_id)
            if (
                usage is None
                or usage.tenant_id != actor.tenant_id
                or usage.submission_id != link.submission_id
                or usage.source_sha256 != recording.source_sha256
            ):
                raise _conflict()
            if usage.visitor_id is None and usage.person_id is not None:
                return "person", usage.person_id
            if usage.visitor_id is None:
                raise _conflict()
            claim = await self.database.get(ConversationVisitorClaim, usage.visitor_id)
            if claim is not None and claim.tenant_id != usage.tenant_id:
                raise _conflict()
            if claim is not None:
                return "person", claim.person_id
            return "visitor", usage.visitor_id

        if await owner(target) != await owner(source):
            raise _conflict()
        source_link = await self.database.scalar(
            select(ConversationGuestSubmission).where(
                ConversationGuestSubmission.recording_id == source.id,
                ConversationGuestSubmission.tenant_id == actor.tenant_id,
                ConversationGuestSubmission.person_id == actor.person_id,
            )
        )
        if source_link is None:
            raise _conflict()
        return source_link.processing_lease_id

    async def _verify_source(
        self,
        recording: ConversationRecording,
        task: ConversationInferenceTask,
        source_plan: TranscriptionPlan,
        target_stage: TranscriptionPlan,
        approval: StageApproval,
        now: datetime,
        authorization_ref: str,
        source_processing_lease_id: UUID | None,
    ) -> _VerifiedSource:
        permission = await self.database.get(ConversationPermission, recording.permission_id)
        run = await self.database.get(ConversationRun, task.run_id)
        job = await self.database.get(Job, task.job_id)
        quote_row = await self.database.get(ConversationQuote, task.quote_id)
        if (
            permission is None
            or permission.tenant_id != recording.tenant_id
            or permission.person_id != recording.person_id
            or permission.provider != "local"
            or permission.source_sha256 != recording.source_sha256
            or not permission.permission_reference
            or not permission.retention_reference
            or permission.revoked_at is not None
            or utc(permission.expires_at) <= utc(now)
            or utc(permission.retention_until) <= utc(now)
            or run is None
            or job is None
            or quote_row is None
            or (
                source_processing_lease_id is not None
                and (
                    task.session_id is not None
                    or task.processing_lease_id != source_processing_lease_id
                )
            )
        ):
            raise _conflict()
        if (
            task.state == "completed"
            and task.checkpoint_id is not None
            or task.state in {"failed", "uncertain"}
            and task.checkpoint_id is None
        ) is False:
            raise _conflict()
        if (
            task.state not in {"completed", "failed", "uncertain"}
            or task.recording_id != recording.id
            or task.tenant_id != recording.tenant_id
            or task.person_id != recording.person_id
            or task.generation != recording.generation
            or task.input_sha256 != recording.source_sha256
            or run.recording_id != recording.id
            or run.tenant_id != recording.tenant_id
            or run.person_id != recording.person_id
            or run.generation != recording.generation
            or run.recipe_revision != source_plan.recipe_revision
            or run.job_id != task.job_id
            or run.state not in {"failed", "completed"}
            or job.tenant_id != recording.tenant_id
            or job.kind != INFERENCE_JOB
            or job.dedupe_key != f"conversation:provider:{task.run_id}"
            or job.payload != {"schema": 1, "run_id": str(task.run_id)}
            or not job.external_side_effect
            or job.recovery_generation < 1
            or job.dispatch_started_at is None
            or job.provider_idempotency_key != job.dedupe_key
            or job.status
            not in {
                JobStatus.DEAD_LETTER.value,
                JobStatus.SUCCEEDED.value,
                JobStatus.RETRY_WAIT.value,
                JobStatus.HELD.value,
            }
            or (
                task.state == "completed"
                and (run.state != "completed" or job.status != JobStatus.SUCCEEDED.value)
            )
            or (
                task.state in {"failed", "uncertain"}
                and (
                    run.state != "failed"
                    or job.status
                    not in {
                        JobStatus.DEAD_LETTER.value,
                        JobStatus.RETRY_WAIT.value,
                        JobStatus.HELD.value,
                    }
                )
            )
            or job.provider_receipt is None
            or job.provider_receipt_digest is None
            or not isinstance(job.provider_receipt, dict)
            or canonical_receipt_digest(job.provider_receipt) != job.provider_receipt_digest
        ):
            raise _conflict()
        try:
            quote = Quote.from_dict(quote_row.quote)
            execution = ExecutionPermission.from_dict(quote_row.execution_permission)
        except (TypeError, ValueError, KeyError):
            raise _conflict() from None
        receipt = job.provider_receipt
        if (
            quote.quote_id != str(quote_row.id)
            or quote.source != binding_for(recording)
            or quote.account_id != str(recording.person_id)
            or quote.budget_scope_id != str(quote_row.budget_scope_id)
            or quote.provider_id != source_plan.prepared.provider
            or quote.provider_model != source_plan.prepared.model
            or quote.recipe_revision != source_plan.recipe_revision
            or quote.operation != source_plan.prepared.operation
            or quote.input_sha256 != source_plan.prepared.input_sha256
            or quote.entitlement_seconds != 0
            or quote.max_cost_paise != approval.max_cost_paise
            or quote.privacy_revision != approval.privacy_revision
            or quote.permission_ref != approval.permission_ref
            or quote.provider_terms_ref != approval.provider_terms_ref
            or quote.retention_ref != approval.retention_ref
            or quote.professional_gate_ref != approval.professional_gate_ref
            or quote.pricing_ref != approval.pricing_ref
            or quote.provider_configuration_sha256 != approval.configuration_sha256
            or quote_row.recording_id != recording.id
            or quote_row.tenant_id != recording.tenant_id
            or quote_row.person_id != recording.person_id
            or quote_row.revoked_at is not None
            or execution.quote_fingerprint != quote.fingerprint
            or execution.approved_by != str(recording.person_id)
            or execution.authorization_ref != authorization_ref
            or execution.expires_at_epoch != quote.expires_at_epoch
            or (
                quote.provider_configuration_sha256 is not None
                and quote.provider_configuration_sha256 != approval.configuration_sha256
            )
            or not isinstance(receipt, dict)
            or receipt.get("schema") != "ac.sales-xray.provider-receipt/1"
            or receipt.get("provider") != source_plan.prepared.provider
            or receipt.get("model") != source_plan.prepared.model
            or receipt.get("input_sha256") != source_plan.prepared.input_sha256
            or receipt.get("response_sha256") is None
            or _SHA256.fullmatch(str(receipt.get("response_sha256"))) is None
            or receipt.get("raw_blob_id") != str(task.run_id)
            or receipt.get("idempotency_key") != job.dedupe_key
            or receipt.get("validation") != _C2_VALIDATION
            or receipt.get("validation_state") not in {"provider_returned", "validated"}
            or receipt.get("human_approved") is not False
            or "retained_reuse" in receipt
        ):
            raise _conflict()
        dispatch_epoch = int(utc(job.dispatch_started_at).timestamp())
        if not (
            quote.created_at_epoch
            <= dispatch_epoch
            < min(quote.expires_at_epoch, execution.expires_at_epoch)
        ):
            raise _conflict()
        if task.intent is None or content_hash(task.intent) != task.intent_sha256:
            raise _conflict()
        if content_hash(task.intent) != content_hash(source_plan.intent()):
            raise _conflict()
        if (
            source_plan.duration_ms != target_stage.duration_ms
            or source_plan.prepared.input_sha256 != target_stage.prepared.input_sha256
            or source_plan.prepared.provider != target_stage.prepared.provider
            or source_plan.prepared.model != target_stage.prepared.model
            or source_plan.prepared.operation != target_stage.prepared.operation
            or source_plan.recipe_revision != target_stage.recipe_revision
            or source_plan.checkpoint.revision != target_stage.checkpoint.revision
            or source_plan.checkpoint.config_json != target_stage.checkpoint.config_json
        ):
            raise _conflict()
        source_checkpoint = None
        if task.checkpoint_id is not None:
            source_checkpoint = await self.database.get(ConversationCheckpoint, task.checkpoint_id)
            if source_checkpoint is None or source_checkpoint.recording_id != recording.id:
                raise _conflict()
            try:
                verified_checkpoint(source_checkpoint, binding_for(recording))
            except ConversationConflict:
                raise _conflict() from None
            if (
                receipt.get("checkpoint_id") != str(source_checkpoint.id)
                or receipt.get("checkpoint_manifest_sha256") != source_checkpoint.manifest_sha256
                or not isinstance(source_checkpoint.payload, dict)
                or source_checkpoint.payload.get("revision") != receipt.get("response_sha256")
                or source_checkpoint.payload.get("raw_response_sha256")
                != receipt.get("response_sha256")
            ):
                raise _conflict()
        elif (
            receipt.get("checkpoint_id") is not None
            or receipt.get("checkpoint_manifest_sha256") is not None
        ):
            raise _conflict()
        try:
            usage = _safe_usage(receipt.get("usage", {}))
            request_id = receipt.get("provider_request_id")
            if request_id is not None and (
                not isinstance(request_id, str) or _REQUEST_ID.fullmatch(request_id) is None
            ):
                raise _conflict()
            raw = await asyncio.to_thread(
                lambda: b"".join(
                    self.storage.iter_bytes(
                        ObjectKey(
                            recording.tenant_id,
                            recording.id,
                            task.run_id,
                            ObjectKind.PROVIDER_RESPONSE,
                        ),
                        expected_sha256=receipt["response_sha256"],
                    )
                )
            )
            if not 1 <= len(raw) <= MAX_JSON_BYTES:
                raise _conflict()
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise _conflict()
            result = ProviderResult(
                provider=receipt["provider"],
                model=receipt["model"],
                request_id=request_id,
                response_sha256=receipt["response_sha256"],
                raw_json=raw,
                data=data,
                usage=usage,
                input_sha256=task.input_sha256,
            )
            normalized = validate_scribe_result(
                result,
                source_plan.prepared,
                duration_ms=source_plan.duration_ms,
            ).data()
            if source_checkpoint is not None and source_checkpoint.payload != normalized:
                raise _conflict()
        except (
            StorageError,
            InferenceTaskError,
            ConversationConflict,
            TypeError,
            ValueError,
            KeyError,
        ):
            raise _conflict() from None
        return _VerifiedSource(
            recording, permission, task, run, job, quote_row, quote, receipt, normalized
        )

    async def _materialize(
        self,
        actor: ConversationActor,
        plan_row: ConversationProcessingPlan,
        plan_value: PlanManifest,
        target: ConversationRecording,
        stage: TranscriptionPlan,
        approval: StageApproval,
        source: _VerifiedSource,
        *,
        budget_scope_id: UUID,
        key: str,
        now: datetime,
    ) -> ConversationInferenceTask:
        now_epoch = int(now.timestamp())
        expires_at_epoch = min(
            now_epoch + 900, plan_value.expires_at_epoch, approval.expires_at_epoch
        )
        if expires_at_epoch <= now_epoch:
            raise _conflict()
        quote_id = uuid4()
        quote = replace(
            source.quote,
            quote_id=str(quote_id),
            source=binding_for(target),
            account_id=str(target.person_id),
            budget_scope_id=str(budget_scope_id),
            provider_id=approval.provider_id,
            provider_model=approval.model_id,
            recipe_revision=approval.recipe_revision,
            operation=stage.prepared.operation,
            input_sha256=stage.prepared.input_sha256,
            privacy_revision=approval.privacy_revision,
            permission_ref=approval.permission_ref,
            provider_terms_ref=approval.provider_terms_ref,
            retention_ref=approval.retention_ref,
            professional_gate_ref=approval.professional_gate_ref,
            pricing_ref=approval.pricing_ref,
            entitlement_seconds=0,
            max_cost_paise=0,
            created_at_epoch=now_epoch,
            expires_at_epoch=expires_at_epoch,
            provider_configuration_sha256=approval.configuration_sha256,
        )
        execution = ExecutionPermission(
            authorization_ref=f"retained-c2-reuse-v1:{source.task.run_id}",
            quote_fingerprint=quote.fingerprint,
            approved_by=str(actor.person_id),
            expires_at_epoch=expires_at_epoch,
        )
        self.database.add(
            ConversationQuote(
                id=quote_id,
                tenant_id=target.tenant_id,
                person_id=target.person_id,
                recording_id=target.id,
                budget_scope_id=budget_scope_id,
                quote=quote.as_dict(),
                execution_permission=execution.as_dict(),
            )
        )
        normalized_checkpoint = replace(
            stage.checkpoint,
            payload_sha256=content_hash(source.normalized),
        )
        checkpoint = await ReportingPipeline(self.inference).save(
            target, normalized_checkpoint, source.normalized
        )
        identifier = uuid4()
        job = await JobRepository(self.database).enqueue(
            kind=INFERENCE_JOB,
            dedupe_key=f"conversation:provider:{identifier}",
            payload={"schema": 1, "run_id": str(identifier)},
            tenant_id=target.tenant_id,
            external_side_effect=False,
            max_attempts=1,
        )
        receipt = retained_c2_receipt(
            job=job,
            source=source,
            checkpoint=checkpoint,
            input_sha256=stage.prepared.input_sha256,
        )
        job.status = JobStatus.SUCCEEDED.value
        job.attempt_count = 0
        job.provider_idempotency_key = None
        job.dispatch_started_at = None
        job.provider_receipt = receipt
        job.provider_receipt_digest = canonical_receipt_digest(receipt)
        job.receipt_recorded_at = now
        job.last_error = None
        job.dead_lettered_at = None
        job.held_at = None
        job.hold_reason = None
        job.leased_until = None
        job.lease_token = None
        job.delivery_ambiguous_at = None
        job.updated_at = now
        command_intent = {
            "recording_id": str(target.id),
            "cache_key": stage.checkpoint.cache_key,
            "source_recording_id": str(source.recording.id),
            "source_run_id": str(source.task.run_id),
            "source_response_sha256": source.receipt["response_sha256"],
            "provider_calls": 0,
        }
        self.database.add(
            ConversationRun(
                id=identifier,
                tenant_id=target.tenant_id,
                person_id=target.person_id,
                recording_id=target.id,
                request_key=self.application.command_key(actor, key),
                intent_sha256=content_hash(command_intent),
                recipe_revision=stage.recipe_revision,
                generation=target.generation,
                state="completed",
                job_id=job.id,
                created_at=now,
                completed_at=now,
            )
        )
        self.database.add(
            ConversationInferenceTask(
                run_id=identifier,
                tenant_id=target.tenant_id,
                person_id=target.person_id,
                recording_id=target.id,
                **actor_columns(actor),
                job_id=job.id,
                quote_id=quote_id,
                generation=target.generation,
                stage="C2",
                cache_key=stage.checkpoint.cache_key,
                input_sha256=stage.prepared.input_sha256,
                intent_sha256=content_hash(stage.intent()),
                intent=stage.intent(),
                state="completed",
                checkpoint_id=checkpoint.id,
                created_at=now,
            )
        )
        self.database.add(
            ConversationPlanStageAuthorization(
                quote_id=quote_id,
                plan_id=plan_row.id,
                tenant_id=plan_row.tenant_id,
                person_id=plan_row.person_id,
                quote_fingerprint=quote.fingerprint,
                cache_key=stage.checkpoint.cache_key,
                created_at=now,
            )
        )
        await self.database.flush()
        await self.application._receipt(
            actor,
            key,
            "provider_transcription_retained_reuse",
            command_intent,
            identifier,
            now,
            resource_type="conversation_run",
        )
        task = await self.database.get(ConversationInferenceTask, identifier)
        if task is None:
            raise ConversationConflict("The retained transcription task was not persisted.")
        return task


__all__ = ["RetainedC2ReuseService", "retained_c2_receipt"]
