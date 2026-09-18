"""Exact-report assignments, revocations and erasable reviewer feedback.

Revision ID: 20260913_0034
Revises: 20260913_0033
"""

import sqlalchemy as sa
from alembic import op

revision = "20260913_0034"
down_revision = "20260913_0033"
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
        "conversation_review_assignments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("recording_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=False),
        sa.Column("creator_id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("assignment", sa.JSON(), nullable=False),
        sa.Column("assignment_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        _recording_fk(),
        sa.ForeignKeyConstraint(
            ["run_id", "tenant_id", "person_id"],
            ["conversation_runs.id", "conversation_runs.tenant_id", "conversation_runs.person_id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reviewer_id"], ["memberships.tenant_id", "memberships.person_id"]
        ),
        sa.ForeignKeyConstraint(["creator_id"], ["persons.id"]),
        sa.ForeignKeyConstraint(["report_id"], ["conversation_report_drafts.id"]),
        sa.UniqueConstraint("id", "tenant_id", "person_id", "reviewer_id"),
        sa.CheckConstraint("expires_at > created_at", name="bounded_expiry"),
    )
    op.create_table(
        "conversation_review_revocations",
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("assignment_id"),
        sa.ForeignKeyConstraint(["assignment_id"], ["conversation_review_assignments.id"]),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"]),
    )
    op.create_table(
        "conversation_review_feedback",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=False),
        sa.Column("recording_id", sa.Uuid(), nullable=False),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        _recording_fk(),
        sa.ForeignKeyConstraint(
            ["assignment_id", "tenant_id", "person_id", "reviewer_id"],
            [
                "conversation_review_assignments.id",
                "conversation_review_assignments.tenant_id",
                "conversation_review_assignments.person_id",
                "conversation_review_assignments.reviewer_id",
            ],
        ),
        sa.UniqueConstraint("assignment_id", "request_key"),
    )
    op.execute(
        sa.text("""
CREATE TRIGGER conversation_review_assignments_append_only
BEFORE UPDATE OR DELETE ON conversation_review_assignments
FOR EACH ROW EXECUTE FUNCTION prevent_conversation_command_mutation();
CREATE TRIGGER conversation_review_revocations_append_only
BEFORE UPDATE OR DELETE ON conversation_review_revocations
FOR EACH ROW EXECUTE FUNCTION prevent_conversation_command_mutation();
CREATE FUNCTION preserve_conversation_review_feedback() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'review feedback history is immutable'; END IF;
    IF (to_jsonb(OLD) - ARRAY['payload','erased_at']) IS DISTINCT FROM
       (to_jsonb(NEW) - ARRAY['payload','erased_at'])
       OR NEW.erased_at IS NULL
       OR (NEW.payload IS NOT NULL AND NEW.payload::jsonb <> 'null'::jsonb)
       OR (OLD.erased_at IS NOT NULL AND
           (OLD.erased_at IS DISTINCT FROM NEW.erased_at OR
            OLD.payload::jsonb IS DISTINCT FROM NEW.payload::jsonb))
    THEN RAISE EXCEPTION 'review feedback only permits irreversible content erasure'; END IF;
    RETURN NEW;
END; $$;
CREATE TRIGGER conversation_review_feedback_immutable
BEFORE UPDATE OR DELETE ON conversation_review_feedback
FOR EACH ROW EXECUTE FUNCTION preserve_conversation_review_feedback();
""")
    )


def downgrade() -> None:
    raise RuntimeError("Review history is forward-only; use the verified restore path")
