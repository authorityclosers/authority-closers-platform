from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from ac_platform.conversation_intelligence.activation_contract import (
    AcquisitionProviderPolicy,
    AcquisitionStagePolicy,
)
from ac_platform.conversation_intelligence.application import ConversationDenied
from ac_platform.conversation_intelligence.models import ConversationProviderConfiguration
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from tests.database.test_conversation_authority_postgresql import (
    _bundle,
    _registry_config,
)

TENANT_ID = UUID("10000000-0000-4000-8000-000000000001")
PERSON_ID = UUID("20000000-0000-4000-8000-000000000002")


def _state() -> SimpleNamespace:
    return SimpleNamespace(tenant_id=TENANT_ID, person_id=PERSON_ID)


def _row(config: object, *, digest: str | None = None) -> ConversationProviderConfiguration:
    value = config.as_dict()  # type: ignore[attr-defined]
    return ConversationProviderConfiguration(
        id=uuid4(),
        tenant_id=TENANT_ID,
        person_id=PERSON_ID,
        session_id=uuid4(),
        revision=1,
        configuration_sha256=digest or config.digest,  # type: ignore[attr-defined]
        configuration=value,
        created_at=datetime.now(UTC),
    )


def _approved_bundle(config: object):
    state = _state()
    bundle = _bundle(state, "a" * 64, config.digest, now_epoch=1_000)  # type: ignore[attr-defined]
    fields = (
        "stage",
        "configuration_sha256",
        "provider_id",
        "model_id",
        "recipe_revision",
        "permission_ref",
        "retention_ref",
        "professional_gate_ref",
        "pricing_ref",
        "provider_terms_ref",
        "privacy_ref",
        "credential_ref",
        "free_allowance_ref",
        "no_paid_overage_ref",
        "privacy_revision",
        "privacy_notice",
        "expires_at_epoch",
        "max_requests",
        "entitlement_seconds",
        "zero_cost_basis",
        "price_evidence_sha256",
        "max_cost_paise",
        "max_source_duration_ms",
        "max_input_bytes",
        "max_completion_tokens",
        "profile_sha256",
    )
    templates = tuple(
        AcquisitionStagePolicy(**{field: getattr(stage, field) for field in fields})
        for stage in bundle.stages
    )
    policy = AcquisitionProviderPolicy(
        schema="ac.sales-xray.acquisition-provider-policy/1",
        id=uuid4(),
        tenant_id=TENANT_ID,
        processing_person_id=PERSON_ID,
        authorization_ref="ref:approval/acquisition-test",
        expires_at_epoch=bundle.expires_at_epoch - 1,
        max_recordings=64,
        max_source_bytes=134_217_728,
        max_stored_source_bytes=8_589_934_592,
        stages=templates,  # type: ignore[arg-type]
    )
    return bundle.model_copy(update={"stages": (), "acquisition_policy": policy})


def test_only_pinned_routes_for_an_exact_configuration_can_activate() -> None:
    config = _registry_config("approved-config-v1")
    bundle = _approved_bundle(config)

    dispatches = ConversationProviderAdmin._approved_configuration(_row(config), bundle)

    assert [(item.task, item.provider_id, item.model_id) for item in dispatches] == [
        ("asr", "elevenlabs", "scribe_v2"),
        ("facts", "groq", "openai/gpt-oss-120b"),
        ("coaching", "groq", "openai/gpt-oss-120b"),
    ]

    drifted = _registry_config("approved-config-v2")
    with pytest.raises(ConversationDenied, match="pinned activation approval"):
        ConversationProviderAdmin._approved_configuration(_row(drifted), bundle)


def test_exact_source_approval_cannot_be_promoted_to_a_global_activation() -> None:
    state = _state()
    config = _registry_config("approved-config-v1")
    exact_source_only = _bundle(state, "a" * 64, config.digest, now_epoch=1_000)

    with pytest.raises(ConversationDenied, match="pinned activation approval"):
        ConversationProviderAdmin._approved_configuration(
            _row(config),
            exact_source_only,
        )


def test_activation_rejects_configuration_digest_mismatch_even_if_row_claims_old_digest() -> None:
    state = _state()
    config = _registry_config("approved-config-v1")
    bundle = _bundle(state, "a" * 64, config.digest, now_epoch=1_000)

    with pytest.raises(ConversationDenied, match="pinned activation approval"):
        ConversationProviderAdmin._approved_configuration(
            _row(config, digest="b" * 64),
            bundle,
        )
