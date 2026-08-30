"""Focused authorization and transaction-boundary tests for the G1 learning adapter."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from ac_platform.application.settings import Settings
from ac_platform.http import learning as learning_module
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.http.learning import install_learning_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.kernel.authz import ActorContext
from ac_platform.learning.services import ActivityState, DraftRevisionConflict


class _Database:
    def __init__(self) -> None:
        self.run_sync_calls = 0

    async def run_sync(self, operation: Any) -> Any:
        self.run_sync_calls += 1
        return operation(SimpleNamespace())


class _Store:
    def __init__(self, actor: ActorContext) -> None:
        self.actor = actor
        self.progress: Any = None
        self.access = SimpleNamespace(
            activity=SimpleNamespace(
                id=uuid4(),
                module_id=uuid4(),
                kind="reflection",
                title="Write the first reflection",
                required=True,
            ),
            program_version_id=uuid4(),
            program=SimpleNamespace(
                id=uuid4(),
                program_version_id=uuid4(),
                program_scope="tenant",
                program_owner_key=actor.tenant_id,
                version="program-v1",
                modules=(),
            ),
            scope=(actor.tenant_id, uuid4(), actor.person_id, uuid4(), uuid4()),
        )

    def resolve_access(self, **kwargs: Any) -> Any:
        assert kwargs["actor"] is self.actor
        assert kwargs["tenant_id"] == self.actor.tenant_id
        assert kwargs["activity_id"] == self.access.activity.id
        return self.access

    def get_progress(self, *_scope: UUID) -> Any:
        return self.progress

    def list_progress(self, **_kwargs: Any) -> tuple[Any, ...]:
        return ()


class _Drafts:
    def __init__(self, store: _Store) -> None:
        self.store = store
        self.calls: list[dict[str, Any]] = []
        self.raise_stale = False

    def save(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.raise_stale:
            raise DraftRevisionConflict(expected_revision=2, actual_revision=3)
        return SimpleNamespace(
            id=uuid4(),
            activity_id=kwargs["activity_id"],
            revision=kwargs["expected_revision"] + 1,
            status="saved",
            payload=kwargs["payload"],
            saved_at=datetime(2026, 8, 30, tzinfo=UTC),
        )


class _Activities:
    def current_state(self, **_kwargs: Any) -> ActivityState:
        return ActivityState.AVAILABLE


class _Bundle:
    def __init__(self, actor: ActorContext) -> None:
        self.store = _Store(actor)
        self.drafts = _Drafts(self.store)
        self.activities = _Activities()


def _settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+psycopg://unused:unused@localhost/unused",
        database_migrator_url="postgresql+psycopg://unused:unused@localhost/unused",
        session_token_pepper="learning-http-session-pepper-long-enough",  # noqa: S106
        oauth_transaction_secret="learning-http-oauth-secret-long-enough",  # noqa: S106
        public_app_url="https://app.authorityclosers.test",
        admin_app_url="https://admin.authorityclosers.test",
        api_url="https://api.authorityclosers.test",
    )


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, ActorContext, _Database, _Bundle]:
    tenant_id = uuid4()
    actor = ActorContext(person_id=uuid4(), session_id=uuid4(), tenant_id=tenant_id)
    database = _Database()
    bundle = _Bundle(actor)

    def scope(_database: Any, _actor: ActorContext, activity_id: UUID) -> tuple[Any, Any, Any]:
        assert _actor is actor
        assert activity_id == bundle.store.access.activity.id
        return (
            SimpleNamespace(id=uuid4()),
            SimpleNamespace(id=bundle.store.access.program_version_id),
            SimpleNamespace(id=activity_id),
        )

    monkeypatch.setattr(learning_module, "_scope_for_activity", scope)
    monkeypatch.setattr(learning_module, "_bundle", lambda *_args, **_kwargs: bundle)

    async def require_actor(_request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        yield AuthenticatedTransaction(
            database=database,  # type: ignore[arg-type]
            identity=SimpleNamespace(),  # type: ignore[arg-type]
            resolved=ResolvedActorContext(
                actor=actor,
                membership_role="learner",
                person_revision=0,
                session_revision=0,
                tenant_revision=0,
                membership_revision=0,
            ),
            token="opaque-learning-session-token",  # noqa: S106
        )

    application = FastAPI()
    register_problem_handlers(application)
    install_learning_http(
        application,
        settings=_settings(),
        require_actor=require_actor,
    )
    return TestClient(application), actor, database, bundle


def _headers(*, etag: str = '"draft-revision-0"', key: str = "draft-1") -> dict[str, str]:
    return {
        "Origin": "https://app.authorityclosers.test",
        "If-Match": etag,
        "Idempotency-Key": key,
    }


def test_draft_uses_only_authenticated_actor_and_existing_transaction(
    harness: tuple[TestClient, ActorContext, _Database, _Bundle],
) -> None:
    client, actor, database, bundle = harness
    activity_id = bundle.store.access.activity.id

    response = client.put(
        f"/v1/activities/{activity_id}/draft",
        json={"payload": {"answer": "first attempt"}},
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["etag"] == '"draft-revision-1"'
    assert database.run_sync_calls == 1
    call = bundle.drafts.calls[0]
    assert call["actor"] is actor
    assert call["tenant_id"] == actor.tenant_id
    assert call["payload"] == {"answer": "first attempt"}


def test_draft_forbids_forged_identity_fields(harness: Any) -> None:
    client, _actor, _database, bundle = harness
    response = client.put(
        f"/v1/activities/{bundle.store.access.activity.id}/draft",
        json={"payload": {}, "person_id": str(uuid4()), "tenant_id": str(uuid4())},
        headers=_headers(),
    )

    assert response.status_code == 422
    assert bundle.drafts.calls == []


def test_mutation_requires_if_match_and_idempotency_key(harness: Any) -> None:
    client, _actor, _database, bundle = harness
    activity_id = bundle.store.access.activity.id

    missing_etag = client.put(
        f"/v1/activities/{activity_id}/draft",
        json={"payload": {}},
        headers={"Origin": "https://app.authorityclosers.test", "Idempotency-Key": "one"},
    )
    missing_key = client.put(
        f"/v1/activities/{activity_id}/draft",
        json={"payload": {}},
        headers={"Origin": "https://app.authorityclosers.test", "If-Match": '"draft-revision-0"'},
    )

    assert missing_etag.status_code == 428
    assert missing_etag.json()["code"] == "if_match_required"
    assert missing_key.status_code == 428
    assert missing_key.json()["code"] == "idempotency_key_required"
    assert bundle.drafts.calls == []


def test_stale_if_match_is_returned_as_domain_conflict(harness: Any) -> None:
    client, _actor, _database, bundle = harness
    bundle.drafts.raise_stale = True

    response = client.put(
        f"/v1/activities/{bundle.store.access.activity.id}/draft",
        json={"payload": {"answer": "stale"}},
        headers=_headers(etag='"draft-revision-2"', key="stale"),
    )

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "draft_revision_conflict"


def test_guessed_activity_id_does_not_reach_learning_service(
    harness: Any, monkeypatch: Any
) -> None:
    client, _actor, _database, bundle = harness
    monkeypatch.setattr(
        learning_module,
        "_scope_for_activity",
        lambda *_args: (_ for _ in ()).throw(
            learning_module.LearningResourceUnavailable("The enrolled activity is unavailable.")
        ),
    )

    response = client.put(
        f"/v1/activities/{uuid4()}/draft",
        json={"payload": {"answer": "not found"}},
        headers=_headers(key="guessed"),
    )

    assert response.status_code == 404
    assert bundle.drafts.calls == []


def test_activity_query_is_protected_and_returns_an_etag(harness: Any) -> None:
    client, _actor, _database, bundle = harness
    response = client.get(f"/v1/activities/{bundle.store.access.activity.id}")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["etag"] == '"activity-revision-0"'
    assert response.json()["state"] == "available"
