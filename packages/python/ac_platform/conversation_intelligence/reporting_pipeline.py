"""Canonical C3–C6 composition; no provider dispatch or quote issuance here.

Callers hold the current owner/session and recording locks. Every text effect has
its own immutable input, accepted quote, reservation and durable provider task.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from ac_platform.conversation_intelligence.application import ConversationConflict, utc
from ac_platform.conversation_intelligence.checkpoints import (
    Checkpoint,
    assert_same_artifact,
    build_checkpoint,
    canonical,
    content_hash,
    require_sha256,
)
from ac_platform.conversation_intelligence.completion_limits import completion_ceiling
from ac_platform.conversation_intelligence.entitlements import Quote
from ac_platform.conversation_intelligence.inference_tasks import (
    PreparedTaskInput,
    prepare_coaching_input,
    prepare_fact_inputs,
)
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationInferenceTask,
    ConversationQuote,
    ConversationRecording,
    ConversationReportDraft,
    ConversationRun,
)
from ac_platform.conversation_intelligence.processing_actor import actor_from_row
from ac_platform.conversation_intelligence.providers import ProviderResult
from ac_platform.conversation_intelligence.reports import (
    GROQ_MODEL,
    FactPacket,
    load_report_profile,
    merge_fact_packets,
)
from ac_platform.outbox.models import Job

if TYPE_CHECKING:
    from ac_platform.conversation_intelligence.inference import ConversationInference

ALIGNMENT_RECIPE = "source-clock-support-v1"
FACT_RECIPE = "source-fact-chunk-v1"
COACHING_RECIPE = "qualitative-coaching-v1"


class StageRequest(BaseModel):
    """Internal exact checkpoint selection, never a client-supplied transcript."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    stage: Literal["C4", "C5"]
    transcript_checkpoint_id: UUID
    fact_checkpoint_ids: tuple[UUID, ...] = Field(default=(), max_length=64)
    chunk_index: int = Field(default=1, strict=True, ge=1, le=64)
    provider: Literal["groq", "gemini"] = Field(
        default="groq", exclude_if=lambda value: value == "groq"
    )
    model: str = Field(default=GROQ_MODEL, min_length=1, max_length=128)
    max_input_chars: int = Field(default=16_000, strict=True, ge=512, le=32_000)
    max_completion_tokens: int = Field(default=1_400, strict=True, ge=256, le=8_000)
    profile: dict[str, Any] | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def stage_shape(self) -> StageRequest:
        if self.max_completion_tokens > completion_ceiling(self.provider, self.model, self.stage):
            raise ValueError("Stage output exceeds the provider route limit.")
        if self.stage == "C4" and (self.fact_checkpoint_ids or self.profile is not None):
            raise ValueError("Facts cannot take coaching configuration.")
        if self.stage == "C5" and (not self.fact_checkpoint_ids or self.chunk_index != 1):
            raise ValueError("Coaching requires complete fact checkpoints.")
        if len(set(self.fact_checkpoint_ids)) != len(self.fact_checkpoint_ids):
            raise ValueError("Duplicate fact checkpoint.")
        if self.profile is not None and len(canonical(self.profile)) > 128 * 1024:
            raise ValueError("Profile exceeds its limit.")
        return self


@dataclass(frozen=True)
class StagePlan:
    prepared: PreparedTaskInput
    checkpoint: Checkpoint
    duration_ms: int
    request: StageRequest
    transcript: dict[str, Any] = field(repr=False)
    profile: dict[str, Any] | None = field(repr=False)

    @property
    def recipe_revision(self) -> str:
        return self.checkpoint.revision

    def intent(self) -> dict[str, Any]:
        return {
            "schema": "ac.sales-xray.text-intent/1",
            "request": self.request.model_dump(mode="json"),
            "input": self.prepared.as_dict(),
            "checkpoint": self.checkpoint.as_dict(),
        }


