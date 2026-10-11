from __future__ import annotations

import importlib.util
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import (
    CheckConstraint,
    Engine,
    bindparam,
    create_engine,
    event,
    inspect,
    update,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.schema import CreateTable

from ac_platform.db.models import model_metadata
from ac_platform.identity.models import (
    AuthenticationReplay,
    DeletionRequest,
    Person,
    ProviderAuthorizationTransaction,
    ProviderIdentity,
    Session,
)
from ac_platform.identity.repositories import SqlAlchemyIdentityStore
from ac_platform.identity.services import (
    PersonSnapshot,
    ProviderAuthorizationTransactionStatus,
    ProviderAuthorizationType,
    SessionRevisionConflictError,
    SessionService,
    issue_provider_authorization,
)
from ac_platform.tenancy.models import Membership, Tenant


@pytest.fixture()
def database() -> Engine:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    # Load the complete registry even when this module is collected in isolation.
    metadata = model_metadata()
    metadata.create_all(engine)
    try:
        yield engine
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        metadata.drop_all(engine)
        engine.dispose()


def _migration_module() -> ModuleType:
    root = Path(__file__).resolve().parents[2]
    path = root / "db" / "migrations" / "versions" / "20260830_0001_identity_tenancy.py"
    specification = importlib.util.spec_from_file_location("identity_tenancy_migration", path)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_migration_is_forward_only_with_expected_revision() -> None:
    migration = _migration_module()

    assert migration.revision == "20260830_0001"
    assert migration.down_revision is None
    with pytest.raises(RuntimeError):
        migration.downgrade()


def test_migration_upgrade_builds_the_identity_tenancy_schema() -> None:
    engine = create_engine("sqlite:///:memory:")
    migration = _migration_module()
    try:
        with engine.begin() as connection:
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
        assert {
            "authentication_replays",
            "provider_authorization_transactions",
            "persons",
            "provider_identities",
            "sessions",
            "deletion_requests",
            "tenants",
            "memberships",
        }.issubset(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_migration_columns_match_identity_tenancy_models() -> None:
    engine = create_engine("sqlite:///:memory:")
    migration = _migration_module()
    models = (
        Person,
        ProviderIdentity,
        Session,
        DeletionRequest,
        Tenant,
        Membership,
        AuthenticationReplay,
        ProviderAuthorizationTransaction,
    )
    try:
        with engine.begin() as connection:
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
        inspector = inspect(engine)
        for model in models:
            actual = {
                column["name"]: column for column in inspector.get_columns(model.__tablename__)
            }
            expected = set(model.__table__.columns.keys())
            if model is Person:
                # Revision 0001 owns only the original identity columns. Later
                # identity migrations are verified against the current model by
                # the registry and fresh-PostgreSQL migration suites.
                expected -= {
                    "first_name",
                    "whatsapp_number",
                    "consent_version",
                    "consented_at",
                    "experience_context",
                    "learning_goal",
                    "practice_situation",
                    "weekly_minutes",
                    "onboarding_status",
                    "onboarding_step",
                    "onboarding_revision",
                }
            if model is Session:
                # The reviewer audience is introduced at0038, not in this
                # deliberately isolated0001 migration proof.
                expected -= {"audience"}
            assert set(actual) == expected, model.__tablename__
            for column in model.__table__.columns:
                if column.name not in expected:
                    continue
                assert actual[column.name]["nullable"] is column.nullable, (
                    model.__tablename__,
                    column.name,
                )
            expected_checks = {
                constraint.name
                for constraint in model.__table__.constraints
                if isinstance(constraint, CheckConstraint)
            }
            if model is Person:
                expected_checks -= {
                    "ck_persons_first_name_nonblank",
                    "ck_persons_whatsapp_number_min_length",
                    "ck_persons_consent_version_nonblank",
                    "ck_persons_experience_context_nonblank",
                    "ck_persons_learning_goal_nonblank",
                    "ck_persons_practice_situation_nonblank",
                    "ck_persons_weekly_minutes_bounds",
                    "ck_persons_onboarding_status",
                    "ck_persons_onboarding_step_bounds",
                    "ck_persons_onboarding_revision_nonnegative",
                    "ck_persons_onboarding_completed_fields",
                }
            if model is Session:
                expected_checks -= {
                    "ck_sessions_audience_supported",
                    "ck_sessions_reviewer_session_unscoped",
                }
            actual_checks = {
                constraint["name"]
                for constraint in inspector.get_check_constraints(model.__tablename__)
            }
            assert actual_checks == expected_checks, model.__tablename__
    finally:
        engine.dispose()


def test_identity_tenancy_schema_has_named_constraints_and_expected_tables(
    database: Engine,
) -> None:
    inspector = inspect(database)
    assert {
        "authentication_replays",
        "provider_authorization_transactions",
        "persons",
        "provider_identities",
        "sessions",
        "deletion_requests",
        "tenants",
        "memberships",
    }.issubset(inspector.get_table_names())
    assert "uq_provider_identities_issuer_subject" in {
        constraint["name"] for constraint in inspector.get_unique_constraints("provider_identities")
    }
    assert inspector.get_pk_constraint("memberships")["name"] == "pk_memberships"
    assert "fk_sessions_selected_membership" in {
        foreign_key["name"] for foreign_key in inspector.get_foreign_keys("sessions")
    }
    assert {"revision"}.issubset({column["name"] for column in inspector.get_columns("sessions")})
    assert {"revision"}.issubset(
        {column["name"] for column in inspector.get_columns("memberships")}
    )
    assert "ck_deletion_requests_status_timestamps" in {
        constraint["name"] for constraint in inspector.get_check_constraints("deletion_requests")
    }


def test_provider_authorization_transaction_consumption_rolls_back(database: Engine) -> None:
    issued_at = datetime(2026, 8, 30, 12, tzinfo=UTC)
    with DbSession(database) as session:
        store = SqlAlchemyIdentityStore(session)
        issued = issue_provider_authorization(
            store,
            authorization_type=ProviderAuthorizationType.AUTHENTICATE,
            audience="authority-closers-web",
            issued_at=issued_at,
            expires_in=timedelta(minutes=10),
        )
        session.commit()

    with DbSession(database) as session:
        store = SqlAlchemyIdentityStore(session)
        transaction = store.get_provider_authorization_transaction_for_update(issued.transaction_id)
        assert transaction is not None
        assert store.consume_provider_authorization_transaction(
            issued.transaction_id, consumed_at=issued_at
        )
        session.rollback()

    with DbSession(database) as session:
        store = SqlAlchemyIdentityStore(session)
        transaction = store.get_provider_authorization_transaction_for_update(issued.transaction_id)
        assert transaction is not None
        assert transaction.status is ProviderAuthorizationTransactionStatus.ISSUED
        assert transaction.consumed_at is None


def test_provider_identity_key_and_open_deletion_request_are_unique(database: Engine) -> None:
    person_id = uuid4()
    with database.begin() as connection:
        connection.execute(Person.__table__.insert().values(id=person_id))
        connection.execute(
            ProviderIdentity.__table__.insert().values(
                id=uuid4(),
                person_id=person_id,
                issuer="https://issuer.example",
                subject="subject-1",
            )
        )

    with pytest.raises(IntegrityError), database.begin() as connection:
        connection.execute(
            ProviderIdentity.__table__.insert().values(
                id=uuid4(),
                person_id=person_id,
                issuer="https://issuer.example",
                subject="subject-1",
            )
        )

    with database.begin() as connection:
        connection.execute(
            DeletionRequest.__table__.insert().values(id=uuid4(), person_id=person_id)
        )
    with pytest.raises(IntegrityError), database.begin() as connection:
        connection.execute(
            DeletionRequest.__table__.insert().values(id=uuid4(), person_id=person_id)
        )


def test_composite_tenant_foreign_keys_deny_cross_tenant_relationships(database: Engine) -> None:
    person_a = uuid4()
    person_b = uuid4()
    tenant_a = uuid4()
    with database.begin() as connection:
        connection.execute(Person.__table__.insert().values(id=person_a))
        connection.execute(Person.__table__.insert().values(id=person_b))
        connection.execute(
            Tenant.__table__.insert().values(id=tenant_a, slug="tenant-a", name="Tenant A")
        )
        connection.execute(
            Membership.__table__.insert().values(
                tenant_id=tenant_a,
                person_id=person_a,
            )
        )
        connection.execute(
            Session.__table__.insert().values(
                id=uuid4(),
                person_id=person_a,
                token_hash=b"a" * 32,
                created_at=datetime(2026, 8, 30, 12, tzinfo=UTC),
                expires_at=datetime(2026, 8, 30, 13, tzinfo=UTC),
                selected_tenant_id=tenant_a,
            )
        )

    with pytest.raises(IntegrityError), database.begin() as connection:
        connection.execute(
            Session.__table__.insert().values(
                id=uuid4(),
                person_id=person_b,
                token_hash=b"b" * 32,
                created_at=datetime(2026, 8, 30, 12, tzinfo=UTC),
                expires_at=datetime(2026, 8, 30, 13, tzinfo=UTC),
                selected_tenant_id=tenant_a,
            )
        )

    with pytest.raises(IntegrityError), database.begin() as connection:
        connection.execute(
            DeletionRequest.__table__.insert().values(
                id=uuid4(),
                person_id=person_b,
                tenant_id=tenant_a,
            )
        )


def test_membership_composite_primary_key_denies_duplicate_person_in_same_tenant(
    database: Engine,
) -> None:
    person_id = uuid4()
    tenant_id = uuid4()
    with database.begin() as connection:
        connection.execute(Person.__table__.insert().values(id=person_id))
        connection.execute(
            Tenant.__table__.insert().values(id=tenant_id, slug="tenant-a", name="Tenant A")
        )
        membership_values = {"tenant_id": tenant_id, "person_id": person_id}
        connection.execute(Membership.__table__.insert().values(**membership_values))

    with pytest.raises(IntegrityError), database.begin() as connection:
        connection.execute(Membership.__table__.insert().values(**membership_values))


def test_durable_replay_key_is_atomic_and_never_reusable(database: Engine) -> None:
    person_id = uuid4()
    expiry = datetime(2026, 8, 30, 13, tzinfo=UTC)
    with DbSession(database) as session:
        session.add(Person(id=person_id))
        store = SqlAlchemyIdentityStore(session)
        consumed_at = datetime(2026, 8, 30, 12, tzinfo=UTC)
        assert store.consume_replay_key(
            "provider-assertion:v1:test",
            consumed_at=consumed_at,
            expires_at=expiry,
        )
        assert not store.consume_replay_key(
            "provider-assertion:v1:test",
            consumed_at=consumed_at,
            expires_at=expiry,
        )
        session.commit()

    with database.begin() as connection:
        assert (
            connection.execute(AuthenticationReplay.__table__.select()).one().replay_key
            == "provider-assertion:v1:test"
        )


def test_session_cas_preserves_revocation_from_a_stale_authentication_snapshot(
    database: Engine,
) -> None:
    person_id = uuid4()
    with DbSession(database) as session:
        store = SqlAlchemyIdentityStore(session)
        store.save_person(
            PersonSnapshot(
                id=person_id,
                email="learner@authorityclosers.com",
                email_verified_at=datetime(2026, 8, 30, 12, tzinfo=UTC),
            )
        )
        sessions = SessionService(store, token_pepper=b"p" * 32)
        issued = sessions.issue(person_id, now=datetime(2026, 8, 30, 12, tzinfo=UTC))
        session.commit()

        stale = store.get_session(issued.metadata.id)
        assert stale is not None
        store.save_session(
            replace(
                stale,
                revoked_at=datetime(2026, 8, 30, 12, 1, tzinfo=UTC),
                revision=stale.revision + 1,
            )
        )
        session.commit()

        with pytest.raises(SessionRevisionConflictError):
            store.save_session(
                replace(
                    stale,
                    last_seen_at=datetime(2026, 8, 30, 12, 2, tzinfo=UTC),
                    revision=stale.revision + 1,
                )
            )
        current = store.get_session(issued.metadata.id)
        assert current is not None and current.revoked_at is not None


def test_identity_session_cas_sql_compiles_for_postgresql() -> None:
    statement = (
        update(Session)
        .where(
            Session.id == bindparam("session_id"),
            Session.revision == bindparam("expected_revision"),
        )
        .values(
            last_seen_at=bindparam("last_seen_at"),
            revision=bindparam("next_revision"),
        )
    )
    sql = str(statement.compile(dialect=postgresql.dialect()))
    ddl = str(CreateTable(Session.__table__).compile(dialect=postgresql.dialect()))

    assert "UPDATE sessions" in sql
    assert "revision" in sql
    assert "expected_revision" in sql
    assert "revision INTEGER" in ddl
    assert "CONSTRAINT ck_sessions_revision_nonnegative" in ddl


@pytest.mark.parametrize(
    ("status", "cancelled_at", "completed_at"),
    [
        ("requested", datetime(2026, 8, 30, 12, tzinfo=UTC), None),
        ("processing", None, datetime(2026, 8, 30, 12, tzinfo=UTC)),
        ("cancelled", None, None),
        ("completed", None, None),
        (
            "completed",
            datetime(2026, 8, 30, 12, tzinfo=UTC),
            datetime(2026, 8, 30, 12, tzinfo=UTC),
        ),
        ("cancelled", datetime(2026, 8, 30, 10, tzinfo=UTC), None),
        ("completed", None, datetime(2026, 8, 30, 10, tzinfo=UTC)),
    ],
)
def test_deletion_request_database_rejects_impossible_lifecycle_states(
    database: Engine,
    status: str,
    cancelled_at: datetime | None,
    completed_at: datetime | None,
) -> None:
    person_id = uuid4()
    with database.begin() as connection:
        connection.execute(Person.__table__.insert().values(id=person_id))
    with pytest.raises(IntegrityError), database.begin() as connection:
        connection.execute(
            DeletionRequest.__table__.insert().values(
                id=uuid4(),
                person_id=person_id,
                status=status,
                requested_at=datetime(2026, 8, 30, 11, tzinfo=UTC),
                cancelled_at=cancelled_at,
                completed_at=completed_at,
            )
        )


@pytest.mark.parametrize(
    ("status", "cancelled_at", "completed_at"),
    [
        ("requested", None, None),
        ("processing", None, None),
        ("cancelled", datetime(2026, 8, 30, 12, tzinfo=UTC), None),
        ("completed", None, datetime(2026, 8, 30, 12, tzinfo=UTC)),
    ],
)
def test_deletion_request_database_accepts_exact_lifecycle_states(
    database: Engine,
    status: str,
    cancelled_at: datetime | None,
    completed_at: datetime | None,
) -> None:
    person_id = uuid4()
    with database.begin() as connection:
        connection.execute(Person.__table__.insert().values(id=person_id))
        connection.execute(
            DeletionRequest.__table__.insert().values(
                id=uuid4(),
                person_id=person_id,
                status=status,
                requested_at=datetime(2026, 8, 30, 11, tzinfo=UTC),
                cancelled_at=cancelled_at,
                completed_at=completed_at,
            )
        )


def test_session_token_expiry_boundary_remains_exact(database: Engine) -> None:
    now = datetime(2026, 8, 30, 12, tzinfo=UTC)
    person_id = uuid4()
    with DbSession(database) as session:
        store = SqlAlchemyIdentityStore(session)
        store.save_person(
            PersonSnapshot(
                id=person_id,
                email="learner@authorityclosers.com",
                email_verified_at=now,
            )
        )
        service = SessionService(store, token_pepper=b"p" * 32)
        issued = service.issue(person_id, expires_in=timedelta(minutes=1), now=now)
        session.commit()
        assert issued.metadata.expires_at == now + timedelta(minutes=1)
