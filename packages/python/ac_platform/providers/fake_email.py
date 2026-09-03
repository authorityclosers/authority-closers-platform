"""Deterministic no-network email adapter for tests and local development."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from ac_platform.providers.ports import (
    ApprovedTemplateRegistry,
    DeliveryReceipt,
    EmailMessage,
    EmailMessageConflictError,
    SentEmail,
    TransientProviderError,
)


class FakeEmailAdapter:
    """Record accepted messages and deduplicate by the supplied intent key."""

    def __init__(
        self,
        *,
        approved_templates: ApprovedTemplateRegistry | None = None,
        fail_next: int = 0,
    ) -> None:
        if fail_next < 0:
            raise ValueError("fail_next must not be negative")
        self._registry = approved_templates or ApprovedTemplateRegistry()
        self._remaining_failures = fail_next
        self._deliveries: dict[str, SentEmail] = {}

    async def send(self, message: EmailMessage) -> DeliveryReceipt:
        message.validate(self._registry)
        existing = self._deliveries.get(message.idempotency_key)
        if existing is not None:
            if existing.message.canonical_digest != message.canonical_digest:
                raise EmailMessageConflictError(
                    "email idempotency key was reused for different canonical content"
                )
            return DeliveryReceipt(
                idempotency_key=existing.receipt.idempotency_key,
                provider_message_id=existing.receipt.provider_message_id,
                accepted=existing.receipt.accepted,
                deduplicated=True,
                accepted_at=existing.receipt.accepted_at,
            )
        if self._remaining_failures:
            self._remaining_failures -= 1
            raise TransientProviderError("fake email provider transient failure")
        receipt = DeliveryReceipt(
            idempotency_key=message.idempotency_key,
            provider_message_id=f"fake-{uuid4()}",
            accepted=True,
            deduplicated=False,
            accepted_at=datetime.now(UTC),
        )
        self._deliveries[message.idempotency_key] = SentEmail(message=message, receipt=receipt)
        return receipt

    async def send_email(
        self,
        message: EmailMessage | None = None,
        *,
        to: str | None = None,
        recipient: str | None = None,
        template: str | None = None,
        template_name: str | None = None,
        template_version: int = 1,
        idempotency_key: str | None = None,
        variables: Mapping[str, Any] | None = None,
        context: Mapping[str, Any] | None = None,
        communication_class: str = "verification_security",
    ) -> DeliveryReceipt:
        """Convenience facade for tests that construct messages at the edge."""

        if message is None:
            message = EmailMessage(
                to=to,
                recipient=recipient,
                template=template,
                template_name=template_name,
                template_version=template_version,
                idempotency_key=idempotency_key,
                variables=variables,
                context=context,
                communication_class=communication_class,
            )
        return await self.send(message)

    @property
    def deliveries(self) -> tuple[SentEmail, ...]:
        """Return a stable snapshot in acceptance order."""

        return tuple(self._deliveries.values())

    @property
    def sent_messages(self) -> tuple[EmailMessage, ...]:
        return tuple(delivery.message for delivery in self.deliveries)

    def fail_next(self, count: int = 1) -> None:
        if count < 1:
            raise ValueError("count must be positive")
        self._remaining_failures += count


FakeEmailProvider = FakeEmailAdapter


__all__ = ["FakeEmailAdapter", "FakeEmailProvider"]
