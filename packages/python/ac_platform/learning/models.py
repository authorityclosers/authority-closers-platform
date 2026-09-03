"""SQLAlchemy persistence models for the hardened G1 learning boundary.

Learning state is scoped by the tenant, learner, enrollment, pinned program
version, and activity.  The repeated scope columns are intentional: they make
cross-aggregate writes impossible through ordinary foreign keys and make
tenant isolation visible in every query.  Facts are append-only; mutable
progress, drafts, and playback sessions are guarded by service-level CAS
operations.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    Uuid,
    event,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.catalog.models import ActivityKind
from ac_platform.db.base import Base


def utc_now() -> datetime:
    """Return an aware UTC timestamp for application-side defaults."""

    return datetime.now(UTC)


GLOBAL_CATALOG_OWNER = "00000000000000000000000000000000"


def _catalog_scope_checks() -> tuple[CheckConstraint, ...]:
    return (
        CheckConstraint("program_scope IN ('global', 'tenant')", name="program_scope_supported"),
        CheckConstraint(
            f"(program_scope = 'global' AND program_owner_key = '{GLOBAL_CATALOG_OWNER}') "
            "OR (program_scope = 'tenant' AND program_owner_key = tenant_id)",
            name="program_scope_owner_match",
        ),
    )


def _activity_scope_constraints(table: str) -> tuple[ForeignKeyConstraint, ...]:
    return (
        ForeignKeyConstraint(
            [
                "tenant_id",
                "enrollment_id",
                "person_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
            ],
            [
                "enrollments.tenant_id",
                "enrollments.id",
                "enrollments.person_id",
                "enrollments.program_version_id",
                "enrollments.program_id",
                "enrollments.program_scope",
                "enrollments.program_owner_key",
            ],
            name=f"fk_{table}_enrollment_full_scope",
        ),
        ForeignKeyConstraint(
            [
                "activity_id",
                "module_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
            ],
            [
                "activities.id",
                "activities.module_id",
                "activities.program_version_id",
                "activities.program_id",
                "activities.scope",
                "activities.owner_key",
            ],
            name=f"fk_{table}_activity_full_scope",
        ),
    )


class ActivityState(StrEnum):
    """The learner-visible activity states in the first slice."""

    LOCKED = "locked"
    AVAILABLE = "available"
    IN_PROGRESS = "in_progress"
    AWAITING_REVIEW = "awaiting_review"
    COMPLETED = "completed"


class DraftStatus(StrEnum):
    """Durable save status; this is never official completion."""

    SAVED = "saved"


class EvidenceType(StrEnum):
    """Evidence categories accepted by the learning boundary."""

    VIDEO_WATCH = "video_watch"
    REFLECTION = "reflection"
    IMPLEMENTATION = "implementation"
    REVIEW = "review"
    IMPROVEMENT = "improvement"


class EvidenceSubmissionStatus(StrEnum):
    """Submission lifecycle, separate from an activity's current state."""

    RECORDED = "recorded"
    AWAITING_REVIEW = "awaiting_review"


class ReviewDecision(StrEnum):
    """Human-only review decisions; no autonomous score is represented."""

    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_REVISION = "needs_revision"


class PlaybackSessionStatus(StrEnum):
    """Durable playback session lifecycle."""

    ACTIVE = "active"
    CLOSED = "closed"


class WatchIntervalKind(StrEnum):
    """A playback event can be watched time or a seek marker."""

    WATCH = "watch"
    SEEK = "seek"


class ProjectionScope(StrEnum):
    """Persisted projection scopes."""

    MODULE = "module"
    COURSE = "course"


class LearningCommandStatus(StrEnum):
    """Durable learning-command ledger state."""

    PENDING = "pending"
    COMPLETED = "completed"


