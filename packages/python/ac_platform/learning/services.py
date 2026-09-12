"""Trust-bound learning commands for the G1 learning slice.

The public command services require an :class:`~ac_platform.kernel.authz.ActorContext`
and an access context resolved by the repository.  No caller-supplied boolean
can grant membership, enrollment, entitlement, catalog, or reviewer access.
``InMemoryLearningStore`` and ``InMemoryLearningService`` are deliberately
named test seams.  Production construction is provided by
``SqlAlchemyLearningUnitOfWork`` and ``LearningService``.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import math
import secrets
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Any, Protocol, Self, TypeVar, cast
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from ac_platform.catalog.models import ActivityKind
from ac_platform.kernel.authz import ActorContext
from ac_platform.kernel.errors import (
    AuthorizationDenied,
    DomainError,
    InvalidEvidence,
    ResourceConflict,
    ResourceNotFound,
)
from ac_platform.learning.models import (
    ActivityDraft,
    ActivityProgress,
    ActivityState,
    DraftStatus,
    EvidenceCorrection,
    EvidenceSubmission,
    EvidenceSubmissionStatus,
    EvidenceType,
    LearningCommandIdempotency,
    LearningCommandStatus,
    LearningEvidence,
    LearningProgressProjection,
    PlaybackSession,
    PlaybackSessionStatus,
    ProjectionScope,
    ReviewDecision,
    VideoWatchInterval,
    WatchIntervalKind,
)

DEFAULT_PROGRESS_PROJECTION_VERSION = "learning-progress-v1"
DEFAULT_VIDEO_POLICY_VERSION = "video-coverage-v1"
DEFAULT_VIDEO_COVERAGE_THRESHOLD = 0.90
GLOBAL_CATALOG_OWNER = UUID(int=0)
MAX_DRAFT_PAYLOAD_BYTES = 64 * 1024
MAX_EVIDENCE_PAYLOAD_BYTES = 256 * 1024
LEARNING_REVIEW_PERMISSION = "learning_review"
LEARNER_ROLE = "learner"
REVIEWER_ROLES = frozenset({"support", "admin", "owner"})
HUMAN_REVIEW_POLICY_VERSION = "human-review-v1"

T = TypeVar("T")


def _utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _server_now(clock: Callable[[], datetime]) -> datetime:
    return _utc(clock())


def _text(value: str, field_name: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise InvalidLearningInput(f"{field_name} must not be blank")
    if len(normalized) > maximum:
        raise InvalidLearningInput(f"{field_name} must be at most {maximum} characters")
    return normalized


def _number(value: float | int, field_name: str) -> float:
    if isinstance(value, bool):
        raise ImpossibleEvidenceError(f"{field_name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ImpossibleEvidenceError(f"{field_name} must be a finite number")
    return number


def _activity_kind(value: ActivityKind | str) -> ActivityKind:
    if isinstance(value, ActivityKind):
        return value
    try:
        return ActivityKind(value.strip().upper())
    except (AttributeError, ValueError) as exc:
        raise InvalidLearningInput("activity kind is not exposed in the first slice") from exc


def _activity_state(value: ActivityState | str) -> ActivityState:
    if isinstance(value, ActivityState):
        return value
    try:
        return ActivityState(value.strip().lower())
    except (AttributeError, ValueError) as exc:
        raise InvalidLearningInput("activity state is not supported") from exc


def _program_scope(value: str) -> str:
    normalized = _text(value, "program scope", 16).lower()
    if normalized not in {"global", "tenant"}:
        raise InvalidLearningInput("program scope is not supported")
    return normalized


def _evidence_type(value: EvidenceType | str) -> EvidenceType:
    if isinstance(value, EvidenceType):
        return value
    normalized = value.strip().lower()
    aliases = {
        "implementation_challenge": EvidenceType.IMPLEMENTATION,
        "improve": EvidenceType.IMPROVEMENT,
        "video": EvidenceType.VIDEO_WATCH,
    }
    try:
        return aliases.get(normalized, EvidenceType(normalized))
    except (AttributeError, ValueError) as exc:
        raise InvalidLearningInput("evidence type is not supported") from exc


def _review_decision(value: ReviewDecision | str) -> ReviewDecision:
    if isinstance(value, ReviewDecision):
        return value
    try:
        return ReviewDecision(value.strip().lower())
    except (AttributeError, ValueError) as exc:
        raise InvalidLearningInput("review decision is not supported") from exc


def _watch_kind(value: WatchIntervalKind | str) -> WatchIntervalKind:
    if isinstance(value, WatchIntervalKind):
        return value
    try:
        return WatchIntervalKind(value.strip().lower())
    except (AttributeError, ValueError) as exc:
        raise InvalidLearningInput("playback event kind is not supported") from exc


def _draft_status(value: DraftStatus | str) -> DraftStatus:
    if isinstance(value, DraftStatus):
        return value
    try:
        return DraftStatus(value.strip().lower())
    except (AttributeError, ValueError) as exc:
        raise InvalidLearningInput("draft status is not supported") from exc


def _playback_status(value: PlaybackSessionStatus | str) -> PlaybackSessionStatus:
    if isinstance(value, PlaybackSessionStatus):
        return value
    try:
        return PlaybackSessionStatus(value.strip().lower())
    except (AttributeError, ValueError) as exc:
        raise InvalidLearningInput("playback session status is not supported") from exc


def _submission_status(value: EvidenceSubmissionStatus | str) -> EvidenceSubmissionStatus:
    if isinstance(value, EvidenceSubmissionStatus):
        return value
    try:
        return EvidenceSubmissionStatus(value.strip().lower())
    except (AttributeError, ValueError) as exc:
        raise InvalidLearningInput("evidence submission status is not supported") from exc


def _command_status(value: LearningCommandStatus | str) -> LearningCommandStatus:
    if isinstance(value, LearningCommandStatus):
        return value
    try:
        return LearningCommandStatus(value.strip().lower())
    except (AttributeError, ValueError) as exc:
        raise InvalidLearningInput("learning command status is not supported") from exc


def _canonical_payload(
    payload: Mapping[str, Any],
    *,
    maximum_bytes: int,
    reject_scoring_fields: bool = True,
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise InvalidLearningInput("payload must be a JSON object")
    _reject_forbidden_fields(payload, reject_scoring_fields=reject_scoring_fields)
    try:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise InvalidLearningInput("payload must contain JSON-compatible finite values") from exc
    if len(encoded) > maximum_bytes:
        raise PayloadTooLargeError("payload exceeds the bounded learning payload limit")
    decoded = json.loads(encoded)
    if not isinstance(decoded, dict):
        raise InvalidLearningInput("payload must be a JSON object")
    return cast(dict[str, Any], decoded)


_FORBIDDEN_SCORING_FIELDS = frozenset(
    {
        "ai_score",
        "ai_decision",
        "automated_score",
        "model_score",
        "official_ai_score",
        "official_score",
    }
)


def _reject_forbidden_fields(value: object, *, reject_scoring_fields: bool) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if reject_scoring_fields and str(key).strip().lower() in _FORBIDDEN_SCORING_FIELDS:
                raise OfficialAIScoringForbiddenError(
                    "official AI scoring is not part of the learning evidence contract"
                )
            _reject_forbidden_fields(nested, reject_scoring_fields=reject_scoring_fields)
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for nested in value:
            _reject_forbidden_fields(nested, reject_scoring_fields=reject_scoring_fields)


class LearningError(DomainError):
    """Base error for expected learning-domain rejections."""

    code = "learning_rejected"
    title = "The learning operation was rejected"
    status = 422


class InvalidLearningInput(LearningError):
    code = "invalid_learning_input"
    title = "The learning input is invalid"


class PayloadTooLargeError(InvalidLearningInput):
    code = "learning_payload_too_large"
    title = "The learning payload is too large"


class DurableRepositoryRequiredError(LearningError):
    code = "learning_durable_repository_required"
    title = "A durable learning repository is required"
    status = 500


class AccessContextRequiredError(AuthorizationDenied, LearningError):
    code = "learning_access_context_required"
    title = "A server-resolved learning access context is required"


class ActivityNotFound(ResourceNotFound):
    code = "activity_not_found"
    title = "Activity not found"


class ActivityLockedError(AuthorizationDenied):
    code = "activity_locked"
    title = "Activity is locked"


class ActivityStateError(LearningError):
    code = "invalid_activity_state_transition"
    title = "Activity state transition is not allowed"


class ActivityVersionConflict(LearningError):
    code = "learning_activity_version_conflict"
    title = "The activity version is stale"


class CatalogVersionInactiveError(AuthorizationDenied):
    code = "learning_catalog_version_inactive"
    title = "The catalog version is not active"


class EntitlementInactiveError(AuthorizationDenied):
    code = "learning_entitlement_inactive"
    title = "Learning access is not active"


class DraftNotFound(ResourceNotFound):
    code = "draft_not_found"
    title = "Draft not found"


class DraftRevisionConflict(ResourceConflict):
    code = "draft_revision_conflict"
    title = "The draft changed on another device"

    def __init__(
        self,
        detail: str = "The draft revision is stale.",
        *,
        expected_revision: int | None = None,
        actual_revision: int | None = None,
    ) -> None:
        super().__init__(detail)
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision


OptimisticConcurrencyError = DraftRevisionConflict
StaleDraftError = DraftRevisionConflict


class DuplicateDraftRequest(ResourceConflict):
    code = "duplicate_draft_request"
    title = "The draft request was already used"


class PlaybackSessionNotFound(ResourceNotFound):
    code = "playback_session_not_found"
    title = "Playback session not found"


class PlaybackSessionExpired(InvalidEvidence):
    code = "playback_session_expired"
    title = "Playback session has expired"


ExpiredEvidenceError = PlaybackSessionExpired


class PlaybackSessionClosed(LearningError):
    code = "playback_session_closed"
    title = "Playback session is closed"


class SessionTokenError(AuthorizationDenied):
    code = "playback_session_token_invalid"
    title = "Playback session token is invalid"


class ReplayResistanceError(InvalidEvidence):
    code = "playback_event_replay_rejected"
    title = "Playback event replay was rejected"


class EvidenceVersionMismatch(InvalidEvidence):
    code = "evidence_version_mismatch"
    title = "Evidence belongs to another published version"


class ImpossibleEvidenceError(InvalidEvidence):
    code = "impossible_evidence"
    title = "Evidence contains impossible playback data"


class SeekOnlyEvidenceError(InvalidEvidence):
    code = "seek_only_evidence"
    title = "Seek-only playback is not watch evidence"


class InsufficientCoverageError(InvalidEvidence):
    code = "insufficient_video_coverage"
    title = "Video coverage is below the completion threshold"

    def __init__(
        self,
        detail: str = "Unique watched coverage is below the configured threshold.",
        *,
        coverage_ratio: float | None = None,
        threshold: float | None = None,
    ) -> None:
        super().__init__(detail)
        self.coverage_ratio = coverage_ratio
        self.threshold = threshold


class DuplicateEvidenceError(InvalidEvidence):
    code = "duplicate_evidence"
    title = "Evidence has already been submitted"


class DuplicateHeartbeatError(InvalidEvidence):
    code = "duplicate_heartbeat_conflict"
    title = "The playback event id was reused with different data"


class EvidenceSubmissionNotFound(ResourceNotFound):
    code = "evidence_submission_not_found"
    title = "Evidence submission not found"


class ReviewerNotAssignedError(AuthorizationDenied):
    code = "reviewer_not_assigned"
    title = "The reviewer is not assigned to this submission"


class ReviewerAuthorizationError(AuthorizationDenied):
    code = "reviewer_authorization_denied"
    title = "The reviewer is not authorized"


class HumanReviewRequiredError(LearningError):
    code = "human_review_required"
    title = "A human review is required"


class ReviewNotAllowedError(AuthorizationDenied):
    code = "review_not_allowed"
    title = "This evidence cannot be reviewed by this actor"


class CorrectionRevisionConflict(ResourceConflict):
    code = "correction_revision_conflict"
    title = "The review changed on another request"


class CorrectionRequiresNewEvidenceError(InvalidEvidence):
    code = "correction_requires_new_evidence"
    title = "New evidence is required after needs revision"


class CompletedActivityMutationError(ActivityStateError):
    code = "completed_activity_immutable"
    title = "A completed activity cannot be reopened"


class OfficialAIScoringForbiddenError(InvalidEvidence):
    code = "official_ai_scoring_forbidden"
    title = "Official AI scoring is not enabled"


class IdempotencyConflictError(ResourceConflict):
    code = "learning_idempotency_conflict"
    title = "The learning idempotency key was reused"


class CommandInProgressError(ResourceConflict):
    code = "learning_command_in_progress"
    title = "The learning command is already in progress"


class PersistenceConflictError(ResourceConflict):
    code = "learning_persistence_conflict"
    title = "The learning state changed concurrently"


class UniqueConstraintViolation(Exception):
    """Internal repository signal for an insert or idempotency race."""


@dataclass(frozen=True, slots=True)
class ActivityDefinition:
    """Server-resolved immutable activity configuration."""

    id: UUID
    kind: ActivityKind | str
    module_id: UUID
    program_version_id: UUID
    program_id: UUID
    program_scope: str
    program_owner_key: UUID
    title: str = ""
    order: int = 0
    required: bool = True
    version: str = "v1"
    prerequisites: tuple[UUID, ...] = ()
    video_duration_seconds: float | None = None
    policy_version: str = DEFAULT_VIDEO_POLICY_VERSION
    coverage_threshold: float = DEFAULT_VIDEO_COVERAGE_THRESHOLD
    requires_human_review: bool | None = None
    tenant_id: UUID | None = None
    media_binding_id: UUID | None = None
    media_asset_id: UUID | None = None
    media_version_id: UUID | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _activity_kind(self.kind))
        object.__setattr__(self, "program_scope", _program_scope(self.program_scope))
        if self.program_scope == "global" and self.program_owner_key != GLOBAL_CATALOG_OWNER:
            raise InvalidLearningInput("global catalog activity must use the global owner key")
        if self.program_scope == "global" and self.tenant_id is not None:
            raise InvalidLearningInput("global catalog activity cannot carry a tenant")
        if self.program_scope == "tenant" and (
            self.tenant_id is None or self.program_owner_key != self.tenant_id
        ):
            raise InvalidLearningInput("tenant catalog activity owner must match its tenant")
        object.__setattr__(self, "version", _text(self.version, "activity version", 128))
        object.__setattr__(
            self, "policy_version", _text(self.policy_version, "policy version", 128)
        )
        if self.order < 0:
            raise InvalidLearningInput("activity order must be nonnegative")
        if self.video_duration_seconds is not None:
            duration = _number(self.video_duration_seconds, "video_duration_seconds")
            if duration <= 0:
                raise InvalidLearningInput("video duration must be positive")
            object.__setattr__(self, "video_duration_seconds", duration)
        threshold = _number(self.coverage_threshold, "coverage_threshold")
        if threshold <= 0 or threshold > 1:
            raise InvalidLearningInput("coverage threshold must be greater than 0 and at most 1")
        object.__setattr__(self, "coverage_threshold", threshold)
        object.__setattr__(self, "prerequisites", tuple(dict.fromkeys(self.prerequisites)))
        media_ids = (self.media_binding_id, self.media_asset_id, self.media_version_id)
        if any(value is not None for value in media_ids) and not all(
            value is not None for value in media_ids
        ):
            raise InvalidLearningInput(
                "activity media binding, asset, and version must be resolved together"
            )

    @property
    def activity_id(self) -> UUID:
        return self.id

    @property
    def human_review_required(self) -> bool:
        if self.requires_human_review is not None:
            return self.requires_human_review
        return self.kind is not ActivityKind.VIDEO


@dataclass(frozen=True, slots=True)
class ModuleDefinition:
    """Published module ordering and explicit module prerequisites."""

    id: UUID
    program_version_id: UUID
    program_id: UUID
    program_scope: str
    program_owner_key: UUID
    activities: tuple[ActivityDefinition, ...] = ()
    title: str = ""
    order: int = 0
    prerequisite_module_ids: tuple[UUID, ...] = ()
    required: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "program_scope", _program_scope(self.program_scope))
        if self.order < 0:
            raise InvalidLearningInput("module order must be nonnegative")
        object.__setattr__(self, "activities", tuple(self.activities))
        object.__setattr__(
            self,
            "prerequisite_module_ids",
            tuple(dict.fromkeys(self.prerequisite_module_ids)),
        )
        for activity in self.activities:
            if (
                activity.module_id != self.id
                or activity.program_version_id != self.program_version_id
                or activity.program_id != self.program_id
                or activity.program_scope != self.program_scope
                or activity.program_owner_key != self.program_owner_key
            ):
                raise EvidenceVersionMismatch("module activity crosses catalog scope")


@dataclass(frozen=True, slots=True)
class ProgramDefinition:
    """A learner-pinned, immutable program version for projection."""

    id: UUID
    program_version_id: UUID
    program_scope: str
    program_owner_key: UUID
    version: str
    modules: tuple[ModuleDefinition, ...] = ()
    projection_version: str = DEFAULT_PROGRESS_PROJECTION_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "program_scope", _program_scope(self.program_scope))
        object.__setattr__(self, "version", _text(self.version, "program version", 128))
        object.__setattr__(
            self, "projection_version", _text(self.projection_version, "projection version", 128)
        )
        object.__setattr__(self, "modules", tuple(self.modules))
        module_ids = [module.id for module in self.modules]
        module_id_set = set(module_ids)
        if len(module_ids) != len(module_id_set):
            raise InvalidLearningInput("program modules must have unique identities")
        activity_ids = [activity.id for module in self.modules for activity in module.activities]
        if len(activity_ids) != len(set(activity_ids)):
            raise InvalidLearningInput("program activities must have unique identities")
        for module in self.modules:
            if (
                module.program_version_id != self.program_version_id
                or module.program_id != self.id
                or module.program_scope != self.program_scope
                or module.program_owner_key != self.program_owner_key
            ):
                raise EvidenceVersionMismatch("program module crosses catalog scope")
            if any(
                prerequisite_id not in module_id_set
                for prerequisite_id in module.prerequisite_module_ids
            ):
                raise EvidenceVersionMismatch("module prerequisite is outside the program")


CourseDefinition = ProgramDefinition


@dataclass(frozen=True, slots=True)
class MembershipResolution:
    """Repository-derived membership and tenant lifecycle facts."""

    tenant_id: UUID
    person_id: UUID
    role: str
    active: bool
    tenant_active: bool


@dataclass(frozen=True, slots=True)
class LearningAccessContext:
    """Trusted server resolution required by every learner command."""

    actor: ActorContext
    tenant_id: UUID
    person_id: UUID
    enrollment_id: UUID
    program_version_id: UUID
    activity: ActivityDefinition
    program: ProgramDefinition
    membership: MembershipResolution
    enrollment_active: bool
    entitlement_active: bool
    catalog_version_active: bool
    catalog_version_immutable: bool
    assigned_reviewer_id: UUID | None

    def __post_init__(self) -> None:
        if self.actor.person_id != self.person_id:
            raise AccessContextRequiredError("the access context subject is not the trusted actor")
        self.actor.require_tenant(self.tenant_id)
        if (
            self.membership.tenant_id != self.tenant_id
            or self.membership.person_id != self.person_id
        ):
            raise AccessContextRequiredError("membership resolution crosses the learning scope")
        if self.activity.program_version_id != self.program_version_id:
            raise EvidenceVersionMismatch(
                "activity does not belong to the requested program version"
            )
        if (
            self.program.program_version_id != self.program_version_id
            or self.activity.program_id != self.program.id
            or self.activity.program_scope != self.program.program_scope
            or self.activity.program_owner_key != self.program.program_owner_key
        ):
            raise EvidenceVersionMismatch("access context crosses the pinned program scope")
        if (
            self.program.program_scope == "tenant"
            and self.program.program_owner_key != self.tenant_id
        ):
            raise EvidenceVersionMismatch("tenant program owner does not match access tenant")
        if (
            self.program.program_scope == "global"
            and self.program.program_owner_key != GLOBAL_CATALOG_OWNER
        ):
            raise EvidenceVersionMismatch("global program owner key is invalid")
        resolved_activity = next(
            (
                definition
                for module in self.program.modules
                for definition in module.activities
                if definition.id == self.activity.id
            ),
            None,
        )
        if resolved_activity != self.activity:
            raise EvidenceVersionMismatch("access activity is absent from the pinned program")

    @property
    def scope(self) -> tuple[UUID, UUID, UUID, UUID, UUID]:
        return (
            self.tenant_id,
            self.enrollment_id,
            self.person_id,
            self.program_version_id,
            self.activity.id,
        )

    @property
    def full_scope(self) -> tuple[UUID, UUID, UUID, UUID, UUID, str, UUID, UUID, UUID]:
        return (
            self.tenant_id,
            self.enrollment_id,
            self.person_id,
            self.program_version_id,
            self.program.id,
            self.program.program_scope,
            self.program.program_owner_key,
            self.activity.module_id,
            self.activity.id,
        )


@dataclass(frozen=True, slots=True)
class ReviewerAuthorization:
    """Repository-derived reviewer membership, assignment, and permission."""

    actor: ActorContext
    tenant_id: UUID
    submission_id: UUID
    assigned: bool
    membership_active: bool
    role: str
    permission_granted: bool


@dataclass(frozen=True, slots=True)
class ActivityProgressSnapshot:
    tenant_id: UUID
    person_id: UUID
    enrollment_id: UUID
    program_version_id: UUID
    program_id: UUID
    program_scope: str
    program_owner_key: UUID
    module_id: UUID
    activity_id: UUID
    state: ActivityState | str
    activity_version: str
    policy_version: str | None
    revision: int
    started_at: datetime | None = None
    awaiting_review_at: datetime | None = None
    completed_at: datetime | None = None
    completion_evidence_id: UUID | None = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        object.__setattr__(self, "program_scope", _program_scope(self.program_scope))
        object.__setattr__(self, "state", _activity_state(self.state))
        object.__setattr__(
            self, "activity_version", _text(self.activity_version, "activity version", 128)
        )
        if self.policy_version is not None:
            object.__setattr__(
                self, "policy_version", _text(self.policy_version, "policy version", 128)
            )
        if self.revision < 0:
            raise InvalidLearningInput("progress revision must be nonnegative")
        object.__setattr__(self, "updated_at", _utc(self.updated_at))


@dataclass(frozen=True, slots=True)
class DraftSnapshot:
    tenant_id: UUID
    person_id: UUID
    enrollment_id: UUID
    program_version_id: UUID
    program_id: UUID
    program_scope: str
    program_owner_key: UUID
    module_id: UUID
    activity_id: UUID
    payload: Mapping[str, Any]
    revision: int
    status: DraftStatus | str
    id: UUID
    last_idempotency_key: str | None
    last_request_fingerprint: str | None
    saved_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "program_scope", _program_scope(self.program_scope))
        object.__setattr__(
            self, "payload", _canonical_payload(self.payload, maximum_bytes=MAX_DRAFT_PAYLOAD_BYTES)
        )
        if self.revision < 0:
            raise InvalidLearningInput("draft revision must be nonnegative")
        try:
            object.__setattr__(self, "status", DraftStatus(str(self.status).lower()))
        except ValueError as exc:
            raise InvalidLearningInput("draft status is not supported") from exc
        if self.last_idempotency_key is not None:
            object.__setattr__(
                self,
                "last_idempotency_key",
                _text(self.last_idempotency_key, "idempotency key", 128),
            )
        if self.last_request_fingerprint is not None and len(self.last_request_fingerprint) != 64:
            raise InvalidLearningInput("draft request fingerprint must be SHA-256")
        object.__setattr__(self, "saved_at", _utc(self.saved_at))


@dataclass(frozen=True, slots=True)
class TimeInterval:
    start_seconds: float
    end_seconds: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "start_seconds", _number(self.start_seconds, "interval start"))
        object.__setattr__(self, "end_seconds", _number(self.end_seconds, "interval end"))

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


type IntervalInput = TimeInterval | Sequence[float]


@dataclass(frozen=True, slots=True)
class VideoEvidencePolicy:
    """Server-owned, versioned playback policy pinned into a session."""

    version: str
    coverage_threshold: float
    session_ttl_seconds: int
    future_clock_skew_seconds: float
    minimum_watch_interval_seconds: float
    max_event_seconds: float
    max_heartbeat_gap_seconds: float
    minimum_heartbeats_for_completion: int
    clock_grace_seconds: float
    max_rewind_seconds: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "version", _text(self.version, "policy version", 128))
        threshold = _number(self.coverage_threshold, "coverage threshold")
        if threshold <= 0 or threshold > 1:
            raise InvalidLearningInput("coverage threshold must be greater than 0 and at most 1")
        object.__setattr__(self, "coverage_threshold", threshold)
        if self.session_ttl_seconds <= 0:
            raise InvalidLearningInput("playback session TTL must be positive")
        for name in (
            "future_clock_skew_seconds",
            "minimum_watch_interval_seconds",
            "max_event_seconds",
            "max_heartbeat_gap_seconds",
            "clock_grace_seconds",
            "max_rewind_seconds",
        ):
            value = _number(getattr(self, name), name)
            if value < 0 or (
                name in {"max_event_seconds", "max_heartbeat_gap_seconds"} and value <= 0
            ):
                raise InvalidLearningInput(f"{name} must be nonnegative and event limit positive")
            object.__setattr__(self, name, value)
        if self.minimum_heartbeats_for_completion < 2:
            raise InvalidLearningInput("video completion requires at least two heartbeats")


@dataclass(frozen=True, slots=True)
class VideoCoverage:
    duration_seconds: float
    merged_intervals: tuple[TimeInterval, ...]
    unique_seconds: float
    coverage_ratio: float
    threshold: float
    policy_version: str

    @property
    def meets_threshold(self) -> bool:
        return self.coverage_ratio >= self.threshold


def _interval_parts(value: IntervalInput) -> TimeInterval:
    if isinstance(value, TimeInterval):
        return value
    if len(value) != 2:
        raise ImpossibleEvidenceError("each watch interval must contain exactly start and end")
    return TimeInterval(value[0], value[1])


def merge_unique_intervals(intervals: Iterable[IntervalInput]) -> tuple[TimeInterval, ...]:
    """Merge overlapping or adjacent intervals so coverage is counted once."""

    ordered = sorted(
        (_interval_parts(interval) for interval in intervals),
        key=lambda interval: (interval.start_seconds, interval.end_seconds),
    )
    merged: list[TimeInterval] = []
    for interval in ordered:
        if not merged or interval.start_seconds > merged[-1].end_seconds:
            merged.append(interval)
            continue
        if interval.end_seconds > merged[-1].end_seconds:
            merged[-1] = TimeInterval(merged[-1].start_seconds, interval.end_seconds)
    return tuple(merged)


merge_intervals = merge_unique_intervals


def calculate_video_coverage(
    intervals: Iterable[IntervalInput],
    duration_seconds: float,
    *,
    policy: VideoEvidencePolicy,
) -> VideoCoverage:
    """Validate watch intervals and return a unique-coverage calculation."""

    duration = _number(duration_seconds, "video duration")
    if duration <= 0:
        raise ImpossibleEvidenceError("video duration must be positive")
    watch_intervals: list[TimeInterval] = []
    for raw_interval in intervals:
        interval = _interval_parts(raw_interval)
        if interval.start_seconds < 0 or interval.end_seconds < interval.start_seconds:
            raise ImpossibleEvidenceError("watch interval is outside the video timeline")
        if interval.end_seconds > duration:
            raise ImpossibleEvidenceError("watch interval ends after the video duration")
        if interval.duration_seconds <= 0:
            continue
        if interval.duration_seconds < policy.minimum_watch_interval_seconds:
            continue
        watch_intervals.append(interval)
    if not watch_intervals:
        raise SeekOnlyEvidenceError("at least one positive watched interval is required")
    merged = merge_unique_intervals(watch_intervals)
    unique_seconds = sum(interval.duration_seconds for interval in merged)
    ratio = min(1.0, unique_seconds / duration)
    return VideoCoverage(
        duration_seconds=duration,
        merged_intervals=merged,
        unique_seconds=unique_seconds,
        coverage_ratio=ratio,
        threshold=policy.coverage_threshold,
        policy_version=policy.version,
    )


def validate_video_evidence(
    intervals: Iterable[IntervalInput],
    duration_seconds: float,
    *,
    policy: VideoEvidencePolicy,
) -> VideoCoverage:
    """Return coverage only when the explicit server policy passes."""

    coverage = calculate_video_coverage(intervals, duration_seconds, policy=policy)
    if not coverage.meets_threshold:
        raise InsufficientCoverageError(
            coverage_ratio=coverage.coverage_ratio,
            threshold=coverage.threshold,
        )
    return coverage


def unique_coverage_seconds(
    intervals: Iterable[IntervalInput],
    duration_seconds: float,
    *,
    policy: VideoEvidencePolicy,
) -> float:
    return calculate_video_coverage(intervals, duration_seconds, policy=policy).unique_seconds


@dataclass(frozen=True, slots=True)
class WatchIntervalSnapshot:
    playback_session_id: UUID
    tenant_id: UUID
    person_id: UUID
    enrollment_id: UUID
    program_version_id: UUID
    program_id: UUID
    program_scope: str
    program_owner_key: UUID
    module_id: UUID
    activity_id: UUID
    event_id: str
    sequence: int
    start_seconds: float
    end_seconds: float
    kind: WatchIntervalKind | str
    observed_at: datetime
    id: UUID

    def __post_init__(self) -> None:
        object.__setattr__(self, "program_scope", _program_scope(self.program_scope))
        object.__setattr__(self, "event_id", _text(self.event_id, "event id", 128))
        object.__setattr__(self, "kind", _watch_kind(self.kind))
        if self.sequence <= 0:
            raise InvalidLearningInput("playback sequence must be positive")
        object.__setattr__(self, "start_seconds", _number(self.start_seconds, "interval start"))
        object.__setattr__(self, "end_seconds", _number(self.end_seconds, "interval end"))
        object.__setattr__(self, "observed_at", _utc(self.observed_at))

    @property
    def interval(self) -> TimeInterval:
        return TimeInterval(self.start_seconds, self.end_seconds)


@dataclass(frozen=True, slots=True)
class PlaybackSessionSnapshot:
    tenant_id: UUID
    person_id: UUID
    enrollment_id: UUID
    program_version_id: UUID
    program_id: UUID
    program_scope: str
    program_owner_key: UUID
    module_id: UUID
    activity_id: UUID
    content_version: str
    policy_version: str
    session_token_hash: bytes
    duration_seconds: float
    coverage_threshold: float
    minimum_watch_interval_seconds: float
    max_event_seconds: float
    max_heartbeat_gap_seconds: float
    minimum_heartbeats_for_completion: int
    clock_grace_seconds: float
    max_rewind_seconds: float
    started_at: datetime
    expires_at: datetime
    status: PlaybackSessionStatus | str
    revision: int
    last_sequence: int
    last_position_seconds: float
    last_heartbeat_at: datetime | None
    closed_at: datetime | None
    id: UUID
    session_token: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "program_scope", _program_scope(self.program_scope))
        object.__setattr__(
            self, "content_version", _text(self.content_version, "content version", 128)
        )
        object.__setattr__(
            self, "policy_version", _text(self.policy_version, "policy version", 128)
        )
        if len(self.session_token_hash) != 32:
            raise InvalidLearningInput("playback token hash must be SHA-256")
        duration = _number(self.duration_seconds, "video duration")
        if duration <= 0:
            raise InvalidLearningInput("video duration must be positive")
        object.__setattr__(self, "duration_seconds", duration)
        threshold = _number(self.coverage_threshold, "coverage threshold")
        if threshold <= 0 or threshold > 1:
            raise InvalidLearningInput("coverage threshold must be greater than 0 and at most 1")
        object.__setattr__(self, "coverage_threshold", threshold)
        for name in (
            "minimum_watch_interval_seconds",
            "max_event_seconds",
            "max_heartbeat_gap_seconds",
            "clock_grace_seconds",
            "max_rewind_seconds",
        ):
            value = _number(getattr(self, name), name)
            if value < 0 or (
                name in {"max_event_seconds", "max_heartbeat_gap_seconds"} and value <= 0
            ):
                raise InvalidLearningInput("pinned playback policy bounds are invalid")
            object.__setattr__(self, name, value)
        if self.minimum_heartbeats_for_completion < 2:
            raise InvalidLearningInput("pinned playback policy requires two heartbeats")
        object.__setattr__(self, "started_at", _utc(self.started_at))
        object.__setattr__(self, "expires_at", _utc(self.expires_at))
        if self.expires_at <= self.started_at:
            raise InvalidLearningInput("playback expiry must be after session start")
        object.__setattr__(self, "status", PlaybackSessionStatus(str(self.status).lower()))
        if self.revision < 0 or self.last_sequence < 0 or self.last_position_seconds < 0:
            raise InvalidLearningInput("playback counters must be nonnegative")

    def is_expired_at(self, now: datetime) -> bool:
        return _utc(now) >= self.expires_at


@dataclass(frozen=True, slots=True)
class EvidenceSnapshot:
    tenant_id: UUID
    person_id: UUID
    enrollment_id: UUID
    program_version_id: UUID
    program_id: UUID
    program_scope: str
    program_owner_key: UUID
    module_id: UUID
    activity_id: UUID
    evidence_type: EvidenceType | str
    activity_version: str
    policy_version: str
    idempotency_key: str
    payload: Mapping[str, Any]
    playback_session_id: UUID | None
    captured_at: datetime
    id: UUID

    def __post_init__(self) -> None:
        object.__setattr__(self, "program_scope", _program_scope(self.program_scope))
        object.__setattr__(self, "evidence_type", _evidence_type(self.evidence_type))
        object.__setattr__(
            self, "activity_version", _text(self.activity_version, "activity version", 128)
        )
        object.__setattr__(
            self, "policy_version", _text(self.policy_version, "policy version", 128)
        )
        object.__setattr__(
            self, "idempotency_key", _text(self.idempotency_key, "idempotency key", 128)
        )
        object.__setattr__(
            self,
            "payload",
            _canonical_payload(self.payload, maximum_bytes=MAX_EVIDENCE_PAYLOAD_BYTES),
        )
        object.__setattr__(self, "captured_at", _utc(self.captured_at))


@dataclass(frozen=True, slots=True)
class EvidenceSubmissionSnapshot:
    evidence_id: UUID
    tenant_id: UUID
    person_id: UUID
    enrollment_id: UUID
    program_version_id: UUID
    program_id: UUID
    program_scope: str
    program_owner_key: UUID
    module_id: UUID
    activity_id: UUID
    submitted_by_person_id: UUID
    idempotency_key: str
    status: EvidenceSubmissionStatus | str
    assigned_reviewer_id: UUID | None
    submitted_at: datetime
    id: UUID

    def __post_init__(self) -> None:
        object.__setattr__(self, "program_scope", _program_scope(self.program_scope))
        object.__setattr__(
            self, "idempotency_key", _text(self.idempotency_key, "idempotency key", 128)
        )
        object.__setattr__(self, "status", EvidenceSubmissionStatus(str(self.status).lower()))
        object.__setattr__(self, "submitted_at", _utc(self.submitted_at))
        if (
            self.status is EvidenceSubmissionStatus.AWAITING_REVIEW
            and self.assigned_reviewer_id is None
        ):
            raise InvalidLearningInput("human-review submissions require an assigned reviewer")
        if self.assigned_reviewer_id == self.person_id:
            raise ReviewNotAllowedError("a learner cannot review their own submission")


@dataclass(frozen=True, slots=True)
class EvidenceCorrectionSnapshot:
    submission_id: UUID
    evidence_id: UUID
    tenant_id: UUID
    person_id: UUID
    enrollment_id: UUID
    program_version_id: UUID
    program_id: UUID
    program_scope: str
    program_owner_key: UUID
    module_id: UUID
    activity_id: UUID
    reviewer_person_id: UUID
    decision: ReviewDecision | str
    reason: str
    idempotency_key: str
    correction_sequence: int
    supersedes_correction_id: UUID | None
    created_at: datetime
    id: UUID

    def __post_init__(self) -> None:
        object.__setattr__(self, "program_scope", _program_scope(self.program_scope))
        object.__setattr__(self, "decision", _review_decision(self.decision))
        object.__setattr__(self, "reason", _text(self.reason, "review reason", 1000))
        object.__setattr__(
            self, "idempotency_key", _text(self.idempotency_key, "idempotency key", 128)
        )
        if self.correction_sequence <= 0:
            raise InvalidLearningInput("correction sequence must be positive")
        if self.reviewer_person_id == self.person_id:
            raise ReviewNotAllowedError("a learner cannot review their own submission")
        object.__setattr__(self, "created_at", _utc(self.created_at))


@dataclass(frozen=True, slots=True)
class LearningProgressProjectionSnapshot:
    tenant_id: UUID
    person_id: UUID
    enrollment_id: UUID
    program_version_id: UUID
    program_id: UUID
    program_scope: str
    program_owner_key: UUID
    module_id: UUID | None
    scope_type: str
    scope_id: UUID
    denominator: int
    completed_count: int
    percentage: float
    projection_version: str
    explanation: Mapping[str, Any]
    computed_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "program_scope", _program_scope(self.program_scope))
        normalized_scope = ProjectionScope(self.scope_type.strip().lower())
        object.__setattr__(self, "scope_type", normalized_scope.value)
        if normalized_scope is ProjectionScope.MODULE:
            if self.module_id is None or self.scope_id != self.module_id:
                raise InvalidLearningInput("module projection scope must match module_id")
        elif self.module_id is not None or self.scope_id != self.program_id:
            raise InvalidLearningInput("course projection scope must match program_id")
        if (
            self.denominator < 0
            or self.completed_count < 0
            or self.completed_count > self.denominator
        ):
            raise InvalidLearningInput("progress counts must satisfy 0 <= completed <= denominator")
        expected = self.completed_count / self.denominator if self.denominator else 0.0
        if not math.isfinite(self.percentage) or abs(self.percentage - expected) > 1e-9:
            raise InvalidLearningInput("progress percentage must be deterministic")
        object.__setattr__(
            self, "projection_version", _text(self.projection_version, "projection version", 128)
        )
        object.__setattr__(
            self,
            "explanation",
            _canonical_payload(
                self.explanation,
                maximum_bytes=MAX_EVIDENCE_PAYLOAD_BYTES,
                reject_scoring_fields=False,
            ),
        )
        object.__setattr__(self, "computed_at", _utc(self.computed_at))


@dataclass(frozen=True, slots=True)
class CommandLedgerSnapshot:
    id: UUID
    tenant_id: UUID
    actor_person_id: UUID
    person_id: UUID
    enrollment_id: UUID
    program_version_id: UUID
    program_id: UUID
    program_scope: str
    program_owner_key: UUID
    module_id: UUID
    activity_id: UUID
    operation: str
    idempotency_key: str
    request_digest: str
    status: LearningCommandStatus | str
    result_progress_id: UUID | None = None
    result_draft_id: UUID | None = None
    result_session_id: UUID | None = None
    result_interval_id: UUID | None = None
    result_evidence_id: UUID | None = None
    result_submission_id: UUID | None = None
    result_correction_id: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "program_scope", _program_scope(self.program_scope))
        object.__setattr__(
            self, "idempotency_key", _text(self.idempotency_key, "idempotency key", 128)
        )
        if len(self.request_digest) != 64:
            raise InvalidLearningInput("command request digest must be SHA-256")
        object.__setattr__(self, "status", LearningCommandStatus(str(self.status).lower()))
        object.__setattr__(self, "created_at", _utc(self.created_at))
        if self.completed_at is not None:
            object.__setattr__(self, "completed_at", _utc(self.completed_at))


@dataclass(frozen=True, slots=True)
class ActivityStateExplanation:
    activity_id: UUID
    state: ActivityState
    required: bool
    reason: str
    missing_activity_ids: tuple[UUID, ...] = ()
    missing_module_ids: tuple[UUID, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "activity_id": str(self.activity_id),
            "state": self.state.value,
            "required": self.required,
            "reason": self.reason,
            "missing_activity_ids": [str(value) for value in self.missing_activity_ids],
            "missing_module_ids": [str(value) for value in self.missing_module_ids],
        }


@dataclass(frozen=True, slots=True)
class ProgressExplanation:
    scope_type: str
    scope_id: UUID
    program_version: str
    projection_version: str
    denominator: int
    completed_count: int
    predicate: str
    activity_reasons: tuple[ActivityStateExplanation, ...] = ()
    missing_module_ids: tuple[UUID, ...] = ()

    @property
    def percentage(self) -> float:
        return self.completed_count / self.denominator if self.denominator else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "scope_type": self.scope_type,
            "scope_id": str(self.scope_id),
            "program_version": self.program_version,
            "projection_version": self.projection_version,
            "denominator": self.denominator,
            "completed_count": self.completed_count,
            "percentage": self.percentage,
            "predicate": self.predicate,
            "missing_module_ids": [str(value) for value in self.missing_module_ids],
            "activity_reasons": [reason.as_dict() for reason in self.activity_reasons],
        }


@dataclass(frozen=True, slots=True)
class ModuleProgressProjection:
    module_id: UUID
    program_version: str
    projection_version: str
    denominator: int
    completed_count: int
    percentage: float
    complete: bool
    activity_states: tuple[ActivityStateExplanation, ...]
    missing_module_ids: tuple[UUID, ...] = ()

    @property
    def explanation(self) -> ProgressExplanation:
        predicate = "all_required_activities_completed"
        if self.denominator == 0:
            predicate = "module_has_no_required_activities"
        return ProgressExplanation(
            scope_type="module",
            scope_id=self.module_id,
            program_version=self.program_version,
            projection_version=self.projection_version,
            denominator=self.denominator,
            completed_count=self.completed_count,
            predicate=predicate,
            activity_reasons=self.activity_states,
            missing_module_ids=self.missing_module_ids,
        )


@dataclass(frozen=True, slots=True)
class CourseProgressProjection:
    program_id: UUID
    program_version: str
    projection_version: str
    denominator: int
    completed_count: int
    percentage: float
    can_complete: bool
    next_activity_id: UUID | None
    modules: tuple[ModuleProgressProjection, ...]
    activity_states: tuple[ActivityStateExplanation, ...]

    @property
    def explanation(self) -> ProgressExplanation:
        predicate = "all_required_activities_completed"
        if self.denominator == 0:
            predicate = "course_has_no_required_activities"
        return ProgressExplanation(
            scope_type="course",
            scope_id=self.program_id,
            program_version=self.program_version,
            projection_version=self.projection_version,
            denominator=self.denominator,
            completed_count=self.completed_count,
            predicate=predicate,
            activity_reasons=self.activity_states,
        )

    def as_dict(self) -> dict[str, Any]:
        return self.explanation.as_dict() | {
            "program_id": str(self.program_id),
            "can_complete": self.can_complete,
            "next_activity_id": str(self.next_activity_id) if self.next_activity_id else None,
            "modules": [module.explanation.as_dict() for module in self.modules],
        }


class LearningRepository(Protocol):
    """Persistence and server-resolution port used by learning commands."""

    durable: bool

    def atomic(self) -> AbstractContextManager[None]: ...

    def resolve_access(
        self,
        *,
        actor: ActorContext,
        tenant_id: UUID,
        enrollment_id: UUID,
        program_version_id: UUID,
        activity_id: UUID,
    ) -> LearningAccessContext: ...

    def resolve_scope(
        self,
        *,
        tenant_id: UUID,
        person_id: UUID,
        enrollment_id: UUID,
        program_version_id: UUID,
        activity_id: UUID,
    ) -> LearningAccessContext: ...

    def resolve_reviewer(
        self, *, actor: ActorContext, submission: EvidenceSubmissionSnapshot
    ) -> ReviewerAuthorization: ...

    def reviewer_for_activity(self, access: LearningAccessContext) -> UUID | None: ...

    def get_progress(self, *scope: UUID) -> ActivityProgressSnapshot | None: ...

    def list_progress(
        self, *, tenant_id: UUID, person_id: UUID, enrollment_id: UUID, program_version_id: UUID
    ) -> tuple[ActivityProgressSnapshot, ...]: ...

    def compare_and_swap_progress(
        self,
        current: ActivityProgressSnapshot | None,
        replacement: ActivityProgressSnapshot,
        *,
        expected_revision: int,
    ) -> ActivityProgressSnapshot: ...

    def get_draft(self, *scope: UUID) -> DraftSnapshot | None: ...

    def compare_and_swap_draft(
        self,
        current: DraftSnapshot | None,
        replacement: DraftSnapshot,
        *,
        expected_revision: int,
    ) -> DraftSnapshot: ...

    def get_playback_session(self, session_id: UUID) -> PlaybackSessionSnapshot | None: ...

    def add_playback_session(self, item: PlaybackSessionSnapshot) -> None: ...

    def compare_and_swap_session(
        self,
        current: PlaybackSessionSnapshot,
        replacement: PlaybackSessionSnapshot,
        *,
        expected_revision: int,
    ) -> PlaybackSessionSnapshot: ...

    def get_interval_by_event(
        self, session_id: UUID, event_id: str
    ) -> WatchIntervalSnapshot | None: ...

    def get_interval_by_sequence(
        self, session_id: UUID, sequence: int
    ) -> WatchIntervalSnapshot | None: ...

    def add_interval(self, item: WatchIntervalSnapshot) -> None: ...

    def intervals_for_session(self, session_id: UUID) -> tuple[WatchIntervalSnapshot, ...]: ...

    def find_evidence_by_request(self, *scope: UUID | str) -> EvidenceSnapshot | None: ...

    def get_evidence(self, evidence_id: UUID) -> EvidenceSnapshot | None: ...

    def add_evidence(self, item: EvidenceSnapshot) -> None: ...

    def find_submission_by_request(
        self, *scope: UUID | str
    ) -> EvidenceSubmissionSnapshot | None: ...

    def get_submission(self, submission_id: UUID) -> EvidenceSubmissionSnapshot | None: ...

    def submissions_for_evidence(
        self, evidence_id: UUID
    ) -> tuple[EvidenceSubmissionSnapshot, ...]: ...

    def add_submission(self, item: EvidenceSubmissionSnapshot) -> None: ...

    def corrections_for_submission(
        self, submission_id: UUID
    ) -> tuple[EvidenceCorrectionSnapshot, ...]: ...

    def append_correction(
        self,
        item: EvidenceCorrectionSnapshot,
        *,
        expected_revision: int,
    ) -> None: ...

    def get_command(
        self,
        *,
        tenant_id: UUID,
        actor_person_id: UUID,
        operation: str,
        idempotency_key: str,
    ) -> CommandLedgerSnapshot | None: ...

    def claim_command(self, command: CommandLedgerSnapshot) -> None: ...

    def complete_command(
        self, command: CommandLedgerSnapshot, *, now: datetime
    ) -> CommandLedgerSnapshot: ...

    def lock_projection_scope(self, access: LearningAccessContext) -> None: ...

    def upsert_projection(self, item: LearningProgressProjectionSnapshot) -> None: ...


def _scope_tuple(
    *,
    tenant_id: UUID,
    person_id: UUID,
    enrollment_id: UUID,
    program_version_id: UUID,
    activity_id: UUID,
) -> tuple[UUID, UUID, UUID, UUID, UUID]:
    return tenant_id, enrollment_id, person_id, program_version_id, activity_id


def _full_scope_tuple(
    *,
    tenant_id: UUID,
    person_id: UUID,
    enrollment_id: UUID,
    program_version_id: UUID,
    program_id: UUID,
    program_scope: str,
    program_owner_key: UUID,
    module_id: UUID,
    activity_id: UUID,
) -> tuple[UUID, UUID, UUID, UUID, UUID, str, UUID, UUID, UUID]:
    return (
        tenant_id,
        enrollment_id,
        person_id,
        program_version_id,
        program_id,
        program_scope,
        program_owner_key,
        module_id,
        activity_id,
    )


class _DuplicateCommandClaim(Exception):
    pass


class InMemoryLearningStore:
    """Explicit test-only repository with rollback and CAS semantics."""

    durable = False

    def __init__(
        self,
        *,
        activities: Iterable[ActivityDefinition] = (),
        access_contexts: Iterable[LearningAccessContext] = (),
        reviewer_authorizations: Iterable[ReviewerAuthorization] = (),
        progress: Iterable[ActivityProgressSnapshot] = (),
        drafts: Iterable[DraftSnapshot] = (),
        evidence: Iterable[EvidenceSnapshot] = (),
        submissions: Iterable[EvidenceSubmissionSnapshot] = (),
        corrections: Iterable[EvidenceCorrectionSnapshot] = (),
        playback_sessions: Iterable[PlaybackSessionSnapshot] = (),
        intervals: Iterable[WatchIntervalSnapshot] = (),
    ) -> None:
        self.activities: dict[UUID, ActivityDefinition] = {item.id: item for item in activities}
        self.access_contexts: dict[tuple[UUID, UUID, UUID, UUID, UUID], LearningAccessContext] = {
            item.scope: item for item in access_contexts
        }
        self.reviewer_authorizations: dict[tuple[UUID, UUID, UUID], ReviewerAuthorization] = {
            (item.tenant_id, item.submission_id, item.actor.person_id): item
            for item in reviewer_authorizations
        }
        self.progress: dict[tuple[UUID, UUID, UUID, UUID, UUID], ActivityProgressSnapshot] = {
            _scope_tuple(
                tenant_id=item.tenant_id,
                person_id=item.person_id,
                enrollment_id=item.enrollment_id,
                program_version_id=item.program_version_id,
                activity_id=item.activity_id,
            ): item
            for item in progress
        }
        self.drafts: dict[tuple[UUID, UUID, UUID, UUID, UUID], DraftSnapshot] = {
            _scope_tuple(
                tenant_id=item.tenant_id,
                person_id=item.person_id,
                enrollment_id=item.enrollment_id,
                program_version_id=item.program_version_id,
                activity_id=item.activity_id,
            ): item
            for item in drafts
        }
        self.evidence: dict[UUID, EvidenceSnapshot] = {item.id: item for item in evidence}
        self.evidence_request_index: dict[tuple[UUID, UUID, UUID, UUID, UUID, str], UUID] = {
            (
                item.tenant_id,
                item.enrollment_id,
                item.person_id,
                item.program_version_id,
                item.activity_id,
                item.idempotency_key,
            ): item.id
            for item in evidence
        }
        self.submissions: dict[UUID, EvidenceSubmissionSnapshot] = {
            item.id: item for item in submissions
        }
        self.submission_request_index: dict[tuple[UUID, UUID, UUID, UUID, UUID, str], UUID] = {
            (
                item.tenant_id,
                item.enrollment_id,
                item.person_id,
                item.program_version_id,
                item.activity_id,
                item.idempotency_key,
            ): item.id
            for item in submissions
        }
        correction_items = tuple(corrections)
        self.corrections: dict[UUID, EvidenceCorrectionSnapshot] = {
            item.id: item for item in correction_items
        }
        self.correction_order: list[UUID] = [item.id for item in correction_items]
        self.playback_sessions: dict[UUID, PlaybackSessionSnapshot] = {
            item.id: item for item in playback_sessions
        }
        self.intervals: dict[UUID, list[WatchIntervalSnapshot]] = {}
        self.interval_event_index: dict[tuple[UUID, str], UUID] = {}
        self.interval_sequence_index: dict[tuple[UUID, int], UUID] = {}
        for interval in intervals:
            self.intervals.setdefault(interval.playback_session_id, []).append(interval)
            self.interval_event_index[(interval.playback_session_id, interval.event_id)] = (
                interval.id
            )
            self.interval_sequence_index[(interval.playback_session_id, interval.sequence)] = (
                interval.id
            )
        self.commands: dict[tuple[UUID, UUID, str, str], CommandLedgerSnapshot] = {}
        self.projections: dict[
            tuple[UUID, UUID, UUID, str, UUID], LearningProgressProjectionSnapshot
        ] = {}
        self._lock = RLock()

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Provide real rollback for test transactions, including partial writes."""

        with self._lock:
            snapshot = {
                name: copy.deepcopy(getattr(self, name))
                for name in (
                    "progress",
                    "drafts",
                    "evidence",
                    "evidence_request_index",
                    "submissions",
                    "submission_request_index",
                    "corrections",
                    "correction_order",
                    "playback_sessions",
                    "intervals",
                    "interval_event_index",
                    "interval_sequence_index",
                    "commands",
                    "projections",
                )
            }
            try:
                yield
            except BaseException:
                for name, value in snapshot.items():
                    setattr(self, name, value)
                raise

    def register_access(self, access: LearningAccessContext) -> None:
        self.access_contexts[access.scope] = access

    def register_reviewer(self, authorization: ReviewerAuthorization) -> None:
        key = (authorization.tenant_id, authorization.submission_id, authorization.actor.person_id)
        self.reviewer_authorizations[key] = authorization

    def resolve_access(
        self,
        *,
        actor: ActorContext,
        tenant_id: UUID,
        enrollment_id: UUID,
        program_version_id: UUID,
        activity_id: UUID,
    ) -> LearningAccessContext:
        actor.require_tenant(tenant_id)
        key = _scope_tuple(
            tenant_id=tenant_id,
            person_id=actor.person_id,
            enrollment_id=enrollment_id,
            program_version_id=program_version_id,
            activity_id=activity_id,
        )
        access = self.access_contexts.get(key)
        if access is None or access.actor != actor:
            raise AccessContextRequiredError(
                "learning access must be resolved for this trusted session"
            )
        return access

    def resolve_scope(
        self,
        *,
        tenant_id: UUID,
        person_id: UUID,
        enrollment_id: UUID,
        program_version_id: UUID,
        activity_id: UUID,
    ) -> LearningAccessContext:
        access = self.access_contexts.get(
            _scope_tuple(
                tenant_id=tenant_id,
                person_id=person_id,
                enrollment_id=enrollment_id,
                program_version_id=program_version_id,
                activity_id=activity_id,
            )
        )
        if access is None:
            raise AccessContextRequiredError("learning scope is not server-resolved")
        return access

    def resolve_reviewer(
        self, *, actor: ActorContext, submission: EvidenceSubmissionSnapshot
    ) -> ReviewerAuthorization:
        actor.require_tenant(submission.tenant_id)
        result = self.reviewer_authorizations.get(
            (submission.tenant_id, submission.id, actor.person_id)
        )
        if result is None:
            raise ReviewerAuthorizationError("reviewer authorization was not server-resolved")
        return result

    def reviewer_for_activity(self, access: LearningAccessContext) -> UUID | None:
        return access.assigned_reviewer_id

    def get_progress(self, *scope: UUID) -> ActivityProgressSnapshot | None:
        return self.progress.get(cast(tuple[UUID, UUID, UUID, UUID, UUID], scope))

    def list_progress(
        self, *, tenant_id: UUID, person_id: UUID, enrollment_id: UUID, program_version_id: UUID
    ) -> tuple[ActivityProgressSnapshot, ...]:
        return tuple(
            sorted(
                (
                    item
                    for item in self.progress.values()
                    if item.tenant_id == tenant_id
                    and item.person_id == person_id
                    and item.enrollment_id == enrollment_id
                    and item.program_version_id == program_version_id
                ),
                key=lambda item: str(item.activity_id),
            )
        )

    def compare_and_swap_progress(
        self,
        current: ActivityProgressSnapshot | None,
        replacement: ActivityProgressSnapshot,
        *,
        expected_revision: int,
    ) -> ActivityProgressSnapshot:
        key = _scope_tuple(
            tenant_id=replacement.tenant_id,
            person_id=replacement.person_id,
            enrollment_id=replacement.enrollment_id,
            program_version_id=replacement.program_version_id,
            activity_id=replacement.activity_id,
        )
        actual = self.progress.get(key)
        if current is None:
            if actual is not None or expected_revision != 0:
                raise DraftRevisionConflict(
                    expected_revision=expected_revision,
                    actual_revision=actual.revision if actual else 0,
                )
        elif actual is None or actual.revision != expected_revision:
            raise PersistenceConflictError("activity progress revision is stale")
        self.progress[key] = replacement
        return replacement

    def get_draft(self, *scope: UUID) -> DraftSnapshot | None:
        return self.drafts.get(cast(tuple[UUID, UUID, UUID, UUID, UUID], scope))

    def compare_and_swap_draft(
        self,
        current: DraftSnapshot | None,
        replacement: DraftSnapshot,
        *,
        expected_revision: int,
    ) -> DraftSnapshot:
        key = _scope_tuple(
            tenant_id=replacement.tenant_id,
            person_id=replacement.person_id,
            enrollment_id=replacement.enrollment_id,
            program_version_id=replacement.program_version_id,
            activity_id=replacement.activity_id,
        )
        actual = self.drafts.get(key)
        if current is None:
            if actual is not None or expected_revision != 0:
                raise DraftRevisionConflict(
                    expected_revision=expected_revision,
                    actual_revision=actual.revision if actual else 0,
                )
        elif actual is None or actual.revision != expected_revision:
            raise DraftRevisionConflict(
                expected_revision=expected_revision,
                actual_revision=actual.revision if actual else 0,
            )
        self.drafts[key] = replacement
        return replacement

    def get_playback_session(self, session_id: UUID) -> PlaybackSessionSnapshot | None:
        return self.playback_sessions.get(session_id)

    def add_playback_session(self, item: PlaybackSessionSnapshot) -> None:
        if item.id in self.playback_sessions or any(
            hmac.compare_digest(existing.session_token_hash, item.session_token_hash)
            for existing in self.playback_sessions.values()
        ):
            raise UniqueConstraintViolation("playback session token already exists")
        self.playback_sessions[item.id] = replace(item, session_token=None)

    def compare_and_swap_session(
        self,
        current: PlaybackSessionSnapshot,
        replacement: PlaybackSessionSnapshot,
        *,
        expected_revision: int,
    ) -> PlaybackSessionSnapshot:
        actual = self.playback_sessions.get(current.id)
        if actual is None or actual.revision != expected_revision:
            raise PersistenceConflictError("playback session revision is stale")
        self.playback_sessions[current.id] = replacement
        return replacement

    def get_interval_by_event(
        self, session_id: UUID, event_id: str
    ) -> WatchIntervalSnapshot | None:
        interval_id = self.interval_event_index.get((session_id, event_id))
        if interval_id is None:
            return None
        return next(
            (item for item in self.intervals.get(session_id, ()) if item.id == interval_id), None
        )

    def get_interval_by_sequence(
        self, session_id: UUID, sequence: int
    ) -> WatchIntervalSnapshot | None:
        interval_id = self.interval_sequence_index.get((session_id, sequence))
        if interval_id is None:
            return None
        return next(
            (item for item in self.intervals.get(session_id, ()) if item.id == interval_id), None
        )

    def add_interval(self, item: WatchIntervalSnapshot) -> None:
        if self.get_interval_by_event(item.playback_session_id, item.event_id) is not None:
            raise DuplicateHeartbeatError("playback event id has already been used")
        if self.get_interval_by_sequence(item.playback_session_id, item.sequence) is not None:
            raise ReplayResistanceError("playback sequence has already been used")
        self.intervals.setdefault(item.playback_session_id, []).append(item)
        self.interval_event_index[(item.playback_session_id, item.event_id)] = item.id
        self.interval_sequence_index[(item.playback_session_id, item.sequence)] = item.id

    def intervals_for_session(self, session_id: UUID) -> tuple[WatchIntervalSnapshot, ...]:
        return tuple(self.intervals.get(session_id, ()))

    def find_evidence_by_request(self, *scope: UUID | str) -> EvidenceSnapshot | None:
        tenant_id, enrollment_id, person_id, version_id, activity_id, key = scope
        evidence_id = self.evidence_request_index.get(
            (
                cast(UUID, tenant_id),
                cast(UUID, enrollment_id),
                cast(UUID, person_id),
                cast(UUID, version_id),
                cast(UUID, activity_id),
                cast(str, key),
            )
        )
        return self.evidence.get(evidence_id) if evidence_id is not None else None

    def get_evidence(self, evidence_id: UUID) -> EvidenceSnapshot | None:
        return self.evidence.get(evidence_id)

    def add_evidence(self, item: EvidenceSnapshot) -> None:
        key = (
            item.tenant_id,
            item.enrollment_id,
            item.person_id,
            item.program_version_id,
            item.activity_id,
            item.idempotency_key,
        )
        if key in self.evidence_request_index:
            raise DuplicateEvidenceError("evidence idempotency key has already been submitted")
        self.evidence[item.id] = item
        self.evidence_request_index[key] = item.id

    def find_submission_by_request(self, *scope: UUID | str) -> EvidenceSubmissionSnapshot | None:
        tenant_id, enrollment_id, person_id, version_id, activity_id, key = scope
        submission_id = self.submission_request_index.get(
            (
                cast(UUID, tenant_id),
                cast(UUID, enrollment_id),
                cast(UUID, person_id),
                cast(UUID, version_id),
                cast(UUID, activity_id),
                cast(str, key),
            )
        )
        return self.submissions.get(submission_id) if submission_id is not None else None

    def get_submission(self, submission_id: UUID) -> EvidenceSubmissionSnapshot | None:
        return self.submissions.get(submission_id)

    def submissions_for_evidence(self, evidence_id: UUID) -> tuple[EvidenceSubmissionSnapshot, ...]:
        return tuple(item for item in self.submissions.values() if item.evidence_id == evidence_id)

    def add_submission(self, item: EvidenceSubmissionSnapshot) -> None:
        key = (
            item.tenant_id,
            item.enrollment_id,
            item.person_id,
            item.program_version_id,
            item.activity_id,
            item.idempotency_key,
        )
        if key in self.submission_request_index:
            raise DuplicateEvidenceError("submission idempotency key has already been submitted")
        self.submissions[item.id] = item
        self.submission_request_index[key] = item.id

    def corrections_for_submission(
        self, submission_id: UUID
    ) -> tuple[EvidenceCorrectionSnapshot, ...]:
        return tuple(
            sorted(
                (
                    self.corrections[item_id]
                    for item_id in self.correction_order
                    if self.corrections[item_id].submission_id == submission_id
                ),
                key=lambda item: item.correction_sequence,
            )
        )

    def append_correction(
        self, item: EvidenceCorrectionSnapshot, *, expected_revision: int
    ) -> None:
        latest = self.corrections_for_submission(item.submission_id)
        if len(latest) != expected_revision:
            raise CorrectionRevisionConflict("the submission review revision is stale")
        if latest and item.correction_sequence != latest[-1].correction_sequence + 1:
            raise CorrectionRevisionConflict("the correction sequence is stale")
        if not latest and item.correction_sequence != 1:
            raise CorrectionRevisionConflict("the first correction sequence must be one")
        if any(existing.idempotency_key == item.idempotency_key for existing in latest):
            raise DuplicateEvidenceError("correction idempotency key has already been used")
        self.corrections[item.id] = item
        self.correction_order.append(item.id)

    def get_command(
        self,
        *,
        tenant_id: UUID,
        actor_person_id: UUID,
        operation: str,
        idempotency_key: str,
    ) -> CommandLedgerSnapshot | None:
        return self.commands.get((tenant_id, actor_person_id, operation, idempotency_key))

    def claim_command(self, command: CommandLedgerSnapshot) -> None:
        key = (
            command.tenant_id,
            command.actor_person_id,
            command.operation,
            command.idempotency_key,
        )
        if key in self.commands:
            raise _DuplicateCommandClaim
        self.commands[key] = command

    def complete_command(
        self, command: CommandLedgerSnapshot, *, now: datetime
    ) -> CommandLedgerSnapshot:
        key = (
            command.tenant_id,
            command.actor_person_id,
            command.operation,
            command.idempotency_key,
        )
        current = self.commands.get(key)
        if (
            current is None
            or current.id != command.id
            or current.status is not LearningCommandStatus.PENDING
        ):
            raise PersistenceConflictError("the learning command ledger claim is stale")
        completed = replace(command, status=LearningCommandStatus.COMPLETED, completed_at=_utc(now))
        self.commands[key] = completed
        return completed

    def lock_projection_scope(self, access: LearningAccessContext) -> None:
        if access.scope not in self.access_contexts:
            raise AccessContextRequiredError("projection scope is not server-resolved")

    def upsert_projection(self, item: LearningProgressProjectionSnapshot) -> None:
        key = (item.tenant_id, item.enrollment_id, item.person_id, item.scope_type, item.scope_id)
        self.projections[key] = item


