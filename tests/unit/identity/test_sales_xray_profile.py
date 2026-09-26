from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import ac_platform.http.conversation as conversation_http
import ac_platform.identity.sales_xray_profile as profile_service
from ac_platform.application.settings import Settings
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.http.conversation import install_conversation_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.http.sales_xray_profile import (
    install_sales_xray_profile_http,
    require_sales_xray_write_profile,
)
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.identity.models import Person
from ac_platform.identity.sales_xray_profile import (
    SalesXrayProfileIncomplete,
    SalesXrayProfileRevisionConflict,
    erase_sales_xray_profile,
    require_sales_xray_profile_complete,
    update_sales_xray_profile,
)
from ac_platform.identity.sales_xray_profile_models import SalesXrayProfile
from ac_platform.kernel.authz import ActorContext

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
PERSON_ID = UUID("11111111-1111-4111-8111-111111111111")
OTHER_PERSON_ID = UUID("22222222-2222-4222-8222-222222222222")
TENANT_ID = UUID("33333333-3333-4333-8333-333333333333")
SESSION_ID = UUID("44444444-4444-4444-8444-444444444444")


class _AsyncSessionAdapter:
    def __init__(self, session: Session) -> None:
        self.session = session

    async def scalar(self, statement: object) -> Any:
        return self.session.scalar(statement)  # type: ignore[arg-type]

    async def flush(self) -> None:
        self.session.flush()

    def add(self, instance: object) -> None:
        self.session.add(instance)

    def get(self, model: type[Any], identifier: UUID) -> Any:
        return self.session.get(model, identifier)

    async def delete(self, instance: object) -> None:
        self.session.delete(instance)


class _AuditRecorder:
    events: list[dict[str, object]] = []

    def __init__(self, _session: object) -> None:
        pass

    async def append(self, **event: object) -> None:
        self.events.append(event)


@pytest.fixture
def database(monkeypatch: pytest.MonkeyPatch) -> Any:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Person.__table__.create(engine)
    SalesXrayProfile.__table__.create(engine)
    session = Session(engine, expire_on_commit=False)
    session.add_all(
        [
            Person(
                id=PERSON_ID,
                email="one@example.test",
                email_verified_at=NOW,
                display_name="One Person",
                status="active",
            ),
            Person(
                id=OTHER_PERSON_ID,
                email="two@example.test",
                email_verified_at=NOW,
                display_name="Two Person",
                status="active",
            ),
        ]
    )
    session.commit()
    _AuditRecorder.events = []
    monkeypatch.setattr(profile_service, "AuditRepository", _AuditRecorder)
    try:
        yield _AsyncSessionAdapter(session), session
    finally:
        session.close()
        SalesXrayProfile.__table__.drop(engine)
        Person.__table__.drop(engine)
        engine.dispose()


def _actor(person_id: UUID = PERSON_ID) -> ActorContext:
    return ActorContext(
        person_id=person_id,
        session_id=SESSION_ID,
        tenant_id=TENANT_ID,
    )


def _profile_settings() -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        database_url="postgresql+psycopg://unused:unused@localhost/unused",
        database_migrator_url="postgresql+psycopg://unused:unused@localhost/unused",
        session_token_pepper="test-session-token-pepper-long-enough",  # noqa: S106
        oauth_transaction_secret="test-oauth-transaction-secret-key-32",  # noqa: S106
        public_app_url="https://app.authorityclosers.test",
        sales_xray_app_url="https://salesxray.authorityclosers.test",
        admin_app_url="https://admin.authorityclosers.test",
        coach_app_url="https://coach.authorityclosers.test",
        api_url="https://api.authorityclosers.test",
        public_learner_tenant_id=TENANT_ID,
        operations_tenant_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_profile_update_is_versioned_person_scoped_and_audited_without_contact_values(
    database: Any,
) -> None:
    async_database, sync_database = database
    result = await update_sales_xray_profile(
        async_database,
        person_id=PERSON_ID,
        session_id=SESSION_ID,
        tenant_id=TENANT_ID,
        full_name="  One   Updated  ",
        phone_number_e164="+14155550100",
        expected_revision=0,
    )

    assert result.name == "One Updated"
    assert result.email == "one@example.test"
    assert result.phone_number_e164 == "+14155550100"
    assert result.phone_verified is False
    assert result.profile_complete is True
    assert result.revision == 1
    assert sync_database.get(Person, OTHER_PERSON_ID).display_name == "Two Person"
    assert len(_AuditRecorder.events) == 1
    audit = _AuditRecorder.events[0]
    assert audit["action"] == "sales_xray.profile.self_updated.v1"
    assert audit["payload"] == {
        "revision": 1,
        "changed_fields": ["name", "phone_number_e164", "profile_created"],
        "admin_collision_review_required": False,
    }
    assert "+14155550100" not in repr(audit)
    assert "One Updated" not in repr(audit)

    with pytest.raises(SalesXrayProfileRevisionConflict):
        await update_sales_xray_profile(
            async_database,
            person_id=PERSON_ID,
            session_id=SESSION_ID,
            tenant_id=TENANT_ID,
            full_name="Another Name",
            phone_number_e164="+14155550100",
            expected_revision=0,
        )
    assert sync_database.get(Person, OTHER_PERSON_ID).display_name == "Two Person"


