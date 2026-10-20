"""The Messenger and Instagram loop, every 10 seconds inside the API.

- Sends: the messages people queued from Chats and Leads, first (a send wakes the loop,
  so it goes within a second or so).
- Comment to message: one private reply (and the rule's public answer) to each comment
  a Page's rule matched.
- Auto replies: an instant first reply to someone writing for the first time, and a
  reply to messages after work hours.
- Erasure: a lead that leaves Lead Desk takes its Messenger and Instagram words with it.

Ten seconds, not thirty: Meta's review of Instagram messaging looks for an automated
answer within 30 seconds. One pass at a time across API processes (lock 1802/1268).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ac_platform.lead_desk.social import graph, inbox

log = logging.getLogger(__name__)

_TICK = 10
_LOCK = (1802, 1268)  # one pass across API processes and slots
_SENDS_PER_PASS = 20
_nudges: list[asyncio.Event] = []  # this process's loop, woken by a person's send


def wake() -> None:
    """A person queued a message: start this process's next pass now."""
    for nudge in _nudges:
        nudge.set()


async def _pause(stop: asyncio.Event, nudge: asyncio.Event, seconds: float) -> None:
    waits = {asyncio.ensure_future(stop.wait()), asyncio.ensure_future(nudge.wait())}
    try:
        await asyncio.wait(waits, timeout=seconds, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for waiting in waits:
            waiting.cancel()


async def _locked(db: AsyncSession) -> bool:
    return bool(
        await db.scalar(
            text("SELECT pg_try_advisory_xact_lock(:a, :b)"), {"a": _LOCK[0], "b": _LOCK[1]}
        )
    )


async def social_pass(
    sessions: async_sessionmaker[AsyncSession],
    cfg: graph.SocialConfig,
    api: graph.Graph,
    *,
    now: datetime,
) -> dict[str, int]:
    out = {"sent": 0, "comments": 0, "first": 0, "late": 0, "erased": 0}
    for _ in range(_SENDS_PER_PASS):
        async with sessions() as db, db.begin():
            if not await _locked(db):
                return out
            done = await inbox.queued_sends(db, cfg, api, now=now)
        if not done:
            break
        out["sent"] += done
    for name, work in (
        ("comments", inbox.comment_replies),
        ("first", inbox.first_replies),
        ("late", inbox.out_of_hours_replies),
    ):
        async with sessions() as db, db.begin():
            if not await _locked(db):
                return out
            out[name] = await work(db, cfg, api, now=now)
    async with sessions() as db, db.begin():
        out["erased"] = await inbox.erasure_sweep(db, now)
    return out


async def run(
    sessions: async_sessionmaker[AsyncSession], stop: asyncio.Event, *, first_delay: int = _TICK
) -> None:
    nudge = asyncio.Event()
    _nudges.append(nudge)
    try:
        await _pause(stop, nudge, first_delay)
        await _loop(sessions, stop, nudge)
    finally:
        _nudges.remove(nudge)


async def _loop(
    sessions: async_sessionmaker[AsyncSession], stop: asyncio.Event, nudge: asyncio.Event
) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        while not stop.is_set():
            nudge.clear()  # a send during this pass starts the next one at once
            cfg = graph.config()
            if cfg is not None:
                try:
                    await social_pass(
                        sessions, cfg, graph.Graph(cfg, client, timeout=8), now=datetime.now(UTC)
                    )
                except Exception:  # noqa: BLE001 - the loop must survive a bad tick
                    log.warning("messenger and instagram tick failed", exc_info=True)
            await _pause(stop, nudge, _TICK)


def attach(
    application: FastAPI, sessions: async_sessionmaker[AsyncSession], environment: str
) -> None:
    """Run the loop for the API's lifetime by wrapping the app's own lifespan."""
    if environment in {"local", "test"}:
        return
    inner = application.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[Any]:
        async with inner(app) as state:
            stop = asyncio.Event()
            task = asyncio.create_task(run(sessions, stop), name="lead-desk-social")
            try:
                yield state
            finally:
                stop.set()
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    application.router.lifespan_context = lifespan
