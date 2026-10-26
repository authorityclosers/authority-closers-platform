"""Canonical Sales Xray contact details attached to an AC Person."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base


class SalesXrayProfile(Base):
    """One current Sales Xray profile for a canonical AC Person.

    Phone values remain unverified until an SMS ownership adapter is approved.
    The review flag is internal and never returned by self-service routes.
    """

    __tablename__ = "sales_xray_profiles"
    __table_args__ = (
        CheckConstraint("revision >= 0", name="revision_nonnegative"),
        CheckConstraint(
            "phone_number_e164 IS NULL OR length(phone_number_e164) BETWEEN 3 AND 16",
            name="phone_number_length",
        ),
        CheckConstraint(
            "phone_verified_at IS NULL OR phone_number_e164 IS NOT NULL",
            name="verified_phone_present",
        ),
        Index("ix_sales_xray_profiles_phone_number_e164", "phone_number_e164"),
        Index(
            "uq_sales_xray_profiles_verified_phone",
            "phone_number_e164",
            unique=True,
            postgresql_where=text("phone_verified_at IS NOT NULL"),
            sqlite_where=text("phone_verified_at IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    person_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "persons.id",
            name="fk_sales_xray_profiles_person_id_persons",
            ondelete="CASCADE",
        ),
        nullable=False,
        unique=True,
    )
    phone_number_e164: Mapped[str | None] = mapped_column(String(16), nullable=True)
    phone_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    admin_collision_review_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class PersonProfileDetails(Base):
    """What a member's team knows them by (migration 0135): the user id (lower-case,
    unique, changed at most once in 30 days), job title and team. Its own revision, so a
    save here never conflicts with the name and phone form."""

    __tablename__ = "person_profile_details"
    __table_args__ = (
        CheckConstraint(
            "handle IS NULL OR length(handle) BETWEEN 3 AND 30", name="profile_handle_length"
        ),
        CheckConstraint(
            "(handle IS NULL) = (handle_changed_at IS NULL)", name="profile_handle_changed"
        ),
        CheckConstraint(
            "title IS NULL OR length(title) BETWEEN 1 AND 80", name="profile_title_length"
        ),
        CheckConstraint(
            "team IS NULL OR length(team) BETWEEN 1 AND 80", name="profile_team_length"
        ),
        CheckConstraint("revision >= 1", name="profile_details_revision"),
        Index(
            "uq_person_profile_details_handle",
            "handle",
            unique=True,
            postgresql_where=text("handle IS NOT NULL"),
            sqlite_where=text("handle IS NOT NULL"),
        ),
    )

    person_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "persons.id",
            name="fk_person_profile_details_person_id_persons",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    handle: Mapped[str | None] = mapped_column(String(30), nullable=True)
    handle_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    title: Mapped[str | None] = mapped_column(String(80), nullable=True)
    team: Mapped[str | None] = mapped_column(String(80), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PersonPhoto(Base):
    """A person's own current photo (migration 0135): uploaded in Sales X-Ray (later also
    from Pulse). It wins over Google's photo. The bytes are loaded only to serve them."""

    __tablename__ = "person_photos"
    __table_args__ = (
        CheckConstraint("source IN ('upload', 'pulse')", name="person_photo_source"),
        CheckConstraint(
            "content_type IN ('image/jpeg', 'image/png', 'image/webp')",
            name="person_photo_type",
        ),
        CheckConstraint("byte_size BETWEEN 1 AND 2097152", name="person_photo_size"),
        CheckConstraint("length(sha256) = 64", name="person_photo_sha256"),
        CheckConstraint("revision >= 1", name="person_photo_revision"),
        # v0.93 (migration 0138): the photo is a file under the Sales X-Ray store; the bytes
        # column stays for photos saved before, until a later migration clears it.
        CheckConstraint("photo IS NOT NULL OR storage_key IS NOT NULL", name="person_photo_kept"),
    )

    person_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "persons.id",
            name="fk_person_photos_person_id_persons",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    source: Mapped[str] = mapped_column(String(12), nullable=False)
    content_type: Mapped[str] = mapped_column(String(16), nullable=False)
    photo: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True, deferred=True)
    storage_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