@pytest.mark.asyncio
async def test_unverified_phone_collision_is_nonblocking_and_not_exposed(
    database: Any,
) -> None:
    async_database, sync_database = database
    first = await update_sales_xray_profile(
        async_database,
        person_id=PERSON_ID,
        session_id=SESSION_ID,
        tenant_id=TENANT_ID,
        full_name="One Person",
        phone_number_e164="+442079460123",
        expected_revision=0,
    )
    second = await update_sales_xray_profile(
        async_database,
        person_id=OTHER_PERSON_ID,
        session_id=uuid4(),
        tenant_id=TENANT_ID,
        full_name="Two Person",
        phone_number_e164="+442079460123",
        expected_revision=0,
    )

    assert first.profile_complete and second.profile_complete
    assert second.phone_verified is False
    assert "collision" not in repr(second)
    second_row = sync_database.scalar(
        select(SalesXrayProfile).where(SalesXrayProfile.person_id == OTHER_PERSON_ID)
    )
    assert second_row is not None and second_row.admin_collision_review_required is True


@pytest.mark.asyncio
async def test_verified_number_collision_allows_unverified_capture_for_review(
    database: Any,
) -> None:
    async_database, sync_database = database
    sync_database.add(
        SalesXrayProfile(
            person_id=PERSON_ID,
            phone_number_e164="+919876543210",
            phone_verified_at=NOW,
            revision=1,
        )
    )
    sync_database.commit()

    captured = await update_sales_xray_profile(
        async_database,
        person_id=OTHER_PERSON_ID,
        session_id=uuid4(),
        tenant_id=TENANT_ID,
        full_name="Two Person",
        phone_number_e164="+919876543210",
        expected_revision=0,
    )

    assert captured.profile_complete
    assert captured.phone_verified is False
    row = sync_database.scalar(
        select(SalesXrayProfile).where(SalesXrayProfile.person_id == OTHER_PERSON_ID)
    )
    assert row is not None and row.admin_collision_review_required is True


@pytest.mark.asyncio
async def test_account_deletion_erases_private_phone_profile(database: Any) -> None:
    async_database, sync_database = database
    await update_sales_xray_profile(
        async_database,
        person_id=PERSON_ID,
        session_id=SESSION_ID,
        tenant_id=TENANT_ID,
        full_name="One Person",
        phone_number_e164="+817012345678",
        expected_revision=0,
    )

    assert await erase_sales_xray_profile(async_database, person_id=PERSON_ID) is True
    assert await erase_sales_xray_profile(async_database, person_id=PERSON_ID) is False
    assert (
        sync_database.scalar(
            select(SalesXrayProfile).where(SalesXrayProfile.person_id == PERSON_ID)
        )
        is None
    )


