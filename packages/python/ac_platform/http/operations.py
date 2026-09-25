"""Narrow, fail-closed HTTP adapters for privileged operations and webhooks.

The adapter composes the existing durable job, recovery, provider-inbox, and
append-only audit services.  It deliberately does not own a transaction:
authenticated admin routes reuse the transaction yielded by ``require_actor``
and provider callbacks open one caller-owned session transaction only for the
verified inbox write.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, FastAPI, Header, Path, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ac_platform.application.settings import Settings
from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository, build_audit_tenant_lock_statement
from ac_platform.authorization.platform import platform_projection
from ac_platform.authorization.policy import CapabilityDenied
from ac_platform.conversation_intelligence.acquisition_usage import (
    ALLOWANCE_SECONDS,
    shared_account_committed_seconds,
)
from ac_platform.conversation_intelligence.entitlements import MinuteGrant
from ac_platform.conversation_intelligence.internal_tester import InternalTesterPolicy
from ac_platform.conversation_intelligence.minute_account_admin import (
    MINUTE_GRANT_ACTION,
    MINUTE_GRANT_RESOURCE_TYPE,
    EligibleLearnerBusy,
    EligibleLearnerUnavailable,
    InvalidMinuteAccountSnapshot,
    MinuteAccountState,
    append_minute_grant,
    load_minute_account,
    require_eligible_learner,
)
from ac_platform.http.auth import (
    AuthenticatedTransaction,
    RequireActor,
    require_admin_surface,
    require_safe_origin,
)
from ac_platform.kernel.authz import ActorContext
from ac_platform.kernel.errors import DomainError
from ac_platform.outbox.errors import (
    DuplicateIntentError,
    JobStateError,
    RetryNotAllowedError,
)
from ac_platform.outbox.models import Job, JobStatus
from ac_platform.outbox.policy import ReconciliationRequiredError, SideEffectHoldPolicy
from ac_platform.outbox.repository import (
    JobRepository,
    RecoveryStateRepository,
    reconcile_operations,
)
from ac_platform.providers.service import (
    DuplicateProviderEvent,
    ProviderInboxRepository,
    ProviderPayloadConflict,
    ProviderWebhookRejected,
    TrustedWebhookAdapter,
)

MAX_IDEMPOTENCY_KEY_LENGTH = 200
MAX_RELEASE_SET_SIZE = 100
MAX_PROVIDER_TIMESTAMP_LENGTH = 32
MAX_PROVIDER_SIGNATURE_LENGTH = 1024
MAX_SAFE_JSON_INTEGER = (1 << 53) - 1
MAX_MINUTE_GRANT_MINUTES = (MAX_SAFE_JSON_INTEGER - ALLOWANCE_SECONDS) // 60
_PROVIDER_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_PROVIDER_TIMESTAMP_PATTERN = re.compile(r"^[0-9]{1,20}$")

JOB_RETRY_MARKER = "operations.job_retry_idempotency"
RECOVERY_RECONCILE_MARKER = "operations.recovery_reconcile_idempotency"


class OperationsTenantRequired(DomainError):
    code = "tenant_context_required"
    title = "A tenant context is required"
    status = 403


class MissingIdempotencyKey(DomainError):
    code = "idempotency_key_required"
    title = "An idempotency key is required"
    status = 428


class InvalidOperationsRequest(DomainError):
    code = "operations_request_invalid"
    title = "The operations request is invalid"
    status = 422


class OperationsIdempotencyConflict(DomainError):
    code = "idempotency_conflict"
    title = "The idempotency key conflicts with an earlier request"
    status = 409


class JobRetryUnavailable(DomainError):
    code = "job_retry_unavailable"
    title = "The job cannot be retried"
    status = 409


class RecoveryReconciliationUnavailable(DomainError):
    code = "recovery_reconciliation_unavailable"
    title = "Recovery reconciliation cannot be performed"
    status = 409


class MinuteAccountTargetUnavailable(DomainError):
    code = "conversation_minute_account_unavailable"
    title = "The learner account is unavailable"
    status = 404


class MinuteAccountTargetBusy(DomainError):
    code = "conversation_minute_target_busy"
    title = "The learner account is being updated"
    status = 409


class MinuteAccountUnavailable(DomainError):
    code = "conversation_minute_account_conflict"
    title = "The learner minute account is unavailable"
    status = 409


class ProviderWebhookUnavailable(DomainError):
    code = "provider_webhook_unavailable"
    title = "The provider webhook is unavailable"
    status = 404


class ProviderWebhookAuthenticationFailed(DomainError):
    code = "provider_webhook_rejected"
    title = "The provider webhook was rejected"
    status = 401


class ProviderWebhookConflict(DomainError):
    code = "provider_event_conflict"
    title = "The provider event conflicts with a prior delivery"
    status = 409


class RetryJobRequest(BaseModel):
    """The only client-owned fact in a manual retry: its operator reason."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)


