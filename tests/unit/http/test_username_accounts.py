"""Admin admission and one-time credential delivery with fictional relational data."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ac_platform.identity.models import PasswordCredential, Person
from ac_platform.identity.password_auth import verify_password
from ac_platform.tenancy.models import Membership
from tests.unit.http.test_platform_organisations import (  # noqa: F401
    REASON,
    audits,
    call,
    workspace_state,
)
from tests.unit.http.test_platform_organisations import (
    operator as operator_fixture,
)
from tests.unit.http.test_platform_organisations import (
    state as state_fixture,
)


@pytest.fixture
def state(workspace_state):  # noqa: F811
    return state_fixture.__wrapped__(workspace_state)


@pytest.fixture
async def operator(state):
    return await operator_fixture.__wrapped__(state)


def account_body(**changes):
    return {"username": "example.rep", "display_name": "Example Rep", "reason": REASON, **changes}


async def test_admin_creates_email_less_member_and_replay_never_delivers_password(operator):
    path, key = f"/{operator.tenant}/accounts", uuid4()
    response = await call(operator, "POST", path, body=account_body(), key=key)
    assert response.status_code == 201
    result = response.json()
    assert result["username"] == "example.rep" and result["email"] is None
    assert result["password_change_required"] is True and result["membership_status"] == "active"
    assert response.headers["cache-control"] == "private, no-store"
    person_id = UUID(result["person_id"])
    with Session(operator.engine) as db:
        credential = db.scalar(
            select(PasswordCredential).where(PasswordCredential.person_id == person_id)
        )
        assert verify_password(result["temporary_password"], credential.password_hash)
        assert result["temporary_password"] not in credential.password_hash
        person = db.get(Person, person_id)
        assert person.email is None and person.email_verified_at is None
        assert person.username_verified_at is None
        assert db.get(Membership, (operator.tenant, person_id)).role == "member"
        assert db.scalar(select(func.count()).select_from(PasswordCredential)) == 1
    replay = await call(operator, "POST", path, body=account_body(), key=key)
    assert replay.status_code == 201
    assert replay.json()["temporary_password"] is None and replay.json()["replayed"] is True
    event = audits(operator)[0]
    assert event.actor_person_id == operator.person and event.reason == REASON
    assert result["temporary_password"] not in str(event.payload)
    assert "temporary_password" not in event.payload["result"]
    conflict = await call(
        operator, "POST", path, body=account_body(username="different.rep"), key=key
    )
    assert conflict.status_code == 409


@pytest.mark.parametrize(
    "body",
    [account_body(username="Rep@bad"), account_body(display_name="  "), account_body(email="bad")],
)
async def test_invalid_account_is_bounded_and_rolls_back(operator, body):
    response = await call(operator, "POST", f"/{operator.tenant}/accounts", body=body, key=uuid4())
    assert response.status_code in {400, 422}
    with Session(operator.engine) as db:
        assert db.scalar(select(func.count()).select_from(PasswordCredential)) == 0
    assert audits(operator) == []


async def test_account_creation_requires_session_capability_admin_origin_and_unprotected_org(state):
    path = f"/{state.tenant}/accounts"
    for options, status in (({"token": None}, 401), ({}, 403)):
        response = await call(state, "POST", path, body=account_body(), key=uuid4(), **options)
        assert response.status_code == status
    from tests.unit.http.test_platform_organisations import MANAGE, grant

    await grant(state, MANAGE)
    for options, status in (
        ({"host": "learner"}, 403),
        ({"origin": "https://foreign.test"}, 403),
        ({"origin": None}, 403),
    ):
        response = await call(state, "POST", path, body=account_body(), key=uuid4(), **options)
        assert response.status_code == status
    for tenant in (state.tenants["Beta"], state.tenants["Other"], uuid4()):
        response = await call(
            state, "POST", f"/{tenant}/accounts", body=account_body(), key=uuid4()
        )
        assert response.status_code == 404
    assert (await call(state, "POST", path, body=account_body())).status_code == 422
    assert audits(state) == []


async def test_collision_never_attaches_a_preexisting_person(operator):
    path = f"/{operator.tenant}/accounts"
    response = await call(
        operator, "POST", path, body=account_body(email="OWNER@example.test"), key=uuid4()
    )
    assert response.status_code == 409
    created = await call(
        operator, "POST", path, body=account_body(username=" EXAMPLE.Rep "), key=uuid4()
    )
    assert created.status_code == 201 and created.json()["username"] == "example.rep"
    duplicate = await call(
        operator, "POST", path, body=account_body(username="Example.Rep"), key=uuid4()
    )
    assert duplicate.status_code == 409
    assert len(audits(operator)) == 1


async def test_lost_initial_password_can_be_reissued_once_without_replay_or_reactivation(operator):
    created = (
        await call(
            operator, "POST", f"/{operator.tenant}/accounts", body=account_body(), key=uuid4()
        )
    ).json()
    person_id, key = UUID(created["person_id"]), uuid4()
    path = f"/{operator.tenant}/accounts/{person_id}/temporary-password"
    response = await call(operator, "POST", path, body={"reason": REASON}, key=key)
    assert response.status_code == 200
    reissued = response.json()
    with Session(operator.engine) as db:
        verifier = db.scalar(
            select(PasswordCredential).where(PasswordCredential.person_id == person_id)
        ).password_hash
        assert verify_password(reissued["temporary_password"], verifier)
        assert not verify_password(created["temporary_password"], verifier)
    replay = await call(operator, "POST", path, body={"reason": REASON}, key=key)
    assert replay.status_code == 200 and replay.json()["temporary_password"] is None
    for event in audits(operator):
        assert created["temporary_password"] not in str(event.payload)
        assert reissued["temporary_password"] not in str(event.payload)
    with Session(operator.engine) as db, db.begin():
        membership = db.get(Membership, (operator.tenant, person_id))
        membership.status = "inactive"
        membership.ended_at = datetime.now(UTC)
    refused = await call(operator, "POST", path, body={"reason": REASON}, key=uuid4())
    assert refused.status_code == 404
    replay_creation = await call(
        operator,
        "POST",
        f"/{operator.tenant}/accounts",
        body=account_body(),
        key=UUID(audits(operator)[0].request_id),
    )
    assert replay_creation.json()["membership_status"] == "inactive"
