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
from ac_platform.conversation_intelligence.analysis_settings import latest_analysis_settings
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
from ac_platform.conversation_intelligence.contracts import (
    C5_REPAIR_FAILURE_CODES,
    C5RepairIntent,
)
from ac_platform.conversation_intelligence.entitlements import (
    BudgetAccount,
    MinuteAccount,
    Quote,
    effective_budget_cap_paise,
)
from ac_platform.conversation_intelligence.inference import (
    TRANSCRIPT_RECIPE_BY_ROUTE,
    TRANSCRIPT_RECIPES,
    ConversationInference,
    ServicePlan,
    TranscriptionPlan,
)
from ac_platform.conversation_intelligence.inference_tasks import InferenceTaskError
from ac_platform.conversation_intelligence.models import (
    ConversationBudgetAccount,
    ConversationCommand,
    ConversationInferenceTask,
    ConversationMinuteAccount,
    ConversationPlanStageAuthorization,
    ConversationProcessingPlan,
    ConversationQuote,
    ConversationRecording,
    ConversationReportDraft,
)
from ac_platform.conversation_intelligence.processing_actor import (
    ConversationActor,
    ProcessingActor,
    actor_binding,
    actor_columns,
    actor_from_row,
    same_actor,
)
from ac_platform.conversation_intelligence.qualitative_pack import (
    ReportLanguage,
    load_qualitative_pack_for_revision,
)
from ac_platform.conversation_intelligence.reporting_pipeline import (
    COACHING_RECIPE,
    FACT_RECIPE,
    ReportingPipeline,
    StagePlan,
    StageRequest,
)
from ac_platform.conversation_intelligence.reports import (
    COACHING_PROMPT_LEGACY,
    COACHING_PROMPT_V3,
    COACHING_PROMPT_V4,
    COACHING_PROMPT_V5,
    FACT_PROMPT_COMPACT,
    FACT_PROMPT_LEGACY,
    load_report_profile,
)
from ac_platform.conversation_intelligence.storage import PrivateLocalRecordingStorage
from ac_platform.outbox.models import Job
from ac_platform.outbox.repository import RecoveryStateRepository

PLAN_PRIVACY_REVISION: Literal["sales-xray-processing-plan-v1"] = "sales-xray-processing-plan-v1"
C5_AUTO_REPAIR_ATTEMPTS = 1
NEW_PLAN_COACHING_PROMPT_REVISION: Literal["coaching-v3"] = COACHING_PROMPT_V3


def planned_c5_requests(stage: StageApproval) -> int:
    """Reserve one bounded C5 repair only when the pinned approval permits it."""

    return 1 + min(C5_AUTO_REPAIR_ATTEMPTS, max(0, stage.max_requests - 1))


def automatic_c5_repair_cost(stage: StageApproval) -> int:
    return stage.max_cost_paise if planned_c5_requests(stage) > 1 else 0


def maximum_plan_cost(stages: tuple[StageApproval, StageApproval, StageApproval]) -> int:
    """Base upper bound: one ASR, each fact chunk and one C5 judge request."""
    c2, c4, c5 = stages
    return c2.max_cost_paise + c4.max_cost_paise * c4.max_requests + c5.max_cost_paise


def maximum_plan_cost_with_repair(
    stages: tuple[StageApproval, StageApproval, StageApproval],
) -> int:
    return maximum_plan_cost(stages) + automatic_c5_repair_cost(stages[2])


