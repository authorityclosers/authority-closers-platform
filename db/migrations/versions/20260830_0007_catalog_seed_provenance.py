"""Add immutable release and content provenance to program versions.

The fields are nullable for pre-existing catalog rows.  The staging seed
application requires them for every version it creates.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0007"
down_revision: str | None = "20260830_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("program_versions", sa.Column("content_digest", sa.String(length=64)))
    op.add_column("program_versions", sa.Column("content_source_ref", sa.String(length=500)))
    op.add_column("program_versions", sa.Column("content_reviewed_by", sa.String(length=200)))
    op.add_column(
        "program_versions",
        sa.Column("content_reviewed_at", sa.DateTime(timezone=True)),
    )
    op.add_column("program_versions", sa.Column("release_id", sa.String(length=128)))
    op.create_unique_constraint(
        "uq_program_versions_content_digest",
        "program_versions",
        ["program_id", "content_digest"],
    )
    op.create_check_constraint(
        op.f("ck_program_versions_content_digest_sha256"),
        "program_versions",
        "content_digest IS NULL OR length(content_digest) = 64",
    )
    op.create_check_constraint(
        op.f("ck_program_versions_content_source_ref_nonblank"),
        "program_versions",
        "content_source_ref IS NULL OR length(trim(content_source_ref)) > 0",
    )
    op.create_check_constraint(
        op.f("ck_program_versions_content_reviewed_by_nonblank"),
        "program_versions",
        "content_reviewed_by IS NULL OR length(trim(content_reviewed_by)) > 0",
    )
    op.create_check_constraint(
        op.f("ck_program_versions_release_id_nonblank"),
        "program_versions",
        "release_id IS NULL OR length(trim(release_id)) > 0",
    )

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION ac_guard_program_version_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    IF OLD.status IN ('published', 'superseded') THEN
                        RAISE EXCEPTION 'published catalog versions cannot be deleted'
                            USING ERRCODE = 'integrity_constraint_violation';
                    END IF;
                    RETURN OLD;
                END IF;

                IF OLD.status = 'draft' THEN
                    IF NEW.status = 'draft' THEN
                        RETURN NEW;
                    END IF;
                    IF NEW.status = 'published'
                       AND NEW.published_at IS NOT NULL
                       AND NEW.superseded_at IS NULL THEN
                        RETURN NEW;
                    END IF;
                    RAISE EXCEPTION 'unsupported draft catalog version transition'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;

                IF ROW(
                    NEW.id,
                    NEW.program_id,
                    NEW.scope,
                    NEW.owner_key,
                    NEW.tenant_id,
                    NEW.version_number,
                    NEW.supersedes_version_id,
                    NEW.published_at,
                    NEW.content_digest,
                    NEW.content_source_ref,
                    NEW.content_reviewed_by,
                    NEW.content_reviewed_at,
                    NEW.release_id,
                    NEW.created_at
                ) IS DISTINCT FROM ROW(
                    OLD.id,
                    OLD.program_id,
                    OLD.scope,
                    OLD.owner_key,
                    OLD.tenant_id,
                    OLD.version_number,
                    OLD.supersedes_version_id,
                    OLD.published_at,
                    OLD.content_digest,
                    OLD.content_source_ref,
                    OLD.content_reviewed_by,
                    OLD.content_reviewed_at,
                    OLD.release_id,
                    OLD.created_at
                ) THEN
                    RAISE EXCEPTION 'published catalog version identity is immutable'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
                IF OLD.status = 'published' AND NEW.status = 'superseded'
                   AND NEW.superseded_at IS NOT NULL THEN
                    RETURN NEW;
                END IF;
                IF NEW.status = OLD.status
                   AND NEW.superseded_at IS NOT DISTINCT FROM OLD.superseded_at THEN
                    RETURN NEW;
                END IF;
                RAISE EXCEPTION 'published catalog version transition is not allowed'
                    USING ERRCODE = 'integrity_constraint_violation';
            END;
            $$
            """
        )


def downgrade() -> None:
    raise RuntimeError("catalog provenance migration is forward-only")
