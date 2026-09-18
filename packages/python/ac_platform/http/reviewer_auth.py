"""Reviewer-only mailbox authentication on the operations application host."""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationError,
    utc,
)
from ac_platform.conversation_intelligence.models import (
    ConversationReviewAssignment,
    ConversationReviewInvitation,
    ConversationReviewInvitationRevocation,
    ConversationReviewRevocation,
)
from ac_platform.conversation_intelligence.review_contracts import ReviewInvitationAcceptRequest
from ac_platform.conversation_intelligence.review_invitations import (
    decrypt_invitation_token,
    hash_invitation_token,
)
from ac_platform.conversation_intelligence.review_service import ConversationReviewService
from ac_platform.http.auth import (
    SESSION_COOKIE_VALUE_PATTERN,
    AuthenticationRequired,
    _InvalidRawCookie,
    _single_raw_cookie,
    require_admin_surface,
)
from ac_platform.identity.models import Person
from ac_platform.identity.reviewer_auth import (
    REVIEWER_AUTH_CHALLENGE_TTL,
    REVIEWER_AUTH_EVENT,
    ReviewerAuthenticationError,
    ReviewerAuthenticationService,
    ReviewerSession,
    validate_reviewer_browser_nonce,
)
from ac_platform.identity.services import IdentityServiceError, normalize_email
from ac_platform.kernel.authz import ActorContext
from ac_platform.kernel.events import EventCategory, EventEnvelope
from ac_platform.outbox.repository import OutboxRepository
from ac_platform.telemetry.redaction import sanitize_error
from ac_platform.tenancy.models import Tenant


def reviewer_cookie_name(settings: Settings) -> str:
    return "__Host-ac_reviewer_session" if settings.secure_cookies else "ac_reviewer_session"


def reviewer_state_cookie_name(settings: Settings) -> str:
    return "__Host-ac_reviewer_state" if settings.secure_cookies else "ac_reviewer_state"


def reviewer_scope(request: Request, settings: Settings, *, write: bool = False) -> None:
    require_admin_surface(request, settings)
    if write and request.headers.get("origin", "").rstrip("/") != str(
        settings.admin_app_url
    ).rstrip("/"):
        raise HTTPException(403, "Reviewer actions require the reviewer workspace origin.")


def _no_query(request: Request) -> None:
    if request.query_params:
        raise HTTPException(422, "Reviewer scope comes from your sign-in and assignment.")


def _private(response: Response) -> None:
    response.headers["cache-control"] = "private, no-store"
    response.headers["pragma"] = "no-cache"


@dataclass(slots=True)
class ReviewerTransaction:
    database: AsyncSession
    actor: ActorContext
    identity: ReviewerSession
    token: str = field(repr=False)


RequireReviewer = Callable[[Request], AsyncIterator[ReviewerTransaction]]


class ReviewerSignInRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=320)
    invitation_token: str | None = Field(default=None, min_length=40, max_length=512)


class ReviewerVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=40, max_length=512)


async def _invitation(
    database: AsyncSession,
    now: datetime,
    *,
    identifier: UUID | None = None,
    token_hash: bytes | None = None,
    lock: bool = False,
) -> ConversationReviewInvitation | None:
    selector = (
        ConversationReviewInvitation.id == identifier
        if identifier is not None
        else ConversationReviewInvitation.token_hash == token_hash
    )
    row = await database.scalar(
        select(ConversationReviewInvitation)
        .join(Tenant, Tenant.id == ConversationReviewInvitation.tenant_id)
        .where(selector, Tenant.status == "active", ConversationReviewInvitation.expires_at > now)
        .with_for_update(read=not lock)
        .execution_options(populate_existing=True)
    )
    if (
        row is not None
        and await database.get(ConversationReviewInvitationRevocation, row.id) is None
    ):
        return row
    return None


async def _has_assignment(database: AsyncSession, person_id: UUID, now: datetime) -> bool:
    return (
        await database.scalar(
            select(ConversationReviewAssignment.id)
            .join(Tenant, Tenant.id == ConversationReviewAssignment.tenant_id)
            .where(
                ConversationReviewAssignment.reviewer_id == person_id,
                ConversationReviewAssignment.expires_at > now,
                Tenant.status == "active",
                ~select(ConversationReviewRevocation.assignment_id)
                .where(
                    ConversationReviewRevocation.assignment_id == ConversationReviewAssignment.id
                )
                .exists(),
            )
            .limit(1)
        )
        is not None
    )


