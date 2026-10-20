"""Stored daily rates: read them, and add the days the ECB feed has that are missing.

Rates are only ever added (the ECB's published rates are final). A refresh is tried at most
every six hours per process and only when the newest stored day is more than a day old; a
feed that can't be read leaves the stored rates as they are, and Admin says how old they are.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ac_platform.fx.models import FxReferenceRate
from ac_platform.fx.reference import ECB_90_DAYS, SOURCE, parse_ecb

RETRY = timedelta(hours=6)
STALE = timedelta(days=1)
Fetch = Callable[[str], Awaitable[str]]


async def fetch_text(url: str) -> str:
    """A small public document (no credentials, no redirects, 10 seconds at most)."""
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
        answer = await client.get(url, headers={"Accept": "application/xml, text/xml"})
        answer.raise_for_status()
        if len(answer.content) > 2_000_000:
            raise ValueError("feed too large")
        return answer.text


def stored(connection: Any) -> dict[date, Decimal]:
    """Every stored USD to INR rate by day."""
    return {
        day: Decimal(rate)
        for day, rate in connection.execute(
            select(FxReferenceRate.day, FxReferenceRate.rate).where(
                FxReferenceRate.base == "USD",
                FxReferenceRate.quote == "INR",
                FxReferenceRate.source == SOURCE,
            )
        )
    }


def add(connection: Any, rates: dict[date, Decimal], now: datetime) -> int:
    """Store the days not stored yet; returns how many were added."""
    known = stored(connection)
    added = 0
    for day, rate in sorted(rates.items()):
        if day in known:
            continue
        connection.execute(
            insert(FxReferenceRate)
            .values(
                id=uuid4(),
                day=day,
                base="USD",
                quote="INR",
                rate=rate,
                source=SOURCE,
                fetched_at=now,
            )
            .on_conflict_do_nothing(constraint="uq_fx_reference_rates_day")
        )
        added += 1
    return added


class Refresher:
    """At most one feed read every six hours per process, and only when the rates are old."""

    def __init__(self, fetch: Fetch = fetch_text) -> None:
        self.fetch = fetch
        self.tried_at: datetime | None = None
        self.problem: str | None = None

    async def rates(self, database: Any, now: datetime | None = None) -> dict[date, Decimal]:
        now = now or datetime.now(UTC)
        known: dict[date, Decimal] = await database.run_sync(lambda sync: stored(sync.connection()))
        newest = max(known) if known else None
        fresh = newest is not None and now.date() - newest <= STALE
        if fresh or (self.tried_at is not None and now - self.tried_at < RETRY):
            return known
        self.tried_at = now
        try:
            parsed = parse_ecb(await self.fetch(ECB_90_DAYS))
        except Exception:  # noqa: BLE001 - an unreadable feed keeps the stored rates
            self.problem = "The ECB reference rates could not be read just now."
            return known
        self.problem = None if parsed else "The ECB feed had no rupee rates."
        if parsed:
            await database.run_sync(lambda sync: add(sync.connection(), parsed, now))
        return {**known, **{day: rate for day, rate in parsed.items() if day not in known}}


REFRESHER = Refresher()
