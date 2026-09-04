"""Read-only, tenant-safe knowledge retrieval contracts.

The knowledge package is deliberately inert in the first Phase-2 slice.  It
contains no HTTP registration, ingestion worker, model/provider integration,
or write authority.  PostgreSQL retrieval returns advisory evidence that can
later be adapted to the Phase-1 intelligence contracts.
"""

from ac_platform.knowledge.contracts import (
    PINNED_MIN_RANK_SCORE,
    KnowledgeAccessContext,
    KnowledgeQuery,
    KnowledgeRetrievalError,
    KnowledgeRetrievalTimeoutError,
    KnowledgeRetrievalUnavailableError,
    RetrievalOutcome,
    RetrievalResult,
    RetrievedChunk,
)
from ac_platform.knowledge.evaluation import (
    GoldCase,
    GoldEvaluation,
    evaluate_gold_set,
    load_gold_set,
)
from ac_platform.knowledge.repository import PostgresKnowledgeRepository

# Deliberately inert until a later reviewed route/integration slice passes all
# activation gates.  This package has no code path that reads the flag yet.
KNOWLEDGE_RETRIEVAL_ENABLED = False

__all__ = [
    "KnowledgeAccessContext",
    "KnowledgeQuery",
    "KnowledgeRetrievalError",
    "KnowledgeRetrievalTimeoutError",
    "KnowledgeRetrievalUnavailableError",
    "PINNED_MIN_RANK_SCORE",
    "GoldCase",
    "GoldEvaluation",
    "KNOWLEDGE_RETRIEVAL_ENABLED",
    "PostgresKnowledgeRepository",
    "RetrievedChunk",
    "RetrievalOutcome",
    "RetrievalResult",
    "evaluate_gold_set",
    "load_gold_set",
]
