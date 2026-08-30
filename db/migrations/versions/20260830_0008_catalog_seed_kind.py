"""Persist the seed kind with immutable catalog provenance."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0008"
down_revision: str | None = "20260830_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("program_versions", sa.Column("content_seed_kind", sa.String(length=64)))
    op.create_check_constraint(
        op.f("ck_program_versions_content_seed_kind_nonblank"),
        "program_versions",
        "content_seed_kind IS NULL OR length(trim(content_seed_kind)) > 0",
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
                    NEW.content_seed_kind,
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
                    OLD.content_seed_kind,
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
    raise RuntimeError("catalog seed kind migration is forward-only")
