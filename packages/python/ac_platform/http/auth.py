"""Fail-closed cookie authentication and OAuth callback composition."""

from __future__ import annotations

import hmac
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ac_platform.application.settings import Settings
from ac_platform.http.auth_transactions import (
    AUTH_TRANSACTION_MAX_AGE_SECONDS,
    AuthTransaction,
    AuthTransactionCodec,
    InvalidAuthTransaction,
    normalize_return_path,
)
from ac_platform.http.identity_provider import DisabledIdentityProvider, OAuthIdentityProvider
from ac_platform.http.problem import problem_response
from ac_platform.identity.application import AsyncIdentityApplication, ResolvedActorContext
from ac_platform.identity.services import AuthorizationDenied as IdentityAuthorizationDenied
from ac_platform.identity.services import (
    IdentityConcurrencyError,
    IdentityResolutionError,
    IdentityServiceError,
    ProviderAuthorizationType,
    SessionMetadata,
    SessionNotFoundError,
    TenantScopeDeniedError,
)
from ac_platform.kernel.authz import ActorContext
from ac_platform.kernel.errors import DomainError, ResourceNotFound

SESSION_MAX_AGE_SECONDS = 30 * 24 * 60 * 60

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "owner": frozenset(
        {
            "admin_surface",
            "catalog_write",
            "catalog_publish",
            "learner_diagnose",
            "learning_correct",
            "learning_review",
            "enrollment_grant",
            "job_retry",
            "recovery_reconcile",
            "certificate_correct",
            "certificate_revoke",
        }
    ),
    "admin": frozenset(
        {
            "admin_surface",
            "catalog_write",
            "catalog_publish",
            "learner_diagnose",
            "learning_correct",
            "learning_review",
            "enrollment_grant",
            "job_retry",
            "recovery_reconcile",
            "certificate_correct",
            "certificate_revoke",
        }
    ),
    "support": frozenset(
        {
            "admin_surface",
            "learner_diagnose",
            "learning_correct",
            "learning_review",
            "enrollment_grant",
            "job_retry",
        }
    ),
    "learner": frozenset(),
}


class AuthenticationRequired(DomainError):
    code = "authentication_required"
    title = "Authentication is required"
    status = 401


class RequestOriginDenied(DomainError):
    code = "request_origin_denied"
    title = "The request origin is not allowed"
    status = 403


@dataclass(slots=True)
class AuthenticatedTransaction:
    database: AsyncSession
    identity: AsyncIdentityApplication
    resolved: ResolvedActorContext
    token: str


RequireActor = Callable[[Request], AsyncIterator[AuthenticatedTransaction]]


class MeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person_id: UUID
    email: str
    display_name: str | None
    email_verified_at: datetime
    selected_tenant_id: UUID | None
    membership_role: str | None
    permissions: list[str]


class ContextResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person_id: UUID
    session_id: UUID
    tenant_id: UUID | None
    membership_role: str | None
    permissions: list[str]


class SelectContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID


class RevokeSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=200)


class SessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    person_id: UUID
    created_at: datetime
    expires_at: datetime
    last_seen_at: datetime | None
    revoked_at: datetime | None
    revocation_reason: str | None
    selected_tenant_id: UUID | None
    revision: int


def _with_role_permissions(resolved: ResolvedActorContext) -> ResolvedActorContext:
    permissions = ROLE_PERMISSIONS.get(resolved.membership_role or "", frozenset())
    return replace(
        resolved,
        actor=ActorContext(
            person_id=resolved.actor.person_id,
            session_id=resolved.actor.session_id,
            tenant_id=resolved.actor.tenant_id,
            permissions=permissions,
        ),
    )


def _context_response(resolved: ResolvedActorContext) -> ContextResponse:
    return ContextResponse(
        person_id=resolved.actor.person_id,
        session_id=resolved.actor.session_id,
        tenant_id=resolved.actor.tenant_id,
        membership_role=resolved.membership_role,
        permissions=sorted(resolved.actor.permissions),
    )


def _session_response(session: SessionMetadata) -> SessionResponse:
    return SessionResponse(
        id=session.id,
        person_id=session.person_id,
        created_at=session.created_at,
        expires_at=session.expires_at,
        last_seen_at=session.last_seen_at,
        revoked_at=session.revoked_at,
        revocation_reason=session.revocation_reason,
        selected_tenant_id=session.selected_tenant_id,
        revision=session.revision,
    )


def require_safe_origin(request: Request, settings: Settings) -> None:
    origin = request.headers.get("origin")
    if origin is None or origin.rstrip("/") not in settings.allowed_origins:
        raise RequestOriginDenied("Cookie-authenticated state changes require an allowed Origin.")


def _session_cookie(request: Request, settings: Settings) -> str:
    token = request.cookies.get(settings.session_cookie_name)
    if token is None:
        raise AuthenticationRequired("A valid Authority Closers session is required.")
    return token


def _set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )


