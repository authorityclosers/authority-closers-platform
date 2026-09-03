"""Harden PostgreSQL activity-to-media binding immutability.

Revision ``20260903_0015`` created the binding table and its trigger, but its
initial trigger function did not compare ``created_at``.  This forward repair
replaces the function in place so already-applied binding rows retain their
history and the existing trigger remains attached.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260903_0016"
down_revision: str | None = "20260903_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    # Keep the trigger installed by 0015 and replace only its function.  This
    # is safe for databases that already contain binding history.
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION prevent_activity_media_binding_mutation()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.id IS DISTINCT FROM OLD.id
                   OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
                   OR NEW.activity_id IS DISTINCT FROM OLD.activity_id
                   OR NEW.module_id IS DISTINCT FROM OLD.module_id
                   OR NEW.program_version_id IS DISTINCT FROM OLD.program_version_id
                   OR NEW.program_id IS DISTINCT FROM OLD.program_id
                   OR NEW.program_scope IS DISTINCT FROM OLD.program_scope
                   OR NEW.program_owner_key IS DISTINCT FROM OLD.program_owner_key
                   OR NEW.activity_version IS DISTINCT FROM OLD.activity_version
                   OR NEW.asset_id IS DISTINCT FROM OLD.asset_id
                   OR NEW.version_id IS DISTINCT FROM OLD.version_id
                   OR NEW.approval_reference IS DISTINCT FROM OLD.approval_reference
                   OR NEW.approved_by_person_id IS DISTINCT FROM OLD.approved_by_person_id
                   OR NEW.approved_at IS DISTINCT FROM OLD.approved_at
                   OR NEW.supersedes_binding_id IS DISTINCT FROM OLD.supersedes_binding_id
                   OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
                   OR NEW.request_fingerprint IS DISTINCT FROM OLD.request_fingerprint
                   OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                    RAISE EXCEPTION 'activity media binding identity is immutable';
                END IF;
                IF NEW.state IS DISTINCT FROM OLD.state
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


def downgrade() -> None:
    raise RuntimeError("activity media binding immutability repair is forward-only")
