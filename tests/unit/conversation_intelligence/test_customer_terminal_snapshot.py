"""Fictional paired snapshot parity; transactional settlement is tested separately."""

from copy import deepcopy
from dataclasses import replace

import pytest

from ac_platform.conversation_intelligence.entitlements import (
    BudgetAccount,
    MinuteAccount,
    NoChargeReceipt,
    Reservation,
    SettlementReceipt,
    mark_dispatched,
    mark_uncertain,
    record_customer_terminal_failure,
    release,
    reserve,
    settle,
)
from tests.unit.conversation_intelligence.test_customer_terminal_receipt import receipt, uid
from tests.unit.conversation_intelligence.test_entitlements import accounts, permission, quote

STATES = (
    "reserved",
    "in_flight",
    "uncertain",
    "settled",
    "reconciliation_required",
    "released_before_dispatch",
    "released_after_dispatch",
)

# Generated from the source-pinned, unmodified entitlements.py, not the candidate.
LEGACY_FINGERPRINTS = {
    "reserved": (
        "15d5cc92361c6c4f6d469f82af4981fdca48cde9c28c69581bed269f63a2aba1",
        "3fce9f2f2c6cbd1330c8a481d29cbdc0d2c368e4ea4370a2785961846d67335e",
        "f6dd35f9fbe219ba88dec3b81dd640623f18d7e173001de7737f0433906ef84e",
    ),
    "in_flight": (
        "e76833ac0f535bc44ed980ee3bbae48ef498e891e77456bc63e17af87b5602aa",
        "d4140d5c82f3e9b99ca2f964218af91670f75d62e54db28c9313d4200716b646",
        "a48c2aa203e6c19dfbad862e9eac30c2c88c1bbe4f101470d135f5db7a8a2bbb",
    ),
    "uncertain": (
        "452c2d0b0bf52471e952c2e45c941288a21260d92a34b1d3165878f8732b37b0",
        "37a3ea5a92ea5af4d0e0b17b252748d47a6d91e8339083c91ee49888a9c96dd5",
        "582242b4baeef938237e6906271fed9c6a097e50703863a6c2f1504aef5f9372",
    ),
    "settled": (
        "c1de9d113209ac5073ccbd166b22251e49fa36eadf96233f81b3073d8842df05",
        "66d239a4ebd1b8e15e8f0362ee465b10f91f901b5c3e493fde921a21a7a6c245",
        "dc3186197dc86d044e4ebc2d7ec03054e03a4f19bbbf79ff5195255c7bd98259",
    ),
    "reconciliation_required": (
        "146218af41c8df3aa288d24ff33e391966f2d0276fcfd0cb88a58bad0808bf72",
        "c6ec72318f629de1d353c4bf23a40b2a865de8ae5b5245924734df8e225934b3",
        "9b1d5d69e57db0a908c5788df8848c3e0a958b875afb7d18c5e909d5a8f1eaef",
    ),
    "released_before_dispatch": (
        "4b467ca3868644c48d01d52a15404aa53852c9b286167977c7e43dbff1ea0c25",
        "4aa28bd70354b110288c7a662ba4bff96f361adf642f585707d492eeeaa40e35",
        "8cb2d94a4bacf5fa6ee761ca5e330ad54c7a047a448e167682079e26b9eca65a",
    ),
    "released_after_dispatch": (
        "39e8e705ea022a5a33d1cccacc0d18a103c64582fadec92b080192b289285dad",
        "17e6ff2ebe4e4b8ba572219377cb3eb263f0edc205a7bd60fc721831b35529de",
        "61eee283a179cd91041a47e5d98b9f4488ba855cd7070dbd67a8b281647f9904",
    ),
}


def held(state="uncertain", *, seconds=1041, configuration=None):
    value = receipt()
    minutes, budget = accounts(seconds=3000, tenant=value.source.tenant_id)
    quoted = quote(
        source=value.source,
        entitlement_seconds=seconds,
        provider_configuration_sha256=configuration,
    )
    current = reserve(minutes, budget, "reserve-a", quoted, permission(quoted), 200)
    if state == "reserved":
        return current
    if state == "released_before_dispatch":
        return release(current.minutes, current.budget, "reserve-a", "not-dispatched")
    current = mark_dispatched(current.minutes, current.budget, "reserve-a", "attempt-a", 200)
    if state == "in_flight":
        return current
    if state == "released_after_dispatch":
        return release(
            current.minutes,
            current.budget,
            "reserve-a",
            "provider-confirmed",
            NoChargeReceipt(
                "reserve-a",
                quoted.fingerprint,
                "fixture",
                "attempt-a",
                "typed-provider-confirmation",
                "confirmed_not_executed_or_charged",
            ),
        )
    current = mark_uncertain(current.minutes, current.budget, "reserve-a", "original-observation")
    if state == "uncertain":
        return current
    return settle(
        current.minutes,
        current.budget,
        "reserve-a",
        provider_receipt(
            current,
            actual_seconds=seconds + 59 if state == "reconciliation_required" else seconds,
            actual_paise=2600 if state == "reconciliation_required" else 2100,
        ),
    )


