"""Staff keys for the Admin command line and MCP (orchestrator's go, 19 Oct 2026).

One table, admin_staff_keys: a verified control account's key, tied to its own session
in the operations workspace. Only the SHA-256 of the key is kept. Rows are never
deleted; only last use and revocation change. A new, empty table may be rolled back.

Chain: after 20261019_0105.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261019_0106"
down_revision = "20261019_0105"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_staff_keys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("person_id", sa.Uuid(), sa.ForeignKey("persons.id"), nullable=False),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("prefix", sa.String(24), nullable=False),
        sa.Column("secret_sha256", sa.String(64), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_person_id", sa.Uuid(), sa.ForeignKey("persons.id"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("prefix", name="uq_admin_staff_key_prefix"),
        sa.UniqueConstraint("secret_sha256", name="uq_admin_staff_key_secret"),
        sa.UniqueConstraint("session_id", name="uq_admin_staff_key_session"),
        sa.CheckConstraint("length(secret_sha256) = 64", name="secret_digest"),
        sa.CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
        sa.CheckConstraint(
            "(revoked_at IS NULL) = (revoked_by_person_id IS NULL)", name="revocation_by"
        ),
    )
    op.create_index("ix_admin_staff_key_person", "admin_staff_keys", ["person_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_admin_staff_key_person", table_name="admin_staff_keys")
    op.drop_table("admin_staff_keys")