class ActivityProgress(Base):
    """Current mutable state for one enrolled learner activity."""

    __tablename__ = "activity_progress"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_activity_progress_membership_scope",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "enrollment_id"],
            ["enrollments.tenant_id", "enrollments.id"],
            name="fk_activity_progress_enrollment_scope",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "person_id", "program_version_id"],
            [
                "enrollments.tenant_id",
                "enrollments.person_id",
                "enrollments.program_version_id",
            ],
            name="fk_activity_progress_subject_program_version",
        ),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "enrollment_id",
                "person_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
                "module_id",
                "activity_id",
                "completion_evidence_id",
            ],
            [
                "learning_evidence.tenant_id",
                "learning_evidence.enrollment_id",
                "learning_evidence.person_id",
                "learning_evidence.program_version_id",
                "learning_evidence.program_id",
                "learning_evidence.program_scope",
                "learning_evidence.program_owner_key",
                "learning_evidence.module_id",
                "learning_evidence.activity_id",
                "learning_evidence.id",
            ],
            name="fk_activity_progress_completion_evidence_scope",
        ),
        *_activity_scope_constraints("activity_progress"),
        UniqueConstraint("tenant_id", "id", name="uq_activity_progress_tenant_id_id"),
        UniqueConstraint(
            "tenant_id",
            "enrollment_id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            "module_id",
            "activity_id",
            name="uq_activity_progress_learning_scope",
        ),
        UniqueConstraint(
            "tenant_id",
            "enrollment_id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            "module_id",
            "activity_id",
            "id",
            name="uq_activity_progress_learning_scope_id",
        ),
        CheckConstraint(
            "state IN ('locked', 'available', 'in_progress', 'awaiting_review', 'completed')",
            name="state",
        ),
        CheckConstraint("revision >= 0", name="revision_nonnegative"),
        CheckConstraint(
            "completed_at IS NULL OR state = 'completed'",
            name="completed_timestamp_consistent",
        ),
        CheckConstraint(
            "state <> 'completed' OR completion_evidence_id IS NOT NULL",
            name="completed_requires_evidence",
        ),
        *_catalog_scope_checks(),
        Index("ix_activity_progress_tenant_person", "tenant_id", "person_id"),
        Index("ix_activity_progress_learning_scope", "tenant_id", "enrollment_id", "activity_id"),
        Index("ix_activity_progress_activity_state", "activity_id", "state"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    enrollment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_scope: Mapped[str] = mapped_column(String(16), nullable=False)
    program_owner_key: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    module_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    activity_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ActivityState.AVAILABLE.value,
        server_default="available",
    )
    activity_version: Mapped[str] = mapped_column(
        String(128), nullable=False, default="v1", server_default="v1"
    )
    policy_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    awaiting_review_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completion_evidence_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
    )


class ActivityDraft(Base):
    """Mutable learner work-in-progress protected by durable idempotency/CAS."""

    __tablename__ = "activity_drafts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_activity_drafts_membership_scope",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "enrollment_id"],
            ["enrollments.tenant_id", "enrollments.id"],
            name="fk_activity_drafts_enrollment_scope",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "person_id", "program_version_id"],
            [
                "enrollments.tenant_id",
                "enrollments.person_id",
                "enrollments.program_version_id",
            ],
            name="fk_activity_drafts_subject_program_version",
        ),
        *_activity_scope_constraints("activity_drafts"),
        UniqueConstraint("tenant_id", "id", name="uq_activity_drafts_tenant_id_id"),
        UniqueConstraint(
            "tenant_id",
            "enrollment_id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            "module_id",
            "activity_id",
            name="uq_activity_drafts_learning_scope",
        ),
        UniqueConstraint(
            "tenant_id",
            "enrollment_id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            "module_id",
            "activity_id",
            "id",
            name="uq_activity_drafts_learning_scope_id",
        ),
        CheckConstraint("revision >= 0", name="revision_nonnegative"),
        CheckConstraint("status IN ('saved')", name="status"),
        CheckConstraint(
            "last_idempotency_key IS NULL OR length(trim(last_idempotency_key)) > 0",
            name="idempotency_key_nonblank",
        ),
        CheckConstraint(
            "last_request_fingerprint IS NULL OR length(last_request_fingerprint) = 64",
            name="request_fingerprint_sha256",
        ),
        *_catalog_scope_checks(),
        Index("ix_activity_drafts_tenant_person", "tenant_id", "person_id"),
        Index("ix_activity_drafts_learning_scope", "tenant_id", "enrollment_id", "activity_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    enrollment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_scope: Mapped[str] = mapped_column(String(16), nullable=False)
    program_owner_key: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    module_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    activity_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=DraftStatus.SAVED.value, server_default="saved"
    )
    last_idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_request_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    saved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
    )


