"""AI on calls through the HTTP API on PostgreSQL (owner, 21 Oct 2026).

Only an organisation's owners and admins change levels; every member can read them.
A seller on Data only uploads a call: it stops after its transcript, says why, releases
its minutes and offers no retry. An admin's "Get full report" records the upgrade and
prepares a fresh plan; accepted, it reuses the saved transcript (one transcription in
all), finishes the report and delivers the call's minutes once. Fictional people and
the synthetic local providers only.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select, update

from ac_platform.audit.models import AuditEvent
from ac_platform.call_ai.http import install_call_ai_http
from ac_platform.call_ai.models import CallAiDecision, CallAiSettings
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationReportMinuteEvent,
)
from ac_platform.conversation_intelligence.inference_worker import ConversationInferenceWorker
from ac_platform.conversation_intelligence.models import (
    ConversationInferenceTask,
    ConversationProcessingPlan,
)
from ac_platform.conversation_intelligence.processing_plan import ProcessingPlanScheduler
from ac_platform.http.routes import RouteContext
from ac_platform.outbox.repository import RetryPolicy
from ac_platform.tenancy.models import Membership
from tests.database.test_conversation_account_library_postgresql import _session
from tests.database.test_conversation_failure_observation_postgresql import (
    seed_measured_fixture,
)
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_reporting_pipeline_postgresql import ReportingBroker
from tests.database.test_conversation_submission_http_postgresql import (
    ORIGIN,
    _make_due,
    _setup,
    _upload_for_read_test,
)
from tests.database.test_conversation_worker_postgresql import _reconcile, _wav_one_second_48k
from tests.database.test_lead_desk_postgresql import _organisation
from tests.unit.conversation_intelligence.test_acquisition_source import ValidationFixtureRuntime
from tests.unit.conversation_intelligence.test_alignment import _signal

WRITE = {"Origin": ORIGIN, "Content-Type": "application/json"}
BASE = "/v1/sales-xray/call-ai"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def _install(setup: Any) -> None:
    # As the Lead Desk tests do: this harness's own workspace is not the learner one.
    settings = setup.settings.model_copy(update={"public_learner_tenant_id": uuid4()})
    install_call_ai_http(setup.app, RouteContext(settings, setup.require_actor, setup.sessions))


def test_only_owners_and_admins_change_levels_and_every_save_is_audited(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)  # the signed-in person is an admin here
            _install(setup)
            tenant = setup.state.tenant_id
            seller = await seed(setup.engine, tenant_id=tenant, role="member")
            seller_token = await _session(setup, seller)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:

                def as_(token: str) -> None:
                    client.cookies.clear()
                    client.cookies.set(setup.settings.session_cookie_name, token)

                as_(seller_token)
                seen = await client.get(BASE)
                assert seen.status_code == 200, seen.text
                assert seen.headers["cache-control"] == "private, no-store"
                body = seen.json()
                assert (body["revision"], body["default"], body["people"]) == (None, "full", [])
                assert body["can_edit"] is False
                assert body["you"] == {"level": "full", "source": "organisation"}
                assert [level["id"] for level in body["levels"]] == [
                    "off",
                    "data_only",
                    "auto",
                    "full",
                ]
                refused = await client.put(
                    BASE + "/default",
                    json={"expected_revision": None, "level": "off"},
                    headers=WRITE,
                )
                assert refused.status_code == 403
                refused = await client.put(
                    f"{BASE}/people/{seller.person_id}",
                    json={"expected_revision": None, "level": "full"},
                    headers=WRITE,
                )
                assert refused.status_code == 403

                as_(setup.token)
                # Writes come only from the Sales Xray page itself.
                elsewhere = await client.put(
                    BASE + "/default",
                    json={"expected_revision": None, "level": "data_only"},
                    headers={"Origin": "https://elsewhere.example.test"},
                )
                assert elsewhere.status_code == 403
                saved = await client.put(
                    BASE + "/default",
                    json={"expected_revision": None, "level": "data_only"},
                    headers=WRITE,
                )
                assert saved.status_code == 200, saved.text
                assert (saved.json()["revision"], saved.json()["default"]) == (1, "data_only")
                assert saved.json()["can_edit"] is True
                person = await client.put(
                    f"{BASE}/people/{seller.person_id}",
                    json={"expected_revision": 1, "level": "off"},
                    headers=WRITE,
                )
                assert person.status_code == 200, person.text
                assert person.json()["revision"] == 2
                assert person.json()["people"] == [
                    {
                        "person_id": str(seller.person_id),
                        "name": "Synthetic Worker Owner",
                        "level": "off",
                    }
                ]
                stale = await client.put(
                    BASE + "/default",
                    json={"expected_revision": 1, "level": "full"},
                    headers=WRITE,
                )
                assert stale.status_code == 409
                stranger = await client.put(
                    f"{BASE}/people/{uuid4()}",
                    json={"expected_revision": 2, "level": "off"},
                    headers=WRITE,
                )
                assert stranger.status_code == 404
                bad = await client.put(
                    BASE + "/default",
                    json={"expected_revision": 2, "level": "cheap"},
                    headers=WRITE,
                )
                assert bad.status_code == 422

                as_(seller_token)
                mine = (await client.get(BASE)).json()
                assert mine["you"] == {"level": "off", "source": "person"}

                as_(setup.token)
                cleared = await client.put(
                    f"{BASE}/people/{seller.person_id}",
                    json={"expected_revision": 2, "level": None},
                    headers=WRITE,
                )
                assert cleared.status_code == 200, cleared.text
                assert (cleared.json()["revision"], cleared.json()["people"]) == (3, [])

            async with setup.sessions() as db:
                revisions = (
                    await db.scalars(
                        select(CallAiSettings.revision)
                        .where(CallAiSettings.tenant_id == tenant)
                        .order_by(CallAiSettings.revision)
                    )
                ).all()
                assert list(revisions) == [1, 2, 3]
                events = (
                    await db.scalars(
                        select(AuditEvent)
                        .where(AuditEvent.action.like("sales_xray.call_ai.%"))
                        .order_by(AuditEvent.sequence_no)
                    )
                ).all()
                assert [event.action for event in events] == [
                    "sales_xray.call_ai.default_changed",
                    "sales_xray.call_ai.person_changed",
                    "sales_xray.call_ai.person_changed",
                ]
                assert all(event.actor_person_id == setup.state.person_id for event in events)
                assert events[1].payload["before"]["people"] == {}
                assert events[1].payload["after"]["people"] == {str(seller.person_id): "off"}
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_a_data_only_call_stops_after_its_transcript_and_an_admin_gets_its_full_report(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RetryPolicy, "delay_for_attempt", lambda *a, **k: timedelta(microseconds=1))

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path, gemini=True)
        setup.native.validate_source = ValidationFixtureRuntime().validate_source
        try:
            await _organisation(setup)
            tenant = setup.state.tenant_id
            seller = await seed(setup.engine, tenant_id=tenant, role="member")
            seller_token = await _session(setup, seller)
            async with setup.sessions() as db, db.begin():
                db.add(
                    CallAiSettings(
                        id=uuid4(),
                        tenant_id=tenant,
                        revision=1,
                        config={"default": "full", "people": {str(seller.person_id): "data_only"}},
                        created_by_person_id=setup.state.person_id,
                        created_at=datetime.now(UTC),
                    )
                )
            broker = ReportingBroker(_wav_one_second_48k())
            worker = ConversationInferenceWorker(
                setup.sessions, setup.runtime.storage, broker, authority=setup.authority
            )
            scheduler = ProcessingPlanScheduler(setup.sessions, setup.authority)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:

                def as_(token: str) -> None:
                    client.cookies.clear()
                    client.cookies.set(setup.settings.session_cookie_name, token)

                async def accept(plan: dict[str, Any], key: str) -> httpx.Response:
                    return await client.post(
                        path + "/plan",
                        json={
                            "plan_id": plan["id"],
                            "plan_fingerprint": plan["plan_fingerprint"],
                            "privacy_revision": plan["privacy_revision"],
                            "accepted": True,
                        },
                        headers={"Origin": ORIGIN, "Idempotency-Key": key},
                    )

                async def drive(plan_id: UUID, until: str) -> None:
                    for _ in range(10):
                        await worker.run_once()
                        await _make_due(setup, plan_id)
                        await scheduler.step()
                        async with setup.sessions() as db:
                            row = await db.get(ConversationProcessingPlan, plan_id)
                            assert row is not None
                            if row.state == until:
                                return
                    raise AssertionError(f"The plan never reached {until}.")

                as_(seller_token)
                path, submission = await _upload_for_read_test(setup, client)
                await _reconcile(setup.sessions, setup.state)
                recording_id = UUID((await client.get(path)).json()["recording_id"])
                await seed_measured_fixture(
                    setup.sessions,
                    SimpleNamespace(recording_id=recording_id),
                    signal_payload=_signal(
                        source_sha256=hashlib.sha256(_wav_one_second_48k()).hexdigest()
                    ),
                )
                quoted = await client.post(
                    path + "/plan/quote", headers={"Origin": ORIGIN, "Idempotency-Key": "seller"}
                )
                assert quoted.status_code == 201, quoted.text
                first = quoted.json()
                assert (await accept(first, "seller:accept")).status_code == 202
                await drive(UUID(first["id"]), "held")

                stopped = (await client.get(path)).json()
                assert stopped["failure_code"] == "ai_data_only"
                assert (stopped["run_state"], stopped["minute_state"]) == ("failed", "released")
                assert stopped["retry_available"] is False
                assert stopped["ai_skip"] == {
                    "level": "data_only",
                    "stopped_before": "C4",
                    "can_upgrade": False,
                }
                # The transcript was made (one request); no facts or coaching.
                assert broker.calls == 1
                assert stopped["partial_results"]["transcript"] is not None
                # The seller can't upgrade their own call: only owners and admins can.
                mine = await client.post(
                    path + "/full-report", headers={"Origin": ORIGIN, "Idempotency-Key": "s-1"}
                )
                assert mine.status_code == 403

                as_(setup.token)
                seen = (await client.get(path)).json()
                assert seen["ai_skip"]["can_upgrade"] is True
                prepared, again = [
                    await client.post(
                        path + "/full-report",
                        headers={"Origin": ORIGIN, "Idempotency-Key": "admin-full"},
                    )
                    for _ in range(2)
                ]
                assert prepared.status_code == again.status_code == 201, prepared.text
                fresh = prepared.json()
                assert fresh["id"] == again.json()["id"] != first["id"]
                assert fresh["state"] == "quoted" and not fresh["accepted"]
                assert (await accept(fresh, "admin-full:accept")).status_code == 202
                await drive(UUID(fresh["id"]), "completed")

                as_(seller_token)
                done = (await client.get(path)).json()
                assert (done["run_state"], done["minute_state"]) == ("done", "delivered")
                assert done["ai_skip"] is None
                assert (await client.get(path + "/report")).status_code == 200
                # One transcription in all: the full report reused the saved transcript.
                assert broker.calls == 3
                # Nothing left to upgrade.
                as_(setup.token)
                late = await client.post(
                    path + "/full-report", headers={"Origin": ORIGIN, "Idempotency-Key": "late"}
                )
                assert late.status_code == 409

            async with setup.sessions() as db:
                stages = (
                    await db.scalars(
                        select(ConversationInferenceTask.stage)
                        .where(ConversationInferenceTask.recording_id == recording_id)
                        .order_by(ConversationInferenceTask.created_at)
                    )
                ).all()
                assert list(stages) == ["C2", "C4", "C5"]
                decisions = (
                    await db.scalars(
                        select(CallAiDecision)
                        .where(CallAiDecision.recording_id == recording_id)
                        .order_by(CallAiDecision.created_at)
                    )
                ).all()
                assert [(row.decision, row.level, row.stage) for row in decisions] == [
                    ("skipped", "data_only", "C4"),
                    ("upgraded", "data_only", None),
                ]
                assert decisions[0].person_id == seller.person_id
                assert decisions[1].actor_person_id == setup.state.person_id
                kinds = (
                    await db.scalars(
                        select(ConversationReportMinuteEvent.kind).order_by(
                            ConversationReportMinuteEvent.revision
                        )
                    )
                ).all()
                assert list(kinds)[-1] == "delivered" and "released" in kinds
                audited = await db.scalar(
                    select(AuditEvent).where(AuditEvent.action == "sales_xray.call_ai.full_report")
                )
                assert audited is not None
                assert audited.resource_id == str(submission)
                assert audited.payload["call_owner_person_id"] == str(seller.person_id)
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_a_member_cannot_upgrade_a_call(postgres_harness: Any, tmp_path: Path) -> None:
    """A removed admin loses "Get full report" at once (current role, never cached)."""

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _organisation(setup)
            async with setup.sessions() as db, db.begin():
                await db.execute(
                    update(Membership)
                    .where(Membership.person_id == setup.state.person_id)
                    .values(role="member")
                )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                path, _ = await _upload_for_read_test(setup, client)
                refused = await client.post(
                    path + "/full-report", headers={"Origin": ORIGIN, "Idempotency-Key": "m-1"}
                )
                assert refused.status_code == 403
        finally:
            await setup.engine.dispose()

    run(exercise())
