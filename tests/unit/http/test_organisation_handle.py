"""Fictional relational HTTP proof of the editable handle contract."""

from datetime import UTC, datetime
from uuid import uuid1, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain_sync
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.errors import DomainError
from ac_platform.organisations.service import OrganisationService
from ac_platform.tenancy.models import Membership, Organisation, Tenant
from tests.unit.http.test_organisation import call, state  # noqa: F401
from tests.unit.http.test_workspaces import TOKEN, workspace_state  # noqa: F401

RESERVED_HANDLES = [
    "admin",
    "api",
    "app",
    "www",
    "support",
    "help",
    "billing",
    "settings",
    "login",
    "signin",
    "signup",
    "static",
    "assets",
    "internal",
    "ops",
    "platform",
    "system",
    "root",
    "staff",
    "personal",
    "public",
    "me",
    "new",
    "organisation",
]
INVALID_HANDLES = [
    "",
    "a",
    "ab",
    "a" * 41,
    "-abc",
    "abc-",
    "a--b",
    "ABC",
    "a_b",
    "a b",
    " abc",
    "abc\n",
    "équipe",
]


def snapshot(state):  # noqa: F811
    with Session(state.engine) as db:
        assert verify_audit_chain_sync(db, tenant_id=state.tenant).valid
        tenant = db.get(Tenant, state.tenant)
        events = list(db.scalars(select(AuditEvent).where(AuditEvent.tenant_id == state.tenant)))
        return tenant.slug, tenant.revision, events


@pytest.mark.parametrize("role", ["owner", "admin", "member"])
async def test_profile_is_readable_by_every_active_member(state, role):  # noqa: F811
    with Session(state.engine) as db, db.begin():
        db.get(Membership, (state.tenant, state.person)).role = role
    response = await call(state, path="/profile")
    assert response.status_code == 200
    assert response.json() == {
        "tenant_id": str(state.tenant),
        "handle": "alpha",
        "name": "Alpha",
        "your_role": role,
    }
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "Cookie"
    assert snapshot(state) == ("alpha", 0, [])
    assert set((await call(state)).json()) == {
        "tenant_id",
        "name",
        "role",
        "verified_domains",
        "auto_join",
        "member_count",
    }


async def test_change_records_one_audit_and_replays_original_result(state):  # noqa: F811
    key = uuid4()
    response = await call(state, "PUT", "/handle", body={"handle": "fictional-team"}, key=key)
    assert response.status_code == 200, response.text
    expected = {
        "tenant_id": str(state.tenant),
        "handle": "fictional-team",
        "name": "Alpha",
        "your_role": "owner",
    }
    assert response.json() == expected
    assert (await call(state, path="/profile")).json() == expected
    assert (
        await call(state, "PUT", "/handle", body={"handle": "fictional-team"}, key=key)
    ).json() == expected
    slug, revision, (audit,) = snapshot(state)
    assert (slug, revision) == ("fictional-team", 1)
    assert audit.action == "organisation.handle_changed" and audit.request_id == str(key)
    assert audit.actor_person_id == state.person and audit.resource_id == str(state.tenant)
    assert audit.payload["before"] == {"handle": "alpha"}
    assert audit.payload["after"] == {"handle": "fictional-team"}
    assert (
        await call(state, "PUT", "/handle", body={"handle": "another-team"}, key=key)
    ).status_code == 409
    assert (
        await call(state, "PUT", "/handle", body={"handle": "another-team"}, key=uuid4())
    ).status_code == 200
    # A later rename does not alter the saved response or reapply the old handle.
    assert (
        await call(state, "PUT", "/handle", body={"handle": "fictional-team"}, key=key)
    ).json() == expected
    assert snapshot(state)[0] == "another-team" and len(snapshot(state)[2]) == 2


async def test_audit_failure_rolls_back_handle_change(state, monkeypatch):  # noqa: F811
    async def fail_audit(*args, **kwargs):
        raise DomainError("Fictional audit failure.")

    monkeypatch.setattr(OrganisationService, "_audit", fail_audit)
    response = await call(state, "PUT", "/handle", body={"handle": "fictional-team"}, key=uuid4())
    assert response.status_code == 422
    assert snapshot(state) == ("alpha", 0, [])


@pytest.mark.parametrize("handle", ["abc", "a-b", "a" * 40])
async def test_valid_handle_boundaries(state, handle):  # noqa: F811
    assert (
        await call(state, "PUT", "/handle", body={"handle": handle}, key=uuid4())
    ).status_code == 200
    assert snapshot(state)[0] == handle


