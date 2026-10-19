"""The WhatsApp and first-response loop, every 30 seconds inside the API.

- Auto replies (an instant first reply to new ad leads who said yes on their form, and
  a reply to messages after work hours), while AC's WhatsApp app is set up.
- Templates: each connected number's templates are read from Meta once a day (a
  template's review result also arrives by webhook).
- First-response SLA: new breaches are kept and the seller (and managers, if wanted)
  get a phone alert; breaches answered since get their reply time.
- Erasure: a lead that leaves Lead Desk takes its WhatsApp words with it.

One pass at a time across API processes (advisory lock 1802/1267).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from fastapi import FastAPI
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ac_platform.lead_desk import push, sla
from ac_platform.lead_desk.models import LeadWhatsAppNumber, LeadWhatsAppTemplate
from ac_platform.lead_desk.whatsapp import cloud, inbox

log = logging.getLogger(__name__)

_TICK = 30
_LOCK = (1802, 1267)  # one pass across API processes and slots
SYNC_EVERY = timedelta(days=1)


async def _locked(db: AsyncSession) -> bool:
    return bool(
        await db.scalar(
            text("SELECT pg_try_advisory_xact_lock(:a, :b)"), {"a": _LOCK[0], "b": _LOCK[1]}
        )
    )


async def whatsapp_pass(
    sessions: async_sessionmaker[AsyncSession],
    cfg: cloud.WhatsAppConfig,
    api: cloud.Cloud,
    *,
    now: datetime,
) -> dict[str, int]:
    out = {"first": 0, "late": 0, "synced": 0, "erased": 0}
    async with sessions() as db, db.begin():
        if not await _locked(db):
            return out
        out["first"] = await inbox.first_replies(db, cfg, api, now=now)
    async with sessions() as db, db.begin():
        if not await _locked(db):
            return out
        out["late"] = await inbox.out_of_hours_replies(db, cfg, api, now=now)
    async with sessions() as db:
        rows = (
            await db.scalars(
                select(LeadWhatsAppNumber).where(LeadWhatsAppNumber.status == "active")
            )
        ).all()
        last = {
            waba: at
            for waba, at in (
                await db.execute(
                    select(
                        LeadWhatsAppTemplate.waba_id, func.max(LeadWhatsAppTemplate.synced_at)
                    ).group_by(LeadWhatsAppTemplate.waba_id)
                )
            ).tuples()
        }
    for row in rows:
        if last.get(row.waba_id) and now - last[row.waba_id] < SYNC_EVERY:
            continue
        try:
            async with sessions() as db, db.begin():
                fresh = await db.get(LeadWhatsAppNumber, row.id)
                if fresh is not None and fresh.status == "active":
                    await inbox.sync_templates(db, cfg, api, fresh, now=now)
                    out["synced"] += 1
        except cloud.WhatsAppError as error:
            log.warning("whatsapp templates for number %s not synced: %s", row.id, error)
    async with sessions() as db, db.begin():
        out["erased"] = await inbox.erasure_sweep(db, now)
    return out


async def sla_pass(
    sessions: async_sessionmaker[AsyncSession],
    fcm: push.Fcm | None,
    client: httpx.AsyncClient,
    *,
    now: datetime,
) -> dict[str, int]:
    """Keep new breaches and alert once; record replies to earlier ones."""
    async with sessions() as db, db.begin():
        if not await _locked(db):
            return {"breached": 0, "alerted": 0, "settled": 0}
        breaches = await sla.find_breaches(db, now=now)
        settled = await sla.settle(db, now=now)
    alerted = 0
    if fcm is not None:
        for breach in breaches:
            for token in breach.tokens:
                alerted += await fcm.send(client, token, sla.alert_data(breach)) == "sent"
    return {"breached": len(breaches), "alerted": alerted, "settled": settled}


async def run(
    sessions: async_sessionmaker[AsyncSession], stop: asyncio.Event, *, first_delay: int = _TICK
) -> None:
    with suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=first_delay)
    fcm_cfg = push.config()
    fcm = push.Fcm(fcm_cfg) if fcm_cfg is not None else None
    async with httpx.AsyncClient(timeout=15) as client:
        while not stop.is_set():
            now = datetime.now(UTC)
            try:
                await sla_pass(sessions, fcm, client, now=now)
            except Exception:  # noqa: BLE001 - the loop must survive a bad tick
                log.warning("first-response tick failed", exc_info=True)
            cfg = cloud.config()
            if cfg is not None:
                try:
                    await whatsapp_pass(sessions, cfg, cloud.Cloud(cfg, client, timeout=8), now=now)
                except Exception:  # noqa: BLE001 - the loop must survive a bad tick
                    log.warning("whatsapp tick failed", exc_info=True)
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=_TICK)


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
            task = asyncio.create_task(run(sessions, stop), name="lead-desk-whatsapp-sla")
            try:
                yield state
            finally:
                stop.set()
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    application.router.lifespan_context = lifespan
