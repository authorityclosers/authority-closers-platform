"""Private submission reads use customer ownership, never an execution lease.

The root-owned GuestOwnership port resolves the visitor or claimed account.
Every query below additionally selects the immutable recording/person/source
binding. Reading retained evidence cannot renew processing or dispatch a provider.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from sqlalchemy import select

from ac_platform.conversation_intelligence.alignment import (
    AlignmentError,
    project_transcript_for_playback,
)
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationConflict,
    ConversationNotFound,
)
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership, SubmissionScope
from ac_platform.conversation_intelligence.inference import (
    ConversationInference,
    binding_for,
    verified_checkpoint,
)
from ac_platform.conversation_intelligence.inference_broker import InferenceBrokerError
from ac_platform.conversation_intelligence.measurement_view import ConversationMeasurements
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationInferenceTask,
    ConversationProcessingPlan,
    ConversationRecording,
    ConversationReportDraft,
    ConversationRun,
)
from ac_platform.conversation_intelligence.processing_actor import ProcessingActor
from ac_platform.conversation_intelligence.report_access import (
    ReportAccess,
    ReportSourceBinding,
    project_bound_report,
)
from ac_platform.conversation_intelligence.report_store import ConversationReports
from ac_platform.conversation_intelligence.reports import ReportDraft
from ac_platform.conversation_intelligence.retained_c5_recovery import RetainedC5RecoveryService
from ac_platform.kernel.authz import ActorContext
from ac_platform.outbox.models import Job

# ``Job.last_error`` is deliberately a bounded storage field, not a public
# diagnostic channel.  Progress may expose only the stable, content-free codes
# emitted by the inference worker.  Keep the local validation vocabulary here
# so an arbitrary provider/DB message can never cross the HTTP boundary.
_VALIDATION_FAILURE_CODES = frozenset(
    {
        "report_evidence_quote_mismatch",
        "report_evidence_segment_invalid",
        "fact_evidence_outside_chunk",
        "report_json_invalid",
        "report_findings_invalid",
        "report_dimension_status_invalid",
        "report_overview_missing",
        "report_overview_invalid",
        "report_payload_invalid",
        "report_payload_missing_field",
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
_BASE_FAILURE_CODES = frozenset(
    {
        "conversation_provider_execution_unresolved",
        "conversation_provider_execution_timeout",
        "conversation_provider_storage_failed",
    }
)
_PLAN_FAILURE_CODES = frozenset(
    {
        "stage_failed",
        "stage_uncertain",
        "stage_cancelled",
        "processing_authorization_or_input_unavailable",
    }
)
_FAILURE_CODE_PATTERN = re.compile(r"^conversation_[a-z][a-z0-9_]{0,127}$")


def _safe_progress_failure_code(value: object) -> str | None:
    """Return an allowlisted inference failure code suitable for public progress."""

    if not isinstance(value, str):
        return None
    if value in _PLAN_FAILURE_CODES:
        return value
    if _FAILURE_CODE_PATTERN.fullmatch(value) is None:
        return None
    if value in _BASE_FAILURE_CODES or value.removeprefix("conversation_") in (
        _VALIDATION_FAILURE_CODES
    ):
        return value
    # Broker codes are validated by the same constructor that accepts provider
    # HTTP status codes.  Its fallback is detectable by comparing ``code``.
    candidate = value.removeprefix("conversation_")
    broker_error = InferenceBrokerError(candidate)
    return value if broker_error.code == candidate else None


def _progress_failure_code(
    plan: ConversationProcessingPlan | None,
    task_rows: list[tuple[ConversationInferenceTask, str | None]],
    *,
    generation: int,
    has_report: bool,
) -> str | None:
    """Project one current-generation failure without reviving superseded work."""

    if has_report or (plan is not None and plan.state == "active"):
        return None
    failure_code = _safe_progress_failure_code(
        plan.progress.get("failure_code")
        if plan is not None and plan.generation == generation and isinstance(plan.progress, dict)
        else None
    )
    task_failure_code = next(
        (
            code
            for task, last_error in reversed(task_rows)
            if task.generation == generation
            and task.state in {"failed", "uncertain"}
            and (code := _safe_progress_failure_code(last_error)) is not None
        ),
        None,
    )
    return task_failure_code if task_failure_code is not None else failure_code


class AcquisitionReports:
    def __init__(self, ownership: GuestOwnership) -> None:
        self.ownership, self.database = ownership, ownership.database
        self.application = ConversationApplication(self.database, clock=ownership.clock)
        self.reports = ConversationReports(self.application)

    async def recording(
        self, submission_id: UUID, *, token: str | None = None, actor: ActorContext | None = None
    ) -> tuple[SubmissionScope, ConversationRecording]:
        # Root-owned per-visitor read fencing spans this caller transaction.
        # Streaming one call must not take the global acquisition lock or
        # block an unrelated visitor from starting their upload.
        scope = await self.ownership.require_submission_owner(
            submission_id, token=token, actor=actor
        )
        recording = await self.database.scalar(
            select(ConversationRecording)
            .where(
                ConversationRecording.id == scope.recording_id,
                ConversationRecording.tenant_id == scope.tenant_id,
                ConversationRecording.person_id == scope.processing_person_id,
                ConversationRecording.source_sha256 == scope.source_sha256,
                ConversationRecording.state.in_(("awaiting_upload", "ready")),
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if recording is None:
            raise ConversationNotFound("This upload is unavailable.")
        # The recording lock also serializes erasure/permission revocation.
        await self.ownership.require_submission_owner(submission_id, token=token, actor=actor)
        return scope, recording

    async def _draft(self, recording: ConversationRecording) -> ConversationReportDraft | None:
        result: ConversationReportDraft | None = await self.database.scalar(
            select(ConversationReportDraft)
            .where(
                ConversationReportDraft.recording_id == recording.id,
                ConversationReportDraft.tenant_id == recording.tenant_id,
                ConversationReportDraft.person_id == recording.person_id,
                ConversationReportDraft.erased_at.is_(None),
            )
            .order_by(ConversationReportDraft.created_at.desc(), ConversationReportDraft.id.desc())
            .limit(1)
        )
        return result

    async def report(
        self, submission_id: UUID, *, token: str | None = None, actor: ActorContext | None = None
    ) -> dict[str, Any]:
        scope, recording = await self.recording(submission_id, token=token, actor=actor)
        recovered = await RetainedC5RecoveryService(self.application).latest_for_recording(
            recording
        )
        if recovered is not None and recovered.payload is not None:
            report = ReportDraft.model_validate(recovered.payload)
            run = await self.database.scalar(
                select(ConversationRun).where(
                    ConversationRun.id == recovered.run_id,
                    ConversationRun.recording_id == recording.id,
                    ConversationRun.tenant_id == recording.tenant_id,
                    ConversationRun.person_id == recording.person_id,
                )
            )
            if run is None:
                raise ConversationConflict("The recovered report's run is unavailable.")
            envelope = project_bound_report(
                report,
                access=ReportAccess.ACCOUNT if scope.claimed_account else ReportAccess.GUEST,
                source=ReportSourceBinding(
                    recording.id, run.id, recording.source_sha256, report.transcript_revision
                ),
            )
            return {
                "submission_id": str(submission_id),
                **envelope,
                "recovery": {
                    "version": recovered.version,
                    "validation_state": recovered.validation_state,
                    "provider_calls": 0,
                    "human_approved": False,
                    "official_score": False,
                },
            }
        draft = await self._draft(recording)
        if draft is None:
            raise ConversationNotFound("Your sales report is not ready yet.")
        run = await self.database.scalar(
            select(ConversationRun).where(
                ConversationRun.id == draft.run_id,
                ConversationRun.recording_id == recording.id,
                ConversationRun.tenant_id == recording.tenant_id,
                ConversationRun.person_id == recording.person_id,
                ConversationRun.generation == recording.generation,
                ConversationRun.state == "completed",
            )
        )
        if run is None:
            raise ConversationConflict("The stored report needs review.")
        report, _ = self.reports._validated(draft, recording)
        await self.reports._canonical_draft(draft, recording)
        envelope = project_bound_report(
            report,
            access=ReportAccess.ACCOUNT if scope.claimed_account else ReportAccess.GUEST,
            source=ReportSourceBinding(
                recording.id, run.id, recording.source_sha256, report.transcript_revision
            ),
        )
        return {"submission_id": str(submission_id), **envelope}

    async def transcript(
        self, submission_id: UUID, *, token: str | None = None, actor: ActorContext | None = None
    ) -> dict[str, Any]:
        _, recording = await self.recording(submission_id, token=token, actor=actor)
        recovered = await RetainedC5RecoveryService(self.application).latest_for_recording(
            recording
        )
        if recovered is not None:
            checkpoint = await self.database.scalar(
                select(ConversationCheckpoint).where(
                    ConversationCheckpoint.id == recovered.c2_checkpoint_id,
                    ConversationCheckpoint.recording_id == recording.id,
                    ConversationCheckpoint.tenant_id == recording.tenant_id,
                    ConversationCheckpoint.person_id == recording.person_id,
                    ConversationCheckpoint.stage == "C2",
                    ConversationCheckpoint.manifest_sha256 == recovered.c2_manifest_sha256,
                    ConversationCheckpoint.erased_at.is_(None),
                )
            )
            if checkpoint is None or checkpoint.payload is None:
                raise ConversationConflict("The recovered transcript is unavailable.")
            try:
                verified_checkpoint(checkpoint, binding_for(recording))
            except (KeyError, TypeError, ValueError):
                raise ConversationConflict(
                    "The recovered transcript binding is unavailable."
                ) from None
            transcript = checkpoint.payload
            if not isinstance(transcript, dict):
                raise ConversationConflict("The recovered transcript is unavailable.")
            source = await ConversationInference(self.application).plan_transcription(recording)
            if (
                transcript.get("source_sha256") != recording.source_sha256
                or transcript.get("duration_ms") != source.duration_ms
            ):
                raise ConversationConflict("The recovered transcript's source measurement differs.")
            try:
                transcript = project_transcript_for_playback(
                    transcript, duration_ms=source.duration_ms
                )
            except AlignmentError:
                raise ConversationConflict(
                    "The recovered transcript's playback bounds are unavailable."
                ) from None
            return {
                name: transcript[name]
                for name in ("source_sha256", "revision", "timebase_id", "duration_ms", "segments")
            }
        draft = await self._draft(recording)
        if draft is None:
            raise ConversationNotFound("The transcript will appear with your sales report.")
        _, transcript = self.reports._validated(draft, recording)
        await self.reports._canonical_draft(draft, recording)
        return {
            name: transcript[name]
            for name in ("source_sha256", "revision", "timebase_id", "duration_ms", "segments")
        }

    async def waveform(
        self, submission_id: UUID, *, token: str | None = None, actor: ActorContext | None = None
    ) -> dict[str, Any]:
        _, recording = await self.recording(submission_id, token=token, actor=actor)
        return await ConversationMeasurements(self.application).waveform_from_recording(recording)

    async def progress(
        self, submission_id: UUID, *, token: str | None = None, actor: ActorContext | None = None
    ) -> dict[str, Any]:
        scope, recording = await self.recording(submission_id, token=token, actor=actor)
        local_run = await self.database.scalar(
            select(ConversationRun).where(
                ConversationRun.recording_id == recording.id,
                ConversationRun.tenant_id == scope.tenant_id,
                ConversationRun.person_id == scope.processing_person_id,
                ConversationRun.generation == recording.generation,
                ConversationRun.request_key
                == self.application.command_key(
                    ProcessingActor(
                        scope.processing_person_id, scope.tenant_id, scope.processing_lease_id
                    ),
                    f"acquisition-local-run:{recording.id}",
                ),
            )
        )
        plan = await self.database.scalar(
            select(ConversationProcessingPlan)
            .where(
                ConversationProcessingPlan.recording_id == recording.id,
                ConversationProcessingPlan.tenant_id == recording.tenant_id,
                ConversationProcessingPlan.person_id == recording.person_id,
                ConversationProcessingPlan.processing_lease_id == scope.processing_lease_id,
                ConversationProcessingPlan.generation == recording.generation,
                ConversationProcessingPlan.erased_at.is_(None),
            )
            .order_by(
                ConversationProcessingPlan.created_at.desc(),
                ConversationProcessingPlan.id.desc(),
            )
            .limit(1)
        )
        task_rows = [
            (row[0], row[1])
            for row in (
                await self.database.execute(
                    select(ConversationInferenceTask, Job.last_error)
                    .join(Job, Job.id == ConversationInferenceTask.job_id)
                    .where(
                        ConversationInferenceTask.recording_id == recording.id,
                        ConversationInferenceTask.tenant_id == recording.tenant_id,
                        ConversationInferenceTask.person_id == recording.person_id,
                        ConversationInferenceTask.processing_lease_id == scope.processing_lease_id,
                        ConversationInferenceTask.generation == recording.generation,
                        ConversationInferenceTask.erased_at.is_(None),
                    )
                    .order_by(
                        ConversationInferenceTask.created_at.desc(),
                        ConversationInferenceTask.run_id.desc(),
                    )
                    .limit(128)
                )
            ).all()
        ]
        task_rows = list(reversed(task_rows))
        tasks = [row[0] for row in task_rows]
        has_report = False
        recovered = await RetainedC5RecoveryService(self.application).latest_for_recording(
            recording
        )
        if recovered is not None:
            has_report = True
        draft = await self._draft(recording)
        if draft is not None:
            try:
                self.reports._validated(draft, recording)
                await self.reports._canonical_draft(draft, recording)
                has_report = True
            except ConversationConflict:
                if recovered is None:
                    has_report = False
        failure_code = _progress_failure_code(
            plan,
            task_rows,
            generation=recording.generation,
            has_report=has_report,
        )
        return {
            "submission_id": str(submission_id),
            "recording_id": str(recording.id),
            "source_sha256": recording.source_sha256,
            "local_state": local_run.state if local_run else None,
            "state": "report_ready" if has_report else plan.state if plan else recording.state,
            "has_report": has_report,
            "automatic_progression": plan is not None and plan.state == "active",
            "failure_code": failure_code,
            "stages": [{"stage": task.stage, "state": task.state} for task in tasks],
        }
