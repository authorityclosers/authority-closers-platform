from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy.dialects import postgresql

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence import admin_recordings
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.http.conversation_admin import install_conversation_admin_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.kernel.authz import ActorContext

OPS_TENANT = UUID("f5386fc3-033d-4e75-a333-7774381cb4d5")
PUBLIC_TENANT = UUID("206ccee8-a246-433b-b6d3-78eb21592a5c")
UNRELATED_TENANT = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def all(self) -> list[Any]:
        return self.rows


class _Database:
    def __init__(self, responses: list[list[Any]]) -> None:
        self.responses = responses
        self.statements: list[Any] = []

    async def scalars(self, statement: Any) -> _Result:
        self.statements.append(statement)
        return _Result(self.responses.pop(0))


def _recording(
    tenant_id: UUID, person_id: UUID, created_at: datetime, *, recording_id: UUID | None = None
) -> Any:
    return SimpleNamespace(
        id=recording_id or uuid4(),
        tenant_id=tenant_id,
        person_id=person_id,
        source_sha256="a" * 64,
        source_bytes=12_000,
        content_type="audio/ogg",
        source_revision=1,
        state="ready",
        created_at=created_at,
        generation=1,
    )


def _public_page_responses(
    recording: Any, processor_id: UUID, *, run_id: UUID, quote_id: UUID
) -> list[list[Any]]:
    created_at = recording.created_at + timedelta(seconds=1)
    second_run_id, third_run_id = uuid4(), uuid4()
    second_quote_id, third_quote_id = uuid4(), uuid4()
    plan_created_at = recording.created_at + timedelta(seconds=10)
    guest = SimpleNamespace(
        recording_id=recording.id,
        tenant_id=PUBLIC_TENANT,
        usage_id=uuid4(),
    )
    usage = SimpleNamespace(
        id=guest.usage_id,
        tenant_id=PUBLIC_TENANT,
        person_id=None,
        visitor_id=uuid4(),
        reserved_seconds=37,
    )
    run = SimpleNamespace(
        id=run_id,
        recording_id=recording.id,
        tenant_id=PUBLIC_TENANT,
        state="running",
        generation=1,
        recipe_revision="audioatlas-16000-v1",
        created_at=created_at,
        completed_at=None,
    )
    plan = SimpleNamespace(
        id=uuid4(),
        recording_id=recording.id,
        tenant_id=PUBLIC_TENANT,
        state="held",
        generation=1,
        created_at=plan_created_at,
        erased_at=None,
    )
    first_task = SimpleNamespace(
        run_id=run_id,
        recording_id=recording.id,
        tenant_id=PUBLIC_TENANT,
        person_id=processor_id,
        quote_id=quote_id,
        stage="C2",
        generation=1,
        created_at=created_at,
        erased_at=None,
    )
    second_task = SimpleNamespace(
        run_id=second_run_id,
        recording_id=recording.id,
        tenant_id=PUBLIC_TENANT,
        person_id=processor_id,
        quote_id=second_quote_id,
        stage="C4",
        generation=1,
        created_at=recording.created_at + timedelta(seconds=11),
        erased_at=None,
    )
    third_task = SimpleNamespace(
        run_id=third_run_id,
        recording_id=recording.id,
        tenant_id=PUBLIC_TENANT,
        person_id=processor_id,
        quote_id=third_quote_id,
        stage="C5",
        generation=1,
        created_at=recording.created_at + timedelta(seconds=12),
        erased_at=None,
    )
    scope_id = uuid4()
    quote = SimpleNamespace(
        id=quote_id,
        tenant_id=PUBLIC_TENANT,
        budget_scope_id=scope_id,
        quote={"max_cost_paise": 720},
    )
    second_quote = SimpleNamespace(
        id=second_quote_id,
        tenant_id=PUBLIC_TENANT,
        budget_scope_id=scope_id,
        quote={"max_cost_paise": 720},
    )
    third_quote = SimpleNamespace(
        id=third_quote_id,
        tenant_id=PUBLIC_TENANT,
        budget_scope_id=scope_id,
        quote={"max_cost_paise": 720},
    )
    stage_authorizations = [
        SimpleNamespace(plan_id=plan.id, quote_id=second_quote_id, tenant_id=PUBLIC_TENANT),
        SimpleNamespace(plan_id=plan.id, quote_id=third_quote_id, tenant_id=PUBLIC_TENANT),
    ]
    minute = SimpleNamespace(
        tenant_id=PUBLIC_TENANT,
        person_id=processor_id,
        snapshot={},
    )
    checkpoint = SimpleNamespace(
        recording_id=recording.id,
        tenant_id=PUBLIC_TENANT,
        stage="C1",
        payload={"media_duration_ms": 12_000},
        created_at=created_at,
        id=uuid4(),
    )
    return [
        [guest],
        [usage],
        [],
        [],
        [run],
        [plan],
        [first_task, second_task, third_task],
        stage_authorizations,
        [quote, second_quote, third_quote],
        [SimpleNamespace(scope_id=scope_id, snapshot={})],
        [minute],
        [checkpoint],
        [],
    ]


