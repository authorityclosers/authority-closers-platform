"""Call data API on the Sales X-Ray account session (/v1/sales-xray/call-data).

- GET  /leads/{lead_id}            a lead's facts from its calls, its open questions
- POST /objects/{object_id}/decision  a person's accept, edit or reject (writes the
  lead through the Lead Desk's own edit, so its owner and revision rules apply)
- POST /objects/{object_id}/undo-fill  one tap puts back a lead field the engine
  filled, while nobody has changed it since (the fact is rejected, so the same
  words don't fill it again)
- GET  /prospect-facts?lead_id=|call_id=  the agreed read for Prospect's Information
- GET  /taxonomy                   every type the engine knows, for the web app

Lead reads and writes go through the Lead Desk's visibility rules. A call's
facts without a lead are visible to the salesperson on that call and to the
workspace's owners and admins.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid5

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ac_platform.call_data import facts, taxonomy, undo
from ac_platform.call_data.models import CallObject
from ac_platform.conversation_intelligence.sales_xray_tenants import SALES_XRAY_MEMBER_ROLES
from ac_platform.http.auth import require_safe_origin
from ac_platform.http.routes import RouteContext
from ac_platform.identity.models import Person
from ac_platform.kernel.errors import DomainError
from ac_platform.lead_desk.contracts import LeadEdit
from ac_platform.lead_desk.store import MANAGERS, DeskError, LeadDesk, Viewer, person_name
from ac_platform.tenancy.models import Membership

PRIVATE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}
LEAD_LIMITS = {"name": 200, "company": 200, "city": 120, "interest": 200}


class DecisionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: UUID
    decision: Literal["accepted", "edited", "rejected"]
    value: dict[str, Any] | None = Field(default=None)


class UndoFillCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: UUID


def install_call_data_http(application: FastAPI, ctx: RouteContext) -> None:
    router = APIRouter(prefix="/v1/sales-xray/call-data", tags=["call-data"])
    read_actor = getattr(ctx.require_actor, "read_only", ctx.require_actor)
    settings = ctx.settings

    def same_host(request: Request) -> None:
        if (
            settings.sales_xray_app_url is None
            or request.url.hostname != settings.sales_xray_app_url.host
        ):
            raise HTTPException(404, "Call facts are unavailable here.", headers=PRIVATE)

    @asynccontextmanager
    async def workspace(
        request: Request, response: Response, *, write: bool = False
    ) -> AsyncIterator[tuple[Any, Viewer]]:
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
                if tenant_id is None or tenant_id in (
                    settings.operations_tenant_id,
                    settings.public_learner_tenant_id,
                ):
                    raise HTTPException(403, "Open a workspace first.", headers=PRIVATE)
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
                if row is None:
                    raise HTTPException(403, "Open a workspace first.", headers=PRIVATE)
                yield (
                    auth,
                    Viewer(
                        person_id=actor.person_id,
                        tenant_id=tenant_id,
                        role=row[0],
                        name=person_name(row[1]),
                    ),
                )
        except DeskError as error:
            raise HTTPException(error.status, str(error), headers=PRIVATE) from None
        except facts.FactsError as error:
            raise HTTPException(error.status, _words(error.code), headers=PRIVATE) from None
        except DomainError:
            raise HTTPException(401, "Sign in to see this.", headers=PRIVATE) from None

    def no_query(request: Request, allowed: frozenset[str] = frozenset()) -> None:
        if any(name not in allowed for name in request.query_params):
            raise HTTPException(422, "Remove the extra address options.", headers=PRIVATE)

    async def lead_view(auth: Any, viewer: Viewer, lead_id: UUID) -> dict[str, Any]:
        detail = await LeadDesk(auth.database, viewer).detail(lead_id)
        lead = detail.lead
        columns = {
            "name": lead.name,
            "company": lead.company,
            "city": lead.city,
            "interest": lead.interest,
        }
        view: dict[str, Any] = await auth.database.run_sync(
            lambda session: facts.lead_facts(
                session.connection(), viewer.tenant_id, lead_id, columns
            )
        )
        return view

    @router.get("/taxonomy")
    async def read_taxonomy(request: Request, response: Response) -> dict[str, object]:
        no_query(request)
        response.headers.update(PRIVATE)
        same_host(request)
        return taxonomy.registry()

    @router.get("/leads/{lead_id}")
    async def read_lead(lead_id: UUID, request: Request, response: Response) -> dict[str, Any]:
        no_query(request)
        async with workspace(request, response) as (auth, viewer):
            return await lead_view(auth, viewer, lead_id)

    @router.post("/objects/{object_id}/decision")
    async def decide(
        object_id: UUID, command: DecisionCommand, request: Request, response: Response
    ) -> dict[str, Any]:
        no_query(request)
        async with workspace(request, response, write=True) as (auth, viewer):
            database = auth.database
            owner = await database.execute(
                select(CallObject.lead_id, CallObject.person_id).where(
                    CallObject.id == object_id, CallObject.tenant_id == viewer.tenant_id
                )
            )
            found = owner.first()
            if found is None:
                raise HTTPException(404, "This fact is not here any more.", headers=PRIVATE)
            desk = LeadDesk(database, viewer)
            detail = await desk.detail(found.lead_id) if found.lead_id else None
            if detail is None and not (
                viewer.role in MANAGERS or found.person_id == viewer.person_id
            ):
                raise HTTPException(404, "This fact is not here any more.", headers=PRIVATE)
            now = datetime.now(UTC)
            decided = await database.run_sync(
                lambda session: facts.plan_decision(
                    session.connection(),
                    tenant_id=viewer.tenant_id,
                    object_id=object_id,
                    person_id=viewer.person_id,
                    decision=command.decision,
                    value=command.value,
                    command_id=command.command_id,
                    now=now,
                )
            )
            written = False
            if detail is not None and decided.lead_field and decided.lead_value:
                field = decided.lead_field
                value = decided.lead_value.strip()[: LEAD_LIMITS[field]]
                current = getattr(detail.lead, field)
                if value and (current or "").strip().casefold() != value.casefold():
                    await desk.edit(
                        detail.lead.lead_id,
                        LeadEdit(
                            command_id=uuid5(command.command_id, "lead-field"),
                            expected_revision=detail.lead.revision,
                            **{field: value},
                        ),
                    )
                    written = True
            try:
                await database.run_sync(
                    lambda session: facts.save_decision(
                        session.connection(), decided, lead_written=written
                    )
                )
                await database.flush()
            except IntegrityError:
                raise HTTPException(
                    409, "Someone answered this already. Refresh to see it.", headers=PRIVATE
                ) from None
            if found.lead_id is None:
                return {"schema": facts.LEAD_SCHEMA, "decided": str(object_id)}
            return await lead_view(auth, viewer, found.lead_id)

    @router.post("/objects/{object_id}/undo-fill")
    async def undo_fill(
        object_id: UUID, command: UndoFillCommand, request: Request, response: Response
    ) -> dict[str, Any]:
        no_query(request)
        async with workspace(request, response, write=True) as (auth, viewer):
            try:
                lead_id = await undo.undo_fill(
                    auth.database, viewer, object_id, command.command_id, datetime.now(UTC)
                )
            except IntegrityError:
                raise HTTPException(
                    409, "Someone answered this already. Refresh to see it.", headers=PRIVATE
                ) from None
            return await lead_view(auth, viewer, lead_id)

    @router.get("/prospect-facts")
    async def prospect_facts(
        request: Request,
        response: Response,
        lead_id: UUID | None = None,
        call_id: UUID | None = None,
    ) -> dict[str, Any]:
        no_query(request, frozenset({"lead_id", "call_id"}))
        if (lead_id is None) == (call_id is None):
            raise HTTPException(422, "Ask for one lead or one call.", headers=PRIVATE)
        async with workspace(request, response) as (auth, viewer):
            if lead_id is not None:
                await LeadDesk(auth.database, viewer).detail(lead_id)
                where = (CallObject.tenant_id == viewer.tenant_id) & (CallObject.lead_id == lead_id)
                subject = {"kind": "lead", "id": str(lead_id)}
            else:
                where = (CallObject.tenant_id == viewer.tenant_id) & (
                    CallObject.submission_id == call_id
                )
                if viewer.role not in MANAGERS:
                    where = where & (CallObject.person_id == viewer.person_id)
                subject = {"kind": "call", "id": str(call_id)}
            result: dict[str, Any] = await auth.database.run_sync(
                lambda session: facts.prospect_facts(session.connection(), where, subject)
            )
            return result

    application.include_router(router)


_WORDS = {
    "decision_unknown": "Choose keep, change or remove.",
    "command_reused": "That answer was for another fact.",
    "fact_missing": "This fact is not here any more.",
    "fact_replaced": "A newer reading of the call replaced this fact. Refresh to see it.",
    "fact_type_retired": "This kind of fact is no longer used.",
    "already_answered": "This was answered already.",
    "fill_gone": "This was already changed or removed. Refresh to see it.",
    "fill_old": "This was filled before undo was possible. Change it on the lead instead.",
    "fill_changed": "Someone changed this field since. Nothing was undone.",
    "fill_name": "A lead needs a name. Change it on the lead instead.",
}


def _words(code: str) -> str:
    return _WORDS.get(code, "Check the value and try again.")
