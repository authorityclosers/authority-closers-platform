from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from ac_platform.identity.google_profile import (
    GoogleProfileClaims,
    erase_google_profile,
    normalize_google_claims,
    read_google_profile,
    record_google_profile_claims,
)
from ac_platform.identity.google_profile_models import PersonGoogleProfile
from ac_platform.identity.models import Person

PERSON_ID = UUID("11111111-1111-4111-8111-111111111111")
NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


class _AsyncSessionAdapter:
    def __init__(self, session: Session) -> None:
        self.session = session

    async def scalar(self, statement: object) -> Any:
        return self.session.scalar(statement)  # type: ignore[arg-type]

    def add(self, instance: object) -> None:
        self.session.add(instance)

    async def flush(self) -> None:
        self.session.flush()

    async def delete(self, instance: object) -> None:
        self.session.delete(instance)


@pytest.fixture
def database() -> Iterator[tuple[_AsyncSessionAdapter, Session]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Person.__table__.create(engine)
    PersonGoogleProfile.__table__.create(engine)
    session = Session(engine, expire_on_commit=False)
    session.add(
        Person(
            id=PERSON_ID,
            email="google-profile@example.test",
            email_verified_at=NOW,
            status="active",
        )
    )
    session.commit()
    try:
        yield _AsyncSessionAdapter(session), session
    finally:
        session.close()
        PersonGoogleProfile.__table__.drop(engine)
        Person.__table__.drop(engine)
        engine.dispose()


def test_normalizer_keeps_valid_claims_and_normalizes_them_independently() -> None:
    claims = normalize_google_claims(
        SimpleNamespace(
            given_name="  Ada   Marie ",
            family_name="Lovelace",
            locale="en-US",
            hosted_domain="Example.COM",
            picture_url="https://lh3.googleusercontent.com/a/profile",
        )
    )

    assert claims == GoogleProfileClaims(
        given_name="Ada Marie",
        family_name="Lovelace",
        locale="en-US",
        hosted_domain="example.com",
        picture_url="https://lh3.googleusercontent.com/a/profile",
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("given_name", "Bad\nName"),
        ("family_name", "x" * 201),
        ("locale", "en_US"),
        ("locale", "abcdef"),
        ("hosted_domain", "bad_domain.example"),
        ("hosted_domain", "-bad.example"),
        ("picture_url", "http://lh3.googleusercontent.com/a"),
        ("picture_url", "https://user@lh3.googleusercontent.com/a"),
        ("picture_url", "https://lh3.googleusercontent.com:443/a"),
        ("picture_url", "https://example.test/a"),
        ("picture_url", "https://lh3.googleusercontent.com/" + "x" * 2048),
    ],
)
def test_invalid_claim_becomes_null_without_affecting_other_claims(
    field: str,
    value: str,
) -> None:
    source = {
        "given_name": "Ada",
        "family_name": "Lovelace",
        "locale": "en-US",
        "hosted_domain": "example.test",
        "picture_url": "https://lh3.googleusercontent.com/a",
    }
    source[field] = value

    claims = normalize_google_claims(SimpleNamespace(**source))

    assert getattr(claims, field) is None
    for other_field in source.keys() - {field}:
        assert getattr(claims, other_field) == source[other_field]


def test_normalizer_never_raises_for_unreadable_assertion_fields() -> None:
    class UnreadableAssertion:
        @property
        def given_name(self) -> str:
            raise RuntimeError("claim unavailable")

    assert normalize_google_claims(UnreadableAssertion()) == GoogleProfileClaims()


@pytest.mark.asyncio
async def test_record_refresh_read_without_photo_load_and_erase(database: Any) -> None:
    async_database, sync_database = database

    assert await read_google_profile(async_database, PERSON_ID) == GoogleProfileClaims()
    first = GoogleProfileClaims(
        given_name="Ada",
        family_name="Lovelace",
        locale="en-GB",
        hosted_domain="example.test",
        picture_url="https://lh3.googleusercontent.com/a/private-url",
    )
    await record_google_profile_claims(async_database, PERSON_ID, first, NOW)
    row = sync_database.scalar(
        select(PersonGoogleProfile).where(PersonGoogleProfile.person_id == PERSON_ID)
    )
    assert row is not None
    row.photo_jpeg = b"jpeg-copy"
    row.photo_sha256 = "a" * 64
    row.photo_source_sha256 = "b" * 64
    sync_database.flush()

    statements: list[str] = []

    def capture_sql(_connection: object, _cursor: object, statement: str, *_args: object) -> None:
        statements.append(statement)

    event.listen(sync_database.get_bind(), "before_cursor_execute", capture_sql)
    second_time = datetime(2026, 9, 30, 13, 0, tzinfo=UTC)
    await record_google_profile_claims(
        async_database,
        PERSON_ID,
        GoogleProfileClaims(given_name="Augusta", family_name=None, locale="fr-FR"),
        second_time,
    )
    refreshed = await read_google_profile(async_database, PERSON_ID)
    event.remove(sync_database.get_bind(), "before_cursor_execute", capture_sql)

    assert refreshed == GoogleProfileClaims(
        given_name="Augusta",
        family_name=None,
        locale="fr-FR",
        hosted_domain=None,
    )
    assert not any(
        statement.lstrip().upper().startswith("SELECT") and "photo_jpeg" in statement
        for statement in statements
    )
    assert row.photo_sha256 == "a" * 64
    assert row.photo_source_sha256 == "b" * 64
    assert "picture_url" not in PersonGoogleProfile.__table__.columns
    assert await erase_google_profile(async_database, PERSON_ID) is True
    assert await erase_google_profile(async_database, PERSON_ID) is False
