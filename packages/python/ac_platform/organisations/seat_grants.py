"""Complimentary organisation seats the AC owner grants in Admin (owner, 30 Oct 2026:
"a proper seats system", founding clients get seats without paying; migration 20261030_0144).

An organisation's seats are its paid seats (the current paid period, usage.paid_seats) plus
the complimentary seats live now. Each grant row names a seat count, the last day it counts
(an IST date) and why. A change or an early end is a new row that supersedes the old one
(seats 0 ends it); no row is edited or deleted, so the ledger is the history. Ending or
shrinking a grant never removes a member: invitations stop until a seat is free.

Only the owner's own verified account (the AI budget ceiling's allowlist) records a grant;
any Admin with the platform organisation capability reads them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ac_platform.identity.models import Person
from ac_platform.tenancy.models import Organisation
from ac_platform.tenancy.seat_grant_models import MAX_GRANT_SEATS, OrganisationSeatGrant

# Founding clients count their seats on Indian days: "until 31 Jan" lasts all of 31 Jan IST.
SEAT_DAY_ZONE = ZoneInfo("Asia/Kolkata")
# About three years ahead; a longer grant is a contract, not a founding favour.
MAX_GRANT_DAYS = 1100
GRANT_ACTION = "organisation.seats_granted"


class SeatGrantRefused(ValueError):
    """A content-free reason the grant was not recorded, with its HTTP status."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def seat_day(value: datetime) -> date:
    """The IST day an instant falls on."""
    return value.astimezone(SEAT_DAY_ZONE).date()


def day_end(day: date) -> datetime:
    """The instant a grant "until ``day``" stops counting: the next IST midnight, in UTC."""
    return datetime.combine(day + timedelta(days=1), time(), SEAT_DAY_ZONE).astimezone(UTC)


def last_day(valid_until: datetime) -> date:
    """The last IST day a grant counts on (``day_end``'s inverse)."""
    return seat_day(_aware(valid_until) - timedelta(microseconds=1))


def _aware(value: datetime) -> datetime:
    # SQLite returns naive UTC values; PostgreSQL returns aware ones.
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _live(at: datetime) -> Any:
    """Grant rows counting at ``at``: in their window and not yet superseded."""
    grant = OrganisationSeatGrant
    later = aliased(OrganisationSeatGrant)
    return (
        grant.seats > 0,
        grant.created_at <= at,
        grant.valid_from <= at,
        grant.valid_until > at,
        ~exists().where(later.supersedes_grant_id == grant.id, later.created_at <= at),
    )


async def complimentary_seats(database: AsyncSession, tenant_id: UUID, at: datetime) -> int:
    total = await database.scalar(
        select(func.coalesce(func.sum(OrganisationSeatGrant.seats), 0)).where(
            OrganisationSeatGrant.tenant_id == tenant_id, *_live(at)
        )
    )
    return int(total or 0)


async def complimentary_seats_by_tenant(
    database: AsyncSession, at: datetime
) -> dict[UUID, tuple[int, datetime | None]]:
    """Every organisation's live complimentary seats and when the first of them ends."""
    rows = await database.execute(
        select(
            OrganisationSeatGrant.tenant_id,
            func.sum(OrganisationSeatGrant.seats),
            func.min(OrganisationSeatGrant.valid_until),
        )
        .where(*_live(at))
        .group_by(OrganisationSeatGrant.tenant_id)
    )
    return {
        tenant: (int(seats or 0), _aware(until) if until is not None else None)
        for tenant, seats, until in rows
    }


async def live_grants(
    database: AsyncSession, tenant_id: UUID, at: datetime
) -> list[OrganisationSeatGrant]:
    return list(
        (
            await database.scalars(
                select(OrganisationSeatGrant)
                .where(OrganisationSeatGrant.tenant_id == tenant_id, *_live(at))
                .order_by(OrganisationSeatGrant.valid_until, OrganisationSeatGrant.created_at)
            )
        ).all()
    )


async def grant_history(database: AsyncSession, tenant_id: UUID) -> list[dict[str, Any]]:
    """Every grant row, newest first, with who recorded it and why (Admin only)."""
    grants = (
        await database.scalars(
            select(OrganisationSeatGrant)
            .where(OrganisationSeatGrant.tenant_id == tenant_id)
            .order_by(OrganisationSeatGrant.created_at.desc(), OrganisationSeatGrant.id)
        )
    ).all()
    now = datetime.now(UTC)
    live = {grant.id for grant in await live_grants(database, tenant_id, now)}
    who = {grant.granted_by_person_id for grant in grants}
    emails: dict[UUID, str | None] = {}
    if who:
        found = await database.execute(select(Person.id, Person.email).where(Person.id.in_(who)))
        emails = {person: email for person, email in found}
    return [
        {
            "id": str(grant.id),
            "kind": (
                "grant"
                if grant.supersedes_grant_id is None
                else ("end" if grant.seats == 0 else "change")
            ),
            "seats": grant.seats,
            "until": None if grant.seats == 0 else last_day(grant.valid_until).isoformat(),
            "supersedes_grant_id": (
                None if grant.supersedes_grant_id is None else str(grant.supersedes_grant_id)
            ),
            "reason": grant.reason,
            "granted_by": emails.get(grant.granted_by_person_id),
            "created_at": _aware(grant.created_at).isoformat(),
            "live": grant.id in live,
        }
        for grant in grants
    ]


