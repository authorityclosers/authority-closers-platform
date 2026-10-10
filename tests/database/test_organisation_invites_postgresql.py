"""Invitation transaction and race proof in the disposable CI database."""

import asyncio
from datetime import UTC, datetime
from hashlib import sha256
from hmac import digest
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.application.settings import Settings
from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain
from ac_platform.http.auth import install_identity_http
from ac_platform.http.organisation import install_organisation_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.errors import ResourceNotFound
from ac_platform.organisations.invite_email import (
    ORGANISATION_INVITATION_EVENT,
    ORGANISATION_INVITATION_ROUTE,
    resolve_organisation_invitation_message,
)
from ac_platform.organisations.service import OrganisationSeatsFull, OrganisationService
from ac_platform.outbox.models import OutboxEvent
from ac_platform.outbox.repository import OutboxRepository
from ac_platform.providers.fake_email import FakeEmailAdapter
from ac_platform.providers.resend_email import render_email
from ac_platform.tenancy.models import Membership, Organisation, OrganisationInvite
from tests.database.test_conversation_postgresql import (
    cancel_pending,
    run,
    seed,
    wait_blocked,
)
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_worker_postgresql import _reconcile
from tests.unit.organisations.test_service import seed_paid_seats


@pytest.fixture(scope="module")
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


def service(database, owner):
    return OrganisationService(
        database, operations_tenant_id=owner.permission_id, public_learner_tenant_id=owner.tenant_id
    )


async def setup(engine, *, seats=3):
    owner = await seed(engine)
    member = await seed(engine)
    async with AsyncSession(engine) as database, database.begin():
        result = await service(database, owner).create(
            "Fictional organisation",
            owner.person_id,
            uuid4(),
            "self-serve-fixture",
            actor_person_id=owner.person_id,
        )
        await seed_paid_seats(database, result.tenant_id, owner.person_id, seats=seats)
    return owner, member, result.tenant_id


@pytest.mark.parametrize("accept_first", [False, True])
def test_accept_revoke_race_serializes_the_canonical_invite(postgres_harness, accept_first):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        task = None
        try:
            owner, member, tenant_id = await setup(engine)
            async with AsyncSession(engine) as database, database.begin():
                result = await service(database, owner).request_member(
                    tenant_id,
                    f"worker-{member.person_id.hex}@example.test",
                    "member",
                    uuid4(),
                    actor_person_id=owner.person_id,
                    require_acceptance=True,
                )
                invite = await database.scalar(
                    select(OrganisationInvite).where(OrganisationInvite.tenant_id == tenant_id)
                )
                invite_id = invite.id
                assert result["status"] == "invited"
            waiting_pid = asyncio.get_running_loop().create_future()

            async def accept(database):
                return await service(database, owner).accept_invite(
                    invite_id, uuid4(), actor_person_id=member.person_id
                )

            async def revoke(database):
                return await service(database, owner).revoke_invite(
                    tenant_id, invite_id, uuid4(), actor_person_id=owner.person_id
                )

            async def second():
                async with AsyncSession(engine) as database, database.begin():
                    waiting_pid.set_result(await database.scalar(text("SELECT pg_backend_pid()")))
                    return await (revoke(database) if accept_first else accept(database))

            async with AsyncSession(engine) as database, database.begin():
                await (accept(database) if accept_first else revoke(database))
                task = asyncio.create_task(second())
                pid = await asyncio.wait_for(waiting_pid, 5)
                await wait_blocked(engine, pid, task)
            with pytest.raises(ResourceNotFound):
                await asyncio.wait_for(task, 5)
            async with AsyncSession(engine) as database, database.begin():
                invite = await database.get(OrganisationInvite, invite_id)
                assert invite.status == ("accepted" if accept_first else "revoked")
                membership = await database.get(Membership, (tenant_id, member.person_id))
                assert (membership is not None) is accept_first
                assert (await verify_audit_chain(database, tenant_id)).valid
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(OutboxEvent)
                        .where(OutboxEvent.tenant_id == tenant_id)
                    )
                    == 1
                )
        finally:
            await cancel_pending(task)
            await engine.dispose()

    run(exercise())


def test_competing_invites_cannot_reserve_the_same_last_paid_seat(postgres_harness):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        task = None
        try:
            owner, _, tenant_id = await setup(engine, seats=2)
            waiting_pid = asyncio.get_running_loop().create_future()

            async def invite(database, email):
                return await service(database, owner).request_member(
                    tenant_id,
                    email,
                    "member",
                    uuid4(),
                    actor_person_id=owner.person_id,
                    require_acceptance=True,
                )

            async def second():
                async with AsyncSession(engine) as database, database.begin():
                    waiting_pid.set_result(await database.scalar(text("SELECT pg_backend_pid()")))
                    return await invite(database, "second@example.test")

            async with AsyncSession(engine) as database, database.begin():
                await invite(database, "first@example.test")
                task = asyncio.create_task(second())
                pid = await asyncio.wait_for(waiting_pid, 5)
                await wait_blocked(engine, pid, task)
            with pytest.raises(OrganisationSeatsFull):
                await asyncio.wait_for(task, 5)
            async with AsyncSession(engine) as database, database.begin():
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(OrganisationInvite)
                        .where(OrganisationInvite.tenant_id == tenant_id)
                    )
                    == 1
                )
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(AuditEvent)
                        .where(
                            AuditEvent.tenant_id == tenant_id,
                            AuditEvent.action == "organisation.member_invited",
                        )
                    )
                    == 1
                )
                assert (await verify_audit_chain(database, tenant_id)).valid
                assert await database.get(Organisation, tenant_id) is not None
        finally:
            await cancel_pending(task)
            await engine.dispose()

    run(exercise())


