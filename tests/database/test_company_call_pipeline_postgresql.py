"""Signed fake callbacks through storage, standing consent, offline analysis and badge.

Uses the existing canonical upload/plan test workers, not an alternate report builder.
All media and provider results are fictional; no external calls or credentials.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select, update

from ac_platform.audit.models import AuditEvent
from ac_platform.call_ai import auto_consent
from ac_platform.conversation_intelligence.acquisition_processing import upload_policy
from ac_platform.conversation_intelligence.acquisition_source import NativeUploadPreflight
from ac_platform.conversation_intelligence.broker_router import FixedProviderRouter, ProviderRoute
from ac_platform.conversation_intelligence.inference_worker import ConversationInferenceWorker
from ac_platform.conversation_intelligence.models import ConversationProcessingPlan
from ac_platform.conversation_intelligence.processing_plan import ProcessingPlanScheduler
from ac_platform.http.routes import RouteContext
from ac_platform.lead_desk.models import Lead, LeadDevice
from ac_platform.lead_desk.store import token_digest
from ac_platform.lead_desk.telephony import ledger, providers
from ac_platform.lead_desk.telephony.http import install_telephony_http, sign
from ac_platform.lead_desk.telephony.notifications import dispatch
from ac_platform.lead_desk.telephony.pipeline import (
    READY,
    STARTED,
    STORED,
    SUBMITTED,
    Pipeline,
    attach,
    post_fake_callback,
)
from ac_platform.product_updates.models import Notification
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_processing_plan_postgresql import _make_due
from tests.database.test_conversation_submission_http_postgresql import (
    ORIGIN,
    AcquisitionC5HistoryBroker,
    _setup,
)
from tests.database.test_conversation_worker_postgresql import (
    OfflineConversationWorker,
    _reconcile,
    _wav_one_second_48k,
)
from tests.database.test_lead_desk_postgresql import _organisation

BASE = "/v1/lead-desk"
WRITE = {"Origin": ORIGIN}
SECRET = "fictional-callback-key"  # noqa: S105


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


class OfflineFake(providers.FakeProvider):
    def __init__(self) -> None:
        self.now = 100.0
        self.downloads = 0
        super().__init__(clock=lambda: self.now)

    async def fetch_recording(self, url: str) -> providers.Recording:
        self.downloads += 1
        return providers.Recording(_wav_one_second_48k(), "audio/wav")


async def prepare(
    setup: Any, fake: OfflineFake, monkeypatch: pytest.MonkeyPatch
) -> tuple[Any, UUID, UUID]:
    await _organisation(setup)
    tenant = setup.state.tenant_id
    monkeypatch.setenv("AC_TELEPHONY_TENANTS", str(tenant))
    monkeypatch.setenv("AC_TELEPHONY_WEBHOOK_SECRET", SECRET)
    monkeypatch.setattr(providers, "provider_from_env", lambda **kwargs: fake)
    settings = setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()})
    install_telephony_http(setup.app, RouteContext(settings, setup.require_actor, setup.sessions))
    pipeline = Pipeline(
        sessions=setup.sessions,
        runtime=setup.runtime,
        preflight=NativeUploadPreflight(setup.native),
        factory=setup.factory,
        environment="test",
        allow_fictional_analysis=True,
    )
    attach(setup.app, pipeline, lambda: fake)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
    ) as client:
        client.cookies.set(setup.settings.session_cookie_name, setup.token)
        configured = await client.put(
            f"{BASE}/calling", json={"on": True, "number": "020 0000 0000"}, headers=WRITE
        )
        assert configured.status_code == 200, configured.text
        mobile = await client.put(
            f"{BASE}/calling/me", json={"mobile": "98000 00001"}, headers=WRITE
        )
        assert mobile.status_code == 200, mobile.text
        added = await client.post(
            f"{BASE}/leads",
            json={"command_id": str(uuid4()), "name": "Fictional Asha", "phone": "98000 00002"},
            headers=WRITE,
        )
        assert added.status_code == 201, added.text
        lead = UUID(added.json()["lead"]["lead_id"])
        async with setup.sessions() as db, db.begin():
            await db.execute(update(Lead).where(Lead.id == lead).values(source="webhook"))
        placed = await client.post(
            f"{BASE}/leads/{lead}/calls/company", json={"commandId": str(uuid4())}, headers=WRITE
        )
        assert placed.status_code == 200, placed.text
        call = UUID(placed.json()["id"])
    fake.now += 25
    return pipeline, tenant, call


async def callback(
    setup: Any, tenant: UUID, call: UUID, *, mac: str | None = None
) -> httpx.Response:
    path = f"{BASE}/telephony/fake/status/{tenant}/{call}/{mac or sign(SECRET, tenant, call)}"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
    ) as client:
        return await client.post(
            path, json={"Status": "failed", "RecordingUrl": "https://evil.test/x"}
        )


async def consent(setup: Any, *, terms: str | None = None) -> None:
    async with setup.sessions() as db, db.begin():
        await auto_consent.record(
            db,
            tenant_id=setup.state.tenant_id,
            person_id=setup.state.person_id,
            session_id=setup.state.session_id,
            decision="granted",
            policy_sha256=auto_consent.notice()["policy_sha256"],
            upload_policy_sha256=terms or upload_policy(setup.runtime.policy)["policy_sha256"],
            now=datetime.now(UTC),
        )


@pytest.mark.parametrize("choice", ["absent", "old_terms", "current"])
def test_fake_callback_storage_consent_and_tenant_isolation(
    postgres_harness: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    choice: str,
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            fake = OfflineFake()
            pipeline, tenant, call_id = await prepare(setup, fake, monkeypatch)
            if choice != "absent":
                await consent(setup, terms="a" * 64 if choice == "old_terms" else None)
            assert (await callback(setup, tenant, call_id, mac="0" * 64)).status_code == 404
            assert fake.downloads == 0
            assert (await callback(setup, uuid4(), call_id)).status_code == 200
            assert fake.downloads == 0  # A valid MAC for another tenant still finds no call.
            response = await callback(setup, tenant, call_id)
            assert response.status_code == 200, response.text
            assert (await callback(setup, tenant, call_id)).status_code == 200
            assert await post_fake_callback(setup.app, ORIGIN, tenant, call_id)
            assert fake.downloads == 1
            async with setup.sessions() as db:
                call = await ledger.read(db, tenant, call_id)
                assert call is not None and call.hung_up_by == "lead" and call.recording
                events = await pipeline.events(db, call)
                assert STORED in events
                assert (SUBMITTED in events) == (choice == "current")
                count = await db.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(
                        AuditEvent.tenant_id == tenant,
                        AuditEvent.resource_id == str(call_id),
                        AuditEvent.action == STORED,
                    )
                )
                assert count == 1
                assert await ledger.read(db, uuid4(), call_id) is None
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                saved = await client.get(f"{BASE}/calls/company/{call_id}/recording")
                assert saved.status_code == 200 and saved.content == _wav_one_second_48k()
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_fake_call_runs_canonical_offline_pipeline_to_ready_badge_and_push(
    postgres_harness: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path, gemini=True, funded=True)
        try:
            fake = OfflineFake()
            pipeline, tenant, call_id = await prepare(setup, fake, monkeypatch)
            await consent(setup)
            assert (await callback(setup, tenant, call_id)).status_code == 200
            await _reconcile(setup.sessions, setup.state)
            local = OfflineConversationWorker(
                setup.sessions,
                storage=setup.runtime.storage,
                scratch=setup.runtime.scratch,
                environment="test",
            )
            assert await local.run_once()
            await pipeline.advance(fake, tenant, call_id)
            async with setup.sessions() as db:
                call = await ledger.read(db, tenant, call_id)
                events = await pipeline.events(db, call)
                assert STARTED in events
                plan_id = UUID(events[STARTED]["plan_id"])
            broker = AcquisitionC5HistoryBroker(_wav_one_second_48k())
            router = FixedProviderRouter(
                {
                    provider: ProviderRoute(provider, f"ref:credential:{provider}", broker)
                    for provider in ("elevenlabs", "gemini", "openai")
                },
                authority=setup.authority,
            )
            worker = ConversationInferenceWorker(
                setup.sessions, setup.runtime.storage, router, authority=setup.authority
            )
            scheduler = ProcessingPlanScheduler(
                setup.sessions, setup.authority, setup.runtime.storage
            )
            for _ in range(15):
                await worker.run_once()
                await _make_due(setup, plan_id)
                await scheduler.step()
                async with setup.sessions() as db:
                    plan = await db.get(ConversationProcessingPlan, plan_id)
                    if plan.state == "completed":
                        break
            assert plan.state == "completed", plan.progress
            await pipeline.advance(fake, tenant, call_id)
            await pipeline.advance(fake, tenant, call_id)
            async with setup.sessions() as db:
                events = await pipeline.events(db, call)
                assert READY in events
                notifications = (
                    await db.scalars(
                        select(Notification).where(Notification.kind == "report_ready")
                    )
                ).all()
                assert len(notifications) == 1
                assert notifications[0].person_id == setup.state.person_id
                assert notifications[0].read_at is None
                assert "Fictional Asha" in notifications[0].title
            # Two phones, one opt-out (no registration), and transient failure: only
            # successful tokens get a receipt; the failed phone retries next sweep.
            async with setup.sessions() as db, db.begin():
                db.add(
                    LeadDevice(
                        id=uuid4(),
                        tenant_id=tenant,
                        person_id=setup.state.person_id,
                        platform="android",
                        token="fictional-phone",  # noqa: S106 - fictional device
                        token_sha256=token_digest("fictional-phone"),
                        app_version="test",
                        created_at=datetime.now(UTC),
                        last_seen_at=datetime.now(UTC),
                    )
                )

            class Sender:
                def __init__(self) -> None:
                    self.calls = 0

                async def report(self, client: Any, token: str, submission: UUID) -> str:
                    self.calls += 1
                    return "failed" if self.calls == 1 else "sent"

            sender = Sender()
            submission = UUID(events[READY]["submission_id"])
            assert await dispatch(pipeline, call, submission, fcm=sender) == 0
            assert await dispatch(pipeline, call, submission, fcm=sender) == 1
            assert await dispatch(pipeline, call, submission, fcm=sender) == 0
            assert sender.calls == 2
        finally:
            await setup.engine.dispose()

    run(exercise())
