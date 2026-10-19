"""Review 2.0 on PostgreSQL: gold reviewers judge call objects, answers supersede,
repeats are idempotent, revoked reviewers stop, and call erasure empties answers.

Disposable loopback PostgreSQL, fictional rows only; a local fake model, no network.
"""

from __future__ import annotations

import asyncio
import importlib.util
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Engine, inspect, select, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ac_platform.call_data.models import CallObject
from ac_platform.conversation_intelligence.application import (
    ConversationDenied,
    ConversationError,
)
from ac_platform.conversation_intelligence.gold_review_models import GoldReviewer
from ac_platform.conversation_intelligence.review_models import ReviewVerdict
from ac_platform.conversation_intelligence.review_verdicts import (
    ReviewVerdicts,
    erase_review_verdicts_for_recording,
    value_digest,
)
from ac_platform.db.models import model_metadata
from tests.database.conversation_harness import conversation_harness
from tests.database.test_call_data_postgresql import ROOT, FakeModel, _call, _process

TABLES = {"review_pipelines", "review_verdicts"}


@pytest.fixture
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def _with_service(engine_url: Any, operations: UUID, work: Any) -> Any:
    async def go() -> Any:
        engine = create_async_engine(engine_url)
        try:
            async with AsyncSession(engine) as database, database.begin():
                return await work(ReviewVerdicts(database, operations))
        finally:
            await engine.dispose()

    return asyncio.run(go())


def _seeded_call(postgres_harness: Engine) -> dict[str, Any]:
    seeded = _call(postgres_harness)
    assert _process(postgres_harness, seeded, FakeModel())["outcome"] == "succeeded"
    with postgres_harness.connect() as connection:
        objects = connection.execute(
            select(CallObject.id, CallObject.type_key, CallObject.value, CallObject.display)
            .where(CallObject.recording_id == seeded["recording_id"])
            .order_by(CallObject.created_at, CallObject.id)
        ).all()
    target = next(row for row in objects if row.type_key != "conversation.segment")
    seeded["target"] = target
    return seeded


def _designate(postgres_harness: Engine, person_id: UUID, *, revoked: bool = False) -> None:
    now = datetime.now(UTC)
    with postgres_harness.begin() as connection:
        found = connection.scalar(
            select(GoldReviewer.person_id).where(GoldReviewer.person_id == person_id)
        )
        if found is None:
            connection.execute(
                GoldReviewer.__table__.insert().values(
                    person_id=person_id, designated_by=person_id, created_at=now
                )
            )
        connection.execute(
            update(GoldReviewer)
            .where(GoldReviewer.person_id == person_id)
            .values(revoked_at=now if revoked else None)
        )


def _save(seeded: dict[str, Any], **overrides: Any) -> Any:
    owner = seeded["owner"]
    values: dict[str, Any] = {
        "pipeline_key": "analysis-sales",
        "target_kind": "object",
        "target_ref": str(seeded["target"].id),
        "question_key": "correct",
        "answer": {"value": "wrong"},
        "request_key": uuid4().hex,
    }
    values.update(overrides)

    async def work(service: ReviewVerdicts) -> Any:
        return await service.save(owner.actor, seeded["recording_id"], **values)

    return work


