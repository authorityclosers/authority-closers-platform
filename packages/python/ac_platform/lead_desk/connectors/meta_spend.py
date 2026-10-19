"""Ad spend per Meta campaign for the Sales Xray CRM, and what each lead cost.

With its Continue with Meta connection (``ads_read``) Sales Xray reads, for each ad
account the organisation shared, what every campaign spent per day (Marketing API
insights, campaign level). The last 3 days are read again every hour (Meta keeps
adjusting recent days) and the last 30 days once a day. The numbers are the
organisation's own ad data, shown only to its owners and admins; Sales Xray never
pays for ads and shows no price of its own.

Cost per lead = a campaign's spend / the Meta leads that arrived here from it (their
``meta.campaign_id``); cost per customer uses the leads now marked won. Meta's own
lead count is shown beside it, so a gap (forms not connected, leads not pulled) shows.

No database lock is held while Meta answers: tenants are claimed in a short
transaction, Meta is read, then the rows are written in another.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Final
from uuid import UUID

import httpx
from fastapi import FastAPI
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ac_platform.lead_desk.connectors import meta, meta_capi
from ac_platform.lead_desk.models import LeadAdSpendDay, LeadDeskSettings

log = logging.getLogger(__name__)

KEY: Final[str] = "meta_spend"  # the organisation's sync state in its Lead Desk settings
LOOK_BACK_DAYS: Final[int] = 30
RECENT_DAYS: Final[int] = 3
EVERY: Final[timedelta] = timedelta(hours=1)
FULL_EVERY: Final[timedelta] = timedelta(days=1)
MAX_ACCOUNTS: Final[int] = 20
MAX_ROWS: Final[int] = 20_000
_TICK = 300
_LOCK = (1802, 1269)  # one claimer across API processes and slots
# Meta's lead actions, most specific first: Instant Form leads count under "lead".
LEAD_ACTIONS: Final[tuple[str, ...]] = (
    "lead",
    "onsite_conversion.lead_grouped",
    "offsite_conversion.fb_pixel_lead",
)


@dataclass(frozen=True, slots=True)
class SpendRow:
    ad_account_id: str
    campaign_id: str
    campaign_name: str
    day: date
    currency: str
    spend: Decimal
    impressions: int
    clicks: int
    meta_leads: int


def _int(value: Any) -> int:
    try:
        return max(0, int(Decimal(str(value))))
    except (InvalidOperation, ValueError, TypeError):
        return 0


def leads_from(actions: Any) -> int:
    """Meta's lead count for one row, from its ``actions``."""
    if not isinstance(actions, list):
        return 0
    found = {
        str(item.get("action_type")): item.get("value")
        for item in actions
        if isinstance(item, Mapping)
    }
    for name in LEAD_ACTIONS:
        if name in found:
            return _int(found[name])
    return 0


def parse_row(account_id: str, row: Mapping[str, Any], currency: str) -> SpendRow | None:
    campaign = str(row.get("campaign_id") or "")
    try:
        day = date.fromisoformat(str(row.get("date_start") or ""))
        spend = Decimal(str(row.get("spend") or "0")).quantize(Decimal("0.01"))
    except (ValueError, InvalidOperation):
        return None
    if not campaign.isdigit() or len(campaign) > 30 or spend < 0:
        return None
    return SpendRow(
        ad_account_id=account_id,
        campaign_id=campaign,
        campaign_name=str(row.get("campaign_name") or campaign)[:400],
        day=day,
        currency=(str(row.get("account_currency") or currency) or "USD").upper()[:3],
        spend=spend,
        impressions=_int(row.get("impressions")),
        clicks=_int(row.get("clicks")),
        meta_leads=leads_from(row.get("actions")),
    )


async def insights(
    graph: meta.Graph, token: str, account_id: str, *, since: date, until: date
) -> list[SpendRow]:
    """Each campaign's spend per day in one ad account."""
    rows: list[SpendRow] = []
    async for page in graph._pages(
        f"{account_id}/insights",
        limit=MAX_ROWS,
        level="campaign",
        time_increment=1,
        time_range=json.dumps({"since": since.isoformat(), "until": until.isoformat()}),
        fields="campaign_id,campaign_name,spend,impressions,clicks,actions,account_currency",
        access_token=token,
    ):
        for item in page:
            parsed = parse_row(account_id, item, "")
            if parsed is not None:
                rows.append(parsed)
    return rows


@dataclass(slots=True)
class Synced:
    tenants: int = 0
    rows: int = 0
    failed: list[str] = field(default_factory=list)


def _state(config: Mapping[str, Any]) -> dict[str, Any]:
    value = config.get(KEY)
    return dict(value) if isinstance(value, Mapping) else {}


