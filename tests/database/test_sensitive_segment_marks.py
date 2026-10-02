"""Sensitive-segment mark persistence: checks, ORM refusal, migration and PostgreSQL trigger."""

from __future__ import annotations

import runpy
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, delete, event, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from ac_platform.audit.models import AuditEvent
from ac_platform.authorization.models import PLATFORM_CAPABILITIES, CapabilityGrant
from ac_platform.conversation_intelligence.models import (
    ConversationPermission,
    ConversationRecording,
)
from ac_platform.conversation_intelligence.sensitive_segment_models import (
    ConversationSensitiveSegmentMark,
    SensitiveSegmentHistoryMutationError,
)
from ac_platform.db.models import model_metadata
from ac_platform.identity.models import Person
from ac_platform.tenancy.models import Membership, Tenant

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)
MIGRATION = (
    Path(__file__).parents[2] / "db/migrations/versions/20261002_0067_sensitive_segment_marks.py"
)


@dataclass(frozen=True)
class Fixture:
    tenant: UUID
    person: UUID
    recording: UUID


@pytest.fixture
def database() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection: object, _record: object) -> None:
        cursor = connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    model_metadata().create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def seed(database: Session) -> Fixture:
    fixture = Fixture(uuid4(), uuid4(), uuid4())
    database.add_all(
        [
            Tenant(id=fixture.tenant, slug=f"academy-{fixture.tenant}", name="Academy"),
            Person(id=fixture.person, email=f"operator-{fixture.person}@example.test"),
        ]
    )
    database.flush()
    database.add(Membership(tenant_id=fixture.tenant, person_id=fixture.person, role="learner"))
    database.flush()
    permission = uuid4()
    database.add(
        ConversationPermission(
            id=permission,
            tenant_id=fixture.tenant,
            person_id=fixture.person,
            source_sha256="0" * 64,
            provider="local",
            permission_reference="fixture",
            retention_reference="fixture",
            created_at=NOW,
            expires_at=NOW + timedelta(days=1),
            retention_until=NOW + timedelta(days=30),
        )
    )
    database.flush()
    database.add(
        ConversationRecording(
            id=fixture.recording,
            tenant_id=fixture.tenant,
            person_id=fixture.person,
            permission_id=permission,
            request_key="fixture",
            intent_sha256="1" * 64,
            source_sha256="0" * 64,
            source_bytes=1024,
            content_type="audio/mpeg",
            source_revision=1,
            generation=1,
            state="ready",
            created_at=NOW,
        )
    )
    database.commit()
    return fixture


def audit(database: Session, fixture: Fixture) -> UUID:
    prior = database.scalars(select(AuditEvent).where(AuditEvent.tenant_id == fixture.tenant)).all()
    row = AuditEvent(
        id=uuid4(),
        tenant_id=fixture.tenant,
        sequence_no=len(prior) + 1,
        actor_person_id=fixture.person,
        actor_type="person",
        action="conversation.sensitive_segment.mark",
        resource_type="conversation_sensitive_segment_mark",
        payload={},
        reason="AUT-520 fixture",
        previous_hash="0" * 64,
        event_hash="1" * 64,
    )
    database.add(row)
    database.flush()
    return row.id


def mark(
    database: Session, fixture: Fixture, **changes: object
) -> ConversationSensitiveSegmentMark:
    values: dict[str, object] = {
        "id": uuid4(),
        "tenant_id": fixture.tenant,
        "recording_id": fixture.recording,
        "transcript_revision": "rev-fictional",
        "segment_id": "s2",
        "category": "SENSITIVE_FINANCIAL",
        "action": "mark",
        "supersedes_mark_id": None,
        "source": "operator",
        "actor_person_id": fixture.person,
        "reason_ref": "AUT-520 fixture",
        "audit_event_id": audit(database, fixture),
        "created_at": NOW,
    }
    values.update(changes)
    return ConversationSensitiveSegmentMark(**values)


def test_models_build_and_a_release_supersedes_a_mark_once(database: Session) -> None:
    fixture = seed(database)
    original = mark(database, fixture)
    database.add(original)
    database.commit()
    release = mark(database, fixture, action="release", supersedes_mark_id=original.id)
    database.add(release)
    database.commit()
    database.add(mark(database, fixture, action="release", supersedes_mark_id=original.id))
    with pytest.raises(IntegrityError):
        database.flush()
    database.rollback()
    assert (
        database.scalar(
            select(ConversationSensitiveSegmentMark).where(
                ConversationSensitiveSegmentMark.supersedes_mark_id == original.id
            )
        ).id
        == release.id
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"category": "PERSONAL"},
        {"action": "erase"},
        {"source": "guess"},
        {"action": "release"},
        {"supersedes_mark_id": uuid4()},
        {"reason_ref": "x"},
        {"reason_ref": "A" * 81},
        {"segment_id": " "},
        {"transcript_revision": ""},
        {"recording_id": uuid4()},
        {"actor_person_id": uuid4()},
        {"audit_event_id": uuid4()},
    ],
)
def test_invalid_rows_are_database_rejected(database: Session, changes: dict[str, object]) -> None:
    fixture = seed(database)
    database.add(mark(database, fixture, **changes))
    with pytest.raises(IntegrityError):
        database.flush()


