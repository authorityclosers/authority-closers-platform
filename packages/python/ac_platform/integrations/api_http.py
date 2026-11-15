"""The Sales X-Ray API for other apps: ``Authorization: Bearer sxk_...`` or ``sxa_...``.

Base address: ``https://<sales x-ray host>/v1/api``.

- GET  /me                  who is calling: organisation or workspace, scopes (any scope)
- GET  /calls               calls, newest first (calls:read)
- GET  /calls/{id}          one call, with its facts when reports:read is held (calls:read)
- GET  /calls/{id}/facts    the facts found in one call (reports:read)
- GET  /leads               leads, newest change first, with the organisation's own
                            stages; ``stage`` is one of their keys, or open (leads:read)
- GET  /leads/{id}          one lead (leads:read)
- GET  /duplicates          leads that may be one person, the likeliest first, with counts
                            (leads:read; an organisation's owners and admins)
- GET  /duplicates/{id}     one pair side by side: why, the lead a merge would keep and who
                            would have it (leads:read; owners and admins). Merging stays in
                            Sales X-Ray, with a person.
- POST /leads               add a lead; the same ``external_id`` again changes nothing
                            (leads:write). An app's lead shows the app's name as its source.
- POST /leads/imports       up to 10,000 leads at once, filed in the background through the
                            app's own file import; ``Idempotency-Key`` (leads:write;
                            integrations/lead_imports.py)
- POST /leads/imports/uploads  a one-time address (15 minutes) to PUT a CSV of up to 10,000
                            leads to, without the key: it queues as one import, the same file
                            twice once (leads:write; integrations/import_uploads.py)
- PUT  /leads/imports/upload/{token}  the CSV itself
- GET  /leads/imports       recent imports; /leads/imports/{id} where one stands;
                            /leads/imports/{id}/rows each row's outcome (leads:write)
- PATCH /leads/{id}         change a lead's name, company, city, interest or language, as
                            an AI write with Undo (leads:update; the owner's switch decides)
- POST /leads/{id}/stage    move a lead to another stage with the reason, as an AI write
                            with Undo; Won, Lost and Junk wait for a person (leads:stage;
                            the owner's switch decides), except from an owner's or admin's
                            organisation key, which closes with the reason (and Won's amount)
- POST /leads/{id}/assign   give a lead to a teammate, or to whom the lead rules pick, with
                            Undo (leads:assign; an owner's or admin's organisation key only)
- POST /leads/bulk          one stage move or assign for up to 1,000 leads (ids, or a stage
                            filter), each lead its own change with Undo; above 5 leads,
                            preview first and send its preview_sha (an owner's or admin's
                            organisation key only; ai-writes.md, "Amended 15 Nov")
- POST /changes/undo-request  undo every change one bulk request made
- POST /calls               a recording for the connected person to add to their calls;
                            it waits for them, nothing is analysed (calls:write; see
                            integrations/app_uploads.py)
- GET  /calls/uploads/{id}  what became of one (calls:write)
- GET  /tasks               open tasks, as the app's Tasks list shows them: overdue, today
                            or upcoming, and how many of each; ``person`` for an owner or
                            admin (leads:read)
- POST /tasks/{id}/done     mark a task on a lead done, as an AI write with Undo (reopens it)
- POST /tasks/{id}/snooze   snooze a task on a lead (15m, 1h, evening, tomorrow, week), as
                            an AI write with Undo (puts its due back) (leads:tasks; the
                            owner's switch for tasks decides both)
- GET  /team                the team as the app shows it: names and roles (never emails),
                            who takes new leads, lead limits and today's work, and the
                            unassigned leads (team:read; an organisation's key, or a
                            person whose role sees the team)
- GET  /analysis-time       the workspace's analysis time: given, used and left, and the
                            longest call (calls:read; time only, never a price;
                            integrations/analysis_time.py)
- GET  /analysis-time/team  the same, and what each member used of it (calls:read; an
                            organisation's key, or its owners and admins)

Who sees what:
- An API key, or a token from an app an organisation connected, sees what an
  organisation owner sees: every call the library shows (retention, deletion and test
  calls apply), every lead.
- A token from a platform app a person connected for themself (for example Pulse)
  acts as that person and sees what they see in Sales X-Ray: their own calls and
  leads, or their team's when they are an owner or admin. The membership is checked
  on every request, so a person who leaves an organisation stops seeing it at once.
  A Personal workspace has calls but no leads.

Sensitive (withheld) segments are never quoted. Errors are JSON
``{"error": {"code", "message"}}``; 120 requests a minute per key or connection, then
429 with ``Retry-After``. The MCP server (``/v1/mcp``) reads through the same class.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.call_data import facts as call_facts
from ac_platform.call_data.models import CallObject
from ac_platform.http.rate_limits import InMemoryTokenBucketLimiter, RateLimitRule
from ac_platform.http.routes import RouteContext
from ac_platform.integrations import (
    analysis_time,
    app_uploads,
    import_uploads,
    keys,
    lead_imports,
    oauth,
    sealed,
    tiers,
)
from ac_platform.integrations.ai_writes import AiWriteError, AiWrites, Door
from ac_platform.integrations.models import IntegrationOAuthClient
from ac_platform.kernel.authz import ActorContext
from ac_platform.lead_desk import duplicate_queue
from ac_platform.lead_desk.contracts import (
    LeadPage,
    LeadRow,
    TaskBucket,
    TaskKind,
    TaskSnoozeChoice,
)
from ac_platform.lead_desk.journey import model as journeys
from ac_platform.lead_desk.journey import pipelines
from ac_platform.lead_desk.store import DeskError, LeadDesk, Viewer
from ac_platform.lead_desk.tasks import TaskBook
from ac_platform.tenancy.models import Membership, Organisation, Tenant
from ac_platform.tenancy.roles import ORG_ROLES, READ_ONLY_ROLES, can

PRIVATE = {"Cache-Control": "no-store"}
PAGE = 50
RULE = RateLimitRule(
    name="integrations-api-key",
    method="GET",
    path=re.compile(r"^/v1/api/"),
    capacity=120,
    refill_seconds=60.0,
)
_NIL = UUID(int=0)
# The desk's own kinds of stage, which callers from before the organisations' own stages
# still filter by; a stage key of the organisation's comes first.
KINDS = ("new", "not_connected", "follow_up", "interested", "won", "lost")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, retry_after: int | None = None):
        super().__init__(code)
        self.status, self.code, self.message, self.retry_after = status, code, message, retry_after


class NoteBody(BaseModel):
    """A note an app adds to a lead (docs/product/ai-writes.md). Only these fields."""

    model_config = ConfigDict(extra="forbid")
    note: str = Field(min_length=1, max_length=1000)
    request_id: str = Field(min_length=8, max_length=80)
    preview: bool = False


class TaskBody(BaseModel):
    """A task or reminder an app adds to a lead. Only these fields; its owner is the lead's."""

    model_config = ConfigDict(extra="forbid")
    kind: TaskKind
    due: AwareDatetime
    title: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=1000)
    ends_at: AwareDatetime | None = None
    remind_before_minutes: int | None = Field(default=None, ge=0, le=1440)
    request_id: str = Field(min_length=8, max_length=80)
    preview: bool = False


