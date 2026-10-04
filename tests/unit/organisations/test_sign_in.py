"""Join decisions and savepoint rollback using fictional relational state."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select

import ac_platform.organisations.sign_in as sign_in
from ac_platform.application.settings import Settings
from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain_sync
from ac_platform.billing.order_models import BillingPeriod, BillingSubscription
from ac_platform.identity.models import Person
from ac_platform.organisations.service import OrganisationService
from ac_platform.tenancy.models import (
    Membership,
    OrganisationInvite,
    Tenant,
)
from tests.unit.http.test_organisation_seat_exemptions import install_approval
from tests.unit.http.test_workspaces import HttpDatabase
from tests.unit.organisations.test_service import create_org, state  # noqa: F401


async def join(state, *, assertion=None, policy=None):  # noqa: F811
    await sign_in.join_at_sign_in_best_effort(
        HttpDatabase(state.session),
        state.worker_id,
        settings=Settings(
            _env_file=None,
            environment="test",
            operations_tenant_id=state.operations_id,
            public_learner_tenant_id=state.public_id,
        ),
        assertion=assertion,
        internal_tester_policy=policy,
    )


async def set_domains(state, tenant, *, auto_join=True, domains=None):  # noqa: F811
    await state.service.set_domains_attested(
        tenant,
        ["example.test"] if domains is None else domains,
        auto_join,
        "fictional test proof",
        uuid4(),
    )


async def test_domain_join_is_member_and_replay_has_no_command_id_scan(state, monkeypatch):  # noqa: F811
    org = await create_org(state)
    await set_domains(state, org.tenant_id)

    async def forbidden(*args, **kwargs):
        pytest.fail("Sign-in called a command-ID helper")

    monkeypatch.setattr(OrganisationService, "_ensure_command_id_available", forbidden)
    monkeypatch.setattr(OrganisationService, "_command_audit", forbidden)
    await join(state)
    await join(state)
    member = state.session.get(Membership, (org.tenant_id, state.worker_id))
    assert member.role == "member" and member.status == "active"
    events = list(
        state.session.scalars(
            select(AuditEvent).where(AuditEvent.action == "organisation.member_joined")
        )
    )
    assert len(events) == 1 and events[0].actor_person_id == state.worker_id
    assert events[0].reason == "domain_auto_join" and events[0].request_id is None
    assert verify_audit_chain_sync(state.session, org.tenant_id).valid


@pytest.mark.parametrize(
    "case",
    [
        "off",
        "removed",
        "unverified",
        "inactive_person",
        "inactive_tenant",
        "wrong_domain",
        "mismatched_hd",
        "unverified_assertion",
        "missing_assertion_email",
        "mismatched_assertion_email",
        "latest_removed",
    ],
)
async def test_domain_join_fails_closed(state, case):  # noqa: F811
    org = await create_org(state)
    await set_domains(state, org.tenant_id, auto_join=case != "off")
    assertion = None
    if case == "removed":
        state.session.add(
            Membership(
                tenant_id=org.tenant_id,
                person_id=state.worker_id,
                role="admin",
                status="inactive",
                ended_at=datetime.now(UTC),
            )
        )
    elif case == "unverified":
        state.session.get(Person, state.worker_id).email_verified_at = None
    elif case == "inactive_person":
        state.session.get(Person, state.worker_id).status = "suspended"
    elif case == "inactive_tenant":
        state.session.get(Tenant, org.tenant_id).status = "suspended"
    elif case == "wrong_domain":
        state.session.get(Person, state.worker_id).email = "worker@other.test"
    elif case in {
        "mismatched_hd",
        "unverified_assertion",
        "missing_assertion_email",
        "mismatched_assertion_email",
    }:
        assertion = SimpleNamespace(
            email=(
                None
                if case == "missing_assertion_email"
                else "other@old.test"
                if case == "mismatched_assertion_email"
                else "worker@example.test"
            ),
            email_verified=case != "unverified_assertion",
            hosted_domain="wrong.test" if case == "mismatched_hd" else None,
        )
    elif case == "latest_removed":
        await set_domains(state, org.tenant_id, domains=[])
    state.session.flush()
    await join(state, assertion=assertion)
    member = state.session.get(Membership, (org.tenant_id, state.worker_id))
    assert member is None or member.status == "inactive"
    assert (
        state.session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action == "organisation.member_joined")
        )
        == 0
    )


@pytest.mark.parametrize("hosted_domain", [None, "example.test"])
async def test_matching_or_absent_google_hd_joins(state, hosted_domain):  # noqa: F811
    org = await create_org(state)
    await set_domains(state, org.tenant_id)
    await join(
        state,
        assertion=SimpleNamespace(
            email=" worker@EXAMPLE.test ", email_verified=True, hosted_domain=hosted_domain
        ),
    )
    assert state.session.get(Membership, (org.tenant_id, state.worker_id)).role == "member"


@pytest.mark.parametrize("paid,pending,joins", [(1, 0, False), (2, 1, False), (2, 0, True)])
async def test_domain_join_respects_active_and_pending_seats(state, paid, pending, joins, caplog):  # noqa: F811
    org = await create_org(state)
    await set_domains(state, org.tenant_id)
    state.session.scalar(select(BillingSubscription)).seats = paid
    if pending:
        state.session.add(
            OrganisationInvite(
                tenant_id=org.tenant_id,
                email_normalized="pending@example.test",
                role="member",
                command_id=uuid4(),
            )
        )
    state.session.flush()
    with caplog.at_level("INFO", logger=sign_in.__name__):
        await join(state)
    assert (state.session.get(Membership, (org.tenant_id, state.worker_id)) is not None) is joins
    assert ("organisation_domain_auto_join_seats_full" in caplog.text) is not joins
    assert "worker@example.test" not in caplog.text and "example.test" not in caplog.text
    assert state.session.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(AuditEvent.action == "organisation.member_joined")
    ) == int(joins)


@pytest.mark.parametrize(
    "approval", ["current", "missing", "expired", "wrong_environment", "tampered"]
)
async def test_unpaid_auto_join_requires_current_pinned_seat_exemption(state, tmp_path, approval):  # noqa: F811
    org = await create_org(state)
    await set_domains(state, org.tenant_id)
    period = state.session.scalar(select(BillingPeriod))
    period.period_start = datetime(2019, 12, 1, tzinfo=UTC)
    period.period_end = datetime(2020, 1, 1, tzinfo=UTC)
    policy = None
    if approval != "missing":
        fixture = SimpleNamespace(
            tenant=org.tenant_id,
            app=SimpleNamespace(state=SimpleNamespace()),
            settings=Settings(
                _env_file=None, environment="test", operations_tenant_id=state.operations_id
            ),
        )
        updates = {"environment": "staging"} if approval == "wrong_environment" else {}
        if approval == "expired":
            updates.update(issued_at_epoch=1000, expires_at_epoch=2000)
        path = install_approval(fixture, tmp_path, **updates)
        if approval == "tampered":
            path.write_bytes(path.read_bytes() + b" ")
        policy = fixture.app.state.internal_tester_policy
    state.session.flush()
    await join(state, policy=policy)
    assert (state.session.get(Membership, (org.tenant_id, state.worker_id)) is not None) is (
        approval == "current"
    )


async def test_accepts_all_pending_invites_and_restores_only_explicit_invite(state):  # noqa: F811
    tenants = [(await create_org(state, name=f"Invite fixture {i}")).tenant_id for i in range(2)]
    for tenant, role in zip(tenants, ["admin", "member"], strict=True):
        state.session.add(
            OrganisationInvite(
                tenant_id=tenant,
                email_normalized="worker@example.test",
                role=role,
                command_id=uuid4(),
            )
        )
    state.session.add(
        Membership(
            tenant_id=tenants[0],
            person_id=state.worker_id,
            role="member",
            status="inactive",
            ended_at=datetime.now(UTC),
        )
    )
    state.session.flush()
    await join(state)
    await join(state)
    invites = list(state.session.scalars(select(OrganisationInvite)))
    assert all(
        invite.status == "accepted"
        and invite.accepted_person_id == state.worker_id
        and invite.closed_at is not None
        for invite in invites
    )
    assert [
        state.session.get(Membership, (tenant, state.worker_id)).role for tenant in tenants
    ] == ["admin", "member"]
    assert all(
        state.session.get(Membership, (tenant, state.worker_id)).ended_at is None
        for tenant in tenants
    )
    events = list(
        state.session.scalars(
            select(AuditEvent).where(AuditEvent.action == "organisation.member_joined")
        )
    )
    assert len(events) == 2 and all(event.reason == "invite_accepted" for event in events)


async def test_audit_failure_rolls_back_both_invite_and_membership(state, monkeypatch, caplog):  # noqa: F811
    org = await create_org(state)
    state.session.add(
        OrganisationInvite(
            tenant_id=org.tenant_id,
            email_normalized="worker@example.test",
            role="admin",
            command_id=uuid4(),
        )
    )
    state.session.flush()

    async def fail(*args, **kwargs):
        raise RuntimeError("fictional private failure")

    monkeypatch.setattr(sign_in, "append_audit_event", fail)
    await join(state)
    assert state.session.get(Membership, (org.tenant_id, state.worker_id)) is None
    assert state.session.scalar(select(OrganisationInvite)).status == "pending"
    assert "organisation_sign_in_join_failed" in caplog.text
    assert "private failure" not in caplog.text
    assert state.session.is_active
