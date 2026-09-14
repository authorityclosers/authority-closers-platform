"""Durable provider-stage worker with a separate broker and recovery fencing.

No provider credentials are read here. The injected broker owns its process and
must terminate and join it before returning from a cancelled/expired execution.
No HTTP 200 is treated as a settled invoice or as human quality approval.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol, cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationConflict,
    ConversationDenied,
)
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.entitlements import (
    BudgetAccount,
    LedgerTransition,
    MinuteAccount,
    Reservation,
    mark_dispatched,
    mark_uncertain,
    release,
)
from ac_platform.conversation_intelligence.execution_control import (
    ConversationExecutionPaused,
    already_started_effect,
    execution_state,
    lock_execution_control,
    require_execution_enabled,
)
from ac_platform.conversation_intelligence.inference import (
    INFERENCE_JOB,
    ConversationInference,
    ServicePlan,
)
from ac_platform.conversation_intelligence.inference_tasks import (
    InferenceTaskError,
    validate_coaching_result,
    validate_fact_result,
    validate_scribe_result,
)
from ac_platform.conversation_intelligence.models import (
    ConversationBudgetAccount,
    ConversationCheckpoint,
    ConversationInferenceTask,
    ConversationMinuteAccount,
    ConversationQuote,
    ConversationRecording,
    ConversationRun,
)
from ac_platform.conversation_intelligence.processing_actor import actor_from_row
from ac_platform.conversation_intelligence.providers import MAX_AUDIO_BYTES, ProviderResult
from ac_platform.conversation_intelligence.reporting_pipeline import StagePlan
from ac_platform.conversation_intelligence.storage import (
    ObjectKey,
    ObjectKind,
    PrivateLocalRecordingStorage,
    StorageError,
)
from ac_platform.conversation_intelligence.worker import Work, _drain, _FencedExecutor
from ac_platform.outbox.models import Job
from ac_platform.outbox.repository import JobRepository, RecoveryStateRepository

if TYPE_CHECKING:
    from ac_platform.conversation_intelligence.authority import ConversationAuthority

_LEASE = timedelta(minutes=15)
_EFFECT_SECONDS = 240
_VALIDATION_LABELS = {
    "C2": "transcript_schema_and_source_binding",
    "C4": "facts_schema_and_source_binding",
    "C5": "coaching_schema_and_source_binding",
}

# Persist operationally useful categories, never arbitrary exception messages:
# provider errors can contain a response body, transcript or credential URL.
_VALIDATION_FAILURES = frozenset(
    {
        "report_evidence_quote_mismatch",
        "report_evidence_segment_invalid",
        "fact_evidence_outside_chunk",
        "report_json_invalid",
        "report_findings_invalid",
        "report_dimension_status_invalid",
        "report_overview_missing",
        "fact_packet_invalid",
        "provider_result_route_mismatch",
        "provider_result_input_digest_mismatch",
        "provider_raw_json_digest_mismatch",
        "provider_parsed_data_mismatch",
        "gemini_response_blocked",
        "gemini_response_incomplete",
        "gemini_response_json_invalid",
    }
)


def provider_failure_code(error: BaseException) -> str:
    """Map failures to content-free codes without changing recovery policy."""
    if isinstance(error, InferenceTaskError):
        if len(error.args) == 1 and type(error.args[0]) is str:
            code = error.args[0]
            if code in _VALIDATION_FAILURES:
                return f"conversation_{code}"
        return "conversation_provider_result_validation_failed"
    if isinstance(error, TimeoutError):
        return "conversation_provider_execution_timeout"
    if isinstance(error, StorageError):
        return "conversation_provider_storage_failed"
    return "conversation_provider_execution_unresolved"


class InferenceBroker(Protocol):
    async def execute(self, reservation: Reservation, payload: bytes) -> ProviderResult: ...


@dataclass
class Scope:
    task: ConversationInferenceTask
    recording: ConversationRecording
    run: ConversationRun
    quoted: ConversationQuote
    plan: ServicePlan


def save_accounts(
    minutes: ConversationMinuteAccount,
    budget: ConversationBudgetAccount,
    transition: LedgerTransition,
) -> None:
    if transition.changed:
        minutes.snapshot, budget.snapshot = (
            transition.minutes.as_dict(),
            transition.budget.as_dict(),
        )
        minutes.revision += 1
        budget.revision += 1


class ConversationInferenceWorker:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        storage: PrivateLocalRecordingStorage,
        broker: InferenceBroker,
        *,
        authority: ConversationAuthority | None = None,
    ) -> None:
        self.sessions, self.storage, self.broker = sessions, storage, broker
        self.authority = authority

    async def claim(self) -> Work | None:
        async with self.sessions() as db, db.begin():
            if (
                self.authority is not None
                and (
                    await execution_state(
                        db,
                        environment=self.authority.environment,
                        operations_tenant_id=self.authority.operations_tenant_id,
                    )
                )["paused"]
            ):
                return None
            recovery = await RecoveryStateRepository(db).require_ready(lock=True, shared_lock=True)
            jobs = await JobRepository(db).claim(kinds=(INFERENCE_JOB,), limit=1, lease_for=_LEASE)
            if not jobs:
                return None
            job = jobs[0]
            if job.lease_token is None:
                raise ConversationConflict("The provider job has no lease.")
            return Work(job.id, job.lease_token, recovery.generation, job.kind)

    async def _locked_job(self, db: AsyncSession, work: Work) -> Job:
        await RecoveryStateRepository(db).require_ready(
            expected_generation=work.recovery_generation,
            lock=True,
            shared_lock=True,
        )
        job = await db.scalar(
            select(Job)
            .where(Job.id == work.job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            job is None
            or job.kind != INFERENCE_JOB
            or not job.external_side_effect
            or job.lease_token != work.lease_token
            or job.status != "leased"
            or job.recovery_generation != work.recovery_generation
        ):
            raise ConversationConflict("The provider job was fenced.")
        await JobRepository(db).renew(job, work.lease_token, lease_for=_LEASE)
        return job

    async def _scope(self, db: AsyncSession, job: Job) -> Scope:
        if (
            set(job.payload) != {"schema", "run_id"}
            or type(job.payload["schema"]) is not int
            or job.payload["schema"] != 1
        ):
            raise ConversationDenied("The provider job intent is invalid.")
        identifier = UUID(job.payload["run_id"])
        task = await db.scalar(
            select(ConversationInferenceTask)
            .where(
                ConversationInferenceTask.run_id == identifier,
                ConversationInferenceTask.job_id == job.id,
                ConversationInferenceTask.tenant_id == job.tenant_id,
            )
            .execution_options(populate_existing=True)
        )
        if task is None or task.erased_at is not None or task.state not in {"queued", "running"}:
            raise ConversationDenied("The provider task is no longer active.")
        application = ConversationApplication(db)
        actor = actor_from_row(task)
        now = await application.admit(actor)
        await application.get(actor, task.recording_id)
        recording = await application._recording(actor, task.recording_id)
        # Match command lock order: owner/session -> recording -> task.
        # Locking the task before its owner could deadlock a duplicate upload click.
        task = await db.scalar(
            select(ConversationInferenceTask)
            .where(ConversationInferenceTask.run_id == identifier)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if task is None or task.erased_at is not None or task.state not in {"queued", "running"}:
            raise ConversationDenied("The provider task is no longer active.")
        run = await db.scalar(
            select(ConversationRun)
            .where(
                ConversationRun.id == task.run_id,
                ConversationRun.job_id == job.id,
                ConversationRun.tenant_id == task.tenant_id,
                ConversationRun.person_id == task.person_id,
                ConversationRun.recording_id == recording.id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            recording.state != "ready"
            or recording.generation != task.generation
            or task.stage not in {"C2", "C4", "C5"}
            or run is None
            or run.state not in {"queued", "running"}
            or run.generation != task.generation
        ):
            raise ConversationConflict("The recording or provider run changed.")
        service = ConversationInference(application, authority=self.authority)
        plan = await service.plan_task(recording, task)
        if (
            task.intent is None
            or content_hash(task.intent) != task.intent_sha256
            or task.intent_sha256 != content_hash(plan.intent())
            or task.cache_key != plan.checkpoint.cache_key
            or task.input_sha256 != plan.prepared.input_sha256
            or run.recipe_revision != plan.recipe_revision
            or task.stage != plan.checkpoint.stage
        ):
            raise ConversationConflict("The immutable provider input changed.")
        quoted, _, _ = await service._quote(
            actor,
            recording,
            task.quote_id,
            plan,
            now,
            require_acceptance=True,
        )
        return Scope(task, recording, run, quoted, plan)

    def _payload(self, scope: Scope) -> bytes:
        """Load C2 media or use the already prepared immutable text request.

        C4 and C5 must never reread source audio or retranscribe it.  Their
        prepared request bytes are reconstructed from the source-bound plan and
        persisted task intent instead.
        """

        if scope.task.stage == "C2":
            return self._audio(scope.recording)
        if scope.task.stage in {"C4", "C5"}:
            payload = scope.plan.prepared.payload
            if type(payload) is not bytes or not payload:
                raise StorageError("provider_text_payload_invalid")
            return payload
        raise ConversationConflict("The provider task stage is invalid.")

    @staticmethod
    def _validate(
        scope: Scope,
        result: ProviderResult,
    ) -> Any:
        """Validate a provider response against this exact stage plan."""

        if scope.task.stage == "C2":
            return validate_scribe_result(
                result,
                scope.plan.prepared,
                duration_ms=scope.plan.duration_ms,
            )
        stage_plan = cast(StagePlan, scope.plan)
        if scope.task.stage == "C4":
            return validate_fact_result(
                result,
                stage_plan.prepared,
                stage_plan.transcript,
            )
        if scope.task.stage == "C5":
            return validate_coaching_result(
                result,
                stage_plan.prepared,
                stage_plan.transcript,
                profile=stage_plan.profile,
            )
        raise ConversationConflict("The provider task stage is invalid.")

    def _audio(self, recording: ConversationRecording) -> bytes:
        if recording.source_bytes > MAX_AUDIO_BYTES:
            raise StorageError("provider_audio_too_large")
        audio = b"".join(
            self.storage.iter_bytes(
                ObjectKey(recording.tenant_id, recording.id, recording.id, ObjectKind.SOURCE_AUDIO),
                expected_sha256=recording.source_sha256,
            )
        )
        if len(audio) != recording.source_bytes:
            raise StorageError("provider_audio_size_mismatch")
        return audio

    def _save_raw(self, scope: Scope, result: ProviderResult) -> None:
        self.storage.put(
            ObjectKey(
                scope.task.tenant_id,
                scope.recording.id,
                scope.task.run_id,
                ObjectKind.PROVIDER_RESPONSE,
            ),
            (result.raw_json,),
            expected_sha256=result.response_sha256,
            expected_bytes=len(result.raw_json),
        )

    async def _dispatch(self, work: Work) -> None:
        # Both media erasure and inference hold this fence BEFORE locking DB rows.
        async with _FencedExecutor(self.storage.root) as fenced:
            async with self.sessions() as db, db.begin():
                job = await self._locked_job(db, work)
                if job.provider_receipt is not None:
                    # Receipt + checkpoint + completed run were committed together.
                    await JobRepository(db).complete(job, work.lease_token)
                    return
                if job.dispatch_started_at is not None:
                    raise ConversationConflict("A previous provider dispatch needs reconciliation.")
                scope = await self._scope(db, job)
                payload = await fenced.run(self._payload, scope)
                service = ConversationInference(ConversationApplication(db))
                minutes, budget = await service.accounts(scope.recording, scope.quoted)
                before = MinuteAccount.from_dict(minutes.snapshot)
                reservation = next(
                    (r for r in before.reservations if r.reservation_id == str(scope.task.run_id)),
                    None,
                )
                if reservation is None or reservation.state != "reserved":
                    raise ConversationConflict("The provider budget is already dispatched or held.")
                key = job.dedupe_key
                if self.authority is not None:
                    # This short fence serializes the last pause check with the
                    # durable dispatch marker. A marker committed before pause
                    # is already-started work and may finish after pause returns.
                    await lock_execution_control(
                        db,
                        environment=self.authority.environment,
                        operations_tenant_id=self.authority.operations_tenant_id,
                        shared=True,
                    )
                    await require_execution_enabled(
                        db,
                        environment=self.authority.environment,
                        operations_tenant_id=self.authority.operations_tenant_id,
                    )
                transition = mark_dispatched(
                    before,
                    BudgetAccount.from_dict(budget.snapshot),
                    str(scope.task.run_id),
                    key,
                    int(datetime.now(UTC).timestamp()),
                )
                save_accounts(minutes, budget, transition)
                await JobRepository(db).record_dispatch_started(
                    job,
                    work.lease_token,
                    provider_idempotency_key=key,
                    recovery_generation=work.recovery_generation,
                )
                scope.task.state = scope.run.state = "running"
                reservation = transition.reservation

            async with self.sessions() as db, db.begin():
                job = await JobRepository(db).lock_for_dispatch(
                    work.job_id,
                    work.lease_token,
                    recovery_generation=work.recovery_generation,
                    provider_idempotency_key=key,
                )
                if self.authority is None:
                    scope = await self._scope(db, job)
                else:
                    # lock_for_dispatch above proves our committed marker and
                    # current lease. Only the pause check is waived for that
                    # already-started effect; all other authority is rechecked.
                    with already_started_effect(
                        environment=self.authority.environment,
                        operations_tenant_id=self.authority.operations_tenant_id,
                    ):
                        scope = await self._scope(db, job)
                # Restore, revocation and deletion wait on these canonical locks
                # across the one bounded child-process effect.
                async with asyncio.timeout(_EFFECT_SECONDS):
                    result = await self.broker.execute(reservation, payload)
                await fenced.run(self._save_raw, scope, result)
                output = self._validate(scope, result)
                normalized = output.data()
                checkpoint = replace(scope.plan.checkpoint, payload_sha256=content_hash(normalized))
                row = ConversationCheckpoint(
                    id=uuid4(),
                    tenant_id=scope.task.tenant_id,
                    person_id=scope.task.person_id,
                    recording_id=scope.recording.id,
                    cache_key=checkpoint.cache_key,
                    manifest_sha256=checkpoint.manifest_sha256,
                    payload_sha256=checkpoint.payload_sha256,
                    stage=scope.task.stage,
                    feature_blob_id=None,
                    manifest=checkpoint.as_dict(),
                    payload=normalized,
                    created_at=datetime.now(UTC),
                )
                db.add(row)
                await db.flush()
                scope.task.checkpoint_id = row.id
                scope.task.state = scope.run.state = "completed"
                scope.run.completed_at = datetime.now(UTC)
                service = ConversationInference(ConversationApplication(db))
                await service.finish_stage(
                    scope.recording,
                    scope.task,
                    scope.run,
                    scope.plan,
                    row,
                    normalized,
                    result,
                )
                receipt: dict[str, Any] = {
                    "schema": "ac.sales-xray.provider-receipt/1",
                    "idempotency_key": key,
                    "provider": result.provider,
                    "model": result.model,
                    "input_sha256": result.input_sha256,
                    "response_sha256": result.response_sha256,
                    "provider_request_id": output.request_id,
                    "checkpoint_id": str(row.id),
                    "checkpoint_manifest_sha256": checkpoint.manifest_sha256,
                    "raw_blob_id": str(scope.task.run_id),
                    "usage": dict(output.usage),
                    "cost_state": "reconciliation_required",
                    "actual_cost_paise": None,
                    "validation": _VALIDATION_LABELS[scope.task.stage],
                    "human_approved": False,
                }
                await JobRepository(db).record_receipt(job, work.lease_token, receipt)
                minutes, budget = await service.accounts(scope.recording, scope.quoted)
                transition = mark_uncertain(
                    MinuteAccount.from_dict(minutes.snapshot),
                    BudgetAccount.from_dict(budget.snapshot),
                    str(scope.task.run_id),
                    f"provider-cost-reconciliation:{scope.task.run_id}",
                )
                save_accounts(minutes, budget, transition)

            # A crash here only loses acknowledgement, never the saved provider result.
            async with self.sessions() as db, db.begin():
                await JobRepository(db).complete(work.job_id, work.lease_token)

    async def _fail(
        self, work: Work, *, failure_code: str = "conversation_provider_execution_unresolved"
    ) -> None:
        async with self.sessions() as db, db.begin():
            job = await self._locked_job(db, work)
            if job.provider_receipt is not None:
                await JobRepository(db).complete(job, work.lease_token)
                return
            ambiguous = job.dispatch_started_at is not None
            task = await db.scalar(
                select(ConversationInferenceTask)
                .where(
                    ConversationInferenceTask.job_id == job.id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if task is not None:
                run = await db.get(ConversationRun, task.run_id)
                recording = await db.get(ConversationRecording, task.recording_id)
                quoted = await db.get(ConversationQuote, task.quote_id)
                if task.state != "cancelled":
                    task.state = "uncertain" if ambiguous else "failed"
                if run is not None and run.state not in {"cancelled", "completed"}:
                    run.state = "failed"
                if recording is not None and quoted is not None:
                    minutes, budget = await ConversationInference(
                        ConversationApplication(db)
                    ).accounts(recording, quoted)
                    snapshot = MinuteAccount.from_dict(minutes.snapshot)
                    existing = next(
                        (r for r in snapshot.reservations if r.reservation_id == str(task.run_id)),
                        None,
                    )
                    if existing is not None and existing.state in {"reserved", "in_flight"}:
                        if ambiguous and existing.state == "in_flight":
                            transition = mark_uncertain(
                                snapshot,
                                BudgetAccount.from_dict(budget.snapshot),
                                str(task.run_id),
                                f"provider-outcome-reconciliation:{task.run_id}",
                            )
                            save_accounts(minutes, budget, transition)
                        elif not ambiguous and existing.state == "reserved":
                            transition = release(
                                snapshot,
                                BudgetAccount.from_dict(budget.snapshot),
                                str(task.run_id),
                                f"provider-not-dispatched:{task.run_id}",
                            )
                            save_accounts(minutes, budget, transition)
            await JobRepository(db).fail(
                job,
                work.lease_token,
                failure_code,
                permanent=True,
                ambiguous=ambiguous,
            )

    async def run_once(self) -> bool:
        work = await self.claim()
        if work is None:
            return False
        try:
            await self._dispatch(work)
        except ConversationExecutionPaused:
            # A pause racing claim rolls back before a dispatch marker. Keep
            # every source/checkpoint/reservation intact; normal lease recovery
            # can reclaim this job after resume. Do not call failure/refund code.
            return True
        except BaseException as error:
            # A failed cleanup may itself be fenced by restore/lease loss. The
            # dispatch marker still quarantines the job on the next claim.
            cleanup = asyncio.create_task(
                self._fail(work, failure_code=provider_failure_code(error))
            )
            await _drain(cleanup)
            if isinstance(error, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
                raise
        return True
