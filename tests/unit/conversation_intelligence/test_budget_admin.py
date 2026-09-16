from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence.budget_admin import (
    ADMIN_BUDGET_CEILING_PAISE,
    ConversationBudgetAdmin,
)
from ac_platform.conversation_intelligence.entitlements import (
    BudgetAccount,
    BudgetCapApproval,
    reserve,
)
from ac_platform.kernel.authz import ActorContext

from .test_entitlements import accounts, permission, quote


def bundle_for(scope_id, *, cap=150_000):
    return SimpleNamespace(
        provider_control_tenant_id=uuid4(),
        budget_scope_id=scope_id,
        budget_cap_paise=cap,
        budget_authorization_ref="release-budget-approval",
        budget_owner_id=uuid4(),
        current=lambda now, environment: None,
    )


def service_for(row, bundle):
    database = SimpleNamespace(
        scalar=AsyncMock(return_value=row),
        get=AsyncMock(return_value=row),
        flush=AsyncMock(),
    )
    application = SimpleNamespace(
        database=database,
        clock=lambda: datetime(2026, 9, 16, tzinfo=UTC),
        _replay=AsyncMock(return_value=None),
        _receipt=AsyncMock(),
    )
    service = ConversationBudgetAdmin(
        application,
        environment="test",
        operations_tenant_id=bundle.provider_control_tenant_id,
    )
    service.admit = AsyncMock()
    return service, application


def held_budget(scope_id):
    minutes, _ = accounts(cap=150_000)
    budget = BudgetAccount(
        str(scope_id),
        150_000,
        BudgetCapApproval(
            str(scope_id),
            "initial-owner-approval",
            "owner-fixture",
            150_000,
            "0" * 64,
            "approved project cap",
        ),
    )
    value = quote(budget_scope_id=str(scope_id), entitlement_seconds=0)
    return reserve(minutes, budget, "reserve-a", value, permission(value), 200)


@pytest.mark.asyncio
async def test_save_preserves_held_reservations_and_records_an_append_only_receipt():
    scope_id = uuid4()
    held = held_budget(scope_id)
    bundle = bundle_for(scope_id, cap=200_000)
    row = SimpleNamespace(
        scope_id=scope_id,
        revision=7,
        snapshot=held.budget.as_dict(),
    )
    service, application = service_for(row, bundle)
    actor = ActorContext(uuid4(), uuid4(), bundle.provider_control_tenant_id)

    value = await service.save(
        actor,
        bundle=bundle,
        new_cap_paise=200_000,
        expected_revision=7,
        reason="release-approved capacity",
        key="budget-cap-1",
    )

    updated = BudgetAccount.from_dict(row.snapshot)
    assert row.revision == 8
    assert updated.cap_paise == 200_000
    assert updated.reservations == held.budget.reservations
    assert updated.available_paise == 197_500
    assert value["budget"]["reservation_count"] == 1
    application._receipt.assert_awaited_once()
    assert application._receipt.await_args.kwargs["resource_type"] == "conversation_budget_account"


@pytest.mark.asyncio
async def test_save_requires_release_cap_and_optimistic_revision():
    scope_id = uuid4()
    budget = held_budget(scope_id).budget
    bundle = bundle_for(scope_id, cap=200_000)
    row = SimpleNamespace(scope_id=scope_id, revision=4, snapshot=budget.as_dict())
    service, _ = service_for(row, bundle)
    actor = ActorContext(uuid4(), uuid4(), bundle.provider_control_tenant_id)

    with pytest.raises(ValueError, match="Budget settings changed"):
        await service.save(
            actor,
            bundle=bundle,
            new_cap_paise=200_000,
            expected_revision=3,
            reason="stale",
            key="budget-cap-stale",
        )

    with pytest.raises(ValueError, match="pinned release approval"):
        await service.save(
            actor,
            bundle=bundle,
            new_cap_paise=199_999,
            expected_revision=4,
            reason="different amount",
            key="budget-cap-different",
        )


def test_admin_ceiling_is_ten_thousand_inr():
    assert ADMIN_BUDGET_CEILING_PAISE == 1_000_000
