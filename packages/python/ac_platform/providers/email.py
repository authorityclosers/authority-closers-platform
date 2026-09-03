"""Compatibility import surface and fail-closed provider factory."""

from __future__ import annotations

from typing import Any

from ac_platform.providers.fake_email import FakeEmailAdapter, FakeEmailProvider
from ac_platform.providers.ports import (
    AmbiguousDeliveryProviderError,
    ApprovedTemplateRegistry,
    DeliveryReceipt,
    EmailCommunication,
    EmailMessage,
    EmailMessageConflictError,
    EmailProvider,
    PermanentProviderError,
    ProviderError,
    SentEmail,
    TransientProviderError,
)
from ac_platform.providers.resend_email import ResendEmailAdapter


def create_email_provider(
    provider: str = "fake",
    *,
    approved_templates: ApprovedTemplateRegistry | None = None,
    resend_api_key: str | None = None,
    resend_from: str | None = None,
) -> EmailProvider:
    """Build an email adapter without ever silently enabling network I/O."""

    normalized = provider.strip().lower()
    if normalized == "fake":
        return FakeEmailAdapter(approved_templates=approved_templates)
    if normalized == "resend":
        if not resend_api_key or not resend_from:
            raise PermanentProviderError(
                "Resend requires an injected API key and reviewed sender address"
            )
        return ResendEmailAdapter(
            api_key=resend_api_key,
            from_address=resend_from,
            approved_templates=approved_templates,
        )
    raise ValueError(f"unsupported email provider: {normalized or '<blank>'}")


def create_email_provider_from_settings(settings: Any | None = None) -> EmailProvider:
    """Build the configured adapter while keeping the settings seam injectable."""

    if settings is None:
        from ac_platform.application.settings import get_settings

        settings = get_settings()
    resend_key = getattr(settings, "resend_api_key", None)
    return create_email_provider(
        str(getattr(settings, "email_provider", "fake")),
        resend_api_key=(None if resend_key is None else resend_key.get_secret_value()),
        resend_from=getattr(settings, "resend_from", None),
    )


# Names used by small integration callers; all route through the same safe
# implementation rather than creating an alternate provider path.
email_provider_factory = create_email_provider
get_email_provider = create_email_provider

__all__ = [
    "AmbiguousDeliveryProviderError",
    "ApprovedTemplateRegistry",
    "DeliveryReceipt",
    "EmailCommunication",
    "EmailMessage",
    "EmailMessageConflictError",
    "EmailProvider",
    "FakeEmailAdapter",
    "FakeEmailProvider",
    "PermanentProviderError",
    "ProviderError",
    "SentEmail",
    "TransientProviderError",
    "ResendEmailAdapter",
    "create_email_provider",
    "create_email_provider_from_settings",
    "email_provider_factory",
    "get_email_provider",
]
