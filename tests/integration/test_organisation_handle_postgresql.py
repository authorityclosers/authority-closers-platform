"""Fictional PostgreSQL HTTP proof of handles, audit replay and lock contention."""

import asyncio
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from hmac import digest
from typing import Any, cast
from uuid import uuid4

import httpx
from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from ac_platform.application.settings import Settings
from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain_sync
from ac_platform.http.auth import install_identity_http
from ac_platform.http.organisation import install_organisation_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.organisations.service import OrganisationService
from ac_platform.tenancy.models import Membership, Organisation, Tenant
from tests.integration.test_media_delivery_renewal_postgresql import postgres_harness  # noqa: F401
from tests.unit.http.test_organisation_handle import INVALID_HANDLES, RESERVED_HANDLES


def test_handle_contract_and_concurrency(postgres_harness):  # noqa: F811
    async def exercise():
        engine = create_async_engine(postgres_harness.schema_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        public, operations = uuid4(), uuid4()
        settings = Settings(
            _env_file=None,
            environment="test",
            public_learner_tenant_id=public,
            operations_tenant_id=operations,
        )
        owner, admin, member, second_owner = (uuid4() for _ in range(4))
        tokens = {owner: "o" * 43, admin: "a" * 43, member: "m" * 43, second_owner: "s" * 43}
        session_ids = {person: uuid4() for person in tokens}
        now = datetime.now(UTC)
        try:
            async with sessions() as db, db.begin():
                db.add_all(
                    [
                        Person(
                            id=person, email=f"handle-{person}@example.test", email_verified_at=now
                        )
                        for person in tokens
                    ]
                )
                db.add_all(
                    [
                        Tenant(id=tenant, name=label, slug=label.lower())
                        for tenant, label in ((public, "Public"), (operations, "Operations"))
                    ]
                )
                await db.flush()
                service = OrganisationService(
                    db, operations_tenant_id=operations, public_learner_tenant_id=public
                )
                org = await service.create(
                    "Fictional Handle Team", owner, uuid4(), "AUT-1169 fixture"
                )
                other = await service.create(
                    "Fictional Other Team", second_owner, uuid4(), "AUT-1169 fixture"
                )
                db.add_all(
                    [
                        Membership(tenant_id=org.tenant_id, person_id=person, role=role)
                        for person, role in ((admin, "admin"), (member, "member"))
                    ]
                )
                # Even an owner of a registered protected tenant cannot rename it.
                db.add_all(
                    [
                        Organisation(
                            tenant_id=tenant,
                            creation_command_id=uuid4(),
                            domain_verification_token="f" * 43,
                        )
                        for tenant in (public, operations)
                    ]
                )
                db.add_all(
                    [
                        Membership(tenant_id=tenant, person_id=owner, role="owner")
                        for tenant in (public, operations)
                    ]
                )
                await db.flush()
                db.add_all(
                    [
                        IdentitySession(
                            id=session_ids[person],
                            person_id=person,
                            selected_tenant_id=other.tenant_id
                            if person == second_owner
                            else org.tenant_id,
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
            app = FastAPI()
            register_problem_handlers(app)
            actor = install_identity_http(app, settings=settings, sessions=cast(Any, sessions))
            install_organisation_http(app, settings=settings, require_actor=actor)

            def snapshot():
                with Session(postgres_harness.engine) as db:
                    assert verify_audit_chain_sync(db, org.tenant_id).valid
                    tenant = db.get(Tenant, org.tenant_id)
                    events = list(
                        db.scalars(
                            select(AuditEvent)
                            .where(
                                AuditEvent.tenant_id == org.tenant_id,
                                AuditEvent.action == "organisation.handle_changed",
                            )
                            .order_by(AuditEvent.sequence_no)
                        )
                    )
                    return tenant.slug, events

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="https://learner.authorityclosers.test",
            ) as client:

                async def send(method, path, person=owner, body=None, key=None):
                    headers = {} if person is None else {"cookie": f"ac_session={tokens[person]}"}
                    if key is not None:
                        headers["Idempotency-Key"] = str(key)
                    return await client.request(
                        method, "/v1/organisation" + path, json=body, headers=headers
                    )

                async def put(handle, key=None, person=owner):
                    return await send("PUT", "/handle", person, {"handle": handle}, key or uuid4())

                original = snapshot()[0]
                for person, role in ((owner, "owner"), (admin, "admin"), (member, "member")):
                    response = await send("GET", "/profile", person)
                    assert response.status_code == 200
                    assert response.json() == {
                        "tenant_id": str(org.tenant_id),
                        "handle": original,
                        "name": org.name,
                        "your_role": role,
                    }
                    assert response.headers["cache-control"] == "private, no-store"
                for person in (admin, member):
                    assert (await put("forbidden-team", person=person)).status_code == 403
                for handle in INVALID_HANDLES + RESERVED_HANDLES:
                    assert (await put(handle)).status_code == 422, handle
                assert snapshot() == (original, [])
                assert (
                    await send("PUT", "/handle", body={"handle": "valid-team"})
                ).status_code == 422
                assert (
                    await send("PUT", "/handle", body={"handle": "valid-team"}, key="bad")
                ).status_code == 422
                assert (
                    await send("PUT", "/handle", body={"handle": 123}, key=uuid4())
                ).status_code == 422
                assert (await send("GET", "/profile", person=None)).status_code == 401

                with Session(postgres_harness.engine) as db, db.begin():
                    db.get(Tenant, other.tenant_id).slug = "TAKEN-HANDLE"
                taken = await put("taken-handle")
                assert taken.status_code == 409 and taken.json()["detail"] == "Handle taken"
                assert snapshot() == (original, [])

                for selected in (None, public, operations):
                    with Session(postgres_harness.engine) as db, db.begin():
                        # A rejected request must release its session lock before returning.
                        db.execute(text("SET LOCAL lock_timeout = '2s'"))
                        db.get(IdentitySession, session_ids[owner]).selected_tenant_id = selected
                    for method, path in (("GET", "/profile"), ("PUT", "/handle")):
                        denied = await send(
                            method,
                            path,
                            body={"handle": "forbidden-team"} if method == "PUT" else None,
                            key=uuid4(),
                        )
                        assert (
                            denied.status_code == 404
                            and denied.json()["detail"] == "No organisation selected"
                        )
                with Session(postgres_harness.engine) as db, db.begin():
                    db.get(IdentitySession, session_ids[owner]).selected_tenant_id = org.tenant_id
                    assert db.get(Tenant, public).slug == "public"
                    assert db.get(Tenant, operations).slug == "operations"

                # Another authenticated request's shared fence never causes an upgrade cycle.
                key = uuid4()
                with Session(postgres_harness.engine) as held, held.begin():
                    held.scalar(
                        select(Tenant).where(Tenant.id == org.tenant_id).with_for_update(read=True)
                    )
                    busy = await asyncio.wait_for(put("fictional-renamed", key), timeout=5)
                    assert busy.status_code == 409 and "retry" in busy.json()["detail"]
                assert snapshot() == (original, [])
                changed = await put("fictional-renamed", key)
                assert changed.status_code == 200, changed.text
                assert (await send("GET", "/profile")).json() == changed.json()
                assert (await put("fictional-renamed", key)).json() == changed.json()
                assert (await put("different-intent", key)).status_code == 409
                slug, (audit,) = snapshot()
                assert slug == "fictional-renamed" and audit.actor_person_id == owner
                assert audit.payload["before"] == {"handle": original}
                assert audit.payload["after"] == {"handle": "fictional-renamed"}

                for handle in ("abc", "a-b", "a" * 40):
                    assert (await put(handle)).status_code == 200

                # Competing organisations cannot both claim one handle.
                race = await asyncio.wait_for(
                    asyncio.gather(put("shared-handle"), put("shared-handle", person=second_owner)),
                    timeout=15,
                )
                assert sorted(response.status_code for response in race) == [200, 409]
                assert (
                    next(response for response in race if response.status_code == 409).json()[
                        "detail"
                    ]
                    == "Handle taken"
                )
                with Session(postgres_harness.engine) as db:
                    assert (
                        len(list(db.scalars(select(Tenant).where(Tenant.slug == "shared-handle"))))
                        == 1
                    )
                    assert verify_audit_chain_sync(db, other.tenant_id).valid

                # Simultaneous same-key requests settle to one immutable result and audit.
                before = len(snapshot()[1])
                replay_key = uuid4()
                pair = await asyncio.wait_for(
                    asyncio.gather(
                        put("stable-handle", replay_key), put("stable-handle", replay_key)
                    ),
                    timeout=15,
                )
                assert {response.status_code for response in pair} <= {200, 409}
                settled = await put("stable-handle", replay_key)
                assert settled.status_code == 200
                assert (await put("stable-handle", replay_key)).json() == settled.json()
                assert len(snapshot()[1]) == before + 1
                with Session(postgres_harness.engine) as db, db.begin():
                    db.get(Membership, (org.tenant_id, owner)).role = "admin"
                assert (await put("stable-handle", replay_key)).status_code == 403
        finally:
            await engine.dispose()

    asyncio.run(exercise())
