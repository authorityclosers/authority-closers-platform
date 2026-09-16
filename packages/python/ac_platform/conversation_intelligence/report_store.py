"""Audited internal draft import and owner-only report reads.

This connects private, already-produced analysis to AC records. Importing evidence
does not execute a provider, attest model quality, or promote a scoring version.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from ac_platform.conversation_intelligence.alignment import project_transcript_for_playback
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationConflict,
    ConversationError,
    ConversationNotFound,
    utc,
)
from ac_platform.conversation_intelligence.async_io import join_thread
from ac_platform.conversation_intelligence.checkpoints import canonical, content_hash
from ac_platform.conversation_intelligence.inference_tasks import prepare_scribe_input
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationPermission,
    ConversationRecording,
    ConversationReportDraft,
    ConversationRun,
)
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.conversation_intelligence.providers import ProviderResult, scribe_transcript
from ac_platform.conversation_intelligence.reports import (
    ReportDraft,
    extract_style_independent_facts,
    load_report_profile,
    parse_report_draft,
)
from ac_platform.conversation_intelligence.retained_c5_recovery import RetainedC5RecoveryService
from ac_platform.conversation_intelligence.storage import (
    ObjectKey,
    ObjectKind,
    RecordingObjectStorage,
    StorageError,
)
from ac_platform.kernel.authz import ActorContext


class PrivateProofReference(BaseModel):
    """Operator-supplied references, not canonical provider/reviewer attestations.

    Only transcription_response_sha256 is checked against supplied bytes here.
    The other hashes identify private external receipts; this importer cannot
    establish their existence, consent, provider execution or human adjudication.
    Hosted activation must use the durable broker's own canonical receipts.
    """

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    schema_id: Literal["ac.sales-xray.private-proof-reference/1"]
    approval_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    transcription_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    generation_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_review_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    new_provider_calls: Literal[0]


class PrivateDraftIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    raw_transcription_json: str = Field(min_length=1, max_length=3_000_000, repr=False)
    report: dict[str, Any] = Field(repr=False)
    receipt: PrivateProofReference

    @field_validator("report")
    @classmethod
    def bounded_report(cls, value: dict[str, Any]) -> dict[str, Any]:
        pending: list[tuple[Any, int]] = [(value, 0)]
        count = 0
        while pending:
            child, depth = pending.pop()
            count += 1
            if depth > 12 or count > 20_000:
                raise ValueError("The report exceeds its structural limit.")
            if isinstance(child, dict):
                pending.extend((item, depth + 1) for item in child.values())
            elif isinstance(child, list):
                pending.extend((item, depth + 1) for item in child)
        try:
            encoded = canonical(value)
        except (TypeError, ValueError):
            raise ValueError("The report must contain valid JSON values.") from None
        if len(encoded) > 512 * 1024:
            raise ValueError("The report exceeds its byte limit.")
        return value


class DurableDraftProof(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_id: Literal["ac.sales-xray.durable-draft-proof/1"]
    transcript_checkpoint_id: UUID
    transcription_task_id: UUID
    transcription_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    coaching_checkpoint_id: UUID
    presentation_checkpoint_id: UUID
    coaching_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    accepted_quote_id: UUID
    profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    human_approved: Literal[False]
    numeric_publication: Literal[False]


class ConversationReports:
    def __init__(self, application: ConversationApplication) -> None:
        self.application = application
        self.database = application.database

    @staticmethod
    def _validated(
        draft: ConversationReportDraft, recording: ConversationRecording
    ) -> tuple[ReportDraft, dict[str, Any]]:
        if (
            draft.recording_id != recording.id
            or draft.tenant_id != recording.tenant_id
            or draft.person_id != recording.person_id
            or draft.source_revision != recording.source_revision
            or draft.source_sha256 != recording.source_sha256
            or draft.erased_at is not None
            or draft.payload is None
            or draft.transcript is None
            or draft.evidence_receipt is None
            or content_hash(draft.payload) != draft.report_sha256
            or content_hash(draft.transcript) != draft.transcript_sha256
            or content_hash(draft.evidence_receipt) != draft.evidence_receipt_sha256
        ):
            raise ConversationConflict("The stored report evidence is unavailable.")
        try:
            transcript = draft.transcript["normalized"]
            if draft.evidence_receipt.get("schema_id") == "ac.sales-xray.durable-draft-proof/1":
                durable = DurableDraftProof.model_validate(draft.evidence_receipt)
                native_ref = draft.transcript["native_response_ref"]
                profile = draft.transcript["profile"]
                native_sha256 = durable.transcription_response_sha256
                if (
                    not isinstance(profile, dict)
                    or native_ref
                    != {
                        "task_id": str(durable.transcription_task_id),
                        "response_sha256": native_sha256,
                    }
                    or durable.profile_sha256 != draft.profile_sha256
                ):
                    raise ValueError("unbound durable draft")
            else:
                profile = load_report_profile()
                receipt = PrivateProofReference.model_validate(draft.evidence_receipt)
                native = draft.transcript["native_json"]
                native_sha256 = receipt.transcription_response_sha256
                if (
                    not isinstance(native, str)
                    or hashlib.sha256(native.encode()).hexdigest() != native_sha256
                ):
                    raise ValueError("unbound native response")
            if (
                not isinstance(transcript, dict)
                or transcript.get("revision") != native_sha256
                or transcript.get("source_sha256") != recording.source_sha256
                or draft.profile_sha256 != content_hash(profile)
            ):
                raise ValueError("unbound draft")
            report = ReportDraft.model_validate(draft.payload)
            checked = parse_report_draft(
                draft.payload, transcript, source_label=report.source_label, profile=profile
            )
            if content_hash(checked.model_dump(mode="json")) != draft.report_sha256:
                raise ValueError("unbound report")
        except (ValueError, TypeError, KeyError):
            raise ConversationConflict("The stored report needs review.") from None
        return report, transcript

    async def _canonical_draft(
        self, draft: ConversationReportDraft, recording: ConversationRecording
    ) -> None:
        """A durable proof must resolve to actual immutable task/checkpoint receipts."""
        if (
            draft.evidence_receipt is None
            or draft.evidence_receipt.get("schema_id") != "ac.sales-xray.durable-draft-proof/1"
        ):
            return
        from ac_platform.conversation_intelligence.inference import ConversationInference
        from ac_platform.conversation_intelligence.reporting_pipeline import ReportingPipeline

        proof = DurableDraftProof.model_validate(draft.evidence_receipt)
        pipeline = ReportingPipeline(ConversationInference(self.application))
        c2_row, _ = await pipeline.checkpoint(recording, proof.transcript_checkpoint_id, "C2")
        c5_row, c5 = await pipeline.checkpoint(recording, proof.coaching_checkpoint_id, "C5")
        c6_row, c6 = await pipeline.checkpoint(recording, proof.presentation_checkpoint_id, "C6")
        transcription, c2_receipt = await pipeline.provider_task(recording, c2_row)
        source = await pipeline.service.plan_transcription(recording)
        coaching, c5_receipt = await pipeline.provider_task(recording, c5_row)
        aggregate_row, aggregate = await pipeline.parent(recording, c5, "C4")
        _, alignment = await pipeline.parent(recording, aggregate, "C3")
        selected_c2, _ = await pipeline.parent(recording, aggregate, "C2")
        aligned_c2, _ = await pipeline.parent(recording, alignment, "C2")
        config = json.loads(c5.config_json)
        request = (coaching.intent or {}).get("request", {})
        if draft.transcript is None or c2_row.payload is None:
            raise ConversationConflict("The stored report's transcript evidence is unavailable.")
        native_transcript = draft.transcript.get("native", draft.transcript["normalized"])
        projected_transcript = project_transcript_for_playback(
            c2_row.payload, duration_ms=source.duration_ms
        )
        if (
            draft.transcript is None
            or c2_row.payload != native_transcript
            or projected_transcript != draft.transcript["normalized"]
            or c5_row.payload != draft.payload
            or transcription.run_id != proof.transcription_task_id
            or coaching.run_id != draft.run_id
            or coaching.quote_id != proof.accepted_quote_id
            or c2_receipt.get("response_sha256") != proof.transcription_response_sha256
            or c5_receipt.get("response_sha256") != proof.coaching_response_sha256
            or selected_c2.id != c2_row.id
            or aligned_c2.id != c2_row.id
            or config.get("profile_sha256") != draft.profile_sha256
            or config.get("input_sha256") != coaching.input_sha256
            or content_hash(request.get("profile")) != draft.profile_sha256
            or aggregate_row.payload is None
            or aggregate_row.payload.get("schema") != "ac.sales-xray.complete-facts/1"
            or [chunk.get("id") for chunk in aggregate_row.payload.get("chunks", [])]
            != request.get("fact_checkpoint_ids")
            or c6.parents != (("C5", c5.manifest_sha256),)
            or c6_row.payload
            != {
                "schema": "ac.sales-xray.draft-presentation/1",
                "report": draft.payload,
                "transcript_checkpoint_id": str(c2_row.id),
                "profile_sha256": draft.profile_sha256,
                "human_approved": False,
                "numeric_publication": False,
            }
        ):
            raise ConversationConflict("The stored report's canonical evidence differs.")
        for chunk in aggregate_row.payload["chunks"]:
            chunk_row, chunk_checkpoint = await pipeline.checkpoint(
                recording, UUID(chunk["id"]), "C4"
            )
            if chunk_checkpoint.manifest_sha256 != chunk.get("manifest_sha256"):
                raise ConversationConflict("The stored fact checkpoint differs.")
            await pipeline.provider_task(recording, chunk_row)

    async def history(self, actor: ActorContext) -> dict[str, Any]:
        now = await self.application.admit(actor)
        recordings = (
            await self.database.scalars(
                select(ConversationRecording)
                .join(
                    ConversationPermission,
                    ConversationPermission.id == ConversationRecording.permission_id,
                )
                .where(
                    ConversationRecording.tenant_id == actor.tenant_id,
                    ConversationRecording.person_id == actor.person_id,
                    ConversationRecording.state.in_(("awaiting_upload", "ready")),
                    ConversationPermission.tenant_id == actor.tenant_id,
                    ConversationPermission.person_id == actor.person_id,
                    ConversationPermission.source_sha256 == ConversationRecording.source_sha256,
                    ConversationPermission.provider == "local",
                    ConversationPermission.revoked_at.is_(None),
                    ConversationPermission.expires_at > now,
                    ConversationPermission.retention_until > now,
                )
                .order_by(ConversationRecording.created_at.desc(), ConversationRecording.id.desc())
                .limit(20)
            )
        ).all()
        result = []
        for recording in recordings:
            latest = await self.database.scalar(
                select(ConversationRun)
                .where(
                    ConversationRun.recording_id == recording.id,
                    ConversationRun.tenant_id == actor.tenant_id,
                    ConversationRun.person_id == actor.person_id,
                )
                .order_by(ConversationRun.created_at.desc(), ConversationRun.id.desc())
                .limit(1)
            )
            has_report = False
            run_view = None
            if latest is not None:
                current = await self.application._run_view(actor, latest.id)
                run_view = {
                    "id": str(latest.id),
                    "state": current["state"],
                    "recipe_revision": latest.recipe_revision,
                    "provider_calls": current["provider_calls"],
                }
                recovered = await RetainedC5RecoveryService(self.application).owner_report(
                    actor, latest.id
                )
                if recovered is not None:
                    has_report = True
                draft = await self.database.scalar(
                    select(ConversationReportDraft)
                    .where(
                        ConversationReportDraft.run_id == latest.id,
                        ConversationReportDraft.tenant_id == actor.tenant_id,
                        ConversationReportDraft.person_id == actor.person_id,
                        ConversationReportDraft.erased_at.is_(None),
                    )
                    .limit(1)
                )
                if draft is not None:
                    try:
                        self._validated(draft, recording)
                        await self._canonical_draft(draft, recording)
                        has_report = True
                    except (ConversationConflict, ValueError, TypeError, KeyError):
                        if recovered is None:
                            has_report = False
                run_view["has_report"] = has_report
            result.append(
                {
                    **self.application._view(recording),
                    "latest_run": run_view,
                    "has_report": has_report,
                }
            )
        return {"recordings": result}

    async def transcript(self, actor: ActorContext, recording_id: UUID) -> dict[str, Any]:
        await self.application.get(actor, recording_id)
        recording = await self.application._recording(actor, recording_id)
        draft = await self.database.scalar(
            select(ConversationReportDraft)
            .where(
                ConversationReportDraft.recording_id == recording_id,
                ConversationReportDraft.tenant_id == actor.tenant_id,
                ConversationReportDraft.person_id == actor.person_id,
                ConversationReportDraft.erased_at.is_(None),
            )
            .order_by(ConversationReportDraft.created_at.desc(), ConversationReportDraft.id.desc())
            .limit(1)
        )
        if draft is None:
            from ac_platform.conversation_intelligence.inference import (
                TRANSCRIPT_RECIPE_BY_ROUTE,
                ConversationInference,
            )
            from ac_platform.conversation_intelligence.reporting_pipeline import ReportingPipeline

            latest = await self.database.scalar(
                select(ConversationCheckpoint)
                .where(
                    ConversationCheckpoint.recording_id == recording.id,
                    ConversationCheckpoint.tenant_id == recording.tenant_id,
                    ConversationCheckpoint.person_id == recording.person_id,
                    ConversationCheckpoint.stage == "C2",
                    ConversationCheckpoint.erased_at.is_(None),
                )
                .order_by(ConversationCheckpoint.created_at.desc())
                .limit(1)
            )
            if latest is None:
                raise ConversationNotFound("A saved transcript is not available yet.")
            pipeline = ReportingPipeline(ConversationInference(self.application))
            latest, _ = await pipeline.checkpoint(recording, latest.id, "C2")
            task, receipt = await pipeline.provider_task(recording, latest)
            transcript = latest.payload
            if transcript is None or transcript.get("revision") != receipt.get("response_sha256"):
                raise ConversationConflict("The saved transcript's receipt differs.")
            source = await pipeline.service.plan_transcription(recording)
            provider = receipt.get("provider")
            model = receipt.get("model")
            try:
                if not isinstance(provider, str) or not isinstance(model, str):
                    raise ValueError
                expected_recipe = TRANSCRIPT_RECIPE_BY_ROUTE.get((provider, model))
                if expected_recipe is None:
                    raise ValueError
                prepared = prepare_scribe_input(
                    source_sha256=recording.source_sha256,
                    duration_ms=source.duration_ms,
                    content_type=recording.content_type,
                    provider=provider,
                    model=model,
                )
                expected_checkpoint = replace(
                    source.checkpoint,
                    revision=expected_recipe,
                    config_json=canonical(
                        {
                            "provider": prepared.provider,
                            "model": prepared.model,
                            "operation": prepared.operation,
                            "duration_ms": source.duration_ms,
                        }
                    ).decode(),
                )
            except (TypeError, ValueError):
                raise ConversationConflict("The saved transcript's route differs.") from None
            if task.stage != "C2" or latest.cache_key != expected_checkpoint.cache_key:
                raise ConversationConflict("The saved transcript's route differs.")
            # C2 may be bound to a hosted native route selected by the release
            # authority; this read path has no route authority. C1's measured
            # duration is the only source fact needed for this projection; the
            # saved C2 route is checked against its receipt and checkpoint above.
            if (
                transcript.get("source_sha256") != recording.source_sha256
                or transcript.get("duration_ms") != source.duration_ms
            ):
                raise ConversationConflict("The transcript's source measurement differs.")
            transcript = project_transcript_for_playback(
                transcript, duration_ms=source.duration_ms
            )
            extract_style_independent_facts(transcript)
        else:
            _, transcript = self._validated(draft, recording)
            await self._canonical_draft(draft, recording)
        return {
            name: transcript[name]
            for name in ("source_sha256", "revision", "timebase_id", "duration_ms", "segments")
        }

    async def _response(
        self, actor: ActorContext, run: dict[str, Any], draft: ConversationReportDraft
    ) -> dict[str, Any]:
        recording = await self.application._recording(actor, UUID(run["recording_id"]))
        if draft.run_id != UUID(run["id"]):
            raise ConversationConflict("The report belongs to another analysis.")
        report, _ = self._validated(draft, recording)
        await self._canonical_draft(draft, recording)
        return {
            **run,
            "report": report.model_dump(mode="json"),
            "message": "Your private AI draft is ready. Dipak has not reviewed it yet.",
        }

    async def get(self, actor: ActorContext, run_id: UUID) -> dict[str, Any]:
        run = await self.application.get_run(actor, run_id)
        recovered = await RetainedC5RecoveryService(self.application).owner_report(actor, run_id)
        if recovered is not None:
            return {
                **run,
                "report": recovered["report"],
                "message": recovered["message"],
                "recovery": recovered["recovery"],
            }
        draft = await self.database.scalar(
            select(ConversationReportDraft)
            .where(
                ConversationReportDraft.run_id == run_id,
                ConversationReportDraft.tenant_id == actor.tenant_id,
                ConversationReportDraft.person_id == actor.person_id,
                ConversationReportDraft.recording_id == UUID(run["recording_id"]),
                ConversationReportDraft.erased_at.is_(None),
            )
            .order_by(ConversationReportDraft.created_at.desc(), ConversationReportDraft.id.desc())
            .limit(1)
        )
        if draft is None:
            return {
                **run,
                "report": None,
                "message": "Audio analysis is ready; a sales report has not been added yet."
                if run["state"] == "completed"
                else "Your call is being processed."
                if run["state"] in {"queued", "running"}
                else "Analysis needs attention. Your recording remains private.",
            }
        return await self._response(actor, run, draft)

    async def import_internal_draft(
        self,
        actor: ActorContext,
        run_id: UUID,
        intent: PrivateDraftIntent,
        *,
        storage: RecordingObjectStorage,
        key: str,
    ) -> dict[str, Any]:
        await ConversationProviderAdmin(self.application).admit(actor)
        run = await self.application.get_run(actor, run_id)
        run_row = await self.database.get(ConversationRun, run_id)
        recording = await self.application._recording(actor, UUID(run["recording_id"]))
        if (
            run_row is None
            or run_row.state != "completed"
            or run_row.generation != recording.generation
            or recording.state != "ready"
        ):
            raise ConversationConflict(
                "Finish this recording's local analysis before importing a draft."
            )
        from ac_platform.conversation_intelligence.inference import ConversationInference

        source_plan = await ConversationInference(self.application).plan_transcription(
            recording, signal_recipe=run_row.recipe_revision
        )
        signal = await self.database.get(ConversationCheckpoint, source_plan.signal_id)
        if signal is None or signal.payload is None or signal.manifest is None:
            raise ConversationConflict("A verified local audio checkpoint is required.")
        duration = signal.payload.get("media_duration_ms")
        if (
            type(duration) is not int
            or duration <= 0
            or signal.payload.get("source_sha256") != recording.source_sha256
            or content_hash(signal.payload) != signal.payload_sha256
            or signal.manifest.get("binding")
            != {
                "tenant_id": str(recording.tenant_id),
                "recording_id": str(recording.id),
                "source_sha256": recording.source_sha256,
                "source_revision": str(recording.source_revision),
            }
        ):
            raise ConversationConflict("The audio checkpoint is inconsistent.")
        raw = intent.raw_transcription_json.encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        if digest != intent.receipt.transcription_response_sha256:
            raise ConversationError("The native transcription does not match its receipt.")
        try:
            native = json.loads(raw)
            if not isinstance(native, dict):
                raise ValueError("invalid native envelope")
            normalized = scribe_transcript(
                ProviderResult(
                    provider="elevenlabs",
                    model="scribe_v2",
                    request_id=None,
                    response_sha256=digest,
                    raw_json=raw,
                    data=native,
                    input_sha256=recording.source_sha256,
                ),
                duration_ms=duration,
                source_sha256=recording.source_sha256,
            )
            normalized["duration_ms"] = duration
            report = parse_report_draft(intent.report, normalized, source_label="Your sales call")
        except (ValueError, TypeError, KeyError):
            raise ConversationError(
                "The draft or its exact transcript evidence is invalid."
            ) from None
        payload = report.model_dump(mode="json")
        receipt = intent.receipt.model_dump(mode="json")
        transcript = {"native_json": intent.raw_transcription_json, "normalized": normalized}
        command = {
            "run_id": str(run_id),
            "report_sha256": content_hash(payload),
            "transcript_sha256": content_hash(transcript),
            "receipt_sha256": content_hash(receipt),
        }
        replay = await self.application._replay(actor, key, "import_private_draft", command)
        if replay is not None:
            if replay.result_id is None:
                raise ConversationConflict("The imported report receipt is unavailable.")
            previous = await self.database.get(ConversationReportDraft, replay.result_id)
            if previous is None:
                raise ConversationConflict("The imported report receipt is unavailable.")
            return await self._response(actor, run, previous)
        source_key = ObjectKey(
            recording.tenant_id, recording.id, recording.id, ObjectKind.SOURCE_AUDIO
        )
        try:
            size = await join_thread(
                lambda: sum(
                    len(block)
                    for block in storage.iter_bytes(
                        source_key, expected_sha256=recording.source_sha256
                    )
                )
            )
        except StorageError:
            raise ConversationConflict("The retained recording is unavailable.") from None
        if size != recording.source_bytes:
            raise ConversationConflict("The retained recording is inconsistent.")
        existing = await self.database.scalar(
            select(ConversationReportDraft).where(
                ConversationReportDraft.run_id == run_id,
                ConversationReportDraft.report_sha256 == command["report_sha256"],
            )
        )
        if existing is not None:
            if (
                existing.transcript_sha256 != command["transcript_sha256"]
                or existing.evidence_receipt_sha256 != command["receipt_sha256"]
                or existing.erased_at is not None
            ):
                raise ConversationConflict("This report version has conflicting evidence.")
            draft = existing
        else:
            draft = ConversationReportDraft(
                id=uuid4(),
                tenant_id=actor.tenant_id,
                person_id=actor.person_id,
                recording_id=recording.id,
                run_id=run_id,
                source_revision=recording.source_revision,
                source_sha256=recording.source_sha256,
                report_sha256=command["report_sha256"],
                transcript_sha256=command["transcript_sha256"],
                profile_sha256=content_hash(load_report_profile()),
                evidence_receipt_sha256=command["receipt_sha256"],
                payload=payload,
                transcript=transcript,
                evidence_receipt=receipt,
                created_at=utc(self.application.clock()),
            )
            self.database.add(draft)
            await self.database.flush()
        await self.application._receipt(
            actor,
            key,
            "import_private_draft",
            command,
            draft.id,
            utc(self.application.clock()),
            resource_type="conversation_report_draft",
        )
        return await self._response(actor, run, draft)
