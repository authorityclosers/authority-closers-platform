from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import ac_platform.http.auth as auth_module
from ac_platform.application.settings import Settings
from ac_platform.http.auth import (
    AuthenticatedTransaction,
    install_identity_http,
)
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.models import Person, PersonStatus
from ac_platform.kernel.authz import ActorContext

PERSON_ID = UUID("11111111-1111-4111-8111-111111111111")
TENANT_ID = UUID("22222222-2222-4222-8222-222222222222")
SESSION_ID = UUID("33333333-3333-4333-8333-333333333333")
CURRENT_VERSION = "current-learner-document-v2"
OLD_VERSION = "old-learner-document-v1"


class _FakeScalars:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return self._values


class _FakeDatabase:
    def __init__(self, person: Person) -> None:
        self.person = person
        self.audit_events: list[object] = []

    async def scalar(self, _statement: object) -> Person:
        return self.person

    async def scalars(self, _statement: object) -> _FakeScalars:
        return _FakeScalars(self.audit_events)


class _FakeAuditRepository:
    def __init__(self, database: _FakeDatabase) -> None:
        self.database = database

    async def append(self, **kwargs: object) -> object:
        event = SimpleNamespace(
            payload=dict(cast(dict[str, object], kwargs["payload"])),
            occurred_at=cast(datetime, kwargs["now"]),
        )
        self.database.audit_events.append(event)
        return event


def _settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+psycopg://unused:unused@localhost/unused",
        database_migrator_url="postgresql+psycopg://unused:unused@localhost/unused",
        session_token_pepper="test-session-token-pepper-that-is-long-enough",  # noqa: S106
        oauth_transaction_secret="test-route-transaction-signing-key-long-enough",  # noqa: S106
        public_app_url="https://app.authorityclosers.test",
        admin_app_url="https://admin.authorityclosers.test",
        api_url="https://api.authorityclosers.test",
        learner_consent_version=CURRENT_VERSION,
        public_learner_tenant_id=TENANT_ID,
        operations_tenant_id=UUID("44444444-4444-4444-8444-444444444444"),
    )


def _person(*, version: str | None, verified: bool = True) -> Person:
    now = datetime(2026, 9, 13, 10, tzinfo=UTC)
    return Person(
        id=PERSON_ID,
        email="learner@example.com",
        status=PersonStatus.ACTIVE.value,
        email_verified_at=now if verified else None,
        consent_version=version,
        consented_at=now if version else None,
        revision=4,
        created_at=now,
        updated_at=now,
    )


def _client(
    person: Person,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, _FakeDatabase]:
    database = _FakeDatabase(person)
    monkeypatch.setattr(auth_module, "AuditRepository", _FakeAuditRepository)
    app = FastAPI()
    register_problem_handlers(app)
    require_actor = install_identity_http(
        app,
        settings=_settings(),
        sessions=cast(Any, lambda: None),
    )

    async def override_actor(_request: Request):
        yield AuthenticatedTransaction(
            database=cast(Any, database),
            identity=cast(Any, None),
            resolved=SimpleNamespace(
                actor=ActorContext(
                    person_id=PERSON_ID,
                    session_id=SESSION_ID,
                    tenant_id=TENANT_ID,
                )
            ),
            token="s" * 43,  # noqa: S105
        )

    app.dependency_overrides[require_actor] = override_actor
    return TestClient(app, base_url="https://app.authorityclosers.test"), database


def test_renewal_uses_server_version_and_appends_prior_projection_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, database = _client(_person(version=OLD_VERSION), monkeypatch)

    response = client.post(
        "/v1/me/consent/renew",
        headers={"Origin": "https://app.authorityclosers.test"},
        json={"accepted": True},
    )

    assert response.status_code == 200
    assert response.json()["current_version"] == CURRENT_VERSION
    assert response.json()["replayed"] is False
    assert database.person.consent_version == CURRENT_VERSION
    assert len(database.audit_events) == 1
    assert database.audit_events[0].payload == {
        "consent_version": CURRENT_VERSION,
        "previous_consent_version": OLD_VERSION,
        "previous_consented_at": "2026-09-13T10:00:00+00:00",
        "explicit_acceptance": True,
        "age_attestation": "18_plus_learner_declaration",
        "terms_path": "/terms",
        "privacy_path": "/privacy",
    }


def test_current_consent_get_is_current_and_repeated_acceptance_replays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, database = _client(_person(version=CURRENT_VERSION), monkeypatch)

    assert client.get("/v1/me/consent").json()["status"] == "current"
    first = client.post(
        "/v1/me/consent/renew",
        headers={"Origin": "https://app.authorityclosers.test"},
        json={"accepted": True},
    )
    second = client.post(
        "/v1/me/consent/renew",
        headers={"Origin": "https://app.authorityclosers.test"},
        json={"accepted": True},
    )

    assert first.status_code == second.status_code == 200
    assert second.json()["replayed"] is True
    assert len(database.audit_events) == 1


def test_renewal_rejects_client_version_tampering_and_unverified_people(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, database = _client(_person(version=OLD_VERSION), monkeypatch)
    tampered = client.post(
        "/v1/me/consent/renew",
        headers={"Origin": "https://app.authorityclosers.test"},
        json={"accepted": True, "consent_version": "attacker-version"},
    )
    assert tampered.status_code == 422
    assert database.person.consent_version == OLD_VERSION
    assert database.audit_events == []

    unverified_client, unverified_database = _client(
        _person(version=OLD_VERSION, verified=False),
        monkeypatch,
    )
    denied = unverified_client.post(
        "/v1/me/consent/renew",
        headers={"Origin": "https://app.authorityclosers.test"},
        json={"accepted": True},
    )
    assert denied.status_code == 403
    assert unverified_database.person.consent_version == OLD_VERSION
    assert unverified_database.audit_events == []


def test_renewal_requires_authentication() -> None:
    app = FastAPI()
    register_problem_handlers(app)
    install_identity_http(
        app,
        settings=_settings(),
        sessions=cast(Any, lambda: None),
    )
    response = TestClient(app, base_url="https://app.authorityclosers.test").post(
        "/v1/me/consent/renew",
        headers={"Origin": "https://app.authorityclosers.test"},
        json={"accepted": True},
    )
    assert response.status_code == 401
