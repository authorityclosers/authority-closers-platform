"""A slow or member-blocked recording import never lets a call expire unprocessed.

On 18 Oct 2026, 46 imported calls expired with conversation_run_budget_expired. Each
upload had its own one-hour budget; their member had no complete Sales X-Ray profile,
so the worker held every call at its first claim and nothing resumed it. Fictional
data only.
"""

from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select, update

from ac_platform.conversation_intelligence.acquisition_models import ConversationAcquisitionUsage
from ac_platform.conversation_intelligence.guest_models import (
    ConversationGuestSubmission,
    ConversationProcessingLease,
)
from ac_platform.conversation_intelligence.models import ConversationRun
from ac_platform.conversation_intelligence.released_run_recovery import stop_released_run
from ac_platform.conversation_intelligence.report_minutes import ReportMinutes
from ac_platform.conversation_intelligence.source_run_budget import expired_source_reservations
from ac_platform.conversation_intelligence.worker_account_gate import (
    PROFILE_INCOMPLETE_HOLD_REASON,
)
from ac_platform.identity.sales_xray_profile_models import SalesXrayProfile
from ac_platform.outbox.models import Job
from ac_platform.outbox.repository import RecoveryStateRepository
from tests.database.test_bulk_import_postgresql import (
    batch_headers,
    client_for,
    setup_import,
    source,
    upload,
)
from tests.database.test_bulk_import_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import (
    ORIGIN,
    PREFIX,
    _wav_one_second_48k,
)


@pytest.fixture
def postgres_harness(monkeypatch):
    yield from _postgres_harness.__wrapped__(monkeypatch)


def _variant(data: bytes) -> bytes:
    changed = bytearray(data)
    changed[-2] ^= 1
    return bytes(changed)


