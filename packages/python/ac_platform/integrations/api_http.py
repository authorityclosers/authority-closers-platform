"""The Sales X-Ray API for other apps: ``Authorization: Bearer sxk_...`` or ``sxa_...``.

Base address: ``https://<sales x-ray host>/v1/api``.

- GET  /me                  who is calling: organisation or workspace, scopes (any scope)
- GET  /calls               calls, newest first (calls:read)
- GET  /calls/{id}          one call, with its facts when reports:read is held (calls:read)
- GET  /calls/{id}/facts    the facts found in one call (reports:read)
- GET  /leads               leads, newest change first (leads:read)
- GET  /leads/{id}          one lead (leads:read)
- POST /leads               add a lead; the same ``external_id`` again changes nothing
                            (leads:write)

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
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.call_data import facts as call_facts
from ac_platform.call_data.models import CallObject
from ac_platform.http.rate_limits import InMemoryTokenBucketLimiter, RateLimitRule
from ac_platform.http.routes import RouteContext
from ac_platform.integrations import keys, oauth
from ac_platform.kernel.authz import ActorContext
from ac_platform.lead_desk.store import DeskError, LeadDesk, Viewer
from ac_platform.tenancy.models import Membership, Organisation, Tenant

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
STAGES = ("open", "new", "not_connected", "follow_up", "interested", "won", "lost")
Stage = Literal["open", "new", "not_connected", "follow_up", "interested", "won", "lost"]


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, retry_after: int | None = None):
        super().__init__(code)
        self.status, self.code, self.message, self.retry_after = status, code, message, retry_after


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
        return self.reach == "organisation" or self.role in {"owner", "admin"}


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
        self, session: AsyncSession, caller: Caller, base: str | None, environment: str
    ) -> None:
        self.session, self.caller, self.base = session, caller, base
        self.environment = environment

    @property
    def key(self) -> keys.KeyContext:
        return self.caller.key

    def require(self, scope: str) -> None:
        if scope not in self.key.scopes:
            raise ApiError(403, "scope_missing", f"This key does not have {scope}.")

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

    async def leads(
        self, stage: str | None = None, offset: int = 0, limit: int = 50
    ) -> dict[str, Any]:
        self.require("leads:read")
        if stage is not None and stage not in STAGES:
            raise ApiError(422, "stage_unknown", f"stage is one of {', '.join(STAGES)}.")
        try:
            page = await self._desk().leads(
                scope="team" if self.caller.sees_team else "mine",
                stage=stage,
                search=None,
                offset=max(0, offset),
                limit=max(1, min(50, limit)),
            )
        except DeskError as error:
            raise ApiError(error.status, "lead_desk", str(error)) from None
        result: dict[str, Any] = page.model_dump(mode="json", by_alias=True)
        return result

    async def lead(self, lead_id: UUID) -> dict[str, Any]:
        self.require("leads:read")
        try:
            detail = await self._desk().detail(lead_id)
        except DeskError as error:
            raise ApiError(error.status, "lead_desk", str(error)) from None
        result: dict[str, Any] = detail.model_dump(mode="json", by_alias=True)
        return result

    async def add_lead(self, body: NewLeadBody) -> tuple[dict[str, Any], int]:
        self.require("leads:write")
        record = {
            name: value for name, value in body.model_dump(exclude={"external_id"}).items() if value
        }
        try:
            found, outcome = await self._desk().ingest(
                record,
                source="webhook",
                source_label=f"API key {self.key.prefix}",
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
    base = str(settings.sales_xray_app_url).rstrip("/") if settings.sales_xray_app_url else None

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
        return Caller(
            key=key, reach="person", role=role if role in {"owner", "admin"} else "member"
        )

    @asynccontextmanager
    async def open_reader(request: Request) -> AsyncIterator[Reader]:
        if (
            settings.sales_xray_app_url is None
            or request.url.hostname != settings.sales_xray_app_url.host
        ):
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
            allowed, retry, _ = await limiter.consume(str(key.key_id), RULE)
            if not allowed:
                raise ApiError(429, "rate_limited", "Too many requests.", retry_after=max(1, retry))
            caller = await caller_for(session, key, personal)
            if (
                not caller.personal_workspace
                and await session.scalar(
                    select(Organisation.tenant_id).where(Organisation.tenant_id == key.tenant_id)
                )
                is None
            ):
                raise ApiError(403, "organisation_missing", "This organisation is not active.")
            yield Reader(session, caller, base, settings.environment)

    return open_reader


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
        stage: Stage | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> JSONResponse:
        """A page of leads: ``limit`` 1-50 (default 50), ``offset`` for the next."""
        async with open_reader(request) as reader:
            return done(await reader.leads(stage, offset, limit))

    @router.get("/leads/{lead_id}")
    async def lead(lead_id: UUID, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            return done(await reader.lead(lead_id))

    @router.post("/leads")
    async def add_lead(body: NewLeadBody, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            answer, status = await reader.add_lead(body)
            return done(answer, status)

    application.include_router(router)
