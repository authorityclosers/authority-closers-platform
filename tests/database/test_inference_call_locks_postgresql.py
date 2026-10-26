"""Demo P1 (26 Oct 2026): accepting the full report froze that person's requests for the
provider call (production, about 28 s). While the worker's provider call runs:
- a signed-in request of the same person (person and session FOR UPDATE) goes on;
- the call's own page (its recording FOR SHARE) goes on;
- deleting or restoring the recording (FOR UPDATE) still waits for the call;
and the call finishes and saves its result."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from ac_platform.conversation_intelligence.models import (
    ConversationMinuteAccount,
    ConversationRecording,
)
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from tests.database.test_conversation_authority_postgresql import _issue, _setup, _start
from tests.database.test_conversation_authority_postgresql import (
    postgres_harness as _postgres_harness,
)
from tests.database.test_conversation_postgresql import run


@pytest.fixture
def postgres_harness():
    yield from _postgres_harness.__wrapped__()


def test_a_provider_call_holds_neither_the_person_nor_the_call_page(postgres_harness, tmp_path):
    async def exercise():
        setup = await _setup(postgres_harness, tmp_path)
        entered, finish = asyncio.Event(), asyncio.Event()
        original = setup.broker.execute

        async def held_call(reservation, payload):
            entered.set()
            await finish.wait()
            return await original(reservation, payload)

        setup.broker.execute = held_call
        recording = select(ConversationRecording).where(
            ConversationRecording.id == setup.prepared.recording_id
        )

        async def locks(*queries, wait: str) -> None:
            async with setup.sessions() as database, database.begin():
                await database.execute(text(f"SET LOCAL lock_timeout = '{wait}'"))
                for query in queries:
                    await database.execute(query)

        running = None
        try:
            await _start(setup, await _issue(setup, key="p1-quote"), key="p1-start")
            running = asyncio.create_task(setup.worker.run_once())
            await asyncio.wait_for(entered.wait(), 10)
            # What every signed-in request of that person takes, while the call runs.
            await asyncio.wait_for(
                locks(
                    select(Person).where(Person.id == setup.actor.person_id).with_for_update(),
                    select(IdentitySession)
                    .where(IdentitySession.id == setup.actor.session_id)
                    .with_for_update(),
                    wait="3s",
                ),
                5,
            )
            # Their minutes (an upload or a quote locks them) are not held by the call.
            await asyncio.wait_for(
                locks(
                    select(ConversationMinuteAccount)
                    .where(ConversationMinuteAccount.person_id == setup.actor.person_id)
                    .with_for_update(),
                    wait="3s",
                ),
                5,
            )
            # The call's own page reads its recording shared.
            await asyncio.wait_for(locks(recording.with_for_update(read=True), wait="3s"), 5)
            # Deleting or restoring the recording still waits for the call.
            with pytest.raises(DBAPIError, match="lock"):
                await locks(recording.with_for_update(), wait="300ms")
            assert not running.done()
            finish.set()
            assert await running
            assert setup.broker.calls == 1
        finally:
            finish.set()
            if running is not None and not running.done():
                await running
            await setup.engine.dispose()

    run(exercise())
