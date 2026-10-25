"""Every member's profile: a user id, a title, a team and their own photo (owner, 25 Oct
2026: "everyone should be prompted to keep profile pic as well as choose user id and fill
all details ... business owner can identify who did what work"; design:
docs/product/roles-owner-profile-pulse.md, section 4).

Two new tables; no existing table changes:

- ``person_profile_details``: one row per person who set any of it. ``handle`` (the user
  id, stored lower-case, unique across Sales X-Ray, 3 to 30 characters), when it last
  changed (at most once in 30 days), ``title`` and ``team`` (each 1 to 80 characters),
  and its own revision for compare-and-set saves.
- ``person_photos``: one current photo per person that they uploaded (later also from
  Pulse), its type, size and SHA-256. Google's photo stays where it is; the upload wins
  over it.

Rollback: allowed while nobody has saved details or uploaded a photo; otherwise that
history requires forward recovery.

Chain: after Lead OS's 0134 (duplicate tables).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261025_0135"
down_revision = "20261025_0134"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "person_profile_details",
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("handle", sa.String(30), nullable=True),
        sa.Column("handle_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("title", sa.String(80), nullable=True),
        sa.Column("team", sa.String(80), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("person_id"),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["persons.id"],
            name="fk_person_profile_details_person_id_persons",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "handle IS NULL OR length(handle) BETWEEN 3 AND 30", name="profile_handle_length"
        ),
        sa.CheckConstraint(
            "(handle IS NULL) = (handle_changed_at IS NULL)", name="profile_handle_changed"
        ),
        sa.CheckConstraint(
            "title IS NULL OR length(title) BETWEEN 1 AND 80", name="profile_title_length"
        ),
        sa.CheckConstraint(
            "team IS NULL OR length(team) BETWEEN 1 AND 80", name="profile_team_length"
        ),
        sa.CheckConstraint("revision >= 1", name="profile_details_revision"),
    )
    # One person per user id.
    op.create_index(
        "uq_person_profile_details_handle",
        "person_profile_details",
        ["handle"],
        unique=True,
        postgresql_where=sa.text("handle IS NOT NULL"),
    )
    op.create_table(
        "person_photos",
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(12), nullable=False),
        sa.Column("content_type", sa.String(16), nullable=False),
        sa.Column("photo", sa.LargeBinary(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("person_id"),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["persons.id"],
            name="fk_person_photos_person_id_persons",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("source IN ('upload', 'pulse')", name="person_photo_source"),
        sa.CheckConstraint(
            "content_type IN ('image/jpeg', 'image/png', 'image/webp')",
            name="person_photo_type",
        ),
        sa.CheckConstraint("byte_size BETWEEN 1 AND 2097152", name="person_photo_size"),
        sa.CheckConstraint("length(sha256) = 64", name="person_photo_sha256"),
        sa.CheckConstraint("revision >= 1", name="person_photo_revision"),
    )


def downgrade() -> None:
    # Fence writes before the history check, then undo only what holds no history.
    op.execute(sa.text("LOCK TABLE person_profile_details, person_photos IN ACCESS EXCLUSIVE MODE"))
    details = sa.table("person_profile_details", sa.column("person_id"))
    photos = sa.table("person_photos", sa.column("person_id"))
    bind = op.get_bind()
    if bind.scalar(sa.select(sa.exists().where(details.c.person_id.is_not(None)))) or bind.scalar(
        sa.select(sa.exists().where(photos.c.person_id.is_not(None)))
    ):
        raise RuntimeError("Profile detail history requires forward recovery.")
    op.drop_table("person_photos")
    op.drop_index("uq_person_profile_details_handle", table_name="person_profile_details")
    op.drop_table("person_profile_details")
