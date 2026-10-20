"""Usage metrics export (19 Oct 2026): the collector's SQL on the real schema.

A synthetic Scribe call runs through the real inference worker with a local fake
broker and leaves the open hold every provider call leaves. The export then runs
the way ac-metrics-collect runs it: one statement in a read-only transaction.
Disposable loopback PostgreSQL; no provider credentials or network calls.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from ac_platform.conversation_intelligence.cost_metrics import SCHEMA, parse_export, price
from ac_platform.conversation_intelligence.models import ConversationRecording
from ac_platform.usage_people.pseudonyms import ensure_key, names_for, pseudonym
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

        async def export_now() -> dict[str, Any]:
            async with engine.connect() as connection, connection.begin():
                await connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                await connection.exec_driver_sql("SET LOCAL ac.metrics_environment = 'staging'")
                await connection.exec_driver_sql("SET LOCAL ac.metrics_days = '30'")
                result = await connection.exec_driver_sql(EXPORT_SQL.read_text(encoding="utf-8"))
                raw = result.scalar_one()
            return raw if isinstance(raw, dict) else json.loads(raw)

        try:
            # Before this environment has a pseudonym key: no person, and never a name.
            before = await export_now()
            assert [call["person"] for call in before["calls"]] == [None]
            assert all(set(row) == {"id", "kind"} for row in before["companies"])
            now = datetime.now(UTC)
            async with engine.begin() as connection:
                inner, outer = await connection.run_sync(lambda sync: ensure_key(sync, now))
                person_id = (
                    await connection.execute(
                        select(ConversationRecording.person_id).where(
                            ConversationRecording.id == prepared.recording_id
                        )
                    )
                ).scalar_one()
            document = await export_now()
            async with engine.begin() as connection:
                named = await connection.run_sync(
                    lambda sync: names_for(sync, [document["calls"][0]["person"]], now)
                )
        finally:
            await engine.dispose()
        # The export's SQL HMAC is the app's: Admin can name this environment's people.
        expected = pseudonym(inner, outer, person_id)
        assert document["calls"][0]["person"] == expected
        assert list(named) == [expected] and all(named.values())
        assert str(person_id) not in json.dumps(document)
        assert document["schema"] == SCHEMA and document["environment"] == "staging"
        assert document["window_days"] == 30
        assert document["ai_work"] == []  # every paid AI feature is read; none ran here

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
