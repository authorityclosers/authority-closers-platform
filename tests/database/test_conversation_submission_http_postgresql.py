"""Real cookie/HTTP/PostgreSQL upload and retained-owner reads; no providers."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import io
import json
import secrets
import tempfile
import threading
import wave
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import ac_platform.conversation_intelligence.inference_worker as inference_worker_module
from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence import signals
from ac_platform.conversation_intelligence.acquisition_challenge import UploadChallenge
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionSettlement,
    ConversationAcquisitionUsage,
)
from ac_platform.conversation_intelligence.acquisition_reports import AcquisitionReports
from ac_platform.conversation_intelligence.acquisition_sessions import (
    AcquisitionSessions,
    MeasuredSource,
)
from ac_platform.conversation_intelligence.acquisition_source import NativeUploadPreflight
from ac_platform.conversation_intelligence.activation_contract import (
    AcquisitionC5BenchmarkApproval,
    AcquisitionProviderPolicy,
    AcquisitionStagePolicy,
    HostedApprovalBundle,
)
from ac_platform.conversation_intelligence.analysis_settings import settings_from_row
from ac_platform.conversation_intelligence.application import ConversationApplication
from ac_platform.conversation_intelligence.authority import ConversationAuthority
from ac_platform.conversation_intelligence.broker_router import FixedProviderRouter, ProviderRoute
from ac_platform.conversation_intelligence.checkpoints import canonical, content_hash
from ac_platform.conversation_intelligence.guest_models import (
    ConversationGuestSubmission,
    ConversationProcessingContinuation,
)
from ac_platform.conversation_intelligence.inference_worker import ConversationInferenceWorker
from ac_platform.conversation_intelligence.intake import IntakePolicy
from ac_platform.conversation_intelligence.models import (
    ConversationAnalysisSettings,
    ConversationBudgetAccount,
    ConversationCommand,
    ConversationInferenceTask,
    ConversationMinuteAccount,
    ConversationProcessingPlan,
    ConversationProviderActivation,
    ConversationProviderConfiguration,
    ConversationQuote,
    ConversationRecording,
    ConversationReportDraft,
    ConversationRun,
)
from ac_platform.conversation_intelligence.native_runtime import (
    NativeRuntimeError,
    SocketNativeRuntime,
)
from ac_platform.conversation_intelligence.processing_plan import (
    ProcessingPlanScheduler,
)
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.conversation_intelligence.provider_registry import parse_registry_config
from ac_platform.conversation_intelligence.providers import ProviderResult
from ac_platform.conversation_intelligence.qualitative_pack import load_qualitative_pack
from ac_platform.conversation_intelligence.reports import load_report_profile
from ac_platform.conversation_intelligence.storage import PrivateLocalRecordingStorage
from ac_platform.http.auth import install_identity_http
from ac_platform.http.conversation import install_conversation_http
from ac_platform.http.conversation_acquisition import install_acquisition_http
from ac_platform.http.conversation_intake import ConversationIntakeRuntime
from ac_platform.http.conversation_submissions import install_submission_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.application import AsyncIdentityApplication
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.outbox.models import Job
from tests.database.test_conversation_authority_postgresql import (
    _bundle,
    _promote_admin,
    _provider,
    _registry_config,
)
from tests.database.test_conversation_guest_ownership_postgresql import _provision
from tests.database.test_conversation_intake_postgresql import policy
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed, seed_budget
from tests.database.test_conversation_processing_plan_postgresql import _make_due
from tests.database.test_conversation_reporting_pipeline_postgresql import ReportingBroker
from tests.database.test_conversation_worker_postgresql import (
    OfflineConversationWorker,
    _reconcile,
    _wav_one_second_48k,
)
from tests.database.test_openai_c5_http_postgresql import (
    OpenAIC5ReportingBroker,
    _coaching_output,
)

ORIGIN = "https://salesxray.example.test"
PREFIX = "/v1/conversation/acquisition"


@pytest.fixture
def postgres_harness() -> Any:
    # Each test gives its worker a different private storage root. Keep the
    # queue isolated too so an eligible retry from an earlier test cannot be
    # claimed against a later test's storage root.
    yield from _postgres_harness.__wrapped__()


class OfflinePreflight:
    def __init__(self) -> None:
        self.calls = 0

    def inspect(self, source: Path, outdir: Path, *, job_id: UUID, rate: Any) -> dict[str, Any]:
        self.calls += 1
        return signals.inspect_media(source, outdir, rate=rate)


class AcquisitionC5HistoryBroker(OpenAIC5ReportingBroker):
    """Return schema-valid synthetic C5 output for the retained Gemini run too."""

    async def execute(self, reservation: Any, payload: bytes) -> ProviderResult:
        if reservation.quote.provider_id == "gemini":
            body = json.loads(payload)
            user = body["contents"][0]["parts"][0]["text"]
            if not user.startswith("{"):
                self.routes.append("gemini")
                self.calls += 1
                self.payloads.append(payload)
                response = {
                    "candidates": [
                        {
                            "finishReason": "STOP",
                            "content": {
                                "role": "model",
                                "parts": [
                                    {"text": json.dumps(_coaching_output(), ensure_ascii=False)}
                                ],
                            },
                        }
                    ]
                }
                raw = canonical(response)
                return ProviderResult(
                    provider="gemini",
                    model=reservation.quote.provider_model,
                    request_id=f"synthetic-gemini-c5-history-{self.calls + 1}",
                    response_sha256=hashlib.sha256(raw).hexdigest(),
                    raw_json=raw,
                    data=response,
                    usage={"total_tokens": 224},
                    input_sha256=reservation.quote.input_sha256,
                )
        return await super().execute(reservation, payload)


async def _setup(
    postgres: Any,
    tmp_path: Path,
    *,
    gemini: bool = False,
    funded: bool = False,
    text_cost_paise: int = 0,
    asr_cost_paise: int = 50_000,
    c2_max_requests: int = 1,
    c4_max_requests: int = 1,
    c5_max_requests: int = 1,
) -> SimpleNamespace:
    engine = create_async_engine(postgres.url)
    state = await seed(engine)
    scope_id = await seed_budget(engine)
    principal = await _provision(engine, state)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    clock = [state.now]

    def factory(db: AsyncSession) -> AcquisitionSessions:
        return AcquisitionSessions(
            db,
            tenant_id=state.tenant_id,
            policy_revision="guest-processing-v1",
            clock=lambda: clock[0],
        )

    async with sessions() as db, db.begin():
        guest, stranger = await factory(db).issue(), await factory(db).issue()
    token, pepper = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    settings = Settings(
        _env_file=None,
        environment="test",
        public_app_url="https://learner.example.test",
        admin_app_url="https://admin.example.test",
        coach_app_url="https://coach.example.test",
        api_url="https://api.example.test",
        sales_xray_app_url=ORIGIN,
        public_learner_tenant_id=state.tenant_id,
        operations_tenant_id=uuid4(),
        session_token_pepper=SecretStr(pepper),
    )
    async with sessions() as db, db.begin():
        await db.execute(
            update(Person)
            .where(Person.id == state.person_id)
            .values(email=f"submission-{state.person_id.hex}@example.test")
        )
        await db.execute(
            update(IdentitySession)
            .where(IdentitySession.id == state.session_id)
            .values(token_hash=hmac.new(pepper.encode(), token.encode(), hashlib.sha256).digest())
        )
    authority = None
    selected_policy = policy(scope_id, state.tenant_id)
    if gemini:
        admin = await _promote_admin(engine, state)
        config = _registry_config(
            "guest-gemini-test-v1",
            funded=funded,
            text_provider="gemini",
            text_cost_paise=text_cost_paise,
            asr_cost_paise=asr_cost_paise,
        )
        async with sessions() as db, db.begin():
            view = await ConversationProviderAdmin(ConversationApplication(db)).save(
                admin, config.as_dict(), expected_revision=0, key="guest-gemini-config"
            )
        principal_scope = SimpleNamespace(tenant_id=state.tenant_id, person_id=principal)
        bundle = _bundle(
            principal_scope,
            hashlib.sha256(_wav_one_second_48k()).hexdigest(),
            view["configuration_sha256"],
            now_epoch=int(state.now.timestamp()),
            funded=funded,
            text_provider="gemini",
            text_cost_paise=text_cost_paise,
            asr_cost_paise=asr_cost_paise,
        )
        stage_templates = bundle.stages
        stage_request_limits = {"C2": c2_max_requests, "C4": c4_max_requests, "C5": c5_max_requests}
        acquisition_stages = tuple(
            AcquisitionStagePolicy.model_validate(
                {
                    **item.model_dump(exclude={"id", "tenant_id", "person_id", "source_sha256"}),
                    "max_requests": stage_request_limits[item.stage],
                    "max_completion_tokens": {"C2": 0, "C4": 1_400, "C5": 1_800}[item.stage],
                }
            )
            for item in bundle.stages
        )
        bundle = bundle.model_copy(
            update={
                "budget_owner_id": state.person_id,
                "allowances": (),
                "stages": (),
                "acquisition_policy": AcquisitionProviderPolicy(
                    schema="ac.sales-xray.acquisition-provider-policy/1",
                    id=uuid4(),
                    tenant_id=state.tenant_id,
                    processing_person_id=principal,
                    authorization_ref="ref:approval:synthetic-guest-processing",
                    expires_at_epoch=bundle.expires_at_epoch,
                    max_recordings=64,
                    max_source_bytes=134_217_728,
                    max_stored_source_bytes=8_589_934_592,
                    stages=acquisition_stages,
                ),
            }
        )
        bundle = type(bundle).model_validate_json(bundle.model_dump_json())
        bundle_box = {"bundle": bundle}
        authority = ConversationAuthority(
            lambda: bundle_box["bundle"], environment="test", operations_tenant_id=state.tenant_id
        )
        selected_policy = IntakePolicy(
            budget_scope_id=bundle.budget_scope_id,
            tenant_ids=frozenset({state.tenant_id}),
            authorization_ref=bundle.intake_authorization_ref,
            retention_ref=bundle.intake_retention_ref,
            retention_days=bundle.retention_days,
        )
    runtime = ConversationIntakeRuntime(
        selected_policy,
        PrivateLocalRecordingStorage(tmp_path / "source-store"),
        PrivateLocalRecordingStorage(tmp_path / "source-scratch"),
        authority,
    )
    native = OfflinePreflight()
    app = FastAPI()
    register_problem_handlers(app)
    require_actor = install_identity_http(app, settings=settings, sessions=sessions)
    install_submission_http(
        app,
        settings=settings,
        sessions=sessions,
        require_actor=require_actor,
        factory=factory,
        runtime=runtime,
        preflight=NativeUploadPreflight(native),
    )
    return SimpleNamespace(
        engine=engine,
        state=state,
        processing_person_id=principal,
        sessions=sessions,
        clock=clock,
        factory=factory,
        guest=guest,
        stranger=stranger,
        token=token,
        settings=settings,
        runtime=runtime,
        native=native,
        app=app,
        require_actor=require_actor,
        authority=authority,
        bundle_box=None if not gemini else bundle_box,
        stage_templates=None if not gemini else stage_templates,
    )


async def _headers(client: httpx.AsyncClient, data: bytes) -> dict[str, str]:
    terms = await client.get(PREFIX + "/upload-policy")
    assert terms.status_code == 200
    return {
        "Origin": ORIGIN,
        "Content-Type": "application/octet-stream",
        "X-Source-SHA256": hashlib.sha256(data).hexdigest(),
        "X-Upload-Policy": terms.json()["policy_sha256"],
        "X-Upload-Consent": "accepted",
    }


def _sign_in(setup: Any, client: httpx.AsyncClient) -> None:
    """Use the verified canonical account seeded by `_setup` for new uploads."""
    client.cookies.clear()
    client.cookies.set(setup.settings.session_cookie_name, setup.token)


class _DeadlockOrigin(Exception):
    sqlstate = "40P01"


class _OtherDatabaseErrorOrigin(Exception):
    sqlstate = "XX000"


def _database_error(origin: object) -> DBAPIError:
    return DBAPIError("SELECT", {}, origin, False)


async def _upload_for_read_test(setup: Any, client: httpx.AsyncClient) -> tuple[str, UUID]:
    data, submission = _wav_one_second_48k(), uuid4()
    path = f"{PREFIX}/submissions/{submission}"
    uploaded = await client.put(
        path + "/source", content=data, headers=await _headers(client, data)
    )
    assert uploaded.status_code == 202, uploaded.text
    return path, submission


class _HeldPlaybackIterator:
    """Yield one body block, then hold the source fence until the test releases it."""

    def __init__(self, data: bytes) -> None:
        self._first = data[:1]
        self._rest = data[1:]
        self.started = threading.Event()
        self.release = threading.Event()
        self._calls = 0

    def __iter__(self) -> _HeldPlaybackIterator:
        return self

    def __next__(self) -> bytes:
        if self._calls == 0:
            self._calls = 1
            return self._first
        if self._calls == 1:
            self._calls = 2
            self.started.set()
            if not self.release.wait(5):
                raise AssertionError("held playback iterator was not released")
            return self._rest
        raise StopIteration

    def close(self) -> None:
        self.release.set()


def test_progress_retries_one_deadlock_in_a_fresh_owner_transaction(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                _sign_in(setup, client)
                path, _ = await _upload_for_read_test(setup, client)
                original = AcquisitionReports.recording
                calls = 0

                async def flaky_recording(self: Any, *args: Any, **kwargs: Any) -> Any:
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        raise _database_error(_DeadlockOrigin())
                    return await original(self, *args, **kwargs)

                monkeypatch.setattr(AcquisitionReports, "recording", flaky_recording)
                progress = await client.get(path)
                assert progress.status_code == 200, progress.text
                assert calls == 2
                body = progress.json()
                assert body["submission_id"] == path.rsplit("/", 1)[-1]
                assert body["failure_code"] is None
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_owned_acquisition_c5_benchmark_uses_retained_c2_c4_and_one_saved_openai_route(
    postgres_harness: Any, tmp_path: Path
) -> None:
    """The account owner can approve one exact C5 while the processor stays a separate actor."""

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path, gemini=True, funded=True)
        try:
            owner_id = setup.state.person_id
            processor_id = setup.processing_person_id
            assert owner_id != processor_id
            settings_row = ConversationAnalysisSettings(
                id=uuid4(),
                tenant_id=setup.authority.operations_tenant_id,
                person_id=owner_id,
                session_id=setup.state.session_id,
                revision=5,
                c4_max_requests=64,
                c4_max_completion_tokens=1_400,
                c5_max_completion_tokens=8_000,
                c5_output_profile="detailed",
                c5_coaching_prompt_revision="coaching-v5",
                report_language_default="en",
                created_at=setup.state.now,
            )
            benchmark_settings = settings_from_row(settings_row)
            settings_sha256 = content_hash(benchmark_settings.effective_values())
            profile = load_report_profile()
            profile_sha256 = content_hash(profile)

            admin = await _promote_admin(setup.engine, setup.state)
            async with setup.sessions() as database, database.begin():
                base_configuration = await database.scalar(
                    select(ConversationProviderConfiguration).where(
                        ConversationProviderConfiguration.tenant_id
                        == setup.authority.operations_tenant_id,
                        ConversationProviderConfiguration.revision == 1,
                    )
                )
                assert base_configuration is not None
                active_configuration = await database.scalar(
                    select(ConversationProviderActivation).where(
                        ConversationProviderActivation.tenant_id
                        == setup.authority.operations_tenant_id
                    )
                )
                if active_configuration is None:
                    database.add(
                        ConversationProviderActivation(
                            id=uuid4(),
                            tenant_id=setup.authority.operations_tenant_id,
                            person_id=admin.person_id,
                            session_id=admin.session_id,
                            configuration_id=base_configuration.id,
                            configuration_revision=base_configuration.revision,
                            configuration_sha256=base_configuration.configuration_sha256,
                            sequence=1,
                            created_at=setup.state.now,
                        )
                    )
                data = deepcopy(base_configuration.configuration)
                openai_provider = _provider(
                    "openai",
                    "gpt-6-luna",
                    "https://api.openai.com/v1/responses",
                    max_cost_paise=2_200,
                )
                data["revision"] = "saved-openai-c5-benchmark-v5"
                data["providers"].append(openai_provider.as_dict())
                coaching_route = next(item for item in data["routes"] if item["task"] == "coaching")
                coaching_route["provider_id"] = "openai"
                coaching_route["model_id"] = "gpt-6-luna"
                data["policy"]["allow_paid"] = True
                data["policy"]["paid_approval_ref"] = setup.bundle_box["bundle"].paid_approval_ref
                saved_config = parse_registry_config(data)
                saved = await ConversationProviderAdmin(
                    ConversationApplication(database, clock=lambda: setup.state.now)
                ).save(
                    admin,
                    saved_config.as_dict(),
                    expected_revision=1,
                    key="synthetic-openai-c5-saved-revision-five",
                )
                assert saved["revision"] == 2
                database.add(settings_row)

            base_bundle = setup.bundle_box["bundle"]
            base_c5 = next(item for item in setup.stage_templates if item.stage == "C5")
            stage_approval_id = uuid4()
            benchmark_id = uuid4()
            issued_at = int(setup.state.now.timestamp())
            policy = base_bundle.acquisition_policy
            assert policy is not None
            expires_at = min(
                base_bundle.expires_at_epoch,
                policy.expires_at_epoch,
                base_c5.expires_at_epoch,
                issued_at + 3_600,
            )
            benchmark_stage = base_c5.model_copy(
                update={
                    "id": stage_approval_id,
                    "configuration_sha256": saved_config.digest,
                    "provider_id": "openai",
                    "model_id": "gpt-6-luna",
                    "permission_ref": openai_provider.permission_ref,
                    "provider_terms_ref": openai_provider.provider_terms_ref,
                    "privacy_ref": openai_provider.privacy_ref,
                    "pricing_ref": openai_provider.pricing_ref,
                    "credential_ref": openai_provider.credential_ref,
                    "free_allowance_ref": None,
                    "zero_cost_basis": "paid_pricing_evidence",
                    "price_evidence_sha256": hashlib.sha256(
                        b"synthetic isolated PostgreSQL C5 benchmark price fixture"
                    ).hexdigest(),
                    "max_requests": 1,
                    "max_cost_paise": 2_200,
                    "max_completion_tokens": 8_000,
                    "max_input_bytes": 134_217_728,
                    "profile_sha256": profile_sha256,
                    "expires_at_epoch": expires_at,
                }
            )
            origin = ORIGIN
            app = setup.app
            install_conversation_http(
                app,
                settings=setup.settings,
                require_actor=setup.require_actor,
                intake_runtime=setup.runtime,
            )
            broker = AcquisitionC5HistoryBroker(_wav_one_second_48k())
            router = FixedProviderRouter(
                {
                    provider: ProviderRoute(provider, f"ref:credential:{provider}", broker)
                    for provider in ("elevenlabs", "gemini", "openai")
                },
                authority=setup.authority,
            )
            worker = ConversationInferenceWorker(
                setup.sessions,
                setup.runtime.storage,
                router,
                authority=setup.authority,
            )
            scheduler = ProcessingPlanScheduler(
                setup.sessions, setup.authority, setup.runtime.storage
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=origin
            ) as client:
                _sign_in(setup, client)
                audio = _wav_one_second_48k()
                submission_id = uuid4()
                path = f"{PREFIX}/submissions/{submission_id}"
                uploaded = await client.put(
                    path + "/source", content=audio, headers=await _headers(client, audio)
                )
                assert uploaded.status_code == 202, uploaded.text
                await _reconcile(setup.sessions, setup.state)
                local = OfflineConversationWorker(
                    setup.sessions,
                    storage=setup.runtime.storage,
                    scratch=setup.runtime.scratch,
                    environment="test",
                )
                assert await local.run_once()

                # The ordinary acquisition plan is owner-approved and produces
                # the retained C2/C4 inputs. Stop before its default C5 stage.
                quoted_plan = await client.post(
                    path + "/plan/quote",
                    headers={"Origin": origin, "Idempotency-Key": "benchmark-fixture-plan-quote"},
                )
                assert quoted_plan.status_code == 201, quoted_plan.text
                plan = quoted_plan.json()
                accepted_plan = await client.post(
                    path + "/plan",
                    json={
                        "plan_id": plan["id"],
                        "plan_fingerprint": plan["plan_fingerprint"],
                        "privacy_revision": plan["privacy_revision"],
                        "accepted": True,
                    },
                    headers={"Origin": origin, "Idempotency-Key": "benchmark-fixture-plan-accept"},
                )
                assert accepted_plan.status_code == 202, accepted_plan.text
                assert await worker.run_once()
                await _make_due(setup, UUID(plan["id"]))
                assert await scheduler.step()
                assert await worker.run_once()
                await _make_due(setup, UUID(plan["id"]))
                assert await scheduler.step()
                assert await worker.run_once()
                async with setup.sessions() as database:
                    retained = (
                        await database.scalars(
                            select(ConversationInferenceTask).where(
                                ConversationInferenceTask.recording_id
                                == UUID(uploaded.json()["recording_id"]),
                                ConversationInferenceTask.stage.in_(("C2", "C4")),
                            )
                        )
                    ).all()
                    assert {row.stage for row in retained} == {"C2", "C4"}
                    assert all(row.state == "completed" for row in retained)
                    prior_c5 = await database.scalar(
                        select(ConversationInferenceTask).where(
                            ConversationInferenceTask.recording_id
                            == UUID(uploaded.json()["recording_id"]),
                            ConversationInferenceTask.stage == "C5",
                        )
                    )
                    assert prior_c5 is not None
                    if prior_c5.state != "completed":
                        prior_job = await database.get(Job, prior_c5.job_id)
                        raise AssertionError(
                            "synthetic prior C5 did not complete: "
                            f"state={prior_c5.state}, last_error="
                            f"{prior_job.last_error if prior_job is not None else 'job_missing'}"
                        )
                    prior_c5_run_id = prior_c5.run_id
                    prior_draft = await database.scalar(
                        select(ConversationReportDraft).where(
                            ConversationReportDraft.run_id == prior_c5_run_id,
                            ConversationReportDraft.erased_at.is_(None),
                        )
                    )
                    assert prior_draft is not None
                    link = await database.get(
                        ConversationGuestSubmission,
                        (setup.state.tenant_id, submission_id),
                    )
                    recording = await database.get(
                        ConversationRecording, UUID(uploaded.json()["recording_id"])
                    )
                    assert link is not None and recording is not None
                    assert link.person_id == processor_id
                    assert link.source_sha256 == hashlib.sha256(audio).hexdigest()
                    assert recording.source_revision == 1 and recording.generation == 1
                    assert setup.state.person_id == owner_id
                    assert link.person_id != owner_id
                prior_report = await client.get(path + "/report")
                assert prior_report.status_code == 200, prior_report.text
                assert prior_report.json()["run_id"] == str(prior_c5_run_id)
                benchmark = AcquisitionC5BenchmarkApproval(
                    id=benchmark_id,
                    authorization_ref="ref:permission:synthetic-acquisition-c5-benchmark",
                    tenant_id=setup.state.tenant_id,
                    owner_person_id=owner_id,
                    submission_id=submission_id,
                    recording_id=recording.id,
                    processing_person_id=processor_id,
                    processing_lease_id=link.processing_lease_id,
                    usage_id=link.usage_id,
                    source_sha256=recording.source_sha256,
                    source_revision=recording.source_revision,
                    generation=recording.generation,
                    stage_approval_id=stage_approval_id,
                    configuration_sha256=saved_config.digest,
                    analysis_settings_revision=5,
                    analysis_settings_sha256=settings_sha256,
                    coaching_prompt_revision="coaching-v5",
                    report_language="en",
                    output_profile="detailed",
                    profile_sha256=profile_sha256,
                    issued_at_epoch=issued_at,
                    expires_at_epoch=expires_at,
                    max_cost_paise=2_200,
                    max_completion_tokens=8_000,
                )

                configured_bundle = HostedApprovalBundle.model_validate_json(
                    base_bundle.model_copy(
                        update={
                            "stages": (*base_bundle.stages, benchmark_stage),
                            "acquisition_c5_benchmarks": (benchmark,),
                        }
                    ).to_json()
                )
                setup.bundle_box["bundle"] = configured_bundle
                recording_id = UUID(uploaded.json()["recording_id"])
                ordinary = await client.get(f"/v1/conversation/recordings/{recording_id}/analysis")
                assert ordinary.status_code == 404, ordinary.text

                before_routes = list(broker.routes)
                assert before_routes == ["elevenlabs", "gemini", "gemini"]
                benchmark_path = path + "/c5-benchmark"
                caller_selected_route = await client.post(
                    benchmark_path + "/quote",
                    json={"provider": "gemini", "model": "caller-selected"},
                    headers={"Origin": origin, "Idempotency-Key": "caller-route-rejected"},
                )
                assert caller_selected_route.status_code == 422, caller_selected_route.text
                assert broker.routes == before_routes
                invalid_source_sha256 = "0" * 64
                invalid_configuration_sha256 = "0" * 64
                invalid_scopes = (
                    (
                        benchmark.model_copy(update={"source_sha256": invalid_source_sha256}),
                        benchmark_stage.model_copy(update={"source_sha256": invalid_source_sha256}),
                    ),
                    (
                        benchmark.model_copy(
                            update={"configuration_sha256": invalid_configuration_sha256}
                        ),
                        benchmark_stage.model_copy(
                            update={"configuration_sha256": invalid_configuration_sha256}
                        ),
                    ),
                    (
                        benchmark.model_copy(
                            update={
                                "issued_at_epoch": issued_at - 3_600,
                                "expires_at_epoch": issued_at - 1,
                            }
                        ),
                        benchmark_stage,
                    ),
                )
                for index, (invalid, invalid_stage) in enumerate(invalid_scopes):
                    invalid_stages = tuple(
                        invalid_stage if item.id == stage_approval_id else item
                        for item in configured_bundle.stages
                    )
                    setup.bundle_box["bundle"] = HostedApprovalBundle.model_validate_json(
                        configured_bundle.model_copy(
                            update={
                                "stages": invalid_stages,
                                "acquisition_c5_benchmarks": (invalid,),
                            }
                        ).to_json()
                    )
                    refused = await client.post(
                        benchmark_path + "/quote",
                        headers={
                            "Origin": origin,
                            "Idempotency-Key": f"invalid-benchmark-scope-{index}",
                        },
                    )
                    assert refused.status_code in {403, 409}, refused.text
                    assert broker.routes == before_routes
                setup.bundle_box["bundle"] = configured_bundle
                quote_response = await client.post(
                    benchmark_path + "/quote",
                    headers={"Origin": origin, "Idempotency-Key": "owner-benchmark-quote"},
                )
                assert quote_response.status_code == 201, quote_response.text
                quote = quote_response.json()
                assert quote["purpose"] == "acquisition_c5_benchmark"
                assert quote["benchmark_approval_id"] == str(benchmark_id)
                assert quote["provider"] == "openai" and quote["model"] == "gpt-6-luna"
                assert quote["max_cost_paise"] == 2_200

                async with setup.sessions() as database:
                    active = await database.scalar(
                        select(ConversationProviderActivation)
                        .where(
                            ConversationProviderActivation.tenant_id
                            == setup.authority.operations_tenant_id
                        )
                        .order_by(ConversationProviderActivation.sequence.desc())
                    )
                    assert active is not None
                    assert active.configuration_sha256 == base_configuration.configuration_sha256
                    issued_quote = await database.get(ConversationQuote, UUID(quote["id"]))
                    assert issued_quote is not None
                    assert (
                        issued_quote.quote["provider_configuration_sha256"] == saved_config.digest
                    )
                    assert issued_quote.execution_permission[
                        "acquisition_c5_benchmark_approval_id"
                    ] == str(benchmark_id)

                accepted = await client.post(
                    benchmark_path,
                    json={
                        "quote_id": quote["id"],
                        "quote_fingerprint": quote["quote_fingerprint"],
                        "privacy_revision": quote["privacy_revision"],
                        "accepted": True,
                    },
                    headers={"Origin": origin, "Idempotency-Key": "owner-benchmark-accept"},
                )
                assert accepted.status_code == 202, accepted.text
                assert accepted.json()["purpose"] == "acquisition_c5_benchmark"
                assert accepted.json()["state"] == "queued"
                assert await worker.run_once()
                assert broker.routes == ["elevenlabs", "gemini", "gemini", "openai"]
                assert sum(route == "openai" for route in broker.routes) == 1
                assert str(benchmark_id).encode() not in broker.payloads[-1]
                async with setup.sessions() as database:
                    c5_tasks = (
                        await database.scalars(
                            select(ConversationInferenceTask)
                            .where(
                                ConversationInferenceTask.recording_id == recording_id,
                                ConversationInferenceTask.stage == "C5",
                            )
                            .order_by(ConversationInferenceTask.created_at)
                        )
                    ).all()
                    assert len(c5_tasks) == 2
                    c5 = next(
                        item
                        for item in c5_tasks
                        if item.intent["request"].get("acquisition_c5_benchmark_approval_id")
                        == str(benchmark_id)
                    )
                    assert c5.state == "completed" and c5.run_id != prior_c5_run_id
                    assert c5.intent["request"]["acquisition_c5_benchmark_approval_id"] == str(
                        benchmark_id
                    )
                    assert (
                        await database.scalar(
                            select(func.count())
                            .select_from(ConversationInferenceTask)
                            .where(
                                ConversationInferenceTask.recording_id == recording_id,
                                ConversationInferenceTask.stage.in_(("C2", "C4")),
                                ConversationInferenceTask.state == "completed",
                            )
                        )
                        == 2
                    )
                    assert await database.get(ConversationReportDraft, prior_draft.id) is not None
                benchmark_report = await client.get(path + "/report")
                assert benchmark_report.status_code == 200, benchmark_report.text
                assert benchmark_report.json()["run_id"] == str(c5.run_id)
                repeated_accept = await client.post(
                    benchmark_path,
                    json={
                        "quote_id": quote["id"],
                        "quote_fingerprint": quote["quote_fingerprint"],
                        "privacy_revision": quote["privacy_revision"],
                        "accepted": True,
                    },
                    headers={"Origin": origin, "Idempotency-Key": "owner-benchmark-accept"},
                )
                assert repeated_accept.status_code == 202, repeated_accept.text
                assert repeated_accept.json()["id"] == accepted.json()["id"]
                calls_after_benchmark = list(broker.routes)
                outsider = await seed(setup.engine, tenant_id=setup.state.tenant_id)
                outsider_token = secrets.token_urlsafe(32)
                async with setup.sessions() as database, database.begin():
                    session = await database.get(IdentitySession, outsider.session_id)
                    assert session is not None
                    session.token_hash = hmac.new(
                        setup.settings.session_token_pepper.get_secret_value().encode(),
                        outsider_token.encode(),
                        hashlib.sha256,
                    ).digest()
                client.cookies.clear()
                client.cookies.set(setup.settings.session_cookie_name, outsider_token)
                foreign_owner = await client.post(
                    benchmark_path + "/quote",
                    headers={"Origin": origin, "Idempotency-Key": "foreign-owner-benchmark-quote"},
                )
                assert foreign_owner.status_code == 404, foreign_owner.text
                assert broker.routes == calls_after_benchmark
                _sign_in(setup, client)
                owner_report = await client.get(path + "/report")
                assert owner_report.status_code == 200, owner_report.text
                assert owner_report.json()["run_id"] == str(c5.run_id)
        finally:
            await setup.engine.dispose()

    run(exercise())


@pytest.mark.parametrize(
    ("origin", "expected_calls"),
    [(_DeadlockOrigin(), 2), (_OtherDatabaseErrorOrigin(), 1)],
)
def test_progress_deadlock_retry_is_bounded_and_code_specific(
    postgres_harness: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    origin: object,
    expected_calls: int,
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app, raise_app_exceptions=False),
                base_url=ORIGIN,
            ) as client:
                _sign_in(setup, client)
                path, _ = await _upload_for_read_test(setup, client)
                calls = 0

                async def always_fails(self: Any, *args: Any, **kwargs: Any) -> Any:
                    nonlocal calls
                    calls += 1
                    raise _database_error(origin)

                monkeypatch.setattr(AcquisitionReports, "recording", always_fails)
                failed = await client.get(path)
                assert failed.status_code == 500
                assert calls == expected_calls
                assert setup.guest.token not in failed.text
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_original_upload_worker_and_expired_lease_playback_are_owner_bound(
    postgres_harness: Any,
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                _sign_in(setup, client)
                data, submission = _wav_one_second_48k(), uuid4()
                path = f"{PREFIX}/submissions/{submission}"
                headers = await _headers(client, data)
                uploaded = await client.put(path + "/source", content=data, headers=headers)
                assert uploaded.status_code == 202, uploaded.text
                result = uploaded.json()
                assert result["duration_ms"] == 1000
                assert result["source_sha256"] == hashlib.sha256(data).hexdigest()
                assert result["allowance"]["available_seconds"] == 3599
                assert setup.native.calls == 1
                missing_measurements = await client.get(path + "/waveform")
                assert missing_measurements.status_code == 409
                repeat = await client.put(path + "/source", content=data, headers=headers)
                assert repeat.status_code == 202, repeat.text
                assert repeat.json()["recording_id"] == result["recording_id"]
                assert repeat.json()["allowance"]["available_seconds"] == 3599
                async with setup.sessions() as db:
                    assert (
                        await db.scalar(
                            select(func.count())
                            .select_from(ConversationAcquisitionUsage)
                            .where(ConversationAcquisitionUsage.submission_id == submission)
                        )
                        == 1
                    )
                    usage = await db.scalar(
                        select(ConversationAcquisitionUsage).where(
                            ConversationAcquisitionUsage.submission_id == submission
                        )
                    )
                    assert usage is not None
                    assert usage.person_id == setup.state.person_id and usage.visitor_id is None
                    assert (
                        await db.scalar(
                            select(func.count())
                            .select_from(ConversationRun)
                            .where(ConversationRun.recording_id == UUID(result["recording_id"]))
                        )
                        == 1
                    )
                await _reconcile(setup.sessions, setup.state)
                worker = OfflineConversationWorker(
                    setup.sessions,
                    storage=setup.runtime.storage,
                    scratch=setup.runtime.scratch,
                    environment="test",
                )
                assert await worker.run_once()
                status = await client.get(path)
                assert status.status_code == 200
                assert status.json()["has_report"] is False
                assert status.json()["automatic_progression"] is False
                waveform = await client.get(path + "/waveform")
                assert waveform.status_code == 200, waveform.text
                assert waveform.json()["schema"] == "ac.sales-xray.waveform/1"
                assert waveform.json()["kind"] == "rms_envelope"
                assert waveform.json()["duration_ms"] == 1000
                assert 0 < len(waveform.json()["points"]) <= 1200
                assert waveform.headers["cache-control"] == "private, no-store"
                assert (await client.get(path + "/report")).status_code == 404
                unavailable = await client.post(
                    path + "/plan/quote",
                    headers={"Origin": ORIGIN, "Idempotency-Key": "no-provider-approved"},
                )
                assert unavailable.status_code == 409
                client.cookies.clear()
                for suffix in ("", "/source", "/report", "/transcript", "/waveform"):
                    client.cookies.set("ac_xray_guest", setup.stranger.token)
                    denied = await client.get(path + suffix)
                    assert denied.status_code == 404
                client.cookies.clear()
                setup.clock[0] += timedelta(hours=2)
                client.cookies.set("ac_xray_guest", setup.guest.token)
                assert (await client.get(path + "/source")).status_code == 404
                _sign_in(setup, client)
                audio = await client.get(path + "/source", headers={"Range": "bytes=0-43"})
                assert audio.status_code == 206
                assert audio.content == data[:44]
                assert audio.headers["cache-control"] == "private, no-store"
                assert audio.headers["content-range"] == f"bytes 0-43/{len(data)}"
                assert (await client.get(path + "/source")).content == data
                deleted = await client.delete(
                    path, headers={"Origin": ORIGIN, "Idempotency-Key": "owned-delete-after-lease"}
                )
                assert deleted.status_code == 202, deleted.text
                assert (await client.get(path + "/source")).status_code == 404
                assert await worker.run_once()
                async with setup.sessions() as db:
                    erased = await db.get(ConversationRecording, UUID(result["recording_id"]))
                    assert erased is not None and erased.state == "deleted"
                assert (
                    setup.runtime.storage.list_recording(
                        setup.state.tenant_id, UUID(result["recording_id"])
                    )
                    == ()
                )
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_authenticated_playback_keeps_shared_navigation_and_fences_deletion(
    postgres_harness: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read navigation may overlap playback; deletion waits for its source fence."""

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        install_acquisition_http(
            setup.app,
            settings=setup.settings,
            sessions=setup.sessions,
            require_actor=setup.require_actor,
            factory=setup.factory,
            challenge=UploadChallenge(
                secret=SecretStr("synthetic-test-challenge"), hostname="salesxray.example.test"
            ),
        )
        source_client: httpx.AsyncClient | None = None
        read_client: httpx.AsyncClient | None = None
        delete_client: httpx.AsyncClient | None = None
        source_task: asyncio.Task[httpx.Response] | None = None
        delete_task: asyncio.Task[httpx.Response] | None = None
        held: _HeldPlaybackIterator | None = None
        try:
            source_client = httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            )
            read_client = httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            )
            delete_client = httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            )
            for client in (source_client, read_client, delete_client):
                _sign_in(setup, client)
            data, submission = _wav_one_second_48k(), uuid4()
            path = f"{PREFIX}/submissions/{submission}"
            uploaded = await source_client.put(
                path + "/source", content=data, headers=await _headers(source_client, data)
            )
            assert uploaded.status_code == 202, uploaded.text
            read_client.cookies.clear()
            stranger = await read_client.get(path, cookies={"ac_xray_guest": setup.stranger.token})
            assert stranger.status_code == 404
            _sign_in(setup, read_client)
            await _reconcile(setup.sessions, setup.state)
            upload_worker = OfflineConversationWorker(
                setup.sessions,
                storage=setup.runtime.storage,
                scratch=setup.runtime.scratch,
                environment="test",
            )
            assert await upload_worker.run_once()
            async with setup.sessions() as db:
                session_before = await db.get(IdentitySession, setup.state.session_id)
                assert session_before is not None
                activity_before = (session_before.revision, session_before.last_seen_at)

            held = _HeldPlaybackIterator(data)

            def held_iter(_key: Any, *, expected_sha256: str) -> _HeldPlaybackIterator:
                assert expected_sha256 == hashlib.sha256(data).hexdigest()
                return held

            monkeypatch.setattr(setup.runtime.storage, "iter_bytes", held_iter)
            source_task = asyncio.create_task(
                source_client.get(path + "/source", headers={"Range": "bytes=0-100"})
            )
            assert await asyncio.to_thread(held.started.wait, 2)

            session_task = asyncio.create_task(read_client.get(PREFIX + "/session"))
            progress_task = asyncio.create_task(read_client.get(path))
            library_task = asyncio.create_task(read_client.get(PREFIX + "/submissions"))
            workspaces_task = asyncio.create_task(read_client.get("/v1/me/workspaces"))
            session, progress, library, workspaces = await asyncio.gather(
                asyncio.wait_for(session_task, 2),
                asyncio.wait_for(progress_task, 2),
                asyncio.wait_for(library_task, 2),
                asyncio.wait_for(workspaces_task, 2),
            )
            assert session.status_code == 200, session.text
            assert progress.status_code == 200, progress.text
            assert library.status_code == 200, library.text
            assert workspaces.status_code == 200, workspaces.text

            async with setup.sessions() as db:
                session_after_reads = await db.get(IdentitySession, setup.state.session_id)
                assert session_after_reads is not None
                assert (
                    session_after_reads.revision,
                    session_after_reads.last_seen_at,
                ) == activity_before

            delete_task = asyncio.create_task(
                delete_client.delete(
                    path,
                    headers={"Origin": ORIGIN, "Idempotency-Key": "held-stream-delete"},
                )
            )
            lock_attempted = asyncio.Event()
            original_lock_person = AsyncIdentityApplication._lock_person

            async def observed_lock_person(self: Any, *args: Any, **kwargs: Any) -> Any:
                lock_attempted.set()
                return await original_lock_person(self, *args, **kwargs)

            monkeypatch.setattr(AsyncIdentityApplication, "_lock_person", observed_lock_person)
            await asyncio.wait_for(lock_attempted.wait(), 2)
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(asyncio.shield(delete_task), 0.2)

            held.release.set()
            source = await asyncio.wait_for(source_task, 5)
            deleted = await asyncio.wait_for(delete_task, 5)
            assert source.status_code == 206, source.text
            assert source.content == data[:101]
            assert deleted.status_code == 202, deleted.text

            await _reconcile(setup.sessions, setup.state)
            worker = OfflineConversationWorker(
                setup.sessions,
                storage=setup.runtime.storage,
                scratch=setup.runtime.scratch,
                environment="test",
            )
            assert await worker.run_once()
            assert (
                setup.runtime.storage.list_recording(
                    setup.state.tenant_id, UUID(uploaded.json()["recording_id"])
                )
                == ()
            )
        finally:
            if held is not None:
                held.release.set()
            pending = [
                task for task in (source_task, delete_task) if task is not None and not task.done()
            ]
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            for client in (source_client, read_client, delete_client):
                if client is not None:
                    await client.aclose()
            await setup.engine.dispose()

    run(exercise())


