"""Fresh PostgreSQL proof for the transaction-bound G1 learning HTTP adapter."""

from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Coroutine, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from ac_platform.application.settings import Settings
from ac_platform.catalog.models import (
    GLOBAL_CATALOG_OWNER_KEY,
    Activity,
    ActivityKind,
    CatalogScope,
    Module,
    Program,
    ProgramVersion,
    ProgramVersionStatus,
)
from ac_platform.enrollment.models import (
    CommandIdempotency,
    Enrollment,
    EnrollmentProvenance,
    Entitlement,
)
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.http.learning import install_learning_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.learning.models import ActivityDraft
from ac_platform.tenancy.models import Membership, Tenant

NOW = datetime(2026, 8, 30, 12, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class _Harness:
    engine: Engine
    schema_url: URL


@dataclass(frozen=True, slots=True)
class _Seed:
    tenant_id: UUID
    learner_id: UUID
    enrollment_id: UUID
    program_id: UUID
    version_id: UUID
    activity_id: UUID


def _run_async[T](coroutine: Coroutine[Any, Any, T]) -> T:
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            return runner.run(coroutine)
    return asyncio.run(coroutine)


def _postgres_url() -> URL:
    raw = os.getenv("AC_LEARNING_HTTP_POSTGRES_TEST_URL") or os.getenv("AC_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("learning HTTP PostgreSQL URL is not configured")
    url = make_url(raw)
    if url.get_backend_name() != "postgresql":
        pytest.skip("learning HTTP integration requires PostgreSQL")
    if (
        url.host not in {None, "127.0.0.1", "localhost", "::1"}
        and os.getenv("AC_ALLOW_REMOTE_TEST_DATABASE") != "1"
    ):
        pytest.skip("refusing to mutate a non-local PostgreSQL database")
    return url.set(drivername="postgresql+psycopg")


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[_Harness]:
    root = Path(__file__).parents[2]
    base_url = _postgres_url()
    schema = f"learning_http_{uuid4().hex}"
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
            # Operations migration 0006 is outside this learning adapter's
            # scope and currently assumes public-schema audit tables.  0005
            # is the fresh migration boundary required for this journey.
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "20260830_0005"],
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
        schema_engine = create_engine(schema_url, pool_pre_ping=True)
        yield _Harness(engine=schema_engine, schema_url=schema_url)
    finally:
        if schema_engine is not None:
            schema_engine.dispose()
        if created:
            with admin_engine.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True))
        admin_engine.dispose()


