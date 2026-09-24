"""Disposable PostgreSQL proof for the hosted conversation authority boundary.

Approval references and provider configuration are synthetic fixtures. Tests
stop at durable admission, so no provider network, credentials, actual charge,
or production deployment is exercised.
"""

from __future__ import annotations

import asyncio
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
    AcquisitionProviderPolicy,
    AcquisitionStagePolicy,
    AllowanceApproval,
    HostedApprovalBundle,
    InternalTesterApproval,
    StageApproval,
)
from ac_platform.conversation_intelligence.application import (
    AUDIOATLAS_HOSTED_RECIPE,
    AUDIOATLAS_RECIPE,
    ConversationApplication,
    ConversationConflict,
    ConversationDenied,
)
from ac_platform.conversation_intelligence.authority import ConversationAuthority
from ac_platform.conversation_intelligence.budget_admin import ConversationBudgetAdmin
from ac_platform.conversation_intelligence.checkpoints import (
    build_checkpoint,
    canonical,
    content_hash,
)
from ac_platform.conversation_intelligence.contracts import QuoteAcceptance, RunIntent
from ac_platform.conversation_intelligence.entitlements import BudgetAccount, MinuteAccount
from ac_platform.conversation_intelligence.inference import (
    INFERENCE_JOB,
    TRANSCRIPT_RECIPE_BY_ROUTE,
    ConversationInference,
    binding_for,
)
from ac_platform.conversation_intelligence.inference_worker import ConversationInferenceWorker
from ac_platform.conversation_intelligence.intake import IntakePolicy
from ac_platform.conversation_intelligence.internal_tester import InternalTesterPolicy
from ac_platform.conversation_intelligence.models import (
    ConversationBudgetAccount,
    ConversationCheckpoint,
    ConversationCommand,
    ConversationInferenceTask,
    ConversationMinuteAccount,
    ConversationQuote,
    ConversationQuoteAcceptance,
    ConversationRecording,
    ConversationReportDraft,
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


def _refs(provider: str, *, paid: bool = False) -> dict[str, str | None]:
    return {
        "credential_ref": f"ref:credential:{provider}",
        "provider_terms_ref": f"ref:terms:{provider}",
        "privacy_ref": f"ref:privacy:{provider}",
        "pricing_ref": "ref:pricing:synthetic-zero",
        "free_allowance_ref": None if paid else f"ref:allowance:{provider}",
        "permission_ref": f"ref:permission:{provider}",
        "endpoint_approval_ref": f"ref:endpoint:{provider}",
    }


def _provider(
    provider: str, model: str, endpoint: str, *, max_cost_paise: int = 0
) -> ProviderConfig:
    return ProviderConfig(
        provider_id=provider,
        model_id=model,
        endpoint=endpoint,
        endpoint_sha256=hashlib.sha256(endpoint.encode()).hexdigest(),
        **_refs(provider, paid=max_cost_paise > 0),
        local_endpoint_approval_ref=None,
        max_cost_paise=max_cost_paise,
    )


def _registry_config(
    revision: str,
    *,
    funded: bool = False,
    text_provider: str = "groq",
    text_cost_paise: int = 0,
    asr_provider: str = "elevenlabs",
    asr_cost_paise: int = 50_000,
) -> RegistryConfig:
    asr_model = "nova-3" if asr_provider == "deepgram" else "scribe_v2"
    asr_endpoint = (
        "https://api.deepgram.com/v1/listen"
        if asr_provider == "deepgram"
        else "https://api.elevenlabs.io/v1/speech-to-text"
    )
    asr_recipe = TRANSCRIPT_RECIPE_BY_ROUTE[(asr_provider, asr_model)]
    text_model = "gemini-3.8-flash" if text_provider == "gemini" else "openai/gpt-oss-120b"
    text_endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent"
        if text_provider == "gemini"
        else "https://api.groq.com/openai/v1/chat/completions"
    )
    return RegistryConfig(
        revision=revision,
        policy=RegistryPolicy(
            allow_paid=funded,
            paid_approval_ref="ref:approval:hosted-paid" if funded else None,
        ),
        providers=(
            _provider(
                asr_provider,
                asr_model,
                asr_endpoint,
                max_cost_paise=asr_cost_paise if funded else 0,
            ),
            _provider(
                text_provider,
                text_model,
                text_endpoint,
                max_cost_paise=text_cost_paise,
            ),
        ),
        routes=(
            RouteConfig(
                "asr",
                asr_provider,
                asr_model,
                asr_recipe,
                "profile-none-v1",
                "prompt-asr-v1",
                "C0",
                None,
            ),
            RouteConfig(
                "facts",
                text_provider,
                text_model,
                FACT_RECIPE,
                "profile-none-v1",
                "prompt-facts-v1",
                "C2",
                "C2",
            ),
            RouteConfig(
                "coaching",
                text_provider,
                text_model,
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
    paid: bool = False,
    max_cost_paise: int = 0,
    max_source_duration_ms: int = 1_000,
) -> StageApproval:
    refs = _refs(provider, paid=paid)
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
        zero_cost_basis="paid_pricing_evidence" if paid else "synthetic",
        price_evidence_sha256="a" * 64,
        max_cost_paise=max_cost_paise,
        max_source_duration_ms=max_source_duration_ms,
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
    funded: bool = False,
    text_provider: str = "groq",
    text_cost_paise: int = 0,
    asr_provider: str = "elevenlabs",
    asr_cost_paise: int = 50_000,
    max_source_duration_ms: int = 1_000,
) -> HostedApprovalBundle:
    bundle_expires = expires_at_epoch or now_epoch + 3_600
    stage_expires = min(bundle_expires, now_epoch + 1_800)
    asr_model = "nova-3" if asr_provider == "deepgram" else "scribe_v2"
    asr_recipe = TRANSCRIPT_RECIPE_BY_ROUTE[(asr_provider, asr_model)]
    profile_sha256 = hashlib.sha256(canonical(load_report_profile())).hexdigest()
    return HostedApprovalBundle(
        schema="ac.sales-xray.hosted-approval/1",
        environment="test",
        provider_control_tenant_id=state.tenant_id,
        deployment_ref="ref:deployment:synthetic",
        issued_at_epoch=now_epoch - 1,
        expires_at_epoch=bundle_expires,
        budget_scope_id=uuid4(),
        budget_authorization_ref="ref:budget:synthetic-zero",
        budget_owner_id=state.person_id,
        budget_cap_paise=100_000 if funded else 0,
        paid_approval_ref="ref:approval:hosted-paid" if funded else None,
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
                provider=asr_provider,
                model=asr_model,
                recipe=asr_recipe,
                expires_at_epoch=stage_expires,
                entitlement_seconds=None,
                max_completion_tokens=0,
                profile_sha256=None,
                paid=funded,
                max_cost_paise=asr_cost_paise if funded else 0,
                max_source_duration_ms=max_source_duration_ms,
            ),
            _stage(
                state=state,
                source_sha256=source_sha256,
                config_sha256=config_sha256,
                stage="C4",
                provider=text_provider,
                model="gemini-3.8-flash" if text_provider == "gemini" else "openai/gpt-oss-120b",
                recipe=FACT_RECIPE,
                expires_at_epoch=stage_expires,
                entitlement_seconds=0,
                max_completion_tokens=4_000,
                profile_sha256=None,
                paid=text_cost_paise > 0,
                max_cost_paise=text_cost_paise,
                max_source_duration_ms=max_source_duration_ms,
            ),
            _stage(
                state=state,
                source_sha256=source_sha256,
                config_sha256=config_sha256,
                stage="C5",
                provider=text_provider,
                model="gemini-3.8-flash" if text_provider == "gemini" else "openai/gpt-oss-120b",
                recipe=COACHING_RECIPE,
                expires_at_epoch=stage_expires,
                entitlement_seconds=0,
                max_completion_tokens=4_000,
                profile_sha256=profile_sha256,
                paid=text_cost_paise > 0,
                max_cost_paise=text_cost_paise,
                max_source_duration_ms=max_source_duration_ms,
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


async def _setup(
    postgres_harness: Any,
    tmp_path: Path,
    *,
    funded: bool = False,
    text_provider: str = "groq",
    text_cost_paise: int = 0,
    asr_provider: str = "elevenlabs",
    duration_ms: int = 1_000,
    complete_local_fixture: bool = True,
) -> AuthorityFixture:
    prepared = await prepare_local(postgres_harness, tmp_path, duration_ms=duration_ms)
    if complete_local_fixture:
        assert await prepared.worker.run_once(), "The synthetic C1 fixture did not complete."
    engine = create_async_engine(postgres_harness.url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        actor = await _promote_admin(engine, prepared.state)
        config = _registry_config(
            "hosted-test-config-v1",
            funded=funded,
            text_provider=text_provider,
            text_cost_paise=text_cost_paise,
            asr_provider=asr_provider,
        )
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
            funded=funded,
            text_provider=text_provider,
            text_cost_paise=text_cost_paise,
            asr_provider=asr_provider,
            max_source_duration_ms=duration_ms,
        )
        bundle_box = {"bundle": bundle}
        authority = ConversationAuthority(
            lambda: bundle_box["bundle"],
            environment="test",
            operations_tenant_id=prepared.state.tenant_id,
        )
        if asr_provider == "deepgram":
            fields = (
                "stage",
                "configuration_sha256",
                "provider_id",
                "model_id",
                "recipe_revision",
                "permission_ref",
                "retention_ref",
                "professional_gate_ref",
                "pricing_ref",
                "provider_terms_ref",
                "privacy_ref",
                "credential_ref",
                "free_allowance_ref",
                "no_paid_overage_ref",
                "privacy_revision",
                "privacy_notice",
                "expires_at_epoch",
                "max_requests",
                "entitlement_seconds",
                "zero_cost_basis",
                "price_evidence_sha256",
                "max_cost_paise",
                "max_source_duration_ms",
                "max_input_bytes",
                "max_completion_tokens",
                "profile_sha256",
            )
            policy = AcquisitionProviderPolicy(
                schema="ac.sales-xray.acquisition-provider-policy/1",
                id=uuid4(),
                tenant_id=prepared.state.tenant_id,
                processing_person_id=prepared.state.person_id,
                authorization_ref="ref:approval/acquisition-deepgram-test",
                expires_at_epoch=bundle.expires_at_epoch - 1,
                max_recordings=64,
                max_source_bytes=134_217_728,
                max_stored_source_bytes=8_589_934_592,
                stages=tuple(
                    AcquisitionStagePolicy(**{field: getattr(stage, field) for field in fields})
                    for stage in bundle.stages
                ),
            )
            bundle = bundle.model_copy(update={"acquisition_policy": policy})
            bundle_box["bundle"] = bundle
            async with sessions() as database, database.begin():
                await ConversationProviderAdmin(
                    ConversationApplication(database, clock=lambda: prepared.state.now)
                ).activate(
                    actor,
                    target_revision=1,
                    expected_revision=1,
                    key="hosted-config-activation-v1",
                    bundle=bundle,
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
    recording_id: UUID | None = None,
) -> dict[str, Any]:
    target_recording_id = recording_id or setup.prepared.recording_id
    async with setup.sessions() as database, database.begin():
        service = ConversationInference(_application(setup, database), authority=setup.authority)
        acceptance = QuoteAcceptance(
            quote_fingerprint=quote["quote_fingerprint"],
            privacy_revision=quote["privacy_revision"],
            accepted=True,
        )
        await service.accept(
            setup.actor,
            target_recording_id,
            UUID(quote["id"]),
            acceptance,
            request=request,
        )
        if request is None:
            return await service.request_transcription(
                setup.actor,
                target_recording_id,
                UUID(quote["id"]),
                key=key,
            )
        return await service.request_stage(
            setup.actor,
            target_recording_id,
            UUID(quote["id"]),
            key=key,
            request=request,
        )


async def _duplicate_ready_recording(setup: AuthorityFixture, key: str) -> UUID:
    intent = setup.prepared.state.recording_intent.model_copy(
        update={"source_bytes": len(setup.prepared.data), "content_type": "audio/wav"}
    )
    async with setup.sessions() as database, database.begin():
        registered = await _application(setup, database).register(
            setup.actor, intent, key=f"{key}-register"
        )
    recording_id = UUID(registered["id"])
    async with setup.sessions() as database, database.begin():
        stored = await _application(setup, database).store_source(
            setup.actor,
            recording_id,
            chunks=(setup.prepared.data,),
            storage=setup.prepared.storage,
        )
    assert stored["state"] == "ready"
    return recording_id


def _grant_provider_stage_request_count_scope(setup: AuthorityFixture) -> None:
    approval = InternalTesterApproval(
        id=uuid4(),
        email="dipak@authorityclosers.com",
        authorization_ref="ref:approval:provider-stage-count-test",
        scopes=("provider_stage_request_count",),
        reason="Approved internal tester exemption",
    )
    bundle = setup.bundle_box["bundle"].model_copy(update={"internal_tester_accounts": (approval,)})
    setup.bundle_box["bundle"] = bundle
    setup.authority.tester_policy = InternalTesterPolicy(lambda: setup.bundle_box["bundle"], "test")


async def _seed_transcription_inputs(setup: AuthorityFixture, recording_id: UUID) -> None:
    async with setup.sessions() as database, database.begin():
        recording = await database.get(ConversationRecording, recording_id)
        assert recording is not None
        binding = binding_for(recording)
        c0_payload = {
            "source_sha256": recording.source_sha256,
            "source_bytes": recording.source_bytes,
            "content_type": recording.content_type,
            "permission_reference": str(recording.permission_id),
        }
        c0 = build_checkpoint(binding, "C0", "recording-v1", {}, (), content_hash(c0_payload))
        c1_payload = {
            "source_sha256": recording.source_sha256,
            "media_duration_ms": 1_000,
        }
        c1 = build_checkpoint(
            binding,
            "C1",
            AUDIOATLAS_HOSTED_RECIPE,
            {"decode_rate": 16_000, "window_profile": "audioatlas-40ms-10ms"},
            (c0,),
            content_hash(c1_payload),
        )
        for checkpoint, payload in ((c0, c0_payload), (c1, c1_payload)):
            database.add(
                ConversationCheckpoint(
                    id=uuid4(),
                    tenant_id=recording.tenant_id,
                    person_id=recording.person_id,
                    recording_id=recording.id,
                    cache_key=checkpoint.cache_key,
                    manifest_sha256=checkpoint.manifest_sha256,
                    payload_sha256=checkpoint.payload_sha256,
                    stage=checkpoint.stage,
                    manifest=checkpoint.as_dict(),
                    payload=payload,
                    created_at=setup.prepared.state.now,
                )
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


def test_paid_hosted_quote_uses_project_cap_and_preserves_uncertain_hold(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path, funded=True)
        try:
            quote = await _issue(setup, key="funded-hosted-c2-quote")
            assert quote["max_cost_paise"] == 50_000
            assert quote["budget_cap_paise"] == 100_000
            assert quote["cost_label"] == "up to ₹500.00 · approved project cap"

            run_view = await _start(setup, quote, key="funded-hosted-c2-run")
            assert await setup.worker.run_once()
            assert await completed_checkpoint(setup.sessions, run_view)

            async with setup.sessions() as database:
                budget_row = await database.get(
                    ConversationBudgetAccount, setup.bundle.budget_scope_id
                )
                assert budget_row is not None
                budget = BudgetAccount.from_dict(budget_row.snapshot)
                reservation = budget.reservations[0]
                assert reservation.state == "uncertain"
                assert reservation.committed_paise == 50_000
                assert budget.available_paise == 50_000
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_authority_runs_c2_c4_c5_and_reuses_cached_effect(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            async with setup.sessions() as database:
                minutes_before = await database.get(
                    ConversationMinuteAccount,
                    (setup.actor.tenant_id, setup.actor.person_id),
                )
                assert minutes_before is not None
                audio_balance = MinuteAccount.from_dict(minutes_before.snapshot).available_seconds
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
                assert account.available_seconds == audio_balance
                assert [
                    reservation.quote.entitlement_seconds for reservation in account.reservations
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


def test_deepgram_native_tail_is_bounded_through_c3_c5_and_report_read(
    postgres_harness: Any, tmp_path: Path
) -> None:
    """A tolerated native tail stays in C2 proof and is bounded for playback consumers."""

    async def exercise() -> None:
        setup = await _setup(
            postgres_harness,
            tmp_path,
            asr_provider="deepgram",
            duration_ms=60_000,
        )
        setup.broker.deepgram_tail_ms = 135
        try:
            c2_quote = await _issue(setup, key="deepgram-tail-c2-quote")
            c2_run = await _start(setup, c2_quote, key="deepgram-tail-c2-run")
            assert await setup.worker.run_once()
            c2 = await completed_checkpoint(setup.sessions, c2_run)
            async with setup.sessions() as database, database.begin():
                early = await ConversationReports(_application(setup, database)).transcript(
                    setup.actor, setup.prepared.recording_id
                )
                assert early["duration_ms"] == 60_000
                assert early["segments"][-1]["end_ms"] == 60_000
                assert "playback_projection" not in early

            facts_request = StageRequest(stage="C4", transcript_checkpoint_id=c2)
            c4_quote = await _issue(setup, key="deepgram-tail-c4-quote", request=facts_request)
            c4_run = await _start(
                setup, c4_quote, key="deepgram-tail-c4-run", request=facts_request
            )
            assert await setup.worker.run_once()
            c4 = await completed_checkpoint(setup.sessions, c4_run)

            coaching_request = StageRequest(
                stage="C5", transcript_checkpoint_id=c2, fact_checkpoint_ids=(c4,)
            )
            c5_quote = await _issue(setup, key="deepgram-tail-c5-quote", request=coaching_request)
            c5_run = await _start(
                setup, c5_quote, key="deepgram-tail-c5-run", request=coaching_request
            )
            assert await setup.worker.run_once()

            async with setup.sessions() as database, database.begin():
                c2_row = await database.get(ConversationCheckpoint, c2)
                c3_row = await database.scalar(
                    select(ConversationCheckpoint).where(
                        ConversationCheckpoint.recording_id == setup.prepared.recording_id,
                        ConversationCheckpoint.stage == "C3",
                    )
                )
                assert c2_row is not None and c2_row.payload is not None
                assert c3_row is not None and c3_row.payload is not None
                assert c2_row.payload["duration_ms"] == 60_000
                assert c2_row.payload["segments"][-1]["end_ms"] == 60_135
                assert c3_row.payload["duration_ms"] == 60_000
                assert c3_row.payload["segments"][-1]["end_ms"] == 60_000
                assert c3_row.payload["playback_projection"]["segments"][-1] == {
                    "id": "s2",
                    "native_start_ms": 54_135,
                    "native_end_ms": 60_135,
                    "playback_start_ms": 54_135,
                    "playback_end_ms": 60_000,
                }
                reports = ConversationReports(_application(setup, database))
                response = await reports.get(setup.actor, UUID(c5_run["id"]))
                transcript = await reports.transcript(setup.actor, setup.prepared.recording_id)
                draft = await database.scalar(
                    select(ConversationReportDraft).where(
                        ConversationReportDraft.run_id == UUID(c5_run["id"]),
                    )
                )
                assert response["report"]["review_status"] == "draft_not_dipak_adjudicated"
                assert transcript["duration_ms"] == 60_000
                assert transcript["segments"][-1]["end_ms"] == 60_000
                assert "playback_projection" not in transcript
                assert draft is not None and draft.transcript is not None
                assert draft.transcript["native"]["segments"][-1]["end_ms"] == 60_135
            assert setup.broker.routes == ["deepgram", "groq", "groq"]
            assert setup.broker.calls == 3
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


def test_named_provider_request_scope_keeps_budget_and_uncertain_stage_holds(
    postgres_harness: Any, tmp_path: Path
) -> None:
    """The named source owner can exceed count caps, not budget or dispatch holds."""

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path, funded=True)
        try:
            async with setup.sessions() as database, database.begin():
                await database.execute(
                    update(Person)
                    .where(Person.id == setup.actor.person_id)
                    .values(email="dipak@authorityclosers.com")
                )
            _grant_provider_stage_request_count_scope(setup)

            first_quote = await _issue(setup, key="named-provider-count-first-quote")
            assert first_quote["max_cost_paise"] == 50_000
            first_run = await _start(setup, first_quote, key="named-provider-count-first-run")
            assert await setup.worker.run_once()
            assert await completed_checkpoint(setup.sessions, first_run)
            assert setup.broker.calls == 1

            second_recording_id = await _duplicate_ready_recording(
                setup, "named-provider-count-second"
            )
            await _seed_transcription_inputs(setup, second_recording_id)
            second_quote = await _issue(
                setup,
                key="named-provider-count-second-quote",
                recording_id=second_recording_id,
            )
            assert second_quote["max_cost_paise"] == 50_000

            # An unknown provider outcome remains held. The new count scope
            # cannot turn the same recording/stage into a second dispatch.
            setup.broker.mode = "failure"
            second_run = await _start(
                setup,
                second_quote,
                key="named-provider-count-second-run",
                recording_id=second_recording_id,
            )
            assert await setup.worker.run_once()
            assert setup.broker.calls == 2
            async with setup.sessions() as database:
                uncertain = await database.get(ConversationInferenceTask, UUID(second_run["id"]))
                assert uncertain is not None and uncertain.state == "uncertain"
                job = await database.get(Job, uncertain.job_id)
                assert job is not None and job.dispatch_started_at is not None

            retry_quote = await _issue(
                setup,
                key="named-provider-count-same-stage-recheck",
                recording_id=second_recording_id,
            )
            with pytest.raises(
                ConversationConflict,
                match="previous stage requires explicit recovery",
            ):
                await _start(
                    setup,
                    retry_quote,
                    key="named-provider-count-new-attempt",
                    recording_id=second_recording_id,
                )
            retry_run = await _start(
                setup,
                second_quote,
                key="named-provider-count-second-run",
                recording_id=second_recording_id,
            )
            assert retry_run["id"] == second_run["id"]
            assert await setup.worker.run_once() is False
            assert setup.broker.calls == 2

            third_recording_id = await _duplicate_ready_recording(
                setup, "named-provider-count-third"
            )
            await _seed_transcription_inputs(setup, third_recording_id)
            with pytest.raises(
                ConversationConflict,
                match="remaining approved processing allowance",
            ):
                await _issue(
                    setup,
                    key="named-provider-count-budget-exhausted",
                    recording_id=third_recording_id,
                )
            async with setup.sessions() as database:
                budget = await database.get(ConversationBudgetAccount, setup.bundle.budget_scope_id)
                assert budget is not None
                reservations = BudgetAccount.from_dict(budget.snapshot).reservations
                assert len(reservations) == 2
                assert all(item.state == "uncertain" for item in reservations)
                assert sum(item.committed_paise for item in reservations) == 100_000
            assert setup.broker.calls == 2
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_carried_budget_cap_does_not_expand_current_release_admission(
    postgres_harness: Any, tmp_path: Path
) -> None:
    """A carried Admin ledger must not admit cumulative work above the current release cap."""

    async def exercise() -> None:
        setup = await _setup(
            postgres_harness,
            tmp_path,
            funded=True,
            complete_local_fixture=False,
        )
        try:
            original_bundle = setup.bundle
            historical_bundle = original_bundle.model_copy(update={"budget_cap_paise": 250_000})
            async with setup.sessions() as database, database.begin():
                saved = await ConversationBudgetAdmin(
                    _application(setup, database),
                    environment="test",
                    operations_tenant_id=setup.actor.tenant_id,
                ).save(
                    setup.actor,
                    bundle=historical_bundle,
                    new_cap_paise=250_000,
                    expected_revision=1,
                    reason="Synthetic carried-cap regression fixture",
                    key="risk22-historical-cap",
                )
                assert saved["budget"]["cap_paise"] == 250_000

            config = _registry_config("hosted-test-config-v2", funded=True)
            config = replace(
                config,
                providers=tuple(
                    replace(provider, max_cost_paise=60_000)
                    if provider.provider_id == "elevenlabs"
                    else provider
                    for provider in config.providers
                ),
            )
            async with setup.sessions() as database, database.begin():
                config_view = await ConversationProviderAdmin(_application(setup, database)).save(
                    setup.actor,
                    config.as_dict(),
                    expected_revision=1,
                    key="risk22-config-v2",
                )
            config = parse_registry_config(config_view["configuration"])
            current_stages = tuple(
                stage.model_copy(
                    update={
                        "configuration_sha256": config.digest,
                        "max_cost_paise": 60_000,
                        "max_requests": 2,
                    }
                )
                if stage.stage == "C2"
                else stage
                for stage in original_bundle.stages
            )
            current_bundle = original_bundle.model_copy(update={"stages": current_stages})
            setup.bundle_box["bundle"] = current_bundle
            async with setup.sessions() as database, database.begin():
                await setup.authority.claim_allowance(_application(setup, database), setup.actor)

            second_recording_id = await _duplicate_ready_recording(setup, "risk22-second")
            await _seed_transcription_inputs(setup, setup.prepared.recording_id)
            await _seed_transcription_inputs(setup, second_recording_id)

            # Both quotes are issued against the same untouched 250,000 ledger.
            first_quote = await _issue(
                setup, key="risk22-first-quote", recording_id=setup.prepared.recording_id
            )
            second_quote = await _issue(
                setup, key="risk22-second-quote", recording_id=second_recording_id
            )
            assert first_quote["max_cost_paise"] == second_quote["max_cost_paise"] == 60_000

            outcomes = await asyncio.gather(
                _start(
                    setup,
                    first_quote,
                    key="risk22-first-run",
                    recording_id=setup.prepared.recording_id,
                ),
                _start(
                    setup,
                    second_quote,
                    key="risk22-second-run",
                    recording_id=second_recording_id,
                ),
                return_exceptions=True,
            )
            assert sum(isinstance(result, dict) for result in outcomes) == 1
            conflicts = [result for result in outcomes if isinstance(result, ConversationConflict)]
            assert len(conflicts) == 1
            assert "allowance" in str(conflicts[0])

            async with setup.sessions() as database:
                row = await database.get(ConversationBudgetAccount, current_bundle.budget_scope_id)
                assert row is not None
                ledger = BudgetAccount.from_dict(row.snapshot)
                jobs = await database.scalar(
                    select(func.count())
                    .select_from(Job)
                    .where(
                        Job.kind == INFERENCE_JOB,
                        Job.tenant_id == setup.prepared.state.tenant_id,
                    )
                )
            assert ledger.cap_paise == 250_000
            assert sum(item.committed_paise for item in ledger.reservations) == 60_000
            assert jobs == 1
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
            assert oversized.status_code == 422
            assert any(
                error["loc"] == ["body", "source_bytes"]
                and error["type"] == "less_than_equal"
                and error["ctx"]["le"] == 32 * 1024 * 1024
                for error in oversized.json()["detail"]
            )
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


def test_authority_pins_saved_draft_and_rejects_changed_expired_or_unavailable_approval(
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
            # Saving a draft must not activate it or invalidate an approved quote.
            fresh_quote = await _issue(setup, key="hosted-after-draft-quote")
            run_view = await _start(setup, quote, key="hosted-pinned-start")
            async with setup.sessions() as database:
                for issued in (quote, fresh_quote):
                    row = await database.get(ConversationQuote, UUID(issued["id"]))
                    assert row is not None
                    assert (
                        row.quote["provider_configuration_sha256"]
                        == setup.config_view["configuration_sha256"]
                        != changed["configuration_sha256"]
                    )
                task = await database.get(ConversationInferenceTask, UUID(run_view["id"]))
                assert task is not None and task.quote_id == UUID(quote["id"])
                assert task.state == "queued"
            assert await _counts(setup) == (1, 1, 1)

            # Removing the pinned route from the current approval is different:
            # even the existing queued quote must be revalidated and refused.
            setup.bundle_box["bundle"] = setup.bundle.model_copy(
                update={
                    "stages": tuple(
                        stage.model_copy(
                            update={"configuration_sha256": changed["configuration_sha256"]}
                        )
                        for stage in setup.bundle.stages
                    )
                }
            )
            with pytest.raises(ConversationDenied, match="need current approval"):
                await _start(setup, quote, key="hosted-changed-approval-start")
            expired = _bundle(
                setup.prepared.state,
                setup.prepared.state.source_sha256,
                changed["configuration_sha256"],
                now_epoch=int(setup.prepared.state.now.timestamp()),
            ).model_copy(update={"expires_at_epoch": int(setup.prepared.state.now.timestamp()) - 1})
            expired_authority = ConversationAuthority(
                lambda: expired, environment="test", operations_tenant_id=setup.actor.tenant_id
            )
            with pytest.raises(ConversationDenied):
                await _issue(
                    setup,
                    key="hosted-expired-bundle",
                    authority=expired_authority,
                )

            def unavailable() -> HostedApprovalBundle:
                raise ValueError("synthetic approval manifest unavailable")

            unavailable_authority = ConversationAuthority(
                unavailable, environment="test", operations_tenant_id=setup.actor.tenant_id
            )
            with pytest.raises(ConversationDenied):
                await _issue(
                    setup,
                    key="hosted-unavailable-bundle",
                    authority=unavailable_authority,
                )
            assert setup.broker.calls == 0
            assert await _counts(setup) == (1, 1, 1)
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_provider_activation_replay_survives_later_draft_and_binds_original_command(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        # This control-plane test needs the saved provider record, not the
        # unrelated offline C1 worker. Keep its setup synthetic and provider-free.
        setup = await _setup(
            postgres_harness,
            tmp_path,
            asr_provider="deepgram",
            complete_local_fixture=False,
        )
        try:
            legacy_intent = {
                "target_revision": 1,
                "configuration_sha256": setup.config_view["configuration_sha256"],
                "approval_bundle_sha256": setup.bundle.digest,
            }
            async with setup.sessions() as database:
                command = await database.scalar(
                    select(ConversationCommand).where(
                        ConversationCommand.tenant_id == setup.actor.tenant_id,
                        ConversationCommand.person_id == setup.actor.person_id,
                        ConversationCommand.key == "hosted-config-activation-v1",
                    )
                )
                assert command is not None
                assert command.intent_sha256 == content_hash(legacy_intent)
                command_id = command.id

            async with setup.sessions() as database, database.begin():
                first = await ConversationProviderAdmin(_application(setup, database)).current(
                    setup.actor, bundle=setup.bundle
                )
            assert first is not None and first["activation"] is not None

            later = replace(setup.config, revision="hosted-test-config-v2")
            async with setup.sessions() as database, database.begin():
                await ConversationProviderAdmin(_application(setup, database)).save(
                    setup.actor,
                    later.as_dict(),
                    expected_revision=1,
                    key="hosted-config-v2",
                )

            async with setup.sessions() as database, database.begin():
                service = ConversationProviderAdmin(_application(setup, database))
                replay = await service.activate(
                    setup.actor,
                    target_revision=1,
                    expected_revision=1,
                    key="hosted-config-activation-v1",
                    bundle=setup.bundle,
                )
                assert replay["revision"] == 2
                assert replay["activation"] == first["activation"]

                changed_approval = setup.bundle.model_copy(
                    update={"issued_at_epoch": setup.bundle.issued_at_epoch - 1}
                )
                with pytest.raises(ConversationConflict, match="different command"):
                    await service.activate(
                        setup.actor,
                        target_revision=1,
                        expected_revision=2,
                        key="hosted-config-activation-v1",
                        bundle=changed_approval,
                    )

                with pytest.raises(ConversationConflict, match="changed"):
                    await service.activate(
                        setup.actor,
                        target_revision=1,
                        expected_revision=1,
                        key="hosted-config-activation-new-key",
                        bundle=setup.bundle,
                    )
            async with setup.sessions() as database:
                command = await database.scalar(
                    select(ConversationCommand).where(
                        ConversationCommand.tenant_id == setup.actor.tenant_id,
                        ConversationCommand.person_id == setup.actor.person_id,
                        ConversationCommand.key == "hosted-config-activation-v1",
                    )
                )
                assert command is not None
                assert command.id == command_id
                assert command.intent_sha256 == content_hash(legacy_intent)
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
