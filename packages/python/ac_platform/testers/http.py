"""Sales X-Ray Play testers over HTTP (owner, 13 Nov 2026).

The person, signed in on a Sales X-Ray address (/testers):

GET  /v1/sales-xray/testers/me
    Where they stand: none, waiting, approved (being added to the group), ready (in the
    group: the two Play steps) or declined, with the Play links once ready.
POST /v1/sales-xray/testers/me   {phone_model, role, business}
    Joins the waitlist with the Google account they signed in with. Once only.

The team, in Admin -> Testers (Admin host, the AC operations workspace, a Sales X-Ray
control account, as Bugs):

GET  /v1/admin/testers
    Everyone on the list with their stage, counts per stage and Play's 12-tester line.
GET  /v1/admin/testers/export.csv
    The same list as a spreadsheet.
POST /v1/admin/testers/{id}/decision   {decision: approve|decline, note?}
POST /v1/admin/testers/{id}/group      {send_email}   "Added to the group" (+ the email)
POST /v1/admin/testers/{id}/email      The welcome email (again)
POST /v1/admin/testers/{id}/hours      Their 3 hours of call analysis (hours.py)

Approving, "Added" and the email also give the tester their 3 hours of call analysis where
they are due (an organisation member's audited grant, approved by the Admin who acted).

A tester's {id} is their first row's id, never their email, so no address rides in a URL.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationError,
)
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.http.auth import (
    AuthenticatedTransaction,
    require_admin_surface,
    require_safe_origin,
)
from ac_platform.http.routes import RouteContext
from ac_platform.identity.models import Person
from ac_platform.kernel.errors import DomainError
from ac_platform.testers import hours, store

PRIVATE = {"Cache-Control": "private, no-store"}


class TesterApplication(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    phone_model: str = Field(min_length=2, max_length=80)
    role: Literal["owner", "manager", "seller", "other"]
    business: str = Field(min_length=2, max_length=120)


class TesterDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    decision: Literal["approve", "decline"]
    note: str | None = Field(default=None, max_length=500)


class TesterGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    send_email: bool = True


def _mask(email: str | None) -> str | None:
    if not email or "@" not in email:
        return email
    local, domain = email.split("@", 1)
    return f"{local[:1]}…@{domain}"


def _public(standing: store.Standing | None, email: str) -> dict[str, Any]:
    state = standing.public_state if standing is not None else "none"
    answer: dict[str, Any] = {"state": state, "email": email}
    if standing is not None:
        answer["phone_model"] = standing.phone_model
        answer["listed"] = standing.listed_at is not None
    if state == "ready":
        answer["links"] = {"opt_in": store.OPT_IN_URL, "play": store.PLAY_URL}
    return answer


def install_testers_http(app: FastAPI, ctx: RouteContext) -> None:
    settings = ctx.settings
    dependency = Depends(ctx.require_actor, scope="function")
    read_dependency = Depends(
        getattr(ctx.require_actor, "read_only", ctx.require_actor), scope="function"
    )

    # ---------- The person ----------

    public = APIRouter(prefix="/v1/sales-xray/testers", tags=["sales-xray-testers"])

    def on_app_host(request: Request) -> None:
        hosts = {settings.public_app_url.host}
        hosts.update(settings.sales_xray_hosts)
        if request.url.hostname not in hosts or request.query_params:
            raise HTTPException(404, "Not found.", headers=PRIVATE)

    async def signed_in(auth: AuthenticatedTransaction) -> Person:
        person = await auth.database.get(Person, auth.resolved.actor.person_id)
        if person is None or not person.email or person.email_verified_at is None:
            raise HTTPException(403, "Sign in with your Google account first.", headers=PRIVATE)
        return person

    @public.get("/me")
    async def mine(
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = read_dependency,
    ) -> dict[str, Any]:
        response.headers.update(PRIVATE)
        on_app_host(request)
        person = await signed_in(auth)
        email = store.normal_email(person.email or "")
        return _public(await store.standing_for_email(auth.database, email), email)

    @public.post("/me")
    async def join(
        command: TesterApplication,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        response.headers.update(PRIVATE)
        on_app_host(request)
        try:
            require_safe_origin(request, settings)
        except DomainError:
            raise HTTPException(403, "Send this from the testers page.", headers=PRIVATE) from None
        person = await signed_in(auth)
        email = store.normal_email(person.email or "")
        try:
            standing = await store.apply(
                auth.database,
                person_id=person.id,
                email=email,
                name=person.display_name or getattr(person, "first_name", None),
                phone_model=command.phone_model,
                role=command.role,
                business=command.business,
                now=datetime.now(UTC),
            )
        except store.TesterRefused as error:
            raise HTTPException(422, str(error), headers=PRIVATE) from None
        return _public(standing, email)

    app.include_router(public)

    # ---------- The team ----------

    admin = APIRouter(prefix="/v1/admin/testers", tags=["sales-xray-testers-admin"])

    async def admit(
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction,
        *,
        write: bool,
    ) -> Any:
        require_admin_surface(request, settings)
        response.headers.update(PRIVATE)
        if write:
            try:
                require_safe_origin(request, settings)
            except DomainError:
                raise HTTPException(403, "Use this Admin page to continue.") from None
        if request.query_params:
            raise HTTPException(422, "This view takes no filters.")
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
        return actor

    async def read(request: Request, auth: AuthenticatedTransaction) -> dict[str, Any]:
        page = await store.listing(auth.database, now=datetime.now(UTC))
        states = await hours.hours_for(
            auth.database, settings, [item["email"] for item in page["items"]]
        )
        for item in page["items"]:
            item["hours"] = states.get(item["email"], "on_sign_in")
        page["tester_hours"] = hours.TESTER_HOURS
        # A staff key (agents) reads stages and counts; addresses and names stay masked.
        if getattr(request.state, "staff_key_row", None) is not None:
            for item in page["items"]:
                item["email"] = _mask(item["email"])
                item["name"] = None
        return page

    @admin.get("")
    async def listing(
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = read_dependency,
    ) -> dict[str, Any]:
        await admit(request, response, auth, write=False)
        return await read(request, auth)

    @admin.get("/export.csv")
    async def export(
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = read_dependency,
    ) -> Response:
        await admit(request, response, auth, write=False)
        page = await read(request, auth)
        day = datetime.now(UTC).strftime("%Y-%m-%d")
        return Response(
            content=store.to_csv(page["items"]),
            media_type="text/csv; charset=utf-8",
            headers={
                **PRIVATE,
                "Content-Disposition": f'attachment; filename="sales-xray-testers-{day}.csv"',
            },
        )

    async def acting(auth: AuthenticatedTransaction) -> tuple[UUID, str | None]:
        actor = auth.resolved.actor
        email = await auth.database.scalar(select(Person.email).where(Person.id == actor.person_id))
        return actor.person_id, email

    async def answer(
        request: Request,
        auth: AuthenticatedTransaction,
        tester_id: UUID,
        given: hours.HoursOutcome | None = None,
    ) -> dict[str, Any]:
        page = await read(request, auth)
        for item in page["items"]:
            if item["id"] == str(tester_id):
                body: dict[str, Any] = {"tester": item, "counts": page["counts"]}
                if given is not None:
                    body["hours"] = given
                    body["hours_words"] = hours.HOURS_WORDS[given]
                return body
        raise HTTPException(404, "No tester has that reference.")

    async def give(
        auth: AuthenticatedTransaction, tester_id: UUID, person_id: UUID
    ) -> hours.HoursOutcome:
        standing = await store.standing_for(auth.database, tester_id)
        return await hours.give_tester_hours(
            auth.database,
            settings,
            email=standing.email,
            approver_person_id=person_id,
            session_id=getattr(auth.resolved.actor, "session_id", None),
            request_id=None,
        )

    def refused(error: Exception) -> HTTPException:
        if isinstance(error, store.TesterNotFound):
            return HTTPException(404, "No tester has that reference.")
        return HTTPException(422, str(error))

    @admin.post("/{tester_id}/decision")
    async def decision(
        tester_id: UUID,
        command: TesterDecision,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        await admit(request, response, auth, write=True)
        person_id, email = await acting(auth)
        try:
            await store.decide(
                auth.database,
                tester_id,
                decision=command.decision,
                actor_person_id=person_id,
                actor_email=email,
                note=command.note,
                now=datetime.now(UTC),
            )
        except (store.TesterRefused, store.TesterNotFound) as error:
            raise refused(error) from None
        given = await give(auth, tester_id, person_id) if command.decision == "approve" else None
        return await answer(request, auth, tester_id, given)

    @admin.post("/{tester_id}/group")
    async def group(
        tester_id: UUID,
        command: TesterGroup,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        await admit(request, response, auth, write=True)
        person_id, _ = await acting(auth)
        try:
            await store.mark_added(
                auth.database,
                tester_id,
                actor_person_id=person_id,
                send_email=command.send_email,
                now=datetime.now(UTC),
            )
        except (store.TesterRefused, store.TesterNotFound) as error:
            raise refused(error) from None
        return await answer(request, auth, tester_id, await give(auth, tester_id, person_id))

    @admin.post("/{tester_id}/email")
    async def email(
        tester_id: UUID,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        await admit(request, response, auth, write=True)
        person_id, _ = await acting(auth)
        try:
            await store.request_welcome(
                auth.database, tester_id, actor_person_id=person_id, now=datetime.now(UTC)
            )
        except (store.TesterRefused, store.TesterNotFound) as error:
            raise refused(error) from None
        return await answer(request, auth, tester_id, await give(auth, tester_id, person_id))

    @admin.post("/{tester_id}/hours")
    async def tester_hours(
        tester_id: UUID,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        await admit(request, response, auth, write=True)
        person_id, _ = await acting(auth)
        try:
            standing = await store.standing_for(auth.database, tester_id)
        except store.TesterNotFound as error:
            raise refused(error) from None
        if standing.decision == "declined":
            raise HTTPException(422, "They were declined. Approve them first.")
        if standing.decision != "approved" and standing.listed_at is None:
            raise HTTPException(422, "Approve them first.")
        return await answer(request, auth, tester_id, await give(auth, tester_id, person_id))

    app.include_router(admin)


__all__ = ["install_testers_http"]
