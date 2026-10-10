"""Explicit acceptance, expiry and durable mail with fictional identities."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from hmac import digest
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain_sync
from ac_platform.billing.order_models import BillingPeriod
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.organisations.invite_email import (
    ORGANISATION_INVITATION_JOB,
    resolve_organisation_invitation_message,
)
from ac_platform.organisations.sign_in import join_at_sign_in_best_effort
from ac_platform.outbox.models import Job, OutboxEvent
from ac_platform.providers.ports import PermanentProviderError
from ac_platform.providers.resend_email import render_email
from ac_platform.tenancy.models import (
    Membership,
    OrganisationDomainSetting,
    OrganisationInvite,
    Tenant,
)
from tests.unit.http.test_organisation import call
from tests.unit.http.test_organisation import state as organisation_state  # noqa: F401
from tests.unit.http.test_workspaces import (  # noqa: F401
    OTHER_TOKEN,
    TOKEN,
    HttpDatabase,
    workspace_state,
)

ORIGIN = "https://learner.authorityclosers.test"


@pytest.fixture
def state(request):
    return request.getfixturevalue("organisation_state")


def identity_cookie(state, person_id):
    token = uuid4().hex + "z" * 11
    pepper = state.settings.session_token_pepper.get_secret_value().encode()
    with Session(state.engine) as db, db.begin():
        db.add(
            IdentitySession(
                person_id=person_id,
                token_hash=digest(pepper, token.encode(), sha256),
                created_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
    return token


async def person_call(state, path, *, method="GET", token=OTHER_TOKEN, key=None, origin=ORIGIN):
    headers = {"Cookie": f"ac_session={token}", "Origin": origin}
    if key is not None:
        headers["Idempotency-Key"] = str(key)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=state.app), base_url=ORIGIN
    ) as client:
        return await client.request(method, "/v1/organisation" + path, headers=headers)


async def invite(state, *, email="synthetic-other@example.test", role="member", key=None):
    return await call(
        state, "POST", "/members", body={"email": email, "role": role}, key=key or uuid4()
    )


def remove_other_membership(state):
    with Session(state.engine) as db, db.begin():
        member = db.get(Membership, (state.tenant, state.other))
        member.status, member.ended_at = "inactive", datetime.now(UTC)
        db.scalar(
            select(IdentitySession).where(IdentitySession.person_id == state.other)
        ).selected_tenant_id = None


async def test_existing_person_must_choose_invite_even_when_domain_auto_join_is_enabled(state):
    remove_other_membership(state)
    with Session(state.engine) as db, db.begin():
        db.add(
            OrganisationDomainSetting(
                tenant_id=state.tenant,
                version=1,
                verified_domains=["example.test"],
                auto_join=True,
                proof={},
                operator_reference="fictional proof",
                command_id=uuid4(),
            )
        )
    key = uuid4()
    response = await invite(state, key=key, role="admin")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "invited" and response.json()["person_id"] is None
    invite_id = UUID(response.json()["invite_id"])
    assert (await invite(state, key=key, role="admin")).json() == response.json()
    with Session(state.engine) as db, db.begin():
        await join_at_sign_in_best_effort(HttpDatabase(db), state.other, settings=state.settings)
        assert db.get(Membership, (state.tenant, state.other)).status == "inactive"
        assert db.get(OrganisationInvite, invite_id).status == "pending"
    pending = await person_call(state, "/invites")
    assert pending.status_code == 200, pending.text
    assert pending.headers["cache-control"] == "private, no-store"
    row = pending.json()["invites"][0]
    assert row["invite_id"] == str(invite_id) and row["role"] == "admin"
    assert datetime.fromisoformat(row["expires_at"]) > datetime.now(UTC) + timedelta(days=6)
    assert (await person_call(state, "/invites", token=TOKEN)).json()["invites"] == []
    assert (
        await person_call(
            state, f"/invites/{invite_id}/accept", method="POST", key=uuid4(), token=TOKEN
        )
    ).status_code == 404
    accept_key = uuid4()
    accepted = await person_call(
        state, f"/invites/{invite_id}/accept", method="POST", key=accept_key
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json() == {
        "invite_id": str(invite_id),
        "tenant_id": str(state.tenant),
        "person_id": str(state.other),
        "role": "admin",
        "status": "accepted",
    }
    for replay_key in (accept_key, uuid4()):
        assert (
            await person_call(state, f"/invites/{invite_id}/accept", method="POST", key=replay_key)
        ).json() == accepted.json()
    with Session(state.engine) as db:
        member = db.get(Membership, (state.tenant, state.other))
        assert member.status == "active" and member.ended_at is None and member.role == "admin"
        assert db.scalar(select(func.count()).select_from(OutboxEvent)) == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "organisation.member_joined")
            )
            == 1
        )
        assert verify_audit_chain_sync(db, state.tenant).valid


async def test_person_who_does_not_exist_can_sign_up_then_accept_and_mail_contains_no_grant(state):
    response = await invite(state, email="new-person@example.test")
    assert response.status_code == 200, response.text
    invite_id = UUID(response.json()["invite_id"])
    person_id = uuid4()
    with Session(state.engine) as db, db.begin():
        assert db.scalar(select(Person).where(Person.email == "new-person@example.test")) is None
        outbox = db.scalar(select(OutboxEvent))
        assert outbox.payload == {"invite_id": str(invite_id)}
        job = Job(
            kind=ORGANISATION_INVITATION_JOB,
            tenant_id=state.tenant,
            dedupe_key="fictional-invite-mail",
            payload=outbox.payload,
        )
        message = await resolve_organisation_invitation_message(
            HttpDatabase(db), state.settings, job, provider_key="fictional-provider-key"
        )
        rendered = render_email(message)
        assert message.to == "new-person@example.test"
        assert f"/organisation/invites?invite_id={invite_id}" in rendered.text
        assert "link alone does not grant membership" in rendered.text
        db.add(Person(id=person_id, email=message.to, email_verified_at=datetime.now(UTC)))
    cookie = identity_cookie(state, person_id)
    accepted = await person_call(
        state, f"/invites/{invite_id}/accept", method="POST", token=cookie, key=uuid4()
    )
    assert accepted.status_code == 200, accepted.text
    with Session(state.engine) as db, pytest.raises(PermanentProviderError, match="unavailable"):
        await resolve_organisation_invitation_message(
            HttpDatabase(db), state.settings, job, provider_key="fictional-provider-key"
        )


async def test_expiry_is_sealed_and_reissue_supersedes_the_old_invitation(state, monkeypatch):
    import ac_platform.organisations.service as service_module

    monkeypatch.setattr(service_module, "INVITATION_LIFETIME", timedelta(seconds=-1))
    response = await invite(state, email="expired@example.test")
    old_id = UUID(response.json()["invite_id"])
    with Session(state.engine) as db, db.begin():
        person_id = uuid4()
        db.add(
            Person(id=person_id, email="expired@example.test", email_verified_at=datetime.now(UTC))
        )
    cookie = identity_cookie(state, person_id)
    assert (await person_call(state, "/invites", token=cookie)).json()["invites"] == []
    assert (await call(state, path="/billing")).json()["pending_invites"] == 0
    assert (
        await person_call(
            state, f"/invites/{old_id}/accept", method="POST", token=cookie, key=uuid4()
        )
    ).status_code == 409
    monkeypatch.setattr(service_module, "INVITATION_LIFETIME", timedelta(days=7))
    reissued = await invite(state, email="expired@example.test")
    assert reissued.status_code == 200, reissued.text
    assert reissued.json()["invite_id"] != str(old_id)
    with Session(state.engine) as db:
        assert db.get(OrganisationInvite, old_id).status == "revoked"
        event = db.scalar(
            select(AuditEvent).where(AuditEvent.action == "organisation.invite_expired")
        )
        assert event.resource_id == str(old_id)
        assert verify_audit_chain_sync(db, state.tenant).valid


async def test_revocation_and_unsafe_origin_prevent_acceptance(state):
    remove_other_membership(state)
    response = await invite(state)
    invite_id = response.json()["invite_id"]
    assert (
        await person_call(
            state,
            f"/invites/{invite_id}/accept",
            method="POST",
            key=uuid4(),
            origin="https://wrong.test",
        )
    ).status_code == 403
    assert (await call(state, "DELETE", f"/invites/{invite_id}", key=uuid4())).status_code == 204
    assert (
        await person_call(state, f"/invites/{invite_id}/accept", method="POST", key=uuid4())
    ).status_code == 404
    with Session(state.engine) as db:
        assert db.get(Membership, (state.tenant, state.other)).status == "inactive"


@pytest.mark.parametrize("change", ["unverified", "inactive_org", "no_paid_seats"])
async def test_acceptance_rechecks_verified_identity_active_org_and_paid_capacity(state, change):
    remove_other_membership(state)
    response = await invite(state)
    invite_id = UUID(response.json()["invite_id"])
    with Session(state.engine) as db, db.begin():
        if change == "unverified":
            db.get(Person, state.other).email_verified_at = None
        elif change == "inactive_org":
            db.get(Tenant, state.tenant).status = "suspended"
        else:
            period = db.scalar(select(BillingPeriod))
            period.period_start = datetime.now(UTC) - timedelta(days=32)
            period.period_end = datetime.now(UTC) - timedelta(days=1)
    accepted = await person_call(state, f"/invites/{invite_id}/accept", method="POST", key=uuid4())
    assert (
        accepted.status_code
        == {"unverified": 401, "inactive_org": 404, "no_paid_seats": 409}[change]
    )
    with Session(state.engine) as db:
        assert db.get(OrganisationInvite, invite_id).status == "pending"
        assert db.get(Membership, (state.tenant, state.other)).status == "inactive"


async def test_acceptance_audit_failure_rolls_back_invite_and_membership(state, monkeypatch):
    import ac_platform.organisations.service as service_module

    remove_other_membership(state)
    response = await invite(state)
    invite_id = UUID(response.json()["invite_id"])

    async def fail(*args, **kwargs):
        raise RuntimeError("fictional audit write failed")

    monkeypatch.setattr(service_module, "append_audit_event", fail)
    with pytest.raises(RuntimeError, match="fictional audit"):
        await person_call(state, f"/invites/{invite_id}/accept", method="POST", key=uuid4())
    with Session(state.engine) as db:
        assert db.get(OrganisationInvite, invite_id).status == "pending"
        assert db.get(Membership, (state.tenant, state.other)).status == "inactive"


async def test_invitation_mail_escapes_organisation_name_and_rejects_cross_tenant_jobs(state):
    with Session(state.engine) as db, db.begin():
        db.get(Tenant, state.tenant).name = 'मराठी <script>alert("x")</script>'
    response = await invite(state, email="mail@example.test")
    job = Job(
        kind=ORGANISATION_INVITATION_JOB,
        tenant_id=state.tenant,
        dedupe_key="fictional-mail",
        payload={"invite_id": response.json()["invite_id"]},
    )
    with Session(state.engine) as db:
        message = await resolve_organisation_invitation_message(
            HttpDatabase(db), state.settings, job, provider_key="fictional-provider-key"
        )
        rendered = render_email(message)
        assert "<script>" not in rendered.html and "&lt;script&gt;" in rendered.html
        job.tenant_id = state.tenants["Beta"]
        with pytest.raises(PermanentProviderError, match="unavailable"):
            await resolve_organisation_invitation_message(
                HttpDatabase(db), state.settings, job, provider_key="fictional-provider-key"
            )
