"""Purpose-specific email code sign-in challenges.

Revision ID: 20260923_0045
Revises: 20260923_0044
"""

import sqlalchemy as sa
from alembic import op

revision = "20260923_0045"
down_revision = "20260923_0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_login_codes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("generation_id", sa.Uuid(), nullable=False),
        sa.Column("normalized_email", sa.String(length=320), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("encrypted_code", sa.String(length=256), nullable=False),
        sa.Column("consent_version", sa.String(length=64), nullable=True),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("send_window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sends_in_window", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("length(trim(normalized_email)) > 0", name="email_nonblank"),
        sa.CheckConstraint("length(token_hash) = 32", name="token_hash_length"),
        sa.CheckConstraint("length(trim(encrypted_code)) > 0", name="encrypted_code_nonblank"),
        sa.CheckConstraint("expires_at > issued_at", name="expiry_after_issue"),
        sa.CheckConstraint(
            "consumed_at IS NULL OR consumed_at >= issued_at",
            name="consumed_after_issue",
        ),
        sa.CheckConstraint("failed_attempts BETWEEN 0 AND 5", name="failed_attempts_bounds"),
        sa.CheckConstraint("sends_in_window BETWEEN 1 AND 5", name="sends_in_window_bounds"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_email", name="uq_email_login_codes_email"),
        sa.UniqueConstraint("generation_id", name="uq_email_login_codes_generation"),
    )
    op.create_index(
        "ix_email_login_codes_expiry",
        "email_login_codes",
        ["expires_at"],
    )


def downgrade() -> None:
    raise RuntimeError("Email login challenge history is forward-only.")
