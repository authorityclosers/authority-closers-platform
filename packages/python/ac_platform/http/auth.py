"""Fail-closed cookie authentication and OAuth callback composition."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Annotated, Literal, cast
from urllib.parse import urlencode, urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ac_platform.application.settings import Settings
from ac_platform.audit.service import AuditRepository
from ac_platform.http.auth_transactions import (
    AUTH_TRANSACTION_MAX_AGE_SECONDS,
    AuthTransaction,
    AuthTransactionCodec,
    InvalidAuthTransaction,
    normalize_return_path,
)
from ac_platform.http.identity_provider import (
    DisabledIdentityProvider,
    IdentityProviderRejected,
    IdentityProviderUnavailable,
    OAuthIdentityProvider,
)
from ac_platform.http.problem import problem_response
from ac_platform.identity.application import (
    AccountDeletionPrivacyHook,
    AsyncIdentityApplication,
    ResolvedActorContext,
)
from ac_platform.identity.models import IdentityCommandIdempotency
from ac_platform.identity.onboarding import (
    LearnerOnboardingService,
    OnboardingConcurrencyError,
    OnboardingNotFound,
    OnboardingSnapshot,
    OnboardingValidationError,
)
from ac_platform.identity.password_auth import (
    PASSWORD_EMAIL_RESET_EVENT,
    PASSWORD_EMAIL_RESET_EVENT_V2,
    PASSWORD_EMAIL_RESET_EVENT_V3,
    PASSWORD_EMAIL_VERIFICATION_EVENT,
    PASSWORD_EMAIL_VERIFICATION_EVENT_V2,
    PASSWORD_EMAIL_VERIFICATION_EVENT_V3,
    EmailVerificationRequired,
    InvalidEmailChallenge,
    InvalidPasswordCredentials,
    PasswordAuthError,
    PasswordIdentityService,
    PasswordPolicyError,
)
from ac_platform.identity.services import AuthorizationDenied as IdentityAuthorizationDenied
from ac_platform.identity.services import (
    IdentityConcurrencyError,
    IdentityResolutionError,
    IdentityServiceError,
    ProviderAuthorizationType,
    ProviderConsentVersionConflictError,
    ProviderIdentityNotLinkedError,
    SessionMetadata,
    SessionNotFoundError,
    TenantScopeDeniedError,
)
from ac_platform.kernel.authz import ActorContext
from ac_platform.kernel.errors import DomainError, ResourceNotFound
from ac_platform.kernel.events import EventCategory, EventEnvelope
from ac_platform.outbox.repository import OutboxRepository
from ac_platform.tenancy.learner_provisioning import (
    AsyncLearnerProvisioningApplication,
    LearnerConsentMissingError,
    LearnerConsentUpdateRequiredError,
    LearnerProvisioningError,
)
from ac_platform.tenancy.models import Membership, MembershipRole, MembershipStatus

SESSION_MAX_AGE_SECONDS = 30 * 24 * 60 * 60
SESSION_COOKIE_VALUE_PATTERN = re.compile(r"[A-Za-z0-9_-]{43,512}\Z")
OAUTH_TRANSACTION_COOKIE_VALUE_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,4000}\.[A-Za-z0-9_-]{43}\Z")
OAUTH_TRANSACTION_COOKIE_SUFFIX_PATTERN = re.compile(r"[A-Za-z0-9_-]{22}\Z")
OAUTH_TRANSACTION_MAX_PENDING = 4
ONBOARDING_IDEMPOTENCY_MARKER = "identity.onboarding_save_idempotency"
ONBOARDING_IDEMPOTENCY_KEY_MAX_LENGTH = 200

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "owner": frozenset(
        {
            "admin_surface",
            "catalog_read",
            "catalog_write",
            "catalog_publish",
            "learner_diagnose",
            "learning_correct",
            "learning_review",
            "enrollment_grant",
            "job_retry",
            "recovery_reconcile",
            "global_job_retry",
            "global_recovery_reconcile",
            "certificate_correct",
            "certificate_revoke",
        }
    ),
    "admin": frozenset(
        {
            "admin_surface",
            "catalog_read",
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


class AdminSurfaceRequired(DomainError):
    code = "admin_surface_required"
    title = "The admin surface is required"
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


class GoogleLinkResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    linked: bool


class WorkspaceChoiceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    name: str = Field(min_length=1, max_length=200)


class WorkspacesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person_id: UUID
    session_id: UUID
    selected_tenant_id: UUID | None
    workspaces: list[WorkspaceChoiceResponse]


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


class PasswordRegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    first_name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=320)
    whatsapp_number: str = Field(min_length=7, max_length=32)
    password: str = Field(min_length=12, max_length=256)
    consent: Literal[True]
    consent_version: str | None = Field(default=None, min_length=1, max_length=64)
    course: Literal["authority-closers-free-course"] | None = None
    activity: UUID | None = None
    next: Literal["/sales-xray"] | None = None

    @model_validator(mode="after")
    def validate_navigation_context(self) -> PasswordRegistrationRequest:
        if self.course is None and self.activity is not None:
            raise ValueError("activity requires an allowlisted course")
        return self


class PasswordLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)


class PasswordRecoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    course: Literal["authority-closers-free-course"] | None = None
    activity: UUID | None = None
    next: Literal["/sales-xray"] | None = None

    @model_validator(mode="after")
    def validate_navigation_context(self) -> PasswordRecoveryRequest:
        if self.course is None and self.activity is not None:
            raise ValueError("activity requires an allowlisted course")
        return self


class PasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=40, max_length=512)
    new_password: str = Field(min_length=12, max_length=256)


class PasswordVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=40, max_length=512)


class PasswordRegistrationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["verification_required"]


class PasswordSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authenticated: Literal[True]
    person_id: UUID
    email: str
    display_name: str | None


class PasswordRecoveryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: Literal[True]


class PasswordResetResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reset: Literal[True]


class OnboardingSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experience_context: str | None = Field(default=None, max_length=64)
    learning_goal: str | None = Field(default=None, max_length=240)
    practice_situation: str | None = Field(default=None, max_length=500)
    weekly_minutes: int | None = Field(default=None, ge=15, le=1200)
    status: Literal["in_progress", "completed", "skipped"]
    current_step: int = Field(ge=1, le=3)


class OnboardingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person_id: UUID
    experience_context: str | None
    learning_goal: str | None
    practice_situation: str | None
    weekly_minutes: int | None
    status: str
    current_step: int
    revision: int
    updated_at: datetime
    next_action_href: str
    next_action_reason: str


class PasswordRequestInvalid(DomainError):
    code = "password_request_invalid"
    title = "The password request is invalid"
    status = 422


def _password_email_event(
    *,
    challenge_id: UUID,
    person_id: UUID,
    kind: str,
    course: str | None = None,
    activity: UUID | None = None,
    next: str | None = None,
) -> EventEnvelope:
    event_names = {
        "email_verification": (
            PASSWORD_EMAIL_VERIFICATION_EVENT,
            PASSWORD_EMAIL_VERIFICATION_EVENT_V2,
            PASSWORD_EMAIL_VERIFICATION_EVENT_V3,
        ),
        "password_reset": (
            PASSWORD_EMAIL_RESET_EVENT,
            PASSWORD_EMAIL_RESET_EVENT_V2,
            PASSWORD_EMAIL_RESET_EVENT_V3,
        ),
    }.get(kind)
    if event_names is None:
        raise PasswordRequestInvalid("unsupported email challenge kind")
    if course is None and activity is not None:
        raise PasswordRequestInvalid("activity requires an allowlisted course")
    if course is not None and course != "authority-closers-free-course":
        raise PasswordRequestInvalid("course is not allowlisted")
    if next is not None and next != "/sales-xray":
        raise PasswordRequestInvalid("next is not allowlisted")
    payload: dict[str, str] = {"challenge_id": str(challenge_id), "kind": kind}
    event_name = event_names[0]
    if course is not None:
        event_name = event_names[1]
        payload["course"] = course
        if activity is not None:
            payload["activity"] = str(activity).lower()
    elif next is not None:
        event_name = event_names[2]
        payload["next"] = next
    return EventEnvelope(
        name=event_name,
        category=EventCategory.OPERATIONAL,
        aggregate_type="person",
        aggregate_id=person_id,
        tenant_id=None,
        payload=payload,
    )


class PasswordRegistrationUnavailable(DomainError):
    code = "password_registration_unavailable"
    title = "Password registration is not available"
    status = 503


class LearnerConsentRequired(DomainError):
    code = "learner_consent_required"
    title = "Learner consent is required"
    status = 400


def _require_current_learner_consent(
    settings: Settings,
    *,
    submitted_version: str | None,
    configured_version: str,
) -> None:
    if (submitted_version is not None and submitted_version != configured_version) or (
        submitted_version is None and settings.environment == "production"
    ):
        raise LearnerConsentRequired(
            "Reload registration and review the current Terms and Privacy Policy before agreeing."
        )


class AdminRegistrationUnavailable(DomainError):
    code = "admin_registration_unavailable"
    title = "Admin self-registration is not available"
    status = 403


class PasswordCredentialsRejected(DomainError):
    code = "password_credentials_rejected"
    title = "The email or password is not valid"
    status = 401


class PasswordEmailVerificationRequired(DomainError):
    code = "email_verification_required"
    title = "Email verification is required"
    status = 403


class PasswordChallengeRejected(DomainError):
    code = "email_challenge_rejected"
    title = "The email link is no longer valid"
    status = 400


class OnboardingRequestInvalid(DomainError):
    code = "onboarding_request_invalid"
    title = "The onboarding profile is invalid"
    status = 422


class OnboardingChanged(DomainError):
    code = "onboarding_changed"
    title = "The onboarding profile changed"
    status = 409


class OnboardingProfileUnavailable(DomainError):
    code = "onboarding_profile_unavailable"
    title = "The onboarding profile is unavailable"
    status = 404


class OnboardingTenantRequired(DomainError):
    code = "tenant_context_required"
    title = "A tenant context is required"
    status = 403


class OnboardingIdempotencyKeyRequired(DomainError):
    code = "idempotency_key_required"
    title = "An idempotency key is required"
    status = 428


class OnboardingIdempotencyConflict(DomainError):
    code = "onboarding_idempotency_conflict"
    title = "The onboarding idempotency key conflicts with an earlier request"
    status = 409


_ONBOARDING_ETAG_PATTERN = re.compile(r'^"onboarding-revision-(?P<revision>0|[1-9][0-9]*)"$')


def _onboarding_revision(if_match: str | None) -> int:
    if if_match is None:
        raise OnboardingRequestInvalid("Onboarding updates require If-Match.")
    match = _ONBOARDING_ETAG_PATTERN.fullmatch(if_match.strip())
    if match is None:
        raise OnboardingRequestInvalid(
            'If-Match must use the canonical "onboarding-revision-N" format.'
        )
    return int(match.group("revision"))


def _onboarding_response(snapshot: OnboardingSnapshot) -> OnboardingResponse:
    return OnboardingResponse(
        person_id=snapshot.person_id,
        experience_context=snapshot.experience_context,
        learning_goal=snapshot.learning_goal,
        practice_situation=snapshot.practice_situation,
        weekly_minutes=snapshot.weekly_minutes,
        status=snapshot.status,
        current_step=snapshot.current_step,
        revision=snapshot.revision,
        updated_at=snapshot.updated_at,
        next_action_href=snapshot.next_action_href,
        next_action_reason=snapshot.next_action_reason,
    )


def _onboarding_idempotency_key(value: str | None) -> str:
    if value is None or not value.strip():
        raise OnboardingIdempotencyKeyRequired(
            "Onboarding updates require an Idempotency-Key header."
        )
    normalized = value.strip()
    if len(normalized) > ONBOARDING_IDEMPOTENCY_KEY_MAX_LENGTH:
        raise OnboardingRequestInvalid("The Idempotency-Key header is too long.")
    try:
        parsed = UUID(normalized)
    except ValueError as error:
        raise OnboardingRequestInvalid(
            "The Idempotency-Key header must be a canonical UUIDv4 value."
        ) from error
    canonical = str(parsed)
    if parsed.version != 4 or normalized.lower() != canonical:
        raise OnboardingRequestInvalid(
            "The Idempotency-Key header must be a canonical UUIDv4 value."
        )
    return canonical


def _onboarding_key_digest(idempotency_key: str) -> str:
    return hashlib.sha256(idempotency_key.encode("ascii")).hexdigest()


def _onboarding_request_digest(
    body: OnboardingSaveRequest,
    *,
    expected_revision: int,
) -> str:
    canonical = json.dumps(
        {
            "operation": "onboarding_save",
            "expected_revision": expected_revision,
            "body": body.model_dump(mode="json"),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _onboarding_request_id(request: Request) -> str | None:
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) else None


async def _find_onboarding_command(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    actor_person_id: UUID,
    key_digest: str,
) -> IdentityCommandIdempotency | None:
    return cast(
        IdentityCommandIdempotency | None,
        await session.scalar(
            select(IdentityCommandIdempotency)
            .where(
                IdentityCommandIdempotency.tenant_id == tenant_id,
                IdentityCommandIdempotency.actor_person_id == actor_person_id,
                IdentityCommandIdempotency.operation == "onboarding_save",
                IdentityCommandIdempotency.key_digest == key_digest,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        ),
    )


async def _claim_onboarding_command(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    actor_person_id: UUID,
    key_digest: str,
    request_digest: str,
) -> tuple[IdentityCommandIdempotency, bool]:
    existing = await _find_onboarding_command(
        session,
        tenant_id=tenant_id,
        actor_person_id=actor_person_id,
        key_digest=key_digest,
    )
    if existing is not None:
        return existing, False
    command = IdentityCommandIdempotency(
        tenant_id=tenant_id,
        actor_person_id=actor_person_id,
        operation="onboarding_save",
        key_digest=key_digest,
        request_digest=request_digest,
        status="pending",
    )
    try:
        async with session.begin_nested():
            session.add(command)
            await session.flush()
    except IntegrityError:
        raced = await _find_onboarding_command(
            session,
            tenant_id=tenant_id,
            actor_person_id=actor_person_id,
            key_digest=key_digest,
        )
        if raced is None:
            raise
        return raced, False
    return command, True


def _onboarding_command_result(
    command: IdentityCommandIdempotency,
    *,
    request_digest: str,
) -> tuple[int, datetime]:
    if command.request_digest != request_digest:
        raise OnboardingIdempotencyConflict(
            "The Idempotency-Key was already used for a different onboarding request."
        )
    if (
        command.status != "completed"
        or command.result_revision is None
        or command.result_updated_at is None
    ):
        raise OnboardingIdempotencyConflict(
            "The onboarding command is still being committed; retry with the same key."
        )
    return command.result_revision, command.result_updated_at


def _require_onboarding_replay_snapshot(
    snapshot: OnboardingSnapshot,
    *,
    result_revision: int,
    result_updated_at: datetime,
) -> None:
    if snapshot.revision != result_revision or snapshot.updated_at != result_updated_at:
        raise OnboardingChanged(
            "The committed onboarding result has since been superseded; refresh before continuing."
        )


async def _complete_onboarding_command(
    session: AsyncSession,
    command: IdentityCommandIdempotency,
    snapshot: OnboardingSnapshot,
) -> None:
    command.status = "completed"
    command.result_revision = snapshot.revision
    command.result_updated_at = snapshot.updated_at
    command.completed_at = snapshot.updated_at
    await session.flush()


async def _append_onboarding_marker(
    auth: AuthenticatedTransaction,
    request: Request,
    *,
    key_digest: str,
    request_digest: str,
    snapshot: OnboardingSnapshot,
) -> None:
    payload: Mapping[str, object] = {
        "operation": "onboarding_save",
        "idempotency_key_digest": key_digest,
        "request_digest": request_digest,
        "result_person_id": str(snapshot.person_id),
        "result_revision": snapshot.revision,
        "result_updated_at": snapshot.updated_at.isoformat(),
    }
    await AuditRepository(auth.database).append_for_actor(
        auth.resolved.actor,
        action=ONBOARDING_IDEMPOTENCY_MARKER,
        resource_type="learner_onboarding_profile",
        resource_id=snapshot.person_id,
        payload=payload,
        request_id=_onboarding_request_id(request),
    )


def _set_onboarding_response_headers(response: Response, snapshot: OnboardingSnapshot) -> None:
    response.headers["etag"] = f'"onboarding-revision-{snapshot.revision}"'
    response.headers["cache-control"] = "private, no-store"


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


def require_admin_surface(request: Request, settings: Settings) -> None:
    """Keep privileged routes behind the configured admin-host ingress boundary."""

    if request.url.hostname != settings.admin_app_url.host:
        raise AdminSurfaceRequired(
            "Admin operations are available only through the configured admin host."
        )


def require_safe_origin(request: Request, settings: Settings) -> None:
    origin = request.headers.get("origin")
    normalized_origin = None if origin is None else origin.rstrip("/")
    if normalized_origin not in settings.allowed_origins:
        raise RequestOriginDenied("Cookie-authenticated state changes require an allowed Origin.")
    coach_origin = str(settings.coach_app_url).rstrip("/")
    sales_origin = (
        str(settings.sales_xray_app_url).rstrip("/")
        if settings.sales_xray_app_url is not None
        else None
    )
    sales_host = settings.sales_xray_app_url.host if settings.sales_xray_app_url else None
    if (
        settings.environment not in {"staging", "production"}
        and request.url.hostname != settings.coach_app_url.host
        and normalized_origin != coach_origin
        and request.url.hostname != sales_host
        and normalized_origin != sales_origin
    ):
        return

    expected_origin = None
    if request.url.hostname == settings.public_app_url.host:
        expected_origin = str(settings.public_app_url).rstrip("/")
    elif request.url.hostname == settings.admin_app_url.host:
        expected_origin = str(settings.admin_app_url).rstrip("/")
    elif request.url.hostname == settings.coach_app_url.host:
        expected_origin = coach_origin
    elif sales_host is not None and request.url.hostname == sales_host:
        expected_origin = sales_origin
    if normalized_origin != expected_origin:
        raise RequestOriginDenied(
            "Cookie-authenticated state changes require a same-surface Origin."
        )


class _InvalidRawCookie(ValueError):
    """A security-sensitive cookie is missing, duplicated, or malformed."""


def _single_raw_cookie(
    request: Request,
    *,
    name: str,
    pattern: re.Pattern[str],
    required: bool,
) -> str | None:
    values: list[str] = []
    for raw_name, raw_value in request.scope.get("headers", []):
        if raw_name.lower() != b"cookie":
            continue
        for segment in raw_value.decode("latin-1").split(";"):
            pair = segment.strip()
            separator = pair.find("=")
            if separator < 1:
                if pair == name:
                    raise _InvalidRawCookie
                continue
            raw_cookie_name = pair[:separator]
            if raw_cookie_name.strip() != name:
                continue
            if raw_cookie_name != name:
                raise _InvalidRawCookie
            values.append(pair[separator + 1 :])

    if not values and not required:
        return None
    if len(values) != 1 or pattern.fullmatch(values[0]) is None:
        raise _InvalidRawCookie
    return values[0]


def _session_cookie(request: Request, settings: Settings, *, required: bool = True) -> str | None:
    try:
        token = _single_raw_cookie(
            request,
            name=settings.session_cookie_name,
            pattern=SESSION_COOKIE_VALUE_PATTERN,
            required=required,
        )
    except _InvalidRawCookie:
        raise AuthenticationRequired("A valid Authority Closers session is required.") from None
    return token


def _read_oauth_transaction_cookie(
    request: Request,
    settings: Settings,
    *,
    name: str,
    required: bool,
) -> str | None:
    try:
        encoded = _single_raw_cookie(
            request,
            name=name,
            pattern=OAUTH_TRANSACTION_COOKIE_VALUE_PATTERN,
            required=required,
        )
    except _InvalidRawCookie:
        raise InvalidAuthTransaction("The sign-in transaction cookie is invalid.") from None
    if encoded is None and required:
        raise InvalidAuthTransaction("The sign-in transaction cookie is invalid.")
    return encoded


def _oauth_transaction_cookie(request: Request, settings: Settings) -> str:
    encoded = _read_oauth_transaction_cookie(
        request,
        settings,
        name=settings.oauth_transaction_cookie_name,
        required=True,
    )
    if encoded is None:  # pragma: no cover - required=True narrows this value
        raise InvalidAuthTransaction("The sign-in transaction cookie is invalid.")
    return encoded


def _oauth_transaction_cookie_name(settings: Settings, state: str) -> str:
    digest = hashlib.sha256(state.encode("utf-8")).digest()[:16]
    suffix = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return f"{settings.oauth_transaction_cookie_name}.{suffix}"


def _callback_oauth_transaction_cookie(
    request: Request,
    settings: Settings,
    *,
    state: str,
) -> tuple[str, str]:
    state_cookie_name = _oauth_transaction_cookie_name(settings, state)
    encoded = _read_oauth_transaction_cookie(
        request,
        settings,
        name=state_cookie_name,
        required=False,
    )
    if encoded is not None:
        return state_cookie_name, encoded
    return settings.oauth_transaction_cookie_name, _oauth_transaction_cookie(request, settings)


def _pending_oauth_transaction_cookies(
    request: Request,
    settings: Settings,
) -> dict[str, list[str]]:
    prefix = f"{settings.oauth_transaction_cookie_name}."
    values: dict[str, list[str]] = {}
    for raw_name, raw_value in request.scope.get("headers", []):
        if raw_name.lower() != b"cookie":
            continue
        for segment in raw_value.decode("latin-1").split(";"):
            pair = segment.strip()
            separator = pair.find("=")
            if separator < 1:
                continue
            cookie_name = pair[:separator]
            if cookie_name != cookie_name.strip() or not cookie_name.startswith(prefix):
                continue
            suffix = cookie_name.removeprefix(prefix)
            if OAUTH_TRANSACTION_COOKIE_SUFFIX_PATTERN.fullmatch(suffix) is None:
                continue
            values.setdefault(cookie_name, []).append(pair[separator + 1 :])
    return values


def _set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    if SESSION_COOKIE_VALUE_PATTERN.fullmatch(token) is None:
        raise RuntimeError("Refusing to set a malformed session cookie.")
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


def _set_oauth_transaction_cookie(
    response: Response,
    encoded_transaction: str,
    settings: Settings,
    *,
    state: str,
) -> None:
    if OAUTH_TRANSACTION_COOKIE_VALUE_PATTERN.fullmatch(encoded_transaction) is None:
        raise RuntimeError("Refusing to set a malformed OAuth transaction cookie.")
    for name in (
        settings.oauth_transaction_cookie_name,
        _oauth_transaction_cookie_name(settings, state),
    ):
        response.set_cookie(
            name,
            encoded_transaction,
            max_age=AUTH_TRANSACTION_MAX_AGE_SECONDS,
            httponly=True,
            secure=settings.secure_cookies,
            samesite="lax",
            path="/",
        )


def _delete_oauth_transaction_cookie(
    response: Response,
    settings: Settings,
    *,
    name: str | None = None,
) -> None:
    response.delete_cookie(
        name or settings.oauth_transaction_cookie_name,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )


def _prune_oauth_transaction_cookies(
    request: Request,
    response: Response,
    settings: Settings,
    codec: AuthTransactionCodec,
) -> None:
    valid: list[tuple[int, str]] = []
    for name, values in _pending_oauth_transaction_cookies(request, settings).items():
        if len(values) != 1 or OAUTH_TRANSACTION_COOKIE_VALUE_PATTERN.fullmatch(values[0]) is None:
            _delete_oauth_transaction_cookie(response, settings, name=name)
            continue
        try:
            transaction = codec.decode(values[0])
        except InvalidAuthTransaction:
            _delete_oauth_transaction_cookie(response, settings, name=name)
            continue
        expected_name = _oauth_transaction_cookie_name(settings, transaction.state)
        if not hmac.compare_digest(name, expected_name):
            _delete_oauth_transaction_cookie(response, settings, name=name)
            continue
        valid.append((transaction.issued_at, name))

    valid.sort(reverse=True)
    for _, name in valid[OAUTH_TRANSACTION_MAX_PENDING - 1 :]:
        _delete_oauth_transaction_cookie(response, settings, name=name)


def _oauth_transaction_cookie_names_to_clear(
    request: Request,
    settings: Settings,
    *,
    selected_name: str,
    selected_value: str,
) -> tuple[str, ...]:
    if selected_name == settings.oauth_transaction_cookie_name:
        return (selected_name,)
    compatibility_value = _read_oauth_transaction_cookie(
        request,
        settings,
        name=settings.oauth_transaction_cookie_name,
        required=False,
    )
    if compatibility_value is not None and hmac.compare_digest(
        compatibility_value,
        selected_value,
    ):
        return (settings.oauth_transaction_cookie_name, selected_name)
    return (selected_name,)


def _delete_oauth_transaction_cookies(
    response: Response,
    settings: Settings,
    names: tuple[str, ...],
) -> None:
    for name in names:
        _delete_oauth_transaction_cookie(response, settings, name=name)


def _oauth_callback_failure_cookie_names(
    request: Request,
    settings: Settings,
    *,
    state: str,
) -> tuple[str, ...]:
    """Select only the failed callback transaction cookies for deletion.

    A state-keyed cookie is authoritative when present.  The compatibility
    cookie is deleted with it only when both carry the same signed value, so a
    failed callback cannot consume a different transaction opened in another
    tab.
    """

    state_cookie_name = _oauth_transaction_cookie_name(settings, state)
    try:
        state_cookie_value = _read_oauth_transaction_cookie(
            request,
            settings,
            name=state_cookie_name,
            required=False,
        )
    except InvalidAuthTransaction:
        return (state_cookie_name,)
    if state_cookie_value is not None:
        try:
            return _oauth_transaction_cookie_names_to_clear(
                request,
                settings,
                selected_name=state_cookie_name,
                selected_value=state_cookie_value,
            )
        except InvalidAuthTransaction:
            return (state_cookie_name,)

    try:
        compatibility_value = _read_oauth_transaction_cookie(
            request,
            settings,
            name=settings.oauth_transaction_cookie_name,
            required=False,
        )
    except InvalidAuthTransaction:
        return (settings.oauth_transaction_cookie_name,)
    if compatibility_value is not None:
        return (settings.oauth_transaction_cookie_name,)
    return (state_cookie_name,)


def _invalid_oauth_callback_response(
    request: Request,
    settings: Settings,
    error: InvalidAuthTransaction,
    *,
    transaction_cookie_names: tuple[str, ...],
) -> JSONResponse:
    response = problem_response(
        request=request,
        status_code=error.status,
        code=error.code,
        title=error.title,
        detail=error.detail,
    )
    _delete_oauth_transaction_cookies(response, settings, transaction_cookie_names)
    response.headers["cache-control"] = "no-store"
    response.headers["pragma"] = "no-cache"
    return response


def _oauth_terminal_problem_response(
    request: Request,
    settings: Settings,
    error: DomainError,
    *,
    transaction_cookie_names: tuple[str, ...],
) -> JSONResponse:
    response = problem_response(
        request=request,
        status_code=error.status,
        code=error.code,
        title=error.title,
        detail=error.detail,
    )
    _delete_oauth_transaction_cookies(response, settings, transaction_cookie_names)
    response.headers["cache-control"] = "no-store"
    response.headers["pragma"] = "no-cache"
    return response


def _oauth_callback_unavailable_response(
    request: Request,
    settings: Settings,
    *,
    transaction_cookie_names: tuple[str, ...],
) -> JSONResponse:
    response = problem_response(
        request=request,
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        code="oauth_callback_unavailable",
        title="Sign-in could not be completed",
        detail="The sign-in transaction could not be completed. Start a new sign-in attempt.",
    )
    _delete_oauth_transaction_cookies(response, settings, transaction_cookie_names)
    response.headers["cache-control"] = "no-store"
    response.headers["pragma"] = "no-cache"
    return response


async def _oauth_identity_problem_response(
    request: Request,
    settings: Settings,
    error: IdentityServiceError,
    *,
    transaction_cookie_names: tuple[str, ...],
) -> JSONResponse:
    response = await identity_error_handler(request, error)
    _delete_oauth_transaction_cookies(response, settings, transaction_cookie_names)
    response.headers["cache-control"] = "no-store"
    response.headers["pragma"] = "no-cache"
    return response


def _surface_origin(settings: Settings, surface: str) -> str:
    values = {
        "learner": settings.public_app_url,
        "admin": settings.admin_app_url,
        "coach": settings.coach_app_url,
    }
    if settings.sales_xray_app_url is not None:
        values["sales_xray"] = settings.sales_xray_app_url
    if surface not in values:
        raise InvalidAuthTransaction("The requested application surface is not allowed.")
    value = values[surface]
    return str(value).rstrip("/")


def _surface_callback_uri(settings: Settings, surface: str) -> str:
    return f"{_surface_origin(settings, surface)}/v1/auth/google/callback"


# Navigation context only; these destinations do not grant enrollment or access.
_LEARNER_COURSE_INTENT = "authority-closers-free-course"
_LEARNER_COURSE_RETURN_PATHS = frozenset(
    f"{path}?course={_LEARNER_COURSE_INTENT}" for path in ("/home", "/onboarding")
)
_LEARNER_SALES_RETURN_PATH = "/onboarding?next=/sales-xray"
_LEARNER_ACTIVITY_RETURN_PATH = re.compile(
    r"/onboarding\?(?:course=(?P<course>authority-closers-free-course)&)?"
    r"activity=(?P<activity>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
)


def _learner_oauth_recovery_response(
    settings: Settings,
    *,
    result: Literal[
        "consent_required",
        "consent_update_required",
        "provider_rejected",
        "provider_unavailable",
        "registration_required",
    ],
    transaction_cookie_names: tuple[str, ...],
    transaction_return_path: str | None = None,
) -> Response:
    parameters: dict[str, str] = {"result": result}
    if transaction_return_path == _LEARNER_SALES_RETURN_PATH:
        parameters["next"] = "/sales-xray"
    if transaction_return_path in _LEARNER_COURSE_RETURN_PATHS:
        parameters["course"] = _LEARNER_COURSE_INTENT
    activity_return = _LEARNER_ACTIVITY_RETURN_PATH.fullmatch(transaction_return_path or "")
    if activity_return:
        parameters["activity"] = activity_return["activity"]
        if activity_return["course"]:
            parameters["course"] = _LEARNER_COURSE_INTENT
    location = f"{_surface_origin(settings, 'learner')}/auth/callback?{urlencode(parameters)}"
    response = RedirectResponse(location, status_code=status.HTTP_303_SEE_OTHER)
    _delete_oauth_transaction_cookies(response, settings, transaction_cookie_names)
    response.headers["cache-control"] = "no-store"
    response.headers["pragma"] = "no-cache"
    return response


def _require_surface_host(request: Request, settings: Settings, surface: str) -> None:
    if (
        settings.environment not in {"staging", "production"}
        and surface not in {"coach", "sales_xray"}
        and request.url.hostname != settings.coach_app_url.host
        and request.url.hostname
        != (settings.sales_xray_app_url.host if settings.sales_xray_app_url else None)
    ):
        return
    expected_host = urlsplit(_surface_origin(settings, surface)).hostname
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
    elif isinstance(error, IdentityAuthorizationDenied | IdentityResolutionError):
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
    account_deletion_hook: AccountDeletionPrivacyHook | None = None,
) -> RequireActor:
    """Install identity routes around one caller-owned database transaction."""

    identity_provider = provider or DisabledIdentityProvider()
    codec = AuthTransactionCodec(settings.oauth_transaction_secret.get_secret_value())
    token_pepper = settings.session_token_pepper.get_secret_value()
    challenge_secret = settings.email_challenge_secret.get_secret_value()
    router = APIRouter(prefix="/v1", tags=["identity"])
    application.add_exception_handler(IdentityServiceError, identity_error_handler)  # type: ignore[arg-type]

    def _identity(database: AsyncSession) -> AsyncIdentityApplication:
        """Construct identity without widening legacy test/provider adapters."""

        if account_deletion_hook is None:
            return AsyncIdentityApplication(database, token_pepper=token_pepper)
        return AsyncIdentityApplication(
            database,
            token_pepper=token_pepper,
            account_deletion_hook=account_deletion_hook,
        )

    async def require_actor(request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        token = _session_cookie(request, settings)
        if token is None:  # pragma: no cover - required session cookie narrows this value
            raise AuthenticationRequired("A valid Authority Closers session is required.")
        async with sessions() as database, database.begin():
            identity = _identity(database)
            resolved = _with_role_permissions(await identity.resolve_actor(token))
            yield AuthenticatedTransaction(
                database=database,
                identity=identity,
                resolved=resolved,
                token=token,
            )

    actor_dependency = Depends(require_actor)

    async def enqueue_password_email(
        database: AsyncSession,
        *,
        challenge_id: UUID,
        person_id: UUID,
        kind: str,
        course: str | None = None,
        activity: UUID | None = None,
        next: str | None = None,
    ) -> None:
        await OutboxRepository(database).enqueue(
            _password_email_event(
                challenge_id=challenge_id,
                person_id=person_id,
                kind=kind,
                course=course,
                activity=activity,
                next=next,
            ),
            dedupe_key=f"identity-email:{kind}:{challenge_id}",
        )

    async def ensure_public_learner(database: AsyncSession, person_id: UUID) -> UUID:
        tenant_id = settings.public_learner_tenant_id
        consent_version = (settings.learner_consent_version or "").strip()
        if tenant_id is None or not consent_version:
            raise PasswordRegistrationUnavailable(
                "Reviewed learner consent and the public learner context must be configured."
            )
        try:
            await AsyncLearnerProvisioningApplication(database).ensure(
                person_id=person_id,
                tenant_id=tenant_id,
                required_consent_version=consent_version,
            )
        except LearnerProvisioningError as error:
            raise PasswordRegistrationUnavailable(str(error)) from error
        return tenant_id

    @router.post(
        "/auth/password/register",
        response_model=PasswordRegistrationResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def register_password(
        request: Request,
        response: Response,
        body: PasswordRegistrationRequest,
    ) -> PasswordRegistrationResponse:
        require_safe_origin(request, settings)
        consent_version = (settings.learner_consent_version or "").strip()
        if not consent_version or settings.public_learner_tenant_id is None:
            raise PasswordRegistrationUnavailable(
                "Reviewed learner consent and the public learner context must be configured."
            )
        _require_current_learner_consent(
            settings,
            submitted_version=body.consent_version,
            configured_version=consent_version,
        )
        try:
            async with sessions() as database, database.begin():
                registration = await PasswordIdentityService(
                    database, token_secret=challenge_secret
                ).register(
                    email=body.email,
                    first_name=body.first_name,
                    whatsapp_number=body.whatsapp_number,
                    password=body.password,
                    consent_version=consent_version,
                )
                if registration.created and registration.challenge is not None:
                    await enqueue_password_email(
                        database,
                        challenge_id=registration.challenge.challenge_id,
                        person_id=registration.challenge.person_id,
                        kind=registration.challenge.kind.value,
                        course=body.course,
                        activity=body.activity,
                        next=body.next,
                    )
        except (PasswordAuthError, ValueError) as error:
            raise PasswordRequestInvalid(str(error)) from error
        # Deliberately identical for new and existing addresses.
        response.headers["cache-control"] = "no-store"
        return PasswordRegistrationResponse(status="verification_required")

    @router.post("/auth/password/login", response_model=PasswordSessionResponse)
    async def login_password(
        request: Request,
        response: Response,
        body: PasswordLoginRequest,
    ) -> PasswordSessionResponse:
        require_safe_origin(request, settings)
        try:
            async with sessions() as database, database.begin():
                person = await PasswordIdentityService(
                    database, token_secret=challenge_secret
                ).authenticate(email=body.email, password=body.password)
                identity = _identity(database)
                issued = await identity.issue_authenticated_session(
                    person.id,
                    user_agent=request.headers.get("user-agent"),
                    ip_address=request.client.host if request.client else None,
                )
                tenant_id = settings.public_learner_tenant_id
                if tenant_id is not None:
                    membership = await database.scalar(
                        select(Membership).where(
                            Membership.tenant_id == tenant_id,
                            Membership.person_id == person.id,
                            Membership.role == MembershipRole.LEARNER.value,
                            Membership.status == MembershipStatus.ACTIVE.value,
                        )
                    )
                    if membership is not None:
                        await identity.select_tenant(issued.token, tenant_id)
        except EmailVerificationRequired as error:
            raise PasswordEmailVerificationRequired(str(error)) from error
        except (InvalidPasswordCredentials, ValueError) as error:
            raise PasswordCredentialsRejected("email or password is not valid") from error
        _set_session_cookie(response, issued.token, settings)
        response.headers["cache-control"] = "no-store"
        return PasswordSessionResponse(
            authenticated=True,
            person_id=person.id,
            email=person.email or "",
            display_name=person.display_name,
        )

    @router.post("/auth/password/recovery", response_model=PasswordRecoveryResponse)
    async def recover_password(
        request: Request,
        response: Response,
        body: PasswordRecoveryRequest,
    ) -> PasswordRecoveryResponse:
        require_safe_origin(request, settings)
        try:
            async with sessions() as database, database.begin():
                passwords = PasswordIdentityService(database, token_secret=challenge_secret)
                challenge = await passwords.begin_reset(email=body.email)
                if challenge is None:
                    # Recovery must also help a password account whose first
                    # verification email was missed. This remains a mailbox
                    # challenge, never a verification flag or a reset bypass.
                    # Ineligible/unknown addresses keep the same public reply.
                    challenge = await passwords.begin_verification(email=body.email)
                if challenge is not None:
                    await enqueue_password_email(
                        database,
                        challenge_id=challenge.challenge_id,
                        person_id=challenge.person_id,
                        kind=challenge.kind.value,
                        course=body.course,
                        activity=body.activity,
                        next=body.next,
                    )
        except (PasswordAuthError, ValueError):
            pass
        response.headers["cache-control"] = "no-store"
        return PasswordRecoveryResponse(accepted=True)

    @router.post(
        "/auth/password/resend-verification",
        response_model=PasswordRecoveryResponse,
    )
    async def resend_password_verification(
        request: Request,
        response: Response,
        body: PasswordRecoveryRequest,
    ) -> PasswordRecoveryResponse:
        require_safe_origin(request, settings)
        try:
            async with sessions() as database, database.begin():
                challenge = await PasswordIdentityService(
                    database, token_secret=challenge_secret
                ).begin_verification(email=body.email)
                if challenge is not None:
                    await enqueue_password_email(
                        database,
                        challenge_id=challenge.challenge_id,
                        person_id=challenge.person_id,
                        kind=challenge.kind.value,
                        course=body.course,
                        activity=body.activity,
                        next=body.next,
                    )
        except (PasswordAuthError, ValueError):
            pass
        response.headers["cache-control"] = "no-store"
        return PasswordRecoveryResponse(accepted=True)

    @router.post("/auth/password/verify", response_model=PasswordSessionResponse)
    async def verify_password_email(
        request: Request,
        response: Response,
        body: PasswordVerifyRequest,
    ) -> PasswordSessionResponse:
        require_safe_origin(request, settings)
        try:
            async with sessions() as database, database.begin():
                person = await PasswordIdentityService(
                    database, token_secret=challenge_secret
                ).consume_verification(body.token)
                tenant_id = await ensure_public_learner(database, person.id)
                identity = _identity(database)
                issued = await identity.issue_authenticated_session(
                    person.id,
                    user_agent=request.headers.get("user-agent"),
                    ip_address=request.client.host if request.client else None,
                )
                await identity.select_tenant(issued.token, tenant_id)
        except (InvalidEmailChallenge, ValueError) as error:
            raise PasswordChallengeRejected(str(error)) from error
        _set_session_cookie(response, issued.token, settings)
        response.headers["cache-control"] = "no-store"
        return PasswordSessionResponse(
            authenticated=True,
            person_id=person.id,
            email=person.email or "",
            display_name=person.display_name,
        )

    @router.post("/auth/password/reset", response_model=PasswordResetResponse)
    async def reset_password(
        request: Request,
        response: Response,
        body: PasswordResetRequest,
    ) -> PasswordResetResponse:
        require_safe_origin(request, settings)
        try:
            async with sessions() as database, database.begin():
                await PasswordIdentityService(
                    database, token_secret=challenge_secret
                ).consume_reset(body.token, body.new_password)
        except PasswordPolicyError as error:
            raise PasswordRequestInvalid(str(error)) from error
        except (InvalidEmailChallenge, ValueError) as error:
            raise PasswordChallengeRejected(str(error)) from error
        response.headers["cache-control"] = "no-store"
        return PasswordResetResponse(reset=True)

    @router.get("/onboarding", response_model=OnboardingResponse)
    async def get_onboarding(
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> OnboardingResponse:
        try:
            snapshot = await LearnerOnboardingService(auth.database).get(
                auth.resolved.actor.person_id
            )
        except OnboardingNotFound as error:
            raise OnboardingProfileUnavailable(str(error)) from error
        _set_onboarding_response_headers(response, snapshot)
        return _onboarding_response(snapshot)

    @router.put("/onboarding", response_model=OnboardingResponse)
    async def save_onboarding(
        request: Request,
        response: Response,
        body: OnboardingSaveRequest,
        if_match: Annotated[str | None, Header(alias="If-Match", max_length=96)] = None,
        idempotency_key: Annotated[
            str | None,
            Header(
                alias="Idempotency-Key",
                max_length=ONBOARDING_IDEMPOTENCY_KEY_MAX_LENGTH,
            ),
        ] = None,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> OnboardingResponse:
        require_safe_origin(request, settings)
        expected_revision = _onboarding_revision(if_match)
        command_key = _onboarding_idempotency_key(idempotency_key)
        command_key_digest = _onboarding_key_digest(command_key)
        request_digest = _onboarding_request_digest(
            body,
            expected_revision=expected_revision,
        )
        actor = auth.resolved.actor
        tenant_id = actor.tenant_id
        if tenant_id is None:
            raise OnboardingTenantRequired(
                "Select an active learner tenant before saving onboarding."
            )
        command, claimed = await _claim_onboarding_command(
            auth.database,
            tenant_id=tenant_id,
            actor_person_id=actor.person_id,
            key_digest=command_key_digest,
            request_digest=request_digest,
        )
        if not claimed:
            result_revision, result_updated_at = _onboarding_command_result(
                command,
                request_digest=request_digest,
            )
            try:
                snapshot = await LearnerOnboardingService(auth.database).get(
                    actor.person_id,
                    lock=True,
                )
            except OnboardingNotFound as error:
                raise OnboardingProfileUnavailable(str(error)) from error
            _require_onboarding_replay_snapshot(
                snapshot,
                result_revision=result_revision,
                result_updated_at=result_updated_at,
            )
            _set_onboarding_response_headers(response, snapshot)
            return _onboarding_response(snapshot)
        try:
            snapshot = await LearnerOnboardingService(auth.database).save(
                actor.person_id,
                expected_revision=expected_revision,
                experience_context=body.experience_context,
                learning_goal=body.learning_goal,
                practice_situation=body.practice_situation,
                weekly_minutes=body.weekly_minutes,
                status=body.status,
                current_step=body.current_step,
            )
        except OnboardingConcurrencyError as error:
            raise OnboardingChanged(str(error)) from error
        except OnboardingValidationError as error:
            raise OnboardingRequestInvalid(str(error)) from error
        except OnboardingNotFound as error:
            raise OnboardingProfileUnavailable(str(error)) from error
        await _complete_onboarding_command(auth.database, command, snapshot)
        await _append_onboarding_marker(
            auth,
            request,
            key_digest=command_key_digest,
            request_digest=request_digest,
            snapshot=snapshot,
        )
        _set_onboarding_response_headers(response, snapshot)
        return _onboarding_response(snapshot)

    @router.get("/auth/google/start", name="google_auth_start")
    async def google_auth_start(
        request: Request,
        authorization_type: Annotated[ProviderAuthorizationType, Query(alias="action")],
        surface: Literal["learner", "admin", "coach", "sales_xray"] = "learner",
        return_path: str = "/home",
        consent: bool = False,
        client_consent_version: Annotated[
            str | None, Query(alias="consent_version", min_length=1, max_length=64)
        ] = None,
    ) -> Response:
        _require_surface_host(request, settings, surface)
        safe_return_path = normalize_return_path(return_path)
        if surface == "sales_xray" and authorization_type is ProviderAuthorizationType.LINK:
            raise InvalidAuthTransaction(
                "Manage linked identities through your Academy account settings."
            )
        if (
            surface == "sales_xray"
            and authorization_type is ProviderAuthorizationType.AUTHENTICATE
            and consent
        ):
            # One consent-aware Google button serves new and existing people.
            # REGISTER already resolves a linked provider key to the same person;
            # it never links another person's account by an email match.
            authorization_type = ProviderAuthorizationType.REGISTER
        if (
            surface in {"admin", "coach"}
            and authorization_type is ProviderAuthorizationType.REGISTER
        ):
            raise AdminRegistrationUnavailable(
                "Studio and admin identities must be provisioned through the reviewed identity "
                "and membership bootstrap path before they can sign in with Google."
            )
        if (
            surface in {"learner", "sales_xray"}
            and authorization_type is ProviderAuthorizationType.REGISTER
        ):
            if not consent:
                raise LearnerConsentRequired(
                    "Explicit learner consent is required before Google registration."
                )
            if surface == "sales_xray" and client_consent_version is None:
                raise LearnerConsentRequired(
                    "Review the current Academy Terms and Privacy Policy before continuing."
                )
            consent_version = (settings.learner_consent_version or "").strip()
            if settings.public_learner_tenant_id is None or not consent_version:
                raise PasswordRegistrationUnavailable(
                    "Reviewed learner consent and the public learner context must be configured."
                )
            _require_current_learner_consent(
                settings,
                submitted_version=client_consent_version,
                configured_version=consent_version,
            )
        else:
            consent_version = None
        audience = identity_provider.audience
        person_id: UUID | None = None
        async with sessions() as database, database.begin():
            identity = _identity(database)
            if authorization_type is ProviderAuthorizationType.LINK:
                token = _session_cookie(request, settings)
                if token is None:  # pragma: no cover - required session cookie narrows this value
                    raise AuthenticationRequired("A valid Authority Closers session is required.")
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
            consent_version=consent_version,
        )
        redirect_uri = _surface_callback_uri(settings, surface)
        authorization_url = identity_provider.authorization_url(
            transaction,
            redirect_uri=redirect_uri,
        )
        response = RedirectResponse(authorization_url, status_code=status.HTTP_303_SEE_OTHER)
        _prune_oauth_transaction_cookies(request, response, settings, codec)
        _set_oauth_transaction_cookie(
            response,
            codec.encode(transaction),
            settings,
            state=transaction.state,
        )
        response.headers["cache-control"] = "no-store"
        response.headers["pragma"] = "no-cache"
        return response

    @router.get("/auth/google/callback", name="google_auth_callback")
    async def google_auth_callback(
        request: Request,
        state_value: Annotated[str, Query(alias="state", min_length=32, max_length=160)],
        code: Annotated[str | None, Query(min_length=1, max_length=4096)] = None,
        provider_error: Annotated[
            str | None,
            Query(alias="error", min_length=1, max_length=200),
        ] = None,
    ) -> Response:
        transaction_cookie_names: tuple[str, ...] = ()
        try:
            transaction_cookie_name, encoded_transaction = _callback_oauth_transaction_cookie(
                request,
                settings,
                state=state_value,
            )
            transaction_cookie_names = _oauth_transaction_cookie_names_to_clear(
                request,
                settings,
                selected_name=transaction_cookie_name,
                selected_value=encoded_transaction,
            )
            transaction = codec.decode(encoded_transaction)
            _require_surface_host(request, settings, transaction.surface)
            if (
                transaction.surface == "sales_xray"
                and transaction.authorization_type is ProviderAuthorizationType.LINK
            ):
                raise InvalidAuthTransaction("Link identities through Academy account settings.")
            if not hmac.compare_digest(transaction.state, state_value):
                raise InvalidAuthTransaction("The callback state does not match the transaction.")
        except InvalidAuthTransaction as error:
            if not transaction_cookie_names:
                transaction_cookie_names = _oauth_callback_failure_cookie_names(
                    request,
                    settings,
                    state=state_value,
                )
            return _invalid_oauth_callback_response(
                request,
                settings,
                error,
                transaction_cookie_names=transaction_cookie_names,
            )
        if provider_error is not None:
            if transaction.surface == "learner":
                return _learner_oauth_recovery_response(
                    settings,
                    result="provider_rejected",
                    transaction_cookie_names=transaction_cookie_names,
                    transaction_return_path=transaction.return_path,
                )
            return _oauth_terminal_problem_response(
                request,
                settings,
                IdentityProviderRejected("The identity provider stopped the sign-in attempt."),
                transaction_cookie_names=transaction_cookie_names,
            )
        if code is None:
            return _invalid_oauth_callback_response(
                request,
                settings,
                InvalidAuthTransaction("The callback authorization code is missing."),
                transaction_cookie_names=transaction_cookie_names,
            )
        try:
            presented_session_token = _session_cookie(request, settings, required=False)
        except AuthenticationRequired as error:
            return _oauth_terminal_problem_response(
                request,
                settings,
                error,
                transaction_cookie_names=transaction_cookie_names,
            )
        if (
            transaction.surface in {"learner", "sales_xray"}
            and transaction.authorization_type is ProviderAuthorizationType.REGISTER
        ):
            required_consent_version = (settings.learner_consent_version or "").strip()
            if (
                not transaction.consent_version
                or not required_consent_version
                or not hmac.compare_digest(
                    transaction.consent_version,
                    required_consent_version,
                )
            ):
                return _oauth_terminal_problem_response(
                    request,
                    settings,
                    PasswordRegistrationUnavailable(
                        "The learner consent version is no longer available for this registration."
                    ),
                    transaction_cookie_names=transaction_cookie_names,
                )
        link_session_token = presented_session_token
        if (
            transaction.authorization_type is ProviderAuthorizationType.LINK
            and link_session_token is None
        ):
            return _oauth_terminal_problem_response(
                request,
                settings,
                AuthenticationRequired("A valid Authority Closers session is required."),
                transaction_cookie_names=transaction_cookie_names,
            )
        redirect_uri = _surface_callback_uri(settings, transaction.surface)
        try:
            assertion = await identity_provider.exchange_code(
                code,
                transaction,
                callback_state=state_value,
                redirect_uri=redirect_uri,
            )
        except IdentityProviderRejected:
            if transaction.surface == "learner":
                return _learner_oauth_recovery_response(
                    settings,
                    result="provider_rejected",
                    transaction_cookie_names=transaction_cookie_names,
                    transaction_return_path=transaction.return_path,
                )
            return _oauth_terminal_problem_response(
                request,
                settings,
                IdentityProviderRejected("The identity provider rejected the sign-in attempt."),
                transaction_cookie_names=transaction_cookie_names,
            )
        except IdentityProviderUnavailable:
            if transaction.surface == "learner":
                return _learner_oauth_recovery_response(
                    settings,
                    result="provider_unavailable",
                    transaction_cookie_names=transaction_cookie_names,
                    transaction_return_path=transaction.return_path,
                )
            return _oauth_terminal_problem_response(
                request,
                settings,
                IdentityProviderUnavailable("The identity provider is temporarily unavailable."),
                transaction_cookie_names=transaction_cookie_names,
            )
        session_token: str | None = None
        try:
            async with sessions() as database, database.begin():
                identity = _identity(database)
                if transaction.authorization_type is ProviderAuthorizationType.REGISTER:
                    registered = await identity.register_verified_provider(
                        transaction.transaction_id,
                        assertion,
                        pkce_verifier=transaction.pkce_verifier,
                        consent_version=transaction.consent_version or "",
                        display_name=None,
                        user_agent=request.headers.get("user-agent"),
                    )
                    session_token = registered.session.token
                    if transaction.surface in {"learner", "sales_xray"}:
                        tenant_id = await ensure_public_learner(
                            database,
                            registered.person.id,
                        )
                        await identity.select_tenant(session_token, tenant_id)
                elif transaction.authorization_type is ProviderAuthorizationType.AUTHENTICATE:
                    issued = await identity.authenticate_provider(
                        transaction.transaction_id,
                        assertion,
                        pkce_verifier=transaction.pkce_verifier,
                        user_agent=request.headers.get("user-agent"),
                    )
                    session_token = issued.token
                    # Existing members may also own an operations tenant. In
                    # that case the generic identity service issues an
                    # unscoped session; the learner surface must select its
                    # existing learner context just as password login does.
                    existing_learner_tenant_id = settings.public_learner_tenant_id
                    if (
                        transaction.surface in {"learner", "sales_xray"}
                        and existing_learner_tenant_id is not None
                    ):
                        membership = await database.scalar(
                            select(Membership).where(
                                Membership.tenant_id == existing_learner_tenant_id,
                                Membership.person_id == issued.metadata.person_id,
                                Membership.role == MembershipRole.LEARNER.value,
                                Membership.status == MembershipStatus.ACTIVE.value,
                            )
                        )
                        if membership is not None:
                            await identity.select_tenant(session_token, existing_learner_tenant_id)
                else:
                    if link_session_token is None:  # pragma: no cover - narrowed above
                        raise AuthenticationRequired(
                            "A valid Authority Closers session is required."
                        )
                    await identity.link_provider_for_session(
                        link_session_token,
                        transaction.transaction_id,
                        assertion,
                        pkce_verifier=transaction.pkce_verifier,
                    )
        except PasswordRegistrationUnavailable as error:
            if transaction.surface != "learner":
                return _oauth_terminal_problem_response(
                    request,
                    settings,
                    error,
                    transaction_cookie_names=transaction_cookie_names,
                )
            if isinstance(error.__cause__, LearnerConsentMissingError):
                return _learner_oauth_recovery_response(
                    settings,
                    result="consent_required",
                    transaction_cookie_names=transaction_cookie_names,
                    transaction_return_path=transaction.return_path,
                )
            if isinstance(error.__cause__, LearnerConsentUpdateRequiredError):
                return _learner_oauth_recovery_response(
                    settings,
                    result="consent_update_required",
                    transaction_cookie_names=transaction_cookie_names,
                    transaction_return_path=transaction.return_path,
                )
            return _oauth_terminal_problem_response(
                request,
                settings,
                error,
                transaction_cookie_names=transaction_cookie_names,
            )
        except ProviderConsentVersionConflictError as error:
            if (
                transaction.surface == "learner"
                and transaction.authorization_type is ProviderAuthorizationType.REGISTER
            ):
                return _learner_oauth_recovery_response(
                    settings,
                    result="consent_update_required",
                    transaction_cookie_names=transaction_cookie_names,
                    transaction_return_path=transaction.return_path,
                )
            return await _oauth_identity_problem_response(
                request,
                settings,
                error,
                transaction_cookie_names=transaction_cookie_names,
            )
        except ProviderIdentityNotLinkedError as error:
            if (
                transaction.surface == "learner"
                and transaction.authorization_type is ProviderAuthorizationType.AUTHENTICATE
            ):
                return _learner_oauth_recovery_response(
                    settings,
                    result="registration_required",
                    transaction_cookie_names=transaction_cookie_names,
                    transaction_return_path=transaction.return_path,
                )
            return await _oauth_identity_problem_response(
                request,
                settings,
                error,
                transaction_cookie_names=transaction_cookie_names,
            )
        except IdentityServiceError as error:
            return await _oauth_identity_problem_response(
                request,
                settings,
                error,
                transaction_cookie_names=transaction_cookie_names,
            )
        except (SQLAlchemyError, OSError, TimeoutError):
            return _oauth_callback_unavailable_response(
                request,
                settings,
                transaction_cookie_names=transaction_cookie_names,
            )
        base_url = _surface_origin(settings, transaction.surface)
        response = RedirectResponse(
            f"{str(base_url).rstrip('/')}{transaction.return_path}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
        _delete_oauth_transaction_cookies(response, settings, transaction_cookie_names)
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

    @router.get("/me/google-link", response_model=GoogleLinkResponse)
    async def google_link(
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> GoogleLinkResponse:
        if request.query_params:
            raise DomainError("Google-link status is resolved only for the authenticated person.")
        linked = await auth.identity.repository.has_provider_identity_for_issuers(
            auth.resolved.actor.person_id,
            ("accounts.google.com", "https://accounts.google.com"),
        )
        response.headers["cache-control"] = "private, no-store"
        response.headers["pragma"] = "no-cache"
        return GoogleLinkResponse(linked=linked)

    @router.get("/me/workspaces", response_model=WorkspacesResponse)
    async def workspaces(
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> WorkspacesResponse:
        if request.query_params:
            raise DomainError("Workspaces are resolved only for the authenticated person.")
        actor = auth.resolved.actor
        choices = await auth.identity.repository.list_active_workspaces(actor.person_id)
        response.headers["cache-control"] = "no-store"
        response.headers["pragma"] = "no-cache"
        return WorkspacesResponse(
            person_id=actor.person_id,
            session_id=actor.session_id,
            selected_tenant_id=actor.tenant_id,
            workspaces=[
                WorkspaceChoiceResponse(tenant_id=tenant_id, name=name)
                for tenant_id, name in choices
            ],
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
    ) -> Response:
        require_safe_origin(request, settings)
        response = Response(status_code=status.HTTP_204_NO_CONTENT)
        _delete_session_cookie(response, settings)
        try:
            token = _session_cookie(request, settings, required=False)
        except AuthenticationRequired:
            return response
        if token is None:
            return response
        try:
            async with sessions() as database, database.begin():
                identity = _identity(database)
                resolved = await identity.resolve_actor(token)
                await identity.revoke_self(
                    token,
                    resolved.actor.session_id,
                    reason="user_logout",
                )
        except IdentityServiceError:
            # Logout is idempotent: an absent, expired, or already-revoked
            # server session still results in clearing the browser cookie.
            pass
        except (SQLAlchemyError, OSError, TimeoutError):
            failure = problem_response(
                request=request,
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                code="logout_revocation_unavailable",
                title="Sign-out could not be fully confirmed",
                detail=(
                    "The browser session was cleared, but server-side revocation could not be "
                    "confirmed. This browser is signed out; contact support to revoke outstanding "
                    "sessions if this was a shared device."
                ),
            )
            _delete_session_cookie(failure, settings)
            failure.headers["cache-control"] = "no-store"
            return failure
        return response

    application.include_router(router)
    return require_actor


__all__ = [
    "AdminRegistrationUnavailable",
    "AdminSurfaceRequired",
    "AuthenticatedTransaction",
    "AuthenticationRequired",
    "ContextResponse",
    "GoogleLinkResponse",
    "LearnerConsentRequired",
    "MeResponse",
    "PasswordChallengeRejected",
    "PasswordCredentialsRejected",
    "PasswordEmailVerificationRequired",
    "PasswordRecoveryResponse",
    "PasswordRegistrationResponse",
    "PasswordRequestInvalid",
    "PasswordResetResponse",
    "PasswordSessionResponse",
    "RequestOriginDenied",
    "RequireActor",
    "install_identity_http",
    "require_admin_surface",
    "require_safe_origin",
]
