"""Reports V4 files each call by how it arrived and its lead's side (Dipak's spec, 13 Nov 2026).

``include_kind=true`` adds ``upload`` ("auto" when the phone captured the recording and
uploaded it itself, "manual" when someone chose the file) and ``lead_side`` ("inbound" or
"cold" for a call a lead names, null otherwise), and ``limit`` reads up to 100 calls a page,
so the Reports library is a few reads. Without the flags the rows are unchanged. Synthetic
one-second WAV uploads, no provider.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from ac_platform.lead_desk.models import Lead
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import (
    ORIGIN,
    PREFIX,
    _headers,
    _setup,
)
from tests.database.test_conversation_worker_postgresql import _wav_one_second_48k


@pytest.fixture(scope="module")
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


async def _upload(client: httpx.AsyncClient, capture_source: str | None) -> str:
    audio = _wav_one_second_48k()
    headers = await _headers(client, audio)
    if capture_source is not None:
        headers["X-Capture-Source"] = capture_source
    response = await client.put(
        PREFIX + f"/submissions/{uuid4()}/source", content=audio, headers=headers
    )
    assert response.status_code == 202, response.json()
    return str(response.json()["submission_id"])


def _lead(tenant_id: UUID, name: str, submission_id: str, pipeline: str | None) -> Lead:
    now = datetime.now(UTC) - timedelta(minutes=5)
    return Lead(
        id=uuid4(),
        tenant_id=tenant_id,
        revision=1,
        source="manual",
        payload={},
        name=name,
        stage="follow_up",
        attempts=1,
        calls=1,
        repeats=0,
        last_submission_id=UUID(submission_id),
        pipeline=pipeline,
        test_data=False,
        created_at=now,
        updated_at=now,
    )


def test_reports_know_how_each_call_arrived_and_its_leads_side(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set("ac_session", setup.token)
                dialled = await _upload(client, "android_dialer_pickup")
                recorded = await _upload(client, "android_in_app_recorder")
                chosen = await _upload(client, "web_upload")
                shared = await _upload(client, "android_share")
                older = await _upload(client, None)
                async with setup.sessions() as db, db.begin():
                    db.add_all(
                        [
                            _lead(setup.state.tenant_id, "cold sample", dialled, "cold"),
                            _lead(setup.state.tenant_id, "old sample", recorded, "history"),
                            _lead(setup.state.tenant_id, "inbound sample", chosen, None),
                            _lead(setup.state.tenant_id, "live sample", shared, "live"),
                        ]
                    )

                plain = await client.get(PREFIX + "/submissions")
                assert plain.status_code == 200, plain.text
                for row in plain.json()["submissions"]:
                    assert "upload" not in row and "lead_side" not in row and "lead" not in row

                page = await client.get(PREFIX + "/submissions?include_kind=true&limit=100")
                assert page.status_code == 200, page.text
                rows = {row["submission_id"]: row for row in page.json()["submissions"]}
                assert set(rows) == {dialled, recorded, chosen, shared, older}
                kinds = {key: (row["upload"], row["lead_side"]) for key, row in rows.items()}
                assert kinds == {
                    dialled: ("auto", "cold"),
                    # Old leads count with Cold, as Lead Desk reads them.
                    recorded: ("auto", "cold"),
                    chosen: ("manual", "inbound"),
                    shared: ("manual", "inbound"),
                    # Stored before the phone said how it captured: a chosen file.
                    older: ("manual", None),
                }
                # The kind never brings the lead along: that is include_leads.
                assert all("lead" not in row for row in rows.values())

                both = await client.get(
                    PREFIX + "/submissions?include_kind=true&include_leads=true"
                )
                assert both.status_code == 200, both.text
                named = {row["submission_id"]: row for row in both.json()["submissions"]}
                assert set(named[dialled]["lead"]) == {
                    "lead_id",
                    "name",
                    "stage",
                    "step",
                    "pipeline",
                }
                assert named[dialled]["lead"]["name"] == "cold sample"
                assert "lead" not in named[older]
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_a_page_holds_up_to_one_hundred_calls_and_pages_still_follow(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set("ac_session", setup.token)
                uploaded = [await _upload(client, None) for _ in range(3)]

                first = await client.get(PREFIX + "/submissions?limit=2")
                assert first.status_code == 200, first.text
                body = first.json()
                assert len(body["submissions"]) == 2
                assert body["next_cursor"] == body["submissions"][-1]["submission_id"]
                rest = await client.get(
                    PREFIX + f"/submissions?limit=2&before={body['next_cursor']}"
                )
                assert rest.status_code == 200, rest.text
                assert rest.json()["next_cursor"] is None
                listed = body["submissions"] + rest.json()["submissions"]
                # Every call once, newest first.
                assert sorted(row["submission_id"] for row in listed) == sorted(uploaded)
                created = [row["created_at"] for row in listed]
                assert created == sorted(created, reverse=True)

                whole = await client.get(PREFIX + "/submissions?limit=100")
                assert whole.status_code == 200, whole.text
                assert len(whole.json()["submissions"]) == 3
                assert whole.json()["next_cursor"] is None
                for refused in ("limit=0", "limit=101", "limit=many", "limit=2&limit=3"):
                    response = await client.get(PREFIX + f"/submissions?{refused}")
                    assert response.status_code == 422, (refused, response.text)
        finally:
            await setup.engine.dispose()

    run(exercise())
