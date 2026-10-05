"""SQLite model and PostgreSQL CHECK/ORM/trigger contracts for the new store."""

from __future__ import annotations

import runpy
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, delete, event, insert, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from ac_platform.authorization.cli import _parser
from ac_platform.db.models import model_metadata
from ac_platform.identity.models import Person
from ac_platform.product_updates.models import (
    Notification,
    ProductUpdate,
    ProductUpdateMutationError,
    UpdateSeen,
)
from tests.integration.test_product_updates_postgresql import (
    updates_engine as updates_engine,  # noqa: F401
)

NOW = datetime(2026, 10, 4, 12, tzinfo=UTC)


@pytest.fixture(params=["sqlite", "postgresql"])
def engine(request: pytest.FixtureRequest) -> Iterator[Engine]:
    if request.param == "postgresql":
        yield request.getfixturevalue("updates_engine")
        return
    database = create_engine("sqlite:///:memory:")

    @event.listens_for(database, "connect")
    def foreign_keys(connection, _record) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    model_metadata().create_all(database)
    try:
        yield database
    finally:
        database.dispose()


def note(**changes):
    return (
        dict(
            id=uuid4(),
            note_key=f"pr-{uuid4().hex}",
            version=1,
            release_id="fictional",
            note_date=date(2026, 10, 4),
            title="Fictional change",
            items=["One change."],
            status="draft",
            created_by="deploy",
        )
        | changes
    )


def rows(database: Session):
    person = Person(email=f"updates-{uuid4().hex}@example.test")
    database.add(person)
    database.flush()
    result = (
        ProductUpdate(**note()),
        UpdateSeen(person_id=person.id, note_key="fictional-note"),
        Notification(
            person_id=person.id,
            kind="report_ready",
            dedupe_key=uuid4().hex,
            title="Fictional report",
            body="Ready to read.",
            href="/reports/test",
        ),
    )
    database.add_all(result)
    database.commit()
    return result


@pytest.mark.parametrize(
    "changes,constraint",
    [
        ({"title": "x" * 61}, "title_length"),
        ({"title": ""}, "title_length"),
        ({"audience": "plans"}, "audience"),
        ({"status": "unknown"}, "status"),
        ({"version": 2}, "version_supersession"),
        ({"version": 0}, "version_supersession"),
        ({"published_at": NOW}, "publication"),
        ({"status": "published"}, "publication"),
        ({"created_by": "unknown"}, "created_by"),
    ],
)
def test_portable_checks_refuse_bad_notes(engine: Engine, changes, constraint: str) -> None:
    with pytest.raises(IntegrityError, match=constraint), engine.begin() as connection:
        connection.execute(insert(ProductUpdate), note(**changes))


def test_lineage_has_unique_versions_and_at_most_one_successor(engine: Engine) -> None:
    first = note()
    with engine.begin() as connection:
        connection.execute(insert(ProductUpdate), first)
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(insert(ProductUpdate), first | {"id": uuid4()})
    with engine.begin() as connection:
        connection.execute(
            insert(ProductUpdate),
            note(note_key=first["note_key"], version=2, supersedes_id=first["id"]),
        )
    with (
        pytest.raises(IntegrityError, match="successor|supersedes_id"),
        engine.begin() as connection,
    ):
        connection.execute(insert(ProductUpdate), note(version=3, supersedes_id=first["id"]))
    with pytest.raises(IntegrityError, match="version_supersession"), engine.begin() as connection:
        connection.execute(insert(ProductUpdate), note(supersedes_id=first["id"]))


@pytest.mark.parametrize("target", [0, 1, 2])
@pytest.mark.parametrize("operation", ["update", "delete"])
def test_orm_refuses_history_mutation(engine: Engine, target: int, operation: str) -> None:
    with Session(engine) as database:
        current = rows(database)[target]
        if operation == "delete":
            database.delete(current)
        else:
            setattr(current, "note_key" if target < 2 else "title", "rewritten")
        with pytest.raises(ProductUpdateMutationError):
            database.flush()


@pytest.mark.parametrize("expire", [False, True])
def test_notification_orm_allows_one_read_including_expired_state(
    engine: Engine, expire: bool
) -> None:
    with Session(engine) as database:
        current = rows(database)[2]
        current.read_at = NOW
        database.commit()
        if expire:
            database.expire(current)
        current.read_at = NOW + timedelta(seconds=1)
        with pytest.raises(ProductUpdateMutationError, match="once"):
            database.flush()
        database.rollback()
        current.read_at = None
        with pytest.raises(ProductUpdateMutationError, match="once"):
            database.flush()


