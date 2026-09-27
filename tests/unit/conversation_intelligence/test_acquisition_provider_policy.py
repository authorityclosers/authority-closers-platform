from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from ac_platform.conversation_intelligence.activation_contract import (
    ACQUISITION_POLICY_SCHEMA,
    AcquisitionProviderPolicy,
    AcquisitionProviderProfile,
    AcquisitionStagePolicy,
    AllowanceApproval,
    HostedApprovalBundle,
    InternalTesterApproval,
    StageCallSupplement,
)
from ac_platform.conversation_intelligence.application import ConversationDenied
from ac_platform.conversation_intelligence.authority import ConversationAuthority
from ac_platform.conversation_intelligence.broker_router import FixedProviderRouter
from ac_platform.conversation_intelligence.checkpoints import SourceBinding, canonical
from ac_platform.conversation_intelligence.contracts import IntakeIntent
from ac_platform.conversation_intelligence.entitlements import (
    ExecutionPermission,
    Quote,
    Reservation,
)
from ac_platform.conversation_intelligence.internal_tester import InternalTesterPolicy
from ac_platform.conversation_intelligence.limits import MAX_AUDIO_BYTES
from ac_platform.conversation_intelligence.models import (
    ConversationBudgetAccount,
    ConversationMinuteAccount,
)
from ac_platform.conversation_intelligence.processing_actor import ProcessingActor
from ac_platform.conversation_intelligence.stage_supplement_cli import (
    CommandError as SupplementCommandError,
)
from ac_platform.conversation_intelligence.stage_supplement_cli import (
    main as supplement_cli_main,
)
from ac_platform.conversation_intelligence.stage_supplement_cli import (
    prepare_bundle,
)
from ac_platform.conversation_intelligence.stage_supplements import (
    StageSupplementContext,
    matches_stage_supplement,
    processing_plan_sha256,
    supplemental_reservations,
)
from ac_platform.kernel.authz import ActorContext

TENANT_ID = UUID("10000000-0000-4000-8000-000000000001")
PROCESSING_PERSON_ID = UUID("20000000-0000-4000-8000-000000000002")
CONTROL_PERSON_ID = UUID("30000000-0000-4000-8000-000000000003")
POLICY_ID = UUID("40000000-0000-4000-8000-000000000004")
SOURCE_SHA = "a" * 64
SUPPLEMENT_OWNER_ID = UUID("70000000-0000-4000-8000-000000000007")
LEGACY_DESCRIPTOR_MAX_BYTES = 128 * 1024 * 1024


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
        max_input_bytes=MAX_AUDIO_BYTES,
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
        "max_source_bytes": MAX_AUDIO_BYTES,
        "max_stored_source_bytes": 536_870_912,
        "stages": (_template("C2"), _template("C4"), _template("C5")),
    }
    values.update(updates)
    return AcquisitionProviderPolicy(**values)


def _gemini_profile() -> AcquisitionProviderProfile:
    configuration_sha256 = "e" * 64
    stages = (
        _template("C2").model_copy(update={"configuration_sha256": configuration_sha256}),
        _template("C4").model_copy(
            update={
                "configuration_sha256": configuration_sha256,
                "provider_id": "gemini",
                "model_id": "gemini-3.1-pro-preview",
            }
        ),
        _template("C5").model_copy(
            update={
                "configuration_sha256": configuration_sha256,
                "provider_id": "gemini",
                "model_id": "gemini-3.1-pro-preview",
            }
        ),
    )
    return AcquisitionProviderProfile(profile_id="gemini-31-pro", stages=stages)


def _bundle(
    policy: AcquisitionProviderPolicy | None = None,
    *,
    budget_cap_paise: int = 0,
    paid_approval_ref: str | None = None,
    stage_call_supplements: tuple[StageCallSupplement, ...] = (),
) -> HostedApprovalBundle:
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
        budget_cap_paise=budget_cap_paise,
        paid_approval_ref=paid_approval_ref,
        intake_authorization_ref="ref:intake/acquisition-v1",
        intake_retention_ref="ref:retention/acquisition-v1",
        retention_days=7,
        max_stored_source_bytes=1_073_741_824,
        allowances=(),
        stages=(),
        acquisition_policy=policy,
        stage_call_supplements=stage_call_supplements,
    )


