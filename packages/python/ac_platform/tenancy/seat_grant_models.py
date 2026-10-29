"""Complimentary organisation seat grants (owner, 30 Oct 2026; migration 20261030_0144).

One append-only row per grant, change or early end the AC owner records in Admin. A change
or an end is a new row that supersedes the old one (seats 0 ends it). The schema gate allows
no triggers, so the ORM refuses updates and deletes (as for plan price changes). The rules
that read and write these rows live in ``ac_platform.organisations.seat_grants``.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.db.base import Base

MAX_GRANT_SEATS = 500


class SeatGrantHistoryError(RuntimeError):
    """A saved grant was edited or deleted; record a new grant that supersedes it instead."""


class OrganisationSeatGrant(Base):
    """One complimentary seat grant, change or end."""

    __tablename__ = "organisation_seat_grants"
    __table_args__ = (
        # A grant is superseded at most once, so changes form one line per grant.
        UniqueConstraint("supersedes_grant_id", name="uq_organisation_seat_grants_supersedes"),
        CheckConstraint(f"seats >= 0 AND seats <= {MAX_GRANT_SEATS}", name="seats_in_range"),
        CheckConstraint(
            "seats > 0 OR supersedes_grant_id IS NOT NULL", name="zero_seats_only_end_a_grant"
        ),
        CheckConstraint("seats = 0 OR valid_until > valid_from", name="valid_until_after_from"),
        CheckConstraint("length(trim(reason)) > 0", name="reason_present"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT", name="fk_organisation_seat_grant_tenant"),
        index=True,
    )
    seats: Mapped[int] = mapped_column(Integer)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    supersedes_grant_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organisation_seat_grants.id", name="fk_organisation_seat_grant_supersedes"),
        nullable=True,
    )
    reason: Mapped[str] = mapped_column(String(300))
    granted_by_person_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("persons.id", name="fk_organisation_seat_grant_person")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


@event.listens_for(OrganisationSeatGrant, "before_update")
def _refuse_grant_update(_mapper: object, _connection: object, _target: object) -> None:
    raise SeatGrantHistoryError("Seat grants are append-only: record a new grant instead.")


@event.listens_for(OrganisationSeatGrant, "before_delete")
def _refuse_grant_delete(_mapper: object, _connection: object, _target: object) -> None:
    raise SeatGrantHistoryError("Seat grants are append-only: record a new grant instead.")


__all__ = ["MAX_GRANT_SEATS", "OrganisationSeatGrant", "SeatGrantHistoryError"]
