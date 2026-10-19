from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence.application import (
    ConversationConflict,
    ConversationDenied,
)
from ac_platform.conversation_intelligence.authority import _budget_matches_release
from ac_platform.conversation_intelligence.budget_admin import (
    MAX_CAP_PAISE,
    SETTINGS_ACTION,
    ConversationBudgetAdmin,
    admin_budget_approval_ref,
    is_admin_budget_approval_ref,
    is_any_admin_budget_approval_ref,
)
from ac_platform.conversation_intelligence.budget_settings import LEDGER_OPEN_CAP_PAISE
from ac_platform.conversation_intelligence.budget_settings_models import ConversationBudgetSetting
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.entitlements import (
    BudgetAccount,
    BudgetCapApproval,
    effective_budget_cap_paise,
    reserve,
)
from ac_platform.identity.models import Person
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


class FakeDatabase:
    """The ledger row, the settings revisions and the actor's workspace role."""

    def __init__(self, row, *, email="dipak@authorityclosers.com"):
        self.row, self.email = row, email
        self.settings: list[ConversationBudgetSetting] = []
        self.flush = AsyncMock()

    async def scalar(self, query):
        if query.column_descriptions[0]["entity"] is ConversationBudgetSetting:
            return max(self.settings, key=lambda item: item.revision, default=None)
        return self.row

    async def scalars(self, query):
        newest = sorted(self.settings, key=lambda item: -item.revision)[:10]
        return SimpleNamespace(all=lambda: newest)

    async def get(self, model, key):
        if model is Person:
            return SimpleNamespace(
                email=self.email, email_verified_at=datetime(2026, 9, 29, tzinfo=UTC)
            )
        if model is ConversationBudgetSetting:
            return next((item for item in self.settings if item.id == key), None)
        return self.row

    def add(self, item):
        assert isinstance(item, ConversationBudgetSetting)
        self.settings.append(item)


def service_for(row, bundle, *, email="dipak@authorityclosers.com"):
    database = FakeDatabase(row, email=email)
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

    with pytest.raises(ValueError, match="cannot exceed the ceiling"):
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


def test_the_sealed_ceiling_not_a_code_constant_bounds_an_admin_cap():
    # 19 Oct 2026: no limit of its own; the release approval's ceiling decides.
    assert MAX_CAP_PAISE == 2_147_483_647


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
    above_old_limit = replace(
        admin_budget,
        cap_paise=10_000_001,
        cap_approval=replace(
            admin_budget.cap_approval,
            approved_cap_paise=10_000_001,
            explicit_above_ceiling=True,
        ),
    )
    # Kept in the ledger; new work is still bounded by the sealed ceiling.
    assert _budget_matches_release(above_old_limit, release_bundle)
    assert effective_budget_cap_paise(release_bundle.budget_cap_paise, 10_000_001) == 200_000


@pytest.mark.asyncio
async def test_a_cap_above_ten_thousand_inr_is_saved_when_the_sealed_ceiling_allows(
    monkeypatch: pytest.MonkeyPatch,
):
    scope_id = uuid4()
    held = held_budget(scope_id)
    bundle = bundle_for(scope_id, cap=5_000_000)  # a Rs 50,000 sealed ceiling
    row = SimpleNamespace(scope_id=scope_id, revision=2, snapshot=held.budget.as_dict())
    service, _ = service_for(row, bundle)
    actor = ActorContext(uuid4(), uuid4(), bundle.provider_control_tenant_id)
    value = await service.save(
        actor,
        bundle=bundle,
        new_cap_paise=1_500_000,
        expected_revision=2,
        reason="Raised by Rs 5,000 from Execution & budget",
        key="budget-cap-15000",
    )
    assert value["budget"]["cap_paise"] == 1_500_000 and row.revision == 3


def test_an_admin_cap_saved_by_any_admin_carries_into_the_next_release():
    # 19 Oct 2026: a one-click raise by an Admin who is not the release's budget owner
    # must not block every call once a new release (another digest) is installed.
    scope_id = uuid4()
    bundle = bundle_for(scope_id, cap=1_000_000)
    budget = held_budget(scope_id).budget
    raised = replace(
        budget,
        cap_paise=400_000,
        cap_approval=BudgetCapApproval(
            str(scope_id),
            admin_budget_approval_ref("c" * 64, uuid4(), "older-release-key"),
            str(uuid4()),
            400_000,
            budget.fingerprint,
            "Raised by Rs 2,500 from Execution & budget",
            explicit_above_ceiling=True,
        ),
    )
    assert _budget_matches_release(raised, bundle)


class _Audit:
    events: list[dict] = []

    def __init__(self, _database):
        pass

    async def append_for_actor(self, _actor, **fields):
        _Audit.events.append(fields)
        return SimpleNamespace(id=uuid4())


