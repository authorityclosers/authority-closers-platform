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
from ac_platform.conversation_intelligence.completion_limits import (
    require_approval_completion_bound,
)

HOSTED_APPROVAL_SCHEMA: Literal["ac.sales-xray.hosted-approval/1"] = (
    "ac.sales-xray.hosted-approval/1"
)
MAX_APPROVAL_BUNDLE_BYTES = 512 * 1024
MAX_ALLOWANCES = 64
MAX_STAGES = 192
MAX_INTERNAL_TESTER_ACCOUNTS = 8
MAX_STAGE_CALL_SUPPLEMENTS = 64
MAX_ACQUISITION_C5_BENCHMARKS = 8
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
_EMAIL = re.compile(r"^[^@\s]{1,254}@[^@\s]{1,254}$")


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


class InternalTesterApproval(_StrictFrozenModel):
    """One exact, release-approved human tester exemption.

    This is deliberately separate from provider and minute allowances.  The
    identity is re-resolved from the current verified Person record before a
    scope is applied; the approval itself only travels in the hash-pinned
    hosted release bundle.
    """

    id: UUID
    email: str = Field(min_length=3, max_length=320)
    authorization_ref: str = Field(min_length=6, max_length=256)
    scopes: tuple[
        Literal[
            "account_minutes",
            "analysis_count",
            "ip_session_issuance",
            "provider_stage_request_count",
        ],
        ...,
    ] = Field(min_length=1, max_length=4)
    reason: Literal["Approved internal tester exemption"]

    _authorization_ref = field_validator("authorization_ref")(_validate_reference)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if _EMAIL.fullmatch(normalized) is None:
            raise ValueError("internal_tester_email_invalid")
        return normalized

    @model_validator(mode="after")
    def validate_scopes(self) -> Self:
        if len(set(self.scopes)) != len(self.scopes):
            raise ValueError("duplicate_internal_tester_scope")
        if tuple(sorted(self.scopes)) != self.scopes:
            raise ValueError("internal_tester_scopes_unordered")
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
    max_completion_tokens: StrictInt = Field(ge=0, le=8_000)
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
        require_approval_completion_bound(
            self.provider_id,
            self.model_id,
            self.stage,
            self.max_completion_tokens,
            self.zero_cost_basis,
            self.max_cost_paise,
        )
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


class StageCallSupplement(_StrictFrozenModel):
    """One exact, source-scoped addition to an acquisition stage call cap.

    Supplements are included in the release-pinned approval digest. They do
    not mutate the acquisition policy, approval identifier, or historical
    reservation counter. This v1 contract intentionally supports only the
    bounded C5 test lane and has hard ceilings independent of operator input.
    """

    id: UUID
    authorization_ref: str = Field(min_length=6, max_length=256)
    base_approval_id: UUID
    tenant_id: UUID
    processing_person_id: UUID
    owner_person_id: UUID
    source_sha256: str = Field(pattern=_DIGEST)
    configuration_sha256: str = Field(pattern=_DIGEST)
    stage: Literal["C5"]
    recipe_revision: str = Field(min_length=1, max_length=256)
    coaching_prompt_revision: Literal["coaching-v4"]
    report_language: Literal["en", "hi-Deva+en", "mr-Deva+en"]
    processing_plan_sha256: str = Field(pattern=_DIGEST)
    prepared_input_sha256: str = Field(pattern=_DIGEST)
    issued_at_epoch: StrictInt = Field(gt=0)
    expires_at_epoch: StrictInt = Field(gt=0)
    max_additional_requests: StrictInt = Field(ge=1, le=2)
    max_cost_per_request_paise: StrictInt = Field(ge=1, le=2_200)
    max_aggregate_cost_paise: StrictInt = Field(ge=1, le=4_400)

    _authorization_ref = field_validator("authorization_ref")(_validate_reference)
    _recipe_revision = field_validator("recipe_revision")(_validate_identifier)

    @model_validator(mode="after")
    def validate_supplement_bounds(self) -> Self:
        if self.expires_at_epoch <= self.issued_at_epoch:
            raise ValueError("stage_supplement_window_invalid")
        if self.max_aggregate_cost_paise > (
            self.max_additional_requests * self.max_cost_per_request_paise
        ):
            raise ValueError("stage_supplement_aggregate_exceeds_request_cap")
        return self


