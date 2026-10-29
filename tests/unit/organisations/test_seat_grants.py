"""Complimentary seats: an unpaid organisation invites up to its grant, a removal frees a seat
for someone else, and the grant ledger only grows (fictional people and organisations)."""

# ruff: noqa: F811 - imported relational pytest fixtures

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from ac_platform.identity.models import Person
from ac_platform.organisations.seat_grants import (
    GrantCommand,
    SeatGrantRefused,
    complimentary_seats,
    complimentary_seats_by_tenant,
    day_end,
    grant_history,
    last_day,
    live_grants,
    record_grant,
    seat_day,
)
from ac_platform.organisations.service import OrganisationSeatsFull
from ac_platform.organisations.usage import organisation_seats
from ac_platform.tenancy.models import Membership
from ac_platform.tenancy.seat_grant_models import OrganisationSeatGrant, SeatGrantHistoryError
from tests.unit.organisations.test_service import seed_paid_seats, state  # noqa: F401


def until(days: int) -> date:
    return seat_day(datetime.now(UTC)) + timedelta(days=days)


async def grant(state, tenant_id, seats, *, days=90, replaces=None, reason="Founding client"):
    row, _ = await record_grant(
        state.adapter,
        tenant_id=tenant_id,
        command=GrantCommand(
            seats=seats,
            until=None if seats == 0 else until(days),
            reason=reason,
            supersedes_grant_id=replaces,
        ),
        person_id=state.owner_id,
        now=datetime.now(UTC),
    )
    return row


async def unpaid_org(state):
    return await state.service.create("Seat Grant Fixture", state.owner_id, uuid4(), "AUT-seats")


def test_a_grant_counts_through_its_last_indian_day():
    # "Until 31 Jan" lasts until midnight IST, 18:30 UTC on 31 Jan.
    assert day_end(date(2027, 1, 31)) == datetime(2027, 1, 31, 18, 30, tzinfo=UTC)
    assert last_day(datetime(2027, 1, 31, 18, 30, tzinfo=UTC)) == date(2027, 1, 31)
    assert last_day(datetime(2027, 1, 31, 18, 30)) == date(2027, 1, 31)  # SQLite's naive UTC
    assert seat_day(datetime(2027, 1, 31, 18, 29, tzinfo=UTC)) == date(2027, 1, 31)
    assert seat_day(datetime(2027, 1, 31, 18, 30, tzinfo=UTC)) == date(2027, 2, 1)


@pytest.mark.asyncio
async def test_four_free_seats_take_three_invites_and_a_removal_frees_one(state):
    org = await unpaid_org(state)
    tenant = org.tenant_id
    with pytest.raises(OrganisationSeatsFull, match="Every seat is taken"):
        await state.service.request_member(
            tenant, "first@example.test", "member", uuid4(), actor_person_id=state.owner_id
        )

    await grant(state, tenant, 4)
    for name in ("first", "second", "third"):
        invited = await state.service.request_member(
            tenant, f"{name}@example.test", "member", uuid4(), actor_person_id=state.owner_id
        )
        assert invited["status"] == "invited"
    assert await organisation_seats(state.adapter, tenant) == {
        "paid_seats": 0,
        "complimentary_seats": 4,
        "total_seats": 4,
        "active_members": 1,
        "pending_invites": 3,
        "seats_available": 0,
    }
    with pytest.raises(OrganisationSeatsFull):
        await state.service.request_member(
            tenant, "fourth@example.test", "member", uuid4(), actor_person_id=state.owner_id
        )

    # One invite is accepted; the member later leaves and their seat goes to someone new.
    joiner = uuid4()
    state.session.add(
        Person(id=joiner, email="second@example.test", email_verified_at=datetime.now(UTC))
    )
    state.session.flush()
    joined = await state.service.request_member(
        tenant, "second@example.test", "member", uuid4(), actor_person_id=state.owner_id
    )
    assert joined["status"] == "active"
    await state.service.remove_member(tenant, joiner, uuid4(), actor_person_id=state.owner_id)
    seats = await organisation_seats(state.adapter, tenant)
    assert (seats["active_members"], seats["pending_invites"], seats["seats_available"]) == (
        1,
        2,
        1,
    )
    reassigned = await state.service.request_member(
        tenant, "fourth@example.test", "member", uuid4(), actor_person_id=state.owner_id
    )
    assert reassigned["status"] == "invited"
    # The removed member's history stays; only their state ended.
    removed = state.session.get(Membership, (tenant, joiner))
    assert removed.status == "inactive" and removed.ended_at is not None


