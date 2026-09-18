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


def _expiry_label(variables: Mapping[str, Any]) -> str:
    value = _required_text(variables, "expires_at", maximum=64)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise PermanentProviderError("email expiry must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise PermanentProviderError("email expiry must include a timezone")
    return parsed.astimezone(UTC).strftime("%d %b %Y at %H:%M UTC")


def _email_layout(
    *,
    preheader: str,
    eyebrow: str,
    heading: str,
    greeting: str,
    paragraphs: tuple[str, ...],
    action_label: str,
    action_link: str,
    security_note: str,
) -> str:
    """Render a client-safe responsive transactional email shell.

    All caller-supplied values must already be escaped. The template uses
    tables and inline styles for broad email-client support while retaining a
    small mobile override for narrow screens.
    """

    paragraph_html = "".join(
        f'<p style="margin:0 0 16px;color:#435066;font-size:16px;line-height:1.65;">{item}</p>'
        for item in paragraphs
    )
    return (
        '<!doctype html><html lang="en"><head>'
        '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="x-apple-disable-message-reformatting">'
        "<title>Authority Closers</title>"
        "<style>"
        "@media screen and (max-width:620px){"
        ".ac-shell{padding:20px 10px!important}.ac-card{border-radius:14px!important}"
        ".ac-content{padding:30px 22px!important}.ac-title{font-size:30px!important}"
        ".ac-button{display:block!important;text-align:center!important}"
        "}"
        "</style></head>"
        '<body style="margin:0;padding:0;background:#f3f6fb;color:#0f1b33;'
        'font-family:Inter,-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Arial,sans-serif;">'
        '<div style="display:none;max-height:0;overflow:hidden;opacity:0;'
        f'color:transparent;">{preheader}</div>'
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" '
        'style="width:100%;background:#f3f6fb;"><tr><td class="ac-shell" align="center" '
        'style="padding:42px 16px;">'
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" '
        'style="width:100%;max-width:640px;">'
        '<tr><td style="padding:0 4px 18px;">'
        '<table role="presentation" cellspacing="0" cellpadding="0" border="0"><tr>'
        '<td style="width:38px;height:38px;border-radius:10px;background:#18244a;color:#ffffff;'
        'font-size:13px;font-weight:800;letter-spacing:.08em;text-align:center;vertical-align:middle;">AC</td>'
        '<td style="padding-left:12px;color:#0f1b33;font-size:17px;'
        'font-weight:800;line-height:1.2;">'
        'Authority Closers<br><span style="color:#667085;font-size:12px;font-weight:600;">'
        "Learning &amp; Practice OS</span></td></tr></table></td></tr>"
        '<tr><td class="ac-card" style="overflow:hidden;border:1px solid #dfe5ee;'
        "border-radius:20px;"
        'background:#ffffff;box-shadow:0 16px 38px rgba(15,27,51,.08);">'
        '<div style="height:7px;background:#4f46e5;line-height:7px;">&nbsp;</div>'
        '<div class="ac-content" style="padding:44px 46px 40px;">'
        f'<p style="margin:0 0 18px;color:#4f46e5;font-size:12px;'
        f"font-weight:800;letter-spacing:.12em;"
        f'text-transform:uppercase;">{eyebrow}</p>'
        f'<h1 class="ac-title" style="margin:0 0 22px;color:#0f1b33;'
        f"font-size:38px;line-height:1.12;"
        f'letter-spacing:-.035em;">{heading}</h1>'
        f'<p style="margin:0 0 16px;color:#0f1b33;font-size:17px;line-height:1.55;">{greeting}</p>'
        f"{paragraph_html}"
        '<table role="presentation" cellspacing="0" cellpadding="0" border="0" '
        'style="margin:28px 0 26px;"><tr><td style="border-radius:9px;background:#4f46e5;">'
        f'<a class="ac-button" href="{action_link}" style="display:inline-block;padding:15px 24px;'
        f'color:#ffffff;font-size:15px;font-weight:800;text-decoration:none;">{action_label}</a>'
        "</td></tr></table>"
        '<div style="margin-top:8px;padding:15px 16px;border:1px solid #d9e0f5;border-radius:10px;'
        'background:#f6f7ff;color:#3f4b63;font-size:13px;line-height:1.55;">'
        f'<strong style="color:#18244a;">Security note</strong><br>{security_note}</div>'
        '<p style="margin:24px 0 0;color:#7a8495;font-size:12px;line-height:1.6;">'
        "If the button does not open, copy this secure link into your browser:<br>"
        f'<a href="{action_link}" style="color:#3730a3;word-break:break-all;">{action_link}</a></p>'
        "</div></td></tr>"
        '<tr><td style="padding:20px 8px 0;color:#7a8495;font-size:11px;'
        'line-height:1.55;text-align:center;">'
        "Authority Closers · Transactional service message<br>"
        "Sent only for account security or learner access. No marketing subscription was added."
        "</td></tr></table></td></tr></table></body></html>"
    )


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
        expires = _expiry_label(message.variables)
        safe_expiry = html.escape(expires)
        return RenderedEmail(
            subject="Verify your email — Authority Closers",
            text=(
                f"Hi {first_name},\n\nConfirm your email to activate your Authority Closers "
                f"learner account and protect your learning record.\n\nVerify my email:\n{link}"
                f"\n\nThis one-time link expires {expires}. If you did not create this account, "
                "ignore this message."
            ),
            html=_email_layout(
                preheader="Confirm your email to activate your learner account.",
                eyebrow="Account verification",
                heading="Your learning record starts here.",
                greeting=f"Hi {safe_name},",
                paragraphs=(
                    "Confirm this email address to activate your learner account and keep "
                    "course access, progress, and workbook evidence attached to you.",
                    f"This one-time link expires on <strong>{safe_expiry}</strong>.",
                ),
                action_label="Verify my email",
                action_link=safe_link,
                security_note=(
                    "If you did not create an Authority Closers account, ignore this message. "
                    "The link can be used only once."
                ),
            ),
        )

    if message.template == "identity-password-reset":
        if message.communication_class != "verification_security":
            raise PermanentProviderError(
                "password-reset template has the wrong communication class"
            )
        link = _action_link(message.variables)
        safe_link = html.escape(link, quote=True)
        expires = _expiry_label(message.variables)
        safe_expiry = html.escape(expires)
        return RenderedEmail(
            subject="Reset your password — Authority Closers",
            text=(
                f"Hi {first_name},\n\nA password reset was requested for your Authority "
                f"Closers learner account.\n\nChoose a new password:\n{link}\n\nThis "
                f"one-time link expires {expires}. If you did not request a reset, ignore "
                "this message; your current password stays unchanged."
            ),
            html=_email_layout(
                preheader="Use this one-time link to choose a new password.",
                eyebrow="Password recovery",
                heading="Reset access. Keep your work.",
                greeting=f"Hi {safe_name},",
                paragraphs=(
                    "A password reset was requested for your learner account. Your course "
                    "progress and saved evidence are not changed by this request.",
                    f"This one-time link expires on <strong>{safe_expiry}</strong>.",
                ),
                action_label="Choose a new password",
                action_link=safe_link,
                security_note=(
                    "If you did not request this reset, ignore this message. Your current "
                    "password remains active and this link will expire automatically."
                ),
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
                f"Continue with your next learning action:\n{link}\n\nYour progress and workbook "
                "evidence stay attached to your verified learner identity."
            ),
            html=_email_layout(
                preheader="Your free course access is ready. Start your next learning action.",
                eyebrow="Course access ready",
                heading="You’re in. Start the first honest rep.",
                greeting=f"Hi {safe_name},",
                paragraphs=(
                    "Your free Authority Closers course access is ready. Begin with the next "
                    "clear learning action, then reflect and put it to work.",
                    "Your progress and workbook evidence stay attached to your verified identity.",
                ),
                action_label="Continue learning",
                action_link=safe_link,
                security_note=(
                    "This link opens your learner workspace. Sign in only at the official "
                    "Authority Closers domain."
                ),
            ),
        )

    if message.template == "sales-xray-review-invitation":
        if message.communication_class != "verification_security":
            raise PermanentProviderError(
                "review invitation template has the wrong communication class"
            )
        link = _action_link(message.variables)
        safe_link = html.escape(link, quote=True)
        expires = _expiry_label(message.variables)
        safe_expiry = html.escape(expires)
        return RenderedEmail(
            subject="You’re invited to review a saved call — Authority Closers",
            text=(
                f"Hi {first_name},\n\nYou have been invited to review a saved Authority "
                "Closers call. Use this email address to sign in to the reviewer "
                "workspace.\n\nOpen reviewer invitation:\n"
                f"{link}\n\nThis invitation expires "
                f"{expires}. The email link alone does not grant access; your verified "
                "identity and exact review assignment are checked before the call opens."
            ),
            html=_email_layout(
                preheader="A saved call is ready for your bounded reviewer feedback.",
                eyebrow="Reviewer invitation",
                heading="A saved call is ready for your review.",
                greeting=f"Hi {safe_name},",
                paragraphs=(
                    "You have been invited to add source-linked sales, technical, or UX feedback "
                    "to one saved Authority Closers call.",
                    f"Sign in to the reviewer workspace with this email address. This invitation "
                    f"expires on <strong>{safe_expiry}</strong>.",
                ),
                action_label="Open reviewer invitation",
                action_link=safe_link,
                security_note=(
                    "Verify your email in the reviewer workspace to continue. Access is limited "
                    "to your assigned reviews. This invitation does not enroll you in a course."
                ),
            ),
        )

    if message.template == "reviewer-sign-in":
        if message.communication_class != "verification_security":
            raise PermanentProviderError("reviewer sign-in has the wrong communication class")
        link = _action_link(message.variables)
        safe_link = html.escape(link, quote=True)
        expires = _expiry_label(message.variables)
        safe_expiry = html.escape(expires)
        return RenderedEmail(
            subject="Sign in to your reviewer workspace — Authority Closers",
            text=(
                f"Hi {first_name},\n\nConfirm your email to open your assigned reviews.\n\n"
                f"Open reviewer workspace:\n{link}\n\nThis one-time sign-in link expires "
                f"{expires}. If you did not request it, ignore this email."
            ),
            html=_email_layout(
                preheader="Confirm your email to open your assigned reviews.",
                eyebrow="Reviewer sign-in",
                heading="Your reviews are ready when you are.",
                greeting=f"Hi {safe_name},",
                paragraphs=(
                    "Confirm your email to sign in to the Authority Closers reviewer workspace.",
                    f"This one-time link expires on <strong>{safe_expiry}</strong>.",
                ),
                action_label="Open reviewer workspace",
                action_link=safe_link,
                security_note=(
                    "If you did not request this sign-in link, ignore this email. "
                    "Access to each review is checked when you open it."
                ),
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
