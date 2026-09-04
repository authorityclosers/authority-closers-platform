"""PostgreSQL integration coverage for the inert knowledge read model."""

from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from ac_platform.intelligence import IntelligencePurpose
from ac_platform.knowledge import (
    PINNED_MIN_RANK_SCORE,
    KnowledgeAccessContext,
    KnowledgeQuery,
    PostgresKnowledgeRepository,
    RetrievalOutcome,
)

ROOT = Path(__file__).parents[2]
NOW = datetime.now(UTC).replace(microsecond=0)


def _postgres_url() -> URL:
    raw = os.getenv("AC_KNOWLEDGE_POSTGRES_TEST_URL") or os.getenv("AC_TEST_DATABASE_URL")
    if not raw:
        if os.getenv("AC_REQUIRE_KNOWLEDGE_POSTGRES_TEST") == "1":
            pytest.fail("knowledge PostgreSQL URL is required but not configured")
        pytest.skip("knowledge PostgreSQL URL is not configured")
    url = make_url(raw)
    if url.get_backend_name() != "postgresql":
        pytest.fail("knowledge integration requires PostgreSQL")
    if (
        url.host not in {None, "127.0.0.1", "localhost", "::1"}
        and os.getenv("AC_ALLOW_REMOTE_TEST_DATABASE") != "1"
    ):
        pytest.skip("refusing to mutate a non-local PostgreSQL database")
    return url.set(drivername="postgresql+psycopg")


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[URL]:
    base_url = _postgres_url()
    schema = f"knowledge_{uuid4().hex}"
    admin_engine = create_engine(base_url, pool_pre_ping=True)
    created = False
    try:
        with admin_engine.begin() as connection:
            connection.execute(CreateSchema(schema))
        created = True
        query = dict(base_url.query)
        query["options"] = f"-csearch_path={schema}"
        schema_url = base_url.set(query=query)
        environment = os.environ.copy()
        environment.update(
            {
                "AC_DATABASE_URL": base_url.render_as_string(hide_password=False),
                "AC_DATABASE_MIGRATOR_URL": base_url.render_as_string(hide_password=False),
                "AC_ENVIRONMENT": "test",
                "PGOPTIONS": f"-csearch_path={schema}",
                "PYTHONPATH": os.pathsep.join(
                    part
                    for part in (
                        str(ROOT / "packages" / "python"),
                        environment.get("PYTHONPATH", ""),
                    )
                    if part
                ),
            }
        )
        migration = subprocess.run(  # noqa: S603 - fixed local Alembic command
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if migration.returncode != 0:
            pytest.fail(
                f"fresh PostgreSQL migration failed\n{migration.stdout}\n{migration.stderr}"
            )
        yield schema_url
    finally:
        if created:
            with admin_engine.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True))
        admin_engine.dispose()


def _run(coroutine):
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        return runner.run(coroutine)


