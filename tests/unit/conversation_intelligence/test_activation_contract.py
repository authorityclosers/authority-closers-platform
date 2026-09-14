from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import pytest

from ac_platform.conversation_intelligence.activation_contract import (
    HOSTED_APPROVAL_SCHEMA,
    ActivationContractError,
    AllowanceApproval,
    HostedApprovalBundle,
    StageApproval,
    load_hosted_approval_bundle,
)

TENANT_ID = UUID("10000000-0000-4000-8000-000000000001")
PERSON_ID = UUID("20000000-0000-4000-8000-000000000002")
APPROVER_ID = UUID("30000000-0000-4000-8000-000000000004")
BUDGET_SCOPE_ID = UUID("40000000-0000-4000-8000-000000000005")
DEFAULT_ALLOWANCE_ID = UUID("50000000-0000-4000-8000-000000000006")
DEFAULT_STAGE_ID = UUID("60000000-0000-4000-8000-000000000007")
LEGACY_DESCRIPTOR_MAX_BYTES = 128 * 1024 * 1024


def _allowance(
    *,
    approval_id: UUID = DEFAULT_ALLOWANCE_ID,
    person_id: UUID = PERSON_ID,
) -> AllowanceApproval:
    return AllowanceApproval(
        id=approval_id,
        tenant_id=TENANT_ID,
        person_id=person_id,
        seconds=86_400,
        authorization_ref="ref:approval/allowance-1",
        granted_by=APPROVER_ID,
        reason="Approved internal testing allowance",
        max_recordings=4,
        max_source_bytes=LEGACY_DESCRIPTOR_MAX_BYTES,
        max_stored_source_bytes=536_870_912,
    )


def _stage(
    *,
    approval_id: UUID = DEFAULT_STAGE_ID,
    stage: str = "C2",
    person_id: UUID = PERSON_ID,
    source_sha256: str = "a" * 64,
    expires_at_epoch: int = 1_900,
    entitlement_seconds: int | None = None,
    max_completion_tokens: int = 0,
    profile_sha256: str | None = None,
    zero_cost_basis: str = "synthetic",
    max_cost_paise: int = 0,
    free_allowance_ref: str | None = "ref:allowance/1",
) -> StageApproval:
    return StageApproval(
        id=approval_id,
        tenant_id=TENANT_ID,
        person_id=person_id,
        source_sha256=source_sha256,
        configuration_sha256="b" * 64,
        stage=stage,  # type: ignore[arg-type]
        provider_id="elevenlabs" if stage == "C2" else "groq",
        model_id="scribe_v2" if stage == "C2" else "openai/gpt-oss-120b",
        recipe_revision="scribe-v2-native-normalized-v1" if stage == "C2" else "facts-v1",
        permission_ref="ref:permission/1",
        retention_ref="ref:retention/1",
        professional_gate_ref="ref:professional/1",
        pricing_ref="ref:pricing/zero/1",
        provider_terms_ref="ref:provider-terms/1",
        privacy_ref="ref:privacy/1",
        credential_ref="ref:credential/elevenlabs/1",
        free_allowance_ref=free_allowance_ref,
        no_paid_overage_ref="ref:billing/overage-disabled",
        privacy_revision="privacy-20260913-v1",
        privacy_notice="Approved internal testing only; retain the source for the stated window.",
        expires_at_epoch=expires_at_epoch,
        max_requests=3,
        entitlement_seconds=entitlement_seconds,
        zero_cost_basis=zero_cost_basis,  # type: ignore[arg-type]
        price_evidence_sha256="c" * 64,
        max_cost_paise=max_cost_paise,
        max_source_duration_ms=14_400_000,
        max_input_bytes=LEGACY_DESCRIPTOR_MAX_BYTES,
        max_completion_tokens=max_completion_tokens,
        profile_sha256=profile_sha256,
    )


