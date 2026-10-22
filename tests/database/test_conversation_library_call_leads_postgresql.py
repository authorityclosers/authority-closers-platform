"""Calls name the lead they belong to (approved map, slice 7, 22 Oct 2026).

``include_leads=true`` adds ``lead`` to each listed call a lead names through
``last_submission_id``: one more statement for the page, the actor's tenant
only, and without the flag the rows are unchanged. Synthetic one-second WAV
uploads, no provider.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from ac_platform.lead_desk.models import Lead
from tests.database.test_conversation_account_library_postgresql import _upload
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, PREFIX, _setup


@pytest.fixture(scope="module")
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


def _lead(
    tenant_id: UUID,
    name: str,
    *,
    submission_id: str,
    stage: str = "interested",
    step: str | None = None,
    updated: datetime,
) -> Lead:
    return Lead(
        id=uuid4(),
        tenant_id=tenant_id,
        revision=1,
        source="manual",
        payload={},
        name=name,
        stage=stage,
        step=step,
        attempts=1,
        calls=1,
        repeats=0,
        last_submission_id=UUID(submission_id),
        test_data=False,
        created_at=updated,
        updated_at=updated,
    )


def test_calls_name_their_lead_only_when_asked_and_only_in_the_tenant(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set("ac_session", setup.token)
                linked, other, plain = [(await _upload(client))["submission_id"] for _ in range(3)]
                stranger = await seed(setup.engine)
                now = datetime.now(UTC)
                async with setup.sessions() as db, db.begin():
                    db.add_all(
                        [
                            # Two leads name one call: the one changed last wins.
                            _lead(
                                setup.state.tenant_id,
                                "meera fictional",
                                submission_id=linked,
                                step="site_visit",
                                updated=now,
                            ),
                            _lead(
                                setup.state.tenant_id,
                                "older example",
                                submission_id=linked,
                                stage="follow_up",
                                updated=now - timedelta(days=1),
                            ),
                            # Another organisation's lead naming this tenant's call.
                            _lead(
                                stranger.tenant_id,
                                "elsewhere sample",
                                submission_id=other,
                                updated=now,
                            ),
                        ]
                    )

                plain_page = await client.get(PREFIX + "/submissions")
                assert plain_page.status_code == 200, plain_page.text
                assert all("lead" not in row for row in plain_page.json()["submissions"])

                page = await client.get(PREFIX + "/submissions?include_leads=true")
                assert page.status_code == 200, page.text
                rows = {row["submission_id"]: row for row in page.json()["submissions"]}
                assert set(rows) == {linked, other, plain}
                lead = rows[linked]["lead"]
                assert lead["name"] == "meera fictional"
                assert UUID(lead["lead_id"])
                assert lead == {
                    "lead_id": lead["lead_id"],
                    "name": "meera fictional",
                    "stage": "interested",
                    "step": "site_visit",
                    "pipeline": "main",
                }
                assert "lead" not in rows[other]
                assert "lead" not in rows[plain]
        finally:
            await setup.engine.dispose()

    run(exercise())