def test_notification_cannot_rewrite_content_while_marking_read(engine: Engine) -> None:
    with Session(engine) as database:
        current = rows(database)[2]
        current.read_at, current.title = NOW, "Rewritten"
        with pytest.raises(ProductUpdateMutationError):
            database.flush()


@pytest.mark.parametrize("target", [0, 1])
@pytest.mark.parametrize("operation", ["update", "delete"])
def test_postgresql_refuses_bulk_history_mutations(
    updates_engine: Engine, target: int, operation: str
) -> None:
    with Session(updates_engine) as database:
        current = rows(database)[target]
        table, identifier = current.__table__, current.id
    command = update(table).values(note_key="rewritten") if operation == "update" else delete(table)
    with pytest.raises(DBAPIError, match="append-only"), updates_engine.begin() as connection:
        connection.execute(command.where(table.c.id == identifier))


@pytest.mark.parametrize("changes", [{"read_at": NOW + timedelta(seconds=1)}, {"read_at": None}])
def test_postgresql_notification_allows_one_read_and_no_reset(
    updates_engine: Engine, changes
) -> None:
    with Session(updates_engine) as database:
        identifier = rows(database)[2].id
    command = update(Notification).where(Notification.id == identifier)
    with updates_engine.begin() as connection:
        connection.execute(command.values(read_at=NOW))
    with pytest.raises(DBAPIError, match="once"), updates_engine.begin() as connection:
        connection.execute(command.values(**changes))


@pytest.mark.parametrize("operation", ["delete", "update", "update-and-read"])
def test_postgresql_notification_refuses_deletion_and_other_edits(
    updates_engine: Engine, operation: str
) -> None:
    with Session(updates_engine) as database:
        identifier = rows(database)[2].id
    command = (
        delete(Notification)
        if operation == "delete"
        else update(Notification).values(title="Rewritten")
    )
    if operation == "update-and-read":
        command = command.values(read_at=NOW)
    with pytest.raises(DBAPIError), updates_engine.begin() as connection:
        connection.execute(command.where(Notification.id == identifier))


@pytest.mark.parametrize("items", [[], ["x"] * 5, ["x" * 201], [None], [1], [True], {}, None])
def test_postgresql_checks_item_shape_and_bounds(updates_engine: Engine, items) -> None:
    with pytest.raises(IntegrityError), updates_engine.begin() as connection:
        connection.execute(insert(ProductUpdate), note(items=items))


@pytest.mark.parametrize("target", [1, 2])
def test_account_deduplication(engine: Engine, target: int) -> None:
    with Session(engine) as database:
        current = rows(database)[target]
        values = {
            column.name: getattr(current, column.name) for column in current.__table__.columns
        }
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(insert(current.__table__), values | {"id": uuid4()})
    with Session(engine) as database:
        person = Person(email=f"other-{uuid4().hex}@example.test")
        database.add(person)
        database.commit()
        values |= {"id": uuid4(), "person_id": person.id}
    with engine.begin() as connection:
        connection.execute(insert(current.__table__), values)


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": "release"},
        {"href": "https://example.test"},
        {"href": "//example.test"},
        {"href": "/\\example.test"},
    ],
)
def test_notification_checks_refuse_unknown_kind_and_external_links(
    engine: Engine, changes
) -> None:
    with Session(engine) as database:
        current = rows(database)[2]
        values = {
            column.name: getattr(current, column.name) for column in current.__table__.columns
        }
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            insert(Notification), values | {"id": uuid4(), "dedupe_key": uuid4().hex} | changes
        )


def test_migration_is_forward_only_and_grant_cli_accepts_the_capability() -> None:
    migration = runpy.run_path(
        str(Path(__file__).parents[2] / "db/migrations/versions/20261004_0075_product_updates.py")
    )
    assert migration["down_revision"] == "20261004_0074"
    with pytest.raises(RuntimeError, match="forward-only"):
        migration["downgrade"]()
    args = _parser().parse_args(
        [
            "grant",
            "--environment",
            "test",
            "--person-id",
            str(uuid4()),
            "--command-id",
            str(uuid4()),
            "--reason",
            "Fictional grant",
            "--permission",
            "platform_updates_manage",
            "--scope",
            "platform",
        ]
    )
    assert args.permission == "platform_updates_manage"
