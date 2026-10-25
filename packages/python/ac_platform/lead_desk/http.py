"""Lead Desk API on the Sales Xray account session (/v1/lead-desk).

Reads and writes use the signed-in person's current organisation workspace.
The website-form capture endpoint is the one exception: it has no session,
and the source's own key is its authority.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Any, Literal
from urllib.parse import parse_qsl
from uuid import UUID

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict
from sqlalchemy import select
from starlette.requests import ClientDisconnect

from ac_platform.conversation_intelligence.sales_xray_tenants import SALES_XRAY_MEMBER_ROLES
from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
)
from ac_platform.http.auth import require_safe_origin
from ac_platform.http.routes import RouteContext
from ac_platform.identity.models import Person
from ac_platform.integrations.ai_writes import IN_APP, AiWrites, AiWritesSettings
from ac_platform.kernel.errors import DomainError
from ac_platform.lead_desk import finder, merging, push, simulation
from ac_platform.lead_desk import tasks as task_book
from ac_platform.lead_desk import team as team_engine
from ac_platform.lead_desk.contracts import (
    ActivityPage,
    AlertText,
    Badge,
    BulkDone,
    BulkLeads,
    CallPrivacy,
    CallRecord,
    CallReport,
    DeleteLead,
    DeleteLeads,
    Desk,
    DeviceCommand,
    DeviceView,
    Disposition,
    DistributeLeads,
    Distribution,
    FollowUp,
    ImportCommand,
    ImportPreview,
    ImportResult,
    LeadDetail,
    LeadDue,
    LeadEdit,
    LeadMade,
    LeadMatch,
    LeadPage,
    LeadsDeleted,
    LeadSince,
    LeadSort,
    Me,
    MergeLeads,
    MergeView,
    MessageSent,
    MovePipeline,
    MyDayView,
    NewLead,
    NewSource,
    NoteCommand,
    NudgesCommand,
    Performance,
    PhoneBook,
    PhoneCall,
    PhoneHealth,
    PhoneLog,
    PhoneLogResult,
    PhoneReport,
    PushConfig,
    Reassign,
    RecordingCommand,
    RepRules,
    SearchResult,
    SeedCommand,
    SellerTargets,
    SettingsCommand,
    SimulationPick,
    Sources,
    SourceView,
    TakingLeads,
    TargetsCommand,
    TaskAction,
    TaskBucket,
    TaskChange,
    TaskCommand,
    TaskList,
    TaskSnooze,
    TaskView,
    Team,
    TeamTargets,
    UndoMerge,
    WorkDay,
    WorkHoursCommand,
)
from ac_platform.lead_desk.intake import MAX_FILE_BYTES, Intake
from ac_platform.lead_desk.store import DeskError, LeadDesk, Viewer, person_name
from ac_platform.lead_desk.vocabulary import STAGES
from ac_platform.tenancy.models import Membership, Organisation

PRIVATE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}
_CAPTURE_MAX = 64 * 1024
_FILE_NAME = re.compile(r"[^\w .()\-]+")


class _Active(BaseModel):
    model_config = ConfigDict(extra="forbid")
    active: bool


def install_lead_desk_http(application: FastAPI, ctx: RouteContext) -> None:
    router = APIRouter(prefix="/v1/lead-desk", tags=["lead-desk"])
    read_actor = getattr(ctx.require_actor, "read_only", ctx.require_actor)
    settings = ctx.settings

    def app_url() -> str:
        return str(settings.sales_xray_app_url or "").rstrip("/")

    def same_host(request: Request) -> None:
        if (
            settings.sales_xray_app_url is None
            or request.url.hostname != settings.sales_xray_app_url.host
        ):
            raise HTTPException(404, "Leads are unavailable here.", headers=PRIVATE)

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
                        session_id=actor.session_id,
                    ),
                    # Sandbox organisations practise with sample recordings. Everyone
                    # else calls from their own phone: the desk opens the dialer and
                    # logs the call. Provider-routed calling (AUT-1004) is separate.
                    call_mode="simulated" if sandbox else "phone",
                    sandbox=sandbox,
                )
        except DeskError as error:
            raise HTTPException(error.status, str(error), headers=PRIVATE) from None
        except DomainError:
            raise HTTPException(401, "Sign in to see your leads.", headers=PRIVATE) from None

    def no_query(request: Request, allowed: frozenset[str] = frozenset()) -> None:
        if any(name not in allowed for name in request.query_params):
            raise HTTPException(422, "Remove the extra address options.", headers=PRIVATE)

    def pipeline_key(pipeline: str | None) -> str | None:
        if pipeline is not None and not 0 < len(pipeline) <= 40:
            raise HTTPException(422, "Choose a pipeline.", headers=PRIVATE)
        return pipeline

    @router.get("", response_model=Desk, response_model_by_alias=True)
    async def desk(request: Request, response: Response, pipeline: str | None = None) -> Desk:
        # ?pipeline=: one pipeline's day, so Start calling works one at a time.
        no_query(request, frozenset({"pipeline"}))
        async with desk_for(request, response) as lead_desk:
            return await lead_desk.desk(pipeline_key(pipeline))

    @router.get("/next", response_model=LeadDetail | None, response_model_by_alias=True)
    async def next_lead(
        request: Request, response: Response, skip: UUID | None = None, pipeline: str | None = None
    ) -> LeadDetail | None:
        no_query(request, frozenset({"skip", "pipeline"}))
        async with desk_for(request, response) as lead_desk:
            return await lead_desk.next_lead(skip, pipeline_key(pipeline))

    @router.get("/leads", response_model=LeadPage, response_model_by_alias=True)
    async def leads(
        request: Request,
        response: Response,
        scope: Literal["mine", "team", "unassigned"] = "mine",
        stage: str | None = None,
        search: str | None = None,
        offset: int = 0,
        test: Literal["only"] | None = None,
        owner: UUID | None = None,
        pipeline: str | None = None,
        sort: LeadSort | None = None,
        order: Literal["asc", "desc"] | None = None,
        source: str | None = Query(default=None, max_length=16),
        due: LeadDue | None = None,
        contact: LeadSince | None = None,
        created: LeadMade | None = None,
    ) -> LeadPage:
        no_query(
            request,
            frozenset(
                {
                    "scope",
                    "stage",
                    "search",
                    "offset",
                    "test",
                    "owner",
                    "pipeline",
                    "sort",
                    "order",
                    "source",
                    "due",
                    "contact",
                    "created",
                }
            ),
        )
        if pipeline is not None and not 0 < len(pipeline) <= 40:
            raise HTTPException(422, "Choose a pipeline.", headers=PRIVATE)
        if stage is not None and stage != "open" and stage not in STAGES:
            raise HTTPException(422, "Choose a lead stage.", headers=PRIVATE)
        if not 0 <= offset <= 100_000 or (search is not None and len(search) > 80):
            raise HTTPException(422, "Search with fewer words.", headers=PRIVATE)
        async with desk_for(request, response) as lead_desk:
            return await lead_desk.leads(
                scope=scope,
                stage=stage,
                search=search,
                offset=offset,
                test_only=test == "only",
                owner=owner,
                pipeline=pipeline,
                sort=sort,
                descending=None if order is None else order == "desc",
                source=source,
                due=due,
                contact=contact,
                created=created,
            )

    @router.get("/activity", response_model=ActivityPage, response_model_by_alias=True)
    async def activity(
        request: Request,
        response: Response,
        day: WorkDay = "today",
        before: AwareDatetime | None = None,
        person: UUID | None = None,
    ) -> ActivityPage:
        """My work: what a seller did, newest first, today, yesterday or this week."""
        no_query(request, frozenset({"day", "before", "person"}))
        async with desk_for(request, response) as lead_desk:
            return await lead_desk.activity(day=day, before=before, person=person)

    @router.get("/notes", response_model=ActivityPage, response_model_by_alias=True)
    async def list_notes(
        request: Request,
        response: Response,
        q: str | None = None,
        before: AwareDatetime | None = None,
    ) -> ActivityPage:
        """Notes: what people wrote on your leads, newest first; with q, what says it."""
        no_query(request, frozenset({"q", "before"}))
        async with desk_for(request, response) as lead_desk:
            return await finder.notes(lead_desk, q=q, before=before)

    @router.get("/search", response_model=SearchResult, response_model_by_alias=True)
    async def search_desk(request: Request, response: Response, q: str = "") -> SearchResult:
        """A few words across leads, notes and open tasks."""
        no_query(request, frozenset({"q"}))
        async with desk_for(request, response) as lead_desk:
            return await finder.search(lead_desk, q)

    @router.get("/leads/match", response_model=LeadMatch, response_model_by_alias=True)
    async def match_lead(request: Request, response: Response, phone: str = "") -> LeadMatch:
        """Is this number already a lead? Add lead asks while a number is typed."""
        no_query(request, frozenset({"phone"}))
        if not 0 < len(phone) <= 40:
            raise HTTPException(422, "Enter a phone number.", headers=PRIVATE)
        async with desk_for(request, response) as lead_desk:
            return await lead_desk.match(phone)

    @router.post("/leads/bulk", response_model=BulkDone, response_model_by_alias=True)
    async def bulk_leads(command: BulkLeads, request: Request, response: Response) -> BulkDone:
        """Owners and admins give, move or re-stage many leads at once."""
        no_query(request)
        async with desk_for(request, response, write=True) as lead_desk:
            return await lead_desk.bulk(command)

    @router.post("/leads/distribute", response_model=Distribution, response_model_by_alias=True)
    async def distribute_leads(
        command: DistributeLeads, request: Request, response: Response
    ) -> Distribution:
        """Owners and managers give chosen or unassigned leads out by a rule; a preview
        changes nothing and names no lead."""
        no_query(request)
        async with desk_for(request, response, write=True) as lead_desk:
            return await team_engine.distribute_leads(lead_desk, command)

    @router.post("/duplicates/merge", response_model=MergeView, response_model_by_alias=True)
    async def merge_leads(command: MergeLeads, request: Request, response: Response) -> MergeView:
        """Owners and managers merge two leads that are one person; undone within 30 days."""
        no_query(request)
        async with desk_for(request, response, write=True) as lead_desk:
            return await merging.merge(lead_desk, command)

    @router.post("/merges/{merge_id}/undo", response_model=MergeView, response_model_by_alias=True)
    async def undo_merge(
        merge_id: UUID, command: UndoMerge, request: Request, response: Response
    ) -> MergeView:
        """Put a merge back: every moved row returns to the lead merged away."""
        no_query(request)
        async with desk_for(request, response, write=True) as lead_desk:
            return await merging.unmerge(lead_desk, merge_id, command)

    @router.post("/leads/delete", response_model=LeadsDeleted, response_model_by_alias=True)
    async def delete_leads(
        command: DeleteLeads, request: Request, response: Response
    ) -> LeadsDeleted:
        """Owners and admins delete chosen leads for good, after a confirm (audited)."""
        no_query(request)
        async with desk_for(request, response, write=True) as lead_desk:
            return await lead_desk.delete_leads(command)

    @router.post("/leads", response_model=LeadDetail, response_model_by_alias=True, status_code=201)
    async def add_lead(command: NewLead, request: Request, response: Response) -> LeadDetail:
        no_query(request)
        async with desk_for(request, response, write=True) as lead_desk:
            return await lead_desk.add(command)

    @router.get("/leads/{lead_id}", response_model=LeadDetail, response_model_by_alias=True)
    async def lead(lead_id: UUID, request: Request, response: Response) -> LeadDetail:
        no_query(request)
        async with desk_for(request, response) as lead_desk:
            return await lead_desk.detail(lead_id)

    @router.post(
        "/leads/{lead_id}/delete", response_model=LeadsDeleted, response_model_by_alias=True
    )
    async def delete_lead(
        lead_id: UUID, command: DeleteLead, request: Request, response: Response
    ) -> LeadsDeleted:
        no_query(request)
        async with desk_for(request, response, write=True) as lead_desk:
            return await lead_desk.delete_leads(
                DeleteLeads(command_id=command.command_id, lead_ids=(lead_id,)), one=True
            )

    @router.post(
        "/leads/{lead_id}/dispose", response_model=LeadDetail, response_model_by_alias=True
    )
    async def dispose(
        lead_id: UUID, command: Disposition, request: Request, response: Response
    ) -> LeadDetail:
        no_query(request)
        async with desk_for(request, response, write=True) as lead_desk:
            return await lead_desk.dispose(lead_id, command)

    @router.patch("/leads/{lead_id}", response_model=LeadDetail, response_model_by_alias=True)
    async def edit_lead(
        lead_id: UUID, command: LeadEdit, request: Request, response: Response
    ) -> LeadDetail:
        no_query(request)
        async with desk_for(request, response, write=True) as lead_desk:
            return await lead_desk.edit(lead_id, command)

    # ----- targets (team engine) ------------------------------------------------------

    @router.get("/targets", response_model=SellerTargets, response_model_by_alias=True)
    async def read_targets(
        request: Request, response: Response, person: UUID | None = None
    ) -> SellerTargets:
        """A seller's targets today and their progress; a manager may read a seller's."""
        no_query(request, frozenset({"person"}))
        async with desk_for(request, response) as lead_desk:
            return await team_engine.seller_targets(lead_desk, person)

    @router.put("/targets", response_model=SellerTargets, response_model_by_alias=True)
    async def write_targets(
        command: TargetsCommand, request: Request, response: Response
    ) -> SellerTargets:
        """An owner or manager sets a seller's daily and weekly targets from a day on."""
        async with desk_for(request, response, write=True) as lead_desk:
            return await team_engine.set_targets(lead_desk, command)

    @router.get("/my-day", response_model=MyDayView, response_model_by_alias=True)
    async def read_my_day(
        request: Request, response: Response, person: UUID | None = None
    ) -> MyDayView:
        """The seller's work, ranked with why, today's numbers and targets, and what to
        show when today is empty; a manager may read a seller's."""
        no_query(request, frozenset({"person"}))
        async with desk_for(request, response) as lead_desk:
            return await team_engine.my_day_for(lead_desk, person)

    @router.get("/targets/team", response_model=TeamTargets, response_model_by_alias=True)
    async def read_team_targets(request: Request, response: Response) -> TeamTargets:
        """Every seller with targets, and how each is doing (owners and managers)."""
        async with desk_for(request, response) as lead_desk:
            return TeamTargets(sellers=await team_engine.team_progress(lead_desk))

    # ----- tasks (work-memory engine) ------------------------------------------------

    @router.post("/leads/{lead_id}/tasks", response_model=TaskView, response_model_by_alias=True)
    async def add_task(
        lead_id: UUID, command: TaskCommand, request: Request, response: Response
    ) -> TaskView:
        """A task on a lead: call back, WhatsApp, email, send a file, a meeting or other."""
        no_query(request)
        async with desk_for(request, response, write=True) as lead_desk:
            return await task_book.TaskBook(lead_desk).create(lead_id, command)

    @router.get("/tasks", response_model=TaskList, response_model_by_alias=True)
    async def list_tasks(
        request: Request,
        response: Response,
        view: TaskBucket = "today",
        person: UUID | None = None,
    ) -> TaskList:
        """A seller's open tasks: overdue, today or upcoming, and how many of each."""
        no_query(request, frozenset({"view", "person"}))
        async with desk_for(request, response) as lead_desk:
            return await task_book.TaskBook(lead_desk).listing(view, person)

    @router.patch("/tasks/{task_id}", response_model=TaskView, response_model_by_alias=True)
    async def change_task(
        task_id: UUID, command: TaskChange, request: Request, response: Response
    ) -> TaskView:
        no_query(request)
        async with desk_for(request, response, write=True) as lead_desk:
            return await task_book.TaskBook(lead_desk).change(task_id, command)

    @router.post("/tasks/{task_id}/snooze", response_model=TaskView, response_model_by_alias=True)
    async def snooze_task(
        task_id: UUID, command: TaskSnooze, request: Request, response: Response
    ) -> TaskView:
        no_query(request)
        async with desk_for(request, response, write=True) as lead_desk:
            return await task_book.TaskBook(lead_desk).snooze(task_id, command)

    @router.post("/tasks/{task_id}/{action}", response_model=TaskView, response_model_by_alias=True)
    async def act_on_task(
        task_id: UUID,
        action: Literal["done", "undo", "cancel"],
        command: TaskAction,
        request: Request,
        response: Response,
    ) -> TaskView:
        """Done in one tap; undo; cancel."""
        no_query(request)
        async with desk_for(request, response, write=True) as lead_desk:
            book = task_book.TaskBook(lead_desk)
            if action == "done":
                return await book.done(task_id, command)
            if action == "undo":
                return await book.undo(task_id, command)
            return await book.cancel(task_id, command)

    # Changes from AI apps and API keys (docs/product/ai-writes.md): the list, undo,
    # and the owner's switch.
    @router.get("/ai-changes")
    async def ai_changes(
        request: Request, response: Response, lead_id: UUID | None = None
    ) -> dict[str, Any]:
        no_query(request, frozenset({"lead_id"}))
        async with desk_for(request, response) as lead_desk:
            return await AiWrites(lead_desk, IN_APP).changes(lead_id=lead_id)

    @router.post("/ai-changes/{change_id}/undo")
    async def undo_ai_change(
        change_id: UUID, request: Request, response: Response
    ) -> dict[str, Any]:
        no_query(request)
        async with desk_for(request, response, write=True) as lead_desk:
            return await AiWrites(lead_desk, IN_APP).undo(change_id)

    @router.get("/ai-writes")
    async def ai_writes(request: Request, response: Response) -> dict[str, Any]:
        no_query(request)
        async with desk_for(request, response) as lead_desk:
            return await AiWrites(lead_desk, IN_APP).describe()

    @router.put("/ai-writes")
    async def save_ai_writes(
        body: AiWritesSettings, request: Request, response: Response
    ) -> dict[str, Any]:
        no_query(request)
        async with desk_for(request, response, write=True) as lead_desk:
            return await AiWrites(lead_desk, IN_APP).save_settings(
                body.expected_revision, body.model_dump(exclude={"expected_revision"})
            )

    @router.post("/leads/{lead_id}/notes", response_model=LeadDetail, response_model_by_alias=True)
    async def add_note(
        lead_id: UUID, command: NoteCommand, request: Request, response: Response
    ) -> LeadDetail:
        no_query(request)
        async with desk_for(request, response, write=True) as lead_desk:
            return await lead_desk.note(lead_id, command)

    @router.post(
        "/leads/{lead_id}/follow-up", response_model=LeadDetail, response_model_by_alias=True
    )
    async def follow_up(
        lead_id: UUID, command: FollowUp, request: Request, response: Response
    ) -> LeadDetail:
        no_query(request)
        async with desk_for(request, response, write=True) as lead_desk:
            return await lead_desk.follow_up(lead_id, command)

    @router.post(
        "/leads/{lead_id}/messages", response_model=LeadDetail, response_model_by_alias=True
    )
    async def message(
        lead_id: UUID, command: MessageSent, request: Request, response: Response
    ) -> LeadDetail:
        no_query(request)
        async with desk_for(request, response, write=True) as lead_desk:
            return await lead_desk.message(lead_id, command)

    @router.get("/badge", response_model=Badge, response_model_by_alias=True)
    async def badge(request: Request, response: Response) -> Badge:
        no_query(request)
        async with desk_for(request, response) as lead_desk:
            return await lead_desk.badge()

    @router.get("/alert", response_model=AlertText, response_model_by_alias=True)
    async def alert_summary(
        request: Request, response: Response, kind: Literal["nudge"] | None = None
    ) -> AlertText:
        """The words on a phone alert for several leads at once; with kind=nudge, on the
        seller's latest nudge (team engine)."""
        no_query(request, frozenset({"kind"}))
        async with desk_for(request, response) as lead_desk:
            if kind == "nudge":
                return await team_engine.nudge_words(lead_desk)
            return await lead_desk.alert_summary()

    @router.get("/leads/{lead_id}/alert", response_model=AlertText, response_model_by_alias=True)
    async def alert_text(lead_id: UUID, request: Request, response: Response) -> AlertText:
        no_query(request)
        async with desk_for(request, response) as lead_desk:
            return await lead_desk.alert_text(lead_id)

    @router.get("/push", response_model=PushConfig, response_model_by_alias=True)
    async def push_config(request: Request, response: Response) -> PushConfig:
        no_query(request)
        async with desk_for(request, response):
            return push.client_config(push.config())

    @router.post("/devices", response_model=DeviceView, response_model_by_alias=True)
    async def register_device(
        command: DeviceCommand, request: Request, response: Response
    ) -> DeviceView:
        no_query(request)
        async with desk_for(request, response, write=True) as lead_desk:
            return DeviceView(registered=await lead_desk.register_device(command))

    @router.post("/devices/forget", response_model=DeviceView, response_model_by_alias=True)
    async def forget_device(
        command: DeviceCommand, request: Request, response: Response
    ) -> DeviceView:
        no_query(request)
        async with desk_for(request, response, write=True) as lead_desk:
            return DeviceView(registered=await lead_desk.forget_device(command))

    @router.post("/leads/{lead_id}/assign", response_model=LeadDetail, response_model_by_alias=True)
    async def assign(
        lead_id: UUID, command: Reassign, request: Request, response: Response
    ) -> LeadDetail:
        no_query(request)
        async with desk_for(request, response, write=True) as lead_desk:
            return await lead_desk.reassign(lead_id, command)

    @router.post(
        "/leads/{lead_id}/pipeline", response_model=LeadDetail, response_model_by_alias=True
    )
    async def move_pipeline(
        lead_id: UUID, command: MovePipeline, request: Request, response: Response
    ) -> LeadDetail:
        no_query(request)
        async with desk_for(request, response, write=True) as lead_desk:
            return await lead_desk.move_pipeline(
                lead_id,
                pipeline=command.pipeline,
                expected_revision=command.expected_revision,
                command_id=command.command_id,
            )

    @router.post("/leads/{lead_id}/simulation", response_model=SimulationPick)
    async def simulation_pick(
        lead_id: UUID, request: Request, response: Response
    ) -> SimulationPick:
        no_query(request)
        samples = simulation.catalogue(settings.lead_desk_simulation_root)
        if not samples:
            raise HTTPException(503, "Simulated calls aren't set up here yet.", headers=PRIVATE)
        async with desk_for(request, response, write=True) as lead_desk:
            lead, business, owner_name = await lead_desk.simulation_target(lead_id)
            sample = simulation.pick(
                samples,
                language=lead.language,
                business=business,
                seed=f"{lead.id}:{lead.calls}",
            )
            if sample is None or lead.owner_person_id is None:
                raise HTTPException(503, "No test recording fits this lead.", headers=PRIVATE)
            return SimulationPick(
                sample_id=sample.sample_id,
                duration_seconds=round(sample.duration_ms / 1000),
                language_mix=sample.language_mix,
                business_name=sample.business_name,
                owner_person_id=lead.owner_person_id,
                owner_name=owner_name,
            )

    @router.get("/simulation/{sample_id}/audio")
    async def simulation_audio(sample_id: str, request: Request, response: Response) -> Any:
        no_query(request)
        path = simulation.audio_path(settings.lead_desk_simulation_root, sample_id)
        if path is None:
            raise HTTPException(404, "That test recording isn't here.", headers=PRIVATE)
        async with desk_for(request, response):
            pass  # Any signed-in desk may fetch the fictional recordings.
        return FileResponse(
            path,
            media_type="audio/mpeg",
            filename=f"{sample_id}.mp3",
            headers=PRIVATE,
        )

    @router.post("/leads/{lead_id}/calls", response_model=LeadDetail, response_model_by_alias=True)
    async def record_call(
        lead_id: UUID, command: CallRecord, request: Request, response: Response
    ) -> LeadDetail:
        no_query(request)
        async with desk_for(request, response, write=True) as lead_desk:
            return await lead_desk.record_call(
                lead_id,
                command_id=command.command_id,
                submission_id=command.submission_id,
                simulated=command.simulated,
                duration_seconds=command.duration_seconds,
                sample=command.sample,
            )

    @router.post(
        "/leads/{lead_id}/calls/phone", response_model=LeadDetail, response_model_by_alias=True
    )
    async def record_phone_call(
        lead_id: UUID, command: PhoneCall, request: Request, response: Response
    ) -> LeadDetail:
        no_query(request)
        async with desk_for(request, response, write=True) as lead_desk:
            return await lead_desk.record_call(
                lead_id,
                command_id=command.command_id,
                submission_id=None,
                simulated=False,
                duration_seconds=command.duration_seconds,
            )

    @router.get("/phone-book", response_model=PhoneBook, response_model_by_alias=True)
    async def phone_book(request: Request, response: Response) -> PhoneBook:
        no_query(request)
        async with desk_for(request, response) as lead_desk:
            return await lead_desk.phone_book()

    @router.post("/phone-log", response_model=PhoneLogResult, response_model_by_alias=True)
    async def phone_log(command: PhoneLog, request: Request, response: Response) -> PhoneLogResult:
        """Work calls the phone app found in the phone's call history (UX study item 5)."""
        no_query(request)
        async with desk_for(request, response, write=True) as lead_desk:
            return await lead_desk.log_phone_calls(command)

    @router.post(
        "/calls/{event_id}/private", response_model=LeadDetail, response_model_by_alias=True
    )
    async def call_privacy(
        event_id: UUID, command: CallPrivacy, request: Request, response: Response
    ) -> LeadDetail:
        """Mark private (Salestrail's untracked call): the seller's own phone-logged call only."""
        no_query(request)
        async with desk_for(request, response, write=True) as lead_desk:
            return await lead_desk.set_call_privacy(event_id, command)

    @router.post(
        "/leads/{lead_id}/recordings", response_model=LeadDetail, response_model_by_alias=True
    )
    async def attach_recording(
        lead_id: UUID, command: RecordingCommand, request: Request, response: Response
    ) -> LeadDetail:
        no_query(request)
        async with desk_for(request, response, write=True) as lead_desk:
            return await lead_desk.attach_recording(
                lead_id,
                command_id=command.command_id,
                submission_id=command.submission_id,
                call_event_id=command.call_event_id,
            )

    @router.get("/team", response_model=Team, response_model_by_alias=True)
    async def team(request: Request, response: Response) -> Team:
        no_query(request)
        async with desk_for(request, response) as lead_desk:
            return await lead_desk.team()

    @router.put("/team/{person_id}", response_model=Team, response_model_by_alias=True)
    async def save_rep(
        person_id: UUID, command: RepRules, request: Request, response: Response
    ) -> Team:
        no_query(request)
        async with desk_for(request, response, write=True) as lead_desk:
            return await lead_desk.save_rep(person_id, command)

    @router.get("/reports/calls", response_model=CallReport, response_model_by_alias=True)
    async def call_report(request: Request, response: Response) -> CallReport:
        """Calls by seller by day for a date range (managers; the page makes the CSV)."""
        no_query(request, frozenset({"start", "end"}))
        try:
            start = date.fromisoformat(request.query_params.get("start", ""))
            end = date.fromisoformat(request.query_params.get("end", ""))
        except ValueError:
            raise HTTPException(422, "Pick a start and an end date.", headers=PRIVATE) from None
        async with desk_for(request, response) as lead_desk:
            return await lead_desk.call_report(start, end)

    @router.get("/reports/performance", response_model=Performance, response_model_by_alias=True)
    async def performance(request: Request, response: Response, days: int = 7) -> Performance:
        """How sales went over today, 7 or 30 days (owners and admins; Home)."""
        no_query(request, frozenset({"days"}))
        async with desk_for(request, response) as lead_desk:
            return await lead_desk.performance(days)

    @router.get("/me", response_model=Me, response_model_by_alias=True)
    async def me(request: Request, response: Response) -> Me:
        """Whether new leads come to me: the account sheet's switch (UX study item 8)."""
        no_query(request)
        async with desk_for(request, response) as lead_desk:
            return await lead_desk.me()

    @router.put("/me/taking", response_model=Me, response_model_by_alias=True)
    async def set_taking(command: TakingLeads, request: Request, response: Response) -> Me:
        no_query(request)
        async with desk_for(request, response, write=True) as lead_desk:
            return await lead_desk.set_taking(command)

    @router.post("/me/phone", response_model=PhoneHealth, response_model_by_alias=True)
    async def report_phone(
        command: PhoneReport, request: Request, response: Response
    ) -> PhoneHealth:
        """The seller's phone setup checklist, from the page inside the phone app (item 7)."""
        no_query(request)
        async with desk_for(request, response, write=True) as lead_desk:
            return await lead_desk.report_phone(command)

    @router.put("/settings", response_model=Team, response_model_by_alias=True)
    async def save_settings(command: SettingsCommand, request: Request, response: Response) -> Team:
        no_query(request)
        async with desk_for(request, response, write=True) as lead_desk:
            return await lead_desk.save_settings(command)

    @router.put("/nudges", response_model=Team, response_model_by_alias=True)
    async def save_nudges(command: NudgesCommand, request: Request, response: Response) -> Team:
        """Nudges on for the workspace (off by default), and off for chosen sellers."""
        no_query(request)
        async with desk_for(request, response, write=True) as lead_desk:
            return await team_engine.save_nudges(lead_desk, command)

    @router.put("/work-hours", response_model=Team, response_model_by_alias=True)
    async def save_work_hours(
        command: WorkHoursCommand, request: Request, response: Response
    ) -> Team:
        """The team's work days and hours; outside them calls stay on phones and leads wait."""
        no_query(request)
        async with desk_for(request, response, write=True) as lead_desk:
            return await lead_desk.save_work_hours(command)

    @router.post("/sweep")
    async def sweep(request: Request, response: Response) -> dict[str, int]:
        no_query(request)
        async with desk_for(request, response, write=True) as lead_desk:
            lead_desk._require_manager()
            return {"moved": await lead_desk.sweep()}

    @router.post("/imports/preview", response_model=ImportPreview)
    async def preview(request: Request, response: Response) -> ImportPreview:
        no_query(request)
        name = _FILE_NAME.sub("", request.headers.get("x-file-name", "leads.csv"))[:200] or "leads"
        data = await _body(request, MAX_FILE_BYTES)
        async with desk_for(request, response, write=True) as lead_desk:
            return await Intake(lead_desk, app_url=app_url()).preview(name, data)

    @router.post("/imports", response_model=ImportResult)
    async def commit_import(
        command: ImportCommand, request: Request, response: Response
    ) -> ImportResult:
        no_query(request)
        async with desk_for(request, response, write=True) as lead_desk:
            return await Intake(lead_desk, app_url=app_url()).commit(command)

    @router.get("/sources", response_model=Sources, response_model_by_alias=True)
    async def sources(request: Request, response: Response) -> Sources:
        no_query(request)
        async with desk_for(request, response) as lead_desk:
            return await Intake(lead_desk, app_url=app_url()).sources(meta_ready=False)

    @router.post("/sources", response_model=SourceView, status_code=201)
    async def add_source(command: NewSource, request: Request, response: Response) -> SourceView:
        no_query(request)
        async with desk_for(request, response, write=True) as lead_desk:
            return await Intake(lead_desk, app_url=app_url()).add_source(command)

    @router.post("/sources/{source_id}/rotate", response_model=SourceView)
    async def rotate(source_id: UUID, request: Request, response: Response) -> SourceView:
        no_query(request)
        async with desk_for(request, response, write=True) as lead_desk:
            return await Intake(lead_desk, app_url=app_url()).rotate(source_id)

    @router.post("/sources/{source_id}/active", response_model=SourceView)
    async def set_active(
        source_id: UUID, command: _Active, request: Request, response: Response
    ) -> SourceView:
        no_query(request)
        async with desk_for(request, response, write=True) as lead_desk:
            return await Intake(lead_desk, app_url=app_url()).set_active(source_id, command.active)

    @router.post("/sources/{source_id}/sync", response_model=ImportResult)
    async def sync(source_id: UUID, request: Request, response: Response) -> ImportResult:
        no_query(request)
        async with desk_for(request, response, write=True) as lead_desk:
            return await Intake(lead_desk, app_url=app_url()).sync_sheet(source_id)

    @router.post("/sandbox/seed", response_model=ImportResult)
    async def seed(command: SeedCommand, request: Request, response: Response) -> ImportResult:
        no_query(request)
        async with desk_for(request, response, write=True) as lead_desk:
            return await Intake(lead_desk, app_url=app_url()).seed_sandbox(command)

    @router.post("/capture/{source_id}", status_code=202)
    async def capture(source_id: UUID, request: Request, response: Response) -> dict[str, Any]:
        """A website form or another system sends one lead. No cookie, no session."""
        response.headers.update({"Cache-Control": "no-store"})
        same_host(request)
        token = (
            request.headers.get("x-lead-desk-key")
            or request.headers.get("authorization", "").removeprefix("Bearer ").strip()
            or request.query_params.get("key", "")
        )
        if not token or len(token) > 128:
            raise HTTPException(401, "Send the source key.", headers={"Cache-Control": "no-store"})
        record = _record(await _body(request, _CAPTURE_MAX), request.headers.get("content-type"))
        record.pop("key", None)
        try:
            async with ctx.sessions() as database, database.begin():
                lead_id, outcome = await Intake.capture(
                    database, source_id, token, record, app_url=app_url()
                )
        except DeskError as error:
            raise HTTPException(
                error.status, str(error), headers={"Cache-Control": "no-store"}
            ) from None
        return {"received": outcome != "skipped", "outcome": outcome, "lead_id": lead_id}

    application.include_router(router)
    push.attach(application, ctx.sessions, settings.environment)


async def _body(request: Request, limit: int) -> bytes:
    raw = bytearray()
    try:
        async with asyncio.timeout(15):
            async for chunk in request.stream():
                if len(raw) + len(chunk) > limit:
                    raise HTTPException(413, "That's too large to send.", headers=PRIVATE)
                raw.extend(chunk)
    except (TimeoutError, ClientDisconnect):
        raise HTTPException(408, "The upload stopped. Try again.", headers=PRIVATE) from None
    return bytes(raw)


def _record(raw: bytes, content_type: str | None) -> dict[str, Any]:
    kind = (content_type or "").split(";", 1)[0].strip().lower()
    try:
        if kind == "application/x-www-form-urlencoded":
            pairs = parse_qsl(raw.decode(), keep_blank_values=False, max_num_fields=200)
            return {name[:120]: value[:2000] for name, value in pairs}
        value = json.loads(raw)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise HTTPException(
            422, "Send the lead as JSON or as a form.", headers={"Cache-Control": "no-store"}
        ) from None
    if not isinstance(value, dict):
        raise HTTPException(
            422, "Send one lead as a JSON object.", headers={"Cache-Control": "no-store"}
        )
    return value
