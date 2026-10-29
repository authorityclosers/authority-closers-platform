"""Company-number calls in the Sales Xray CRM (/v1/lead-desk).

- ``GET/PUT /calling``: the organisation's company number, recording notice, which
  leads may be called from it, and (``PUT /calling/me``) each seller's own mobile.
- ``GET /calling/leads/{id}``: may this lead be called from the company number now?
- ``POST /leads/{id}/calls/company``: ring the seller, then the lead (the bridge).
- ``GET /calls/company/{id}``: how that call is going (the app polls while it shows).
- ``GET /calls/company/{id}/recording``: the call's recording, for the seller's app to
  send through the usual upload (consent and AI setting as for any recording).
- ``POST /telephony/{provider}/status/…``: the provider's status webhook, signed by
  its address. The webhook only nudges: what counts is what the provider's API says.
- ``GET /telephony/notice/{version}.wav``: the recording notice the lead hears.

Development sits behind Cloudflare Access, so its webhook and notice use the Leads
webhook's bypass (``/v1/lead-desk/meta/webhook/telephony/…``), as WhatsApp's does.

Off unless this environment has a provider (``AC_TELEPHONY_PROVIDER``) and staff
listed the organisation (``AC_TELEPHONY_TENANTS``); then the organisation's owner
turns it on in Settings → Calling. Prices never appear in any answer here.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import anyio
from fastapi import APIRouter, BackgroundTasks, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from ac_platform.conversation_intelligence.sales_xray_tenants import SALES_XRAY_MEMBER_ROLES
from ac_platform.http.auth import require_safe_origin
from ac_platform.http.routes import RouteContext
from ac_platform.identity.models import Person
from ac_platform.kernel.errors import DomainError
from ac_platform.lead_desk.capture import normalise_phone
from ac_platform.lead_desk.models import LeadDeskSettings
from ac_platform.lead_desk.store import DeskError, LeadDesk, Viewer, person_name
from ac_platform.lead_desk.telephony import ledger, policy, providers, service
from ac_platform.tenancy.models import Membership, Organisation

PRIVATE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}
NO_STORE = {"Cache-Control": "no-store"}
NOTICES_DIR = Path(__file__).parent / "notices"
_MAX_WEBHOOK = 64 * 1024
# The app polls a live call every few seconds; the provider is asked at most this often.
_ASK_EVERY = 4.0
_asked: dict[UUID, float] = {}


class _Command(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)


class _View(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class SourceView(_View):
    key: str
    label: str
    on: bool


class NoticeView(_View):
    version: str
    text: str


class CallingView(_View):
    available: bool
    on: bool = False
    number: str | None = None
    provider: str | None = None
    notice: NoticeView | None = None
    notices: list[NoticeView] = Field(default_factory=list)
    window_days: int = Field(default=policy.DEFAULT_WINDOW_DAYS, alias="windowDays")
    sources: list[SourceView] = Field(default_factory=list)
    my_mobile: str | None = Field(default=None, alias="myMobile")
    can_manage: bool = Field(default=False, alias="canManage")
    ready: bool = False
    blockers: list[str] = Field(default_factory=list)
    paused: str | None = None
    test_only: bool = Field(default=False, alias="testOnly")


class CallingCommand(_Command):
    on: bool
    number: str | None = Field(default=None, max_length=32)
    notice_version: str = Field(default=policy.DEFAULT_NOTICE, alias="noticeVersion", max_length=64)
    window_days: int = Field(default=policy.DEFAULT_WINDOW_DAYS, alias="windowDays", ge=1, le=90)
    sources: list[str] = Field(default_factory=lambda: list(policy.DEFAULT_SOURCES), max_length=10)


class MobileCommand(_Command):
    mobile: str | None = Field(default=None, max_length=32)


class LeadCheck(_View):
    available: bool
    reason: str | None = None
    words: str | None = None


class StartCommand(_Command):
    command_id: UUID = Field(alias="commandId")


class CompanyCallView(_View):
    id: UUID
    lead_id: UUID = Field(alias="leadId")
    status: str
    final: bool
    words: str | None = None
    talk_seconds: int | None = Field(default=None, alias="talkSeconds")
    connected: bool | None = None
    event_id: UUID | None = Field(default=None, alias="eventId")
    recording: bool = False
    requested_at: datetime = Field(alias="requestedAt")
    hung_up_by: str | None = Field(default=None, alias="hungUpBy")


def call_view(call: ledger.CompanyCall) -> CompanyCallView:
    return CompanyCallView(
        id=call.id,
        lead_id=call.lead_id,
        status=call.status,
        final=call.final,
        words=call.words,
        talk_seconds=call.talk_seconds,
        connected=call.lead_answered,
        event_id=call.lead_event_id,
        recording=call.recording,
        requested_at=call.requested_at,
        hung_up_by=call.hung_up_by,
    )


def sign(secret: str, tenant_id: UUID, call_id: UUID) -> str:
    """The webhook address's signature: only the provider we gave it to knows it."""
    message = f"{tenant_id}:{call_id}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()[:32]


