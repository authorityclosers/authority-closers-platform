"""Authenticated, fail-closed learner product-analytics intake routes."""

from __future__ import annotations

import inspect
import json
import re
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, FastAPI, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ac_platform.application.settings import Settings
from ac_platform.http.auth import AuthenticatedTransaction, RequireActor, require_safe_origin
from ac_platform.kernel.authz import ActorContext
from ac_platform.kernel.errors import DomainError
from ac_platform.learning.planning_models import AnalyticsEvent
from ac_platform.learning.planning_repository import (
    AnalyticsEventReplayConflict,
    PlanningRepository,
)
from ac_platform.telemetry.ingest import (
    LEARNER_PRODUCT_ANALYTICS_EVENTS,
    MAX_BATCH_BYTES,
    MAX_BATCH_EVENTS,
    MAX_FUTURE_SKEW,
    MAX_RETENTION_DAYS,
    TELEMETRY_PROVENANCE_SOURCE,
    TELEMETRY_PROVENANCE_VERSION,
    TELEMETRY_PURPOSE,
    LearnerTelemetryBatch,
    TelemetryAdmission,
    TelemetryConsent,
    TelemetryConsentResolver,
    TelemetryConsentStatus,
    ensure_utc,
    validate_batch_size,
    validate_event_timestamp,
)


class TelemetryTenantContextRequired(DomainError):
    code = "telemetry_tenant_context_required"
    title = "A tenant context is required"
    status = 403


class TelemetrySessionBindingDenied(DomainError):
    code = "telemetry_session_binding_denied"
    title = "The telemetry session is not authorized"
    status = 403


class TelemetryConsentUnavailable(DomainError):
    code = "telemetry_consent_unavailable"
    title = "Telemetry consent policy is unavailable"
    status = 503


class TelemetryConsentIdentityMismatch(DomainError):
    code = "telemetry_consent_identity_mismatch"
    title = "Telemetry consent is not bound to this session"
    status = 403


class TelemetryRetentionUnavailable(DomainError):
    code = "telemetry_retention_unavailable"
    title = "Telemetry retention policy is unavailable"
    status = 503


class TelemetryBackpressure(DomainError):
    code = "telemetry_backpressure"
    title = "Telemetry intake is temporarily unavailable"
    status = 503


class TelemetryAdmissionUnavailable(DomainError):
    code = "telemetry_admission_unavailable"
    title = "Telemetry admission is not configured"
    status = 503


class TelemetryEventInvalid(DomainError):
    code = "telemetry_event_invalid"
    title = "The telemetry batch is invalid"
    status = 422


class TelemetryIdempotencyConflict(DomainError):
    code = "telemetry_idempotency_conflict"
    title = "The telemetry event id was already used"
    status = 409


class TelemetryBatchResult(BaseModel):
    """Safe batch outcome; it contains no submitted payload or person data."""

    model_config = ConfigDict(extra="forbid")

    accepted: int = Field(ge=0, le=MAX_BATCH_EVENTS)
    duplicate: int = Field(default=0, ge=0, le=MAX_BATCH_EVENTS)
    dropped: int = Field(default=0, ge=0, le=MAX_BATCH_EVENTS)
    accepted_event_ids: list[str] = Field(default_factory=list, max_length=MAX_BATCH_EVENTS)
    reason: str | None = Field(default=None, max_length=64)
    trace_id: str = Field(min_length=1, max_length=128)
    retention_expires_at: datetime | None = None
    provenance_source: str = TELEMETRY_PROVENANCE_SOURCE
    provenance_version: str = TELEMETRY_PROVENANCE_VERSION


class TelemetryTaxonomyItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_name: str
    event_version: str
    allowed_payload_keys: list[str] = Field(default_factory=list)
    consent_required: bool = True
    canonical_state: bool = False


class TelemetryTaxonomy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[TelemetryTaxonomyItem]
    ingest_path: str = "/v1/telemetry/events"
    disclaimer: str = (
        "Learner product telemetry is consented, disposable analytics only; it never "
        "creates canonical progress, completion, payment, entitlement, access, audit, "
        "or scoring state."
    )


_RETENTION_POLICY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _tenant(actor: ActorContext) -> UUID:
    if actor.tenant_id is None:
        raise TelemetryTenantContextRequired(
            "Select an active tenant before sending learner telemetry."
        )
    return actor.tenant_id


