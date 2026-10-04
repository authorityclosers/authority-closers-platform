"""Staff grants reject malformed evidence before any persistence or audit work."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from ac_platform.authorization.policy import CapabilityDenied
from ac_platform.billing import credit_grants
from ac_platform.billing.credit_grants import CreditGrantReceipt, CreditGrantService
from ac_platform.billing.ledger import BillingError
from ac_platform.kernel.authz import ActorContext


def setup():
    database = AsyncMock()
    database.in_transaction = Mock(return_value=True)
    service = CreditGrantService(
        database, operations_tenant_id=uuid4(), public_learner_tenant_id=uuid4()
    )
    facts = dict(
        actor=ActorContext(uuid4(), uuid4(), None),
        tenant_id=uuid4(),
        account_id=uuid4(),
        quantity=Decimal("1.25"),
        operation_id="fictional-grant-operation",
        reason="Synthetic staff grant",
    )
    return database, service, facts


@pytest.mark.parametrize(
    "quantity",
    [
        None,
        1,
        True,
        0.1,
        "1.25",
        Decimal(0),
        Decimal("-0"),
        Decimal("-1"),
        Decimal("NaN"),
        Decimal("sNaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
        Decimal("1E+131072"),
        Decimal("1E-16384"),
    ],
)
def test_invalid_quantity_has_no_database_work(quantity):
    database, service, facts = setup()
    with pytest.raises(BillingError):
        asyncio.run(service.grant(**(facts | {"quantity": quantity})))
    assert database.mock_calls == []


@pytest.mark.parametrize(
    "changes",
    [
        {"actor": None},
        {"actor": ActorContext(None, uuid4(), None)},
        {"actor": ActorContext(uuid4(), None, None)},
        {"tenant_id": None},
        {"account_id": None},
        {"operation_id": None},
        {"operation_id": "  "},
        {"operation_id": "x" * 129},
        {"reason": None},
        {"reason": "  "},
        {"reason": "x" * 501},
    ],
)
def test_invalid_actor_target_or_operation_has_no_database_work(changes):
    database, service, facts = setup()
    with pytest.raises(BillingError):
        asyncio.run(service.grant(**(facts | changes)))
    assert database.mock_calls == []


def test_grant_requires_caller_transaction():
    database, service, facts = setup()
    database.in_transaction.return_value = False
    with pytest.raises(BillingError, match="caller-owned transaction"):
        asyncio.run(service.grant(**facts))
    database.scalar.assert_not_awaited()


def test_permission_is_checked_before_target_lookup(monkeypatch):
    database, service, facts = setup()
    projection = AsyncMock(return_value=frozenset({"platform_billing_manage"}))
    monkeypatch.setattr(credit_grants, "platform_projection", projection)
    facts["actor"] = replace(facts["actor"], permissions=frozenset({"platform_access_manage"}))
    with pytest.raises(CapabilityDenied):
        asyncio.run(service.grant(**facts))
    projection.assert_awaited_once_with(
        database, facts["actor"], operations_tenant_id=service.operations_tenant_id
    )
    database.scalar.assert_not_awaited()
    database.flush.assert_not_awaited()
    database.commit.assert_not_awaited()


def test_receipt_has_exact_quantity_and_utc_time():
    receipt = CreditGrantReceipt(
        uuid4(),
        uuid4(),
        Decimal("123456789012345678901234567890.12345678901234567890123456789"),
        "credit-grant:fictional-account:fictional-operation",
        uuid4(),
        datetime(2026, 10, 4, 8, tzinfo=UTC),
    )
    with localcontext() as context:
        context.prec = 2
        result = receipt.to_dict()
    assert Decimal(result["quantity"]).as_tuple() == receipt.quantity.as_tuple()
    assert result["created_at"] == "2026-10-04T08:00:00Z"
    assert result["entry_id"] == str(receipt.entry_id)
    assert set(result) == {
        "entry_id",
        "account_id",
        "quantity",
        "source_ref",
        "audit_event_id",
        "created_at",
    }
    assert all(isinstance(value, str) for value in result.values())
