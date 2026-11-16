"""organisation-members.py on PostgreSQL: a read-only preview, then members added or invited with
the app's invitation e-mail, an owner refused, an existing member kept, replay, and the invite
joining at a verified sign-in. Fictional people only."""

import json
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain_sync
from ac_platform.identity.models import Person
from ac_platform.organisations.service import OrganisationCommandError
from ac_platform.organisations.sign_in import join_at_sign_in_best_effort
from ac_platform.outbox.models import OutboxEvent
from ac_platform.tenancy.models import Membership, OrganisationInvite
from tests.integration.test_media_delivery_renewal_postgresql import postgres_harness  # noqa: F401
from tests.integration.test_organisation_membership_data_change_postgresql import counts
from tests.integration.test_organisation_membership_data_change_postgresql import (
    state as membership_state,
)
from tests.unit.organisations.test_organisation_members import arguments, tool


@pytest.fixture
def members_state(postgres_harness, monkeypatch):  # noqa: F811
    state = membership_state.__wrapped__(postgres_harness, monkeypatch)
    monkeypatch.setattr(tool, "_settings", lambda _args: state.settings)
    return state


def args_for(state, targets, **kwargs):
    return arguments(state.tenant, state.owner, targets, **kwargs)


@pytest.mark.asyncio
async def test_preview_then_apply_adds_the_verified_and_invites_the_rest(members_state, capsys):
    state = members_state
    targets = [state.people[state.worker], "new-seller@example.test"]
    args = args_for(state, targets)
    before = counts(state)
    await tool._run(args)
    preview = json.loads(capsys.readouterr().out)
    assert [row["status"] for row in preview["targets"]] == ["eligible", "eligible_invite"]
    assert counts(state) == before
    assert "new-seller@example.test" not in json.dumps(preview)
    with pytest.raises(OrganisationCommandError, match="snapshot"):
        args.apply = True
        await tool._run(args)
    args.snapshot_reference = "snapshot-fixture"
    await tool._run(args)
    report = json.loads(capsys.readouterr().out)
    assert [row["status"] for row in report["targets"]] == ["applied", "applied"]
    invite_id = UUID(report["targets"][1]["invite_id"])
    with Session(state.harness.engine) as db:
        member = db.get(Membership, (state.tenant, state.worker))
        assert member.role == "member" and member.status == "active"
        assert db.scalar(select(Person).where(Person.email == "new-seller@example.test")) is None
        assert db.get(OrganisationInvite, invite_id).status == "pending"
        assert (
            db.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(
                    OutboxEvent.tenant_id == state.tenant,
                    OutboxEvent.event_type == "organisation.invitation.requested.v1",
                )
            )
            == 1
        )
        audits = list(
            db.scalars(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == state.tenant, AuditEvent.action == tool.ACTION
                )
            )
        )
        assert len(audits) == 2
        assert all(json.loads(audit.reason)["approver"] == args.approver for audit in audits)
        assert verify_audit_chain_sync(db, state.tenant).valid
    # The same command IDs replay and change nothing; a fresh run keeps the member's role and
    # never sends the pending invite twice.
    before = counts(state)
    await tool._run(args)
    assert {row["status"] for row in json.loads(capsys.readouterr().out)["targets"]} == {"replayed"}
    again = args_for(state, targets, apply=True)
    await tool._run(again)
    assert [row["status"] for row in json.loads(capsys.readouterr().out)["targets"]] == [
        "already_member",
        "already_invited",
    ]
    assert counts(state) == before


@pytest.mark.asyncio
async def test_an_owner_is_never_a_target(members_state):
    state = members_state
    with pytest.raises(OrganisationCommandError, match="owner target"):
        await tool._run(args_for(state, [state.people[state.owner]]))


@pytest.mark.asyncio
async def test_the_invited_seller_joins_at_a_verified_sign_in(members_state, capsys):
    state = members_state
    await tool._run(args_for(state, [state.people[state.unverified]], apply=True))
    invite_id = UUID(json.loads(capsys.readouterr().out)["targets"][0]["invite_id"])
    engine = create_async_engine(state.settings.database_url)
    try:
        async with AsyncSession(engine) as db, db.begin():
            person = await db.get(Person, state.unverified)
            person.email_verified_at = datetime.now(UTC)
            await db.flush()
            await join_at_sign_in_best_effort(db, state.unverified, settings=state.settings)
        with Session(state.harness.engine) as db:
            member = db.get(Membership, (state.tenant, state.unverified))
            assert member is not None and member.role == "member" and member.status == "active"
            assert db.get(OrganisationInvite, invite_id).status == "accepted"
    finally:
        await engine.dispose()
