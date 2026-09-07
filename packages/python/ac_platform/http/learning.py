"""HTTP composition for the G1 learner learning boundary.

The learning domain is synchronous at its repository edge.  These routes use
``AsyncSession.run_sync`` so the domain work participates in the transaction
opened by :class:`AuthenticatedTransaction`; this module never opens,
commits, or rolls back a second transaction.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from enum import Enum
from typing import Annotated, Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, Path, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ac_platform.application.settings import Settings
from ac_platform.catalog.models import Activity as CatalogActivity
from ac_platform.catalog.models import ActivityKind, ProgramVersion
from ac_platform.catalog.models import Program as CatalogProgram
from ac_platform.enrollment.models import Enrollment, Entitlement
from ac_platform.http.auth import AuthenticatedTransaction, RequireActor, require_safe_origin
from ac_platform.kernel.authz import ActorContext
from ac_platform.kernel.errors import DomainError, ResourceNotFound
from ac_platform.learning.catalog_activity import resolve_catalog_activity
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
    authoritative_progress,
)
from ac_platform.media.api_contracts import ActivityMediaDescriptorResponse

MAX_IDEMPOTENCY_KEY_LENGTH = 128
MAX_PLAYBACK_TOKEN_LENGTH = 512
MAX_LEARNING_COLLECTION_PAGE = 50
MAX_LEARNING_CURSOR_LENGTH = 512
_ETAG_PATTERN = re.compile(
    r'^"(?P<kind>draft|activity|submission|playback)-revision-(?P<revision>0|[1-9][0-9]*)"$'
)

ActivityResolver = Callable[[object, object], ActivityDefinition]
PromptResolver = Callable[[object, object], str | None]
ReviewerResolver = Callable[[LearningAccessContext], UUID | None]
PolicyResolver = Callable[[LearningAccessContext], VideoEvidencePolicy]
ActivityMediaResolver = Callable[[Session, UUID, object, object], object | None]
MediaDescriptorResolver = Callable[
    [Session, ActorContext, LearningAccessContext], ActivityMediaDescriptorResponse | None
]


class LearningTenantContextRequired(DomainError):
    code = "learning_tenant_context_required"
    title = "A tenant context is required"
    status = 403


class InvalidLearningCursor(DomainError):
    code = "invalid_learning_cursor"
    title = "The learning collection cursor is invalid"
    status = 400


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


class ActivityActionUnavailable(DomainError):
    code = "activity_action_unavailable"
    title = "This activity action is unavailable"
    status = 403


type ActivityAllowedAction = Literal["save_draft", "submit_evidence", "complete_video"]


class ActivityReasonResponse(BaseModel):
    """The exact server-owned activity reason projection exposed to learners."""

    model_config = ConfigDict(extra="forbid")

    activity_id: UUID
    state: ActivityState
    required: bool
    reason: str
    missing_activity_ids: list[UUID]
    missing_module_ids: list[UUID]


class LearningProjectionResponse(BaseModel):
    """The exact progress projection consumed by the learner web app."""

    model_config = ConfigDict(extra="forbid")

    scope_type: str
    scope_id: UUID
    program_version: str
    projection_version: str
    denominator: int
    completed_count: int
    percentage: float
    predicate: str
    missing_module_ids: list[UUID]
    activity_reasons: list[ActivityReasonResponse]


class ActivityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    module_id: UUID
    program_version_id: UUID
    position: int
    kind: str
    title: str
    prompt: str | None
    state: ActivityState
    revision: int
    required: bool
    explanation: ActivityReasonResponse
    allowed_actions: list[ActivityAllowedAction]


class ModuleLearningResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    position: int
    title: str
    activities: list[ActivityRequest]


class LearningResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    program_id: UUID
    program_version_id: UUID
    program_slug: str
    program_title: str
    version_number: int
    enrollment_id: UUID
    modules: list[ModuleLearningResponse]
    projection: LearningProjectionResponse


type LearningCourseState = Literal["in_progress", "completed", "unavailable"]
type LearningSavedState = Literal["saved", "unavailable"]


class LearningCourseSummaryResponse(BaseModel):
    """A server-authorized course row for the learner's library.

    The collection intentionally exposes only facts that are backed by the
    active enrollment, entitlement, published version, and canonical progress
    projection.  ``saved_state`` stays unavailable until a durable course
    bookmark projection exists; activity drafts are not course bookmarks.
    """

    model_config = ConfigDict(extra="forbid")

    program_id: UUID
    program_version_id: UUID
    program_slug: str
    program_title: str
    version_number: int
    enrollment_id: UUID
    enrolled_at: datetime
    updated_at: datetime
    state: LearningCourseState
    saved_state: LearningSavedState = "unavailable"
    projection: LearningProjectionResponse | None = None


class LearningCollectionResponse(BaseModel):
    """The canonical learner-owned/enrolled course collection."""

    model_config = ConfigDict(extra="forbid")

    items: list[LearningCourseSummaryResponse]
    next_cursor: str | None
    saved_filter_available: bool = False


class ActivityDetailResponse(ActivityRequest):
    model_config = ConfigDict(extra="forbid")

    program_id: UUID
    enrollment_id: UUID
    draft_revision: int
    draft_payload: dict[str, Any] | None
    media: ActivityMediaDescriptorResponse | None = None


class DraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payload: dict[str, Any] = Field(default_factory=dict)


class DraftResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    activity_id: UUID
    revision: int
    activity_revision: int
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
    activity_revision: int
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
    return resolve_catalog_activity(row, _version)


def _default_activity_prompt_resolver(row: object, _version: object) -> str | None:
    """Read only the explicit learner prompt field from catalog data.

    Legacy catalog rows may have no prompt. Returning ``None`` is intentional:
    the learner surface must not turn an activity title or a progress
    explanation into instructions.
    """

    value = getattr(row, "prompt", None)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


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


def _allowed_actions(
    access: LearningAccessContext,
    *,
    state: ActivityState,
    prompt: str | None,
    playback_enabled: bool,
) -> list[ActivityAllowedAction]:
    if state not in {ActivityState.AVAILABLE, ActivityState.IN_PROGRESS} or prompt is None:
        return []
    actions: list[ActivityAllowedAction] = ["save_draft"]
    kind = ActivityKind(_enum_value(access.activity.kind).upper())
    if kind is ActivityKind.VIDEO:
        if (
            playback_enabled
            and access.activity.video_duration_seconds is not None
            and getattr(access.activity, "media_binding_id", None) is not None
            and getattr(access.activity, "media_asset_id", None) is not None
            and getattr(access.activity, "media_version_id", None) is not None
        ):
            actions.append("complete_video")
        return actions
    reviewer_id = access.assigned_reviewer_id
    if reviewer_id is not None and reviewer_id != access.person_id:
        actions.append("submit_evidence")
    return actions


def _require_action(
    action: ActivityAllowedAction,
    allowed_actions: list[ActivityAllowedAction],
) -> None:
    if action not in allowed_actions:
        raise ActivityActionUnavailable(
            "The server has not enabled this action for the current activity state."
        )


def _reason_response(
    explanation: object,
    *,
    activity_id: UUID,
    state: ActivityState,
    required: bool,
) -> ActivityReasonResponse:
    for item in explanation.activity_reasons:  # type: ignore[attr-defined]
        if item.activity_id == activity_id:
            return ActivityReasonResponse.model_validate(item.as_dict())
    return ActivityReasonResponse(
        activity_id=activity_id,
        state=state,
        required=required,
        reason="server_resolved_activity_state",
        missing_activity_ids=[],
        missing_module_ids=[],
    )


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


def _draft_response(draft: DraftSnapshot, *, activity_revision: int) -> DraftResponse:
    return DraftResponse(
        id=draft.id,
        activity_id=draft.activity_id,
        revision=draft.revision,
        activity_revision=activity_revision,
        status=_enum_value(draft.status),
        payload=dict(draft.payload),
        saved_at=draft.saved_at,
    )


def _evidence_response(
    evidence: EvidenceSnapshot,
    submission: EvidenceSubmissionSnapshot,
    *,
    activity_revision: int,
) -> EvidenceResponse:
    return EvidenceResponse(
        evidence_id=evidence.id,
        submission_id=submission.id,
        activity_id=evidence.activity_id,
        activity_revision=activity_revision,
        evidence_type=_enum_value(evidence.evidence_type),
        submission_status=_enum_value(submission.status),
    )


def _require_playback_token(value: str | None) -> str:
    if value is None or not value.strip():
        raise MissingPlaybackToken("The opaque playback token is required.")
    return value


def _scope_for_program(
    database: Session,
    actor: ActorContext,
    program_id: UUID,
    *,
    enrollment_id: UUID | None = None,
    program_version_id: UUID | None = None,
) -> tuple[Enrollment, ProgramVersion, CatalogProgram]:
    tenant_id = _tenant(actor)
    statement = (
        select(Enrollment, ProgramVersion, CatalogProgram)
        .join(
            ProgramVersion,
            (ProgramVersion.id == Enrollment.program_version_id)
            & (ProgramVersion.program_id == Enrollment.program_id)
            & (ProgramVersion.scope == Enrollment.program_scope)
            & (ProgramVersion.owner_key == Enrollment.program_owner_key),
        )
        .join(
            CatalogProgram,
            (CatalogProgram.id == ProgramVersion.program_id)
            & (CatalogProgram.scope == ProgramVersion.scope)
            & (CatalogProgram.owner_key == ProgramVersion.owner_key),
        )
        .where(
            Enrollment.tenant_id == tenant_id,
            Enrollment.person_id == actor.person_id,
            Enrollment.program_id == program_id,
            Enrollment.status == "active",
            ProgramVersion.status.in_(("published", "superseded")),
        )
    )
    if enrollment_id is not None:
        statement = statement.where(Enrollment.id == enrollment_id)
    if program_version_id is not None:
        statement = statement.where(Enrollment.program_version_id == program_version_id)
    rows = database.execute(statement).all()
    if len(rows) != 1:
        raise LearningResourceUnavailable("The enrolled learning resource is unavailable.")
    return cast(tuple[Enrollment, ProgramVersion, CatalogProgram], rows[0])


def _learner_learning_scopes(
    database: Session,
    actor: ActorContext,
    *,
    limit: int,
    cursor: str | None = None,
) -> tuple[tuple[Enrollment, ProgramVersion, CatalogProgram], ...]:
    """Return only active, fully scoped learner access rows.

    Enrollment is not sufficient to expose a course.  The entitlement join is
    deliberately repeated across the full scope identity so a stale or
    cross-tenant row cannot turn into a learner-owned card.
    """

    tenant_id = _tenant(actor)
    statement = (
        select(Enrollment, ProgramVersion, CatalogProgram)
        .join(
            ProgramVersion,
            (ProgramVersion.id == Enrollment.program_version_id)
            & (ProgramVersion.program_id == Enrollment.program_id)
            & (ProgramVersion.scope == Enrollment.program_scope)
            & (ProgramVersion.owner_key == Enrollment.program_owner_key),
        )
        .join(
            CatalogProgram,
            (CatalogProgram.id == ProgramVersion.program_id)
            & (CatalogProgram.scope == ProgramVersion.scope)
            & (CatalogProgram.owner_key == ProgramVersion.owner_key),
        )
        .join(
            Entitlement,
            (Entitlement.tenant_id == Enrollment.tenant_id)
            & (Entitlement.enrollment_id == Enrollment.id)
            & (Entitlement.person_id == Enrollment.person_id)
            & (Entitlement.program_version_id == Enrollment.program_version_id)
            & (Entitlement.program_id == Enrollment.program_id)
            & (Entitlement.program_scope == Enrollment.program_scope)
            & (Entitlement.program_owner_key == Enrollment.program_owner_key),
        )
        .where(
            Enrollment.tenant_id == tenant_id,
            Enrollment.person_id == actor.person_id,
            Enrollment.status == "active",
            Entitlement.status == "active",
            ProgramVersion.status.in_(("published", "superseded")),
        )
        .order_by(
            CatalogProgram.title.asc(),
            ProgramVersion.version_number.asc(),
            Enrollment.id.asc(),
        )
    )
    decoded_cursor = _decode_learning_cursor(cursor)
    if decoded_cursor is not None:
        title, version_number, enrollment_id = decoded_cursor
        statement = statement.where(
            or_(
                CatalogProgram.title > title,
                and_(
                    CatalogProgram.title == title,
                    ProgramVersion.version_number > version_number,
                ),
                and_(
                    CatalogProgram.title == title,
                    ProgramVersion.version_number == version_number,
                    Enrollment.id > enrollment_id,
                ),
            )
        )
    # Fetch one sentinel row so the HTTP boundary can truthfully advertise a
    # next cursor without making the cursor itself part of canonical state.
    statement = statement.limit(limit + 1)
    return tuple(
        cast(tuple[Enrollment, ProgramVersion, CatalogProgram], row)
        for row in database.execute(statement).all()
    )


def _encode_learning_cursor(
    scope: tuple[Enrollment, ProgramVersion, CatalogProgram],
) -> str:
    enrollment, version, catalog_program = scope
    payload = json.dumps(
        {
            "title": catalog_program.title,
            "version_number": version.version_number,
            "enrollment_id": str(enrollment.id),
        },
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_learning_cursor(
    value: str | None,
) -> tuple[str, int, UUID] | None:
    if value is None:
        return None
    if not value or len(value) > MAX_LEARNING_CURSOR_LENGTH:
        raise InvalidLearningCursor("The learning collection cursor is invalid.")
    try:
        padding = "=" * (-len(value) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(f"{value}{padding}").decode("utf-8"))
        title = decoded["title"]
        version_number = decoded["version_number"]
        enrollment_id = UUID(decoded["enrollment_id"])
    except (
        KeyError,
        TypeError,
        ValueError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        binascii.Error,
    ):
        raise InvalidLearningCursor("The learning collection cursor is invalid.") from None
    if (
        not isinstance(title, str)
        or not title
        or len(title) > 200
        or isinstance(version_number, bool)
        or not isinstance(version_number, int)
        or version_number <= 0
    ):
        raise InvalidLearningCursor("The learning collection cursor is invalid.")
    return title, version_number, enrollment_id


def _learning_course_state(
    projection: LearningProjectionResponse | None,
) -> LearningCourseState:
    """Map only a complete canonical projection to a learner-facing state."""

    if projection is None or projection.denominator <= 0:
        return "unavailable"
    if projection.completed_count >= projection.denominator:
        return "completed"
    return "in_progress"


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
    activity_media_resolver: ActivityMediaResolver | None = None,
) -> LearningCommandBundle:
    repository = SqlAlchemyLearningRepository(
        database,
        activity_resolver=activity_resolver,
        reviewer_resolver=reviewer_resolver,
        activity_media_resolver=activity_media_resolver,
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
    prompt_resolver: PromptResolver | None = None,
    reviewer_resolver: ReviewerResolver | None = None,
    policy_resolver: PolicyResolver | None = None,
    activity_media_resolver: ActivityMediaResolver | None = None,
    media_descriptor_resolver: MediaDescriptorResolver | None = None,
) -> None:
    """Install the G1 learning routes around the authenticated transaction.

    Playback routes are intentionally not registered until a server-owned
    ``policy_resolver`` is supplied.  The catalog currently has no durable
    video policy/content fields, so a default policy would weaken authority.
    """

    resolved_activity = activity_resolver or _default_activity_resolver
    resolved_prompt = prompt_resolver or _default_activity_prompt_resolver
    resolved_reviewer = reviewer_resolver or (lambda _access: None)
    resolved_policy = policy_resolver or _missing_policy
    playback_enabled = policy_resolver is not None
    router = APIRouter(prefix="/v1", tags=["learning"])
    actor_dependency = Depends(require_actor)

    def bundle_for(database: Session) -> LearningCommandBundle:
        return _bundle(
            database,
            activity_resolver=resolved_activity,
            reviewer_resolver=resolved_reviewer,
            policy_resolver=resolved_policy,
            activity_media_resolver=activity_media_resolver,
        )

    @router.get("/learning", response_model=LearningCollectionResponse)
    async def get_learning_collection(
        response: Response,
        limit: Annotated[int, Query(ge=1, le=MAX_LEARNING_COLLECTION_PAGE)] = (
            MAX_LEARNING_COLLECTION_PAGE
        ),
        cursor: Annotated[str | None, Query(max_length=MAX_LEARNING_CURSOR_LENGTH)] = None,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> LearningCollectionResponse:
        """Return the authenticated learner's complete course library page.

        Every row is selected from active enrollment + active entitlement and
        then projected from the pinned catalog version.  No public catalog
        fallback is used, so the library cannot present a course merely
        because it is published or because analytics mention it.
        """

        actor = auth.resolved.actor

        def read(database: Session) -> LearningCollectionResponse:
            all_scopes = _learner_learning_scopes(
                database,
                actor,
                limit=limit,
                cursor=cursor,
            )
            has_more = len(all_scopes) > limit
            scopes = all_scopes[:limit]
            bundle = bundle_for(database)
            items: list[LearningCourseSummaryResponse] = []
            for enrollment, version, catalog_program in scopes:
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
                            CatalogActivity.module_id,
                            CatalogActivity.position,
                            CatalogActivity.id,
                        )
                    )
                )
                projection: LearningProjectionResponse | None = None
                if catalog_activities:
                    access = bundle.store.resolve_access(
                        actor=actor,
                        tenant_id=_tenant(actor),
                        enrollment_id=enrollment.id,
                        program_version_id=version.id,
                        activity_id=catalog_activities[0].id,
                    )
                    progress = authoritative_progress(bundle.store, access)
                    explanation = ProgressProjector(access.program.projection_version).explain(
                        access.program, progress
                    )
                    projection = LearningProjectionResponse.model_validate(explanation.as_dict())
                items.append(
                    LearningCourseSummaryResponse(
                        program_id=version.program_id,
                        program_version_id=version.id,
                        program_slug=catalog_program.slug,
                        program_title=catalog_program.title,
                        version_number=version.version_number,
                        enrollment_id=enrollment.id,
                        enrolled_at=enrollment.enrolled_at,
                        updated_at=enrollment.updated_at,
                        state=_learning_course_state(projection),
                        projection=projection,
                    )
                )
            return LearningCollectionResponse(
                items=items,
                next_cursor=_encode_learning_cursor(scopes[-1]) if has_more and scopes else None,
                saved_filter_available=False,
            )

        result = await _run_in_auth_transaction(auth, read)
        _no_store(response)
        return result

    @router.get("/learning/{program_id}", response_model=LearningResponse)
    async def get_learning(
        program_id: Annotated[UUID, Path()],
        response: Response,
        enrollment_id: Annotated[UUID | None, Query()] = None,
        program_version_id: Annotated[UUID | None, Query()] = None,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> LearningResponse:
        actor = auth.resolved.actor

        def read(database: Session) -> LearningResponse:
            enrollment, version, catalog_program = _scope_for_program(
                database,
                actor,
                program_id,
                enrollment_id=enrollment_id,
                program_version_id=program_version_id,
            )
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
            prompts = {row.id: resolved_prompt(row, version) for row in catalog_activities}
            bundle = bundle_for(database)
            first_access = bundle.store.resolve_access(
                actor=actor,
                tenant_id=_tenant(actor),
                enrollment_id=enrollment.id,
                program_version_id=version.id,
                activity_id=catalog_activities[0].id,
            )
            progress = authoritative_progress(bundle.store, first_access)
            explanation = ProgressProjector().explain(first_access.program, progress)
            by_module: dict[UUID, list[ActivityRequest]] = {}
            for module in first_access.program.modules:
                for definition in module.activities:
                    current = progress.get(definition.id)
                    access = bundle.store.resolve_access(
                        actor=actor,
                        tenant_id=_tenant(actor),
                        enrollment_id=enrollment.id,
                        program_version_id=version.id,
                        activity_id=definition.id,
                    )
                    state = bundle.activities.current_state(
                        actor=actor,
                        tenant_id=_tenant(actor),
                        enrollment_id=enrollment.id,
                        program_version_id=version.id,
                        activity_id=definition.id,
                    )
                    prompt = None if state is ActivityState.LOCKED else prompts.get(definition.id)
                    by_module.setdefault(module.id, []).append(
                        ActivityRequest(
                            id=definition.id,
                            module_id=definition.module_id,
                            program_version_id=definition.program_version_id,
                            position=definition.order,
                            kind=_enum_value(definition.kind),
                            title=definition.title,
                            prompt=prompt,
                            state=state,
                            revision=current.revision if current else 0,
                            required=definition.required,
                            explanation=_reason_response(
                                explanation,
                                activity_id=definition.id,
                                state=state,
                                required=definition.required,
                            ),
                            allowed_actions=_allowed_actions(
                                access,
                                state=state,
                                prompt=prompt,
                                playback_enabled=playback_enabled,
                            ),
                        )
                    )
            return LearningResponse(
                program_id=first_access.program.id,
                program_version_id=version.id,
                program_slug=catalog_program.slug,
                program_title=catalog_program.title,
                version_number=version.version_number,
                enrollment_id=enrollment.id,
                modules=[
                    ModuleLearningResponse(
                        id=module.id,
                        position=module.order,
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
            enrollment, version, catalog_activity = _scope_for_activity(
                database, actor, activity_id
            )
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
            progress_by_activity = authoritative_progress(bundle.store, access)
            explanation = ProgressProjector().explain(access.program, progress_by_activity)
            reason = _reason_response(
                explanation,
                activity_id=activity_id,
                state=state,
                required=access.activity.required,
            )
            prompt = (
                None
                if state is ActivityState.LOCKED
                else resolved_prompt(catalog_activity, version)
            )
            draft = (
                None
                if state is ActivityState.LOCKED
                else bundle.drafts.get(
                    actor=actor,
                    tenant_id=_tenant(actor),
                    enrollment_id=enrollment.id,
                    program_version_id=version.id,
                    activity_id=activity_id,
                )
            )
            media = (
                None
                if state is ActivityState.LOCKED or media_descriptor_resolver is None
                else media_descriptor_resolver(database, actor, access)
            )
            return ActivityDetailResponse(
                id=access.activity.id,
                module_id=access.activity.module_id,
                program_version_id=access.program_version_id,
                position=access.activity.order,
                kind=_enum_value(access.activity.kind),
                title=access.activity.title,
                prompt=prompt,
                state=state,
                revision=progress.revision if progress else 0,
                required=access.activity.required,
                explanation=reason,
                allowed_actions=_allowed_actions(
                    access,
                    state=state,
                    prompt=prompt,
                    playback_enabled=playback_enabled,
                ),
                program_id=enrollment.program_id,
                enrollment_id=enrollment.id,
                draft_revision=draft.revision if draft is not None else 0,
                draft_payload=dict(draft.payload) if draft is not None else None,
                media=media,
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

        def mutate(database: Session) -> tuple[DraftSnapshot, int]:
            enrollment, version, catalog_activity = _scope_for_activity(
                database, actor, activity_id
            )
            bundle = bundle_for(database)
            access = bundle.store.resolve_access(
                actor=actor,
                tenant_id=_tenant(actor),
                enrollment_id=enrollment.id,
                program_version_id=version.id,
                activity_id=activity_id,
            )
            activity_state = bundle.activities.current_state(
                actor=actor,
                tenant_id=_tenant(actor),
                enrollment_id=enrollment.id,
                program_version_id=version.id,
                activity_id=activity_id,
            )
            prompt = (
                None
                if activity_state is ActivityState.LOCKED
                else resolved_prompt(catalog_activity, version)
            )
            _require_action(
                "save_draft",
                _allowed_actions(
                    access,
                    state=activity_state,
                    prompt=prompt,
                    playback_enabled=playback_enabled,
                ),
            )
            draft = bundle.drafts.save(
                actor=actor,
                tenant_id=_tenant(actor),
                enrollment_id=enrollment.id,
                program_version_id=version.id,
                activity_id=activity_id,
                payload=body.payload,
                expected_revision=expected_revision,
                idempotency_key=command_key,
            )
            progress = bundle.store.get_progress(
                _tenant(actor),
                enrollment.id,
                actor.person_id,
                version.id,
                activity_id,
            )
            if progress is None:
                raise DomainError("The draft command completed without progress state.")
            return draft, progress.revision

        result, activity_revision = await _run_in_auth_transaction(auth, mutate)
        _no_store(response, kind="draft", revision=result.revision)
        return _draft_response(result, activity_revision=activity_revision)

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
            enrollment, version, catalog_activity = _scope_for_activity(
                database, actor, activity_id
            )
            bundle = bundle_for(database)
            access = bundle.store.resolve_access(
                actor=actor,
                tenant_id=_tenant(actor),
                enrollment_id=enrollment.id,
                program_version_id=version.id,
                activity_id=activity_id,
            )
            activity_state = bundle.activities.current_state(
                actor=actor,
                tenant_id=_tenant(actor),
                enrollment_id=enrollment.id,
                program_version_id=version.id,
                activity_id=activity_id,
            )
            prompt = (
                None
                if activity_state is ActivityState.LOCKED
                else resolved_prompt(catalog_activity, version)
            )
            required_action: ActivityAllowedAction = (
                "complete_video"
                if body.evidence_type == EvidenceType.VIDEO_WATCH.value
                else "submit_evidence"
            )
            _require_action(
                required_action,
                _allowed_actions(
                    access,
                    state=activity_state,
                    prompt=prompt,
                    playback_enabled=playback_enabled,
                ),
            )
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
        return _evidence_response(
            evidence,
            submission,
            activity_revision=progress_revision,
        )

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
                enrollment, version, catalog_activity = _scope_for_activity(
                    database, actor, activity_id
                )
                bundle = bundle_for(database)
                access = bundle.store.resolve_access(
                    actor=actor,
                    tenant_id=_tenant(actor),
                    enrollment_id=enrollment.id,
                    program_version_id=version.id,
                    activity_id=activity_id,
                )
                activity_state = bundle.activities.current_state(
                    actor=actor,
                    tenant_id=_tenant(actor),
                    enrollment_id=enrollment.id,
                    program_version_id=version.id,
                    activity_id=activity_id,
                )
                prompt = (
                    None
                    if activity_state is ActivityState.LOCKED
                    else resolved_prompt(catalog_activity, version)
                )
                _require_action(
                    "complete_video",
                    _allowed_actions(
                        access,
                        state=activity_state,
                        prompt=prompt,
                        playback_enabled=playback_enabled,
                    ),
                )
                return bundle.playback.start_session(
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
    "ActivityActionUnavailable",
    "ActivityAllowedAction",
    "ActivityDetailResponse",
    "ActivityRequest",
    "DraftRequest",
    "DraftResponse",
    "EvidenceRequest",
    "EvidenceResponse",
    "InvalidLearningETag",
    "LearningCollectionResponse",
    "LearningCourseState",
    "LearningCourseSummaryResponse",
    "LearningSavedState",
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
