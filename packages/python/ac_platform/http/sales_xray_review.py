"""Gold review in the Sales Xray app (owner, 19 Oct): Dipak reviews on his phone.

Account sessions of standing gold reviewers only, on the Sales Xray host. The
gold service, rows and audio guards are the Admin reviewer workspace's own; see
:mod:`conversation_intelligence.gold_review_account` for the admission. ``/push``
and ``/devices`` turn on review alerts on the reviewer's phone
(:mod:`lead_desk.review_push`).

Every route signs in inside a time budget (:func:`http.bounded_session.signed_in`).
Reads and the audio route use the read-only sign-in (shared locks, no session write), and the audio
route lets go of its database transaction before the bytes stream. On 19 Oct a
review audio stream held the locking sign-in for its whole stream; each badge
poll of the same person queued behind it holding a pooled connection, and the
production pool ran dry (13 badges waited up to 28 minutes).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, FastAPI, Header, HTTPException, Request, Response
from starlette.responses import StreamingResponse

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationError,
)
from ac_platform.conversation_intelligence.gold_review_account import (
    AccountGoldReviewService,
    account_actor,
    badge,
    metrics,
    queue,
    standing_reviewer,
)
from ac_platform.conversation_intelligence.gold_review_contracts import GoldSave
from ac_platform.conversation_intelligence.gold_reviews import GoldReviews
from ac_platform.http.auth import AuthenticatedTransaction, RequireActor, require_safe_origin
from ac_platform.http.bounded_session import read_only as read_only_sign_in
from ac_platform.http.bounded_session import signed_in
from ac_platform.kernel.errors import DomainError
from ac_platform.lead_desk import push, review_push
from ac_platform.lead_desk.contracts import DeviceCommand, DeviceView, PushConfig
from ac_platform.telemetry.redaction import sanitize_error

_PRIVATE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}
# Seconds a request may spend signing in and reading; the badge is polled by
# every signed-in person, so it gets the shortest budget.
BADGE_BUDGET = 5.0
READ_BUDGET = 15.0
WRITE_BUDGET = 15.0

StreamSource = Callable[..., Awaitable[StreamingResponse]]


def install_sales_xray_review_http(
    app: FastAPI,
    *,
    settings: Settings,
    require_actor: RequireActor,
    stream_source: StreamSource,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> None:
    router = APIRouter(prefix="/v1/sales-xray/review", tags=["sales-xray-review"])
    read_only = read_only_sign_in(require_actor)

    def reading(request: Request, budget: float = READ_BUDGET) -> Any:
        return signed_in(read_only, request, budget)

    def writing(request: Request) -> Any:
        return signed_in(require_actor, request, WRITE_BUDGET)

    def surface(request: Request, response: Response, *, write: bool = False) -> None:
        response.headers.update(_PRIVATE)
        hosts = {settings.public_app_url.host}
        if settings.sales_xray_app_url is not None:
            hosts.add(settings.sales_xray_app_url.host)
        if request.url.hostname not in hosts:
            raise HTTPException(404, "Review is unavailable here.", headers=_PRIVATE)
        if request.query_params:
            raise HTTPException(422, "Review comes from your sign-in.", headers=_PRIVATE)
        if write:
            try:
                require_safe_origin(request, settings)
            except DomainError:
                raise HTTPException(
                    403, "Save from the Sales Xray app.", headers=_PRIVATE
                ) from None

    def service(auth: AuthenticatedTransaction) -> AccountGoldReviewService:
        if settings.operations_tenant_id is None:
            raise HTTPException(503, "Review is not configured.", headers=_PRIVATE)
        return AccountGoldReviewService(
            ConversationApplication(auth.database, clock=clock),
            operations_tenant_id=settings.operations_tenant_id,
        )

    def failed(error: ConversationError) -> HTTPException:
        return HTTPException(
            getattr(error, "status", 422), sanitize_error(error, max_length=512), headers=_PRIVATE
        )

    @router.get("/badge")
    async def read_badge(request: Request, response: Response) -> Any:
        surface(request, response)
        async with reading(request, BADGE_BUDGET) as auth:
            return await badge(
                auth.database, settings.operations_tenant_id, auth.resolved.actor.person_id, clock()
            )

    @router.get("/push", response_model=PushConfig, response_model_by_alias=True)
    async def read_push(request: Request, response: Response) -> PushConfig:
        """The app's Firebase client settings (public, no secrets), for reviewers only."""
        surface(request, response)
        async with reading(request, BADGE_BUDGET) as auth:
            if not await standing_reviewer(auth.database, auth.resolved.actor.person_id):
                return PushConfig(enabled=False)
        return push.client_config(push.config())

    @router.post("/devices", response_model=DeviceView, response_model_by_alias=True)
    async def register_phone(
        body: DeviceCommand,
        request: Request,
        response: Response,
    ) -> DeviceView:
        """This phone gets my review alerts."""
        surface(request, response, write=True)
        try:
            async with writing(request) as auth:
                actor = auth.resolved.actor
                registered = await review_push.register_phone(
                    auth.database,
                    actor.person_id,
                    body,
                    clock(),
                    quiet=(settings.operations_tenant_id, settings.public_learner_tenant_id),
                    current=actor.tenant_id,
                )
        except ConversationError as error:
            raise failed(error) from None
        return DeviceView(registered=registered)

    @router.get("/queue")
    async def read_queue(request: Request, response: Response) -> Any:
        surface(request, response)
        try:
            async with reading(request) as auth:
                return await queue(auth.database, auth.resolved.actor.person_id, clock())
        except ConversationError as error:
            raise failed(error) from None

    @router.get("/metrics")
    async def read_metrics(request: Request, response: Response) -> Any:
        surface(request, response)
        try:
            async with reading(request) as auth:
                return await metrics(
                    auth.database,
                    settings.operations_tenant_id,
                    auth.resolved.actor.person_id,
                    clock(),
                )
        except ConversationError as error:
            raise failed(error) from None

    @router.get("/assignments/{assignment_id}")
    async def read_assignment(
        assignment_id: UUID,
        request: Request,
        response: Response,
    ) -> Any:
        surface(request, response)
        try:
            async with reading(request) as auth:
                body = await GoldReviews(service(auth)).get(
                    account_actor(auth.resolved.actor), assignment_id
                )
        except ConversationError as error:
            raise failed(error) from None
        body["audio_source_url"] = f"/v1/sales-xray/review/assignments/{assignment_id}/source"
        return body

    @router.post("/assignments/{assignment_id}/lines", status_code=201)
    async def save_line(
        assignment_id: UUID,
        body: GoldSave,
        request: Request,
        response: Response,
        idempotency_key: str = Header(min_length=1, max_length=128, alias="Idempotency-Key"),
    ) -> Any:
        surface(request, response, write=True)
        try:
            async with writing(request) as auth:
                return await GoldReviews(service(auth)).save(
                    account_actor(auth.resolved.actor), assignment_id, body, idempotency_key
                )
        except ConversationError as error:
            raise failed(error) from None

    @router.get("/assignments/{assignment_id}/source")
    async def source(
        assignment_id: UUID,
        request: Request,
        response: Response,
    ) -> StreamingResponse:
        surface(request, response)
        # The transaction ends with this block: the stream itself holds no locks
        # and no pooled connection, however long the phone keeps it open.
        async with reading(request) as auth:
            return await stream_source(
                service(auth),
                auth.database,
                account_actor(auth.resolved.actor),
                assignment_id,
                request,
            )

    app.include_router(router)


__all__ = ["install_sales_xray_review_http"]
