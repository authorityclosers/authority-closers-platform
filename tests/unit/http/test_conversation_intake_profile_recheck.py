"""A profile change during source streaming must prevent source binding."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from starlette.requests import Request

import ac_platform.http.conversation_intake as intake_http
from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.intake import IntakePolicy
from ac_platform.http.conversation_intake import (
    ConversationByteTransport,
    ConversationIntakeRuntime,
)
from ac_platform.identity.models import Person
from ac_platform.identity.sales_xray_profile_models import SalesXrayProfile
from ac_platform.kernel.authz import ActorContext

_NOW = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
_PERSON_ID = UUID("11111111-1111-4111-8111-111111111111")
_SESSION_ID = UUID("44444444-4444-4444-8444-444444444444")
_TENANT_ID = UUID("33333333-3333-4333-8333-333333333333")
_RECORDING_ID = UUID("55555555-5555-4555-8555-555555555555")
_QUOTE_ID = UUID("66666666-6666-4666-8666-666666666666")
_DATA = b"original-audio-16"


class _AsyncSessionAdapter:
    def __init__(self, session: Session) -> None:
        self.session = session

    async def scalar(self, statement: object) -> Any:
        return self.session.scalar(statement)  # type: ignore[arg-type]


@pytest.fixture
def profile_database() -> Any:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
    )
    Person.__table__.create(engine)
    SalesXrayProfile.__table__.create(engine)
    session = Session(engine, expire_on_commit=False)
    session.add(
        Person(
            id=_PERSON_ID,
            email="upload-owner@example.test",
            email_verified_at=_NOW,
            display_name="Upload Owner",
            status="active",
        )
    )
    session.add(
        SalesXrayProfile(
            person_id=_PERSON_ID,
            phone_number_e164="+14155550100",
            revision=1,
        )
    )
    session.commit()
    try:
        yield _AsyncSessionAdapter(session), session
    finally:
        session.close()
        SalesXrayProfile.__table__.drop(engine)
        Person.__table__.drop(engine)
        engine.dispose()


def _request(receive: Any) -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "PUT",
            "scheme": "http",
            "path": f"/v1/conversation/recordings/{_RECORDING_ID}/source",
            "raw_path": f"/v1/conversation/recordings/{_RECORDING_ID}/source".encode(),
            "query_string": b"",
            "headers": [
                (b"host", b"localhost"),
                (b"origin", b"http://localhost:3000"),
                (b"content-length", str(len(_DATA)).encode()),
                (b"content-type", b"application/octet-stream"),
            ],
            "client": ("127.0.0.1", 8000),
            "server": ("localhost", 8000),
        },
        receive,
    )


def test_profile_cleared_during_stream_prevents_source_binding_and_closes_scratch(
    profile_database: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async_database, sync_database = profile_database
    actor = ActorContext(
        person_id=_PERSON_ID,
        session_id=_SESSION_ID,
        tenant_id=_TENANT_ID,
    )
    auth = SimpleNamespace(database=async_database, resolved=SimpleNamespace(actor=actor))
    auth_calls = 0

    async def require_actor(_request: Request) -> AsyncIterator[Any]:
        nonlocal auth_calls
        auth_calls += 1
        yield auth

    class _FakeIntake:
        def __init__(self) -> None:
            self.accepted_calls = 0
            self.store_calls = 0
            self.application = self

        async def require_accepted(
            self, _actor: ActorContext, _recording_id: UUID, _quote_id: UUID
        ) -> dict[str, Any]:
            self.accepted_calls += 1
            return {"source_bytes": len(_DATA), "recording_id": str(_RECORDING_ID)}

        async def store_source(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            self.store_calls += 1
            return {"id": str(_RECORDING_ID), "state": "ready"}

    fake_intake = _FakeIntake()
    monkeypatch.setattr(
        ConversationIntakeRuntime,
        "intake",
        lambda _runtime, _app: fake_intake,
    )

    storage_root = tmp_path / "recordings"
    scratch_root = tmp_path / "scratch"
    storage_root.mkdir()
    scratch_root.mkdir()
    storage = SimpleNamespace(root=storage_root, max_bytes=len(_DATA))
    scratch = SimpleNamespace(root=scratch_root, max_bytes=len(_DATA))
    runtime = ConversationIntakeRuntime(
        policy=IntakePolicy(
            budget_scope_id=uuid4(),
            tenant_ids=frozenset({_TENANT_ID}),
            authorization_ref="intake-test-authorization",
            retention_ref="intake-test-retention",
        ),
        storage=storage,
        scratch=scratch,
    )
    settings = Settings(_env_file=None, environment="test")
    transport = ConversationByteTransport(runtime, settings, require_actor)

    receive_calls = 0

    async def receive() -> dict[str, Any]:
        nonlocal receive_calls
        receive_calls += 1
        profile = sync_database.scalar(
            select(SalesXrayProfile).where(SalesXrayProfile.person_id == _PERSON_ID)
        )
        assert profile is not None
        profile.phone_number_e164 = None
        profile.revision += 1
        sync_database.commit()
        return {"type": "http.request", "body": _DATA, "more_body": False}

    original_temporary_file = intake_http.tempfile.TemporaryFile
    scratch_handles: list[Any] = []

    def tracked_temporary_file(*args: Any, **kwargs: Any) -> Any:
        handle = original_temporary_file(*args, **kwargs)
        scratch_handles.append(handle)
        return handle

    monkeypatch.setattr(intake_http.tempfile, "TemporaryFile", tracked_temporary_file)

    with pytest.raises(HTTPException) as caught:
        asyncio.run(transport.accept(_request(receive), _RECORDING_ID, _QUOTE_ID))

    assert caught.value.status_code == 403
    assert auth_calls == 3
    assert receive_calls == 1
    assert fake_intake.accepted_calls == 2
    assert fake_intake.store_calls == 0
    assert len(scratch_handles) == 1
    assert scratch_handles[0].closed is True
