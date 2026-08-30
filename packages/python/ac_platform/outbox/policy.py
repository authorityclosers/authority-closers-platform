"""Explicit policy for holding external side effects during recovery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from ac_platform.kernel.authz import ActorContext
from ac_platform.outbox.models import JobStatus


class ReconciliationRequiredError(RuntimeError):
    """An external side effect cannot run until recovery reconciliation occurs."""


@dataclass(frozen=True, slots=True)
class SideEffectHoldPolicy:
    """Policy object shared by job creation and restore reconciliation.

    The local flag is an additional fail-closed gate. The durable recovery
    generation remains authoritative and cannot be bypassed by setting this
    flag false.
    """

    hold_new_jobs: bool = True
    restore_reason: str = "database_restore_requires_reconciliation"

    def __post_init__(self) -> None:
        if not self.restore_reason.strip():
            raise ValueError("restore_reason must not be blank")

    def initial_status(self, *, external_side_effect: bool) -> JobStatus:
        """Return the initial state for a newly created job."""

        if external_side_effect and self.hold_new_jobs:
            return JobStatus.HELD
        return JobStatus.QUEUED

    def status_after_restore(self) -> JobStatus:
        """Return the only safe state for work found after a restore."""

        return JobStatus.HELD

    def require_reconciliation(self, actor: ActorContext) -> None:
        """Require the named operations permission for release decisions."""

        actor.require_permission("recovery_reconcile")

    def assert_reconciled(self, *, status: JobStatus | str) -> None:
        """Reject attempts to execute a held job before explicit release."""

        if status == JobStatus.HELD or status == JobStatus.HELD.value:
            raise ReconciliationRequiredError(
                "external side effect is held until named operations reconciliation"
            )

    @staticmethod
    def normalize_reconciliation_reason(reason: str) -> str:
        normalized = reason.strip()
        if not normalized:
            raise ValueError("reconciliation reason must not be blank")
        if len(normalized) > 500:
            raise ValueError("reconciliation reason must be at most 500 characters")
        return normalized


ExternalSideEffectHoldPolicy = SideEffectHoldPolicy


def recovery_hold_timestamp(value: datetime | None = None) -> datetime:
    """Normalize an optional recovery timestamp to aware UTC."""

    timestamp = value or datetime.now(UTC)
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)


def recovery_actor_id(actor: ActorContext) -> UUID:
    """Return the attributable person identifier for reconciliation metadata."""

    return actor.person_id


__all__ = [
    "ExternalSideEffectHoldPolicy",
    "ReconciliationRequiredError",
    "SideEffectHoldPolicy",
    "recovery_actor_id",
    "recovery_hold_timestamp",
]
