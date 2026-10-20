"""The Calls list reads a page in a fixed number of statements, with row summaries.

Owner, 20 Oct 2026: Home and Calls waited 1.9 s (p50) on the list, which re-read
every call's whole progress and label. A page now costs admission, the
organisation check, the page and its recheck, plus three statements for the
row summaries (``include_summary``), however many rows it holds. Each summary
is what the Report read itself gives for that call.
"""

import httpx
from sqlalchemy import event

from ac_platform.conversation_intelligence.acquisition_library import (
    account_library,
    library_row_summary,
)
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from tests.database.test_conversation_account_library_postgresql import (
    postgres_harness,  # noqa: F401 - shared disposable PostgreSQL fixture
)
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_retained_c5_recovery_postgresql import (
    _seed_guest_retained_case,
)
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, PREFIX
from tests.database.test_conversation_submission_summary_postgresql import (
    PLAN_BUCKETS,
    _mixed_library,
)

SUMMARY_KEYS = {"outcome", "assessment", "fix_first", "next_focus", "strengths", "missed"}


async def _pages(client, params):
    rows, cursor = [], None
    while True:
        response = await client.get(
            PREFIX + "/submissions", params={**params, **({"before": cursor} if cursor else {})}
        )
        assert response.status_code == 200, response.text
        page = response.json()
        rows.extend(page["submissions"])
        cursor = page["next_cursor"]
        if cursor is None:
            return rows


def test_list_page_costs_fixed_statements(postgres_harness, tmp_path):  # noqa: F811
    async def exercise():
        case = await _seed_guest_retained_case(postgres_harness, tmp_path)
        setup = case["setup"]
        statements = []
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set("ac_session", setup.token)
                expected = await _mixed_library(case, client, postgres_harness, tmp_path)
                async with setup.sessions() as db, db.begin():
                    ownership = GuestOwnership(setup.factory(db))

                    async def admit():
                        await ownership.sessions._owner(
                            None,
                            setup.state.actor,
                            await ownership.sessions._admit(),
                            shared_identity_locks=True,
                        )

                    await admit()

                    def capture(conn, cursor, statement, parameters, context, executemany):
                        statements.append(statement)

                    event.listen(setup.engine.sync_engine, "before_cursor_execute", capture)
                    try:
                        await admit()
                        admission = len(statements)
                        statements.clear()
                        page = await account_library(
                            ownership,
                            setup.state.actor,
                            shared_identity_locks=True,
                            include_owners=True,
                            order="reports_first",
                            include_summary=True,
                        )
                    finally:
                        event.remove(setup.engine.sync_engine, "before_cursor_execute", capture)
                assert len(page["submissions"]) == 20
                # Admission, the organisation check, the page, its recheck, then
                # retained Reports, drafts and marks: never one read per call.
                assert len(statements) == admission + 6, statements
                assert all(s.lstrip().upper().startswith("SELECT") for s in statements)
                # Shared locks only: a polled list never blocks a sign-in's writes.
                assert not any("FOR UPDATE" in s.upper() for s in statements)

                plain = await _pages(client, {"include_owners": "true", "order": "reports_first"})
                rich = await _pages(
                    client,
                    {"include_owners": "true", "order": "reports_first", "include_summary": "true"},
                )
                # Without the flag the rows keep their shape (Android, MCP, older pages).
                assert all("summary" not in row for row in plain)
                assert [{k: v for k, v in row.items() if k != "summary"} for row in rich] == plain
                assert {
                    row["submission_id"]: "completed"
                    if row["has_report"]
                    else PLAN_BUCKETS.get(row["state"], "total_only")
                    for row in rich
                } == expected
                summarised = 0
                for row in rich:
                    if not row["has_report"]:
                        assert row["summary"] is None
                        continue
                    report = await client.get(
                        PREFIX + f"/submissions/{row['submission_id']}/report"
                    )
                    if report.status_code == 409:
                        # The Report read refuses this draft, so the row has no summary.
                        assert row["summary"] is None
                        continue
                    assert report.status_code == 200, report.text
                    assert set(row["summary"]) == SUMMARY_KEYS
                    assert row["summary"] == library_row_summary(report.json()["report"]["content"])
                    summarised += 1
                assert summarised >= 1
                refused = await client.get(
                    PREFIX + "/submissions", params={"include_summary": "true", "sideways": "1"}
                )
                assert refused.status_code == 422
        finally:
            await setup.engine.dispose()

    run(exercise())
