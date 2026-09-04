"""Contract and fixture-evaluation tests for inert knowledge retrieval."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from ac_platform.intelligence import IntelligencePurpose
from ac_platform.knowledge import (
    KNOWLEDGE_RETRIEVAL_ENABLED,
    PINNED_MIN_RANK_SCORE,
    KnowledgeAccessContext,
    KnowledgeQuery,
    KnowledgeRetrievalError,
    KnowledgeRetrievalTimeoutError,
    RetrievalOutcome,
    RetrievalResult,
    RetrievedChunk,
    evaluate_gold_set,
    load_gold_set,
)
from ac_platform.knowledge.contracts import snapshot_fingerprint


def _access(*, tenant_id=None, subjects=()):
    return KnowledgeAccessContext(
        tenant_id=tenant_id or uuid4(),
        purpose=IntelligencePurpose.SUPPORT_ASSISTANCE,
        acl_subject_ids=subjects,
    )


def _chunk(*, source_id="support-policy", ordinal=1, score="1.0"):
    del ordinal
    return RetrievedChunk(
        chunk_id=uuid4(),
        source_id=source_id,
        source_version_id=uuid4(),
        tenant_id=uuid4(),
        locator="recovery.md#email",
        passage="Contact support to verify account recovery.",
        content_sha256="a" * 64,
        rank_score=Decimal(score),
        snapshot_id="snapshot",
    )


def test_access_context_rejects_duplicate_or_oversized_acl_subjects() -> None:
    subject = uuid4()
    with pytest.raises(KnowledgeRetrievalError, match="duplicates"):
        _access(subjects=(subject, subject))
    with pytest.raises(KnowledgeRetrievalError, match="too many"):
        _access(subjects=tuple(uuid4() for _ in range(65)))


def test_query_is_bounded_and_requires_admitted_purpose() -> None:
    with pytest.raises(KnowledgeRetrievalError, match="top_k"):
        KnowledgeQuery(
            access=_access(),
            question="recovery",
            min_rank_score=PINNED_MIN_RANK_SCORE,
            top_k=13,
        )
    with pytest.raises(KnowledgeRetrievalError, match="question"):
        KnowledgeQuery(access=_access(), question=" ", min_rank_score=PINNED_MIN_RANK_SCORE)
    with pytest.raises(KnowledgeRetrievalError, match="pinned"):
        KnowledgeQuery(access=_access(), question="recovery", min_rank_score=Decimal("0"))
    with pytest.raises(KnowledgeRetrievalError, match="purpose"):
        KnowledgeAccessContext(tenant_id=uuid4(), purpose="sales_simulation")  # type: ignore[arg-type]


def test_retrieval_is_inert_by_default() -> None:
    assert KNOWLEDGE_RETRIEVAL_ENABLED is False


async def test_repository_normalizes_timeout_at_nested_transaction_boundary() -> None:
    from sqlalchemy.exc import DBAPIError

    class Dialect:
        name = "postgresql"

    class Bind:
        dialect = Dialect()

    class Session:
        def __init__(self) -> None:
            self.exited = False

        def get_bind(self):
            return Bind()

        @asynccontextmanager
        async def begin_nested(self):
            try:
                yield
            finally:
                self.exited = True

        async def execute(self, statement, params=None):
            if "SET LOCAL" in str(statement):
                return None
            raise DBAPIError("knowledge", params or {}, RuntimeError("statement timeout"), False)

    from ac_platform.knowledge import PostgresKnowledgeRepository

    session = Session()
    with pytest.raises(KnowledgeRetrievalTimeoutError):
        await PostgresKnowledgeRepository(session).search(
            KnowledgeQuery(
                access=_access(),
                question="recovery",
                min_rank_score=PINNED_MIN_RANK_SCORE,
            )
        )
    assert session.exited is True


def test_retrieved_chunk_requires_provenance_and_lowercase_sha256() -> None:
    with pytest.raises(KnowledgeRetrievalError, match="content_sha256"):
        RetrievedChunk(
            chunk_id=uuid4(),
            source_id="source",
            source_version_id=uuid4(),
            tenant_id=uuid4(),
            locator="policy#1",
            passage="Evidence",
            content_sha256="A" * 64,
            rank_score=Decimal("1"),
            snapshot_id="snapshot",
        )
    with pytest.raises(KnowledgeRetrievalError, match="locator"):
        RetrievedChunk(
            chunk_id=uuid4(),
            source_id="source",
            source_version_id=uuid4(),
            tenant_id=uuid4(),
            locator=" ",
            passage="Evidence",
            content_sha256="a" * 64,
            rank_score=Decimal("1"),
            snapshot_id="snapshot",
        )


def test_outcome_shape_is_fail_closed() -> None:
    chunk = _chunk()
    result = RetrievalResult(RetrievalOutcome.FOUND, "snapshot", (chunk,))
    assert result.chunks == (chunk,)
    with pytest.raises(KnowledgeRetrievalError, match="FOUND"):
        RetrievalResult(RetrievalOutcome.FOUND, "snapshot")
    with pytest.raises(KnowledgeRetrievalError, match="non-FOUND"):
        RetrievalResult(RetrievalOutcome.BELOW_THRESHOLD, "snapshot", (chunk,))


def test_snapshot_fingerprint_is_deterministic_and_non_authoritative() -> None:
    first = _chunk(source_id="one")
    second = _chunk(source_id="two")
    assert snapshot_fingerprint((first, second)) == snapshot_fingerprint((first, second))
    assert snapshot_fingerprint((first, second)) != snapshot_fingerprint((second, first))


def test_gold_set_fixture_has_bounded_schema_and_expected_classes() -> None:
    fixture = Path(__file__).parents[2] / "fixtures" / "knowledge_gold_set.jsonl"
    cases = [json.loads(line) for line in fixture.read_text(encoding="utf-8").splitlines() if line]
    assert cases
    assert {case["expected"] for case in cases} == {"answerable", "abstain"}
    for case in cases:
        assert set(case) == {
            "case_id",
            "tenant_key",
            "purpose",
            "question",
            "expected",
            "relevant",
            "forbidden_source_ids",
            "acl_subject_ids",
            "poisoned_document",
        }
        assert case["purpose"] == "support_assistance"
        assert 1 <= len(case["question"]) <= 4000
        assert isinstance(case["relevant"], list)
        assert isinstance(case["forbidden_source_ids"], list)
        assert isinstance(case["acl_subject_ids"], list)
        assert isinstance(case["poisoned_document"], bool)


def test_gold_set_recall_and_isolation_metric_helpers() -> None:
    fixture = Path(__file__).parents[2] / "fixtures" / "knowledge_gold_set.jsonl"
    cases = load_gold_set(fixture)
    predictions = {case.case_id: case.relevant for case in cases if case.expected == "answerable"}
    evaluation = evaluate_gold_set(cases, predictions)
    assert evaluation.answerable_cases == 5
    assert evaluation.abstention_cases == 3
    assert evaluation.recall_at_k == 1.0
    assert evaluation.abstention_accuracy == 1.0
    assert evaluation.leakage_count == 0


def test_gold_set_evaluation_counts_forbidden_source_leakage() -> None:
    fixture = Path(__file__).parents[2] / "fixtures" / "knowledge_gold_set.jsonl"
    cases = load_gold_set(fixture)
    predictions = {case.case_id: case.relevant for case in cases if case.expected == "answerable"}
    predictions["ks-0005"] = (("payment-secret", "card"),)
    evaluation = evaluate_gold_set(cases, predictions)
    assert evaluation.leakage_count == 1


def test_gold_set_evaluation_rejects_unknown_or_malformed_predictions() -> None:
    fixture = Path(__file__).parents[2] / "fixtures" / "knowledge_gold_set.jsonl"
    cases = load_gold_set(fixture)
    with pytest.raises(KnowledgeRetrievalError, match="unknown"):
        evaluate_gold_set(cases, {"unknown": ()})
    with pytest.raises(KnowledgeRetrievalError, match="invalid provenance"):
        evaluate_gold_set(cases, {"ks-0001": (("source", ""),)})
