"""Coaching for API keys, connected apps, MCP and the CLI (API, MCP and CLI gaps, 15 Nov 2026,
gap 11; the orchestrator gave it to the Ask Dipak lane). The Coaching the app shows, behind
``reports:read`` (no new scope), through the integrations ``Reader``.

The app's Coaching rules stand (coaching/library.py):

- a person's own Coaching and one call's coaching are theirs alone: owners, admins and managers
  have no private-coaching bypass, and an organisation key, which is no person, has none;
- the team's Coaching (anonymous counts, and the names of reps who chose to share) is for owners
  and admins, and for an organisation key; the names come only while the person reading (for a
  key, the person who made it) is a current owner or admin (``shared_reps``).

A key has no browser session, and the app's Coaching re-admits one, so the reports are read as
``integrations/reports_api.py`` reads them: found through the library query, recordings locked
for share, then the app's post-authorization projection (never the previous call's context).
The Coaching itself is built by the app's own code: ``CoachingLibrary.read_authorized`` for a
person's Coaching, ``CallCoachingCache.read`` for one call, ``from_report`` and
``summarize_team`` for the team. Nothing here is an official score (AC-SVAL gates that).
"""

from __future__ import annotations

import functools
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func

from ac_platform.http.routes import RouteContext
from ac_platform.integrations import reports_api
from ac_platform.integrations.api_http import ApiError, Reader, make_opener
from ac_platform.kernel.authz import ActorContext

READ = "reports:read"
PRIVATE = {"Cache-Control": "no-store"}
_NIL = UUID(int=0)
_READS = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}
# A call the library query found for this person is account-owned: its full report.
_CLAIMED = SimpleNamespace(claimed_account=True)

TOOLS: tuple[dict[str, Any], ...] = (
    {
        "name": "my_coaching",
        "title": "My Coaching",
        "description": (
            "This person's Coaching from their analysed calls, as the app's Coaching tab "
            "shows it: the skills to work on, recurring focus and each call's state. Suggestions "
            "from AI reports, never a score. A person's own: not for organisation keys."
        ),
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": _READS,
        "scope": READ,
    },
    {
        "name": "call_coaching",
        "title": "Coaching for one call",
        "description": (
            "The coaching for one of this person's own calls (call_id from list_calls or "
            "list_reports): what went well, what to change and the mission for the next call."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"call_id": {"type": "string", "description": "One of your calls."}},
            "required": ["call_id"],
        },
        "annotations": _READS,
        "scope": READ,
    },
    {
        "name": "team_coaching",
        "title": "The team's Coaching",
        "description": (
            "Across the organisation's analysed calls: how often each recommendation came up, "
            "as counts (never mistakes or success rates), and the reps who chose to share their "
            "Coaching. Owners, admins and organisation keys only."
        ),
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": _READS,
        "scope": READ,
    },
)
NAMES = frozenset(tool["name"] for tool in TOOLS)


@functools.cache
def _cache() -> Any:
    """One per process, as the app keeps one (a report is parsed once per content)."""
    from ac_platform.coaching.call import CallCoachingCache

    return CallCoachingCache()


def _person(reader: Reader) -> UUID:
    if reader.caller.reach != "person":
        raise ApiError(
            403,
            "person_only",
            "Coaching is a person's own: connect as yourself, not with an organisation key.",
        )
    return reader.key.acting_person_id


def _actor(reader: Reader) -> ActorContext:
    return ActorContext(
        person_id=reader.key.acting_person_id, session_id=_NIL, tenant_id=reader.key.tenant_id
    )


def _view(view: Any) -> dict[str, Any]:
    body: dict[str, Any] = view.model_dump(mode="json", by_alias=True)
    body.pop("session_id", None)
    body.pop("sessionId", None)
    return body


async def my_coaching(reader: Reader) -> dict[str, Any]:
    from ac_platform.coaching.library import HISTORY_LIMIT, CoachingLibrary
    from ac_platform.conversation_intelligence.acquisition_library import (
        _account_library_query,
        _report_columns,
    )
    from ac_platform.conversation_intelligence.acquisition_models import (
        ConversationAcquisitionUsage as Usage,
    )

    reader.require(READ)
    _person(reader)
    actor = _actor(reader)
    has_report, state = _report_columns()
    rows = (
        await reader.session.execute(
            _account_library_query(actor, datetime.now(UTC))  # their own calls only
            .add_columns(has_report, state)
            .order_by(Usage.created_at.desc(), Usage.submission_id.desc())
            .limit(HISTORY_LIMIT + 1)
        )
    ).all()
    ready = [usage.submission_id for usage, is_ready, _ in rows[:HISTORY_LIMIT] if is_ready]
    found = await reports_api._recordings(reader, ready, team=False)
    allowed = {call: (_CLAIMED, recording) for call, recording in found.items()}
    library = CoachingLibrary(reports_api._ownership(reader))
    return _view(await library.read_authorized(actor, rows, allowed))


