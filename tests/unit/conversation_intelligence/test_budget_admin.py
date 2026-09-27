from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence.application import ConversationConflict
from ac_platform.conversation_intelligence.authority import _budget_matches_release
from ac_platform.conversation_intelligence.budget_admin import (
    ADMIN_BUDGET_CEILING_PAISE,
    ConversationBudgetAdmin,
    admin_budget_approval_ref,
    is_admin_budget_approval_ref,
    is_any_admin_budget_approval_ref,
)
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.entitlements import (
    BudgetAccount,
    BudgetCapApproval,
    reserve,
)
from ac_platform.kernel.authz import ActorContext

from .test_entitlements import accounts, permission, quote


def bundle_for(scope_id, *, cap=150_000):
    return SimpleNamespace(
        digest="a" * 64,
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
async def test_save_requires_release_ceiling_and_optimistic_revision():
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
            new_cap_paise=200_001,
            expected_revision=4,
            reason="above release ceiling",
            key="budget-cap-above-ceiling",
        )


@pytest.mark.asyncio
async def test_save_accepts_lower_cap_above_held_commitments_and_binds_admin_receipt():
    scope_id = uuid4()
    held = held_budget(scope_id)
    bundle = bundle_for(scope_id, cap=200_000)
    row = SimpleNamespace(scope_id=scope_id, revision=4, snapshot=held.budget.as_dict())
    service, application = service_for(row, bundle)
    actor = ActorContext(uuid4(), uuid4(), bundle.provider_control_tenant_id)

    value = await service.save(
        actor,
        bundle=bundle,
        new_cap_paise=149_000,
        expected_revision=4,
        reason="reduce future provider exposure",
        key="budget-cap-lower",
    )

    updated = BudgetAccount.from_dict(row.snapshot)
    assert updated.cap_paise == 149_000
    assert updated.reservations == held.budget.reservations
    assert value["budget"]["available_paise"] == 146_500
    approval = updated.cap_approval
    assert approval.owner_actor_id == str(actor.person_id)
    assert approval.approval_ref == admin_budget_approval_ref(
        bundle.digest, actor.person_id, "budget-cap-lower"
    )
    application._receipt.assert_awaited_once()


@pytest.mark.asyncio
async def test_save_retries_same_key_against_the_recorded_receipt_action():
    scope_id = uuid4()
    held = held_budget(scope_id)
    bundle = bundle_for(scope_id, cap=200_000)
    row = SimpleNamespace(scope_id=scope_id, revision=4, snapshot=held.budget.as_dict())
    receipts: dict[str, SimpleNamespace] = {}

    async def replay(_actor, key, action, intent):
        recorded = receipts.get(key)
        if recorded is None:
            return None
        if recorded.action != action or recorded.intent_sha256 != content_hash(intent):
            raise ConversationConflict("The request key belongs to a different command.")
        return recorded

    async def receipt(_actor, key, action, intent, result_id, _now, **_kwargs):
        receipts[key] = SimpleNamespace(
            action=action,
            intent_sha256=content_hash(intent),
            result_id=result_id,
        )

    service, application = service_for(row, bundle)
    application._replay = replay
    application._receipt = receipt
    actor = ActorContext(uuid4(), uuid4(), bundle.provider_control_tenant_id)

    first = await service.save(
        actor,
        bundle=bundle,
        new_cap_paise=149_000,
        expected_revision=4,
        reason="reduce future provider exposure",
        key="budget-cap-retry",
    )
    second = await service.save(
        actor,
        bundle=bundle,
        new_cap_paise=149_000,
        expected_revision=4,
        reason="reduce future provider exposure",
        key="budget-cap-retry",
    )

    assert first == second
    assert receipts["budget-cap-retry"].action == "budget_cap"


def test_admin_ceiling_is_ten_thousand_inr():
    assert ADMIN_BUDGET_CEILING_PAISE == 1_000_000


def test_admin_approval_ref_is_bound_to_the_release_digest():
    actor_id = uuid4()
    value = admin_budget_approval_ref("a" * 64, actor_id, "budget-key")
    assert is_admin_budget_approval_ref(value, "a" * 64)
    assert not is_admin_budget_approval_ref(value, "b" * 64)
    assert is_any_admin_budget_approval_ref(value)


def test_authority_carries_an_admin_limit_across_release_refreshes():
    scope_id = uuid4()
    bundle = bundle_for(scope_id, cap=200_000)
    owner = uuid4()
    release_budget = BudgetAccount(
        str(scope_id),
        150_000,
        BudgetCapApproval(
            str(scope_id),
            "release-budget-approval",
            str(owner),
            150_000,
            "0" * 64,
            "release",
        ),
    )
    release_bundle = SimpleNamespace(
        **{
            **vars(bundle),
            "budget_authorization_ref": "release-budget-approval",
            "budget_owner_id": owner,
        }
    )
    assert _budget_matches_release(release_budget, release_bundle)

    admin_budget = replace(
        release_budget,
        cap_paise=100_000,
        cap_approval=BudgetCapApproval(
            str(scope_id),
            admin_budget_approval_ref(bundle.digest, uuid4(), "budget-key"),
            str(owner),
            100_000,
            release_budget.fingerprint,
            "admin limit",
        ),
    )
    assert _budget_matches_release(admin_budget, release_bundle)
    carried_admin_budget = replace(
        admin_budget,
        cap_paise=250_000,
        cap_approval=replace(
            admin_budget.cap_approval,
            approved_cap_paise=250_000,
            explicit_above_ceiling=True,
        ),
    )
    assert _budget_matches_release(carried_admin_budget, release_bundle)
    over_ceiling = replace(
        admin_budget,
        cap_paise=1_000_001,
        cap_approval=replace(
            admin_budget.cap_approval,
            approved_cap_paise=1_000_001,
            explicit_above_ceiling=True,
        ),
    )
    assert not _budget_matches_release(over_ceiling, release_bundle)