class ReconcileRecoveryRequest(BaseModel):
    """A bounded held-record release or control-tenant finalization request."""

    model_config = ConfigDict(extra="forbid")

    job_ids: list[UUID] = Field(default_factory=list, max_length=MAX_RELEASE_SET_SIZE)
    outbox_event_ids: list[UUID] = Field(
        default_factory=list,
        max_length=MAX_RELEASE_SET_SIZE,
    )
    reason: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def require_unique_release_set(self) -> ReconcileRecoveryRequest:
        if len(set(self.job_ids)) != len(self.job_ids):
            raise ValueError("job_ids must not contain duplicates")
        if len(set(self.outbox_event_ids)) != len(self.outbox_event_ids):
            raise ValueError("outbox_event_ids must not contain duplicates")
        return self


class JobRetryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    status: str
    attempt_count: int
    recovery_generation: int
    held: bool
    replayed: bool


class RecoveryReconcileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_ids: list[UUID]
    outbox_event_ids: list[UUID]
    recovery_generation: int
    recovery_status: str
    replayed: bool


class ProviderWebhookResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inbox_id: UUID
    provider: str
    external_event_id: str
    created: bool
    replayed: bool


class MinuteGrantHistoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grant_id: str
    seconds: int
    authorization_ref: str
    granted_by: str
    reason: str
    created_at: datetime | None
    audit_sequence: int | None


class ConversationMinuteAccountResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    person_id: UUID
    revision: int
    stored_unlimited: bool
    effective_unlimited: bool
    granted_seconds: int
    committed_seconds: int
    available_seconds: int
    available_minutes: int
    shared_upload_allowance_seconds: int
    shared_upload_committed_seconds: int
    shared_upload_available_seconds: int
    grants: list[MinuteGrantHistoryEntry]


class ConversationMinuteGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minutes: StrictInt = Field(gt=0, le=MAX_MINUTE_GRANT_MINUTES)
    reason: str = Field(min_length=1, max_length=500)


class ConversationMinuteGrantResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grant_id: UUID
    minutes: int
    replayed: bool
    account: ConversationMinuteAccountResponse


def _normalize_idempotency_key(value: str | None) -> str:
    if value is None:
        raise MissingIdempotencyKey("The operation must include an Idempotency-Key header.")
    normalized = value.strip()
    if not normalized:
        raise MissingIdempotencyKey("The operation must include an Idempotency-Key header.")
    if len(normalized) > MAX_IDEMPOTENCY_KEY_LENGTH:
        raise InvalidOperationsRequest("The Idempotency-Key header is too long.")
    return normalized


def _normalize_reason(reason: str) -> str:
    try:
        return SideEffectHoldPolicy.normalize_reconciliation_reason(reason)
    except ValueError as error:
        raise InvalidOperationsRequest("A non-blank bounded reason is required.") from error


def _require_operations_actor(actor: ActorContext, permission: str) -> None:
    if actor.tenant_id is None:
        raise OperationsTenantRequired("Select an active operations tenant before continuing.")
    actor.require_permission("admin_surface")
    actor.require_permission(permission)


def _no_store(response: Response) -> None:
    response.headers["cache-control"] = "no-store"
    response.headers["pragma"] = "no-cache"


def _request_id(request: Request) -> str | None:
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) else None


def _request_digest(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        dict(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _dialect_name(session: AsyncSession) -> str | None:
    bind = session.get_bind()
    dialect = getattr(getattr(bind, "dialect", None), "name", None)
    return dialect if isinstance(dialect, str) else None


async def _lock_idempotency_scope(session: AsyncSession, tenant_id: UUID) -> None:
    """Serialize HTTP idempotency lookup, command, and marker on PostgreSQL."""

    if _dialect_name(session) == "postgresql":
        await session.execute(build_audit_tenant_lock_statement(tenant_id))


async def _find_marker(
    session: AsyncSession,
    *,
    actor: ActorContext,
    action: str,
    idempotency_key: str,
) -> AuditEvent | None:
    if actor.tenant_id is None:  # pragma: no cover - guarded by the route boundary
        raise OperationsTenantRequired("Select an active operations tenant before continuing.")
    events = list(
        (
            await session.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.tenant_id == actor.tenant_id,
                    AuditEvent.actor_person_id == actor.person_id,
                    AuditEvent.action == action,
                )
                .order_by(AuditEvent.sequence_no.desc())
            )
        ).all()
    )
    for event in events:
        payload = event.payload
        if isinstance(payload, dict) and payload.get("idempotency_key") == idempotency_key:
            return event
    return None


