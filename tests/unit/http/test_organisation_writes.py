"""Fictional HTTP contract evidence using canonical cookies and relational state."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid1, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain_sync
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionUsage as Usage,
)
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.tenancy.models import (
    Membership,
    Organisation,
    OrganisationInvite,
)
from tests.unit.http.test_organisation import call, state  # noqa: F401
from tests.unit.http.test_organisation_invites import identity_cookie, person_call
from tests.unit.http.test_workspaces import (  # noqa: F401
    OTHER_TOKEN,
    TOKEN,
    HttpDatabase,
    workspace_state,
)


async def test_invite_replay_conflict_revoke_and_audit(state):  # noqa: F811 - imported pytest fixture
    key = uuid4()
    body = {"email": "invite@example.test", "role": "admin"}
    response = await call(state, "POST", "/members", body=body, key=key)
    assert response.status_code == 200, response.text
    row = response.json()
    assert row == {
        "person_id": None,
        "invite_id": row["invite_id"],
        "name": None,
        "email": body["email"],
        "role": "admin",
        "status": "invited",
        "joined_at": None,
        "last_active_at": None,
        "minutes_used_30d": 0.0,
        "calls_30d": 0,
    }
    assert (await call(state, "POST", "/members", body=body, key=key)).json() == row
    assert (
        await call(state, "POST", "/members", body=dict(body, role="member"), key=key)
    ).status_code == 409
    assert row in (await call(state, path="/members")).json()["members"]
    revoke_key = uuid4()
    assert (
        await call(state, "DELETE", f"/invites/{row['invite_id']}", key=revoke_key)
    ).status_code == 204
    assert (
        await call(state, "DELETE", f"/invites/{row['invite_id']}", key=revoke_key)
    ).status_code == 204
    assert (await call(state, "POST", "/members", body=body, key=key)).json() == row
    assert row not in (await call(state, path="/members")).json()["members"]
    with Session(state.engine) as db:
        invite = db.get(OrganisationInvite, UUID(row["invite_id"]))
        assert invite.status == "revoked" and invite.closed_at is not None
        audits = list(db.scalars(select(AuditEvent).where(AuditEvent.tenant_id == state.tenant)))
        assert len(audits) == 2
        assert all(a.actor_person_id == state.person for a in audits)
        assert verify_audit_chain_sync(db, tenant_id=state.tenant).valid


async def test_verified_invite_explicit_reactivation_and_stable_response(state):  # noqa: F811
    with Session(state.engine) as db, db.begin():
        membership = db.get(Membership, (state.tenant, state.member))
        membership.status, membership.ended_at = "inactive", datetime.now(UTC)
        membership.created_at = datetime.now(UTC) - timedelta(days=40)
    key = uuid4()
    body = {"email": "rep@example.test", "role": "member"}
    response = await call(state, "POST", "/members", body=body, key=key)
    assert response.status_code == 200, response.text
    row = response.json()
    assert row["person_id"] is None and row["invite_id"] is not None and row["status"] == "invited"
    with Session(state.engine) as db:
        assert db.get(Membership, (state.tenant, state.member)).status == "inactive"
    cookie = identity_cookie(state, state.member)
    accepted = await person_call(
        state, f"/invites/{row['invite_id']}/accept", method="POST", key=uuid4(), token=cookie
    )
    assert accepted.status_code == 200, accepted.text
    listed = next(
        r
        for r in (await call(state, path="/members")).json()["members"]
        if r["person_id"] == str(state.member)
    )
    assert listed["person_id"] == str(state.member) and listed["status"] == "active"
    assert datetime.fromisoformat(listed["joined_at"]) > datetime.now(UTC) - timedelta(minutes=1)
    with Session(state.engine) as db, db.begin():
        membership = db.get(Membership, (state.tenant, state.member))
        assert (
            membership.status == "active"
            and membership.ended_at is None
            and membership.revision == 1
        )
        assert membership.created_at < datetime.now(UTC).replace(tzinfo=None) - timedelta(days=30)
        db.get(Person, state.member).display_name = "Changed Fixture"
        db.add(
            Usage(
                id=uuid4(),
                tenant_id=state.tenant,
                person_id=state.member,
                submission_id=uuid4(),
                source_sha256="a" * 64,
                duration_evidence_sha256="b" * 64,
                reserved_seconds=120,
                policy_revision="fictional",
                created_at=datetime.now(UTC),
            )
        )
    current = next(
        r
        for r in (await call(state, path="/members")).json()["members"]
        if r["person_id"] == str(state.member)
    )
    assert current["name"] == "Changed Fixture" and current["minutes_used_30d"] == 2.0
    assert (await call(state, "POST", "/members", body=body, key=key)).json() == row


@pytest.mark.parametrize(
    "email,role,token,expected",
    [
        ("new@example.test", "admin", OTHER_TOKEN, 403),
        ("synthetic-owner@example.test", "member", OTHER_TOKEN, 403),
        ("synthetic-owner@example.test", "member", TOKEN, 409),
        ("rep@example.test", "admin", TOKEN, 409),
        ("new@example.test", "member", OTHER_TOKEN, 200),
    ],
)
async def test_add_permissions(state, email, role, token, expected):  # noqa: F811 - imported pytest fixture
    response = await call(
        state, "POST", "/members", body={"email": email, "role": role}, token=token, key=uuid4()
    )
    assert response.status_code == expected, response.text


@pytest.mark.parametrize("key", [None, "invalid", uuid1(), uuid4().hex, "urn:uuid:" + str(uuid4())])
async def test_canonical_uuid4_required(state, key):  # noqa: F811 - imported pytest fixture
    assert (
        await call(
            state,
            "POST",
            "/members",
            body={"email": "invite@example.test", "role": "member"},
            key=key,
        )
    ).status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {"email": "bad", "role": "member"},
        {"email": "invite@example.test", "role": "owner"},
        {"email": "invite@example.test", "role": "member", "tenant_id": "guessed"},
        {"email": 42, "role": "member"},
    ],
)
async def test_strict_input(state, body):  # noqa: F811 - imported pytest fixture
    assert (await call(state, "POST", "/members", body=body, key=uuid4())).status_code == 422


async def test_active_member_cannot_be_reinvited_to_bypass_roles(state):  # noqa: F811
    with Session(state.engine) as db, db.begin():
        db.get(Person, state.member).email_verified_at = None
    assert (
        await call(
            state,
            "POST",
            "/members",
            body={"email": "rep@example.test", "role": "member"},
            key=uuid4(),
        )
    ).status_code == 409
    with Session(state.engine) as db:
        assert db.scalar(select(func.count()).select_from(OrganisationInvite)) == 0


async def test_daily_limit_includes_invites_and_replay_does_not_consume(state):  # noqa: F811 - imported pytest fixture
    with Session(state.engine) as db, db.begin():
        db.add_all(
            [
                OrganisationInvite(
                    tenant_id=state.tenant,
                    email_normalized=f"seed{i}@example.test",
                    role="member",
                    command_id=uuid4(),
                )
                for i in range(49)
            ]
        )
    key = uuid4()
    body = {"email": "fiftieth@example.test", "role": "member"}
    accepted = await call(state, "POST", "/members", body=body, key=key)
    assert accepted.status_code == 200
    assert (
        await call(
            state, "POST", "/members", body=dict(body, email="extra@example.test"), key=uuid4()
        )
    ).status_code == 429
    assert (await call(state, "POST", "/members", body=body, key=key)).json() == accepted.json()


async def test_invite_wrong_tenant_member_and_changed_key_are_denied(state):  # noqa: F811 - imported pytest fixture
    key = uuid4()
    with Session(state.engine) as db, db.begin():
        other_tenant = state.tenants["Inactive"]
        db.add(
            Organisation(
                tenant_id=other_tenant,
                creation_command_id=uuid4(),
                domain_verification_token="s" * 43,
            )
        )
        db.flush()
        wrong = OrganisationInvite(
            tenant_id=other_tenant,
            email_normalized="wrong@example.test",
            role="member",
            command_id=uuid4(),
        )
        db.add(wrong)
        db.flush()
        wrong_id = wrong.id
    assert (await call(state, "DELETE", f"/invites/{wrong_id}", key=key)).status_code == 404
    invite = (
        await call(
            state,
            "POST",
            "/members",
            body={"email": "local@example.test", "role": "member"},
            key=key,
        )
    ).json()
    assert (
        await call(state, "DELETE", f"/invites/{invite['invite_id']}", key=key)
    ).status_code == 409
    with Session(state.engine) as db, db.begin():
        db.get(Membership, (state.tenant, state.person)).role = "member"
    assert (
        await call(state, "DELETE", f"/invites/{invite['invite_id']}", key=uuid4())
    ).status_code == 403


async def test_verified_email_lookup_matches_identity_case_insensitively(state):  # noqa: F811
    with Session(state.engine) as db, db.begin():
        db.get(Person, state.member).email = "Rep@Example.Test"
        member = db.get(Membership, (state.tenant, state.member))
        member.status, member.ended_at = "inactive", datetime.now(UTC)
    response = await call(
        state, "POST", "/members", body={"email": "REP@example.test", "role": "member"}, key=uuid4()
    )
    assert response.status_code == 200
    assert response.json()["person_id"] is None
    assert response.json()["invite_id"] is not None
    assert response.json()["email"] == "rep@example.test"


@pytest.mark.parametrize("method", ["POST", "DELETE"])
@pytest.mark.parametrize("token", [None, "bad"])
async def test_write_session_required(state, method, token):  # noqa: F811
    response = await call(
        state,
        method,
        "/members" if method == "POST" else f"/invites/{uuid4()}",
        body={"email": "pending@example.test", "role": "member"} if method == "POST" else None,
        key=uuid4(),
        token=token,
    )
    assert response.status_code == 401


@pytest.mark.parametrize("method", ["POST", "DELETE"])
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
    response = await call(
        state,
        method,
        "/members" if method == "POST" else f"/invites/{uuid4()}",
        body={"email": "pending@example.test", "role": "member"} if method == "POST" else None,
        key=uuid4(),
    )
    assert response.status_code == 404
    with Session(state.engine) as db:
        assert db.scalar(select(func.count()).select_from(OrganisationInvite)) == 0
        assert db.scalar(select(func.count()).select_from(AuditEvent)) == 0


@pytest.mark.parametrize("method", ["POST", "DELETE"])
@pytest.mark.parametrize("change,expected", [("role", 403), ("membership", 404), ("actor", 409)])
async def test_replay_rechecks_actor_membership_and_role(state, method, change, expected):  # noqa: F811
    body = {"email": "replay@example.test", "role": "member"}
    add_key, revoke_key = uuid4(), uuid4()
    added = await call(state, "POST", "/members", body=body, key=add_key)
    assert added.status_code == 200
    path = "/members" if method == "POST" else f"/invites/{added.json()['invite_id']}"
    key = add_key if method == "POST" else revoke_key
    if method == "DELETE":
        assert (await call(state, method, path, key=key)).status_code == 204
    with Session(state.engine) as db, db.begin():
        member = db.get(Membership, (state.tenant, state.person))
        if change == "role":
            member.role = "member"
        elif change == "membership":
            member.status, member.ended_at = "inactive", datetime.now(UTC)
    response = await call(
        state,
        method,
        path,
        body=body if method == "POST" else None,
        key=key,
        token=OTHER_TOKEN if change == "actor" else TOKEN,
    )
    assert response.status_code == expected
    with Session(state.engine) as db:
        assert db.scalar(select(func.count()).select_from(OrganisationInvite)) == 1
        assert db.scalar(select(func.count()).select_from(AuditEvent)) == (
            1 if method == "POST" else 2
        )
        assert verify_audit_chain_sync(db, tenant_id=state.tenant).valid


@pytest.mark.parametrize("method", ["POST", "DELETE"])
async def test_replay_key_cannot_move_to_another_organisation(state, method):  # noqa: F811
    body = {"email": "tenant-replay@example.test", "role": "member"}
    key = uuid4()
    added = await call(state, "POST", "/members", body=body, key=key)
    path = "/members" if method == "POST" else f"/invites/{added.json()['invite_id']}"
    if method == "DELETE":
        key = uuid4()
        assert (await call(state, method, path, key=key)).status_code == 204
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
        db.get(IdentitySession, state.session).selected_tenant_id = other_tenant
    response = await call(state, method, path, body=body if method == "POST" else None, key=key)
    assert response.status_code == 409
    with Session(state.engine) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(OrganisationInvite)
                .where(OrganisationInvite.tenant_id == other_tenant)
            )
            == 0
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.tenant_id == other_tenant)
            )
            == 0
        )


async def test_admin_cannot_change_existing_admin_through_add(state):  # noqa: F811
    response = await call(
        state,
        "POST",
        "/members",
        body={"email": "synthetic-other@example.test", "role": "member"},
        key=uuid4(),
        token=OTHER_TOKEN,
    )
    assert response.status_code == 403
    with Session(state.engine) as db:
        assert db.get(Membership, (state.tenant, state.other)).role == "admin"
        assert db.scalar(select(func.count()).select_from(AuditEvent)) == 0


async def test_previous_utc_day_additions_do_not_exhaust_today(state):  # noqa: F811
    yesterday = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
        microseconds=1
    )
    with Session(state.engine) as db, db.begin():
        db.add_all(
            OrganisationInvite(
                tenant_id=state.tenant,
                email_normalized=f"yesterday-{i}@example.test",
                role="member",
                command_id=uuid4(),
                created_at=yesterday,
            )
            for i in range(50)
        )
    response = await call(
        state,
        "POST",
        "/members",
        body={"email": "today@example.test", "role": "member"},
        key=uuid4(),
    )
    assert response.status_code == 200


async def test_revoke_key_cannot_change_target(state):  # noqa: F811
    invites = [
        (
            await call(
                state, "POST", "/members", body={"email": email, "role": "member"}, key=uuid4()
            )
        ).json()["invite_id"]
        for email in ("first@example.test", "second@example.test")
    ]
    key = uuid4()
    assert (await call(state, "DELETE", f"/invites/{invites[0]}", key=key)).status_code == 204
    assert (await call(state, "DELETE", f"/invites/{invites[1]}", key=key)).status_code == 409
    with Session(state.engine) as db:
        assert db.get(OrganisationInvite, UUID(invites[1])).status == "pending"
        assert db.scalar(select(func.count()).select_from(AuditEvent)) == 3
        assert verify_audit_chain_sync(db, tenant_id=state.tenant).valid
