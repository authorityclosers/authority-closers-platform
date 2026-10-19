"""Analysis health, Phase 4, on PostgreSQL: the engine's runs and Review 2.0 answers read back.

Disposable loopback PostgreSQL, fictional rows only; a local fake model, no network.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ac_platform.call_data.models import CallDataRun
from ac_platform.conversation_intelligence.analysis_health_engine import (
    engine_health,
    review_health,
)
from ac_platform.conversation_intelligence.review_verdicts import (
    erase_review_verdicts_for_recording,
)
from tests.database.conversation_harness import conversation_harness
from tests.database.test_call_data_postgresql import ROOT
from tests.database.test_review_verdicts_postgresql import (
    _designate,
    _save,
    _seeded_call,
    _with_service,
)


@pytest.fixture
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def _read(engine_url: Any, work: Any) -> Any:
    async def go() -> Any:
        engine = create_async_engine(engine_url)
        try:
            async with AsyncSession(engine) as database, database.begin():
                return await work(database)
        finally:
            await engine.dispose()

    return asyncio.run(go())


def test_engine_runs_per_pipeline_and_review_answers_read_back(postgres_harness: Engine) -> None:
    seeded = _seeded_call(postgres_harness)  # one fast run: a running row, then success
    owner, url = seeded["owner"], postgres_harness.url
    now = datetime.now(UTC)
    with postgres_harness.begin() as connection:
        done = (
            connection.execute(
                select(CallDataRun.__table__).where(
                    CallDataRun.recording_id == seeded["recording_id"],
                    CallDataRun.state == "succeeded",
                )
            )
            .mappings()
            .one()
        )
        # Every row names every column: an insert of many rows binds the first row's keys.
        base = {
            **{
                key: done[key]
                for key in (
                    "tenant_id",
                    "recording_id",
                    "person_id",
                    "taxonomy_version",
                    "trigger",
                    "created_by",
                )
            },
            "reason_code": None,
            "cost_inr": None,
            "supersedes_id": None,
        }
        quiet, started = uuid4(), uuid4()
        connection.execute(
            insert(CallDataRun),
            [
                # A fast run that never reported back.
                {
                    **base,
                    "id": quiet,
                    "pipeline": "fast",
                    "pipeline_version": done["pipeline_version"],
                    "state": "running",
                    "created_at": now - timedelta(hours=2),
                },
                # A deep run that failed, and a deep skip.
                {
                    **base,
                    "id": started,
                    "pipeline": "deep",
                    "pipeline_version": "deep-test",
                    "state": "running",
                    "created_at": now - timedelta(minutes=10),
                },
                {
                    **base,
                    "id": uuid4(),
                    "pipeline": "deep",
                    "pipeline_version": "deep-test",
                    "state": "failed",
                    "reason_code": "deep_parse_failed",
                    "cost_inr": Decimal("0.0500"),
                    "supersedes_id": started,
                    "created_at": now - timedelta(minutes=9),
                },
                {
                    **base,
                    "id": uuid4(),
                    "pipeline": "deep",
                    "pipeline_version": "deep-test",
                    "state": "skipped",
                    "reason_code": "too_long",
                    "created_at": now - timedelta(minutes=8),
                },
            ],
        )

    since = now - timedelta(days=1)
    scope = (owner.tenant_id,)

    async def engine(database: AsyncSession) -> Any:
        return await engine_health(database, scope, since=since, now=now)

    view = _read(url, engine)
    fast, deep = view["pipelines"]
    assert (fast["runs"], fast["succeeded"], fast["calls"], fast["quiet"]) == (1, 1, 1, 1)
    assert fast["success_share"] == 1.0 and fast["version"] == done["pipeline_version"]
    assert fast["time"]["count"] == 1
    assert (deep["runs"], deep["failed"], deep["skipped"], deep["running"]) == (2, 1, 1, 0)
    assert deep["success_share"] == 0.0 and deep["cost_inr"] == 0.05
    assert deep["reasons"] == [
        {"state": "failed", "code": "deep_parse_failed", "runs": 1},
        {"state": "skipped", "code": "too_long", "runs": 1},
    ]
    assert [item["run_id"] for item in view["quiet"]] == [str(quiet)]
    assert view["truncated"] is False

    # Another organisation's runs never show.
    async def elsewhere(database: AsyncSession) -> Any:
        return await engine_health(database, (uuid4(),), since=since, now=now)

    assert all(item["runs"] == 0 for item in _read(url, elsewhere)["pipelines"])

    # Review 2.0: only each reviewer's current answer counts.
    _designate(postgres_harness, owner.person_id)
    _with_service(url, owner.tenant_id, _save(seeded, answer={"value": "correct"}))
    _with_service(url, owner.tenant_id, _save(seeded, answer={"value": "wrong"}))
    _with_service(
        url, owner.tenant_id, _save(seeded, question_key="fix", answer={"text": "Ira, not Amit"})
    )

    async def review(database: AsyncSession) -> Any:
        return await review_health(database, owner.tenant_id, scope, since=since)

    measured = _read(url, review)
    sales = next(item for item in measured["pipelines"] if item["key"] == "analysis-sales")
    target = seeded["target"]
    assert (sales["answers"], sales["right"], sales["wrong"]) == (2, 0, 1)
    assert sales["right_share"] == 0.0
    assert sales["types"] == [
        {"type": target.type_key, "answers": 1, "right": 0, "wrong": 1, "right_share": 0.0}
    ]
    assert [item["answers"] for item in measured["engine_versions"]] == [1]
    assert measured["reviewers"][0]["answers"] == 2
    assert measured["truncated"] is False

    # Call erasure empties the answers, and the measures with them.
    async def erase(database: AsyncSession) -> Any:
        return await erase_review_verdicts_for_recording(
            database, UUID(str(seeded["recording_id"])), datetime.now(UTC)
        )

    assert _read(url, erase) == 3
    assert _read(url, review)["answers"] == 0
