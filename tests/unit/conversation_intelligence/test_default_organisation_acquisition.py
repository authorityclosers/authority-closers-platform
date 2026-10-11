"""Default organisation processing reuses sealed routes without granting access."""

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
from ac_platform.conversation_intelligence.contracts import IntakeIntent
from ac_platform.conversation_intelligence.processing_actor import ProcessingActor
from tests.unit.conversation_intelligence.test_acquisition_provider_policy import SOURCE_SHA
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
        database=SimpleNamespace(scalar=AsyncMock(return_value=tenant_id if registered else None)),
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
        with pytest.raises(ConversationDenied, match="approved acquisition provider policy"):
            authority.recipient(bundle, ProcessingActor(ORG_PERSON_ID, tenant_id, uuid4()))


def test_personal_template_can_supply_routes_when_no_organisation_override_is_sealed():
    bundle = organisation_bundle().model_copy(update={"organisation_acquisition_policies": ()})
    policy = bundle.acquisition_policy_for(uuid4(), registered_organisation=True)
    assert policy.stage_sets() == bundle.acquisition_policy.stage_sets()
    assert policy.max_recordings == 2000


@pytest.mark.parametrize("limit", ["count", "source", "organisation_storage", "shared_storage"])
async def test_default_organisation_keeps_every_storage_and_count_limit(limit):
    bundle = organisation_bundle()
    tenant_id = uuid4()
    policy = bundle.acquisition_policy_for(tenant_id, registered_organisation=True)
    actor = ProcessingActor(policy.processing_person_id, tenant_id, uuid4())
    database = SimpleNamespace(
        scalar=AsyncMock(
            side_effect=[
                tenant_id,
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