def _validate_access(access: LearningAccessContext) -> None:
    if not access.membership.active or not access.membership.tenant_active:
        raise AccessContextRequiredError("an active tenant membership is required")
    if access.membership.role != LEARNER_ROLE:
        raise AccessContextRequiredError("the learner command requires a learner membership")
    if not access.enrollment_active or not access.entitlement_active:
        raise EntitlementInactiveError("the learner enrollment and entitlement must be active")
    if not access.catalog_version_active or not access.catalog_version_immutable:
        raise CatalogVersionInactiveError("the catalog version must be published and immutable")
    if access.activity.tenant_id is not None and access.activity.tenant_id != access.tenant_id:
        raise ActivityNotFound("activity does not exist in this tenant")
    if access.activity.program_version_id != access.program_version_id:
        raise EvidenceVersionMismatch("the server-resolved activity is not pinned to this version")


def _resolve_access(
    store: LearningRepository,
    *,
    actor: ActorContext,
    tenant_id: UUID,
    enrollment_id: UUID,
    program_version_id: UUID,
    activity_id: UUID,
) -> LearningAccessContext:
    if not isinstance(actor, ActorContext):
        raise AccessContextRequiredError("a trusted ActorContext is required")
    actor.require_tenant(tenant_id)
    access = store.resolve_access(
        actor=actor,
        tenant_id=tenant_id,
        enrollment_id=enrollment_id,
        program_version_id=program_version_id,
        activity_id=activity_id,
    )
    if access.actor != actor:
        raise AccessContextRequiredError("the access context is not bound to the trusted session")
    _validate_access(access)
    return access


