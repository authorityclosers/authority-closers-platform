"""Bounded contracts for the inert PostgreSQL knowledge retrieval slice."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from uuid import UUID

from ac_platform.intelligence.contracts import IntelligencePurpose

MAX_KNOWLEDGE_QUESTION_CHARS = 4_000
MAX_KNOWLEDGE_PASSAGE_CHARS = 8_000
MAX_KNOWLEDGE_LOCATOR_CHARS = 512
MAX_KNOWLEDGE_SOURCE_KEY_CHARS = 256
MAX_KNOWLEDGE_ACL_SUBJECTS = 64
MAX_KNOWLEDGE_TOP_K = 12
MAX_KNOWLEDGE_MIN_SCORE = Decimal("1000000")
PINNED_MIN_RANK_SCORE = Decimal("0.05")


class KnowledgeRetrievalError(ValueError):
    """Raised when a retrieval boundary value is invalid."""


class KnowledgeRetrievalTimeoutError(KnowledgeRetrievalError):
    """Raised when PostgreSQL exceeds the bounded retrieval statement timeout."""


class KnowledgeRetrievalUnavailableError(KnowledgeRetrievalError):
    """Raised when PostgreSQL cannot execute a retrieval query."""


class RetrievalOutcome(StrEnum):
    """Closed set of deterministic retrieval outcomes."""

    FOUND = "found"
    NO_AUTHORIZED_EVIDENCE = "no_authorized_evidence"
    BELOW_THRESHOLD = "below_threshold"


def _text(value: object, field_name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise KnowledgeRetrievalError(f"{field_name} must be text")
    normalized = value.strip()
    if not normalized:
        raise KnowledgeRetrievalError(f"{field_name} must not be blank")
    if "\x00" in normalized:
        raise KnowledgeRetrievalError(f"{field_name} contains a NUL byte")
    if len(normalized) > maximum:
        raise KnowledgeRetrievalError(f"{field_name} must be at most {maximum} characters")
    return normalized


def _uuid(value: object, field_name: str) -> UUID:
    if not isinstance(value, UUID):
        raise KnowledgeRetrievalError(f"{field_name} must be a UUID")
    return value


def _score(value: object) -> Decimal:
    if isinstance(value, bool):
        raise KnowledgeRetrievalError("min_rank_score must be a decimal")
    try:
        normalized = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise KnowledgeRetrievalError("min_rank_score must be a decimal") from exc
    if not normalized.is_finite() or normalized < 0 or normalized > MAX_KNOWLEDGE_MIN_SCORE:
        raise KnowledgeRetrievalError("min_rank_score is outside the permitted bound")
    return normalized


@dataclass(frozen=True, slots=True)
class KnowledgeAccessContext:
    """Authorization context created by the existing authz boundary."""

    tenant_id: UUID
    purpose: IntelligencePurpose
    acl_subject_ids: tuple[UUID, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", _uuid(self.tenant_id, "tenant_id"))
        if not isinstance(self.purpose, IntelligencePurpose):
            raise KnowledgeRetrievalError("purpose must be an admitted IntelligencePurpose")
        if isinstance(self.acl_subject_ids, str | bytes | bytearray) or not isinstance(
            self.acl_subject_ids, Sequence
        ):
            raise KnowledgeRetrievalError("acl_subject_ids must be a sequence")
        subjects = tuple(self.acl_subject_ids)
        if len(subjects) > MAX_KNOWLEDGE_ACL_SUBJECTS:
            raise KnowledgeRetrievalError("acl_subject_ids contains too many subjects")
        if any(not isinstance(subject, UUID) for subject in subjects):
            raise KnowledgeRetrievalError("acl_subject_ids contains a non-UUID subject")
        if len(set(subjects)) != len(subjects):
            raise KnowledgeRetrievalError("acl_subject_ids must not contain duplicates")
        object.__setattr__(self, "acl_subject_ids", subjects)


@dataclass(frozen=True, slots=True)
class KnowledgeQuery:
    """Bounded read-only retrieval request."""

    access: KnowledgeAccessContext
    question: str
    min_rank_score: Decimal = PINNED_MIN_RANK_SCORE
    top_k: int = MAX_KNOWLEDGE_TOP_K
    snapshot_id: UUID | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.access, KnowledgeAccessContext):
            raise KnowledgeRetrievalError("access must be a KnowledgeAccessContext")
        object.__setattr__(
            self,
            "question",
            _text(self.question, "question", MAX_KNOWLEDGE_QUESTION_CHARS),
        )
        if isinstance(self.top_k, bool) or not isinstance(self.top_k, int):
            raise KnowledgeRetrievalError("top_k must be an integer")
        if not 1 <= self.top_k <= MAX_KNOWLEDGE_TOP_K:
            raise KnowledgeRetrievalError(f"top_k must be between 1 and {MAX_KNOWLEDGE_TOP_K}")
        rank_score = _score(self.min_rank_score)
        if rank_score != PINNED_MIN_RANK_SCORE:
            raise KnowledgeRetrievalError(
                f"min_rank_score must equal the pinned threshold {PINNED_MIN_RANK_SCORE}"
            )
        object.__setattr__(self, "min_rank_score", rank_score)
        if self.snapshot_id is not None:
            object.__setattr__(self, "snapshot_id", _uuid(self.snapshot_id, "snapshot_id"))


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """One authorized passage with mandatory citation provenance."""

    chunk_id: UUID
    source_id: str
    source_version_id: UUID
    tenant_id: UUID
    locator: str
    passage: str
    content_sha256: str
    rank_score: Decimal
    snapshot_id: str

    def __post_init__(self) -> None:
        for field_name in ("chunk_id", "source_version_id", "tenant_id"):
            object.__setattr__(self, field_name, _uuid(getattr(self, field_name), field_name))
        for field_name, maximum in (
            ("source_id", MAX_KNOWLEDGE_SOURCE_KEY_CHARS),
            ("locator", MAX_KNOWLEDGE_LOCATOR_CHARS),
            ("passage", MAX_KNOWLEDGE_PASSAGE_CHARS),
            ("snapshot_id", 128),
        ):
            object.__setattr__(
                self, field_name, _text(getattr(self, field_name), field_name, maximum)
            )
        digest = _text(self.content_sha256, "content_sha256", 64)
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise KnowledgeRetrievalError("content_sha256 must be a lowercase SHA-256 digest")
        object.__setattr__(self, "content_sha256", digest)
        object.__setattr__(self, "rank_score", _score(self.rank_score))


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """Deterministic retrieval output; it has no write or policy authority."""

    outcome: RetrievalOutcome
    snapshot_id: str
    chunks: tuple[RetrievedChunk, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, RetrievalOutcome):
            raise KnowledgeRetrievalError("outcome must be a RetrievalOutcome")
        object.__setattr__(self, "snapshot_id", _text(self.snapshot_id, "snapshot_id", 128))
        if isinstance(self.chunks, str | bytes | bytearray) or not isinstance(
            self.chunks, Sequence
        ):
            raise KnowledgeRetrievalError("chunks must be a sequence")
        chunks = tuple(self.chunks)
        if len(chunks) > MAX_KNOWLEDGE_TOP_K:
            raise KnowledgeRetrievalError("chunks contains too many items")
        if any(not isinstance(chunk, RetrievedChunk) for chunk in chunks):
            raise KnowledgeRetrievalError("chunks contains an invalid item")
        if self.outcome is RetrievalOutcome.FOUND and not chunks:
            raise KnowledgeRetrievalError("FOUND requires at least one chunk")
        if self.outcome is not RetrievalOutcome.FOUND and chunks:
            raise KnowledgeRetrievalError("non-FOUND outcomes must not contain chunks")
        object.__setattr__(self, "chunks", chunks)


def snapshot_fingerprint(chunks: Sequence[RetrievedChunk]) -> str:
    """Return a non-authoritative stable fingerprint for retrieved provenance."""

    material = "|".join(
        f"{chunk.source_version_id}:{chunk.chunk_id}:{chunk.content_sha256}" for chunk in chunks
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


__all__ = [
    "KnowledgeAccessContext",
    "KnowledgeQuery",
    "KnowledgeRetrievalError",
    "KnowledgeRetrievalTimeoutError",
    "KnowledgeRetrievalUnavailableError",
    "PINNED_MIN_RANK_SCORE",
    "RetrievedChunk",
    "RetrievalOutcome",
    "RetrievalResult",
    "snapshot_fingerprint",
]
