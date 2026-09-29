"""Canary visibility proofs against PostgreSQL with fictional uploads only."""

from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import func, select

from ac_platform.conversation_intelligence import acquisition_library
from ac_platform.conversation_intelligence.admin_recordings import AdminConversationRecordings
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationConflict,
    ConversationDenied,
)
from ac_platform.conversation_intelligence.canary import mark_canary_submission
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.models import (
    ConversationRecording,
    ConversationReviewAssignment,
    ConversationRun,
)
from ac_platform.conversation_intelligence.review_contracts import ReviewAssignmentCreateRequest
from ac_platform.conversation_intelligence.review_service import ConversationReviewService
from tests.database.test_conversation_account_library_postgresql import (
    _seed_retained_guest_submission,
    _upload,
)
from tests.database.test_conversation_authority_postgresql import _promote_admin
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


async def _sources(setup: Any, owner: str = "guest") -> list[dict[str, Any]]:
    sources = []
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
    ) as client:
        client.cookies.set(setup.settings.session_cookie_name, setup.token)
        for index in range(3):
            setup.clock[0] = setup.state.now + timedelta(seconds=index)
            if owner == "direct":
                uploaded = await _upload(client)
                source = {
                    "submission_id": UUID(uploaded["submission_id"]),
                    "recording_id": UUID(uploaded["recording_id"]),
                }
            else:
                async with setup.sessions() as db, db.begin():
                    setup.guest = await setup.factory(db).issue()
                source = await _seed_retained_guest_submission(setup)
                if owner == "claimed":
                    async with setup.sessions() as db, db.begin():
                        await setup.factory(db).claim(setup.guest.token, setup.state.actor)
            sources.append(source)
            if index == 1:
                async with setup.sessions() as db, db.begin():
                    recording = await db.get(ConversationRecording, source["recording_id"])
                    await mark_canary_submission(
                        db,
                        tenant_id=setup.state.tenant_id,
                        submission_id=source["submission_id"],
                        environment="test",
                        fixture_sha256=recording.source_sha256,
                        created_at=setup.clock[0],
                    )
    return sources


def test_admin_pages_and_search_exclude_canary(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            older, canary, newer = await _sources(setup)
            actor = await _promote_admin(setup.engine, setup.state)
            async with setup.sessions() as db, db.begin():
                inventory = AdminConversationRecordings(
                    ConversationApplication(db, clock=lambda: setup.clock[0]),
                    operations_tenant_id=setup.state.tenant_id,
                )
                first = await inventory.list(actor, limit=1)
                assert [row["id"] for row in first["items"]] == [str(newer["recording_id"])]
                assert first["next_cursor"] is not None
                second = await inventory.list(actor, limit=1, cursor=first["next_cursor"])
                assert [row["id"] for row in second["items"]] == [str(older["recording_id"])]
                assert second["next_cursor"] is None
                assert await inventory.list(actor, search=str(canary["recording_id"])) == {
                    "items": [],
                    "next_cursor": None,
                }
        finally:
            await setup.engine.dispose()

    run(exercise())


@pytest.mark.parametrize("owner", ["direct", "claimed"])
def test_account_library_excludes_canary_before_pagination(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, owner: str
) -> None:
    monkeypatch.setattr(acquisition_library, "PAGE_SIZE", 1)

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            older, _, newer = await _sources(setup, owner)
            async with setup.sessions() as db, db.begin():
                ownership = GuestOwnership(setup.factory(db))
                first = await acquisition_library.account_library(ownership, setup.state.actor)
                assert [row["submission_id"] for row in first["submissions"]] == [
                    str(newer["submission_id"])
                ]
                assert first["next_cursor"] == str(newer["submission_id"])
                second = await acquisition_library.account_library(
                    ownership, setup.state.actor, before=UUID(first["next_cursor"])
                )
                assert [row["submission_id"] for row in second["submissions"]] == [
                    str(older["submission_id"])
                ]
                assert second["next_cursor"] is None
                summary = await acquisition_library.account_library_summary(
                    ownership, setup.state.actor
                )
                assert summary["total"] == 2
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_review_create_refuses_canary_without_assignment(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            ordinary, canary, _ = await _sources(setup, "direct")
            actor = await _promote_admin(setup.engine, setup.state)
            async with setup.sessions() as db, db.begin():
                service = ConversationReviewService(
                    ConversationApplication(db, clock=lambda: setup.clock[0]),
                    operations_tenant_id=setup.state.tenant_id,
                )
                for source in (canary, ordinary):
                    run_id = await db.scalar(
                        select(ConversationRun.id).where(
                            ConversationRun.recording_id == source["recording_id"]
                        )
                    )
                    assert run_id is not None
                    intent = ReviewAssignmentCreateRequest(
                        schema="ac.sales-xray.review-assignment-create/1",
                        run_id=run_id,
                        reviewer_person_id=setup.state.person_id,
                        allowed_lenses=("sales",),
                        expires_at_epoch=int(setup.clock[0].timestamp()) + 1800,
                    )
                    error, message = (
                        (ConversationDenied, "Canary calls cannot be assigned for review")
                        if source is canary
                        else (ConversationConflict, "The review call is no longer available")
                    )
                    with pytest.raises(error, match=message):
                        await service.create(actor, intent, f"visibility-{run_id}")
                assert (
                    await db.scalar(select(func.count()).select_from(ConversationReviewAssignment))
                    == 0
                )
        finally:
            await setup.engine.dispose()

    run(exercise())
