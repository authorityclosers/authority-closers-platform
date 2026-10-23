"""Economics settings (owner, 23 Oct 2026: "making economically strong app which can earn money
according to how much we overall spend from all points").

- New table ``economics_settings``: revisions of the fixed costs a month and the fee rates
  Admin's Economics page uses; newest wins; written only from Admin, each save audited with
  old and new. Until a revision is saved, the code's defaults apply. The ORM refuses updates
  and deletes (the schema gate allows no triggers): a change is a new revision.

A rollback is possible while no settings were saved (the release gate rehearses upgrade,
downgrade and re-upgrade on an empty schema); after that, the history requires forward
recovery.

Chain: after 20261023_0125 (Offer Studio offer versions).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261023_0126"
down_revision = "20261023_0125"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "economics_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("reason", sa.String(200), nullable=True),
        sa.Column("created_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("revision", name="uq_economics_settings_revision"),
        sa.CheckConstraint("revision >= 1", name="revision"),
    )


def downgrade() -> None:
    # Fence writes before the history check, then remove only an empty table.
    op.execute(sa.text("LOCK TABLE economics_settings IN ACCESS EXCLUSIVE MODE"))
    saved = sa.table("economics_settings", sa.column("id"))
    if op.get_bind().scalar(sa.select(sa.exists().where(saved.c.id.is_not(None)))):
        raise RuntimeError("Economics settings history requires forward recovery.")
    op.drop_table("economics_settings")
