"""Read-only PostgreSQL lexical retrieval implementation."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from ac_platform.knowledge.contracts import (
    KnowledgeQuery,
    KnowledgeRetrievalError,
    KnowledgeRetrievalTimeoutError,
    KnowledgeRetrievalUnavailableError,
    RetrievalOutcome,
    RetrievalResult,
    RetrievedChunk,
    snapshot_fingerprint,
)

STATEMENT_TIMEOUT_MS = 300

_RETRIEVAL_QUERY = text(
    """
    WITH authorized AS NOT MATERIALIZED (
        SELECT
            c.id AS chunk_id,
            s.source_key AS source_id,
            v.id AS source_version_id,
            c.tenant_id,
            c.ordinal,
            c.locator,
            c.passage,
            c.content_sha256,
            c.search_vector
        FROM knowledge_chunks AS c
        JOIN knowledge_source_versions AS v
          ON v.id = c.source_version_id
         AND v.tenant_id = c.tenant_id
        JOIN knowledge_sources AS s
          ON s.id = v.source_id
         AND s.tenant_id = c.tenant_id
        WHERE c.tenant_id = :tenant_id
          AND v.status = 'active'
          AND v.valid_from <= CURRENT_TIMESTAMP
          AND (v.valid_until IS NULL OR v.valid_until > CURRENT_TIMESTAMP)
          AND EXISTS (
              SELECT 1
              FROM knowledge_version_purposes AS vp
              WHERE vp.source_version_id = v.id
                AND vp.tenant_id = c.tenant_id
                AND vp.purpose = :purpose
          )
          AND (
              NOT EXISTS (
                  SELECT 1
                  FROM knowledge_chunk_acl AS open_acl
                  WHERE open_acl.chunk_id = c.id
                    AND open_acl.tenant_id = c.tenant_id
              )
              OR EXISTS (
                  SELECT 1
                  FROM knowledge_chunk_acl AS acl
                  WHERE acl.chunk_id = c.id
                    AND acl.tenant_id = c.tenant_id
                    AND acl.acl_subject_id = ANY(:acl_subject_ids)
              )
          )
          AND (
              CAST(:snapshot_id AS uuid) IS NULL
              OR v.id = CAST(:snapshot_id AS uuid)
          )
    ), ranked AS (
        SELECT
            authorized.*,
            ts_rank_cd(
                authorized.search_vector,
                websearch_to_tsquery('simple'::regconfig, :question)
            ) AS rank_score
        FROM authorized
        WHERE authorized.search_vector @@ websearch_to_tsquery('simple'::regconfig, :question)
        ORDER BY rank_score DESC, source_version_id ASC, ordinal ASC, chunk_id ASC
        LIMIT :top_k
    ), summary AS (
        SELECT EXISTS (SELECT 1 FROM authorized) AS authorized_exists
    )
    SELECT ranked.*, summary.authorized_exists
    FROM summary
    LEFT JOIN ranked ON TRUE
    ORDER BY ranked.rank_score DESC NULLS LAST,
             ranked.source_version_id ASC NULLS LAST,
             ranked.ordinal ASC NULLS LAST,
             ranked.chunk_id ASC NULLS LAST
    """
).bindparams(bindparam("acl_subject_ids", type_=ARRAY(PGUUID(as_uuid=True))))


def _row_value(row: Any, key: str) -> Any:
    """Read a mapping value from a SQLAlchemy Row without trusting user data."""

    return row._mapping[key]


class PostgresKnowledgeRepository:
    """Execute bounded, read-only lexical queries without borrowing caller state.

    The supplied session is used only to resolve its configured database bind.
    Retrieval itself always leases a separate pooled connection, so SQLAlchemy
    cannot autoflush pending caller ORM objects and the retrieval transaction
    cannot alter the caller's transaction or session-local settings.
    """

    def __init__(self, session: AsyncSession, *, engine: AsyncEngine | None = None) -> None:
        self._session = session
        self._engine = engine

    def _dedicated_engine(self, bind: object) -> AsyncEngine:
        """Return the async engine behind the caller session's configured bind."""

        if self._engine is not None:
            return self._engine
        if isinstance(bind, AsyncEngine):
            return bind
        if isinstance(bind, Engine) and bind.dialect.is_async:
            # AsyncSession.get_bind() intentionally returns the synchronous
            # proxy. Re-wrapping that proxy reuses the configured async pool
            # without touching the caller session's checked-out connection.
            return AsyncEngine(bind)
        candidate = getattr(bind, "engine", None)
        if isinstance(candidate, Engine) and candidate.dialect.is_async:
            # A session may be bound to an AsyncConnection rather than an
            # engine. Resolve its engine, then still acquire a fresh pooled
            # connection for this read.
            return AsyncEngine(candidate)
        raise KnowledgeRetrievalUnavailableError(
            "knowledge retrieval requires an async PostgreSQL engine"
        )

    @staticmethod
    def _is_statement_timeout(error: SQLAlchemyError) -> bool:
        """Recognize PostgreSQL's cancellation SQLSTATE without trusting text."""

        original: object = getattr(error, "orig", None)
        sqlstate = getattr(original, "sqlstate", None)
        if sqlstate is None:
            sqlstate = getattr(original, "pgcode", None)
        return sqlstate == "57014" or "statement timeout" in str(error).lower()

    async def search(self, query: KnowledgeQuery) -> RetrievalResult:
        try:
            bind = self._session.get_bind()
        except SQLAlchemyError as exc:
            raise KnowledgeRetrievalUnavailableError(
                "knowledge PostgreSQL bind was unavailable"
            ) from exc
        if getattr(getattr(bind, "dialect", None), "name", None) != "postgresql":
            raise KnowledgeRetrievalError("knowledge retrieval requires PostgreSQL")

        try:
            engine = self._dedicated_engine(bind)
            async with engine.connect() as connection:
                transaction = await connection.begin()
                try:
                    # Both settings disappear on the unconditional rollback
                    # below, before this pooled connection is reused.
                    await connection.execute(text("SET TRANSACTION READ ONLY"))
                    await connection.execute(
                        text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT_MS}ms'")
                    )
                    ranked_result = await connection.execute(
                        _RETRIEVAL_QUERY,
                        {
                            "tenant_id": query.access.tenant_id,
                            "purpose": query.access.purpose.value,
                            "acl_subject_ids": list(query.access.acl_subject_ids),
                            "snapshot_id": query.snapshot_id,
                            "question": query.question,
                            "top_k": query.top_k,
                        },
                    )
                    rows = list(ranked_result.mappings())
                finally:
                    # Never commit a retrieval transaction. This also keeps
                    # the caller's transaction and session-local settings
                    # completely untouched.
                    await transaction.rollback()
        except SQLAlchemyError as exc:
            if self._is_statement_timeout(exc):
                raise KnowledgeRetrievalTimeoutError(
                    "knowledge retrieval exceeded the statement timeout"
                ) from exc
            raise KnowledgeRetrievalUnavailableError(
                "knowledge PostgreSQL query was unavailable"
            ) from exc

        candidates: list[RetrievedChunk] = []
        authorized_exists = False
        for row in rows:
            authorized_exists = bool(row["authorized_exists"])
            if row["chunk_id"] is None:
                continue
            rank_score = Decimal(str(row["rank_score"]))
            if rank_score < query.min_rank_score:
                continue
            candidates.append(
                RetrievedChunk(
                    chunk_id=row["chunk_id"],
                    source_id=row["source_id"],
                    source_version_id=row["source_version_id"],
                    tenant_id=row["tenant_id"],
                    locator=row["locator"],
                    passage=row["passage"],
                    content_sha256=row["content_sha256"],
                    rank_score=rank_score,
                    snapshot_id=str(query.snapshot_id or "retrieval-result"),
                )
            )
        if not authorized_exists:
            return RetrievalResult(
                outcome=RetrievalOutcome.NO_AUTHORIZED_EVIDENCE,
                snapshot_id="knowledge-empty",
            )
        if not candidates:
            return RetrievalResult(
                outcome=RetrievalOutcome.BELOW_THRESHOLD,
                snapshot_id="knowledge-empty",
            )
        fingerprint = str(query.snapshot_id or snapshot_fingerprint(candidates))
        normalized = tuple(
            RetrievedChunk(
                chunk_id=chunk.chunk_id,
                source_id=chunk.source_id,
                source_version_id=chunk.source_version_id,
                tenant_id=chunk.tenant_id,
                locator=chunk.locator,
                passage=chunk.passage,
                content_sha256=chunk.content_sha256,
                rank_score=chunk.rank_score,
                snapshot_id=fingerprint,
            )
            for chunk in candidates
        )
        return RetrievalResult(
            outcome=RetrievalOutcome.FOUND,
            snapshot_id=fingerprint,
            chunks=normalized,
        )


__all__ = ["PostgresKnowledgeRepository", "STATEMENT_TIMEOUT_MS"]
