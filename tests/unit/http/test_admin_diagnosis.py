from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import ac_platform.http.admin_diagnosis as diagnosis_http
from ac_platform.application.settings import Settings
from ac_platform.http.admin_learning import AdminAuthorizationDenied
from ac_platform.http.problem import register_problem_handlers
from ac_platform.kernel.authz import ActorContext
from ac_platform.learning.admin_diagnosis import (
    DiagnosisPurpose,
    LearnerDiagnosis,
    LearnerLookupCandidate,
    LearnerLookupResult,
)

TENANT_ID = uuid4()
ACTOR_ID = uuid4()
LEARNER_ID = uuid4()
NOW = datetime(2026, 9, 13, 12, tzinfo=UTC)


def _directory_result():
    from ac_platform.learning.admin_directory import (
        DirectoryMember,
        DirectorySummary,
        MemberDirectory,
    )

    return MemberDirectory(
        tenant_id=TENANT_ID,
        tenant_name="Academy",
        page=1,
        page_size=25,
        matching_count=1,
        summary=DirectorySummary(1, 0, 1, 0),
        members=(
            DirectoryMember(
                LEARNER_ID,
                "Owner",
                None,
                "o***@example.test",
                "owner",
                "active",
                "active",
                True,
                NOW,
                0,
            ),
        ),
    )


def test_directory_loads_without_exact_lookup_and_audits_without_search_pii(monkeypatch):
    client, _db = _harness(monkeypatch)
    calls = []

    def listing(database, **kwargs):
        calls.append(kwargs)
        return _directory_result()

    monkeypatch.setattr(diagnosis_http, "list_members", listing)
    response = client.post(
        "/v1/admin/people/directory",
        json={"query": "Owner"},
        headers={"Origin": "https://admin.authorityclosers.test"},
    )
    assert response.status_code == 200
    assert response.json()["members"][0]["membership_role"] == "owner"
    assert "no-store" in response.headers["Cache-Control"]
    assert calls[0]["tenant_id"] == TENANT_ID
    assert "Owner" not in str(FakeAuditRepository.events)
    assert FakeAuditRepository.events[0]["action"] == "audit.admin.people.directory.v1"


@pytest.mark.parametrize(
    "body", [{"tenant_id": str(uuid4())}, {"page_size": 51}, {"role": "superuser"}, {"page": 0}]
)
def test_directory_rejects_client_scope_and_unbounded_reads(monkeypatch, body):
    client, db = _harness(monkeypatch)
    assert client.post("/v1/admin/people/directory", json=body).status_code == 422
    assert db.run_sync_calls == 0


def test_directory_does_not_deliver_private_rows_when_audit_commit_fails(monkeypatch):
    client, _db = _harness(monkeypatch, fail_after_yield=True)
    monkeypatch.setattr(diagnosis_http, "list_members", lambda *_args, **_kw: _directory_result())
    with pytest.raises(RuntimeError, match="transaction commit failed"):
        client.post(
            "/v1/admin/people/directory",
            json={},
            headers={"Origin": "https://admin.authorityclosers.test"},
        )


def test_directory_denies_without_permission_or_from_other_surface(monkeypatch):
    client, db = _harness(monkeypatch)

    async def deny(*args, **kwargs):
        raise AdminAuthorizationDenied("Permission unavailable")

    monkeypatch.setattr(diagnosis_http, "_require_named_admin", deny)
    assert (
        client.post(
            "/v1/admin/people/directory",
            json={},
            headers={"Origin": "https://admin.authorityclosers.test"},
        ).status_code
        == 403
    )
    assert db.run_sync_calls == 0
    assert (
        client.post(
            "/v1/admin/people/directory",
            json={},
            headers={"Origin": "https://app.authorityclosers.test"},
        ).status_code
        == 403
    )


class FakeDatabase:
    def __init__(self) -> None:
        self.run_sync_calls = 0
        self.sync_session = FakeSyncSession()

    async def run_sync(self, operation):
        self.run_sync_calls += 1
        return operation(self.sync_session)


class FakeSyncSession:
    def __init__(self) -> None:
        self.query_calls = 0

    def execute(self, _statement):
        self.query_calls += 1
        raise AssertionError("the test must not issue a database query")

    def scalars(self, _statement):
        self.query_calls += 1
        raise AssertionError("the test must not issue a database query")


class FakeAuditRepository:
    events: list[dict[str, object]] = []

    def __init__(self, _database) -> None:
        pass

    async def append_for_actor(self, actor, **kwargs):
        type(self).events.append({"actor": actor, **kwargs})