def _when(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


async def claim(
    db: AsyncSession, *, now: datetime, only: UUID | None = None
) -> list[tuple[UUID, bool]]:
    """Organisations due a sync (connected to Meta, not read within the hour), stamped so
    another process skips them; True when the full 30 days are due."""
    query = select(LeadDeskSettings).with_for_update(skip_locked=True)
    if only is not None:
        query = query.where(LeadDeskSettings.tenant_id == only)
    due: list[tuple[UUID, bool]] = []
    for row in (await db.scalars(query)).all():
        config = row.config or {}
        if not isinstance(config.get(meta_capi.CONNECTION), Mapping):
            continue
        state = _state(config)
        last, full_at = _when(state.get("claimed_at")), _when(state.get("full_at"))
        if only is None and last is not None and now - last < EVERY:
            continue
        full = full_at is None or now - full_at >= FULL_EVERY
        row.config = {**config, KEY: {**state, "claimed_at": now.isoformat()}}
        due.append((row.tenant_id, full))
    return due


async def sync_tenant(
    sessions: async_sessionmaker[AsyncSession],
    cfg: meta.MetaConfig,
    graph: meta.Graph,
    tenant_id: UUID,
    *,
    full: bool,
    now: datetime,
) -> int:
    """Read one organisation's spend from Meta and keep it. Errors are kept for the page."""
    async with sessions() as db:
        settings = await db.get(LeadDeskSettings, tenant_id)
        token = meta_capi.connection_token(
            (settings.config if settings else None) or {}, cfg, tenant_id
        )
    until = now.date()
    since = until - timedelta(days=(LOOK_BACK_DAYS if full else RECENT_DAYS) - 1)
    rows: list[SpendRow] = []
    error: str | None = None
    # A connection made before ads_read was in the login, or without it: no spend, quietly.
    needs_ads_read = False
    accounts = 0
    if token is None:
        error = "Continue with Meta again to read your ad spend."
    else:
        try:
            shared = (await graph.ad_accounts(token))[:MAX_ACCOUNTS]
            accounts = len(shared)
            for account in shared:
                rows.extend(await insights(graph, token, account["id"], since=since, until=until))
        except meta.MetaError as error_found:
            if error_found.kind == "permission":
                needs_ads_read = True
            else:
                error = str(error_found)
    async with sessions() as db, db.begin():
        for row in rows[:MAX_ROWS]:
            values = {
                "campaign_name": row.campaign_name,
                "currency": row.currency,
                "spend": row.spend,
                "impressions": row.impressions,
                "clicks": row.clicks,
                "meta_leads": row.meta_leads,
                "synced_at": now,
            }
            await db.execute(
                insert(LeadAdSpendDay)
                .values(
                    tenant_id=tenant_id,
                    provider="meta",
                    ad_account_id=row.ad_account_id,
                    campaign_id=row.campaign_id,
                    day=row.day,
                    **values,
                )
                .on_conflict_do_update(
                    index_elements=["tenant_id", "provider", "ad_account_id", "campaign_id", "day"],
                    set_=values,
                )
            )
        settings = await db.get(LeadDeskSettings, tenant_id, with_for_update=True)
        if settings is not None:
            config = settings.config or {}
            state = _state(config)
            state.update(
                synced_at=now.isoformat() if error is None else state.get("synced_at"),
                full_at=now.isoformat() if full and error is None else state.get("full_at"),
                error=error,
                needs_ads_read=needs_ads_read,
                accounts=accounts if error is None else state.get("accounts"),
            )
            settings.config = {**config, KEY: state}
    return len(rows)


async def tick(
    sessions: async_sessionmaker[AsyncSession],
    cfg: meta.MetaConfig,
    graph: meta.Graph,
    *,
    now: datetime,
    only: UUID | None = None,
) -> Synced:
    out = Synced()
    async with sessions() as db, db.begin():
        if only is None and not await db.scalar(
            text("SELECT pg_try_advisory_xact_lock(:a, :b)"), {"a": _LOCK[0], "b": _LOCK[1]}
        ):
            return out
        due = await claim(db, now=now, only=only)
    for tenant_id, full in due:
        out.tenants += 1
        try:
            out.rows += await sync_tenant(sessions, cfg, graph, tenant_id, full=full, now=now)
        except Exception:  # noqa: BLE001 - one organisation must not stop the others
            log.warning("meta spend for %s not read", tenant_id, exc_info=True)
            out.failed.append(str(tenant_id))
    return out


async def run(
    sessions: async_sessionmaker[AsyncSession], stop: asyncio.Event, *, first_delay: int = 90
) -> None:
    with suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=first_delay)
    async with httpx.AsyncClient(timeout=30) as client:
        while not stop.is_set():
            cfg = meta.config()
            if cfg is not None:
                try:
                    await tick(sessions, cfg, meta.Graph(cfg, client), now=datetime.now(UTC))
                except Exception:  # noqa: BLE001 - the loop must survive a bad tick
                    log.warning("meta spend tick failed", exc_info=True)
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
            task = asyncio.create_task(run(sessions, stop), name="meta-spend")
            try:
                yield state
            finally:
                stop.set()
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    application.router.lifespan_context = lifespan


