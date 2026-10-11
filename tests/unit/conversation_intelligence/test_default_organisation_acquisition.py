"""Default organisation processing reuses sealed routes without granting access."""

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence.application import (
    ConversationConflict,
    ConversationDenied,
)
from ac_platform.conversation_intelligence.authority import ConversationAuthority
from ac_platform.conversation_intelligence.broker_router import (
    FixedProviderRouter,
    ProviderRoute,
    ProviderRouterError,
)
from ac_platform.conversation_intelligence.checkpoints import SourceBinding
from ac_platform.conversation_intelligence.contracts import IntakeIntent
from ac_platform.conversation_intelligence.entitlements import (
    ExecutionPermission,
    Quote,
    Reservation,
)
from ac_platform.conversation_intelligence.processing_actor import ProcessingActor
from tests.unit.conversation_intelligence.test_acquisition_provider_policy import SOURCE_SHA
from tests.unit.conversation_intelligence.test_broker_router import FakeChild
from tests.unit.conversation_intelligence.test_organisation_acquisition_policies import (
    CONTROL_ID,
    ORG_ID,
    ORG_PERSON_ID,
    TENANT_ID,
    organisation_bundle,
)


def test_default_preserves_template_limits_routes_and_legacy_approval_bytes():
    bundle = organisation_bundle()
    raw, digest = bundle.to_json(), bundle.digest
    tenant_id = uuid4()
    # An operator/exact-policy lookup remains explicit. A runtime must first
    # prove the registry and processing lease before requesting the default.
    assert bundle.acquisition_policy_for(tenant_id) is None
    policy = bundle.acquisition_policy_for(tenant_id, registered_organisation=True)
    template = bundle.organisation_acquisition_policies[0]
    assert policy is not None and policy.tenant_id == tenant_id
    assert policy.max_recordings == 2000
    assert (policy.max_source_bytes, policy.max_stored_source_bytes) == (
        template.max_source_bytes,
        template.max_stored_source_bytes,
    )
    assert policy.stage_sets() == template.stage_sets()
    assert policy.expires_at_epoch == template.expires_at_epoch
    assert policy.authorization_ref == template.authorization_ref
    assert bundle.to_json() == raw and bundle.digest == digest
    assert bundle.acquisition_policy_for(ORG_ID, registered_organisation=True) == template
    assert (
        bundle.acquisition_policy_for(
            ORG_ID, registered_organisation=True, processing_person_id=uuid4()
        )
        == template
    )
    assert (
        bundle.acquisition_policy_for(TENANT_ID, registered_organisation=True)
        == bundle.acquisition_policy
    )
    assert bundle.acquisition_policy_for(CONTROL_ID, registered_organisation=True) is None


def test_default_principals_are_distinct_and_stable_across_resealing():
    bundle = organisation_bundle()
    first, second = uuid4(), uuid4()
    policy = bundle.acquisition_policy_for(first, registered_organisation=True)
    other = bundle.acquisition_policy_for(second, registered_organisation=True)
    assert policy.processing_person_id != other.processing_person_id
    assert policy.processing_person_id != ORG_PERSON_ID
    replacement = bundle.organisation_acquisition_policies[0].model_copy(update={"id": uuid4()})
    resealed = organisation_bundle(organisation=replacement)
    assert (
        resealed.acquisition_policy_for(first, registered_organisation=True).processing_person_id
        == policy.processing_person_id
    )


@pytest.mark.parametrize("registered", [False, True])
async def test_authority_requires_live_registry_before_accepting_default(registered):
    bundle = organisation_bundle()
    tenant_id = uuid4()
    policy = bundle.acquisition_policy_for(tenant_id, registered_organisation=True)
    actor = ProcessingActor(policy.processing_person_id, tenant_id, uuid4())
    app = SimpleNamespace(
        admit=AsyncMock(return_value=datetime.fromtimestamp(1100, UTC)),
        database=SimpleNamespace(
            scalar=AsyncMock(return_value=actor.person_id if registered else None)
        ),
    )
    authority = ConversationAuthority(
        lambda: bundle, environment="test", operations_tenant_id=CONTROL_ID
    )
    if not registered:
        with pytest.raises(ConversationDenied, match="active registered organisation"):
            await authority.admit(app, actor)
    else:
        assert await authority.admit(app, actor) == bundle
        stage = authority.stage_approval(bundle, actor, source_sha256=SOURCE_SHA, stage="C2")
        assert (stage.tenant_id, stage.person_id) == (tenant_id, policy.processing_person_id)
        app.database.scalar.return_value = uuid4()
        with pytest.raises(ConversationDenied, match="its processing principal"):
            await authority.admit(app, ProcessingActor(ORG_PERSON_ID, tenant_id, uuid4()))


