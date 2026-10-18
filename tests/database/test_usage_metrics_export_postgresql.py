"""Usage metrics export (19 Oct 2026): the collector's SQL on the real schema.

A synthetic Scribe call runs through the real inference worker with a local fake
broker and leaves the open hold every provider call leaves. The export then runs
the way ac-metrics-collect runs it: one statement in a read-only transaction.
Disposable loopback PostgreSQL; no provider credentials or network calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ac_platform.conversation_intelligence.cost_metrics import SCHEMA, parse_export, price
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_worker_postgresql import (  # type: ignore[attr-defined]
    _postgres_harness,
)
from tests.database.test_provider_hold_settlement_postgresql import _uncertain_hold

EXPORT_SQL = Path(__file__).resolve().parents[2] / "infra" / "metrics" / "usage-metrics-export.sql"


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()  # type: ignore[attr-defined]


def test_export_reads_a_real_step_and_its_open_hold_read_only(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        engine, _sessions, prepared, reservation_id = await _uncertain_hold(
            postgres_harness, tmp_path, max_cost_paise=2_000
        )
        try:
            async with engine.connect() as connection, connection.begin():
                await connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                await connection.exec_driver_sql("SET LOCAL ac.metrics_environment = 'staging'")
                await connection.exec_driver_sql("SET LOCAL ac.metrics_days = '30'")
                result = await connection.exec_driver_sql(EXPORT_SQL.read_text(encoding="utf-8"))
                raw = result.scalar_one()
        finally:
            await engine.dispose()
        document = raw if isinstance(raw, dict) else json.loads(raw)
        assert document["schema"] == SCHEMA and document["environment"] == "staging"
        assert document["window_days"] == 30

        export = parse_export("staging", document)
        call_id = str(prepared.recording_id)
        assert [call.id for call in export.calls] == [call_id]
        assert export.calls[0].kind == "real" and export.calls[0].audio_ms > 0
        (step,) = [step for step in export.steps if step.stage == "C2"]
        assert (step.call, step.provider, step.model, step.status) == (
            call_id,
            "elevenlabs",
            "scribe_v2",
            "succeeded",
        )
        assert step.paise == price("elevenlabs", "scribe_v2", None, step.audio_ms) > 0
        (hold,) = [row for row in document["holds"] if row["state"] == "uncertain"]
        assert hold["ref"] == "provider-cost-reconciliation" and hold["held_paise"] == 2_000
        assert reservation_id  # the same hold the settlement test settles
        text = json.dumps(document)
        assert prepared.data.hex()[:32] not in text  # no audio, only numbers and labels

    run(exercise())
