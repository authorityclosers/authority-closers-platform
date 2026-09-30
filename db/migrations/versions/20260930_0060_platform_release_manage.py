"""Add the explicit platform release-management capability."""

from alembic import op

revision = "20260930_0060"
down_revision = "20260930_0054"
branch_labels = None
depends_on = None


def upgrade() -> None:
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
        "'platform_organisations_manage', 'platform_release_manage', "
        "'catalog_read', 'catalog_write', 'catalog_publish', 'learner_diagnose', "
        "'learning_review')",
    )
    op.create_check_constraint(
        "permission_scope",
        "capability_grants",
        "(scope_kind = 'platform' AND permission IN ('platform_access_manage', "
        "'platform_tenants_read', 'platform_catalog_read', 'platform_catalog_write', "
        "'platform_catalog_publish', 'platform_organisations_manage', "
        "'platform_release_manage')) OR "
        "(scope_kind IN ('tenant', 'program') AND permission IN ('catalog_read', "
        "'catalog_write', 'catalog_publish', 'learner_diagnose', 'learning_review'))",
    )


def downgrade() -> None:
    raise RuntimeError("forward-only")
