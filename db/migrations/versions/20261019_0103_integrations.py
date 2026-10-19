"""Developer platform: API keys, sealed secrets and OAuth Connect (owner order, 19 Oct 2026).

The owner's order: connecting any app to Sales X-Ray is as simple as with top SaaS
apps, with no Infisical, password manager or ops step per customer. An
organisation's owners and admins make API keys (shown once, stored only as a
SHA-256) and webhooks (a signing secret made by the app, shown once and kept sealed
with AES-256-GCM under the environment's platform key) in Settings -> Integrations.
Other apps connect with OAuth 2.0 and PKCE: clients, connections (grants), one-time
codes and tokens, each code and token stored only as a SHA-256.

Rows are never deleted: a key changes only its last-used time and its one-time
revocation; a secret only its one-time retirement. New, empty tables may be rolled
back; once any row exists, history requires forward recovery.

Chain: after 20261019_0102 (partner lead events).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261019_0103"
down_revision = "20261019_0102"
branch_labels = None
depends_on = None

TABLES = (
    "integration_oauth_tokens",
    "integration_oauth_codes",
    "integration_oauth_grants",
    "integration_oauth_clients",
    "integration_secrets",
    "integration_api_keys",
)


def upgrade() -> None:
    op.create_table(
        "integration_api_keys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("prefix", sa.String(16), nullable=False),
        sa.Column("key_sha256", sa.String(64), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("created_by_person_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_person_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_integration_api_key_tenant"
        ),
        sa.UniqueConstraint("key_sha256", name="uq_integration_api_key_sha256"),
        sa.CheckConstraint("length(key_sha256) = 64", name="integration_api_key_sha256"),
        sa.CheckConstraint("length(trim(name)) BETWEEN 1 AND 80", name="integration_api_key_name"),
        sa.CheckConstraint(
            "(revoked_at IS NULL) = (revoked_by_person_id IS NULL)",
            name="integration_api_key_revoked",
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > created_at", name="integration_api_key_expiry"
        ),
    )
    op.create_index(
        "ix_integration_api_key_tenant", "integration_api_keys", ["tenant_id", "created_at"]
    )

    op.create_table(
        "integration_secrets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(24), nullable=False),
        sa.Column("sealed", sa.Text(), nullable=False),
        sa.Column("seal_key_id", sa.String(16), nullable=False),
        sa.Column("hint", sa.String(8), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("created_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_by", sa.String(160), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_integration_secret_tenant"),
        sa.CheckConstraint(
            "purpose IN ('webhook_signing', 'partner_key')", name="integration_secret_purpose"
        ),
        sa.CheckConstraint("length(seal_key_id) = 16", name="integration_secret_seal_key"),
        sa.CheckConstraint(
            "(retired_at IS NULL) = (retired_by IS NULL)", name="integration_secret_retired"
        ),
    )
    op.create_index(
        "ix_integration_secret_tenant", "integration_secrets", ["tenant_id", "created_at"]
    )

    op.create_table(
        "integration_oauth_clients",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.String(40), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("redirect_uris", sa.JSON(), nullable=False),
        sa.Column("client_secret_sha256", sa.String(64), nullable=True),
        sa.Column("created_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_integration_oauth_client_tenant"
        ),
        sa.UniqueConstraint("client_id", name="uq_integration_oauth_client_id"),
        sa.CheckConstraint(
            "client_secret_sha256 IS NULL OR length(client_secret_sha256) = 64",
            name="integration_oauth_client_secret",
        ),
    )
    op.create_index(
        "ix_integration_oauth_client_tenant",
        "integration_oauth_clients",
        ["tenant_id", "created_at"],
    )

    op.create_table(
        "integration_oauth_grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.String(40), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.String(160), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_integration_oauth_grant_tenant"
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["integration_oauth_clients.client_id"],
            name="fk_integration_oauth_grant_client",
        ),
        sa.CheckConstraint(
            "(revoked_at IS NULL) = (revoked_by IS NULL)", name="integration_oauth_grant_revoked"
        ),
    )
    op.create_index(
        "ix_integration_oauth_grant_tenant", "integration_oauth_grants", ["tenant_id", "created_at"]
    )

    op.create_table(
        "integration_oauth_codes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code_sha256", sa.String(64), nullable=False),
        sa.Column("client_id", sa.String(40), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("redirect_uri", sa.String(512), nullable=False),
        sa.Column("code_challenge", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_integration_oauth_code_tenant"
        ),
        sa.UniqueConstraint("code_sha256", name="uq_integration_oauth_code_sha256"),
        sa.CheckConstraint("expires_at > created_at", name="integration_oauth_code_expiry"),
    )

    op.create_table(
        "integration_oauth_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("grant_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("token_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["grant_id"], ["integration_oauth_grants.id"], name="fk_integration_oauth_token_grant"
        ),
        sa.UniqueConstraint("token_sha256", name="uq_integration_oauth_token_sha256"),
        sa.CheckConstraint("kind IN ('access', 'refresh')", name="integration_oauth_token_kind"),
        sa.CheckConstraint("expires_at > created_at", name="integration_oauth_token_expiry"),
    )
    op.create_index("ix_integration_oauth_token_grant", "integration_oauth_tokens", ["grant_id"])


def downgrade() -> None:
    # Fence inserts before the history check, then remove only empty tables.
    for name in TABLES:
        op.execute(sa.text(f"LOCK TABLE {name} IN ACCESS EXCLUSIVE MODE"))
    for name in TABLES:
        if op.get_bind().scalar(sa.select(sa.exists().select_from(sa.table(name)))):
            raise RuntimeError("Integration history requires forward recovery.")
    op.drop_index("ix_integration_oauth_token_grant", table_name="integration_oauth_tokens")
    op.drop_table("integration_oauth_tokens")
    op.drop_table("integration_oauth_codes")
    op.drop_index("ix_integration_oauth_grant_tenant", table_name="integration_oauth_grants")
    op.drop_table("integration_oauth_grants")
    op.drop_index("ix_integration_oauth_client_tenant", table_name="integration_oauth_clients")
    op.drop_table("integration_oauth_clients")
    op.drop_index("ix_integration_secret_tenant", table_name="integration_secrets")
    op.drop_table("integration_secrets")
    op.drop_index("ix_integration_api_key_tenant", table_name="integration_api_keys")
    op.drop_table("integration_api_keys")