async def is_seat_owner(database: AsyncSession, person_id: UUID) -> bool:
    """The owner's own verified account, on the AI budget ceiling's allowlist."""
    # Imported here: the budget module sits above the organisation package.
    from ac_platform.conversation_intelligence.budget_admin import CEILING_OWNER_EMAILS

    person = await database.get(Person, person_id)
    return (
        person is not None
        and person.email_verified_at is not None
        and (person.email or "").casefold() in CEILING_OWNER_EMAILS
    )


@dataclass(frozen=True, slots=True)
class GrantCommand:
    seats: int
    until: date | None
    reason: str
    supersedes_grant_id: UUID | None = None

    def intent(self) -> dict[str, Any]:
        return {
            "seats": self.seats,
            "until": None if self.until is None else self.until.isoformat(),
            "reason": self.reason,
            "supersedes_grant_id": (
                None if self.supersedes_grant_id is None else str(self.supersedes_grant_id)
            ),
        }


async def record_grant(
    database: AsyncSession,
    *,
    tenant_id: UUID,
    command: GrantCommand,
    person_id: UUID,
    now: datetime,
) -> tuple[OrganisationSeatGrant, OrganisationSeatGrant | None]:
    """Record one grant, change or end and return it with the grant it replaced.

    The caller has checked the owner and audits. The organisation row lock serializes this
    with invitations, which hold the same lock while they count seats.
    """
    reason = command.reason.strip()
    if not reason or len(reason) > 300 or any(ord(char) < 32 for char in reason):
        raise SeatGrantRefused(422, "Add a short reason (up to 300 characters).")
    if not 0 <= command.seats <= MAX_GRANT_SEATS:
        raise SeatGrantRefused(422, f"Give between 1 and {MAX_GRANT_SEATS} seats.")
    organisation = await database.scalar(
        select(Organisation).where(Organisation.tenant_id == tenant_id).with_for_update()
    )
    if organisation is None:
        raise SeatGrantRefused(404, "Organisation not found.")
    replaced = None
    if command.supersedes_grant_id is not None:
        replaced = await database.scalar(
            select(OrganisationSeatGrant)
            .where(OrganisationSeatGrant.id == command.supersedes_grant_id)
            .with_for_update()
        )
        if replaced is None or replaced.tenant_id != tenant_id:
            raise SeatGrantRefused(404, "That grant is not this organisation's.")
        if replaced.id not in {grant.id for grant in await live_grants(database, tenant_id, now)}:
            raise SeatGrantRefused(409, "That grant already ended or changed. Refresh.")
    elif command.seats == 0:
        raise SeatGrantRefused(422, f"Give between 1 and {MAX_GRANT_SEATS} seats.")
    valid_until = now
    if command.seats > 0:
        if command.until is None:
            raise SeatGrantRefused(422, "Choose the last day the seats count.")
        if command.until < seat_day(now):
            raise SeatGrantRefused(422, "The last day can't be in the past.")
        if command.until > seat_day(now) + timedelta(days=MAX_GRANT_DAYS):
            raise SeatGrantRefused(422, "Give seats for about three years at most.")
        valid_until = day_end(command.until)
        if replaced is not None and (
            replaced.seats == command.seats and _aware(replaced.valid_until) == valid_until
        ):
            raise SeatGrantRefused(422, "That is the grant as it stands; nothing changed.")
    grant = OrganisationSeatGrant(
        id=uuid4(),
        tenant_id=tenant_id,
        seats=command.seats,
        valid_from=now,
        valid_until=valid_until,
        supersedes_grant_id=command.supersedes_grant_id,
        reason=reason,
        granted_by_person_id=person_id,
        created_at=now,
    )
    database.add(grant)
    await database.flush()
    return grant, replaced


__all__ = [
    "GRANT_ACTION",
    "MAX_GRANT_DAYS",
    "MAX_GRANT_SEATS",
    "GrantCommand",
    "OrganisationSeatGrant",
    "SeatGrantRefused",
    "complimentary_seats",
    "complimentary_seats_by_tenant",
    "day_end",
    "grant_history",
    "is_seat_owner",
    "last_day",
    "live_grants",
    "record_grant",
    "seat_day",
]
