"""Expected failures for the inert intelligence contract boundary."""

from __future__ import annotations


class IntelligenceError(Exception):
    """Base class for failures that are safe to expose as a bounded error code."""

    code = "intelligence_error"


class IntelligenceValidationError(IntelligenceError, ValueError):
    """A request or provider result failed deterministic validation."""

    code = "validation_error"


class PolicyDeniedError(IntelligenceError):
    """The request is outside the capability policy of this harness."""

    code = "policy_denied"


class ToolsDeniedError(PolicyDeniedError):
    """A request or provider response attempted to use tools."""

    code = "tools_denied"


class DeadlineExceededError(IntelligenceError, TimeoutError):
    """The request deadline was elapsed before or during generation."""

    code = "deadline_exceeded"


class ProviderUnavailableError(IntelligenceError):
    """The selected provider cannot currently serve the request."""

    code = "provider_unavailable"


class ProviderTimeoutError(IntelligenceError, TimeoutError):
    """The provider did not complete within the bounded request deadline."""

    code = "provider_timeout"


class ProviderResultError(IntelligenceError):
    """The provider returned a result that cannot be trusted by the application."""

    code = "provider_result_invalid"


class BudgetExceededError(IntelligenceError):
    """A bounded generation budget was exceeded."""

    code = "budget_exceeded"


__all__ = [
    "BudgetExceededError",
    "DeadlineExceededError",
    "IntelligenceError",
    "IntelligenceValidationError",
    "PolicyDeniedError",
    "ProviderResultError",
    "ProviderTimeoutError",
    "ProviderUnavailableError",
    "ToolsDeniedError",
]