def _delete_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        settings.session_cookie_name,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )


def _surface_origin(settings: Settings, surface: str) -> str:
    value = settings.admin_app_url if surface == "admin" else settings.public_app_url
    return str(value).rstrip("/")


def _surface_callback_uri(settings: Settings, surface: str) -> str:
    return f"{_surface_origin(settings, surface)}/v1/auth/google/callback"


def _require_surface_host(request: Request, settings: Settings, surface: str) -> None:
    if settings.environment not in {"staging", "production"}:
        return
    expected_host = (
        settings.admin_app_url.host if surface == "admin" else settings.public_app_url.host
    )
    if request.url.hostname != expected_host:
        raise InvalidAuthTransaction("The sign-in surface does not match the request host.")


async def identity_error_handler(
    request: Request,
    error: IdentityServiceError,
) -> JSONResponse:
    if isinstance(error, TenantScopeDeniedError):
        error_status = status.HTTP_403_FORBIDDEN
        code = "tenant_context_denied"
        title = "Tenant context is not allowed"
        detail = "The selected tenant context is unavailable."
    elif isinstance(error, (IdentityAuthorizationDenied, IdentityResolutionError)):
        error_status = status.HTTP_401_UNAUTHORIZED
        code = "authentication_rejected"
        title = "Authentication was rejected"
        detail = "The identity or session could not be authenticated."
    elif isinstance(error, SessionNotFoundError):
        error_status = status.HTTP_404_NOT_FOUND
        code = "session_not_found"
        title = "Session not found"
        detail = "The requested session does not exist."
    elif isinstance(error, IdentityConcurrencyError):
        error_status = status.HTTP_409_CONFLICT
        code = "identity_changed"
        title = "The identity changed"
        detail = "Refresh the current identity state and retry."
    else:
        error_status = status.HTTP_422_UNPROCESSABLE_CONTENT
        code = "identity_rejected"
        title = "The identity operation was rejected"
        detail = "The requested identity operation violates a policy."
    return problem_response(
        request=request,
        status_code=error_status,
        code=code,
        title=title,
        detail=detail,
    )


