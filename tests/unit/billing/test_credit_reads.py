"""Credit reads keep C1 authority and bounded, tenant-scoped queries."""

import asyncio
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal, localcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from ac_platform.billing.commands import Caller
from ac_platform.billing.credit_reads import CreditReads
from ac_platform.billing.errors import BillingForbidden, CreditEntryNotFound
from ac_platform.conversation_intelligence.minute_account_admin import EligibleLearnerUnavailable


@pytest.fixture
def setup(monkeypatch):
    eligibility = AsyncMock()
    monkeypatch.setattr("ac_platform.billing.credit_reads.require_eligible_learner", eligibility)
    database = AsyncMock()
    public, operations, selected = uuid4(), uuid4(), uuid4()
    caller = Caller(uuid4(), uuid4(), selected, membership_role="owner")
    reads = CreditReads(database, public_learner_tenant_id=public, operations_tenant_id=operations)
    return SimpleNamespace(
        reads=reads,
        database=database,
        eligibility=eligibility,
        public=public,
        operations=operations,
        caller=caller,
    )


def test_personal_selects_public_person_and_exact_full_ledger_sum(setup):
    account_id = uuid4()
    value = "123456789012345678901234567890.00000000000000000000000000001"
    setup.database.scalar.side_effect = [account_id, Decimal(value)]
    with localcontext() as context:
        context.prec = 2
        result = asyncio.run(setup.reads.balance(setup.caller, "personal"))
    assert (result.account_id, result.balance) == (account_id, value)
    setup.eligibility.assert_awaited_once_with(
        setup.database,
        tenant_id=setup.public,
        person_id=setup.caller.person_id,
        operations_tenant_id=setup.operations,
    )
    statement = setup.database.scalar.await_args_list[0].args[0]
    parameters = statement.compile().params.values()
    assert setup.public in parameters and setup.caller.person_id in parameters
    assert setup.caller.tenant_id not in parameters
    setup.database.add.assert_not_called()


@pytest.mark.parametrize("name", ["personal", "organisation"])
def test_absent_account_is_empty_only_after_eligibility(setup, name):
    setup.database.scalar.return_value = None
    assert asyncio.run(setup.reads.balance(setup.caller, name)).balance == "0"
    history = asyncio.run(setup.reads.history(setup.caller, name, limit=50, before=None))
    assert (history.account_id, history.entries, history.next_before) == (None, [], None)
    assert setup.eligibility.await_count == 2
    if name == "organisation":
        assert setup.eligibility.await_args.kwargs["roles"] == frozenset({"owner", "admin"})
    setup.database.execute.assert_not_awaited()
    setup.database.add.assert_not_called()


@pytest.mark.parametrize("name", ["personal", "organisation"])
def test_ineligible_caller_is_forbidden_before_account_query(setup, name):
    setup.eligibility.side_effect = EligibleLearnerUnavailable
    with pytest.raises(BillingForbidden):
        asyncio.run(setup.reads.balance(setup.caller, name))
    setup.database.scalar.assert_not_awaited()


def test_operations_and_unselected_or_unregistered_org_are_forbidden(setup):
    for tenant in (setup.operations, None):
        caller = Caller(uuid4(), uuid4(), tenant, membership_role=None)
        with pytest.raises(BillingForbidden):
            asyncio.run(setup.reads.balance(caller, "organisation"))
    setup.database.get.return_value = None
    with pytest.raises(BillingForbidden):
        asyncio.run(setup.reads.balance(setup.caller, "organisation"))
    setup.database.scalar.assert_not_awaited()


def test_bounded_history_uses_tie_cursor_and_exact_signed_utc_entries(setup):
    account, entry, older, cursor_id = (uuid4() for _ in range(4))
    now = datetime(2026, 10, 5, 14, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    cursor = SimpleNamespace(created_at=now, id=cursor_id)
    setup.database.scalar.side_effect = [account, cursor]
    setup.database.execute.return_value = [
        (SimpleNamespace(id=entry, created_at=now, quantity=Decimal("-1E-29")), older),
        (SimpleNamespace(id=older, created_at=now, quantity=Decimal("2.50")), None),
    ]
    result = asyncio.run(setup.reads.history(setup.caller, "personal", limit=1, before=cursor_id))
    assert len(result.entries) == 1 and result.next_before == entry
    assert result.entries[0].quantity == "-0.00000000000000000000000000001"
    assert result.entries[0].corrected_entry_id == older
    assert result.entries[0].created_at == datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
    statement = setup.database.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert "DESC" in str(compiled) and "LIMIT" in str(compiled)
    assert "(billing_credit_entries.created_at, billing_credit_entries.id) <" in str(compiled)
    assert 2 in compiled.params.values() and setup.public in compiled.params.values()
    assert account in compiled.params.values()


@pytest.mark.parametrize("account", [None, uuid4()])
def test_unknown_cursor_refused_with_scoped_lookup_even_on_empty_account(setup, account):
    setup.database.scalar.side_effect = [account, None]
    cursor = uuid4()
    with pytest.raises(CreditEntryNotFound):
        asyncio.run(setup.reads.history(setup.caller, "personal", limit=50, before=cursor))
    parameters = setup.database.scalar.await_args.args[0].compile().params.values()
    assert setup.public in parameters and cursor in parameters
    if account:
        assert account in parameters
    setup.database.execute.assert_not_awaited()