def c5_repair_intent(task: ConversationInferenceTask, job: Job) -> C5RepairIntent | None:
    """Return a repair intent only for a persisted, returned C5 validation failure."""

    if task.stage != "C5" or task.state != "uncertain":
        return None
    request = task.intent.get("request") if isinstance(task.intent, dict) else None
    if not isinstance(request, dict) or request.get("repair") is not None:
        return None
    receipt = job.provider_receipt
    if (
        job.kind != "conversation.infer_provider.v1"
        or job.dispatch_started_at is None
        or job.provider_idempotency_key != job.dedupe_key
        or not isinstance(receipt, dict)
        or receipt.get("schema") != "ac.sales-xray.provider-receipt/1"
        or receipt.get("validation_state") != "provider_returned"
        or receipt.get("idempotency_key") != job.provider_idempotency_key
        or receipt.get("raw_blob_id") != str(task.run_id)
        or not isinstance(job.last_error, str)
        or job.last_error not in C5_REPAIR_FAILURE_CODES
    ):
        return None
    try:
        return C5RepairIntent(
            failure_code=job.last_error,
            original_run_id=task.run_id,
            original_response_sha256=receipt.get("response_sha256"),
        )
    except (TypeError, ValueError):
        return None


def plan_cost_label(maximum: int) -> str:
    if maximum == 0:
        return "₹0 · approved allowance"
    return f"Up to ₹{maximum // 100}.{maximum % 100:02d} · approved budget"


class PlanManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_id: Literal["ac.sales-xray.processing-plan/1"]
    recording_id: UUID
    tenant_id: UUID
    person_id: UUID
    session_id: UUID | None
    processing_lease_id: UUID | None = None
    continuation_grant_id: UUID | None = None
    generation: int = Field(strict=True, ge=1)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_revision: int = Field(strict=True, ge=1)
    authority_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    transcription_cache_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    duration_ms: int = Field(strict=True, gt=0)
    stages: tuple[StageApproval, StageApproval, StageApproval]
    profile: dict[str, Any] = Field(repr=False)
    max_input_chars: Literal[16000] = 16000
    fact_prompt_revision: Literal["facts-v1", "facts-v2"] = FACT_PROMPT_LEGACY
    coaching_prompt_revision: Literal[
        "coaching-v1", "coaching-v2", "coaching-v3", "coaching-v4", "coaching-v5"
    ] = COACHING_PROMPT_LEGACY
    report_language: ReportLanguage | None = None
    qualitative_pack_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    privacy_revision: Literal["sales-xray-processing-plan-v1"] = PLAN_PRIVACY_REVISION
    created_at_epoch: int = Field(strict=True, gt=0)
    expires_at_epoch: int = Field(strict=True, gt=0)
    max_cost_paise: int = Field(default=0, strict=True, ge=0, le=2_147_483_647)
    automatic_c5_repair_cost_paise: int | None = Field(
        default=None, strict=True, ge=0, le=2_147_483_647
    )
    max_entitlement_seconds: int = Field(strict=True, ge=0, le=86400)
    analysis_settings_revision: int | None = Field(default=None, strict=True, ge=1)
    output_profile: Literal["standard", "detailed"] = "detailed"

    @model_validator(mode="after")
    def bounded(self) -> PlanManifest:
        if (self.session_id is None) == (self.processing_lease_id is None):
            raise ValueError("processing_plan_actor_invalid")
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
        repair_cost = self.automatic_c5_repair_cost_paise or 0
        if (
            (c2.provider_id, c2.model_id) not in TRANSCRIPT_RECIPE_BY_ROUTE
            or c2.recipe_revision != TRANSCRIPT_RECIPE_BY_ROUTE[(c2.provider_id, c2.model_id)]
            or c2.recipe_revision not in TRANSCRIPT_RECIPES
            or c4.recipe_revision != FACT_RECIPE
            or c5.recipe_revision != COACHING_RECIPE
            or c4.max_completion_tokens < 256
            or c5.max_completion_tokens < 256
            or content_hash(self.profile) != c5.profile_sha256
            # The user's minute allowance is for unique call audio. C2/C4/C5
            # provider requests have separate request/token/budget approvals and
            # must not add the same audio duration or text work to that ledger.
            or self.max_entitlement_seconds != 0
            or (
                self.automatic_c5_repair_cost_paise is not None
                and (planned_c5_requests(c5) <= 1 or repair_cost != automatic_c5_repair_cost(c5))
            )
            or self.max_cost_paise != maximum_plan_cost(self.stages) + repair_cost
        ):
            raise ValueError("processing_plan_bounds_invalid")
        if self.coaching_prompt_revision in {COACHING_PROMPT_V4, COACHING_PROMPT_V5}:
            if (
                self.report_language is None
                or self.qualitative_pack_sha256
                != load_qualitative_pack_for_revision(self.coaching_prompt_revision).sha256
            ):
                raise ValueError("processing_plan_coaching_options_invalid")
        elif self.report_language not in {None, "en"} or self.qualitative_pack_sha256 is not None:
            raise ValueError("processing_plan_coaching_options_invalid")
        return self

    def as_dict(self) -> dict[str, Any]:
        value = self.model_dump(mode="json")
        if self.processing_lease_id is None:
            value.pop("processing_lease_id", None)
        if self.continuation_grant_id is None:
            value.pop("continuation_grant_id", None)
        if self.analysis_settings_revision is None:
            value.pop("analysis_settings_revision", None)
        if self.automatic_c5_repair_cost_paise is None:
            value.pop("automatic_c5_repair_cost_paise", None)
        if self.output_profile == "detailed":
            value.pop("output_profile", None)
        if self.fact_prompt_revision == FACT_PROMPT_LEGACY:
            value.pop("fact_prompt_revision", None)
        if self.coaching_prompt_revision == COACHING_PROMPT_LEGACY:
            value.pop("coaching_prompt_revision", None)
        if self.report_language is None:
            value.pop("report_language", None)
        if self.qualitative_pack_sha256 is None:
            value.pop("qualitative_pack_sha256", None)
        return value


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


