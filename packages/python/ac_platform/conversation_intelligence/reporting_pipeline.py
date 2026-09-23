"""Canonical C3–C6 composition; no provider dispatch or quote issuance here.

Callers hold the current owner/session and recording locks. Every text effect has
its own immutable input, accepted quote, reservation and durable provider task.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
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
from ac_platform.conversation_intelligence.contracts import C5RepairIntent
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
from ac_platform.conversation_intelligence.qualitative_pack import (
    ReportLanguage,
    load_qualitative_pack,
)
from ac_platform.conversation_intelligence.reports import (
    COACHING_PROMPT_LEGACY,
    COACHING_PROMPT_V4,
    FACT_PROMPT_LEGACY,
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


def _raw_response_binding(
    receipt: dict[str, Any], task: ConversationInferenceTask, recording: ConversationRecording
) -> bool:
    """Accept either the task-local raw blob or an explicit retained C2 source blob."""

    marker = receipt.get("retained_reuse")
    if marker is None:
        return receipt.get("raw_blob_id") == str(task.run_id)
    return (
        isinstance(marker, dict)
        and set(marker)
        == {
            "schema",
            "provider_calls",
            "source_recording_id",
            "source_run_id",
            "source_response_sha256",
        }
        and marker.get("schema") == "ac.sales-xray.retained-c2-reuse/1"
        and type(marker.get("provider_calls")) is int
        and marker.get("provider_calls") == 0
        and marker.get("source_recording_id") != str(recording.id)
        and marker.get("source_run_id") == receipt.get("raw_blob_id")
        and marker.get("source_run_id") != str(task.run_id)
        and marker.get("source_response_sha256") == receipt.get("response_sha256")
        and isinstance(marker.get("source_run_id"), str)
        and isinstance(marker.get("source_recording_id"), str)
        and isinstance(marker.get("source_response_sha256"), str)
        and len(marker["source_response_sha256"]) == 64
        and all(character in "0123456789abcdef" for character in marker["source_response_sha256"])
    )


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
    fact_prompt_revision: Literal["facts-v1", "facts-v2"] = Field(
        default=FACT_PROMPT_LEGACY,
        exclude_if=lambda value: value == FACT_PROMPT_LEGACY,
    )
    coaching_prompt_revision: Literal[
        "coaching-v1", "coaching-v2", "coaching-v3", "coaching-v4"
    ] = Field(
        default=COACHING_PROMPT_LEGACY, exclude_if=lambda value: value == COACHING_PROMPT_LEGACY
    )
    report_language: ReportLanguage | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    qualitative_pack_sha256: str | None = Field(
        default=None,
        pattern=r"^[a-f0-9]{64}$",
        exclude_if=lambda value: value is None,
    )
    output_profile: Literal["standard", "detailed"] = Field(
        default="detailed", exclude_if=lambda value: value == "detailed"
    )
    profile: dict[str, Any] | None = Field(default=None, repr=False)
    repair: C5RepairIntent | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def stage_shape(self) -> StageRequest:
        if self.max_completion_tokens > completion_ceiling(self.provider, self.model, self.stage):
            raise ValueError("Stage output exceeds the provider route limit.")
        if self.stage == "C4" and (self.fact_checkpoint_ids or self.profile is not None):
            raise ValueError("Facts cannot take coaching configuration.")
        if self.stage == "C4" and self.output_profile != "detailed":
            raise ValueError("Facts cannot select a coaching output profile.")
        if self.stage == "C4" and self.repair is not None:
            raise ValueError("Facts cannot use coaching repair.")
        if self.stage == "C5" and self.fact_prompt_revision != FACT_PROMPT_LEGACY:
            raise ValueError("Coaching cannot select a fact prompt revision.")
        if self.stage == "C4" and self.coaching_prompt_revision != COACHING_PROMPT_LEGACY:
            raise ValueError("Facts cannot select a coaching prompt revision.")
        if self.stage == "C4" and (
            self.report_language is not None or self.qualitative_pack_sha256 is not None
        ):
            raise ValueError("Facts cannot select coaching configuration.")
        if self.stage == "C5" and (not self.fact_checkpoint_ids or self.chunk_index != 1):
            raise ValueError("Coaching requires complete fact checkpoints.")
        if self.stage == "C5" and self.coaching_prompt_revision == COACHING_PROMPT_V4:
            if (
                self.report_language is None
                or self.qualitative_pack_sha256 != load_qualitative_pack().sha256
            ):
                raise ValueError("Coaching requires the current qualitative pack and language.")
        elif self.stage == "C5" and (
            self.report_language not in {None, "en"} or self.qualitative_pack_sha256 is not None
        ):
            raise ValueError("This coaching prompt revision cannot select language or a pack.")
        if len(set(self.fact_checkpoint_ids)) != len(self.fact_checkpoint_ids):
            raise ValueError("Duplicate fact checkpoint.")
        if self.profile is not None and len(canonical(self.profile)) > 128 * 1024:
            raise ValueError("Profile exceeds its limit.")
        return self


def repair_coaching_input(prepared: PreparedTaskInput, repair: C5RepairIntent) -> PreparedTaskInput:
    """Add one bounded format repair instruction without changing source inputs."""

    if prepared.task != "coaching":
        raise ConversationConflict("Only a coaching response can be repaired.")
    body = prepared.as_provider_body()
    if prepared.provider == "groq":
        messages = body.get("messages")
        if (
            not isinstance(messages, list)
            or len(messages) != 2
            or not isinstance(messages[0], dict)
            or not isinstance(messages[0].get("content"), str)
        ):
            raise ConversationConflict("The coaching repair envelope is unavailable.")
        system = messages[0]["content"]
        messages[0]["content"] = _repair_system_content(system, repair)
    else:
        instruction = body.get("systemInstruction")
        parts = instruction.get("parts") if isinstance(instruction, dict) else None
        if (
            not isinstance(parts, list)
            or len(parts) != 1
            or not isinstance(parts[0], dict)
            or not isinstance(parts[0].get("text"), str)
        ):
            raise ConversationConflict("The coaching repair envelope is unavailable.")
        parts[0]["text"] = _repair_system_content(parts[0]["text"], repair)
    payload = canonical(body)
    return replace(
        prepared,
        payload=payload,
        input_sha256=hashlib.sha256(payload).hexdigest(),
    )


def _repair_system_content(system: str, repair: C5RepairIntent) -> str:
    marker = "Profile:\n"
    head, separator, profile = system.rpartition(marker)
    if not separator or not profile:
        raise ConversationConflict("The coaching repair profile is unavailable.")
    instruction = (
        "SERVER_REPAIR: The previous provider-returned C5 object failed the server's "
        f"canonical validation ({repair.failure_code}). Return one complete JSON object "
        "matching the existing schema and exact source references. Use only the supplied "
        "transcript, facts and frozen profile. Preserve uncertainty; do not add unsupported "
        "claims, scores, approvals, identities or new provenance. This is a format repair."
    )
    if repair.failure_code == "conversation_report_evidence_invalid":
        instruction += (
            " Evidence correction: prefer {segment_id} alone for a whole source segment "
            "of at most 2000 characters. Only use {segment_id,quote_start,quote_end} for "
            "a shorter excerpt. These offsets are zero-based Python Unicode code-point "
            "indices into that segment's text, with an exclusive end. They are never "
            "audio timestamps. Require 0 <= quote_start < quote_end <= len(segment.text), "
            "and an excerpt of at most 2000 characters. Do not copy start_ms/end_ms "
            "into quote_start/quote_end. The server supplies native timestamps."
        )
    return f"{head}\n{instruction}\n{marker}{profile}"


@dataclass(frozen=True)
class StagePlan:
    prepared: PreparedTaskInput
    checkpoint: Checkpoint
    duration_ms: int
    request: StageRequest
    transcript: dict[str, Any] = field(repr=False)
    native_transcript: dict[str, Any] = field(repr=False)
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
        retained_binding = (
            task is not None
            and isinstance(receipt, dict)
            and receipt.get("retained_reuse") is not None
            and _raw_response_binding(receipt, task, recording)
        )
        if (
            task is None
            or job is None
            or quoted is None
            or run is None
            or not isinstance(receipt, dict)
            or job.kind != "conversation.infer_provider.v1"
            or job.tenant_id != recording.tenant_id
            or (not job.external_side_effect and not retained_binding)
            or job.status not in {"succeeded", "leased", "queued"}
            or (job.dispatch_started_at is None and not retained_binding)
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
            or (
                not retained_binding
                and receipt.get("idempotency_key") != job.provider_idempotency_key
            )
            or receipt.get("checkpoint_id") != str(row.id)
            or receipt.get("checkpoint_manifest_sha256") != row.manifest_sha256
            or receipt.get("input_sha256") != task.input_sha256
            or not _raw_response_binding(receipt, task, recording)
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
        from ac_platform.conversation_intelligence.alignment import (
            build_alignment,
            project_transcript_for_playback,
        )
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
        native_transcript = transcript_row.payload
        assert native_transcript is not None and signal_row.payload is not None
        if native_transcript.get("revision") != transcript_receipt.get("response_sha256"):
            raise ConversationConflict("The transcript differs from its native receipt.")
        transcript = project_transcript_for_playback(
            native_transcript, duration_ms=source.duration_ms
        )
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
                prompt_revision=request.fact_prompt_revision,
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
            return StagePlan(
                prepared,
                template,
                source.duration_ms,
                request,
                transcript,
                native_transcript,
                None,
            )

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
            output_profile=request.output_profile,
            coaching_prompt_revision=request.coaching_prompt_revision,
            report_language=request.report_language or "en",
            qualitative_pack_sha256=request.qualitative_pack_sha256,
        )
        if request.repair is not None:
            prepared = repair_coaching_input(prepared, request.repair)
        c5_config: dict[str, Any] = {
            "input_sha256": prepared.input_sha256,
            "provider": prepared.provider,
            "model": prepared.model,
            "profile_sha256": content_hash(profile),
        }
        if request.coaching_prompt_revision != COACHING_PROMPT_LEGACY:
            c5_config["coaching_prompt_revision"] = request.coaching_prompt_revision
        if request.coaching_prompt_revision == COACHING_PROMPT_V4:
            c5_config["report_language"] = request.report_language
            c5_config["qualitative_pack_sha256"] = request.qualitative_pack_sha256
        if request.repair is not None:
            c5_config["repair"] = request.repair.model_dump(mode="json")
        template = build_checkpoint(
            binding,
            "C5",
            COACHING_RECIPE,
            c5_config,
            (aggregate,),
            "0" * 64,
        )
        return StagePlan(
            prepared,
            template,
            source.duration_ms,
            request,
            transcript,
            native_transcript,
            profile,
        )

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
        if plan.transcript != plan.native_transcript:
            transcript_bundle["native"] = plan.native_transcript
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