@pytest.mark.parametrize("handle", INVALID_HANDLES + RESERVED_HANDLES)
async def test_invalid_and_reserved_handles_leave_state_unchanged(state, handle):  # noqa: F811
    assert (
        await call(state, "PUT", "/handle", body={"handle": handle}, key=uuid4())
    ).status_code == 422
    assert snapshot(state) == ("alpha", 0, [])


async def test_taken_handle_uses_case_insensitive_comparison(state):  # noqa: F811
    with Session(state.engine) as db, db.begin():
        db.get(Tenant, state.tenants["Beta"]).slug = "TAKEN-HANDLE"
    response = await call(state, "PUT", "/handle", body={"handle": "taken-handle"}, key=uuid4())
    assert response.status_code == 409 and response.json()["detail"] == "Handle taken"
    assert snapshot(state) == ("alpha", 0, [])
    assert (
        await call(state, "PUT", "/handle", body={"handle": "alpha"}, key=uuid4())
    ).status_code == 200


@pytest.mark.parametrize("role", ["admin", "member"])
async def test_only_owner_can_change_or_replay_handle(state, role):  # noqa: F811
    key = uuid4()
    assert (
        await call(state, "PUT", "/handle", body={"handle": "owner-team"}, key=key)
    ).status_code == 200
    with Session(state.engine) as db, db.begin():
        db.get(Membership, (state.tenant, state.person)).role = role
    for request_key in (key, uuid4()):
        response = await call(
            state, "PUT", "/handle", body={"handle": "owner-team"}, key=request_key
        )
        assert response.status_code == 403
    assert snapshot(state)[0] == "owner-team" and len(snapshot(state)[2]) == 1


@pytest.mark.parametrize("selected", [None, "Beta", "Other", "Inactive", "Suspended"])
@pytest.mark.parametrize("method,path", [("GET", "/profile"), ("PUT", "/handle")])
async def test_personal_protected_and_inactive_contexts_are_hidden(state, selected, method, path):  # noqa: F811
    with Session(state.engine) as db, db.begin():
        if selected in {"Beta", "Other"}:
            db.add(
                Organisation(
                    tenant_id=state.tenants[selected],
                    creation_command_id=uuid4(),
                    domain_verification_token="f" * 43,
                )
            )
            member = db.get(Membership, (state.tenants[selected], state.person))
            if member is None:
                db.add(
                    Membership(
                        tenant_id=state.tenants[selected], person_id=state.person, role="owner"
                    )
                )
            else:
                member.role = "owner"
        db.get(IdentitySession, state.session).selected_tenant_id = (
            None if selected is None else state.tenants[selected]
        )
        before = {t.id: t.slug for t in db.scalars(select(Tenant))}
    response = await call(
        state,
        method,
        path,
        body={"handle": "forbidden-team"} if method == "PUT" else None,
        key=uuid4(),
    )
    assert response.status_code == 404 and response.json()["detail"] == "No organisation selected"
    with Session(state.engine) as db:
        assert {t.id: t.slug for t in db.scalars(select(Tenant))} == before
    assert snapshot(state) == ("alpha", 0, [])


@pytest.mark.parametrize("key", [None, "bad", uuid1()])
async def test_handle_requires_uuid4_idempotency_key(state, key):  # noqa: F811
    assert (
        await call(state, "PUT", "/handle", body={"handle": "fictional-team"}, key=key)
    ).status_code == 422
    assert snapshot(state) == ("alpha", 0, [])


@pytest.mark.parametrize(
    "body", [{}, {"handle": 123}, {"handle": "fictional-team", "name": "Extra"}]
)
async def test_handle_body_is_strict(state, body):  # noqa: F811
    assert (await call(state, "PUT", "/handle", body=body, key=uuid4())).status_code == 422


@pytest.mark.parametrize("method,path", [("GET", "/profile"), ("PUT", "/handle")])
async def test_handle_requires_authentication_and_active_membership(state, method, path):  # noqa: F811
    assert (
        await call(state, method, path, body={"handle": "fictional-team"}, key=uuid4(), token=None)
    ).status_code == 401
    with Session(state.engine) as db, db.begin():
        member = db.get(Membership, (state.tenant, state.person))
        member.status, member.ended_at = "inactive", datetime.now(UTC)
    assert (
        await call(state, method, path, body={"handle": "fictional-team"}, key=uuid4(), token=TOKEN)
    ).status_code == 404
