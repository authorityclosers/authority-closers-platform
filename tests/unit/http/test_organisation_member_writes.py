"""Fictional HTTP evidence for role change, inactive removal and ownership transfer."""

from datetime import UTC, datetime
from uuid import uuid1, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain_sync
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.tenancy.models import Membership, Organisation
from tests.unit.http.test_organisation import call, state  # noqa: F401
from tests.unit.http.test_workspaces import (  # noqa: F401
    OTHER_TOKEN,
    TOKEN,
    workspace_state,
)


def audits(state):  # noqa: F811
    with Session(state.engine) as db:
        assert verify_audit_chain_sync(db, tenant_id=state.tenant).valid
        return list(
            db.scalars(
                select(AuditEvent)
                .where(AuditEvent.tenant_id == state.tenant)
                .order_by(AuditEvent.sequence_no)
            )
        )


def roles(state):  # noqa: F811
    with Session(state.engine) as db:
        return {
            row.person_id: (row.role, row.status)
            for row in db.scalars(select(Membership).where(Membership.tenant_id == state.tenant))
        }


def other_organisation_member(state):  # noqa: F811
    outsider = uuid4()
    with Session(state.engine) as db, db.begin():
        db.add(
            Organisation(
                tenant_id=state.tenants["Inactive"],
                creation_command_id=uuid4(),
                domain_verification_token="s" * 43,
            )
        )
        db.add(
            Person(id=outsider, email="outsider@example.test", email_verified_at=datetime.now(UTC))
        )
        db.flush()
        db.add(Membership(tenant_id=state.tenants["Inactive"], person_id=outsider, role="member"))
    return outsider


def deactivate(state, person_id):  # noqa: F811
    with Session(state.engine) as db, db.begin():
        membership = db.get(Membership, (state.tenant, person_id))
        membership.status, membership.ended_at = "inactive", datetime.now(UTC)


async def test_owner_changes_role_with_stable_replay(state):  # noqa: F811
    key = uuid4()
    path = f"/members/{state.member}"
    response = await call(state, "PATCH", path, body={"role": "admin"}, key=key)
    assert response.status_code == 200, response.text
    row = response.json()
    assert row["person_id"] == str(state.member) and row["role"] == "admin"
    assert row["status"] == "active" and row["invite_id"] is None
    assert row in (await call(state, path="/members")).json()["members"]
    # A same-intent replay is stable; a changed role, target or actor is refused.
    assert (await call(state, "PATCH", path, body={"role": "admin"}, key=key)).json() == row
    assert (await call(state, "PATCH", path, body={"role": "member"}, key=key)).status_code == 409
    assert (
        await call(state, "PATCH", f"/members/{state.other}", body={"role": "admin"}, key=key)
    ).status_code == 409
    assert (
        await call(state, "PATCH", path, body={"role": "admin"}, key=key, token=OTHER_TOKEN)
    ).status_code == 409
    assert roles(state)[state.member] == ("admin", "active")
    (event,) = audits(state)
    assert event.action == "organisation.member_role_changed"
    assert event.actor_person_id == state.person and event.resource_id == str(state.member)
    assert event.payload["before"]["role"] == "member"
    assert event.payload["after"]["role"] == "admin"


@pytest.mark.parametrize("actor_role", ["admin", "member"])
async def test_only_the_owner_changes_roles(state, actor_role):  # noqa: F811
    with Session(state.engine) as db, db.begin():
        db.get(Membership, (state.tenant, state.other)).role = actor_role
    response = await call(
        state,
        "PATCH",
        f"/members/{state.member}",
        body={"role": "admin"},
        key=uuid4(),
        token=OTHER_TOKEN,
    )
    assert response.status_code == 403
    assert roles(state)[state.member] == ("member", "active") and audits(state) == []


