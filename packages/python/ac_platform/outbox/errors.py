"""Expected failures at the durable-work boundary."""

from __future__ import annotations


class OutboxError(Exception):
    """Base error for outbox/job operations."""


class DuplicateIntentError(OutboxError):
    """A dedupe key was reused for a different canonical intent."""


class JobStateError(OutboxError):
    """A job transition is not valid for its current durable state."""


class LeaseLostError(JobStateError):
    """The worker no longer owns the job lease."""


class JobHeldError(JobStateError):
    """A side-effect job is held pending explicit reconciliation."""


class RetryNotAllowedError(JobStateError):
    """A manual retry was requested for a state that cannot be retried."""


__all__ = [
    "DuplicateIntentError",
    "JobHeldError",
    "JobStateError",
    "LeaseLostError",
    "OutboxError",
    "RetryNotAllowedError",
]
