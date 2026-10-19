"""The company view's routes (AUT-1798), mounted from the app composition.

Sales Xray (``/v1/conversation/acquisition/insights``): ``GET`` returns every
aggregate of the company view in one answer (so the page arrives whole),
``GET /calls`` pages through the calls behind it, and ``POST /refresh``
brings the per-call projection up to date in one bounded batch. Every request
re-checks, from the database, that the caller is an active owner or admin of
the selected organisation (the same rule as the organisation's call reads);
members get 403. Real calls are limited to the live library scope.

Admin (``/v1/admin/conversation/insights``): the same view of any served
organisation (or the synthetic sandbox) for the operations control accounts,
admitted exactly like the call review console.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, Annotated, Any
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response
from sqlalchemy import select

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence import sales_xray_tenants
from ac_platform.conversation_intelligence.acquisition_library import _account_library_query
from ac_platform.conversation_intelligence.admin_call_review import AdminCallReview
from ac_platform.conversation_intelligence.analysis_insights import analysis_insights
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationError,
)
from ac_platform.conversation_intelligence.insight_models import OUTCOMES
from ac_platform.conversation_intelligence.org_insights import (
    RANGES,
    InsightFilters,
    OrganisationInsights,
    scope_columns,
)
from ac_platform.conversation_intelligence.sales_xray_tenants import (
    WORKSPACE_UNAVAILABLE_MESSAGE,
    sales_xray_served_tenant_ids,
)
from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
)
from ac_platform.http.auth import (
    AuthenticatedTransaction,
    RequireActor,
    require_admin_surface,
    require_safe_origin,
)
from ac_platform.kernel.authz import ActorContext
from ac_platform.kernel.errors import DomainError
from ac_platform.organisations.workspace_kinds import classify_workspaces, ordered
from ac_platform.tenancy.models import Membership, Organisation

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ac_platform.http.conversation_intake import ConversationIntakeRuntime

INDIA = ZoneInfo("Asia/Kolkata")
FIRST_DAY, LAST_DAY = date(2000, 1, 1), date(2100, 12, 31)
PARAMS = {"range", "from", "to", "person", "team", "outcome", "language", "offset"}
DENIED = "Only owners and admins of this organisation can see the company view."
PRIVATE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}


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
    for value in (start, end):
        if value is not None and not FIRST_DAY <= value <= LAST_DAY:
            raise HTTPException(422, "Pick dates between 2000 and 2100.")
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


def library_insights(
    database: AsyncSession, actor: ActorContext, *, recordings: bool = False
) -> OrganisationInsights:
    """Insights limited to the calls the organisation's library shows today."""
    assert actor.tenant_id is not None
    now = datetime.now(UTC)
    ids, rows = scope_columns(_account_library_query(actor, now, every_owner=True))
    return OrganisationInsights(
        database, actor.tenant_id, scope_ids=ids, scope_rows=rows, recordings=recordings
    )


def tenant_insights(
    database: AsyncSession, actor: ActorContext, tenant_id: Any
) -> OrganisationInsights:
    """The Admin counterpart: the same scope for one chosen organisation."""
    return library_insights(database, replace(actor, tenant_id=tenant_id), recordings=True)


async def insight_organisations(
    database: AsyncSession,
    tenant_ids: Iterable[UUID],
    *,
    operations_tenant_id: UUID | None = None,
    personal_tenant_id: UUID | None = None,
) -> list[dict[str, Any]]:
    """The organisations the Admin company view may open: served ones and sandboxes.

    Names are the clear ones Admin shows everywhere ("Personal accounts"), with
    the workspace kind; ours first, sandboxes last.
    """
    served = set(tenant_ids)
    sandboxes = set(await database.scalars(select(ConversationSandboxOrganisation.tenant_id)))
    workspaces = await classify_workspaces(
        database,
        operations_tenant_id=operations_tenant_id,
        personal_tenant_id=personal_tenant_id,
        tenant_ids=served | sandboxes,
    )
    return [
        {
            "id": str(item.tenant_id),
            "name": item.name,
            "sandbox": item.tenant_id in sandboxes,
            "kind": item.kind,
        }
        for item in sorted(
            ordered(workspaces.values()), key=lambda item: item.tenant_id in sandboxes
        )
    ]


