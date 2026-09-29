"""Fictional HTTP playback follows reference history in the admitted session."""

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import APIRouter, FastAPI, Request

from ac_platform.conversation_intelligence.acquisition_reports import AcquisitionReports
from ac_platform.conversation_intelligence.application import ConversationApplication
from ac_platform.conversation_intelligence.models import ConversationRecording
from ac_platform.conversation_intelligence.review_service import ConversationReviewService
from ac_platform.conversation_intelligence.source_object_models import (
    ConversationSourceObject as Source,
)
from ac_platform.conversation_intelligence.source_object_models import (
    ConversationSourceReference as Reference,
)
from ac_platform.conversation_intelligence.storage import (
    ObjectKey,
    ObjectKind,
    PrivateLocalRecordingStorage,
    SourceAudioKey,
)
from ac_platform.http.conversation_playback import install_playback_route
from ac_platform.http.conversation_reviews import install_conversation_review_http
from ac_platform.http.conversation_submissions import install_submission_http
from tests.unit.http.test_conversation_learner_acquisition import PUBLIC_TENANT, _runtime, _settings


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["legacy", "submission", "reviewer"])
@pytest.mark.parametrize("history", ["none", "live", "released", "missing"])
@pytest.mark.parametrize("range_header", [None, "bytes=2-5", "bytes=999-1000"])
async def test_http_source_reference_routing(tmp_path, monkeypatch, route, history, range_header):
    data = b"fictional retained audio"
    digest, now = hashlib.sha256(data).hexdigest(), datetime.now(UTC)
    recording_id, person_id, source_id = uuid4(), uuid4(), uuid4()
    recording = ConversationRecording(
        id=recording_id,
        tenant_id=PUBLIC_TENANT,
        person_id=person_id,
        source_sha256=digest,
        source_bytes=len(data),
        content_type="audio/wav",
    )
    rows = {
        (ConversationRecording, recording_id): recording,
        (Reference, recording_id): None
        if history == "none"
        else Reference(
            recording_id=recording_id,
            tenant_id=PUBLIC_TENANT,
            person_id=person_id,
            source_object_id=source_id,
            released_at=now if history == "released" else None,
        ),
        (Source, source_id): Source(
            id=source_id,
            tenant_id=PUBLIC_TENANT,
            source_sha256=digest,
            deleted_at=None,
        ),
    }
    db = SimpleNamespace(get=AsyncMock(side_effect=lambda model, key: rows[(model, key)]))
    actor = SimpleNamespace(tenant_id=PUBLIC_TENANT, person_id=person_id)

    async def require_actor(_request: Request):
        yield SimpleNamespace(database=db, resolved=SimpleNamespace(actor=actor), actor=actor)

    descriptor = {
        "id": str(recording_id),
        "tenant_id": str(PUBLIC_TENANT),
        "source_sha256": digest,
        "source_bytes": len(data),
        "content_type": "audio/wav",
    }
    monkeypatch.setattr(ConversationApplication, "get", AsyncMock(return_value=descriptor))
    monkeypatch.setattr(ConversationReviewService, "playback", AsyncMock(return_value=descriptor))
    monkeypatch.setattr(AcquisitionReports, "recording", AsyncMock(return_value=(None, recording)))
    storage = PrivateLocalRecordingStorage(tmp_path / "objects")
    legacy = ObjectKey(PUBLIC_TENANT, recording_id, recording_id, ObjectKind.SOURCE_AUDIO)
    shared = SourceAudioKey(PUBLIC_TENANT, digest)
    storage.put(legacy, [data], expected_sha256=digest)
    if history != "missing":
        storage.put(shared, [data], expected_sha256=digest)
    if history == "live":
        storage.delete(legacy)
    reads, closed = [], []
    original = storage.iter_bytes

    def read(key, **kwargs):
        reads.append(key)
        try:
            yield from original(key, **kwargs)
        finally:
            closed.append(key)

    monkeypatch.setattr(storage, "iter_bytes", read)
    app, router, settings = FastAPI(), APIRouter(), _settings()
    install_playback_route(router, require_actor, storage)
    app.include_router(router)
    runtime = _runtime(tmp_path)
    install_submission_http(
        app,
        settings=settings,
        sessions=None,
        require_actor=require_actor,
        factory=lambda database: SimpleNamespace(
            database=database,
            tenant_id=PUBLIC_TENANT,
            clock=lambda: now,
        ),
        runtime=replace(runtime.intake, storage=storage),
        preflight=runtime.preflight,
    )
    install_conversation_review_http(
        app,
        settings=settings,
        require_actor=require_actor,
        require_reviewer=require_actor,
        storage=storage,
    )
    paths = {
        "legacy": f"/recordings/{recording_id}/source",
        "submission": f"/v1/conversation/acquisition/submissions/{uuid4()}/source",
        "reviewer": f"/v1/reviewer/review-assignments/{uuid4()}/source",
    }
    origin = settings.admin_app_url if route == "reviewer" else settings.public_app_url
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=str(origin)
    ) as client:
        response = await client.get(
            paths[route], headers={"Range": range_header} if range_header else {}
        )
    if range_header == "bytes=999-1000":
        assert response.status_code == 416
        assert response.headers["content-range"] == f"bytes */{len(data)}"
        db.get.assert_not_awaited()
        assert reads == []
    else:
        if route != "submission":
            assert db.get.await_args_list[0].args == (ConversationRecording, recording_id)
        if history in {"released", "missing"}:
            assert response.status_code == 409
            assert response.json() == {"detail": "The retained recording is unavailable."}
        else:
            assert response.status_code == (206 if range_header else 200)
            assert response.content == (data[2:6] if range_header else data)
            assert response.headers["cache-control"] == "private, no-store"
            assert response.headers["accept-ranges"] == "bytes"
            assert response.headers["content-length"] == str(len(response.content))
            if range_header:
                assert response.headers["content-range"] == f"bytes 2-5/{len(data)}"
        assert reads == ([] if history == "released" else [legacy if history == "none" else shared])
    assert closed == reads
