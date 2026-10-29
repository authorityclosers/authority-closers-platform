"""Fictional HTTP evidence: only the owner gives complimentary seats in Admin, every grant is
audited in the organisation's chain, and the organisation's Seats read counts them."""

# ruff: noqa: F811 - imported relational pytest fixtures

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain_sync
from ac_platform.http.platform_organisations import PlatformSeatsResponse
from ac_platform.identity.models import Person
from ac_platform.organisations.seat_grants import seat_day
from ac_platform.tenancy.models import Membership
from ac_platform.tenancy.seat_grant_models import OrganisationSeatGrant
from tests.unit.http.test_platform_organisations import (  # noqa: F401
    call,
    grant,
    operator,
    state,
)
from tests.unit.http.test_workspaces import workspace_state  # noqa: F401

OWNER_EMAIL = "admin@authorityclosers.com"


def until(days: int) -> str:
    return (seat_day(datetime.now(UTC)) + timedelta(days=days)).isoformat()


def as_owner(state):
    """The operator's account becomes the owner's own verified address (the allowlist)."""
    with Session(state.engine) as db, db.begin():
        db.get(Person, state.person).email = OWNER_EMAIL
    return state


async def give(state, body, *, key=None):
    return await call(state, "POST", f"/{state.tenant}/seat-grants", body=body, key=key or uuid4())


def grant_count(state) -> int:
    with Session(state.engine) as db:
        return db.scalar(select(func.count()).select_from(OrganisationSeatGrant))


async def test_an_operator_who_is_not_the_owner_reads_seats_but_cannot_grant(operator):
    state = operator
    seats = await call(state, path=f"/{state.tenant}/seats")
    assert seats.status_code == 200, seats.text
    body = PlatformSeatsResponse.model_validate_json(seats.text)
    assert body.can_grant is False and body.grants == [] and body.plan is None
    assert body.seats.total_seats == 0 and body.seats.active_members == 3
    refused = await give(state, {"seats": 4, "until": until(90), "reason": "Founding client"})
    assert refused.status_code == 403
    assert "Only the owner" in refused.json()["detail"]
    assert grant_count(state) == 0


async def test_reading_needs_the_read_capability(state):
    as_owner(state)
    await grant(state, "platform_organisations_manage")
    assert (await call(state, path=f"/{state.tenant}/seats")).status_code == 403


async def test_the_owner_without_the_manage_capability_cannot_grant(state):
    as_owner(state)
    await grant(state, "platform_tenants_read")
    view = await call(state, path=f"/{state.tenant}/seats")
    assert view.json()["can_grant"] is True  # the allowlist alone; the write checks both
    body = {"seats": 4, "until": until(90), "reason": "Founding client"}
    assert (await give(state, body)).status_code == 403
    assert grant_count(state) == 0


