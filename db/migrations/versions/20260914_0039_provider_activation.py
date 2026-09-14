"""Append-only provider selection for plans quoted after activation.

Revision ID: 20260914_0039
Revises: 20260914_0038
"""

import sqlalchemy as sa
from alembic import op

revision = "20260914_0039"
down_revision = "20260914_0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_provider_activations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("configuration_id", sa.Uuid(), nullable=False),
        sa.Column("configuration_revision", sa.Integer(), nullable=False),
        sa.Column("configuration_sha256", sa.String(64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_provider_activations")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name=op.f("fk_conversation_provider_activations_tenant_id_memberships"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name=op.f("fk_conversation_provider_activations_session_id_sessions"),
        ),
        sa.ForeignKeyConstraint(
            ["configuration_id"],
            ["conversation_provider_configurations.id"],
            name=op.f(
                "fk_conversation_provider_activations_configuration_id_conversation_provider_configurations"
            ),
        ),
        sa.UniqueConstraint(
            "tenant_id", "sequence", name=op.f("uq_conversation_provider_activations_tenant_id")
        ),
        sa.CheckConstraint(
            "sequence >= 1", name=op.f("ck_conversation_provider_activations_positive_sequence")
        ),
        sa.CheckConstraint(
            "configuration_revision >= 1",
            name=op.f("ck_conversation_provider_activations_positive_config_revision"),
        ),
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER conversation_provider_activations_append_only "
            "BEFORE UPDATE OR DELETE ON conversation_provider_activations "
            "FOR EACH ROW EXECUTE FUNCTION prevent_conversation_command_mutation();"
        )
    )


def downgrade() -> None:
    raise RuntimeError("Provider activation history is append-only and forward-only.")
