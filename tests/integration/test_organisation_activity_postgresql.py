"""Fictional PostgreSQL proof of organisation activity scope and privacy fences."""

import asyncio
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from hmac import digest
from typing import Any, cast
from uuid import uuid4

import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.application.settings import Settings
from ac_platform.http.auth import install_identity_http
from ac_platform.http.organisation import install_organisation_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.organisations.service import OrganisationService
from ac_platform.tenancy.models import Membership, Tenant
from tests.integration.test_media_delivery_renewal_postgresql import postgres_harness  # noqa: F401
from tests.unit.http.test_organisation_activity import seed_call
from tests.unit.organisations.test_service import seed_paid_seats


def test_activity_scope_on_postgresql(postgres_harness):  # noqa: F811
    async def exercise():
        engine = create_async_engine(postgres_harness.schema_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        personal = uuid4()
        settings = Settings(
            _env_file=None,
            environment="test",
            public_learner_tenant_id=personal,
            operations_tenant_id=uuid4(),
        )
        owner, first, second = (uuid4() for _ in range(3))
        tokens = {owner: "o" * 43, first: "f" * 43}
        now = datetime.now(UTC)
        try:
            async with sessions() as db, db.begin():
                db.add(Tenant(id=personal, slug=f"personal-{personal}", name="Personal"))
                db.add_all(
                    [
                        Person(
                            id=owner, email=f"owner-{owner}@example.test", email_verified_at=now
                        ),
                        Person(
                            id=first,
                            email=f"first-{first}@example.test",
                            display_name="Fictional First",
                            email_verified_at=now,
                        ),
                        Person(
                            id=second, email=f"second-{second}@example.test", email_verified_at=now
                        ),
                    ]
                )
                await db.flush()
                service = OrganisationService(
                    db,
                    operations_tenant_id=settings.operations_tenant_id,
                    public_learner_tenant_id=settings.public_learner_tenant_id,
                )
                org = await service.create(
                    "Fictional Activity Team", owner, uuid4(), "AUT-449 fixture"
                )
                await seed_paid_seats(db, org.tenant_id, owner)
                for person in (first, second):
                    await service.add_member(org.tenant_id, person, "member", uuid4())
                db.add(Membership(tenant_id=personal, person_id=first, role="learner"))
                await db.flush()
                for person, token in tokens.items():
                    db.add(
                        IdentitySession(
                            id=uuid4(),
                            person_id=person,
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

                def seed(sync):
                    return dict(
                        first=seed_call(
                            sync,
                            org.tenant_id,
                            first,
                            created_at=now - timedelta(hours=2),
                            report=True,
                            label="Fictional pricing call",
                        ),
                        second=seed_call(
                            sync,
                            org.tenant_id,
                            second,
                            created_at=now - timedelta(hours=1),
                            plan_state="held",
                        ),
                        deleted=seed_call(
                            sync,
                            org.tenant_id,
                            first,
                            created_at=now,
                            recording_state="deleted",
                        ),
                        personal=seed_call(sync, personal, first, created_at=now),
                    )

                ids = await db.run_sync(seed)
            app = FastAPI()
            register_problem_handlers(app)
            actor = install_identity_http(app, settings=settings, sessions=cast(Any, sessions))
            install_organisation_http(app, settings=settings, require_actor=actor)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="https://learner.authorityclosers.test",
            ) as client:

                async def activity(person, query=""):
                    return await client.get(
                        "/v1/organisation/activity" + query,
                        headers={"cookie": f"ac_session={tokens[person]}"},
                    )

                response = await activity(owner)
                assert response.status_code == 200, response.json()
                body = response.json()
                assert [(row["id"], row["owner_person_id"]) for row in body["calls"]] == [
                    (str(ids["second"]), str(second)),
                    (str(ids["first"]), str(first)),
                ]
                held, reported = body["calls"]
                assert (held["state"], held["has_report"]) == ("held", False)
                assert held["owner_name"] == "s***@example.test"
                assert reported["owner_name"] == "Fictional First"
                assert reported["label"] == "Fictional pricing call"
                assert (reported["state"], reported["duration_seconds"]) == ("report_ready", 90)
                assert datetime.fromisoformat(reported["created_at"]) == now - timedelta(hours=2)
                members = {row["person_id"]: row for row in body["members"]}
                assert set(members) == {str(owner), str(first), str(second)}
                assert members[str(owner)]["calls"] == 0
                assert members[str(first)]["reports_ready"] == 1
                assert members[str(second)]["minutes"] == 1.5

                own = (await activity(first)).json()
                assert [row["person_id"] for row in own["members"]] == [str(first)]
                assert [row["id"] for row in own["calls"]] == [str(ids["first"])]

                for days in (0, 91):
                    assert (await activity(owner, f"?days={days}")).status_code == 422
        finally:
            await engine.dispose()

    asyncio.run(exercise())
