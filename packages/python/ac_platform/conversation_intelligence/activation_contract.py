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
from uuid import UUID, uuid5

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
ACQUISITION_POLICY_SCHEMA: Literal["ac.sales-xray.acquisition-provider-policy/1"] = (
    "ac.sales-xray.acquisition-provider-policy/1"
)
MAX_ACQUISITION_POLICY_STAGES = 3

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


def _validate_optional_reference(value: str | None) -> str | None:
    if value is None:
        return None
    return _validate_reference(value)


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
    # Keep the descriptor schema compatible with existing 128 MiB approval
    # manifests; guest intake and provider execution remain capped at 32 MiB
    # by the admission and provider paths.
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
    free_allowance_ref: str | None = Field(default=None, min_length=6, max_length=256)
    no_paid_overage_ref: str = Field(min_length=6, max_length=256)
    privacy_revision: str = Field(min_length=1, max_length=128)
    privacy_notice: str = Field(min_length=1, max_length=1_500)
    expires_at_epoch: StrictInt = Field(gt=0)
    max_requests: StrictInt = Field(ge=1, le=64)
    entitlement_seconds: StrictInt | None = Field(default=None, ge=0, le=86_400)
    zero_cost_basis: Literal["verified_free_allowance", "synthetic", "paid_pricing_evidence"]
    price_evidence_sha256: str = Field(pattern=_DIGEST)
    max_cost_paise: StrictInt = Field(default=0, ge=0, le=2_147_483_647)
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
        "no_paid_overage_ref",
    )(_validate_reference)
    _free_allowance_ref = field_validator("free_allowance_ref")(_validate_optional_reference)
    _provider_id = field_validator("provider_id")(_validate_identifier)
    _model_id = field_validator("model_id")(_validate_identifier)
    _recipe_revision = field_validator("recipe_revision")(_validate_identifier)
    _privacy_revision = field_validator("privacy_revision")(_validate_identifier)
    _privacy_notice = field_validator("privacy_notice")(_validate_notice)

    @model_validator(mode="after")
    def validate_stage_bounds(self) -> Self:
        if self.zero_cost_basis == "paid_pricing_evidence":
            if self.max_cost_paise <= 0:
                raise ValueError("paid_stage_cost_required")
            if self.free_allowance_ref is not None:
                raise ValueError("paid_stage_free_allowance_forbidden")
        else:
            if self.max_cost_paise != 0:
                raise ValueError("free_stage_cost_must_be_zero")
            if self.free_allowance_ref is None:
                raise ValueError("free_allowance_required")
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
            if self.entitlement_seconds != 0:
                raise ValueError("provider_entitlement_must_be_zero")
            if self.max_completion_tokens < 1:
                raise ValueError("text_completion_tokens_required")
            if self.profile_sha256 is None and self.stage == "C5":
                raise ValueError("c5_profile_required")
            if self.stage == "C4" and self.profile_sha256 is not None:
                raise ValueError("c4_profile_must_be_none")
        return self


class AcquisitionStagePolicy(_StrictFrozenModel):
    """Release-approved provider template for a newly measured source.

    Scope and identity are intentionally absent.  ``AcquisitionProviderPolicy``
    derives them from the server-owned processing actor and exact source hash
    before a stage can enter a plan or reservation.
    """

    stage: Literal["C2", "C4", "C5"]
    configuration_sha256: str = Field(pattern=_DIGEST)
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
    free_allowance_ref: str | None = Field(default=None, min_length=6, max_length=256)
    no_paid_overage_ref: str = Field(min_length=6, max_length=256)
    privacy_revision: str = Field(min_length=1, max_length=128)
    privacy_notice: str = Field(min_length=1, max_length=1_500)
    expires_at_epoch: StrictInt = Field(gt=0)
    max_requests: StrictInt = Field(ge=1, le=64)
    entitlement_seconds: StrictInt | None = Field(default=None, ge=0, le=86_400)
    zero_cost_basis: Literal["verified_free_allowance", "synthetic", "paid_pricing_evidence"]
    price_evidence_sha256: str = Field(pattern=_DIGEST)
    max_cost_paise: StrictInt = Field(default=0, ge=0, le=2_147_483_647)
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
        "no_paid_overage_ref",
    )(_validate_reference)
    _free_allowance_ref = field_validator("free_allowance_ref")(_validate_optional_reference)
    _provider_id = field_validator("provider_id")(_validate_identifier)
    _model_id = field_validator("model_id")(_validate_identifier)
    _recipe_revision = field_validator("recipe_revision")(_validate_identifier)
    _privacy_revision = field_validator("privacy_revision")(_validate_identifier)
    _privacy_notice = field_validator("privacy_notice")(_validate_notice)

    @model_validator(mode="after")
    def validate_stage_bounds(self) -> Self:
        # Keep this in lockstep with StageApproval.  A public template may
        # never widen a bound merely because its source is not known yet.
        if self.zero_cost_basis == "paid_pricing_evidence":
            if self.max_cost_paise <= 0 or self.free_allowance_ref is not None:
                raise ValueError("paid_stage_template_invalid")
        elif self.max_cost_paise != 0 or self.free_allowance_ref is None:
            raise ValueError("free_stage_template_invalid")
        if self.stage == "C2":
            if self.entitlement_seconds is not None:
                raise ValueError("c2_entitlement_must_be_none")
            if self.max_completion_tokens != 0:
                raise ValueError("c2_completion_tokens_must_be_zero")
            if self.profile_sha256 is not None:
                raise ValueError("c2_profile_must_be_none")
        else:
            if self.entitlement_seconds != 0:
                raise ValueError("provider_entitlement_must_be_zero")
            if self.max_completion_tokens < 1:
                raise ValueError("text_completion_tokens_required")
            if self.stage == "C5" and self.profile_sha256 is None:
                raise ValueError("c5_profile_required")
            if self.stage == "C4" and self.profile_sha256 is not None:
                raise ValueError("c4_profile_must_be_none")
        return self


