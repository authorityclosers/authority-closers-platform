"""Admin routes use the composed Personal/organisation set before reading evidence."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.admin_reports import AdminConversationReports
from ac_platform.conversation_intelligence.application import ConversationNotFound
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.intake import IntakePolicy
from ac_platform.conversation_intelligence.models import ConversationRecording, ConversationRun
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.conversation_intelligence.recovery_models import ConversationRetainedC5Version
from ac_platform.conversation_intelligence.retained_c5_recovery import RetainedC5RecoveryService
from ac_platform.conversation_intelligence.review_service import ConversationReviewService
from ac_platform.conversation_intelligence.storage import PrivateLocalRecordingStorage
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.http.conversation_admin import install_conversation_admin_http
from ac_platform.http.conversation_intake import ConversationIntakeRuntime
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.kernel.authz import ActorContext

OPS, PERSONAL, ORGANISATION, UNAPPROVED = (UUID(int=index) for index in range(1, 5))
NOW = datetime(2026, 10, 4, tzinfo=UTC)


class _Database:
    def __init__(self) -> None:
        self.statements: list[Any] = []
        self.recordings = [
            SimpleNamespace(
                id=uuid4(),
                tenant_id=tenant,
                person_id=uuid4(),
                created_at=NOW,
                source_sha256="a" * 64,
                source_bytes=12000,
                content_type="audio/ogg",
                source_revision=1,
                state="ready",
                generation=1,
            )
            for tenant in (PERSONAL, ORGANISATION, UNAPPROVED, OPS)
        ]
        self.runs = [
            SimpleNamespace(
                id=uuid4(),
                tenant_id=row.tenant_id,
                recording_id=row.id,
                person_id=row.person_id,
                state="completed",
                generation=1,
                recipe_revision="fictional-v1",
                created_at=NOW,
                completed_at=NOW,
            )
            for row in self.recordings
        ]

    def rows(self, statement: Any) -> list[Any]:
        self.statements.append(statement)
        model = statement.column_descriptions[0]["entity"]
        rows = (
            self.recordings
            if model is ConversationRecording
            else self.runs
            if model is ConversationRun
            else []
        )
        for name, value in statement.compile(dialect=postgresql.dialect()).params.items():
            field = name.rsplit("_", 1)[0]
            if field in {"tenant_id", "id", "recording_id"}:
                rows = (
                    [row for row in rows if getattr(row, field) in value]
                    if isinstance(value, list)
                    else [row for row in rows if getattr(row, field) == value]
                )
        return rows

    async def scalars(self, statement: Any) -> Any:
        return SimpleNamespace(all=lambda: self.rows(statement))

    async def scalar(self, statement: Any) -> Any:
        return next(iter(self.rows(statement)), None)


@pytest.fixture
async def admin_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> AsyncIterator[tuple[httpx.AsyncClient, _Database]]:
    database = _Database()
    actor = ActorContext(uuid4(), uuid4(), OPS, frozenset({"admin_surface"}))
    resolved = ResolvedActorContext(
        actor=actor, membership_role="admin", person_revision=1, session_revision=1
    )

    async def require_actor(_request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        yield AuthenticatedTransaction(
            database=cast(Any, database),
            identity=cast(Any, object()),
            resolved=resolved,
            token=str(uuid4()),
        )

    async def admit(_service: Any, _actor: Any) -> Any:
        return NOW

    async def render(
        _service: Any, _review: Any, _actor: Any, run_id: UUID, _now: Any
    ) -> dict[str, Any]:
        run = next(row for row in database.runs if row.id == run_id)
        return {"run_id": str(run.id), "tenant_id": str(run.tenant_id), "report": {}}

    monkeypatch.setattr(ConversationProviderAdmin, "admit", admit)
    monkeypatch.setattr(ConversationReviewService, "_admin", admit)
    monkeypatch.setattr(AdminConversationReports, "render", render)
    storage = PrivateLocalRecordingStorage(tmp_path / "storage")
    intake = ConversationIntakeRuntime(
        policy=IntakePolicy(
            budget_scope_id=uuid4(),
            tenant_ids=frozenset({ORGANISATION, OPS}),
            authorization_ref="ref:fictional/intake",
            retention_ref="ref:fictional/retention",
        ),
        storage=storage,
        scratch=PrivateLocalRecordingStorage(tmp_path / "scratch"),
    )
    settings = Settings(
        _env_file=None,
        environment="test",
        admin_app_url="https://admin.test",
        operations_tenant_id=OPS,
        public_learner_tenant_id=PERSONAL,
    )
    app = FastAPI()
    register_problem_handlers(app)
    install_conversation_admin_http(
        app,
        settings=settings,
        require_actor=require_actor,
        intake=intake,
        recovery_storage=storage if getattr(request, "param", True) else None,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://admin.test"
    ) as client:
        yield client, database


@pytest.mark.parametrize("admin_client", [True, False], indirect=True)
async def test_admin_lists_and_reports_only_personal_and_approved_organisations(
    admin_client,
    request: pytest.FixtureRequest,
) -> None:
    client, database = admin_client
    response = await client.get("/v1/admin/conversation/recordings")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items", "next_cursor"}
    assert {item["id"] for item in body["items"]} == {
        str(row.id) for row in database.recordings[:2]
    }
    assert all(
        item["duration"]["seconds"] is None and item["cost"]["actual_paise"] is None
        for item in body["items"]
    )
    page_queries = len(database.statements)
    database.recordings.append(SimpleNamespace(**{**vars(database.recordings[1]), "id": uuid4()}))
    database.statements.clear()
    assert (await client.get("/v1/admin/conversation/recordings")).status_code == 200
    assert len(database.statements) == page_queries  # no per-recording or per-tenant reads
    for run in database.runs:
        response = await client.get(f"/v1/admin/conversation/runs/{run.id}/report")
        assert response.status_code == (200 if run.tenant_id in {PERSONAL, ORGANISATION} else 404)
        if response.status_code == 200:
            assert response.json()["tenant_id"] == str(run.tenant_id)
    for statement in database.statements:
        params = statement.compile(dialect=postgresql.dialect()).params
        if "tenant_id_1" in params:
            assert set(params["tenant_id_1"]) == {PERSONAL, ORGANISATION}
    recovery_enabled = any(
        statement.column_descriptions[0]["entity"] is ConversationRetainedC5Version
        for statement in database.statements
    )
    assert recovery_enabled == request.node.callspec.params["admin_client"]


@pytest.mark.parametrize("endpoint", ["revalidate", "correct"])
async def test_retained_fix_routes_use_the_same_tenant_scope(
    admin_client, monkeypatch, endpoint
) -> None:
    client, database = admin_client

    async def revalidate(service, actor, run_id, **kwargs):
        # Exercise the actual run-scope predicate without provider or storage work.
        await service._admin_admit(actor)
        run = await service.database.scalar(
            select(ConversationRun).where(
                ConversationRun.id == run_id,
                ConversationRun.tenant_id.in_(service.recording_tenant_ids),
            )
        )
        if run is None:
            raise ConversationNotFound("Run not found.")
        assert (kwargs.get("correction") is not None) == (endpoint == "correct")
        return {"run_id": str(run_id)}

    monkeypatch.setattr(RetainedC5RecoveryService, "revalidate", revalidate)
    payload = {"original_raw_sha256": "a" * 64}
    if endpoint == "correct":
        corrections = [
            {
                "path": "/summary",
                "old_sha256": "b" * 64,
                "new_text": "Fictional correction",
                "source_segment_ids": ["s1"],
                "rationale": "Fictional source-bound correction",
            }
        ]
        payload.update(corrections=corrections, correction_payload_sha256=content_hash(corrections))
    for run in database.runs:
        response = await client.post(
            f"/v1/admin/conversation/runs/{run.id}/retained-c5/{endpoint}",
            json=payload,
            headers={"Origin": "https://admin.test", "Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == (
            201 if run.tenant_id in {PERSONAL, ORGANISATION} else 404
        ), response.text
