"""Durable telemetry retention and explicit account-deletion privacy seams."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from ac_platform.db.models import model_metadata
from ac_platform.identity.models import DeletionRequest, DeletionRequestStatus, Person
from ac_platform.learning.planning_models import AnalyticsEvent
from ac_platform.telemetry.retention import (
    TelemetryAccountDeletionAction,
    TelemetryAccountDeletionHook,
    TelemetryAccountDeletionResult,
    TelemetryRetentionJob,
    TelemetryRetentionPolicy,
    TelemetryRetentionPolicyUnavailable,
    TelemetryRetentionTransactionRequired,
)
from ac_platform.tenancy.models import Membership, Tenant

POLICY_ID = "learner-telemetry-v1"


@pytest.fixture
def retention_session() -> tuple[Session, UUID, UUID]:
    tenant_id = uuid4()
    person_id = uuid4()
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    model_metadata().create_all(engine)
    session = Session(engine)
    session.add_all(
        [
            Tenant(id=tenant_id, slug=f"retention-{tenant_id.hex}", name="Retention tenant"),
            Person(id=person_id, email=f"retention-{person_id.hex}@example.test"),
            Membership(tenant_id=tenant_id, person_id=person_id, role="learner", status="active"),
        ]
    )
    session.commit()
    try:
        yield session, tenant_id, person_id
    finally:
        session.close()
        engine.dispose()


def _event(
    *,
    tenant_id: UUID,
    person_id: UUID,
    event_id: str | None = None,
    expires_at: datetime,
    payload: dict[str, object] | None = None,
) -> AnalyticsEvent:
    occurred_at = expires_at - timedelta(days=30)
    return AnalyticsEvent(
        event_id=event_id or str(uuid4()),
        tenant_id=tenant_id,
        actor_person_id=person_id,
        subject_person_id=person_id,
        event_name="analytics.plan_viewed",
        event_version="1.0",
        event_class="product_analytics",
        occurred_at=occurred_at,
        trace_id="server-trace",
        release_id="test-release",
        session_id=str(uuid4()),
        route="/home",
        period="today",
        payload=payload or {"period": "today"},
        consent_status="granted",
        consent_purpose="product_analytics",
        consent_policy_version="consent-v1",
        consent_captured_at=occurred_at,
        retention_policy_id=POLICY_ID,
        retention_expires_at=expires_at,
        created_at=occurred_at,
    )


def _policy(
    action: TelemetryAccountDeletionAction = TelemetryAccountDeletionAction.PURGE,
    *,
    legal_retention: bool = False,
) -> TelemetryRetentionPolicy:
    return TelemetryRetentionPolicy(
        policy_id=POLICY_ID,
        retention_days=30,
        account_deletion_action=action,
        legal_retention=legal_retention,
    )


def test_expiry_job_is_explicit_bounded_and_not_read_triggered(
    retention_session: tuple[Session, UUID, UUID],
) -> None:
    session, tenant_id, person_id = retention_session
    now = datetime.now(UTC)
    expired = _event(
        tenant_id=tenant_id,
        person_id=person_id,
        expires_at=now - timedelta(seconds=1),
    )
    fresh = _event(
        tenant_id=tenant_id,
        person_id=person_id,
        expires_at=now + timedelta(days=1),
    )
    session.add_all([expired, fresh])
    session.commit()

    job = TelemetryRetentionJob(policy=_policy(), batch_size=1)
    with session.begin():
        first = job.run_sync(session, now=now)
    assert first.deleted == 1
    assert session.get(AnalyticsEvent, (tenant_id, expired.event_id)) is None
    assert session.get(AnalyticsEvent, (tenant_id, fresh.event_id)) is not None
    session.rollback()

    with session.begin():
        second = job.run_sync(session, now=now)
    assert second.deleted == 0


def test_expiry_job_requires_transaction_and_explicit_policy(
    retention_session: tuple[Session, UUID, UUID],
) -> None:
    session, tenant_id, person_id = retention_session
    now = datetime.now(UTC)
    session.add(
        _event(
            tenant_id=tenant_id,
            person_id=person_id,
            expires_at=now - timedelta(seconds=1),
        )
    )
    session.commit()

    with pytest.raises(TelemetryRetentionTransactionRequired):
        TelemetryRetentionJob(policy=_policy()).run_sync(session, now=now)
    with session.begin(), pytest.raises(TelemetryRetentionPolicyUnavailable):
        TelemetryRetentionJob(policy=None).run_sync(session, now=now)


def test_account_deletion_anonymization_hook_is_identity_bound_and_idempotent(
    retention_session: tuple[Session, UUID, UUID],
) -> None:
    session, tenant_id, person_id = retention_session
    deletion_request_id = uuid4()
    now = datetime.now(UTC)
    session.add(
        DeletionRequest(
            id=deletion_request_id,
            person_id=person_id,
            tenant_id=None,
            status=DeletionRequestStatus.PROCESSING.value,
            requested_at=now - timedelta(minutes=2),
        )
    )
    event = _event(
        tenant_id=tenant_id,
        person_id=person_id,
        expires_at=now + timedelta(days=1),
        payload={"period": "today"},
    )
    session.add(event)
    session.commit()

    hook = TelemetryAccountDeletionHook(policy=_policy(TelemetryAccountDeletionAction.ANONYMIZE))
    with session.begin():
        first = hook.apply_sync(
            session,
            deletion_request_id=deletion_request_id,
            person_id=person_id,
            tenant_id=tenant_id,
            now=now,
        )
    assert first.anonymized == 1
    row = session.get(AnalyticsEvent, (tenant_id, event.event_id))
    assert row is not None
    assert row.payload == {}
    assert row.route is None
    assert row.session_id is None
    assert row.trace_id.startswith("anonymized-")
    session.rollback()

    with session.begin():
        second = hook.apply_sync(
            session,
            deletion_request_id=deletion_request_id,
            person_id=person_id,
            tenant_id=tenant_id,
            now=now,
        )
    assert second.already_anonymized == 1
    assert second.has_more is False


def test_account_deletion_reports_and_drains_more_than_one_bounded_batch(
    retention_session: tuple[Session, UUID, UUID],
) -> None:
    session, tenant_id, person_id = retention_session
    deletion_request_id = uuid4()
    now = datetime.now(UTC)
    session.add(
        DeletionRequest(
            id=deletion_request_id,
            person_id=person_id,
            tenant_id=None,
            status=DeletionRequestStatus.PROCESSING.value,
            requested_at=now - timedelta(minutes=2),
        )
    )
    session.add_all(
        [
            _event(
                tenant_id=tenant_id,
                person_id=person_id,
                event_id=str(uuid4()),
                expires_at=now + timedelta(days=1),
            )
            for _ in range(3)
        ]
    )
    session.commit()

    hook = TelemetryAccountDeletionHook(policy=_policy(), batch_size=1)
    results: list[TelemetryAccountDeletionResult] = []
    for _ in range(3):
        with session.begin():
            results.append(
                hook.apply_sync(
                    session,
                    deletion_request_id=deletion_request_id,
                    person_id=person_id,
                    tenant_id=tenant_id,
                    now=now,
                )
            )

    assert [result.purged for result in results] == [1, 1, 1]
    assert [result.has_more for result in results] == [True, True, False]
    assert session.query(AnalyticsEvent).count() == 0


def test_account_deletion_preserves_continuation_when_bounded_lock_skips_work(
    retention_session: tuple[Session, UUID, UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, tenant_id, person_id = retention_session
    deletion_request_id = uuid4()
    now = datetime.now(UTC)
    event = _event(
        tenant_id=tenant_id,
        person_id=person_id,
        expires_at=now + timedelta(days=1),
    )
    session.add(
        DeletionRequest(
            id=deletion_request_id,
            person_id=person_id,
            tenant_id=None,
            status=DeletionRequestStatus.PROCESSING.value,
            requested_at=now - timedelta(minutes=2),
        )
    )
    session.add(event)
    session.commit()

    original_scalars = Session.scalars
    calls = 0

    def skip_one_bounded_select(
        database: Session, statement: object, *args: object, **kwargs: object
    ) -> object:
        nonlocal calls
        calls += 1
        if calls == 1:
            return iter(())
        return original_scalars(database, statement, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Session, "scalars", skip_one_bounded_select)
    with session.begin():
        result = TelemetryAccountDeletionHook(policy=_policy(), batch_size=1).apply_sync(
            session,
            deletion_request_id=deletion_request_id,
            person_id=person_id,
            tenant_id=tenant_id,
            now=now,
        )

    assert result.purged == 0
    assert result.has_more is True
    assert session.get(AnalyticsEvent, (tenant_id, event.event_id)) is not None


def test_account_deletion_action_rejects_raw_runtime_values() -> None:
    policy = TelemetryRetentionPolicy(
        policy_id=POLICY_ID,
        retention_days=30,
        account_deletion_action=cast(TelemetryAccountDeletionAction, "purge"),
    )

    with pytest.raises(TelemetryRetentionPolicyUnavailable, match="controlled policy enum"):
        policy.validate()


def test_account_deletion_hook_rejects_wrong_person_or_legal_retention(
    retention_session: tuple[Session, UUID, UUID],
) -> None:
    session, tenant_id, person_id = retention_session
    now = datetime.now(UTC)
    deletion_request_id = uuid4()
    session.add(
        DeletionRequest(
            id=deletion_request_id,
            person_id=person_id,
            tenant_id=None,
            status=DeletionRequestStatus.PROCESSING.value,
            requested_at=now - timedelta(minutes=2),
        )
    )
    event = _event(tenant_id=tenant_id, person_id=person_id, expires_at=now + timedelta(days=1))
    session.add(event)
    session.commit()

    hook = TelemetryAccountDeletionHook(policy=_policy())
    with session.begin(), pytest.raises(TelemetryRetentionPolicyUnavailable):
        hook.apply_sync(
            session,
            deletion_request_id=deletion_request_id,
            person_id=uuid4(),
            tenant_id=tenant_id,
            now=now,
        )
    legal_hook = TelemetryAccountDeletionHook(policy=_policy(legal_retention=True))
    with session.begin(), pytest.raises(TelemetryRetentionPolicyUnavailable):
        legal_hook.apply_sync(
            session,
            deletion_request_id=deletion_request_id,
            person_id=person_id,
            tenant_id=tenant_id,
            now=now,
        )
    assert session.get(AnalyticsEvent, (tenant_id, event.event_id)) is not None