@pytest.mark.parametrize("target", ["owner", "unknown", "inactive", "wrong_org"])
async def test_role_change_refuses_protected_and_foreign_targets(state, target):  # noqa: F811
    outsider = other_organisation_member(state)
    if target == "inactive":
        deactivate(state, state.member)
    person_id = {
        "owner": state.person,
        "unknown": uuid4(),
        "inactive": state.member,
        "wrong_org": outsider,
    }[target]
    before = roles(state)
    response = await call(
        state, "PATCH", f"/members/{person_id}", body={"role": "admin"}, key=uuid4()
    )
    assert response.status_code == (409 if target == "owner" else 404)
    assert response.json()["detail"] == (
        "Transfer ownership first." if target == "owner" else "Member not found."
    )
    assert roles(state) == before and audits(state) == []
    with Session(state.engine) as db:
        assert db.get(Membership, (state.tenants["Inactive"], outsider)).role == "member"


@pytest.mark.parametrize(
    "actor_role,target,expected",
    [
        ("owner", "admin", 204),
        ("owner", "member", 204),
        ("owner", "self", 409),
        ("admin", "member", 204),
        ("admin", "admin", 403),
        ("admin", "owner", 409),
        ("admin", "self", 204),
        ("member", "self", 204),
        ("member", "member", 403),
        ("member", "owner", 403),
    ],
)
async def test_removal_boundaries_keep_the_membership(state, actor_role, target, expected):  # noqa: F811
    # The owner acts with TOKEN; an admin or member acts with OTHER_TOKEN.
    token = TOKEN if actor_role == "owner" else OTHER_TOKEN
    actor = state.person if actor_role == "owner" else state.other
    with Session(state.engine) as db, db.begin():
        db.get(Membership, (state.tenant, state.other)).role = (
            "admin" if actor_role == "owner" else actor_role
        )
        if actor_role == "admin" and target == "admin":
            db.get(Membership, (state.tenant, state.member)).role = "admin"
    person_id = {
        "self": actor,
        "owner": state.person,
        "admin": state.other if actor_role == "owner" else state.member,
        "member": state.member,
    }[target]
    before = roles(state)
    key = uuid4()
    response = await call(state, "DELETE", f"/members/{person_id}", key=key, token=token)
    assert response.status_code == expected, response.text
    if expected != 204:
        if expected == 409:
            assert response.json()["detail"] == "Transfer ownership first."
        assert roles(state) == before and audits(state) == []
        return
    with Session(state.engine) as db:
        membership = db.get(Membership, (state.tenant, person_id))
        assert membership.status == "inactive" and membership.ended_at is not None
        assert membership.role == before[person_id][0] and membership.revision == 1
    (event,) = audits(state)
    assert event.action == "organisation.member_removed"
    assert event.actor_person_id == actor and event.resource_id == str(person_id)
    listed = (await call(state, path="/members")).json()["members"]
    assert str(person_id) not in {row["person_id"] for row in listed}
    replay = await call(state, "DELETE", f"/members/{person_id}", key=key, token=token)
    # A person who removed themself is no longer a member of the organisation.
    assert replay.status_code == (404 if target == "self" else 204)
    assert len(audits(state)) == 1


async def test_removal_refuses_foreign_inactive_and_changed_requests(state):  # noqa: F811
    outsider = other_organisation_member(state)
    for person_id in (uuid4(), outsider):
        response = await call(state, "DELETE", f"/members/{person_id}", key=uuid4())
        assert response.status_code == 404 and response.json()["detail"] == "Member not found."
    key = uuid4()
    assert (await call(state, "DELETE", f"/members/{state.member}", key=key)).status_code == 204
    assert (await call(state, "DELETE", f"/members/{state.member}", key=uuid4())).status_code == 404
    assert (await call(state, "DELETE", f"/members/{state.other}", key=key)).status_code == 409
    assert (
        await call(state, "DELETE", f"/members/{state.member}", key=key, token=OTHER_TOKEN)
    ).status_code == 409
    assert roles(state)[state.other] == ("admin", "active") and len(audits(state)) == 1
    with Session(state.engine) as db:
        assert db.get(Membership, (state.tenants["Inactive"], outsider)).status == "active"