async def organisation_reader(database: AsyncSession, actor: ActorContext, operations: Any) -> bool:
    """An active owner or admin of the selected organisation, read fresh.

    The same rule as ``GuestOwnership.organisation_call_reader``: never the
    operations tenant, a current membership row of an organisation, active,
    not ended, role owner or admin.
    """
    if actor.tenant_id is None or actor.tenant_id == operations:
        return False
    member = await database.scalar(
        select(Membership)
        .join(Organisation, Organisation.tenant_id == Membership.tenant_id)
        .where(
            Membership.tenant_id == actor.tenant_id,
            Membership.person_id == actor.person_id,
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    return (
        member is not None
        and member.status == "active"
        and member.ended_at is None
        and member.role in {"owner", "admin"}
    )


async def served_tenants(
    settings: Settings, intake: ConversationIntakeRuntime | None, database: AsyncSession
) -> frozenset[UUID]:
    """The tenants Sales Xray serves now, read inside the request (never at startup).

    Uses the live organisation registry's helper (AUT-1694, every active
    organisation) where it exists; until then, the composed served set.
    """
    active = getattr(sales_xray_tenants, "sales_xray_active_tenant_ids", None)
    if active is not None:
        return frozenset(await active(settings, database))
    return sales_xray_served_tenant_ids(settings, intake)


async def workspace_served(
    settings: Settings,
    intake: ConversationIntakeRuntime | None,
    database: AsyncSession,
    tenant_id: UUID | None,
) -> bool:
    """Is the selected workspace served now? The registry's predicate where it exists."""
    if tenant_id is None:
        return False
    predicate = getattr(sales_xray_tenants, "sales_xray_workspace_served", None)
    if predicate is not None:
        return bool(await predicate(database, settings, tenant_id))
    return tenant_id in sales_xray_served_tenant_ids(settings, intake)


def install_insights_routes(
    application: FastAPI,
    *,
    settings: Settings,
    require_actor: RequireActor,
    intake: ConversationIntakeRuntime | None,
    acquisition_intake: ConversationIntakeRuntime | None,
) -> None:
    """Mount the company view: Sales Xray for owners/admins, Admin for AC staff."""
    # Which organisations are served is read inside each request, so an
    # organisation created or suspended after start is seen at once. These are
    # reads of stored figures (no provider call), so they stay mounted on the
    # Sales Xray host even when acquisition isn't composed.
    if settings.sales_xray_app_url is not None:
        _install_sales_xray(
            application,
            settings=settings,
            require_actor=require_actor,
            intake=acquisition_intake,
        )
    _install_admin(application, settings=settings, require_actor=require_actor, intake=intake)


def _install_sales_xray(
    application: FastAPI,
    *,
    settings: Settings,
    require_actor: RequireActor,
    intake: ConversationIntakeRuntime | None,
) -> None:
    assert settings.sales_xray_app_url is not None
    hostname = settings.sales_xray_app_url.host
    read_actor = getattr(require_actor, "read_only", require_actor)
    router = APIRouter(prefix="/v1/conversation/acquisition", tags=["conversation-insights"])

    def fail(status: int, message: str) -> HTTPException:
        return HTTPException(status, message, headers=PRIVATE)

    @asynccontextmanager
    async def admitted(
        request: Request, *, write: bool = False
    ) -> AsyncIterator[OrganisationInsights]:
        try:
            async with asynccontextmanager(require_actor if write else read_actor)(request) as auth:
                actor = auth.resolved.actor
                if not await workspace_served(settings, intake, auth.database, actor.tenant_id):
                    raise fail(403, WORKSPACE_UNAVAILABLE_MESSAGE)
                if not await organisation_reader(
                    auth.database, actor, settings.operations_tenant_id
                ):
                    raise fail(403, DENIED)
                yield library_insights(auth.database, actor)
        except ConversationError as error:
            raise fail(error.status, str(error)) from None
        except DomainError:
            raise fail(401, "Sign in to see your organisation's calls.") from None

    def guard(request: Request, response: Response, *, write: bool = False) -> None:
        response.headers.update(PRIVATE)
        if request.url.hostname != hostname:
            raise fail(404, "Not found.")
        if write:
            if request.query_params:
                raise fail(422, "This command takes no parameters.")
            try:
                require_safe_origin(request, settings, allow_missing_sales_xray_origin=True)
            except DomainError:
                raise fail(403, "Use this Sales Xray page to continue.") from None

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
        guard(request, response)
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
        async with admitted(request) as company:
            return await company.overview(filters, now=now)

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
        guard(request, response)
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
        async with admitted(request) as company:
            return await company.calls(filters, offset=offset)

    @router.post("/insights/refresh")
    async def refresh_insights(request: Request, response: Response) -> dict[str, Any]:
        """Bring the per-call projection up to date, one bounded batch per request."""
        guard(request, response, write=True)
        async with admitted(request, write=True) as company:
            return await company.refresh(now=datetime.now(UTC))

    application.include_router(router)


def _install_admin(
    application: FastAPI,
    *,
    settings: Settings,
    require_actor: RequireActor,
    intake: ConversationIntakeRuntime | None,
) -> None:
    router = APIRouter(prefix="/v1/admin/conversation", tags=["conversation-insights-admin"])
    dependency = Depends(require_actor, scope="function")
    params = frozenset({"organisation"})

    def surface(request: Request, response: Response) -> None:
        require_admin_surface(request, settings)
        response.headers["Cache-Control"] = "private, no-store"

    async def target(
        auth: AuthenticatedTransaction, organisation: UUID | None
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        if settings.operations_tenant_id is None:
            raise HTTPException(503, "Call review is not configured.")
        # Admitted exactly like the call review console, before anything is read.
        await AdminCallReview(
            ConversationApplication(auth.database),
            settings.operations_tenant_id,
            recording_tenant_ids=(),
        )._admit(auth.resolved.actor)
        served = await served_tenants(settings, intake, auth.database)
        organisations = await insight_organisations(
            auth.database,
            served,
            operations_tenant_id=settings.operations_tenant_id,
            personal_tenant_id=settings.public_learner_tenant_id,
        )
        if organisation is None:
            return organisations, organisations[0] if organisations else None
        chosen = next((item for item in organisations if item["id"] == str(organisation)), None)
        if chosen is None:
            raise HTTPException(404, "That organisation isn't served by Sales Xray.")
        return organisations, chosen

    @router.get("/insights")
    async def company_view(
        request: Request,
        response: Response,
        organisation: UUID | None = None,
        span: Annotated[str | None, Query(alias="range", max_length=8)] = None,
        start: Annotated[date | None, Query(alias="from")] = None,
        end: Annotated[date | None, Query(alias="to")] = None,
        person: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
        team: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
        outcome: Annotated[str | None, Query(max_length=16)] = None,
        language: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """One organisation's company view, as its owner sees it (read-only)."""
        surface(request, response)
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
            extra=params,
        )
        try:
            organisations, chosen = await target(auth, organisation)
            overview = (
                None
                if chosen is None
                else await tenant_insights(
                    auth.database, auth.resolved.actor, UUID(chosen["id"])
                ).overview(filters, now=now)
            )
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None
        return {"organisations": organisations, "organisation": chosen, "overview": overview}

    @router.get("/insights/analysis")
    async def company_analysis(
        request: Request,
        response: Response,
        organisation: UUID | None = None,
        days: Annotated[int, Query(ge=1, le=365)] = 30,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """What buyers said and skill scores, from the analysis itself (Phase 4)."""
        surface(request, response)
        try:
            _, chosen = await target(auth, organisation)
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None
        if chosen is None:
            return {"organisation": None}
        found = await analysis_insights(auth.database, UUID(chosen["id"]), days=days)
        return {"organisation": chosen, **found}

    @router.get("/insights/calls")
    async def company_view_calls(
        request: Request,
        response: Response,
        organisation: UUID,
        span: Annotated[str | None, Query(alias="range", max_length=8)] = None,
        start: Annotated[date | None, Query(alias="from")] = None,
        end: Annotated[date | None, Query(alias="to")] = None,
        person: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
        team: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
        outcome: Annotated[str | None, Query(max_length=16)] = None,
        language: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
        offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """The calls behind one organisation's company view, newest first."""
        surface(request, response)
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
            extra=params,
        )
        try:
            await target(auth, organisation)
            return await tenant_insights(auth.database, auth.resolved.actor, organisation).calls(
                filters, offset=offset
            )
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @router.post("/insights/refresh")
    async def company_view_refresh(
        request: Request,
        response: Response,
        organisation: UUID,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """Bring one organisation's per-call projection up to date (one batch)."""
        surface(request, response)
        if set(request.query_params) - params:
            raise HTTPException(422, "This command takes only the organisation.")
        require_safe_origin(request, settings)
        try:
            await target(auth, organisation)
            return await tenant_insights(auth.database, auth.resolved.actor, organisation).refresh(
                now=datetime.now(UTC)
            )
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    application.include_router(router)