async def _seed(schema_url: URL) -> dict[str, UUID]:
    engine = create_async_engine(schema_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    tenant_a, tenant_b = uuid4(), uuid4()
    source_a, source_b = uuid4(), uuid4()
    version_a, version_b = uuid4(), uuid4()
    open_chunk, restricted_chunk, other_tenant_chunk = uuid4(), uuid4(), uuid4()
    acl_subject_a, acl_subject_b = uuid4(), uuid4()
    async with sessions() as session:
        await session.execute(
            text(
                "INSERT INTO tenants (id, slug, name, status, revision) VALUES "
                "(:a, :slug_a, 'Tenant A', 'active', 0), "
                "(:b, :slug_b, 'Tenant B', 'active', 0)"
            ),
            {
                "a": tenant_a,
                "b": tenant_b,
                "slug_a": f"tenant-a-{tenant_a.hex}",
                "slug_b": f"tenant-b-{tenant_b.hex}",
            },
        )
        await session.execute(
            text(
                "INSERT INTO knowledge_sources "
                "(id, tenant_id, source_key, title, provenance_uri, source_kind) VALUES "
                "(:source_a, :tenant_a, 'support-policy', 'Support policy', "
                "'fixture://support', 'fixture'), "
                "(:source_b, :tenant_b, 'tenant-b-policy', 'Tenant B policy', "
                "'fixture://tenant-b', 'fixture')"
            ),
            {
                "source_a": source_a,
                "tenant_a": tenant_a,
                "source_b": source_b,
                "tenant_b": tenant_b,
            },
        )
        await session.execute(
            text(
                "INSERT INTO knowledge_source_versions "
                "(id, source_id, tenant_id, version_no, status, valid_from, content_sha256) VALUES "
                "(:version_a, :source_a, :tenant_a, 1, 'active', :now, :digest_a), "
                "(:version_b, :source_b, :tenant_b, 1, 'active', :now, :digest_b)"
            ),
            {
                "version_a": version_a,
                "source_a": source_a,
                "tenant_a": tenant_a,
                "version_b": version_b,
                "source_b": source_b,
                "tenant_b": tenant_b,
                "now": NOW - timedelta(days=1),
                "digest_a": "a" * 64,
                "digest_b": "b" * 64,
            },
        )
        await session.execute(
            text(
                "INSERT INTO knowledge_version_purposes "
                "(source_version_id, tenant_id, purpose) VALUES "
                "(:version_a, :tenant_a, 'support_assistance'), "
                "(:version_b, :tenant_b, 'support_assistance')"
            ),
            {
                "version_a": version_a,
                "tenant_a": tenant_a,
                "version_b": version_b,
                "tenant_b": tenant_b,
            },
        )
        await session.execute(
            text(
                "INSERT INTO knowledge_chunks "
                "(id, source_version_id, tenant_id, ordinal, locator, passage, "
                "content_sha256) VALUES "
                "(:open, :version_a, :tenant_a, 0, 'recovery.md#email', "
                "'Account recovery requires verified support review.', :digest_open), "
                "(:restricted, :version_a, :tenant_a, 1, 'support.md#readonly', "
                "'Support can diagnose access but cannot change the rubric.', :digest_restricted), "
                "(:other, :version_b, :tenant_b, 0, 'recovery.md#email', "
                "'Tenant B account recovery policy.', :digest_other)"
            ),
            {
                "open": open_chunk,
                "restricted": restricted_chunk,
                "other": other_tenant_chunk,
                "version_a": version_a,
                "version_b": version_b,
                "tenant_a": tenant_a,
                "tenant_b": tenant_b,
                "digest_open": hashlib.sha256(b"open").hexdigest(),
                "digest_restricted": hashlib.sha256(b"restricted").hexdigest(),
                "digest_other": hashlib.sha256(b"other").hexdigest(),
            },
        )
        await session.execute(
            text(
                "INSERT INTO knowledge_chunk_acl (chunk_id, tenant_id, acl_subject_id) VALUES "
                "(:chunk, :tenant, :subject_a), (:chunk, :tenant, :subject_b)"
            ),
            {
                "chunk": restricted_chunk,
                "tenant": tenant_a,
                "subject_a": acl_subject_a,
                "subject_b": acl_subject_b,
            },
        )
        await session.commit()
    await engine.dispose()
    return {
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "version_a": version_a,
        "open_chunk": open_chunk,
        "restricted_chunk": restricted_chunk,
        "other_tenant_chunk": other_tenant_chunk,
        "acl_subject_a": acl_subject_a,
        "acl_subject_b": acl_subject_b,
        "acl_subject_unlisted": uuid4(),
        "source_a": source_a,
    }


def test_postgresql_retrieval_is_tenant_acl_safe_and_deterministic(postgres_harness: URL) -> None:
    ids = _run(_seed(postgres_harness))

    async def exercise() -> None:
        engine = create_async_engine(postgres_harness, pool_pre_ping=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session:
            query = KnowledgeQuery(
                access=KnowledgeAccessContext(
                    tenant_id=ids["tenant_a"],
                    purpose=IntelligencePurpose.SUPPORT_ASSISTANCE,
                    acl_subject_ids=(ids["acl_subject_a"],),
                ),
                question="account recovery support review",
                min_rank_score=PINNED_MIN_RANK_SCORE,
                top_k=12,
            )
            first = await PostgresKnowledgeRepository(session).search(query)
            second = await PostgresKnowledgeRepository(session).search(query)
            assert first.outcome is RetrievalOutcome.FOUND
            assert first.chunks == second.chunks
            assert {chunk.tenant_id for chunk in first.chunks} == {ids["tenant_a"]}
            assert {chunk.locator for chunk in first.chunks} == {"recovery.md#email"}
            assert first.chunks[0].content_sha256 == hashlib.sha256(b"open").hexdigest()

            other = await PostgresKnowledgeRepository(session).search(
                KnowledgeQuery(
                    access=KnowledgeAccessContext(
                        tenant_id=ids["tenant_b"],
                        purpose=IntelligencePurpose.SUPPORT_ASSISTANCE,
                    ),
                    question="account recovery",
                    min_rank_score=PINNED_MIN_RANK_SCORE,
                )
            )
            assert other.outcome is RetrievalOutcome.FOUND
            assert all(chunk.tenant_id == ids["tenant_b"] for chunk in other.chunks)

            restricted = await PostgresKnowledgeRepository(session).search(
                KnowledgeQuery(
                    access=KnowledgeAccessContext(
                        tenant_id=ids["tenant_a"],
                        purpose=IntelligencePurpose.SUPPORT_ASSISTANCE,
                        acl_subject_ids=(ids["acl_subject_a"],),
                    ),
                    question="support rubric",
                    min_rank_score=PINNED_MIN_RANK_SCORE,
                )
            )
            assert restricted.outcome is RetrievalOutcome.FOUND
            assert {chunk.locator for chunk in restricted.chunks} == {"support.md#readonly"}

            denied = await PostgresKnowledgeRepository(session).search(
                KnowledgeQuery(
                    access=KnowledgeAccessContext(
                        tenant_id=ids["tenant_a"],
                        purpose=IntelligencePurpose.SUPPORT_ASSISTANCE,
                        acl_subject_ids=(ids["acl_subject_unlisted"],),
                    ),
                    question="support rubric",
                    min_rank_score=PINNED_MIN_RANK_SCORE,
                )
            )
            assert denied.outcome is RetrievalOutcome.BELOW_THRESHOLD
            assert not denied.chunks

            below = await PostgresKnowledgeRepository(session).search(
                KnowledgeQuery(
                    access=KnowledgeAccessContext(
                        tenant_id=ids["tenant_a"],
                        purpose=IntelligencePurpose.SUPPORT_ASSISTANCE,
                    ),
                    question="account recovery",
                    min_rank_score=PINNED_MIN_RANK_SCORE,
                )
            )
            assert below.outcome is RetrievalOutcome.BELOW_THRESHOLD
            assert not below.chunks
        await engine.dispose()

    _run(exercise())


def test_postgresql_withdrawn_version_is_not_retrievable(postgres_harness: URL) -> None:
    ids = _run(_seed(postgres_harness))

    async def exercise() -> None:
        engine = create_async_engine(postgres_harness, pool_pre_ping=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session:
            with pytest.raises(DBAPIError):
                await session.execute(
                    text("UPDATE knowledge_chunks SET passage = 'mutated' WHERE id = :id"),
                    {"id": ids["open_chunk"]},
                )
            await session.rollback()
            with pytest.raises(DBAPIError):
                await session.execute(
                    text(
                        "UPDATE knowledge_source_versions SET status = 'withdrawn' WHERE id = :id"
                    ),
                    {"id": ids["version_a"]},
                )
            await session.rollback()
            await session.execute(
                text(
                    "UPDATE knowledge_source_versions "
                    "SET status = 'withdrawn', valid_until = :valid_until WHERE id = :id"
                ),
                {"id": ids["version_a"], "valid_until": NOW},
            )
            await session.commit()
            result = await PostgresKnowledgeRepository(session).search(
                KnowledgeQuery(
                    access=KnowledgeAccessContext(
                        tenant_id=ids["tenant_a"],
                        purpose=IntelligencePurpose.SUPPORT_ASSISTANCE,
                    ),
                    question="account recovery",
                    min_rank_score=PINNED_MIN_RANK_SCORE,
                )
            )
            assert result.outcome is RetrievalOutcome.NO_AUTHORIZED_EVIDENCE
            assert not result.chunks
        await engine.dispose()

    _run(exercise())


def test_postgresql_knowledge_schema_guards_and_fts(postgres_harness: URL) -> None:
    ids = _run(_seed(postgres_harness))

    async def exercise() -> None:
        engine = create_async_engine(postgres_harness, pool_pre_ping=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session:
            with pytest.raises(DBAPIError):
                await session.execute(
                    text("UPDATE knowledge_sources SET title = 'mutated' WHERE id = :id"),
                    {"id": ids["source_a"]},
                )
            await session.rollback()

            with pytest.raises(DBAPIError):
                await session.execute(
                    text(
                        "INSERT INTO knowledge_source_versions "
                        "(id, source_id, tenant_id, version_no, status, valid_from, "
                        "content_sha256) "
                        "VALUES (:id, :source, :tenant, 2, 'active', :now, :digest)"
                    ),
                    {
                        "id": uuid4(),
                        "source": ids["source_a"],
                        "tenant": ids["tenant_a"],
                        "now": NOW,
                        "digest": "z" * 64,
                    },
                )
            await session.rollback()

            with pytest.raises(DBAPIError):
                await session.execute(
                    text(
                        "INSERT INTO knowledge_chunks "
                        "(id, source_version_id, tenant_id, ordinal, locator, passage, "
                        "content_sha256) "
                        "VALUES (:id, :version, :tenant, 9, 'invalid#tenant', "
                        "'Cross tenant', :digest)"
                    ),
                    {
                        "id": uuid4(),
                        "version": ids["version_a"],
                        "tenant": ids["tenant_b"],
                        "digest": hashlib.sha256(b"cross").hexdigest(),
                    },
                )
            await session.rollback()

            with pytest.raises(DBAPIError):
                await session.execute(
                    text(
                        "UPDATE knowledge_chunk_acl SET acl_subject_id = :subject "
                        "WHERE chunk_id = :chunk"
                    ),
                    {"subject": uuid4(), "chunk": ids["restricted_chunk"]},
                )
            await session.rollback()

            vector = await session.execute(
                text(
                    "SELECT search_vector IS NOT NULL AS populated "
                    "FROM knowledge_chunks WHERE id = :id"
                ),
                {"id": ids["open_chunk"]},
            )
            assert vector.scalar_one() is True
            index = await session.execute(
                text("SELECT to_regclass('ix_knowledge_chunks_search_vector')")
            )
            assert index.scalar_one() == "ix_knowledge_chunks_search_vector"
        await engine.dispose()

    _run(exercise())