def _settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+psycopg://unused:unused@localhost/unused",
        database_migrator_url="postgresql+psycopg://unused:unused@localhost/unused",
        session_token_pepper="admin-diagnosis-http-session-pepper-long-enough",  # noqa: S106
        oauth_transaction_secret="admin-diagnosis-http-oauth-secret-long-enough",  # noqa: S106
        public_app_url="https://app.authorityclosers.test",
        admin_app_url="https://admin.authorityclosers.test",
        api_url="https://api.authorityclosers.test",
    )


def _harness(monkeypatch: pytest.MonkeyPatch, *, fail_after_yield: bool = False):
    actor = ActorContext(
        person_id=ACTOR_ID,
        session_id=uuid4(),
        tenant_id=TENANT_ID,
        permissions=frozenset({"admin_surface", "learner_diagnose"}),
    )
    database = FakeDatabase()
    auth = SimpleNamespace(
        database=database,
        resolved=SimpleNamespace(actor=actor),
    )

    if fail_after_yield:

        async def require_actor(_request: Request):
            yield auth
            raise RuntimeError("transaction commit failed")

    else:

        async def require_actor(_request: Request):
            return auth

    async def require_named_admin(_auth, *, permission, lock=True, program_id=None):
        assert permission == "learner_diagnose"
        assert lock is False
        assert program_id is None
        return actor, TENANT_ID

    monkeypatch.setattr(diagnosis_http, "_require_named_admin", require_named_admin)
    monkeypatch.setattr(diagnosis_http, "AuditRepository", FakeAuditRepository)
    FakeAuditRepository.events = []

    application = FastAPI()
    register_problem_handlers(application)
    diagnosis_http.install_admin_diagnosis_http(
        application,
        settings=_settings(),
        require_actor=require_actor,
    )
    return TestClient(application, base_url="https://admin.authorityclosers.test"), database


def _lookup_result() -> LearnerLookupResult:
    return LearnerLookupResult(
        tenant_id=TENANT_ID,
        redaction_version="admin-learner-v1",
        candidates=(
            LearnerLookupCandidate(
                person_id=LEARNER_ID,
                display_name="Learner One",
                username="learner_one",
                masked_email="l***@example.test",
                membership_status="active",
                membership_role="learner",
            ),
        ),
        truncated=False,
    )


def _diagnosis_result() -> LearnerDiagnosis:
    return LearnerDiagnosis(
        tenant_id=TENANT_ID,
        person_id=LEARNER_ID,
        display_name="Learner One",
        username="learner_one",
        masked_email="l***@example.test",
        purpose=DiagnosisPurpose.LEARNER_SUPPORT.value,
        redaction_version="admin-learner-v1",
        as_of=NOW,
        membership_status="active",
        membership_role="learner",
        enrollments=(),
        truncated=False,
    )


