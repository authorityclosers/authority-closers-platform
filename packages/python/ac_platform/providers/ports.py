"""Provider-independent email contracts and bounded template policy."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol


class ProviderError(Exception):
    """Base class for expected provider adapter failures."""


class TransientProviderError(ProviderError):
    """A provider failure that may be retried within the job budget."""


class PermanentProviderError(ProviderError):
    """A provider failure that should not be retried indefinitely."""


class AmbiguousDeliveryProviderError(ProviderError):
    """A provider call may have caused an effect but returned no durable receipt.

    This error must be quarantined behind explicit operations reconciliation. It
    is intentionally neither transient nor permanent: automatic retry could
    duplicate an effect after a provider's idempotency window expires, while an
    ordinary permanent dead letter would hide the unresolved delivery state.
    """


class EmailMessageConflictError(PermanentProviderError):
    """An idempotency key was reused for different canonical email content."""


class EmailCommunication(StrEnum):
    """The three launch communication classes permitted by AC-G1-016."""

    VERIFICATION_SECURITY = "verification_security"
    VERIFICATION = "verification_security"
    ENROLLMENT_WELCOME_NEXT_ACTION = "enrollment_welcome_next_action"
    ENROLLMENT_WELCOME = "enrollment_welcome_next_action"
    COMPLETION_CERTIFICATE = "completion_certificate"
    COMPLETION = "completion_certificate"


class ApprovedTemplateRegistry:
    """Version allowlist for bounded launch communication classes."""

    def __init__(self, approved_versions: Mapping[str, set[int]] | None = None) -> None:
        values = approved_versions or {
            EmailCommunication.VERIFICATION_SECURITY.value: {1},
            EmailCommunication.ENROLLMENT_WELCOME_NEXT_ACTION.value: {1},
            EmailCommunication.COMPLETION_CERTIFICATE.value: {1},
        }
        normalized: dict[str, frozenset[int]] = {}
        for name, versions in values.items():
            key = str(name).strip()
            if not key or not versions or any(version < 1 for version in versions):
                raise ValueError("approved template names and versions must be positive")
            normalized[key] = frozenset(versions)
        self._approved_versions = normalized

    def require(self, communication_class: str, version: int) -> None:
        normalized = communication_class.strip()
        if version not in self._approved_versions.get(normalized, frozenset()):
            raise PermanentProviderError(
                "email communication class or template version is not approved"
            )

    @property
    def approved_versions(self) -> Mapping[str, frozenset[int]]:
        return dict(self._approved_versions)


@dataclass(frozen=True, slots=True, init=False)
class EmailMessage:
    """Provider-neutral, versioned, idempotent email intent.

    ``recipient``/``template_name``/``communication``/``context`` are accepted
    aliases so adapter tests can use domain language without changing the
    canonical port shape.
    """

    to: str
    template: str
    template_version: int
    idempotency_key: str
    variables: Mapping[str, Any]
    communication_class: str

    def __init__(
        self,
        to: str | None = None,
        template: str | None = None,
        template_version: int = 1,
        idempotency_key: str | None = None,
        variables: Mapping[str, Any] | None = None,
        communication_class: str | EmailCommunication = EmailCommunication.VERIFICATION_SECURITY,
        *,
        recipient: str | None = None,
        template_name: str | None = None,
        communication: str | EmailCommunication | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        resolved_to = to if to is not None else recipient
        resolved_template = template if template is not None else template_name
        resolved_communication = communication or communication_class
        if resolved_to is None or resolved_template is None or idempotency_key is None:
            raise ValueError("email requires recipient, template, and idempotency_key")
        object.__setattr__(self, "to", self._text(resolved_to, "to", 320))
        object.__setattr__(self, "template", self._text(resolved_template, "template", 128))
        object.__setattr__(self, "template_version", template_version)
        object.__setattr__(
            self,
            "idempotency_key",
            self._text(idempotency_key, "idempotency_key", 255),
        )
        resolved_variables = variables if variables is not None else context or {}
        object.__setattr__(self, "variables", dict(resolved_variables))
        communication_value = (
            resolved_communication.value
            if isinstance(resolved_communication, EmailCommunication)
            else self._text(resolved_communication, "communication_class", 80)
        )
        object.__setattr__(self, "communication_class", communication_value)
        self.validate()

    @staticmethod
    def _text(value: str, field_name: str, maximum: int) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} must not be blank")
        if len(normalized) > maximum:
            raise ValueError(f"{field_name} must be at most {maximum} characters")
        return normalized

    def validate(self, registry: ApprovedTemplateRegistry | None = None) -> None:
        if "\n" in self.to or "\r" in self.to or self.to.count("@") != 1:
            raise ValueError("email recipient must be a single bounded address")
        if not 1 <= self.template_version <= 1000:
            raise ValueError("template_version must be between 1 and 1000")
        if registry is not None:
            registry.require(self.communication_class, self.template_version)

    @property
    def recipient(self) -> str:
        return self.to

    @property
    def template_name(self) -> str:
        return self.template

    @property
    def communication(self) -> str:
        return self.communication_class

    @property
    def context(self) -> Mapping[str, Any]:
        return self.variables

    @property
    def canonical_digest(self) -> str:
        """Digest every field that can change the accepted email intent."""

        record = {
            "to": self.to,
            "template": self.template,
            "template_version": self.template_version,
            "idempotency_key": self.idempotency_key,
            "variables": self.variables,
            "communication_class": self.communication_class,
        }
        canonical = json.dumps(
            record,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
            default=_json_default,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        timestamp = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return timestamp.astimezone(UTC).isoformat()
    return str(value)


@dataclass(frozen=True, slots=True)
class DeliveryReceipt:
    """Stable provider result safe to persist on a job result boundary."""

    idempotency_key: str
    provider_message_id: str
    accepted: bool = True
    deduplicated: bool = False
    accepted_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class SentEmail:
    """Inspectable fake-provider record; it contains no provider secret."""

    message: EmailMessage
    receipt: DeliveryReceipt


class EmailProvider(Protocol):
    """Port implemented by fake, sandbox, or production email adapters."""

    async def send(self, message: EmailMessage) -> DeliveryReceipt:
        """Accept one idempotent email intent."""


__all__ = [
    "AmbiguousDeliveryProviderError",
    "ApprovedTemplateRegistry",
    "DeliveryReceipt",
    "EmailCommunication",
    "EmailMessageConflictError",
    "EmailMessage",
    "EmailProvider",
    "PermanentProviderError",
    "ProviderError",
    "SentEmail",
    "TransientProviderError",
]
