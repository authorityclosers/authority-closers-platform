from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.identity.models import EmailChallengeKind
from ac_platform.identity.password_auth import (
    PASSWORD_EMAIL_RESET_EVENT_V2,
    PASSWORD_EMAIL_RESET_JOB_V2,
)
from ac_platform.outbox.models import (
    JobStatus,
    OperationsRecoveryState,
    OutboxEvent,
    OutboxEventStatus,
)
from ac_platform.outbox.repository import OutboxRepository
from ac_platform.worker import OUTBOX_JOB_ROUTES

ACTIVITY_ID = UUID("86f7efee-f504-4d6f-b4bc-9b3cb84ba2be")
COURSE = "authority-closers-free-course"


class _Rows:
    def __init__(self, rows: list[OutboxEvent]) -> None:
        self._rows = rows

    def all(self) -> list[OutboxEvent]:
        return self._rows


class _Savepoint:
    async def __aenter__(self) -> _Savepoint:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


def _session() -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.add = Mock()
    session.begin_nested = Mock(return_value=_Savepoint())
    return session


def _ready_state() -> OperationsRecoveryState:
    now = datetime(2026, 8, 30, 12, tzinfo=UTC)
    return OperationsRecoveryState(
        id=1,
        generation=3,
        status="ready",
        marked_at=now,
        hold_reason="restore review",
        reconciled_at=now,
        reconciled_by=uuid4(),
        reconciliation_reason="approved",
        updated_at=now,
    )


@pytest.mark.parametrize(
    "include_activity", [False, True], ids=["course-only", "course-and-activity"]
)
async def test_materialize_password_email_v2_preserves_allowlisted_job_payload(
    include_activity: bool,
) -> None:
    challenge_id = uuid4()
    person_id = uuid4()
    payload = {
        "challenge_id": str(challenge_id).upper(),
        "kind": EmailChallengeKind.PASSWORD_RESET.value,
        "course": COURSE,
    }
    if include_activity:
        payload["activity"] = str(ACTIVITY_ID).upper()
    event = OutboxEvent(
        id=uuid4(),
        tenant_id=None,
        event_type=PASSWORD_EMAIL_RESET_EVENT_V2,
        aggregate_type="person",
        aggregate_id=person_id,
        dedupe_key=f"identity-email:password_reset:{challenge_id}",
        payload=payload,
        status=OutboxEventStatus.PENDING.value,
        occurred_at=datetime(2026, 8, 30, 12, tzinfo=UTC),
        created_at=datetime(2026, 8, 30, 12, tzinfo=UTC),
    )
    session = _session()
    session.scalar.side_effect = [_ready_state(), None, _ready_state()]
    session.scalars.return_value = _Rows([event])

    jobs = await OutboxRepository(session).materialize_pending_jobs(
        routes=OUTBOX_JOB_ROUTES,
    )

    assert len(jobs) == 1
    job = jobs[0]
    assert job.kind == PASSWORD_EMAIL_RESET_JOB_V2
    assert job.status == JobStatus.QUEUED.value
    assert job.external_side_effect is True
    assert job.recovery_generation == 3
    expected_payload = {
        "challenge_id": str(challenge_id),
        "kind": EmailChallengeKind.PASSWORD_RESET.value,
        "course": COURSE,
    }
    if include_activity:
        expected_payload["activity"] = str(ACTIVITY_ID)
    assert job.payload == expected_payload
    assert event.status == OutboxEventStatus.PUBLISHED.value
    assert event.published_at is not None
    assert job.kind != "email.identity_password_reset.v1"
