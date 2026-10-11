"""Sandbox flag, cookie HTTP, restart/replay and isolated no-cost relational proof."""

import asyncio
import importlib.util
import subprocess
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError

from ac_platform.audit.models import AuditEvent
from ac_platform.conversation_intelligence.acquisition_models import ConversationAcquisitionUsage
from ac_platform.conversation_intelligence.application import ConversationNotFound
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.models import ConversationInferenceTask, ConversationRun
from ac_platform.conversation_intelligence.synthetic_import_audio import (
    SyntheticAudioManifest,
    media_key,
    retain_audio,
)
from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
    ConversationSyntheticRecord,
)
from ac_platform.conversation_intelligence.synthetic_imports import SyntheticImports
from ac_platform.db.models import model_metadata
from ac_platform.http.request_limits import RequestBodyLimitMiddleware
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.outbox.models import Job
from ac_platform.tenancy.models import Membership, Organisation, Tenant
from tests.database.test_bulk_import_postgresql import client_for, setup_import
from tests.database.test_bulk_import_postgresql import postgres_harness as _bulk_postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, PREFIX
from tests.unit.conversation_intelligence.test_synthetic_import_audio import media_bundle
from tests.unit.conversation_intelligence.test_synthetic_import_contracts import bundle

pytestmark = pytest.mark.usefixtures("postgres_harness")


@pytest.fixture(scope="module")
def postgres_harness():
    # Reuse C's existing test-only guardian bridge: native children retain the
    # acquired slot, whose live ancestor is still verified by ac-heavy.
    with pytest.MonkeyPatch.context() as patch:
        yield from _bulk_postgres_harness.__wrapped__(patch)


def test_exact_sandbox_data_change_dry_run_apply_replay_and_environment_guard(
    postgres_harness, tmp_path
):
    path = Path(__file__).parents[2] / "scripts/data-changes/enable-synthetic-sandbox.py"
    spec = importlib.util.spec_from_file_location("synthetic_sandbox_data_change", path)
    assert spec is not None and spec.loader is not None
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)

    async def exercise():
        setup = await setup_import(postgres_harness, tmp_path)
        try:
            async with setup.sessions() as db, db.begin():
                db.add(Tenant(id=tool.TARGET, slug="fictional-ac-sandbox", name="AC Sandbox"))
                await db.flush()
                db.add(
                    Organisation(
                        tenant_id=tool.TARGET,
                        created_by_person_id=setup.state.person_id,
                        creation_command_id=uuid4(),
                        domain_verification_token="f" * 43,
                    )
                )
                db.add(
                    Membership(
                        tenant_id=tool.TARGET,
                        person_id=setup.state.person_id,
                        role="owner",
                    )
                )
            settings = setup.settings.model_copy(
                update={
                    "environment": "staging",
                    "database_url": postgres_harness.url.render_as_string(hide_password=False),
                }
            )
            args = dict(
                settings=settings,
                approver=setup.state.person_id,
                approval="fictional-owner-approval:AUT-1676",
            )
            preview = await tool.execute(**args, apply=False)
            assert preview["before"] is False and preview["after"] is True
            async with setup.sessions() as db:
                assert await db.get(ConversationSandboxOrganisation, tool.TARGET) is None
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(AuditEvent)
                        .where(AuditEvent.tenant_id == tool.TARGET)
                    )
                    == 0
                )
            applied = await tool.execute(**args, apply=True)
            assert applied["before"] is False and applied["applied"] is True
            repeat = await tool.execute(**args, apply=True)
            assert repeat["before"] is True and repeat["run_id"] != applied["run_id"]
            async with setup.sessions() as db:
                flag = await db.get(ConversationSandboxOrganisation, tool.TARGET)
                assert flag is not None and flag.approved_by_person_id == setup.state.person_id
                events = (
                    await db.scalars(select(AuditEvent).where(AuditEvent.tenant_id == tool.TARGET))
                ).all()
                assert len(events) == 2
                assert all(event.action == "conversation.sandbox_flag_approved" for event in events)
            for environment in ("test", "production"):
                with pytest.raises(ValueError, match="staging"):
                    await tool.execute(
                        **{
                            **args,
                            "settings": settings.model_copy(update={"environment": environment}),
                        },
                        apply=True,
                    )
        finally:
            await setup.engine.dispose()

    run(exercise())


