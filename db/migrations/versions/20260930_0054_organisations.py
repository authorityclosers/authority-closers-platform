"""Add organisation registry, membership role, invites, and domain settings."""

import sqlalchemy as sa
from alembic import op

revision = "20260930_0054"
down_revision = "20260930_0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_memberships_role_supported"), "memberships", type_="check")
    op.create_check_constraint(
        "role_supported",
        "memberships",
        "role IN ('learner', 'support', 'admin', 'owner', 'processing', 'member')",
    )
    op.drop_constraint(
        op.f("ck_capability_grants_permission_supported"), "capability_grants", type_="check"
    )
    op.drop_constraint(
        op.f("ck_capability_grants_permission_scope"), "capability_grants", type_="check"
    )
    op.create_check_constraint(
        "permission_supported",
        "capability_grants",
        "permission IN ('platform_access_manage', 'platform_tenants_read', "
        "'platform_catalog_read', 'platform_catalog_write', 'platform_catalog_publish', "
        "'platform_organisations_manage', 'catalog_read', 'catalog_write', 'catalog_publish', "
        "'learner_diagnose', 'learning_review')",
    )
    op.create_check_constraint(
        "permission_scope",
        "capability_grants",
        "(scope_kind = 'platform' AND permission IN ('platform_access_manage', "
        "'platform_tenants_read', 'platform_catalog_read', 'platform_catalog_write', "
        "'platform_catalog_publish', 'platform_organisations_manage')) OR "
        "(scope_kind IN ('tenant', 'program') AND permission IN ('catalog_read', "
        "'catalog_write', 'catalog_publish', 'learner_diagnose', 'learning_review'))",
    )
    op.create_table(
        "organisations",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("creation_command_id", sa.Uuid(), nullable=False),
        sa.Column("domain_verification_token", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "length(domain_verification_token) >= 43",
            name=op.f("ck_organisations_domain_verification_token_min_length"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_person_id"], ["persons.id"], name="fk_organisations_created_by_person_id_persons"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_organisations_tenant_id_tenants", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_organisations")),
        sa.UniqueConstraint("creation_command_id", name=op.f("uq_organisations_creation_command_id")),
    )
    op.create_table(
        "organisation_domain_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("verified_domains", sa.JSON(), nullable=False),
        sa.Column("auto_join", sa.Boolean(), nullable=False),
        sa.Column("proof", sa.JSON(), nullable=False),
        sa.Column("actor_person_id", sa.Uuid(), nullable=True),
        sa.Column("operator_reference", sa.String(length=160), nullable=True),
        sa.Column("command_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("version >= 1", name=op.f("ck_organisation_domain_settings_version_positive")),
        sa.ForeignKeyConstraint(
            ["actor_person_id"], ["persons.id"], name="fk_organisation_domain_settings_actor_person_id_persons"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["organisations.tenant_id"], name="fk_org_domain_settings_organisation"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organisation_domain_settings")),
        sa.UniqueConstraint("command_id", name=op.f("uq_org_domain_settings_command_id")),
        sa.UniqueConstraint("tenant_id", "version", name=op.f("uq_org_domain_settings_tenant_version")),
    )
    op.create_table(
        "organisation_invites",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("email_normalized", sa.String(length=320), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("invited_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("command_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_person_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint("role IN ('admin', 'member')", name=op.f("ck_organisation_invites_role_supported")),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'revoked')",
            name=op.f("ck_organisation_invites_status_supported"),
        ),
        sa.ForeignKeyConstraint(
            ["accepted_person_id"], ["persons.id"], name="fk_organisation_invites_accepted_person_id_persons"
        ),
        sa.ForeignKeyConstraint(
            ["invited_by_person_id"], ["persons.id"], name="fk_organisation_invites_invited_by_person_id_persons"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["organisations.tenant_id"], name="fk_org_invites_organisation"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organisation_invites")),
        sa.UniqueConstraint("command_id", name=op.f("uq_org_invites_command_id")),
    )
    op.create_index(
        "uq_org_invites_pending_email",
        "organisation_invites",
        ["tenant_id", "email_normalized"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
        sqlite_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    raise RuntimeError("forward-only")
