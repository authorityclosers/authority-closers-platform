from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.identity.models import (
    EmailChallenge,
    EmailChallengeKind,
    Person,
    PersonStatus,
)
from ac_platform.identity.password_auth import encrypt_challenge_token
from ac_platform.outbox.models import (
    Job,
    JobStatus,
    OperationsRecoveryState,
    RecoveryStatus,
)
from ac_platform.outbox.repository import LeaseLostError
from ac_platform.providers import (
    AmbiguousDeliveryProviderError,
    DeliveryReceipt,
    EmailMessage,
    PermanentProviderError,
    TransientProviderError,
)
from ac_platform.telemetry import InMemoryTelemetrySink, TelemetryRecorder
from ac_platform.worker import (
    ENROLLMENT_WELCOME_EVENT,
    ENROLLMENT_WELCOME_JOB,
    OUTBOX_JOB_ROUTES,
    PASSWORD_EMAIL_RESET_EVENT,
    PASSWORD_EMAIL_RESET_JOB,
    PASSWORD_EMAIL_VERIFICATION_EVENT,
    PASSWORD_EMAIL_VERIFICATION_JOB,
    AllowlistedDispatcher,
    AmbiguousProviderReceiptError,
    DurableWorker,
    PreparedDispatch,
    UnknownJobKindError,
)


class _AsyncContext:
    def __init__(self, value: object) -> None:
        self.value = value

    async def __aenter__(self) -> object:
        return self.value

    async def __aexit__(self, *_args: object) -> None:
        return None


class _TracingTransaction:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def __aenter__(self) -> None:
        self._events.append("transaction-enter")

    async def __aexit__(self, *_args: object) -> None:
        self._events.append("transaction-exit")


def _state(status: str = RecoveryStatus.READY.value) -> OperationsRecoveryState:
    now = datetime(2026, 8, 30, 12, tzinfo=UTC)
    return OperationsRecoveryState(
        id=1,
        generation=3,
        status=status,
        marked_at=now,
        hold_reason="restore reviewed",
        reconciled_at=now if status == RecoveryStatus.READY.value else None,
        reconciled_by=uuid4() if status == RecoveryStatus.READY.value else None,
        reconciliation_reason="approved" if status == RecoveryStatus.READY.value else None,
        updated_at=now,
    )


def _payload(*, person_id: str | None = None) -> dict[str, str]:
    return {
        "enrollment_id": str(uuid4()),
        "entitlement_id": str(uuid4()),
        "provenance_id": str(uuid4()),
        "person_id": person_id or str(uuid4()),
        "program_version_id": str(uuid4()),
        "source": "free_self",
    }


def _job(kind: str = ENROLLMENT_WELCOME_JOB, *, person_id: str | None = None) -> Job:
    now = datetime(2026, 8, 30, 12, tzinfo=UTC)
    return Job(
        id=uuid4(),
        tenant_id=uuid4(),
        kind=kind,
        dedupe_key=f"outbox:{uuid4()}",
        payload=_payload(person_id=person_id),
        external_side_effect=True,
        recovery_generation=3,
        status=JobStatus.LEASED.value,
        attempt_count=1,
        max_attempts=3,
        available_at=now,
        leased_until=now + timedelta(minutes=2),
        lease_token=uuid4(),
        created_at=now,
        updated_at=now,
    )


def _prepared(job: Job, *, recipient: str = "learner@example.test") -> PreparedDispatch:
    assert job.lease_token is not None
    return PreparedDispatch(
        job_id=job.id,
        tenant_id=job.tenant_id,
        kind=job.kind,
        attempt_count=job.attempt_count,
        lease_token=job.lease_token,
        recovery_generation=job.recovery_generation,
        provider_idempotency_key=job.dedupe_key,
        message=EmailMessage(
            to=recipient,
            template="enrollment-welcome",
            template_version=1,
            idempotency_key=job.dedupe_key,
            variables={"source": "free_self"},
            communication_class="enrollment_welcome_next_action",
        ),
    )


