"""Connector endpoints for the Sales Xray CRM (/v1/lead-desk).

Google Ads lead forms post to ``/capture/{source_id}/google-ads``. The source is
the CRM's own website-form source (kind ``webhook``) labelled "Google Ads lead
form"; Google's ``google_key`` is that source's key, so no session is needed and
the source key stays the only authority, exactly as for website forms.

Meta Lead Ads live under ``/meta``: a manager connects with Meta, picks Pages and
forms, and Meta's signed webhook brings each new lead (see ``connectors.meta``). A
pull every few minutes reads the same leads, because Meta holds webhooks while an
app is in development mode (see ``connectors.meta_pull``).

Google Ads lead forms can also be connected under ``/google``: Continue with Google,
turn an account on, and Sales Xray writes its own webhook into the account's lead
forms and reads new submissions every 10 minutes (``connectors.google_ads_api``,
``connectors.google_pull``). Each account is a kind ``webhook`` source marked
``config.connector = "google_ads"``, so its leads come in through the same
``/capture/{source_id}/google-ads`` route and key check as a by-hand lead form.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import UTC, datetime
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
from ac_platform.lead_desk.connectors import (
    google_ads,
    google_pull,
    meta,
    meta_backfill,
    meta_capi,
    meta_pull,
)
from ac_platform.lead_desk.connectors import google_ads_api as gads
from ac_platform.lead_desk.intake import Intake, token_hash
from ac_platform.lead_desk.models import LeadDeskSettings, LeadSource
from ac_platform.lead_desk.store import DeskError, LeadDesk, Viewer, person_name
from ac_platform.tenancy.models import Membership, Organisation

log = logging.getLogger(__name__)
NO_STORE = {"Cache-Control": "no-store"}
PRIVATE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}
_MAX_BODY = 64 * 1024
_MAX_WEBHOOK = 256 * 1024
_MAX_SOURCES = 20


class MetaForm(BaseModel):
    id: str
    name: str
    status: str


class MetaBackfill(BaseModel):
    """Bringing in the older leads Meta still keeps (90 days) for one Page."""

    model_config = ConfigDict(populate_by_name=True)
    state: Literal["running", "done", "blocked"]
    created: int
    seen: int
    since: str | None = None
    started_at: str | None = Field(default=None, alias="startedAt")
    finished_at: str | None = Field(default=None, alias="finishedAt")
    error: str | None = None


class MetaProblem(BaseModel):
    """Why Meta last refused this Page, and what kind of fix it needs."""

    kind: Literal["token", "permission", "lead_access", "other"]
    text: str
    at: str | None = None


class MetaPage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    page_id: str = Field(alias="pageId")
    name: str
    active: bool
    forms: Literal["all"] | list[str]
    received: int
    last_received_at: str | None = Field(default=None, alias="lastReceivedAt")
    last_pulled_at: str | None = Field(default=None, alias="lastPulledAt")
    # The forms whose leads come in: every form on the Page for "all" (new ones too).
    forms_covered: list[MetaForm] = Field(default_factory=list, alias="formsCovered")
    backfill: MetaBackfill | None = None
    problem: MetaProblem | None = None


class MetaStatus(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    configured: bool
    pages: list[MetaPage]


class ConnectPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    forms: Literal["all"] | list[str] = "all"


class Connected(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    page: MetaPage
    imported: int


class BackfillStarted(BaseModel):
    """The first slice of older leads filed now; the rest follow in the background."""

    model_config = ConfigDict(populate_by_name=True)
    page: MetaPage
    imported: int


class MetaDataset(BaseModel):
    id: str
    name: str


class MetaAdAccount(BaseModel):
    id: str
    name: str


class MetaDatasets(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    ad_accounts: list[MetaAdAccount] = Field(alias="adAccounts")
    datasets: list[MetaDataset]


class NewDataset(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    ad_account_id: str = Field(alias="adAccountId", pattern=r"^act_[0-9]{5,20}$")
    name: str = Field(min_length=1, max_length=60)


class ConversionsCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    dataset_id: str = Field(alias="datasetId", pattern=r"^[0-9]{5,20}$")
    dataset_name: str = Field(alias="datasetName", min_length=1, max_length=120)
    on: bool
    events: dict[str, str | None] | None = None
    test_code: str | None = Field(default=None, alias="testCode", max_length=32)


class ConversionEventView(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: UUID
    lead_id: UUID = Field(alias="leadId")
    lead_name: str = Field(alias="leadName")
    stage: str
    event_name: str = Field(alias="eventName")
    status: str
    attempts: int
    event_time: datetime = Field(alias="eventTime")
    delivered_at: datetime | None = Field(default=None, alias="deliveredAt")
    error: str | None = None


class ConversionsView(BaseModel):
    """Lead stages going back to the organisation's Meta dataset, and how it's going."""

    model_config = ConfigDict(populate_by_name=True)
    configured: bool
    connected: bool
    connection_expires_at: str | None = Field(default=None, alias="connectionExpiresAt")
    dataset: MetaDataset | None = None
    on: bool
    events: dict[str, str | None]
    test_code: str | None = Field(default=None, alias="testCode")
    since: str | None = None
    counts: dict[str, int]
    last_delivered_at: str | None = Field(default=None, alias="lastDeliveredAt")
    waiting_on: str | None = Field(default=None, alias="waitingOn")
    recent: list[ConversionEventView]


class GoogleAccount(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    customer_id: str = Field(alias="customerId")
    name: str
    active: bool
    test: bool
    received: int
    last_received_at: str | None = Field(default=None, alias="lastReceivedAt")
    last_pulled_at: str | None = Field(default=None, alias="lastPulledAt")
    forms: int | None = None
    sending: int | None = None
    other: int | None = None
    failed: int | None = None


class GoogleStatus(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    configured: bool
    accounts: list[GoogleAccount]


class GoogleConnected(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    account: GoogleAccount
    imported: int


class GooglePull(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    account: GoogleAccount
    fetched: int
    created: int
    repeat: int
    known: int
    skipped: int


class PullResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    page: MetaPage
    fetched: int
    created: int
    repeat: int
    known: int
    skipped: int


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
        except (meta.MetaError, gads.GoogleAdsApiError) as error:
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
        forms = forms if forms == "all" or isinstance(forms, list) else "all"
        return MetaPage(
            page_id=str(config.get("page_id", "")),
            name=str(config.get("page_name") or source.label),
            active=bool(source.active),
            forms=forms,
            received=int(source.received or 0),
            last_received_at=source.last_received_at.isoformat()
            if source.last_received_at
            else None,
            last_pulled_at=_epoch_iso(config.get("last_pulled_at")),
            forms_covered=_covered(config.get("form_list"), forms),
            backfill=_backfill_view(meta_backfill.state(config)),
            problem=_problem_view(config.get("last_error")),
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
            user = await graph.user_token(code=code, redirect_uri=callback_url())
            pages = await graph.pages(user.token)
            # The organisation's own connection, sealed to it: it lists and writes the
            # datasets that lead stages go back to (Conversions API for CRM).
            row = await lead_settings(desk)
            row.config = {
                **(row.config or {}),
                meta_capi.CONNECTION: {
                    "token": meta.seal(
                        cfg.token_key,
                        user.token,
                        page_id=meta_capi.connection_bound(desk.viewer.tenant_id),
                    ),
                    "expires_at": user.expires_at,
                    "by": str(desk.viewer.person_id),
                    "at": int(time.time()),
                },
            }
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

    # ----- lead stages back to Meta (Conversions API for CRM) -------------------------

    async def lead_settings(desk: LeadDesk) -> LeadDeskSettings:
        """The workspace's Lead Desk settings row, locked; made when missing. Writing
        the Meta parts never moves the revision (not the team settings form)."""
        row = await desk.db.get(LeadDeskSettings, desk.viewer.tenant_id, with_for_update=True)
        if row is None:
            row = LeadDeskSettings(
                tenant_id=desk.viewer.tenant_id,
                revision=1,
                config={},
                updated_by_person_id=None,
                updated_at=desk.now,
            )
            desk.db.add(row)
        return row

    def connection(desk: LeadDesk, row: LeadDeskSettings | None, cfg: meta.MetaConfig) -> str:
        token = (
            meta_capi.connection_token(row.config or {}, cfg, desk.viewer.tenant_id)
            if row is not None
            else None
        )
        if token is None:
            raise DeskError(409, "Continue with Meta again, so Sales Xray can see your datasets.")
        return token

    async def conversions_view(desk: LeadDesk) -> ConversionsView:
        row = await desk.db.get(LeadDeskSettings, desk.viewer.tenant_id)
        config = (row.config if row is not None else None) or {}
        cfg = meta.config()
        chosen = meta_capi.read_settings(config)
        box = config.get(meta_capi.CONNECTION)
        facts = await meta_capi.summary(desk.db, desk.viewer.tenant_id, desk.now)
        return ConversionsView(
            configured=cfg is not None,
            connected=cfg is not None
            and meta_capi.connection_token(config, cfg, desk.viewer.tenant_id) is not None,
            connection_expires_at=_epoch_iso(box.get("expires_at"))
            if isinstance(box, dict)
            else None,
            dataset=MetaDataset(id=chosen.dataset_id, name=chosen.dataset_name) if chosen else None,
            on=bool(chosen and chosen.on),
            events=chosen.events if chosen else dict(meta_capi.DEFAULT_EVENTS),
            test_code=chosen.test_code if chosen else None,
            since=_epoch_iso(chosen.since) if chosen else None,
            counts=facts["counts"],
            last_delivered_at=facts["last_delivered_at"].isoformat()
            if facts["last_delivered_at"]
            else None,
            waiting_on=_waiting_words(facts["waiting_on"]),
            recent=[ConversionEventView(**item) for item in facts["recent"]],
        )

    @router.get("/meta/conversions", response_model=ConversionsView, response_model_by_alias=True)
    async def meta_conversions(request: Request, response: Response) -> ConversionsView:
        async with desk_for(request, response) as desk:
            desk._require_manager()
            return await conversions_view(desk)

    @router.get("/meta/datasets", response_model=MetaDatasets, response_model_by_alias=True)
    async def meta_datasets(request: Request, response: Response) -> MetaDatasets:
        """The datasets and ad accounts the organisation shared when it connected."""
        cfg = meta_config()
        async with desk_for(request, response) as desk:
            desk._require_manager()
            token = connection(
                desk, await desk.db.get(LeadDeskSettings, desk.viewer.tenant_id), cfg
            )
            graph = meta.Graph(cfg)
            return MetaDatasets(
                ad_accounts=[MetaAdAccount(**item) for item in await graph.ad_accounts(token)],
                datasets=[MetaDataset(**item) for item in await graph.datasets(token)],
            )

    @router.post("/meta/datasets", response_model=MetaDataset, status_code=201)
    async def meta_new_dataset(
        command: NewDataset, request: Request, response: Response
    ) -> MetaDataset:
        """A new dataset in one of the organisation's ad accounts."""
        cfg = meta_config()
        async with desk_for(request, response, write=True) as desk:
            desk._require_manager()
            token = connection(
                desk, await desk.db.get(LeadDeskSettings, desk.viewer.tenant_id), cfg
            )
            made = await meta.Graph(cfg).create_dataset(
                token, ad_account_id=command.ad_account_id, name=command.name.strip()
            )
            return MetaDataset(**made)

    @router.put("/meta/conversions", response_model=ConversionsView, response_model_by_alias=True)
    async def meta_save_conversions(
        command: ConversionsCommand, request: Request, response: Response
    ) -> ConversionsView:
        """Pick the dataset, name each stage's event, switch sending on or off."""
        meta_config()
        async with desk_for(request, response, write=True) as desk:
            desk._require_manager()
            row = await lead_settings(desk)
            try:
                row.config = meta_capi.saved(
                    row.config or {},
                    dataset_id=command.dataset_id,
                    dataset_name=command.dataset_name,
                    on=command.on,
                    events=command.events,
                    test_code=command.test_code or None,
                    now=int(time.time()),
                    by=desk.viewer.person_id,
                )
            except meta_capi.ConversionsError as error:
                raise DeskError(422, str(error)) from None
            await desk.db.flush()
            return await conversions_view(desk)

    @router.post(
        "/meta/conversions/{conversion_id}/retry",
        response_model=ConversionsView,
        response_model_by_alias=True,
    )
    async def meta_retry_conversion(
        conversion_id: UUID, request: Request, response: Response
    ) -> ConversionsView:
        """Send an event Meta refused once more, while it is under 7 days old."""
        async with desk_for(request, response, write=True) as desk:
            desk._require_manager()
            if not await meta_capi.retry(desk.db, desk.viewer.tenant_id, conversion_id, desk.now):
                raise DeskError(
                    409, "That event can't be sent again: it went already, or is too old."
                )
            await desk.db.flush()
            return await conversions_view(desk)

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
            await desk.db.refresh(source, with_for_update=True)
            token = meta.unseal(cfg.token_key, source.config["token"], page_id=page_id)
            graph = meta.Graph(cfg)
            await graph.require_lead_access(page_id, token)
            await graph.subscribe(page_id, token)
            # "all" (the default) reads every form on the Page each time, so a form made
            # later comes in by itself; a list keeps to the forms picked.
            forms = (
                command.forms
                if command.forms == "all"
                else [str(f)[:40] for f in command.forms][:100]
            )
            listed = await graph.forms(page_id, token)
            form_ids = [form["id"] for form in listed] if forms == "all" else forms
            now = int(time.time())
            source.config = meta_backfill.begin(
                meta_backfill.remember_forms({**source.config, "forms": forms}, listed),
                form_ids=form_ids,
                now=now,
            )
            source.active = True
            source.updated_at = desk.now
            # The last week comes in now; the rest Meta keeps (90 days) follows in the
            # background, a slice a minute (meta_backfill).
            imported = 0
            page_name = str(source.config.get("page_name") or "")
            for lead in await graph.recent_leads(
                form_ids, token, since=now - meta.PULL_DAYS * 86400
            ):
                outcome = await meta_backfill.file_lead(desk, source, lead, page_name=page_name)
                imported += outcome == "created"
            source.config = {
                **{k: v for k, v in source.config.items() if k != "last_error"},
                "last_pulled_at": now,
            }
            await desk.db.flush()
            return Connected(page=page_view(source), imported=imported)

    @router.post(
        "/meta/pages/{page_id}/backfill",
        response_model=BackfillStarted,
        response_model_by_alias=True,
    )
    async def meta_backfill_page(
        page_id: str, request: Request, response: Response
    ) -> BackfillStarted:
        """Bring in every lead Meta still keeps for this Page (90 days). Leads already
        here are skipped; the first slice is filed now and the rest in the background."""
        cfg = meta_config()
        async with desk_for(request, response, write=True) as desk:
            desk._require_manager()
            source = await page_source(desk, page_id)
            if not source.active:
                raise DeskError(409, "Turn this Page on first.")
            await desk.db.refresh(source, with_for_update=True)
            token = meta.unseal(cfg.token_key, source.config["token"], page_id=page_id)
            graph = meta.Graph(cfg)
            await graph.require_lead_access(page_id, token)
            forms = source.config.get("forms", "all")
            listed = await graph.forms(page_id, token)
            form_ids = (
                [form["id"] for form in listed]
                if forms == "all" or not isinstance(forms, list)
                else [str(form) for form in forms]
            )
            now = int(time.time())
            source.config = meta_backfill.begin(
                meta_backfill.remember_forms(source.config, listed), form_ids=form_ids, now=now
            )
            imported = await meta_backfill.step(desk, source, graph, cfg, now=now)
            source.updated_at = desk.now
            await desk.db.flush()
            return BackfillStarted(page=page_view(source), imported=imported)

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

    @router.post(
        "/meta/pages/{page_id}/pull", response_model=PullResult, response_model_by_alias=True
    )
    async def meta_pull_page(page_id: str, request: Request, response: Response) -> PullResult:
        """Fetch this Page's new leads now, without waiting for the scheduled pull."""
        cfg = meta_config()
        async with desk_for(request, response, write=True) as desk:
            desk._require_manager()
            source = await page_source(desk, page_id)
            if not source.active:
                raise DeskError(409, "Switch this Page on first: pick its forms and connect it.")
            await desk.db.refresh(source, with_for_update=True)
            counts = await meta_pull.pull_source(
                desk, source, meta.Graph(cfg), cfg, now=int(time.time())
            )
            source.updated_at = desk.now
            await desk.db.flush()
            return PullResult(page=page_view(source), **asdict(counts))

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

    # ----- Google Ads lead forms, connected ------------------------------------------

    def google_config() -> gads.GoogleAdsConfig:
        cfg = gads.config()
        if cfg is None:
            raise HTTPException(
                409,
                "Google Ads isn't set up for Sales Xray yet: AC's Google Ads app is missing.",
                headers=PRIVATE,
            )
        return cfg

    def google_callback_url() -> str:
        return f"{app_url()}/v1/lead-desk/google/callback"

    async def google_sources(desk: LeadDesk) -> list[LeadSource]:
        rows = (
            await desk.db.scalars(
                select(LeadSource)
                .where(LeadSource.tenant_id == desk.viewer.tenant_id, LeadSource.kind == "webhook")
                .order_by(LeadSource.created_at)
            )
        ).all()
        return [row for row in rows if gads.is_connector(row)]

    def account_view(source: LeadSource) -> GoogleAccount:
        config = source.config or {}
        hooks = config.get("webhooks")
        counts = (
            {
                name: int(hooks[name])
                for name in ("forms", "sending", "other", "failed")
                if isinstance(hooks.get(name), int)
            }
            if isinstance(hooks, dict)
            else {}
        )
        return GoogleAccount(
            customer_id=str(config.get("customer_id", "")),
            name=str(config.get("account_name") or source.label),
            active=bool(source.active),
            test=bool(config.get("test")),
            received=int(source.received or 0),
            last_received_at=source.last_received_at.isoformat()
            if source.last_received_at
            else None,
            last_pulled_at=_epoch_iso(config.get("last_pulled_at")),
            **counts,
        )

    async def account_source(desk: LeadDesk, customer_id: str) -> LeadSource:
        for source in await google_sources(desk):
            if str((source.config or {}).get("customer_id")) == customer_id:
                return source
        raise DeskError(
            404, "That Google Ads account isn't connected here. Continue with Google first."
        )

    @router.get("/google/status", response_model=GoogleStatus, response_model_by_alias=True)
    async def google_status(request: Request, response: Response) -> GoogleStatus:
        async with desk_for(request, response) as desk:
            desk._require_manager()
            return GoogleStatus(
                configured=gads.config() is not None,
                accounts=[account_view(source) for source in await google_sources(desk)],
            )

    @router.get("/google/connect")
    async def google_connect(request: Request, response: Response) -> RedirectResponse:
        cfg = google_config()
        async with desk_for(request, response) as desk:
            desk._require_manager()
            state = gads.make_state(
                cfg, tenant_id=desk.viewer.tenant_id, person_id=desk.viewer.person_id
            )
        return RedirectResponse(
            gads.consent_url(cfg, redirect_uri=google_callback_url(), state=state),
            status_code=303,
            headers=PRIVATE,
        )

    @router.get("/google/callback")
    async def google_callback(request: Request, response: Response) -> RedirectResponse:
        cfg = google_config()
        back = f"{app_url()}/leads?tab=sources"
        if request.query_params.get("error"):
            return RedirectResponse(f"{back}&google=cancelled", status_code=303, headers=PRIVATE)
        code = request.query_params.get("code", "")
        state = request.query_params.get("state", "")
        if not code or not state:
            return RedirectResponse(f"{back}&google=failed", status_code=303, headers=PRIVATE)
        async with desk_for(request, response, write=True, origin=False) as desk:
            desk._require_manager()
            gads.read_state(
                cfg, state, tenant_id=desk.viewer.tenant_id, person_id=desk.viewer.person_id
            )
            ads = gads.Ads(cfg)
            try:
                refresh = await ads.refresh_token(code=code, redirect_uri=google_callback_url())
                accounts = await ads.accounts(await ads.access_token(refresh))
            except gads.GoogleAdsApiError as error:
                log.warning("google ads connect failed: %s", error)
                return RedirectResponse(f"{back}&google=failed", status_code=303, headers=PRIVATE)
            existing = {
                str((s.config or {}).get("customer_id")): s for s in await google_sources(desk)
            }
            count = int(
                await desk.db.scalar(
                    select(func.count()).where(LeadSource.tenant_id == desk.viewer.tenant_id)
                )
                or 0
            )
            for account in accounts:
                details = {
                    "account_name": account.name,
                    "login_customer_id": account.login_customer_id,
                    "test": account.test,
                    "token": gads.seal(
                        cfg.token_key, refresh, customer_id=account.customer_id, what="token"
                    ),
                }
                source = existing.get(account.customer_id)
                if source is not None:
                    source.config = {**(source.config or {}), **details}
                    source.label = f"Google Ads · {account.name}"[:120]
                    source.updated_at = desk.now
                    continue
                if count >= _MAX_SOURCES:
                    break
                count += 1
                key = secrets.token_urlsafe(32)
                desk.db.add(
                    LeadSource(
                        id=uuid4(),
                        tenant_id=desk.viewer.tenant_id,
                        kind="webhook",
                        label=f"Google Ads · {account.name}"[:120],
                        token_sha256=token_hash(key),
                        config={
                            "connector": gads.CONNECTOR,
                            "customer_id": account.customer_id,
                            **details,
                            "key": gads.seal(
                                cfg.token_key, key, customer_id=account.customer_id, what="key"
                            ),
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
        found = "connected" if accounts else "noaccounts"
        return RedirectResponse(f"{back}&google={found}", status_code=303, headers=PRIVATE)

    @router.post(
        "/google/accounts/{customer_id}",
        response_model=GoogleConnected,
        response_model_by_alias=True,
    )
    async def google_turn_on(
        customer_id: str, request: Request, response: Response
    ) -> GoogleConnected:
        """Write Sales Xray's webhook into the account's lead forms; bring in the last 30 days."""
        cfg = google_config()
        async with desk_for(request, response, write=True) as desk:
            desk._require_manager()
            source = await account_source(desk, customer_id)
            await desk.db.refresh(source, with_for_update=True)
            ads = gads.Ads(cfg)
            await google_pull.ensure_webhooks(source, ads, cfg, app_url=app_url())
            source.active = True
            source.updated_at = desk.now
            counts = await google_pull.pull_source(desk, source, ads, cfg, now=int(time.time()))
            await desk.db.flush()
            return GoogleConnected(account=account_view(source), imported=counts.created)

    @router.post(
        "/google/accounts/{customer_id}/disconnect",
        response_model=GoogleAccount,
        response_model_by_alias=True,
    )
    async def google_switch_off(
        customer_id: str, request: Request, response: Response
    ) -> GoogleAccount:
        """No new leads from this account. Its forms keep the address; their posts are refused
        while it is off, and turning it on again brings in what was missed (30 days)."""
        async with desk_for(request, response, write=True) as desk:
            desk._require_manager()
            source = await account_source(desk, customer_id)
            source.active = False
            source.updated_at = desk.now
            await desk.db.flush()
            return account_view(source)

    @router.post(
        "/google/accounts/{customer_id}/pull",
        response_model=GooglePull,
        response_model_by_alias=True,
    )
    async def google_check_now(
        customer_id: str, request: Request, response: Response
    ) -> GooglePull:
        """Fetch this account's new leads now, and point any new lead forms at Sales Xray."""
        cfg = google_config()
        async with desk_for(request, response, write=True) as desk:
            desk._require_manager()
            source = await account_source(desk, customer_id)
            if not source.active:
                raise DeskError(409, "Turn this account on first.")
            await desk.db.refresh(source, with_for_update=True)
            ads = gads.Ads(cfg)
            await google_pull.ensure_webhooks(source, ads, cfg, app_url=app_url())
            counts = await google_pull.pull_source(desk, source, ads, cfg, now=int(time.time()))
            source.updated_at = desk.now
            await desk.db.flush()
            return GooglePull(account=account_view(source), **asdict(counts))

    application.include_router(router)
    meta_pull.attach(application, ctx.sessions, settings.environment)
    meta_capi.attach(application, ctx.sessions, settings.environment)
    google_pull.attach(application, ctx.sessions, settings.environment)


def _epoch_iso(value: object) -> str | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return datetime.fromtimestamp(value, UTC).isoformat()
    return None


def _waiting_words(code: str | None) -> str | None:
    """Why events wait on the customer, in words, or None when nothing waits on them."""
    if code in ("meta_190", "meta_102", "not_connected"):
        return "Meta ended the connection. Continue with Meta again to keep sending stages."
    permission = code in ("meta_10", "meta_3") or (
        code is not None and code.startswith("meta_2") and len(code) == 8
    )
    if permission:
        return (
            "Meta didn't allow sending to this dataset. Continue with Meta again and allow "
            "your ad account and dataset."
        )
    return None


def _covered(form_list: object, forms: object) -> list[MetaForm]:
    """The forms whose leads come in, from the Page's last known list of forms."""
    known = [
        MetaForm(
            id=str(item["id"]),
            name=str(item.get("name") or item["id"]),
            status=str(item.get("status") or ""),
        )
        for item in (form_list if isinstance(form_list, list) else [])
        if isinstance(item, dict) and item.get("id")
    ]
    if forms == "all" or not isinstance(forms, list):
        return known
    picked = {str(form) for form in forms}
    return [form for form in known if form.id in picked]


def _backfill_view(state: dict[str, Any] | None) -> MetaBackfill | None:
    if state is None or state.get("state") not in ("running", "done", "blocked"):
        return None
    return MetaBackfill(
        state=state["state"],
        created=int(state.get("created") or 0),
        seen=int(state.get("seen") or 0),
        since=_epoch_iso(state.get("since")),
        started_at=_epoch_iso(state.get("started_at")),
        finished_at=_epoch_iso(state.get("finished_at")),
        error=str(state["error"])[:300] if state.get("error") else None,
    )


def _problem_view(value: object) -> MetaProblem | None:
    if not isinstance(value, dict) or not value.get("text"):
        return None
    kind = value.get("kind")
    return MetaProblem(
        kind=kind if kind in ("token", "permission", "lead_access") else "other",
        text=str(value["text"])[:300],
        at=_epoch_iso(value.get("at")),
    )


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
