"""Actual canonical joins and a PostgreSQL-enforced read-only export boundary."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from psycopg import AsyncConnection
from psycopg.conninfo import make_conninfo
from psycopg.errors import ReadOnlySqlTransaction
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row
from sqlalchemy import update

from ac_platform.conversation_intelligence import pipeline_timings
from ac_platform.conversation_intelligence.models import ConversationReportDraft
from ac_platform.conversation_intelligence.processing_plan import ProcessingPlanScheduler
from tests.database.test_conversation_authority_postgresql import _setup
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_processing_plan_postgresql import _accept, _quote, _view
from tests.database.test_conversation_worker_postgresql import _postgres_harness


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


def _dsn(url: Any) -> str:
    # SQLAlchemy URI query spaces use '+', while libpq expects literal options.
    return make_conninfo(
        **url.translate_connect_args(username="user", database="dbname"), **dict(url.query)
    )


def test_canonical_pipeline_timings_and_erased_delivery(
    postgres_harness: Any, tmp_path: Any
) -> None:
    async def exercise() -> None:
        since = datetime.now(UTC) - timedelta(seconds=1)
        setup = await _setup(postgres_harness, tmp_path)
        try:
            # The fixture's command clock is frozen at registration; advance
            # it past the completed local publication before accepting C2.
            setup = replace(
                setup,
                prepared=replace(
                    setup.prepared, state=replace(setup.prepared.state, now=datetime.now(UTC))
                ),
            )
            quote = await _quote(setup, "timing-export")
            await _accept(setup, quote, "timing-accept")
            scheduler = ProcessingPlanScheduler(setup.sessions, setup.authority)
            for _ in range(12):
                assert await setup.worker.run_once()
                assert await scheduler.step()
                if (await _view(setup, UUID(quote["id"])))["state"] == "completed":
                    break
            assert (await _view(setup, UUID(quote["id"])))["report_ready"] is True
            async with await AsyncConnection.connect(
                _dsn(setup.engine.url), autocommit=True, row_factory=dict_row
            ) as connection:
                result = await pipeline_timings.export_summary(connection, since=since)
                assert result["transaction_read_only"] is True
                assert result["plan_sample"] == {"n": 1, "truncated": False}
                assert result["plans"]["states"] == {"completed": 1}
                assert result["checkpoint_counts"]["C6"] == 1
                for stage in ("C2", "C4", "C5"):
                    measured = result["stages"][stage]
                    assert measured["runs"] == 1
                    assert measured["states"] == {"completed": 1}
                    assert measured["enqueue_to_dispatch"]["n"] == 1
                    assert measured["dispatch_to_receipt"]["n"] == 1
                    assert measured["enqueue_to_completed"]["n"] == 1
                assert result["stages"]["C0_C1"]["runs"] == 1
                assert result["stages"]["C0_C1"]["enqueue_to_dispatch"]["n"] == 0
                assert result["c1_c2_handoff"]["ambiguous_c1_artifacts"] == 0
                assert result["c1_c2_handoff"]["c1_publication_to_c2_dispatch"]["n"] == 1
                assert result["twenty_minute_under_60_seconds"] == "unverified"
                assert str(quote["id"]) not in json.dumps(result)
                assert "payload" not in json.dumps(result)
                assert connection.info.transaction_status == TransactionStatus.IDLE
                # This fixture has no acquisition-minute delivery event. Saving
                # a C6/draft does not fabricate that independent delivery clock.
                assert result["plans"]["bound_delivery_reports"] == 0
                assert result["plans"]["bound_saved_reports"] == 1
                assert result["plans"]["acceptance_to_report_saved"]["n"] == 1
                async with setup.sessions() as db, db.begin():
                        await db.execute(
                            update(ConversationReportDraft).values(
                                payload=None,
                                transcript=None,
                                evidence_receipt=None,
                                erased_at=datetime.now(UTC),
                            )
                    )
                erased = await pipeline_timings.export_summary(connection, since=since)
                assert erased["plans"]["bound_delivery_reports"] == 0
                assert erased["plans"]["bound_saved_reports"] == 0
                assert erased["plans"]["acceptance_to_delivery"]["n"] == 0
                truncated = await pipeline_timings.export_summary(connection, since=since, limit=1)
                assert truncated["run_sample"] == {"n": 1, "truncated": True}
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_snapshot_rejects_sql_mutation_and_closes_transaction(
    postgres_harness: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        async with await AsyncConnection.connect(
            _dsn(postgres_harness.url), autocommit=True, row_factory=dict_row
        ) as connection:
            monkeypatch.setattr(
                pipeline_timings,
                "RUNS_SQL",
                "UPDATE conversation_runs SET state = state "
                "WHERE created_at >= %(since)s AND created_at <= %(observed)s "
                "AND %(limit)s > 0 RETURNING state",
            )
            with pytest.raises(ReadOnlySqlTransaction):
                await pipeline_timings.export_summary(
                    connection, since=datetime.now(UTC) - timedelta(hours=1)
                )
            assert connection.info.transaction_status == TransactionStatus.IDLE
            cursor = await connection.execute("SELECT count(*) AS n FROM conversation_runs")
            assert (await cursor.fetchone()) == {"n": 0}

    run(exercise())


def test_existing_transaction_and_future_window_are_refused(postgres_harness: Any) -> None:
    async def exercise() -> None:
        async with await AsyncConnection.connect(
            _dsn(postgres_harness.url), autocommit=True, row_factory=dict_row
        ) as connection:
            async with connection.transaction():
                with pytest.raises(ValueError, match="pipeline_timing_idle_connection_required"):
                    await pipeline_timings.export_summary(connection, since=datetime.now(UTC))
            with pytest.raises(ValueError, match="pipeline_timing_snapshot_invalid"):
                await pipeline_timings.export_summary(
                    connection, since=datetime.now(UTC) + timedelta(hours=1)
                )
            assert connection.info.transaction_status == TransactionStatus.IDLE

    run(exercise())
