"""PostgreSQL proof for the reviewed staging seed and course enrollment seam."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Coroutine, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from ac_platform.application.settings import Settings
from ac_platform.catalog.models import (
    Activity,
    CatalogScope,
    Module,
    ProgramVersion,
    ProgramVersionStatus,
)
from ac_platform.enrollment.models import Enrollment, EnrollmentEligibilityFact
from ac_platform.enrollment.services import AsyncEnrollmentApplication, FreeEnrollmentCommand
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.http.course import install_course_http
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.seed.application import SeedApplicationError, StagingSeedApplication
from ac_platform.seed.contract import load_seed
from ac_platform.tenancy.models import Membership, Tenant

FIXTURE = Path(__file__).parents[1] / "fixtures" / "free_course_staging_test_fixture.json"
NOW = datetime(2026, 8, 30, 12, tzinfo=UTC)
TEST_RELEASE = "0000000000000000000000000000000000000000"


def _run_async[T](coroutine: Coroutine[Any, Any, T]) -> T:
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            return runner.run(coroutine)
    return asyncio.run(coroutine)


def _postgres_url() -> URL:
    seed_database_url = os.getenv("AC_STAGING_SEED_POSTGRES_TEST_URL")
    test_database_url = os.getenv("AC_TEST_DATABASE_URL")
    raw = seed_database_url or test_database_url
    if not raw:
        if seed_database_url is not None or test_database_url is not None:
            pytest.fail("configured staging seed PostgreSQL URL is empty", pytrace=False)
        if os.getenv("AC_REQUIRE_STAGING_SEED_POSTGRES_TEST") == "1":
            pytest.fail("required staging seed PostgreSQL URL is not configured", pytrace=False)
        pytest.skip("staging seed PostgreSQL URL is not configured")
    try:
        url = make_url(raw)
    except ArgumentError:
        pytest.fail("configured staging seed PostgreSQL URL is malformed", pytrace=False)
    if url.get_backend_name() != "postgresql":
        pytest.fail("configured staging seed integration URL is not PostgreSQL", pytrace=False)
    if (
        url.host not in {None, "127.0.0.1", "localhost", "::1"}
        and os.getenv("AC_ALLOW_REMOTE_TEST_DATABASE") != "1"
    ):
        pytest.fail(
            "configured staging seed PostgreSQL URL is not an approved target", pytrace=False
        )
    return url.set(drivername="postgresql+psycopg")


def test_configured_seed_database_cannot_skip_on_wrong_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AC_STAGING_SEED_POSTGRES_TEST_URL", "sqlite+pysqlite:///:memory:")

    with pytest.raises(pytest.fail.Exception, match="not PostgreSQL"):
        _postgres_url()


def test_configured_seed_database_cannot_skip_on_empty_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AC_STAGING_SEED_POSTGRES_TEST_URL", raising=False)
    monkeypatch.setenv("AC_TEST_DATABASE_URL", "")

    with pytest.raises(pytest.fail.Exception, match="is empty"):
        _postgres_url()


def test_required_seed_database_cannot_skip_when_url_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AC_STAGING_SEED_POSTGRES_TEST_URL", raising=False)
    monkeypatch.delenv("AC_TEST_DATABASE_URL", raising=False)
    monkeypatch.setenv("AC_REQUIRE_STAGING_SEED_POSTGRES_TEST", "1")

    with pytest.raises(pytest.fail.Exception, match="is not configured"):
        _postgres_url()


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[URL]:
    root = Path(__file__).parents[2]
    base_url = _postgres_url()
    schema = f"seed_{uuid4().hex}"
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
            pytest.fail("fresh PostgreSQL migration failed")
        yield schema_url
    finally:
        if created:
            with admin_engine.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True))
        admin_engine.dispose()


def _settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+psycopg://unused:unused@localhost/unused",
        database_migrator_url="postgresql+psycopg://unused:unused@localhost/unused",
        session_token_pepper="seed-test-session-pepper-long-enough",  # noqa: S106
        oauth_transaction_secret="seed-test-oauth-secret-long-enough",  # noqa: S106
        public_app_url="https://app.authorityclosers.test",
        admin_app_url="https://admin.authorityclosers.test",
        api_url="https://api.authorityclosers.test",
    )


def test_reviewed_seed_is_idempotent_enrollable_and_visible(
    postgres_harness: URL, tmp_path: Path
) -> None:
    engine = create_engine(postgres_harness, pool_pre_ping=True)
    learner_id = uuid4()
    tenant_id = uuid4()
    global_actor_id = uuid4()
    with Session(engine) as database:
        database.add_all(
            [
                Person(id=learner_id, email=f"learner-{learner_id.hex}@example.test"),
                Person(id=global_actor_id, email=f"seed-{global_actor_id.hex}@example.test"),
                Tenant(id=tenant_id, slug=f"seed-tenant-{tenant_id.hex}", name="Seed test tenant"),
            ]
        )
        database.flush()
        database.add_all(
            [
                Membership(tenant_id=tenant_id, person_id=learner_id, role="learner"),
                Membership(tenant_id=tenant_id, person_id=global_actor_id, role="admin"),
            ]
        )
        database.commit()

    async def scenario() -> tuple[UUID, UUID, UUID, int, int]:
        async_engine = create_async_engine(postgres_harness, pool_pre_ping=True)
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        seed = load_seed(FIXTURE, environment="test", expected_release_id=TEST_RELEASE)
        actor = ActorContext(
            person_id=global_actor_id,
            session_id=uuid4(),
            tenant_id=None,
            permissions=frozenset(),
        )
        try:
            with pytest.raises(SeedApplicationError, match="expected runtime release ID"):
                async with sessions() as release_session:
                    await StagingSeedApplication(
                        release_session,
                        environment="test",
                        expected_release_id="1" * 40,
                        clock=lambda: NOW,
                    ).apply(seed, actor=actor)

            async with sessions() as first_session, sessions() as second_session:
                first, second = await asyncio.gather(
                    StagingSeedApplication(
                        first_session,
                        environment="test",
                        expected_release_id=TEST_RELEASE,
                        clock=lambda: NOW,
                    ).apply(seed, actor=actor),
                    StagingSeedApplication(
                        second_session,
                        environment="test",
                        expected_release_id=TEST_RELEASE,
                        clock=lambda: NOW,
                    ).apply(seed, actor=actor),
                )
            assert {first.status, second.status} == {"published", "already_applied"}
            assert first.program_version_id == second.program_version_id
            for result in (first, second):
                assert result.content_digest == seed.content_digest
                assert result.release_id == seed.release_id
                assert result.content_source_ref == seed.source_ref
                assert result.content_reviewed_by == seed.reviewed_by
                assert result.content_reviewed_at == seed.reviewed_at
                assert result.seed_kind == seed.seed_kind

            unauthorized_actor = ActorContext(
                person_id=learner_id,
                session_id=uuid4(),
                tenant_id=None,
                permissions=frozenset({"catalog_write", "catalog_publish"}),
            )
            async with sessions() as unauthorized_session:
                with pytest.raises(SeedApplicationError, match="active admin or owner membership"):
                    await StagingSeedApplication(
                        unauthorized_session,
                        environment="test",
                        expected_release_id=TEST_RELEASE,
                        clock=lambda: NOW,
                    ).apply(seed, actor=unauthorized_actor)

            tampered_payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
            tampered_payload["content"]["source_ref"] = "tampered-source-ref"
            tampered_path = tmp_path / "tampered-provenance.json"
            tampered_path.write_text(json.dumps(tampered_payload), encoding="utf-8")
            tampered_seed = load_seed(
                tampered_path,
                environment="test",
                expected_release_id=TEST_RELEASE,
            )
            async with sessions() as tampered_session:
                with pytest.raises(SeedApplicationError, match="replay provenance"):
                    await StagingSeedApplication(
                        tampered_session,
                        environment="test",
                        expected_release_id=TEST_RELEASE,
                        clock=lambda: NOW,
                    ).apply(tampered_seed, actor=actor)

            async with sessions() as database:
                async with database.begin():
                    version = await database.get(ProgramVersion, first.program_version_id)
                    assert version is not None
                    assert version.content_digest == seed.content_digest
                    assert version.content_source_ref == seed.source_ref
                    assert version.content_reviewed_by == seed.reviewed_by
                    assert version.content_reviewed_at == seed.reviewed_at
                    assert version.release_id == seed.release_id
                    assert version.content_seed_kind == seed.seed_kind
                    activities = list(
                        (
                            await database.scalars(
                                select(Activity)
                                .join(Module, Module.id == Activity.module_id)
                                .where(Activity.program_version_id == version.id)
                                .order_by(Module.position, Activity.position)
                            )
                        ).all()
                    )
                    assert [activity.prompt for activity in activities] == [
                        activity.prompt for module in seed.modules for activity in module.activities
                    ]
                    assert all(activity.prompt for activity in activities)
                    database.add(
                        EnrollmentEligibilityFact(
                            id=uuid4(),
                            tenant_id=tenant_id,
                            person_id=learner_id,
                            program_version_id=version.id,
                            program_id=version.program_id,
                            program_scope=CatalogScope.GLOBAL.value,
                            program_tenant_id=None,
                            program_owner_key=version.owner_key,
                            age_gate_passed=True,
                            eligibility_passed=True,
                            prerequisites_satisfied=True,
                            policy_version="seed-test-v1",
                            evidence={"source": "seed-test"},
                            evaluated_at=NOW,
                        )
                    )
                async with database.begin():
                    enrollment_actor = ActorContext(
                        person_id=learner_id,
                        session_id=uuid4(),
                        tenant_id=tenant_id,
                    )
                    enrollment = await AsyncEnrollmentApplication(
                        database, clock=lambda: NOW
                    ).enroll_free(
                        FreeEnrollmentCommand(
                            actor_person_id=learner_id,
                            subject_person_id=learner_id,
                            tenant_id=tenant_id,
                            program_version_id=first.program_version_id,
                            idempotency_key="seed-enrollment",
                        ),
                        actor=enrollment_actor,
                    )
                assert enrollment.created is True

            changed_payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
            changed_payload["modules"][0]["title"] = "Mutated reviewed fixture module"
            changed_path = tmp_path / "changed-seed.json"
            changed_path.write_text(json.dumps(changed_payload), encoding="utf-8")
            changed_seed = load_seed(
                changed_path,
                environment="test",
                expected_release_id=TEST_RELEASE,
            )
            async with sessions() as changed_session:
                changed = await StagingSeedApplication(
                    changed_session,
                    environment="test",
                    expected_release_id=TEST_RELEASE,
                    clock=lambda: NOW,
                ).apply(changed_seed, actor=actor)
                async with changed_session.begin():
                    prior = await changed_session.get(ProgramVersion, first.program_version_id)
                    assert prior is not None
                    assert prior.status == ProgramVersionStatus.SUPERSEDED.value

            async with sessions() as database:
                version_count = int(
                    await database.scalar(select(func.count()).select_from(ProgramVersion)) or 0
                )
                enrollment_count = int(
                    await database.scalar(select(func.count()).select_from(Enrollment)) or 0
                )

            application = FastAPI()

            async def unused_actor(_request: Request) -> AsyncIterator[AuthenticatedTransaction]:
                raise AssertionError("anonymous catalog read unexpectedly resolved an actor")
                yield  # pragma: no cover

            install_course_http(
                application,
                settings=_settings(),
                sessions=sessions,
                require_actor=unused_actor,
            )
            transport = httpx.ASGITransport(app=application)
            async with httpx.AsyncClient(
                transport=transport, base_url="https://api.authorityclosers.test"
            ) as client:
                response = await client.get("/v1/programs")
            assert response.status_code == 200
            assert response.json()["items"][0]["slug"] == seed.slug
            assert response.json()["items"][0]["program_version_id"] == str(
                changed.program_version_id
            )
            return (
                first.program_version_id,
                second.program_version_id,
                changed.program_version_id,
                version_count,
                enrollment_count,
            )
        finally:
            await async_engine.dispose()

    (
        first_version_id,
        second_version_id,
        changed_version_id,
        version_count,
        enrollment_count,
    ) = _run_async(scenario())
    assert first_version_id == second_version_id
    assert changed_version_id != first_version_id
    assert version_count == 2
    assert enrollment_count == 1
    engine.dispose()
