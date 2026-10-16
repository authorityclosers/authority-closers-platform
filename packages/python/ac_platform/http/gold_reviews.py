"""Gold routes reuse the canonical reviewer/admin dependencies and source guards."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response

from ac_platform.conversation_intelligence.application import ConversationError
from ac_platform.conversation_intelligence.gold_review_contracts import GoldDesignation, GoldSave
from ac_platform.conversation_intelligence.gold_reviews import GoldReviews
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.http.reviewer_auth import ReviewerTransaction
from ac_platform.telemetry.redaction import sanitize_error


def install_gold_routes(
    admin: APIRouter,
    reviewer: APIRouter,
    review_service: Any,
    admin_scope: Any,
    review_scope: Any,
    require_actor: Any,
    require_reviewer: Any,
) -> None:
    admin_dependency = Depends(require_actor, scope="function")
    reviewer_dependency = Depends(require_reviewer, scope="function")

    def failed(error: ConversationError) -> HTTPException:
        return HTTPException(getattr(error, "status", 422), sanitize_error(error, max_length=512))

    @admin.get("/gold-reviewers")
    async def reviewers(
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = admin_dependency,
    ) -> Any:
        admin_scope(request, response)
        try:
            return await GoldReviews(review_service(auth)).reviewers(auth.resolved.actor)
        except ConversationError as error:
            raise failed(error) from None

    @admin.post("/gold-reviewers")
    async def designate(
        body: GoldDesignation,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = admin_dependency,
    ) -> Any:
        admin_scope(request, response, write=True)
        try:
            return await GoldReviews(review_service(auth)).designate(
                auth.resolved.actor, body.email, body.active
            )
        except ConversationError as error:
            raise failed(error) from None

    @admin.get("/gold-rows")
    async def gold_rows(
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = admin_dependency,
    ) -> Any:
        admin_scope(request, response)
        try:
            return await GoldReviews(review_service(auth)).rows(auth.resolved.actor)
        except ConversationError as error:
            raise failed(error) from None

    if require_reviewer is None:
        return

    @reviewer.get("/review-assignments/{assignment_id}/gold")
    async def workspace(
        assignment_id: UUID,
        request: Request,
        response: Response,
        auth: ReviewerTransaction = reviewer_dependency,
    ) -> Any:
        review_scope(request, response)
        try:
            return await GoldReviews(review_service(auth)).get(auth.actor, assignment_id)
        except ConversationError as error:
            raise failed(error) from None

    @reviewer.post("/review-assignments/{assignment_id}/gold", status_code=201)
    async def save(
        assignment_id: UUID,
        body: GoldSave,
        request: Request,
        response: Response,
        idempotency_key: str = Header(min_length=1, max_length=128, alias="Idempotency-Key"),
        auth: ReviewerTransaction = reviewer_dependency,
    ) -> Any:
        review_scope(request, response, write=True)
        try:
            return await GoldReviews(review_service(auth)).save(
                auth.actor, assignment_id, body, idempotency_key
            )
        except ConversationError as error:
            raise failed(error) from None
