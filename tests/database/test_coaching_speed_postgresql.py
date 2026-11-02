"""A seller's Coaching keeps its query count with many reports (the test robot, 2 Nov 2026:
GET /v1/me/coaching took 3.5-5.4 s for a seller with 20 reports, and made 758 queries). With
20 report-ready calls the read stays within a fixed number of queries a report, and it never
asks for the previous call's context, which Coaching does not show."""

import re
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from sqlalchemy import event

from ac_platform.conversation_intelligence.acquisition_reports import AcquisitionReports
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from tests.database.test_coaching_postgresql import PATH, draft_for, install
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup
from tests.database.test_prospect_store_postgresql import direct_call

CALLS = 20
# The read itself, then each report's access checks, recording, draft, run and withholding.
READ_QUERIES = 20
QUERIES_PER_REPORT = 35


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def test_coaching_with_twenty_reports_keeps_its_query_count(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        install(setup)
        try:
            for index in range(CALLS):
                call = await direct_call(setup)
                await draft_for(setup, call, line=f"Fictional line {index}: price and timing.")
                async with setup.sessions() as db, db.begin():
                    await AcquisitionReports(GuestOwnership(setup.factory(db))).report(
                        call, actor=setup.state.actor
                    )
            tables: list[str] = []

            def counted(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
                found = re.search(r"\bFROM\s+([a-z_]+)", statement, re.I)
                tables.append(found.group(1) if found else statement[:40])

            event.listen(setup.engine.sync_engine, "before_cursor_execute", counted)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                for _ in range(2):
                    tables.clear()
                    response = await client.get(PATH)
                    assert response.status_code == 200, response.text
                    data = response.json()
                    assert [row["state"] for row in data["calls"]] == ["ready"] * CALLS
                    assert not [t for t in tables if t.startswith("conversation_prospect")]
                    assert len(tables) <= READ_QUERIES + QUERIES_PER_REPORT * CALLS, len(tables)
        finally:
            await setup.engine.dispose()

    run(exercise())