def _seed(engine: Engine) -> _Seed:
    tenant_id = uuid4()
    learner_id = uuid4()
    enrollment_id = uuid4()
    program_id = uuid4()
    version_id = uuid4()
    module_id = uuid4()
    activity_id = uuid4()
    command_id = uuid4()
    provenance_id = uuid4()
    entitlement_id = uuid4()
    with Session(engine) as database:
        database.add_all(
            [
                Tenant(id=tenant_id, slug=f"g1-{uuid4().hex[:10]}", name="G1 tenant"),
                Person(
                    id=learner_id,
                    email=f"learner-{learner_id.hex}@example.test",
                    email_verified_at=NOW,
                ),
            ]
        )
        database.flush()
        database.add(Membership(tenant_id=tenant_id, person_id=learner_id, role="learner"))
        database.flush()
        database.add(
            Program(
                id=program_id,
                scope=CatalogScope.GLOBAL.value,
                owner_key=GLOBAL_CATALOG_OWNER_KEY,
                tenant_id=None,
                slug=f"g1-{uuid4().hex[:10]}",
                title="G1 free course",
            )
        )
        database.flush()
        version = ProgramVersion(
            id=version_id,
            program_id=program_id,
            scope=CatalogScope.GLOBAL.value,
            owner_key=GLOBAL_CATALOG_OWNER_KEY,
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
                title="First module",
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
                title="Write a reflection",
                is_required=True,
            )
        )
        database.flush()
        database.add(
            Enrollment(
                id=enrollment_id,
                tenant_id=tenant_id,
                person_id=learner_id,
                program_version_id=version_id,
                program_id=program_id,
                program_scope=CatalogScope.GLOBAL.value,
                program_tenant_id=None,
                program_owner_key=GLOBAL_CATALOG_OWNER_KEY,
                source="free_self",
                status="active",
                enrolled_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        database.flush()
        version.status = ProgramVersionStatus.PUBLISHED.value
        version.published_at = NOW
        database.flush()
        database.add(
            CommandIdempotency(
                id=command_id,
                tenant_id=tenant_id,
                actor_person_id=learner_id,
                subject_person_id=learner_id,
                program_version_id=version_id,
                program_id=program_id,
                program_scope=CatalogScope.GLOBAL.value,
                program_tenant_id=None,
                program_owner_key=GLOBAL_CATALOG_OWNER_KEY,
                operation="enroll_free",
                idempotency_key="seed-enrollment",
                request_digest=hashlib.sha256(b"seed-enrollment").hexdigest(),
                status="pending",
                result_enrollment_id=None,
                result_entitlement_id=None,
                result_provenance_id=None,
                created_at=NOW,
                completed_at=None,
            )
        )
        database.flush()
        database.add(
            EnrollmentProvenance(
                id=provenance_id,
                tenant_id=tenant_id,
                enrollment_id=enrollment_id,
                person_id=learner_id,
                actor_person_id=learner_id,
                program_version_id=version_id,
                program_id=program_id,
                program_scope=CatalogScope.GLOBAL.value,
                program_tenant_id=None,
                program_owner_key=GLOBAL_CATALOG_OWNER_KEY,
                command_idempotency_id=command_id,
                source="free_self",
                reason=None,
                audit_event_name="audit.enrollment.created.v1",
                policy_inputs={},
                controlled_gaps=[],
                created_at=NOW,
            )
        )
        database.flush()
        database.add(
            Entitlement(
                id=entitlement_id,
                tenant_id=tenant_id,
                person_id=learner_id,
                enrollment_id=enrollment_id,
                provenance_id=provenance_id,
                program_version_id=version_id,
                program_id=program_id,
                program_scope=CatalogScope.GLOBAL.value,
                program_tenant_id=None,
                program_owner_key=GLOBAL_CATALOG_OWNER_KEY,
                status="active",
                granted_at=NOW,
                revoked_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        database.flush()
        command = database.get(CommandIdempotency, command_id)
        assert command is not None
        command.status = "completed"
        command.result_enrollment_id = enrollment_id
        command.result_entitlement_id = entitlement_id
        command.result_provenance_id = provenance_id
        command.completed_at = NOW
        database.commit()
    return _Seed(tenant_id, learner_id, enrollment_id, program_id, version_id, activity_id)


def _settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+psycopg://unused:unused@localhost/unused",
        database_migrator_url="postgresql+psycopg://unused:unused@localhost/unused",
        session_token_pepper="learning-http-session-pepper-long-enough",  # noqa: S106
        oauth_transaction_secret="learning-http-oauth-secret-long-enough",  # noqa: S106
        public_app_url="https://app.authorityclosers.test",
        admin_app_url="https://admin.authorityclosers.test",
        api_url="https://api.authorityclosers.test",
    )


def test_learning_http_uses_one_authenticated_postgres_transaction(
    postgres_harness: _Harness,
) -> None:
    seed = _seed(postgres_harness.engine)

    async def scenario() -> None:
        async_engine = create_async_engine(postgres_harness.schema_url, pool_pre_ping=True)
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        actor = ActorContext(
            person_id=seed.learner_id,
            session_id=uuid4(),
            tenant_id=seed.tenant_id,
        )

        async def require_actor(_request: Request) -> AsyncIterator[AuthenticatedTransaction]:
            async with sessions() as database, database.begin():
                yield AuthenticatedTransaction(
                    database=database,
                    identity=cast(Any, object()),
                    resolved=ResolvedActorContext(
                        actor=actor,
                        membership_role="learner",
                        person_revision=0,
                        session_revision=0,
                        tenant_revision=0,
                        membership_revision=0,
                    ),
                    token="learning-http-opaque-session-token",  # noqa: S106
                )

        application = FastAPI()
        register_problem_handlers(application)
        install_learning_http(
            application,
            settings=_settings(),
            require_actor=require_actor,
            reviewer_resolver=lambda _access: uuid4(),
        )
        transport = httpx.ASGITransport(app=application)
        try:
            async with httpx.AsyncClient(
                transport=transport,
                base_url="https://api.authorityclosers.test",
            ) as client:
                activity_url = f"/v1/activities/{seed.activity_id}"
                initial = await client.get(activity_url)
                assert initial.status_code == 200
                assert initial.headers["etag"] == '"activity-revision-0"'
                assert initial.headers["cache-control"] == "no-store"

                draft = await client.put(
                    f"{activity_url}/draft",
                    json={"payload": {"answer": "first durable answer"}},
                    headers={
                        "Origin": "https://app.authorityclosers.test",
                        "If-Match": '"draft-revision-0"',
                        "Idempotency-Key": "http-draft-1",
                    },
                )
                assert draft.status_code == 200
                assert draft.headers["etag"] == '"draft-revision-1"'

                forged = await client.put(
                    f"{activity_url}/draft",
                    json={"payload": {}, "person_id": str(uuid4())},
                    headers={
                        "Origin": "https://app.authorityclosers.test",
                        "If-Match": '"draft-revision-1"',
                        "Idempotency-Key": "http-forged",
                    },
                )
                assert forged.status_code == 422

                stale = await client.put(
                    f"{activity_url}/draft",
                    json={"payload": {"answer": "stale writer"}},
                    headers={
                        "Origin": "https://app.authorityclosers.test",
                        "If-Match": '"draft-revision-0"',
                        "Idempotency-Key": "http-stale",
                    },
                )
                assert stale.status_code == 409
                assert stale.json()["code"] == "draft_revision_conflict"
        finally:
            await async_engine.dispose()

    _run_async(scenario())

    with Session(postgres_harness.engine) as database:
        assert database.scalar(select(func.count()).select_from(ActivityDraft)) == 1
