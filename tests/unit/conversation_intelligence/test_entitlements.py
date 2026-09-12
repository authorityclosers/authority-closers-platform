"""Synthetic ledger transitions; root integration must test its actual PostgreSQL locks."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace

import pytest

from ac_platform.conversation_intelligence.checkpoints import SourceBinding
from ac_platform.conversation_intelligence.entitlements import (
    BudgetAccount,
    BudgetCapApproval,
    ExecutionPermission,
    MinuteAccount,
    MinuteGrant,
    NoChargeReceipt,
    Quote,
    SettlementReceipt,
    grant_minutes,
    mark_dispatched,
    mark_uncertain,
    metered_seconds,
    release,
    reserve,
    revise_budget_cap,
    settle,
)


def accounts(*, seconds=600, cap=150_000, tenant="tenant-a", account="account-a"):
    minute = MinuteAccount(tenant, account)
    if seconds:
        minute = grant_minutes(
            minute,
            MinuteGrant(
                tenant, account, "grant-a", seconds, "explicit-grant", "authorized-actor", "pilot"
            ),
        )
    approval = BudgetCapApproval(
        "project-pilot",
        "initial-owner-approval",
        "owner-fixture",
        cap,
        "0" * 64,
        "approved project cap",
    )
    return minute, BudgetAccount("project-pilot", cap, approval)


def quote(**changes):
    values = {
        "quote_id": "quote-a",
        "source": SourceBinding("tenant-a", "recording-a", "1" * 64, "v1"),
        "account_id": "account-a",
        "budget_scope_id": "project-pilot",
        "provider_id": "fixture",
        "provider_model": "offline-fixture",
        "recipe_revision": "recipe-1",
        "operation": "analysis",
        "input_sha256": "2" * 64,
        "privacy_revision": "privacy-1",
        "permission_ref": "recording-use",
        "provider_terms_ref": "fixture-terms",
        "retention_ref": "fixture-retention",
        "professional_gate_ref": "fixture-purpose-approval",
        "pricing_ref": "dated-quote-fixture",
        "entitlement_seconds": 120,
        "max_cost_paise": 2500,
        "created_at_epoch": 100,
        "expires_at_epoch": 300,
    }
    return Quote(**{**values, **changes})


def permission(value, **changes):
    return ExecutionPermission(
        **{
            "authorization_ref": "exact-execution-approval",
            "quote_fingerprint": value.fingerprint,
            "approved_by": "authorized-owner",
            "expires_at_epoch": 250,
            **changes,
        }
    )


def reserved(*, seconds=600, cap=150_000, **changes):
    minutes, budget = accounts(seconds=seconds, cap=cap)
    value = quote(**changes)
    return reserve(minutes, budget, "reserve-a", value, permission(value), 200)


def dispatched(**changes):
    held = reserved(**changes)
    return mark_dispatched(held.minutes, held.budget, "reserve-a", "attempt-a", 200)


def settlement(current, **changes):
    return SettlementReceipt(
        **{
            "reservation_id": "reserve-a",
            "quote_fingerprint": current.reservation.quote.fingerprint,
            "provider_id": "fixture",
            "attempt_id": "attempt-a",
            "actual_seconds": 100,
            "actual_paise": 2000,
            "receipt_ref": "exact-usage-receipt",
            **changes,
        }
    )


def test_no_implicit_allowance_and_explicit_grant_is_immutable_idempotent():
    minutes, budget = accounts(seconds=0)
    value = quote()
    assert minutes.available_seconds == 0
    with pytest.raises(ValueError, match="insufficient explicit minute grant"):
        reserve(minutes, budget, "r", value, permission(value), 200)
    grant = MinuteGrant("tenant-a", "account-a", "g", 60, "authorized-grant", "admin", "pilot")
    updated = grant_minutes(minutes, grant)
    assert updated.available_seconds == 60 and minutes.available_seconds == 0
    assert grant_minutes(updated, grant) is updated
    with pytest.raises(ValueError, match="idempotency conflict"):
        grant_minutes(updated, replace(grant, seconds=120))
    with pytest.raises(ValueError, match="cross-tenant"):
        grant_minutes(updated, replace(grant, tenant_id="other"))
    with pytest.raises(FrozenInstanceError):
        grant.seconds = 100


@pytest.mark.parametrize("value", [True, -1, 1.5, "60"])
def test_noninteger_and_negative_units_are_rejected(value):
    with pytest.raises(ValueError, match="integer"):
        quote(entitlement_seconds=value)
    with pytest.raises(ValueError, match="integer"):
        quote(max_cost_paise=value)
    with pytest.raises(ValueError, match="integer"):
        metered_seconds(value)


@pytest.mark.parametrize("milliseconds,seconds", [(1, 1), (1000, 1), (1001, 2), (60_001, 61)])
def test_meter_rounding_once(milliseconds, seconds):
    assert metered_seconds(milliseconds) == seconds


def test_reservation_atomic_budget_failure_does_not_consume_minutes():
    minutes, budget = accounts(cap=2000)
    value = quote(max_cost_paise=2500)
    with pytest.raises(ValueError, match="project budget exhausted"):
        reserve(minutes, budget, "r", value, permission(value), 200)
    assert minutes.available_seconds == 600 and budget.available_paise == 2000
    assert minutes.reservations == budget.reservations == ()


def test_reserve_idempotency_and_quote_expiry_before_dispatch():
    held = reserved()
    again = reserve(
        held.minutes,
        held.budget,
        "reserve-a",
        held.reservation.quote,
        held.reservation.permission,
        400,
    )
    assert again.changed is False and again.minutes.available_seconds == 480
    with pytest.raises(ValueError, match="expired"):
        mark_dispatched(held.minutes, held.budget, "reserve-a", "attempt-a", 400)
    changed = replace(held.reservation.quote, max_cost_paise=2400)
    with pytest.raises(ValueError, match="idempotency conflict"):
        reserve(held.minutes, held.budget, "reserve-a", changed, permission(changed), 200)
    with pytest.raises(ValueError, match="quote already reserved"):
        reserve(
            held.minutes,
            held.budget,
            "repeat-paid-execution",
            held.reservation.quote,
            held.reservation.permission,
            200,
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("provider_id", "another-provider"),
        ("privacy_revision", "privacy-2"),
        ("permission_ref", "another-purpose"),
        ("provider_terms_ref", "terms-2"),
        ("retention_ref", "retention-2"),
        ("recipe_revision", "recipe-2"),
        ("input_sha256", "3" * 64),
        ("expires_at_epoch", 301),
        ("max_cost_paise", 2400),
    ],
)
def test_permission_binds_exact_recording_provider_privacy_and_quote(field, value):
    minutes, budget = accounts()
    original = quote()
    changed = replace(original, **{field: value})
    with pytest.raises(ValueError, match="quote-specific"):
        reserve(minutes, budget, "r", changed, permission(original), 200)


def test_cross_tenant_source_and_expired_permission_rejected():
    minutes, budget = accounts()
    foreign = quote(source=SourceBinding("other", "recording-a", "1" * 64, "v1"))
    with pytest.raises(ValueError, match="tenant/account/budget mismatch"):
        reserve(minutes, budget, "r", foreign, permission(foreign), 200)
    value = quote()
    with pytest.raises(ValueError, match="expired"):
        reserve(minutes, budget, "r", value, permission(value, expires_at_epoch=200), 200)


def test_project_budget_is_shared_across_accounts():
    first = reserved(cap=4000)
    second_minutes, _ = accounts(tenant="tenant-b", account="account-b")
    second_quote = quote(
        source=SourceBinding("tenant-b", "recording-b", "3" * 64, "v1"), account_id="account-b"
    )
    with pytest.raises(ValueError, match="shared project budget exhausted"):
        reserve(
            second_minutes, first.budget, "reserve-b", second_quote, permission(second_quote), 200
        )
    affordable = replace(second_quote, max_cost_paise=1500)
    second = reserve(
        second_minutes, first.budget, "reserve-b", affordable, permission(affordable), 200
    )
    assert second.budget.available_paise == 0
    with pytest.raises(ValueError, match="another tenant/account"):
        release(second.minutes, second.budget, "reserve-a", "foreign-cancel")


def test_paired_divergent_snapshot_fails_before_any_transition():
    held = reserved()
    original_minutes, _ = accounts()
    with pytest.raises(ValueError, match="snapshots diverged"):
        release(original_minutes, held.budget, "reserve-a", "cancel")


def test_zero_priced_offline_and_profile_replay_quote_uses_only_explicit_seconds():
    offline = reserved(max_cost_paise=0)
    assert offline.minutes.available_seconds == 480
    assert offline.budget.available_paise == 150_000
    replay = quote(
        quote_id="profile-replay",
        operation="profile-replay",
        entitlement_seconds=0,
        max_cost_paise=0,
    )
    held = reserve(offline.minutes, offline.budget, "replay-a", replay, permission(replay), 200)
    assert held.minutes.available_seconds == 480
    assert held.budget.available_paise == 150_000
    with pytest.raises(ValueError, match="quote-specific"):
        reserve(
            offline.minutes,
            offline.budget,
            "replay-b",
            replay,
            permission(offline.reservation.quote),
            200,
        )


def test_settlement_is_idempotent_reclaims_unused_hold_and_cannot_release_again():
    started = dispatched()
    receipt = settlement(started)
    done = settle(started.minutes, started.budget, "reserve-a", receipt)
    assert done.minutes.available_seconds == 500
    assert done.budget.available_paise == 148_000
    assert settle(done.minutes, done.budget, "reserve-a", receipt).changed is False
    with pytest.raises(ValueError, match="immutable settlement conflict"):
        settle(done.minutes, done.budget, "reserve-a", replace(receipt, actual_paise=1900))
    with pytest.raises(ValueError, match="cannot release settled"):
        release(done.minutes, done.budget, "reserve-a", "refund-without-authority")


def test_cancellation_releases_once_and_replay_cannot_create_another_call():
    held = reserved()
    cancelled = release(held.minutes, held.budget, "reserve-a", "cancel-before-dispatch")
    assert cancelled.minutes.available_seconds == 600
    assert cancelled.budget.available_paise == 150_000
    assert (
        release(cancelled.minutes, cancelled.budget, "reserve-a", "cancel-before-dispatch").changed
        is False
    )
    with pytest.raises(ValueError, match="release idempotency conflict"):
        release(cancelled.minutes, cancelled.budget, "reserve-a", "another-command")
    with pytest.raises(ValueError, match="second provider attempt"):
        mark_dispatched(cancelled.minutes, cancelled.budget, "reserve-a", "new-attempt", 200)


def test_unknown_provider_outcome_keeps_both_reservations_until_reconciliation():
    started = dispatched()
    unknown = mark_uncertain(started.minutes, started.budget, "reserve-a", "timeout-evidence")
    assert unknown.minutes.available_seconds == 480 and unknown.budget.available_paise == 147_500
    with pytest.raises(ValueError, match="remains reserved"):
        release(unknown.minutes, unknown.budget, "reserve-a", "timeout-is-not-free")
    assert (
        mark_dispatched(unknown.minutes, unknown.budget, "reserve-a", "attempt-a", 200).changed
        is False
    )
    with pytest.raises(ValueError, match="second provider attempt"):
        mark_dispatched(unknown.minutes, unknown.budget, "reserve-a", "attempt-b", 200)
    receipt = NoChargeReceipt(
        "reserve-a",
        unknown.reservation.quote.fingerprint,
        "fixture",
        "attempt-a",
        "provider-confirmed-not-executed",
        "confirmed_not_executed_or_charged",
    )
    released = release(unknown.minutes, unknown.budget, "reserve-a", "reconciled", receipt)
    assert released.minutes.available_seconds == 600 and released.budget.available_paise == 150_000


def test_overrun_is_explicit_actual_usage_hold_and_blocks_new_spend():
    started = dispatched(cap=2500, seconds=120)
    receipt = settlement(started, actual_paise=3000, actual_seconds=150)
    incident = settle(started.minutes, started.budget, "reserve-a", receipt)
    assert incident.reservation.state == "reconciliation_required"
    assert incident.budget.available_paise == -500
    assert incident.minutes.available_seconds == -30
    assert incident.reservation.settlement.actual_paise == 3000
    assert settle(incident.minutes, incident.budget, "reserve-a", receipt).changed is False
    new = quote(quote_id="new", entitlement_seconds=0, max_cost_paise=0)
    with pytest.raises(ValueError, match="overrun holds"):
        reserve(incident.minutes, incident.budget, "reserve-b", new, permission(new), 200)
    with pytest.raises(ValueError, match="unresolved overrun"):
        release(incident.minutes, incident.budget, "reserve-a", "hide-spend")


def test_normal_and_above_ceiling_cap_changes_require_new_exact_owner_approval():
    _, budget = accounts()
    with pytest.raises(ValueError, match="new approval bound"):
        BudgetCapApproval(
            budget.scope_id, "bad", "owner", 170_000, "0" * 64, "cannot-initialize-higher"
        )
    with pytest.raises(ValueError, match="above INR2000"):
        BudgetCapApproval(budget.scope_id, "above", "owner", 200_001, budget.fingerprint, "raise")
    approval = BudgetCapApproval(
        budget.scope_id,
        "new-explicit-owner-approval",
        "owner",
        200_001,
        budget.fingerprint,
        "owner-approved-new-boundary",
        True,
    )
    raised = revise_budget_cap(budget, 200_001, approval)
    assert raised.cap_paise == 200_001
    assert revise_budget_cap(raised, 200_001, approval) is raised
    with pytest.raises(ValueError, match="current budget snapshot"):
        revise_budget_cap(raised, 200_001, replace(approval, approval_ref="stale-approval"))


def test_json_snapshots_roundtrip_and_reject_extra_fields_boolean_units_and_counterfeits():
    held = dispatched()
    for obj in (held.minutes, held.budget, held.reservation.quote, held.reservation.permission):
        assert type(obj).from_dict(obj.as_dict()) == obj
        extra = obj.as_dict()
        extra["approved"] = True
        with pytest.raises(ValueError, match="snapshot fields"):
            type(obj).from_dict(extra)
    malformed = held.minutes.as_dict()
    malformed["grants"][0]["seconds"] = True
    with pytest.raises(ValueError, match="integer"):
        MinuteAccount.from_dict(malformed)
    counterfeit = deepcopy(held.budget.as_dict())
    counterfeit["reservations"][0]["state"] = "released"
    counterfeit["reservations"][0]["release_reason_ref"] = "unproven-cancellation"
    with pytest.raises(ValueError, match="no-charge reconciliation"):
        BudgetAccount.from_dict(counterfeit)
    counterfeit = deepcopy(held.budget.as_dict())
    counterfeit["reservations"][0]["permission"]["quote_fingerprint"] = "3" * 64
    with pytest.raises(ValueError, match="exact recording/provider/privacy quote"):
        BudgetAccount.from_dict(counterfeit)


def test_same_quote_new_source_revision_and_provider_receipt_cannot_cross_bind():
    started = dispatched()
    wrong = settlement(started, provider_id="unapproved-provider")
    with pytest.raises(ValueError, match="does not match"):
        settle(started.minutes, started.budget, "reserve-a", wrong)
    original = started.reservation.quote
    changed = replace(original, source=replace(original.source, source_revision="v2"))
    assert changed.fingerprint != original.fingerprint


def test_two_requests_must_reload_shared_budget_after_first_commit():
    # This is a serialized-transition proof, not a claim that PostgreSQL contention was tested.
    minutes, budget = accounts(cap=3000)
    value = quote()
    committed = reserve(minutes, budget, "r1", value, permission(value), 200)
    second_value = quote(quote_id="quote-b")
    with pytest.raises(ValueError, match="budget exhausted"):
        reserve(
            committed.minutes, committed.budget, "r2", second_value, permission(second_value), 200
        )
    assert committed.budget.available_paise == 500
