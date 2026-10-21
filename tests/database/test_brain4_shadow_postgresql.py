"""Brain 4.0 shadow reads: admitted, spend-guarded, saved as a beta, erased with the call.

Disposable-loopback PostgreSQL with the real imported-report fixture (synthetic audio and
transcript). The provider is a local fake: no network, no key.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.ai_spend import guard as spend_guard
from ac_platform.ai_spend import ledger
from ac_platform.ai_spend import store as spend_store
from ac_platform.conversation_intelligence import brain4, brain4_shadow
from ac_platform.conversation_intelligence.brain4_models import ConversationBrain4Review
from ac_platform.conversation_intelligence.models import ConversationPermission
from ac_platform.conversation_intelligence.pointer_review import (
    erase_pointer_reviews_for_recording,
    latest_review,
    payload_sha256,
)
from ac_platform.conversation_intelligence.pointer_review_cli import _segments
from ac_platform.conversation_intelligence.pointer_review_models import ConversationPointerReview
from ac_platform.db.models import model_metadata
from tests.database.test_conversation_postgresql import (
    postgres_harness as _postgres_harness,
)
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_reports_postgresql import ReportFixture, _build_fixture
from tests.database.test_pointer_review_admission_postgresql import _report

ROOT = Path(__file__).parents[2]


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()  # type: ignore[attr-defined]


@pytest.fixture
def report_fixture(
    postgres_harness: Any, tmp_path_factory: pytest.TempPathFactory
) -> ReportFixture:
    return run(_build_fixture(postgres_harness, tmp_path_factory.mktemp("brain4-shadow")))


def migration() -> Any:
    path = ROOT / "db/migrations/versions/20261021_0117_brain4_reviews.py"
    spec = importlib.util.spec_from_file_location("brain4_migration_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_is_additive_and_passes_the_schema_gate_rules() -> None:
    from scripts.ci.migration_schema_gate import check_operations
    from scripts.ops.migration_safety import classify_source

    module = migration()
    assert (module.revision, module.down_revision) == ("20261021_0117", "20261021_0116")
    path = Path(module.__file__)
    item = classify_source(path.read_text(), str(path))
    check_operations([item], set())
    assert item.verdict == "additive"


def test_empty_migration_downgrades_reupgrades_and_matches_the_models(
    postgres_harness: Any,
) -> None:
    module = migration()
    with postgres_harness.begin() as connection:
        assert "conversation_brain4_reviews" in inspect(connection).get_table_names()
        context = MigrationContext.configure(connection, opts={"target_metadata": model_metadata()})
        with Operations.context(context):
            module.downgrade()
            assert "conversation_brain4_reviews" not in inspect(connection).get_table_names()
            module.upgrade()
        assert compare_metadata(MigrationContext.configure(connection), model_metadata()) == []


def answer(segment_ids: list[str]) -> dict[str, Any]:
    first = segment_ids[:1]
    return {
        "call_type": "inbound",
        "dimensions": [
            {
                "id": dimension,
                "applicability": "applicable",
                "rating": 3,
                "confidence": "medium",
                "evidence": first,
                "observed": "You asked what happens next.",
                "coaching": "On your next relevant call, ask why.",
                "ethics_gate": "PASS" if dimension == "D07" else None,
            }
            for dimension in brain4.DIMENSION_IDS
        ],
    }


def test_a_shadow_read_is_admitted_saved_counted_shown_and_erased(
    postgres_harness: Any, report_fixture: ReportFixture
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            report = await _report(sessions, report_fixture)
            async with sessions() as session:
                segments = await session.run_sync(
                    lambda sync: _segments(sync.connection(), report["draft_id"])
                )
            ids = [str(segment["id"]) for segment in segments]
            bodies: list[dict[str, Any]] = []

            def provider(body: dict[str, Any]) -> dict[str, Any]:
                bodies.append(body)
                return {
                    "candidates": [{"content": {"parts": [{"text": json.dumps(answer(ids))}]}}],
                    "usageMetadata": {"promptTokenCount": 9_000, "candidatesTokenCount": 2_100},
                }

            # Development's defaults: background off, the feature at ₹0.
            async with sessions() as session:
                refusal = await spend_guard.check_async(
                    session, brain4_shadow.FEATURE, environment="development"
                )
            assert refusal is not None and refusal.code == "ai_spend_background_off"
            async with sessions() as session, session.begin():
                await spend_store.save(
                    session,
                    "development",
                    {"background_enabled": True},
                    person_id=None,
                    reason="fictional test",
                    now=datetime.now(UTC),
                )
            async with sessions() as session:
                refusal = await spend_guard.check_async(
                    session, brain4_shadow.FEATURE, environment="development"
                )
            assert refusal is not None and refusal.code == "ai_spend_feature_cap"

            line = await brain4_shadow.read_one(sessions, report, call_provider=provider)
            assert line["outcome"] == "saved" and line["rated"] == 18
            assert len(bodies) == 1
            body = bodies[0]
            assert body["systemInstruction"]["parts"][0]["text"].startswith("BRAIN4_SHADOW")
            assert body["generationConfig"]["responseJsonSchema"] == brain4.response_schema()
            envelope = {
                "recording_id": report["recording_id"],
                "run_id": report["run_id"],
                "source_sha256": report["source_sha256"],
                "transcript_revision": report["transcript_revision"],
            }
            async with sessions() as session:
                read = await brain4_shadow.latest(session, envelope)
                spent = await session.run_sync(
                    lambda sync: ledger.totals(
                        ledger.read(sync.connection(), datetime.now(UTC) - timedelta(hours=1))
                    )
                )
            assert read is not None and read["status"] == "beta"
            assert [e["segment_id"] for e in read["dimensions"][0]["evidence"]] == ids[:1]
            assert spent.by_feature.get("brain4_shadow", 0) > 0
            # Read once: the next pass finds nothing to read for this report.
            async with sessions() as session:
                again = await session.run_sync(
                    lambda sync: brain4_shadow.recent_reports(
                        sync.connection(), datetime.now(UTC), 10
                    )
                )
            assert report["draft_id"] not in {item["draft_id"] for item in again}

            # The Report's review read carries the shadow read when the review has none.
            pointer = {"version": "pointer-review/1", "overall": {"score": 70}, "pointers": []}
            async with sessions() as session, session.begin():
                session.add(
                    ConversationPointerReview(
                        id=uuid4(),
                        tenant_id=report["tenant_id"],
                        recording_id=report["recording_id"],
                        run_id=report["run_id"],
                        report_draft_id=report["draft_id"],
                        source_sha256=report["source_sha256"],
                        transcript_revision=report["transcript_revision"],
                        version="pointer-review/1",
                        model_id="fictional-offline",
                        prompt_sha256="c" * 64,
                        payload=pointer,
                        payload_sha256=payload_sha256(pointer),
                        created_by="fictional-test",
                        created_at=datetime.now(UTC),
                    )
                )
            async with sessions() as session:
                shown = await latest_review(session, envelope)
            assert shown is not None and shown["brain4"]["version"] == brain4.VERSION

            # A revoked permission is refused before any provider call.
            async with sessions() as session, session.begin():
                await session.execute(
                    update(ConversationPermission)
                    .where(ConversationPermission.id == report_fixture.prepared.state.permission_id)
                    .values(revoked_at=datetime.now(UTC))
                )
            refused = await brain4_shadow.read_one(sessions, report, call_provider=provider)
            assert refused["skipped"] == "permission_inactive" and len(bodies) == 1

            async with sessions() as session, session.begin():
                await erase_pointer_reviews_for_recording(
                    session, report["recording_id"], datetime.now(UTC)
                )
            async with sessions() as session:
                rows = (
                    await session.scalars(
                        select(ConversationBrain4Review).where(
                            ConversationBrain4Review.recording_id == report["recording_id"]
                        )
                    )
                ).all()
                assert await brain4_shadow.latest(session, envelope) is None
            assert rows and all(row.payload is None and row.erased_at for row in rows)
            texts = [str(segment.get("text")) for segment in segments if segment.get("text")]
            kept = json.dumps([[row.reason_code, row.model_id, row.state] for row in rows])
            assert not any(text in kept for text in texts)
        finally:
            await engine.dispose()

    run(exercise())


def test_an_unreadable_answer_is_a_failed_attempt_not_a_read(
    postgres_harness: Any, report_fixture: ReportFixture
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            report = await _report(sessions, report_fixture)

            def provider(body: dict[str, Any]) -> dict[str, Any]:
                text = json.dumps({"call_type": "cold", "dimensions": []})
                return {
                    "candidates": [{"content": {"parts": [{"text": text}]}}],
                    "usageMetadata": {"promptTokenCount": 9_000, "candidatesTokenCount": 40},
                }

            for _ in range(brain4_shadow.MAX_ATTEMPTS):
                line = await brain4_shadow.read_one(sessions, report, call_provider=provider)
                assert line["outcome"] == "parse_failed:brain4_dimensions_incomplete"
            async with sessions() as session:
                pending = await session.run_sync(
                    lambda sync: brain4_shadow.recent_reports(
                        sync.connection(), datetime.now(UTC), 10
                    )
                )
            # Two attempts per report, then it is left alone.
            assert report["draft_id"] not in {item["draft_id"] for item in pending}
        finally:
            await engine.dispose()

    run(exercise())
