"""Fictional tenant policies preserve public artifacts and isolate processing."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from ac_platform.conversation_intelligence.activation_contract import (
    ActivationContractError,
    HostedApprovalBundle,
    load_hosted_approval_bundle,
)
from ac_platform.conversation_intelligence.application import (
    ConversationConflict,
    ConversationDenied,
)
from ac_platform.conversation_intelligence.authority import ConversationAuthority
from ac_platform.conversation_intelligence.broker_router import FixedProviderRouter
from ac_platform.conversation_intelligence.contracts import IntakeIntent
from ac_platform.conversation_intelligence.entitlements import (
    ExecutionPermission,
    Quote,
    Reservation,
)
from ac_platform.conversation_intelligence.processing_actor import ProcessingActor
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.conversation_intelligence.sales_xray_tenants import sales_xray_tenant_ids
from tests.unit.conversation_intelligence.test_acquisition_provider_policy import (
    SOURCE_SHA,
    TENANT_ID,
    _bundle,
    _paid_policy,
    _policy,
)
from tests.unit.conversation_intelligence.test_hosted_runtime import settings_for

CONTROL_ID = UUID("90000000-0000-4000-8000-000000000009")
ORG_ID = UUID("80000000-0000-4000-8000-000000000008")
ORG_PERSON_ID = UUID("70000000-0000-4000-8000-000000000007")


def organisation_bundle(*, organisation=None, public=True, **updates) -> HostedApprovalBundle:
    if organisation is None:
        organisation = _policy(
            id=uuid4(),
            tenant_id=ORG_ID,
            processing_person_id=ORG_PERSON_ID,
            max_source_bytes=100,
            max_stored_source_bytes=200,
            max_recordings=2,
            stages=tuple(
                stage.model_copy(update={"configuration_sha256": "e" * 64})
                for stage in _policy().stages
            ),
        )
    value = _bundle(_policy() if public else None).model_dump()
    value.update(
        provider_control_tenant_id=CONTROL_ID,
        organisation_acquisition_policies=(organisation,),
        **updates,
    )
    return HostedApprovalBundle(**value)


def test_staging_fixture_preserves_baseline_bytes_and_sha256() -> None:
    raw = Path("tests/fixtures/organisation_acquisition_legacy_staging.json").read_bytes()
    bundle = load_hosted_approval_bundle(raw)
    assert bundle.to_json() == raw
    assert bundle.digest == hashlib.sha256(raw).hexdigest()
    assert bundle.digest == "a1ba21d8c0e83cc694e389018d18239576812516f34a79e6fde260b38f7efe4a"
    assert "organisation_acquisition_policies" not in bundle.as_dict()
    assert load_hosted_approval_bundle(bundle.to_json()) == bundle


def test_organisation_roundtrip_lookup_and_unlisted_refusal() -> None:
    bundle = organisation_bundle()
    loaded = load_hosted_approval_bundle(bundle.to_json())
    assert loaded == bundle
    assert loaded.digest == bundle.digest
    assert loaded.acquisition_tenant_ids() == (TENANT_ID, ORG_ID)
    assert loaded.acquisition_policy_for(ORG_ID) == bundle.organisation_acquisition_policies[0]
    assert loaded.acquisition_policy_for(uuid4()) is None
    authority = ConversationAuthority(
        lambda: loaded, environment="test", operations_tenant_id=CONTROL_ID
    )
    actor = ProcessingActor(ORG_PERSON_ID, ORG_ID, uuid4())
    authority.recipient(loaded, actor)
    for invalid in (
        ProcessingActor(ORG_PERSON_ID, uuid4(), uuid4()),
        ProcessingActor(uuid4(), ORG_ID, uuid4()),
    ):
        with pytest.raises(ConversationDenied, match="no approved acquisition provider policy"):
            authority.recipient(loaded, invalid)
        assert (
            authority.stage_approval(loaded, invalid, source_sha256=SOURCE_SHA, stage="C2") is None
        )
    stage = authority.stage_approval(loaded, actor, source_sha256=SOURCE_SHA, stage="C2")
    assert stage is not None
    assert (stage.tenant_id, stage.person_id, stage.configuration_sha256) == (
        ORG_ID,
        ORG_PERSON_ID,
        "e" * 64,
    )
    assert (
        authority._approved_default_configuration_sha256(
            loaded, actor, source_sha256=SOURCE_SHA, stage="C2"
        )
        == "e" * 64
    )
    assert stage is not None
    ref = ExecutionPermission(
        authorization_ref=f"hosted-stage-v1:{stage.id}:{loaded.digest}",
        quote_fingerprint="a" * 64,
        approved_by=str(ORG_PERSON_ID),
        expires_at_epoch=1600,
    )
    assert (
        authority._configuration_from_permission(loaded, actor, SOURCE_SHA, "C2", ref) == "e" * 64
    )


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ("operations", "organisation_acquisition_tenant_invalid"),
        ("public", "organisation_acquisition_tenant_invalid"),
        ("duplicate_tenant", "duplicate_acquisition_tenant"),
        ("duplicate_person", "duplicate_acquisition_processing_person"),
        ("duplicate_organisation_person", "duplicate_acquisition_processing_person"),
        ("duplicate_id", "duplicate_approval_id"),
        ("expiry", "acquisition_policy_expiry_or_capacity_invalid"),
        ("capacity", "acquisition_policy_expiry_or_capacity_invalid"),
        ("stage_expiry", "acquisition_stage_expiry_outside_bundle"),
    ],
)
def test_organisation_policy_constraints(change, code) -> None:
    payload = organisation_bundle().as_dict()
    org = payload["organisation_acquisition_policies"][0]
    if change in {"operations", "public"}:
        org["tenant_id"] = (
            payload["provider_control_tenant_id"] if change == "operations" else str(TENANT_ID)
        )
    if change in {"duplicate_tenant", "duplicate_organisation_person"}:
        second = dict(org, id=str(uuid4()))
        second["processing_person_id" if change == "duplicate_tenant" else "tenant_id"] = str(
            uuid4()
        )
        payload["organisation_acquisition_policies"].append(second)
    if change == "duplicate_person":
        org["processing_person_id"] = payload["acquisition_policy"]["processing_person_id"]
    if change == "duplicate_id":
        org["id"] = payload["acquisition_policy"]["id"]
    if change == "expiry":
        org["expires_at_epoch"] = 2001
    if change == "capacity":
        org["max_stored_source_bytes"] = payload["max_stored_source_bytes"] + 1
    if change == "stage_expiry":
        org["stages"][0]["expires_at_epoch"] = 1000
    with pytest.raises(ActivationContractError, match=code):
        load_hosted_approval_bundle(payload)


def test_organisation_paid_checks_and_current_window() -> None:
    paid = _paid_policy().model_copy(
        update={"id": uuid4(), "tenant_id": ORG_ID, "processing_person_id": ORG_PERSON_ID}
    )
    with pytest.raises(ValueError, match="paid_project_cap_required"):
        organisation_bundle(organisation=paid)
    with pytest.raises(ValueError, match="paid_stage_cost_exceeds_project_cap"):
        organisation_bundle(
            organisation=paid, budget_cap_paise=1, paid_approval_ref="ref:approval/paid"
        )
    bundle = organisation_bundle(
        organisation=paid, budget_cap_paise=10000, paid_approval_ref="ref:approval/paid"
    )
    with pytest.raises(ActivationContractError, match="acquisition_policy_inactive"):
        bundle.current(1900, "test")


@pytest.mark.parametrize(
    ("count", "stored", "source_bytes", "refused"),
    [(1, 0, 100, False), (2, 0, 1, True), (0, 0, 101, True), (0, 200, 1, True)],
)
async def test_upload_uses_organisation_caps(count, stored, source_bytes, refused) -> None:
    bundle = organisation_bundle()
    database = SimpleNamespace(
        scalar=AsyncMock(return_value=0),
        execute=AsyncMock(side_effect=[None, SimpleNamespace(one=lambda: (count, stored))]),
    )
    app = SimpleNamespace(
        database=database, admit=AsyncMock(return_value=datetime.fromtimestamp(1100, UTC))
    )
    authority = ConversationAuthority(
        lambda: bundle, environment="test", operations_tenant_id=CONTROL_ID
    )
    intent = IntakeIntent(
        source_sha256=SOURCE_SHA,
        source_bytes=source_bytes,
        content_type="audio/mpeg",
        duration_ms=1000,
        purpose="internal_analysis",
    )
    call = authority.admit_upload(app, ProcessingActor(ORG_PERSON_ID, ORG_ID, uuid4()), intent)
    if refused:
        with pytest.raises(ConversationConflict, match="capacity is full"):
            await call
    else:
        await call
    assert database.execute.await_count == 2
    assert database.scalar.await_count == 1


def test_router_and_admin_resolve_organisation_policy() -> None:
    bundle = organisation_bundle()
    actor = ProcessingActor(ORG_PERSON_ID, ORG_ID, uuid4())
    stage = ConversationAuthority.stage_approval(
        bundle, actor, source_sha256=SOURCE_SHA, stage="C2"
    )
    from ac_platform.conversation_intelligence.checkpoints import SourceBinding

    quote = Quote(
        quote_id="fictional-org-quote",
        source=SourceBinding(str(ORG_ID), str(uuid4()), SOURCE_SHA, "1"),
        account_id=str(ORG_PERSON_ID),
        budget_scope_id=str(bundle.budget_scope_id),
        provider_id=stage.provider_id,
        provider_model=stage.model_id,
        recipe_revision=stage.recipe_revision,
        operation="transcribe_scribe_v2",
        input_sha256=SOURCE_SHA,
        provider_configuration_sha256=stage.configuration_sha256,
        privacy_revision=stage.privacy_revision,
        permission_ref=stage.permission_ref,
        provider_terms_ref=stage.provider_terms_ref,
        retention_ref=stage.retention_ref,
        professional_gate_ref=stage.professional_gate_ref,
        pricing_ref=stage.pricing_ref,
        entitlement_seconds=0,
        max_cost_paise=0,
        created_at_epoch=1100,
        expires_at_epoch=1600,
    )
    reservation = Reservation(
        reservation_id="fictional-org-reservation",
        quote=quote,
        permission=ExecutionPermission(
            authorization_ref=f"hosted-stage-v1:{stage.id}:{bundle.digest}",
            quote_fingerprint=quote.fingerprint,
            approved_by=str(ORG_PERSON_ID),
            expires_at_epoch=1600,
        ),
        state="in_flight",
        attempt_id="fictional-org-attempt",
    )
    assert FixedProviderRouter._stage(reservation, bundle) == stage
    candidates = ConversationProviderAdmin._approved_route(
        bundle,
        configuration_sha256="e" * 64,
        stage="C2",
        provider_id=stage.provider_id,
        model_id=stage.model_id,
        recipe_revision=stage.recipe_revision,
    )
    assert candidates == (bundle.organisation_acquisition_policies[0].stages[0],)


def test_composed_intake_and_workspace_directory_include_organisations(tmp_path) -> None:
    from ac_platform.conversation_intelligence.hosted_runtime import compose_hosted_intake

    now = int(datetime.now(UTC).timestamp())
    payload = organisation_bundle().as_dict()
    payload.update(issued_at_epoch=now - 1, expires_at_epoch=now + 3600)
    for policy in [payload["acquisition_policy"], *payload["organisation_acquisition_policies"]]:
        policy["expires_at_epoch"] = now + 3600
        for stage in policy["stages"]:
            stage["expires_at_epoch"] = now + 3600
    settings = settings_for(tmp_path, payload).model_copy(
        update={"public_learner_tenant_id": TENANT_ID}
    )
    runtime = compose_hosted_intake(settings)
    assert runtime.policy.tenant_ids == frozenset({TENANT_ID, ORG_ID})
    assert sales_xray_tenant_ids(settings, runtime) == frozenset({TENANT_ID, ORG_ID})
    assert CONTROL_ID not in sales_xray_tenant_ids(settings, runtime)
    with pytest.raises(ValueError, match="hosted_approval_unavailable"):
        compose_hosted_intake(settings.model_copy(update={"public_learner_tenant_id": ORG_ID}))


def current_payload(*, public=True, environment="test"):
    now = int(datetime.now(UTC).timestamp())
    payload = organisation_bundle(public=public).as_dict()
    payload.update(environment=environment, issued_at_epoch=now - 1, expires_at_epoch=now + 3600)
    policies = payload["organisation_acquisition_policies"]
    if public:
        policies = [payload["acquisition_policy"], *policies]
    for policy in policies:
        policy["expires_at_epoch"] = now + 3600
        for stage in policy["stages"]:
            stage["expires_at_epoch"] = now + 3600
    return payload


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_organisation_synthetic_routes_remain_test_only(tmp_path, environment) -> None:
    from ac_platform.conversation_intelligence.hosted_runtime import compose_hosted_intake

    payload = current_payload(public=False, environment=environment)
    settings = settings_for(tmp_path, payload).model_copy(update={"environment": environment})
    with pytest.raises(ValueError, match="hosted_approval_unavailable"):
        compose_hosted_intake(settings)
    bundle = load_hosted_approval_bundle(payload)
    authority = ConversationAuthority(
        lambda: bundle, environment=environment, operations_tenant_id=CONTROL_ID
    )
    with pytest.raises(ConversationDenied, match="configuration is unavailable"):
        authority.current(datetime.now(UTC))


def test_reporting_binds_organisation_only_credentials_and_refuses_bootstrap(monkeypatch) -> None:
    import ac_platform.conversation_intelligence.reporting_runtime as reporting
    from ac_platform.conversation_intelligence.inference_broker import InfisicalLauncher

    bundle = load_hosted_approval_bundle(current_payload(public=False))
    with pytest.raises(ValueError, match="worker_bootstrap_approval_not_empty"):
        reporting.validate_bootstrap_approval(bundle)
    authority = ConversationAuthority(
        lambda: bundle, environment="test", operations_tenant_id=CONTROL_ID
    )
    intake = SimpleNamespace(authority=authority, storage=object())
    monkeypatch.setattr(reporting, "compose_hosted_intake", lambda settings: intake)
    launchers = {
        f"ref:credential/{provider}/v1": InfisicalLauncher(
            executable="infisical",
            provider_id=provider,
            project_ref="fictional",
            environment_ref="test",
            secret_path_ref=f"/fictional/{provider}",
        )
        for provider in ("elevenlabs", "groq")
    }
    runtime = reporting.compose_hosted_reporting(object(), object(), launchers=launchers)
    assert runtime is not None
    assert set(runtime.inference.broker._routes) == {"elevenlabs", "groq"}
