"""Fictional uploads prove whole-library counts and constant SQL cost."""

import httpx
from sqlalchemy import event

from ac_platform.conversation_intelligence.acquisition_library import account_library_summary
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from tests.database.test_conversation_account_library_postgresql import (
    _seed_retained_guest_submission,
    _upload,
    postgres_harness,  # noqa: F401 - shared disposable PostgreSQL fixture
)
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, PREFIX, _setup


def test_summary_counts_all_pages_and_claimed_guest_in_one_statement(postgres_harness, tmp_path):  # noqa: F811
    async def exercise():
        setup = await _setup(postgres_harness, tmp_path)
        statements = []
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set("ac_session", setup.token)
                assert (await client.get(PREFIX + "/submissions/summary")).json() == {
                    "total": 0,
                    "processing": 0,
                    "completed": 0,
                    "needs_attention": 0,
                }
                await _seed_retained_guest_submission(setup)
                async with setup.sessions() as db, db.begin():
                    await setup.factory(db).claim(setup.guest.token, setup.state.actor)
                for _ in range(24):
                    await _upload(client)
                async with setup.sessions() as db, db.begin():
                    ownership = GuestOwnership(setup.factory(db))
                    # Measure admission independently so only aggregate SQL remains.
                    await ownership.sessions._owner(
                        None, setup.state.actor, await ownership.sessions._admit()
                    )

                    def capture(conn, cursor, statement, parameters, context, executemany):
                        statements.append(statement)

                    event.listen(setup.engine.sync_engine, "before_cursor_execute", capture)
                    await ownership.sessions._owner(
                        None, setup.state.actor, await ownership.sessions._admit()
                    )
                    admission = len(statements)
                    statements.clear()
                    counts = await account_library_summary(ownership, setup.state.actor)
                    event.remove(setup.engine.sync_engine, "before_cursor_execute", capture)
                    assert len(statements) == admission + 1
                    assert all(s.lstrip().upper().startswith("SELECT") for s in statements)
                assert counts == {
                    "total": 25,
                    "processing": 0,
                    "completed": 0,
                    "needs_attention": 0,
                }
                first = (await client.get(PREFIX + "/submissions")).json()
                second = (
                    await client.get(
                        PREFIX + "/submissions", params={"before": first["next_cursor"]}
                    )
                ).json()
                assert len(first["submissions"]) == 20 and len(second["submissions"]) == 5
        finally:
            await setup.engine.dispose()

    run(exercise())
