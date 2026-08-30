from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import ac_platform.http.certificates as certificates_module
from ac_platform.certificates.services import (
    CertificateEventData,
    CertificateEventType,
    CompletionSnapshot,
    CourseCompletionCertificateData,
    ModuleCompletion,
)
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.http.certificates import install_certificate_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.kernel.authz import ActorContext

NOW = datetime(2026, 8, 30, 12, tzinfo=UTC)


class _Database:
    def __init__(self) -> None:
        self.run_sync_calls = 0

    async def run_sync(self, operation: Any) -> Any:
        self.run_sync_calls += 1
        return operation(SimpleNamespace())


class _CertificateStore:
    def __init__(
        self,
        certificate: CourseCompletionCertificateData,
        snapshot: CompletionSnapshot,
        event: CertificateEventData,
    ) -> None:
        self.certificate = certificate
        self.snapshot = snapshot
        self.event = event
        self.looked_up_ids: list[UUID] = []

    def get_certificate_by_id(self, certificate_id: UUID) -> CourseCompletionCertificateData | None:
        self.looked_up_ids.append(certificate_id)
        return self.certificate if certificate_id == self.certificate.id else None

    def get_snapshot(self, snapshot_id: UUID) -> CompletionSnapshot | None:
        return self.snapshot if snapshot_id == self.snapshot.id else None

    def get_latest_event(self, certificate_id: UUID) -> CertificateEventData | None:
        return self.event if certificate_id == self.certificate.id else None

    def get_event_by_id(self, _event_id: UUID) -> CertificateEventData | None:
        return None


def _seed(
    *,
    tenant_id: UUID,
    person_id: UUID,
) -> tuple[CourseCompletionCertificateData, CompletionSnapshot, CertificateEventData]:
    enrollment_id = uuid4()
    program_id = uuid4()
    program_version_id = uuid4()
    module_id = uuid4()
    activity_id = uuid4()
    module = ModuleCompletion(
        module_id=module_id,
        prerequisite_module_ids=(),
        required_activity_ids=(activity_id,),
        completed_activity_ids=(activity_id,),
        prerequisites_satisfied=True,
        is_complete=True,
    )
    snapshot = CompletionSnapshot(
        tenant_id=tenant_id,
        person_id=person_id,
        enrollment_id=enrollment_id,
        program_id=program_id,
        program_version_id=program_version_id,
        predicate_version="g1-v1",
        required_activity_ids=(activity_id,),
        completed_activity_ids=(activity_id,),
        module_results=(module,),
        required_activity_count=1,
        completed_activity_count=1,
        is_complete=True,
        captured_at=NOW,
        program_scope="tenant",
        program_tenant_id=tenant_id,
        program_owner_key=tenant_id,
    )
    certificate = CourseCompletionCertificateData(
        id=uuid4(),
        tenant_id=tenant_id,
        person_id=person_id,
        enrollment_id=enrollment_id,
        program_id=program_id,
        program_version_id=program_version_id,
        program_scope="tenant",
        program_tenant_id=tenant_id,
        program_owner_key=tenant_id,
        certificate_type="course-completion",
        original_completion_snapshot_id=snapshot.id,
        issued_at=NOW,
        created_at=NOW,
        idempotency_key="issued-by-test",
    )
    event = CertificateEventData(
        id=uuid4(),
        certificate_id=certificate.id,
        tenant_id=tenant_id,
        person_id=person_id,
        enrollment_id=enrollment_id,
        program_id=program_id,
        program_version_id=program_version_id,
        program_scope="tenant",
        program_tenant_id=tenant_id,
        program_owner_key=tenant_id,
        event_type=CertificateEventType.ISSUED,
        completion_snapshot_id=snapshot.id,
        supersedes_event_id=None,
        actor_person_id=None,
        reason=None,
        provenance={"source": "unit-test"},
        occurred_at=NOW,
        idempotency_key="issued-by-test",
        sequence_no=1,
    )
    return certificate, snapshot, event


