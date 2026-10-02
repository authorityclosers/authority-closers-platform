"""Fictional PostgreSQL HTTP proof of concurrent additions and the daily budget."""

import asyncio
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from hmac import digest
from typing import Any, cast
from uuid import uuid4

import httpx
from fastapi import FastAPI
from sqlalchemy import func, select
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
from ac_platform.tenancy.models import Membership, OrganisationInvite
from tests.integration.test_media_delivery_renewal_postgresql import postgres_harness  # noqa: F401


def test_concurrent_http_budget_and_verified_add(postgres_harness):  # noqa: F811
    async def exercise():
        engine = create_async_engine(postgres_harness.schema_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        settings = Settings(
            _env_file=None,
            environment="test",
            public_learner_tenant_id=uuid4(),
            operations_tenant_id=uuid4(),
        )
        owner, admin, target, identity = (uuid4() for _ in range(4))
        token = "o" * 43
        admin_token = "a" * 43
        now = datetime.now(UTC)
        try:
            async with sessions() as db, db.begin():
                db.add_all(
                    [
                        Person(
                            id=owner, email=f"owner-{owner}@example.test", email_verified_at=now
                        ),
                        Person(
                            id=admin, email=f"admin-{admin}@example.test", email_verified_at=now
                        ),
                        Person(
                            id=target, email=f"rep-{target}@example.test", email_verified_at=now
                        ),
                    ]
                )
                await db.flush()
                service = OrganisationService(
                    db,
                    operations_tenant_id=settings.operations_tenant_id,
                    public_learner_tenant_id=settings.public_learner_tenant_id,
                )
                org = await service.create("Fictional HTTP Team", owner, uuid4(), "AUT-439 fixture")
                db.add(
                    IdentitySession(
                        id=identity,
                        person_id=owner,
                        selected_tenant_id=org.tenant_id,
                        token_hash=digest(
                            settings.session_token_pepper.get_secret_value().encode(),
                            token.encode(),
                            sha256,
                        ),
                        created_at=now,
                        expires_at=now + timedelta(days=1),
                    )
                )
                db.add(Membership(tenant_id=org.tenant_id, person_id=admin, role="admin"))
                await db.flush()
                db.add(
                    IdentitySession(
                        id=uuid4(),
                        person_id=admin,
                        selected_tenant_id=org.tenant_id,
                        token_hash=digest(
                            settings.session_token_pepper.get_secret_value().encode(),
                            admin_token.encode(),
                            sha256,
                        ),
                        created_at=now,
                        expires_at=now + timedelta(days=1),
                    )
                )
            app = FastAPI()
            register_problem_handlers(app)
            actor = install_identity_http(app, settings=settings, sessions=cast(Any, sessions))
            install_organisation_http(app, settings=settings, require_actor=actor)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="https://learner.authorityclosers.test",
            ) as client:

                async def add(email, key, actor_token=token):
                    return await client.post(
                        "/v1/organisation/members",
                        json={"email": email, "role": "member"},
                        headers={
                            "cookie": f"ac_session={actor_token}",
                            "Idempotency-Key": str(key),
                        },
                    )

                key = uuid4()
                pair = await asyncio.wait_for(
                    asyncio.gather(
                        add(f"rep-{target}@example.test", key),
                        add(f"rep-{target}@example.test", key),
                    ),
                    timeout=15,
                )
                assert [r.status_code for r in pair] == [200, 200]
                assert pair[0].json() == pair[1].json()
                # A request holding the target's shared identity fence must
                # produce a retryable conflict, rather than a lock cycle.
                with Session(postgres_harness.engine) as held, held.begin():
                    held.scalar(
                        select(Membership)
                        .where(
                            Membership.tenant_id == org.tenant_id, Membership.person_id == target
                        )
                        .with_for_update(read=True)
                    )
                    busy = await asyncio.wait_for(
                        add(f"rep-{target}@example.test", uuid4()), timeout=5
                    )
                    assert busy.status_code == 409
                async with sessions() as db, db.begin():
                    db.add_all(
                        [
                            OrganisationInvite(
                                tenant_id=org.tenant_id,
                                email_normalized=f"seed-{i}@example.test",
                                role="member",
                                command_id=uuid4(),
                            )
                            for i in range(48)
                        ]
                    )
                competing = await asyncio.wait_for(
                    asyncio.gather(
                        add("last-a@example.test", uuid4()),
                        add("last-b@example.test", uuid4(), admin_token),
                    ),
                    timeout=15,
                )
                assert sorted(r.status_code for r in competing) == [200, 429]
            with Session(postgres_harness.engine) as db:
                assert (
                    db.scalar(
                        select(func.count())
                        .select_from(OrganisationInvite)
                        .where(OrganisationInvite.tenant_id == org.tenant_id)
                    )
                    == 50
                )
                assert (
                    db.scalar(
                        select(func.count())
                        .select_from(AuditEvent)
                        .where(AuditEvent.tenant_id == org.tenant_id)
                    )
                    == 3
                )
                assert verify_audit_chain_sync(db, org.tenant_id).valid
        finally:
            await engine.dispose()

    asyncio.run(exercise())
