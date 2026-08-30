"""Compatibility import surface for audit event callers."""

from ac_platform.audit.models import GENESIS_HASH, AuditChainHead, AuditEvent, AuditMutationError
from ac_platform.audit.service import (
    AuditChainVerification,
    AuditIntegrityError,
    AuditRepository,
    append_audit_event,
    append_for_actor,
    build_audit_tenant_lock_statement,
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
    "build_audit_tenant_lock_statement",
    "compute_audit_hash",
    "is_audit_chain_valid",
    "verify_audit_chain",
    "verify_audit_chain_sync",
]
