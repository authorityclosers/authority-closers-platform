"""Append-only, tenant-bound audit evidence with an integrity chain."""

from ac_platform.audit.models import (
    GENESIS_HASH,
    AuditChainHead,
    AuditEvent,
    AuditMutationError,
    audit_control_metadata,
)
from ac_platform.audit.service import (
    AuditChainVerification,
    AuditIntegrityError,
    AuditRepository,
    append_audit_event,
    append_for_actor,
    build_audit_head_append_statement,
    build_audit_tenant_lock_statement,
    canonical_audit_bytes,
    compute_audit_hash,
    is_audit_chain_valid,
    verify_audit_chain,
    verify_audit_chain_sync,
)

__all__ = [
    "AuditChainVerification",
    "AuditChainHead",
    "AuditEvent",
    "AuditIntegrityError",
    "AuditMutationError",
    "AuditRepository",
    "GENESIS_HASH",
    "append_audit_event",
    "append_for_actor",
    "audit_control_metadata",
    "build_audit_tenant_lock_statement",
    "build_audit_head_append_statement",
    "canonical_audit_bytes",
    "compute_audit_hash",
    "is_audit_chain_valid",
    "verify_audit_chain",
    "verify_audit_chain_sync",
]
