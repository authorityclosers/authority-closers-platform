"""Gemini 3.1 Flash-Lite as the C2 route: the provider configuration and its sealed approval.

Owner, 21 Oct 2026: "So at least get this on prod now!!!". Production runs C2 on Scribe,
C4 and C5 on Gemini 3.8 Flash and the pointer review; its one-pass saving is the
transcription. A route is used only when its configuration digest is in the hosted
approval bundle, so:

- ``derive_configuration``: today's provider configuration with one change: the asr route
  goes to ``gemini / gemini-3.1-flash-lite`` (a provider entry with Gemini's own credential,
  terms, privacy and permission references, the Flash-Lite pricing reference and a
  ₹40 per-request ceiling); C4, C5 and everything else stay as they are;
- ``seal``: the bundle with every classic route kept and, in each acquisition policy, one
  more finite profile (``gemini-flash-lite-c2``) for that configuration: C2 on Flash-Lite,
  C4 and C5 copied from the classic templates with the new digest.

With ``one_pass`` (owner, 21 Oct 2026: "build B ... one-pass in the sealed plan"), the
facts route is also the one-pass C4 request (``one_pass.stage``: one read of the whole call
gives the C4 fact packet, the call data and the pointer review; today's C5 reads the packet).
Its profile's C4 template is one request at the one-pass output bound, and the Gemini
3.8 Flash entry's per-request ceiling covers the whole call's input.

With ``luna`` (the cheapest choice, cost research 21 Oct 2026), the one-pass C4 request
and C5 both go to OpenAI GPT-6 Luna (standard or Flex): the configuration must already
carry an OpenAI GPT-6 Luna provider entry (its credential, terms, privacy and permission
references are an admin's governance step in Providers, never made up here), and Root
supplies the OpenAI stages' privacy notice and retention references when sealing.

Admin activates either configuration; activating the classic one is the one-click
fallback. Pure: no I/O. ``scripts/ops/one_pass_c2_seal.py`` runs it on the host's files.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Any, Final

from ac_platform.conversation_intelligence import gemini_audio, gemini_tiers
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
from ac_platform.one_pass import markers

PROFILE_ID: Final = "gemini-flash-lite-c2"
# Flash-Lite C2 and Gemini 3.8 Flash C4/C5 on Flex (gemini_tiers), a second finite profile.
FLEX_PROFILE_ID: Final = "gemini-flash-lite-c2-flex"
TEXT_MODEL: Final = "gemini-3.8-flash"
PROVIDER: Final = "gemini"
MODEL: Final = gemini_audio.MODEL
ENDPOINT: Final = gemini_audio.URL.format(model=MODEL)
# Two hours of audio at the measured planning rate, its parts heard 30 seconds into each
# other: about USD 0.38 (docs/ops/pricing-evidence/gemini-3.1-flash-lite-audio-20261021.md).
MAX_COST_PAISE: Final = 4_000
MAX_SOURCE_DURATION_MS: Final = 7_200_000
# One pass inside the plan: Flash-Lite C2 and the one-pass C4 request, standard or Flex.
ONE_PASS_PROFILE_ID: Final = "gemini-one-pass"  # noqa: S105 - a profile id
ONE_PASS_FLEX_PROFILE_ID: Final = "gemini-one-pass-flex"  # noqa: S105 - a profile id
# The one request's output bound on Gemini (call data, notes and the review measured at
# 6.5-9.1k tokens with thinking LOW, 21 Oct 2026).
ONE_PASS_COMPLETION_TOKENS: Final = 16_000
# Per request on Gemini 3.8 Flash at standard rates: a two-hour call's transcript, the
# instructions and schema (about 300k input tokens) and the full output: about USD 0.30.
ONE_PASS_MAX_COST_PAISE: Final = 3_000
# GPT-6 Luna (OpenAI) for the one-pass C4 request and C5, standard or Flex.
LUNA_MODEL: Final = "gpt-6-luna"
LUNA_PROFILE_ID: Final = "luna-one-pass"
LUNA_FLEX_PROFILE_ID: Final = "luna-one-pass-flex"
LUNA_ENDPOINT: Final = "https://api.openai.com/v1/responses"
LUNA_COMPLETION_TOKENS: Final = 20_000
# Per request at standard rates: a two-hour call's transcript (about 255k input tokens)
# and 20,000 output tokens is about USD 0.04; Rs 10 is the extended-output floor.
LUNA_MAX_COST_PAISE: Final = 1_000
# What Root supplies for the OpenAI stages (privacy notice and retention are governance).
LUNA_GOVERNANCE_FIELDS: Final = (
    "privacy_revision",
    "privacy_notice",
    "retention_ref",
    "professional_gate_ref",
)


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


def _entry(gemini: ProviderConfig, model: str, max_cost_paise: int | None) -> ProviderConfig:
    endpoint = gemini_audio.URL.format(model=gemini_tiers.base_model(model))
    return ProviderConfig(
        provider_id=PROVIDER,
        model_id=model,
        endpoint=endpoint,
        endpoint_sha256=hashlib.sha256(endpoint.encode()).hexdigest(),
        credential_ref=gemini.credential_ref,
        provider_terms_ref=gemini.provider_terms_ref,
        privacy_ref=gemini.privacy_ref,
        pricing_ref=PRICING_SNAPSHOTS[(PROVIDER, model)].pricing_ref,
        free_allowance_ref=None,
        permission_ref=gemini.permission_ref,
        endpoint_approval_ref=gemini.endpoint_approval_ref,
        local_endpoint_approval_ref=gemini.local_endpoint_approval_ref,
        max_cost_paise=max_cost_paise,
    )


def derive_configuration(
    config: RegistryConfig, *, flex: bool = False, one_pass: bool = False, luna: bool = False
) -> RegistryConfig:
    """Today's (Scribe) configuration with the asr route on Gemini 3.1 Flash-Lite; with
    ``flex``, Flash-Lite and the Gemini 3.8 Flash C4/C5 routes on their Flex routes
    (gemini_tiers), each keeping its standard per-request ceiling (a fallback is billed at
    standard); with ``one_pass``, the facts route is the one-pass C4 request; with
    ``luna`` too, it and the coaching route are on GPT-6 Luna (``flex``: Luna on Flex)."""
    if luna and not one_pass:
        raise SealError("luna_is_the_one_pass_route")
    asr = next((route for route in config.routes if route.task == "asr"), None)
    if asr is None:
        raise SealError("configuration_has_no_asr_route")
    if asr.provider_id == PROVIDER:
        raise SealError("configuration_already_transcribes_on_gemini")
    gemini = _gemini_entry(config)
    transcription_model = gemini_tiers.flex(MODEL) if flex else MODEL
    entries = [_entry(gemini, transcription_model, MAX_COST_PAISE)]
    text_models: dict[str, str] = {}
    if flex and not luna:
        for item in config.providers:
            if (item.provider_id, item.model_id) == (PROVIDER, TEXT_MODEL):
                text_models[TEXT_MODEL] = gemini_tiers.flex(TEXT_MODEL)
                entries.append(_entry(item, gemini_tiers.flex(TEXT_MODEL), item.max_cost_paise))
    added = {entry.model_id for entry in entries}
    providers = tuple(
        item
        for item in config.providers
        if not (item.provider_id == PROVIDER and item.model_id in added)
    ) + tuple(entries)
    route = RouteConfig(
        task="asr",
        provider_id=PROVIDER,
        model_id=transcription_model,
        recipe_revision=gemini_audio.RECIPE,
        profile_revision=asr.profile_revision,
        prompt_revision=gemini_audio.PROMPT_REVISION,
        required_input_stage=asr.required_input_stage,
        reuses_checkpoint_stage=asr.reuses_checkpoint_stage,
    )
    routes = tuple(
        route
        if item.task == "asr"
        else replace(item, model_id=text_models[item.model_id])
        if item.provider_id == PROVIDER and item.model_id in text_models
        else item
        for item in config.routes
    )
    if luna:
        providers, routes = _luna(providers, routes, flex=flex)
    elif one_pass:
        providers, routes = _one_pass(providers, routes, flex=flex)
    suffix = ("-luna" if luna else "-one-pass" if one_pass else "") + ("-flex" if flex else "")
    revision = f"{config.revision}-gemini-c2{suffix}"[:128]
    return RegistryConfig(
        revision=revision, policy=config.policy, providers=providers, routes=routes
    )


def _one_pass(
    providers: tuple[ProviderConfig, ...], routes: tuple[RouteConfig, ...], *, flex: bool
) -> tuple[tuple[ProviderConfig, ...], tuple[RouteConfig, ...]]:
    """The facts route as the one-pass request, and its Gemini entry's ceiling raised to
    cover the whole call (C5 on the same model shares the entry, so its ceiling too)."""
    model = gemini_tiers.flex(TEXT_MODEL) if flex else TEXT_MODEL
    facts = next((route for route in routes if route.task == "facts"), None)
    if facts is None or (facts.provider_id, facts.model_id) != (PROVIDER, model):
        raise SealError("facts_route_is_not_gemini_flash")
    if (facts.provider_id, facts.model_id) not in markers.ROUTES:
        raise SealError("facts_route_is_not_one_pass_capable")
    providers = tuple(
        replace(item, max_cost_paise=max(item.max_cost_paise or 0, ONE_PASS_MAX_COST_PAISE))
        if (item.provider_id, item.model_id) == (PROVIDER, model)
        else item
        for item in providers
    )
    routes = tuple(
        replace(route, recipe_revision=markers.RECIPE, prompt_revision=markers.PROMPT_REVISION)
        if route.task == "facts"
        else route
        for route in routes
    )
    return providers, routes


def _luna(
    providers: tuple[ProviderConfig, ...], routes: tuple[RouteConfig, ...], *, flex: bool
) -> tuple[tuple[ProviderConfig, ...], tuple[RouteConfig, ...]]:
    """The facts route as the one-pass request and the coaching route, both on GPT-6
    Luna, with the configuration's own OpenAI entry's references."""
    openai = next(
        (item for item in providers if (item.provider_id, item.model_id) == ("openai", LUNA_MODEL)),
        None,
    )
    if openai is None:
        raise SealError("configuration_has_no_openai_luna_provider")
    model = LUNA_MODEL + (":flex" if flex else "")
    if ("openai", model) not in markers.ROUTES:
        raise SealError("luna_is_not_one_pass_capable")
    entry = ProviderConfig(
        provider_id="openai",
        model_id=model,
        endpoint=LUNA_ENDPOINT,
        endpoint_sha256=hashlib.sha256(LUNA_ENDPOINT.encode()).hexdigest(),
        credential_ref=openai.credential_ref,
        provider_terms_ref=openai.provider_terms_ref,
        privacy_ref=openai.privacy_ref,
        pricing_ref=PRICING_SNAPSHOTS[("openai", model)].pricing_ref,
        free_allowance_ref=None,
        permission_ref=openai.permission_ref,
        endpoint_approval_ref=openai.endpoint_approval_ref,
        local_endpoint_approval_ref=openai.local_endpoint_approval_ref,
        max_cost_paise=LUNA_MAX_COST_PAISE,
    )
    providers = tuple(
        item for item in providers if (item.provider_id, item.model_id) != ("openai", model)
    ) + (entry,)
    if not any(route.task == "facts" for route in routes) or not any(
        route.task == "coaching" for route in routes
    ):
        raise SealError("configuration_has_no_text_routes")
    routes = tuple(
        replace(
            route,
            provider_id="openai",
            model_id=model,
            recipe_revision=markers.RECIPE,
            prompt_revision=markers.PROMPT_REVISION,
        )
        if route.task == "facts"
        else replace(route, provider_id="openai", model_id=model)
        if route.task == "coaching"
        else route
        for route in routes
    )
    return providers, routes


def _luna_stages(
    c4: Any, c5: Any, new: RegistryConfig, *, flex: bool, governance: Any
) -> tuple[Any, Any]:
    """The C4 (one-pass) and C5 templates on GPT-6 Luna: the classic templates' bounds,
    the configuration's OpenAI references and Root's OpenAI governance."""
    if not isinstance(governance, dict) or set(governance) != set(LUNA_GOVERNANCE_FIELDS):
        raise SealError("luna_needs_roots_openai_governance")
    model = LUNA_MODEL + (":flex" if flex else "")
    entry = next(
        item for item in new.providers if (item.provider_id, item.model_id) == ("openai", model)
    )
    snapshot = PRICING_SNAPSHOTS[("openai", model)]
    common = {
        "configuration_sha256": new.digest,
        "provider_id": "openai",
        "model_id": model,
        "permission_ref": entry.permission_ref,
        "pricing_ref": snapshot.pricing_ref,
        "provider_terms_ref": entry.provider_terms_ref,
        "privacy_ref": entry.privacy_ref,
        "credential_ref": entry.credential_ref,
        "free_allowance_ref": None,
        "zero_cost_basis": "paid_pricing_evidence",
        "price_evidence_sha256": snapshot.evidence_sha256,
        "max_cost_paise": entry.max_cost_paise,
        **governance,
    }
    one_pass = {
        **common,
        "recipe_revision": markers.RECIPE,
        "max_requests": 1,
        "max_completion_tokens": LUNA_COMPLETION_TOKENS,
        "max_input_bytes": max(c4.max_input_bytes, markers.MAX_INPUT_BYTES),
        "max_source_duration_ms": min(c4.max_source_duration_ms, MAX_SOURCE_DURATION_MS),
    }
    coaching = {**common, "max_completion_tokens": min(c5.max_completion_tokens, 8_000)}
    return (
        type(c4).model_validate(c4.model_copy(update=one_pass).model_dump()),
        type(c5).model_validate(c5.model_copy(update=coaching).model_dump()),
    )


def _profile(
    policy: AcquisitionProviderPolicy,
    classic_sha256: str,
    new: RegistryConfig,
    *,
    flex: bool = False,
    one_pass: bool = False,
    luna: Any = None,
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
    transcription_model = gemini_tiers.flex(MODEL) if flex else MODEL
    entry = next(
        item
        for item in new.providers
        if (item.provider_id, item.model_id) == (PROVIDER, transcription_model)
    )
    gemini = c4 if c4.provider_id == PROVIDER else c5
    if gemini.provider_id != PROVIDER:
        raise SealError("policy_has_no_gemini_text_stage")
    snapshot = PRICING_SNAPSHOTS[(PROVIDER, transcription_model)]
    transcription = c2.model_copy(
        update={
            "configuration_sha256": new.digest,
            "provider_id": PROVIDER,
            "model_id": transcription_model,
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

    def text(stage: Any) -> Any:
        update: dict[str, Any] = {"configuration_sha256": new.digest}
        if flex and (stage.provider_id, stage.model_id) == (PROVIDER, TEXT_MODEL):
            flex_snapshot = PRICING_SNAPSHOTS[(PROVIDER, gemini_tiers.flex(TEXT_MODEL))]
            update.update(
                model_id=gemini_tiers.flex(TEXT_MODEL),
                pricing_ref=flex_snapshot.pricing_ref,
                price_evidence_sha256=flex_snapshot.evidence_sha256,
            )
        if one_pass and (stage.provider_id, stage.model_id) == (PROVIDER, TEXT_MODEL):
            # The shared Gemini entry's ceiling (validate_route matches it per stage).
            model = update.get("model_id", TEXT_MODEL)
            update["max_cost_paise"] = next(
                item.max_cost_paise
                for item in new.providers
                if (item.provider_id, item.model_id) == (PROVIDER, model)
            )
            if stage.stage == "C4":
                update.update(
                    recipe_revision=markers.RECIPE,
                    max_requests=1,
                    max_completion_tokens=ONE_PASS_COMPLETION_TOKENS,
                    max_input_bytes=max(stage.max_input_bytes, markers.MAX_INPUT_BYTES),
                    max_source_duration_ms=min(
                        stage.max_source_duration_ms, MAX_SOURCE_DURATION_MS
                    ),
                )
        return type(stage).model_validate(stage.model_copy(update=update).model_dump())

    if luna is not None:
        luna_c4, luna_c5 = _luna_stages(c4, c5, new, flex=flex, governance=luna)
        stages = (type(c2).model_validate(transcription.model_dump()), luna_c4, luna_c5)
        return AcquisitionProviderProfile(
            profile_id=LUNA_FLEX_PROFILE_ID if flex else LUNA_PROFILE_ID, stages=stages
        )
    if one_pass and (c4.provider_id, c4.model_id) != (PROVIDER, TEXT_MODEL):
        raise SealError("policy_c4_is_not_gemini_flash")
    stages = (type(c2).model_validate(transcription.model_dump()), text(c4), text(c5))
    profile_id = (
        (ONE_PASS_FLEX_PROFILE_ID if flex else ONE_PASS_PROFILE_ID)
        if one_pass
        else FLEX_PROFILE_ID
        if flex
        else PROFILE_ID
    )
    return AcquisitionProviderProfile(profile_id=profile_id, stages=stages)


def _with_profile(
    policy: AcquisitionProviderPolicy,
    classic_sha256: str,
    new: RegistryConfig,
    *,
    flex: bool = False,
    one_pass: bool = False,
    luna: Any = None,
) -> AcquisitionProviderPolicy:
    profile = _profile(policy, classic_sha256, new, flex=flex, one_pass=one_pass, luna=luna)
    kept = tuple(item for item in policy.profiles if item.profile_id != profile.profile_id)
    updated = policy.model_copy(update={"profiles": (*kept, profile)})
    # Strict models: revalidate through JSON, as the host loads the file.
    return AcquisitionProviderPolicy.model_validate_json(updated.model_dump_json(by_alias=True))


def seal(
    bundle: HostedApprovalBundle,
    classic: RegistryConfig,
    new: RegistryConfig,
    *,
    flex: bool = False,
    one_pass: bool = False,
    luna: Any = None,
) -> HostedApprovalBundle:
    """The bundle with every classic route kept and the Flash-Lite (or one-pass) profile
    added to each acquisition policy. Revalidated as a whole, exactly as the host loads it."""
    if bundle.acquisition_policy is None and not bundle.organisation_acquisition_policies:
        raise SealError("bundle_has_no_acquisition_policy")
    update: dict[str, Any] = {
        "organisation_acquisition_policies": tuple(
            _with_profile(item, classic.digest, new, flex=flex, one_pass=one_pass, luna=luna)
            for item in bundle.organisation_acquisition_policies
        )
    }
    if bundle.acquisition_policy is not None:
        update["acquisition_policy"] = _with_profile(
            bundle.acquisition_policy,
            classic.digest,
            new,
            flex=flex,
            one_pass=one_pass,
            luna=luna,
        )
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
