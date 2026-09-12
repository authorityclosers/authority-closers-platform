from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import SessionTransactionOrigin

from ac_platform.app_updates.application import (
    AppUpdateError,
    AppUpdatesApplication,
    AppUpdateUnavailable,
)
from ac_platform.app_updates.catalogue import AppRelease, AppReleaseCatalogue
from ac_platform.app_updates.models import AppUpdateReadReceipt
from ac_platform.kernel.authz import ActorContext

NOW = datetime(2026, 9, 10, 12, tzinfo=UTC)


def release(
    release_id: str = "current-release",
    *,
    state: str = "shipped",
    created_at: datetime = NOW,
) -> AppRelease:
    return AppRelease(
        id=release_id,
        title="Release title",
        message="Release message",
        version="v0.2 Alpha",
        highlights=("One factual change.",),
        target_href="/notifications",
        created_at=created_at,
        state=state,  # type: ignore[arg-type]
    )


class FakeScalarResult:
    def __init__(self, values: list[str]) -> None:
        self.values = values

    def all(self) -> list[str]:
        return self.values


class FakeDatabase:
    def __init__(
        self,
        *,
        scalar_rows: list[Any] | None = None,
        read_ids: list[list[str]] | None = None,
        explicit_transaction: bool = True,
    ) -> None:
        self.scalar_rows = list(scalar_rows or [])
        self.read_ids = list(read_ids or [])
        self.explicit_transaction = explicit_transaction
        self.added: list[Any] = []
        self.statements: list[Any] = []
        self.flush_error: Exception | None = None

    def get_transaction(self) -> Any:
        if not self.explicit_transaction:
            return None
        return SimpleNamespace(
            sync_transaction=SimpleNamespace(origin=SessionTransactionOrigin.BEGIN)
        )

    async def scalar(self, statement: Any) -> Any:
        self.statements.append(statement)
        return self.scalar_rows.pop(0) if self.scalar_rows else None

    async def scalars(self, statement: Any) -> FakeScalarResult:
        self.statements.append(statement)
        values = self.read_ids.pop(0) if self.read_ids else []
        return FakeScalarResult(values)

    def add(self, row: Any) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        if self.flush_error is not None:
            raise self.flush_error

    @asynccontextmanager
    async def begin_nested(self):  # type: ignore[no-untyped-def]
        yield


def actor() -> ActorContext:
    return ActorContext(person_id=uuid4(), session_id=uuid4(), tenant_id=uuid4())


def catalogue(*releases: AppRelease) -> AppReleaseCatalogue:
    return AppReleaseCatalogue(version="test-catalogue", releases=tuple(releases))


def application(
    database: FakeDatabase,
    *releases: AppRelease,
) -> AppUpdatesApplication:
    return AppUpdatesApplication(  # type: ignore[arg-type]
        database,
        catalogue=catalogue(*releases),
        clock=lambda: NOW,
    )


def test_catalogue_is_deterministic_and_filters_draft_and_future_items() -> None:
    current = release()
    older = release("older-release", created_at=NOW - timedelta(days=1))
    draft = release("draft-release", state="draft")
    future = release("future-release", created_at=NOW + timedelta(seconds=1))

    visible = catalogue(older, future, draft, current).available(NOW)

    assert [item.id for item in visible] == ["current-release", "older-release"]
    assert catalogue(current).resolve_available("current-release", NOW) is current


@pytest.mark.parametrize(
    "target_href",
    [
        "https://evil.example",
        "//evil.example",
        "/safe\\evil",
        "/%2fevil",
        "/%5Cevil",
        "/line\nbreak",
    ],
)
def test_release_targets_reject_external_and_ambiguous_paths(target_href: str) -> None:
    with pytest.raises(ValueError, match="release targets"):
        AppRelease(
            id="unsafe-release",
            title="Release title",
            message="Release message",
            version="v0.2 Alpha",
            highlights=("One factual change.",),
            target_href=target_href,
            created_at=NOW,
        )


