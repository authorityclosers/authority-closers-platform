from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, ClassVar, cast
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, insert
from sqlalchemy.orm import Session

import ac_platform.http.auth as auth_module
from ac_platform.application.settings import Settings
from ac_platform.http.auth import install_identity_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.identity.models import Person, ProviderIdentity
from ac_platform.identity.repositories import AsyncSqlAlchemyIdentityRepository
from ac_platform.identity.services import PersonSnapshot
from ac_platform.kernel.authz import ActorContext

SESSION_TOKEN = "s" * 43  # noqa: S105
PERSON_ID = UUID("11111111-1111-4111-8111-111111111111")
OTHER_PERSON_ID = UUID("22222222-2222-4222-8222-222222222222")
SESSION_ID = UUID("33333333-3333-4333-8333-333333333333")
THIRD_PERSON_ID = UUID("55555555-5555-4555-8555-555555555555")
GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")


class _Database:
    async def __aenter__(self) -> _Database:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def begin(self) -> _Database:
        return self


def _sessions() -> _Database:
    return _Database()


class _Repository:
    def __init__(self, provider_rows: Sequence[tuple[UUID, str]]) -> None:
        self.provider_rows = tuple(provider_rows)
        self.calls: list[tuple[UUID, tuple[str, ...]]] = []

    async def has_provider_identity_for_issuers(
        self, person_id: UUID, issuers: Sequence[str]
    ) -> bool:
        issuer_values = tuple(issuers)
        self.calls.append((person_id, issuer_values))
        return any(
            linked_person_id == person_id and issuer in issuer_values
            for linked_person_id, issuer in self.provider_rows
        )

    async def get_person(self, person_id: UUID) -> PersonSnapshot:
        return PersonSnapshot(
            id=person_id,
            email="learner@example.com",
            display_name="Learner",
            email_verified_at=datetime(2026, 1, 1, tzinfo=UTC),
        )


class _IdentityApplication:
    linked_rows: ClassVar[Sequence[tuple[UUID, str]]] = ()
    instances: ClassVar[list[_IdentityApplication]] = []

    def __init__(self, _database: object, *, token_pepper: str) -> None:
        del token_pepper
        self.repository = _Repository(type(self).linked_rows)
        type(self).instances.append(self)

    async def resolve_actor(self, token: str) -> ResolvedActorContext:
        assert token == SESSION_TOKEN
        return ResolvedActorContext(
            actor=ActorContext(
                person_id=PERSON_ID,
                session_id=SESSION_ID,
                tenant_id=None,
            ),
            membership_role=None,
            person_revision=0,
            session_revision=0,
        )


def _settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+psycopg://unused:unused@localhost/unused",
        database_migrator_url="postgresql+psycopg://unused:unused@localhost/unused",
        session_token_pepper="test-session-token-pepper-that-is-long-enough",  # noqa: S106
        oauth_transaction_secret="test-route-transaction-key-long-enough",  # noqa: S106
        public_app_url="https://app.authorityclosers.test",
        admin_app_url="https://admin.authorityclosers.test",
        api_url="https://api.authorityclosers.test",
    )


def _client(
    monkeypatch: pytest.MonkeyPatch,
    provider_rows: Sequence[tuple[UUID, str]] = (),
) -> tuple[TestClient, type[_IdentityApplication]]:
    _IdentityApplication.instances = []
    _IdentityApplication.linked_rows = provider_rows
    monkeypatch.setattr(auth_module, "AsyncIdentityApplication", _IdentityApplication)
    application = FastAPI()
    register_problem_handlers(application)
    install_identity_http(
        application,
        settings=_settings(),
        sessions=cast(Any, _sessions),
        provider=None,
    )
    client = TestClient(application)
    client.cookies.set("ac_session", SESSION_TOKEN)
    return client, _IdentityApplication


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        ([(PERSON_ID, "accounts.google.com")], True),
        ([(PERSON_ID, "https://accounts.google.com")], True),
        ([(PERSON_ID, "accounts.google.invalid")], False),
        ([(OTHER_PERSON_ID, "accounts.google.com")], False),
        (
            [
                (OTHER_PERSON_ID, "https://accounts.google.com"),
                (PERSON_ID, "accounts.google.invalid"),
            ],
            False,
        ),
    ],
)
def test_google_link_status_is_person_scoped_and_uses_google_issuers(
    monkeypatch: pytest.MonkeyPatch,
    rows: Sequence[tuple[UUID, str]],
    expected: bool,
) -> None:
    client, identity_type = _client(monkeypatch, rows)

    response = client.get("/v1/me/google-link")

    assert response.status_code == 200
    assert response.json() == {"linked": expected}
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["pragma"] == "no-cache"
    repository = identity_type.instances[0].repository
    assert repository.calls == [(PERSON_ID, GOOGLE_ISSUERS)]