def _scope_progress(
    store: LearningRepository, access: LearningAccessContext
) -> dict[UUID, ActivityProgressSnapshot]:
    tenant_id, enrollment_id, person_id, program_version_id, _ = access.scope
    return {
        item.activity_id: item
        for item in store.list_progress(
            tenant_id=tenant_id,
            person_id=person_id,
            enrollment_id=enrollment_id,
            program_version_id=program_version_id,
        )
    }


def _scope_definitions(
    store: LearningRepository, access: LearningAccessContext
) -> dict[UUID, ActivityDefinition]:
    del store
    return {
        activity.id: activity for module in access.program.modules for activity in module.activities
    }


def _require_authoritative_completion(
    store: LearningRepository,
    access: LearningAccessContext,
    definition: ActivityDefinition,
    progress: ActivityProgressSnapshot | None,
) -> None:
    if (
        progress is None
        or _activity_state(progress.state) is not ActivityState.COMPLETED
        or progress.activity_version != definition.version
        or progress.program_version_id != access.program_version_id
        or progress.program_id != access.program.id
        or progress.program_scope != access.program.program_scope
        or progress.program_owner_key != access.program.program_owner_key
        or progress.module_id != definition.module_id
        or progress.completion_evidence_id is None
    ):
        raise ActivityLockedError(
            f"prerequisite {definition.id} is not completed in this catalog scope"
        )
    try:
        _validate_completion_evidence(
            store,
            replace(access, activity=definition),
            progress.completion_evidence_id,
        )
    except DomainError as exc:
        raise ActivityLockedError(
            f"prerequisite {definition.id} has no authoritative completion evidence"
        ) from exc


def authoritative_progress(
    store: LearningRepository, access: LearningAccessContext
) -> dict[UUID, ActivityProgressSnapshot]:
    """Return progress that is safe for learner reads and completion predicates.

    ``ActivityProgress`` is deliberately mutable and its state is not itself
    evidence of completion.  A completed row is only readable as completed
    when it still matches the pinned activity version and has a valid,
    same-scope evidence/submission/review (or playback) chain.  Non-completed
    rows remain visible so the learner can resume work.  This keeps projection
    and certificate callers on the same server-owned completion boundary.
    """

    progress = _scope_progress(store, access)
    definitions = _scope_definitions(store, access)
    authoritative: dict[UUID, ActivityProgressSnapshot] = {}
    for activity_id, item in progress.items():
        if _activity_state(item.state) is not ActivityState.COMPLETED:
            authoritative[activity_id] = item
            continue
        definition = definitions.get(activity_id)
        if definition is None:
            continue
        try:
            _require_authoritative_completion(store, access, definition, item)
        except ActivityLockedError:
            continue
        authoritative[activity_id] = item
    return authoritative


def _require_prerequisites(store: LearningRepository, access: LearningAccessContext) -> None:
    progress = _scope_progress(store, access)
    definitions = _scope_definitions(store, access)
    for prerequisite_id in access.activity.prerequisites:
        definition = definitions.get(prerequisite_id)
        if definition is None:
            raise ActivityLockedError(
                f"prerequisite {prerequisite_id} is outside the pinned program"
            )
        _require_authoritative_completion(
            store,
            access,
            definition,
            progress.get(prerequisite_id),
        )

    modules = {module.id: module for module in access.program.modules}
    current_module = modules.get(access.activity.module_id)
    if current_module is None:
        raise ActivityLockedError("activity module is outside the pinned program")
    for prerequisite_module_id in current_module.prerequisite_module_ids:
        prerequisite_module = modules.get(prerequisite_module_id)
        if prerequisite_module is None:
            raise ActivityLockedError("module prerequisite is outside the pinned program")
        required_activities = tuple(
            definition for definition in prerequisite_module.activities if definition.required
        )
        if not required_activities:
            raise ActivityLockedError("module prerequisite has no completable required activity")
        for definition in required_activities:
            _require_authoritative_completion(
                store,
                access,
                definition,
                progress.get(definition.id),
            )


def _require_current_activity(
    access: LearningAccessContext, progress: ActivityProgressSnapshot | None
) -> None:
    if (
        progress is not None
        and _full_scope_tuple(
            tenant_id=progress.tenant_id,
            enrollment_id=progress.enrollment_id,
            person_id=progress.person_id,
            program_version_id=progress.program_version_id,
            program_id=progress.program_id,
            program_scope=progress.program_scope,
            program_owner_key=progress.program_owner_key,
            module_id=progress.module_id,
            activity_id=progress.activity_id,
        )
        != access.full_scope
    ):
        raise EvidenceVersionMismatch("progress crosses the pinned learning scope")
    if progress is not None and progress.activity_version != access.activity.version:
        raise ActivityVersionConflict("the progress row belongs to an older activity version")