async def _confirm_for(client, owners, files, *, key):
    preview = await client.post(
        PREFIX + "/imports/preview", json={"files": files}, headers={"Origin": ORIGIN}
    )
    assert preview.status_code == 200, preview.text
    assert {folder["folder"] for folder in preview.json()["folders"]} == set(owners)
    policy = await client.get(PREFIX + "/upload-policy")
    response = await client.post(
        PREFIX + "/imports",
        json={
            "manifest": {"files": files},
            "manifest_sha256": preview.json()["manifest_sha256"],
            "policy_sha256": policy.json()["policy_sha256"],
            "rights_confirmed": True,
            "folders": [
                {"folder": folder["folder"], "person_id": str(owners[folder["folder"]])}
                for folder in preview.json()["folders"]
            ],
        },
        headers={"Origin": ORIGIN, "Idempotency-Key": key},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _lease(db, tenant_id, accepted) -> ConversationProcessingLease:
    link = await db.get(
        ConversationGuestSubmission, (tenant_id, UUID(accepted.json()["submission_id"]))
    )
    lease = await db.get(ConversationProcessingLease, link.processing_lease_id)
    assert lease is not None
    return lease


async def _set_phone(setup, person_id, phone):
    async with setup.sessions() as db, db.begin():
        await db.execute(
            update(SalesXrayProfile)
            .where(SalesXrayProfile.person_id == person_id)
            .values(phone_number_e164=phone)
        )


async def _count(db, model) -> int:
    return await db.scalar(select(func.count()).select_from(model))


def test_a_slow_import_gives_each_recording_its_own_one_hour_budget(postgres_harness, tmp_path):
    async def exercise():
        setup = await setup_import(postgres_harness, tmp_path)
        data = _wav_one_second_48k()
        later = _variant(data)
        try:
            async with await client_for(setup) as client:
                batch = await _confirm_for(
                    client,
                    {"Rep": setup.member.person_id},
                    [source("Rep/one", data), source("Rep/two", later)],
                    key="slow-import",
                )
                started = setup.clock[0]
                first = await upload(client, batch, 0, data)
                assert first.status_code == 202, first.text
                # The browser uploads one recording at a time. This one starts 90
                # minutes after the batch, past the whole first upload budget.
                setup.clock[0] = started + timedelta(minutes=90)
                second = await upload(client, batch, 1, later)
                assert second.status_code == 202, second.text
            async with setup.sessions() as db:
                one = await _lease(db, setup.organisation.tenant_id, first)
                two = await _lease(db, setup.organisation.tenant_id, second)
                assert (one.created_at, one.expires_at) == (started, started + timedelta(hours=1))
                assert (two.created_at, two.expires_at) == (
                    started + timedelta(minutes=90),
                    started + timedelta(minutes=150),
                )

                async def due(minutes: int) -> set[UUID]:
                    usages = await db.scalars(
                        expired_source_reservations(started + timedelta(minutes=minutes))
                    )
                    return {usage.id for usage in usages}

                assert one.usage_id in await due(120)
                assert two.usage_id not in await due(149)
                assert two.usage_id in await due(150)
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_an_import_waits_for_member_setup_instead_of_reserving_a_call_that_expires(
    postgres_harness, tmp_path
):
    async def exercise():
        setup = await setup_import(postgres_harness, tmp_path)
        newcomer = await seed(setup.engine, tenant_id=setup.organisation.tenant_id, role="member")
        await _set_phone(setup, newcomer.person_id, None)
        data = _wav_one_second_48k()
        theirs = _variant(data)
        try:
            async with await client_for(setup) as client:
                batch = await _confirm_for(
                    client,
                    {"Ready": setup.member.person_id, "New": newcomer.person_id},
                    [source("Ready/one", data), source("New/two", theirs)],
                    key="member-setup-import",
                )
                assert [(row["state"], row["member_setup_required"]) for row in batch["files"]] == [
                    ("awaiting_upload", False),
                    ("needs_member", True),
                ]
                measured = setup.native.calls
                refused = await upload(client, batch, 1, theirs)
                assert refused.status_code == 409, refused.text
                assert "phone number" in refused.text
                # Refused before any bytes, minutes, upload budget or job exist.
                assert setup.native.calls == measured
                async with setup.sessions() as db:
                    assert await _count(db, ConversationAcquisitionUsage) == 0
                    assert await _count(db, ConversationProcessingLease) == 0
                    assert await _count(db, Job) == 0
                accepted = await upload(client, batch, 0, data)
                assert accepted.status_code == 202, accepted.text
                # The member adds a phone number much later. The waiting recording
                # then uploads under them with its own full budget.
                await _set_phone(setup, newcomer.person_id, "+15550000123")
                setup.clock[0] += timedelta(minutes=90)
                progress = await client.get(PREFIX + "/imports/" + batch["batch_id"])
                assert progress.status_code == 200, progress.text
                waiting = progress.json()["files"][1]
                assert (waiting["state"], waiting["member_setup_required"]) == (
                    "awaiting_upload",
                    False,
                )
                resumed = await upload(client, batch, 1, theirs)
                assert resumed.status_code == 202, resumed.text
            async with setup.sessions() as db:
                lease = await _lease(db, setup.organisation.tenant_id, resumed)
                usage = await db.get(ConversationAcquisitionUsage, lease.usage_id)
                assert usage.person_id == newcomer.person_id
                assert (lease.created_at, lease.expires_at) == (
                    setup.clock[0],
                    setup.clock[0] + timedelta(hours=1),
                )
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_an_expired_import_call_is_not_retried_into_another_hold_before_member_setup(
    postgres_harness, tmp_path
):
    async def exercise():
        setup = await setup_import(postgres_harness, tmp_path)
        data = _wav_one_second_48k()
        try:
            async with await client_for(setup) as client:
                batch = await _confirm_for(
                    client, {"Rep": setup.member.person_id}, [source("Rep/one", data)], key="held"
                )
                uploaded = await upload(client, batch, 0, data)
                assert uploaded.status_code == 202, uploaded.text
                identifier = uploaded.json()["submission_id"]
            # 18 Oct: the member's profile was incomplete, the worker held the call
            # and its upload budget ran out before anything resumed it.
            await _set_phone(setup, setup.member.person_id, None)
            async with setup.sessions() as db, db.begin():
                held = await db.scalar(select(Job))
                held.status, held.held_at = "held", setup.clock[0]
                held.hold_reason = PROFILE_INCOMPLETE_HOLD_REASON
                await db.flush()
                setup.clock[0] += timedelta(hours=1, seconds=1)
                assert await ReportMinutes(db).release_expired_source(now=setup.clock[0])
                recovery = await RecoveryStateRepository(db).require_ready(
                    lock=True, shared_lock=True
                )
                assert await stop_released_run(db, generation=recovery.generation)
            async with setup.sessions() as db:
                stopped = await db.scalar(select(Job))
                assert (stopped.status, stopped.last_error) == (
                    "dead_letter",
                    "conversation_run_budget_expired",
                )
                assert (await db.scalar(select(ConversationRun))).state == "failed"
            headers = {"Origin": ORIGIN, **batch_headers(batch, 0)}
            path = f"{PREFIX}/submissions/{identifier}/retry"
            async with await client_for(setup) as client:
                progress = await client.get(PREFIX + "/imports/" + batch["batch_id"])
                assert progress.json()["files"][0]["run_state"] == "failed"
                refused = await client.post(
                    path, headers={**headers, "Idempotency-Key": "retry-before-setup"}
                )
                assert refused.status_code == 409, refused.text
                assert "phone number" in refused.text
                async with setup.sessions() as db:
                    assert await _count(db, Job) == 1
                    usage_id = await db.scalar(select(ConversationAcquisitionUsage.id))
                    assert (await ReportMinutes(db).latest(usage_id)).kind == "released"
                await _set_phone(setup, setup.member.person_id, "+15550000124")
                retried = await client.post(
                    path, headers={**headers, "Idempotency-Key": "retry-after-setup"}
                )
                assert retried.status_code == 201, retried.text
            async with setup.sessions() as db:
                assert await _count(db, Job) == 2
                assert (await ReportMinutes(db).latest(usage_id)).kind == "reserved"
        finally:
            await setup.engine.dispose()

    run(exercise())
