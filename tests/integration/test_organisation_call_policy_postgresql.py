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
from sqlalchemy import event
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
from ac_platform.conversation_intelligence.models import (
    ConversationPermission,
    ConversationRecording,
)
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
                            display_name="Fictional Rep" if person == member else None,
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
                        submission = ids[name] = seed_call(
                            sync,
                            org,
                            member,
                            created_at=now - timedelta(days=366) if name == "expired" else now,
                            recording_state="deleted" if name == "deleted" else "ready",
                            visitor_id=visitor,
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
                    return ids

                ids = await db.run_sync(seed)

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

            @event.listens_for(engine.sync_engine, "before_cursor_execute")
            def capture(_connection, _cursor, statement, _parameters, _context, _many):
                if statement.split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
                    writes.append(statement)

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
                    assert counts == dict(total=26, completed=1, processing=0, needs_attention=0)
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
                        for suffix in ("", "/report"):
                            denied = await request(person, path=PREFIX + f"/{ids[name]}" + suffix)
                            assert denied.status_code == 404, (name, suffix, denied.json())
                            assert denied.json() == {"detail": "This upload is unavailable."}
                    assert (
                        await request(person, path=PREFIX + f"?before={ids['personal']}")
                    ).status_code == 404
                    for suffix in ("/report.docx", "/transcript", "/waveform", "/source"):
                        assert (
                            await request(person, path=PREFIX + f"/{ids['reported']}" + suffix)
                        ).status_code == 404

                own = (await request(member)).json()["submissions"]
                assert str(ids["reported"]) in {row["submission_id"] for row in own}
                assert str(ids["other"]) not in {row["submission_id"] for row in own}
                assert (
                    await request(member, path=PREFIX + f"/{ids['reported']}/report")
                ).status_code == 200
                for suffix in ("", "/report"):
                    assert (
                        await request(member, path=PREFIX + f"/{ids['other']}" + suffix)
                    ).status_code == 404
                assert (
                    await request(owner, path=PREFIX + "?include_owners=true&include_owners=false")
                ).status_code == 422
                assert (await client.get(PREFIX)).status_code == 401
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
                ):
                    denied = await request(
                        owner, method, PREFIX + f"/{ids['reported']}" + suffix, **kwargs
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
                for suffix in ("", "/report"):
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

                async with sessions() as db, db.begin():
                    (await db.get(IdentitySession, identities[owner])).selected_tenant_id = personal
                assert (await request(owner)).json()["submissions"] == []
                assert (
                    await request(owner, path=PREFIX + f"/{ids['personal']}/report")
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
        finally:
            await engine.dispose()

    asyncio.run(exercise())