def _fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def _claim_command(
    store: LearningRepository,
    *,
    actor: ActorContext,
    access: LearningAccessContext,
    operation: str,
    idempotency_key: str,
    payload: Mapping[str, Any],
    now: datetime,
) -> tuple[CommandLedgerSnapshot, bool]:
    key = _text(idempotency_key, "idempotency key", 128)
    digest = _fingerprint(payload)
    existing = store.get_command(
        tenant_id=access.tenant_id,
        actor_person_id=actor.person_id,
        operation=operation,
        idempotency_key=key,
    )
    if existing is not None:
        if existing.request_digest != digest:
            raise IdempotencyConflictError(
                "the idempotency key is bound to another request"
            ) from None
        if existing.status is LearningCommandStatus.PENDING:
            raise CommandInProgressError(
                "the idempotency key is owned by an unfinished command"
            ) from None
        return existing, True
    command = CommandLedgerSnapshot(
        id=uuid4(),
        tenant_id=access.tenant_id,
        actor_person_id=actor.person_id,
        person_id=access.person_id,
        enrollment_id=access.enrollment_id,
        program_version_id=access.program_version_id,
        program_id=access.program.id,
        program_scope=access.program.program_scope,
        program_owner_key=access.program.program_owner_key,
        module_id=access.activity.module_id,
        activity_id=access.activity.id,
        operation=operation,
        idempotency_key=key,
        request_digest=digest,
        status=LearningCommandStatus.PENDING,
        created_at=now,
    )
    try:
        store.claim_command(command)
    except _DuplicateCommandClaim:
        raced = store.get_command(
            tenant_id=access.tenant_id,
            actor_person_id=actor.person_id,
            operation=operation,
            idempotency_key=key,
        )
        if raced is None:
            raise PersistenceConflictError(
                "the idempotency race has no canonical ledger row"
            ) from None
        if raced.request_digest != digest:
            raise IdempotencyConflictError(
                "the idempotency key is bound to another request"
            ) from None
        if raced.status is LearningCommandStatus.PENDING:
            raise CommandInProgressError(
                "the idempotency key is owned by an unfinished command"
            ) from None
        return raced, True
    return command, False


def _finish_command(
    store: LearningRepository,
    command: CommandLedgerSnapshot,
    *,
    result: Mapping[str, UUID | None],
    now: datetime,
) -> None:
    store.complete_command(
        replace(
            command,
            result_progress_id=result.get("result_progress_id", command.result_progress_id),
            result_draft_id=result.get("result_draft_id", command.result_draft_id),
            result_session_id=result.get("result_session_id", command.result_session_id),
            result_interval_id=result.get("result_interval_id", command.result_interval_id),
            result_evidence_id=result.get("result_evidence_id", command.result_evidence_id),
            result_submission_id=result.get("result_submission_id", command.result_submission_id),
            result_correction_id=result.get("result_correction_id", command.result_correction_id),
        ),
        now=now,
    )


def _load_progress_replay(
    store: LearningRepository, command: CommandLedgerSnapshot
) -> ActivityProgressSnapshot:
    if command.result_progress_id is not None:
        for item in store.list_progress(
            tenant_id=command.tenant_id,
            person_id=command.person_id,
            enrollment_id=command.enrollment_id,
            program_version_id=command.program_version_id,
        ):
            if item.id == command.result_progress_id and item.activity_id == command.activity_id:
                return item
    raise PersistenceConflictError("the completed command has no replayable progress")


_ALLOWED_TRANSITIONS: dict[ActivityState, frozenset[ActivityState]] = {
    ActivityState.LOCKED: frozenset(),
    ActivityState.AVAILABLE: frozenset({ActivityState.IN_PROGRESS}),
    ActivityState.IN_PROGRESS: frozenset({ActivityState.AWAITING_REVIEW, ActivityState.COMPLETED}),
    ActivityState.AWAITING_REVIEW: frozenset({ActivityState.COMPLETED}),
    ActivityState.COMPLETED: frozenset({ActivityState.COMPLETED}),
}


class PrerequisiteEvaluation:
    """Deterministic prerequisite result used by pure projection callers."""

    def __init__(
        self,
        activity_id: UUID,
        satisfied: bool,
        missing_activity_ids: tuple[UUID, ...] = (),
        missing_module_ids: tuple[UUID, ...] = (),
    ) -> None:
        self.activity_id = activity_id
        self.satisfied = satisfied
        self.missing_activity_ids = missing_activity_ids
        self.missing_module_ids = missing_module_ids

    @property
    def reason(self) -> str:
        if self.satisfied:
            return "prerequisites_satisfied"
        pieces: list[str] = []
        if self.missing_activity_ids:
            pieces.append("activity:" + ",".join(str(value) for value in self.missing_activity_ids))
        if self.missing_module_ids:
            pieces.append("module:" + ",".join(str(value) for value in self.missing_module_ids))
        return "prerequisite_not_completed(" + ";".join(pieces) + ")"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, PrerequisiteEvaluation) and (
            self.activity_id,
            self.satisfied,
            self.missing_activity_ids,
            self.missing_module_ids,
        ) == (
            other.activity_id,
            other.satisfied,
            other.missing_activity_ids,
            other.missing_module_ids,
        )


class PrerequisiteEvaluator:
    """Evaluate explicit activity and module prerequisites deterministically."""

    def evaluate(
        self,
        activity: ActivityDefinition,
        progress_by_activity: Mapping[UUID, ActivityProgressSnapshot],
        *,
        activities: Mapping[UUID, ActivityDefinition] | None = None,
        completed_modules: Mapping[UUID, bool] | None = None,
        prerequisite_module_ids: Iterable[UUID] = (),
    ) -> PrerequisiteEvaluation:
        missing_activities: list[UUID] = []
        for prerequisite_id in activity.prerequisites:
            item = progress_by_activity.get(prerequisite_id)
            definition = activities.get(prerequisite_id) if activities else None
            if (
                item is None
                or _activity_state(item.state) is not ActivityState.COMPLETED
                or (definition is not None and item.activity_version != definition.version)
            ):
                missing_activities.append(prerequisite_id)
        missing_modules = [
            module_id
            for module_id in prerequisite_module_ids
            if not (completed_modules or {}).get(module_id, False)
        ]
        return PrerequisiteEvaluation(
            activity_id=activity.id,
            satisfied=not missing_activities and not missing_modules,
            missing_activity_ids=tuple(dict.fromkeys(missing_activities)),
            missing_module_ids=tuple(dict.fromkeys(missing_modules)),
        )


def evaluate_prerequisites(
    activity: ActivityDefinition,
    progress_by_activity: Mapping[UUID, ActivityProgressSnapshot],
    *,
    activities: Mapping[UUID, ActivityDefinition] | None = None,
    completed_modules: Mapping[UUID, bool] | None = None,
    prerequisite_module_ids: Iterable[UUID] = (),
) -> PrerequisiteEvaluation:
    return PrerequisiteEvaluator().evaluate(
        activity,
        progress_by_activity,
        activities=activities,
        completed_modules=completed_modules,
        prerequisite_module_ids=prerequisite_module_ids,
    )


def _require_expected_revision(value: int) -> int:
    if isinstance(value, bool) or value < 0:
        raise DraftRevisionConflict("expected revision must be a nonnegative integer")
    return value


def _completion_evidence(
    store: LearningRepository,
    access: LearningAccessContext,
    evidence_id: UUID,
) -> EvidenceSnapshot:
    evidence = store.get_evidence(evidence_id)
    if evidence is None:
        raise InvalidEvidence("completion evidence does not exist")
    evidence_scope = (
        evidence.tenant_id,
        evidence.enrollment_id,
        evidence.person_id,
        evidence.program_version_id,
        evidence.program_id,
        evidence.program_scope,
        evidence.program_owner_key,
        evidence.module_id,
        evidence.activity_id,
    )
    if evidence_scope != access.full_scope:
        raise InvalidEvidence("completion evidence is outside the requested learning scope")
    if evidence.activity_version != access.activity.version:
        raise EvidenceVersionMismatch("completion evidence belongs to an older activity version")
    return evidence


def _pinned_video_policy(session: PlaybackSessionSnapshot) -> VideoEvidencePolicy:
    return VideoEvidencePolicy(
        version=session.policy_version,
        coverage_threshold=session.coverage_threshold,
        session_ttl_seconds=max(1, int((session.expires_at - session.started_at).total_seconds())),
        future_clock_skew_seconds=0,
        minimum_watch_interval_seconds=session.minimum_watch_interval_seconds,
        max_event_seconds=session.max_event_seconds,
        max_heartbeat_gap_seconds=session.max_heartbeat_gap_seconds,
        minimum_heartbeats_for_completion=session.minimum_heartbeats_for_completion,
        clock_grace_seconds=session.clock_grace_seconds,
        max_rewind_seconds=session.max_rewind_seconds,
    )


def _validated_watch_intervals(
    session: PlaybackSessionSnapshot,
    records: Iterable[WatchIntervalSnapshot],
) -> tuple[TimeInterval, ...]:
    policy = _pinned_video_policy(session)
    ordered = tuple(sorted(records, key=lambda item: item.sequence))
    expected_sequence = 1
    previous_position = 0.0
    previous_observed_at = session.started_at
    watched: list[TimeInterval] = []
    for record in ordered:
        if record.sequence != expected_sequence:
            raise ReplayResistanceError("playback evidence has a non-contiguous sequence")
        if _full_scope_tuple(
            tenant_id=record.tenant_id,
            enrollment_id=record.enrollment_id,
            person_id=record.person_id,
            program_version_id=record.program_version_id,
            program_id=record.program_id,
            program_scope=record.program_scope,
            program_owner_key=record.program_owner_key,
            module_id=record.module_id,
            activity_id=record.activity_id,
        ) != _full_scope_tuple(
            tenant_id=session.tenant_id,
            enrollment_id=session.enrollment_id,
            person_id=session.person_id,
            program_version_id=session.program_version_id,
            program_id=session.program_id,
            program_scope=session.program_scope,
            program_owner_key=session.program_owner_key,
            module_id=session.module_id,
            activity_id=session.activity_id,
        ):
            raise InvalidEvidence("playback event crosses the pinned session scope")
        elapsed = (record.observed_at - previous_observed_at).total_seconds()
        if elapsed < 0:
            raise ReplayResistanceError("playback evidence time is not monotonic")
        if record.kind is WatchIntervalKind.WATCH:
            if elapsed > policy.max_heartbeat_gap_seconds + policy.clock_grace_seconds:
                raise ReplayResistanceError("playback heartbeat gap exceeds the pinned policy")
            if record.start_seconds < previous_position - policy.max_rewind_seconds:
                raise ReplayResistanceError("playback position rewound beyond the pinned policy")
            if record.start_seconds > previous_position + policy.clock_grace_seconds:
                raise ReplayResistanceError("watched positions are not sequential")
            if (
                record.interval.duration_seconds
                > min(
                    policy.max_event_seconds,
                    elapsed + policy.clock_grace_seconds,
                )
                + 1e-9
            ):
                raise ReplayResistanceError("playback interval exceeds server-observed time")
            watched.append(record.interval)
        previous_position = record.end_seconds
        previous_observed_at = record.observed_at
        expected_sequence += 1
    if len(watched) < policy.minimum_heartbeats_for_completion:
        raise InsufficientCoverageError(coverage_ratio=0.0, threshold=policy.coverage_threshold)
    return tuple(watched)


def _validate_completion_evidence(
    store: LearningRepository,
    access: LearningAccessContext,
    evidence_id: UUID,
) -> None:
    evidence = _completion_evidence(store, access, evidence_id)
    expected_type = {
        ActivityKind.VIDEO: EvidenceType.VIDEO_WATCH,
        ActivityKind.REFLECTION: EvidenceType.REFLECTION,
        ActivityKind.IMPLEMENTATION_CHALLENGE: EvidenceType.IMPLEMENTATION,
        ActivityKind.REVIEW: EvidenceType.REVIEW,
        ActivityKind.IMPROVE: EvidenceType.IMPROVEMENT,
    }[_activity_kind(access.activity.kind)]
    if evidence.evidence_type is not expected_type:
        raise InvalidEvidence("completion evidence type does not match the catalog activity")
    submissions = tuple(
        item
        for item in store.submissions_for_evidence(evidence.id)
        if (
            item.tenant_id,
            item.enrollment_id,
            item.person_id,
            item.program_version_id,
            item.program_id,
            item.program_scope,
            item.program_owner_key,
            item.module_id,
            item.activity_id,
        )
        == access.full_scope
    )
    if len(submissions) != 1:
        raise InvalidEvidence("completion requires one same-scope evidence submission")
    submission = submissions[0]
    if access.activity.human_review_required:
        corrections = store.corrections_for_submission(submission.id)
        if not corrections or corrections[-1].decision is not ReviewDecision.APPROVED:
            raise HumanReviewRequiredError("completion requires the effective human approval")
        return
    if evidence.playback_session_id is None:
        raise InvalidEvidence("video completion requires a playback session")
    session = store.get_playback_session(evidence.playback_session_id)
    if (
        session is None
        or (
            session.tenant_id,
            session.enrollment_id,
            session.person_id,
            session.program_version_id,
            session.program_id,
            session.program_scope,
            session.program_owner_key,
            session.module_id,
            session.activity_id,
        )
        != access.full_scope
    ):
        raise InvalidEvidence("video completion requires a same-scope playback session")
    policy = _pinned_video_policy(session)
    intervals = _validated_watch_intervals(session, store.intervals_for_session(session.id))
    coverage = validate_video_evidence(intervals, session.duration_seconds, policy=policy)
    if (
        evidence.policy_version != session.policy_version
        or coverage.policy_version != access.activity.policy_version
    ):
        raise EvidenceVersionMismatch(
            "video evidence policy is not the server-pinned activity policy"
        )


def _materialize_projections(
    store: LearningRepository,
    access: LearningAccessContext,
    *,
    computed_at: datetime,
) -> None:
    store.lock_projection_scope(access)
    persisted_progress = {
        item.activity_id: item
        for item in store.list_progress(
            tenant_id=access.tenant_id,
            person_id=access.person_id,
            enrollment_id=access.enrollment_id,
            program_version_id=access.program_version_id,
        )
    }
    definitions = {
        activity.id: activity for module in access.program.modules for activity in module.activities
    }
    progress_by_activity: dict[UUID, ActivityProgressSnapshot] = {}
    evidence_by_activity: dict[UUID, EvidenceSnapshot] = {}
    for item in persisted_progress.values():
        if _activity_state(item.state) is not ActivityState.COMPLETED:
            progress_by_activity[item.activity_id] = item
            continue
        definition = definitions.get(item.activity_id)
        if definition is None or item.completion_evidence_id is None:
            continue
        try:
            _validate_completion_evidence(
                store,
                replace(access, activity=definition),
                item.completion_evidence_id,
            )
        except DomainError:
            continue
        evidence = store.get_evidence(item.completion_evidence_id)
        if evidence is not None:
            progress_by_activity[item.activity_id] = item
            evidence_by_activity[item.activity_id] = evidence
    course = ProgressProjector(access.program.projection_version).project_authoritative(
        access.program,
        progress_by_activity,
        evidence_by_activity,
    )
    for module in course.modules:
        explanation = module.explanation.as_dict()
        store.upsert_projection(
            LearningProgressProjectionSnapshot(
                tenant_id=access.tenant_id,
                person_id=access.person_id,
                enrollment_id=access.enrollment_id,
                program_version_id=access.program_version_id,
                program_id=access.program.id,
                program_scope=access.program.program_scope,
                program_owner_key=access.program.program_owner_key,
                module_id=module.module_id,
                scope_type=ProjectionScope.MODULE.value,
                scope_id=module.module_id,
                denominator=module.denominator,
                completed_count=module.completed_count,
                percentage=module.percentage,
                projection_version=module.projection_version,
                explanation=explanation,
                computed_at=computed_at,
            )
        )
    store.upsert_projection(
        LearningProgressProjectionSnapshot(
            tenant_id=access.tenant_id,
            person_id=access.person_id,
            enrollment_id=access.enrollment_id,
            program_version_id=access.program_version_id,
            program_id=access.program.id,
            program_scope=access.program.program_scope,
            program_owner_key=access.program.program_owner_key,
            module_id=None,
            scope_type=ProjectionScope.COURSE.value,
            scope_id=access.program.id,
            denominator=course.denominator,
            completed_count=course.completed_count,
            percentage=course.percentage,
            projection_version=course.projection_version,
            explanation=course.explanation.as_dict(),
            computed_at=computed_at,
        )
    )


class ActivityService:
    """Apply scoped activity transitions behind a trusted repository boundary."""

    def __init__(self, store: LearningRepository, *, clock: Callable[[], datetime]) -> None:
        self.store = store
        self.clock = clock
        self.prerequisites = PrerequisiteEvaluator()

    def _access(
        self,
        *,
        actor: ActorContext,
        tenant_id: UUID,
        enrollment_id: UUID,
        program_version_id: UUID,
        activity_id: UUID,
    ) -> LearningAccessContext:
        return _resolve_access(
            self.store,
            actor=actor,
            tenant_id=tenant_id,
            enrollment_id=enrollment_id,
            program_version_id=program_version_id,
            activity_id=activity_id,
        )

    def current_state(
        self,
        *,
        actor: ActorContext,
        tenant_id: UUID,
        enrollment_id: UUID,
        program_version_id: UUID,
        activity_id: UUID,
    ) -> ActivityState:
        access = self._access(
            actor=actor,
            tenant_id=tenant_id,
            enrollment_id=enrollment_id,
            program_version_id=program_version_id,
            activity_id=activity_id,
        )
        progress = self.store.get_progress(*access.scope)
        _require_current_activity(access, progress)
        try:
            _require_prerequisites(self.store, access)
        except ActivityLockedError:
            return ActivityState.LOCKED
        if progress is None:
            return ActivityState.AVAILABLE
        state = _activity_state(progress.state)
        if state is ActivityState.COMPLETED:
            try:
                _require_authoritative_completion(
                    self.store,
                    access,
                    access.activity,
                    progress,
                )
            except ActivityLockedError:
                # A stale or malformed completion must not be exposed as a
                # learner completion.  The next checked write can replace it
                # through the normal CAS path; no direct repair is performed
                # by this read.
                return ActivityState.AVAILABLE
        return state

    def _ensure_started(
        self,
        access: LearningAccessContext,
        *,
        expected_revision: int,
        moment: datetime,
    ) -> ActivityProgressSnapshot:
        expected_revision = _require_expected_revision(expected_revision)
        progress = self.store.get_progress(*access.scope)
        _require_current_activity(access, progress)
        if progress is not None and progress.revision != expected_revision:
            raise DraftRevisionConflict(
                expected_revision=expected_revision,
                actual_revision=progress.revision,
            )
        _require_prerequisites(self.store, access)
        if progress is not None:
            state = _activity_state(progress.state)
            if state is ActivityState.COMPLETED:
                try:
                    _require_authoritative_completion(
                        self.store,
                        access,
                        access.activity,
                        progress,
                    )
                except ActivityLockedError:
                    # Treat an invalid historical completion as an available
                    # activity.  The replacement below is an auditable CAS
                    # transition, not an out-of-band repair.
                    pass
                else:
                    return progress
            if state in {ActivityState.IN_PROGRESS, ActivityState.AWAITING_REVIEW}:
                return progress
        replacement = ActivityProgressSnapshot(
            tenant_id=access.tenant_id,
            person_id=access.person_id,
            enrollment_id=access.enrollment_id,
            program_version_id=access.program_version_id,
            program_id=access.program.id,
            program_scope=access.program.program_scope,
            program_owner_key=access.program.program_owner_key,
            module_id=access.activity.module_id,
            activity_id=access.activity.id,
            state=ActivityState.IN_PROGRESS,
            activity_version=access.activity.version,
            policy_version=(
                access.activity.policy_version
                if access.activity.kind is ActivityKind.VIDEO
                else None
            ),
            revision=(progress.revision + 1 if progress is not None else 1),
            started_at=progress.started_at
            if progress is not None and progress.started_at
            else moment,
            updated_at=moment,
        )
        return self.store.compare_and_swap_progress(
            progress,
            replacement,
            expected_revision=expected_revision,
        )

    def start(
        self,
        *,
        actor: ActorContext,
        tenant_id: UUID,
        enrollment_id: UUID,
        program_version_id: UUID,
        activity_id: UUID,
        expected_revision: int,
        idempotency_key: str,
    ) -> ActivityProgressSnapshot:
        access = self._access(
            actor=actor,
            tenant_id=tenant_id,
            enrollment_id=enrollment_id,
            program_version_id=program_version_id,
            activity_id=activity_id,
        )
        moment = _server_now(self.clock)
        payload = {"activity_id": str(activity_id), "expected_revision": expected_revision}
        with self.store.atomic():
            # Serialize the complete learning scope before any child-row write.
            # Projection materialization takes this same lock defensively; taking it
            # here establishes enrollment -> child rows as the only lock order.
            self.store.lock_projection_scope(access)
            command, replayed = _claim_command(
                self.store,
                actor=actor,
                access=access,
                operation="activity_start",
                idempotency_key=idempotency_key,
                payload=payload,
                now=moment,
            )
            if replayed:
                return _load_progress_replay(self.store, command)
            progress = self._ensure_started(
                access,
                expected_revision=expected_revision,
                moment=moment,
            )
            _materialize_projections(self.store, access, computed_at=moment)
            _finish_command(
                self.store,
                command,
                result={"result_progress_id": progress.id},
                now=moment,
            )
            return progress

    def _transition_internal(
        self,
        access: LearningAccessContext,
        *,
        requested: ActivityState,
        expected_revision: int,
        moment: datetime,
        completion_evidence_id: UUID | None,
        allow_review_reset: bool = False,
    ) -> ActivityProgressSnapshot:
        expected_revision = _require_expected_revision(expected_revision)
        progress = self.store.get_progress(*access.scope)
        if progress is None:
            raise ActivityStateError("activity must be started before it can transition")
        _require_current_activity(access, progress)
        if progress.revision != expected_revision:
            raise PersistenceConflictError("activity progress revision is stale")
        current = _activity_state(progress.state)
        if current is ActivityState.LOCKED:
            raise ActivityStateError(
                "locked activity may only enter progress through the checked start command"
            )
        if current is ActivityState.COMPLETED:
            if (
                requested is ActivityState.COMPLETED
                and completion_evidence_id == progress.completion_evidence_id
            ):
                return progress
            raise CompletedActivityMutationError(
                "completed activity cannot be reopened or replaced"
            )
        review_reset = (
            allow_review_reset
            and current is ActivityState.AWAITING_REVIEW
            and requested is ActivityState.IN_PROGRESS
        )
        if requested not in _ALLOWED_TRANSITIONS[current] and not review_reset:
            raise ActivityStateError(
                f"cannot transition activity from {current.value} to {requested.value}"
            )
        if (
            requested is ActivityState.IN_PROGRESS
            and current is ActivityState.AWAITING_REVIEW
            and not allow_review_reset
        ):
            raise ReviewNotAllowedError(
                "only the review command may return awaiting work to progress"
            )
        if requested is ActivityState.AWAITING_REVIEW and not access.activity.human_review_required:
            raise ActivityStateError("objective activity cannot await human review")
        if requested is ActivityState.COMPLETED:
            if completion_evidence_id is None:
                raise InvalidEvidence("official completion requires a recorded evidence id")
            _validate_completion_evidence(self.store, access, completion_evidence_id)
            replacement = replace(
                progress,
                state=requested,
                revision=progress.revision + 1,
                completed_at=moment,
                awaiting_review_at=None,
                completion_evidence_id=completion_evidence_id,
                updated_at=moment,
            )
        elif requested is ActivityState.AWAITING_REVIEW:
            replacement = replace(
                progress,
                state=requested,
                revision=progress.revision + 1,
                awaiting_review_at=moment,
                completed_at=None,
                completion_evidence_id=None,
                updated_at=moment,
            )
        else:
            replacement = replace(
                progress,
                state=requested,
                revision=progress.revision + 1,
                completed_at=None,
                awaiting_review_at=None,
                completion_evidence_id=None,
                updated_at=moment,
            )
        return self.store.compare_and_swap_progress(
            progress,
            replacement,
            expected_revision=expected_revision,
        )

    def transition(
        self,
        *,
        actor: ActorContext,
        tenant_id: UUID,
        enrollment_id: UUID,
        program_version_id: UUID,
        activity_id: UUID,
        state: ActivityState | str,
        expected_revision: int,
        idempotency_key: str,
        completion_evidence_id: UUID | None = None,
    ) -> ActivityProgressSnapshot:
        access = self._access(
            actor=actor,
            tenant_id=tenant_id,
            enrollment_id=enrollment_id,
            program_version_id=program_version_id,
            activity_id=activity_id,
        )
        _require_prerequisites(self.store, access)
        requested = _activity_state(state)
        moment = _server_now(self.clock)
        payload = {
            "activity_id": str(activity_id),
            "state": requested.value,
            "expected_revision": expected_revision,
            "completion_evidence_id": (
                str(completion_evidence_id) if completion_evidence_id else None
            ),
        }
        with self.store.atomic():
            self.store.lock_projection_scope(access)
            command, replayed = _claim_command(
                self.store,
                actor=actor,
                access=access,
                operation="activity_transition",
                idempotency_key=idempotency_key,
                payload=payload,
                now=moment,
            )
            if replayed:
                return _load_progress_replay(self.store, command)
            progress = self._transition_internal(
                access,
                requested=requested,
                expected_revision=expected_revision,
                moment=moment,
                completion_evidence_id=completion_evidence_id,
            )
            _materialize_projections(self.store, access, computed_at=moment)
            _finish_command(
                self.store,
                command,
                result={"result_progress_id": progress.id},
                now=moment,
            )
            return progress