# ----- the report -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CampaignSpend:
    ad_account_id: str
    campaign_id: str
    campaign_name: str
    currency: str
    spend: Decimal
    impressions: int
    clicks: int
    meta_leads: int
    leads: int
    won: int

    @property
    def per_lead(self) -> Decimal | None:
        return (self.spend / self.leads).quantize(Decimal("0.01")) if self.leads else None

    @property
    def per_customer(self) -> Decimal | None:
        return (self.spend / self.won).quantize(Decimal("0.01")) if self.won else None


_LEADS = """
    SELECT CAST(l.payload AS JSONB) -> 'meta' ->> 'campaign_id' AS campaign,
           COUNT(*) AS leads,
           COUNT(*) FILTER (WHERE l.stage = 'won') AS won
    FROM lead_desk_leads l
    WHERE l.tenant_id = :tenant AND l.source = 'meta'
      AND l.created_at >= :start AND l.created_at < :end
    GROUP BY 1
"""


async def report(
    db: AsyncSession, tenant_id: UUID, *, start: date, end: date
) -> list[CampaignSpend]:
    """Each campaign's spend from ``start`` to ``end`` (both included), with the leads
    that arrived here from it in those days; the biggest spender first."""
    spent = (
        await db.execute(
            select(
                LeadAdSpendDay.ad_account_id,
                LeadAdSpendDay.campaign_id,
                func.max(LeadAdSpendDay.campaign_name),
                LeadAdSpendDay.currency,
                func.sum(LeadAdSpendDay.spend),
                func.sum(LeadAdSpendDay.impressions),
                func.sum(LeadAdSpendDay.clicks),
                func.sum(LeadAdSpendDay.meta_leads),
            )
            .where(
                LeadAdSpendDay.tenant_id == tenant_id,
                LeadAdSpendDay.day >= start,
                LeadAdSpendDay.day <= end,
            )
            .group_by(
                LeadAdSpendDay.ad_account_id, LeadAdSpendDay.campaign_id, LeadAdSpendDay.currency
            )
        )
    ).all()
    here = {
        str(row.campaign): (int(row.leads), int(row.won))
        for row in (
            await db.execute(
                text(_LEADS),
                {
                    "tenant": tenant_id,
                    "start": datetime.combine(start, time.min, tzinfo=UTC),
                    "end": datetime.combine(end + timedelta(days=1), time.min, tzinfo=UTC),
                },
            )
        ).all()
        if row.campaign
    }
    out = [
        CampaignSpend(
            ad_account_id=account,
            campaign_id=campaign,
            campaign_name=str(name),
            currency=currency,
            spend=Decimal(spend or 0),
            impressions=int(impressions or 0),
            clicks=int(clicks or 0),
            meta_leads=int(meta_leads or 0),
            leads=here.get(campaign, (0, 0))[0],
            won=here.get(campaign, (0, 0))[1],
        )
        for account, campaign, name, currency, spend, impressions, clicks, meta_leads in spent
    ]
    out.sort(key=lambda item: (-item.spend, item.campaign_name))
    return out


def totals(campaigns: Sequence[CampaignSpend]) -> dict[str, dict[str, Any]]:
    """Spend, leads and cost per lead per currency (accounts can bill in different ones)."""
    out: dict[str, dict[str, Any]] = {}
    for item in campaigns:
        bucket = out.setdefault(item.currency, {"spend": Decimal(0), "leads": 0, "won": 0})
        bucket["spend"] += item.spend
        bucket["leads"] += item.leads
        bucket["won"] += item.won
    for bucket in out.values():
        bucket["per_lead"] = (
            (bucket["spend"] / bucket["leads"]).quantize(Decimal("0.01"))
            if bucket["leads"]
            else None
        )
    return out


def sync_state(config: Mapping[str, Any]) -> dict[str, Any]:
    state = _state(config)
    return {
        "connected": isinstance(config.get(meta_capi.CONNECTION), Mapping),
        "synced_at": _when(state.get("synced_at")),
        "error": state.get("error") if isinstance(state.get("error"), str) else None,
        "accounts": state.get("accounts") if isinstance(state.get("accounts"), int) else None,
        "needs_ads_read": state.get("needs_ads_read") is True,
    }
