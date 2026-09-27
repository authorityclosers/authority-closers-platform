"""Add owner-authored private call-label revision history.

Revision ID: 20260925_0050
Revises: 20260925_0049
"""

import sqlalchemy as sa
from alembic import op

revision = "20260925_0050"
down_revision = "20260925_0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_submission_label_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=True),
        sa.Column("actor_person_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "revision >= 1",
            name=op.f("ck_conversation_submission_label_revisions_positive_revision"),
        ),
        sa.CheckConstraint(
            "display_name IS NULL OR (length(trim(display_name)) > 0 "
            "AND length(display_name) <= 120)",
            name=op.f("ck_conversation_submission_label_revisions_display_name_bounds"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "submission_id"],
            [
                "conversation_guest_submissions.tenant_id",
                "conversation_guest_submissions.submission_id",
            ],
            name=op.f(
                "fk_conversation_submission_label_revisions_tenant_id_conversation_guest_submissions"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name=op.f("fk_conversation_submission_label_revisions_tenant_id_memberships"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_submission_label_revisions")),
        sa.UniqueConstraint(
            "tenant_id",
            "submission_id",
            "revision",
            name=op.f("uq_submission_label_revision"),
        ),
    )
    op.create_index(
        "ix_submission_label_latest",
        "conversation_submission_label_revisions",
        ["tenant_id", "submission_id", "revision"],
    )
    op.create_index(
        "ix_submission_label_actor",
        "conversation_submission_label_revisions",
        ["tenant_id", "actor_person_id"],
    )


def downgrade() -> None:
    raise RuntimeError("Private call-label history is forward-only and erased by retention hooks.")