def _validate_consent_binding(consent: TelemetryConsent, actor: ActorContext) -> None:
    """Require an immutable consent grant for this exact auth scope."""

    tenant_id = _tenant(actor)
    if (
        consent.tenant_id != tenant_id
        or consent.person_id != actor.person_id
        or consent.session_id != actor.session_id
    ):
        raise TelemetryConsentIdentityMismatch(
            "The server-owned telemetry consent is bound to another identity scope."
        )


async def _resolve_consent(
    resolver: TelemetryConsentResolver, database: object, actor: ActorContext
) -> TelemetryConsent | None:
    value = resolver(database, actor)
    if inspect.isawaitable(value):
        return await value
    return value


async def _admit(
    admission: TelemetryAdmission, *, tenant_id: UUID, event_count: int, payload_bytes: int
) -> bool:
    value = admission.admit(
        tenant_id=tenant_id,
        event_count=event_count,
        payload_bytes=payload_bytes,
    )
    if inspect.isawaitable(value):
        return await value
    return value


async def _parse_batch(request: Request) -> LearnerTelemetryBatch:
    """Parse manually so validation errors never echo submitted PII/secrets."""

    raw = await request.body()
    if len(raw) > MAX_BATCH_BYTES:
        raise TelemetryEventInvalid("The telemetry batch exceeds the bounded request size.")
    try:
        value = json.loads(raw)
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise TelemetryEventInvalid("The telemetry request must be a JSON batch.") from exc
    try:
        batch = LearnerTelemetryBatch.model_validate(value)
        validate_batch_size(batch)
    except (TypeError, ValueError, ValidationError) as exc:
        raise TelemetryEventInvalid(
            "The telemetry batch does not match the server schema."
        ) from exc
    return batch


def _validate_event_schema(batch: LearnerTelemetryBatch) -> None:
    for event in batch.events:
        definition = LEARNER_PRODUCT_ANALYTICS_EVENTS.get(event.event_name)
        if definition is None:
            raise TelemetryEventInvalid("The telemetry event is not in the server allowlist.")
        if event.event_version != definition.event_version:
            raise TelemetryEventInvalid("The telemetry event version is not supported.")
        allowed_payload_keys = set(definition.allowed_payload_keys)
        if set(event.payload) - allowed_payload_keys:
            raise TelemetryEventInvalid("The telemetry payload contains a non-allowlisted key.")
        if definition.requires_period:
            period = event.payload.get("period")
            if period not in {"today", "week", "month"}:
                raise TelemetryEventInvalid("This telemetry event requires a valid period label.")
        elif "period" in event.payload:
            raise TelemetryEventInvalid("This telemetry event does not accept a period label.")


def _validate_timestamps(
    batch: LearnerTelemetryBatch, *, consent: TelemetryConsent, now: datetime
) -> None:
    current = ensure_utc(now)
    captured_at = ensure_utc(consent.captured_at)
    if captured_at > current + MAX_FUTURE_SKEW:
        raise TelemetryEventInvalid("The consent timestamp is outside the permitted clock skew.")
    for event in batch.events:
        occurred_at = validate_event_timestamp(occurred_at=event.occurred_at, now=current)
        if occurred_at < captured_at:
            raise TelemetryEventInvalid(
                "Telemetry cannot be stored for a time before the consent capture."
            )


