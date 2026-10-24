"""One person's parallel reads never queue behind each other, on PostgreSQL.

On 24 Oct 2026 a phone opened a new app version and sent ~20 reads at once.
Each signed in by locking the person and session rows FOR UPDATE and writing
``last_seen_at``, so they ran one by one and all waited about 14 seconds. Reads
now sign in with FOR KEY SHARE fences and advance ``last_seen_at`` at most once
a minute without waiting (SKIP LOCKED); revocation still waits for them.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi import Request
from sqlalchemy import select, update

from ac_platform.identity.application import AsyncIdentityApplication
from ac_platform.identity.models import Session as IdentitySession
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import ORIGIN, _setup

# Each read keeps its transaction open this long, as a real read does while it works.
HOLD = 0.3
READS = 20


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def _install_read(setup: Any) -> None:
    @setup.app.get("/v1/test/first-launch-read")
    async def first_launch_read(request: Request) -> dict[str, float]:
        started = time.monotonic()
        async with asynccontextmanager(setup.require_actor)(request):
            waited = time.monotonic() - started
            await asyncio.sleep(HOLD)
        return {"waited": waited}


async def _session_row(setup: Any) -> tuple[datetime | None, int]:
    async with setup.sessions() as db:
        row = (
            await db.execute(
                select(IdentitySession.last_seen_at, IdentitySession.revision).where(
                    IdentitySession.id == setup.state.session_id
                )
            )
        ).one()
    return row[0], int(row[1])


def test_twenty_parallel_reads_and_the_activity_touch_never_wait(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            # The first launch after a while: every read finds last_seen_at stale.
            long_ago = datetime.now(UTC) - timedelta(hours=8)
            async with setup.sessions() as db, db.begin():
                await db.execute(
                    update(IdentitySession)
                    .where(IdentitySession.id == setup.state.session_id)
                    .values(last_seen_at=long_ago)
                )
            _, revision_before = await _session_row(setup)
            _install_read(setup)
            transport = httpx.ASGITransport(app=setup.app)
            async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                began = time.monotonic()
                answers = await asyncio.gather(
                    *(client.get("/v1/test/first-launch-read") for _ in range(READS))
                )
                took = time.monotonic() - began
            assert [answer.status_code for answer in answers] == [200] * READS
            waits = [answer.json()["waited"] for answer in answers]
            # One by one this was READS x HOLD (6 s); now none waits over a second.
            assert max(waits) < 1.0, waits
            assert took < READS * HOLD / 2, took
            # The activity moved forward once, by whichever read got there first.
            last_seen, revision_after = await _session_row(setup)
            assert last_seen is not None and last_seen > long_ago + timedelta(hours=7)
            assert revision_after == revision_before + 1

            # Within the minute nothing is written again.
            async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                again = await client.get("/v1/test/first-launch-read")
            assert again.status_code == 200
            assert (await _session_row(setup))[1] == revision_after
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_revocation_still_waits_for_reads_in_flight_and_then_ends_them(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            _install_read(setup)
            transport = httpx.ASGITransport(app=setup.app)
            pepper = setup.settings.session_token_pepper.get_secret_value()

            async def revoke() -> float:
                await asyncio.sleep(HOLD / 3)  # the reads hold their fences by now
                started = time.monotonic()
                async with setup.sessions() as db, db.begin():
                    await AsyncIdentityApplication(db, token_pepper=pepper).revoke_self(
                        setup.token, setup.state.session_id, reason="test sign-out"
                    )
                return time.monotonic() - started

            async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as client:
                client.cookies.set(setup.settings.session_cookie_name, setup.token)
                *reads, revoke_wait = await asyncio.gather(
                    *(client.get("/v1/test/first-launch-read") for _ in range(3)), revoke()
                )
                # The reads that had signed in finish; the sign-out waited for them.
                assert [read.status_code for read in reads] == [200, 200, 200]
                assert revoke_wait > HOLD / 3, revoke_wait
                after = await client.get("/v1/test/first-launch-read")
            assert after.status_code == 401
        finally:
            await setup.engine.dispose()

    run(exercise())