def _identity_body(identity: ReviewerSession) -> dict[str, Any]:
    return {
        "person_id": str(identity.person.id),
        "email": identity.person.email,
        "display_name": identity.person.display_name,
        "expires_at_epoch": int(utc(identity.session.expires_at).timestamp()),
    }


def install_reviewer_identity_http(
    app: FastAPI,
    *,
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> RequireReviewer:
    secret = settings.email_challenge_secret.get_secret_value()
    pepper = settings.session_token_pepper.get_secret_value()
    cookie_name = reviewer_cookie_name(settings)
    state_cookie_name = reviewer_state_cookie_name(settings)

    def service(database: AsyncSession) -> ReviewerAuthenticationService:
        return ReviewerAuthenticationService(database, challenge_secret=secret, token_pepper=pepper)

    async def require_reviewer(request: Request) -> AsyncIterator[ReviewerTransaction]:
        reviewer_scope(request, settings)
        try:
            token = _single_raw_cookie(
                request, name=cookie_name, pattern=SESSION_COOKIE_VALUE_PATTERN, required=True
            )
            if token is None:
                raise _InvalidRawCookie
        except _InvalidRawCookie:
            raise AuthenticationRequired("Sign in to your reviewer workspace.") from None
        async with sessions() as database, database.begin():
            try:
                resolved = await service(database).resolve_session(token, now=clock())
            except (IdentityServiceError, ReviewerAuthenticationError, ValueError):
                raise AuthenticationRequired("Sign in to your reviewer workspace.") from None
            yield ReviewerTransaction(
                database,
                ActorContext(resolved.person.id, resolved.session.id, None),
                resolved,
                token,
            )

    router = APIRouter(prefix="/v1/reviewer", tags=["reviewer-identity"])
    dependency = Depends(require_reviewer, scope="function")

    @router.post("/auth/request", status_code=202)
    async def request_sign_in(
        request: Request, response: Response, body: ReviewerSignInRequest
    ) -> dict[str, str]:
        reviewer_scope(request, settings, write=True)
        _no_query(request)
        _private(response)
        generic = {"status": "check_email"}
        try:
            browser_nonce = _single_raw_cookie(
                request,
                name=state_cookie_name,
                pattern=SESSION_COOKIE_VALUE_PATTERN,
                required=False,
            )
            if browser_nonce is not None:
                validate_reviewer_browser_nonce(browser_nonce)
        except (_InvalidRawCookie, ReviewerAuthenticationError):
            browser_nonce = None
        browser_nonce = browser_nonce or secrets.token_urlsafe(32)
        # Every request receives identical cookie treatment, including unknown
        # addresses. Preserve a valid nonce so a retry does not break an in-flight link.
        response.set_cookie(
            state_cookie_name,
            browser_nonce,
            max_age=int(REVIEWER_AUTH_CHALLENGE_TTL.total_seconds()),
            secure=settings.secure_cookies,
            httponly=True,
            samesite="lax",
            path="/",
        )
        try:
            email = normalize_email(body.email)
            digest = (
                None
                if body.invitation_token is None
                else hash_invitation_token(secret, body.invitation_token)
            )
        except (ValueError, UnicodeError, TypeError):
            return generic
        now = utc(clock())
        async with sessions() as database, database.begin():
            person = await database.scalar(
                select(Person).where(func.lower(Person.email) == func.lower(email))
            )
            if person is not None and person.status != "active":
                return generic
            invitation_id = None
            if digest is not None:
                invite = await _invitation(database, now, token_hash=digest)
                if (
                    invite is None
                    or normalize_email(invite.invited_email).casefold() != email.casefold()
                ):
                    return generic
                invitation_id = invite.id
            elif person is None or not await _has_assignment(database, person.id, now):
                return generic
            try:
                challenge = await service(database).issue_challenge(
                    email=email,
                    browser_nonce=browser_nonce,
                    invitation_id=invitation_id,
                    person_id=None if person is None else person.id,
                    now=now,
                )
            except ReviewerAuthenticationError:
                return generic
            if challenge is not None:
                await OutboxRepository(database).enqueue(
                    EventEnvelope(
                        name=REVIEWER_AUTH_EVENT,
                        category=EventCategory.OPERATIONAL,
                        aggregate_type="reviewer_auth_challenge",
                        aggregate_id=challenge.challenge_id,
                        payload={"challenge_id": str(challenge.challenge_id)},
                        occurred_at=now,
                        tenant_id=None,
                    ),
                    dedupe_key=f"reviewer-auth:{challenge.challenge_id}",
                )
        return generic

    @router.post("/auth/verify")
    async def verify_sign_in(
        request: Request, response: Response, body: ReviewerVerifyRequest
    ) -> dict[str, Any]:
        reviewer_scope(request, settings, write=True)
        _no_query(request)
        try:
            browser_nonce = _single_raw_cookie(
                request,
                name=state_cookie_name,
                pattern=SESSION_COOKIE_VALUE_PATTERN,
                required=True,
            )
            if browser_nonce is None:
                raise _InvalidRawCookie
        except _InvalidRawCookie:
            raise AuthenticationRequired(
                "Open the sign-in link in the same browser where you requested it."
            ) from None
        async with sessions() as database, database.begin():
            try:
                verified = await service(database).consume_challenge(
                    body.token,
                    browser_nonce=browser_nonce,
                    user_agent=request.headers.get("user-agent"),
                    ip_address=request.client.host if request.client else None,
                    now=clock(),
                )
            except (IdentityServiceError, ReviewerAuthenticationError, ValueError):
                raise AuthenticationRequired(
                    "This sign-in link is invalid or has expired."
                ) from None
            actor = ActorContext(verified.person.id, verified.session.metadata.id, None)
            assignment_id = None
            if verified.invitation_id is not None:
                invite = await _invitation(
                    database, utc(clock()), identifier=verified.invitation_id, lock=True
                )
                if (
                    invite is None
                    or normalize_email(invite.invited_email).casefold()
                    != normalize_email(verified.person.email or "").casefold()
                ):
                    raise HTTPException(404, "Review invitation is no longer available.")
                if settings.operations_tenant_id is None:
                    raise HTTPException(503, "Review access is not configured.")
                reviews = ConversationReviewService(
                    ConversationApplication(database, clock=clock),
                    operations_tenant_id=settings.operations_tenant_id,
                    token_secret=secret,
                )
                try:
                    assignment = await reviews.accept_invitation(
                        actor,
                        ReviewInvitationAcceptRequest(
                            token=decrypt_invitation_token(
                                secret, invite.encrypted_token, invite.id
                            )
                        ),
                    )
                except ConversationError as error:
                    raise HTTPException(
                        error.status, sanitize_error(error, max_length=512)
                    ) from None
                if assignment["state"] in {"revoked", "expired"}:
                    raise HTTPException(403, "This reviewer assignment has ended.")
                assignment_id = assignment["id"]
            elif not await _has_assignment(database, verified.person.id, utc(clock())):
                raise HTTPException(403, "No current reviewer assignment is available.")
        # A failed transaction must never deliver a session cookie.
        response.delete_cookie(
            state_cookie_name,
            path="/",
            secure=settings.secure_cookies,
            httponly=True,
            samesite="lax",
        )
        response.set_cookie(
            cookie_name,
            verified.session.token,
            max_age=max(
                0, int((utc(verified.session.metadata.expires_at) - utc(clock())).total_seconds())
            ),
            secure=settings.secure_cookies,
            httponly=True,
            samesite="lax",
            path="/",
        )
        _private(response)
        return {
            **_identity_body(ReviewerSession(verified.person, verified.session.metadata)),
            "assignment_id": assignment_id,
        }

    @router.get("/me")
    async def me(
        request: Request, response: Response, auth: ReviewerTransaction = dependency
    ) -> Any:
        _no_query(request)
        _private(response)
        return _identity_body(auth.identity)

    @router.post("/auth/logout", status_code=204)
    async def logout(
        request: Request, response: Response, auth: ReviewerTransaction = dependency
    ) -> None:
        reviewer_scope(request, settings, write=True)
        _no_query(request)
        await service(auth.database).revoke_session(auth.token, now=clock())
        response.delete_cookie(
            cookie_name, path="/", secure=settings.secure_cookies, httponly=True, samesite="lax"
        )
        _private(response)

    app.include_router(router)
    return require_reviewer
