"""Call reports for API keys, connected apps, MCP and the CLI (API, MCP and CLI gaps, 15 Nov
2026, gap 5; the orchestrator gave it to the Ask Dipak lane). The report a person reads in the
app, its transcript, its Word file and the list of reports, behind ``reports:read`` (no new
scope), through the integrations ``Reader``: a key's plan and rate limits apply as they do to
a call's facts.

Who opens which report is the app's rule (``GuestOwnership.organisation_call_reader``): a
person opens their own calls' reports, and an owner or admin also their organisation's; an
organisation key opens its organisation's. Managers and viewers see the team's calls in the
call list but open only their own reports, as in the app.

A key has no browser session, and the app's own read re-admits the signed-in session, so it
cannot be used here. Instead the call is found through the library query the call list uses
(deleted, revoked and expired calls are not in it), its recording is locked for share as the
app's read locks it (erasure and revocation wait), and the app's post-authorization projection
shows it: the same report and transcript, sensitive parts withheld, and never the previous
call's context.

``saved`` is the app's Saved reports (Reports V4) of the person the key acts as: the person
for a connected app, and for an organisation key the person who made it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import false, func, select, tuple_

from ac_platform.http.routes import RouteContext
from ac_platform.integrations.api_http import PAGE, ApiError, Reader, _label, make_opener
from ac_platform.kernel.authz import ActorContext

READ = "reports:read"
SCHEMA = "sales-xray.api-report/1"
PRIVATE = {"Cache-Control": "no-store"}
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
# The roles whose app read reaches the organisation's reports (organisation_call_reader).
TEAM_ROLES = frozenset({"owner", "admin"})
# Reads only: the acquisition policy revision is never used to admit an upload here.
POLICY = "integrations-report-read"
_NIL = UUID(int=0)
_READS = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}
_CALL = {"type": "string", "description": "A call id from list_calls or list_reports."}

TOOLS: tuple[dict[str, Any], ...] = (
    {
        "name": "list_reports",
        "title": "List call reports",
        "description": (
            "Calls whose report is ready, newest first, 50 a page: id, title, date, length and "
            "whether the person saved it in Sales X-Ray. saved true lists only Saved reports. "
            "Pass next_before for the next page; read one with get_report."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "saved": {"type": "boolean", "description": "true for Saved reports only."},
                "before": {"type": "string", "description": "next_before from a page."},
            },
        },
        "annotations": _READS,
        "scope": READ,
    },
    {
        "name": "get_report",
        "title": "Read a call's report",
        "description": (
            "The report Sales X-Ray wrote for one call, as the app shows it: summary, verdict, "
            "strengths, what to improve and the next action, missed opportunities, objections, "
            "closing and each skill's state. Sensitive parts are withheld. Not an official "
            "score."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"call_id": _CALL},
            "required": ["call_id"],
        },
        "annotations": _READS,
        "scope": READ,
    },
    {
        "name": "get_transcript",
        "title": "Read a call's transcript",
        "description": (
            "The transcript of one call with a ready report, segment by segment with start and "
            "end times in milliseconds. Sensitive parts are withheld."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"call_id": _CALL},
            "required": ["call_id"],
        },
        "annotations": _READS,
        "scope": READ,
    },
)
NAMES = frozenset(tool["name"] for tool in TOOLS)


# ---------- Who reads what ----------


def _team(reader: Reader) -> bool:
    """An organisation key, or a person whose role reads the organisation's reports."""
    caller = reader.caller
    return caller.reach == "organisation" or (
        not caller.personal_workspace and caller.role in TEAM_ROLES
    )


def _scope(reader: Reader, now: datetime, *, team: bool | None = None) -> tuple[Any, Any]:
    """The calls this caller may open a report of, and the report-ready column. ``team``
    False keeps it to the caller's own calls whatever their role (Coaching's rule)."""
    from ac_platform.conversation_intelligence.acquisition_library import (
        _account_library_query,
        _report_columns,
    )

    person = _NIL if reader.caller.reach == "organisation" else reader.key.acting_person_id
    actor = ActorContext(person_id=person, session_id=_NIL, tenant_id=reader.key.tenant_id)
    has_report, _ = _report_columns()
    every = _team(reader) if team is None else team
    return _account_library_query(actor, now, every_owner=every), has_report