class AcquisitionProviderPolicy(_StrictFrozenModel):
    """An exact processing principal's bounded public acquisition template."""

    schema_id: Literal["ac.sales-xray.acquisition-provider-policy/1"] = Field(alias="schema")
    id: UUID
    tenant_id: UUID
    processing_person_id: UUID
    authorization_ref: str = Field(min_length=6, max_length=256)
    expires_at_epoch: StrictInt = Field(gt=0)
    max_recordings: StrictInt = Field(ge=1, le=64)
    max_source_bytes: StrictInt = Field(ge=1, le=134_217_728)
    max_stored_source_bytes: StrictInt = Field(ge=1, le=8_589_934_592)
    stages: tuple[AcquisitionStagePolicy, ...] = Field(
        min_length=MAX_ACQUISITION_POLICY_STAGES, max_length=MAX_ACQUISITION_POLICY_STAGES
    )

    _authorization_ref = field_validator("authorization_ref")(_validate_reference)

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if self.max_source_bytes > self.max_stored_source_bytes:
            raise ValueError("acquisition_source_bytes_exceed_stored_cap")
        if tuple(item.stage for item in self.stages) != ("C2", "C4", "C5"):
            raise ValueError("acquisition_policy_stages_invalid")
        if len({item.stage for item in self.stages}) != len(self.stages):
            raise ValueError("duplicate_acquisition_policy_stage")
        if self.max_source_bytes > self.stages[0].max_input_bytes:
            raise ValueError("acquisition_source_bytes_exceed_stage_cap")
        if any(item.expires_at_epoch > self.expires_at_epoch for item in self.stages):
            raise ValueError("acquisition_stage_expiry_outside_policy")
        return self

    def matches_actor(self, actor: Any) -> bool:
        """Return true only for the release's processing principal identity."""

        from ac_platform.conversation_intelligence.processing_actor import ProcessingActor

        return (
            isinstance(actor, ProcessingActor)
            and actor.tenant_id == self.tenant_id
            and actor.person_id == self.processing_person_id
        )

    def derive_stage(
        self,
        *,
        tenant_id: UUID,
        person_id: UUID,
        source_sha256: str,
        stage: Literal["C2", "C4", "C5"],
    ) -> StageApproval:
        """Bind a template to one exact source and deterministic approval id."""

        if (
            tenant_id != self.tenant_id
            or person_id != self.processing_person_id
            or re.fullmatch(_DIGEST, source_sha256) is None
        ):
            raise ValueError("acquisition_policy_scope_mismatch")
        template = next((item for item in self.stages if item.stage == stage), None)
        if template is None:
            raise ValueError("acquisition_policy_stage_unavailable")
        # UUID5 makes the approval stable across retries while binding policy,
        # principal and source.  The source hash is the immutable source key;
        # the plan separately retains source revision and the lease binding.
        approval_id = uuid5(
            self.id,
            f"{self.tenant_id}:{self.processing_person_id}:{source_sha256}:{stage}",
        )
        return StageApproval(
            id=approval_id,
            tenant_id=tenant_id,
            person_id=person_id,
            source_sha256=source_sha256,
            **template.model_dump(),
        )

    def provider_references(self) -> tuple[tuple[str, str], ...]:
        return tuple((item.provider_id, item.credential_ref) for item in self.stages)


