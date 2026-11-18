"""Analysis minutes given, used and left (owner, 18 Nov 2026), on the Sales Xray host.

- ``GET /v1/conversation/acquisition/minutes``: the signed-in person's minutes in the
  selected workspace. In an organisation that is the shared pool plus their own use;
  in the Personal workspace, their own account.
- ``GET /v1/conversation/acquisition/minutes/workspace``: the organisation's pool and
  each current member's grants and use, for its active owners and admins only (the
  company view's rule); members get 403.

Both are reads of the minutes ledger (``conversation_intelligence.minutes_summary``):
seconds only, never a price, nothing written.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from sqlalchemy import select

from ac_platform.application.settings import Settings
from ac_platform.billing.ledger import BillingError
from ac_platform.conversation_intelligence import minutes_summary
from ac_platform.conversation_intelligence.application import ConversationError
from ac_platform.conversation_intelligence.sales_xray_tenants import (
    WORKSPACE_UNAVAILABLE_MESSAGE,
)
from ac_platform.http.auth import AuthenticatedTransaction, RequireActor
from ac_platform.http.conversation_insights import (
    PRIVATE,
    organisation_reader,
    workspace_served,
)
from ac_platform.kernel.authz import ActorContext
from ac_platform.kernel.errors import DomainError
from ac_platform.tenancy.models import Membership

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ac_platform.http.conversation_intake import ConversationIntakeRuntime

DENIED = "Only owners and admins of this organisation can see everyone's minutes."
NOT_A_MEMBER = "You are not a current member of this workspace."


async def current_member(database: AsyncSession, actor: ActorContext, settings: Settings) -> bool:
    """The Personal workspace's own person, or an active member of the organisation."""
    if actor.tenant_id is None or actor.tenant_id == settings.operations_tenant_id:
        return False
    if actor.tenant_id == settings.public_learner_tenant_id:
        return True
    member = await database.scalar(
        select(Membership).where(
            Membership.tenant_id == actor.tenant_id,
            Membership.person_id == actor.person_id,
        )
    )
    return member is not None and member.status == "active" and member.ended_at is None


def install_minutes_routes(
    application: FastAPI,
    *,
    settings: Settings,
    require_actor: RequireActor,
    intake: ConversationIntakeRuntime | None,
) -> None:
    """Mount the minutes reads on the Sales Xray host (nothing when it isn't configured)."""
    if settings.sales_xray_app_url is None:
        return
    read_actor = getattr(require_actor, "read_only", require_actor)
    router = APIRouter(prefix="/v1/conversation/acquisition", tags=["conversation-minutes"])

    def fail(status: int, message: str) -> HTTPException:
        return HTTPException(status, message, headers=PRIVATE)

    def guard(request: Request, response: Response) -> None:
        response.headers.update(PRIVATE)
        if not settings.is_sales_xray_host(request.url.hostname):
            raise fail(404, "Not found.")
        if request.query_params:
            raise fail(422, "This read takes no parameters.")

    @asynccontextmanager
    async def admitted(request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        try:
            async with asynccontextmanager(read_actor)(request) as auth:
                actor = auth.resolved.actor
                if not await workspace_served(settings, intake, auth.database, actor.tenant_id):
                    raise fail(403, WORKSPACE_UNAVAILABLE_MESSAGE)
                yield auth
        except (ConversationError, BillingError) as error:
            raise fail(getattr(error, "status", 403), str(error)) from None
        except DomainError:
            raise fail(401, "Sign in to see your analysis minutes.") from None

    @router.get("/minutes")
    async def my_minutes(request: Request, response: Response) -> dict[str, Any]:
        """Minutes given, used and left for the signed-in person's workspace."""
        guard(request, response)
        async with admitted(request) as auth:
            actor = auth.resolved.actor
            tenant_id = actor.tenant_id
            if tenant_id is None or not await current_member(auth.database, actor, settings):
                raise fail(403, NOT_A_MEMBER)
            return await minutes_summary.seller_minutes(
                auth.database,
                tenant_id=tenant_id,
                person_id=actor.person_id,
                now=datetime.now(UTC),
                operations_tenant_id=settings.operations_tenant_id,
                public_learner_tenant_id=settings.public_learner_tenant_id,
            )

    @router.get("/minutes/workspace")
    async def workspace_minutes(request: Request, response: Response) -> dict[str, Any]:
        """The organisation's pool and every current member's grants and use."""
        guard(request, response)
        async with admitted(request) as auth:
            actor = auth.resolved.actor
            tenant_id = actor.tenant_id
            if (
                tenant_id is None
                or tenant_id == settings.public_learner_tenant_id
                or not await organisation_reader(
                    auth.database, actor, settings.operations_tenant_id
                )
            ):
                raise fail(403, DENIED)
            return await minutes_summary.workspace_minutes(
                auth.database,
                tenant_id=tenant_id,
                now=datetime.now(UTC),
                operations_tenant_id=settings.operations_tenant_id,
                public_learner_tenant_id=settings.public_learner_tenant_id,
            )

    application.include_router(router)


__all__ = ["DENIED", "NOT_A_MEMBER", "current_member", "install_minutes_routes"]
