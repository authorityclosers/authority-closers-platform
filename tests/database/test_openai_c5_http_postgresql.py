"""Disposable PostgreSQL proof for the canonical OpenAI C5 HTTP/worker path.

All C1/C2/C4/C5 inputs and provider responses are synthetic local fixtures.
The test exercises the real authenticated HTTP routes and durable worker,
without credentials, provider network calls, or paid effects.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, update

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.activation_contract import HostedApprovalBundle
from ac_platform.conversation_intelligence.application import ConversationApplication
from ac_platform.conversation_intelligence.broker_router import (
    FixedProviderRouter,
    ProviderRoute,
)
from ac_platform.conversation_intelligence.checkpoints import canonical
from ac_platform.conversation_intelligence.entitlements import (
    BudgetAccount,
    MinuteAccount,
    Quote,
)
from ac_platform.conversation_intelligence.inference import INFERENCE_JOB
from ac_platform.conversation_intelligence.inference_worker import ConversationInferenceWorker
from ac_platform.conversation_intelligence.models import (
    ConversationAnalysisSettings,
    ConversationBudgetAccount,
    ConversationCheckpoint,
    ConversationInferenceTask,
    ConversationMinuteAccount,
    ConversationPermission,
    ConversationQuote,
    ConversationQuoteAcceptance,
    ConversationReportDraft,
)
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.conversation_intelligence.provider_registry import parse_registry_config
from ac_platform.conversation_intelligence.providers import ProviderResult
from ac_platform.conversation_intelligence.reports import load_report_profile
from ac_platform.conversation_intelligence.storage import ObjectKey, ObjectKind
from ac_platform.http.auth import install_identity_http
from ac_platform.http.conversation import install_conversation_http
from ac_platform.http.conversation_intake import ConversationIntakeRuntime, IntakePolicy
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.outbox.models import Job
from tests.conversation_overview_fixtures import overview_for
from tests.database.test_conversation_authority_postgresql import (
    _application,
    _provider,
    _setup,
)
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_reporting_pipeline_postgresql import ReportingBroker
from tests.database.test_conversation_worker_postgresql import _postgres_harness


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


def _analysis_settings(
    setup: Any, revision: int, *, language: str = "en"
) -> ConversationAnalysisSettings:
    now = setup.prepared.state.now
    return ConversationAnalysisSettings(
        id=uuid4(),
        tenant_id=setup.authority.operations_tenant_id,
        person_id=setup.actor.person_id,
        session_id=setup.actor.session_id,
        revision=revision,
        c4_max_requests=64,
        c4_max_completion_tokens=1_400,
        c5_max_completion_tokens=8_000,
        c5_output_profile="detailed",
        c5_coaching_prompt_revision="coaching-v5",
        report_language_default=language,
        created_at=now,
    )


async def _configure_openai_c5(setup: Any) -> None:
    config_data = setup.config.as_dict()
    config_data["revision"] = "hosted-openai-c5-http-test-v1"
    openai_config = _provider("openai", "gpt-6-luna", "https://api.openai.com/v1/responses")
    config_data["providers"].append(openai_config.as_dict())
    for route in config_data["routes"]:
        if route["task"] == "coaching":
            route["provider_id"] = "openai"
            route["model_id"] = "gpt-6-luna"
    config = parse_registry_config(config_data)
    async with setup.sessions() as database, database.begin():
        saved = await ConversationProviderAdmin(_application(setup, database)).save(
            setup.actor,
            config.as_dict(),
            expected_revision=1,
            key="openai-c5-http-config-v1",
        )
    assert saved["configuration_sha256"] == config.digest

    openai_refs = {
        "provider_id": openai_config.provider_id,
        "model_id": openai_config.model_id,
        "credential_ref": openai_config.credential_ref,
        "permission_ref": openai_config.permission_ref,
        "provider_terms_ref": openai_config.provider_terms_ref,
        "privacy_ref": openai_config.privacy_ref,
        "pricing_ref": openai_config.pricing_ref,
        "free_allowance_ref": openai_config.free_allowance_ref,
    }
    stages = []
    for stage in setup.bundle.stages:
        update: dict[str, Any] = {"configuration_sha256": config.digest}
        if stage.stage == "C5":
            update.update(
                openai_refs,
                max_completion_tokens=8_000,
                max_input_bytes=255_000,
            )
        stages.append(stage.model_copy(update=update))
    new_bundle = HostedApprovalBundle.model_validate_json(
        setup.bundle.model_copy(update={"stages": tuple(stages)}).to_json()
    )
    setup.bundle_box["bundle"] = new_bundle


def _coaching_output() -> dict[str, Any]:
    profile = load_report_profile()
    result: dict[str, Any] = {
        "summary": "Synthetic qualitative draft for human review.",
        "strengths": [],
        "missed_opportunities": [],
        "improvements": [],
        "objection_analysis": [],
        "closing_analysis": [],
        "verdict": "The synthetic source does not establish a sales outcome.",
        "review_status": "draft_not_dipak_adjudicated",
        "dimensions": [
            {
                "dimension_id": dimension["id"],
                "status": "insufficient_evidence",
                "observation": "The synthetic source does not establish this dimension.",
                "evidence": [],
            }
            for dimension in profile["dimensions"]
        ],
    }
    result["overview"] = overview_for(result)
    return result


class OpenAIC5ReportingBroker(ReportingBroker):
    reported_model = "gpt-6-luna"

    async def execute(self, reservation: Any, payload: bytes) -> ProviderResult:
        if reservation.quote.provider_id != "openai":
            return await super().execute(reservation, payload)
        self.routes.append("openai")
        self.calls += 1
        self.payloads.append(payload)
        body = json.loads(payload)
        assert body["model"] == "gpt-6-luna"
        assert body["reasoning"] == {"effort": "low"}
        assert body["store"] is False and body["background"] is False
        usage = {
            "input_tokens": 128,
            "output_tokens": 96,
            "total_tokens": 224,
            "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 32},
        }
        response = {
            "object": "response",
            "model": self.reported_model,
            "status": "completed",
            "incomplete_details": None,
            "error": None,
            "store": False,
            "service_tier": "default",
            "usage": usage,
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(_coaching_output(), ensure_ascii=False),
                        }
                    ],
                }
            ],
        }
        raw = canonical(response)
        return ProviderResult(
            provider="openai",
            model=reservation.quote.provider_model,
            request_id=f"synthetic-openai-{self.calls}",
            response_sha256=hashlib.sha256(raw).hexdigest(),
            raw_json=raw,
            data=response,
            usage={
                "input_tokens": 128,
                "output_tokens": 96,
                "total_tokens": 224,
                "cached_tokens": 0,
                "cache_write_tokens": 0,
                "reasoning_tokens": 32,
            },
            input_sha256=reservation.quote.input_sha256,
        )


async def _insert_settings(setup: Any, revision: int, *, language: str = "en") -> None:
    row = _analysis_settings(setup, revision, language=language)
    async with setup.sessions() as database, database.begin():
        database.add(row)


async def _http_start(
    client: httpx.AsyncClient,
    recording_id: UUID,
    selection: dict[str, Any],
    *,
    key: str,
) -> dict[str, Any]:
    quoted = await client.post(
        f"/v1/conversation/recordings/{recording_id}/analysis/quote",
        json=selection,
        headers={"Idempotency-Key": f"{key}-quote"},
    )
    assert quoted.status_code == 201, quoted.text
    quote = quoted.json()
    started = await client.post(
        f"/v1/conversation/recordings/{recording_id}/analysis",
        json={
            "quote_id": quote["id"],
            "selection": selection,
            "quote_fingerprint": quote["quote_fingerprint"],
            "privacy_revision": quote["privacy_revision"],
            "accepted": True,
        },
        headers={"Idempotency-Key": f"{key}-start"},
    )
    assert started.status_code == 202, started.text
    return started.json()


async def _checkpoints(setup: Any, stage: str) -> UUID:
    async with setup.sessions() as database:
        task = await database.scalar(
            select(ConversationInferenceTask).where(
                ConversationInferenceTask.recording_id == setup.prepared.recording_id,
                ConversationInferenceTask.stage == stage,
            )
        )
        job = None if task is None else await database.get(Job, task.job_id)
        assert task is not None and task.state == "completed", (
            None
            if task is None
            else f"task={task.state}; job={None if job is None else (job.status, job.last_error)}"
        )
        assert task.checkpoint_id is not None
        return task.checkpoint_id


@pytest.mark.parametrize("reported_model", ["gpt-6-luna", "gpt-6-sol"])
def test_http_openai_c5_reuses_checkpoints_and_fences_settings_and_scope(
    postgres_harness: Any, tmp_path: Path, reported_model: str
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path, text_provider="gemini")
        try:
            await _configure_openai_c5(setup)
            await _insert_settings(setup, 1)

            provider_child = OpenAIC5ReportingBroker(setup.prepared.data)
            provider_child.reported_model = reported_model
            router = FixedProviderRouter(
                {
                    provider: ProviderRoute(
                        provider,
                        f"ref:credential:{provider}",
                        provider_child,
                    )
                    for provider in ("elevenlabs", "gemini", "openai")
                },
                authority=setup.authority,
                clock=lambda: datetime.now(UTC),
            )
            worker = ConversationInferenceWorker(
                setup.sessions,
                setup.prepared.storage,
                router,
                authority=setup.authority,
                clock=lambda: datetime.now(UTC),
            )

            origin = "http://sales-xray.test"
            pepper = "synthetic-openai-c5-http-cookie-pepper"
            token = secrets.token_urlsafe(32)
            settings = Settings(
                _env_file=None,
                environment="test",
                public_app_url=origin,
                admin_app_url="http://admin.test",
                coach_app_url="http://coach.test",
                api_url=origin,
                session_token_pepper=pepper,
                oauth_transaction_secret=secrets.token_urlsafe(32),
                email_challenge_secret=secrets.token_urlsafe(32),
            )
            async with setup.sessions() as database, database.begin():
                await database.execute(
                    update(IdentitySession)
                    .where(IdentitySession.id == setup.actor.session_id)
                    .values(
                        token_hash=hmac.new(
                            pepper.encode(), token.encode(), hashlib.sha256
                        ).digest()
                    )
                )

            app = FastAPI()
            require_actor = install_identity_http(app, settings=settings, sessions=setup.sessions)
            bundle = setup.bundle
            intake_runtime = ConversationIntakeRuntime(
                policy=IntakePolicy(
                    budget_scope_id=bundle.budget_scope_id,
                    tenant_ids=frozenset(item.tenant_id for item in bundle.allowances),
                    authorization_ref=bundle.intake_authorization_ref,
                    retention_ref=bundle.intake_retention_ref,
                    retention_days=bundle.retention_days,
                ),
                storage=setup.prepared.storage,
                scratch=setup.prepared.scratch,
                authority=setup.authority,
            )
            install_conversation_http(
                app,
                settings=settings,
                require_actor=require_actor,
                intake_runtime=intake_runtime,
            )

            origin_header = {"Origin": origin}
            cookies = {settings.session_cookie_name: token}
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url=origin,
                cookies=cookies,
                headers=origin_header,
            ) as client:
                c2 = await _http_start(
                    client,
                    setup.prepared.recording_id,
                    {"stage": "C2"},
                    key="openai-c5-http-c2",
                )
                assert c2["state"] == "queued"
                assert await worker.run_once()
                transcript_id = await _checkpoints(setup, "C2")

                c4 = await _http_start(
                    client,
                    setup.prepared.recording_id,
                    {"stage": "C4", "transcript_checkpoint_id": str(transcript_id)},
                    key="openai-c5-http-c4",
                )
                assert c4["state"] == "queued"
                assert await worker.run_once()
                facts_id = await _checkpoints(setup, "C4")
                assert provider_child.routes == ["elevenlabs", "gemini"]

                c5_selection = {
                    "stage": "C5",
                    "transcript_checkpoint_id": str(transcript_id),
                    "fact_checkpoint_ids": [str(facts_id)],
                }
                c5_quote_response = await client.post(
                    f"/v1/conversation/recordings/{setup.prepared.recording_id}/analysis/quote",
                    json=c5_selection,
                    headers={**origin_header, "Idempotency-Key": "openai-c5-http-drift-quote"},
                )
                assert c5_quote_response.status_code == 201, c5_quote_response.text
                c5_quote = c5_quote_response.json()
                assert c5_quote["accepted"] is False
                assert c5_quote["provider"] == "openai"
                assert c5_quote["model"] == "gpt-6-luna"
                assert c5_quote["input_sha256"] != setup.prepared.state.source_sha256

                async with setup.sessions() as database:
                    task_count = await database.scalar(
                        select(func.count()).select_from(ConversationInferenceTask)
                    )
                    job_count = await database.scalar(
                        select(func.count()).select_from(Job).where(Job.kind == INFERENCE_JOB)
                    )
                    acceptance_count = await database.scalar(
                        select(func.count()).select_from(ConversationQuoteAcceptance)
                    )
                    minutes = await database.get(
                        ConversationMinuteAccount,
                        (setup.actor.tenant_id, setup.actor.person_id),
                    )
                    budget = await database.get(
                        ConversationBudgetAccount, setup.bundle.budget_scope_id
                    )
                    assert minutes is not None and budget is not None
                    minutes_before = dict(minutes.snapshot)
                    budget_before = dict(budget.snapshot)
                    minute_revision_before = minutes.revision
                    budget_revision_before = budget.revision

                await _insert_settings(setup, 2, language="mr-Deva+en")
                rejected = await client.post(
                    f"/v1/conversation/recordings/{setup.prepared.recording_id}/analysis",
                    json={
                        "quote_id": c5_quote["id"],
                        "selection": c5_selection,
                        "quote_fingerprint": c5_quote["quote_fingerprint"],
                        "privacy_revision": c5_quote["privacy_revision"],
                        "accepted": True,
                    },
                    headers={
                        **origin_header,
                        "Idempotency-Key": "openai-c5-http-drift-start",
                    },
                )
                assert rejected.status_code == 403, rejected.text
                async with setup.sessions() as database:
                    assert (
                        await database.scalar(
                            select(func.count()).select_from(ConversationInferenceTask)
                        )
                        == task_count
                    )
                    assert (
                        await database.scalar(
                            select(func.count()).select_from(Job).where(Job.kind == INFERENCE_JOB)
                        )
                        == job_count
                    )
                    assert (
                        await database.scalar(
                            select(func.count()).select_from(ConversationQuoteAcceptance)
                        )
                        == acceptance_count
                    )
                    assert (
                        await database.scalar(
                            select(func.count())
                            .select_from(ConversationQuoteAcceptance)
                            .where(ConversationQuoteAcceptance.quote_id == UUID(c5_quote["id"]))
                        )
                        == 0
                    )
                    minutes = await database.get(
                        ConversationMinuteAccount,
                        (setup.actor.tenant_id, setup.actor.person_id),
                    )
                    budget = await database.get(
                        ConversationBudgetAccount, setup.bundle.budget_scope_id
                    )
                    assert minutes is not None and budget is not None
                    assert minutes.snapshot == minutes_before
                    assert budget.snapshot == budget_before
                    assert minutes.revision == minute_revision_before
                    assert budget.revision == budget_revision_before
                assert provider_child.routes == ["elevenlabs", "gemini"]

                await _insert_settings(setup, 3, language="en")
                changed_source = bytearray(setup.prepared.data)
                changed_source[-1] ^= 1
                changed_sha256 = hashlib.sha256(changed_source).hexdigest()
                changed_permission_id = uuid4()
                now = datetime.now(UTC)
                async with setup.sessions() as database, database.begin():
                    database.add(
                        ConversationPermission(
                            id=changed_permission_id,
                            tenant_id=setup.actor.tenant_id,
                            person_id=setup.actor.person_id,
                            source_sha256=changed_sha256,
                            provider="local",
                            permission_reference="synthetic-fixture:different-source-consent",
                            retention_reference="synthetic-fixture:delete-after-test",
                            created_at=now,
                            expires_at=now + timedelta(hours=2),
                            retention_until=now + timedelta(hours=3),
                        )
                    )
                async with setup.sessions() as database, database.begin():
                    application = ConversationApplication(database, clock=lambda: now)
                    recording = await application.register(
                        setup.actor,
                        setup.prepared.state.recording_intent.model_copy(
                            update={
                                "source_sha256": changed_sha256,
                                "source_bytes": len(changed_source),
                                "permission_reference": changed_permission_id,
                            }
                        ),
                        key="openai-c5-http-wrong-source-register",
                    )
                    changed_recording_id = UUID(recording["id"])
                    await application.store_source(
                        setup.actor,
                        changed_recording_id,
                        chunks=(bytes(changed_source),),
                        storage=setup.prepared.storage,
                    )
                wrong_source = await client.post(
                    f"/v1/conversation/recordings/{changed_recording_id}/analysis/quote",
                    json=c5_selection,
                    headers={**origin_header, "Idempotency-Key": "openai-c5-http-wrong-source"},
                )
                assert wrong_source.status_code == 403, wrong_source.text
                async with setup.sessions() as database:
                    assert (
                        await database.scalar(
                            select(func.count())
                            .select_from(ConversationQuote)
                            .where(ConversationQuote.recording_id == changed_recording_id)
                        )
                        == 0
                    )

                other_state = await seed(setup.engine)
                other_token = secrets.token_urlsafe(32)
                async with setup.sessions() as database, database.begin():
                    await database.execute(
                        update(IdentitySession)
                        .where(IdentitySession.id == other_state.session_id)
                        .values(
                            token_hash=hmac.new(
                                pepper.encode(), other_token.encode(), hashlib.sha256
                            ).digest()
                        )
                    )
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url=origin,
                    cookies={settings.session_cookie_name: other_token},
                    headers=origin_header,
                ) as other_client:
                    wrong_owner = await other_client.post(
                        f"/v1/conversation/recordings/{setup.prepared.recording_id}/analysis/quote",
                        json=c5_selection,
                        headers={
                            **origin_header,
                            "Idempotency-Key": "openai-c5-http-wrong-owner",
                        },
                    )
                assert wrong_owner.status_code == 403, wrong_owner.text
                assert provider_child.routes == ["elevenlabs", "gemini"]

                successful_c5 = await _http_start(
                    client,
                    setup.prepared.recording_id,
                    c5_selection,
                    key="openai-c5-http-success",
                )
                assert successful_c5["state"] == "queued"
                assert await worker.run_once()
                if reported_model != "gpt-6-luna":
                    async with setup.sessions() as database:
                        task = await database.scalar(
                            select(ConversationInferenceTask).where(
                                ConversationInferenceTask.recording_id
                                == setup.prepared.recording_id,
                                ConversationInferenceTask.stage == "C5",
                            )
                        )
                        assert task is not None and task.state == "uncertain"
                        assert task.checkpoint_id is None
                        job = await database.get(Job, task.job_id)
                        assert job is not None and job.status == "dead_letter"
                        assert job.last_error == "conversation_openai_response_model_mismatch"
                        assert job.provider_receipt is not None
                        receipt = job.provider_receipt
                        assert receipt["model"] == "gpt-6-luna"
                        assert receipt["reported_model"] == reported_model
                        assert receipt["model_verified"] is False
                        assert receipt["validation_state"] == "provider_returned"
                        raw = b"".join(
                            setup.prepared.storage.iter_bytes(
                                ObjectKey(
                                    task.tenant_id,
                                    task.recording_id,
                                    task.run_id,
                                    ObjectKind.PROVIDER_RESPONSE,
                                ),
                                expected_sha256=receipt["response_sha256"],
                            )
                        )
                        assert json.loads(raw)["model"] == reported_model
                        assert (
                            await database.scalar(
                                select(func.count())
                                .select_from(ConversationReportDraft)
                                .where(
                                    ConversationReportDraft.run_id == task.run_id,
                                )
                            )
                            == 0
                        )
                        budget = await database.get(
                            ConversationBudgetAccount, setup.bundle.budget_scope_id
                        )
                        assert budget is not None
                        reservations = BudgetAccount.from_dict(budget.snapshot).reservations
                        openai_reservations = [
                            item for item in reservations if item.quote.provider_id == "openai"
                        ]
                        assert len(openai_reservations) == 1
                        assert openai_reservations[0].state == "uncertain"
                    assert await _checkpoints(setup, "C2") == transcript_id
                    assert await _checkpoints(setup, "C4") == facts_id
                    assert not await worker.run_once()
                    assert provider_child.routes == ["elevenlabs", "gemini", "openai"]
                    return
                c5_checkpoint = await _checkpoints(setup, "C5")
                assert provider_child.routes == ["elevenlabs", "gemini", "openai"]

                async with setup.sessions() as database:
                    tasks = (
                        await database.scalars(
                            select(ConversationInferenceTask)
                            .where(
                                ConversationInferenceTask.recording_id
                                == setup.prepared.recording_id
                            )
                            .order_by(ConversationInferenceTask.created_at)
                        )
                    ).all()
                    assert [task.stage for task in tasks] == ["C2", "C4", "C5"]
                    quote_rows = (
                        await database.scalars(
                            select(ConversationQuote).where(
                                ConversationQuote.id.in_([task.quote_id for task in tasks])
                            )
                        )
                    ).all()
                    quotes_by_id = {str(row.id): Quote.from_dict(row.quote) for row in quote_rows}
                    assert [quotes_by_id[str(task.quote_id)].provider_id for task in tasks] == [
                        "elevenlabs",
                        "gemini",
                        "openai",
                    ]
                    c5_task = tasks[-1]
                    assert c5_task.checkpoint_id == c5_checkpoint
                    job = await database.get(Job, c5_task.job_id)
                    assert job is not None and job.status == "succeeded"
                    assert job.provider_receipt is not None
                    assert job.provider_receipt["provider"] == "openai"
                    assert job.provider_receipt["usage"] == {
                        "input_tokens": 128,
                        "output_tokens": 96,
                        "total_tokens": 224,
                        "cached_tokens": 0,
                        "cache_write_tokens": 0,
                        "reasoning_tokens": 32,
                    }
                    draft = await database.scalar(
                        select(ConversationReportDraft).where(
                            ConversationReportDraft.run_id == c5_task.run_id
                        )
                    )
                    assert draft is not None
                    assert draft.payload is not None
                    assert draft.payload["review_status"] == "draft_not_dipak_adjudicated"
                    assert draft.source_sha256 == setup.prepared.state.source_sha256
                    assert c5_task.intent["request"]["provider"] == "openai"
                    assert c5_task.intent["request"]["model"] == "gpt-6-luna"
                    assert c5_task.intent["request"]["coaching_prompt_revision"] == "coaching-v5"

                    checkpoint = await database.get(ConversationCheckpoint, c5_checkpoint)
                    assert checkpoint is not None and checkpoint.stage == "C5"
                    quote_ids = [task.quote_id for task in tasks]
                    accepted_ids = set(
                        (
                            await database.scalars(
                                select(ConversationQuoteAcceptance.quote_id).where(
                                    ConversationQuoteAcceptance.quote_id.in_(quote_ids)
                                )
                            )
                        ).all()
                    )
                    assert accepted_ids == set(quote_ids)
                    minutes = await database.get(
                        ConversationMinuteAccount,
                        (setup.actor.tenant_id, setup.actor.person_id),
                    )
                    budget = await database.get(
                        ConversationBudgetAccount, setup.bundle.budget_scope_id
                    )
                    assert minutes is not None and budget is not None
                    minute_reservations = MinuteAccount.from_dict(minutes.snapshot).reservations
                    provider_minutes = [
                        item for item in minute_reservations if item.quote.provider_id != "local"
                    ]
                    assert [item.quote.provider_id for item in provider_minutes] == [
                        "elevenlabs",
                        "gemini",
                        "openai",
                    ]
                    assert all(item.quote.entitlement_seconds == 0 for item in provider_minutes)
                    assert all(item.state == "uncertain" for item in provider_minutes)
                    assert all(item.uncertainty_ref for item in provider_minutes)
                    budget_reservations = BudgetAccount.from_dict(budget.snapshot).reservations
                    assert [item.quote.provider_id for item in budget_reservations] == [
                        "elevenlabs",
                        "gemini",
                        "openai",
                    ]
                    assert all(item.state == "uncertain" for item in budget_reservations)
        finally:
            await setup.engine.dispose()

    run(exercise())
