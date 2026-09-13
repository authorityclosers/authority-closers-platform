"""Pure provider catalog/routing tests using synthetic metadata only."""

from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError

import pytest

from ac_platform.conversation_intelligence.provider_registry import (
    DEFAULT_PROVIDER_CATALOG,
    TASK_CONTRACTS,
    DispatchRequest,
    ModelCatalogEntry,
    ProviderCatalog,
    ProviderCatalogEntry,
    ProviderConfig,
    ProviderRegistryError,
    ProviderRequest,
    ProviderResponse,
    RegistryConfig,
    RegistryPolicy,
    RouteConfig,
    TaskName,
    catalog_public_view,
    parse_registry_config,
    resolve_dispatch,
    task_contract,
    validate_registry_config,
)

_ENDPOINTS = {
    "elevenlabs": "https://api.elevenlabs.io/v1/speech-to-text",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
    "groq": "https://api.groq.com/openai/v1/chat/completions",
}


def _provider(
    *,
    provider_id: str = "elevenlabs",
    model_id: str = "scribe_v2",
    endpoint: str | None = None,
    credential_ref: str | None = "ref:secret:synthetic",
    provider_terms_ref: str | None = "ref:terms:synthetic",
    privacy_ref: str | None = "ref:privacy:synthetic",
    pricing_ref: str | None = "ref:pricing:synthetic",
    free_allowance_ref: str | None = "ref:allowance:synthetic",
    permission_ref: str | None = "ref:permission:synthetic",
    endpoint_approval_ref: str | None = "ref:approval:endpoint",
    local_endpoint_approval_ref: str | None = None,
    max_cost_paise: int | None = 0,
) -> ProviderConfig:
    resolved_endpoint = _ENDPOINTS.get(provider_id) if endpoint is None else endpoint
    endpoint_digest = (
        None
        if resolved_endpoint is None
        else hashlib.sha256(resolved_endpoint.encode("utf-8")).hexdigest()
    )
    return ProviderConfig(
        provider_id=provider_id,
        model_id=model_id,
        endpoint=resolved_endpoint,
        endpoint_sha256=endpoint_digest,
        credential_ref=credential_ref,
        provider_terms_ref=provider_terms_ref,
        privacy_ref=privacy_ref,
        pricing_ref=pricing_ref,
        free_allowance_ref=free_allowance_ref,
        permission_ref=permission_ref,
        endpoint_approval_ref=endpoint_approval_ref,
        local_endpoint_approval_ref=local_endpoint_approval_ref,
        max_cost_paise=max_cost_paise,
    )


def _route(
    task: TaskName, *, provider_id: str = "elevenlabs", model_id: str = "scribe_v2"
) -> RouteConfig:
    contract = task_contract(task)
    return RouteConfig(
        task=task,
        provider_id=provider_id,
        model_id=model_id,
        recipe_revision="recipe-v1",
        profile_revision="none" if not contract.profile_required else "profile-v1",
        prompt_revision="prompt-v1",
        required_input_stage=contract.input_stage,
        reuses_checkpoint_stage=contract.reuse_stage,
    )


def _config(
    *,
    task: TaskName = "asr",
    provider: ProviderConfig | None = None,
    route: RouteConfig | None = None,
    policy: RegistryPolicy | None = None,
) -> RegistryConfig:
    selected_provider = provider or _provider()
    selected_route = route or _route(
        task, provider_id=selected_provider.provider_id, model_id=selected_provider.model_id
    )
    return RegistryConfig(
        revision="registry-v1",
        policy=policy or RegistryPolicy(),
        providers=(selected_provider,),
        routes=(selected_route,),
    )


def _dispatch_request(config: RegistryConfig, *, task: TaskName = "asr") -> DispatchRequest:
    contract = task_contract(task)
    return DispatchRequest(
        task=task,
        config_revision=config.revision,
        config_digest=config.digest,
        permission_ref="ref:permission:synthetic",
        input_stage=contract.input_stage,
    )


