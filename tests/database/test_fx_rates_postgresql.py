"""Daily reference rates on PostgreSQL: stored once per day, never changed, read back by day,
and the feed read at most when the stored rates are old. A fake feed: no network."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ac_platform.fx import store
from ac_platform.fx.models import FxReferenceRate
from tests.database.conversation_harness import conversation_harness
from tests.database.test_conversation_postgresql import run
from tests.unit.fx.test_reference import FEED

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 21, 6, 0, tzinfo=UTC)


@pytest.fixture
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


class Feed:
    def __init__(self, text: str | None) -> None:
        self.text, self.reads = text, 0

    async def __call__(self, _url: str) -> str:
        self.reads += 1
        if self.text is None:
            raise OSError("feed down")
        return self.text


def test_rates_are_added_once_and_the_feed_is_read_only_when_old(
    postgres_harness: Engine,
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            feed = Feed(FEED)
            refresher = store.Refresher(feed)
            async with AsyncSession(engine) as database, database.begin():
                rates = await refresher.rates(database, NOW)
            assert rates == {
                date(2026, 10, 20): Decimal("88.3000"),
                date(2026, 10, 16): Decimal("88.0000"),
            }
            assert feed.reads == 1 and refresher.problem is None

            # Fresh (yesterday's rate is stored): no read, the stored rates as they are.
            async with AsyncSession(engine) as database, database.begin():
                again = await store.Refresher(feed).rates(database, NOW)
            assert again == rates and feed.reads == 1

            # Old and the feed is down: the stored rates, the problem said, no second try soon.
            down = store.Refresher(Feed(None))
            later = NOW + timedelta(days=5)
            async with AsyncSession(engine) as database, database.begin():
                assert await down.rates(database, later) == rates
                assert await down.rates(database, later + timedelta(hours=1)) == rates
            assert down.problem and down.fetch.reads == 1  # type: ignore[attr-defined]

            # A second add of the same days stores nothing new.
            async with AsyncSession(engine) as database, database.begin():
                added = await database.run_sync(
                    lambda sync: store.add(sync.connection(), rates, NOW)
                )
                count = await database.scalar(select(func.count()).select_from(FxReferenceRate))
            assert added == 0 and count == 2
        finally:
            await engine.dispose()

    run(exercise())