class LeadUpdateBody(BaseModel):
    """An app's change to a lead's details (docs/product/ai-writes.md, "update")."""

    model_config = ConfigDict(extra="forbid")
    fields: dict[str, str | None] = Field(min_length=1, max_length=8)
    expected_revision: int | None = Field(default=None, ge=1)
    request_id: str = Field(min_length=8, max_length=80)
    preview: bool = False


class StageBody(BaseModel):
    """An app moves a lead to another stage, with the reason (ai-writes.md, "stage")."""

    model_config = ConfigDict(extra="forbid")
    step: str = Field(min_length=1, max_length=40)
    reason: str = Field(min_length=1, max_length=500)
    # What the stage list asks for on some stages (for example why a talk is incomplete).
    reason_code: str | None = Field(default=None, min_length=1, max_length=40)
    next_action_at: AwareDatetime | None = None
    expected_revision: int | None = Field(default=None, ge=1)
    request_id: str = Field(min_length=8, max_length=80)
    preview: bool = False
    # Whole rupees, for a move to Won (an owner's or admin's organisation key).
    amount: int | None = Field(default=None, ge=1)


class AssignBody(BaseModel):
    """An owner's or admin's organisation key gives a lead to a teammate (person_id from
    GET /team), or, with none, to whom the lead rules pick."""

    model_config = ConfigDict(extra="forbid")
    person_id: UUID | None = None
    expected_revision: int | None = Field(default=None, ge=1)
    request_id: str = Field(min_length=8, max_length=80)
    preview: bool = False


class BulkStage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step: str = Field(min_length=1, max_length=40)
    reason: str = Field(min_length=1, max_length=500)
    reason_code: str | None = Field(default=None, min_length=1, max_length=40)
    next_action_at: AwareDatetime | None = None
    amount: int | None = Field(default=None, ge=1)


class BulkAssign(BaseModel):
    model_config = ConfigDict(extra="forbid")
    person_id: UUID | None = None


class BulkChange(BaseModel):
    """Exactly one: a stage move or an assign."""

    model_config = ConfigDict(extra="forbid")
    stage: BulkStage | None = None
    assign: BulkAssign | None = None


class BulkFilter(BaseModel):
    """The leads a bulk change takes, by stage (a key from GET /leads's stages, or open)."""

    model_config = ConfigDict(extra="forbid")
    stage: str = Field(min_length=1, max_length=40)
    search: str | None = Field(default=None, max_length=120)


class BulkBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lead_ids: list[UUID] | None = Field(default=None, min_length=1, max_length=1000)
    filter: BulkFilter | None = None
    change: BulkChange
    request_id: str = Field(min_length=8, max_length=80)
    preview: bool = False
    preview_sha: str | None = Field(default=None, min_length=64, max_length=64)


class UploadBody(BaseModel):
    """The choices for an import whose rows come as a CSV to a one-time address."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="CSV upload", min_length=1, max_length=200)
    side: Literal["inbound", "cold"] = "inbound"
    assign: Literal["rules", "none"] = "rules"
    duplicates: Literal["skip", "fill", "replace"] = "skip"
    pipeline: str | None = Field(default=None, max_length=40)
    stage: str | None = Field(default=None, max_length=40)


class UndoRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=8, max_length=80)


class TaskDoneBody(BaseModel):
    """An app marks a task on a lead done (ai-writes.md: leads:tasks)."""

    model_config = ConfigDict(extra="forbid")
    expected_revision: int | None = Field(default=None, ge=1)
    request_id: str = Field(min_length=8, max_length=80)
    preview: bool = False


class TaskSnoozeBody(TaskDoneBody):
    """An app snoozes a task on a lead, by one of the app's own choices."""

    choice: TaskSnoozeChoice


class UndoBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str | None = Field(default=None, min_length=8, max_length=80)


class NewLeadBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=320)
    company: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=120)
    interest: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=2000)
    external_id: str | None = Field(default=None, min_length=1, max_length=120)


@dataclass(frozen=True, slots=True)
class Caller:
    """A checked key or token, with how far it reaches."""

    key: keys.KeyContext
    reach: Literal["organisation", "person"]
    role: str | None  # the person's live role (person reach); None in a Personal workspace
    personal_workspace: bool = False

    @property
    def sees_team(self) -> bool:
        return self.reach == "organisation" or can(self.role, "team.view")


def _authenticate(
    connection: Any, presented: str, environment: str, now: datetime
) -> tuple[keys.KeyContext, bool] | None:
    """An API key (``sxk_``) or a Connect access token (``sxa_``), and whether it acts as
    one person (a platform app's connection)."""
    if presented.startswith("sxa_"):
        token = oauth.authenticate(connection, presented, now=now)
        if token is None or token.person_id is None:
            return None
        context = keys.KeyContext(
            key_id=token.grant_id,
            tenant_id=token.tenant_id,
            scopes=token.scopes,
            prefix=f"app {token.client_id}",
            acting_person_id=token.person_id,
        )
        return context, token.personal
    found = keys.authenticate(connection, presented, environment=environment, now=now)
    return None if found is None else (found, False)


def _error(error: ApiError) -> JSONResponse:
    headers = dict(PRIVATE)
    if error.status == 401:
        headers["WWW-Authenticate"] = 'Bearer realm="sales-xray"'
    if error.retry_after is not None:
        headers["Retry-After"] = str(error.retry_after)
    return JSONResponse(
        {"error": {"code": error.code, "message": error.message}},
        status_code=error.status,
        headers=headers,
    )


