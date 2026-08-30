"""Compatibility import surface and safe provider factory.

The G1 default is deliberately the deterministic fake adapter. Resend is
named in configuration for future work, but no production-network adapter is
implemented in this slice and the factory rejects it explicitly.
"""

from __future__ import annotations

from typing import Any

from ac_platform.providers.fake_email import FakeEmailAdapter, FakeEmailProvider
from ac_platform.providers.ports import (
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


def create_email_provider(
    provider: str = "fake",
    *,
    approved_templates: ApprovedTemplateRegistry | None = None,
) -> EmailProvider:
    """Build an email adapter without ever silently enabling network I/O."""

    normalized = provider.strip().lower()
    if normalized == "fake":
        return FakeEmailAdapter(approved_templates=approved_templates)
    if normalized == "resend":
        raise PermanentProviderError(
            "Resend email delivery is not implemented; the G1 slice only permits fake delivery"
        )
    raise ValueError(f"unsupported email provider: {normalized or '<blank>'}")


def create_email_provider_from_settings(settings: Any | None = None) -> EmailProvider:
    """Build the configured adapter while keeping the settings seam injectable."""

    if settings is None:
        from ac_platform.application.settings import get_settings

        settings = get_settings()
    return create_email_provider(str(getattr(settings, "email_provider", "fake")))


# Names used by small integration callers; all route through the same safe
# implementation rather than creating an alternate provider path.
email_provider_factory = create_email_provider
get_email_provider = create_email_provider

__all__ = [
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
    "create_email_provider",
    "create_email_provider_from_settings",
    "email_provider_factory",
    "get_email_provider",
]
