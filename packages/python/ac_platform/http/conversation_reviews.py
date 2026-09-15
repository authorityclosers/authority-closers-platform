"""Authenticated HTTP transport for AC Sales Xray review assignments.

Review authority remains in :mod:`conversation_intelligence.review_service`.
This module only binds the current cookie session, same-origin mutation checks,
bounded request DTOs and private source playback to HTTP.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from starlette.responses import StreamingResponse

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationError,
)
from ac_platform.conversation_intelligence.async_io import join_thread
from ac_platform.conversation_intelligence.review_contracts import (
    ReviewAssignmentCreateRequest,
    ReviewFeedbackRequest,
    ReviewInvitationAcceptRequest,
    ReviewInvitationCreateRequest,
)
from ac_platform.conversation_intelligence.review_service import ConversationReviewService
from ac_platform.conversation_intelligence.storage import (
    ObjectKey,
    ObjectKind,
    PrivateLocalRecordingStorage,
    StorageError,
)
from ac_platform.http.auth import (
    AuthenticatedTransaction,
    RequireActor,
    require_admin_surface,
    require_safe_origin,
)
from ac_platform.http.conversation_playback import _PrivateAudioResponse, byte_range
from ac_platform.http.reviewer_auth import RequireReviewer, ReviewerTransaction, reviewer_scope
from ac_platform.telemetry.redaction import sanitize_error

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
ReviewKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]


def _private(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"


def _raise_conversation(error: ConversationError) -> HTTPException:
    status = getattr(error, "status", 422)
    return HTTPException(status, sanitize_error(error, max_length=512))


def _reviewer_capability_unavailable() -> NoReturn:
    raise HTTPException(503, "Reviewer access is not available.")


def install_conversation_review_http(
    app: FastAPI,
    *,
    settings: Settings,
    require_actor: RequireActor,
    require_reviewer: RequireReviewer | None = None,
    storage: PrivateLocalRecordingStorage | None = None,
    clock: Callable[[], datetime] | None = None,
) -> None:
    """Install admin assignment management and reviewer feedback routes."""

    def review_service(
        auth: AuthenticatedTransaction | ReviewerTransaction,
    ) -> ConversationReviewService:
        operations_tenant_id = settings.operations_tenant_id
        if operations_tenant_id is None:
            raise HTTPException(503, "Conversation review is not configured.")
        service = ConversationReviewService(
            ConversationApplication(auth.database, clock=clock)
            if clock is not None
            else ConversationApplication(auth.database),
            operations_tenant_id=operations_tenant_id,
        )
        # Keep cryptographic email delivery configuration at the HTTP composition
        # boundary; the service never reads process settings itself.
        service.token_secret = settings.email_challenge_secret.get_secret_value()
        return service

    function_dependency = Depends(require_actor, scope="function")
    reviewer_dependency = Depends(
        require_reviewer or _reviewer_capability_unavailable, scope="function"
    )
    reviewer_request_dependency = Depends(
        require_reviewer or _reviewer_capability_unavailable, scope="request"
    )
    admin = APIRouter(prefix="/v1/admin/conversation", tags=["conversation-review-admin"])
    reviewer = APIRouter(prefix="/v1/reviewer", tags=["conversation-review"])

    def admin_scope(request: Request, response: Response, *, write: bool = False) -> None:
        require_admin_surface(request, settings)
        _private(response)
        if request.query_params:
            raise HTTPException(422, "Review scope comes from your current AC session.")
        if write:
            require_safe_origin(request, settings)

    def review_scope(request: Request, response: Response, *, write: bool = False) -> None:
        reviewer_scope(request, settings, write=write)
        _private(response)
        if request.query_params:
            raise HTTPException(422, "Review scope comes from your current AC session.")

    async def reviewer_write_hold(auth: AuthenticatedTransaction) -> NoReturn:
        try:
            await review_service(auth)._admin(auth.resolved.actor)
        except ConversationError as error:
            raise _raise_conversation(error) from None
        _reviewer_capability_unavailable()

    @admin.get("/review-assignments")
    async def list_assignments(
        request: Request,
        response: Response,
        limit: Annotated[int, Query(ge=1, le=50)] = 50,
        auth: AuthenticatedTransaction = function_dependency,
    ) -> Any:
        require_admin_surface(request, settings)
        _private(response)
        # FastAPI validates the bounded value; reject all selectors and
        # duplicate values before service scope is evaluated.
        if request.query_params and (
            set(request.query_params) != {"limit"}
            or len(request.query_params.getlist("limit")) != 1
        ):
            raise HTTPException(422, "Review scope accepts only one bounded limit.")
        try:
            return await review_service(auth).list_assignments(auth.resolved.actor, limit=limit)
        except ConversationError as error:
            raise _raise_conversation(error) from None

    @admin.get("/review-assignments/{assignment_id}")
    async def admin_review_details(
        assignment_id: UUID,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = function_dependency,
    ) -> Any:
        """Operations read of saved review history; never impersonate a reviewer."""

        admin_scope(request, response)
        try:
            return await review_service(auth).admin_details(auth.resolved.actor, assignment_id)
        except ConversationError as error:
            raise _raise_conversation(error) from None

    @admin.post("/review-assignments", status_code=201)
    async def create_assignment(
        intent: ReviewAssignmentCreateRequest,
        request: Request,
        response: Response,
        key: ReviewKey,
        auth: AuthenticatedTransaction = function_dependency,
    ) -> Any:
        admin_scope(request, response, write=True)
        if require_reviewer is None:
            await reviewer_write_hold(auth)
        try:
            return await review_service(auth).create(auth.resolved.actor, intent, key)
        except ConversationError as error:
            raise _raise_conversation(error) from None

    @admin.post("/review-invitations", status_code=201)
    async def create_invitation(
        intent: ReviewInvitationCreateRequest,
        request: Request,
        response: Response,
        key: ReviewKey,
        auth: AuthenticatedTransaction = function_dependency,
    ) -> Any:
        admin_scope(request, response, write=True)
        if require_reviewer is None:
            await reviewer_write_hold(auth)
        try:
            return await review_service(auth).invite(auth.resolved.actor, intent, key)
        except ConversationError as error:
            raise _raise_conversation(error) from None

    @admin.post("/review-invitations/{invitation_id}/revoke")
    async def revoke_invitation(
        invitation_id: UUID,
        request: Request,
        response: Response,
        key: ReviewKey,
        auth: AuthenticatedTransaction = function_dependency,
    ) -> Any:
        admin_scope(request, response, write=True)
        try:
            return await review_service(auth).revoke_invitation(
                auth.resolved.actor, invitation_id, key
            )
        except ConversationError as error:
            raise _raise_conversation(error) from None

    @admin.post("/review-assignments/{assignment_id}/revoke")
    async def revoke_assignment(
        assignment_id: UUID,
        request: Request,
        response: Response,
        key: ReviewKey,
        auth: AuthenticatedTransaction = function_dependency,
    ) -> Any:
        admin_scope(request, response, write=True)
        try:
            return await review_service(auth).revoke(auth.resolved.actor, assignment_id, key)
        except ConversationError as error:
            raise _raise_conversation(error) from None

    @reviewer.get("/review-assignments")
    async def assigned_reviews(
        request: Request,
        response: Response,
        limit: Annotated[int, Query(ge=1, le=50)] = 50,
        auth: ReviewerTransaction = reviewer_dependency,
    ) -> Any:
        reviewer_scope(request, settings)
        _private(response)
        if request.query_params and (
            set(request.query_params) != {"limit"}
            or len(request.query_params.getlist("limit")) != 1
        ):
            raise HTTPException(422, "Review scope accepts only one bounded limit.")
        try:
            return await review_service(auth).reviewer_assignments(auth.actor, limit=limit)
        except ConversationError as error:
            raise _raise_conversation(error) from None

    @reviewer.get("/review-assignments/{assignment_id}")
    async def get_assignment(
        assignment_id: UUID,
        request: Request,
        response: Response,
        auth: ReviewerTransaction = reviewer_dependency,
    ) -> Any:
        review_scope(request, response)
        try:
            return await review_service(auth).get(auth.actor, assignment_id)
        except ConversationError as error:
            raise _raise_conversation(error) from None

    @reviewer.post("/review-invitations/accept", status_code=201)
    async def accept_invitation(
        intent: ReviewInvitationAcceptRequest,
        request: Request,
        response: Response,
        auth: ReviewerTransaction = reviewer_dependency,
    ) -> Any:
        review_scope(request, response, write=True)
        try:
            return await review_service(auth).accept_invitation(auth.actor, intent)
        except ConversationError as error:
            raise _raise_conversation(error) from None

    @reviewer.get("/review-assignments/{assignment_id}/submissions")
    async def list_submissions(
        assignment_id: UUID,
        request: Request,
        response: Response,
        auth: ReviewerTransaction = reviewer_dependency,
    ) -> Any:
        review_scope(request, response)
        try:
            return await review_service(auth).submissions(auth.actor, assignment_id)
        except ConversationError as error:
            raise _raise_conversation(error) from None

    @reviewer.post("/review-assignments/{assignment_id}/submissions", status_code=201)
    async def submit_submission(
        assignment_id: UUID,
        intent: ReviewFeedbackRequest,
        request: Request,
        response: Response,
        auth: ReviewerTransaction = reviewer_dependency,
    ) -> Any:
        review_scope(request, response, write=True)
        try:
            return await review_service(auth).submit(auth.actor, assignment_id, intent)
        except ConversationError as error:
            raise _raise_conversation(error) from None

    @reviewer.get("/review-assignments/{assignment_id}/source")
    async def source(
        assignment_id: UUID,
        request: Request,
        response: Response,
        auth: ReviewerTransaction = reviewer_request_dependency,
    ) -> StreamingResponse:
        review_scope(request, response)
        if storage is None:
            raise HTTPException(503, "Private conversation storage is not configured.")
        try:
            recording = await review_service(auth).playback(auth.actor, assignment_id)
        except ConversationError as error:
            raise _raise_conversation(error) from None
        try:
            source_bytes = recording["source_bytes"]
            source_sha256 = recording["source_sha256"]
            tenant_id = UUID(str(recording["tenant_id"]))
            recording_id = UUID(str(recording["id"]))
            content_type = str(recording["content_type"])
            if (
                type(source_bytes) is not int
                or source_bytes <= 0
                or not isinstance(source_sha256, str)
                or _DIGEST.fullmatch(source_sha256) is None
                or not content_type
            ):
                raise StorageError("invalid private source descriptor")
            ranges = request.headers.getlist("range")
            if len(ranges) > 1:
                raise ValueError("duplicate range")
            start, end = byte_range(ranges[0] if ranges else None, source_bytes)
        except (KeyError, TypeError, ValueError, StorageError):
            raise HTTPException(
                416,
                "Use a single valid audio byte range.",
                headers={"Content-Range": f"bytes */{recording.get('source_bytes', 0)}"},
            ) from None
        iterator = storage.iter_bytes(
            ObjectKey(tenant_id, recording_id, recording_id, ObjectKind.SOURCE_AUDIO),
            expected_sha256=source_sha256,
        )
        try:
            first = await join_thread(lambda: next(iterator, None))
            if first is None:
                raise StorageError("empty private source")
        except BaseException as error:
            close = getattr(iterator, "close", None)
            if close is not None:
                await join_thread(close)
            if isinstance(error, (StorageError, OSError)):
                raise HTTPException(409, "The retained recording is unavailable.") from None
            raise
        headers = {
            "Cache-Control": "private, no-store",
            "Accept-Ranges": "bytes",
            "Content-Length": str(end - start + 1),
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": 'inline; filename="sales-call"',
        }
        if ranges:
            headers["Content-Range"] = f"bytes {start}-{end}/{source_bytes}"
        return _PrivateAudioResponse(
            iterator,
            first,
            start,
            end,
            status_code=206 if ranges else 200,
            media_type=content_type,
            headers=headers,
        )

    app.include_router(admin)
    if require_reviewer is not None:
        app.include_router(reviewer)
    # The legacy /v1/conversation review routes remain absent. Generic learner
    # sessions are never an admission dependency for the reviewer workspace.


__all__ = ["install_conversation_review_http"]
