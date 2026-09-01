"""Add indexed identity command idempotency state.

Revision ID: 20260901_0012
Revises: 20260830_0011
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260901_0012"
down_revision: str | None = "20260830_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "identity_command_idempotency",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("actor_person_id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("key_digest", sa.String(length=64), nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("result_revision", sa.Integer(), nullable=True),
        sa.Column("result_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_identity_command_idempotency")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name=op.f("fk_identity_command_idempotency_actor_membership"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "actor_person_id",
            "operation",
            "key_digest",
            name=op.f("uq_identity_command_idempotency_scope_key"),
        ),
        sa.CheckConstraint(
            "operation = 'onboarding_save'",
            name=op.f("ck_identity_command_idempotency_operation_supported"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'completed')",
            name=op.f("ck_identity_command_idempotency_status"),
        ),
        sa.CheckConstraint(
            "length(key_digest) = 64",
            name=op.f("ck_identity_command_idempotency_key_digest_sha256"),
        ),
        sa.CheckConstraint(
            "length(request_digest) = 64",
            name=op.f("ck_identity_command_idempotency_request_digest_sha256"),
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND result_revision IS NULL "
            "AND result_updated_at IS NULL AND completed_at IS NULL) OR "
            "(status = 'completed' AND result_revision IS NOT NULL "
            "AND result_revision >= 1 AND result_updated_at IS NOT NULL "
            "AND completed_at IS NOT NULL)",
            name=op.f("ck_identity_command_idempotency_result_state_complete"),
        ),
    )


def downgrade() -> None:
    raise RuntimeError("identity command idempotency migration is forward-only")
