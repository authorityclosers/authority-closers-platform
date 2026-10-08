"""Exact internal intent, bounded composition and content-free failure evidence."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from ac_platform.billing import expiry_jobs as jobs
from ac_platform.billing.expiry import ExpiryConflict, ExpiryScopeRefused
from ac_platform.billing.trial import TrialPolicy
from ac_platform.outbox.policy import ReconciliationRequiredError
from ac_platform.outbox.repository import LeaseLostError
from ac_platform.worker import OUTBOX_JOB_ROUTES, create_minute_expiry_worker

NOW = datetime(2026, 10, 6, tzinfo=UTC)


@pytest.fixture
def state(monkeypatch):
    public, operations, account = uuid4(), uuid4(), uuid4()
    job = SimpleNamespace(
        id=uuid4(),
        lease_token=uuid4(),
        kind=jobs.EXPIRY_JOB_KIND,
        tenant_id=public,
        external_side_effect=False,
        payload={"account_id": str(account)},
    )
    order = []

    @asynccontextmanager
    async def transaction():
        try:
            yield
        except BaseException:
            order.append("rollback")
            raise
        else:
            order.append("commit")

    db = MagicMock()
    db.begin.side_effect = transaction

    @asynccontextmanager
    async def sessions():
        yield db

    repository = SimpleNamespace(
        claim=AsyncMock(return_value=[job]),
        lock_internal_lease=AsyncMock(return_value=job),
        complete=AsyncMock(),
        fail=AsyncMock(return_value=SimpleNamespace(status="dead_letter")),
    )
    recovery = SimpleNamespace(require_ready=AsyncMock(return_value=SimpleNamespace(generation=7)))
    result = SimpleNamespace(closings=[SimpleNamespace(seconds=480)], deferred_pending_lot_ids=())
    service = SimpleNamespace(expire_due=AsyncMock(return_value=result))
    service_factory = MagicMock(return_value=service)
    signal = MagicMock()
    monkeypatch.setattr(jobs, "JobRepository", lambda db: repository)
    monkeypatch.setattr(jobs, "RecoveryStateRepository", lambda db: recovery)
    monkeypatch.setattr(jobs, "MinuteExpiryService", service_factory)
    worker = jobs.MinuteExpiryWorker(
        session_factory=sessions,
        public_learner_tenant_id=public,
        operations_tenant_id=operations,
        trial_policy=TrialPolicy("v2"),
        clock=lambda: NOW,
        signal=signal,
    )
    worker._logger = MagicMock()
    return SimpleNamespace(**locals())


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": "billing.capacity_expiry.v2"},
        {"external_side_effect": True},
        {"tenant_id": None},
        {"tenant_id": "untrusted"},
        {"payload": {}},
        {"payload": {"account_id": "bad"}},
        {"payload": {"account_id": 123}},
        {"payload": {"account_id": None}},
        {"payload": []},
        {"payload": {"account_id": str(uuid4()), "kind": "organisation"}},
    ],
)
def test_exact_intent_refuses_authority_hints_and_invalid_scope(state, changes):
    intent = SimpleNamespace(**(vars(state.job) | changes))
    with pytest.raises(jobs.ExpiryIntentRefused, match="^expiry_intent_refused$"):
        jobs.validate_expiry_intent(intent, operations_tenant_id=state.operations)


def test_operations_tenant_is_refused_and_reference_only_is_accepted(state):
    assert jobs.validate_expiry_intent(state.job, operations_tenant_id=state.operations) == (
        state.public,
        state.account,
    )
    state.job.tenant_id = state.operations
    with pytest.raises(jobs.ExpiryIntentRefused):
        jobs.validate_expiry_intent(state.job, operations_tenant_id=state.operations)


def test_claim_is_bounded_and_carries_global_generation_into_atomic_execution(state):
    result = asyncio.run(state.worker.run_once())
    assert result == jobs.ExpiryWorkerResult("succeeded", 1, 1, 480, 0)
    assert state.order == ["commit", "commit"]
    state.repository.claim.assert_awaited_once_with(now=NOW, kinds=(jobs.EXPIRY_JOB_KIND,))
    state.repository.lock_internal_lease.assert_awaited_once_with(
        state.job.id,
        state.job.lease_token,
        kind=jobs.EXPIRY_JOB_KIND,
        recovery_generation=7,
    )
    state.service.expire_due.assert_awaited_once_with(
        tenant_id=state.public, account_id=state.account
    )
    state.repository.complete.assert_awaited_once_with(state.job, state.job.lease_token)


def test_deferred_success_and_idle_do_not_self_enqueue(state):
    state.result.closings = []
    state.result.deferred_pending_lot_ids = (uuid4(),)
    assert asyncio.run(state.worker.run_once()) == jobs.ExpiryWorkerResult("succeeded", 1, 0, 0, 1)
    state.repository.claim.return_value = []
    assert asyncio.run(state.worker.run_once()) == jobs.ExpiryWorkerResult("idle")
    assert state.service.expire_due.await_count == 1


@pytest.mark.parametrize(
    "error,permanent,code",
    [
        (ExpiryConflict("raw lot/account/SQL"), True, "expiry_conflict"),
        (ExpiryScopeRefused("foreign"), True, "expiry_refused"),
        (ValueError("invalid config"), True, "expiry_refused"),
        (TypeError("invalid config"), True, "expiry_refused"),
        (RuntimeError("raw database SQL parameters"), False, "expiry_transient_failure"),
    ],
)
def test_failure_rolls_back_then_uses_the_original_fence_and_bounded_code(
    state, error, permanent, code
):
    state.service.expire_due.side_effect = error
    state.repository.fail.return_value.status = "dead_letter" if permanent else "retry_wait"
    result = asyncio.run(state.worker.run_once())
    assert result == jobs.ExpiryWorkerResult("dead_lettered" if permanent else "retry_wait", 1)
    assert state.order == ["commit", "rollback", "commit"]
    assert state.repository.lock_internal_lease.await_count == 2
    assert all(
        call.kwargs["recovery_generation"] == 7
        for call in state.repository.lock_internal_lease.await_args_list
    )
    state.repository.fail.assert_awaited_once_with(
        state.job,
        state.job.lease_token,
        code,
        permanent=permanent,
    )
    state.repository.complete.assert_not_awaited()
    if isinstance(error, ExpiryConflict):
        state.signal.assert_called_once_with(
            "billing.expiry_conflict",
            {"outcome": "dead_lettered", "retryable": False},
        )
        state.worker._logger.warning.assert_called_once_with(
            "billing.expiry_conflict",
            outcome="dead_lettered",
            retryable=False,
        )
    else:
        state.signal.assert_not_called()


@pytest.mark.parametrize("phase", ["claim", "execute", "failure"])
@pytest.mark.parametrize("error", [LeaseLostError("lease"), ReconciliationRequiredError("held")])
def test_every_phase_is_fenced_without_failure_ack_or_alert(state, phase, error):
    if phase == "claim":
        state.recovery.require_ready.side_effect = error
    elif phase == "execute":
        state.repository.lock_internal_lease.side_effect = error
    else:
        state.service.expire_due.side_effect = ExpiryConflict("raw")
        state.repository.lock_internal_lease.side_effect = [state.job, error]
    result = asyncio.run(state.worker.run_once())
    assert result.outcome == "fenced" and result.closings == 0
    state.repository.fail.assert_not_awaited()
    state.repository.complete.assert_not_awaited()
    state.signal.assert_not_called()


def test_hook_failure_does_not_replace_committed_terminal_outcome(state):
    state.service.expire_due.side_effect = ExpiryConflict("raw")
    state.signal.side_effect = RuntimeError("hook")
    assert asyncio.run(state.worker.run_once()).outcome == "dead_lettered"
    assert state.repository.fail.await_count == 1


def test_missing_or_disabled_factory_fails_closed_without_starting_work(state):
    settings = SimpleNamespace(
        billing_enabled=True,
        public_learner_tenant_id=state.public,
        operations_tenant_id=state.operations,
        sales_xray_trial_policy="v2",
        sales_xray_trial_policy_switch_at=NOW,
    )
    worker = create_minute_expiry_worker(
        settings=settings,
        session_factory=state.sessions,
        clock=lambda: NOW,
        signal=state.signal,
    )
    assert isinstance(worker, jobs.MinuteExpiryWorker)
    assert worker._trial == TrialPolicy("v2", NOW)
    assert not any(route.job_kind == jobs.EXPIRY_JOB_KIND for route in OUTBOX_JOB_ROUTES.values())
    state.repository.claim.assert_not_awaited()
    for field, value in [
        ("billing_enabled", False),
        ("public_learner_tenant_id", None),
        ("operations_tenant_id", None),
        ("operations_tenant_id", state.public),
    ]:
        invalid = SimpleNamespace(**(vars(settings) | {field: value}))
        with pytest.raises(ValueError, match="expiry_composition_refused"):
            create_minute_expiry_worker(settings=invalid, session_factory=state.sessions)


def test_failure_recording_database_error_leaves_lease_for_bounded_reclaim(state):
    state.service.expire_due.side_effect = RuntimeError("raw")
    state.repository.fail.side_effect = RuntimeError("SQL parameters")
    assert asyncio.run(state.worker.run_once()) == jobs.ExpiryWorkerResult("unavailable", 1)
    state.signal.assert_not_called()