def _marker_payload(marker: AuditEvent, *, digest: str) -> dict[str, Any]:
    payload = marker.payload
    if not isinstance(payload, dict) or payload.get("request_digest") != digest:
        raise OperationsIdempotencyConflict(
            "The Idempotency-Key was already used for a different request."
        )
    return payload


def _job_response(job: Job, *, replayed: bool) -> JobRetryResponse:
    return JobRetryResponse(
        job_id=job.id,
        status=job.status,
        attempt_count=job.attempt_count,
        recovery_generation=job.recovery_generation,
        held=job.status == JobStatus.HELD.value,
        replayed=replayed,
    )


def _job_replay_response(
    marker: AuditEvent,
    *,
    digest: str,
    job_id: UUID,
) -> JobRetryResponse:
    payload = _marker_payload(marker, digest=digest)
    if payload.get("resource_id") != str(job_id):
        raise OperationsIdempotencyConflict(
            "The Idempotency-Key was already used for a different request."
        )
    try:
        return JobRetryResponse.model_validate(
            {
                "job_id": payload["job_id"],
                "status": payload["status"],
                "attempt_count": payload["attempt_count"],
                "recovery_generation": payload["recovery_generation"],
                "held": payload["held"],
                "replayed": True,
            }
        )
    except (TypeError, ValueError, KeyError) as error:
        raise OperationsIdempotencyConflict("The stored idempotency result is invalid.") from error


def _reconcile_replay_response(
    marker: AuditEvent,
    *,
    digest: str,
) -> RecoveryReconcileResponse:
    payload = _marker_payload(marker, digest=digest)
    try:
        return RecoveryReconcileResponse.model_validate(
            {
                "job_ids": payload["job_ids"],
                "outbox_event_ids": payload["outbox_event_ids"],
                "recovery_generation": payload["recovery_generation"],
                "recovery_status": payload["recovery_status"],
                "replayed": True,
            }
        )
    except (TypeError, ValueError, KeyError) as error:
        raise OperationsIdempotencyConflict("The stored idempotency result is invalid.") from error


async def _append_marker(
    audit: AuditRepository,
    actor: ActorContext,
    *,
    action: str,
    resource_type: str,
    resource_id: UUID | str,
    idempotency_key: str,
    request_digest: str,
    result: Mapping[str, Any],
    reason: str,
    request_id: str | None,
) -> None:
    payload = {
        "idempotency_key": idempotency_key,
        "request_digest": request_digest,
        "resource_id": str(resource_id),
        **dict(result),
    }
    await audit.append_for_actor(
        actor,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        payload=payload,
        reason=reason,
        request_id=request_id,
    )


async def _find_minute_grant_marker(
    session: AsyncSession,
    *,
    operations_tenant_id: UUID,
    actor: ActorContext,
    idempotency_key: str,
) -> AuditEvent | None:
    events = list(
        (
            await session.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.tenant_id == operations_tenant_id,
                    AuditEvent.actor_person_id == actor.person_id,
                    AuditEvent.action == MINUTE_GRANT_ACTION,
                )
                .order_by(AuditEvent.sequence_no.desc())
            )
        ).all()
    )
    for event in events:
        payload = event.payload
        if isinstance(payload, dict) and payload.get("idempotency_key") == idempotency_key:
            return event
    return None


def _minute_grant_digest(*, tenant_id: UUID, person_id: UUID, minutes: int, reason: str) -> str:
    return _request_digest(
        {
            "operation": "conversation_minute_grant",
            "tenant_id": str(tenant_id),
            "person_id": str(person_id),
            "minutes": minutes,
            "reason": reason,
        }
    )


