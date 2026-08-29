from __future__ import annotations


class DomainError(Exception):
    """Expected domain rejection safe to map to a bounded public problem."""

    code = "domain_rejected"
    title = "The requested operation was rejected"
    status = 422

    def __init__(self, detail: str = "The operation violates a domain invariant.") -> None:
        super().__init__(detail)
        self.detail = detail


class AuthorizationDenied(DomainError):
    code = "authorization_denied"
    title = "Permission denied"
    status = 403


class ResourceConflict(DomainError):
    code = "resource_conflict"
    title = "The resource changed"
    status = 409


class ResourceNotFound(DomainError):
    code = "resource_not_found"
    title = "Resource not found"
    status = 404


class InvalidEvidence(DomainError):
    code = "invalid_evidence"
    title = "Evidence was not accepted"
    status = 422
