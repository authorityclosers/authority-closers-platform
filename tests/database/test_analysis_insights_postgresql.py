"""Company analysis on PostgreSQL: one organisation's engine objects in the window,
current ones only, and no skill scores until a pointer review exists.

Disposable loopback PostgreSQL, fictional rows only; a local fake model, no network.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ac_platform.conversation_intelligence.analysis_insights import analysis_insights
from tests.database.conversation_harness import conversation_harness
from tests.database.test_call_data_postgresql import ROOT, FakeModel, _call, _process


@pytest.fixture
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def _read(engine_url: Any, organisation: Any, **options: Any) -> dict[str, Any]:
    async def go() -> dict[str, Any]:
        engine = create_async_engine(engine_url)
        try:
            async with AsyncSession(engine) as database:
                return await analysis_insights(database, organisation, **options)
        finally:
            await engine.dispose()

    return asyncio.run(go())


def test_one_organisations_current_objects_in_the_window(postgres_harness: Engine) -> None:
    seeded = _call(postgres_harness)
    assert _process(postgres_harness, seeded, FakeModel())["outcome"] == "succeeded"
    tenant = seeded["owner"].tenant_id

    found = _read(postgres_harness.url, tenant, days=30)
    assert found["calls_analysed"] == 1
    assert found["calls_scored"] == 0 and found["skills"] == []
    assert set(found["said"]) == {"objections", "questions", "pains", "goals"}
    assert all(item["calls"] == 1 for items in found["said"].values() for item in items)
    # Trends: the call is in this week, under its seller; no leads, so an empty funnel.
    assert found["calls"] == 1
    assert sum(week["calls"] for week in found["weeks"]) == 1
    assert sum(week["analysed"] for week in found["weeks"]) == 1
    assert [row["calls"] for row in found["people"]] == [1]
    assert found["people"][0]["name"]
    assert found["stages"]["leads"] == 0 and found["stages"]["version"] == 0
    # Another organisation, or a window before the call, sees nothing.
    assert _read(postgres_harness.url, uuid4(), days=30)["calls_analysed"] == 0
    past = datetime.now(UTC) + timedelta(days=60)
    assert _read(postgres_harness.url, tenant, days=30, now=past)["calls_analysed"] == 0
