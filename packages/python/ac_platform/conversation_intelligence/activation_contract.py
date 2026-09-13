"""Strict, source-independent approval bundle for hosted conversation stages.

This module only validates an operator-supplied approval document. It does not
load secrets, contact a provider, authorize a tenant, or persist an approval.
The application composition must reparse the canonical JSON returned by this
module and compare the resulting digest with its separately approved release
metadata before enabling any runtime.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any, Literal, NoReturn, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    ValidationError,
    field_validator,
    model_validator,
)

from ac_platform.conversation_intelligence.checkpoints import canonical

HOSTED_APPROVAL_SCHEMA: Literal["ac.sales-xray.hosted-approval/1"] = (
    "ac.sales-xray.hosted-approval/1"
)
MAX_APPROVAL_BUNDLE_BYTES = 512 * 1024
MAX_ALLOWANCES = 64
MAX_STAGES = 192

_DIGEST = r"^[0-9a-f]{64}$"
_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_.:/-]{0,255}$")
_REFERENCE = re.compile(r"^ref:[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}$")
_SENSITIVE = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{12,}|sk_[A-Za-z0-9_-]{20,}|gsk_[A-Za-z0-9_-]{12,}|"
    r"AQ\.[A-Za-z0-9_-]{30,}|AIza[A-Za-z0-9_-]{16,}|xai-[A-Za-z0-9_-]{12,}|"
    r"(?:bearer|basic)\s+\S+|(?:api[_-]?key|token|password|secret)\s*[:=])",
    re.IGNORECASE,
)


class ActivationContractError(ValueError):
    """Stable validation code that never includes bundle content."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, populate_by_name=True)


def _validate_reference(value: str) -> str:
    if (
        _REFERENCE.fullmatch(value) is None
        or "://" in value
        or any(character in value for character in "?#=@")
        or _SENSITIVE.search(value) is not None
    ):
        raise ValueError("opaque_reference_invalid")
    return value


def _validate_identifier(value: str) -> str:
    if _IDENTIFIER.fullmatch(value) is None or _SENSITIVE.search(value) is not None:
        raise ValueError("identifier_invalid")
    return value


def _validate_notice(value: str) -> str:
    if not value.strip():
        raise ValueError("privacy_notice_invalid")
    if any(ord(character) < 0x20 and character not in "\r\n\t" for character in value):
        raise ValueError("privacy_notice_invalid")
    if _SENSITIVE.search(value) is not None:
        raise ValueError("privacy_notice_secret")
    return value


class AllowanceApproval(_StrictFrozenModel):
    id: UUID
    tenant_id: UUID
    person_id: UUID
    seconds: StrictInt = Field(ge=1, le=86_400)
    authorization_ref: str = Field(min_length=6, max_length=256)
    granted_by: UUID
    reason: Literal["Approved internal testing allowance"]
    max_recordings: StrictInt = Field(ge=1, le=64)
    max_source_bytes: StrictInt = Field(ge=1, le=134_217_728)
    max_stored_source_bytes: StrictInt = Field(ge=1, le=8_589_934_592)

    _authorization_ref = field_validator("authorization_ref")(_validate_reference)

    @model_validator(mode="after")
    def validate_capacity_bounds(self) -> Self:
        if self.max_source_bytes > self.max_stored_source_bytes:
            raise ValueError("allowance_source_bytes_exceed_stored_cap")
        return self


