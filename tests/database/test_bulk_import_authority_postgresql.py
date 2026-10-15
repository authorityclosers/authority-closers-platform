"""Current authority, replay races and append-only batch decisions in PostgreSQL."""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError

from ac_platform.conversation_intelligence.acquisition_models import ConversationAcquisitionUsage
from ac_platform.conversation_intelligence.bulk_import_models import (
    ConversationRecordingImport,
    ConversationRecordingImportItem,
)
from ac_platform.conversation_intelligence.models import ConversationCommand
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.outbox.models import Job
from ac_platform.tenancy.models import Membership
from tests.database.test_bulk_import_postgresql import (
    batch_headers,
    client_for,
    confirm,
    setup_import,
    source,
    upload,
)
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import (
    ORIGIN,
    PREFIX,
    _headers,
    _wav_one_second_48k,
)


@pytest.fixture
def postgres_harness():
    yield from _postgres_harness.__wrapped__()


def test_current_member_tenant_and_exact_request_grant_are_required_before_native_decode(
    postgres_harness, tmp_path
):
    async def exercise():
        setup = await setup_import(postgres_harness, tmp_path)
        data = _wav_one_second_48k()
        try:
            async with await client_for(setup) as client:
                response, body = await confirm(
                    client,
                    setup,
                    [source("Rep/one", data), source("Unknown/two", b"fictional")],
                    unmatched=True,
                )
                assert response.status_code == 201, response.text
                batch = response.json()
                target = f"{PREFIX}/submissions/{batch['files'][0]['upload_submission_id']}/source"
                normal = await _headers(client, data)
                incomplete = await client.put(
                    target,
                    content=data,
                    headers={
                        **normal,
                        "X-Recording-Import": batch["batch_id"],
                    },
                )
                assert incomplete.status_code == 422
                wrong_item = await client.put(
                    target,
                    content=data,
                    headers={
                        **normal,
                        **batch_headers(batch, 255),
                    },
                )
                assert wrong_item.status_code == 404
                wrong_source = await client.put(
                    f"{PREFIX}/submissions/{uuid4()}/source",
                    content=data,
                    headers={**normal, **batch_headers(batch, 0)},
                )
                assert wrong_source.status_code == 409
                unmatched = await upload(client, batch, 1, b"fictional")
                assert unmatched.status_code == 409
                for method, suffix in (("DELETE", ""), ("PATCH", "/label")):
                    denied = await client.request(
                        method,
                        f"{PREFIX}/submissions/{batch['files'][0]['upload_submission_id']}{suffix}",
                        headers={"Origin": ORIGIN, **batch_headers(batch, 0)},
                        json={},
                    )
                    assert denied.status_code == 403
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(Membership)
                        .where(
                            Membership.tenant_id == setup.organisation.tenant_id,
                            Membership.person_id == setup.member.person_id,
                        )
                        .values(status="inactive", ended_at=setup.clock[0])
                    )
                removed = await upload(client, batch, 0, data)
                assert removed.status_code == 403
                # Reading the exact receipt is safe even if a confirmed member
                # subsequently leaves; it cannot authorize a new upload.
                replay = await client.post(
                    PREFIX + "/imports",
                    json=body,
                    headers={"Origin": ORIGIN, "Idempotency-Key": "fixture-import"},
                )
                assert replay.status_code == 201 and replay.json()["batch_id"] == batch["batch_id"]
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(IdentitySession)
                        .where(
                            IdentitySession.id == setup.state.session_id,
                        )
                        .values(selected_tenant_id=setup.state.tenant_id)
                    )
                foreign = await client.get(PREFIX + "/imports/" + batch["batch_id"])
                assert foreign.status_code == 403
            assert setup.native.calls == 0
            async with setup.sessions() as db:
                assert (
                    await db.scalar(select(func.count()).select_from(ConversationAcquisitionUsage))
                    == 0
                )
                assert await db.scalar(select(func.count()).select_from(Job)) == 0
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_same_key_concurrent_confirmations_replay_one_immutable_receipt(postgres_harness, tmp_path):
    async def exercise():
        setup = await setup_import(postgres_harness, tmp_path)
        try:
            async with await client_for(setup) as client:
                first, body = await confirm(client, setup, [source("Rep/one", b"fictional")])
                assert first.status_code == 201, first.text
                request_headers = {"Origin": ORIGIN, "Idempotency-Key": "racing-confirmation"}
                results = await asyncio.gather(
                    *(
                        client.post(PREFIX + "/imports", json=body, headers=request_headers)
                        for _ in range(3)
                    )
                )
                assert all(result.status_code == 201 for result in results)
                assert len({result.json()["batch_id"] for result in results}) == 1
                identifier = UUID(results[0].json()["batch_id"])
            async with setup.sessions() as db:
                assert (
                    await db.scalar(select(func.count()).select_from(ConversationRecordingImport))
                    == 2
                )
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(ConversationCommand)
                        .where(ConversationCommand.action == "recording_import_confirmed")
                    )
                    == 2
                )
            for statement in (
                update(ConversationRecordingImport)
                .where(ConversationRecordingImport.id == identifier)
                .values(total_bytes=10),
                delete(ConversationRecordingImport).where(
                    ConversationRecordingImport.id == identifier
                ),
                update(ConversationRecordingImportItem)
                .where(ConversationRecordingImportItem.batch_id == identifier)
                .values(person_id=setup.organisation.person_id),
                delete(ConversationRecordingImportItem).where(
                    ConversationRecordingImportItem.batch_id == identifier
                ),
            ):
                with pytest.raises(DBAPIError):
                    async with setup.sessions() as db, db.begin():
                        await db.execute(statement)
            async with setup.sessions() as db:
                item = await db.get(ConversationRecordingImportItem, (identifier, 0))
                assert item.person_id == setup.member.person_id and item.usage_id is None
        finally:
            await setup.engine.dispose()

    run(exercise())
