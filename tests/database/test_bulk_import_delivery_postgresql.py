"""Confirmed member upload composes with real plans, workers and delivered-report charging."""

import hashlib
from uuid import UUID

import pytest
from sqlalchemy import func, select

from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionSettlement,
    ConversationAcquisitionUsage,
)
from ac_platform.conversation_intelligence.broker_router import FixedProviderRouter, ProviderRoute
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.inference_worker import ConversationInferenceWorker
from ac_platform.conversation_intelligence.processing_plan import ProcessingPlanScheduler
from ac_platform.conversation_intelligence.report_minutes import ReportMinutes
from tests.database.test_bulk_import_postgresql import (
    batch_headers,
    client_for,
    confirm,
    setup_import,
    source,
    upload,
)
from tests.database.test_bulk_import_postgresql import postgres_harness as _bulk_postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_processing_plan_postgresql import _make_due
from tests.database.test_conversation_reporting_pipeline_postgresql import ReportingBroker
from tests.database.test_conversation_submission_http_postgresql import (
    ORIGIN,
    PREFIX,
    _wav_one_second_48k,
)
from tests.database.test_conversation_worker_postgresql import (
    OfflineConversationWorker,
    _reconcile,
)


@pytest.fixture
def postgres_harness(monkeypatch):
    yield from _bulk_postgres_harness.__wrapped__(monkeypatch)


def test_member_import_delivers_via_normal_workers_and_commits_once_across_repeats(
    postgres_harness,
    tmp_path,
):
    async def exercise():
        setup = await setup_import(postgres_harness, tmp_path, gemini=True)
        data = _wav_one_second_48k()
        broker = ReportingBroker(data)
        try:
            async with await client_for(setup) as client:
                response, _ = await confirm(client, setup, [source("Rep/call", data)])
                assert response.status_code == 201, response.text
                batch = response.json()
                accepted_source = await upload(client, batch, 0, data)
                assert accepted_source.status_code == 202, accepted_source.text
                identifier = UUID(accepted_source.json()["submission_id"])
                path = f"{PREFIX}/submissions/{identifier}"
                async with setup.sessions() as db:
                    usage = await db.scalar(
                        select(ConversationAcquisitionUsage).where(
                            ConversationAcquisitionUsage.submission_id == identifier
                        )
                    )
                    assert usage.person_id == setup.member.person_id
                    usage_id = usage.id
                    # The initial hold is the ordinary usage reservation;
                    # the superseding report journal starts on retry/delivery.
                    assert usage.reserved_seconds == 1
                    assert await ReportMinutes(db).latest(usage_id) is None
                    assert await db.get(ConversationAcquisitionSettlement, usage_id) is None
                    link = await db.get(
                        ConversationGuestSubmission, (setup.organisation.tenant_id, identifier)
                    )
                    assert link.person_id == setup.org_principal
                await _reconcile(setup.sessions, setup.state)
                local = OfflineConversationWorker(
                    setup.sessions,
                    storage=setup.runtime.storage,
                    scratch=setup.runtime.scratch,
                    environment="test",
                )
                assert await local.run_once()
                headers = {"Origin": ORIGIN, **batch_headers(batch, 0)}
                quote = await client.post(
                    path + "/plan/quote",
                    headers={**headers, "Idempotency-Key": "fictional-member-plan-quote"},
                )
                assert quote.status_code == 201, quote.text
                plan = quote.json()
                approval = {
                    "plan_id": plan["id"],
                    "plan_fingerprint": plan["plan_fingerprint"],
                    "privacy_revision": plan["privacy_revision"],
                    "accepted": True,
                }
                accepted = await client.post(
                    path + "/plan",
                    json=approval,
                    headers={**headers, "Idempotency-Key": "fictional-member-plan-accept"},
                )
                assert accepted.status_code == 202, accepted.text
                router = FixedProviderRouter(
                    {
                        provider: ProviderRoute(provider, f"ref:credential:{provider}", broker)
                        for provider in ("elevenlabs", "gemini")
                    },
                    authority=setup.authority,
                )
                # Fresh workers/scheduler: no browser reads advance or settle the plan.
                worker = ConversationInferenceWorker(
                    setup.sessions, setup.runtime.storage, router, authority=setup.authority
                )
                scheduler = ProcessingPlanScheduler(setup.sessions, setup.authority)
                for _ in range(8):
                    await worker.run_once()
                    await _make_due(setup, UUID(plan["id"]))
                    await scheduler.step()
                assert broker.routes == ["elevenlabs", "gemini", "gemini"]
                async with setup.sessions() as db:
                    settlement = await db.get(ConversationAcquisitionSettlement, usage_id)
                    assert settlement.kind == "completed" and settlement.charged_seconds == 1
                    assert (await ReportMinutes(db).latest(usage_id)).kind == "delivered"
                    account = await setup.factory(
                        db, setup.organisation.tenant_id
                    ).ledger.project_organisation(
                        tenant_id=setup.organisation.tenant_id, now=setup.clock[0]
                    )
                    assert account.committed_seconds == 1
                delivered = await client.get(path + "/report")
                assert delivered.status_code == 200, delivered.text
                assert delivered.json()["source_sha256"] == hashlib.sha256(data).hexdigest()
                progress = await client.get(PREFIX + "/imports/" + batch["batch_id"])
                assert progress.json()["files"][0]["state"] == "done"
                assert progress.json()["files"][0]["minute_state"] == "delivered"
                replay = await client.post(
                    path + "/plan",
                    json=approval,
                    headers={**headers, "Idempotency-Key": "fictional-member-plan-accept"},
                )
                assert replay.status_code == 202, replay.text
                duplicate, _ = await confirm(
                    client, setup, [source("Rep/repeated", data)], key="fictional-new-batch"
                )
                assert duplicate.status_code == 201, duplicate.text
                reused = await upload(client, duplicate.json(), 0, data)
                assert reused.status_code == 202 and reused.json()["state"] == "already_imported"
                read = await client.get(PREFIX + "/imports/" + duplicate.json()["batch_id"])
                assert read.json()["files"][0]["state"] == "already_imported"
                assert read.json()["files"][0]["person_id"] == str(setup.member.person_id)
                assert read.json()["files"][0]["submission_id"] == str(identifier)
                assert setup.native.calls == 1
                assert broker.calls == 3
                async with setup.sessions() as db:
                    assert (
                        await db.scalar(
                            select(func.count()).select_from(ConversationAcquisitionUsage)
                        )
                        == 1
                    )
                    assert (
                        await db.scalar(
                            select(func.count()).select_from(ConversationAcquisitionSettlement)
                        )
                        == 1
                    )
        finally:
            await setup.engine.dispose()

    run(exercise())
