from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from pydantic import BaseModel
from sqlalchemy.ext import asyncio as sqlalchemy_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.bootstrap import verification_email_cli as cli_module
from ac_platform.bootstrap.verification_email import (
    VerificationEmailBootstrapApplication,
    VerificationEmailBootstrapCommand,
    VerificationEmailBootstrapError,
    _validate_receipt,
)
from ac_platform.outbox.models import Job, JobStatus
from ac_platform.providers import (
    AmbiguousDeliveryProviderError,
    DeliveryReceipt,
    PermanentProviderError,
)


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
    application = VerificationEmailBootstrapApplication(
        cast(AsyncSession, session), operations_tenant_id=uuid4()
    )
    prepared = SimpleNamespace(
        command=_command(),
        event_id=uuid4(),
        job_id=job.id,
        recovery_generation=1,
        replayed=True,
    )

    result = await application.result_for_succeeded(cast(Any, prepared))

    assert result.replayed is True
    assert result.provider_message_id == "msg-1"
    assert "token" not in result.__dict__ if hasattr(result, "__dict__") else True


@pytest.mark.asyncio
async def test_application_requires_caller_owned_transaction() -> None:
    class _UntransactionalSession:
        def get_transaction(self) -> None:
            return None

    session = _UntransactionalSession()
    application = VerificationEmailBootstrapApplication(
        cast(AsyncSession, session), operations_tenant_id=uuid4()
    )

    with pytest.raises(VerificationEmailBootstrapError, match="caller-owned"):
        await application.prepare(_command())


def test_cli_rejects_fake_production_provider_before_database_prepare(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("AC_ENVIRONMENT", "production")
    monkeypatch.setenv("AC_DATABASE_URL", "postgresql+psycopg://fixture.invalid/database")
    monkeypatch.setattr(
        cli_module,
        "Settings",
        lambda **_kwargs: SimpleNamespace(
            release_id="b" * 40,
            database_url="postgresql+psycopg://fixture.invalid/database",
            operations_tenant_id=uuid4(),
            email_provider="fake",
        ),
    )
    monkeypatch.setattr(cli_module, "require_baked_release_id", lambda value: value)
    monkeypatch.setattr(
        sqlalchemy_asyncio,
        "create_async_engine",
        lambda *_args, **_kwargs: pytest.fail("database must not be opened"),
    )

    result = cli_module.main(
        [
            "--environment",
            "production",
            "--allow-production",
            "--person-id",
            str(uuid4()),
            "--challenge-id",
            str(uuid4()),
            "--command-id",
            str(uuid4()),
            "--expected-email",
            "dipak@example.test",
            "--operator-reference",
            "test-preflight",
            "--reason",
            "provider must be reviewed",
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert "require the reviewed Resend provider" in captured.err
    assert captured.out == ""


def test_cli_validates_resend_credentials_before_database_prepare(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("AC_ENVIRONMENT", "staging")
    monkeypatch.setenv("AC_DATABASE_URL", "postgresql+psycopg://fixture.invalid/database")
    monkeypatch.setattr(
        cli_module,
        "Settings",
        lambda **_kwargs: SimpleNamespace(
            release_id="c" * 40,
            database_url="postgresql+psycopg://fixture.invalid/database",
            operations_tenant_id=uuid4(),
            email_provider="resend",
        ),
    )
    monkeypatch.setattr(cli_module, "require_baked_release_id", lambda value: value)
    monkeypatch.setattr(
        cli_module,
        "create_email_provider_from_settings",
        lambda _settings: (_ for _ in ()).throw(
            PermanentProviderError("reviewed Resend credentials are missing")
        ),
    )
    monkeypatch.setattr(
        sqlalchemy_asyncio,
        "create_async_engine",
        lambda *_args, **_kwargs: pytest.fail("database must not be opened"),
    )

    result = cli_module.main(
        [
            "--environment",
            "staging",
            "--person-id",
            str(uuid4()),
            "--challenge-id",
            str(uuid4()),
            "--command-id",
            str(uuid4()),
            "--expected-email",
            "dipak@example.test",
            "--operator-reference",
            "test-provider",
            "--reason",
            "provider preflight",
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert "credentials are missing" in captured.err
    assert captured.out == ""


def test_cli_does_not_echo_validation_input(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class _Probe(BaseModel):
        database_url: int

    def invalid_settings(**_kwargs: object) -> object:
        _Probe(database_url="synthetic-secret-database-url")
        raise AssertionError("unreachable")

    monkeypatch.setenv("AC_ENVIRONMENT", "staging")
    monkeypatch.setenv("AC_DATABASE_URL", "postgresql+psycopg://fixture.invalid/database")
    monkeypatch.setattr(cli_module, "Settings", invalid_settings)

    result = cli_module.main(
        [
            "--environment",
            "staging",
            "--person-id",
            str(uuid4()),
            "--challenge-id",
            str(uuid4()),
            "--command-id",
            str(uuid4()),
            "--expected-email",
            "dipak@example.test",
            "--operator-reference",
            "test-config",
            "--reason",
            "invalid settings",
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert "deployment configuration is invalid" in captured.err
    assert "synthetic-secret-database-url" not in captured.err
    assert captured.out == ""
