"""Fictional PostgreSQL HTTP proof of operator member management on a real organisation."""

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
from ac_platform.authorization.application import CapabilityApplication
from ac_platform.authorization.policy import CapabilityScope
from ac_platform.http.auth import install_identity_http
from ac_platform.http.platform_organisations import install_platform_organisations_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.organisations.service import OrganisationService
from ac_platform.tenancy.models import Membership, Tenant
from tests.integration.test_media_delivery_renewal_postgresql import postgres_harness  # noqa: F401

ORIGIN = "https://admin.authorityclosers.test"
REASON = "AUT-446 fictional support request"
TOKEN = "p" * 43  # noqa: S105 - isolated synthetic cookie


def test_operator_manages_members_without_a_membership(postgres_harness):  # noqa: F811
    async def exercise():
        engine = create_async_engine(postgres_harness.schema_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        operations, public = uuid4(), uuid4()
        settings = Settings(
            _env_file=None,
            environment="test",
            admin_app_url=ORIGIN,
            public_learner_tenant_id=public,
            operations_tenant_id=operations,
        )
        manager, operator, owner, admin, rep = (uuid4() for _ in range(5))
        manager_session = uuid4()
        now = datetime.now(UTC)
        try:
            async with sessions() as db, db.begin():
                db.add_all(
                    Person(id=person, email=f"{label}-{person}@example.test", email_verified_at=now)
                    for label, person in (
                        ("manager", manager),
                        ("operator", operator),
                        ("owner", owner),
                        ("admin", admin),
                        ("rep", rep),
                    )
                )
                db.add(Tenant(id=operations, slug=f"ops-{operations}", name="Fictional Operations"))
                await db.flush()
                db.add(Membership(tenant_id=operations, person_id=manager, role="owner"))
                service = OrganisationService(
                    db, operations_tenant_id=operations, public_learner_tenant_id=public
                )
                org = await service.create("Fictional Operator Team", owner, uuid4(), "AUT-446")
                db.add_all(
                    [
                        Membership(tenant_id=org.tenant_id, person_id=admin, role="admin"),
                        Membership(tenant_id=org.tenant_id, person_id=rep, role="member"),
                    ]
                )
                await db.flush()
                pepper = settings.session_token_pepper.get_secret_value().encode()
                db.add_all(
                    IdentitySession(
                        id=identity,
                        person_id=person,
                        token_hash=digest(pepper, token.encode(), sha256),
                        created_at=now,
                        expires_at=now + timedelta(days=1),
                    )
                    for identity, person, token in (
                        (manager_session, manager, "m" * 43),
                        (uuid4(), operator, TOKEN),
                    )
                )
                await db.flush()
                capabilities = CapabilityApplication(db, operations_tenant_id=operations)
                await capabilities.bootstrap_first_manager(
                    person_id=manager, command_id=uuid4(), reason="Fictional first manager"
                )
                for permission in ("platform_tenants_read", "platform_organisations_manage"):
                    await capabilities.grant(
                        ActorContext(
                            person_id=manager,
                            session_id=manager_session,
                            tenant_id=operations,
                            permissions=frozenset(),
                        ),
                        command_id=uuid4(),
                        subject_person_id=operator,
                        permission=permission,
                        scope=CapabilityScope("platform"),
                        reason="Fictional operator assignment",
                    )
            app = FastAPI()
            register_problem_handlers(app)
            actor = install_identity_http(app, settings=settings, sessions=cast(Any, sessions))
            install_platform_organisations_http(app, settings=settings, require_actor=actor)

            def memberships():
                with Session(postgres_harness.engine) as db:
                    return {
                        row.person_id: (row.role, row.status)
                        for row in db.scalars(
                            select(Membership).where(Membership.tenant_id == org.tenant_id)
                        )
                    }

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=ORIGIN
            ) as client:

                async def send(method, path, key=None, body=None):
                    headers = {"cookie": f"ac_session={TOKEN}", "origin": ORIGIN}
                    if key is not None:
                        headers["Idempotency-Key"] = str(key)
                    return await client.request(
                        method,
                        "/v1/platform/organisations" + path,
                        json=None if body is None else {**body, "reason": REASON},
                        headers=headers,
                    )

                listed = await send("GET", "")
                assert listed.status_code == 200, listed.text
                row = next(
                    item
                    for item in listed.json()["organisations"]
                    if item["tenant_id"] == str(org.tenant_id)
                )
                assert (row["name"], row["member_count"]) == ("Fictional Operator Team", 3)
                base = f"/{org.tenant_id}"
                assert (await send("GET", f"/{operations}/members")).status_code == 404
                directory = await send("GET", f"{base}/members")
                assert {m["person_id"] for m in directory.json()["members"]} == {
                    str(owner),
                    str(admin),
                    str(rep),
                }

                def transfer(target, key):
                    return send("POST", f"{base}/owner", key, {"person_id": str(target)})

                # A member's own request may hold a shared fence on the row: the
                # operator gets a retryable conflict, never a wait or a partial swap.
                key = uuid4()
                with Session(postgres_harness.engine) as held, held.begin():
                    held.scalar(
                        select(Membership)
                        .where(Membership.tenant_id == org.tenant_id, Membership.person_id == owner)
                        .with_for_update(read=True)
                    )
                    busy = await asyncio.wait_for(transfer(rep, key), timeout=5)
                    assert busy.status_code == 409 and "retry" in busy.json()["detail"]
                assert memberships()[owner] == ("owner", "active")

                # Same-key concurrent transfers have one effect and one result.
                pair = await asyncio.wait_for(
                    asyncio.gather(transfer(rep, key), transfer(rep, key)), timeout=15
                )
                assert {r.status_code for r in pair} <= {200, 409}
                settled = await transfer(rep, key)
                assert settled.status_code == 200, settled.text
                assert all(r.json() == settled.json() for r in pair if r.status_code == 200)
                assert settled.json()["former_owner"]["person_id"] == str(owner)

                # The operator acts on any role: demote the former owner, remove the admin.
                demoted = await send(
                    "PATCH", f"{base}/members/{owner}", uuid4(), {"role": "member"}
                )
                assert demoted.status_code == 200, demoted.text
                assert (
                    await send("DELETE", f"{base}/members/{admin}", uuid4(), {})
                ).status_code == 204
                refused = await send("DELETE", f"{base}/members/{rep}", uuid4(), {})
                assert refused.status_code == 409
                added = await send(
                    "POST",
                    f"{base}/members",
                    uuid4(),
                    {"email": f"admin-{admin}@example.test", "role": "member"},
                )
                assert added.status_code == 200, added.text
                assert memberships() == {
                    owner: ("member", "active"),
                    admin: ("member", "active"),
                    rep: ("owner", "active"),
                }

            with Session(postgres_harness.engine) as db:
                events = list(
                    db.scalars(
                        select(AuditEvent)
                        .where(AuditEvent.tenant_id == org.tenant_id)
                        .order_by(AuditEvent.sequence_no)
                    )
                )
                assert [event.action for event in events[1:]] == [
                    "organisation.ownership_transferred",
                    "organisation.member_role_changed",
                    "organisation.member_removed",
                    "organisation.member_added",
                ]
                # Every write is one event in the organisation tenant naming the
                # operator and the reason; the operator gained no membership.
                assert all(
                    event.actor_person_id == operator and event.reason == REASON
                    for event in events[1:]
                )
                assert verify_audit_chain_sync(db, org.tenant_id).valid
                assert db.get(Membership, (org.tenant_id, operator)) is None
        finally:
            await engine.dispose()

    asyncio.run(exercise())