@pytest.mark.parametrize("target_role", ["admin", "member"])
async def test_transfer_swaps_roles_with_exactly_one_owner(state, target_role):  # noqa: F811
    target = state.other if target_role == "admin" else state.member
    with Session(state.engine) as db:
        created = db.get(Membership, (state.tenant, state.person)).created_at
    key = uuid4()
    response = await call(state, "POST", "/owner", body={"person_id": str(target)}, key=key)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"owner", "former_owner"}
    assert body["owner"]["person_id"] == str(target) and body["owner"]["role"] == "owner"
    assert body["former_owner"]["person_id"] == str(state.person)
    assert body["former_owner"]["role"] == "admin"
    after = roles(state)
    assert [role for role, _ in after.values()].count("owner") == 1
    assert after[target] == ("owner", "active") and after[state.person] == ("admin", "active")
    with Session(state.engine) as db:
        former = db.get(Membership, (state.tenant, state.person))
        assert former.created_at == created and former.revision == 1
    assert (await call(state)).json()["role"] == "admin"
    # The former owner's same-intent replay is stable after losing authority;
    # a changed target or a fresh request is refused without another effect.
    assert (
        await call(state, "POST", "/owner", body={"person_id": str(target)}, key=key)
    ).json() == body
    assert (
        await call(state, "POST", "/owner", body={"person_id": str(state.person)}, key=key)
    ).status_code == 409
    assert (
        await call(state, "POST", "/owner", body={"person_id": str(target)}, key=uuid4())
    ).status_code == 403
    assert roles(state) == after
    (event,) = audits(state)
    assert event.action == "organisation.ownership_transferred"
    assert event.actor_person_id == state.person and event.resource_id == str(target)
    assert event.payload["before"] == {
        "owner_person_id": str(state.person),
        "target_role": target_role,
    }


async def test_new_owner_can_transfer_back_and_changed_actor_is_refused(state):  # noqa: F811
    key = uuid4()
    body = {"person_id": str(state.other)}
    assert (await call(state, "POST", "/owner", body=body, key=key)).status_code == 200
    assert (
        await call(state, "POST", "/owner", body=body, key=key, token=OTHER_TOKEN)
    ).status_code == 409
    back = await call(
        state,
        "POST",
        "/owner",
        body={"person_id": str(state.person)},
        key=uuid4(),
        token=OTHER_TOKEN,
    )
    assert back.status_code == 200
    after = roles(state)
    assert after[state.person] == ("owner", "active") and after[state.other] == ("admin", "active")
    assert len(audits(state)) == 2


@pytest.mark.parametrize("target", ["self", "unknown", "inactive", "wrong_org", "suspended"])
async def test_transfer_refuses_unavailable_targets(state, target):  # noqa: F811
    outsider = other_organisation_member(state)
    if target == "inactive":
        deactivate(state, state.member)
    if target == "suspended":
        with Session(state.engine) as db, db.begin():
            db.get(Person, state.member).status = "suspended"
    person_id = {
        "self": state.person,
        "unknown": uuid4(),
        "inactive": state.member,
        "wrong_org": outsider,
        "suspended": state.member,
    }[target]
    before = roles(state)
    response = await call(state, "POST", "/owner", body={"person_id": str(person_id)}, key=uuid4())
    assert response.status_code == (409 if target == "self" else 404)
    assert roles(state) == before and audits(state) == []


@pytest.mark.parametrize("actor_role", ["admin", "member"])
async def test_only_the_owner_transfers_ownership(state, actor_role):  # noqa: F811
    with Session(state.engine) as db, db.begin():
        db.get(Membership, (state.tenant, state.other)).role = actor_role
    before = roles(state)
    response = await call(
        state,
        "POST",
        "/owner",
        body={"person_id": str(state.other)},
        key=uuid4(),
        token=OTHER_TOKEN,
    )
    assert response.status_code == 403
    assert roles(state) == before and audits(state) == []


