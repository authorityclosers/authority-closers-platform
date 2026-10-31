"""Owner-approved organisation deletion (31 Oct 2026): the script refuses anything off its
list, decides one step at a time, and on a fictional organisation removes the lead desk, ends
access and marks the tenant deleted while keeping audit history (SQLite, no providers)."""

# ruff: noqa: F811 - imported relational pytest fixtures

from __future__ import annotations

import importlib.util
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from ac_platform.audit.models import AuditEvent
from ac_platform.db.models import model_metadata
from ac_platform.lead_desk.models import Lead, LeadEvent
from ac_platform.tenancy.models import Membership, OrganisationInvite, Tenant
from tests.unit.organisations.test_service import state  # noqa: F401

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "delete_organisations", ROOT / "scripts/data-changes/delete-organisations.py"
)
assert SPEC and SPEC.loader
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)

DEV = sorted(tool.APPROVED["development"], key=str)
PRODUCTION = next(iter(tool.APPROVED["production"]))


def test_the_approved_lists_are_exactly_the_owners_two_lists():
    assert [str(tenant)[:8] for tenant in DEV] == [
        "114f3e0f",
        "349e94a3",
        "5505b9fb",
        "b36c86a7",
    ]
    assert str(PRODUCTION).startswith("67a697a5")
    assert set(tool.APPROVED) == {"development", "production"}
    digests = [d for env in tool.APPROVED.values() for d in env.values()]
    assert all(len(d) == 64 and int(d, 16) >= 0 for d in digests)
    assert len(set(digests)) == 5


@pytest.mark.parametrize(
    ("flag", "runtime", "expected"),
    [("dev", "development", "development"), ("production", "production", "production")],
)
def test_the_environment_must_be_the_runtime_s_own(flag, runtime, expected):
    assert tool.environment_of(flag, runtime) == expected


@pytest.mark.parametrize(
    ("flag", "runtime"),
    [
        ("dev", "production"),
        ("production", "development"),
        ("staging", "staging"),
        ("dev", ""),
    ],
)
def test_another_environment_is_refused(flag, runtime):
    with pytest.raises(tool.Refused, match="refused_environment"):
        tool.environment_of(flag, runtime)


def test_targets_are_all_approved_ids_or_exact_prefix_picks():
    assert tool.targets("development") == DEV
    assert tool.targets("development", ["5505b9fb", "114F3E0F", "5505b9fb"]) == [
        DEV[2],
        DEV[0],
    ]
    assert tool.targets("production", ["67a697a5-99d3"]) == [PRODUCTION]


@pytest.mark.parametrize(
    ("environment", "pick"),
    [
        ("development", "3100ddbc"),  # AC Sales Sandbox: not approved
        ("production", "3100ddbc"),
        ("production", "114f3e0f"),  # a dev id never reaches production
        ("development", "67a697a5"),
        ("development", "114f3e0"),  # too short to be a whole prefix
        ("development", ""),
    ],
)
def test_targets_refuse_any_id_off_the_environment_s_list(environment, pick):
    with pytest.raises(tool.Refused, match="refused_unlisted"):
        tool.targets(environment, [pick])


def test_targets_refuse_an_unknown_environment():
    with pytest.raises(tool.Refused, match="refused_environment"):
        tool.targets("staging")


def approved_name(monkeypatch, tenant: UUID, name: str, environment: str = "test") -> None:
    monkeypatch.setitem(tool.APPROVED, environment, {tenant: tool.name_digest(name)})


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ("other_id", "refused_unlisted"),
        ("protected", "refused_protected"),
        ("missing", "refused_missing"),
        ("renamed", "refused_name"),
        ("unregistered", "refused_not_organisation"),
    ],
)
def test_check_refuses_anything_but_the_approved_registered_organisation(monkeypatch, change, code):
    tenant = uuid4()
    approved_name(monkeypatch, tenant, "Fictional Sandbox")
    kwargs: dict[str, Any] = dict(name="Fictional Sandbox", registered=True, protected=(None,))
    target = uuid4() if change == "other_id" else tenant
    if change == "protected":
        kwargs["protected"] = (tenant,)
    if change == "missing":
        kwargs["name"] = None
    if change == "renamed":
        kwargs["name"] = "Fictional Sandbox (renamed)"
    if change == "unregistered":
        kwargs["registered"] = False
    with pytest.raises(tool.Refused, match=code):
        tool.check("test", target, **kwargs)
    tool.check("test", tenant, name="Fictional Sandbox", registered=True, protected=(None,))


