"""Expiry orchestration uses the shared projection and refuses ambiguous scope."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from ac_platform.billing import expiry
from ac_platform.billing.ledger import BillingError
from ac_platform.billing.models import BillingAccount, BillingLedgerEntry
from ac_platform.billing.projection import Lot, LotKind, Use, project
from ac_platform.billing.trial import TrialPolicy

NOW = datetime(2024, 2, 29, 18, 30, tzinfo=UTC)


@asynccontextmanager
async def savepoint():
    yield


@pytest.fixture
def setup(monkeypatch):
    public, operations = uuid4(), uuid4()
    account = BillingAccount(
        id=uuid4(), tenant_id=public, person_id=uuid4(), kind="personal", created_at=NOW
    )
    database = MagicMock()
    database.in_transaction.return_value = True
    database.begin_nested.side_effect = savepoint
    database.scalar = AsyncMock(side_effect=[account, None])
    ledger = MagicMock()
    ledger.project_person = AsyncMock()
    ledger.project_organisation = AsyncMock()
    ledger.person_entries = AsyncMock(return_value=[])
    ledger.organisation_entries = AsyncMock(return_value=[])
    ledger.write_closing = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    factory = MagicMock(return_value=ledger)
    lock = AsyncMock()
    audit = SimpleNamespace(append=AsyncMock(return_value=SimpleNamespace(id=uuid4())))
    monkeypatch.setattr(expiry, "BillingLedger", factory)
    monkeypatch.setattr(expiry, "take_admission_lock", lock)
    monkeypatch.setattr(expiry, "AuditRepository", lambda db: audit)
    service = expiry.MinuteExpiryService(
        database,
        public_learner_tenant_id=public,
        operations_tenant_id=operations,
        trial_policy=TrialPolicy("v2"),
        clock=lambda: NOW,
    )
    return SimpleNamespace(**locals())


def due_lot(setup, *, pending=False):
    entry = BillingLedgerEntry(
        id=uuid4(),
        account_id=setup.account.id,
        kind="period_grant",
        seconds=600,
        valid_from=NOW - timedelta(days=29),
        expires_at=NOW,
        source_ref="fictional:month",
        plan_key="personal",
    )
    lot = Lot(str(entry.id), LotKind.PERIOD_GRANT, 600, entry.valid_from, NOW)
    uses = [Use("fictional", NOW - timedelta(days=1), 120, pending=pending)]
    setup.ledger.project_person.return_value = SimpleNamespace(projection=project([lot], uses, NOW))
    setup.ledger.person_entries.return_value = [entry]
    return entry


def execute(setup, **changes):
    return asyncio.run(
        setup.service.expire_due(
            **dict(tenant_id=setup.account.tenant_id, account_id=setup.account.id, **changes)
        )
    )


def test_lock_precedes_fresh_projection_and_audited_closing(setup):
    entry = due_lot(setup)
    order = []

    async def locked(*args):
        order.append("lock")

    async def projected(**kwargs):
        order.append("projection")
        assert order == ["lock", "projection"]
        return setup.ledger.project_person.return_value

    setup.lock.side_effect = locked
    setup.ledger.project_person.side_effect = projected
    result = execute(setup)
    setup.lock.assert_awaited_once_with(setup.database, setup.public)
    setup.ledger.project_person.assert_awaited_once_with(
        tenant_id=setup.public, person_id=setup.account.person_id, now=NOW, mirror=False
    )
    facts = setup.ledger.write_closing.await_args.kwargs
    assert facts == dict(
        lot=entry,
        kind="expiry",
        seconds=480,
        remainder=480,
        source_ref=f"expiry:{entry.id}",
        actor_type="system",
        reason=expiry._REASON,
        audit_event_id=setup.audit.append.return_value.id,
    )
    event = setup.audit.append.await_args.kwargs
    assert event["tenant_id"] == setup.public and event["actor_person_id"] is None
    assert event["payload"]["lot_source_ref"] == entry.source_ref
    assert event["payload"]["plan_key"] == "personal"
    assert result.closings[0].seconds == 480
    assert result.closings[0].lot_id == entry.id
    assert result.account_id == setup.account.id and result.person_id == setup.account.person_id
    assert result.deferred_pending_lot_ids == ()
    setup.database.commit.assert_not_called()


def test_pending_and_fully_allocated_pending_are_reported(setup):
    entry = due_lot(setup, pending=True)
    result = execute(setup)
    assert result.closings == () and result.deferred_pending_lot_ids == (entry.id,)
    setup.audit.append.assert_not_awaited()
    setup.ledger.write_closing.assert_not_awaited()
    position = setup.ledger.project_person.return_value.projection.positions[0]
    setup.ledger.project_person.return_value = SimpleNamespace(
        projection=project([position.lot], [Use("held", NOW - timedelta(days=1), 600, True)], NOW)
    )
    setup.database.scalar.side_effect = [setup.account]
    assert execute(setup).deferred_pending_lot_ids == (entry.id,)


def test_organisation_projects_whole_pool_and_keeps_member_lot_owner(setup):
    entry = due_lot(setup)
    member_account_id = entry.account_id
    setup.account.kind, setup.account.person_id = "organisation", None
    setup.account.tenant_id, setup.account.id = uuid4(), uuid4()
    setup.ledger.project_organisation.return_value = setup.ledger.project_person.return_value
    setup.ledger.organisation_entries.return_value = [entry]
    result = execute(setup)
    setup.ledger.project_person.assert_not_awaited()
    setup.ledger.project_organisation.assert_awaited_once_with(
        tenant_id=setup.account.tenant_id, now=NOW, mirror=False
    )
    assert setup.factory.call_args.kwargs["trial_enabled"] is False
    assert result.account_kind == "organisation" and result.person_id is None
    assert result.closings[0].account_id == member_account_id


@pytest.mark.parametrize("target", ["missing", "member", "public_pool", "wrong_person"])
def test_unavailable_account_has_scoped_read_and_no_other_reads_or_writes(setup, target):
    if target == "missing":
        setup.database.scalar.side_effect = [None]
    elif target == "member":
        setup.account.tenant_id = uuid4()
    elif target == "public_pool":
        setup.account.kind, setup.account.person_id = "organisation", None
    else:
        setup.account.person_id = None
    with pytest.raises(expiry.ExpiryScopeRefused, match="unavailable"):
        execute(setup)
    params = setup.database.scalar.await_args.args[0].compile(dialect=postgresql.dialect()).params
    assert setup.account.tenant_id in params.values() and setup.account.id in params.values()
    setup.factory.assert_not_called()
    setup.audit.append.assert_not_awaited()


def test_operations_tenant_and_missing_caller_transaction_are_refused(setup):
    with pytest.raises(expiry.ExpiryScopeRefused):
        asyncio.run(setup.service.expire_due(tenant_id=setup.operations, account_id=uuid4()))
    setup.database.scalar.assert_not_awaited()
    setup.lock.assert_not_awaited()
    setup.database.in_transaction.return_value = False
    with pytest.raises(BillingError, match="caller-owned"):
        execute(setup)
    setup.lock.assert_not_awaited()


def test_clock_normalizes_utc_and_refuses_naive_or_missing_offsets(setup):
    due_lot(setup)
    setup.service.clock = lambda: NOW.astimezone(timezone(timedelta(hours=5, minutes=30)))
    assert execute(setup).at.tzinfo is UTC
    setup.service.clock = lambda: NOW.replace(tzinfo=None)
    with pytest.raises(ValueError, match="timezone-aware"):
        execute(setup)


@pytest.mark.parametrize("conflict", ["missing_lot", "source"])
def test_conflict_discloses_no_receipt_and_writes_nothing(setup, conflict):
    due_lot(setup)
    if conflict == "missing_lot":
        setup.ledger.person_entries.return_value = []
    else:
        setup.database.scalar.side_effect = [setup.account, SimpleNamespace(id=uuid4())]
    with pytest.raises(expiry.ExpiryConflict):
        execute(setup)
    setup.audit.append.assert_not_awaited()
    setup.ledger.write_closing.assert_not_awaited()


@pytest.mark.parametrize("bad_context", ["same_tenants", "missing_policy", "invalid_tenant"])
def test_composition_requires_explicit_valid_context(bad_context):
    public, operations, policy = uuid4(), uuid4(), TrialPolicy()
    if bad_context == "same_tenants":
        operations = public
    elif bad_context == "missing_policy":
        policy = None
    else:
        public = str(public)
    with pytest.raises(ValueError, match="tenants and trial policy"):
        expiry.MinuteExpiryService(
            MagicMock(),
            public_learner_tenant_id=public,
            operations_tenant_id=operations,
            trial_policy=policy,
        )
