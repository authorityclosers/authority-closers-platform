"""Create the versioned catalog with non-null scope-owner identities.

Revision ID: 20260830_0002
Revises: 20260830_0001
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0002"
down_revision: str | None = "20260830_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GLOBAL_OWNER = "00000000000000000000000000000000"


def _scope_constraints(table: str) -> tuple[sa.CheckConstraint, ...]:
    return (
        sa.CheckConstraint(
            "scope IN ('global', 'tenant')",
            name=op.f(f"ck_{table}_scope_supported_{table}"),
        ),
        sa.CheckConstraint(
            "(scope = 'global' AND tenant_id IS NULL) "
            "OR (scope = 'tenant' AND tenant_id IS NOT NULL)",
            name=op.f(f"ck_{table}_scope_tenant_match_{table}"),
        ),
        sa.CheckConstraint(
            f"(scope = 'global' AND owner_key = '{GLOBAL_OWNER}') "
            "OR (scope = 'tenant' AND owner_key = tenant_id)",
            name=op.f(f"ck_{table}_scope_owner_match_{table}"),
        ),
    )


def _install_postgresql_immutability() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        """
        CREATE FUNCTION ac_guard_published_program()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM program_versions
                WHERE program_id = OLD.id
                  AND status IN ('published', 'superseded')
            ) THEN
                RAISE EXCEPTION 'published catalog programs are immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION ac_guard_program_version_mutation()
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
    op.execute(
        """
        CREATE FUNCTION ac_guard_published_catalog_child()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            candidate_version uuid;
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                candidate_version := OLD.program_version_id;
                IF EXISTS (
                    SELECT 1 FROM program_versions
                    WHERE id = candidate_version
                      AND status IN ('published', 'superseded')
                ) THEN
                    RAISE EXCEPTION 'published catalog content is immutable'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;
            IF TG_OP <> 'DELETE' THEN
                candidate_version := NEW.program_version_id;
                IF EXISTS (
                    SELECT 1 FROM program_versions
                    WHERE id = candidate_version
                      AND status IN ('published', 'superseded')
                ) THEN
                    RAISE EXCEPTION 'published catalog content is immutable'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
                RETURN NEW;
            END IF;
            RETURN OLD;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_programs_published_immutable
        BEFORE UPDATE OR DELETE ON programs
        FOR EACH ROW EXECUTE FUNCTION ac_guard_published_program()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_program_versions_published_immutable
        BEFORE UPDATE OR DELETE ON program_versions
        FOR EACH ROW EXECUTE FUNCTION ac_guard_program_version_mutation()
        """
    )
    for table in ("modules", "module_prerequisites", "activities"):
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER trg_{table}_published_immutable
                BEFORE INSERT OR UPDATE OR DELETE ON {table}
                FOR EACH ROW EXECUTE FUNCTION ac_guard_published_catalog_child()
                """
            )
        )


def upgrade() -> None:
    op.create_table(
        "programs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "scope", sa.String(length=16), server_default=sa.text("'tenant'"), nullable=False
        ),
        sa.Column("owner_key", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_programs"),
        sa.UniqueConstraint("id", "scope", "owner_key", name="uq_programs_scope_identity"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_programs_tenant_id_tenants"
        ),
        sa.CheckConstraint("length(trim(slug)) > 0", name=op.f("ck_programs_slug_nonblank")),
        sa.CheckConstraint("length(trim(title)) > 0", name=op.f("ck_programs_title_nonblank")),
        *_scope_constraints("programs"),
    )
    op.create_index(
        "uq_programs_global_slug",
        "programs",
        ["slug"],
        unique=True,
        postgresql_where=sa.text("scope = 'global'"),
        sqlite_where=sa.text("scope = 'global'"),
    )
    op.create_index(
        "uq_programs_tenant_slug",
        "programs",
        ["tenant_id", "slug"],
        unique=True,
        postgresql_where=sa.text("scope = 'tenant'"),
        sqlite_where=sa.text("scope = 'tenant'"),
    )

    op.create_table(
        "program_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("program_id", sa.Uuid(), nullable=False),
        sa.Column(
            "scope", sa.String(length=16), server_default=sa.text("'tenant'"), nullable=False
        ),
        sa.Column("owner_key", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'draft'"), nullable=False
        ),
        sa.Column("supersedes_version_id", sa.Uuid(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_program_versions"),
        sa.UniqueConstraint(
            "id", "program_id", "scope", "owner_key", name="uq_program_versions_scope_identity"
        ),
        sa.UniqueConstraint(
            "program_id", "version_number", name="uq_program_versions_program_number"
        ),
        sa.ForeignKeyConstraint(
            ["program_id", "scope", "owner_key"],
            ["programs.id", "programs.scope", "programs.owner_key"],
            name="fk_program_versions_program_scope",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_program_versions_tenant_id_tenants"
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_version_id", "program_id", "scope", "owner_key"],
            [
                "program_versions.id",
                "program_versions.program_id",
                "program_versions.scope",
                "program_versions.owner_key",
            ],
            name="fk_program_versions_supersedes_same_program",
        ),
        sa.CheckConstraint(
            "version_number > 0", name=op.f("ck_program_versions_version_number_positive")
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'superseded')",
            name=op.f("ck_program_versions_status_supported"),
        ),
        sa.CheckConstraint(
            "published_at IS NULL OR status IN ('published', 'superseded')",
            name=op.f("ck_program_versions_published_timestamp_requires_publication"),
        ),
        sa.CheckConstraint(
            "supersedes_version_id IS NULL OR supersedes_version_id <> id",
            name=op.f("ck_program_versions_cannot_supersede_self"),
        ),
        *_scope_constraints("program_versions"),
    )
    op.create_index(
        "ix_program_versions_program_status", "program_versions", ["program_id", "status"]
    )
    op.create_index(
        "uq_program_versions_one_current_published",
        "program_versions",
        ["program_id"],
        unique=True,
        postgresql_where=sa.text("status = 'published'"),
        sqlite_where=sa.text("status = 'published'"),
    )

    op.create_table(
        "modules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("program_version_id", sa.Uuid(), nullable=False),
        sa.Column("program_id", sa.Uuid(), nullable=False),
        sa.Column(
            "scope", sa.String(length=16), server_default=sa.text("'tenant'"), nullable=False
        ),
        sa.Column("owner_key", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_modules"),
        sa.UniqueConstraint(
            "id",
            "program_version_id",
            "program_id",
            "scope",
            "owner_key",
            name="uq_modules_scope_identity",
        ),
        sa.UniqueConstraint("program_version_id", "position", name="uq_modules_version_position"),
        sa.ForeignKeyConstraint(
            ["program_version_id", "program_id", "scope", "owner_key"],
            [
                "program_versions.id",
                "program_versions.program_id",
                "program_versions.scope",
                "program_versions.owner_key",
            ],
            name="fk_modules_program_version_scope",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_modules_tenant_id_tenants"),
        sa.CheckConstraint("position > 0", name=op.f("ck_modules_position_positive")),
        sa.CheckConstraint("length(trim(title)) > 0", name=op.f("ck_modules_title_nonblank")),
        *_scope_constraints("modules"),
    )
    op.create_index("ix_modules_version_position", "modules", ["program_version_id", "position"])

    op.create_table(
        "module_prerequisites",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("program_version_id", sa.Uuid(), nullable=False),
        sa.Column("program_id", sa.Uuid(), nullable=False),
        sa.Column(
            "scope", sa.String(length=16), server_default=sa.text("'tenant'"), nullable=False
        ),
        sa.Column("owner_key", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("module_id", sa.Uuid(), nullable=False),
        sa.Column("prerequisite_module_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_module_prerequisites"),
        sa.UniqueConstraint(
            "id",
            "program_version_id",
            "program_id",
            "scope",
            "owner_key",
            name="uq_module_prerequisites_scope_identity",
        ),
        sa.UniqueConstraint(
            "module_id", "prerequisite_module_id", name="uq_module_prerequisites_edge"
        ),
        sa.ForeignKeyConstraint(
            ["program_version_id", "program_id", "scope", "owner_key"],
            [
                "program_versions.id",
                "program_versions.program_id",
                "program_versions.scope",
                "program_versions.owner_key",
            ],
            name="fk_module_prerequisites_program_version_scope",
        ),
        sa.ForeignKeyConstraint(
            ["module_id", "program_version_id", "program_id", "scope", "owner_key"],
            [
                "modules.id",
                "modules.program_version_id",
                "modules.program_id",
                "modules.scope",
                "modules.owner_key",
            ],
            name="fk_module_prerequisites_module_scope",
        ),
        sa.ForeignKeyConstraint(
            ["prerequisite_module_id", "program_version_id", "program_id", "scope", "owner_key"],
            [
                "modules.id",
                "modules.program_version_id",
                "modules.program_id",
                "modules.scope",
                "modules.owner_key",
            ],
            name="fk_module_prerequisites_required_module_scope",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_module_prerequisites_tenant_id_tenants"
        ),
        sa.CheckConstraint(
            "module_id <> prerequisite_module_id",
            name=op.f("ck_module_prerequisites_module_prerequisite_not_self"),
        ),
        *_scope_constraints("module_prerequisites"),
    )

    op.create_table(
        "activities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("module_id", sa.Uuid(), nullable=False),
        sa.Column("program_version_id", sa.Uuid(), nullable=False),
        sa.Column("program_id", sa.Uuid(), nullable=False),
        sa.Column(
            "scope", sa.String(length=16), server_default=sa.text("'tenant'"), nullable=False
        ),
        sa.Column("owner_key", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("is_required", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_activities"),
        sa.UniqueConstraint(
            "id",
            "module_id",
            "program_version_id",
            "program_id",
            "scope",
            "owner_key",
            name="uq_activities_scope_identity",
        ),
        sa.UniqueConstraint("module_id", "position", name="uq_activities_module_position"),
        sa.ForeignKeyConstraint(
            ["module_id", "program_version_id", "program_id", "scope", "owner_key"],
            [
                "modules.id",
                "modules.program_version_id",
                "modules.program_id",
                "modules.scope",
                "modules.owner_key",
            ],
            name="fk_activities_module_scope",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_activities_tenant_id_tenants"
        ),
        sa.CheckConstraint("position > 0", name=op.f("ck_activities_position_positive")),
        sa.CheckConstraint(
            "kind IN ('VIDEO', 'REFLECTION', 'IMPLEMENTATION_CHALLENGE', 'REVIEW', 'IMPROVE')",
            name=op.f("ck_activities_kind_supported"),
        ),
        sa.CheckConstraint("length(trim(title)) > 0", name=op.f("ck_activities_title_nonblank")),
        *_scope_constraints("activities"),
    )
    op.create_index("ix_activities_module_position", "activities", ["module_id", "position"])

    op.create_table(
        "learner_version_pins",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("learner_person_id", sa.Uuid(), nullable=False),
        sa.Column("program_id", sa.Uuid(), nullable=False),
        sa.Column("program_scope", sa.String(length=16), nullable=False),
        sa.Column("program_tenant_id", sa.Uuid(), nullable=True),
        sa.Column("program_owner_key", sa.Uuid(), nullable=False),
        sa.Column("program_version_id", sa.Uuid(), nullable=False),
        sa.Column(
            "pinned_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_learner_version_pins"),
        sa.UniqueConstraint(
            "tenant_id",
            "learner_person_id",
            "program_id",
            name="uq_learner_version_pins_learner_program",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "learner_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_learner_version_pins_membership",
        ),
        sa.ForeignKeyConstraint(
            ["program_tenant_id"],
            ["tenants.id"],
            name="fk_learner_version_pins_program_tenant_id_tenants",
        ),
        sa.ForeignKeyConstraint(
            ["program_id", "program_scope", "program_owner_key"],
            ["programs.id", "programs.scope", "programs.owner_key"],
            name="fk_learner_version_pins_program_scope",
        ),
        sa.ForeignKeyConstraint(
            ["program_version_id", "program_id", "program_scope", "program_owner_key"],
            [
                "program_versions.id",
                "program_versions.program_id",
                "program_versions.scope",
                "program_versions.owner_key",
            ],
            name="fk_learner_version_pins_version_scope",
        ),
        sa.CheckConstraint(
            "program_scope IN ('global', 'tenant')",
            name=op.f("ck_learner_version_pins_program_scope_supported"),
        ),
        sa.CheckConstraint(
            "(program_scope = 'global' AND program_tenant_id IS NULL) "
            "OR (program_scope = 'tenant' AND program_tenant_id IS NOT NULL)",
            name=op.f("ck_learner_version_pins_program_scope_tenant_match"),
        ),
        sa.CheckConstraint(
            f"(program_scope = 'global' AND program_owner_key = '{GLOBAL_OWNER}') "
            "OR (program_scope = 'tenant' AND program_owner_key = program_tenant_id)",
            name=op.f("ck_learner_version_pins_program_scope_owner_match"),
        ),
        sa.CheckConstraint(
            "program_scope = 'global' OR program_tenant_id = tenant_id",
            name=op.f("ck_learner_version_pins_tenant_pin_matches_program_owner"),
        ),
    )
    _install_postgresql_immutability()


def downgrade() -> None:
    raise RuntimeError("catalog migration is forward-only")
