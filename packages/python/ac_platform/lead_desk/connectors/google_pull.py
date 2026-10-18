"""Google Ads lead forms: turn an account on, and read its new leads on a schedule.

Turning an account on writes AC's webhook into its lead forms (``ensure_webhooks``)
and files the last 30 days of leads. Every 10 minutes the pull reads each active
account's newest submissions and files them through the same ``LeadDesk.ingest``
path as the webhook; a lead's reference is Google's click id, so one that arrives
both ways is filed once. One pull is one Google Ads API operation per account.
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

from ac_platform.lead_desk.connectors import google_ads
from ac_platform.lead_desk.connectors import google_ads_api as api
from ac_platform.lead_desk.connectors.meta_pull import Pulled
from ac_platform.lead_desk.models import LeadSource
from ac_platform.lead_desk.store import DeskError, LeadDesk, Viewer

log = logging.getLogger(__name__)

PULL_EVERY = 600  # seconds between pulls of one account
OVERLAP = 3600  # re-read the last hour, so a lead Google stamps late is not missed
_TICK = 60
_LOCK = (1802, 1264)  # one puller across API processes and slots
_OUTCOMES = ("created", "repeat", "known", "skipped")


class _Ads(Protocol):
    async def access_token(self, refresh_token: str) -> str: ...

    async def lead_forms(self, account: api.Account, access: str) -> list[api.LeadForm]: ...

    async def set_webhook(
        self, account: api.Account, form: api.LeadForm, access: str, *, url: str, key: str
    ) -> None: ...

    async def submissions(
        self, account: api.Account, access: str, *, since: int
    ) -> list[dict[str, Any]]: ...


@dataclass(slots=True)
class Webhooks:
    forms: int = 0
    sending: int = 0  # forms that post each new lead to Sales Xray now
    other: int = 0  # forms that keep someone else's webhook (the pull still reads them)
    failed: int = 0  # forms Google wouldn't change (the pull still reads them)


def _last(config: Mapping[str, Any]) -> int | None:
    value = config.get("last_pulled_at")
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def since(config: Mapping[str, Any], now: int) -> int:
    """From the last pull minus an hour, never further back than the connect backfill."""
    floor = now - api.BACKFILL_DAYS * 86400
    last = _last(config)
    return floor if last is None else max(floor, last - OVERLAP)


def due(config: Mapping[str, Any], now: int, every: int = PULL_EVERY) -> bool:
    last = _last(config)
    return last is None or now - last >= every - _TICK // 2


def webhook_url(app_url: str, source: LeadSource) -> str:
    return f"{app_url.rstrip('/')}/v1/lead-desk/capture/{source.id}/google-ads"


def _secrets(source: LeadSource, cfg: api.GoogleAdsConfig) -> tuple[api.Account, str, str]:
    config = source.config or {}
    account = api.account_of(config)
    refresh = api.unseal(
        cfg.token_key, config.get("token"), customer_id=account.customer_id, what="token"
    )
    key = api.unseal(cfg.token_key, config.get("key"), customer_id=account.customer_id, what="key")
    return account, refresh, key


async def ensure_webhooks(
    source: LeadSource, ads: _Ads, cfg: api.GoogleAdsConfig, *, app_url: str
) -> Webhooks:
    """Point every lead form of the account that has no other webhook at Sales Xray."""
    account, refresh, key = _secrets(source, cfg)
    access = await ads.access_token(refresh)
    url = webhook_url(app_url, source)
    result = Webhooks()
    for form in await ads.lead_forms(account, access):
        result.forms += 1
        plan = api.webhook_plan(form, url=url, key=key)
        if plan == "other":
            result.other += 1
            continue
        if plan == "set":
            try:
                await ads.set_webhook(account, form, access, url=url, key=key)
            except api.GoogleAdsApiError as error:
                log.warning("google ads webhook for form %s not set: %s", form.form_id, error)
                result.failed += 1
                continue
        result.sending += 1
    config = dict(source.config or {})
    config["webhooks"] = {
        "forms": result.forms,
        "sending": result.sending,
        "other": result.other,
        "failed": result.failed,
    }
    source.config = config
    return result


async def pull_source(
    desk: LeadDesk, source: LeadSource, ads: _Ads, cfg: api.GoogleAdsConfig, *, now: int
) -> Pulled:
    """Read one account's submissions since its last pull and file them; records the pull time."""
    config = dict(source.config or {})
    account, refresh, _ = _secrets(source, cfg)
    access = await ads.access_token(refresh)
    result = Pulled()
    for payload in await ads.submissions(account, access, since=since(config, now)):
        result.fetched += 1
        try:
            record = google_ads.to_record(payload)
        except google_ads.GoogleAdsError:
            result.skipped += 1
            continue
        _, outcome = await desk.ingest(
            record,
            source="webhook",
            source_label=source.label,
            source_ref=str(record.get("lead_id") or "")[:200] or None,
            actor=None,
        )
        key = outcome if outcome in _OUTCOMES else "skipped"
        setattr(result, key, getattr(result, key) + 1)
        if outcome in {"created", "repeat"}:
            source.received = int(source.received or 0) + 1
            source.last_received_at = desk.now
    config["last_pulled_at"] = now
    source.config = config
    return result


def _desk(database: AsyncSession, source: LeadSource) -> LeadDesk:
    return LeadDesk(
        database,
        Viewer(
            person_id=source.created_by_person_id,
            tenant_id=source.tenant_id,
            role="system",
            name=source.label,
        ),
    )


async def pull_due(
    sessions: async_sessionmaker[AsyncSession], cfg: api.GoogleAdsConfig, ads: _Ads, *, now: int
) -> int:
    """Pull every active Google Ads account that is due. Returns how many were pulled."""
    pulled = 0
    async with sessions() as database, database.begin():
        if not await database.scalar(
            text("SELECT pg_try_advisory_xact_lock(:a, :b)"), {"a": _LOCK[0], "b": _LOCK[1]}
        ):
            return 0
        sources = (
            await database.scalars(
                select(LeadSource)
                .where(LeadSource.kind == "webhook", LeadSource.active.is_(True))
                .order_by(LeadSource.created_at)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for source in sources:
            if not api.is_connector(source) or not due(source.config or {}, now):
                continue
            try:
                async with database.begin_nested():
                    counts = await pull_source(_desk(database, source), source, ads, cfg, now=now)
            except (api.GoogleAdsApiError, DeskError, KeyError, ValueError) as error:
                # One account's failure must not stop the others; it is retried next tick.
                log.warning("google ads pull for lead source %s failed: %s", source.id, error)
                continue
            pulled += 1
            if counts.created or counts.repeat:
                log.info(
                    "google ads pull filed %d new and %d repeat leads for lead source %s",
                    counts.created,
                    counts.repeat,
                    source.id,
                )
    return pulled


async def run_google_puller(
    sessions: async_sessionmaker[AsyncSession], stop: asyncio.Event, *, first_delay: int = _TICK
) -> None:
    """Every minute, pull the accounts that are due. Does nothing until Google Ads is set up."""
    with suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=first_delay)
    while not stop.is_set():
        cfg = api.config()
        if cfg is not None:
            try:
                await pull_due(sessions, cfg, api.Ads(cfg), now=int(time.time()))
            except Exception:  # noqa: BLE001 - the loop must survive a bad tick
                log.warning("google ads pull tick failed")
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
            task = asyncio.create_task(
                run_google_puller(sessions, stop), name="google-ads-lead-puller"
            )
            try:
                yield state
            finally:
                stop.set()
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    application.router.lifespan_context = lifespan