def _receipt(prepared: PreparedDispatch) -> DeliveryReceipt:
    return DeliveryReceipt(
        idempotency_key=prepared.provider_idempotency_key,
        provider_message_id=f"fake-{prepared.job_id}",
        accepted_at=datetime(2026, 8, 30, 12, 0, 1, tzinfo=UTC),
    )


def _settings(*, hold: bool = False, provider: str = "fake") -> SimpleNamespace:
    challenge_secret = "worker-password-challenge-secret-that-is-long-enough"  # noqa: S105
    return SimpleNamespace(
        external_side_effects_hold=hold,
        email_provider=provider,
        release_id="test-release",
        environment="test",
        public_app_url="https://learner.example.test",
        email_challenge_secret=SimpleNamespace(
            get_secret_value=lambda: challenge_secret,
        ),
    )


def _factory(session: AsyncSession) -> Callable[[], _AsyncContext]:
    return lambda: _AsyncContext(session)


async def test_dispatcher_rejects_job_kinds_outside_the_exact_allowlist() -> None:
    job = _job("not-approved")
    dispatcher = AllowlistedDispatcher({})

    with pytest.raises(UnknownJobKindError, match="not allowlisted"):
        await dispatcher.dispatch(_prepared(job))


def test_outbox_route_is_exact_and_contains_no_unsafe_default_email_kind() -> None:
    assert set(OUTBOX_JOB_ROUTES) == {
        ENROLLMENT_WELCOME_EVENT,
        PASSWORD_EMAIL_VERIFICATION_EVENT,
        PASSWORD_EMAIL_RESET_EVENT,
    }
    assert OUTBOX_JOB_ROUTES[ENROLLMENT_WELCOME_EVENT].job_kind == ENROLLMENT_WELCOME_JOB
    assert ENROLLMENT_WELCOME_JOB != "email.send"
    assert OUTBOX_JOB_ROUTES[ENROLLMENT_WELCOME_EVENT].allowed_payload_values["source"] == {
        "free_self",
        "manual_grant",
    }
    assert OUTBOX_JOB_ROUTES[PASSWORD_EMAIL_VERIFICATION_EVENT].job_kind == (
        PASSWORD_EMAIL_VERIFICATION_JOB
    )
    assert OUTBOX_JOB_ROUTES[PASSWORD_EMAIL_RESET_EVENT].job_kind == PASSWORD_EMAIL_RESET_JOB
    assert all(route.job_kind != "email.send" for route in OUTBOX_JOB_ROUTES.values())


async def test_password_email_link_uses_fragment_and_never_exposes_token_in_request_target() -> (
    None
):
    settings = _settings()
    person = Person(
        id=uuid4(),
        email="learner@example.test",
        first_name="Learner",
        display_name="Learner",
        status=PersonStatus.ACTIVE.value,
    )
    token = "v" * 43
    challenge = EmailChallenge(
        id=uuid4(),
        person_id=person.id,
        kind=EmailChallengeKind.VERIFICATION.value,
        token_hash=b"x" * 32,
        encrypted_token=encrypt_challenge_token(
            settings.email_challenge_secret.get_secret_value(),
            token,
            kind=EmailChallengeKind.VERIFICATION,
            person_id=person.id,
        ),
        issued_at=datetime(2026, 8, 30, 12, tzinfo=UTC),
        expires_at=datetime(2026, 8, 31, 12, tzinfo=UTC),
    )
    job = _job(PASSWORD_EMAIL_VERIFICATION_JOB)
    job.payload = {
        "challenge_id": str(challenge.id),
        "kind": EmailChallengeKind.VERIFICATION.value,
    }
    session = AsyncMock(spec=AsyncSession)
    session.scalar.side_effect = [challenge, person]
    worker = DurableWorker(_factory(session), settings=settings)

    message = await worker._resolve_message(
        session,
        job,
        provider_key="identity-email:test",
    )

    assert message.variables["action_link"] == (
        f"https://learner.example.test/verify-email#token={token}"
    )
    assert "?token=" not in str(message.variables["action_link"])
    challenge_query = session.scalar.await_args_list[0].args[0]
    assert "email_challenges.expires_at > now()" in str(challenge_query)


