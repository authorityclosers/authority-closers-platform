"""Bug reports over HTTP (owner, 23 Oct 2026: "bug catcher for everyone").

- POST /v1/bug-reports                     any signed-in person on Sales X-Ray: their words,
                                           the screen, app and device, recent client errors,
                                           an optional picture of the screen and voice note
- GET  /v1/bug-reports/mine                that person's own recent reports and where each
                                           stands, so the app can say when one is fixed
- GET  /v1/admin/bugs                      the team's list: filters for status, severity,
                                           area and organisation, counts per status
- GET  /v1/admin/bugs/{id}                 one report with everything captured and its history
- GET  /v1/admin/bugs/{id}/screenshot      its picture (same origin, private)
- GET  /v1/admin/bugs/{id}/voice           its voice note (same origin, private)
- POST /v1/admin/bugs/{id}/events          change status, severity or area, or add a note

Everything the device sends is scrubbed again here (scrub.py). Admin routes follow the
other Admin areas: Admin host, the AC operations workspace, a Sales X-Ray control account;
each change is audited in the operations chain.
"""

from __future__ import annotations

import base64
import binascii
import re
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from ac_platform.audit.service import AuditRepository
from ac_platform.bug_reports.models import AREAS, SEVERITIES, STATUSES
from ac_platform.bug_reports.screenshots import (
    ScreenshotError,
    ScreenshotStore,
    check_voice,
    clean_screenshot,
)
from ac_platform.bug_reports.scrub import area_for, clean_context, clean_errors, scrub_route
from ac_platform.bug_reports.store import (
    BugReportNotFound,
    BugReportRefused,
    BugReportStore,
    NewReport,
)
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
from ac_platform.http.rate_limits import InMemoryTokenBucketLimiter, RateLimitRule
from ac_platform.http.routes import RouteContext
from ac_platform.kernel.errors import DomainError

PRIVATE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}
MAX_BODY_BYTES = 6 * 1024 * 1024
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_LIST_QUERY = frozenset({"status", "severity", "area", "organisation", "offset"})


class Screenshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_type: Literal["image/png", "image/jpeg", "image/webp"]
    data: str = Field(min_length=8, max_length=5_600_000)
    source: Literal["auto", "upload"]


class Voice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_type: Literal["audio/webm", "audio/ogg", "audio/mp4"]
    data: str = Field(min_length=8, max_length=2_100_000)
    seconds: int = Field(ge=1, le=120)


class NewBugReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    words: str = Field(min_length=1, max_length=4000)
    blocks_work: bool = False
    route: str = Field(min_length=1, max_length=2048)
    area: str | None = Field(default=None, max_length=32)
    context: dict[str, Any] = Field(default_factory=dict)
    client_errors: list[Any] = Field(default_factory=list, max_length=50)
    screenshot: Screenshot | None = None
    voice: Voice | None = None


class BugChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["new", "triaged", "in_progress", "fixed", "verified", "closed"] | None = None
    severity: Literal["blocker", "high", "medium", "low"] | None = None
    area: str | None = Field(default=None, max_length=32)
    note: str | None = Field(default=None, max_length=2000)


def _words(value: str) -> str:
    return _CONTROL.sub("", value).strip()[:4000]


