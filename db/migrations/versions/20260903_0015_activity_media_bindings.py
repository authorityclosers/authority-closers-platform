"""Add tenant-scoped, append-only activity-to-media approvals.

The binding is an application-owned approval fact.  It does not activate an
object store, scanner, processor, recording path, or external media provider.
Those capabilities remain behind their existing fail-closed composition and
governance gates.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260903_0015"
down_revision: str | None = "20260902_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "activity_media_bindings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("activity_id", sa.Uuid(), nullable=False),
        sa.Column("module_id", sa.Uuid(), nullable=False),
        sa.Column("program_version_id", sa.Uuid(), nullable=False),
        sa.Column("program_id", sa.Uuid(), nullable=False),
        sa.Column("program_scope", sa.String(length=16), nullable=False),
        sa.Column("program_owner_key", sa.Uuid(), nullable=False),
        sa.Column("activity_version", sa.String(length=128), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column(
            "state",
            sa.String(length=32),
            server_default="approved",
            nullable=False,
        ),
        sa.Column("approval_reference", sa.String(length=200), nullable=False),
        sa.Column("approved_by_person_id", sa.Uuid(), nullable=False),
        sa.Column(
            "approved_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("supersedes_binding_id", sa.Uuid(), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_activity_media_bindings")),
        sa.ForeignKeyConstraint(
            [
                "activity_id",
                "module_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
            ],
            [
                "activities.id",
                "activities.module_id",
                "activities.program_version_id",
                "activities.program_id",
                "activities.scope",
                "activities.owner_key",
            ],
            name=op.f("fk_activity_media_bindings_activity_scope"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "asset_id"],
            ["media_assets.tenant_id", "media_assets.id"],
            name=op.f("fk_activity_media_bindings_asset_scope"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "asset_id", "version_id"],
            ["media_versions.tenant_id", "media_versions.asset_id", "media_versions.id"],
            name=op.f("fk_activity_media_bindings_version_scope"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "approved_by_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name=op.f("fk_activity_media_bindings_approver_membership"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "supersedes_binding_id"],
            ["activity_media_bindings.tenant_id", "activity_media_bindings.id"],
            name=op.f("fk_activity_media_bindings_supersedes_scope"),
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", name=op.f("uq_activity_media_bindings_tenant_id_id")
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "approved_by_person_id",
            "idempotency_key",
            name=op.f("uq_activity_media_bindings_idempotency"),
        ),
        sa.CheckConstraint(
            "state IN ('approved', 'superseded', 'revoked')",
            name=op.f("ck_activity_media_bindings_state_supported"),
        ),
        sa.CheckConstraint(
            "program_scope IN ('global', 'tenant')",
            name=op.f("ck_activity_media_bindings_program_scope_supported"),
        ),
        sa.CheckConstraint(
            "(program_scope = 'global' AND program_owner_key = '00000000000000000000000000000000') "
            "OR (program_scope = 'tenant' AND program_owner_key = tenant_id)",
            name=op.f("ck_activity_media_bindings_program_scope_owner_match"),
        ),
        sa.CheckConstraint(
            "length(trim(activity_version)) > 0",
            name=op.f("ck_activity_media_bindings_activity_version_nonblank"),
        ),
        sa.CheckConstraint(
            "length(trim(approval_reference)) > 0",
            name=op.f("ck_activity_media_bindings_approval_reference_nonblank"),
        ),
        sa.CheckConstraint(
            "length(trim(idempotency_key)) > 0",
            name=op.f("ck_activity_media_bindings_idempotency_key_nonblank"),
        ),
        sa.CheckConstraint(
            "length(request_fingerprint) = 64",
            name=op.f("ck_activity_media_bindings_request_fingerprint_sha256"),
        ),
    )
    op.create_index(
        op.f("ix_activity_media_bindings_activity_state"),
        "activity_media_bindings",
        ["tenant_id", "activity_id", "program_version_id", "state"],
    )
    op.create_index(
        op.f("uq_activity_media_bindings_current"),
        "activity_media_bindings",
        ["tenant_id", "activity_id", "program_version_id"],
        unique=True,
        postgresql_where=sa.text("state = 'approved'"),
        sqlite_where=sa.text("state = 'approved'"),
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            sa.text(
                """
                CREATE OR REPLACE FUNCTION prevent_activity_media_binding_mutation()
                RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.id <> OLD.id
                       OR NEW.tenant_id <> OLD.tenant_id
                       OR NEW.activity_id <> OLD.activity_id
                       OR NEW.module_id <> OLD.module_id
                       OR NEW.program_version_id <> OLD.program_version_id
                       OR NEW.program_id <> OLD.program_id
                       OR NEW.program_scope <> OLD.program_scope
                       OR NEW.program_owner_key <> OLD.program_owner_key
                       OR NEW.activity_version <> OLD.activity_version
                       OR NEW.asset_id <> OLD.asset_id
                       OR NEW.version_id <> OLD.version_id
                       OR NEW.approval_reference <> OLD.approval_reference
                       OR NEW.approved_by_person_id <> OLD.approved_by_person_id
                       OR NEW.approved_at <> OLD.approved_at
                       OR NEW.supersedes_binding_id IS DISTINCT FROM OLD.supersedes_binding_id
                       OR NEW.idempotency_key <> OLD.idempotency_key
                       OR NEW.request_fingerprint <> OLD.request_fingerprint THEN
                        RAISE EXCEPTION 'activity media binding identity is immutable';
                    END IF;
                    IF NEW.state <> OLD.state
                       AND NOT (
                           OLD.state = 'approved'
                           AND NEW.state IN ('superseded', 'revoked')
                       ) THEN
                        RAISE EXCEPTION 'activity media binding state transition is not allowed';
                    END IF;
                    RETURN NEW;
                END;
                $$
                """
            )
        )
        op.execute(
            sa.text(
                """
                CREATE TRIGGER activity_media_bindings_mutation_guard
                BEFORE UPDATE ON activity_media_bindings
                FOR EACH ROW EXECUTE FUNCTION prevent_activity_media_binding_mutation()
                """
            )
        )
        op.execute(
            sa.text(
                """
                CREATE OR REPLACE FUNCTION prevent_activity_media_binding_delete()
                RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    RAISE EXCEPTION 'activity media binding history cannot be deleted';
                END;
                $$
                """
            )
        )
        op.execute(
            sa.text(
                """
                CREATE TRIGGER activity_media_bindings_delete_guard
                BEFORE DELETE ON activity_media_bindings
                FOR EACH ROW EXECUTE FUNCTION prevent_activity_media_binding_delete()
                """
            )
        )


def downgrade() -> None:
    raise RuntimeError("activity media binding migration is forward-only")
