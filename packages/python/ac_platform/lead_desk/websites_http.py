"""Website endpoints for the CRM (/v1/lead-desk): the one-line script's two calls, and the
Websites card a manager sees (lead_desk/websites.py).

The script's calls have no session: the organisation's public key and the page's own
Origin are their authority, as an ad pixel's are. They answer any site (CORS without
credentials), so the script can say "connected" on the page it runs on. Each address may
send only a few (``http/rate_limits.py``: ``website-hello`` and ``website-lead``).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from starlette.requests import ClientDisconnect

from ac_platform.conversation_intelligence.sales_xray_tenants import SALES_XRAY_MEMBER_ROLES
from ac_platform.http.auth import require_safe_origin
from ac_platform.http.routes import RouteContext
from ac_platform.identity.models import Person
from ac_platform.kernel.errors import DomainError
from ac_platform.lead_desk import websites
from ac_platform.lead_desk.store import DeskError, LeadDesk, Viewer, person_name
from ac_platform.tenancy.models import Membership, Organisation

PRIVATE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}
HELLO_MAX = 8 * 1024
LEAD_MAX = 48 * 1024


def _cors(origin: str | None) -> dict[str, str]:
    """Any site may read the answer; no cookie is ever sent or read."""
    headers = {"Cache-Control": "no-store", "Vary": "Origin"}
    if origin and origin != "null":
        headers["Access-Control-Allow-Origin"] = origin[:300]
    return headers


async def _json(request: Request, limit: int) -> dict[str, Any]:
    """The script sends JSON as text/plain, so the browser needs no preflight."""
    raw = bytearray()
    try:
        async with asyncio.timeout(10):
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw) > limit:
                    raise DeskError(413, "That's too much to send.")
    except (TimeoutError, ClientDisconnect):
        raise DeskError(408, "The page stopped sending.") from None
    try:
        value = json.loads(bytes(raw))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise DeskError(422, "Send the form as JSON.") from None
    if not isinstance(value, dict):
        raise DeskError(422, "Send one form as a JSON object.")
    return value


def install_websites_http(application: FastAPI, ctx: RouteContext) -> None:
    router = APIRouter(prefix="/v1/lead-desk", tags=["lead-desk"])
    settings = ctx.settings
    read_actor = getattr(ctx.require_actor, "read_only", ctx.require_actor)

    def app_url() -> str:
        return str(settings.sales_xray_app_url or "").rstrip("/")

    def same_host(request: Request, headers: dict[str, str]) -> None:
        if (
            settings.sales_xray_app_url is None
            or request.url.hostname != settings.sales_xray_app_url.host
        ):
            raise HTTPException(404, "Leads are unavailable here.", headers=headers)

    # ----- the script (no session) ----------------------------------------------------

    @router.options("/site/hello")
    @router.options("/site/lead")
    async def site_preflight(request: Request) -> Response:
        origin = request.headers.get("origin")
        return Response(
            status_code=204,
            headers={
                **_cors(origin),
                "Access-Control-Allow-Methods": "POST",
                "Access-Control-Allow-Headers": "content-type",
                "Access-Control-Max-Age": "86400",
            },
        )

    @router.post("/site/hello")
    async def site_hello(request: Request) -> JSONResponse:
        """A page with the line was opened."""
        origin = request.headers.get("origin")
        headers = _cors(origin)
        same_host(request, headers)
        try:
            body = await _json(request, HELLO_MAX)
            async with ctx.sessions() as database, database.begin():
                state = await websites.hello(database, body, origin)
        except DeskError as error:
            return JSONResponse(
                {"ok": False, "detail": str(error)}, status_code=error.status, headers=headers
            )
        return JSONResponse({"ok": True, "site": state}, headers=headers)

    @router.post("/site/lead", status_code=202)
    async def site_lead(request: Request) -> JSONResponse:
        """A visitor sent a lead form on a page with the line."""
        origin = request.headers.get("origin")
        headers = _cors(origin)
        same_host(request, headers)
        try:
            body = await _json(request, LEAD_MAX)
            async with ctx.sessions() as database, database.begin():
                filed = await websites.file_lead(database, body, origin)
        except DeskError as error:
            return JSONResponse(
                {"received": False, "detail": str(error)},
                status_code=error.status,
                headers=headers,
            )
        # A bot is told nothing it could learn from; the counters say it was turned away.
        received = filed.outcome in ("created", "repeat", "known", "blocked")
        return JSONResponse(
            {"received": received, "outcome": "received" if received else filed.outcome},
            status_code=202,
            headers=headers,
        )

    # ----- the Websites card (a signed-in manager) -----------------------------------

    @asynccontextmanager
    async def book_for(
        request: Request, response: Response, *, write: bool = False
    ) -> AsyncIterator[websites.SiteBook]:
        response.headers.update(PRIVATE)
        same_host(request, PRIVATE)
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
                yield websites.SiteBook(desk, app_url=app_url())
        except DeskError as error:
            raise HTTPException(error.status, str(error), headers=PRIVATE) from None
        except DomainError:
            raise HTTPException(401, "Sign in to see your leads.", headers=PRIVATE) from None

    # The card reads its sites again a few seconds apart while "Add website" waits for the
    # first visit; a read never writes, so the key is made by "start" (or adding a site).
    @router.get("/websites", response_model=websites.Websites)
    async def read_websites(request: Request, response: Response) -> websites.Websites:
        async with book_for(request, response) as book:
            return await book.read()

    @router.post("/websites/start", response_model=websites.Websites)
    async def start_websites(request: Request, response: Response) -> websites.Websites:
        async with book_for(request, response, write=True) as book:
            await book.source(create=True)
            return await book.read()

    @router.post("/websites", response_model=websites.Websites, status_code=201)
    async def add_website(
        command: websites.NewSite, request: Request, response: Response
    ) -> websites.Websites:
        async with book_for(request, response, write=True) as book:
            await book.add(command)
            return await book.read()

    @router.post("/websites/{site_id}/status", response_model=websites.Websites)
    async def website_status(
        site_id: UUID, command: websites.SiteStatus, request: Request, response: Response
    ) -> websites.Websites:
        async with book_for(request, response, write=True) as book:
            await book.set_status(site_id, command.status)
            return await book.read()

    @router.delete("/websites/{site_id}", response_model=websites.Websites)
    async def remove_website(
        site_id: UUID, request: Request, response: Response
    ) -> websites.Websites:
        async with book_for(request, response, write=True) as book:
            await book.remove(site_id)
            return await book.read()

    @router.post("/websites/key", response_model=websites.Websites)
    async def new_website_key(request: Request, response: Response) -> websites.Websites:
        async with book_for(request, response, write=True) as book:
            await book.rotate()
            return await book.read()

    @router.post("/websites/{site_id}/test", status_code=201)
    async def website_test_lead(
        site_id: UUID, request: Request, response: Response
    ) -> dict[str, Any]:
        """A test lead from this site, filed the way a visitor's is, under Test leads."""
        async with book_for(request, response, write=True) as book:
            lead_id = await book.test_lead(site_id, command_id=uuid4())
            return {"lead_id": str(lead_id) if lead_id else None}

    application.include_router(router)