@pytest.fixture
def audit(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    from ac_platform.conversation_intelligence import budget_admin

    _Audit.events = []
    monkeypatch.setattr(budget_admin, "AuditRepository", _Audit)
    return _Audit.events


def settings_for(bundle, **values):
    return {
        "bundle": bundle,
        "ceiling_paise": 1_000_000,
        "period": "monthly",
        "cap_paise": 300_000,
        "expected_setting_revision": 0,
        "reason": "Owner: Rs 10,000 ceiling, Rs 3,000 a month",
        "key": "settings-1",
        **values,
    }


def ledger_row(scope_id):
    return SimpleNamespace(
        scope_id=scope_id, revision=2, snapshot=held_budget(scope_id).budget.as_dict()
    )


@pytest.mark.asyncio
async def test_only_the_owner_changes_the_ceiling_and_the_period(audit):
    scope_id = uuid4()
    bundle = bundle_for(scope_id, cap=850_000)
    row = ledger_row(scope_id)
    # A workspace owner who isn't Suyash (Dipak is one in production) is refused.
    service, _ = service_for(row, bundle, email="dipak@authorityclosers.com")
    actor = ActorContext(uuid4(), uuid4(), bundle.provider_control_tenant_id)
    view = await service.current(actor, bundle=bundle)
    assert view["settings"]["can_change_ceiling"] is False
    assert view["settings"]["from_release"] is True
    assert view["settings"]["ceiling_paise"] == 850_000
    with pytest.raises(ConversationDenied, match="Only the owner"):
        await service.save_settings(actor, **settings_for(bundle))
    assert audit == [] and row.revision == 2
    # Suyash's second account is on the allowlist too (any letter case).
    service, _ = service_for(row, bundle, email="Suyash@AuthorityClosers.com")
    assert (await service.current(actor, bundle=bundle))["settings"]["can_change_ceiling"]


@pytest.mark.asyncio
async def test_the_owner_sets_a_monthly_allowance_under_a_new_ceiling(audit):
    scope_id = uuid4()
    bundle = bundle_for(scope_id, cap=850_000)
    row = ledger_row(scope_id)
    service, application = service_for(row, bundle, email="admin@authorityclosers.com")
    owner = ActorContext(uuid4(), uuid4(), bundle.provider_control_tenant_id)

    view = await service.save_settings(owner, **settings_for(bundle))

    # The ledger's own cap is lifted out of the way; the cap per month is the limit.
    ledger = BudgetAccount.from_dict(row.snapshot)
    assert ledger.cap_paise == LEDGER_OPEN_CAP_PAISE and row.revision == 3
    assert ledger.cap_approval.explicit_above_ceiling is True
    (saved,) = service.database.settings
    assert (saved.revision, saved.ceiling_paise, saved.period, saved.period_cap_paise) == (
        1,
        1_000_000,
        "monthly",
        300_000,
    )
    assert saved.set_by_person_id == owner.person_id
    assert view["approved_cap_paise"] == 1_000_000
    assert view["settings"]["period"] == "monthly" and view["settings"]["cap_paise"] == 300_000
    assert view["settings"]["can_change_ceiling"] is True
    # The open hold (2,500 paise) counts against this month.
    assert view["budget"]["cap_paise"] == 300_000
    assert view["budget"]["available_paise"] == 297_500
    (event,) = audit
    assert event["action"] == SETTINGS_ACTION
    assert event["payload"]["before"] == {
        "ceiling_paise": 850_000,
        "period": "lifetime",
        "cap_paise": 150_000,
        "from_release": True,
    }
    assert event["payload"]["after"] == {
        "ceiling_paise": 1_000_000,
        "period": "monthly",
        "cap_paise": 300_000,
    }
    assert application._receipt.await_args.args[2] == "budget_settings"

    # Any Admin then raises this month's cap in one click: a new settings revision,
    # the ledger untouched; above the ceiling is refused.
    admin = ActorContext(uuid4(), uuid4(), bundle.provider_control_tenant_id)
    raised = await service.save(
        admin,
        bundle=bundle,
        new_cap_paise=400_000,
        expected_revision=3,
        reason="Raised by Rs 1,000 from Execution & budget",
        key="raise-1",
    )
    assert row.revision == 3 and len(service.database.settings) == 2
    assert raised["settings"]["cap_paise"] == 400_000 and raised["settings"]["revision"] == 2
    with pytest.raises(ConversationDenied, match="cannot exceed the ceiling"):
        await service.save(
            admin,
            bundle=bundle,
            new_cap_paise=1_000_001,
            expected_revision=3,
            reason="too much",
            key="raise-2",
        )


@pytest.mark.asyncio
async def test_settings_refuse_stale_screens_caps_above_the_ceiling_and_lifetime_below_spend(
    audit,
):
    scope_id = uuid4()
    bundle = bundle_for(scope_id, cap=850_000)
    row = ledger_row(scope_id)
    service, _ = service_for(row, bundle, email="admin@authorityclosers.com")
    owner = ActorContext(uuid4(), uuid4(), bundle.provider_control_tenant_id)
    with pytest.raises(ValueError, match="between INR 0 and the ceiling"):
        await service.save_settings(owner, **settings_for(bundle, cap_paise=1_000_001))
    with pytest.raises(ConversationConflict, match="Reload before saving"):
        await service.save_settings(owner, **settings_for(bundle, expected_setting_revision=1))
    with pytest.raises(ConversationConflict, match="already spent or held"):
        await service.save_settings(
            owner, **settings_for(bundle, period="lifetime", cap_paise=2_000)
        )
    assert audit == [] and service.database.settings == [] and row.revision == 2

    # Back to lifetime: the ledger's cap becomes the chosen cap.
    view = await service.save_settings(
        owner, **settings_for(bundle, period="lifetime", cap_paise=1_000_000)
    )
    assert BudgetAccount.from_dict(row.snapshot).cap_paise == 1_000_000
    assert service.database.settings[0].period_cap_paise is None
    assert view["budget"]["cap_paise"] == 1_000_000