def test_catalog_distinguishes_current_transport_from_planned_provider_options() -> None:
    view = {entry["provider_id"]: entry for entry in catalog_public_view()}
    assert DEFAULT_PROVIDER_CATALOG.digest
    assert {view[name]["status"] for name in ("gemini", "groq", "elevenlabs")} == {"implemented"}
    planned = (
        "openai",
        "deepseek",
        "anthropic",
        "openai_compatible_gateway",
        "ollama",
        "vllm",
        "llama_cpp",
        "sarvam",
    )
    assert all(view[name]["status"] == "planned" and view[name]["models"] == [] for name in planned)
    assert view["elevenlabs"]["readiness"] == "transport_available"
    assert view["ollama"]["readiness"] == "planned_no_transport"
    assert view["ollama"]["deployment"] == "local"
    assert view["openai_compatible_gateway"]["deployment"] == "gateway"
    scribe = next(
        model for model in view["elevenlabs"]["models"] if model["model_id"] == "scribe_v2"
    )
    assert {item["task"]: item["status"] for item in scribe["task_support"]} == {
        "asr": "implemented"
    }
    gemini = next(
        model for model in view["gemini"]["models"] if model["model_id"] == "gemini-2.5-flash"
    )
    assert {item["task"]: item["status"] for item in gemini["task_support"]} == {
        "facts": "contract_only",
        "coaching": "contract_only",
    }
    serialized = json.dumps(view, sort_keys=True)
    assert "free_allowance" not in serialized
    assert "api_key" not in serialized.lower()


def test_task_contracts_define_all_tasks_and_checkpoint_reuse() -> None:
    assert {contract.task for contract in TASK_CONTRACTS} == {
        "asr",
        "facts",
        "embeddings",
        "retrieval",
        "rerank",
        "coaching",
        "presentation",
    }
    assert task_contract("facts").reuse_stage == "C2"
    assert task_contract("coaching").reuse_stage == "C2"
    assert task_contract("presentation").reuse_stage == "C5"
    with pytest.raises(ProviderRegistryError, match="unknown_task"):
        task_contract("unknown")  # type: ignore[arg-type]


def test_config_round_trip_has_stable_digest_and_is_frozen() -> None:
    config = _config()
    parsed = parse_registry_config(config.as_dict())
    assert parsed.as_dict() == config.as_dict()
    assert parsed.digest == config.digest
    with pytest.raises(FrozenInstanceError):
        config.revision = "changed"  # type: ignore[misc]
    with pytest.raises(ProviderRegistryError, match="invalid_registry_config_fields"):
        parse_registry_config({**config.as_dict(), "unexpected": True})
    with pytest.raises(ProviderRegistryError, match="invalid_provider_config_fields"):
        payload = config.as_dict()
        payload["providers"][0]["unexpected"] = True
        parse_registry_config(payload)


def test_provider_models_are_keyed_by_provider_and_model_for_independent_task_routes() -> None:
    first = _provider(provider_id="gemini", model_id="gemini-2.5-flash")
    second = _provider(
        provider_id="gemini",
        model_id="gemini-2.5-pro",
        endpoint="https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent",
    )
    config = RegistryConfig(
        revision="registry-multi-model-v1",
        policy=RegistryPolicy(),
        providers=(first, second),
        routes=(
            _route("facts", provider_id="gemini", model_id="gemini-2.5-flash"),
            _route("coaching", provider_id="gemini", model_id="gemini-2.5-pro"),
        ),
    )
    assert validate_registry_config(config) is config
    assert parse_registry_config(config.as_dict()).as_dict() == config.as_dict()


def test_planned_provider_model_can_be_saved_as_dormant_but_never_dispatched() -> None:
    planned = _provider(
        provider_id="ollama",
        model_id="admin-registered-model",
        endpoint=None,
        credential_ref=None,
        provider_terms_ref=None,
        privacy_ref=None,
        pricing_ref=None,
        free_allowance_ref=None,
        permission_ref=None,
        endpoint_approval_ref=None,
        max_cost_paise=None,
    )
    config = _config(
        task="coaching",
        provider=planned,
        route=_route("coaching", provider_id="ollama", model_id="admin-registered-model"),
    )
    assert validate_registry_config(config) is config
    with pytest.raises(ProviderRegistryError, match="provider_planned"):
        resolve_dispatch(config, _dispatch_request(config, task="coaching"))


def test_zero_cost_asr_resolves_exact_permission_and_endpoint_without_transport() -> None:
    config = _config()
    plan = resolve_dispatch(config, _dispatch_request(config))
    assert plan.provider_id == "elevenlabs"
    assert plan.model_id == "scribe_v2"
    assert plan.endpoint == _ENDPOINTS["elevenlabs"]
    assert plan.max_cost_paise == 0
    assert plan.required_input_stage == "C0"
    assert plan.reuses_checkpoint_stage is None


