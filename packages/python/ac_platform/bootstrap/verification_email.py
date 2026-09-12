"""One approved verification-email delivery while global recovery is held.

This boundary exists only to break the empty-production identity cycle.  It
does not create a person, challenge, membership, session, or outbox event.  It
reuses one existing pending verification event and its canonical ``outbox:``
job key, records an operator audit intent, and keeps the recovery generation
held while the provider request and receipt are fenced.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import SessionTransactionOrigin

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository
from ac_platform.identity.models import EmailChallenge, EmailChallengeKind, Person, PersonStatus
from ac_platform.identity.password_auth import normalize_email
from ac_platform.outbox.models import (
    Job,
    JobStatus,
    OutboxEvent,
    OutboxEventStatus,
)
from ac_platform.outbox.repository import (
    JobRepository,
    OutboxRepository,
    RecoveryStateRepository,
)
from ac_platform.providers import (
    AmbiguousDeliveryProviderError,
    DeliveryReceipt,
    EmailMessage,
    EmailProvider,
    PermanentProviderError,
    TransientProviderError,
)
from ac_platform.worker import (
    OUTBOX_JOB_ROUTES,
    PASSWORD_EMAIL_VERIFICATION_EVENT,
    PASSWORD_EMAIL_VERIFICATION_JOB,
    resolve_password_message,
)

VERIFICATION_EMAIL_BOOTSTRAP_ACTION = "identity.verification_email_bootstrapped"
VERIFICATION_EMAIL_DEDUPE_PREFIX = "identity-email:email_verification:"
BOOTSTRAP_EMAIL_LEASE_SECONDS = 120
BOOTSTRAP_EMAIL_PROVIDER_TIMEOUT_SECONDS = 30
INITIAL_BOOTSTRAP_GENERATION = 1
INITIAL_BOOTSTRAP_HOLD_REASON = "initial_activation_requires_reconciliation"


class VerificationEmailBootstrapError(Exception):
    """Expected fail-closed refusal from the held-state email boundary."""


@dataclass(frozen=True, slots=True)
class VerificationEmailBootstrapCommand:
    """Operator intent for one exact existing challenge and recipient."""

    command_id: UUID
    person_id: UUID
    challenge_id: UUID
    expected_email: str
    operator_reference: str
    reason: str


@dataclass(frozen=True, slots=True)
class VerificationEmailBootstrapResult:
    """Safe identifiers and provider evidence; never includes the challenge token."""

    command_id: UUID
    person_id: UUID
    challenge_id: UUID
    event_id: UUID
    job_id: UUID
    recovery_generation: int
    provider_message_id: str | None
    deduplicated: bool | None
    replayed: bool


@dataclass(frozen=True, slots=True)
class _PreparedIntent:
    command: VerificationEmailBootstrapCommand
    event_id: UUID
    job_id: UUID
    recovery_generation: int
    replayed: bool


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _required_text(value: str, field: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise VerificationEmailBootstrapError(f"{field} must not be blank")
    if len(normalized) > maximum:
        raise VerificationEmailBootstrapError(f"{field} must be at most {maximum} characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise VerificationEmailBootstrapError(f"{field} must not contain control characters")
    return normalized


def _receipt_payload(receipt: DeliveryReceipt) -> dict[str, Any]:
    return {
        "idempotency_key": receipt.idempotency_key,
        "provider_message_id": receipt.provider_message_id,
        "accepted": receipt.accepted,
        "deduplicated": receipt.deduplicated,
        "accepted_at": receipt.accepted_at.isoformat(),
    }


def _validate_receipt(receipt: DeliveryReceipt, provider_key: str) -> None:
    if receipt.idempotency_key != provider_key:
        raise AmbiguousDeliveryProviderError(
            "provider receipt idempotency key did not match the durable dispatch"
        )
    if (
        not receipt.provider_message_id.strip()
        or len(receipt.provider_message_id) > 255
        or not isinstance(receipt.deduplicated, bool)
        or not isinstance(receipt.accepted_at, datetime)
        or receipt.accepted_at.tzinfo is None
    ):
        raise AmbiguousDeliveryProviderError("provider returned invalid receipt evidence")
    if receipt.accepted is not True:
        raise PermanentProviderError("provider did not accept the durable dispatch")


class VerificationEmailBootstrapApplication:
    """Prepare and dispatch one exact pending verification event."""

    def __init__(self, session: AsyncSession, *, operations_tenant_id: UUID) -> None:
        if not isinstance(operations_tenant_id, UUID):
            raise VerificationEmailBootstrapError("an explicit operations tenant is required")
        self._session = session
        self._operations_tenant_id = operations_tenant_id

    def _require_transaction(self) -> None:
        transaction = self._session.get_transaction()
        sync_transaction = None if transaction is None else transaction.sync_transaction
        if (
            sync_transaction is None
            or sync_transaction.origin is not SessionTransactionOrigin.BEGIN
        ):
            raise VerificationEmailBootstrapError(
                "verification-email bootstrap requires an explicit caller-owned transaction"
            )

    @staticmethod
    def _result_from_job(
        prepared: _PreparedIntent,
        job: Job,
    ) -> VerificationEmailBootstrapResult:
        receipt = job.provider_receipt or {}
        return VerificationEmailBootstrapResult(
            command_id=prepared.command.command_id,
            person_id=prepared.command.person_id,
            challenge_id=prepared.command.challenge_id,
            event_id=prepared.event_id,
            job_id=prepared.job_id,
            recovery_generation=prepared.recovery_generation,
            provider_message_id=receipt.get("provider_message_id"),
            deduplicated=receipt.get("deduplicated"),
            replayed=True,
        )

    async def _prepare_intent(
        self,
        command: VerificationEmailBootstrapCommand,
    ) -> _PreparedIntent:
        expected_email = normalize_email(command.expected_email)
        operator_reference = _required_text(command.operator_reference, "operator_reference", 160)
        reason = _required_text(command.reason, "reason", 500)
        if not isinstance(command.command_id, UUID):
            raise VerificationEmailBootstrapError("command_id must be an explicit UUID")
        if not isinstance(command.person_id, UUID) or not isinstance(command.challenge_id, UUID):
            raise VerificationEmailBootstrapError(
                "person_id and challenge_id must be explicit UUIDs"
            )
        normalized = VerificationEmailBootstrapCommand(
            command_id=command.command_id,
            person_id=command.person_id,
            challenge_id=command.challenge_id,
            expected_email=expected_email,
            operator_reference=operator_reference,
            reason=reason,
        )

        state = await RecoveryStateRepository(self._session).require_held(lock=True)
        if (
            state.generation != INITIAL_BOOTSTRAP_GENERATION
            or state.hold_reason != INITIAL_BOOTSTRAP_HOLD_REASON
        ):
            raise VerificationEmailBootstrapError(
                "verification email bootstrap is limited to the initial recovery hold"
            )
        prior = await self._session.get(AuditEvent, command.command_id)
        if prior is not None:
            if (
                prior.tenant_id != self._operations_tenant_id
                or prior.actor_type != "operator_bootstrap"
                or prior.actor_person_id is not None
                or prior.session_id is not None
                or prior.action != VERIFICATION_EMAIL_BOOTSTRAP_ACTION
                or prior.resource_type != "email_challenge"
                or prior.resource_id != str(command.challenge_id)
                or prior.reason != reason
                or not isinstance(prior.payload, dict)
                or prior.payload.get("operator_reference") != operator_reference
                or prior.payload.get("expected_email") != expected_email
                or prior.payload.get("person_id") != str(command.person_id)
                or prior.payload.get("challenge_id") != str(command.challenge_id)
                or prior.payload.get("recovery_generation") != state.generation
            ):
                raise VerificationEmailBootstrapError(
                    "command ID conflicts with an immutable verification-email intent"
                )
            try:
                prior_event_id = UUID(str(prior.payload["event_id"]))
                prior_job_id = UUID(str(prior.payload["job_id"]))
            except (KeyError, TypeError, ValueError) as error:
                raise VerificationEmailBootstrapError(
                    "existing verification-email intent is malformed"
                ) from error
            prior_job = await self._session.scalar(
                select(Job).where(Job.id == prior_job_id).with_for_update()
            )
            if (
                prior_job is not None
                and prior_job.status == JobStatus.SUCCEEDED.value
                and prior_job.provider_receipt is not None
                and prior_job.dedupe_key == f"outbox:{prior_event_id}"
                and prior_job.recovery_generation == state.generation
            ):
                return _PreparedIntent(
                    command=VerificationEmailBootstrapCommand(
                        command_id=command.command_id,
                        person_id=command.person_id,
                        challenge_id=command.challenge_id,
                        expected_email=expected_email,
                        operator_reference=operator_reference,
                        reason=reason,
                    ),
                    event_id=prior_event_id,
                    job_id=prior_job_id,
                    recovery_generation=state.generation,
                    replayed=True,
                )
        person = await self._session.scalar(
            select(Person).where(Person.id == normalized.person_id).with_for_update()
        )
        if (
            person is None
            or person.status != PersonStatus.ACTIVE.value
            or person.email is None
            or normalize_email(person.email) != expected_email
            or person.email_verified_at is not None
        ):
            raise VerificationEmailBootstrapError(
                "the exact person must be active, unverified, and match the approved email"
            )

        current = datetime.now(UTC)
        challenge = await self._session.scalar(
            select(EmailChallenge)
            .where(
                EmailChallenge.id == normalized.challenge_id,
                EmailChallenge.person_id == normalized.person_id,
                EmailChallenge.kind == EmailChallengeKind.VERIFICATION.value,
            )
            .with_for_update()
        )
        if (
            challenge is None
            or challenge.consumed_at is not None
            or _as_utc(challenge.expires_at) <= current
        ):
            raise VerificationEmailBootstrapError(
                "the exact verification challenge is expired, consumed, or unavailable"
            )
        active_challenge_ids = tuple(
            await self._session.scalars(
                select(EmailChallenge.id)
                .where(
                    EmailChallenge.person_id == normalized.person_id,
                    EmailChallenge.kind == EmailChallengeKind.VERIFICATION.value,
                    EmailChallenge.consumed_at.is_(None),
                    EmailChallenge.expires_at > func.now(),
                )
                .with_for_update()
            )
        )
        if active_challenge_ids != (normalized.challenge_id,):
            raise VerificationEmailBootstrapError(
                "exactly one active verification challenge is required"
            )

        event_key = f"{VERIFICATION_EMAIL_DEDUPE_PREFIX}{normalized.challenge_id}"
        event = await self._session.scalar(
            select(OutboxEvent).where(OutboxEvent.dedupe_key == event_key).with_for_update()
        )
        if event is None:
            raise VerificationEmailBootstrapError(
                "the canonical verification outbox event is unavailable"
            )
        expected_payload = {
            "challenge_id": str(normalized.challenge_id),
            "kind": EmailChallengeKind.VERIFICATION.value,
        }
        if (
            event.event_type != PASSWORD_EMAIL_VERIFICATION_EVENT
            or event.aggregate_type != "person"
            or event.aggregate_id != normalized.person_id
            or event.tenant_id is not None
            or event.payload != expected_payload
            or event.status
            not in {
                OutboxEventStatus.PENDING.value,
                OutboxEventStatus.PUBLISHED.value,
            }
        ):
            raise VerificationEmailBootstrapError(
                "the canonical verification outbox intent is not publishable"
            )

        route = OUTBOX_JOB_ROUTES[PASSWORD_EMAIL_VERIFICATION_EVENT]
        job_key = f"outbox:{event.id}"
        job = await self._session.scalar(
            select(Job).where(Job.dedupe_key == job_key).with_for_update()
        )
        if event.status == OutboxEventStatus.PUBLISHED.value and job is None:
            raise VerificationEmailBootstrapError(
                "published verification intent has no durable job"
            )
        if job is None:
            job = await JobRepository(self._session).enqueue(
                kind=route.job_kind,
                dedupe_key=job_key,
                payload=route.normalize_payload(event.payload),
                tenant_id=event.tenant_id,
                max_attempts=route.max_attempts,
                external_side_effect=True,
            )
            if job.status != JobStatus.HELD.value or job.recovery_generation != state.generation:
                raise VerificationEmailBootstrapError(
                    "verification job did not remain held in the current generation"
                )
            await OutboxRepository(self._session).mark_published(event)
        elif (
            job.kind != PASSWORD_EMAIL_VERIFICATION_JOB
            or job.dedupe_key != job_key
            or job.payload != expected_payload
            or not job.external_side_effect
            or job.recovery_generation != state.generation
        ):
            raise VerificationEmailBootstrapError(
                "verification job intent does not match the event"
            )
        if job.status == JobStatus.SUCCEEDED.value and prior is None:
            raise VerificationEmailBootstrapError(
                "existing successful verification job lacks the bootstrap audit intent"
            )

        payload = {
            "schema_version": 1,
            "operator_reference": operator_reference,
            "expected_email": expected_email,
            "person_id": str(normalized.person_id),
            "challenge_id": str(normalized.challenge_id),
            "event_id": str(event.id),
            "job_id": str(job.id),
            "recovery_generation": state.generation,
        }
        if prior is not None:
            if (
                prior.tenant_id != self._operations_tenant_id
                or prior.actor_type != "operator_bootstrap"
                or prior.actor_person_id is not None
                or prior.session_id is not None
                or prior.action != VERIFICATION_EMAIL_BOOTSTRAP_ACTION
                or prior.resource_type != "email_challenge"
                or prior.resource_id != str(normalized.challenge_id)
                or prior.payload != payload
                or prior.reason != reason
            ):
                raise VerificationEmailBootstrapError(
                    "command ID conflicts with an immutable verification-email intent"
                )
            replayed = True
        else:
            await AuditRepository(self._session).append(
                event_id=normalized.command_id,
                tenant_id=self._operations_tenant_id,
                actor_person_id=None,
                actor_type="operator_bootstrap",
                action=VERIFICATION_EMAIL_BOOTSTRAP_ACTION,
                resource_type="email_challenge",
                resource_id=normalized.challenge_id,
                payload=payload,
                reason=reason,
            )
            replayed = False
        return _PreparedIntent(
            command=normalized,
            event_id=event.id,
            job_id=job.id,
            recovery_generation=state.generation,
            replayed=replayed,
        )

    async def prepare(
        self,
        command: VerificationEmailBootstrapCommand,
    ) -> _PreparedIntent:
        """Persist the immutable operator intent in a caller-owned transaction."""

        self._require_transaction()
        return await self._prepare_intent(command)

    async def claim(self, prepared: _PreparedIntent) -> tuple[UUID, UUID] | None:
        """Lease the exact held job in a short transaction before any provider call."""

        self._require_transaction()
        job = await self._session.get(Job, prepared.job_id)
        if job is None:
            raise VerificationEmailBootstrapError("verification job no longer exists")
        if job.status == JobStatus.SUCCEEDED.value:
            if job.provider_receipt is None:
                raise VerificationEmailBootstrapError("successful verification job lacks receipt")
            return None
        claimed = await JobRepository(self._session).claim_bootstrap_external(
            prepared.job_id,
            kind=PASSWORD_EMAIL_VERIFICATION_JOB,
            recovery_generation=prepared.recovery_generation,
            lease_for=timedelta(seconds=BOOTSTRAP_EMAIL_LEASE_SECONDS),
        )
        if claimed.lease_token is None:
            raise VerificationEmailBootstrapError("verification job lease was not created")
        return claimed.id, claimed.lease_token

    async def result_for_succeeded(
        self,
        prepared: _PreparedIntent,
    ) -> VerificationEmailBootstrapResult:
        """Return an existing receipt without re-reading or re-sending a token."""

        self._require_transaction()
        job = await self._session.get(Job, prepared.job_id)
        if job is None or job.status != JobStatus.SUCCEEDED.value or job.provider_receipt is None:
            raise VerificationEmailBootstrapError("verification job has no durable success receipt")
        return self._result_from_job(prepared, job)

    async def begin_dispatch(
        self,
        prepared: _PreparedIntent,
        lease: tuple[UUID, UUID],
        *,
        settings: Any,
    ) -> EmailMessage:
        """Resolve the canonical message and durably mark dispatch before sending."""

        self._require_transaction()
        job_id, lease_token = lease
        provider_key = f"outbox:{prepared.event_id}"
        repository = JobRepository(self._session)
        job = await repository.lock_bootstrap_dispatch(
            job_id,
            lease_token,
            kind=PASSWORD_EMAIL_VERIFICATION_JOB,
            recovery_generation=prepared.recovery_generation,
            provider_idempotency_key=provider_key,
        )
        message = await resolve_password_message(
            self._session,
            settings,
            job,
            provider_key=provider_key,
        )
        await repository.record_bootstrap_dispatch_started(
            job_id,
            lease_token,
            kind=PASSWORD_EMAIL_VERIFICATION_JOB,
            recovery_generation=prepared.recovery_generation,
            provider_idempotency_key=provider_key,
        )
        return message

    async def dispatch(
        self,
        prepared: _PreparedIntent,
        lease: tuple[UUID, UUID],
        *,
        message: EmailMessage,
        provider: EmailProvider,
    ) -> DeliveryReceipt:
        """Send under the held recovery fence and persist the receipt atomically."""

        self._require_transaction()
        job_id, lease_token = lease
        provider_key = f"outbox:{prepared.event_id}"
        repository = JobRepository(self._session)
        await repository.lock_bootstrap_effect(
            job_id,
            lease_token,
            kind=PASSWORD_EMAIL_VERIFICATION_JOB,
            recovery_generation=prepared.recovery_generation,
            provider_idempotency_key=provider_key,
        )
        async with asyncio.timeout(BOOTSTRAP_EMAIL_PROVIDER_TIMEOUT_SECONDS):
            receipt = await provider.send(message)
        if not isinstance(receipt, DeliveryReceipt):
            raise AmbiguousDeliveryProviderError("provider returned an unsupported receipt shape")
        _validate_receipt(receipt, provider_key)
        await repository.record_receipt(job_id, lease_token, _receipt_payload(receipt))
        await repository.complete(job_id, lease_token)
        return receipt

    async def record_failure(
        self,
        prepared: _PreparedIntent,
        lease: tuple[UUID, UUID],
        error: BaseException,
        *,
        ambiguous: bool,
    ) -> None:
        """Persist provider failure evidence after the provider transaction rolls back."""

        self._require_transaction()
        job_id, lease_token = lease
        await JobRepository(self._session).fail(
            job_id,
            lease_token,
            error,
            permanent=not isinstance(error, TransientProviderError),
            ambiguous=ambiguous,
        )


__all__ = [
    "VerificationEmailBootstrapApplication",
    "VerificationEmailBootstrapCommand",
    "VerificationEmailBootstrapError",
    "VerificationEmailBootstrapResult",
    "VERIFICATION_EMAIL_BOOTSTRAP_ACTION",
    "INITIAL_BOOTSTRAP_GENERATION",
    "INITIAL_BOOTSTRAP_HOLD_REASON",
]
