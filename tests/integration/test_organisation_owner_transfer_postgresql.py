"""Fictional PostgreSQL HTTP proof of atomic ownership transfer under concurrency."""

import asyncio
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from hmac import digest
from typing import Any, cast
from uuid import uuid4

import httpx
from fastapi import FastAPI
from sqlalchemy import select
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
from ac_platform.tenancy.models import Membership
from tests.integration.test_media_delivery_renewal_postgresql import postgres_harness  # noqa: F401


def test_transfer_is_atomic_under_concurrency_and_shared_fences(postgres_harness):  # noqa: F811
    async def exercise():
        engine = create_async_engine(postgres_harness.schema_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        settings = Settings(
            _env_file=None,
            environment="test",
            public_learner_tenant_id=uuid4(),
            operations_tenant_id=uuid4(),
        )
        owner, admin, rep = (uuid4() for _ in range(3))
        tokens = {owner: "o" * 43, admin: "a" * 43, rep: "r" * 43}
        now = datetime.now(UTC)
        try:
            async with sessions() as db, db.begin():
                db.add_all(
                    [
                        Person(
                            id=person,
                            email=f"{label}-{person}@example.test",
                            email_verified_at=now,
                        )
                        for label, person in (("owner", owner), ("admin", admin), ("rep", rep))
                    ]
                )
                await db.flush()
                service = OrganisationService(
                    db,
                    operations_tenant_id=settings.operations_tenant_id,
                    public_learner_tenant_id=settings.public_learner_tenant_id,
                )
                org = await service.create(
                    "Fictional Transfer Team", owner, uuid4(), "AUT-786 fixture"
                )
                db.add_all(
                    [
                        Membership(tenant_id=org.tenant_id, person_id=admin, role="admin"),
                        Membership(tenant_id=org.tenant_id, person_id=rep, role="member"),
                    ]
                )
                await db.flush()
                db.add_all(
                    [
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
                        for person, token in tokens.items()
                    ]
                )
            app = FastAPI()
            register_problem_handlers(app)
            actor = install_identity_http(app, settings=settings, sessions=cast(Any, sessions))
            install_organisation_http(app, settings=settings, require_actor=actor)

            def memberships():
                with Session(postgres_harness.engine) as db:
                    return {
                        row.person_id: row
                        for row in db.scalars(
                            select(Membership).where(Membership.tenant_id == org.tenant_id)
                        )
                    }

            def owners():
                return [
                    person
                    for person, row in memberships().items()
                    if row.role == "owner" and row.status == "active"
                ]

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="https://learner.authorityclosers.test",
            ) as client:

                async def send(method, path, actor_id, key, body=None):
                    return await client.request(
                        method,
                        "/v1/organisation" + path,
                        json=body,
                        headers={
                            "cookie": f"ac_session={tokens[actor_id]}",
                            "Idempotency-Key": str(key),
                        },
                    )

                def transfer(actor_id, target, key):
                    return send("POST", "/owner", actor_id, key, {"person_id": str(target)})

                original = memberships()[owner].created_at
                # A request holding the target's shared authentication fence
                # yields a retryable conflict, never a lock cycle or a partial swap.
                fenced_key = uuid4()
                with Session(postgres_harness.engine) as held, held.begin():
                    held.scalar(
                        select(Membership)
                        .where(Membership.tenant_id == org.tenant_id, Membership.person_id == admin)
                        .with_for_update(read=True)
                    )
                    busy = await asyncio.wait_for(transfer(owner, admin, fenced_key), timeout=5)
                    assert busy.status_code == 409
                    assert "retry" in busy.json()["detail"]
                assert owners() == [owner]

                # Two fresh transfers by the same owner to different targets:
                # each request holds the owner's shared fence, so only one swaps.
                racing = await asyncio.wait_for(
                    asyncio.gather(
                        transfer(owner, admin, fenced_key), transfer(owner, rep, uuid4())
                    ),
                    timeout=15,
                )
                assert sorted(r.status_code for r in racing)[0] == 200
                assert sorted(r.status_code for r in racing)[1] in {403, 409}
                winner = next(r for r in racing if r.status_code == 200).json()
                new_owner = admin if winner["owner"]["person_id"] == str(admin) else rep
                assert owners() == [new_owner]
                assert winner["former_owner"]["person_id"] == str(owner)
                assert winner["former_owner"]["role"] == "admin"
                rows = memberships()
                assert rows[owner].role == "admin" and rows[owner].created_at == original
                assert rows[owner].revision == 1 and rows[new_owner].revision == 1

                # Stale authority: the former owner cannot transfer, change a
                # role or remove an admin with a fresh request.
                loser = rep if new_owner == admin else admin
                assert (await transfer(owner, loser, uuid4())).status_code == 403
                assert (
                    await send("PATCH", f"/members/{rep}", owner, uuid4(), {"role": "admin"})
                ).status_code == 403
                assert owners() == [new_owner]

                # Same-key concurrent replays have one effect and one result.
                back_key = uuid4()
                pair = await asyncio.wait_for(
                    asyncio.gather(
                        transfer(new_owner, owner, back_key), transfer(new_owner, owner, back_key)
                    ),
                    timeout=15,
                )
                assert {r.status_code for r in pair} <= {200, 409}
                settled = await transfer(new_owner, owner, back_key)
                assert settled.status_code == 200
                assert all(r.json() == settled.json() for r in pair if r.status_code == 200)
                assert owners() == [owner]

                # Opposite concurrent writes by two authenticated actors: the
                # owner hands over to the admin while the admin removes the rep.
                with Session(postgres_harness.engine) as db, db.begin():
                    for person, role in ((admin, "admin"), (rep, "member")):
                        db.get(Membership, (org.tenant_id, person)).role = role
                crossing = await asyncio.wait_for(
                    asyncio.gather(
                        transfer(owner, admin, uuid4()),
                        send("DELETE", f"/members/{rep}", admin, uuid4()),
                    ),
                    timeout=15,
                )
                assert all(r.status_code in {200, 204, 409} for r in crossing)
                assert len(owners()) == 1

                # Removal keeps the membership row, inactive with an end time.
                current = owners()[0]
                removed = await send("DELETE", f"/members/{rep}", current, uuid4())
                assert removed.status_code == (404 if crossing[1].status_code == 204 else 204)
                row = memberships()[rep]
                assert row.status == "inactive" and row.ended_at is not None
                listed = await client.get(
                    "/v1/organisation/members",
                    headers={"cookie": f"ac_session={tokens[current]}"},
                )
                assert str(rep) not in {m["person_id"] for m in listed.json()["members"]}
                assert (
                    await client.get(
                        "/v1/organisation", headers={"cookie": f"ac_session={tokens[rep]}"}
                    )
                ).status_code == 404

            with Session(postgres_harness.engine) as db:
                events = list(
                    db.scalars(
                        select(AuditEvent)
                        .where(AuditEvent.tenant_id == org.tenant_id)
                        .order_by(AuditEvent.sequence_no)
                    )
                )
                transfers = [e for e in events if e.action == "organisation.ownership_transferred"]
                removals = [e for e in events if e.action == "organisation.member_removed"]
                # One event per effect: two settled transfers, a possible third
                # from the crossing pair, and exactly one removal.
                assert len(transfers) == 2 + (crossing[0].status_code == 200)
                assert len(removals) == 1 and len(events) == 1 + len(transfers) + 1
                assert all(e.actor_person_id is not None for e in events[1:])
                assert verify_audit_chain_sync(db, org.tenant_id).valid
        finally:
            await engine.dispose()

    asyncio.run(exercise())
