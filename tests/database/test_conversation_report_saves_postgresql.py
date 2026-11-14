"""Saved reports (Reports V4, Dipak's spec, 13 Nov 2026: "Saved Reports" in the filter).

PUT /submissions/{id}/saved saves or unsaves a call's report for the signed-in person; the
list says so with ``include_saved=true``. Asking for what already stands writes nothing.
Saves are erased with the recording and with the person's account. Synthetic one-second WAV
uploads, no provider.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select

from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.report_save_models import ConversationReportSave
from ac_platform.conversation_intelligence.report_saves import erase_report_saves_for_recording
from ac_platform.identity.sales_xray_profile import erase_sales_xray_profile
from tests.database.test_conversation_account_library_postgresql import _upload
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, PREFIX, _setup

JSON = {"Origin": ORIGIN, "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


async def _rows(setup: Any, *submission_ids: str) -> int:
    """Saved-report rows of these calls (the module's database is shared)."""
    async with setup.sessions() as db:
        query = (
            select(func.count())
            .select_from(ConversationReportSave)
            .where(
                ConversationReportSave.submission_id.in_(
                    [UUID(submission_id) for submission_id in submission_ids]
                )
            )
        )
        return int(await db.scalar(query) or 0)


async def _saved(client: httpx.AsyncClient) -> dict[str, bool]:
    page = await client.get(PREFIX + "/submissions?include_saved=true")
    assert page.status_code == 200, page.text
    return {row["submission_id"]: row["saved"] for row in page.json()["submissions"]}


def test_a_person_saves_and_unsaves_a_report_and_the_list_says_so(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set("ac_session", setup.token)
                first = str((await _upload(client))["submission_id"])
                second = str((await _upload(client))["submission_id"])
                assert await _saved(client) == {first: False, second: False}
                plain = await client.get(PREFIX + "/submissions")
                assert all("saved" not in row for row in plain.json()["submissions"])

                save = await client.put(
                    PREFIX + f"/submissions/{first}/saved", json={"saved": True}, headers=JSON
                )
                assert save.status_code == 200, save.text
                assert save.json() == {"saved": True}
                # A second tap (or a retry) writes nothing.
                again = await client.put(
                    PREFIX + f"/submissions/{first}/saved", json={"saved": True}, headers=JSON
                )
                assert again.json() == {"saved": True}
                assert await _rows(setup, first) == 1
                assert await _saved(client) == {first: True, second: False}

                unsave = await client.put(
                    PREFIX + f"/submissions/{first}/saved", json={"saved": False}, headers=JSON
                )
                assert unsave.json() == {"saved": False}
                assert await _rows(setup, first) == 2
                # Unsaving a report never saved writes nothing either.
                never = await client.put(
                    PREFIX + f"/submissions/{second}/saved", json={"saved": False}, headers=JSON
                )
                assert never.json() == {"saved": False}
                assert await _rows(setup, second) == 0
                assert await _saved(client) == {first: False, second: False}

                for body, status in (
                    ('{"saved": "yes"}', 422),
                    ('{"saved": true, "note": 1}', 422),
                    ("{}", 422),
                    ("true", 422),
                ):
                    refused = await client.put(
                        PREFIX + f"/submissions/{first}/saved", content=body, headers=JSON
                    )
                    assert refused.status_code == status, (body, refused.text)
                plain_text = await client.put(
                    PREFIX + f"/submissions/{first}/saved",
                    content='{"saved": true}',
                    headers={"Origin": ORIGIN, "Content-Type": "text/plain"},
                )
                assert plain_text.status_code == 415
                missing = await client.put(
                    PREFIX + f"/submissions/{uuid4()}/saved", json={"saved": True}, headers=JSON
                )
                assert missing.status_code == 404
                assert await _rows(setup, first, second) == 2

                # Signed out: nothing is saved.
                client.cookies.clear()
                signed_out = await client.put(
                    PREFIX + f"/submissions/{second}/saved", json={"saved": True}, headers=JSON
                )
                assert signed_out.status_code in (401, 404)
                assert await _rows(setup, second) == 0
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_saves_are_erased_with_the_recording_and_with_the_account(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set("ac_session", setup.token)
                first = str((await _upload(client))["submission_id"])
                second = str((await _upload(client))["submission_id"])
                for submission in (first, second):
                    response = await client.put(
                        PREFIX + f"/submissions/{submission}/saved",
                        json={"saved": True},
                        headers=JSON,
                    )
                    assert response.json() == {"saved": True}
            assert await _rows(setup, first, second) == 2

            async with setup.sessions() as db, db.begin():
                recording_id = await db.scalar(
                    select(ConversationGuestSubmission.recording_id).where(
                        ConversationGuestSubmission.submission_id == UUID(first)
                    )
                )
                assert recording_id is not None
                erased = await erase_report_saves_for_recording(
                    db, tenant_id=setup.state.tenant_id, recording_id=recording_id
                )
                assert erased == 1
            assert await _rows(setup, first) == 0
            assert await _rows(setup, second) == 1

            async with setup.sessions() as db, db.begin():
                # The canonical account-deletion hook removes the person's saves.
                await erase_sales_xray_profile(db, person_id=setup.state.person_id)
            assert await _rows(setup, first, second) == 0
        finally:
            await setup.engine.dispose()

    run(exercise())
