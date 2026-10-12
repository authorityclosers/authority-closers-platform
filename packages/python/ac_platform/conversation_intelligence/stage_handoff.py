"""Make an accepted plan due atomically with its predecessor's publication."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from psycopg import AsyncConnection
from sqlalchemy import func, select, update
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.conversation_intelligence.models import (
    ConversationProcessingPlan,
    ConversationRecording,
)

CHANNEL = "ac_conversation_work_v1"
_LOGGER = logging.getLogger(__name__)


async def notify_work(database: AsyncSession) -> None:
    """PostgreSQL delivers this content-free hint only after commit."""
    await database.execute(select(func.pg_notify(CHANNEL, "")))


@asynccontextmanager
async def committed_work_listener(
    database_url: str | URL,
) -> AsyncIterator[tuple[asyncio.Event, asyncio.Event]]:
    """One dedicated LISTEN connection; durable scans cover loss/reconnection.

    Notifications carry no source, customer, transcript or credentials. They
    grant no execution authority and do not change canonical progress.
    """
    wakeups = (asyncio.Event(), asyncio.Event())
    url = make_url(database_url).set(drivername="postgresql")
    dsn = url.render_as_string(hide_password=False)

    async def listen() -> None:
        while True:
            try:
                async with await AsyncConnection.connect(
                    dsn, autocommit=True, connect_timeout=10
                ) as connection:
                    await connection.execute("LISTEN ac_conversation_work_v1")
                    # Catch work committed before LISTEN or while disconnected.
                    for event in wakeups:
                        event.set()
                    async for _ in connection.notifies():
                        for event in wakeups:
                            event.set()
            except asyncio.CancelledError:
                raise
            except Exception:
                # No exception text: connection errors may contain the DSN.
                _LOGGER.warning("conversation_worker_notifications_unavailable")
                await asyncio.sleep(10)

    listener = asyncio.create_task(listen(), name="conversation-committed-work-listener")
    try:
        yield wakeups
    finally:
        listener.cancel()
        with suppress(asyncio.CancelledError):
            await listener


async def make_plans_due(database: AsyncSession, recording: ConversationRecording) -> None:
    # This is scheduling only. The coordinator still rechecks current consent,
    # actor, source, route, budget and immutable checkpoint before enqueuing.
    # The coordinator locks plan -> recording; publication already owns the
    # recording. Never wait for its plan lock in the opposite order. If skipped,
    # the coordinator's pending recording read sees this committed completion.
    unlocked_plans = (
        select(ConversationProcessingPlan.id)
        .where(
            ConversationProcessingPlan.tenant_id == recording.tenant_id,
            ConversationProcessingPlan.recording_id == recording.id,
            ConversationProcessingPlan.generation == recording.generation,
            ConversationProcessingPlan.state == "active",
            ConversationProcessingPlan.erased_at.is_(None),
        )
        .with_for_update(skip_locked=True)
    )
    await database.execute(
        update(ConversationProcessingPlan)
        .where(ConversationProcessingPlan.id.in_(unlocked_plans))
        .values(next_check_at=func.clock_timestamp())
        .execution_options(synchronize_session=False)
    )
    await notify_work(database)