def test_dispatch_requires_current_config_digest_permission_and_input_stage() -> None:
    config = _config()
    with pytest.raises(ProviderRegistryError, match="digest_or_revision_mismatch"):
        resolve_dispatch(
            config,
            DispatchRequest("asr", config.revision, "a" * 64, "ref:permission:synthetic", "C0"),
        )
    with pytest.raises(ProviderRegistryError, match="permission_reference_mismatch"):
        resolve_dispatch(
            config,
            DispatchRequest("asr", config.revision, config.digest, "ref:permission:other", "C0"),
        )
    with pytest.raises(ProviderRegistryError, match="dispatch_input_stage_mismatch"):
        resolve_dispatch(
            config,
            DispatchRequest(
                "asr", config.revision, config.digest, "ref:permission:synthetic", "C2"
            ),
        )


def test_contract_only_generation_cannot_be_presented_as_implemented_task_adapter() -> None:
    provider = _provider(
        provider_id="gemini",
        model_id="gemini-2.5-flash",
    )
    config = _config(
        task="facts",
        provider=provider,
        route=_route("facts", provider_id="gemini", model_id="gemini-2.5-flash"),
    )
    validate_registry_config(config)
    with pytest.raises(ProviderRegistryError, match="task_adapter_not_implemented"):
        resolve_dispatch(config, _dispatch_request(config, task="facts"))


@pytest.mark.parametrize(
    "field", ["provider_terms_ref", "privacy_ref", "pricing_ref", "free_allowance_ref"]
)
def test_missing_provider_evidence_blocks_dispatch(field: str) -> None:
    provider = _provider(**{field: None})
    config = _config(provider=provider)
    with pytest.raises(ProviderRegistryError, match=f"invalid_{field}"):
        resolve_dispatch(config, _dispatch_request(config))


def test_paid_policy_is_explicit_and_auto_purchase_is_always_forbidden() -> None:
    with pytest.raises(ProviderRegistryError, match="automatic_purchase_forbidden"):
        RegistryPolicy(auto_purchase=True)
    with pytest.raises(ProviderRegistryError, match="owner_approval_reference"):
        RegistryPolicy(allow_paid=True)
    config = _config(provider=_provider(max_cost_paise=1))
    with pytest.raises(ProviderRegistryError, match="paid_dispatch_disabled"):
        resolve_dispatch(config, _dispatch_request(config))


def test_paid_dispatch_requires_policy_and_explicit_pricing_but_not_free_allowance() -> None:
    provider = _provider(max_cost_paise=50_000, free_allowance_ref=None)
    config = _config(
        provider=provider,
        policy=RegistryPolicy(
            allow_paid=True,
            paid_approval_ref="ref:approval:paid-provider",
        ),
    )
    plan = resolve_dispatch(config, _dispatch_request(config))
    assert plan.max_cost_paise == 50_000

    missing_pricing = _provider(max_cost_paise=50_000, free_allowance_ref=None, pricing_ref=None)
    with pytest.raises(ProviderRegistryError, match="invalid_pricing_ref"):
        resolve_dispatch(
            _config(
                provider=missing_pricing,
                policy=RegistryPolicy(
                    allow_paid=True,
                    paid_approval_ref="ref:approval:paid-provider",
                ),
            ),
            _dispatch_request(
                _config(
                    provider=missing_pricing,
                    policy=RegistryPolicy(
                        allow_paid=True,
                        paid_approval_ref="ref:approval:paid-provider",
                    ),
                )
            ),
        )


@pytest.mark.parametrize(
    ("endpoint", "error"),
    [
        ("https://user:password@example.invalid/v1", "credentials_forbidden"),
        ("https://api.elevenlabs.io/v1/speech-to-text?key=secret", "query_forbidden"),
        ("http://10.0.0.1:11434/api", "http_endpoint_must_be_local"),
    ],
)
def test_endpoint_credentials_queries_and_remote_http_are_rejected(
    endpoint: str, error: str
) -> None:
    with pytest.raises(ProviderRegistryError, match=error):
        _provider(endpoint=endpoint)


