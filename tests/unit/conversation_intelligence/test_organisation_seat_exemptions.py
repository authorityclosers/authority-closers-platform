"""Fictional release approvals preserve old bundles and bind exact tenants."""

from pathlib import Path
from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence.activation_contract import (
    ActivationContractError,
    InternalTesterApproval,
    OrganisationSeatExemption,
    load_hosted_approval_bundle,
)
from tests.unit.conversation_intelligence.test_acquisition_provider_policy import (
    _bundle as acquisition_bundle,
)
from tests.unit.conversation_intelligence.test_acquisition_provider_policy import (
    _paid_policy,
    _stage_supplement,
)
from tests.unit.conversation_intelligence.test_activation_contract import _allowance, _bundle
from tests.unit.conversation_intelligence.test_organisation_acquisition_policies import (
    organisation_bundle,
)


def exemption(tenant_id=None, **updates):
    values = dict(
        id=uuid4(),
        tenant_id=tenant_id or uuid4(),
        authorization_ref="ref:approval/fictional-owner-seats",
        reason="Owner organisation: no seat limit",
    )
    values.update(updates)
    return OrganisationSeatExemption(**values)


def test_empty_exemptions_preserve_existing_fixture_bytes_and_digest():
    raw = Path("tests/fixtures/organisation_acquisition_legacy_staging.json").read_bytes()
    bundle = load_hosted_approval_bundle(raw)
    assert bundle.to_json() == raw
    assert bundle.digest == "a1ba21d8c0e83cc694e389018d18239576812516f34a79e6fde260b38f7efe4a"
    assert "organisation_seat_exemptions" not in bundle.as_dict()
    payload = bundle.as_dict() | {"organisation_seat_exemptions": []}
    assert load_hosted_approval_bundle(payload).to_json() == raw


def test_exemptions_round_trip_and_change_digest():
    base = _bundle(allowances=(_allowance(),))
    assert base.digest == "f4c7b59e41eadcfc7dadde5b63b50508adce7f0c71c5ecab50e9942dae17d52b"
    entries = (exemption(), exemption())
    payload = base.as_dict() | {
        "organisation_seat_exemptions": [entry.model_dump(mode="json") for entry in entries]
    }
    bundle = load_hosted_approval_bundle(payload)
    assert bundle.organisation_seat_exemptions == entries
    assert load_hosted_approval_bundle(bundle.to_json()) == bundle
    assert bundle.digest != base.digest


@pytest.mark.parametrize(
    "conflict",
    [
        "tenant",
        "id",
        "operations",
        "allowance",
        "stage",
        "policy",
        "public_policy",
        "tester",
        "supplement",
    ],
)
def test_exemptions_reject_duplicate_identity_and_operations_tenant(conflict):
    base = (
        organisation_bundle()
        if conflict in {"policy", "public_policy"}
        else _bundle(allowances=(_allowance(),))
    )
    if conflict == "tester":
        base = _bundle(
            internal_tester_accounts=(
                InternalTesterApproval(
                    id=uuid4(),
                    email="tester@example.test",
                    authorization_ref="ref:approval/fictional-tester",
                    scopes=("account_minutes",),
                    reason="Approved internal tester exemption",
                ),
            )
        )
    elif conflict == "supplement":
        policy = _paid_policy()
        base = acquisition_bundle(
            policy,
            budget_cap_paise=10_000,
            paid_approval_ref="ref:approval/fictional-paid",
            stage_call_supplements=(_stage_supplement(policy),),
        )
    first, second = exemption(), exemption()
    code = "duplicate_approval_id"
    if conflict == "tenant":
        second = exemption(first.tenant_id)
        code = "duplicate_organisation_seat_exemption_tenant"
    elif conflict == "id":
        second = exemption(id=first.id)
    elif conflict == "operations":
        first = exemption(base.provider_control_tenant_id)
        code = "organisation_seat_exemption_tenant_invalid"
    else:
        collision = {
            "allowance": lambda: base.allowances[0].id,
            "stage": lambda: base.stages[0].id,
            "policy": lambda: base.organisation_acquisition_policies[0].id,
            "public_policy": lambda: base.acquisition_policy.id,
            "tester": lambda: base.internal_tester_accounts[0].id,
            "supplement": lambda: base.stage_call_supplements[0].id,
        }[conflict]()
        first = exemption(id=collision)
    payload = base.as_dict() | {
        "organisation_seat_exemptions": [entry.model_dump(mode="json") for entry in (first, second)]
    }
    with pytest.raises(ActivationContractError, match=code):
        load_hosted_approval_bundle(payload)


@pytest.mark.parametrize(
    "updates",
    [{"reason": "Customer exemption"}, {"authorization_ref": "https://example.test/approval"}],
)
def test_exemption_reason_and_reference_are_strict(updates):
    with pytest.raises(ValueError):
        exemption(**updates)


def test_exemption_list_is_bounded():
    payload = _bundle().as_dict() | {
        "organisation_seat_exemptions": [exemption().model_dump(mode="json") for _ in range(9)]
    }
    with pytest.raises(ActivationContractError):
        load_hosted_approval_bundle(payload)
