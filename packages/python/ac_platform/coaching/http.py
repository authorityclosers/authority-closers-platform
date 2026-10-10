"""Private Coaching reads on the existing Sales Xray account session only."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from sqlalchemy import select

from ac_platform.coaching.call import CallCoachingCache, CallCoachingView
from ac_platform.coaching.contracts import CoachingView
from ac_platform.coaching.library import CoachingLibrary
from ac_platform.coaching.team import TeamCoachingView
from ac_platform.conversation_intelligence.acquisition_sessions import AcquisitionSessions
from ac_platform.conversation_intelligence.application import ConversationError
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.sales_xray_tenants import SALES_XRAY_MEMBER_ROLES
from ac_platform.http.routes import RouteContext
from ac_platform.kernel.authz import ActorContext
from ac_platform.kernel.errors import DomainError
from ac_platform.tenancy.models import Membership, Organisation

PRIVATE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}


def install_coaching_http(application: FastAPI, ctx: RouteContext) -> None:
    router = APIRouter(prefix="/v1/me/coaching", tags=["coaching"])
    read_actor = getattr(ctx.require_actor, "read_only", ctx.require_actor)
    call_cache = CallCoachingCache()

    @asynccontextmanager
    async def account_library(
        request: Request, response: Response
    ) -> AsyncIterator[tuple[CoachingLibrary, ActorContext]]:
        response.headers.update(PRIVATE)
        settings = ctx.settings
        if (
            settings.sales_xray_app_url is None
            or request.url.hostname != settings.sales_xray_app_url.host
        ):
            raise HTTPException(404, "Coaching is unavailable.", headers=PRIVATE)
        if request.query_params:
            raise HTTPException(
                422, "Coaching uses your signed-in account and workspace.", headers=PRIVATE
            )
        try:
            async with asynccontextmanager(read_actor)(request) as auth:
                actor = auth.resolved.actor
                tenant_id = actor.tenant_id
                if tenant_id is None or tenant_id == settings.operations_tenant_id:
                    raise HTTPException(403, "Choose a Sales Xray workspace.", headers=PRIVATE)
                member = await auth.database.scalar(
                    select(Membership)
                    .where(
                        Membership.tenant_id == tenant_id,
                        Membership.person_id == actor.person_id,
                        Membership.status == "active",
                        Membership.ended_at.is_(None),
                        Membership.role.in_(SALES_XRAY_MEMBER_ROLES),
                    )
                    .with_for_update(read=True)
                )
                organisation = await auth.database.scalar(
                    select(Organisation).where(
                        Organisation.tenant_id == tenant_id,
                    )
                )
                if member is None or (
                    tenant_id != settings.public_learner_tenant_id and organisation is None
                ):
                    raise HTTPException(
                        403, "Coaching is unavailable in this workspace.", headers=PRIVATE
                    )
                # AUT-1678: coaching is open to internal, free and unlimited
                # accounts. No payment/provider balance or analysis credit is read.
                sessions = AcquisitionSessions(
                    auth.database,
                    tenant_id=tenant_id,
                    policy_revision="AUT-1678-open-access",
                    operations_tenant_id=settings.operations_tenant_id,
                )
                yield CoachingLibrary(GuestOwnership(sessions)), actor
        except ConversationError as error:
            raise HTTPException(error.status, str(error), headers=PRIVATE) from None
        except DomainError:
            raise HTTPException(401, "Sign in to see your Coaching.", headers=PRIVATE) from None

    @router.get("", response_model=CoachingView, response_model_by_alias=True)
    async def coaching(request: Request, response: Response) -> CoachingView:
        async with account_library(request, response) as (library, actor):
            view = await library.read(actor)
            return view.model_copy(update={"session_id": actor.session_id})

    @router.get(
        "/calls/{submission_id}", response_model=CallCoachingView, response_model_by_alias=True
    )
    async def call_coaching(
        submission_id: UUID, request: Request, response: Response
    ) -> CallCoachingView:
        async with account_library(request, response) as (library, actor):
            view = await library.read_call(actor, submission_id, call_cache)
            return view.model_copy(update={"session_id": actor.session_id})

    @router.get("/team", response_model=TeamCoachingView, response_model_by_alias=True)
    async def team_coaching(request: Request, response: Response) -> TeamCoachingView:
        async with account_library(request, response) as (library, actor):
            view = await library.read_team(actor)
            return view.model_copy(update={"session_id": actor.session_id})

    application.include_router(router)
