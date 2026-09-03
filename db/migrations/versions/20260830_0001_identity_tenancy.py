"""Create the G1 identity and tenancy foundation.

Revision ID: 20260830_0001
Revises:
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "persons",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_persons"),
        sa.CheckConstraint(
            "status IN ('active', 'suspended', 'deleted')",
            name=op.f("ck_persons_status"),
        ),
        sa.CheckConstraint(
            "email IS NULL OR length(trim(email)) > 0",
            name=op.f("ck_persons_email_nonblank"),
        ),
        sa.CheckConstraint(
            "display_name IS NULL OR length(trim(display_name)) > 0",
            name=op.f("ck_persons_display_name_nonblank"),
        ),
        sa.CheckConstraint("revision >= 0", name=op.f("ck_persons_revision_nonnegative")),
    )

    op.create_table(
        "authentication_replays",
        sa.Column("replay_key", sa.String(length=1024), nullable=False),
        sa.Column(
            "consumed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("replay_key", name="pk_authentication_replays"),
        sa.CheckConstraint(
            "length(trim(replay_key)) > 0",
            name=op.f("ck_authentication_replays_replay_key_nonblank"),
        ),
        sa.CheckConstraint(
            "expires_at > consumed_at",
            name=op.f("ck_authentication_replays_expiry_after_consumption"),
        ),
    )
    op.create_index(
        "ix_authentication_replays_expires_at",
        "authentication_replays",
        ["expires_at"],
    )

    op.create_table(
        "provider_authorization_transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("authorization_type", sa.String(length=32), nullable=False),
        sa.Column("audience", sa.String(length=2048), nullable=False),
        sa.Column("state_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("nonce_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("pkce_verifier_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=True),
        sa.Column(
            "issued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'issued'"),
            nullable=False,
        ),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_provider_authorization_transactions"),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["persons.id"],
            name="fk_provider_authorization_transactions_person_id_persons",
        ),
        sa.CheckConstraint(
            "authorization_type IN ('register', 'authenticate', 'link')",
            name=op.f("ck_provider_authorization_transactions_auth_type_supported"),
        ),
        sa.CheckConstraint(
            "status IN ('issued', 'consumed')",
            name=op.f("ck_provider_authorization_transactions_status_supported"),
        ),
        sa.CheckConstraint(
            "length(state_hash) = 32",
            name=op.f("ck_provider_authorization_transactions_state_hash_length"),
        ),
        sa.CheckConstraint(
            "length(nonce_hash) = 32",
            name=op.f("ck_provider_authorization_transactions_nonce_hash_length"),
        ),
        sa.CheckConstraint(
            "length(pkce_verifier_hash) = 32",
            name=op.f("ck_provider_authorization_transactions_pkce_hash_length"),
        ),
        sa.CheckConstraint(
            "expires_at > issued_at",
            name=op.f("ck_provider_authorization_transactions_expiry_after_issue"),
        ),
        sa.CheckConstraint(
            "(status = 'issued' AND consumed_at IS NULL) OR "
            "(status = 'consumed' AND consumed_at IS NOT NULL AND consumed_at >= issued_at)",
            name=op.f("ck_provider_authorization_transactions_status_consumption"),
        ),
    )
    op.create_index(
        "ix_provider_authorization_transactions_expiry",
        "provider_authorization_transactions",
        ["expires_at"],
    )
    op.create_index(
        "ix_provider_authorization_transactions_person",
        "provider_authorization_transactions",
        ["person_id", "status"],
    )

    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=63), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tenants"),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
        sa.CheckConstraint("length(trim(slug)) > 0", name=op.f("ck_tenants_slug_nonblank")),
        sa.CheckConstraint("length(trim(name)) > 0", name=op.f("ck_tenants_name_nonblank")),
        sa.CheckConstraint(
            "status IN ('active', 'suspended', 'deleted')",
            name=op.f("ck_tenants_status"),
        ),
        sa.CheckConstraint("revision >= 0", name=op.f("ck_tenants_revision_nonnegative")),
    )

    op.create_table(
        "provider_identities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("issuer", sa.String(length=2048), nullable=False),
        sa.Column("subject", sa.String(length=512), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("last_authenticated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_provider_identities"),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["persons.id"],
            name="fk_provider_identities_person_id_persons",
        ),
        sa.UniqueConstraint(
            "issuer",
            "subject",
            name="uq_provider_identities_issuer_subject",
        ),
        sa.CheckConstraint(
            "length(trim(issuer)) > 0",
            name=op.f("ck_provider_identities_issuer_nonblank"),
        ),
        sa.CheckConstraint(
            "length(trim(subject)) > 0",
            name=op.f("ck_provider_identities_subject_nonblank"),
        ),
        sa.CheckConstraint(
            "revision >= 0",
            name=op.f("ck_provider_identities_revision_nonnegative"),
        ),
    )
    op.create_index(
        "ix_provider_identities_person_id",
        "provider_identities",
        ["person_id"],
    )

    op.create_table(
        "memberships",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role",
            sa.String(length=32),
            server_default=sa.text("'learner'"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("tenant_id", "person_id", name="pk_memberships"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_memberships_tenant_id_tenants",
        ),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["persons.id"],
            name="fk_memberships_person_id_persons",
        ),
        sa.CheckConstraint(
            "role IN ('learner', 'support', 'admin', 'owner')",
            name=op.f("ck_memberships_role_supported"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')",
            name=op.f("ck_memberships_status"),
        ),
        sa.CheckConstraint(
            "status = 'active' OR ended_at IS NOT NULL",
            name=op.f("ck_memberships_inactive_has_end"),
        ),
        sa.CheckConstraint(
            "status = 'inactive' OR ended_at IS NULL",
            name=op.f("ck_memberships_active_has_no_end"),
        ),
        sa.CheckConstraint("revision >= 0", name=op.f("ck_memberships_revision_nonnegative")),
    )
    op.create_index(
        "ix_memberships_person_status",
        "memberships",
        ["person_id", "status"],
    )
    op.create_index(
        "ix_memberships_tenant_status",
        "memberships",
        ["tenant_id", "status"],
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.String(length=200), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("selected_tenant_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_sessions"),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["persons.id"],
            name="fk_sessions_person_id_persons",
        ),
        sa.ForeignKeyConstraint(
            ["selected_tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_sessions_selected_membership",
        ),
        sa.UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
        sa.CheckConstraint(
            "length(token_hash) = 32",
            name=op.f("ck_sessions_token_hash_length"),
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name=op.f("ck_sessions_expiry_after_creation"),
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR "
            "revocation_reason IS NULL OR "
            "length(trim(revocation_reason)) > 0",
            name=op.f("ck_sessions_revocation_reason_nonblank"),
        ),
        sa.CheckConstraint("revision >= 0", name=op.f("ck_sessions_revision_nonnegative")),
    )
    op.create_index("ix_sessions_person_id", "sessions", ["person_id"])
    op.create_index("ix_sessions_selected_tenant_id", "sessions", ["selected_tenant_id"])

    op.create_table(
        "deletion_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'requested'"),
            nullable=False,
        ),
        sa.Column(
            "requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_deletion_requests"),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["persons.id"],
            name="fk_deletion_requests_person_id_persons",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_deletion_requests_scoped_membership",
        ),
        sa.CheckConstraint(
            "status IN ('requested', 'processing', 'completed', 'cancelled')",
            name=op.f("ck_deletion_requests_status"),
        ),
        sa.CheckConstraint(
            "(status IN ('requested', 'processing') "
            "AND cancelled_at IS NULL AND completed_at IS NULL) OR "
            "(status = 'cancelled' "
            "AND cancelled_at IS NOT NULL AND completed_at IS NULL "
            "AND cancelled_at >= requested_at) OR "
            "(status = 'completed' "
            "AND completed_at IS NOT NULL AND cancelled_at IS NULL "
            "AND completed_at >= requested_at)",
            name=op.f("ck_deletion_requests_status_timestamps"),
        ),
        sa.CheckConstraint(
            "revision >= 0",
            name=op.f("ck_deletion_requests_revision_nonnegative"),
        ),
    )
    op.create_index("ix_deletion_requests_person_id", "deletion_requests", ["person_id"])
    open_statuses = sa.text("status IN ('requested', 'processing')")
    op.create_index(
        "uq_deletion_requests_one_open_per_person",
        "deletion_requests",
        ["person_id"],
        unique=True,
        postgresql_where=open_statuses,
        sqlite_where=open_statuses,
    )


def downgrade() -> None:
    raise RuntimeError("identity and tenancy migrations are forward-only")
