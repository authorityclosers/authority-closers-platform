"""Ask Dipak's lessons and coaching loop over HTTP, for the signed-in person in the app (13 Nov
2026 meeting, section 5; owner via the orchestrator, 14 Nov 2026; migration 0155).

GET  /v1/sales-xray/ask-dipak/lessons?q=            search Dipak's 150 questions (keywords only)
GET  /v1/sales-xray/ask-dipak/lessons/{id}          a question and its lesson (null while none)
GET  /v1/sales-xray/ask-dipak/how-to-improve?skills=&objections=
                                                    Dipak's questions for a report's weaknesses
GET  /v1/sales-xray/ask-dipak/growth                my ticked and active missions, with counts
PUT  /v1/sales-xray/ask-dipak/focus/{id}  {active}  make a ticked mission active (max 3) or drop it
GET  /v1/sales-xray/ask-dipak/calls                 my latest calls from leads, with what each
                                                    still waits on
GET  /v1/sales-xray/ask-dipak/calls/{call}/check    the after-call question for one of my calls
PUT  /v1/sales-xray/ask-dipak/calls/{call}/check  {answers: [{question_id, done}]}
GET  /v1/sales-xray/ask-dipak/team                  per seller, per mission, the calls it was
                                                    done on (owner, admin, manager, viewer)

{call} is the lead's call event ID (right after a call from a lead) or the analysed call's ID.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Path, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ac_platform.ask_dipak import catalogue, coaching, how_to_improve, store, team
from ac_platform.http.auth import AuthenticatedTransaction, require_safe_origin
from ac_platform.http.routes import RouteContext
from ac_platform.kernel.errors import DomainError

PRIVATE = {"Cache-Control": "private, no-store"}
QUESTION = r"^([A-Z]{2}[0-9]{2}|NEW-[0-9]{3})$"
KEYS = r"^[a-z_,]{0,400}$"


class FocusChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active: bool


class MissionAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str = Field(pattern=QUESTION)
    done: bool


class CallAnswers(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answers: list[MissionAnswer] = Field(min_length=1, max_length=coaching.MAX_ACTIVE * 2)


def _keys(value: str | None) -> list[str]:
    return [key for key in (value or "").split(",") if key]


def refusal(error: Exception) -> HTTPException:
    """The coaching loop's refusals, in words the app can show."""
    if isinstance(error, store.UnknownQuestion):
        return HTTPException(404, "No such question.", headers=PRIVATE)
    if isinstance(error, store.NoMission):
        return HTTPException(422, "This question has no Next-call mission yet.", headers=PRIVATE)
    if isinstance(error, coaching.NotTicked):
        return HTTPException(422, "Tick this lesson's Next-call mission first.", headers=PRIVATE)
    if isinstance(error, coaching.TooManyActive):
        return HTTPException(
            409,
            f"{coaching.MAX_ACTIVE} missions are already active; drop one first.",
            headers=PRIVATE,
        )
    if isinstance(error, coaching.NotAsked):
        return HTTPException(
            422, "That mission isn't active, so this call wasn't asked about it.", headers=PRIVATE
        )
    raise error