def test_http_create_invite_durable_mail_and_explicit_accept_journey(postgres_harness):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            owner = await seed(engine)
            origin = "https://salesxray.example.test"
            settings = Settings(
                _env_file=None,
                environment="test",
                public_app_url="https://learner.example.test",
                sales_xray_app_url=origin,
                operations_tenant_id=owner.permission_id,
                public_learner_tenant_id=owner.tenant_id,
            )
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            await _reconcile(sessions, owner)
            app = FastAPI()
            register_problem_handlers(app)
            actor = install_identity_http(app, settings=settings, sessions=sessions)
            install_organisation_http(app, settings=settings, require_actor=actor)
            owner_cookie, member_cookie = "o" * 43, "m" * 43
            pepper = settings.session_token_pepper.get_secret_value().encode()
            async with sessions() as database, database.begin():
                identity = await database.get(IdentitySession, owner.session_id)
                identity.token_hash = digest(pepper, owner_cookie.encode(), sha256)
                identity.selected_tenant_id = None

            def headers(cookie, key=None):
                result = {"Origin": origin, "Cookie": f"ac_session={cookie}"}
                if key is not None:
                    result["Idempotency-Key"] = str(key)
                return result

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=origin
            ) as client:
                create_key = uuid4()
                response = await client.post(
                    "/v1/organisation",
                    json={"name": "Fictional journey team"},
                    headers=headers(owner_cookie, create_key),
                )
                assert response.status_code == 201, response.text
                tenant_id = UUID(response.json()["tenant_id"])
                async with sessions() as database, database.begin():
                    await seed_paid_seats(database, tenant_id, owner.person_id, seats=2)
                selected = await client.post(
                    "/v1/context",
                    json={"tenant_id": str(tenant_id)},
                    headers=headers(owner_cookie),
                )
                assert selected.status_code == 200, selected.text
                email = f"journey-{tenant_id.hex}@example.test"
                invited = await client.post(
                    "/v1/organisation/members",
                    json={"email": email, "role": "member"},
                    headers=headers(owner_cookie, uuid4()),
                )
                assert invited.status_code == 200, invited.text
                invite_id = UUID(invited.json()["invite_id"])
                async with sessions() as database, database.begin():
                    assert (
                        await database.scalar(select(Person).where(Person.email == email)) is None
                    )
                    # Exercise the exact organisation route in the existing outbox. The
                    # production worker registration is owned by Strike C, separately.
                    jobs = await OutboxRepository(database).materialize(
                        routes={ORGANISATION_INVITATION_EVENT: ORGANISATION_INVITATION_ROUTE},
                        limit=10,
                    )
                    assert len(jobs) == 1
                    message = await resolve_organisation_invitation_message(
                        database, settings, jobs[0], provider_key=f"outbox:{jobs[0].id}"
                    )
                    mail = FakeEmailAdapter()
                    first_receipt = await mail.send(message)
                    replay_receipt = await mail.send(message)
                    assert first_receipt.accepted and replay_receipt.deduplicated
                    rendered = render_email(message)
                    assert f"/organisation/invites?invite_id={invite_id}" in rendered.text
                member = await seed(engine)
                async with sessions() as database, database.begin():
                    person = await database.get(Person, member.person_id)
                    person.email, person.email_verified_at = email, datetime.now(UTC)
                    identity = await database.get(IdentitySession, member.session_id)
                    identity.token_hash = digest(pepper, member_cookie.encode(), sha256)
                    identity.selected_tenant_id = None
                pending = await client.get(
                    "/v1/organisation/invites", headers=headers(member_cookie)
                )
                assert pending.status_code == 200, pending.text
                assert pending.json()["invites"][0]["invite_id"] == str(invite_id)
                accept_key = uuid4()
                accepted = await client.post(
                    f"/v1/organisation/invites/{invite_id}/accept",
                    headers=headers(member_cookie, accept_key),
                )
                assert accepted.status_code == 200, accepted.text
                assert accepted.json()["role"] == "member"
                replay = await client.post(
                    f"/v1/organisation/invites/{invite_id}/accept",
                    headers=headers(member_cookie, accept_key),
                )
                assert replay.json() == accepted.json()
                selected = await client.post(
                    "/v1/context",
                    json={"tenant_id": str(tenant_id)},
                    headers=headers(member_cookie),
                )
                assert selected.status_code == 200, selected.text
                profile = await client.get(
                    "/v1/organisation/profile", headers=headers(member_cookie)
                )
                assert profile.json()["your_role"] == "member"
                pending = await client.get(
                    "/v1/organisation/invites", headers=headers(member_cookie)
                )
                assert pending.json()["invites"] == []
            async with sessions() as database, database.begin():
                assert (await verify_audit_chain(database, tenant_id)).valid
        finally:
            await engine.dispose()

    run(exercise())
