"""Provider-neutral, bounded contracts for advisory intelligence.

This module intentionally contains no provider SDK, persistence, retrieval, or
tool interface. Its values are advisory data and cannot become canonical state.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4

from ac_platform.intelligence.errors import (
    IntelligenceValidationError,
    ToolsDeniedError,
)

MAX_QUESTION_CHARS = 4_000
MAX_EVIDENCE_ITEMS = 12
MAX_EVIDENCE_CHARS = 8_000
MAX_CONTEXT_CHARS = 60_000
MAX_CITATIONS = 12
MAX_CITATION_CHARS = 512
MAX_OUTPUT_CHARS = 20_000
MAX_OUTPUT_TOKENS = 512
MAX_INPUT_TOKENS = 131_072


def _bounded_text(value: str, field_name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise IntelligenceValidationError(f"{field_name} must be text")
    normalized = value.strip()
    if not normalized:
        raise IntelligenceValidationError(f"{field_name} must not be blank")
    if "\x00" in normalized:
        raise IntelligenceValidationError(f"{field_name} contains a NUL byte")
    if len(normalized) > maximum:
        raise IntelligenceValidationError(f"{field_name} must be at most {maximum} characters")
    return normalized


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise IntelligenceValidationError(f"{field_name} must include a timezone")
    return value.astimezone(UTC)


def _uuid(value: object, field_name: str) -> UUID:
    if not isinstance(value, UUID):
        raise IntelligenceValidationError(f"{field_name} must be a UUID")
    return value


def _immutable_tuple[T](
    value: object,
    field_name: str,
    item_type: type[T],
    *,
    require_tuple: bool = False,
) -> tuple[T, ...]:
    if require_tuple and not isinstance(value, tuple):
        raise IntelligenceValidationError(f"{field_name} must be immutable")
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise IntelligenceValidationError(f"{field_name} must be a sequence")
    normalized = tuple(value)
    if any(not isinstance(item, item_type) for item in normalized):
        raise IntelligenceValidationError(f"{field_name} contains an invalid item")
    return normalized


def _token_count(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise IntelligenceValidationError(f"{field_name} must be an integer")
    if value < 0:
        raise IntelligenceValidationError(f"{field_name} cannot be negative")
    return value


class IntelligencePurpose(StrEnum):
    """Purposes that may be admitted by the first-slice harness."""

    SUPPORT_ASSISTANCE = "support_assistance"


class AdvisoryKind(StrEnum):
    ANSWER = "answer"
    ABSTAIN = "abstain"
    ESCALATE = "escalate"


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    """A caller-supplied evidence passage; its text remains untrusted content."""

    source_id: str
    passage: str
    locator: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _bounded_text(self.source_id, "source_id", 256))
        object.__setattr__(
            self,
            "passage",
            _bounded_text(self.passage, "passage", MAX_EVIDENCE_CHARS),
        )
        if self.locator is not None:
            object.__setattr__(
                self,
                "locator",
                _bounded_text(self.locator, "locator", MAX_CITATION_CHARS),
            )


def _validate_evidence_fields(item: EvidenceItem) -> None:
    _bounded_text(item.source_id, "source_id", 256)
    _bounded_text(item.passage, "passage", MAX_EVIDENCE_CHARS)
    if item.locator is not None:
        _bounded_text(item.locator, "locator", MAX_CITATION_CHARS)


def _validate_evidence(
    evidence: object,
    *,
    require_tuple: bool = False,
) -> tuple[EvidenceItem, ...]:
    normalized = _immutable_tuple(
        evidence,
        "evidence",
        EvidenceItem,
        require_tuple=require_tuple,
    )
    for item in normalized:
        _validate_evidence_fields(item)
    return normalized


@dataclass(frozen=True, slots=True)
class Citation:
    """A bounded pointer to evidence supporting an advisory answer."""

    source_id: str
    locator: str
    quote: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _bounded_text(self.source_id, "source_id", 256))
        object.__setattr__(
            self,
            "locator",
            _bounded_text(self.locator, "locator", MAX_CITATION_CHARS),
        )
        if self.quote is not None:
            object.__setattr__(
                self,
                "quote",
                _bounded_text(self.quote, "quote", MAX_CITATION_CHARS),
            )


@dataclass(frozen=True, slots=True)
class AnswerOutcome:
    answer: str
    citations: tuple[Citation, ...] = ()
    kind: AdvisoryKind = field(default=AdvisoryKind.ANSWER, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "answer", _bounded_text(self.answer, "answer", MAX_OUTPUT_CHARS))
        object.__setattr__(self, "citations", _validate_citations(self.citations))


@dataclass(frozen=True, slots=True)
class AbstainOutcome:
    reason: str
    missing_evidence: tuple[str, ...] = ()
    kind: AdvisoryKind = field(default=AdvisoryKind.ABSTAIN, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason", _bounded_text(self.reason, "reason", 1_000))
        missing_evidence = _immutable_tuple(self.missing_evidence, "missing_evidence", str)
        if len(missing_evidence) > MAX_EVIDENCE_ITEMS:
            raise IntelligenceValidationError("missing_evidence contains too many items")
        object.__setattr__(
            self,
            "missing_evidence",
            tuple(_bounded_text(item, "missing_evidence item", 256) for item in missing_evidence),
        )


@dataclass(frozen=True, slots=True)
class EscalateOutcome:
    reason: str
    queue: str | None = None
    kind: AdvisoryKind = field(default=AdvisoryKind.ESCALATE, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason", _bounded_text(self.reason, "reason", 1_000))
        if self.queue is not None:
            object.__setattr__(self, "queue", _bounded_text(self.queue, "queue", 128))


type AdvisoryOutcome = AnswerOutcome | AbstainOutcome | EscalateOutcome


def _validate_outcome(outcome: object, *, require_immutable: bool = False) -> None:
    if isinstance(outcome, AnswerOutcome):
        if outcome.kind is not AdvisoryKind.ANSWER:
            raise IntelligenceValidationError("answer outcome kind is invalid")
        _bounded_text(outcome.answer, "answer", MAX_OUTPUT_CHARS)
        _validate_citations(outcome.citations, require_tuple=require_immutable)
        return
    if isinstance(outcome, AbstainOutcome):
        if outcome.kind is not AdvisoryKind.ABSTAIN:
            raise IntelligenceValidationError("abstain outcome kind is invalid")
        _bounded_text(outcome.reason, "reason", 1_000)
        missing_evidence = _immutable_tuple(
            outcome.missing_evidence,
            "missing_evidence",
            str,
            require_tuple=require_immutable,
        )
        if len(missing_evidence) > MAX_EVIDENCE_ITEMS:
            raise IntelligenceValidationError("missing_evidence contains too many items")
        for item in missing_evidence:
            _bounded_text(item, "missing_evidence item", 256)
        return
    if isinstance(outcome, EscalateOutcome):
        if outcome.kind is not AdvisoryKind.ESCALATE:
            raise IntelligenceValidationError("escalate outcome kind is invalid")
        _bounded_text(outcome.reason, "reason", 1_000)
        if outcome.queue is not None:
            _bounded_text(outcome.queue, "queue", 128)
        return
    raise IntelligenceValidationError("provider outcome is not a typed advisory outcome")


def _validate_citations(
    citations: object,
    *,
    require_tuple: bool = False,
) -> tuple[Citation, ...]:
    normalized = _immutable_tuple(
        citations,
        "citations",
        Citation,
        require_tuple=require_tuple,
    )
    if len(normalized) > MAX_CITATIONS:
        raise IntelligenceValidationError("citations contains too many items")
    for citation in normalized:
        _validate_citation_fields(citation)
    if len({(citation.source_id, citation.locator) for citation in normalized}) != len(normalized):
        raise IntelligenceValidationError("citations must not contain duplicates")
    return normalized


def _validate_citation_fields(citation: Citation) -> None:
    _bounded_text(citation.source_id, "source_id", 256)
    _bounded_text(citation.locator, "locator", MAX_CITATION_CHARS)
    if citation.quote is not None:
        _bounded_text(citation.quote, "quote", MAX_CITATION_CHARS)


@dataclass(frozen=True, slots=True)
class ModelProfile:
    """A non-secret, versioned description of one generation target."""

    profile_id: str
    provider: str
    model: str
    revision: str
    runtime: str
    max_input_tokens: int = 8_192
    max_output_tokens: int = MAX_OUTPUT_TOKENS
    tools_enabled: bool = False

    def __post_init__(self) -> None:
        for name in ("profile_id", "provider", "model", "revision", "runtime"):
            object.__setattr__(self, name, _bounded_text(getattr(self, name), name, 256))
        if isinstance(self.max_input_tokens, bool) or not isinstance(self.max_input_tokens, int):
            raise IntelligenceValidationError("max_input_tokens must be an integer")
        if not 1 <= self.max_input_tokens <= MAX_INPUT_TOKENS:
            raise IntelligenceValidationError("max_input_tokens is outside the permitted bound")
        if isinstance(self.max_output_tokens, bool) or not isinstance(self.max_output_tokens, int):
            raise IntelligenceValidationError("max_output_tokens must be an integer")
        if not 1 <= self.max_output_tokens <= MAX_OUTPUT_TOKENS:
            raise IntelligenceValidationError("max_output_tokens is outside the permitted bound")
        if not isinstance(self.tools_enabled, bool):
            raise IntelligenceValidationError("tools_enabled must be a boolean")
        if self.tools_enabled:
            raise ToolsDeniedError("the Phase-1 intelligence harness cannot enable tools")


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    """A bounded, tenant-scoped request with an absolute UTC deadline."""

    request_id: UUID
    tenant_id: UUID
    actor_id: UUID
    purpose: IntelligencePurpose
    question: str
    deadline: datetime
    evidence: tuple[EvidenceItem, ...] = ()
    output_tokens: int = 256
    tool_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _uuid(self.request_id, "request_id"))
        object.__setattr__(self, "tenant_id", _uuid(self.tenant_id, "tenant_id"))
        object.__setattr__(self, "actor_id", _uuid(self.actor_id, "actor_id"))
        object.__setattr__(
            self,
            "question",
            _bounded_text(self.question, "question", MAX_QUESTION_CHARS),
        )
        object.__setattr__(self, "deadline", _utc(self.deadline, "deadline"))
        evidence = _validate_evidence(self.evidence)
        tool_names = _immutable_tuple(self.tool_names, "tool_names", str)
        if len(evidence) > MAX_EVIDENCE_ITEMS:
            raise IntelligenceValidationError("evidence contains too many items")
        object.__setattr__(self, "evidence", evidence)
        object.__setattr__(
            self,
            "tool_names",
            tuple(_bounded_text(item, "tool name", 128) for item in tool_names),
        )
        context_chars = len(self.question) + sum(len(item.passage) for item in evidence)
        if context_chars > MAX_CONTEXT_CHARS:
            raise IntelligenceValidationError("evidence exceeds the context character bound")
        output_tokens = _token_count(self.output_tokens, "output_tokens")
        object.__setattr__(self, "output_tokens", output_tokens)
        if not 1 <= output_tokens <= MAX_OUTPUT_TOKENS:
            raise IntelligenceValidationError("output_tokens is outside the permitted bound")
        if self.tool_names:
            raise ToolsDeniedError("tool use is disabled for advisory generation")

    @classmethod
    def new(
        cls,
        *,
        tenant_id: UUID,
        actor_id: UUID,
        purpose: IntelligencePurpose,
        question: str,
        deadline: datetime,
        evidence: Sequence[EvidenceItem] = (),
        output_tokens: int = 256,
    ) -> GenerationRequest:
        return cls(
            request_id=uuid4(),
            tenant_id=tenant_id,
            actor_id=actor_id,
            purpose=purpose,
            question=question,
            deadline=deadline,
            evidence=tuple(evidence),
            output_tokens=output_tokens,
        )

    def remaining_seconds(self, now: datetime) -> float:
        remaining = (self.deadline - _utc(now, "now")).total_seconds()
        return remaining


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "input_tokens", _token_count(self.input_tokens, "input_tokens"))
        object.__setattr__(self, "output_tokens", _token_count(self.output_tokens, "output_tokens"))
        if self.output_tokens > MAX_OUTPUT_TOKENS:
            raise IntelligenceValidationError("provider output exceeds the token bound")


@dataclass(frozen=True, slots=True)
class GenerationResult:
    """A provider result already normalized into an advisory outcome."""

    request_id: UUID
    profile_id: str
    outcome: AdvisoryOutcome
    usage: Usage = field(default_factory=Usage)
    tool_calls: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _uuid(self.request_id, "request_id"))
        object.__setattr__(self, "profile_id", _bounded_text(self.profile_id, "profile_id", 256))
        if not isinstance(self.usage, Usage):
            raise IntelligenceValidationError("provider usage is not a Usage value")
        _validate_outcome(self.outcome)
        tool_calls = _immutable_tuple(self.tool_calls, "tool_calls", str)
        object.__setattr__(
            self,
            "tool_calls",
            tuple(_bounded_text(item, "tool call", 128) for item in tool_calls),
        )
        if tool_calls:
            raise ToolsDeniedError("provider attempted tool use")


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    """Non-authoritative execution provenance suitable for later persistence."""

    execution_id: UUID
    request_id: UUID
    profile_id: str
    started_at: datetime
    completed_at: datetime
    output_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "execution_id", _uuid(self.execution_id, "execution_id"))
        object.__setattr__(self, "request_id", _uuid(self.request_id, "request_id"))
        object.__setattr__(self, "profile_id", _bounded_text(self.profile_id, "profile_id", 256))
        object.__setattr__(self, "started_at", _utc(self.started_at, "started_at"))
        object.__setattr__(self, "completed_at", _utc(self.completed_at, "completed_at"))
        if self.completed_at < self.started_at:
            raise IntelligenceValidationError("completed_at must not precede started_at")
        if len(self.output_digest) != 64 or any(
            character not in "0123456789abcdef" for character in self.output_digest
        ):
            raise IntelligenceValidationError("output_digest must be a lowercase SHA-256 digest")


@dataclass(frozen=True, slots=True)
class IntelligenceResponse:
    """Advisory output plus provenance; this object has no write authority."""

    outcome: AdvisoryOutcome
    execution: ExecutionRecord
    advisory: bool = field(default=True, init=False)


def validate_generation_request(request: object) -> None:
    """Revalidate a request without normalizing mutable provider boundary data."""

    if not isinstance(request, GenerationRequest):
        raise IntelligenceValidationError("request is not a GenerationRequest")
    _uuid(request.request_id, "request_id")
    _uuid(request.tenant_id, "tenant_id")
    _uuid(request.actor_id, "actor_id")
    _bounded_text(request.question, "question", MAX_QUESTION_CHARS)
    _utc(request.deadline, "deadline")
    evidence = _validate_evidence(request.evidence, require_tuple=True)
    if len(evidence) > MAX_EVIDENCE_ITEMS:
        raise IntelligenceValidationError("evidence contains too many items")
    if len(request.question) + sum(len(item.passage) for item in evidence) > MAX_CONTEXT_CHARS:
        raise IntelligenceValidationError("evidence exceeds the context character bound")
    _token_count(request.output_tokens, "output_tokens")
    if not 1 <= request.output_tokens <= MAX_OUTPUT_TOKENS:
        raise IntelligenceValidationError("output_tokens is outside the permitted bound")
    tool_names = _immutable_tuple(request.tool_names, "tool_names", str, require_tuple=True)
    for item in tool_names:
        _bounded_text(item, "tool name", 128)


def validate_generation_result(result: object) -> None:
    """Revalidate every provider-controlled result field at the trust boundary."""

    if not isinstance(result, GenerationResult):
        raise IntelligenceValidationError("provider returned a non-contract result")
    _uuid(result.request_id, "request_id")
    _bounded_text(result.profile_id, "profile_id", 256)
    if not isinstance(result.usage, Usage):
        raise IntelligenceValidationError("provider usage is not a Usage value")
    _token_count(result.usage.input_tokens, "input_tokens")
    _token_count(result.usage.output_tokens, "output_tokens")
    if result.usage.output_tokens > MAX_OUTPUT_TOKENS:
        raise IntelligenceValidationError("provider output exceeds the token bound")
    _validate_outcome(result.outcome, require_immutable=True)
    tool_calls = _immutable_tuple(result.tool_calls, "tool_calls", str, require_tuple=True)
    for item in tool_calls:
        _bounded_text(item, "tool call", 128)
    if tool_calls:
        raise ToolsDeniedError("provider attempted tool use")


def validate_answer_grounding(
    outcome: AnswerOutcome,
    evidence: tuple[EvidenceItem, ...],
) -> None:
    """Require each answer citation to point to one unambiguous evidence item."""

    _validate_outcome(outcome, require_immutable=True)
    if not outcome.citations:
        return
    normalized = _validate_evidence(evidence, require_tuple=True)
    sources: dict[str, list[EvidenceItem]] = {}
    for item in normalized:
        sources.setdefault(item.source_id, []).append(item)
    if any(len(items) != 1 for items in sources.values()):
        raise IntelligenceValidationError("duplicate evidence source IDs make citations ambiguous")
    for citation in outcome.citations:
        matches = sources.get(citation.source_id, [])
        if not matches:
            raise IntelligenceValidationError("citation source is absent from request evidence")
        item = matches[0]
        if citation.locator != item.locator:
            raise IntelligenceValidationError("citation locator does not match evidence locator")
        if citation.quote is not None and citation.quote not in item.passage:
            raise IntelligenceValidationError("citation quote is not grounded in evidence")


class GenerationPort(Protocol):
    """Provider-neutral port implemented by a future local or remote adapter."""

    async def generate(self, request: GenerationRequest, profile: ModelProfile) -> GenerationResult:
        """Return a normalized advisory result without changing application state."""


def outcome_digest(outcome: AdvisoryOutcome) -> str:
    """Return a stable digest without retaining the model's raw prompt or output."""

    if isinstance(outcome, AnswerOutcome):
        payload: Mapping[str, object] = {
            "kind": outcome.kind.value,
            "answer": outcome.answer,
            "citations": [
                {"source_id": item.source_id, "locator": item.locator, "quote": item.quote}
                for item in outcome.citations
            ],
        }
    elif isinstance(outcome, AbstainOutcome):
        payload = {
            "kind": outcome.kind.value,
            "reason": outcome.reason,
            "missing_evidence": list(outcome.missing_evidence),
        }
    else:
        payload = {"kind": outcome.kind.value, "reason": outcome.reason, "queue": outcome.queue}
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "AbstainOutcome",
    "AdvisoryKind",
    "AdvisoryOutcome",
    "AnswerOutcome",
    "Citation",
    "EscalateOutcome",
    "EvidenceItem",
    "ExecutionRecord",
    "GenerationPort",
    "GenerationRequest",
    "GenerationResult",
    "IntelligencePurpose",
    "IntelligenceResponse",
    "MAX_INPUT_TOKENS",
    "MAX_OUTPUT_TOKENS",
    "ModelProfile",
    "Usage",
    "outcome_digest",
    "validate_answer_grounding",
    "validate_generation_request",
    "validate_generation_result",
]