def test_personal_template_can_supply_routes_when_no_organisation_override_is_sealed():
    bundle = organisation_bundle().model_copy(update={"organisation_acquisition_policies": ()})
    policy = bundle.acquisition_policy_for(uuid4(), registered_organisation=True)
    assert policy.stage_sets() == bundle.acquisition_policy.stage_sets()
    assert policy.max_recordings == 2000


def test_default_keeps_canonical_existing_principal_without_changing_sealed_bytes():
    bundle = organisation_bundle()
    raw = bundle.to_json()
    tenant_id, person_id = uuid4(), uuid4()
    policy = bundle.acquisition_policy_for(
        tenant_id, registered_organisation=True, processing_person_id=person_id
    )
    assert policy.processing_person_id == person_id
    assert policy.max_recordings == 2000 and bundle.to_json() == raw
    assert (
        bundle.acquisition_policy_for(
            tenant_id, registered_organisation=True, processing_person_id=ORG_PERSON_ID
        )
        is None
    )
    with pytest.raises(ValueError, match="organisation_processing_principal_invalid"):
        bundle.acquisition_policy_for(
            tenant_id, registered_organisation=True, processing_person_id="untrusted-value"
        )


def default_reservation(bundle, tenant_id, stage_name, source_sha):
    policy = bundle.acquisition_policy_for(tenant_id, registered_organisation=True)
    actor = ProcessingActor(policy.processing_person_id, tenant_id, uuid4())
    stage = ConversationAuthority.stage_approval(
        bundle, actor, source_sha256=source_sha, stage=stage_name
    )
    quote = Quote(
        quote_id="fictional-default-org-quote",
        source=SourceBinding(str(tenant_id), str(uuid4()), source_sha, "1"),
        account_id=str(actor.person_id),
        budget_scope_id=str(bundle.budget_scope_id),
        provider_id=stage.provider_id,
        provider_model=stage.model_id,
        recipe_revision=stage.recipe_revision,
        operation="transcribe_scribe_v2" if stage_name == "C2" else "extract_context_evidence",
        input_sha256=source_sha,
        provider_configuration_sha256=stage.configuration_sha256,
        privacy_revision=stage.privacy_revision,
        permission_ref=stage.permission_ref,
        provider_terms_ref=stage.provider_terms_ref,
        retention_ref=stage.retention_ref,
        professional_gate_ref=stage.professional_gate_ref,
        pricing_ref=stage.pricing_ref,
        entitlement_seconds=0,
        max_cost_paise=stage.max_cost_paise,
        created_at_epoch=1100,
        expires_at_epoch=1600,
    )
    reservation = Reservation(
        reservation_id="fictional-default-org-reservation",
        quote=quote,
        permission=ExecutionPermission(
            authorization_ref=f"hosted-stage-v1:{stage.id}:{bundle.digest}",
            quote_fingerprint=quote.fingerprint,
            approved_by=quote.account_id,
            expires_at_epoch=1600,
        ),
        state="in_flight",
        attempt_id="fictional-default-org-attempt",
    )
    return stage, reservation


