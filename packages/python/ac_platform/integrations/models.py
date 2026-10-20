"""Developer platform tables (migration 20261019_0103, owner order 19 Oct 2026).

Rows are never deleted. A key's only later changes are ``last_used_at`` (at most once a
minute) and its one-time revocation; a secret's only later change is its one-time
retirement; an OAuth code is used once; a connection (grant) and its tokens are revoked
once. Every create, revoke and retire is also an audit event in the organisation's chain.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base


class IntegrationApiKey(Base):
    """One API key of an organisation. The key itself is never stored, only its SHA-256."""

    __tablename__ = "integration_api_keys"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_integration_api_key_tenant"),
        UniqueConstraint("key_sha256", name="uq_integration_api_key_sha256"),
        CheckConstraint("length(key_sha256) = 64", name="integration_api_key_sha256"),
        CheckConstraint("length(trim(name)) BETWEEN 1 AND 80", name="integration_api_key_name"),
        CheckConstraint(
            "(revoked_at IS NULL) = (revoked_by_person_id IS NULL)",
            name="integration_api_key_revoked",
        ),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > created_at", name="integration_api_key_expiry"
        ),
        Index("ix_integration_api_key_tenant", "tenant_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(String(80))
    prefix: Mapped[str] = mapped_column(String(16))
    key_sha256: Mapped[str] = mapped_column(String(64))
    scopes: Mapped[list[str]] = mapped_column(JSON)
    created_by_person_id: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by_person_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)


class IntegrationSecret(Base):
    """A secret the app must use again, sealed with AES-256-GCM under the platform key."""

    __tablename__ = "integration_secrets"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_integration_secret_tenant"),
        CheckConstraint(
            "purpose IN ('webhook_signing', 'partner_key', 'provider_key')",
            name="integration_secret_purpose",
        ),
        CheckConstraint("length(seal_key_id) = 16", name="integration_secret_seal_key"),
        CheckConstraint(
            "(retired_at IS NULL) = (retired_by IS NULL)", name="integration_secret_retired"
        ),
        Index("ix_integration_secret_tenant", "tenant_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    purpose: Mapped[str] = mapped_column(String(24))
    sealed: Mapped[str] = mapped_column(Text)
    seal_key_id: Mapped[str] = mapped_column(String(16))
    hint: Mapped[str] = mapped_column(String(8))
    meta: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_by_person_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_by: Mapped[str | None] = mapped_column(String(160), nullable=True)


class IntegrationOAuthClient(Base):
    """An app that may ask organisations to connect (OAuth 2.0 client)."""

    __tablename__ = "integration_oauth_clients"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_integration_oauth_client_tenant"
        ),
        UniqueConstraint("client_id", name="uq_integration_oauth_client_id"),
        CheckConstraint(
            "client_secret_sha256 IS NULL OR length(client_secret_sha256) = 64",
            name="integration_oauth_client_secret",
        ),
        Index("ix_integration_oauth_client_tenant", "tenant_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    client_id: Mapped[str] = mapped_column(String(40))
    tenant_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    name: Mapped[str] = mapped_column(String(80))
    redirect_uris: Mapped[list[str]] = mapped_column(JSON)
    client_secret_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by_person_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IntegrationOAuthGrant(Base):
    """One organisation's connection to one app: who approved it and which scopes."""

    __tablename__ = "integration_oauth_grants"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_integration_oauth_grant_tenant"
        ),
        ForeignKeyConstraint(
            ["client_id"],
            ["integration_oauth_clients.client_id"],
            name="fk_integration_oauth_grant_client",
        ),
        CheckConstraint(
            "(revoked_at IS NULL) = (revoked_by IS NULL)", name="integration_oauth_grant_revoked"
        ),
        Index("ix_integration_oauth_grant_tenant", "tenant_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    client_id: Mapped[str] = mapped_column(String(40))
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    scopes: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[str | None] = mapped_column(String(160), nullable=True)


class IntegrationOAuthCode(Base):
    """A one-time authorisation code (stored as SHA-256), bound to PKCE and the address."""

    __tablename__ = "integration_oauth_codes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_integration_oauth_code_tenant"
        ),
        UniqueConstraint("code_sha256", name="uq_integration_oauth_code_sha256"),
        CheckConstraint("expires_at > created_at", name="integration_oauth_code_expiry"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    code_sha256: Mapped[str] = mapped_column(String(64))
    client_id: Mapped[str] = mapped_column(String(40))
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    person_id: Mapped[UUID] = mapped_column(Uuid)
    scopes: Mapped[list[str]] = mapped_column(JSON)
    redirect_uri: Mapped[str] = mapped_column(String(512))
    code_challenge: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IntegrationOAuthToken(Base):
    """An access (1 h) or refresh (30 d, replaced on use) token, stored as SHA-256."""

    __tablename__ = "integration_oauth_tokens"
    __table_args__ = (
        ForeignKeyConstraint(
            ["grant_id"], ["integration_oauth_grants.id"], name="fk_integration_oauth_token_grant"
        ),
        UniqueConstraint("token_sha256", name="uq_integration_oauth_token_sha256"),
        CheckConstraint("kind IN ('access', 'refresh')", name="integration_oauth_token_kind"),
        CheckConstraint("expires_at > created_at", name="integration_oauth_token_expiry"),
        Index("ix_integration_oauth_token_grant", "grant_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    grant_id: Mapped[UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(8))
    token_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
