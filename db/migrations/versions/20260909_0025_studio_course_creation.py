"""Admit atomic course/draft creation receipts without altering existing history."""

from alembic import op

revision = "20260909_0025"
down_revision = "20260909_0024"
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
            "'version_revise', 'program_create')",
        )


def downgrade() -> None:
    raise RuntimeError("course creation command history is forward-only")
