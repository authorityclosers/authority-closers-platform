"""Connector endpoints for the Sales Xray CRM (/v1/lead-desk).

Google Ads lead forms post to ``/capture/{source_id}/google-ads``. The source is
the CRM's own website-form source (kind ``webhook``) labelled "Google Ads lead
form"; Google's ``google_key`` is that source's key, so no session is needed and
the source key stays the only authority, exactly as for website forms.

Meta Lead Ads live under ``/meta``: a manager connects with Meta, picks Pages and
forms, and Meta's signed webhook brings each new lead (see ``connectors.meta``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from starlette.requests import ClientDisconnect

from ac_platform.conversation_intelligence.sales_xray_tenants import SALES_XRAY_MEMBER_ROLES
from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
)
from ac_platform.http.auth import require_safe_origin
from ac_platform.http.routes import RouteContext
from ac_platform.identity.models import Person
from ac_platform.kernel.errors import DomainError
from ac_platform.lead_desk.connectors import google_ads, meta
from ac_platform.lead_desk.intake import Intake
from ac_platform.lead_desk.models import LeadSource
from ac_platform.lead_desk.store import DeskError, LeadDesk, Viewer, person_name
from ac_platform.tenancy.models import Membership, Organisation

log = logging.getLogger(__name__)
NO_STORE = {"Cache-Control": "no-store"}
PRIVATE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}
_MAX_BODY = 64 * 1024
_MAX_WEBHOOK = 256 * 1024
_MAX_SOURCES = 20


class MetaPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    page_id: str = Field(alias="pageId")
    name: str
    active: bool
    forms: Literal["all"] | list[str]
    received: int
    last_received_at: str | None = Field(default=None, alias="lastReceivedAt")


class MetaStatus(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    configured: bool
    pages: list[MetaPage]


class MetaForm(BaseModel):
    id: str
    name: str
    status: str


class ConnectPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    forms: Literal["all"] | list[str] = "all"


class Connected(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    page: MetaPage
    imported: int


def install_connectors_http(application: FastAPI, ctx: RouteContext) -> None:
    router = APIRouter(prefix="/v1/lead-desk", tags=["lead-desk"])
    settings = ctx.settings
    read_actor = getattr(ctx.require_actor, "read_only", ctx.require_actor)

    def app_url() -> str:
        return str(settings.sales_xray_app_url or "").rstrip("/")

    def same_host(request: Request) -> None:
        if (
            settings.sales_xray_app_url is None
            or request.url.hostname != settings.sales_xray_app_url.host
        ):
            raise HTTPException(404, "Leads are unavailable here.", headers=NO_STORE)

    def meta_config() -> meta.MetaConfig:
        cfg = meta.config()
        if cfg is None:
            raise HTTPException(
                409,
                "Meta isn't set up for Sales Xray yet: AC's Meta app is missing.",
                headers=PRIVATE,
            )
        return cfg

    def callback_url() -> str:
        return f"{app_url()}/v1/lead-desk/meta/callback"

    # The same workspace rule as the CRM's own routes: a signed-in member of an
    # organisation workspace. ``origin`` is off only for Meta's redirect back, which a
    # browser makes as a top-level navigation; the signed state guards that one.
    @asynccontextmanager
    async def desk_for(
        request: Request, response: Response, *, write: bool = False, origin: bool = True
    ) -> AsyncIterator[LeadDesk]:
        response.headers.update(PRIVATE)
        same_host(request)
        if write and origin:
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
                sandbox = (
                    await auth.database.scalar(
                        select(ConversationSandboxOrganisation.tenant_id).where(
                            ConversationSandboxOrganisation.tenant_id == tenant_id
                        )
                    )
                ) is not None
                yield LeadDesk(
                    auth.database,
                    Viewer(
                        person_id=actor.person_id,
                        tenant_id=tenant_id,
                        role=row[0],
                        name=person_name(row[1]),
                    ),
                    call_mode="simulated",
                    sandbox=sandbox,
                )
        except DeskError as error:
            raise HTTPException(error.status, str(error), headers=PRIVATE) from None
        except meta.MetaError as error:
            raise HTTPException(502, str(error), headers=PRIVATE) from None
        except DomainError:
            raise HTTPException(401, "Sign in to see your leads.", headers=PRIVATE) from None

    # ----- Google Ads lead forms ------------------------------------------------------

    @router.post("/capture/{source_id}/google-ads")
    async def google_ads_lead(
        source_id: UUID, request: Request, response: Response
    ) -> dict[str, Any]:
        """Google Ads sends one lead form submission. No cookie, no session."""
        response.headers.update(NO_STORE)
        same_host(request)
        payload = _json_object(await _body(request, _MAX_BODY))
        try:
            token = google_ads.google_key(payload)
            record = google_ads.to_record(payload)
        except google_ads.GoogleAdsError as error:
            raise HTTPException(422, str(error), headers=NO_STORE) from None
        try:
            async with ctx.sessions() as database, database.begin():
                lead_id, outcome = await Intake.capture(
                    database, source_id, token, record, app_url=app_url()
                )
        except DeskError as error:
            raise HTTPException(error.status, str(error), headers=NO_STORE) from None
        return {"received": outcome != "skipped", "outcome": outcome, "lead_id": lead_id}

    # ----- Meta Lead Ads --------------------------------------------------------------

    async def meta_sources(desk: LeadDesk) -> list[LeadSource]:
        return list(
            (
                await desk.db.scalars(
                    select(LeadSource)
                    .where(LeadSource.tenant_id == desk.viewer.tenant_id, LeadSource.kind == "meta")
                    .order_by(LeadSource.created_at)
                )
            ).all()
        )

    def page_view(source: LeadSource) -> MetaPage:
        config = source.config or {}
        forms = config.get("forms", "all")
        return MetaPage(
            page_id=str(config.get("page_id", "")),
            name=str(config.get("page_name") or source.label),
            active=bool(source.active),
            forms=forms if forms == "all" or isinstance(forms, list) else "all",
            received=int(source.received or 0),
            last_received_at=source.last_received_at.isoformat()
            if source.last_received_at
            else None,
        )

    async def page_source(desk: LeadDesk, page_id: str) -> LeadSource:
        for source in await meta_sources(desk):
            if str((source.config or {}).get("page_id")) == page_id:
                return source
        raise DeskError(
            404, "That Page isn't connected to this workspace. Continue with Meta first."
        )

    @router.get("/meta/status", response_model=MetaStatus, response_model_by_alias=True)
    async def meta_status(request: Request, response: Response) -> MetaStatus:
        async with desk_for(request, response) as desk:
            desk._require_manager()
            return MetaStatus(
                configured=meta.config() is not None,
                pages=[page_view(source) for source in await meta_sources(desk)],
            )

    @router.get("/meta/connect")
    async def meta_connect(request: Request, response: Response) -> RedirectResponse:
        cfg = meta_config()
        async with desk_for(request, response) as desk:
            desk._require_manager()
            state = meta.make_state(
                cfg.app_secret, tenant_id=desk.viewer.tenant_id, person_id=desk.viewer.person_id
            )
        return RedirectResponse(
            meta.dialog_url(cfg, redirect_uri=callback_url(), state=state),
            status_code=303,
            headers=PRIVATE,
        )

    @router.get("/meta/callback")
    async def meta_callback(request: Request, response: Response) -> RedirectResponse:
        cfg = meta_config()
        back = f"{app_url()}/leads?tab=sources"
        if request.query_params.get("error"):
            return RedirectResponse(f"{back}&meta=cancelled", status_code=303, headers=PRIVATE)
        code = request.query_params.get("code", "")
        state = request.query_params.get("state", "")
        if not code or not state:
            return RedirectResponse(f"{back}&meta=failed", status_code=303, headers=PRIVATE)
        async with desk_for(request, response, write=True, origin=False) as desk:
            desk._require_manager()
            meta.read_state(
                cfg.app_secret,
                state,
                tenant_id=desk.viewer.tenant_id,
                person_id=desk.viewer.person_id,
            )
            graph = meta.Graph(cfg)
            user_token = await graph.user_token(code=code, redirect_uri=callback_url())
            pages = await graph.pages(user_token)
            existing = {str((s.config or {}).get("page_id")): s for s in await meta_sources(desk)}
            count = int(
                await desk.db.scalar(
                    select(func.count()).where(LeadSource.tenant_id == desk.viewer.tenant_id)
                )
                or 0
            )
            for page in pages:
                sealed = meta.seal(cfg.token_key, page["token"], page_id=page["id"])
                source = existing.get(page["id"])
                if source is not None:
                    source.config = {
                        **(source.config or {}),
                        "page_name": page["name"],
                        "token": sealed,
                    }
                    source.label = f"Meta · {page['name']}"[:120]
                    source.updated_at = desk.now
                    continue
                if count >= _MAX_SOURCES:
                    break
                count += 1
                desk.db.add(
                    LeadSource(
                        id=uuid4(),
                        tenant_id=desk.viewer.tenant_id,
                        kind="meta",
                        label=f"Meta · {page['name']}"[:120],
                        token_sha256=None,
                        config={
                            "page_id": page["id"],
                            "page_name": page["name"],
                            "token": sealed,
                            "forms": "all",
                        },
                        active=False,
                        received=0,
                        created_by_person_id=desk.viewer.person_id,
                        created_at=desk.now,
                        updated_at=desk.now,
                    )
                )
            await desk.db.flush()
        found = "connected" if pages else "nopages"
        return RedirectResponse(f"{back}&meta={found}", status_code=303, headers=PRIVATE)

    @router.get("/meta/pages/{page_id}/forms", response_model=list[MetaForm])
    async def meta_forms(page_id: str, request: Request, response: Response) -> list[MetaForm]:
        cfg = meta_config()
        async with desk_for(request, response) as desk:
            desk._require_manager()
            source = await page_source(desk, page_id)
            token = meta.unseal(cfg.token_key, source.config["token"], page_id=page_id)
            return [MetaForm(**form) for form in await meta.Graph(cfg).forms(page_id, token)]

    @router.post("/meta/pages/{page_id}", response_model=Connected, response_model_by_alias=True)
    async def meta_connect_page(
        page_id: str, command: ConnectPage, request: Request, response: Response
    ) -> Connected:
        cfg = meta_config()
        async with desk_for(request, response, write=True) as desk:
            desk._require_manager()
            source = await page_source(desk, page_id)
            token = meta.unseal(cfg.token_key, source.config["token"], page_id=page_id)
            graph = meta.Graph(cfg)
            await graph.subscribe(page_id, token)
            forms = (
                command.forms
                if command.forms == "all"
                else [str(f)[:40] for f in command.forms][:100]
            )
            source.config = {**source.config, "forms": forms}
            source.active = True
            source.updated_at = desk.now
            form_ids = (
                [form["id"] for form in await graph.forms(page_id, token)]
                if forms == "all"
                else forms
            )
            since = int(time.time()) - meta.BACKFILL_DAYS * 86400
            imported = 0
            for lead in await graph.recent_leads(form_ids, token, since=since):
                _, outcome = await desk.ingest(
                    meta.lead_record(lead, page_name=str(source.config.get("page_name") or "")),
                    source="meta",
                    source_label=source.label,
                    source_ref=str(lead.get("id") or "")[:200] or None,
                    actor=None,
                )
                if outcome == "created":
                    imported += 1
                    source.received += 1
                    source.last_received_at = desk.now
            await desk.db.flush()
            return Connected(page=page_view(source), imported=imported)

    @router.post(
        "/meta/pages/{page_id}/disconnect", response_model=MetaPage, response_model_by_alias=True
    )
    async def meta_disconnect(page_id: str, request: Request, response: Response) -> MetaPage:
        cfg = meta_config()
        async with desk_for(request, response, write=True) as desk:
            desk._require_manager()
            source = await page_source(desk, page_id)
            try:
                token = meta.unseal(cfg.token_key, source.config["token"], page_id=page_id)
                await meta.Graph(cfg).unsubscribe(page_id, token)
            except meta.MetaError:
                pass  # Already gone at Meta's end; switching it off here is what matters.
            source.active = False
            source.updated_at = desk.now
            await desk.db.flush()
            return page_view(source)

    @router.get("/meta/webhook", response_class=PlainTextResponse)
    async def meta_verify(request: Request) -> PlainTextResponse:
        """Meta checks the callback address once when the webhook is set up."""
        same_host(request)
        cfg = meta_config()
        params = request.query_params
        if (
            params.get("hub.mode") == "subscribe"
            and params.get("hub.verify_token") == cfg.verify_token
            and params.get("hub.challenge")
        ):
            return PlainTextResponse(params["hub.challenge"][:200], headers=NO_STORE)
        raise HTTPException(403, "Unknown verify token.", headers=NO_STORE)

    @router.post("/meta/webhook")
    async def meta_webhook(request: Request) -> dict[str, Any]:
        """Meta's signed notice of new leads. No cookie, no session; the app secret signs it."""
        same_host(request)
        cfg = meta_config()
        raw = await _body(request, _MAX_WEBHOOK)
        if not meta.signature_ok(cfg.app_secret, raw, request.headers.get("x-hub-signature-256")):
            raise HTTPException(401, "Bad signature.", headers=NO_STORE)
        events = meta.lead_events(_json_object(raw))
        filed = 0
        graph = meta.Graph(cfg)
        for event in events:
            try:
                async with ctx.sessions() as database, database.begin():
                    sources = (
                        await database.scalars(
                            select(LeadSource)
                            .where(LeadSource.kind == "meta", LeadSource.active.is_(True))
                            .with_for_update()
                        )
                    ).all()
                    for source in sources:
                        config = source.config or {}
                        if str(config.get("page_id")) != event.page_id:
                            continue
                        if not meta.wants_form(config.get("forms"), event.form_id):
                            continue
                        token = meta.unseal(cfg.token_key, config["token"], page_id=event.page_id)
                        lead = await graph.lead(event.leadgen_id, token)
                        desk = LeadDesk(
                            database,
                            Viewer(
                                person_id=source.created_by_person_id,
                                tenant_id=source.tenant_id,
                                role="system",
                                name=source.label,
                            ),
                        )
                        _, outcome = await desk.ingest(
                            meta.lead_record(lead, page_name=str(config.get("page_name") or "")),
                            source="meta",
                            source_label=source.label,
                            source_ref=event.leadgen_id[:200],
                            actor=None,
                        )
                        if outcome in {"created", "repeat"}:
                            source.received += 1
                            source.last_received_at = desk.now
                            filed += 1
                    await database.flush()
            except (meta.MetaError, DeskError) as error:
                # Meta retries a delivery that fails; one bad lead must not block the rest.
                log.warning("meta lead %s not filed: %s", event.leadgen_id, error)
        return {"received": len(events), "filed": filed}

    application.include_router(router)


async def _body(request: Request, limit: int) -> bytes:
    raw = bytearray()
    try:
        async with asyncio.timeout(15):
            async for chunk in request.stream():
                if len(raw) + len(chunk) > limit:
                    raise HTTPException(413, "That's too large to send.", headers=NO_STORE)
                raw.extend(chunk)
    except (TimeoutError, ClientDisconnect):
        raise HTTPException(408, "The upload stopped. Try again.", headers=NO_STORE) from None
    return bytes(raw)


def _json_object(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise HTTPException(422, "Send the lead as JSON.", headers=NO_STORE) from None
    if not isinstance(value, dict):
        raise HTTPException(422, "Send one lead as a JSON object.", headers=NO_STORE)
    return value