@pytest.mark.parametrize(
    ("local_hold", "durable_state", "expected"),
    [
        (True, _state(), False),
        (False, _state(RecoveryStatus.HELD.value), False),
        (False, None, False),
        (False, _state(), True),
    ],
)
async def test_worker_readiness_requires_local_release_and_durable_ready_generation(
    local_hold: bool,
    durable_state: OperationsRecoveryState | None,
    expected: bool,
) -> None:
    session = AsyncMock(spec=AsyncSession)
    session.begin = Mock(return_value=_AsyncContext(None))
    session.scalar.return_value = durable_state
    worker = DurableWorker(_factory(session), settings=_settings(hold=local_hold))

    assert await worker.prepare() is expected
    assert worker.ready is expected


async def test_worker_can_recheck_readiness_after_audited_reconciliation() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.begin = Mock(return_value=_AsyncContext(None))
    session.scalar.side_effect = [_state(RecoveryStatus.HELD.value), _state()]
    worker = DurableWorker(_factory(session), settings=_settings())

    assert not await worker.prepare()
    assert await worker.prepare()
    assert worker.ready


async def test_worker_reports_an_unchanged_recovery_blocker_only_once() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.begin = Mock(return_value=_AsyncContext(None))
    session.scalar.return_value = _state(RecoveryStatus.HELD.value)
    worker = DurableWorker(_factory(session), settings=_settings())
    worker._logger = Mock()

    assert not await worker.prepare()
    assert not await worker.prepare()

    worker._logger.warning.assert_called_once_with(  # type: ignore[attr-defined]
        "worker_recovery_reconciliation_required",
        recovery_generation=3,
    )


async def test_worker_loop_stays_fail_closed_then_runs_after_reconciliation() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.begin = Mock(return_value=_AsyncContext(None))
    session.scalar.side_effect = [_state(RecoveryStatus.HELD.value), _state()]
    worker = DurableWorker(
        _factory(session),
        settings=_settings(),
        poll_interval=0,
    )
    worker.run_once = AsyncMock(return_value=Mock())  # type: ignore[method-assign]

    await worker.run(max_iterations=2)

    worker.run_once.assert_awaited_once()  # type: ignore[attr-defined]


async def test_prepare_dispatch_resolves_verified_recipient_from_canonical_identity() -> None:
    person_id = uuid4()
    job = _job(person_id=str(person_id))
    person = Person(
        id=person_id,
        email="verified@example.test",
        status=PersonStatus.ACTIVE.value,
        email_verified_at=datetime(2026, 8, 30, 11, tzinfo=UTC),
    )
    session = AsyncMock(spec=AsyncSession)
    session.begin = Mock(return_value=_AsyncContext(None))
    session.get.return_value = job
    session.scalar.side_effect = [_state(), person]
    worker = DurableWorker(_factory(session), settings=_settings())
    assert job.lease_token is not None

    with (
        patch("ac_platform.worker.JobRepository.renew", new=AsyncMock(return_value=job)) as renew,
        patch(
            "ac_platform.worker.JobRepository.record_dispatch_started",
            new=AsyncMock(return_value=job),
        ) as record_dispatch,
    ):
        prepared = await worker._prepare_dispatch(job.id, job.lease_token)

    assert prepared.message.to == "verified@example.test"
    assert "email" not in job.payload
    assert "to" not in job.payload
    resolver_statement = session.scalar.await_args_list[1].args[0]
    resolver_sql = str(resolver_statement.compile(dialect=postgresql.dialect()))
    assert "JOIN enrollments" in resolver_sql
    assert "JOIN entitlements" in resolver_sql
    assert "JOIN enrollment_provenance" in resolver_sql
    assert "FOR SHARE" in resolver_sql
    renew.assert_awaited_once()
    record_dispatch.assert_awaited_once()


