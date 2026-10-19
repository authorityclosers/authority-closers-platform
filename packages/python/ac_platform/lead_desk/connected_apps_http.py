"""Settings → Connected apps routes (/v1/lead-desk/integrations, owners and admins).

- ``GET  /integrations/health``: each app's health for this workspace.
- ``POST /integrations/{app}/test``: a real test of one app (``connected_apps``).
- ``GET  /integrations/tests/{test_id}``: how a test that takes a while is going.

Same workspace rule as the CRM's own routes. Admin-2 builds the Settings pages on these.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from sqlalchemy import select

from ac_platform.conversation_intelligence.sales_xray_tenants import SALES_XRAY_MEMBER_ROLES
from ac_platform.http.auth import require_safe_origin
from ac_platform.http.routes import RouteContext
from ac_platform.identity.models import Person
from ac_platform.kernel.errors import DomainError
from ac_platform.lead_desk import connected_apps as apps
from ac_platform.lead_desk.store import DeskError, LeadDesk, Viewer, person_name
from ac_platform.tenancy.models import Membership, Organisation

PRIVATE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}
NO_STORE = {"Cache-Control": "no-store"}


class TestCommand(BaseModel):
    model_config = ConfigDict(
        extra="forbid", alias_generator=to_camel, populate_by_name=True, str_strip_whitespace=True
    )
    page_id: str | None = Field(default=None, max_length=32)
    form_id: str | None = Field(default=None, max_length=32)
    to: str | None = Field(default=None, max_length=32)
    number_id: UUID | None = None
    account_id: UUID | None = None
    send_reply: bool = False
    confirm: bool = False
    customer_id: str | None = Field(default=None, max_length=32)


def install_connected_apps_http(application: FastAPI, ctx: RouteContext) -> None:
    router = APIRouter(prefix="/v1/lead-desk", tags=["lead-desk"])
    settings = ctx.settings
    read_actor = getattr(ctx.require_actor, "read_only", ctx.require_actor)

    def same_host(request: Request) -> None:
        if (
            settings.sales_xray_app_url is None
            or request.url.hostname != settings.sales_xray_app_url.host
        ):
            raise HTTPException(404, "Leads are unavailable here.", headers=NO_STORE)

    @asynccontextmanager
    async def desk_for(
        request: Request, response: Response, *, write: bool = False
    ) -> AsyncIterator[LeadDesk]:
        response.headers.update(PRIVATE)
        same_host(request)
        if write:
            try:
                require_safe_origin(request, settings)
            except DomainError:
                raise HTTPException(
                    403, "Use this Sales Xray page to continue.", headers=PRIVATE
                ) from None
        try:
            async with asynccontextmanager(ctx.require_actor if write else read_actor)(
                request
            ) as auth:
                actor = auth.resolved.actor
                tenant_id = actor.tenant_id
                if (
                    tenant_id is None
                    or tenant_id == settings.operations_tenant_id
                    or tenant_id == settings.public_learner_tenant_id
                ):
                    raise HTTPException(
                        403, "Leads work inside an organisation workspace.", headers=PRIVATE
                    )
                row = (
                    await auth.database.execute(
                        select(Membership.role, Person)
                        .join(Person, Person.id == Membership.person_id)
                        .where(
                            Membership.tenant_id == tenant_id,
                            Membership.person_id == actor.person_id,
                            Membership.status == "active",
                            Membership.ended_at.is_(None),
                            Membership.role.in_(SALES_XRAY_MEMBER_ROLES),
                        )
                    )
                ).first()
                organisation = await auth.database.scalar(
                    select(Organisation.tenant_id).where(Organisation.tenant_id == tenant_id)
                )
                if row is None or organisation is None:
                    raise HTTPException(
                        403, "Leads work inside an organisation workspace.", headers=PRIVATE
                    )
                desk = LeadDesk(
                    auth.database,
                    Viewer(
                        person_id=actor.person_id,
                        tenant_id=tenant_id,
                        role=row[0],
                        name=person_name(row[1]),
                    ),
                )
                desk._require_manager()
                yield desk
        except DeskError as error:
            raise HTTPException(error.status, str(error), headers=PRIVATE) from None
        except DomainError:
            raise HTTPException(401, "Sign in to see your leads.", headers=PRIVATE) from None

    def needs(value: str | None, words: str) -> str:
        if not value:
            raise DeskError(422, words)
        return value

    @router.get("/integrations/health", response_model=apps.Health, response_model_by_alias=True)
    async def integrations_health(request: Request, response: Response) -> apps.Health:
        async with desk_for(request, response) as desk:
            return await apps.health(desk.db, desk.tenant_id, now=desk.now)

    @router.post(
        "/integrations/{app}/test", response_model=apps.TestResult, response_model_by_alias=True
    )
    async def integrations_test(
        app: Literal[
            "meta_leads",
            "whatsapp",
            "messenger",
            "instagram",
            "google_ads",
            "phone_calls",
            "webhook_sources",
        ],
        command: TestCommand,
        request: Request,
        response: Response,
    ) -> apps.TestResult:
        """A real test of one app. AI replies have their own: POST /ai-replies/try."""
        async with desk_for(request, response, write=True) as desk:
            if app == "meta_leads":
                return await apps.test_lead(
                    desk,
                    needs(command.page_id, "Pick a connected Page."),
                    needs(command.form_id, "Pick one of the Page's forms."),
                )
            if app == "whatsapp":
                return await apps.test_whatsapp(
                    desk,
                    needs(command.to, "Enter the number to send the test to."),
                    command.number_id,
                )
            if app in ("messenger", "instagram"):
                return await apps.test_social(
                    desk,
                    "messenger" if app == "messenger" else "instagram",
                    command.account_id,
                    send_reply=command.send_reply,
                    confirm=command.confirm,
                )
            if app == "google_ads":
                return await apps.test_google(
                    desk,
                    command.customer_id,
                    app_url=str(settings.sales_xray_app_url or "").rstrip("/"),
                )
            found = await apps.health(desk.db, desk.tenant_id, now=desk.now)
            return apps.report(next(item for item in found.apps if item.app == app))

    @router.get(
        "/integrations/tests/{test_id}",
        response_model=apps.TestResult,
        response_model_by_alias=True,
    )
    async def integrations_test_status(
        test_id: str, request: Request, response: Response
    ) -> apps.TestResult:
        """How a test that takes a while is going (ask every 2 seconds while waiting)."""
        async with desk_for(request, response) as desk:
            return await apps.test_status(desk, test_id[:80])

    application.include_router(router)
