"""Actual cookie/native/transaction proof in disposable loopback PostgreSQL."""

from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi import FastAPI
from sqlalchemy import func, select, update

from ac_platform.conversation_intelligence.acquisition_models import ConversationAcquisitionUsage
from ac_platform.conversation_intelligence.acquisition_sessions import AcquisitionSessions
from ac_platform.conversation_intelligence.acquisition_source import NativeUploadPreflight
from ac_platform.conversation_intelligence.bulk_import_models import (
    ConversationRecordingImportItem,
)
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.guest_ownership import (
    GuestOwnership,
    admit_processing_actor,
)
from ac_platform.conversation_intelligence.models import ConversationCommand, ConversationRun
from ac_platform.conversation_intelligence.report_minutes import ReportMinutes
from ac_platform.db.models import model_metadata
from ac_platform.http.auth import install_identity_http
from ac_platform.http.conversation_submissions import install_submission_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.outbox.models import Job
from ac_platform.tenancy.models import Membership, Organisation
from tests.database.test_conversation_guest_ownership_postgresql import _provision
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import (
    ORIGIN,
    PREFIX,
    _headers,
    _setup,
    _wav_one_second_48k,
)


@pytest.fixture
def postgres_harness(monkeypatch):
    # This host wraps ffmpeg/ffprobe in ac-heavy. The media runtime deliberately
    # strips the process environment, including the inherited slot marker. Keep
    # that one non-secret marker for these test children only: ac-heavy verifies
    # a live ancestor guardian, and both children stay inside this test's slot.
    guardian = os.environ.get("AC_HEAVY_GUARDIAN")
    original = subprocess.Popen

    def media_child(args, *positional, **keywords):
        if (
            guardian
            and isinstance(args, (list, tuple))
            and args
            and Path(str(args[0])).name in {"ffmpeg", "ffprobe"}
            and isinstance(keywords.get("env"), dict)
        ):
            keywords["env"] = {**keywords["env"], "AC_HEAVY_GUARDIAN": guardian}
        return original(args, *positional, **keywords)

    monkeypatch.setattr(subprocess, "Popen", media_child)
    yield from _postgres_harness.__wrapped__()


async def setup_import(postgres_harness: Any, tmp_path: Any, *, gemini: bool = False) -> Any:
    setup = await _setup(postgres_harness, tmp_path, separate_operations=True, gemini=gemini)
    organisation = await seed(setup.engine, role="owner")
    member = await seed(setup.engine, tenant_id=organisation.tenant_id, role="member")
    principal = await _provision(setup.engine, organisation)
    if gemini:
        # Explicit fictional approval for this exact organisation/processor;
        # no production approval, provider send or settings change is inferred.
        bundle = setup.bundle_box["bundle"]
        bundle = bundle.model_copy(
            update={
                "acquisition_policy": bundle.acquisition_policy.model_copy(
                    update={"tenant_id": organisation.tenant_id, "processing_person_id": principal}
                )
            }
        )
        setup.bundle_box["bundle"] = type(bundle).model_validate_json(bundle.model_dump_json())
    async with setup.sessions() as db, db.begin():
        db.add(
            Organisation(
                tenant_id=organisation.tenant_id,
                created_by_person_id=setup.state.person_id,
                creation_command_id=uuid4(),
                domain_verification_token="f" * 43,
            )
        )
        db.add(
            Membership(
                tenant_id=organisation.tenant_id, person_id=setup.state.person_id, role="owner"
            )
        )
        await db.execute(
            update(IdentitySession)
            .where(IdentitySession.id == setup.state.session_id)
            .values(selected_tenant_id=organisation.tenant_id)
        )
        await db.flush()
        ledger = AcquisitionSessions(
            db,
            tenant_id=organisation.tenant_id,
            policy_revision="guest-processing-v1",
            trial_enabled=False,
        ).ledger
        account = await ledger.organisation_account(tenant_id=organisation.tenant_id, create=True)
        await ledger.write_lot(
            account=account,
            kind="grant",
            seconds=600,
            valid_from=setup.state.now,
            source_ref=f"fictional-import:{uuid4()}",
            actor_type="system",
        )
    runtime = replace(
        setup.runtime,
        policy=replace(
            setup.runtime.policy,
            tenant_ids=frozenset({setup.state.tenant_id, organisation.tenant_id}),
        ),
    )

    def factory(db, tenant_id):
        return AcquisitionSessions(
            db,
            tenant_id=tenant_id,
            policy_revision="guest-processing-v1",
            clock=lambda: setup.clock[0],
            operations_tenant_id=setup.settings.operations_tenant_id,
            trial_enabled=tenant_id == setup.state.tenant_id,
        )

    app = FastAPI()
    register_problem_handlers(app)
    require_actor = install_identity_http(app, settings=setup.settings, sessions=setup.sessions)
    install_submission_http(
        app,
        settings=setup.settings,
        sessions=setup.sessions,
        require_actor=require_actor,
        factory=factory,
        runtime=runtime,
        preflight=NativeUploadPreflight(setup.native),
    )
    setup.app, setup.runtime, setup.factory = app, runtime, factory
    setup.organisation, setup.member, setup.org_principal = organisation, member, principal
    return setup


