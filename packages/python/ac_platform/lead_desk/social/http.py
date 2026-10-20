"""Messenger and Instagram routes for the Sales Xray CRM (/v1/lead-desk).

- ``/messaging/*``: connect the organisation's Pages (Facebook Login for Business on
  AC's Messaging app, from a browser or the Sales Xray app), each Page's channels, auto
  replies and comment rules, and Meta's signed webhook.
- ``/leads/{id}/social``: one lead's Messenger and Instagram conversations and sending
  (Meta's 24-hour window; a person may use the Human Agent tag within 7 days).
- ``/social/inbox``: the conversations of the last month.

Same workspace rule as the CRM's own routes: a signed-in member of an organisation
workspace; managers (owners and admins) set things up, sellers see their own leads.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Literal
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
from ac_platform.lead_desk.connectors import app_return, meta
from ac_platform.lead_desk.connectors.app_return import AppComplete, AppCompleted
from ac_platform.lead_desk.models import LeadSocialAccount
from ac_platform.lead_desk.social import graph, inbox, runner
from ac_platform.lead_desk.store import DeskError, LeadDesk, Viewer, person_name
from ac_platform.tenancy.models import Membership, Organisation

log = logging.getLogger(__name__)
events = structlog.get_logger(__name__)
PRIVATE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}
NO_STORE = {"Cache-Control": "no-store"}
_MAX_WEBHOOK = 3 * 1024 * 1024
_MAX_NAMES = 10  # profile look-ups per webhook delivery


class _Command(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)


class Reply(_Command):
    on: bool = False
    text: str | None = Field(default=None, max_length=1000)


class CommentRule(_Command):
    on: bool = True
    keywords: list[str] = Field(default_factory=list, max_length=inbox.MAX_KEYWORDS)
    reply: str = Field(default="", max_length=1000)
    public_reply: str | None = Field(default=None, alias="publicReply", max_length=300)


class AccountSettings(_Command):
    messenger: bool = True
    instagram: bool = True
    human_agent: bool = Field(default=False, alias="humanAgent")
    first_reply: Reply = Field(default_factory=Reply, alias="firstReply")
    out_of_hours: Reply = Field(default_factory=Reply, alias="outOfHours")
    comments: list[CommentRule] = Field(default_factory=list, max_length=inbox.MAX_RULES)


class AccountView(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: UUID
    page_id: str = Field(alias="pageId")
    page_name: str = Field(alias="pageName")
    ig_username: str | None = Field(default=None, alias="igUsername")
    has_instagram: bool = Field(alias="hasInstagram")
    settings: AccountSettings


class MessagingStatus(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    configured: bool
    accounts: list[AccountView]
    taken: list[str] = Field(default_factory=list)


class MessageView(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: UUID
    direction: Literal["in", "out"]
    kind: str
    text: str | None = None
    status: str
    error: str | None = None
    auto: str | None = None
    human_agent: bool = Field(default=False, alias="humanAgent")
    at: datetime
    by: str | None = None


class ThreadView(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    account_id: UUID = Field(alias="accountId")
    channel: Literal["messenger", "instagram"]
    place: str
    messages: list[MessageView]
    window_open: bool = Field(alias="windowOpen")
    window_closes_at: datetime | None = Field(default=None, alias="windowClosesAt")
    human_agent: bool = Field(alias="humanAgent")


class SocialConversation(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    configured: bool
    connected: bool
    threads: list[ThreadView]


class SendCommand(_Command):
    command_id: UUID = Field(alias="commandId")
    channel: Literal["messenger", "instagram"]
    account_id: UUID | None = Field(default=None, alias="accountId")
    text: str = Field(min_length=1, max_length=2000)
    human_agent: bool = Field(default=False, alias="humanAgent")


class InboxView(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    lead_id: UUID | None = Field(default=None, alias="leadId")
    lead_name: str = Field(alias="leadName")
    channel: Literal["messenger", "instagram"]
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


# The Settings → Connected apps cards a Messenger/Instagram connect can come back to.
MESSAGING_CARDS: tuple[str, ...] = ("messenger", "instagram")


def install_social_http(application: FastAPI, ctx: RouteContext) -> None:
    router = APIRouter(prefix="/v1/lead-desk", tags=["lead-desk"])
    settings = ctx.settings
    read_actor = getattr(ctx.require_actor, "read_only", ctx.require_actor)

    def same_host(request: Request) -> None:
        if (
            settings.sales_xray_app_url is None
            or request.url.hostname != settings.sales_xray_app_url.host
        ):
            raise HTTPException(404, "Leads are unavailable here.", headers=NO_STORE)

    def social_config() -> graph.SocialConfig:
        cfg = graph.config()
        if cfg is None:
            raise HTTPException(
                409,
                "Messenger and Instagram aren't set up for Sales Xray yet.",
                headers=PRIVATE,
            )
        return cfg

    def app_url() -> str:
        return str(settings.sales_xray_app_url or "").rstrip("/")

    def callback_url() -> str:
        return f"{app_url()}/v1/lead-desk/messaging/callback"

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
        except (graph.SocialError, meta.MetaError) as error:
            raise HTTPException(502, str(error), headers=PRIVATE) from None
        except DomainError:
            raise HTTPException(401, "Sign in to see your leads.", headers=PRIVATE) from None

    def account_view(row: LeadSocialAccount) -> AccountView:
        rules = inbox.account_config(row)
        return AccountView(
            id=row.id,
            page_id=row.page_id,
            page_name=row.page_name,
            ig_username=row.ig_username,
            has_instagram=row.ig_user_id is not None,
            settings=AccountSettings(
                messenger=rules["messenger"],
                instagram=rules["instagram"],
                human_agent=rules["human_agent"],
                first_reply=Reply(**rules["first_reply"]),
                out_of_hours=Reply(**rules["out_of_hours"]),
                comments=[
                    CommentRule(
                        on=rule.get("on") is not False,
                        keywords=list(rule.get("keywords") or []),
                        reply=str(rule.get("reply") or ""),
                        public_reply=rule.get("public_reply"),
                    )
                    for rule in rules["comments"]
                ],
            ),
        )

    async def status_view(desk: LeadDesk, taken: list[str] | None = None) -> MessagingStatus:
        return MessagingStatus(
            configured=graph.config() is not None,
            accounts=[account_view(row) for row in await inbox.accounts(desk.db, desk.tenant_id)],
            taken=taken or [],
        )

    @router.get("/messaging/status", response_model=MessagingStatus, response_model_by_alias=True)
    async def messaging_status(request: Request, response: Response) -> MessagingStatus:
        async with desk_for(request, response) as desk:
            desk._require_manager()
            return await status_view(desk)

    # ----- connect ------------------------------------------------------------------------

    @router.get("/messaging/connect", response_model=None)
    async def messaging_connect(
        request: Request,
        response: Response,
        app_challenge: str | None = Query(default=None),
        reply: str | None = Query(default=None, alias="format"),
        return_to: str | None = Query(default=None),
        card: str | None = Query(default=None),
    ) -> Response:
        """Connect Messenger and Instagram: off to Facebook Login for Business and back.
        From the Sales Xray app, with ``app_challenge``, it finishes in the app; from
        Settings → Connected apps, with ``return_to``, it comes back to that card."""
        cfg = social_config()
        if app_challenge is not None and not app_return.CHALLENGE.fullmatch(app_challenge):
            raise HTTPException(422, "Start again from the Sales Xray app.", headers=PRIVATE)
        try:
            settings_card = app_return.settings_card(return_to, card, allowed=MESSAGING_CARDS)
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
        url = graph.dialog_url(cfg, redirect_uri=callback_url(), state=state)
        if reply == "json":
            return JSONResponse({"url": url}, headers=PRIVATE)
        return RedirectResponse(url, status_code=303, headers=PRIVATE)

    async def finish(desk: LeadDesk, cfg: graph.SocialConfig, code: str) -> tuple[str, list[str]]:
        api = graph.Graph(cfg)
        user = await api.user_token(code=code, redirect_uri=callback_url())
        pages = await api.pages(user)
        done = await inbox.connect_pages(desk, cfg, api, pages)
        if done.accounts:
            return "connected", done.taken
        return ("taken" if done.taken else "nopages"), done.taken

    @router.get("/messaging/callback", response_model=None)
    async def messaging_callback(request: Request, response: Response) -> Response:
        cfg = social_config()
        params = request.query_params
        state = params.get("state", "")
        try:
            peeked = meta.peek_state(cfg.app_secret, state)
        except meta.MetaError:
            peeked = {}
        from_app = bool(peeked.get("a"))
        card = app_return.card_of(peeked, MESSAGING_CARDS)
        if from_app:
            # In the phone's browser, with no Sales Xray session: hand back to the app.
            if params.get("error"):
                return app_return.return_page("messaging", result="cancelled")
            if not params.get("code"):
                return app_return.return_page("messaging", result="failed")
            return app_return.return_page(
                "messaging",
                handoff=app_return.seal(
                    cfg.token_key, provider="messaging", code=params["code"][:2048], state=state
                ),
            )
        back = f"{app_url()}/organisation?tab=integrations"

        def done(outcome: str) -> Response:
            url = (
                app_return.settings_url(app_url(), card, outcome)
                if card
                else f"{back}&messaging={outcome}"
            )
            return RedirectResponse(url, status_code=303, headers=PRIVATE)

        if params.get("error"):
            return done("cancelled")
        code = params.get("code", "")
        if not code or not state:
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
                    return done("failed")
                outcome, _ = await finish(desk, cfg, code)
        except HTTPException as error:
            if error.status_code in (401, 403):
                raise
            log.warning("messaging connect failed: %s", error.detail)
            return done("failed")
        return done(outcome)

    @router.post("/messaging/app-complete", response_model=AppCompleted)
    async def messaging_app_complete(
        command: AppComplete, request: Request, response: Response
    ) -> AppCompleted:
        """The app is back from Facebook: finish connecting on this person's session."""
        cfg = social_config()
        async with desk_for(request, response, write=True) as desk:
            desk._require_manager()
            try:
                code, state = app_return.open_(cfg.token_key, command.handoff, provider="messaging")
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
            outcome, _ = await finish(desk, cfg, code)
            return AppCompleted(result=outcome)

    @router.post(
        "/messaging/accounts/{account_id}/disconnect",
        response_model=MessagingStatus,
        response_model_by_alias=True,
    )
    async def messaging_disconnect(
        account_id: UUID, request: Request, response: Response
    ) -> MessagingStatus:
        async with desk_for(request, response, write=True) as desk:
            await inbox.disconnect(desk, account_id)
            return await status_view(desk)

    @router.put(
        "/messaging/accounts/{account_id}",
        response_model=MessagingStatus,
        response_model_by_alias=True,
    )
    async def messaging_settings(
        account_id: UUID, command: AccountSettings, request: Request, response: Response
    ) -> MessagingStatus:
        async with desk_for(request, response, write=True) as desk:
            desk._require_manager()
            row = await inbox.account(desk.db, desk.tenant_id, account_id)
            inbox.save_settings(
                row,
                {
                    "messenger": command.messenger,
                    "instagram": command.instagram,
                    "human_agent": command.human_agent,
                    "first_reply": command.first_reply.model_dump(),
                    "out_of_hours": command.out_of_hours.model_dump(),
                    "comments": [rule.model_dump() for rule in command.comments],
                },
            )
            row.updated_at = desk.now
            await desk.db.flush()
            return await status_view(desk)

    # ----- one lead's conversations ---------------------------------------------------------

    async def conversation_view(desk: LeadDesk, lead_id: UUID) -> SocialConversation:
        _, found = await inbox.conversation(desk, lead_id)
        names = await desk._names(m.sent_by_person_id for thread in found for m in thread.messages)
        views: list[ThreadView] = []
        for thread in found:
            rules = inbox.account_config(thread.account)
            open_now = graph.window_open(thread.last_inbound, desk.now)
            views.append(
                ThreadView(
                    account_id=thread.account.id,
                    channel="instagram" if thread.channel == "instagram" else "messenger",
                    place=inbox.label(thread.account, thread.channel),
                    messages=[
                        MessageView(
                            id=m.id,
                            direction="in" if m.direction == "in" else "out",
                            kind=m.kind,
                            text=m.body,
                            status=m.status,
                            error=inbox.error_words(
                                m.error_title, m.error_code, manager=desk.viewer.can_manage
                            ),
                            auto=m.auto,
                            human_agent=m.tag == "HUMAN_AGENT",
                            at=m.meta_time or m.created_at,
                            by=names.get(m.sent_by_person_id) if m.sent_by_person_id else None,
                        )
                        for m in thread.messages
                    ],
                    window_open=open_now,
                    window_closes_at=thread.last_inbound + graph.WINDOW
                    if open_now and thread.last_inbound
                    else None,
                    human_agent=rules["human_agent"]
                    and not open_now
                    and graph.human_agent_open(thread.last_inbound, desk.now),
                )
            )
        return SocialConversation(
            configured=graph.config() is not None,
            connected=bool(await inbox.accounts(desk.db, desk.tenant_id)),
            threads=views,
        )

    @router.get(
        "/leads/{lead_id}/social", response_model=SocialConversation, response_model_by_alias=True
    )
    async def lead_social(
        lead_id: UUID, request: Request, response: Response
    ) -> SocialConversation:
        async with desk_for(request, response) as desk:
            return await conversation_view(desk, lead_id)

    @router.post(
        "/leads/{lead_id}/social", response_model=SocialConversation, response_model_by_alias=True
    )
    async def lead_social_send(
        lead_id: UUID, command: SendCommand, request: Request, response: Response
    ) -> SocialConversation:
        cfg = social_config()
        async with desk_for(request, response, write=True) as desk:
            message = await inbox.send(
                desk,
                cfg,
                graph.Graph(cfg),
                lead_id,
                command_id=command.command_id,
                channel=command.channel,
                account_id=command.account_id,
                body=command.text,
                human_agent=command.human_agent,
            )
            await desk.db.flush()
            view = await conversation_view(desk, lead_id)
            if message.status == "failed":
                response.headers["X-Messaging-Error"] = "1"
            return view

    @router.get("/social/inbox", response_model=list[InboxView], response_model_by_alias=True)
    async def social_inbox(request: Request, response: Response) -> list[InboxView]:
        async with desk_for(request, response) as desk:
            return [
                InboxView(
                    lead_id=thread.lead_id,
                    lead_name=thread.lead_name,
                    channel="instagram" if thread.channel == "instagram" else "messenger",
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
                )
                for thread in await inbox.inbox(desk)
            ]

    # ----- webhook ------------------------------------------------------------------------

    # Dev reaches these through the Leads webhook's Cloudflare Access bypass
    # (/v1/lead-desk/meta/webhook/*); staging and production use the canonical path.
    @router.get("/meta/webhook/messaging", response_class=PlainTextResponse)
    @router.get("/messaging/webhook", response_class=PlainTextResponse)
    async def messaging_verify(request: Request) -> PlainTextResponse:
        """Meta checks the callback address once when the webhook is set up."""
        same_host(request)
        cfg = social_config()
        params = request.query_params
        if (
            params.get("hub.mode") == "subscribe"
            and params.get("hub.verify_token") == cfg.verify_token
            and params.get("hub.challenge")
        ):
            return PlainTextResponse(params["hub.challenge"][:200], headers=NO_STORE)
        raise HTTPException(403, "Unknown verify token.", headers=NO_STORE)

    async def names_for(
        cfg: graph.SocialConfig, delivery: graph.Delivery
    ) -> dict[tuple[str, str, str], str | None]:
        """New people's names from Meta, asked with no database transaction open."""
        async with ctx.sessions() as database:
            known = await inbox.known_people(database, delivery)
            wanted: dict[tuple[str, str, str], LeadSocialAccount] = {}
            for message in delivery.inbound:
                key = inbox.chat_key(message.channel, message.account_id, message.user_id)
                if key in known or key in wanted or len(wanted) >= _MAX_NAMES:
                    continue
                row = await inbox.find_account(database, message.channel, message.account_id)
                if row is not None:
                    wanted[key] = row
        api = graph.Graph(cfg, timeout=4)

        async def one(key: tuple[str, str, str], row: LeadSocialAccount) -> str | None:
            try:
                return await api.profile(key[0], key[2], inbox.page_token(cfg, row))
            except graph.SocialError:
                return None

        found = await asyncio.gather(*(one(key, row) for key, row in wanted.items()))
        return dict(zip(wanted, found, strict=True))

    @router.post("/meta/webhook/messaging")
    @router.post("/messaging/webhook")
    async def messaging_webhook(request: Request) -> dict[str, int]:
        """Meta's signed notice of messages, delivery and read receipts, and comments."""
        same_host(request)
        cfg = social_config()
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > _MAX_WEBHOOK:
                raise HTTPException(413, "That's too large.", headers=NO_STORE)
            raw.extend(chunk)
        if not meta.signature_ok(
            cfg.app_secret, bytes(raw), request.headers.get("x-hub-signature-256")
        ):
            raise HTTPException(401, "Bad signature.", headers=NO_STORE)
        try:
            payload = json.loads(bytes(raw))
        except (UnicodeDecodeError, ValueError):
            raise HTTPException(422, "Send JSON.", headers=NO_STORE) from None
        if not isinstance(payload, dict):
            raise HTTPException(422, "Send one JSON object.", headers=NO_STORE)
        delivery = graph.parse(payload)
        names = await names_for(cfg, delivery) if delivery.inbound else {}
        async with ctx.sessions() as database, database.begin():
            done = await inbox.receive(
                database, delivery, now=datetime.now(UTC), names=names, app_id=cfg.app_id
            )
        # Counts and reasons only, never a message, a name or an id (structlog: the
        # stdlib logger's info lines don't reach the journal).
        events.info(
            "lead_desk_messaging_webhook",
            messages=done.messages,
            statuses=done.statuses,
            comments=done.comments,
            skipped=[f"{skip.reason}:{','.join(skip.fields)}" for skip in delivery.skipped]
            + [reason for reason in done.skipped if reason == "no_rule"],
        )
        return {
            "messages": done.messages,
            "leads": done.leads_created,
            "statuses": done.statuses,
            "comments": done.comments,
            "unsent": done.unsent,
        }

    application.include_router(router)
    runner.attach(application, ctx.sessions, settings.environment)
