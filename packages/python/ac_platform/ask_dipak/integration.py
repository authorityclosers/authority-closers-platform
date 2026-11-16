"""Ask Dipak for API keys, connected apps and the MCP server (owner via the orchestrator, 14 Nov
2026: "so Claude can drive it"). Everything goes through the integrations ``Reader``, so a key's
scopes, its plan, its rate limits and its person's role apply exactly as they do to calls.

Scopes (the orchestrator, 14 Nov 2026, mirroring the call scopes; no plan or price changes):

- none: Dipak's lessons, search and "how to improve" (his content, the same for everyone);
- ``coaching:read``: my missions and their counts, my latest calls from leads, and, for an
  organisation key or a person whose role sees the team, every seller's counts;
- ``coaching:write`` (a person's connected app only): save lessons, tick missions, keep up to
  three active, answer the after-call question. Missions are a person's own, so an
  organisation's API key never writes them.

API routes (``/v1/api/ask-dipak/...``) and MCP tools (``ask_dipak_*``) answer the same JSON.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ac_platform.ask_dipak import catalogue, coaching, how_to_improve, store, team
from ac_platform.http.routes import RouteContext
from ac_platform.integrations.api_http import ApiError, Reader, make_opener

READ = "coaching:read"
WRITE = "coaching:write"
QUESTION = r"^([A-Z]{2}[0-9]{2}|NEW-[0-9]{3})$"
PRIVATE = {"Cache-Control": "private, no-store"}

_READS = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}
_WRITES = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}
_QUESTION = {"type": "string", "pattern": QUESTION, "description": "A question ID, e.g. PB03."}
_KEYS = {"type": "array", "items": {"type": "string", "maxLength": 40}, "maxItems": 16}


class CallAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str = Field(pattern=QUESTION)
    done: bool


class CallAnswers(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answers: list[CallAnswer] = Field(min_length=1, max_length=coaching.MAX_ACTIVE * 2)


class Switch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    on: bool


TOOLS: tuple[dict[str, Any], ...] = (
    {
        "name": "ask_dipak_search",
        "title": "Search Dipak's sales questions",
        "description": (
            "Ask Dipak's library: 150 sales questions in 10 categories, found by keywords "
            "(titles, categories, IDs and common words such as 'mahanga'). No AI: an empty "
            "query gives six suggestions. Open one with ask_dipak_lesson."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string", "maxLength": 200}},
        },
        "annotations": _READS,
        "scope": None,
    },
    {
        "name": "ask_dipak_lesson",
        "title": "Read one of Dipak's lessons",
        "description": (
            "A question and, when Dipak has written it, its lesson in his words: quick "
            "answer, scenario with three options and his word on each, deep lesson, the line "
            "to remember, the Next-call mission and what to learn next. lesson is null for a "
            "question whose lesson isn't ready; never write one in Dipak's name."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"question_id": _QUESTION},
            "required": ["question_id"],
        },
        "annotations": _READS,
        "scope": None,
    },
    {
        "name": "ask_dipak_how_to_improve",
        "title": "Dipak's questions for a report's weaknesses",
        "description": (
            "Up to 4 of Dipak's questions for what a call report says to improve: skills "
            "(report dimension_id with call_state needs_attention) and objection kinds "
            "(call_map.objections[].kind). A fixed table Dipak reviews, not AI."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"skills": _KEYS, "objections": _KEYS},
        },
        "annotations": _READS,
        "scope": None,
    },
    {
        "name": "ask_dipak_my_missions",
        "title": "My Next-call missions and their counts",
        "description": (
            "This person's ticked Next-call missions, the (up to 3) active ones, and for "
            "each the calls they said they did it on, and didn't. Their own answers, never "
            "a score."
        ),
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": _READS,
        "scope": READ,
    },
    {
        "name": "ask_dipak_recent_calls",
        "title": "My latest calls, for the after-call question",
        "description": (
            "This person's latest calls from leads, newest first, each with the active "
            "missions still waiting for a yes or no. Answer with ask_dipak_answer_call."
        ),
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": _READS,
        "scope": READ,
    },
    {
        "name": "ask_dipak_team_missions",
        "title": "The team's Next-call missions and counts",
        "description": (
            "For each seller in this organisation, their active and ticked missions and the "
            "calls they said they did each on. Organisation keys and owners, admins, "
            "managers and viewers only."
        ),
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": _READS,
        "scope": READ,
    },
    {
        "name": "ask_dipak_save_lesson",
        "title": "Save or unsave a lesson",
        "description": "Keeps a question in this person's Saved lessons, or takes it out.",
        "inputSchema": {
            "type": "object",
            "properties": {"question_id": _QUESTION, "saved": {"type": "boolean"}},
            "required": ["question_id", "saved"],
        },
        "annotations": _WRITES,
        "scope": WRITE,
    },
    {
        "name": "ask_dipak_tick_mission",
        "title": "Tick or untick a Next-call mission",
        "description": (
            "Ticks a lesson's Next-call mission, which keeps it in this person's missions, or "
            "unticks it (which also drops it from the active ones). Every question with one "
            "of Dipak's lessons has one."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"question_id": _QUESTION, "ticked": {"type": "boolean"}},
            "required": ["question_id", "ticked"],
        },
        "annotations": _WRITES,
        "scope": WRITE,
    },
    {
        "name": "ask_dipak_set_active",
        "title": "Make a mission active, or drop it",
        "description": (
            "Makes a ticked mission one of the person's active missions (at most 3; the "
            "after-call question asks about these), or drops it."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"question_id": _QUESTION, "active": {"type": "boolean"}},
            "required": ["question_id", "active"],
        },
        "annotations": _WRITES,
        "scope": WRITE,
    },
    {
        "name": "ask_dipak_answer_call",
        "title": "Answer the after-call question",
        "description": (
            "Records, for one of the person's calls (its call_id from "
            "ask_dipak_recent_calls), whether they did each active mission. Answering again "
            "replaces the answer that stands; history is kept."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "call_id": {"type": "string", "description": "A call_id from recent calls."},
                "answers": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": coaching.MAX_ACTIVE * 2,
                    "items": {
                        "type": "object",
                        "properties": {"question_id": _QUESTION, "done": {"type": "boolean"}},
                        "required": ["question_id", "done"],
                    },
                },
            },
            "required": ["call_id", "answers"],
        },
        "annotations": _WRITES,
        "scope": WRITE,
    },
)
NAMES = frozenset(tool["name"] for tool in TOOLS)


# ---------- What each tool and route does ----------


def _person(reader: Reader) -> UUID:
    if reader.caller.reach != "person":
        raise ApiError(
            403,
            "person_only",
            "Missions are a person's own: connect as yourself, not with an organisation key.",
        )
    return reader.key.acting_person_id


def _refused(error: Exception) -> ApiError:
    if isinstance(error, store.UnknownQuestion):
        return ApiError(404, "question_missing", "No such question.")
    if isinstance(error, store.NoMission):
        return ApiError(422, "no_mission", "This question has no Next-call mission yet.")
    if isinstance(error, coaching.NotTicked):
        return ApiError(422, "not_ticked", "Tick this lesson's Next-call mission first.")
    if isinstance(error, coaching.TooManyActive):
        return ApiError(
            409, "too_many_active", f"{coaching.MAX_ACTIVE} missions are already active."
        )
    if isinstance(error, coaching.NotAsked):
        return ApiError(422, "not_asked", "That mission isn't active for this call.")
    raise error


def search(query: str) -> dict[str, Any]:
    return {"questions": [item.public() for item in catalogue.search(query[:200])]}


def lesson(question_id: str) -> dict[str, Any]:
    found = catalogue.question(question_id)
    if found is None:
        raise ApiError(404, "question_missing", "No such question.")
    return {"question": found.public(), "lesson": catalogue.lesson(question_id)}


def improve(skills: list[str], objections: list[str]) -> dict[str, Any]:
    return {
        "skills": skills,
        "objections": objections,
        "questions": how_to_improve.questions_for(skills, objections),
    }


async def my_missions(reader: Reader) -> dict[str, Any]:
    reader.require(READ)
    return await coaching.my_growth(reader.session, person_id=_person(reader))


async def recent_calls(reader: Reader) -> dict[str, Any]:
    reader.require(READ)
    person = _person(reader)
    return {
        "calls": await coaching.recent_calls(
            reader.session, person_id=person, tenant_id=reader.key.tenant_id
        )
    }


async def team_missions(reader: Reader) -> dict[str, Any]:
    reader.require(READ)
    if reader.caller.personal_workspace or not reader.caller.sees_team:
        raise ApiError(
            403, "team_only", "Only organisation keys and roles that see the team read this."
        )
    return await team.workspace_counts(reader.session, tenant_id=reader.key.tenant_id)


async def save_lesson(reader: Reader, question_id: str, saved: bool) -> dict[str, Any]:
    reader.require(WRITE)
    try:
        answer = await store.set_item(
            reader.session,
            person_id=_person(reader),
            tenant_id=reader.key.tenant_id,
            question_id=question_id,
            item="saved",
            on=saved,
            now=datetime.now(UTC),
        )
    except (store.UnknownQuestion, ValueError) as error:
        raise _refused(error) from None
    return answer.public()


async def tick_mission(reader: Reader, question_id: str, ticked: bool) -> dict[str, Any]:
    reader.require(WRITE)
    person = _person(reader)
    try:
        await store.set_item(
            reader.session,
            person_id=person,
            tenant_id=reader.key.tenant_id,
            question_id=question_id,
            item="mission",
            on=ticked,
            now=datetime.now(UTC),
        )
    except (store.UnknownQuestion, ValueError) as error:
        raise _refused(error) from None
    return await coaching.my_growth(reader.session, person_id=person)


async def set_active(reader: Reader, question_id: str, active: bool) -> dict[str, Any]:
    reader.require(WRITE)
    person = _person(reader)
    try:
        await coaching.set_active(
            reader.session,
            person_id=person,
            tenant_id=reader.key.tenant_id,
            question_id=question_id,
            on=active,
            now=datetime.now(UTC),
        )
    except (store.UnknownQuestion, ValueError) as error:
        raise _refused(error) from None
    return await coaching.my_growth(reader.session, person_id=person)


async def _call(reader: Reader, call_id: str) -> coaching.CallRef:
    person = _person(reader)
    try:
        ident = UUID(str(call_id))
    except ValueError:
        raise ApiError(422, "argument", "call_id must be a call_id from recent calls.") from None
    call = await coaching.resolve_call(
        reader.session, person_id=person, tenant_id=reader.key.tenant_id, call_id=ident
    )
    if call is None:
        raise ApiError(404, "call_missing", "No such call of yours here.")
    return call


async def call_check(reader: Reader, call_id: str) -> dict[str, Any]:
    reader.require(READ)
    call = await _call(reader, call_id)
    return await coaching.call_check(reader.session, person_id=_person(reader), call=call)


async def answer_call(reader: Reader, call_id: str, body: CallAnswers) -> dict[str, Any]:
    reader.require(WRITE)
    call = await _call(reader, call_id)
    try:
        return await coaching.record_answers(
            reader.session,
            person_id=_person(reader),
            call=call,
            answers=[(item.question_id, item.done) for item in body.answers],
            now=datetime.now(UTC),
        )
    except (store.UnknownQuestion, ValueError) as error:
        raise _refused(error) from None


# ---------- MCP ----------


def _text(args: dict[str, Any], name: str, *, required: bool = True) -> str:
    value = args.get(name)
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise ApiError(422, "argument", f"{name} must be text.")
    return value


def _flag(args: dict[str, Any], name: str) -> bool:
    value = args.get(name)
    if not isinstance(value, bool):
        raise ApiError(422, "argument", f"{name} must be true or false.")
    return value


def _keys(args: dict[str, Any], name: str) -> list[str]:
    value = args.get(name) or []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ApiError(422, "argument", f"{name} must be a list of keys.")
    return value[:16]


async def run_tool(reader: Reader, name: str, args: dict[str, Any]) -> Any:
    if name == "ask_dipak_search":
        return search(_text(args, "query", required=False))
    if name == "ask_dipak_lesson":
        return lesson(_text(args, "question_id"))
    if name == "ask_dipak_how_to_improve":
        return improve(_keys(args, "skills"), _keys(args, "objections"))
    if name == "ask_dipak_my_missions":
        return await my_missions(reader)
    if name == "ask_dipak_recent_calls":
        return await recent_calls(reader)
    if name == "ask_dipak_team_missions":
        return await team_missions(reader)
    if name == "ask_dipak_save_lesson":
        return await save_lesson(reader, _text(args, "question_id"), _flag(args, "saved"))
    if name == "ask_dipak_tick_mission":
        return await tick_mission(reader, _text(args, "question_id"), _flag(args, "ticked"))
    if name == "ask_dipak_set_active":
        return await set_active(reader, _text(args, "question_id"), _flag(args, "active"))
    if name == "ask_dipak_answer_call":
        try:
            body = CallAnswers(answers=args.get("answers"))
        except ValueError:
            raise ApiError(
                422, "argument", "answers must be a list of {question_id, done}."
            ) from None
        return await answer_call(reader, _text(args, "call_id"), body)
    raise KeyError(name)


# ---------- API routes ----------


def _split(text: str) -> list[str]:
    return [key for key in text.split(",") if key][:16]


def install_ask_dipak_api(app: FastAPI, ctx: RouteContext) -> None:
    router = APIRouter(prefix="/v1/api/ask-dipak", tags=["sales-xray-api"])
    open_reader = make_opener(ctx)

    def done(body: dict[str, Any]) -> JSONResponse:
        return JSONResponse(body, headers=PRIVATE)

    @router.get("/lessons")
    async def lessons_route(request: Request, q: str = Query("", max_length=200)) -> JSONResponse:
        async with open_reader(request):
            return done(search(q))

    @router.get("/lessons/{question_id}")
    async def lesson_route(question_id: str, request: Request) -> JSONResponse:
        async with open_reader(request):
            return done(lesson(question_id))

    @router.get("/how-to-improve")
    async def improve_route(
        request: Request,
        skills: str = Query("", max_length=400),
        objections: str = Query("", max_length=400),
    ) -> JSONResponse:
        async with open_reader(request):
            return done(improve(_split(skills), _split(objections)))

    @router.get("/missions")
    async def missions_route(request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            return done(await my_missions(reader))

    @router.get("/team")
    async def team_route(request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            return done(await team_missions(reader))

    @router.get("/calls")
    async def calls_route(request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            return done(await recent_calls(reader))

    @router.get("/calls/{call_id}/check")
    async def check_route(call_id: str, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            return done(await call_check(reader, call_id))

    @router.put("/calls/{call_id}/check")
    async def answer_route(call_id: str, body: CallAnswers, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            return done(await answer_call(reader, call_id, body))

    @router.put("/saved/{question_id}")
    async def save_route(question_id: str, body: Switch, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            return done(await save_lesson(reader, question_id, body.on))

    @router.put("/ticked/{question_id}")
    async def tick_route(question_id: str, body: Switch, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            return done(await tick_mission(reader, question_id, body.on))

    @router.put("/active/{question_id}")
    async def active_route(question_id: str, body: Switch, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            return done(await set_active(reader, question_id, body.on))

    app.include_router(router)


__all__ = ["NAMES", "READ", "TOOLS", "WRITE", "install_ask_dipak_api", "run_tool"]
