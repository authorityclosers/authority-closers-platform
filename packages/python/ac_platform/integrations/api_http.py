"""The Sales X-Ray API for other apps: ``Authorization: Bearer sxk_...`` (one organisation).

Base address: ``https://<sales x-ray host>/v1/api``.

- GET  /me                  the key's organisation and scopes (any scope)
- GET  /calls               the organisation's calls, newest first (calls:read)
- GET  /calls/{id}/facts    the facts found in one call (reports:read)
- GET  /leads               leads, newest change first (leads:read)
- GET  /leads/{id}          one lead (leads:read)
- POST /leads               add a lead; the same ``external_id`` again changes nothing
                            (leads:write)

A key sees what an organisation owner sees: every call the library shows (retention,
deletion and test calls apply), every lead. Sensitive (withheld) segments are never
quoted. Errors are JSON ``{"error": {"code", "message"}}``; 120 requests a minute per
key, then 429 with ``Retry-After``.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
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
from ac_platform.integrations.models import IntegrationOAuthGrant
from ac_platform.kernel.authz import ActorContext
from ac_platform.lead_desk.store import DeskError, LeadDesk, Viewer
from ac_platform.tenancy.models import Organisation, Tenant

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


def _authenticate(
    connection: Any, presented: str, environment: str, now: datetime
) -> keys.KeyContext | None:
    """An API key (``sxk_``) or a Connect access token (``sxa_``)."""
    if presented.startswith("sxa_"):
        token = oauth.authenticate(connection, presented, now=now)
        if token is None:
            return None
        person = connection.scalar(
            select(IntegrationOAuthGrant.person_id).where(
                IntegrationOAuthGrant.id == token.grant_id
            )
        )
        return keys.KeyContext(
            key_id=token.grant_id,
            tenant_id=token.tenant_id,
            scopes=token.scopes,
            prefix=f"app {token.client_id}",
            acting_person_id=person,
        )
    return keys.authenticate(connection, presented, environment=environment, now=now)


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


def install_integrations_api(application: FastAPI, ctx: RouteContext) -> None:
    router = APIRouter(prefix="/v1/api", tags=["sales-xray-api"])
    settings = ctx.settings
    limiter = InMemoryTokenBucketLimiter()

    @application.exception_handler(ApiError)
    async def api_error(_: Request, error: ApiError) -> JSONResponse:
        return _error(error)

    @asynccontextmanager
    async def keyed(
        request: Request, scope: str | None
    ) -> AsyncIterator[tuple[AsyncSession, keys.KeyContext]]:
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
            key = await session.run_sync(
                lambda sync: _authenticate(sync.connection(), presented, settings.environment, now)
            )
            if key is None:
                raise ApiError(401, "key_invalid", "This API key is wrong, expired or revoked.")
            allowed, retry, _ = await limiter.consume(str(key.key_id), RULE)
            if not allowed:
                raise ApiError(429, "rate_limited", "Too many requests.", retry_after=max(1, retry))
            if scope is not None and scope not in key.scopes:
                raise ApiError(403, "scope_missing", f"This key does not have {scope}.")
            if (
                await session.scalar(
                    select(Organisation.tenant_id).where(Organisation.tenant_id == key.tenant_id)
                )
                is None
            ):
                raise ApiError(403, "organisation_missing", "This organisation is not active.")
            yield session, key

    def desk(session: AsyncSession, key: keys.KeyContext) -> LeadDesk:
        viewer = Viewer(
            person_id=key.acting_person_id, tenant_id=key.tenant_id, role="owner", name=key.prefix
        )
        return LeadDesk(session, viewer)

    @router.get("/me")
    async def me(request: Request) -> JSONResponse:
        async with keyed(request, None) as (session, key):
            name = await session.scalar(select(Tenant.name).where(Tenant.id == key.tenant_id))
            return JSONResponse(
                {
                    "organisation": {"id": str(key.tenant_id), "name": name},
                    "key": {"prefix": key.prefix, "scopes": sorted(key.scopes)},
                    "environment": settings.environment,
                },
                headers=PRIVATE,
            )

    @router.get("/calls")
    async def calls(request: Request, before: UUID | None = None) -> JSONResponse:
        from ac_platform.conversation_intelligence.acquisition_library import (
            _account_library_query,
            _report_columns,
        )
        from ac_platform.conversation_intelligence.acquisition_models import (
            ConversationAcquisitionUsage as Usage,
        )

        async with keyed(request, "calls:read") as (session, key):
            now = datetime.now(UTC)
            # Organisation-wide reading, as an owner sees it; the actor ids are never used.
            reader = ActorContext(person_id=_NIL, session_id=_NIL, tenant_id=key.tenant_id)
            has_report, _ = _report_columns()
            query = _account_library_query(reader, now, every_owner=True).add_columns(has_report)
            if before is not None:
                cursor = (
                    await session.execute(
                        _account_library_query(reader, now, every_owner=True).where(
                            Usage.submission_id == before
                        )
                    )
                ).scalar()
                if cursor is None:
                    raise ApiError(404, "cursor_missing", "That call is not in this list.")
                query = query.where(
                    tuple_(Usage.created_at, Usage.submission_id)
                    < (cursor.created_at, cursor.submission_id)
                )
            rows = (
                await session.execute(
                    query.order_by(Usage.created_at.desc(), Usage.submission_id.desc()).limit(
                        PAGE + 1
                    )
                )
            ).all()
            items = [
                {
                    "id": str(usage.submission_id),
                    "created_at": usage.created_at.isoformat(),
                    "duration_seconds": usage.reserved_seconds,
                    "has_report": bool(reported),
                }
                for usage, reported in rows[:PAGE]
            ]
            return JSONResponse(
                {
                    "calls": items,
                    "next_before": items[-1]["id"] if len(rows) > PAGE else None,
                },
                headers=PRIVATE,
            )

    @router.get("/calls/{call_id}/facts")
    async def call_facts_read(call_id: UUID, request: Request) -> JSONResponse:
        async with keyed(request, "reports:read") as (session, key):
            where = (CallObject.tenant_id == key.tenant_id) & (CallObject.submission_id == call_id)
            result = await session.run_sync(
                lambda sync: call_facts.prospect_facts(
                    sync.connection(), where, {"kind": "call", "id": str(call_id)}
                )
            )
            return JSONResponse(result, headers=PRIVATE)

    @router.get("/leads")
    async def leads(
        request: Request,
        stage: Literal["open", "new", "not_connected", "follow_up", "interested", "won", "lost"]
        | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> JSONResponse:
        """A page of the team's leads: ``limit`` 1-50 (default 50), ``offset`` for the next."""
        async with keyed(request, "leads:read") as (session, key):
            try:
                page = await desk(session, key).leads(
                    scope="team",
                    stage=stage,
                    search=None,
                    offset=max(0, offset),
                    limit=max(1, min(50, limit)),
                )
            except DeskError as error:
                raise ApiError(error.status, "lead_desk", str(error)) from None
            return JSONResponse(page.model_dump(mode="json", by_alias=True), headers=PRIVATE)

    @router.get("/leads/{lead_id}")
    async def lead(lead_id: UUID, request: Request) -> JSONResponse:
        async with keyed(request, "leads:read") as (session, key):
            try:
                detail = await desk(session, key).detail(lead_id)
            except DeskError as error:
                raise ApiError(error.status, "lead_desk", str(error)) from None
            return JSONResponse(detail.model_dump(mode="json", by_alias=True), headers=PRIVATE)

    @router.post("/leads")
    async def add_lead(body: NewLeadBody, request: Request) -> JSONResponse:
        async with keyed(request, "leads:write") as (session, key):
            record = {
                name: value
                for name, value in body.model_dump(exclude={"external_id"}).items()
                if value
            }
            try:
                found, outcome = await desk(session, key).ingest(
                    record,
                    source="webhook",
                    source_label=f"API key {key.prefix}",
                    source_ref=f"api:{body.external_id}" if body.external_id else None,
                )
            except DeskError as error:
                raise ApiError(error.status, "lead_desk", str(error)) from None
            if found is None:
                raise ApiError(422, "lead_empty", "Send at least a name, phone or email.")
            return JSONResponse(
                {"id": str(found.id), "outcome": outcome},
                status_code=201 if outcome == "created" else 200,
                headers=PRIVATE,
            )

    application.include_router(router)