def _paid_policy() -> AcquisitionProviderPolicy:
    stages = tuple(
        _template(stage).model_copy(
            update={
                **(
                    {
                        "zero_cost_basis": "paid_pricing_evidence",
                        "max_cost_paise": 2_200,
                        "free_allowance_ref": None,
                    }
                    if stage == "C5"
                    else {}
                ),
                **({"recipe_revision": "qualitative-coaching-v1"} if stage == "C5" else {}),
            }
        )
        for stage in ("C2", "C4", "C5")
    )
    return _policy(stages=stages)


def _stage_supplement(
    policy: AcquisitionProviderPolicy,
    *,
    source_sha256: str = SOURCE_SHA,
    owner_person_id: UUID = SUPPLEMENT_OWNER_ID,
    configuration_sha256: str = "b" * 64,
    processing_plan_sha256: str = "f" * 64,
    prepared_input_sha256: str = "1" * 64,
    expires_at_epoch: int = 1_800,
) -> StageCallSupplement:
    approval = policy.derive_stage(
        tenant_id=TENANT_ID,
        person_id=PROCESSING_PERSON_ID,
        source_sha256=source_sha256,
        stage="C5",
        configuration_sha256=configuration_sha256,
    )
    return StageCallSupplement(
        id=uuid4(),
        authorization_ref="ref:test/approved-marathi-plan",
        base_approval_id=approval.id,
        tenant_id=TENANT_ID,
        processing_person_id=PROCESSING_PERSON_ID,
        owner_person_id=owner_person_id,
        source_sha256=source_sha256,
        configuration_sha256=configuration_sha256,
        stage="C5",
        recipe_revision="qualitative-coaching-v1",
        coaching_prompt_revision="coaching-v4",
        report_language="mr-Deva+en",
        processing_plan_sha256=processing_plan_sha256,
        prepared_input_sha256=prepared_input_sha256,
        issued_at_epoch=1_100,
        expires_at_epoch=expires_at_epoch,
        max_additional_requests=2,
        max_cost_per_request_paise=2_200,
        max_aggregate_cost_paise=4_400,
    )


def test_absent_policy_keeps_existing_canonical_bundle_bytes() -> None:
    bundle = _bundle()
    assert "acquisition_policy" not in bundle.as_dict()
    assert "stage_call_supplements" not in bundle.as_dict()
    assert HostedApprovalBundle.model_validate_json(bundle.to_json()) == bundle


def test_source_supplement_is_hash_pinned_without_changing_base_policy_or_counter() -> None:
    policy = _paid_policy()
    supplement = _stage_supplement(policy)
    bundle = _bundle(
        policy,
        budget_cap_paise=10_000,
        paid_approval_ref="ref:budget/test-approved",
        stage_call_supplements=(supplement,),
    )

    before = policy.derive_stage(
        tenant_id=TENANT_ID,
        person_id=PROCESSING_PERSON_ID,
        source_sha256=SOURCE_SHA,
        stage="C5",
    )
    after = bundle.acquisition_policy.derive_stage(
        tenant_id=TENANT_ID,
        person_id=PROCESSING_PERSON_ID,
        source_sha256=SOURCE_SHA,
        stage="C5",
    )
    restored = HostedApprovalBundle.model_validate_json(bundle.to_json())

    assert after.id == before.id == supplement.base_approval_id
    assert restored == bundle
    assert "stage_call_supplements" in bundle.as_dict()
    assert bundle.digest != bundle.model_copy(update={"stage_call_supplements": ()}).digest


def test_supplement_model_and_runtime_reject_production_activation() -> None:
    policy = _paid_policy()
    supplement = _stage_supplement(policy)
    candidate = {
        **_bundle(
            policy,
            budget_cap_paise=10_000,
            paid_approval_ref="ref:budget/test-approved",
        ).as_dict(),
        "environment": "production",
        "stage_call_supplements": [supplement.model_dump(mode="json")],
    }
    with pytest.raises(ValueError, match="stage_supplements_not_approved_for_production"):
        HostedApprovalBundle.model_validate_json(canonical(candidate))

    valid_test_bundle = _bundle(
        policy,
        budget_cap_paise=10_000,
        paid_approval_ref="ref:budget/test-approved",
        stage_call_supplements=(supplement,),
    )
    spoofed = valid_test_bundle.model_copy(update={"environment": "production"})
    authority = ConversationAuthority(
        lambda: spoofed, environment="production", operations_tenant_id=TENANT_ID
    )
    with pytest.raises(ConversationDenied, match="processing configuration is unavailable"):
        authority.current(datetime.fromtimestamp(1_200, UTC))