def _direct_page_responses(recording: Any) -> list[list[Any]]:
    return [
        [recording],
        [],
        [],
        [SimpleNamespace(id=recording.person_id)],
        [],
        [],
        [],
        [],
        [],
        [],
    ]


@pytest.mark.asyncio
async def test_admin_recordings_http_maps_public_guest_rows_and_paginates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 9, 14, 12, 30, tzinfo=UTC)
    processor_id = uuid4()
    public_recording = _recording(PUBLIC_TENANT, processor_id, now)
    operations_recording = _recording(OPS_TENANT, uuid4(), now - timedelta(seconds=1))
    unrelated_recording = _recording(UNRELATED_TENANT, uuid4(), now - timedelta(seconds=2))
    run_id, quote_id = uuid4(), uuid4()
    public_page_responses = _public_page_responses(
        public_recording, processor_id, run_id=run_id, quote_id=quote_id
    )
    database = _Database(
        [
            [public_recording, operations_recording, unrelated_recording],
            *public_page_responses,
        ]
    )

    fake_quote = SimpleNamespace(max_cost_paise=720)
    fake_reservations = [
        SimpleNamespace(
            reservation_id=str(task.run_id),
            state="settled",
            quote=SimpleNamespace(max_cost_paise=720),
            settlement=SimpleNamespace(actual_paise=410),
        )
        for task in public_page_responses[6]
    ]
    monkeypatch.setattr(
        admin_recordings.Quote,
        "from_dict",
        classmethod(lambda _cls, _value: fake_quote),
    )
    monkeypatch.setattr(
        admin_recordings.BudgetAccount,
        "from_dict",
        classmethod(lambda _cls, _value: SimpleNamespace(reservations=fake_reservations)),
    )
    monkeypatch.setattr(
        admin_recordings.MinuteAccount,
        "from_dict",
        classmethod(lambda _cls, _value: SimpleNamespace(reservations=fake_reservations)),
    )

    async def admit(_self: ConversationProviderAdmin, _actor: ActorContext) -> None:
        return None

    monkeypatch.setattr(ConversationProviderAdmin, "admit", admit)
    actor = ActorContext(uuid4(), uuid4(), OPS_TENANT, frozenset({"admin_surface"}))
    resolved = ResolvedActorContext(
        actor=actor,
        membership_role="admin",
        person_revision=1,
        session_revision=1,
    )

    async def require_actor(_request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        yield AuthenticatedTransaction(
            database=cast(Any, database),
            identity=cast(Any, object()),
            resolved=resolved,
            token=str(uuid4()),
        )

    settings = Settings(
        _env_file=None,
        environment="test",
        public_app_url="https://learner.test",
        admin_app_url="https://admin.test",
        coach_app_url="https://coach.test",
        api_url="https://api.test",
        operations_tenant_id=OPS_TENANT,
        public_learner_tenant_id=PUBLIC_TENANT,
    )
    application = FastAPI()
    register_problem_handlers(application)
    install_conversation_admin_http(
        application,
        settings=settings,
        require_actor=require_actor,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="https://admin.test"
    ) as client:
        response = await client.get("/v1/admin/conversation/recordings?limit=1&q=Guest")
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["id"] == str(public_recording.id)
    assert item["owner"] == {
        "kind": "guest",
        "label": "Guest upload",
        "person_id": None,
        "display_name": None,
        "email": None,
        "claimed": False,
    }
    assert item["status"] == "held"
    assert item["latest_run"]["state"] == "running"
    assert item["processing_plan"]["state"] == "held"
    assert item["cost"] == {
        "currency": "INR",
        "scope": "recording_total",
        "reservation_paise": 2160,
        "estimate_paise": 2160,
        "actual_paise": 1230,
        "reservation_state": "settled",
        "actual_state": "settled",
    }
    assert body["next_cursor"]

    compiled = database.statements[0].compile(dialect=postgresql.dialect())
    tenant_lists = [value for value in compiled.params.values() if isinstance(value, list)]
    assert any(set(values) == {OPS_TENANT, PUBLIC_TENANT} for values in tenant_lists)
    assert UNRELATED_TENANT not in set(
        next(values for values in tenant_lists if isinstance(values, list))
    )
