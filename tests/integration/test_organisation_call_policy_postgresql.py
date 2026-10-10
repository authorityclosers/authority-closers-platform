"""Real cookie/HTTP/PostgreSQL proof of the default organisation call read policy."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from hmac import digest
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import event, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationVisitor,
    ConversationVisitorClaim,
)
from ac_platform.conversation_intelligence.acquisition_reports import AcquisitionReports
from ac_platform.conversation_intelligence.acquisition_sessions import AcquisitionSessions
from ac_platform.conversation_intelligence.application import ConversationNotFound
from ac_platform.conversation_intelligence.canary_models import ConversationCanarySubmission
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.measurement_view import ConversationMeasurements
from ac_platform.conversation_intelligence.models import (
    ConversationPermission,
    ConversationRecording,
    ConversationReportDraft,
)
from ac_platform.conversation_intelligence.speaker_map_models import ConversationSpeakerMapRevision
from ac_platform.conversation_intelligence.storage import StorageError
from ac_platform.http.auth import install_identity_http
from ac_platform.http.conversation_submissions import install_submission_http
from ac_platform.http.organisation import install_organisation_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import Membership, Organisation, Tenant
from tests.integration.test_media_delivery_renewal_postgresql import postgres_harness  # noqa: F401
from tests.unit.conversation_intelligence.test_organisation_call_reads import seed_readable_call
from tests.unit.http.test_conversation_learner_acquisition import _runtime, _settings
from tests.unit.http.test_organisation_activity import seed_call

PREFIX = "/v1/conversation/acquisition/submissions"
READ_SUFFIXES = (
    "",
    "/report",
    "/report.docx",
    "/transcript",
    "/waveform",
    "/source",
    "/speaker-map",
)


def test_organisation_call_policy_on_postgresql(postgres_harness, tmp_path, monkeypatch):  # noqa: F811
    async def exercise():
        engine = create_async_engine(postgres_harness.schema_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        personal, org, other_org, operations = (uuid4() for _ in range(4))
        owner, admin, member, other_member = (uuid4() for _ in range(4))
        identities = {person: uuid4() for person in (owner, admin, member, other_member)}
        tokens = {
            person: character * 43 for person, character in zip(identities, "oamn", strict=True)
        }
        settings = _settings().model_copy(
            update={"public_learner_tenant_id": personal, "operations_tenant_id": operations}
        )
        runtime = _runtime(tmp_path)
        intake = replace(
            runtime.intake,
            policy=replace(
                runtime.intake.policy, tenant_ids=frozenset({personal, org, other_org, operations})
            ),
        )
        now = datetime.now(UTC)
        try:
            async with sessions() as db, db.begin():
                db.add_all(
                    [
                        Tenant(id=tenant, name=name, slug=str(tenant))
                        for tenant, name in (
                            (personal, "Personal"),
                            (org, "Fictional Team A"),
                            (other_org, "Fictional Team B"),
                            (operations, "Operations"),
                        )
                    ]
                )
                db.add_all(
                    [
                        Person(
                            id=person,
                            email=f"fictional-{person}@example.test",
                            display_name=(
                                "Fictional Rep" if person == member else "Fictional Manager"
                            ),
                            email_verified_at=now,
                        )
                        for person in identities
                    ]
                )
                await db.flush()
                db.add_all(
                    [
                        Organisation(
                            tenant_id=tenant,
                            creation_command_id=uuid4(),
                            domain_verification_token="f" * 43,
                        )
                        for tenant in (org, other_org)
                    ]
                )
                db.add_all(
                    [
                        Membership(tenant_id=org, person_id=person, role=role)
                        for person, role in (
                            (owner, "owner"),
                            (admin, "admin"),
                            (member, "member"),
                            (other_member, "member"),
                        )
                    ]
                )
                db.add_all(
                    [
                        Membership(tenant_id=tenant, person_id=person, role=role)
                        for tenant, person, role in (
                            (other_org, owner, "owner"),
                            (other_org, member, "member"),
                            (personal, member, "learner"),
                            (personal, owner, "owner"),
                            (operations, owner, "owner"),
                        )
                    ]
                )
                await db.flush()
                db.add_all(
                    [
                        IdentitySession(
                            id=identities[person],
                            person_id=person,
                            selected_tenant_id=org,
                            token_hash=digest(
                                settings.session_token_pepper.get_secret_value().encode(),
                                token.encode(),
                                sha256,
                            ),
                            created_at=now,
                            expires_at=now + timedelta(days=1),
                        )
                        for person, token in tokens.items()
                    ]
                )
                await db.flush()

                def seed(sync):
                    ids = dict(
                        reported=seed_readable_call(
                            sync, org, member, created_at=now - timedelta(hours=1)
                        ),
                        own_admin=seed_call(sync, org, admin, created_at=now - timedelta(hours=2)),
                        other=seed_call(
                            sync, org, other_member, created_at=now - timedelta(hours=3)
                        ),
                        personal=seed_readable_call(sync, personal, member, created_at=now),
                        cross_org=seed_readable_call(sync, other_org, member, created_at=now),
                    )
                    for index in range(22):
                        seed_call(
                            sync, org, member, created_at=now - timedelta(days=2, seconds=index)
                        )
                    for name in ("claimed", "unclaimed", "canary", "deleted", "revoked", "expired"):
                        visitor = None
                        if name in {"claimed", "unclaimed"}:
                            visitor = uuid4()
                            sync.add(
                                ConversationVisitor(
                                    id=visitor,
                                    tenant_id=org,
                                    token_hash=sha256(visitor.bytes).digest(),
                                    created_at=now,
                                    expires_at=now + timedelta(days=1),
                                )
                            )
                            sync.flush()
                            if name == "claimed":
                                sync.add(
                                    ConversationVisitorClaim(
                                        visitor_id=visitor,
                                        tenant_id=org,
                                        person_id=member,
                                        session_id=identities[member],
                                        created_at=now,
                                    )
                                )
                        seed = seed_readable_call if name == "claimed" else seed_call
                        options = (
                            {}
                            if name == "claimed"
                            else {"recording_state": "deleted" if name == "deleted" else "ready"}
                        )
                        submission = ids[name] = seed(
                            sync,
                            org,
                            member,
                            created_at=now - timedelta(days=366) if name == "expired" else now,
                            visitor_id=visitor,
                            **options,
                        )
                        if name == "canary":
                            sync.add(
                                ConversationCanarySubmission(
                                    tenant_id=org,
                                    submission_id=submission,
                                    environment="test",
                                    fixture_sha256="f" * 64,
                                    created_at=now,
                                )
                            )
                        elif name == "revoked":
                            link = sync.get(ConversationGuestSubmission, (org, submission))
                            recording = sync.get(ConversationRecording, link.recording_id)
                            permission = sync.get(ConversationPermission, recording.permission_id)
                            permission.revoked_at = now
                        sync.flush()
                    for name in ("reported", "claimed"):
                        draft = sync.scalar(
                            select(ConversationReportDraft)
                            .join(
                                ConversationGuestSubmission,
                                ConversationGuestSubmission.recording_id
                                == ConversationReportDraft.recording_id,
                            )
                            .where(
                                ConversationGuestSubmission.tenant_id == org,
                                ConversationGuestSubmission.submission_id == ids[name],
                            )
                        )
                        sync.add(
                            ConversationSpeakerMapRevision(
                                id=uuid4(),
                                tenant_id=org,
                                submission_id=ids[name],
                                revision=1,
                                transcript_revision=draft.transcript["normalized"]["revision"],
                                speakers=[
                                    {"speaker_id": "speaker_1", "role": "you", "display_name": None}
                                ],
                                actor_person_id=member,
                                created_at=now,
                            )
                        )
                    sync.flush()
                    return ids

                ids = await db.run_sync(seed)
                retained = {
                    recording.id: recording
                    for recording in (
                        await db.scalars(
                            select(ConversationRecording)
                            .join(
                                ConversationGuestSubmission,
                                ConversationGuestSubmission.recording_id
                                == ConversationRecording.id,
                            )
                            .where(
                                ConversationGuestSubmission.tenant_id == org,
                                ConversationGuestSubmission.submission_id.in_(
                                    (ids["reported"], ids["claimed"])
                                ),
                            )
                        )
                    ).all()
                }

            # Media transports are fictional; cookie admission and all live
            # ownership/claim/role/retention queries run on real PostgreSQL.
            audio = b"f" * 1024

            def stream(key, *, expected_sha256):
                if key.recording_id not in retained:
                    raise StorageError("fictional_source_unavailable")
                recording = retained[key.recording_id]
                assert key.tenant_id == recording.tenant_id
                assert expected_sha256 == recording.source_sha256
                return iter((audio,))

            monkeypatch.setattr(intake.storage, "iter_bytes", stream, raising=False)
            original_waveform = ConversationMeasurements.waveform_from_recording

            async def retained_waveform(self, recording):
                if recording.id not in retained:
                    return await original_waveform(self, recording)
                assert recording.tenant_id == org
                assert recording.person_id == retained[recording.id].person_id
                return {
                    "schema": "ac.sales-xray.waveform/1",
                    "kind": "rms_envelope",
                    "duration_ms": 90_000,
                    "points": [{"start_ms": 0.0, "level": None}],
                }

            monkeypatch.setattr(
                ConversationMeasurements, "waveform_from_recording", retained_waveform
            )

            def factory(database, tenant_id):
                return AcquisitionSessions(
                    database,
                    tenant_id=tenant_id,
                    policy_revision="fictional",
                    operations_tenant_id=operations,
                    trial_enabled=tenant_id == personal,
                )

            app = FastAPI()
            register_problem_handlers(app)
            require_actor = install_identity_http(
                app, settings=settings, sessions=cast(Any, sessions)
            )
            install_organisation_http(app, settings=settings, require_actor=require_actor)
            install_submission_http(
                app,
                settings=settings,
                sessions=cast(Any, sessions),
                require_actor=require_actor,
                factory=factory,
                runtime=intake,
                preflight=runtime.preflight,
            )
            writes = []
            reads = []
            read_counts = {}

            @event.listens_for(engine.sync_engine, "before_cursor_execute")
            def capture(_connection, _cursor, statement, _parameters, _context, _many):
                if statement.split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
                    writes.append(statement)
                elif statement.split()[0].upper() == "SELECT":
                    reads.append(statement)

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://salesxray.example.test"
            ) as client:

                async def request(person, method="GET", path=PREFIX, **kwargs):
                    return await client.request(
                        method,
                        path,
                        headers={
                            "cookie": f"ac_session={tokens[person]}",
                            "origin": "https://salesxray.example.test",
                            **kwargs.pop("headers", {}),
                        },
                        **kwargs,
                    )

                for person in (owner, admin):
                    page = await request(person)
                    assert page.status_code == 200, page.json()
                    assert page.headers["cache-control"] == "private, no-store"
                    assert page.headers["vary"] == "Cookie"
                    assert len(page.json()["submissions"]) == 20
                    assert all(
                        set(row)
                        == {
                            "submission_id",
                            "created_at",
                            "duration_seconds",
                            "display_name",
                            "display_name_revision",
                            "state",
                            "has_report",
                        }
                        for row in page.json()["submissions"]
                    )
                    rows = []
                    cursor = None
                    while True:
                        query = "?include_owners=true" + ("&before=" + cursor if cursor else "")
                        response = await request(person, path=PREFIX + query)
                        assert response.status_code == 200, response.json()
                        page = response.json()
                        rows.extend(page["submissions"])
                        cursor = page["next_cursor"]
                        if cursor is None:
                            break
                    activity = (
                        await request(person, path="/v1/organisation/activity?days=30")
                    ).json()
                    assert [row["submission_id"] for row in rows] == [
                        row["id"] for row in activity["calls"]
                    ]
                    assert len(rows) == len({row["submission_id"] for row in rows}) == 26
                    counts = (await request(person, path=PREFIX + "/summary")).json()
                    assert counts == dict(total=26, completed=2, processing=0, needs_attention=0)
                    assert sum(row["calls"] for row in activity["per_day"]) == counts["total"]
                    for row, call in zip(rows, activity["calls"], strict=True):
                        assert (row["owner_person_id"], row["owner_name"], row["has_report"]) == (
                            call["owner_person_id"],
                            call["owner_name"],
                            call["has_report"],
                        )
                    reported = next(
                        row for row in rows if row["submission_id"] == str(ids["reported"])
                    )
                    assert (reported["owner_person_id"], reported["owner_name"]) == (
                        str(member),
                        "Fictional Rep",
                    )
                    for suffix in ("", "/report"):
                        response = await request(
                            person, path=PREFIX + f"/{ids['reported']}" + suffix
                        )
                        assert response.status_code == 200, response.json()
                        assert response.json()["submission_id"] == str(ids["reported"])
                        assert response.json()["display_name"] == "Fictional call"
                    for name in (
                        "personal",
                        "cross_org",
                        "unclaimed",
                        "canary",
                        "deleted",
                        "revoked",
                        "expired",
                    ):
                        for suffix in READ_SUFFIXES:
                            denied = await request(person, path=PREFIX + f"/{ids[name]}" + suffix)
                            assert denied.status_code == 404, (name, suffix, denied.json())
                            detail = (
                                "This saved call is unavailable."
                                if suffix == "/speaker-map"
                                else "This upload is unavailable."
                            )
                            assert denied.json() == {"detail": detail}
                            assert denied.headers["cache-control"] == "private, no-store"
                            assert denied.headers["vary"] == "Cookie"
                    assert (
                        await request(person, path=PREFIX + f"?before={ids['personal']}")
                    ).status_code == 404
                    for name in ("reported", "claimed"):
                        for suffix in READ_SUFFIXES[2:]:
                            start_reads = len(reads)
                            response = await request(person, path=PREFIX + f"/{ids[name]}" + suffix)
                            assert response.status_code == 200, (name, suffix, response.text)
                            assert response.headers["cache-control"] == "private, no-store"
                            assert response.headers["vary"] == "Cookie"
                            read_counts[person, name, suffix] = len(reads) - start_reads
                            # Speaker reads retain two ownership checks plus
                            # transcript/report attribution. A visitor claim
                            # adds one lookup to each ownership check.
                            budget = 66 if suffix == "/speaker-map" else 60
                            assert read_counts[person, name, suffix] <= budget, (
                                name,
                                suffix,
                                read_counts[person, name, suffix],
                            )
                            if suffix == "/speaker-map":
                                assert response.headers["etag"] == '"call-label-1"'
                                assert response.json()["status"] == "confirmed"
                                assert (
                                    response.json()["speakers"][0]["display_name"]
                                    == "Fictional Rep"
                                )
                                assert response.json()["speakers"][0]["role"] == "you"
                            elif suffix == "/transcript":
                                assert response.json()["segments"][0]["text"] == "Hello buyer"
                            elif suffix == "/waveform":
                                assert response.json()["points"] == [
                                    {"start_ms": 0.0, "level": None}
                                ]
                            elif suffix == "/source":
                                assert response.content == audio
                            else:
                                assert response.content.startswith(b"PK")
                        partial = await request(
                            person,
                            path=PREFIX + f"/{ids[name]}/source",
                            headers={"Range": "bytes=10-19"},
                        )
                        assert partial.status_code == 206 and partial.content == audio[10:20]
                        assert partial.headers["content-range"] == "bytes 10-19/1024"
                    unavailable = await request(
                        person, path=PREFIX + f"/{ids['other']}/speaker-map"
                    )
                    assert unavailable.status_code == 200
                    assert unavailable.json()["status"] == "unavailable"
                    assert unavailable.json()["speakers"] == []
                    for suffix, status in (
                        ("/transcript", 404),
                        ("/waveform", 409),
                        ("/source", 409),
                    ):
                        assert (
                            await request(person, path=PREFIX + f"/{ids['other']}" + suffix)
                        ).status_code == status

                own = (await request(member)).json()["submissions"]
                assert str(ids["reported"]) in {row["submission_id"] for row in own}
                assert str(ids["other"]) not in {row["submission_id"] for row in own}
                assert (
                    await request(member, path=PREFIX + f"/{ids['reported']}/report")
                ).status_code == 200
                own_map = await request(member, path=PREFIX + f"/{ids['reported']}/speaker-map")
                assert own_map.status_code == 200
                assert own_map.json()["speakers"][0]["display_name"] == "Fictional Rep"
                for person in (owner, admin):
                    assert (
                        await request(person, path=PREFIX + f"/{ids['reported']}/plan")
                    ).status_code == 404
                for suffix in READ_SUFFIXES:
                    assert (
                        await request(member, path=PREFIX + f"/{ids['other']}" + suffix)
                    ).status_code == 404
                assert (
                    await request(owner, path=PREFIX + "?include_owners=true&include_owners=false")
                ).status_code == 422
                assert (await client.get(PREFIX)).status_code == 401
                assert writes == []

                # Grow the library from 26 to 48 calls and prove that the
                # exact-call read cost does not grow with unrelated calls.
                async with sessions() as db, db.begin():

                    def grow_library(sync):
                        for index in range(22):
                            seed_call(
                                sync, org, member, created_at=now - timedelta(days=3, seconds=index)
                            )

                    await db.run_sync(grow_library)
                writes.clear()  # Only the explicit fixture writes above.
                for person in (owner, admin):
                    for name in ("reported", "claimed"):
                        for suffix in READ_SUFFIXES[2:]:
                            start_reads = len(reads)
                            response = await request(person, path=PREFIX + f"/{ids[name]}" + suffix)
                            assert response.status_code == 200
                            assert len(reads) - start_reads == read_counts[person, name, suffix]
                assert writes == []
                original_progress = AcquisitionReports.progress
                attempts = 0

                class Deadlock(Exception):
                    sqlstate = "40P01"

                async def retry_progress(self, *args, **kwargs):
                    nonlocal attempts
                    attempts += 1
                    if attempts == 1:
                        raise DBAPIError("select", {}, Deadlock(), False)
                    return await original_progress(self, *args, **kwargs)

                with monkeypatch.context() as patch:
                    patch.setattr(AcquisitionReports, "progress", retry_progress)
                    retried = await request(owner, path=PREFIX + f"/{ids['reported']}")
                    assert retried.status_code == 200, retried.json()
                    assert retried.json()["display_name"] == "Fictional call"
                    assert attempts == 2
                for method, suffix, kwargs in (
                    (
                        "PATCH",
                        "/label",
                        dict(
                            json={"display_name": "Cannot rename"},
                            headers={"If-Match": '"call-label-1"'},
                        ),
                    ),
                    ("DELETE", "", dict(headers={"Idempotency-Key": "fictional-denied-delete"})),
                    (
                        "PUT",
                        "/speaker-map",
                        dict(
                            headers={"If-Match": '"call-label-1"'},
                            json={
                                "transcript_revision": "fictional",
                                "speakers": [{"speaker_id": "speaker_1", "role": "you"}],
                            },
                        ),
                    ),
                ):
                    for person in (owner, admin):
                        denied = await request(
                            person, method, PREFIX + f"/{ids['reported']}" + suffix, **kwargs
                        )
                        assert denied.status_code == 404, denied.json()
                async with sessions() as db, db.begin():
                    ownership = GuestOwnership(factory(db, org))
                    with pytest.raises(ConversationNotFound):
                        await ownership.resolve_processing_actor(
                            ids["reported"], actor=ActorContext(owner, identities[owner], org)
                        )
                # Mutating routes keep their existing identity last-seen update;
                # denied commands still write no call, report, grant or audit rows.
                assert all(statement.startswith("UPDATE sessions ") for statement in writes)

                async with sessions() as db, db.begin():
                    (await db.get(Membership, (org, admin))).role = "member"
                for suffix in READ_SUFFIXES:
                    assert (
                        await request(admin, path=PREFIX + f"/{ids['reported']}" + suffix)
                    ).status_code == 404
                assert [
                    row["submission_id"] for row in (await request(admin)).json()["submissions"]
                ] == [str(ids["own_admin"])]
                assert (await request(admin, path=PREFIX + "/summary")).json()["total"] == 1
                async with sessions() as db, db.begin():
                    membership = await db.get(Membership, (org, admin))
                    membership.status, membership.ended_at = "inactive", now
                assert (await request(admin)).status_code in {401, 403}
                for suffix in READ_SUFFIXES:
                    assert (
                        await request(admin, path=PREFIX + f"/{ids['reported']}" + suffix)
                    ).status_code in {401, 403}

                async with sessions() as db, db.begin():
                    (await db.get(IdentitySession, identities[owner])).selected_tenant_id = personal
                assert (await request(owner)).json()["submissions"] == []
                for suffix in READ_SUFFIXES:
                    assert (
                        await request(owner, path=PREFIX + f"/{ids['personal']}" + suffix)
                    ).status_code == 404
                async with sessions() as db, db.begin():
                    (
                        await db.get(IdentitySession, identities[member])
                    ).selected_tenant_id = personal
                assert [
                    row["submission_id"] for row in (await request(member)).json()["submissions"]
                ] == [str(ids["personal"])]
                assert (
                    await request(member, path=PREFIX + f"/{ids['personal']}/report")
                ).status_code == 200
                async with sessions() as db, db.begin():
                    (
                        await db.get(IdentitySession, identities[owner])
                    ).selected_tenant_id = operations
                assert (await request(owner)).status_code == 403
                for suffix in READ_SUFFIXES:
                    denied = await request(owner, path=PREFIX + f"/{ids['reported']}" + suffix)
                    assert denied.status_code == (404 if suffix == "/speaker-map" else 403)
        finally:
            await engine.dispose()

    asyncio.run(exercise())
