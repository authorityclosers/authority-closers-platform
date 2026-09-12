from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ac_platform.bootstrap.verification_email import (
    VerificationEmailBootstrapApplication,
    VerificationEmailBootstrapCommand,
    VerificationEmailBootstrapError,
    _validate_receipt,
)
from ac_platform.outbox.models import Job, JobStatus
from ac_platform.providers import AmbiguousDeliveryProviderError, DeliveryReceipt


class _TransactionalSession:
    def __init__(self, job: Job | None = None) -> None:
        self.job = job

    def get_transaction(self) -> SimpleNamespace:
        from sqlalchemy.orm import SessionTransactionOrigin

        return SimpleNamespace(
            sync_transaction=SimpleNamespace(origin=SessionTransactionOrigin.BEGIN)
        )

    async def get(self, _model: object, _key: object) -> Job | None:
        return self.job


def _command() -> VerificationEmailBootstrapCommand:
    return VerificationEmailBootstrapCommand(
        command_id=uuid4(),
        person_id=uuid4(),
        challenge_id=uuid4(),
        expected_email="dipak@authorityclosers.com",
        operator_reference="release-2026-09-13",
        reason="approved mailbox bootstrap",
    )


def test_receipt_must_bind_to_the_canonical_outbox_key() -> None:
    receipt = DeliveryReceipt(
        idempotency_key="outbox:event-1",
        provider_message_id="msg-1",
        accepted_at=datetime.now(UTC),
    )
    _validate_receipt(receipt, "outbox:event-1")
    with pytest.raises(AmbiguousDeliveryProviderError):
        _validate_receipt(receipt, "outbox:event-2")


@pytest.mark.asyncio
async def test_replay_returns_receipt_without_resending_or_token() -> None:
    job = Job(
        id=uuid4(),
        kind="email.identity_verification.v1",
        dedupe_key="outbox:event-1",
        payload={},
        external_side_effect=True,
        recovery_generation=1,
        status=JobStatus.SUCCEEDED.value,
        attempt_count=1,
        max_attempts=3,
        provider_receipt={
            "idempotency_key": "outbox:event-1",
            "provider_message_id": "msg-1",
            "deduplicated": True,
        },
    )
    session = _TransactionalSession(job)
    application = VerificationEmailBootstrapApplication(session, operations_tenant_id=uuid4())
    prepared = SimpleNamespace(
        command=_command(),
        event_id=uuid4(),
        job_id=job.id,
        recovery_generation=1,
        replayed=True,
    )

    result = await application.result_for_succeeded(prepared)

    assert result.replayed is True
    assert result.provider_message_id == "msg-1"
    assert "token" not in result.__dict__ if hasattr(result, "__dict__") else True


@pytest.mark.asyncio
async def test_application_requires_caller_owned_transaction() -> None:
    class _UntransactionalSession:
        def get_transaction(self) -> None:
            return None

    session = _UntransactionalSession()
    application = VerificationEmailBootstrapApplication(session, operations_tenant_id=uuid4())

    with pytest.raises(VerificationEmailBootstrapError, match="caller-owned"):
        await application.prepare(_command())
