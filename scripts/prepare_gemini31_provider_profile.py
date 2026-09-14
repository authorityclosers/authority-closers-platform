"""Prepare a reviewed, offline Gemini 3.1 Pro C4 profile candidate.

This command reads an existing source-validated registry and pinned approval,
then writes a new registry revision and a candidate approval bundle containing
one finite profile: ElevenLabs C2, Gemini 3.1 Pro C4, and Gemini 3.8 Flash C5.
It never reads credentials, calls a provider, writes a database, or activates
the candidate. The output approval is explicitly pending a new owner approval.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import replace
from pathlib import Path
from typing import Any

from ac_platform.conversation_intelligence.activation_contract import (
    AcquisitionProviderProfile,
    HostedApprovalBundle,
)
from ac_platform.conversation_intelligence.provider_registry import (
    RegistryConfig,
    parse_registry_config,
)

PROVIDER_ID = "gemini"
PRO_MODEL_ID = "gemini-3.1-pro-preview"
FLASH_MODEL_ID = "gemini-3.8-flash"
PRO_ENDPOINT = (
    f"https://generativelanguage.googleapis.com/v1beta/models/{PRO_MODEL_ID}:generateContent"
)
PRO_PRICING_REF = "ref:pricing/gemini-31-pro-preview-20260914"
PRO_INPUT_USD_PER_MILLION = 2
PRO_OUTPUT_USD_PER_MILLION = 12
PLANNING_USD_TO_INR = 100
# The native adapter currently admits facts prompts when
# ceil(input_bytes / 3) + output_tokens + 128 <= 8,000. Keep that transport
# gate as the actual byte limit, but use one token per UTF-8 byte for the
# financial bound below. The latter is deliberately conservative accounting,
# not a claim about the provider tokenizer.
PRO_C4_MAX_OUTPUT_TOKENS = 1_400
PRO_C4_PROMPT_LIMIT_TOKENS = 8_000
PROMPT_OVERHEAD_TOKENS = 128
PRO_C4_MAX_INPUT_BYTES = (
    PRO_C4_PROMPT_LIMIT_TOKENS - PRO_C4_MAX_OUTPUT_TOKENS - PROMPT_OVERHEAD_TOKENS
) * 3
PRO_C4_SAFE_BILLING_INPUT_TOKENS = PRO_C4_MAX_INPUT_BYTES
PRO_C4_MAX_COST_PAISE = 700


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pro_c4_cost_bound_paise() -> int:
    """Return the conservative rounded-up Pro C4 bound at the source caps."""

    numerator = (
        PRO_C4_SAFE_BILLING_INPUT_TOKENS + PROMPT_OVERHEAD_TOKENS
    ) * PRO_INPUT_USD_PER_MILLION + PRO_C4_MAX_OUTPUT_TOKENS * PRO_OUTPUT_USD_PER_MILLION
    exact_paise = numerator * PLANNING_USD_TO_INR * 100 / 1_000_000
    return math.ceil(exact_paise)


def build_alternate_registry(
    base: RegistryConfig,
    *,
    revision: str,
    pricing_ref: str = PRO_PRICING_REF,
    max_cost_paise: int = PRO_C4_MAX_COST_PAISE,
) -> RegistryConfig:
    """Add one exact Pro provider binding and route only the facts task to it."""

    if any(
        item.provider_id == PROVIDER_ID and item.model_id == PRO_MODEL_ID for item in base.providers
    ):
        raise ValueError("gemini31_provider_already_present")
    flash = next(
        (
            item
            for item in base.providers
            if item.provider_id == PROVIDER_ID and item.model_id == FLASH_MODEL_ID
        ),
        None,
    )
    if flash is None:
        raise ValueError("gemini38_provider_required")
    if not any(
        route.provider_id == PROVIDER_ID and route.model_id == FLASH_MODEL_ID
        for route in base.routes
    ):
        raise ValueError("gemini38_route_required")
    pro = replace(
        flash,
        model_id=PRO_MODEL_ID,
        endpoint=PRO_ENDPOINT,
        endpoint_sha256=hashlib.sha256(PRO_ENDPOINT.encode("utf-8")).hexdigest(),
        pricing_ref=pricing_ref,
        max_cost_paise=max_cost_paise,
    )
    routes = tuple(
        replace(route, model_id=PRO_MODEL_ID)
        if route.task == "facts"
        and route.provider_id == PROVIDER_ID
        and route.model_id == FLASH_MODEL_ID
        else route
        for route in base.routes
    )
    return replace(base, revision=revision, providers=(*base.providers, pro), routes=routes)


def build_alternate_profile(
    bundle: HostedApprovalBundle,
    *,
    configuration_sha256: str,
    pricing_evidence_sha256: str,
    pricing_ref: str = PRO_PRICING_REF,
    profile_id: str = "gemini-31-pro-c4-flash-c5",
    max_cost_paise: int = PRO_C4_MAX_COST_PAISE,
) -> AcquisitionProviderProfile:
    """Copy the approved policy bounds and change only the pinned C4 route."""

    policy = bundle.acquisition_policy
    if policy is None or policy.profiles:
        raise ValueError("single_unprofiled_acquisition_policy_required")
    if tuple(item.stage for item in policy.stages) != ("C2", "C4", "C5"):
        raise ValueError("acquisition_policy_stages_invalid")
    stages = tuple(
        item.model_copy(
            update={
                "configuration_sha256": configuration_sha256,
                "pricing_ref": pricing_ref if item.stage == "C4" else item.pricing_ref,
                "price_evidence_sha256": (
                    pricing_evidence_sha256 if item.stage == "C4" else item.price_evidence_sha256
                ),
                "provider_id": PROVIDER_ID if item.stage == "C4" else item.provider_id,
                "model_id": PRO_MODEL_ID if item.stage == "C4" else item.model_id,
                "max_completion_tokens": (
                    PRO_C4_MAX_OUTPUT_TOKENS if item.stage == "C4" else item.max_completion_tokens
                ),
                "max_input_bytes": (
                    PRO_C4_MAX_INPUT_BYTES if item.stage == "C4" else item.max_input_bytes
                ),
                "max_cost_paise": max_cost_paise if item.stage == "C4" else item.max_cost_paise,
            }
        )
        for item in policy.stages
    )
    return AcquisitionProviderProfile(profile_id=profile_id, stages=stages)


def build_candidate_bundle(
    bundle: HostedApprovalBundle, profile: AcquisitionProviderProfile
) -> HostedApprovalBundle:
    policy = bundle.acquisition_policy
    if policy is None or policy.profiles:
        raise ValueError("single_unprofiled_acquisition_policy_required")
    return bundle.model_copy(
        update={
            "acquisition_policy": policy.model_copy(update={"profiles": (profile,)}),
        }
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=("staging", "production"), required=True)
    parser.add_argument("--base-registry-config", type=Path, required=True)
    parser.add_argument("--pinned-approval", type=Path, required=True)
    parser.add_argument("--pricing-evidence", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--release-sha", required=True)
    return parser


def _load_pricing(path: Path) -> tuple[str, str]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("pricing_evidence_object_required")
    if value.get("provider_id") != PROVIDER_ID or value.get("model_id") != PRO_MODEL_ID:
        raise ValueError("pricing_evidence_model_mismatch")
    if value.get("pricing_ref") != PRO_PRICING_REF:
        raise ValueError("pricing_evidence_reference_mismatch")
    if value.get("input_usd_per_million") != PRO_INPUT_USD_PER_MILLION:
        raise ValueError("pricing_evidence_input_rate_mismatch")
    if value.get("output_usd_per_million") != PRO_OUTPUT_USD_PER_MILLION:
        raise ValueError("pricing_evidence_output_rate_mismatch")
    return PRO_PRICING_REF, sha256_file(path)


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    base_registry_raw = json.loads(args.base_registry_config.read_text(encoding="utf-8"))
    base_registry = parse_registry_config(base_registry_raw)
    bundle = HostedApprovalBundle.model_validate_json(args.pinned_approval.read_bytes())
    policy = bundle.acquisition_policy
    if policy is None:
        raise ValueError("pinned_acquisition_policy_required")
    if policy.stages[0].configuration_sha256 != base_registry.digest:
        raise ValueError("base_registry_digest_not_pinned")
    pricing_ref, pricing_sha = _load_pricing(args.pricing_evidence)
    if pro_c4_cost_bound_paise() > PRO_C4_MAX_COST_PAISE:
        raise ValueError("pro_c4_cost_bound_exceeds_candidate_cap")
    revision = f"{base_registry.revision}-gemini31-c4"
    alternate_registry = build_alternate_registry(
        base_registry,
        revision=revision,
        pricing_ref=pricing_ref,
    )
    profile = build_alternate_profile(
        bundle,
        configuration_sha256=alternate_registry.digest,
        pricing_evidence_sha256=pricing_sha,
        pricing_ref=pricing_ref,
    )
    candidate_bundle = build_candidate_bundle(bundle, profile)
    projected_cost = (
        policy.stages[0].max_cost_paise
        + profile.stages[1].max_cost_paise * profile.stages[1].max_requests
        + profile.stages[2].max_cost_paise
    )
    if projected_cost > bundle.budget_cap_paise:
        raise ValueError("candidate_plan_exceeds_existing_budget")
    output_root = args.output_root
    output_root.mkdir(parents=True, exist_ok=False)
    registry_path = output_root / f"registry-config-{args.environment}-gemini31-c4.json"
    approval_path = output_root / f"candidate-approval-{args.environment}-gemini31-c4.json"
    profile_path = output_root / f"profile-{args.environment}-gemini31-c4.json"
    registry_path.write_text(
        json.dumps(alternate_registry.as_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    approval_path.write_bytes(candidate_bundle.to_json())
    profile_path.write_text(
        json.dumps(profile.model_dump(mode="json", by_alias=True), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schema": "ac.sales_xray.alternate_provider_profile_manifest/1",
        "status": "candidate_pending_owner_approval",
        "environment": args.environment,
        "release_sha": args.release_sha,
        "base": {
            "registry_path": str(args.base_registry_config.resolve()),
            "registry_sha256": sha256_file(args.base_registry_config),
            "registry_configuration_sha256": base_registry.digest,
            "approval_path": str(args.pinned_approval.resolve()),
            "approval_sha256": sha256_file(args.pinned_approval),
            "approval_digest": bundle.digest,
            "budget_scope_id": str(bundle.budget_scope_id),
            "budget_cap_paise": bundle.budget_cap_paise,
        },
        "alternate": {
            "registry_path": str(registry_path.resolve()),
            "registry_sha256": sha256_file(registry_path),
            "registry_configuration_sha256": alternate_registry.digest,
            "profile_path": str(profile_path.resolve()),
            "profile_sha256": sha256_file(profile_path),
            "candidate_approval_path": str(approval_path.resolve()),
            "candidate_approval_sha256": sha256_file(approval_path),
            "candidate_approval_digest": candidate_bundle.digest,
            "profile_id": profile.profile_id,
            "routes": {
                "C2": [profile.stages[0].provider_id, profile.stages[0].model_id],
                "C4": [profile.stages[1].provider_id, profile.stages[1].model_id],
                "C5": [profile.stages[2].provider_id, profile.stages[2].model_id],
            },
        },
        "pricing": {
            "path": str(args.pricing_evidence.resolve()),
            "sha256": pricing_sha,
            "pricing_ref": pricing_ref,
            "input_usd_per_million": PRO_INPUT_USD_PER_MILLION,
            "output_usd_per_million": PRO_OUTPUT_USD_PER_MILLION,
            "planning_usd_to_inr": PLANNING_USD_TO_INR,
            "max_input_bytes": PRO_C4_MAX_INPUT_BYTES,
            "safe_billing_input_tokens": PRO_C4_SAFE_BILLING_INPUT_TOKENS,
            "system_prefix_overhead_tokens": PROMPT_OVERHEAD_TOKENS,
            "max_output_tokens": PRO_C4_MAX_OUTPUT_TOKENS,
            "computed_cost_paise": pro_c4_cost_bound_paise(),
            "quoted_max_cost_paise": PRO_C4_MAX_COST_PAISE,
        },
        "budget": {
            "same_budget_scope_id": str(bundle.budget_scope_id),
            "same_budget_cap_paise": bundle.budget_cap_paise,
            "projected_max_plan_cost_paise": projected_cost,
        },
        "provider_calls_performed": False,
        "database_writes_performed": False,
        "runtime_mutation_performed": False,
        "secrets_included": False,
        "activation_requires": [
            "owner-approved Pro pricing/provider terms and paid policy",
            "new pinned approval bundle digest",
            "admin save of the alternate registry revision",
            "Admin activation with the observed expected revision and idempotency key",
        ],
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    args = _parser().parse_args()
    manifest = prepare(args)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
