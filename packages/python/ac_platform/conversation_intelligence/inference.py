"""Durable external-stage admission; local storage permission never authorizes AI.

Only server-issued exact quotes enter this service. It cannot issue provider
terms, pricing, professional approvals, grants, or credentials for itself.
The first executable stage is C2; C4/C5 adapters remain separately composed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select

from ac_platform.conversation_intelligence.application import (
    AUDIOATLAS_RECIPE,
    ConversationApplication,
    ConversationConflict,
    ConversationDenied,
)
from ac_platform.conversation_intelligence.checkpoints import (
    Checkpoint,
    SourceBinding,
    build_checkpoint,
    content_hash,
)
from ac_platform.conversation_intelligence.contracts import QuoteAcceptance
from ac_platform.conversation_intelligence.entitlements import (
    BudgetAccount,
    ExecutionPermission,
    MinuteAccount,
    Quote,
    reserve,
)
from ac_platform.conversation_intelligence.inference_tasks import (
    PreparedTaskInput,
    prepare_scribe_input,
)
from ac_platform.conversation_intelligence.models import (
    ConversationBudgetAccount,
    ConversationCheckpoint,
    ConversationInferenceTask,
    ConversationMinuteAccount,
    ConversationQuote,
    ConversationQuoteAcceptance,
    ConversationRecording,
    ConversationRun,
)
from ac_platform.kernel.authz import ActorContext
from ac_platform.outbox.repository import JobRepository

INFERENCE_JOB = "conversation.infer_provider.v1"
TRANSCRIPT_RECIPE = "scribe-v2-native-normalized-v1"


def binding_for(recording: ConversationRecording) -> SourceBinding:
    return SourceBinding(
        str(recording.tenant_id),
        str(recording.id),
        recording.source_sha256,
        str(recording.source_revision),
    )


def verified_checkpoint(row: ConversationCheckpoint, binding: SourceBinding) -> Checkpoint:
    """Reconstruct and verify content and lineage before using a cache hit."""
    try:
        manifest = row.manifest
        if not isinstance(manifest, dict) or not isinstance(row.payload, dict):
            raise ValueError
        checkpoint = Checkpoint(
            SourceBinding(**manifest["binding"]),
            manifest["stage"],
            manifest["revision"],
            manifest["config_json"],
            tuple(tuple(p) for p in manifest["parents"]),
            manifest["payload_sha256"],
            manifest["replicate"],
        )
        if (
            checkpoint.binding != binding
            or checkpoint.as_dict()
            != {**manifest, "parents": tuple(tuple(p) for p in manifest["parents"])}
            or checkpoint.cache_key != row.cache_key
            or checkpoint.manifest_sha256 != row.manifest_sha256
            or checkpoint.payload_sha256 != row.payload_sha256
            or content_hash(row.payload) != row.payload_sha256
            or row.erased_at is not None
        ):
            raise ValueError
        return checkpoint
    except (TypeError, ValueError, KeyError):
        raise ConversationConflict("The saved checkpoint failed its integrity check.") from None


@dataclass(frozen=True)
class TranscriptionPlan:
    prepared: PreparedTaskInput
    checkpoint: Checkpoint
    duration_ms: int

    def intent(self) -> dict[str, Any]:
        return {
            "schema": "ac.sales-xray.transcription-intent/1",
            "source_sha256": self.prepared.source_sha256,
            "duration_ms": self.duration_ms,
            "checkpoint": self.checkpoint.as_dict(),
        }


class ConversationInference:
    def __init__(self, application: ConversationApplication) -> None:
        self.application = application
        self.database = application.database

    async def plan_transcription(self, recording: ConversationRecording) -> TranscriptionPlan:
        """Internal only: caller must already lock and authorize this recording."""
        binding = binding_for(recording)
        c0 = build_checkpoint(
            binding,
            "C0",
            "recording-v1",
            {},
            (),
            content_hash(
                {
                    "source_sha256": recording.source_sha256,
                    "source_bytes": recording.source_bytes,
                    "content_type": recording.content_type,
                    "permission_reference": str(recording.permission_id),
                }
            ),
        )
        c1 = build_checkpoint(
            binding,
            "C1",
            AUDIOATLAS_RECIPE,
            {"decode_rate": 48000, "window_profile": "audioatlas-40ms-10ms"},
            (c0,),
            "0" * 64,
        )
        rows = (
            await self.database.scalars(
                select(ConversationCheckpoint).where(
                    ConversationCheckpoint.recording_id == recording.id,
                    ConversationCheckpoint.tenant_id == recording.tenant_id,
                    ConversationCheckpoint.person_id == recording.person_id,
                    ConversationCheckpoint.cache_key.in_((c0.cache_key, c1.cache_key)),
                    ConversationCheckpoint.erased_at.is_(None),
                )
            )
        ).all()
        by_stage = {row.stage: row for row in rows}
        if set(by_stage) != {"C0", "C1"}:
            raise ConversationConflict("Finish local audio inspection before transcription.")
        if verified_checkpoint(by_stage["C0"], binding) != c0:
            raise ConversationConflict("The original recording checkpoint changed.")
        actual_c1 = verified_checkpoint(by_stage["C1"], binding)
        if actual_c1.parents != c1.parents:
            raise ConversationConflict("The measured recording has different source parents.")
        payload = by_stage["C1"].payload
        assert payload is not None
        duration = payload.get("media_duration_ms")
        if (
            type(duration) is not int
            or duration <= 0
            or payload.get("source_sha256") != recording.source_sha256
        ):
            raise ConversationConflict("The recording needs a verified duration.")
        prepared = prepare_scribe_input(
            source_sha256=recording.source_sha256,
            duration_ms=duration,
            content_type=recording.content_type,
        )
        template = build_checkpoint(
            binding,
            "C2",
            TRANSCRIPT_RECIPE,
            {
                "provider": prepared.provider,
                "model": prepared.model,
                "operation": prepared.operation,
                "duration_ms": duration,
            },
            (c0,),
            "0" * 64,
        )
        return TranscriptionPlan(prepared, template, duration)

    async def _quote(
        self,
        actor: ActorContext,
        recording: ConversationRecording,
        quote_id: UUID,
        plan: TranscriptionPlan,
        now: datetime,
        *,
        require_acceptance: bool,
    ) -> tuple[ConversationQuote, Quote, ExecutionPermission]:
        row = await self.database.scalar(
            select(ConversationQuote)
            .where(
                ConversationQuote.id == quote_id,
                ConversationQuote.tenant_id == actor.tenant_id,
                ConversationQuote.person_id == actor.person_id,
                ConversationQuote.recording_id == recording.id,
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if row is None or row.revoked_at is not None:
            raise ConversationDenied("An exact external-processing quote is required.")
        quote, permission = (
            Quote.from_dict(row.quote),
            ExecutionPermission.from_dict(row.execution_permission),
        )
        if (
            quote.quote_id != str(row.id)
            or quote.source != binding_for(recording)
            or quote.account_id != str(actor.person_id)
            or quote.budget_scope_id != str(row.budget_scope_id)
            or quote.recipe_revision != TRANSCRIPT_RECIPE
            or quote.provider_id != plan.prepared.provider
            or quote.provider_model != plan.prepared.model
            or quote.operation != plan.prepared.operation
            or quote.input_sha256 != plan.prepared.input_sha256
            or quote.entitlement_seconds != (plan.duration_ms + 999) // 1000
            or permission.quote_fingerprint != quote.fingerprint
            or permission.approved_by != str(actor.person_id)
            or not quote.created_at_epoch
            <= int(now.timestamp())
            < min(quote.expires_at_epoch, permission.expires_at_epoch)
        ):
            raise ConversationDenied("This quote does not authorize this exact provider request.")
        if require_acceptance:
            accepted = await self.database.scalar(
                select(ConversationQuoteAcceptance)
                .where(
                    ConversationQuoteAcceptance.quote_id == row.id,
                )
                .execution_options(populate_existing=True)
            )
            if (
                accepted is None
                or accepted.person_id != actor.person_id
                or accepted.tenant_id != actor.tenant_id
                or accepted.session_id != actor.session_id
                or accepted.quote_fingerprint != quote.fingerprint
                or accepted.privacy_revision != quote.privacy_revision
            ):
                raise ConversationDenied(
                    "Approve this exact recording, provider, price and privacy quote."
                )
        return row, quote, permission

    async def accept(
        self,
        actor: ActorContext,
        recording_id: UUID,
        quote_id: UUID,
        acceptance: QuoteAcceptance,
    ) -> dict[str, str]:
        now = await self.application.admit(actor)
        await self.application.get(actor, recording_id)
        recording = await self.application._recording(actor, recording_id)
        plan = await self.plan_transcription(recording)
        _, quote, _ = await self._quote(
            actor, recording, quote_id, plan, now, require_acceptance=False
        )
        if (
            acceptance.accepted is not True
            or acceptance.quote_fingerprint != quote.fingerprint
            or acceptance.privacy_revision != quote.privacy_revision
        ):
            raise ConversationDenied("Approve the exact displayed quote and privacy terms.")
        existing = await self.database.get(ConversationQuoteAcceptance, quote_id)
        if existing is None:
            self.database.add(
                ConversationQuoteAcceptance(
                    quote_id=quote_id,
                    tenant_id=recording.tenant_id,
                    person_id=recording.person_id,
                    session_id=actor.session_id,
                    quote_fingerprint=quote.fingerprint,
                    privacy_revision=quote.privacy_revision,
                    accepted_at=now,
                )
            )
            await self.database.flush()
            await self.application._receipt(
                actor,
                f"provider-accept:{quote_id}",
                "provider_quote_accepted",
                acceptance.model_dump(mode="json"),
                quote_id,
                now,
            )
        await self._quote(actor, recording, quote_id, plan, now, require_acceptance=True)
        return {"id": str(quote_id), "state": "accepted"}

    async def accounts(
        self,
        recording: ConversationRecording,
        quote: ConversationQuote,
    ) -> tuple[ConversationMinuteAccount, ConversationBudgetAccount]:
        budget = await self.database.scalar(
            select(ConversationBudgetAccount)
            .where(
                ConversationBudgetAccount.scope_id == quote.budget_scope_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        minutes = await self.database.scalar(
            select(ConversationMinuteAccount)
            .where(
                ConversationMinuteAccount.tenant_id == recording.tenant_id,
                ConversationMinuteAccount.person_id == recording.person_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if budget is None or minutes is None:
            raise ConversationDenied("An explicitly approved processing allowance is required.")
        return minutes, budget

    async def request_transcription(
        self,
        actor: ActorContext,
        recording_id: UUID,
        quote_id: UUID,
        *,
        key: str,
    ) -> dict[str, Any]:
        now = await self.application.admit(actor)
        await self.application.get(actor, recording_id)
        recording = await self.application._recording(actor, recording_id)
        if recording.state != "ready":
            raise ConversationConflict("The recording is not ready.")
        plan = await self.plan_transcription(recording)
        row, quote, permission = await self._quote(
            actor, recording, quote_id, plan, now, require_acceptance=True
        )
        command = {
            "recording_id": str(recording_id),
            "quote_id": str(quote_id),
            "cache_key": plan.checkpoint.cache_key,
        }
        replay = await self.application._replay(actor, key, "provider_transcription", command)
        if replay is not None and replay.result_id is not None:
            return await self.application._run_view(actor, replay.result_id)
        existing = await self.database.scalar(
            select(ConversationInferenceTask)
            .where(
                ConversationInferenceTask.recording_id == recording_id,
                ConversationInferenceTask.cache_key == plan.checkpoint.cache_key,
            )
            .with_for_update()
        )
        if existing is not None:
            if existing.erased_at is not None or existing.generation != recording.generation:
                raise ConversationConflict("The previous request is no longer reusable.")
            # Another click, quote, or coaching profile cannot create a second ASR effect.
            await self.application._receipt(
                actor, key, "provider_transcription", command, existing.run_id, now
            )
            return await self.application._run_view(actor, existing.run_id)
        identifier = uuid4()
        minutes, budget = await self.accounts(recording, row)
        try:
            transition = reserve(
                MinuteAccount.from_dict(minutes.snapshot),
                BudgetAccount.from_dict(budget.snapshot),
                str(identifier),
                quote,
                permission,
                int(now.timestamp()),
            )
        except ValueError:
            raise ConversationConflict(
                "The approved quote or remaining allowance is unavailable."
            ) from None
        minutes.snapshot, budget.snapshot = (
            transition.minutes.as_dict(),
            transition.budget.as_dict(),
        )
        minutes.revision += 1
        budget.revision += 1
        job = await JobRepository(self.database).enqueue(
            kind=INFERENCE_JOB,
            dedupe_key=f"conversation:provider:{identifier}",
            payload={"schema": 1, "run_id": str(identifier)},
            tenant_id=recording.tenant_id,
            external_side_effect=True,
            # Additional claims can acknowledge an already durable receipt;
            # the worker never repeats a recorded provider dispatch.
            max_attempts=3,
        )
        self.database.add(
            ConversationRun(
                id=identifier,
                tenant_id=recording.tenant_id,
                person_id=recording.person_id,
                recording_id=recording.id,
                request_key=key,
                intent_sha256=content_hash(command),
                recipe_revision=TRANSCRIPT_RECIPE,
                generation=recording.generation,
                state="queued",
                job_id=job.id,
                created_at=now,
            )
        )
        await self.database.flush()
        self.database.add(
            ConversationInferenceTask(
                run_id=identifier,
                tenant_id=recording.tenant_id,
                person_id=recording.person_id,
                recording_id=recording.id,
                session_id=actor.session_id,
                job_id=job.id,
                quote_id=quote_id,
                generation=recording.generation,
                stage="C2",
                cache_key=plan.checkpoint.cache_key,
                input_sha256=plan.prepared.input_sha256,
                intent_sha256=content_hash(plan.intent()),
                intent=plan.intent(),
                state="queued",
                created_at=now,
            )
        )
        await self.database.flush()
        await self.application._receipt(
            actor, key, "provider_transcription", command, identifier, now
        )
        return await self.application._run_view(actor, identifier)
