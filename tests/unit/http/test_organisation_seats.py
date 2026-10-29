"""Fictional HTTP evidence: the Team tab's seat read counts paid and complimentary seats for
owners, admins and finance, never shows a grant's reason or end date, and says who may buy."""

# ruff: noqa: F811 - imported relational pytest fixtures

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from ac_platform.http.organisation import OrganisationSeatsResponse
from ac_platform.organisations.seat_grants import day_end, seat_day
from ac_platform.tenancy.models import Membership
from ac_platform.tenancy.seat_grant_models import OrganisationSeatGrant
from tests.unit.http.test_organisation import call, state  # noqa: F401
from tests.unit.http.test_workspaces import OTHER_TOKEN, workspace_state  # noqa: F401


def give(state, seats: int, days: int) -> str:
    now = datetime.now(UTC)
    last = seat_day(now) + timedelta(days=days)
    with Session(state.engine) as db, db.begin():
        db.add(
            OrganisationSeatGrant(
                id=uuid4(),
                tenant_id=state.tenant,
                seats=seats,
                valid_from=now - timedelta(days=30),
                valid_until=day_end(last),
                reason="Fictional founding client note",
                granted_by_person_id=state.person,
                created_at=now - timedelta(days=30),
            )
        )
    return last.isoformat()


async def test_the_owner_sees_paid_and_complimentary_seats_and_may_buy(state):
    last = give(state, 4, 60)
    response = await call(state, path="/seats")
    assert response.status_code == 200, response.text
    body = OrganisationSeatsResponse.model_validate_json(response.text)
    assert (body.paid_seats, body.complimentary_seats, body.total_seats) == (100, 4, 104)
    assert (body.active_members, body.pending_invites, body.seats_available) == (3, 0, 101)
    assert body.can_buy is True
    assert "Fictional founding" not in response.text and last not in response.text
    billing = (await call(state, path="/billing")).json()
    assert (billing["complimentary_seats"], billing["total_seats"]) == (4, 104)


async def test_an_admin_sees_seats_but_does_not_buy(state):
    response = await call(state, path="/seats", token=OTHER_TOKEN)
    assert response.status_code == 200, response.text
    assert response.json()["can_buy"] is False


@pytest.mark.parametrize(("role", "status", "can_buy"), [("finance", 200, True)])
async def test_finance_sees_seats_and_may_buy(state, role, status, can_buy):
    with Session(state.engine) as db, db.begin():
        db.get(Membership, (state.tenant, state.person)).role = role
    response = await call(state, path="/seats")
    assert response.status_code == status
    assert response.json()["can_buy"] is can_buy


@pytest.mark.parametrize("role", ["manager", "member", "viewer"])
async def test_people_who_neither_invite_nor_pay_do_not_see_seats(state, role):
    with Session(state.engine) as db, db.begin():
        db.get(Membership, (state.tenant, state.person)).role = role
    assert (await call(state, path="/seats")).status_code == 403


async def test_an_ended_grant_no_longer_counts(state):
    give(state, 4, -2)
    body = (await call(state, path="/seats")).json()
    assert (body["complimentary_seats"], body["total_seats"]) == (0, 100)
