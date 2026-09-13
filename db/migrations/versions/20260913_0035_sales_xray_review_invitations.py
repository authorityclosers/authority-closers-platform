"""Canonical email invitations for exact Sales Xray review assignments.

Revision ID: 20260913_0035
Revises: 20260913_0034
"""

import sqlalchemy as sa
from alembic import op

revision = "20260913_0035"
down_revision = "20260913_0034"
branch_labels = None
depends_on = None


def _recording_fk() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["recording_id", "tenant_id", "person_id"],
        [
            "conversation_recordings.id",
            "conversation_recordings.tenant_id",
            "conversation_recordings.person_id",
        ],
    )


def upgrade() -> None:
    op.create_table(
        "conversation_review_invitations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("recording_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("invited_email", sa.String(320), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("encrypted_token", sa.String(768), nullable=False),
        sa.Column("allowed_lenses", sa.JSON(), nullable=False),
        sa.Column("creator_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        _recording_fk(),
        sa.ForeignKeyConstraint(
            ["run_id", "tenant_id", "person_id"],
            ["conversation_runs.id", "conversation_runs.tenant_id", "conversation_runs.person_id"],
        ),
        sa.ForeignKeyConstraint(["report_id"], ["conversation_report_drafts.id"]),
        sa.ForeignKeyConstraint(["creator_id"], ["persons.id"]),
        sa.UniqueConstraint("token_hash"),
        sa.CheckConstraint("length(token_hash) = 32", name="token_hash_length"),
        sa.CheckConstraint("length(trim(invited_email)) > 3", name="invited_email_nonblank"),
        sa.CheckConstraint("expires_at > created_at", name="bounded_expiry"),
    )
    op.create_table(
        "conversation_review_invitation_revocations",
        sa.Column("invitation_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("invitation_id"),
        sa.ForeignKeyConstraint(
            ["invitation_id"], ["conversation_review_invitations.id"]
        ),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"]),
    )
    op.create_table(
        "conversation_review_invitation_acceptances",
        sa.Column("invitation_id", sa.Uuid(), nullable=False),
        sa.Column("accepted_person_id", sa.Uuid(), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("invitation_id"),
        sa.ForeignKeyConstraint(
            ["invitation_id"], ["conversation_review_invitations.id"]
        ),
        sa.ForeignKeyConstraint(["accepted_person_id"], ["persons.id"]),
        sa.ForeignKeyConstraint(["assignment_id"], ["conversation_review_assignments.id"]),
        sa.UniqueConstraint("assignment_id"),
    )
    op.execute(
        sa.text("""
CREATE TRIGGER conversation_review_invitations_append_only
BEFORE UPDATE OR DELETE ON conversation_review_invitations
FOR EACH ROW EXECUTE FUNCTION prevent_conversation_command_mutation();
CREATE TRIGGER conversation_review_invitation_revocations_append_only
BEFORE UPDATE OR DELETE ON conversation_review_invitation_revocations
FOR EACH ROW EXECUTE FUNCTION prevent_conversation_command_mutation();
CREATE TRIGGER conversation_review_invitation_acceptances_append_only
BEFORE UPDATE OR DELETE ON conversation_review_invitation_acceptances
FOR EACH ROW EXECUTE FUNCTION prevent_conversation_command_mutation();
"""))


def downgrade() -> None:
    raise RuntimeError("Review invitation history is forward-only; use the verified restore path")