def _saved(reader: Reader) -> Any:
    """Whether the person the key acts as has the call in their Saved reports now."""
    from ac_platform.conversation_intelligence.acquisition_models import (
        ConversationAcquisitionUsage as Usage,
    )
    from ac_platform.conversation_intelligence.report_save_models import (
        ConversationReportSave as Save,
    )

    latest = (
        select(Save.saved)
        .where(
            Save.tenant_id == Usage.tenant_id,
            Save.person_id == reader.key.acting_person_id,
            Save.submission_id == Usage.submission_id,
        )
        .order_by(Save.revision.desc())
        .limit(1)
        .correlate(Usage)
        .scalar_subquery()
    )
    return func.coalesce(latest, false())


def _call(reader: Reader, usage: Any, title: str | None) -> dict[str, Any]:
    call_id = str(usage.submission_id)
    return {
        "id": call_id,
        "title": title,
        "created_at": usage.created_at.isoformat(),
        "duration_seconds": usage.reserved_seconds,
        "open_url": f"{reader.base}/analysis/calls/{call_id}" if reader.base else None,
    }


async def _recording(
    reader: Reader, call_id: UUID, *, team: bool | None = None
) -> tuple[Any, Any, str | None]:
    """The call, its recording (locked for share) and its title, or 404."""
    from ac_platform.conversation_intelligence.acquisition_models import (
        ConversationAcquisitionUsage as Usage,
    )
    from ac_platform.conversation_intelligence.models import ConversationRecording as Recording

    library, _ = _scope(reader, datetime.now(UTC), team=team)
    row = (
        await reader.session.execute(
            library.add_columns(Recording, _label())
            .where(Usage.submission_id == call_id)
            .with_for_update(read=True, of=Recording)
            .execution_options(populate_existing=True)
        )
    ).first()
    if row is None:
        raise ApiError(404, "call_missing", "That call is not here, or not yours to read.")
    return row[0], row[1], row[2]


async def _recordings(reader: Reader, call_ids: list[UUID], *, team: bool) -> dict[UUID, Any]:
    """Many calls' recordings at once, locked for share, keyed by call; calls outside this
    caller's reach are simply not in it."""
    from ac_platform.conversation_intelligence.acquisition_models import (
        ConversationAcquisitionUsage as Usage,
    )
    from ac_platform.conversation_intelligence.models import ConversationRecording as Recording

    if not call_ids:
        return {}
    library, _ = _scope(reader, datetime.now(UTC), team=team)
    rows = (
        await reader.session.execute(
            library.add_columns(Recording)
            .where(Usage.submission_id.in_(call_ids))
            .with_for_update(read=True, of=Recording)
            .execution_options(populate_existing=True)
        )
    ).all()
    return {usage.submission_id: recording for usage, recording in rows}


def _ownership(reader: Reader) -> Any:
    from ac_platform.conversation_intelligence.acquisition_sessions import AcquisitionSessions
    from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership

    return GuestOwnership(
        AcquisitionSessions(reader.session, tenant_id=reader.key.tenant_id, policy_revision=POLICY)
    )


def _reports(reader: Reader) -> Any:
    from ac_platform.conversation_intelligence.acquisition_reports import AcquisitionReports

    return AcquisitionReports(_ownership(reader))


def _refused(error: Any) -> ApiError:
    if error.status == 404:
        return ApiError(404, "report_not_ready", "This call's report is not ready yet.")
    return ApiError(409, "report_unavailable", "This call's report can't be shown right now.")


async def _envelope(reader: Reader, call_id: UUID) -> tuple[dict[str, Any], dict[str, Any]]:
    from ac_platform.conversation_intelligence.application import ConversationError
    from ac_platform.conversation_intelligence.report_access import ReportAccess

    usage, recording, title = await _recording(reader, call_id)
    try:
        envelope = await _reports(reader).render_report(
            recording,
            submission_id=call_id,
            access=ReportAccess.ACCOUNT,
            previous_context=False,
        )
    except ConversationError as error:
        raise _refused(error) from None
    return _call(reader, usage, title), envelope


# ---------- What each route and tool does ----------