class PlaybackSession(Base):
    """Version-pinned playback window authenticated by a hashed opaque token."""

    __tablename__ = "playback_sessions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_playback_sessions_membership_scope",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "enrollment_id"],
            ["enrollments.tenant_id", "enrollments.id"],
            name="fk_playback_sessions_enrollment_scope",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "person_id", "program_version_id"],
            [
                "enrollments.tenant_id",
                "enrollments.person_id",
                "enrollments.program_version_id",
            ],
            name="fk_playback_sessions_subject_program_version",
        ),
        *_activity_scope_constraints("playback_sessions"),
        UniqueConstraint("tenant_id", "id", name="uq_playback_sessions_tenant_id_id"),
        UniqueConstraint("session_token_hash", name="uq_playback_sessions_token_hash"),
        UniqueConstraint(
            "tenant_id",
            "enrollment_id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            "module_id",
            "activity_id",
            "id",
            name="uq_playback_sessions_learning_scope_id",
        ),
        CheckConstraint("status IN ('active', 'closed')", name="status"),
        CheckConstraint("duration_seconds > 0", name="duration_positive"),
        CheckConstraint(
            "coverage_threshold > 0 AND coverage_threshold <= 1",
            name="coverage_threshold_range",
        ),
        CheckConstraint("expires_at > started_at", name="expiry_after_start"),
        CheckConstraint("revision >= 0", name="revision_nonnegative"),
        CheckConstraint("last_sequence >= 0", name="last_sequence_nonnegative"),
        CheckConstraint("last_position_seconds >= 0", name="last_position_nonnegative"),
        CheckConstraint(
            "minimum_watch_interval_seconds >= 0",
            name="minimum_watch_interval_nonnegative",
        ),
        CheckConstraint("max_event_seconds > 0", name="max_event_positive"),
        CheckConstraint(
            "max_heartbeat_gap_seconds > 0",
            name="max_heartbeat_gap_positive",
        ),
        CheckConstraint(
            "minimum_heartbeats_for_completion >= 2",
            name="minimum_heartbeats_at_least_two",
        ),
        CheckConstraint("clock_grace_seconds >= 0", name="clock_grace_nonnegative"),
        CheckConstraint("max_rewind_seconds >= 0", name="max_rewind_nonnegative"),
        CheckConstraint(
            "length(session_token_hash) = 32",
            name="session_token_hash_sha256",
        ),
        CheckConstraint("length(policy_version) > 0", name="policy_version_nonblank"),
        *_catalog_scope_checks(),
        Index("ix_playback_sessions_tenant_person", "tenant_id", "person_id"),
        Index(
            "ix_playback_sessions_learning_scope",
            "tenant_id",
            "enrollment_id",
            "program_version_id",
            "activity_id",
        ),
        Index("ix_playback_sessions_activity_status", "activity_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    enrollment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_scope: Mapped[str] = mapped_column(String(16), nullable=False)
    program_owner_key: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    module_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    activity_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    content_version: Mapped[str] = mapped_column(String(128), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(128), nullable=False)
    session_token_hash: Mapped[bytes] = mapped_column(LargeBinary(length=32), nullable=False)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    coverage_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.90)
    minimum_watch_interval_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    max_event_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    max_heartbeat_gap_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    minimum_heartbeats_for_completion: Mapped[int] = mapped_column(Integer, nullable=False)
    clock_grace_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    max_rewind_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=PlaybackSessionStatus.ACTIVE.value,
        server_default="active",
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_sequence: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_position_seconds: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0"
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class VideoWatchInterval(Base):
    """Append-only playback event; seek markers never count as watch time."""

    __tablename__ = "video_watch_intervals"
    __table_args__ = (
        ForeignKeyConstraint(
            [
                "tenant_id",
                "enrollment_id",
                "person_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
                "module_id",
                "activity_id",
                "playback_session_id",
            ],
            [
                "playback_sessions.tenant_id",
                "playback_sessions.enrollment_id",
                "playback_sessions.person_id",
                "playback_sessions.program_version_id",
                "playback_sessions.program_id",
                "playback_sessions.program_scope",
                "playback_sessions.program_owner_key",
                "playback_sessions.module_id",
                "playback_sessions.activity_id",
                "playback_sessions.id",
            ],
            name="fk_video_watch_intervals_session_scope",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_video_watch_intervals_tenant_id_id"),
        UniqueConstraint(
            "tenant_id",
            "enrollment_id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            "module_id",
            "activity_id",
            "id",
            name="uq_video_watch_intervals_learning_scope_id",
        ),
        UniqueConstraint(
            "playback_session_id",
            "event_id",
            name="uq_video_watch_intervals_session_event",
        ),
        UniqueConstraint(
            "playback_session_id",
            "sequence",
            name="uq_video_watch_intervals_session_sequence",
        ),
        CheckConstraint("kind IN ('watch', 'seek')", name="kind"),
        CheckConstraint("sequence > 0", name="sequence_positive"),
        CheckConstraint("start_seconds >= 0", name="start_nonnegative"),
        CheckConstraint("end_seconds >= start_seconds", name="end_after_start"),
        CheckConstraint(
            "kind = 'seek' OR end_seconds > start_seconds",
            name="watch_interval_positive",
        ),
        CheckConstraint("length(trim(event_id)) > 0", name="event_id_nonblank"),
        *_catalog_scope_checks(),
        Index("ix_video_watch_intervals_session_start", "playback_session_id", "start_seconds"),
        Index("ix_video_watch_intervals_tenant_person", "tenant_id", "person_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    playback_session_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    enrollment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_scope: Mapped[str] = mapped_column(String(16), nullable=False)
    program_owner_key: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    module_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    activity_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default=WatchIntervalKind.WATCH.value, server_default="watch"
    )
    start_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    end_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )


class LearningEvidence(Base):
    """Immutable evidence fact submitted for one learner activity."""

    __tablename__ = "learning_evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_learning_evidence_membership_scope",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "enrollment_id"],
            ["enrollments.tenant_id", "enrollments.id"],
            name="fk_learning_evidence_enrollment_scope",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "person_id", "program_version_id"],
            [
                "enrollments.tenant_id",
                "enrollments.person_id",
                "enrollments.program_version_id",
            ],
            name="fk_learning_evidence_subject_program_version",
        ),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "enrollment_id",
                "person_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
                "module_id",
                "activity_id",
                "playback_session_id",
            ],
            [
                "playback_sessions.tenant_id",
                "playback_sessions.enrollment_id",
                "playback_sessions.person_id",
                "playback_sessions.program_version_id",
                "playback_sessions.program_id",
                "playback_sessions.program_scope",
                "playback_sessions.program_owner_key",
                "playback_sessions.module_id",
                "playback_sessions.activity_id",
                "playback_sessions.id",
            ],
            name="fk_learning_evidence_playback_session_scope",
        ),
        *_activity_scope_constraints("learning_evidence"),
        UniqueConstraint("tenant_id", "id", name="uq_learning_evidence_tenant_id_id"),
        UniqueConstraint(
            "tenant_id",
            "enrollment_id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            "module_id",
            "activity_id",
            "idempotency_key",
            name="uq_learning_evidence_request",
        ),
        UniqueConstraint(
            "tenant_id",
            "enrollment_id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            "module_id",
            "activity_id",
            "id",
            name="uq_learning_evidence_learning_scope_id",
        ),
        CheckConstraint(
            "evidence_type IN ("
            "'video_watch', 'reflection', 'implementation', 'review', 'improvement'"
            ")",
            name="evidence_type",
        ),
        CheckConstraint("length(trim(idempotency_key)) > 0", name="idempotency_key_nonblank"),
        CheckConstraint("length(trim(activity_version)) > 0", name="activity_version_nonblank"),
        CheckConstraint("length(trim(policy_version)) > 0", name="policy_version_nonblank"),
        *_catalog_scope_checks(),
        Index(
            "ix_learning_evidence_tenant_person_activity",
            "tenant_id",
            "person_id",
            "activity_id",
        ),
        Index("ix_learning_evidence_learning_scope", "tenant_id", "enrollment_id", "activity_id"),
        Index("ix_learning_evidence_playback_session", "playback_session_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    enrollment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_scope: Mapped[str] = mapped_column(String(16), nullable=False)
    program_owner_key: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    module_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    activity_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    evidence_type: Mapped[str] = mapped_column(String(32), nullable=False)
    activity_version: Mapped[str] = mapped_column(String(128), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    playback_session_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )


class EvidenceSubmission(Base):
    """Immutable submission envelope around one evidence fact."""

    __tablename__ = "evidence_submissions"
    __table_args__ = (
        ForeignKeyConstraint(
            [
                "tenant_id",
                "enrollment_id",
                "person_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
                "module_id",
                "activity_id",
                "evidence_id",
            ],
            [
                "learning_evidence.tenant_id",
                "learning_evidence.enrollment_id",
                "learning_evidence.person_id",
                "learning_evidence.program_version_id",
                "learning_evidence.program_id",
                "learning_evidence.program_scope",
                "learning_evidence.program_owner_key",
                "learning_evidence.module_id",
                "learning_evidence.activity_id",
                "learning_evidence.id",
            ],
            name="fk_evidence_submissions_evidence_scope",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_evidence_submissions_membership_scope",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "submitted_by_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_evidence_submissions_submitter_membership",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "assigned_reviewer_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_evidence_submissions_reviewer_membership",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_evidence_submissions_tenant_id_id"),
        UniqueConstraint(
            "tenant_id",
            "enrollment_id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            "module_id",
            "activity_id",
            "idempotency_key",
            name="uq_evidence_submissions_request",
        ),
        UniqueConstraint(
            "tenant_id",
            "enrollment_id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            "module_id",
            "activity_id",
            "id",
            name="uq_evidence_submissions_learning_scope_id",
        ),
        CheckConstraint(
            "status IN ('recorded', 'awaiting_review')",
            name="status",
        ),
        CheckConstraint(
            "(status = 'recorded' AND assigned_reviewer_id IS NULL) "
            "OR (status = 'awaiting_review' AND assigned_reviewer_id IS NOT NULL)",
            name="review_assignment_matches_status",
        ),
        CheckConstraint(
            "assigned_reviewer_id IS NULL OR assigned_reviewer_id <> person_id",
            name="reviewer_not_learner",
        ),
        CheckConstraint("length(trim(idempotency_key)) > 0", name="idempotency_key_nonblank"),
        *_catalog_scope_checks(),
        Index(
            "ix_evidence_submissions_tenant_person_activity",
            "tenant_id",
            "person_id",
            "activity_id",
        ),
        Index(
            "ix_evidence_submissions_learning_scope", "tenant_id", "enrollment_id", "activity_id"
        ),
        Index("ix_evidence_submissions_reviewer", "tenant_id", "assigned_reviewer_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    evidence_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    enrollment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_scope: Mapped[str] = mapped_column(String(16), nullable=False)
    program_owner_key: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    module_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    activity_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    submitted_by_person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    assigned_reviewer_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )


class EvidenceCorrection(Base):
    """Append-only human correction that supersedes an earlier review fact."""

    __tablename__ = "evidence_corrections"
    __table_args__ = (
        ForeignKeyConstraint(
            [
                "tenant_id",
                "enrollment_id",
                "person_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
                "module_id",
                "activity_id",
                "submission_id",
            ],
            [
                "evidence_submissions.tenant_id",
                "evidence_submissions.enrollment_id",
                "evidence_submissions.person_id",
                "evidence_submissions.program_version_id",
                "evidence_submissions.program_id",
                "evidence_submissions.program_scope",
                "evidence_submissions.program_owner_key",
                "evidence_submissions.module_id",
                "evidence_submissions.activity_id",
                "evidence_submissions.id",
            ],
            name="fk_evidence_corrections_submission_scope",
        ),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "enrollment_id",
                "person_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
                "module_id",
                "activity_id",
                "evidence_id",
            ],
            [
                "learning_evidence.tenant_id",
                "learning_evidence.enrollment_id",
                "learning_evidence.person_id",
                "learning_evidence.program_version_id",
                "learning_evidence.program_id",
                "learning_evidence.program_scope",
                "learning_evidence.program_owner_key",
                "learning_evidence.module_id",
                "learning_evidence.activity_id",
                "learning_evidence.id",
            ],
            name="fk_evidence_corrections_evidence_scope",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "reviewer_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_evidence_corrections_reviewer_membership",
        ),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "enrollment_id",
                "person_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
                "module_id",
                "activity_id",
                "supersedes_correction_id",
            ],
            [
                "evidence_corrections.tenant_id",
                "evidence_corrections.enrollment_id",
                "evidence_corrections.person_id",
                "evidence_corrections.program_version_id",
                "evidence_corrections.program_id",
                "evidence_corrections.program_scope",
                "evidence_corrections.program_owner_key",
                "evidence_corrections.module_id",
                "evidence_corrections.activity_id",
                "evidence_corrections.id",
            ],
            name="fk_evidence_corrections_supersedes_scope",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_evidence_corrections_tenant_id_id"),
        UniqueConstraint(
            "submission_id",
            "correction_sequence",
            name="uq_evidence_corrections_submission_sequence",
        ),
        UniqueConstraint(
            "tenant_id",
            "enrollment_id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            "module_id",
            "activity_id",
            "idempotency_key",
            name="uq_evidence_corrections_request",
        ),
        UniqueConstraint(
            "tenant_id",
            "enrollment_id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            "module_id",
            "activity_id",
            "id",
            name="uq_evidence_corrections_learning_scope_id",
        ),
        CheckConstraint(
            "decision IN ('approved', 'rejected', 'needs_revision')",
            name="decision",
        ),
        CheckConstraint("length(trim(reason)) > 0", name="reason_nonblank"),
        CheckConstraint("reviewer_person_id <> person_id", name="reviewer_not_learner"),
        CheckConstraint("correction_sequence > 0", name="correction_sequence_positive"),
        CheckConstraint("length(trim(idempotency_key)) > 0", name="idempotency_key_nonblank"),
        *_catalog_scope_checks(),
        Index("ix_evidence_corrections_submission_created", "submission_id", "created_at"),
        Index("ix_evidence_corrections_tenant_person", "tenant_id", "person_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    submission_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    evidence_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    enrollment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_scope: Mapped[str] = mapped_column(String(16), nullable=False)
    program_owner_key: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    module_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    activity_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    reviewer_person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    correction_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    supersedes_correction_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )


class LearningProgressProjection(Base):
    """Authoritative deterministic explanation of a module or course predicate."""

    __tablename__ = "learning_progress_projections"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_learning_progress_projections_membership_scope",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "enrollment_id"],
            ["enrollments.tenant_id", "enrollments.id"],
            name="fk_learning_progress_projections_enrollment_scope",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "person_id", "program_version_id"],
            [
                "enrollments.tenant_id",
                "enrollments.person_id",
                "enrollments.program_version_id",
            ],
            name="fk_learning_progress_projections_subject_program_version",
        ),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "enrollment_id",
                "person_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
            ],
            [
                "enrollments.tenant_id",
                "enrollments.id",
                "enrollments.person_id",
                "enrollments.program_version_id",
                "enrollments.program_id",
                "enrollments.program_scope",
                "enrollments.program_owner_key",
            ],
            name="fk_learning_progress_projections_enrollment_full_scope",
        ),
        ForeignKeyConstraint(
            ["program_version_id", "program_id", "program_scope", "program_owner_key"],
            [
                "program_versions.id",
                "program_versions.program_id",
                "program_versions.scope",
                "program_versions.owner_key",
            ],
            name="fk_learning_progress_projections_program_version_scope",
        ),
        ForeignKeyConstraint(
            [
                "module_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
            ],
            [
                "modules.id",
                "modules.program_version_id",
                "modules.program_id",
                "modules.scope",
                "modules.owner_key",
            ],
            name="fk_learning_progress_projections_module_scope",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_learning_progress_projections_tenant_id_id"),
        UniqueConstraint(
            "tenant_id",
            "enrollment_id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            "scope_type",
            "scope_id",
            name="uq_learning_progress_projections_scope",
        ),
        CheckConstraint("scope_type IN ('module', 'course')", name="scope_type"),
        CheckConstraint(
            "(scope_type = 'module' AND module_id IS NOT NULL AND scope_id = module_id) "
            "OR (scope_type = 'course' AND module_id IS NULL AND scope_id = program_id)",
            name="scope_identity_consistent",
        ),
        CheckConstraint("denominator >= 0", name="denominator_nonnegative"),
        CheckConstraint(
            "completed_count >= 0 AND completed_count <= denominator",
            name="completed_count_range",
        ),
        CheckConstraint("percentage >= 0 AND percentage <= 1", name="percentage_range"),
        CheckConstraint(
            "abs(percentage - CASE WHEN denominator = 0 THEN 0.0 "
            "ELSE (1.0 * completed_count / denominator) END) <= 0.000000001",
            name="percentage_deterministic",
        ),
        CheckConstraint("projection_version <> ''", name="projection_version_nonblank"),
        *_catalog_scope_checks(),
        Index("ix_learning_progress_projections_tenant_person", "tenant_id", "person_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    enrollment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_scope: Mapped[str] = mapped_column(String(16), nullable=False)
    program_owner_key: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    module_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    denominator: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    percentage: Mapped[float] = mapped_column(Float, nullable=False)
    projection_version: Mapped[str] = mapped_column(String(128), nullable=False)
    explanation: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )


class LearningCommandIdempotency(Base):
    """Durable idempotency claim/result ledger for every learning command."""

    __tablename__ = "learning_command_idempotency"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "actor_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_learning_command_idempotency_actor_membership",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_learning_command_idempotency_subject_membership",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "enrollment_id"],
            ["enrollments.tenant_id", "enrollments.id"],
            name="fk_learning_command_idempotency_enrollment_scope",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "person_id", "program_version_id"],
            [
                "enrollments.tenant_id",
                "enrollments.person_id",
                "enrollments.program_version_id",
            ],
            name="fk_learning_command_idempotency_subject_program_version",
        ),
        *_activity_scope_constraints("learning_command_idempotency"),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "enrollment_id",
                "person_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
                "module_id",
                "activity_id",
                "result_progress_id",
            ],
            [
                "activity_progress.tenant_id",
                "activity_progress.enrollment_id",
                "activity_progress.person_id",
                "activity_progress.program_version_id",
                "activity_progress.program_id",
                "activity_progress.program_scope",
                "activity_progress.program_owner_key",
                "activity_progress.module_id",
                "activity_progress.activity_id",
                "activity_progress.id",
            ],
            name="fk_learning_command_idempotency_progress",
        ),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "enrollment_id",
                "person_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
                "module_id",
                "activity_id",
                "result_draft_id",
            ],
            [
                "activity_drafts.tenant_id",
                "activity_drafts.enrollment_id",
                "activity_drafts.person_id",
                "activity_drafts.program_version_id",
                "activity_drafts.program_id",
                "activity_drafts.program_scope",
                "activity_drafts.program_owner_key",
                "activity_drafts.module_id",
                "activity_drafts.activity_id",
                "activity_drafts.id",
            ],
            name="fk_learning_command_idempotency_draft",
        ),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "enrollment_id",
                "person_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
                "module_id",
                "activity_id",
                "result_session_id",
            ],
            [
                "playback_sessions.tenant_id",
                "playback_sessions.enrollment_id",
                "playback_sessions.person_id",
                "playback_sessions.program_version_id",
                "playback_sessions.program_id",
                "playback_sessions.program_scope",
                "playback_sessions.program_owner_key",
                "playback_sessions.module_id",
                "playback_sessions.activity_id",
                "playback_sessions.id",
            ],
            name="fk_learning_command_idempotency_session",
        ),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "enrollment_id",
                "person_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
                "module_id",
                "activity_id",
                "result_interval_id",
            ],
            [
                "video_watch_intervals.tenant_id",
                "video_watch_intervals.enrollment_id",
                "video_watch_intervals.person_id",
                "video_watch_intervals.program_version_id",
                "video_watch_intervals.program_id",
                "video_watch_intervals.program_scope",
                "video_watch_intervals.program_owner_key",
                "video_watch_intervals.module_id",
                "video_watch_intervals.activity_id",
                "video_watch_intervals.id",
            ],
            name="fk_learning_command_idempotency_interval",
        ),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "enrollment_id",
                "person_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
                "module_id",
                "activity_id",
                "result_evidence_id",
            ],
            [
                "learning_evidence.tenant_id",
                "learning_evidence.enrollment_id",
                "learning_evidence.person_id",
                "learning_evidence.program_version_id",
                "learning_evidence.program_id",
                "learning_evidence.program_scope",
                "learning_evidence.program_owner_key",
                "learning_evidence.module_id",
                "learning_evidence.activity_id",
                "learning_evidence.id",
            ],
            name="fk_learning_command_idempotency_evidence",
        ),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "enrollment_id",
                "person_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
                "module_id",
                "activity_id",
                "result_submission_id",
            ],
            [
                "evidence_submissions.tenant_id",
                "evidence_submissions.enrollment_id",
                "evidence_submissions.person_id",
                "evidence_submissions.program_version_id",
                "evidence_submissions.program_id",
                "evidence_submissions.program_scope",
                "evidence_submissions.program_owner_key",
                "evidence_submissions.module_id",
                "evidence_submissions.activity_id",
                "evidence_submissions.id",
            ],
            name="fk_learning_command_idempotency_submission",
        ),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "enrollment_id",
                "person_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
                "module_id",
                "activity_id",
                "result_correction_id",
            ],
            [
                "evidence_corrections.tenant_id",
                "evidence_corrections.enrollment_id",
                "evidence_corrections.person_id",
                "evidence_corrections.program_version_id",
                "evidence_corrections.program_id",
                "evidence_corrections.program_scope",
                "evidence_corrections.program_owner_key",
                "evidence_corrections.module_id",
                "evidence_corrections.activity_id",
                "evidence_corrections.id",
            ],
            name="fk_learning_command_idempotency_correction",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_learning_command_idempotency_tenant_id_id"),
        UniqueConstraint(
            "tenant_id",
            "actor_person_id",
            "operation",
            "idempotency_key",
            name="uq_learning_command_idempotency_scope_key",
        ),
        CheckConstraint(
            "operation IN ("
            "'activity_start', 'activity_transition', 'draft_save', 'playback_start', "
            "'playback_event', 'playback_close', 'evidence_submit', 'evidence_review'"
            ")",
            name="operation_allowed",
        ),
        CheckConstraint("status IN ('pending', 'completed')", name="status"),
        CheckConstraint("length(trim(idempotency_key)) > 0", name="idempotency_key_nonblank"),
        CheckConstraint("length(request_digest) = 64", name="request_digest_sha256"),
        CheckConstraint(
            "(status = 'pending' AND completed_at IS NULL) "
            "OR (status = 'completed' AND completed_at IS NOT NULL)",
            name="completion_timestamp_consistent",
        ),
        *_catalog_scope_checks(),
        Index(
            "ix_learning_command_idempotency_scope",
            "tenant_id",
            "person_id",
            "enrollment_id",
            "program_version_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    actor_person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    person_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    enrollment_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_version_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    program_scope: Mapped[str] = mapped_column(String(16), nullable=False)
    program_owner_key: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    module_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    activity_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=LearningCommandStatus.PENDING.value,
        server_default="pending",
    )
    result_progress_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    result_draft_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    result_session_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    result_interval_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    result_evidence_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    result_submission_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    result_correction_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def _reject_append_only_update(_mapper: object, _connection: object, _target: object) -> None:
    raise ValueError("learning facts are append-only and cannot be updated")


