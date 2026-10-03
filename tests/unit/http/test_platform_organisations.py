"""Fictional HTTP evidence for platform-operator organisation member management."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain_sync
from ac_platform.authorization.application import CapabilityApplication
from ac_platform.authorization.policy import CapabilityScope
from ac_platform.http.auth import install_identity_http
from ac_platform.http.organisation import MembersResponse
from ac_platform.http.platform_organisations import (
    PlatformOrganisationsResponse,
    install_platform_organisations_http,
)
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.application import AsyncIdentityApplication
from ac_platform.identity.models import Person
from ac_platform.tenancy.models import Membership, Organisation, OrganisationInvite
from tests.unit.http.test_workspaces import (  # noqa: F401
    OTHER_TOKEN,
    TOKEN,
    HttpDatabase,
    workspace_state,
)
from tests.unit.organisations.test_service import seed_paid_seats

ORIGIN = "https://admin.authorityclosers.test"
REASON = "AUT-446 fictional support request"
READ = "platform_tenants_read"
MANAGE = "platform_organisations_manage"


@pytest.fixture
def state(workspace_state):  # noqa: F811
    """The operator (``state.person``) is not a member of the Alpha organisation."""
    state = workspace_state
    state.tenant = state.tenants["Alpha"]
    state.settings = state.settings.model_copy(
        update={
            "public_learner_tenant_id": state.tenants["Beta"],
            "operations_tenant_id": state.tenants["Other"],
        }
    )
    state.owner, state.admin, state.member = (uuid4() for _ in range(3))
    now = datetime.now(UTC)
    with Session(state.engine) as db, db.begin():
        # The registry rows on the protected tenants prove the 404 is a fence.
        db.add_all(
            Organisation(
                tenant_id=state.tenants[name],
                creation_command_id=uuid4(),
                domain_verification_token="f" * 43,
                created_at=now - timedelta(days=age),
            )
            for name, age in (("Alpha", 2), ("Inactive", 1), ("Beta", 0), ("Other", 0))
        )
        operator = db.get(Membership, (state.tenant, state.person))
        operator.status, operator.ended_at = "inactive", now
        db.add_all(
            Person(id=person, email=f"{label}@example.test", email_verified_at=now)
            for label, person in (
                ("owner", state.owner),
                ("admin", state.admin),
                ("rep", state.member),
            )
        )
        db.add(Person(id=uuid4(), email="joiner@example.test", email_verified_at=now))
        db.flush()
        db.add_all(
            Membership(tenant_id=state.tenant, person_id=person, role=role)
            for role, person in (
                ("owner", state.owner),
                ("admin", state.admin),
                ("member", state.member),
            )
        )
        db.flush()
        asyncio.run(seed_paid_seats(HttpDatabase(db), state.tenant, state.owner))

    @asynccontextmanager
    async def sessions():
        with Session(state.engine) as db:
            yield HttpDatabase(db)

    state.app = FastAPI()
    register_problem_handlers(state.app)
    actor = install_identity_http(state.app, settings=state.settings, sessions=cast(Any, sessions))
    install_platform_organisations_http(state.app, settings=state.settings, require_actor=actor)
    return state


async def grant(state, *permissions):
    with Session(state.engine) as db, db.begin():
        database = cast(Any, HttpDatabase(db))
        app = CapabilityApplication(database, operations_tenant_id=state.tenants["Other"])
        await app.bootstrap_first_manager(
            person_id=state.other, command_id=uuid4(), reason="Synthetic first manager"
        )
        manager = (
            await AsyncIdentityApplication(
                database, token_pepper=state.settings.session_token_pepper.get_secret_value()
            ).resolve_actor(OTHER_TOKEN)
        ).actor
        for permission in permissions:
            await app.grant(
                manager,
                subject_person_id=state.person,
                command_id=uuid4(),
                permission=permission,
                scope=CapabilityScope("platform"),
                reason="Synthetic platform assignment",
            )


@pytest.fixture
async def operator(state):
    await grant(state, READ, MANAGE)
    return state


async def call(
    state, method="GET", path="", *, body=None, token=TOKEN, key=None, host="admin", origin=ORIGIN
):
    headers = {} if token is None else {"cookie": f"ac_session={token}"}
    if key is not None:
        headers["Idempotency-Key"] = str(key)
    if method != "GET" and origin is not None:
        headers["origin"] = origin
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=state.app),
        base_url=f"https://{host}.authorityclosers.test",
    ) as client:
        return await client.request(
            method, "/v1/platform/organisations" + path, headers=headers, json=body
        )


def audits(state):
    with Session(state.engine) as db:
        assert verify_audit_chain_sync(db, tenant_id=state.tenant).valid
        return list(
            db.scalars(
                select(AuditEvent)
                .where(AuditEvent.tenant_id == state.tenant)
                .order_by(AuditEvent.sequence_no)
            )
        )


def roles(state):
    with Session(state.engine) as db:
        return {
            row.person_id: (row.role, row.status)
            for row in db.scalars(select(Membership).where(Membership.tenant_id == state.tenant))
        }


def operator_event(state, action, resource_id):
    (event,) = audits(state)
    assert event.action == action and event.resource_id == str(resource_id)
    # The audit event names the operator and the reason.
    assert event.actor_person_id == state.person and event.actor_type == "person"
    assert event.reason == REASON
    return event


def writes(state):
    org = f"/{state.tenant}"
    return [
        ("POST", f"{org}/members", {"email": "joiner@example.test", "role": "member"}),
        ("PATCH", f"{org}/members/{state.member}", {"role": "admin"}),
        ("DELETE", f"{org}/members/{state.member}", {}),
        ("POST", f"{org}/owner", {"person_id": str(state.member)}),
        ("DELETE", f"{org}/invites/{uuid4()}", {}),
    ]


async def test_session_capability_surface_and_origin_are_required(state):
    reads = ["", f"/{state.tenant}/members"]
    for path in reads:
        assert (await call(state, path=path, token=None)).status_code == 401
        assert (await call(state, path=path)).status_code == 403
    for method, path, body in writes(state):
        body = {**body, "reason": REASON}
        assert (
            await call(state, method, path, body=body, key=uuid4(), token=None)
        ).status_code == 401
        assert (await call(state, method, path, body=body, key=uuid4())).status_code == 403
    await grant(state, READ)
    # Read access alone never writes; the tenant-owner session has no platform access.
    for method, path, body in writes(state):
        body = {**body, "reason": REASON}
        assert (await call(state, method, path, body=body, key=uuid4())).status_code == 403
    for path in reads:
        assert (await call(state, path=path)).status_code == 200
        assert (await call(state, path=path, token=OTHER_TOKEN)).status_code == 403
        assert (await call(state, path=path, host="learner")).status_code == 403
    assert audits(state) == [] and roles(state)[state.member] == ("member", "active")


async def test_manage_capability_alone_does_not_read_and_writes_need_the_admin_origin(state):
    await grant(state, MANAGE)
    assert (await call(state)).status_code == 403
    assert (await call(state, path=f"/{state.tenant}/members")).status_code == 403
    body = {"role": "admin", "reason": REASON}
    path = f"/{state.tenant}/members/{state.member}"
    assert (
        await call(state, "PATCH", path, body=body, key=uuid4(), origin=None)
    ).status_code == 403
    assert (
        await call(state, "PATCH", path, body=body, key=uuid4(), host="learner")
    ).status_code == 403
    assert audits(state) == []
    assert (await call(state, "PATCH", path, body=body, key=uuid4())).status_code == 200


async def test_lists_registered_organisations_newest_first(operator):
    state = operator
    response = await call(state)
    assert response.status_code == 200, response.text
    PlatformOrganisationsResponse.model_validate_json(response.text)
    rows = response.json()["organisations"]
    # The operations and public tenants are never listed.
    assert [(row["name"], row["member_count"]) for row in rows] == [("Inactive", 0), ("Alpha", 3)]
    assert rows[1]["tenant_id"] == str(state.tenant)
    assert set(rows[0]) == {"tenant_id", "name", "member_count", "created_at"}
    assert datetime.fromisoformat(rows[0]["created_at"]) > datetime.fromisoformat(
        rows[1]["created_at"]
    )


async def test_reads_the_member_directory_of_any_organisation(operator):
    state = operator
    with Session(state.engine) as db, db.begin():
        db.add(
            OrganisationInvite(
                tenant_id=state.tenant,
                email_normalized="pending@example.test",
                role="member",
                command_id=uuid4(),
            )
        )
    response = await call(state, path=f"/{state.tenant}/members")
    assert response.status_code == 200, response.text
    MembersResponse.model_validate_json(response.text)
    assert [(row["email"], row["role"], row["status"]) for row in response.json()["members"]] == [
        ("admin@example.test", "admin", "active"),
        ("owner@example.test", "owner", "active"),
        ("rep@example.test", "member", "active"),
        ("pending@example.test", "member", "invited"),
    ]


@pytest.mark.parametrize("tenant", ["Other", "Beta", "Deleted", "unknown"])
async def test_protected_and_unknown_tenants_are_not_found(operator, tenant):
    state = operator
    tenant_id = uuid4() if tenant == "unknown" else state.tenants[tenant]
    assert (await call(state, path=f"/{tenant_id}/members")).status_code == 404
    for method, path, body in writes(state):
        path = path.replace(str(state.tenant), str(tenant_id))
        response = await call(state, method, path, body={**body, "reason": REASON}, key=uuid4())
        assert response.status_code == 404, (method, path, response.text)
        assert response.json()["detail"] == "Organisation not found."


async def test_adds_a_known_person_with_stable_replay(operator):
    state = operator
    path, key = f"/{state.tenant}/members", uuid4()
    body = {"email": " Joiner@Example.test ", "role": "admin", "reason": REASON}
    response = await call(state, "POST", path, body=body, key=key)
    assert response.status_code == 200, response.text
    row = response.json()
    assert (row["email"], row["role"], row["status"]) == ("joiner@example.test", "admin", "active")
    assert row in (await call(state, path=path)).json()["members"]
    # A same-intent replay is stable; a changed role or reason is refused.
    assert (await call(state, "POST", path, body=body, key=key)).json() == row
    for change in ({"role": "member"}, {"reason": "another fictional reason"}):
        assert (
            await call(state, "POST", path, body={**body, **change}, key=key)
        ).status_code == 409
    event = operator_event(state, "organisation.member_added", row["person_id"])
    assert event.payload["http_intent"]["operator_reference"] == REASON


async def test_invites_an_unknown_email_and_revokes_the_invite(operator):
    state = operator
    path = f"/{state.tenant}/members"
    body = {"email": "new-hire@example.test", "role": "member", "reason": REASON}
    invited = await call(state, "POST", path, body=body, key=uuid4())
    assert invited.status_code == 200, invited.text
    invite_id = invited.json()["invite_id"]
    assert invited.json()["status"] == "invited" and invited.json()["person_id"] is None
    (event,) = audits(state)
    assert event.action == "organisation.member_invited" and event.reason == REASON
    assert event.actor_person_id == state.person

    key, revoke = uuid4(), f"/{state.tenant}/invites/{invite_id}"
    assert (
        await call(state, "DELETE", revoke, body={"reason": REASON}, key=key)
    ).status_code == 204
    assert (
        await call(state, "DELETE", revoke, body={"reason": REASON}, key=key)
    ).status_code == 204
    assert (
        await call(state, "DELETE", revoke, body={"reason": "another reason"}, key=key)
    ).status_code == 409
    assert (
        await call(state, "DELETE", revoke, body={"reason": REASON}, key=uuid4())
    ).status_code == 404
    assert (await call(state, path=path)).json()["members"][-1]["status"] == "active"
    events = audits(state)
    assert [item.action for item in events] == [
        "organisation.member_invited",
        "organisation.invite_revoked",
    ]
    assert events[1].actor_person_id == state.person and events[1].reason == REASON
    assert events[1].resource_id == invite_id


async def test_changes_any_non_owner_role_with_stable_replay(operator):
    state = operator
    path, key = f"/{state.tenant}/members/{state.admin}", uuid4()
    body = {"role": "member", "reason": REASON}
    response = await call(state, "PATCH", path, body=body, key=key)
    assert response.status_code == 200, response.text
    assert response.json()["role"] == "member"
    assert (await call(state, "PATCH", path, body=body, key=key)).json() == response.json()
    assert (
        await call(state, "PATCH", path, body={**body, "role": "admin"}, key=key)
    ).status_code == 409
    assert roles(state)[state.admin] == ("member", "active")
    event = operator_event(state, "organisation.member_role_changed", state.admin)
    assert event.payload["before"]["role"] == "admin"
    assert event.payload["http_intent"]["operator_reference"] == REASON


async def test_removal_leaves_an_inactive_membership(operator):
    state = operator
    path, key = f"/{state.tenant}/members/{state.admin}", uuid4()
    assert (await call(state, "DELETE", path, body={"reason": REASON}, key=key)).status_code == 204
    assert (await call(state, "DELETE", path, body={"reason": REASON}, key=key)).status_code == 204
    # The membership row stays; a fresh command finds no active member.
    assert roles(state)[state.admin] == ("admin", "inactive")
    assert (
        await call(state, "DELETE", path, body={"reason": REASON}, key=uuid4())
    ).status_code == 404
    operator_event(state, "organisation.member_removed", state.admin)


async def test_owner_guards_refuse_role_change_removal_and_self_transfer(operator):
    state = operator
    org = f"/{state.tenant}"
    refused = [
        ("PATCH", f"{org}/members/{state.owner}", {"role": "admin"}, "Transfer ownership first."),
        ("DELETE", f"{org}/members/{state.owner}", {}, "Transfer ownership first."),
        (
            "POST",
            f"{org}/owner",
            {"person_id": str(state.owner)},
            "This person is already the owner.",
        ),
    ]
    for method, path, body, detail in refused:
        response = await call(state, method, path, body={**body, "reason": REASON}, key=uuid4())
        assert response.status_code == 409, (method, path, response.text)
        assert response.json()["detail"] == detail
    unknown = {"person_id": str(uuid4()), "reason": REASON}
    assert (await call(state, "POST", f"{org}/owner", body=unknown, key=uuid4())).status_code == 404
    assert roles(state)[state.owner] == ("owner", "active") and audits(state) == []


async def test_transfer_swaps_the_owner_and_former_owner_roles(operator):
    state = operator
    path, key = f"/{state.tenant}/owner", uuid4()
    body = {"person_id": str(state.member), "reason": REASON}
    response = await call(state, "POST", path, body=body, key=key)
    assert response.status_code == 200, response.text
    result = response.json()
    assert (result["owner"]["person_id"], result["owner"]["role"]) == (str(state.member), "owner")
    assert (result["former_owner"]["person_id"], result["former_owner"]["role"]) == (
        str(state.owner),
        "admin",
    )
    assert (await call(state, "POST", path, body=body, key=key)).json() == result
    other = {"person_id": str(state.admin), "reason": REASON}
    assert (await call(state, "POST", path, body=other, key=key)).status_code == 409
    assert roles(state) == {
        state.person: ("learner", "inactive"),
        state.owner: ("admin", "active"),
        state.admin: ("admin", "active"),
        state.member: ("owner", "active"),
    }
    event = operator_event(state, "organisation.ownership_transferred", state.member)
    assert event.payload["before"]["owner_person_id"] == str(state.owner)
    assert event.payload["after"]["former_owner_person_id"] == str(state.owner)


@pytest.mark.parametrize(
    "body", [{}, {"reason": "no"}, {"reason": "x" * 201}, {"reason": REASON, "extra": 1}]
)
async def test_a_bounded_reason_and_idempotency_key_are_required(operator, body):
    state = operator
    path = f"/{state.tenant}/members/{state.member}"
    assert (await call(state, "DELETE", path, body=body, key=uuid4())).status_code == 422
    missing_key = await call(state, "DELETE", path, body={"reason": REASON})
    assert missing_key.status_code == 422
    bad_key = await call(state, "DELETE", path, body={"reason": REASON}, key="not-a-uuid")
    assert bad_key.status_code in {400, 422}
    assert roles(state)[state.member] == ("member", "active") and audits(state) == []
