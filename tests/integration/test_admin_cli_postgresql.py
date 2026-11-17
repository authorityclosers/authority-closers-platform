"""admin.py on PostgreSQL: read-only dry runs, then transfer-owner (the owner becomes an admin,
both e-mailed), set-role, rename-person, refusals and replay. Fictional people only."""

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain_sync
from ac_platform.identity.models import Person
from ac_platform.lead_desk.contracts import NewLead
from ac_platform.lead_desk.journey import model as journeys
from ac_platform.lead_desk.models import Lead
from ac_platform.lead_desk.store import LeadDesk, Viewer
from ac_platform.organisations.service import OrganisationCommandError
from ac_platform.outbox.models import OutboxEvent
from ac_platform.tenancy.models import Membership
from tests.integration.test_media_delivery_renewal_postgresql import postgres_harness  # noqa: F401
from tests.integration.test_organisation_membership_data_change_postgresql import counts
from tests.integration.test_organisation_membership_data_change_postgresql import (
    state as membership_state,
)
from tests.unit.organisations.test_admin_cli import arguments, tool


@pytest.fixture
def admin_state(postgres_harness, monkeypatch):  # noqa: F811
    state = membership_state.__wrapped__(postgres_harness, monkeypatch)
    monkeypatch.setattr(tool, "_settings", lambda _args: state.settings)
    with Session(state.harness.engine) as db, db.begin():
        db.add(Membership(tenant_id=state.tenant, person_id=state.worker, role="member"))
        db.add(Membership(tenant_id=state.tenant, person_id=state.second, role="admin"))
    return state


def run_args(state, command, person, **kwargs):
    return arguments(command, state.tenant, person, state.owner, **kwargs)


def role(state, person):
    with Session(state.harness.engine) as db:
        return db.get(Membership, (state.tenant, person)).role


@pytest.mark.asyncio
async def test_dry_runs_write_nothing_and_say_what_would_change(admin_state, capsys):
    state = admin_state
    before = counts(state)
    for command, person, extra in (
        ("transfer-owner", state.second, ()),
        ("set-role", state.worker, ("--role", "admin")),
        ("rename-person", state.worker, ("--name", "Wise Life Admin")),
    ):
        await tool._run(run_args(state, command, person, extra=extra))
        out = json.loads(capsys.readouterr().out)
        assert (out["mode"], out["status"]) == ("dry_run", "eligible")
    assert counts(state) == before
    assert role(state, state.owner) == "owner"


@pytest.mark.asyncio
async def test_transfer_owner_makes_the_owner_an_admin_and_emails_both(admin_state, capsys):
    state = admin_state
    args = run_args(state, "transfer-owner", state.second, apply=True)
    await tool._run(args)
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "applied" and out["after"]["former_owner_role"] == "admin"
    assert role(state, state.second) == "owner" and role(state, state.owner) == "admin"
    with Session(state.harness.engine) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(
                    OutboxEvent.tenant_id == state.tenant,
                    OutboxEvent.event_type == "organisation.ownership_transferred.v1",
                )
            )
            == 2  # one e-mail to each person
        )
        audit = db.scalar(select(AuditEvent).where(AuditEvent.action == tool.ACTION))
        assert json.loads(audit.reason)["command"] == "transfer-owner"
        assert verify_audit_chain_sync(db, state.tenant).valid
    before = counts(state)
    await tool._run(args)
    assert json.loads(capsys.readouterr().out)["status"] == "replayed"
    assert counts(state) == before
    await tool._run(run_args(state, "transfer-owner", state.second, apply=True))
    assert json.loads(capsys.readouterr().out)["status"] == "already_owner"


