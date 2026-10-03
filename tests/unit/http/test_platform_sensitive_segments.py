"""Platform sensitive-segment marks over HTTP (SQLite, real identity and grants).

Fictional transcript only. The sentinel phrase below stands in for sensitive
content: every assertion proves it never leaves the database through this API.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session

from ac_platform.audit.models import AuditEvent
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationPermission,
    ConversationRecording,
)
from ac_platform.conversation_intelligence.sensitive_segment_models import (
    ConversationSensitiveSegmentMark,
)
from ac_platform.conversation_intelligence.sensitive_segments_store import effective_marks
from ac_platform.http.auth import install_identity_http
from ac_platform.http.platform_sensitive_segments import install_platform_sensitive_segments_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.http.surfaces import CoachSurfaceMiddleware
from tests.unit.http.test_platform_access import grant
from tests.unit.http.test_workspaces import OTHER_TOKEN, TOKEN, HttpDatabase
from tests.unit.http.test_workspaces import workspace_state as workspace_state

SENTINEL = "zebra-umbrella fictional disclosure"
REVISION = "rev-fictional-c2-" + "a" * 16
OTHER_REVISION = "rev-fictional-c2-" + "b" * 16
REASON = "AUT-520 fixture"
ORIGIN = "https://admin.authorityclosers.test"


def _transcript(revision: str) -> dict[str, Any]:
    texts = {
        "s1": "Thanks for joining the fictional demo today.",
        "s2": f"My {SENTINEL} is nobody's business.",
        "s3": "Let us talk about the fictional widget pricing.",
        "s4": "Sounds good, send the fictional proposal over.",
    }
    return {
        "source_sha256": "0" * 64,
        "revision": revision,
        "timebase_id": "fictional-timebase",
        "segments": [
            {
                "id": segment_id,
                "speaker_id": "A" if index % 2 == 0 else "B",
                "start_ms": index * 1000,
                "end_ms": index * 1000 + 900,
                "text": text,
            }
            for index, (segment_id, text) in enumerate(texts.items())
        ],
    }


def seed_recording(state: Any, *, revision: str, tenant: str = "Alpha") -> UUID:
    now = datetime.now(UTC)
    permission_id, recording_id = uuid4(), uuid4()
    with Session(state.engine) as db, db.begin():
        db.add(
            ConversationPermission(
                id=permission_id,
                tenant_id=state.tenants[tenant],
                person_id=state.person,
                source_sha256="0" * 64,
                provider="local",
                permission_reference=f"fixture-{permission_id}",
                retention_reference="fixture-retention",
                created_at=now,
                expires_at=now + timedelta(days=1),
                retention_until=now + timedelta(days=30),
            )
        )
        db.flush()
        db.add(
            ConversationRecording(
                id=recording_id,
                tenant_id=state.tenants[tenant],
                person_id=state.person,
                permission_id=permission_id,
                request_key=f"fixture-{recording_id}",
                intent_sha256="1" * 64,
                source_sha256="0" * 64,
                source_bytes=1024,
                content_type="audio/mpeg",
                source_revision=1,
                generation=1,
                state="ready",
                created_at=now,
            )
        )
        db.flush()
        payload = _transcript(revision)
        db.add(
            ConversationCheckpoint(
                id=uuid4(),
                tenant_id=state.tenants[tenant],
                person_id=state.person,
                recording_id=recording_id,
                cache_key=sha256(f"{recording_id}:{revision}".encode()).hexdigest(),
                manifest_sha256="2" * 64,
                payload_sha256="3" * 64,
                stage="C2",
                payload=payload,
                created_at=now,
            )
        )
    return recording_id


@pytest.fixture
def marks_state(workspace_state):
    state = workspace_state
    state.settings = state.settings.model_copy(
        update={"operations_tenant_id": state.tenants["Other"]}
    )

    @asynccontextmanager
    async def sessions():
        state.opened += 1
        with Session(state.engine) as db:
            yield HttpDatabase(db)

    state.app = FastAPI()
    register_problem_handlers(state.app)
    require_actor = install_identity_http(
        state.app, settings=state.settings, sessions=cast(Any, sessions)
    )
    install_platform_sensitive_segments_http(
        state.app, settings=state.settings, require_actor=require_actor
    )
    state.app.add_middleware(CoachSurfaceMiddleware, settings=state.settings)
    state.recording = seed_recording(state, revision=REVISION)
    return state


async def call(
    state,
    method: str,
    path: str,
    *,
    token: str | None = TOKEN,
    host: str = "admin",
    json: Any = None,
    key: str | None = "key-1",
    origin: str | None = ORIGIN,
    query: str = "",
):
    base = f"https://{host}.authorityclosers.test"
    headers: dict[str, str] = {}
    if token is not None:
        headers["cookie"] = f"ac_session={token}"
    if method == "POST":
        if key is not None:
            headers["Idempotency-Key"] = key
        if origin is not None:
            headers["origin"] = origin
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=state.app), base_url=base) as c:
        return await c.request(
            method, f"/v1/platform/sensitive-segments{path}{query}", headers=headers, json=json
        )


def mark_body(*segments: tuple[str, str], revision: str = REVISION, reason: str = REASON):
    return {
        "transcript_revision": revision,
        "segments": [{"segment_id": s, "category": c} for s, c in segments],
        "reason_ref": reason,
    }


def rows(state, recording_id: UUID) -> list[ConversationSensitiveSegmentMark]:
    with Session(state.engine) as db:
        return list(
            db.scalars(
                select(ConversationSensitiveSegmentMark)
                .where(ConversationSensitiveSegmentMark.recording_id == recording_id)
                .order_by(ConversationSensitiveSegmentMark.created_at)
            )
        )


async def effective(state, recording_id: UUID, revision: str = REVISION) -> set[str]:
    with Session(state.engine) as db:
        marks = await effective_marks(
            cast(Any, HttpDatabase(db)), recording_id=recording_id, transcript_revision=revision
        )
    return {mark.segment_id for mark in marks}


@pytest.mark.parametrize(
    "method,path", [("GET", "/recordings/{id}"), ("POST", "/recordings/{id}/marks")]
)
async def test_routes_need_a_session_and_the_capability(marks_state, method, path):
    state = marks_state
    path = path.format(id=state.recording)
    body = mark_body(("s2", "SENSITIVE_FINANCIAL")) if method == "POST" else None
    assert (await call(state, method, path, token=None, json=body)).status_code == 401
    assert (await call(state, method, path, json=body)).status_code == 403
    await grant(state, "platform_release_manage")
    assert (await call(state, method, path, json=body)).status_code == 403
    assert (await call(state, method, path, token=OTHER_TOKEN, json=body)).status_code == 403
    assert rows(state, state.recording) == []


async def test_release_needs_the_capability_even_for_an_unknown_mark(marks_state):
    response = await call(
        marks_state, "POST", f"/marks/{uuid4()}/release", json={"reason_ref": REASON}
    )
    assert response.status_code == 403


@pytest.mark.parametrize("host", ["coach", "learner"])
async def test_other_surfaces_are_refused(marks_state, host):
    await grant(marks_state, "platform_content_safety_manage")
    response = await call(marks_state, "GET", f"/recordings/{marks_state.recording}", host=host)
    assert response.status_code == 403


async def test_mark_remark_release_mark_keeps_three_rows_with_audit(marks_state, caplog):
    state = marks_state
    caplog.set_level(logging.DEBUG)
    await grant(state, "platform_content_safety_manage")
    recording = state.recording
    path = f"/recordings/{recording}/marks"

    first = await call(state, "POST", path, json=mark_body(("s2", "SENSITIVE_FINANCIAL")), key="k1")
    assert first.status_code == 200, first.text
    assert first.headers["cache-control"] == "private, no-store"
    mark = first.json()["marks"][0]
    assert mark["segment_id"] == "s2" and mark["action"] == "mark"
    assert mark["actor_person_id"] == str(state.person) and mark["reason_ref"] == REASON
    assert await effective(state, recording) == {"s2"}

    again = await call(state, "POST", path, json=mark_body(("s2", "SENSITIVE_LEGAL")), key="k2")
    assert again.status_code == 200
    assert again.json()["marks"][0]["mark_id"] == mark["mark_id"]
    assert len(rows(state, recording)) == 1

    released = await call(
        state,
        "POST",
        f"/marks/{mark['mark_id']}/release",
        json={"reason_ref": "AUT-520 release"},
        key="k3",
    )
    assert released.status_code == 200, released.text
    assert released.json()["action"] == "release"
    assert released.json()["supersedes_mark_id"] == mark["mark_id"]
    assert await effective(state, recording) == set()

    twice = await call(
        state,
        "POST",
        f"/marks/{mark['mark_id']}/release",
        json={"reason_ref": "AUT-520 release"},
        key="k4",
    )
    assert twice.status_code == 409

    third = await call(state, "POST", path, json=mark_body(("s2", "SENSITIVE_LEGAL")), key="k5")
    assert third.status_code == 200
    assert third.json()["marks"][0]["mark_id"] not in {mark["mark_id"], released.json()["mark_id"]}
    assert await effective(state, recording) == {"s2"}

    history = rows(state, recording)
    assert [row.action for row in history] == ["mark", "release", "mark"]
    with Session(state.engine) as db:
        for row in history:
            event = db.get(AuditEvent, row.audit_event_id)
            assert event is not None
            assert event.tenant_id == state.tenants["Alpha"]
            assert event.actor_person_id == state.person
            assert event.reason == row.reason_ref
            assert event.resource_id == str(row.id)
            assert SENTINEL not in repr(event.payload)
        assert db.scalar(
            select(AuditEvent.id).where(AuditEvent.tenant_id == state.tenants["Alpha"]).limit(1)
        )

    listing = await call(state, "GET", f"/recordings/{recording}")
    assert listing.status_code == 200
    body = listing.json()
    assert body["tenant_id"] == str(state.tenants["Alpha"])
    assert body["transcript_revisions"] == [{"revision": REVISION, "segment_count": 4}]
    assert [item["action"] for item in body["marks"]] == ["mark", "release", "mark"]
    for response in (first, again, released, twice, third, listing):
        assert SENTINEL not in response.text
    assert SENTINEL not in caplog.text


async def test_same_key_replays_without_a_second_write(marks_state):
    state = marks_state
    await grant(state, "platform_content_safety_manage")
    path = f"/recordings/{state.recording}/marks"
    body = mark_body(("s1", "SENSITIVE_LEGAL"), ("s3", "SENSITIVE_FINANCIAL"))
    first = await call(state, "POST", path, json=body, key="same")
    replay = await call(state, "POST", path, json=body, key="same")
    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    assert len(rows(state, state.recording)) == 2
    with Session(state.engine) as db:
        assert (
            db.scalar(
                select(AuditEvent.sequence_no)
                .where(AuditEvent.tenant_id == state.tenants["Alpha"])
                .order_by(AuditEvent.sequence_no.desc())
            )
            == 3  # one request receipt plus one event per mark; the replay adds none
        )
    other = await call(
        state, "POST", path, json=mark_body(("s1", "SENSITIVE_FINANCIAL")), key="same"
    )
    assert other.status_code == 409
    assert (await call(state, "POST", path, json=body, key=None)).status_code == 422
    assert (await call(state, "POST", path, json=body, origin=None)).status_code == 403


async def test_unknown_recording_revision_and_segment_never_echo_text(marks_state, caplog):
    state = marks_state
    caplog.set_level(logging.DEBUG)
    await grant(state, "platform_content_safety_manage")
    path = f"/recordings/{state.recording}/marks"
    missing = await call(state, "GET", f"/recordings/{uuid4()}")
    assert missing.status_code == 404
    missing_write = await call(
        state, "POST", f"/recordings/{uuid4()}/marks", json=mark_body(("s2", "SENSITIVE_LEGAL"))
    )
    assert missing_write.status_code == 404
    revision = await call(
        state, "POST", path, json=mark_body(("s2", "SENSITIVE_LEGAL"), revision=OTHER_REVISION)
    )
    assert revision.status_code == 409
    segment = await call(state, "POST", path, json=mark_body(("s9", "SENSITIVE_LEGAL")))
    assert segment.status_code == 422
    assert "s9" in segment.json()["detail"]
    extra = await call(
        state, "POST", path, json={**mark_body(("s2", "SENSITIVE_LEGAL")), "note": SENTINEL}
    )
    assert extra.status_code == 422
    bad_reason = await call(
        state, "POST", path, json=mark_body(("s2", "SENSITIVE_LEGAL"), reason="x")
    )
    assert bad_reason.status_code == 422
    too_many = await call(
        state, "POST", path, json=mark_body(*[(f"s{i}", "SENSITIVE_LEGAL") for i in range(21)])
    )
    assert too_many.status_code == 422
    query = await call(state, "GET", f"/recordings/{state.recording}", query="?text=1")
    assert query.status_code == 422
    unknown_mark = await call(
        state, "POST", f"/marks/{uuid4()}/release", json={"reason_ref": REASON}
    )
    assert unknown_mark.status_code == 404
    assert rows(state, state.recording) == []
    for response in (
        missing,
        missing_write,
        revision,
        segment,
        extra,
        bad_reason,
        too_many,
        query,
        unknown_mark,
    ):
        assert SENTINEL not in response.text
        assert "widget" not in response.text and "demo today" not in response.text
    assert SENTINEL not in caplog.text


async def test_duplicate_upload_with_the_same_revision_sees_the_marks(marks_state):
    state = marks_state
    await grant(state, "platform_content_safety_manage")
    duplicate = seed_recording(state, revision=REVISION, tenant="Beta")
    unrelated = seed_recording(state, revision=OTHER_REVISION, tenant="Beta")
    response = await call(
        state,
        "POST",
        f"/recordings/{state.recording}/marks",
        json=mark_body(("s3", "SENSITIVE_FINANCIAL")),
    )
    assert response.status_code == 200
    assert await effective(state, duplicate) == {"s3"}
    assert await effective(state, unrelated, OTHER_REVISION) == set()
    with Session(state.engine) as db:
        marks = await effective_marks(
            cast(Any, HttpDatabase(db)), recording_id=duplicate, transcript_revision=REVISION
        )
    assert marks[0].recording_id == state.recording
    assert marks[0].tenant_id == state.tenants["Alpha"]
    assert not hasattr(marks[0], "text") and SENTINEL not in repr(marks)
    listing = await call(state, "GET", f"/recordings/{duplicate}")
    assert listing.json()["marks"] == []
    assert listing.json()["transcript_revisions"] == [{"revision": REVISION, "segment_count": 4}]


async def test_same_key_with_a_different_body_is_refused(marks_state):
    """AUT-521: the Idempotency-Key binds the whole request, not each segment."""

    state = marks_state
    await grant(state, "platform_content_safety_manage")
    path = f"/recordings/{state.recording}/marks"
    first = await call(state, "POST", path, json=mark_body(("s1", "SENSITIVE_LEGAL")), key="k")
    assert first.status_code == 200
    superset = await call(
        state,
        "POST",
        path,
        json=mark_body(("s1", "SENSITIVE_LEGAL"), ("s3", "SENSITIVE_FINANCIAL")),
        key="k",
    )
    disjoint = await call(state, "POST", path, json=mark_body(("s4", "SENSITIVE_LEGAL")), key="k")
    reason = await call(
        state, "POST", path, json=mark_body(("s1", "SENSITIVE_LEGAL"), reason="AUT-999"), key="k"
    )
    assert superset.status_code == disjoint.status_code == reason.status_code == 409
    identical = await call(state, "POST", path, json=mark_body(("s1", "SENSITIVE_LEGAL")), key="k")
    assert identical.status_code == 200 and identical.json() == first.json()
    assert [row.segment_id for row in rows(state, state.recording)] == ["s1"]
    for response in (first, superset, disjoint, reason, identical):
        assert SENTINEL not in response.text
