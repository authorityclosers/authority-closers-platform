"""Reserve one durable external effect per immutable Sales Xray stage input.

Revision ID: 20260913_0031
Revises: 20260913_0030
"""

import sqlalchemy as sa
from alembic import op

revision = "20260913_0031"
down_revision = "20260913_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_inference_tasks",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("recording_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("quote_id", sa.Uuid(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(2), nullable=False),
        sa.Column("cache_key", sa.String(64), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("intent_sha256", sa.String(64), nullable=False),
        sa.Column("intent", sa.JSON(), nullable=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("checkpoint_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("run_id"),
        sa.ForeignKeyConstraint(
            ["recording_id", "tenant_id", "person_id"],
            [
                "conversation_recordings.id",
                "conversation_recordings.tenant_id",
                "conversation_recordings.person_id",
            ],
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "tenant_id", "person_id"],
            ["conversation_runs.id", "conversation_runs.tenant_id", "conversation_runs.person_id"],
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["quote_id"], ["conversation_quotes.id"]),
        sa.ForeignKeyConstraint(["checkpoint_id"], ["conversation_checkpoints.id"]),
        sa.UniqueConstraint("recording_id", "cache_key"),
        sa.UniqueConstraint("job_id"),
        sa.CheckConstraint("stage IN ('C2','C4','C5')", name="stage"),
        sa.CheckConstraint("generation >= 1", name="positive_generation"),
        sa.CheckConstraint(
            "state IN ('queued','running','completed','failed','uncertain','cancelled')",
            name="state",
        ),
    )
    op.execute(
        sa.text("""
CREATE FUNCTION preserve_conversation_inference_intent() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'inference history is immutable'; END IF;
    IF (to_jsonb(OLD) - ARRAY['intent','erased_at','state','checkpoint_id']) IS DISTINCT FROM
       (to_jsonb(NEW) - ARRAY['intent','erased_at','state','checkpoint_id'])
       OR (OLD.checkpoint_id IS NOT NULL AND OLD.checkpoint_id IS DISTINCT FROM NEW.checkpoint_id)
       OR (OLD.erased_at IS NOT NULL AND
           (OLD.erased_at IS DISTINCT FROM NEW.erased_at
            OR OLD.intent::jsonb IS DISTINCT FROM NEW.intent::jsonb))
       OR (OLD.intent::jsonb IS DISTINCT FROM NEW.intent::jsonb AND
           (NEW.erased_at IS NULL
            OR (NEW.intent IS NOT NULL AND NEW.intent::jsonb <> 'null'::jsonb)))
       OR (NEW.erased_at IS NOT NULL
           AND NEW.intent IS NOT NULL AND NEW.intent::jsonb <> 'null'::jsonb)
    THEN RAISE EXCEPTION 'inference intent only permits content erasure'; END IF;
    RETURN NEW;
END; $$;
CREATE TRIGGER conversation_inference_tasks_immutable
BEFORE UPDATE OR DELETE ON conversation_inference_tasks
FOR EACH ROW EXECUTE FUNCTION preserve_conversation_inference_intent();

CREATE FUNCTION preserve_conversation_review() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'review history is immutable'; END IF;
    IF (to_jsonb(OLD) - ARRAY['proposal','erased_at']) IS DISTINCT FROM
       (to_jsonb(NEW) - ARRAY['proposal','erased_at'])
       OR OLD.erased_at IS NOT NULL OR NEW.erased_at IS NULL
       OR (NEW.proposal IS NOT NULL AND NEW.proposal::jsonb <> 'null'::jsonb)
    THEN RAISE EXCEPTION 'review history only permits content erasure'; END IF;
    RETURN NEW;
END; $$;
CREATE TRIGGER conversation_reviews_immutable
BEFORE UPDATE OR DELETE ON conversation_reviews
FOR EACH ROW EXECUTE FUNCTION preserve_conversation_review();
""")
    )


def downgrade() -> None:
    raise RuntimeError("Inference audit history is forward-only; use the verified restore path")
