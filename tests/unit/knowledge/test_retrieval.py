"""Contract and fixture-evaluation tests for inert knowledge retrieval."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from ac_platform.intelligence import IntelligencePurpose
from ac_platform.knowledge import (
    KNOWLEDGE_RETRIEVAL_ENABLED,
    PINNED_MIN_RANK_SCORE,
    GoldPrediction,
    KnowledgeAccessContext,
    KnowledgeQuery,
    KnowledgeRetrievalError,
    KnowledgeRetrievalTimeoutError,
    KnowledgeRetrievalUnavailableError,
    PostgresKnowledgeRepository,
    RetrievalOutcome,
    RetrievalResult,
    RetrievedChunk,
    canonical_knowledge_version_digest,
    canonical_knowledge_version_digest_material,
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
    passage = "Contact support to verify account recovery."
    return RetrievedChunk(
        chunk_id=uuid4(),
        source_id=source_id,
        source_version_id=uuid4(),
        tenant_id=uuid4(),
        locator="recovery.md#email",
        passage=passage,
        content_sha256=hashlib.sha256(passage.encode("utf-8")).hexdigest(),
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

    class Transaction:
        def __init__(self, connection) -> None:
            self.connection = connection
            self.rolled_back = False

        async def rollback(self):
            self.rolled_back = True
            self.connection.statement_timeout = self.connection.default_statement_timeout
            self.connection.transaction_read_only = False

    class Connection:
        def __init__(self) -> None:
            self.default_statement_timeout = "0"
            self.statement_timeout = self.default_statement_timeout
            self.transaction_read_only = False
            self.transaction = Transaction(self)
            self.statements = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def begin(self):
            return self.transaction

        async def execute(self, statement, params=None):
            statement_text = str(statement)
            self.statements.append(statement_text)
            if "SET TRANSACTION READ ONLY" in statement_text:
                self.transaction_read_only = True
            if "SET LOCAL" in statement_text:
                self.statement_timeout = "300ms"
                raise DBAPIError(
                    "knowledge",
                    params or {},
                    type("Timeout", (), {"sqlstate": "57014"})(),
                    False,
                )
            return None

    class Engine:
        def __init__(self) -> None:
            self.connection = Connection()

        def connect(self):
            return self.connection

    class Session:
        def __init__(self) -> None:
            self.executed = False

        def get_bind(self):
            return Bind()

        async def execute(self, *_args, **_kwargs):
            self.executed = True

    session = Session()
    engine = Engine()
    with pytest.raises(KnowledgeRetrievalTimeoutError):
        await PostgresKnowledgeRepository(session, engine=engine).search(
            KnowledgeQuery(
                access=_access(),
                question="recovery",
                min_rank_score=PINNED_MIN_RANK_SCORE,
            )
        )
    assert session.executed is False
    assert engine.connection.transaction.rolled_back is True
    assert engine.connection.statement_timeout == engine.connection.default_statement_timeout
    assert engine.connection.transaction_read_only is False
    assert "SET TRANSACTION READ ONLY" in engine.connection.statements[0]


async def test_repository_success_uses_dedicated_rolled_back_connection() -> None:
    class Dialect:
        name = "postgresql"

    class Bind:
        dialect = Dialect()

    class Transaction:
        def __init__(self, connection) -> None:
            self.connection = connection
            self.rolled_back = False

        async def rollback(self):
            self.rolled_back = True
            self.connection.statement_timeout = self.connection.default_statement_timeout
            self.connection.transaction_read_only = False

    class Result:
        def mappings(self):
            return [
                {
                    "authorized_exists": True,
                    "chunk_id": uuid4(),
                    "source_id": "support-policy",
                    "source_version_id": uuid4(),
                    "tenant_id": tenant_id,
                    "ordinal": 0,
                    "locator": "recovery.md#email",
                    "passage": "Contact support to verify account recovery.",
                    "content_sha256": hashlib.sha256(
                        b"Contact support to verify account recovery."
                    ).hexdigest(),
                    "rank_score": Decimal("1.0"),
                }
            ]

    class Connection:
        def __init__(self) -> None:
            self.default_statement_timeout = "0"
            self.statement_timeout = self.default_statement_timeout
            self.transaction_read_only = False
            self.transaction = Transaction(self)
            self.statements = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def begin(self):
            return self.transaction

        async def execute(self, statement, _params=None):
            statement_text = str(statement)
            self.statements.append(statement_text)
            if "SET TRANSACTION READ ONLY" in statement_text:
                self.transaction_read_only = True
            if "SET LOCAL" in statement_text:
                self.statement_timeout = "300ms"
            if "WITH authorized" in statement_text:
                return Result()
            return None

    class Engine:
        def __init__(self) -> None:
            self.connection = Connection()

        def connect(self):
            return self.connection

    class Session:
        def get_bind(self):
            return Bind()

        async def execute(self, *_args, **_kwargs):
            raise AssertionError("the caller session must never execute retrieval SQL")

    tenant_id = uuid4()
    engine = Engine()
    result = await PostgresKnowledgeRepository(Session(), engine=engine).search(
        KnowledgeQuery(
            access=_access(tenant_id=tenant_id),
            question="recovery",
            min_rank_score=PINNED_MIN_RANK_SCORE,
        )
    )
    assert result.outcome is RetrievalOutcome.FOUND
    assert engine.connection.transaction.rolled_back is True
    assert engine.connection.statement_timeout == engine.connection.default_statement_timeout
    assert engine.connection.transaction_read_only is False


async def test_repository_unavailable_error_rolls_back_dedicated_transaction() -> None:
    from sqlalchemy.exc import SQLAlchemyError

    class Dialect:
        name = "postgresql"

    class Bind:
        dialect = Dialect()

    class Transaction:
        def __init__(self, connection) -> None:
            self.connection = connection
            self.rolled_back = False

        async def rollback(self):
            self.rolled_back = True
            self.connection.statement_timeout = self.connection.default_statement_timeout
            self.connection.transaction_read_only = False

    class Connection:
        def __init__(self) -> None:
            self.default_statement_timeout = "0"
            self.statement_timeout = self.default_statement_timeout
            self.transaction_read_only = False
            self.transaction = Transaction(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def begin(self):
            return self.transaction

        async def execute(self, statement, _params=None):
            statement_text = str(statement)
            if "SET TRANSACTION READ ONLY" in statement_text:
                self.transaction_read_only = True
            if "SET LOCAL" in statement_text:
                self.statement_timeout = "300ms"
            if "WITH authorized" in statement_text:
                raise SQLAlchemyError("database connection failed")
            return None

    class Engine:
        def __init__(self) -> None:
            self.connection = Connection()

        def connect(self):
            return self.connection

    class Session:
        def get_bind(self):
            return Bind()

    engine = Engine()
    with pytest.raises(KnowledgeRetrievalUnavailableError):
        await PostgresKnowledgeRepository(Session(), engine=engine).search(
            KnowledgeQuery(
                access=_access(),
                question="recovery",
                min_rank_score=PINNED_MIN_RANK_SCORE,
            )
        )
    assert engine.connection.transaction.rolled_back is True
    assert engine.connection.statement_timeout == engine.connection.default_statement_timeout
    assert engine.connection.transaction_read_only is False


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


def test_canonical_version_digest_is_utf8_exact_and_ordered() -> None:
    chunks = ((1, "guide#✓", "Résumé ✓"), (0, "intro", "Start"))
    material = canonical_knowledge_version_digest_material(chunks)
    assert b"ac-knowledge-version-v1\nC|0|5:intro|5:Start\n" in material
    assert b"C|1|9:guide#\xe2\x9c\x93|12:R\xc3\xa9sum\xc3\xa9 \xe2\x9c\x93\n" in material
    assert canonical_knowledge_version_digest(chunks) == hashlib.sha256(material).hexdigest()
    with pytest.raises(KnowledgeRetrievalError, match="ordinals"):
        canonical_knowledge_version_digest(((0, "a", "one"), (0, "b", "two")))


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


def _gold_predictions(cases, *, leaked_case_id=None):
    predictions = {}
    for case in cases:
        snapshot_id = f"snapshot-{case.case_id}"
        if case.expected == "answerable":
            chunks = tuple(
                RetrievedChunk(
                    chunk_id=uuid4(),
                    source_id=source_id,
                    source_version_id=uuid4(),
                    tenant_id=uuid4(),
                    locator=locator,
                    passage=f"Evidence for {source_id} at {locator}.",
                    content_sha256=hashlib.sha256(
                        f"Evidence for {source_id} at {locator}.".encode()
                    ).hexdigest(),
                    rank_score=Decimal("1"),
                    snapshot_id=snapshot_id,
                )
                for source_id, locator in case.relevant
            )
            result = RetrievalResult(RetrievalOutcome.FOUND, snapshot_id, chunks)
        else:
            result = RetrievalResult(RetrievalOutcome.NO_AUTHORIZED_EVIDENCE, snapshot_id)
        predictions[case.case_id] = GoldPrediction(
            result=result,
            tenant_key=case.tenant_key,
            purpose=case.purpose,
            acl_subject_ids=case.acl_subject_ids,
        )
    if leaked_case_id is not None:
        case = next(case for case in cases if case.case_id == leaked_case_id)
        chunk = RetrievedChunk(
            chunk_id=uuid4(),
            source_id=next(iter(case.forbidden_source_ids)),
            source_version_id=uuid4(),
            tenant_id=uuid4(),
            locator="forbidden#1",
            passage="Forbidden evidence.",
            content_sha256=hashlib.sha256(b"Forbidden evidence.").hexdigest(),
            rank_score=Decimal("1"),
            snapshot_id=f"snapshot-{case.case_id}",
        )
        predictions[case.case_id] = GoldPrediction(
            result=RetrievalResult(
                RetrievalOutcome.FOUND,
                f"snapshot-{case.case_id}",
                (chunk,),
            ),
            tenant_key=case.tenant_key,
            purpose=case.purpose,
            acl_subject_ids=case.acl_subject_ids,
        )
    return predictions


def test_gold_set_recall_and_isolation_metric_helpers() -> None:
    fixture = Path(__file__).parents[2] / "fixtures" / "knowledge_gold_set.jsonl"
    cases = load_gold_set(fixture)
    predictions = _gold_predictions(cases)
    evaluation = evaluate_gold_set(cases, predictions)
    assert evaluation.answerable_cases == 5
    assert evaluation.abstention_cases == 3
    assert evaluation.recall_at_k == 1.0
    assert evaluation.abstention_accuracy == 1.0
    assert evaluation.leakage_count == 0


def test_gold_set_evaluation_counts_forbidden_source_leakage() -> None:
    fixture = Path(__file__).parents[2] / "fixtures" / "knowledge_gold_set.jsonl"
    cases = load_gold_set(fixture)
    predictions = _gold_predictions(cases, leaked_case_id="ks-0005")
    evaluation = evaluate_gold_set(cases, predictions)
    assert evaluation.leakage_count == 1


def test_gold_set_evaluation_rejects_unknown_or_malformed_predictions() -> None:
    fixture = Path(__file__).parents[2] / "fixtures" / "knowledge_gold_set.jsonl"
    cases = load_gold_set(fixture)
    with pytest.raises(KnowledgeRetrievalError, match="unknown"):
        evaluate_gold_set(cases, {"unknown": ()})
    with pytest.raises(KnowledgeRetrievalError, match="missing"):
        evaluate_gold_set(cases, _gold_predictions(cases[:-1]))
    malformed = _gold_predictions(cases)
    malformed["ks-0001"] = (("source", "locator"),)  # type: ignore[assignment]
    with pytest.raises(KnowledgeRetrievalError, match="structured RetrievalResult"):
        evaluate_gold_set(cases, malformed)


def test_gold_set_evaluation_rejects_untruthful_or_mismatched_context() -> None:
    fixture = Path(__file__).parents[2] / "fixtures" / "knowledge_gold_set.jsonl"
    cases = load_gold_set(fixture)
    predictions = _gold_predictions(cases)
    case = next(case for case in cases if case.case_id == "ks-0001")
    chunk = RetrievedChunk(
        chunk_id=uuid4(),
        source_id="support-policy",
        source_version_id=uuid4(),
        tenant_id=uuid4(),
        locator="recovery.md#email",
        passage="Evidence with a stale digest.",
        content_sha256="a" * 64,
        rank_score=Decimal("1"),
        snapshot_id="snapshot-ks-0001",
    )
    predictions[case.case_id] = RetrievalResult(
        RetrievalOutcome.FOUND,
        "snapshot-ks-0001",
        (chunk,),
    )
    with pytest.raises(KnowledgeRetrievalError, match="digest"):
        evaluate_gold_set(cases, predictions)

    predictions = _gold_predictions(cases)
    predictions[case.case_id] = GoldPrediction(
        result=predictions[case.case_id].result,  # type: ignore[union-attr]
        tenant_key="tenant-b",
        purpose=case.purpose,
        acl_subject_ids=case.acl_subject_ids,
    )
    with pytest.raises(KnowledgeRetrievalError, match="tenant"):
        evaluate_gold_set(cases, predictions)

    predictions = _gold_predictions(cases)
    predictions[case.case_id] = GoldPrediction(
        result=predictions[case.case_id].result,  # type: ignore[union-attr]
        tenant_key=case.tenant_key,
        purpose="other_purpose",
        acl_subject_ids=case.acl_subject_ids,
    )
    with pytest.raises(KnowledgeRetrievalError, match="purpose"):
        evaluate_gold_set(cases, predictions)

    predictions = _gold_predictions(cases)
    predictions[case.case_id] = GoldPrediction(
        result=predictions[case.case_id].result,  # type: ignore[union-attr]
        tenant_key=case.tenant_key,
        purpose=case.purpose,
        acl_subject_ids=("different-subject",),
    )
    with pytest.raises(KnowledgeRetrievalError, match="ACL"):
        evaluate_gold_set(cases, predictions)