def test_supplement_contract_rejects_duplicate_plan_and_excess_cost() -> None:
    policy = _paid_policy()
    first = _stage_supplement(policy)
    duplicate = first.model_copy(update={"id": uuid4()})
    with pytest.raises(ValueError, match="duplicate_stage_supplement_scope"):
        _bundle(
            policy,
            budget_cap_paise=10_000,
            paid_approval_ref="ref:budget/test-approved",
            stage_call_supplements=(first, duplicate),
        )
    with pytest.raises(ValueError, match="stage_supplement_aggregate_exceeds_request_cap"):
        StageCallSupplement.model_validate(
            {
                **first.model_dump(),
                "max_additional_requests": 1,
                "max_aggregate_cost_paise": 4_400,
            }
        )


def test_supplement_matches_exact_owner_source_route_plan_and_window() -> None:
    policy = _paid_policy()
    supplement = _stage_supplement(policy)
    approval = policy.derive_stage(
        tenant_id=TENANT_ID,
        person_id=PROCESSING_PERSON_ID,
        source_sha256=SOURCE_SHA,
        stage="C5",
        configuration_sha256="b" * 64,
    )
    context = StageSupplementContext(
        tenant_id=TENANT_ID,
        processing_person_id=PROCESSING_PERSON_ID,
        owner_person_id=supplement.owner_person_id,
        source_sha256=SOURCE_SHA,
        configuration_sha256="b" * 64,
        stage="C5",
        recipe_revision="qualitative-coaching-v1",
        coaching_prompt_revision="coaching-v4",
        report_language="mr-Deva+en",
        processing_plan_sha256="f" * 64,
        prepared_input_sha256="1" * 64,
    )

    assert matches_stage_supplement(supplement, approval, context, now_epoch=1_200)
    for field, value in (
        ("owner_person_id", UUID("70000000-0000-4000-8000-000000000099")),
        ("source_sha256", "9" * 64),
        ("configuration_sha256", "8" * 64),
        ("recipe_revision", "different-recipe"),
        ("coaching_prompt_revision", "coaching-v3"),
        ("report_language", "hi-Deva+en"),
        ("processing_plan_sha256", "e" * 64),
        ("prepared_input_sha256", "2" * 64),
    ):
        assert not matches_stage_supplement(
            supplement, approval, replace(context, **{field: value}), now_epoch=1_200
        )
    assert not matches_stage_supplement(supplement, approval, context, now_epoch=1_099)
    assert not matches_stage_supplement(supplement, approval, context, now_epoch=1_800)


def test_supplement_plan_fingerprint_ignores_only_release_and_ephemeral_fields() -> None:
    manifest = {
        "authority_sha256": "a" * 64,
        "created_at_epoch": 1_000,
        "expires_at_epoch": 2_000,
        "session_id": "session-a",
        "processing_lease_id": "lease-a",
        "continuation_grant_id": "grant-a",
        "tenant_id": str(TENANT_ID),
        "person_id": str(PROCESSING_PERSON_ID),
        "source_sha256": SOURCE_SHA,
        "coaching_prompt_revision": "coaching-v4",
        "report_language": "mr-Deva+en",
        "profile": {"revision": "profile-v1"},
    }
    initial = processing_plan_sha256(manifest)
    renewed = processing_plan_sha256(
        {
            **manifest,
            "authority_sha256": "b" * 64,
            "created_at_epoch": 1_300,
            "expires_at_epoch": 2_300,
            "session_id": "session-b",
            "processing_lease_id": "lease-b",
            "continuation_grant_id": "grant-b",
        }
    )

    assert renewed == initial
    assert processing_plan_sha256({**manifest, "report_language": "en"}) != initial
    assert processing_plan_sha256({**manifest, "profile": {"revision": "profile-v2"}}) != initial


def test_supplemental_reservations_preserve_historical_holds_and_consume_only_two_extras() -> None:
    def reservation(paise: int) -> SimpleNamespace:
        return SimpleNamespace(quote=SimpleNamespace(max_cost_paise=paise))

    historical = (reservation(2_200), reservation(2_200))
    first_extra = (*historical, reservation(2_200))
    second_extra = (*first_extra, reservation(2_200))

    assert supplemental_reservations(historical, base_max_requests=2) == (0, 0)
    assert supplemental_reservations(first_extra, base_max_requests=2) == (1, 2_200)
    assert supplemental_reservations(second_extra, base_max_requests=2) == (2, 4_400)