def source(path: str, data: bytes) -> dict[str, Any]:
    return {
        "relative_path": path,
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "source_bytes": len(data),
    }


async def confirm(client, setup, files, *, key="fixture-import", unmatched=False, person_id=None):
    preview = await client.post(
        PREFIX + "/imports/preview", json={"files": files}, headers={"Origin": ORIGIN}
    )
    assert preview.status_code == 200, preview.text
    policy = await client.get(PREFIX + "/upload-policy")
    body = {
        "manifest": {"files": files},
        "manifest_sha256": preview.json()["manifest_sha256"],
        "policy_sha256": policy.json()["policy_sha256"],
        "rights_confirmed": True,
        "folders": [
            {
                "folder": folder["folder"],
                "person_id": None
                if unmatched and folder["folder"] == "Unknown"
                else str(person_id or setup.member.person_id),
            }
            for folder in preview.json()["folders"]
        ],
    }
    return await client.post(
        PREFIX + "/imports", json=body, headers={"Origin": ORIGIN, "Idempotency-Key": key}
    ), body


async def client_for(setup):
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN)
    client.cookies.set(
        setup.settings.session_cookie_name, setup.token, domain="salesxray.example.test", path="/"
    )
    return client


def batch_headers(batch, index):
    return {"X-Recording-Import": batch["batch_id"], "X-Recording-Import-Item": str(index)}


async def upload(client, batch, index, data):
    headers = {**await _headers(client, data), **batch_headers(batch, index)}
    submission_id = batch["files"][index]["submission_id"]
    # Pending rows expose their stable intended source ID only in the upload field.
    from ac_platform.conversation_intelligence.bulk_imports import import_submission_id

    submission_id = submission_id or str(
        import_submission_id(UUID(batch["tenant_id"]), hashlib.sha256(data).hexdigest())
    )
    return await client.put(
        f"{PREFIX}/submissions/{submission_id}/source", content=data, headers=headers
    )


