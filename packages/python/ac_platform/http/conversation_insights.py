"""The company view's routes (AUT-1798) for organisation owners and admins.

``GET /insights`` returns every aggregate of the company view in one answer
(so the page arrives whole), ``GET /insights/calls`` pages through the calls
behind it, and ``POST /insights/refresh`` brings the per-call projection up to
date in one bounded batch. Every request re-checks, from the database, that
the caller is an active owner or admin of the selected organisation; members
get 403. Real calls are limited to the live library scope.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterable
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, Annotated, Any
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, Request, Response
from sqlalchemy import select

from ac_platform.conversation_intelligence.acquisition_library import _account_library_query
from ac_platform.conversation_intelligence.application import ConversationError
from ac_platform.conversation_intelligence.insight_models import OUTCOMES
from ac_platform.conversation_intelligence.org_insights import (
    RANGES,
    InsightFilters,
    OrganisationInsights,
    scope_columns,
)
from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
)
from ac_platform.kernel.authz import ActorContext
from ac_platform.kernel.errors import DomainError
from ac_platform.tenancy.models import Tenant

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
    from ac_platform.http.auth import AuthenticatedTransaction

INDIA = ZoneInfo("Asia/Kolkata")
PARAMS = {"range", "from", "to", "person", "team", "outcome", "language", "offset"}
DENIED = "Only owners and admins of this organisation can see the company view."


def insight_filters(
    request: Request,
    *,
    now: datetime,
    span: str | None,
    start: date | None,
    end: date | None,
    person: str | None,
    team: str | None,
    outcome: str | None,
    language: str | None,
    extra: frozenset[str] = frozenset(),
) -> InsightFilters:
    """Validate the company view's filters; dates are whole India days."""
    names = set(request.query_params)
    if names - PARAMS - extra:
        raise HTTPException(422, "This view takes no other filters.")
    if any(len(request.query_params.getlist(name)) != 1 for name in names):
        raise HTTPException(422, "Give each filter once.")
    if span is not None and span not in (*RANGES, "all"):
        raise HTTPException(422, "Use 30d, 90d, 12m or all.")
    if outcome is not None and outcome not in OUTCOMES:
        raise HTTPException(422, "Use a known outcome.")
    since = None if start is None else datetime.combine(start, time(), INDIA).astimezone(UTC)
    until = (
        None
        if end is None
        else datetime.combine(end + timedelta(days=1), time(), INDIA).astimezone(UTC)
    )
    if since is not None and until is not None and since >= until:
        raise HTTPException(422, "Pick a start date before the end date.")
    return InsightFilters.window(
        now,
        span=span,
        start=since,
        end=until,
        person=person,
        team=team,
        outcome=outcome,
        language=language,
    )


def library_insights(database: AsyncSession, actor: ActorContext) -> OrganisationInsights:
    """Insights limited to the calls the organisation's library shows today."""
    assert actor.tenant_id is not None
    now = datetime.now(UTC)
    ids, rows = scope_columns(_account_library_query(actor, now, every_owner=True))
    return OrganisationInsights(database, actor.tenant_id, scope_ids=ids, scope_rows=rows)


def tenant_insights(
    database: AsyncSession, actor: ActorContext, tenant_id: Any
) -> OrganisationInsights:
    """The Admin counterpart: the same scope for one chosen organisation."""
    return library_insights(database, replace(actor, tenant_id=tenant_id))


async def insight_organisations(
    database: AsyncSession, tenant_ids: Iterable[UUID]
) -> list[dict[str, Any]]:
    """The organisations the Admin company view may open: served ones and sandboxes."""
    served = set(tenant_ids)
    sandboxes = set(await database.scalars(select(ConversationSandboxOrganisation.tenant_id)))
    rows = await database.execute(
        select(Tenant.id, Tenant.name).where(Tenant.id.in_(served | sandboxes))
    )
    return sorted(
        (
            {"id": str(identifier), "name": name, "sandbox": identifier in sandboxes}
            for identifier, name in rows
        ),
        key=lambda item: (item["sandbox"], str(item["name"]).lower(), item["id"]),
    )


def install_insights_http(
    router: APIRouter,
    *,
    hostname: str | None,
    guard: Callable[..., str],
    read_actor: Callable[[Request], AsyncIterator[AuthenticatedTransaction]],
    write_actor: Callable[[Request], AsyncIterator[AuthenticatedTransaction]],
    ownership: Callable[[AsyncSession, UUID], GuestOwnership],
    workspace: Callable[[ActorContext], UUID],
    fail: Callable[..., Any],
) -> None:
    """Mount on the Sales Xray acquisition router; account sessions only."""

    @asynccontextmanager
    async def admitted(
        request: Request, *, write: bool = False
    ) -> AsyncIterator[OrganisationInsights]:
        try:
            async with asynccontextmanager(write_actor if write else read_actor)(request) as auth:
                actor = auth.resolved.actor
                owner = ownership(auth.database, workspace(actor))
                if not await owner.organisation_call_reader(actor):
                    raise fail(403, DENIED)
                yield library_insights(auth.database, actor)
        except ConversationError as error:
            raise fail(error.status, str(error)) from None
        except DomainError:
            raise fail(401, "Sign in to see your organisation's calls.") from None

    def read_guard(request: Request, response: Response) -> None:
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Vary"] = "Cookie"
        if request.url.hostname != hostname:
            raise fail(404, "Not found.")

    @router.get("/insights")
    async def insights(
        request: Request,
        response: Response,
        span: Annotated[str | None, Query(alias="range", max_length=8)] = None,
        start: Annotated[date | None, Query(alias="from")] = None,
        end: Annotated[date | None, Query(alias="to")] = None,
        person: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
        team: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
        outcome: Annotated[str | None, Query(max_length=16)] = None,
        language: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
    ) -> dict[str, Any]:
        """Every aggregate of the company view for one window, in one answer."""
        read_guard(request, response)
        now = datetime.now(UTC)
        filters = insight_filters(
            request,
            now=now,
            span=span,
            start=start,
            end=end,
            person=person,
            team=team,
            outcome=outcome,
            language=language,
        )
        async with admitted(request) as insights:
            return await insights.overview(filters, now=now)

    @router.get("/insights/calls")
    async def insight_calls(
        request: Request,
        response: Response,
        span: Annotated[str | None, Query(alias="range", max_length=8)] = None,
        start: Annotated[date | None, Query(alias="from")] = None,
        end: Annotated[date | None, Query(alias="to")] = None,
        person: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
        team: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
        outcome: Annotated[str | None, Query(max_length=16)] = None,
        language: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
        offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    ) -> dict[str, Any]:
        """The calls behind the company view, newest first, 50 at a time."""
        read_guard(request, response)
        filters = insight_filters(
            request,
            now=datetime.now(UTC),
            span=span,
            start=start,
            end=end,
            person=person,
            team=team,
            outcome=outcome,
            language=language,
        )
        async with admitted(request) as insights:
            return await insights.calls(filters, offset=offset)

    @router.post("/insights/refresh")
    async def refresh_insights(request: Request, response: Response) -> dict[str, Any]:
        """Bring the per-call projection up to date, one bounded batch per request."""
        if guard(request, response, write=True) != "sales":
            raise fail(404, "Not found.")
        async with admitted(request, write=True) as insights:
            return await insights.refresh(now=datetime.now(UTC))
