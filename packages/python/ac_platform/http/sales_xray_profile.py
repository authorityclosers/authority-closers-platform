"""Self-service Sales Xray profile and pre-body write eligibility boundary."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.application.settings import Settings
from ac_platform.http.auth import AuthenticatedTransaction, RequireActor, require_safe_origin
from ac_platform.identity.sales_xray_profile import (
    SalesXrayProfileError,
    SalesXrayProfileIncomplete,
    SalesXrayProfileRevisionConflict,
    SalesXrayProfileSnapshot,
    get_sales_xray_profile,
    require_sales_xray_profile_complete,
    update_sales_xray_profile,
)
from ac_platform.kernel.authz import ActorContext


class SalesXrayProfileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None
    email: str
    phone_number_e164: str | None
    phone_verified: bool
    profile_complete: bool
    revision: int


class SalesXrayProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=1, max_length=200)
    phone_number_e164: str | None = Field(max_length=16)
    expected_revision: int = Field(ge=0, strict=True)


async def require_sales_xray_write_profile(
    database: AsyncSession,
    actor: ActorContext | None,
) -> SalesXrayProfileSnapshot:
    """Fail closed for new bytes/provider work unless a human account is ready."""

    if actor is None:
        raise HTTPException(
            401,
            "Sign in and complete your AC contact profile before continuing.",
            headers={"Cache-Control": "private, no-store", "Vary": "Cookie"},
        )
    try:
        return await require_sales_xray_profile_complete(database, person_id=actor.person_id)
    except SalesXrayProfileError:
        raise HTTPException(
            403,
            "Complete your AC contact profile before continuing.",
            headers={"Cache-Control": "private, no-store", "Vary": "Cookie"},
        ) from None


def install_sales_xray_profile_http(
    application: FastAPI,
    *,
    settings: Settings,
    require_actor: RequireActor,
) -> None:
    router = APIRouter(prefix="/v1/me/sales-xray-profile", tags=["sales-xray-profile"])
    actor_dependency = Depends(require_actor, scope="function")
    read_require_actor = getattr(require_actor, "read_only", require_actor)
    read_actor_dependency = Depends(read_require_actor, scope="function")

    def require_profile_surface(request: Request, actor: ActorContext) -> None:
        allowed_hosts = {settings.public_app_url.host}
        if settings.sales_xray_app_url is not None:
            allowed_hosts.add(settings.sales_xray_app_url.host)
        if request.url.hostname not in allowed_hosts or request.query_params:
            raise HTTPException(404, "Profile route not found.")
        if (
            settings.public_learner_tenant_id is None
            or actor.tenant_id != settings.public_learner_tenant_id
        ):
            raise HTTPException(403, "Use your public Academy account for this profile.")

    def require_eligibility_surface(request: Request, actor: ActorContext) -> None:
        allowed_hosts = {
            settings.public_app_url.host,
            settings.api_url.host,
            settings.admin_app_url.host,
            settings.coach_app_url.host,
        }
        if settings.sales_xray_app_url is not None:
            allowed_hosts.add(settings.sales_xray_app_url.host)
        if request.url.hostname not in allowed_hosts or request.query_params:
            raise HTTPException(404, "Profile eligibility route not found.")
        if (
            settings.public_learner_tenant_id is None
            or actor.tenant_id != settings.public_learner_tenant_id
        ):
            raise HTTPException(403, "Use your public Academy account to continue.")

    def headers(response: Response) -> None:
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Vary"] = "Cookie"

    def fail_profile(error: SalesXrayProfileError) -> HTTPException:
        if isinstance(error, SalesXrayProfileRevisionConflict):
            return HTTPException(409, str(error), headers={"Cache-Control": "private, no-store"})
        if isinstance(error, SalesXrayProfileIncomplete):
            return HTTPException(403, str(error), headers={"Cache-Control": "private, no-store"})
        return HTTPException(403, str(error), headers={"Cache-Control": "private, no-store"})

    def response_value(value: SalesXrayProfileSnapshot) -> dict[str, object]:
        return SalesXrayProfileResponse(
            name=value.name,
            email=value.email,
            phone_number_e164=value.phone_number_e164,
            phone_verified=value.phone_verified,
            profile_complete=value.profile_complete,
            revision=value.revision,
        ).model_dump()

    @router.get("", response_model=SalesXrayProfileResponse)
    async def read_profile(
        request: Request,
        response: Response,
        auth: Annotated[AuthenticatedTransaction, read_actor_dependency] = read_actor_dependency,
    ) -> dict[str, object]:
        headers(response)
        require_profile_surface(request, auth.resolved.actor)
        try:
            value = await get_sales_xray_profile(
                auth.database,
                person_id=auth.resolved.actor.person_id,
            )
        except SalesXrayProfileError as error:
            raise fail_profile(error) from None
        return response_value(value)

    @router.put("", response_model=SalesXrayProfileResponse)
    async def update_profile(
        payload: SalesXrayProfileUpdate,
        request: Request,
        response: Response,
        auth: Annotated[AuthenticatedTransaction, actor_dependency] = actor_dependency,
    ) -> dict[str, object]:
        headers(response)
        actor = auth.resolved.actor
        require_profile_surface(request, actor)
        require_safe_origin(request, settings)
        tenant_id = actor.tenant_id or settings.public_learner_tenant_id
        if tenant_id is None:
            raise HTTPException(503, "A tenant audit boundary is unavailable.")
        try:
            value = await update_sales_xray_profile(
                auth.database,
                person_id=actor.person_id,
                session_id=actor.session_id,
                tenant_id=tenant_id,
                full_name=payload.full_name,
                phone_number_e164=payload.phone_number_e164,
                expected_revision=payload.expected_revision,
            )
        except SalesXrayProfileError as error:
            raise fail_profile(error) from None
        except ValueError:
            raise HTTPException(
                422, "Choose a valid name and explicit E.164 phone number."
            ) from None
        return response_value(value)

    @router.get("/write-eligibility", status_code=204)
    async def write_eligibility(
        request: Request,
        response: Response,
        auth: Annotated[AuthenticatedTransaction, read_actor_dependency] = read_actor_dependency,
    ) -> Response:
        headers(response)
        require_eligibility_surface(request, auth.resolved.actor)
        try:
            await require_sales_xray_profile_complete(
                auth.database,
                person_id=auth.resolved.actor.person_id,
            )
        except SalesXrayProfileError as error:
            raise fail_profile(error) from None
        return Response(
            status_code=204,
            headers={"Cache-Control": "private, no-store", "Vary": "Cookie"},
        )

    application.include_router(router)