async def _minute_account_response(
    session: AsyncSession,
    *,
    state: MinuteAccountState,
    operations_tenant_id: UUID,
    effective_unlimited: bool,
) -> ConversationMinuteAccountResponse:
    account = state.account
    event_by_grant_id: dict[str, AuditEvent] = {}
    grant_ids = [grant.grant_id for grant in account.grants]
    if grant_ids:
        events = await session.scalars(
            select(AuditEvent).where(
                AuditEvent.tenant_id == operations_tenant_id,
                AuditEvent.action == MINUTE_GRANT_ACTION,
                AuditEvent.resource_type == "conversation_minute_grant",
                AuditEvent.resource_id.in_(grant_ids),
            )
        )
        event_by_grant_id = {
            event.resource_id: event for event in events if event.resource_id is not None
        }
    grants = [
        MinuteGrantHistoryEntry(
            grant_id=grant.grant_id,
            seconds=grant.seconds,
            authorization_ref=grant.authorization_ref,
            granted_by=grant.granted_by,
            reason=grant.reason,
            created_at=(
                event_by_grant_id[grant.grant_id].occurred_at
                if grant.grant_id in event_by_grant_id
                else None
            ),
            audit_sequence=(
                event_by_grant_id[grant.grant_id].sequence_no
                if grant.grant_id in event_by_grant_id
                else None
            ),
        )
        for grant in account.grants
    ]
    committed_seconds = sum(item.committed_seconds for item in account.reservations)
    shared_committed_seconds, additional_allowance_seconds = await shared_account_committed_seconds(
        session,
        tenant_id=UUID(account.tenant_id),
        person_id=UUID(account.account_id),
        operations_tenant_id=operations_tenant_id,
    )
    shared_allowance_seconds = ALLOWANCE_SECONDS + additional_allowance_seconds
    return ConversationMinuteAccountResponse(
        tenant_id=UUID(account.tenant_id),
        person_id=UUID(account.account_id),
        revision=state.revision,
        stored_unlimited=account.unlimited,
        effective_unlimited=effective_unlimited,
        granted_seconds=sum(grant.seconds for grant in account.grants),
        committed_seconds=committed_seconds,
        available_seconds=account.available_seconds,
        available_minutes=account.available_seconds // 60,
        shared_upload_allowance_seconds=shared_allowance_seconds,
        shared_upload_committed_seconds=shared_committed_seconds,
        shared_upload_available_seconds=max(0, shared_allowance_seconds - shared_committed_seconds),
        grants=grants,
    )


def _retry_digest(job_id: UUID, reason: str) -> str:
    return _request_digest({"operation": "job_retry", "job_id": str(job_id), "reason": reason})


def _reconcile_digest(
    *,
    job_ids: tuple[UUID, ...],
    outbox_event_ids: tuple[UUID, ...],
    reason: str,
) -> str:
    return _request_digest(
        {
            "operation": "recovery_reconcile",
            "job_ids": [str(value) for value in job_ids],
            "outbox_event_ids": [str(value) for value in outbox_event_ids],
            "reason": reason,
        }
    )


def _parse_provider_timestamp(value: str | None) -> int:
    if value is None:
        raise ProviderWebhookAuthenticationFailed(
            "The provider webhook authentication headers are incomplete."
        )
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > MAX_PROVIDER_TIMESTAMP_LENGTH
        or _PROVIDER_TIMESTAMP_PATTERN.fullmatch(normalized) is None
    ):
        raise ProviderWebhookAuthenticationFailed("The provider webhook timestamp is invalid.")
    timestamp = int(normalized)
    if timestamp <= 0:
        raise ProviderWebhookAuthenticationFailed("The provider webhook timestamp is invalid.")
    return timestamp


def _parse_provider_signature(value: str | None) -> str:
    if value is None:
        raise ProviderWebhookAuthenticationFailed(
            "The provider webhook authentication headers are incomplete."
        )
    normalized = value.strip()
    if not normalized or len(normalized) > MAX_PROVIDER_SIGNATURE_LENGTH:
        raise ProviderWebhookAuthenticationFailed("The provider webhook signature is invalid.")
    return normalized


