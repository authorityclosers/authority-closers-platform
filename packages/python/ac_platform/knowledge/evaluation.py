"""Pure fixture evaluation helpers for the lexical retrieval gold set."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from ac_platform.knowledge.contracts import (
    KnowledgeRetrievalError,
    RetrievalResult,
)


@dataclass(frozen=True, slots=True)
class GoldCase:
    """An anonymized retrieval case with expected provenance and negatives."""

    case_id: str
    tenant_key: str
    purpose: str
    question: str
    expected: str
    relevant: tuple[tuple[str, str], ...]
    forbidden_source_ids: frozenset[str]
    acl_subject_ids: tuple[str, ...]
    poisoned_document: bool


@dataclass(frozen=True, slots=True)
class GoldEvaluation:
    """Deterministic, non-authoritative retrieval evaluation metrics."""

    answerable_cases: int
    abstention_cases: int
    recall_at_k: float
    abstention_accuracy: float
    leakage_count: int


@dataclass(frozen=True, slots=True)
class GoldPrediction:
    """One structured retrieval prediction and its evaluated query context.

    ``RetrievalResult`` carries the complete returned provenance.  The query
    context is optional for callers that already bind cases externally, but
    when supplied it is checked against the fixture so tenant/purpose/ACL
    regressions cannot be hidden behind a source/locator-only tuple.
    """

    result: RetrievalResult
    tenant_key: str
    purpose: str
    acl_subject_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.result, RetrievalResult):
            raise KnowledgeRetrievalError("gold prediction result must be a RetrievalResult")
        object.__setattr__(
            self,
            "tenant_key",
            _bounded_fixture_text(self.tenant_key, "prediction tenant_key", 128),
        )
        object.__setattr__(
            self,
            "purpose",
            _bounded_fixture_text(self.purpose, "prediction purpose", 64),
        )
        if (
            isinstance(self.acl_subject_ids, str | bytes | bytearray)
            or not isinstance(self.acl_subject_ids, Sequence)
        ):
            raise KnowledgeRetrievalError("gold prediction ACL subject IDs must be a sequence")
        subjects = tuple(
            _bounded_fixture_text(subject, "prediction ACL subject_id", 256)
            for subject in self.acl_subject_ids
        )
        if len(set(subjects)) != len(subjects):
            raise KnowledgeRetrievalError("gold prediction ACL subject IDs must be unique")
        object.__setattr__(self, "acl_subject_ids", subjects)


type StructuredPrediction = RetrievalResult | GoldPrediction


def _bounded_fixture_text(value: object, field_name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise KnowledgeRetrievalError(f"gold-set {field_name} is invalid")
    return value.strip()


def load_gold_set(path: Path) -> tuple[GoldCase, ...]:
    """Load and validate bounded JSONL fixture cases without logging content."""

    cases: list[GoldCase] = []
    required_fields = {
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
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            if not isinstance(payload, dict) or set(payload) != required_fields:
                raise TypeError("gold-set fields do not match the contract")
            case_id = _bounded_fixture_text(payload["case_id"], "case_id", 128)
            tenant_key = _bounded_fixture_text(payload["tenant_key"], "tenant_key", 128)
            purpose = _bounded_fixture_text(payload["purpose"], "purpose", 64)
            question = _bounded_fixture_text(payload["question"], "question", 4_000)
            expected = _bounded_fixture_text(payload["expected"], "expected", 16)
            relevant_values = payload["relevant"]
            forbidden_values = payload["forbidden_source_ids"]
            acl_values = payload["acl_subject_ids"]
            poisoned_document = payload["poisoned_document"]
            if not isinstance(relevant_values, list):
                raise TypeError("relevant must be a list")
            if not isinstance(forbidden_values, list) or not isinstance(acl_values, list):
                raise TypeError("source and ACL negatives must be lists")
            relevant = tuple(
                (
                    _bounded_fixture_text(item["source_id"], "relevant source_id", 256),
                    _bounded_fixture_text(item["locator"], "relevant locator", 512),
                )
                for item in relevant_values
            )
            forbidden = frozenset(
                _bounded_fixture_text(value, "forbidden source_id", 256)
                for value in forbidden_values
            )
            acl_subject_ids = tuple(
                _bounded_fixture_text(value, "ACL subject_id", 256) for value in acl_values
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise KnowledgeRetrievalError(f"invalid gold-set case at line {line_number}") from exc
        if purpose != "support_assistance":
            raise KnowledgeRetrievalError("gold-set purpose must be support_assistance")
        if expected not in {"answerable", "abstain"}:
            raise KnowledgeRetrievalError("gold-set expected must be answerable or abstain")
        if not isinstance(poisoned_document, bool):
            raise KnowledgeRetrievalError("gold-set poisoned_document must be boolean")
        if len(set(acl_subject_ids)) != len(acl_subject_ids):
            raise KnowledgeRetrievalError("gold-set ACL subject IDs must be unique")
        cases.append(
            GoldCase(
                case_id=case_id,
                tenant_key=tenant_key,
                purpose=purpose,
                question=question,
                expected=expected,
                relevant=relevant,
                forbidden_source_ids=forbidden,
                acl_subject_ids=acl_subject_ids,
                poisoned_document=poisoned_document,
            )
        )
    if not cases:
        raise KnowledgeRetrievalError("gold-set must contain at least one case")
    if len({case.case_id for case in cases}) != len(cases):
        raise KnowledgeRetrievalError("gold-set case IDs must be unique")
    return tuple(cases)


def evaluate_gold_set(
    cases: Iterable[GoldCase],
    predictions: Mapping[str, StructuredPrediction],
) -> GoldEvaluation:
    """Evaluate structured retrieval results without accepting partial output."""

    normalized_cases = tuple(cases)
    if not normalized_cases:
        raise KnowledgeRetrievalError("evaluation requires at least one case")
    if any(case.expected not in {"answerable", "abstain"} for case in normalized_cases):
        raise KnowledgeRetrievalError("gold-set expected must be answerable or abstain")
    case_ids = {case.case_id for case in normalized_cases}
    if any(not isinstance(case_id, str) for case_id in predictions):
        raise KnowledgeRetrievalError("prediction case IDs must be text")
    prediction_ids = set(predictions)
    if prediction_ids != case_ids:
        missing = case_ids - prediction_ids
        unknown = prediction_ids - case_ids
        details = []
        if missing:
            details.append("missing " + ", ".join(sorted(missing)))
        if unknown:
            details.append("unknown " + ", ".join(sorted(unknown)))
        raise KnowledgeRetrievalError(
            "predictions must contain exactly one structured result per gold-set case ("
            + "; ".join(details)
            + ")"
        )
    answerable = [case for case in normalized_cases if case.expected == "answerable"]
    abstentions = [case for case in normalized_cases if case.expected == "abstain"]
    hits = 0
    abstention_hits = 0
    leakage = 0
    for case in normalized_cases:
        prediction = predictions[case.case_id]
        if isinstance(prediction, GoldPrediction):
            if prediction.tenant_key != case.tenant_key:
                raise KnowledgeRetrievalError(
                    f"prediction tenant does not match case {case.case_id}"
                )
            if prediction.purpose != case.purpose:
                raise KnowledgeRetrievalError(
                    f"prediction purpose does not match case {case.case_id}"
                )
            if prediction.acl_subject_ids != case.acl_subject_ids:
                raise KnowledgeRetrievalError(
                    f"prediction ACL context does not match case {case.case_id}"
                )
            result = prediction.result
        elif isinstance(prediction, RetrievalResult):
            result = prediction
        else:
            raise KnowledgeRetrievalError(
                "predictions must contain structured RetrievalResult values"
            )

        returned_chunks = tuple(result.chunks)
        if len({chunk.snapshot_id for chunk in returned_chunks}) > 1:
            raise KnowledgeRetrievalError("predictions contain mixed chunk snapshot IDs")
        if any(chunk.snapshot_id != result.snapshot_id for chunk in returned_chunks):
            raise KnowledgeRetrievalError("prediction chunk provenance does not match its snapshot")
        if len({chunk.tenant_id for chunk in returned_chunks}) > 1:
            raise KnowledgeRetrievalError("predictions contain cross-tenant provenance")
        for chunk in returned_chunks:
            expected_digest = hashlib.sha256(chunk.passage.encode("utf-8")).hexdigest()
            if chunk.content_sha256 != expected_digest:
                raise KnowledgeRetrievalError(
                    "prediction passage digest does not match its UTF-8 provenance"
                )
        returned = tuple((chunk.source_id, chunk.locator) for chunk in returned_chunks)
        if len(set(returned)) != len(returned):
            raise KnowledgeRetrievalError("predictions contain duplicate provenance tuples")
        returned_sources = {source_id for source_id, _locator in returned}
        if returned_sources & case.forbidden_source_ids:
            leakage += 1
        if case.expected == "answerable":
            if set(returned) & set(case.relevant):
                hits += 1
        elif not returned:
            abstention_hits += 1
    return GoldEvaluation(
        answerable_cases=len(answerable),
        abstention_cases=len(abstentions),
        recall_at_k=hits / len(answerable) if answerable else 1.0,
        abstention_accuracy=abstention_hits / len(abstentions) if abstentions else 1.0,
        leakage_count=leakage,
    )


__all__ = [
    "GoldCase",
    "GoldEvaluation",
    "GoldPrediction",
    "StructuredPrediction",
    "evaluate_gold_set",
    "load_gold_set",
]
