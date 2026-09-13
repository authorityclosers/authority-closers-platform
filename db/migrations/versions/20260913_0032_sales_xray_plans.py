"""Persist explicit bounded processing plans and derived stage authority.

Revision ID: 20260913_0032
Revises: 20260913_0031
"""

import sqlalchemy as sa
from alembic import op

revision = "20260913_0032"
down_revision = "20260913_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_processing_plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("recording_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("plan_sha256", sa.String(64), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=True),
        sa.Column("acceptance_command_id", sa.Uuid(), nullable=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("progress", sa.JSON(), nullable=False),
        sa.Column("next_check_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["recording_id", "tenant_id", "person_id"],
            [
                "conversation_recordings.id",
                "conversation_recordings.tenant_id",
                "conversation_recordings.person_id",
            ],
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.ForeignKeyConstraint(["acceptance_command_id"], ["conversation_commands.id"]),
        sa.UniqueConstraint("id", "tenant_id", "person_id"),
        sa.CheckConstraint("generation >= 1", name="positive_generation"),
        sa.CheckConstraint(
            "state IN ('quoted','active','completed','held','cancelled')", name="state"
        ),
        sa.CheckConstraint(
            "state <> 'active' OR acceptance_command_id IS NOT NULL", name="consent"
        ),
    )
    op.create_index(
        "ix_conversation_processing_plans_state", "conversation_processing_plans", ["state"]
    )
    op.create_index(
        "ix_conversation_processing_plans_next_check_at",
        "conversation_processing_plans",
        ["next_check_at"],
    )
    op.create_table(
        "conversation_plan_stage_authorizations",
        sa.Column("quote_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("quote_fingerprint", sa.String(64), nullable=False),
        sa.Column("cache_key", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("quote_id"),
        sa.ForeignKeyConstraint(["quote_id"], ["conversation_quotes.id"]),
        sa.ForeignKeyConstraint(
            ["plan_id", "tenant_id", "person_id"],
            [
                "conversation_processing_plans.id",
                "conversation_processing_plans.tenant_id",
                "conversation_processing_plans.person_id",
            ],
        ),
    )
    op.execute(
        sa.text("""
CREATE FUNCTION preserve_conversation_processing_plan() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'processing plan history is immutable'; END IF;
    IF (to_jsonb(OLD) - ARRAY['manifest','erased_at','state','progress',
                             'next_check_at','acceptance_command_id'])
       IS DISTINCT FROM
       (to_jsonb(NEW) - ARRAY['manifest','erased_at','state','progress',
                             'next_check_at','acceptance_command_id'])
       OR (OLD.acceptance_command_id IS NOT NULL AND
           OLD.acceptance_command_id IS DISTINCT FROM NEW.acceptance_command_id)
       OR (OLD.manifest::jsonb IS DISTINCT FROM NEW.manifest::jsonb AND
           (NEW.erased_at IS NULL OR
            (NEW.manifest IS NOT NULL AND NEW.manifest::jsonb <> 'null'::jsonb)))
       OR (OLD.erased_at IS NOT NULL AND
           (OLD.erased_at IS DISTINCT FROM NEW.erased_at OR
            OLD.manifest::jsonb IS DISTINCT FROM NEW.manifest::jsonb))
       OR (NEW.erased_at IS NOT NULL AND
           NEW.manifest IS NOT NULL AND NEW.manifest::jsonb <> 'null'::jsonb)
    THEN RAISE EXCEPTION 'processing plan intent and acceptance are immutable'; END IF;
    RETURN NEW;
END; $$;
CREATE TRIGGER conversation_processing_plans_immutable
BEFORE UPDATE OR DELETE ON conversation_processing_plans
FOR EACH ROW EXECUTE FUNCTION preserve_conversation_processing_plan();
CREATE TRIGGER conversation_plan_stage_authorizations_append_only
BEFORE UPDATE OR DELETE ON conversation_plan_stage_authorizations
FOR EACH ROW EXECUTE FUNCTION prevent_conversation_command_mutation();
""")
    )


def downgrade() -> None:
    raise RuntimeError("Processing consent history is forward-only; use the verified restore path")