@pytest.fixture
def harness(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, ActorContext, _Database, _CertificateStore, dict[str, ActorContext]]:
    tenant_id = uuid4()
    actor = ActorContext(person_id=uuid4(), session_id=uuid4(), tenant_id=tenant_id)
    certificate, snapshot, event = _seed(tenant_id=tenant_id, person_id=actor.person_id)
    database = _Database()
    store = _CertificateStore(certificate, snapshot, event)
    monkeypatch.setattr(
        certificates_module,
        "SqlAlchemyCertificateRepository",
        lambda _database: store,
    )
    state = {"actor": actor}

    async def require_actor(_request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        current_actor = state["actor"]
        yield AuthenticatedTransaction(
            database=database,  # type: ignore[arg-type]
            identity=cast(Any, object()),
            resolved=ResolvedActorContext(
                actor=current_actor,
                membership_role="learner",
                person_revision=0,
                session_revision=0,
                tenant_revision=0 if current_actor.tenant_id is not None else None,
                membership_revision=0 if current_actor.tenant_id is not None else None,
            ),
            token="opaque-certificate-http-session-token",  # noqa: S106
        )

    application = FastAPI()
    register_problem_handlers(application)
    install_certificate_http(application, require_actor=require_actor)
    return TestClient(application), actor, database, store, state


def test_certificate_read_is_self_scoped_transaction_bound_and_safe(
    harness: tuple[TestClient, ActorContext, _Database, _CertificateStore, dict[str, ActorContext]],
) -> None:
    client, actor, database, store, state = harness
    certificate_id = store.certificate.id

    response = client.get(f"/v1/certificates/{certificate_id}")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert database.run_sync_calls == 1
    assert store.looked_up_ids == [certificate_id]
    assert state["actor"] is actor
    payload = response.json()
    assert set(payload) == {
        "id",
        "certificate_type",
        "program_id",
        "program_version_id",
        "issued_at",
        "status",
        "completion",
    }
    assert payload["status"] == "issued"
    assert payload["completion"] == {
        "predicate_version": "g1-v1",
        "required_activity_count": 1,
        "completed_activity_count": 1,
        "is_complete": True,
        "captured_at": "2026-08-30T12:00:00Z",
    }
    assert not {
        "tenant_id",
        "person_id",
        "enrollment_id",
        "provenance",
        "actor_person_id",
        "request_digest",
    }.intersection(payload)


@pytest.mark.parametrize("scope", ["person", "tenant"])
def test_certificate_read_rejects_cross_scope_actor(
    harness: tuple[TestClient, ActorContext, _Database, _CertificateStore, dict[str, ActorContext]],
    scope: str,
) -> None:
    client, actor, _database, store, state = harness
    state["actor"] = replace(
        actor,
        person_id=uuid4() if scope == "person" else actor.person_id,
        tenant_id=uuid4() if scope == "tenant" else actor.tenant_id,
    )

    response = client.get(f"/v1/certificates/{store.certificate.id}")

    assert response.status_code == 403
    assert response.json()["code"] == "authorization_denied"


def test_guessed_certificate_id_is_not_found(
    harness: tuple[TestClient, ActorContext, _Database, _CertificateStore, dict[str, ActorContext]],
) -> None:
    client, _actor, _database, store, _state = harness

    response = client.get(f"/v1/certificates/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["code"] == "resource_not_found"
    assert store.looked_up_ids[-1] != store.certificate.id


def test_certificate_read_requires_selected_tenant_context(
    harness: tuple[TestClient, ActorContext, _Database, _CertificateStore, dict[str, ActorContext]],
) -> None:
    client, actor, database, store, state = harness
    state["actor"] = replace(actor, tenant_id=None)

    response = client.get(f"/v1/certificates/{store.certificate.id}")

    assert response.status_code == 403
    assert response.json()["code"] == "certificate_tenant_context_required"
    assert database.run_sync_calls == 0
    assert store.looked_up_ids == []


def test_certificate_route_openapi_exposes_only_the_safe_response(
    harness: tuple[TestClient, ActorContext, _Database, _CertificateStore, dict[str, ActorContext]],
) -> None:
    client, _actor, _database, _store, _state = harness

    document = client.app.openapi()
    response_schema = document["components"]["schemas"]["CertificateResponse"]

    assert response_schema["additionalProperties"] is False
    assert "tenant_id" not in response_schema["properties"]
    assert "person_id" not in response_schema["properties"]
    assert document["paths"]["/v1/certificates/{certificate_id}"]["get"]["responses"]["200"]
