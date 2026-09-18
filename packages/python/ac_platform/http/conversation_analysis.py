"""Exact owner consent and stage admission; no learner provider controls."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationError,
)
from ac_platform.conversation_intelligence.authority import ConversationAuthority
from ac_platform.conversation_intelligence.contracts import QuoteAcceptance
from ac_platform.conversation_intelligence.inference import ConversationInference
from ac_platform.conversation_intelligence.models import (
    ConversationInferenceTask,
    ConversationProcessingPlan,
)
from ac_platform.conversation_intelligence.report_overview import stage_completion_limit
from ac_platform.conversation_intelligence.reporting_pipeline import StageRequest
from ac_platform.http.auth import AuthenticatedTransaction, RequireActor, require_safe_origin
from ac_platform.kernel.authz import ActorContext


class AnalysisSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    stage: Literal["C2", "C4", "C5"]
    transcript_checkpoint_id: UUID | None = None
    fact_checkpoint_ids: tuple[UUID, ...] = Field(default=(), max_length=64)
    chunk_index: int = Field(default=1, strict=True, ge=1, le=64)

    @model_validator(mode="after")
    def selection(self) -> AnalysisSelection:
        if self.stage == "C2" and (
            self.transcript_checkpoint_id or self.fact_checkpoint_ids or self.chunk_index != 1
        ):
            raise ValueError("Transcription selects the original recording.")
        if self.stage != "C2" and self.transcript_checkpoint_id is None:
            raise ValueError("Select the saved transcript checkpoint.")
        if self.stage == "C4" and self.fact_checkpoint_ids:
            raise ValueError("Facts select the transcript.")
        if self.stage == "C5" and (not self.fact_checkpoint_ids or self.chunk_index != 1):
            raise ValueError("Coaching requires saved facts.")
        return self

    async def stage_request(
        self,
        app: ConversationApplication,
        actor: ActorContext,
        recording_id: UUID,
        authority: ConversationAuthority,
    ) -> StageRequest | None:
        bundle = await authority.admit(app, actor)
        await app.get(actor, recording_id)
        recording = await app._recording(actor, recording_id)
        approval = next(
            (
                item
                for item in bundle.stages
                if (item.tenant_id, item.person_id, item.source_sha256, item.stage)
                == (actor.tenant_id, actor.person_id, recording.source_sha256, self.stage)
            ),
            None,
        )
        if approval is None:
            raise HTTPException(403, "This recording and stage need current processing approval.")
        if self.stage == "C2":
            return None
        if approval.max_completion_tokens < 256:
            raise HTTPException(403, "The approved output limit does not support this stage.")
        assert self.transcript_checkpoint_id is not None
        return StageRequest(
            stage=self.stage,
            transcript_checkpoint_id=self.transcript_checkpoint_id,
            fact_checkpoint_ids=self.fact_checkpoint_ids,
            chunk_index=self.chunk_index,
            provider=approval.provider_id,
            model=approval.model_id,
            max_completion_tokens=stage_completion_limit(
                self.stage, approval.max_completion_tokens
            ),
        )


class AnalysisAcceptance(QuoteAcceptance):
    quote_id: UUID
    selection: AnalysisSelection


def install_analysis_routes(
    router: APIRouter,
    settings: Settings,
    require_actor: RequireActor,
    authority: ConversationAuthority,
) -> None:
    from ac_platform.http.conversation_plan import install_plan_routes

    install_plan_routes(router, settings, require_actor, authority)
    dependency = Depends(require_actor, scope="function")

    def guard(request: Request, response: Response, *, write: bool = True) -> None:
        response.headers["Cache-Control"] = "private, no-store"
        if request.query_params:
            raise HTTPException(422, "Processing uses your current AC workspace.")
        if write:
            require_safe_origin(request, settings)

    @router.post("/recordings/{recording_id}/analysis/quote", status_code=201)
    async def quote(
        recording_id: UUID,
        payload: AnalysisSelection,
        request: Request,
        response: Response,
        key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
        auth: AuthenticatedTransaction = dependency,
    ) -> Any:
        guard(request, response)
        app = ConversationApplication(auth.database)
        try:
            stage = await payload.stage_request(app, auth.resolved.actor, recording_id, authority)
            return await authority.issue(
                app, auth.resolved.actor, recording_id, key=key, request=stage
            )
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @router.post("/recordings/{recording_id}/analysis", status_code=202)
    async def start(
        recording_id: UUID,
        payload: AnalysisAcceptance,
        request: Request,
        response: Response,
        key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
        auth: AuthenticatedTransaction = dependency,
    ) -> Any:
        guard(request, response)
        app = ConversationApplication(auth.database)
        try:
            stage = await payload.selection.stage_request(
                app, auth.resolved.actor, recording_id, authority
            )
            service = ConversationInference(app, authority=authority)
            await service.accept(
                auth.resolved.actor,
                recording_id,
                payload.quote_id,
                QuoteAcceptance(
                    quote_fingerprint=payload.quote_fingerprint,
                    privacy_revision=payload.privacy_revision,
                    accepted=payload.accepted,
                ),
                request=stage,
            )
            return await service.request_stage(
                auth.resolved.actor,
                recording_id,
                payload.quote_id,
                key=key,
                request=stage,
            )
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @router.get("/recordings/{recording_id}/analysis")
    async def progress(
        recording_id: UUID,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        guard(request, response, write=False)
        app = ConversationApplication(auth.database)
        try:
            # History remains readable when a provider authorization expires.
            await app.get(auth.resolved.actor, recording_id)
            tasks = (
                await auth.database.scalars(
                    select(ConversationInferenceTask)
                    .where(
                        ConversationInferenceTask.recording_id == recording_id,
                        ConversationInferenceTask.person_id == auth.resolved.actor.person_id,
                        ConversationInferenceTask.tenant_id == auth.resolved.actor.tenant_id,
                        ConversationInferenceTask.erased_at.is_(None),
                    )
                    .order_by(ConversationInferenceTask.created_at)
                    .limit(128)
                )
            ).all()
            active_plan = await auth.database.scalar(
                select(ConversationProcessingPlan.id)
                .where(
                    ConversationProcessingPlan.recording_id == recording_id,
                    ConversationProcessingPlan.tenant_id == auth.resolved.actor.tenant_id,
                    ConversationProcessingPlan.person_id == auth.resolved.actor.person_id,
                    ConversationProcessingPlan.state == "active",
                    ConversationProcessingPlan.erased_at.is_(None),
                )
                .limit(1)
            )
            return {
                "recording_id": str(recording_id),
                "automatic_progression": active_plan is not None,
                "stages": [
                    {
                        "run_id": str(item.run_id),
                        "stage": item.stage,
                        "state": item.state,
                        "checkpoint_id": str(item.checkpoint_id) if item.checkpoint_id else None,
                    }
                    for item in tasks
                ],
            }
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None