def _bundle(
    *,
    allowances: tuple[AllowanceApproval, ...] = (),
    stages: tuple[StageApproval, ...] | None = None,
    environment: str = "test",
    issued_at_epoch: int = 1_000,
    expires_at_epoch: int = 2_000,
    budget_cap_paise: int = 0,
    paid_approval_ref: str | None = None,
) -> HostedApprovalBundle:
    return HostedApprovalBundle(
        schema_id=HOSTED_APPROVAL_SCHEMA,
        environment=environment,  # type: ignore[arg-type]
        provider_control_tenant_id=TENANT_ID,
        deployment_ref="ref:deployment/test-1",
        issued_at_epoch=issued_at_epoch,
        expires_at_epoch=expires_at_epoch,
        budget_scope_id=BUDGET_SCOPE_ID,
        budget_authorization_ref="ref:budget/test-1",
        budget_owner_id=APPROVER_ID,
        budget_cap_paise=budget_cap_paise,
        paid_approval_ref=paid_approval_ref,
        intake_authorization_ref="ref:intake/test-1",
        intake_retention_ref="ref:intake-retention/test-1",
        retention_days=7,
        max_stored_source_bytes=1_073_741_824,
        allowances=allowances,
        stages=(_stage(),) if stages is None else stages,
    )


def test_bundle_round_trips_canonical_json_and_current_window() -> None:
    bundle = _bundle(allowances=(_allowance(),))

    loaded = load_hosted_approval_bundle(bundle.to_json())

    assert loaded == bundle
    assert loaded.as_dict()["schema"] == HOSTED_APPROVAL_SCHEMA
    assert loaded.to_json() == bundle.to_json()
    assert loaded.digest == bundle.digest
    assert loaded.current(1_500, "test") is loaded


def test_legacy_128_mib_descriptor_remains_loadable() -> None:
    bundle = _bundle(allowances=(_allowance(),), stages=(_stage(),))

    loaded = load_hosted_approval_bundle(bundle.to_json())

    assert loaded.allowances[0].max_source_bytes == LEGACY_DESCRIPTOR_MAX_BYTES
    assert loaded.stages[0].max_input_bytes == LEGACY_DESCRIPTOR_MAX_BYTES


@pytest.mark.parametrize(
    "field",
    [
        "zero_cost_basis",
        "price_evidence_sha256",
        "free_allowance_ref",
        "no_paid_overage_ref",
    ],
)
def test_zero_quote_requires_explicit_price_allocation_and_overage_evidence(field: str) -> None:
    payload = _bundle().as_dict()
    del payload["stages"][0][field]
    with pytest.raises(ActivationContractError):
        load_hosted_approval_bundle(payload)


@pytest.mark.parametrize(
    ("now", "environment", "code"),
    [
        (999, "test", "approval_bundle_inactive"),
        (2_000, "test", "approval_bundle_inactive"),
        (1_500, "production", "approval_environment_mismatch"),
        (True, "test", "approval_now_invalid"),
    ],
)
def test_current_requires_exact_environment_and_active_strict_time(
    now: int, environment: str, code: str
) -> None:
    with pytest.raises(ActivationContractError, match=code):
        _bundle().current(now, environment)


@pytest.mark.parametrize(
    "field",
    [
        "deployment_ref",
        "budget_authorization_ref",
        "intake_authorization_ref",
        "intake_retention_ref",
    ],
)
def test_loader_rejects_urls_and_credential_shaped_references(field: str) -> None:
    bundle = _bundle()
    payload = json.loads(bundle.to_json())
    payload[field] = "ref:https://provider.example/token=secret"

    with pytest.raises(ActivationContractError, match="opaque_reference_invalid"):
        load_hosted_approval_bundle(payload)

    stage_payload = json.loads(bundle.to_json())
    stage_payload["stages"][0]["credential_ref"] = "ref:sk-12345678901234567890"
    with pytest.raises(ActivationContractError, match="opaque_reference_invalid"):
        load_hosted_approval_bundle(stage_payload)