def test_cancelled_authenticated_playback_closes_response_fence(
    postgres_harness: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Client backpressure cancellation closes the real source iterator and transaction."""

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        source_started = asyncio.Event()
        source_release = asyncio.Event()
        source_cancelled = asyncio.Event()

        async def gated_app(scope: Any, receive: Any, send: Any) -> None:
            async def gated_send(message: Any) -> None:
                if (
                    scope.get("path", "").endswith("/source")
                    and message["type"] == "http.response.body"
                    and message.get("body")
                ):
                    source_started.set()
                    try:
                        await source_release.wait()
                    except asyncio.CancelledError:
                        source_cancelled.set()
                        raise
                await send(message)

            await setup.app(scope, receive, gated_send)

        source_client: httpx.AsyncClient | None = None
        delete_client: httpx.AsyncClient | None = None
        source_task: asyncio.Task[httpx.Response] | None = None
        delete_task: asyncio.Task[httpx.Response] | None = None
        try:
            source_client = httpx.AsyncClient(
                transport=httpx.ASGITransport(app=gated_app), base_url=ORIGIN
            )
            delete_client = httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            )
            for client in (source_client, delete_client):
                _sign_in(setup, client)
            data, submission = _wav_one_second_48k(), uuid4()
            path = f"{PREFIX}/submissions/{submission}"
            uploaded = await delete_client.put(
                path + "/source", content=data, headers=await _headers(delete_client, data)
            )
            assert uploaded.status_code == 202, uploaded.text
            await _reconcile(setup.sessions, setup.state)
            upload_worker = OfflineConversationWorker(
                setup.sessions,
                storage=setup.runtime.storage,
                scratch=setup.runtime.scratch,
                environment="test",
            )
            assert await upload_worker.run_once()
            source_task = asyncio.create_task(source_client.get(path + "/source"))
            await asyncio.wait_for(source_started.wait(), 2)

            lock_attempted = asyncio.Event()
            original_lock_person = AsyncIdentityApplication._lock_person

            async def observed_lock_person(self: Any, *args: Any, **kwargs: Any) -> Any:
                lock_attempted.set()
                return await original_lock_person(self, *args, **kwargs)

            monkeypatch.setattr(AsyncIdentityApplication, "_lock_person", observed_lock_person)
            delete_task = asyncio.create_task(
                delete_client.delete(
                    path,
                    headers={"Origin": ORIGIN, "Idempotency-Key": "cancelled-stream-delete"},
                )
            )
            await asyncio.wait_for(lock_attempted.wait(), 2)
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(asyncio.shield(delete_task), 0.2)

            source_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(source_task, 5)
            await asyncio.wait_for(source_cancelled.wait(), 2)
            deleted = await asyncio.wait_for(delete_task, 5)
            assert deleted.status_code == 202, deleted.text

            await _reconcile(setup.sessions, setup.state)
            delete_worker = OfflineConversationWorker(
                setup.sessions,
                storage=setup.runtime.storage,
                scratch=setup.runtime.scratch,
                environment="test",
            )
            assert await delete_worker.run_once()
            assert (
                setup.runtime.storage.list_recording(
                    setup.state.tenant_id, UUID(uploaded.json()["recording_id"])
                )
                == ()
            )
        finally:
            source_release.set()
            pending = [
                task for task in (source_task, delete_task) if task is not None and not task.done()
            ]
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            for client in (source_client, delete_client):
                if client is not None:
                    await client.aclose()
            await setup.engine.dispose()

    run(exercise())


def test_native_preflight_timeout_does_not_reserve_usage(
    postgres_harness: Any,
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:

            def timed_out(
                _source: Path, _outdir: Path, *, job_id: UUID, rate: Any
            ) -> dict[str, Any]:
                assert type(job_id) is UUID and rate == 16000
                raise NativeRuntimeError("native_runtime_timeout")

            setup.native.validate_source = timed_out  # type: ignore[method-assign]
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                _sign_in(setup, client)
                data, submission = _wav_one_second_48k(), uuid4()
                headers = await _headers(client, data)
                uploaded = await client.put(
                    f"{PREFIX}/submissions/{submission}/source",
                    content=data,
                    headers=headers,
                )
                assert uploaded.status_code == 408, uploaded.text
                assert "too long to verify" in uploaded.json()["detail"]

            async with setup.sessions() as db:
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(ConversationAcquisitionUsage)
                        .where(ConversationAcquisitionUsage.submission_id == submission)
                    )
                    == 0
                )
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_exact_owned_upload_retry_survives_exhausted_allowance(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                _sign_in(setup, client)
                data, submission = _wav_one_second_48k(), uuid4()
                path = f"{PREFIX}/submissions/{submission}/source"
                headers = await _headers(client, data)
                original = await client.put(path, content=data, headers=headers)
                assert original.status_code == 202
                # Canonical ledger fixture consumes the remaining allowance;
                # it creates no recording/job or external provider execution.
                async with setup.sessions() as db, db.begin():
                    await setup.factory(db).reserve(
                        MeasuredSource(uuid4(), "a" * 64, 3599 * 1000, "b" * 64),
                        actor=setup.state.actor,
                    )
                replay = await client.put(path, content=data, headers=headers)
                assert replay.status_code == 202, replay.text
                assert replay.json()["recording_id"] == original.json()["recording_id"]
                assert replay.json()["allowance"]["available_seconds"] == 0
                changed = await client.put(
                    path, content=data, headers={**headers, "X-Source-SHA256": "f" * 64}
                )
                assert changed.status_code == 409
                new = await client.put(
                    f"{PREFIX}/submissions/{uuid4()}/source", content=data, headers=headers
                )
                assert new.status_code == 409
                async with setup.sessions() as db:
                    assert (
                        await db.scalar(
                            select(func.count())
                            .select_from(ConversationAcquisitionUsage)
                            .where(ConversationAcquisitionUsage.submission_id == submission)
                        )
                        == 1
                    )
            await _reconcile(setup.sessions, setup.state)
            worker = OfflineConversationWorker(
                setup.sessions,
                storage=setup.runtime.storage,
                scratch=setup.runtime.scratch,
                environment="test",
            )
            assert await worker.run_once()
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_create_app_mounts_account_first_flow_and_streams_more_than_generic_body_limit(
    postgres_harness: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        import ac_platform.http.app as app_module

        setup = await _setup(postgres_harness, tmp_path)
        try:
            secret_file = tmp_path / "challenge.secret"
            secret_file.write_text(secrets.token_urlsafe(32), encoding="ascii")
            secret_file.chmod(0o600)
            configured = setup.settings.model_copy(
                update={
                    "sales_xray_acquisition_enabled": True,
                    "sales_xray_acquisition_policy_revision": "guest-processing-v1",
                    "sales_xray_challenge_secret_file": str(secret_file),
                    "sales_xray_challenge_site_key": "synthetic-site-key",
                    "sales_xray_native_socket_path": str(
                        Path(tempfile.gettempdir()) / "ac-xray-test.sock"
                    ),
                    "sales_xray_native_image_ref": "sha256:" + "a" * 64,
                }
            )
            monkeypatch.setattr(app_module, "settings", configured)
            monkeypatch.setattr(app_module, "session_factory", setup.sessions)

            def local_test_inspect(
                self: Any, source: Path, outdir: Path, *, job_id: UUID, rate: Any
            ) -> dict[str, Any]:
                return signals.validate_media(source, outdir, rate=rate)

            monkeypatch.setattr(SocketNativeRuntime, "validate_source", local_test_inspect)
            application = app_module.create_app(conversation_intake_runtime=setup.runtime)
            assert application.state.sales_xray_acquisition_configured is True
            paths = application.openapi()["paths"]
            assert PREFIX + "/session" in paths
            assert PREFIX + "/claim" in paths
            assert PREFIX + "/submissions/{submission_id}/source" in paths
            source = io.BytesIO()
            with wave.open(source, "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(48000)
                audio.writeframes(b"\x00\x00" * 48000 * 12)
            data = source.getvalue()
            assert len(data) > 1024 * 1024

            async def chunks():
                for offset in range(0, len(data), 256 * 1024):
                    yield data[offset : offset + 256 * 1024]

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application), base_url=ORIGIN
            ) as client:
                client.cookies.set("ac_xray_guest", setup.guest.token)
                entry = await client.get(PREFIX + "/entry")
                assert entry.json()["enabled"] is True
                assert entry.json()["site_key"] == "synthetic-site-key"
                headers = await _headers(client, data)
                headers["Content-Length"] = str(len(data))
                submission = uuid4()
                guest_upload = await client.put(
                    f"{PREFIX}/submissions/{submission}/source", content=chunks(), headers=headers
                )
                assert guest_upload.status_code == 401, guest_upload.text
                assert setup.native.calls == 0
                async with setup.sessions() as db:
                    assert (
                        await db.scalar(
                            select(func.count())
                            .select_from(ConversationAcquisitionUsage)
                            .where(ConversationAcquisitionUsage.submission_id == submission)
                        )
                        == 0
                    )
                _sign_in(setup, client)
                uploaded = await client.put(
                    f"{PREFIX}/submissions/{submission}/source", content=chunks(), headers=headers
                )
                assert uploaded.status_code == 202, uploaded.text
                assert uploaded.json()["duration_ms"] == 12000
                assert uploaded.json()["allowance"]["available_seconds"] == 3588
                pending = await client.get(f"{PREFIX}/submissions/{submission}")
                assert pending.json()["local_state"] == "queued"
                # The new byte exemption applies only to its explicit UUID PUT,
                # not arbitrary account JSON or a neighboring route.
                rejected = await client.post(
                    "/v1/context", content=data, headers={"Origin": ORIGIN}
                )
                assert rejected.status_code == 413
            await _reconcile(setup.sessions, setup.state)
            local = OfflineConversationWorker(
                setup.sessions,
                storage=setup.runtime.storage,
                scratch=setup.runtime.scratch,
                environment="test",
            )
            assert await local.run_once()
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application), base_url=ORIGIN
            ) as client:
                _sign_in(setup, client)
                ready = await client.get(f"{PREFIX}/submissions/{submission}")
                assert ready.json()["local_state"] == "completed"
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_account_http_plan_reaches_source_bound_overview_and_settles_without_browser(
    postgres_harness: Any,
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path, gemini=True)
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                _sign_in(setup, client)
                data, submission = _wav_one_second_48k(), uuid4()
                path = f"{PREFIX}/submissions/{submission}"
                headers = await _headers(client, data)
                uploaded = await client.put(path + "/source", content=data, headers=headers)
                assert uploaded.status_code == 202, uploaded.text
                await _reconcile(setup.sessions, setup.state)
                local = OfflineConversationWorker(
                    setup.sessions,
                    storage=setup.runtime.storage,
                    scratch=setup.runtime.scratch,
                    environment="test",
                )
                assert await local.run_once()
                quote = await client.post(
                    path + "/plan/quote",
                    headers={"Origin": ORIGIN, "Idempotency-Key": "exact-guest-plan"},
                )
                assert quote.status_code == 201, quote.text
                plan = quote.json()
                assert plan["max_cost_paise"] == 0
                assert "report_language" not in plan
                assert "coaching_prompt_revision" not in plan
                assert [stage["provider"] for stage in plan["stages"]] == [
                    "elevenlabs",
                    "gemini",
                    "gemini",
                ]
                # The source must enter the same durable uncertain state as a
                # real provider validation failure.  Do this through the
                # worker so the immutable inference-history trigger is tested
                # instead of being bypassed with a direct row mutation.
                broker = ReportingBroker(data)
                router = FixedProviderRouter(
                    {
                        provider: ProviderRoute(provider, f"ref:credential:{provider}", broker)
                        for provider in ("elevenlabs", "gemini")
                    },
                    authority=setup.authority,
                )
                worker = ConversationInferenceWorker(
                    setup.sessions, setup.runtime.storage, router, authority=setup.authority
                )
                approval = {
                    "plan_id": plan["id"],
                    "plan_fingerprint": plan["plan_fingerprint"],
                    "privacy_revision": plan["privacy_revision"],
                    "accepted": True,
                }
                rejected = await client.post(
                    path + "/plan",
                    json={**approval, "accepted": False},
                    headers={"Origin": ORIGIN, "Idempotency-Key": "reject-guest-plan"},
                )
                assert rejected.status_code == 422
                assert broker.calls == 0
                accepted = await client.post(
                    path + "/plan",
                    json=approval,
                    headers={"Origin": ORIGIN, "Idempotency-Key": "accept-guest-plan"},
                )
                assert accepted.status_code == 202, accepted.text
                scheduler = ProcessingPlanScheduler(setup.sessions, setup.authority)
                # No progress/read route settles usage; workers run independently
                # after the HTTP acceptance response, including a closed browser.
                for _ in range(8):
                    await worker.run_once()
                    await _make_due(setup, UUID(plan["id"]))
                    await scheduler.step()
                assert broker.routes == ["elevenlabs", "gemini", "gemini"]
                async with setup.sessions() as db:
                    usage = await db.scalar(
                        select(ConversationAcquisitionUsage).where(
                            ConversationAcquisitionUsage.submission_id == submission
                        )
                    )
                    assert usage is not None
                    settlement = await db.get(ConversationAcquisitionSettlement, usage.id)
                    assert settlement is not None and settlement.charged_seconds == 1
                    assert settlement.kind == "completed"
                report = await client.get(path + "/report")
                assert report.status_code == 200, report.text
                envelope = report.json()
                assert envelope["source_sha256"] == hashlib.sha256(data).hexdigest()
                assert envelope["report"]["access"] == "claimed_account"
                assert envelope["report"]["numeric_publication"] is False
                assert envelope["report"]["content"]["overview"]["version"] == "dipak-14-point-v1"
                transcript = await client.get(path + "/transcript")
                assert transcript.status_code == 200
                assert transcript.json()["revision"] == envelope["transcript_revision"]
                assert "native_json" not in transcript.json()
                setup.clock[0] += timedelta(hours=2)
                assert (await client.get(path + "/report")).json() == envelope
                assert broker.calls == 3
                client.cookies.clear()
                client.cookies.set("ac_xray_guest", setup.stranger.token)
                assert (await client.get(path + "/report")).status_code == 404
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_account_report_language_quote_is_bounded_frozen_and_read_only(
    postgres_harness: Any,
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path, gemini=True)
        try:
            data = _wav_one_second_48k()
            submission = uuid4()
            path = f"{PREFIX}/submissions/{submission}"
            async with setup.sessions() as database, database.begin():
                database.add(
                    ConversationAnalysisSettings(
                        id=uuid4(),
                        tenant_id=setup.state.tenant_id,
                        person_id=setup.state.person_id,
                        session_id=setup.state.session_id,
                        revision=1,
                        c4_max_requests=64,
                        c4_max_completion_tokens=1_400,
                        c5_max_completion_tokens=3_200,
                        c5_output_profile="detailed",
                        c5_coaching_prompt_revision="coaching-v4",
                        report_language_default="hi-Deva+en",
                        created_at=setup.state.now,
                    )
                )

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                _sign_in(setup, client)
                headers = await _headers(client, data)
                upload = await client.put(path + "/source", content=data, headers=headers)
                assert upload.status_code == 202, upload.text
                await _reconcile(setup.sessions, setup.state)
                local = OfflineConversationWorker(
                    setup.sessions,
                    storage=setup.runtime.storage,
                    scratch=setup.runtime.scratch,
                    environment="test",
                )
                assert await local.run_once()

                malformed = await client.post(
                    path + "/plan/quote",
                    content=b'{"report_language":"mr-Deva+en","unexpected":true}',
                    headers={
                        "Origin": ORIGIN,
                        "Content-Type": "application/json",
                        "Idempotency-Key": "malformed-language-preference",
                    },
                )
                assert malformed.status_code == 422
                before_quote = await client.post(
                    path + "/plan/quote",
                    json={"report_language": "mr-Deva+en"},
                    headers={"Origin": ORIGIN, "Idempotency-Key": "explicit-marathi-plan"},
                )
                assert before_quote.status_code == 201, before_quote.text
                quote = before_quote.json()
                assert quote["report_language"] == "mr-Deva+en"
                assert quote["coaching_prompt_revision"] == "coaching-v4"
                assert "qualitative_pack_sha256" not in quote
                assert "sources" not in quote

                async with setup.sessions() as database:
                    plan_row = await database.get(ConversationProcessingPlan, UUID(quote["id"]))
                    assert plan_row is not None and plan_row.manifest is not None
                    frozen_manifest = dict(plan_row.manifest)
                    assert frozen_manifest["report_language"] == "mr-Deva+en"
                    assert frozen_manifest["coaching_prompt_revision"] == "coaching-v4"
                    assert frozen_manifest["qualitative_pack_sha256"] == (
                        load_qualitative_pack().sha256
                    )
                    commands_before_read = await database.scalar(
                        select(func.count()).select_from(ConversationCommand)
                    )
                    continuations_before_read = await database.scalar(
                        select(func.count()).select_from(ConversationProcessingContinuation)
                    )

                read_plan = await client.get(path + "/plan")
                assert read_plan.status_code == 200, read_plan.text
                assert read_plan.json()["report_language"] == "mr-Deva+en"
                assert read_plan.json()["coaching_prompt_revision"] == "coaching-v4"
                assert "qualitative_pack_sha256" not in read_plan.json()

                async with setup.sessions() as database:
                    assert (
                        await database.scalar(select(func.count()).select_from(ConversationCommand))
                        == commands_before_read
                    )
                    assert (
                        await database.scalar(
                            select(func.count()).select_from(ConversationProcessingContinuation)
                        )
                        == continuations_before_read
                    )

                async with setup.sessions() as database, database.begin():
                    database.add(
                        ConversationAnalysisSettings(
                            id=uuid4(),
                            tenant_id=setup.state.tenant_id,
                            person_id=setup.state.person_id,
                            session_id=setup.state.session_id,
                            revision=2,
                            c4_max_requests=64,
                            c4_max_completion_tokens=1_400,
                            c5_max_completion_tokens=3_200,
                            c5_output_profile="detailed",
                            c5_coaching_prompt_revision="coaching-v4",
                            report_language_default="en",
                            created_at=setup.state.now,
                        )
                    )
                still_frozen = await client.get(path + "/plan")
                assert still_frozen.status_code == 200
                assert still_frozen.json()["report_language"] == "mr-Deva+en"

                client.cookies.clear()
                client.cookies.set("ac_xray_guest", setup.stranger.token)
                foreign = await client.get(path + "/plan")
                assert foreign.status_code == 404
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_account_duplicate_upload_reuses_uncertain_retained_c2_without_provider_call(
    postgres_harness: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The account-owned recovery path reuses a retained uncertain C2 receipt."""

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path, gemini=True)
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                _sign_in(setup, client)
                data = _wav_one_second_48k()
                source_submission = uuid4()
                source_path = f"{PREFIX}/submissions/{source_submission}"
                source_upload = await client.put(
                    source_path + "/source",
                    content=data,
                    headers=await _headers(client, data),
                )
                assert source_upload.status_code == 202, source_upload.text
                source_recording_id = UUID(source_upload.json()["recording_id"])
                await _reconcile(setup.sessions, setup.state)
                local = OfflineConversationWorker(
                    setup.sessions,
                    storage=setup.runtime.storage,
                    scratch=setup.runtime.scratch,
                    environment="test",
                )
                assert await local.run_once()

                source_quote_response = await client.post(
                    source_path + "/plan/quote",
                    headers={"Origin": ORIGIN, "Idempotency-Key": "retained-source-quote"},
                )
                assert source_quote_response.status_code == 201, source_quote_response.text
                source_plan = source_quote_response.json()
                source_approval = {
                    "plan_id": source_plan["id"],
                    "plan_fingerprint": source_plan["plan_fingerprint"],
                    "privacy_revision": source_plan["privacy_revision"],
                    "accepted": True,
                }
                # Keep a valid provider response, then model the real
                # recoverable failure window: the provider receipt was saved
                # but checkpoint publication was interrupted.
                broker = ReportingBroker(data)
                router = FixedProviderRouter(
                    {
                        provider: ProviderRoute(provider, f"ref:credential:{provider}", broker)
                        for provider in ("elevenlabs", "gemini")
                    },
                    authority=setup.authority,
                )
                worker = ConversationInferenceWorker(
                    setup.sessions, setup.runtime.storage, router, authority=setup.authority
                )
                original_validate = inference_worker_module.validate_scribe_result
                validation_failed = False

                def fail_once_after_receipt(*args: Any, **kwargs: Any) -> Any:
                    nonlocal validation_failed
                    if not validation_failed:
                        validation_failed = True
                        raise inference_worker_module.InferenceTaskError(
                            "synthetic_post_receipt_validation_failure"
                        )
                    return original_validate(*args, **kwargs)

                monkeypatch.setattr(
                    inference_worker_module,
                    "validate_scribe_result",
                    fail_once_after_receipt,
                )
                source_acceptance = await client.post(
                    source_path + "/plan",
                    json=source_approval,
                    headers={"Origin": ORIGIN, "Idempotency-Key": "retained-source-accept"},
                )
                assert source_acceptance.status_code == 202, source_acceptance.text
                assert await worker.run_once()
                assert broker.calls == 1
                assert validation_failed is True

                async with setup.sessions() as database, database.begin():
                    source_task = await database.scalar(
                        select(ConversationInferenceTask).where(
                            ConversationInferenceTask.recording_id == source_recording_id,
                            ConversationInferenceTask.stage == "C2",
                        )
                    )
                    assert source_task is not None and source_task.checkpoint_id is None
                    source_run = await database.get(ConversationRun, source_task.run_id)
                    source_job = await database.get(Job, source_task.job_id)
                    assert source_run is not None and source_job is not None
                    assert source_task.state == "uncertain"
                    assert source_run.state == "failed"
                    assert source_job.status == "dead_letter"
                    assert source_job.provider_receipt is not None
                    assert source_job.provider_receipt["validation_state"] == "provider_returned"

                async with setup.sessions() as database, database.begin():
                    source_task = await database.scalar(
                        select(ConversationInferenceTask)
                        .where(
                            ConversationInferenceTask.recording_id == source_recording_id,
                            ConversationInferenceTask.stage == "C2",
                        )
                        .order_by(ConversationInferenceTask.created_at)
                    )
                    assert source_task is not None
                    source_run = await database.get(ConversationRun, source_task.run_id)
                    source_job = await database.get(Job, source_task.job_id)
                    source_quote = await database.get(ConversationQuote, source_task.quote_id)
                    source_plan_row = await database.get(
                        ConversationProcessingPlan, UUID(source_plan["id"])
                    )
                    source_budget = (
                        await database.get(ConversationBudgetAccount, source_quote.budget_scope_id)
                        if source_quote is not None
                        else None
                    )
                    source_minute = await database.get(
                        ConversationMinuteAccount,
                        (setup.state.tenant_id, setup.processing_person_id),
                    )
                    assert (
                        source_run is not None
                        and source_job is not None
                        and source_quote is not None
                        and source_plan_row is not None
                        and source_budget is not None
                        and source_minute is not None
                        and source_task.state == "uncertain"
                        and source_task.checkpoint_id is None
                        and source_run.state == "failed"
                        and source_job.status == "dead_letter"
                        and source_job.provider_receipt is not None
                        and source_job.provider_receipt["validation_state"] == "provider_returned"
                    )
                    source_run_id = source_run.id
                    source_response_sha256 = source_job.provider_receipt["response_sha256"]
                    source_snapshot = {
                        "task": (source_task.state, source_task.checkpoint_id),
                        "run": (source_run.state, source_run.completed_at),
                        "job": (
                            source_job.status,
                            source_job.provider_receipt,
                            source_job.provider_receipt_digest,
                            source_job.dispatch_started_at,
                            source_job.provider_idempotency_key,
                        ),
                        "plan": (source_plan_row.state, source_plan_row.progress),
                        "budget": deepcopy(source_budget.snapshot),
                        "minute": deepcopy(source_minute.snapshot),
                        "checkpoint": None,
                    }

                target_submission = uuid4()
                target_path = f"{PREFIX}/submissions/{target_submission}"
                target_upload = await client.put(
                    target_path + "/source",
                    content=data,
                    headers=await _headers(client, data),
                )
                assert target_upload.status_code == 202, target_upload.text
                await _reconcile(setup.sessions, setup.state)
                assert await local.run_once()
                target_quote_response = await client.post(
                    target_path + "/plan/quote",
                    headers={"Origin": ORIGIN, "Idempotency-Key": "retained-target-quote"},
                )
                assert target_quote_response.status_code == 201, target_quote_response.text
                target_plan = target_quote_response.json()
                target_acceptance = await client.post(
                    target_path + "/plan",
                    json={
                        "plan_id": target_plan["id"],
                        "plan_fingerprint": target_plan["plan_fingerprint"],
                        "privacy_revision": target_plan["privacy_revision"],
                        "accepted": True,
                    },
                    headers={"Origin": ORIGIN, "Idempotency-Key": "retained-target-accept"},
                )
                assert target_acceptance.status_code == 202, target_acceptance.text
                assert broker.calls == 1

                target_recording_id = UUID(target_upload.json()["recording_id"])
                async with setup.sessions() as database:
                    target_task = await database.scalar(
                        select(ConversationInferenceTask).where(
                            ConversationInferenceTask.recording_id == target_recording_id,
                            ConversationInferenceTask.stage == "C2",
                        )
                    )
                    assert target_task is not None and target_task.state == "completed"
                    target_job = await database.get(Job, target_task.job_id)
                    target_quote = await database.get(ConversationQuote, target_task.quote_id)
                    assert target_job is not None and target_quote is not None
                    assert target_job.external_side_effect is False
                    assert target_job.dispatch_started_at is None
                    assert target_job.provider_idempotency_key is None
                    assert target_job.provider_receipt is not None
                    assert target_job.provider_receipt["raw_blob_id"] == str(source_run_id)
                    assert target_job.provider_receipt["retained_reuse"] == {
                        "schema": "ac.sales-xray.retained-c2-reuse/1",
                        "provider_calls": 0,
                        "source_recording_id": str(source_recording_id),
                        "source_run_id": str(source_run_id),
                        "source_response_sha256": source_response_sha256,
                    }
                    assert target_quote.quote["max_cost_paise"] == 0

                scheduler = ProcessingPlanScheduler(setup.sessions, setup.authority)
                # The source plan schedules its next reconciliation a couple of
                # seconds after the worker records the uncertain result. Make
                # that due point explicit before driving the target plan so the
                # assertion below proves the retained source is held rather
                # than depending on wall-clock timing in the CI shard.
                await _make_due(setup, UUID(source_plan["id"]))
                for _ in range(8):
                    await worker.run_once()
                    await _make_due(setup, UUID(target_plan["id"]))
                    await scheduler.step()
                assert broker.calls == 3
                assert broker.routes == ["elevenlabs", "gemini", "gemini"]
                report = await client.get(target_path + "/report")
                assert report.status_code == 200, report.text
                envelope = report.json()
                assert envelope["report"]["numeric_publication"] is False
                transcript = await client.get(target_path + "/transcript")
                assert transcript.status_code == 200, transcript.text

                async with setup.sessions() as database:
                    source_task = await database.scalar(
                        select(ConversationInferenceTask).where(
                            ConversationInferenceTask.recording_id == source_recording_id,
                            ConversationInferenceTask.stage == "C2",
                        )
                    )
                    assert source_task is not None
                    source_run = await database.get(ConversationRun, source_task.run_id)
                    source_job = await database.get(Job, source_task.job_id)
                    source_plan_row = await database.get(
                        ConversationProcessingPlan, UUID(source_plan["id"])
                    )
                    source_quote = await database.get(ConversationQuote, source_task.quote_id)
                    source_budget = (
                        await database.get(ConversationBudgetAccount, source_quote.budget_scope_id)
                        if source_quote is not None
                        else None
                    )
                    source_minute = await database.get(
                        ConversationMinuteAccount,
                        (setup.state.tenant_id, setup.processing_person_id),
                    )
                    assert (
                        source_run is not None
                        and source_job is not None
                        and source_plan_row is not None
                        and source_budget is not None
                        and source_minute is not None
                    )
                    # The target call uses the same tenant/account, so its
                    # valid C4/C5 reservations and the scheduler's normal
                    # held-plan projection may change shared snapshots. The
                    # retained source itself must remain immutable: task/run,
                    # provider receipt, and its own reservation are unchanged.
                    assert (source_task.state, source_task.checkpoint_id) == source_snapshot["task"]
                    assert (source_run.state, source_run.completed_at) == source_snapshot["run"]
                    assert (
                        source_job.status,
                        source_job.provider_receipt,
                        source_job.provider_receipt_digest,
                        source_job.dispatch_started_at,
                        source_job.provider_idempotency_key,
                    ) == source_snapshot["job"]
                    assert source_plan_row.state == "held"
                    assert source_plan_row.progress == {
                        "current_stage": "C2",
                        "failure_code": "stage_uncertain",
                    }
                    source_reservations = {
                        item["reservation_id"]: item
                        for item in source_snapshot["budget"]["reservations"]
                    }
                    current_reservations = {
                        item["reservation_id"]: item
                        for item in source_budget.snapshot["reservations"]
                    }
                    assert (
                        current_reservations[str(source_run_id)]
                        == source_reservations[str(source_run_id)]
                    )
                    assert source_snapshot["checkpoint"] is None
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_upload_boundary_rejects_selector_cookie_origin_and_source_tampering(
    postgres_harness: Any,
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                data = _wav_one_second_48k()
                path = f"{PREFIX}/submissions/{uuid4()}/source"
                headers = await _headers(client, data)
                assert (await client.put(path, content=data, headers=headers)).status_code == 401
                client.cookies.set("ac_xray_guest", setup.guest.token)
                guest_denied = await client.put(path, content=data, headers=headers)
                assert guest_denied.status_code == 401, guest_denied.text
                assert setup.native.calls == 0
                _sign_in(setup, client)
                for changed, url, expected in [
                    ({"Origin": "https://foreign.example.test"}, path, 403),
                    ({}, path + "?tenant_id=" + str(setup.state.tenant_id), 422),
                    ({"Host": "learner.example.test"}, path, 403),
                    ({"X-Upload-Consent": "false"}, path, 422),
                    ({"X-Upload-Policy": "0" * 64}, path, 422),
                ]:
                    rejected = await client.put(url, content=data, headers={**headers, **changed})
                    assert rejected.status_code == expected
                assert setup.native.calls == 0
                duplicate_cookie = (
                    f"{setup.settings.session_cookie_name}={setup.token}; "
                    f"{setup.settings.session_cookie_name}={setup.token}"
                )
                client.cookies.clear()
                duplicated = await client.put(
                    path,
                    content=data,
                    headers={**headers, "Cookie": duplicate_cookie},
                )
                assert duplicated.status_code == 401
                _sign_in(setup, client)
                mismatch = await client.put(
                    path, content=data, headers={**headers, "X-Source-SHA256": "0" * 64}
                )
                assert mismatch.status_code == 422
                assert setup.native.calls == 0
                async with setup.sessions() as db:
                    assert (
                        await db.scalar(
                            select(func.count())
                            .select_from(ConversationAcquisitionUsage)
                            .where(ConversationAcquisitionUsage.tenant_id == setup.state.tenant_id)
                        )
                        == 0
                    )
                    assert (
                        await db.scalar(
                            select(func.count())
                            .select_from(ConversationRecording)
                            .where(ConversationRecording.tenant_id == setup.state.tenant_id)
                        )
                        == 0
                    )
                assert list(setup.runtime.scratch.root.glob("work-*")) == []
        finally:
            await setup.engine.dispose()

    run(exercise())