async def reports(
    reader: Reader, *, saved: bool = False, before: UUID | None = None
) -> dict[str, Any]:
    from ac_platform.conversation_intelligence.acquisition_models import (
        ConversationAcquisitionUsage as Usage,
    )

    reader.require(READ)
    library, has_report = _scope(reader, datetime.now(UTC))
    library = library.where(has_report)
    kept = _saved(reader)
    if saved:
        library = library.where(kept.is_(True))
    query = library.add_columns(_label(), kept)
    if before is not None:
        cursor = (
            await reader.session.execute(library.where(Usage.submission_id == before))
        ).scalar()
        if cursor is None:
            raise ApiError(404, "cursor_missing", "That report is not in this list.")
        query = query.where(
            tuple_(Usage.created_at, Usage.submission_id)
            < (cursor.created_at, cursor.submission_id)
        )
    rows = (
        await reader.session.execute(
            query.order_by(Usage.created_at.desc(), Usage.submission_id.desc()).limit(PAGE + 1)
        )
    ).all()
    items = [
        {**_call(reader, usage, title), "saved": bool(is_saved)}
        for usage, title, is_saved in rows[:PAGE]
    ]
    return {"reports": items, "next_before": items[-1]["id"] if len(rows) > PAGE else None}


async def report(reader: Reader, call_id: UUID) -> dict[str, Any]:
    reader.require(READ)
    call, envelope = await _envelope(reader, call_id)
    view = envelope["report"]
    return {
        "schema": SCHEMA,
        "call": call,
        "review_status": view.get("review_status"),
        # The app's own words on it: an AI report, never an official score.
        "official_score": False,
        "numeric_publication": bool(view.get("numeric_publication", False)),
        "transcript_revision": envelope.get("transcript_revision"),
        "report": view["content"],
    }


async def report_docx(reader: Reader, call_id: UUID) -> bytes:
    from ac_platform.conversation_intelligence.report_export import report_docx_bytes

    reader.require(READ)
    _, envelope = await _envelope(reader, call_id)
    try:
        return report_docx_bytes(envelope)
    except (KeyError, TypeError, ValueError):
        raise ApiError(
            409, "report_unavailable", "This report could not be made into a Word file."
        ) from None


async def transcript(reader: Reader, call_id: UUID) -> dict[str, Any]:
    from ac_platform.conversation_intelligence.application import ConversationError

    reader.require(READ)
    usage, recording, title = await _recording(reader, call_id)
    try:
        shown = await _reports(reader).render_transcript(recording)
    except ConversationError as error:
        raise _refused(error) from None
    return {
        "call": _call(reader, usage, title),
        "revision": shown["revision"],
        "duration_ms": shown["duration_ms"],
        "segments": shown["segments"],
    }


# ---------- MCP ----------


def _uuid(args: dict[str, Any], name: str) -> UUID:
    try:
        return UUID(str(args.get(name, "")))
    except ValueError:
        raise ApiError(422, "argument", f"{name} must be an id from a list.") from None


async def run_tool(reader: Reader, name: str, args: dict[str, Any]) -> Any:
    if name == "list_reports":
        saved = args.get("saved", False)
        if not isinstance(saved, bool):
            raise ApiError(422, "argument", "saved must be true or false.")
        before = _uuid(args, "before") if args.get("before") else None
        return await reports(reader, saved=saved, before=before)
    if name == "get_report":
        return await report(reader, _uuid(args, "call_id"))
    if name == "get_transcript":
        return await transcript(reader, _uuid(args, "call_id"))
    raise KeyError(name)


# ---------- API routes ----------


def install_reports_api(app: FastAPI, ctx: RouteContext) -> None:
    router = APIRouter(prefix="/v1/api", tags=["sales-xray-api"])
    open_reader = make_opener(ctx)

    @router.get("/reports")
    async def reports_route(
        request: Request, saved: bool = False, before: UUID | None = None
    ) -> JSONResponse:
        async with open_reader(request) as reader:
            return JSONResponse(await reports(reader, saved=saved, before=before), headers=PRIVATE)

    @router.get("/calls/{call_id}/report")
    async def report_route(call_id: UUID, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            return JSONResponse(await report(reader, call_id), headers=PRIVATE)

    @router.get("/calls/{call_id}/report.docx")
    async def report_docx_route(call_id: UUID, request: Request) -> Response:
        async with open_reader(request) as reader:
            document = await report_docx(reader, call_id)
        return Response(
            content=document,
            media_type=DOCX,
            headers={
                **PRIVATE,
                "Content-Disposition": 'attachment; filename="sales-call-report.docx"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.get("/calls/{call_id}/transcript")
    async def transcript_route(call_id: UUID, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            return JSONResponse(await transcript(reader, call_id), headers=PRIVATE)

    app.include_router(router)


__all__ = [
    "NAMES",
    "READ",
    "TOOLS",
    "install_reports_api",
    "report",
    "report_docx",
    "reports",
    "run_tool",
    "transcript",
]
