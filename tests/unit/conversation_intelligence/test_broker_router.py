"""Pure fail-closed tests for the fixed hosted provider router."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

import pytest

from ac_platform.conversation_intelligence.activation_contract import (
    HOSTED_APPROVAL_SCHEMA,
    HostedApprovalBundle,
    StageApproval,
)
from ac_platform.conversation_intelligence.broker_router import (
    FixedProviderRouter,
    ProviderRoute,
    ProviderRouterError,
)
from ac_platform.conversation_intelligence.checkpoints import SourceBinding, canonical
from ac_platform.conversation_intelligence.entitlements import (
    ExecutionPermission,
    Quote,
    Reservation,
)
from ac_platform.conversation_intelligence.inference_broker import InferenceBrokerError
from ac_platform.conversation_intelligence.inference_tasks import (
    prepare_coaching_input,
    prepare_fact_inputs,
)
from ac_platform.conversation_intelligence.providers import ProviderResult
from ac_platform.conversation_intelligence.reporting_pipeline import (
    COACHING_RECIPE,
    FACT_RECIPE,
)
from ac_platform.conversation_intelligence.reports import FactPacket, load_report_profile

TENANT_ID = UUID("10000000-0000-4000-8000-000000000001")
PERSON_ID = UUID("20000000-0000-4000-8000-000000000002")
BUDGET_ID = UUID("30000000-0000-4000-8000-000000000003")
SOURCE = b"synthetic router audio"
SOURCE_SHA = hashlib.sha256(SOURCE).hexdigest()
NOW_EPOCH = 1_000
NOW = datetime.fromtimestamp(NOW_EPOCH, UTC)


class FakeChild:
    def __init__(self) -> None:
        self.calls: list[tuple[Reservation, bytes]] = []

    async def execute(self, reservation: Reservation, payload: bytes) -> ProviderResult:
        self.calls.append((reservation, payload))
        raw = b'{"ok":true}'
        return ProviderResult(
            provider=reservation.quote.provider_id,
            model=reservation.quote.provider_model,
            request_id="synthetic-router-request",
            response_sha256=hashlib.sha256(raw).hexdigest(),
            raw_json=raw,
            data={"ok": True},
            input_sha256=hashlib.sha256(payload).hexdigest(),
        )


class ResultMutationChild(FakeChild):
    def __init__(self, **mutations: object) -> None:
        super().__init__()
        self._mutations: dict[str, Any] = mutations

    async def execute(self, reservation: Reservation, payload: bytes) -> ProviderResult:
        result = await super().execute(reservation, payload)
        return replace(result, **self._mutations)


class WrongTypeChild:
    async def execute(self, reservation: Reservation, payload: bytes) -> Any:
        return {"provider": reservation.quote.provider_id}


class UnexpectedFailureChild(FakeChild):
    async def execute(self, reservation: Reservation, payload: bytes) -> ProviderResult:
        raise RuntimeError("synthetic sk_live_router_secret_should_not_escape")


class StableFailureChild(FakeChild):
    async def execute(self, reservation: Reservation, payload: bytes) -> ProviderResult:
        raise InferenceBrokerError("broker_timeout")


class CancellationChild(FakeChild):
    async def execute(self, reservation: Reservation, payload: bytes) -> ProviderResult:
        raise asyncio.CancelledError


def _stage(
    *,
    credential_ref: str | None = None,
    expires_at_epoch: int = 1_800,
    provider_id: str = "elevenlabs",
    model_id: str = "scribe_v2",
    stage: Literal["C2", "C4", "C5"] = "C2",
    recipe_revision: str = "scribe-v2-native-normalized-v1",
    profile_sha256: str | None = None,
) -> StageApproval:
    is_c2 = stage == "C2"
    resolved_credential_ref = credential_ref or f"ref:credential/{provider_id}/v1"
    return StageApproval(
        id=UUID("40000000-0000-4000-8000-000000000004"),
        tenant_id=TENANT_ID,
        person_id=PERSON_ID,
        source_sha256=SOURCE_SHA,
        configuration_sha256="b" * 64,
        stage=stage,
        provider_id=provider_id,
        model_id=model_id,
        recipe_revision=recipe_revision,
        permission_ref="ref:permission/router-v1",
        retention_ref="ref:retention/router-v1",
        professional_gate_ref="ref:professional/router-v1",
        pricing_ref="ref:pricing/router-zero-v1",
        provider_terms_ref="ref:terms/router-v1",
        privacy_ref="ref:privacy/router-v1",
        credential_ref=resolved_credential_ref,
        free_allowance_ref="ref:allowance/router-v1",
        no_paid_overage_ref="ref:billing/router-no-overage-v1",
        privacy_revision="privacy-router-v1",
        privacy_notice="Synthetic router test approval.",
        expires_at_epoch=expires_at_epoch,
        max_requests=1,
        entitlement_seconds=None if is_c2 else 0,
        zero_cost_basis="synthetic",
        price_evidence_sha256="c" * 64,
        max_source_duration_ms=14_400_000,
        max_input_bytes=32 * 1024 * 1024,
        max_completion_tokens=0 if is_c2 else 4_000,
        profile_sha256=profile_sha256,
    )


def _bundle(stage: StageApproval | None = None) -> HostedApprovalBundle:
    return HostedApprovalBundle(
        schema_id=HOSTED_APPROVAL_SCHEMA,
        environment="test",
        provider_control_tenant_id=TENANT_ID,
        deployment_ref="ref:deployment/router-test-v1",
        issued_at_epoch=900,
        expires_at_epoch=2_000,
        budget_scope_id=BUDGET_ID,
        budget_authorization_ref="ref:budget/router-test-v1",
        budget_owner_id=PERSON_ID,
        intake_authorization_ref="ref:intake/router-test-v1",
        intake_retention_ref="ref:retention/router-intake-v1",
        retention_days=7,
        max_stored_source_bytes=1_073_741_824,
        allowances=(),
        stages=(_stage() if stage is None else stage,),
    )


def _reservation(
    bundle: HostedApprovalBundle,
    *,
    permission_ref: str | None = None,
    provider_id: str = "elevenlabs",
    provider_model: str = "scribe_v2",
    recipe_revision: str = "scribe-v2-native-normalized-v1",
    operation: str = "transcribe_scribe_v2",
    input_sha256: str = SOURCE_SHA,
    entitlement_seconds: int = 1,
) -> Reservation:
    quote = Quote(
        quote_id="quote-router-1",
        source=SourceBinding(str(TENANT_ID), "recording-router-1", SOURCE_SHA, "1"),
        account_id=str(PERSON_ID),
        budget_scope_id=str(BUDGET_ID),
        provider_id=provider_id,
        provider_model=provider_model,
        recipe_revision=recipe_revision,
        operation=operation,
        input_sha256=input_sha256,
        privacy_revision="privacy-router-v1",
        permission_ref=permission_ref or "ref:permission/router-v1",
        provider_terms_ref="ref:terms/router-v1",
        retention_ref="ref:retention/router-v1",
        professional_gate_ref="ref:professional/router-v1",
        pricing_ref="ref:pricing/router-zero-v1",
        entitlement_seconds=entitlement_seconds,
        max_cost_paise=0,
        created_at_epoch=900,
        expires_at_epoch=1_600,
    )
    permission = ExecutionPermission(
        authorization_ref=(f"hosted-stage-v1:{bundle.stages[0].id}:{bundle.digest}"),
        quote_fingerprint=quote.fingerprint,
        approved_by=str(PERSON_ID),
        expires_at_epoch=1_600,
    )
    return Reservation(
        reservation_id="reservation-router-1",
        quote=quote,
        permission=permission,
        state="in_flight",
        attempt_id="attempt-router-1",
    )


def _router(bundle_box: dict[str, HostedApprovalBundle], child: Any) -> FixedProviderRouter:
    return FixedProviderRouter(
        {
            "elevenlabs": ProviderRoute("elevenlabs", "ref:credential/elevenlabs/v1", child),
            "groq": ProviderRoute("groq", "ref:credential/groq/v1", child),
            "gemini": ProviderRoute("gemini", "ref:credential/gemini/v1", child),
        },
        current_authority=lambda _now: bundle_box["bundle"],
        clock=lambda: NOW,
    )


@pytest.mark.asyncio
async def test_exact_current_approval_selects_only_fixed_provider_child() -> None:
    child = FakeChild()
    bundle_box = {"bundle": _bundle()}
    reservation = _reservation(bundle_box["bundle"])

    result = await _router(bundle_box, child).execute(reservation, SOURCE)

    assert result.provider == "elevenlabs"
    assert child.calls == [(reservation, SOURCE)]


@pytest.mark.asyncio
async def test_changed_credential_reference_is_rejected_before_child() -> None:
    child = FakeChild()
    bundle_box = {"bundle": _bundle(_stage(credential_ref="ref:credential/elevenlabs/v2"))}
    reservation = _reservation(bundle_box["bundle"])

    with pytest.raises(ProviderRouterError, match="broker_router_credential_mismatch"):
        await _router(bundle_box, child).execute(reservation, SOURCE)

    assert child.calls == []


@pytest.mark.asyncio
async def test_unknown_provider_has_no_fallback_child() -> None:
    child = FakeChild()
    bundle = _bundle(_stage(provider_id="unconfigured-provider"))
    reservation = _reservation(bundle, provider_id="unconfigured-provider")
    # An unconfigured approved provider cannot fall through to ElevenLabs.

    with pytest.raises(ProviderRouterError, match="broker_router_provider_unconfigured"):
        await FixedProviderRouter(
            {"elevenlabs": ProviderRoute("elevenlabs", "ref:credential/elevenlabs/v1", child)},
            current_authority=lambda _now: bundle,
            clock=lambda: NOW,
        ).execute(reservation, SOURCE)

    assert child.calls == []


@pytest.mark.asyncio
async def test_stale_stage_approval_is_rejected_before_child() -> None:
    child = FakeChild()
    bundle = _bundle(_stage(expires_at_epoch=999))
    reservation = _reservation(bundle)

    with pytest.raises(ProviderRouterError, match="broker_router_expired"):
        await _router({"bundle": bundle}, child).execute(reservation, SOURCE)

    assert child.calls == []


@pytest.mark.asyncio
async def test_permission_authorization_is_bound_to_current_bundle_digest() -> None:
    child = FakeChild()
    current = _bundle()
    old = _bundle(_stage(credential_ref="ref:credential/elevenlabs/old"))
    reservation = _reservation(old)

    with pytest.raises(ProviderRouterError, match="broker_router_authorization_mismatch"):
        await _router({"bundle": current}, child).execute(reservation, SOURCE)

    assert child.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("provider", "elevenlabs-forged"),
        ("model", "different-model"),
        ("input_sha256", "f" * 64),
        ("response_sha256", "f" * 64),
        ("raw_json", bytearray(b'{"ok":true}')),
    ),
)
async def test_child_result_is_bound_to_reservation_and_raw_receipt(
    field: str, value: object
) -> None:
    child = ResultMutationChild(**{field: value})
    bundle = _bundle()
    reservation = _reservation(bundle)

    with pytest.raises(ProviderRouterError, match="broker_router_result_mismatch"):
        await _router({"bundle": bundle}, child).execute(reservation, SOURCE)

    assert len(child.calls) == 1


@pytest.mark.asyncio
async def test_wrong_child_result_type_is_rejected() -> None:
    child = WrongTypeChild()
    bundle = _bundle()

    with pytest.raises(ProviderRouterError, match="broker_router_result_mismatch"):
        await _router({"bundle": bundle}, child).execute(_reservation(bundle), SOURCE)


@pytest.mark.asyncio
async def test_c2_quote_input_digest_must_remain_exact_source_digest() -> None:
    child = FakeChild()
    bundle = _bundle()
    original = _reservation(bundle)
    alternate = b"synthetic router alternate source bytes"
    quote = replace(
        original.quote,
        input_sha256=hashlib.sha256(alternate).hexdigest(),
    )
    permission = replace(original.permission, quote_fingerprint=quote.fingerprint)
    reservation = replace(original, quote=quote, permission=permission)

    with pytest.raises(ProviderRouterError, match="broker_router_payload_mismatch"):
        await _router({"bundle": bundle}, child).execute(reservation, alternate)

    assert child.calls == []


def _synthetic_transcript() -> dict[str, Any]:
    return {
        "source_sha256": SOURCE_SHA,
        "revision": "synthetic-transcript-revision",
        "timebase_id": "scribe-native-seconds",
        "duration_ms": 1_000,
        "segments": [
            {
                "id": "segment-1",
                "speaker_id": "speaker-1",
                "start_ms": 0,
                "end_ms": 800,
                "text": "The buyer asked about price.",
            }
        ],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("price", [0, 50])
async def test_gemini_uses_exact_free_or_paid_scope_without_fallback(price: int) -> None:
    prepared = prepare_fact_inputs(
        _synthetic_transcript(), provider="gemini", model="gemini-3.8-flash"
    )[0]
    stage = _stage(
        stage="C4", provider_id="gemini", model_id=prepared.model, recipe_revision=FACT_RECIPE
    )
    value = _bundle(stage).model_dump(mode="json")
    if price:
        value.update(budget_cap_paise=100, paid_approval_ref="ref:owner/paid-test")
        value["stages"][0].update(
            max_cost_paise=price, zero_cost_basis="paid_pricing_evidence", free_allowance_ref=None
        )
    bundle = HostedApprovalBundle.model_validate_json(canonical(value))
    reservation = _reservation(
        bundle,
        provider_id="gemini",
        provider_model=prepared.model,
        recipe_revision=FACT_RECIPE,
        operation="extract_context_evidence",
        input_sha256=prepared.input_sha256,
        entitlement_seconds=0,
    )
    quote = replace(reservation.quote, max_cost_paise=price)
    reservation = replace(
        reservation,
        quote=quote,
        permission=replace(reservation.permission, quote_fingerprint=quote.fingerprint),
    )
    child = FakeChild()
    router = _router({"bundle": bundle}, child)
    result = await router.execute(reservation, prepared.payload)
    assert result.provider == "gemini" and len(child.calls) == 1
    changed_quote = replace(quote, max_cost_paise=price + 1)
    changed = replace(
        reservation,
        quote=changed_quote,
        permission=replace(reservation.permission, quote_fingerprint=changed_quote.fingerprint),
    )
    with pytest.raises(ProviderRouterError, match="broker_router_authorization_mismatch"):
        await router.execute(changed, prepared.payload)
    assert len(child.calls) == 1


@pytest.mark.asyncio
async def test_gemini_router_checks_native_output_cap_before_child() -> None:
    prepared = prepare_fact_inputs(
        _synthetic_transcript(), provider="gemini", model="gemini-3.8-flash"
    )[0]
    stage = _stage(
        stage="C4", provider_id="gemini", model_id=prepared.model, recipe_revision=FACT_RECIPE
    )
    stage = stage.model_copy(update={"max_completion_tokens": 512})
    bundle = _bundle(stage)
    reservation = _reservation(
        bundle,
        provider_id="gemini",
        provider_model=prepared.model,
        recipe_revision=FACT_RECIPE,
        operation="extract_context_evidence",
        input_sha256=prepared.input_sha256,
        entitlement_seconds=0,
    )
    child = FakeChild()
    with pytest.raises(ProviderRouterError, match="broker_router_payload_mismatch"):
        await _router({"bundle": bundle}, child).execute(reservation, prepared.payload)
    assert child.calls == []


@pytest.mark.asyncio
async def test_c4_router_accepts_production_fact_recipe_and_payload() -> None:
    transcript = _synthetic_transcript()
    prepared = prepare_fact_inputs(transcript)[0]
    stage = _stage(
        stage="C4",
        provider_id="groq",
        model_id=prepared.model,
        recipe_revision=FACT_RECIPE,
    )
    bundle = _bundle(stage)
    reservation = _reservation(
        bundle,
        provider_id="groq",
        provider_model=prepared.model,
        recipe_revision=FACT_RECIPE,
        operation="extract_context_evidence",
        input_sha256=prepared.input_sha256,
        entitlement_seconds=0,
    )
    child = FakeChild()

    result = await _router({"bundle": bundle}, child).execute(reservation, prepared.payload)

    assert result.provider == "groq"
    assert child.calls == [(reservation, prepared.payload)]


@pytest.mark.asyncio
async def test_c5_router_accepts_production_coaching_recipe_and_frozen_profile() -> None:
    transcript = _synthetic_transcript()
    fact_packet = FactPacket(
        schema_id="ac.sales-xray.style-independent-facts/1",
        source_sha256=SOURCE_SHA,
        transcript_revision=str(transcript["revision"]),
        timebase_id="scribe-native-seconds",
        chunk_index=1,
        chunk_count=1,
        covered_segment_ids=["segment-1"],
        overview="A literal pricing question is present.",
        observations=[],
        uncertainties=["Synthetic speaker labels remain unverified."],
    )
    profile = load_report_profile()
    prepared = prepare_coaching_input(transcript, [fact_packet], profile=profile)
    profile_sha256 = hashlib.sha256(canonical(profile)).hexdigest()
    stage = _stage(
        stage="C5",
        provider_id="groq",
        model_id=prepared.model,
        recipe_revision=COACHING_RECIPE,
        profile_sha256=profile_sha256,
    )
    bundle = _bundle(stage)
    reservation = _reservation(
        bundle,
        provider_id="groq",
        provider_model=prepared.model,
        recipe_revision=COACHING_RECIPE,
        operation="extract_context_evidence",
        input_sha256=prepared.input_sha256,
        entitlement_seconds=0,
    )
    child = FakeChild()

    result = await _router({"bundle": bundle}, child).execute(reservation, prepared.payload)

    assert result.provider == "groq"
    assert child.calls == [(reservation, prepared.payload)]
    assert b"Profile:\\n" in prepared.payload
    assert str(profile["revision"]).encode() in prepared.payload


@pytest.mark.asyncio
async def test_unexpected_child_error_is_sanitized() -> None:
    child = UnexpectedFailureChild()
    bundle = _bundle()

    with pytest.raises(ProviderRouterError, match="broker_failed") as caught:
        await _router({"bundle": bundle}, child).execute(_reservation(bundle), SOURCE)

    assert "sk_live" not in repr(caught.value)


@pytest.mark.asyncio
async def test_stable_broker_error_is_preserved() -> None:
    child = StableFailureChild()
    bundle = _bundle()

    with pytest.raises(InferenceBrokerError, match="broker_timeout"):
        await _router({"bundle": bundle}, child).execute(_reservation(bundle), SOURCE)


@pytest.mark.asyncio
async def test_cancellation_is_not_converted_to_router_failure() -> None:
    child = CancellationChild()
    bundle = _bundle()

    with pytest.raises(asyncio.CancelledError):
        await _router({"bundle": bundle}, child).execute(_reservation(bundle), SOURCE)