def _load_draft_replay(store: LearningRepository, command: CommandLedgerSnapshot) -> DraftSnapshot:
    if command.result_draft_id is None:
        raise PersistenceConflictError("the completed draft command has no replayable draft")
    draft = store.get_draft(
        command.tenant_id,
        command.enrollment_id,
        command.person_id,
        command.program_version_id,
        command.activity_id,
    )
    if draft is None or draft.id != command.result_draft_id:
        raise PersistenceConflictError("the completed draft command points to missing state")
    return draft


class DraftService:
    """Persist drafts with a durable command ledger and SQL-style CAS."""

    def __init__(self, store: LearningRepository, *, clock: Callable[[], datetime]) -> None:
        self.store = store
        self.clock = clock
        self.activities = ActivityService(store, clock=clock)

    def get(
        self,
        *,
        actor: ActorContext,
        tenant_id: UUID,
        enrollment_id: UUID,
        program_version_id: UUID,
        activity_id: UUID,
    ) -> DraftSnapshot | None:
        access = self.activities._access(
            actor=actor,
            tenant_id=tenant_id,
            enrollment_id=enrollment_id,
            program_version_id=program_version_id,
            activity_id=activity_id,
        )
        _require_prerequisites(self.store, access)
        draft = self.store.get_draft(*access.scope)
        if draft is not None and draft.program_version_id != access.program_version_id:
            raise EvidenceVersionMismatch("draft belongs to another program version")
        return draft

    def save(
        self,
        *,
        actor: ActorContext,
        tenant_id: UUID,
        enrollment_id: UUID,
        program_version_id: UUID,
        activity_id: UUID,
        payload: Mapping[str, Any],
        expected_revision: int,
        idempotency_key: str,
    ) -> DraftSnapshot:
        access = self.activities._access(
            actor=actor,
            tenant_id=tenant_id,
            enrollment_id=enrollment_id,
            program_version_id=program_version_id,
            activity_id=activity_id,
        )
        _require_prerequisites(self.store, access)
        normalized_payload = _canonical_payload(payload, maximum_bytes=MAX_DRAFT_PAYLOAD_BYTES)
        moment = _server_now(self.clock)
        command_payload = {
            "activity_id": str(activity_id),
            "expected_revision": expected_revision,
            "payload": normalized_payload,
        }
        with self.store.atomic():
            self.store.lock_projection_scope(access)
            command, replayed = _claim_command(
                self.store,
                actor=actor,
                access=access,
                operation="draft_save",
                idempotency_key=idempotency_key,
                payload=command_payload,
                now=moment,
            )
            if replayed:
                return _load_draft_replay(self.store, command)
            expected_revision = _require_expected_revision(expected_revision)
            current_progress = self.store.get_progress(*access.scope)
            _require_current_activity(access, current_progress)
            if current_progress is None:
                current_progress = self.activities._ensure_started(
                    access, expected_revision=0, moment=moment
                )
            elif _activity_state(current_progress.state) is ActivityState.LOCKED:
                raise ActivityStateError(
                    "locked activity must pass the checked start command before drafting"
                )
            elif _activity_state(current_progress.state) is ActivityState.AVAILABLE:
                current_progress = self.activities._ensure_started(
                    access,
                    expected_revision=current_progress.revision,
                    moment=moment,
                )
            elif _activity_state(current_progress.state) is ActivityState.COMPLETED:
                raise CompletedActivityMutationError("completed activity cannot accept a new draft")
            elif _activity_state(current_progress.state) is ActivityState.AWAITING_REVIEW:
                raise ActivityStateError("an activity awaiting review cannot accept a new draft")
            current = self.store.get_draft(*access.scope)
            if current is not None and current.revision != expected_revision:
                raise DraftRevisionConflict(
                    expected_revision=expected_revision,
                    actual_revision=current.revision,
                )
            if current is None and expected_revision != 0:
                raise DraftRevisionConflict(expected_revision=expected_revision, actual_revision=0)
            draft = DraftSnapshot(
                tenant_id=access.tenant_id,
                person_id=access.person_id,
                enrollment_id=access.enrollment_id,
                program_version_id=access.program_version_id,
                program_id=access.program.id,
                program_scope=access.program.program_scope,
                program_owner_key=access.program.program_owner_key,
                module_id=access.activity.module_id,
                activity_id=access.activity.id,
                payload=normalized_payload,
                revision=expected_revision + 1,
                status=DraftStatus.SAVED,
                id=current.id if current is not None else uuid4(),
                last_idempotency_key=_text(idempotency_key, "idempotency key", 128),
                last_request_fingerprint=_fingerprint(normalized_payload),
                saved_at=moment,
            )
            self.store.compare_and_swap_draft(
                current,
                draft,
                expected_revision=expected_revision,
            )
            _materialize_projections(self.store, access, computed_at=moment)
            _finish_command(
                self.store,
                command,
                result={"result_draft_id": draft.id},
                now=moment,
            )
            return draft

    save_draft = save


def _token_hash(token: str) -> bytes:
    return hashlib.sha256(_text(token, "session token", 512).encode("utf-8")).digest()


