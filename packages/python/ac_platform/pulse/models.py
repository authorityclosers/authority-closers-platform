"""Pulse tables (migration 20261025_0137; contract docs/architecture/pulse-identity-contract.md).

- ``person_pulse_profiles``: the name, title, team and photo a person's Pulse account
  gives them here (one row per person; from their own sign-in or their org's link).
- ``pulse_org_links``: an organisation's link to one Pulse org. A pending row holds one
  connect attempt (state hash and sealed PKCE verifier, 10 minutes); an active row holds
  the link's sealed refresh token and webhook secret. Revoked rows stay as history.
- ``pulse_org_members``: the Pulse org's member directory as last read, each matched to
  a Sales X-Ray person by their Pulse sign-in or their verified email.
- ``app_call_uploads``: a recording an authorised app (Pulse) sent for one person. It
  waits until that person adds it to their calls in Sales X-Ray, where the usual upload
  consent, allowance and plan apply, or discards it; the bytes go after 7 days.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, deferred, mapped_column

from ac_platform.db.base import Base

PHOTO_MAX_BYTES = 65_536
LINK_STATUSES = ("pending", "active", "revoked")
UPLOAD_STATES = ("waiting", "imported", "discarded", "expired")


class PersonPulseProfile(Base):
    __tablename__ = "person_pulse_profiles"
    __table_args__ = (
        ForeignKeyConstraint(
            ["person_id"], ["persons.id"], name="fk_person_pulse_profile_person", ondelete="CASCADE"
        ),
        UniqueConstraint("person_id", name="uq_person_pulse_profile_person"),
        CheckConstraint(
            "(photo_jpeg IS NULL) = (photo_sha256 IS NULL)", name="person_pulse_profile_photo"
        ),
        CheckConstraint(
            f"photo_jpeg IS NULL OR octet_length(photo_jpeg) <= {PHOTO_MAX_BYTES}",
            name="person_pulse_profile_photo_size",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint("source IN ('sign_in', 'org_link')", name="person_pulse_profile_source"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    issuer: Mapped[str] = mapped_column(String(2048))
    subject: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(16))
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    team: Mapped[str | None] = mapped_column(String(120), nullable=True)
    handle: Mapped[str | None] = mapped_column(String(60), nullable=True)
    picture_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    photo_jpeg: Mapped[bytes | None] = deferred(mapped_column(LargeBinary, nullable=True))
    photo_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    photo_source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    photo_fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PulseOrgLink(Base):
    __tablename__ = "pulse_org_links"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_pulse_org_link_tenant"),
        CheckConstraint("status IN ('pending', 'active', 'revoked')", name="pulse_org_link_status"),
        CheckConstraint(
            "status <> 'pending' OR (state_sha256 IS NOT NULL AND sealed_verifier IS NOT NULL"
            " AND expires_at IS NOT NULL)",
            name="pulse_org_link_pending",
        ),
        CheckConstraint(
            "status <> 'active' OR (pulse_org_id IS NOT NULL AND sealed_refresh_token IS NOT NULL"
            " AND linked_at IS NOT NULL)",
            name="pulse_org_link_active",
        ),
        CheckConstraint(
            "(status = 'revoked') = (revoked_at IS NOT NULL)", name="pulse_org_link_revoked"
        ),
        # One open link or attempt per organisation, and one organisation per Pulse org.
        Index(
            "uq_pulse_org_link_tenant_open",
            "tenant_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'active')"),
            sqlite_where=text("status IN ('pending', 'active')"),
        ),
        Index(
            "uq_pulse_org_link_pulse_org",
            "issuer",
            "pulse_org_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
        Index("ix_pulse_org_link_state", "state_sha256"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    issuer: Mapped[str] = mapped_column(String(2048))
    status: Mapped[str] = mapped_column(String(12))
    pulse_org_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    pulse_org_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    scopes: Mapped[list[str]] = mapped_column(JSON)
    # What flows each way and how (Organisation -> Integrations -> Pulse), e.g.
    # {"members": "read", "photos": "read", "signals": {"calls_analysed": false, ...}}.
    sharing: Mapped[dict[str, Any]] = mapped_column(JSON)
    seal_key_id: Mapped[str] = mapped_column(String(16))
    state_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sealed_verifier: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sealed_refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    sealed_access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    webhook_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sealed_webhook_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_by_person_id: Mapped[UUID] = mapped_column(Uuid)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    linked_by_person_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync: Mapped[dict[str, Any]] = mapped_column(JSON)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[str | None] = mapped_column(String(160), nullable=True)


class PulseOrgMember(Base):
    __tablename__ = "pulse_org_members"
    __table_args__ = (
        ForeignKeyConstraint(["link_id"], ["pulse_org_links.id"], name="fk_pulse_org_member_link"),
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_pulse_org_member_tenant"),
        UniqueConstraint("link_id", "subject", name="uq_pulse_org_member_subject"),
        CheckConstraint(
            "matched_by IS NULL OR matched_by IN ('pulse_sign_in', 'email')",
            name="pulse_org_member_matched_by",
        ),
        CheckConstraint(
            "(person_id IS NULL) = (matched_by IS NULL)", name="pulse_org_member_match"
        ),
        CheckConstraint(
            "(photo_jpeg IS NULL) = (photo_sha256 IS NULL)", name="pulse_org_member_photo"
        ),
        CheckConstraint(
            f"photo_jpeg IS NULL OR octet_length(photo_jpeg) <= {PHOTO_MAX_BYTES}",
            name="pulse_org_member_photo_size",
        ).ddl_if(dialect="postgresql"),
        Index("ix_pulse_org_member_tenant", "tenant_id", "person_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    link_id: Mapped[UUID] = mapped_column(Uuid)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    subject: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    email_verified: Mapped[bool] = mapped_column(Boolean)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    team: Mapped[str | None] = mapped_column(String(120), nullable=True)
    role: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(16))
    picture_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    photo_jpeg: Mapped[bytes | None] = deferred(mapped_column(LargeBinary, nullable=True))
    photo_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    photo_source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pulse_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    person_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    matched_by: Mapped[str | None] = mapped_column(String(16), nullable=True)
    invited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AppCallUpload(Base):
    __tablename__ = "app_call_uploads"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_app_call_upload_tenant"),
        CheckConstraint(
            "state IN ('waiting', 'imported', 'discarded', 'expired')",
            name="app_call_upload_state",
        ),
        CheckConstraint("length(source_sha256) = 64", name="app_call_upload_sha256"),
        CheckConstraint("byte_size > 0 AND byte_size <= 100000000", name="app_call_upload_size"),
        CheckConstraint(
            "(state = 'imported') = (submission_id IS NOT NULL)", name="app_call_upload_imported"
        ),
        # The same app, person and external id is the same upload.
        UniqueConstraint(
            "tenant_id", "person_id", "grant_id", "external_id", name="uq_app_call_upload_external"
        ),
        Index("ix_app_call_upload_person", "tenant_id", "person_id", "state", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    grant_id: Mapped[UUID] = mapped_column(Uuid)
    app_label: Mapped[str] = mapped_column(String(80))
    external_id: Mapped[str] = mapped_column(String(120))
    source_sha256: Mapped[str] = mapped_column(String(64))
    byte_size: Mapped[int] = mapped_column(Integer)
    media_type: Mapped[str] = mapped_column(String(80))
    file_name: Mapped[str] = mapped_column(String(200))
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    call_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lead_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    consent: Mapped[str] = mapped_column(String(40))
    state: Mapped[str] = mapped_column(String(12))
    submission_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = [
    "LINK_STATUSES",
    "PHOTO_MAX_BYTES",
    "UPLOAD_STATES",
    "AppCallUpload",
    "PersonPulseProfile",
    "PulseOrgLink",
    "PulseOrgMember",
]
