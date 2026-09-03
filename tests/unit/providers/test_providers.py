from __future__ import annotations

import hashlib
import hmac
import inspect
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.providers import (
    AmbiguousDeliveryProviderError,
    ConfiguredWebhookAdapter,
    EmailCommunication,
    EmailMessage,
    EmailMessageConflictError,
    FakeEmailAdapter,
    HmacWebhookVerifier,
    PermanentProviderError,
    ProviderWebhookRejected,
    ResendEmailAdapter,
    TransientProviderError,
    WebhookAttribution,
    create_email_provider,
)
from ac_platform.providers.models import ProviderInbox, ProviderInboxStatus, provider_payload_digest
from ac_platform.providers.resend_email import render_email
from ac_platform.providers.service import (
    MAX_PROVIDER_LEASE,
    ProviderInboxRepository,
    ProviderPayloadConflict,
    build_provider_inbox_acknowledge_statement,
    build_provider_inbox_claim_statement,
    build_provider_inbox_exhausted_statement,
    build_provider_inbox_failure_statement,
    build_provider_inbox_insert_statement,
    build_provider_inbox_renew_statement,
    build_provider_inbox_take_statement,
    deterministic_provider_retry_delay,
)


class _Savepoint:
    async def __aenter__(self) -> _Savepoint:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


class _ProviderRows:
    def __init__(self, rows: list[ProviderInbox]) -> None:
        self._rows = rows

    def all(self) -> list[ProviderInbox]:
        return self._rows


def _session() -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.add = Mock()
    session.begin_nested = Mock(return_value=_Savepoint())
    return session


def _message(key: str = "welcome:1") -> EmailMessage:
    return EmailMessage(
        recipient="learner@example.test",
        template_name="welcome-v1",
        template_version=1,
        communication=EmailCommunication.ENROLLMENT_WELCOME,
        context={"next_action": "start"},
        idempotency_key=key,
    )


def _resend_message(key: str = "reset/person-1") -> EmailMessage:
    return EmailMessage(
        to="learner@example.test",
        template="identity-password-reset",
        idempotency_key=key,
        variables={
            "first_name": "Learner",
            "action_link": "https://app.authorityclosers.test/reset#token=safe",
            "expires_at": "2026-08-31T18:30:00+00:00",
        },
        communication_class="verification_security",
    )