class AcquisitionC5BenchmarkApproval(_StrictFrozenModel):
    """One human-authorized, exact-source acquisition C5 benchmark."""

    id: UUID
    authorization_ref: str = Field(min_length=6, max_length=256)
    tenant_id: UUID
    owner_person_id: UUID
    submission_id: UUID
    recording_id: UUID
    processing_person_id: UUID
    processing_lease_id: UUID
    usage_id: UUID
    source_sha256: str = Field(pattern=_DIGEST)
    source_revision: StrictInt = Field(ge=1)
    generation: StrictInt = Field(ge=1)
    stage_approval_id: UUID
    configuration_sha256: str = Field(pattern=_DIGEST)
    analysis_settings_revision: StrictInt = Field(ge=1)
    analysis_settings_sha256: str = Field(pattern=_DIGEST)
    coaching_prompt_revision: Literal["coaching-v5"]
    report_language: Literal["en", "hi-Deva+en", "mr-Deva+en"]
    output_profile: Literal["detailed"]
    profile_sha256: str = Field(pattern=_DIGEST)
    issued_at_epoch: StrictInt = Field(gt=0)
    expires_at_epoch: StrictInt = Field(gt=0)
    max_requests: Literal[1] = 1
    max_cost_paise: StrictInt = Field(ge=1, le=2_200)
    max_completion_tokens: StrictInt = Field(ge=256, le=8_000)

    _authorization_ref = field_validator("authorization_ref")(_validate_reference)

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        if self.expires_at_epoch <= self.issued_at_epoch:
            raise ValueError("acquisition_c5_benchmark_window_invalid")
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
    max_completion_tokens: StrictInt = Field(ge=0, le=8_000)
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
        require_approval_completion_bound(
            self.provider_id,
            self.model_id,
            self.stage,
            self.max_completion_tokens,
            self.zero_cost_basis,
            self.max_cost_paise,
        )
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


