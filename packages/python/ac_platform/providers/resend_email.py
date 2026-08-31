"""Resend transactional-email adapter for the bounded AC alpha.

The adapter renders only the versioned service/security templates used by the
durable worker. It never accepts arbitrary subject or HTML input, and it sends
the worker's durable idempotency key to Resend as a second deduplication fence.
"""

from __future__ import annotations

import html
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parseaddr
from typing import Any
from urllib.parse import urlsplit

import httpx

from ac_platform.providers.ports import (
    AmbiguousDeliveryProviderError,
    ApprovedTemplateRegistry,
    DeliveryReceipt,
    EmailMessage,
    EmailMessageConflictError,
    PermanentProviderError,
    TransientProviderError,
)

RESEND_EMAIL_ENDPOINT = "https://api.resend.com/emails"


@dataclass(frozen=True, slots=True)
class RenderedEmail:
    subject: str
    text: str
    html: str


def _required_text(
    variables: Mapping[str, Any],
    name: str,
    *,
    maximum: int,
) -> str:
    value = variables.get(name)
    if not isinstance(value, str):
        raise PermanentProviderError(f"email template variable {name} must be text")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise PermanentProviderError(
            f"email template variable {name} must be non-blank and at most {maximum} characters"
        )
    return normalized


def _action_link(variables: Mapping[str, Any]) -> str:
    link = _required_text(variables, "action_link", maximum=2048)
    parsed = urlsplit(link)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username:
        raise PermanentProviderError("email action link must be an absolute HTTP(S) URL")
    if any(character in link for character in ("\r", "\n")):
        raise PermanentProviderError("email action link contains forbidden control characters")
    return link


def render_email(message: EmailMessage) -> RenderedEmail:
    """Render one exact approved template without accepting arbitrary markup."""

    if message.template_version != 1:
        raise PermanentProviderError("email template version is not implemented")
    first_name = _required_text(message.variables, "first_name", maximum=120)
    safe_name = html.escape(first_name)

    if message.template == "identity-email-verification":
        if message.communication_class != "verification_security":
            raise PermanentProviderError("verification template has the wrong communication class")
        link = _action_link(message.variables)
        safe_link = html.escape(link, quote=True)
        return RenderedEmail(
            subject="Verify your Authority Closers email",
            text=(
                f"Hi {first_name},\n\nVerify your email to finish creating your Authority "
                f"Closers account:\n{link}\n\nIf you did not request this, you can ignore this "
                "message."
            ),
            html=(
                f"<p>Hi {safe_name},</p>"
                "<p>Verify your email to finish creating your Authority Closers account.</p>"
                f'<p><a href="{safe_link}">Verify email</a></p>'
                "<p>If you did not request this, you can ignore this message.</p>"
            ),
        )

    if message.template == "identity-password-reset":
        if message.communication_class != "verification_security":
            raise PermanentProviderError(
                "password-reset template has the wrong communication class"
            )
        link = _action_link(message.variables)
        safe_link = html.escape(link, quote=True)
        return RenderedEmail(
            subject="Reset your Authority Closers password",
            text=(
                f"Hi {first_name},\n\nUse this secure link to reset your Authority Closers "
                f"password:\n{link}\n\nIf you did not request a reset, you can ignore this "
                "message."
            ),
            html=(
                f"<p>Hi {safe_name},</p>"
                "<p>Use this secure link to reset your Authority Closers password.</p>"
                f'<p><a href="{safe_link}">Reset password</a></p>'
                "<p>If you did not request a reset, you can ignore this message.</p>"
            ),
        )

    if message.template == "enrollment-welcome":
        if message.communication_class != "enrollment_welcome_next_action":
            raise PermanentProviderError("welcome template has the wrong communication class")
        link = _action_link(message.variables)
        safe_link = html.escape(link, quote=True)
        return RenderedEmail(
            subject="Your Authority Closers course access is ready",
            text=(
                f"Hi {first_name},\n\nYour free Authority Closers course access is ready. "
                f"Continue with your next learning action:\n{link}"
            ),
            html=(
                f"<p>Hi {safe_name},</p>"
                "<p>Your free Authority Closers course access is ready.</p>"
                f'<p><a href="{safe_link}">Continue learning</a></p>'
            ),
        )

    raise PermanentProviderError("email template is not implemented by the Resend adapter")


