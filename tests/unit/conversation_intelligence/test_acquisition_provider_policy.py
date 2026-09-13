from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from ac_platform.conversation_intelligence.activation_contract import (
    ACQUISITION_POLICY_SCHEMA,
    AcquisitionProviderPolicy,
    AcquisitionStagePolicy,
    HostedApprovalBundle,
)
from ac_platform.conversation_intelligence.application import ConversationDenied
from ac_platform.conversation_intelligence.authority import ConversationAuthority
from ac_platform.conversation_intelligence.broker_router import FixedProviderRouter
from ac_platform.conversation_intelligence.checkpoints import SourceBinding
from ac_platform.conversation_intelligence.entitlements import (
    ExecutionPermission,
    Quote,
    Reservation,
)
from ac_platform.conversation_intelligence.models import (
    ConversationBudgetAccount,
    ConversationMinuteAccount,
)
from ac_platform.conversation_intelligence.processing_actor import ProcessingActor
from ac_platform.kernel.authz import ActorContext

TENANT_ID = UUID("10000000-0000-4000-8000-000000000001")
PROCESSING_PERSON_ID = UUID("20000000-0000-4000-8000-000000000002")
CONTROL_PERSON_ID = UUID("30000000-0000-4000-8000-000000000003")
POLICY_ID = UUID("40000000-0000-4000-8000-000000000004")
SOURCE_SHA = "a" * 64


def _template(stage: str) -> AcquisitionStagePolicy:
    is_c2 = stage == "C2"
    return AcquisitionStagePolicy(
        stage=stage,  # type: ignore[arg-type]
        configuration_sha256="b" * 64,
        provider_id="elevenlabs" if is_c2 else "groq",
        model_id="scribe_v2" if is_c2 else "openai/gpt-oss-120b",
        recipe_revision="asr-v1" if is_c2 else ("facts-v1" if stage == "C4" else "coaching-v1"),
        permission_ref="ref:permission/acquisition-v1",
        retention_ref="ref:retention/acquisition-v1",
        professional_gate_ref="ref:professional/acquisition-v1",
        pricing_ref="ref:pricing/acquisition-v1",
        provider_terms_ref="ref:provider-terms/acquisition-v1",
        privacy_ref="ref:privacy/acquisition-v1",
        credential_ref=f"ref:credential/{'elevenlabs' if is_c2 else 'groq'}/v1",
        free_allowance_ref="ref:allowance/acquisition-v1",
        no_paid_overage_ref="ref:billing/acquisition-v1",
        privacy_revision="privacy-acquisition-v1",
        privacy_notice="Approved public acquisition test route.",
        expires_at_epoch=1_900,
        max_requests=3,
        entitlement_seconds=None if is_c2 else 0,
        zero_cost_basis="synthetic",
        price_evidence_sha256="c" * 64,
        max_source_duration_ms=14_400_000,
        max_input_bytes=134_217_728,
        max_completion_tokens=0 if is_c2 else 800,
        profile_sha256="d" * 64 if stage == "C5" else None,
    )


def _policy(**updates: object) -> AcquisitionProviderPolicy:
    values: dict[str, object] = {
        "schema": ACQUISITION_POLICY_SCHEMA,
        "id": POLICY_ID,
        "tenant_id": TENANT_ID,
        "processing_person_id": PROCESSING_PERSON_ID,
        "authorization_ref": "ref:acquisition/approval-v1",
        "expires_at_epoch": 1_900,
        "max_recordings": 4,
        "max_source_bytes": 134_217_728,
        "max_stored_source_bytes": 536_870_912,
        "stages": (_template("C2"), _template("C4"), _template("C5")),
    }
    values.update(updates)
    return AcquisitionProviderPolicy(**values)


def _bundle(policy: AcquisitionProviderPolicy | None = None) -> HostedApprovalBundle:
    return HostedApprovalBundle(
        schema="ac.sales-xray.hosted-approval/1",
        environment="test",
        provider_control_tenant_id=TENANT_ID,
        deployment_ref="ref:deployment/acquisition-v1",
        issued_at_epoch=1_000,
        expires_at_epoch=2_000,
        budget_scope_id=uuid4(),
        budget_authorization_ref="ref:budget/acquisition-v1",
        budget_owner_id=CONTROL_PERSON_ID,
        intake_authorization_ref="ref:intake/acquisition-v1",
        intake_retention_ref="ref:retention/acquisition-v1",
        retention_days=7,
        max_stored_source_bytes=1_073_741_824,
        allowances=(),
        stages=(),
        acquisition_policy=policy,
    )


def test_absent_policy_keeps_existing_canonical_bundle_bytes() -> None:
    bundle = _bundle()
    assert "acquisition_policy" not in bundle.as_dict()
    assert HostedApprovalBundle.model_validate_json(bundle.to_json()) == bundle


def test_policy_derives_exact_source_and_principal_bound_stage() -> None:
    policy = _policy()
    first = policy.derive_stage(
        tenant_id=TENANT_ID,
        person_id=PROCESSING_PERSON_ID,
        source_sha256=SOURCE_SHA,
        stage="C2",
    )
    second = policy.derive_stage(
        tenant_id=TENANT_ID,
        person_id=PROCESSING_PERSON_ID,
        source_sha256=SOURCE_SHA,
        stage="C2",
    )
    assert first.id == second.id
    assert first.source_sha256 == SOURCE_SHA
    assert first.configuration_sha256 == policy.stages[0].configuration_sha256
    with pytest.raises(ValueError, match="acquisition_policy_scope_mismatch"):
        policy.derive_stage(
            tenant_id=TENANT_ID,
            person_id=UUID("20000000-0000-4000-8000-000000000099"),
            source_sha256=SOURCE_SHA,
            stage="C2",
        )


