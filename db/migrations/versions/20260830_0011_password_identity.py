"""Add the first-slice email/password identity lifecycle.

Revision ID: 20260830_0011
Revises: 20260830_0010
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0011"
down_revision: str | None = "20260830_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("persons", sa.Column("first_name", sa.String(length=120), nullable=True))
    op.add_column("persons", sa.Column("whatsapp_number", sa.String(length=32), nullable=True))
    op.add_column("persons", sa.Column("consent_version", sa.String(length=64), nullable=True))
    op.add_column("persons", sa.Column("consented_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("persons", sa.Column("experience_context", sa.String(length=64), nullable=True))
    op.add_column("persons", sa.Column("learning_goal", sa.String(length=240), nullable=True))
    op.add_column("persons", sa.Column("practice_situation", sa.String(length=500), nullable=True))
    op.add_column("persons", sa.Column("weekly_minutes", sa.Integer(), nullable=True))
    op.add_column(
        "persons",
        sa.Column(
            "onboarding_status",
            sa.String(length=24),
            server_default="not_started",
            nullable=False,
        ),
    )
    op.add_column(
        "persons",
        sa.Column("onboarding_step", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "persons",
        sa.Column("onboarding_revision", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_persons_first_name_nonblank"),
        "persons",
        "first_name IS NULL OR length(trim(first_name)) > 0",
    )
    op.create_check_constraint(
        op.f("ck_persons_whatsapp_number_min_length"),
        "persons",
        "whatsapp_number IS NULL OR length(trim(whatsapp_number)) >= 7",
    )
    op.create_check_constraint(
        op.f("ck_persons_consent_version_nonblank"),
        "persons",
        "consent_version IS NULL OR length(trim(consent_version)) > 0",
    )
    op.create_check_constraint(
        op.f("ck_persons_experience_context_nonblank"),
        "persons",
        "experience_context IS NULL OR length(trim(experience_context)) > 0",
    )
    op.create_check_constraint(
        op.f("ck_persons_learning_goal_nonblank"),
        "persons",
        "learning_goal IS NULL OR length(trim(learning_goal)) > 0",
    )
    op.create_check_constraint(
        op.f("ck_persons_practice_situation_nonblank"),
        "persons",
        "practice_situation IS NULL OR length(trim(practice_situation)) > 0",
    )
    op.create_check_constraint(
        op.f("ck_persons_weekly_minutes_bounds"),
        "persons",
        "weekly_minutes IS NULL OR weekly_minutes BETWEEN 15 AND 1200",
    )
    op.create_check_constraint(
        op.f("ck_persons_onboarding_status"),
        "persons",
        "onboarding_status IN ('not_started', 'in_progress', 'completed', 'skipped')",
    )
    op.create_check_constraint(
        op.f("ck_persons_onboarding_step_bounds"),
        "persons",
        "onboarding_step BETWEEN 1 AND 3",
    )
    op.create_check_constraint(
        op.f("ck_persons_onboarding_revision_nonnegative"),
        "persons",
        "onboarding_revision >= 0",
    )
    op.create_check_constraint(
        op.f("ck_persons_onboarding_completed_fields"),
        "persons",
        "onboarding_status <> 'completed' OR "
        "(experience_context IS NOT NULL AND learning_goal IS NOT NULL)",
    )
    duplicate_email = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM persons WHERE email IS NOT NULL "
                "GROUP BY lower(email) HAVING count(*) > 1 LIMIT 1"
            )
        )
        .first()
    )
    if duplicate_email is not None:
        raise RuntimeError(
            "case-insensitive duplicate person emails block password identity migration"
        )
    op.create_index(
        "uq_persons_email_ci",
        "persons",
        [sa.text("lower(email)")],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL"),
        sqlite_where=sa.text("email IS NOT NULL"),
    )

    op.create_table(
        "password_credentials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_password_credentials")),
        sa.UniqueConstraint("person_id", name=op.f("uq_password_credentials_person_id")),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["persons.id"],
            name=op.f("fk_password_credentials_person_id_persons"),
        ),
        sa.CheckConstraint(
            "length(trim(password_hash)) > 0",
            name=op.f("ck_password_credentials_password_hash_nonblank"),
        ),
        sa.CheckConstraint(
            "revision >= 0", name=op.f("ck_password_credentials_revision_nonnegative")
        ),
    )

    op.create_table(
        "email_challenges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("encrypted_token", sa.String(length=768), nullable=False),
        sa.Column(
            "issued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_challenges")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_email_challenges_token_hash")),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["persons.id"],
            name=op.f("fk_email_challenges_person_id_persons"),
        ),
        sa.CheckConstraint(
            "kind IN ('email_verification', 'password_reset')",
            name=op.f("ck_email_challenges_kind_supported"),
        ),
        sa.CheckConstraint(
            "length(token_hash) = 32",
            name=op.f("ck_email_challenges_token_hash_length"),
        ),
        sa.CheckConstraint(
            "length(trim(encrypted_token)) > 0",
            name=op.f("ck_email_challenges_encrypted_token_nonblank"),
        ),
        sa.CheckConstraint(
            "expires_at > issued_at",
            name=op.f("ck_email_challenges_expiry_after_issue"),
        ),
        sa.CheckConstraint(
            "consumed_at IS NULL OR consumed_at >= issued_at",
            name=op.f("ck_email_challenges_consumed_after_issue"),
        ),
    )
    op.create_index(
        "ix_email_challenges_person_kind",
        "email_challenges",
        ["person_id", "kind", "issued_at"],
    )
    op.create_index("ix_email_challenges_expiry", "email_challenges", ["expires_at"])


def downgrade() -> None:
    raise RuntimeError("password identity migration is forward-only")
