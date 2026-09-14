from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence.application import ConversationDenied
from ac_platform.conversation_intelligence.review_service import ConversationReviewService

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)


def _recording() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        person_id=uuid4(),
        source_sha256="a" * 64,
    )


def _application(database: Mock) -> SimpleNamespace:
    return SimpleNamespace(database=database, clock=Mock(return_value=NOW))


def _guest_rows(recording: SimpleNamespace) -> tuple[object, ...]:
    principal_id = uuid4()
    usage_id = uuid4()
    visitor_id = uuid4()
    guest = SimpleNamespace(
        tenant_id=recording.tenant_id,
        submission_id=uuid4(),
        person_id=recording.person_id,
        recording_id=recording.id,
        processing_lease_id=uuid4(),
        usage_id=usage_id,
        source_sha256=recording.source_sha256,
    )
    lease = SimpleNamespace(
        principal_id=principal_id,
        tenant_id=recording.tenant_id,
        person_id=recording.person_id,
        usage_id=usage_id,
        expires_at=NOW.replace(day=13),
        revoked_at=None,
    )
    principal = SimpleNamespace(
        tenant_id=recording.tenant_id,
        person_id=recording.person_id,
        revoked_at=None,
    )
    person = SimpleNamespace(
        status="active",
        email=None,
        email_verified_at=None,
    )
    tenant = SimpleNamespace(status="active")
    member = SimpleNamespace(role="processing", status="active", ended_at=None)
    usage = SimpleNamespace(
        visitor_id=visitor_id,
        person_id=None,
        source_sha256=recording.source_sha256,
    )
    settlement = SimpleNamespace(kind="completed")
    visitor = SimpleNamespace(id=visitor_id, expires_at=NOW.replace(day=13), revoked_at=None)
    return (
        guest,
        lease,
        principal,
        person,
        tenant,
        member,
        None,
        None,
        None,
        usage,
        settlement,
        visitor,
        None,
    )


@pytest.mark.asyncio
async def test_guest_recording_owner_allows_retained_non_login_principal() -> None:
    recording = _recording()
    database = Mock()
    database.scalar = AsyncMock(side_effect=_guest_rows(recording))
    service = ConversationReviewService(
        _application(database), operations_tenant_id=uuid4()
    )

    await service._recording_owner(recording)  # type: ignore[arg-type]

    assert database.scalar.await_count == 13


@pytest.mark.asyncio
async def test_guest_recording_owner_denies_revoked_processing_principal() -> None:
    recording = _recording()
    rows = list(_guest_rows(recording))
    rows[2] = SimpleNamespace(
        tenant_id=recording.tenant_id,
        person_id=recording.person_id,
        revoked_at=NOW,
    )
    database = Mock()
    database.scalar = AsyncMock(side_effect=rows)
    service = ConversationReviewService(
        _application(database), operations_tenant_id=uuid4()
    )

    with pytest.raises(ConversationDenied, match="source owner"):
        await service._recording_owner(recording)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_guest_recording_owner_denies_foreign_recording_link() -> None:
    recording = _recording()
    guest = SimpleNamespace(
        tenant_id=recording.tenant_id,
        person_id=recording.person_id,
        recording_id=uuid4(),
        source_sha256=recording.source_sha256,
    )
    database = Mock()
    database.scalar = AsyncMock(return_value=guest)
    service = ConversationReviewService(
        _application(database), operations_tenant_id=uuid4()
    )

    with pytest.raises(ConversationDenied, match="source owner"):
        await service._guest_source_owner(recording, guest)  # type: ignore[arg-type]

    database.scalar.assert_not_awaited()


@pytest.mark.asyncio
async def test_unverified_non_guest_learner_stays_on_verified_member_path() -> None:
    recording = _recording()
    database = Mock()
    database.scalar = AsyncMock(
        side_effect=[
            None,
            SimpleNamespace(status="active", email_verified_at=None),
            SimpleNamespace(status="active"),
            SimpleNamespace(status="active", ended_at=None),
        ]
    )
    service = ConversationReviewService(
        _application(database), operations_tenant_id=uuid4()
    )

    with pytest.raises(ConversationDenied, match="verified AC workspace member"):
        await service._recording_owner(recording)  # type: ignore[arg-type]

    assert database.scalar.await_count == 4