def test_exact_endpoint_digest_and_catalog_binding_are_required() -> None:
    provider = _provider(endpoint="https://api.elevenlabs.io/v1/other")
    config = _config(provider=provider)
    with pytest.raises(ProviderRegistryError, match="not_exact_catalog_match"):
        validate_registry_config(config)
    provider = _provider()
    object.__setattr__(provider, "endpoint_sha256", "b" * 64)
    config = _config(provider=provider)
    with pytest.raises(ProviderRegistryError, match="endpoint_digest_mismatch"):
        validate_registry_config(config)


def test_local_http_endpoint_requires_explicit_operator_approval() -> None:
    model = ModelCatalogEntry(
        "local-model",
        "http://127.0.0.1:11434/api",
        "implemented",
        (("asr", "implemented"),),
    )
    local = ProviderCatalogEntry(
        "ollama",
        "Local Ollama test catalog",
        "ollama_http",
        "implemented",
        (model,),
    )
    catalog = ProviderCatalog(
        "synthetic-local-v1",
        tuple(
            provider
            for provider in DEFAULT_PROVIDER_CATALOG.providers
            if provider.provider_id != "ollama"
        )
        + (local,),
    )
    provider = _provider(
        provider_id="ollama",
        model_id="local-model",
        endpoint="http://127.0.0.1:11434/api",
        local_endpoint_approval_ref=None,
    )
    config = _config(provider=provider)
    with pytest.raises(ProviderRegistryError, match="local_endpoint_approval_ref"):
        resolve_dispatch(config, _dispatch_request(config), catalog=catalog)
    approved = _provider(
        provider_id="ollama",
        model_id="local-model",
        endpoint="http://127.0.0.1:11434/api",
        local_endpoint_approval_ref="ref:approval:local-endpoint",
    )
    approved_config = _config(provider=approved)
    plan = resolve_dispatch(approved_config, _dispatch_request(approved_config), catalog=catalog)
    assert plan.endpoint == "http://127.0.0.1:11434/api"


def test_raw_credentials_and_url_references_never_parse() -> None:
    payload = _config().as_dict()
    payload["providers"][0]["credential_ref"] = "sk-live-secret-value"
    with pytest.raises(ProviderRegistryError, match="raw_credential"):
        parse_registry_config(payload)
    payload = _config().as_dict()
    payload["providers"][0]["privacy_ref"] = "https://privacy.example/policy"
    with pytest.raises(ProviderRegistryError, match="invalid_privacy_ref"):
        parse_registry_config(payload)


@pytest.mark.parametrize(
    "secret_value",
    [
        "sk_" + "a" * 25,
        "AQ." + "a" * 35,
        "ref:secret:sk_" + "a" * 25,
        "ref:secret:AQ." + "a" * 35,
    ],
)
def test_provider_key_formats_are_rejected_even_inside_reference_prefixes(
    secret_value: str,
) -> None:
    with pytest.raises(ProviderRegistryError, match="raw_credential"):
        _provider(credential_ref=secret_value)


def test_registry_record_limits_are_bounded() -> None:
    payload = _config().as_dict()
    payload["providers"] = [payload["providers"][0]] * 65
    with pytest.raises(ProviderRegistryError, match="configured_providers_too_large"):
        parse_registry_config(payload)
    payload = _config().as_dict()
    payload["routes"] = [payload["routes"][0]] * 65
    with pytest.raises(ProviderRegistryError, match="configured_routes_too_large"):
        parse_registry_config(payload)


def test_typed_protocol_payloads_require_immutable_digest_bound_bytes() -> None:
    config = _config()
    plan = resolve_dispatch(config, _dispatch_request(config))
    payload = b"synthetic request"
    request = ProviderRequest("asr", plan, hashlib.sha256(payload).hexdigest(), payload)
    assert request.payload == payload
    with pytest.raises(ProviderRegistryError, match="immutable_bytes"):
        ProviderRequest("asr", plan, hashlib.sha256(payload).hexdigest(), bytearray(payload))
    with pytest.raises(ProviderRegistryError, match="payload_digest_mismatch"):
        ProviderRequest("asr", plan, "a" * 64, payload)
    response_payload = b"synthetic response"
    response = ProviderResponse(
        "elevenlabs",
        "scribe_v2",
        hashlib.sha256(response_payload).hexdigest(),
        response_payload,
    )
    assert response_payload not in repr(response).encode("utf-8")