async def test_provider_call_occurs_inside_the_shared_recovery_transaction() -> None:
    person_id = uuid4()
    job = _job(person_id=str(person_id))
    prepared = _prepared(job, recipient="stale@example.test")
    person = Person(
        id=person_id,
        email="current@example.test",
        status=PersonStatus.ACTIVE.value,
        email_verified_at=datetime(2026, 8, 30, 11, tzinfo=UTC),
    )
    events: list[str] = []
    session = AsyncMock(spec=AsyncSession)
    session.begin = Mock(return_value=_TracingTransaction(events))
    session.scalar.return_value = person

    async def handler(current: PreparedDispatch) -> DeliveryReceipt:
        events.append("provider-dispatch")
        assert current.message.to == "current@example.test"
        return _receipt(current)

    worker = DurableWorker(
        _factory(session),
        dispatcher=AllowlistedDispatcher({ENROLLMENT_WELCOME_JOB: handler}),
        settings=_settings(),
    )
    with patch(
        "ac_platform.worker.JobRepository.lock_for_dispatch",
        new=AsyncMock(return_value=job),
    ) as lock_for_dispatch:
        receipt = await worker._dispatch_under_recovery_fence(prepared)

    assert receipt.idempotency_key == job.dedupe_key
    assert events == ["transaction-enter", "provider-dispatch", "transaction-exit"]
    lock_for_dispatch.assert_awaited_once_with(
        job.id,
        prepared.lease_token,
        recovery_generation=3,
        provider_idempotency_key=job.dedupe_key,
    )


async def test_worker_claims_and_commits_one_job_at_a_time() -> None:
    worker = DurableWorker(
        lambda: _AsyncContext(Mock()),
        settings=_settings(),
        batch_size=2,
    )
    first = _job()
    second = _job()
    worker._ready = True
    worker._materialize = AsyncMock(return_value=[])
    worker._claim_one = AsyncMock(side_effect=[first, second])
    worker._execute_one = AsyncMock(
        side_effect=[{"claimed": 1, "retried": 1}, {"claimed": 1, "succeeded": 1}]
    )

    result = await worker.run_once()

    assert result.claimed == 2
    assert result.retried == 1
    assert result.succeeded == 1
    assert worker._claim_one.await_count == 2
    assert [call.args[0] for call in worker._execute_one.await_args_list] == [first, second]


async def test_worker_claim_passes_its_exact_dispatch_allowlist() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.begin = Mock(return_value=_AsyncContext(None))
    worker = DurableWorker(_factory(session), settings=_settings())
    job = _job()

    with patch(
        "ac_platform.worker.JobRepository.claim",
        new=AsyncMock(return_value=[job]),
    ) as claim:
        assert await worker._claim_one() is job

    assert claim.await_args is not None
    assert claim.await_args.kwargs["kinds"] == worker.allowed_job_kinds
    assert isinstance(claim.await_args.kwargs["kinds"], frozenset)


async def test_lease_loss_on_failure_does_not_abort_remaining_work() -> None:
    sink = InMemoryTelemetrySink()
    worker = DurableWorker(
        lambda: _AsyncContext(Mock()),
        settings=_settings(),
        batch_size=2,
        telemetry=TelemetryRecorder(sink),
    )
    first = _job()
    second = _job()
    first_prepared = _prepared(first)
    second_prepared = _prepared(second)
    worker._ready = True
    worker._materialize = AsyncMock(return_value=[])
    worker._claim_one = AsyncMock(side_effect=[first, second])
    worker._prepare_dispatch = AsyncMock(side_effect=[first_prepared, second_prepared])
    worker._dispatch_under_recovery_fence = AsyncMock(
        side_effect=[TimeoutError(), _receipt(second_prepared)]
    )
    worker._fail = AsyncMock(side_effect=LeaseLostError("stale"))
    worker._record_ambiguous = AsyncMock()
    worker._record_receipt = AsyncMock()
    worker._complete = AsyncMock()

    result = await worker.run_once()

    assert result.claimed == 2
    assert result.succeeded == 1
    worker._record_ambiguous.assert_awaited_once()
    worker._record_receipt.assert_awaited_once()
    worker._complete.assert_awaited_once()
    assert all("job_id" not in event.attributes for event in sink.events)
    assert all(event.tenant_id is None for event in sink.events)


