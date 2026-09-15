"""Owner-only processing-plan consent and progress in the existing AC API."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationError,
)
from ac_platform.conversation_intelligence.authority import ConversationAuthority
from ac_platform.conversation_intelligence.processing_plan import (
    ConversationProcessingPlans,
    PlanAcceptance,
)
from ac_platform.http.auth import AuthenticatedTransaction, RequireActor, require_safe_origin


def install_plan_routes(
    router: APIRouter,
    settings: Settings,
    require_actor: RequireActor,
    authority: ConversationAuthority,
) -> None:
    dependency = Depends(require_actor, scope="function")

    def guard(request: Request, response: Response, *, write: bool = True) -> None:
        response.headers["Cache-Control"] = "private, no-store"
        if request.query_params:
            raise HTTPException(422, "Processing uses your current AC workspace.")
        if write:
            require_safe_origin(request, settings)

    @router.post("/recordings/{recording_id}/plan/quote", status_code=201)
    async def quote(
        recording_id: UUID,
        request: Request,
        response: Response,
        key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        guard(request, response)
        if await request.body():
            raise HTTPException(422, "The processing plan comes from the approved configuration.")
        try:
            return await ConversationProcessingPlans(
                ConversationApplication(auth.database), authority
            ).quote(
                auth.resolved.actor,
                recording_id,
                key=key,
            )
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @router.post("/recordings/{recording_id}/plan", status_code=202)
    async def accept(
        recording_id: UUID,
        payload: PlanAcceptance,
        request: Request,
        response: Response,
        key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        guard(request, response)
        try:
            return await ConversationProcessingPlans(
                ConversationApplication(auth.database), authority
            ).accept(
                auth.resolved.actor,
                recording_id,
                payload,
                key=key,
            )
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @router.get("/recordings/{recording_id}/plan")
    async def progress(
        recording_id: UUID,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        guard(request, response, write=False)
        try:
            return await ConversationProcessingPlans(
                ConversationApplication(auth.database), authority
            ).get(
                auth.resolved.actor,
                recording_id,
            )
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None
