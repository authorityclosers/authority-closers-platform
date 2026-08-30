"""HTTP composition for the G1 learner learning boundary.

The learning domain is synchronous at its repository edge.  These routes use
``AsyncSession.run_sync`` so the domain work participates in the transaction
opened by :class:`AuthenticatedTransaction`; this module never opens,
commits, or rolls back a second transaction.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from enum import Enum
from typing import Annotated, Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, Path, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ac_platform.application.settings import Settings
from ac_platform.catalog.models import Activity as CatalogActivity
from ac_platform.catalog.models import ProgramVersion
from ac_platform.enrollment.models import Enrollment
from ac_platform.http.auth import AuthenticatedTransaction, RequireActor, require_safe_origin
from ac_platform.kernel.authz import ActorContext
from ac_platform.kernel.errors import DomainError, ResourceNotFound
from ac_platform.learning.services import (
    ActivityDefinition,
    ActivityState,
    DraftSnapshot,
    EvidenceCorrectionSnapshot,
    EvidenceSnapshot,
    EvidenceSubmissionSnapshot,
    EvidenceType,
    LearningAccessContext,
    LearningCommandBundle,
    PlaybackSessionSnapshot,
    ProgressProjector,
    ReviewDecision,
    SqlAlchemyLearningRepository,
    VideoEvidencePolicy,
    WatchIntervalKind,
    WatchIntervalSnapshot,
)

MAX_IDEMPOTENCY_KEY_LENGTH = 128
MAX_PLAYBACK_TOKEN_LENGTH = 512
_ETAG_PATTERN = re.compile(
    r'^"(?P<kind>draft|activity|submission|playback)-revision-(?P<revision>0|[1-9][0-9]*)"$'
)

ActivityResolver = Callable[[object, object], ActivityDefinition]
ReviewerResolver = Callable[[LearningAccessContext], UUID | None]
PolicyResolver = Callable[[LearningAccessContext], VideoEvidencePolicy]


class LearningTenantContextRequired(DomainError):
    code = "learning_tenant_context_required"
    title = "A tenant context is required"
    status = 403


class LearningResourceUnavailable(ResourceNotFound):
    code = "learning_resource_unavailable"
    title = "Learning resource not found"


class MissingIdempotencyKey(DomainError):
    code = "idempotency_key_required"
    title = "An idempotency key is required"
    status = 428


class InvalidLearningETag(DomainError):
    code = "invalid_if_match"
    title = "The If-Match value is invalid"
    status = 400


class MissingLearningETag(DomainError):
    code = "if_match_required"
    title = "An If-Match value is required"
    status = 428


class MissingPlaybackToken(DomainError):
    code = "playback_token_required"
    title = "A playback token is required"
    status = 401


class ActivityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    module_id: UUID
    program_version_id: UUID
    kind: str
    title: str
    state: ActivityState
    revision: int
    required: bool
    explanation: dict[str, Any]


class ModuleLearningResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    title: str
    activities: list[ActivityRequest]


class LearningResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    program_id: UUID
    program_version_id: UUID
    enrollment_id: UUID
    modules: list[ModuleLearningResponse]
    projection: dict[str, Any]


class ActivityDetailResponse(ActivityRequest):
    model_config = ConfigDict(extra="forbid")

    enrollment_id: UUID


class DraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payload: dict[str, Any] = Field(default_factory=dict)


class DraftResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    activity_id: UUID
    revision: int
    status: str
    payload: dict[str, Any]
    saved_at: datetime


class EvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_type: Literal["video_watch", "reflection", "implementation", "review", "improvement"]
    payload: dict[str, Any] = Field(default_factory=dict)
    playback_session_id: UUID | None = None
    playback_token: str | None = Field(
        default=None, min_length=1, max_length=MAX_PLAYBACK_TOKEN_LENGTH
    )


class EvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: UUID
    submission_id: UUID
    activity_id: UUID
    evidence_type: str
    submission_status: str


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "rejected", "needs_revision"]
    reason: str = Field(min_length=1, max_length=1000)


class ReviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    correction_id: UUID
    submission_id: UUID
    decision: str
    correction_sequence: int


class PlaybackStartResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    activity_id: UUID
    session_token: str
    revision: int
    expires_at: datetime
    duration_seconds: float


class PlaybackEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    event_id: str = Field(min_length=1, max_length=128)
    sequence: int = Field(ge=1, le=1_000_000_000)
    start_seconds: float = Field(ge=0, le=86_400)
    end_seconds: float = Field(ge=0, le=86_400)
    kind: Literal["watch", "seek"] = "watch"


class PlaybackEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    interval_id: UUID
    sequence: int
    revision: int
    observed_at: datetime


class PlaybackFinishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID


class PlaybackFinishResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    activity_id: UUID
    revision: int
    status: str
    closed_at: datetime | None


def _default_activity_resolver(row: object, _version: object) -> ActivityDefinition:
    """Resolve catalog facts without inventing content or scoring policy."""

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


def _missing_policy(_access: LearningAccessContext) -> VideoEvidencePolicy:
    raise DomainError("No server-owned playback policy is configured for this deployment.")


def _etag(kind: str, revision: int) -> str:
    return f'"{kind}-revision-{revision}"'


def _revision(if_match: str | None, *, kind: str) -> int:
    if if_match is None:
        raise MissingLearningETag("Optimistic learning mutations require If-Match.")
    match = _ETAG_PATTERN.fullmatch(if_match.strip())
    if match is None or match.group("kind") != kind:
        raise InvalidLearningETag(f"If-Match must be the canonical {kind} revision ETag.")
    return int(match.group("revision"))


def _enum_value(value: object) -> str:
    if isinstance(value, Enum):
        raw = value.value
        return raw if isinstance(raw, str) else str(raw)
    return str(value)


def _activity_state(value: ActivityState | str) -> ActivityState:
    return value if isinstance(value, ActivityState) else ActivityState(value)


def _idempotency(value: str | None) -> str:
    if value is None or not value.strip():
        raise MissingIdempotencyKey("Mutating learning commands require Idempotency-Key.")
    return value.strip()


def _tenant(actor: ActorContext) -> UUID:
    if actor.tenant_id is None:
        raise LearningTenantContextRequired("Select an active tenant before using learning.")
    return actor.tenant_id


def _no_store(response: Response, *, kind: str | None = None, revision: int | None = None) -> None:
    response.headers["cache-control"] = "no-store"
    response.headers["pragma"] = "no-cache"
    if kind is not None and revision is not None:
        response.headers["etag"] = _etag(kind, revision)


def _draft_response(draft: DraftSnapshot) -> DraftResponse:
    return DraftResponse(
        id=draft.id,
        activity_id=draft.activity_id,
        revision=draft.revision,
        status=_enum_value(draft.status),
        payload=dict(draft.payload),
        saved_at=draft.saved_at,
    )


def _evidence_response(
    evidence: EvidenceSnapshot, submission: EvidenceSubmissionSnapshot
) -> EvidenceResponse:
    return EvidenceResponse(
        evidence_id=evidence.id,
        submission_id=submission.id,
        activity_id=evidence.activity_id,
        evidence_type=_enum_value(evidence.evidence_type),
        submission_status=_enum_value(submission.status),
    )


def _require_playback_token(value: str | None) -> str:
    if value is None or not value.strip():
        raise MissingPlaybackToken("The opaque playback token is required.")
    return value


def _scope_for_program(
    database: Session, actor: ActorContext, program_id: UUID
) -> tuple[Enrollment, ProgramVersion]:
    tenant_id = _tenant(actor)
    row = database.execute(
        select(Enrollment, ProgramVersion)
        .join(
            ProgramVersion,
            (ProgramVersion.id == Enrollment.program_version_id)
            & (ProgramVersion.program_id == Enrollment.program_id)
            & (ProgramVersion.scope == Enrollment.program_scope)
            & (ProgramVersion.owner_key == Enrollment.program_owner_key),
        )
        .where(
            Enrollment.tenant_id == tenant_id,
            Enrollment.person_id == actor.person_id,
            Enrollment.program_id == program_id,
            Enrollment.status == "active",
            ProgramVersion.status.in_(("published", "superseded")),
        )
    ).one_or_none()
    if row is None:
        raise LearningResourceUnavailable("The enrolled learning resource is unavailable.")
    return cast(tuple[Enrollment, ProgramVersion], row)


def _scope_for_activity(
    database: Session, actor: ActorContext, activity_id: UUID
) -> tuple[Enrollment, ProgramVersion, CatalogActivity]:
    tenant_id = _tenant(actor)
    row = database.execute(
        select(Enrollment, ProgramVersion, CatalogActivity)
        .join(
            ProgramVersion,
            (ProgramVersion.id == Enrollment.program_version_id)
            & (ProgramVersion.program_id == Enrollment.program_id)
            & (ProgramVersion.scope == Enrollment.program_scope)
            & (ProgramVersion.owner_key == Enrollment.program_owner_key),
        )
        .join(
            CatalogActivity,
            (CatalogActivity.id == activity_id)
            & (CatalogActivity.program_version_id == ProgramVersion.id)
            & (CatalogActivity.program_id == ProgramVersion.program_id)
            & (CatalogActivity.scope == ProgramVersion.scope)
            & (CatalogActivity.owner_key == ProgramVersion.owner_key),
        )
        .where(
            Enrollment.tenant_id == tenant_id,
            Enrollment.person_id == actor.person_id,
            Enrollment.status == "active",
            ProgramVersion.status.in_(("published", "superseded")),
        )
    ).one_or_none()
    if row is None:
        raise LearningResourceUnavailable("The enrolled activity is unavailable.")
    return cast(tuple[Enrollment, ProgramVersion, CatalogActivity], row)


def _bundle(
    database: Session,
    *,
    activity_resolver: ActivityResolver,
    reviewer_resolver: ReviewerResolver,
    policy_resolver: PolicyResolver,
) -> LearningCommandBundle:
    repository = SqlAlchemyLearningRepository(
        database,
        activity_resolver=activity_resolver,
        reviewer_resolver=reviewer_resolver,
    )
    return LearningCommandBundle(
        repository,
        clock=lambda: datetime.now(UTC),
        policy_resolver=policy_resolver,
    )


async def _run_in_auth_transaction[ResultT](
    auth: AuthenticatedTransaction,
    operation: Callable[[Session], ResultT],
) -> ResultT:
    """Run sync learning services on the authenticated session's transaction."""

    return cast(ResultT, await auth.database.run_sync(operation))


