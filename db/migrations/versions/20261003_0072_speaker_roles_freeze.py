"""Permit exactly one names-free speaker-role freeze on an existing plan."""

from alembic import op

revision = "20261003_0072"
down_revision = "20261003_0071"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("""
CREATE OR REPLACE FUNCTION preserve_conversation_processing_plan()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'processing plan history is immutable'; END IF;
    IF (to_jsonb(OLD) - ARRAY['manifest','erased_at','state','progress',
                             'next_check_at','acceptance_command_id','speaker_roles'])
       IS DISTINCT FROM
       (to_jsonb(NEW) - ARRAY['manifest','erased_at','state','progress',
                             'next_check_at','acceptance_command_id','speaker_roles'])
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

    IF OLD.speaker_roles::jsonb IS DISTINCT FROM NEW.speaker_roles::jsonb AND NOT (
        (OLD.speaker_roles IS NULL AND OLD.erased_at IS NULL AND NEW.erased_at IS NULL
         AND (OLD.progress->'speaker_roles_frozen')::jsonb IS DISTINCT FROM 'true'::jsonb
         AND (NEW.progress->'speaker_roles_frozen')::jsonb IS NOT DISTINCT FROM 'true'::jsonb)
        OR (NEW.erased_at IS NOT NULL AND NEW.speaker_roles IS NULL)
    ) THEN RAISE EXCEPTION 'processing plan speaker roles are frozen'; END IF;
    IF (OLD.progress->'speaker_roles_frozen')::jsonb = 'true'::jsonb
       AND (NEW.progress->'speaker_roles_frozen')::jsonb IS DISTINCT FROM 'true'::jsonb
       AND NEW.erased_at IS NULL
    THEN RAISE EXCEPTION 'processing plan speaker roles are frozen'; END IF;
    RETURN NEW;
END; $$;
    """)


def downgrade() -> None:
    raise RuntimeError("Speaker-role freezing is forward-only; erasure clears private content.")
