"""Gold reviewer assignments and append-only erasable judgements (ecff5661).

AI text and quotes stay in the canonical pointer review. Gold rows reference
that immutable version and its digest. Call erasure removes every judgement's
payload; a database trigger joins even direct pointer-review erasure to this
lifecycle. Ordinary updates/deletes of gold history are refused.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261016_0094"
down_revision = "20261016_0093"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_gold_reviewers",
        sa.Column("person_id", sa.Uuid(), sa.ForeignKey("persons.id"), primary_key=True),
        sa.Column("designated_by", sa.Uuid(), sa.ForeignKey("persons.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "conversation_gold_assignments",
        sa.Column(
            "assignment_id",
            sa.Uuid(),
            sa.ForeignKey("conversation_review_assignments.id"),
            primary_key=True,
        ),
        sa.Column(
            "recording_id", sa.Uuid(), sa.ForeignKey("conversation_recordings.id"), nullable=False
        ),
        sa.Column("reviewer_id", sa.Uuid(), sa.ForeignKey("persons.id"), nullable=False),
        sa.Column(
            "review_id", sa.Uuid(), sa.ForeignKey("conversation_pointer_reviews.id"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("recording_id", "reviewer_id", name="uq_gold_assignment_call_reviewer"),
    )
    op.create_table(
        "conversation_gold_rows",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "assignment_id",
            sa.Uuid(),
            sa.ForeignKey("conversation_gold_assignments.assignment_id"),
            nullable=False,
        ),
        sa.Column(
            "recording_id", sa.Uuid(), sa.ForeignKey("conversation_recordings.id"), nullable=False
        ),
        sa.Column(
            "review_id", sa.Uuid(), sa.ForeignKey("conversation_pointer_reviews.id"), nullable=False
        ),
        sa.Column("reviewer_id", sa.Uuid(), sa.ForeignKey("persons.id"), nullable=False),
        sa.Column("target", sa.String(96), nullable=False),
        sa.Column("ai_sha256", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("supersedes_id", sa.Uuid(), sa.ForeignKey("conversation_gold_rows.id")),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("erased_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("assignment_id", "request_key", name="uq_gold_row_request"),
        sa.UniqueConstraint("supersedes_id", name="uq_gold_row_supersedes"),
        sa.CheckConstraint("length(target) BETWEEN 1 AND 96", name="gold_target"),
        sa.CheckConstraint(
            "length(ai_sha256) = 64 AND length(request_sha256) = 64", name="gold_digests"
        ),
        sa.CheckConstraint("(erased_at IS NULL) = (payload IS NOT NULL)", name="gold_erasure"),
    )
    op.create_index("ix_gold_row_call", "conversation_gold_rows", ["recording_id", "created_at"])
    op.execute("""
      CREATE FUNCTION ac_gold_history_guard() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF TG_OP = 'UPDATE' AND OLD.erased_at IS NULL AND NEW.erased_at IS NOT NULL
           AND NEW.payload IS NULL
           AND (to_jsonb(OLD) - 'payload' - 'erased_at') =
               (to_jsonb(NEW) - 'payload' - 'erased_at')
           AND EXISTS (SELECT 1 FROM conversation_recordings c WHERE c.id = OLD.recording_id
                       AND c.state IN ('deleting', 'deleted')) THEN
          RETURN NEW;
        END IF;
        RAISE EXCEPTION 'Gold history is append-only; supersede or erase with the call';
      END $$;
      CREATE TRIGGER ac_gold_history_guard BEFORE UPDATE OR DELETE ON conversation_gold_rows
        FOR EACH ROW EXECUTE FUNCTION ac_gold_history_guard();
      CREATE FUNCTION ac_gold_pointer_erasure() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF NEW.erased_at IS NOT NULL THEN
          UPDATE conversation_gold_rows SET payload = NULL, erased_at = NEW.erased_at
            WHERE recording_id = NEW.recording_id AND erased_at IS NULL;
        END IF;
        RETURN NEW;
      END $$;
      CREATE TRIGGER ac_gold_pointer_erasure
        AFTER UPDATE OF erased_at ON conversation_pointer_reviews
        FOR EACH ROW EXECUTE FUNCTION ac_gold_pointer_erasure();
    """)


def downgrade() -> None:
    op.execute(
        "LOCK TABLE conversation_gold_rows, conversation_gold_assignments, "
        "conversation_gold_reviewers IN ACCESS EXCLUSIVE MODE"
    )
    for name in (
        "conversation_gold_rows",
        "conversation_gold_assignments",
        "conversation_gold_reviewers",
    ):
        if op.get_bind().scalar(sa.select(sa.exists().select_from(sa.table(name)))):
            raise RuntimeError("Gold reviewer history requires forward recovery.")
    op.execute(
        "DROP TRIGGER ac_gold_pointer_erasure ON conversation_pointer_reviews; "
        "DROP FUNCTION ac_gold_pointer_erasure(); "
        "DROP FUNCTION ac_gold_history_guard() CASCADE"
    )
    op.drop_table("conversation_gold_rows")
    op.drop_table("conversation_gold_assignments")
    op.drop_table("conversation_gold_reviewers")
