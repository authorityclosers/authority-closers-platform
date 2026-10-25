"""Business roles: Sales manager, Viewer and Finance (owner, 25 Oct 2026: "only two
options that is admin and member, there are many roles businesses need and this admin is
not to be made to all"; design: docs/product/roles-owner-profile-pulse.md, section 1).

- ``memberships.role`` and ``organisation_invites.role`` also allow 'manager' (Sales
  manager: the team's leads and calls, no settings, members or billing), 'viewer' (reads
  the team's work, changes nothing) and 'finance' (billing only). Sellers keep the stored
  value 'member', so no row changes meaning.

Only the checks change; no row is rewritten.

Rollback: allowed while no membership or invitation has one of the new roles; otherwise
that history requires forward recovery.

Chain: after 20261025_0135 (the member profile).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261025_0136"
down_revision = "20261025_0135"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_memberships_role_supported"), "memberships", type_="check")
    op.create_check_constraint(
        "role_supported",
        "memberships",
        "role IN ('learner', 'support', 'admin', 'owner', 'processing', 'member',"
        " 'manager', 'viewer', 'finance')",
    )
    op.drop_constraint(
        op.f("ck_organisation_invites_role_supported"), "organisation_invites", type_="check"
    )
    op.create_check_constraint(
        "role_supported",
        "organisation_invites",
        "role IN ('admin', 'member', 'manager', 'viewer', 'finance')",
    )


def downgrade() -> None:
    # Fence writes before the history check, then undo only what holds no history.
    op.execute(sa.text("LOCK TABLE memberships, organisation_invites IN ACCESS EXCLUSIVE MODE"))
    memberships = sa.table("memberships", sa.column("role"))
    invites = sa.table("organisation_invites", sa.column("role"))
    new_roles = ("manager", "viewer", "finance")
    bind = op.get_bind()
    if bind.scalar(sa.select(sa.exists().where(memberships.c.role.in_(new_roles)))) or bind.scalar(
        sa.select(sa.exists().where(invites.c.role.in_(new_roles)))
    ):
        raise RuntimeError("Business role history requires forward recovery.")
    # Written as PostgreSQL stores the 0054 checks after a dump and restore (element casts
    # inside ARRAY[...]), so the rollback gives back the exact schema the gate compares.
    op.drop_constraint(
        op.f("ck_organisation_invites_role_supported"), "organisation_invites", type_="check"
    )
    op.create_check_constraint(
        "role_supported",
        "organisation_invites",
        "(role)::text = ANY (ARRAY[('admin'::character varying)::text,"
        " ('member'::character varying)::text])",
    )
    op.drop_constraint(op.f("ck_memberships_role_supported"), "memberships", type_="check")
    op.create_check_constraint(
        "role_supported",
        "memberships",
        "(role)::text = ANY (ARRAY[('learner'::character varying)::text,"
        " ('support'::character varying)::text, ('admin'::character varying)::text,"
        " ('owner'::character varying)::text, ('processing'::character varying)::text,"
        " ('member'::character varying)::text])",
    )
