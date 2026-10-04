"""Fictional PostgreSQL proof of member usage and directory response shapes."""

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
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionUsage as Usage,
)
from ac_platform.http.auth import install_identity_http
from ac_platform.http.organisation import install_organisation_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.organisations.service import OrganisationService
from ac_platform.tenancy.models import Membership
from tests.integration.test_media_delivery_renewal_postgresql import postgres_harness  # noqa: F401
from tests.unit.organisations.test_service import seed_paid_seats


def test_directory_reads_on_postgresql(postgres_harness):  # noqa: F811
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
                await seed_paid_seats(db, org.tenant_id, owner)
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
            async with sessions() as db, db.begin():
                service = OrganisationService(
                    db,
                    operations_tenant_id=settings.operations_tenant_id,
                    public_learner_tenant_id=settings.public_learner_tenant_id,
                )
                await service.add_member(org.tenant_id, target, "member", uuid4())
                db.add(
                    Usage(
                        id=uuid4(),
                        tenant_id=org.tenant_id,
                        person_id=target,
                        submission_id=uuid4(),
                        source_sha256="a" * 64,
                        duration_evidence_sha256="b" * 64,
                        reserved_seconds=90,
                        policy_revision="fictional",
                        created_at=now,
                    )
                )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="https://learner.authorityclosers.test",
            ) as client:
                profile = await client.get(
                    "/v1/organisation", headers={"cookie": f"ac_session={token}"}
                )
                assert profile.status_code == 200 and profile.json()["member_count"] == 3
                response = await client.get(
                    "/v1/organisation/members", headers={"cookie": f"ac_session={token}"}
                )
                assert response.status_code == 200
                rep = next(
                    row for row in response.json()["members"] if row["person_id"] == str(target)
                )
                assert rep["minutes_used_30d"] == 1.5 and rep["calls_30d"] == 1
                assert datetime.fromisoformat(rep["last_active_at"]) == now
            with Session(postgres_harness.engine) as db:
                assert (
                    db.scalar(
                        select(func.count())
                        .select_from(AuditEvent)
                        .where(AuditEvent.tenant_id == org.tenant_id)
                    )
                    == 2
                )
                assert verify_audit_chain_sync(db, org.tenant_id).valid
        finally:
            await engine.dispose()

    asyncio.run(exercise())
