"""Feedback over HTTP (owner, 23 Oct 2026: "for each single small to small things as well as
each new update ... we take review from the user").

- POST /v1/feedback          an answer to a small prompt after a key moment: a rating from 1 to
                             3 with an optional comment, "not now", or "don't ask again". A bad
                             rating with a comment also becomes a bug report, so it reaches the
                             team's bug list and the work board.
- GET  /v1/feedback/state    what the app needs to decide whether it may ask this person now
- GET  /v1/admin/feedback    the team's trends: by moment, release and day, newest comments

Nothing here carries call content: the person's own words only, scrubbed context like bug
reports. Admin follows the other Admin areas (Admin host, operations workspace, Sales X-Ray
control account).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ac_platform.bug_reports.scrub import area_for, clean_context, scrub_route
from ac_platform.bug_reports.store import BugReportStore, NewReport
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationError,
)
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.feedback.models import MOMENTS
from ac_platform.feedback.store import RATING, FeedbackStore, NewFeedback
from ac_platform.http.auth import (
    AuthenticatedTransaction,
    require_admin_surface,
    require_safe_origin,
)
from ac_platform.http.rate_limits import InMemoryTokenBucketLimiter, RateLimitRule
from ac_platform.http.routes import RouteContext
from ac_platform.kernel.errors import DomainError

PRIVATE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SUBJECT = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_MOMENT_LABEL = {
    "report_read": "reading a call's Report",
    "call_outcome": "logging a call's outcome",
    "first_import": "the first import",
    "plan_purchase": "buying a plan",
    "chats_used": "Chats",
    "app_update": "an app update",
    "general": "the app",
}


class NewAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: UUID
    moment: str = Field(min_length=2, max_length=32)
    kind: Literal["rating", "dismissed", "opt_out"]
    rating: int | None = Field(default=None, ge=1, le=3)
    comment: str | None = Field(default=None, max_length=1000)
    subject: str | None = Field(default=None, max_length=64)
    route: str = Field(min_length=1, max_length=2048)
    context: dict[str, Any] = Field(default_factory=dict)


def install_feedback_http(app: FastAPI, ctx: RouteContext) -> None:
    settings = ctx.settings
    dependency = Depends(ctx.require_actor, scope="function")
    read_dependency = Depends(
        getattr(ctx.require_actor, "read_only", ctx.require_actor), scope="function"
    )
    limiter = InMemoryTokenBucketLimiter()
    per_person = RateLimitRule("feedback", "POST", re.compile(".*"), 30, 3600)

    def on_app_host(request: Request) -> None:
        hosts = {settings.public_app_url.host}
        if settings.sales_xray_app_url is not None:
            hosts.add(settings.sales_xray_app_url.host)
        if request.url.hostname not in hosts or request.query_params:
            raise HTTPException(404, "Not found.", headers=PRIVATE)

    router = APIRouter(prefix="/v1/feedback", tags=["feedback"])

    @router.post("", status_code=201)
    async def answer(
        command: NewAnswer,
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
        if command.moment not in MOMENTS:
            raise HTTPException(422, "That moment is not one we ask about.", headers=PRIVATE)
        if (command.kind == "rating") != (command.rating is not None):
            raise HTTPException(422, "A rating needs a choice.", headers=PRIVATE)
        comment = _CONTROL.sub("", command.comment or "").strip()[:1000] or None
        if comment and command.kind != "rating":
            raise HTTPException(422, "Comments go with a rating.", headers=PRIVATE)
        if command.subject is not None and not _SUBJECT.fullmatch(command.subject):
            raise HTTPException(422, "That subject is not valid.", headers=PRIVATE)
        actor = auth.resolved.actor
        store = FeedbackStore(auth.database)
        earlier = await store.find_command(actor.person_id, command.command_id)
        if earlier is not None:
            response.status_code = 200
            return {"feedback_id": str(earlier.id)}
        allowed, retry, _remaining = await limiter.consume(str(actor.person_id), per_person)
        if not allowed:
            raise HTTPException(
                429,
                "Thanks, that's plenty for now.",
                headers={**PRIVATE, "Retry-After": str(retry)},
            )
        route = scrub_route(command.route)
        context = clean_context(command.context)
        release = context.get("app", {}).get("release") or settings.release_id[:40]
        now = datetime.now(UTC)
        row = await store.add(
            NewFeedback(
                person_id=actor.person_id,
                tenant_id=actor.tenant_id,
                command_id=command.command_id,
                moment=command.moment,
                subject=command.subject,
                kind=command.kind,
                rating=command.rating,
                comment=comment,
                route=route,
                release=str(release)[:40] if release else None,
                context=context,
            ),
            now=now,
        )
        result: dict[str, Any] = {"feedback_id": str(row.id)}
        if command.rating == 1 and comment:
            # A bad rating with words is something to fix: it joins the bug list.
            bug_id = uuid4()
            await BugReportStore(auth.database).create(
                NewReport(
                    person_id=actor.person_id,
                    tenant_id=actor.tenant_id,
                    command_id=command.command_id,
                    words=comment,
                    blocks_work=False,
                    area=area_for(route),
                    route=route,
                    context={
                        **context,
                        "server": {
                            "environment": settings.environment,
                            "release": settings.release_id[:40],
                        },
                        "feedback": {
                            "feedback_id": str(row.id),
                            "moment": command.moment,
                            "about": _MOMENT_LABEL.get(command.moment, command.moment),
                            "rating": RATING[1],
                        },
                    },
                    client_errors=[],
                    user_agent=(request.headers.get("user-agent") or "")[:512],
                ),
                bug_id=bug_id,
                now=now,
            )
            result["bug_id"] = str(bug_id)
        return result

    @router.get("/state")
    async def state(
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = read_dependency,
    ) -> dict[str, Any]:
        response.headers.update(PRIVATE)
        on_app_host(request)
        return await FeedbackStore(auth.database).state(
            auth.resolved.actor.person_id, now=datetime.now(UTC)
        )

    app.include_router(router)

    admin = APIRouter(prefix="/v1/admin/feedback", tags=["feedback-admin"])

    @admin.get("")
    async def summary(
        request: Request,
        response: Response,
        days: int = 30,
        moment: str | None = None,
        auth: AuthenticatedTransaction = read_dependency,
    ) -> dict[str, Any]:
        require_admin_surface(request, settings)
        response.headers.update(PRIVATE)
        if set(request.query_params) - {"days", "moment"}:
            raise HTTPException(422, "This view takes other filters.")
        if days not in (7, 30, 90):
            raise HTTPException(422, "Choose 7, 30 or 90 days.")
        if moment is not None and moment not in MOMENTS:
            raise HTTPException(422, "Choose a moment from the list.")
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
        return {
            "moments_known": list(MOMENTS),
            **await FeedbackStore(auth.database).summary(
                now=datetime.now(UTC), days=days, moment=moment
            ),
        }

    app.include_router(admin)