@pytest.mark.parametrize(
    ("status", "live", "erasing", "expected"),
    [
        ("deleted", 0, 0, "already_deleted"),
        ("deleted", 3, 1, "already_deleted"),
        ("active", 360, 0, "request_erasure"),
        ("active", 2, 5, "request_erasure"),
        ("active", 0, 5, "wait_for_erasure"),
        ("active", 0, 0, "finish"),
    ],
)
def test_decide_takes_one_safe_step_at_a_time(status, live, erasing, expected):
    assert tool.decide(status, live_calls=live, erasing_calls=erasing) == expected


def test_decide_refuses_a_suspended_organisation():
    with pytest.raises(tool.Refused, match="refused_status"):
        tool.decide("suspended", live_calls=0, erasing_calls=0)


def test_lead_desk_tables_delete_children_before_parents():
    tables = tool.lead_desk_tables(model_metadata())
    order = {table.name: index for index, table in enumerate(tables)}
    assert "lead_desk_leads" in order and "lead_desk_events" in order
    assert all(name.startswith("lead_desk_") for name in order)
    for table in tables:
        for key in table.foreign_keys:
            parent = key.column.table.name
            if parent in order and parent != table.name:
                assert order[table.name] < order[parent], (table.name, parent)


class _Session:
    """The script's AsyncSession calls over the fixture's synchronous SQLite session."""

    def __init__(self, session: Any) -> None:
        self.session = session

    def get_bind(self) -> Any:
        return self.session.get_bind()

    def add(self, row: Any) -> None:
        self.session.add(row)

    async def get(self, model: Any, key: Any) -> Any:
        return self.session.get(model, key)

    async def scalar(self, statement: Any) -> Any:
        return self.session.scalar(statement)

    async def scalars(self, statement: Any) -> Any:
        return self.session.scalars(statement)

    async def execute(self, statement: Any) -> Any:
        return self.session.execute(statement)

    async def flush(self) -> None:
        self.session.flush()

    @asynccontextmanager
    async def begin(self):
        # The fixture's own transaction holds everything; refusals happen before writes.
        yield self


async def organisation(state, monkeypatch, name="Fictional Sandbox"):
    created = await state.service.create(name, state.owner_id, uuid4(), "AUT-fictional")
    tenant = created.tenant_id
    approved_name(monkeypatch, tenant, name)
    await state.service.add_member(
        tenant, state.worker_id, "member", uuid4(), operator_reference="fictional setup"
    )
    await state.service.request_member(
        tenant,
        "invited@example.test",
        "member",
        uuid4(),
        actor_person_id=state.owner_id,
        operator_reference="fictional invite",
    )
    now = datetime.now(UTC)
    lead = Lead(
        id=uuid4(),
        tenant_id=tenant,
        revision=1,
        source="manual",
        payload={},
        name="Fictional Lead",
        stage="new",
        attempts=0,
        calls=0,
        repeats=0,
        test_data=True,
        created_at=now,
        updated_at=now,
    )
    state.session.add(lead)
    state.session.flush()
    state.session.add(
        LeadEvent(
            id=uuid4(),
            tenant_id=tenant,
            lead_id=lead.id,
            kind="note",
            data={},
            created_at=now,
        )
    )
    state.session.flush()
    return tenant