def test_audit_event_cannot_back_two_rows(database: Session) -> None:
    fixture = seed(database)
    original = mark(database, fixture)
    database.add(original)
    database.commit()
    database.add(mark(database, fixture, segment_id="s3", audit_event_id=original.audit_event_id))
    with pytest.raises(IntegrityError):
        database.flush()


def test_orm_cannot_rewrite_or_delete_history(database: Session) -> None:
    fixture = seed(database)
    row = mark(database, fixture)
    database.add(row)
    database.commit()
    row.reason_ref = "AUT-520 rewrite"
    with pytest.raises(SensitiveSegmentHistoryMutationError):
        database.flush()
    database.rollback()
    database.delete(row)
    with pytest.raises(SensitiveSegmentHistoryMutationError):
        database.flush()
    database.rollback()
    assert database.get(ConversationSensitiveSegmentMark, row.id).reason_ref == "AUT-520 fixture"


def test_migration_is_linked_forward_only_and_installs_the_trigger() -> None:
    migration = runpy.run_path(str(MIGRATION))
    assert migration["revision"] == "20261002_0067"
    assert migration["down_revision"] == "20261002_0066"
    with pytest.raises(RuntimeError, match="forward-only"):
        migration["downgrade"]()
    source = MIGRATION.read_text(encoding="utf-8")
    assert "BEFORE UPDATE OR DELETE" in source
    assert "prevent_conversation_command_mutation" in source
    assert source.count("'platform_content_safety_manage'") == 2
    assert "platform_content_safety_manage" in PLATFORM_CAPABILITIES


@pytest.fixture(scope="module")
def postgres() -> Iterator[Engine]:
    from tests.database.test_capability_grants_postgresql import _postgres_schema

    with _postgres_schema(current_application=True) as engine:
        yield engine


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_postgresql_sql_cannot_mutate_marks(postgres: Engine, operation: str) -> None:
    with Session(postgres) as session:
        fixture = seed(session)
        row = mark(session, fixture)
        session.add(row)
        session.commit()
        target = row.id
    table = ConversationSensitiveSegmentMark.__table__
    statement = (
        update(table).where(table.c.id == target).values(reason_ref="AUT-520 rewrite")
        if operation == "update"
        else delete(table).where(table.c.id == target)
    )
    with (
        pytest.raises(DBAPIError, match="conversation commands are append-only"),
        postgres.begin() as connection,
    ):
        connection.execute(statement)
    with postgres.connect() as connection:
        assert connection.scalar(select(table.c.id).where(table.c.id == target)) == target


@pytest.mark.parametrize("reason_ref", ["-AUT", "AUT 520 <b>", "AUT\n520"])
def test_postgresql_rejects_reason_refs_outside_the_pattern(
    postgres: Engine, reason_ref: str
) -> None:
    with Session(postgres) as session:
        fixture = seed(session)
        session.add(mark(session, fixture, reason_ref=reason_ref))
        with pytest.raises(IntegrityError, match="reason_ref_pattern"):
            session.flush()


def test_postgresql_head_knows_the_content_safety_capability(postgres: Engine) -> None:
    with postgres.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20261002_0067"
        definition = connection.scalar(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = 'capability_grants'::regclass "
                "AND conname = 'ck_capability_grants_permission_scope'"
            )
        )
    assert "platform_content_safety_manage" in str(definition)
    assert "platform_billing_manage" in str(definition)


@pytest.mark.parametrize(
    "permission", ["platform_billing_manage", "platform_content_safety_manage"]
)
def test_postgresql_head_accepts_both_recreated_platform_grants(
    postgres: Engine, permission: str
) -> None:
    from tests.database.test_capability_grants import grant, seed_scope

    with Session(postgres) as session:
        scope = seed_scope(session)
        row = grant(
            session,
            scope,
            permission=permission,
            scope_kind="platform",
            tenant_id=None,
            program_id=None,
        )
        session.add(row)
        session.commit()
        assert session.get(CapabilityGrant, row.id).permission == permission