@pytest.mark.asyncio
async def test_write_gate_accepts_unverified_phone_and_rejects_incomplete_or_suspended(
    database: Any,
) -> None:
    async_database, sync_database = database
    await update_sales_xray_profile(
        async_database,
        person_id=PERSON_ID,
        session_id=SESSION_ID,
        tenant_id=TENANT_ID,
        full_name="One Person",
        phone_number_e164="+33123456789",
        expected_revision=0,
    )
    eligible = await require_sales_xray_write_profile(async_database, _actor())
    assert eligible.profile_complete is True
    assert eligible.phone_verified is False

    with pytest.raises(SalesXrayProfileIncomplete):
        await require_sales_xray_profile_complete(async_database, person_id=OTHER_PERSON_ID)
    with pytest.raises(HTTPException) as guest:
        await require_sales_xray_write_profile(async_database, None)
    assert guest.value.status_code == 401

    suspended = sync_database.get(Person, OTHER_PERSON_ID)
    suspended.status = "suspended"
    sync_database.commit()
    with pytest.raises(HTTPException) as rejected:
        await require_sales_xray_write_profile(async_database, _actor(OTHER_PERSON_ID))
    assert rejected.value.status_code == 403


@pytest.mark.asyncio
async def test_profile_http_surface_returns_only_204_when_current_account_is_ready(
    database: Any,
) -> None:
    async_database, _ = database
    await update_sales_xray_profile(
        async_database,
        person_id=PERSON_ID,
        session_id=SESSION_ID,
        tenant_id=TENANT_ID,
        full_name="One Person",
        phone_number_e164="+61412345678",
        expected_revision=0,
    )
    settings = _profile_settings()
    selected_actor: ActorContext | None = _actor()
    mutating_calls = 0
    read_only_calls = 0

    async def transaction_for(
        request: Request,
    ) -> AsyncIterator[AuthenticatedTransaction]:
        if request.cookies.get("ac_session") != "present" or selected_actor is None:
            raise HTTPException(401, "Sign in required")
        yield AuthenticatedTransaction(
            database=async_database,  # type: ignore[arg-type]
            identity=object(),  # type: ignore[arg-type]
            resolved=ResolvedActorContext(
                actor=selected_actor,
                membership_role="learner",
                person_revision=0,
                session_revision=0,
                tenant_revision=0,
                membership_revision=0,
            ),
            token="test-session-token",  # noqa: S106
        )

    async def require_actor(request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        nonlocal mutating_calls
        mutating_calls += 1
        async for auth in transaction_for(request):
            yield auth

    async def read_only_actor(request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        nonlocal read_only_calls
        read_only_calls += 1
        async for auth in transaction_for(request):
            yield auth

    require_actor.read_only = read_only_actor  # type: ignore[attr-defined]

    application = FastAPI()
    register_problem_handlers(application)
    install_sales_xray_profile_http(application, settings=settings, require_actor=require_actor)
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url=str(settings.public_app_url)) as client:
        ready = await client.get(
            "/v1/me/sales-xray-profile/write-eligibility",
            cookies={"ac_session": "present"},
        )
        assert ready.status_code == 204, ready.text
        assert ready.content == b""
        assert ready.headers["cache-control"] == "private, no-store"
        assert (read_only_calls, mutating_calls) == (1, 0)
        unauthenticated = await client.get(
            "/v1/me/sales-xray-profile/write-eligibility",
            cookies={"ac_xray_guest": "g" * 43},
        )
        assert unauthenticated.status_code == 401
        assert read_only_calls == 2

        read_profile = await client.get(
            "/v1/me/sales-xray-profile",
            cookies={"ac_session": "present"},
        )
        assert read_profile.status_code == 200
        assert read_profile.json() == {
            "name": "One Person",
            "email": "one@example.test",
            "phone_number_e164": "+61412345678",
            "phone_verified": False,
            "profile_complete": True,
            "revision": 1,
        }
        assert read_only_calls == 3
        assert mutating_calls == 0

        updated = await client.put(
            "/v1/me/sales-xray-profile",
            cookies={"ac_session": "present"},
            headers={"origin": str(settings.public_app_url).rstrip("/")},
            json={
                "full_name": "One Updated",
                "phone_number_e164": "+61412345678",
                "expected_revision": 1,
            },
        )
        assert updated.status_code == 200
        assert updated.json()["name"] == "One Updated"
        assert updated.json()["revision"] == 2
        assert mutating_calls == 1

        stale_revision = await client.put(
            "/v1/me/sales-xray-profile",
            cookies={"ac_session": "present"},
            headers={"origin": str(settings.public_app_url).rstrip("/")},
            json={
                "full_name": "One Stale",
                "phone_number_e164": "+61412345678",
                "expected_revision": 1,
            },
        )
        assert stale_revision.status_code == 409

        guessed_person = await client.put(
            "/v1/me/sales-xray-profile",
            cookies={"ac_session": "present"},
            headers={"origin": str(settings.public_app_url).rstrip("/")},
            json={
                "full_name": "One Updated",
                "phone_number_e164": "+61412345678",
                "expected_revision": 2,
                "person_id": str(OTHER_PERSON_ID),
            },
        )
        assert guessed_person.status_code == 422

        disallowed_host = await client.get(
            "/v1/me/sales-xray-profile",
            cookies={"ac_session": "present"},
            headers={"host": settings.api_url.host},
        )
        assert disallowed_host.status_code == 404

        selected_actor = _actor(OTHER_PERSON_ID)
        incomplete = await client.get(
            "/v1/me/sales-xray-profile/write-eligibility",
            cookies={"ac_session": "present"},
        )
        assert incomplete.status_code == 403
        for allowed_host in (
            settings.public_app_url.host,
            settings.sales_xray_app_url.host,
            settings.api_url.host,
            settings.admin_app_url.host,
            settings.coach_app_url.host,
        ):
            allowed_preflight = await client.get(
                "/v1/me/sales-xray-profile/write-eligibility",
                cookies={"ac_session": "present"},
                headers={"host": allowed_host},
            )
            assert allowed_preflight.status_code == 403


def test_legacy_registration_requires_an_account_profile_and_guest_cookie_is_not_auth(
    database: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async_database, _ = database
    settings = _profile_settings()
    selected_actor: ActorContext | None = _actor()
    calls: list[ActorContext] = []

    async def require_actor(request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        if request.cookies.get("ac_session") != "present" or selected_actor is None:
            raise HTTPException(401, "An AC account session is required")
        yield AuthenticatedTransaction(
            database=async_database,  # type: ignore[arg-type]
            identity=object(),  # type: ignore[arg-type]
            resolved=ResolvedActorContext(
                actor=selected_actor,
                membership_role="learner",
                person_revision=0,
                session_revision=0,
                tenant_revision=0,
                membership_revision=0,
            ),
            token="test-session-token",  # noqa: S106
        )

    async def register(_self: object, actor: ActorContext, _payload: object, *, key: str) -> Any:
        calls.append(actor)
        return {"idempotency_key": key}

    monkeypatch.setattr(conversation_http.ConversationApplication, "register", register)
    application = FastAPI()
    register_problem_handlers(application)
    install_conversation_http(
        application,
        settings=settings,
        require_actor=require_actor,
    )
    client = TestClient(application)
    body = {
        "source_sha256": "a" * 64,
        "source_bytes": 1,
        "content_type": "audio/mpeg",
        "permission_reference": str(uuid4()),
        "purpose": "internal_analysis",
    }
    headers = {
        "host": settings.public_app_url.host,
        "origin": str(settings.public_app_url).rstrip("/"),
        "Idempotency-Key": "profile-gate-test",
    }

    guest_only = client.post(
        "/v1/conversation/recordings",
        json=body,
        headers=headers,
        cookies={"ac_xray_guest": "g" * 43},
    )
    assert guest_only.status_code == 401
    assert calls == []

    incomplete = client.post(
        "/v1/conversation/recordings",
        json=body,
        headers=headers,
        cookies={"ac_session": "present"},
    )
    assert incomplete.status_code == 403
    assert calls == []

    sync_session = database[1]
    profile = SalesXrayProfile(
        person_id=PERSON_ID,
        phone_number_e164="+14155550100",
        revision=1,
    )
    sync_session.add(profile)
    sync_session.commit()
    ready = client.post(
        "/v1/conversation/recordings",
        json=body,
        headers=headers,
        cookies={"ac_session": "present"},
    )
    assert ready.status_code == 201
    assert ready.json()["idempotency_key"] == "profile-gate-test"
    assert calls == [_actor()]
