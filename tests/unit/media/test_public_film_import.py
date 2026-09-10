"""Real relational/canonical service tests; tiny bytes are NOT codec/VPS evidence."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from ac_platform.audit import AuditRepository
from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain_sync
from ac_platform.authorization.models import CapabilityGrant, CapabilityRevocation
from ac_platform.authorization.policy import CapabilityDenied
from ac_platform.catalog.content import (
    CanonicalActivityContent,
    CanonicalModuleContent,
    canonical_catalog_content_digest,
)
from ac_platform.catalog.models import Activity, Module, Program, ProgramVersion
from ac_platform.catalog.services import AsyncCatalogApplication, CatalogConflictError
from ac_platform.db.models import model_metadata
from ac_platform.enrollment.models import Enrollment
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.identity.services import IdentityServiceError
from ac_platform.kernel.authz import ActorContext
from ac_platform.media import public_film_manifest as manifest
from ac_platform.media.api_contracts import ActivityMediaBindingRequest
from ac_platform.media.errors import MediaConflict, MediaForbidden
from ac_platform.media.models import (
    ActivityMediaBinding,
    MediaAsset,
    MediaPlaybackGrant,
    MediaVersion,
)
from ac_platform.media.public_film_import import (
    PublicFilmImportApplication,
    main,
    public_film_catalog,
)
from ac_platform.tenancy.models import Membership, Tenant
from tests.unit.media.test_staging_fixture_import import AsyncDatabase as StagingDatabase
from tests.unit.media.test_staging_fixture_import import artifact_factory as artifact_factory

RELEASE = "a" * 40
TOKEN = "canonical_synthetic_operator_token_for_test_12345"  # noqa: S105 - isolated fixture
PEPPER = "public-film-test-pepper-only-not-a-secret-12345"


class Database(StagingDatabase):
    async def get(self, model, key):
        return self.session.get(model, key)


@pytest.fixture
def public_artifact(artifact_factory, monkeypatch):
    old = artifact_factory()
    payload = json.loads(manifest.MANIFEST_PATH.read_bytes())
    payload["clips"] = old.payload["clips"]
    raw = json.dumps(payload).encode()
    target = old.root / "test-only-public-manifest.json"
    target.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(manifest, "MANIFEST_PATH", target)
    monkeypatch.setattr(manifest, "MANIFEST_SHA256", digest)
    return SimpleNamespace(root=old.root, tenant_id=old.tenant_id, digest=digest)


@pytest.fixture
def pack(public_artifact):
    return manifest.load_verified_public_film_pack(
        environment="test",
        release_id=RELEASE,
        tenant_id=public_artifact.tenant_id,
        root=public_artifact.root,
        expected_manifest_sha256=public_artifact.digest,
    )


@pytest.fixture
def state(pack):
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def configure(connection, _):
        connection.isolation_level = None
        connection.execute("PRAGMA foreign_keys=ON")

    @event.listens_for(engine, "begin")
    def begin(connection):
        connection.exec_driver_sql("BEGIN")

    model_metadata().create_all(engine)
    database = Session(engine, expire_on_commit=False)
    person_id, session_id, other_tenant = uuid4(), uuid4(), uuid4()
    now = datetime.now(UTC)
    with database.begin():
        database.add_all(
            [
                Person(
                    id=person_id, email="synthetic-operator@example.test", email_verified_at=now
                ),
                Tenant(id=pack.tenant_id, slug="film-academy", name="Film academy"),
                Tenant(id=other_tenant, slug="other-academy", name="Other academy"),
            ]
        )
        database.flush()
        database.add(Membership(tenant_id=pack.tenant_id, person_id=person_id, role="owner"))
        database.flush()
        database.add(
            IdentitySession(
                id=session_id,
                person_id=person_id,
                selected_tenant_id=pack.tenant_id,
                token_hash=hmac.new(PEPPER.encode(), TOKEN.encode(), hashlib.sha256).digest(),
                created_at=now - timedelta(minutes=1),
                expires_at=now + timedelta(hours=1),
            )
        )
    facade = Database(database)
    app = PublicFilmImportApplication(
        facade, token_pepper=PEPPER, environment="test", release_id=RELEASE, pack=pack
    )
    yield SimpleNamespace(
        engine=engine,
        database=database,
        facade=facade,
        app=app,
        pack=pack,
        person_id=person_id,
        session_id=session_id,
        other_tenant=other_tenant,
        command_id=uuid4(),
    )
    database.close()
    engine.dispose()


async def apply(state, **changes):
    values = dict(
        session_token=TOKEN,
        command_id=state.command_id,
        expected_program_version_id=state.app.catalog.program_version_id,
        reason="Approve the fixed licensed technical demonstration package",
    )
    values.update(changes)
    async with state.facade.begin():
        return await state.app.apply(**values)


def count(database, model):
    return database.scalar(select(func.count()).select_from(model))


async def tenant_grants(state):
    async with state.facade.begin():
        member = state.database.scalar(
            select(Membership).where(Membership.person_id == state.person_id)
        )
        member.role = "learner"
        for permission in ("catalog_write", "catalog_publish"):
            audit = await AuditRepository(state.facade).append(
                tenant_id=state.pack.tenant_id,
                actor_person_id=state.person_id,
                action="test.capability.granted",
                resource_type="test",
                payload={},
            )
            state.database.add(
                CapabilityGrant(
                    subject_person_id=state.person_id,
                    granted_by_person_id=state.person_id,
                    permission=permission,
                    scope_kind="tenant",
                    tenant_id=state.pack.tenant_id,
                    audit_event_id=audit.id,
                    reason="Explicit synthetic test assignment",
                )
            )


async def test_real_import_publishes_only_optional_tenant_videos_with_atomic_audit(state):
    result = await apply(state)
    with state.database.begin():
        assert result.status == "imported"
        assert count(state.database, Program) == count(state.database, ProgramVersion) == 1
        assert count(state.database, Module) == 1
        activities = tuple(state.database.scalars(select(Activity).order_by(Activity.position)))
        version = state.database.get(ProgramVersion, result.program_version_id)
        assert len(activities) == 2
        assert all(item.kind == "VIDEO" and item.is_required is False for item in activities)
        assert all(state.app.catalog.matches_catalog(item, version) for item in activities)
        assert all("not Dipak instruction" in item.prompt for item in activities)
        assert version.content_reviewed_by == f"person:{state.person_id}"
        assert all(row.state == "ready" for row in state.database.scalars(select(MediaVersion)))
        assert count(state.database, Enrollment) == count(state.database, MediaPlaybackGrant) == 0
        audit = state.database.get(AuditEvent, state.command_id)
        assert audit.session_id == state.session_id and audit.actor_person_id == state.person_id
        assert audit.payload["course_content"] is False
        assert audit.payload["watch_completion_enabled"] is False
        assert TOKEN not in json.dumps(audit.payload)
        assert verify_audit_chain_sync(state.database, state.pack.tenant_id).valid


async def test_tenant_assigned_learner_imports_without_generic_permission_or_role_invention(state):
    await tenant_grants(state)
    await apply(state)
    with state.database.begin():
        member = state.database.scalar(
            select(Membership).where(Membership.person_id == state.person_id)
        )
        assert member.role == "learner"
        assert count(state.database, IdentitySession) == 1


async def test_replay_keeps_same_bindings_versions_and_single_import_audit(state):
    first, second = await apply(state), await apply(state)
    assert second.status == "already_imported"
    assert first.binding_ids == second.binding_ids
    with state.database.begin():
        assert count(state.database, AuditEvent) == 1
        assert count(state.database, MediaAsset) == count(state.database, ActivityMediaBinding) == 2


@pytest.mark.parametrize("change", ["reason", "command", "other-event"])
async def test_exact_intent_replay_conflict_never_creates_second_catalog(state, change):
    await apply(state)
    if change == "other-event":
        other = uuid4()
        async with state.facade.begin():
            await AuditRepository(state.facade).append(
                tenant_id=state.other_tenant,
                actor_person_id=state.person_id,
                event_id=other,
                action="other.command",
                resource_type="test",
            )
        overrides = {"command_id": other}
    else:
        overrides = (
            {"reason": "Different approval intent"}
            if change == "reason"
            else {"command_id": uuid4()}
        )
    with pytest.raises((MediaConflict, CatalogConflictError)):
        await apply(state, **overrides)
    with state.database.begin():
        assert count(state.database, Program) == 1
        assert count(state.database, ActivityMediaBinding) == 2


@pytest.mark.parametrize(
    "denial",
    [
        "token",
        "expired",
        "revoked",
        "tenantless",
        "suspended",
        "unverified",
        "member-ended",
        "tenant-inactive",
        "read-only",
    ],
)
async def test_normal_auth_and_fresh_authority_denials_precede_catalog_writes(state, denial):
    with state.database.begin():
        session = state.database.get(IdentitySession, state.session_id)
        person = state.database.get(Person, state.person_id)
        member = state.database.scalar(
            select(Membership).where(Membership.person_id == state.person_id)
        )
        if denial == "expired":
            session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        if denial == "revoked":
            session.revoked_at = datetime.now(UTC)
            session.revocation_reason = "test"
        if denial == "tenantless":
            session.selected_tenant_id = None
        if denial == "suspended":
            person.status = "suspended"
        if denial == "unverified":
            person.email_verified_at = None
        if denial == "member-ended":
            member.status = "inactive"
            member.ended_at = datetime.now(UTC)
        if denial == "tenant-inactive":
            state.database.get(Tenant, state.pack.tenant_id).status = "suspended"
        if denial == "read-only":
            member.role = "learner"
    with pytest.raises((MediaForbidden, CapabilityDenied, IdentityServiceError)):
        await apply(state, **({"session_token": "x" * 44} if denial == "token" else {}))
    with state.database.begin():
        assert count(state.database, Program) == count(state.database, MediaAsset) == 0


async def test_replay_rechecks_revoked_scope(state):
    await tenant_grants(state)
    await apply(state)
    with state.database.begin():
        grant = state.database.scalar(
            select(CapabilityGrant).where(CapabilityGrant.permission == "catalog_publish")
        )
        state.database.add(
            CapabilityRevocation(
                grant_id=grant.id,
                revoked_by_person_id=state.person_id,
                audit_event_id=grant.audit_event_id,
                reason="Synthetic revocation",
            )
        )
    with pytest.raises(CapabilityDenied):
        await apply(state)


@pytest.mark.parametrize("failure", ["second-source", "audit"])
async def test_late_failure_rolls_back_catalog_media_approval_even_if_caller_catches(
    state, monkeypatch, failure
):
    if failure == "second-source":
        original = state.app.service.process_version

        def process(database, actor, version_id, **kwargs):
            if version_id == state.pack.clips[1].version_id:
                raise MediaConflict("Synthetic late processing failure")
            return original(database, actor, version_id, **kwargs)

        monkeypatch.setattr(state.app.service, "process_version", process)
    else:

        async def append(*args, **kwargs):
            raise MediaConflict("Synthetic audit failure")

        monkeypatch.setattr(AuditRepository, "append", append)
    async with state.facade.begin():
        with pytest.raises(MediaConflict):
            await state.app.apply(
                session_token=TOKEN,
                command_id=state.command_id,
                expected_program_version_id=state.app.catalog.program_version_id,
                reason="Approved demo",
            )
    with state.database.begin():
        for model in (
            Program,
            ProgramVersion,
            Activity,
            MediaAsset,
            MediaVersion,
            ActivityMediaBinding,
            AuditEvent,
        ):
            assert count(state.database, model) == 0


@pytest.mark.parametrize(
    "change", ["revoked", "expired", "context", "permission", "service", "wrong-version", "fake"]
)
async def test_sealed_lease_rechecks_state_and_target_before_processing(state, monkeypatch, change):
    if change == "permission":
        await tenant_grants(state)
    original = state.app.service.process_version

    def process(database, actor, version_id, *, public_film_authorization):
        session = database.get(IdentitySession, actor.session_id)
        lease = public_film_authorization
        if change == "revoked":
            session.revoked_at = datetime.now(UTC)
            session.revocation_reason = "test"
        elif change == "expired":
            session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        elif change == "context":
            session.selected_tenant_id = None
        elif change == "permission":
            grant = database.scalar(
                select(CapabilityGrant).where(CapabilityGrant.permission == "catalog_publish")
            )
            database.add(
                CapabilityRevocation(
                    grant_id=grant.id,
                    revoked_by_person_id=actor.person_id,
                    audit_event_id=grant.audit_event_id,
                    reason="Synthetic revocation during command",
                )
            )
        elif change == "service":
            lease = replace(lease, service=object())
        elif change == "wrong-version":
            version_id = uuid4()
        elif change == "fake":
            lease = SimpleNamespace(require=lambda *args, **kwargs: None)
        database.flush()
        return original(database, actor, version_id, public_film_authorization=lease)

    monkeypatch.setattr(state.app.service, "process_version", process)
    with pytest.raises(MediaForbidden):
        await apply(state)
    with state.database.begin():
        assert count(state.database, Program) == 0


async def test_lease_cannot_survive_its_savepoint_or_switch_database(state, monkeypatch):
    captured = []
    original = state.app.service.process_version

    def process(database, actor, version_id, *, public_film_authorization):
        captured.append(public_film_authorization)
        with Session(state.engine) as other, pytest.raises(MediaForbidden):
            public_film_authorization.require(
                other, actor, version_id=version_id, service=state.app.service
            )
        return original(
            database, actor, version_id, public_film_authorization=public_film_authorization
        )

    monkeypatch.setattr(state.app.service, "process_version", process)
    async with state.facade.begin():
        await state.app.apply(
            session_token=TOKEN,
            command_id=state.command_id,
            expected_program_version_id=state.app.catalog.program_version_id,
            reason="Approved demo",
        )
        # Root transaction is still open, but its authorizing savepoint ended.
        lease = captured[0]
        with pytest.raises(MediaForbidden):
            lease.require(
                state.database,
                lease.actor,
                version_id=state.pack.clips[0].version_id,
                service=state.app.service,
            )
    with state.database.begin(), pytest.raises(MediaForbidden):
        lease.require(
            state.database,
            lease.actor,
            version_id=state.pack.clips[0].version_id,
            service=state.app.service,
        )


async def test_lease_refuses_film_swap_in_otherwise_allowed_binding(state, monkeypatch):
    original = state.app.service.bind_activity_media

    def bind(database, actor, request, **kwargs):
        wrong = request.model_copy(update={"activity_id": state.app.catalog.activity_ids[1]})
        return original(database, actor, wrong, **kwargs)

    monkeypatch.setattr(state.app.service, "bind_activity_media", bind)
    with pytest.raises(MediaForbidden):
        await apply(state)


async def test_general_service_still_denies_unassigned_actor_without_lease(state):
    actor = ActorContext(state.person_id, state.session_id, state.pack.tenant_id)
    async with state.facade.begin():
        with pytest.raises(MediaForbidden):
            state.app.service.bind_activity_media(
                state.database,
                actor,
                ActivityMediaBindingRequest(
                    activity_id=uuid4(),
                    module_id=uuid4(),
                    program_id=uuid4(),
                    program_version_id=uuid4(),
                    program_scope="tenant",
                    program_owner_key=state.pack.tenant_id,
                    asset_id=uuid4(),
                    version_id=uuid4(),
                    approval_reference="test",
                ),
                idempotency_key="test",
            )


@pytest.mark.parametrize("clip_index", [0, 1])
@pytest.mark.parametrize("identity", ["both", "asset-only", "version-only"])
async def test_generic_manager_cannot_bind_public_films_into_a_normal_course(
    state, clip_index, identity
):
    await apply(state)
    actor = ActorContext(
        state.person_id,
        state.session_id,
        state.pack.tenant_id,
        frozenset({"catalog_write", "catalog_publish"}),
    )
    async with state.facade.begin():
        catalog = AsyncCatalogApplication(state.facade)
        scope = {"actor": actor, "tenant_id": state.pack.tenant_id}
        program = await catalog.create_program(
            **scope, slug="normal-synthetic-course", title="Synthetic instructional course"
        )
        version = await catalog.create_version(
            program.id,
            **scope,
            content_digest=canonical_catalog_content_digest(
                program_slug="normal-synthetic-course",
                program_title="Synthetic instructional course",
                modules=(
                    CanonicalModuleContent(
                        position=1,
                        title="First module",
                        prerequisite_positions=(),
                        activities=(
                            CanonicalActivityContent(
                                position=1,
                                kind="VIDEO",
                                title="An instructional lesson",
                                is_required=True,
                                prompt=None,
                            ),
                        ),
                    ),
                ),
            ),
            content_source_ref="test:synthetic-instructional-course",
            content_reviewed_by=f"person:{state.person_id}",
            content_reviewed_at=datetime.now(UTC),
            release_id=RELEASE,
            content_seed_kind="reviewed",
        )
        module = await catalog.add_module(version.id, **scope, title="First module")
        activity = await catalog.add_activity(
            module.id, **scope, kind="VIDEO", title="An instructional lesson"
        )
        await catalog.publish_version(version.id, **scope)
        before_audits = count(state.database, AuditEvent)
        clip = state.pack.clips[clip_index]
        request = ActivityMediaBindingRequest(
            activity_id=activity.id,
            module_id=module.id,
            program_id=program.id,
            program_version_id=version.id,
            program_scope="tenant",
            program_owner_key=state.pack.tenant_id,
            asset_id=uuid4() if identity == "version-only" else clip.asset_id,
            version_id=uuid4() if identity == "asset-only" else clip.version_id,
            # Copying the importer's reference is not sealed authorization.
            approval_reference=f"PUBLIC-FILM-DEMO:{state.pack.manifest_sha256}",
        )
        with pytest.raises(MediaForbidden, match="dedicated demonstration"):
            state.app.service.bind_activity_media(
                state.database, actor, request, idempotency_key="ordinary-course-binding"
            )
        assert count(state.database, ActivityMediaBinding) == 2
        assert count(state.database, AuditEvent) == before_audits
        assert all(
            row.state == "approved" for row in state.database.scalars(select(ActivityMediaBinding))
        )
        assert verify_audit_chain_sync(state.database, state.pack.tenant_id).valid


@pytest.mark.parametrize("operation", ["replay", "supersede", "replace"])
async def test_generic_manager_cannot_reapprove_public_demo_without_its_lease(state, operation):
    imported = await apply(state)
    actor = ActorContext(
        state.person_id,
        state.session_id,
        state.pack.tenant_id,
        frozenset({"catalog_write"}),
    )
    with state.database.begin():
        binding = state.database.get(ActivityMediaBinding, imported.binding_ids[0])
        request = ActivityMediaBindingRequest(
            **{
                name: getattr(binding, name)
                for name in (
                    "activity_id",
                    "module_id",
                    "program_id",
                    "program_version_id",
                    "program_scope",
                    "program_owner_key",
                    "asset_id",
                    "version_id",
                    "approval_reference",
                )
            },
            supersedes_binding_id=binding.id if operation != "replay" else None,
        )
        if operation == "replace":
            asset_id, version_id = uuid4(), uuid4()
            state.database.add(
                MediaAsset(
                    id=asset_id,
                    tenant_id=state.pack.tenant_id,
                    owner_person_id=state.person_id,
                    purpose="video",
                    state="ready",
                )
            )
            state.database.flush()
            state.database.add(
                MediaVersion(
                    id=version_id,
                    asset_id=asset_id,
                    tenant_id=state.pack.tenant_id,
                    version_number=1,
                    purpose="video",
                    state="ready",
                    content_type="video/mp4",
                    declared_bytes=100,
                    actual_bytes=100,
                    object_key=f"tenants/{state.pack.tenant_id}/media/video/{asset_id}/{version_id}/original",
                )
            )
            state.database.flush()
            request = request.model_copy(update={"asset_id": asset_id, "version_id": version_id})
        with pytest.raises(MediaForbidden, match="dedicated demonstration"):
            state.app.service.bind_activity_media(
                state.database,
                actor,
                request,
                idempotency_key=binding.idempotency_key if operation == "replay" else "reapprove",
            )
        assert count(state.database, ActivityMediaBinding) == 2
        assert count(state.database, AuditEvent) == 1
        assert binding.state == "approved"


async def test_requires_explicit_outer_transaction(state):
    with pytest.raises(MediaForbidden, match="caller-owned"):
        await state.app.apply(
            session_token=TOKEN,
            command_id=state.command_id,
            expected_program_version_id=state.app.catalog.program_version_id,
            reason="Approved demo",
        )


async def test_expiry_during_processor_validation_cannot_advance_ready(state, monkeypatch):
    original = state.app.service.processor.process

    def process(**kwargs):
        result = original(**kwargs)
        state.database.get(IdentitySession, state.session_id).expires_at = datetime.now(
            UTC
        ) - timedelta(seconds=1)
        return result

    monkeypatch.setattr(state.app.service.processor, "process", process)
    with pytest.raises(MediaForbidden):
        await apply(state)
    with state.database.begin():
        assert count(state.database, MediaVersion) == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", uuid4()),
        ("owner_key", uuid4()),
        ("program_id", uuid4()),
        ("module_id", uuid4()),
        ("title", "Unreviewed content"),
        ("prompt", "Changed prompt"),
        ("is_required", True),
        ("position", 5),
    ],
)
async def test_catalog_matcher_refuses_changed_identity_or_presentation(state, field, value):
    await apply(state)
    with state.database.begin():
        actual = state.database.get(Activity, state.app.catalog.activity_ids[0])
        version = state.database.get(ProgramVersion, state.app.catalog.program_version_id)
        row = SimpleNamespace(
            **{column.name: getattr(actual, column.name) for column in Activity.__table__.columns}
        )
        setattr(row, field, value)
        assert not state.app.catalog.matches_catalog(row, version)


async def test_catalog_matcher_retains_immutable_superseded_version_across_releases(state):
    await apply(state)
    with state.database.begin():
        activity = state.database.get(Activity, state.app.catalog.activity_ids[0])
        actual = state.database.get(ProgramVersion, state.app.catalog.program_version_id)
        version = SimpleNamespace(
            **{
                column.name: getattr(actual, column.name)
                for column in ProgramVersion.__table__.columns
            }
        )
        version.status = "superseded"
        assert state.app.catalog.matches_catalog(activity, version)
        assert public_film_catalog(replace(state.pack, release_id="b" * 40)) == state.app.catalog
        version.content_source_ref = "unreviewed"
        assert not state.app.catalog.matches_catalog(activity, version)


@pytest.fixture
def cli_state(state, public_artifact, monkeypatch):
    from pydantic import SecretStr
    from sqlalchemy import ext

    from ac_platform.application import settings as settings_module
    from ac_platform.authorization import cli as auth_cli

    settings = SimpleNamespace(
        environment="test",
        release_id=RELEASE,
        database_url="sqlite://explicit-test-adapter",
        media_public_films_delivery_enabled=True,
        media_public_films_root=str(public_artifact.root),
        public_learner_tenant_id=state.pack.tenant_id,
        session_token_pepper=SecretStr(PEPPER),
    )
    calls = []

    class Engine:
        async def dispose(self):
            calls.append("disposed")

    class Scope:
        async def __aenter__(self):
            return state.facade

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(settings_module, "Settings", lambda **kwargs: settings)
    monkeypatch.setattr(ext.asyncio, "create_async_engine", lambda *args, **kwargs: Engine())
    monkeypatch.setattr(ext.asyncio, "async_sessionmaker", lambda *args, **kwargs: Scope)
    monkeypatch.setattr(auth_cli, "_read_session_token", lambda: TOKEN)
    monkeypatch.setenv("AC_ENVIRONMENT", "test")
    monkeypatch.setenv("AC_RELEASE_ID", RELEASE)
    monkeypatch.setenv("AC_DATABASE_URL", "sqlite://explicit-test-adapter")
    args = [
        "--environment",
        "test",
        "--release-id",
        RELEASE,
        "--tenant-id",
        str(state.pack.tenant_id),
        "--catalog-version-id",
        str(state.app.catalog.program_version_id),
        "--manifest-sha256",
        state.pack.manifest_sha256,
        "--command-id",
        str(state.command_id),
        "--reason",
        "Explicit licensed demonstration approval",
        "--acknowledge-public-film-demonstration",
    ]
    return SimpleNamespace(state=state, settings=settings, args=args, calls=calls)


def test_cli_uses_hidden_canonical_session_and_reports_only_after_commit(cli_state, capsys):
    assert main(cli_state.args) == 0
    assert cli_state.calls == ["disposed"]
    output = capsys.readouterr()
    assert not output.err and TOKEN not in output.out and PEPPER not in output.out
    assert json.loads(output.out)["status"] == "imported"
    with cli_state.state.database.begin():
        assert cli_state.state.database.get(AuditEvent, cli_state.state.command_id) is not None


@pytest.mark.parametrize(
    "failure", ["ack", "environment", "release", "tenant", "manifest", "disabled", "token-argument"]
)
def test_cli_fails_before_database_for_unacknowledged_or_foreign_configuration(
    cli_state, monkeypatch, capsys, failure
):
    args = cli_state.args.copy()
    if failure == "ack":
        args.remove("--acknowledge-public-film-demonstration")
    if failure == "environment":
        monkeypatch.setenv("AC_ENVIRONMENT", "production")
    if failure == "release":
        monkeypatch.setenv("AC_RELEASE_ID", "b" * 40)
    if failure == "tenant":
        cli_state.settings.public_learner_tenant_id = uuid4()
    if failure == "manifest":
        args[args.index("--manifest-sha256") + 1] = "b" * 64
    if failure == "disabled":
        cli_state.settings.media_public_films_delivery_enabled = False
    if failure == "token-argument":
        args.extend(["--session-token", TOKEN])
    assert main(args) == 2
    assert not cli_state.calls
    output = capsys.readouterr()
    assert not output.out and TOKEN not in output.err


def test_cli_commit_failure_cannot_emit_success(cli_state, monkeypatch, capsys):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fail_commit():
        with cli_state.state.database.begin():
            yield
            raise MediaConflict("synthetic commit failure with secret-like content " + TOKEN)

    monkeypatch.setattr(cli_state.state.facade, "begin", fail_commit)
    assert main(cli_state.args) == 2
    output = capsys.readouterr()
    assert not output.out and TOKEN not in output.err
    with cli_state.state.database.begin():
        assert count(cli_state.state.database, Program) == 0