def install_operations_http(
    application: FastAPI,
    *,
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    require_actor: RequireActor,
    tester_policy: InternalTesterPolicy | None = None,
    webhook_adapters: Mapping[str, TrustedWebhookAdapter] | None = None,
) -> None:
    """Install narrow operations routes around existing durable abstractions.

    ``webhook_adapters`` is an explicit server-side registry.  With no
    registry, the provider callback route is not installed at all; this keeps
    an unverified internal endpoint from becoming part of the application
    surface by accident.
    """

    def require_admin_route_surface(request: Request) -> None:
        require_admin_surface(request, settings)

    router = APIRouter(
        prefix="/v1",
        tags=["operations"],
        dependencies=[Depends(require_admin_route_surface)],
    )
    actor_dependency = Depends(require_actor)

    @router.get(
        "/admin/conversation-minute-accounts/{tenant_id}/{person_id}",
        response_model=ConversationMinuteAccountResponse,
    )
    async def read_conversation_minute_account(
        tenant_id: Annotated[UUID, Path()],
        person_id: Annotated[UUID, Path()],
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> ConversationMinuteAccountResponse:
        if request.query_params:
            raise InvalidOperationsRequest("The minute-account read accepts no query parameters.")
        operations_tenant_id = settings.operations_tenant_id
        capabilities = await platform_projection(
            auth.database,
            auth.resolved.actor,
            operations_tenant_id=operations_tenant_id,
        )
        if "platform_access_manage" not in capabilities:
            raise CapabilityDenied("A current platform access-management assignment is required.")
        assert operations_tenant_id is not None  # platform_projection rejects missing settings
        try:
            await require_eligible_learner(
                auth.database,
                tenant_id=tenant_id,
                person_id=person_id,
                operations_tenant_id=operations_tenant_id,
            )
            state = await load_minute_account(
                auth.database,
                tenant_id=tenant_id,
                person_id=person_id,
                lock=True,
            )
            effective_unlimited = (
                tester_policy is not None
                and await tester_policy.for_learner_account(
                    auth.database,
                    tenant_id=tenant_id,
                    person_id=person_id,
                )
                is not None
            )
            result = await _minute_account_response(
                auth.database,
                state=state,
                operations_tenant_id=operations_tenant_id,
                effective_unlimited=effective_unlimited,
            )
        except EligibleLearnerUnavailable as error:
            raise MinuteAccountTargetUnavailable(
                "The exact active learner account is unavailable."
            ) from error
        except InvalidMinuteAccountSnapshot as error:
            raise MinuteAccountUnavailable(
                "The learner minute ledger cannot be read safely."
            ) from error
        _no_store(response)
        return result

    @router.post(
        "/admin/conversation-minute-accounts/{tenant_id}/{person_id}/grants",
        response_model=ConversationMinuteGrantResponse,
    )
    async def grant_conversation_minutes(
        tenant_id: Annotated[UUID, Path()],
        person_id: Annotated[UUID, Path()],
        request: Request,
        response: Response,
        body: ConversationMinuteGrantRequest,
        idempotency_key: Annotated[
            str | None,
            Header(alias="Idempotency-Key", max_length=MAX_IDEMPOTENCY_KEY_LENGTH),
        ] = None,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> ConversationMinuteGrantResponse:
        require_safe_origin(request, settings)
        actor = auth.resolved.actor
        operations_tenant_id = settings.operations_tenant_id
        capabilities = await platform_projection(
            auth.database,
            actor,
            operations_tenant_id=operations_tenant_id,
        )
        if "platform_access_manage" not in capabilities:
            raise CapabilityDenied("A current platform access-management assignment is required.")
        assert operations_tenant_id is not None  # platform_projection rejects missing settings
        key = _normalize_idempotency_key(idempotency_key)
        reason = _normalize_reason(body.reason)
        digest = _minute_grant_digest(
            tenant_id=tenant_id,
            person_id=person_id,
            minutes=body.minutes,
            reason=reason,
        )
        marker = await _find_minute_grant_marker(
            auth.database,
            operations_tenant_id=operations_tenant_id,
            actor=actor,
            idempotency_key=key,
        )
        replayed = marker is not None
        grant_id: UUID
        if marker is not None:
            payload = _marker_payload(marker, digest=digest)
            if (
                payload.get("tenant_id") != str(tenant_id)
                or payload.get("person_id") != str(person_id)
                or payload.get("minutes") != body.minutes
            ):
                raise OperationsIdempotencyConflict(
                    "The Idempotency-Key was already used for a different minute grant."
                )
            try:
                grant_id = UUID(str(payload["grant_id"]))
            except (ValueError, KeyError) as error:
                raise OperationsIdempotencyConflict(
                    "The stored minute-grant result is invalid."
                ) from error
            try:
                await require_eligible_learner(
                    auth.database,
                    tenant_id=tenant_id,
                    person_id=person_id,
                    operations_tenant_id=operations_tenant_id,
                )
                state = await load_minute_account(
                    auth.database,
                    tenant_id=tenant_id,
                    person_id=person_id,
                    lock=True,
                )
            except EligibleLearnerUnavailable as error:
                raise MinuteAccountTargetUnavailable(
                    "The exact active learner account is unavailable."
                ) from error
            except InvalidMinuteAccountSnapshot as error:
                raise MinuteAccountUnavailable(
                    "The learner minute ledger cannot be read safely."
                ) from error
        else:
            grant_id = uuid4()
            audit_event_id = uuid4()
            grant = MinuteGrant(
                tenant_id=str(tenant_id),
                account_id=str(person_id),
                grant_id=str(grant_id),
                seconds=body.minutes * 60,
                authorization_ref=f"audit-event:{audit_event_id}",
                granted_by=str(actor.person_id),
                reason=reason,
            )
            try:
                state = await append_minute_grant(
                    auth.database,
                    tenant_id=tenant_id,
                    person_id=person_id,
                    operations_tenant_id=operations_tenant_id,
                    grant=grant,
                )
            except EligibleLearnerUnavailable as error:
                raise MinuteAccountTargetUnavailable(
                    "The exact active learner account is unavailable."
                ) from error
            except EligibleLearnerBusy as error:
                raise MinuteAccountTargetBusy(
                    "The learner account is being updated. Retry this request with the same "
                    "Idempotency-Key."
                ) from error
            except InvalidMinuteAccountSnapshot as error:
                raise MinuteAccountUnavailable(
                    "The learner minute ledger cannot be changed safely."
                ) from error
            if sum(grant.seconds for grant in state.account.grants) > (
                MAX_SAFE_JSON_INTEGER - ALLOWANCE_SECONDS
            ):
                raise InvalidOperationsRequest(
                    "The resulting allowance exceeds the exact JSON integer range."
                )
            await AuditRepository(auth.database).append(
                event_id=audit_event_id,
                tenant_id=operations_tenant_id,
                actor_person_id=actor.person_id,
                session_id=actor.session_id,
                action=MINUTE_GRANT_ACTION,
                resource_type=MINUTE_GRANT_RESOURCE_TYPE,
                resource_id=grant_id,
                payload={
                    "idempotency_key": key,
                    "request_digest": digest,
                    "grant_id": str(grant_id),
                    "tenant_id": str(tenant_id),
                    "person_id": str(person_id),
                    "minutes": body.minutes,
                    "seconds": body.minutes * 60,
                },
                reason=reason,
                request_id=_request_id(request),
            )

        effective_unlimited = (
            tester_policy is not None
            and await tester_policy.for_learner_account(
                auth.database,
                tenant_id=tenant_id,
                person_id=person_id,
            )
            is not None
        )
        account = await _minute_account_response(
            auth.database,
            state=state,
            operations_tenant_id=operations_tenant_id,
            effective_unlimited=effective_unlimited,
        )
        _no_store(response)
        return ConversationMinuteGrantResponse(
            grant_id=grant_id,
            minutes=body.minutes,
            replayed=replayed,
            account=account,
        )

    @router.post("/admin/jobs/{job_id}/retry", response_model=JobRetryResponse)
    async def retry_job(
        job_id: Annotated[UUID, Path()],
        request: Request,
        response: Response,
        body: RetryJobRequest,
        idempotency_key: Annotated[
            str | None,
            Header(alias="Idempotency-Key", max_length=MAX_IDEMPOTENCY_KEY_LENGTH),
        ] = None,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> JobRetryResponse:
        require_safe_origin(request, settings)
        actor = auth.resolved.actor
        _require_operations_actor(actor, "job_retry")
        key = _normalize_idempotency_key(idempotency_key)
        reason = _normalize_reason(body.reason)
        digest = _retry_digest(job_id, reason)
        tenant_id = actor.tenant_id
        if tenant_id is None:  # pragma: no cover - narrowed by the guard above
            raise OperationsTenantRequired("Select an active operations tenant before continuing.")
        await _lock_idempotency_scope(auth.database, tenant_id)
        marker = await _find_marker(
            auth.database,
            actor=actor,
            action=JOB_RETRY_MARKER,
            idempotency_key=key,
        )
        if marker is not None:
            result = _job_replay_response(marker, digest=digest, job_id=job_id)
            _no_store(response)
            return result

        audit = AuditRepository(auth.database)
        try:
            job = await JobRepository(auth.database).retry(
                job_id,
                actor=actor,
                reason=reason,
                audit=audit,
                operations_tenant_id=settings.operations_tenant_id,
            )
            await _append_marker(
                audit,
                actor,
                action=JOB_RETRY_MARKER,
                resource_type="job",
                resource_id=job.id,
                idempotency_key=key,
                request_digest=digest,
                result={
                    "job_id": str(job.id),
                    "status": job.status,
                    "attempt_count": job.attempt_count,
                    "recovery_generation": job.recovery_generation,
                    "held": job.status == JobStatus.HELD.value,
                },
                reason=reason,
                request_id=_request_id(request),
            )
        except RetryNotAllowedError as error:
            marker = await _find_marker(
                auth.database,
                actor=actor,
                action=JOB_RETRY_MARKER,
                idempotency_key=key,
            )
            if marker is not None:
                result = _job_replay_response(marker, digest=digest, job_id=job_id)
                _no_store(response)
                return result
            raise JobRetryUnavailable("The job is not in a retryable state.") from error
        except DuplicateIntentError as error:
            raise OperationsIdempotencyConflict(
                "The idempotency key conflicts with an earlier request."
            ) from error
        except ReconciliationRequiredError as error:
            raise JobRetryUnavailable(
                "The job remains held pending recovery reconciliation."
            ) from error
        except JobStateError as error:
            raise JobRetryUnavailable(
                "The requested job is unavailable for this tenant."
            ) from error
        except ValueError as error:
            raise InvalidOperationsRequest("The job retry request was rejected.") from error

        _no_store(response)
        return _job_response(job, replayed=False)

    @router.post(
        "/admin/recovery/reconcile",
        response_model=RecoveryReconcileResponse,
    )
    async def reconcile_recovery(
        request: Request,
        response: Response,
        body: ReconcileRecoveryRequest,
        idempotency_key: Annotated[
            str | None,
            Header(alias="Idempotency-Key", max_length=MAX_IDEMPOTENCY_KEY_LENGTH),
        ] = None,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> RecoveryReconcileResponse:
        require_safe_origin(request, settings)
        actor = auth.resolved.actor
        _require_operations_actor(actor, "recovery_reconcile")
        key = _normalize_idempotency_key(idempotency_key)
        reason = _normalize_reason(body.reason)
        job_ids = tuple(sorted(body.job_ids, key=str))
        outbox_event_ids = tuple(sorted(body.outbox_event_ids, key=str))
        digest = _reconcile_digest(
            job_ids=job_ids,
            outbox_event_ids=outbox_event_ids,
            reason=reason,
        )
        tenant_id = actor.tenant_id
        if tenant_id is None:  # pragma: no cover - narrowed by the guard above
            raise OperationsTenantRequired("Select an active operations tenant before continuing.")
        await _lock_idempotency_scope(auth.database, tenant_id)
        marker = await _find_marker(
            auth.database,
            actor=actor,
            action=RECOVERY_RECONCILE_MARKER,
            idempotency_key=key,
        )
        if marker is not None:
            result = _reconcile_replay_response(marker, digest=digest)
            _no_store(response)
            return result

        try:
            await RecoveryStateRepository(auth.database).require_held(lock=True)
            events, jobs = await reconcile_operations(
                auth.database,
                outbox_event_ids=outbox_event_ids,
                job_ids=job_ids,
                actor=actor,
                reason=reason,
                operations_tenant_id=settings.operations_tenant_id,
            )
            recovery_state = await RecoveryStateRepository(auth.database).get()
            if recovery_state is None:
                raise ReconciliationRequiredError("durable recovery state is missing")
            audit = AuditRepository(auth.database)
            await _append_marker(
                audit,
                actor,
                action=RECOVERY_RECONCILE_MARKER,
                resource_type="operations_recovery_state",
                resource_id=str(recovery_state.generation),
                idempotency_key=key,
                request_digest=digest,
                result={
                    "job_ids": [str(job.id) for job in jobs],
                    "outbox_event_ids": [str(event.id) for event in events],
                    "recovery_generation": recovery_state.generation,
                    "recovery_status": recovery_state.status,
                },
                reason=reason,
                request_id=_request_id(request),
            )
        except ReconciliationRequiredError as error:
            marker = await _find_marker(
                auth.database,
                actor=actor,
                action=RECOVERY_RECONCILE_MARKER,
                idempotency_key=key,
            )
            if marker is not None:
                result = _reconcile_replay_response(marker, digest=digest)
                _no_store(response)
                return result
            raise RecoveryReconciliationUnavailable(
                "The recovery state is not ready for this reconciliation request."
            ) from error
        except DuplicateIntentError as error:
            raise OperationsIdempotencyConflict(
                "The idempotency key conflicts with an earlier request."
            ) from error
        except JobStateError as error:
            raise RecoveryReconciliationUnavailable(
                "Every named record must be held and authorized for the selected tenant or "
                "configured control scope."
            ) from error
        except ValueError as error:
            raise InvalidOperationsRequest(
                "The recovery reconciliation request was rejected."
            ) from error

        result = RecoveryReconcileResponse(
            job_ids=[job.id for job in jobs],
            outbox_event_ids=[event.id for event in events],
            recovery_generation=recovery_state.generation,
            recovery_status=recovery_state.status,
            replayed=False,
        )
        _no_store(response)
        return result

    application.include_router(router)

    if not webhook_adapters:
        return

    normalized_adapters: dict[str, TrustedWebhookAdapter] = {}
    for configured_provider, adapter in webhook_adapters.items():
        provider = configured_provider.strip().lower()
        if _PROVIDER_NAME_PATTERN.fullmatch(provider) is None:
            raise ValueError("webhook registry contains an invalid provider name")
        if provider == "video":
            raise ValueError("video provider webhooks are owned by media composition")
        if not isinstance(adapter, TrustedWebhookAdapter):
            raise TypeError("webhook registry entries must be TrustedWebhookAdapter instances")
        if (
            type(adapter).verify is TrustedWebhookAdapter.verify
            or type(adapter).attribution is TrustedWebhookAdapter.attribution
        ):
            raise TypeError("webhook registry entries must implement verification and attribution")
        if provider in normalized_adapters:
            raise ValueError("webhook registry contains duplicate provider names")
        normalized_adapters[provider] = adapter

    if not normalized_adapters:
        return

    webhook_router = APIRouter(prefix="/internal/v1", tags=["provider-webhooks"])

    @webhook_router.post(
        "/providers/{provider}/webhooks",
        response_model=ProviderWebhookResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def receive_provider_webhook(
        provider: Annotated[
            str,
            Path(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"),
        ],
        request: Request,
        response: Response,
        provider_timestamp: Annotated[
            str | None,
            Header(alias="X-Provider-Timestamp", max_length=MAX_PROVIDER_TIMESTAMP_LENGTH),
        ] = None,
        provider_signature: Annotated[
            str | None,
            Header(alias="X-Provider-Signature", max_length=MAX_PROVIDER_SIGNATURE_LENGTH),
        ] = None,
    ) -> ProviderWebhookResponse:
        adapter = normalized_adapters.get(provider.lower())
        if adapter is None:
            raise ProviderWebhookUnavailable("The requested provider webhook is not configured.")
        timestamp = _parse_provider_timestamp(provider_timestamp)
        signature = _parse_provider_signature(provider_signature)
        body = await request.body()
        try:
            async with sessions() as database, database.begin():
                row, created = await ProviderInboxRepository(database).ingest_verified(
                    adapter=adapter,
                    body=body,
                    timestamp=timestamp,
                    signature=signature,
                )
        except ProviderPayloadConflict as error:
            raise ProviderWebhookConflict(
                "The provider event conflicts with previously verified facts."
            ) from error
        except DuplicateProviderEvent as error:
            raise ProviderWebhookConflict("The provider event was already received.") from error
        except ProviderWebhookRejected as error:
            raise ProviderWebhookAuthenticationFailed(
                "The provider webhook signature, timestamp, or body was rejected."
            ) from error
        except ValueError as error:
            raise ProviderWebhookAuthenticationFailed(
                "The provider webhook could not be accepted."
            ) from error

        response.status_code = status.HTTP_202_ACCEPTED if created else status.HTTP_200_OK
        _no_store(response)
        return ProviderWebhookResponse(
            inbox_id=row.id,
            provider=row.provider,
            external_event_id=row.external_event_id,
            created=created,
            replayed=not created,
        )

    application.include_router(webhook_router)


__all__ = [
    "InvalidOperationsRequest",
    "JobRetryResponse",
    "RetryJobRequest",
    "MissingIdempotencyKey",
    "OperationsIdempotencyConflict",
    "OperationsTenantRequired",
    "ProviderWebhookResponse",
    "ReconcileRecoveryRequest",
    "RecoveryReconcileResponse",
    "install_operations_http",
]
