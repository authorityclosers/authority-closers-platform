"""Admin → Sellers (owner, 24 Oct 2026: "finding out what went wrong for a seller is too
hard ... Build one Admin screen that makes it obvious").

GET /v1/admin/sellers?email=
    The person signed up with that email (one exact, case-blind match by its unique index).
GET /v1/admin/sellers/{person_id}/timeline?days=7|14|30
    What happened, day by day: workspaces and sign-ins, devices and versions, what reached
    the server beside what the phone reported, and a line naming the newest gap
    (telemetry/seller_timeline.py). Counts, times and states only.

Both follow the other Admin areas: Admin host, the AC operations workspace, a Sales X-Ray
control account.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from sqlalchemy import func, select

from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationError,
)
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.http.auth import AuthenticatedTransaction, require_admin_surface
from ac_platform.http.routes import RouteContext
from ac_platform.identity.models import Person
from ac_platform.telemetry import seller_timeline

PRIVATE = {"Cache-Control": "private, no-store"}


def install_admin_sellers_http(application: FastAPI, ctx: RouteContext) -> None:
    settings = ctx.settings
    dependency = Depends(
        getattr(ctx.require_actor, "read_only", ctx.require_actor), scope="function"
    )
    router = APIRouter(prefix="/v1/admin/sellers", tags=["admin-sellers"])

    async def admit(
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction,
        query: frozenset[str],
    ) -> None:
        require_admin_surface(request, settings)
        response.headers.update(PRIVATE)
        if set(request.query_params) - query:
            raise HTTPException(422, "This view takes other filters.")
        actor = auth.resolved.actor
        if (
            settings.operations_tenant_id is None
            or actor.tenant_id != settings.operations_tenant_id
        ):
            raise HTTPException(403, "Use the AC operations workspace.")
        try:
            await ConversationProviderAdmin(ConversationApplication(auth.database)).admit(actor)
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @router.get("")
    async def find(
        request: Request,
        response: Response,
        email: str,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        await admit(request, response, auth, frozenset({"email"}))
        wanted = email.strip().lower()
        if not (3 <= len(wanted) <= 320 and "@" in wanted):
            raise HTTPException(422, "Enter the email they signed up with.")

        def read(connection: Any) -> Any:
            return connection.execute(
                select(Person.id, Person.display_name, Person.first_name, Person.email).where(
                    func.lower(Person.email) == wanted
                )
            ).first()

        row = await auth.database.run_sync(read)
        if row is None:
            raise HTTPException(404, "No one has signed up with that email.")
        person, display, first, found = row
        return {"person": {"id": str(person), "name": display or first, "email": found}}

    @router.get("/{person_id}/timeline")
    async def timeline(
        request: Request,
        response: Response,
        person_id: UUID,
        days: int = 14,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        await admit(request, response, auth, frozenset({"days"}))
        if days not in seller_timeline.DAYS:
            raise HTTPException(422, "Choose 7, 14 or 30 days.")
        now = datetime.now(UTC)
        since = seller_timeline.window_start(now, days)

        def read(connection: Any) -> seller_timeline.Inputs | None:
            return seller_timeline.read(
                connection,
                person_id,
                since=since,
                now=now,
                personal_tenant_id=settings.public_learner_tenant_id,
                operations_tenant_id=settings.operations_tenant_id,
            )

        inputs = await auth.database.run_sync(read)
        if inputs is None:
            raise HTTPException(404, "That person is not here.")
        return seller_timeline.build(inputs, now=now, days=days)

    application.include_router(router)


__all__ = ["install_admin_sellers_http"]