def test_supplement_cli_prepares_one_new_bundle_without_activation(tmp_path, capsys) -> None:
    policy = _paid_policy()
    base = _bundle(
        policy,
        budget_cap_paise=10_000,
        paid_approval_ref="ref:budget/test-approved",
    )
    supplement = _stage_supplement(policy)
    bundle_path = tmp_path / "base.json"
    supplement_path = tmp_path / "supplement.json"
    output_path = tmp_path / "prepared.json"
    bundle_path.write_bytes(base.to_json())
    supplement_path.write_text(supplement.model_dump_json(), encoding="utf-8")

    assert (
        supplement_cli_main(
            [
                "--bundle",
                str(bundle_path),
                "--supplement",
                str(supplement_path),
                "--out",
                str(output_path),
            ]
        )
        == 2
    )  # The fixture grant is historical relative to the wall clock.
    assert not output_path.exists()

    prepared = prepare_bundle(
        base.to_json(),
        supplement.model_dump_json().encode(),
        now_epoch=1_200,
    )
    restored = HostedApprovalBundle.model_validate_json(prepared)
    assert restored.stage_call_supplements == (supplement,)
    assert restored.acquisition_policy == base.acquisition_policy
    assert restored.stages == base.stages

    output_path.write_bytes(prepared)
    before = output_path.read_bytes()
    assert (
        supplement_cli_main(
            [
                "--bundle",
                str(bundle_path),
                "--supplement",
                str(supplement_path),
                "--out",
                str(output_path),
            ]
        )
        == 2
    )
    assert output_path.read_bytes() == before
    assert "70000000-0000" not in capsys.readouterr().out


def test_supplement_cli_rejects_duplicate_keys_and_inactive_grant() -> None:
    policy = _paid_policy()
    base = _bundle(
        policy,
        budget_cap_paise=10_000,
        paid_approval_ref="ref:budget/test-approved",
    )
    supplement = _stage_supplement(policy)
    with pytest.raises(SupplementCommandError, match="bounded grant contract"):
        prepare_bundle(base.to_json(), b'{"id":"first","id":"second"}', now_epoch=1_200)
    with pytest.raises(SupplementCommandError, match="must be active"):
        prepare_bundle(
            base.to_json(),
            supplement.model_dump_json().encode(),
            now_epoch=1_800,
        )


def test_supplement_cli_refuses_production_bundle(tmp_path, capsys) -> None:
    now = int(datetime.now(UTC).timestamp())
    policy = _paid_policy()
    policy = policy.model_copy(
        update={
            "expires_at_epoch": now + 3_000,
            "stages": tuple(
                item.model_copy(update={"expires_at_epoch": now + 2_000}) for item in policy.stages
            ),
        }
    )
    base = _bundle(
        _paid_policy(),
        budget_cap_paise=10_000,
        paid_approval_ref="ref:budget/test-approved",
    ).model_copy(
        update={
            "environment": "production",
            "issued_at_epoch": now - 10,
            "expires_at_epoch": now + 3_000,
            "acquisition_policy": policy,
        }
    )
    supplement = _stage_supplement(policy, expires_at_epoch=now + 1_000).model_copy(
        update={"issued_at_epoch": now - 5}
    )
    bundle_path = tmp_path / "production-base.json"
    supplement_path = tmp_path / "supplement.json"
    output_path = tmp_path / "prepared.json"
    bundle_path.write_bytes(base.to_json())
    supplement_path.write_text(supplement.model_dump_json(), encoding="utf-8")

    assert (
        supplement_cli_main(
            [
                "--bundle",
                str(bundle_path),
                "--supplement",
                str(supplement_path),
                "--out",
                str(output_path),
            ]
        )
        == 2
    )
    assert not output_path.exists()
    assert "does not match the current approval bundle" in capsys.readouterr().err


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


def test_legacy_128_mib_provider_policy_remains_readable() -> None:
    legacy_stages = tuple(
        _template(stage).model_copy(update={"max_input_bytes": LEGACY_DESCRIPTOR_MAX_BYTES})
        for stage in ("C2", "C4", "C5")
    )

    policy = _policy(
        max_source_bytes=LEGACY_DESCRIPTOR_MAX_BYTES,
        stages=legacy_stages,
    )

    assert policy.max_source_bytes == LEGACY_DESCRIPTOR_MAX_BYTES
    assert all(item.max_input_bytes == LEGACY_DESCRIPTOR_MAX_BYTES for item in policy.stages)