def install_telemetry_http(
    application: FastAPI,
    *,
    settings: Settings,
    require_actor: RequireActor,
    consent_resolver: TelemetryConsentResolver | None = None,
    retention_days: int | None = None,
    retention_policy_id: str | None = None,
    admission: TelemetryAdmission | None = None,
) -> None:
    """Install the authenticated learner telemetry boundary.

    ``consent_resolver`` and retention settings are intentionally explicit
    composition seams.  Leaving either unset means the route rejects writes
    before persistence; no client-provided consent is accepted as authority.
    The resolver receives the active transaction and actor, and must resolve
    the authoritative identity-bound grant with a write lock on each call.
    """

    configured_retention_days = (
        retention_days
        if retention_days is not None and 1 <= retention_days <= MAX_RETENTION_DAYS
        else None
    )
    configured_policy_id = (
        retention_policy_id.strip()
        if retention_policy_id is not None
        and _RETENTION_POLICY_PATTERN.fullmatch(retention_policy_id)
        else None
    )

    router = APIRouter(prefix="/v1", tags=["telemetry"])
    actor_dependency = Depends(require_actor)
    repository = PlanningRepository()

    @router.get("/telemetry/taxonomy", response_model=TelemetryTaxonomy)
    async def telemetry_taxonomy(
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> TelemetryTaxonomy:
        _tenant(auth.resolved.actor)
        response.headers["cache-control"] = "private, no-store"
        return TelemetryTaxonomy(
            events=[
                TelemetryTaxonomyItem(
                    event_name=name,
                    event_version=definition.event_version,
                    allowed_payload_keys=list(definition.allowed_payload_keys),
                )
                for name, definition in LEARNER_PRODUCT_ANALYTICS_EVENTS.items()
            ]
        )

    @router.post(
        "/telemetry/events",
        response_model=TelemetryBatchResult,
        status_code=status.HTTP_202_ACCEPTED,
    )
    @router.post(
        "/telemetry/batch",
        response_model=TelemetryBatchResult,
        status_code=status.HTTP_202_ACCEPTED,
        include_in_schema=False,
    )
    @router.post(
        "/analytics/events/batch",
        response_model=TelemetryBatchResult,
        status_code=status.HTTP_202_ACCEPTED,
        include_in_schema=False,
    )
    async def ingest_telemetry_batch(
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> TelemetryBatchResult:
        require_safe_origin(request, settings)
        response.headers["cache-control"] = "no-store"
        batch = await _parse_batch(request)
        _validate_event_schema(batch)
        actor = auth.resolved.actor
        tenant_id = _tenant(actor)
        # A request header is an untrusted correlation hint.  It is never
        # persisted as telemetry metadata; this trace is server-issued.
        trace_id = str(uuid4())
        expected_session_id = str(actor.session_id)
        if any(str(event.session_id) != expected_session_id for event in batch.events):
            raise TelemetrySessionBindingDenied(
                "Every telemetry event must use the authenticated session identifier."
            )
        if consent_resolver is None:
            raise TelemetryConsentUnavailable(
                "A server-owned telemetry consent resolver is required before storing events."
            )
        if configured_retention_days is None or configured_policy_id is None:
            raise TelemetryRetentionUnavailable(
                "An explicit telemetry retention policy is required before storing events."
            )
        if admission is None:
            raise TelemetryAdmissionUnavailable(
                "A tenant-aware telemetry admission seam is required before storing events."
            )

        now = datetime.now(UTC)
        try:
            authoritative_consent = await _resolve_consent(consent_resolver, auth.database, actor)
        except Exception as exc:
            raise TelemetryConsentUnavailable(
                "The server-owned telemetry consent policy could not be resolved."
            ) from exc
        if authoritative_consent is None:
            raise TelemetryConsentUnavailable(
                "A server-owned telemetry consent decision is required before storing events."
            )
        if not isinstance(authoritative_consent, TelemetryConsent):
            raise TelemetryConsentUnavailable(
                "The server-owned telemetry consent decision has an invalid shape."
            )
        _validate_consent_binding(authoritative_consent, actor)
        consent_status = getattr(
            authoritative_consent.status, "value", authoritative_consent.status
        )
        if consent_status != TelemetryConsentStatus.GRANTED.value:
            return TelemetryBatchResult(
                accepted=0,
                dropped=len(batch.events),
                reason="consent_required",
                trace_id=trace_id,
            )
        consent_purpose = getattr(
            authoritative_consent.purpose, "value", authoritative_consent.purpose
        )
        if consent_purpose != TELEMETRY_PURPOSE:
            return TelemetryBatchResult(
                accepted=0,
                dropped=len(batch.events),
                reason="consent_scope_not_authorized",
                trace_id=trace_id,
            )
        try:
            batch_bytes = validate_batch_size(batch)
            _validate_timestamps(batch, consent=authoritative_consent, now=now)
        except ValueError as exc:
            raise TelemetryEventInvalid(
                "The telemetry timestamp or batch size is invalid."
            ) from exc

        try:
            admitted = await _admit(
                admission,
                tenant_id=tenant_id,
                event_count=len(batch.events),
                payload_bytes=batch_bytes,
            )
        except Exception as exc:
            raise TelemetryBackpressure(
                "Telemetry intake admission could not be evaluated; retry later."
            ) from exc
        if not admitted:
            raise TelemetryBackpressure(
                "Telemetry intake is temporarily saturated; retry the batch later."
            )

        # Admission is intentionally not the final authorization decision.  A
        # consent grant can be revoked between the initial policy check and
        # this write.  Resolve it again through the same active transaction;
        # the composed resolver is responsible for selecting the authoritative
        # row with a write lock so a revoke cannot race the insert.
        try:
            authoritative_consent = await _resolve_consent(consent_resolver, auth.database, actor)
        except Exception as exc:
            raise TelemetryConsentUnavailable(
                "The server-owned telemetry consent policy could not be re-checked."
            ) from exc
        if authoritative_consent is None:
            raise TelemetryConsentUnavailable(
                "A current server-owned telemetry consent decision is required "
                "before storing events."
            )
        if not isinstance(authoritative_consent, TelemetryConsent):
            raise TelemetryConsentUnavailable(
                "The current server-owned telemetry consent decision has an invalid shape."
            )
        _validate_consent_binding(authoritative_consent, actor)
        consent_status = getattr(
            authoritative_consent.status, "value", authoritative_consent.status
        )
        if consent_status != TelemetryConsentStatus.GRANTED.value:
            return TelemetryBatchResult(
                accepted=0,
                dropped=len(batch.events),
                reason="consent_required",
                trace_id=trace_id,
            )
        consent_purpose = getattr(
            authoritative_consent.purpose, "value", authoritative_consent.purpose
        )
        if consent_purpose != TELEMETRY_PURPOSE:
            return TelemetryBatchResult(
                accepted=0,
                dropped=len(batch.events),
                reason="consent_scope_not_authorized",
                trace_id=trace_id,
            )
        try:
            _validate_timestamps(batch, consent=authoritative_consent, now=now)
        except ValueError as exc:
            raise TelemetryEventInvalid(
                "The telemetry timestamp or batch size is invalid."
            ) from exc

        retention_expires_at = now + timedelta(days=configured_retention_days)
        events = [
            AnalyticsEvent(
                event_id=str(event.event_id),
                tenant_id=tenant_id,
                actor_person_id=actor.person_id,
                subject_person_id=actor.person_id,
                event_name=event.event_name,
                event_version=event.event_version,
                event_class="product_analytics",
                occurred_at=ensure_utc(event.occurred_at),
                trace_id=trace_id,
                release_id=settings.release_id,
                session_id=str(event.session_id),
                route=event.route,
                period=(str(event.payload["period"]) if "period" in event.payload else None),
                payload=dict(event.payload),
                consent_status=str(consent_status),
                consent_purpose=str(consent_purpose),
                consent_policy_version=authoritative_consent.policy_version,
                consent_captured_at=ensure_utc(authoritative_consent.captured_at),
                retention_policy_id=configured_policy_id,
                retention_expires_at=retention_expires_at,
                created_at=now,
            )
            for event in batch.events
        ]
        try:
            # Re-check the immutable identity-bound grant immediately before
            # the repository write, inside the caller-owned transaction.
            def write(database):  # type: ignore[no-untyped-def]
                _validate_consent_binding(authoritative_consent, actor)
                return repository.add_analytics_events(database, events)

            stored, duplicates, stored_event_ids = await auth.database.run_sync(write)
        except AnalyticsEventReplayConflict as exc:
            raise TelemetryIdempotencyConflict(
                "An event id was replayed with a different immutable observation."
            ) from exc
        return TelemetryBatchResult(
            accepted=stored,
            duplicate=duplicates,
            accepted_event_ids=list(stored_event_ids),
            reason="duplicate_only" if stored == 0 and duplicates else None,
            trace_id=trace_id,
            retention_expires_at=retention_expires_at if stored else None,
        )

    application.include_router(router)


__all__ = [
    "TelemetryAdmissionUnavailable",
    "TelemetryBackpressure",
    "TelemetryBatchResult",
    "TelemetryConsentIdentityMismatch",
    "TelemetryConsentUnavailable",
    "TelemetryEventInvalid",
    "TelemetryIdempotencyConflict",
    "TelemetryRetentionUnavailable",
    "TelemetrySessionBindingDenied",
    "TelemetryTaxonomy",
    "TelemetryTaxonomyItem",
    "TelemetryTenantContextRequired",
    "install_telemetry_http",
]