def _label() -> Any:
    from ac_platform.conversation_intelligence.acquisition_models import (
        ConversationAcquisitionUsage as Usage,
    )
    from ac_platform.conversation_intelligence.submission_label_models import (
        ConversationSubmissionLabelRevision as Label,
    )

    return (
        select(Label.display_name)
        .where(Label.tenant_id == Usage.tenant_id, Label.submission_id == Usage.submission_id)
        .order_by(Label.revision.desc())
        .limit(1)
        .scalar_subquery()
    )


class Reader:
    """Everything the API and the MCP server read or write, for one checked caller."""

    def __init__(
        self,
        session: AsyncSession,
        caller: Caller,
        base: str | None,
        environment: str,
        tier: tiers.Tier | None = None,
        platform: tiers.Platform | None = None,
        resource: str | None = None,
        settings: Any = None,
    ) -> None:
        self.session, self.caller, self.base = session, caller, base
        # The server's settings, for reads composed as the app composes them.
        self.settings = settings
        # The origin the caller reached (app, API or MCP host): its own resource metadata.
        self.resource = resource or base
        self.environment = environment
        # What the workspace's plan lets apps do (integrations/tiers.py).
        self.platform = platform or tiers.DEFAULT_PLATFORM
        self.tier = tier or self.platform.tier("unbilled")

    @property
    def key(self) -> keys.KeyContext:
        return self.caller.key

    def require(self, scope: str) -> None:
        if scope not in self.key.scopes:
            raise ApiError(403, "scope_missing", f"This key does not have {scope}.")
        # A plan that no longer includes it (a downgrade) stops it; the key is kept.
        if self.tier.enforce_existing and not self.tier.allows(scope):
            raise ApiError(403, "plan_scope", tiers.not_included(self.platform, scope))
        if not scope.endswith(":read"):
            self._refuse_read_only()

    def _refuse_read_only(self) -> None:
        # Roles B (25 Oct 2026): what a person's role cannot change, their keys and
        # connections cannot either, whatever scopes they were given.
        if self.caller.reach == "person" and self.caller.role in READ_ONLY_ROLES:
            raise ApiError(403, "role_read_only", "Your role can view only. Ask an owner or admin.")

    def _desk(self) -> LeadDesk:
        if self.caller.personal_workspace:
            raise ApiError(
                403, "organisation_only", "Leads are kept in organisations, not Personal."
            )
        role = "owner" if self.caller.reach == "organisation" else (self.caller.role or "member")
        viewer = Viewer(
            person_id=self.key.acting_person_id,
            tenant_id=self.key.tenant_id,
            role=role,
            name=self.key.prefix,
        )
        return LeadDesk(self.session, viewer)

    def _library(self, now: datetime) -> Any:
        from ac_platform.conversation_intelligence.acquisition_library import (
            _account_library_query,
            _report_columns,
        )

        # The organisation's calls for an owner's view (the actor ids are not used), or
        # this person's own calls.
        person = _NIL if self.caller.reach == "organisation" else self.key.acting_person_id
        reader = ActorContext(person_id=person, session_id=_NIL, tenant_id=self.key.tenant_id)
        has_report, _ = _report_columns()
        return _account_library_query(reader, now, every_owner=self.caller.sees_team), has_report

    def _item(self, usage: Any, reported: Any, title: str | None) -> dict[str, Any]:
        call_id = str(usage.submission_id)
        return {
            "id": call_id,
            "title": title,
            "created_at": usage.created_at.isoformat(),
            "duration_seconds": usage.reserved_seconds,
            "has_report": bool(reported),
            "open_url": f"{self.base}/analysis/calls/{call_id}" if self.base else None,
        }

    async def me(self) -> dict[str, Any]:
        name = await self.session.scalar(select(Tenant.name).where(Tenant.id == self.key.tenant_id))
        answer: dict[str, Any] = {
            "organisation": {"id": str(self.key.tenant_id), "name": name},
            "key": {"prefix": self.key.prefix, "scopes": sorted(self.key.scopes)},
            "environment": self.environment,
            "reach": self.caller.reach,
        }
        if self.caller.reach == "person":
            from ac_platform.identity.models import Person

            person = await self.session.scalar(
                select(Person.display_name).where(Person.id == self.key.acting_person_id)
            )
            answer["person"] = {"id": str(self.key.acting_person_id), "name": person}
            answer["workspace"] = {
                "id": str(self.key.tenant_id),
                "kind": "personal" if self.caller.personal_workspace else "organisation",
                "name": "Personal" if self.caller.personal_workspace else name,
                "role": self.caller.role,
            }
            if self.caller.personal_workspace:
                answer["organisation"] = None
        return answer

    async def calls(self, before: UUID | None = None) -> dict[str, Any]:
        from ac_platform.conversation_intelligence.acquisition_models import (
            ConversationAcquisitionUsage as Usage,
        )

        self.require("calls:read")
        now = datetime.now(UTC)
        library, has_report = self._library(now)
        query = library.add_columns(has_report, _label())
        if before is not None:
            cursor = (
                await self.session.execute(library.where(Usage.submission_id == before))
            ).scalar()
            if cursor is None:
                raise ApiError(404, "cursor_missing", "That call is not in this list.")
            query = query.where(
                tuple_(Usage.created_at, Usage.submission_id)
                < (cursor.created_at, cursor.submission_id)
            )
        rows = (
            await self.session.execute(
                query.order_by(Usage.created_at.desc(), Usage.submission_id.desc()).limit(PAGE + 1)
            )
        ).all()
        items = [self._item(usage, reported, title) for usage, reported, title in rows[:PAGE]]
        return {"calls": items, "next_before": items[-1]["id"] if len(rows) > PAGE else None}

    async def _visible(self, call_id: UUID) -> tuple[Any, Any, str | None]:
        from ac_platform.conversation_intelligence.acquisition_models import (
            ConversationAcquisitionUsage as Usage,
        )

        library, has_report = self._library(datetime.now(UTC))
        row = (
            await self.session.execute(
                library.add_columns(has_report, _label()).where(Usage.submission_id == call_id)
            )
        ).first()
        if row is None:
            raise ApiError(404, "call_missing", "That call is not here, or not yours to read.")
        return row[0], row[1], row[2]

    async def _facts(self, call_id: UUID) -> dict[str, Any]:
        where = (CallObject.tenant_id == self.key.tenant_id) & (CallObject.submission_id == call_id)
        result: dict[str, Any] = await self.session.run_sync(
            lambda sync: call_facts.prospect_facts(
                sync.connection(), where, {"kind": "call", "id": str(call_id)}
            )
        )
        return result

    async def call(self, call_id: UUID) -> dict[str, Any]:
        self.require("calls:read")
        usage, reported, title = await self._visible(call_id)
        answer = self._item(usage, reported, title)
        answer["facts"] = (
            (await self._facts(call_id))["facts"] if "reports:read" in self.key.scopes else None
        )
        return answer

    async def facts(self, call_id: UUID) -> dict[str, Any]:
        self.require("reports:read")
        if self.caller.reach == "person":
            await self._visible(call_id)
        return await self._facts(call_id)

    async def duplicates(self) -> dict[str, Any]:
        """Leads that may be one person (docs/product/lead-desk/duplicates.md, D4b): read
        only, for an organisation's owners and admins."""
        self.require("leads:read")
        try:
            queue = await duplicate_queue.queue(self._desk())
        except DeskError as error:
            raise ApiError(error.status, "lead_desk", str(error)) from None
        result: dict[str, Any] = queue.model_dump(mode="json", by_alias=True)
        return result

    async def duplicate(self, pair_id: UUID) -> dict[str, Any]:
        self.require("leads:read")
        try:
            pair = await duplicate_queue.compare(self._desk(), pair_id)
        except DeskError as error:
            raise ApiError(error.status, "lead_desk", str(error)) from None
        result: dict[str, Any] = pair.model_dump(mode="json", by_alias=True)
        return result

    async def leads(
        self,
        stage: str | None = None,
        offset: int = 0,
        limit: int = 50,
        search: str | None = None,
    ) -> dict[str, Any]:
        """A page of leads, with the organisation's own stages (key and label) that
        ``stage`` filters by: one of their keys, or ``open`` for every open lead (the sales
        team's eight stages, orchestrator, 26 Oct 2026)."""
        self.require("leads:read")
        desk = self._desk()
        stages = await self.stages()
        keys = [item["key"] for item in stages]
        offset, limit = max(0, offset), max(1, min(50, limit))
        try:
            if stage is not None and stage in keys:
                page = await self._stage_page(desk, stage, offset, limit, search)
            elif stage is None or stage == "open" or stage in KINDS:
                page = await desk.leads(
                    scope="team" if self.caller.sees_team else "mine",
                    stage=stage,
                    search=search,
                    offset=offset,
                    limit=limit,
                )
            else:
                raise ApiError(422, "stage_unknown", f"stage is one of open, {', '.join(keys)}.")
        except DeskError as error:
            raise ApiError(error.status, "lead_desk", str(error)) from None
        result: dict[str, Any] = page.model_dump(mode="json", by_alias=True)
        result["stages"] = stages
        return result

    async def stages(self) -> list[dict[str, str]]:
        """The organisation's own stages, each pipeline's in its board's order, each key
        once (the first pipeline's label)."""
        found: dict[str, dict[str, str]] = {}
        for pipeline in await pipelines.listed(self.session, self.key.tenant_id):
            journey = await journeys.read(self.session, self.key.tenant_id, pipeline.key)
            for stage in journey.board():
                found.setdefault(stage.key, {"key": stage.key, "label": stage.label})
        return list(found.values())

    async def _stage_page(
        self, desk: LeadDesk, step: str, offset: int, limit: int, search: str | None
    ) -> LeadPage:
        """One of the organisation's own stages: its column on each pipeline's board, the
        pipelines in their order (each lead is in exactly one column)."""
        rows: list[LeadRow] = []
        total, skip = 0, offset
        for pipeline in await pipelines.listed(self.session, self.key.tenant_id):
            board = await desk.board(
                pipeline=pipeline.key,
                step=step,
                search=search,
                cursor=skip,
                limit=max(1, limit - len(rows)),
            )
            for group in board.groups:
                for column in group.columns:
                    total += column.count
                    rows.extend(column.cards[: limit - len(rows)])
                    skip = max(0, skip - column.count)
        end = offset + len(rows)
        return LeadPage(leads=tuple(rows), total=total, next_offset=end if end < total else None)

    async def lead(self, lead_id: UUID) -> dict[str, Any]:
        self.require("leads:read")
        try:
            detail = await self._desk().detail(lead_id)
        except DeskError as error:
            raise ApiError(error.status, "lead_desk", str(error)) from None
        result: dict[str, Any] = detail.model_dump(mode="json", by_alias=True)
        return result

    async def app_name(self) -> str | None:
        """The connected app's own name (for example "Pulse"); None for an API key."""
        if not self.key.prefix.startswith("app "):
            return None
        name = await self.session.scalar(
            select(IntegrationOAuthClient.name).where(
                IntegrationOAuthClient.client_id == self.key.prefix[4:]
            )
        )
        return (name or "An AI app")[:80]

    async def _manager_key(self) -> bool:
        """An organisation's API key (not a connected app) whose person is, right now, one
        of the organisation's owners or admins (ai-writes.md, "Amended 15 Nov")."""
        if self.caller.reach != "organisation" or self.key.prefix.startswith("app "):
            return False
        role = await self.session.scalar(
            select(Membership.role).where(
                Membership.tenant_id == self.key.tenant_id,
                Membership.person_id == self.key.acting_person_id,
                Membership.status == "active",
                Membership.ended_at.is_(None),
            )
        )
        return role in {"owner", "admin"}

    async def _writes(self) -> AiWrites:
        """Changes from this caller, behind the AI-write guardrails (ai-writes.md)."""
        self._refuse_read_only()
        desk = self._desk()
        name = await self.app_name()
        if name is not None:
            door = Door(
                via="connection",
                door_id=self.key.key_id,
                label=name,
                scopes=self.key.scopes,
            )
        else:
            door = Door(
                via="key",
                door_id=self.key.key_id,
                label=f"API key {self.key.prefix}",
                scopes=self.key.scopes,
                manager_key=await self._manager_key(),
            )
        return AiWrites(desk, door)

    async def _write(self, change: Any) -> tuple[dict[str, Any], int]:
        try:
            answer: dict[str, Any] = await change
        except AiWriteError as error:
            raise ApiError(error.status, error.code, str(error)) from None
        except DeskError as error:
            raise ApiError(error.status, "lead_desk", str(error)) from None
        fresh = not (answer.get("preview") or answer.get("replayed"))
        return answer, 201 if fresh else 200

    async def add_note(self, lead_id: UUID, body: NoteBody) -> tuple[dict[str, Any], int]:
        writes = await self._writes()
        return await self._write(
            writes.note(lead_id, body.note, request_id=body.request_id, preview=body.preview)
        )

    async def add_task(self, lead_id: UUID, body: TaskBody) -> tuple[dict[str, Any], int]:
        writes = await self._writes()
        return await self._write(
            writes.task(
                lead_id,
                kind=body.kind,
                starts_at=body.due,
                ends_at=body.ends_at,
                title=body.title,
                note=body.note,
                remind_before_minutes=body.remind_before_minutes,
                request_id=body.request_id,
                preview=body.preview,
            )
        )

    async def update_lead(self, lead_id: UUID, body: LeadUpdateBody) -> tuple[dict[str, Any], int]:
        writes = await self._writes()
        return await self._write(
            writes.update(
                lead_id,
                dict(body.fields),
                request_id=body.request_id,
                expected_revision=body.expected_revision,
                preview=body.preview,
            )
        )

    async def tasks(self, view: str = "today", person: UUID | None = None) -> dict[str, Any]:
        """Open tasks as the app's Tasks list shows them (call-backs live in To Call):
        overdue, today or upcoming, with how many of each. ``person``: an owner's or
        admin's look at a seller's list (the desk's own check)."""
        self.require("leads:read")
        if view not in ("overdue", "today", "upcoming"):
            raise ApiError(422, "view", "view is overdue, today or upcoming.")
        bucket: TaskBucket = view  # type: ignore[assignment]
        try:
            listing = await TaskBook(self._desk()).listing(bucket, person)
        except DeskError as error:
            raise ApiError(error.status, "lead_desk", str(error)) from None
        result: dict[str, Any] = listing.model_dump(mode="json", by_alias=True)
        return result

    async def task_done(self, task_id: UUID, body: TaskDoneBody) -> tuple[dict[str, Any], int]:
        writes = await self._writes()
        return await self._write(
            writes.task_done(
                task_id,
                request_id=body.request_id,
                expected_revision=body.expected_revision,
                preview=body.preview,
            )
        )

    async def task_snooze(self, task_id: UUID, body: TaskSnoozeBody) -> tuple[dict[str, Any], int]:
        writes = await self._writes()
        return await self._write(
            writes.task_snooze(
                task_id,
                body.choice,
                request_id=body.request_id,
                expected_revision=body.expected_revision,
                preview=body.preview,
            )
        )

    async def move_stage(self, lead_id: UUID, body: StageBody) -> tuple[dict[str, Any], int]:
        writes = await self._writes()
        return await self._write(
            writes.stage(
                lead_id,
                body.step,
                reason=body.reason,
                reason_code=body.reason_code,
                next_action_at=body.next_action_at,
                expected_revision=body.expected_revision,
                request_id=body.request_id,
                preview=body.preview,
                amount=body.amount,
            )
        )

    async def assign_lead(self, lead_id: UUID, body: AssignBody) -> tuple[dict[str, Any], int]:
        writes = await self._writes()
        return await self._write(
            writes.assign(
                lead_id,
                body.person_id,
                request_id=body.request_id,
                expected_revision=body.expected_revision,
                preview=body.preview,
            )
        )

    async def _filtered(self, chosen: BulkFilter) -> list[UUID]:
        """The leads a stage filter takes, newest change first, up to the bulk limit."""
        found: list[UUID] = []
        offset: int | None = 0
        while offset is not None and len(found) < 1000:
            page = await self.leads(stage=chosen.stage, offset=offset, search=chosen.search)
            found.extend(UUID(str(row["lead_id"])) for row in page["leads"])
            offset = page.get("next_offset")
        return found[:1000]

    async def bulk(self, body: BulkBody) -> tuple[dict[str, Any], int]:
        """One change to many leads (ai-writes.md, "Amended 15 Nov")."""
        if (body.lead_ids is None) == (body.filter is None):
            raise ApiError(422, "leads", "Send lead_ids or a filter, one of them.")
        change = body.change
        if (change.stage is None) == (change.assign is None):
            raise ApiError(422, "change", "The change is one stage move or one assign.")
        writes = await self._writes()
        ids = list(body.lead_ids) if body.lead_ids is not None else []
        if body.filter is not None:
            ids = await self._filtered(body.filter)
            if not ids:
                raise ApiError(404, "no_leads", "No leads match that filter.")
        # As JSON (ids and times as text): the preview answers it and hashes it.
        spec = (
            {"stage": change.stage.model_dump(mode="json", exclude_none=True)}
            if change.stage is not None
            else {"assign": change.assign.model_dump(mode="json") if change.assign else {}}
        )
        return await self._write(
            writes.bulk(
                ids,
                spec,
                request_id=body.request_id,
                preview=body.preview,
                preview_sha=body.preview_sha,
            )
        )

    async def undo_request(self, body: UndoRequestBody) -> dict[str, Any]:
        writes = await self._writes()
        answer, _ = await self._write(writes.undo_request(body.request_id))
        return answer

    async def changes(self, lead_id: UUID | None = None) -> dict[str, Any]:
        writes = await self._writes()
        answer, _ = await self._write(writes.changes(lead_id=lead_id))
        return answer

    async def undo_change(self, change_id: UUID, body: UndoBody) -> dict[str, Any]:
        writes = await self._writes()
        answer, _ = await self._write(writes.undo(change_id, request_id=body.request_id))
        return answer

    async def team(self) -> dict[str, Any]:
        """The team as Lead Desk's Team page shows it, for apps (API gap 7, 15 Nov 2026):
        each person's name and role (never an email or phone), whether they take new leads,
        their lead limit and open leads, and today's work; and the leads waiting for an
        owner. Who may see it is the desk's own check (an organisation's key always)."""
        self.require("team:read")
        try:
            team = await self._desk().team()
        except DeskError as error:
            raise ApiError(error.status, "lead_desk", str(error)) from None
        return {
            "people": [
                {
                    "person_id": str(rep.person_id),
                    "name": rep.name,
                    "role": rep.role,
                    "takes_new_leads": rep.available,
                    "max_open_leads": rep.max_open,
                    "open_leads": rep.open_leads,
                    "over_limit": rep.over_capacity,
                    "due_now": rep.due_now,
                    "calls_today": rep.calls_today,
                    "connected_today": rep.connected_today,
                    "languages": list(rep.languages),
                    "areas": list(rep.areas),
                    "interests": list(rep.interests),
                }
                for rep in team.reps
            ],
            "unassigned_leads": team.unassigned,
            "waiting_first_call": team.waiting_first_call,
        }

    async def analysis_time(self, *, team: bool = False) -> dict[str, Any]:
        """The workspace's analysis time (and, for ``team``, each member's share), read as
        the app reads it. Time only, never a price; names, never emails."""
        self.require("calls:read")
        settings = self.settings
        tenant_id = self.key.tenant_id
        if settings is None or tenant_id == settings.operations_tenant_id:
            raise ApiError(
                404, "not_available", "Analysis time is kept for Sales X-Ray workspaces."
            )
        if team:
            if self.caller.personal_workspace:
                raise ApiError(403, "organisation_only", "A team's time is kept in organisations.")
            if self.caller.reach == "person" and self.caller.role not in {"owner", "admin"}:
                raise ApiError(
                    403,
                    "not_manager",
                    "Your organisation's owner or admin sees its team's analysis time.",
                )
            read = analysis_time.team
        else:
            read = analysis_time.left
        return await read(
            self.session,
            settings,
            tenant_id=tenant_id,
            person_id=self.key.acting_person_id,
            now=datetime.now(UTC),
        )

    async def lead_import_upload(self, body: UploadBody) -> dict[str, Any]:
        """A one-time address to send a CSV of leads to (import_uploads.py)."""
        door = await self.import_door()
        seal = sealed.load_key()
        if seal is None:
            raise ApiError(503, "not_ready", "Uploads aren't set up on this server yet.")
        now = datetime.now(UTC)
        token = import_uploads.make(seal.key, door, body.model_dump(exclude_none=True), now)
        return {
            "upload_url": f"{self.base or ''}/v1/api/leads/imports/upload/{token}",
            "method": "PUT",
            "content_type": "text/csv",
            "expires_at": (now + import_uploads.LIFETIME).isoformat(),
            "max_bytes": import_uploads.MAX_BYTES,
            "max_rows": lead_imports.MAX_ROWS,
            "columns": sorted(set(import_uploads.COLUMNS.values())),
            "then": "The PUT answers the import's id; read it with get_lead_import.",
        }

    async def import_door(self) -> lead_imports.Door:
        """Who an import is from: this key or app connection, acting as its person, with the
        Lead Desk role it reaches (an organisation's key acts as its owner)."""
        self.require("leads:write")
        self._desk()  # leads are kept in organisations, not Personal
        name = await self.app_name()
        return lead_imports.Door(
            via="connection" if name is not None else "key",
            door_id=self.key.key_id,
            tenant_id=self.key.tenant_id,
            acting_person_id=self.key.acting_person_id,
            role="owner" if self.caller.reach == "organisation" else (self.caller.role or "member"),
            label=name or f"API key {self.key.prefix}",
        )

    async def add_lead(self, body: NewLeadBody) -> tuple[dict[str, Any], int]:
        self.require("leads:write")
        record = {
            name: value for name, value in body.model_dump(exclude={"external_id"}).items() if value
        }
        try:
            app = await self.app_name()
            found, outcome = await self._desk().ingest(
                record,
                source="webhook",
                # An app's lead says where it came from: "Pulse", not its client id.
                source_label=app or f"API key {self.key.prefix}",
                source_ref=f"api:{body.external_id}" if body.external_id else None,
            )
        except DeskError as error:
            raise ApiError(error.status, "lead_desk", str(error)) from None
        if found is None:
            raise ApiError(422, "lead_empty", "Send at least a name, phone or email.")
        return {"id": str(found.id), "outcome": outcome}, 201 if outcome == "created" else 200


