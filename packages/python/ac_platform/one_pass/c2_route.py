"""Gemini 3.1 Flash-Lite as the C2 route: the provider configuration and its sealed approval.

Owner, 21 Oct 2026: "So at least get this on prod now!!!". Production runs C2 on Scribe,
C4 and C5 on Gemini 3.8 Flash and the pointer review; its one-pass saving is the
transcription. A route is used only when its configuration digest is in the hosted
approval bundle, so:

- ``derive_configuration``: today's provider configuration with one change: the asr route
  goes to ``gemini / gemini-3.1-flash-lite`` (a provider entry with Gemini's own credential,
  terms, privacy and permission references, the Flash-Lite pricing reference and a
  ₹24 per-request ceiling); C4, C5 and everything else stay as they are;
- ``seal``: the bundle with every classic route kept and, in each acquisition policy, one
  more finite profile (``gemini-flash-lite-c2``) for that configuration: C2 on Flash-Lite,
  C4 and C5 copied from the classic templates with the new digest.

Admin activates either configuration; activating the classic one is the one-click
fallback. Pure: no I/O. ``scripts/ops/one_pass_c2_seal.py`` runs it on the host's files.
"""

from __future__ import annotations

import hashlib
from typing import Any, Final

from ac_platform.conversation_intelligence import gemini_audio
from ac_platform.conversation_intelligence.activation_contract import (
    AcquisitionProviderPolicy,
    AcquisitionProviderProfile,
    HostedApprovalBundle,
    load_hosted_approval_bundle,
)
from ac_platform.conversation_intelligence.admin_pricing import PRICING_SNAPSHOTS
from ac_platform.conversation_intelligence.provider_registry import (
    ProviderConfig,
    RegistryConfig,
    RouteConfig,
)

PROFILE_ID: Final = "gemini-flash-lite-c2"
PROVIDER: Final = "gemini"
MODEL: Final = gemini_audio.MODEL
ENDPOINT: Final = gemini_audio.URL.format(model=MODEL)
# One request is at most two hours of audio and 60,000 output tokens: USD 0.2052, ₹20.52
# (docs/ops/pricing-evidence/gemini-3.1-flash-lite-audio-20261020.md).
MAX_COST_PAISE: Final = 2_400
MAX_SOURCE_DURATION_MS: Final = 7_200_000


class SealError(ValueError):
    """A stable code: what in the inputs does not fit."""


def _gemini_entry(config: RegistryConfig) -> ProviderConfig:
    entries = [item for item in config.providers if item.provider_id == PROVIDER]
    for route in config.routes:
        if route.provider_id == PROVIDER:
            for item in entries:
                if item.model_id == route.model_id:
                    return item
    if not entries:
        raise SealError("configuration_has_no_gemini_provider")
    return entries[0]


def derive_configuration(config: RegistryConfig) -> RegistryConfig:
    """Today's configuration with the asr route on Gemini 3.1 Flash-Lite."""
    asr = next((route for route in config.routes if route.task == "asr"), None)
    if asr is None:
        raise SealError("configuration_has_no_asr_route")
    if asr.provider_id == PROVIDER:
        raise SealError("configuration_already_transcribes_on_gemini")
    gemini = _gemini_entry(config)
    entry = ProviderConfig(
        provider_id=PROVIDER,
        model_id=MODEL,
        endpoint=ENDPOINT,
        endpoint_sha256=hashlib.sha256(ENDPOINT.encode()).hexdigest(),
        credential_ref=gemini.credential_ref,
        provider_terms_ref=gemini.provider_terms_ref,
        privacy_ref=gemini.privacy_ref,
        pricing_ref=PRICING_SNAPSHOTS[(PROVIDER, MODEL)].pricing_ref,
        free_allowance_ref=None,
        permission_ref=gemini.permission_ref,
        endpoint_approval_ref=gemini.endpoint_approval_ref,
        local_endpoint_approval_ref=gemini.local_endpoint_approval_ref,
        max_cost_paise=MAX_COST_PAISE,
    )
    providers = tuple(
        item for item in config.providers if (item.provider_id, item.model_id) != (PROVIDER, MODEL)
    ) + (entry,)
    route = RouteConfig(
        task="asr",
        provider_id=PROVIDER,
        model_id=MODEL,
        recipe_revision=gemini_audio.RECIPE,
        profile_revision=asr.profile_revision,
        prompt_revision=gemini_audio.PROMPT_REVISION,
        required_input_stage=asr.required_input_stage,
        reuses_checkpoint_stage=asr.reuses_checkpoint_stage,
    )
    routes = tuple(route if item.task == "asr" else item for item in config.routes)
    revision = f"{config.revision}-gemini-c2"[:128]
    return RegistryConfig(
        revision=revision, policy=config.policy, providers=providers, routes=routes
    )


