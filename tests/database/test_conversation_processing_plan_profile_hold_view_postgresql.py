"""Scheduler publishes bounded profile-hold progress; owner reads only project it."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionSettlement,
    ConversationAcquisitionUsage,
)
from ac_platform.conversation_intelligence.acquisition_sessions import AcquisitionSessions
from ac_platform.conversation_intelligence.application import ConversationApplication
from ac_platform.conversation_intelligence.broker_router import FixedProviderRouter, ProviderRoute
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.inference_worker import ConversationInferenceWorker
from ac_platform.conversation_intelligence.models import (
    ConversationBudgetAccount,
    ConversationInferenceTask,
    ConversationProcessingPlan,
    ConversationQuote,
)
from ac_platform.conversation_intelligence.processing_actor import ProcessingActor
from ac_platform.conversation_intelligence.processing_plan import (
    ConversationProcessingPlans,
    ProcessingPlanScheduler,
)
from ac_platform.identity.sales_xray_profile import (
    get_sales_xray_profile,
    update_sales_xray_profile,
)
from ac_platform.outbox.models import Job
from ac_platform.outbox.repository import JobRepository
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_reporting_pipeline_postgresql import ReportingBroker
from tests.database.test_conversation_submission_http_postgresql import (
    ORIGIN,
    PREFIX,
    _headers,
    _reconcile,
    _setup,
    _sign_in,
)
from tests.database.test_conversation_worker_postgresql import (
    OfflineConversationWorker,
    _wav_one_second_48k,
)


@pytest.fixture
def isolated_postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


def test_plan_owner_reads_project_and_clear_a_worker_profile_hold(
    isolated_postgres_harness: Any, tmp_path: Any
) -> None:
    async def exercise() -> None:
        setup = await _setup(isolated_postgres_harness, tmp_path, gemini=True)
        try:
            data = _wav_one_second_48k()
            submission_id = uuid4()
            path = f"{PREFIX}/submissions/{submission_id}"
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                _sign_in(setup, client)
                uploaded = await client.put(
                    path + "/source", content=data, headers=await _headers(client, data)
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

                quote_response = await client.post(
                    path + "/plan/quote",
                    headers={"Origin": ORIGIN, "Idempotency-Key": "profile-hold-plan-quote"},
                )
                assert quote_response.status_code == 201, quote_response.text
                quote = quote_response.json()
                accepted_response = await client.post(
                    path + "/plan",
                    json={
                        "plan_id": quote["id"],
                        "plan_fingerprint": quote["plan_fingerprint"],
                        "privacy_revision": quote["privacy_revision"],
                        "accepted": True,
                    },
                    headers={"Origin": ORIGIN, "Idempotency-Key": "profile-hold-plan-accept"},
                )
                assert accepted_response.status_code == 202, accepted_response.text
                accepted = accepted_response.json()
                assert accepted["state"] == "active"

            async with setup.sessions() as database, database.begin():
                profile = await get_sales_xray_profile(database, person_id=setup.state.person_id)
                assert profile.profile_complete
                incomplete = await update_sales_xray_profile(
                    database,
                    person_id=setup.state.person_id,
                    session_id=setup.state.session_id,
                    tenant_id=setup.state.tenant_id,
                    full_name=profile.name or "Synthetic Learner",
                    phone_number_e164=None,
                    expected_revision=profile.revision,
                )
                assert not incomplete.profile_complete

            broker = ReportingBroker(data)
            router = FixedProviderRouter(
                {
                    provider: ProviderRoute(provider, f"ref:credential:{provider}", broker)
                    for provider in ("elevenlabs", "gemini")
                },
                authority=setup.authority,
            )
            worker = ConversationInferenceWorker(
                setup.sessions,
                setup.runtime.storage,
                router,
                authority=setup.authority,
            )
            assert await worker.run_once()
            assert broker.calls == 0

            plan_id = UUID(quote["id"])

            async def queue_and_ledger_snapshot() -> tuple[Any, ...]:
                async with setup.sessions() as database:
                    task_rows = tuple(
                        sorted(
                            await database.scalars(
                                select(ConversationInferenceTask.run_id).where(
                                    ConversationInferenceTask.recording_id
                                    == UUID(accepted["recording_id"])
                                )
                            )
                        )
                    )
                    job_rows = tuple(
                        sorted(
                            await database.scalars(
                                select(Job.id).where(Job.tenant_id == setup.state.tenant_id)
                            )
                        )
                    )
                    c2_task = await database.scalar(
                        select(ConversationInferenceTask).where(
                            ConversationInferenceTask.recording_id
                            == UUID(accepted["recording_id"]),
                            ConversationInferenceTask.stage == "C2",
                        )
                    )
                    assert c2_task is not None
                    task_quote = await database.get(ConversationQuote, c2_task.quote_id)
                    assert task_quote is not None
                    budget = await database.get(
                        ConversationBudgetAccount, task_quote.budget_scope_id
                    )
                    assert budget is not None
                    reservations = budget.snapshot.get("reservations")
                    assert isinstance(reservations, list)
                    return (
                        task_rows,
                        job_rows,
                        deepcopy(budget.snapshot),
                        budget.revision,
                        len(reservations),
                    )

            accepted_queue_and_reservations = await queue_and_ledger_snapshot()

            async def tick_plan_scheduler() -> None:
                async with setup.sessions() as database, database.begin():
                    scheduled_plan = await database.get(ConversationProcessingPlan, plan_id)
                    assert scheduled_plan is not None
                    scheduled_plan.next_check_at = datetime.now(UTC) - timedelta(seconds=1)
                scheduler = ProcessingPlanScheduler(
                    setup.sessions, setup.authority, setup.runtime.storage
                )
                assert await scheduler.step()

            await tick_plan_scheduler()
            assert await queue_and_ledger_snapshot() == accepted_queue_and_reservations

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                _sign_in(setup, client)
                latest = await client.get(path + "/plan")
                assert latest.status_code == 200, latest.text
                assert latest.json()["state"] == "held"
                assert latest.json()["failure_code"] == "account_profile_required"
                assert "hold_reason" not in latest.json()
                assert "sales_xray_profile_incomplete" not in latest.text

            async with setup.sessions() as database, database.begin():
                sessions = AcquisitionSessions(
                    database,
                    tenant_id=setup.state.tenant_id,
                    policy_revision="guest-processing-v1",
                    clock=lambda: setup.clock[0],
                )
                processing_actor = await GuestOwnership(sessions).resolve_processing_actor(
                    submission_id, actor=setup.state.actor
                )
                assert isinstance(processing_actor, ProcessingActor)
                direct = await ConversationProcessingPlans(
                    ConversationApplication(database, clock=lambda: setup.clock[0]),
                    setup.authority,
                    setup.runtime.storage,
                ).get(processing_actor, UUID(accepted["recording_id"]))
                assert direct["state"] == "held"
                assert direct["failure_code"] == "account_profile_required"

                plan_row = await database.get(ConversationProcessingPlan, UUID(quote["id"]))
                task = await database.scalar(
                    select(ConversationInferenceTask).where(
                        ConversationInferenceTask.recording_id == UUID(accepted["recording_id"]),
                        ConversationInferenceTask.stage == "C2",
                    )
                )
                assert plan_row is not None and plan_row.state == "active"
                assert task is not None and task.state == "queued"
                job = await database.get(Job, task.job_id)
                assert job is not None and job.status == "held"
                assert job.dispatch_started_at is None and job.provider_receipt is None
                usage = await database.scalar(
                    select(ConversationAcquisitionUsage).where(
                        ConversationAcquisitionUsage.submission_id == submission_id
                    )
                )
                assert usage is not None
                assert await database.get(ConversationAcquisitionSettlement, usage.id) is None
                held_job_id = job.id

            async with setup.sessions() as database, database.begin():
                profile = await get_sales_xray_profile(database, person_id=setup.state.person_id)
                await update_sales_xray_profile(
                    database,
                    person_id=setup.state.person_id,
                    session_id=setup.state.session_id,
                    tenant_id=setup.state.tenant_id,
                    full_name=profile.name or "Synthetic Learner",
                    phone_number_e164="+12025550123",
                    expected_revision=profile.revision,
                )

            operations_actor = replace(
                setup.state.actor,
                permissions=frozenset({"recovery_reconcile", "global_recovery_reconcile"}),
            )
            async with setup.sessions() as database, database.begin():
                await JobRepository(database).reconcile_held(
                    [held_job_id],
                    actor=operations_actor,
                    reason="Profile completion confirmed and pre-dispatch hold reviewed.",
                    audit=AuditRepository(database),
                    operations_tenant_id=setup.state.tenant_id,
                    now=setup.clock[0],
                )

            await tick_plan_scheduler()
            assert await queue_and_ledger_snapshot() == accepted_queue_and_reservations

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                _sign_in(setup, client)
                resumed = await client.get(path + "/plan")
                assert resumed.status_code == 200, resumed.text
                assert resumed.json()["state"] == "active"
                assert resumed.json()["failure_code"] is None

            async with setup.sessions() as database, database.begin():
                sessions = AcquisitionSessions(
                    database,
                    tenant_id=setup.state.tenant_id,
                    policy_revision="guest-processing-v1",
                    clock=lambda: setup.clock[0],
                )
                processing_actor = await GuestOwnership(sessions).resolve_processing_actor(
                    submission_id, actor=setup.state.actor
                )
                assert isinstance(processing_actor, ProcessingActor)
                direct = await ConversationProcessingPlans(
                    ConversationApplication(database, clock=lambda: setup.clock[0]),
                    setup.authority,
                    setup.runtime.storage,
                ).get(processing_actor, UUID(accepted["recording_id"]))
                assert direct["state"] == "active"
                assert direct["failure_code"] is None

            async with setup.sessions() as database:
                plan_row = await database.get(ConversationProcessingPlan, UUID(quote["id"]))
                task = await database.scalar(
                    select(ConversationInferenceTask).where(
                        ConversationInferenceTask.recording_id == UUID(accepted["recording_id"]),
                        ConversationInferenceTask.stage == "C2",
                    )
                )
                assert plan_row is not None and plan_row.state == "active"
                assert task is not None and task.state == "queued"
                job = await database.get(Job, held_job_id)
                assert job is not None and job.status == "queued"
                assert job.dispatch_started_at is None and job.provider_receipt is None
                assert broker.calls == 0
        finally:
            await setup.engine.dispose()

    run(exercise())