def test_google_link_status_rejects_person_and_tenant_selectors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, identity_type = _client(monkeypatch, [(PERSON_ID, GOOGLE_ISSUERS[0])])

    for selector in ("person_id", "tenant_id"):
        response = client.get(
            "/v1/me/google-link",
            params={selector: str(OTHER_PERSON_ID)},
        )

        assert response.status_code == 422
        assert response.json()["code"] == "domain_rejected"
    assert identity_type.instances[0].repository.calls == []


def test_google_link_status_requires_the_existing_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, identity_type = _client(monkeypatch, [(PERSON_ID, GOOGLE_ISSUERS[0])])
    client.cookies.clear()

    response = client.get("/v1/me/google-link")

    assert response.status_code == 401
    assert response.json()["code"] == "authentication_required"
    assert identity_type.instances == []


def test_existing_me_response_shape_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _identity_type = _client(monkeypatch, [(PERSON_ID, GOOGLE_ISSUERS[0])])

    response = client.get("/v1/me")

    assert response.status_code == 200
    assert set(response.json()) == {
        "person_id",
        "email",
        "display_name",
        "email_verified_at",
        "selected_tenant_id",
        "membership_role",
        "permissions",
    }
    assert response.json()["person_id"] == str(PERSON_ID)


class _SyncScalarSession:
    def __init__(self, session: Session) -> None:
        self._session = session

    async def scalar(self, statement: object) -> object:
        return self._session.scalar(cast(Any, statement))


@pytest.mark.asyncio
async def test_repository_google_issuer_query_is_person_scoped_and_exact() -> None:
    engine = create_engine("sqlite:///:memory:")
    cast(Any, Person.__table__).create(engine)
    cast(Any, ProviderIdentity.__table__).create(engine)
    try:
        with Session(engine) as database:
            database.execute(
                insert(Person),
                [
                    {"id": PERSON_ID, "email": "person@example.com"},
                    {"id": OTHER_PERSON_ID, "email": "other@example.com"},
                    {"id": THIRD_PERSON_ID, "email": "third@example.com"},
                ],
            )
            database.execute(
                insert(ProviderIdentity),
                [
                    {
                        "id": UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
                        "person_id": PERSON_ID,
                        "issuer": "accounts.google.com",
                        "subject": "person-bare",
                    },
                    {
                        "id": UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
                        "person_id": PERSON_ID,
                        "issuer": "https://accounts.google.com",
                        "subject": "person-url",
                    },
                    {
                        "id": UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
                        "person_id": OTHER_PERSON_ID,
                        "issuer": "accounts.google.invalid",
                        "subject": "other-unknown",
                    },
                    {
                        "id": UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd"),
                        "person_id": THIRD_PERSON_ID,
                        "issuer": "accounts.google.com",
                        "subject": "third-bare",
                    },
                ],
            )
            database.commit()

            repository = AsyncSqlAlchemyIdentityRepository(cast(Any, _SyncScalarSession(database)))
            assert await repository.has_provider_identity_for_issuers(PERSON_ID, GOOGLE_ISSUERS)
            assert not await repository.has_provider_identity_for_issuers(
                OTHER_PERSON_ID, GOOGLE_ISSUERS
            )
            assert await repository.has_provider_identity_for_issuers(
                THIRD_PERSON_ID, GOOGLE_ISSUERS
            )
            assert not await repository.has_provider_identity_for_issuers(
                UUID("66666666-6666-4666-8666-666666666666"), GOOGLE_ISSUERS
            )
    finally:
        engine.dispose()
