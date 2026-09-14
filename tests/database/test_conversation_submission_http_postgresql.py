"""Real cookie/HTTP/PostgreSQL upload and retained-owner reads; no providers."""

from __future__ import annotations

import hashlib
import hmac
import io
import secrets
import tempfile
import wave
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

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence import signals
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
    AcquisitionProviderPolicy,
    AcquisitionStagePolicy,
)
from ac_platform.conversation_intelligence.application import ConversationApplication
from ac_platform.conversation_intelligence.authority import ConversationAuthority
from ac_platform.conversation_intelligence.broker_router import FixedProviderRouter, ProviderRoute
from ac_platform.conversation_intelligence.inference_worker import ConversationInferenceWorker
from ac_platform.conversation_intelligence.intake import IntakePolicy
from ac_platform.conversation_intelligence.models import ConversationRecording, ConversationRun
from ac_platform.conversation_intelligence.native_runtime import (
    NativeRuntimeError,
    SocketNativeRuntime,
)
from ac_platform.conversation_intelligence.processing_plan import ProcessingPlanScheduler
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.conversation_intelligence.storage import PrivateLocalRecordingStorage
from ac_platform.http.auth import install_identity_http
from ac_platform.http.conversation_intake import ConversationIntakeRuntime
from ac_platform.http.conversation_submissions import install_submission_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from tests.database.test_conversation_authority_postgresql import (
    _bundle,
    _promote_admin,
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

ORIGIN = "https://salesxray.example.test"
PREFIX = "/v1/conversation/acquisition"


@pytest.fixture(scope="module")
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


class OfflinePreflight:
    def __init__(self) -> None:
        self.calls = 0

    def inspect(self, source: Path, outdir: Path, *, job_id: UUID, rate: Any) -> dict[str, Any]:
        self.calls += 1
        return signals.inspect_media(source, outdir, rate=rate)


async def _setup(postgres: Any, tmp_path: Path, *, gemini: bool = False) -> SimpleNamespace:
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
        config = _registry_config("guest-gemini-test-v1", text_provider="gemini")
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
            text_provider="gemini",
        )
        acquisition_stages = tuple(
            AcquisitionStagePolicy.model_validate(
                {
                    **item.model_dump(exclude={"id", "tenant_id", "person_id", "source_sha256"}),
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
        authority = ConversationAuthority(
            lambda: bundle, environment="test", operations_tenant_id=state.tenant_id
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
        authority=authority,
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


def test_progress_retries_one_deadlock_in_a_fresh_owner_transaction(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set("ac_xray_guest", setup.guest.token)
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
                assert progress.json()["submission_id"] == path.rsplit("/", 1)[-1]
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
                client.cookies.set("ac_xray_guest", setup.guest.token)
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
                client.cookies.set("ac_xray_guest", setup.guest.token)
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
                assert (await client.get(path + "/report")).status_code == 404
                unavailable = await client.post(
                    path + "/plan/quote",
                    headers={"Origin": ORIGIN, "Idempotency-Key": "no-provider-approved"},
                )
                assert unavailable.status_code == 409
                for suffix in ("", "/source", "/report", "/transcript"):
                    client.cookies.set("ac_xray_guest", setup.stranger.token)
                    denied = await client.get(path + suffix)
                    assert denied.status_code == 404
                client.cookies.set("ac_xray_guest", setup.guest.token)
                setup.clock[0] += timedelta(hours=2)
                audio = await client.get(path + "/source", headers={"Range": "bytes=0-43"})
                assert audio.status_code == 206
                assert audio.content == data[:44]
                assert audio.headers["cache-control"] == "private, no-store"
                assert audio.headers["content-range"] == f"bytes 0-43/{len(data)}"
                async with setup.sessions() as db, db.begin():
                    await setup.factory(db).claim(setup.guest.token, setup.state.actor)
                assert (await client.get(path + "/source")).status_code == 403
                client.cookies.clear()
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
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

            setup.native.inspect = timed_out  # type: ignore[method-assign]
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set("ac_xray_guest", setup.guest.token)
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
                client.cookies.set("ac_xray_guest", setup.guest.token)
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
                        token=setup.guest.token,
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


def test_create_app_mounts_guest_flow_and_streams_more_than_generic_body_limit(
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
                return signals.inspect_media(source, outdir, rate=rate)

            monkeypatch.setattr(SocketNativeRuntime, "inspect", local_test_inspect)
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
                client.cookies.set("ac_xray_guest", setup.guest.token)
                ready = await client.get(f"{PREFIX}/submissions/{submission}")
                assert ready.json()["local_state"] == "completed"
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_guest_http_plan_reaches_source_bound_overview_and_settles_without_browser(
    postgres_harness: Any,
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path, gemini=True)
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set("ac_xray_guest", setup.guest.token)
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
                assert [stage["provider"] for stage in plan["stages"]] == [
                    "elevenlabs",
                    "gemini",
                    "gemini",
                ]
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
                assert envelope["report"]["access"] == "guest_preview"
                assert envelope["report"]["numeric_publication"] is False
                assert envelope["report"]["content"]["overview"]["version"] == "dipak-14-point-v1"
                transcript = await client.get(path + "/transcript")
                assert transcript.status_code == 200
                assert transcript.json()["revision"] == envelope["transcript_revision"]
                assert "native_json" not in transcript.json()
                setup.clock[0] += timedelta(hours=2)
                assert (await client.get(path + "/report")).json() == envelope
                assert broker.calls == 3
                client.cookies.set("ac_xray_guest", setup.stranger.token)
                assert (await client.get(path + "/report")).status_code == 404
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
                for changed, url, expected in [
                    ({"Origin": "https://foreign.example.test"}, path, 403),
                    ({}, path + "?tenant_id=" + str(setup.state.tenant_id), 422),
                    ({"Host": "learner.example.test"}, path, 403),
                    ({"X-Upload-Consent": "false"}, path, 422),
                    ({"X-Upload-Policy": "0" * 64}, path, 422),
                    (
                        {
                            "Cookie": (
                                f"ac_xray_guest={setup.guest.token}; "
                                f"ac_xray_guest={setup.guest.token}"
                            )
                        },
                        path,
                        401,
                    ),
                ]:
                    rejected = await client.put(url, content=data, headers={**headers, **changed})
                    assert rejected.status_code == expected
                    assert setup.guest.token not in rejected.text
                assert setup.native.calls == 0
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