class HostedApprovalBundle(_StrictFrozenModel):
    schema_id: Literal["ac.sales-xray.hosted-approval/1"] = Field(alias="schema")
    environment: Literal["staging", "production", "test"]
    provider_control_tenant_id: UUID
    deployment_ref: str = Field(min_length=6, max_length=256)
    issued_at_epoch: StrictInt = Field(gt=0)
    expires_at_epoch: StrictInt = Field(gt=0)
    budget_scope_id: UUID
    budget_authorization_ref: str = Field(min_length=6, max_length=256)
    budget_owner_id: UUID
    budget_cap_paise: StrictInt = Field(default=0, ge=0, le=2_147_483_647)
    paid_approval_ref: str | None = Field(default=None, min_length=6, max_length=256)
    intake_authorization_ref: str = Field(min_length=6, max_length=256)
    intake_retention_ref: str = Field(min_length=6, max_length=256)
    retention_days: StrictInt = Field(ge=1, le=7)
    max_stored_source_bytes: StrictInt = Field(ge=1, le=34_359_738_368)
    allowances: tuple[AllowanceApproval, ...] = Field(max_length=MAX_ALLOWANCES)
    stages: tuple[StageApproval, ...] = Field(max_length=MAX_STAGES)
    acquisition_policy: AcquisitionProviderPolicy | None = None

    _deployment_ref = field_validator("deployment_ref")(_validate_reference)
    _budget_authorization_ref = field_validator("budget_authorization_ref")(_validate_reference)
    _paid_approval_ref = field_validator("paid_approval_ref")(_validate_optional_reference)
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

        policy = self.acquisition_policy
        paid_stages = [
            approval
            for approval in self.stages
            if approval.zero_cost_basis == "paid_pricing_evidence"
        ]
        policy_has_paid_stages = policy is not None and any(
            item.zero_cost_basis == "paid_pricing_evidence" for item in policy.stages
        )
        if paid_stages or policy_has_paid_stages:
            if self.budget_cap_paise <= 0:
                raise ValueError("paid_project_cap_required")
            if self.paid_approval_ref is None:
                raise ValueError("paid_approval_reference_required")
            if any(approval.max_cost_paise > self.budget_cap_paise for approval in paid_stages) or (
                policy is not None
                and any(item.max_cost_paise > self.budget_cap_paise for item in policy.stages)
            ):
                raise ValueError("paid_stage_cost_exceeds_project_cap")
        elif self.budget_cap_paise != 0 or self.paid_approval_ref is not None:
            raise ValueError("free_bundle_cannot_bind_paid_budget")

        # One source/stage may have several finite, release-approved routes.
        # The configuration digest is part of the key so an Admin activation
        # can select one of those alternatives without making the stage a
        # wildcard. Existing bundles with one route per stage serialize
        # byte-for-byte as before.
        stage_keys = [
            (
                approval.tenant_id,
                approval.person_id,
                approval.source_sha256,
                approval.stage,
                approval.configuration_sha256,
            )
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
        if policy is not None:
            if (
                policy.expires_at_epoch <= self.issued_at_epoch
                or policy.expires_at_epoch > self.expires_at_epoch
                or policy.max_stored_source_bytes > self.max_stored_source_bytes
            ):
                raise ValueError("acquisition_policy_expiry_or_capacity_invalid")
            if any(item.expires_at_epoch <= self.issued_at_epoch for item in policy.stages):
                raise ValueError("acquisition_stage_expiry_outside_bundle")
            if policy.id in approval_ids:
                raise ValueError("duplicate_approval_id")
        return self

    @property
    def digest(self) -> str:
        """SHA-256 of the canonical JSON content, including the schema."""

        return hashlib.sha256(self.to_json()).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        value = self.model_dump(mode="json", by_alias=True)
        # Keep the canonical bytes (and therefore the digest) of existing /1
        # free approvals unchanged. Paid extensions serialize only when used.
        if self.budget_cap_paise == 0:
            value.pop("budget_cap_paise", None)
        if self.paid_approval_ref is None:
            value.pop("paid_approval_ref", None)
        if self.acquisition_policy is None:
            # Existing /1 artifacts retain byte-for-byte canonical form.
            value.pop("acquisition_policy", None)
        for stage in value["stages"]:
            if stage.get("max_cost_paise") == 0:
                stage.pop("max_cost_paise", None)
        return value

    def to_json(self) -> bytes:
        return canonical(self.as_dict())

    def current(self, now: int, environment: str) -> Self:
        if type(now) is not int or now <= 0:
            raise ActivationContractError("approval_now_invalid")
        if environment != self.environment:
            raise ActivationContractError("approval_environment_mismatch")
        if not self.issued_at_epoch <= now < self.expires_at_epoch:
            raise ActivationContractError("approval_bundle_inactive")
        if self.acquisition_policy is not None and now >= self.acquisition_policy.expires_at_epoch:
            raise ActivationContractError("acquisition_policy_inactive")
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
    "ACQUISITION_POLICY_SCHEMA",
    "AcquisitionProviderPolicy",
    "AcquisitionStagePolicy",
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
