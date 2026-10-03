"""Credit input rejects lossy quantities before any persistence or audit work."""

import asyncio
from datetime import datetime
from decimal import Decimal, localcontext
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ac_platform.billing.credits import CreditsLedger, validate_credit_quantity
from ac_platform.billing.ledger import BillingError


@pytest.mark.parametrize(
    "quantity",
    [
        0,
        1,
        True,
        0.1,
        "1.25",
        Decimal(0),
        Decimal("NaN"),
        Decimal("sNaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
    ],
)
def test_credit_quantity_refuses_implicit_or_nonfinite_values(quantity):
    with pytest.raises(BillingError):
        validate_credit_quantity(quantity)


@pytest.mark.parametrize(
    "text", ["-0.00000000000000000000000000001", "12345678901234567890.123456789"]
)
def test_explicit_quantity_is_not_rounded_by_decimal_context(text):
    quantity = Decimal(text)
    with localcontext() as context:
        context.prec = 2
        validate_credit_quantity(quantity)
    assert quantity.as_tuple() == Decimal(text).as_tuple()


@pytest.mark.parametrize("text", ["1E+131072", "1E-16384"])
def test_quantity_outside_postgresql_exact_storage_is_refused(text):
    with pytest.raises(BillingError, match="storage limits"):
        validate_credit_quantity(Decimal(text))


@pytest.mark.parametrize(
    "changes",
    [
        {"actor_type": "provider"},
        {"actor_type": "person"},
        {"source_ref": "  "},
        {"source_ref": "x" * 161},
        {"reason": "  "},
        {"reason": "x" * 501},
    ],
)
def test_invalid_provenance_is_refused_before_database_work(changes):
    database = AsyncMock()
    facts = dict(
        tenant_id=uuid4(),
        account_id=uuid4(),
        quantity=Decimal("1.25"),
        source_ref="fictional:explicit",
        actor_type="system",
        reason="Synthetic evidence",
    )
    facts.update(changes)
    with pytest.raises(BillingError):
        asyncio.run(CreditsLedger(database).append(**facts))
    database.scalar.assert_not_awaited()


def test_naive_clock_is_refused_before_database_work():
    database = AsyncMock()
    ledger = CreditsLedger(database, clock=lambda: datetime(2026, 10, 3))
    with pytest.raises(BillingError, match="timezone-aware"):
        asyncio.run(
            ledger.append(
                tenant_id=uuid4(),
                account_id=uuid4(),
                quantity=Decimal("1"),
                source_ref="fictional:clock",
                actor_type="system",
                reason="Fixture",
            )
        )
    database.scalar.assert_not_awaited()