async def test_the_owner_grants_changes_and_ends_with_audit_and_replay(operator):
    state = as_owner(operator)
    key = uuid4()
    body = {"seats": 4, "until": until(90), "reason": "Founding client"}
    given = await give(state, body, key=key)
    assert given.status_code == 200, given.text
    view = PlatformSeatsResponse.model_validate_json(given.text)
    assert view.can_grant is True
    assert (view.seats.complimentary_seats, view.seats.total_seats) == (4, 4)
    assert view.seats.seats_available == 1  # owner, admin and rep hold three
    assert [(row.kind, row.seats, row.until.isoformat(), row.live) for row in view.grants] == [
        ("grant", 4, until(90), True)
    ]
    assert view.grants[0].granted_by == OWNER_EMAIL

    # A retry with the same key answers without a second grant; another body is refused.
    assert (await give(state, body, key=key)).status_code == 200
    assert grant_count(state) == 1
    assert (await give(state, dict(body, seats=5), key=key)).status_code == 409

    first = view.grants[0].id
    changed = await give(
        state,
        {"seats": 6, "until": until(180), "reason": "Extended", "supersedes_grant_id": str(first)},
    )
    assert changed.status_code == 200, changed.text
    assert PlatformSeatsResponse.model_validate_json(changed.text).seats.total_seats == 6
    again = await give(
        state,
        {"seats": 2, "until": until(30), "reason": "Late", "supersedes_grant_id": str(first)},
    )
    assert again.status_code == 409
    current = PlatformSeatsResponse.model_validate_json(changed.text).grants[0].id
    ended = await give(
        state, {"seats": 0, "reason": "Moved to paid", "supersedes_grant_id": str(current)}
    )
    assert ended.status_code == 200, ended.text
    final = PlatformSeatsResponse.model_validate_json(ended.text)
    assert final.seats.total_seats == 0
    assert [row.kind for row in final.grants] == ["end", "change", "grant"]

    with Session(state.engine) as db:
        events = db.scalars(
            select(AuditEvent)
            .where(AuditEvent.action == "organisation.seats_granted")
            .order_by(AuditEvent.sequence_no)
        ).all()
        assert [event.tenant_id for event in events] == [state.tenant] * 3
        assert [event.reason for event in events] == [
            "Founding client",
            "Extended",
            "Moved to paid",
        ]
        assert events[0].actor_person_id == state.person
        assert events[0].payload["before"] == {"complimentary_seats": 0, "total_seats": 0}
        assert events[0].payload["after"] == {"complimentary_seats": 4, "total_seats": 4}
        assert events[1].payload["replaced"]["seats"] == 4
        assert verify_audit_chain_sync(db, tenant_id=state.tenant).valid


async def test_the_directory_lists_seats_and_refuses_bad_grants(operator):
    state = as_owner(operator)
    for bad in (
        {"seats": 4, "until": until(-1), "reason": "Founding client"},
        {"seats": 4, "until": until(2000), "reason": "Founding client"},
        {"seats": 0, "until": until(30), "reason": "Founding client"},
        {"seats": 4, "reason": "Founding client"},
        {"seats": 4, "until": until(30), "reason": "x"},
        {"seats": 999, "until": until(30), "reason": "Founding client"},
    ):
        response = await give(state, bad)
        assert response.status_code == 422, (bad, response.text)
    assert grant_count(state) == 0
    assert (await give(state, {"seats": 3, "until": until(30), "reason": "Pilot"})).is_success
    rows = {row["name"]: row for row in (await call(state)).json()["organisations"]}
    assert (rows["Alpha"]["complimentary_seats"], rows["Alpha"]["paid_seats"]) == (3, 0)
    assert rows["Inactive"]["complimentary_seats"] == 0


async def test_grants_need_a_safe_origin_and_a_registered_organisation(operator):
    state = as_owner(operator)
    body = {"seats": 4, "until": until(30), "reason": "Founding client"}
    response = await call(
        state, "POST", f"/{state.tenant}/seat-grants", body=body, key=uuid4(), origin=None
    )
    assert response.status_code == 403
    missing = await call(state, "POST", f"/{uuid4()}/seat-grants", body=body, key=uuid4())
    assert missing.status_code == 404
    protected = await call(
        state, "POST", f"/{state.tenants['Other']}/seat-grants", body=body, key=uuid4()
    )
    assert protected.status_code == 404
    assert grant_count(state) == 0


async def test_removing_a_member_frees_a_complimentary_seat(operator):
    state = as_owner(operator)
    assert (await give(state, {"seats": 3, "until": until(30), "reason": "Pilot"})).is_success
    view = PlatformSeatsResponse.model_validate_json(
        (await call(state, path=f"/{state.tenant}/seats")).text
    )
    assert (view.seats.active_members, view.seats.seats_available) == (3, 0)
    removed = await call(
        state,
        "DELETE",
        f"/{state.tenant}/members/{state.member}",
        body={"reason": "Fictional leaver"},
        key=uuid4(),
    )
    assert removed.status_code == 204, removed.text
    view = PlatformSeatsResponse.model_validate_json(
        (await call(state, path=f"/{state.tenant}/seats")).text
    )
    assert (view.seats.active_members, view.seats.seats_available) == (2, 1)
    with Session(state.engine) as db:
        assert db.get(Membership, (state.tenant, state.member)).status == "inactive"
