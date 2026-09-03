"""Serialize catalog publication with child writes and verify reviewed content.

Revision ID: 20260830_0010
Revises: 20260830_0009
"""

# ruff: noqa: S608 -- trigger DDL interpolates only fixed migration-owned table names.

from __future__ import annotations

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0010"
down_revision: str | None = "20260830_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _technical_validation_allowed_sql() -> str:
    """Return a fixed SQL boolean; missing/unknown environments fail closed."""

    environment = os.getenv("AC_ENVIRONMENT", "").strip().lower()
    return "TRUE" if environment in {"staging", "test"} else "FALSE"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    technical_validation_allowed = _technical_validation_allowed_sql()
    # Keep the legacy-row audit and trigger replacement in one write-quiescent
    # transaction. Otherwise a 0009 writer could publish between the audit and
    # the installation of the 0010 guards.
    op.execute(
        sa.text(
            """
            LOCK TABLE programs, program_versions, modules,
                       module_prerequisites, activities
            IN ACCESS EXCLUSIVE MODE
            """
        )
    )
    op.execute(
        sa.text(
            r"""
            CREATE OR REPLACE FUNCTION ac_catalog_content_digest(candidate_version uuid)
            RETURNS text
            LANGUAGE plpgsql
            STABLE
            STRICT
            AS $$
            DECLARE
                material text := 'ac-catalog-content-v1' || chr(10);
                program_slug text;
                program_title text;
                module_row record;
                activity_row record;
                prerequisite_positions text;
            BEGIN
                SELECT program.slug, program.title
                  INTO program_slug, program_title
                  FROM program_versions version
                  JOIN programs program ON program.id = version.program_id
                 WHERE version.id = candidate_version;
                IF NOT FOUND THEN
                    RETURN NULL;
                END IF;

                material := material
                    || 'P|'
                    || octet_length(convert_to(program_slug, 'UTF8'))::text
                    || ':' || program_slug
                    || '|'
                    || octet_length(convert_to(program_title, 'UTF8'))::text
                    || ':' || program_title
                    || chr(10);

                FOR module_row IN
                    SELECT module.id, module.position, module.title
                      FROM modules module
                     WHERE module.program_version_id = candidate_version
                     ORDER BY module.position, module.id
                LOOP
                    SELECT string_agg(prerequisite_module.position::text, ','
                                      ORDER BY prerequisite_module.position)
                      INTO prerequisite_positions
                      FROM module_prerequisites edge
                      JOIN modules prerequisite_module
                        ON prerequisite_module.id = edge.prerequisite_module_id
                     WHERE edge.program_version_id = candidate_version
                       AND edge.module_id = module_row.id;

                    material := material
                        || 'M|' || module_row.position::text
                        || '|'
                        || octet_length(convert_to(module_row.title, 'UTF8'))::text
                        || ':' || module_row.title
                        || '|R[' || coalesce(prerequisite_positions, '') || ']'
                        || chr(10);

                    FOR activity_row IN
                        SELECT activity.position,
                               activity.kind,
                               activity.title,
                               activity.is_required,
                               activity.prompt
                          FROM activities activity
                         WHERE activity.program_version_id = candidate_version
                           AND activity.module_id = module_row.id
                         ORDER BY activity.position, activity.id
                    LOOP
                        material := material
                            || 'A|' || module_row.position::text
                            || '|' || activity_row.position::text
                            || '|'
                            || octet_length(convert_to(activity_row.kind, 'UTF8'))::text
                            || ':' || activity_row.kind
                            || '|'
                            || octet_length(convert_to(activity_row.title, 'UTF8'))::text
                            || ':' || activity_row.title
                            || '|' || CASE WHEN activity_row.is_required THEN '1' ELSE '0' END
                            || '|'
                            || CASE
                                WHEN activity_row.prompt IS NULL THEN 'N'
                                ELSE 'S'
                                    || octet_length(convert_to(activity_row.prompt, 'UTF8'))::text
                                    || ':' || activity_row.prompt
                               END
                            || chr(10);
                    END LOOP;
                END LOOP;

                RETURN encode(sha256(convert_to(material, 'UTF8')), 'hex');
            END;
            $$
            """
        )
    )
    # Migration 0009 allowed provenance columns to remain empty on already
    # immutable rows. Refuse to install stronger guards over unverifiable
    # history: silently grandfathering it would make the new invariant false.
    op.execute(
        sa.text(
            f"""
            DO $$
            DECLARE
                invalid_version_id uuid;
            BEGIN
                SELECT version.id
                  INTO invalid_version_id
                  FROM program_versions version
                 WHERE version.status IN ('published', 'superseded')
                   AND (
                       version.published_at IS NULL
                       OR (
                           version.status = 'published'
                           AND version.superseded_at IS NOT NULL
                       )
                       OR (
                           version.status = 'superseded'
                           AND version.superseded_at IS NULL
                       )
                       OR version.content_digest IS NULL
                       OR version.content_digest !~ '^[0-9a-f]{{64}}$'
                       OR version.content_source_ref IS NULL
                       OR length(trim(version.content_source_ref)) = 0
                       OR version.content_reviewed_by IS NULL
                       OR length(trim(version.content_reviewed_by)) = 0
                       OR version.content_reviewed_at IS NULL
                       OR version.release_id IS NULL
                       OR version.release_id !~ '^[0-9a-f]{{40}}$'
                       OR version.content_seed_kind IS NULL
                       OR version.content_seed_kind NOT IN (
                           'reviewed',
                           'technical-validation'
                       )
                       OR (
                           version.content_seed_kind = 'technical-validation'
                           AND NOT {technical_validation_allowed}
                       )
                       OR version.content_digest IS DISTINCT FROM
                          ac_catalog_content_digest(version.id)
                   )
                 ORDER BY version.id
                 LIMIT 1;

                IF invalid_version_id IS NOT NULL THEN
                    RAISE EXCEPTION
                        'catalog publication integrity upgrade refused legacy version %',
                        invalid_version_id
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text(
            r"""
            CREATE OR REPLACE FUNCTION ac_guard_published_program()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            DECLARE
                candidate_status text;
            BEGIN
                FOR candidate_status IN
                    SELECT version.status
                      FROM program_versions version
                     WHERE version.program_id = OLD.id
                     ORDER BY version.id
                     FOR UPDATE OF version
                LOOP
                    IF candidate_status IN ('published', 'superseded') THEN
                        RAISE EXCEPTION 'published catalog programs are immutable'
                            USING ERRCODE = 'integrity_constraint_violation';
                    END IF;
                END LOOP;
                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                RETURN NEW;
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            CREATE OR REPLACE FUNCTION ac_guard_program_version_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            DECLARE
                computed_digest text;
            BEGIN
                IF TG_OP = 'INSERT' THEN
                    IF NEW.status <> 'draft' THEN
                        RAISE EXCEPTION 'catalog versions must be created as drafts'
                            USING ERRCODE = 'integrity_constraint_violation';
                    END IF;
                    RETURN NEW;
                END IF;

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
                        IF ROW(
                            NEW.id,
                            NEW.program_id,
                            NEW.scope,
                            NEW.owner_key,
                            NEW.tenant_id,
                            NEW.version_number,
                            NEW.supersedes_version_id,
                            NEW.created_at
                        ) IS DISTINCT FROM ROW(
                            OLD.id,
                            OLD.program_id,
                            OLD.scope,
                            OLD.owner_key,
                            OLD.tenant_id,
                            OLD.version_number,
                            OLD.supersedes_version_id,
                            OLD.created_at
                        ) THEN
                            RAISE EXCEPTION
                                'catalog version identity cannot change during publication'
                                USING ERRCODE = 'integrity_constraint_violation';
                        END IF;
                        IF NEW.content_digest IS NULL
                           OR NEW.content_digest !~ '^[0-9a-f]{{64}}$'
                           OR NEW.content_source_ref IS NULL
                           OR length(trim(NEW.content_source_ref)) = 0
                           OR NEW.content_reviewed_by IS NULL
                           OR length(trim(NEW.content_reviewed_by)) = 0
                           OR NEW.content_reviewed_at IS NULL
                           OR NEW.release_id IS NULL
                           OR NEW.release_id !~ '^[0-9a-f]{{40}}$'
                           OR NEW.content_seed_kind IS NULL
                           OR NEW.content_seed_kind NOT IN ('reviewed', 'technical-validation') THEN
                            RAISE EXCEPTION 'catalog publication requires complete valid provenance'
                                USING ERRCODE = 'integrity_constraint_violation';
                        END IF;
                        IF NEW.content_seed_kind = 'technical-validation'
                           AND NOT {technical_validation_allowed} THEN
                            RAISE EXCEPTION
                                'technical-validation publication is disabled in this environment'
                                USING ERRCODE = 'integrity_constraint_violation';
                        END IF;
                        computed_digest := ac_catalog_content_digest(OLD.id);
                        IF computed_digest IS NULL OR NEW.content_digest <> computed_digest THEN
                            RAISE EXCEPTION 'catalog publication content digest is stale or invalid'
                                USING ERRCODE = 'integrity_constraint_violation';
                        END IF;
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
    )
    op.execute(
        sa.text(
            r"""
            CREATE OR REPLACE FUNCTION ac_guard_published_catalog_child()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            DECLARE
                candidate_versions uuid[] := ARRAY[]::uuid[];
                candidate_program_id uuid;
                candidate_status text;
            BEGIN
                IF TG_OP <> 'INSERT' THEN
                    candidate_versions := array_append(
                        candidate_versions,
                        OLD.program_version_id
                    );
                END IF;
                IF TG_OP <> 'DELETE' THEN
                    candidate_versions := array_append(
                        candidate_versions,
                        NEW.program_version_id
                    );
                END IF;

                FOR candidate_program_id IN
                    SELECT program.id
                      FROM programs program
                     WHERE program.id IN (
                        SELECT version.program_id
                          FROM program_versions version
                         WHERE version.id = ANY(candidate_versions)
                     )
                     ORDER BY program.id
                     FOR UPDATE OF program
                LOOP
                    NULL;
                END LOOP;

                FOR candidate_status IN
                    SELECT version.status
                      FROM program_versions version
                     WHERE version.id = ANY(candidate_versions)
                     ORDER BY version.id
                     FOR UPDATE OF version
                LOOP
                    IF candidate_status IN ('published', 'superseded') THEN
                        RAISE EXCEPTION 'published catalog content is immutable'
                            USING ERRCODE = 'integrity_constraint_violation';
                    END IF;
                END LOOP;

                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                RETURN NEW;
            END;
            $$
            """
        )
    )

    op.execute(sa.text("DROP TRIGGER trg_program_versions_published_immutable ON program_versions"))
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_program_versions_published_immutable
            BEFORE INSERT OR UPDATE OR DELETE ON program_versions
            FOR EACH ROW EXECUTE FUNCTION ac_guard_program_version_mutation()
            """
        )
    )
    for table in ("modules", "module_prerequisites", "activities"):
        op.execute(sa.text(f"DROP TRIGGER trg_{table}_published_immutable ON {table}"))
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER trg_{table}_published_immutable
                BEFORE INSERT OR UPDATE OR DELETE ON {table}
                FOR EACH ROW EXECUTE FUNCTION ac_guard_published_catalog_child()
                """
            )
        )


def downgrade() -> None:
    raise RuntimeError("catalog publication integrity migration is forward-only")