def make_opener(ctx: RouteContext) -> Any:
    """``open(request)``: check the bearer key or token and yield a ``Reader``."""
    settings = ctx.settings
    limiter = InMemoryTokenBucketLimiter()

    async def caller_for(session: AsyncSession, key: keys.KeyContext, personal: bool) -> Caller:
        if not personal:
            return Caller(key=key, reach="organisation", role="owner")
        if key.tenant_id == settings.public_learner_tenant_id:
            return Caller(key=key, reach="person", role=None, personal_workspace=True)
        role = await session.scalar(
            select(Membership.role).where(
                Membership.tenant_id == key.tenant_id,
                Membership.person_id == key.acting_person_id,
                Membership.status == "active",
                Membership.ended_at.is_(None),
            )
        )
        if role is None or key.tenant_id == settings.operations_tenant_id:
            raise ApiError(
                403, "access_ended", "This person no longer has access to that workspace."
            )
        return Caller(key=key, reach="person", role=role if role in ORG_ROLES else "member")

    @asynccontextmanager
    async def open_reader(request: Request) -> AsyncIterator[Reader]:
        if not settings.is_sales_xray_host(request.url.hostname):
            raise ApiError(404, "not_here", "The Sales X-Ray API is not served here.")
        header = request.headers.get("authorization", "")
        scheme, _, presented = header.partition(" ")
        if scheme.lower() != "bearer" or not presented:
            raise ApiError(
                401, "key_missing", "Send your API key as: Authorization: Bearer sxk_..."
            )
        now = datetime.now(UTC)
        async with ctx.sessions() as session, session.begin():
            presented = presented.strip()
            found = await session.run_sync(
                lambda sync: _authenticate(sync.connection(), presented, settings.environment, now)
            )
            if found is None:
                raise ApiError(401, "key_invalid", "This API key is wrong, expired or revoked.")
            key, personal = found
            caller = await caller_for(session, key, personal)
            if (
                not caller.personal_workspace
                and await session.scalar(
                    select(Organisation.tenant_id).where(Organisation.tenant_id == key.tenant_id)
                )
                is None
            ):
                raise ApiError(403, "organisation_missing", "This organisation is not active.")
            # The plan's limits: per key or connection, and per workspace (a person's own
            # in Personal, which many people share).
            platform = await tiers.read_platform(session)
            tier = await tiers.workspace_tier(
                session,
                platform,
                billing_enabled=settings.billing_enabled,
                tenant_id=key.tenant_id,
                person_id=key.acting_person_id,
                personal=caller.personal_workspace,
                now=now,
            )
            workspace = (
                f"{key.tenant_id}:{key.acting_person_id}"
                if caller.personal_workspace
                else str(key.tenant_id)
            )
            for bucket, rule in (
                (str(key.key_id), tiers.per_key_rule(tier)),
                (workspace, tiers.per_workspace_rule(tier)),
            ):
                allowed, retry, _ = await limiter.consume(bucket, rule)
                if not allowed:
                    raise ApiError(
                        429, "rate_limited", "Too many requests.", retry_after=max(1, retry)
                    )
            # Links go to the app of the family the caller reached (salesxray.in or the old one).
            yield Reader(
                session,
                caller,
                settings.sales_xray_origin_for(request.url.hostname),
                settings.environment,
                tier=tier,
                platform=platform,
                resource=settings.sales_xray_host_origin(request.url.hostname),
                settings=settings,
            )

    return open_reader