def test_alternate_profile_requires_configuration_and_keeps_legacy_ids() -> None:
    policy = _policy(profiles=(_gemini_profile(),))
    default = policy.derive_stage(
        tenant_id=TENANT_ID,
        person_id=PROCESSING_PERSON_ID,
        source_sha256=SOURCE_SHA,
        stage="C4",
        configuration_sha256="b" * 64,
    )
    alternate = policy.derive_stage(
        tenant_id=TENANT_ID,
        person_id=PROCESSING_PERSON_ID,
        source_sha256=SOURCE_SHA,
        stage="C4",
        configuration_sha256="e" * 64,
    )
    assert (
        default.id
        == _policy()
        .derive_stage(
            tenant_id=TENANT_ID,
            person_id=PROCESSING_PERSON_ID,
            source_sha256=SOURCE_SHA,
            stage="C4",
        )
        .id
    )
    assert alternate.id != default.id
    assert alternate.provider_id == "gemini"
    assert alternate.model_id == "gemini-3.1-pro-preview"
    with pytest.raises(ValueError, match="acquisition_policy_configuration_required"):
        policy.derive_stage(
            tenant_id=TENANT_ID,
            person_id=PROCESSING_PERSON_ID,
            source_sha256=SOURCE_SHA,
            stage="C4",
        )


def test_legacy_permission_recovers_default_digest_after_alternate_is_pinned() -> None:
    policy = _policy(profiles=(_gemini_profile(),))
    bundle = _bundle(policy)
    authority = ConversationAuthority(
        lambda: bundle, environment="test", operations_tenant_id=TENANT_ID
    )
    actor = ProcessingActor(PROCESSING_PERSON_ID, TENANT_ID, uuid4())
    approval = policy.derive_stage(
        tenant_id=TENANT_ID,
        person_id=PROCESSING_PERSON_ID,
        source_sha256=SOURCE_SHA,
        stage="C4",
        configuration_sha256="b" * 64,
    )
    permission = ExecutionPermission(
        authorization_ref=f"hosted-stage-v1:{approval.id}:{bundle.digest}",
        quote_fingerprint="f" * 64,
        approved_by=str(PROCESSING_PERSON_ID),
        expires_at_epoch=1_600,
    )
    assert (
        authority._configuration_from_permission(bundle, actor, SOURCE_SHA, "C4", permission)
        == "b" * 64
    )


def test_empty_profiles_are_omitted_from_legacy_canonical_bundle() -> None:
    bundle = _bundle(_policy())
    value = bundle.as_dict()["acquisition_policy"]
    assert "profiles" not in value
    assert HostedApprovalBundle.model_validate_json(bundle.to_json()) == bundle


def test_unactivated_processing_default_stays_on_the_release_policy() -> None:
    bundle = _bundle(_policy())
    actor = ProcessingActor(PROCESSING_PERSON_ID, TENANT_ID, uuid4())
    authority = ConversationAuthority(
        lambda: bundle, environment="test", operations_tenant_id=TENANT_ID
    )

    assert (
        authority._approved_default_configuration_sha256(
            bundle,
            actor,
            source_sha256=SOURCE_SHA,
            stage="C2",
        )
        == "b" * 64
    )


@pytest.mark.asyncio
async def test_unactivated_saved_draft_is_not_an_implicit_provider_route() -> None:
    class _Application:
        def __init__(self) -> None:
            self.database = MagicMock()
            self.database.execute = AsyncMock(return_value=None)
            self.database.scalar = AsyncMock(side_effect=[None, object()])

    authority = ConversationAuthority(
        lambda: _bundle(_policy()), environment="test", operations_tenant_id=TENANT_ID
    )

    app = _Application()
    assert await authority._provider_configuration(app) is None
    # Only the activation lookup is allowed. The newest saved configuration
    # must never become an implicit route when no activation exists.
    assert app.database.scalar.await_count == 1