def _profile(
    policy: AcquisitionProviderPolicy, classic_sha256: str, new: RegistryConfig
) -> AcquisitionProviderProfile:
    stage_set = next(
        (
            stages
            for stages in policy.stage_sets()
            if {item.configuration_sha256 for item in stages} == {classic_sha256}
        ),
        None,
    )
    if stage_set is None:
        raise SealError("policy_does_not_approve_the_classic_configuration")
    c2, c4, c5 = stage_set
    entry = next(
        item for item in new.providers if (item.provider_id, item.model_id) == (PROVIDER, MODEL)
    )
    gemini = c4 if c4.provider_id == PROVIDER else c5
    if gemini.provider_id != PROVIDER:
        raise SealError("policy_has_no_gemini_text_stage")
    snapshot = PRICING_SNAPSHOTS[(PROVIDER, MODEL)]
    transcription = c2.model_copy(
        update={
            "configuration_sha256": new.digest,
            "provider_id": PROVIDER,
            "model_id": MODEL,
            "recipe_revision": gemini_audio.RECIPE,
            "permission_ref": entry.permission_ref,
            "pricing_ref": snapshot.pricing_ref,
            "provider_terms_ref": entry.provider_terms_ref,
            "privacy_ref": entry.privacy_ref,
            "credential_ref": entry.credential_ref,
            "free_allowance_ref": None,
            "privacy_revision": gemini.privacy_revision,
            "privacy_notice": gemini.privacy_notice,
            "zero_cost_basis": "paid_pricing_evidence",
            "price_evidence_sha256": snapshot.evidence_sha256,
            "max_cost_paise": MAX_COST_PAISE,
            "max_source_duration_ms": min(c2.max_source_duration_ms, MAX_SOURCE_DURATION_MS),
            "max_completion_tokens": 0,
        }
    )
    stages = (
        type(c2).model_validate(transcription.model_dump()),
        c4.model_copy(update={"configuration_sha256": new.digest}),
        c5.model_copy(update={"configuration_sha256": new.digest}),
    )
    return AcquisitionProviderProfile(profile_id=PROFILE_ID, stages=stages)


def _with_profile(
    policy: AcquisitionProviderPolicy, classic_sha256: str, new: RegistryConfig
) -> AcquisitionProviderPolicy:
    kept = tuple(item for item in policy.profiles if item.profile_id != PROFILE_ID)
    updated = policy.model_copy(update={"profiles": (*kept, _profile(policy, classic_sha256, new))})
    # Strict models: revalidate through JSON, as the host loads the file.
    return AcquisitionProviderPolicy.model_validate_json(updated.model_dump_json(by_alias=True))


def seal(
    bundle: HostedApprovalBundle, classic: RegistryConfig, new: RegistryConfig
) -> HostedApprovalBundle:
    """The bundle with every classic route kept and the Flash-Lite profile added to each
    acquisition policy. Revalidated as a whole, exactly as the host loads it."""
    if bundle.acquisition_policy is None and not bundle.organisation_acquisition_policies:
        raise SealError("bundle_has_no_acquisition_policy")
    update: dict[str, Any] = {
        "organisation_acquisition_policies": tuple(
            _with_profile(item, classic.digest, new)
            for item in bundle.organisation_acquisition_policies
        )
    }
    if bundle.acquisition_policy is not None:
        update["acquisition_policy"] = _with_profile(bundle.acquisition_policy, classic.digest, new)
    sealed = load_hosted_approval_bundle(bundle.model_copy(update=update).to_json())
    for before, after in zip(
        (
            *(() if bundle.acquisition_policy is None else (bundle.acquisition_policy,)),
            *bundle.organisation_acquisition_policies,
        ),
        (
            *(() if sealed.acquisition_policy is None else (sealed.acquisition_policy,)),
            *sealed.organisation_acquisition_policies,
        ),
        strict=True,
    ):
        if after.stages != before.stages:
            raise SealError("classic_routes_changed")
    if sealed.stages != bundle.stages or sealed.allowances != bundle.allowances:
        raise SealError("classic_routes_changed")
    return sealed