def test_loader_rejects_duplicate_ids_recipients_and_stage_scope() -> None:
    allowance = _allowance()
    duplicate_id_payload = json.loads(_bundle(allowances=(allowance,)).to_json())
    duplicate_id_payload["stages"][0]["id"] = str(allowance.id)
    with pytest.raises(ActivationContractError, match="duplicate_approval_id"):
        load_hosted_approval_bundle(duplicate_id_payload)

    second_allowance = _allowance(
        approval_id=UUID("50000000-0000-4000-8000-000000000008"),
        person_id=UUID("20000000-0000-4000-8000-000000000003"),
    )
    duplicate_recipient_payload = json.loads(
        _bundle(allowances=(allowance, second_allowance), stages=()).to_json()
    )
    duplicate_recipient_payload["allowances"][1]["person_id"] = str(PERSON_ID)
    with pytest.raises(ActivationContractError, match="duplicate_allowance_recipient"):
        load_hosted_approval_bundle(duplicate_recipient_payload)

    second_stage = _stage(
        approval_id=UUID("60000000-0000-4000-8000-000000000009"),
        person_id=UUID("20000000-0000-4000-8000-000000000003"),
    )
    duplicate_scope_payload = json.loads(_bundle(stages=(_stage(), second_stage)).to_json())
    duplicate_scope_payload["stages"][1]["person_id"] = str(PERSON_ID)
    with pytest.raises(ActivationContractError, match="duplicate_stage_scope"):
        load_hosted_approval_bundle(duplicate_scope_payload)


def test_loader_rejects_stage_expiry_outside_bundle_and_unknown_paid_fields() -> None:
    expired_payload = json.loads(_bundle().to_json())
    expired_payload["stages"][0]["expires_at_epoch"] = 2_001
    with pytest.raises(ActivationContractError, match="stage_expiry_outside_bundle"):
        load_hosted_approval_bundle(expired_payload)

    payload = json.loads(_bundle().to_json())
    payload["paid_paise"] = 1
    with pytest.raises(ActivationContractError, match="hosted_approval_invalid"):
        load_hosted_approval_bundle(payload)


def test_paid_stage_requires_explicit_pricing_and_project_cap() -> None:
    paid_stage = _stage(
        zero_cost_basis="paid_pricing_evidence",
        max_cost_paise=50_000,
        free_allowance_ref=None,
    )
    with pytest.raises(ValueError, match="paid_project_cap_required"):
        _bundle(stages=(paid_stage,))

    with pytest.raises(ValueError, match="paid_approval_reference_required"):
        _bundle(stages=(paid_stage,), budget_cap_paise=100_000)

    bundle = _bundle(
        stages=(paid_stage,),
        budget_cap_paise=100_000,
        paid_approval_ref="ref:approval/paid-provider",
    )
    loaded = load_hosted_approval_bundle(bundle.to_json())
    assert loaded.budget_cap_paise == 100_000
    assert loaded.stages[0].max_cost_paise == 50_000

    invalid = json.loads(bundle.to_json())
    invalid["stages"][0]["price_evidence_sha256"] = "not-a-digest"
    with pytest.raises(ActivationContractError):
        load_hosted_approval_bundle(invalid)


def test_free_v1_bundle_canonical_bytes_omit_paid_extension_defaults() -> None:
    bundle = _bundle()
    payload = json.loads(bundle.to_json())
    assert "budget_cap_paise" not in payload
    assert "paid_approval_ref" not in payload
    assert "max_cost_paise" not in payload["stages"][0]


def test_loader_enforces_explicit_source_and_stored_capacity_bounds() -> None:
    allowance = _allowance()
    payload = json.loads(_bundle(allowances=(allowance,)).to_json())
    payload["allowances"][0]["max_source_bytes"] = 20_000_000
    payload["allowances"][0]["max_stored_source_bytes"] = 10_000_000
    with pytest.raises(ActivationContractError, match="allowance_source_bytes_exceed_stored_cap"):
        load_hosted_approval_bundle(payload)

    payload = json.loads(_bundle(allowances=(allowance,)).to_json())
    payload["allowances"][0]["max_stored_source_bytes"] = 2_000_000_000
    with pytest.raises(ActivationContractError, match="allowance_stored_bytes_exceed_bundle_cap"):
        load_hosted_approval_bundle(payload)


