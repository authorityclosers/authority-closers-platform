"""Every call names its lead through the lead's call history (approved map, slice 7 B,
22 Oct 2026; owner: every call linked).

- ``ix_lead_desk_event_call_submission``: the lead history's call events by the call they
  recorded, ``(tenant_id, (data ->> 'submission_id'))`` where ``kind = 'call'``. The Calls
  list names each listed call's lead in one statement per page, so a lead's earlier calls
  show it too, not only its latest (``lead_desk_leads.last_submission_id``).

``lead_desk_events`` already holds rows, so the index is built CONCURRENTLY, outside the
migration's transaction: the history keeps taking writes while it builds. Nothing else
changes.

Rollback: forward-only (the schema gate's recovery policy); a later migration drops the
index if it is ever unwanted. No data depends on it.

Chain: after 20261022_0121 (lead pipelines).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261022_0122"
down_revision = "20261022_0121"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_lead_desk_event_call_submission",
            "lead_desk_events",
            ["tenant_id", sa.text("(data ->> 'submission_id')")],
            postgresql_where=sa.text("kind = 'call'"),
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    raise RuntimeError(
        "The call-history index is forward-only: a later migration drops it if unwanted."
    )
