"""Spend inputs and receipt serialization stay exact before persistence."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ac_platform.billing.commands import Caller
from ac_platform.billing.credit_spend import CreditSpendReceipt, CreditSpendService
from ac_platform.billing.ledger import BillingError


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
def test_invalid_quantity_has_no_database_or_audit_work(quantity):
    database = AsyncMock()
    service = CreditSpendService(
        database, checkout=SimpleNamespace(clock=lambda: datetime.now(UTC))
    )
    with pytest.raises(BillingError):
        asyncio.run(
            service.spend(
                caller=Caller(uuid4(), uuid4(), None, None),
                account_id=uuid4(),
                quantity=quantity,
                operation_id="fictional-report-operation",
                reason="Synthetic spend",
            )
        )
    database.scalar.assert_not_awaited()
    database.flush.assert_not_awaited()
    database.commit.assert_not_awaited()


@pytest.mark.parametrize(
    "changes",
    [
        {"operation_id": None},
        {"operation_id": "  "},
        {"operation_id": "x" * 129},
        {"reason": None},
        {"reason": "  "},
        {"reason": "x" * 501},
    ],
)
def test_invalid_operation_evidence_has_no_database_work(changes):
    database = AsyncMock()
    service = CreditSpendService(
        database, checkout=SimpleNamespace(clock=lambda: datetime.now(UTC))
    )
    facts = dict(
        caller=Caller(uuid4(), uuid4(), None, None),
        account_id=uuid4(),
        quantity=Decimal("1.25"),
        operation_id="fictional-report-operation",
        reason="Synthetic spend",
    )
    facts.update(changes)
    with pytest.raises(BillingError):
        asyncio.run(service.spend(**facts))
    database.scalar.assert_not_awaited()


def test_spend_requires_caller_transaction_before_database_work():
    database = AsyncMock()
    database.in_transaction = lambda: False
    service = CreditSpendService(
        database, checkout=SimpleNamespace(clock=lambda: datetime.now(UTC))
    )
    with pytest.raises(BillingError, match="caller-owned transaction"):
        asyncio.run(
            service.spend(
                caller=Caller(uuid4(), uuid4(), None, None),
                account_id=uuid4(),
                quantity=Decimal("1.25"),
                operation_id="fictional-report-operation",
                reason="Synthetic spend",
            )
        )
    database.scalar.assert_not_awaited()


def test_receipt_has_exact_json_quantity_and_utc_time():
    receipt = CreditSpendReceipt(
        uuid4(),
        uuid4(),
        Decimal("123456789012345678901234567890.12345678901234567890123456789"),
        "fictional:source",
        uuid4(),
        datetime(2026, 10, 4, 5, 31, tzinfo=UTC),
    )
    with localcontext() as context:
        context.prec = 2
        result = receipt.to_dict()
    assert Decimal(result["quantity"]).as_tuple() == receipt.quantity.as_tuple()
    assert result["created_at"] == "2026-10-04T05:31:00Z"
    assert result["entry_id"] == str(receipt.entry_id)
    assert all(isinstance(value, str) for value in result.values())
