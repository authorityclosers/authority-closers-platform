"""The Calls page lists calls whose analysis started before never-analysed ones.

Dev owner report (16 Oct 2026): 76 imported calls that were never analysed
filled the first pages, so no Report showed. ``order=reports_first`` keeps
the cursor stable: synthetic one-second WAV uploads, no provider.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.models import (
    ConversationProcessingPlan,
    ConversationRecording,
)
from tests.database.test_conversation_account_library_postgresql import _upload
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, PREFIX, _setup
from tests.database.test_conversation_worker_postgresql import (
    OfflineConversationWorker,
    _reconcile,
)


@pytest.fixture(scope="module")
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


async def _pause_analysis(setup: Any, submission_id: str) -> None:
    """A held processing plan: the call's analysis started (paused for attention).

    This harness has provider analysis off, so the plan row stands in for one.
    """
    async with setup.sessions() as db, db.begin():
        link = await db.scalar(
            select(ConversationGuestSubmission).where(
                ConversationGuestSubmission.submission_id == UUID(submission_id)
            )
        )
        assert link is not None
        recording = await db.get(ConversationRecording, link.recording_id)
        assert recording is not None
        now = datetime.now(UTC)
        db.add(
            ConversationProcessingPlan(
                id=uuid4(),
                tenant_id=recording.tenant_id,
                person_id=recording.person_id,
                recording_id=recording.id,
                session_id=None,
                processing_lease_id=link.processing_lease_id,
                generation=recording.generation,
                plan_sha256="d" * 64,
                manifest=None,
                speaker_roles=None,
                acceptance_command_id=None,
                state="held",
                progress={},
                next_check_at=now,
                created_at=now,
                expires_at=now + timedelta(days=1),
            )
        )


async def _pages(client: httpx.AsyncClient, query: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cursor = None
    while True:
        suffix = query + (f"&before={cursor}" if cursor else "")
        page = await client.get(PREFIX + "/submissions" + suffix)
        assert page.status_code == 200, page.text
        body = page.json()
        rows.extend(body["submissions"])
        cursor = body["next_cursor"]
        if cursor is None:
            return rows


def test_reports_first_lists_started_calls_first_with_a_stable_cursor(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set("ac_session", setup.token)
                uploaded = [(await _upload(client))["submission_id"] for _ in range(23)]
                await _reconcile(setup.sessions, setup.state)
                worker = OfflineConversationWorker(
                    setup.sessions,
                    storage=setup.runtime.storage,
                    scratch=setup.runtime.scratch,
                    environment="test",
                )
                while await worker.run_once():
                    pass
                newest = await _pages(client, "?include_owners=true")
                assert [row["submission_id"] for row in newest] == sorted(
                    uploaded, key=UUID, reverse=True
                )
                # Two older calls (positions 3 and 17 of the newest-first list).
                started = [newest[3]["submission_id"], newest[17]["submission_id"]]
                for submission_id in started:
                    await _pause_analysis(setup, submission_id)
                listed = await _pages(client, "?include_owners=true&order=reports_first")
                ids = [row["submission_id"] for row in listed]
                assert len(ids) == len(set(ids)) == 23
                assert ids[:2] == started
                rest = [item for item in newest if item["submission_id"] not in started]
                assert ids[2:] == [row["submission_id"] for row in rest]
                assert [row["state"] for row in listed[:2]] == ["held", "held"]
                # The first page already shows both started calls.
                first = (
                    await client.get(
                        PREFIX + "/submissions?include_owners=true&order=reports_first"
                    )
                ).json()
                assert [row["submission_id"] for row in first["submissions"][:2]] == started
                assert len(first["submissions"]) == 20
                # The default order is unchanged and unknown orders are refused.
                assert [row["submission_id"] for row in await _pages(client, "?")] == [
                    row["submission_id"] for row in newest
                ]
                refused = await client.get(PREFIX + "/submissions?order=sideways")
                assert refused.status_code == 422
        finally:
            await setup.engine.dispose()

    run(exercise())