def test_catalogue_rejects_invalid_frozen_state_and_more_than_fifty_notes() -> None:
    with pytest.raises(ValueError, match="state"):
        release(state="retired")
    with pytest.raises(ValueError, match="at most 50"):
        catalogue(*(release(f"release-{index}") for index in range(51)))


@pytest.mark.asyncio
async def test_list_is_person_and_tenant_scoped_and_counts_only_visible_unread() -> None:
    current = actor()
    database = FakeDatabase(read_ids=[["older-release"]])
    result = await application(
        database,
        release("older-release", created_at=NOW - timedelta(days=1)),
        release(),
    ).list_updates(current)

    assert result["person_id"] == current.person_id
    assert result["tenant_id"] == current.tenant_id
    assert [(item["id"], item["read"]) for item in result["items"]] == [
        ("current-release", False),
        ("older-release", True),
    ]
    assert result["unread_count"] == 1
    statement = str(database.statements[0])
    assert "app_update_read_receipts.tenant_id" in statement
    assert "app_update_read_receipts.person_id" in statement
    assert "app_update_read_receipts.release_id IN" in statement


@pytest.mark.asyncio
async def test_mark_read_inserts_one_self_scoped_append_only_receipt() -> None:
    current = actor()
    database = FakeDatabase(scalar_rows=[None], read_ids=[["current-release"]])

    result = await application(database, release()).mark_read(current, "current-release")

    receipt = database.added[0]
    assert isinstance(receipt, AppUpdateReadReceipt)
    assert (receipt.tenant_id, receipt.person_id, receipt.release_id) == (
        current.tenant_id,
        current.person_id,
        "current-release",
    )
    assert result["unread_count"] == 0
    assert result["items"][0]["read"] is True


@pytest.mark.asyncio
async def test_mark_read_is_idempotent_across_sessions_for_the_same_person_and_tenant() -> None:
    first = actor()
    second_session = ActorContext(first.person_id, uuid4(), first.tenant_id)
    existing = AppUpdateReadReceipt(
        tenant_id=first.tenant_id,
        person_id=first.person_id,
        release_id="current-release",
    )
    database = FakeDatabase(
        scalar_rows=[existing, existing],
        read_ids=[["current-release"], ["current-release"]],
    )
    app = application(database, release())

    first_result = await app.mark_read(first, "current-release")
    second_result = await app.mark_read(second_session, "current-release")

    assert database.added == []
    assert first_result["items"][0]["read"] is True
    assert second_result["items"][0]["read"] is True


@pytest.mark.asyncio
async def test_concurrent_duplicate_insert_is_a_successful_idempotent_read() -> None:
    current = actor()
    existing = AppUpdateReadReceipt(
        tenant_id=current.tenant_id,
        person_id=current.person_id,
        release_id="current-release",
    )
    database = FakeDatabase(
        scalar_rows=[None, existing],
        read_ids=[["current-release"]],
    )
    database.flush_error = IntegrityError("insert", {}, RuntimeError("duplicate"))

    result = await application(database, release()).mark_read(current, "current-release")

    assert result["unread_count"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("release_id", "candidate"),
    [
        ("unknown-release", release()),
        ("draft-release", release("draft-release", state="draft")),
        (
            "future-release",
            release("future-release", created_at=NOW + timedelta(seconds=1)),
        ),
    ],
)
async def test_unknown_draft_and_future_releases_share_one_rejection(
    release_id: str,
    candidate: AppRelease,
) -> None:
    database = FakeDatabase()

    with pytest.raises(AppUpdateUnavailable, match="unavailable"):
        await application(database, candidate).mark_read(actor(), release_id)

    assert database.statements == []
    assert database.added == []


@pytest.mark.asyncio
async def test_mutation_requires_the_authenticated_caller_transaction() -> None:
    database = FakeDatabase(explicit_transaction=False)

    with pytest.raises(AppUpdateError, match="caller-owned transaction"):
        await application(database, release()).mark_read(actor(), "current-release")

    assert database.statements == []