def install_identity_http(
    application: FastAPI,
    *,
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    provider: OAuthIdentityProvider | None = None,
) -> RequireActor:
    """Install identity routes around one caller-owned database transaction."""

    identity_provider = provider or DisabledIdentityProvider()
    codec = AuthTransactionCodec(settings.oauth_transaction_secret.get_secret_value())
    token_pepper = settings.session_token_pepper.get_secret_value()
    router = APIRouter(prefix="/v1", tags=["identity"])
    application.add_exception_handler(IdentityServiceError, identity_error_handler)  # type: ignore[arg-type]

    async def require_actor(request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        token = _session_cookie(request, settings)
        async with sessions() as database, database.begin():
            identity = AsyncIdentityApplication(database, token_pepper=token_pepper)
            resolved = _with_role_permissions(await identity.resolve_actor(token))
            yield AuthenticatedTransaction(
                database=database,
                identity=identity,
                resolved=resolved,
                token=token,
            )

    actor_dependency = Depends(require_actor)

    @router.get("/auth/google/start", name="google_auth_start")
    async def google_auth_start(
        request: Request,
        authorization_type: Annotated[ProviderAuthorizationType, Query(alias="action")],
        surface: Literal["learner", "admin"] = "learner",
        return_path: str = "/home",
    ) -> Response:
        _require_surface_host(request, settings, surface)
        safe_return_path = normalize_return_path(return_path)
        audience = identity_provider.audience
        person_id: UUID | None = None
        async with sessions() as database, database.begin():
            identity = AsyncIdentityApplication(database, token_pepper=token_pepper)
            if authorization_type is ProviderAuthorizationType.LINK:
                token = _session_cookie(request, settings)
                resolved = await identity.resolve_actor(token)
                person_id = resolved.actor.person_id
            issued = await identity.begin_provider_authorization(
                authorization_type,
                audience,
                person_id=person_id,
            )
        transaction = AuthTransaction.from_issued(
            issued,
            surface=surface,
            return_path=safe_return_path,
        )
        redirect_uri = _surface_callback_uri(settings, surface)
        authorization_url = identity_provider.authorization_url(
            transaction,
            redirect_uri=redirect_uri,
        )
        response = RedirectResponse(authorization_url, status_code=status.HTTP_303_SEE_OTHER)
        response.set_cookie(
            settings.oauth_transaction_cookie_name,
            codec.encode(transaction),
            max_age=AUTH_TRANSACTION_MAX_AGE_SECONDS,
            httponly=True,
            secure=settings.secure_cookies,
            samesite="lax",
            path="/v1/auth/google/callback",
        )
        response.headers["cache-control"] = "no-store"
        response.headers["pragma"] = "no-cache"
        return response

    @router.get("/auth/google/callback", name="google_auth_callback")
    async def google_auth_callback(
        request: Request,
        state_value: Annotated[str, Query(alias="state", min_length=32, max_length=160)],
        code: Annotated[str, Query(min_length=1, max_length=4096)],
    ) -> Response:
        encoded_transaction = request.cookies.get(settings.oauth_transaction_cookie_name)
        if encoded_transaction is None:
            raise InvalidAuthTransaction("The sign-in transaction cookie is missing.")
        transaction = codec.decode(encoded_transaction)
        _require_surface_host(request, settings, transaction.surface)
        if not hmac.compare_digest(transaction.state, state_value):
            raise InvalidAuthTransaction("The callback state does not match the transaction.")
        link_session_token = (
            _session_cookie(request, settings)
            if transaction.authorization_type is ProviderAuthorizationType.LINK
            else None
        )
        redirect_uri = _surface_callback_uri(settings, transaction.surface)
        assertion = await identity_provider.exchange_code(
            code,
            transaction,
            callback_state=state_value,
            redirect_uri=redirect_uri,
        )
        session_token: str | None = None
        async with sessions() as database, database.begin():
            identity = AsyncIdentityApplication(database, token_pepper=token_pepper)
            if transaction.authorization_type is ProviderAuthorizationType.REGISTER:
                registered = await identity.register_verified_provider(
                    transaction.transaction_id,
                    assertion,
                    pkce_verifier=transaction.pkce_verifier,
                    display_name=None,
                    user_agent=request.headers.get("user-agent"),
                )
                session_token = registered.session.token
            elif transaction.authorization_type is ProviderAuthorizationType.AUTHENTICATE:
                issued = await identity.authenticate_provider(
                    transaction.transaction_id,
                    assertion,
                    pkce_verifier=transaction.pkce_verifier,
                    user_agent=request.headers.get("user-agent"),
                )
                session_token = issued.token
            else:
                if link_session_token is None:  # pragma: no cover - narrowed above
                    raise AuthenticationRequired("A valid Authority Closers session is required.")
                await identity.link_provider_for_session(
                    link_session_token,
                    transaction.transaction_id,
                    assertion,
                    pkce_verifier=transaction.pkce_verifier,
                )
        base_url = (
            settings.admin_app_url if transaction.surface == "admin" else settings.public_app_url
        )
        response = RedirectResponse(
            f"{str(base_url).rstrip('/')}{transaction.return_path}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
        response.delete_cookie(
            settings.oauth_transaction_cookie_name,
            httponly=True,
            secure=settings.secure_cookies,
            samesite="lax",
            path="/v1/auth/google/callback",
        )
        if session_token is not None:
            _set_session_cookie(response, session_token, settings)
        response.headers["cache-control"] = "no-store"
        response.headers["pragma"] = "no-cache"
        return response

    @router.get("/me", response_model=MeResponse)
    async def me(
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> MeResponse:
        person = await auth.identity.repository.get_person(auth.resolved.actor.person_id)
        if person is None or person.email is None or person.email_verified_at is None:
            raise ResourceNotFound("The authenticated person no longer exists.")
        return MeResponse(
            person_id=person.id,
            email=person.email,
            display_name=person.display_name,
            email_verified_at=person.email_verified_at,
            selected_tenant_id=auth.resolved.actor.tenant_id,
            membership_role=auth.resolved.membership_role,
            permissions=sorted(auth.resolved.actor.permissions),
        )

    @router.get("/context", response_model=ContextResponse)
    async def context(
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> ContextResponse:
        return _context_response(auth.resolved)

    @router.post("/context", response_model=ContextResponse)
    async def select_context(
        request: Request,
        body: SelectContextRequest,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> ContextResponse:
        require_safe_origin(request, settings)
        selected = _with_role_permissions(
            await auth.identity.select_tenant(auth.token, body.tenant_id)
        )
        return _context_response(selected)

    @router.post("/sessions/{session_id}/revoke", response_model=SessionResponse)
    async def revoke_session(
        session_id: UUID,
        request: Request,
        response: Response,
        body: RevokeSessionRequest,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> SessionResponse:
        require_safe_origin(request, settings)
        revoked = await auth.identity.revoke_self(
            auth.token,
            session_id,
            reason=body.reason,
        )
        if session_id == auth.resolved.actor.session_id:
            _delete_session_cookie(response, settings)
        return _session_response(revoked)

    @router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
    async def logout(
        request: Request,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> Response:
        require_safe_origin(request, settings)
        await auth.identity.revoke_self(
            auth.token,
            auth.resolved.actor.session_id,
            reason="user_logout",
        )
        response = Response(status_code=status.HTTP_204_NO_CONTENT)
        _delete_session_cookie(response, settings)
        return response

    application.include_router(router)
    return require_actor


__all__ = [
    "AuthenticatedTransaction",
    "AuthenticationRequired",
    "ContextResponse",
    "MeResponse",
    "RequestOriginDenied",
    "RequireActor",
    "install_identity_http",
    "require_safe_origin",
]
