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
from pydantic import ValidationError

from ac_platform.application.settings import Settings
from ac_platform.http import learning as learning_module
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.http.learning import LearningProjectionResponse, install_learning_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.kernel.authz import ActorContext
from ac_platform.learning.services import ActivityState, DraftRevisionConflict


class _Database:
    def __init__(self) -> None:
        self.run_sync_calls = 0

    async def run_sync(self, operation: Any) -> Any:
        self.run_sync_calls += 1
        return operation(self)

    def scalars(self, _statement: Any) -> tuple[Any, ...]:
        return ()


class _ScopeResult:
    def __init__(self, rows: list[tuple[Any, Any, Any]]) -> None:
        self.rows = rows

    def all(self) -> list[tuple[Any, Any, Any]]:
        return self.rows


class _ScopeDatabase:
    def __init__(self, rows: list[tuple[Any, Any, Any]]) -> None:
        self.rows = rows
        self.statement: Any = None

    def execute(self, statement: Any) -> _ScopeResult:
        self.statement = statement
        return _ScopeResult(self.rows)


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
                order=1,
                required=True,
                video_duration_seconds=None,
            ),
            person_id=actor.person_id,
            assigned_reviewer_id=None,
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
        self.store.progress = SimpleNamespace(revision=1)
        return SimpleNamespace(
            id=uuid4(),
            activity_id=kwargs["activity_id"],
            revision=kwargs["expected_revision"] + 1,
            status="saved",
            payload=kwargs["payload"],
            saved_at=datetime(2026, 8, 30, tzinfo=UTC),
        )

    def get(self, **_kwargs: Any) -> Any:
        return None


class _Activities:
    def current_state(self, **_kwargs: Any) -> ActivityState:
        return ActivityState.AVAILABLE


class _Bundle:
    def __init__(self, actor: ActorContext) -> None:
        self.enrollment_program_id = uuid4()
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
            SimpleNamespace(id=uuid4(), program_id=bundle.enrollment_program_id),
            SimpleNamespace(id=bundle.store.access.program_version_id),
            SimpleNamespace(id=activity_id, prompt="Answer the server-owned prompt."),
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


def test_program_scope_uses_exact_enrollment_and_version_identity() -> None:
    tenant_id = uuid4()
    actor = ActorContext(person_id=uuid4(), session_id=uuid4(), tenant_id=tenant_id)
    program_id = uuid4()
    enrollment_id = uuid4()
    version_id = uuid4()
    row = (
        SimpleNamespace(id=enrollment_id),
        SimpleNamespace(id=version_id),
        SimpleNamespace(id=program_id),
    )
    database = _ScopeDatabase([row])

    assert (
        learning_module._scope_for_program(  # noqa: SLF001
            database,  # type: ignore[arg-type]
            actor,
            program_id,
            enrollment_id=enrollment_id,
            program_version_id=version_id,
        )
        == row
    )
    parameters = {
        value for value in database.statement.compile().params.values() if isinstance(value, UUID)
    }
    assert enrollment_id in parameters
    assert version_id in parameters


def test_program_scope_rejects_ambiguous_active_version_enrollments() -> None:
    actor = ActorContext(person_id=uuid4(), session_id=uuid4(), tenant_id=uuid4())
    program_id = uuid4()
    database = _ScopeDatabase(
        [
            (SimpleNamespace(), SimpleNamespace(), SimpleNamespace()),
            (SimpleNamespace(), SimpleNamespace(), SimpleNamespace()),
        ]
    )

    with pytest.raises(learning_module.LearningResourceUnavailable):
        learning_module._scope_for_program(  # noqa: SLF001
            database,  # type: ignore[arg-type]
            actor,
            program_id,
        )


def test_learning_collection_scope_requires_active_entitlement_and_exact_identity() -> None:
    tenant_id = uuid4()
    actor = ActorContext(person_id=uuid4(), session_id=uuid4(), tenant_id=tenant_id)
    enrollment = SimpleNamespace(id=uuid4())
    version = SimpleNamespace(id=uuid4())
    program = SimpleNamespace(id=uuid4())
    database = _ScopeDatabase([(enrollment, version, program)])

    assert learning_module._learner_learning_scopes(  # noqa: SLF001
        database,  # type: ignore[arg-type]
        actor,
        limit=50,
    ) == ((enrollment, version, program),)
    sql = str(database.statement.compile()).lower()
    assert "entitlements" in sql
    assert "entitlements.status" in sql
    parameters = {
        value for value in database.statement.compile().params.values() if isinstance(value, UUID)
    }
    assert tenant_id in parameters
    assert actor.person_id in parameters


def test_learning_course_state_never_turns_an_empty_projection_into_completion() -> None:
    def projection(denominator: int, completed_count: int) -> LearningProjectionResponse:
        return LearningProjectionResponse(
            scope_type="course",
            scope_id=uuid4(),
            program_version="1",
            projection_version="g1-v1",
            denominator=denominator,
            completed_count=completed_count,
            percentage=(completed_count / denominator) if denominator else 0.0,
            predicate="required activities",
            missing_module_ids=[],
            activity_reasons=[],
        )

    assert learning_module._learning_course_state(None) == "unavailable"  # noqa: SLF001
    assert learning_module._learning_course_state(projection(0, 0)) == "unavailable"  # noqa: SLF001
    assert learning_module._learning_course_state(projection(3, 2)) == "in_progress"  # noqa: SLF001
    assert learning_module._learning_course_state(projection(3, 3)) == "completed"  # noqa: SLF001