class StageApproval(_StrictFrozenModel):
    id: UUID
    tenant_id: UUID
    person_id: UUID
    source_sha256: str = Field(pattern=_DIGEST)
    configuration_sha256: str = Field(pattern=_DIGEST)
    stage: Literal["C2", "C4", "C5"]
    provider_id: str = Field(min_length=1, max_length=256)
    model_id: str = Field(min_length=1, max_length=256)
    recipe_revision: str = Field(min_length=1, max_length=256)
    permission_ref: str = Field(min_length=6, max_length=256)
    retention_ref: str = Field(min_length=6, max_length=256)
    professional_gate_ref: str = Field(min_length=6, max_length=256)
    pricing_ref: str = Field(min_length=6, max_length=256)
    provider_terms_ref: str = Field(min_length=6, max_length=256)
    privacy_ref: str = Field(min_length=6, max_length=256)
    credential_ref: str = Field(min_length=6, max_length=256)
    free_allowance_ref: str = Field(min_length=6, max_length=256)
    no_paid_overage_ref: str = Field(min_length=6, max_length=256)
    privacy_revision: str = Field(min_length=1, max_length=128)
    privacy_notice: str = Field(min_length=1, max_length=1_500)
    expires_at_epoch: StrictInt = Field(gt=0)
    max_requests: StrictInt = Field(ge=1, le=64)
    entitlement_seconds: StrictInt | None = Field(default=None, ge=0, le=86_400)
    zero_cost_basis: Literal["verified_free_allowance", "synthetic"]
    price_evidence_sha256: str = Field(pattern=_DIGEST)
    max_source_duration_ms: StrictInt = Field(ge=1, le=14_400_000)
    max_input_bytes: StrictInt = Field(ge=1, le=134_217_728)
    max_completion_tokens: StrictInt = Field(ge=0, le=4_000)
    profile_sha256: str | None = Field(default=None, pattern=_DIGEST)

    _permission_ref = field_validator(
        "permission_ref",
        "retention_ref",
        "professional_gate_ref",
        "pricing_ref",
        "provider_terms_ref",
        "privacy_ref",
        "credential_ref",
        "free_allowance_ref",
        "no_paid_overage_ref",
    )(_validate_reference)
    _provider_id = field_validator("provider_id")(_validate_identifier)
    _model_id = field_validator("model_id")(_validate_identifier)
    _recipe_revision = field_validator("recipe_revision")(_validate_identifier)
    _privacy_revision = field_validator("privacy_revision")(_validate_identifier)
    _privacy_notice = field_validator("privacy_notice")(_validate_notice)

    @model_validator(mode="after")
    def validate_stage_bounds(self) -> Self:
        if self.stage == "C2":
            if self.entitlement_seconds is not None:
                raise ValueError("c2_entitlement_must_be_none")
            if self.max_completion_tokens != 0:
                raise ValueError("c2_completion_tokens_must_be_zero")
            if self.profile_sha256 is not None:
                raise ValueError("c2_profile_must_be_none")
        else:
            if self.entitlement_seconds is None:
                raise ValueError("text_entitlement_required")
            if self.max_completion_tokens < 1:
                raise ValueError("text_completion_tokens_required")
            if self.profile_sha256 is None and self.stage == "C5":
                raise ValueError("c5_profile_required")
            if self.stage == "C4" and self.profile_sha256 is not None:
                raise ValueError("c4_profile_must_be_none")
        return self


class HostedApprovalBundle(_StrictFrozenModel):
    schema_id: Literal["ac.sales-xray.hosted-approval/1"] = Field(alias="schema")
    environment: Literal["staging", "production", "test"]
    deployment_ref: str = Field(min_length=6, max_length=256)
    issued_at_epoch: StrictInt = Field(gt=0)
    expires_at_epoch: StrictInt = Field(gt=0)
    budget_scope_id: UUID
    budget_authorization_ref: str = Field(min_length=6, max_length=256)
    budget_owner_id: UUID
    intake_authorization_ref: str = Field(min_length=6, max_length=256)
    intake_retention_ref: str = Field(min_length=6, max_length=256)
    retention_days: StrictInt = Field(ge=1, le=7)
    max_stored_source_bytes: StrictInt = Field(ge=1, le=34_359_738_368)
    allowances: tuple[AllowanceApproval, ...] = Field(max_length=MAX_ALLOWANCES)
    stages: tuple[StageApproval, ...] = Field(max_length=MAX_STAGES)

    _deployment_ref = field_validator("deployment_ref")(_validate_reference)
    _budget_authorization_ref = field_validator("budget_authorization_ref")(_validate_reference)
    _intake_authorization_ref = field_validator("intake_authorization_ref")(_validate_reference)
    _intake_retention_ref = field_validator("intake_retention_ref")(_validate_reference)

    @model_validator(mode="after")
    def validate_bundle_consistency(self) -> Self:
        if self.expires_at_epoch <= self.issued_at_epoch:
            raise ValueError("approval_bundle_window_invalid")

        approvals: list[AllowanceApproval | StageApproval] = [
            *self.allowances,
            *self.stages,
        ]
        approval_ids = [approval.id for approval in approvals]
        if len(approval_ids) != len(set(approval_ids)):
            raise ValueError("duplicate_approval_id")

        allowance_recipients = [
            (approval.tenant_id, approval.person_id) for approval in self.allowances
        ]
        if len(allowance_recipients) != len(set(allowance_recipients)):
            raise ValueError("duplicate_allowance_recipient")
        if any(
            approval.max_stored_source_bytes > self.max_stored_source_bytes
            for approval in self.allowances
        ):
            raise ValueError("allowance_stored_bytes_exceed_bundle_cap")

        stage_keys = [
            (approval.tenant_id, approval.person_id, approval.source_sha256, approval.stage)
            for approval in self.stages
        ]
        if len(stage_keys) != len(set(stage_keys)):
            raise ValueError("duplicate_stage_scope")

        if any(
            approval.expires_at_epoch <= self.issued_at_epoch
            or approval.expires_at_epoch > self.expires_at_epoch
            for approval in self.stages
        ):
            raise ValueError("stage_expiry_outside_bundle")
        return self

    @property
    def digest(self) -> str:
        """SHA-256 of the canonical JSON content, including the schema."""

        return hashlib.sha256(self.to_json()).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)

    def to_json(self) -> bytes:
        return canonical(self.as_dict())

    def current(self, now: int, environment: str) -> Self:
        if type(now) is not int or now <= 0:
            raise ActivationContractError("approval_now_invalid")
        if environment != self.environment:
            raise ActivationContractError("approval_environment_mismatch")
        if not self.issued_at_epoch <= now < self.expires_at_epoch:
            raise ActivationContractError("approval_bundle_inactive")
        return self


