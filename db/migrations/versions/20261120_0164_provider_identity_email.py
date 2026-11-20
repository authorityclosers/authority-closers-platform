"""Each linked sign-in account shows its email (owner, 19 Nov 2026: "more than one Gmail
account to log in with"; Settings -> Sign-in & security lists every Google account, and the
person must see which is which).

- ``provider_identities.email``: the email the provider last asserted for this
  (issuer, subject) key, written when the key is linked and each time it signs in. Display
  only: the key stays the identity and sign-in never selects by this column. Null for links
  made before this migration until they are next used.

Rollback: allowed while no row holds an email; once one does, that history requires forward
recovery.

Chain: after 20261117_0162 (WhatsApp files and campaigns).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261120_0164"
down_revision = "20261117_0162"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("provider_identities", sa.Column("email", sa.String(length=320), nullable=True))


def downgrade() -> None:
    # Fence writes before the history check, then undo only what holds no history.
    op.execute(sa.text("LOCK TABLE provider_identities IN ACCESS EXCLUSIVE MODE"))
    identities = sa.table("provider_identities", sa.column("email"))
    if op.get_bind().scalar(sa.select(sa.exists().where(identities.c.email.is_not(None)))):
        raise RuntimeError("Sign-in account email history requires forward recovery.")
    op.drop_column("provider_identities", "email")
