"""Keep current Google profile claims and an optional first-party photo copy."""

import sqlalchemy as sa
from alembic import op

revision = "20260930_0053"
down_revision = "20260929_0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "person_google_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("given_name", sa.String(length=200), nullable=True),
        sa.Column("family_name", sa.String(length=200), nullable=True),
        sa.Column("locale", sa.String(length=35), nullable=True),
        sa.Column("hosted_domain", sa.String(length=253), nullable=True),
        sa.Column("photo_jpeg", sa.LargeBinary(), nullable=True),
        sa.Column("photo_sha256", sa.String(length=64), nullable=True),
        sa.Column("photo_source_sha256", sa.String(length=64), nullable=True),
        sa.Column("photo_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claims_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "photo_jpeg IS NULL OR octet_length(photo_jpeg) <= 65536",
            name=op.f("ck_person_google_profiles_photo_jpeg_max_bytes"),
        ),
        sa.CheckConstraint(
            "(photo_jpeg IS NULL) = (photo_sha256 IS NULL)",
            name=op.f("ck_person_google_profiles_photo_sha256_matches_jpeg"),
        ),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["persons.id"],
            name="fk_person_google_profiles_person_id_persons",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_person_google_profiles"),
        sa.UniqueConstraint("person_id", name="uq_person_google_profiles_person_id"),
    )


def downgrade() -> None:
    raise RuntimeError("forward-only")
