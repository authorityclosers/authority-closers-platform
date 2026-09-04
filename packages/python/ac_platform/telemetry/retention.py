"""Durable, explicitly composed retention and account-deletion hooks.

Telemetry expiry is maintenance work.  It must run from a durable scheduler
or worker inside a caller-owned transaction; serving a learner read never
authorizes a retention mutation.  The policy is deliberately explicit and
limited to disposable product analytics.  Legal-retention records require a
separate controlled workflow and fail closed at this boundary.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransactionOrigin

from ac_platform.identity.models import DeletionRequest, DeletionRequestStatus
from ac_platform.learning.planning_models import AnalyticsEvent
from ac_platform.learning.planning_repository import PlanningRepository
from ac_platform.telemetry.ingest import MAX_RETENTION_DAYS, TELEMETRY_PURPOSE

_POLICY_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MAX_BATCH_SIZE = 10_000


class TelemetryRetentionPolicyUnavailable(RuntimeError):
    """Retention or deletion was not backed by an approved policy."""


class TelemetryRetentionTransactionRequired(RuntimeError):
    """A maintenance operation was called without an outer transaction."""


class TelemetryAccountDeletionAction(StrEnum):
    """Explicit action selected by the account-deletion policy owner."""

    PURGE = "purge"
    ANONYMIZE = "anonymize"


@dataclass(frozen=True, slots=True)
class TelemetryRetentionPolicy:
    """A policy for the disposable product-analytics retention class.

    ``legal_retention`` is intentionally not interpreted as permission to
    keep or delete rows.  Marking it true routes the operation to a separate
    controlled legal-retention workflow and this slice refuses to act.
    """

    policy_id: str
    retention_days: int
    account_deletion_action: TelemetryAccountDeletionAction | None = None
    purpose: str = TELEMETRY_PURPOSE
    legal_retention: bool = False

    def validate(self) -> None:
        normalized_policy_id = self.policy_id.strip()
        if normalized_policy_id != self.policy_id or not _POLICY_ID_PATTERN.fullmatch(
            normalized_policy_id
        ):
            raise TelemetryRetentionPolicyUnavailable(
                "an explicit bounded telemetry retention policy id is required"
            )
        if not 1 <= self.retention_days <= MAX_RETENTION_DAYS:
            raise TelemetryRetentionPolicyUnavailable(
                "telemetry retention days are outside the approved bounded range"
            )
        if self.purpose != TELEMETRY_PURPOSE:
            raise TelemetryRetentionPolicyUnavailable(
                "this retention boundary only handles disposable product analytics"
            )
        if self.account_deletion_action is not None and not isinstance(
            self.account_deletion_action, TelemetryAccountDeletionAction
        ):
            raise TelemetryRetentionPolicyUnavailable(
                "account-deletion action must use the controlled policy enum"
            )
        if self.legal_retention:
            raise TelemetryRetentionPolicyUnavailable(
                "legal-retention records require a separate controlled workflow"
            )


@dataclass(frozen=True, slots=True)
class TelemetryRetentionResult:
    """One bounded durable expiry pass."""

    policy_id: str
    deleted: int


@dataclass(frozen=True, slots=True)
class TelemetryAccountDeletionResult:
    """One bounded account-deletion privacy pass.

    ``has_more`` is an explicit durable-continuation signal.  It remains true
    for rows not acquired by a ``SKIP LOCKED`` pass so the identity workflow
    cannot mark the deletion complete while privacy work is still pending.
    """

    policy_id: str
    action: TelemetryAccountDeletionAction
    purged: int = 0
    anonymized: int = 0
    already_anonymized: int = 0
    has_more: bool = False

    @property
    def affected(self) -> int:
        return self.purged + self.anonymized + self.already_anonymized


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _require_async_transaction(session: AsyncSession) -> None:
    transaction = session.get_transaction()
    sync_transaction = None if transaction is None else transaction.sync_transaction
    if sync_transaction is None or sync_transaction.origin is not SessionTransactionOrigin.BEGIN:
        raise TelemetryRetentionTransactionRequired(
            "telemetry maintenance requires an explicit caller-owned transaction"
        )


def _require_sync_transaction(database: Session) -> None:
    transaction = database.get_transaction()
    if transaction is None or transaction.origin is not SessionTransactionOrigin.BEGIN:
        raise TelemetryRetentionTransactionRequired(
            "telemetry maintenance requires an explicit caller-owned transaction"
        )


class TelemetryRetentionJob:
    """Durable scheduler seam for one bounded expiry pass.

    The application does not run this job on a read path.  A deployment may
    invoke ``run`` from its existing durable worker/scheduler after composing
    an approved policy and distributed ownership/quota controls.
    """

    name = "telemetry.product_analytics.retention"

    def __init__(
        self,
        *,
        policy: TelemetryRetentionPolicy | None,
        batch_size: int = 1_000,
    ) -> None:
        if not 1 <= batch_size <= _MAX_BATCH_SIZE:
            raise ValueError("batch_size must be between 1 and 10000")
        self._policy = policy
        self._batch_size = batch_size

    def run_sync(
        self,
        database: Session,
        *,
        now: datetime,
        tenant_id: UUID | None = None,
    ) -> TelemetryRetentionResult:
        """Run a policy-scoped delete in an existing synchronous transaction."""

        _require_sync_transaction(database)
        policy = self._policy
        if policy is None:
            raise TelemetryRetentionPolicyUnavailable(
                "an explicit telemetry retention policy is required"
            )
        policy.validate()
        deleted = PlanningRepository().purge_expired_analytics_batch(
            database,
            retention_policy_id=policy.policy_id,
            now=_as_utc(now),
            batch_size=self._batch_size,
            tenant_id=tenant_id,
        )
        return TelemetryRetentionResult(policy_id=policy.policy_id, deleted=deleted)

    async def run(
        self,
        session: AsyncSession,
        *,
        now: datetime,
        tenant_id: UUID | None = None,
    ) -> TelemetryRetentionResult:
        """Run one durable expiry pass from an async worker transaction."""

        _require_async_transaction(session)
        return await session.run_sync(
            lambda database: self.run_sync(database, now=now, tenant_id=tenant_id)
        )


async def run_telemetry_retention_job(
    session: AsyncSession,
    *,
    policy: TelemetryRetentionPolicy | None,
    now: datetime,
    batch_size: int = 1_000,
    tenant_id: UUID | None = None,
) -> TelemetryRetentionResult:
    """Functional scheduler seam kept for worker integrations."""

    return await TelemetryRetentionJob(policy=policy, batch_size=batch_size).run(
        session,
        now=now,
        tenant_id=tenant_id,
    )


def _anonymized_trace_id(*, tenant_id: UUID, event_id: str, deletion_request_id: UUID) -> str:
    digest = hashlib.sha256(
        f"{tenant_id}:{event_id}:{deletion_request_id}".encode("ascii")
    ).hexdigest()[:48]
    return f"anonymized-{digest}"


class TelemetryAccountDeletionHook:
    """Explicit privacy hook for the identity deletion orchestrator.

    The hook requires a persisted processing/completed deletion request and
    the exact person scope.  It acts only on the configured disposable
    analytics policy.  ``ANONYMIZE`` clears client payload and request-bound
    metadata while retaining the immutable tenant/person foreign-key shape;
    ``PURGE`` removes the rows.  No action is taken for a legal-retention
    policy.
    """

    def __init__(
        self,
        *,
        policy: TelemetryRetentionPolicy | None,
        batch_size: int = _MAX_BATCH_SIZE,
    ) -> None:
        if not 1 <= batch_size <= _MAX_BATCH_SIZE:
            raise ValueError("batch_size must be between 1 and 10000")
        self._policy = policy
        self._batch_size = batch_size

    def _validated_policy(self) -> TelemetryRetentionPolicy:
        policy = self._policy
        if policy is None:
            raise TelemetryRetentionPolicyUnavailable(
                "an explicit telemetry deletion policy is required"
            )
        policy.validate()
        if policy.account_deletion_action is None:
            raise TelemetryRetentionPolicyUnavailable(
                "an explicit account-deletion purge or anonymization action is required"
            )
        return policy

    @staticmethod
    def _require_deletion_request(
        database: Session,
        *,
        deletion_request_id: UUID,
        person_id: UUID,
        tenant_id: UUID | None,
    ) -> DeletionRequest:
        request = database.scalar(
            select(DeletionRequest)
            .where(DeletionRequest.id == deletion_request_id)
            .with_for_update()
        )
        if request is None or request.person_id != person_id:
            raise TelemetryRetentionPolicyUnavailable(
                "a matching account-deletion request is required"
            )
        if request.status not in {
            DeletionRequestStatus.PROCESSING.value,
            DeletionRequestStatus.COMPLETED.value,
        }:
            raise TelemetryRetentionPolicyUnavailable(
                "telemetry privacy runs only during an authorized deletion"
            )
        if request.tenant_id is not None and request.tenant_id != tenant_id:
            raise TelemetryRetentionPolicyUnavailable(
                "the deletion request tenant scope does not match"
            )
        return request

    def apply_sync(
        self,
        database: Session,
        *,
        deletion_request_id: UUID,
        person_id: UUID,
        tenant_id: UUID | None,
        now: datetime,
    ) -> TelemetryAccountDeletionResult:
        """Apply one explicit deletion/anonymization pass in a transaction."""

        del now  # Kept in the seam for audit/retention orchestration symmetry.
        _require_sync_transaction(database)
        policy = self._validated_policy()
        action = policy.account_deletion_action
        assert action is not None
        self._require_deletion_request(
            database,
            deletion_request_id=deletion_request_id,
            person_id=person_id,
            tenant_id=tenant_id,
        )
        scope_filters = (
            AnalyticsEvent.retention_policy_id == policy.policy_id,
            or_(
                AnalyticsEvent.actor_person_id == person_id,
                AnalyticsEvent.subject_person_id == person_id,
            ),
        )
        statement = (
            select(AnalyticsEvent)
            .where(*scope_filters)
            .order_by(AnalyticsEvent.tenant_id, AnalyticsEvent.event_id)
            .with_for_update(skip_locked=True)
        )
        if tenant_id is not None:
            statement = statement.where(AnalyticsEvent.tenant_id == tenant_id)
        if action is TelemetryAccountDeletionAction.ANONYMIZE:
            statement = statement.where(~AnalyticsEvent.trace_id.like("anonymized-%"))
        statement = statement.limit(self._batch_size)
        rows = tuple(database.scalars(statement))
        purged = 0
        anonymized = 0
        already_anonymized = 0
        if action is TelemetryAccountDeletionAction.ANONYMIZE and not rows:
            already_statement = (
                select(AnalyticsEvent)
                .where(*scope_filters, AnalyticsEvent.trace_id.like("anonymized-%"))
                .order_by(AnalyticsEvent.tenant_id, AnalyticsEvent.event_id)
                .limit(self._batch_size)
                .with_for_update(skip_locked=True)
            )
            if tenant_id is not None:
                already_statement = already_statement.where(AnalyticsEvent.tenant_id == tenant_id)
            already_anonymized = len(tuple(database.scalars(already_statement)))
        if action is TelemetryAccountDeletionAction.PURGE:
            for row in rows:
                database.delete(row)
                purged += 1
        else:
            for row in rows:
                marker = _anonymized_trace_id(
                    tenant_id=row.tenant_id,
                    event_id=row.event_id,
                    deletion_request_id=deletion_request_id,
                )
                if (
                    row.trace_id == marker
                    and row.payload == {}
                    and row.route is None
                    and row.session_id is None
                ):
                    already_anonymized += 1
                    continue
                row.payload = {}
                row.route = None
                row.session_id = None
                row.trace_id = marker
                anonymized += 1
        if rows:
            database.flush()
        # Probe without ``skip_locked`` after the bounded pass.  This is a
        # continuation signal, not a read-path mutation: rows still held by a
        # concurrent worker remain visible here even when the bounded select
        # skipped them.  The identity orchestrator must keep the deletion
        # request processing until a later attempt can drain that work.
        more_statement = select(AnalyticsEvent.event_id).where(*scope_filters)
        if tenant_id is not None:
            more_statement = more_statement.where(AnalyticsEvent.tenant_id == tenant_id)
        if action is TelemetryAccountDeletionAction.ANONYMIZE:
            more_statement = more_statement.where(~AnalyticsEvent.trace_id.like("anonymized-%"))
        has_more = database.scalar(more_statement.limit(1)) is not None
        return TelemetryAccountDeletionResult(
            policy_id=policy.policy_id,
            action=action,
            purged=purged,
            anonymized=anonymized,
            already_anonymized=already_anonymized,
            has_more=has_more,
        )

    async def apply(
        self,
        session: AsyncSession,
        *,
        deletion_request_id: UUID,
        person_id: UUID,
        tenant_id: UUID | None,
        now: datetime,
    ) -> TelemetryAccountDeletionResult:
        """Apply the hook from an identity transaction."""

        _require_async_transaction(session)
        return await session.run_sync(
            lambda database: self.apply_sync(
                database,
                deletion_request_id=deletion_request_id,
                person_id=person_id,
                tenant_id=tenant_id,
                now=now,
            )
        )


__all__ = [
    "TelemetryAccountDeletionAction",
    "TelemetryAccountDeletionHook",
    "TelemetryAccountDeletionResult",
    "TelemetryRetentionJob",
    "TelemetryRetentionPolicy",
    "TelemetryRetentionPolicyUnavailable",
    "TelemetryRetentionResult",
    "TelemetryRetentionTransactionRequired",
    "run_telemetry_retention_job",
]