def install_ask_dipak_coaching_http(app: FastAPI, ctx: RouteContext) -> None:
    settings = ctx.settings
    dependency = Depends(ctx.require_actor, scope="function")
    read_dependency = Depends(
        getattr(ctx.require_actor, "read_only", ctx.require_actor), scope="function"
    )
    router = APIRouter(prefix="/v1/sales-xray/ask-dipak", tags=["sales-xray-ask-dipak"])

    def on_app_host(request: Request, *, query: frozenset[str] = frozenset()) -> None:
        hosts = {settings.public_app_url.host}
        hosts.update(settings.sales_xray_hosts)
        if request.url.hostname not in hosts or set(request.query_params) - query:
            raise HTTPException(404, "Not found.", headers=PRIVATE)

    def writer(request: Request) -> None:
        on_app_host(request)
        try:
            require_safe_origin(request, settings)
        except DomainError:
            raise HTTPException(403, "Send this from Ask Dipak.", headers=PRIVATE) from None

    def workspace(auth: AuthenticatedTransaction) -> UUID:
        tenant_id = auth.resolved.actor.tenant_id
        if tenant_id is None:
            raise HTTPException(409, "Open a workspace first.", headers=PRIVATE)
        return tenant_id

    @router.get("/lessons")
    async def lessons(
        request: Request,
        response: Response,
        q: str = Query(default="", max_length=200),
        auth: AuthenticatedTransaction = read_dependency,
    ) -> dict[str, Any]:
        response.headers.update(PRIVATE)
        on_app_host(request, query=frozenset({"q"}))
        return {"questions": [item.public() for item in catalogue.search(q)]}

    @router.get("/lessons/{question_id}")
    async def lesson(
        request: Request,
        response: Response,
        question_id: str = Path(pattern=QUESTION, max_length=16),
        auth: AuthenticatedTransaction = read_dependency,
    ) -> dict[str, Any]:
        response.headers.update(PRIVATE)
        on_app_host(request)
        found = catalogue.question(question_id)
        if found is None:
            raise HTTPException(404, "No such question.", headers=PRIVATE)
        return {"question": found.public(), "lesson": catalogue.lesson(question_id)}

    @router.get("/how-to-improve")
    async def improve(
        request: Request,
        response: Response,
        skills: str = Query(default="", pattern=KEYS),
        objections: str = Query(default="", pattern=KEYS),
        auth: AuthenticatedTransaction = read_dependency,
    ) -> dict[str, Any]:
        response.headers.update(PRIVATE)
        on_app_host(request, query=frozenset({"skills", "objections"}))
        return {
            "skills": _keys(skills),
            "objections": _keys(objections),
            "questions": how_to_improve.questions_for(_keys(skills), _keys(objections)),
        }

    @router.get("/growth")
    async def growth(
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = read_dependency,
    ) -> dict[str, Any]:
        response.headers.update(PRIVATE)
        on_app_host(request)
        return await coaching.my_growth(auth.database, person_id=auth.resolved.actor.person_id)

    @router.put("/focus/{question_id}")
    async def focus(
        command: FocusChange,
        request: Request,
        response: Response,
        question_id: str = Path(pattern=QUESTION, max_length=16),
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        response.headers.update(PRIVATE)
        writer(request)
        actor = auth.resolved.actor
        try:
            await coaching.set_active(
                auth.database,
                person_id=actor.person_id,
                tenant_id=actor.tenant_id,
                question_id=question_id,
                on=command.active,
                now=datetime.now(UTC),
            )
        except (store.UnknownQuestion, store.NoMission, ValueError) as error:
            raise refusal(error) from None
        return await coaching.my_growth(auth.database, person_id=actor.person_id)

    @router.get("/calls")
    async def calls(
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = read_dependency,
    ) -> dict[str, Any]:
        response.headers.update(PRIVATE)
        on_app_host(request)
        actor = auth.resolved.actor
        return {
            "active": [
                coaching.mission_public(code)
                for code in await coaching.active_missions(auth.database, actor.person_id)
            ],
            "calls": await coaching.recent_calls(
                auth.database, person_id=actor.person_id, tenant_id=workspace(auth)
            ),
        }

    async def mine(auth: AuthenticatedTransaction, call_id: UUID) -> coaching.CallRef:
        call = await coaching.resolve_call(
            auth.database,
            person_id=auth.resolved.actor.person_id,
            tenant_id=workspace(auth),
            call_id=call_id,
        )
        if call is None:
            raise HTTPException(404, "No such call of yours here.", headers=PRIVATE)
        return call

    @router.get("/calls/{call_id}/check")
    async def check(
        call_id: UUID,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = read_dependency,
    ) -> dict[str, Any]:
        response.headers.update(PRIVATE)
        on_app_host(request)
        call = await mine(auth, call_id)
        return await coaching.call_check(
            auth.database, person_id=auth.resolved.actor.person_id, call=call
        )

    @router.put("/calls/{call_id}/check")
    async def answer(
        call_id: UUID,
        command: CallAnswers,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        response.headers.update(PRIVATE)
        writer(request)
        call = await mine(auth, call_id)
        try:
            return await coaching.record_answers(
                auth.database,
                person_id=auth.resolved.actor.person_id,
                call=call,
                answers=[(item.question_id, item.done) for item in command.answers],
                now=datetime.now(UTC),
            )
        except (store.UnknownQuestion, store.NoMission, ValueError) as error:
            raise refusal(error) from None

    @router.get("/team")
    async def team_read(
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = read_dependency,
    ) -> dict[str, Any]:
        response.headers.update(PRIVATE)
        on_app_host(request)
        tenant_id = workspace(auth)
        try:
            return await team.team_counts(
                auth.database, tenant_id=tenant_id, viewer_id=auth.resolved.actor.person_id
            )
        except team.NotTeamViewer:
            raise HTTPException(
                403, "Only owners, admins and managers see the team's missions.", headers=PRIVATE
            ) from None

    app.include_router(router)


__all__ = ["CallAnswers", "FocusChange", "install_ask_dipak_coaching_http", "refusal"]
