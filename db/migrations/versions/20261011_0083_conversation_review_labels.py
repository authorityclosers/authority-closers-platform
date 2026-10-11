"""Add append-only call review labels (AUT-1798): verdicts, notes, gold set.

One row is one reviewer statement about one call: a verdict on a section of a
run's report, a note, a gold label, a training/test data mark or a review
state. A later statement supersedes an earlier one as a new row; the
``prevent_conversation_command_mutation`` trigger from 0030 refuses every
UPDATE and DELETE. Each row names the audit event that recorded it. Purely
additive: one new table, its indexes and its trigger.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261011_0083"
down_revision = "20261011_0082"
branch_labels = None
depends_on = None

TABLE = "conversation_review_labels"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("recording_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("section", sa.String(length=96), nullable=True),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.Column("actor_person_id", sa.Uuid(), nullable=False),
        sa.Column("audit_event_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('verdict', 'note', 'gold', 'data_use', 'status')", name="kind_supported"
        ),
        sa.CheckConstraint(
            "kind <> 'verdict' OR (section IS NOT NULL AND run_id IS NOT NULL)",
            name="verdict_has_section_and_run",
        ),
        sa.CheckConstraint("section IS NULL OR length(trim(section)) > 0", name="section_nonblank"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["recording_id"], ["conversation_recordings.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["conversation_runs.id"]),
        sa.ForeignKeyConstraint(["supersedes_id"], [f"{TABLE}.id"]),
        sa.ForeignKeyConstraint(["actor_person_id"], ["persons.id"]),
        sa.ForeignKeyConstraint(["audit_event_id"], ["audit_events.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("supersedes_id", name="uq_conversation_review_labels_supersedes"),
        sa.UniqueConstraint("audit_event_id", name="uq_conversation_review_labels_audit_event"),
    )
    op.create_index("ix_conversation_review_labels_recording", TABLE, ["tenant_id", "recording_id"])
    op.create_index("ix_conversation_review_labels_kind_created", TABLE, ["kind", "created_at"])
    op.execute(
        f"CREATE TRIGGER {TABLE}_append_only BEFORE UPDATE OR DELETE "
        f"ON {TABLE} FOR EACH ROW "
        "EXECUTE FUNCTION prevent_conversation_command_mutation();"
    )


def downgrade() -> None:
    raise RuntimeError("forward-only: review labels are reviewer history")
