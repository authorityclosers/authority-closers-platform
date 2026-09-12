"""Pure provider catalog and task-routing contracts.

This module deliberately does not read settings, secrets, a database or a network,
and it does not implement an HTTP or process adapter.  The application owns
admin authorization and persistence; a transport broker owns credential injection
and dispatch.  A :class:`DispatchPlan` is only a validated plan for those layers.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from typing import Any, Literal, NoReturn, Protocol, cast
from urllib.parse import urlsplit

from ac_platform.conversation_intelligence.checkpoints import content_hash

type TaskName = Literal[
    "asr",
    "facts",
    "embeddings",
    "retrieval",
    "rerank",
    "coaching",
    "presentation",
]
type CheckpointStage = Literal["C0", "C1", "C2", "C3", "C4", "C5", "C6"]
type ImplementationStatus = Literal["implemented", "planned"]
type TaskSupportStatus = Literal["implemented", "contract_only", "planned", "unavailable"]
type ProviderProtocol = Literal[
    "elevenlabs_https",
    "gemini_https",
    "groq_openai_compatible_https",
    "openai_https",
    "deepseek_https",
    "anthropic_https",
    "openai_compatible_https",
    "ollama_http",
    "vllm_http",
    "llama_cpp_http",
    "sarvam_https",
    "local_process",
]
type DeploymentKind = Literal["hosted", "gateway", "local", "deterministic_tool"]

CATALOG_SCHEMA = "ac.sales_xray.provider_catalog/1"
CONFIG_SCHEMA = "ac.sales_xray.provider_registry_config/1"
REQUEST_SCHEMA = "ac.sales_xray.provider_dispatch_request/1"
PLAN_SCHEMA = "ac.sales_xray.provider_dispatch_plan/1"
TASK_CONTRACT_SCHEMA = "ac.sales_xray.task_contract/1"
PROVIDER_CONFIG_SCHEMA = "ac.sales_xray.provider_config/1"
ROUTE_SCHEMA = "ac.sales_xray.route_config/1"
POLICY_SCHEMA = "ac.sales_xray.registry_policy/1"
RESULT_SCHEMA = "ac.sales_xray.provider_result/1"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_.:/-]{0,255}$")
_SENSITIVE_VALUE = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{12,}|sk_[A-Za-z0-9_-]{20,}|gsk_[A-Za-z0-9_-]{12,}|"
    r"AQ\.[A-Za-z0-9_-]{30,}|AIza[A-Za-z0-9_-]{16,}|xai-[A-Za-z0-9_-]{12,}|"
    r"Bearer\s+\S+|Basic\s+\S+|eyJ[A-Za-z0-9_-]{12,})",
    re.IGNORECASE,
)
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_TASK_NAMES: tuple[TaskName, ...] = (
    "asr",
    "facts",
    "embeddings",
    "retrieval",
    "rerank",
    "coaching",
    "presentation",
)
_CHECKPOINT_STAGES = frozenset({"C0", "C1", "C2", "C3", "C4", "C5", "C6"})
MAX_REGISTRY_ITEMS = 64


class ProviderRegistryError(ValueError):
    """Stable validation code; no provider or caller content is included."""


def _fail(code: str) -> NoReturn:
    raise ProviderRegistryError(code)


def _text(
    value: object,
    field_name: str,
    *,
    allow_none: bool = False,
    allow_spaces: bool = False,
) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        _fail(f"invalid_{field_name}")
    if not allow_spaces and any(character.isspace() for character in value):
        _fail(f"invalid_{field_name}")
    if _SENSITIVE_VALUE.search(value) is not None:
        _fail(f"raw_credential_in_{field_name}")
    return value


def _identifier(value: object, field_name: str) -> str:
    text = _text(value, field_name)
    assert text is not None
    if _IDENTIFIER.fullmatch(text) is None:
        _fail(f"invalid_{field_name}")
    return text


def _ref(value: object, field_name: str, *, required: bool = False) -> str | None:
    if value is None and not required:
        return None
    text = _text(value, field_name)
    assert text is not None
    # Only opaque references cross this boundary.  URLs, query material and
    # credentials belong in their separately approved systems.
    if not text.startswith("ref:") or "://" in text or any(char in text for char in "?#=@"):
        _fail(f"invalid_{field_name}_reference")
    if _IDENTIFIER.fullmatch(text) is None:
        _fail(f"invalid_{field_name}_reference")
    return text


def _digest(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _fail(f"invalid_{field_name}")
    return value


def _nonnegative(value: object, field_name: str, *, allow_none: bool = False) -> int | None:
    if value is None and allow_none:
        return None
    if type(value) is not int or value < 0:
        _fail(f"invalid_{field_name}")
    return value


def _sequence(value: object, field_name: str) -> tuple[Any, ...]:
    if type(value) is not tuple:
        _fail(f"{field_name}_must_be_immutable_tuple")
    if len(value) > MAX_REGISTRY_ITEMS:
        _fail(f"{field_name}_too_large")
    return value


def _mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"invalid_{field_name}")
    return cast(Mapping[str, Any], value)


def _strict_keys(value: Mapping[str, Any], expected: set[str], field_name: str) -> None:
    if set(value) != expected:
        _fail(f"invalid_{field_name}_fields")


def _task(value: object) -> TaskName:
    if value not in _TASK_NAMES:
        _fail("unknown_task")
    return value


def _stage(value: object, field_name: str) -> CheckpointStage:
    if value not in _CHECKPOINT_STAGES:
        _fail(f"invalid_{field_name}")
    return cast(CheckpointStage, value)


def _validate_endpoint_syntax(endpoint: str) -> None:
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        _fail("provider_endpoint_invalid")
    if parsed.username is not None or parsed.password is not None:
        _fail("provider_endpoint_credentials_forbidden")
    if parsed.query or parsed.fragment:
        _fail("provider_endpoint_query_forbidden")
    if parsed.scheme == "http" and parsed.hostname.lower() not in _LOCAL_HOSTS:
        _fail("provider_http_endpoint_must_be_local")


@dataclass(frozen=True, slots=True)
class TaskContract:
    """The task boundary is independent of vendor protocol or model."""

    task: TaskName
    input_stage: CheckpointStage
    reuse_stage: CheckpointStage | None
    profile_required: bool
    schema_revision: str = TASK_CONTRACT_SCHEMA

    def __post_init__(self) -> None:
        _task(self.task)
        _stage(self.input_stage, "input_stage")
        if self.reuse_stage is not None:
            _stage(self.reuse_stage, "reuse_stage")
        if type(self.profile_required) is not bool:
            _fail("invalid_profile_required")
        if self.schema_revision != TASK_CONTRACT_SCHEMA:
            _fail("unsupported_task_contract_schema")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema_revision,
            "task": self.task,
            "input_stage": self.input_stage,
            "reuse_stage": self.reuse_stage,
            "profile_required": self.profile_required,
        }


# These are lineage requirements, not claims about which providers have been
# implemented.  C2 is reusable by facts, retrieval and independent profiles/judges.
TASK_CONTRACTS: tuple[TaskContract, ...] = (
    TaskContract("asr", "C0", None, False),
    TaskContract("facts", "C2", "C2", False),
    TaskContract("embeddings", "C2", "C2", False),
    TaskContract("retrieval", "C2", "C2", False),
    TaskContract("rerank", "C2", "C2", False),
    TaskContract("coaching", "C4", "C2", True),
    TaskContract("presentation", "C5", "C5", True),
)


def task_contract(task: TaskName) -> TaskContract:
    for contract in TASK_CONTRACTS:
        if contract.task == task:
            return contract
    _fail("unknown_task")


@dataclass(frozen=True, slots=True)
class ModelCatalogEntry:
    model_id: str
    endpoint: str | None
    transport_status: ImplementationStatus
    task_support: tuple[tuple[TaskName, TaskSupportStatus], ...] = ()

    def __post_init__(self) -> None:
        _identifier(self.model_id, "model_id")
        if self.endpoint is not None:
            _text(self.endpoint, "endpoint")
            _validate_endpoint_syntax(self.endpoint)
        if self.transport_status not in {"implemented", "planned"}:
            _fail("invalid_transport_status")
        entries = _sequence(self.task_support, "task_support")
        seen: set[str] = set()
        for item in entries:
            if type(item) is not tuple or len(item) != 2:
                _fail("invalid_task_support")
            task_name = _task(item[0])
            status = item[1]
            if status not in {"implemented", "contract_only", "planned", "unavailable"}:
                _fail("invalid_task_support_status")
            if task_name in seen:
                _fail("duplicate_task_support")
            seen.add(task_name)

    def support_for(self, task: TaskName) -> TaskSupportStatus:
        for candidate, status in self.task_support:
            if candidate == task:
                return status
        return "unavailable"

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "endpoint": self.endpoint,
            "transport_status": self.transport_status,
            "readiness": (
                "transport_available"
                if self.transport_status == "implemented"
                else "planned_no_transport"
            ),
            "task_support": [
                {"task": task, "status": status} for task, status in self.task_support
            ],
        }


@dataclass(frozen=True, slots=True)
class ProviderCatalogEntry:
    provider_id: str
    display_name: str
    protocol: ProviderProtocol
    status: ImplementationStatus
    models: tuple[ModelCatalogEntry, ...] = ()
    note: str = ""
    deployment: DeploymentKind = "hosted"

    def __post_init__(self) -> None:
        _identifier(self.provider_id, "provider_id")
        _text(self.display_name, "display_name", allow_spaces=True)
        if self.protocol not in {
            "elevenlabs_https",
            "gemini_https",
            "groq_openai_compatible_https",
            "openai_https",
            "deepseek_https",
            "anthropic_https",
            "openai_compatible_https",
            "ollama_http",
            "vllm_http",
            "llama_cpp_http",
            "sarvam_https",
            "local_process",
        }:
            _fail("invalid_provider_protocol")
        if self.status not in {"implemented", "planned"}:
            _fail("invalid_provider_status")
        if self.deployment not in {"hosted", "gateway", "local", "deterministic_tool"}:
            _fail("invalid_provider_deployment")
        if self.note:
            _text(self.note, "provider_note", allow_none=False, allow_spaces=True)
        entries = _sequence(self.models, "provider_models")
        seen: set[str] = set()
        for model in entries:
            if not isinstance(model, ModelCatalogEntry) or model.model_id in seen:
                _fail("invalid_or_duplicate_provider_model")
            seen.add(model.model_id)
        if self.status == "planned" and entries:
            _fail("planned_provider_cannot_claim_models")

    def model(self, model_id: str) -> ModelCatalogEntry:
        for model in self.models:
            if model.model_id == model_id:
                return model
        _fail("provider_model_not_in_catalog")

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "protocol": self.protocol,
            "status": self.status,
            "readiness": (
                "transport_available" if self.status == "implemented" else "planned_no_transport"
            ),
            "deployment": self.deployment,
            "models": [model.as_dict() for model in self.models],
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class ProviderCatalog:
    revision: str
    providers: tuple[ProviderCatalogEntry, ...]
    schema_revision: str = CATALOG_SCHEMA

    def __post_init__(self) -> None:
        _identifier(self.revision, "catalog_revision")
        if self.schema_revision != CATALOG_SCHEMA:
            _fail("unsupported_catalog_schema")
        entries = _sequence(self.providers, "catalog_providers")
        seen: set[str] = set()
        for provider in entries:
            if not isinstance(provider, ProviderCatalogEntry) or provider.provider_id in seen:
                _fail("invalid_or_duplicate_catalog_provider")
            seen.add(provider.provider_id)

    def provider(self, provider_id: str) -> ProviderCatalogEntry:
        for provider in self.providers:
            if provider.provider_id == provider_id:
                return provider
        _fail("provider_not_in_catalog")

    @property
    def digest(self) -> str:
        return content_hash(self.as_dict())

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema_revision,
            "revision": self.revision,
            "providers": [provider.as_dict() for provider in self.providers],
        }


def _model(
    model_id: str,
    endpoint: str | None,
    *task_support: tuple[TaskName, TaskSupportStatus],
) -> ModelCatalogEntry:
    return ModelCatalogEntry(model_id, endpoint, "implemented", tuple(task_support))


DEFAULT_PROVIDER_CATALOG = ProviderCatalog(
    revision="provider-catalog-20260913-v1",
    providers=(
        ProviderCatalogEntry(
            "local",
            "AC local deterministic tools",
            "local_process",
            "implemented",
            (_model("audioatlas", None),),
            "AudioAtlas C1 is implemented outside the external task adapter catalog.",
            "deterministic_tool",
        ),
        ProviderCatalogEntry(
            "gemini",
            "Google Gemini",
            "gemini_https",
            "implemented",
            (
                _model(
                    "gemini-2.5-flash",
                    "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
                    ("facts", "contract_only"),
                    ("coaching", "contract_only"),
                ),
                _model(
                    "gemini-2.5-pro",
                    "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent",
                    ("facts", "contract_only"),
                    ("coaching", "contract_only"),
                ),
                _model(
                    "gemini-3.8-flash",
                    "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent",
                    ("facts", "contract_only"),
                    ("coaching", "contract_only"),
                ),
                _model(
                    "gemini-3.1-pro-preview",
                    "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-pro-preview:generateContent",
                    ("facts", "contract_only"),
                    ("coaching", "contract_only"),
                ),
            ),
            (
                "Bounded structured generation transport exists; task adapters remain "
                "contract-only here."
            ),
        ),
        ProviderCatalogEntry(
            "groq",
            "Groq",
            "groq_openai_compatible_https",
            "implemented",
            (
                _model(
                    "openai/gpt-oss-120b",
                    "https://api.groq.com/openai/v1/chat/completions",
                    ("facts", "contract_only"),
                    ("coaching", "contract_only"),
                ),
                _model(
                    "llama-3.3-70b-versatile",
                    "https://api.groq.com/openai/v1/chat/completions",
                    ("facts", "contract_only"),
                    ("coaching", "contract_only"),
                ),
            ),
            (
                "Bounded structured generation transport exists; task adapters remain "
                "contract-only here."
            ),
        ),
        ProviderCatalogEntry(
            "elevenlabs",
            "ElevenLabs Scribe",
            "elevenlabs_https",
            "implemented",
            (
                _model(
                    "scribe_v2",
                    "https://api.elevenlabs.io/v1/speech-to-text",
                    ("asr", "implemented"),
                ),
            ),
            (
                "Scribe native transcript normalization is implemented; speaker identity "
                "remains unverified."
            ),
        ),
        ProviderCatalogEntry(
            "openai",
            "OpenAI",
            "openai_https",
            "planned",
            (),
            (
                "Provider option cataloged for a future approved adapter; model and terms "
                "are not asserted."
            ),
        ),
        ProviderCatalogEntry(
            "deepseek",
            "DeepSeek",
            "deepseek_https",
            "planned",
            (),
            (
                "Provider option cataloged for a future approved adapter; model and terms "
                "are not asserted."
            ),
        ),
        ProviderCatalogEntry(
            "anthropic",
            "Anthropic",
            "anthropic_https",
            "planned",
            (),
            (
                "Provider option cataloged for a future approved adapter; model and terms "
                "are not asserted."
            ),
        ),
        ProviderCatalogEntry(
            "openai_compatible_gateway",
            "Approved OpenAI-compatible gateway",
            "openai_compatible_https",
            "planned",
            (),
            (
                "Gateway-specific endpoint, model, privacy and budget evidence are required "
                "before configuration."
            ),
            "gateway",
        ),
        ProviderCatalogEntry(
            "ollama",
            "Local Ollama",
            "ollama_http",
            "planned",
            (),
            (
                "Local endpoint requires explicit operator approval; no arbitrary browser "
                "endpoint is accepted."
            ),
            "local",
        ),
        ProviderCatalogEntry(
            "vllm",
            "Self-hosted vLLM",
            "vllm_http",
            "planned",
            (),
            (
                "Self-hosted endpoint, model digest, retention and operator approval are not "
                "yet configured."
            ),
            "local",
        ),
        ProviderCatalogEntry(
            "llama_cpp",
            "Self-hosted llama.cpp",
            "llama_cpp_http",
            "planned",
            (),
            (
                "Self-hosted endpoint, model digest, retention and operator approval are not "
                "yet configured."
            ),
            "local",
        ),
        ProviderCatalogEntry(
            "sarvam",
            "Sarvam",
            "sarvam_https",
            "planned",
            (),
            (
                "Provider option cataloged for a future approved adapter; model, privacy and "
                "terms are not asserted."
            ),
        ),
    ),
)


def catalog_public_view(
    catalog: ProviderCatalog = DEFAULT_PROVIDER_CATALOG,
) -> list[dict[str, Any]]:
    """Return safe catalog metadata; no credential, pricing or quota values are included."""

    return [provider.as_dict() for provider in catalog.providers]


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """An admin-persisted provider binding containing references, never secret values."""

    provider_id: str
    model_id: str
    endpoint: str | None
    endpoint_sha256: str | None
    credential_ref: str | None
    provider_terms_ref: str | None
    privacy_ref: str | None
    pricing_ref: str | None
    free_allowance_ref: str | None
    permission_ref: str | None
    endpoint_approval_ref: str | None
    local_endpoint_approval_ref: str | None
    max_cost_paise: int | None
    schema_revision: str = PROVIDER_CONFIG_SCHEMA

    def __post_init__(self) -> None:
        _identifier(self.provider_id, "provider_id")
        _identifier(self.model_id, "model_id")
        if self.endpoint is not None:
            _text(self.endpoint, "provider_endpoint")
            _validate_endpoint_syntax(self.endpoint)
        if self.endpoint_sha256 is not None:
            _digest(self.endpoint_sha256, "endpoint_sha256")
        for value, name in (
            (self.credential_ref, "credential_ref"),
            (self.provider_terms_ref, "provider_terms_ref"),
            (self.privacy_ref, "privacy_ref"),
            (self.pricing_ref, "pricing_ref"),
            (self.free_allowance_ref, "free_allowance_ref"),
            (self.permission_ref, "permission_ref"),
            (self.endpoint_approval_ref, "endpoint_approval_ref"),
            (self.local_endpoint_approval_ref, "local_endpoint_approval_ref"),
        ):
            _ref(value, name)
        _nonnegative(self.max_cost_paise, "max_cost_paise", allow_none=True)
        if self.schema_revision != PROVIDER_CONFIG_SCHEMA:
            _fail("unsupported_provider_config_schema")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema_revision,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "endpoint": self.endpoint,
            "endpoint_sha256": self.endpoint_sha256,
            "credential_ref": self.credential_ref,
            "provider_terms_ref": self.provider_terms_ref,
            "privacy_ref": self.privacy_ref,
            "pricing_ref": self.pricing_ref,
            "free_allowance_ref": self.free_allowance_ref,
            "permission_ref": self.permission_ref,
            "endpoint_approval_ref": self.endpoint_approval_ref,
            "local_endpoint_approval_ref": self.local_endpoint_approval_ref,
            "max_cost_paise": self.max_cost_paise,
        }


@dataclass(frozen=True, slots=True)
class RouteConfig:
    task: TaskName
    provider_id: str
    model_id: str
    recipe_revision: str
    profile_revision: str
    prompt_revision: str
    required_input_stage: CheckpointStage
    reuses_checkpoint_stage: CheckpointStage | None
    schema_revision: str = ROUTE_SCHEMA

    def __post_init__(self) -> None:
        task = _task(self.task)
        _identifier(self.provider_id, "provider_id")
        _identifier(self.model_id, "model_id")
        _identifier(self.recipe_revision, "recipe_revision")
        _identifier(self.profile_revision, "profile_revision")
        _identifier(self.prompt_revision, "prompt_revision")
        contract = task_contract(task)
        if self.required_input_stage != contract.input_stage:
            _fail("route_input_stage_does_not_match_task_contract")
        if self.reuses_checkpoint_stage != contract.reuse_stage:
            _fail("route_checkpoint_reuse_does_not_match_task_contract")
        if self.schema_revision != ROUTE_SCHEMA:
            _fail("unsupported_route_schema")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema_revision,
            "task": self.task,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "recipe_revision": self.recipe_revision,
            "profile_revision": self.profile_revision,
            "prompt_revision": self.prompt_revision,
            "required_input_stage": self.required_input_stage,
            "reuses_checkpoint_stage": self.reuses_checkpoint_stage,
        }


@dataclass(frozen=True, slots=True)
class RegistryPolicy:
    allow_paid: bool = False
    auto_purchase: bool = False
    paid_approval_ref: str | None = None
    schema_revision: str = POLICY_SCHEMA

    def __post_init__(self) -> None:
        if type(self.allow_paid) is not bool or type(self.auto_purchase) is not bool:
            _fail("invalid_registry_policy_boolean")
        if self.auto_purchase:
            _fail("automatic_purchase_forbidden")
        _ref(self.paid_approval_ref, "paid_approval_ref")
        if self.allow_paid and self.paid_approval_ref is None:
            _fail("paid_policy_requires_owner_approval_reference")
        if not self.allow_paid and self.paid_approval_ref is not None:
            _fail("paid_approval_without_paid_policy")
        if self.schema_revision != POLICY_SCHEMA:
            _fail("unsupported_registry_policy_schema")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema_revision,
            "allow_paid": self.allow_paid,
            "auto_purchase": self.auto_purchase,
            "paid_approval_ref": self.paid_approval_ref,
        }


@dataclass(frozen=True, slots=True)
class RegistryConfig:
    """Versioned immutable mapping to be persisted by the admin control plane."""

    revision: str
    policy: RegistryPolicy
    providers: tuple[ProviderConfig, ...]
    routes: tuple[RouteConfig, ...]
    schema_revision: str = CONFIG_SCHEMA

    def __post_init__(self) -> None:
        _identifier(self.revision, "config_revision")
        if not isinstance(self.policy, RegistryPolicy):
            _fail("invalid_registry_policy")
        provider_values = _sequence(self.providers, "configured_providers")
        route_values = _sequence(self.routes, "configured_routes")
        seen_providers: set[tuple[str, str]] = set()
        for provider in provider_values:
            if not isinstance(provider, ProviderConfig):
                _fail("invalid_or_duplicate_provider_config")
            provider_key = (provider.provider_id, provider.model_id)
            if provider_key in seen_providers:
                _fail("invalid_or_duplicate_provider_config")
            seen_providers.add(provider_key)
        seen_tasks: set[str] = set()
        for route in route_values:
            if not isinstance(route, RouteConfig) or route.task in seen_tasks:
                _fail("invalid_or_duplicate_route_config")
            if (route.provider_id, route.model_id) not in seen_providers:
                _fail("route_provider_config_missing")
            seen_tasks.add(route.task)
        if self.schema_revision != CONFIG_SCHEMA:
            _fail("unsupported_registry_config_schema")

    @property
    def digest(self) -> str:
        return content_hash(self.as_dict())

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema_revision,
            "revision": self.revision,
            "policy": self.policy.as_dict(),
            "providers": [provider.as_dict() for provider in self.providers],
            "routes": [route.as_dict() for route in self.routes],
        }


def _parse_provider_config(value: object) -> ProviderConfig:
    data = _mapping(value, "provider_config")
    _strict_keys(
        data,
        {
            "schema",
            "provider_id",
            "model_id",
            "endpoint",
            "endpoint_sha256",
            "credential_ref",
            "provider_terms_ref",
            "privacy_ref",
            "pricing_ref",
            "free_allowance_ref",
            "permission_ref",
            "endpoint_approval_ref",
            "local_endpoint_approval_ref",
            "max_cost_paise",
        },
        "provider_config",
    )
    return ProviderConfig(
        provider_id=_identifier(data["provider_id"], "provider_id"),
        model_id=_identifier(data["model_id"], "model_id"),
        endpoint=_text(data["endpoint"], "provider_endpoint", allow_none=True),
        endpoint_sha256=(
            None
            if data["endpoint_sha256"] is None
            else _digest(data["endpoint_sha256"], "endpoint_sha256")
        ),
        credential_ref=_ref(data["credential_ref"], "credential_ref"),
        provider_terms_ref=_ref(data["provider_terms_ref"], "provider_terms_ref"),
        privacy_ref=_ref(data["privacy_ref"], "privacy_ref"),
        pricing_ref=_ref(data["pricing_ref"], "pricing_ref"),
        free_allowance_ref=_ref(data["free_allowance_ref"], "free_allowance_ref"),
        permission_ref=_ref(data["permission_ref"], "permission_ref"),
        endpoint_approval_ref=_ref(data["endpoint_approval_ref"], "endpoint_approval_ref"),
        local_endpoint_approval_ref=_ref(
            data["local_endpoint_approval_ref"], "local_endpoint_approval_ref"
        ),
        max_cost_paise=_nonnegative(data["max_cost_paise"], "max_cost_paise", allow_none=True),
        schema_revision=data["schema"],
    )


def _parse_route_config(value: object) -> RouteConfig:
    data = _mapping(value, "route_config")
    _strict_keys(
        data,
        {
            "schema",
            "task",
            "provider_id",
            "model_id",
            "recipe_revision",
            "profile_revision",
            "prompt_revision",
            "required_input_stage",
            "reuses_checkpoint_stage",
        },
        "route_config",
    )
    task = _task(data["task"])
    reuse_value = data["reuses_checkpoint_stage"]
    return RouteConfig(
        task=task,
        provider_id=_identifier(data["provider_id"], "provider_id"),
        model_id=_identifier(data["model_id"], "model_id"),
        recipe_revision=_identifier(data["recipe_revision"], "recipe_revision"),
        profile_revision=_identifier(data["profile_revision"], "profile_revision"),
        prompt_revision=_identifier(data["prompt_revision"], "prompt_revision"),
        required_input_stage=_stage(data["required_input_stage"], "required_input_stage"),
        reuses_checkpoint_stage=(
            None if reuse_value is None else _stage(reuse_value, "reuses_checkpoint_stage")
        ),
        schema_revision=data["schema"],
    )


def parse_registry_config(
    payload: Mapping[str, Any], *, catalog: ProviderCatalog = DEFAULT_PROVIDER_CATALOG
) -> RegistryConfig:
    """Parse strict admin JSON into an immutable config; this performs no authorization or IO."""

    data = _mapping(payload, "registry_config")
    _strict_keys(data, {"schema", "revision", "policy", "providers", "routes"}, "registry_config")
    policy_data = _mapping(data["policy"], "registry_policy")
    _strict_keys(
        policy_data,
        {"schema", "allow_paid", "auto_purchase", "paid_approval_ref"},
        "registry_policy",
    )
    if (
        type(policy_data["allow_paid"]) is not bool
        or type(policy_data["auto_purchase"]) is not bool
    ):
        _fail("invalid_registry_policy_boolean")
    providers_data = data["providers"]
    routes_data = data["routes"]
    if type(providers_data) is not list or type(routes_data) is not list:
        _fail("registry_collections_must_be_lists")
    config = RegistryConfig(
        revision=_identifier(data["revision"], "config_revision"),
        policy=RegistryPolicy(
            allow_paid=policy_data["allow_paid"],
            auto_purchase=policy_data["auto_purchase"],
            paid_approval_ref=_ref(policy_data["paid_approval_ref"], "paid_approval_ref"),
            schema_revision=policy_data["schema"],
        ),
        providers=tuple(_parse_provider_config(item) for item in providers_data),
        routes=tuple(_parse_route_config(item) for item in routes_data),
        schema_revision=data["schema"],
    )
    validate_registry_config(config, catalog=catalog)
    return config


def validate_registry_config(
    config: RegistryConfig, *, catalog: ProviderCatalog = DEFAULT_PROVIDER_CATALOG
) -> RegistryConfig:
    """Validate catalog identity and routing shape without declaring transport readiness."""

    if not isinstance(config, RegistryConfig):
        _fail("invalid_registry_config")
    for provider_config in config.providers:
        provider = catalog.provider(provider_config.provider_id)
        if provider.status == "planned":
            # A future admin registration can be retained as dormant metadata.
            # It cannot be dispatched until the catalog contains a model and an
            # implemented task adapter.
            continue
        model = provider.model(provider_config.model_id)
        if model.endpoint != provider_config.endpoint:
            _fail("provider_endpoint_not_exact_catalog_match")
        if model.endpoint is None:
            if provider_config.endpoint_sha256 is not None:
                _fail("local_tool_must_not_have_endpoint_digest")
        elif provider_config.endpoint_sha256 != sha256(model.endpoint.encode("utf-8")).hexdigest():
            _fail("provider_endpoint_digest_mismatch")
    for route in config.routes:
        route_provider_config = next(
            (
                item
                for item in config.providers
                if item.provider_id == route.provider_id and item.model_id == route.model_id
            ),
            None,
        )
        if route_provider_config is None:
            _fail("route_provider_config_missing")
        provider = catalog.provider(route.provider_id)
        if route_provider_config.model_id != route.model_id:
            _fail("route_model_does_not_match_provider_config")
        if provider.status == "planned":
            continue
        model = provider.model(route.model_id)
        if model.support_for(route.task) == "unavailable":
            _fail("route_task_not_cataloged")
    return config


@dataclass(frozen=True, slots=True)
class DispatchRequest:
    task: TaskName
    config_revision: str
    config_digest: str
    permission_ref: str
    input_stage: CheckpointStage
    schema_revision: str = REQUEST_SCHEMA

    def __post_init__(self) -> None:
        _task(self.task)
        _identifier(self.config_revision, "config_revision")
        _digest(self.config_digest, "config_digest")
        _ref(self.permission_ref, "permission_ref", required=True)
        _stage(self.input_stage, "input_stage")
        if self.schema_revision != REQUEST_SCHEMA:
            _fail("unsupported_dispatch_request_schema")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DispatchPlan:
    """A pure plan; producing one does not make an HTTP or process call."""

    task: TaskName
    provider_id: str
    model_id: str
    endpoint: str | None
    endpoint_sha256: str | None
    config_revision: str
    config_digest: str
    recipe_revision: str
    profile_revision: str
    prompt_revision: str
    required_input_stage: CheckpointStage
    reuses_checkpoint_stage: CheckpointStage | None
    max_cost_paise: int
    schema_revision: str = PLAN_SCHEMA

    def __post_init__(self) -> None:
        _task(self.task)
        _identifier(self.provider_id, "provider_id")
        _identifier(self.model_id, "model_id")
        _digest(self.config_digest, "config_digest")
        _identifier(self.config_revision, "config_revision")
        _identifier(self.recipe_revision, "recipe_revision")
        _identifier(self.profile_revision, "profile_revision")
        _identifier(self.prompt_revision, "prompt_revision")
        _stage(self.required_input_stage, "required_input_stage")
        if self.reuses_checkpoint_stage is not None:
            _stage(self.reuses_checkpoint_stage, "reuses_checkpoint_stage")
        _nonnegative(self.max_cost_paise, "max_cost_paise")
        if self.schema_revision != PLAN_SCHEMA:
            _fail("unsupported_dispatch_plan_schema")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_dispatch(
    config: RegistryConfig,
    request: DispatchRequest,
    *,
    catalog: ProviderCatalog = DEFAULT_PROVIDER_CATALOG,
) -> DispatchPlan:
    """Resolve an exact route only when all local policy/evidence gates are present."""

    validate_registry_config(config, catalog=catalog)
    if request.config_revision != config.revision or request.config_digest != config.digest:
        _fail("registry_config_digest_or_revision_mismatch")
    route = next((item for item in config.routes if item.task == request.task), None)
    if route is None:
        _fail("task_route_not_configured")
    provider_config = next(
        (
            item
            for item in config.providers
            if item.provider_id == route.provider_id and item.model_id == route.model_id
        ),
        None,
    )
    if provider_config is None:
        _fail("route_provider_config_missing")
    provider = catalog.provider(route.provider_id)
    if provider.status == "planned":
        _fail("provider_planned")
    model = provider.model(route.model_id)
    if model.support_for(route.task) != "implemented":
        _fail("task_adapter_not_implemented")
    if request.input_stage != route.required_input_stage:
        _fail("dispatch_input_stage_mismatch")
    if provider_config.permission_ref != request.permission_ref:
        _fail("dispatch_permission_reference_mismatch")
    required_refs = (
        (provider_config.provider_terms_ref, "provider_terms_ref"),
        (provider_config.privacy_ref, "privacy_ref"),
        (provider_config.pricing_ref, "pricing_ref"),
        (provider_config.free_allowance_ref, "free_allowance_ref"),
        (provider_config.permission_ref, "permission_ref"),
        (provider_config.endpoint_approval_ref, "endpoint_approval_ref"),
    )
    for value, field_name in required_refs:
        _ref(value, field_name, required=True)
    if provider_config.endpoint is None:
        # A process tool has no URL.  External protocols require an exact URL.
        if provider.protocol != "local_process":
            _fail("provider_endpoint_missing")
    else:
        if model.endpoint != provider_config.endpoint:
            _fail("provider_endpoint_not_exact_catalog_match")
        if provider_config.endpoint_sha256 is None:
            _fail("provider_endpoint_digest_missing")
        _validate_endpoint_syntax(provider_config.endpoint)
        if (
            provider_config.endpoint_sha256
            != sha256(provider_config.endpoint.encode("utf-8")).hexdigest()
        ):
            _fail("provider_endpoint_digest_mismatch")
        if urlsplit(provider_config.endpoint).scheme == "http":
            _ref(
                provider_config.local_endpoint_approval_ref,
                "local_endpoint_approval_ref",
                required=True,
            )
    if provider_config.credential_ref is None and provider.protocol != "local_process":
        _fail("credential_reference_missing")
    max_cost = _nonnegative(provider_config.max_cost_paise, "max_cost_paise")
    assert max_cost is not None
    if max_cost > 0 and not config.policy.allow_paid:
        _fail("paid_dispatch_disabled")
    return DispatchPlan(
        task=route.task,
        provider_id=route.provider_id,
        model_id=route.model_id,
        endpoint=provider_config.endpoint,
        endpoint_sha256=provider_config.endpoint_sha256,
        config_revision=config.revision,
        config_digest=config.digest,
        recipe_revision=route.recipe_revision,
        profile_revision=route.profile_revision,
        prompt_revision=route.prompt_revision,
        required_input_stage=route.required_input_stage,
        reuses_checkpoint_stage=route.reuses_checkpoint_stage,
        max_cost_paise=max_cost,
    )


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    """Typed transport input; the implementation of transport lives elsewhere."""

    task: TaskName
    plan: DispatchPlan
    input_sha256: str
    payload: bytes = field(repr=False)

    def __post_init__(self) -> None:
        _task(self.task)
        if self.plan.task != self.task:
            _fail("provider_request_task_mismatch")
        _digest(self.input_sha256, "input_sha256")
        if type(self.payload) is not bytes:
            _fail("provider_payload_must_be_immutable_bytes")
        if hashlib.sha256(self.payload).hexdigest() != self.input_sha256:
            _fail("provider_payload_digest_mismatch")


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    """Typed response envelope; raw bytes are hidden from representations."""

    provider_id: str
    model_id: str
    response_sha256: str
    raw_payload: bytes = field(repr=False)
    schema_revision: str = RESULT_SCHEMA

    def __post_init__(self) -> None:
        _identifier(self.provider_id, "provider_id")
        _identifier(self.model_id, "model_id")
        _digest(self.response_sha256, "response_sha256")
        if type(self.raw_payload) is not bytes:
            _fail("provider_response_must_be_immutable_bytes")
        if hashlib.sha256(self.raw_payload).hexdigest() != self.response_sha256:
            _fail("provider_response_digest_mismatch")
        if self.schema_revision != RESULT_SCHEMA:
            _fail("unsupported_provider_result_schema")


class ProviderTransport(Protocol):
    """Protocol only: no concrete network implementation is supplied here."""

    provider_id: str
    protocol: ProviderProtocol

    def execute(self, request: ProviderRequest) -> ProviderResponse: ...


class TaskAdapter(Protocol):
    """Task-specific schema adapter, separate from provider/model transport."""

    task: TaskName

    def build_request(self, payload: bytes, plan: DispatchPlan) -> ProviderRequest: ...

    def parse_response(
        self, response: ProviderResponse, plan: DispatchPlan
    ) -> Mapping[str, Any]: ...


__all__ = [
    "CATALOG_SCHEMA",
    "CONFIG_SCHEMA",
    "CheckpointStage",
    "DEFAULT_PROVIDER_CATALOG",
    "DeploymentKind",
    "DispatchPlan",
    "DispatchRequest",
    "ImplementationStatus",
    "ModelCatalogEntry",
    "ProviderCatalog",
    "ProviderCatalogEntry",
    "ProviderConfig",
    "ProviderProtocol",
    "ProviderRegistryError",
    "ProviderRequest",
    "ProviderResponse",
    "ProviderTransport",
    "RegistryConfig",
    "RegistryPolicy",
    "RouteConfig",
    "TASK_CONTRACTS",
    "TaskAdapter",
    "TaskContract",
    "TaskName",
    "TaskSupportStatus",
    "catalog_public_view",
    "parse_registry_config",
    "resolve_dispatch",
    "task_contract",
    "validate_registry_config",
]
