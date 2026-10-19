"""Partner webhook tables (migration 20261018_0096, 18 Oct 2026).

Endpoints are superseded, never edited: a new URL or secret disables the old
row and adds a new one. Quote facts and events keep their minimal provenance
after erasure (ids, digests, model, token counts, times); only the payload is
emptied. Delivery attempts are append-only.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base

# The name of the environment variable holding a secret, never a secret value.
SECRET_REF_PATTERN = r"^AC_PARTNER_WEBHOOK_SECRET__[A-Z0-9_]{1,64}$"  # noqa: S105


class PartnerWebhookEndpoint(Base):
    __tablename__ = "partner_webhook_endpoints"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_partner_webhook_endpoint_tenant"
        ),
        ForeignKeyConstraint(
            ["supersedes_endpoint_id"],
            ["partner_webhook_endpoints.id"],
            name="fk_partner_webhook_endpoint_supersedes",
        ),
        CheckConstraint("status IN ('active', 'disabled')", name="status"),
        CheckConstraint("(status = 'disabled') = (disabled_at IS NOT NULL)", name="disabled"),
        # PostgreSQL regular expressions; the SQLite registry checks skip them.
        CheckConstraint(
            "url ~ '^(https://|http://(127\\.0\\.0\\.1|localhost)(:[0-9]{1,5})?(/|$))'",
            name="url",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "secret_ref ~ '^AC_PARTNER_WEBHOOK_SECRET__[A-Z0-9_]{1,64}$'"
            " AND (secret_ref_next IS NULL"
            " OR (secret_ref_next ~ '^AC_PARTNER_WEBHOOK_SECRET__[A-Z0-9_]{1,64}$'"
            " AND secret_ref_next <> secret_ref))",
            name="secret_ref",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "facts_profile IS NULL OR length(facts_profile) BETWEEN 1 AND 64", name="profile"
        ),
        CheckConstraint(
            "length(trim(created_by)) > 0 AND length(trim(reason)) > 0", name="provenance"
        ),
        Index(
            "uq_partner_webhook_endpoint_active",
            "tenant_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index("ix_partner_webhook_endpoint_tenant", "tenant_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    url: Mapped[str] = mapped_column(String(2048))
    secret_ref: Mapped[str] = mapped_column(String(100))
    secret_ref_next: Mapped[str | None] = mapped_column(String(100), nullable=True)
    events: Mapped[list[str]] = mapped_column(JSON)
    facts_profile: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16))
    events_since: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    supersedes_endpoint_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_by: Mapped[str] = mapped_column(String(160))
    reason: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PartnerQuoteFacts(Base):
    __tablename__ = "partner_quote_facts"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_partner_quote_facts_tenant"),
        ForeignKeyConstraint(
            ["recording_id"],
            ["conversation_recordings.id"],
            name="fk_partner_quote_facts_recording",
        ),
        ForeignKeyConstraint(
            ["run_id"], ["conversation_runs.id"], name="fk_partner_quote_facts_run"
        ),
        ForeignKeyConstraint(
            ["report_draft_id"],
            ["conversation_report_drafts.id"],
            name="fk_partner_quote_facts_report_draft",
        ),
        UniqueConstraint(
            "report_draft_id", "profile", "attempt", name="uq_partner_quote_facts_attempt"
        ),
        CheckConstraint("status IN ('complete', 'failed')", name="status"),
        CheckConstraint("attempt BETWEEN 1 AND 2", name="attempt"),
        CheckConstraint(
            "(payload IS NOT NULL) = (status = 'complete' AND erased_at IS NULL)", name="payload"
        ),
        CheckConstraint(
            "(payload_sha256 IS NOT NULL) = (status = 'complete')", name="payload_digest"
        ),
        CheckConstraint("(error_code IS NOT NULL) = (status = 'failed')", name="error"),
        CheckConstraint(
            "length(source_sha256) = 64 AND length(prompt_sha256) = 64"
            " AND (payload_sha256 IS NULL OR length(payload_sha256) = 64)",
            name="digests",
        ),
        Index("ix_partner_quote_facts_recording", "recording_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    recording_id: Mapped[UUID] = mapped_column(Uuid)
    run_id: Mapped[UUID] = mapped_column(Uuid)
    report_draft_id: Mapped[UUID] = mapped_column(Uuid)
    source_sha256: Mapped[str] = mapped_column(String(64))
    transcript_revision: Mapped[str] = mapped_column(String(256))
    profile: Mapped[str] = mapped_column(String(64))
    attempt: Mapped[int] = mapped_column(Integer)
    model_id: Mapped[str] = mapped_column(String(64))
    prompt_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    payload_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PartnerWebhookEvent(Base):
    __tablename__ = "partner_webhook_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["endpoint_id"],
            ["partner_webhook_endpoints.id"],
            name="fk_partner_webhook_event_endpoint",
        ),
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_partner_webhook_event_tenant"),
        ForeignKeyConstraint(
            ["recording_id"],
            ["conversation_recordings.id"],
            name="fk_partner_webhook_event_recording",
        ),
        ForeignKeyConstraint(
            ["report_draft_id"],
            ["conversation_report_drafts.id"],
            name="fk_partner_webhook_event_report_draft",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "submission_id"],
            [
                "conversation_guest_submissions.tenant_id",
                "conversation_guest_submissions.submission_id",
            ],
            name="fk_partner_webhook_event_submission",
        ),
        ForeignKeyConstraint(
            ["supersedes_event_id"],
            ["partner_webhook_events.id"],
            name="fk_partner_webhook_event_supersedes",
        ),
        UniqueConstraint("endpoint_id", "report_draft_id", name="uq_partner_webhook_event_draft"),
        CheckConstraint(
            "status IN ('pending', 'delivered', 'dead_letter', 'dropped')", name="status"
        ),
        CheckConstraint("event_type IN ('analysis.completed')", name="event_type"),
        CheckConstraint("(payload IS NULL) = (erased_at IS NOT NULL)", name="erasure"),
        CheckConstraint(
            "erased_at IS NULL OR status IN ('delivered', 'dropped')", name="erased_status"
        ),
        CheckConstraint("(status = 'delivered') = (delivered_at IS NOT NULL)", name="delivered"),
        CheckConstraint("analysis_revision >= 1", name="revision"),
        CheckConstraint(
            "attempts >= 0 AND replayed_attempts >= 0 AND replayed_attempts <= attempts",
            name="attempts",
        ),
        CheckConstraint("length(payload_sha256) = 64", name="digest"),
        CheckConstraint(
            "last_http_status IS NULL OR last_http_status BETWEEN 100 AND 599",
            name="http_status",
        ),
        Index(
            "ix_partner_webhook_event_due",
            "next_attempt_at",
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_partner_webhook_event_recording", "tenant_id", "recording_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    endpoint_id: Mapped[UUID] = mapped_column(Uuid)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    recording_id: Mapped[UUID] = mapped_column(Uuid)
    report_draft_id: Mapped[UUID] = mapped_column(Uuid)
    submission_id: Mapped[UUID] = mapped_column(Uuid)
    event_type: Mapped[str] = mapped_column(String(64))
    analysis_revision: Mapped[int] = mapped_column(Integer)
    supersedes_event_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    payload_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    attempts: Mapped[int] = mapped_column(Integer)
    replayed_attempts: Mapped[int] = mapped_column(Integer)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    leased_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PartnerWebhookAttempt(Base):
    __tablename__ = "partner_webhook_attempts"
    __table_args__ = (
        PrimaryKeyConstraint("event_id", "attempt"),
        ForeignKeyConstraint(
            ["event_id"], ["partner_webhook_events.id"], name="fk_partner_webhook_attempt_event"
        ),
        CheckConstraint("attempt >= 1", name="number"),
        CheckConstraint("duration_ms >= 0 AND finished_at >= started_at", name="timing"),
        CheckConstraint(
            "http_status IS NULL OR http_status BETWEEN 100 AND 599", name="http_status"
        ),
        CheckConstraint("http_status IS NOT NULL OR error_code IS NOT NULL", name="outcome"),
    )

    event_id: Mapped[UUID] = mapped_column(Uuid)
    attempt: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer)