class PlanLanguagePreference(BaseModel):
    """One optional caller preference; it cannot select an engine or pack."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    report_language: ReportLanguage


def parse_report_language_preference(raw: bytes) -> ReportLanguage | None:
    """Parse the bounded, exact optional language body used by quote routes."""

    if not raw:
        return None
    try:
        return PlanLanguagePreference.model_validate_json(raw).report_language
    except ValueError:
        raise ValueError("The report language preference is invalid.") from None


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
                value.processing_lease_id,
                value.generation,
            )
            != (
                row.recording_id,
                row.tenant_id,
                row.person_id,
                row.session_id,
                row.processing_lease_id,
                row.generation,
            )
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
        **actor_binding(actor_from_row(row)),
        "accepted": True,
    }


async def require_plan_consent(
    app: ConversationApplication,
    actor: ConversationActor,
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
        or not same_actor(row, actor)
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
    await validate_continuation_grant(app, actor, recording, value, now)
    return value


async def validate_continuation_grant(
    app: ConversationApplication,
    actor: ConversationActor,
    recording: ConversationRecording,
    value: PlanManifest,
    now: datetime,
) -> None:
    """Verify a fresh-plan manifest remains bound to its owner grant."""
    if value.continuation_grant_id is None:
        return
    if not isinstance(actor, ProcessingActor) or actor.processing_lease_id is None:
        raise ConversationDenied("This continuation plan requires its processing lease.")
    from ac_platform.conversation_intelligence.acquisition_models import (
        ConversationAcquisitionUsage,
        ConversationVisitorClaim,
    )
    from ac_platform.conversation_intelligence.guest_models import (
        ConversationGuestSubmission,
        ConversationProcessingContinuation,
    )

    grant = await app.database.get(ConversationProcessingContinuation, value.continuation_grant_id)
    usage = (
        None
        if grant is None
        else await app.database.get(ConversationAcquisitionUsage, grant.usage_id)
    )
    link = (
        None
        if grant is None
        else await app.database.get(
            ConversationGuestSubmission, (grant.tenant_id, grant.submission_id)
        )
    )
    claim = (
        None
        if usage is None or usage.visitor_id is None
        else await app.database.get(ConversationVisitorClaim, usage.visitor_id)
    )
    expected_owner_person_id = (
        usage.person_id
        if usage is not None and usage.visitor_id is None
        else claim.person_id
        if claim is not None
        else None
    )
    expected_owner_visitor_id = (
        usage.visitor_id
        if usage is not None and usage.visitor_id is not None and claim is None
        else None
    )
    if (
        grant is None
        or utc(grant.expires_at) <= now
        or grant.tenant_id != actor.tenant_id
        or grant.person_id != actor.person_id
        or grant.processing_lease_id != actor.processing_lease_id
        or grant.recording_id != recording.id
        or usage is None
        or usage.tenant_id != actor.tenant_id
        or usage.source_sha256 != recording.source_sha256
        or link is None
        or link.tenant_id != actor.tenant_id
        or link.person_id != actor.person_id
        or link.recording_id != recording.id
        or link.processing_lease_id != actor.processing_lease_id
        or link.usage_id != usage.id
        or link.source_sha256 != recording.source_sha256
        or grant.owner_person_id != expected_owner_person_id
        or grant.owner_visitor_id != expected_owner_visitor_id
        or grant.source_sha256 != recording.source_sha256
        or grant.source_revision != recording.source_revision
        or grant.generation != recording.generation
        or value.expires_at_epoch > int(utc(grant.expires_at).timestamp())
    ):
        raise ConversationDenied("This continuation plan is no longer authorized.")


def require_derived_input(value: PlanManifest, plan: ServicePlan) -> None:
    from ac_platform.conversation_intelligence.report_overview import stage_completion_limit

    if plan.checkpoint.stage == "C2":
        if plan.checkpoint.cache_key != value.transcription_cache_key:
            raise ConversationDenied("Transcription differs from the approved processing plan.")
        return
    if not isinstance(plan, StagePlan):
        raise ConversationDenied("The derived stage is unavailable.")
    approval = next(item for item in value.stages if item.stage == plan.checkpoint.stage)
    if (
        plan.request.provider != approval.provider_id
        or plan.request.model != approval.model_id
        or plan.request.max_input_chars != value.max_input_chars
        or plan.request.max_completion_tokens
        != stage_completion_limit(
            plan.checkpoint.stage,
            approval.max_completion_tokens,
            provider=approval.provider_id,
            model=approval.model_id,
        )
        or (plan.checkpoint.stage == "C4" and plan.request.chunk_index > approval.max_requests)
        or (
            plan.checkpoint.stage == "C4"
            and plan.request.fact_prompt_revision != value.fact_prompt_revision
        )
        or (
            plan.checkpoint.stage == "C5"
            and content_hash(plan.profile) != content_hash(value.profile)
        )
        or (
            plan.checkpoint.stage == "C5"
            and plan.request.coaching_prompt_revision != value.coaching_prompt_revision
        )
        or (plan.checkpoint.stage == "C5" and plan.request.report_language != value.report_language)
        or (
            plan.checkpoint.stage == "C5"
            and plan.request.qualitative_pack_sha256 != value.qualitative_pack_sha256
        )
        or (plan.checkpoint.stage == "C5" and plan.request.output_profile != value.output_profile)
    ):
        raise ConversationDenied("The derived request exceeds the accepted processing plan.")


async def require_stage_authorization(
    app: ConversationApplication,
    actor: ConversationActor,
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
    def __init__(
        self,
        app: ConversationApplication,
        authority: ConversationAuthority,
        storage: PrivateLocalRecordingStorage | None = None,
    ) -> None:
        self.app, self.db, self.authority, self.storage = app, app.database, authority, storage
        self.inference = ConversationInference(app, authority=authority)

    async def _row(
        self, actor: ConversationActor, recording_id: UUID, identifier: UUID | None = None
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

    async def _automatic_c5_repair(
        self, value: PlanManifest, task: ConversationInferenceTask
    ) -> C5RepairIntent | None:
        """Authorize one repair from the accepted plan's explicit retry budget."""

        if (
            value.automatic_c5_repair_cost_paise is None
            or value.automatic_c5_repair_cost_paise != automatic_c5_repair_cost(value.stages[2])
            or planned_c5_requests(value.stages[2]) <= 1
        ):
            return None
        job = await self.db.get(Job, task.job_id)
        return None if job is None else c5_repair_intent(task, job)

    @staticmethod
    def view(
        row: ConversationProcessingPlan, *, include_report_options: bool = False
    ) -> dict[str, Any]:
        value = manifest_for(row)
        result = {
            "id": str(row.id),
            "recording_id": str(row.recording_id),
            "plan_fingerprint": row.plan_sha256,
            "privacy_revision": PLAN_PRIVACY_REVISION,
            "accepted": row.acceptance_command_id is not None,
            "state": row.state,
            "automatic_progression": True,
            "cost_label": plan_cost_label(value.max_cost_paise),
            "max_cost_paise": value.max_cost_paise,
            "automatic_c5_repair_cost_paise": value.automatic_c5_repair_cost_paise or 0,
            "max_entitlement_seconds": value.max_entitlement_seconds,
            "expires_at_epoch": value.expires_at_epoch,
            "stages": [
                {
                    "stage": item.stage,
                    "provider": item.provider_id,
                    "model": item.model_id,
                    "max_requests": (
                        item.max_requests
                        if item.stage == "C4"
                        else planned_c5_requests(item)
                        if item.stage == "C5"
                        else 1
                    ),
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
        if include_report_options:
            result["report_language"] = value.report_language or "en"
            result["coaching_prompt_revision"] = value.coaching_prompt_revision
        return result

    @staticmethod
    async def latest_submission_view(
        database: AsyncSession,
        *,
        tenant_id: UUID,
        person_id: UUID,
        recording_id: UUID,
        processing_lease_id: UUID,
    ) -> dict[str, Any]:
        """Read the latest retained plan for an owner-verified submission."""

        row = await database.scalar(
            select(ConversationProcessingPlan)
            .where(
                ConversationProcessingPlan.recording_id == recording_id,
                ConversationProcessingPlan.tenant_id == tenant_id,
                ConversationProcessingPlan.person_id == person_id,
                ConversationProcessingPlan.processing_lease_id == processing_lease_id,
                ConversationProcessingPlan.erased_at.is_(None),
            )
            .order_by(ConversationProcessingPlan.created_at.desc())
            .limit(1)
        )
        if row is None:
            raise ConversationNotFound("No processing plan has been prepared for this call.")
        return ConversationProcessingPlans.view(row, include_report_options=True)

    async def get(self, actor: ConversationActor, recording_id: UUID) -> dict[str, Any]:
        return self.view(await self._row(actor, recording_id))

    async def quote(
        self,
        actor: ConversationActor,
        recording_id: UUID,
        *,
        key: str,
        continuation_grant_id: UUID | None = None,
        report_language: ReportLanguage | None = None,
    ) -> dict[str, Any]:
        now = await self.app.admit(actor)
        await self.app.get(actor, recording_id)
        recording = await self.app._recording(actor, recording_id)
        continuation_expires_at: datetime | None = None
        if continuation_grant_id is not None:
            from ac_platform.conversation_intelligence.guest_models import (
                ConversationProcessingContinuation,
            )

            grant = await self.db.get(ConversationProcessingContinuation, continuation_grant_id)
            if grant is None:
                raise ConversationDenied("This continuation grant is unavailable.")
            continuation_expires_at = utc(grant.expires_at)
        source = await self.inference.plan_transcription(recording)
        bundle, c2 = await self.authority.approval(self.app, actor, recording, source, now)
        command = {
            "recording_id": str(recording_id),
            **actor_binding(actor),
            "authority_sha256": bundle.digest,
        }
        if report_language is not None:
            if not isinstance(report_language, str) or report_language not in {
                "en",
                "hi-Deva+en",
                "mr-Deva+en",
            }:
                raise ConversationDenied("Choose a supported report language.")
            command["report_language"] = report_language
        include_report_options = report_language is not None
        replay = await self.app._replay(actor, key, "processing_plan_quote", command)
        if replay is not None and replay.result_id is not None:
            return self.view(
                await self._row(actor, recording_id, replay.result_id),
                include_report_options=include_report_options,
            )
        active = await self.db.scalar(
            select(ConversationProcessingPlan).where(
                ConversationProcessingPlan.recording_id == recording_id,
                ConversationProcessingPlan.state == "active",
            )
        )
        if active is not None:
            return self.view(active, include_report_options=include_report_options)
        approvals: dict[str, StageApproval]
        if isinstance(actor, ProcessingActor):
            derived_approvals = {
                stage: self.authority.stage_approval(
                    bundle,
                    actor,
                    source_sha256=recording.source_sha256,
                    stage=stage,
                    configuration_sha256=c2.configuration_sha256,
                )
                for stage in ("C2", "C4", "C5")
            }
            if any(item is None for item in derived_approvals.values()):
                raise ConversationDenied(
                    "This call needs an approved transcription, facts and coaching route."
                )
            approvals = {
                stage: item for stage, item in derived_approvals.items() if item is not None
            }
        else:
            approvals = {
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
                item.provider_id not in {"groq", "gemini"}
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
                provider=item.provider_id,
                model=item.model_id,
                recipe=recipe,
                profile_revision=str(profile["revision"]) if stage == "C5" else None,
                configuration_sha256=c2.configuration_sha256,
            )
        settings_row, analysis_settings = await latest_analysis_settings(
            self.db, self.authority.operations_tenant_id
        )
        coaching_prompt_revision = analysis_settings.c5_coaching_prompt_revision
        selected_language = report_language or analysis_settings.report_language_default
        if coaching_prompt_revision == COACHING_PROMPT_V3 and selected_language != "en":
            raise ConversationDenied(
                "Non-English report language requires the coaching-v4 or coaching-v5 "
                "qualitative engine."
            )
        qualitative_pack_sha256 = (
            load_qualitative_pack_for_revision(coaching_prompt_revision).sha256
            if coaching_prompt_revision in {COACHING_PROMPT_V4, COACHING_PROMPT_V5}
            else None
        )
        c4, c5 = approvals["C4"], approvals["C5"]
        if settings_row is not None:
            c4 = c4.model_copy(
                update={
                    "max_requests": min(c4.max_requests, analysis_settings.c4_max_requests),
                    "max_completion_tokens": min(
                        c4.max_completion_tokens, analysis_settings.c4_max_completion_tokens
                    ),
                }
            )
            c5 = c5.model_copy(
                update={
                    "max_completion_tokens": min(
                        c5.max_completion_tokens, analysis_settings.c5_max_completion_tokens
                    ),
                }
            )
        # C1 has already charged the measured source audio. The remaining
        # provider plan needs zero additional user minutes, even when the last
        # authorized call consumed the account's entire allowance.
        maximum_seconds = 0
        maximum_cost = maximum_plan_cost_with_repair((c2, c4, c5))
        repair_cost = automatic_c5_repair_cost(c5)
        if maximum_cost:
            budget_row = await self.db.get(ConversationBudgetAccount, bundle.budget_scope_id)
            if budget_row is None:
                raise ConversationConflict("The provider budget cannot cover this complete plan.")
            budget = BudgetAccount.from_dict(budget_row.snapshot)
            try:
                effective_cap = effective_budget_cap_paise(
                    bundle.budget_cap_paise, budget.cap_paise
                )
            except ValueError:
                raise ConversationDenied(
                    "The persisted provider budget exceeds its release approval."
                ) from None
            if maximum_cost > effective_cap:
                raise ConversationDenied("The complete plan exceeds the effective provider budget.")
            if budget.available_paise < maximum_cost:
                raise ConversationConflict("The provider budget cannot cover this complete plan.")
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
                **actor_columns(actor),
                continuation_grant_id=continuation_grant_id,
                generation=recording.generation,
                source_sha256=recording.source_sha256,
                source_revision=recording.source_revision,
                authority_sha256=bundle.digest,
                transcription_cache_key=source.checkpoint.cache_key,
                duration_ms=source.duration_ms,
                stages=(c2, c4, c5),
                profile=profile,
                fact_prompt_revision=FACT_PROMPT_COMPACT,
                coaching_prompt_revision=coaching_prompt_revision,
                report_language=(
                    selected_language
                    if coaching_prompt_revision in {COACHING_PROMPT_V4, COACHING_PROMPT_V5}
                    or report_language is not None
                    else None
                ),
                qualitative_pack_sha256=qualitative_pack_sha256,
                created_at_epoch=int(now.timestamp()),
                expires_at_epoch=min(
                    int(now.timestamp()) + 3600,
                    bundle.expires_at_epoch,
                    *(item.expires_at_epoch for item in approvals.values()),
                    *(
                        [int(continuation_expires_at.timestamp())]
                        if continuation_expires_at is not None
                        else []
                    ),
                ),
                max_entitlement_seconds=maximum_seconds,
                max_cost_paise=maximum_cost,
                automatic_c5_repair_cost_paise=(
                    repair_cost if planned_c5_requests(c5) > 1 else None
                ),
                analysis_settings_revision=None if settings_row is None else settings_row.revision,
                output_profile=analysis_settings.c5_output_profile,
            )
        except ValueError:
            raise ConversationDenied("The complete processing plan is not approved.") from None
        await validate_continuation_grant(self.app, actor, recording, value, now)
        row = ConversationProcessingPlan(
            id=uuid4(),
            tenant_id=recording.tenant_id,
            person_id=recording.person_id,
            recording_id=recording_id,
            **actor_columns(actor),
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
        return self.view(row, include_report_options=include_report_options)

    async def accept(
        self, actor: ConversationActor, recording_id: UUID, payload: PlanAcceptance, *, key: str
    ) -> dict[str, Any]:
        now = await self.app.admit(actor)
        await self.authority.require_execution_enabled(self.app)
        row = await self._row(actor, recording_id, payload.plan_id)
        value = manifest_for(row)
        recording = await self.app._recording(actor, recording_id)
        await validate_continuation_grant(self.app, actor, recording, value, now)
        bundle = await self.authority.admit(self.app, actor)
        if (
            payload.accepted is not True
            or payload.plan_fingerprint != row.plan_sha256
            or not same_actor(row, actor)
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
        actor: ConversationActor,
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
        selected_configuration_sha256 = next(
            item.configuration_sha256
            for item in value.stages
            if item.stage == stage.checkpoint.stage
        )
        bundle, stage_approval = await self.authority.approval(
            self.app,
            actor,
            recording,
            stage,
            utc(self.app.clock()),
            configuration_sha256=selected_configuration_sha256,
        )
        existing = await self.db.scalar(
            select(ConversationInferenceTask).where(
                ConversationInferenceTask.recording_id == row.recording_id,
                ConversationInferenceTask.cache_key == stage.checkpoint.cache_key,
            )
        )
        if existing is not None:
            if existing.erased_at is not None or existing.generation != row.generation:
                raise ConversationConflict("The saved stage is no longer reusable.")
            # The coordinator must observe terminal tasks to publish their
            # exact hold or select the separately authorized bounded C5 repair.
            # Returning the retained task here never dispatches it again;
            # fresh stage requests are fenced by inference.request_stage.
            if existing.state == "completed":
                if existing.checkpoint_id is None:
                    raise ConversationConflict("The saved stage checkpoint is unavailable.")
                pipeline = ReportingPipeline(self.inference)
                checkpoint, _ = await pipeline.checkpoint(
                    recording, existing.checkpoint_id, existing.stage
                )
                await pipeline.provider_task(recording, checkpoint)
            return existing
        if stage.checkpoint.stage == "C2" and self.storage is not None:
            if not isinstance(stage, TranscriptionPlan):
                raise ConversationConflict("The saved transcription plan is unavailable.")
            from ac_platform.conversation_intelligence.retained_c2_recovery import (
                RetainedC2ReuseService,
            )

            reused = await RetainedC2ReuseService(
                self.app,
                self.authority,
                self.storage,
            ).reuse(
                actor,
                row,
                value,
                recording,
                stage,
                stage_approval,
                budget_scope_id=bundle.budget_scope_id,
                authorization_ref=self.authority.authorization_ref(bundle, stage_approval),
                key=f"run:{row.id}:{stage.checkpoint.cache_key}",
                now=utc(self.app.clock()),
            )
            if reused is not None:
                return reused
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

    async def advance(self, actor: ConversationActor, row: ConversationProcessingPlan) -> None:
        from ac_platform.conversation_intelligence.report_overview import stage_completion_limit

        value = await require_plan_consent(self.app, actor, row, self.authority)
        if row.state != "active":
            return
        # Inspect the exact canonical task each time. A crash between polling
        # and enqueue cannot duplicate its immutable cache key or reservation.
        c2 = await self._enqueue(actor, row, value, None)
        tasks = [c2]
        current = "C2"
        repair_progress: dict[str, Any] | None = None
        if c2.state == "completed" and c2.checkpoint_id is not None:
            c4 = value.stages[1]
            first_request = StageRequest(
                stage="C4",
                transcript_checkpoint_id=c2.checkpoint_id,
                provider=c4.provider_id,
                model=c4.model_id,
                fact_prompt_revision=value.fact_prompt_revision,
                max_input_chars=value.max_input_chars,
                max_completion_tokens=stage_completion_limit(
                    "C4", c4.max_completion_tokens, provider=c4.provider_id, model=c4.model_id
                ),
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
                c5_request = StageRequest(
                    stage="C5",
                    transcript_checkpoint_id=c2.checkpoint_id,
                    fact_checkpoint_ids=tuple(facts),
                    provider=c5.provider_id,
                    model=c5.model_id,
                    max_input_chars=value.max_input_chars,
                    max_completion_tokens=stage_completion_limit(
                        "C5",
                        c5.max_completion_tokens,
                        provider=c5.provider_id,
                        model=c5.model_id,
                    ),
                    output_profile=value.output_profile,
                    profile=value.profile,
                    coaching_prompt_revision=value.coaching_prompt_revision,
                    report_language=value.report_language,
                    qualitative_pack_sha256=value.qualitative_pack_sha256,
                )
                judge = await self._enqueue(
                    actor,
                    row,
                    value,
                    c5_request,
                )
                if judge.state == "uncertain":
                    repair = await self._automatic_c5_repair(value, judge)
                    if repair is not None:
                        repair_progress = {
                            "attempt": repair.attempt,
                            "failure_code": repair.failure_code,
                            "original_run_id": str(repair.original_run_id),
                            "original_response_sha256": repair.original_response_sha256,
                        }
                        judge = await self._enqueue(
                            actor,
                            row,
                            value,
                            c5_request.model_copy(update={"repair": repair}),
                        )
                        repair_progress.update({"run_id": str(judge.run_id), "state": judge.state})
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
                    if repair_progress is not None:
                        row.progress["c5_repair"] = repair_progress
                    return
        bad = next(
            (item for item in tasks if item.state in {"failed", "uncertain", "cancelled"}), None
        )
        if bad is not None:
            row.state = "held"
            row.progress = {"current_stage": bad.stage, "failure_code": f"stage_{bad.state}"}
        else:
            row.progress = {"current_stage": current}
        if repair_progress is not None:
            row.progress["c5_repair"] = repair_progress
        row.next_check_at = utc(self.app.clock()) + timedelta(seconds=2)


class ProcessingPlanScheduler:
    """Bounded database-driven coordinator; no browser or provider credentials."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        authority: ConversationAuthority,
        storage: PrivateLocalRecordingStorage | None = None,
    ) -> None:
        self.sessions, self.authority, self.storage = sessions, authority, storage

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
            actor = actor_from_row(candidate)
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
                    await ConversationProcessingPlans(app, self.authority, self.storage).advance(
                        actor, row
                    )
            except (ConversationError, InferenceTaskError):
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
