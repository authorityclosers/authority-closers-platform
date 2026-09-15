"""Private submission reads use customer ownership, never an execution lease.

The root-owned GuestOwnership port resolves the visitor or claimed account.
Every query below additionally selects the immutable recording/person/source
binding. Reading retained evidence cannot renew processing or dispatch a provider.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select

from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationConflict,
    ConversationNotFound,
)
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership, SubmissionScope
from ac_platform.conversation_intelligence.models import (
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
        draft = await self._draft(recording)
        if draft is None:
            raise ConversationNotFound("The transcript will appear with your sales report.")
        _, transcript = self.reports._validated(draft, recording)
        await self.reports._canonical_draft(draft, recording)
        return {
            name: transcript[name]
            for name in ("source_sha256", "revision", "timebase_id", "duration_ms", "segments")
        }

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
                ConversationProcessingPlan.erased_at.is_(None),
            )
            .order_by(ConversationProcessingPlan.created_at.desc())
            .limit(1)
        )
        tasks = (
            await self.database.scalars(
                select(ConversationInferenceTask)
                .where(
                    ConversationInferenceTask.recording_id == recording.id,
                    ConversationInferenceTask.tenant_id == recording.tenant_id,
                    ConversationInferenceTask.person_id == recording.person_id,
                    ConversationInferenceTask.processing_lease_id == scope.processing_lease_id,
                    ConversationInferenceTask.erased_at.is_(None),
                )
                .order_by(ConversationInferenceTask.created_at)
                .limit(128)
            )
        ).all()
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
        return {
            "submission_id": str(submission_id),
            "recording_id": str(recording.id),
            "source_sha256": recording.source_sha256,
            "local_state": local_run.state if local_run else None,
            "state": "report_ready" if has_report else plan.state if plan else recording.state,
            "has_report": has_report,
            "automatic_progression": plan is not None and plan.state == "active",
            "stages": [{"stage": task.stage, "state": task.state} for task in tasks],
        }