async def flag(setup):
    async with setup.sessions() as db, db.begin():
        db.add(
            ConversationSandboxOrganisation(
                tenant_id=setup.organisation.tenant_id,
                approved_by_person_id=setup.state.person_id,
                approval_reference="fictional-owner-approval:AUT-1676",
                created_at=setup.clock[0],
            )
        )


def test_bound_sandbox_requests_refuse_changed_selection_before_any_import(
    postgres_harness, tmp_path
):
    async def exercise():
        setup = await setup_import(postgres_harness, tmp_path)
        try:
            await flag(setup)
            # Both organisations are served and explicitly flagged. The header
            # must assert the chosen target, without selecting it or granting access.
            async with setup.sessions() as db, db.begin():
                db.add(
                    Organisation(
                        tenant_id=setup.state.tenant_id,
                        created_by_person_id=setup.state.person_id,
                        creation_command_id=uuid4(),
                        domain_verification_token="g" * 43,
                    )
                )
                await db.flush()
                db.add(
                    ConversationSandboxOrganisation(
                        tenant_id=setup.state.tenant_id,
                        approved_by_person_id=setup.state.person_id,
                        approval_reference="fictional-second-sandbox:AUT-1676",
                        created_at=setup.clock[0],
                    )
                )
                await db.execute(
                    update(Membership)
                    .where(
                        Membership.tenant_id == setup.state.tenant_id,
                        Membership.person_id == setup.state.person_id,
                    )
                    .values(role="owner")
                )
            headers = {
                "Origin": ORIGIN,
                "Idempotency-Key": "bound-target",
                "X-AC-Sandbox-Tenant": str(setup.organisation.tenant_id),
            }
            endpoint = PREFIX + "/imports/sandbox"
            data, media = media_bundle(b"fictional-recording")
            call_path = endpoint + "/calls/" + data["metadata"]["call_id"]
            async with await client_for(setup) as client:
                before = await client.get(endpoint, headers=headers)
                assert before.status_code == 200, before.text
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(IdentitySession)
                        .where(IdentitySession.id == setup.state.session_id)
                        .values(selected_tenant_id=setup.state.tenant_id)
                    )
                changed = await client.get(endpoint, headers=headers)
                assert changed.status_code == 409, changed.text
                unbound = await client.get(endpoint)
                assert unbound.status_code == 200, unbound.text
                assert unbound.json()["tenant_id"] == str(setup.state.tenant_id)
                for path, body in (
                    (endpoint + "/calls", data),
                    (
                        endpoint + "/records",
                        {
                            "schema": "synthetic-record-batch/1",
                            "synthetic": True,
                            "records": [
                                {
                                    "kind": "companies",
                                    "key": "syn-fixture-company-1",
                                    "business_id": "syn-fixture",
                                    "revision": 1,
                                    "occurred_at": "2017-01-01T00:00:00Z",
                                    "payload": {
                                        "synthetic": True,
                                        "schema_version": "synthetic-sales-v1.0",
                                        "name": "Fictional",
                                    },
                                }
                            ],
                        },
                    ),
                    (call_path + "/audio", media),
                ):
                    refused = await client.post(path, json=body, headers=headers)
                    assert refused.status_code == 409, refused.text
                    assert "selected sandbox changed" in refused.json()["detail"]
                refused = await client.put(
                    call_path + "/source",
                    content=b"fictional-recording",
                    headers={**headers, "Content-Type": "audio/mpeg"},
                )
                assert refused.status_code == 409, refused.text
                assert "selected sandbox changed" in refused.json()["detail"]
                for target in ("not-a-uuid", str(setup.state.tenant_id) + "," + str(uuid4())):
                    malformed = await client.post(
                        endpoint + "/calls",
                        json=data,
                        headers={**headers, "X-AC-Sandbox-Tenant": target},
                    )
                    assert malformed.status_code == 422, malformed.text
                duplicated = await client.post(
                    endpoint + "/calls",
                    json=data,
                    headers=[*headers.items(), ("X-AC-Sandbox-Tenant", str(setup.state.tenant_id))],
                )
                assert duplicated.status_code == 422, duplicated.text
            async with setup.sessions() as db:
                assert (
                    await db.scalar(select(func.count()).select_from(ConversationSyntheticRecord))
                    == 0
                )
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_cookie_import_requires_flag_preserves_authored_report_and_never_creates_run_or_charge(
    postgres_harness,
    tmp_path,
):
    async def exercise():
        setup = await setup_import(postgres_harness, tmp_path)
        data = bundle()
        endpoint = PREFIX + "/imports/sandbox/calls"
        headers = {
            "Origin": ORIGIN,
            "Idempotency-Key": "fictional-sandbox-call",
            "X-AC-Sandbox-Tenant": str(setup.organisation.tenant_id),
        }
        try:
            async with await client_for(setup) as client:
                refused = await client.post(endpoint, json=data, headers=headers)
                assert refused.status_code == 403, refused.text
                await flag(setup)
                created = await client.post(endpoint, json=data, headers=headers)
                assert created.status_code == 201, created.text
                assert created.json() == {
                    "synthetic": True,
                    "call_id": data["metadata"]["call_id"],
                    "state": "done",
                    "created": True,
                    "processing": "authored_report",
                    "minute_state": None,
                }
            # A new cookie/HTTP client and session have no in-process import state.
            async with await client_for(setup) as client:
                replay = await client.post(endpoint, json=data, headers=headers)
                assert replay.status_code == 201 and replay.json()["created"] is False
                repeat = await client.post(
                    endpoint, json=data, headers={**headers, "Idempotency-Key": "another-key"}
                )
                assert repeat.status_code == 201 and repeat.json()["created"] is False
                read = await client.get(endpoint + "/" + data["metadata"]["call_id"])
                assert read.status_code == 200, read.text
                assert read.json()["report"] == data["report"]
                assert read.json()["transcript"] == data["transcript"]
                assert "answer_key" not in read.json() and "coaching" not in read.json()
                coaching = await client.get(
                    endpoint + "/" + data["metadata"]["call_id"] + "/coaching"
                )
                assert (
                    coaching.status_code == 200 and coaching.json()["coaching"] == data["coaching"]
                )
                edited = deepcopy(data)
                section = "the_big_picture"
                edited["report"][section] = {"authored": "superseding copy"}
                edited["answer_key"]["report"][section] = edited["report"][section]
                conflict = await client.post(
                    endpoint, json=edited, headers={**headers, "Idempotency-Key": "changed"}
                )
                assert conflict.status_code == 409, conflict.text
                untrusted = await client.post(
                    endpoint, json=data, headers={**headers, "Origin": "https://other.invalid"}
                )
                assert untrusted.status_code == 403
                progress = await client.get(PREFIX + "/imports/sandbox")
                assert progress.status_code == 200 and progress.json()["records"][0]["count"] == 1
            async with setup.sessions() as db:
                for model in (
                    Job,
                    ConversationRun,
                    ConversationInferenceTask,
                    ConversationAcquisitionUsage,
                ):
                    assert await db.scalar(select(func.count()).select_from(model)) == 0
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(ConversationSyntheticRecord)
                        .where(
                            ConversationSyntheticRecord.tenant_id == setup.organisation.tenant_id
                        )
                    )
                    == 1
                )
            with postgres_harness.connect() as connection:
                assert (
                    compare_metadata(MigrationContext.configure(connection), model_metadata()) == []
                )
            async with setup.sessions() as db, db.begin():
                actor = ActorContext(
                    setup.organisation.person_id,
                    setup.organisation.session_id,
                    setup.organisation.tenant_id,
                )
                service = SyntheticImports(GuestOwnership(setup.factory(db, actor.tenant_id)))
                with pytest.raises(ConversationNotFound, match="unavailable"):
                    await service.read_call(actor, data["metadata"]["call_id"], coaching=True)
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_atomic_master_batches_supersede_and_current_role_revocation_denies_reads(
    postgres_harness,
    tmp_path,
):
    async def exercise():
        setup = await setup_import(postgres_harness, tmp_path)
        try:
            await flag(setup)
            row = {
                "kind": "companies",
                "key": "syn-fixture-company-1",
                "business_id": "syn-fixture",
                "revision": 1,
                "occurred_at": "2017-01-01T00:00:00Z",
                "payload": {
                    "synthetic": True,
                    "schema_version": "synthetic-sales-v1.0",
                    "name": "Fictional Company",
                },
            }
            data = {"schema": "synthetic-record-batch/1", "synthetic": True, "records": [row]}
            endpoint = PREFIX + "/imports/sandbox/records"
            headers = {
                "Origin": ORIGIN,
                "Idempotency-Key": "master-1",
                "X-AC-Sandbox-Tenant": str(setup.organisation.tenant_id),
            }
            async with await client_for(setup) as client:
                first = await client.post(endpoint, json=data, headers=headers)
                assert first.status_code == 201, first.text
                assert first.json()["created"] == 1
                second = await client.post(endpoint, json=data, headers=headers)
                assert second.status_code == 201 and second.json()["skipped"] == 1
                conflict = deepcopy(data)
                conflict["records"].insert(0, {**row, "key": "syn-fixture-company-2"})
                conflict["records"][1]["payload"]["name"] = "Changed same revision"
                result = await client.post(
                    endpoint,
                    json=conflict,
                    headers={**headers, "Idempotency-Key": "atomic-conflict"},
                )
                assert result.status_code == 409
                newer = deepcopy(data)
                newer["records"][0]["revision"] = 2
                newer["records"][0]["payload"]["name"] = "Superseding revision"
                result = await client.post(
                    endpoint, json=newer, headers={**headers, "Idempotency-Key": "master-2"}
                )
                assert result.status_code == 201
                listing = await client.get(endpoint + "/companies")
                assert listing.status_code == 200, listing.text
                assert len(listing.json()["records"]) == 1
                assert listing.json()["records"][0]["payload"]["name"] == "Superseding revision"
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(Membership)
                        .where(
                            Membership.person_id == setup.state.person_id,
                            Membership.tenant_id == setup.organisation.tenant_id,
                        )
                        .values(role="member")
                    )
                denied = await client.get(endpoint + "/companies")
                assert denied.status_code == 403
            async with setup.sessions() as db:
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(ConversationSyntheticRecord)
                        .where(
                            ConversationSyntheticRecord.tenant_id == setup.organisation.tenant_id
                        )
                    )
                    == 2
                )
            with pytest.raises(DBAPIError):
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(ConversationSyntheticRecord).values(payload={"rewritten": True})
                    )
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_retained_synthetic_audio_is_source_bound_replayable_and_never_creates_a_charge(
    postgres_harness, tmp_path
):
    async def exercise():
        setup = await setup_import(postgres_harness, tmp_path)
        setup.app.add_middleware(
            RequestBodyLimitMiddleware, acquisition_upload_max_bytes=32 * 1024 * 1024
        )
        media_path = tmp_path / "fictional-tone.mp3"
        await asyncio.to_thread(
            subprocess.run,
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=1",
                "-ar",
                "44100",
                "-ac",
                "1",
                "-b:a",
                "48k",
                str(media_path),
            ],
            check=True,
            capture_output=True,
            timeout=15,
        )
        payload = media_path.read_bytes()
        data, body = media_bundle(payload)
        endpoint = PREFIX + "/imports/sandbox/calls"
        call_path = endpoint + "/" + data["metadata"]["call_id"]
        headers = {
            "Origin": ORIGIN,
            "Idempotency-Key": "fixture-call-with-audio",
            "X-AC-Sandbox-Tenant": str(setup.organisation.tenant_id),
        }
        try:
            await flag(setup)
            async with await client_for(setup) as client:
                result = await client.post(endpoint, json=data, headers=headers)
                assert result.status_code == 201, result.text
                pending = await client.get(call_path)
                assert pending.json()["audio"] == {"state": "awaiting_upload", "playable": False}
                assert pending.json()["transcript"]["lines"][0]["playable"] is False
                wrong = deepcopy(body)
                wrong["call_bundle_sha256"] = "c" * 64
                refused = await client.post(
                    call_path + "/audio",
                    json=wrong,
                    headers={**headers, "Idempotency-Key": "wrong-authored-call"},
                )
                assert refused.status_code == 409
                manifests = await asyncio.gather(
                    *[
                        client.post(
                            call_path + "/audio",
                            json=body,
                            headers={**headers, "Idempotency-Key": f"media-manifest-{n}"},
                        )
                        for n in range(2)
                    ]
                )
                assert all(r.status_code == 201 for r in manifests), [r.text for r in manifests]
                assert sum(r.json()["created"] for r in manifests) == 1
                absent = await client.get(call_path + "/source")
                assert absent.status_code == 404
                # Reproduce a process loss between private file publication and DB commit.
                manifest = SyntheticAudioManifest.model_validate(body)
                retain_audio(
                    setup.runtime.storage,
                    media_key(setup.organisation.tenant_id, manifest),
                    manifest,
                    [payload[: 1024 * 1024], payload[1024 * 1024 :]],
                )

                async def chunks():
                    for offset in range(0, len(payload), 65536):
                        yield payload[offset : offset + 65536]

                upload_headers = {
                    "Origin": ORIGIN,
                    "Idempotency-Key": "media-bytes",
                    "X-AC-Sandbox-Tenant": str(setup.organisation.tenant_id),
                    "Content-Type": "audio/mpeg",
                    "Content-Length": str(len(payload)),
                }
                delivered = await client.put(
                    call_path + "/source", content=chunks(), headers=upload_headers
                )
                assert delivered.status_code == 201, delivered.text
                assert delivered.json()["created"] is True
            # A new client/application transaction represents restart/replay.
            async with await client_for(setup) as client:
                replay = await client.put(
                    call_path + "/source", content=chunks(), headers=upload_headers
                )
                assert replay.status_code == 201 and replay.json()["created"] is False, replay.text
                ready = await client.get(call_path)
                assert ready.json()["audio"]["state"] == "ready"
                assert ready.json()["transcript"]["lines"][0]["playable"] is True
                partial = await client.get(call_path + "/source", headers={"Range": "bytes=2-19"})
                assert partial.status_code == 206 and partial.content == payload[2:20]
                assert partial.headers["cache-control"] == "private, no-store"
                assert partial.headers["content-type"] == "audio/mpeg"
                invalid = await client.get(
                    call_path + "/source", headers={"Range": "bytes=0-1,2-3"}
                )
                assert invalid.status_code == 416
            async with setup.sessions() as db, db.begin():
                await db.execute(
                    update(Membership)
                    .where(
                        Membership.tenant_id == setup.organisation.tenant_id,
                        Membership.person_id == setup.state.person_id,
                    )
                    .values(role="member")
                )
            async with await client_for(setup) as client:
                denied = await client.get(call_path + "/source")
                assert denied.status_code == 403
            async with setup.sessions() as db:
                rows = (
                    await db.scalars(
                        select(ConversationSyntheticRecord).where(
                            ConversationSyntheticRecord.tenant_id == setup.organisation.tenant_id
                        )
                    )
                ).all()
                assert sorted(row.kind for row in rows) == ["audio", "audio_manifest", "call"]
                assert next(row for row in rows if row.kind == "call").payload == data
                for model in (
                    ConversationAcquisitionUsage,
                    ConversationRun,
                    ConversationInferenceTask,
                    Job,
                ):
                    assert await db.scalar(select(func.count()).select_from(model)) == 0
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_simultaneous_cookie_imports_across_fresh_sessions_create_one_authored_call(
    postgres_harness, tmp_path
):
    async def exercise():
        setup = await setup_import(postgres_harness, tmp_path)
        try:
            await flag(setup)
            async with await client_for(setup) as first, await client_for(setup) as second:
                data = bundle()
                responses = await asyncio.gather(
                    *[
                        client.post(
                            PREFIX + "/imports/sandbox/calls",
                            json=data,
                            headers={"Origin": ORIGIN, "Idempotency-Key": "racing-call"},
                        )
                        for client in (first, second)
                    ]
                )
                assert [response.status_code for response in responses] == [201, 201]
                assert sorted(response.json()["created"] for response in responses) == [False, True]
            async with setup.sessions() as db:
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(ConversationSyntheticRecord)
                        .where(
                            ConversationSyntheticRecord.tenant_id == setup.organisation.tenant_id
                        )
                    )
                    == 1
                )
                assert (
                    await db.scalar(select(func.count()).select_from(ConversationAcquisitionUsage))
                    == 0
                )
                assert await db.scalar(select(func.count()).select_from(Job)) == 0
        finally:
            await setup.engine.dispose()

    run(exercise())