@pytest.mark.parametrize("stage_name", ["C2", "C4", "C5"])
def test_default_stages_reach_router_with_exact_org_source_binding(stage_name):
    bundle = organisation_bundle()
    tenant_id = uuid4()
    stage, reservation = default_reservation(bundle, tenant_id, stage_name, SOURCE_SHA)
    assert FixedProviderRouter._stage(reservation, bundle) == stage
    assert stage.configuration_sha256 == "e" * 64
    for forged_quote in (
        replace(reservation.quote, account_id=str(uuid4())),
        replace(
            reservation.quote,
            source=replace(reservation.quote.source, tenant_id=str(uuid4())),
        ),
    ):
        forged = replace(
            reservation,
            quote=forged_quote,
            permission=replace(
                reservation.permission,
                quote_fingerprint=forged_quote.fingerprint,
                approved_by=forged_quote.account_id,
            ),
        )
        candidate = FixedProviderRouter._stage(forged, bundle)
        assert candidate.id != stage.id
        assert forged.permission.authorization_ref != (
            f"hosted-stage-v1:{candidate.id}:{bundle.digest}"
        )


async def test_default_router_dispatches_only_with_matching_signed_permission():
    bundle = organisation_bundle()
    source = b"fictional default organisation audio"
    source_sha = hashlib.sha256(source).hexdigest()
    stage, reservation = default_reservation(bundle, uuid4(), "C2", source_sha)
    child = FakeChild()
    router = FixedProviderRouter(
        {stage.provider_id: ProviderRoute(stage.provider_id, stage.credential_ref, child)},
        authority=ConversationAuthority(
            lambda: bundle, environment="test", operations_tenant_id=CONTROL_ID
        ),
        clock=lambda: datetime.fromtimestamp(1100, UTC),
    )
    result = await router.execute(reservation, source)
    assert result.provider == stage.provider_id and len(child.calls) == 1
    other_stage, _ = default_reservation(bundle, uuid4(), "C2", source_sha)
    forged = replace(
        reservation,
        permission=replace(
            reservation.permission,
            authorization_ref=f"hosted-stage-v1:{other_stage.id}:{bundle.digest}",
        ),
    )
    with pytest.raises(ProviderRouterError, match="broker_router_authorization_mismatch"):
        await router.execute(forged, source)
    for forged_quote in (
        replace(reservation.quote, account_id=str(ORG_PERSON_ID)),
        replace(
            reservation.quote, source=replace(reservation.quote.source, tenant_id=str(uuid4()))
        ),
    ):
        forged = replace(
            reservation,
            quote=forged_quote,
            permission=replace(
                reservation.permission,
                quote_fingerprint=forged_quote.fingerprint,
                approved_by=forged_quote.account_id,
            ),
        )
        with pytest.raises(
            ProviderRouterError, match="broker_router_(authorization|route)_mismatch"
        ):
            await router.execute(forged, source)
    assert len(child.calls) == 1


@pytest.mark.parametrize("limit", ["count", "source", "organisation_storage", "shared_storage"])
async def test_default_organisation_keeps_every_storage_and_count_limit(limit):
    bundle = organisation_bundle()
    tenant_id = uuid4()
    policy = bundle.acquisition_policy_for(tenant_id, registered_organisation=True)
    actor = ProcessingActor(policy.processing_person_id, tenant_id, uuid4())
    database = SimpleNamespace(
        scalar=AsyncMock(
            side_effect=[
                actor.person_id,
                bundle.max_stored_source_bytes if limit == "shared_storage" else 0,
            ]
        ),
        execute=AsyncMock(
            side_effect=[
                None,
                SimpleNamespace(
                    one=lambda: (
                        2000 if limit == "count" else 0,
                        policy.max_stored_source_bytes if limit == "organisation_storage" else 0,
                    )
                ),
            ]
        ),
    )
    app = SimpleNamespace(
        database=database, admit=AsyncMock(return_value=datetime.fromtimestamp(1100, UTC))
    )
    authority = ConversationAuthority(
        lambda: bundle, environment="test", operations_tenant_id=CONTROL_ID
    )
    intent = IntakeIntent(
        source_sha256=SOURCE_SHA,
        source_bytes=policy.max_source_bytes + 1 if limit == "source" else 1,
        content_type="audio/wav",
        duration_ms=1000,
        purpose="internal_analysis",
    )
    with pytest.raises(ConversationConflict, match="recording capacity is full"):
        await authority.admit_upload(app, actor, intent)
