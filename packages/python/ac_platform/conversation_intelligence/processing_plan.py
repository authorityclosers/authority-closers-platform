"""One explicit bounded consent, followed by durable checkpoint progression.

No provider transport, credentials or paid fallback. A scan can be repeated after
process loss: actual effects are still existing deduplicated, reserved AC jobs.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ac_platform.conversation_intelligence.activation_contract import StageApproval
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationConflict,
    ConversationDenied,
    ConversationError,
    ConversationNotFound,
    utc,
)
from ac_platform.conversation_intelligence.authority import ConversationAuthority
from ac_platform.conversation_intelligence.checkpoints import canonical, content_hash
from ac_platform.conversation_intelligence.entitlements import MinuteAccount, Quote
from ac_platform.conversation_intelligence.inference import (
    TRANSCRIPT_RECIPE,
    ConversationInference,
    ServicePlan,
)
from ac_platform.conversation_intelligence.models import (
    ConversationCommand,
    ConversationInferenceTask,
    ConversationMinuteAccount,
    ConversationPlanStageAuthorization,
    ConversationProcessingPlan,
    ConversationQuote,
    ConversationRecording,
    ConversationReportDraft,
)
from ac_platform.conversation_intelligence.reporting_pipeline import (
    COACHING_RECIPE,
    FACT_RECIPE,
    ReportingPipeline,
    StagePlan,
    StageRequest,
)
from ac_platform.conversation_intelligence.reports import load_report_profile
from ac_platform.kernel.authz import ActorContext
from ac_platform.outbox.repository import RecoveryStateRepository

PLAN_PRIVACY_REVISION: Literal["sales-xray-processing-plan-v1"] = "sales-xray-processing-plan-v1"


class PlanManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_id: Literal["ac.sales-xray.processing-plan/1"]
    recording_id: UUID
    tenant_id: UUID
    person_id: UUID
    session_id: UUID
    generation: int = Field(strict=True, ge=1)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_revision: int = Field(strict=True, ge=1)
    authority_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    transcription_cache_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    duration_ms: int = Field(strict=True, gt=0)
    stages: tuple[StageApproval, StageApproval, StageApproval]
    profile: dict[str, Any] = Field(repr=False)
    max_input_chars: Literal[16000] = 16000
    privacy_revision: Literal["sales-xray-processing-plan-v1"] = PLAN_PRIVACY_REVISION
    created_at_epoch: int = Field(strict=True, gt=0)
    expires_at_epoch: int = Field(strict=True, gt=0)
    max_cost_paise: Literal[0] = 0
    max_entitlement_seconds: int = Field(strict=True, ge=0, le=86400)

    @model_validator(mode="after")
    def bounded(self) -> PlanManifest:
        if tuple(item.stage for item in self.stages) != ("C2", "C4", "C5"):
            raise ValueError("processing_plan_stages_invalid")
        if self.expires_at_epoch <= self.created_at_epoch:
            raise ValueError("processing_plan_window_invalid")
        if any(
            (item.tenant_id, item.person_id, item.source_sha256)
            != (self.tenant_id, self.person_id, self.source_sha256)
            or item.expires_at_epoch < self.expires_at_epoch
            for item in self.stages
        ):
            raise ValueError("processing_plan_scope_invalid")
        c2, c4, c5 = self.stages
        if (
            c2.recipe_revision != TRANSCRIPT_RECIPE
            or c4.recipe_revision != FACT_RECIPE
            or c5.recipe_revision != COACHING_RECIPE
            or c4.max_completion_tokens < 256
            or c5.max_completion_tokens < 256
            or content_hash(self.profile) != c5.profile_sha256
            # The user's minute allowance is for unique call audio. C2/C4/C5
            # provider requests have separate request/token/budget approvals and
            # must not add the same audio duration or text work to that ledger.
            or self.max_entitlement_seconds != 0
        ):
            raise ValueError("processing_plan_bounds_invalid")
        return self

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class PlanAcceptance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    plan_id: UUID
    plan_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    privacy_revision: Literal["sales-xray-processing-plan-v1"]
    accepted: Literal[True]

    @field_validator("accepted", mode="before")
    @classmethod
    def explicit_acceptance(cls, value: Any) -> bool:
        if value is not True:
            raise ValueError("Explicit acceptance is required.")
        return True


def manifest_for(row: ConversationProcessingPlan) -> PlanManifest:
    try:
        if row.erased_at is not None or row.manifest is None:
            raise ValueError
        value = PlanManifest.model_validate_json(canonical(row.manifest))
        if (
            content_hash(value.as_dict()) != row.plan_sha256
            or (
                value.recording_id,
                value.tenant_id,
                value.person_id,
                value.session_id,
                value.generation,
            )
            != (row.recording_id, row.tenant_id, row.person_id, row.session_id, row.generation)
            or value.expires_at_epoch != int(utc(row.expires_at).timestamp())
        ):
            raise ValueError
        return value
    except (ValueError, TypeError, KeyError):
        raise ConversationDenied("The saved processing plan is unavailable.") from None


def acceptance_intent(row: ConversationProcessingPlan) -> dict[str, Any]:
    return {
        "plan_id": str(row.id),
        "plan_fingerprint": row.plan_sha256,
        "privacy_revision": PLAN_PRIVACY_REVISION,
        "session_id": str(row.session_id),
        "accepted": True,
    }


async def require_plan_consent(
    app: ConversationApplication,
    actor: ActorContext,
    row: ConversationProcessingPlan,
    authority: ConversationAuthority,
) -> PlanManifest:
    now = await app.admit(actor)
    await app.get(actor, row.recording_id)
    recording = await app._recording(actor, row.recording_id)
    value = manifest_for(row)
    bundle = await authority.admit(app, actor)
    command = (
        await app.database.get(ConversationCommand, row.acceptance_command_id)
        if row.acceptance_command_id is not None
        else None
    )
    if (
        row.state not in {"active", "completed"}
        or (row.tenant_id, row.person_id, row.session_id)
        != (actor.tenant_id, actor.person_id, actor.session_id)
        or row.generation != recording.generation
        or value.source_sha256 != recording.source_sha256
        or value.source_revision != recording.source_revision
        or not value.created_at_epoch <= int(now.timestamp()) < value.expires_at_epoch
        or bundle.digest != value.authority_sha256
        or command is None
        or command.action != "processing_plan_accepted"
        or (command.tenant_id, command.person_id, command.result_id)
        != (row.tenant_id, row.person_id, row.id)
        or command.intent_sha256 != content_hash(acceptance_intent(row))
    ):
        raise ConversationDenied("This processing plan needs current owner approval.")
    return value


def require_derived_input(value: PlanManifest, plan: ServicePlan) -> None:
    if plan.checkpoint.stage == "C2":
        if plan.checkpoint.cache_key != value.transcription_cache_key:
            raise ConversationDenied("Transcription differs from the approved processing plan.")
        return
    if not isinstance(plan, StagePlan):
        raise ConversationDenied("The derived stage is unavailable.")
    approval = next(item for item in value.stages if item.stage == plan.checkpoint.stage)
    if (
        plan.request.model != approval.model_id
        or plan.request.max_input_chars != value.max_input_chars
        or plan.request.max_completion_tokens != min(1400, approval.max_completion_tokens)
        or (plan.checkpoint.stage == "C4" and plan.request.chunk_index > approval.max_requests)
        or (
            plan.checkpoint.stage == "C5"
            and content_hash(plan.profile) != content_hash(value.profile)
        )
    ):
        raise ConversationDenied("The derived request exceeds the accepted processing plan.")


async def require_stage_authorization(
    app: ConversationApplication,
    actor: ActorContext,
    recording: ConversationRecording,
    quoted: ConversationQuote,
    quote: Quote,
    stage: ServicePlan,
    authority: ConversationAuthority | None,
) -> None:
    if authority is None:
        raise ConversationDenied("Approve this exact recording, provider, price and privacy quote.")
    link = await app.database.get(ConversationPlanStageAuthorization, quoted.id)
    row = None if link is None else await app.database.get(ConversationProcessingPlan, link.plan_id)
    if (
        link is None
        or row is None
        or row.recording_id != recording.id
        or (link.tenant_id, link.person_id) != (actor.tenant_id, actor.person_id)
        or link.quote_fingerprint != quote.fingerprint
        or link.cache_key != stage.checkpoint.cache_key
    ):
        raise ConversationDenied("Approve this exact quote or its bounded processing plan.")
    value = await require_plan_consent(app, actor, row, authority)
    require_derived_input(value, stage)


class ConversationProcessingPlans:
    def __init__(self, app: ConversationApplication, authority: ConversationAuthority) -> None:
        self.app, self.db, self.authority = app, app.database, authority
        self.inference = ConversationInference(app, authority=authority)

    async def _row(
        self, actor: ActorContext, recording_id: UUID, identifier: UUID | None = None
    ) -> ConversationProcessingPlan:
        await self.app.get(actor, recording_id)
        query = select(ConversationProcessingPlan).where(
            ConversationProcessingPlan.recording_id == recording_id,
            ConversationProcessingPlan.tenant_id == actor.tenant_id,
            ConversationProcessingPlan.person_id == actor.person_id,
            ConversationProcessingPlan.erased_at.is_(None),
        )
        if identifier is not None:
            query = query.where(ConversationProcessingPlan.id == identifier)
        row = await self.db.scalar(
            query.order_by(ConversationProcessingPlan.created_at.desc()).limit(1).with_for_update()
        )
        if row is None:
            raise ConversationNotFound("No processing plan has been prepared for this call.")
        return row

    @staticmethod
    def view(row: ConversationProcessingPlan) -> dict[str, Any]:
        value = manifest_for(row)
        return {
            "id": str(row.id),
            "recording_id": str(row.recording_id),
            "plan_fingerprint": row.plan_sha256,
            "privacy_revision": PLAN_PRIVACY_REVISION,
            "accepted": row.acceptance_command_id is not None,
            "state": row.state,
            "automatic_progression": True,
            "cost_label": "₹0 · approved allowance",
            "max_cost_paise": 0,
            "max_entitlement_seconds": value.max_entitlement_seconds,
            "expires_at_epoch": value.expires_at_epoch,
            "stages": [
                {
                    "stage": item.stage,
                    "provider": item.provider_id,
                    "model": item.model_id,
                    "max_requests": item.max_requests if item.stage == "C4" else 1,
                    "privacy_revision": item.privacy_revision,
                    "privacy_notice": item.privacy_notice,
                }
                for item in value.stages
            ],
            "current_stage": row.progress.get("current_stage"),
            "report_ready": row.state == "completed" and bool(row.progress.get("report_run_id")),
            "report_run_id": row.progress.get("report_run_id"),
            "failure_code": row.progress.get("failure_code"),
        }

    async def get(self, actor: ActorContext, recording_id: UUID) -> dict[str, Any]:
        return self.view(await self._row(actor, recording_id))

    async def quote(self, actor: ActorContext, recording_id: UUID, *, key: str) -> dict[str, Any]:
        now = await self.app.admit(actor)
        await self.app.get(actor, recording_id)
        recording = await self.app._recording(actor, recording_id)
        source = await self.inference.plan_transcription(recording)
        bundle, c2 = await self.authority.approval(self.app, actor, recording, source, now)
        command = {
            "recording_id": str(recording_id),
            "session_id": str(actor.session_id),
            "authority_sha256": bundle.digest,
        }
        replay = await self.app._replay(actor, key, "processing_plan_quote", command)
        if replay is not None and replay.result_id is not None:
            return self.view(await self._row(actor, recording_id, replay.result_id))
        active = await self.db.scalar(
            select(ConversationProcessingPlan).where(
                ConversationProcessingPlan.recording_id == recording_id,
                ConversationProcessingPlan.state == "active",
            )
        )
        if active is not None:
            return self.view(active)
        approvals: dict[str, StageApproval] = {
            item.stage: item
            for item in bundle.stages
            if (item.tenant_id, item.person_id, item.source_sha256)
            == (actor.tenant_id, actor.person_id, recording.source_sha256)
        }
        if set(approvals) != {"C2", "C4", "C5"}:
            raise ConversationDenied(
                "This call needs an approved transcription, facts and coaching route."
            )
        profile = load_report_profile()
        for stage, task, recipe in (
            ("C4", "facts", FACT_RECIPE),
            ("C5", "coaching", COACHING_RECIPE),
        ):
            item = approvals[stage]
            if (
                item.provider_id != "groq"
                or item.max_completion_tokens < 256
                or source.duration_ms > item.max_source_duration_ms
            ):
                raise ConversationDenied("The approved route is not implemented for this plan.")
            await self.authority.validate_route(
                self.app,
                actor,
                item,
                bundle=bundle,
                task=task,
                provider="groq",
                model=item.model_id,
                recipe=recipe,
                profile_revision=str(profile["revision"]) if stage == "C5" else None,
            )
        c4, c5 = approvals["C4"], approvals["C5"]
        # C1 has already charged the measured source audio. The remaining
        # provider plan needs zero additional user minutes, even when the last
        # authorized call consumed the account's entire allowance.
        maximum_seconds = 0
        minutes = await self.db.get(
            ConversationMinuteAccount, (recording.tenant_id, recording.person_id)
        )
        if (
            minutes is None
            or MinuteAccount.from_dict(minutes.snapshot).available_seconds < maximum_seconds
        ):
            raise ConversationConflict(
                "The approved allowance cannot cover this bounded processing plan."
            )
        try:
            value = PlanManifest(
                schema_id="ac.sales-xray.processing-plan/1",
                recording_id=recording_id,
                tenant_id=recording.tenant_id,
                person_id=recording.person_id,
                session_id=actor.session_id,
                generation=recording.generation,
                source_sha256=recording.source_sha256,
                source_revision=recording.source_revision,
                authority_sha256=bundle.digest,
                transcription_cache_key=source.checkpoint.cache_key,
                duration_ms=source.duration_ms,
                stages=(c2, c4, c5),
                profile=profile,
                created_at_epoch=int(now.timestamp()),
                expires_at_epoch=min(
                    int(now.timestamp()) + 3600,
                    bundle.expires_at_epoch,
                    *(item.expires_at_epoch for item in approvals.values()),
                ),
                max_entitlement_seconds=maximum_seconds,
            )
        except ValueError:
            raise ConversationDenied("The complete processing plan is not approved.") from None
        row = ConversationProcessingPlan(
            id=uuid4(),
            tenant_id=recording.tenant_id,
            person_id=recording.person_id,
            recording_id=recording_id,
            session_id=actor.session_id,
            generation=recording.generation,
            plan_sha256=content_hash(value.as_dict()),
            manifest=value.as_dict(),
            state="quoted",
            progress={},
            created_at=now,
            expires_at=datetime.fromtimestamp(value.expires_at_epoch, UTC),
            next_check_at=now,
        )
        self.db.add(row)
        await self.db.flush()
        await self.app._receipt(actor, key, "processing_plan_quote", command, row.id, now)
        return self.view(row)

    async def accept(
        self, actor: ActorContext, recording_id: UUID, payload: PlanAcceptance, *, key: str
    ) -> dict[str, Any]:
        now = await self.app.admit(actor)
        row = await self._row(actor, recording_id, payload.plan_id)
        value = manifest_for(row)
        bundle = await self.authority.admit(self.app, actor)
        if (
            payload.accepted is not True
            or payload.plan_fingerprint != row.plan_sha256
            or actor.session_id != row.session_id
            or bundle.digest != value.authority_sha256
            or int(now.timestamp()) >= value.expires_at_epoch
            or row.state not in {"quoted", "active", "completed"}
        ):
            raise ConversationDenied("Approve the current displayed processing plan.")
        other = await self.db.scalar(
            select(ConversationProcessingPlan.id).where(
                ConversationProcessingPlan.recording_id == recording_id,
                ConversationProcessingPlan.state == "active",
                ConversationProcessingPlan.id != row.id,
            )
        )
        if other is not None:
            raise ConversationConflict("This call already has an active processing plan.")
        intent = acceptance_intent(row)
        await self.app._replay(actor, key, "processing_plan_accepted", intent)
        if row.acceptance_command_id is None:
            # The append-only command is the actual owner click. Derived quotes
            # link to it; no per-stage ConversationQuoteAcceptance is invented.
            await self.app._receipt(actor, key, "processing_plan_accepted", intent, row.id, now)
            receipt = await self.app._replay(actor, key, "processing_plan_accepted", intent)
            assert receipt is not None
            row.acceptance_command_id, row.state = receipt.id, "active"
            await self.db.flush()
        # A second click reuses the one original acceptance command. Its new
        # request key cannot manufacture another consent event or reservation.
        if row.state == "active":
            await self.advance(actor, row)
        return self.view(row)

    async def _enqueue(
        self,
        actor: ActorContext,
        row: ConversationProcessingPlan,
        value: PlanManifest,
        request: StageRequest | None,
    ) -> ConversationInferenceTask:
        recording = await self.app._recording(actor, row.recording_id)
        stage = (
            await self.inference.plan_transcription(recording)
            if request is None
            else await ReportingPipeline(self.inference).plan(recording, request)
        )
        require_derived_input(value, stage)
        await self.authority.approval(self.app, actor, recording, stage, utc(self.app.clock()))
        existing = await self.db.scalar(
            select(ConversationInferenceTask).where(
                ConversationInferenceTask.recording_id == row.recording_id,
                ConversationInferenceTask.cache_key == stage.checkpoint.cache_key,
            )
        )
        if existing is not None:
            if existing.erased_at is not None or existing.generation != row.generation:
                raise ConversationConflict("The saved stage is no longer reusable.")
            if existing.state == "completed":
                if existing.checkpoint_id is None:
                    raise ConversationConflict("The saved stage checkpoint is unavailable.")
                pipeline = ReportingPipeline(self.inference)
                checkpoint, _ = await pipeline.checkpoint(
                    recording, existing.checkpoint_id, existing.stage
                )
                await pipeline.provider_task(recording, checkpoint)
            return existing
        key = f"plan:{row.id}:{stage.checkpoint.cache_key}"
        quote_view = await self.authority.issue(
            self.app, actor, row.recording_id, key=key, request=request
        )
        quote_id = UUID(quote_view["id"])
        link = await self.db.get(ConversationPlanStageAuthorization, quote_id)
        if link is None:
            self.db.add(
                ConversationPlanStageAuthorization(
                    quote_id=quote_id,
                    plan_id=row.id,
                    tenant_id=row.tenant_id,
                    person_id=row.person_id,
                    quote_fingerprint=quote_view["quote_fingerprint"],
                    cache_key=stage.checkpoint.cache_key,
                    created_at=utc(self.app.clock()),
                )
            )
            await self.db.flush()
        run = await self.inference.request_stage(
            actor,
            row.recording_id,
            quote_id,
            key=f"run:{row.id}:{stage.checkpoint.cache_key}",
            request=request,
        )
        task = await self.db.get(ConversationInferenceTask, UUID(run["id"]))
        assert task is not None
        return task

    async def advance(self, actor: ActorContext, row: ConversationProcessingPlan) -> None:
        value = await require_plan_consent(self.app, actor, row, self.authority)
        if row.state != "active":
            return
        # Inspect the exact canonical task each time. A crash between polling
        # and enqueue cannot duplicate its immutable cache key or reservation.
        c2 = await self._enqueue(actor, row, value, None)
        tasks = [c2]
        current = "C2"
        if c2.state == "completed" and c2.checkpoint_id is not None:
            c4 = value.stages[1]
            first_request = StageRequest(
                stage="C4",
                transcript_checkpoint_id=c2.checkpoint_id,
                model=c4.model_id,
                max_input_chars=value.max_input_chars,
                max_completion_tokens=min(1400, c4.max_completion_tokens),
            )
            recording = await self.app._recording(actor, row.recording_id)
            first_plan = await ReportingPipeline(self.inference).plan(recording, first_request)
            count = first_plan.prepared.chunk_count
            if count is None or count > c4.max_requests:
                raise ConversationDenied(
                    "The transcript exceeds the accepted fact-processing allowance."
                )
            current = "C4"
            facts = []
            for index in range(1, count + 1):
                task = await self._enqueue(
                    actor, row, value, first_request.model_copy(update={"chunk_index": index})
                )
                tasks.append(task)
                if task.state != "completed" or task.checkpoint_id is None:
                    break
                facts.append(task.checkpoint_id)
            if len(facts) == count:
                c5 = value.stages[2]
                current = "C5"
                judge = await self._enqueue(
                    actor,
                    row,
                    value,
                    StageRequest(
                        stage="C5",
                        transcript_checkpoint_id=c2.checkpoint_id,
                        fact_checkpoint_ids=tuple(facts),
                        model=c5.model_id,
                        max_input_chars=value.max_input_chars,
                        max_completion_tokens=min(1400, c5.max_completion_tokens),
                        profile=value.profile,
                    ),
                )
                tasks.append(judge)
                if judge.state == "completed":
                    report = await self.db.scalar(
                        select(ConversationReportDraft).where(
                            ConversationReportDraft.run_id == judge.run_id,
                            ConversationReportDraft.recording_id == row.recording_id,
                            ConversationReportDraft.erased_at.is_(None),
                        )
                    )
                    if report is None:
                        raise ConversationConflict("The completed coaching report is unavailable.")
                    row.state = "completed"
                    row.progress = {"current_stage": "C6", "report_run_id": str(judge.run_id)}
                    return
        bad = next(
            (item for item in tasks if item.state in {"failed", "uncertain", "cancelled"}), None
        )
        if bad is not None:
            row.state = "held"
            row.progress = {"current_stage": bad.stage, "failure_code": f"stage_{bad.state}"}
        else:
            row.progress = {"current_stage": current}
        row.next_check_at = utc(self.app.clock()) + timedelta(seconds=2)


class ProcessingPlanScheduler:
    """Bounded database-driven coordinator; no browser or provider credentials."""

    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], authority: ConversationAuthority
    ) -> None:
        self.sessions, self.authority = sessions, authority

    async def step(self) -> bool:
        async with self.sessions() as db, db.begin():
            await RecoveryStateRepository(db).require_ready(lock=True, shared_lock=True)
            candidate = await db.scalar(
                select(ConversationProcessingPlan)
                .where(
                    ConversationProcessingPlan.state == "active",
                    ConversationProcessingPlan.next_check_at <= datetime.now(UTC),
                    ConversationProcessingPlan.erased_at.is_(None),
                )
                .order_by(ConversationProcessingPlan.next_check_at)
                .limit(1)
            )
            if candidate is None:
                return False
            identifier, recording_id = candidate.id, candidate.recording_id
            actor = ActorContext(candidate.person_id, candidate.session_id, candidate.tenant_id)
            try:
                async with db.begin_nested():
                    app = ConversationApplication(db)
                    await app.admit(actor)
                    await app.get(actor, recording_id)
                    row = await db.scalar(
                        select(ConversationProcessingPlan)
                        .where(
                            ConversationProcessingPlan.id == identifier,
                        )
                        .with_for_update(skip_locked=True)
                        .execution_options(populate_existing=True)
                    )
                    if row is None or row.state != "active":
                        return False
                    await ConversationProcessingPlans(app, self.authority).advance(actor, row)
            except ConversationError:
                # Roll back partial enqueue/quote work, retain the accepted
                # intent and a content-free hold. Never retry an uncertain call.
                row = await db.get(
                    ConversationProcessingPlan,
                    identifier,
                    with_for_update=True,
                    populate_existing=True,
                )
                if row is not None and row.state == "active":
                    row.state = "held"
                    row.progress = {"failure_code": "processing_authorization_or_input_unavailable"}
            return True
