"""Owner-only processing-plan consent and progress in the existing AC API."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from starlette.requests import ClientDisconnect

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationError,
)
from ac_platform.conversation_intelligence.authority import ConversationAuthority
from ac_platform.conversation_intelligence.processing_plan import (
    ConversationProcessingPlans,
    PlanAcceptance,
    parse_report_language_preference,
)
from ac_platform.conversation_intelligence.qualitative_pack import ReportLanguage
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

    async def quote_language(request: Request) -> ReportLanguage | None:
        raw = bytearray()
        try:
            async with asyncio.timeout(10):
                async for block in request.stream():
                    if len(raw) + len(block) > 1024:
                        raise HTTPException(413, "The report preference is too large.")
                    raw.extend(block)
        except (TimeoutError, ClientDisconnect):
            raise HTTPException(408, "The report preference was interrupted.") from None
        if not raw:
            return None
        content_types = request.headers.getlist("content-type")
        if (
            len(content_types) != 1
            or content_types[0].split(";", 1)[0].strip().lower() != "application/json"
        ):
            raise HTTPException(415, "Choose a report language using JSON.")
        try:
            return parse_report_language_preference(bytes(raw))
        except ValueError:
            raise HTTPException(422, "Choose one supported report language.") from None

    @router.post("/recordings/{recording_id}/plan/quote", status_code=201)
    async def quote(
        recording_id: UUID,
        request: Request,
        response: Response,
        key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        guard(request, response)
        report_language = await quote_language(request)
        try:
            return await ConversationProcessingPlans(
                ConversationApplication(auth.database), authority
            ).quote(
                auth.resolved.actor,
                recording_id,
                key=key,
                report_language=report_language,
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