async def call_coaching(reader: Reader, call_id: UUID) -> dict[str, Any]:
    from ac_platform.conversation_intelligence.application import ConversationError
    from ac_platform.conversation_intelligence.report_access import ReportAccess

    reader.require(READ)
    person = _person(reader)
    usage, recording, _ = await reports_api._recording(reader, call_id, team=False)
    try:
        envelope = await reports_api._reports(reader).render_report(
            recording,
            submission_id=call_id,
            access=ReportAccess.ACCOUNT,
            previous_context=False,
        )
    except ConversationError as error:
        raise reports_api._refused(error) from None
    view = _cache().read(
        envelope,
        submission_id=call_id,
        created_at=usage.created_at,
        person_id=person,
        tenant_id=reader.key.tenant_id,
    )
    return _view(view)


async def team_coaching(reader: Reader) -> dict[str, Any]:
    from ac_platform.coaching.library import HISTORY_LIMIT
    from ac_platform.coaching.report_adapter import from_report
    from ac_platform.coaching.sharing_store import shared_reps
    from ac_platform.coaching.team import summarize_team
    from ac_platform.conversation_intelligence.acquisition_library import (
        _account_library_query,
        _report_columns,
    )
    from ac_platform.conversation_intelligence.acquisition_models import (
        ConversationAcquisitionUsage as Usage,
    )
    from ac_platform.conversation_intelligence.acquisition_models import (
        ConversationVisitorClaim as Claim,
    )
    from ac_platform.conversation_intelligence.application import ConversationError
    from ac_platform.conversation_intelligence.report_access import ReportAccess

    reader.require(READ)
    if reader.caller.personal_workspace or not reports_api._team(reader):
        raise ApiError(
            403, "team_only", "The team's Coaching is for owners, admins and organisation keys."
        )
    actor = _actor(reader)  # an organisation key reads as the person who made it
    has_report, state = _report_columns()
    rows = (
        await reader.session.execute(
            _account_library_query(actor, datetime.now(UTC), every_owner=True)
            .add_columns(func.coalesce(Usage.person_id, Claim.person_id), has_report, state)
            .order_by(Usage.created_at.desc(), Usage.submission_id.desc())
            .limit(HISTORY_LIMIT + 1)
        )
    ).all()
    ready = [usage.submission_id for usage, _, is_ready, _ in rows[:HISTORY_LIMIT] if is_ready]
    found = await reports_api._recordings(reader, ready, team=True)
    reports = reports_api._reports(reader)
    history: list[tuple[UUID, Any]] = []
    pending, unavailable = 0, 0
    # As CoachingLibrary.read_team: only anonymous counts come from other people's reports.
    for usage, owner, is_ready, plan_state in rows[:HISTORY_LIMIT]:
        if not is_ready:
            pending += int(plan_state == "active")
            unavailable += int(plan_state != "active")
            continue
        recording = found.get(usage.submission_id)
        if recording is None:
            unavailable += 1
            continue
        try:
            envelope = await reports.render_report(
                recording,
                submission_id=usage.submission_id,
                access=ReportAccess.ACCOUNT,
                previous_context=False,
            )
            call = from_report(
                envelope,
                submission_id=usage.submission_id,
                created_at=usage.created_at,
                comparison_key=f"unlinked:{usage.submission_id}",
            )
        except (ConversationError, ValueError, KeyError):
            call = None
        if call is None:
            unavailable += 1
        else:
            history.append((owner, call))
    shared = await shared_reps(reader.session, actor=actor, tenant_id=reader.key.tenant_id)
    view = summarize_team(
        tuple(history),
        person_id=actor.person_id,
        tenant_id=reader.key.tenant_id,
        pending_calls=pending,
        unavailable_calls=unavailable,
        history_limited=len(rows) > HISTORY_LIMIT,
        shared=tuple((rep.person_id, rep.name, rep.shared_at) for rep in shared),
    )
    return _view(view)


# ---------- MCP ----------


async def run_tool(reader: Reader, name: str, args: dict[str, Any]) -> Any:
    if name == "my_coaching":
        return await my_coaching(reader)
    if name == "call_coaching":
        return await call_coaching(reader, reports_api._uuid(args, "call_id"))
    if name == "team_coaching":
        return await team_coaching(reader)
    raise KeyError(name)


# ---------- API routes ----------


def install_coaching_api(app: FastAPI, ctx: RouteContext) -> None:
    router = APIRouter(prefix="/v1/api/coaching", tags=["sales-xray-api"])
    open_reader = make_opener(ctx)

    @router.get("")
    async def mine_route(request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            return JSONResponse(await my_coaching(reader), headers=PRIVATE)

    @router.get("/team")
    async def team_route(request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            return JSONResponse(await team_coaching(reader), headers=PRIVATE)

    @router.get("/calls/{call_id}")
    async def call_route(call_id: UUID, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            return JSONResponse(await call_coaching(reader, call_id), headers=PRIVATE)

    app.include_router(router)


__all__ = [
    "NAMES",
    "READ",
    "TOOLS",
    "call_coaching",
    "install_coaching_api",
    "my_coaching",
    "run_tool",
    "team_coaching",
]
