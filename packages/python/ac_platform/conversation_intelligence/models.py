"""Private conversation state; content can be erased while command facts survive."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base


def member_fk() -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["tenant_id", "person_id"], ["memberships.tenant_id", "memberships.person_id"]
    )


def recording_fk() -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["recording_id", "tenant_id", "person_id"],
        [
            "conversation_recordings.id",
            "conversation_recordings.tenant_id",
            "conversation_recordings.person_id",
        ],
    )


class ConversationPermission(Base):
    """Server-resolved permission evidence, never an arbitrary caller UUID grant."""

    __tablename__ = "conversation_permissions"
    __table_args__ = (
        member_fk(),
        UniqueConstraint("id", "tenant_id", "person_id"),
        CheckConstraint("provider = 'local'", name="local_provider_only"),
        CheckConstraint("retention_until > created_at", name="bounded_retention"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    source_sha256: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(32))
    permission_reference: Mapped[str] = mapped_column(String(256))
    retention_reference: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    retention_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConversationRecording(Base):
    __tablename__ = "conversation_recordings"
    __table_args__ = (
        member_fk(),
        UniqueConstraint("id", "tenant_id", "person_id"),
        UniqueConstraint("tenant_id", "person_id", "request_key"),
        ForeignKeyConstraint(
            ["permission_id", "tenant_id", "person_id"],
            [
                "conversation_permissions.id",
                "conversation_permissions.tenant_id",
                "conversation_permissions.person_id",
            ],
        ),
        CheckConstraint("source_bytes > 0 AND source_bytes <= 134217728", name="bounded_source"),
        CheckConstraint("state IN ('awaiting_upload','ready','deleting','deleted')", name="state"),
        CheckConstraint("source_revision >= 1 AND generation >= 1", name="positive_revision"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    permission_id: Mapped[UUID] = mapped_column(Uuid)
    request_key: Mapped[str] = mapped_column(String(128))
    intent_sha256: Mapped[str] = mapped_column(String(64))
    source_sha256: Mapped[str] = mapped_column(String(64))
    source_bytes: Mapped[int] = mapped_column(Integer)
    content_type: Mapped[str] = mapped_column(String(32))
    source_revision: Mapped[int] = mapped_column(Integer)
    generation: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConversationRun(Base):
    __tablename__ = "conversation_runs"
    __table_args__ = (
        recording_fk(),
        UniqueConstraint("id", "tenant_id", "person_id"),
        UniqueConstraint("tenant_id", "person_id", "request_key"),
        CheckConstraint(
            "state IN ('queued','running','completed','cancelled','failed')", name="state"
        ),
        CheckConstraint("generation >= 1", name="positive_generation"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    recording_id: Mapped[UUID] = mapped_column(Uuid)
    request_key: Mapped[str] = mapped_column(String(128))
    intent_sha256: Mapped[str] = mapped_column(String(64))
    recipe_revision: Mapped[str] = mapped_column(String(128))
    generation: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(24))
    job_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("jobs.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConversationCheckpoint(Base):
    __tablename__ = "conversation_checkpoints"
    __table_args__ = (
        recording_fk(),
        UniqueConstraint("recording_id", "cache_key"),
        CheckConstraint("stage IN ('C0','C1','C2','C3','C4','C5','C6')", name="stage"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    recording_id: Mapped[UUID] = mapped_column(Uuid)
    cache_key: Mapped[str] = mapped_column(String(64))
    manifest_sha256: Mapped[str] = mapped_column(String(64))
    payload_sha256: Mapped[str] = mapped_column(String(64))
    stage: Mapped[str] = mapped_column(String(2))
    feature_blob_id: Mapped[UUID | None] = mapped_column(Uuid)
    manifest: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConversationMinuteAccount(Base):
    __tablename__ = "conversation_minute_accounts"
    __table_args__ = (member_fk(), CheckConstraint("revision >= 1", name="positive_revision"))
    tenant_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    person_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    revision: Mapped[int] = mapped_column(Integer)


class ConversationBudgetAccount(Base):
    """Project scope shared across users; the INR cap is never multiplied per person."""

    __tablename__ = "conversation_budget_accounts"
    __table_args__ = (CheckConstraint("revision >= 1", name="positive_revision"),)
    scope_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    revision: Mapped[int] = mapped_column(Integer)


class ConversationQuote(Base):
    """Exact quote and execution permission loaded from the bounded broker authority."""

    __tablename__ = "conversation_quotes"
    __table_args__ = (recording_fk(),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    recording_id: Mapped[UUID] = mapped_column(Uuid)
    budget_scope_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("conversation_budget_accounts.scope_id"),
    )
    quote: Mapped[dict[str, Any]] = mapped_column(JSON)
    execution_permission: Mapped[dict[str, Any]] = mapped_column(JSON)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConversationCommand(Base):
    """Append-only non-content receipt; comments/transcripts stay in erasable tables."""

    __tablename__ = "conversation_commands"
    __table_args__ = (member_fk(), UniqueConstraint("tenant_id", "person_id", "key"))
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    key: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(64))
    intent_sha256: Mapped[str] = mapped_column(String(64))
    result_id: Mapped[UUID | None] = mapped_column(Uuid)
    audit_event_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("audit_events.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConversationQuoteAcceptance(Base):
    """Separate immutable owner consent: issuing a quote cannot approve itself."""

    __tablename__ = "conversation_quote_acceptances"
    __table_args__ = (
        member_fk(),
        CheckConstraint("(session_id IS NULL) <> (processing_lease_id IS NULL)", name="one_actor"),
    )
    quote_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("conversation_quotes.id"), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    session_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("sessions.id"))
    processing_lease_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("conversation_processing_leases.id")
    )
    quote_fingerprint: Mapped[str] = mapped_column(String(64))
    privacy_revision: Mapped[str] = mapped_column(String(128))
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConversationReview(Base):
    __tablename__ = "conversation_reviews"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "tenant_id", "person_id"],
            ["conversation_runs.id", "conversation_runs.tenant_id", "conversation_runs.person_id"],
        ),
        UniqueConstraint("tenant_id", "proposal_hash"),
        CheckConstraint("lane IN ('sales','signal')", name="lane"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    run_id: Mapped[UUID] = mapped_column(Uuid)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    reviewer_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("persons.id"))
    lane: Mapped[str] = mapped_column(String(16))
    proposal_hash: Mapped[str] = mapped_column(String(64))
    proposal: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConversationReviewCursor(Base):
    __tablename__ = "conversation_review_cursors"
    __table_args__ = (CheckConstraint("sequence >= 0", name="sequence_nonnegative"),)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), primary_key=True)
    feed_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    sequence: Mapped[int] = mapped_column(Integer)
    event_hash: Mapped[str] = mapped_column(String(64))


class ConversationProviderConfiguration(Base):
    """Append-only admin configuration; only external credential references are permitted."""

    __tablename__ = "conversation_provider_configurations"
    __table_args__ = (
        member_fk(),
        UniqueConstraint("tenant_id", "revision"),
        CheckConstraint("revision >= 1", name="positive_revision"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    session_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("sessions.id"))
    revision: Mapped[int] = mapped_column(Integer)
    configuration_sha256: Mapped[str] = mapped_column(String(64))
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConversationProviderActivation(Base):
    """Append-only selection of one approved configuration for new plans.

    A plan stores the route it was quoted with.  Later activations therefore
    affect only plans quoted after this row; they never rewrite an existing
    quote, reservation, or report lineage.
    """

    __tablename__ = "conversation_provider_activations"
    __table_args__ = (
        member_fk(),
        UniqueConstraint("tenant_id", "sequence"),
        CheckConstraint("sequence >= 1", name="positive_sequence"),
        CheckConstraint("configuration_revision >= 1", name="positive_config_revision"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    session_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("sessions.id"))
    configuration_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("conversation_provider_configurations.id")
    )
    configuration_revision: Mapped[int] = mapped_column(Integer)
    configuration_sha256: Mapped[str] = mapped_column(String(64))
    sequence: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConversationAnalysisSettings(Base):
    """Append-only owner limits intersected into future processing plans."""

    __tablename__ = "conversation_analysis_settings"
    __table_args__ = (
        member_fk(),
        UniqueConstraint("tenant_id", "revision"),
        CheckConstraint("revision >= 1", name="positive_revision"),
        CheckConstraint(
            "c4_max_requests >= 1 AND c4_max_requests <= 64", name="bounded_c4_requests"
        ),
        CheckConstraint(
            "c4_max_completion_tokens >= 256 AND c4_max_completion_tokens <= 4000",
            name="bounded_c4_tokens",
        ),
        CheckConstraint(
            "c5_max_completion_tokens >= 256 AND c5_max_completion_tokens <= 8000",
            name="bounded_c5_tokens",
        ),
        CheckConstraint("c5_output_profile IN ('standard','detailed')", name="known_c5_profile"),
        CheckConstraint(
            "c5_coaching_prompt_revision IN ('coaching-v3','coaching-v4','coaching-v5')",
            name="known_c5_prompt",
        ),
        CheckConstraint(
            "report_language_default IN ('en','hi-Deva+en','mr-Deva+en')",
            name="known_report_language",
        ),
        CheckConstraint(
            "c5_coaching_prompt_revision IN ('coaching-v4','coaching-v5') "
            "OR report_language_default = 'en'",
            name="language_prompt_compatible",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    session_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("sessions.id"))
    revision: Mapped[int] = mapped_column(Integer)
    c4_max_requests: Mapped[int] = mapped_column(Integer)
    c4_max_completion_tokens: Mapped[int] = mapped_column(Integer)
    c5_max_completion_tokens: Mapped[int] = mapped_column(Integer)
    c5_output_profile: Mapped[str] = mapped_column(String(16))
    c5_coaching_prompt_revision: Mapped[str] = mapped_column(
        String(24), server_default="coaching-v3"
    )
    report_language_default: Mapped[str] = mapped_column(String(16), server_default="en")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConversationReportDraft(Base):
    """Internal draft, never an official score or model-promotion decision."""

    __tablename__ = "conversation_report_drafts"
    __table_args__ = (
        recording_fk(),
        ForeignKeyConstraint(
            ["run_id", "tenant_id", "person_id"],
            ["conversation_runs.id", "conversation_runs.tenant_id", "conversation_runs.person_id"],
        ),
        UniqueConstraint("run_id", "report_sha256"),
        CheckConstraint("source_revision >= 1", name="positive_source_revision"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    recording_id: Mapped[UUID] = mapped_column(Uuid)
    run_id: Mapped[UUID] = mapped_column(Uuid)
    source_revision: Mapped[int] = mapped_column(Integer)
    source_sha256: Mapped[str] = mapped_column(String(64))
    report_sha256: Mapped[str] = mapped_column(String(64))
    transcript_sha256: Mapped[str] = mapped_column(String(64))
    profile_sha256: Mapped[str] = mapped_column(String(64))
    evidence_receipt_sha256: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    transcript: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    evidence_receipt: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConversationInferenceTask(Base):
    """One exact external effect, with immutable intent and erasable input content."""

    __tablename__ = "conversation_inference_tasks"
    __table_args__ = (
        recording_fk(),
        ForeignKeyConstraint(
            ["run_id", "tenant_id", "person_id"],
            ["conversation_runs.id", "conversation_runs.tenant_id", "conversation_runs.person_id"],
        ),
        UniqueConstraint("recording_id", "cache_key"),
        UniqueConstraint("job_id"),
        CheckConstraint("stage IN ('C2','C4','C5')", name="stage"),
        CheckConstraint("generation >= 1", name="positive_generation"),
        CheckConstraint("(session_id IS NULL) <> (processing_lease_id IS NULL)", name="one_actor"),
        CheckConstraint(
            "state IN ('queued','running','completed','failed','uncertain','cancelled')",
            name="state",
        ),
    )
    run_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    recording_id: Mapped[UUID] = mapped_column(Uuid)
    session_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("sessions.id"))
    processing_lease_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("conversation_processing_leases.id")
    )
    job_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("jobs.id"))
    quote_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("conversation_quotes.id"))
    generation: Mapped[int] = mapped_column(Integer)
    stage: Mapped[str] = mapped_column(String(2))
    cache_key: Mapped[str] = mapped_column(String(64))
    input_sha256: Mapped[str] = mapped_column(String(64))
    intent_sha256: Mapped[str] = mapped_column(String(64))
    intent: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(16))
    checkpoint_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("conversation_checkpoints.id")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConversationProcessingPlan(Base):
    """Frozen processing intent; acceptance points to an append-only AC command."""

    __tablename__ = "conversation_processing_plans"
    __table_args__ = (
        recording_fk(),
        UniqueConstraint("id", "tenant_id", "person_id"),
        CheckConstraint("generation >= 1", name="positive_generation"),
        CheckConstraint(
            "state IN ('quoted','active','completed','held','cancelled')", name="state"
        ),
        CheckConstraint("state <> 'active' OR acceptance_command_id IS NOT NULL", name="consent"),
        CheckConstraint("(session_id IS NULL) <> (processing_lease_id IS NULL)", name="one_actor"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    recording_id: Mapped[UUID] = mapped_column(Uuid)
    session_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("sessions.id"))
    processing_lease_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("conversation_processing_leases.id")
    )
    generation: Mapped[int] = mapped_column(Integer)
    plan_sha256: Mapped[str] = mapped_column(String(64))
    manifest: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    acceptance_command_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("conversation_commands.id")
    )
    state: Mapped[str] = mapped_column(String(16), index=True)
    progress: Mapped[dict[str, Any]] = mapped_column(JSON)
    next_check_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConversationPlanStageAuthorization(Base):
    """Derived quote authorization, never an invented per-stage user click."""

    __tablename__ = "conversation_plan_stage_authorizations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["plan_id", "tenant_id", "person_id"],
            [
                "conversation_processing_plans.id",
                "conversation_processing_plans.tenant_id",
                "conversation_processing_plans.person_id",
            ],
        ),
    )
    quote_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("conversation_quotes.id"), primary_key=True
    )
    plan_id: Mapped[UUID] = mapped_column(Uuid)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    quote_fingerprint: Mapped[str] = mapped_column(String(64))
    cache_key: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConversationReviewAssignment(Base):
    """Immutable, exact-report reviewer grant independent of learner membership."""

    __tablename__ = "conversation_review_assignments"
    __table_args__ = (
        recording_fk(),
        ForeignKeyConstraint(
            ["run_id", "tenant_id", "person_id"],
            ["conversation_runs.id", "conversation_runs.tenant_id", "conversation_runs.person_id"],
        ),
        ForeignKeyConstraint(["reviewer_id"], ["persons.id"]),
        UniqueConstraint("id", "tenant_id", "person_id", "reviewer_id"),
        CheckConstraint("expires_at > created_at", name="bounded_expiry"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    recording_id: Mapped[UUID] = mapped_column(Uuid)
    run_id: Mapped[UUID] = mapped_column(Uuid)
    reviewer_id: Mapped[UUID] = mapped_column(Uuid)
    creator_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("persons.id"))
    report_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("conversation_report_drafts.id"))
    assignment: Mapped[dict[str, Any]] = mapped_column(JSON)
    assignment_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConversationReviewInvitation(Base):
    """Immutable email invitation bound to one exact saved review run."""

    __tablename__ = "conversation_review_invitations"
    __table_args__ = (
        recording_fk(),
        ForeignKeyConstraint(
            ["run_id", "tenant_id", "person_id"],
            ["conversation_runs.id", "conversation_runs.tenant_id", "conversation_runs.person_id"],
        ),
        UniqueConstraint("token_hash"),
        CheckConstraint("length(token_hash) = 32", name="token_hash_length"),
        CheckConstraint("length(trim(invited_email)) > 3", name="invited_email_nonblank"),
        CheckConstraint("expires_at > created_at", name="bounded_expiry"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    recording_id: Mapped[UUID] = mapped_column(Uuid)
    run_id: Mapped[UUID] = mapped_column(Uuid)
    report_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("conversation_report_drafts.id"))
    invited_email: Mapped[str] = mapped_column(String(320))
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(length=32))
    encrypted_token: Mapped[str] = mapped_column(String(768))
    allowed_lenses: Mapped[list[str]] = mapped_column(JSON)
    creator_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("persons.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConversationReviewInvitationRevocation(Base):
    """Append-only cancellation decision for one pending invitation."""

    __tablename__ = "conversation_review_invitation_revocations"
    invitation_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("conversation_review_invitations.id"), primary_key=True
    )
    person_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("persons.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConversationReviewInvitationAcceptance(Base):
    """Append-only one-use link from an invitation to its created assignment."""

    __tablename__ = "conversation_review_invitation_acceptances"
    __table_args__ = (UniqueConstraint("assignment_id"),)
    invitation_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("conversation_review_invitations.id"), primary_key=True
    )
    accepted_person_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("persons.id"))
    assignment_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("conversation_review_assignments.id")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConversationReviewRevocation(Base):
    __tablename__ = "conversation_review_revocations"
    assignment_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("conversation_review_assignments.id"), primary_key=True
    )
    person_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("persons.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConversationReviewFeedback(Base):
    """Append-only feedback envelope, erasable with its source; no automatic promotion."""

    __tablename__ = "conversation_review_feedback"
    __table_args__ = (
        recording_fk(),
        ForeignKeyConstraint(
            ["assignment_id", "tenant_id", "person_id", "reviewer_id"],
            [
                "conversation_review_assignments.id",
                "conversation_review_assignments.tenant_id",
                "conversation_review_assignments.person_id",
                "conversation_review_assignments.reviewer_id",
            ],
        ),
        UniqueConstraint("assignment_id", "request_key"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    assignment_id: Mapped[UUID] = mapped_column(Uuid)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    reviewer_id: Mapped[UUID] = mapped_column(Uuid)
    recording_id: Mapped[UUID] = mapped_column(Uuid)
    request_key: Mapped[str] = mapped_column(String(128))
    request_sha256: Mapped[str] = mapped_column(String(64))
    payload_sha256: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
