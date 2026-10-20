"""WhatsApp and first-response routes for the Sales Xray CRM (/v1/lead-desk).

- ``/whatsapp/*``: connect the organisation's own number (Embedded Signup's code),
  auto replies, templates, the inbox, and Meta's signed webhook.
- ``/leads/{id}/whatsapp``: one lead's conversation, sending (24-hour window and
  opt-in rules), and the seller's record of the person's yes.
- ``/sla`` and ``/reports/sla``: the first-response target and how the team is doing.

Same workspace rule as the CRM's own routes: a signed-in member of an organisation
workspace; managers (owners and admins) set things up, sellers see their own leads.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal
from uuid import UUID

import structlog
from fastapi import APIRouter, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from ac_platform.conversation_intelligence.sales_xray_tenants import SALES_XRAY_MEMBER_ROLES
from ac_platform.http.auth import require_safe_origin
from ac_platform.http.routes import RouteContext
from ac_platform.identity.models import Person
from ac_platform.kernel.errors import DomainError
from ac_platform.lead_desk import sla
from ac_platform.lead_desk.chats import reads as chat_reads
from ac_platform.lead_desk.connectors import app_return, meta
from ac_platform.lead_desk.connectors.app_return import AppComplete, AppCompleted
from ac_platform.lead_desk.models import LeadDeskSettings, LeadWhatsAppNumber, LeadWhatsAppTemplate
from ac_platform.lead_desk.social import inbox as social_inbox
from ac_platform.lead_desk.store import DeskError, LeadDesk, Viewer, person_name
from ac_platform.lead_desk.whatsapp import cloud, inbox, runner
from ac_platform.tenancy.models import Membership, Organisation

log = logging.getLogger(__name__)
events = structlog.get_logger(__name__)


def signup_log(outcome: str, params: Any = None, *, detail: str | None = None) -> None:
    """Each Embedded Signup outcome in the journal (structlog: the stdlib logger's lines
    don't reach it): Meta's own error words when it sent any, never a code or a token."""
    found = params if params is not None else {}

    def part(name: str, limit: int) -> str | None:
        return " ".join(str(found.get(name) or "").split())[:limit] or None

    events.info(
        "lead_desk_whatsapp_signup",
        outcome=outcome,
        error=part("error", 60),
        reason=part("error_reason", 60),
        meta_code=part("error_code", 12),
        meta_said=part("error_description", 200) or part("error_message", 200),
        detail=" ".join((detail or "").split())[:200] or None,
    )


PRIVATE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}
NO_STORE = {"Cache-Control": "no-store"}
_MAX_WEBHOOK = 3 * 1024 * 1024  # Meta sends up to 3 MB


class _Command(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)


class FirstReply(_Command):
    on: bool = False
    template: str | None = Field(default=None, max_length=512)
    language: str | None = Field(default=None, max_length=16)
    consent_question: str | None = Field(default=None, alias="consentQuestion", max_length=200)


class OutOfHours(_Command):
    on: bool = False
    text: str | None = Field(default=None, max_length=1000)


class AutoReplies(_Command):
    first_reply: FirstReply = Field(default_factory=FirstReply, alias="firstReply")
    out_of_hours: OutOfHours = Field(default_factory=OutOfHours, alias="outOfHours")


class NumberView(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: UUID
    display_number: str = Field(alias="displayNumber")
    verified_name: str | None = Field(default=None, alias="verifiedName")
    quality: str | None = None
    auto_replies: AutoReplies = Field(alias="autoReplies")


class TemplateView(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    name: str
    language: str
    category: str
    status: str
    text: str
    parts: int
    rejected_reason: str | None = Field(default=None, alias="rejectedReason")


class WhatsAppStatus(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    configured: bool
    app_id: str | None = Field(default=None, alias="appId")
    config_id: str | None = Field(default=None, alias="configId")
    graph_version: str | None = Field(default=None, alias="graphVersion")
    numbers: list[NumberView]
    templates: list[TemplateView]


class ConnectCommand(_Command):
    code: str = Field(min_length=4, max_length=2000)
    waba_id: str = Field(alias="wabaId", pattern=r"^[0-9]{5,32}$")
    phone_number_id: str = Field(alias="phoneNumberId", pattern=r"^[0-9]{5,32}$")


class NewTemplate(_Command):
    name: str = Field(pattern=r"^[a-z0-9_]{1,512}$")
    language: str = Field(pattern=r"^[a-z]{2,3}(_[A-Z]{2})?$")
    category: Literal["MARKETING", "UTILITY"]
    body: str = Field(min_length=1, max_length=1024)
    example: list[str] = Field(default_factory=list, max_length=10)


class MessageView(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: UUID
    direction: Literal["in", "out"]
    kind: str
    text: str | None = None
    template: str | None = None
    status: str
    error: str | None = None
    auto: str | None = None
    at: datetime
    by: str | None = None


class ConversationView(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    configured: bool
    connected: bool
    numbers: list[NumberView]
    messages: list[MessageView]
    window_open: bool = Field(alias="windowOpen")
    window_closes_at: datetime | None = Field(default=None, alias="windowClosesAt")
    opted_in: bool = Field(alias="optedIn")
    opt_in_how: str | None = Field(default=None, alias="optInHow")
    templates: list[TemplateView]


class SendCommand(_Command):
    command_id: UUID = Field(alias="commandId")
    number_id: UUID | None = Field(default=None, alias="numberId")
    text: str | None = Field(default=None, max_length=4096)
    template: str | None = Field(default=None, max_length=512)
    language: str | None = Field(default=None, max_length=16)
    values: list[str] = Field(default_factory=list, max_length=10)


class OptInCommand(_Command):
    command_id: UUID = Field(alias="commandId")
    agreed: bool
    how: str = Field(default="", max_length=200)


class ThreadView(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    lead_id: UUID | None = Field(default=None, alias="leadId")
    lead_name: str = Field(alias="leadName")
    last_text: str | None = Field(default=None, alias="lastText")
    last_at: datetime = Field(alias="lastAt")
    waiting: bool
    window_open: bool = Field(alias="windowOpen")
    # For the Chats screen; read as optional by older pages.
    account_id: UUID | None = Field(default=None, alias="accountId")
    place: str | None = None
    last_kind: str = Field(default="text", alias="lastKind")
    last_direction: str = Field(default="in", alias="lastDirection")
    last_status: str = Field(default="received", alias="lastStatus")
    waiting_since: datetime | None = Field(default=None, alias="waitingSince")
    window_closes_at: datetime | None = Field(default=None, alias="windowClosesAt")
    owner_id: UUID | None = Field(default=None, alias="ownerId")
    owner_name: str | None = Field(default=None, alias="ownerName")


class ChatThreadView(ThreadView):
    """One conversation on the Chats screen, whichever channel it is on."""

    key: str  # the channel, the account and a hash of the person's id: stable, opaque
    channel: Literal["whatsapp", "messenger", "instagram"]
    # Their messages this person hasn't read yet, on any device (read marks, 0113).
    unread: int = 0


class ChatsSla(BaseModel):
    on: bool
    minutes: int


class ChatsView(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    generated_at: datetime = Field(alias="generatedAt")
    sla: ChatsSla
    threads: list[ChatThreadView]


CHATS_LIMIT = 200


def _person_key(*parts: object) -> str:
    return hashlib.sha256(":".join(str(part) for part in parts).encode()).hexdigest()[:16]


class SlaView(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    on: bool
    minutes: int
    alert_managers: bool = Field(alias="alertManagers")
    targets: list[int]


class SlaCommand(_Command):
    on: bool
    minutes: int
    alert_managers: bool = Field(default=False, alias="alertManagers")


class SellerSlaView(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    person_id: UUID | None = Field(default=None, alias="personId")
    name: str
    leads: int
    in_time: int = Field(alias="inTime")
    breached: int
    waiting: int
    median_minutes: int | None = Field(default=None, alias="medianMinutes")


class LateView(BaseModel):
    """A lead waiting for a person past the target right now."""

    model_config = ConfigDict(populate_by_name=True)
    lead_id: UUID = Field(alias="leadId")
    lead_name: str = Field(alias="leadName")
    seller: str
    minutes_late: int = Field(alias="minutesLate")


class SlaReport(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    settings: SlaView
    start: date
    end: date
    sellers: list[SellerSlaView]
    late: list[LateView] = Field(default_factory=list)


# The Settings → Connected apps card a WhatsApp connect can come back to.
WHATSAPP_CARDS: tuple[str, ...] = ("whatsapp",)


def install_whatsapp_http(application: FastAPI, ctx: RouteContext) -> None:
    router = APIRouter(prefix="/v1/lead-desk", tags=["lead-desk"])
    settings = ctx.settings
    read_actor = getattr(ctx.require_actor, "read_only", ctx.require_actor)

    def same_host(request: Request) -> None:
        if (
            settings.sales_xray_app_url is None
            or request.url.hostname != settings.sales_xray_app_url.host
        ):
            raise HTTPException(404, "Leads are unavailable here.", headers=NO_STORE)

    def whatsapp_config() -> cloud.WhatsAppConfig:
        cfg = cloud.config()
        if cfg is None:
            raise HTTPException(
                409,
                "WhatsApp isn't set up for Sales Xray yet: AC's WhatsApp app is missing.",
                headers=PRIVATE,
            )
        return cfg

    @asynccontextmanager
    async def desk_for(
        request: Request, response: Response, *, write: bool = False, origin: bool = True
    ) -> AsyncIterator[LeadDesk]:
        response.headers.update(PRIVATE)
        same_host(request)
        # ``origin`` is off only for Meta's redirect back, a top-level navigation that
        # the signed state guards.
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
                yield LeadDesk(
                    auth.database,
                    Viewer(
                        person_id=actor.person_id,
                        tenant_id=tenant_id,
                        role=row[0],
                        name=person_name(row[1]),
                    ),
                )
        except DeskError as error:
            raise HTTPException(error.status, str(error), headers=PRIVATE) from None
        except cloud.WhatsAppError as error:
            raise HTTPException(502, str(error), headers=PRIVATE) from None
        except DomainError:
            raise HTTPException(401, "Sign in to see your leads.", headers=PRIVATE) from None

    def template_view(template: Any) -> TemplateView:
        body = cloud.template_text(template.components)
        return TemplateView(
            name=template.name,
            language=template.language,
            category=template.category,
            status=template.status,
            text=body,
            parts=cloud.placeholders(body),
            rejected_reason=template.rejected_reason,
        )

    def number_view(row: LeadWhatsAppNumber) -> NumberView:
        rules = inbox.number_config(row)
        return NumberView(
            id=row.id,
            display_number=row.display_number,
            verified_name=row.verified_name,
            quality=row.quality,
            auto_replies=AutoReplies(
                first_reply=FirstReply(
                    on=rules["first_reply"]["on"],
                    template=rules["first_reply"]["template"],
                    language=rules["first_reply"]["language"],
                    consent_question=rules["first_reply"]["consent_question"],
                ),
                out_of_hours=OutOfHours(
                    on=rules["out_of_hours"]["on"], text=rules["out_of_hours"]["text"]
                ),
            ),
        )

    async def status_view(desk: LeadDesk) -> WhatsAppStatus:
        cfg = cloud.config()
        rows = await inbox.numbers(desk.db, desk.tenant_id)
        templates: list[LeadWhatsAppTemplate] = []
        for row in rows:
            templates.extend(
                (
                    await desk.db.scalars(
                        select(LeadWhatsAppTemplate)
                        .where(
                            LeadWhatsAppTemplate.tenant_id == desk.tenant_id,
                            LeadWhatsAppTemplate.waba_id == row.waba_id,
                        )
                        .order_by(LeadWhatsAppTemplate.name, LeadWhatsAppTemplate.language)
                    )
                ).all()
            )
        unique = {(t.waba_id, t.name, t.language): t for t in templates}
        return WhatsAppStatus(
            configured=cfg is not None,
            app_id=cfg.app_id if cfg else None,
            config_id=cfg.config_id if cfg else None,
            graph_version=cfg.graph_version if cfg else None,
            numbers=[number_view(row) for row in rows],
            templates=[template_view(t) for t in unique.values()],
        )

    @router.get("/whatsapp/status", response_model=WhatsAppStatus, response_model_by_alias=True)
    async def whatsapp_status(request: Request, response: Response) -> WhatsAppStatus:
        async with desk_for(request, response) as desk:
            desk._require_manager()
            return await status_view(desk)

    def app_url() -> str:
        return str(settings.sales_xray_app_url or "").rstrip("/")

    def callback_url() -> str:
        return f"{app_url()}/v1/lead-desk/whatsapp/callback"

    @router.get("/whatsapp/start", response_model=None)
    async def whatsapp_start(
        request: Request,
        response: Response,
        app_challenge: str | None = Query(default=None),
        reply: str | None = Query(default=None, alias="format"),
        return_to: str | None = Query(default=None),
        card: str | None = Query(default=None),
    ) -> Response:
        """Connect WhatsApp: off to Meta's Embedded Signup, back to the callback. From
        the Sales Xray app, with ``app_challenge``, it finishes in the app (app_return);
        from Settings → Connected apps, with ``return_to``, it comes back there."""
        cfg = whatsapp_config()
        if app_challenge is not None and not app_return.CHALLENGE.fullmatch(app_challenge):
            raise HTTPException(422, "Start again from the Sales Xray app.", headers=PRIVATE)
        try:
            settings_card = app_return.settings_card(return_to, card, allowed=WHATSAPP_CARDS)
        except ValueError:
            raise HTTPException(422, "Start again from Settings.", headers=PRIVATE) from None
        async with desk_for(request, response) as desk:
            desk._require_manager()
            state = meta.make_state(
                cfg.app_secret,
                tenant_id=desk.tenant_id,
                person_id=desk.viewer.person_id,
                app_challenge=app_challenge,
                card=settings_card,
            )
        url = cloud.dialog_url(cfg, redirect_uri=callback_url(), state=state)
        if reply == "json":
            return JSONResponse({"url": url}, headers=PRIVATE)
        return RedirectResponse(url, status_code=303, headers=PRIVATE)

    async def finish_whatsapp(desk: LeadDesk, cfg: cloud.WhatsAppConfig, code: str) -> str:
        """Swap Embedded Signup's code and connect every number the customer shared."""
        api = cloud.Cloud(cfg)
        try:
            token = await api.exchange(code, redirect_uri=callback_url())
            rows = await inbox.connect_shared(desk, cfg, api, token)
        except (HTTPException, cloud.WhatsAppError) as error:
            signup_log("failed", detail=str(getattr(error, "detail", None) or error))
            raise
        signup_log("connected" if rows else "nonumbers")
        for row in rows:
            try:
                await inbox.sync_templates(desk.db, cfg, api, row, now=desk.now)
            except cloud.WhatsAppError as error:
                log.warning("whatsapp templates not synced on connect: %s", error)
        return "connected" if rows else "nonumbers"

    @router.post("/whatsapp/app-complete", response_model=AppCompleted)
    async def whatsapp_app_complete(
        command: AppComplete, request: Request, response: Response
    ) -> AppCompleted:
        """The app is back from Meta: finish connecting WhatsApp on this person's session."""
        cfg = whatsapp_config()
        async with desk_for(request, response, write=True) as desk:
            desk._require_manager()
            try:
                code, state = app_return.open_(cfg.token_key, command.handoff, provider="whatsapp")
            except app_return.HandoffError as error:
                raise DeskError(422, str(error)) from None
            try:
                body = meta.read_state(
                    cfg.app_secret, state, tenant_id=desk.tenant_id, person_id=desk.viewer.person_id
                )
            except meta.MetaError as error:
                raise DeskError(403, str(error)) from None
            if not app_return.answers(body.get("a"), command.verifier):
                raise DeskError(403, "That didn't come from this app. Connect again.")
            return AppCompleted(result=await finish_whatsapp(desk, cfg, code))

    @router.get("/whatsapp/callback", response_model=None)
    async def whatsapp_callback(request: Request, response: Response) -> Response:
        """Meta's Embedded Signup came back: connect every number the customer shared."""
        cfg = whatsapp_config()
        state_value = request.query_params.get("state", "")
        try:
            peeked = meta.peek_state(cfg.app_secret, state_value)
        except meta.MetaError:
            peeked = {}
        app_started = bool(peeked.get("a"))
        card = app_return.card_of(peeked, WHATSAPP_CARDS)
        if app_started:
            # In the phone's browser, with no Sales Xray session: hand back to the app.
            params = request.query_params
            if params.get("error"):
                signup_log("cancelled", params)
                return app_return.return_page("whatsapp", result="cancelled")
            if not params.get("code"):
                signup_log("failed", params, detail="no code from Meta")
                return app_return.return_page("whatsapp", result="failed")
            return app_return.return_page(
                "whatsapp",
                handoff=app_return.seal(
                    cfg.token_key,
                    provider="whatsapp",
                    code=params["code"][:2048],
                    state=state_value,
                ),
            )
        back = f"{app_url()}/organisation?tab=integrations"

        def done(outcome: str) -> Response:
            url = (
                app_return.settings_url(app_url(), card, outcome)
                if card
                else f"{back}&whatsapp={outcome}"
            )
            return RedirectResponse(url, status_code=303, headers=PRIVATE)

        if request.query_params.get("error"):
            signup_log("cancelled", request.query_params)
            return done("cancelled")
        code = request.query_params.get("code", "")
        state = request.query_params.get("state", "")
        if not code or not state:
            signup_log("failed", request.query_params, detail="no code from Meta")
            return done("failed")
        try:
            async with desk_for(request, response, write=True, origin=False) as desk:
                desk._require_manager()
                try:
                    meta.read_state(
                        cfg.app_secret,
                        state,
                        tenant_id=desk.tenant_id,
                        person_id=desk.viewer.person_id,
                    )
                except meta.MetaError:
                    signup_log("failed", detail="the start doesn't match this person")
                    return done("failed")
                outcome = await finish_whatsapp(desk, cfg, code)
        except HTTPException as error:
            if error.status_code in (401, 403):
                raise
            log.warning("whatsapp connect failed: %s", error.detail)
            return done("failed")
        return done(outcome)

    @router.post("/whatsapp/connect", response_model=WhatsAppStatus, response_model_by_alias=True)
    async def whatsapp_connect(
        command: ConnectCommand, request: Request, response: Response
    ) -> WhatsAppStatus:
        """Embedded Signup finished in the page: connect the number it returned."""
        cfg = whatsapp_config()
        async with desk_for(request, response, write=True) as desk:
            api = cloud.Cloud(cfg)
            row = await inbox.connect(
                desk,
                cfg,
                api,
                code=command.code,
                waba_id=command.waba_id,
                phone_number_id=command.phone_number_id,
            )
            try:
                await inbox.sync_templates(desk.db, cfg, api, row, now=desk.now)
            except cloud.WhatsAppError as error:
                log.warning("whatsapp templates not synced on connect: %s", error)
            return await status_view(desk)

    @router.post(
        "/whatsapp/numbers/{number_id}/disconnect",
        response_model=WhatsAppStatus,
        response_model_by_alias=True,
    )
    async def whatsapp_disconnect(
        number_id: UUID, request: Request, response: Response
    ) -> WhatsAppStatus:
        async with desk_for(request, response, write=True) as desk:
            await inbox.disconnect(desk, number_id)
            return await status_view(desk)

    @router.put(
        "/whatsapp/numbers/{number_id}/auto-replies",
        response_model=WhatsAppStatus,
        response_model_by_alias=True,
    )
    async def whatsapp_auto_replies(
        number_id: UUID, command: AutoReplies, request: Request, response: Response
    ) -> WhatsAppStatus:
        async with desk_for(request, response, write=True) as desk:
            desk._require_manager()
            row = await inbox.number(desk.db, desk.tenant_id, number_id)
            approved = {(t.name, t.language) for t in await inbox.approved_templates(desk.db, row)}
            inbox.save_auto_replies(
                row,
                {
                    "first_reply": command.first_reply.model_dump(),
                    "out_of_hours": command.out_of_hours.model_dump(),
                },
                approved,
            )
            row.updated_at = desk.now
            await desk.db.flush()
            return await status_view(desk)

    @router.post(
        "/whatsapp/numbers/{number_id}/templates/sync",
        response_model=WhatsAppStatus,
        response_model_by_alias=True,
    )
    async def whatsapp_sync_templates(
        number_id: UUID, request: Request, response: Response
    ) -> WhatsAppStatus:
        cfg = whatsapp_config()
        async with desk_for(request, response, write=True) as desk:
            desk._require_manager()
            row = await inbox.number(desk.db, desk.tenant_id, number_id)
            await inbox.sync_templates(desk.db, cfg, cloud.Cloud(cfg), row, now=desk.now)
            await desk.db.flush()
            return await status_view(desk)

    @router.post(
        "/whatsapp/numbers/{number_id}/templates",
        response_model=WhatsAppStatus,
        response_model_by_alias=True,
        status_code=201,
    )
    async def whatsapp_new_template(
        number_id: UUID, command: NewTemplate, request: Request, response: Response
    ) -> WhatsAppStatus:
        cfg = whatsapp_config()
        async with desk_for(request, response, write=True) as desk:
            row = await inbox.number(desk.db, desk.tenant_id, number_id)
            await inbox.create_template(
                desk,
                cfg,
                cloud.Cloud(cfg),
                row,
                name=command.name,
                language=command.language,
                category=command.category,
                body=command.body,
                example=command.example,
            )
            await desk.db.flush()
            return await status_view(desk)

    @router.delete(
        "/whatsapp/numbers/{number_id}/templates/{name}",
        response_model=WhatsAppStatus,
        response_model_by_alias=True,
    )
    async def whatsapp_delete_template(
        number_id: UUID, name: str, request: Request, response: Response
    ) -> WhatsAppStatus:
        cfg = whatsapp_config()
        async with desk_for(request, response, write=True) as desk:
            row = await inbox.number(desk.db, desk.tenant_id, number_id)
            await inbox.delete_template(desk, cfg, cloud.Cloud(cfg), row, name=name)
            await desk.db.flush()
            return await status_view(desk)

    async def conversation_view(desk: LeadDesk, lead_id: UUID) -> ConversationView:
        chat = await inbox.conversation(desk, lead_id)
        names = await desk._names(m.sent_by_person_id for m in chat.messages)
        templates: list[TemplateView] = []
        for row in chat.numbers[:1]:
            templates = [template_view(t) for t in await inbox.approved_templates(desk.db, row)]
        open_now = cloud.window_open(chat.last_inbound, desk.now)
        return ConversationView(
            configured=cloud.config() is not None,
            connected=bool(chat.numbers),
            numbers=[number_view(row) for row in chat.numbers],
            messages=[
                MessageView(
                    id=m.id,
                    direction="in" if m.direction == "in" else "out",
                    kind=m.kind,
                    text=m.body,
                    template=m.template_name,
                    status=m.status,
                    error=m.error_title,
                    auto=m.auto,
                    at=m.meta_time or m.created_at,
                    by=names.get(m.sent_by_person_id) if m.sent_by_person_id else None,
                )
                for m in chat.messages
            ],
            window_open=open_now,
            window_closes_at=cloud.window_closes(chat.last_inbound) if open_now else None,
            opted_in=chat.opted_in,
            opt_in_how=chat.opt_in_how,
            templates=templates,
        )

    @router.get(
        "/leads/{lead_id}/whatsapp", response_model=ConversationView, response_model_by_alias=True
    )
    async def lead_whatsapp(
        lead_id: UUID, request: Request, response: Response
    ) -> ConversationView:
        async with desk_for(request, response) as desk:
            return await conversation_view(desk, lead_id)

    @router.post(
        "/leads/{lead_id}/whatsapp", response_model=ConversationView, response_model_by_alias=True
    )
    async def lead_whatsapp_send(
        lead_id: UUID, command: SendCommand, request: Request, response: Response
    ) -> ConversationView:
        cfg = whatsapp_config()
        async with desk_for(request, response, write=True) as desk:
            message = await inbox.send(
                desk,
                cfg,
                cloud.Cloud(cfg),
                lead_id,
                command_id=command.command_id,
                number_id=command.number_id,
                body=command.text,
                template=command.template,
                language=command.language,
                values=command.values,
            )
            await desk.db.flush()
            view = await conversation_view(desk, lead_id)
            if message.status == "failed":
                response.headers["X-WhatsApp-Error"] = "1"
            return view

    @router.post(
        "/leads/{lead_id}/whatsapp/opt-in",
        response_model=ConversationView,
        response_model_by_alias=True,
    )
    async def lead_whatsapp_opt_in(
        lead_id: UUID, command: OptInCommand, request: Request, response: Response
    ) -> ConversationView:
        async with desk_for(request, response, write=True) as desk:
            await inbox.record_opt_in(
                desk, lead_id, command_id=command.command_id, agreed=command.agreed, how=command.how
            )
            return await conversation_view(desk, lead_id)

    @router.get("/whatsapp/inbox", response_model=list[ThreadView], response_model_by_alias=True)
    async def whatsapp_inbox(request: Request, response: Response) -> list[ThreadView]:
        async with desk_for(request, response) as desk:
            return [
                ThreadView(
                    lead_id=thread.lead_id,
                    lead_name=thread.lead_name,
                    last_text=thread.last_text,
                    last_at=thread.last_at,
                    waiting=thread.waiting,
                    window_open=thread.window_open,
                    account_id=thread.number_id,
                    place=thread.place,
                    last_kind=thread.last_kind,
                    last_direction=thread.last_direction,
                    last_status=thread.last_status,
                    waiting_since=thread.waiting_since,
                    window_closes_at=thread.window_closes_at,
                    owner_id=thread.owner_id,
                    owner_name=thread.owner_name,
                )
                for thread in await inbox.inbox(desk)
            ]

    @router.get("/chats", response_model=ChatsView, response_model_by_alias=True)
    async def chats(request: Request, response: Response) -> ChatsView:
        """WhatsApp, Messenger and Instagram conversations together (the Chats screen):
        waiting ones first, then newest. A seller sees only the leads they own."""
        async with desk_for(request, response) as desk:
            _, config = await desk.settings()
            target = sla.read(config)
            unread = await chat_reads.unread(desk)

            def unread_for(channel: str, account: UUID | None, lead: UUID | None) -> int:
                return unread.get((channel, account, lead), 0) if account and lead else 0

            rows: list[ChatThreadView] = [
                ChatThreadView(
                    key=f"whatsapp:{thread.number_id}:{_person_key(desk.tenant_id, thread.wa_id)}",
                    channel="whatsapp",
                    lead_id=thread.lead_id,
                    lead_name=thread.lead_name,
                    last_text=thread.last_text,
                    last_at=thread.last_at,
                    waiting=thread.waiting,
                    window_open=thread.window_open,
                    account_id=thread.number_id,
                    place=thread.place,
                    last_kind=thread.last_kind,
                    last_direction=thread.last_direction,
                    last_status=thread.last_status,
                    waiting_since=thread.waiting_since,
                    window_closes_at=thread.window_closes_at,
                    owner_id=thread.owner_id,
                    owner_name=thread.owner_name,
                    unread=unread_for("whatsapp", thread.number_id, thread.lead_id),
                )
                for thread in await inbox.inbox(desk)
            ]
            rows += [
                ChatThreadView(
                    key=f"{thread.channel}:{thread.account_id}:"
                    f"{_person_key(desk.tenant_id, thread.user_id)}",
                    channel="instagram" if thread.channel == "instagram" else "messenger",
                    lead_id=thread.lead_id,
                    lead_name=thread.lead_name,
                    last_text=thread.last_text,
                    last_at=thread.last_at,
                    waiting=thread.waiting,
                    window_open=thread.window_open,
                    account_id=thread.account_id,
                    place=thread.place,
                    last_kind=thread.last_kind,
                    last_direction=thread.last_direction,
                    last_status=thread.last_status,
                    waiting_since=thread.waiting_since,
                    window_closes_at=thread.window_closes_at,
                    owner_id=thread.owner_id,
                    owner_name=thread.owner_name,
                    unread=unread_for(thread.channel, thread.account_id, thread.lead_id),
                )
                for thread in await social_inbox.inbox(desk)
            ]
            rows.sort(key=lambda row: (not row.waiting, -row.last_at.timestamp()))
            return ChatsView(
                generated_at=desk.now,
                sla=ChatsSla(on=bool(target.on), minutes=int(target.minutes)),
                threads=rows[:CHATS_LIMIT],
            )

    # Dev reaches these through the Leads webhook's Cloudflare Access bypass
    # (/v1/lead-desk/meta/webhook/*); staging and production use the canonical path.
    @router.get("/meta/webhook/whatsapp", response_class=PlainTextResponse)
    @router.get("/whatsapp/webhook", response_class=PlainTextResponse)
    async def whatsapp_verify(request: Request) -> PlainTextResponse:
        """Meta checks the callback address once when the webhook is set up."""
        same_host(request)
        cfg = whatsapp_config()
        params = request.query_params
        if (
            params.get("hub.mode") == "subscribe"
            and params.get("hub.verify_token") == cfg.verify_token
            and params.get("hub.challenge")
        ):
            return PlainTextResponse(params["hub.challenge"][:200], headers=NO_STORE)
        raise HTTPException(403, "Unknown verify token.", headers=NO_STORE)

    @router.post("/meta/webhook/whatsapp")
    @router.post("/whatsapp/webhook")
    async def whatsapp_webhook(request: Request) -> dict[str, int]:
        """Meta's signed notice of messages, delivery statuses and template reviews."""
        same_host(request)
        cfg = whatsapp_config()
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > _MAX_WEBHOOK:
                raise HTTPException(413, "That's too large.", headers=NO_STORE)
            raw.extend(chunk)
        if not cloud.signature_ok(
            cfg.app_secret, bytes(raw), request.headers.get("x-hub-signature-256")
        ):
            raise HTTPException(401, "Bad signature.", headers=NO_STORE)
        try:
            payload = json.loads(bytes(raw))
        except (UnicodeDecodeError, ValueError):
            raise HTTPException(422, "Send JSON.", headers=NO_STORE) from None
        if not isinstance(payload, dict):
            raise HTTPException(422, "Send one JSON object.", headers=NO_STORE)
        delivery = cloud.parse(payload)
        async with ctx.sessions() as database, database.begin():
            done = await inbox.receive(database, delivery, now=datetime.now(UTC))
        return {
            "messages": done.messages,
            "leads": done.leads_created,
            "statuses": done.statuses,
            "templates": done.templates,
        }

    # ----- first-response SLA ---------------------------------------------------------

    def sla_view(value: sla.SlaSettings) -> SlaView:
        return SlaView(
            on=value.on,
            minutes=value.minutes,
            alert_managers=value.alert_managers,
            targets=list(sla.TARGETS),
        )

    @router.get("/sla", response_model=SlaView, response_model_by_alias=True)
    async def sla_settings(request: Request, response: Response) -> SlaView:
        async with desk_for(request, response) as desk:
            _, config = await desk.settings()
            return sla_view(sla.read(config))

    @router.put("/sla", response_model=SlaView, response_model_by_alias=True)
    async def save_sla(command: SlaCommand, request: Request, response: Response) -> SlaView:
        async with desk_for(request, response, write=True) as desk:
            desk._require_manager()
            value = sla.SlaSettings(command.on, command.minutes, command.alert_managers)
            try:
                stored = sla.as_config(value)
            except ValueError as error:
                raise DeskError(422, str(error)) from None
            row = await desk.db.get(LeadDeskSettings, desk.tenant_id, with_for_update=True)
            if row is None:
                row = LeadDeskSettings(
                    tenant_id=desk.tenant_id,
                    revision=1,
                    config={},
                    updated_by_person_id=None,
                    updated_at=desk.now,
                )
                desk.db.add(row)
            # Its own part of the settings: the team settings form's revision stays.
            row.config = {**(row.config or {}), sla.KEY: stored}
            await desk.db.flush()
            return sla_view(value)

    @router.get("/reports/sla", response_model=SlaReport, response_model_by_alias=True)
    async def sla_report(
        request: Request, response: Response, start: date | None = None, end: date | None = None
    ) -> SlaReport:
        async with desk_for(request, response) as desk:
            desk._require_manager()
            last = end or desk.now.date()
            first = start or last - timedelta(days=6)
            if first > last or (last - first).days > 92:
                raise DeskError(422, "Pick up to 92 days.")
            settings_value, sellers = await sla.report(
                desk.db,
                desk.tenant_id,
                start=datetime.combine(first, time.min, tzinfo=UTC),
                end=datetime.combine(last + timedelta(days=1), time.min, tzinfo=UTC),
                now=desk.now,
            )
            late = await sla.late_now(desk.db, desk.tenant_id, now=desk.now)
            names = await desk._names(
                [seller.person_id for seller in sellers] + [item.owner_person_id for item in late]
            )
            return SlaReport(
                late=[
                    LateView(
                        lead_id=item.lead_id,
                        lead_name=item.lead_name,
                        seller=names.get(item.owner_person_id, "Not shared out yet")
                        if item.owner_person_id
                        else "Not shared out yet",
                        minutes_late=item.minutes_late,
                    )
                    for item in late
                ],
                settings=sla_view(settings_value),
                start=first,
                end=last,
                sellers=[
                    SellerSlaView(
                        person_id=seller.person_id,
                        name=names.get(seller.person_id, "Not shared out yet")
                        if seller.person_id
                        else "Not shared out yet",
                        leads=seller.leads,
                        in_time=seller.in_time,
                        breached=seller.breached,
                        waiting=seller.waiting,
                        median_minutes=seller.median_minutes,
                    )
                    for seller in sellers
                ],
            )

    application.include_router(router)
    runner.attach(application, ctx.sessions, settings.environment)
