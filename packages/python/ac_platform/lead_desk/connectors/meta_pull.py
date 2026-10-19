"""Meta Lead Ads pull: read each connected Page's new leads on a schedule.

Meta holds real-time lead webhooks while an app is in development mode, and a test
app (dev, staging) never leaves it, so without a pull their leads would arrive only
when a Page is connected. Every few minutes the pull reads each active Page's recent
leads with its sealed token and files them through the same ``LeadDesk.ingest`` path
as the webhook. The Meta lead id is the source reference, so a lead that arrives by
webhook and by pull is filed once. On production the pull is the safety net for a
webhook Meta drops.

The same tick moves each Page's "Bring in older leads" along (``meta_backfill``), and
keeps the Page's list of forms fresh, so the page can say which forms are covered. A
pull that Meta refuses leaves its reason on the Page (``last_error``) for the manager.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ac_platform.lead_desk.connectors import meta, meta_backfill
from ac_platform.lead_desk.models import LeadSource
from ac_platform.lead_desk.store import DeskError, LeadDesk, Viewer

log = logging.getLogger(__name__)

PULL_EVERY = 600  # seconds between pulls of one Page
OVERLAP = 3600  # re-read the last hour, so a lead Meta stamps late is not missed
_TICK = 60
_LOCK = (1802, 1261)  # one puller across API processes and slots
_OUTCOMES = ("created", "repeat", "known", "skipped")


class _Graph(Protocol):
    async def forms(self, page_id: str, page_token: str) -> list[dict[str, str]]: ...

    async def recent_leads(
        self, form_ids: list[str], page_token: str, *, since: int
    ) -> list[dict[str, Any]]: ...

    async def leads_page(
        self, form_id: str, page_token: str, *, since: int, after: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None]: ...


@dataclass(slots=True)
class Pulled:
    fetched: int = 0
    created: int = 0
    repeat: int = 0
    known: int = 0
    skipped: int = 0


def _last(config: Mapping[str, Any]) -> int | None:
    value = config.get("last_pulled_at")
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def since(config: Mapping[str, Any], now: int) -> int:
    """From the last pull minus an hour, never further back than a week (older leads come
    in through the backfill)."""
    floor = now - meta.PULL_DAYS * 86400
    last = _last(config)
    return floor if last is None else max(floor, last - OVERLAP)


def failed(config: Mapping[str, Any], error: meta.MetaError, now: int) -> dict[str, Any]:
    """The source config with Meta's refusal kept for the manager to see."""
    return {**config, "last_error": {"at": now, "kind": error.kind, "text": str(error)[:300]}}


def due(config: Mapping[str, Any], now: int, every: int = PULL_EVERY) -> bool:
    last = _last(config)
    return last is None or now - last >= every - _TICK // 2


async def pull_source(
    desk: LeadDesk, source: LeadSource, graph: _Graph, cfg: meta.MetaConfig, *, now: int
) -> Pulled:
    """Read one Page's leads since its last pull and file them; records the pull time."""
    config = dict(source.config or {})
    page_id = str(config.get("page_id") or "")
    token = meta.unseal(cfg.token_key, config["token"], page_id=page_id)
    forms = config.get("forms", "all")
    if forms == "all":
        # Every form on the Page, read afresh each time, so a new form comes in by itself.
        listed = await graph.forms(page_id, token)
        config = meta_backfill.remember_forms(config, listed)
        form_ids = [str(form["id"]) for form in listed]
    else:
        form_ids = [str(form) for form in forms or []]
    result = Pulled()
    page_name = str(config.get("page_name") or "")
    for lead in await graph.recent_leads(form_ids, token, since=since(config, now)):
        result.fetched += 1
        outcome = await meta_backfill.file_lead(desk, source, lead, page_name=page_name)
        key = outcome if outcome in _OUTCOMES else "skipped"
        setattr(result, key, getattr(result, key) + 1)
    config["last_pulled_at"] = now
    config.pop("last_error", None)
    source.config = config
    return result


async def pull_due(
    sessions: async_sessionmaker[AsyncSession], cfg: meta.MetaConfig, graph: _Graph, *, now: int
) -> int:
    """Pull every active Meta Page that is due. Returns how many Pages were pulled."""
    pulled = 0
    async with sessions() as database, database.begin():
        if not await database.scalar(
            text("SELECT pg_try_advisory_xact_lock(:a, :b)"), {"a": _LOCK[0], "b": _LOCK[1]}
        ):
            return 0
        sources = (
            await database.scalars(
                select(LeadSource)
                .where(LeadSource.kind == "meta", LeadSource.active.is_(True))
                .order_by(LeadSource.created_at)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for source in sources:
            pull = due(source.config or {}, now)
            backfill = meta_backfill.running(source.config or {})
            if not (pull or backfill):
                continue
            desk = LeadDesk(
                database,
                Viewer(
                    person_id=source.created_by_person_id,
                    tenant_id=source.tenant_id,
                    role="system",
                    name=source.label,
                ),
            )
            if backfill:
                try:
                    async with database.begin_nested():
                        await meta_backfill.step(desk, source, graph, cfg, now=now)
                except (DeskError, KeyError, ValueError) as error:
                    log.warning("meta backfill for lead source %s failed: %s", source.id, error)
                    await database.refresh(source)
            if not pull:
                continue
            try:
                async with database.begin_nested():
                    counts = await pull_source(desk, source, graph, cfg, now=now)
            except (meta.MetaError, DeskError, KeyError, ValueError) as error:
                # One Page's failure must not stop the others; it is retried next tick.
                log.warning("meta pull for lead source %s failed: %s", source.id, error)
                await database.refresh(source)
                if isinstance(error, meta.MetaError):
                    source.config = failed(
                        {**(source.config or {}), "last_pulled_at": now}, error, now
                    )
                continue
            pulled += 1
            if counts.created or counts.repeat:
                log.info(
                    "meta pull filed %d new and %d repeat leads for lead source %s",
                    counts.created,
                    counts.repeat,
                    source.id,
                )
    return pulled


async def run_meta_puller(
    sessions: async_sessionmaker[AsyncSession], stop: asyncio.Event, *, first_delay: int = _TICK
) -> None:
    """Every minute, pull the Pages that are due. Does nothing until Meta is set up."""
    with suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=first_delay)
    while not stop.is_set():
        cfg = meta.config()
        if cfg is not None:
            try:
                await pull_due(sessions, cfg, meta.Graph(cfg), now=int(time.time()))
            except Exception:  # noqa: BLE001 - the loop must survive a bad tick
                log.warning("meta pull tick failed")
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=_TICK)


def attach(
    application: FastAPI, sessions: async_sessionmaker[AsyncSession], environment: str
) -> None:
    """Run the puller for the API's lifetime by wrapping the app's own lifespan."""
    if environment in {"local", "test"}:
        return
    inner = application.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[Any]:
        async with inner(app) as state:
            stop = asyncio.Event()
            task = asyncio.create_task(run_meta_puller(sessions, stop), name="meta-lead-puller")
            try:
                yield state
            finally:
                stop.set()
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    application.router.lifespan_context = lifespan
