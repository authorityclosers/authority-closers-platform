"""Review 2.0 routes on the Admin conversation router (admin revamp, 19 Oct 2026).

GET  /review/pipelines                      the active pipelines
GET  /review/calls/{recording_id}           pipelines and the call's current answers
POST /review/calls/{recording_id}/verdicts  one answer (Idempotency-Key, append-only)

Admin host only; the service admits standing gold reviewers in the operations
workspace. Answers never write to call objects, decisions or Lead Desk fields.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.application import ConversationError
from ac_platform.conversation_intelligence.review_verdicts import ReviewVerdicts
from ac_platform.http.auth import (
    AuthenticatedTransaction,
    RequireActor,
    require_admin_surface,
    require_safe_origin,
)


class VerdictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pipeline: str = Field(min_length=1, max_length=48)
    target_kind: str = Field(min_length=1, max_length=16)
    target_ref: str = Field(min_length=1, max_length=96)
    question: str = Field(min_length=1, max_length=48)
    answer: dict[str, Any]


def install_review_verdict_routes(
    router: APIRouter, *, settings: Settings, require_actor: RequireActor
) -> None:
    dependency = Depends(require_actor, scope="function")

    def scope(request: Request, response: Response) -> None:
        require_admin_surface(request, settings)
        response.headers["Cache-Control"] = "private, no-store"

    def service(auth: AuthenticatedTransaction) -> ReviewVerdicts:
        if settings.operations_tenant_id is None:
            raise HTTPException(503, "Review is not configured.")
        return ReviewVerdicts(auth.database, settings.operations_tenant_id)

    @router.get("/review/pipelines")
    async def pipelines(
        request: Request, response: Response, auth: AuthenticatedTransaction = dependency
    ) -> dict[str, Any]:
        """Each review pipeline's active version, built from primitives."""
        scope(request, response)
        try:
            return await service(auth).list_pipelines(auth.resolved.actor)
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @router.get("/review/calls/{recording_id}")
    async def call(
        recording_id: UUID,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """The active pipelines and every reviewer's current answers for one call."""
        scope(request, response)
        try:
            return await service(auth).call(auth.resolved.actor, recording_id)
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @router.post("/review/calls/{recording_id}/verdicts", status_code=201)
    async def save(
        recording_id: UUID,
        body: VerdictRequest,
        request: Request,
        response: Response,
        key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """One reviewer's answer to one question about one analysis item."""
        scope(request, response)
        require_safe_origin(request, settings)
        try:
            return await service(auth).save(
                auth.resolved.actor,
                recording_id,
                pipeline_key=body.pipeline,
                target_kind=body.target_kind,
                target_ref=body.target_ref,
                question_key=body.question,
                answer=body.answer,
                request_key=key,
            )
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None