def test_loader_rejects_capacity_types_and_out_of_range_values() -> None:
    payload = json.loads(_bundle(allowances=(_allowance(),)).to_json())
    payload["allowances"][0]["max_recordings"] = True
    with pytest.raises(ActivationContractError, match="hosted_approval_invalid"):
        load_hosted_approval_bundle(payload)

    payload = json.loads(_bundle(allowances=(_allowance(),)).to_json())
    payload["max_stored_source_bytes"] = 34_359_738_369
    with pytest.raises(ActivationContractError, match="hosted_approval_invalid"):
        load_hosted_approval_bundle(payload)


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"entitlement_seconds": 1}, "c2_entitlement_must_be_none"),
        (
            {"stage": "C4", "entitlement_seconds": None, "max_completion_tokens": 800},
            "text_entitlement_required",
        ),
        (
            {"stage": "C4", "entitlement_seconds": 0, "max_completion_tokens": 0},
            "text_completion_tokens_required",
        ),
        (
            {"stage": "C5", "entitlement_seconds": 0, "max_completion_tokens": 800},
            "c5_profile_required",
        ),
    ],
    ids=["c2-entitlement", "c4-missing-entitlement", "c4-zero-completion", "c5-profile-missing"],
)
def test_stage_entitlement_completion_and_profile_constraints(
    changes: dict[str, Any],
    code: str,
) -> None:
    payload = json.loads(_bundle().to_json())
    payload["stages"][0].update(changes)
    with pytest.raises(ActivationContractError, match=code):
        load_hosted_approval_bundle(payload)


def test_provider_stage_cannot_add_a_second_audio_minute_charge() -> None:
    stage = _stage(stage="C4", entitlement_seconds=0, max_completion_tokens=800)
    payload = json.loads(_bundle(stages=(stage,)).to_json())
    payload["stages"][0]["entitlement_seconds"] = 1
    with pytest.raises(ActivationContractError, match="provider_entitlement_must_be_zero"):
        load_hosted_approval_bundle(payload)


def test_c5_requires_profile_digest_and_text_stage_accepts_zero_allowance() -> None:
    stage = _stage(
        stage="C5",
        entitlement_seconds=0,
        max_completion_tokens=800,
        profile_sha256="d" * 64,
    )
    loaded = load_hosted_approval_bundle(_bundle(stages=(stage,)).to_json())
    assert loaded.stages[0].profile_sha256 == "d" * 64
    assert loaded.stages[0].entitlement_seconds == 0


def test_strict_bounds_reject_boolean_and_oversized_values_without_leaking_input() -> None:
    payload = json.loads(_bundle().to_json())
    payload["retention_days"] = True
    with pytest.raises(ActivationContractError) as error:
        load_hosted_approval_bundle(payload)
    assert str(error.value) == "hosted_approval_invalid"
    assert "True" not in str(error.value)

    oversized = json.loads(_bundle().to_json())
    oversized["stages"][0]["max_input_bytes"] = LEGACY_DESCRIPTOR_MAX_BYTES + 1
    with pytest.raises(ActivationContractError, match="hosted_approval_invalid"):
        load_hosted_approval_bundle(oversized)

    blank_notice = json.loads(_bundle().to_json())
    blank_notice["stages"][0]["privacy_notice"] = " \t\n"
    with pytest.raises(ActivationContractError, match="privacy_notice_invalid"):
        load_hosted_approval_bundle(blank_notice)


def test_model_copy_is_revalidated_by_loader() -> None:
    forged = _bundle().model_copy(update={"expires_at_epoch": 999})

    with pytest.raises(ActivationContractError, match="approval_bundle_window_invalid"):
        load_hosted_approval_bundle(forged.to_json())