def request_for(state, method):  # noqa: F811
    if method == "POST":
        return "/owner", {"person_id": str(state.member)}
    return f"/members/{state.member}", ({"role": "admin"} if method == "PATCH" else None)


@pytest.mark.parametrize("method", ["PATCH", "DELETE", "POST"])
@pytest.mark.parametrize("key", [None, "invalid", uuid1(), uuid4().hex])
async def test_writes_require_canonical_uuid4(state, method, key):  # noqa: F811
    path, body = request_for(state, method)
    assert (await call(state, method, path, body=body, key=key)).status_code == 422
    assert audits(state) == []


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("PATCH", "/members/{member}", {"role": "owner"}),
        ("PATCH", "/members/{member}", {"role": "admin", "status": "inactive"}),
        ("PATCH", "/members/not-a-uuid", {"role": "admin"}),
        ("POST", "/owner", {"person_id": "{member}", "tenant_id": "guessed"}),
        ("POST", "/owner", {"person_id": 42}),
        ("POST", "/owner", {}),
    ],
)
async def test_strict_write_input(state, method, path, body):  # noqa: F811
    path = path.format(member=state.member)
    body = {k: v.format(member=state.member) if isinstance(v, str) else v for k, v in body.items()}
    assert (await call(state, method, path, body=body, key=uuid4())).status_code == 422
    assert audits(state) == []


@pytest.mark.parametrize("method", ["PATCH", "DELETE", "POST"])
@pytest.mark.parametrize("token", [None, "bad"])
async def test_write_session_required(state, method, token):  # noqa: F811
    path, body = request_for(state, method)
    response = await call(state, method, path, body=body, key=uuid4(), token=token)
    assert response.status_code == 401


@pytest.mark.parametrize("method", ["PATCH", "DELETE", "POST"])
@pytest.mark.parametrize("selected", [None, "Beta", "Other", "Inactive", "Suspended"])
async def test_write_requires_selected_active_organisation(state, method, selected):  # noqa: F811
    with Session(state.engine) as db, db.begin():
        if selected == "Other":
            db.add(
                Membership(tenant_id=state.tenants[selected], person_id=state.person, role="owner")
            )
            db.flush()
        db.get(IdentitySession, state.session).selected_tenant_id = (
            None if selected is None else state.tenants[selected]
        )
    before = roles(state)
    path, body = request_for(state, method)
    response = await call(state, method, path, body=body, key=uuid4())
    assert response.status_code == 404
    assert response.json()["detail"] == "No organisation selected."
    assert roles(state) == before
    with Session(state.engine) as db:
        assert db.scalar(select(func.count()).select_from(AuditEvent)) == 0


@pytest.mark.parametrize("method", ["PATCH", "DELETE", "POST"])
async def test_replay_key_cannot_move_to_another_organisation(state, method):  # noqa: F811
    key = uuid4()
    path, body = request_for(state, method)
    assert (await call(state, method, path, body=body, key=key)).status_code in {200, 204}
    other_tenant = state.tenants["Inactive"]
    with Session(state.engine) as db, db.begin():
        db.add(
            Organisation(
                tenant_id=other_tenant,
                creation_command_id=uuid4(),
                domain_verification_token="t" * 43,
            )
        )
        member = db.get(Membership, (other_tenant, state.person))
        member.status, member.ended_at, member.role = "active", None, "owner"
        db.add(Membership(tenant_id=other_tenant, person_id=state.member, role="member"))
        db.get(IdentitySession, state.session).selected_tenant_id = other_tenant
    response = await call(state, method, path, body=body, key=key)
    assert response.status_code == 409
    with Session(state.engine) as db:
        assert db.get(Membership, (other_tenant, state.member)).role == "member"
        assert db.get(Membership, (other_tenant, state.member)).status == "active"
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.tenant_id == other_tenant)
            )
            == 0
        )