def sessions_of(state):
    @asynccontextmanager
    async def sessions():
        yield _Session(state.session)

    return sessions


def protected(state):
    return (state.operations_id, state.public_id)


async def run(state, tenant, mode):
    return await tool.execute_one(
        sessions_of(state),
        tenant,
        environment="test",
        mode=mode,
        protected=protected(state),
    )


def audits(state, tenant):
    return list(
        state.session.scalars(
            select(AuditEvent)
            .where(AuditEvent.tenant_id == tenant, AuditEvent.action == tool.ACTION_DONE)
            .order_by(AuditEvent.sequence_no)
        )
    )


@pytest.mark.asyncio
async def test_a_dry_run_counts_and_changes_nothing(state, monkeypatch):
    tenant = await organisation(state, monkeypatch)
    result = await run(state, tenant, "dry-run")
    assert result["next"] == "finish" and "after" not in result
    before = result["before"]
    assert (before["active_members"], before["pending_invites"]) == (2, 1)
    assert before["rows"]["lead_desk_leads"] == 1 and before["rows"]["lead_desk_events"] == 1
    assert before["calls"] == {"live": 0, "erasing": 0, "erased": 0}
    assert state.session.get(Tenant, tenant).status == "active"
    assert state.session.scalar(select(func.count()).select_from(Lead)) == 1
    assert audits(state, tenant) == []


@pytest.mark.asyncio
async def test_apply_removes_the_lead_desk_ends_access_and_keeps_audit(state, monkeypatch):
    tenant = await organisation(state, monkeypatch)
    audit_before = state.session.scalar(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.tenant_id == tenant)
    )
    result = await run(state, tenant, "apply")
    assert result["next"] == "finish"
    assert result["leads"]["removed"]["leads"] == 1
    after = result["after"]
    assert (after["active_members"], after["pending_invites"]) == (0, 0)
    assert not any(name.startswith("lead_desk_") for name in after["rows"])
    assert state.session.get(Tenant, tenant).status == "deleted"
    members = list(state.session.scalars(select(Membership).where(Membership.tenant_id == tenant)))
    assert members and all(m.status == "inactive" and m.ended_at is not None for m in members)
    invite = state.session.scalar(
        select(OrganisationInvite).where(
            OrganisationInvite.tenant_id == tenant,
            OrganisationInvite.email_normalized == "invited@example.test",
        )
    )
    assert invite.status == "revoked"
    [event] = audits(state, tenant)
    assert event.reason == tool.APPROVER and "Approve delete: both lists" in event.reason
    assert event.payload["approved_on"] == "2026-10-31"
    assert event.payload["before"]["active_members"] == 2
    # Audit history stays: every earlier event is still there, plus this one.
    assert (
        state.session.scalar(
            select(func.count()).select_from(AuditEvent).where(AuditEvent.tenant_id == tenant)
        )
        == audit_before + 1
    )
    # A second run sees the deletion and changes nothing.
    again = await run(state, tenant, "apply")
    assert again["next"] == "already_deleted" and "after" not in again
    assert len(audits(state, tenant)) == 1


@pytest.mark.asyncio
async def test_unlisted_and_renamed_organisations_are_refused_untouched(state, monkeypatch):
    approved = await organisation(state, monkeypatch, name="Fictional Approved")
    other = await state.service.create("Fictional Other", state.owner_id, uuid4(), "AUT-other")
    with pytest.raises(tool.Refused, match="refused_unlisted"):
        await run(state, other.tenant_id, "apply")
    state.session.get(Tenant, approved).name = "Fictional Approved (renamed)"
    state.session.flush()
    with pytest.raises(tool.Refused, match="refused_name"):
        await run(state, approved, "apply")
    for tenant in (approved, other.tenant_id):
        assert state.session.get(Tenant, tenant).status == "active"
    assert state.session.scalar(select(func.count()).select_from(Lead)) == 1
    assert audits(state, approved) == []
