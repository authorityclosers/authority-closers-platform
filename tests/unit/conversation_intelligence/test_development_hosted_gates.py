"""Development uses hosted gates; all data and persistence here are fictional."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence import acquisition_c5_benchmark
from ac_platform.conversation_intelligence.acquisition_c5_benchmark import validate_benchmark_scope
from ac_platform.conversation_intelligence.analysis_settings import DEFAULT_ANALYSIS_SETTINGS
from ac_platform.conversation_intelligence.application import (
    ConversationConflict,
    ConversationDenied,
)
from ac_platform.conversation_intelligence.budget_admin import ConversationBudgetAdmin
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.entitlements import BudgetAccount
from ac_platform.conversation_intelligence.execution_control import (
    ConversationExecutionPaused,
    require_execution_enabled,
)
from ac_platform.conversation_intelligence.processing_actor import ProcessingActor
from ac_platform.conversation_intelligence.reports import load_report_profile
from ac_platform.conversation_intelligence.service_config import load_service_config
from ac_platform.conversation_intelligence.storage import PrivateLocalRecordingStorage
from ac_platform.conversation_intelligence.worker import (
    HostedConversationWorker,
    OfflineConversationWorker,
)
from ac_platform.kernel.authz import ActorContext

from .test_budget_admin import bundle_for, held_budget, service_for
from .test_service_config import manifest, write_config


@pytest.mark.parametrize("environment", ["development", "staging", "production"])
def test_hosted_service_config_accepts_environment(tmp_path, environment):
    value = manifest(tmp_path)
    value["environment"] = environment
    assert load_service_config(*write_config(tmp_path, value)).environment == environment


@pytest.mark.parametrize("environment", ["development", "staging", "production", "local", "test"])
def test_worker_environment_preserves_native_boundary(tmp_path, environment):
    kwargs = dict(
        sessions=None,
        storage=PrivateLocalRecordingStorage(tmp_path / "storage"),
        scratch=PrivateLocalRecordingStorage(tmp_path / "scratch"),
        environment=environment,
    )
    native = SimpleNamespace(inspect=Mock(side_effect=AssertionError("no native execution")))
    if environment in {"local", "test"}:
        assert OfflineConversationWorker(**kwargs).native_runtime is None
        with pytest.raises(ValueError, match="Offline conversation worker"):
            HostedConversationWorker(**kwargs, native_runtime=native)
    else:
        with pytest.raises(
            ValueError, match="Hosted conversation worker requires a native adapter"
        ):
            HostedConversationWorker(**kwargs, native_runtime=None)
        worker = HostedConversationWorker(**kwargs, native_runtime=native)
        assert worker.environment == environment
        assert worker.native_runtime is native and worker.c1_rate == 16000
    native.inspect.assert_not_called()


@pytest.mark.parametrize("environment", ["development", "staging", "production", "local", "test"])
async def test_execution_control_still_enforces_pause(environment):
    row = SimpleNamespace(revision=1, paused=False, created_at=datetime(2026, 9, 28, tzinfo=UTC))
    database = SimpleNamespace(scalar=AsyncMock(return_value=row))
    tenant = uuid4()
    await require_execution_enabled(database, environment=environment, operations_tenant_id=tenant)
    row.paused = True
    with pytest.raises(ConversationExecutionPaused):
        await require_execution_enabled(
            database, environment=environment, operations_tenant_id=tenant
        )


@pytest.mark.parametrize("environment", ["development", "staging", "production", "local", "test"])
async def test_budget_cap_save_accepts_environment_and_preserves_reservations(environment):
    scope = uuid4()
    held = held_budget(scope).budget
    bundle = bundle_for(scope, cap=1_000_000)
    bundle.current = Mock()
    row = SimpleNamespace(scope_id=scope, revision=1, snapshot=held.as_dict())
    _, application = service_for(row, bundle)
    service = ConversationBudgetAdmin(
        application, environment=environment, operations_tenant_id=bundle.provider_control_tenant_id
    )
    service.admit = AsyncMock()
    actor = ActorContext(uuid4(), uuid4(), bundle.provider_control_tenant_id)
    await service.save(
        actor,
        bundle=bundle,
        new_cap_paise=1_000_000,
        expected_revision=1,
        reason="fictional approved development cap",
        key="development-cap",
    )
    saved = BudgetAccount.from_dict(row.snapshot)
    assert saved.cap_paise == 1_000_000 and row.revision == 2
    assert saved.reservations == held.reservations
    assert bundle.current.call_args.args[1] == environment
    application._receipt.assert_awaited_once()


@pytest.mark.parametrize("environment", ["development", "staging", "test", "production", "local"])
async def test_c5_benchmark_recheck_preserves_environment_and_source_boundary(
    environment, monkeypatch: pytest.MonkeyPatch
):
    marks_in_force = AsyncMock(return_value=False)
    monkeypatch.setattr(acquisition_c5_benchmark, "marks_in_force", marks_in_force)
    actor = ProcessingActor(uuid4(), uuid4(), uuid4())
    now = datetime(2026, 9, 28, tzinfo=UTC)
    settings = DEFAULT_ANALYSIS_SETTINGS
    shared = dict(
        tenant_id=actor.tenant_id,
        source_sha256="a" * 64,
        source_revision=1,
        generation=1,
    )
    recording = SimpleNamespace(**shared, id=uuid4(), state="ready")
    stage = SimpleNamespace(
        id=uuid4(),
        tenant_id=actor.tenant_id,
        person_id=actor.person_id,
        source_sha256=recording.source_sha256,
        stage="C5",
        provider_id="openai",
        model_id="gpt-6-luna",
        configuration_sha256="b" * 64,
        max_requests=1,
        max_cost_paise=100,
        max_completion_tokens=settings.c5_max_completion_tokens,
        profile_sha256=content_hash(load_report_profile()),
        expires_at_epoch=int(now.timestamp()) + 60,
    )
    benchmark = SimpleNamespace(
        **shared,
        recording_id=recording.id,
        processing_person_id=actor.person_id,
        processing_lease_id=actor.processing_lease_id,
        owner_person_id=uuid4(),
        submission_id=uuid4(),
        usage_id=uuid4(),
        stage_approval_id=stage.id,
        issued_at_epoch=int(now.timestamp()) - 60,
        expires_at_epoch=stage.expires_at_epoch,
        configuration_sha256=stage.configuration_sha256,
        max_cost_paise=stage.max_cost_paise,
        max_completion_tokens=stage.max_completion_tokens,
        profile_sha256=stage.profile_sha256,
        analysis_settings_revision=1,
        analysis_settings_sha256=content_hash(settings.effective_values()),
        coaching_prompt_revision=settings.c5_coaching_prompt_revision,
        report_language=settings.report_language_default,
        output_profile=settings.c5_output_profile,
    )
    bundle = SimpleNamespace(
        environment=environment,
        expires_at_epoch=stage.expires_at_epoch,
        stages=(stage,),
        provider_control_tenant_id=uuid4(),
    )
    link = SimpleNamespace(**vars(benchmark), person_id=actor.person_id)
    usage = SimpleNamespace(
        **vars(benchmark),
        person_id=benchmark.owner_person_id,
        visitor_id=None,
    )
    principal = SimpleNamespace(
        tenant_id=actor.tenant_id,
        person_id=actor.person_id,
        revoked_at=None,
        principal_id=uuid4(),
        usage_id=benchmark.usage_id,
    )
    owner = SimpleNamespace(status="active", email_verified_at=now)
    membership = SimpleNamespace(status="active", ended_at=None, role="learner")
    database = SimpleNamespace(
        get=AsyncMock(side_effect=[link, usage, principal, principal, owner, membership]),
        scalar=AsyncMock(return_value=SimpleNamespace(**settings.effective_values())),
    )
    app = SimpleNamespace(database=database)
    # AUT-519 D7 runs first and fails closed: a marked recording is refused before any
    # environment, lease or allowance read, in every environment.
    marks_in_force.return_value = True
    with pytest.raises(ConversationConflict, match="cannot be processed again"):
        await validate_benchmark_scope(app, actor, recording, bundle, benchmark, now)
    database.get.assert_not_awaited()
    marks_in_force.return_value = False
    if environment in {"production", "local"}:
        with pytest.raises(ConversationDenied, match="no longer matches its benchmark approval"):
            await validate_benchmark_scope(app, actor, recording, bundle, benchmark, now)
        database.get.assert_not_awaited()
    else:
        assert (
            await validate_benchmark_scope(app, actor, recording, bundle, benchmark, now) is stage
        )
        recording.source_revision += 1
        with pytest.raises(ConversationDenied, match="no longer matches its benchmark approval"):
            await validate_benchmark_scope(app, actor, recording, bundle, benchmark, now)
