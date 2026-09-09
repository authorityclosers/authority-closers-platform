"""Canonical public-film import acceptance in an isolated, migrated PostgreSQL schema.

The imported harness rejects unapproved database targets and never substitutes
SQLite. Package bytes here are pytest-only structural doubles, not codec or VPS
evidence. Fixtures create synthetic identities and explicit tenant grants only;
the command still resolves its real opaque session and current authorization.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.audit import AuditRepository
from ac_platform.audit.models import AuditEvent
from ac_platform.authorization.models import CapabilityGrant
from ac_platform.catalog.models import Activity, Module, Program, ProgramVersion
from ac_platform.catalog.services import CatalogConflictError
from ac_platform.enrollment.models import Enrollment
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.identity.services import IdentityServiceError
from ac_platform.media.errors import MediaConflict
from ac_platform.media.models import (
    ActivityMediaBinding,
    MediaAsset,
    MediaCaptionTrack,
    MediaPlaybackGrant,
    MediaQuotaUsage,
    MediaRendition,
    MediaUploadIntent,
    MediaVersion,
)
from ac_platform.media.public_film_import import (
    PublicFilmImportApplication,
    public_film_catalog,
)
from ac_platform.tenancy.models import Membership, Tenant
from tests.integration.test_staging_seed_postgresql import _run_async
from tests.integration.test_staging_seed_postgresql import postgres_harness as postgres_harness
from tests.unit.media.test_public_film_manifest import load_public
from tests.unit.media.test_public_film_manifest import (
    public_artifact_factory as public_artifact_factory,
)
from tests.unit.media.test_staging_fixture_import import artifact_factory as artifact_factory

RELEASE = "a" * 40
PEPPER = "public-film-pg-synthetic-pepper-not-a-secret-12345"
REASON = "Fixed synthetic approval for the licensed technical demonstration package"
IMPORT_ACTION = "media.public_films_imported.v1"
IMPORT_COUNTS = (
    (Program, 1),
    (ProgramVersion, 1),
    (Module, 1),
    (Activity, 2),
    (MediaAsset, 2),
    (MediaVersion, 2),
    (MediaRendition, 4),
    (MediaCaptionTrack, 2),
    (ActivityMediaBinding, 2),
)


@asynccontextmanager
async def scenario(schema_url: URL, pack, *, role="learner"):
    """Accept an already verified pack so real-byte delivery tests can reuse identity setup."""
    query = dict(schema_url.query)
    query["options"] = str(query.get("options", "")) + " -cstatement_timeout=15000"
    engine = create_async_engine(schema_url.set(query=query), pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    person_id, session_id = uuid4(), uuid4()
    token = f"synthetic_public_film_pg_session_{session_id.hex}"
    assert role in {"learner", "owner"}
    permissions = ("catalog_write", "catalog_publish") if role == "learner" else ()
    now = datetime.now(UTC)
    try:
        async with sessions() as database, database.begin():
            database.add_all(
                [
                    Person(
                        id=person_id,
                        email=f"public-film-{person_id.hex}@example.test",
                        email_verified_at=now,
                    ),
                    Tenant(
                        id=pack.tenant_id,
                        slug=f"public-film-pg-{pack.tenant_id.hex}",
                        name="Synthetic public-film import academy",
                    ),
                ]
            )
            await database.flush()
            database.add(Membership(tenant_id=pack.tenant_id, person_id=person_id, role=role))
            await database.flush()
            database.add(
                IdentitySession(
                    id=session_id,
                    person_id=person_id,
                    selected_tenant_id=pack.tenant_id,
                    token_hash=hmac.new(PEPPER.encode(), token.encode(), hashlib.sha256).digest(),
                    created_at=now - timedelta(minutes=1),
                    expires_at=now + timedelta(hours=1),
                )
            )
            await database.flush()
            for permission in permissions:
                grant_id = uuid4()
                audit = await AuditRepository(database).append(
                    tenant_id=pack.tenant_id,
                    actor_person_id=person_id,
                    session_id=session_id,
                    action="test.capability.granted",
                    resource_type="test_capability_grant",
                    resource_id=str(grant_id),
                    payload={"permission": permission, "scope_kind": "tenant"},
                    reason="Explicit synthetic test assignment",
                )
                database.add(
                    CapabilityGrant(
                        id=grant_id,
                        subject_person_id=person_id,
                        granted_by_person_id=person_id,
                        permission=permission,
                        scope_kind="tenant",
                        tenant_id=pack.tenant_id,
                        audit_event_id=audit.id,
                        reason="Explicit synthetic test assignment",
                    )
                )
        yield SimpleNamespace(
            sessions=sessions,
            pack=pack,
            catalog=public_film_catalog(pack),
            person_id=person_id,
            session_id=session_id,
            token=token,
            command_id=uuid4(),
            membership_role=role,
            expected_grants=len(permissions),
        )
    finally:
        await engine.dispose()


async def apply_in_transaction(database, h, *, command_id=None):
    """The caller owns BEGIN and must commit before exposing this result."""
    return await PublicFilmImportApplication(
        database,
        token_pepper=PEPPER,
        environment="test",
        release_id=RELEASE,
        pack=h.pack,
    ).apply(
        session_token=h.token,
        command_id=command_id or h.command_id,
        expected_program_version_id=h.catalog.program_version_id,
        reason=REASON,
    )


async def import_once(h, *, command_id=None):
    async with h.sessions() as database, database.begin():
        result = await apply_in_transaction(database, h, command_id=command_id)
    return result


async def tenant_count(database, h, model):
    return await database.scalar(
        select(func.count()).select_from(model).where(model.tenant_id == h.pack.tenant_id)
    )


async def snapshot(h):
    """Detached persisted values: replay cannot hide a new row or audit rewrite."""
    async with h.sessions() as database, database.begin():
        result = {}
        for model, _ in IMPORT_COUNTS:
            rows = (
                await database.execute(
                    select(model.__table__)
                    .where(model.tenant_id == h.pack.tenant_id)
                    .order_by(model.id)
                )
            ).mappings()
            result[model.__tablename__] = [dict(row) for row in rows]
        for model in (AuditEvent, CapabilityGrant):
            rows = (
                await database.execute(
                    select(model.__table__)
                    .where(model.tenant_id == h.pack.tenant_id)
                    .order_by(model.id)
                )
            ).mappings()
            result[model.__tablename__] = [dict(row) for row in rows]
        result["enrollments"] = await tenant_count(database, h, Enrollment)
        result["delivery_grants"] = await tenant_count(database, h, MediaPlaybackGrant)
        assert (await AuditRepository(database).verify(h.pack.tenant_id)).valid
        return result


async def assert_imported_once(h, result):
    async with h.sessions() as database, database.begin():
        for model, expected in (
            *IMPORT_COUNTS,
            (AuditEvent, 1 + h.expected_grants),
            (CapabilityGrant, h.expected_grants),
        ):
            assert await tenant_count(database, h, model) == expected
        assert await tenant_count(database, h, Enrollment) == 0
        assert await tenant_count(database, h, MediaPlaybackGrant) == 0
        member = await database.scalar(
            select(Membership).where(
                Membership.tenant_id == h.pack.tenant_id, Membership.person_id == h.person_id
            )
        )
        assert member is not None
        assert member.role == h.membership_role and member.status == "active"
        assert (
            await database.scalar(
                select(func.count())
                .select_from(IdentitySession)
                .where(IdentitySession.person_id == h.person_id)
            )
            == 1
        )
        version = await database.get(ProgramVersion, result.program_version_id)
        assert version is not None and version.status == "published"
        assert version.content_reviewed_by == f"person:{h.person_id}"
        activities = (
            await database.scalars(select(Activity).where(Activity.tenant_id == h.pack.tenant_id))
        ).all()
        assert {row.id for row in activities} == set(h.catalog.activity_ids)
        assert all(h.catalog.matches_catalog(row, version) for row in activities)
        assert all(row.kind == "VIDEO" and row.is_required is False for row in activities)
        assert all("not Dipak instruction" in row.prompt for row in activities)
        versions = (
            await database.scalars(
                select(MediaVersion).where(MediaVersion.tenant_id == h.pack.tenant_id)
            )
        ).all()
        assert {row.id for row in versions} == set(result.media_version_ids)
        assert all(row.state == "ready" and row.duration_seconds == 12.032 for row in versions)
        bindings = (
            await database.scalars(
                select(ActivityMediaBinding).where(
                    ActivityMediaBinding.tenant_id == h.pack.tenant_id
                )
            )
        ).all()
        assert {row.id for row in bindings} == set(result.binding_ids)
        assert all(row.state == "approved" for row in bindings)
        audit = await database.get(AuditEvent, h.command_id)
        assert audit is not None
        assert audit.action == IMPORT_ACTION and audit.resource_type == "public_film_import"
        assert audit.resource_id == h.pack.manifest_sha256
        assert audit.actor_type == "person" and audit.actor_person_id == h.person_id
        assert audit.session_id == h.session_id and audit.reason == REASON
        assert audit.request_id == f"public-films:{h.command_id}"
        assert audit.payload == {
            "manifest_sha256": h.pack.manifest_sha256,
            "release_id": RELEASE,
            "environment": "test",
            "program_id": str(h.catalog.program_id),
            "program_version_id": str(h.catalog.program_version_id),
            "content_digest": h.catalog.content_digest,
            "course_content": False,
            "watch_completion_enabled": False,
            "binding_ids": [str(item) for item in result.binding_ids],
            "media_version_ids": [str(item) for item in result.media_version_ids],
        }
        assert h.token not in json.dumps(audit.payload)
        assert (await AuditRepository(database).verify(h.pack.tenant_id)).valid


@pytest.mark.parametrize("role", ["learner", "owner"])
def test_real_import_and_fresh_session_replay_preserve_exact_history(
    postgres_harness: URL, public_artifact_factory, role: str
):
    pack = load_public(public_artifact_factory())

    async def run():
        async with scenario(postgres_harness, pack, role=role) as h:
            first = await import_once(h)
            assert first.status == "imported"
            before = await snapshot(h)
            second = await import_once(h)
            assert second.status == "already_imported"
            assert first.binding_ids == second.binding_ids
            assert first.media_version_ids == second.media_version_ids
            assert before == await snapshot(h)
            await assert_imported_once(h, first)

    _run_async(run())


def test_concurrent_exact_command_waits_for_real_postgresql_lock_and_replays(
    postgres_harness: URL, public_artifact_factory
):
    pack = load_public(public_artifact_factory())

    async def run():
        async with scenario(postgres_harness, pack) as h:
            first_ready, second_started, release_first = (
                asyncio.Event(),
                asyncio.Event(),
                asyncio.Event(),
            )
            backend_ids = {}

            async def first_import():
                async with h.sessions() as database, database.begin():
                    backend_ids["first"] = await database.scalar(select(func.pg_backend_pid()))
                    result = await apply_in_transaction(database, h)
                    first_ready.set()
                    await asyncio.wait_for(release_first.wait(), timeout=15)
                return result

            async def second_import():
                await asyncio.wait_for(first_ready.wait(), timeout=15)
                async with h.sessions() as database, database.begin():
                    backend_ids["second"] = await database.scalar(select(func.pg_backend_pid()))
                    second_started.set()
                    result = await apply_in_transaction(database, h)
                return result

            tasks = [asyncio.create_task(first_import()), asyncio.create_task(second_import())]
            try:
                await asyncio.wait_for(second_started.wait(), timeout=15)
                assert backend_ids["first"] != backend_ids["second"]
                observed_block = False
                async with h.sessions() as observer, observer.begin():
                    deadline = asyncio.get_running_loop().time() + 5
                    while asyncio.get_running_loop().time() < deadline:
                        blockers = await observer.scalar(
                            select(func.pg_blocking_pids(backend_ids["second"]))
                        )
                        if backend_ids["first"] in blockers:
                            observed_block = True
                            break
                        await asyncio.sleep(0.025)
                assert observed_block, "The second import never waited on the first transaction"
                assert not tasks[1].done()
                release_first.set()
                first, second = await asyncio.wait_for(asyncio.gather(*tasks), timeout=30)
            finally:
                release_first.set()
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
            assert first.status == "imported" and second.status == "already_imported"
            assert first.binding_ids == second.binding_ids
            assert first.media_version_ids == second.media_version_ids
            await assert_imported_once(h, first)

    _run_async(run())


def test_different_command_cannot_reapprove_existing_package(
    postgres_harness: URL, public_artifact_factory
):
    pack = load_public(public_artifact_factory())

    async def run():
        async with scenario(postgres_harness, pack) as h:
            first = await import_once(h)
            before = await snapshot(h)
            with pytest.raises((MediaConflict, CatalogConflictError)):
                await import_once(h, command_id=uuid4())
            assert before == await snapshot(h)
            await assert_imported_once(h, first)

    _run_async(run())


def test_late_audit_failure_rolls_back_import_even_when_caller_commits(
    postgres_harness: URL, public_artifact_factory, monkeypatch: pytest.MonkeyPatch
):
    pack = load_public(public_artifact_factory())
    original_append = AuditRepository.append
    reached_final_audit = []

    async def append(repository, **kwargs):
        if kwargs.get("action") == IMPORT_ACTION:
            reached_final_audit.append(True)
            raise MediaConflict("Synthetic final import audit failure")
        return await original_append(repository, **kwargs)

    monkeypatch.setattr(AuditRepository, "append", append)

    async def run():
        async with scenario(postgres_harness, pack) as h:
            before = await snapshot(h)
            async with h.sessions() as database, database.begin():
                with pytest.raises(MediaConflict, match="Synthetic final import audit failure"):
                    await apply_in_transaction(database, h)
            assert reached_final_audit == [True]
            assert before == await snapshot(h)
            async with h.sessions() as database, database.begin():
                for model in (MediaUploadIntent, MediaQuotaUsage):
                    assert await tenant_count(database, h, model) == 0
                assert await tenant_count(database, h, AuditEvent) == 2
                assert await database.get(AuditEvent, h.command_id) is None

    _run_async(run())


@pytest.mark.parametrize("imported_before_revocation", [False, True])
def test_revoked_real_session_is_denied_before_import_and_replay(
    postgres_harness: URL, public_artifact_factory, imported_before_revocation: bool
):
    pack = load_public(public_artifact_factory())

    async def run():
        async with scenario(postgres_harness, pack) as h:
            if imported_before_revocation:
                await import_once(h)
            async with h.sessions() as database, database.begin():
                session = await database.get(IdentitySession, h.session_id)
                assert session is not None
                session.revoked_at = datetime.now(UTC)
                session.revocation_reason = "Synthetic test revocation"
            before = await snapshot(h)
            with pytest.raises(IdentityServiceError):
                await import_once(h)
            assert before == await snapshot(h)

    _run_async(run())
