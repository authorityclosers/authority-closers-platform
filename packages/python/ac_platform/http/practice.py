"""Explicit tenant-scoped editorial practice pilot with real session checks."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from ac_platform.application.settings import Settings
from ac_platform.http.auth import AuthenticatedTransaction, RequireActor, require_safe_origin
from ac_platform.practice.application import PracticeApplication, PracticeError
from ac_platform.practice.arcade import (
    ExerciseUnavailable,
    InvalidPracticeResponse,
    catalog,
    check_response,
    practice_set,
)
from ac_platform.practice.focus import FocusApplication, FocusConflict


class PracticeCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$")
    selections: list[Annotated[StrictInt, Field(ge=0, le=15)]] = Field(min_length=1, max_length=12)


class PracticeRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: StrictInt = Field(ge=0)


class PracticeStoredResponse(PracticeCheck, PracticeRevision):
    pass


class PracticeTimezone(PracticeRevision):
    timezone: str = Field(min_length=1, max_length=64)


class PracticeIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FocusRevision(PracticeRevision):
    expected_attempt_revision: StrictInt = Field(ge=0)


PracticeKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]


def install_practice_http(app: FastAPI, *, settings: Settings, require_actor: RequireActor) -> None:
    # Resolve again at composition, including callers that bypassed Settings
    # validation with model_copy. No local preview flag enables a deployed pilot.
    tenant_id = settings.practice_tenant_id
    if tenant_id is None:
        return
    router = APIRouter(prefix="/v1/practice", tags=["editorial-practice-pilot"])
    # Deferred journal checks must commit before a success response is emitted.
    actor_dependency = Depends(require_actor, scope="function")

    def admitted(auth: AuthenticatedTransaction, request: Request, response: Response) -> None:
        if (
            auth.resolved.actor.tenant_id is None
            or auth.resolved.actor.tenant_id != tenant_id
            or auth.resolved.membership_role not in {"learner", "admin", "owner"}
        ):
            raise HTTPException(403, "Select your academy to open practice.")
        if request.query_params:
            raise HTTPException(422, "Practice does not accept account or tenant selectors.")
        response.headers["cache-control"] = "private, no-store"

    def engine(auth: AuthenticatedTransaction) -> PracticeApplication:
        return PracticeApplication(
            auth.database,
            academy_tenant_id=tenant_id,
            environment=settings.environment,
            preview_enabled=settings.practice_arcade_preview_enabled,
            pilot_enabled=settings.practice_pilot_enabled,
        )

    async def result(call: Awaitable[dict[str, Any]]) -> dict[str, Any]:
        try:
            return await call
        except FocusConflict as error:
            raise HTTPException(
                error.status, {"reason": error.reason, "message": str(error)}
            ) from None
        except PracticeError as error:
            raise HTTPException(error.status, str(error)) from None
        except ExerciseUnavailable as error:
            raise HTTPException(404, str(error)) from None
        except InvalidPracticeResponse as error:
            raise HTTPException(422, str(error)) from None

    @router.get("/focus")
    async def get_focus(
        request: Request, response: Response, auth: AuthenticatedTransaction = actor_dependency
    ) -> dict[str, Any]:
        admitted(auth, request, response)
        return await result(FocusApplication(engine(auth)).summary(auth.resolved.actor))

    @router.post("/attempts/{attempt_id}/focus")
    async def start_focus(
        attempt_id: UUID,
        payload: FocusRevision,
        request: Request,
        response: Response,
        key: PracticeKey,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> dict[str, Any]:
        admitted(auth, request, response)
        require_safe_origin(request, settings)
        return await result(
            FocusApplication(engine(auth)).start(
                auth.resolved.actor,
                attempt_id,
                key=key,
                expected_revision=payload.expected_revision,
                expected_attempt_revision=payload.expected_attempt_revision,
            )
        )

    @router.post("/focus/runs/{run_id}/end")
    async def end_focus(
        run_id: UUID,
        payload: FocusRevision,
        request: Request,
        response: Response,
        key: PracticeKey,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> dict[str, Any]:
        admitted(auth, request, response)
        require_safe_origin(request, settings)
        return await result(
            FocusApplication(engine(auth)).end(
                auth.resolved.actor,
                run_id,
                key=key,
                expected_revision=payload.expected_revision,
                expected_attempt_revision=payload.expected_attempt_revision,
            )
        )

    @router.get("/profile")
    async def get_profile(
        request: Request, response: Response, auth: AuthenticatedTransaction = actor_dependency
    ) -> dict[str, Any]:
        admitted(auth, request, response)
        return await result(engine(auth).profile(auth.resolved.actor))

    @router.put("/profile")
    async def put_profile(
        payload: PracticeTimezone,
        request: Request,
        response: Response,
        key: PracticeKey,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> dict[str, Any]:
        admitted(auth, request, response)
        require_safe_origin(request, settings)
        return await result(
            engine(auth).save_profile(
                auth.resolved.actor,
                key=key,
                timezone=payload.timezone,
                expected_revision=payload.expected_revision,
            )
        )

    @router.get("/progress")
    async def get_progress(
        request: Request, response: Response, auth: AuthenticatedTransaction = actor_dependency
    ) -> dict[str, Any]:
        admitted(auth, request, response)
        return await result(engine(auth).progress(auth.resolved.actor))

    @router.post("/sets/{set_id}/attempts")
    async def issue_attempt(
        set_id: str,
        payload: PracticeIssue,
        request: Request,
        response: Response,
        key: PracticeKey,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> dict[str, Any]:
        admitted(auth, request, response)
        require_safe_origin(request, settings)
        return await result(engine(auth).issue(auth.resolved.actor, set_id=set_id, key=key))

    @router.get("/attempts/{attempt_id}")
    async def get_attempt(
        attempt_id: UUID,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> dict[str, Any]:
        admitted(auth, request, response)
        return await result(engine(auth).attempt(auth.resolved.actor, attempt_id))

    @router.post("/attempts/{attempt_id}/responses")
    async def save_response(
        attempt_id: UUID,
        payload: PracticeStoredResponse,
        request: Request,
        response: Response,
        key: PracticeKey,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> dict[str, Any]:
        admitted(auth, request, response)
        require_safe_origin(request, settings)
        return await result(
            engine(auth).respond(
                auth.resolved.actor,
                attempt_id,
                key=key,
                item_id=payload.item_id,
                selections=payload.selections,
                expected_revision=payload.expected_revision,
            )
        )

    @router.post("/attempts/{attempt_id}/feedback/{response_id}/acknowledge")
    async def acknowledge_feedback(
        attempt_id: UUID,
        response_id: UUID,
        payload: PracticeRevision,
        request: Request,
        response: Response,
        key: PracticeKey,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> dict[str, Any]:
        admitted(auth, request, response)
        require_safe_origin(request, settings)
        return await result(
            engine(auth).acknowledge(
                auth.resolved.actor,
                attempt_id,
                response_id,
                key=key,
                expected_revision=payload.expected_revision,
            )
        )

    @router.get("/sets")
    async def list_sets(
        request: Request, response: Response, auth: AuthenticatedTransaction = actor_dependency
    ) -> dict[str, Any]:
        admitted(auth, request, response)
        return catalog()

    @router.get("/sets/{set_id}")
    async def get_set(
        set_id: str,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> dict[str, Any]:
        admitted(auth, request, response)
        try:
            return practice_set(set_id)
        except ExerciseUnavailable as error:
            raise HTTPException(404, str(error)) from None

    async def check(
        set_id: str,
        payload: PracticeCheck,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> dict[str, Any]:
        admitted(auth, request, response)
        require_safe_origin(request, settings)
        try:
            return check_response(set_id, payload.item_id, payload.selections)
        except ExerciseUnavailable as error:
            raise HTTPException(404, str(error)) from None
        except InvalidPracticeResponse as error:
            raise HTTPException(422, str(error)) from None

    # Deployment uses stored attempts/feedback only. Preserve the old stateless
    # comparator solely for explicitly opted-in local preview callers.
    if settings.practice_arcade_preview_enabled:
        router.add_api_route("/sets/{set_id}/check", check, methods=["POST"])
    app.include_router(router)
