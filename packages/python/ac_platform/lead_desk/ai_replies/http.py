"""AI reply routes for the Sales Xray CRM (/v1/lead-desk).

- ``/ai-replies/settings``: off, suggest or auto, the channels, price answers, and the
  business profile the AI answers from (owners and admins).
- ``/leads/{id}/ai``: this lead's AI state (mode, channels, recent hand-offs).
- ``/leads/{id}/ai-draft``: a draft for the seller to read and send, or why a person
  should answer instead (suggest).

Same workspace rule as the CRM's own routes. No price is shown to anyone here; each
reply's model, tokens and cost are kept for Admin (``lead_desk_ai_replies``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from ac_platform.conversation_intelligence.sales_xray_tenants import SALES_XRAY_MEMBER_ROLES
from ac_platform.http.auth import require_safe_origin
from ac_platform.http.routes import RouteContext
from ac_platform.identity.models import Person
from ac_platform.kernel.errors import DomainError
from ac_platform.lead_desk.ai_replies import registry, rules, runner, service
from ac_platform.lead_desk.models import Lead, LeadDeskSettings
from ac_platform.lead_desk.store import DeskError, LeadDesk, Viewer, person_name
from ac_platform.tenancy.models import Membership, Organisation

PRIVATE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}
NO_STORE = {"Cache-Control": "no-store"}
WORDS: dict[str, str] = {
    "human": "They asked for a person.",
    "complaint": "It sounds like a complaint.",
    "price": "They're asking about price.",
    "discount": "They want a better price.",
    "unsure": "The answer isn't in your business profile.",
    "off_topic": "It isn't about your business.",
    "opt_out": "They asked to stop messages. Nothing automatic goes to them now.",
    "not_text": "They sent something other than words.",
    "window": "It's more than 24 hours since their last message.",
    "no_profile": "Add your business profile in Settings → Integrations → AI replies.",
    "blocked_reply": "The draft said something your profile doesn't, so it wasn't used.",
    "budget": "AI replies are paused for now.",
    "failed": "The AI couldn't answer just now.",
}


class _Command(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)


Channel = Literal["whatsapp", "messenger", "instagram"]
_ALL_CHANNELS: list[Channel] = ["whatsapp", "messenger", "instagram"]


class Faq(_Command):
    question: str = Field(max_length=300)
    answer: str = Field(max_length=1000)


class AiSettingsCommand(_Command):
    mode: Literal["off", "suggest", "auto"] = "suggest"
    channels: list[Channel] = Field(default_factory=lambda: _ALL_CHANNELS.copy())
    quote_prices: bool = Field(default=False, alias="quotePrices")
    business_name: str = Field(default="", alias="businessName", max_length=200)
    about: str = Field(default="", max_length=rules.MAX_TEXT)
    offerings: str = Field(default="", max_length=rules.MAX_TEXT)
    faqs: list[Faq] = Field(default_factory=list, max_length=rules.MAX_FAQS)
    notes: str = Field(default="", max_length=rules.MAX_TEXT)


class AiSettingsView(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    mode: str
    channels: list[str]
    quote_prices: bool = Field(alias="quotePrices")
    business_name: str = Field(alias="businessName")
    about: str
    offerings: str
    faqs: list[Faq]
    notes: str
    ready: bool
    available: bool


class HandoffView(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    channel: str
    reason: str
    at: datetime


class LeadAiView(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    mode: str
    channels: list[str]
    ready: bool
    available: bool
    handoffs: list[HandoffView]


class DraftCommand(_Command):
    channel: Channel
    account_id: UUID | None = Field(default=None, alias="accountId")


class DraftView(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    reply_id: UUID = Field(alias="replyId")
    draft: str | None = None
    handoff: bool
    reason: str | None = None
    words: str


def install_ai_replies_http(application: FastAPI, ctx: RouteContext) -> None:
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
        except DomainError:
            raise HTTPException(401, "Sign in to see your leads.", headers=PRIVATE) from None

    def settings_view(value: rules.Settings) -> AiSettingsView:
        return AiSettingsView(
            mode=value.mode,
            channels=list(value.channels),
            quote_prices=value.quote_prices,
            business_name=value.business_name,
            about=value.about,
            offerings=value.offerings,
            faqs=[Faq(question=q, answer=a) for q, a in value.faqs],
            notes=value.notes,
            ready=value.has_profile,
            available=registry.available()[0],
        )

    @router.get("/ai-replies/settings", response_model=AiSettingsView, response_model_by_alias=True)
    async def ai_settings(request: Request, response: Response) -> AiSettingsView:
        async with desk_for(request, response) as desk:
            desk._require_manager()
            row = await desk.db.get(LeadDeskSettings, desk.tenant_id)
            return settings_view(rules.read((row.config if row else None) or {}))

    @router.put("/ai-replies/settings", response_model=AiSettingsView, response_model_by_alias=True)
    async def save_ai_settings(
        command: AiSettingsCommand, request: Request, response: Response
    ) -> AiSettingsView:
        async with desk_for(request, response, write=True) as desk:
            desk._require_manager()
            value = rules.Settings(
                mode=command.mode,
                channels=tuple(dict.fromkeys(command.channels)),
                quote_prices=command.quote_prices,
                business_name=command.business_name,
                about=command.about,
                offerings=command.offerings,
                faqs=tuple(
                    (faq.question, faq.answer)
                    for faq in command.faqs
                    if faq.question and faq.answer
                ),
                notes=command.notes,
            )
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
            row.config = {**(row.config or {}), rules.KEY: rules.as_config(value)}
            await desk.db.flush()
            return settings_view(value)

    @router.get("/leads/{lead_id}/ai", response_model=LeadAiView, response_model_by_alias=True)
    async def lead_ai(lead_id: UUID, request: Request, response: Response) -> LeadAiView:
        async with desk_for(request, response) as desk:
            lead = await service.lead_for(desk, lead_id)
            row = await desk.db.get(LeadDeskSettings, desk.tenant_id)
            value = rules.read((row.config if row else None) or {})
            handoffs = await service.recent_handoffs(desk.db, lead.id, now=desk.now)
            return LeadAiView(
                mode=value.mode,
                channels=list(value.channels),
                ready=value.has_profile,
                available=registry.available()[0],
                handoffs=[
                    HandoffView(
                        channel=item.channel, reason=item.reason or "unsure", at=item.created_at
                    )
                    for item in handoffs
                ],
            )

    @router.post(
        "/leads/{lead_id}/ai-draft", response_model=DraftView, response_model_by_alias=True
    )
    async def lead_ai_draft(
        lead_id: UUID, command: DraftCommand, request: Request, response: Response
    ) -> DraftView:
        """A draft for the seller to read and send, or why a person should answer."""

        async with desk_for(request, response, write=True) as desk:
            lead = await service.lead_for(desk, lead_id)
            ready = await service.prepare(
                desk.db, lead, command.channel, account_id=command.account_id, now=desk.now
            )
            if not registry.available()[0]:
                raise DeskError(409, "AI replies aren't switched on for Sales Xray yet.")
            if ready.settings.mode == "off":
                raise DeskError(409, "AI replies are off. A manager turns them on in Settings.")
            if command.channel not in ready.settings.channels:
                raise DeskError(409, "AI replies are off for this channel.")
            person = desk.viewer.person_id
        # The model is asked with no transaction of this request open.
        result = await service.think(registry.model_for(ctx.sessions), ready)
        now = datetime.now(UTC)
        async with ctx.sessions() as db, db.begin():
            row = service.audit(ready, result, mode="suggest", now=now, by=person)
            db.add(row)
            if result.outcome == "opted_out":
                lead_row = await db.get(Lead, lead_id, with_for_update=True)
                if lead_row is not None:
                    await service.record_stop(
                        service.system_desk(db, lead_row, now), lead_row, command.channel
                    )
        handoff = result.outcome != "drafted"
        return DraftView(
            reply_id=row.id,
            draft=result.draft if not handoff else None,
            handoff=handoff,
            reason=result.reason,
            words="" if not handoff else WORDS.get(result.reason or "", WORDS["unsure"]),
        )

    application.include_router(router)
    runner.attach(application, ctx.sessions, settings.environment)