def test_manifest_receipt_is_replayed_without_content_jobs_or_minutes_and_migration_has_no_drift(
    postgres_harness, tmp_path
):
    async def exercise():
        setup = await setup_import(postgres_harness, tmp_path)
        try:
            async with await client_for(setup) as client:
                files = [source("Rep/one", b"abc"), source("Unknown/two.wav", b"def")]
                response, body = await confirm(client, setup, files, unmatched=True)
                assert response.status_code == 201, response.text
                batch = response.json()
                assert [item["state"] for item in batch["files"]] == [
                    "awaiting_upload",
                    "needs_member",
                ]
                assert batch["terminal_state"] is None
                replay = await client.post(
                    PREFIX + "/imports",
                    json=body,
                    headers={"Origin": ORIGIN, "Idempotency-Key": "fixture-import"},
                )
                assert replay.status_code == 201 and replay.json() == batch
                body["folders"][0]["person_id"] = str(setup.organisation.person_id)
                collision = await client.post(
                    PREFIX + "/imports",
                    json=body,
                    headers={"Origin": ORIGIN, "Idempotency-Key": "fixture-import"},
                )
                assert collision.status_code == 409
                read = await client.get(PREFIX + "/imports/" + batch["batch_id"])
                assert read.status_code == 200 and read.json() == batch
                assert read.headers["cache-control"] == "private, no-store"
            async with setup.sessions() as db:
                assert (
                    await db.scalar(select(func.count()).select_from(ConversationAcquisitionUsage))
                    == 0
                )
                assert await db.scalar(select(func.count()).select_from(Job)) == 0
                receipt = await db.scalar(
                    select(ConversationCommand).where(
                        ConversationCommand.action == "recording_import_confirmed"
                    )
                )
                assert receipt.person_id == setup.state.person_id and receipt.result_id == UUID(
                    batch["batch_id"]
                )
                item = await db.get(ConversationRecordingImportItem, (UUID(batch["batch_id"]), 0))
                assert item.person_id == setup.member.person_id
                assert item.usage_id is None and len(item.path_sha256) == 64
            async with setup.engine.connect() as connection:
                diff = await connection.run_sync(
                    lambda sync: compare_metadata(
                        MigrationContext.configure(sync), model_metadata()
                    )
                )
                assert diff == []
            setup.clock[0] += timedelta(days=8)
            async with setup.sessions() as db, db.begin():
                # Direct service read still uses a currently valid fictional session.
                await db.execute(
                    update(IdentitySession)
                    .where(IdentitySession.id == setup.state.session_id)
                    .values(expires_at=setup.clock[0] + timedelta(days=1))
                )
            async with await client_for(setup) as client:
                expired = await client.get(PREFIX + "/imports/" + batch["batch_id"])
                assert expired.status_code == 200, expired.text
                assert expired.json()["terminal_state"] == "failed"
                assert {item["state"] for item in expired.json()["files"]} == {"expired"}
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_restart_and_racing_safe_retries_renew_once_without_changing_member_ownership(
    postgres_harness, tmp_path
):
    async def exercise():
        import asyncio

        from ac_platform.conversation_intelligence.guest_models import ConversationProcessingLease
        from ac_platform.conversation_intelligence.processing_actor import ProcessingActor

        setup = await setup_import(postgres_harness, tmp_path)
        data = _wav_one_second_48k()
        try:
            async with await client_for(setup) as client:
                response, _ = await confirm(client, setup, [source("Rep/one", data)])
                assert response.status_code == 201, response.text
                batch = response.json()
                uploaded = await upload(client, batch, 0, data)
                assert uploaded.status_code == 202, uploaded.text
                identifier = uploaded.json()["submission_id"]
            async with setup.sessions() as db, db.begin():
                # Persist a terminal fictional local attempt, then construct
                # a fresh HTTP app. No mock identity, provider or minute write.
                original_run = await db.scalar(select(ConversationRun))
                original_job = await db.get(Job, original_run.job_id)
                original_job.status = "dead_letter"
                original_job.dead_lettered_at = setup.clock[0]
                original_job.last_error = "fictional_local_failure"
                original_run.state = "failed"
                original_run.completed_at = setup.clock[0]
                await db.flush()
                assert await ReportMinutes(db).release_failed_local()
                item = await db.get(ConversationRecordingImportItem, (UUID(batch["batch_id"]), 0))
                usage_id = item.usage_id
                assert (await ReportMinutes(db).latest(usage_id)).kind == "released"
                lease = await db.scalar(
                    select(ConversationProcessingLease).where(
                        ConversationProcessingLease.usage_id == usage_id
                    )
                )
                processing = ProcessingActor(lease.person_id, lease.tenant_id, lease.id)
            setup.clock[0] += timedelta(hours=1, seconds=1)
            restarted = FastAPI()
            register_problem_handlers(restarted)
            identity = install_identity_http(
                restarted, settings=setup.settings, sessions=setup.sessions
            )
            install_submission_http(
                restarted,
                settings=setup.settings,
                sessions=setup.sessions,
                require_actor=identity,
                factory=setup.factory,
                runtime=setup.runtime,
                preflight=NativeUploadPreflight(setup.native),
            )
            setup.app = restarted
            async with await client_for(setup) as client:
                denied = await client.post(
                    f"{PREFIX}/submissions/{identifier}/retry",
                    headers={"Origin": ORIGIN, "Idempotency-Key": "admin-is-not-owner"},
                )
                assert denied.status_code == 404
                headers = {
                    "Origin": ORIGIN,
                    "Idempotency-Key": "same-import-retry",
                    **batch_headers(batch, 0),
                }
                retries = await asyncio.gather(
                    *(
                        client.post(f"{PREFIX}/submissions/{identifier}/retry", headers=headers)
                        for _ in range(2)
                    )
                )
                assert all(result.status_code == 201 for result in retries), [
                    result.text for result in retries
                ]
                assert retries[0].json()["run_id"] == retries[1].json()["run_id"]
                progress = await client.get(PREFIX + "/imports/" + batch["batch_id"])
                assert progress.status_code == 200, progress.text
                assert progress.json()["files"][0]["run_state"] == "queued"
            async with setup.sessions() as db, db.begin():
                usage = await db.get(ConversationAcquisitionUsage, usage_id)
                assert usage.person_id == setup.member.person_id
                assert (
                    await db.scalar(select(func.count()).select_from(ConversationAcquisitionUsage))
                    == 1
                )
                assert await db.scalar(select(func.count()).select_from(Job)) == 2
                assert (await ReportMinutes(db).latest(usage_id)).kind == "reserved"
                pool = await setup.factory(
                    db, setup.organisation.tenant_id
                ).ledger.project_organisation(
                    tenant_id=setup.organisation.tenant_id, now=setup.clock[0]
                )
                assert pool.committed_seconds == 1
                await db.execute(
                    update(Membership)
                    .where(
                        Membership.tenant_id == setup.organisation.tenant_id,
                        Membership.person_id == setup.state.person_id,
                    )
                    .values(role="member")
                )
            # After admission, the real member owns the ordinary call. Uploader
            # demotion does not retroactively change its immutable provenance.
            async with setup.sessions() as db, db.begin():
                admitted = await admit_processing_actor(db, processing, setup.clock[0])
                assert admitted.id == usage_id and admitted.person_id == setup.member.person_id
            assert setup.native.calls == 1
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_native_upload_keeps_member_and_principal_replays_hash_and_leaves_normal_users_unblocked(
    postgres_harness, tmp_path
):
    async def exercise():
        setup = await setup_import(postgres_harness, tmp_path)
        data = _wav_one_second_48k()
        other = bytearray(data)
        other[-2] ^= 1
        other = bytes(other)
        try:
            async with await client_for(setup) as client:
                response, _ = await confirm(
                    client, setup, [source("Rep/one", data), source("Rep/two.wav", other)]
                )
                assert response.status_code == 201, response.text
                batch = response.json()
                accepted = await upload(client, batch, 0, data)
                assert accepted.status_code == 202, accepted.text
                repeated = await upload(client, batch, 0, data)
                assert (
                    repeated.status_code == 202 and repeated.json()["state"] == "already_imported"
                )
                assert setup.native.calls == 1
                blocked = await upload(client, batch, 1, other)
                assert blocked.status_code == 409, blocked.text
                assert setup.native.calls == 1
                setup.clock[0] += timedelta(seconds=1)
                ordinary = await client.put(
                    f"{PREFIX}/submissions/{uuid4()}/source",
                    content=other,
                    headers=await _headers(client, other),
                )
                assert ordinary.status_code == 202, ordinary.text
                assert setup.native.calls == 2
                progress = await client.get(PREFIX + "/imports/" + batch["batch_id"])
                assert progress.status_code == 200, progress.text
                assert progress.json()["files"][0]["state"] == "queued"
                assert progress.json()["files"][0]["minute_state"] in {None, "reserved"}
                assert progress.json()["files"][1]["state"] == "awaiting_upload"
                # A fresh batch reuses the original normal call even if this
                # uploader confirmed a different member; ownership is retained.
                another, body = await confirm(
                    client,
                    setup,
                    [source("Different/copy.wav", data)],
                    key="fixture-second-batch",
                    person_id=setup.organisation.person_id,
                )
                assert another.status_code == 201
                reuse = await upload(client, another.json(), 0, data)
                assert (
                    reuse.status_code == 202
                    and reuse.json()["submission_id"] == accepted.json()["submission_id"]
                )
                assert setup.native.calls == 2
                reused_progress = await client.get(
                    PREFIX + "/imports/" + another.json()["batch_id"]
                )
                assert reused_progress.json()["files"][0]["person_id"] == str(
                    setup.member.person_id
                )
                assert reused_progress.json()["files"][0]["confirmed_person_id"] == str(
                    setup.organisation.person_id
                )
            async with setup.sessions() as db:
                usages = list(
                    (
                        await db.scalars(
                            select(ConversationAcquisitionUsage).where(
                                ConversationAcquisitionUsage.tenant_id
                                == setup.organisation.tenant_id
                            )
                        )
                    ).all()
                )
                assert len(usages) == 2
                member_usage = next(
                    row
                    for row in usages
                    if row.submission_id == UUID(accepted.json()["submission_id"])
                )
                assert (
                    member_usage.person_id == setup.member.person_id
                    and member_usage.visitor_id is None
                )
                link = await db.get(
                    ConversationGuestSubmission,
                    (member_usage.tenant_id, member_usage.submission_id),
                )
                assert link.person_id == setup.org_principal and link.usage_id == member_usage.id
                assert await db.scalar(select(func.count()).select_from(Job)) == 2
                allowance = await GuestOwnership(
                    setup.factory(db, setup.organisation.tenant_id)
                ).sessions.ledger.project_organisation(
                    tenant_id=setup.organisation.tenant_id, now=setup.clock[0]
                )
                assert allowance.committed_seconds == 2
            async with setup.sessions() as db, db.begin():
                setup.clock[0] += timedelta(hours=1, seconds=1)
                assert await ReportMinutes(db).release_expired_source(now=setup.clock[0])
            async with await client_for(setup) as client:
                read = await client.get(PREFIX + "/imports/" + batch["batch_id"])
                assert read.status_code == 200, read.text
                assert read.json()["files"][0]["run_state"] == "failed"
                assert read.json()["files"][0]["minute_state"] == "released"
                # Source-hash reuse never reserves again, even after failure.
                old = await upload(client, batch, 0, data)
                assert old.status_code == 202 and old.json()["state"] == "already_imported"
                assert setup.native.calls == 2
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_role_revocation_during_real_native_upload_rolls_back_before_any_call_or_hold(
    postgres_harness, tmp_path
):
    async def exercise():
        setup = await setup_import(postgres_harness, tmp_path)
        data = _wav_one_second_48k()
        try:
            async with await client_for(setup) as client:
                response, _ = await confirm(client, setup, [source("Rep/one", data)])
                assert response.status_code == 201, response.text
                batch = response.json()
                headers = {
                    **await _headers(client, data),
                    **batch_headers(batch, 0),
                    "Content-Length": str(len(data)),
                }
                from ac_platform.conversation_intelligence.bulk_imports import import_submission_id

                identifier = import_submission_id(
                    setup.organisation.tenant_id, hashlib.sha256(data).hexdigest()
                )

                async def chunks():
                    yield data[:10]
                    async with setup.sessions() as db, db.begin():
                        await db.execute(
                            update(Membership)
                            .where(
                                Membership.tenant_id == setup.organisation.tenant_id,
                                Membership.person_id == setup.state.person_id,
                            )
                            .values(role="member")
                        )
                    yield data[10:]

                failed = await client.put(
                    f"{PREFIX}/submissions/{identifier}/source", content=chunks(), headers=headers
                )
                assert failed.status_code == 403, failed.text
            async with setup.sessions() as db:
                assert (
                    await db.scalar(select(func.count()).select_from(ConversationAcquisitionUsage))
                    == 0
                )
                assert await db.scalar(select(func.count()).select_from(Job)) == 0
                item = await db.get(ConversationRecordingImportItem, (UUID(batch["batch_id"]), 0))
                assert item.usage_id is None
            assert setup.native.calls == 1
            assert list(setup.runtime.scratch.root.glob("work-*")) == []
        finally:
            await setup.engine.dispose()

    run(exercise())