class _DuplicateJSONKey(ValueError):
    pass


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJSONKey
        result[key] = value
    return result


def _reject_json_constant(_: str) -> NoReturn:
    raise ValueError("non-finite JSON number")


def load_hosted_approval_bundle(raw: bytes | str | Mapping[str, Any]) -> HostedApprovalBundle:
    """Load bounded JSON and return only a fully revalidated immutable bundle."""

    try:
        if isinstance(raw, bytes):
            if not 0 < len(raw) <= MAX_APPROVAL_BUNDLE_BYTES:
                raise ActivationContractError("approval_bundle_size_invalid")
            text = raw.decode("utf-8")
        elif isinstance(raw, str):
            encoded = raw.encode("utf-8")
            if not 0 < len(encoded) <= MAX_APPROVAL_BUNDLE_BYTES:
                raise ActivationContractError("approval_bundle_size_invalid")
            text = raw
        elif isinstance(raw, Mapping):
            value = dict(raw)
            encoded = canonical(value)
            if not 0 < len(encoded) <= MAX_APPROVAL_BUNDLE_BYTES:
                raise ActivationContractError("approval_bundle_size_invalid")
            text = encoded.decode("utf-8")
        else:
            raise ActivationContractError("approval_bundle_input_invalid")
        parsed = json.loads(
            text,
            object_pairs_hook=_object_pairs,
            parse_constant=_reject_json_constant,
        )
        if not isinstance(parsed, dict):
            raise ActivationContractError("approval_bundle_object_required")
        encoded = canonical(parsed)
        if not 0 < len(encoded) <= MAX_APPROVAL_BUNDLE_BYTES:
            raise ActivationContractError("approval_bundle_size_invalid")
        return HostedApprovalBundle.model_validate_json(encoded)
    except ActivationContractError:
        raise
    except ValidationError as error:
        # Model validators use stable, content-free codes. Preserve those
        # codes for the composition root while collapsing field errors whose
        # Pydantic context could contain untrusted input values.
        for item in error.errors():
            context = item.get("ctx")
            candidate = context.get("error") if isinstance(context, dict) else None
            if isinstance(candidate, ValueError) and re.fullmatch(
                r"[a-z][a-z0-9_]{0,63}", str(candidate)
            ):
                raise ActivationContractError(str(candidate)) from None
        raise ActivationContractError("hosted_approval_invalid") from None
    except (
        UnicodeError,
        ValueError,
        TypeError,
        OverflowError,
        RecursionError,
    ):
        raise ActivationContractError("hosted_approval_invalid") from None


def load_approval_bundle(raw: bytes | str | Mapping[str, Any]) -> HostedApprovalBundle:
    """Compatibility alias for the application composition root."""

    return load_hosted_approval_bundle(raw)


__all__ = [
    "ActivationContractError",
    "AllowanceApproval",
    "HOSTED_APPROVAL_SCHEMA",
    "HostedApprovalBundle",
    "MAX_APPROVAL_BUNDLE_BYTES",
    "MAX_ALLOWANCES",
    "MAX_STAGES",
    "StageApproval",
    "load_approval_bundle",
    "load_hosted_approval_bundle",
]