def provider_receipt(current, **changes):
    return SettlementReceipt(
        **{
            "reservation_id": "reserve-a",
            "quote_fingerprint": current.reservation.quote.fingerprint,
            "provider_id": "fixture",
            "attempt_id": "attempt-a",
            "actual_seconds": 1041,
            "actual_paise": 2100,
            "receipt_ref": "original-provider-usage",
            **changes,
        }
    )


def failed(current, value=None, canonical=None, **facts):
    value = receipt() if value is None else value
    return record_customer_terminal_failure(
        current.minutes,
        current.budget,
        "reserve-a",
        value,
        value if canonical is None else canonical,
        **{"run_state": "failed", "task_state": "uncertain", "report_published": False, **facts},
    )


@pytest.mark.parametrize("state", STATES)
def test_absent_customer_receipt_preserves_pinned_legacy_fingerprints(state):
    current = held(state)
    snapshots = (current.reservation, current.minutes, current.budget)
    assert tuple(item.fingerprint for item in snapshots) == LEGACY_FINGERPRINTS[state]
    for item in snapshots:
        original = item.as_dict()
        assert "customer_terminal_failure" not in str(original)
        assert type(item).from_dict(deepcopy(original)).as_dict() == original
        assert type(item).from_dict(original).fingerprint == item.fingerprint


@pytest.mark.parametrize("state", STATES)
def test_failed_customer_release_preserves_original_provider_evidence_and_exposure(state):
    current = held(state)
    before = current.reservation.as_dict()
    result = failed(current)
    assert result.changed is True
    assert result.reservation.committed_seconds == 0
    assert result.minutes.available_seconds == 3000
    assert result.minutes.grants == current.minutes.grants
    assert result.budget.available_paise == current.budget.available_paise
    assert result.reservation.committed_paise == current.reservation.committed_paise
    assert result.budget.has_overrun == current.budget.has_overrun
    after = result.reservation.as_dict()
    assert after.pop("customer_terminal_failure") == receipt().as_dict()
    assert after == before
    assert current.reservation.as_dict() == before
    assert result.minutes.reservations == result.budget.reservations
    assert failed(result).changed is False


@pytest.mark.parametrize("state", STATES)
def test_terminal_snapshot_roundtrip_keeps_pair_equality_and_provider_exposure(state):
    current = failed(held(state))
    minutes = MinuteAccount.from_dict(deepcopy(current.minutes.as_dict()))
    budget = BudgetAccount.from_dict(deepcopy(current.budget.as_dict()))
    assert minutes == current.minutes and budget == current.budget
    assert minutes.fingerprint == current.minutes.fingerprint
    assert budget.fingerprint == current.budget.fingerprint
    assert minutes.reservations == budget.reservations
    assert failed(replace(current, minutes=minutes, budget=budget)).changed is False


@pytest.mark.parametrize("state", STATES)
def test_terminal_failure_fences_new_and_repeated_dispatch(state):
    current = failed(held(state))
    for attempt in ("attempt-a", "attempt-new"):
        with pytest.raises(ValueError, match="terminal failure fences"):
            mark_dispatched(current.minutes, current.budget, "reserve-a", attempt, 200)


@pytest.mark.parametrize("overrun", [False, True])
def test_late_provider_settlement_cannot_restore_customer_charge(overrun):
    current = failed(held())
    original_failure = current.reservation.customer_terminal_failure
    result = settle(
        current.minutes,
        current.budget,
        "reserve-a",
        provider_receipt(current, actual_paise=2600 if overrun else 2100),
    )
    assert result.reservation.committed_seconds == 0
    assert result.minutes.available_seconds == 3000
    assert result.reservation.customer_terminal_failure == original_failure
    assert result.reservation.settlement == provider_receipt(
        current, actual_paise=2600 if overrun else 2100
    )
    assert result.budget.available_paise == 150_000 - (2600 if overrun else 2100)
    assert settle(result.minutes, result.budget, "reserve-a", result.reservation.settlement) == (
        replace(result, changed=False)
    )
    with pytest.raises(ValueError, match="immutable settlement conflict"):
        settle(
            result.minutes,
            result.budget,
            "reserve-a",
            provider_receipt(result, receipt_ref="conflicting-provider-usage"),
        )


def test_late_no_charge_confirmation_changes_only_provider_exposure():
    current = failed(held())
    result = release(
        current.minutes,
        current.budget,
        "reserve-a",
        "later-confirmation",
        NoChargeReceipt(
            "reserve-a",
            current.reservation.quote.fingerprint,
            "fixture",
            "attempt-a",
            "typed-provider-confirmation",
            "confirmed_not_executed_or_charged",
        ),
    )
    assert result.reservation.customer_terminal_failure == receipt()
    assert result.reservation.committed_seconds == 0
    assert result.reservation.committed_paise == 0
    assert result.minutes.available_seconds == current.minutes.available_seconds
    assert result.budget.available_paise == 150_000