def install_telephony_http(application: FastAPI, ctx: RouteContext) -> None:
    router = APIRouter(prefix="/v1/lead-desk", tags=["lead-desk"])
    settings = ctx.settings
    environment = str(settings.environment)
    read_actor = getattr(ctx.require_actor, "read_only", ctx.require_actor)
    development = environment == "development"

    def same_host(request: Request) -> None:
        if (
            settings.sales_xray_app_url is None
            or request.url.hostname != settings.sales_xray_app_url.host
        ):
            raise HTTPException(404, "Leads are unavailable here.", headers=NO_STORE)

    def provider() -> providers.Provider | None:
        return providers.provider_from_env(environment=environment)

    def run() -> policy.Rules:
        return policy.rules(environment=environment)

    def base() -> str | None:
        url = settings.sales_xray_app_url
        return str(url).rstrip("/") if url is not None else None

    def hook_prefix() -> str:
        # Development: under the Leads webhook's Cloudflare Access bypass.
        return "/v1/lead-desk/meta/webhook/telephony" if development else "/v1/lead-desk/telephony"

    def status_url(tenant_id: UUID, name: str) -> Any:
        secret = (os.environ.get("AC_TELEPHONY_WEBHOOK_SECRET") or "").strip()
        root = base()

        def url(call_id: UUID) -> str | None:
            if not secret or root is None:
                return None  # no webhook: the app's polling follows the call
            middle = f"{name}/" if development else f"{name}/status/"
            return (
                f"{root}{hook_prefix()}/{middle}{tenant_id}/{call_id}/"
                f"{sign(secret, tenant_id, call_id)}"
            )

        return url

    def notice_url(notice: policy.Notice) -> str | None:
        root = base()
        return f"{root}{hook_prefix()}/notice/{notice.version}.wav" if root else None

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
                        session_id=actor.session_id,
                    ),
                )
        except DeskError as error:
            raise HTTPException(error.status, str(error), headers=PRIVATE) from None
        except service.CallRefused as refused:
            raise HTTPException(
                refused.status,
                refused.refusal.words,
                headers={**PRIVATE, "X-Company-Call-Refused": refused.refusal.reason},
            ) from None
        except DomainError:
            raise HTTPException(401, "Sign in to see your leads.", headers=PRIVATE) from None

    def offered(desk: LeadDesk, found: providers.Provider | None, rules: policy.Rules) -> bool:
        return found is not None and desk.tenant_id in rules.tenants

    async def calling_view(desk: LeadDesk) -> CallingView:
        found, rules = provider(), run()
        manage = desk.viewer.can_manage
        if found is None or not offered(desk, found, rules):
            return CallingView(available=False, can_manage=manage)
        _, config = await desk.settings()
        value = policy.read(config)
        blockers = [
            refusal.words
            for refusal in (
                policy.place_check(value, rules, real_provider=found.real),
                policy.mobile_check(value, rules, desk.viewer.person_id, real_provider=found.real),
            )
            if refusal is not None
        ]
        left = await service.budget(desk.db, desk.tenant_id, policy.limits(config), desk.now)
        paused = None
        if left.paused is not None:
            paused = (
                policy.PAUSED.words
                if not manage
                else "Paused until tomorrow: today's calling limit is reached."
                if left.paused == "day"
                else "Paused until the 1st: this month's calling limit is reached."
            )
        notice = value.notice
        return CallingView(
            available=True,
            on=value.on,
            number=value.number,
            provider=found.label if manage else None,
            notice=NoticeView(version=notice.version, text=notice.text) if notice else None,
            notices=[NoticeView(version=n.version, text=n.text) for n in policy.NOTICES.values()],
            window_days=value.window_days,
            sources=[
                SourceView(key=key, label=label, on=key in value.sources)
                for key, label in policy.SOURCES.items()
            ],
            my_mobile=value.mobiles.get(str(desk.viewer.person_id)),
            can_manage=manage,
            ready=not blockers and paused is None,
            blockers=blockers,
            paused=paused,
            test_only=found.real and not rules.production,
        )

    async def save(desk: LeadDesk, value: policy.CallingSettings) -> None:
        try:
            stored = policy.as_config(value)
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
        row.config = {**(row.config or {}), policy.KEY: stored}
        await desk.db.flush()

    async def current(desk: LeadDesk) -> policy.CallingSettings:
        row = await desk.db.get(LeadDeskSettings, desk.tenant_id, with_for_update=True)
        return policy.read(row.config if row is not None and row.config else {})

    @router.get("/calling", response_model=CallingView, response_model_by_alias=True)
    async def calling(request: Request, response: Response) -> CallingView:
        async with desk_for(request, response) as desk:
            return await calling_view(desk)

    @router.put("/calling", response_model=CallingView, response_model_by_alias=True)
    async def save_calling(
        command: CallingCommand, request: Request, response: Response
    ) -> CallingView:
        async with desk_for(request, response, write=True) as desk:
            desk._require_manager()
            if not offered(desk, provider(), run()):
                raise DeskError(409, policy.NOT_SET_UP.words)
            number = normalise_phone(command.number) if command.number else None
            if command.number and number is None:
                raise DeskError(422, "That doesn't look like a phone number.")
            value = replace(
                await current(desk),
                on=command.on,
                number=number,
                notice_on=True,  # owner, 27 Oct 2026: "recording notice on"
                notice_version=command.notice_version,
                window_days=command.window_days,
                sources=tuple(command.sources),
            )
            await save(desk, value)
            return await calling_view(desk)

    @router.put("/calling/me", response_model=CallingView, response_model_by_alias=True)
    async def save_mobile(
        command: MobileCommand, request: Request, response: Response
    ) -> CallingView:
        async with desk_for(request, response, write=True) as desk:
            if not offered(desk, provider(), run()):
                raise DeskError(409, policy.NOT_SET_UP.words)
            mobile = normalise_phone(command.mobile) if command.mobile else None
            if command.mobile and mobile is None:
                raise DeskError(422, "That doesn't look like a mobile number.")
            value = await current(desk)
            mobiles = {k: v for k, v in value.mobiles.items() if k != str(desk.viewer.person_id)}
            if mobile is not None:
                mobiles[str(desk.viewer.person_id)] = mobile
            await save(desk, replace(value, mobiles=mobiles))
            return await calling_view(desk)

    @router.get("/calling/leads/{lead_id}", response_model=LeadCheck, response_model_by_alias=True)
    async def lead_check(lead_id: UUID, request: Request, response: Response) -> LeadCheck:
        async with desk_for(request, response) as desk:
            found, rules = provider(), run()
            if found is None or not offered(desk, found, rules):
                return LeadCheck(available=False, reason="not_set_up")
            lead = await desk._lead(lead_id)
            if not (desk.viewer.can_manage or lead.owner_person_id == desk.viewer.person_id):
                return LeadCheck(
                    available=False,
                    reason="not_yours",
                    words="Only the lead's owner or a manager can call this lead.",
                )
            _, config = await desk.settings()
            value = policy.read(config)
            refusal = (
                policy.place_check(value, rules, real_provider=found.real)
                or policy.lead_check(
                    value,
                    rules,
                    source=lead.source,
                    asked_at=lead.created_at,
                    phone=lead.phone,
                    now=desk.now,
                    real_provider=found.real,
                )
                or policy.mobile_check(
                    value, rules, desk.viewer.person_id, real_provider=found.real
                )
            )
            if refusal is None:
                left = await service.budget(
                    desk.db, desk.tenant_id, policy.limits(config), desk.now
                )
                refusal = policy.PAUSED if left.paused is not None else None
            if refusal is not None:
                return LeadCheck(available=False, reason=refusal.reason, words=refusal.words)
            return LeadCheck(available=True)

    @router.post(
        "/leads/{lead_id}/calls/company",
        response_model=CompanyCallView,
        response_model_by_alias=True,
    )
    async def start_call(
        lead_id: UUID, command: StartCommand, request: Request, response: Response
    ) -> CompanyCallView:
        found, rules = provider(), run()
        async with desk_for(request, response, write=True) as desk:
            if found is None or not offered(desk, found, rules):
                raise service.CallRefused(policy.NOT_SET_UP)
            tenant_id = desk.tenant_id
            prepared = await service.prepare(
                desk,
                lead_id=lead_id,
                command_id=command.command_id,
                provider=found,
                run=rules,
                env=os.environ,
                status_url=status_url(tenant_id, found.name),
                notice_url=notice_url,
            )
        # The request is on record; now the provider, with no transaction open.
        try:
            call = await service.settle(ctx.sessions, found, prepared, now=datetime.now(UTC))
        except providers.TelephonyError as error:
            raise HTTPException(error.status, str(error), headers=PRIVATE) from None
        return call_view(call)

    async def own_call(desk: LeadDesk, call_id: UUID) -> ledger.CompanyCall:
        call = await ledger.read(desk.db, desk.tenant_id, call_id)
        if call is None or not (
            desk.viewer.can_manage or call.seller_person_id == desk.viewer.person_id
        ):
            raise DeskError(404, "This call isn't on your desk.")
        return call

    @router.get(
        "/calls/company/{call_id}", response_model=CompanyCallView, response_model_by_alias=True
    )
    async def read_call(call_id: UUID, request: Request, response: Response) -> CompanyCallView:
        async with desk_for(request, response) as desk:
            call = await own_call(desk, call_id)
            tenant_id = desk.tenant_id
        now = datetime.now(UTC)
        tick = time.monotonic()
        if not call.final and tick - _asked.get(call_id, 0.0) >= _ASK_EVERY:
            _asked[call_id] = tick
            if len(_asked) > 2000:
                _asked.clear()
            call = (
                await service.refresh(ctx.sessions, provider(), tenant_id, call_id, now=now) or call
            )
        return call_view(call)

    @router.get("/calls/company/{call_id}/recording")
    async def call_recording(call_id: UUID, request: Request, response: Response) -> Response:
        async with desk_for(request, response) as desk:
            call = await own_call(desk, call_id)
            person_id = desk.viewer.person_id
        from ac_platform.lead_desk.telephony.pipeline import STATE, STORED

        intake = getattr(application.state, STATE, None)
        if intake is not None:
            async with ctx.sessions() as db:
                stored = (await intake.events(db, call)).get(STORED)
            if stored is not None:
                path = intake.path(call.tenant_id, call.id)
                if await anyio.to_thread.run_sync(path.is_file):
                    content = await anyio.to_thread.run_sync(path.read_bytes)
                    digest = hashlib.sha256(content).hexdigest()
                    if digest != stored["sha256"]:
                        raise HTTPException(
                            409, "The recording could not be verified.", headers=PRIVATE
                        )
                    async with ctx.sessions() as db, db.begin():
                        await ledger.recording_fetched(
                            db,
                            call,
                            person_id=person_id,
                            size=len(content),
                            sha256=digest,
                            now=datetime.now(UTC),
                        )
                    extension = "wav" if stored["content_type"] == "audio/wav" else "mp3"
                    filename = f"company-call.{extension}"
                    return Response(
                        content,
                        media_type=stored["content_type"],
                        headers={
                            **PRIVATE,
                            "X-Recording-Sha256": digest,
                            "Content-Disposition": f'attachment; filename="{filename}"',
                            "X-Content-Type-Options": "nosniff",
                        },
                    )
        found = provider()
        if not call.final or not call.recording or not call.sid:
            raise HTTPException(409, "There's no recording for this call yet.", headers=PRIVATE)
        if found is None or found.name != call.provider:
            raise HTTPException(409, policy.NOT_SET_UP.words, headers=PRIVATE)
        try:
            report = await found.report(call.sid)
            if not report.recording_url:
                raise providers.TelephonyError("The recording isn't ready yet.", status=409)
            recording = await found.fetch_recording(report.recording_url)
        except providers.TelephonyError as error:
            raise HTTPException(error.status, str(error), headers=PRIVATE) from None
        digest = hashlib.sha256(recording.content).hexdigest()
        async with ctx.sessions() as db, db.begin():
            await ledger.recording_fetched(
                db,
                call,
                person_id=person_id,
                size=len(recording.content),
                sha256=digest,
                now=datetime.now(UTC),
            )
        day = call.requested_at.astimezone(service.IST).strftime("%Y-%m-%d-%H%M")
        return Response(
            recording.content,
            media_type=recording.content_type,
            headers={
                **PRIVATE,
                "Content-Disposition": f'attachment; filename="company-call-{day}.mp3"',
                "X-Recording-Sha256": digest,
            },
        )

    # ----- the provider's side: its status webhook and the notice it plays ----------------

    async def status_webhook(
        name: str,
        tenant_id: UUID,
        call_id: UUID,
        mac: str,
        request: Request,
        background: BackgroundTasks,
    ) -> dict[str, str]:
        same_host(request)
        secret = (os.environ.get("AC_TELEPHONY_WEBHOOK_SECRET") or "").strip()
        found = provider()
        if (
            not secret
            or not hmac.compare_digest(mac, sign(secret, tenant_id, call_id))
            or found is None
            or found.name != name
        ):
            raise HTTPException(404, "Unknown call.", headers=NO_STORE)
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > _MAX_WEBHOOK:
                raise HTTPException(413, "That's too large.", headers=NO_STORE)
            raw.extend(chunk)
        now = datetime.now(UTC)
        # The signed address identifies a call; only its provider API supplies status
        # and recording URLs. Replaying or altering a callback cannot supply new facts.
        call = await service.refresh(ctx.sessions, found, tenant_id, call_id, now=now)
        from ac_platform.lead_desk.telephony.pipeline import STATE

        intake = getattr(application.state, STATE, None)
        if intake is not None and call is not None:
            background.add_task(intake.resume, found, tenant_id, call_id)
        return {"call": "final" if call is not None and call.final else "open"}

    @router.post("/telephony/{name}/status/{tenant_id}/{call_id}/{mac}")
    async def status_hook(
        name: str,
        tenant_id: UUID,
        call_id: UUID,
        mac: str,
        request: Request,
        background: BackgroundTasks,
    ) -> dict[str, str]:
        return await status_webhook(name, tenant_id, call_id, mac, request, background)

    @router.post("/meta/webhook/telephony/{name}/{tenant_id}/{call_id}/{mac}")
    async def status_hook_dev(
        name: str,
        tenant_id: UUID,
        call_id: UUID,
        mac: str,
        request: Request,
        background: BackgroundTasks,
    ) -> dict[str, str]:
        return await status_webhook(name, tenant_id, call_id, mac, request, background)

    def notice_audio(file_name: str, request: Request) -> Response:
        same_host(request)
        notice = policy.NOTICES.get(file_name.removesuffix(".wav"))
        if notice is None or not file_name.endswith(".wav"):
            raise HTTPException(404, "No such notice.", headers=NO_STORE)
        return Response(
            (NOTICES_DIR / notice.file).read_bytes(),
            media_type="audio/wav",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @router.get("/telephony/notice/{file_name}")
    def notice(file_name: str, request: Request) -> Response:
        return notice_audio(file_name, request)

    @router.get("/meta/webhook/telephony/notice/{file_name}")
    def notice_dev(file_name: str, request: Request) -> Response:
        return notice_audio(file_name, request)

    application.include_router(router)
