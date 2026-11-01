"""Owner alerts and the day's summary (/v1/lead-desk/owner-alerts, owners and admins;
competitor teardown 19 and 20, 1 Nov 2026).

- ``GET  /owner-alerts``: the switches, and this person's summary days.
- ``PUT  /owner-alerts``: save them.
- ``GET  /owner-alerts/list?kind=``: everything of that kind past its limit now (the list
  an alert opens).
- ``GET  /owner-alerts/summary``: today so far, per seller (the page the summary opens).
- ``POST /owner-alerts/summary/test``: the summary to this person's own phones now.

Same workspace rule as the CRM's own routes. The work is in ``owner_alerts``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from ac_platform.conversation_intelligence.sales_xray_tenants import SALES_XRAY_MEMBER_ROLES
from ac_platform.http.auth import require_safe_origin
from ac_platform.http.routes import RouteContext
from ac_platform.identity.models import Person
from ac_platform.kernel.errors import DomainError
from ac_platform.lead_desk import owner_alerts, push
from ac_platform.lead_desk.store import DeskError, LeadDesk, Viewer, person_name
from ac_platform.tenancy.models import Membership, Organisation

PRIVATE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}
NO_STORE = {"Cache-Control": "no-store"}


class TestSent(BaseModel):
    """How the test went: the phones it went to, and whether phone alerts work here."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    phones: int
    sent: int
    ready: bool


def install_owner_alerts_http(application: FastAPI, ctx: RouteContext) -> None:
    router = APIRouter(prefix="/v1/lead-desk", tags=["lead-desk"])
    settings = ctx.settings
    read_actor = getattr(ctx.require_actor, "read_only", ctx.require_actor)

    def same_host(request: Request) -> None:
        if (
            settings.sales_xray_app_url is None
            or request.url.hostname != settings.sales_xray_app_url.host
        ):
            raise HTTPException(404, "Leads are unavailable here.", headers=NO_STORE)

    def no_query(request: Request, allowed: frozenset[str] = frozenset()) -> None:
        if any(name not in allowed for name in request.query_params):
            raise HTTPException(422, "Remove the extra address options.", headers=PRIVATE)

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

    @router.get(
        "/owner-alerts",
        response_model=owner_alerts.OwnerAlertsView,
        response_model_by_alias=True,
    )
    async def owner_alerts_view(
        request: Request, response: Response
    ) -> owner_alerts.OwnerAlertsView:
        no_query(request)
        async with desk_for(request, response) as desk:
            return await owner_alerts.view(desk)

    @router.put(
        "/owner-alerts",
        response_model=owner_alerts.OwnerAlertsView,
        response_model_by_alias=True,
    )
    async def owner_alerts_save(
        command: owner_alerts.OwnerAlertsCommand, request: Request, response: Response
    ) -> owner_alerts.OwnerAlertsView:
        no_query(request)
        async with desk_for(request, response, write=True) as desk:
            return await owner_alerts.save(desk, command)

    @router.get(
        "/owner-alerts/list",
        response_model=owner_alerts.OwnerAlertList,
        response_model_by_alias=True,
    )
    async def owner_alerts_list(
        kind: owner_alerts.Kind, request: Request, response: Response
    ) -> owner_alerts.OwnerAlertList:
        no_query(request, frozenset({"kind"}))
        async with desk_for(request, response) as desk:
            return await owner_alerts.alert_list(desk, kind)

    @router.get(
        "/owner-alerts/summary",
        response_model=owner_alerts.DaySummary,
        response_model_by_alias=True,
    )
    async def owner_alerts_summary(request: Request, response: Response) -> owner_alerts.DaySummary:
        no_query(request)
        async with desk_for(request, response) as desk:
            return await owner_alerts.day_summary(
                desk.db, desk.tenant_id, desk.viewer.person_id, now=desk.now
            )

    @router.post("/owner-alerts/summary/test", response_model=TestSent)
    async def owner_alerts_summary_test(request: Request, response: Response) -> TestSent:
        no_query(request)
        async with desk_for(request, response, write=True) as desk:
            test = await owner_alerts.summary_test(desk)
        # Kept first (the app reads the words as the push arrives), then sent.
        cfg = push.config()
        if test.alert is None or cfg is None:
            return TestSent(phones=test.phones, sent=0, ready=cfg is not None)
        async with httpx.AsyncClient(timeout=15) as client:
            sent, _ = await push.send([test.alert], push.Fcm(cfg), client)
        return TestSent(phones=test.phones, sent=sent, ready=True)

    application.include_router(router)
