"""Add immutable, tenant-safe lexical knowledge snapshots."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260904_0018"
down_revision: str | None = "20260904_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _install_postgresql_guards() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    # The version digest is intentionally defined in the database as well as
    # in the Python contract.  Length-prefixing UTF-8 fields makes the digest
    # unambiguous even when a locator or passage contains separators/newlines.
    op.execute(
        """
        CREATE FUNCTION ac_knowledge_version_digest_material(candidate_version uuid)
        RETURNS text
        LANGUAGE plpgsql
        STABLE
        STRICT
        AS $$
        DECLARE
            material text := 'ac-knowledge-version-v1' || chr(10);
            chunk_row record;
        BEGIN
            FOR chunk_row IN
                SELECT ordinal, locator, passage
                  FROM knowledge_chunks
                 WHERE source_version_id = candidate_version
                 ORDER BY ordinal, id
            LOOP
                material := material
                    || 'C|' || chunk_row.ordinal::text
                    || '|'
                    || octet_length(convert_to(chunk_row.locator, 'UTF8'))::text
                    || ':' || chunk_row.locator
                    || '|'
                    || octet_length(convert_to(chunk_row.passage, 'UTF8'))::text
                    || ':' || chunk_row.passage
                    || chr(10);
            END LOOP;
            RETURN material;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION ac_knowledge_version_digest(candidate_version uuid)
        RETURNS text
        LANGUAGE sql
        STABLE
        STRICT
        AS $$
            SELECT encode(
                sha256(convert_to(ac_knowledge_version_digest_material(candidate_version), 'UTF8')),
                'hex'
            )
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION ac_guard_knowledge_version_digest()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            expected_digest text;
        BEGIN
            expected_digest := ac_knowledge_version_digest(NEW.id);
            IF NEW.content_sha256 IS DISTINCT FROM expected_digest THEN
                RAISE EXCEPTION
                    'knowledge source version digest does not match canonical content'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )

    op.execute(
        """
        CREATE FUNCTION ac_guard_knowledge_source_immutable()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'knowledge source history is immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_knowledge_sources_immutable
        BEFORE UPDATE OR DELETE ON knowledge_sources
        FOR EACH ROW EXECUTE FUNCTION ac_guard_knowledge_source_immutable()
        """
    )
    op.execute(
        """
        CREATE FUNCTION ac_guard_knowledge_version_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            predecessor record;
            latest_version_no integer;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                -- Lock the immutable source row to serialize concurrent
                -- version append attempts for one tenant/source scope.
                PERFORM 1
                  FROM knowledge_sources
                 WHERE id = NEW.source_id
                   AND tenant_id = NEW.tenant_id
                 FOR UPDATE;

                SELECT version.id,
                       version.version_no,
                       version.status,
                       version.valid_until
                  INTO predecessor
                  FROM knowledge_source_versions version
                 WHERE version.source_id = NEW.source_id
                   AND version.tenant_id = NEW.tenant_id
                 ORDER BY version.version_no DESC
                 LIMIT 1
                 FOR UPDATE;

                IF NOT FOUND THEN
                    IF NEW.version_no <> 1 OR NEW.supersedes_version_id IS NOT NULL THEN
                        RAISE EXCEPTION
                            'knowledge version chain must start at version 1 without a predecessor'
                            USING ERRCODE = 'integrity_constraint_violation';
                    END IF;
                ELSE
                    latest_version_no := predecessor.version_no;
                    IF NEW.version_no <> latest_version_no + 1
                       OR NEW.supersedes_version_id IS DISTINCT FROM predecessor.id THEN
                        RAISE EXCEPTION
                            'knowledge version must supersede the exact previous version number'
                            USING ERRCODE = 'integrity_constraint_violation';
                    END IF;
                    IF predecessor.status NOT IN ('superseded', 'withdrawn')
                       OR predecessor.valid_until IS NULL
                       OR predecessor.valid_until > CURRENT_TIMESTAMP THEN
                        RAISE EXCEPTION
                            'knowledge version predecessor must be terminal before supersession'
                            USING ERRCODE = 'integrity_constraint_violation';
                    END IF;
                END IF;

                IF NEW.status = 'active' AND NEW.valid_until IS NOT NULL THEN
                    RAISE EXCEPTION 'active knowledge versions cannot have a terminal timestamp'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
                IF NEW.status IN ('superseded', 'withdrawn')
                   AND (NEW.valid_until IS NULL OR NEW.valid_until > CURRENT_TIMESTAMP) THEN
                    RAISE EXCEPTION
                        'terminal knowledge versions require a past terminal timestamp'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
                RETURN NEW;
            END IF;
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'knowledge source versions cannot be deleted'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF TG_OP = 'UPDATE'
               AND OLD.id IS NOT DISTINCT FROM NEW.id
               AND OLD.source_id IS NOT DISTINCT FROM NEW.source_id
               AND OLD.tenant_id IS NOT DISTINCT FROM NEW.tenant_id
               AND OLD.version_no IS NOT DISTINCT FROM NEW.version_no
               AND OLD.valid_from IS NOT DISTINCT FROM NEW.valid_from
               AND (
                   (NEW.status = 'active'
                    AND OLD.valid_until IS NOT DISTINCT FROM NEW.valid_until)
                   OR (
                       NEW.status IN ('superseded', 'withdrawn')
                       AND NEW.valid_until IS NOT NULL
                       AND NEW.valid_until <= CURRENT_TIMESTAMP
                   )
               )
               AND OLD.content_sha256 IS NOT DISTINCT FROM NEW.content_sha256
               AND OLD.supersedes_version_id IS NOT DISTINCT FROM NEW.supersedes_version_id
               AND OLD.created_at IS NOT DISTINCT FROM NEW.created_at
               AND OLD.status = 'active'
               AND NEW.status IN ('active', 'superseded', 'withdrawn') THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'knowledge source version history is immutable'
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_knowledge_source_versions_immutable
        BEFORE INSERT OR UPDATE OR DELETE ON knowledge_source_versions
        FOR EACH ROW EXECUTE FUNCTION ac_guard_knowledge_version_mutation()
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_knowledge_version_digest
        AFTER INSERT OR UPDATE ON knowledge_source_versions
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION ac_guard_knowledge_version_digest()
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_knowledge_chunk_version_digest
        AFTER INSERT ON knowledge_chunks
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION ac_guard_knowledge_version_digest()
        """
    )
    op.execute(
        """
        CREATE FUNCTION ac_guard_knowledge_child_immutable()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'knowledge snapshot child history is immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    for table_name, trigger_name in (
        ("knowledge_chunks", "trg_knowledge_chunks_immutable"),
        ("knowledge_version_purposes", "trg_knowledge_version_purposes_immutable"),
        ("knowledge_chunk_acl", "trg_knowledge_chunk_acl_immutable"),
    ):
        op.execute(
            f"""
            CREATE TRIGGER {trigger_name}
            BEFORE UPDATE OR DELETE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION ac_guard_knowledge_child_immutable()
            """
        )


def upgrade() -> None:
    dialect = op.get_bind().dialect.name

    op.create_table(
        "knowledge_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("source_key", sa.String(length=256), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("provenance_uri", sa.String(length=2048), nullable=False),
        sa.Column("source_kind", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "length(trim(source_key)) > 0", name=op.f("ck_knowledge_sources_key_nonblank")
        ),
        sa.CheckConstraint(
            "length(trim(title)) > 0", name=op.f("ck_knowledge_sources_title_nonblank")
        ),
        sa.CheckConstraint(
            "length(trim(provenance_uri)) > 0", name=op.f("ck_knowledge_sources_uri_nonblank")
        ),
        sa.CheckConstraint(
            "length(trim(source_kind)) > 0", name=op.f("ck_knowledge_sources_kind_nonblank")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_knowledge_sources_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_sources")),
        sa.UniqueConstraint("id", "tenant_id", name=op.f("uq_knowledge_sources_scope_identity")),
        sa.UniqueConstraint(
            "tenant_id", "source_key", name=op.f("uq_knowledge_sources_tenant_key")
        ),
    )

    op.create_table(
        "knowledge_source_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("supersedes_version_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("version_no > 0", name=op.f("ck_knowledge_versions_positive_number")),
        sa.CheckConstraint(
            "status IN ('active', 'superseded', 'withdrawn')",
            name=op.f("ck_knowledge_versions_status_supported"),
        ),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_until > valid_from",
            name=op.f("ck_knowledge_versions_valid_window"),
        ),
        sa.CheckConstraint(
            "(status = 'active' AND valid_until IS NULL) OR "
            "(status IN ('superseded', 'withdrawn') AND valid_until IS NOT NULL)",
            name=op.f("ck_knowledge_versions_terminal_timestamp"),
        ),
        sa.CheckConstraint(
            "length(content_sha256) = 64",
            name=op.f("ck_knowledge_versions_digest_length"),
        ),
        sa.CheckConstraint(
            "content_sha256 = lower(content_sha256)",
            name=op.f("ck_knowledge_versions_digest_lowercase"),
        ),
        sa.CheckConstraint(
            "supersedes_version_id IS NULL OR supersedes_version_id <> id",
            name=op.f("ck_knowledge_versions_not_self_superseding"),
        ),
        sa.ForeignKeyConstraint(
            ["source_id", "tenant_id"],
            ["knowledge_sources.id", "knowledge_sources.tenant_id"],
            name=op.f("fk_knowledge_versions_source_scope"),
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_version_id", "source_id", "tenant_id"],
            [
                "knowledge_source_versions.id",
                "knowledge_source_versions.source_id",
                "knowledge_source_versions.tenant_id",
            ],
            name=op.f("fk_knowledge_versions_supersedes_same_source"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_source_versions")),
        sa.UniqueConstraint("id", "tenant_id", name=op.f("uq_knowledge_versions_scope_identity")),
        sa.UniqueConstraint("id", "source_id", name=op.f("uq_knowledge_versions_source_identity")),
        sa.UniqueConstraint(
            "id",
            "source_id",
            "tenant_id",
            name=op.f("uq_knowledge_versions_source_scope_identity"),
        ),
        sa.UniqueConstraint(
            "source_id", "version_no", name=op.f("uq_knowledge_versions_source_number")
        ),
    )

    op.create_table(
        "knowledge_version_purposes",
        sa.Column("source_version_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "purpose = 'support_assistance'", name=op.f("ck_knowledge_purposes_supported")
        ),
        sa.ForeignKeyConstraint(
            ["source_version_id", "tenant_id"],
            ["knowledge_source_versions.id", "knowledge_source_versions.tenant_id"],
            name=op.f("fk_knowledge_purposes_version_scope"),
        ),
        sa.PrimaryKeyConstraint(
            "source_version_id", "tenant_id", "purpose", name=op.f("pk_knowledge_version_purposes")
        ),
    )

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_version_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("locator", sa.String(length=512), nullable=False),
        sa.Column("passage", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR() if dialect == "postgresql" else sa.Text(),
            nullable=True,
        ),
        sa.CheckConstraint("ordinal >= 0", name=op.f("ck_knowledge_chunks_ordinal_nonnegative")),
        sa.CheckConstraint(
            "length(trim(locator)) > 0", name=op.f("ck_knowledge_chunks_locator_nonblank")
        ),
        sa.CheckConstraint(
            "length(trim(passage)) > 0 AND length(passage) <= 8000",
            name=op.f("ck_knowledge_chunks_passage_bound"),
        ),
        sa.CheckConstraint(
            "length(content_sha256) = 64", name=op.f("ck_knowledge_chunks_digest_length")
        ),
        sa.CheckConstraint(
            "content_sha256 = lower(content_sha256)",
            name=op.f("ck_knowledge_chunks_digest_lowercase"),
        ),
        sa.ForeignKeyConstraint(
            ["source_version_id", "tenant_id"],
            ["knowledge_source_versions.id", "knowledge_source_versions.tenant_id"],
            name=op.f("fk_knowledge_chunks_version_scope"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_chunks")),
        sa.UniqueConstraint("id", "tenant_id", name=op.f("uq_knowledge_chunks_scope_identity")),
        sa.UniqueConstraint(
            "source_version_id", "ordinal", name=op.f("uq_knowledge_chunks_version_ordinal")
        ),
    )

    op.create_table(
        "knowledge_chunk_acl",
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("acl_subject_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["chunk_id", "tenant_id"],
            ["knowledge_chunks.id", "knowledge_chunks.tenant_id"],
            name=op.f("fk_knowledge_chunk_acl_chunk_scope"),
        ),
        sa.PrimaryKeyConstraint(
            "chunk_id", "tenant_id", "acl_subject_id", name=op.f("pk_knowledge_chunk_acl")
        ),
    )

    if dialect == "postgresql":
        op.execute(
            sa.text(
                f"ALTER TABLE knowledge_source_versions ADD CONSTRAINT "
                f"{op.f('ck_knowledge_versions_digest_hex')} "
                "CHECK (content_sha256 ~ '^[0-9a-f]{64}$')"
            )
        )
        op.execute(
            sa.text(
                "ALTER TABLE knowledge_chunks ADD CONSTRAINT "
                f"{op.f('ck_knowledge_chunks_digest_matches_passage')} "
                "CHECK (content_sha256 = encode(sha256(convert_to(passage, 'UTF8')), 'hex'))"
            )
        )
        op.execute(
            sa.text(
                "CREATE UNIQUE INDEX "
                f"{op.f('uq_knowledge_versions_active_source')} "
                "ON knowledge_source_versions (tenant_id, source_id) WHERE status = 'active'"
            )
        )
        op.execute(
            sa.text(
                f"ALTER TABLE knowledge_chunks ADD CONSTRAINT "
                f"{op.f('ck_knowledge_chunks_digest_hex')} "
                "CHECK (content_sha256 ~ '^[0-9a-f]{64}$')"
            )
        )

    op.create_index(
        "ix_knowledge_chunks_tenant_version",
        "knowledge_chunks",
        ["tenant_id", "source_version_id", "ordinal"],
    )
    op.create_index(
        "ix_knowledge_versions_tenant_status",
        "knowledge_source_versions",
        ["tenant_id", "status", "valid_from"],
    )
    if dialect == "postgresql":
        op.execute(
            """
            ALTER TABLE knowledge_chunks
            DROP COLUMN search_vector
            """
        )
        op.execute(
            """
            ALTER TABLE knowledge_chunks
            ADD COLUMN search_vector tsvector
            GENERATED ALWAYS AS (to_tsvector('simple'::regconfig, passage)) STORED NOT NULL
            """
        )
        op.execute(
            """
            CREATE INDEX ix_knowledge_chunks_search_vector
            ON knowledge_chunks USING GIN (search_vector)
            """
        )
    _install_postgresql_guards()


def downgrade() -> None:
    raise RuntimeError("knowledge snapshot history is forward-only")
