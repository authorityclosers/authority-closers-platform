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
    GoldPrediction,
    KnowledgeAccessContext,
    KnowledgeQuery,
    PostgresKnowledgeRepository,
    RetrievalOutcome,
    canonical_knowledge_version_digest,
    evaluate_gold_set,
    gold_access_context,
    gold_acl_subject_id,
    gold_tenant_id,
    load_gold_set,
)
from ac_platform.tenancy.models import Tenant

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
    tenant_a, tenant_b = gold_tenant_id("tenant-a"), gold_tenant_id("tenant-b")
    source_a, source_b, withdrawn_source, state_source = uuid4(), uuid4(), uuid4(), uuid4()
    version_a, version_b, withdrawn_version, state_version = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    open_chunk, restricted_chunk = uuid4(), uuid4()
    access_chunk, state_chunk, other_tenant_chunk = uuid4(), uuid4(), uuid4()
    acl_subject_a, acl_subject_b = gold_acl_subject_id("subject-support"), uuid4()
    open_passage = (
        "How does account recovery work? Account recovery requires verified support review."
    )
    restricted_passage = (
        "Can support change the rubric? Support can diagnose access but cannot change the rubric."
    )
    access_passage = (
        "Where can a learner read the access policy? Learners can read the access policy "
        "in the support handbook."
    )
    state_passage = (
        "What is the canonical learner progress source? Learner progress source is canonical "
        "in the enrollment state ledger."
    )
    other_passage = "How does account recovery work? Tenant B account recovery policy."
    version_a_digest = canonical_knowledge_version_digest(
        (
            (0, "recovery.md#email", open_passage),
            (1, "support.md#readonly", restricted_passage),
            (2, "access.md#overview", access_passage),
        )
    )
    state_version_digest = canonical_knowledge_version_digest(
        ((0, "state.md#canonical", state_passage),)
    )
    version_b_digest = canonical_knowledge_version_digest(
        ((0, "recovery.md#email", other_passage),)
    )
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
                "'fixture://tenant-b', 'fixture'), "
                "(:withdrawn_source, :tenant_a, 'withdrawn-policy', 'Withdrawn policy', "
                "'fixture://withdrawn', 'fixture'), "
                "(:state_source, :tenant_a, 'platform-contract', 'Platform contract', "
                "'fixture://platform-contract', 'fixture')"
            ),
            {
                "source_a": source_a,
                "tenant_a": tenant_a,
                "source_b": source_b,
                "tenant_b": tenant_b,
                "withdrawn_source": withdrawn_source,
                "state_source": state_source,
            },
        )
        await session.execute(
            text(
                "INSERT INTO knowledge_source_versions "
                "(id, source_id, tenant_id, version_no, status, valid_from, content_sha256) VALUES "
                "(:version_a, :source_a, :tenant_a, 1, 'active', :now, :digest_a), "
                "(:version_b, :source_b, :tenant_b, 1, 'active', :now, :digest_b), "
                "(:withdrawn_version, :withdrawn_source, :tenant_a, 1, 'active', "
                ":withdrawn_now, :withdrawn_digest), "
                "(:state_version, :state_source, :tenant_a, 1, 'active', "
                ":state_now, :state_digest)"
            ),
            {
                "version_a": version_a,
                "source_a": source_a,
                "tenant_a": tenant_a,
                "version_b": version_b,
                "source_b": source_b,
                "tenant_b": tenant_b,
                "now": NOW - timedelta(days=1),
                "digest_a": version_a_digest,
                "digest_b": version_b_digest,
                "withdrawn_version": withdrawn_version,
                "withdrawn_source": withdrawn_source,
                "withdrawn_now": NOW - timedelta(days=2),
                "withdrawn_digest": canonical_knowledge_version_digest(()),
                "state_version": state_version,
                "state_source": state_source,
                "state_now": NOW - timedelta(days=1),
                "state_digest": state_version_digest,
            },
        )
        await session.execute(
            text(
                "INSERT INTO knowledge_version_purposes "
                "(source_version_id, tenant_id, purpose) VALUES "
                "(:version_a, :tenant_a, 'support_assistance'), "
                "(:version_b, :tenant_b, 'support_assistance'), "
                "(:withdrawn_version, :tenant_a, 'support_assistance'), "
                "(:state_version, :tenant_a, 'support_assistance')"
            ),
            {
                "version_a": version_a,
                "tenant_a": tenant_a,
                "version_b": version_b,
                "tenant_b": tenant_b,
                "withdrawn_version": withdrawn_version,
                "state_version": state_version,
            },
        )
        await session.execute(
            text(
                "INSERT INTO knowledge_chunks "
                "(id, source_version_id, tenant_id, ordinal, locator, passage, "
                "content_sha256) VALUES "
                "(:open, :version_a, :tenant_a, 0, 'recovery.md#email', "
                "'How does account recovery work? Account recovery requires verified support "
                "review.', "
                ":digest_open), "
                "(:restricted, :version_a, :tenant_a, 1, 'support.md#readonly', "
                "'Can support change the rubric? Support can diagnose access but cannot change the "
                "rubric.', "
                ":digest_restricted), "
                "(:access, :version_a, :tenant_a, 2, 'access.md#overview', "
                "'Where can a learner read the access policy? Learners can read the access policy "
                "in the support handbook.', :digest_access), "
                "(:state, :state_version, :tenant_a, 0, 'state.md#canonical', "
                "'What is the canonical learner progress source? Learner progress source is "
                "canonical "
                "in the enrollment state ledger.', "
                ":digest_state), "
                "(:other, :version_b, :tenant_b, 0, 'recovery.md#email', "
                "'How does account recovery work? Tenant B account recovery policy.', "
                ":digest_other)"
            ),
            {
                "open": open_chunk,
                "restricted": restricted_chunk,
                "access": access_chunk,
                "state": state_chunk,
                "other": other_tenant_chunk,
                "version_a": version_a,
                "version_b": version_b,
                "state_version": state_version,
                "tenant_a": tenant_a,
                "tenant_b": tenant_b,
                "digest_open": hashlib.sha256(open_passage.encode("utf-8")).hexdigest(),
                "digest_restricted": hashlib.sha256(
                    restricted_passage.encode("utf-8")
                ).hexdigest(),
                "digest_access": hashlib.sha256(access_passage.encode("utf-8")).hexdigest(),
                "digest_state": hashlib.sha256(state_passage.encode("utf-8")).hexdigest(),
                "digest_other": hashlib.sha256(other_passage.encode("utf-8")).hexdigest(),
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
        await session.execute(
            text(
                "UPDATE knowledge_source_versions SET status = 'withdrawn', "
                "valid_until = :valid_until WHERE id = :id"
            ),
            {"id": withdrawn_version, "valid_until": NOW},
        )
        await session.commit()
    await engine.dispose()
    return {
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "version_a": version_a,
        "withdrawn_version": withdrawn_version,
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
            assert first.chunks[0].content_sha256 == hashlib.sha256(
                b"How does account recovery work? "
                b"Account recovery requires verified support review."
            ).hexdigest()

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
                    question="unrelated billing escalation",
                    min_rank_score=PINNED_MIN_RANK_SCORE,
                )
            )
            assert below.outcome is RetrievalOutcome.BELOW_THRESHOLD
            assert not below.chunks
        await engine.dispose()

    _run(exercise())


def test_postgresql_retrieval_does_not_flush_or_break_outer_transaction(
    postgres_harness: URL,
) -> None:
    """A caller's pending ORM write and transaction remain untouched by search."""

    ids = _run(_seed(postgres_harness))

    async def exercise() -> None:
        engine = create_async_engine(postgres_harness, pool_pre_ping=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        pending_id = uuid4()
        async with sessions() as session:
            async with session.begin():
                pending = Tenant(
                    id=pending_id,
                    slug=f"pending-{pending_id.hex}",
                    name="Pending outer transaction tenant",
                )
                session.add(pending)
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
                assert result.outcome is RetrievalOutcome.FOUND
                assert pending in session.new
                await session.flush()
            assert await session.scalar(
                text("SELECT slug FROM tenants WHERE id = :id"), {"id": pending_id}
            ) == f"pending-{pending_id.hex}"
        await engine.dispose()

    _run(exercise())


def test_postgresql_knowledge_active_version_is_concurrent_unique(
    postgres_harness: URL,
) -> None:
    """Concurrent appenders cannot commit two active versions for one source."""

    ids = _run(_seed(postgres_harness))

    async def exercise() -> None:
        engine = create_async_engine(postgres_harness, pool_pre_ping=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        first = sessions()
        second = sessions()
        try:
            await first.execute(
                text(
                    "UPDATE knowledge_source_versions SET status = 'superseded', "
                    "valid_until = :valid_until WHERE id = :id"
                ),
                {"id": ids["version_a"], "valid_until": NOW},
            )
            await first.commit()
            await first.begin()
            await second.begin()
            first_version, second_version = uuid4(), uuid4()
            empty_digest = canonical_knowledge_version_digest(())
            insert = text(
                "INSERT INTO knowledge_source_versions "
                "(id, source_id, tenant_id, version_no, status, valid_from, "
                "content_sha256, supersedes_version_id) VALUES (:id, :source, :tenant, "
                "2, 'active', :now, :digest, :supersedes)"
            )
            params = {
                "source": ids["source_a"],
                "tenant": ids["tenant_a"],
                "now": NOW,
                "digest": empty_digest,
                "supersedes": ids["version_a"],
            }
            await first.execute(insert, {**params, "id": first_version})
            blocked = asyncio.create_task(second.execute(insert, {**params, "id": second_version}))
            await asyncio.sleep(0)
            await first.commit()
            with pytest.raises(DBAPIError):
                await blocked
            await second.rollback()
            assert (
                await first.scalar(
                    text(
                        "SELECT count(*) FROM knowledge_source_versions "
                        "WHERE source_id = :source AND tenant_id = :tenant "
                        "AND status = 'active'"
                    ),
                    {"source": ids["source_a"], "tenant": ids["tenant_a"]},
                )
                == 1
            )
        finally:
            await first.close()
            await second.close()
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


def test_postgresql_knowledge_digest_and_version_chain_guards(postgres_harness: URL) -> None:
    """Prove passage/version digests and append-only version lifecycle rules."""

    ids = _run(_seed(postgres_harness))

    async def exercise() -> None:
        engine = create_async_engine(postgres_harness, pool_pre_ping=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session:
            with pytest.raises(DBAPIError):
                await session.execute(
                    text(
                        "INSERT INTO knowledge_chunks "
                        "(id, source_version_id, tenant_id, ordinal, locator, passage, "
                        "content_sha256) VALUES (:id, :version, :tenant, 99, "
                        "'digest#wrong', 'Exact UTF-8 passage', :digest)"
                    ),
                    {
                        "id": uuid4(),
                        "version": ids["version_a"],
                        "tenant": ids["tenant_a"],
                        "digest": hashlib.sha256(b"different").hexdigest(),
                    },
                )
            await session.rollback()

            with pytest.raises(DBAPIError):
                await session.execute(
                    text(
                        "INSERT INTO knowledge_source_versions "
                        "(id, source_id, tenant_id, version_no, status, valid_from, "
                        "content_sha256) VALUES (:id, :source, :tenant, 2, 'active', "
                        ":now, :digest)"
                    ),
                    {
                        "id": uuid4(),
                        "source": ids["source_a"],
                        "tenant": ids["tenant_a"],
                        "now": NOW,
                        "digest": "0" * 64,
                    },
                )
            await session.rollback()

            terminal_source = uuid4()
            await session.execute(
                text(
                    "INSERT INTO knowledge_sources "
                    "(id, tenant_id, source_key, title, provenance_uri, source_kind) "
                    "VALUES (:id, :tenant, 'terminal-fixture', 'Terminal fixture', "
                    "'fixture://terminal', 'fixture')"
                ),
                {"id": terminal_source, "tenant": ids["tenant_a"]},
            )
            await session.commit()
            with pytest.raises(DBAPIError):
                await session.execute(
                    text(
                        "INSERT INTO knowledge_source_versions "
                        "(id, source_id, tenant_id, version_no, status, valid_from, "
                        "valid_until, content_sha256) VALUES (:id, :source, :tenant, "
                        "1, 'withdrawn', :now, :valid_until, :digest)"
                    ),
                    {
                        "id": uuid4(),
                        "source": terminal_source,
                        "tenant": ids["tenant_a"],
                        "now": NOW - timedelta(days=1),
                        "valid_until": NOW,
                        "digest": canonical_knowledge_version_digest(()),
                    },
                )
            await session.rollback()

            await session.execute(
                text(
                    "UPDATE knowledge_source_versions SET status = 'superseded', "
                    "valid_until = :valid_until WHERE id = :id"
                ),
                {"id": ids["version_a"], "valid_until": NOW},
            )
            await session.commit()

            version_two = uuid4()
            with pytest.raises(DBAPIError):
                await session.execute(
                    text(
                        "INSERT INTO knowledge_source_versions "
                        "(id, source_id, tenant_id, version_no, status, valid_from, "
                        "content_sha256, supersedes_version_id) VALUES (:id, :source, "
                        ":tenant, 2, 'active', :now, :digest, :supersedes)"
                    ),
                    {
                        "id": version_two,
                        "source": ids["source_a"],
                        "tenant": ids["tenant_a"],
                        "now": NOW,
                        "digest": "0" * 64,
                        "supersedes": ids["version_a"],
                    },
                )
                await session.commit()
            await session.rollback()

            passage = "Exact UTF-8 passage ✓"
            version_digest = canonical_knowledge_version_digest(
                ((0, "digest#exact", passage),)
            )
            await session.execute(
                text(
                    "INSERT INTO knowledge_source_versions "
                    "(id, source_id, tenant_id, version_no, status, valid_from, "
                    "content_sha256, supersedes_version_id) VALUES (:id, :source, :tenant, "
                    "2, 'active', :now, :digest, :supersedes)"
                ),
                {
                    "id": version_two,
                    "source": ids["source_a"],
                    "tenant": ids["tenant_a"],
                    "now": NOW,
                    "digest": version_digest,
                    "supersedes": ids["version_a"],
                },
            )
            await session.execute(
                text(
                    "INSERT INTO knowledge_chunks "
                    "(id, source_version_id, tenant_id, ordinal, locator, passage, "
                    "content_sha256) VALUES (:id, :version, :tenant, 0, "
                    "'digest#exact', :passage, :digest)"
                ),
                {
                    "id": uuid4(),
                    "version": version_two,
                    "tenant": ids["tenant_a"],
                    "passage": passage,
                    "digest": hashlib.sha256(passage.encode("utf-8")).hexdigest(),
                },
            )
            await session.execute(
                text(
                    "INSERT INTO knowledge_version_purposes "
                    "(source_version_id, tenant_id, purpose) VALUES (:version, :tenant, "
                    "'support_assistance')"
                ),
                {"version": version_two, "tenant": ids["tenant_a"]},
            )
            await session.commit()
            assert (
                await session.scalar(
                    text(
                        "SELECT content_sha256 FROM knowledge_source_versions WHERE id = :id"
                    ),
                    {"id": version_two},
                )
                == version_digest
            )
        await engine.dispose()

    _run(exercise())


def test_postgresql_retrieval_equal_score_ties_respect_top_k(
    postgres_harness: URL,
) -> None:
    """The UUID/ordinal tie-breakers remain stable while LIMIT is enforced."""

    ids = _run(_seed(postgres_harness))

    async def exercise() -> None:
        engine = create_async_engine(postgres_harness, pool_pre_ping=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        source_id, version_id = uuid4(), uuid4()
        passages = ("Identical recovery phrase for deterministic ranking.",) * 3
        locators = tuple(f"tie#{index}" for index in range(3))
        version_digest = canonical_knowledge_version_digest(
            tuple((index, locators[index], passages[index]) for index in range(3))
        )
        async with sessions() as session:
            await session.execute(
                text(
                    "INSERT INTO knowledge_sources "
                    "(id, tenant_id, source_key, title, provenance_uri, source_kind) "
                    "VALUES (:id, :tenant, 'tie-fixture', 'Tie fixture', "
                    "'fixture://tie', 'fixture')"
                ),
                {"id": source_id, "tenant": ids["tenant_a"]},
            )
            await session.execute(
                text(
                    "INSERT INTO knowledge_source_versions "
                    "(id, source_id, tenant_id, version_no, status, valid_from, "
                    "content_sha256) VALUES (:id, :source, :tenant, 1, 'active', :now, :digest)"
                ),
                {
                    "id": version_id,
                    "source": source_id,
                    "tenant": ids["tenant_a"],
                    "now": NOW - timedelta(days=1),
                    "digest": version_digest,
                },
            )
            for index, (locator, passage) in enumerate(zip(locators, passages, strict=True)):
                await session.execute(
                    text(
                        "INSERT INTO knowledge_chunks "
                        "(id, source_version_id, tenant_id, ordinal, locator, passage, "
                        "content_sha256) VALUES (:id, :version, :tenant, :ordinal, "
                        ":locator, :passage, :digest)"
                    ),
                    {
                        "id": uuid4(),
                        "version": version_id,
                        "tenant": ids["tenant_a"],
                        "ordinal": index,
                        "locator": locator,
                        "passage": passage,
                        "digest": hashlib.sha256(passage.encode("utf-8")).hexdigest(),
                    },
                )
            await session.execute(
                text(
                    "INSERT INTO knowledge_version_purposes "
                    "(source_version_id, tenant_id, purpose) VALUES (:version, :tenant, "
                    "'support_assistance')"
                ),
                {"version": version_id, "tenant": ids["tenant_a"]},
            )
            await session.commit()

            query = KnowledgeQuery(
                access=KnowledgeAccessContext(
                    tenant_id=ids["tenant_a"],
                    purpose=IntelligencePurpose.SUPPORT_ASSISTANCE,
                ),
                question="identical recovery phrase",
                min_rank_score=PINNED_MIN_RANK_SCORE,
                top_k=2,
            )
            first = await PostgresKnowledgeRepository(session).search(query)
            second = await PostgresKnowledgeRepository(session).search(query)
            assert first.outcome is RetrievalOutcome.FOUND
            assert len(first.chunks) == 2
            assert first.chunks == second.chunks
            assert [chunk.locator for chunk in first.chunks] == ["tie#0", "tie#1"]
        await engine.dispose()

    _run(exercise())


def test_postgresql_gold_set_runner_enforces_context_acl_and_withdrawal(
    postgres_harness: URL,
) -> None:
    """Run the complete gold fixture through PostgreSQL and typed evaluation."""

    ids = _run(_seed(postgres_harness))
    cases = load_gold_set(ROOT / "tests" / "fixtures" / "knowledge_gold_set.jsonl")

    async def exercise() -> None:
        engine = create_async_engine(postgres_harness, pool_pre_ping=True)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session:
            repository = PostgresKnowledgeRepository(session)
            predictions: dict[str, GoldPrediction] = {}
            for case in cases:
                access = gold_access_context(case)
                snapshot_id = (
                    ids["withdrawn_version"] if case.case_id == "ks-0007" else None
                )
                result = await repository.search(
                    KnowledgeQuery(
                        access=access,
                        question=case.question,
                        min_rank_score=PINNED_MIN_RANK_SCORE,
                        top_k=10,
                        snapshot_id=snapshot_id,
                    )
                )
                predictions[case.case_id] = GoldPrediction(result=result, access=access)

            evaluation = evaluate_gold_set(cases, predictions)
            assert evaluation.answerable_cases == 5
            assert evaluation.abstention_cases == 3
            assert evaluation.recall_at_k == 1.0
            assert evaluation.abstention_accuracy == 1.0
            assert evaluation.leakage_count == 0

            withdrawn = await repository.search(
                KnowledgeQuery(
                    access=KnowledgeAccessContext(
                        tenant_id=ids["tenant_a"],
                        purpose=IntelligencePurpose.SUPPORT_ASSISTANCE,
                    ),
                    question="withdrawn policy",
                    min_rank_score=PINNED_MIN_RANK_SCORE,
                    snapshot_id=ids["withdrawn_version"],
                )
            )
            assert withdrawn.outcome is RetrievalOutcome.NO_AUTHORIZED_EVIDENCE
            assert not withdrawn.chunks

            acl_denied = await repository.search(
                KnowledgeQuery(
                    access=KnowledgeAccessContext(
                        tenant_id=ids["tenant_a"],
                        purpose=IntelligencePurpose.SUPPORT_ASSISTANCE,
                        acl_subject_ids=(ids["acl_subject_unlisted"],),
                    ),
                    question="support change rubric",
                    min_rank_score=PINNED_MIN_RANK_SCORE,
                )
            )
            assert acl_denied.outcome is RetrievalOutcome.BELOW_THRESHOLD
            assert not acl_denied.chunks
        await engine.dispose()

    _run(exercise())