@pytest.mark.parametrize(
    ("error", "expected", "stored_dead_letter", "permanent", "ambiguous"),
    [
        (
            TransientProviderError("temporary"),
            {"claimed": 1, "retried": 1, "dead_lettered": 0},
            False,
            False,
            False,
        ),
        (
            PermanentProviderError("permanent"),
            {"claimed": 1, "retried": 0, "dead_lettered": 1},
            True,
            True,
            False,
        ),
        (
            AmbiguousProviderReceiptError("mismatch"),
            {"claimed": 1, "reconciliation_required": 1},
            True,
            True,
            True,
        ),
        (
            AmbiguousDeliveryProviderError("unknown delivery"),
            {"claimed": 1, "reconciliation_required": 1},
            True,
            True,
            True,
        ),
    ],
)
async def test_worker_failure_boundary_retries_dead_letters_or_requires_reconciliation(
    error: BaseException,
    expected: dict[str, int],
    stored_dead_letter: bool,
    permanent: bool,
    ambiguous: bool,
) -> None:
    sink = InMemoryTelemetrySink()
    worker = DurableWorker(
        lambda: _AsyncContext(Mock()),
        settings=_settings(),
        telemetry=TelemetryRecorder(sink),
    )
    job = _job()
    prepared = _prepared(job)
    failed = _job()
    failed.status = (
        JobStatus.DEAD_LETTER.value if stored_dead_letter else JobStatus.RETRY_WAIT.value
    )
    failed.lease_token = None
    failed.leased_until = None
    failed.dead_lettered_at = datetime(2026, 8, 30, 12, tzinfo=UTC) if stored_dead_letter else None
    worker._prepare_dispatch = AsyncMock(return_value=prepared)
    worker._dispatch_under_recovery_fence = AsyncMock(side_effect=error)
    worker._fail = AsyncMock(return_value=failed)

    outcome = await worker._execute_one(job)

    assert outcome == expected
    assert worker._fail.await_args.kwargs["permanent"] is permanent
    assert worker._fail.await_args.kwargs["ambiguous"] is ambiguous
    event_names = [event.name for event in sink.events]
    if ambiguous:
        assert "worker.job.failed" in event_names
        assert "worker.job.dead_lettered" not in event_names
        assert "worker.job.retry_wait" not in event_names


async def test_ambiguous_delivery_is_not_silently_retried_after_resend_window() -> None:
    worker = DurableWorker(lambda: _AsyncContext(Mock()), settings=_settings())
    job = _job()
    job.dispatch_started_at = datetime(2026, 8, 29, 10, tzinfo=UTC)
    prepared = _prepared(job)
    failed = _job()
    failed.status = JobStatus.DEAD_LETTER.value
    failed.lease_token = None
    failed.leased_until = None
    failed.delivery_ambiguous_at = datetime(2026, 8, 30, 12, tzinfo=UTC)
    failed.dead_lettered_at = datetime(2026, 8, 30, 12, tzinfo=UTC)
    worker._prepare_dispatch = AsyncMock(return_value=prepared)
    worker._dispatch_under_recovery_fence = AsyncMock(
        side_effect=AmbiguousDeliveryProviderError("unknown delivery")
    )
    worker._fail = AsyncMock(return_value=failed)

    outcome = await worker._execute_one(job)

    assert outcome == {"claimed": 1, "reconciliation_required": 1}
    worker._dispatch_under_recovery_fence.assert_awaited_once()
    assert worker._fail.await_args.kwargs == {"permanent": True, "ambiguous": True}


