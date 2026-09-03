"""Durable transactional outbox and job primitives.

The outbox records an intent in the same transaction as canonical state. Jobs
then provide the retry, lease, and recovery boundary for work that may have an
external side effect. This package deliberately has no provider SDK or HTTP
dependency.
"""

from ac_platform.outbox.models import (
    Job,
    JobStatus,
    OperationsRecoveryState,
    OutboxEvent,
    OutboxEventStatus,
    RecoveryStatus,
    operations_control_metadata,
    utc_now,
)
from ac_platform.outbox.policy import (
    ExternalSideEffectHoldPolicy,
    ReconciliationRequiredError,
    SideEffectHoldPolicy,
)
from ac_platform.outbox.repository import (
    MAX_JOB_LEASE,
    DuplicateIntentError,
    JobRepository,
    JobStateError,
    LeaseLostError,
    OutboxJobRoute,
    OutboxRepository,
    RecoveryStateRepository,
    RetryPolicy,
    build_job_acknowledge_statement,
    build_job_ambiguity_statement,
    build_job_dispatch_statement,
    build_job_exhausted_statement,
    build_job_failure_statement,
    build_job_receipt_statement,
    build_job_renew_statement,
    build_job_take_statement,
    canonical_receipt_digest,
    mark_database_restore,
    reconcile_operations,
    reconcile_recovery_state,
)

__all__ = [
    "DuplicateIntentError",
    "ExternalSideEffectHoldPolicy",
    "Job",
    "JobRepository",
    "JobStateError",
    "JobStatus",
    "LeaseLostError",
    "MAX_JOB_LEASE",
    "OperationsRecoveryState",
    "OutboxJobRoute",
    "OutboxEvent",
    "OutboxEventStatus",
    "OutboxRepository",
    "RecoveryStateRepository",
    "RecoveryStatus",
    "ReconciliationRequiredError",
    "RetryPolicy",
    "build_job_acknowledge_statement",
    "build_job_ambiguity_statement",
    "build_job_dispatch_statement",
    "build_job_exhausted_statement",
    "build_job_failure_statement",
    "build_job_receipt_statement",
    "build_job_renew_statement",
    "build_job_take_statement",
    "canonical_receipt_digest",
    "mark_database_restore",
    "operations_control_metadata",
    "reconcile_operations",
    "reconcile_recovery_state",
    "SideEffectHoldPolicy",
    "utc_now",
]