def _reject_append_only_delete(_mapper: object, _connection: object, _target: object) -> None:
    raise ValueError("learning facts are append-only and cannot be deleted")


for _append_only_model in (
    VideoWatchInterval,
    LearningEvidence,
    EvidenceSubmission,
    EvidenceCorrection,
):
    event.listen(_append_only_model, "before_update", _reject_append_only_update)
    event.listen(_append_only_model, "before_delete", _reject_append_only_delete)


def _validate_projection_values(_mapper: object, _connection: object, target: object) -> None:
    projection = cast(LearningProgressProjection, target)
    denominator = projection.denominator
    completed_count = projection.completed_count
    expected = completed_count / denominator if denominator else 0.0
    if abs(projection.percentage - expected) > 1e-9:
        raise ValueError("learning projections must store their deterministic percentage")
    if not isinstance(projection.explanation, dict):
        raise ValueError("learning projections require a JSON explanation object")
    if projection.explanation.get("denominator") != denominator:
        raise ValueError("learning projection explanation does not match its denominator")
    if projection.explanation.get("completed_count") != completed_count:
        raise ValueError("learning projection explanation does not match its completed count")


event.listen(LearningProgressProjection, "before_insert", _validate_projection_values)
event.listen(LearningProgressProjection, "before_update", _validate_projection_values)


__all__ = [
    "ActivityDraft",
    "ActivityKind",
    "ActivityProgress",
    "ActivityState",
    "DraftStatus",
    "EvidenceCorrection",
    "EvidenceSubmission",
    "EvidenceSubmissionStatus",
    "EvidenceType",
    "LearningCommandIdempotency",
    "LearningCommandStatus",
    "LearningEvidence",
    "LearningProgressProjection",
    "PlaybackSession",
    "PlaybackSessionStatus",
    "ProjectionScope",
    "ReviewDecision",
    "VideoWatchInterval",
    "WatchIntervalKind",
    "utc_now",
]
