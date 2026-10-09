"""Fictional HTTP and PostgreSQL race proofs for companion card 5.

Uses the established explicit-loopback, migrated, disposable schema harness.
No application flag, host service or real account is changed by these tests.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from sqlalchemy import event, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from ac_platform.application.settings import Settings
from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain
from ac_platform.db.models import companion_credentials as credentials
from ac_platform.db.models import companion_devices as devices
from ac_platform.db.models import companion_pairings as pairings
from ac_platform.db.models import companion_refresh_families as families
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.http.native_devices import install_native_devices_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.native_devices import NativeDevices, digest
from ac_platform.organisations.service import OrganisationService
from ac_platform.tenancy.models import Membership, Organisation, Tenant
from tests.database.test_conversation_postgresql import postgres_harness as postgres_harness

ORIGIN = "https://xray.example.test"
PREFIX = "/v1/native"


@pytest.fixture
async def native(postgres_harness, monkeypatch) -> AsyncIterator[Any]:
    monkeypatch.setenv("AC_NATIVE_API_ENABLED", "1")
    person, tenant, other_person, other_tenant = [uuid4() for _ in range(4)]
    with Session(postgres_harness) as db, db.begin():
        db.add_all(
            [
                Tenant(id=tenant, slug=tenant.hex, name="Fictional workspace"),
                Tenant(id=other_tenant, slug=other_tenant.hex, name="Other fictional workspace"),
                Person(id=person, email=f"{person.hex}@example.test"),
                Person(id=other_person, email=f"{other_person.hex}@example.test"),
            ]
        )
        db.flush()
        db.add_all(
            [
                Membership(tenant_id=tenant, person_id=person, role="member"),
                Membership(tenant_id=tenant, person_id=other_person, role="member"),
                Membership(tenant_id=other_tenant, person_id=person, role="member"),
            ]
        )
    engine = create_async_engine(postgres_harness.url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    actor = ActorContext(person_id=person, tenant_id=tenant, session_id=uuid4())
    actors = {
        "fictional-owner": actor,
        "fictional-other": ActorContext(other_person, uuid4(), tenant),
        "fictional-workspace": ActorContext(person, uuid4(), other_tenant),
    }
    # Preserve the real audit/session FK while using a bounded cookie-resolver
    # seam; the application's established resolver is wired in app.py.
    with Session(postgres_harness) as db, db.begin():
        for context in actors.values():
            db.add(
                IdentitySession(
                    id=context.session_id,
                    person_id=context.person_id,
                    selected_tenant_id=context.tenant_id,
                    token_hash=bytes.fromhex(digest(str(context.session_id))),
                    expires_at=datetime.now(UTC) + timedelta(days=1),
                )
            )

    async def require_actor(request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        resolved = actors.get(request.cookies.get("fictional-session", ""))
        if resolved is None:
            raise HTTPException(401, "Cookie session required.")
        async with sessions() as db, db.begin():
            yield cast(
                AuthenticatedTransaction,
                SimpleNamespace(
                    database=db,
                    resolved=SimpleNamespace(actor=resolved),
                ),
            )

    application = FastAPI()
    register_problem_handlers(application)
    settings = Settings(
        environment="test",
        sales_xray_app_url=ORIGIN,
        allowed_origins=[ORIGIN],
    )
    install_native_devices_http(
        application,
        settings=settings,
        require_actor=require_actor,
        sessions=sessions,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url=ORIGIN,
        cookies={"fictional-session": "fictional-owner"},
        headers={"Origin": ORIGIN},
    ) as client:
        yield SimpleNamespace(
            client=client,
            app=application,
            sessions=sessions,
            actor=actor,
            person=person,
            tenant=tenant,
            engine=engine,
        )
    await engine.dispose()


async def start(native) -> dict[str, Any]:
    result = await native.client.post(
        PREFIX + "/pair/start",
        json={
            "name": "Fictional phone",
            "platform": "android",
        },
    )
    assert result.status_code == 201
    return result.json()


async def poll(native, pairing) -> httpx.Response:
    return await native.client.post(
        PREFIX + "/pair/poll",
        json={
            "pairing_id": pairing["pairing_id"],
            "poll_secret": pairing["poll_secret"],
        },
    )


async def paired(native) -> dict[str, Any]:
    pairing = await start(native)
    decided = await native.client.post(
        PREFIX + "/pair/decide",
        json={
            "code": pairing["code"],
            "decision": "approve",
        },
    )
    assert decided.json() == {"state": "approved"}
    result = await poll(native, pairing)
    assert result.status_code == 200
    return result.json()


async def refresh(native, token) -> httpx.Response:
    return await native.client.post(PREFIX + "/token/refresh", json={"refresh_token": token})


@pytest.mark.asyncio
async def test_approve_collect_once_hashes_audit_and_empty_list(native, caplog):
    assert (await native.client.get(PREFIX + "/devices")).json() == {
        "devices": [],
        "next_cursor": None,
    }
    pairing = await start(native)
    assert len(pairing["code"]) == 8 and len(pairing["poll_secret"]) == 43
    assert (await poll(native, pairing)).json() == {"state": "pending"}
    assert (
        await native.client.post(
            PREFIX + "/pair/decide",
            json={
                "code": pairing["code"],
                "decision": "approve",
            },
        )
    ).json() == {"state": "approved"}
    wrong = await poll(native, pairing | {"poll_secret": "x" * 43})
    assert wrong.status_code == 404
    collected = await poll(native, pairing)
    tokens = collected.json()
    assert tokens["token_type"] == "Bearer"  # noqa: S105 - public HTTP authentication scheme
    assert tokens["workspace_id"] == str(native.tenant)
    assert (await poll(native, pairing)).status_code == 409
    assert (
        await native.client.post(
            PREFIX + "/pair/decide",
            json={
                "code": pairing["code"],
                "decision": "approve",
            },
        )
    ).status_code == 409
    listing = (await native.client.get(PREFIX + "/devices")).json()
    assert listing["devices"][0]["id"] == tokens["device_id"]
    assert listing["devices"][0]["revoked_at"] is None
    async with native.sessions() as db:
        row = (
            (
                await db.execute(
                    select(pairings).where(
                        pairings.c.id == UUID(pairing["pairing_id"]),
                    )
                )
            )
            .mappings()
            .one()
        )
        assert row["code_sha256"] == digest(pairing["code"])
        assert row["poll_secret_sha256"] == digest(pairing["poll_secret"])
        hashes = (
            (
                await db.execute(
                    select(credentials.c.token_sha256)
                    .join(families)
                    .where(
                        families.c.device_id == UUID(tokens["device_id"]),
                    )
                )
            )
            .scalars()
            .all()
        )
        assert set(hashes) == {digest(tokens["access_token"]), digest(tokens["refresh_token"])}
        assert (await verify_audit_chain(db, native.tenant)).valid
        audit = str(
            (
                await db.scalars(
                    select(AuditEvent.payload).where(
                        AuditEvent.tenant_id == native.tenant,
                    )
                )
            ).all()
        )
    for secret in [
        pairing["code"],
        pairing["poll_secret"],
        tokens["access_token"],
        tokens["refresh_token"],
    ]:
        assert secret not in audit and secret not in caplog.text
    assert collected.headers["cache-control"] == "private, no-store"


@pytest.mark.asyncio
async def test_deny_expiry_and_wrong_secret(native):
    pairing = await start(native)
    assert (
        await native.client.post(
            PREFIX + "/pair/decide",
            json={
                "code": pairing["code"],
                "decision": "deny",
            },
        )
    ).json() == {"state": "denied"}
    assert (await poll(native, pairing)).json() == {"state": "denied"}
    assert (await native.client.get(PREFIX + "/devices")).json()["devices"] == []
    old = datetime.now(UTC) - timedelta(minutes=11)
    async with native.sessions() as db, db.begin():
        outcome = await NativeDevices(db, clock=lambda: old).start("Expired", "ios")
    expired = outcome.body
    assert (await poll(native, expired)).status_code == 410
    assert (
        await native.client.post(
            PREFIX + "/pair/decide",
            json={
                "code": expired["code"],
                "decision": "approve",
            },
        )
    ).status_code == 410


@pytest.mark.asyncio
async def test_rotation_reuse_commits_family_revocation_and_rejects_all_access(native):
    tokens = await paired(native)
    rotated = await refresh(native, tokens["refresh_token"])
    assert rotated.status_code == 200
    assert rotated.json()["access_token"] != tokens["access_token"]
    assert rotated.json()["refresh_token"] != tokens["refresh_token"]
    replay = await refresh(native, tokens["refresh_token"])
    assert replay.status_code == 401 and replay.json()["code"] == "refresh_reuse"
    assert (await refresh(native, rotated.json()["refresh_token"])).status_code == 401
    for access in [tokens["access_token"], rotated.json()["access_token"]]:
        assert (
            await native.client.post(
                PREFIX + f"/devices/{tokens['device_id']}/revoke",
                headers={"Authorization": "Bearer " + access},
            )
        ).status_code == 401
    async with native.sessions() as db:
        family = (
            (
                await db.execute(
                    select(families).where(
                        families.c.device_id == UUID(tokens["device_id"]),
                    )
                )
            )
            .mappings()
            .one()
        )
        assert family["revoked_at"] is not None
        assert (
            await db.scalar(
                select(AuditEvent.action).where(
                    AuditEvent.tenant_id == native.tenant,
                    AuditEvent.action == "native.refresh.reuse_revoke",
                )
            )
        ) is not None
        assert (await verify_audit_chain(db, native.tenant)).valid


@pytest.mark.asyncio
async def test_concurrent_collect_and_refresh(native):
    pairing = await start(native)
    await native.client.post(
        PREFIX + "/pair/decide",
        json={
            "code": pairing["code"],
            "decision": "approve",
        },
    )
    results = await asyncio.gather(poll(native, pairing), poll(native, pairing))
    assert sorted(r.status_code for r in results) == [200, 409]
    tokens = next(r.json() for r in results if r.status_code == 200)
    rotated = await asyncio.gather(
        refresh(native, tokens["refresh_token"]),
        refresh(native, tokens["refresh_token"]),
    )
    assert sorted(r.status_code for r in rotated) == [200, 401]
    winner = next(r.json() for r in rotated if r.status_code == 200)
    assert (await refresh(native, winner["refresh_token"])).status_code == 401


@pytest.mark.asyncio
async def test_cookie_revoke_scope_and_bearer_own_device_only(native):
    tokens = await paired(native)
    second = await paired(native)
    headers = {"Authorization": "Bearer " + tokens["access_token"]}
    wrong = await native.client.post(
        PREFIX + f"/devices/{second['device_id']}/revoke", headers=headers
    )
    assert wrong.status_code == 404  # Cookie for the same person cannot broaden bearer scope.
    for cookie in ["fictional-other", "fictional-workspace"]:
        native.client.cookies.set("fictional-session", cookie)
        assert (await native.client.get(PREFIX + "/devices")).json()["devices"] == []
        assert (
            await native.client.post(
                PREFIX + f"/devices/{tokens['device_id']}/revoke",
            )
        ).status_code == 404
    native.client.cookies.set("fictional-session", "fictional-owner")
    assert (
        await native.client.post(
            PREFIX + f"/devices/{tokens['device_id']}/revoke",
            headers={"Authorization": "Bearer invalid"},
        )
    ).status_code == 401
    assert (
        await native.client.post(
            PREFIX + f"/devices/{tokens['device_id']}/revoke",
            headers=headers,
        )
    ).json()["state"] == "revoked"
    assert (await refresh(native, tokens["refresh_token"])).status_code == 401
    assert (
        await native.client.post(
            PREFIX + f"/devices/{second['device_id']}/revoke",
        )
    ).status_code == 200
    assert (
        await native.client.post(
            PREFIX + f"/devices/{second['device_id']}/revoke",
        )
    ).status_code == 200


@pytest.mark.asyncio
async def test_membership_removal_revokes_binding_on_next_request(native):
    first, second = await paired(native), await paired(native)
    async with native.sessions() as db, db.begin():
        await db.execute(
            update(Membership)
            .where(
                Membership.tenant_id == native.tenant,
                Membership.person_id == native.person,
            )
            .values(status="inactive", ended_at=datetime.now(UTC))
        )
    assert (await refresh(native, first["refresh_token"])).status_code == 401
    async with native.sessions() as db, db.begin():
        rows = (
            (
                await db.execute(
                    select(devices.c.revoked_at).where(
                        devices.c.tenant_id == native.tenant,
                        devices.c.person_id == native.person,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 2 and all(rows)
        await db.execute(
            update(Membership)
            .where(
                Membership.tenant_id == native.tenant,
                Membership.person_id == native.person,
            )
            .values(status="active", ended_at=None)
        )
    assert (await refresh(native, second["refresh_token"])).status_code == 401


@pytest.mark.asyncio
async def test_cookie_origin_and_browser_bearer_separation(native):
    tokens = await paired(native)
    pairing = await start(native)
    data = {"code": pairing["code"], "decision": "approve"}
    for origin in ["https://evil.example.test", ""]:
        assert (
            await native.client.post(PREFIX + "/pair/decide", json=data, headers={"Origin": origin})
        ).status_code == 403
    native.client.cookies.clear()
    bearer = {"Authorization": "Bearer " + tokens["access_token"]}
    assert (
        await native.client.post(PREFIX + "/pair/decide", json=data, headers=bearer)
    ).status_code == 401
    assert (await native.client.get(PREFIX + "/devices", headers=bearer)).status_code == 401
    native.client.cookies.set("fictional-session", "fictional-owner")
    assert (
        await native.client.post(
            PREFIX + "/pair/decide", json=data, headers={"Authorization": "Bearer invalid"}
        )
    ).status_code == 200
    assert (
        await native.client.post(
            PREFIX + "/pair/poll",
            json={
                "pairing_id": pairing["pairing_id"],
            },
        )
    ).status_code == 422
    assert (await native.client.post(PREFIX + "/token/refresh", json={})).status_code == 422
    for path in [
        "/notifications",
        "/conversation/acquisition/submissions",
        "/refresh",
        "/web-session",
    ]:
        assert (await native.client.post(PREFIX + path, headers=bearer)).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", [None, "0", "true", "yes"])
async def test_kill_switch_precedes_auth_and_validation(native, monkeypatch, flag):
    if flag is None:
        monkeypatch.delenv("AC_NATIVE_API_ENABLED")
    else:
        monkeypatch.setenv("AC_NATIVE_API_ENABLED", flag)
    native.client.cookies.clear()
    for path in [
        "/pair/start",
        "/pair/poll",
        "/pair/decide",
        "/token/refresh",
        "/devices/not-uuid/revoke",
    ]:
        result = await native.client.post(PREFIX + path, content=b"invalid-json")
        assert result.status_code == 404
    assert (await native.client.get(PREFIX + "/devices?after=bad")).status_code == 404


@pytest.mark.asyncio
async def test_address_rate_limit_and_safe_validation(native, caplog):
    for _ in range(5):
        await start(native)
    assert (
        await native.client.post(
            PREFIX + "/pair/start",
            json={
                "name": "Fictional",
                "platform": "ios",
            },
        )
    ).status_code == 429
    marker = "fictional-credential-never-echo"
    for path, data in [
        ("/token/refresh", {"refresh_token": marker}),
        ("/pair/poll", {"pairing_id": str(uuid4()), "poll_secret": marker}),
    ]:
        result = await native.client.post(PREFIX + path, json=data)
        assert result.status_code == 422 and marker not in result.text
    assert marker not in caplog.text
    assert (
        await native.client.post(PREFIX + "/token/refresh", content=b"x" * 4097)
    ).status_code == 413


@pytest.mark.asyncio
async def test_device_list_has_bounded_query_count_and_validated_cursor(native):
    await paired(native)
    statements = []

    def track(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(native.engine.sync_engine, "before_cursor_execute", track)
    try:
        result = await native.client.get(PREFIX + "/devices")
    finally:
        event.remove(native.engine.sync_engine, "before_cursor_execute", track)
    assert result.status_code == 200
    assert len(statements) == 3  # Binding, latest immutable removal and bounded device read.
    cursor = result.json()["devices"][0]["id"]
    assert (await native.client.get(PREFIX + "/devices", params={"after": cursor})).json()[
        "devices"
    ] == []
    assert (await native.client.get(PREFIX + "/devices?after=invalid")).status_code == 422


@pytest.mark.asyncio
async def test_removal_rejoin_without_native_traffic_does_not_revive_credentials(native):
    tokens = await paired(native)
    async with native.sessions() as db, db.begin():
        db.add(
            Organisation(
                tenant_id=native.tenant,
                creation_command_id=uuid4(),
                domain_verification_token=uuid4().hex * 2,
            )
        )
        await db.flush()
        await OrganisationService(
            db,
            operations_tenant_id=uuid4(),
            public_learner_tenant_id=uuid4(),
        ).remove_member(
            native.tenant,
            native.person,
            uuid4(),
            actor_person_id=native.person,
        )
    async with native.sessions() as db, db.begin():
        await db.execute(
            update(Membership)
            .where(
                Membership.tenant_id == native.tenant,
                Membership.person_id == native.person,
            )
            .values(status="active", ended_at=None)
        )
    listing = (await native.client.get(PREFIX + "/devices")).json()
    assert listing["devices"][0]["revoked_at"] is not None
    assert (await refresh(native, tokens["refresh_token"])).status_code == 401
    fresh = await paired(native)
    assert (await refresh(native, fresh["refresh_token"])).status_code == 200


@pytest.mark.asyncio
async def test_idle_absolute_access_expiry_and_expired_spent_evidence(native):
    tokens = await paired(native)
    now = datetime.now(UTC)

    async def timed_refresh(token, days):
        async with native.sessions() as db, db.begin():
            return await NativeDevices(db, clock=lambda: now + timedelta(days=days)).refresh(token)

    async with native.sessions() as db, db.begin():
        assert (
            await NativeDevices(db, clock=lambda: now + timedelta(minutes=16)).authenticate(
                tokens["access_token"],
            )
            is None
        )
    assert (await timed_refresh(tokens["refresh_token"], 31)).status == 401
    rotated = await timed_refresh(tokens["refresh_token"], 29)
    assert rotated.status == 200
    replay = await timed_refresh(tokens["refresh_token"], 31)
    assert replay.body["code"] == "refresh_reuse"
    tokens = await paired(native)
    for day in [29, 58, 87]:
        result = await timed_refresh(tokens["refresh_token"], day)
        assert result.status == 200
        tokens = result.body
    assert datetime.fromisoformat(tokens["refresh_expires_at"]) < now + timedelta(days=91)
    assert (await timed_refresh(tokens["refresh_token"], 91)).status == 401


@pytest.mark.asyncio
async def test_per_device_refresh_limit_survives_address_changes(native):
    tokens = await paired(native)
    for index in range(31):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=native.app, client=(f"192.0.2.{index + 1}", 1234)),
            base_url=ORIGIN,
        ) as client:
            result = await client.post(
                PREFIX + "/token/refresh",
                json={
                    "refresh_token": tokens["refresh_token"],
                },
            )
        if index == 30:
            assert result.status_code == 429
        else:
            assert result.status_code == 200
            tokens = result.json()


@pytest.mark.asyncio
async def test_approve_deny_race_and_approval_keeps_original_expiry(native):
    pairing = await start(native)
    results = await asyncio.gather(
        *[
            native.client.post(
                PREFIX + "/pair/decide",
                json={
                    "code": pairing["code"],
                    "decision": decision,
                },
            )
            for decision in ["approve", "deny"]
        ]
    )
    assert sorted(r.status_code for r in results) == [200, 409]
    async with native.sessions() as db:
        row = (
            (
                await db.execute(
                    select(pairings).where(
                        pairings.c.id == UUID(pairing["pairing_id"]),
                    )
                )
            )
            .mappings()
            .one()
        )
        assert row["expires_at"] == datetime.fromisoformat(pairing["expires_at"])