@pytest.mark.asyncio
async def test_paid_and_complimentary_seats_add_up(state):
    org = await unpaid_org(state)
    await seed_paid_seats(state.adapter, org.tenant_id, state.owner_id, seats=2)
    await grant(state, org.tenant_id, 3)
    await grant(state, org.tenant_id, 1, days=10, reason="Pilot extra")
    seats = await organisation_seats(state.adapter, org.tenant_id)
    assert (seats["paid_seats"], seats["complimentary_seats"], seats["total_seats"]) == (2, 4, 6)
    by_tenant = await complimentary_seats_by_tenant(state.adapter, datetime.now(UTC))
    assert by_tenant[org.tenant_id] == (4, day_end(until(10)))


@pytest.mark.asyncio
async def test_change_and_end_supersede_and_history_keeps_every_row(state):
    org = await unpaid_org(state)
    tenant = org.tenant_id
    first = await grant(state, tenant, 4)
    changed = await grant(state, tenant, 6, days=200, replaces=first.id, reason="Extended")
    assert await complimentary_seats(state.adapter, tenant, datetime.now(UTC)) == 6
    with pytest.raises(SeatGrantRefused, match="already ended or changed") as twice:
        await grant(state, tenant, 5, replaces=first.id)
    assert twice.value.status == 409
    ended = await grant(state, tenant, 0, replaces=changed.id, reason="Moved to paid")
    assert await complimentary_seats(state.adapter, tenant, datetime.now(UTC)) == 0
    assert await live_grants(state.adapter, tenant, datetime.now(UTC)) == []

    history = await grant_history(state.adapter, tenant)
    assert [row["kind"] for row in history] == ["end", "change", "grant"]
    assert [row["id"] for row in history] == [str(ended.id), str(changed.id), str(first.id)]
    assert history[0]["until"] is None and history[1]["until"] == until(200).isoformat()
    assert history[2]["granted_by"] == "owner@example.test"
    assert not any(row["live"] for row in history)
    # Ending a grant removes nobody: members stay, new invitations wait for a seat.
    assert (await organisation_seats(state.adapter, tenant))["active_members"] == 1


@pytest.mark.asyncio
async def test_a_grant_stops_counting_after_its_last_day(state):
    org = await unpaid_org(state)
    row = await grant(state, org.tenant_id, 4, days=0)
    assert await complimentary_seats(state.adapter, org.tenant_id, row.valid_until) == 0
    assert (
        await complimentary_seats(
            state.adapter, org.tenant_id, row.valid_until - timedelta(seconds=1)
        )
        == 4
    )
    # A change recorded later does not rewrite what counted before it.
    later = await grant(state, org.tenant_id, 2, replaces=row.id)
    assert await complimentary_seats(state.adapter, org.tenant_id, row.created_at) == 4
    assert await complimentary_seats(state.adapter, org.tenant_id, later.created_at) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("seats", "days", "reason", "status", "message"),
    [
        (0, 30, "Founding client", 422, "between 1 and"),
        (4, -1, "Founding client", 422, "can't be in the past"),
        (4, 1200, "Founding client", 422, "three years at most"),
        (4, 30, "   ", 422, "short reason"),
        (501, 30, "Founding client", 422, "between 1 and"),
    ],
)
async def test_refused_grants_record_nothing(state, seats, days, reason, status, message):
    org = await unpaid_org(state)
    with pytest.raises(SeatGrantRefused, match=message) as refused:
        await record_grant(
            state.adapter,
            tenant_id=org.tenant_id,
            command=GrantCommand(seats=seats, until=until(days), reason=reason),
            person_id=state.owner_id,
            now=datetime.now(UTC),
        )
    assert refused.value.status == status
    assert state.session.scalar(select(func.count()).select_from(OrganisationSeatGrant)) == 0


@pytest.mark.asyncio
async def test_unchanged_or_foreign_grants_are_refused(state):
    org = await unpaid_org(state)
    other = await state.service.create("Other Fixture", state.owner_id, uuid4(), "AUT-seats")
    row = await grant(state, org.tenant_id, 4)
    with pytest.raises(SeatGrantRefused, match="nothing changed"):
        await grant(state, org.tenant_id, 4, replaces=row.id)
    with pytest.raises(SeatGrantRefused, match="not this organisation") as foreign:
        await grant(state, other.tenant_id, 2, replaces=row.id)
    assert foreign.value.status == 404


@pytest.mark.asyncio
async def test_grant_rows_are_append_only(state):
    org = await unpaid_org(state)
    row = await grant(state, org.tenant_id, 4)
    row.seats = 40
    with pytest.raises(SeatGrantHistoryError):
        state.session.flush()
    state.session.rollback()


@pytest.mark.asyncio
async def test_grant_rows_cannot_be_deleted(state):
    org = await unpaid_org(state)
    row = await grant(state, org.tenant_id, 4)
    state.session.delete(row)
    with pytest.raises(SeatGrantHistoryError):
        state.session.flush()
    state.session.rollback()
