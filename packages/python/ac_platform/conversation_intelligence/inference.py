"""Durable external-stage admission; local storage permission never authorizes AI.

Only server-issued exact quotes enter this service. It cannot issue provider
terms, pricing, professional approvals, grants, or credentials for itself.
Each stage is bound to an exact canonical input and a separately accepted quote.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import select

from ac_platform.conversation_intelligence.application import (
    AUDIOATLAS_HOSTED_RECIPE,
    AUDIOATLAS_RECIPES,
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
from ac_platform.conversation_intelligence.processing_actor import (
    ConversationActor,
    actor_columns,
    same_actor,
)
from ac_platform.conversation_intelligence.providers import ProviderResult
from ac_platform.conversation_intelligence.reporting_pipeline import (
    ReportingPipeline,
    StagePlan,
    StageRequest,
)
from ac_platform.outbox.repository import JobRepository

if TYPE_CHECKING:
    from ac_platform.conversation_intelligence.authority import ConversationAuthority

INFERENCE_JOB = "conversation.infer_provider.v1"
TRANSCRIPT_RECIPE = "scribe-v2-native-normalized-v1"
DEEPGRAM_TRANSCRIPT_RECIPE = "deepgram-nova-3-multilingual-v1"
TRANSCRIPT_RECIPE_BY_ROUTE = {
    ("elevenlabs", "scribe_v2"): TRANSCRIPT_RECIPE,
    ("deepgram", "nova-3"): DEEPGRAM_TRANSCRIPT_RECIPE,
}
TRANSCRIPT_RECIPES = frozenset(TRANSCRIPT_RECIPE_BY_ROUTE.values())


def transcription_recipe_for_route(provider: str, model: str) -> str:
    """Return the exact C2 recipe bound to a supported ASR route."""

    try:
        return TRANSCRIPT_RECIPE_BY_ROUTE[(provider, model)]
    except KeyError:
        raise ConversationConflict("The selected transcription route is unavailable.") from None


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
            or checkpoint.stage != row.stage
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
    signal_id: UUID | None = None

    @property
    def recipe_revision(self) -> str:
        return transcription_recipe_for_route(self.prepared.provider, self.prepared.model)

    def intent(self) -> dict[str, Any]:
        return {
            "schema": "ac.sales-xray.transcription-intent/1",
            "source_sha256": self.prepared.source_sha256,
            "duration_ms": self.duration_ms,
            "checkpoint": self.checkpoint.as_dict(),
        }


ServicePlan = TranscriptionPlan | StagePlan


class ConversationInference:
    def __init__(
        self,
        application: ConversationApplication,
        *,
        authority: ConversationAuthority | None = None,
    ) -> None:
        self.application = application
        self.database = application.database
        self.authority = authority

    async def plan_transcription(
        self,
        recording: ConversationRecording,
        *,
        signal_recipe: str | None = None,
        route: tuple[str, str] | None = None,
    ) -> TranscriptionPlan:
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
        # Both exact measurement profiles can establish duration. Prefer the
        # hosted profile when both exist; C2 still depends only on C0, so a
        # measurement/profile change cannot trigger another transcription.
        if signal_recipe is not None and signal_recipe not in AUDIOATLAS_RECIPES:
            raise ConversationConflict("The requested measurement recipe is unavailable.")
        c1_templates = {
            revision: build_checkpoint(
                binding,
                "C1",
                revision,
                {"decode_rate": rate, "window_profile": "audioatlas-40ms-10ms"},
                (c0,),
                "0" * 64,
            )
            for revision, rate in AUDIOATLAS_RECIPES.items()
            if signal_recipe is None or revision == signal_recipe
        }
        rows = (
            await self.database.scalars(
                select(ConversationCheckpoint).where(
                    ConversationCheckpoint.recording_id == recording.id,
                    ConversationCheckpoint.tenant_id == recording.tenant_id,
                    ConversationCheckpoint.person_id == recording.person_id,
                    ConversationCheckpoint.cache_key.in_(
                        (c0.cache_key, *(c.cache_key for c in c1_templates.values()))
                    ),
                    ConversationCheckpoint.erased_at.is_(None),
                )
            )
        ).all()
        ordered = sorted(
            rows,
            key=lambda row: (
                AUDIOATLAS_HOSTED_RECIPE in c1_templates
                and row.cache_key == c1_templates[AUDIOATLAS_HOSTED_RECIPE].cache_key
            ),
        )
        by_stage = {row.stage: row for row in ordered}
        if set(by_stage) != {"C0", "C1"}:
            raise ConversationConflict("Finish local audio inspection before transcription.")
        if verified_checkpoint(by_stage["C0"], binding) != c0:
            raise ConversationConflict("The original recording checkpoint changed.")
        actual_c1 = verified_checkpoint(by_stage["C1"], binding)
        if actual_c1.parents != (("C0", c0.manifest_sha256),):
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
        provider, model = "elevenlabs", "scribe_v2"
        if route is not None:
            provider, model = route
        elif self.authority is not None:
            selected = await self.authority.selected_asr_route(self.application)
            if selected is not None:
                provider, model = selected
        # Validate frozen or newly selected routes through the same canonical
        # recipe map before constructing the immutable C2 checkpoint.
        transcription_recipe_for_route(provider, model)
        prepared = prepare_scribe_input(
            source_sha256=recording.source_sha256,
            duration_ms=duration,
            content_type=recording.content_type,
            provider=provider,
            model=model,
        )
        recipe = transcription_recipe_for_route(prepared.provider, prepared.model)
        template = build_checkpoint(
            binding,
            "C2",
            recipe,
            {
                "provider": prepared.provider,
                "model": prepared.model,
                "operation": prepared.operation,
                "duration_ms": duration,
            },
            (c0,),
            "0" * 64,
        )
        return TranscriptionPlan(prepared, template, duration, by_stage["C1"].id)

    async def plan_task(
        self, recording: ConversationRecording, task: ConversationInferenceTask
    ) -> ServicePlan:
        if task.stage == "C2":
            frozen_route: tuple[str, str] | None = None
            if isinstance(task.intent, dict):
                checkpoint = task.intent.get("checkpoint")
                config = checkpoint.get("config") if isinstance(checkpoint, dict) else None
                if isinstance(config, dict):
                    provider = config.get("provider")
                    model = config.get("model")
                    if isinstance(provider, str) and isinstance(model, str):
                        frozen_route = (provider, model)
            return await self.plan_transcription(recording, route=frozen_route)
        if task.intent is None:
            raise ConversationConflict("The saved provider intent is unavailable.")
        try:
            request = StageRequest.model_validate(task.intent["request"])
        except (ValueError, TypeError, KeyError):
            raise ConversationConflict("The saved provider intent is invalid.") from None
        return await ReportingPipeline(self).plan(recording, request)

    async def finish_stage(
        self,
        recording: ConversationRecording,
        task: ConversationInferenceTask,
        run: ConversationRun,
        plan: ServicePlan,
        checkpoint: ConversationCheckpoint,
        normalized: dict[str, Any],
        result: ProviderResult,
    ) -> None:
        if isinstance(plan, StagePlan) and plan.checkpoint.stage == "C5":
            await ReportingPipeline(self).finish(
                recording, task, run, plan, checkpoint, normalized, result
            )

    async def _quote(
        self,
        actor: ConversationActor,
        recording: ConversationRecording,
        quote_id: UUID,
        plan: ServicePlan,
        now: datetime,
        *,
        require_acceptance: bool,
        dispatch_started_at: datetime | None = None,
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
        # A quote's expiry is the deadline to admit an external effect. Once
        # the durable dispatch marker is committed, a bounded provider call
        # may return after that deadline. All other checks still use ``now``
        # below so revocation, retention and current release authority remain
        # live at provider-return time.
        quote_admission_epoch = int(
            (dispatch_started_at if dispatch_started_at is not None else now).timestamp()
        )
        if (
            quote.quote_id != str(row.id)
            or quote.source != binding_for(recording)
            or quote.account_id != str(actor.person_id)
            or quote.budget_scope_id != str(row.budget_scope_id)
            or quote.recipe_revision != plan.recipe_revision
            or quote.provider_id != plan.prepared.provider
            or quote.provider_model != plan.prepared.model
            or quote.operation != plan.prepared.operation
            or quote.input_sha256 != plan.prepared.input_sha256
            # Hosted provider work is metered separately from the one source
            # audio charge made by local C1. Offline callers retain their
            # existing quote semantics.
            or (self.authority is not None and quote.entitlement_seconds != 0)
            or (
                self.authority is None
                and plan.checkpoint.stage == "C2"
                and quote.entitlement_seconds != (plan.duration_ms + 999) // 1000
            )
            or permission.quote_fingerprint != quote.fingerprint
            or permission.approved_by != str(actor.person_id)
            or not quote.created_at_epoch
            <= quote_admission_epoch
            < min(quote.expires_at_epoch, permission.expires_at_epoch)
        ):
            raise ConversationDenied("This quote does not authorize this exact provider request.")
        if self.authority is not None:
            await self.authority.validate_quote(
                self.application,
                actor,
                recording,
                plan,
                row,
                quote,
                permission,
                now,
            )
        elif permission.authorization_ref.startswith("hosted-stage-v1:"):
            raise ConversationDenied("Hosted processing requires its current release authority.")
        if require_acceptance:
            accepted = await self.database.scalar(
                select(ConversationQuoteAcceptance)
                .where(
                    ConversationQuoteAcceptance.quote_id == row.id,
                )
                .execution_options(populate_existing=True)
            )
            if accepted is None:
                from ac_platform.conversation_intelligence.processing_plan import (
                    require_stage_authorization,
                )

                await require_stage_authorization(
                    self.application,
                    actor,
                    recording,
                    row,
                    quote,
                    plan,
                    self.authority,
                )
            elif (
                accepted.person_id != actor.person_id
                or accepted.tenant_id != actor.tenant_id
                or not same_actor(accepted, actor)
                or accepted.quote_fingerprint != quote.fingerprint
                or accepted.privacy_revision != quote.privacy_revision
            ):
                raise ConversationDenied(
                    "Approve this exact recording, provider, price and privacy quote."
                )
        return row, quote, permission

    async def accept(
        self,
        actor: ConversationActor,
        recording_id: UUID,
        quote_id: UUID,
        acceptance: QuoteAcceptance,
        *,
        request: StageRequest | None = None,
    ) -> dict[str, str]:
        now = await self.application.admit(actor)
        if self.authority is not None:
            await self.authority.require_execution_enabled(self.application)
        await self.application.get(actor, recording_id)
        recording = await self.application._recording(actor, recording_id)
        plan: ServicePlan = (
            await self.plan_transcription(recording)
            if request is None
            else await ReportingPipeline(self).plan(recording, request)
        )
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
                    **actor_columns(actor),
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
        actor: ConversationActor,
        recording_id: UUID,
        quote_id: UUID,
        *,
        key: str,
    ) -> dict[str, Any]:
        return await self.request_stage(actor, recording_id, quote_id, key=key)

    async def request_stage(
        self,
        actor: ConversationActor,
        recording_id: UUID,
        quote_id: UUID,
        *,
        key: str,
        request: StageRequest | None = None,
    ) -> dict[str, Any]:
        now = await self.application.admit(actor)
        if self.authority is not None:
            await self.authority.require_execution_enabled(self.application)
        await self.application.get(actor, recording_id)
        recording = await self.application._recording(actor, recording_id)
        if recording.state != "ready":
            raise ConversationConflict("The recording is not ready.")
        plan: ServicePlan = (
            await self.plan_transcription(recording)
            if request is None
            else await ReportingPipeline(self).plan(recording, request)
        )
        row, quote, permission = await self._quote(
            actor, recording, quote_id, plan, now, require_acceptance=True
        )
        command = {
            "recording_id": str(recording_id),
            "quote_id": str(quote_id),
            "cache_key": plan.checkpoint.cache_key,
        }
        action = "provider_transcription" if request is None else "provider_analysis"
        replay = await self.application._replay(actor, key, action, command)
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
            if existing.state not in {"queued", "running", "completed"}:
                # A terminal failed/uncertain task may have crossed provider
                # dispatch, or may only be known to have failed before it. In
                # either case the same cache key cannot silently become a new
                # run; an explicit recovery path must establish a safe next
                # generation or leave the request blocked for reconciliation.
                raise ConversationConflict(
                    "The previous stage requires explicit recovery before it can run again."
                )
            # Another click, quote, or coaching profile cannot create a second ASR effect.
            await self.application._receipt(actor, key, action, command, existing.run_id, now)
            return await self.application._run_view(actor, existing.run_id)
        identifier = uuid4()
        minutes, budget = await self.accounts(recording, row)
        try:
            release_cap_paise = (
                self.authority.current(now).budget_cap_paise if self.authority is not None else None
            )
            transition = reserve(
                MinuteAccount.from_dict(minutes.snapshot),
                BudgetAccount.from_dict(budget.snapshot),
                str(identifier),
                quote,
                permission,
                int(now.timestamp()),
                release_cap_paise=release_cap_paise,
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
                request_key=self.application.command_key(actor, key),
                intent_sha256=content_hash(command),
                recipe_revision=plan.recipe_revision,
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
                **actor_columns(actor),
                job_id=job.id,
                quote_id=quote_id,
                generation=recording.generation,
                stage=plan.checkpoint.stage,
                cache_key=plan.checkpoint.cache_key,
                input_sha256=plan.prepared.input_sha256,
                intent_sha256=content_hash(plan.intent()),
                intent=plan.intent(),
                state="queued",
                created_at=now,
            )
        )
        await self.database.flush()
        await self.application._receipt(actor, key, action, command, identifier, now)
        return await self.application._run_view(actor, identifier)
