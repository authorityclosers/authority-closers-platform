"""Actual HTTP/cookie/PostgreSQL proof for account-owned saved upload discovery."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select, update

from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionUsage,
    ConversationVisitorClaim,
)
from ac_platform.conversation_intelligence.acquisition_processing import (
    AcquisitionProcessing,
    upload_policy,
)
from ac_platform.conversation_intelligence.acquisition_sessions import MeasuredSource
from ac_platform.conversation_intelligence.acquisition_source import MeasuredUpload
from ac_platform.conversation_intelligence.contracts import IntakeIntent
from ac_platform.conversation_intelligence.guest_models import ConversationProcessingLease
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.models import (
    ConversationPermission,
    ConversationRecording,
)
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.outbox.models import Job
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import (
    ORIGIN,
    PREFIX,
    _headers,
    _setup,
)
from tests.database.test_conversation_worker_postgresql import _wav_one_second_48k


@pytest.fixture(scope="module")
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


async def _upload(client: httpx.AsyncClient) -> dict[str, Any]:
    audio = _wav_one_second_48k()
    response = await client.put(
        PREFIX + f"/submissions/{uuid4()}/source",
        content=audio,
        headers=await _headers(client, audio),
    )
    assert response.status_code == 202, response.json()
    return response.json()


async def _seed_retained_guest_submission(setup: Any) -> dict[str, Any]:
    """Create a pre-cutover retained guest record through canonical services."""
    audio = _wav_one_second_48k()
    submission_id = uuid4()
    source_sha256 = hashlib.sha256(audio).hexdigest()
    upload = MeasuredUpload(
        MeasuredSource(
            submission_id,
            source_sha256,
            1_000,
            hashlib.sha256(b"account-library-legacy-duration").hexdigest(),
        ),
        IntakeIntent(
            source_sha256=source_sha256,
            source_bytes=len(audio),
            content_type="audio/wav",
            duration_ms=1_000,
            purpose="internal_analysis",
        ),
    )
    async with setup.sessions() as db, db.begin():
        processing = AcquisitionProcessing(GuestOwnership(setup.factory(db)), setup.runtime)
        processing_actor, quote = await processing.prepare(
            upload,
            policy_sha256=upload_policy(setup.runtime.policy)["policy_sha256"],
            token=setup.guest.token,
        )
        recording_id = UUID(quote["recording_id"])
        await processing.application.store_source(
            processing_actor,
            recording_id,
            chunks=(audio,),
            storage=setup.runtime.storage,
        )
        recording = await db.get(ConversationRecording, recording_id)
        usage = await db.scalar(
            select(ConversationAcquisitionUsage).where(
                ConversationAcquisitionUsage.tenant_id == setup.state.tenant_id,
                ConversationAcquisitionUsage.submission_id == submission_id,
            )
        )
        assert recording is not None and usage is not None
        return {
            "submission_id": submission_id,
            "recording_id": recording_id,
            "recording_person_id": recording.person_id,
            "usage_id": usage.id,
        }


async def _session(setup: Any, state: Any) -> str:
    token = secrets.token_urlsafe(32)
    pepper = setup.settings.session_token_pepper.get_secret_value()
    async with setup.sessions() as db, db.begin():
        await db.execute(
            update(Person)
            .where(Person.id == state.person_id)
            .values(email=f"library-{state.person_id.hex}@example.test")
        )
        await db.execute(
            update(IdentitySession)
            .where(IdentitySession.id == state.session_id)
            .values(token_hash=hmac.new(pepper.encode(), token.encode(), hashlib.sha256).digest())
        )
    return token


def test_account_library_discovers_claimed_and_direct_calls_without_reassignment(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        transport = httpx.ASGITransport(app=setup.app)
        try:
            async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as guest:
                assert (await guest.get(PREFIX + "/submissions")).status_code == 401
                guest.cookies.set("ac_xray_guest", setup.guest.token)
                guest_upload = await guest.put(
                    PREFIX + f"/submissions/{uuid4()}/source",
                    content=(audio := _wav_one_second_48k()),
                    headers=await _headers(guest, audio),
                )
                assert guest_upload.status_code == 401
                assert (await guest.get(PREFIX + "/submissions")).status_code == 401
            retained_guest = await _seed_retained_guest_submission(setup)
            async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as account:
                account.cookies.set(setup.settings.session_cookie_name, setup.token)
                assert (await account.get(PREFIX + "/submissions")).json()["submissions"] == []
                async with setup.sessions() as db, db.begin():
                    jobs_before_claim = await db.scalar(select(func.count()).select_from(Job))
                    await setup.factory(db).claim(setup.guest.token, setup.state.actor)
                async with setup.sessions() as db:
                    claim = await db.get(ConversationVisitorClaim, setup.guest.visitor_id)
                    usage = await db.get(ConversationAcquisitionUsage, retained_guest["usage_id"])
                    recording = await db.get(ConversationRecording, retained_guest["recording_id"])
                    assert claim is not None and claim.person_id == setup.state.person_id
                    assert usage is not None
                    assert usage.visitor_id == setup.guest.visitor_id and usage.person_id is None
                    assert recording is not None
                    assert recording.person_id == retained_guest["recording_person_id"]
                    assert recording.person_id != setup.state.person_id
                    assert (
                        await db.scalar(select(func.count()).select_from(Job)) == jobs_before_claim
                    )
                async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as guest:
                    guest.cookies.set("ac_xray_guest", setup.guest.token)
                    assert (
                        await guest.get(PREFIX + f"/submissions/{retained_guest['submission_id']}")
                    ).status_code == 403
                assert {
                    row["submission_id"]
                    for row in (await account.get(PREFIX + "/submissions")).json()["submissions"]
                } == {str(retained_guest["submission_id"])}
                uploaded_first = await _upload(account)
                uploaded_second = await _upload(account)
                async with setup.sessions() as db, db.begin():
                    jobs_before = await db.scalar(select(func.count()).select_from(Job))
                # New client has no guest cookie or local-storage selector.
                response = await account.get(PREFIX + "/submissions")
                assert response.status_code == 200
                assert response.headers["cache-control"] == "private, no-store"
                assert response.headers["vary"] == "Cookie"
                rows = response.json()["submissions"]
                assert {row["submission_id"] for row in rows} == {
                    str(retained_guest["submission_id"]),
                    uploaded_first["submission_id"],
                    uploaded_second["submission_id"],
                }
                assert all(row["duration_seconds"] == 1 and not row["has_report"] for row in rows)
                assert all(
                    set(row)
                    == {"submission_id", "created_at", "duration_seconds", "state", "has_report"}
                    for row in rows
                )
                assert response.json()["next_cursor"] is None
                async with setup.sessions() as db, db.begin():
                    assert await db.scalar(select(func.count()).select_from(Job)) == jobs_before
                    recordings = (
                        await db.scalars(
                            select(ConversationRecording).where(
                                ConversationRecording.tenant_id == setup.state.tenant_id
                            )
                        )
                    ).all()
                    assert all(row.person_id != setup.state.person_id for row in recordings)
                    usage_rows = (
                        await db.scalars(
                            select(ConversationAcquisitionUsage).where(
                                ConversationAcquisitionUsage.tenant_id == setup.state.tenant_id
                            )
                        )
                    ).all()
                    assert {row.submission_id for row in usage_rows} == {
                        retained_guest["submission_id"],
                        UUID(uploaded_first["submission_id"]),
                        UUID(uploaded_second["submission_id"]),
                    }
                    by_submission = {row.submission_id: row for row in usage_rows}
                    retained_usage = by_submission[retained_guest["submission_id"]]
                    assert retained_usage.visitor_id == setup.guest.visitor_id
                    assert retained_usage.person_id is None
                    assert all(
                        by_submission[UUID(item["submission_id"])].person_id
                        == setup.state.person_id
                        and by_submission[UUID(item["submission_id"])].visitor_id is None
                        for item in (uploaded_first, uploaded_second)
                    )
                    assert (
                        await db.scalar(select(func.count()).select_from(ConversationVisitorClaim))
                        == 1
                    )
                # Owner selectors, duplicate cursors and malformed cursors do not widen scope.
                for query in (
                    "?person_id=" + str(setup.state.person_id),
                    "?before=bad",
                    "?before=" + str(uuid4()) + "&before=" + str(uuid4()),
                ):
                    assert (await account.get(PREFIX + "/submissions" + query)).status_code == 422
                assert (
                    await account.get(PREFIX + "/submissions?before=" + str(uuid4()))
                ).status_code == 404
                assert (
                    await account.get(
                        PREFIX + "/submissions", headers={"Host": "other.example.test"}
                    )
                ).status_code == 404
                for foreign_tenant in (False, True):
                    other = await seed(
                        setup.engine, tenant_id=None if foreign_tenant else setup.state.tenant_id
                    )
                    other_token = await _session(setup, other)
                    async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as stranger:
                        stranger.cookies.set("ac_session", other_token)
                        listing = await stranger.get(PREFIX + "/submissions")
                        if foreign_tenant:
                            assert listing.status_code == 403
                        else:
                            assert listing.json() == {"submissions": [], "next_cursor": None}
                            assert (
                                await stranger.get(
                                    PREFIX
                                    + "/submissions?before="
                                    + str(retained_guest["submission_id"])
                                )
                            ).status_code == 404
                        denied = await stranger.get(
                            PREFIX + f"/submissions/{retained_guest['submission_id']}"
                        )
                        assert denied.status_code in (403, 404)
                # Natural execution lease expiry does not hide retained ownership.
                setup.clock[0] = setup.state.now + timedelta(hours=2)
                async with setup.sessions() as db, db.begin():
                    leases = (
                        await db.scalars(
                            select(ConversationProcessingLease).where(
                                ConversationProcessingLease.tenant_id == setup.state.tenant_id
                            )
                        )
                    ).all()
                    assert leases and all(lease.expires_at < setup.clock[0] for lease in leases)
                assert len((await account.get(PREFIX + "/submissions")).json()["submissions"]) == 3
                # Deleting the legacy item and revoking current permissions remove its rows.
                deleted = await account.delete(
                    PREFIX + f"/submissions/{retained_guest['submission_id']}",
                    headers={"Origin": ORIGIN, "Idempotency-Key": "library-delete-claimed"},
                )
                assert deleted.status_code == 202
                assert len((await account.get(PREFIX + "/submissions")).json()["submissions"]) == 2
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(ConversationPermission)
                        .where(ConversationPermission.tenant_id == setup.state.tenant_id)
                        .values(revoked_at=setup.state.now)
                    )
                assert (await account.get(PREFIX + "/submissions")).json()["submissions"] == []
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_account_library_bounded_cursor_survives_equal_timestamps(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set("ac_session", setup.token)
                ids = {(await _upload(client))["submission_id"] for _ in range(23)}
                first = (await client.get(PREFIX + "/submissions")).json()
                assert len(first["submissions"]) == 20
                assert first["next_cursor"] == first["submissions"][-1]["submission_id"]
                second = (
                    await client.get(PREFIX + "/submissions?before=" + first["next_cursor"])
                ).json()
                assert len(second["submissions"]) == 3 and second["next_cursor"] is None
                ordered = [
                    row["submission_id"] for row in first["submissions"] + second["submissions"]
                ]
                assert len(set(ordered)) == 23 and set(ordered) == ids
                assert ordered == sorted(ids, key=UUID, reverse=True)
                # Deleting the previous page's final item must not strand pagination.
                deleted = await client.delete(
                    PREFIX + "/submissions/" + first["next_cursor"],
                    headers={"Origin": ORIGIN, "Idempotency-Key": "library-delete-cursor"},
                )
                assert deleted.status_code == 202
                continued = await client.get(PREFIX + "/submissions?before=" + first["next_cursor"])
                assert continued.status_code == 200 and continued.json() == second
        finally:
            await setup.engine.dispose()

    run(exercise())