@pytest.mark.asyncio
async def test_processing_actor_cannot_override_release_pinned_configuration() -> None:
    authority = ConversationAuthority(
        lambda: _bundle(_policy()), environment="test", operations_tenant_id=TENANT_ID
    )
    actor = ProcessingActor(PROCESSING_PERSON_ID, TENANT_ID, uuid4())

    with pytest.raises(ConversationDenied, match="release-pinned route"):
        await authority.issue(
            None,  # rejected before application, database, or plan work is accessed
            actor,
            uuid4(),
            key="processing-config-override-denied",
            configuration_sha256="a" * 64,
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


@pytest.mark.asyncio
async def test_tester_analysis_scope_bypasses_count_but_keeps_bound_allowance_caps() -> None:
    allowance = AllowanceApproval(
        id=uuid4(),
        tenant_id=TENANT_ID,
        person_id=PROCESSING_PERSON_ID,
        seconds=86_400,
        authorization_ref="ref:approval/finite-tester",
        granted_by=CONTROL_PERSON_ID,
        reason="Approved internal testing allowance",
        max_recordings=4,
        max_source_bytes=MAX_AUDIO_BYTES,
        max_stored_source_bytes=536_870_912,
    )
    tester = InternalTesterApproval(
        id=uuid4(),
        email="admin@authorityclosers.com",
        authorization_ref="ref:approval/tester-exemption",
        scopes=("account_minutes", "analysis_count", "ip_session_issuance"),
        reason="Approved internal tester exemption",
    )
    bundle = HostedApprovalBundle(
        schema="ac.sales-xray.hosted-approval/1",
        environment="test",
        provider_control_tenant_id=TENANT_ID,
        deployment_ref="ref:deployment/tester-exemption",
        issued_at_epoch=1_000,
        expires_at_epoch=2_000,
        budget_scope_id=uuid4(),
        budget_authorization_ref="ref:budget/tester-exemption",
        budget_owner_id=CONTROL_PERSON_ID,
        intake_authorization_ref="ref:intake/tester-exemption",
        intake_retention_ref="ref:retention/tester-exemption",
        retention_days=7,
        max_stored_source_bytes=1_073_741_824,
        allowances=(allowance,),
        stages=(),
        internal_tester_accounts=(tester,),
    )

    class _Application:
        def __init__(self) -> None:
            self.database = MagicMock()
            self.database.scalar = AsyncMock(
                side_effect=[
                    SimpleNamespace(
                        status="active",
                        email="admin@authorityclosers.com",
                        email_verified_at=datetime.now(UTC),
                    ),
                    SimpleNamespace(status="active", role="learner", ended_at=None),
                    0,
                ]
            )
            self.database.execute = AsyncMock(
                side_effect=[None, SimpleNamespace(one=lambda: (4, 0))]
            )

        async def admit(self, _: ActorContext) -> datetime:
            return datetime.fromtimestamp(1_100, UTC)

    authority = ConversationAuthority(
        lambda: bundle,
        environment="test",
        operations_tenant_id=TENANT_ID,
        tester_policy=InternalTesterPolicy(lambda: bundle, "test"),
    )
    actor = ActorContext(PROCESSING_PERSON_ID, uuid4(), TENANT_ID)
    intent = IntakeIntent(
        source_sha256=SOURCE_SHA,
        source_bytes=1,
        content_type="audio/mpeg",
        duration_ms=1_000,
        purpose="internal_analysis",
    )

    await authority.admit_upload(_Application(), actor, intent)


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


def test_router_selects_the_pinned_alternate_profile_by_quote_digest() -> None:
    policy = _policy(profiles=(_gemini_profile(),))
    bundle = _bundle(policy)
    template = policy.profiles[0].stages[0]
    quote = Quote(
        quote_id="quote-acquisition-profile-v1",
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
        provider_configuration_sha256=template.configuration_sha256,
    )
    approval = policy.derive_stage(
        tenant_id=TENANT_ID,
        person_id=PROCESSING_PERSON_ID,
        source_sha256=SOURCE_SHA,
        stage="C2",
        configuration_sha256=template.configuration_sha256,
    )
    reservation = Reservation(
        reservation_id="reservation-acquisition-profile-v1",
        quote=quote,
        permission=ExecutionPermission(
            authorization_ref=f"hosted-stage-v1:{approval.id}:{bundle.digest}",
            quote_fingerprint=quote.fingerprint,
            approved_by=str(PROCESSING_PERSON_ID),
            expires_at_epoch=1_600,
        ),
        state="in_flight",
        attempt_id="attempt-acquisition-profile-v1",
    )
    resolved = FixedProviderRouter._stage(reservation, bundle)
    assert resolved.id == approval.id
    assert resolved.configuration_sha256 == template.configuration_sha256