def test_hosted_zero_second_quote_binds_canonical_source_admission():
    current = held(seconds=0)
    assert current.reservation.quote.entitlement_seconds == 0
    result = failed(current)
    assert result.minutes.available_seconds == current.minutes.available_seconds == 3000
    assert result.reservation.customer_terminal_failure.reserved_seconds == 1041
    assert result.reservation.committed_paise == current.reservation.committed_paise


def test_failure_receipt_replay_conflict_preserves_original():
    current = failed(held())
    changed = replace(receipt(), failure_event_id=uid(7))
    with pytest.raises(ValueError, match="immutable customer failure conflict"):
        failed(current, changed)
    assert current.reservation.customer_terminal_failure == receipt()


@pytest.mark.parametrize("fact", [{"report_published": True}, {"run_state": "running"}])
def test_receipt_replay_does_not_bypass_current_canonical_validation(fact):
    current = failed(held())
    with pytest.raises(ValueError):
        failed(current, **fact)
    assert current.reservation.customer_terminal_failure == receipt()


@pytest.mark.parametrize("field", ["tenant_id", "recording_id", "source_sha256", "source_revision"])
def test_source_mismatch_is_rejected_before_pair_changes(field):
    changed = replace(
        receipt(),
        source=replace(
            receipt().source,
            **{
                field: "d" * 64
                if field == "source_sha256"
                else "v2"
                if field == "source_revision"
                else uid(99)
            },
        ),
    )
    current = held()
    with pytest.raises(ValueError, match="source differs"):
        failed(current, changed)
    with pytest.raises(ValueError, match="source differs"):
        replace(current.reservation, customer_terminal_failure=changed)
    assert current.reservation.customer_terminal_failure is None


@pytest.mark.parametrize(
    "facts",
    [
        {"run_state": "running"},
        {"run_state": "cancelled"},
        {"run_state": "erased"},
        {"task_state": "running"},
        {"task_state": "completed"},
        {"report_published": True},
        {"report_published": None},
        {"report_published": 0},
    ],
)
def test_missing_or_nonterminal_canonical_facts_cannot_release_minutes(facts):
    current = held()
    with pytest.raises(ValueError):
        failed(current, **facts)
    assert current.reservation.committed_seconds == 1041
    assert current.reservation.customer_terminal_failure is None


def test_mismatched_canonical_generation_is_rejected():
    current = held()
    with pytest.raises(ValueError, match="binding mismatch"):
        failed(current, canonical=replace(receipt(), recovery_generation=2))


@pytest.mark.parametrize("missing_side", ["minutes", "budget"])
def test_divergent_terminal_receipt_pair_is_rejected(missing_side):
    before = held()
    current = failed(before)
    divergent = replace(current, **{missing_side: getattr(before, missing_side)})
    with pytest.raises(ValueError, match="snapshots diverged"):
        failed(divergent)
    with pytest.raises(ValueError, match="snapshots diverged"):
        settle(divergent.minutes, divergent.budget, "reserve-a", provider_receipt(divergent))


@pytest.mark.parametrize("bad", [{}, "receipt", 1, False])
def test_snapshot_rejects_untyped_customer_failure(bad):
    current = held()
    with pytest.raises(ValueError, match="typed customer terminal failure"):
        replace(current.reservation, customer_terminal_failure=bad)
    snapshot = current.reservation.as_dict()
    snapshot["customer_terminal_failure"] = bad
    with pytest.raises(ValueError):
        Reservation.from_dict(snapshot)


def test_new_route_digest_is_preserved_with_customer_failure():
    current = held(configuration="d" * 64)
    result = failed(current)
    assert result.reservation.quote.fingerprint == current.reservation.quote.fingerprint
    assert result.reservation.permission == current.reservation.permission
    assert result.reservation.quote.provider_configuration_sha256 == "d" * 64
    assert Reservation.from_dict(result.reservation.as_dict()) == result.reservation


def test_shared_budget_other_account_is_unchanged_by_customer_failure():
    current = held()
    other_minutes, _ = accounts(tenant=current.minutes.tenant_id, account="account-b")
    other_quote = quote(
        account_id="account-b",
        quote_id="quote-b",
        source=replace(receipt().source, recording_id=uid(99)),
    )
    other = reserve(
        other_minutes, current.budget, "reserve-b", other_quote, permission(other_quote), 200
    )
    current = replace(current, budget=other.budget)
    result = failed(current)
    assert result.budget.reservations[-1] == other.reservation
    assert result.budget.available_paise == current.budget.available_paise
    assert result.minutes.available_seconds == 3000


def test_unknown_reservation_cannot_append_customer_receipt():
    minutes, budget = accounts(tenant=receipt().source.tenant_id)
    with pytest.raises(ValueError, match="unknown reservation"):
        record_customer_terminal_failure(
            minutes,
            budget,
            "missing",
            receipt(),
            receipt(),
            run_state="failed",
            task_state="failed",
            report_published=False,
        )
