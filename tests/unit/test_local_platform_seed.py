"""Disposable setup guards and real relational identity behavior."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from ac_platform.application.settings import Settings
from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain_sync
from ac_platform.authorization.application import CapabilityApplication
from ac_platform.authorization.models import CapabilityGrant
from ac_platform.authorization.policy import CapabilityDenied
from ac_platform.authorization.studio import StudioAuthorization
from ac_platform.catalog.models import Program, ProgramVersion
from ac_platform.catalog.services import AsyncCatalogApplication, CatalogAccessDeniedError
from ac_platform.db.models import model_metadata
from ac_platform.development.seed import (
    ACADEMY_TENANT,
    ACCOUNTS,
    CONSENT_VERSION,
    OPERATIONS_TENANT,
    STUDIO_PROGRAM,
    STUDIO_VERSION,
    require_local_target,
    seed_accounts,
    seed_local_access,
)
from ac_platform.enrollment.models import (
    Enrollment,
    EnrollmentEligibilityFact,
    EnrollmentProvenance,
    Entitlement,
)
from ac_platform.enrollment.self_attestation import (
    AsyncSelfAttestedEligibilityApplication,
    SelfAttestedEligibilityDenied,
)
from ac_platform.identity.application import AsyncIdentityApplication
from ac_platform.identity.models import EmailChallenge, Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.identity.password_auth import InvalidPasswordCredentials, PasswordIdentityService
from ac_platform.kernel.authz import ActorContext
from ac_platform.seed.application import StagingSeedApplication
from ac_platform.seed.technical_media_fixture_v2 import (
    technical_media_identity,
    technical_media_seed,
)
from ac_platform.tenancy.models import Membership
from tests.unit.authorization.test_capability_application import AwaitableSession

PASSWORD = "test-fixture-password-only"  # noqa: S105 - isolated test input
SECRET = "test-fixture-email-key-at-least-32-bytes"  # noqa: S105 - isolated test input


class LocalSession(AwaitableSession):
    def add_all(self, rows):
        self.database.add_all(rows)

    @asynccontextmanager
    async def begin(self):
        with self.database.begin():
            yield

    @asynccontextmanager
    async def begin_nested(self):
        with self.database.begin_nested():
            yield

    async def run_sync(self, operation):
        return operation(self.database)


@pytest.fixture
def empty_database():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    model_metadata().create_all(engine)
    with Session(engine, expire_on_commit=False) as database, database.begin():
        yield SimpleNamespace(db=database, adapter=LocalSession(database))
    engine.dispose()


def local_settings(**updates):
    # CI runs with AC_ENVIRONMENT=test and its own database/provider settings.
    # This fixture exercises the local boundary, never the ambient environment.
    return Settings(
        _env_file=None,
        environment="local",
        external_side_effects_hold=True,
        email_provider="fake",
        media_provider_enabled=False,
        google_oauth_client_id=None,
        google_oauth_client_secret=None,
    ).model_copy(
        update={
            "database_url": "postgresql+psycopg://ac_runtime:unused@127.0.0.1:55432/ac_local_sandbox",
            **updates,
        }
    )


def test_local_fixture_is_independent_of_ci_environment(monkeypatch):
    monkeypatch.setenv("AC_ENVIRONMENT", "test")
    assert local_settings().environment == "local"
    require_local_target(local_settings(), acknowledged=True)


def test_exact_local_target_requires_acknowledgement():
    require_local_target(local_settings(), acknowledged=True)
    with pytest.raises(ValueError):
        require_local_target(local_settings(), acknowledged=False)


@pytest.mark.parametrize(
    "updates",
    [
        {"environment": "production"},
        {"environment": "staging"},
        {"external_side_effects_hold": False},
        {"email_provider": "resend"},
        {"media_provider_enabled": True},
        {"database_url": "postgresql+psycopg://ac_runtime@db.remote:55432/ac_platform"},
        {"database_url": "postgresql+psycopg://ac_runtime@127.0.0.1:5432/ac_platform"},
        {"database_url": "postgresql+psycopg://ac_runtime@127.0.0.1:55432/other"},
        {"database_url": "postgresql+psycopg://ac_owner@127.0.0.1:55432/ac_platform"},
        {"database_url": "postgresql+psycopg://ac_runtime@127.0.0.1:55432/ac_platform?host=remote"},
    ],
)
def test_unsafe_targets_rejected_before_database_connection(updates):
    with pytest.raises(ValueError):
        require_local_target(local_settings(**updates), acknowledged=True)


@pytest.mark.parametrize("name", ["PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS"])
def test_libpq_overrides_cannot_redirect_the_local_seed(monkeypatch, name):
    monkeypatch.setenv(name, "untrusted-override")
    with pytest.raises(ValueError):
        require_local_target(local_settings(), acknowledged=True)


async def test_seed_exercises_password_verification_without_creating_browser_sessions(
    empty_database,
):
    state = empty_database
    ids = await seed_accounts(state.adapter, password=PASSWORD, secret=SECRET)
    assert set(ids) == set(ACCOUNTS)
    assert state.db.scalar(select(func.count()).select_from(Person)) == 3
    assert state.db.scalar(select(func.count()).select_from(IdentitySession)) == 0
    assert all(row.consumed_at for row in state.db.scalars(select(EmailChallenge)))
    identity = PasswordIdentityService(state.adapter, token_secret=SECRET)
    for kind, email in ACCOUNTS.items():
        assert (await identity.authenticate(email=email, password=PASSWORD)).id == ids[kind]
    assert state.db.get(Membership, (ACADEMY_TENANT, ids["coach"])).role == "learner"
    assert state.db.get(Membership, (OPERATIONS_TENANT, ids["admin"])).role == "owner"
    assert await seed_accounts(state.adapter, password=PASSWORD, secret=SECRET) == ids
    assert state.db.scalar(select(func.count()).select_from(EmailChallenge)) == 3


async def test_existing_non_fixture_people_are_never_repaired(empty_database):
    empty_database.db.add(Person(id=uuid4(), email="real@example.com"))
    empty_database.db.flush()
    with pytest.raises(ValueError, match="non-fixture"):
        await seed_accounts(empty_database.adapter, password=PASSWORD, secret=SECRET)
    assert empty_database.db.scalar(select(func.count()).select_from(Person)) == 1


async def test_changed_membership_is_not_silently_restored(empty_database):
    ids = await seed_accounts(empty_database.adapter, password=PASSWORD, secret=SECRET)
    empty_database.db.get(Membership, (ACADEMY_TENANT, ids["coach"])).role = "support"
    empty_database.db.flush()
    with pytest.raises(ValueError, match="assignment changed"):
        await seed_accounts(empty_database.adapter, password=PASSWORD, secret=SECRET)


@pytest.fixture
async def sandbox():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    model_metadata().create_all(engine)
    with Session(engine, expire_on_commit=False) as database:
        adapter = LocalSession(database)
        settings = local_settings(release_id="a" * 40)
        with database.begin():
            ids = await seed_accounts(adapter, password=PASSWORD, secret=SECRET)
        await StagingSeedApplication(
            adapter, environment="test", expected_release_id=settings.release_id
        ).apply_technical_validation(
            technical_media_seed(settings.release_id),
            actor=ActorContext(ids["admin"], uuid4(), None),
        )
        yield SimpleNamespace(db=database, adapter=adapter, settings=settings, ids=ids)
    engine.dispose()


async def apply_access(state, **overrides):
    with state.db.begin():
        await seed_local_access(
            state.adapter,
            settings=state.settings,
            ids=state.ids,
            password=overrides.get("password", PASSWORD),
        )


async def test_fixture_access_uses_audited_canonical_grants_and_revokes_setup_session(sandbox):
    await apply_access(sandbox)
    state = sandbox
    with state.db.begin():
        films, version, _, _ = technical_media_identity(state.settings.release_id)
        enrollments = tuple(state.db.scalars(select(Enrollment)))
        assert len(enrollments) == 2
        assert {row.person_id for row in enrollments} == {state.ids["learner"], state.ids["coach"]}
        assert all(
            row.source == "manual_grant" and row.program_version_id == version
            for row in enrollments
        )
        facts = tuple(state.db.scalars(select(EnrollmentEligibilityFact)))
        assert len(facts) == 2 and all(row.evidence["synthetic"] is True for row in facts)
        provenances = tuple(state.db.scalars(select(EnrollmentProvenance)))
        assert len(provenances) == 2
        assert all(row.actor_person_id == state.ids["admin"] for row in provenances)
        assert all("Synthetic localhost" in row.reason for row in provenances)
        sessions = tuple(state.db.scalars(select(IdentitySession)))
        assert len(sessions) == 1 and sessions[0].revoked_at is not None
        assert sessions[0].selected_tenant_id == ACADEMY_TENANT
        assert state.db.get(Membership, (ACADEMY_TENANT, state.ids["coach"])).role == "learner"
        assert state.db.get(Program, STUDIO_PROGRAM).scope == "tenant"
        draft = state.db.get(ProgramVersion, STUDIO_VERSION)
        assert draft.status == "draft" and draft.content_reviewed_by is None
        grants = tuple(state.db.scalars(select(CapabilityGrant)))
        assert len(grants) == 4
        coach_grants = [row for row in grants if row.subject_person_id == state.ids["coach"]]
        assert {row.permission for row in coach_grants} == {
            "catalog_read",
            "catalog_write",
            "catalog_publish",
        }
        assert all(
            row.scope_kind == "program" and row.program_id == STUDIO_PROGRAM for row in coach_grants
        )
        actor = ActorContext(state.ids["coach"], uuid4(), ACADEMY_TENANT)
        authorization = StudioAuthorization(state.adapter)
        for permission in ("catalog_read", "catalog_write", "catalog_publish"):
            await authorization.require(actor, permission, program_id=STUDIO_PROGRAM)
            with pytest.raises(CapabilityDenied):
                await authorization.require(actor, permission)
            with pytest.raises(CapabilityDenied):
                await authorization.require(actor, permission, program_id=films)
        with pytest.raises(CatalogAccessDeniedError):
            await AsyncCatalogApplication(state.adapter).create_program(
                actor=actor, tenant_id=ACADEMY_TENANT, slug="not-allowed", title="Not allowed"
            )
        session_audits = tuple(
            state.db.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "local.synthetic_film_enrollment_created"
                )
            )
        )
        assert len(session_audits) == 2
        assert all(row.session_id == sessions[0].id for row in session_audits)
        assert verify_audit_chain_sync(state.db, ACADEMY_TENANT).valid
        assert verify_audit_chain_sync(state.db, OPERATIONS_TENANT).valid


async def test_fixture_replay_preserves_ui_edits_without_duplicate_access(sandbox):
    await apply_access(sandbox)
    with sandbox.db.begin():
        sandbox.db.get(Program, STUDIO_PROGRAM).title = "Coach edited this title"
        before = tuple(
            sandbox.db.scalar(select(func.count()).select_from(model))
            for model in (Enrollment, EnrollmentEligibilityFact, CapabilityGrant, AuditEvent)
        )
    await apply_access(sandbox)
    with sandbox.db.begin():
        assert sandbox.db.get(Program, STUDIO_PROGRAM).title == "Coach edited this title"
        assert before == tuple(
            sandbox.db.scalar(select(func.count()).select_from(model))
            for model in (Enrollment, EnrollmentEligibilityFact, CapabilityGrant, AuditEvent)
        )
        assert all(row.revoked_at for row in sandbox.db.scalars(select(IdentitySession)))


async def test_bad_setup_credentials_roll_back_bootstrap_and_all_access(sandbox):
    with pytest.raises(InvalidPasswordCredentials):
        await apply_access(sandbox, password="wrong-local-fixture-password")  # noqa: S106
    with sandbox.db.begin():
        for model in (CapabilityGrant, Enrollment, EnrollmentEligibilityFact, IdentitySession):
            assert sandbox.db.scalar(select(func.count()).select_from(model)) == 0
        assert sandbox.db.get(Program, STUDIO_PROGRAM) is None


@pytest.mark.parametrize("change", ["ids", "account", "admin_membership"])
async def test_changed_fixture_scope_is_rejected_without_new_access(sandbox, change):
    with sandbox.db.begin():
        if change == "ids":
            sandbox.ids = {**sandbox.ids, "learner": sandbox.ids["admin"]}
        elif change == "account":
            sandbox.db.get(Person, sandbox.ids["coach"]).consent_version = "not-a-fixture"
        else:
            sandbox.db.get(Membership, (ACADEMY_TENANT, sandbox.ids["admin"])).role = "learner"
    with pytest.raises((ValueError, CapabilityDenied)):
        await apply_access(sandbox)
    with sandbox.db.begin():
        assert sandbox.db.scalar(select(func.count()).select_from(Enrollment)) == 0
        assert sandbox.db.scalar(select(func.count()).select_from(CapabilityGrant)) == 0


async def test_revoked_coach_grant_is_never_restored(sandbox):
    await apply_access(sandbox)
    with sandbox.db.begin():
        identity = AsyncIdentityApplication(
            sandbox.adapter, token_pepper=sandbox.settings.session_token_pepper.get_secret_value()
        )
        issued = await identity.issue_authenticated_session(sandbox.ids["admin"])
        actor = (await identity.select_tenant(issued.token, ACADEMY_TENANT)).actor
        grant = sandbox.db.scalar(
            select(CapabilityGrant).where(
                CapabilityGrant.subject_person_id == sandbox.ids["coach"],
                CapabilityGrant.permission == "catalog_write",
            )
        )
        await CapabilityApplication(sandbox.adapter, operations_tenant_id=OPERATIONS_TENANT).revoke(
            actor, grant_id=grant.id, command_id=uuid4(), reason="Local test revocation"
        )
        await identity.revoke_self(issued.token, issued.metadata.id)
    with pytest.raises(ValueError, match="revoked"):
        await apply_access(sandbox)
    with sandbox.db.begin():
        actor = ActorContext(sandbox.ids["coach"], uuid4(), ACADEMY_TENANT)
        with pytest.raises(CapabilityDenied):
            await StudioAuthorization(sandbox.adapter).require(
                actor, "catalog_write", program_id=STUDIO_PROGRAM
            )
        assert all(row.revoked_at for row in sandbox.db.scalars(select(IdentitySession)))


async def test_changed_eligibility_is_not_overwritten(sandbox):
    await apply_access(sandbox)
    with sandbox.db.begin():
        fact = sandbox.db.scalar(select(EnrollmentEligibilityFact))
        fact.eligibility_passed = False
    with pytest.raises(ValueError, match="eligibility changed"):
        await apply_access(sandbox)


async def test_missing_published_films_cannot_create_fixture_access(empty_database):
    ids = await seed_accounts(empty_database.adapter, password=PASSWORD, secret=SECRET)
    with pytest.raises(ValueError, match="exact published"):
        await seed_local_access(
            empty_database.adapter,
            settings=local_settings(release_id="a" * 40),
            ids=ids,
            password=PASSWORD,
        )
    assert empty_database.db.scalar(select(func.count()).select_from(CapabilityGrant)) == 0


async def test_synthetic_facts_do_not_open_public_self_attestation_for_films(sandbox):
    await apply_access(sandbox)
    with sandbox.db.begin():
        version_id = technical_media_identity(sandbox.settings.release_id)[1]
        with pytest.raises(SelfAttestedEligibilityDenied, match="limited to the published"):
            await AsyncSelfAttestedEligibilityApplication(sandbox.adapter).ensure(
                person_id=sandbox.ids["learner"],
                tenant_id=ACADEMY_TENANT,
                program_version_id=version_id,
                required_consent_version=CONSENT_VERSION,
            )


@pytest.mark.parametrize("model", [Enrollment, Entitlement])
async def test_revoked_fixture_access_stays_revoked_on_replay(sandbox, model):
    await apply_access(sandbox)
    with sandbox.db.begin():
        # Existing revoked-state test fixture, not an operational recovery action.
        row = sandbox.db.scalar(select(model))
        row.status = "revoked"
        row_id = row.id
    with pytest.raises(ValueError, match="access was revoked"):
        await apply_access(sandbox)
    with sandbox.db.begin():
        assert sandbox.db.get(model, row_id).status == "revoked"
        assert sandbox.db.scalar(select(func.count()).select_from(model)) == 2
        assert all(row.revoked_at for row in sandbox.db.scalars(select(IdentitySession)))