@pytest.mark.asyncio
async def test_set_role_and_rename_apply_once_and_the_owner_role_is_refused(admin_state, capsys):
    state = admin_state
    await tool._run(
        run_args(state, "set-role", state.worker, extra=("--role", "admin"), apply=True)
    )
    assert json.loads(capsys.readouterr().out)["status"] == "applied"
    assert role(state, state.worker) == "admin"
    await tool._run(
        run_args(state, "set-role", state.worker, extra=("--role", "admin"), apply=True)
    )
    assert json.loads(capsys.readouterr().out)["status"] == "already_admin"
    with pytest.raises(OrganisationCommandError, match="transfer-owner"):
        await tool._run(run_args(state, "set-role", state.owner, extra=("--role", "member")))
    rename = run_args(state, "rename-person", state.worker, extra=("--name", "Wise Life Admin"))
    rename.apply, rename.snapshot_reference = True, "snapshot-fixture"
    await tool._run(rename)
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "applied" and out["after"] == {"name": "Wise Life Admin"}
    with Session(state.harness.engine) as db:
        assert db.get(Person, state.worker).display_name == "Wise Life Admin"
        assert verify_audit_chain_sync(db, state.tenant).valid


@pytest.mark.asyncio
async def test_refusals(admin_state):
    state = admin_state
    with pytest.raises(OrganisationCommandError, match="snapshot"):
        args = run_args(state, "set-role", state.worker)
        args.apply = True
        await tool._run(args)
    with pytest.raises(OrganisationCommandError, match="active member"):
        await tool._run(run_args(state, "rename-person", uuid4()))
    with pytest.raises(OrganisationCommandError, match="protected tenant"):
        await tool._run(arguments("set-role", state.operations, state.worker, state.owner))


@pytest.mark.asyncio
async def test_remove_member_ends_the_membership_once_and_never_the_owner(admin_state, capsys):
    state = admin_state
    args = run_args(state, "remove-member", state.worker, apply=True)
    await tool._run(args)
    assert json.loads(capsys.readouterr().out)["status"] == "applied"
    with Session(state.harness.engine) as db:
        member = db.get(Membership, (state.tenant, state.worker))
        assert member.status == "inactive" and member.ended_at is not None
        assert db.get(Person, state.worker).status == "active"
    await tool._run(run_args(state, "remove-member", state.worker, apply=True))
    assert json.loads(capsys.readouterr().out)["status"] == "already_absent"
    with pytest.raises(OrganisationCommandError, match="transfer-owner"):
        await tool._run(run_args(state, "remove-member", state.owner))


@pytest.mark.asyncio
async def test_reassign_leads_moves_every_lead_through_lead_desk(admin_state, capsys):
    state = admin_state
    engine = create_async_engine(state.settings.database_url)
    try:
        async with AsyncSession(engine) as db, db.begin():
            now = datetime.now(UTC)
            await journeys.start_organisation(db, state.tenant, state.owner, now)
            desk = LeadDesk(
                db,
                Viewer(person_id=state.owner, tenant_id=state.tenant, role="owner", name="Owner"),
                call_mode="phone",
                now=now,
            )
            for index in range(3):
                await desk.add(
                    NewLead(
                        command_id=uuid4(),
                        name=f"Fictional lead {index}",
                        phone=f"+9198765000{index:02d}",
                        assign="person",
                        person_id=state.worker,
                    )
                )
    finally:
        await engine.dispose()
    move = ("--to-person-id", str(state.second))
    await tool._run(run_args(state, "reassign-leads", state.worker, extra=move))
    preview = json.loads(capsys.readouterr().out)
    assert (preview["status"], preview["before"]) == ("eligible", {"leads_of_person": 3})
    args = run_args(state, "reassign-leads", state.worker, extra=move, apply=True)
    await tool._run(args)
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "applied" and out["after"]["moved"] == 3
    with Session(state.harness.engine) as db:
        owners = list(
            db.scalars(select(Lead.owner_person_id).where(Lead.tenant_id == state.tenant))
        )
        assert owners == [state.second] * 3
        assert verify_audit_chain_sync(db, state.tenant).valid
    await tool._run(run_args(state, "reassign-leads", state.worker, extra=move, apply=True))
    assert json.loads(capsys.readouterr().out)["status"] == "no_leads"
    with pytest.raises(OrganisationCommandError, match="active member"):
        await tool._run(
            run_args(state, "reassign-leads", state.second, extra=("--to-person-id", str(uuid4())))
        )
