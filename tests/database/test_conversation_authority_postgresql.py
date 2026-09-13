"""Disposable PostgreSQL proof for the hosted conversation authority boundary.

The approval bundle and provider configuration are synthetic, zero-cost test
artifacts.  The durable worker uses ReportingBroker, so no provider network,
credentials, paid allowance, or production deployment is exercised.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.activation_contract import (
    AllowanceApproval,
    HostedApprovalBundle,
    StageApproval,
)
from ac_platform.conversation_intelligence.application import (
    AUDIOATLAS_RECIPE,
    ConversationApplication,
    ConversationDenied,
)
from ac_platform.conversation_intelligence.authority import ConversationAuthority
from ac_platform.conversation_intelligence.checkpoints import canonical
from ac_platform.conversation_intelligence.contracts import QuoteAcceptance, RunIntent
from ac_platform.conversation_intelligence.entitlements import BudgetAccount, MinuteAccount
from ac_platform.conversation_intelligence.inference import (
    INFERENCE_JOB,
    TRANSCRIPT_RECIPE,
    ConversationInference,
)
from ac_platform.conversation_intelligence.inference_worker import ConversationInferenceWorker
from ac_platform.conversation_intelligence.intake import IntakePolicy
from ac_platform.conversation_intelligence.models import (
    ConversationBudgetAccount,
    ConversationCheckpoint,
    ConversationInferenceTask,
    ConversationMinuteAccount,
    ConversationQuoteAcceptance,
    ConversationRecording,
    ConversationRun,
)
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.conversation_intelligence.provider_registry import (
    ProviderConfig,
    RegistryConfig,
    RegistryPolicy,
    RouteConfig,
    parse_registry_config,
)
from ac_platform.conversation_intelligence.report_store import ConversationReports
from ac_platform.conversation_intelligence.reporting_pipeline import (
    COACHING_RECIPE,
    FACT_RECIPE,
    StageRequest,
)
from ac_platform.conversation_intelligence.reports import load_report_profile
from ac_platform.http.auth import install_identity_http
from ac_platform.http.conversation import install_conversation_http
from ac_platform.http.conversation_intake import ConversationIntakeRuntime
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.outbox.models import Job
from ac_platform.tenancy.models import Membership
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_reporting_pipeline_postgresql import (
    ReportingBroker,
    completed_checkpoint,
)
from tests.database.test_conversation_worker_postgresql import _add_quote, _postgres_harness
from tests.database.test_conversation_worker_postgresql import _prepare as prepare_local


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


@dataclass(frozen=True)
class AuthorityFixture:
    prepared: Any
    engine: Any
    sessions: async_sessionmaker[AsyncSession]
    actor: ActorContext
    config: RegistryConfig
    config_view: dict[str, Any]
    bundle: HostedApprovalBundle
    bundle_box: dict[str, HostedApprovalBundle]
    authority: ConversationAuthority
    broker: ReportingBroker
    worker: ConversationInferenceWorker


def _refs(provider: str) -> dict[str, str]:
    return {
        "credential_ref": f"ref:credential:{provider}",
        "provider_terms_ref": f"ref:terms:{provider}",
        "privacy_ref": f"ref:privacy:{provider}",
        "pricing_ref": "ref:pricing:synthetic-zero",
        "free_allowance_ref": f"ref:allowance:{provider}",
        "permission_ref": f"ref:permission:{provider}",
        "endpoint_approval_ref": f"ref:endpoint:{provider}",
    }


def _provider(provider: str, model: str, endpoint: str) -> ProviderConfig:
    return ProviderConfig(
        provider_id=provider,
        model_id=model,
        endpoint=endpoint,
        endpoint_sha256=hashlib.sha256(endpoint.encode()).hexdigest(),
        **_refs(provider),
        local_endpoint_approval_ref=None,
        max_cost_paise=0,
    )


def _registry_config(revision: str) -> RegistryConfig:
    return RegistryConfig(
        revision=revision,
        policy=RegistryPolicy(),
        providers=(
            _provider(
                "elevenlabs",
                "scribe_v2",
                "https://api.elevenlabs.io/v1/speech-to-text",
            ),
            _provider(
                "groq",
                "openai/gpt-oss-120b",
                "https://api.groq.com/openai/v1/chat/completions",
            ),
        ),
        routes=(
            RouteConfig(
                "asr",
                "elevenlabs",
                "scribe_v2",
                TRANSCRIPT_RECIPE,
                "profile-none-v1",
                "prompt-asr-v1",
                "C0",
                None,
            ),
            RouteConfig(
                "facts",
                "groq",
                "openai/gpt-oss-120b",
                FACT_RECIPE,
                "profile-none-v1",
                "prompt-facts-v1",
                "C2",
                "C2",
            ),
            RouteConfig(
                "coaching",
                "groq",
                "openai/gpt-oss-120b",
                COACHING_RECIPE,
                str(load_report_profile()["revision"]),
                "prompt-coaching-v1",
                "C4",
                "C2",
            ),
        ),
    )


def _stage(
    *,
    state: Any,
    source_sha256: str,
    config_sha256: str,
    stage: str,
    provider: str,
    model: str,
    recipe: str,
    expires_at_epoch: int,
    entitlement_seconds: int | None,
    max_completion_tokens: int,
    profile_sha256: str | None,
    max_requests: int = 1,
) -> StageApproval:
    refs = _refs(provider)
    refs.pop("endpoint_approval_ref")
    return StageApproval(
        id=uuid4(),
        tenant_id=state.tenant_id,
        person_id=state.person_id,
        source_sha256=source_sha256,
        configuration_sha256=config_sha256,
        stage=stage,
        provider_id=provider,
        model_id=model,
        recipe_revision=recipe,
        **refs,
        retention_ref="ref:retention:synthetic",
        professional_gate_ref="ref:professional:synthetic",
        no_paid_overage_ref="ref:billing:synthetic-no-overage",
        privacy_revision="hosted-privacy-test-v1",
        privacy_notice="Synthetic zero-cost test approval; private source retention is bounded.",
        expires_at_epoch=expires_at_epoch,
        max_requests=max_requests,
        entitlement_seconds=entitlement_seconds,
        zero_cost_basis="synthetic",
        price_evidence_sha256="a" * 64,
        max_source_duration_ms=1_000,
        max_input_bytes=134_217_728,
        max_completion_tokens=max_completion_tokens,
        profile_sha256=profile_sha256,
    )


def _bundle(
    state: Any,
    source_sha256: str,
    config_sha256: str,
    *,
    now_epoch: int,
    expires_at_epoch: int | None = None,
) -> HostedApprovalBundle:
    bundle_expires = expires_at_epoch or now_epoch + 3_600
    stage_expires = min(bundle_expires, now_epoch + 1_800)
    profile_sha256 = hashlib.sha256(canonical(load_report_profile())).hexdigest()
    return HostedApprovalBundle(
        schema="ac.sales-xray.hosted-approval/1",
        environment="test",
        deployment_ref="ref:deployment:synthetic",
        issued_at_epoch=now_epoch - 1,
        expires_at_epoch=bundle_expires,
        budget_scope_id=uuid4(),
        budget_authorization_ref="ref:budget:synthetic-zero",
        budget_owner_id=state.person_id,
        intake_authorization_ref="ref:intake:synthetic",
        intake_retention_ref="ref:retention:intake-synthetic",
        retention_days=7,
        max_stored_source_bytes=34_359_738_368,
        allowances=(
            AllowanceApproval(
                id=uuid4(),
                tenant_id=state.tenant_id,
                person_id=state.person_id,
                seconds=300,
                authorization_ref="ref:allowance:synthetic",
                granted_by=state.person_id,
                reason="Approved internal testing allowance",
                max_recordings=64,
                max_source_bytes=134_217_728,
                max_stored_source_bytes=8_589_934_592,
            ),
        ),
        stages=(
            _stage(
                state=state,
                source_sha256=source_sha256,
                config_sha256=config_sha256,
                stage="C2",
                provider="elevenlabs",
                model="scribe_v2",
                recipe=TRANSCRIPT_RECIPE,
                expires_at_epoch=stage_expires,
                entitlement_seconds=None,
                max_completion_tokens=0,
                profile_sha256=None,
            ),
            _stage(
                state=state,
                source_sha256=source_sha256,
                config_sha256=config_sha256,
                stage="C4",
                provider="groq",
                model="openai/gpt-oss-120b",
                recipe=FACT_RECIPE,
                expires_at_epoch=stage_expires,
                entitlement_seconds=0,
                max_completion_tokens=4_000,
                profile_sha256=None,
            ),
            _stage(
                state=state,
                source_sha256=source_sha256,
                config_sha256=config_sha256,
                stage="C5",
                provider="groq",
                model="openai/gpt-oss-120b",
                recipe=COACHING_RECIPE,
                expires_at_epoch=stage_expires,
                entitlement_seconds=0,
                max_completion_tokens=4_000,
                profile_sha256=profile_sha256,
            ),
        ),
    )


async def _promote_admin(engine: Any, state: Any) -> ActorContext:
    async with AsyncSession(engine) as database, database.begin():
        await database.execute(
            update(Person)
            .where(Person.id == state.person_id)
            .values(email="admin@authorityclosers.com", email_verified_at=state.now)
        )
        await database.execute(
            update(Membership)
            .where(
                Membership.tenant_id == state.tenant_id,
                Membership.person_id == state.person_id,
            )
            .values(role="owner")
        )
    return ActorContext(
        state.person_id,
        state.session_id,
        state.tenant_id,
        frozenset({"admin_surface"}),
    )


async def _setup(postgres_harness: Any, tmp_path: Path) -> AuthorityFixture:
    prepared = await prepare_local(postgres_harness, tmp_path)
    assert await prepared.worker.run_once(), "The synthetic C1 fixture did not complete."
    engine = create_async_engine(postgres_harness.url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        actor = await _promote_admin(engine, prepared.state)
        config = _registry_config("hosted-test-config-v1")
        async with sessions() as database, database.begin():
            config_view = await ConversationProviderAdmin(
                ConversationApplication(database, clock=lambda: prepared.state.now)
            ).save(actor, config.as_dict(), expected_revision=0, key="hosted-config-v1")
        config = parse_registry_config(config_view["configuration"])
        source_sha256 = prepared.state.source_sha256
        bundle = _bundle(
            prepared.state,
            source_sha256,
            config_view["configuration_sha256"],
            now_epoch=int(prepared.state.now.timestamp()),
        )
        bundle_box = {"bundle": bundle}
        authority = ConversationAuthority(
            lambda: bundle_box["bundle"],
            environment="test",
        )
        async with sessions() as database, database.begin():
            await authority.claim_allowance(
                ConversationApplication(database, clock=lambda: prepared.state.now), actor
            )
        broker = ReportingBroker(prepared.data)
        worker = ConversationInferenceWorker(
            sessions,
            prepared.storage,
            broker,
            authority=authority,
        )
        return AuthorityFixture(
            prepared,
            engine,
            sessions,
            actor,
            config,
            config_view,
            bundle,
            bundle_box,
            authority,
            broker,
            worker,
        )
    except BaseException:
        await engine.dispose()
        raise


def _application(setup: AuthorityFixture, database: AsyncSession) -> ConversationApplication:
    return ConversationApplication(database, clock=lambda: setup.prepared.state.now)


async def _issue(
    setup: AuthorityFixture,
    *,
    key: str,
    request: StageRequest | None = None,
    authority: ConversationAuthority | None = None,
    recording_id: UUID | None = None,
) -> dict[str, Any]:
    target_recording_id = recording_id or setup.prepared.recording_id
    async with setup.sessions() as database, database.begin():
        return await (authority or setup.authority).issue(
            _application(setup, database),
            setup.actor,
            target_recording_id,
            key=key,
            request=request,
        )


async def _start(
    setup: AuthorityFixture,
    quote: dict[str, Any],
    *,
    key: str,
    request: StageRequest | None = None,
) -> dict[str, Any]:
    async with setup.sessions() as database, database.begin():
        service = ConversationInference(_application(setup, database), authority=setup.authority)
        acceptance = QuoteAcceptance(
            quote_fingerprint=quote["quote_fingerprint"],
            privacy_revision=quote["privacy_revision"],
            accepted=True,
        )
        await service.accept(
            setup.actor,
            setup.prepared.recording_id,
            UUID(quote["id"]),
            acceptance,
            request=request,
        )
        if request is None:
            return await service.request_transcription(
                setup.actor,
                setup.prepared.recording_id,
                UUID(quote["id"]),
                key=key,
            )
        return await service.request_stage(
            setup.actor,
            setup.prepared.recording_id,
            UUID(quote["id"]),
            key=key,
            request=request,
        )


async def _counts(setup: AuthorityFixture) -> tuple[int, int, int]:
    async with setup.sessions() as database:
        tasks = await database.scalar(
            select(func.count())
            .select_from(ConversationInferenceTask)
            .where(
                ConversationInferenceTask.recording_id == setup.prepared.recording_id,
                ConversationInferenceTask.erased_at.is_(None),
            )
        )
        jobs = await database.scalar(
            select(func.count())
            .select_from(Job)
            .where(
                Job.kind == INFERENCE_JOB,
                Job.tenant_id == setup.prepared.state.tenant_id,
            )
        )
        acceptances = await database.scalar(
            select(func.count())
            .select_from(ConversationQuoteAcceptance)
            .where(ConversationQuoteAcceptance.tenant_id == setup.prepared.state.tenant_id)
        )
    return int(tasks or 0), int(jobs or 0), int(acceptances or 0)


def test_authority_claim_is_idempotent_and_quote_waits_for_consent(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            async with setup.sessions() as database, database.begin():
                await setup.authority.claim_allowance(_application(setup, database), setup.actor)
            async with setup.sessions() as database:
                minutes = await database.get(
                    ConversationMinuteAccount,
                    (setup.actor.tenant_id, setup.actor.person_id),
                )
                budget = await database.get(ConversationBudgetAccount, setup.bundle.budget_scope_id)
                assert minutes is not None and budget is not None
                account = MinuteAccount.from_dict(minutes.snapshot)
                allowance_ids = [
                    grant.grant_id
                    for grant in account.grants
                    if grant.grant_id == str(setup.bundle.allowances[0].id)
                ]
                assert allowance_ids == [str(setup.bundle.allowances[0].id)]
                budget_account = BudgetAccount.from_dict(budget.snapshot)
                assert budget_account.cap_paise == 0
                assert (
                    budget_account.cap_approval.approval_ref
                    == setup.bundle.budget_authorization_ref
                )

            quote = await _issue(setup, key="hosted-c2-quote")
            assert quote["stage"] == "C2"
            assert quote["provider"] == "elevenlabs"
            assert quote["model"] == "scribe_v2"
            assert quote["max_cost_paise"] == 0
            assert quote["accepted"] is False
            assert quote["input_sha256"] == setup.prepared.state.source_sha256
            assert await _counts(setup) == (0, 0, 0)

            run_view = await _start(setup, quote, key="hosted-c2-run")
            replayed_quote = await _issue(setup, key="hosted-c2-quote")
            assert replayed_quote["id"] == quote["id"]
            assert replayed_quote["accepted"] is True
            assert await setup.worker.run_once()
            assert await completed_checkpoint(setup.sessions, run_view)
            assert setup.broker.calls == 1
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_authority_runs_c2_c4_c5_and_reuses_cached_effect(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            c2_quote = await _issue(setup, key="hosted-pipeline-c2-quote")
            c2_run = await _start(setup, c2_quote, key="hosted-pipeline-c2-run")
            assert await setup.worker.run_once()
            c2 = await completed_checkpoint(setup.sessions, c2_run)

            duplicate_quote = await _issue(setup, key="hosted-pipeline-c2-duplicate")
            duplicate_run = await _start(
                setup, duplicate_quote, key="hosted-pipeline-c2-duplicate-run"
            )
            assert duplicate_run["id"] == c2_run["id"]
            assert await setup.worker.run_once() is False
            assert setup.broker.calls == 1

            facts_request = StageRequest(stage="C4", transcript_checkpoint_id=c2)
            c4_quote = await _issue(setup, key="hosted-pipeline-c4-quote", request=facts_request)
            c4_run = await _start(
                setup, c4_quote, key="hosted-pipeline-c4-run", request=facts_request
            )
            assert await setup.worker.run_once()
            c4 = await completed_checkpoint(setup.sessions, c4_run)

            coaching_request = StageRequest(
                stage="C5",
                transcript_checkpoint_id=c2,
                fact_checkpoint_ids=(c4,),
            )
            c5_quote = await _issue(setup, key="hosted-pipeline-c5-quote", request=coaching_request)
            c5_run = await _start(
                setup, c5_quote, key="hosted-pipeline-c5-run", request=coaching_request
            )
            assert await setup.worker.run_once()
            await completed_checkpoint(setup.sessions, c5_run)
            assert setup.broker.calls == 3

            # The local C1 source-audio reservation is the only user-minute
            # charge. Hosted C2/C4/C5 provider reservations stay zero-minute
            # records while provider request/budget controls still apply.
            async with setup.sessions() as database:
                minutes = await database.get(
                    ConversationMinuteAccount,
                    (setup.actor.tenant_id, setup.actor.person_id),
                )
                assert minutes is not None
                account = MinuteAccount.from_dict(minutes.snapshot)
                assert account.available_seconds == 599
                assert [
                    reservation.quote.entitlement_seconds
                    for reservation in account.reservations
                ] == [120, 0, 0, 0]

            async with setup.sessions() as database, database.begin():
                report = await ConversationReports(_application(setup, database)).get(
                    setup.actor, UUID(c5_run["id"])
                )
            assert report["report"] is not None
            assert report["report"]["summary"] == "A synthetic draft from saved facts."
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_authority_stage_max_requests_spans_same_source_on_second_recording(
    postgres_harness: Any, tmp_path: Path
) -> None:
    """One hosted C2 allowance cannot be multiplied by re-uploading the same WAV."""

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            first_quote = await _issue(setup, key="hosted-cap-first-quote")
            first_run = await _start(setup, first_quote, key="hosted-cap-first-run")
            assert await setup.worker.run_once()
            assert await completed_checkpoint(setup.sessions, first_run)
            assert setup.broker.calls == 1

            state = setup.prepared.state
            recording_intent = state.recording_intent.model_copy(
                update={"source_bytes": len(setup.prepared.data), "content_type": "audio/wav"}
            )
            async with setup.sessions() as database, database.begin():
                registered = await _application(setup, database).register(
                    setup.actor,
                    recording_intent,
                    key=f"hosted-cap-second-register-{uuid4().hex}",
                )
            second_recording_id = UUID(registered["id"])
            async with setup.sessions() as database, database.begin():
                stored = await _application(setup, database).store_source(
                    setup.actor,
                    second_recording_id,
                    chunks=(setup.prepared.data,),
                    storage=setup.prepared.storage,
                )
            assert stored["state"] == "ready"

            # Complete the second recording's local C1 through the actual
            # native fixture worker before asking hosted authority for C2.
            local_quote_id = await _add_quote(
                setup.sessions,
                state,
                second_recording_id,
                setup.prepared.scope_id,
                state.source_sha256,
            )
            async with setup.sessions() as database, database.begin():
                requested = await _application(setup, database).request_run(
                    setup.actor,
                    RunIntent(
                        recording_id=second_recording_id,
                        source_revision="1",
                        quote_id=local_quote_id,
                        recipe_revision=AUDIOATLAS_RECIPE,
                    ),
                    key=f"hosted-cap-second-c1-{uuid4().hex}",
                )
            local_run_id = UUID(requested["id"])
            assert await setup.prepared.worker.run_once()
            async with setup.sessions() as database:
                local_run = await database.get(ConversationRun, local_run_id)
                local_c1 = await database.scalar(
                    select(ConversationCheckpoint).where(
                        ConversationCheckpoint.recording_id == second_recording_id,
                        ConversationCheckpoint.stage == "C1",
                        ConversationCheckpoint.erased_at.is_(None),
                    )
                )
                assert local_run is not None and local_run.state == "completed"
                assert local_c1 is not None and local_c1.payload is not None

            with pytest.raises(ConversationDenied, match="allowance"):
                await _issue(
                    setup,
                    key="hosted-cap-second-quote",
                    recording_id=second_recording_id,
                )
            assert setup.broker.calls == 1
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_hosted_intake_http_rejects_capacity_after_existing_recording(
    postgres_harness: Any, tmp_path: Path
) -> None:
    """The cookie-authenticated intake quote uses the current hosted capacity."""

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        engine = setup.engine
        pepper = "synthetic-authority-http-session-pepper"
        token = secrets.token_urlsafe(32)
        settings = Settings(
            _env_file=None,
            environment="test",
            public_app_url="http://learner.test",
            admin_app_url="http://admin.test",
            coach_app_url="http://coach.test",
            api_url="http://api.test",
            session_token_pepper=pepper,
            oauth_transaction_secret=secrets.token_urlsafe(32),
            email_challenge_secret=secrets.token_urlsafe(32),
        )
        limited_allowance = setup.bundle.allowances[0].model_copy(update={"max_recordings": 1})
        setup.bundle_box["bundle"] = setup.bundle.model_copy(
            update={"allowances": (limited_allowance,)}
        )
        runtime = ConversationIntakeRuntime(
            IntakePolicy(
                setup.bundle.budget_scope_id,
                frozenset({setup.prepared.state.tenant_id}),
                setup.bundle.intake_authorization_ref,
                setup.bundle.intake_retention_ref,
                setup.bundle.retention_days,
            ),
            setup.prepared.storage,
            setup.prepared.scratch,
            authority=setup.authority,
        )
        app = FastAPI()
        require_actor = install_identity_http(app, settings=settings, sessions=setup.sessions)
        install_conversation_http(
            app,
            settings=settings,
            require_actor=require_actor,
            intake_runtime=runtime,
        )
        payload = {
            "source_sha256": setup.prepared.state.source_sha256,
            "source_bytes": len(setup.prepared.data),
            "content_type": "audio/wav",
            "duration_ms": 1_000,
            "purpose": "internal_analysis",
        }
        headers = {
            "Cookie": f"{settings.session_cookie_name}={token}",
            "Origin": "http://learner.test",
            "Idempotency-Key": "hosted-intake-capacity-http",
        }
        try:
            async with setup.sessions() as database, database.begin():
                await database.execute(
                    update(IdentitySession)
                    .where(IdentitySession.id == setup.prepared.state.session_id)
                    .values(
                        token_hash=hmac.new(
                            pepper.encode(), token.encode(), hashlib.sha256
                        ).digest()
                    )
                )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://learner.test"
            ) as client:
                response = await client.post(
                    "/v1/conversation/intake/quote", headers=headers, json=payload
                )
                oversized = await client.post(
                    "/v1/conversation/intake/quote",
                    headers={**headers, "Idempotency-Key": "hosted-oversized-source"},
                    json={**payload, "source_bytes": 32 * 1024 * 1024 + 1},
                )
            assert response.status_code == 409, response.text
            assert "capacity" in response.text.lower()
            assert oversized.status_code == 403
            assert "32 MB" in oversized.text
            assert setup.broker.calls == 0
            async with setup.sessions() as database:
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(ConversationRecording)
                        .where(
                            ConversationRecording.tenant_id == setup.prepared.state.tenant_id,
                            ConversationRecording.person_id == setup.prepared.state.person_id,
                        )
                    )
                    == 1
                )
        finally:
            await engine.dispose()

    run(exercise())


def test_authority_rejects_config_change_expired_or_unavailable_bundle_before_dispatch(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            quote = await _issue(setup, key="hosted-stale-quote")
            config_v2 = replace(setup.config, revision="hosted-test-config-v2")
            async with setup.sessions() as database, database.begin():
                changed = await ConversationProviderAdmin(_application(setup, database)).save(
                    setup.actor,
                    config_v2.as_dict(),
                    expected_revision=1,
                    key="hosted-config-v2",
                )
            with pytest.raises(ConversationDenied, match="approved"):
                await _start(setup, quote, key="hosted-stale-start")
            expired = _bundle(
                setup.prepared.state,
                setup.prepared.state.source_sha256,
                changed["configuration_sha256"],
                now_epoch=int(setup.prepared.state.now.timestamp()),
            ).model_copy(update={"expires_at_epoch": int(setup.prepared.state.now.timestamp()) - 1})
            expired_authority = ConversationAuthority(lambda: expired, environment="test")
            with pytest.raises(ConversationDenied):
                await _issue(
                    setup,
                    key="hosted-expired-bundle",
                    authority=expired_authority,
                )

            def unavailable() -> HostedApprovalBundle:
                raise ValueError("synthetic approval manifest unavailable")

            unavailable_authority = ConversationAuthority(unavailable, environment="test")
            with pytest.raises(ConversationDenied):
                await _issue(
                    setup,
                    key="hosted-unavailable-bundle",
                    authority=unavailable_authority,
                )
            assert setup.broker.calls == 0
            assert await _counts(setup) == (0, 0, 0)
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_queued_authority_task_is_fenced_after_bundle_expiry_before_dispatch(
    postgres_harness: Any, tmp_path: Path
) -> None:
    """A queued task must recheck the hosted approval at the worker boundary."""

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            quote = await _issue(setup, key="hosted-queued-revocation-quote")
            run_view = await _start(setup, quote, key="hosted-queued-revocation-run")

            expired = setup.bundle.model_copy(
                update={"expires_at_epoch": int(setup.prepared.state.now.timestamp()) - 1}
            )
            setup.bundle_box["bundle"] = expired

            # The job and acceptance already exist.  Expiry is checked again by
            # the worker's locked scope reconstruction, before the broker call.
            assert await setup.worker.run_once()
            assert setup.broker.calls == 0
            async with setup.sessions() as database:
                task = await database.scalar(
                    select(ConversationInferenceTask).where(
                        ConversationInferenceTask.run_id == UUID(run_view["id"]),
                    )
                )
                assert task is not None
                assert task.state == "failed"
                assert task.checkpoint_id is None
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(ConversationCheckpoint)
                        .where(
                            ConversationCheckpoint.recording_id == setup.prepared.recording_id,
                            ConversationCheckpoint.stage == "C2",
                        )
                    )
                    == 0
                )
        finally:
            await setup.engine.dispose()

    run(exercise())
