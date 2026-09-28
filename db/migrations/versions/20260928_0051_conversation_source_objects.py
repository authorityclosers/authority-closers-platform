"""Add unused source-object/reference schema; preserve tombstone history (ADR 0033)."""

from alembic import op

revision = "20260928_0051"
down_revision = "20260925_0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE conversation_source_objects (
            id uuid CONSTRAINT pk_conversation_source_objects PRIMARY KEY,
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            source_sha256 varchar(64) NOT NULL,
            created_at timestamptz NOT NULL,
            deleted_at timestamptz,
            CONSTRAINT uq_conversation_source_objects_id UNIQUE (id, tenant_id),
            CONSTRAINT ck_conversation_source_objects_sha256
                CHECK (source_sha256 ~ '^[0-9a-f]{64}$')
        );
        CREATE UNIQUE INDEX uq_source_object_live ON conversation_source_objects
            (tenant_id, source_sha256) WHERE deleted_at IS NULL;
        CREATE TABLE conversation_source_references (
            recording_id uuid CONSTRAINT pk_conversation_source_references PRIMARY KEY,
            tenant_id uuid NOT NULL,
            person_id uuid NOT NULL,
            source_object_id uuid NOT NULL,
            created_at timestamptz NOT NULL,
            released_at timestamptz,
            release_reason varchar(64),
            FOREIGN KEY (recording_id, tenant_id, person_id)
                REFERENCES conversation_recordings(id, tenant_id, person_id),
            FOREIGN KEY (source_object_id, tenant_id)
                REFERENCES conversation_source_objects(id, tenant_id),
            CONSTRAINT ck_conversation_source_references_release_pair CHECK (
                (released_at IS NULL AND release_reason IS NULL) OR
                (released_at IS NOT NULL AND release_reason IS NOT NULL
                 AND length(trim(release_reason)) > 0))
        );
        CREATE INDEX ix_source_reference_live ON conversation_source_references
            (tenant_id, source_object_id) WHERE released_at IS NULL;
        CREATE FUNCTION conversation_source_history_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'source history cannot be deleted' USING ERRCODE = '23514';
            END IF;
            IF to_jsonb(OLD)->>TG_ARGV[0] IS NOT NULL OR
               (to_jsonb(OLD) - TG_ARGV) IS DISTINCT FROM (to_jsonb(NEW) - TG_ARGV) THEN
                RAISE EXCEPTION 'source history is immutable' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER source_object_history BEFORE UPDATE OR DELETE
            ON conversation_source_objects FOR EACH ROW
            EXECUTE FUNCTION conversation_source_history_guard('deleted_at');
        CREATE TRIGGER source_reference_history BEFORE UPDATE OR DELETE
            ON conversation_source_references FOR EACH ROW
            EXECUTE FUNCTION conversation_source_history_guard('released_at', 'release_reason');
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM conversation_source_objects) OR
               EXISTS (SELECT 1 FROM conversation_source_references) THEN
                RAISE EXCEPTION 'source history must not be lost on downgrade';
            END IF;
        END $$;
        DROP TABLE conversation_source_references;
        DROP TABLE conversation_source_objects;
        DROP FUNCTION conversation_source_history_guard();
    """)