def test_only_matching_processing_actor_can_select_policy() -> None:
    bundle = _bundle(_policy())
    actor = ProcessingActor(PROCESSING_PERSON_ID, TENANT_ID, uuid4())
    approval = ConversationAuthority.stage_approval(
        bundle, actor, source_sha256=SOURCE_SHA, stage="C2"
    )
    assert approval is not None
    ordinary = ActorContext(PROCESSING_PERSON_ID, uuid4(), TENANT_ID)
    assert (
        ConversationAuthority.stage_approval(bundle, ordinary, source_sha256=SOURCE_SHA, stage="C2")
        is None
    )
    with pytest.raises(ConversationDenied):
        ConversationAuthority(
            lambda: bundle, environment="test", operations_tenant_id=TENANT_ID
        ).recipient(bundle, ProcessingActor(uuid4(), TENANT_ID, uuid4()))


@pytest.mark.asyncio
async def test_processing_actor_initializes_shared_budget_without_minute_grant() -> None:
    class _Application:
        def __init__(self) -> None:
            self.database = MagicMock()
            self.database.execute = AsyncMock(return_value=None)
            self.database.scalar = AsyncMock(return_value=None)
            self.database.add = MagicMock()
            self.database.flush = AsyncMock(return_value=None)

        async def admit(self, _: ProcessingActor) -> datetime:
            return datetime.fromtimestamp(1_100, UTC)

    bundle = _bundle(_policy())
    app = _Application()
    authority = ConversationAuthority(
        lambda: bundle, environment="test", operations_tenant_id=TENANT_ID
    )

    await authority.claim_allowance(
        app,
        ProcessingActor(PROCESSING_PERSON_ID, TENANT_ID, uuid4()),
    )

    added = [call.args[0] for call in app.database.add.call_args_list]
    assert [item for item in added if isinstance(item, ConversationBudgetAccount)]
    assert not any(isinstance(item, ConversationMinuteAccount) for item in added)


def test_policy_expiry_and_stage_configuration_are_bound() -> None:
    with pytest.raises(ValueError, match="acquisition_policy_expiry_or_capacity_invalid"):
        _bundle(_policy(expires_at_epoch=2_001))
    changed_c2 = _template("C2").model_copy(update={"configuration_sha256": "e" * 64})
    changed = _policy(stages=(changed_c2, _template("C4"), _template("C5")))
    assert changed.stages[0].configuration_sha256 == "e" * 64
    assert _bundle(changed).acquisition_policy == changed


def test_current_rejects_an_expired_acquisition_policy_before_stage_selection() -> None:
    policy = _policy(
        expires_at_epoch=1_500,
        stages=tuple(
            item.model_copy(update={"expires_at_epoch": 1_400})
            for item in (_template("C2"), _template("C4"), _template("C5"))
        ),
    )
    with pytest.raises(ValueError, match="acquisition_policy_inactive"):
        _bundle(policy).current(1_500, "test")


def test_router_recomputes_policy_stage_from_exact_source_binding() -> None:
    policy = _policy()
    bundle = _bundle(policy)
    template = policy.stages[0]
    quote = Quote(
        quote_id="quote-acquisition-policy-v1",
        source=SourceBinding(str(TENANT_ID), str(uuid4()), SOURCE_SHA, "1"),
        account_id=str(PROCESSING_PERSON_ID),
        budget_scope_id=str(bundle.budget_scope_id),
        provider_id=template.provider_id,
        provider_model=template.model_id,
        recipe_revision=template.recipe_revision,
        operation="transcribe_scribe_v2",
        input_sha256=SOURCE_SHA,
        privacy_revision=template.privacy_revision,
        permission_ref=template.permission_ref,
        provider_terms_ref=template.provider_terms_ref,
        retention_ref=template.retention_ref,
        professional_gate_ref=template.professional_gate_ref,
        pricing_ref=template.pricing_ref,
        entitlement_seconds=0,
        max_cost_paise=0,
        created_at_epoch=1_100,
        expires_at_epoch=1_600,
    )
    approval_id = policy.derive_stage(
        tenant_id=TENANT_ID,
        person_id=PROCESSING_PERSON_ID,
        source_sha256=SOURCE_SHA,
        stage="C2",
    ).id
    reservation = Reservation(
        reservation_id="reservation-acquisition-policy-v1",
        quote=quote,
        permission=ExecutionPermission(
            authorization_ref=f"hosted-stage-v1:{approval_id}:{bundle.digest}",
            quote_fingerprint=quote.fingerprint,
            approved_by=str(PROCESSING_PERSON_ID),
            expires_at_epoch=1_600,
        ),
        state="in_flight",
        attempt_id="attempt-acquisition-policy-v1",
    )
    resolved = FixedProviderRouter._stage(reservation, bundle)
    assert resolved.id == approval_id
    assert resolved.source_sha256 == SOURCE_SHA
