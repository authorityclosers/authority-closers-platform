"""Private Google profile claims and an optional first-party photo copy."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, LargeBinary, String, Uuid, func
from sqlalchemy.orm import Mapped, deferred, mapped_column

from ac_platform.db.base import Base


class PersonGoogleProfile(Base):
    """One current Google display-profile projection for a canonical person."""

    __tablename__ = "person_google_profiles"
    __table_args__ = (
        CheckConstraint(
            "(photo_jpeg IS NULL) = (photo_sha256 IS NULL)",
            name="photo_sha256_matches_jpeg",
        ),
        CheckConstraint(
            "photo_jpeg IS NULL OR octet_length(photo_jpeg) <= 65536",
            name="photo_jpeg_max_bytes",
        ).ddl_if(dialect="postgresql"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    person_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "persons.id",
            name="fk_person_google_profiles_person_id_persons",
            ondelete="CASCADE",
        ),
        nullable=False,
        unique=True,
    )
    given_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    family_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    locale: Mapped[str | None] = mapped_column(String(35), nullable=True)
    hosted_domain: Mapped[str | None] = mapped_column(String(253), nullable=True)
    photo_jpeg: Mapped[bytes | None] = deferred(mapped_column(LargeBinary, nullable=True))
    photo_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    photo_source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    photo_fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    claims_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
