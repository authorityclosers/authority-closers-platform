"""Dedicated reviewer mailbox challenges and audience-separated sessions."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260914_0038"
down_revision: str | None = "20260914_0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Reviewer admission is a person-level grant.  Existing assignments keep
    # their reviewer identifier and history while no longer requiring that
    # person to have a learner membership in the assignment tenant.
    op.drop_constraint(
        op.f("fk_conversation_review_assignments_tenant_id_memberships"),
        "conversation_review_assignments",
        type_="foreignkey",
    )
    op.create_foreign_key(
        op.f("fk_conversation_review_assignments_reviewer_id_persons"),
        "conversation_review_assignments",
        "persons",
        ["reviewer_id"],
        ["id"],
    )

    # Existing rows are ordinary account sessions.  The database default keeps
    # old writers safe while the application starts emitting the explicit value.
    op.add_column(
        "sessions",
        sa.Column(
            "audience",
            sa.String(length=24),
            server_default="account",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f("ck_sessions_audience_supported"),
        "sessions",
        "audience IN ('account', 'reviewer')",
    )
    op.create_check_constraint(
        op.f("ck_sessions_reviewer_session_unscoped"),
        "sessions",
        "audience = 'account' OR selected_tenant_id IS NULL",
    )
    op.create_index("ix_sessions_audience", "sessions", ["audience"])

    op.create_table(
        "reviewer_auth_challenges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=True),
        sa.Column("invitation_id", sa.Uuid(), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("browser_nonce_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("encrypted_token", sa.String(length=768), nullable=False),
        sa.Column(
            "issued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reviewer_auth_challenges")),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["persons.id"],
            name=op.f("fk_reviewer_auth_challenges_person_id_persons"),
        ),
        sa.UniqueConstraint("token_hash", name=op.f("uq_reviewer_auth_challenges_token_hash")),
        sa.CheckConstraint(
            "length(trim(email)) > 3",
            name=op.f("ck_reviewer_auth_challenges_email_nonblank"),
        ),
        sa.CheckConstraint(
            "length(token_hash) = 32",
            name=op.f("ck_reviewer_auth_challenges_token_hash_length"),
        ),
        sa.CheckConstraint(
            "length(browser_nonce_hash) = 32",
            name=op.f("ck_reviewer_auth_challenges_browser_nonce_hash_length"),
        ),
        sa.CheckConstraint(
            "length(trim(encrypted_token)) > 0",
            name=op.f("ck_reviewer_auth_challenges_encrypted_token_nonblank"),
        ),
        sa.CheckConstraint(
            "expires_at > issued_at",
            name=op.f("ck_reviewer_auth_challenges_expiry_after_issue"),
        ),
        sa.CheckConstraint(
            "consumed_at IS NULL OR consumed_at >= issued_at",
            name=op.f("ck_reviewer_auth_challenges_consumed_after_issue"),
        ),
    )
    op.create_index(
        "ix_reviewer_auth_challenges_email_issued",
        "reviewer_auth_challenges",
        ["email", "issued_at"],
    )
    op.create_index(
        "ix_reviewer_auth_challenges_invitation",
        "reviewer_auth_challenges",
        ["invitation_id"],
    )
    op.create_index(
        "ix_reviewer_auth_challenges_expiry",
        "reviewer_auth_challenges",
        ["expires_at"],
    )


def downgrade() -> None:
    raise RuntimeError("reviewer identity history is forward-only")
