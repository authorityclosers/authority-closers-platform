"""Real PostgreSQL proofs for catalog publication lock ordering and digest integrity."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, event, func, select, text, update
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from ac_platform.catalog.models import (
    GLOBAL_CATALOG_OWNER_KEY,
    Activity,
    ActivityKind,
    CatalogScope,
    Module,
    ModulePrerequisite,
    Program,
    ProgramVersion,
    ProgramVersionStatus,
)
from ac_platform.catalog.services import (
    CatalogConflictError,
    CatalogContentDigestMismatchError,
    CatalogService,
    PublishedVersionImmutableError,
    SqlAlchemyCatalogStore,
)

NOW = datetime(2026, 8, 30, 12, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class _CatalogSeed:
    program_id: UUID
    version_id: UUID
    module_id: UUID
    activity_id: UUID
    reviewed_digest: str


def _postgres_url() -> URL:
    raw = os.getenv("AC_CATALOG_POSTGRES_TEST_URL") or os.getenv("AC_TEST_DATABASE_URL")
    if not raw:
        if os.getenv("AC_REQUIRE_CATALOG_POSTGRES_TEST") == "1":
            pytest.fail("catalog PostgreSQL URL is required but not configured")
        pytest.skip("catalog PostgreSQL URL is not configured")
    url = make_url(raw)
    if url.get_backend_name() != "postgresql":
        pytest.fail("catalog publication integration requires PostgreSQL")
    if (
        url.host not in {None, "127.0.0.1", "localhost", "::1"}
        and os.getenv("AC_ALLOW_REMOTE_TEST_DATABASE") != "1"
    ):
        if os.getenv("AC_REQUIRE_CATALOG_POSTGRES_TEST") == "1":
            pytest.fail("required catalog PostgreSQL test refused a non-local database")
        pytest.skip("refusing to mutate a non-local PostgreSQL database")
    return url.set(drivername="postgresql+psycopg")


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    root = Path(__file__).parents[2]
    base_url = _postgres_url()
    schema = f"catalog_publication_{uuid4().hex}"
    admin_engine = create_engine(base_url, pool_pre_ping=True)
    schema_engine: Engine | None = None
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
                        str(root / "packages" / "python"),
                        environment.get("PYTHONPATH", ""),
                    )
                    if part
                ),
            }
        )
        migration = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if migration.returncode != 0:
            pytest.fail(
                "fresh PostgreSQL migration failed\n"
                f"stdout:\n{migration.stdout}\n"
                f"stderr:\n{migration.stderr}"
            )
        schema_engine = create_engine(schema_url, pool_size=8, max_overflow=0)
        yield schema_engine
    finally:
        if schema_engine is not None:
            schema_engine.dispose()
        if created:
            with admin_engine.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True))
        admin_engine.dispose()


def _transaction_timeouts(database: Session) -> None:
    database.execute(text("SET LOCAL lock_timeout = '5s'"))
    database.execute(text("SET LOCAL statement_timeout = '10s'"))


def _seed_reviewed_draft(engine: Engine) -> _CatalogSeed:
    program_id = uuid4()
    version_id = uuid4()
    module_id = uuid4()
    activity_id = uuid4()
    with Session(engine) as database:
        database.add(
            Program(
                id=program_id,
                scope=CatalogScope.GLOBAL.value,
                owner_key=GLOBAL_CATALOG_OWNER_KEY,
                tenant_id=None,
                slug=f"publication-race-{uuid4().hex}",
                title="Publication race fixture",
            )
        )
        database.flush()
        version = ProgramVersion(
            id=version_id,
            program_id=program_id,
            scope=CatalogScope.GLOBAL.value,
            owner_key=GLOBAL_CATALOG_OWNER_KEY,
            tenant_id=None,
            version_number=1,
            status=ProgramVersionStatus.DRAFT.value,
        )
        database.add(version)
        database.flush()
        database.add(
            Module(
                id=module_id,
                program_version_id=version_id,
                program_id=program_id,
                scope=CatalogScope.GLOBAL.value,
                owner_key=GLOBAL_CATALOG_OWNER_KEY,
                tenant_id=None,
                position=1,
                title="Reviewed module",
            )
        )
        database.flush()
        database.add(
            Activity(
                id=activity_id,
                module_id=module_id,
                program_version_id=version_id,
                program_id=program_id,
                scope=CatalogScope.GLOBAL.value,
                owner_key=GLOBAL_CATALOG_OWNER_KEY,
                tenant_id=None,
                position=1,
                kind=ActivityKind.REFLECTION.value,
                title="Reviewed activity",
                prompt="Original reviewed prompt.",
                is_required=True,
            )
        )
        database.flush()
        store = SqlAlchemyCatalogStore(database)
        service = CatalogService(store, clock=lambda: NOW)
        snapshot = store.get_version(version_id)
        assert snapshot is not None
        digest = service._canonical_content_digest(snapshot)  # noqa: SLF001
        version.content_digest = digest
        version.content_source_ref = __file__
        version.content_reviewed_by = "postgres-race-reviewer@example.test"
        version.content_reviewed_at = NOW
        version.release_id = "c" * 40
        version.content_seed_kind = "reviewed"
        database.flush()
        assert database.scalar(select(func.ac_catalog_content_digest(version_id))) == digest
        database.commit()
    return _CatalogSeed(program_id, version_id, module_id, activity_id, digest)


def _publish(engine: Engine, seed: _CatalogSeed) -> str:
    with Session(engine) as database:
        _transaction_timeouts(database)
        published = CatalogService(
            SqlAlchemyCatalogStore(database),
            clock=lambda: NOW,
        ).publish_version(seed.version_id, tenant_id=None, now=NOW)
        database.commit()
        assert published.content_digest is not None
        return published.content_digest


def test_publication_wins_and_concurrent_prompt_update_is_rejected(
    postgres_engine: Engine,
) -> None:
    seed = _seed_reviewed_draft(postgres_engine)
    publication_locked = Event()
    update_attempted = Event()

    def publish_first() -> str:
        with Session(postgres_engine) as database:
            _transaction_timeouts(database)
            database.scalar(select(Program).where(Program.id == seed.program_id).with_for_update())
            database.scalar(
                select(ProgramVersion).where(ProgramVersion.id == seed.version_id).with_for_update()
            )
            publication_locked.set()
            assert update_attempted.wait(timeout=5)
            published = CatalogService(
                SqlAlchemyCatalogStore(database),
                clock=lambda: NOW,
            ).publish_version(seed.version_id, tenant_id=None, now=NOW)
            database.commit()
            assert published.content_digest is not None
            return published.content_digest

    def update_prompt() -> str:
        assert publication_locked.wait(timeout=5)
        with Session(postgres_engine) as database:
            _transaction_timeouts(database)
            update_attempted.set()
            try:
                database.execute(
                    update(Activity)
                    .where(Activity.id == seed.activity_id)
                    .values(prompt="Unreviewed concurrent prompt.")
                )
                database.commit()
            except DBAPIError:
                database.rollback()
                return "rejected"
            return "committed"

    with ThreadPoolExecutor(max_workers=2) as pool:
        publish_future = pool.submit(publish_first)
        update_future = pool.submit(update_prompt)
        assert publish_future.result(timeout=15) == seed.reviewed_digest
        assert update_future.result(timeout=15) == "rejected"

    with Session(postgres_engine) as database:
        version = database.get(ProgramVersion, seed.version_id)
        activity = database.get(Activity, seed.activity_id)
        assert version is not None and activity is not None
        assert version.status == ProgramVersionStatus.PUBLISHED.value
        assert version.content_digest == seed.reviewed_digest
        assert activity.prompt == "Original reviewed prompt."
        assert (
            database.scalar(select(func.ac_catalog_content_digest(seed.version_id)))
            == seed.reviewed_digest
        )


@pytest.mark.parametrize("covered_child", ["activity_prompt", "module_title"])
def test_committed_child_change_invalidates_review_before_publication(
    postgres_engine: Engine,
    covered_child: str,
) -> None:
    seed = _seed_reviewed_draft(postgres_engine)
    mutation_ready = Event()
    publication_attempted = Event()

    def mutate_first() -> None:
        with Session(postgres_engine) as database:
            _transaction_timeouts(database)
            statement = (
                update(Activity)
                .where(Activity.id == seed.activity_id)
                .values(prompt="Committed prompt change.")
                if covered_child == "activity_prompt"
                else update(Module)
                .where(Module.id == seed.module_id)
                .values(title="Committed module title change")
            )
            database.execute(statement)
            mutation_ready.set()
            assert publication_attempted.wait(timeout=5)
            database.commit()

    def publish_second() -> str:
        assert mutation_ready.wait(timeout=5)
        publication_attempted.set()
        try:
            _publish(postgres_engine, seed)
        except CatalogContentDigestMismatchError:
            return "stale-digest-rejected"
        return "published"

    with ThreadPoolExecutor(max_workers=2) as pool:
        mutation_future = pool.submit(mutate_first)
        publication_future = pool.submit(publish_second)
        mutation_future.result(timeout=15)
        assert publication_future.result(timeout=15) == "stale-digest-rejected"

    with Session(postgres_engine) as database:
        version = database.get(ProgramVersion, seed.version_id)
        assert version is not None
        assert version.status == ProgramVersionStatus.DRAFT.value
        assert version.content_digest == seed.reviewed_digest
        assert (
            database.scalar(select(func.ac_catalog_content_digest(seed.version_id)))
            != seed.reviewed_digest
        )


@pytest.mark.parametrize("program_field", ["title", "slug"])
def test_committed_program_change_serializes_and_invalidates_publication(
    postgres_engine: Engine,
    program_field: str,
) -> None:
    seed = _seed_reviewed_draft(postgres_engine)
    mutation_ready = Event()
    publication_attempted = Event()

    def mutate_program_first() -> None:
        with Session(postgres_engine) as database:
            _transaction_timeouts(database)
            value = (
                "Committed program title change"
                if program_field == "title"
                else f"committed-program-slug-{uuid4().hex}"
            )
            database.execute(
                update(Program).where(Program.id == seed.program_id).values({program_field: value})
            )
            mutation_ready.set()
            assert publication_attempted.wait(timeout=5)
            database.commit()

    def publish_second() -> str:
        assert mutation_ready.wait(timeout=5)
        publication_attempted.set()
        try:
            _publish(postgres_engine, seed)
        except CatalogContentDigestMismatchError:
            return "stale-digest-rejected"
        return "published"

    with ThreadPoolExecutor(max_workers=2) as pool:
        mutation_future = pool.submit(mutate_program_first)
        publication_future = pool.submit(publish_second)
        mutation_future.result(timeout=15)
        assert publication_future.result(timeout=15) == "stale-digest-rejected"

    with Session(postgres_engine) as database:
        version = database.get(ProgramVersion, seed.version_id)
        assert version is not None
        assert version.status == ProgramVersionStatus.DRAFT.value
        assert (
            database.scalar(select(func.ac_catalog_content_digest(seed.version_id)))
            != seed.reviewed_digest
        )


@pytest.mark.parametrize("preloaded_change", ["program", "module", "activity"])
def test_publication_refreshes_preloaded_digest_rows_under_the_parent_lock(
    postgres_engine: Engine,
    preloaded_change: str,
) -> None:
    seed = _seed_reviewed_draft(postgres_engine)
    with Session(postgres_engine) as publisher:
        _transaction_timeouts(publisher)
        assert publisher.get(Program, seed.program_id) is not None
        assert publisher.get(Module, seed.module_id) is not None
        assert publisher.get(Activity, seed.activity_id) is not None

        with Session(postgres_engine) as mutator:
            _transaction_timeouts(mutator)
            if preloaded_change == "program":
                mutator.execute(
                    update(Program)
                    .where(Program.id == seed.program_id)
                    .values(title="Committed after the publisher preloaded its identity map")
                )
            elif preloaded_change == "module":
                mutator.execute(
                    update(Module)
                    .where(Module.id == seed.module_id)
                    .values(title="Committed after the publisher preloaded the module")
                )
            else:
                mutator.execute(
                    update(Activity)
                    .where(Activity.id == seed.activity_id)
                    .values(prompt="Committed after the publisher preloaded the activity.")
                )
            mutator.commit()

        with pytest.raises(CatalogContentDigestMismatchError):
            CatalogService(
                SqlAlchemyCatalogStore(publisher),
                clock=lambda: NOW,
            ).publish_version(seed.version_id, tenant_id=None, now=NOW)
        publisher.rollback()


def test_candidate_program_identity_move_is_detected_after_ordered_locks(
    postgres_engine: Engine,
) -> None:
    initial_program_id = uuid4()
    replacement_program_id = uuid4()
    version_id = uuid4()
    with Session(postgres_engine) as database:
        database.add_all(
            [
                Program(
                    id=initial_program_id,
                    scope=CatalogScope.GLOBAL.value,
                    owner_key=GLOBAL_CATALOG_OWNER_KEY,
                    tenant_id=None,
                    slug=f"identity-move-source-{uuid4().hex}",
                    title="Identity move source",
                ),
                Program(
                    id=replacement_program_id,
                    scope=CatalogScope.GLOBAL.value,
                    owner_key=GLOBAL_CATALOG_OWNER_KEY,
                    tenant_id=None,
                    slug=f"identity-move-target-{uuid4().hex}",
                    title="Identity move target",
                ),
            ]
        )
        database.flush()
        # No child rows reference this draft, so its program identity is still
        # database-mutable and the lock revalidation is the actual protection.
        database.add(
            ProgramVersion(
                id=version_id,
                program_id=initial_program_id,
                scope=CatalogScope.GLOBAL.value,
                owner_key=GLOBAL_CATALOG_OWNER_KEY,
                tenant_id=None,
                version_number=1,
                status=ProgramVersionStatus.DRAFT.value,
            )
        )
        database.commit()

    blocker = Session(postgres_engine)
    candidate_seen = Event()

    def observe_candidate_read(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        normalized = " ".join(statement.lower().split())
        if (
            "select program_versions.program_id" in normalized
            and "program_versions.id" in normalized
        ):
            candidate_seen.set()

    def publish_while_identity_moves() -> str:
        try:
            with Session(postgres_engine) as database:
                _transaction_timeouts(database)
                CatalogService(
                    SqlAlchemyCatalogStore(database),
                    clock=lambda: NOW,
                ).publish_version(version_id, tenant_id=None, now=NOW)
                database.commit()
        except CatalogConflictError as error:
            return str(error)
        return "published"

    event.listen(postgres_engine, "after_cursor_execute", observe_candidate_read)
    try:
        _transaction_timeouts(blocker)
        blocker.scalar(select(Program).where(Program.id == initial_program_id).with_for_update())
        with ThreadPoolExecutor(max_workers=1) as pool:
            publication_future = pool.submit(publish_while_identity_moves)
            assert candidate_seen.wait(timeout=5)
            with Session(postgres_engine) as mover:
                _transaction_timeouts(mover)
                mover.execute(
                    update(ProgramVersion)
                    .where(ProgramVersion.id == version_id)
                    .values(program_id=replacement_program_id)
                )
                mover.commit()
            blocker.commit()
            assert "identity changed" in publication_future.result(timeout=15)
    finally:
        if blocker.in_transaction():
            blocker.rollback()
        blocker.close()
        event.remove(postgres_engine, "after_cursor_execute", observe_candidate_read)

    with Session(postgres_engine) as database:
        moved = database.get(ProgramVersion, version_id)
        assert moved is not None
        assert moved.program_id == replacement_program_id
        assert moved.status == ProgramVersionStatus.DRAFT.value


def test_direct_sql_publication_without_complete_provenance_is_blocked(
    postgres_engine: Engine,
) -> None:
    seed = _seed_reviewed_draft(postgres_engine)
    with Session(postgres_engine) as database:
        version = database.get(ProgramVersion, seed.version_id)
        assert version is not None
        version.content_reviewed_by = None
        database.flush()
        with pytest.raises(DBAPIError, match="complete valid provenance"):
            database.execute(
                update(ProgramVersion)
                .where(ProgramVersion.id == seed.version_id)
                .values(status="published", published_at=NOW)
            )
            database.flush()
        database.rollback()

    with Session(postgres_engine) as database:
        version = database.get(ProgramVersion, seed.version_id)
        assert version is not None
        assert version.status == ProgramVersionStatus.DRAFT.value


def test_direct_sql_cannot_move_version_identity_during_publication(
    postgres_engine: Engine,
) -> None:
    seed = _seed_reviewed_draft(postgres_engine)
    replacement_program_id = uuid4()
    with Session(postgres_engine) as database:
        database.add(
            Program(
                id=replacement_program_id,
                scope=CatalogScope.GLOBAL.value,
                owner_key=GLOBAL_CATALOG_OWNER_KEY,
                tenant_id=None,
                slug=f"direct-publication-target-{uuid4().hex}",
                title="Direct publication target",
            )
        )
        database.commit()

    with Session(postgres_engine) as database:
        _transaction_timeouts(database)
        with pytest.raises(DBAPIError, match="identity cannot change during publication"):
            database.execute(
                update(ProgramVersion)
                .where(ProgramVersion.id == seed.version_id)
                .values(
                    program_id=replacement_program_id,
                    status=ProgramVersionStatus.PUBLISHED.value,
                    published_at=NOW,
                )
            )
            database.flush()
        database.rollback()

    with Session(postgres_engine) as database:
        version = database.get(ProgramVersion, seed.version_id)
        assert version is not None
        assert version.program_id == seed.program_id
        assert version.status == ProgramVersionStatus.DRAFT.value


def test_publication_lock_winner_makes_concurrent_authoring_fail_without_deadlock(
    postgres_engine: Engine,
) -> None:
    seed = _seed_reviewed_draft(postgres_engine)
    publication_locked = Event()
    authoring_attempted = Event()

    def publish_first() -> str:
        with Session(postgres_engine) as database:
            _transaction_timeouts(database)
            store = SqlAlchemyCatalogStore(database)
            store.lock_for_publication(seed.version_id)
            publication_locked.set()
            assert authoring_attempted.wait(timeout=5)
            published = CatalogService(store, clock=lambda: NOW).publish_version(
                seed.version_id,
                tenant_id=None,
                now=NOW,
            )
            database.commit()
            return published.status

    def author_second() -> str:
        assert publication_locked.wait(timeout=5)
        with Session(postgres_engine) as database:
            _transaction_timeouts(database)
            connection = database.connection()

            def observe_program_lock(
                _connection: object,
                _cursor: object,
                statement: str,
                _parameters: object,
                _context: object,
                _executemany: bool,
            ) -> None:
                normalized = " ".join(statement.lower().split())
                if " from programs " in normalized and " for update" in normalized:
                    authoring_attempted.set()

            event.listen(connection, "before_cursor_execute", observe_program_lock)
            try:
                try:
                    CatalogService(
                        SqlAlchemyCatalogStore(database),
                        clock=lambda: NOW,
                    ).add_activity(
                        seed.module_id,
                        tenant_id=None,
                        position=2,
                        kind=ActivityKind.REVIEW,
                        title="Must lose to publication",
                    )
                    database.commit()
                except PublishedVersionImmutableError:
                    database.rollback()
                    return "immutable-rejected"
                return "authored"
            finally:
                event.remove(connection, "before_cursor_execute", observe_program_lock)

    with ThreadPoolExecutor(max_workers=2) as pool:
        publication_future = pool.submit(publish_first)
        authoring_future = pool.submit(author_second)
        assert publication_future.result(timeout=15) == ProgramVersionStatus.PUBLISHED.value
        assert authoring_future.result(timeout=15) == "immutable-rejected"


def test_authoring_lock_winner_invalidates_concurrent_publication_without_deadlock(
    postgres_engine: Engine,
) -> None:
    seed = _seed_reviewed_draft(postgres_engine)
    authoring_locked = Event()
    publication_attempted = Event()

    def author_first() -> str:
        with Session(postgres_engine) as database:
            _transaction_timeouts(database)
            CatalogService(
                SqlAlchemyCatalogStore(database),
                clock=lambda: NOW,
            ).add_activity(
                seed.module_id,
                tenant_id=None,
                position=2,
                kind=ActivityKind.IMPROVE,
                title="Committed before publication",
                prompt="This changes the reviewed digest.",
            )
            authoring_locked.set()
            assert publication_attempted.wait(timeout=5)
            database.commit()
            return "authored"

    def publish_second() -> str:
        assert authoring_locked.wait(timeout=5)
        with Session(postgres_engine) as database:
            _transaction_timeouts(database)
            connection = database.connection()

            def observe_program_lock(
                _connection: object,
                _cursor: object,
                statement: str,
                _parameters: object,
                _context: object,
                _executemany: bool,
            ) -> None:
                normalized = " ".join(statement.lower().split())
                if " from programs " in normalized and " for update" in normalized:
                    publication_attempted.set()

            event.listen(connection, "before_cursor_execute", observe_program_lock)
            try:
                try:
                    CatalogService(
                        SqlAlchemyCatalogStore(database),
                        clock=lambda: NOW,
                    ).publish_version(seed.version_id, tenant_id=None, now=NOW)
                    database.commit()
                except CatalogContentDigestMismatchError:
                    database.rollback()
                    return "stale-digest-rejected"
                return "published"
            finally:
                event.remove(connection, "before_cursor_execute", observe_program_lock)

    with ThreadPoolExecutor(max_workers=2) as pool:
        authoring_future = pool.submit(author_first)
        publication_future = pool.submit(publish_second)
        assert authoring_future.result(timeout=15) == "authored"
        assert publication_future.result(timeout=15) == "stale-digest-rejected"


def _attach_reviewed_provenance(
    database: Session,
    service: CatalogService,
    version_id: UUID,
) -> str:
    store = SqlAlchemyCatalogStore(database)
    snapshot = store.get_version(version_id)
    assert snapshot is not None
    digest = service._canonical_content_digest(snapshot)  # noqa: SLF001
    version = database.get(ProgramVersion, version_id)
    assert version is not None
    version.content_digest = digest
    version.content_source_ref = __file__
    version.content_reviewed_by = "postgres-supersession-reviewer@example.test"
    version.content_reviewed_at = NOW
    version.release_id = "d" * 40
    version.content_seed_kind = "reviewed"
    database.flush()
    return digest


@pytest.mark.parametrize(
    ("current_version_id", "candidate_version_id"),
    [
        pytest.param(UUID(int=102), UUID(int=101), id="candidate-uuid-sorts-first"),
        pytest.param(UUID(int=201), UUID(int=202), id="current-uuid-sorts-first"),
    ],
)
def test_supersession_flush_order_is_independent_of_uuid_sorting(
    postgres_engine: Engine,
    current_version_id: UUID,
    candidate_version_id: UUID,
) -> None:
    with Session(postgres_engine) as database:
        _transaction_timeouts(database)
        store = SqlAlchemyCatalogStore(database)
        service = CatalogService(store, clock=lambda: NOW)
        program = service.create_program(
            tenant_id=None,
            scope=CatalogScope.GLOBAL,
            slug=f"uuid-order-{uuid4().hex}",
            title="UUID-independent supersession",
        )
        current = service.create_version(
            program.id,
            tenant_id=None,
            version_id=current_version_id,
            version_number=1,
        )
        service.add_module(
            current.id,
            tenant_id=None,
            position=1,
            title="Current content",
        )
        _attach_reviewed_provenance(database, service, current.id)
        service.publish_version(current.id, tenant_id=None, now=NOW)

        candidate = service.create_version(
            program.id,
            tenant_id=None,
            version_id=candidate_version_id,
            version_number=2,
            supersedes_version_id=current.id,
        )
        service.add_module(
            candidate.id,
            tenant_id=None,
            position=1,
            title="Candidate content",
        )
        _attach_reviewed_provenance(database, service, candidate.id)
        published = service.publish_version(candidate.id, tenant_id=None, now=NOW)
        database.commit()

    assert published.status == ProgramVersionStatus.PUBLISHED.value
    with Session(postgres_engine) as database:
        old = database.get(ProgramVersion, current_version_id)
        new = database.get(ProgramVersion, candidate_version_id)
        assert old is not None and new is not None
        assert old.status == ProgramVersionStatus.SUPERSEDED.value
        assert old.superseded_at is not None
        assert new.status == ProgramVersionStatus.PUBLISHED.value


def test_python_and_postgresql_digest_parity_for_unicode_delimiters_and_prompts(
    postgres_engine: Engine,
) -> None:
    with Session(postgres_engine) as database:
        store = SqlAlchemyCatalogStore(database)
        service = CatalogService(store, clock=lambda: NOW)
        program = service.create_program(
            tenant_id=None,
            scope=CatalogScope.GLOBAL,
            slug=f"digest-parity-{uuid4().hex}-नमस्ते",
            title="Élite 学習 | line one\nline two 🙂",
        )
        version = service.create_version(program.id, tenant_id=None)
        first = service.add_module(
            version.id,
            tenant_id=None,
            position=1,
            title="Foundation | α\nβ",
        )
        second = service.add_module(
            version.id,
            tenant_id=None,
            position=2,
            title="实践: second module",
        )
        service.add_activity(
            first.id,
            tenant_id=None,
            position=2,
            kind=ActivityKind.REVIEW,
            title="Delimiter | review:二",
            prompt="π|x\nline:🙂",
            is_required=False,
        )
        service.add_activity(
            first.id,
            tenant_id=None,
            position=1,
            kind=ActivityKind.REFLECTION,
            title="Null prompt activity",
            prompt=None,
        )
        service.add_activity(
            second.id,
            tenant_id=None,
            position=1,
            kind=ActivityKind.IMPLEMENTATION_CHALLENGE,
            title="Build — लागू करें",
            prompt="First\r\nSecond | 终",
        )
        edge = service.add_module_prerequisite(
            second.id,
            first.id,
            tenant_id=None,
        )
        assert isinstance(edge.id, UUID)
        snapshot = store.get_version(version.id)
        assert snapshot is not None
        python_digest = service._canonical_content_digest(snapshot)  # noqa: SLF001
        postgres_digest = database.scalar(select(func.ac_catalog_content_digest(version.id)))
        assert postgres_digest == python_digest
        assert database.get(ModulePrerequisite, edge.id) is not None
        database.rollback()