class PlaybackService:
    """Create version-pinned sessions and reject forged or replayed events."""

    def __init__(
        self,
        store: LearningRepository,
        *,
        policy_resolver: Callable[[LearningAccessContext], VideoEvidencePolicy],
        clock: Callable[[], datetime],
    ) -> None:
        self.store = store
        self.policy_resolver = policy_resolver
        self.clock = clock
        self.activities = ActivityService(store, clock=clock)

    def _server_policy(self, access: LearningAccessContext) -> VideoEvidencePolicy:
        try:
            policy = self.policy_resolver(access)
        except Exception as exc:
            raise CatalogVersionInactiveError(
                "the video policy could not be resolved server-side"
            ) from exc
        if not isinstance(policy, VideoEvidencePolicy):
            raise CatalogVersionInactiveError(
                "the video policy resolver returned an invalid policy"
            )
        if policy.version != access.activity.policy_version:
            raise EvidenceVersionMismatch("the server policy is not pinned to the activity")
        if abs(policy.coverage_threshold - access.activity.coverage_threshold) > 1e-12:
            raise EvidenceVersionMismatch(
                "the server policy threshold is not pinned to the activity"
            )
        return policy

    def start_session(
        self,
        *,
        actor: ActorContext,
        tenant_id: UUID,
        enrollment_id: UUID,
        program_version_id: UUID,
        activity_id: UUID,
        expected_revision: int,
        idempotency_key: str,
    ) -> PlaybackSessionSnapshot:
        access = self.activities._access(
            actor=actor,
            tenant_id=tenant_id,
            enrollment_id=enrollment_id,
            program_version_id=program_version_id,
            activity_id=activity_id,
        )
        if access.activity.kind is not ActivityKind.VIDEO:
            raise InvalidEvidence("playback sessions are only valid for video activities")
        policy = self._server_policy(access)
        moment = _server_now(self.clock)
        payload = {"activity_id": str(activity_id), "expected_revision": expected_revision}
        with self.store.atomic():
            self.store.lock_projection_scope(access)
            command, replayed = _claim_command(
                self.store,
                actor=actor,
                access=access,
                operation="playback_start",
                idempotency_key=idempotency_key,
                payload=payload,
                now=moment,
            )
            if replayed:
                if command.result_session_id is None:
                    raise PersistenceConflictError("the completed playback command has no session")
                session = self.store.get_playback_session(command.result_session_id)
                if session is None:
                    raise PersistenceConflictError(
                        "the completed playback command points to missing session"
                    )
                return session
            progress = self.store.get_progress(*access.scope)
            if progress is not None and _activity_state(progress.state) is ActivityState.COMPLETED:
                raise CompletedActivityMutationError("completed activity cannot start playback")
            progress = self.activities._ensure_started(
                access,
                expected_revision=expected_revision,
                moment=moment,
            )
            if _activity_state(progress.state) is ActivityState.COMPLETED:
                raise CompletedActivityMutationError("completed activity cannot start playback")
            duration = access.activity.video_duration_seconds
            if duration is None:
                raise InvalidLearningInput("video duration is required to start playback")
            token = secrets.token_urlsafe(32)
            session = PlaybackSessionSnapshot(
                tenant_id=access.tenant_id,
                person_id=access.person_id,
                enrollment_id=access.enrollment_id,
                program_version_id=access.program_version_id,
                program_id=access.program.id,
                program_scope=access.program.program_scope,
                program_owner_key=access.program.program_owner_key,
                module_id=access.activity.module_id,
                activity_id=access.activity.id,
                content_version=access.activity.version,
                policy_version=policy.version,
                session_token_hash=_token_hash(token),
                duration_seconds=duration,
                coverage_threshold=policy.coverage_threshold,
                minimum_watch_interval_seconds=policy.minimum_watch_interval_seconds,
                max_event_seconds=policy.max_event_seconds,
                max_heartbeat_gap_seconds=policy.max_heartbeat_gap_seconds,
                minimum_heartbeats_for_completion=policy.minimum_heartbeats_for_completion,
                clock_grace_seconds=policy.clock_grace_seconds,
                max_rewind_seconds=policy.max_rewind_seconds,
                started_at=moment,
                expires_at=moment + timedelta(seconds=policy.session_ttl_seconds),
                status=PlaybackSessionStatus.ACTIVE,
                revision=0,
                last_sequence=0,
                last_position_seconds=0.0,
                last_heartbeat_at=None,
                closed_at=None,
                id=uuid4(),
                session_token=token,
            )
            self.store.add_playback_session(session)
            _materialize_projections(self.store, access, computed_at=moment)
            _finish_command(
                self.store,
                command,
                result={"result_session_id": session.id},
                now=moment,
            )
            return session

    start = start_session

    def _owned_session(
        self,
        *,
        session_id: UUID,
        access: LearningAccessContext,
        session_token: str,
        now: datetime,
        allow_closed: bool = False,
    ) -> PlaybackSessionSnapshot:
        session = self.store.get_playback_session(session_id)
        if session is None:
            raise PlaybackSessionNotFound("playback session does not exist")
        if (
            session.tenant_id,
            session.enrollment_id,
            session.person_id,
            session.program_version_id,
            session.program_id,
            session.program_scope,
            session.program_owner_key,
            session.module_id,
            session.activity_id,
        ) != access.full_scope:
            raise AuthorizationDenied("playback session does not belong to this learning scope")
        if not hmac.compare_digest(session.session_token_hash, _token_hash(session_token)):
            raise SessionTokenError("playback session token is invalid")
        if session.is_expired_at(now):
            raise PlaybackSessionExpired("playback session evidence window has expired")
        if not allow_closed and session.status is PlaybackSessionStatus.CLOSED:
            raise PlaybackSessionClosed("playback session is closed")
        if (
            session.content_version != access.activity.version
            or session.policy_version != access.activity.policy_version
        ):
            raise EvidenceVersionMismatch(
                "playback session is no longer pinned to the activity version"
            )
        return session

    def record_event(
        self,
        *,
        actor: ActorContext,
        tenant_id: UUID,
        enrollment_id: UUID,
        program_version_id: UUID,
        activity_id: UUID,
        session_id: UUID,
        session_token: str,
        event_id: str,
        sequence: int,
        start_seconds: float,
        end_seconds: float,
        kind: WatchIntervalKind | str,
        idempotency_key: str,
    ) -> WatchIntervalSnapshot:
        access = self.activities._access(
            actor=actor,
            tenant_id=tenant_id,
            enrollment_id=enrollment_id,
            program_version_id=program_version_id,
            activity_id=activity_id,
        )
        _require_prerequisites(self.store, access)
        moment = _server_now(self.clock)
        normalized_event = _text(event_id, "event id", 128)
        normalized_kind = _watch_kind(kind)
        start = _number(start_seconds, "interval start")
        end = _number(end_seconds, "interval end")
        payload = {
            "session_id": str(session_id),
            "event_id": normalized_event,
            "sequence": sequence,
            "start_seconds": start,
            "end_seconds": end,
            "kind": normalized_kind.value,
            "token_hash": _token_hash(session_token).hex(),
        }
        with self.store.atomic():
            self.store.lock_projection_scope(access)
            session = self._owned_session(
                session_id=session_id,
                access=access,
                session_token=session_token,
                now=moment,
            )
            policy = _pinned_video_policy(session)
            command, replayed = _claim_command(
                self.store,
                actor=actor,
                access=access,
                operation="playback_event",
                idempotency_key=idempotency_key,
                payload=payload,
                now=moment,
            )
            if replayed:
                if command.result_interval_id is None:
                    raise PersistenceConflictError("the completed playback event has no interval")
                existing = self.store.get_interval_by_event(session_id, normalized_event)
                if existing is None or existing.id != command.result_interval_id:
                    raise PersistenceConflictError(
                        "the completed playback event points to missing state"
                    )
                return existing
            progress = self.store.get_progress(*access.scope)
            _require_current_activity(access, progress)
            if progress is None or _activity_state(progress.state) is not ActivityState.IN_PROGRESS:
                if (
                    progress is not None
                    and _activity_state(progress.state) is ActivityState.COMPLETED
                ):
                    raise CompletedActivityMutationError(
                        "completed activity cannot accept playback events"
                    )
                raise ActivityStateError("playback events require an activity in progress")
            if sequence <= 0:
                raise ReplayResistanceError("playback sequence must be positive")
            existing_event = self.store.get_interval_by_event(session_id, normalized_event)
            if existing_event is not None:
                if (
                    existing_event.sequence,
                    existing_event.start_seconds,
                    existing_event.end_seconds,
                    existing_event.kind,
                ) == (sequence, start, end, normalized_kind):
                    _finish_command(
                        self.store,
                        command,
                        result={"result_interval_id": existing_event.id},
                        now=moment,
                    )
                    return existing_event
                raise DuplicateHeartbeatError("playback event id was reused with different data")
            if sequence != session.last_sequence + 1:
                raise ReplayResistanceError("playback events must use the next monotonic sequence")
            if end < start or start < 0 or end > session.duration_seconds:
                raise ImpossibleEvidenceError("playback interval is outside the video timeline")
            if normalized_kind is WatchIntervalKind.WATCH and end <= start:
                raise SeekOnlyEvidenceError("a zero-length playback event is seek-only evidence")
            if start < session.last_position_seconds - policy.max_rewind_seconds:
                raise ReplayResistanceError("playback position moved backwards beyond policy")
            if (
                normalized_kind is WatchIntervalKind.WATCH
                and start > session.last_position_seconds + policy.clock_grace_seconds
            ):
                raise ReplayResistanceError("watched positions must follow the last heartbeat")
            elapsed_since_start = (moment - session.started_at).total_seconds()
            if elapsed_since_start < 0:
                raise ImpossibleEvidenceError("server clock precedes playback session start")
            allowed_position = elapsed_since_start + policy.clock_grace_seconds
            if end > allowed_position + 1e-9:
                raise ReplayResistanceError("playback advanced beyond trusted server time")
            anchor = session.last_heartbeat_at or session.started_at
            elapsed_since_event = (moment - anchor).total_seconds()
            if elapsed_since_event < 0:
                raise ImpossibleEvidenceError("playback event time is not monotonic")
            if (
                normalized_kind is WatchIntervalKind.WATCH
                and elapsed_since_event
                > policy.max_heartbeat_gap_seconds + policy.clock_grace_seconds
            ):
                raise ReplayResistanceError("playback heartbeat gap exceeds the pinned policy")
            if (
                end - start
                > min(policy.max_event_seconds, elapsed_since_event + policy.clock_grace_seconds)
                + 1e-9
            ):
                raise ReplayResistanceError(
                    "playback interval exceeds real-time advancement policy"
                )
            interval = WatchIntervalSnapshot(
                playback_session_id=session.id,
                tenant_id=session.tenant_id,
                person_id=session.person_id,
                enrollment_id=session.enrollment_id,
                program_version_id=session.program_version_id,
                program_id=session.program_id,
                program_scope=session.program_scope,
                program_owner_key=session.program_owner_key,
                module_id=session.module_id,
                activity_id=session.activity_id,
                event_id=normalized_event,
                sequence=sequence,
                start_seconds=start,
                end_seconds=end,
                kind=normalized_kind,
                observed_at=moment,
                id=uuid4(),
            )
            self.store.add_interval(interval)
            replacement = replace(
                session,
                revision=session.revision + 1,
                last_sequence=sequence,
                last_position_seconds=end,
                last_heartbeat_at=moment,
            )
            self.store.compare_and_swap_session(
                session,
                replacement,
                expected_revision=session.revision,
            )
            _finish_command(
                self.store,
                command,
                result={"result_interval_id": interval.id},
                now=moment,
            )
            return interval

    record_heartbeat = record_event
    record_watch_interval = record_event

    def close_session(
        self,
        *,
        actor: ActorContext,
        tenant_id: UUID,
        enrollment_id: UUID,
        program_version_id: UUID,
        activity_id: UUID,
        session_id: UUID,
        session_token: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> PlaybackSessionSnapshot:
        access = self.activities._access(
            actor=actor,
            tenant_id=tenant_id,
            enrollment_id=enrollment_id,
            program_version_id=program_version_id,
            activity_id=activity_id,
        )
        _require_prerequisites(self.store, access)
        moment = _server_now(self.clock)
        payload = {"session_id": str(session_id), "expected_revision": expected_revision}
        with self.store.atomic():
            self.store.lock_projection_scope(access)
            session = self._owned_session(
                session_id=session_id,
                access=access,
                session_token=session_token,
                now=moment,
                allow_closed=True,
            )
            command, replayed = _claim_command(
                self.store,
                actor=actor,
                access=access,
                operation="playback_close",
                idempotency_key=idempotency_key,
                payload=payload,
                now=moment,
            )
            if replayed:
                return session
            if session.revision != _require_expected_revision(expected_revision):
                raise PersistenceConflictError("playback session revision is stale")
            if session.status is PlaybackSessionStatus.CLOSED:
                replacement = session
            else:
                replacement = replace(
                    session,
                    status=PlaybackSessionStatus.CLOSED,
                    closed_at=moment,
                    revision=session.revision + 1,
                )
                self.store.compare_and_swap_session(
                    session,
                    replacement,
                    expected_revision=expected_revision,
                )
            _finish_command(
                self.store,
                command,
                result={"result_session_id": replacement.id},
                now=moment,
            )
            return replacement

    def coverage_for_session(
        self,
        *,
        actor: ActorContext,
        tenant_id: UUID,
        enrollment_id: UUID,
        program_version_id: UUID,
        activity_id: UUID,
        session_id: UUID,
        session_token: str,
    ) -> VideoCoverage:
        access = self.activities._access(
            actor=actor,
            tenant_id=tenant_id,
            enrollment_id=enrollment_id,
            program_version_id=program_version_id,
            activity_id=activity_id,
        )
        session = self._owned_session(
            session_id=session_id,
            access=access,
            session_token=session_token,
            now=_server_now(self.clock),
            allow_closed=True,
        )
        pinned_policy = _pinned_video_policy(session)
        intervals = _validated_watch_intervals(
            session,
            self.store.intervals_for_session(session.id),
        )
        return calculate_video_coverage(intervals, session.duration_seconds, policy=pinned_policy)


def _load_evidence_replay(
    store: LearningRepository, command: CommandLedgerSnapshot
) -> tuple[EvidenceSnapshot, EvidenceSubmissionSnapshot]:
    if command.result_evidence_id is None or command.result_submission_id is None:
        raise PersistenceConflictError("the completed evidence command has no replayable result")
    evidence = store.get_evidence(command.result_evidence_id)
    submission = store.get_submission(command.result_submission_id)
    if evidence is None or submission is None or submission.evidence_id != evidence.id:
        raise PersistenceConflictError("the completed evidence command points to missing state")
    return evidence, submission


class EvidenceService:
    """Append evidence and human review corrections in one transaction."""

    def __init__(
        self,
        store: LearningRepository,
        *,
        policy_resolver: Callable[[LearningAccessContext], VideoEvidencePolicy],
        clock: Callable[[], datetime],
    ) -> None:
        self.store = store
        self.clock = clock
        self.activities = ActivityService(store, clock=clock)
        self.playback = PlaybackService(
            store,
            policy_resolver=policy_resolver,
            clock=clock,
        )

    def submit(
        self,
        *,
        actor: ActorContext,
        tenant_id: UUID,
        enrollment_id: UUID,
        program_version_id: UUID,
        activity_id: UUID,
        evidence_type: EvidenceType | str,
        idempotency_key: str,
        expected_revision: int,
        payload: Mapping[str, Any],
        playback_session_id: UUID | None = None,
        session_token: str | None = None,
    ) -> tuple[EvidenceSnapshot, EvidenceSubmissionSnapshot]:
        access = self.activities._access(
            actor=actor,
            tenant_id=tenant_id,
            enrollment_id=enrollment_id,
            program_version_id=program_version_id,
            activity_id=activity_id,
        )
        _require_prerequisites(self.store, access)
        normalized_type = _evidence_type(evidence_type)
        expected_type = {
            ActivityKind.VIDEO: EvidenceType.VIDEO_WATCH,
            ActivityKind.REFLECTION: EvidenceType.REFLECTION,
            ActivityKind.IMPLEMENTATION_CHALLENGE: EvidenceType.IMPLEMENTATION,
            ActivityKind.REVIEW: EvidenceType.REVIEW,
            ActivityKind.IMPROVE: EvidenceType.IMPROVEMENT,
        }[_activity_kind(access.activity.kind)]
        if normalized_type is not expected_type:
            raise InvalidEvidence("evidence type does not match the server-resolved activity kind")
        normalized_payload = _canonical_payload(payload, maximum_bytes=MAX_EVIDENCE_PAYLOAD_BYTES)
        moment = _server_now(self.clock)
        command_payload = {
            "activity_id": str(activity_id),
            "evidence_type": normalized_type.value,
            "expected_revision": expected_revision,
            "payload": normalized_payload,
            "playback_session_id": str(playback_session_id) if playback_session_id else None,
            "session_token_hash": _token_hash(session_token).hex() if session_token else None,
        }
        with self.store.atomic():
            self.store.lock_projection_scope(access)
            command, replayed = _claim_command(
                self.store,
                actor=actor,
                access=access,
                operation="evidence_submit",
                idempotency_key=idempotency_key,
                payload=command_payload,
                now=moment,
            )
            if replayed:
                return _load_evidence_replay(self.store, command)
            progress = self.store.get_progress(*access.scope)
            _require_current_activity(access, progress)
            expected_revision = _require_expected_revision(expected_revision)
            if progress is not None and progress.revision != expected_revision:
                raise PersistenceConflictError("activity progress revision is stale")
            if progress is not None and _activity_state(progress.state) is ActivityState.COMPLETED:
                raise CompletedActivityMutationError("completed activity cannot accept evidence")
            if progress is not None and _activity_state(progress.state) is ActivityState.LOCKED:
                raise ActivityStateError(
                    "locked activity must pass the checked start command before evidence"
                )
            if (
                progress is not None
                and _activity_state(progress.state) is ActivityState.AWAITING_REVIEW
            ):
                raise ActivityStateError(
                    "an activity awaiting review needs its current review resolved first"
                )
            if progress is None or _activity_state(progress.state) is ActivityState.AVAILABLE:
                progress = self.activities._ensure_started(
                    access,
                    expected_revision=expected_revision,
                    moment=moment,
                )
            evidence_payload: dict[str, Any]
            assigned_reviewer_id: UUID | None = None
            policy_version = HUMAN_REVIEW_POLICY_VERSION
            if normalized_type is EvidenceType.VIDEO_WATCH:
                if playback_session_id is None or session_token is None:
                    raise InvalidEvidence(
                        "video evidence requires the opaque playback session token"
                    )
                coverage = self.playback.coverage_for_session(
                    actor=actor,
                    tenant_id=tenant_id,
                    enrollment_id=enrollment_id,
                    program_version_id=program_version_id,
                    activity_id=activity_id,
                    session_id=playback_session_id,
                    session_token=session_token,
                )
                evidence_payload = {
                    "duration_seconds": coverage.duration_seconds,
                    "unique_coverage_seconds": coverage.unique_seconds,
                    "coverage_ratio": coverage.coverage_ratio,
                    "coverage_threshold": coverage.threshold,
                    "policy_version": coverage.policy_version,
                    "intervals": [
                        [interval.start_seconds, interval.end_seconds]
                        for interval in coverage.merged_intervals
                    ],
                }
                if normalized_payload:
                    evidence_payload["client_payload"] = normalized_payload
                policy_version = coverage.policy_version
            else:
                if not normalized_payload:
                    raise InvalidEvidence("subjective evidence payload must not be empty")
                assigned_reviewer_id = self.store.reviewer_for_activity(access)
                if assigned_reviewer_id is None or assigned_reviewer_id == actor.person_id:
                    raise ReviewerAuthorizationError(
                        "subjective evidence requires a server-resolved independent reviewer"
                    )
                evidence_payload = normalized_payload
            evidence = EvidenceSnapshot(
                tenant_id=access.tenant_id,
                person_id=access.person_id,
                enrollment_id=access.enrollment_id,
                program_version_id=access.program_version_id,
                program_id=access.program.id,
                program_scope=access.program.program_scope,
                program_owner_key=access.program.program_owner_key,
                module_id=access.activity.module_id,
                activity_id=access.activity.id,
                evidence_type=normalized_type,
                activity_version=access.activity.version,
                policy_version=policy_version,
                idempotency_key=_text(idempotency_key, "idempotency key", 128),
                payload=evidence_payload,
                playback_session_id=playback_session_id,
                captured_at=moment,
                id=uuid4(),
            )
            self.store.add_evidence(evidence)
            submission = EvidenceSubmissionSnapshot(
                evidence_id=evidence.id,
                tenant_id=access.tenant_id,
                person_id=access.person_id,
                enrollment_id=access.enrollment_id,
                program_version_id=access.program_version_id,
                program_id=access.program.id,
                program_scope=access.program.program_scope,
                program_owner_key=access.program.program_owner_key,
                module_id=access.activity.module_id,
                activity_id=access.activity.id,
                submitted_by_person_id=actor.person_id,
                idempotency_key=_text(idempotency_key, "idempotency key", 128),
                status=(
                    EvidenceSubmissionStatus.RECORDED
                    if normalized_type is EvidenceType.VIDEO_WATCH
                    else EvidenceSubmissionStatus.AWAITING_REVIEW
                ),
                assigned_reviewer_id=assigned_reviewer_id,
                submitted_at=moment,
                id=uuid4(),
            )
            self.store.add_submission(submission)
            if normalized_type is EvidenceType.VIDEO_WATCH:
                progress = self.activities._transition_internal(
                    access,
                    requested=ActivityState.COMPLETED,
                    expected_revision=progress.revision,
                    moment=moment,
                    completion_evidence_id=evidence.id,
                )
            else:
                progress = self.activities._transition_internal(
                    access,
                    requested=ActivityState.AWAITING_REVIEW,
                    expected_revision=progress.revision,
                    moment=moment,
                    completion_evidence_id=None,
                )
            del progress
            _materialize_projections(self.store, access, computed_at=moment)
            _finish_command(
                self.store,
                command,
                result={
                    "result_evidence_id": evidence.id,
                    "result_submission_id": submission.id,
                },
                now=moment,
            )
            return evidence, submission

    submit_evidence = submit

    def submit_video_evidence(
        self,
        *,
        actor: ActorContext,
        tenant_id: UUID,
        enrollment_id: UUID,
        program_version_id: UUID,
        activity_id: UUID,
        playback_session_id: UUID,
        session_token: str,
        idempotency_key: str,
        expected_revision: int,
        payload: Mapping[str, Any],
    ) -> tuple[EvidenceSnapshot, EvidenceSubmissionSnapshot]:
        return self.submit(
            actor=actor,
            tenant_id=tenant_id,
            enrollment_id=enrollment_id,
            program_version_id=program_version_id,
            activity_id=activity_id,
            evidence_type=EvidenceType.VIDEO_WATCH,
            idempotency_key=idempotency_key,
            expected_revision=expected_revision,
            payload=payload,
            playback_session_id=playback_session_id,
            session_token=session_token,
        )

    def review_submission(
        self,
        *,
        actor: ActorContext,
        tenant_id: UUID,
        submission_id: UUID,
        decision: ReviewDecision | str,
        reason: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> EvidenceCorrectionSnapshot:
        submission = self.store.get_submission(submission_id)
        if submission is None:
            raise EvidenceSubmissionNotFound("evidence submission does not exist")
        actor.require_tenant(tenant_id)
        if submission.tenant_id != tenant_id:
            raise AuthorizationDenied("the selected tenant does not own this submission")
        authorization = self.store.resolve_reviewer(actor=actor, submission=submission)
        if (
            authorization.actor != actor
            or not authorization.assigned
            or not authorization.membership_active
        ):
            raise ReviewerAuthorizationError(
                "the reviewer is not actively assigned to this submission"
            )
        if authorization.role not in REVIEWER_ROLES or not authorization.permission_granted:
            raise ReviewerAuthorizationError(
                "the reviewer lacks the server-resolved review permission"
            )
        if submission.status is EvidenceSubmissionStatus.RECORDED:
            raise HumanReviewRequiredError(
                "objective video evidence does not require human scoring"
            )
        access = self.store.resolve_scope(
            tenant_id=submission.tenant_id,
            person_id=submission.person_id,
            enrollment_id=submission.enrollment_id,
            program_version_id=submission.program_version_id,
            activity_id=submission.activity_id,
        )
        _validate_access(access)
        _require_prerequisites(self.store, access)
        if access.assigned_reviewer_id != actor.person_id:
            raise ReviewerNotAssignedError("reviewer is not the server-assigned reviewer")
        normalized_decision = _review_decision(decision)
        normalized_reason = _text(reason, "review reason", 1000)
        moment = _server_now(self.clock)
        payload = {
            "submission_id": str(submission_id),
            "decision": normalized_decision.value,
            "reason": normalized_reason,
            "expected_revision": expected_revision,
        }
        with self.store.atomic():
            self.store.lock_projection_scope(access)
            command, replayed = _claim_command(
                self.store,
                actor=actor,
                access=access,
                operation="evidence_review",
                idempotency_key=idempotency_key,
                payload=payload,
                now=moment,
            )
            if replayed:
                if command.result_correction_id is None:
                    raise PersistenceConflictError("the completed review command has no correction")
                correction = next(
                    (
                        item
                        for item in self.store.corrections_for_submission(submission.id)
                        if item.id == command.result_correction_id
                    ),
                    None,
                )
                if correction is None:
                    raise PersistenceConflictError(
                        "the completed review command points to missing state"
                    )
                return correction
            latest = self.store.corrections_for_submission(submission.id)
            expected_revision = _require_expected_revision(expected_revision)
            if len(latest) != expected_revision:
                raise CorrectionRevisionConflict("the submission review revision is stale")
            if latest and latest[-1].decision is ReviewDecision.NEEDS_REVISION:
                raise CorrectionRequiresNewEvidenceError(
                    "a needs_revision correction must be followed by new evidence"
                )
            progress = self.store.get_progress(*access.scope)
            if progress is None:
                raise ActivityStateError("reviewed activity has no progress row")
            _require_current_activity(access, progress)
            if _activity_state(progress.state) is ActivityState.COMPLETED:
                raise CompletedActivityMutationError(
                    "a completed activity cannot be reopened by review"
                )
            correction = EvidenceCorrectionSnapshot(
                submission_id=submission.id,
                evidence_id=submission.evidence_id,
                tenant_id=submission.tenant_id,
                person_id=submission.person_id,
                enrollment_id=submission.enrollment_id,
                program_version_id=submission.program_version_id,
                program_id=submission.program_id,
                program_scope=submission.program_scope,
                program_owner_key=submission.program_owner_key,
                module_id=submission.module_id,
                activity_id=submission.activity_id,
                reviewer_person_id=actor.person_id,
                decision=normalized_decision,
                reason=normalized_reason,
                idempotency_key=_text(idempotency_key, "idempotency key", 128),
                correction_sequence=expected_revision + 1,
                supersedes_correction_id=latest[-1].id if latest else None,
                created_at=moment,
                id=uuid4(),
            )
            self.store.append_correction(correction, expected_revision=expected_revision)
            if normalized_decision is ReviewDecision.APPROVED:
                self.activities._transition_internal(
                    access,
                    requested=ActivityState.COMPLETED,
                    expected_revision=progress.revision,
                    moment=moment,
                    completion_evidence_id=submission.evidence_id,
                )
            else:
                self.activities._transition_internal(
                    access,
                    requested=ActivityState.IN_PROGRESS,
                    expected_revision=progress.revision,
                    moment=moment,
                    completion_evidence_id=None,
                    allow_review_reset=True,
                )
            _materialize_projections(self.store, access, computed_at=moment)
            _finish_command(
                self.store,
                command,
                result={"result_correction_id": correction.id},
                now=moment,
            )
            return correction

    review = review_submission


class ProgressProjector:
    """Build deterministic module/course projections from a pinned version."""

    def __init__(self, projection_version: str = DEFAULT_PROGRESS_PROJECTION_VERSION) -> None:
        self.projection_version = _text(projection_version, "projection version", 128)
        self.prerequisites = PrerequisiteEvaluator()

    @staticmethod
    def _ordered_modules(program: ProgramDefinition) -> tuple[ModuleDefinition, ...]:
        return tuple(sorted(program.modules, key=lambda item: (item.order, str(item.id))))

    @staticmethod
    def _ordered_activities(module: ModuleDefinition) -> tuple[ActivityDefinition, ...]:
        return tuple(sorted(module.activities, key=lambda item: (item.order, str(item.id))))

    @classmethod
    def _dependency_order(cls, program: ProgramDefinition) -> tuple[ModuleDefinition, ...]:
        display_order = cls._ordered_modules(program)
        by_id = {module.id: module for module in display_order}
        remaining = set(by_id)
        evaluation_order: list[ModuleDefinition] = []
        while remaining:
            ready = tuple(
                module
                for module in display_order
                if module.id in remaining
                and all(
                    prerequisite_id not in remaining
                    for prerequisite_id in module.prerequisite_module_ids
                )
            )
            if not ready:
                evaluation_order.extend(
                    module for module in display_order if module.id in remaining
                )
                break
            evaluation_order.extend(ready)
            remaining.difference_update(module.id for module in ready)
        return tuple(evaluation_order)

    def project(
        self,
        program: ProgramDefinition,
        progress_by_activity: Mapping[UUID, ActivityProgressSnapshot],
    ) -> CourseProgressProjection:
        by_definition = {
            activity.id: activity for module in program.modules for activity in module.activities
        }
        completed_modules: dict[UUID, bool] = {}
        module_projections: dict[UUID, ModuleProgressProjection] = {}
        activity_states_by_module: dict[UUID, tuple[ActivityStateExplanation, ...]] = {}
        total_required = 0
        total_completed = 0
        for module in self._dependency_order(program):
            ordered = self._ordered_activities(module)
            missing_module_ids = tuple(
                module_id
                for module_id in module.prerequisite_module_ids
                if not completed_modules.get(module_id, False)
            )
            module_states: list[ActivityStateExplanation] = []
            module_required = 0
            module_completed = 0
            for activity in ordered:
                evaluation = self.prerequisites.evaluate(
                    activity,
                    progress_by_activity,
                    activities=by_definition,
                    completed_modules=completed_modules,
                    prerequisite_module_ids=module.prerequisite_module_ids,
                )
                progress = progress_by_activity.get(activity.id)
                version_matches = (
                    progress is not None
                    and progress.activity_version == activity.version
                    and progress.program_version_id == program.program_version_id
                    and progress.program_id == program.id
                    and progress.program_scope == program.program_scope
                    and progress.program_owner_key == program.program_owner_key
                    and progress.module_id == activity.module_id
                    and progress.activity_id == activity.id
                )
                if not evaluation.satisfied:
                    state = ActivityState.LOCKED
                    reason = evaluation.reason
                elif progress is None or not version_matches:
                    state = ActivityState.AVAILABLE
                    reason = "available" if progress is None else "content_version_changed"
                else:
                    state = _activity_state(progress.state)
                    reason = {
                        ActivityState.LOCKED: "prerequisite_not_completed",
                        ActivityState.AVAILABLE: "available",
                        ActivityState.IN_PROGRESS: "learner_started",
                        ActivityState.AWAITING_REVIEW: "awaiting_human_review",
                        ActivityState.COMPLETED: "completed",
                    }[state]
                explanation = ActivityStateExplanation(
                    activity_id=activity.id,
                    state=state,
                    required=activity.required and module.required,
                    reason=reason,
                    missing_activity_ids=evaluation.missing_activity_ids,
                    missing_module_ids=evaluation.missing_module_ids,
                )
                module_states.append(explanation)
                if activity.required and module.required:
                    module_required += 1
                    if state is ActivityState.COMPLETED and version_matches:
                        module_completed += 1
            module_complete = not missing_module_ids and (
                module_required > 0 and module_completed == module_required
            )
            completed_modules[module.id] = module_complete
            module_projection = ModuleProgressProjection(
                module_id=module.id,
                program_version=program.version,
                projection_version=self.projection_version,
                denominator=module_required,
                completed_count=module_completed,
                percentage=module_completed / module_required if module_required else 0.0,
                complete=module_complete,
                activity_states=tuple(module_states),
                missing_module_ids=missing_module_ids,
            )
            module_projections[module.id] = module_projection
            activity_states_by_module[module.id] = tuple(module_states)
            total_required += module_required
            total_completed += module_completed
        display_modules = self._ordered_modules(program)
        displayed_activity_states = tuple(
            state for module in display_modules for state in activity_states_by_module[module.id]
        )
        next_activity_id = next(
            (
                item.activity_id
                for item in displayed_activity_states
                # A lock or a pending human review is useful explanation, but
                # neither is an action the learner can take now.  Keep the
                # recommendation on the canonical progress projection and
                # fail closed when no required activity is currently eligible.
                if item.required
                and item.state in {ActivityState.AVAILABLE, ActivityState.IN_PROGRESS}
            ),
            None,
        )
        return CourseProgressProjection(
            program_id=program.id,
            program_version=program.version,
            projection_version=self.projection_version,
            denominator=total_required,
            completed_count=total_completed,
            percentage=total_completed / total_required if total_required else 0.0,
            can_complete=total_required > 0 and total_completed == total_required,
            next_activity_id=next_activity_id,
            modules=tuple(module_projections[module.id] for module in display_modules),
            activity_states=displayed_activity_states,
        )

    def project_authoritative(
        self,
        program: ProgramDefinition,
        progress_by_activity: Mapping[UUID, ActivityProgressSnapshot],
        evidence_by_activity: Mapping[UUID, EvidenceSnapshot],
    ) -> CourseProgressProjection:
        """Project only completed rows tied to real, same-scope evidence."""

        valid: dict[UUID, ActivityProgressSnapshot] = {}
        for activity_id, progress in progress_by_activity.items():
            if _activity_state(progress.state) is not ActivityState.COMPLETED:
                valid[activity_id] = progress
                continue
            evidence = evidence_by_activity.get(activity_id)
            if (
                evidence is not None
                and progress.completion_evidence_id == evidence.id
                and (
                    evidence.tenant_id,
                    evidence.enrollment_id,
                    evidence.person_id,
                    evidence.program_version_id,
                    evidence.program_id,
                    evidence.program_scope,
                    evidence.program_owner_key,
                    evidence.module_id,
                    evidence.activity_id,
                )
                == (
                    progress.tenant_id,
                    progress.enrollment_id,
                    progress.person_id,
                    progress.program_version_id,
                    progress.program_id,
                    progress.program_scope,
                    progress.program_owner_key,
                    progress.module_id,
                    progress.activity_id,
                )
                and evidence.activity_version
                == next(
                    (
                        activity.version
                        for module in program.modules
                        for activity in module.activities
                        if activity.id == activity_id
                    ),
                    "",
                )
            ):
                valid[activity_id] = progress
        return self.project(program, valid)

    def explain(
        self,
        program: ProgramDefinition,
        progress_by_activity: Mapping[UUID, ActivityProgressSnapshot],
    ) -> ProgressExplanation:
        return self.project(program, progress_by_activity).explanation


ProgressService = ProgressProjector
LearningProgressService = ProgressProjector


def project_progress(
    program: ProgramDefinition,
    progress_by_activity: Mapping[UUID, ActivityProgressSnapshot],
    *,
    projection_version: str = DEFAULT_PROGRESS_PROJECTION_VERSION,
) -> CourseProgressProjection:
    return ProgressProjector(projection_version).project(program, progress_by_activity)


def explain_progress(
    program: ProgramDefinition,
    progress_by_activity: Mapping[UUID, ActivityProgressSnapshot],
    *,
    projection_version: str = DEFAULT_PROGRESS_PROJECTION_VERSION,
) -> ProgressExplanation:
    return ProgressProjector(projection_version).explain(program, progress_by_activity)


class LearningUnitOfWork(Protocol):
    """Async production boundary containing all learning records and the ledger."""

    durable: bool

    async def __aenter__(self) -> Self: ...

    async def __aexit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None: ...

    async def run(self, operation: Callable[[LearningRepository], T]) -> T: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class LearningCommandBundle:
    """Services bound to one repository/UoW transaction."""

    def __init__(
        self,
        repository: LearningRepository,
        *,
        clock: Callable[[], datetime],
        policy_resolver: Callable[[LearningAccessContext], VideoEvidencePolicy],
    ) -> None:
        self.store = repository
        self.activities = ActivityService(repository, clock=clock)
        self.drafts = DraftService(repository, clock=clock)
        self.playback = PlaybackService(
            repository,
            policy_resolver=policy_resolver,
            clock=clock,
        )
        self.evidence = EvidenceService(
            repository,
            policy_resolver=policy_resolver,
            clock=clock,
        )
        self.progress = ProgressProjector()


class InMemoryLearningService(LearningCommandBundle):
    """Explicit test-only service composition; never a production default."""

    def __init__(
        self,
        store: InMemoryLearningStore,
        *,
        clock: Callable[[], datetime],
        policy_resolver: Callable[[LearningAccessContext], VideoEvidencePolicy],
    ) -> None:
        if not isinstance(store, InMemoryLearningStore):
            raise DurableRepositoryRequiredError("the in-memory learning service is test-only")
        super().__init__(store, clock=clock, policy_resolver=policy_resolver)


class LearningService:
    """Production composition executed wholly inside one async SQL transaction."""

    def __init__(
        self,
        uow_factory: Callable[[], LearningUnitOfWork],
        *,
        clock: Callable[[], datetime],
        policy_resolver: Callable[[LearningAccessContext], VideoEvidencePolicy],
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._policy_resolver = policy_resolver

    async def execute(self, operation: Callable[[LearningCommandBundle], T]) -> T:
        uow = self._uow_factory()
        if not uow.durable or not isinstance(uow, SqlAlchemyLearningUnitOfWork):
            raise DurableRepositoryRequiredError(
                "production learning requires SqlAlchemyLearningUnitOfWork"
            )
        async with uow:
            try:
                result = await uow.run(
                    lambda repository: operation(
                        LearningCommandBundle(
                            repository,
                            clock=self._clock,
                            policy_resolver=self._policy_resolver,
                        )
                    )
                )
                await uow.commit()
                return result
            except BaseException:
                await uow.rollback()
                raise


def _to_progress(row: ActivityProgress) -> ActivityProgressSnapshot:
    return ActivityProgressSnapshot(
        tenant_id=row.tenant_id,
        person_id=row.person_id,
        enrollment_id=row.enrollment_id,
        program_version_id=row.program_version_id,
        program_id=row.program_id,
        program_scope=row.program_scope,
        program_owner_key=row.program_owner_key,
        module_id=row.module_id,
        activity_id=row.activity_id,
        state=row.state,
        activity_version=row.activity_version,
        policy_version=row.policy_version,
        revision=row.revision,
        started_at=row.started_at,
        awaiting_review_at=row.awaiting_review_at,
        completed_at=row.completed_at,
        completion_evidence_id=row.completion_evidence_id,
        updated_at=row.updated_at,
        id=row.id,
    )


def _to_draft(row: ActivityDraft) -> DraftSnapshot:
    return DraftSnapshot(
        tenant_id=row.tenant_id,
        person_id=row.person_id,
        enrollment_id=row.enrollment_id,
        program_version_id=row.program_version_id,
        program_id=row.program_id,
        program_scope=row.program_scope,
        program_owner_key=row.program_owner_key,
        module_id=row.module_id,
        activity_id=row.activity_id,
        payload=row.payload,
        revision=row.revision,
        status=row.status,
        id=row.id,
        last_idempotency_key=row.last_idempotency_key,
        last_request_fingerprint=row.last_request_fingerprint,
        saved_at=row.saved_at,
    )


def _to_session(row: PlaybackSession) -> PlaybackSessionSnapshot:
    return PlaybackSessionSnapshot(
        tenant_id=row.tenant_id,
        person_id=row.person_id,
        enrollment_id=row.enrollment_id,
        program_version_id=row.program_version_id,
        program_id=row.program_id,
        program_scope=row.program_scope,
        program_owner_key=row.program_owner_key,
        module_id=row.module_id,
        activity_id=row.activity_id,
        content_version=row.content_version,
        policy_version=row.policy_version,
        session_token_hash=bytes(row.session_token_hash),
        duration_seconds=row.duration_seconds,
        coverage_threshold=row.coverage_threshold,
        minimum_watch_interval_seconds=row.minimum_watch_interval_seconds,
        max_event_seconds=row.max_event_seconds,
        max_heartbeat_gap_seconds=row.max_heartbeat_gap_seconds,
        minimum_heartbeats_for_completion=row.minimum_heartbeats_for_completion,
        clock_grace_seconds=row.clock_grace_seconds,
        max_rewind_seconds=row.max_rewind_seconds,
        started_at=row.started_at,
        expires_at=row.expires_at,
        status=row.status,
        revision=row.revision,
        last_sequence=row.last_sequence,
        last_position_seconds=row.last_position_seconds,
        last_heartbeat_at=row.last_heartbeat_at,
        closed_at=row.closed_at,
        id=row.id,
    )


def _to_interval(row: VideoWatchInterval) -> WatchIntervalSnapshot:
    return WatchIntervalSnapshot(
        playback_session_id=row.playback_session_id,
        tenant_id=row.tenant_id,
        person_id=row.person_id,
        enrollment_id=row.enrollment_id,
        program_version_id=row.program_version_id,
        program_id=row.program_id,
        program_scope=row.program_scope,
        program_owner_key=row.program_owner_key,
        module_id=row.module_id,
        activity_id=row.activity_id,
        event_id=row.event_id,
        sequence=row.sequence,
        start_seconds=row.start_seconds,
        end_seconds=row.end_seconds,
        kind=row.kind,
        observed_at=row.observed_at,
        id=row.id,
    )


def _to_evidence(row: LearningEvidence) -> EvidenceSnapshot:
    return EvidenceSnapshot(
        tenant_id=row.tenant_id,
        person_id=row.person_id,
        enrollment_id=row.enrollment_id,
        program_version_id=row.program_version_id,
        program_id=row.program_id,
        program_scope=row.program_scope,
        program_owner_key=row.program_owner_key,
        module_id=row.module_id,
        activity_id=row.activity_id,
        evidence_type=row.evidence_type,
        activity_version=row.activity_version,
        policy_version=row.policy_version,
        idempotency_key=row.idempotency_key,
        payload=row.payload,
        playback_session_id=row.playback_session_id,
        captured_at=row.captured_at,
        id=row.id,
    )


def _to_submission(row: EvidenceSubmission) -> EvidenceSubmissionSnapshot:
    return EvidenceSubmissionSnapshot(
        evidence_id=row.evidence_id,
        tenant_id=row.tenant_id,
        person_id=row.person_id,
        enrollment_id=row.enrollment_id,
        program_version_id=row.program_version_id,
        program_id=row.program_id,
        program_scope=row.program_scope,
        program_owner_key=row.program_owner_key,
        module_id=row.module_id,
        activity_id=row.activity_id,
        submitted_by_person_id=row.submitted_by_person_id,
        idempotency_key=row.idempotency_key,
        status=row.status,
        assigned_reviewer_id=row.assigned_reviewer_id,
        submitted_at=row.submitted_at,
        id=row.id,
    )


def _to_correction(row: EvidenceCorrection) -> EvidenceCorrectionSnapshot:
    return EvidenceCorrectionSnapshot(
        submission_id=row.submission_id,
        evidence_id=row.evidence_id,
        tenant_id=row.tenant_id,
        person_id=row.person_id,
        enrollment_id=row.enrollment_id,
        program_version_id=row.program_version_id,
        program_id=row.program_id,
        program_scope=row.program_scope,
        program_owner_key=row.program_owner_key,
        module_id=row.module_id,
        activity_id=row.activity_id,
        reviewer_person_id=row.reviewer_person_id,
        decision=row.decision,
        reason=row.reason,
        idempotency_key=row.idempotency_key,
        correction_sequence=row.correction_sequence,
        supersedes_correction_id=row.supersedes_correction_id,
        created_at=row.created_at,
        id=row.id,
    )


def _to_command(row: LearningCommandIdempotency) -> CommandLedgerSnapshot:
    return CommandLedgerSnapshot(
        id=row.id,
        tenant_id=row.tenant_id,
        actor_person_id=row.actor_person_id,
        person_id=row.person_id,
        enrollment_id=row.enrollment_id,
        program_version_id=row.program_version_id,
        program_id=row.program_id,
        program_scope=row.program_scope,
        program_owner_key=row.program_owner_key,
        module_id=row.module_id,
        activity_id=row.activity_id,
        operation=row.operation,
        idempotency_key=row.idempotency_key,
        request_digest=row.request_digest,
        status=row.status,
        result_progress_id=row.result_progress_id,
        result_draft_id=row.result_draft_id,
        result_session_id=row.result_session_id,
        result_interval_id=row.result_interval_id,
        result_evidence_id=row.result_evidence_id,
        result_submission_id=row.result_submission_id,
        result_correction_id=row.result_correction_id,
        created_at=row.created_at,
        completed_at=row.completed_at,
    )


class SqlAlchemyLearningRepository:
    """Synchronous adapter executed inside ``AsyncSession.run_sync`` in production."""

    durable = True

    def __init__(
        self,
        session: Session,
        *,
        activity_resolver: Callable[[object, object], ActivityDefinition],
        reviewer_resolver: Callable[[LearningAccessContext], UUID | None],
        activity_media_resolver: Callable[[Session, UUID, object, object], object | None]
        | None = None,
    ) -> None:
        self._session = session
        self._activity_resolver = activity_resolver
        self._reviewer_resolver = reviewer_resolver
        self._activity_media_resolver = activity_media_resolver

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """The owning UoW supplies the transaction; this keeps the port uniform."""

        yield

    def _resolved_activity(
        self,
        catalog_activity: Any,
        catalog_version: Any,
        *,
        tenant_id: UUID | None = None,
    ) -> ActivityDefinition:
        resolved = self._activity_resolver(catalog_activity, catalog_version)
        if resolved.id != catalog_activity.id:
            raise EvidenceVersionMismatch("the activity resolver returned another activity")
        resolved = replace(
            resolved,
            id=catalog_activity.id,
            kind=catalog_activity.kind,
            module_id=catalog_activity.module_id,
            program_version_id=catalog_version.id,
            program_id=catalog_activity.program_id,
            program_scope=catalog_activity.scope,
            program_owner_key=catalog_activity.owner_key,
            title=catalog_activity.title,
            order=catalog_activity.position,
            required=catalog_activity.is_required,
            tenant_id=catalog_activity.tenant_id,
            version=_text(resolved.version, "activity version", 128),
        )
        if self._activity_media_resolver is None or tenant_id is None:
            return resolved
        media = self._activity_media_resolver(
            self._session,
            tenant_id,
            catalog_activity,
            catalog_version,
        )
        if media is None:
            return resolved
        binding_id = getattr(media, "binding_id", None)
        asset_id = getattr(media, "asset_id", None)
        version_id = getattr(media, "version_id", None)
        if not all(isinstance(value, UUID) for value in (binding_id, asset_id, version_id)):
            raise EvidenceVersionMismatch("the activity media resolver returned invalid identities")
        duration = getattr(media, "duration_seconds", None)
        activity_version = getattr(media, "activity_version", resolved.version)
        if not isinstance(activity_version, str):
            raise EvidenceVersionMismatch("the activity media resolver returned an invalid version")
        return replace(
            resolved,
            media_binding_id=binding_id,
            media_asset_id=asset_id,
            media_version_id=version_id,
            video_duration_seconds=duration,
            version=_text(activity_version, "activity version", 128),
        )

    def _load_program_definition(
        self,
        catalog_version: Any,
        *,
        tenant_id: UUID | None = None,
    ) -> ProgramDefinition:
        from ac_platform.catalog.models import Activity as CatalogActivity
        from ac_platform.catalog.models import Module as CatalogModule
        from ac_platform.catalog.models import ModulePrerequisite

        catalog_filter = (
            CatalogModule.program_version_id == catalog_version.id,
            CatalogModule.program_id == catalog_version.program_id,
            CatalogModule.scope == catalog_version.scope,
            CatalogModule.owner_key == catalog_version.owner_key,
        )
        module_rows = tuple(
            self._session.scalars(
                select(CatalogModule).where(*catalog_filter).order_by(CatalogModule.position)
            )
        )
        activity_rows = tuple(
            self._session.scalars(
                select(CatalogActivity)
                .where(
                    CatalogActivity.program_version_id == catalog_version.id,
                    CatalogActivity.program_id == catalog_version.program_id,
                    CatalogActivity.scope == catalog_version.scope,
                    CatalogActivity.owner_key == catalog_version.owner_key,
                )
                .order_by(CatalogActivity.module_id, CatalogActivity.position)
            )
        )
        prerequisite_rows = tuple(
            self._session.scalars(
                select(ModulePrerequisite)
                .where(
                    ModulePrerequisite.program_version_id == catalog_version.id,
                    ModulePrerequisite.program_id == catalog_version.program_id,
                    ModulePrerequisite.scope == catalog_version.scope,
                    ModulePrerequisite.owner_key == catalog_version.owner_key,
                )
                .order_by(
                    ModulePrerequisite.module_id,
                    ModulePrerequisite.prerequisite_module_id,
                )
            )
        )
        activities_by_module: dict[UUID, list[ActivityDefinition]] = {
            module.id: [] for module in module_rows
        }
        for catalog_activity in activity_rows:
            try:
                activities_by_module[catalog_activity.module_id].append(
                    self._resolved_activity(
                        catalog_activity,
                        catalog_version,
                        tenant_id=tenant_id,
                    )
                )
            except KeyError as exc:
                raise EvidenceVersionMismatch(
                    "catalog activity references an unloaded module"
                ) from exc
        prerequisites_by_module: dict[UUID, list[UUID]] = {module.id: [] for module in module_rows}
        for edge in prerequisite_rows:
            try:
                prerequisites_by_module[edge.module_id].append(edge.prerequisite_module_id)
            except KeyError as exc:
                raise EvidenceVersionMismatch(
                    "module prerequisite references an unloaded module"
                ) from exc
        modules = tuple(
            ModuleDefinition(
                id=module.id,
                program_version_id=catalog_version.id,
                program_id=catalog_version.program_id,
                program_scope=catalog_version.scope,
                program_owner_key=catalog_version.owner_key,
                activities=tuple(activities_by_module[module.id]),
                title=module.title,
                order=module.position,
                prerequisite_module_ids=tuple(prerequisites_by_module[module.id]),
            )
            for module in module_rows
        )
        return ProgramDefinition(
            id=catalog_version.program_id,
            program_version_id=catalog_version.id,
            program_scope=catalog_version.scope,
            program_owner_key=catalog_version.owner_key,
            version=f"program-version:{catalog_version.id}",
            modules=modules,
        )

    def _catalog_access(
        self,
        *,
        actor: ActorContext,
        tenant_id: UUID,
        person_id: UUID,
        enrollment_id: UUID,
        program_version_id: UUID,
        activity_id: UUID,
    ) -> LearningAccessContext:
        from ac_platform.catalog.models import Activity as CatalogActivity
        from ac_platform.catalog.models import Module as CatalogModule
        from ac_platform.catalog.models import Program as CatalogProgram
        from ac_platform.catalog.models import ProgramVersion as CatalogProgramVersion
        from ac_platform.enrollment.models import Enrollment as EnrollmentModel
        from ac_platform.enrollment.models import Entitlement as EntitlementModel
        from ac_platform.tenancy.models import Membership as MembershipModel
        from ac_platform.tenancy.models import Tenant as TenantModel

        actor.require_tenant(tenant_id)
        row = self._session.execute(
            select(
                MembershipModel,
                TenantModel,
                EnrollmentModel,
                EntitlementModel,
                CatalogActivity,
                CatalogModule,
                CatalogProgramVersion,
                CatalogProgram,
            )
            .join(TenantModel, TenantModel.id == MembershipModel.tenant_id)
            .join(
                EnrollmentModel,
                (EnrollmentModel.tenant_id == MembershipModel.tenant_id)
                & (EnrollmentModel.person_id == MembershipModel.person_id),
            )
            .join(
                EntitlementModel,
                (EntitlementModel.tenant_id == EnrollmentModel.tenant_id)
                & (EntitlementModel.enrollment_id == EnrollmentModel.id)
                & (EntitlementModel.person_id == EnrollmentModel.person_id)
                & (EntitlementModel.program_version_id == EnrollmentModel.program_version_id)
                & (EntitlementModel.program_id == EnrollmentModel.program_id)
                & (EntitlementModel.program_scope == EnrollmentModel.program_scope)
                & (EntitlementModel.program_owner_key == EnrollmentModel.program_owner_key),
            )
            .join(
                CatalogProgramVersion,
                (CatalogProgramVersion.id == EnrollmentModel.program_version_id)
                & (CatalogProgramVersion.program_id == EnrollmentModel.program_id)
                & (CatalogProgramVersion.scope == EnrollmentModel.program_scope)
                & (CatalogProgramVersion.owner_key == EnrollmentModel.program_owner_key),
            )
            .join(
                CatalogProgram,
                (CatalogProgram.id == CatalogProgramVersion.program_id)
                & (CatalogProgram.scope == CatalogProgramVersion.scope)
                & (CatalogProgram.owner_key == CatalogProgramVersion.owner_key),
            )
            .join(
                CatalogActivity,
                (CatalogActivity.id == activity_id)
                & (CatalogActivity.program_version_id == CatalogProgramVersion.id)
                & (CatalogActivity.program_id == CatalogProgramVersion.program_id)
                & (CatalogActivity.scope == CatalogProgramVersion.scope)
                & (CatalogActivity.owner_key == CatalogProgramVersion.owner_key),
            )
            .join(
                CatalogModule,
                (CatalogModule.id == CatalogActivity.module_id)
                & (CatalogModule.program_version_id == CatalogActivity.program_version_id)
                & (CatalogModule.program_id == CatalogActivity.program_id)
                & (CatalogModule.scope == CatalogActivity.scope)
                & (CatalogModule.owner_key == CatalogActivity.owner_key),
            )
            .where(
                MembershipModel.tenant_id == tenant_id,
                MembershipModel.person_id == person_id,
                MembershipModel.role == LEARNER_ROLE,
                MembershipModel.status == "active",
                TenantModel.status == "active",
                EnrollmentModel.id == enrollment_id,
                EnrollmentModel.program_version_id == program_version_id,
                EnrollmentModel.status == "active",
                EntitlementModel.enrollment_id == enrollment_id,
                EntitlementModel.person_id == person_id,
                EntitlementModel.program_version_id == program_version_id,
                EntitlementModel.status == "active",
                CatalogActivity.program_version_id == program_version_id,
                (CatalogActivity.tenant_id.is_(None) | (CatalogActivity.tenant_id == tenant_id)),
                CatalogProgramVersion.status.in_(("published", "superseded")),
            )
        ).one_or_none()
        if row is None:
            raise AccessContextRequiredError(
                "active membership, enrollment, entitlement, and catalog access are required"
            )
        _, _, enrollment, entitlement, catalog_activity, _, catalog_version, _ = row
        program = self._load_program_definition(catalog_version, tenant_id=tenant_id)
        activity = next(
            (
                definition
                for module in program.modules
                for definition in module.activities
                if definition.id == catalog_activity.id
            ),
            None,
        )
        if activity is None:
            raise EvidenceVersionMismatch("requested activity is absent from the complete program")
        access = LearningAccessContext(
            actor=actor,
            tenant_id=tenant_id,
            person_id=person_id,
            enrollment_id=enrollment.id,
            program_version_id=catalog_version.id,
            activity=activity,
            program=program,
            membership=MembershipResolution(
                tenant_id=tenant_id,
                person_id=person_id,
                role=LEARNER_ROLE,
                active=True,
                tenant_active=True,
            ),
            enrollment_active=enrollment.status == "active",
            entitlement_active=entitlement.status == "active",
            catalog_version_active=catalog_version.status in {"published", "superseded"},
            catalog_version_immutable=catalog_version.status in {"published", "superseded"},
            assigned_reviewer_id=None,
        )
        return replace(access, assigned_reviewer_id=self._reviewer_resolver(access))

    def resolve_access(
        self,
        *,
        actor: ActorContext,
        tenant_id: UUID,
        enrollment_id: UUID,
        program_version_id: UUID,
        activity_id: UUID,
    ) -> LearningAccessContext:
        actor.require_tenant(tenant_id)
        return self._catalog_access(
            actor=actor,
            tenant_id=tenant_id,
            person_id=actor.person_id,
            enrollment_id=enrollment_id,
            program_version_id=program_version_id,
            activity_id=activity_id,
        )

    def resolve_scope(
        self,
        *,
        tenant_id: UUID,
        person_id: UUID,
        enrollment_id: UUID,
        program_version_id: UUID,
        activity_id: UUID,
    ) -> LearningAccessContext:
        return self._catalog_access(
            actor=ActorContext(person_id=person_id, session_id=UUID(int=0), tenant_id=tenant_id),
            tenant_id=tenant_id,
            person_id=person_id,
            enrollment_id=enrollment_id,
            program_version_id=program_version_id,
            activity_id=activity_id,
        )

    def resolve_reviewer(
        self, *, actor: ActorContext, submission: EvidenceSubmissionSnapshot
    ) -> ReviewerAuthorization:
        from ac_platform.tenancy.models import Membership as MembershipModel
        from ac_platform.tenancy.models import Tenant as TenantModel

        actor.require_tenant(submission.tenant_id)
        row = self._session.execute(
            select(MembershipModel, TenantModel)
            .join(TenantModel, TenantModel.id == MembershipModel.tenant_id)
            .where(
                MembershipModel.tenant_id == submission.tenant_id,
                MembershipModel.person_id == actor.person_id,
            )
        ).one_or_none()
        if row is None:
            raise ReviewerAuthorizationError("reviewer membership was not found")
        membership, tenant = row
        return ReviewerAuthorization(
            actor=actor,
            tenant_id=submission.tenant_id,
            submission_id=submission.id,
            assigned=submission.assigned_reviewer_id == actor.person_id,
            membership_active=membership.status == "active" and tenant.status == "active",
            role=membership.role,
            permission_granted=LEARNING_REVIEW_PERMISSION in actor.permissions,
        )

    def reviewer_for_activity(self, access: LearningAccessContext) -> UUID | None:
        return access.assigned_reviewer_id

    def get_progress(self, *scope: UUID) -> ActivityProgressSnapshot | None:
        tenant_id, enrollment_id, person_id, version_id, activity_id = scope
        row = self._session.scalar(
            select(ActivityProgress).where(
                ActivityProgress.tenant_id == tenant_id,
                ActivityProgress.enrollment_id == enrollment_id,
                ActivityProgress.person_id == person_id,
                ActivityProgress.program_version_id == version_id,
                ActivityProgress.activity_id == activity_id,
            )
        )
        return _to_progress(row) if row is not None else None

    def list_progress(
        self, *, tenant_id: UUID, person_id: UUID, enrollment_id: UUID, program_version_id: UUID
    ) -> tuple[ActivityProgressSnapshot, ...]:
        rows = self._session.scalars(
            select(ActivityProgress)
            .where(
                ActivityProgress.tenant_id == tenant_id,
                ActivityProgress.person_id == person_id,
                ActivityProgress.enrollment_id == enrollment_id,
                ActivityProgress.program_version_id == program_version_id,
            )
            .order_by(ActivityProgress.activity_id)
        )
        return tuple(_to_progress(row) for row in rows)

    def compare_and_swap_progress(
        self,
        current: ActivityProgressSnapshot | None,
        replacement: ActivityProgressSnapshot,
        *,
        expected_revision: int,
    ) -> ActivityProgressSnapshot:
        if current is None:
            if expected_revision != 0:
                raise DraftRevisionConflict(expected_revision=expected_revision, actual_revision=0)
            try:
                with self._session.begin_nested():
                    self._session.add(
                        ActivityProgress(
                            id=replacement.id,
                            tenant_id=replacement.tenant_id,
                            person_id=replacement.person_id,
                            enrollment_id=replacement.enrollment_id,
                            program_version_id=replacement.program_version_id,
                            program_id=replacement.program_id,
                            program_scope=replacement.program_scope,
                            program_owner_key=replacement.program_owner_key,
                            module_id=replacement.module_id,
                            activity_id=replacement.activity_id,
                            state=_activity_state(replacement.state).value,
                            activity_version=replacement.activity_version,
                            policy_version=replacement.policy_version,
                            revision=replacement.revision,
                            started_at=replacement.started_at,
                            awaiting_review_at=replacement.awaiting_review_at,
                            completed_at=replacement.completed_at,
                            completion_evidence_id=replacement.completion_evidence_id,
                            updated_at=replacement.updated_at,
                        )
                    )
                    self._session.flush()
            except IntegrityError as exc:
                canonical = self.get_progress(
                    replacement.tenant_id,
                    replacement.enrollment_id,
                    replacement.person_id,
                    replacement.program_version_id,
                    replacement.activity_id,
                )
                if canonical is not None and canonical == replacement:
                    return canonical
                raise PersistenceConflictError(
                    "activity progress first-write lost a uniqueness race"
                ) from exc
            return replacement
        result = cast(
            Any,
            self._session.execute(
                update(ActivityProgress)
                .where(
                    ActivityProgress.id == current.id,
                    ActivityProgress.revision == expected_revision,
                    ActivityProgress.tenant_id == replacement.tenant_id,
                    ActivityProgress.enrollment_id == replacement.enrollment_id,
                    ActivityProgress.person_id == replacement.person_id,
                    ActivityProgress.program_version_id == replacement.program_version_id,
                    ActivityProgress.program_id == replacement.program_id,
                    ActivityProgress.program_scope == replacement.program_scope,
                    ActivityProgress.program_owner_key == replacement.program_owner_key,
                    ActivityProgress.module_id == replacement.module_id,
                    ActivityProgress.activity_id == replacement.activity_id,
                )
                .values(
                    state=_activity_state(replacement.state).value,
                    activity_version=replacement.activity_version,
                    policy_version=replacement.policy_version,
                    revision=replacement.revision,
                    started_at=replacement.started_at,
                    awaiting_review_at=replacement.awaiting_review_at,
                    completed_at=replacement.completed_at,
                    completion_evidence_id=replacement.completion_evidence_id,
                    updated_at=replacement.updated_at,
                )
            ),
        )
        if result.rowcount != 1:
            raise PersistenceConflictError("activity progress CAS update lost a race")
        return replacement

    def get_draft(self, *scope: UUID) -> DraftSnapshot | None:
        tenant_id, enrollment_id, person_id, version_id, activity_id = scope
        row = self._session.scalar(
            select(ActivityDraft).where(
                ActivityDraft.tenant_id == tenant_id,
                ActivityDraft.enrollment_id == enrollment_id,
                ActivityDraft.person_id == person_id,
                ActivityDraft.program_version_id == version_id,
                ActivityDraft.activity_id == activity_id,
            )
        )
        return _to_draft(row) if row is not None else None

    def compare_and_swap_draft(
        self,
        current: DraftSnapshot | None,
        replacement: DraftSnapshot,
        *,
        expected_revision: int,
    ) -> DraftSnapshot:
        if current is None:
            if expected_revision != 0:
                raise DraftRevisionConflict(expected_revision=expected_revision, actual_revision=0)
            try:
                with self._session.begin_nested():
                    self._session.add(
                        ActivityDraft(
                            id=replacement.id,
                            tenant_id=replacement.tenant_id,
                            person_id=replacement.person_id,
                            enrollment_id=replacement.enrollment_id,
                            program_version_id=replacement.program_version_id,
                            program_id=replacement.program_id,
                            program_scope=replacement.program_scope,
                            program_owner_key=replacement.program_owner_key,
                            module_id=replacement.module_id,
                            activity_id=replacement.activity_id,
                            revision=replacement.revision,
                            payload=dict(replacement.payload),
                            status=_draft_status(replacement.status).value,
                            last_idempotency_key=replacement.last_idempotency_key,
                            last_request_fingerprint=replacement.last_request_fingerprint,
                            saved_at=replacement.saved_at,
                            created_at=replacement.saved_at,
                            updated_at=replacement.saved_at,
                        )
                    )
                    self._session.flush()
            except IntegrityError as exc:
                canonical = self.get_draft(
                    replacement.tenant_id,
                    replacement.enrollment_id,
                    replacement.person_id,
                    replacement.program_version_id,
                    replacement.activity_id,
                )
                if canonical is not None and canonical == replacement:
                    return canonical
                raise DraftRevisionConflict(
                    expected_revision=expected_revision,
                    actual_revision=canonical.revision if canonical is not None else None,
                ) from exc
            return replacement
        result = cast(
            Any,
            self._session.execute(
                update(ActivityDraft)
                .where(
                    ActivityDraft.id == current.id,
                    ActivityDraft.revision == expected_revision,
                    ActivityDraft.tenant_id == replacement.tenant_id,
                    ActivityDraft.enrollment_id == replacement.enrollment_id,
                    ActivityDraft.person_id == replacement.person_id,
                    ActivityDraft.program_version_id == replacement.program_version_id,
                    ActivityDraft.program_id == replacement.program_id,
                    ActivityDraft.program_scope == replacement.program_scope,
                    ActivityDraft.program_owner_key == replacement.program_owner_key,
                    ActivityDraft.module_id == replacement.module_id,
                    ActivityDraft.activity_id == replacement.activity_id,
                )
                .values(
                    revision=replacement.revision,
                    payload=dict(replacement.payload),
                    status=_draft_status(replacement.status).value,
                    last_idempotency_key=replacement.last_idempotency_key,
                    last_request_fingerprint=replacement.last_request_fingerprint,
                    saved_at=replacement.saved_at,
                    updated_at=replacement.saved_at,
                )
            ),
        )
        if result.rowcount != 1:
            raise DraftRevisionConflict(expected_revision=expected_revision)
        return replacement

    def get_playback_session(self, session_id: UUID) -> PlaybackSessionSnapshot | None:
        row = self._session.scalar(
            select(PlaybackSession).where(PlaybackSession.id == session_id).with_for_update()
        )
        return _to_session(row) if row is not None else None

    def add_playback_session(self, item: PlaybackSessionSnapshot) -> None:
        try:
            with self._session.begin_nested():
                self._session.add(
                    PlaybackSession(
                        id=item.id,
                        tenant_id=item.tenant_id,
                        person_id=item.person_id,
                        enrollment_id=item.enrollment_id,
                        program_version_id=item.program_version_id,
                        program_id=item.program_id,
                        program_scope=item.program_scope,
                        program_owner_key=item.program_owner_key,
                        module_id=item.module_id,
                        activity_id=item.activity_id,
                        content_version=item.content_version,
                        policy_version=item.policy_version,
                        session_token_hash=item.session_token_hash,
                        duration_seconds=item.duration_seconds,
                        coverage_threshold=item.coverage_threshold,
                        minimum_watch_interval_seconds=item.minimum_watch_interval_seconds,
                        max_event_seconds=item.max_event_seconds,
                        max_heartbeat_gap_seconds=item.max_heartbeat_gap_seconds,
                        minimum_heartbeats_for_completion=item.minimum_heartbeats_for_completion,
                        clock_grace_seconds=item.clock_grace_seconds,
                        max_rewind_seconds=item.max_rewind_seconds,
                        status=_playback_status(item.status).value,
                        revision=item.revision,
                        last_sequence=item.last_sequence,
                        last_position_seconds=item.last_position_seconds,
                        started_at=item.started_at,
                        expires_at=item.expires_at,
                        last_heartbeat_at=item.last_heartbeat_at,
                        closed_at=item.closed_at,
                    )
                )
                self._session.flush()
        except IntegrityError as exc:
            raise UniqueConstraintViolation("playback session uniqueness was violated") from exc

    def compare_and_swap_session(
        self,
        current: PlaybackSessionSnapshot,
        replacement: PlaybackSessionSnapshot,
        *,
        expected_revision: int,
    ) -> PlaybackSessionSnapshot:
        result = cast(
            Any,
            self._session.execute(
                update(PlaybackSession)
                .where(
                    PlaybackSession.id == current.id,
                    PlaybackSession.revision == expected_revision,
                    PlaybackSession.tenant_id == replacement.tenant_id,
                    PlaybackSession.enrollment_id == replacement.enrollment_id,
                    PlaybackSession.person_id == replacement.person_id,
                    PlaybackSession.program_version_id == replacement.program_version_id,
                    PlaybackSession.program_id == replacement.program_id,
                    PlaybackSession.program_scope == replacement.program_scope,
                    PlaybackSession.program_owner_key == replacement.program_owner_key,
                    PlaybackSession.module_id == replacement.module_id,
                    PlaybackSession.activity_id == replacement.activity_id,
                )
                .values(
                    status=_playback_status(replacement.status).value,
                    revision=replacement.revision,
                    last_sequence=replacement.last_sequence,
                    last_position_seconds=replacement.last_position_seconds,
                    last_heartbeat_at=replacement.last_heartbeat_at,
                    closed_at=replacement.closed_at,
                )
            ),
        )
        if result.rowcount != 1:
            raise PersistenceConflictError("playback session CAS update lost a race")
        return replacement

    def get_interval_by_event(
        self, session_id: UUID, event_id: str
    ) -> WatchIntervalSnapshot | None:
        row = self._session.scalar(
            select(VideoWatchInterval).where(
                VideoWatchInterval.playback_session_id == session_id,
                VideoWatchInterval.event_id == event_id,
            )
        )
        return _to_interval(row) if row is not None else None

    def get_interval_by_sequence(
        self, session_id: UUID, sequence: int
    ) -> WatchIntervalSnapshot | None:
        row = self._session.scalar(
            select(VideoWatchInterval).where(
                VideoWatchInterval.playback_session_id == session_id,
                VideoWatchInterval.sequence == sequence,
            )
        )
        return _to_interval(row) if row is not None else None

    def add_interval(self, item: WatchIntervalSnapshot) -> None:
        try:
            with self._session.begin_nested():
                self._session.add(
                    VideoWatchInterval(
                        id=item.id,
                        playback_session_id=item.playback_session_id,
                        tenant_id=item.tenant_id,
                        person_id=item.person_id,
                        enrollment_id=item.enrollment_id,
                        program_version_id=item.program_version_id,
                        program_id=item.program_id,
                        program_scope=item.program_scope,
                        program_owner_key=item.program_owner_key,
                        module_id=item.module_id,
                        activity_id=item.activity_id,
                        event_id=item.event_id,
                        sequence=item.sequence,
                        kind=_watch_kind(item.kind).value,
                        start_seconds=item.start_seconds,
                        end_seconds=item.end_seconds,
                        observed_at=item.observed_at,
                    )
                )
                self._session.flush()
        except IntegrityError as exc:
            raise ReplayResistanceError("playback event uniqueness was violated") from exc

    def intervals_for_session(self, session_id: UUID) -> tuple[WatchIntervalSnapshot, ...]:
        rows = self._session.scalars(
            select(VideoWatchInterval)
            .where(VideoWatchInterval.playback_session_id == session_id)
            .order_by(VideoWatchInterval.sequence)
        )
        return tuple(_to_interval(row) for row in rows)

    def find_evidence_by_request(self, *scope: UUID | str) -> EvidenceSnapshot | None:
        tenant_id, enrollment_id, person_id, version_id, activity_id, key = scope
        row = self._session.scalar(
            select(LearningEvidence).where(
                LearningEvidence.tenant_id == cast(UUID, tenant_id),
                LearningEvidence.enrollment_id == cast(UUID, enrollment_id),
                LearningEvidence.person_id == cast(UUID, person_id),
                LearningEvidence.program_version_id == cast(UUID, version_id),
                LearningEvidence.activity_id == cast(UUID, activity_id),
                LearningEvidence.idempotency_key == cast(str, key),
            )
        )
        return _to_evidence(row) if row is not None else None

    def get_evidence(self, evidence_id: UUID) -> EvidenceSnapshot | None:
        row = self._session.scalar(
            select(LearningEvidence).where(LearningEvidence.id == evidence_id)
        )
        return _to_evidence(row) if row is not None else None

    def add_evidence(self, item: EvidenceSnapshot) -> None:
        try:
            with self._session.begin_nested():
                self._session.add(
                    LearningEvidence(
                        id=item.id,
                        tenant_id=item.tenant_id,
                        person_id=item.person_id,
                        enrollment_id=item.enrollment_id,
                        program_version_id=item.program_version_id,
                        program_id=item.program_id,
                        program_scope=item.program_scope,
                        program_owner_key=item.program_owner_key,
                        module_id=item.module_id,
                        activity_id=item.activity_id,
                        evidence_type=_evidence_type(item.evidence_type).value,
                        activity_version=item.activity_version,
                        policy_version=item.policy_version,
                        idempotency_key=item.idempotency_key,
                        payload=dict(item.payload),
                        playback_session_id=item.playback_session_id,
                        captured_at=item.captured_at,
                    )
                )
                self._session.flush()
        except IntegrityError as exc:
            raise DuplicateEvidenceError(
                "evidence idempotency key has already been submitted"
            ) from exc

    def find_submission_by_request(self, *scope: UUID | str) -> EvidenceSubmissionSnapshot | None:
        tenant_id, enrollment_id, person_id, version_id, activity_id, key = scope
        row = self._session.scalar(
            select(EvidenceSubmission).where(
                EvidenceSubmission.tenant_id == cast(UUID, tenant_id),
                EvidenceSubmission.enrollment_id == cast(UUID, enrollment_id),
                EvidenceSubmission.person_id == cast(UUID, person_id),
                EvidenceSubmission.program_version_id == cast(UUID, version_id),
                EvidenceSubmission.activity_id == cast(UUID, activity_id),
                EvidenceSubmission.idempotency_key == cast(str, key),
            )
        )
        return _to_submission(row) if row is not None else None

    def get_submission(self, submission_id: UUID) -> EvidenceSubmissionSnapshot | None:
        row = self._session.scalar(
            select(EvidenceSubmission).where(EvidenceSubmission.id == submission_id)
        )
        return _to_submission(row) if row is not None else None

    def submissions_for_evidence(self, evidence_id: UUID) -> tuple[EvidenceSubmissionSnapshot, ...]:
        rows = self._session.scalars(
            select(EvidenceSubmission)
            .where(EvidenceSubmission.evidence_id == evidence_id)
            .order_by(EvidenceSubmission.submitted_at, EvidenceSubmission.id)
        )
        return tuple(_to_submission(row) for row in rows)

    def add_submission(self, item: EvidenceSubmissionSnapshot) -> None:
        try:
            with self._session.begin_nested():
                self._session.add(
                    EvidenceSubmission(
                        id=item.id,
                        evidence_id=item.evidence_id,
                        tenant_id=item.tenant_id,
                        person_id=item.person_id,
                        enrollment_id=item.enrollment_id,
                        program_version_id=item.program_version_id,
                        program_id=item.program_id,
                        program_scope=item.program_scope,
                        program_owner_key=item.program_owner_key,
                        module_id=item.module_id,
                        activity_id=item.activity_id,
                        submitted_by_person_id=item.submitted_by_person_id,
                        assigned_reviewer_id=item.assigned_reviewer_id,
                        idempotency_key=item.idempotency_key,
                        status=_submission_status(item.status).value,
                        submitted_at=item.submitted_at,
                    )
                )
                self._session.flush()
        except IntegrityError as exc:
            raise DuplicateEvidenceError(
                "submission idempotency key has already been submitted"
            ) from exc

    def corrections_for_submission(
        self, submission_id: UUID
    ) -> tuple[EvidenceCorrectionSnapshot, ...]:
        rows = self._session.scalars(
            select(EvidenceCorrection)
            .where(EvidenceCorrection.submission_id == submission_id)
            .order_by(EvidenceCorrection.correction_sequence, EvidenceCorrection.id)
        )
        return tuple(_to_correction(row) for row in rows)

    def append_correction(
        self, item: EvidenceCorrectionSnapshot, *, expected_revision: int
    ) -> None:
        rows = list(
            self._session.scalars(
                select(EvidenceCorrection)
                .where(EvidenceCorrection.submission_id == item.submission_id)
                .order_by(EvidenceCorrection.correction_sequence.desc())
                .with_for_update()
            )
        )
        if len(rows) != expected_revision:
            raise CorrectionRevisionConflict("the submission review revision is stale")
        expected_sequence = rows[0].correction_sequence + 1 if rows else 1
        if item.correction_sequence != expected_sequence:
            raise CorrectionRevisionConflict("the correction sequence is stale")
        if any(row.idempotency_key == item.idempotency_key for row in rows):
            raise DuplicateEvidenceError("correction idempotency key has already been used")
        try:
            with self._session.begin_nested():
                self._session.add(
                    EvidenceCorrection(
                        id=item.id,
                        submission_id=item.submission_id,
                        evidence_id=item.evidence_id,
                        tenant_id=item.tenant_id,
                        person_id=item.person_id,
                        enrollment_id=item.enrollment_id,
                        program_version_id=item.program_version_id,
                        program_id=item.program_id,
                        program_scope=item.program_scope,
                        program_owner_key=item.program_owner_key,
                        module_id=item.module_id,
                        activity_id=item.activity_id,
                        reviewer_person_id=item.reviewer_person_id,
                        decision=_review_decision(item.decision).value,
                        reason=item.reason,
                        idempotency_key=item.idempotency_key,
                        correction_sequence=item.correction_sequence,
                        supersedes_correction_id=item.supersedes_correction_id,
                        created_at=item.created_at,
                    )
                )
                self._session.flush()
        except IntegrityError as exc:
            raise CorrectionRevisionConflict("the correction append lost a race") from exc

    def get_command(
        self,
        *,
        tenant_id: UUID,
        actor_person_id: UUID,
        operation: str,
        idempotency_key: str,
    ) -> CommandLedgerSnapshot | None:
        row = self._session.scalar(
            select(LearningCommandIdempotency)
            .where(
                LearningCommandIdempotency.tenant_id == tenant_id,
                LearningCommandIdempotency.actor_person_id == actor_person_id,
                LearningCommandIdempotency.operation == operation,
                LearningCommandIdempotency.idempotency_key == idempotency_key,
            )
            .with_for_update()
        )
        return _to_command(row) if row is not None else None

    def claim_command(self, command: CommandLedgerSnapshot) -> None:
        try:
            with self._session.begin_nested():
                self._session.add(
                    LearningCommandIdempotency(
                        id=command.id,
                        tenant_id=command.tenant_id,
                        actor_person_id=command.actor_person_id,
                        person_id=command.person_id,
                        enrollment_id=command.enrollment_id,
                        program_version_id=command.program_version_id,
                        program_id=command.program_id,
                        program_scope=command.program_scope,
                        program_owner_key=command.program_owner_key,
                        module_id=command.module_id,
                        activity_id=command.activity_id,
                        operation=command.operation,
                        idempotency_key=command.idempotency_key,
                        request_digest=command.request_digest,
                        status=_command_status(command.status).value,
                        result_progress_id=command.result_progress_id,
                        result_draft_id=command.result_draft_id,
                        result_session_id=command.result_session_id,
                        result_interval_id=command.result_interval_id,
                        result_evidence_id=command.result_evidence_id,
                        result_submission_id=command.result_submission_id,
                        result_correction_id=command.result_correction_id,
                        created_at=command.created_at,
                        completed_at=command.completed_at,
                    )
                )
                self._session.flush()
        except IntegrityError as exc:
            raise _DuplicateCommandClaim from exc

    def complete_command(
        self, command: CommandLedgerSnapshot, *, now: datetime
    ) -> CommandLedgerSnapshot:
        completed_at = _utc(now)
        result = cast(
            Any,
            self._session.execute(
                update(LearningCommandIdempotency)
                .where(
                    LearningCommandIdempotency.id == command.id,
                    LearningCommandIdempotency.tenant_id == command.tenant_id,
                    LearningCommandIdempotency.actor_person_id == command.actor_person_id,
                    LearningCommandIdempotency.operation == command.operation,
                    LearningCommandIdempotency.idempotency_key == command.idempotency_key,
                    LearningCommandIdempotency.status == LearningCommandStatus.PENDING.value,
                )
                .values(
                    status=LearningCommandStatus.COMPLETED.value,
                    result_progress_id=command.result_progress_id,
                    result_draft_id=command.result_draft_id,
                    result_session_id=command.result_session_id,
                    result_interval_id=command.result_interval_id,
                    result_evidence_id=command.result_evidence_id,
                    result_submission_id=command.result_submission_id,
                    result_correction_id=command.result_correction_id,
                    completed_at=completed_at,
                )
            ),
        )
        if result.rowcount != 1:
            raise PersistenceConflictError("the learning command ledger claim is stale")
        return replace(
            command,
            status=LearningCommandStatus.COMPLETED,
            completed_at=completed_at,
        )

    def lock_projection_scope(self, access: LearningAccessContext) -> None:
        from ac_platform.enrollment.models import Enrollment as EnrollmentModel

        enrollment_id = self._session.scalar(
            select(EnrollmentModel.id)
            .where(
                EnrollmentModel.tenant_id == access.tenant_id,
                EnrollmentModel.id == access.enrollment_id,
                EnrollmentModel.person_id == access.person_id,
                EnrollmentModel.program_version_id == access.program_version_id,
                EnrollmentModel.program_id == access.program.id,
                EnrollmentModel.program_scope == access.program.program_scope,
                EnrollmentModel.program_owner_key == access.program.program_owner_key,
            )
            .with_for_update()
        )
        if enrollment_id is None:
            raise AccessContextRequiredError("projection enrollment scope no longer exists")

    def upsert_projection(self, item: LearningProgressProjectionSnapshot) -> None:
        lookup = select(LearningProgressProjection).where(
            LearningProgressProjection.tenant_id == item.tenant_id,
            LearningProgressProjection.enrollment_id == item.enrollment_id,
            LearningProgressProjection.person_id == item.person_id,
            LearningProgressProjection.program_version_id == item.program_version_id,
            LearningProgressProjection.program_id == item.program_id,
            LearningProgressProjection.program_scope == item.program_scope,
            LearningProgressProjection.program_owner_key == item.program_owner_key,
            LearningProgressProjection.scope_type == item.scope_type,
            LearningProgressProjection.scope_id == item.scope_id,
        )
        existing = self._session.scalar(lookup.with_for_update())
        values = {
            "tenant_id": item.tenant_id,
            "person_id": item.person_id,
            "enrollment_id": item.enrollment_id,
            "program_version_id": item.program_version_id,
            "program_id": item.program_id,
            "program_scope": item.program_scope,
            "program_owner_key": item.program_owner_key,
            "module_id": item.module_id,
            "scope_type": item.scope_type,
            "scope_id": item.scope_id,
            "denominator": item.denominator,
            "completed_count": item.completed_count,
            "percentage": item.percentage,
            "projection_version": item.projection_version,
            "explanation": dict(item.explanation),
            "computed_at": item.computed_at,
        }
        if existing is None:
            try:
                with self._session.begin_nested():
                    self._session.add(LearningProgressProjection(id=uuid4(), **values))
                    self._session.flush()
                return
            except IntegrityError:
                existing = self._session.scalar(lookup.with_for_update())
                if existing is None:
                    raise PersistenceConflictError(
                        "progress projection first-write lost an unrecoverable race"
                    ) from None
        if existing is not None:
            self._session.execute(
                update(LearningProgressProjection)
                .where(LearningProgressProjection.id == existing.id)
                .values(**values)
            )
        self._session.flush()


class InMemoryLearningUnitOfWork:
    """Explicit test-only UoW; it is rejected by ``LearningService``."""

    durable = False

    def __init__(self, repository: InMemoryLearningStore) -> None:
        self.repository = repository
        self._transaction: AbstractContextManager[None] | None = None
        self._committed = False

    async def __aenter__(self) -> Self:
        self._transaction = self.repository.atomic()
        self._transaction.__enter__()
        return self

    async def run(self, operation: Callable[[LearningRepository], T]) -> T:
        return operation(self.repository)

    async def commit(self) -> None:
        self._committed = True

    async def rollback(self) -> None:
        self._committed = False
        if self._transaction is not None:
            self._transaction.__exit__(RuntimeError, RuntimeError("rollback"), None)
            self._transaction = None

    async def __aexit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        if self._transaction is None:
            return
        if exc_type is not None or not self._committed:
            self._transaction.__exit__(exc_type or RuntimeError, exc_value, traceback)
        else:
            self._transaction.__exit__(None, None, None)
        self._transaction = None


class SqlAlchemyLearningUnitOfWork:
    """Async SQLAlchemy UoW that runs the synchronous domain adapter via greenlet."""

    durable = True

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        activity_resolver: Callable[[object, object], ActivityDefinition],
        reviewer_resolver: Callable[[LearningAccessContext], UUID | None],
    ) -> None:
        self._session_factory = session_factory
        self._activity_resolver = activity_resolver
        self._reviewer_resolver = reviewer_resolver
        self._session: AsyncSession | None = None
        self._committed = False

    async def __aenter__(self) -> Self:
        session = self._session_factory()
        self._session = session
        await session.begin()
        return self

    async def run(self, operation: Callable[[LearningRepository], T]) -> T:
        if self._session is None:
            raise PersistenceConflictError("the learning UoW is not active")

        def invoke(sync_session: Session) -> T:
            repository = SqlAlchemyLearningRepository(
                sync_session,
                activity_resolver=self._activity_resolver,
                reviewer_resolver=self._reviewer_resolver,
            )
            return operation(repository)

        return await self._session.run_sync(invoke)

    async def commit(self) -> None:
        if self._session is None:
            raise PersistenceConflictError("the learning UoW is not active")
        await self._session.commit()
        self._committed = True

    async def rollback(self) -> None:
        if self._session is not None:
            await self._session.rollback()
        self._committed = False

    async def __aexit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        del exc_value, traceback
        if self._session is None:
            return
        try:
            if exc_type is not None or not self._committed:
                await self._session.rollback()
        finally:
            await self._session.close()
            self._session = None


__all__ = [
    "ActivityDefinition",
    "ActivityProgressSnapshot",
    "ActivityService",
    "ActivityState",
    "CourseDefinition",
    "CourseProgressProjection",
    "DraftService",
    "DraftSnapshot",
    "DraftStatus",
    "EvidenceCorrectionSnapshot",
    "EvidenceService",
    "EvidenceSnapshot",
    "EvidenceSubmissionSnapshot",
    "EvidenceSubmissionStatus",
    "EvidenceType",
    "InMemoryLearningService",
    "InMemoryLearningStore",
    "InMemoryLearningUnitOfWork",
    "LearningAccessContext",
    "LearningCommandBundle",
    "LearningCommandIdempotency",
    "LearningCommandStatus",
    "LearningError",
    "LearningProgressProjectionSnapshot",
    "LearningRepository",
    "LearningService",
    "LearningUnitOfWork",
    "MembershipResolution",
    "ModuleDefinition",
    "PlaybackService",
    "PlaybackSessionSnapshot",
    "PlaybackSessionStatus",
    "ProgressExplanation",
    "ProgressProjector",
    "ProjectionScope",
    "PrerequisiteEvaluation",
    "PrerequisiteEvaluator",
    "ReviewDecision",
    "ReviewerAuthorization",
    "SqlAlchemyLearningRepository",
    "SqlAlchemyLearningUnitOfWork",
    "TimeInterval",
    "VideoCoverage",
    "VideoEvidencePolicy",
    "VideoWatchInterval",
    "WatchIntervalKind",
    "WatchIntervalSnapshot",
    "calculate_video_coverage",
    "authoritative_progress",
    "explain_progress",
    "merge_intervals",
    "merge_unique_intervals",
    "project_progress",
    "unique_coverage_seconds",
    "validate_video_evidence",
]
