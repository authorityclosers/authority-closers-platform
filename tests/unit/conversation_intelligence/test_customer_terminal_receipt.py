"""Fictional receipt boundaries; no financial persistence or provider effects."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from uuid import UUID

import pytest

from ac_platform.conversation_intelligence.checkpoints import SourceBinding, content_hash
from ac_platform.conversation_intelligence.customer_terminal_receipt import (
    CustomerTerminalFailureReceipt,
    validate_terminal_failure_binding,
)
from ac_platform.conversation_intelligence.entitlements import Reservation
from tests.unit.conversation_intelligence.test_entitlements import permission, quote


def uid(number):
    return str(UUID(int=number))


def receipt():
    return CustomerTerminalFailureReceipt(
        source=SourceBinding(uid(1), uid(2), "a" * 64, "v1"),
        usage_id=uid(3),
        submission_id=uid(4),
        duration_evidence_sha256="b" * 64,
        reserved_seconds=1041,
        run_id=uid(5),
        recovery_generation=1,
        failure_event_id=uid(6),
        failure_event_sha256="c" * 64,
        completed_at_epoch=1791600000,
    )


def validate(value, canonical=None, **changes):
    return validate_terminal_failure_binding(
        value,
        receipt() if canonical is None else canonical,
        **{"run_state": "failed", "task_state": "uncertain", "report_published": False, **changes},
    )


def test_receipt_round_trip_is_exact_immutable_and_contains_no_provider_claim():
    value = receipt()
    payload = value.as_dict()
    assert payload["schema"] == "ac.sales_xray.CustomerTerminalFailureReceipt/1"
    assert CustomerTerminalFailureReceipt.from_dict(payload) == value
    assert value.fingerprint == content_hash(payload)
    assert "actual_paise" not in payload and "no_charge_receipt" not in payload
    with pytest.raises(FrozenInstanceError):
        value.reserved_seconds = 1
    assert validate(value) is None
    assert validate(value) is None


@pytest.mark.parametrize("state", ["failed", "uncertain"])
def test_terminal_customer_evidence_does_not_need_a_provider_no_charge_receipt(state):
    value = receipt()
    accepted = quote(source=value.source)
    provider = Reservation(
        "provider-reservation",
        accepted,
        permission(accepted),
        state="uncertain",
        attempt_id="original-attempt",
        uncertainty_ref="original-evidence",
    )
    before = deepcopy(provider.as_dict())
    validate(value, task_state=state)
    assert provider.as_dict() == before
    assert provider.committed_paise == accepted.max_cost_paise
    assert provider.committed_seconds == accepted.entitlement_seconds
    assert provider.no_charge_receipt is None


@pytest.mark.parametrize(
    "field,wrong",
    [
        ("usage_id", uid(30)),
        ("submission_id", uid(40)),
        ("run_id", uid(50)),
        ("recovery_generation", 2),
        ("failure_event_id", uid(60)),
        ("failure_event_sha256", "d" * 64),
        ("duration_evidence_sha256", "e" * 64),
        ("reserved_seconds", 1042),
        ("completed_at_epoch", 1791600001),
    ],
)
def test_different_usage_source_generation_or_original_event_is_rejected(field, wrong):
    with pytest.raises(ValueError, match="binding mismatch"):
        validate(replace(receipt(), **{field: wrong}))


@pytest.mark.parametrize(
    "field,wrong",
    [
        ("tenant_id", uid(10)),
        ("recording_id", uid(20)),
        ("source_sha256", "d" * 64),
        ("source_revision", "v2"),
    ],
)
def test_every_source_component_is_bound(field, wrong):
    value = receipt()
    with pytest.raises(ValueError, match="binding mismatch"):
        validate(replace(value, source=replace(value.source, **{field: wrong})))


@pytest.mark.parametrize(
    "changes",
    [
        {"run_state": "running"},
        {"run_state": "completed"},
        {"task_state": "queued"},
        {"task_state": "running"},
        {"task_state": "completed"},
        {"task_state": "cancelled"},
        {"task_state": "erased"},
        {"report_published": True},
        {"report_published": None},
        {"report_published": 0},
    ],
)
def test_live_cancelled_erased_published_or_unknown_facts_cannot_release(changes):
    with pytest.raises(ValueError):
        validate(receipt(), **changes)


@pytest.mark.parametrize(
    "field,value",
    [
        ("reserved_seconds", True),
        ("reserved_seconds", 0),
        ("reserved_seconds", 6001),
        ("reserved_seconds", "1041"),
        ("reserved_seconds", 1.0),
        ("recovery_generation", False),
        ("recovery_generation", 0),
        ("completed_at_epoch", None),
        ("completed_at_epoch", True),
        ("completed_at_epoch", 0),
        ("duration_evidence_sha256", "f" * 63),
        ("failure_event_sha256", "F" * 64),
        ("run_id", "not-a-uuid"),
        ("usage_id", 3),
        ("submission_id", UUID(int=4)),
        ("failure_event_id", uid(6).replace("-", "")),
        ("source", {}),
    ],
)
def test_invalid_snapshots_never_coerce_missing_or_malformed_evidence(field, value):
    payload = receipt().as_dict()
    payload[field] = value
    with pytest.raises(ValueError):
        CustomerTerminalFailureReceipt.from_dict(payload)


@pytest.mark.parametrize("change", ["extra", "missing", "schema", "source-extra"])
def test_decoder_requires_exact_versioned_fields(change):
    payload = receipt().as_dict()
    if change == "extra":
        payload["no_work"] = True
    elif change == "missing":
        del payload["failure_event_sha256"]
    elif change == "schema":
        payload["schema"] = "ac.sales_xray.CustomerTerminalFailureReceipt/2"
    else:
        payload["source"]["person_id"] = uid(7)
    with pytest.raises(ValueError):
        CustomerTerminalFailureReceipt.from_dict(payload)


def test_deserialized_data_does_not_stand_in_for_independently_loaded_canonical_facts():
    with pytest.raises(ValueError, match="typed customer failure"):
        validate(receipt(), canonical=receipt().as_dict())
