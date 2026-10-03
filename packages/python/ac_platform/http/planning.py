"""Authenticated planning and descriptive-analytics proposal routes.

The routes are intentionally read-model oriented.  They never create a
schedule, choose a next activity, or derive canonical progress from
analytics.  Analytics ingestion is disabled unless an application supplies an
authoritative consent resolver and an explicit retention policy.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ac_platform.application.settings import Settings
from ac_platform.catalog.models import Activity as CatalogActivity
from ac_platform.catalog.models import ProgramVersion
from ac_platform.enrollment.models import Enrollment
from ac_platform.http.auth import AuthenticatedTransaction, RequireActor, require_safe_origin
from ac_platform.kernel.authz import ActorContext
from ac_platform.kernel.errors import DomainError
from ac_platform.learning.models import ActivityState
from ac_platform.learning.planning import PROPOSED_ANALYTICS_EVENTS, PlanPeriod
from ac_platform.learning.planning_models import AnalyticsEvent
from ac_platform.learning.planning_repository import PlanningRepository, ensure_utc
from ac_platform.learning.services import (
    ActivityDefinition,
    SqlAlchemyLearningRepository,
    authoritative_progress,
)


class PlanningTenantContextRequired(DomainError):
    code = "planning_tenant_context_required"
    title = "A tenant context is required"
    status = 403


class PlanningSubjectDenied(DomainError):
    code = "planning_subject_denied"
    title = "The planning subject is unavailable"
    status = 403


class PlanningConsentUnavailable(DomainError):
    code = "consent_policy_not_configured"
    title = "Analytics consent policy is unavailable"
    status = 503


class PlanningRetentionUnavailable(DomainError):
    code = "retention_policy_not_configured"
    title = "Analytics retention policy is unavailable"
    status = 503


class PlanningEventInvalid(DomainError):
    code = "planning_event_invalid"
    title = "The analytics event is invalid"
    status = 422


class ConsentStatus(StrEnum):
    GRANTED = "granted"
    DENIED = "denied"
    NOT_PROVIDED = "not_provided"


class ConsentPurpose(StrEnum):
    PRODUCT_ANALYTICS = "product_analytics"


class PlanStatus(StrEnum):
    NOT_CONFIGURED = "not_configured"
    AVAILABLE = "available"


class UpNextStatus(StrEnum):
    NOT_CONFIGURED = "not_configured"
    AVAILABLE = "available"


class AnalyticsStatus(StrEnum):
    INSUFFICIENT_SIGNAL = "insufficient_signal"
    AVAILABLE = "available"


class ConsentSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ConsentStatus
    purpose: ConsentPurpose
    scope: Literal["product_analytics"]
    policy_version: str = Field(min_length=1, max_length=64)
    captured_at: datetime

    @field_validator("captured_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("captured_at must include a timezone")
        return value

    @field_validator("policy_version")
    @classmethod
    def require_policy_version(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("policy_version must not be blank")
        return normalized


_ROUTE_PATTERN = re.compile(r"^/[A-Za-z0-9/_{}?=&.:-]{0,180}$")
_PAYLOAD_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,48}$")
_PII_KEY_PATTERN = re.compile(
    r"(?:email|e[-_ ]?mail|phone|mobile|address|name|transcript|audio|recording|"
    r"token|secret|password|ip|device.?id|cookie|prompt|answer|message)",
    re.IGNORECASE,
)


class AnalyticsEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]+$",
    )
    event_name: str = Field(min_length=1, max_length=96)
    event_version: str = Field(default="1.0", min_length=1, max_length=16)
    occurred_at: datetime
    session_id: str | None = Field(default=None, min_length=1, max_length=128)
    route: str | None = Field(default=None, max_length=180)
    period: PlanPeriod | None = None
    subject_person_id: UUID | None = None
    payload: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    consent: ConsentSnapshot

    @field_validator("occurred_at")
    @classmethod
    def require_occurred_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("occurred_at must include a timezone")
        return value

    @field_validator("route")
    @classmethod
    def validate_route(cls, value: str | None) -> str | None:
        if value is not None and not _ROUTE_PATTERN.fullmatch(value):
            raise ValueError("route must be a relative application route")
        return value

    @field_validator("payload")
    @classmethod
    def validate_payload(
        cls, value: dict[str, str | int | float | bool | None]
    ) -> dict[str, str | int | float | bool | None]:
        if len(value) > 20:
            raise ValueError("payload may contain at most 20 scalar fields")
        for key, item in value.items():
            if not _PAYLOAD_KEY_PATTERN.fullmatch(key) or _PII_KEY_PATTERN.search(key):
                raise ValueError("payload keys must be bounded, lowercase, and non-PII")
            if isinstance(item, str) and len(item) > 256:
                raise ValueError("payload string values must be at most 256 characters")
        return value


class PlanItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    tenant_id: UUID
    person_id: UUID
    period: PlanPeriod
    title: str
    activity_id: UUID | None = None
    planned_for: date | None = None
    state: Literal["planned", "completed"] = "planned"
    source: Literal["explicit_learning_plan"] = "explicit_learning_plan"


class PlanView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period: PlanPeriod
    status: PlanStatus
    source: Literal["explicit_learning_plan"] = "explicit_learning_plan"
    items: list[PlanItemResponse] = Field(default_factory=list)
    message: str | None = None


class CanonicalProgressView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["empty", "available"]
    source: Literal["canonical_progress"] = "canonical_progress"
    person_id: UUID
    tenant_id: UUID
    enrollment_id: UUID | None = None
    completed_activity_ids: list[UUID] = Field(default_factory=list)
    in_progress_activity_ids: list[UUID] = Field(default_factory=list)
    required_activity_count: int | None = Field(default=None, ge=0)
    completed_activity_count: int | None = Field(default=None, ge=0)
    completion_ratio: float | None = Field(default=None, ge=0, le=1)
    last_updated_at: datetime | None = None
    message: str | None = None


class UpNextView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: UpNextStatus
    source: Literal["canonical_next_action_projection"] = "canonical_next_action_projection"
    item: PlanItemResponse | None = None
    message: str


class LearningInsight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal["descriptive_signal"] = "descriptive_signal"
    title: str
    detail: str
    observed_event_count: int = Field(ge=0)
    source_event_names: list[str] = Field(default_factory=list)


class AnalyticsView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: AnalyticsStatus
    source: Literal["descriptive_analytics_projection"] = "descriptive_analytics_projection"
    period: PlanPeriod | None = None
    freshness_as_of: datetime | None = None
    retained_event_count: int = Field(default=0, ge=0)
    insights: list[LearningInsight] = Field(default_factory=list)
    disclaimer: str = (
        "Descriptive product analytics only; never canonical progress, mastery, payment, "
        "entitlement, or access state."
    )


class DashboardView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_person_id: UUID
    tenant_id: UUID
    period: PlanPeriod
    plan: PlanView
    up_next: UpNextView
    canonical_progress: CanonicalProgressView
    analytics: AnalyticsView


class CalendarView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["explicit_learning_plan"] = "explicit_learning_plan"
    periods: dict[PlanPeriod, PlanView]
    disclaimer: str = (
        "Periods are explicit plan labels until controlled scheduling semantics are promoted."
    )


class TaxonomyItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_name: str
    event_version: str
    event_class: Literal["product_analytics"] = "product_analytics"
    authority: Literal["proposal"] = "proposal"
    ingestible_from_client: bool = True
    consent_required: bool = True
    allowed_payload_keys: list[str] = Field(default_factory=list)
    retention_policy_id: str | None = None


class TaxonomyView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[TaxonomyItem]
    disclaimer: str = "Proposal analytics events are not canonical domain facts or audit records."


class AnalyticsIngestResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    stored: bool
    duplicate: bool = False
    reason: str | None = None
    trace_id: str
    retention_expires_at: datetime | None = None


ConsentResolver = Callable[[ActorContext, AnalyticsEventRequest], ConsentSnapshot | None]


def _tenant(actor: ActorContext) -> UUID:
    if actor.tenant_id is None:
        raise PlanningTenantContextRequired("Select an active tenant before using planning.")
    return actor.tenant_id


def _subject(actor: ActorContext, requested: UUID | None) -> UUID:
    subject = requested or actor.person_id
    if subject != actor.person_id:
        raise PlanningSubjectDenied(
            "Planning projections are currently available only for the authenticated learner."
        )
    return subject


def _empty_progress(*, tenant_id: UUID, person_id: UUID, message: str) -> CanonicalProgressView:
    return CanonicalProgressView(
        status="empty",
        tenant_id=tenant_id,
        person_id=person_id,
        message=message,
    )


def _catalog_activity_definition(row: object, _version: object) -> ActivityDefinition:
    """Adapt catalog facts for the existing authoritative learning boundary."""

    return ActivityDefinition(
        id=row.id,  # type: ignore[attr-defined]
        kind=row.kind,  # type: ignore[attr-defined]
        module_id=row.module_id,  # type: ignore[attr-defined]
        program_version_id=row.program_version_id,  # type: ignore[attr-defined]
        program_id=row.program_id,  # type: ignore[attr-defined]
        program_scope=row.scope,  # type: ignore[attr-defined]
        program_owner_key=row.owner_key,  # type: ignore[attr-defined]
        title=row.title,  # type: ignore[attr-defined]
        order=row.position,  # type: ignore[attr-defined]
        required=row.is_required,  # type: ignore[attr-defined]
        version=f"activity:{row.id}",  # type: ignore[attr-defined]
        tenant_id=row.tenant_id,  # type: ignore[attr-defined]
    )


def _canonical_progress(
    database: Session, *, actor: ActorContext, tenant_id: UUID, person_id: UUID
) -> CanonicalProgressView:
    actor.require_tenant(tenant_id)
    actor.require_self(person_id)
    enrollments = tuple(
        database.scalars(
            select(Enrollment)
            .join(
                ProgramVersion,
                (ProgramVersion.id == Enrollment.program_version_id)
                & (ProgramVersion.program_id == Enrollment.program_id)
                & (ProgramVersion.scope == Enrollment.program_scope)
                & (ProgramVersion.owner_key == Enrollment.program_owner_key),
            )
            .where(
                Enrollment.tenant_id == tenant_id,
                Enrollment.person_id == person_id,
                Enrollment.status == "active",
                ProgramVersion.status.in_(("published", "superseded")),
            )
            .order_by(Enrollment.enrolled_at, Enrollment.id)
        )
    )
    if not enrollments:
        return _empty_progress(
            tenant_id=tenant_id,
            person_id=person_id,
            message="No canonical progress has been recorded for this learner yet.",
        )
    if len(enrollments) > 1:
        return _empty_progress(
            tenant_id=tenant_id,
            person_id=person_id,
            message=(
                "Canonical progress is unavailable until the active learning scope is unambiguous."
            ),
        )
    enrollment = enrollments[0]
    activity_ids = tuple(
        database.scalars(
            select(CatalogActivity.id).where(
                CatalogActivity.program_version_id == enrollment.program_version_id,
                CatalogActivity.program_id == enrollment.program_id,
                CatalogActivity.scope == enrollment.program_scope,
                CatalogActivity.owner_key == enrollment.program_owner_key,
            )
        )
    )
    if not activity_ids:
        return _empty_progress(
            tenant_id=tenant_id,
            person_id=person_id,
            message="The enrolled learning resource has no canonical activities yet.",
        )

    learning_repository = SqlAlchemyLearningRepository(
        database,
        activity_resolver=_catalog_activity_definition,
        reviewer_resolver=lambda _access: None,
    )
    try:
        access = learning_repository.resolve_scope(
            tenant_id=tenant_id,
            person_id=person_id,
            enrollment_id=enrollment.id,
            program_version_id=enrollment.program_version_id,
            activity_id=activity_ids[0],
        )
        authoritative = authoritative_progress(learning_repository, access)
    except DomainError:
        return _empty_progress(
            tenant_id=tenant_id,
            person_id=person_id,
            message="Canonical progress is unavailable for this learning scope.",
        )

    if not authoritative:
        return _empty_progress(
            tenant_id=tenant_id,
            person_id=person_id,
            message="No authoritative progress snapshot is available for this enrollment yet.",
        )

    required_activity_ids = frozenset(
        definition.id
        for module in access.program.modules
        for definition in module.activities
        if definition.required
    )
    completed = frozenset(
        activity_id
        for activity_id, progress in authoritative.items()
        if progress.state is ActivityState.COMPLETED and activity_id in required_activity_ids
    )
    in_progress = frozenset(
        activity_id
        for activity_id, progress in authoritative.items()
        if progress.state is ActivityState.IN_PROGRESS
    )
    completed_count = len(completed)
    denominator = len(required_activity_ids)
    return CanonicalProgressView(
        status="available",
        tenant_id=tenant_id,
        person_id=person_id,
        enrollment_id=enrollment.id,
        completed_activity_ids=sorted(completed, key=str),
        in_progress_activity_ids=sorted(in_progress, key=str),
        required_activity_count=denominator,
        completed_activity_count=completed_count,
        completion_ratio=completed_count / denominator if denominator else None,
        last_updated_at=max(
            (progress.updated_at for progress in authoritative.values()), default=None
        ),
    )


def _plan_view(
    repository: PlanningRepository,
    database: Session,
    *,
    completed_activity_ids: Collection[UUID],
    tenant_id: UUID,
    person_id: UUID,
    period: PlanPeriod,
) -> PlanView:
    rows = repository.list_plan_items(
        database, tenant_id=tenant_id, person_id=person_id, period=period
    )
    if not rows:
        return PlanView(
            period=period,
            status=PlanStatus.NOT_CONFIGURED,
            message="No explicit plan items are configured for this period.",
        )
    return PlanView(
        period=period,
        status=PlanStatus.AVAILABLE,
        items=[
            PlanItemResponse(
                id=row.id,
                tenant_id=row.tenant_id,
                person_id=row.person_id,
                period=PlanPeriod(row.period),
                title=row.title,
                activity_id=row.activity_id,
                planned_for=row.planned_for,
                state=(
                    "completed"
                    if row.activity_id is not None and row.activity_id in completed_activity_ids
                    else "planned"
                ),
            )
            for row in rows
        ],
    )


def _up_next(
    repository: PlanningRepository,
    database: Session,
    *,
    completed_activity_ids: Collection[UUID],
    tenant_id: UUID,
    person_id: UUID,
) -> UpNextView:
    projection = repository.get_next_action(database, tenant_id=tenant_id, person_id=person_id)
    if projection is None:
        return UpNextView(
            status=UpNextStatus.NOT_CONFIGURED,
            message="No explicit next action projection is available.",
        )
    item = repository.get_plan_item(
        database,
        tenant_id=tenant_id,
        person_id=person_id,
        plan_item_id=projection.plan_item_id,
    )
    if item is None:
        return UpNextView(
            status=UpNextStatus.NOT_CONFIGURED,
            message="The explicit next action is unavailable until its plan item is available.",
        )
    return UpNextView(
        status=UpNextStatus.AVAILABLE,
        item=PlanItemResponse(
            id=item.id,
            tenant_id=item.tenant_id,
            person_id=item.person_id,
            period=PlanPeriod(item.period),
            title=item.title,
            activity_id=item.activity_id,
            planned_for=item.planned_for,
            state=(
                "completed"
                if item.activity_id is not None and item.activity_id in completed_activity_ids
                else "planned"
            ),
        ),
        message=(
            "Projected from an explicit server-side next action; no automatic ordering "
            "was inferred."
        ),
    )


def _analytics_view(
    repository: PlanningRepository,
    database: Session,
    *,
    tenant_id: UUID,
    person_id: UUID,
    period: PlanPeriod | None,
    now: datetime,
) -> AnalyticsView:
    events = repository.list_analytics_events(
        database,
        tenant_id=tenant_id,
        person_id=person_id,
        period=period,
        now=now,
    )
    if not events:
        return AnalyticsView(status=AnalyticsStatus.INSUFFICIENT_SIGNAL, period=period)
    names = sorted({event.event_name for event in events})
    return AnalyticsView(
        status=AnalyticsStatus.AVAILABLE,
        period=period,
        freshness_as_of=max(event.occurred_at for event in events),
        retained_event_count=len(events),
        insights=[
            LearningInsight(
                id="descriptive:planning-interaction",
                title="Planning activity is present",
                detail=(
                    "A consented planning interaction was observed. This descriptive signal "
                    "does not judge mastery, completion, payment, entitlement, or access."
                ),
                observed_event_count=len(events),
                source_event_names=names,
            )
        ],
    )


def install_planning_http(
    application: FastAPI,
    *,
    settings: Settings,
    require_actor: RequireActor,
    consent_resolver: ConsentResolver | None = None,
    retention_days: int | None = None,
    retention_policy_id: str | None = None,
    legacy_analytics_enabled: bool = False,
) -> None:
    """Install bounded planning reads and explicitly opted-in proposal writes.

    The legacy single-event ``/v1/analytics/events`` route is disabled by
    default.  Phase 2 composition uses ``/v1/telemetry/events``; callers that
    intentionally exercise the older proposal adapter must opt in explicitly
    and must not use it as a production activation path.
    """

    if legacy_analytics_enabled and settings.environment != "test":
        raise RuntimeError("the legacy analytics adapter is restricted to the test environment")
    if retention_days is not None and retention_days <= 0:
        retention_days = None
    if retention_policy_id is not None:
        retention_policy_id = retention_policy_id.strip() or None

    router = APIRouter(prefix="/v1", tags=["planning"])
    actor_dependency = Depends(require_actor)
    repository = PlanningRepository()

    @router.get("/learning/plans", response_model=PlanView)
    async def learning_plans(
        response: Response,
        period: Annotated[PlanPeriod, Query()] = PlanPeriod.TODAY,
        subject_person_id: Annotated[UUID | None, Query()] = None,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> PlanView:
        actor = auth.resolved.actor
        tenant_id = _tenant(actor)
        person_id = _subject(actor, subject_person_id)

        def read(database: Session) -> PlanView:
            canonical = _canonical_progress(
                database, actor=actor, tenant_id=tenant_id, person_id=person_id
            )
            return _plan_view(
                repository,
                database,
                completed_activity_ids=canonical.completed_activity_ids,
                tenant_id=tenant_id,
                person_id=person_id,
                period=period,
            )

        result = await auth.database.run_sync(read)
        response.headers["cache-control"] = "private, no-store"
        return result

    @router.get("/learning/up-next", response_model=UpNextView)
    async def learning_up_next(
        response: Response,
        subject_person_id: Annotated[UUID | None, Query()] = None,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> UpNextView:
        actor = auth.resolved.actor
        tenant_id = _tenant(actor)
        person_id = _subject(actor, subject_person_id)

        def read(database: Session) -> UpNextView:
            canonical = _canonical_progress(
                database, actor=actor, tenant_id=tenant_id, person_id=person_id
            )
            return _up_next(
                repository,
                database,
                completed_activity_ids=canonical.completed_activity_ids,
                tenant_id=tenant_id,
                person_id=person_id,
            )

        result = await auth.database.run_sync(read)
        response.headers["cache-control"] = "private, no-store"
        return result

    @router.get("/learning/progress", response_model=CanonicalProgressView)
    async def learning_progress(
        response: Response,
        subject_person_id: Annotated[UUID | None, Query()] = None,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> CanonicalProgressView:
        actor = auth.resolved.actor
        tenant_id = _tenant(actor)
        person_id = _subject(actor, subject_person_id)
        result = await auth.database.run_sync(
            lambda database: _canonical_progress(
                database, actor=actor, tenant_id=tenant_id, person_id=person_id
            )
        )
        response.headers["cache-control"] = "private, no-store"
        return result

    @router.get("/learning/insights", response_model=AnalyticsView)
    async def learning_insights(
        response: Response,
        period: Annotated[PlanPeriod | None, Query()] = None,
        subject_person_id: Annotated[UUID | None, Query()] = None,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> AnalyticsView:
        actor = auth.resolved.actor
        tenant_id = _tenant(actor)
        person_id = _subject(actor, subject_person_id)
        now = datetime.now(UTC)
        result = await auth.database.run_sync(
            lambda database: _analytics_view(
                repository,
                database,
                tenant_id=tenant_id,
                person_id=person_id,
                period=period,
                now=now,
            )
        )
        response.headers["cache-control"] = "private, no-store"
        return result

    @router.get("/learning/dashboard", response_model=DashboardView)
    @router.get("/learning/home", response_model=DashboardView)
    async def learning_home(
        response: Response,
        period: Annotated[PlanPeriod, Query()] = PlanPeriod.TODAY,
        subject_person_id: Annotated[UUID | None, Query()] = None,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> DashboardView:
        actor = auth.resolved.actor
        tenant_id = _tenant(actor)
        person_id = _subject(actor, subject_person_id)
        now = datetime.now(UTC)

        def read(database: Session) -> DashboardView:
            canonical_progress = _canonical_progress(
                database, actor=actor, tenant_id=tenant_id, person_id=person_id
            )
            return DashboardView(
                subject_person_id=person_id,
                tenant_id=tenant_id,
                period=period,
                plan=_plan_view(
                    repository,
                    database,
                    completed_activity_ids=canonical_progress.completed_activity_ids,
                    tenant_id=tenant_id,
                    person_id=person_id,
                    period=period,
                ),
                up_next=_up_next(
                    repository,
                    database,
                    completed_activity_ids=canonical_progress.completed_activity_ids,
                    tenant_id=tenant_id,
                    person_id=person_id,
                ),
                canonical_progress=canonical_progress,
                analytics=_analytics_view(
                    repository,
                    database,
                    tenant_id=tenant_id,
                    person_id=person_id,
                    period=period,
                    now=now,
                ),
            )

        result = await auth.database.run_sync(read)
        response.headers["cache-control"] = "private, no-store"
        return result

    @router.get("/learning/calendar", response_model=CalendarView)
    async def learning_calendar(
        response: Response,
        subject_person_id: Annotated[UUID | None, Query()] = None,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> CalendarView:
        actor = auth.resolved.actor
        tenant_id = _tenant(actor)
        person_id = _subject(actor, subject_person_id)

        def read(database: Session) -> CalendarView:
            canonical_progress = _canonical_progress(
                database, actor=actor, tenant_id=tenant_id, person_id=person_id
            )
            return CalendarView(
                periods={
                    period: _plan_view(
                        repository,
                        database,
                        completed_activity_ids=canonical_progress.completed_activity_ids,
                        tenant_id=tenant_id,
                        person_id=person_id,
                        period=period,
                    )
                    for period in PlanPeriod
                }
            )

        result = await auth.database.run_sync(read)
        response.headers["cache-control"] = "private, no-store"
        return result

    @router.get("/analytics/taxonomy", response_model=TaxonomyView)
    async def analytics_taxonomy(
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> TaxonomyView:
        _tenant(auth.resolved.actor)
        result = TaxonomyView(
            events=[
                TaxonomyItem(
                    event_name=name,
                    event_version=str(definition["event_version"]),
                    allowed_payload_keys=list(definition["allowed_payload_keys"]),
                    retention_policy_id=retention_policy_id,
                )
                for name, definition in PROPOSED_ANALYTICS_EVENTS.items()
            ]
        )
        response.headers["cache-control"] = "private, no-store"
        return result

    async def ingest_analytics_event(
        body: AnalyticsEventRequest,
        request: Request,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> AnalyticsIngestResult:
        require_safe_origin(request, settings)
        actor = auth.resolved.actor
        tenant_id = _tenant(actor)
        subject_person_id = _subject(actor, body.subject_person_id)
        definition = PROPOSED_ANALYTICS_EVENTS.get(body.event_name)
        if definition is None:
            raise PlanningEventInvalid("The analytics event is not in the proposal allowlist.")
        if body.event_version != definition["event_version"]:
            raise PlanningEventInvalid("The analytics event version is not supported.")
        if bool(definition["requires_period"]) and body.period is None:
            raise PlanningEventInvalid("This analytics event requires a period label.")
        allowed_payload_keys = set(definition["allowed_payload_keys"])
        if set(body.payload) - allowed_payload_keys:
            raise PlanningEventInvalid("The analytics payload contains a non-allowlisted key.")
        if "period" in body.payload and (
            body.period is None or body.payload["period"] != body.period.value
        ):
            raise PlanningEventInvalid("The analytics period payload does not match the period.")
        if consent_resolver is None:
            raise PlanningConsentUnavailable(
                "A verified product-analytics consent resolver is required before storing events."
            )
        authoritative_consent = consent_resolver(actor, body)
        if authoritative_consent is None:
            raise PlanningConsentUnavailable(
                "A verified product-analytics consent resolver is required before storing events."
            )
        if authoritative_consent.status is not ConsentStatus.GRANTED:
            return AnalyticsIngestResult(
                event_id=body.event_id,
                stored=False,
                reason="consent_required",
                trace_id=getattr(request.state, "request_id", "unavailable"),
            )
        if (
            authoritative_consent.purpose is not ConsentPurpose.PRODUCT_ANALYTICS
            or authoritative_consent.scope != "product_analytics"
        ):
            return AnalyticsIngestResult(
                event_id=body.event_id,
                stored=False,
                reason="consent_scope_not_authorized",
                trace_id=getattr(request.state, "request_id", "unavailable"),
            )
        if retention_days is None or retention_policy_id is None:
            raise PlanningRetentionUnavailable(
                "An explicit analytics retention policy is required before storing events."
            )
        now = datetime.now(UTC)
        occurred_at = ensure_utc(body.occurred_at)
        captured_at = ensure_utc(authoritative_consent.captured_at)
        if occurred_at > now or captured_at > now:
            raise PlanningEventInvalid("Analytics timestamps must not be in the future.")
        retention_expires_at = now + timedelta(days=retention_days)
        event = AnalyticsEvent(
            event_id=body.event_id,
            tenant_id=tenant_id,
            actor_person_id=actor.person_id,
            subject_person_id=subject_person_id,
            event_name=body.event_name,
            event_version=body.event_version,
            occurred_at=occurred_at,
            trace_id=getattr(request.state, "request_id", "unavailable"),
            release_id=settings.release_id,
            session_id=body.session_id,
            route=body.route,
            period=body.period.value if body.period is not None else None,
            payload=dict(body.payload),
            consent_status=authoritative_consent.status.value,
            consent_purpose=authoritative_consent.purpose.value,
            consent_policy_version=authoritative_consent.policy_version,
            consent_captured_at=captured_at,
            retention_policy_id=retention_policy_id,
            retention_expires_at=retention_expires_at,
            created_at=now,
        )
        stored = await auth.database.run_sync(
            lambda database: repository.add_analytics_event(database, event)
        )
        return AnalyticsIngestResult(
            event_id=body.event_id,
            stored=stored,
            duplicate=not stored,
            reason=None if stored else "duplicate_event_id",
            trace_id=event.trace_id,
            retention_expires_at=retention_expires_at,
        )

    if legacy_analytics_enabled:
        router.add_api_route(
            "/analytics/events",
            ingest_analytics_event,
            methods=["POST"],
            response_model=AnalyticsIngestResult,
            status_code=status.HTTP_202_ACCEPTED,
        )

    application.include_router(router)


__all__ = [
    "AnalyticsEventRequest",
    "AnalyticsIngestResult",
    "AnalyticsStatus",
    "AnalyticsView",
    "CalendarView",
    "CanonicalProgressView",
    "ConsentPurpose",
    "ConsentSnapshot",
    "ConsentStatus",
    "DashboardView",
    "LearningInsight",
    "PlanItemResponse",
    "PlanPeriod",
    "PlanStatus",
    "PlanView",
    "PlanningConsentUnavailable",
    "PlanningEventInvalid",
    "PlanningRetentionUnavailable",
    "PlanningSubjectDenied",
    "PlanningTenantContextRequired",
    "TaxonomyItem",
    "TaxonomyView",
    "UpNextStatus",
    "UpNextView",
    "install_planning_http",
]
