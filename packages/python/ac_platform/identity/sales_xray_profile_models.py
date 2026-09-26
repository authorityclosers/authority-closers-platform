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
