from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from ac_platform.conversation_intelligence.activation_contract import (
    AcquisitionProviderPolicy,
    AcquisitionProviderProfile,
    AcquisitionStagePolicy,
)
from ac_platform.conversation_intelligence.application import ConversationDenied
from ac_platform.conversation_intelligence.models import ConversationProviderConfiguration
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.conversation_intelligence.provider_registry import parse_registry_config
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


def _approved_bundle(
    config: object,
    *,
    funded: bool = False,
    text_provider: str = "groq",
    text_cost_paise: int = 0,
):
    state = _state()
    bundle = _bundle(
        state,
        "a" * 64,
        config.digest,
        now_epoch=1_000,
        funded=funded,
        text_provider=text_provider,
        text_cost_paise=text_cost_paise,
    )  # type: ignore[attr-defined]
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


def test_pinned_alternate_gemini_profile_is_a_real_activation_option() -> None:
    base_config = _registry_config(
        "approved-gemini-base-v1", funded=True, text_provider="gemini", text_cost_paise=40
    )
    alternate_value = base_config.as_dict()
    alternate_endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-3.1-pro-preview:generateContent"
    )
    for provider in alternate_value["providers"]:
        if provider["provider_id"] == "gemini":
            provider["model_id"] = "gemini-3.1-pro-preview"
            provider["endpoint"] = alternate_endpoint
            provider["endpoint_sha256"] = hashlib.sha256(alternate_endpoint.encode()).hexdigest()
    for route in alternate_value["routes"]:
        if route["provider_id"] == "gemini":
            route["model_id"] = "gemini-3.1-pro-preview"
    alternate_config = parse_registry_config(alternate_value)
    bundle = _approved_bundle(base_config, funded=True, text_provider="gemini", text_cost_paise=40)
    policy = bundle.acquisition_policy
    assert policy is not None
    profile = AcquisitionProviderProfile(
        profile_id="gemini-31-pro-preview",
        stages=tuple(
            stage.model_copy(
                update={
                    "configuration_sha256": alternate_config.digest,
                    "model_id": (
                        "gemini-3.1-pro-preview" if stage.stage in {"C4", "C5"} else stage.model_id
                    ),
                }
            )
            for stage in policy.stages
        ),
    )
    pinned = bundle.model_copy(
        update={
            "acquisition_policy": policy.model_copy(update={"profiles": (profile,)}),
        }
    )

    dispatches = ConversationProviderAdmin._approved_configuration(_row(alternate_config), pinned)
    assert [(item.provider_id, item.model_id) for item in dispatches] == [
        ("elevenlabs", "scribe_v2"),
        ("gemini", "gemini-3.1-pro-preview"),
        ("gemini", "gemini-3.1-pro-preview"),
    ]


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


def test_activation_cap_covers_approved_c4_request_count() -> None:
    config = _registry_config("approved-cap-v1", funded=True, text_cost_paise=40)
    config = replace(
        config,
        providers=tuple(
            replace(provider, max_cost_paise=10 if provider.provider_id == "elevenlabs" else 40)
            for provider in config.providers
        ),
    )
    bundle = _approved_bundle(config)
    policy = bundle.acquisition_policy
    assert policy is not None
    stages = tuple(
        stage.model_copy(
            update={
                "max_cost_paise": 10 if stage.stage == "C2" else 40,
                "max_requests": 3 if stage.stage == "C4" else 1,
            }
        )
        for stage in policy.stages
    )
    bounded = bundle.model_copy(
        update={
            "budget_cap_paise": 100,
            "acquisition_policy": policy.model_copy(update={"stages": stages}),
        }
    )
    with pytest.raises(ConversationDenied, match="pinned activation approval"):
        ConversationProviderAdmin._approved_configuration(_row(config), bounded)


def test_activation_cap_counts_c2_and_c5_once() -> None:
    config = _registry_config("approved-cap-stage-count-v1", funded=True, text_cost_paise=40)
    config = replace(
        config,
        providers=tuple(
            replace(provider, max_cost_paise=10 if provider.provider_id == "elevenlabs" else 40)
            for provider in config.providers
        ),
    )
    bundle = _approved_bundle(config, funded=True, text_cost_paise=40)
    policy = bundle.acquisition_policy
    assert policy is not None
    stages = tuple(
        stage.model_copy(
            update={
                "max_cost_paise": 10 if stage.stage == "C2" else 40,
                "max_requests": (2 if stage.stage == "C2" else 3 if stage.stage == "C4" else 9),
            }
        )
        for stage in policy.stages
    )
    bounded = bundle.model_copy(
        update={
            "budget_cap_paise": 170,
            "acquisition_policy": policy.model_copy(update={"stages": stages}),
        }
    )

    dispatches = ConversationProviderAdmin._approved_configuration(_row(config), bounded)

    assert len(dispatches) == 3


def test_activation_uses_the_persisted_admin_limit_below_release_cap() -> None:
    config = _registry_config(
        "approved-effective-cap-v1", funded=True, text_cost_paise=40
    )
    bundle = _approved_bundle(config, funded=True, text_cost_paise=40)

    with pytest.raises(ConversationDenied, match="pinned activation approval"):
        ConversationProviderAdmin._approved_configuration(
            _row(config), bundle, budget_limit_paise=50_079
        )

    dispatches = ConversationProviderAdmin._approved_configuration(
        _row(config), bundle, budget_limit_paise=50_080
    )
    assert len(dispatches) == 3
