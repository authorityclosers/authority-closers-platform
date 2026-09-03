"""Fresh-PostgreSQL proof for the self-scoped learner certificate read."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import subprocess
import sys
from collections.abc import Coroutine, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, create_engine, update
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from ac_platform.application.settings import Settings
from ac_platform.catalog.models import CatalogScope, Program, ProgramVersion
from ac_platform.catalog.services import CatalogService, SqlAlchemyCatalogStore
from ac_platform.certificates.models import CertificateEvent, CourseCompletionCertificate
from ac_platform.certificates.models import CompletionSnapshot as CompletionSnapshotRecord
from ac_platform.certificates.services import (
    CertificateEventType,
    CompletionSnapshot,
    ModuleCompletion,
)
from ac_platform.enrollment.models import Enrollment
from ac_platform.http.auth import install_identity_http
from ac_platform.http.certificates import install_certificate_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.tenancy.models import Membership, Tenant

NOW = datetime(2026, 8, 30, 12, tzinfo=UTC)
SESSION_PEPPER = "certificate-http-session-pepper-long-enough"  # noqa: S105


@dataclass(frozen=True, slots=True)
class _Harness:
    engine: Engine
    schema_url: URL


@dataclass(frozen=True, slots=True)
class _Seed:
    tenant_id: UUID
    other_tenant_id: UUID
    learner_id: UUID
    other_person_id: UUID
    certificate_id: UUID
    learner_token: str
    other_tenant_token: str
    other_person_token: str
    no_context_token: str


def _run_async[T](coroutine: Coroutine[Any, Any, T]) -> T:
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            return runner.run(coroutine)
    return asyncio.run(coroutine)


def _postgres_url() -> URL:
    raw = os.getenv("AC_CERTIFICATE_HTTP_POSTGRES_TEST_URL") or os.getenv("AC_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("certificate HTTP PostgreSQL URL is not configured")
    url = make_url(raw)
    if url.get_backend_name() != "postgresql":
        pytest.skip("certificate HTTP integration requires PostgreSQL")
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
    schema = f"certificate_http_{uuid4().hex}"
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
        migration_environment = os.environ.copy()
        migration_environment.update(
            {
                "AC_DATABASE_URL": base_url.render_as_string(hide_password=False),
                "AC_DATABASE_MIGRATOR_URL": base_url.render_as_string(hide_password=False),
                "AC_ENVIRONMENT": "test",
                "PGOPTIONS": f"-csearch_path={schema}",
                "PYTHONPATH": os.pathsep.join(
                    part
                    for part in (
                        str(root / "packages" / "python"),
                        migration_environment.get("PYTHONPATH", ""),
                    )
                    if part
                ),
            }
        )
        migration = subprocess.run(
            # This adapter uses the current catalog models, so its isolated
            # schema must prove the full forward-only migration chain.
            [
                sys.executable,
                "-m",
                "alembic",
                "-c",
                "alembic.ini",
                "upgrade",
                "head",
            ],
            cwd=root,
            env=migration_environment,
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


def _token_hash(token: str) -> bytes:
    return hmac.new(SESSION_PEPPER.encode("utf-8"), token.encode("ascii"), hashlib.sha256).digest()


def _settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+psycopg://unused:unused@localhost/unused",
        database_migrator_url="postgresql+psycopg://unused:unused@localhost/unused",
        session_token_pepper=SESSION_PEPPER,
        oauth_transaction_secret="certificate-http-oauth-secret-long-enough",  # noqa: S106
        public_app_url="https://app.authorityclosers.test",
        admin_app_url="https://admin.authorityclosers.test",
        api_url="https://api.authorityclosers.test",
    )


def _seed(engine: Engine) -> _Seed:
    tenant_id, other_tenant_id = uuid4(), uuid4()
    learner_id, other_person_id = uuid4(), uuid4()
    program_id, program_version_id = uuid4(), uuid4()
    enrollment_id, snapshot_id, certificate_id = uuid4(), uuid4(), uuid4()
    module_id, activity_id = uuid4(), uuid4()
    learner_token = f"certificate-http-learner-{uuid4().hex}"
    other_tenant_token = f"certificate-http-other-tenant-{uuid4().hex}"
    other_person_token = f"certificate-http-other-person-{uuid4().hex}"
    no_context_token = f"certificate-http-no-context-{uuid4().hex}"

    module = ModuleCompletion(
        module_id=module_id,
        prerequisite_module_ids=(),
        required_activity_ids=(activity_id,),
        completed_activity_ids=(activity_id,),
        prerequisites_satisfied=True,
        is_complete=True,
    )
    completion = CompletionSnapshot(
        id=snapshot_id,
        tenant_id=tenant_id,
        person_id=learner_id,
        enrollment_id=enrollment_id,
        program_id=program_id,
        program_version_id=program_version_id,
        program_scope=CatalogScope.TENANT.value,
        program_tenant_id=tenant_id,
        program_owner_key=tenant_id,
        predicate_version="g1-v1",
        required_activity_ids=(activity_id,),
        completed_activity_ids=(activity_id,),
        module_results=(module,),
        required_activity_count=1,
        completed_activity_count=1,
        is_complete=True,
        captured_at=NOW,
    )

    def identity_session(
        person_id: UUID,
        token: str,
        selected_tenant_id: UUID | None,
    ) -> IdentitySession:
        return IdentitySession(
            id=uuid4(),
            person_id=person_id,
            token_hash=_token_hash(token),
            created_at=NOW,
            # Keep this fixture independent of the wall clock. The route resolves
            # sessions against real UTC time; a one-day lifetime made the otherwise
            # deterministic PostgreSQL contract expire after its authored date.
            expires_at=NOW + timedelta(days=3650),
            selected_tenant_id=selected_tenant_id,
        )

    with Session(engine) as database:
        database.add_all(
            [
                Tenant(
                    id=tenant_id,
                    slug=f"certificate-http-{uuid4().hex[:10]}",
                    name="Certificate HTTP",
                ),
                Tenant(
                    id=other_tenant_id,
                    slug=f"certificate-http-other-{uuid4().hex[:10]}",
                    name="Other Certificate HTTP",
                ),
                Person(
                    id=learner_id,
                    email=f"certificate-learner-{learner_id.hex}@example.test",
                    email_verified_at=NOW,
                ),
                Person(
                    id=other_person_id,
                    email=f"certificate-other-{other_person_id.hex}@example.test",
                    email_verified_at=NOW,
                ),
            ]
        )
        database.flush()
        database.add_all(
            [
                Membership(tenant_id=tenant_id, person_id=learner_id, role="learner"),
                Membership(tenant_id=other_tenant_id, person_id=learner_id, role="learner"),
                Membership(tenant_id=tenant_id, person_id=other_person_id, role="learner"),
            ]
        )
        database.flush()
        program = Program(
            id=program_id,
            scope=CatalogScope.TENANT.value,
            owner_key=tenant_id,
            tenant_id=tenant_id,
            slug=f"certificate-http-program-{uuid4().hex[:10]}",
            title="Certificate HTTP program",
        )
        version = ProgramVersion(
            id=program_version_id,
            program_id=program_id,
            scope=CatalogScope.TENANT.value,
            owner_key=tenant_id,
            tenant_id=tenant_id,
            version_number=1,
            status="draft",
        )
        database.add(program)
        database.flush()
        database.add(version)
        database.flush()
        store = SqlAlchemyCatalogStore(database)
        catalog = CatalogService(store, clock=lambda: NOW)
        snapshot = store.get_version(program_version_id)
        assert snapshot is not None
        version.content_digest = catalog._canonical_content_digest(snapshot)  # noqa: SLF001
        version.content_source_ref = __file__
        version.content_reviewed_by = "certificate-http-reviewer@example.test"
        version.content_reviewed_at = NOW
        version.release_id = "1" * 40
        version.content_seed_kind = "reviewed"
        database.flush()
        catalog.publish_version(program_version_id, tenant_id=tenant_id, now=NOW)
        database.add(
            Enrollment(
                id=enrollment_id,
                tenant_id=tenant_id,
                person_id=learner_id,
                program_version_id=program_version_id,
                program_id=program_id,
                program_scope=CatalogScope.TENANT.value,
                program_tenant_id=tenant_id,
                program_owner_key=tenant_id,
                source="free_self",
                status="active",
                enrolled_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        database.flush()
        database.add(
            CompletionSnapshotRecord(
                id=completion.id,
                tenant_id=tenant_id,
                person_id=learner_id,
                enrollment_id=enrollment_id,
                program_id=program_id,
                program_version_id=program_version_id,
                program_scope=CatalogScope.TENANT.value,
                program_tenant_id=tenant_id,
                program_owner_key=tenant_id,
                predicate_version=completion.predicate_version,
                required_activity_count=completion.required_activity_count,
                completed_activity_count=completion.completed_activity_count,
                is_complete=completion.is_complete,
                required_activity_ids=[str(activity_id)],
                completed_activity_ids=[str(activity_id)],
                module_results=[
                    {
                        "module_id": str(module.module_id),
                        "prerequisite_module_ids": [],
                        "required_activity_ids": [str(activity_id)],
                        "completed_activity_ids": [str(activity_id)],
                        "prerequisites_satisfied": True,
                        "is_complete": True,
                    }
                ],
                snapshot_hash=cast(str, completion.snapshot_hash),
                captured_at=NOW,
            )
        )
        database.flush()
        database.add(
            CourseCompletionCertificate(
                id=certificate_id,
                tenant_id=tenant_id,
                person_id=learner_id,
                enrollment_id=enrollment_id,
                program_id=program_id,
                program_version_id=program_version_id,
                program_scope=CatalogScope.TENANT.value,
                program_tenant_id=tenant_id,
                program_owner_key=tenant_id,
                certificate_type="course-completion",
                original_completion_snapshot_id=snapshot_id,
                idempotency_key="certificate-http-issue",
                issued_at=NOW,
                created_at=NOW,
            )
        )
        database.flush()
        database.add(
            CertificateEvent(
                id=uuid4(),
                certificate_id=certificate_id,
                tenant_id=tenant_id,
                person_id=learner_id,
                enrollment_id=enrollment_id,
                program_id=program_id,
                program_version_id=program_version_id,
                program_scope=CatalogScope.TENANT.value,
                program_tenant_id=tenant_id,
                program_owner_key=tenant_id,
                sequence_no=1,
                event_type=CertificateEventType.ISSUED.value,
                completion_snapshot_id=snapshot_id,
                supersedes_event_id=None,
                actor_person_id=None,
                reason=None,
                provenance={"source": "certificate-http-test"},
                idempotency_key="certificate-http-issue",
                request_digest="",
                occurred_at=NOW,
            )
        )
        database.flush()
        database.add_all(
            [
                identity_session(learner_id, learner_token, tenant_id),
                identity_session(learner_id, other_tenant_token, other_tenant_id),
                identity_session(other_person_id, other_person_token, tenant_id),
                identity_session(learner_id, no_context_token, None),
            ]
        )
        database.commit()
    return _Seed(
        tenant_id=tenant_id,
        other_tenant_id=other_tenant_id,
        learner_id=learner_id,
        other_person_id=other_person_id,
        certificate_id=certificate_id,
        learner_token=learner_token,
        other_tenant_token=other_tenant_token,
        other_person_token=other_person_token,
        no_context_token=no_context_token,
    )


def test_certificate_http_is_self_tenant_and_active_context_scoped(
    postgres_harness: _Harness,
) -> None:
    seed = _seed(postgres_harness.engine)

    async def scenario() -> None:
        async_engine = create_async_engine(postgres_harness.schema_url, pool_pre_ping=True)
        sessions = async_sessionmaker(async_engine, expire_on_commit=False)
        application = FastAPI()
        register_problem_handlers(application)
        require_actor = install_identity_http(
            application,
            settings=_settings(),
            sessions=sessions,
        )
        install_certificate_http(application, require_actor=require_actor)
        transport = httpx.ASGITransport(app=application)
        try:
            async with httpx.AsyncClient(
                transport=transport,
                base_url="https://api.authorityclosers.test",
            ) as client:
                client.cookies.set("ac_session", seed.learner_token)
                success = await client.get(f"/v1/certificates/{seed.certificate_id}")
                assert success.status_code == 200
                assert success.headers["cache-control"] == "no-store"
                assert success.headers["pragma"] == "no-cache"
                payload = success.json()
                assert payload["id"] == str(seed.certificate_id)
                assert payload["status"] == "issued"
                assert payload["completion"]["is_complete"] is True
                assert "person_id" not in payload
                assert "tenant_id" not in payload
                assert "provenance" not in payload

                guessed = await client.get(f"/v1/certificates/{uuid4()}")
                assert guessed.status_code == 404
                assert guessed.json()["code"] == "resource_not_found"

                client.cookies.set("ac_session", seed.other_person_token)
                wrong_person = await client.get(f"/v1/certificates/{seed.certificate_id}")
                assert wrong_person.status_code == 403
                assert wrong_person.json()["code"] == "authorization_denied"

                client.cookies.set("ac_session", seed.other_tenant_token)
                wrong_tenant = await client.get(f"/v1/certificates/{seed.certificate_id}")
                assert wrong_tenant.status_code == 403
                assert wrong_tenant.json()["code"] == "authorization_denied"

                client.cookies.set("ac_session", seed.no_context_token)
                no_context = await client.get(f"/v1/certificates/{seed.certificate_id}")
                assert no_context.status_code == 403
                assert no_context.json()["code"] == "certificate_tenant_context_required"

                async with sessions() as database, database.begin():
                    await database.execute(
                        update(Membership)
                        .where(
                            Membership.tenant_id == seed.tenant_id,
                            Membership.person_id == seed.learner_id,
                        )
                        .values(status="inactive", ended_at=NOW)
                    )
                client.cookies.set("ac_session", seed.learner_token)
                inactive_context = await client.get(f"/v1/certificates/{seed.certificate_id}")
                assert inactive_context.status_code == 403
                assert inactive_context.json()["code"] == "tenant_context_denied"
        finally:
            await async_engine.dispose()

    _run_async(scenario())
