"""Provider keys in Admin's Providers hub (owner, 20 Oct 2026: "search for a provider name,
add, add key and boom it's there").

- ``integration_secrets.purpose`` accepts ``provider_key``: an AI provider's API key a
  control account adds in Admin, sealed for this environment under the platform key
  (AES-256-GCM, as webhook and partner secrets are) and never shown again. One active key
  per provider; adding another retires the one before it, so the history stays.

No new table and no new column. A rollback is possible while no provider key was saved;
after that, the sealed keys require forward recovery.

Chain: after 20261020_0113 (Chats read marks).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261020_0114"
down_revision = "20261020_0113"
branch_labels = None
depends_on = None


def _stored_any(column: str, values: tuple[str, ...]) -> str:
    """PostgreSQL's stored text for ``column IN (values)`` on a varchar column."""
    items = ", ".join(f"('{value}'::character varying)::text" for value in values)
    return f"({column})::text = ANY (ARRAY[{items}])"


# Downgrade restores the constraint in PostgreSQL's stored form, as the staging baseline holds it
# (a restored dump keeps that text; a fresh IN (...) parse stores another), so the schema gate's
# byte comparison matches. Same meaning as the original IN list.
_PURPOSE_BEFORE = _stored_any("purpose", ("webhook_signing", "partner_key"))
_PURPOSE_AFTER = "purpose IN ('webhook_signing', 'partner_key', 'provider_key')"


def upgrade() -> None:
    op.drop_constraint("ck_integration_secrets_integration_secret_purpose", "integration_secrets")
    op.create_check_constraint("integration_secret_purpose", "integration_secrets", _PURPOSE_AFTER)


def downgrade() -> None:
    # Fence writes before the history check, then undo only what holds no history.
    op.execute(sa.text("LOCK TABLE integration_secrets IN ACCESS EXCLUSIVE MODE"))
    bind = op.get_bind()
    secrets = sa.table("integration_secrets", sa.column("purpose"))
    if bind.scalar(sa.select(sa.exists().where(secrets.c.purpose == "provider_key"))):
        raise RuntimeError("Provider key history requires forward recovery.")
    op.drop_constraint("ck_integration_secrets_integration_secret_purpose", "integration_secrets")
    op.create_check_constraint("integration_secret_purpose", "integration_secrets", _PURPOSE_BEFORE)
