"""Focused tests for the inert, release-bound hosted reporting composition."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import ac_platform.conversation_intelligence.reporting_runtime as runtime_module
from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.activation_contract import (
    HOSTED_APPROVAL_SCHEMA,
    HostedApprovalBundle,
    InternalTesterApproval,
    StageApproval,
)
from ac_platform.conversation_intelligence.application import ConversationDenied
from ac_platform.conversation_intelligence.authority import ConversationAuthority
from ac_platform.conversation_intelligence.broker_router import FixedProviderRouter
from ac_platform.conversation_intelligence.inference_broker import (
    InfisicalLauncher,
    ProcessInferenceBroker,
)

TENANT_ID = UUID("10000000-0000-4000-8000-000000000001")
PERSON_ID = UUID("20000000-0000-4000-8000-000000000002")
SOURCE_SHA = "a" * 64
PROFILE_SHA = "d" * 64


def _stage(
    stage: str,
    provider: str,
    model: str,
    recipe: str,
    credential_ref: str,
    *,
    expires_at_epoch: int,
    index: int,
) -> StageApproval:
    is_c2 = stage == "C2"
    return StageApproval(
        id=UUID(f"40000000-0000-4000-8000-{index:012d}"),
        tenant_id=TENANT_ID,
        person_id=PERSON_ID,
        source_sha256=SOURCE_SHA,
        configuration_sha256="b" * 64,
        stage=stage,
        provider_id=provider,
        model_id=model,
        recipe_revision=recipe,
        permission_ref="ref:permission/reporting-runtime-v1",
        retention_ref="ref:retention/reporting-runtime-v1",
        professional_gate_ref="ref:professional/reporting-runtime-v1",
        pricing_ref="ref:pricing/reporting-runtime-zero-v1",
        provider_terms_ref="ref:provider-terms/reporting-runtime-v1",
        privacy_ref="ref:privacy/reporting-runtime-v1",
        credential_ref=credential_ref,
        free_allowance_ref="ref:allowance/reporting-runtime-v1",
        no_paid_overage_ref="ref:billing/reporting-runtime-no-overage-v1",
        privacy_revision="privacy-reporting-runtime-v1",
        privacy_notice="Synthetic test approval for the hosted reporting seam.",
        expires_at_epoch=expires_at_epoch,
        max_requests=3,
        entitlement_seconds=None if is_c2 else 0,
        zero_cost_basis="synthetic",
        price_evidence_sha256="c" * 64,
        max_source_duration_ms=14_400_000,
        max_input_bytes=32 * 1024 * 1024,
        max_completion_tokens=0 if is_c2 else 800,
        profile_sha256=PROFILE_SHA if stage == "C5" else None,
    )


def _bundle(
    stages: tuple[StageApproval, ...],
    *,
    issued_at_epoch: int,
    expires_at_epoch: int,
    environment: str = "test",
) -> HostedApprovalBundle:
    return HostedApprovalBundle(
        schema=HOSTED_APPROVAL_SCHEMA,
        environment=environment,
        provider_control_tenant_id=TENANT_ID,
        deployment_ref="ref:deployment/reporting-runtime-test-v1",
        issued_at_epoch=issued_at_epoch,
        expires_at_epoch=expires_at_epoch,
        budget_scope_id=UUID("30000000-0000-4000-8000-000000000003"),
        budget_authorization_ref="ref:budget/reporting-runtime-test-v1",
        budget_owner_id=PERSON_ID,
        intake_authorization_ref="ref:intake/reporting-runtime-test-v1",
        intake_retention_ref="ref:retention/reporting-runtime-intake-v1",
        retention_days=7,
        max_stored_source_bytes=1_073_741_824,
        allowances=(),
        stages=stages,
    )


def _current_bundle(
    stages: tuple[StageApproval, ...] | None = None,
) -> HostedApprovalBundle:
    now = int(datetime.now(UTC).timestamp())
    expires = now + 3_600
    if stages is None:
        stages = (
            _stage(
                "C2",
                "elevenlabs",
                "scribe_v2",
                "scribe-v2-native-normalized-v1",
                "ref:credential/elevenlabs/v1",
                expires_at_epoch=now + 1_800,
                index=1,
            ),
            _stage(
                "C4",
                "groq",
                "openai/gpt-oss-120b",
                "facts-v1",
                "ref:credential/groq/v1",
                expires_at_epoch=now + 1_800,
                index=2,
            ),
            _stage(
                "C5",
                "groq",
                "openai/gpt-oss-120b",
                "coaching-v1",
                "ref:credential/groq/v1",
                expires_at_epoch=now + 1_800,
                index=3,
            ),
        )
    return _bundle(stages, issued_at_epoch=now - 10, expires_at_epoch=expires)


def test_bootstrap_approval_boundary_requires_empty_free_bundle() -> None:
    now = int(datetime.now(UTC).timestamp())
    inert = _bundle((), issued_at_epoch=now - 60, expires_at_epoch=now + 3_600)

    runtime_module.validate_bootstrap_approval(inert)
    with pytest.raises(ValueError, match="worker_bootstrap_approval_not_empty"):
        runtime_module.validate_bootstrap_approval(_current_bundle())
    tester_bundle = inert.model_copy(
        update={
            "internal_tester_accounts": (
                InternalTesterApproval(
                    id=UUID("50000000-0000-4000-8000-000000000005"),
                    email="admin@authorityclosers.com",
                    authorization_ref="ref:tester/bootstrap",
                    scopes=("account_minutes",),
                    reason="Approved internal tester exemption",
                ),
            )
        }
    )
    with pytest.raises(ValueError, match="worker_bootstrap_approval_not_empty"):
        runtime_module.validate_bootstrap_approval(tester_bundle)


def _launcher(provider: str) -> InfisicalLauncher:
    return InfisicalLauncher(
        executable="infisical",
        provider_id=provider,
        project_ref="sales-xray-test",
        environment_ref="test",
        secret_path_ref=f"/provider-runtime/{provider}",
    )


def _sessions() -> async_sessionmaker[AsyncSession]:
    return cast(async_sessionmaker[AsyncSession], object())


def _compose(
    monkeypatch: pytest.MonkeyPatch,
    bundle: HostedApprovalBundle,
    launchers: dict[str, InfisicalLauncher],
    *,
    sessions: async_sessionmaker[AsyncSession] | None = None,
    storage: object | None = None,
) -> tuple[runtime_module.HostedReportingRuntime | None, ConversationAuthority, object]:
    authority = ConversationAuthority(
        lambda: bundle, environment="test", operations_tenant_id=bundle.provider_control_tenant_id
    )
    resolved_storage = object() if storage is None else storage
    intake = cast(Any, type("IntakeStub", (), {})())
    intake.authority = authority
    intake.storage = resolved_storage
    monkeypatch.setattr(runtime_module, "compose_hosted_intake", lambda _settings: intake)
    result = runtime_module.compose_hosted_reporting(
        Settings(environment="test"),
        _sessions() if sessions is None else sessions,
        launchers=launchers,
    )
    return result, authority, resolved_storage


def test_disabled_composition_is_inert_and_does_not_construct_provider_children(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime_module, "compose_hosted_intake", lambda _settings: None)

    class UnexpectedProviderConstruction:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pytest.fail("disabled hosted reporting constructed a provider child")

    monkeypatch.setattr(runtime_module, "ProcessInferenceBroker", UnexpectedProviderConstruction)
    result = runtime_module.compose_hosted_reporting(
        Settings(environment="test"),
        _sessions(),
        launchers={},
    )

    assert result is None


def test_current_approval_binds_shared_authority_store_and_db_seam_without_starting_workers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _current_bundle()
    elevenlabs = _launcher("elevenlabs")
    groq = _launcher("groq")
    storage = object()
    sessions = _sessions()
    runtime, authority, resolved_storage = _compose(
        monkeypatch,
        bundle,
        {
            "ref:credential/elevenlabs/v1": elevenlabs,
            "ref:credential/groq/v1": groq,
        },
        sessions=sessions,
        storage=storage,
    )

    assert runtime is not None
    assert runtime.authority is authority
    assert runtime.storage is resolved_storage is storage
    assert runtime.inference.sessions is sessions
    assert runtime.inference.storage is storage
    assert runtime.plans.sessions is sessions
    assert runtime.plans.authority is authority
    assert runtime.retention.sessions is sessions
    assert isinstance(runtime.inference.broker, FixedProviderRouter)

    routes = runtime.inference.broker._routes
    assert set(routes) == {"elevenlabs", "groq"}
    assert routes["elevenlabs"].credential_ref == "ref:credential/elevenlabs/v1"
    assert routes["groq"].credential_ref == "ref:credential/groq/v1"
    assert isinstance(routes["elevenlabs"].broker, ProcessInferenceBroker)
    assert isinstance(routes["groq"].broker, ProcessInferenceBroker)
    assert routes["elevenlabs"].broker is not routes["groq"].broker
    assert routes["elevenlabs"].broker._infisical is elevenlabs
    assert routes["groq"].broker._infisical is groq


@pytest.mark.parametrize(  # type: ignore[untyped-decorator]
    ("keys", "code"),
    [
        ({"ref:credential/elevenlabs/v1"}, "hosted_reporting_launcher_scope_mismatch"),
        (
            {
                "ref:credential/elevenlabs/v1",
                "ref:credential/groq/v1",
                "ref:credential/unused/v1",
            },
            "hosted_reporting_launcher_scope_mismatch",
        ),
    ],
    ids=["missing-approved-reference", "extra-reference"],
)
def test_launcher_scope_must_equal_approved_credential_references(
    monkeypatch: pytest.MonkeyPatch,
    keys: set[str],
    code: str,
) -> None:
    bundle = _current_bundle()
    launchers = {key: _launcher("groq" if "groq" in key else "elevenlabs") for key in keys}

    with pytest.raises(ValueError, match=f"^{code}$"):
        _compose(monkeypatch, bundle, launchers)


def test_launcher_provider_identity_must_match_the_approved_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _current_bundle()
    launchers = {
        "ref:credential/elevenlabs/v1": _launcher("groq"),
        "ref:credential/groq/v1": _launcher("groq"),
    }

    with pytest.raises(ValueError, match="^hosted_reporting_launcher_provider_mismatch$"):
        _compose(monkeypatch, bundle, launchers)


def test_provider_reference_ambiguity_is_rejected_before_any_child_is_created(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = int(datetime.now(UTC).timestamp())
    stages = (
        _stage(
            "C4",
            "groq",
            "openai/gpt-oss-120b",
            "facts-v1",
            "ref:credential/groq/v1",
            expires_at_epoch=now + 1_800,
            index=10,
        ),
        _stage(
            "C5",
            "groq",
            "openai/gpt-oss-120b",
            "coaching-v1",
            "ref:credential/groq/v2",
            expires_at_epoch=now + 1_800,
            index=11,
        ),
    )

    with pytest.raises(ValueError, match="^hosted_reporting_provider_reference_ambiguous$"):
        _compose(
            monkeypatch,
            _bundle(stages, issued_at_epoch=now - 10, expires_at_epoch=now + 3_600),
            {},
        )


def test_empty_approval_has_no_provider_mapping_or_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="^hosted_reporting_stage_approval_required$"):
        _compose(monkeypatch, _current_bundle(stages=()), {})


def test_expired_approval_is_denied_before_storage_or_provider_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = int(datetime.now(UTC).timestamp())
    stage = _stage(
        "C2",
        "elevenlabs",
        "scribe_v2",
        "scribe-v2-native-normalized-v1",
        "ref:credential/elevenlabs/v1",
        expires_at_epoch=now - 2,
        index=20,
    )
    expired = _bundle((stage,), issued_at_epoch=now - 3_600, expires_at_epoch=now - 1)

    with pytest.raises(ConversationDenied, match="approved processing configuration"):
        _compose(
            monkeypatch,
            expired,
            {"ref:credential/elevenlabs/v1": _launcher("elevenlabs")},
        )


def test_forged_invalid_bundle_is_reparsed_and_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _current_bundle()
    forged = bundle.model_copy(update={"expires_at_epoch": bundle.issued_at_epoch})

    with pytest.raises(ConversationDenied, match="approved processing configuration"):
        _compose(
            monkeypatch,
            forged,
            {
                "ref:credential/elevenlabs/v1": _launcher("elevenlabs"),
                "ref:credential/groq/v1": _launcher("groq"),
            },
        )
