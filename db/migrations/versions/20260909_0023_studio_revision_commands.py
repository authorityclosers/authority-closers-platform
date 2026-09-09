"""Admit immutable published-to-draft revision receipts without rewriting history."""

from alembic import op

revision = "20260909_0023"
down_revision = "20260908_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("catalog_authoring_commands") as batch:
        batch.drop_constraint(
            op.f("ck_catalog_authoring_commands_operation_supported"), type_="check"
        )
        batch.create_check_constraint(
            op.f("ck_catalog_authoring_commands_operation_supported"),
            "operation IN ('module_add', 'module_update', 'activity_add', 'activity_update', "
            "'version_revise')",
        )


def downgrade() -> None:
    raise RuntimeError("catalog revision command history is forward-only")