def test_reviewers_judge_objects_answers_supersede_and_repeats_are_idempotent(
    postgres_harness: Engine,
) -> None:
    seeded = _seeded_call(postgres_harness)
    owner, url = seeded["owner"], postgres_harness.url

    # Not a gold reviewer: refused before anything is read or written.
    with pytest.raises(ConversationDenied):
        _with_service(url, owner.tenant_id, _save(seeded))

    _designate(postgres_harness, owner.person_id)
    first = _with_service(url, owner.tenant_id, _save(seeded, request_key="r-1"))
    target = seeded["target"]
    assert first["answer"] == {"value": "wrong"}
    assert first["ai_sha256"] == value_digest(target.type_key, target.value)
    assert first["pipeline"] == {"key": "analysis-sales", "version": 1}

    # The same request again returns the same answer and writes nothing new.
    again = _with_service(url, owner.tenant_id, _save(seeded, request_key="r-1"))
    assert again["id"] == first["id"]

    fix = _with_service(
        url,
        owner.tenant_id,
        _save(seeded, question_key="fix", answer={"text": "The buyer is Ira, not Amit."}),
    )
    changed = _with_service(url, owner.tenant_id, _save(seeded, answer={"value": "correct"}))
    assert changed["supersedes_id"] == first["id"]

    async def read(service: ReviewVerdicts) -> Any:
        return await service.call(owner.actor, seeded["recording_id"])

    current = _with_service(url, owner.tenant_id, read)
    answers = {item["question"]: item["answer"] for item in current["verdicts"]}
    assert answers == {"correct": {"value": "correct"}, "fix": {"text": fix["answer"]["text"]}}
    assert all(item["mine"] for item in current["verdicts"])
    assert [item["key"] for item in current["pipelines"]] == ["analysis-sales"]
    with postgres_harness.connect() as connection:
        assert connection.scalar(
            select(ReviewVerdict.id).where(ReviewVerdict.id == UUID(first["id"]))
        )  # the old answer stays, superseded


def test_answers_are_checked_and_revoked_reviewers_stop(postgres_harness: Engine) -> None:
    seeded = _seeded_call(postgres_harness)
    owner, url = seeded["owner"], postgres_harness.url
    _designate(postgres_harness, owner.person_id)
    for overrides in (
        {"answer": {"value": "maybe"}},  # not an option
        {"question_key": "fix", "answer": {"text": "  "}},  # empty correction
        {"question_key": "nonsense"},
        {"target_kind": "segment"},  # not judged in this pipeline yet
        {"target_kind": "voice"},  # not judged in this pipeline
        {"target_ref": "not-a-uuid"},
    ):
        with pytest.raises(ConversationError):
            _with_service(url, owner.tenant_id, _save(seeded, **overrides))
    _designate(postgres_harness, owner.person_id, revoked=True)
    with pytest.raises(ConversationDenied):
        _with_service(url, owner.tenant_id, _save(seeded))


def test_call_erasure_empties_every_answer(postgres_harness: Engine) -> None:
    seeded = _seeded_call(postgres_harness)
    owner, url = seeded["owner"], postgres_harness.url
    _designate(postgres_harness, owner.person_id)
    _with_service(url, owner.tenant_id, _save(seeded))
    _with_service(url, owner.tenant_id, _save(seeded, answer={"value": "correct"}))

    async def erase(service: ReviewVerdicts) -> int:
        return await erase_review_verdicts_for_recording(
            service.database, seeded["recording_id"], datetime.now(UTC)
        )

    assert _with_service(url, owner.tenant_id, erase) == 2
    with postgres_harness.connect() as connection:
        rows = connection.execute(
            select(ReviewVerdict.answer, ReviewVerdict.erased_at).where(
                ReviewVerdict.recording_id == seeded["recording_id"]
            )
        ).all()
    assert len(rows) == 2 and all(answer is None and at is not None for answer, at in rows)


def migration() -> Any:
    path = ROOT / "db/migrations/versions/20261019_0101_review_verdicts.py"
    spec = importlib.util.spec_from_file_location("review_verdicts_migration_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_is_additive_and_passes_the_schema_gate_rules() -> None:
    from scripts.ci.migration_schema_gate import check_operations
    from scripts.ops.migration_safety import classify_source

    module = migration()
    assert (module.revision, module.down_revision) == ("20261019_0101", "20261019_0100")
    path = Path(module.__file__)
    item = classify_source(path.read_text(), str(path))
    check_operations([item], set())
    assert item.verdict == "additive"


def test_empty_migration_downgrades_reupgrades_and_matches_the_models(
    postgres_harness: Engine,
) -> None:
    module = migration()
    with postgres_harness.begin() as connection:
        assert set(inspect(connection).get_table_names()) >= TABLES
        context = MigrationContext.configure(connection, opts={"target_metadata": model_metadata()})
        with Operations.context(context):
            module.downgrade()
            assert not TABLES & set(inspect(connection).get_table_names())
            module.upgrade()
        assert compare_metadata(MigrationContext.configure(connection), model_metadata()) == []