async def _any_lead(_: Any, __: UUID) -> bool:
    return True  # checked above, inside the caller's own reader


def install_integrations_api(application: FastAPI, ctx: RouteContext) -> None:
    router = APIRouter(prefix="/v1/api", tags=["sales-xray-api"])
    open_reader = make_opener(ctx)

    @application.exception_handler(ApiError)
    async def api_error(_: Request, error: ApiError) -> JSONResponse:
        return _error(error)

    def done(body: dict[str, Any], status: int = 200) -> JSONResponse:
        return JSONResponse(body, status_code=status, headers=PRIVATE)

    @router.get("/me")
    async def me(request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            return done(await reader.me())

    @router.get("/calls")
    async def calls(request: Request, before: UUID | None = None) -> JSONResponse:
        async with open_reader(request) as reader:
            return done(await reader.calls(before))

    @router.get("/calls/{call_id}")
    async def call(call_id: UUID, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            return done(await reader.call(call_id))

    @router.get("/calls/{call_id}/facts")
    async def call_facts_read(call_id: UUID, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            return done(await reader.facts(call_id))

    @router.get("/leads")
    async def leads(
        request: Request,
        stage: str | None = Query(default=None, max_length=40),
        offset: int = 0,
        limit: int = 50,
    ) -> JSONResponse:
        """A page of leads: ``limit`` 1-50 (default 50), ``offset`` for the next; ``stage``
        is one of the answer's ``stages`` keys, or open."""
        async with open_reader(request) as reader:
            return done(await reader.leads(stage, offset, limit))

    # Many leads at once (integrations/lead_imports.py). Before /leads/{lead_id}, which
    # would take "imports" for an id.
    def refused(refusal: lead_imports.ImportRefused) -> ApiError:
        return ApiError(refusal.status, refusal.code, refusal.message)

    @router.post("/leads/imports/uploads")
    async def lead_import_upload(body: UploadBody, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            return done(await reader.lead_import_upload(body), 201)

    @router.put("/leads/imports/upload/{token}")
    async def lead_import_upload_file(token: str, request: Request) -> JSONResponse:
        """The CSV, sent to its one-time address: the token is the permission, read again in
        full (the key or app still in force, its person still able to add leads)."""
        seal = sealed.load_key()
        if seal is None:
            raise ApiError(503, "not_ready", "Uploads aren't set up on this server yet.")
        now = datetime.now(UTC)
        raw = await request.body()
        try:
            upload = import_uploads.read(seal.key, token, now)
            body = lead_imports.ImportBody(leads=import_uploads.rows(raw), **upload.choices)
            door = upload.door
            async with ctx.sessions() as session, session.begin():
                if not await lead_imports.door_open(session, door.via, door.door_id, now):
                    raise ApiError(
                        403,
                        "key_revoked",
                        "The key or app that asked for this address was revoked.",
                    )
                role = await lead_imports.person_role(
                    session, door.tenant_id, door.acting_person_id, door.role
                )
                if role is None:
                    raise ApiError(
                        403,
                        "person_removed",
                        "The person who asked for this address can no longer add leads.",
                    )
                answer, status = await lead_imports.create(
                    session,
                    replace(door, role=role),
                    body,
                    idempotency_key=f"upload-{upload.nonce}",
                )
        except lead_imports.ImportRefused as refusal:
            raise refused(refusal) from None
        return done(answer, status)

    @router.post("/leads/imports")
    async def import_leads(body: lead_imports.ImportBody, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            door = await reader.import_door()
            try:
                answer, status = await lead_imports.create(
                    reader.session,
                    door,
                    body,
                    idempotency_key=request.headers.get("idempotency-key"),
                )
            except lead_imports.ImportRefused as refusal:
                raise refused(refusal) from None
            return done(answer, status)

    @router.get("/leads/imports")
    async def lead_import_list(request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            door = await reader.import_door()
            return done(
                await lead_imports.recent(reader.session, door, every_door=reader.caller.sees_team)
            )

    async def one_import(reader: Reader, import_id: UUID) -> Any:
        door = await reader.import_door()
        job = await lead_imports.find(
            reader.session, door, import_id, every_door=reader.caller.sees_team
        )
        if job is None:
            raise ApiError(404, "import_missing", "No such import here.")
        return job

    @router.get("/leads/imports/{import_id}")
    async def lead_import(import_id: UUID, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            job = await one_import(reader, import_id)
            return done(await lead_imports.view(reader.session, job))

    @router.get("/leads/imports/{import_id}/rows")
    async def lead_import_rows(
        import_id: UUID,
        request: Request,
        outcome: str | None = Query(default=None, max_length=16),
        after: int = Query(default=-1, ge=-1, le=lead_imports.MAX_ROWS),
        limit: int = Query(default=lead_imports.ROWS_PAGE, ge=1, le=lead_imports.ROWS_PAGE),
    ) -> JSONResponse:
        """Each row's outcome, ``limit`` at a time; ``after`` is the last row seen."""
        async with open_reader(request) as reader:
            job = await one_import(reader, import_id)
            try:
                return done(
                    await lead_imports.rows(
                        reader.session, job, outcome=outcome, after=after, limit=limit
                    )
                )
            except lead_imports.ImportRefused as refusal:
                raise refused(refusal) from None

    @router.get("/leads/{lead_id}")
    async def lead(lead_id: UUID, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            return done(await reader.lead(lead_id))

    @router.get("/duplicates")
    async def duplicates(request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            return done(await reader.duplicates())

    @router.get("/duplicates/{pair_id}")
    async def duplicate(pair_id: UUID, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            return done(await reader.duplicate(pair_id))

    @router.post("/leads")
    async def add_lead(body: NewLeadBody, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            answer, status = await reader.add_lead(body)
            return done(answer, status)

    # AI writes (docs/product/ai-writes.md): notes and tasks, what was changed, and undo.
    @router.post("/leads/{lead_id}/notes")
    async def add_note(lead_id: UUID, body: NoteBody, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            answer, status = await reader.add_note(lead_id, body)
            return done(answer, status)

    @router.post("/leads/{lead_id}/tasks")
    async def add_task(lead_id: UUID, body: TaskBody, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            answer, status = await reader.add_task(lead_id, body)
            return done(answer, status)

    @router.patch("/leads/{lead_id}")
    async def update_lead(lead_id: UUID, body: LeadUpdateBody, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            answer, status = await reader.update_lead(lead_id, body)
            return done(answer, 200 if status == 201 else status)

    @router.get("/tasks")
    async def tasks(
        request: Request, view: str = "today", person: UUID | None = None
    ) -> JSONResponse:
        async with open_reader(request) as reader:
            return done(await reader.tasks(view, person))

    @router.post("/tasks/{task_id}/done")
    async def task_done(task_id: UUID, body: TaskDoneBody, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            answer, status = await reader.task_done(task_id, body)
            return done(answer, 200 if status == 201 else status)

    @router.post("/tasks/{task_id}/snooze")
    async def task_snooze(task_id: UUID, body: TaskSnoozeBody, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            answer, status = await reader.task_snooze(task_id, body)
            return done(answer, 200 if status == 201 else status)

    @router.post("/leads/{lead_id}/stage")
    async def move_stage(lead_id: UUID, body: StageBody, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            answer, status = await reader.move_stage(lead_id, body)
            return done(answer, 200 if status == 201 else status)

    @router.post("/leads/{lead_id}/assign")
    async def assign_lead(lead_id: UUID, body: AssignBody, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            answer, status = await reader.assign_lead(lead_id, body)
            return done(answer, 200 if status == 201 else status)

    @router.post("/leads/bulk")
    async def bulk_leads(body: BulkBody, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            answer, _ = await reader.bulk(body)
            return done(answer)

    @router.post("/changes/undo-request")
    async def undo_request(body: UndoRequestBody, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            return done(await reader.undo_request(body))

    # Recordings an app sends for its person (integrations/app_uploads.py).
    upload_root = app_uploads.inbox_root(ctx.settings.sales_xray_storage_root)
    upload_base = (
        str(ctx.settings.sales_xray_app_url).rstrip("/")
        if ctx.settings.sales_xray_app_url
        else None
    )

    def pulse_on() -> None:
        """App call uploads are off with the rest of Pulse until it is set up here."""
        if not ctx.settings.pulse_configured:
            raise ApiError(404, "pulse_off", app_uploads.PULSE_OFF)

    @router.post("/calls")
    async def upload_call(request: Request) -> JSONResponse:
        pulse_on()
        async with open_reader(request) as reader:
            reader.require("calls:write")
            app = await reader.app_name()
            if app is None or reader.caller.reach != "person":
                raise ApiError(
                    403,
                    "person_only",
                    "Recordings come from an app a person connected, for that person.",
                )
            lead_header = request.headers.get("x-lead-id")
            if lead_header:
                try:
                    await reader._desk().detail(UUID(lead_header))
                except ValueError:
                    raise ApiError(422, "lead_id", "X-Lead-Id must be a lead id.") from None
                except DeskError:
                    raise ApiError(
                        404, "lead_missing", "This person can't see that lead."
                    ) from None
            key = reader.key
        try:
            answer, status = await app_uploads.receive(
                request,
                ctx.sessions,
                root=upload_root,
                tenant_id=key.tenant_id,
                person_id=key.acting_person_id,
                grant_id=key.key_id,
                app_label=app,
                lead_ok=_any_lead,
                base=upload_base,
            )
        except app_uploads.UploadRefused as refusal:
            raise ApiError(refusal.status, refusal.code, refusal.message) from None
        return done(answer, status)

    @router.get("/calls/uploads/{upload_id}")
    async def upload_state(upload_id: UUID, request: Request) -> JSONResponse:
        pulse_on()
        async with open_reader(request) as reader:
            reader.require("calls:write")
            found = await app_uploads.status(
                reader.session,
                upload_id,
                tenant_id=reader.key.tenant_id,
                person_id=reader.key.acting_person_id,
                grant_id=reader.key.key_id,
            )
            if found is None:
                raise ApiError(404, "upload_missing", "No such recording from this connection.")
            return done(app_uploads.upload_view(found, upload_base))

    @router.get("/team")
    async def team(request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            return done(await reader.team())

    @router.get("/analysis-time")
    async def analysis_left(request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            return done(await reader.analysis_time())

    @router.get("/analysis-time/team")
    async def analysis_team(request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            return done(await reader.analysis_time(team=True))

    @router.get("/changes")
    async def changes(request: Request, lead_id: UUID | None = None) -> JSONResponse:
        async with open_reader(request) as reader:
            return done(await reader.changes(lead_id))

    @router.post("/changes/{change_id}/undo")
    async def undo_change(
        change_id: UUID, request: Request, body: UndoBody | None = None
    ) -> JSONResponse:
        async with open_reader(request) as reader:
            return done(await reader.undo_change(change_id, body or UndoBody()))

    application.include_router(router)
    # The importer files waiting chunks in the background (servers only).
    lead_imports.attach(
        application,
        ctx.sessions,
        ctx.settings.environment,
        app_url=str(ctx.settings.sales_xray_app_url or "").rstrip("/"),
    )