class ResendEmailAdapter:
    """Small Resend REST adapter with fail-closed error classification."""

    def __init__(
        self,
        *,
        api_key: str,
        from_address: str,
        approved_templates: ApprovedTemplateRegistry | None = None,
        http_client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        normalized_key = api_key.strip()
        if len(normalized_key) < 12 or "\n" in normalized_key or "\r" in normalized_key:
            raise ValueError("Resend API key is not configured")
        normalized_from = from_address.strip()
        _display_name, parsed_address = parseaddr(normalized_from)
        if (
            not normalized_from
            or len(normalized_from) > 320
            or "\n" in normalized_from
            or "\r" in normalized_from
            or parsed_address.count("@") != 1
        ):
            raise ValueError("Resend sender address is invalid")
        if not 1 <= timeout_seconds <= 60:
            raise ValueError("Resend timeout must be between one and sixty seconds")
        self._api_key = normalized_key
        self._from_address = normalized_from
        self._registry = approved_templates or ApprovedTemplateRegistry()
        self._client = http_client
        self._timeout = httpx.Timeout(timeout_seconds)

    async def send(self, message: EmailMessage) -> DeliveryReceipt:
        message.validate(self._registry)
        rendered = render_email(message)
        payload = {
            "from": self._from_address,
            "to": [message.to],
            "subject": rendered.subject,
            "text": rendered.text,
            "html": rendered.html,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Idempotency-Key": message.idempotency_key,
        }
        try:
            if self._client is None:
                async with httpx.AsyncClient(
                    timeout=self._timeout,
                    follow_redirects=False,
                ) as client:
                    response = await client.post(
                        RESEND_EMAIL_ENDPOINT,
                        headers=headers,
                        json=payload,
                    )
            else:
                response = await self._client.post(
                    RESEND_EMAIL_ENDPOINT,
                    headers=headers,
                    json=payload,
                )
        except (httpx.TimeoutException, httpx.NetworkError):
            # httpx cannot prove whether a timeout/disconnect happened before
            # or after Resend accepted the request. Quarantine the durable job
            # instead of silently replaying it, including after Resend's
            # finite idempotency window has elapsed.
            raise AmbiguousDeliveryProviderError(
                "Resend delivery outcome is unknown because no receipt was returned"
            ) from None

        provider_error = self._provider_error_name(response)
        if response.status_code == 409 and provider_error == "concurrent_idempotent_requests":
            raise AmbiguousDeliveryProviderError(
                "Resend delivery outcome is unknown while processing the same idempotent request"
            )
        if response.status_code == 409 and provider_error == "invalid_idempotent_request":
            raise EmailMessageConflictError(
                "Resend idempotency key was reused for different canonical content"
            )
        if response.status_code in {425, 429}:
            raise TransientProviderError(f"Resend returned retryable status {response.status_code}")
        if response.status_code == 408 or response.status_code >= 500:
            raise AmbiguousDeliveryProviderError(
                f"Resend returned status {response.status_code} with unknown delivery outcome"
            )
        if response.status_code < 200 or response.status_code >= 300:
            raise PermanentProviderError(
                f"Resend rejected the email request with status {response.status_code}"
            )

        try:
            body = response.json()
        except ValueError:
            raise AmbiguousDeliveryProviderError(
                "Resend accepted the request but returned unusable receipt evidence"
            ) from None
        provider_message_id = body.get("id") if isinstance(body, dict) else None
        if (
            not isinstance(provider_message_id, str)
            or not provider_message_id.strip()
            or len(provider_message_id) > 128
        ):
            raise AmbiguousDeliveryProviderError(
                "Resend accepted the request but returned unusable receipt evidence"
            )
        return DeliveryReceipt(
            idempotency_key=message.idempotency_key,
            provider_message_id=provider_message_id,
            accepted=True,
            deduplicated=False,
            accepted_at=datetime.now(UTC),
        )

    @staticmethod
    def _provider_error_name(response: httpx.Response) -> str | None:
        try:
            body = response.json()
        except ValueError:
            return None
        if not isinstance(body, dict):
            return None
        name = body.get("name")
        return name if isinstance(name, str) else None


__all__ = [
    "RESEND_EMAIL_ENDPOINT",
    "RenderedEmail",
    "ResendEmailAdapter",
    "render_email",
]