def test_lookup_is_same_origin_redacted_and_audited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, database = _harness(monkeypatch)
    monkeypatch.setattr(
        diagnosis_http,
        "lookup_learners",
        lambda *_args, **_kwargs: _lookup_result(),
    )

    response = client.post(
        "/v1/admin/learners/lookup",
        json={"query": "  LEARNER_ONE ", "purpose": "learner_support"},
        headers={"Origin": "https://admin.authorityclosers.test"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert payload["tenant_id"] == str(TENANT_ID)
    assert payload["candidates"][0]["username"] == "learner_one"
    assert payload["candidates"][0]["masked_email"] == "l***@example.test"
    assert "learner@example.test" not in response.text
    assert database.run_sync_calls == 1
    assert len(FakeAuditRepository.events) == 1
    event = FakeAuditRepository.events[0]
    assert event["action"] == "audit.admin.learner.lookup.v1"
    assert event["resource_id"] == TENANT_ID
    assert event["payload"] == {
        "purpose": "learner_support",
        "redaction_version": "admin-learner-v1",
        "result_count": 1,
    }


def test_lookup_rejects_extra_input_and_raw_identifier_without_querying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, database = _harness(monkeypatch)

    extra = client.post(
        "/v1/admin/learners/lookup",
        json={
            "query": "learner_one",
            "purpose": "learner_support",
            "tenant_id": str(uuid4()),
        },
        headers={"Origin": "https://admin.authorityclosers.test"},
    )
    raw = client.post(
        "/v1/admin/learners/lookup",
        json={
            "query": str(LEARNER_ID),
            "purpose": "learner_support",
        },
        headers={"Origin": "https://admin.authorityclosers.test"},
    )
    lookup_query = client.post(
        "/v1/admin/learners/lookup?tenant_id=" + str(uuid4()),
        json={"query": "learner_one", "purpose": "learner_support"},
        headers={"Origin": "https://admin.authorityclosers.test"},
    )
    duplicate_purpose = client.get(
        f"/v1/admin/learners/{LEARNER_ID}/diagnosis?purpose=learner_support&purpose=learner_support"
    )

    assert extra.status_code == 422
    assert raw.status_code == 422
    assert lookup_query.status_code == 422
    assert duplicate_purpose.status_code == 422
    assert database.run_sync_calls == 1
    assert database.sync_session.query_calls == 0
    assert FakeAuditRepository.events == []


def test_diagnosis_is_redacted_and_audited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _database = _harness(monkeypatch)
    monkeypatch.setattr(
        diagnosis_http,
        "diagnose_learner",
        lambda *_args, **_kwargs: _diagnosis_result(),
    )

    response = client.get(
        f"/v1/admin/learners/{LEARNER_ID}/diagnosis",
        params={"purpose": "learner_support"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert payload["person_id"] == str(LEARNER_ID)
    assert payload["membership_role"] == "learner"
    assert payload["enrollments"] == []
    assert "payload" not in response.text
    assert FakeAuditRepository.events[-1]["action"] == "audit.admin.learner.diagnosed.v1"
    assert FakeAuditRepository.events[-1]["resource_id"] == LEARNER_ID


def test_diagnosis_denies_unknown_target_and_extra_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _database = _harness(monkeypatch)

    def unavailable(*_args, **_kwargs):
        from ac_platform.learning.admin_diagnosis import LearnerDiagnosisUnavailable

        raise LearnerDiagnosisUnavailable("The learner is unavailable in this tenant.")

    monkeypatch.setattr(diagnosis_http, "diagnose_learner", unavailable)
    unknown = client.get(
        f"/v1/admin/learners/{uuid4()}/diagnosis",
        params={"purpose": "learner_support"},
    )
    extra = client.get(
        f"/v1/admin/learners/{LEARNER_ID}/diagnosis",
        params={"purpose": "learner_support", "tenant_id": str(uuid4())},
    )

    assert unknown.status_code == 404
    assert extra.status_code == 422
    assert FakeAuditRepository.events == []


def test_diagnosis_preserves_named_permission_denial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, database = _harness(monkeypatch)

    async def denied(*_args, **_kwargs):
        raise AdminAuthorizationDenied("The actor lacks the learner_diagnose permission.")

    monkeypatch.setattr(diagnosis_http, "_require_named_admin", denied)
    response = client.get(
        f"/v1/admin/learners/{LEARNER_ID}/diagnosis",
        params={"purpose": "learner_support"},
    )

    assert response.status_code == 403
    assert database.run_sync_calls == 0
    assert FakeAuditRepository.events == []


def test_lookup_does_not_leak_private_response_when_audit_append_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _database = _harness(monkeypatch)
    monkeypatch.setattr(
        diagnosis_http,
        "lookup_learners",
        lambda *_args, **_kwargs: _lookup_result(),
    )

    async def audit_failure(*_args, **_kwargs):
        raise RuntimeError("audit append failed")

    monkeypatch.setattr(diagnosis_http, "_append_read_audit", audit_failure)
    client = TestClient(
        client.app, base_url="https://admin.authorityclosers.test", raise_server_exceptions=False
    )
    response = client.post(
        "/v1/admin/learners/lookup",
        json={"query": "learner_one", "purpose": "learner_support"},
        headers={"Origin": "https://admin.authorityclosers.test"},
    )

    assert response.status_code == 500
    assert "l***@example.test" not in response.text
    assert "Learner One" not in response.text


def test_function_scoped_transaction_failure_does_not_leak_private_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _database = _harness(monkeypatch, fail_after_yield=True)
    monkeypatch.setattr(
        diagnosis_http,
        "lookup_learners",
        lambda *_args, **_kwargs: _lookup_result(),
    )
    client = TestClient(
        client.app, base_url="https://admin.authorityclosers.test", raise_server_exceptions=False
    )

    response = client.post(
        "/v1/admin/learners/lookup",
        json={"query": "learner_one", "purpose": "learner_support"},
        headers={"Origin": "https://admin.authorityclosers.test"},
    )

    assert response.status_code == 500
    assert "l***@example.test" not in response.text
    assert "Learner One" not in response.text