def install_bug_reports_http(app: FastAPI, ctx: RouteContext) -> None:
    settings = ctx.settings
    dependency = Depends(ctx.require_actor, scope="function")
    read_dependency = Depends(
        getattr(ctx.require_actor, "read_only", ctx.require_actor), scope="function"
    )
    pictures = ScreenshotStore(settings.sales_xray_storage_root)
    limiter = InMemoryTokenBucketLimiter()
    per_person = RateLimitRule("bug-report", "POST", re.compile(".*"), 12, 3600)

    # ---------- Sales X-Ray: send a report ----------

    reports = APIRouter(prefix="/v1/bug-reports", tags=["bug-reports"])

    def on_app_host(request: Request) -> None:
        hosts = {settings.public_app_url.host}
        if settings.sales_xray_app_url is not None:
            hosts.add(settings.sales_xray_app_url.host)
        if request.url.hostname not in hosts or request.query_params:
            raise HTTPException(404, "Not found.", headers=PRIVATE)

    @reports.post("", status_code=201)
    async def send(
        command: NewBugReport,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        response.headers.update(PRIVATE)
        on_app_host(request)
        try:
            require_safe_origin(request, settings)
        except DomainError:
            raise HTTPException(403, "Send this from the app.", headers=PRIVATE) from None
        actor = auth.resolved.actor
        store = BugReportStore(auth.database)
        earlier = await store.find_command(actor.person_id, command.command_id)
        if earlier is not None:
            response.status_code = 200
            return {
                "bug_id": str(earlier.id),
                "screenshot": "kept" if earlier.screenshot_key else "none",
                "voice": "kept" if await store.voice_kept(earlier.id) else "none",
            }
        words = _words(command.words)
        if not words:
            raise HTTPException(422, "Say what went wrong.", headers=PRIVATE)
        allowed, retry, _remaining = await limiter.consume(str(actor.person_id), per_person)
        if not allowed:
            raise HTTPException(
                429,
                "That's a lot of reports in an hour. Send again a little later.",
                headers={**PRIVATE, "Retry-After": str(retry)},
            )
        route = scrub_route(command.route)
        context = clean_context(command.context)
        context["server"] = {
            "environment": settings.environment,
            "release": settings.release_id[:40],
        }
        if auth.resolved.membership_role:
            context["workspace"] = {"role": str(auth.resolved.membership_role)[:32]}
        bug_id = uuid4()
        now = datetime.now(UTC)
        picture: dict[str, Any] | None = None
        kept = "none"
        if command.screenshot is not None:
            kept = "skipped"
            try:
                raw = base64.b64decode(command.screenshot.data, validate=True)
                if not pictures.available:
                    raise ScreenshotError("Pictures are not kept here.")
                clean = await run_in_threadpool(
                    clean_screenshot, raw, command.screenshot.content_type
                )
                key = await run_in_threadpool(pictures.put, bug_id, clean)
            except (ScreenshotError, binascii.Error, ValueError):
                picture = None
            else:
                picture = {
                    "screenshot_key": key,
                    "screenshot_type": clean.content_type,
                    "screenshot_bytes": len(clean.data),
                    "screenshot_sha256": clean.sha256,
                    "screenshot_source": command.screenshot.source,
                }
                kept = "kept"
        voice: dict[str, Any] | None = None
        spoken = "none"
        if command.voice is not None:
            spoken = "skipped"
            try:
                raw = base64.b64decode(command.voice.data, validate=True)
                if not pictures.available:
                    raise ScreenshotError("Voice notes are not kept here.")
                note = check_voice(raw, command.voice.content_type, command.voice.seconds)
                key = await run_in_threadpool(pictures.put_voice, bug_id, note)
            except (ScreenshotError, binascii.Error, ValueError):
                voice = None
            else:
                voice = {
                    "storage_key": key,
                    "content_type": note.content_type,
                    "bytes": len(note.data),
                    "sha256": note.sha256,
                    "seconds": note.seconds,
                }
                spoken = "kept"
        await store.create(
            NewReport(
                person_id=actor.person_id,
                tenant_id=actor.tenant_id,
                command_id=command.command_id,
                words=words,
                blocks_work=command.blocks_work,
                area=area_for(route, command.area),
                route=route,
                context=context,
                client_errors=clean_errors(command.client_errors),
                user_agent=(request.headers.get("user-agent") or "")[:512],
            ),
            bug_id=bug_id,
            now=now,
            screenshot=picture,
            voice=voice,
        )
        return {"bug_id": str(bug_id), "screenshot": kept, "voice": spoken}

    @reports.get("/mine")
    async def mine(
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = read_dependency,
    ) -> dict[str, Any]:
        response.headers.update(PRIVATE)
        on_app_host(request)
        items = await BugReportStore(auth.database).mine(auth.resolved.actor.person_id)
        return {"items": items}

    app.include_router(reports)

    # ---------- Admin: the team's list ----------

    admin = APIRouter(prefix="/v1/admin/bugs", tags=["bug-reports-admin"])

    async def admit(
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction,
        *,
        write: bool,
        query: frozenset[str] = frozenset(),
    ) -> Any:
        require_admin_surface(request, settings)
        response.headers.update(PRIVATE)
        if write:
            try:
                require_safe_origin(request, settings)
            except DomainError:
                raise HTTPException(403, "Use this Admin page to continue.") from None
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
        return actor

    @admin.get("")
    async def listing(
        request: Request,
        response: Response,
        status: str | None = None,
        severity: str | None = None,
        area: str | None = None,
        organisation: UUID | None = None,
        offset: int = 0,
        auth: AuthenticatedTransaction = read_dependency,
    ) -> dict[str, Any]:
        await admit(request, response, auth, write=False, query=_LIST_QUERY)
        if status is not None and status not in (*STATUSES, "open"):
            raise HTTPException(422, "Choose a status from the list.")
        if severity is not None and severity not in (*SEVERITIES, "none"):
            raise HTTPException(422, "Choose a severity from the list.")
        if area is not None and area not in AREAS:
            raise HTTPException(422, "Choose an area from the list.")
        if not 0 <= offset <= 100_000:
            raise HTTPException(422, "That page is out of range.")
        return await BugReportStore(auth.database).page(
            status=status,
            severity=severity,
            area=area,
            organisation=organisation,
            offset=offset,
        )

    @admin.get("/{bug_id}")
    async def one(
        bug_id: UUID,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = read_dependency,
    ) -> dict[str, Any]:
        await admit(request, response, auth, write=False)
        try:
            return await BugReportStore(auth.database).detail(bug_id)
        except BugReportNotFound:
            raise HTTPException(404, "That report is not here.") from None

    @admin.get("/{bug_id}/voice")
    async def voice_note(
        bug_id: UUID,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = read_dependency,
    ) -> Response:
        await admit(request, response, auth, write=False)
        try:
            key, digest, content_type = await BugReportStore(auth.database).voice(bug_id)
            data = await run_in_threadpool(pictures.read, key, expected_sha256=digest)
        except (BugReportNotFound, ScreenshotError):
            raise HTTPException(404, "That voice note is not here.") from None
        return Response(
            content=data,
            media_type=content_type,
            headers={
                **PRIVATE,
                "X-Content-Type-Options": "nosniff",
                "Cross-Origin-Resource-Policy": "same-origin",
            },
        )

    @admin.get("/{bug_id}/screenshot")
    async def picture(
        bug_id: UUID,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = read_dependency,
    ) -> Response:
        await admit(request, response, auth, write=False)
        try:
            key, digest, content_type = await BugReportStore(auth.database).screenshot(bug_id)
            data = await run_in_threadpool(pictures.read, key, expected_sha256=digest)
        except (BugReportNotFound, ScreenshotError):
            raise HTTPException(404, "That picture is not here.") from None
        return Response(
            content=data,
            media_type=content_type,
            headers={
                **PRIVATE,
                "X-Content-Type-Options": "nosniff",
                "Cross-Origin-Resource-Policy": "same-origin",
            },
        )

    @admin.post("/{bug_id}/events")
    async def change(
        bug_id: UUID,
        command: BugChange,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        actor = await admit(request, response, auth, write=True)
        if command.area is not None and command.area not in AREAS:
            raise HTTPException(422, "Choose an area from the list.")
        store = BugReportStore(auth.database)
        try:
            before = await store.state(bug_id)
            added = await store.change(
                bug_id,
                actor_person_id=actor.person_id,
                now=datetime.now(UTC),
                status=command.status,
                severity=command.severity,
                area=command.area,
                note=command.note,
            )
        except BugReportNotFound:
            raise HTTPException(404, "That report is not here.") from None
        except BugReportRefused as error:
            raise HTTPException(422, str(error)) from None
        if added:
            await AuditRepository(auth.database).append_for_actor(
                actor,
                action="bug_report.changed",
                resource_type="bug_report",
                resource_id=str(bug_id),
                payload={
                    "changed": added,
                    "status": [before["status"], command.status or before["status"]],
                    "severity": [before["severity"], command.severity or before["severity"]],
                    "area": [before["area"], command.area or before["area"]],
                    "note": bool(command.note),
                },
            )
        return await store.detail(bug_id)

    app.include_router(admin)