class AcquisitionProviderProfile(_StrictFrozenModel):
    """One finite, release-approved route set for future source processing."""

    schema_id: Literal["ac.sales-xray.acquisition-provider-profile/1"] = Field(
        default="ac.sales-xray.acquisition-provider-profile/1", alias="schema"
    )
    profile_id: str = Field(min_length=1, max_length=128)
    stages: tuple[AcquisitionStagePolicy, ...] = Field(
        min_length=MAX_ACQUISITION_POLICY_STAGES, max_length=MAX_ACQUISITION_POLICY_STAGES
    )

    _profile_id = field_validator("profile_id")(_validate_identifier)

    @model_validator(mode="after")
    def validate_profile(self) -> Self:
        if tuple(item.stage for item in self.stages) != ("C2", "C4", "C5"):
            raise ValueError("acquisition_profile_stages_invalid")
        if len({item.stage for item in self.stages}) != len(self.stages):
            raise ValueError("duplicate_acquisition_profile_stage")
        if len({item.configuration_sha256 for item in self.stages}) != 1:
            raise ValueError("acquisition_profile_configuration_mismatch")
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
    profiles: tuple[AcquisitionProviderProfile, ...] = Field(default=(), max_length=8)

    _authorization_ref = field_validator("authorization_ref")(_validate_reference)

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if self.max_source_bytes > self.max_stored_source_bytes:
            raise ValueError("acquisition_source_bytes_exceed_stored_cap")
        if tuple(item.stage for item in self.stages) != ("C2", "C4", "C5"):
            raise ValueError("acquisition_policy_stages_invalid")
        if len({item.stage for item in self.stages}) != len(self.stages):
            raise ValueError("duplicate_acquisition_policy_stage")
        profile_ids = [profile.profile_id for profile in self.profiles]
        if len(profile_ids) != len(set(profile_ids)):
            raise ValueError("duplicate_acquisition_profile_id")
        profile_digests = [
            next(iter({item.configuration_sha256 for item in profile.stages}))
            for profile in self.profiles
        ]
        base_digests = {item.configuration_sha256 for item in self.stages}
        if len(set(profile_digests)) != len(profile_digests) or any(
            digest in base_digests for digest in profile_digests
        ):
            raise ValueError("duplicate_acquisition_profile_configuration")
        if any(
            self.max_source_bytes > item.max_input_bytes
            for stages in self.stage_sets()
            for item in stages
        ):
            raise ValueError("acquisition_source_bytes_exceed_stage_cap")
        if any(
            item.expires_at_epoch > self.expires_at_epoch
            for stages in self.stage_sets()
            for item in stages
        ):
            raise ValueError("acquisition_stage_expiry_outside_policy")
        return self

    def stage_sets(self) -> tuple[tuple[AcquisitionStagePolicy, ...], ...]:
        """Return the default route followed by each finite alternative."""

        return (self.stages, *(profile.stages for profile in self.profiles))

    def configuration_digests(self) -> tuple[str, ...]:
        """Return configuration identities in stable release order."""

        return tuple(
            dict.fromkeys(
                item.configuration_sha256 for stages in self.stage_sets() for item in stages
            )
        )

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
        configuration_sha256: str | None = None,
    ) -> StageApproval:
        """Bind a template to one exact source and deterministic approval id."""

        if (
            tenant_id != self.tenant_id
            or person_id != self.processing_person_id
            or re.fullmatch(_DIGEST, source_sha256) is None
        ):
            raise ValueError("acquisition_policy_scope_mismatch")
        candidates = [
            item
            for stages in self.stage_sets()
            for item in stages
            if item.stage == stage
            and (configuration_sha256 is None or item.configuration_sha256 == configuration_sha256)
        ]
        if len(candidates) != 1:
            raise ValueError("acquisition_policy_configuration_required")
        template = candidates[0]
        # UUID5 makes the approval stable across retries while binding policy,
        # principal and source.  The source hash is the immutable source key;
        # the plan separately retains source revision and the lease binding.
        # Preserve the /1 identifier for the default route. Alternatives need
        # a disjoint id so two pinned models cannot share an authorization ref.
        identity = f"{self.tenant_id}:{self.processing_person_id}:{source_sha256}:{stage}"
        base_template = next(item for item in self.stages if item.stage == stage)
        if template is not base_template:
            identity += f":{template.configuration_sha256}"
        approval_id = uuid5(self.id, identity)
        return StageApproval(
            id=approval_id,
            tenant_id=tenant_id,
            person_id=person_id,
            source_sha256=source_sha256,
            **template.model_dump(),
        )

    def provider_references(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            dict.fromkeys(
                (item.provider_id, item.credential_ref)
                for stages in self.stage_sets()
                for item in stages
            )
        )


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
    internal_tester_accounts: tuple[InternalTesterApproval, ...] = Field(
        default=(), max_length=MAX_INTERNAL_TESTER_ACCOUNTS
    )
    acquisition_policy: AcquisitionProviderPolicy | None = None
    stage_call_supplements: tuple[StageCallSupplement, ...] = Field(
        default=(), max_length=MAX_STAGE_CALL_SUPPLEMENTS
    )
    acquisition_c5_benchmarks: tuple[AcquisitionC5BenchmarkApproval, ...] = Field(
        default=(), max_length=MAX_ACQUISITION_C5_BENCHMARKS
    )

    _deployment_ref = field_validator("deployment_ref")(_validate_reference)
    _budget_authorization_ref = field_validator("budget_authorization_ref")(_validate_reference)
    _paid_approval_ref = field_validator("paid_approval_ref")(_validate_optional_reference)
    _intake_authorization_ref = field_validator("intake_authorization_ref")(_validate_reference)
    _intake_retention_ref = field_validator("intake_retention_ref")(_validate_reference)

    @model_validator(mode="after")
    def validate_bundle_consistency(self) -> Self:
        if self.expires_at_epoch <= self.issued_at_epoch:
            raise ValueError("approval_bundle_window_invalid")
        if self.stage_call_supplements and self.environment == "production":
            raise ValueError("stage_supplements_not_approved_for_production")

        approvals: list[AllowanceApproval | StageApproval] = [
            *self.allowances,
            *self.stages,
        ]
        approval_ids = [approval.id for approval in approvals]
        if len(approval_ids) != len(set(approval_ids)):
            raise ValueError("duplicate_approval_id")

        tester_ids = [approval.id for approval in self.internal_tester_accounts]
        if len(tester_ids) != len(set(tester_ids)) or set(tester_ids) & set(approval_ids):
            raise ValueError("duplicate_approval_id")
        tester_emails = [approval.email for approval in self.internal_tester_accounts]
        if len(tester_emails) != len(set(tester_emails)):
            raise ValueError("duplicate_internal_tester_email")
        supplement_ids = [item.id for item in self.stage_call_supplements]
        if len(supplement_ids) != len(set(supplement_ids)) or set(supplement_ids) & set(
            approval_ids + tester_ids
        ):
            raise ValueError("duplicate_approval_id")
        supplement_scopes = [
            (
                item.base_approval_id,
                item.owner_person_id,
                item.source_sha256,
                item.configuration_sha256,
                item.stage,
                item.processing_plan_sha256,
            )
            for item in self.stage_call_supplements
        ]
        if len(supplement_scopes) != len(set(supplement_scopes)):
            raise ValueError("duplicate_stage_supplement_scope")

        benchmarks = self.acquisition_c5_benchmarks
        benchmark_ids = [item.id for item in benchmarks]
        if len(benchmark_ids) != len(set(benchmark_ids)) or set(benchmark_ids) & set(
            approval_ids + tester_ids + supplement_ids
        ):
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
            item.zero_cost_basis == "paid_pricing_evidence"
            for stages in policy.stage_sets()
            for item in stages
        )
        if paid_stages or policy_has_paid_stages:
            if self.budget_cap_paise <= 0:
                raise ValueError("paid_project_cap_required")
            if self.paid_approval_ref is None:
                raise ValueError("paid_approval_reference_required")
            if any(approval.max_cost_paise > self.budget_cap_paise for approval in paid_stages) or (
                policy is not None
                and any(
                    item.max_cost_paise > self.budget_cap_paise
                    for stages in policy.stage_sets()
                    for item in stages
                )
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
            if any(
                item.expires_at_epoch <= self.issued_at_epoch
                for stages in policy.stage_sets()
                for item in stages
            ):
                raise ValueError("acquisition_stage_expiry_outside_bundle")
            if policy.id in approval_ids:
                raise ValueError("duplicate_approval_id")
        elif self.stage_call_supplements:
            raise ValueError("stage_supplement_requires_acquisition_policy")
        if policy is not None:
            for supplement in self.stage_call_supplements:
                if (
                    supplement.tenant_id != policy.tenant_id
                    or supplement.processing_person_id != policy.processing_person_id
                    or supplement.issued_at_epoch < self.issued_at_epoch
                    or supplement.expires_at_epoch
                    > min(self.expires_at_epoch, policy.expires_at_epoch)
                ):
                    raise ValueError("stage_supplement_scope_or_expiry_invalid")
                try:
                    base = policy.derive_stage(
                        tenant_id=supplement.tenant_id,
                        person_id=supplement.processing_person_id,
                        source_sha256=supplement.source_sha256,
                        stage=supplement.stage,
                        configuration_sha256=supplement.configuration_sha256,
                    )
                except ValueError:
                    raise ValueError("stage_supplement_base_approval_invalid") from None
                if (
                    base.id != supplement.base_approval_id
                    or base.recipe_revision != supplement.recipe_revision
                    or base.expires_at_epoch < supplement.expires_at_epoch
                    or base.stage != "C5"
                    or base.zero_cost_basis != "paid_pricing_evidence"
                    or supplement.max_cost_per_request_paise > base.max_cost_paise
                ):
                    raise ValueError("stage_supplement_base_approval_invalid")
        elif benchmarks:
            raise ValueError("acquisition_c5_benchmark_requires_acquisition_policy")
        for benchmark in benchmarks:
            candidates = tuple(
                item for item in self.stages if item.id == benchmark.stage_approval_id
            )
            if len(candidates) != 1:
                raise ValueError("acquisition_c5_benchmark_stage_approval_missing")
            stage = candidates[0]
            if (
                self.environment not in {"staging", "test"}
                or policy is None
                or benchmark.tenant_id != policy.tenant_id
                or benchmark.processing_person_id != policy.processing_person_id
                or stage.tenant_id != benchmark.tenant_id
                or stage.person_id != benchmark.processing_person_id
                or stage.source_sha256 != benchmark.source_sha256
                or stage.stage != "C5"
                or stage.provider_id != "openai"
                or stage.model_id != "gpt-6-luna"
                or stage.configuration_sha256 != benchmark.configuration_sha256
                or stage.expires_at_epoch < benchmark.expires_at_epoch
                or stage.max_requests != 1
                or stage.max_cost_paise != benchmark.max_cost_paise
                or stage.max_completion_tokens != benchmark.max_completion_tokens
                or stage.profile_sha256 != benchmark.profile_sha256
                or stage.zero_cost_basis != "paid_pricing_evidence"
                or benchmark.expires_at_epoch > min(self.expires_at_epoch, policy.expires_at_epoch)
            ):
                raise ValueError("acquisition_c5_benchmark_stage_scope_invalid")
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
        elif not self.acquisition_policy.profiles:
            # The optional field is omitted when empty so an existing /1
            # bundle keeps its exact canonical bytes and digest.
            value["acquisition_policy"].pop("profiles", None)
        if not self.internal_tester_accounts:
            # Existing /1 artifacts retain byte-for-byte canonical form until
            # an operator explicitly issues a tester exemption approval.
            value.pop("internal_tester_accounts", None)
        if not self.stage_call_supplements:
            # Keep the canonical bytes and digest of historical /1 bundles.
            value.pop("stage_call_supplements", None)
        if not self.acquisition_c5_benchmarks:
            # Do not change canonical bytes for deployments without this
            # explicitly issued one-source benchmark grant.
            value.pop("acquisition_c5_benchmarks", None)
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
    "AcquisitionC5BenchmarkApproval",
    "AcquisitionProviderPolicy",
    "AcquisitionProviderProfile",
    "AcquisitionStagePolicy",
    "AllowanceApproval",
    "HOSTED_APPROVAL_SCHEMA",
    "HostedApprovalBundle",
    "InternalTesterApproval",
    "MAX_INTERNAL_TESTER_ACCOUNTS",
    "MAX_APPROVAL_BUNDLE_BYTES",
    "MAX_ALLOWANCES",
    "MAX_ACQUISITION_C5_BENCHMARKS",
    "MAX_STAGES",
    "StageApproval",
    "StageCallSupplement",
    "MAX_STAGE_CALL_SUPPLEMENTS",
    "load_approval_bundle",
    "load_hosted_approval_bundle",
]
