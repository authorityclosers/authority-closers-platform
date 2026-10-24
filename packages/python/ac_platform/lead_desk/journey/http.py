"""Lead stages routes for the Sales Xray CRM (/v1/lead-desk/journey).

- ``GET /journey``: the business's stages, what each means, and how many leads sit in
  each (everyone in the workspace: sellers pick from them). Owners and admins change
  them: ``PUT /journey`` (the whole list), ``POST /journey/template`` (an industry
  profile), ``POST /journey/guess`` (what a name probably means, while typing).
- ``GET /journey/templates``: the industry profiles.
- ``GET /journey/history``: the last saves, newest first.
- ``POST /leads/{id}/stage``: move a lead to one of the business's stages without a
  call ("Site visit done"); the lead's owner or a manager. Lead OS (24 Oct 2026): the
  move goes through the stage list's moves (409 says where it can go), and gives what
  the stage needs (422 says what): a Lost or Junk reason, why a call didn't connect,
  the next follow-up, or the meeting.
- ``POST /leads/{id}/reopen``: back to work from Won, Lost or Junk, on the same lead.
- ``POST /leads/{id}/meetings`` books or moves the lead's meeting;
  ``POST /meetings/{id}/done`` (it happened) and ``POST /meetings/{id}/not-held``
  (missed or cancelled, and where the lead stands now).
- ``GET /board`` (every live stage as a column, each lead once) and
  ``GET /board/column`` (the next cards of one column).
- ``GET /journey/ads``: every ad platform: set up or not, where stages go, each stage's
  match in plain words, and what went lately. ``PUT /journey/ads/{platform}`` sets
  where and whether; ``PUT /journey/ads/{platform}/matches`` confirms matches;
  ``POST /journey/ads/events/{id}/retry`` tries a refused event again.
- ``GET /journey/summary``: one line for Connected apps.
- ``GET /pipelines``, ``POST /pipelines`` (a name, a kind of business and the lead
  sources it takes) and ``PATCH /pipelines/{key}``: the organisation's pipelines. Every
  stage route above takes ``?pipeline=`` (default ``main``); a lead's own routes use its
  pipeline.

Same workspace rule as the CRM's own routes: an organisation workspace, an active
member. Nothing here shows a price or cost.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import select

from ac_platform.conversation_intelligence.sales_xray_tenants import SALES_XRAY_MEMBER_ROLES
from ac_platform.http.auth import require_safe_origin
from ac_platform.http.routes import RouteContext
from ac_platform.identity.models import Person
from ac_platform.kernel.errors import DomainError
from ac_platform.lead_desk import meetings as meeting_rows
from ac_platform.lead_desk.contracts import (
    Board,
    Contact,
    LeadDetail,
    MeetingClosed,
    MeetingCommand,
    MeetingDone,
    MeetingInput,
    MeetingMode,
    MoveVia,
    PipelineReport,
    Reopen,
    StageMove,
)
from ac_platform.lead_desk.journey import catalogue, engine, mapping, pipelines, signals
from ac_platform.lead_desk.journey import model as journeys
from ac_platform.lead_desk.journey.model import Journey, JourneyError
from ac_platform.lead_desk.journey.providers import oauth
from ac_platform.lead_desk.journey.templates import (
    KIND_WORDS,
    MILESTONE_KIND,
    MILESTONE_WORDS,
    TEMPLATES,
    guess_milestone,
)
from ac_platform.lead_desk.models import LeadDeskSettings, LeadJourneyVersion
from ac_platform.lead_desk.store import DeskError, LeadDesk, Viewer, owner_names, person_name
from ac_platform.lead_desk.vocabulary import Reason
from ac_platform.tenancy.models import Membership, Organisation

PRIVATE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}
NO_STORE = {"Cache-Control": "no-store"}


class _Command(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)


class _View(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


# ----- shapes -----------------------------------------------------------------------------


class ReasonItem(_View):
    key: str
    label: str


class StageView(_View):
    key: str
    label: str
    kind: str
    kind_words: str = Field(alias="kindWords")
    milestone: str
    meaning: str
    archived: bool
    origin: str
    leads: int
    # Lead OS: where a lead may go from it (None: anywhere), what it asks on the way
    # in, its Lost or Junk reasons, and how long a lead may sit in it.
    moves: list[str] | None = None
    needs: list[str] | None = None
    reasons: list[ReasonItem] | None = None
    rot_hours: int | None = Field(default=None, alias="rotHours")


class JourneyView(_View):
    version: int
    industry: str | None
    saved_at: datetime | None = Field(alias="savedAt")
    saved_by: str | None = Field(alias="savedBy")
    stages: list[StageView]
    can_edit: bool = Field(alias="canEdit")
    kinds: dict[str, str]
    meanings: dict[str, str]
    pipeline: str = "main"


class PipelineView(_View):
    key: str
    name: str
    position: int
    main: bool
    # The lead source kinds whose new leads come here; main takes every other one.
    sources: list[str]
    industry: str | None
    leads: int


class PipelinesView(_View):
    pipelines: list[PipelineView]
    # Every lead source a pipeline can take, in the page's words.
    sources: dict[str, str]
    can_edit: bool = Field(alias="canEdit")


class PipelineCommand(_Command):
    name: str = Field(min_length=1, max_length=60)
    template: str = Field(min_length=1, max_length=40)
    sources: list[str] = Field(default_factory=list, max_length=12)


class PipelineChange(_Command):
    name: str | None = Field(default=None, max_length=60)
    sources: list[str] | None = Field(default=None, max_length=12)


class TemplateStageView(_View):
    label: str
    kind: str
    milestone: str


class TemplateView(_View):
    id: str
    name: str
    blurb: str
    icon: str
    stages: list[TemplateStageView]


class ReasonCommand(_Command):
    key: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=60)


class StageCommand(_Command):
    key: str | None = Field(default=None, max_length=40)
    label: str = Field(max_length=60)
    kind: str | None = Field(default=None, max_length=16)
    milestone: str | None = Field(default=None, max_length=24)
    archived: bool = False
    origin: str | None = Field(default=None, max_length=16)
    ref: str | None = Field(default=None, max_length=80)
    # Lead OS rules; left out, a stage keeps what it had.
    moves: list[str] | None = Field(default=None, max_length=journeys.MAX_LIVE)
    needs: list[str] | None = Field(default=None, max_length=6)
    reasons: list[ReasonCommand] | None = Field(default=None, max_length=journeys.MAX_REASONS)
    rot_hours: int | None = Field(default=None, alias="rotHours", ge=1, le=journeys.MAX_ROT_HOURS)


class JourneyCommand(_Command):
    expected_version: int = Field(alias="expectedVersion", ge=0)
    stages: list[StageCommand] = Field(min_length=1, max_length=journeys.MAX_ALL)


class TemplateCommand(_Command):
    expected_version: int = Field(alias="expectedVersion", ge=0)
    template: str = Field(max_length=40)
    # Where the leads of today's columns go (today's stage key -> the new list's stage
    # key); a column left out keeps its leads where they stand (Lead OS, L4).
    places: dict[str, str] = Field(default_factory=dict, alias="map")


class TemplateLanding(_View):
    """Where the leads of one current stage land under a new list (Lead OS, L4)."""

    from_key: str = Field(alias="fromKey")
    from_label: str = Field(alias="fromLabel")
    to_label: str = Field(alias="toLabel")
    to_key: str = Field(alias="toKey")
    leads: int
    # The new list's stages these leads may be put in instead (the install's map).
    choices: list[str]


def wanted(command: TemplateCommand) -> dict[str, str]:
    """The install's map, bounded: one entry per stage of today's list at most."""
    if len(command.places) > journeys.MAX_ALL:
        raise JourneyError("Pick where leads go for fewer stages.")
    return dict(command.places)


class TemplatePreview(_View):
    template: str
    stages: list[StageView]
    landings: list[TemplateLanding]


class GuessCommand(_Command):
    label: str = Field(max_length=60)


class GuessView(_View):
    milestone: str
    meaning: str
    kind: str
    kind_words: str = Field(alias="kindWords")


class HistoryItem(_View):
    version: int
    note: str
    by: str | None
    at: datetime


class MeetingBody(_Command):
    starts_at: AwareDatetime = Field(alias="startsAt")
    duration_minutes: int = Field(default=30, alias="durationMinutes", ge=5, le=480)
    mode: MeetingMode
    link: str | None = Field(default=None, max_length=500)
    location: str | None = Field(default=None, max_length=300)
    agenda: str | None = Field(default=None, max_length=1000)

    def as_input(self) -> MeetingInput:
        return MeetingInput(
            starts_at=self.starts_at,
            duration_minutes=self.duration_minutes,
            mode=self.mode,
            link=self.link,
            location=self.location,
            agenda=self.agenda,
        )


class MoveCommand(_Command):
    command_id: UUID = Field(alias="commandId")
    expected_revision: int = Field(alias="expectedRevision", ge=1)
    step: str = Field(max_length=40)
    note: str | None = Field(default=None, max_length=500)
    # Lead OS: what the stage asks for (only what it needs is required).
    reason: str | None = Field(default=None, max_length=40)
    reason_note: str | None = Field(default=None, alias="reasonNote", max_length=500)
    nc_reason: Reason | None = Field(default=None, alias="ncReason")
    next_action_at: AwareDatetime | None = Field(default=None, alias="nextActionAt")
    next_action_note: str | None = Field(default=None, alias="nextActionNote", max_length=500)
    meeting: MeetingBody | None = None
    contact: Contact | None = None
    source: Literal["seller", "ai_suggestion"] = "seller"
    suggestion_ref: str | None = Field(default=None, alias="suggestionRef", max_length=120)
    via: MoveVia | None = None

    def as_move(self) -> StageMove:
        return StageMove(
            command_id=self.command_id,
            expected_revision=self.expected_revision,
            step=self.step,
            note=self.note,
            outcome_reason=self.reason,
            reason_note=self.reason_note,
            nc_reason=self.nc_reason,
            next_action_at=self.next_action_at,
            next_action_note=self.next_action_note,
            meeting=self.meeting.as_input() if self.meeting else None,
            contact=self.contact,
            source=self.source,
            suggestion_ref=self.suggestion_ref,
            via=self.via,
        )


class MoveView(_View):
    lead_id: UUID = Field(alias="leadId")
    revision: int
    stage: str
    step: str
    step_label: str = Field(alias="stepLabel")
    stage_at: datetime | None = Field(default=None, alias="stageAt")
    meeting_id: UUID | None = Field(default=None, alias="meetingId")


class MatchView(_View):
    stage_key: str = Field(alias="stageKey")
    stage_label: str = Field(alias="stageLabel")
    kind: str
    milestone: str
    suggested: str | None
    saved: str | None
    state: Literal["on", "off", "new"]
    words: str | None


class AdEventView(_View):
    id: UUID
    provider: str
    lead_id: UUID = Field(alias="leadId")
    lead_name: str = Field(alias="leadName")
    stage_label: str = Field(alias="stageLabel")
    event_name: str = Field(alias="eventName")
    status: str
    attempts: int
    event_time: datetime = Field(alias="eventTime")
    delivered_at: datetime | None = Field(alias="deliveredAt")
    error: str | None
    test: bool


class OptionView(_View):
    id: str
    words: str


class ProviderView(_View):
    id: str
    name: str
    brand: str
    naming: str
    learns: str
    reaches: str
    destination_words: str = Field(alias="destinationWords")
    manual_destination: str | None = Field(default=None, alias="manualDestination")
    connect_path: str | None = Field(default=None, alias="connectPath")
    available: bool
    configured: bool
    connected: bool
    destination: dict[str, str] | None
    on: bool
    test_code: str | None = Field(alias="testCode")
    since: datetime | None
    matches: list[MatchView]
    options: list[OptionView] = Field(default_factory=list)
    needs_check: int = Field(alias="needsCheck")
    confirmed_at: datetime | None = Field(alias="confirmedAt")
    counts: dict[str, int]
    last_delivered_at: datetime | None = Field(alias="lastDeliveredAt")
    waiting_on: str | None = Field(alias="waitingOn")


class AdsView(_View):
    version: int
    providers: list[ProviderView]
    recent: list[AdEventView]
    settling: int
    sends_at: datetime | None = Field(alias="sendsAt")


class DestinationCommand(_Command):
    destination_id: str = Field(alias="destinationId", min_length=1, max_length=64)
    destination_name: str = Field(alias="destinationName", min_length=1, max_length=120)
    on: bool
    test_code: str | None = Field(default=None, alias="testCode", max_length=32)


class QualityView(_View):
    score: float
    events: int
    keys: dict[str, int]


class DestinationView(_View):
    id: str
    name: str


class MatchesCommand(_Command):
    expected_version: int = Field(alias="expectedVersion", ge=0)
    events: dict[str, str | None]


class SuggestionView(_View):
    ref: str
    label: str
    source: str
    workflow: str
    milestone: str
    meaning: str
    kind: str
    kind_words: str = Field(alias="kindWords")


class LeadSuggestionView(_View):
    step: str
    label: str
    kind: str
    why: str
    at: datetime


class SummaryView(_View):
    stages: int
    industry: str | None
    providers_on: list[str] = Field(alias="providersOn")
    needs_check: int = Field(alias="needsCheck")
    last_delivered_at: datetime | None = Field(alias="lastDeliveredAt")


# Where each platform's Connect starts (Meta and Google: Lead sources' own routes).
CONNECT_PATHS: dict[str, str] = {
    "meta": "/v1/lead-desk/meta/connect",
    "google_ads": "/v1/lead-desk/google/connect",
    **{provider: f"/v1/lead-desk/{slug}/connect" for provider, slug in oauth.SLUGS.items()},
}

# Planned platforms, shown as coming while their adapters are not here yet.
_COMING: dict[str, tuple[str, str]] = {
    "google_ads": ("Google Ads", "googleads"),
    "linkedin": ("LinkedIn", "linkedin"),
    "tiktok": ("TikTok", "tiktok"),
    "microsoft_ads": ("Microsoft Ads", "microsoft"),
}


def waiting_words(provider: str, code: str | None) -> str | None:
    """Why events wait on the customer, in words, or None when nothing waits on them."""
    if code is None:
        return None
    if provider == "meta":
        if code in ("meta_190", "meta_102", "not_connected"):
            return "Meta ended the connection. Continue with Meta again to keep sending stages."
        if code in ("meta_10", "meta_3") or (code.startswith("meta_2") and len(code) == 8):
            return (
                "Meta didn't allow sending to this dataset. Continue with Meta again and allow "
                "your ad account and dataset."
            )
    if provider == "google_ads":
        if "customer_data_terms" in code or "enhanced_conversions" in code:
            return (
                "In Google Ads, open Goals → Settings, accept the customer data terms and "
                "turn on enhanced conversions for leads."
            )
        if code in ("not_connected", "google_no_action") or "permission" in code:
            return "Continue with Google again and allow Sales Xray to manage conversions."
        if "developer_token" in code:
            return "Google hasn't approved Sales Xray for live accounts yet. Test accounts work."
    if code == "not_connected":
        return "Connect it again to keep sending stages."
    return None


def _epoch(value: int | None) -> datetime | None:
    return datetime.fromtimestamp(value, UTC) if value else None


def journey_view(journey: Journey, counts: dict[str, int], can_edit: bool) -> JourneyView:
    return JourneyView(
        version=journey.version,
        industry=journey.industry,
        saved_at=journey.saved_at,
        saved_by=str(journey.saved_by) if journey.saved_by else None,
        stages=[
            StageView(
                key=stage.key,
                label=stage.label,
                kind=stage.kind,
                kind_words=KIND_WORDS[stage.kind],
                milestone=stage.milestone,
                meaning=MILESTONE_WORDS[stage.milestone],
                archived=stage.archived,
                origin=stage.origin,
                leads=counts.get(stage.key, 0),
                moves=list(stage.moves) if stage.moves is not None else None,
                needs=list(stage.needs) if stage.needs is not None else None,
                reasons=[ReasonItem(key=key, label=label) for key, label in stage.reasons]
                if stage.reasons is not None
                else None,
                rot_hours=stage.rot_hours,
            )
            for stage in journey.stages
        ],
        can_edit=can_edit,
        kinds=dict(KIND_WORDS),
        meanings=dict(MILESTONE_WORDS),
        pipeline=journey.pipeline,
    )


def match_words(provider: str, name: str | None) -> str | None:
    if name is None:
        return None
    option = mapping.spec(provider).option(name)
    return option.words if option else f"“{name}”"


def install_journey_http(application: FastAPI, ctx: RouteContext) -> None:
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
        except JourneyError as error:
            raise HTTPException(422, str(error), headers=PRIVATE) from None
        except DeskError as error:
            raise HTTPException(error.status, str(error), headers=PRIVATE) from None
        except DomainError:
            raise HTTPException(401, "Sign in to see your leads.", headers=PRIVATE) from None

    async def current(desk: LeadDesk, pipeline: str = journeys.MAIN_PIPELINE) -> JourneyView:
        journey = await journeys.read(desk.db, desk.tenant_id, pipeline)
        counts = await journeys.lead_counts(desk.db, desk.tenant_id, journey)
        return journey_view(journey, counts, desk.viewer.can_manage)

    async def known(desk: LeadDesk, key: str) -> str:
        """The pipeline's key, when the organisation has it (422 otherwise)."""
        return pipelines.find(await pipelines.listed(desk.db, desk.tenant_id), key).key

    async def pipelines_view(desk: LeadDesk) -> PipelinesView:
        found = await pipelines.listed(desk.db, desk.tenant_id)
        totals = await pipelines.lead_totals(desk.db, desk.tenant_id)
        views = []
        for item in found:
            journey = await journeys.read(desk.db, desk.tenant_id, item.key)
            views.append(
                PipelineView(
                    key=item.key,
                    name=item.name,
                    position=item.position,
                    main=item.main,
                    sources=list(item.sources),
                    industry=journey.industry,
                    leads=totals.get(item.key, 0),
                )
            )
        return PipelinesView(
            pipelines=views, sources=dict(pipelines.SOURCES), can_edit=desk.viewer.can_manage
        )

    # ----- pipelines ----------------------------------------------------------------------

    @router.get("/pipelines", response_model=PipelinesView, response_model_by_alias=True)
    async def list_pipelines(request: Request, response: Response) -> PipelinesView:
        async with desk_for(request, response) as desk:
            return await pipelines_view(desk)

    @router.post("/pipelines", response_model=PipelinesView, response_model_by_alias=True)
    async def create_pipeline(
        command: PipelineCommand, request: Request, response: Response
    ) -> PipelinesView:
        """A new pipeline with a kind of business's stages, taking the sources picked."""
        async with desk_for(request, response, write=True) as desk:
            desk._require_manager()
            profile = next((item for item in TEMPLATES if item.id == command.template), None)
            if profile is None:
                raise JourneyError("Pick one of the listed kinds of business.")
            made = await pipelines.create(
                desk.db,
                desk.tenant_id,
                name=command.name,
                sources=command.sources,
                by=desk.viewer.person_id,
                now=desk.now,
            )
            before = await journeys.read(desk.db, desk.tenant_id, made.key)
            await journeys.save(
                desk.db,
                desk.tenant_id,
                stages=journeys.from_template(command.template, before, {}),
                industry=command.template,
                expected_version=before.version,
                note=f"Used the {profile.name} stages",
                by=desk.viewer.person_id,
                now=desk.now,
                pipeline=made.key,
            )
            return await pipelines_view(desk)

    @router.patch("/pipelines/{key}", response_model=PipelinesView, response_model_by_alias=True)
    async def change_pipeline(
        key: str, command: PipelineChange, request: Request, response: Response
    ) -> PipelinesView:
        """Rename a pipeline, or pick the lead sources whose new leads come to it."""
        async with desk_for(request, response, write=True) as desk:
            desk._require_manager()
            await pipelines.change(
                desk.db,
                desk.tenant_id,
                key,
                name=command.name,
                sources=command.sources,
                by=desk.viewer.person_id,
                now=desk.now,
            )
            return await pipelines_view(desk)

    async def lock_settings(desk: LeadDesk) -> LeadDeskSettings:
        """The workspace's Lead Desk settings row, locked; made when missing. Writing
        these parts never moves the revision (not the team settings form)."""
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
        return row

    # ----- stages -------------------------------------------------------------------------

    @router.get("/journey", response_model=JourneyView, response_model_by_alias=True)
    async def journey(
        request: Request,
        response: Response,
        pipeline: str = Query(default=journeys.MAIN_PIPELINE, max_length=40),
    ) -> JourneyView:
        async with desk_for(request, response) as desk:
            return await current(desk, await known(desk, pipeline))

    @router.get(
        "/journey/templates", response_model=list[TemplateView], response_model_by_alias=True
    )
    async def journey_templates(request: Request, response: Response) -> list[TemplateView]:
        async with desk_for(request, response):
            return [
                TemplateView(
                    id=item.id,
                    name=item.name,
                    blurb=item.blurb,
                    icon=item.icon,
                    stages=[
                        TemplateStageView(label=s.label, kind=s.kind, milestone=s.milestone)
                        for s in item.stages
                    ],
                )
                for item in TEMPLATES
            ]

    @router.put("/journey", response_model=JourneyView, response_model_by_alias=True)
    async def save_journey(
        command: JourneyCommand,
        request: Request,
        response: Response,
        pipeline: str = Query(default=journeys.MAIN_PIPELINE, max_length=40),
    ) -> JourneyView:
        async with desk_for(request, response, write=True) as desk:
            desk._require_manager()
            key = await known(desk, pipeline)
            before = await journeys.read(desk.db, desk.tenant_id, key)
            counts = await journeys.lead_counts(desk.db, desk.tenant_id, before)
            stages = journeys.build(
                [item.model_dump(exclude_none=True) for item in command.stages], before, counts
            )
            await journeys.save(
                desk.db,
                desk.tenant_id,
                stages=stages,
                industry=before.industry,
                expected_version=command.expected_version,
                note=journeys.change_note(before, stages),
                by=desk.viewer.person_id,
                now=desk.now,
                pipeline=key,
            )
            return await current(desk, key)

    @router.post("/journey/template", response_model=JourneyView, response_model_by_alias=True)
    async def use_template(
        command: TemplateCommand,
        request: Request,
        response: Response,
        pipeline: str = Query(default=journeys.MAIN_PIPELINE, max_length=40),
    ) -> JourneyView:
        async with desk_for(request, response, write=True) as desk:
            desk._require_manager()
            key = await known(desk, pipeline)
            before = await journeys.read(desk.db, desk.tenant_id, key)
            counts = await journeys.lead_counts(desk.db, desk.tenant_id, before)
            stages = journeys.from_template(command.template, before, counts)
            profile = next(item for item in TEMPLATES if item.id == command.template)
            draft = Journey(before.version + 1, command.template, stages, pipeline=key)
            places = journeys.check_places(before, draft, wanted(command))
            after = await journeys.save(
                desk.db,
                desk.tenant_id,
                stages=stages,
                industry=command.template,
                expected_version=command.expected_version,
                note=f"Used the {profile.name} stages",
                by=desk.viewer.person_id,
                now=desk.now,
                pipeline=key,
            )
            await desk.place_leads(before, after, places)
            return await current(desk, key)

    @router.post(
        "/journey/template/preview",
        response_model=TemplatePreview,
        response_model_by_alias=True,
    )
    async def preview_template(
        command: TemplateCommand,
        request: Request,
        response: Response,
        pipeline: str = Query(default=journeys.MAIN_PIPELINE, max_length=40),
    ) -> TemplatePreview:
        """What a kind of business's stages would look like here, and where today's leads
        would land, before anything is saved (the builder's Preview and Done steps)."""
        async with desk_for(request, response, write=True) as desk:
            desk._require_manager()
            key = await known(desk, pipeline)
            before = await journeys.read(desk.db, desk.tenant_id, key)
            counts = await journeys.lead_counts(desk.db, desk.tenant_id, before)
            stages = journeys.from_template(command.template, before, counts)
            after = Journey(before.version + 1, command.template, stages, pipeline=key)
            places = journeys.check_places(before, after, wanted(command))
            choices = journeys.place_choices(before, after)
            landings: dict[tuple[str, str], int] = {}
            for (kind, step), leads in (
                await journeys.lead_pairs(desk.db, desk.tenant_id, before)
            ).items():
                old = before.column(kind, step)
                new = journeys.landing(before, after, places, kind, step)
                pair = (old.key, new.key)
                landings[pair] = landings.get(pair, 0) + leads
            old_labels = {stage.key: stage.label for stage in before.board()}
            labels = {stage.key: stage.label for stage in after.board()}
            view = journey_view(after, {}, True)
            return TemplatePreview(
                template=command.template,
                stages=view.stages,
                landings=[
                    TemplateLanding(
                        from_key=old,
                        from_label=old_labels.get(old, old),
                        to_label=labels.get(new, new),
                        to_key=new,
                        leads=leads,
                        choices=list(choices.get(old, ())),
                    )
                    for (old, new), leads in sorted(landings.items(), key=lambda item: -item[1])
                ],
            )

    @router.post("/journey/guess", response_model=GuessView, response_model_by_alias=True)
    async def guess(command: GuessCommand, request: Request, response: Response) -> GuessView:
        async with desk_for(request, response):
            milestone = guess_milestone(command.label)
            kind = MILESTONE_KIND[milestone]
            return GuessView(
                milestone=milestone,
                meaning=MILESTONE_WORDS[milestone],
                kind=kind,
                kind_words=KIND_WORDS[kind],
            )

    @router.get(
        "/journey/suggestions",
        response_model=list[SuggestionView],
        response_model_by_alias=True,
    )
    async def suggestions(
        request: Request,
        response: Response,
        pipeline: str = Query(default=journeys.MAIN_PIPELINE, max_length=40),
    ) -> list[SuggestionView]:
        """Stages the business already uses in an app it connected (Pulse's workflow steps)
        that aren't stages here yet. Offered only: a manager adds one with a tap."""
        async with desk_for(request, response) as desk:
            desk._require_manager()
            row = await desk.db.get(LeadDeskSettings, desk.tenant_id)
            journey = await journeys.read(desk.db, desk.tenant_id, await known(desk, pipeline))
            found = catalogue.suggestions((row.config if row else None) or {}, journey)
            counts, terms = await signals.heard(desk.db, desk.tenant_id, desk.now)
            found += signals.business_suggestions(counts, terms, journey)
            return [SuggestionView(**item) for item in found]

    @router.get(
        "/leads/{lead_id}/stage-suggestion",
        response_model=LeadSuggestionView | None,
        response_model_by_alias=True,
    )
    async def lead_suggestion(
        lead_id: UUID, request: Request, response: Response
    ) -> LeadSuggestionView | None:
        """Where this lead's newest call says it got to, when that is further than its
        stage (null otherwise). Offered on the lead; a person confirms the move."""
        async with desk_for(request, response) as desk:
            lead = await desk._lead(lead_id)
            if not (desk.viewer.can_manage or lead.owner_person_id == desk.viewer.person_id):
                raise DeskError(403, "Only the lead's owner or a manager sees this.")
            journey = await journeys.read(desk.db, desk.tenant_id, journeys.pipeline_of(lead))
            found = await signals.lead_suggestion(
                desk.db, desk.tenant_id, lead.id, lead.stage, lead.step, journey
            )
            return LeadSuggestionView(**found) if found else None

    @router.get("/journey/history", response_model=list[HistoryItem], response_model_by_alias=True)
    async def history(
        request: Request,
        response: Response,
        pipeline: str = Query(default=journeys.MAIN_PIPELINE, max_length=40),
    ) -> list[HistoryItem]:
        async with desk_for(request, response) as desk:
            desk._require_manager()
            rows = (
                await desk.db.scalars(
                    select(LeadJourneyVersion)
                    .where(
                        LeadJourneyVersion.tenant_id == desk.tenant_id,
                        journeys.version_in(pipeline),
                    )
                    .order_by(LeadJourneyVersion.version.desc())
                    .limit(20)
                )
            ).all()
            names = await owner_names(desk.db, (row.created_by_person_id for row in rows))
            return [
                HistoryItem(
                    version=row.version,
                    note=row.note,
                    by=names.get(row.created_by_person_id) if row.created_by_person_id else None,
                    at=row.created_at,
                )
                for row in rows
            ]

    @router.post("/leads/{lead_id}/stage", response_model=MoveView, response_model_by_alias=True)
    async def move(
        lead_id: UUID, command: MoveCommand, request: Request, response: Response
    ) -> MoveView:
        """A lead moves to one of the business's stages without a call, through its
        stage list's moves (Lead OS). The same lead, one history line."""
        async with desk_for(request, response, write=True) as desk:
            lead = await desk.move(lead_id, command.as_move())
            # The lead's own pipeline's stages.
            journey = await journeys.read(desk.db, desk.tenant_id, journeys.pipeline_of(lead))
            shown = journey.resolve(lead.stage, lead.step)
            meeting = await meeting_rows.open_meeting(desk.db, desk.tenant_id, lead.id)
            return MoveView(
                lead_id=lead.id,
                revision=lead.revision,
                stage=lead.stage,
                step=shown.key if shown else lead.stage,
                step_label=shown.label if shown else lead.stage,
                stage_at=lead.stage_at,
                meeting_id=meeting.id if meeting else None,
            )

    @router.post("/leads/{lead_id}/reopen", response_model=LeadDetail, response_model_by_alias=True)
    async def reopen(
        lead_id: UUID, command: Reopen, request: Request, response: Response
    ) -> LeadDetail:
        """Back to work from Won, Lost or Junk: the stage it was closed from unless another
        is picked, with the next follow-up. Its history stays."""
        async with desk_for(request, response, write=True) as desk:
            lead = await desk.reopen(lead_id, command)
            return await desk.detail(lead.id)

    @router.post(
        "/leads/{lead_id}/meetings", response_model=LeadDetail, response_model_by_alias=True
    )
    async def schedule_meeting(
        lead_id: UUID, command: MeetingCommand, request: Request, response: Response
    ) -> LeadDetail:
        """Book the lead's meeting, or move the one booked (it stays one meeting)."""
        async with desk_for(request, response, write=True) as desk:
            lead = await desk.schedule_meeting(lead_id, command)
            return await desk.detail(lead.id)

    @router.post(
        "/meetings/{meeting_id}/done", response_model=LeadDetail, response_model_by_alias=True
    )
    async def meeting_done(
        meeting_id: UUID, command: MeetingDone, request: Request, response: Response
    ) -> LeadDetail:
        async with desk_for(request, response, write=True) as desk:
            lead = await desk.meeting_done(meeting_id, command)
            return await desk.detail(lead.id)

    @router.post(
        "/meetings/{meeting_id}/not-held",
        response_model=LeadDetail,
        response_model_by_alias=True,
    )
    async def meeting_not_held(
        meeting_id: UUID, command: MeetingClosed, request: Request, response: Response
    ) -> LeadDetail:
        async with desk_for(request, response, write=True) as desk:
            lead = await desk.meeting_not_held(meeting_id, command)
            return await desk.detail(lead.id)

    @router.get("/reports/pipeline", response_model=PipelineReport, response_model_by_alias=True)
    async def pipeline_report(
        request: Request,
        response: Response,
        days: int = Query(default=30),
        pipeline: str = Query(default=journeys.MAIN_PIPELINE, min_length=1, max_length=40),
        owner: UUID | None = None,
        source: str | None = Query(default=None, max_length=16),
    ) -> PipelineReport:
        """The pipeline's numbers: each lead once; conversions from history, Junk left
        out; Lost reasons, Junk by source, overdue and no next step; per seller and
        source. A seller sees their own leads' numbers."""
        async with desk_for(request, response) as desk:
            return await desk.pipeline_report(
                days=days, pipeline=pipeline, owner=owner, source=source
            )

    @router.get("/board", response_model=Board, response_model_by_alias=True)
    async def board(
        request: Request,
        response: Response,
        pipeline: str = Query(default=journeys.MAIN_PIPELINE, min_length=1, max_length=40),
        owner: UUID | None = None,
        source: str | None = Query(default=None, max_length=16),
        q: str | None = Query(default=None, max_length=80),
    ) -> Board:
        """The pipeline board: every live stage a column, grouped Active, Won, Lost and
        Junk, each lead in exactly one column; the first cards of each."""
        async with desk_for(request, response) as desk:
            return await desk.board(pipeline=pipeline, owner=owner, source=source, search=q)

    @router.get("/board/column", response_model=Board, response_model_by_alias=True)
    async def board_column(
        request: Request,
        response: Response,
        step: str = Query(min_length=1, max_length=40),
        cursor: int = Query(default=0, ge=0, le=100_000),
        pipeline: str = Query(default=journeys.MAIN_PIPELINE, min_length=1, max_length=40),
        owner: UUID | None = None,
        source: str | None = Query(default=None, max_length=16),
        q: str | None = Query(default=None, max_length=80),
    ) -> Board:
        """One column's next cards (the board's "Show more")."""
        async with desk_for(request, response) as desk:
            return await desk.board(
                pipeline=pipeline,
                owner=owner,
                source=source,
                search=q,
                step=step,
                cursor=cursor,
            )

    # ----- ad platforms -----------------------------------------------------------------

    async def ads_view(desk: LeadDesk) -> AdsView:
        row = await desk.db.get(LeadDeskSettings, desk.tenant_id)
        config = dict((row.config if row else None) or {})
        journey = await journeys.read(desk.db, desk.tenant_id)
        facts = await engine.summary(desk.db, desk.tenant_id, desk.now)
        waits, sends_at = await engine.settling(desk.db, desk.tenant_id, config, journey, desk.now)
        providers: list[ProviderView] = []
        for provider in mapping.available():
            adapter = mapping.module(provider)
            info = mapping.spec(provider)
            saved = mapping.read(config, provider)
            found = mapping.matches(provider, journey, saved)
            providers.append(
                ProviderView(
                    id=provider,
                    name=info.name,
                    brand=info.brand,
                    naming=info.naming,
                    learns=info.learns,
                    reaches=info.reaches,
                    destination_words=info.destination,
                    manual_destination=getattr(adapter, "MANUAL", None),
                    connect_path=CONNECT_PATHS.get(provider),
                    available=True,
                    configured=adapter.configured(),
                    connected=await mapping.is_connected(provider, desk.db, desk.tenant_id, config),
                    destination={
                        "id": saved.destination_id,
                        "name": saved.destination_name or saved.destination_id,
                    }
                    if saved.destination_id
                    else None,
                    on=saved.on,
                    test_code=saved.test_code,
                    since=_epoch(saved.since),
                    options=[OptionView(id=item.id, words=item.words) for item in info.options],
                    matches=[
                        MatchView(
                            stage_key=item.stage.key,
                            stage_label=item.stage.label,
                            kind=item.stage.kind,
                            milestone=item.stage.milestone,
                            suggested=item.suggested,
                            saved=item.saved,
                            state=item.state,
                            words=match_words(
                                provider, item.saved if item.state != "new" else item.suggested
                            ),
                        )
                        for item in found
                    ],
                    needs_check=sum(
                        1 for item in found if item.state == "new" and item.suggested is not None
                    ),
                    confirmed_at=_epoch(saved.confirmed_at),
                    counts=facts["counts"].get(provider, {}),
                    last_delivered_at=facts["last_delivered_at"].get(provider),
                    waiting_on=waiting_words(provider, facts["waiting_on"].get(provider)),
                )
            )
        for provider, (name, brand) in _COMING.items():
            if provider in mapping.MODULES:
                continue
            providers.append(
                ProviderView(
                    id=provider,
                    name=name,
                    brand=brand,
                    naming="action",
                    learns="",
                    reaches="",
                    destination_words="",
                    available=False,
                    configured=False,
                    connected=False,
                    destination=None,
                    on=False,
                    test_code=None,
                    since=None,
                    matches=[],
                    needs_check=0,
                    confirmed_at=None,
                    counts={},
                    last_delivered_at=None,
                    waiting_on=None,
                )
            )
        labels = {stage.key: stage.label for stage in journey.stages}
        return AdsView(
            version=journey.version,
            providers=providers,
            recent=[
                AdEventView(
                    id=item["id"],
                    provider=item["provider"],
                    lead_id=item["lead_id"],
                    lead_name=item["lead_name"],
                    stage_label=labels.get(item["stage_key"], item["event_name"]),
                    event_name=item["event_name"],
                    status=item["status"],
                    attempts=item["attempts"],
                    event_time=item["event_time"],
                    delivered_at=item["delivered_at"],
                    error=item["error"],
                    test=item["test"],
                )
                for item in facts["recent"]
            ],
            settling=waits,
            sends_at=sends_at,
        )

    @router.get("/journey/ads", response_model=AdsView, response_model_by_alias=True)
    async def ads(request: Request, response: Response) -> AdsView:
        async with desk_for(request, response) as desk:
            desk._require_manager()
            return await ads_view(desk)

    @router.put("/journey/ads/{provider}", response_model=AdsView, response_model_by_alias=True)
    async def save_destination(
        provider: str, command: DestinationCommand, request: Request, response: Response
    ) -> AdsView:
        async with desk_for(request, response, write=True) as desk:
            desk._require_manager()
            adapter = mapping.module(provider)
            if not adapter.DESTINATION.fullmatch(command.destination_id):
                info = adapter.SPEC
                raise DeskError(422, f"Pick one of your {info.name} {info.destination}s.")
            if command.test_code and not adapter.TEST_CODE.fullmatch(command.test_code):
                raise DeskError(422, "Copy the test code exactly as the platform shows it.")
            extra: dict[str, Any] = {}
            prepare = getattr(adapter, "prepare", None)
            if command.on and prepare is not None:
                # Before any lock: this asks the platform (Google makes its conversion
                # actions in the business's account).
                try:
                    async with httpx.AsyncClient(timeout=20) as client:
                        extra = await prepare(
                            desk.db, desk.tenant_id, command.destination_id, client
                        )
                except ValueError as error:
                    raise DeskError(409, str(error)) from None
            row = await lock_settings(desk)
            config = dict(row.config or {})
            if command.on and not mapping.read(config, provider).events:
                # First switch-on: the engine's matches are confirmed with it.
                journey = await journeys.read(desk.db, desk.tenant_id)
                config = mapping.confirmed(
                    config,
                    provider,
                    journey,
                    mapping.suggestions(provider, journey),
                    by=desk.viewer.person_id,
                    now=mapping.epoch(desk.now),
                )
            row.config = mapping.destination_saved(
                config,
                provider,
                destination_id=command.destination_id,
                destination_name=command.destination_name,
                on=command.on,
                test_code=command.test_code or None,
                now=mapping.epoch(desk.now),
                extra=extra,
            )
            await desk.db.flush()
            return await ads_view(desk)

    @router.get(
        "/journey/ads/{provider}/quality",
        response_model=QualityView | None,
        response_model_by_alias=True,
    )
    async def ads_quality(
        provider: str, request: Request, response: Response
    ) -> QualityView | None:
        """How well the platform matches this business's events (Meta's event match
        quality, 0-10), read from the platform each time; null when it has none."""
        adapter = mapping.module(provider)
        read = getattr(adapter, "quality", None)
        async with desk_for(request, response) as desk:
            desk._require_manager()
            row = await desk.db.get(LeadDeskSettings, desk.tenant_id)
            config = dict((row.config if row else None) or {})
            tenant_id = desk.tenant_id
        destination = mapping.read(config, provider).destination_id
        if read is None or not destination:
            return None
        # The platform is asked with no transaction of ours open.
        async with httpx.AsyncClient(timeout=10) as client:
            found = await read(client, config=config, tenant_id=tenant_id, destination=destination)
        if not found:
            return None
        return QualityView(score=found["score"], events=found["events"], keys=found["keys"])

    @router.get(
        "/journey/ads/{provider}/destinations",
        response_model=list[DestinationView],
        response_model_by_alias=True,
    )
    async def destinations(
        provider: str, request: Request, response: Response
    ) -> list[DestinationView]:
        """Where this platform's events can go: Meta's datasets, Google's Ads accounts."""
        async with desk_for(request, response) as desk:
            desk._require_manager()
            adapter = mapping.module(provider)
            row = await desk.db.get(LeadDeskSettings, desk.tenant_id)
            config = dict((row.config if row else None) or {})
            found = await adapter.destinations(desk.db, desk.tenant_id, config)
            return [DestinationView(id=item["id"], name=item["name"]) for item in found]

    @router.put(
        "/journey/ads/{provider}/matches", response_model=AdsView, response_model_by_alias=True
    )
    async def confirm_matches(
        provider: str, command: MatchesCommand, request: Request, response: Response
    ) -> AdsView:
        async with desk_for(request, response, write=True) as desk:
            desk._require_manager()
            journey = await journeys.read(desk.db, desk.tenant_id)
            if journey.version != command.expected_version:
                raise DeskError(409, "The stages changed just now. Check the matches again.")
            row = await lock_settings(desk)
            row.config = mapping.confirmed(
                dict(row.config or {}),
                provider,
                journey,
                command.events,
                by=desk.viewer.person_id,
                now=mapping.epoch(desk.now),
            )
            await desk.db.flush()
            return await ads_view(desk)

    @router.post(
        "/journey/ads/events/{conversion_id}/retry",
        response_model=AdsView,
        response_model_by_alias=True,
    )
    async def retry(conversion_id: UUID, request: Request, response: Response) -> AdsView:
        async with desk_for(request, response, write=True) as desk:
            desk._require_manager()
            if not await engine.retry(desk.db, desk.tenant_id, conversion_id, desk.now):
                raise DeskError(
                    409, "That event can't be sent again: it went already, or is too old."
                )
            await desk.db.flush()
            return await ads_view(desk)

    @router.get("/journey/summary", response_model=SummaryView, response_model_by_alias=True)
    async def summary(request: Request, response: Response) -> SummaryView:
        async with desk_for(request, response) as desk:
            row = await desk.db.get(LeadDeskSettings, desk.tenant_id)
            config: dict[str, Any] = dict((row.config if row else None) or {})
            journey = await journeys.read(desk.db, desk.tenant_id)
            facts = await engine.summary(desk.db, desk.tenant_id, desk.now)
            on = [p for p in mapping.available() if mapping.read(config, p).ready]
            checks = sum(
                1
                for p in on
                for item in mapping.matches(p, journey, mapping.read(config, p))
                if item.state == "new" and item.suggested is not None
            )
            delivered = [at for at in facts["last_delivered_at"].values() if at is not None]
            return SummaryView(
                stages=len(journey.live),
                industry=journey.industry,
                providers_on=on,
                needs_check=checks,
                last_delivered_at=max(delivered, default=None),
            )

    # ----- connecting LinkedIn, TikTok and Microsoft Advertising -------------------------

    def app_url() -> str:
        return str(settings.sales_xray_app_url or "").rstrip("/")

    def install_connect(provider: str, slug: str) -> None:
        adapter = mapping.module(provider)

        @router.get(f"/{slug}/connect", response_model=None, name=f"{slug}_connect")
        async def connect(request: Request, response: Response) -> Response:
            """Start Connect: to the platform's sign-in, back to the callback."""
            cfg = oauth.app(provider)
            async with desk_for(request, response) as desk:
                desk._require_manager()
                if cfg is None:
                    raise DeskError(404, f"{adapter.SPEC.name} isn't set up here yet.")
                state = oauth.make_state(
                    cfg, tenant_id=desk.tenant_id, person_id=desk.viewer.person_id
                )
            url = adapter.consent_url(
                cfg, redirect_uri=f"{app_url()}/v1/lead-desk/{slug}/callback", state=state
            )
            return RedirectResponse(url, status_code=303, headers=PRIVATE)

        @router.get(f"/{slug}/callback", response_model=None, name=f"{slug}_callback")
        async def callback(request: Request, response: Response) -> Response:
            """The platform sends the person back here: keep its tokens, sealed."""

            def done(outcome: str) -> Response:
                url = f"{app_url()}/leads?tab=stages&{slug}={outcome}"
                return RedirectResponse(url, status_code=303, headers=PRIVATE)

            if request.query_params.get("error"):
                return done("cancelled")
            params = request.query_params
            code = params.get("code") or params.get("auth_code") or ""
            state = params.get("state", "")
            cfg = oauth.app(provider)
            if not code or not state or cfg is None:
                return done("failed")
            async with desk_for(request, response) as desk:
                desk._require_manager()
                try:
                    oauth.read_state(
                        cfg, state, tenant_id=desk.tenant_id, person_id=desk.viewer.person_id
                    )
                except oauth.ConnectError:
                    return done("failed")
                tenant_id, person_id = desk.tenant_id, desk.viewer.person_id
            # The platform is asked with no transaction of ours open.
            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    tokens, accounts = await adapter.finish(
                        client,
                        cfg,
                        code=code,
                        redirect_uri=f"{app_url()}/v1/lead-desk/{slug}/callback",
                    )
            except (oauth.ConnectError, httpx.HTTPError, ValueError):
                return done("failed")
            async with desk_for(request, response, write=True, origin=False) as desk:
                if desk.tenant_id != tenant_id:
                    return done("failed")
                row = await lock_settings(desk)
                row.config = oauth.saved(
                    row.config or {},
                    cfg,
                    desk.tenant_id,
                    tokens=tokens,
                    accounts=accounts,
                    by=person_id,
                )
                await desk.db.flush()
            return done("connected")

    for provider, slug in oauth.SLUGS.items():
        install_connect(provider, slug)

    application.include_router(router)