def test_learning_collection_route_returns_accessible_rows_without_inventing_progress(
    harness: tuple[TestClient, ActorContext, _Database, _Bundle],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, actor, database, _bundle = harness
    enrollment = SimpleNamespace(
        id=uuid4(),
        enrolled_at=datetime(2026, 9, 1, tzinfo=UTC),
        updated_at=datetime(2026, 9, 2, tzinfo=UTC),
    )
    version = SimpleNamespace(
        id=uuid4(),
        program_id=uuid4(),
        version_number=2,
        scope="global",
        owner_key=uuid4(),
    )
    catalog_program = SimpleNamespace(
        slug="owned-course",
        title="Owned course",
    )
    monkeypatch.setattr(
        learning_module,
        "_learner_learning_scopes",
        lambda _database, resolved_actor, *, limit, cursor=None: (
            ((enrollment, version, catalog_program),)
            if resolved_actor is actor and limit == 50 and cursor is None
            else ()
        ),
    )

    response = client.get("/v1/learning")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert database.run_sync_calls == 1
    assert response.json() == {
        "items": [
            {
                "program_id": str(version.program_id),
                "program_version_id": str(version.id),
                "program_slug": "owned-course",
                "program_title": "Owned course",
                "version_number": 2,
                "enrollment_id": str(enrollment.id),
                "enrolled_at": "2026-09-01T00:00:00Z",
                "updated_at": "2026-09-02T00:00:00Z",
                "state": "unavailable",
                "saved_state": "unavailable",
                "projection": None,
            }
        ],
        "next_cursor": None,
        "saved_filter_available": False,
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
    assert response.json()["activity_revision"] == 1
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
    assert response.json()["position"] == 1
    assert response.json()["program_id"] == str(bundle.enrollment_program_id)
    assert response.json()["prompt"] == "Answer the server-owned prompt."
    assert response.json()["allowed_actions"] == ["save_draft"]
    assert response.json()["draft_revision"] == 0
    assert response.json()["draft_payload"] is None


def test_activity_query_reads_an_explicit_catalog_prompt_only(
    harness: tuple[TestClient, ActorContext, _Database, _Bundle],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _actor, _database, bundle = harness
    activity_id = bundle.store.access.activity.id
    monkeypatch.setattr(
        learning_module,
        "_scope_for_activity",
        lambda *_args: (
            SimpleNamespace(id=uuid4(), program_id=bundle.enrollment_program_id),
            SimpleNamespace(id=bundle.store.access.program_version_id),
            SimpleNamespace(id=activity_id, prompt="Use the published question."),
        ),
    )

    response = client.get(f"/v1/activities/{activity_id}")

    assert response.status_code == 200
    assert response.json()["prompt"] == "Use the published question."
    assert response.json()["allowed_actions"] == ["save_draft"]


def test_locked_activity_redacts_prompt_and_discloses_no_actions(
    harness: tuple[TestClient, ActorContext, _Database, _Bundle],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _actor, _database, bundle = harness
    activity_id = bundle.store.access.activity.id
    monkeypatch.setattr(
        learning_module,
        "_scope_for_activity",
        lambda *_args: (
            SimpleNamespace(id=uuid4(), program_id=bundle.enrollment_program_id),
            SimpleNamespace(id=bundle.store.access.program_version_id),
            SimpleNamespace(id=activity_id, prompt="Secret prerequisite-gated prompt."),
        ),
    )
    monkeypatch.setattr(
        bundle.activities,
        "current_state",
        lambda **_kwargs: ActivityState.LOCKED,
    )

    response = client.get(f"/v1/activities/{activity_id}")

    assert response.status_code == 200
    assert response.json()["state"] == "locked"
    assert response.json()["prompt"] is None
    assert response.json()["allowed_actions"] == []
    assert response.json()["draft_payload"] is None


def test_promptless_activity_denies_draft_before_the_learning_service(
    harness: tuple[TestClient, ActorContext, _Database, _Bundle],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _actor, _database, bundle = harness
    activity_id = bundle.store.access.activity.id
    monkeypatch.setattr(
        learning_module,
        "_scope_for_activity",
        lambda *_args: (
            SimpleNamespace(id=uuid4(), program_id=bundle.enrollment_program_id),
            SimpleNamespace(id=bundle.store.access.program_version_id),
            SimpleNamespace(id=activity_id, prompt=None),
        ),
    )

    detail_response = client.get(f"/v1/activities/{activity_id}")

    assert detail_response.status_code == 200
    assert detail_response.json()["prompt"] is None
    assert detail_response.json()["allowed_actions"] == []

    response = client.put(
        f"/v1/activities/{activity_id}/draft",
        json={"payload": {"answer": "invented"}},
        headers=_headers(key="promptless"),
    )

    assert response.status_code == 403
    assert response.json()["code"] == "activity_action_unavailable"
    assert bundle.drafts.calls == []


def test_learning_projection_schema_is_exact_and_forbids_unknown_fields() -> None:
    payload = {
        "scope_type": "program",
        "scope_id": str(uuid4()),
        "program_version": "program-v1",
        "projection_version": "g1-v1",
        "denominator": 1,
        "completed_count": 0,
        "percentage": 0.0,
        "predicate": "all_required_activities_completed",
        "missing_module_ids": [],
        "activity_reasons": [],
    }

    parsed = LearningProjectionResponse.model_validate(payload)
    assert parsed.scope_type == "program"
    assert parsed.model_dump(mode="json")["next_activity_id"] is None
    pointer = uuid4()
    guided = LearningProjectionResponse.model_validate(payload | {"next_activity_id": pointer})
    assert guided.model_dump(mode="json")["next_activity_id"] == str(pointer)
    assert guided.projection_version == payload["projection_version"]
    with pytest.raises(ValidationError):
        LearningProjectionResponse.model_validate(payload | {"next_activity_id": "not-a-uuid"})
    with pytest.raises(ValidationError):
        LearningProjectionResponse.model_validate(payload | {"unexpected": True})