async def test_recovery_fence_before_provider_call_does_not_mark_delivery_ambiguous() -> None:
    worker = DurableWorker(lambda: _AsyncContext(Mock()), settings=_settings())
    worker._ready = True
    job = _job()
    prepared = _prepared(job)
    worker._prepare_dispatch = AsyncMock(return_value=prepared)
    worker._dispatch_under_recovery_fence = AsyncMock(
        side_effect=LeaseLostError("lease expired before provider call")
    )
    worker._fail = AsyncMock()
    worker._record_ambiguous = AsyncMock()

    outcome = await worker._execute_one(job)

    assert outcome == {"claimed": 1}
    worker._fail.assert_not_awaited()
    worker._record_ambiguous.assert_not_awaited()


@pytest.mark.parametrize(
    "job_kind",
    [
        ENROLLMENT_WELCOME_JOB,
        PASSWORD_EMAIL_VERIFICATION_JOB,
        PASSWORD_EMAIL_RESET_JOB,
    ],
)
async def test_durable_receipt_skips_provider_redispatch(job_kind: str) -> None:
    worker = DurableWorker(lambda: _AsyncContext(Mock()), settings=_settings())
    job = _job(job_kind)
    job.provider_idempotency_key = job.dedupe_key
    job.dispatch_started_at = datetime(2026, 8, 30, 12, tzinfo=UTC)
    job.provider_receipt = {"idempotency_key": job.dedupe_key, "accepted": True}
    job.provider_receipt_digest = "a" * 64
    job.receipt_recorded_at = datetime(2026, 8, 30, 12, 0, 1, tzinfo=UTC)
    worker._complete = AsyncMock()
    worker._prepare_dispatch = AsyncMock()

    outcome = await worker._execute_one(job)

    assert outcome == {"claimed": 1, "succeeded": 1}
    worker._complete.assert_awaited_once_with(job.id, job.lease_token)
    worker._prepare_dispatch.assert_not_awaited()


async def test_lost_post_provider_ack_keeps_the_durable_receipt_and_continues() -> None:
    worker = DurableWorker(lambda: _AsyncContext(Mock()), settings=_settings())
    job = _job()
    prepared = _prepared(job)
    worker._prepare_dispatch = AsyncMock(return_value=prepared)
    worker._dispatch_under_recovery_fence = AsyncMock(return_value=_receipt(prepared))
    worker._record_receipt = AsyncMock()
    worker._complete = AsyncMock(side_effect=LeaseLostError("expired"))
    worker._record_ambiguous = AsyncMock()

    outcome = await worker._execute_one(job)

    assert outcome == {"claimed": 1}
    worker._record_ambiguous.assert_not_awaited()


def test_default_worker_provider_is_fake_and_unconfigured_resend_is_rejected() -> None:
    worker = DurableWorker(lambda: _AsyncContext(Mock()), settings=_settings())
    assert worker.allowed_job_kinds == frozenset(
        {
            ENROLLMENT_WELCOME_JOB,
            PASSWORD_EMAIL_VERIFICATION_JOB,
            PASSWORD_EMAIL_RESET_JOB,
        }
    )
    with pytest.raises(PermanentProviderError, match="injected API key"):
        DurableWorker(lambda: _AsyncContext(Mock()), settings=_settings(provider="resend"))


def test_worker_lease_must_cover_the_bounded_provider_timeout() -> None:
    with pytest.raises(ValueError, match="cover provider_timeout"):
        DurableWorker(
            lambda: _AsyncContext(Mock()),
            settings=_settings(),
            lease_for=timedelta(seconds=30),
            provider_timeout=timedelta(seconds=25),
        )