def _signature(secret: bytes, body: bytes, timestamp: int) -> str:
    digest = hmac.new(
        secret,
        f"{timestamp}.".encode("ascii") + body,
        hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


def _processing_event(*, attempts: int = 1, maximum: int = 3) -> ProviderInbox:
    now = datetime(2026, 8, 30, 12, tzinfo=UTC)
    payload = {"id": "evt-lease", "type": "delivery.accepted"}
    return ProviderInbox(
        id=uuid4(),
        provider="fake-email",
        external_event_id="evt-lease",
        event_type="delivery.accepted",
        payload=payload,
        payload_digest=provider_payload_digest(payload),
        status=ProviderInboxStatus.PROCESSING.value,
        processing_attempts=attempts,
        max_processing_attempts=maximum,
        processing_lease_token=uuid4(),
        processing_lease_until=now + timedelta(minutes=1),
        received_at=now,
        available_at=now,
    )


async def test_fake_email_is_no_network_and_deduplicates_replays() -> None:
    provider = FakeEmailAdapter()
    first = await provider.send(_message())
    replay = await provider.send(_message())

    assert first.accepted
    assert not first.deduplicated
    assert replay.deduplicated
    assert replay.provider_message_id == first.provider_message_id
    assert len(provider.sent_messages) == 1


async def test_fake_email_retries_transient_failure_without_recording_a_delivery() -> None:
    provider = FakeEmailAdapter(fail_next=1)
    with pytest.raises(TransientProviderError):
        await provider.send(_message("retry:1"))
    assert provider.deliveries == ()

    receipt = await provider.send(_message("retry:1"))
    assert receipt.accepted
    assert len(provider.deliveries) == 1


async def test_fake_email_digest_conflict_covers_every_canonical_message_field() -> None:
    provider = FakeEmailAdapter()
    await provider.send(_message("conflict:1"))

    with pytest.raises(PermanentProviderError, match="different canonical content"):
        await provider.send(
            EmailMessage(
                recipient="different@example.test",
                template_name="welcome-v1",
                template_version=1,
                communication=EmailCommunication.ENROLLMENT_WELCOME,
                context={"next_action": "start"},
                idempotency_key="conflict:1",
            )
        )


def test_email_canonical_digest_changes_with_each_effectful_message_field() -> None:
    base = _message("digest:1")
    variants = (
        EmailMessage(
            recipient="other@example.test",
            template_name=base.template,
            template_version=base.template_version,
            communication=base.communication,
            context=base.context,
            idempotency_key=base.idempotency_key,
        ),
        EmailMessage(
            recipient=base.recipient,
            template_name="welcome-v2",
            template_version=base.template_version,
            communication=base.communication,
            context=base.context,
            idempotency_key=base.idempotency_key,
        ),
        EmailMessage(
            recipient=base.recipient,
            template_name=base.template,
            template_version=2,
            communication=base.communication,
            context=base.context,
            idempotency_key=base.idempotency_key,
        ),
        EmailMessage(
            recipient=base.recipient,
            template_name=base.template,
            template_version=base.template_version,
            communication=base.communication,
            context={"next_action": "different"},
            idempotency_key=base.idempotency_key,
        ),
        EmailMessage(
            recipient=base.recipient,
            template_name=base.template,
            template_version=base.template_version,
            communication=EmailCommunication.COMPLETION,
            context=base.context,
            idempotency_key=base.idempotency_key,
        ),
        EmailMessage(
            recipient=base.recipient,
            template_name=base.template,
            template_version=base.template_version,
            communication=base.communication,
            context=base.context,
            idempotency_key="digest:2",
        ),
    )

    assert all(variant.canonical_digest != base.canonical_digest for variant in variants)


def test_provider_factory_fails_closed_for_unimplemented_resend() -> None:
    assert isinstance(create_email_provider(), FakeEmailAdapter)
    with pytest.raises(PermanentProviderError, match="injected API key"):
        create_email_provider("resend")


async def test_resend_adapter_sends_bounded_template_with_provider_idempotency() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.resend.com/emails"
        assert request.headers["authorization"] == "Bearer re_test_only_key"
        assert request.headers["idempotency-key"] == "verify/person-1"
        payload = json.loads(request.content)
        assert payload["from"] == "Authority Closers <learn@authorityclosers.test>"
        assert payload["to"] == ["learner@example.test"]
        assert payload["subject"] == "Verify your email — Authority Closers"
        assert "Authority Closers" in payload["html"]
        assert "Learning &amp; Practice OS" in payload["html"]
        assert "Verify my email" in payload["html"]
        assert "@media screen and (max-width:620px)" in payload["html"]
        assert "Transactional service message" in payload["html"]
        assert "No marketing subscription was added" in payload["html"]
        assert "<script>" not in payload["html"]
        assert "&lt;script&gt;" in payload["html"]
        return httpx.Response(200, json={"id": "provider-message-1"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = ResendEmailAdapter(
            api_key="re_test_only_key",
            from_address="Authority Closers <learn@authorityclosers.test>",
            http_client=client,
        )
        receipt = await provider.send(
            EmailMessage(
                to="learner@example.test",
                template="identity-email-verification",
                idempotency_key="verify/person-1",
                variables={
                    "first_name": "<script>",
                    "action_link": "https://app.authorityclosers.test/verify#token=safe",
                    "expires_at": "2026-09-01T18:30:00+00:00",
                },
                communication_class="verification_security",
            )
        )

    assert receipt.provider_message_id == "provider-message-1"
    assert receipt.idempotency_key == "verify/person-1"


@pytest.mark.parametrize(
    ("template", "communication_class", "expected_subject", "expected_action"),
    [
        (
            "identity-email-verification",
            "verification_security",
            "Verify your email — Authority Closers",
            "Verify my email",
        ),
        (
            "identity-password-reset",
            "verification_security",
            "Reset your password — Authority Closers",
            "Choose a new password",
        ),
        (
            "enrollment-welcome",
            "enrollment_welcome_next_action",
            "Your Authority Closers course access is ready",
            "Continue learning",
        ),
    ],
)
def test_transactional_email_family_renders_branded_responsive_html_and_text(
    template: str,
    communication_class: str,
    expected_subject: str,
    expected_action: str,
) -> None:
    variables = {
        "first_name": "Learner & Coach",
        "action_link": "https://staging.authorityclosers.com/action#token=preview",
    }
    if template != "enrollment-welcome":
        variables["expires_at"] = "2026-08-31T18:30:00+00:00"
    rendered = render_email(
        EmailMessage(
            to="learner@example.test",
            template=template,
            idempotency_key=f"preview/{template}",
            variables=variables,
            communication_class=communication_class,
        )
    )

    assert rendered.subject == expected_subject
    assert expected_action in rendered.html
    assert expected_action in rendered.text or template == "enrollment-welcome"
    assert rendered.html.startswith("<!doctype html>")
    assert 'role="presentation"' in rendered.html
    assert '<meta name="viewport"' in rendered.html
    assert "Learner &amp; Coach" in rendered.html
    assert "Learner & Coach" in rendered.text
    assert "No marketing subscription was added" in rendered.html
    assert "unsubscribe" not in rendered.text.lower()


@pytest.mark.parametrize(
    "expires_at",
    ["not-a-date", "2026-08-31T18:30:00"],
)
def test_security_email_rejects_invalid_or_timezone_free_expiry(expires_at: str) -> None:
    with pytest.raises(PermanentProviderError, match="expiry"):
        render_email(
            EmailMessage(
                to="learner@example.test",
                template="identity-password-reset",
                idempotency_key="preview/invalid-expiry",
                variables={
                    "first_name": "Learner",
                    "action_link": "https://staging.authorityclosers.com/reset#token=safe",
                    "expires_at": expires_at,
                },
                communication_class="verification_security",
            )
        )


@pytest.mark.parametrize(
    ("status_code", "body", "error_type"),
    [
        (425, {"name": "too_early"}, TransientProviderError),
        (429, {"name": "rate_limit_exceeded"}, TransientProviderError),
        (408, {"name": "request_timeout"}, AmbiguousDeliveryProviderError),
        (503, {"name": "application_error"}, AmbiguousDeliveryProviderError),
        (409, {"name": "concurrent_idempotent_requests"}, AmbiguousDeliveryProviderError),
        (409, {"name": "invalid_idempotent_request"}, EmailMessageConflictError),
        (422, {"name": "validation_error"}, PermanentProviderError),
    ],
)
async def test_resend_adapter_classifies_provider_failures_without_response_body_leak(
    status_code: int,
    body: dict[str, str],
    error_type: type[Exception],
) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = ResendEmailAdapter(
            api_key="re_test_only_key",
            from_address="learn@authorityclosers.test",
            http_client=client,
        )
        with pytest.raises(error_type) as caught:
            await provider.send(
                EmailMessage(
                    to="learner@example.test",
                    template="identity-password-reset",
                    idempotency_key="reset/person-1",
                    variables={
                        "first_name": "Learner",
                        "action_link": "https://app.authorityclosers.test/reset#token=safe",
                        "expires_at": "2026-08-31T18:30:00+00:00",
                    },
                    communication_class="verification_security",
                )
            )

    assert str(body) not in str(caught.value)


@pytest.mark.parametrize("error_type", [httpx.ReadTimeout, httpx.ReadError])
async def test_resend_adapter_quarantines_timeout_or_disconnect_without_leaking_details(
    error_type: type[httpx.RequestError],
) -> None:
    request_seen = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_seen
        request_seen = True
        assert request.headers["idempotency-key"] == "reset/ambiguous-transport"
        raise error_type("sensitive transport detail", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = ResendEmailAdapter(
            api_key="re_test_only_key",
            from_address="learn@authorityclosers.test",
            http_client=client,
        )
        with pytest.raises(AmbiguousDeliveryProviderError) as caught:
            await provider.send(_resend_message("reset/ambiguous-transport"))

    assert request_seen
    assert "sensitive transport detail" not in str(caught.value)
    assert "re_test_only_key" not in str(caught.value)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"sensitive malformed provider body"),
        httpx.Response(200, json={}),
        httpx.Response(200, json={"id": "x" * 129}),
    ],
)
async def test_resend_adapter_quarantines_malformed_success_receipt(
    response: httpx.Response,
) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return response

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = ResendEmailAdapter(
            api_key="re_test_only_key",
            from_address="learn@authorityclosers.test",
            http_client=client,
        )
        with pytest.raises(AmbiguousDeliveryProviderError) as caught:
            await provider.send(_resend_message("reset/ambiguous-success"))

    assert "sensitive malformed provider body" not in str(caught.value)
    assert "re_test_only_key" not in str(caught.value)


async def test_fake_email_rejects_unapproved_communication_class() -> None:
    provider = FakeEmailAdapter()
    message = EmailMessage(
        to="learner@example.test",
        template="unbounded",
        idempotency_key="unbounded:1",
        communication_class="marketing_blast",
    )
    with pytest.raises(PermanentProviderError):
        await provider.send(message)


def test_timestamped_webhook_hmac_is_verified_before_processing() -> None:
    secret = b"test-only-provider-secret"
    body = b'{"id":"evt_1","type":"delivery.accepted"}'
    now = datetime(2026, 8, 30, 12, tzinfo=UTC)
    timestamp = int(now.timestamp())
    verifier = HmacWebhookVerifier(secret)

    verifier.verify(
        body,
        timestamp=timestamp,
        signature=_signature(secret, body, timestamp),
        now=now,
    )
    with pytest.raises(ProviderWebhookRejected):
        verifier.verify(body, timestamp=timestamp, signature="0" * 64, now=now)


async def test_signed_body_cannot_be_rebound_to_another_configured_attribution() -> None:
    body = b'{"id":"evt-bound","type":"delivery.accepted"}'
    now = datetime(2026, 8, 30, 12, tzinfo=UTC)
    timestamp = int(now.timestamp())
    source = ConfiguredWebhookAdapter(
        provider="fake-email", verifier=HmacWebhookVerifier(b"source-secret")
    )
    other = ConfiguredWebhookAdapter(
        provider="another-provider", verifier=HmacWebhookVerifier(b"other-secret")
    )

    with pytest.raises(ProviderWebhookRejected):
        await ProviderInboxRepository(_session()).ingest_verified(
            adapter=other,
            body=body,
            timestamp=timestamp,
            signature=_signature(b"source-secret", body, timestamp),
            now=now,
        )
    assert source.attribution({"id": "evt-bound", "type": "delivery.accepted"}).provider == (
        "fake-email"
    )


async def test_ingest_verified_derives_all_provider_facts_from_the_exact_signed_body() -> None:
    secret = b"test-only-provider-secret"
    now = datetime(2026, 8, 30, 12, tzinfo=UTC)
    timestamp = int(now.timestamp())
    body = b'{"id":"evt-signed","type":"delivery.accepted","resource":"canonical"}'
    session = _session()
    session.scalar.return_value = None

    row, created = await ProviderInboxRepository(session).ingest_verified(
        adapter=ConfiguredWebhookAdapter(
            provider="fake-email",
            verifier=HmacWebhookVerifier(secret),
            resource_type="delivery",
            resource_id_field="resource",
        ),
        body=body,
        timestamp=timestamp,
        signature=_signature(secret, body, timestamp),
        now=now,
    )

    assert created
    assert row.external_event_id == "evt-signed"
    assert row.event_type == "delivery.accepted"
    assert row.provider == "fake-email"
    assert row.resource_type == "delivery"
    assert row.resource_id == "canonical"
    assert row.payload == {
        "id": "evt-signed",
        "type": "delivery.accepted",
        "resource": "canonical",
    }
    assert row.verified_body_digest == hashlib.sha256(body).hexdigest()
    parameters = inspect.signature(ProviderInboxRepository.ingest_verified).parameters
    assert "payload" not in parameters
    assert "external_event_id" not in parameters
    assert "event_type" not in parameters
    assert "provider" not in parameters
    assert "tenant_id" not in parameters
    assert "resource_type" not in parameters
    assert "resource_id" not in parameters
    assert "verifier" not in parameters


@pytest.mark.parametrize(
    "body",
    [
        b'{"id":"evt-1","id":"evt-2","type":"delivery.accepted"}',
        b'{"id":"evt-1","type":"delivery.accepted","value":NaN}',
        b'["evt-1"]',
        b'{"id":"evt-1"}',
    ],
)
async def test_ingest_verified_rejects_ambiguous_or_incomplete_json(body: bytes) -> None:
    secret = b"test-only-provider-secret"
    now = datetime(2026, 8, 30, 12, tzinfo=UTC)
    timestamp = int(now.timestamp())

    with pytest.raises(ProviderWebhookRejected):
        await ProviderInboxRepository(_session()).ingest_verified(
            adapter=ConfiguredWebhookAdapter(
                provider="fake-email", verifier=HmacWebhookVerifier(secret)
            ),
            body=body,
            timestamp=timestamp,
            signature=_signature(secret, body, timestamp),
            now=now,
        )


async def test_exact_body_digest_detects_semantically_equal_replay_conflict() -> None:
    secret = b"test-only-provider-secret"
    now = datetime(2026, 8, 30, 12, tzinfo=UTC)
    timestamp = int(now.timestamp())
    first_body = b'{"id":"evt-conflict","type":"delivery.accepted"}'
    replay_body = b'{ "id": "evt-conflict", "type": "delivery.accepted" }'
    session = _session()
    session.scalar.return_value = None
    repository = ProviderInboxRepository(session)
    first, _ = await repository.ingest_verified(
        adapter=ConfiguredWebhookAdapter(
            provider="fake-email", verifier=HmacWebhookVerifier(secret)
        ),
        body=first_body,
        timestamp=timestamp,
        signature=_signature(secret, first_body, timestamp),
        now=now,
    )

    session.scalar.return_value = first
    with pytest.raises(ProviderPayloadConflict, match="different verified body"):
        await repository.ingest_verified(
            adapter=ConfiguredWebhookAdapter(
                provider="fake-email", verifier=HmacWebhookVerifier(secret)
            ),
            body=replay_body,
            timestamp=timestamp,
            signature=_signature(secret, replay_body, timestamp),
            now=now,
        )


async def test_provider_inbox_replay_requires_identical_canonical_facts() -> None:
    session = _session()
    session.scalar.return_value = None
    repository = ProviderInboxRepository(session)
    first, created = await repository.record_once(
        attribution=WebhookAttribution(provider="fake-email"),
        external_event_id="evt-1",
        event_type="delivery.accepted",
        payload={"resource": "canonical"},
    )
    assert created

    session.scalar.return_value = first
    replay, created = await repository.record_once(
        attribution=WebhookAttribution(provider="fake-email"),
        external_event_id="evt-1",
        event_type="delivery.accepted",
        payload={"resource": "canonical"},
    )
    assert replay is first
    assert not created

    with pytest.raises(ProviderPayloadConflict, match="canonical facts"):
        await repository.record_once(
            attribution=WebhookAttribution(provider="fake-email"),
            external_event_id="evt-1",
            event_type="delivery.failed",
            payload={"resource": "canonical"},
        )


async def test_provider_savepoint_conflict_reloads_the_canonical_event() -> None:
    session = _session()
    payload = {"resource": "canonical"}
    canonical = ProviderInbox(
        id=uuid4(),
        provider="fake-email",
        external_event_id="evt-savepoint",
        event_type="delivery.accepted",
        payload=payload,
        payload_digest=provider_payload_digest(payload),
        max_processing_attempts=5,
    )
    session.scalar.side_effect = [None, canonical]
    session.flush.side_effect = IntegrityError("duplicate", {}, Exception("duplicate"))

    row, created = await ProviderInboxRepository(session).record_once(
        attribution=WebhookAttribution(provider=canonical.provider),
        external_event_id=canonical.external_event_id,
        event_type=canonical.event_type,
        payload=payload,
    )

    assert row is canonical
    assert not created
    session.begin_nested.assert_called_once()


def test_provider_inbox_postgresql_sql_is_atomic_db_timed_and_fenced() -> None:
    event_id = uuid4()
    token = uuid4()
    values = {
        "id": event_id,
        "provider": "fake-email",
        "external_event_id": "evt-sql",
        "event_type": "delivery.accepted",
        "payload": {"ok": True},
        "payload_digest": "a" * 64,
    }
    statements = (
        build_provider_inbox_insert_statement(values=values),
        build_provider_inbox_claim_statement(limit=1),
        build_provider_inbox_take_statement(
            event_id=event_id,
            lease_token=token,
            lease_for=timedelta(seconds=30),
        ),
        build_provider_inbox_acknowledge_statement(event_id=event_id, lease_token=token),
        build_provider_inbox_renew_statement(
            event_id=event_id,
            lease_token=token,
            lease_for=timedelta(seconds=30),
        ),
        build_provider_inbox_failure_statement(
            event_id=event_id,
            lease_token=token,
            error="safe",
            dead_letter=False,
            retry_delay=timedelta(seconds=7),
        ),
        build_provider_inbox_exhausted_statement(),
    )
    sql = [str(statement.compile(dialect=postgresql.dialect())) for statement in statements]

    assert "ON CONFLICT" in sql[0]
    assert "RETURNING provider_inbox.id" in sql[0]
    assert "FOR UPDATE SKIP LOCKED" in sql[1]
    assert all("now()" in statement.lower() for statement in sql[2:])
    assert all("processing_lease_token" in statement for statement in sql[3:6])


async def test_provider_inbox_claims_one_and_recovers_an_expired_lease() -> None:
    now = datetime(2026, 8, 30, 12, 0, 1, tzinfo=UTC)
    event = _processing_event()
    old_token = event.processing_lease_token
    event.processing_lease_until = now - timedelta(seconds=1)
    session = _session()
    session.scalars.return_value = _ProviderRows([event])
    repository = ProviderInboxRepository(session)

    with pytest.raises(ValueError, match="exactly one"):
        await repository.claim_processing(limit=2)
    claimed = await repository.claim_processing(now=now, lease_for=timedelta(seconds=30))

    assert claimed == [event]
    assert event.processing_lease_token not in {None, old_token}
    assert event.processing_attempts == 2
    assert event.processing_lease_until == now + timedelta(seconds=30)


async def test_provider_failure_requires_live_lease_and_uses_bounded_retry() -> None:
    now = datetime(2026, 8, 30, 12, tzinfo=UTC)
    event = _processing_event()
    token = event.processing_lease_token
    assert token is not None
    session = _session()
    repository = ProviderInboxRepository(session)

    with pytest.raises(ValueError, match="require.*lease token"):
        await repository.mark_failed(event, "temporary", now=now)
    failed = await repository.mark_failed(
        event,
        "temporary user@example.test 203.0.113.1",
        lease_token=token,
        now=now,
    )

    assert failed.status == ProviderInboxStatus.RETRY_WAIT.value
    assert failed.processing_lease_token is None
    assert failed.available_at > now
    assert "user@example.test" not in (failed.last_error or "")
    assert "203.0.113.1" not in (failed.last_error or "")


async def test_provider_failure_dead_letters_at_attempt_limit() -> None:
    now = datetime(2026, 8, 30, 12, tzinfo=UTC)
    event = _processing_event(attempts=3, maximum=3)
    token = event.processing_lease_token
    assert token is not None

    failed = await ProviderInboxRepository(_session()).mark_failed(
        event,
        "attempts exhausted",
        lease_token=token,
        now=now,
    )

    assert failed.status == ProviderInboxStatus.DEAD_LETTER.value
    assert failed.dead_lettered_at == now
    assert failed.processing_lease_token is None


@pytest.mark.parametrize("operation", ["ack", "renew", "fail"])
async def test_provider_processing_transitions_reject_zero_row_fence(operation: str) -> None:
    event = _processing_event()
    token = event.processing_lease_token
    assert token is not None
    session = _session()
    session.execute.return_value = Mock(rowcount=0)
    repository = ProviderInboxRepository(session)

    with pytest.raises(ValueError, match="lease is no longer current"):
        if operation == "ack":
            await repository.mark_processed(event, lease_token=token)
        elif operation == "renew":
            await repository.renew_processing(event, token)
        else:
            await repository.mark_failed(event, "failed", lease_token=token)


def test_provider_lease_and_retry_jitter_are_bounded() -> None:
    with pytest.raises(ValueError, match="at most 15 minutes"):
        build_provider_inbox_take_statement(
            event_id=uuid4(),
            lease_token=uuid4(),
            lease_for=MAX_PROVIDER_LEASE + timedelta(seconds=1),
        )

    event_id = UUID("00000000-0000-0000-0000-000000000001")
    first = deterministic_provider_retry_delay(event_id, 3)
    assert first == deterministic_provider_retry_delay(event_id, 3)
    assert timedelta(seconds=20) <= first <= timedelta(seconds=25)
    assert deterministic_provider_retry_delay(event_id, 25) <= timedelta(minutes=5)
