"""Failed/expired local work gets one bounded source-bound owner successor."""

import secrets
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionUsage,
    ConversationReportMinuteEvent,
)
from ac_platform.conversation_intelligence.application import LOCAL_JOB
from ac_platform.conversation_intelligence.models import ConversationRun
from ac_platform.conversation_intelligence.released_run_recovery import stop_released_run
from ac_platform.conversation_intelligence.report_minutes import ReportMinutes
from ac_platform.outbox.models import Job
from ac_platform.outbox.repository import JobRepository
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import (
    ORIGIN,
    _setup,
    _sign_in,
    _upload_for_read_test,
)
from tests.database.test_conversation_worker_postgresql import _postgres_harness, _reconcile
from tests.unit.conversation_intelligence.test_acquisition_source import ValidationFixtureRuntime


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


@pytest.mark.parametrize("mode", ["failure", "expired"])
def test_local_failure_releases_and_retry_survives_restart_and_replay(
    postgres_harness: Any, tmp_path: Path, mode: str
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        setup.native.validate_source = ValidationFixtureRuntime().validate_source
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                _sign_in(setup, client)
                path, submission = await _upload_for_read_test(setup, client)
                await _reconcile(setup.sessions, setup.state)
                async with setup.sessions() as db, db.begin():
                    usage = await db.scalar(
                        select(ConversationAcquisitionUsage).where(
                            ConversationAcquisitionUsage.submission_id == submission
                        )
                    )
                    original = await db.scalar(
                        select(ConversationRun)
                        .join(Job, Job.id == ConversationRun.job_id)
                        .where(
                            Job.kind == LOCAL_JOB,
                            ConversationRun.recording_id
                            == UUID((await client.get(path)).json()["recording_id"]),
                        )
                    )
                    if mode == "failure":
                        jobs = await JobRepository(db).claim(kinds=(LOCAL_JOB,), limit=1)
                        assert len(jobs) == 1
                        await JobRepository(db).fail(
                            jobs[0],
                            jobs[0].lease_token,
                            "conversation_local_phase_failed",
                            permanent=True,
                        )
                        assert await ReportMinutes(db).release_failed_local()
                        assert not await ReportMinutes(db).release_failed_local()
                    else:
                        after_budget = setup.clock[0] + timedelta(hours=1, seconds=1)
                        assert await ReportMinutes(db).release_expired_source(now=after_budget)
                        assert await stop_released_run(db, generation=1)
                        assert not await stop_released_run(db, generation=1)
                        setup.clock[0] = after_budget
                failed = (await client.get(path)).json()
                assert failed["run_state"] == "failed" and failed["minute_state"] == "released"
                headers = {"Origin": ORIGIN, "Idempotency-Key": "retry:local"}
                if mode == "failure":
                    from hashlib import sha256
                    from hmac import digest

                    from ac_platform.identity.models import Session as IdentitySession
                    from ac_platform.tenancy.models import Organisation

                    manager = await seed(
                        setup.engine, tenant_id=setup.state.tenant_id, role="admin"
                    )
                    manager_token = secrets.token_urlsafe(32)
                    async with setup.sessions() as db, db.begin():
                        if await db.get(Organisation, setup.state.tenant_id) is None:
                            db.add(
                                Organisation(
                                    tenant_id=setup.state.tenant_id,
                                    creation_command_id=uuid4(),
                                    domain_verification_token="f" * 43,
                                )
                            )
                        manager_session = await db.get(IdentitySession, manager.session_id)
                        manager_session.token_hash = digest(
                            setup.settings.session_token_pepper.get_secret_value().encode(),
                            manager_token.encode(),
                            sha256,
                        )
                    async with httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
                    ) as reader:
                        reader.cookies.set(setup.settings.session_cookie_name, manager_token)
                        read = await reader.get(path)
                        assert read.status_code == 200, read.text
                        assert read.json()["run_state"] == "failed"
                        assert read.json()["retry_available"] is False
                        assert (
                            await reader.post(path + "/retry", headers=headers)
                        ).status_code == 404
                assert (
                    await client.post(
                        path + "/retry",
                        headers={**headers, "Origin": "https://untrusted.example.test"},
                    )
                ).status_code == 403
                assert (
                    await client.post(path + "/retry", headers={"Origin": ORIGIN})
                ).status_code == 422
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
                ) as stranger:
                    assert (
                        await stranger.post(path + "/retry", headers=headers)
                    ).status_code == 401
                    stranger.cookies.set("ac_xray_guest", setup.stranger.token)
                    assert (
                        await stranger.post(path + "/retry", headers=headers)
                    ).status_code == 401
                prepared = await client.post(path + "/retry", headers=headers)
                assert prepared.status_code == 201, prepared.text
                view = prepared.json()
                assert view["retry_kind"] == "local" and view["state"] == "queued"
                assert UUID(view["run_id"]) != original.id
                replay = await client.post(path + "/retry", headers=headers)
                assert replay.status_code == 201 and replay.json() == view
                # A different tab must not create a third local job while the
                # confirmed successor is queued. The reservation remains once.
                other = await client.post(
                    path + "/retry", headers={**headers, "Idempotency-Key": "retry:other"}
                )
                assert other.status_code == 409
                progress = (await client.get(path)).json()
                assert progress["run_state"] == "queued" and progress["minute_state"] == "reserved"
                async with setup.sessions() as db:
                    old = await db.get(ConversationRun, original.id)
                    old_job = await db.get(Job, original.job_id)
                    assert old.state == "failed" and old_job.status == "dead_letter"
                    assert old_job.dispatch_started_at is None
                    events = list(
                        await db.scalars(
                            select(ConversationReportMinuteEvent)
                            .where(ConversationReportMinuteEvent.usage_id == usage.id)
                            .order_by(ConversationReportMinuteEvent.revision)
                        )
                    )
                    assert [e.kind for e in events] == ["released", "reserved"]
                    # The owner continuation budget protects the restarted
                    # local retry when the original immutable lease expired.
                    assert not await ReportMinutes(db).release_expired_source(now=setup.clock[0])
                if mode == "failure":
                    # The owner may try two local successors. A fourth attempt
                    # fails atomically with the last reservation still released.
                    for attempt in (2, 3):
                        async with setup.sessions() as db, db.begin():
                            jobs = await JobRepository(db).claim(kinds=(LOCAL_JOB,), limit=1)
                            assert len(jobs) == 1
                            await JobRepository(db).fail(
                                jobs[0],
                                jobs[0].lease_token,
                                "conversation_local_phase_failed",
                                permanent=True,
                            )
                            assert await ReportMinutes(db).release_failed_local()
                        next_retry = await client.post(
                            path + "/retry",
                            headers={**headers, "Idempotency-Key": f"retry:local:{attempt}"},
                        )
                        assert next_retry.status_code == (201 if attempt == 2 else 409), (
                            next_retry.text
                        )
                    assert (await client.get(path)).json()["minute_state"] == "released"
        finally:
            await setup.engine.dispose()

    run(exercise())