class ReportingPipeline:
    def __init__(self, service: ConversationInference) -> None:
        self.service = service
        self.database = service.database

    async def checkpoint(
        self, recording: ConversationRecording, identifier: UUID, stage: str
    ) -> tuple[ConversationCheckpoint, Checkpoint]:
        from ac_platform.conversation_intelligence.inference import binding_for, verified_checkpoint

        row = await self.database.scalar(
            select(ConversationCheckpoint).where(
                ConversationCheckpoint.id == identifier,
                ConversationCheckpoint.tenant_id == recording.tenant_id,
                ConversationCheckpoint.person_id == recording.person_id,
                ConversationCheckpoint.recording_id == recording.id,
                ConversationCheckpoint.stage == stage,
                ConversationCheckpoint.erased_at.is_(None),
            )
        )
        if row is None:
            raise ConversationConflict("The required saved analysis is unavailable.")
        return row, verified_checkpoint(row, binding_for(recording))

    async def provider_task(
        self, recording: ConversationRecording, row: ConversationCheckpoint
    ) -> tuple[ConversationInferenceTask, dict[str, Any]]:
        task = await self.database.scalar(
            select(ConversationInferenceTask).where(
                ConversationInferenceTask.checkpoint_id == row.id,
                ConversationInferenceTask.recording_id == recording.id,
                ConversationInferenceTask.tenant_id == recording.tenant_id,
                ConversationInferenceTask.person_id == recording.person_id,
                ConversationInferenceTask.generation == recording.generation,
                ConversationInferenceTask.state == "completed",
                ConversationInferenceTask.erased_at.is_(None),
            )
        )
        job = None if task is None else await self.database.get(Job, task.job_id)
        receipt = None if job is None else job.provider_receipt
        quoted = None if task is None else await self.database.get(ConversationQuote, task.quote_id)
        run = None if task is None else await self.database.get(ConversationRun, task.run_id)
        if (
            task is None
            or job is None
            or quoted is None
            or run is None
            or not isinstance(receipt, dict)
            or job.kind != "conversation.infer_provider.v1"
            or job.tenant_id != recording.tenant_id
            or not job.external_side_effect
            or job.status not in {"succeeded", "leased", "queued"}
            or job.dispatch_started_at is None
            or run.state != "completed"
            or run.generation != recording.generation
            or run.job_id != task.job_id
            or run.recording_id != recording.id
            or run.person_id != recording.person_id
            or run.tenant_id != recording.tenant_id
            or quoted.recording_id != recording.id
            or quoted.person_id != recording.person_id
            or quoted.tenant_id != recording.tenant_id
            or task.stage != row.stage
            or task.intent is None
            or content_hash(task.intent) != task.intent_sha256
            or task.cache_key != row.cache_key
            or receipt.get("schema") != "ac.sales-xray.provider-receipt/1"
            or receipt.get("idempotency_key") != job.dedupe_key
            or receipt.get("idempotency_key") != job.provider_idempotency_key
            or receipt.get("checkpoint_id") != str(row.id)
            or receipt.get("checkpoint_manifest_sha256") != row.manifest_sha256
            or receipt.get("input_sha256") != task.input_sha256
            or receipt.get("raw_blob_id") != str(task.run_id)
            or receipt.get("human_approved") is not False
            or receipt.get("validation")
            != {
                "C2": "transcript_schema_and_source_binding",
                "C4": "facts_schema_and_source_binding",
                "C5": "coaching_schema_and_source_binding",
            }.get(task.stage)
        ):
            raise ConversationConflict("A canonical provider receipt is required.")
        from ac_platform.conversation_intelligence.inference import binding_for

        try:
            quote = Quote.from_dict(quoted.quote)
            require_sha256(receipt.get("response_sha256"), "provider response")
            if (
                quote.source != binding_for(recording)
                or quote.account_id != str(recording.person_id)
                or quote.quote_id != str(task.quote_id)
                or quote.provider_id != receipt.get("provider")
                or quote.provider_model != receipt.get("model")
                or quote.input_sha256 != task.input_sha256
                or quote.recipe_revision != run.recipe_revision
            ):
                raise ValueError
        except (ValueError, TypeError, KeyError):
            raise ConversationConflict("The canonical provider route or source differs.") from None
        return task, receipt

    async def parent(
        self, recording: ConversationRecording, checkpoint: Checkpoint, stage: str
    ) -> tuple[ConversationCheckpoint, Checkpoint]:
        digest = dict(checkpoint.parents).get(stage)
        identifier = await self.database.scalar(
            select(ConversationCheckpoint.id).where(
                ConversationCheckpoint.recording_id == recording.id,
                ConversationCheckpoint.tenant_id == recording.tenant_id,
                ConversationCheckpoint.person_id == recording.person_id,
                ConversationCheckpoint.stage == stage,
                ConversationCheckpoint.manifest_sha256 == digest,
                ConversationCheckpoint.erased_at.is_(None),
            )
        )
        if digest is None or identifier is None:
            raise ConversationConflict("A required parent checkpoint is unavailable.")
        return await self.checkpoint(recording, identifier, stage)

    async def save(
        self, recording: ConversationRecording, checkpoint: Checkpoint, payload: dict[str, Any]
    ) -> ConversationCheckpoint:
        from ac_platform.conversation_intelligence.inference import binding_for, verified_checkpoint

        existing = await self.database.scalar(
            select(ConversationCheckpoint).where(
                ConversationCheckpoint.recording_id == recording.id,
                ConversationCheckpoint.cache_key == checkpoint.cache_key,
            )
        )
        if existing is not None:
            assert_same_artifact(verified_checkpoint(existing, binding_for(recording)), checkpoint)
            return existing
        row = ConversationCheckpoint(
            id=uuid4(),
            tenant_id=recording.tenant_id,
            person_id=recording.person_id,
            recording_id=recording.id,
            cache_key=checkpoint.cache_key,
            manifest_sha256=checkpoint.manifest_sha256,
            payload_sha256=checkpoint.payload_sha256,
            stage=checkpoint.stage,
            feature_blob_id=None,
            manifest=checkpoint.as_dict(),
            payload=payload,
            created_at=utc(self.service.application.clock()),
        )
        self.database.add(row)
        await self.database.flush()
        return row

    async def plan(self, recording: ConversationRecording, request: StageRequest) -> StagePlan:
        from ac_platform.conversation_intelligence.alignment import build_alignment
        from ac_platform.conversation_intelligence.inference import binding_for

        # Revalidate a detached snapshot even for internal model_copy callers.
        request = StageRequest.model_validate(request.model_dump(mode="json"))
        source = await self.service.plan_transcription(recording)
        if source.signal_id is None:
            raise ConversationConflict("The source measurement checkpoint is required.")
        signal_row, signal = await self.checkpoint(recording, source.signal_id, "C1")
        transcript_row, transcript_checkpoint = await self.checkpoint(
            recording, request.transcript_checkpoint_id, "C2"
        )
        if transcript_checkpoint.cache_key != source.checkpoint.cache_key:
            raise ConversationConflict("The saved transcript uses a different source recipe.")
        _, transcript_receipt = await self.provider_task(recording, transcript_row)
        transcript = transcript_row.payload
        assert transcript is not None and signal_row.payload is not None
        if transcript.get("revision") != transcript_receipt.get("response_sha256"):
            raise ConversationConflict("The transcript differs from its native receipt.")
        aligned = build_alignment(signal_row.payload, transcript)
        binding = binding_for(recording)
        alignment = build_checkpoint(
            binding,
            "C3",
            ALIGNMENT_RECIPE,
            {},
            (signal, transcript_checkpoint),
            content_hash(aligned),
        )
        await self.save(recording, alignment, aligned)
        parents: tuple[Checkpoint, ...] = (transcript_checkpoint, alignment)
        if request.stage == "C4":
            inputs = prepare_fact_inputs(
                transcript,
                provider=request.provider,
                model=request.model,
                max_input_chars=request.max_input_chars,
                max_completion_tokens=request.max_completion_tokens,
            )
            if len(inputs) > 64 or request.chunk_index > len(inputs):
                raise ConversationConflict("The selected fact chunk is unavailable.")
            prepared = inputs[request.chunk_index - 1]
            template = build_checkpoint(
                binding,
                "C4",
                FACT_RECIPE,
                {
                    "input_sha256": prepared.input_sha256,
                    "chunk_index": prepared.chunk_index,
                    "chunk_count": prepared.chunk_count,
                    "provider": prepared.provider,
                    "model": prepared.model,
                },
                parents,
                "0" * 64,
            )
            return StagePlan(prepared, template, source.duration_ms, request, transcript, None)

        packets: list[tuple[FactPacket, Checkpoint, UUID]] = []
        for identifier in request.fact_checkpoint_ids:
            row, checkpoint = await self.checkpoint(recording, identifier, "C4")
            if checkpoint.revision != FACT_RECIPE or checkpoint.parents != (
                ("C2", transcript_checkpoint.manifest_sha256),
                ("C3", alignment.manifest_sha256),
            ):
                raise ConversationConflict("Facts belong to a different transcript or alignment.")
            await self.provider_task(recording, row)
            packet = FactPacket.model_validate(row.payload)
            packets.append((packet, checkpoint, row.id))
        packets.sort(key=lambda item: item[0].chunk_index)
        merged = merge_fact_packets([packet for packet, _, _ in packets], transcript)
        aggregate_payload = {
            "schema": "ac.sales-xray.complete-facts/1",
            "facts": merged.model_dump(mode="json"),
            "chunks": [
                {"id": str(identifier), "manifest_sha256": checkpoint.manifest_sha256}
                for _, checkpoint, identifier in packets
            ],
        }
        aggregate = build_checkpoint(
            binding,
            "C4",
            "source-facts-complete-v1",
            {"chunk_manifests": [checkpoint.manifest_sha256 for _, checkpoint, _ in packets]},
            parents,
            content_hash(aggregate_payload),
        )
        await self.save(recording, aggregate, aggregate_payload)
        profile = load_report_profile() if request.profile is None else request.profile
        request = request.model_copy(
            update={
                "profile": profile,
                "fact_checkpoint_ids": tuple(identifier for _, _, identifier in packets),
            }
        )
        prepared = prepare_coaching_input(
            transcript,
            [packet for packet, _, _ in packets],
            provider=request.provider,
            profile=profile,
            model=request.model,
            max_completion_tokens=request.max_completion_tokens,
        )
        template = build_checkpoint(
            binding,
            "C5",
            COACHING_RECIPE,
            {
                "input_sha256": prepared.input_sha256,
                "provider": prepared.provider,
                "model": prepared.model,
                "profile_sha256": content_hash(profile),
            },
            (aggregate,),
            "0" * 64,
        )
        return StagePlan(prepared, template, source.duration_ms, request, transcript, profile)

    async def finish(
        self,
        recording: ConversationRecording,
        task: ConversationInferenceTask,
        run: ConversationRun,
        plan: StagePlan,
        row: ConversationCheckpoint,
        normalized: dict[str, Any],
        result: ProviderResult,
    ) -> None:
        """Publish an owner-only draft view, atomically with its C5 receipt.

        C6 means a validated presentation artifact, never human adjudication,
        numerical scoring, model promotion or public recording publication.
        """
        from ac_platform.conversation_intelligence.inference import binding_for, verified_checkpoint

        transcript_row, _ = await self.checkpoint(
            recording, plan.request.transcript_checkpoint_id, "C2"
        )
        transcription_task, transcription_receipt = await self.provider_task(
            recording, transcript_row
        )
        if plan.profile is None:
            raise ConversationConflict("A frozen coaching profile is required.")
        c5 = verified_checkpoint(row, binding_for(recording))
        transcript_bundle = {
            "normalized": plan.transcript,
            "profile": plan.profile,
            "native_response_ref": {
                "task_id": str(transcription_task.run_id),
                "response_sha256": transcription_receipt["response_sha256"],
            },
        }
        presented = {
            "schema": "ac.sales-xray.draft-presentation/1",
            "report": normalized,
            "transcript_checkpoint_id": str(transcript_row.id),
            "profile_sha256": content_hash(plan.profile),
            "human_approved": False,
            "numeric_publication": False,
        }
        c6 = build_checkpoint(
            binding_for(recording),
            "C6",
            "owner-draft-presentation-v1",
            {},
            (c5,),
            content_hash(presented),
        )
        c6_row = await self.save(recording, c6, presented)
        evidence = {
            "schema_id": "ac.sales-xray.durable-draft-proof/1",
            "transcript_checkpoint_id": str(transcript_row.id),
            "transcription_task_id": str(transcription_task.run_id),
            "transcription_response_sha256": transcription_receipt["response_sha256"],
            "coaching_checkpoint_id": str(row.id),
            "presentation_checkpoint_id": str(c6_row.id),
            "coaching_response_sha256": result.response_sha256,
            "accepted_quote_id": str(task.quote_id),
            "profile_sha256": content_hash(plan.profile),
            "human_approved": False,
            "numeric_publication": False,
        }
        draft = ConversationReportDraft(
            id=uuid4(),
            tenant_id=recording.tenant_id,
            person_id=recording.person_id,
            recording_id=recording.id,
            run_id=run.id,
            source_revision=recording.source_revision,
            source_sha256=recording.source_sha256,
            report_sha256=content_hash(normalized),
            transcript_sha256=content_hash(transcript_bundle),
            profile_sha256=content_hash(plan.profile),
            evidence_receipt_sha256=content_hash(evidence),
            payload=normalized,
            transcript=transcript_bundle,
            evidence_receipt=evidence,
            created_at=utc(self.service.application.clock()),
        )
        self.database.add(draft)
        await self.database.flush()
        await self.service.application._receipt(
            actor_from_row(task),
            f"provider-draft:{run.id}",
            "provider_draft_persisted",
            {
                "run_id": str(run.id),
                "report_sha256": draft.report_sha256,
                "presentation_manifest_sha256": c6.manifest_sha256,
            },
            draft.id,
            utc(self.service.application.clock()),
            resource_type="conversation_report_draft",
        )
        from ac_platform.conversation_intelligence.acquisition_models import (
            ConversationAcquisitionSettlement,
        )
        from ac_platform.conversation_intelligence.acquisition_sessions import AcquisitionSessions
        from ac_platform.conversation_intelligence.guest_ownership import admit_processing_actor
        from ac_platform.conversation_intelligence.processing_actor import ProcessingActor

        actor = actor_from_row(task)
        if isinstance(actor, ProcessingActor):
            now = utc(self.service.application.clock())
            usage = await admit_processing_actor(self.database, actor, now)
            previous = await self.database.get(ConversationAcquisitionSettlement, usage.id)
            if previous is None:
                await AcquisitionSessions(
                    self.database,
                    tenant_id=actor.tenant_id,
                    policy_revision=usage.policy_revision,
                    clock=lambda: now,
                ).settle(
                    usage.id,
                    charged_seconds=usage.reserved_seconds,
                    receipt_sha256=c6.manifest_sha256,
                )
            elif previous.kind != "completed" or previous.charged_seconds != usage.reserved_seconds:
                raise ConversationConflict("The source usage receipt differs.")
            # A later authorized model/profile report retains the original
            # completed source charge and its first receipt; it never rewrites it.