def install_learning_http(
    application: FastAPI,
    *,
    settings: Settings,
    require_actor: RequireActor,
    activity_resolver: ActivityResolver | None = None,
    reviewer_resolver: ReviewerResolver | None = None,
    policy_resolver: PolicyResolver | None = None,
) -> None:
    """Install the G1 learning routes around the authenticated transaction.

    Playback routes are intentionally not registered until a server-owned
    ``policy_resolver`` is supplied.  The catalog currently has no durable
    video policy/content fields, so a default policy would weaken authority.
    """

    resolved_activity = activity_resolver or _default_activity_resolver
    resolved_reviewer = reviewer_resolver or (lambda _access: None)
    resolved_policy = policy_resolver or _missing_policy
    router = APIRouter(prefix="/v1", tags=["learning"])
    actor_dependency = Depends(require_actor)

    def bundle_for(database: Session) -> LearningCommandBundle:
        return _bundle(
            database,
            activity_resolver=resolved_activity,
            reviewer_resolver=resolved_reviewer,
            policy_resolver=resolved_policy,
        )

    @router.get("/learning/{program_id}", response_model=LearningResponse)
    async def get_learning(
        program_id: Annotated[UUID, Path()],
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> LearningResponse:
        actor = auth.resolved.actor

        def read(database: Session) -> LearningResponse:
            enrollment, version = _scope_for_program(database, actor, program_id)
            catalog_activities = tuple(
                database.scalars(
                    select(CatalogActivity)
                    .where(
                        CatalogActivity.program_version_id == version.id,
                        CatalogActivity.program_id == version.program_id,
                        CatalogActivity.scope == version.scope,
                        CatalogActivity.owner_key == version.owner_key,
                    )
                    .order_by(
                        CatalogActivity.module_id, CatalogActivity.position, CatalogActivity.id
                    )
                )
            )
            if not catalog_activities:
                raise LearningResourceUnavailable("The enrolled learning resource is unavailable.")
            bundle = bundle_for(database)
            first_access = bundle.store.resolve_access(
                actor=actor,
                tenant_id=_tenant(actor),
                enrollment_id=enrollment.id,
                program_version_id=version.id,
                activity_id=catalog_activities[0].id,
            )
            progress = {
                item.activity_id: item
                for item in bundle.store.list_progress(
                    tenant_id=_tenant(actor),
                    person_id=actor.person_id,
                    enrollment_id=enrollment.id,
                    program_version_id=version.id,
                )
            }
            explanation = ProgressProjector().explain(first_access.program, progress)
            by_module: dict[UUID, list[ActivityRequest]] = {}
            for module in first_access.program.modules:
                for definition in module.activities:
                    current = progress.get(definition.id)
                    state = bundle.activities.current_state(
                        actor=actor,
                        tenant_id=_tenant(actor),
                        enrollment_id=enrollment.id,
                        program_version_id=version.id,
                        activity_id=definition.id,
                    )
                    by_module.setdefault(module.id, []).append(
                        ActivityRequest(
                            id=definition.id,
                            module_id=definition.module_id,
                            program_version_id=definition.program_version_id,
                            kind=_enum_value(definition.kind),
                            title=definition.title,
                            state=state,
                            revision=current.revision if current else 0,
                            required=definition.required,
                            explanation=next(
                                (
                                    item.as_dict()
                                    for item in explanation.activity_reasons
                                    if item.activity_id == definition.id
                                ),
                                {"activity_id": str(definition.id), "state": _enum_value(state)},
                            ),
                        )
                    )
            return LearningResponse(
                program_id=first_access.program.id,
                program_version_id=version.id,
                enrollment_id=enrollment.id,
                modules=[
                    ModuleLearningResponse(
                        id=module.id,
                        title=module.title,
                        activities=by_module.get(module.id, []),
                    )
                    for module in first_access.program.modules
                ],
                projection=explanation.as_dict(),
            )

        result = await _run_in_auth_transaction(auth, read)
        _no_store(response)
        return result

    @router.get("/activities/{activity_id}", response_model=ActivityDetailResponse)
    async def get_activity(
        activity_id: Annotated[UUID, Path()],
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> ActivityDetailResponse:
        actor = auth.resolved.actor

        def read(database: Session) -> ActivityDetailResponse:
            enrollment, version, _catalog = _scope_for_activity(database, actor, activity_id)
            bundle = bundle_for(database)
            access = bundle.store.resolve_access(
                actor=actor,
                tenant_id=_tenant(actor),
                enrollment_id=enrollment.id,
                program_version_id=version.id,
                activity_id=activity_id,
            )
            progress = bundle.store.get_progress(*access.scope)
            state = bundle.activities.current_state(
                actor=actor,
                tenant_id=_tenant(actor),
                enrollment_id=enrollment.id,
                program_version_id=version.id,
                activity_id=activity_id,
            )
            progress_by_activity = {
                item.activity_id: item
                for item in bundle.store.list_progress(
                    tenant_id=_tenant(actor),
                    person_id=actor.person_id,
                    enrollment_id=enrollment.id,
                    program_version_id=version.id,
                )
            }
            explanation = ProgressProjector().explain(access.program, progress_by_activity)
            reason = next(
                (
                    item.as_dict()
                    for item in explanation.activity_reasons
                    if item.activity_id == activity_id
                ),
                {"activity_id": str(activity_id), "state": _enum_value(state)},
            )
            return ActivityDetailResponse(
                id=access.activity.id,
                module_id=access.activity.module_id,
                program_version_id=access.program_version_id,
                kind=_enum_value(access.activity.kind),
                title=access.activity.title,
                state=state,
                revision=progress.revision if progress else 0,
                required=access.activity.required,
                explanation=reason,
                enrollment_id=enrollment.id,
            )

        result = await _run_in_auth_transaction(auth, read)
        _no_store(response, kind="activity", revision=result.revision)
        return result

    @router.put("/activities/{activity_id}/draft", response_model=DraftResponse)
    async def save_draft(
        activity_id: Annotated[UUID, Path()],
        request: Request,
        response: Response,
        body: DraftRequest,
        if_match: Annotated[str | None, Header(alias="If-Match", max_length=96)] = None,
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key", max_length=MAX_IDEMPOTENCY_KEY_LENGTH)
        ] = None,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> DraftResponse:
        require_safe_origin(request, settings)
        actor = auth.resolved.actor
        expected_revision = _revision(if_match, kind="draft")
        command_key = _idempotency(idempotency_key)

        def mutate(database: Session) -> DraftSnapshot:
            enrollment, version, _catalog = _scope_for_activity(database, actor, activity_id)
            return bundle_for(database).drafts.save(
                actor=actor,
                tenant_id=_tenant(actor),
                enrollment_id=enrollment.id,
                program_version_id=version.id,
                activity_id=activity_id,
                payload=body.payload,
                expected_revision=expected_revision,
                idempotency_key=command_key,
            )

        result = await _run_in_auth_transaction(auth, mutate)
        _no_store(response, kind="draft", revision=result.revision)
        return _draft_response(result)

    @router.post("/activities/{activity_id}/evidence", response_model=EvidenceResponse)
    async def submit_evidence(
        activity_id: Annotated[UUID, Path()],
        request: Request,
        response: Response,
        body: EvidenceRequest,
        if_match: Annotated[str | None, Header(alias="If-Match", max_length=96)] = None,
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key", max_length=MAX_IDEMPOTENCY_KEY_LENGTH)
        ] = None,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> EvidenceResponse:
        require_safe_origin(request, settings)
        actor = auth.resolved.actor
        expected_revision = _revision(if_match, kind="activity")
        command_key = _idempotency(idempotency_key)

        def mutate(
            database: Session,
        ) -> tuple[EvidenceSnapshot, EvidenceSubmissionSnapshot, int]:
            enrollment, version, _catalog = _scope_for_activity(database, actor, activity_id)
            bundle = bundle_for(database)
            evidence, submission = bundle.evidence.submit(
                actor=actor,
                tenant_id=_tenant(actor),
                enrollment_id=enrollment.id,
                program_version_id=version.id,
                activity_id=activity_id,
                evidence_type=EvidenceType(body.evidence_type),
                idempotency_key=command_key,
                expected_revision=expected_revision,
                payload=body.payload,
                playback_session_id=body.playback_session_id,
                session_token=body.playback_token,
            )
            progress = bundle.store.get_progress(
                _tenant(actor),
                enrollment.id,
                actor.person_id,
                version.id,
                activity_id,
            )
            if progress is None:
                raise DomainError("The evidence command completed without progress state.")
            return evidence, submission, progress.revision

        evidence, submission, progress_revision = await _run_in_auth_transaction(auth, mutate)
        _no_store(response)
        response.status_code = status.HTTP_201_CREATED
        response.headers["etag"] = _etag("activity", progress_revision)
        return _evidence_response(evidence, submission)

    @router.post("/evidence/{submission_id}/review", response_model=ReviewResponse)
    async def review_evidence(
        submission_id: Annotated[UUID, Path()],
        request: Request,
        response: Response,
        body: ReviewRequest,
        if_match: Annotated[str | None, Header(alias="If-Match", max_length=96)] = None,
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key", max_length=MAX_IDEMPOTENCY_KEY_LENGTH)
        ] = None,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> ReviewResponse:
        require_safe_origin(request, settings)
        actor = auth.resolved.actor
        expected_revision = _revision(if_match, kind="submission")
        command_key = _idempotency(idempotency_key)

        def mutate(database: Session) -> EvidenceCorrectionSnapshot:
            return bundle_for(database).evidence.review_submission(
                actor=actor,
                tenant_id=_tenant(actor),
                submission_id=submission_id,
                decision=ReviewDecision(body.decision),
                reason=body.reason,
                expected_revision=expected_revision,
                idempotency_key=command_key,
            )

        correction = await _run_in_auth_transaction(auth, mutate)
        _no_store(response, kind="submission", revision=correction.correction_sequence)
        return ReviewResponse(
            correction_id=correction.id,
            submission_id=correction.submission_id,
            decision=_enum_value(correction.decision),
            correction_sequence=correction.correction_sequence,
        )

    if policy_resolver is not None:

        @router.post(
            "/activities/{activity_id}/playback/start", response_model=PlaybackStartResponse
        )
        async def start_playback(
            activity_id: Annotated[UUID, Path()],
            request: Request,
            response: Response,
            if_match: Annotated[str | None, Header(alias="If-Match", max_length=96)] = None,
            idempotency_key: Annotated[
                str | None,
                Header(alias="Idempotency-Key", max_length=MAX_IDEMPOTENCY_KEY_LENGTH),
            ] = None,
            auth: AuthenticatedTransaction = actor_dependency,
        ) -> PlaybackStartResponse:
            require_safe_origin(request, settings)
            actor = auth.resolved.actor
            expected_revision = _revision(if_match, kind="activity")
            command_key = _idempotency(idempotency_key)

            def mutate(database: Session) -> PlaybackSessionSnapshot:
                enrollment, version, _catalog = _scope_for_activity(database, actor, activity_id)
                return bundle_for(database).playback.start_session(
                    actor=actor,
                    tenant_id=_tenant(actor),
                    enrollment_id=enrollment.id,
                    program_version_id=version.id,
                    activity_id=activity_id,
                    expected_revision=expected_revision,
                    idempotency_key=command_key,
                )

            session = await _run_in_auth_transaction(auth, mutate)
            _no_store(response, kind="playback", revision=session.revision)
            return PlaybackStartResponse(
                session_id=session.id,
                activity_id=session.activity_id,
                session_token=session.session_token or "",
                revision=session.revision,
                expires_at=session.expires_at,
                duration_seconds=session.duration_seconds,
            )

        @router.post(
            "/activities/{activity_id}/playback/heartbeat", response_model=PlaybackEventResponse
        )
        async def heartbeat_playback(
            activity_id: Annotated[UUID, Path()],
            request: Request,
            response: Response,
            body: PlaybackEventRequest,
            playback_token: Annotated[
                str | None, Header(alias="X-Playback-Token", max_length=MAX_PLAYBACK_TOKEN_LENGTH)
            ] = None,
            idempotency_key: Annotated[
                str | None,
                Header(alias="Idempotency-Key", max_length=MAX_IDEMPOTENCY_KEY_LENGTH),
            ] = None,
            auth: AuthenticatedTransaction = actor_dependency,
        ) -> PlaybackEventResponse:
            require_safe_origin(request, settings)
            actor = auth.resolved.actor
            command_key = _idempotency(idempotency_key)
            token = _require_playback_token(playback_token)

            def mutate(database: Session) -> WatchIntervalSnapshot:
                enrollment, version, _catalog = _scope_for_activity(database, actor, activity_id)
                return bundle_for(database).playback.record_event(
                    actor=actor,
                    tenant_id=_tenant(actor),
                    enrollment_id=enrollment.id,
                    program_version_id=version.id,
                    activity_id=activity_id,
                    session_id=body.session_id,
                    session_token=token,
                    event_id=body.event_id,
                    sequence=body.sequence,
                    start_seconds=body.start_seconds,
                    end_seconds=body.end_seconds,
                    kind=WatchIntervalKind(body.kind),
                    idempotency_key=command_key,
                )

            interval = await _run_in_auth_transaction(auth, mutate)
            _no_store(response)
            return PlaybackEventResponse(
                session_id=interval.playback_session_id,
                interval_id=interval.id,
                sequence=interval.sequence,
                revision=interval.sequence,
                observed_at=interval.observed_at,
            )

        @router.post(
            "/activities/{activity_id}/playback/finish", response_model=PlaybackFinishResponse
        )
        async def finish_playback(
            activity_id: Annotated[UUID, Path()],
            request: Request,
            response: Response,
            body: PlaybackFinishRequest,
            if_match: Annotated[str | None, Header(alias="If-Match", max_length=96)] = None,
            playback_token: Annotated[
                str | None, Header(alias="X-Playback-Token", max_length=MAX_PLAYBACK_TOKEN_LENGTH)
            ] = None,
            idempotency_key: Annotated[
                str | None,
                Header(alias="Idempotency-Key", max_length=MAX_IDEMPOTENCY_KEY_LENGTH),
            ] = None,
            auth: AuthenticatedTransaction = actor_dependency,
        ) -> PlaybackFinishResponse:
            require_safe_origin(request, settings)
            actor = auth.resolved.actor
            expected_revision = _revision(if_match, kind="playback")
            command_key = _idempotency(idempotency_key)
            token = _require_playback_token(playback_token)

            def mutate(database: Session) -> PlaybackSessionSnapshot:
                enrollment, version, _catalog = _scope_for_activity(database, actor, activity_id)
                return bundle_for(database).playback.close_session(
                    actor=actor,
                    tenant_id=_tenant(actor),
                    enrollment_id=enrollment.id,
                    program_version_id=version.id,
                    activity_id=activity_id,
                    session_id=body.session_id,
                    session_token=token,
                    expected_revision=expected_revision,
                    idempotency_key=command_key,
                )

            session = await _run_in_auth_transaction(auth, mutate)
            _no_store(response, kind="playback", revision=session.revision)
            return PlaybackFinishResponse(
                session_id=session.id,
                activity_id=session.activity_id,
                revision=session.revision,
                status=_enum_value(session.status),
                closed_at=session.closed_at,
            )

    application.include_router(router)


__all__ = [
    "ActivityDetailResponse",
    "ActivityRequest",
    "DraftRequest",
    "DraftResponse",
    "EvidenceRequest",
    "EvidenceResponse",
    "InvalidLearningETag",
    "LearningResponse",
    "LearningTenantContextRequired",
    "MissingIdempotencyKey",
    "MissingLearningETag",
    "MissingPlaybackToken",
    "ModuleLearningResponse",
    "PlaybackEventRequest",
    "PlaybackEventResponse",
    "PlaybackFinishRequest",
    "PlaybackFinishResponse",
    "PlaybackStartResponse",
    "ReviewRequest",
    "ReviewResponse",
    "install_learning_http",
]
